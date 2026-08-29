"""The upload-only tick (docs/UPLOAD_ONLY_TICK.md, 2026-08-27).

A tick carries a MODE. `full` is every lane; `upload_only` is lane A alone:
the machine sends its video originals for the project and nothing comes
down -- no lane B proxies, and no Syncthing share, because the enforce cycle
never makes one for it. These tests pin the three consumers of a tick (the
plan the companion reads, the share set, the queue views) and the controls.
"""
from __future__ import annotations

import re

import pytest
from fastapi.testclient import TestClient

from ccsync_dashboard import auth
from ccsync_dashboard import db as dbmod
from ccsync_dashboard.api import build_queue_view, build_transfers_view
from ccsync_dashboard.app import create_app
from ccsync_dashboard.collector import Collector
from ccsync_dashboard.settings import Settings
from ccsync_dashboard.syncthing_client import SyncthingClient

from fake_syncthing import EDITOR_ID, SERVER_ID, FakeSyncthing

SECRET = "s"
TOKEN = "tok"
FULL = dbmod.SYNC_MODE_FULL
UP = dbmod.SYNC_MODE_UPLOAD_ONLY


@pytest.fixture
def env(tmp_path):
    db_path = tmp_path / "u.db"
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
        conn.close()


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


def modes_for(client, editor, machine=None):
    url = f"/api/v1/selection/{editor}" + (f"?machine={machine}" if machine else "")
    return {s["slug"]: s["sync_mode"] for s in client.get(url).json()["selection"]}


# -- the tick itself ---------------------------------------------------------


def test_a_tick_is_full_unless_it_says_otherwise(env):
    """What every tick meant before the mode existed, and what an old client
    or a bookmarked URL still means."""
    client, conn, _now = env
    report(client, "ruskin", "DESKTOP-1")
    assert client.put("/api/v1/selection/ruskin/p1?machine=DESKTOP-1").status_code == 200
    assert modes_for(client, "ruskin", "DESKTOP-1") == {"p1": FULL}


def test_an_upload_only_tick_reaches_the_companion_as_such(env):
    client, conn, _now = env
    report(client, "ruskin", "DESKTOP-1")
    r = client.put("/api/v1/selection/ruskin/p1?machine=DESKTOP-1&mode=upload_only")
    assert r.status_code == 200 and r.json()["changed"] is True
    assert modes_for(client, "ruskin", "DESKTOP-1") == {"p1": UP}
    # The companion's own read carries it too.
    client.cookies.delete(auth.COOKIE_NAME)
    body = client.get("/api/v1/selection/ruskin?machine=DESKTOP-1",
                      headers=hdr("ruskin")).json()
    assert [(s["slug"], s["sync_mode"]) for s in body["selection"]] == [("p1", UP)]


def test_re_ticking_in_the_other_mode_switches_it_and_keeps_its_place(env):
    """PUT is idempotent-add for the same mode and a SWITCH for the other.
    The queue position is a separate fact from what the tick carries."""
    client, conn, _now = env
    report(client, "ruskin", "DESKTOP-1")
    client.put("/api/v1/selection/ruskin/p1?machine=DESKTOP-1")
    client.put("/api/v1/selection/ruskin/p2?machine=DESKTOP-1")
    r = client.put("/api/v1/selection/ruskin/p1?machine=DESKTOP-1&mode=upload_only")
    assert r.json()["changed"] is True
    r = client.put("/api/v1/selection/ruskin/p1?machine=DESKTOP-1&mode=upload_only")
    assert r.json()["changed"] is False
    rows = dbmod.selections_for_machine(conn, "ruskin", "DESKTOP-1")
    assert [(s["slug"], s["sync_mode"]) for s in rows] == [("p1", UP), ("p2", FULL)]
    r = client.put("/api/v1/selection/ruskin/p1?machine=DESKTOP-1&mode=full")
    assert r.json()["changed"] is True
    assert modes_for(client, "ruskin", "DESKTOP-1") == {"p1": FULL, "p2": FULL}


def test_a_typo_in_the_mode_is_refused_not_read_as_full(env):
    client, conn, _now = env
    report(client, "ruskin", "DESKTOP-1")
    r = client.put("/api/v1/selection/ruskin/p1?machine=DESKTOP-1&mode=uploadonly")
    assert r.status_code == 400
    assert "upload_only" in r.json()["detail"]
    assert dbmod.selections_for_machine(conn, "ruskin", "DESKTOP-1") == []


def test_the_person_level_tick_carries_the_mode_to_every_computer(env):
    client, conn, _now = env
    report(client, "ruskin", "DESKTOP-1")
    report(client, "ruskin", "LAPTOP-1")
    client.put("/api/v1/selection/ruskin/p1?mode=upload_only")
    for machine in ("DESKTOP-1", "LAPTOP-1"):
        assert modes_for(client, "ruskin", machine) == {"p1": UP}


def test_an_untick_is_the_same_untick_whatever_the_mode(env):
    client, conn, _now = env
    report(client, "ruskin", "DESKTOP-1")
    client.put("/api/v1/selection/ruskin/p1?machine=DESKTOP-1&mode=upload_only")
    r = client.delete("/api/v1/selection/ruskin/p1?machine=DESKTOP-1")
    assert r.json()["changed"] is True
    assert modes_for(client, "ruskin", "DESKTOP-1") == {}


def test_the_wired_machine_refusal_still_applies(env):
    """An upload-only tick on a wired machine makes as little sense as a full
    one: its tree IS the NAS tree, there is nothing to upload."""
    client, conn, _now = env
    report(client, "alex", "RIG", mode="base")
    r = client.put("/api/v1/selection/alex/p1?machine=RIG&mode=upload_only")
    assert r.status_code == 409


# -- the mode survives the plan-level operations ------------------------------


def test_copying_a_plan_copies_the_modes_with_it(env):
    """An upload-only tick copied as a full one would start the very
    download the source was ticked to avoid."""
    client, conn, _now = env
    report(client, "ruskin", "DESKTOP-1")
    report(client, "ruskin", "LAPTOP-1")
    client.put("/api/v1/selection/ruskin/p1?machine=DESKTOP-1&mode=upload_only")
    client.put("/api/v1/selection/ruskin/p2?machine=DESKTOP-1")
    r = client.post("/api/v1/admin/machines/ruskin/LAPTOP-1/copy-plan?source=DESKTOP-1")
    assert r.status_code == 200, r.text
    assert modes_for(client, "ruskin", "LAPTOP-1") == {"p1": UP, "p2": FULL}


def test_the_unassigned_bucket_keeps_the_mode_when_it_is_materialised(env):
    """A tick made before the companion ever reported lands in the bucket;
    the machine's first own row copies the bucket across (dash-core-1), and
    the copy must carry the mode."""
    client, conn, now = env
    dbmod.add_selection(conn, "ruskin", "p1", "owen", now, sync_mode=UP)   # bucket
    conn.commit()
    report(client, "ruskin", "DESKTOP-1")
    assert modes_for(client, "ruskin", "DESKTOP-1") == {"p1": UP}          # inherited
    client.put("/api/v1/selection/ruskin/p2?machine=DESKTOP-1")            # first own row
    assert modes_for(client, "ruskin", "DESKTOP-1") == {"p1": UP, "p2": FULL}


def test_a_renamed_computer_keeps_its_upload_only_ticks(env):
    """The old row is taken off the air between the two reports because a
    rename reboots the computer, and since SYS-18a (2026-08-29) that silence
    is what tells the adoption path a rename from a cloned disk still
    reporting under the first name."""
    client, conn, now = env
    report(client, "ruskin", "OLD-NAME", machine_id="mid-1")
    client.put("/api/v1/selection/ruskin/p1?machine=OLD-NAME&mode=upload_only")
    conn.execute("UPDATE machines SET last_seen='2026-08-26T09:00:00+00:00' "
                 "WHERE editor_username='ruskin' AND machine='OLD-NAME'")
    conn.commit()
    report(client, "ruskin", "NEW-NAME", machine_id="mid-1")
    assert modes_for(client, "ruskin", "NEW-NAME") == {"p1": UP}


# -- the three consumers -----------------------------------------------------


def test_the_mode_filter_never_hands_a_machine_the_bucket_it_would_not_get(env):
    """The bucket applies only to a machine with NO rows of its own -- and
    "its own" is decided before the mode filter, or a laptop holding one
    upload-only tick would inherit every full tick in the bucket the moment
    the enforce cycle asked for full ticks only."""
    client, conn, now = env
    report(client, "ruskin", "LAPTOP-1")
    # The laptop's own row FIRST: a tick on a machine materialises the bucket
    # onto it (dash-core-1), so a bucket row written before it would simply
    # become the laptop's own. The shape under test is a machine with a plan
    # of its own beside a bucket row it must not inherit.
    dbmod.add_selection(conn, "ruskin", "p2", "owen", now, machine="LAPTOP-1",
                        sync_mode=UP)
    dbmod.add_selection(conn, "ruskin", "p1", "owen", now)                       # bucket, full
    conn.commit()
    full = dbmod.fetch_machine_selections(conn, sync_modes=(FULL,))
    assert full.get("p1", []) == []
    assert full.get("p2", []) == []
    up = dbmod.fetch_machine_selections(conn, sync_modes=(UP,))
    assert up == {"p2": [("ruskin", "LAPTOP-1")]}
    # Unfiltered: exactly what it always answered.
    assert dbmod.fetch_machine_selections(conn) == {"p2": [("ruskin", "LAPTOP-1")]}


@pytest.fixture
def fake():
    server = FakeSyncthing().start()
    yield server
    server.stop()


@pytest.fixture
def collector(fake):
    settings = Settings(syncthing_url=fake.url, syncthing_api_key="k")
    return Collector(settings, client=SyncthingClient(fake.url, "k", timeout=5))


def _folder_devices(fake, slug):
    folder = next(f for f in fake.state["folders"] if f["id"] == slug)
    return {d["deviceID"] for d in folder.get("devices", [])}


def test_the_enforce_cycle_never_shares_a_folder_for_an_upload_only_tick(
        conn, fake, collector):
    """THE property: nothing comes down. Lane C is a Syncthing share, and an
    upload-only machine is simply not in the share set -- not a `sendonly`
    folder, which would exist, index, and read as permanently out of sync on
    every page that draws completion."""
    collector.run_cycle(conn, ["config", "enforce"])      # seeds jsmith's existing share
    now = dbmod.utcnow_iso()
    dbmod.upsert_machine(conn, "jsmith", "JS-DESKTOP", now, syncthing_device_id=EDITOR_ID)
    dbmod.add_selection(conn, "jsmith", "2025-ff4-nuclear", "jsmith", now,
                        machine="JS-DESKTOP", sync_mode=UP)
    conn.commit()
    collector.run_cycle(conn, ["enforce"])
    assert EDITOR_ID not in _folder_devices(fake, "2025-ff4-nuclear")
    assert SERVER_ID in _folder_devices(fake, "2025-ff4-nuclear")

    # ...and switching it back to a full tick shares it again.
    dbmod.add_selection(conn, "jsmith", "2025-ff4-nuclear", "jsmith", now,
                        machine="JS-DESKTOP", sync_mode=FULL)
    conn.commit()
    collector.run_cycle(conn, ["enforce"])
    assert EDITOR_ID in _folder_devices(fake, "2025-ff4-nuclear")


def test_an_upload_only_borrower_gets_no_lender_folder_either(conn, fake, collector):
    """A borrower's device normally receives the lender's folder for the
    borrowed subtree (SHARED_FOLDERS_PLAN.md §4.1). Upload-only downloads
    nothing, borrowed or not."""
    collector.run_cycle(conn, ["config", "enforce"])
    now = dbmod.utcnow_iso()
    fake.state["folders"].append({
        "id": "2026-ff5-borrower", "label": "2026/FF5/Borrower",
        "path": "/data/Projects/2026/FF5/Borrower",
        "devices": [{"deviceID": SERVER_ID}], "type": "sendreceive", "ignorePerms": True,
    })
    dbmod.upsert_project(conn, "2026-ff5-borrower", "2026/FF5/Borrower",
                         "/data/Projects/2026/FF5/Borrower", now)
    dbmod.replace_project_links(conn, "2026-ff5-borrower", [{
        "declared_path": "2025/FF4/Nuclear/LUTs", "lender_slug": "2025-ff4-nuclear",
        "sub_rel": "LUTs", "status": "ok", "detail": None}], now)
    dbmod.upsert_machine(conn, "jsmith", "JS-DESKTOP", now, syncthing_device_id=EDITOR_ID)
    dbmod.remove_selection(conn, "jsmith", "2025-ff4-nuclear")
    dbmod.add_selection(conn, "jsmith", "2026-ff5-borrower", "jsmith", now,
                        machine="JS-DESKTOP", sync_mode=UP)
    conn.commit()
    collector.run_cycle(conn, ["enforce"])
    assert EDITOR_ID not in _folder_devices(fake, "2026-ff5-borrower")
    assert EDITOR_ID not in _folder_devices(fake, "2025-ff4-nuclear")


def _manifest(conn, editor, machine, slug, now):
    dbmod.upsert_editor_media_project(
        conn, editor=editor, machine=machine, slug=slug, mode="editor",
        n_originals=0, bytes_originals=0, n_proxies=0, bytes_proxies=0,
        truncated=False, now=now)


def test_the_backlog_lists_uploads_but_never_proxies_for_an_upload_only_tick(env):
    """Lane B never runs for it, so the proxies it lacks are not a queue --
    listing them would show a download that is never going to start."""
    client, conn, now = env
    report(client, "ruskin", "DESKTOP-1")
    report(client, "ruskin", "LAPTOP-1")
    client.put("/api/v1/selection/ruskin/p1?machine=DESKTOP-1&mode=upload_only")
    client.put("/api/v1/selection/ruskin/p1?machine=LAPTOP-1")
    pid = conn.execute("SELECT id FROM projects WHERE slug='p1'").fetchone()["id"]
    dbmod.replace_nas_media(conn, pid, [("A/Proxy/a.mov", "proxy", ".mov", 10, 1)],
                            "sig", 1, now)
    for machine in ("DESKTOP-1", "LAPTOP-1"):
        _manifest(conn, "ruskin", machine, "p1", now)
        dbmod.replace_editor_media(
            conn, "ruskin", machine, "p1",
            [("A/b.braw", "original", 100)], now)
    conn.commit()
    rows = {(q["machine"], q["lane"]) for q in build_transfers_view(conn)["queues"]
            if q["slug"] == "p1" and not q.get("pending")}
    assert ("DESKTOP-1", "a") in rows and ("DESKTOP-1", "b") not in rows
    assert ("LAPTOP-1", "a") in rows and ("LAPTOP-1", "b") in rows


def test_an_upload_only_tick_prepares_until_the_first_manifest_then_stops(env):
    """A full tick's GETTING READY clears on a Syncthing completion row. An
    upload-only tick never gets one, so its chip would be permanent (the
    CR-28 shape) -- what clears it is the machine's first file list."""
    client, conn, now = env
    report(client, "ruskin", "DESKTOP-1")
    client.put("/api/v1/selection/ruskin/p1?machine=DESKTOP-1&mode=upload_only")
    pending = [q for q in build_transfers_view(conn)["queues"]
               if q["slug"] == "p1" and q.get("pending")]
    assert len(pending) == 1
    assert pending[0]["lane"] == "a" and pending[0]["direction"] == "up"
    assert pending[0]["upload_only"] is True
    _manifest(conn, "ruskin", "DESKTOP-1", "p1", now)
    conn.commit()
    assert not [q for q in build_transfers_view(conn)["queues"]
                if q["slug"] == "p1" and q.get("pending")]


def test_the_queue_panel_marks_it(env):
    client, conn, now = env
    report(client, "ruskin", "DESKTOP-1")
    client.put("/api/v1/selection/ruskin/p1?machine=DESKTOP-1&mode=upload_only")
    client.put("/api/v1/selection/ruskin/p2?machine=DESKTOP-1")
    items = {i["slug"]: i["upload_only"]
             for i in build_queue_view(conn, "ruskin", machine="DESKTOP-1")["queue"]}
    assert items == {"p1": True, "p2": False}


# -- the controls ------------------------------------------------------------


def test_the_project_page_offers_upload_only_and_the_way_back(env):
    client, conn, _now = env
    report(client, "ruskin", "DESKTOP-1")
    client.cookies.set(auth.COOKIE_NAME, auth.make_session_cookie(SECRET, "ruskin"))
    page = client.get("/project/p1").text
    assert "[ UPLOAD ONLY FOR ME ]" in page and "[ TICK FOR ME ]" in page

    r = client.post("/partials/selection/ruskin/p1/toggle?view=project&mode=upload_only")
    assert r.status_code == 200, r.text
    assert "[ SWITCH TO FULL SYNC ]" in r.text and "[ UNTICK FOR ME ]" in r.text
    assert "[ UP ]" in r.text                       # the SELECTED BY marker
    assert modes_for(client, "ruskin", "DESKTOP-1") == {"p1": UP}

    # A SET, never an untick: pressing it again changes nothing.
    r = client.post("/partials/selection/ruskin/p1/toggle?view=project&mode=upload_only")
    assert modes_for(client, "ruskin", "DESKTOP-1") == {"p1": UP}

    r = client.post("/partials/selection/ruskin/p1/toggle?view=project&mode=full")
    assert "[ SWITCH TO UPLOAD ONLY ]" in r.text
    assert modes_for(client, "ruskin", "DESKTOP-1") == {"p1": FULL}

    # The plain toggle is still the plain toggle.
    client.post("/partials/selection/ruskin/p1/toggle?view=project")
    assert modes_for(client, "ruskin", "DESKTOP-1") == {}


def test_the_sidebar_marks_an_upload_only_project(env):
    client, conn, _now = env
    report(client, "ruskin", "DESKTOP-1")
    client.cookies.set(auth.COOKIE_NAME, auth.make_session_cookie(SECRET, "ruskin"))
    client.put("/api/v1/selection/ruskin/p1?machine=DESKTOP-1&mode=upload_only")
    page = client.get("/project/p1").text
    assert "[ UP ]" in page


def test_the_grid_draws_the_upload_only_half_of_a_cell(env):
    client, conn, _now = env
    report(client, "ruskin", "DESKTOP-1")
    client.put("/api/v1/selection/ruskin/p1?machine=DESKTOP-1&mode=upload_only")
    client.put("/api/v1/selection/ruskin/p2?machine=DESKTOP-1")
    page = client.get("/admin/assignments").text
    boxes = {}
    for tag in re.findall(r"<input[^>]*>", page, re.S):
        if "matrix-upmode" in tag and 'data-editor="ruskin"' in tag:
            slug = re.search(r'data-slug="([^"]+)"', tag).group(1)
            boxes[slug] = "checked" in tag
    assert boxes == {"p1": True, "p2": False}
    # ...and the main tick is checked for both: upload-only IS a tick.
    main = {}
    for tag in re.findall(r"<input[^>]*>", page, re.S):
        if "matrix-check" in tag and 'data-editor="ruskin"' in tag:
            slug = re.search(r'data-slug="([^"]+)"', tag).group(1)
            main[slug] = "checked" in tag
    assert main == {"p1": True, "p2": True}
