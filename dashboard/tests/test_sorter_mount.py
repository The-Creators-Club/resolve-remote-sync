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
    sys.path[:] = [p for p in sys.path if not p.replace("\\", "/").endswith("/stub")]    # _stub_checkout's


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


# ------------------------------------------------------------------ card ingest: the hunt's fixes

def _report(client, editor, machine, cards):
    client.cookies.clear()
    return client.post("/sorter/agent/cards", json={"machine": machine, "cards": cards}, headers=fleet_headers(editor))


def _claimed_run(client, app, editor="alex", machine="creator-1", serial_card=CARD):
    """owen presses Copy on a card `editor` reported; `editor`'s machine claims the job. -> (job id, copies)."""
    from ccsync_dashboard import db
    me = login(client, "owen")
    h = {"x-csrf-token": me["csrf"]}
    sid = next(s["id"] for s in client.get("/sorter/api/ingest/sessions").json()["sessions"]
               if s["machine"] == machine and s["serial"] == serial_card["serial"])
    plan = client.post("/sorter/api/ingest/plan", json={"sessionId": sid, "mode": "stage"}, headers=h).json()
    job_id = client.post("/sorter/api/ingest/run", json={"sessionId": sid, "planId": plan["planId"]}, headers=h).json()["jobId"]
    conn = db.connect(app.state.settings.db_path)
    try:
        target = db.get_job(conn, job_id)["target_machine"]
        conn.execute("UPDATE jobs SET state='running', claimed_by=?, claimed_machine=? WHERE id=?", (editor, machine, job_id))
        conn.commit()
    finally:
        conn.close()
    client.cookies.clear()
    copies = client.get(f"/sorter/agent/ingest/{job_id}", headers=fleet_headers(editor)).json()["copies"]
    return job_id, copies, sid, target


def test_two_editors_with_one_machine_name_do_not_share_cards(mounted):
    client, app, *_ = mounted
    login(client, "owen")
    bob_card = {**CARD, "serial": "BOB1"}
    assert _report(client, "alex", "LAPTOP", [CARD]).status_code == 200
    assert _report(client, "bob", "LAPTOP", [bob_card]).status_code == 200
    login(client, "owen")
    assert len(client.get("/sorter/api/ingest/sessions").json()["sessions"]) == 2
    assert _report(client, "bob", "LAPTOP", []).status_code == 200            # bob's empty report is bob's
    login(client, "owen")
    assert [s["serial"] for s in client.get("/sorter/api/ingest/sessions").json()["sessions"]] == [CARD["serial"]]
    assert _report(client, "bob", "LAPTOP", [bob_card]).status_code == 200
    _jid, _copies, _sid, target = _claimed_run(client, app, editor="bob", machine="LAPTOP", serial_card=bob_card)
    assert target == "bob/LAPTOP"


def test_a_report_with_a_drive_that_is_a_server_path_is_dropped(mounted):
    client, app, *_ = mounted
    login(client, "owen")
    _report(client, "alex", "creator-1", [{**CARD, "drive": "/etc"}])
    login(client, "owen")
    assert client.get("/sorter/api/ingest/sessions").json()["sessions"] == []
    flood = [_report(client, "alex", f"fake-{m}", [CARD]).status_code for m in range(6)]
    assert flood[:4] == [200] * 4 and flood[4:] == [413, 413]


def test_a_forged_receipt_lands_nothing(mounted):
    client, app, projects, _staged = mounted
    login(client, "owen")
    assert _report(client, "alex", "creator-1", [CARD]).status_code == 200
    job_id, copies, sid, _t = _claimed_run(client, app)
    forged = {"copied": [{**c, "dst": {"root": "pool", "rel": "../../../../etc/" + c["src"].split("/")[-1]}, "verified": True}
                         for c in copies], "skipped": [], "conflicts": [], "failed": []}
    r = client.post(f"/sorter/agent/ingest/{job_id}/receipt", json=forged, headers=fleet_headers("alex"))
    assert r.status_code == 200 and r.json()["state"] == "error"
    cat = app.state.sorter_engine.catalog
    assert not any(e.get("locations") for e in cat.doc["clips"].values() if e.get("stem") in ("C0001", "C0002")
                   and any(l.get("root") in ("staging", "final") for l in e["locations"]))


def test_a_halted_receipt_keeps_the_run_open_and_the_list_available(mounted):
    client, app, projects, _staged = mounted
    login(client, "owen")
    assert _report(client, "alex", "creator-1", [CARD]).status_code == 200
    job_id, copies, sid, _t = _claimed_run(client, app)
    pool = projects.parent.parent
    first = copies[0]
    dst = pool.joinpath(*first["dst"]["rel"].split("/"))
    dst.parent.mkdir(parents=True, exist_ok=True)
    dst.write_bytes(b"x" * first["size"])
    r = client.post(f"/sorter/agent/ingest/{job_id}/receipt", headers=fleet_headers("alex"), json={
        "copied": [{**first, "verified": True}], "skipped": [], "conflicts": [], "failed": [], "final": False})
    assert r.status_code == 200 and r.json()["final"] is False
    assert client.get(f"/sorter/agent/ingest/{job_id}", headers=fleet_headers("alex")).json()["copies"] == copies
    login(client, "owen")
    st = client.get(f"/sorter/api/ingest/status?sessionId={sid}").json()
    assert st["state"] not in ("done", "error") and st["done"] == 1


def test_the_copy_list_is_refused_to_a_suspended_account_but_its_receipt_is_taken(mounted):
    from ccsync_dashboard import db
    client, app, projects, _staged = mounted
    login(client, "owen")
    assert _report(client, "alex", "creator-1", [CARD]).status_code == 200
    job_id, copies, sid, _t = _claimed_run(client, app)
    conn = db.connect(app.state.settings.db_path)
    try:
        db.record_known_editor(conn, "alex", "admin")
        assert db.suspend_editor(conn, "alex", by="owen", reason="test")
        conn.commit()
    finally:
        conn.close()
    assert client.get(f"/sorter/agent/ingest/{job_id}", headers=fleet_headers("alex")).status_code == 410
    r = client.post(f"/sorter/agent/ingest/{job_id}/receipt", headers=fleet_headers("alex"),
                    json={"copied": [], "skipped": [], "conflicts": [], "failed": []})
    assert r.status_code == 200


def test_progress_is_the_claimants_alone_and_shows_in_the_status(mounted):
    client, app, projects, _staged = mounted
    login(client, "owen")
    assert _report(client, "alex", "creator-1", [CARD]).status_code == 200
    job_id, copies, sid, _t = _claimed_run(client, app)
    total = sum(c["size"] for c in copies)
    body = {"bytesDone": total // 2, "bytesTotal": total, "filesDone": 1, "filesTotal": len(copies),
            "current": "PRIVATE/M4ROOT/CLIP/C0001.MP4", "bps": 1000, "phase": "copy", "copier": "teracopy"}
    url = f"/sorter/agent/ingest/{job_id}/progress"
    client.cookies.clear()
    assert client.post(url, json=body, headers=fleet_headers("bob")).status_code == 409   # not the claimant
    assert client.post("/sorter/agent/ingest/99999/progress", json=body, headers=fleet_headers("alex")).status_code == 404
    r = client.post(url, json=body, headers=fleet_headers("alex"))
    assert r.status_code == 200 and r.json()["ok"] is True, r.text
    login(client, "owen")
    st = client.get(f"/sorter/api/ingest/status?sessionId={sid}").json()
    assert st["bytesDone"] == total // 2 and st["bps"] == 1000 and st["phase"] == "copy"
    assert st["copier"] == "teracopy" and st["currentFile"] == body["current"] and st["filesTotal"] == len(copies)
    assert st["etaSeconds"] == (total - total // 2) // 1000
    assert st["done"] == 0 and st["state"] not in ("done", "error")                   # nothing was applied
    assert not app.state.sorter_engine.catalog.final_paths_for("x")


# ------------------------------------------------------------------ wave-2: load hold, failed load, stop, public URL

def _stub_checkout(tmp_path, mode):
    """A footage_sorter whose engine loads slowly or fails, to test the mount's lifecycle."""
    root = tmp_path / "stub"
    pkg = root / "footage_sorter"
    pkg.mkdir(parents=True)
    (root / "public").mkdir()
    (pkg / "__init__.py").write_text("", encoding="utf-8")
    (pkg / "config.py").write_text("class Paths:\n    def __init__(self, *a): pass\n", encoding="utf-8")
    (pkg / "web.py").write_text("def create_app(engine, trust_identity_headers=False):\n"
                                "    async def app(scope, receive, send):\n"
                                "        await send({'type': 'http.response.start', 'status': 200, 'headers': []})\n"
                                "        await send({'type': 'http.response.body', 'body': b'ok'})\n"
                                "    return app\n", encoding="utf-8")
    (pkg / "engine.py").write_text(
        "import threading, time\n"
        f"MODE = {mode!r}\n"
        "class SorterEngine:\n"
        "    instances = []\n"
        "    def __init__(self, paths, host, **k):\n"
        "        self.host = host; self.clips = []; self.stopped = False; self.started = False\n"
        "        SorterEngine.instances.append(self)\n"
        "    def load(self):\n"
        "        if MODE == 'fail': raise MemoryError('clips.json')\n"
        "        time.sleep(0.6)\n"
        "    def start(self): self.started = True\n"
        "    def stop(self): self.stopped = True\n", encoding="utf-8")
    return str(root)


def _stub_settings(tmp_path, mode, **kw):
    return make_settings(tmp_path, sorter_enabled=True, sorter_src=_stub_checkout(tmp_path, mode),
                         sorter_data=str(tmp_path / "d"), **kw)


def test_a_failed_load_takes_the_mount_back(tmp_path):
    from ccsync_dashboard import mount_status
    app = create_app(_stub_settings(tmp_path, "fail"))
    assert app.state.sorter_holder.ready.wait(5)
    assert app.state.sorter_mounted is False
    status, detail = mount_status.get("sorter")
    assert status == sorter.ABSENT and "could not load" in detail
    with TestClient(app) as client:
        login(client, "owen")
        r = client.get("/sorter/")
        assert r.status_code == 503 and "could not load" in r.json()["error"]


def test_stop_during_the_load_starts_no_engine(tmp_path):
    import time
    app = create_app(_stub_settings(tmp_path, "slow"))
    time.sleep(0.1)
    sorter.stop_sorter(app)
    assert app.state.sorter_holder.ready.wait(5)
    engine_mod = sys.modules["footage_sorter.engine"]
    assert all(not e.started for e in engine_mod.SorterEngine.instances)
    assert app.state.sorter_engine is None and app.state.sorter_holder.app is None


def test_held_requests_use_no_threads_and_get_a_sentence_after_the_wait(monkeypatch):
    import asyncio

    import anyio
    import httpx
    monkeypatch.setattr(sorter, "LOAD_WAIT_S", 1.0)
    holder = sorter._Holder()
    gate = sorter.SorterGate(holder, None)

    async def main():
        limiter = anyio.to_thread.current_default_thread_limiter()
        before = limiter.borrowed_tokens
        transport = httpx.ASGITransport(app=gate)
        async with httpx.AsyncClient(transport=transport, base_url="http://t") as c:
            held = [asyncio.create_task(c.get(f"/sorter/api/thumb/{i}")) for i in range(60)]
            await asyncio.sleep(0.3)
            assert limiter.borrowed_tokens == before        # 60 held, no thread taken
            rs = await asyncio.gather(*held)
        return rs
    rs = asyncio.run(main())
    assert {r.status_code for r in rs} == {503} and "still loading" in rs[0].json()["error"]


def test_a_held_request_is_released_the_moment_the_load_ends(monkeypatch):
    import asyncio
    import threading

    import httpx
    holder = sorter._Holder()
    gate = sorter.SorterGate(holder, None)

    async def app(scope, receive, send):
        await send({"type": "http.response.start", "status": 200, "headers": []})
        await send({"type": "http.response.body", "body": b"ok"})

    def finish():
        holder.app = app
        holder.finish()

    async def main():
        async with httpx.AsyncClient(transport=httpx.ASGITransport(app=gate), base_url="http://t") as c:
            t = asyncio.create_task(c.get("/sorter/x"))
            await asyncio.sleep(0.2)
            threading.Timer(0.1, finish).start()
            return await asyncio.wait_for(t, 5)
    assert asyncio.run(main()).status_code == 200


def test_the_dashboards_public_url_becomes_the_oauth_callback(tmp_path):
    pool, data, projects, staged, host = make_pool(tmp_path)
    settings = make_settings(tmp_path, sorter_enabled=True, sorter_src=SRC, sorter_data=str(data),
                             sorter_settings=json.dumps(host), site_dashboard_url="https://dash.example.com")
    app = create_app(settings)
    assert app.state.sorter_status == sorter.MOUNTED, app.state.sorter_detail
    assert app.state.sorter_holder.ready.wait(30) and app.state.sorter_holder.engine is not None
    from footage_sorter import integrations
    engine = app.state.sorter_holder.engine
    assert engine.host["publicUrl"] == "https://dash.example.com"
    assert integrations._redirect_uri(engine) == "https://dash.example.com/sorter/api/google/callback"
    sorter.stop_sorter(app)


def test_an_explicit_public_url_in_the_sorter_settings_wins(tmp_path):
    app = create_app(_stub_settings(tmp_path, "slow", sorter_settings=json.dumps({"publicUrl": "https://a.example"}),
                                    site_dashboard_url="https://b.example"))
    holder = app.state.sorter_holder
    assert holder.ready.wait(5)
    engine_mod = sys.modules["footage_sorter.engine"]
    assert engine_mod.SorterEngine.instances[-1].host["publicUrl"] == "https://a.example"
    sorter.stop_sorter(app)
