"""The 2026-09-18b mediums wave, dashboard api/db group (CR-297).

One test per finding, named for the behaviour it pins; the finding id is in
the docstring and at the code site.
"""
from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from ccsync_dashboard import auth
from ccsync_dashboard import db as dbmod
from ccsync_dashboard import provision
from ccsync_dashboard.app import create_app
from ccsync_dashboard.collector import Collector
from ccsync_dashboard.settings import Settings
from ccsync_dashboard.syncthing_client import SyncthingClient

SECRET = "test-secret"
TOKEN = "companion-token"
DRONE = "2026/Base Drone"
D_SLUG = "2026-base-drone"


# ---------------------------------------------------------------------------
# dash-api-2: one transient inventory error is not a life sentence
# ---------------------------------------------------------------------------


def test_a_project_that_could_not_be_read_once_is_walked_again(conn, tmp_path):
    """dash-api-2: `record_inventory_error` kept `tree_sig`, and the
    collector's phase 1 skips the walk whenever the directory signature
    matches the stored one. `_dir_signature` is directory mtimes only, so an
    archived project (the normal case) never produces a different one - the
    share blinks for one cycle, and `last_error` is stuck for ever, which
    `locate`'s `COALESCE(s.last_error,'') = ''` filter turns into "this
    project has no files" for every reader downstream."""
    projects = tmp_path / "projects"
    proj = projects / DRONE
    (proj / "B-roll").mkdir(parents=True)
    (proj / ".stfolder").mkdir()
    (proj / "B-roll" / "A001.braw").write_bytes(b"x" * 10)
    now = dbmod.utcnow_iso()
    dbmod.upsert_project(conn, D_SLUG, DRONE, f"/data/Projects/{DRONE}", now)
    conn.commit()

    # syncthing_url only to get past run_cycle's Syncthing-less short circuit:
    # the inventory walk itself never calls it.
    c = Collector(Settings(projects_dir=str(projects),
                           syncthing_url="http://127.0.0.1:1", syncthing_api_key="k"),
                  client=SyncthingClient("http://127.0.0.1:1", "k", timeout=1))
    c.run_cycle(conn, ["inventory"])
    pid = conn.execute("SELECT id FROM projects WHERE slug=?", (D_SLUG,)).fetchone()[0]
    good_sig = dbmod.nas_inventory_sig(conn, pid)
    assert good_sig and dbmod.fetch_nas_media_summary(conn, pid)["n_originals"] == 1

    # The share blinks: the dir is gone for exactly one cycle. A rename does
    # not touch the mtimes INSIDE the tree, so the signature that comes back
    # is the same one - which is the whole point of the finding.
    away = tmp_path / "away"
    proj.rename(away)
    c.run_cycle(conn, ["inventory"])
    row = conn.execute("SELECT last_error FROM nas_inventory_state WHERE project_id=?",
                       (pid,)).fetchone()
    assert row["last_error"]

    away.rename(proj)
    c.run_cycle(conn, ["inventory"])
    row = conn.execute("SELECT last_error FROM nas_inventory_state WHERE project_id=?",
                       (pid,)).fetchone()
    assert row["last_error"] is None
    assert dbmod.nas_inventory_sig(conn, pid) == good_sig


# ---------------------------------------------------------------------------
# dash-db-3: the admin's MOVE button asks the same predicate as the collector
# ---------------------------------------------------------------------------


@pytest.fixture
def move_env(tmp_path):
    projects = tmp_path / "Projects"
    d = projects / DRONE
    (d / "Gold_Card_Meetup").mkdir(parents=True)
    provision.write_marker(d, D_SLUG)
    (d / "Gold_Card_Meetup" / "A001.braw").write_bytes(b"braw")
    (d / "Dest").mkdir()

    settings = Settings(db_path=str(tmp_path / "moves.db"), session_secret=SECRET,
                        report_token=TOKEN, admin_users=frozenset({"owen"}),
                        projects_dir=str(projects))
    app = create_app(settings)
    with TestClient(app) as client:
        client.app.state.collector.stop()
        conn = dbmod.connect(tmp_path / "moves.db")
        now = dbmod.utcnow_iso()
        dbmod.upsert_project(conn, D_SLUG, DRONE, f"/data/{D_SLUG}", now)
        conn.commit()
        yield client, conn, projects
        conn.close()


def test_the_move_button_does_not_claim_a_lookalike_folders_machines(move_env):
    """dash-db-3: dash-db-4's LIKE escaping landed on
    `db.file_move_target_machines` (the DETECTED hand-move path) and missed
    the byte-for-byte copy of the same query in the admin's MOVE route, which
    is the path the button runs. `_` is a single-character wildcard, so
    moving `Gold_Card_Meetup` also matched the machine holding
    `Gold-Card-Meetup` and sent it a move command for a file it does not
    hold."""
    client, conn, projects = move_env
    now = dbmod.utcnow_iso()
    dbmod.replace_editor_media(conn, "jsmith", "EDIT-PC", D_SLUG,
                               [("Gold_Card_Meetup/A001.braw", "original", 4)], now)
    dbmod.replace_editor_media(conn, "ruskin", "DESK-1", D_SLUG,
                               [("Gold-Card-Meetup/A001.braw", "original", 4)], now)
    conn.commit()
    client.cookies.set(auth.COOKIE_NAME, auth.make_session_cookie(SECRET, "owen"))
    r = client.post(f"/api/v1/projects/{D_SLUG}/move", json={
        "path": "Gold_Card_Meetup", "to_slug": D_SLUG, "to_path": "Dest"})
    assert r.status_code == 200, r.text
    assert r.json()["machines"] == [{"editor": "jsmith", "machine": "EDIT-PC"}]


# ---------------------------------------------------------------------------
# dash-api-3 / CR-306: a push that cannot be sent no longer costs every job
# ---------------------------------------------------------------------------

NOW = "2026-09-18T12:00:00+00:00"


def _settings(tmp_path, **over):
    kwargs = dict(db_path=str(tmp_path / "push.db"), session_secret=SECRET,
                  report_token="r" * 30, admin_users=frozenset({"owen"}),
                  auth_method="local")
    kwargs.update(over)
    return Settings(**kwargs)


def _unofferable_push(tmp_path):
    """An arm64 0.9.74 made current, and a push of it at an x86_64 machine.

    The same scenario as res-fleet-2's own test: `_upgrade_info` withholds the
    build (wrong processor), so the command must not be sent - and after the
    report the machine must be back in the job fleet."""
    settings = _settings(tmp_path)
    app = create_app(settings)
    c = dbmod.connect(settings.db_path)
    dbmod.migrate(c)
    now = dbmod.utcnow_iso()
    dbmod.insert_companion_package(
        c, version="0.9.74", platform="windows", filename="c.exe",
        sha256="a" * 64, size_bytes=1, published_by="owen", now=now,
        kind="companion", signature="sig", pubkey_id="k", min_version="",
        signed_binary=False, requires_dashboard="", arch="arm64")
    dbmod.set_current_package(c, "windows", "0.9.74", "companion")
    dbmod.upsert_machine(c, "jsmith", "EDIT-PC", now)
    dbmod.request_machine_update(c, "jsmith", "EDIT-PC", "0.9.74", "owen", now)
    c.commit()
    return settings, app, c


def _report(app, version="0.9.70"):
    client = TestClient(app)
    return client.post("/api/v1/report", json={
        "editor_name": "jsmith", "machine": "EDIT-PC", "platform": "windows",
        "arch": "x86_64", "companion_version": version,
        "reported_at": NOW, "lanes": []},
        headers={"X-CCSync-Token": "r" * 30,
                 "X-CCSync-Identity": auth.make_identity_token(SECRET, "jsmith")},
    ).json()


def test_a_withheld_push_no_longer_costs_the_machine_every_job(tmp_path):
    """dash-api-3: res-fleet-2 withholds `commands.upgrade` for a build this
    machine is not being offered and LEAVES THE REQUEST STANDING, but
    `jobs.fleet_facts`/`machine_facts` read "upgrading" from
    `update_requested_version` alone and `policy_refusal` refuses every job
    kind to a machine that is upgrading - so the computer was out of the
    whisper/proxy/audio-extract/peaks fleet for the 14 days until the request
    expired, and nothing told the admin."""
    from ccsync_dashboard import jobs

    settings, app, c = _unofferable_push(tmp_path)
    # BEFORE the report the verdict is undecided, and undecided is upgrading:
    # fail closed, because the upgrade may really be about to happen.
    # (fleet_facts is asked below, after the report: it walks `machine_state`,
    # and this machine has not reported yet.)
    assert jobs.machine_facts(c, "jsmith", "EDIT-PC")["upgrading"] is True
    c.close()

    reply = _report(app)
    assert "upgrade" not in reply.get("commands", {})
    assert "processor" in reply.get("upgrade_none_reason", "")

    c = dbmod.connect(settings.db_path)
    request = dbmod.machine_update_request(c, "jsmith", "EDIT-PC")
    assert request is not None and request["version"] == "0.9.74"
    assert "processor" in request["withheld"]
    assert jobs.machine_facts(c, "jsmith", "EDIT-PC")["upgrading"] is False
    assert jobs.fleet_facts(c)[("jsmith", "EDIT-PC")]["upgrading"] is False
    facts = jobs.machine_facts(c, "jsmith", "EDIT-PC")
    # It may still be refused for another reason (this machine has reported no
    # capabilities); it must no longer be refused for the update.
    code, _why = jobs.policy_refusal(facts, "whisper", now=NOW)
    assert code != jobs.REFUSE_UPGRADING

    # ...and an UNDECIDED row - one written by a dashboard older than v55, or
    # a push made since the last report - is upgrading in both readers. Fail
    # closed: only an explicit verdict lifts the refusal.
    c.execute("UPDATE machines SET update_requested_withheld=NULL")
    c.commit()
    assert jobs.machine_facts(c, "jsmith", "EDIT-PC")["upgrading"] is True
    assert jobs.fleet_facts(c)[("jsmith", "EDIT-PC")]["upgrading"] is True
    c.close()


def test_the_flag_clears_the_moment_the_build_is_offerable_again(tmp_path):
    """CR-306: the request is left standing because the build may become
    offerable again (an un-retraction, a dashboard upgrade). When it does, the
    command rides the very next report and the machine is back to upgrading -
    the fail-closed direction, since the upgrade really is about to happen."""
    from ccsync_dashboard import jobs

    settings, app, c = _unofferable_push(tmp_path)
    c.close()
    _report(app)

    c = dbmod.connect(settings.db_path)
    assert dbmod.machine_update_request(c, "jsmith", "EDIT-PC")["withheld"]
    # The build becomes offerable: the vendor corrects the record's processor.
    # Written directly because the publish door holds one row per
    # (kind, platform, version) - what matters here is only that
    # `_upgrade_info` stops withholding it.
    c.execute("UPDATE companion_packages SET arch='x86_64' WHERE version='0.9.74'")
    c.commit()
    c.close()

    reply = _report(app)
    assert reply["commands"]["upgrade"]["version"] == "0.9.74"

    c = dbmod.connect(settings.db_path)
    assert dbmod.machine_update_request(c, "jsmith", "EDIT-PC")["withheld"] == ""
    assert jobs.machine_facts(c, "jsmith", "EDIT-PC")["upgrading"] is True
    assert jobs.fleet_facts(c)[("jsmith", "EDIT-PC")]["upgrading"] is True
    c.close()


def test_withdrawing_or_expiring_a_push_clears_the_verdict(conn):
    """CR-306: the verdict belongs to the request. A row that outlived its
    request would make the machine's next push look already-refused."""
    now = dbmod.utcnow_iso()
    dbmod.upsert_machine(conn, "jsmith", "EDIT-PC", now)
    dbmod.request_machine_update(conn, "jsmith", "EDIT-PC", "0.9.74", "owen", now)
    assert dbmod.machine_update_request(conn, "jsmith", "EDIT-PC")["withheld"] == ""
    assert dbmod.set_machine_update_withheld(
        conn, "jsmith", "EDIT-PC",
        "that build was made for a different processor") is True
    # Only a CHANGE writes: the report handler reaches this every 30 s.
    assert dbmod.set_machine_update_withheld(
        conn, "jsmith", "EDIT-PC",
        "that build was made for a different processor") is False
    dbmod.clear_machine_update_request(conn, "jsmith", "EDIT-PC")
    assert dbmod.machine_update_request(conn, "jsmith", "EDIT-PC") is None
    assert conn.execute(
        "SELECT update_requested_withheld FROM machines "
        " WHERE editor_username=? AND machine=?",
        ("jsmith", "EDIT-PC")).fetchone()[0] is None

    # ...and the 14-day expiry takes it with the request too.
    old = "2026-08-01T00:00:00+00:00"
    dbmod.upsert_machine(conn, "ruskin", "DESK-1", old)
    dbmod.request_machine_update(conn, "ruskin", "DESK-1", "0.9.74", "owen", old)
    dbmod.set_machine_update_withheld(conn, "ruskin", "DESK-1",
                                      "that build was recalled")
    assert dbmod.expire_machine_update_requests(conn, now) == 1
    assert conn.execute(
        "SELECT update_requested_withheld FROM machines "
        " WHERE editor_username=? AND machine=?",
        ("ruskin", "DESK-1")).fetchone()[0] is None


def test_the_packages_page_names_a_push_that_cannot_be_sent(tmp_path):
    """CR-306: the push is left standing on purpose, so the page has to say it
    cannot be sent - otherwise it renders as "asked, waiting for its next
    report" for a fortnight while nothing can ever apply it."""
    from ccsync_dashboard import api

    settings, app, c = _unofferable_push(tmp_path)
    c.close()
    _report(app)

    c = dbmod.connect(settings.db_path)
    view = api.build_packages_view(c, settings)
    entry = [m for m in view["outdated_machines"] if m["machine"] == "EDIT-PC"]
    assert entry and "processor" in entry[0]["update_withheld"]
    c.close()

    client = TestClient(app)
    client.cookies.set(auth.COOKIE_NAME, auth.make_session_cookie(SECRET, "owen"))
    html = client.get("/partials/admin/packages").text
    assert "[ CANNOT BE SENT ]" in html
    assert "It still takes jobs." in html


def test_v55_adds_the_withheld_column(tmp_path):
    """The migration itself, gapless."""
    c = dbmod.connect(tmp_path / "fresh.db")
    dbmod.migrate(c)
    cols = {r["name"] for r in c.execute("PRAGMA table_info(machines)")}
    assert "update_requested_withheld" in cols
    assert dbmod.SCHEMA_VERSION == 55
    c.close()
