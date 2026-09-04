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


def _quieten(conn, editor, machine):
    """Take a registry row off the air, which is what a rename does to the old
    hostname: the computer reboots to take its new name and never reports
    under the old one again. Since SYS-18a (2026-08-29) that silence is what
    tells the adoption path a rename from a cloned disk, so a rename test has
    to spell it out rather than fire two reports in the same millisecond."""
    conn.execute("UPDATE machines SET last_seen='2026-08-18T09:00:00+00:00' "
                 "WHERE editor_username=? AND machine=?", (editor, machine))
    conn.commit()


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
    computer with an empty plan -- a machine that silently stops syncing.

    The old row is taken off the air first (SYS-18a, 2026-08-29): a rename is
    one computer with two names over TIME, so the adoption now happens only
    when the old hostname has gone quiet. Two reports a millisecond apart are
    the disk-clone shape, and are refused."""
    client, conn, _now = env
    report(client, "ruskin", "DESKTOP-1", machine_id="mid-1")
    client.put("/api/v1/selection/ruskin/p1?machine=DESKTOP-1")
    _quieten(conn, "ruskin", "DESKTOP-1")

    report(client, "ruskin", "RUSKIN-PC", machine_id="mid-1")

    assert [m["machine"] for m in dbmod.fetch_machines(conn, "ruskin")] == ["RUSKIN-PC"]
    assert [s["slug"] for s in dbmod.selections_for_machine(conn, "ruskin", "RUSKIN-PC")] == ["p1"]


def test_a_rename_onto_another_live_computers_name_destroys_neither_plan(env):
    """ultrareview 2026-08-19. adopt_renamed_machine DELETEd whatever sat at
    the new name before moving the old rows across, so an editor who renamed
    PC B to PC A's old name (or restored an image carrying A's machine.json
    onto a box called B) silently lost B's plan, and upsert_machine then
    wrote A's identity over B's. MULTI_MACHINE_PLAN.md §6's "solved by
    construction" was not: every table but the registry is keyed on the
    hostname. Both plans must survive; the collision is an admin's call."""
    client, conn, _now = env
    report(client, "ruskin", "DESKTOP-1", machine_id="mid-1", syncthing_device_id="DEV-A")
    report(client, "ruskin", "WORK-PC", machine_id="mid-2", syncthing_device_id="DEV-B")
    client.put("/api/v1/selection/ruskin/p1?machine=DESKTOP-1")
    client.put("/api/v1/selection/ruskin/p2?machine=WORK-PC")

    # DESKTOP-1 comes back calling itself WORK-PC. Quietened first so this
    # still exercises the TAKEN-NAME refusal and not SYS-18a's clone refusal
    # one branch above it, which would pass this test for another reason.
    _quieten(conn, "ruskin", "DESKTOP-1")
    report(client, "ruskin", "WORK-PC", machine_id="mid-1", syncthing_device_id="DEV-A")

    # Nothing was deleted: WORK-PC's plan is still p2, DESKTOP-1's still p1.
    assert [s["slug"] for s in dbmod.selections_for_machine(conn, "ruskin", "WORK-PC")] == ["p2"]
    assert [s["slug"] for s in dbmod.selections_for_machine(conn, "ruskin", "DESKTOP-1")] == ["p1"]
    assert sorted(m["machine"] for m in dbmod.fetch_machines(conn, "ruskin")) == \
        ["DESKTOP-1", "WORK-PC"]

    # ...and the next report from the same machine does not thrash: it is
    # the most recently heard-from holder of mid-1, so no rename branch.
    report(client, "ruskin", "WORK-PC", machine_id="mid-1", syncthing_device_id="DEV-A")
    assert [s["slug"] for s in dbmod.selections_for_machine(conn, "ruskin", "WORK-PC")] == ["p2"]
    assert [s["slug"] for s in dbmod.selections_for_machine(conn, "ruskin", "DESKTOP-1")] == ["p1"]


def test_adopt_renamed_machine_refuses_a_taken_name(env):
    """The unit behind the test above: the registry row at the new name is
    the whole test. A name nobody holds is adopted as before."""
    client, conn, now = env
    dbmod.upsert_machine(conn, "ruskin", "OLD", now, machine_id="mid-1")
    dbmod.add_selection(conn, "ruskin", "p1", "admin", now, machine="OLD")
    dbmod.upsert_machine(conn, "ruskin", "TAKEN", now, machine_id="mid-2")
    dbmod.add_selection(conn, "ruskin", "p2", "admin", now, machine="TAKEN")
    conn.commit()

    assert dbmod.adopt_renamed_machine(conn, "ruskin", "OLD", "TAKEN") is False
    assert [s["slug"] for s in dbmod.selections_for_machine(conn, "ruskin", "TAKEN")] == ["p2"]
    assert [s["slug"] for s in dbmod.selections_for_machine(conn, "ruskin", "OLD")] == ["p1"]

    assert dbmod.adopt_renamed_machine(conn, "ruskin", "OLD", "FRESH") is True
    assert [s["slug"] for s in dbmod.selections_for_machine(conn, "ruskin", "FRESH")] == ["p1"]
    assert dbmod.selections_for_machine(conn, "ruskin", "OLD") == []


def test_adopt_onto_the_same_computers_own_empty_row_is_allowed(env):
    """The unit behind SYS-18a's deferred adoption (2026-08-29). A rename is
    refused at first sight, which REGISTERS the new hostname, so by the time
    the rename is confirmed the new name is "taken" - by the very row the
    refusal created. `same_computer=True` replaces the existence test with
    the thing it was protecting: a row with a plan or a sticky root of its own
    is a different computer and is still refused, so nothing can be
    destroyed."""
    client, conn, now = env
    dbmod.upsert_machine(conn, "ruskin", "OLD", now, machine_id="mid-1")
    dbmod.add_selection(conn, "ruskin", "p1", "admin", now, machine="OLD")
    # The row the refusal left behind: registered, and empty.
    dbmod.upsert_machine(conn, "ruskin", "NEW", now, machine_id="mid-1")
    conn.commit()

    assert dbmod.adopt_renamed_machine(conn, "ruskin", "OLD", "NEW") is False
    assert dbmod.adopt_renamed_machine(conn, "ruskin", "OLD", "NEW",
                                       same_computer=True) is True
    assert [s["slug"] for s in dbmod.selections_for_machine(conn, "ruskin", "NEW")] == ["p1"]
    assert [m["machine"] for m in dbmod.fetch_machines(conn, "ruskin")] == ["NEW"]


def test_adopt_never_lands_on_a_row_that_has_a_plan_of_its_own(env):
    """...and the guard that makes the line above safe. Same shape, except
    somebody ticked a project for the new name in the meantime."""
    client, conn, now = env
    dbmod.upsert_machine(conn, "ruskin", "OLD", now, machine_id="mid-1")
    dbmod.add_selection(conn, "ruskin", "p1", "admin", now, machine="OLD")
    dbmod.upsert_machine(conn, "ruskin", "NEW", now, machine_id="mid-1")
    dbmod.add_selection(conn, "ruskin", "p2", "admin", now, machine="NEW")
    conn.commit()

    assert dbmod.adopt_renamed_machine(conn, "ruskin", "OLD", "NEW",
                                       same_computer=True) is False
    assert [s["slug"] for s in dbmod.selections_for_machine(conn, "ruskin", "NEW")] == ["p2"]
    assert [s["slug"] for s in dbmod.selections_for_machine(conn, "ruskin", "OLD")] == ["p1"]


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
    the bucket -- that would make "untick this on the laptop" impossible.

    Its first own row COPIES the bucket across first, though (dash-core-1),
    so what it inherited is kept and can then be unticked one project at a
    time."""
    client, conn, now = env
    report(client, "ruskin", "DESKTOP-1")
    report(client, "ruskin", "LAPTOP-1")
    dbmod.add_selection(conn, "ruskin", "p1", "seed", now)          # bucket
    dbmod.add_selection(conn, "ruskin", "p2", "admin", now, machine="LAPTOP-1")
    conn.commit()

    assert [s["slug"] for s in dbmod.selections_for_machine(conn, "ruskin", "DESKTOP-1")] == ["p1"]
    laptop = [s["slug"] for s in dbmod.selections_for_machine(conn, "ruskin", "LAPTOP-1")]
    assert sorted(laptop) == ["p1", "p2"]
    # ...and the bucket itself is untouched, so the OTHER computer keeps it.
    assert dbmod.remove_selection(conn, "ruskin", "p1", machine="LAPTOP-1") is True
    assert [s["slug"] for s in dbmod.selections_for_machine(conn, "ruskin", "LAPTOP-1")] == ["p2"]
    assert [s["slug"] for s in dbmod.selections_for_machine(conn, "ruskin", "DESKTOP-1")] == ["p1"]


# -- dash-core-1: a tick must not eclipse what the machine was inheriting ----


def test_a_tick_keeps_the_projects_the_machine_was_inheriting(env):
    """The bucket is the normal onboarding state: an admin ticks projects for
    a new editor before their companion has ever reported. Ticking one more a
    day later used to leave that machine's plan as exactly that one project,
    and the next enforce cycle unshared the rest."""
    client, conn, now = env
    dbmod.add_selection_for_person(conn, "newbie", "p1", "owen", now)   # no machine yet
    conn.commit()
    assert dbmod.selections_for_machine(conn, "newbie", "") != []

    report(client, "newbie", "LAPTOP")                                  # first report
    assert [s["slug"] for s in dbmod.selections_for_machine(conn, "newbie", "LAPTOP")] == ["p1"]

    r = client.put("/api/v1/selection/newbie/p2")                       # person-level tick
    assert r.status_code == 200, r.text
    plan = [s["slug"] for s in dbmod.selections_for_machine(conn, "newbie", "LAPTOP")]
    assert sorted(plan) == ["p1", "p2"]
    # ...and the enforce cycle's view agrees: the share is still made.
    assert ("newbie", "LAPTOP") in dbmod.fetch_machine_selections(conn)["p1"]


def test_unticking_an_inherited_project_on_one_machine_takes(env):
    """DELETE ...?machine=X used to delete 0 rows and answer changed=false
    while the project kept syncing (dash-core-1)."""
    client, conn, now = env
    dbmod.add_selection_for_person(conn, "newbie", "p1", "owen", now)
    dbmod.add_selection_for_person(conn, "newbie", "p2", "owen", now)
    conn.commit()
    report(client, "newbie", "LAPTOP")

    r = client.delete("/api/v1/selection/newbie/p1?machine=LAPTOP")
    assert r.status_code == 200 and r.json()["changed"] is True
    assert [s["slug"] for s in dbmod.selections_for_machine(conn, "newbie", "LAPTOP")] == ["p2"]


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


def test_the_packages_page_update_button_names_a_computer_it_did_not_find(env):
    """UX-20 ("Same for partial_admin_machine_update if it has the same
    shape", resilience sweep 2026-08-28): the Settings -> Packages page's
    own [ UPDATE NOW ] posts to this htmx partial, not the JSON route
    above."""
    client, _conn, _now = env
    resp = client.post("/partials/admin/machines/update",
                       data={"editor": "ruskin", "machine": "GHOST"})
    assert resp.status_code == 200
    # Jinja autoescapes the quotes in repr() output.
    assert ("no computer" in resp.text and "GHOST" in resp.text
            and "ruskin" in resp.text)


# -- resuming proxy download from the dashboard (v26, CR-45) ----------------
#
# The lane B breaker could only ever be cleared at the editor's own tray, so
# a machine that tripped one sat with proxy download stopped until its owner
# was next at the keyboard -- ruskin's PC spent a day like that on
# 2026-08-19, over a folder move that had deleted nothing.


def _guard(tripped, reason="the NAS listed the tree as empty"):
    return {"lane_b_breaker": {"tripped": tripped, "reason": reason if tripped else None,
                               "tripped_at": "2026-08-19T17:49:58+00:00" if tripped else None}}


def test_an_admin_can_ask_one_machine_to_resume_proxy_download(env):
    client, _conn, _now = env
    report(client, "ruskin", "DESKTOP-1", sync_guard=_guard(True))

    r = client.post("/api/v1/admin/machines/ruskin/DESKTOP-1/resume-lane-b")
    assert r.status_code == 200, r.text

    reply = report(client, "ruskin", "DESKTOP-1", sync_guard=_guard(True))
    command = reply["commands"]["resume_lane_b"]
    assert command["apply"] is True
    assert command["requested_by"] == "owen"


def test_the_request_is_delivered_exactly_once(env):
    """ONE CLICK, ONE RESUME (comp-lanes-ab-2, 2026-08-21).

    A standing request re-armed the breaker on every report, so a pass that
    re-tripped inside the report interval was resumed again, and again: one
    admin click became an unbounded sequence of deleting passes, which is
    the exact failure the breaker exists to stop."""
    client, conn, _now = env
    report(client, "ruskin", "DESKTOP-1", sync_guard=_guard(True))
    client.post("/api/v1/admin/machines/ruskin/DESKTOP-1/resume-lane-b")

    reply = report(client, "ruskin", "DESKTOP-1", sync_guard=_guard(True))
    assert reply["commands"]["resume_lane_b"]["apply"] is True
    assert dbmod.lane_b_resume_request(conn, "ruskin", "DESKTOP-1") is None

    # The machine re-trips seconds later, before any report: NOT resumed again.
    reply = report(client, "ruskin", "DESKTOP-1", sync_guard=_guard(True))
    assert "resume_lane_b" not in reply["commands"]


def test_the_command_carries_the_stamp_the_companion_dedupes_on(env):
    """The companion refuses to apply the same requested_at twice, so a
    redelivered reply cannot clear a later trip."""
    client, conn, _now = env
    report(client, "ruskin", "DESKTOP-1", sync_guard=_guard(True))
    client.post("/api/v1/admin/machines/ruskin/DESKTOP-1/resume-lane-b")

    command = report(client, "ruskin", "DESKTOP-1",
                     sync_guard=_guard(True))["commands"]["resume_lane_b"]
    assert command["requested_by"] == "owen"
    assert command["requested_at"]


def test_the_request_is_dropped_when_the_machine_reports_it_already_resumed(env):
    client, conn, _now = env
    report(client, "ruskin", "DESKTOP-1", sync_guard=_guard(True))
    client.post("/api/v1/admin/machines/ruskin/DESKTOP-1/resume-lane-b")

    reply = report(client, "ruskin", "DESKTOP-1", sync_guard=_guard(False))
    assert "resume_lane_b" not in reply["commands"]
    assert dbmod.lane_b_resume_request(conn, "ruskin", "DESKTOP-1") is None


def test_a_companion_too_old_to_send_a_guard_section_still_gets_it_once(env):
    """Otherwise "no guard" reads as "not tripped" and the admin's click is
    thrown away without ever reaching the machine."""
    client, conn, _now = env
    report(client, "ruskin", "DESKTOP-1", sync_guard=_guard(True))
    client.post("/api/v1/admin/machines/ruskin/DESKTOP-1/resume-lane-b")

    reply = report(client, "ruskin", "DESKTOP-1")           # no sync_guard at all
    assert reply["commands"]["resume_lane_b"]["apply"] is True
    assert dbmod.lane_b_resume_request(conn, "ruskin", "DESKTOP-1") is None


def test_a_machine_that_is_not_parked_cannot_be_pre_armed(env):
    """A request armed before the trip is a decision about a trip nobody has
    seen: an offline machine's first report would auto-resume whatever it
    tripped on, days later (comp-lanes-ab-2)."""
    client, conn, _now = env
    report(client, "ruskin", "DESKTOP-1", sync_guard=_guard(False))

    r = client.post("/api/v1/admin/machines/ruskin/DESKTOP-1/resume-lane-b")
    assert r.status_code == 409, r.text
    assert "nothing to resume" in r.json()["detail"]
    assert dbmod.lane_b_resume_request(conn, "ruskin", "DESKTOP-1") is None

    # ...and a machine that has never sent a guard section at all is the same
    # answer: it has no breaker to clear.
    report(client, "leso", "MacBook")
    assert client.post(
        "/api/v1/admin/machines/leso/MacBook/resume-lane-b").status_code == 409


def test_resuming_an_unknown_machine_is_a_404(env):
    client, _conn, _now = env
    report(client, "ruskin", "DESKTOP-1")
    r = client.post("/api/v1/admin/machines/ruskin/NOPE/resume-lane-b")
    assert r.status_code == 404


def test_an_admin_can_withdraw_a_resume_request(env):
    client, conn, _now = env
    report(client, "ruskin", "DESKTOP-1", sync_guard=_guard(True))
    client.post("/api/v1/admin/machines/ruskin/DESKTOP-1/resume-lane-b")
    assert dbmod.lane_b_resume_request(conn, "ruskin", "DESKTOP-1") is not None

    r = client.request("DELETE", "/api/v1/admin/machines/ruskin/DESKTOP-1/resume-lane-b")
    assert r.status_code == 200
    assert dbmod.lane_b_resume_request(conn, "ruskin", "DESKTOP-1") is None

    reply = report(client, "ruskin", "DESKTOP-1", sync_guard=_guard(True))
    assert "resume_lane_b" not in reply["commands"]


def test_a_machine_with_no_request_is_told_nothing(env):
    client, _conn, _now = env
    reply = report(client, "ruskin", "DESKTOP-1", sync_guard=_guard(True))
    assert "resume_lane_b" not in reply["commands"]
    # ...and the halt, which is always present, still is.
    assert "halt" in reply["commands"]


def test_the_fleet_page_resume_button_names_a_computer_it_did_not_find(env):
    """UX-20 (resilience sweep 2026-08-28): the fleet grid's [ RESUME ]
    button posts to this htmx partial, not the JSON route above -- and used
    to re-render looking fine for a machine left open across a rename or a
    [ FORGET ], queuing nothing and leaving the editor's proxies stopped."""
    client, _conn, _now = env
    resp = client.post("/partials/admin/machines/resume-lane-b",
                       data={"editor": "ruskin", "machine": "GHOST"})
    assert resp.status_code == 200
    assert "no longer in the fleet" in resp.text
    assert "Reload the page" in resp.text

    # ...and a real, parked machine still resumes from the same route.
    report(client, "ruskin", "DESKTOP-1", sync_guard=_guard(True))
    resp = client.post("/partials/admin/machines/resume-lane-b",
                       data={"editor": "ruskin", "machine": "DESKTOP-1"})
    assert resp.status_code == 200
    assert "no longer in the fleet" not in resp.text
    reply = report(client, "ruskin", "DESKTOP-1", sync_guard=_guard(True))
    assert reply["commands"]["resume_lane_b"]["apply"] is True
