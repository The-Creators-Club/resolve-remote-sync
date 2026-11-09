"""The Footage Sorter mounted at /sorter (sorter.py), against a real footage-sorter checkout.

The checkout is FOOTAGE_SORTER_SRC, or ../footage-sorter beside this repo (the
E:\\Projects\\Editing layout); the module's own tests live there. These test the
mount: the tri-state, login and CSRF, the identity the gate stamps (and strips),
and one move end to end, a staged clip renamed into Projects on a temp pool.
"""

from __future__ import annotations

import json
import os
import sys
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from ccsync_dashboard import auth, sorter
from ccsync_dashboard.app import create_app
from ccsync_dashboard.settings import Settings

SECRET = "test-secret-not-a-real-one"
TOKEN = "report-token-not-a-real-one"
SRC = os.environ.get("FOOTAGE_SORTER_SRC") or str(Path(__file__).resolve().parents[3] / "footage-sorter")
pytestmark = pytest.mark.skipif(not (Path(SRC) / "footage_sorter" / "engine.py").is_file(),
                                reason=f"no footage-sorter checkout at {SRC}")


@pytest.fixture(autouse=True)
def _clean(monkeypatch):
    monkeypatch.delenv("SORTER_SRC", raising=False)
    yield
    for name in [n for n in sys.modules if n.split(".")[0] == "footage_sorter"]:
        del sys.modules[name]
    while SRC in sys.path:
        sys.path.remove(SRC)


def make_pool(tmp_path):
    pool = tmp_path / "pool"
    staged = pool / "Temp Transfer" / "2026-11-07 12.26-14.35 A-CAM"
    projects = pool / "Creators_Club" / "Projects"
    staged.mkdir(parents=True)
    projects.mkdir(parents=True)
    (staged / "fx3_0001.MP4").write_bytes(b"v" * 1000)
    data = tmp_path / "sorter-data"
    data.mkdir()
    clip = {"id": "c1", "stem": "fx3_0001", "kind": "video", "camera": "A-CAM", "sourceRoot": str(pool / "Temp Transfer"),
            "sourceFolder": staged.name, "files": [{"path": str(staged / "fx3_0001.MP4"), "role": "master", "size": 1000, "mtimeMs": 0}],
            "folder": None, "fileCount": 1, "bytes": 1000, "recordedAt": "2026-11-07T12:26:00+08:00", "durationSec": None,
            "umid": None, "model": None, "key": "fs:fx3_0001|1000|2026-11-07"}
    (data / "clips.json").write_text(json.dumps({"scannedAt": "2026-11-09T00:00:00Z", "clips": [clip]}), encoding="utf-8")
    host = {"sourceRoots": [str(pool / "Temp Transfer")], "destRoot": str(projects), "ffmpegDir": ""}
    return pool, data, projects, staged, host


def make_settings(tmp_path, **kw):
    projects = tmp_path / "tree" / "Projects"
    projects.mkdir(parents=True, exist_ok=True)
    return Settings(db_path=str(tmp_path / "dash.db"), session_secret=SECRET, admin_users=frozenset({"owen"}),
                    projects_dir=str(projects), report_token=TOKEN, **kw)


def login(client, user):
    client.cookies.set(auth.COOKIE_NAME, auth.make_session_cookie(SECRET, user))
    return client.get("/sorter/api/whoami").json()


# ------------------------------------------------------------------ the tri-state

def test_off_by_default_and_the_dashboard_boots(tmp_path):
    app = create_app(make_settings(tmp_path))
    assert app.state.sorter_status == sorter.DISABLED and not app.state.sorter_mounted


@pytest.mark.parametrize("kw,status,words", [
    ({"sorter_src": "/no/such/checkout", "sorter_data": "x"}, sorter.ABSENT, "not there"),
    ({"sorter_data": ""}, sorter.DISABLED, "DASH_SORTER_DATA"),
    ({"sorter_settings": "{not json"}, sorter.ABSENT, "not JSON"),
    ({"sorter_settings": json.dumps({"destRoot": "/no/pool/Projects"})}, sorter.ABSENT, "pool is not mounted"),
])
def test_every_way_it_does_not_mount_says_why(tmp_path, kw, status, words):
    base = {"sorter_enabled": True, "sorter_src": SRC, "sorter_data": str(tmp_path / "d")}
    app = create_app(make_settings(tmp_path, **{**base, **kw}))
    assert app.state.sorter_status == status and words in app.state.sorter_detail


@pytest.fixture
def mounted(tmp_path):
    pool, data, projects, staged, host = make_pool(tmp_path)
    settings = make_settings(tmp_path, sorter_enabled=True, sorter_src=SRC, sorter_data=str(data),
                             sorter_settings=json.dumps(host))
    app = create_app(settings)
    assert app.state.sorter_status == sorter.MOUNTED, app.state.sorter_detail
    with TestClient(app) as client:
        yield client, app, projects, staged


# ------------------------------------------------------------------ login, CSRF, identity

def test_login_is_required(mounted):
    client, _app, _p, _s = mounted
    api = client.get("/sorter/api/state")
    assert api.status_code == 401 and api.json()["detail"] == "login required"
    page = client.get("/sorter/", follow_redirects=False)
    assert page.status_code == 303 and "/login" in page.headers["location"]


def test_bare_prefix_redirects_to_the_slash(mounted):
    client, *_ = mounted
    login(client, "owen")
    r = client.get("/sorter", follow_redirects=False)
    assert r.status_code == 307 and r.headers["location"].endswith("/sorter/")


def test_whoami_page_and_state(mounted):
    client, app, _p, _s = mounted
    me = login(client, "owen")
    assert me["user"] == "owen" and me["admin"] is True and me["csrf"]
    page = client.get("/sorter/")
    assert page.status_code == 200 and "Footage" in page.text
    state = client.get("/sorter/api/state")
    assert state.status_code == 200 and [c["id"] for c in state.json()["clips"]] == ["c1"]
    assert state.headers.get("etag")
    assert client.get("/sorter/api/state", headers={"if-none-match": state.headers["etag"]}).status_code == 304


STRONG = "kX9-quiet-harbour-42-zephyr"   # passes the boot secret floor
PASSWORD = "correct-horse-battery"


def test_writes_need_the_csrf_token(tmp_path, monkeypatch):
    """Strict, as deployed: a real sign-in (a TRACKED session) and the CSRF gate live.

    The sorter is an ordinary session route, not an exemption: the token the gate's
    whoami hands the page is the one the dashboard's csrf_gate checks.
    """
    from ccsync_dashboard import db
    monkeypatch.delenv("DASH_DEV_INSECURE", raising=False)
    _pool, data, _projects, _staged, host = make_pool(tmp_path)
    settings = Settings(db_path=str(tmp_path / "strict.db"), session_secret=STRONG, admin_users=frozenset({"owen"}),
                        smb_host="nas.test", sorter_enabled=True, sorter_src=SRC, sorter_data=str(data),
                        sorter_settings=json.dumps(host))
    conn = db.connect(settings.db_path)
    try:
        db.migrate(conn)
    finally:
        conn.close()
    app = create_app(settings)
    app.state.credential_verifier = lambda s, u, p: p == PASSWORD
    with TestClient(app) as client:
        signed = client.post("/api/v1/login", json={"username": "owen", "password": PASSWORD})
        assert signed.status_code == 200, signed.text
        me = client.get("/sorter/api/whoami").json()
        assert me["user"] == "owen" and me["csrf"] == signed.json()["csrf"]
        body = {"clipIds": ["c1"], "dest": "2026/Test"}
        refused = client.post("/sorter/api/assign", json=body)
        assert refused.status_code == 403 and "CSRF" in refused.json()["detail"]
        r = client.post("/sorter/api/assign", json=body, headers={"x-csrf-token": me["csrf"]})
        assert r.status_code == 200 and r.json()["assigned"] == 1


def test_a_forged_identity_header_is_stripped(mounted):
    """bob is logged in but not an admin; claiming admin in a header changes nothing."""
    client, *_ = mounted
    me = login(client, "bob")
    assert me["admin"] is False
    h = {"x-csrf-token": me["csrf"], "x-sorter-admin": "1", "x-sorter-user": "owen"}
    client.post("/sorter/api/assign", json={"clipIds": ["c1"], "dest": "2026/X"}, headers=h)
    plan = client.post("/sorter/api/moves/plan", json={}, headers=h).json()
    r = client.post(f"/sorter/api/moves/{plan['id']}/execute", json={}, headers=h)
    assert r.status_code == 403 and "admin" in r.json()["error"]


# ------------------------------------------------------------------ a move, end to end

def test_a_staged_clip_moves_into_projects(mounted):
    import time
    client, app, projects, staged = mounted
    me = login(client, "owen")
    h = {"x-csrf-token": me["csrf"]}
    assert client.post("/sorter/api/assign", json={"clipIds": ["c1"], "dest": "2026/FF5/Interviewees/Brian"}, headers=h).status_code == 200
    plan = client.post("/sorter/api/moves/plan", json={}, headers=h).json()
    assert plan["dryRun"]["ok"], plan["dryRun"]
    assert plan["entries"] == 1
    r = client.post(f"/sorter/api/moves/{plan['id']}/execute", json={}, headers=h)
    assert r.status_code == 200
    for _ in range(100):
        m = client.get(f"/sorter/api/moves/{plan['id']}").json()
        if m["state"] != "moving":
            break
        time.sleep(0.05)
    assert m["state"] == "done", m
    moved = projects / "2026" / "FF5" / "Interviewees" / "Brian" / "fx3_0001.MP4"
    assert moved.read_bytes() == b"v" * 1000 and not (staged / "fx3_0001.MP4").exists()
    # who did it is in the move journal
    journal = Path(app.state.sorter_engine.paths.logs) / "move-journal.jsonl"
    assert '"by":"owen"' in journal.read_text(encoding="utf-8").replace(" ", "")


# ------------------------------------------------------------------ card ingest through the companion

def fleet_headers(editor):
    return {"X-CCSync-Token": TOKEN, "X-CCSync-Identity": auth.make_identity_token(SECRET, editor)}


CARD = {"serial": "1038701C", "label": "SD-3", "drive": "L:", "kind": "sony", "capacity": 128 * 10**9, "free": 10**9,
        "files": [["PRIVATE/M4ROOT/CLIP/C0001.MP4", 4000, 1786236852123.0],
                  ["PRIVATE/M4ROOT/CLIP/C0002.MP4", 5000, 1786236952123.0]],
        "texts": {}, "wav": {}}


def test_the_card_report_needs_the_fleet_credential(mounted):
    client, *_ = mounted
    login(client, "owen")                      # the engine has loaded
    client.cookies.clear()
    # no credential: the login gate turns it away (a 303 to /login) before the route is reached
    assert client.post("/sorter/agent/cards", json={"machine": "creator-1", "cards": [CARD]},
                       follow_redirects=False).status_code in (303, 401, 403)
    # a token without the signed identity reaches the route, and the route refuses it
    assert client.post("/sorter/agent/cards", json={"machine": "creator-1", "cards": [CARD]},
                       headers={"X-CCSync-Token": TOKEN}, follow_redirects=False).status_code == 403
    r = client.post("/sorter/agent/cards", json={"machine": "creator-1", "cards": [CARD]}, headers=fleet_headers("alex"))
    assert r.status_code == 200, r.text
    assert client.post("/sorter/agent/cards", json={"cards": [CARD]}, headers=fleet_headers("alex")).status_code == 422


def test_a_card_is_copied_by_the_machine_that_holds_it(mounted, tmp_path):
    from ccsync_dashboard import db
    client, app, projects, staged = mounted
    me = login(client, "owen")
    h = {"x-csrf-token": me["csrf"]}
    client.cookies.clear()
    assert client.post("/sorter/agent/cards", json={"machine": "creator-1", "cards": [CARD]},
                       headers=fleet_headers("alex")).status_code == 200
    login(client, "owen")
    sessions = client.get("/sorter/api/ingest/sessions").json()["sessions"]
    assert len(sessions) == 1 and sessions[0]["clipCount"] == 2
    sid = sessions[0]["id"]
    state = client.get("/sorter/api/state").json()
    assert {c["stem"] for c in state["clips"]} >= {"C0001", "C0002"}
    plan = client.post("/sorter/api/ingest/plan", json={"sessionId": sid, "mode": "stage"}, headers=h).json()
    assert plan["mode"] == "stage" and plan["needBytes"] == 9000
    out = client.post("/sorter/api/ingest/run", json={"sessionId": sid, "planId": plan["planId"]}, headers=h)
    assert out.status_code == 200, out.text
    job_id = out.json()["jobId"]
    conn = db.connect(app.state.settings.db_path)
    try:
        job = db.get_job(conn, job_id)
        assert job["kind"] == "card-ingest" and job["forced"] and job["target_machine"] == "alex/creator-1"
        assert job["inputs"]["files"] == 2 and "copies" not in job["inputs"]
        # the companion claims it (the claim route's own tests cover the claim itself)
        conn.execute("UPDATE jobs SET state='running', claimed_by='alex', claimed_machine='creator-1' WHERE id=?", (job_id,))
        conn.commit()
    finally:
        conn.close()
    client.cookies.clear()
    assert client.get(f"/sorter/agent/ingest/{job_id}", headers=fleet_headers("bob")).status_code == 409
    man = client.get(f"/sorter/agent/ingest/{job_id}", headers=fleet_headers("alex"))
    assert man.status_code == 200, man.text
    copies = man.json()["copies"]
    assert {c["src"] for c in copies} == {"PRIVATE/M4ROOT/CLIP/C0001.MP4", "PRIVATE/M4ROOT/CLIP/C0002.MP4"}
    pool = projects.parent.parent
    receipt = {"copied": [], "skipped": [], "conflicts": [], "failed": []}
    for c in copies:
        dst = pool.joinpath(*c["dst"]["rel"].split("/"))
        dst.parent.mkdir(parents=True, exist_ok=True)
        dst.write_bytes(b"x" * c["size"])
        receipt["copied"].append({**c, "verified": True})
    r = client.post(f"/sorter/agent/ingest/{job_id}/receipt", json=receipt, headers=fleet_headers("alex"))
    assert r.status_code == 200 and r.json()["state"] == "done", r.text
    assert client.post(f"/sorter/agent/ingest/{job_id}/receipt", json=receipt, headers=fleet_headers("alex")).json()["already"]
    login(client, "owen")
    st = client.get(f"/sorter/api/ingest/status?sessionId={sid}").json()
    assert st["state"] == "done" and st["done"] == 2
    assert all(pool.joinpath(*c["dst"]["rel"].split("/")).is_relative_to(pool / "Temp Transfer") for c in copies)
