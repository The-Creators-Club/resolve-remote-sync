"""Admins can delete users and computers (CR-76, 2026-08-24).

DELETE /api/v1/admin/users/{username} removes a PERSON everywhere: the
account (local row or NAS account), every computer of theirs, their
Syncthing devices and shares, and every credential that could still act as
them. DELETE /api/v1/admin/machines/{editor}/{machine} removes ONE COMPUTER
and nothing of the person.

The property these pin hardest is the order: Syncthing first, because a
device whose editor the dashboard no longer knows is "unmapped" and the
enforce cycle leaves it alone (B16) -- so forgetting the rows before the
device would leave an ex-editor's machine receiving every project it was
ever shared, forever, silently.
"""
from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from ccsync_dashboard import auth
from ccsync_dashboard import db as dbmod
from ccsync_dashboard.app import create_app
from ccsync_dashboard.settings import Settings

from fake_syncthing import EDITOR2_ID, EDITOR_ID, SERVER_ID, FakeSyncthing

SECRET = "test-secret"
TOKEN = "tok"
DEV_A = "DEVAAAA-DEVAAAA-DEVAAAA-DEVAAAA-DEVAAAA-DEVAAAA-DEVAAAA-DEVAAAA"
DEV_B = "DEVBBBB-DEVBBBB-DEVBBBB-DEVBBBB-DEVBBBB-DEVBBBB-DEVBBBB-DEVBBBB"


def as_user(client, user):
    client.cookies.set(auth.COOKIE_NAME, auth.make_session_cookie(SECRET, user))
    return client


def hdr(editor):
    return {"X-CCSync-Token": TOKEN,
            "X-CCSync-Identity": auth.make_identity_token(SECRET, editor)}


def report(client, editor, machine, **extra):
    body = {"editor_name": editor, "machine": machine,
            "reported_at": "2026-08-24T10:00:00+00:00", "lanes": []}
    body.update(extra)
    resp = client.post("/api/v1/report", json=body, headers=hdr(editor))
    assert resp.status_code == 200, resp.text
    return resp.json()


@pytest.fixture
def syncthing():
    fake = FakeSyncthing().start()
    # Two more editor devices beside the defaults: ruskin's desktop and laptop,
    # both shared on the one folder.
    fake.state["devices"] += [{"deviceID": DEV_A, "name": "ruskin"},
                              {"deviceID": DEV_B, "name": "ruskin"}]
    fake.state["folders"][0]["devices"] += [{"deviceID": DEV_A}, {"deviceID": DEV_B}]
    yield fake
    fake.stop()


@pytest.fixture
def env(tmp_path, nas_case, syncthing, monkeypatch):
    """NAS mode (smb), parametrised over every NAS backend, with a fake
    Syncthing and the fleet report token -- the shape of the studio.

    The in-process collector is kept OFF: against a live fake it would seed
    selections from the folder shares and reconcile them on its own clock,
    racing every assertion here about who holds which plan and which device
    is shared where. Its `_stop` is set so the watchdog reads it as stopped
    on purpose, never as dead (Collector.thread_died)."""
    from ccsync_dashboard.collector import Collector
    monkeypatch.setattr(Collector, "start", lambda self: self._stop.set())
    settings = Settings(
        db_path=str(tmp_path / "delete.db"), session_secret=SECRET, report_token=TOKEN,
        admin_users=frozenset({"owen"}), syncthing_url=syncthing.url,
        syncthing_api_key="fake-key", **nas_case.kwargs,
    )
    app = create_app(settings)
    with TestClient(app) as client:
        conn = dbmod.connect(settings.db_path)
        now = dbmod.utcnow_iso()
        dbmod.upsert_project(conn, "2025-ff4-nuclear", "2025/FF4/Nuclear", "/x", now)
        dbmod.upsert_project(conn, "p2", "2026/Two", "/y", now)
        conn.commit()
        yield client, conn, nas_case, syncthing


def _conn(client):
    return dbmod.connect(client.app.state.settings.db_path)


def _nas_has(nas_case, username: str) -> bool:
    from ccsync_dashboard.nas import factory as nas_factory
    return nas_factory.make_nas_client(Settings(
        db_path=":memory:", session_secret=SECRET, **nas_case.kwargs,
    )).find_user(username) is not None


def _setup_ruskin(client):
    """ruskin: a NAS editor with two computers, a plan on each, a token, a
    session and a bucket row -- everything a delete has to find."""
    report(client, "ruskin", "DESKTOP-1", machine_id="mid-1", syncthing_device_id=DEV_A,
           platform="windows")
    report(client, "ruskin", "LAPTOP", machine_id="mid-2", syncthing_device_id=DEV_B,
           platform="macos")
    as_user(client, "owen")
    assert client.put("/api/v1/selection/ruskin/2025-ff4-nuclear?machine=DESKTOP-1").status_code == 200
    assert client.put("/api/v1/selection/ruskin/p2?machine=LAPTOP").status_code == 200
    conn = _conn(client)
    dbmod.add_selection(conn, "ruskin", "p2", "owen", dbmod.utcnow_iso(), machine="")
    dbmod.create_editor_report_token(conn, "ruskin", created_by="owen")
    conn.commit()
    conn.close()
    client.app.state.session_store.create("sid-for-ruskin", "ruskin", client="laptop")


# ------------------------------------------------------------ delete a user


def test_delete_user_removes_account_devices_records_and_credentials(env):
    client, _conn0, nas_case, syncthing = env
    nas_case.seed_editor("ruskin", 3011)
    _setup_ruskin(client)

    resp = client.delete("/api/v1/admin/users/ruskin")
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["ok"] is True
    assert sorted(body["deleted"]["machines"]) == ["DESKTOP-1", "LAPTOP"]
    assert {d["device_id"] for d in body["deleted"]["devices_removed"]} == {DEV_A, DEV_B}
    assert body["deleted"]["sessions_revoked"] == 1
    assert body["deleted"]["report_tokens_revoked"] == 1

    # The NAS account is gone (through the backend's own refusal-guarded delete).
    assert _nas_has(nas_case, "ruskin") is False
    # Syncthing: the devices are gone and so are their shares -- nothing on the
    # server will ever offer this person's computers a folder again.
    ids = {d["deviceID"] for d in syncthing.state["devices"]}
    assert DEV_A not in ids and DEV_B not in ids
    assert SERVER_ID in ids and EDITOR_ID in ids          # nobody else touched
    for folder in syncthing.state["folders"]:
        shared = {d["deviceID"] for d in folder["devices"]}
        assert DEV_A not in shared and DEV_B not in shared
        assert EDITOR_ID in shared
    # The fleet's records: every per-machine table, the bucket, the known row.
    conn = _conn(client)
    assert dbmod.fetch_machines(conn, "ruskin") == []
    assert "ruskin" not in dbmod.known_editor_usernames(conn)
    for table in ("selections", "machine_state", "lane_report_current", "editor_prefs",
                  "report_auth", "machines"):
        assert conn.execute(f"SELECT COUNT(*) FROM {table} WHERE editor_username='ruskin'"
                            ).fetchone()[0] == 0, table
    assert dbmod.fetch_editor_report_tokens(conn, editor="ruskin") == []
    conn.close()
    assert client.app.state.session_store.list_for_user("ruskin") == []
    # And the view the page re-renders from no longer lists them anywhere.
    assert all(m["editor_username"] != "ruskin" for m in body["view"]["computers"])
    assert "ruskin" not in body["view"]["fleet_only_editors"]
    assert all(e["username"] != "ruskin" for e in body["view"]["editors"])


def test_syncthing_down_means_nothing_is_deleted(env):
    """The order is the safety property: if the devices cannot be removed,
    the account and the rows must stay too -- an account-less editor whose
    machine still receives projects is the B16 shape."""
    client, _conn0, nas_case, syncthing = env
    nas_case.seed_editor("ruskin", 3011)
    _setup_ruskin(client)
    syncthing.state["down"] = True

    resp = client.delete("/api/v1/admin/users/ruskin")
    assert resp.status_code == 502, resp.text
    assert "nothing was deleted" in resp.json()["detail"]

    assert _nas_has(nas_case, "ruskin") is True
    conn = _conn(client)
    assert len(dbmod.fetch_machines(conn, "ruskin")) == 2
    assert "ruskin" in dbmod.known_editor_usernames(conn)
    # Credentials are the LAST step, after the commit: untouched here.
    assert len(dbmod.fetch_editor_report_tokens(conn, editor="ruskin")) == 1
    conn.close()
    assert len(client.app.state.session_store.list_for_user("ruskin")) == 1


def test_cannot_delete_yourself_in_nas_mode(env):
    client, _conn0, nas_case, _syncthing = env
    nas_case.seed_editor("owen", 3012)
    as_user(client, "owen")
    resp = client.delete("/api/v1/admin/users/owen")
    assert resp.status_code == 409
    assert "signed in as" in resp.json()["detail"]
    assert _nas_has(nas_case, "owen") is True


def test_delete_refuses_a_system_account(env):
    """The Users page takes a free-text username; the backend's refusals are
    what stop DELETE /admin/users/root from being a NAS takeover."""
    client, _conn0, nas_case, _syncthing = env
    victim = "root" if nas_case.kind == "truenas" else "admin"
    nas_case.seed_editor(victim, 0 if nas_case.kind == "truenas" else 1024)
    as_user(client, "owen")
    resp = client.delete(f"/api/v1/admin/users/{victim}")
    assert resp.status_code == 502, resp.text
    assert "refusing" in resp.json()["detail"]
    assert _nas_has(nas_case, victim) is True


def test_delete_refuses_an_account_outside_the_editors_group(env):
    client, _conn0, nas_case, _syncthing = env
    nas_case.seed_editor("studio", 3020)
    if nas_case.kind == "truenas":
        row = next(u for u in nas_case.fake.state["users"] if u["username"] == "studio")
        row["groups"] = []
        row["group"] = {"id": 999}
    else:
        nas_case.fake.state["members"]["editors"].remove("studio")
    as_user(client, "owen")
    resp = client.delete("/api/v1/admin/users/studio")
    assert resp.status_code == 502, resp.text
    assert "refusing" in resp.json()["detail"]
    assert _nas_has(nas_case, "studio") is True


def test_delete_unknown_everywhere_is_404(env):
    client, _conn0, _nas_case, _syncthing = env
    as_user(client, "owen")
    assert client.delete("/api/v1/admin/users/nobody").status_code == 404


def test_delete_requires_admin(env):
    client, _conn0, nas_case, _syncthing = env
    nas_case.seed_editor("ruskin", 3011)
    assert client.delete("/api/v1/admin/users/ruskin").status_code == 401
    as_user(client, "jsmith")
    assert client.delete("/api/v1/admin/users/ruskin").status_code == 403
    assert client.delete("/api/v1/admin/machines/ruskin/DESKTOP-1").status_code == 403
    assert _nas_has(nas_case, "ruskin") is True


def test_delete_removes_a_device_approved_under_the_name_but_never_registered(env):
    """An admin approved jsmith's device (it is in Syncthing's config, named
    after them) but no companion ever reported an id, so the registry does
    not know it. It is still theirs, and it still goes."""
    client, _conn0, nas_case, syncthing = env
    nas_case.seed_editor("jsmith", 3010)
    as_user(client, "owen")
    resp = client.delete("/api/v1/admin/users/jsmith")
    assert resp.status_code == 200, resp.text
    assert {d["device_id"] for d in resp.json()["deleted"]["devices_removed"]} == {EDITOR_ID}
    assert EDITOR_ID not in {d["deviceID"] for d in syncthing.state["devices"]}
    # The unmapped stranger beside it (EDITOR2_ID, named by its id) is not theirs.
    assert EDITOR2_ID in {d["deviceID"] for d in syncthing.state["devices"]}


def test_delete_a_fleet_only_editor(env):
    """Known from a report, no account on the NAS: deletable, and listed as
    such in the view so the page can offer the button."""
    client, _conn0, nas_case, syncthing = env
    report(client, "ghost", "OLD-PC", syncthing_device_id=DEV_A)
    as_user(client, "owen")
    view = client.get("/api/v1/admin/users").json()
    assert "ghost" in view["fleet_only_editors"]
    assert any(m["machine"] == "OLD-PC" for m in view["computers"])

    resp = client.delete("/api/v1/admin/users/ghost")
    assert resp.status_code == 200, resp.text
    assert resp.json()["deleted"]["machines"] == ["OLD-PC"]
    assert DEV_A not in {d["deviceID"] for d in syncthing.state["devices"]}
    assert "ghost" not in resp.json()["view"]["fleet_only_editors"]


def test_home_directory_fate_is_reported_as_a_warning(env):
    client, _conn0, nas_case, _syncthing = env
    nas_case.seed_editor("ruskin", 3011)
    as_user(client, "owen")
    body = client.delete("/api/v1/admin/users/ruskin").json()
    assert body["warnings"], body
    if nas_case.kind == "truenas":
        assert "left in place" in body["warnings"][0]
        assert nas_case.fake.state["deleted_users"][0]["delete_group"] is False
    else:
        assert "home folder" in body["warnings"][0]


# -------------------------------------------------------- forget a computer


def test_forget_one_computer_leaves_the_person_and_their_other_computer(env):
    client, _conn0, nas_case, syncthing = env
    nas_case.seed_editor("ruskin", 3011)
    _setup_ruskin(client)

    resp = client.delete("/api/v1/admin/machines/ruskin/DESKTOP-1")
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["devices_removed"] == [{"device_id": DEV_A, "unshared": ["2025-ff4-nuclear"]}]
    assert "register it again" in body["note"]

    ids = {d["deviceID"] for d in syncthing.state["devices"]}
    assert DEV_A not in ids and DEV_B in ids
    shared = {d["deviceID"] for d in syncthing.state["folders"][0]["devices"]}
    assert DEV_A not in shared and DEV_B in shared

    conn = _conn(client)
    assert [m["machine"] for m in dbmod.fetch_machines(conn, "ruskin")] == ["LAPTOP"]
    assert [s["slug"] for s in dbmod.selections_for_machine(conn, "ruskin", "LAPTOP")] == ["p2"]
    # The unassigned bucket is the person's, not the desktop's.
    assert conn.execute("SELECT COUNT(*) FROM selections WHERE editor_username='ruskin' "
                        "AND machine=''").fetchone()[0] == 1
    assert "ruskin" in dbmod.known_editor_usernames(conn)
    assert len(dbmod.fetch_editor_report_tokens(conn, editor="ruskin")) == 1
    conn.close()
    assert _nas_has(nas_case, "ruskin") is True
    assert len(client.app.state.session_store.list_for_user("ruskin")) == 1


def test_forget_unknown_computer_is_404(env):
    client, _conn0, _nas_case, _syncthing = env
    as_user(client, "owen")
    assert client.delete("/api/v1/admin/machines/ruskin/NOPE").status_code == 404


def test_forget_computer_with_syncthing_down_removes_nothing(env):
    client, _conn0, nas_case, syncthing = env
    nas_case.seed_editor("ruskin", 3011)
    _setup_ruskin(client)
    syncthing.state["down"] = True
    resp = client.delete("/api/v1/admin/machines/ruskin/DESKTOP-1")
    assert resp.status_code == 502
    conn = _conn(client)
    assert len(dbmod.fetch_machines(conn, "ruskin")) == 2
    conn.close()


def test_forget_computer_without_a_device_id_is_records_only(env):
    client, _conn0, _nas_case, syncthing = env
    report(client, "leso", "MacBook")
    as_user(client, "owen")
    before = list(syncthing.state["devices"])
    resp = client.delete("/api/v1/admin/machines/leso/MacBook")
    assert resp.status_code == 200, resp.text
    assert resp.json()["devices_removed"] == []
    assert syncthing.state["devices"] == before
    conn = _conn(client)
    assert dbmod.fetch_machines(conn, "leso") == []
    conn.close()


def test_a_forgotten_computer_that_keeps_reporting_comes_back(env):
    """Documented, not a bug: report tokens belong to the person. The confirm
    and the response say so; deleting the user is the revocation."""
    client, _conn0, _nas_case, _syncthing = env
    report(client, "ruskin", "DESKTOP-1", machine_id="mid-1", syncthing_device_id=DEV_A)
    as_user(client, "owen")
    assert client.delete("/api/v1/admin/machines/ruskin/DESKTOP-1").status_code == 200
    report(client, "ruskin", "DESKTOP-1", machine_id="mid-1", syncthing_device_id=DEV_A)
    conn = _conn(client)
    assert [m["machine"] for m in dbmod.fetch_machines(conn, "ruskin")] == ["DESKTOP-1"]
    conn.close()


# ------------------------------------------------------------ the page


def test_users_page_lists_computers_with_a_remove_button(env):
    client, _conn0, nas_case, _syncthing = env
    nas_case.seed_editor("ruskin", 3011)
    _setup_ruskin(client)
    resp = client.get("/admin/users")
    assert resp.status_code == 200
    html = resp.text
    assert "[ COMPUTERS ]" in html
    assert "DESKTOP-1" in html and "LAPTOP" in html
    assert "/partials/admin/machines/forget" in html
    assert "[ REMOVE ]" in html
    # The NAS account row carries the delete now too.
    assert html.count("/partials/admin/users/delete") >= 1


def test_partial_forget_machine_via_htmx(env):
    client, _conn0, nas_case, syncthing = env
    nas_case.seed_editor("ruskin", 3011)
    _setup_ruskin(client)
    resp = client.post("/partials/admin/machines/forget",
                       data={"editor": "ruskin", "machine": "DESKTOP-1"})
    assert resp.status_code == 200, resp.text
    assert "DESKTOP-1" not in resp.text
    assert "LAPTOP" in resp.text
    assert DEV_A not in {d["deviceID"] for d in syncthing.state["devices"]}


def test_partial_delete_user_via_htmx_in_nas_mode(env):
    client, _conn0, nas_case, syncthing = env
    nas_case.seed_editor("ruskin", 3011)
    _setup_ruskin(client)
    resp = client.post("/partials/admin/users/delete", data={"username": "ruskin"})
    assert resp.status_code == 200, resp.text
    # No row, no form, no computer left that names them...
    assert 'value="ruskin"' not in resp.text
    assert "DESKTOP-1" not in resp.text and "LAPTOP" not in resp.text
    # ...and the backend's home-directory note is the page's notice.
    assert "deleted ruskin:" in resp.text
    assert _nas_has(nas_case, "ruskin") is False
    assert DEV_A not in {d["deviceID"] for d in syncthing.state["devices"]}


def test_partial_delete_refusal_is_a_banner(env):
    client, _conn0, nas_case, _syncthing = env
    nas_case.seed_editor("ruskin", 3011)
    _setup_ruskin(client)
    resp = client.post("/partials/admin/users/delete", data={"username": "owen"})
    assert resp.status_code == 200
    assert "signed in as" in resp.text
    assert _nas_has(nas_case, "ruskin") is True


def test_partial_forget_requires_admin(env):
    client, _conn0, _nas_case, _syncthing = env
    report(client, "ruskin", "DESKTOP-1")
    as_user(client, "jsmith")
    resp = client.post("/partials/admin/machines/forget",
                       data={"editor": "ruskin", "machine": "DESKTOP-1"})
    assert resp.status_code == 403
    conn = _conn(client)
    assert len(dbmod.fetch_machines(conn, "ruskin")) == 1
    conn.close()


# ------------------------------------------------------------ db layer


def test_forget_editor_clears_every_source_known_editor_usernames_reads(conn):
    now = dbmod.utcnow_iso()
    dbmod.upsert_machine(conn, "ruskin", "PC", now, syncthing_device_id=DEV_A)
    dbmod.record_known_editor(conn, "ruskin", "report", now)
    dbmod.add_selection(conn, "ruskin", "p1", "owen", now, machine="PC")
    dbmod.add_selection(conn, "ruskin", "p1", "owen", now, machine="")
    conn.execute("INSERT INTO editor_prefs (editor_username, machine, updated_at, updated_by) "
                 "VALUES ('ruskin', '', ?, 'owen')", (now,))
    conn.execute("INSERT INTO machine_state (editor_username, machine, reported_at) "
                 "VALUES ('ruskin', 'PC', ?)", (now,))
    device_row = dbmod.upsert_device(conn, DEV_A, "ruskin", False, now, {"ruskin"})
    conn.execute("INSERT INTO missing_files (project_id, device_id, name, refreshed_at) "
                 "VALUES (1, ?, 'a.mov', ?)", (device_row, now))
    assert dbmod.editor_device_ids(conn, "ruskin") == [DEV_A]

    out = dbmod.forget_editor(conn, "ruskin")
    assert out["machines"] == ["PC"]
    assert out["deleted"]["selections"] == 2
    assert out["deleted"]["devices"] == 1
    assert "ruskin" not in dbmod.known_editor_usernames(conn)
    assert conn.execute("SELECT COUNT(*) FROM devices").fetchone()[0] == 0
    assert conn.execute("SELECT COUNT(*) FROM missing_files").fetchone()[0] == 0


def test_forget_machine_never_touches_the_bucket_or_another_machine(conn):
    now = dbmod.utcnow_iso()
    dbmod.upsert_machine(conn, "ruskin", "PC", now)
    dbmod.upsert_machine(conn, "ruskin", "MAC", now)
    dbmod.add_selection(conn, "ruskin", "p1", "owen", now, machine="PC")
    dbmod.add_selection(conn, "ruskin", "p2", "owen", now, machine="MAC")
    dbmod.add_selection(conn, "ruskin", "p3", "owen", now, machine="")
    assert dbmod.forget_machine(conn, "ruskin", "") is None
    assert dbmod.forget_machine(conn, "ruskin", "NOPE") is None
    out = dbmod.forget_machine(conn, "ruskin", "PC")
    assert out["deleted"]["selections"] == 1
    rows = conn.execute("SELECT machine, project_slug FROM selections WHERE editor_username='ruskin' "
                        "ORDER BY project_slug").fetchall()
    assert [(r[0], r[1]) for r in rows] == [("MAC", "p2"), ("", "p3")]
