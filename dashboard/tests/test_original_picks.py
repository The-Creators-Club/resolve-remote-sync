"""Originals on request, the dashboard half (docs/SELECTIVE_ORIGINALS.md §11 /
§12.3, schema v60, 2026-10-31).

A pick names a file or a folder of camera originals ONE computer wants
brought down beside its proxies. These tests pin the store (keyed per
computer, NFC), the refusals (upload-only with the D9 sentence, unticked,
wired), the wire (`originals` on the selection GET, folder picks expanded
against nas_media and live, absent when there is nothing, never on the
person-level union an old companion reads), what takes picks away (an
untick, a forgotten computer) or moves them (a file move, a rename), and the
project page window ("N of M in", "cannot tell", the version gate).
"""
from __future__ import annotations

import json
import sqlite3
import unicodedata

import pytest
from fastapi.testclient import TestClient

from ccsync_dashboard import auth
from ccsync_dashboard import db as dbmod
from ccsync_dashboard.app import create_app
from ccsync_dashboard.settings import Settings

from conftest import HX

SECRET = "s"
TOKEN = "tok"
SLUG = "p1"
LABEL = "2026/Beyond Nights"
NEW = "0.9.87"
OLD = "0.9.86"


@pytest.fixture
def env(tmp_path):
    db_path = tmp_path / "o.db"
    settings = Settings(db_path=str(db_path), session_secret=SECRET, report_token=TOKEN,
                        admin_users=frozenset({"owen"}))
    app = create_app(settings)
    with TestClient(app) as client:
        conn = dbmod.connect(db_path)
        now = dbmod.utcnow_iso()
        dbmod.upsert_project(conn, SLUG, LABEL, "/x", now)
        dbmod.upsert_project(conn, "p2", "2026/Other", "/y", now)
        conn.commit()
        client.cookies.set(auth.COOKIE_NAME, auth.make_session_cookie(SECRET, "owen"))
        yield client, conn
        conn.close()


def hdr(editor):
    return {"X-CCSync-Token": TOKEN,
            "X-CCSync-Identity": auth.make_identity_token(SECRET, editor)}


def report(client, editor, machine, version=NEW, **extra):
    body = {"editor_name": editor, "machine": machine, "companion_version": version,
            "reported_at": "2026-10-31T10:00:00+00:00", "lanes": []}
    body.update(extra)
    resp = client.post("/api/v1/report", json=body, headers=hdr(editor))
    assert resp.status_code == 200, resp.text


def project_id(conn, slug=SLUG):
    return conn.execute("SELECT id FROM projects WHERE slug=?", (slug,)).fetchone()[0]


def nas(conn, rel, size=100, kind="original", slug=SLUG):
    ext = rel.rsplit(".", 1)[-1]
    conn.execute(
        "INSERT OR REPLACE INTO nas_media (project_id, rel_path, kind, ext, size, mtime_ns,"
        " refreshed_at) VALUES (?, ?, ?, ?, ?, 0, ?)",
        (project_id(conn, slug), dbmod.media_rel_key(rel), kind, ext, size, dbmod.utcnow_iso()))
    conn.commit()


def tick(client, editor, machine, slug=SLUG, mode="full"):
    r = client.put(f"/api/v1/selection/{editor}/{slug}?machine={machine}&mode={mode}")
    assert r.status_code == 200, r.text


def pick(client, editor, machine, add=(), remove=(), slug=SLUG, headers=None, via=None):
    body = {"add": [{"rel": rel, "is_dir": is_dir} for rel, is_dir in add],
            "remove": list(remove)}
    if via:
        body["via"] = via
    return client.put(f"/api/v1/selection/{editor}/{slug}/originals?machine={machine}",
                      json=body, headers=headers or {})


def selection(client, editor, machine=None):
    url = f"/api/v1/selection/{editor}" + (f"?machine={machine}" if machine else "")
    return {s["slug"]: s for s in client.get(url, headers=hdr(editor)).json()["selection"]}


@pytest.fixture
def ruskin(env):
    """ruskin with two computers, the project fully ticked on both, and a
    folder of originals (plus a proxy and a look-alike sibling) on the NAS."""
    client, conn = env
    report(client, "ruskin", "RUSKIN-PC")
    report(client, "ruskin", "RUSKIN-LAPTOP")
    tick(client, "ruskin", "RUSKIN-PC")
    tick(client, "ruskin", "RUSKIN-LAPTOP")
    nas(conn, "Footage_Lusty/A001.braw", 1000)
    nas(conn, "Footage_Lusty/A002.braw", 2000)
    nas(conn, "Footage_Lusty/Proxy/A001.mov", 10, kind="proxy")
    nas(conn, "FootageXLusty/B001.braw", 5000)          # `_` is a LIKE wildcard
    return client, conn


# ---------------------------------------------------------------- schema v60

def test_v60_is_the_head_and_the_list_stays_gapless():
    numbers = [n for n, _ in dbmod._MIGRATION_STEPS]
    assert numbers == list(range(1, dbmod.SCHEMA_VERSION + 1))
    assert dbmod.SCHEMA_VERSION == 60
    assert dict(dbmod._MIGRATION_STEPS)[60] is dbmod.SCHEMA_V60


def test_v60_on_a_v59_database_reaches_the_fresh_shape_and_replays(tmp_path):
    old = dbmod.connect(tmp_path / "v59.db")
    dbmod.migrate(old, [s for s in dbmod._MIGRATION_STEPS if s[0] <= 59])
    dbmod.migrate(old)
    assert old.execute("PRAGMA user_version").fetchone()[0] == 60
    fresh = sqlite3.connect(":memory:")
    dbmod.migrate(fresh)
    cols = lambda c: [tuple(r)[1:] for r in c.execute("PRAGMA table_info(original_picks)")]
    assert cols(old) == cols(fresh)
    assert [r[1] for r in old.execute("PRAGMA table_info(original_picks)")] == [
        "editor_username", "machine", "project_slug", "rel_key", "rel_path", "is_dir",
        "picked_by", "picked_via", "created_at"]
    dbmod.migrate(old)                                # twice is a no-op
    old.close()


# ---------------------------------------------------------------- the PUT

def test_a_pick_belongs_to_one_computer(ruskin):
    client, conn = ruskin
    r = pick(client, "ruskin", "RUSKIN-PC", add=[("Footage_Lusty", True)])
    assert r.status_code == 200, r.text
    assert r.json() == {"ok": True, "added": 1, "removed": 0, "total_bytes": 3000}
    pc = selection(client, "ruskin", "RUSKIN-PC")[SLUG]
    laptop = selection(client, "ruskin", "RUSKIN-LAPTOP")[SLUG]
    assert pc["originals"] == ["Footage_Lusty/A001.braw", "Footage_Lusty/A002.braw"]
    assert "originals" not in laptop


def test_the_same_pick_twice_changes_nothing_and_remove_takes_it(ruskin):
    client, conn = ruskin
    pick(client, "ruskin", "RUSKIN-PC", add=[("Footage_Lusty/A001.braw", False)])
    r = pick(client, "ruskin", "RUSKIN-PC", add=[("Footage_Lusty/A001.braw", False)])
    assert r.json()["added"] == 0 and r.json()["total_bytes"] == 1000
    r = pick(client, "ruskin", "RUSKIN-PC", remove=["Footage_Lusty/A001.braw"])
    assert r.json() == {"ok": True, "added": 0, "removed": 1, "total_bytes": 0}
    assert "originals" not in selection(client, "ruskin", "RUSKIN-PC")[SLUG]


def test_an_upload_only_tick_is_refused_with_a_sentence_that_says_how_to_fix_it(ruskin):
    client, conn = ruskin
    tick(client, "ruskin", "RUSKIN-PC", mode="upload_only")
    r = pick(client, "ruskin", "RUSKIN-PC", add=[("Footage_Lusty", True)])
    assert r.status_code == 409
    assert r.json()["detail"] == (
        f"{LABEL} is set to upload only on RUSKIN-PC, so nothing comes down to it. "
        "Switch it to full sync on the dashboard first.")
    assert dbmod.original_picks(conn) == []


def test_a_project_not_ticked_on_that_computer_is_refused(ruskin):
    client, conn = ruskin
    nas(conn, "Cam/C001.braw", slug="p2")
    r = pick(client, "ruskin", "RUSKIN-PC", add=[("Cam", True)], slug="p2")
    assert r.status_code == 409
    assert "is not ticked on RUSKIN-PC" in r.json()["detail"]
    assert "Tick it for RUSKIN-PC first" in r.json()["detail"]


def test_a_wired_computer_is_refused(env):
    client, conn = env
    report(client, "alex", "RIG", mode="base")
    report(client, "alex", "LAPTOP", mode="editor")
    tick(client, "alex", "LAPTOP")
    r = pick(client, "alex", "RIG", add=[("Footage_Lusty", True)])
    assert r.status_code == 409
    assert "RIG is wired to the server" in r.json()["detail"]


def test_a_pick_made_before_the_tick_went_upload_only_can_still_be_removed(ruskin):
    """And it stops coming down at once: an upload-only tick brings nothing."""
    client, conn = ruskin
    pick(client, "ruskin", "RUSKIN-PC", add=[("Footage_Lusty", True)])
    tick(client, "ruskin", "RUSKIN-PC", mode="upload_only")
    assert "originals" not in selection(client, "ruskin", "RUSKIN-PC")[SLUG]
    r = pick(client, "ruskin", "RUSKIN-PC", remove=["Footage_Lusty"])
    assert r.status_code == 200 and r.json()["removed"] == 1


@pytest.mark.parametrize("rel", [
    "../Other/A.braw", "Footage_Lusty/../../x.braw", "/Projects/2026/x.braw",
    "\\\\nas\\share\\x.braw", "P:\\Projects\\2026\\x.braw", "C:/x.braw",
    "Footage_Lusty/Proxy/A001.mov", ".ccsync-project",
])
def test_a_path_outside_the_project_or_not_footage_is_refused(ruskin, rel):
    client, conn = ruskin
    r = pick(client, "ruskin", "RUSKIN-PC", add=[(rel, False)])
    assert r.status_code == 400, (rel, r.text)
    assert dbmod.original_picks(conn) == []


def test_the_computer_must_be_named_and_known(ruskin):
    client, conn = ruskin
    r = client.put(f"/api/v1/selection/ruskin/{SLUG}/originals",
                   json={"add": [{"rel": "Footage_Lusty", "is_dir": True}]})
    assert r.status_code == 400
    assert pick(client, "ruskin", "NOT-A-PC", add=[("Footage_Lusty", True)]).status_code == 404
    assert pick(client, "ruskin", "RUSKIN-PC", add=[("Footage_Lusty", True)],
                via="telepathy").status_code == 400


def test_nfc_and_nfd_spellings_are_one_pick(ruskin):
    """CR-90: a Mac's Resolve hands the NFD spelling of the same folder a
    Windows page picked in NFC."""
    client, conn = ruskin
    name = "Matej Šimalčík"
    nfd = unicodedata.normalize("NFD", name)
    nas(conn, f"{name}/D001.braw", 7)
    pick(client, "ruskin", "RUSKIN-PC", add=[(name, True)])
    r = pick(client, "ruskin", "RUSKIN-PC", add=[(nfd, True)], via="resolve")
    assert r.json()["added"] == 0
    assert len(dbmod.original_picks(conn)) == 1
    assert selection(client, "ruskin", "RUSKIN-PC")[SLUG]["originals"] == [
        unicodedata.normalize("NFC", f"{name}/D001.braw")]
    r = pick(client, "ruskin", "RUSKIN-PC", remove=[nfd])
    assert r.json()["removed"] == 1 and dbmod.original_picks(conn) == []


def test_every_change_is_one_audit_row_with_a_username_actor(ruskin):
    client, conn = ruskin
    pick(client, "ruskin", "RUSKIN-PC", add=[("Footage_Lusty", True)])
    pick(client, "ruskin", "RUSKIN-PC", remove=["Footage_Lusty"],
         headers=hdr("ruskin"))
    rows = dbmod.fetch_audit(conn, actions=("originals.pick", "originals.unpick"))
    assert [(r["action"], r["actor"], r["subject"]) for r in rows] == [
        ("originals.unpick", "ruskin", SLUG), ("originals.pick", "owen", SLUG)]
    assert rows[1]["detail"]["machine"] == "RUSKIN-PC"
    assert rows[1]["detail"]["picks"] == [{"rel": "Footage_Lusty", "is_dir": True}]
    # A no-op writes nothing.
    pick(client, "ruskin", "RUSKIN-PC", remove=["Footage_Lusty"])
    assert len(dbmod.fetch_audit(conn, actions=("originals.unpick",))) == 1


# ---------------------------------------------------------------- who may pick

def test_the_companion_picks_for_its_own_editor_only(ruskin):
    client, conn = ruskin
    client.cookies.delete(auth.COOKIE_NAME)
    r = pick(client, "ruskin", "RUSKIN-PC", add=[("Footage_Lusty/A001.braw", False)],
             headers=hdr("ruskin"), via="resolve")
    assert r.status_code == 200, r.text
    [row] = dbmod.original_picks(conn)
    assert (row["picked_by"], row["picked_via"]) == ("ruskin", "resolve")
    r = pick(client, "ruskin", "RUSKIN-PC", add=[("Footage_Lusty", True)],
             headers=hdr("leso"))
    assert r.status_code == 401
    r = pick(client, "ruskin", "RUSKIN-PC", add=[("Footage_Lusty", True)])
    assert r.status_code == 401                       # nobody at all


def test_an_editor_picks_for_their_own_computers_and_an_admin_for_anyone(ruskin):
    client, conn = ruskin
    client.cookies.set(auth.COOKIE_NAME, auth.make_session_cookie(SECRET, "leso"))
    r = pick(client, "ruskin", "RUSKIN-PC", add=[("Footage_Lusty", True)])
    assert r.status_code == 403
    client.cookies.set(auth.COOKIE_NAME, auth.make_session_cookie(SECRET, "ruskin"))
    assert pick(client, "ruskin", "RUSKIN-PC", add=[("Footage_Lusty", True)]).status_code == 200
    client.cookies.set(auth.COOKIE_NAME, auth.make_session_cookie(SECRET, "owen"))
    assert pick(client, "ruskin", "RUSKIN-LAPTOP",
                add=[("Footage_Lusty", True)]).status_code == 200


# ---------------------------------------------------------------- the GET

def test_a_folder_pick_expands_to_originals_only_and_is_a_live_rule(ruskin):
    client, conn = ruskin
    pick(client, "ruskin", "RUSKIN-PC", add=[("Footage_Lusty", True)])
    got = selection(client, "ruskin", "RUSKIN-PC")[SLUG]["originals"]
    assert got == ["Footage_Lusty/A001.braw", "Footage_Lusty/A002.braw"]   # no proxy, no sibling
    nas(conn, "Footage_Lusty/Day2/A003.braw", 3000)                       # uploaded later (D3)
    got = selection(client, "ruskin", "RUSKIN-PC")[SLUG]["originals"]
    assert got == ["Footage_Lusty/A001.braw", "Footage_Lusty/A002.braw",
                   "Footage_Lusty/Day2/A003.braw"]


def test_a_file_pick_the_walk_has_not_seen_yet_is_still_handed_over(ruskin):
    """Picked in Resolve minutes after upload: the companion re-lists the NAS
    and drops it if it is not really there."""
    client, conn = ruskin
    pick(client, "ruskin", "RUSKIN-PC", add=[("New/Z001.braw", False)], via="resolve")
    assert selection(client, "ruskin", "RUSKIN-PC")[SLUG]["originals"] == ["New/Z001.braw"]


def test_an_old_companion_sees_an_otherwise_identical_selection(ruskin):
    client, conn = ruskin
    before_pc = client.get("/api/v1/selection/ruskin?machine=RUSKIN-PC",
                           headers=hdr("ruskin")).json()
    before_person = client.get("/api/v1/selection/ruskin", headers=hdr("ruskin")).json()
    pick(client, "ruskin", "RUSKIN-PC", add=[("Footage_Lusty", True)])
    after_pc = client.get("/api/v1/selection/ruskin?machine=RUSKIN-PC",
                          headers=hdr("ruskin")).json()
    after_person = client.get("/api/v1/selection/ruskin", headers=hdr("ruskin")).json()
    for body in (before_pc, after_pc, before_person, after_person):
        body.pop("generated_at")
    assert after_pc["selection"][0].pop("originals")
    assert after_pc == before_pc
    # The person-level union (what a companion too old to name itself reads)
    # never carries a computer's picks.
    assert after_person == before_person
    assert all("originals" not in s for s in after_person["selection"])


# ---------------------------------------------------------------- what takes picks away

def test_unticking_a_project_on_a_computer_drops_its_picks_there_only(ruskin):
    client, conn = ruskin
    pick(client, "ruskin", "RUSKIN-PC", add=[("Footage_Lusty", True)])
    pick(client, "ruskin", "RUSKIN-LAPTOP", add=[("Footage_Lusty", True)])
    assert client.delete(f"/api/v1/selection/ruskin/{SLUG}?machine=RUSKIN-PC").status_code == 200
    assert [p["machine"] for p in dbmod.original_picks(conn)] == ["RUSKIN-LAPTOP"]
    client.delete(f"/api/v1/selection/ruskin/{SLUG}")                 # every computer
    assert dbmod.original_picks(conn) == []


def test_forgetting_a_computer_takes_its_picks(ruskin):
    client, conn = ruskin
    pick(client, "ruskin", "RUSKIN-PC", add=[("Footage_Lusty", True)])
    out = dbmod.forget_machine(conn, "ruskin", "RUSKIN-PC")
    assert out["deleted"]["original_picks"] == 1


def test_a_renamed_computer_keeps_its_picks(ruskin):
    client, conn = ruskin
    pick(client, "ruskin", "RUSKIN-PC", add=[("Footage_Lusty", True)])
    assert dbmod.adopt_renamed_machine(conn, "ruskin", "RUSKIN-PC", "RUSKIN-NEW")
    assert [p["machine"] for p in dbmod.original_picks(conn)] == ["RUSKIN-NEW"]


def test_a_file_move_rewrites_the_picks_on_it(ruskin):
    client, conn = ruskin
    pick(client, "ruskin", "RUSKIN-PC", add=[("Footage_Lusty", True),
                                             ("FootageXLusty/B001.braw", False)])
    now = dbmod.utcnow_iso()
    # A detected hand move is recorded as done: it moves the picks at once.
    dbmod.record_file_move(
        conn, from_slug=SLUG, from_project_rel=LABEL, from_rel="Footage_Lusty",
        to_slug=SLUG, to_project_rel=LABEL, to_rel="Shoots/Lusty", is_dir=True,
        proxies_moved=0, requested_by="owen", now=now, targets=[],
        state=dbmod.FILE_MOVE_DONE)
    # The button's move is pending first and moves them on completion.
    move_id = dbmod.record_file_move(
        conn, from_slug=SLUG, from_project_rel=LABEL, from_rel="FootageXLusty/B001.braw",
        to_slug="p2", to_project_rel="2026/Other", to_rel="B001.braw", is_dir=False,
        proxies_moved=0, requested_by="owen", now=now, targets=[],
        state=dbmod.FILE_MOVE_PENDING)
    assert {p["rel_key"] for p in dbmod.original_picks(conn)} == {
        "Shoots/Lusty", "FootageXLusty/B001.braw"}
    dbmod.complete_file_move(conn, move_id, state=dbmod.FILE_MOVE_DONE)
    assert {(p["project_slug"], p["rel_key"], p["is_dir"])
            for p in dbmod.original_picks(conn)} == {
        (SLUG, "Shoots/Lusty", 1), ("p2", "B001.braw", 0)}


# ---------------------------------------------------------------- the project page

def originals_window(client, **params):
    q = "&".join(f"{k}={v}" for k, v in params.items())
    r = client.get(f"/partials/project/{SLUG}/originals" + (f"?{q}" if q else ""), headers=HX)
    assert r.status_code == 200, r.text
    return r.text


def test_the_window_lists_every_pick_with_its_progress(ruskin):
    client, conn = ruskin
    pick(client, "ruskin", "RUSKIN-PC", add=[("Footage_Lusty", True)])
    now = dbmod.utcnow_iso()
    dbmod.upsert_editor_media_project(
        conn, editor="ruskin", machine="RUSKIN-PC", slug=SLUG, mode="editor",
        n_originals=1, bytes_originals=1000, n_proxies=0, bytes_proxies=0,
        truncated=False, now=now)
    dbmod.replace_editor_media(conn, "ruskin", "RUSKIN-PC", SLUG,
                               [("Footage_Lusty/A001.braw", "original", 1000)], now)
    conn.commit()
    html = originals_window(client)
    assert "RUSKIN-PC" in html and "Footage_Lusty" in html
    assert "1 of 2 in" in html


def test_a_computer_that_withholds_its_file_list_reads_cannot_tell(ruskin):
    client, conn = ruskin
    pick(client, "ruskin", "RUSKIN-PC", add=[("Footage_Lusty", True)])
    conn.execute("UPDATE machine_state SET report_optouts=? WHERE editor_username=?"
                 " AND machine=?", (json.dumps(["local_manifest"]), "ruskin", "RUSKIN-PC"))
    conn.commit()
    html = originals_window(client)
    assert "cannot tell" in html
    assert " of 2 in" not in html


def test_a_computer_below_0_9_87_cannot_be_offered_a_pick(env):
    client, conn = env
    report(client, "ruskin", "OLD-PC", version=OLD)
    tick(client, "ruskin", "OLD-PC")
    nas(conn, "Footage_Lusty/A001.braw")
    html = originals_window(client)
    assert 'value="ruskin::OLD-PC" disabled' in html
    assert "ignores originals picks" in html
    html = originals_window(client, target="ruskin::OLD-PC")
    assert "Bring this folder" not in html
    assert "0.9.87 or later" in html


def test_browsing_and_picking_from_the_page(ruskin):
    client, conn = ruskin
    html = originals_window(client, target="ruskin::RUSKIN-PC")
    assert "Footage_Lusty/" in html and "Bring this folder" in html
    html = originals_window(client, target="ruskin::RUSKIN-PC", dir="Footage_Lusty")
    assert "A001.braw" in html and "Proxy" not in html.split("Originals of")[1]
    r = client.post(f"/partials/project/{SLUG}/originals", headers=HX, data={
        "action": "add", "editor": "ruskin", "machine": "RUSKIN-PC",
        "rel": "Footage_Lusty", "is_dir": "1", "dir": ""})
    assert r.status_code == 200
    assert "comes down to RUSKIN-PC" in r.text
    [row] = dbmod.original_picks(conn)
    assert (row["rel_key"], row["is_dir"], row["picked_via"]) == ("Footage_Lusty", 1, "dashboard")


def test_the_page_shows_the_upload_only_refusal_inline(ruskin):
    client, conn = ruskin
    tick(client, "ruskin", "RUSKIN-PC", mode="upload_only")
    r = client.post(f"/partials/project/{SLUG}/originals", headers=HX, data={
        "action": "add", "editor": "ruskin", "machine": "RUSKIN-PC",
        "rel": "Footage_Lusty", "is_dir": "1"})
    assert r.status_code == 200
    assert "Switch it to full sync on the dashboard first." in r.text


def test_an_editor_sees_every_pick_but_buttons_only_for_their_own(ruskin):
    client, conn = ruskin
    report(client, "leso", "LESO-MAC")
    tick(client, "leso", "LESO-MAC")
    pick(client, "ruskin", "RUSKIN-PC", add=[("Footage_Lusty", True)])
    client.cookies.set(auth.COOKIE_NAME, auth.make_session_cookie(SECRET, "leso"))
    html = originals_window(client)
    assert "RUSKIN-PC" in html                         # D2: visible to everyone
    assert 'name="machine" value="RUSKIN-PC"' not in html   # but no Stop button
    assert 'value="leso::LESO-MAC"' in html and 'value="ruskin::RUSKIN-PC"' not in html
    r = client.post(f"/partials/project/{SLUG}/originals", headers=HX, data={
        "action": "remove", "editor": "ruskin", "machine": "RUSKIN-PC",
        "rel": "Footage_Lusty"})
    assert r.status_code == 403
    assert len(dbmod.original_picks(conn)) == 1


def test_the_project_page_carries_the_window(ruskin):
    client, conn = ruskin
    r = client.get(f"/project/{SLUG}")
    assert r.status_code == 200
    assert f'hx-get="/partials/project/{SLUG}/originals"' in r.text
