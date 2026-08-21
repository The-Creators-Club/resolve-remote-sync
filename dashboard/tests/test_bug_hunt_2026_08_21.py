"""The 2026-08-21 bug hunt, dashboard core half.

One file per hunt rather than one test scattered into each existing module:
these are regressions with a finding id, and keeping the id, the mechanism
and the pin together is what makes the next reader understand why the
assertion is the shape it is. docs/bug-hunt-2026-08-21.md has the findings.
"""
from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from ccsync_dashboard import auth, api, sessions
from ccsync_dashboard import db as dbmod
from ccsync_dashboard.api import build_transfers_view
from ccsync_dashboard.app import create_app
from ccsync_dashboard.settings import Settings

SECRET = "test-secret"
TOKEN = "fleet-report-token"


def as_user(client, user):
    client.cookies.set(auth.COOKIE_NAME, auth.make_session_cookie(SECRET, user))
    return client


@pytest.fixture
def env(tmp_path):
    """The fleet shape the report endpoint needs: a project, an admin, and a
    client whose reports are accepted."""
    db_path = tmp_path / "hunt.db"
    settings = Settings(db_path=str(db_path), session_secret=SECRET, report_token=TOKEN,
                        admin_users=frozenset({"owen"}))
    app = create_app(settings)
    with TestClient(app) as client:
        conn = dbmod.connect(db_path)
        now = dbmod.utcnow_iso()
        dbmod.upsert_project(conn, "p1", "2026/One", "/x", now)
        dbmod.upsert_project(conn, "p2", "2026/Two", "/y", now)
        conn.commit()
        as_user(client, "owen")
        yield client, conn, now
        conn.close()


def hdr(editor):
    return {"X-CCSync-Token": TOKEN,
            "X-CCSync-Identity": auth.make_identity_token(SECRET, editor)}


def report(client, editor, machine, **extra):
    body = {"editor_name": editor, "machine": machine,
            "reported_at": "2026-08-21T10:00:00+00:00", "lanes": []}
    body.update(extra)
    resp = client.post("/api/v1/report", json=body, headers=hdr(editor))
    assert resp.status_code == 200, resp.text
    return resp.json()


# -- dash-core-2: /verify must not hand out a retired shared token ----------


def _verify_env(tmp_path, **kwargs):
    settings = Settings(db_path=str(tmp_path / "verify.db"), session_secret=SECRET,
                        report_token=TOKEN, admin_users=frozenset({"owen"}), **kwargs)
    app = create_app(settings)
    app.state.credential_verifier = lambda s, u, p: p == "right"
    return app


def test_verify_hands_out_the_shared_token_while_it_is_enabled(tmp_path):
    with TestClient(_verify_env(tmp_path)) as client:
        body = client.post("/api/v1/verify",
                           json={"username": "jsmith", "password": "right"}).json()
        assert body["report_token"] == TOKEN
        assert body["report_token_kind"] == "shared"


def test_verify_stops_handing_it_out_once_it_is_retired(tmp_path):
    """The operator finished the cce1 migration and set
    DASH_SHARED_REPORT_TOKEN_ENABLED=0. A companion that adopted the token
    /verify returned was answered 401 on every report and never appeared on
    the grid at all (dash-core-2)."""
    app = _verify_env(tmp_path, shared_report_token_enabled=False)
    with TestClient(app) as client:
        body = client.post("/api/v1/verify",
                           json={"username": "jsmith", "password": "right"}).json()
        assert body["report_token"] == ""
        assert body["report_token_kind"] == "editor"
        # ...and the token it did not hand out really is refused everywhere.
        assert api.resolve_companion_credential(
            app.state.settings, None, TOKEN)[0] == api.AUTH_NONE


# -- dash-core-3 / trust-model-2 + dash-admin-5: disable REVOKES ------------


@pytest.fixture
def local(tmp_path):
    settings = Settings(db_path=str(tmp_path / "local.db"), session_secret=SECRET,
                        admin_users=frozenset({"owen"}), auth_method="local")
    app = create_app(settings)
    with TestClient(app) as client:
        yield client


def _make_local(client, username, role="editor"):
    resp = client.post("/api/v1/admin/users",
                       json={"username": username, "role": role,
                             "password": "correct-horse-battery-1"})
    assert resp.status_code == 200, resp.text


def test_disabling_a_local_account_kills_its_session_and_its_report_token(local, tmp_path):
    """DISABLE is the non-destructive button an admin reaches for, and it used
    to leave the contractor's open tab working for 7 days and their companion
    reporting for ever (dash-core-3 / trust-model-2)."""
    as_user(local, "owen")
    _make_local(local, "contractor")
    conn = dbmod.connect(local.app.state.settings.db_path)
    token, _row = dbmod.create_editor_report_token(conn, "contractor", "owen")
    conn.commit()
    assert dbmod.verify_editor_report_token(conn, token) == "contractor"

    # A REAL session of theirs (a hand-minted cookie has no server-side row,
    # and the row is what revocation acts on).
    theirs = TestClient(local.app)
    assert theirs.post("/api/v1/login", json={
        "username": "contractor", "password": "correct-horse-battery-1"}).status_code == 200
    store = local.app.state.session_store
    assert len(store.list_for_user("contractor")) == 1

    resp = local.post("/api/v1/admin/users/contractor/disable", json={"disabled": True})
    assert resp.status_code == 200, resp.text
    assert resp.json()["purged"]["sessions_revoked"] == 1
    assert resp.json()["purged"]["report_tokens_revoked"] == 1

    assert store.list_for_user("contractor") == []
    assert dbmod.verify_editor_report_token(conn, token) is None
    conn.close()


def test_re_enabling_does_not_resurrect_anything(local):
    as_user(local, "owen")
    _make_local(local, "contractor")
    local.post("/api/v1/admin/users/contractor/disable", json={"disabled": True})
    resp = local.post("/api/v1/admin/users/contractor/disable", json={"disabled": False})
    assert resp.status_code == 200
    assert resp.json()["purged"]["sessions_revoked"] == 0


def test_an_admin_cannot_disable_themselves(local):
    """auth.is_admin consults is_local_admin on every request and a disabled
    row is not an admin, so the session that did it could not undo it
    (dash-admin-5)."""
    as_user(local, "owen")
    _make_local(local, "boss", role="admin")
    as_user(local, "boss")

    resp = local.post("/api/v1/admin/users/boss/disable", json={"disabled": True})
    assert resp.status_code == 409, resp.text
    assert local.get("/api/v1/me").json()["is_admin"] is True


def test_the_last_enabled_admin_cannot_be_disabled(local):
    as_user(local, "owen")
    _make_local(local, "boss", role="admin")

    resp = local.post("/api/v1/admin/users/boss/disable", json={"disabled": True})
    assert resp.status_code == 409, resp.text

    _make_local(local, "boss2", role="admin")
    assert local.post("/api/v1/admin/users/boss/disable",
                      json={"disabled": True}).status_code == 200


# -- dash-core-4 / trust-model-3: the two login budgets ---------------------


def test_a_successful_login_does_not_reset_the_per_ip_budget(tmp_path):
    """Interleaving one valid login after every few failures used to delete
    the IP row, so the spray budget never bit (dash-core-4)."""
    store = sessions.SessionStore(tmp_path / "thr.db")
    store.ensure_schema()
    now = "2026-08-21T12:00:00+00:00"
    for n in range(sessions.LOGIN_FAILURE_LIMIT_IP - 1):
        store.record_failure(f"victim{n}", "10.0.0.9", now=now)
    store.clear_failures("attacker")          # what a successful login does now
    store.record_failure("victim-last", "10.0.0.9", now=now)

    assert store.throttled("someone-else", "10.0.0.9", now=now) > 0


def test_one_gateway_does_not_park_the_fleet_after_five_typos(tmp_path):
    """Behind Tailscale Serve every request arrives from the docker bridge
    gateway, so at the per-username limit one editor with caps lock on 429'd
    every editor AND every companion sign-in (trust-model-3)."""
    store = sessions.SessionStore(tmp_path / "gw.db")
    store.ensure_schema()
    now = "2026-08-21T12:00:00+00:00"
    for _ in range(sessions.LOGIN_FAILURE_LIMIT):
        store.record_failure("butterfingers", "172.17.0.1", now=now)

    assert store.throttled("butterfingers", "172.17.0.1", now=now) > 0   # they wait
    assert store.throttled("everyone-else", "172.17.0.1", now=now) == 0  # nobody else does


# -- dash-core-5: the halt read takes both companion credentials ------------


def _bare_request(app, token):
    """A Request with a token header and no cookie.

    The route is exercised directly: app.py's login_gate does not list
    /api/v1/fleet/halt among the paths a companion token may skip, so a
    companion cannot reach this route through the middleware at all today
    (which is also why dash-core-5's leak was never live). What is fixed here
    is the route's own rule, so the route is what the test drives."""
    from starlette.requests import Request

    return Request({
        "type": "http", "method": "GET", "path": "/api/v1/fleet/halt",
        "query_string": b"", "root_path": "", "app": app, "client": ("10.0.0.5", 5),
        "headers": [(b"x-ccsync-token", token.encode())], "state": {},
    })


def test_the_halt_read_takes_a_per_editor_token_and_refuses_a_retired_one(tmp_path):
    settings = Settings(db_path=str(tmp_path / "halt.db"), session_secret=SECRET,
                        report_token=TOKEN, admin_users=frozenset({"owen"}),
                        shared_report_token_enabled=False)
    app = create_app(settings)
    with TestClient(app):
        conn = dbmod.connect(settings.db_path)
        cce1, _row = dbmod.create_editor_report_token(conn, "jsmith", "owen")
        conn.commit()

        assert api.api_fleet_halt(_bare_request(app, cce1), conn)["halt"] is not None
        with pytest.raises(Exception) as refused:
            api.api_fleet_halt(_bare_request(app, TOKEN), conn)
        assert getattr(refused.value, "status_code", None) == 401
        conn.close()


# -- dash-core-6: a pushed update the machine moved past -------------------


def test_a_push_the_machine_overtook_stops_being_re_sent(env):
    """Pushed 0.9.43 while the machine was off; its editor clicked Update and
    it came back on 0.9.44. The request rode every report for ever and the
    packages page showed a push that could never complete (dash-core-6)."""
    client, conn, now = env
    report(client, "ruskin", "PC", platform="windows", companion_version="0.9.42")
    dbmod.insert_companion_package(conn, version="0.9.43", platform="windows",
                                   filename="c.exe", sha256="a" * 64, size_bytes=1,
                                   published_by="owen", now=now)
    dbmod.set_current_package(conn, "windows", "0.9.43", "companion")
    conn.commit()
    client.post("/api/v1/admin/machines/ruskin/PC/update")

    reply = report(client, "ruskin", "PC", platform="windows", companion_version="0.9.44")

    assert "upgrade" not in reply["commands"]
    assert dbmod.machine_update_request(conn, "ruskin", "PC") is None


def test_a_two_digit_minor_is_newer_than_a_one_digit_one(env):
    """After 0.9.9 comes 0.10.0, never 1.0 (owner's rule 2026-08-18), and a
    string compare puts 0.10.0 below 0.9.9."""
    assert api._version_at_least("0.10.0", "0.9.43") is True
    assert api._version_at_least("0.9.43", "0.10.0") is False
    # An unparsable running version never reads as "past it".
    assert api._version_at_least("0.9.43+dirty", "0.9.43") is False
    assert api._version_at_least("0.9.43", "0.9.43") is True


# -- dash-admin-8 / data-model-1: wired is per MACHINE ----------------------


def _wired(client, editor, machine):
    report(client, editor, machine, mode="base")


def test_a_person_level_tick_skips_their_wired_machine(env):
    """One account, one wired desktop and one remote laptop -- the shape
    f27c181 introduced. base_only_editors is false for them, so the tick
    landed on the desktop too and the transfers page showed a
    [ GETTING READY ] chip that could never clear (dash-admin-8)."""
    client, conn, _now = env
    _wired(client, "alex", "BASE-RIG")
    report(client, "alex", "LAPTOP", mode="editor")

    assert client.put("/api/v1/selection/alex/p1").status_code == 200

    plans = dbmod.fetch_machine_selections(conn)["p1"]
    assert ("alex", "LAPTOP") in plans
    assert ("alex", "BASE-RIG") not in plans
    # ...and nothing is left preparing for ever on the wired machine.
    queues = build_transfers_view(conn)["queues"]
    assert not [q for q in queues if q["machine"] == "BASE-RIG"]


def test_ticking_a_wired_machine_by_name_is_refused(env):
    client, _conn, _now = env
    _wired(client, "alex", "BASE-RIG")
    report(client, "alex", "LAPTOP", mode="editor")

    resp = client.put("/api/v1/selection/alex/p1?machine=BASE-RIG")
    assert resp.status_code == 409, resp.text
    assert "wired machine" in resp.json()["detail"]


def test_a_plan_cannot_be_copied_onto_a_wired_machine(env):
    client, _conn, _now = env
    _wired(client, "alex", "BASE-RIG")
    report(client, "alex", "LAPTOP", mode="editor")
    client.put("/api/v1/selection/alex/p1?machine=LAPTOP")

    resp = client.post("/api/v1/admin/machines/alex/BASE-RIG/copy-plan?source=LAPTOP")
    assert resp.status_code == 409, resp.text


# -- data-model-5: one device id belongs to one computer -------------------


def test_a_reported_device_id_is_taken_off_the_row_that_still_claims_it(env):
    """A refused rename adoption leaves two rows holding one device id, and
    enforce then hands the live machine the UNION of both plans while its own
    GET /selection returns one of them (data-model-5)."""
    client, conn, _now = env
    report(client, "ruskin", "OLD-NAME", machine_id="mid-1", syncthing_device_id="DEV-1")
    # A DIFFERENT computer of the same person takes the same device id (a
    # restored image, a regenerated Syncthing home).
    report(client, "ruskin", "NEW-NAME", machine_id="mid-2", syncthing_device_id="DEV-1")

    rows = {r["machine"]: r["syncthing_device_id"] for r in dbmod.fetch_machines(conn, "ruskin")}
    assert rows == {"OLD-NAME": None, "NEW-NAME": "DEV-1"}
    assert dbmod.machine_by_device_id(conn, "DEV-1")["machine"] == "NEW-NAME"


# -- ops-efficiency-1: an absent section leaves the table alone ------------


def test_a_report_without_the_media_sections_does_not_clear_them(env):
    """The companion may stop re-sending an unchanged local_manifest /
    media_tree every 60s. The server contract that makes that safe is
    "absent field => table untouched", and it is worth a pin: the alternative
    is every editor's media panel emptying on the next report."""
    client, conn, _now = env
    report(client, "ruskin", "PC", local_manifest={
        "2026/One": {"n_originals": 2, "bytes_originals": 20,
                     "n_proxies": 1, "bytes_proxies": 5,
                     "originals": [["a.mov", 10], ["b.mov", 10]],
                     "proxies": [["Proxy/a.mov", 5]]},
    })
    before = conn.execute("SELECT COUNT(*) FROM editor_media").fetchone()[0]
    assert before == 3

    report(client, "ruskin", "PC")            # no local_manifest key at all

    assert conn.execute("SELECT COUNT(*) FROM editor_media").fetchone()[0] == before
    row = conn.execute("SELECT n_originals FROM editor_media_project").fetchone()
    assert row["n_originals"] == 2


# -- data-model-4: the registry outranks the device LABEL -------------------


def test_a_device_approved_under_its_hostname_still_shows_its_backlog(env):
    """Two authorities bind a device to an editor: the label an admin typed
    at approve time, and the registry the companion reports. A device
    approved straight in the Syncthing GUI carries a HOSTNAME, which resolves
    to no editor, so the lane C queue dropped that machine's whole backlog
    even though the registry knew whose computer it was (data-model-4)."""
    client, conn, now = env
    device = "DESKTOP-LQQ41TC-AAAA"
    report(client, "ruskin", "PC", syncthing_device_id=device, mode="editor")
    client.put("/api/v1/selection/ruskin/p1?machine=PC")

    pid = conn.execute("SELECT id FROM projects WHERE slug='p1'").fetchone()["id"]
    # ...approved under its hostname, so `devices.editor_username` is NULL.
    did = dbmod.upsert_device(conn, device, "DESKTOP-LQQ41TC", False, now)
    dbmod.upsert_completion(conn, pid, did, completion=10.0, need_items=7,
                            need_bytes=700, need_deletes=0, global_items=70,
                            global_bytes=7000, now=now)
    conn.commit()

    queues = build_transfers_view(conn)["queues"]
    lane_c = [q for q in queues if q["lane"] == "c" and not q.get("pending")]
    assert [(q["editor"], q["machine"], q["n_files"]) for q in lane_c] == [("ruskin", "PC", 7)]


def test_copying_a_plan_replaces_the_target_and_nothing_more(env):
    """copy-plan writes the target's first own row, which is exactly the
    shape that materialises the unassigned bucket -- it must not, or "same as
    the desktop, please" would quietly add the bucket's projects too
    (dash-core-1)."""
    client, conn, now = env
    dbmod.add_selection_for_person(conn, "ruskin", "p1", "owen", now)     # bucket
    conn.commit()
    report(client, "ruskin", "DESK")
    report(client, "ruskin", "LAPTOP")
    client.put("/api/v1/selection/ruskin/p2?machine=DESK")
    # DESK now holds p1 (inherited, materialised) + p2; LAPTOP still inherits.

    resp = client.post("/api/v1/admin/machines/ruskin/LAPTOP/copy-plan?source=DESK")
    assert resp.status_code == 200, resp.text
    assert sorted(s["slug"] for s in
                  dbmod.selections_for_machine(conn, "ruskin", "LAPTOP")) == ["p1", "p2"]
