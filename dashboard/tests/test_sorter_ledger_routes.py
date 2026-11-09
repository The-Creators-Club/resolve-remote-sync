"""The ledger browser's fleet routes (sorter.py: /sorter/agent/volumes and /sorter/agent/ledger/*).

footage-sorter docs/LEDGER-BROWSER-DESIGN.md, part B. The sorter's own ledger (`engine.ledger`) is part A and
lives in the other repo, so these tests stand a recording stub in its place and pin the DOOR: the fleet
credential, the claimant check, CSRF exemption and the login carve-out, the body limits, and the gzip bound.
"""

from __future__ import annotations

import gzip
import json
import re
import zlib

import pytest
from fastapi.testclient import TestClient

from ccsync_dashboard import auth, db, sorter
from ccsync_dashboard.app import create_app
from ccsync_dashboard.settings import Settings

SECRET = "test-secret-not-a-real-one"
TOKEN = "report-token-not-a-real-one"


class LedgerGone(ValueError):
    """footage_sorter.ledger.LedgerGone: a ValueError subclass, told by name."""


class StubLedger:
    """Records what the routes pass in, and answers like the spec's interface."""

    def __init__(self):
        self.calls = []
        self.fail = None

    def _do(self, name, *args):
        self.calls.append((name, args))
        if self.fail:
            raise self.fail
        return {"ok": True, "call": name}

    def report_volumes(self, editor, machine, volumes, digest):
        self._do("report_volumes", editor, machine, volumes, digest)
        return {"scan": []}

    def scan_manifest(self, job_id):
        self._do("scan_manifest", job_id)
        return {"volumeId": "vol:1038701C", "roots": [""], "rules": {}}

    def scan_chunk(self, job_id, seq, rows):
        return self._do("scan_chunk", job_id, seq, rows)

    def scan_finish(self, job_id, body):
        return self._do("scan_finish", job_id, body)

    def scan_progress(self, job_id, body):
        return self._do("scan_progress", job_id, body)

    def record_copies(self, machine, copies, editor=""):
        self._do("record_copies", machine, copies, editor)
        return {"ok": True, "accepted": len(copies), "duplicates": 0, "skipped": 0}

    def mirror(self, volumes, since=0, limit=5000):
        self._do("mirror", volumes, since, limit)
        return {"cols": [], "rows": [], "cursor": "7:1", "more": False, "volumes": []}


class StubEngine:
    def __init__(self):
        self.ledger = StubLedger()

    def stop(self):
        pass


def fleet(editor="alex"):
    return {"X-CCSync-Token": TOKEN, "X-CCSync-Identity": auth.make_identity_token(SECRET, editor)}


@pytest.fixture
def rig(tmp_path):
    projects = tmp_path / "tree" / "Projects"
    projects.mkdir(parents=True)
    settings = Settings(db_path=str(tmp_path / "dash.db"), session_secret=SECRET, admin_users=frozenset({"owen"}),
                        projects_dir=str(projects), report_token=TOKEN)
    app = create_app(settings)
    app.state.sorter_engine = StubEngine()
    with TestClient(app) as client:
        yield client, app, app.state.sorter_engine.ledger


def make_job(app, kind="ledger-scan", claimed_by="alex", state="running"):
    conn = db.connect(app.state.settings.db_path)
    try:
        job_id = db.create_job(conn, kind, {"volumeId": "vol:1038701C"}, {}, created_by="sorter:owen",
                               priority=5, forced=True, target_machine="alex/creator-1")
        conn.execute("UPDATE jobs SET state=?, claimed_by=?, claimed_machine='creator-1' WHERE id=?",
                     (state, claimed_by, job_id))
        conn.commit()
    finally:
        conn.close()
    return job_id


def gz(obj) -> bytes:
    return gzip.compress(json.dumps(obj).encode())


# ------------------------------------------------------------------ the kind

def test_the_job_kind_has_a_label_a_budget_and_a_ceiling():
    assert "ledger-scan" in db.JOB_KINDS
    assert db.job_label("ledger-scan") == "DRIVE SCAN"
    assert db.job_retry_budget("ledger-scan") == 2
    assert db.JOB_MAX_RUNNING["ledger-scan"] == 4


# ------------------------------------------------------------------ the door

PATHS = [("POST", "/sorter/agent/volumes", {"machine": "m", "volumes": []}),
         ("POST", "/sorter/agent/ledger/copies", {"copies": []}),
         ("GET", "/sorter/agent/ledger/mirror", None)]


@pytest.mark.parametrize("method,path,body", PATHS)
def test_every_ledger_route_needs_the_fleet_credential_and_identity(rig, method, path, body):
    client, _app, ledger = rig
    call = lambda **kw: client.request(method, path, json=body, follow_redirects=False, **kw)    # noqa: E731
    assert call().status_code in (303, 401, 403)                                  # no credential
    assert call(headers={"X-CCSync-Token": TOKEN}).status_code == 403             # token, no identity
    assert call(headers={"X-CCSync-Token": "wrong", "X-CCSync-Identity":
                         auth.make_identity_token(SECRET, "alex")}).status_code in (303, 401, 403)
    assert ledger.calls == []
    assert call(headers=fleet()).status_code == 200


def test_the_routes_are_in_the_carve_outs():
    from ccsync_dashboard import app as app_mod
    for path in ("/sorter/agent/volumes", "/sorter/agent/ledger/copies", "/sorter/agent/ledger/mirror",
                 "/sorter/agent/ledger/scan/12", "/sorter/agent/ledger/scan/12/chunk",
                 "/sorter/agent/ledger/scan/12/finish", "/sorter/agent/ledger/scan/12/progress"):
        assert re.match(sorter.AGENT_PATH_RE, path), path
    for path in ("/sorter/agent/volumes", "/sorter/agent/ledger/copies", "/sorter/agent/ledger/scan/12/chunk",
                 "/sorter/agent/ledger/scan/12/finish", "/sorter/agent/ledger/scan/12/progress"):
        assert app_mod._CSRF_EXEMPT_RE.match(path), path
    # nothing wider: the page, the browser API and other agent paths stay gated
    for path in ("/sorter/", "/sorter/api/ledger/volumes", "/sorter/agent/ledger", "/sorter/agent/ledger/scan",
                 "/sorter/agent/ledger/scan/x/chunk", "/sorter/agent/ledger/mirror/x", "/sorter/agent/volumes/1"):
        assert not re.match(sorter.AGENT_PATH_RE, path), path
        assert not app_mod._CSRF_EXEMPT_RE.match(path), path
    assert "/sorter/agent/volumes" in app_mod._COMPANION_TOKEN_PATHS
    assert app_mod._BODY_LIMITS["/sorter/agent/ledger/copies"] == ("POST", sorter.MAX_LEDGER_COPIES_BYTES)
    assert app_mod._BODY_LIMIT_PATTERNS[0][0].match("/sorter/agent/ledger/scan/9/chunk")


def test_no_sorter_ledger_is_a_503_not_a_500(rig):
    client, app, _ledger = rig
    app.state.sorter_engine = None
    assert client.post("/sorter/agent/volumes", json={"machine": "m", "volumes": []}, headers=fleet()).status_code == 503
    app.state.sorter_engine = object()                 # an engine from before the ledger existed
    assert client.post("/sorter/agent/ledger/copies", json={"copies": []}, headers=fleet()).status_code == 503


# ------------------------------------------------------------------ volumes, copies, mirror

def test_a_volume_report_reaches_the_ledger_with_the_verified_editor(rig):
    client, _app, ledger = rig
    vols = [{"serial": "1038701C", "label": "CIB_D1", "root": "E:\\", "capacity": 10, "free": 5}]
    r = client.post("/sorter/agent/volumes", json={"machine": "creator-1", "volumes": vols, "digest": "abc",
                                                   "editor": "mallory"}, headers=fleet("alex"))
    assert r.status_code == 200 and r.json() == {"scan": []}
    assert ledger.calls == [("report_volumes", ("alex", "creator-1", vols, "abc"))]


def test_a_volume_report_is_validated(rig):
    client, _app, ledger = rig
    h = fleet()
    assert client.post("/sorter/agent/volumes", json={"volumes": []}, headers=h).status_code == 422
    assert client.post("/sorter/agent/volumes", json={"machine": "m", "volumes": "x"}, headers=h).status_code == 422
    too_many = [{"serial": str(i)} for i in range(sorter.MAX_VOLUMES_PER_REPORT + 1)]
    assert client.post("/sorter/agent/volumes", json={"machine": "m", "volumes": too_many}, headers=h).status_code == 413
    ledger.fail = ValueError("bad volume")
    assert client.post("/sorter/agent/volumes", json={"machine": "m", "volumes": []}, headers=h).status_code == 422


def test_copies_are_filed_by_the_verified_editor_and_bounded(rig):
    client, _app, ledger = rig
    copy = {"volume": {"serial": "1038701C", "label": "CIB_D1"}, "path": "a/b.braw", "name": "b.braw", "size": 5,
            "mtime": 1, "verified": "full", "tool": "teracopy", "at": "2026-11-09T00:00:00Z"}
    r = client.post("/sorter/agent/ledger/copies", json={"copies": [copy], "machine": "razer"}, headers=fleet("bob"))
    assert r.status_code == 200 and r.json()["accepted"] == 1 and r.json()["duplicates"] == 0
    assert ledger.calls == [("record_copies", ("razer", [copy], "bob"))]
    assert client.post("/sorter/agent/ledger/copies", json={"copies": "x"}, headers=fleet()).status_code == 422
    big = {"copies": [copy] * (sorter.MAX_LEDGER_COPIES_PER_POST + 1)}
    assert client.post("/sorter/agent/ledger/copies", json=big, headers=fleet()).status_code == 413


def test_the_body_gate_refuses_a_huge_copies_post_before_parsing(rig):
    client, _app, ledger = rig
    body = b'{"copies": [], "pad": "' + b"x" * (sorter.MAX_LEDGER_COPIES_BYTES + 10) + b'"}'
    r = client.post("/sorter/agent/ledger/copies", content=body, headers={**fleet(), "content-type": "application/json"})
    assert r.status_code == 413 and ledger.calls == []


def test_the_mirror_passes_the_volume_ids_and_the_cursor(rig):
    client, _app, ledger = rig
    r = client.get("/sorter/agent/ledger/mirror?volumes=vol:AAAA,nas:thecreatorspool,&since=41", headers=fleet())
    assert r.status_code == 200 and r.json()["cursor"] == "7:1"
    assert ledger.calls == [("mirror", (["vol:AAAA", "nas:thecreatorspool"], "41", 5000))]
    ledger.calls.clear()
    client.get("/sorter/agent/ledger/mirror?volumes=vol:AAAA&limit=99999", headers=fleet())
    assert ledger.calls == [("mirror", (["vol:AAAA"], 0, 20000))]            # no cursor yet: from the start


# ------------------------------------------------------------------ a scan job

def test_the_scan_calls_are_the_claimants_alone(rig):
    client, app, ledger = rig
    job = make_job(app)
    base = f"/sorter/agent/ledger/scan/{job}"
    # a manifest for the claimant
    r = client.get(base, headers=fleet("alex"))
    assert r.status_code == 200 and r.json()["volumeId"] == "vol:1038701C"
    # another editor's machine is turned away from every call
    assert client.get(base, headers=fleet("bob")).status_code == 409
    assert client.post(base + "/chunk", content=gz({"rows": [], "seq": 0}),
                       headers={**fleet("bob"), "content-encoding": "gzip"}).status_code == 409
    assert client.post(base + "/finish", json={"files": 0, "bytes": 0, "complete": True}, headers=fleet("bob")).status_code == 409
    assert client.post(base + "/progress", json={"filesDone": 1}, headers=fleet("bob")).status_code == 409
    assert [c[0] for c in ledger.calls] == ["scan_manifest"]


def test_a_scan_route_refuses_a_job_of_another_kind_or_none(rig):
    client, app, _ledger = rig
    copy_job = make_job(app, kind="card-ingest")
    assert client.get(f"/sorter/agent/ledger/scan/{copy_job}", headers=fleet()).status_code == 404
    assert client.get("/sorter/agent/ledger/scan/99999", headers=fleet()).status_code == 404
    # ...and the card routes still refuse a scan job
    scan_job = make_job(app)
    assert client.get(f"/sorter/agent/ingest/{scan_job}", headers=fleet()).status_code == 404


def test_a_gzip_chunk_is_inflated_and_handed_on_with_its_seq(rig):
    client, app, ledger = rig
    job = make_job(app)
    rows = [[f"Trip/clip{i}.braw", 1000 + i, 1786236852123 + i] for i in range(5000)]
    r = client.post(f"/sorter/agent/ledger/scan/{job}/chunk", content=gz({"rows": rows, "seq": 3}),
                    headers={**fleet(), "content-encoding": "gzip", "content-type": "application/json"})
    assert r.status_code == 200, r.text
    assert ledger.calls == [("scan_chunk", (job, 3, rows))]


def test_a_plain_json_chunk_is_accepted_too(rig):
    client, app, ledger = rig
    job = make_job(app)
    r = client.post(f"/sorter/agent/ledger/scan/{job}/chunk", json={"rows": [["a.mov", 1, 2]], "seq": 0}, headers=fleet())
    assert r.status_code == 200 and ledger.calls[0][1] == (job, 0, [["a.mov", 1, 2]])


def test_a_chunk_that_is_not_what_it_says_is_refused(rig):
    client, app, ledger = rig
    job = make_job(app)
    url = f"/sorter/agent/ledger/scan/{job}/chunk"
    h = {**fleet(), "content-encoding": "gzip", "content-type": "application/json"}
    assert client.post(url, content=b"not gzip at all", headers=h).status_code == 400
    assert client.post(url, content=gz({"rows": [], "seq": 0})[:-6], headers=h).status_code == 400     # truncated
    assert client.post(url, content=gzip.compress(b"[1,2]"), headers=h).status_code == 422
    assert client.post(url, content=gzip.compress(b"{nope"), headers=h).status_code == 400
    assert client.post(url, content=gz({"rows": "x", "seq": 0}), headers=h).status_code == 422
    assert client.post(url, content=gz({"rows": [], "seq": -1}), headers=h).status_code == 422
    assert client.post(url, content=gz({"rows": [], "seq": True}), headers=h).status_code == 422
    assert client.post(url, content=gz({"rows": [], "seq": 0}), headers={**h, "content-encoding": "br"}).status_code == 415
    assert client.post(url, content=gz({"rows": [[]] * (sorter.MAX_LEDGER_CHUNK_ROWS + 1), "seq": 0}),
                       headers=h).status_code == 413
    assert ledger.calls == []


def test_a_gzip_bomb_is_stopped_at_the_decompressed_cap(rig):
    client, app, ledger = rig
    job = make_job(app)
    # 40 MB of zeros is about 40 KB on the wire
    bomb = gzip.compress(b'{"rows": [], "pad": "' + b"0" * (40 * 1024 * 1024) + b'", "seq": 0}')
    assert len(bomb) < sorter.MAX_LEDGER_CHUNK_BYTES
    r = client.post(f"/sorter/agent/ledger/scan/{job}/chunk", content=bomb,
                    headers={**fleet(), "content-encoding": "gzip", "content-type": "application/json"})
    assert r.status_code == 413 and ledger.calls == []


def test_the_wire_size_of_a_chunk_is_bounded_before_the_route(rig):
    client, app, ledger = rig
    job = make_job(app)
    # incompressible bytes, over the compressed cap
    import os
    blob = os.urandom(sorter.MAX_LEDGER_CHUNK_BYTES + 1024)
    r = client.post(f"/sorter/agent/ledger/scan/{job}/chunk", content=blob,
                    headers={**fleet(), "content-encoding": "gzip"})
    assert r.status_code == 413 and ledger.calls == []


def test_a_chunk_without_credentials_is_turned_away_before_its_body_is_read(rig):
    client, app, ledger = rig
    job = make_job(app)
    r = client.post(f"/sorter/agent/ledger/scan/{job}/chunk", content=gz({"rows": [], "seq": 0}),
                    headers={"content-encoding": "gzip"}, follow_redirects=False)
    assert r.status_code in (303, 401, 403) and ledger.calls == []


def test_finish_and_progress_reach_the_ledger(rig):
    client, app, ledger = rig
    job = make_job(app)
    fin = {"files": 12, "bytes": 99, "complete": False}
    assert client.post(f"/sorter/agent/ledger/scan/{job}/finish", json=fin, headers=fleet()).status_code == 200
    prog = {"filesDone": 5, "bytesSeen": 6, "bps": 7.0, "current": "Trip"}
    assert client.post(f"/sorter/agent/ledger/scan/{job}/progress", json=prog, headers=fleet()).status_code == 200
    assert ledger.calls == [("scan_finish", (job, fin)), ("scan_progress", (job, prog))]


def test_the_ledgers_errors_are_the_callers(rig):
    client, app, ledger = rig
    job = make_job(app)
    ledger.fail = LookupError("no such scan")
    assert client.post(f"/sorter/agent/ledger/scan/{job}/finish", json={}, headers=fleet()).status_code == 404
    ledger.fail = ValueError("rows out of order")
    assert client.post(f"/sorter/agent/ledger/scan/{job}/progress", json={}, headers=fleet()).status_code == 422
    ledger.fail = LedgerGone("that scan is already finished")           # stop: the companion reads 409 as "not yours"
    assert client.post(f"/sorter/agent/ledger/scan/{job}/finish", json={}, headers=fleet()).status_code == 409
    assert client.post(f"/sorter/agent/ledger/scan/{job}/chunk", json={"rows": [], "seq": 0}, headers=fleet()).status_code == 409


def test_decode_chunk_body_directly():
    assert sorter.decode_chunk_body(gz({"rows": [], "seq": 1}), "gzip") == {"rows": [], "seq": 1}
    assert sorter.decode_chunk_body(b'{"seq": 2}', "") == {"seq": 2}
    raw = zlib.compress(b"{}")                      # zlib, not gzip
    with pytest.raises(sorter.HTTPException) as e:
        sorter.decode_chunk_body(raw, "gzip")
    assert e.value.status_code == 400


# ------------------------------------------------------------------ against the real ledger (footage-sorter part A)

import os                                                          # noqa: E402
import sys                                                         # noqa: E402
from pathlib import Path                                           # noqa: E402

SRC = os.environ.get("FOOTAGE_SORTER_SRC") or str(Path(__file__).resolve().parents[3] / "footage-sorter")
real = pytest.mark.skipif(not (Path(SRC) / "footage_sorter" / "ledger.py").is_file(),
                          reason=f"no footage-sorter checkout with a ledger at {SRC}")


@pytest.fixture
def real_rig(tmp_path, monkeypatch):
    monkeypatch.delenv("SORTER_SRC", raising=False)
    pool = tmp_path / "pool"
    (pool / "Temp Transfer").mkdir(parents=True)
    projects = pool / "Creators_Club" / "Projects"
    projects.mkdir(parents=True)
    data = tmp_path / "sorter-data"
    data.mkdir()
    (data / "clips.json").write_text(json.dumps({"scannedAt": "2026-11-09T00:00:00Z", "clips": []}), encoding="utf-8")
    host = {"sourceRoots": [str(pool / "Temp Transfer")], "destRoot": str(projects), "ffmpegDir": ""}
    tree = tmp_path / "tree" / "Projects"
    tree.mkdir(parents=True)
    settings = Settings(db_path=str(tmp_path / "dash.db"), session_secret=SECRET, admin_users=frozenset({"owen"}),
                        projects_dir=str(tree), report_token=TOKEN, sorter_enabled=True, sorter_src=SRC,
                        sorter_data=str(data), sorter_settings=json.dumps(host))
    app = create_app(settings)
    assert app.state.sorter_status == sorter.MOUNTED, app.state.sorter_detail
    try:
        with TestClient(app) as client:
            client.cookies.set(auth.COOKIE_NAME, auth.make_session_cookie(SECRET, "owen"))
            client.get("/sorter/api/state")                        # held until the engine (and its ledger) has loaded
            assert getattr(app.state.sorter_engine, "ledger", None) is not None
            client.cookies.clear()
            yield client, app
    finally:
        for name in [n for n in sys.modules if n.split(".")[0] == "footage_sorter"]:
            del sys.modules[name]
        while SRC in sys.path:
            sys.path.remove(SRC)


@real
def test_the_whole_scan_protocol_against_the_real_ledger(real_rig):
    client, app = real_rig
    h = fleet("alex")
    # 1. the companion reports a drive; the ledger knows nothing of it yet, so nothing is queued
    vol = {"serial": "6880882B", "label": "CIB_D1", "fs": "exFAT", "size": 14 * 10 ** 12, "free": 3 * 10 ** 12,
           "drive": "M:", "driveType": "fixed", "system": False, "removable": False}
    r = client.post("/sorter/agent/volumes", json={"machine": "creator-1", "volumes": [vol], "digest": "d"}, headers=h)
    assert r.status_code == 200, r.text
    assert r.json()["scan"] == [] and r.json().get("new") == 1
    # 2. a volume with no serial and too many volumes are the sorter's 422
    assert client.post("/sorter/agent/volumes", json={"machine": "m", "volumes": [{"label": "x"}]}, headers=h).status_code == 200
    # 3. a scan is queued for a tracked drive: the ledger tracks it, the next report queues the job
    ledger = app.state.sorter_engine.ledger
    queued = ledger.set_volume("vol:6880882B", {"tracked": True, "kind": "ours", "roots": [""]}, "owen")
    r = client.post("/sorter/agent/volumes", json={"machine": "creator-1", "volumes": [vol], "digest": "e"}, headers=h)
    # tracking a plugged-in volume queues its first scan at once (the answer says so); the report then finds it queued
    first = queued.get("scan") if isinstance(queued, dict) else None
    scans = r.json()["scan"] or ([first] if isinstance(first, dict) else first or [])
    assert scans and "jobId" in scans[0], (queued, r.json())
    job_id = scans[0]["jobId"]
    conn = db.connect(app.state.settings.db_path)
    try:
        job = db.get_job(conn, job_id)
        assert job["kind"] == "ledger-scan" and job["target_machine"] == "alex/creator-1" and job["forced"]
        conn.execute("UPDATE jobs SET state='running', claimed_by='alex', claimed_machine='creator-1' WHERE id=?", (job_id,))
        conn.commit()
    finally:
        conn.close()
    base = f"/sorter/agent/ledger/scan/{job_id}"
    man = client.get(base, headers=h)
    assert man.status_code == 200, man.text
    assert man.json()["serial"] == "6880882B" and man.json()["rules"]["masterExts"]
    rows = [["Trip/A001.braw", 100, 1_786_236_852_123], ["Trip/notes.txt", 5, 1_786_236_852_123]]
    gzh = {**h, "content-encoding": "gzip", "content-type": "application/json"}
    first = client.post(base + "/chunk", content=gz({"rows": rows, "seq": 0}), headers=gzh)
    assert first.status_code == 200 and first.json()["taken"] == 1 and first.json()["duplicate"] is False
    again = client.post(base + "/chunk", content=gz({"rows": rows, "seq": 0}), headers=gzh)
    assert again.json()["duplicate"] is True                       # a retried seq takes nothing
    assert client.post(base + "/progress", json={"filesDone": 1, "bytesSeen": 100, "bps": 1.0, "current": "Trip"}, headers=h).status_code == 200
    fin = client.post(base + "/finish", json={"files": 1, "bytes": 100, "complete": True}, headers=h)
    assert fin.status_code == 200 and fin.json()["status"] == "ok" and fin.json()["added"] == 1
    # a finished scan is gone: 409, which the companion reads as "stop"
    assert client.post(base + "/chunk", content=gz({"rows": rows, "seq": 1}), headers=gzh).status_code == 409
    # 4. a copy filed from an outbox, twice
    copy = {"volume": {"serial": "AAAA0001", "label": "FIELD"}, "path": "Trip/A001.braw", "name": "A001.braw",
            "size": 100, "mtime": 1_786_236_852_123, "verified": "full", "tool": "teracopy", "at": "2026-11-09T10:00:00Z"}
    one = client.post("/sorter/agent/ledger/copies", json={"copies": [copy], "machine": "razer"}, headers=h).json()
    two = client.post("/sorter/agent/ledger/copies", json={"copies": [copy], "machine": "razer"}, headers=h).json()
    assert one["accepted"] == 1 and two["accepted"] == 0 and two["duplicates"] == 1
    # 5. the mirror
    m = client.get("/sorter/agent/ledger/mirror?volumes=vol:6880882B,vol:AAAA0001&since=", headers=h)
    assert m.status_code == 200, m.text
    body = m.json()
    assert body["cols"][0] == "id" and len(body["rows"]) == 2 and body["more"] is False


@real
def test_the_mirror_cursor_advances_against_the_real_ledger(real_rig):
    client, _app = real_rig
    h = fleet("alex")
    copy = {"volume": {"serial": "AAAA0001", "label": "FIELD"}, "path": "Trip/A001.braw", "size": 100,
            "mtime": 1_786_236_852_123, "verified": "full", "tool": "teracopy"}
    assert client.post("/sorter/agent/ledger/copies", json={"copies": [copy], "machine": "razer"}, headers=h).json()["accepted"] == 1
    body = client.get("/sorter/agent/ledger/mirror?volumes=vol:AAAA0001&since=", headers=h).json()
    assert len(body["rows"]) == 1
    back = client.get("/sorter/agent/ledger/mirror?volumes=vol:AAAA0001&since=" + body["cursor"], headers=h).json()
    assert back["rows"] == []
