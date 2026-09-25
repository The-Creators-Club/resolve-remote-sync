"""The `machine_settings` report section and `commands.machine_settings` on
the reply: the dashboard half of the account page's wire (account page
2026-09-25, docs/ACCOUNT_PAGE_FEATURES.md §4, group D).

The rules defended here:

- B6 once more: a settings echo is never worth a 422. A section that will not
  parse is dropped and the report lands (lanes written, machine on the grid).
- Absent is NOT REPORTED, never a default: a report without the section
  leaves the stored cfg_* columns alone.
- The command is STANDING (the file_moves rule): it rides every reply while
  pending, is stamped delivered once, and an answer in a report finalises it
  before that same reply is built. A stale id and a word this build has never
  heard both leave it pending.
- `mode` is never requestable (CR-88), on the way in or on the way out.

Plus owner decision D-15 (the admin password-reset audit row, group D's half)
and the docs/API.md examples this group wrote.
"""
from __future__ import annotations

import json
import re
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from ccsync_dashboard import api, auth, db as dbmod, local_users
from ccsync_dashboard.app import create_app
from ccsync_dashboard.settings import Settings

SECRET = "test-secret-not-a-real-one"
TOKEN = "companion-token-not-a-real-one"
EDITOR = "jsmith"
MACHINE = "EDIT-PC"
NOW = "2026-09-25T10:00:00+00:00"

SECTION = {
    "accepts": ["jobs_enabled", "jobs_kinds"],
    "jobs_volunteer_minutes": 30,
    "drive_reminder_minutes": 30.0,
    "youtube": {"downloads": True, "signin_enabled": True,
                "terms_accepted": True, "signin": "ok"},
    "pending_restart": {"jobs_enabled": False},
}

LANES = [{"name": "lane_a_video_up", "state": "idle"}]


@pytest.fixture
def env(tmp_path):
    projects = tmp_path / "tree" / "Projects"
    projects.mkdir(parents=True)
    settings = Settings(db_path=str(tmp_path / "wire.db"), session_secret=SECRET,
                        report_token=TOKEN, admin_users=frozenset({"owen"}),
                        projects_dir=str(projects))
    app = create_app(settings)
    with TestClient(app) as client:
        conn = dbmod.connect(settings.db_path)
        yield client, conn
        conn.close()


def hdr(editor=EDITOR):
    return {"X-CCSync-Token": TOKEN,
            "X-CCSync-Identity": auth.make_identity_token(SECRET, editor)}


def body(**sections):
    out = {"editor_name": EDITOR, "machine": MACHINE,
           "companion_version": "0.9.80",
           "reported_at": "2026-09-25T10:00:00+00:00", "lanes": LANES}
    out.update(sections)
    return out


def report(client, **sections):
    return client.post("/api/v1/report", json=body(**sections), headers=hdr())


def stored(conn):
    return dbmod.machine_settings_map(conn).get((EDITOR, MACHINE))


def ask(conn, settings, *, by="owen", now=NOW):
    row = dbmod.request_machine_settings(conn, EDITOR, MACHINE, settings,
                                         requested_by=by, now=now)
    conn.commit()
    assert row is not None, "the machine must be registered by a report first"
    return row


def lane_rows(conn):
    return [r for r in dbmod.fetch_lane_reports(conn)
            if r["editor_username"] == EDITOR and r["machine"] == MACHINE]


# ---------------------------------------------------------------- the section

def test_no_section_leaves_nothing_reported(env):
    client, conn = env
    assert report(client).status_code == 200
    # NULL is "not reported", never a default: the machine is registered by
    # the report (so a missing row would prove nothing) and every cfg_* column
    # is still NULL, so it is absent from the map rather than defaulted.
    assert lane_rows(conn), "the report itself must land"
    assert stored(conn) is None
    row = conn.execute(
        "SELECT cfg_accepts, cfg_jobs_volunteer_minutes, cfg_drive_reminder_minutes,"
        " cfg_youtube, cfg_pending_restart, cfg_at FROM machine_state"
        " WHERE editor_username=? AND machine=?", (EDITOR, MACHINE)).fetchone()
    assert row is not None
    assert all(row[i] is None for i in range(6))


def test_the_section_is_stored(env):
    client, conn = env
    r = report(client, machine_settings=SECTION)
    assert r.status_code == 200, r.text
    got = stored(conn)
    assert got["accepts"] == ["jobs_enabled", "jobs_kinds"]
    assert got["jobs_volunteer_minutes"] == 30
    assert got["drive_reminder_minutes"] == 30.0
    assert got["youtube"]["signin"] == "ok"
    assert got["youtube"]["terms_accepted"] is True
    assert got["pending_restart"] == {"jobs_enabled": False}
    assert got["at"]


def test_a_report_without_the_section_leaves_the_columns_alone(env):
    """A companion mid-restart, or a light tick that shed it, says nothing."""
    client, conn = env
    report(client, machine_settings=SECTION)
    assert report(client).status_code == 200
    got = stored(conn)
    assert got["accepts"] == ["jobs_enabled", "jobs_kinds"]
    assert got["jobs_volunteer_minutes"] == 30


def test_a_section_replaces_the_old_one_wholesale(env):
    client, conn = env
    report(client, machine_settings=SECTION)
    report(client, machine_settings={"accepts": ["jobs_enabled"],
                                     "jobs_volunteer_minutes": 45})
    got = stored(conn)
    assert got["accepts"] == ["jobs_enabled"]
    assert got["jobs_volunteer_minutes"] == 45
    assert got["drive_reminder_minutes"] is None
    assert got["youtube"] is None
    assert not got["pending_restart"]


def test_out_of_range_numbers_are_clamped_and_long_words_cut(env):
    client, conn = env
    r = report(client, machine_settings={
        "accepts": ["jobs_enabled"],
        "jobs_volunteer_minutes": 10 ** 9,
        "drive_reminder_minutes": -5,
        "youtube": {"signin": "x" * 500},
        "applied": {"id": "a" * 500, "state": "s" * 500, "detail": "d" * 5000},
    })
    assert r.status_code == 200, r.text
    assert lane_rows(conn), "an oversized section must not cost the report"
    got = stored(conn)
    assert got["jobs_volunteer_minutes"] == 100000
    assert got["drive_reminder_minutes"] == 0
    assert got["youtube"]["signin"] == "x" * 16
    assert got["accepts"] == ["jobs_enabled"]


def test_an_oversized_answer_is_cut_and_an_oversized_id_matches_nothing(env):
    """applied.id/state/detail are cut to 64/32/255, never 422'd. A cut
    500-char id is not the pending request's id, so it finalises nothing; a
    cut 500-char state is a word this build does not know, so the request
    stays pending with the cut detail (review round, account page 2026-09-25)."""
    client, conn = env
    report(client, machine_settings=SECTION)
    row = ask(conn, {"jobs_enabled": False})

    r = report(client, machine_settings=dict(SECTION, applied={
        "id": "a" * 500, "state": "applied", "detail": "d" * 5000}))
    assert r.status_code == 200, r.text
    assert r.json()["commands"]["machine_settings"]["id"] == row["request_id"]
    got = dbmod.machine_settings_request(conn, EDITOR, MACHINE)
    assert got["state"] == "pending"
    assert not got.get("detail")

    r = report(client, machine_settings=dict(SECTION, applied={
        "id": row["request_id"], "state": "s" * 500, "detail": "d" * 5000}))
    assert r.status_code == 200, r.text
    assert r.json()["commands"]["machine_settings"]["id"] == row["request_id"]
    got = dbmod.machine_settings_request(conn, EDITOR, MACHINE)
    assert got["state"] == "pending"
    assert got["detail"] == "d" * 255


def test_known_keys_listed_late_in_a_long_list_are_kept(env):
    """No slice before the whitelist: a future companion that advertises
    many keys of its own ahead of ours must not lose ours (review round)."""
    client, conn = env
    noise = [f"future_{i}" for i in range(40)]
    r = report(client, machine_settings=dict(
        SECTION, accepts=noise + ["jobs_kinds", "jobs_enabled"],
        pending_restart=dict({f"future_{i}": i for i in range(40)},
                             drive_reminder_minutes=15)))
    assert r.status_code == 200, r.text
    got = stored(conn)
    assert got["accepts"] == ["jobs_enabled", "jobs_kinds"]
    assert got["pending_restart"] == {"drive_reminder_minutes": 15}


def test_unknown_keys_are_ignored_and_mode_is_never_accepted(env):
    """CR-88: wired or remote is the computer's own setting. A companion that
    advertises `mode` (or a key a future build grows) must not make it
    requestable here."""
    client, conn = env
    r = report(client, machine_settings=dict(
        SECTION,
        accepts=["mode", "jobs_kinds", 7, "jobs_kinds", "some_future_key"],
        pending_restart={"jobs_enabled": "yes",          # wrong type: dropped
                         "jobs_kinds": ["peaks"],
                         "jobs_volunteer_minutes": True,  # bool is not minutes
                         "drive_reminder_minutes": 15,
                         "mode": "base",                  # not a restart key
                         "future": 1},
        some_future_field={"a": 1}))
    assert r.status_code == 200, r.text
    got = stored(conn)
    assert got["accepts"] == ["jobs_kinds"]
    assert got["pending_restart"] == {"jobs_kinds": ["peaks"],
                                      "drive_reminder_minutes": 15}


@pytest.mark.parametrize("bad", [
    {"accepts": "jobs_enabled"},
    {"jobs_volunteer_minutes": "a while"},
    {"youtube": "on"},
    {"pending_restart": ["jobs_enabled"]},
    {"applied": "done"},
    "not even an object",
])
def test_a_section_with_a_wrong_type_is_dropped_and_the_report_lands(env, bad):
    client, conn = env
    report(client, machine_settings=SECTION)
    r = report(client, machine_settings=bad)
    assert r.status_code == 200, r.text
    assert lane_rows(conn), "the lanes in the same report must be written"
    assert MACHINE in dbmod.machines_of(conn, EDITOR)
    # Dropped means "said nothing": the last good section stands.
    assert stored(conn)["accepts"] == ["jobs_enabled", "jobs_kinds"]


def test_the_section_is_not_on_the_undeclared_banner(env):
    payload = api.ReportIn.model_validate(body(machine_settings=dict(
        SECTION, applied={"id": "abc", "state": "applied", "detail": "", "at": NOW})))
    assert payload.machine_settings is not None
    assert "machine_settings" not in api.undeclared_report_sections(payload)
    assert api.undeclared_report_sections(payload) == []


def test_the_section_is_registered_as_tolerant():
    assert api._TOLERANT_SECTIONS["machine_settings"] is api.MachineSettingsIn


# ---------------------------------------------------------------- the command

def test_no_command_when_nothing_is_asked(env):
    client, _conn = env
    r = report(client, machine_settings=SECTION)
    assert "machine_settings" not in r.json()["commands"]


def test_the_command_rides_while_pending_and_is_delivered_once(env):
    client, conn = env
    report(client, machine_settings=SECTION)
    row = ask(conn, {"jobs_enabled": False})

    first = report(client, machine_settings=SECTION).json()["commands"]
    cmd = first["machine_settings"]
    assert cmd == {"id": row["request_id"], "set": {"jobs_enabled": False},
                   "requested_by": "owen", "requested_at": NOW}
    delivered = dbmod.machine_settings_request(conn, EDITOR, MACHINE)["delivered_at"]
    assert delivered

    # Standing: the next reply carries it again, and the stamp is not moved.
    second = report(client, machine_settings=SECTION).json()["commands"]
    assert second["machine_settings"]["id"] == row["request_id"]
    assert dbmod.machine_settings_request(conn, EDITOR, MACHINE)["delivered_at"] == delivered


def test_an_applied_answer_stops_the_command_on_that_same_reply(env):
    client, conn = env
    report(client, machine_settings=SECTION)
    row = ask(conn, {"jobs_enabled": False})
    report(client, machine_settings=SECTION)
    r = report(client, machine_settings=dict(SECTION, applied={
        "id": row["request_id"], "state": "applied", "detail": "", "at": NOW}))
    assert r.status_code == 200, r.text
    assert "machine_settings" not in r.json()["commands"]
    assert dbmod.machine_settings_request(conn, EDITOR, MACHINE)["state"] == "applied"
    # ...and stays gone on the next one, though the ledger keeps echoing it.
    again = report(client, machine_settings=dict(SECTION, applied={
        "id": row["request_id"], "state": "applied", "detail": "", "at": NOW}))
    assert "machine_settings" not in again.json()["commands"]


def test_a_refused_answer_is_final_too(env):
    client, conn = env
    report(client, machine_settings=SECTION)
    row = ask(conn, {"jobs_kinds": ["peaks"]})
    r = report(client, machine_settings=dict(SECTION, applied={
        "id": row["request_id"], "state": "refused",
        "detail": "this computer does not know those kinds of work"}))
    assert "machine_settings" not in r.json()["commands"]
    got = dbmod.machine_settings_request(conn, EDITOR, MACHINE)
    assert got["state"] == "refused"
    assert got["detail"] == "this computer does not know those kinds of work"


def test_a_stale_id_does_not_stop_a_newer_request(env):
    """A second ask merged over the first under a new id: the machine's answer
    to the OLD id must not finalise the newer one."""
    client, conn = env
    report(client, machine_settings=SECTION)
    old = ask(conn, {"jobs_enabled": False})
    report(client, machine_settings=SECTION)
    new = ask(conn, {"jobs_kinds": ["peaks"]}, now="2026-09-25T10:05:00+00:00")
    assert new["request_id"] != old["request_id"]
    r = report(client, machine_settings=dict(SECTION, applied={
        "id": old["request_id"], "state": "applied"}))
    cmd = r.json()["commands"]["machine_settings"]
    assert cmd["id"] == new["request_id"]
    assert cmd["set"] == {"jobs_enabled": False, "jobs_kinds": ["peaks"]}
    assert dbmod.machine_settings_request(conn, EDITOR, MACHINE)["state"] == "pending"


def test_failed_keeps_the_request_pending_with_its_detail(env):
    client, conn = env
    report(client, machine_settings=SECTION)
    row = ask(conn, {"jobs_enabled": False})
    r = report(client, machine_settings=dict(SECTION, applied={
        "id": row["request_id"], "state": "failed", "detail": "could not save config.toml"}))
    assert r.json()["commands"]["machine_settings"]["id"] == row["request_id"]
    got = dbmod.machine_settings_request(conn, EDITOR, MACHINE)
    assert got["state"] == "pending"
    assert got["detail"] == "could not save config.toml"


def test_mode_never_rides_the_command_even_from_a_row_written_elsewhere(env):
    """The whitelist is applied on the way OUT as well: a row some other door
    wrote with `mode` in it must not reach a computer (CR-88)."""
    client, conn = env
    report(client, machine_settings=SECTION)
    ask(conn, {"jobs_enabled": False})
    conn.execute("UPDATE machine_setting_requests SET settings_json=? "
                 "WHERE editor_username=? AND machine=?",
                 (json.dumps({"jobs_enabled": False, "mode": "base"}), EDITOR, MACHINE))
    conn.commit()
    cmd = report(client, machine_settings=SECTION).json()["commands"]["machine_settings"]
    assert cmd["set"] == {"jobs_enabled": False}


def test_a_withdrawn_request_is_not_sent(env):
    client, conn = env
    report(client, machine_settings=SECTION)
    ask(conn, {"jobs_enabled": False})
    assert dbmod.withdraw_machine_settings_request(conn, EDITOR, MACHINE, by="owen", now=NOW)
    conn.commit()
    assert "machine_settings" not in report(client, machine_settings=SECTION).json()["commands"]


# ---------------------------------------------------------------- version skew

def test_an_answer_word_from_a_future_companion_is_accepted_and_stays_pending(env):
    client, conn = env
    report(client, machine_settings=SECTION)
    row = ask(conn, {"jobs_enabled": False})
    r = report(client, machine_settings=dict(SECTION, applied={
        "id": row["request_id"], "state": "something-new", "detail": "thinking about it"}))
    assert r.status_code == 200, r.text
    assert r.json()["commands"]["machine_settings"]["id"] == row["request_id"]
    got = dbmod.machine_settings_request(conn, EDITOR, MACHINE)
    assert got["state"] == "pending"
    assert got["detail"] == "thinking about it"


def test_a_companion_with_no_section_cannot_be_asked(env):
    """New dashboard, old companion: no `accepts`, so the request route
    refuses and no command is ever stored or sent (spec §4.6 row 1)."""
    client, conn = env
    assert report(client).status_code == 200
    client.cookies.set(auth.COOKIE_NAME, auth.make_session_cookie(SECRET, "owen"))
    r = client.post(f"/api/v1/machines/{EDITOR}/{MACHINE}/settings",
                    json={"jobs_enabled": False})
    assert r.status_code == 409, r.text
    assert "too old to change this from here" in r.json()["detail"]
    assert dbmod.machine_settings_request(conn, EDITOR, MACHINE) is None
    client.cookies.clear()
    assert "machine_settings" not in report(client).json()["commands"]


def test_a_rolled_back_companion_still_gets_the_standing_command(env):
    """New then rolled back to old: the pending request rides the reply and
    is ignored by the old build until it expires (spec §4.6 row 3). The
    dashboard does not withdraw it just because a report lacked the section:
    a shed section must not cost an ask."""
    client, conn = env
    report(client, machine_settings=SECTION)
    row = ask(conn, {"jobs_enabled": False})
    r = report(client)
    assert r.json()["commands"]["machine_settings"]["id"] == row["request_id"]


def test_a_key_the_machine_no_longer_accepts_withholds_the_command(env):
    """Spec §4.6 row 4 (review round, account page 2026-09-25): `accepts`
    shrank after the ask (a rollback to a build that takes only
    jobs_enabled). The companion would refuse the whole request, and a
    trimmed one would read as `applied` for keys never applied, so nothing is
    sent; the request stays pending and goes out again once `accepts` grows
    back."""
    client, conn = env
    report(client, machine_settings=SECTION)
    row = ask(conn, {"jobs_enabled": False, "jobs_kinds": ["peaks"]})

    shrunk = dict(SECTION, accepts=["jobs_enabled"])
    r = report(client, machine_settings=shrunk)
    assert r.status_code == 200, r.text
    assert "machine_settings" not in r.json()["commands"]
    got = dbmod.machine_settings_request(conn, EDITOR, MACHINE)
    assert got["state"] == "pending"
    assert not got.get("delivered_at")

    cmd = report(client, machine_settings=SECTION).json()["commands"]["machine_settings"]
    assert cmd["id"] == row["request_id"]
    assert cmd["set"] == {"jobs_enabled": False, "jobs_kinds": ["peaks"]}


def test_a_key_still_accepted_rides_a_shrunk_accepts(env):
    client, conn = env
    report(client, machine_settings=SECTION)
    row = ask(conn, {"jobs_enabled": False})
    cmd = report(client, machine_settings=dict(SECTION, accepts=["jobs_enabled"])
                 ).json()["commands"]["machine_settings"]
    assert cmd == {"id": row["request_id"], "set": {"jobs_enabled": False},
                   "requested_by": "owen", "requested_at": NOW}


def test_a_machine_that_accepts_nothing_now_gets_no_command(env):
    client, conn = env
    report(client, machine_settings=SECTION)
    ask(conn, {"jobs_enabled": False})
    r = report(client, machine_settings=dict(SECTION, accepts=[]))
    assert "machine_settings" not in r.json()["commands"]


# ------------------------------------------------------- D-15: password reset audit

@pytest.fixture
def local_env(tmp_path):
    settings = Settings(db_path=str(tmp_path / "local.db"), session_secret=SECRET,
                        admin_users=frozenset({"owen"}), auth_method="local")
    app = create_app(settings)
    with TestClient(app) as client:
        conn = dbmod.connect(settings.db_path)
        yield client, conn
        conn.close()


def _resets(conn, subject):
    return [r for r in dbmod.fetch_audit(conn, actions=(api.AUDIT_USER_PASSWORD_RESET,))
            if r["subject"] == subject]


def test_an_admin_password_reset_is_audited_without_the_password(local_env):
    client, conn = local_env
    local_users.create_user(conn, "jsmith", "first-password-long", "editor", created_by="owen")
    conn.commit()
    client.cookies.set(auth.COOKIE_NAME, auth.make_session_cookie(SECRET, "owen"))
    secret_pw = "second-password-long-9f3c"
    r = client.post("/api/v1/admin/users/jsmith/password", json={"password": secret_pw})
    assert r.status_code == 200, r.text
    [row] = _resets(conn, "jsmith")
    assert row["actor"] == "owen"
    assert row["detail"] == {"method": "local", "via": "reset"}
    assert secret_pw not in row["detail_json"]
    assert str(len(secret_pw)) not in row["detail_json"]


def test_a_refused_reset_writes_no_audit_row(local_env):
    client, conn = local_env
    client.cookies.set(auth.COOKIE_NAME, auth.make_session_cookie(SECRET, "owen"))
    r = client.post("/api/v1/admin/users/nobody/password",
                    json={"password": "a-long-enough-password"})
    assert r.status_code == 422
    assert _resets(conn, "nobody") == []


def test_an_editor_cannot_reset_and_leaves_no_row(local_env):
    client, conn = local_env
    local_users.create_user(conn, "jsmith", "first-password-long", "editor", created_by="owen")
    conn.commit()
    client.cookies.set(auth.COOKIE_NAME, auth.make_session_cookie(SECRET, "jsmith"))
    r = client.post("/api/v1/admin/users/jsmith/password",
                    json={"password": "second-password-long"})
    assert r.status_code == 403
    assert _resets(conn, "jsmith") == []


def test_a_nas_reset_and_a_create_with_password_are_audited(tmp_path):
    from fake_syncthing import FakeSyncthing
    from fake_truenas import FakeTrueNAS
    truenas = FakeTrueNAS().start()
    syncthing = FakeSyncthing().start()
    try:
        truenas.state["groups"].append({"id": 111, "group": "editors", "gid": 3001})
        truenas.state["users"].append({
            "id": 5, "uid": 3010, "username": "jsmith", "full_name": "jsmith",
            "home": "/mnt/tank/TheCreatorsPool/homes/jsmith", "group": {"id": 111},
            "groups": [111], "sshpubkey": "ssh-ed25519 AAAA", "smb": True,
            "locked": False, "password_disabled": False})
        settings = Settings(
            db_path=str(tmp_path / "nas.db"), session_secret=SECRET,
            admin_users=frozenset({"owen"}), truenas_host="unused-in-tests",
            truenas_user="truenas_admin", truenas_pw="fake-pw",
            truenas_base_url=truenas.base_url, syncthing_url=syncthing.url,
            syncthing_api_key="fake-key")
        with TestClient(create_app(settings)) as client:
            client.cookies.set(auth.COOKIE_NAME, auth.make_session_cookie(SECRET, "owen"))
            r = client.post("/api/v1/admin/users/jsmith/password",
                            json={"password": "knownpw1234567"})
            assert r.status_code == 200, r.text
            r = client.post("/api/v1/admin/users", json={
                "username": "jsmith", "ssh_pubkey": "ssh-ed25519 AAAA",
                "full_name": "jsmith", "password": "anotherpw1234567"})
            assert r.status_code == 200, r.text
            conn = dbmod.connect(settings.db_path)
            try:
                rows = _resets(conn, "jsmith")
            finally:
                conn.close()
        vias = sorted(r["detail"]["via"] for r in rows)
        assert vias == ["create", "reset"]
        assert all(r["detail"]["method"] == "smb" for r in rows)
        assert all("knownpw" not in r["detail_json"] and "anotherpw" not in r["detail_json"]
                   for r in rows)
    finally:
        truenas.stop()
        syncthing.stop()


# ---------------------------------------------------------------- docs/API.md

API_MD = Path(__file__).resolve().parents[2] / "docs" / "API.md"


def _json_blocks(text: str) -> list[str]:
    return re.findall(r"```json\n(.*?)```", text, re.S)


def test_the_account_section_examples_parse():
    text = API_MD.read_text(encoding="utf-8")
    start = text.index("## 4a. Account")
    end = text.index("## 5. Admin", start)
    blocks = _json_blocks(text[start:end])
    assert len(blocks) >= 4
    for block in blocks:
        json.loads(block)


def test_the_report_section_example_parses_and_is_accepted():
    """The documented section is what a companion may send: it parses as JSON
    and as a MachineSettingsIn with nothing left undeclared."""
    text = API_MD.read_text(encoding="utf-8")
    [block] = [b for b in _json_blocks(text) if b.lstrip().startswith('{"machine_settings"')]
    section = json.loads(block)["machine_settings"]
    model = api.MachineSettingsIn.model_validate(section)
    assert model.accepts == ["jobs_enabled", "jobs_kinds"]
    assert model.applied is not None and model.applied.state == "applied"


def test_no_em_dash_in_the_account_section():
    text = API_MD.read_text(encoding="utf-8")
    start = text.index("## 4a. Account")
    end = text.index("## 5. Admin", start)
    # The detail sentences quoted there are what an editor reads.
    for line in text[start:end].splitlines():
        if line.startswith("|") and "`" in line:
            assert "—" not in line, line
