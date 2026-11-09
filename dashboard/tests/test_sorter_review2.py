"""Regression tests for the second adversarial review of the ledger browser's dashboard half (2026-11-09)."""
from __future__ import annotations

import gzip
import time
import tracemalloc

import pytest

from ccsync_dashboard import auth, db as dbmod, jobs as jobs_mod, sorter

from test_jobs import GOOD_CAPS, conn, seen_machine  # noqa: F401  (conn is a fixture)
from test_sorter_ledger_routes import SECRET, StubLedger, fleet, make_job, rig  # noqa: F401  (rig is a fixture)


# ------------------------------------------------- 1. a running scan must not block a forced card copy

def _jobs(conn, scan_state="claimed"):
    seen_machine(conn)
    caps = dict(GOOD_CAPS, sorter_cards=True, sorter_ledger=True)
    scan = dbmod.create_job(conn, "ledger-scan", {"volumeId": "vol:1"}, {}, forced=True,
                            target_machine="jsmith/EDIT-PC", created_by="ledger")
    card = dbmod.create_job(conn, "card-ingest", {"card": "x"}, {}, forced=True,
                            target_machine="jsmith/EDIT-PC", created_by="sorter:jsmith")
    dbmod.claim_job(conn, scan, "jsmith", "EDIT-PC")
    return caps, scan, card


def test_a_running_scan_does_not_block_a_forced_card_copy(conn):
    caps, scan, card = _jobs(conn)
    offers = jobs_mod.offers_for_machine(conn, "jsmith", "EDIT-PC", caps)
    assert card in offers["offered"] or card in offers.get("forced", []), offers["refused"].get(card)


def test_a_second_scan_on_the_same_machine_is_refused_but_other_kinds_still_count(conn):
    caps, scan, card = _jobs(conn)
    second = dbmod.create_job(conn, "ledger-scan", {"volumeId": "vol:2"}, {}, forced=True,
                              target_machine="jsmith/EDIT-PC", created_by="ledger")
    offers = jobs_mod.offers_for_machine(conn, "jsmith", "EDIT-PC", caps)
    assert second not in offers["offered"] and "holding" in str(offers["refused"].get(second)).lower() or \
        second not in offers["offered"]
    assert second not in offers["offered"]
    # while a card copy IS held, a scan is not what makes it busy and a second card copy still is refused
    dbmod.claim_job(conn, card, "jsmith", "EDIT-PC")
    other_card = dbmod.create_job(conn, "card-ingest", {"card": "y"}, {}, forced=True,
                                  target_machine="jsmith/EDIT-PC", created_by="sorter:jsmith")
    offers = jobs_mod.offers_for_machine(conn, "jsmith", "EDIT-PC", caps)
    assert other_card not in offers["offered"]


def test_the_refusal_reason_for_a_second_scan_is_the_busy_one():
    facts = {"live_jobs": [{"id": 5, "kind": "ledger-scan"}], "capabilities": dict(GOOD_CAPS, sorter_ledger=True),
             "reported_at": dbmod.utcnow_iso()}
    code, why = jobs_mod.policy_refusal(facts, "ledger-scan")
    assert code == jobs_mod.REFUSE_BUSY_WITH_JOB and "#5" in why
    assert jobs_mod.policy_refusal(facts, "card-ingest")[0] != jobs_mod.REFUSE_BUSY_WITH_JOB
    held_card = dict(facts, live_jobs=[{"id": 6, "kind": "card-ingest"}])
    assert jobs_mod.policy_refusal(held_card, "card-ingest")[0] == jobs_mod.REFUSE_BUSY_WITH_JOB
    assert jobs_mod.policy_refusal(held_card, "ledger-scan")[0] != jobs_mod.REFUSE_BUSY_WITH_JOB


# ------------------------------------------------- 4. what the dashboard answers a stale credential

def test_a_stale_token_is_not_a_malformed_body(rig):
    """The companion's outbox sets copies aside only for 400/413/422; a stale token must never look like one."""
    client, app, ledger = rig
    bad = {"X-CCSync-Token": "rotated-old-token", "X-CCSync-Identity": auth.make_identity_token(SECRET, "alex")}
    job = make_job(app)
    cases = [("POST", "/sorter/agent/ledger/copies", {"json": {"copies": [], "machine": "pc"}}),
             ("POST", "/sorter/agent/volumes", {"json": {"machine": "pc", "volumes": []}}),
             ("POST", f"/sorter/agent/ledger/scan/{job}/finish", {"json": {}}),
             ("GET", f"/sorter/agent/ledger/scan/{job}", {}),
             ("GET", "/sorter/agent/ledger/mirror?volumes=vol:1", {})]
    for method, path, kw in cases:
        r = client.request(method, path, headers=bad, follow_redirects=False, **kw)
        assert r.status_code not in (400, 413, 422), (path, r.status_code)
    assert ledger.calls == []


# ------------------------------------------------- 5. the attempt token reaches the ledger

def test_the_chunks_attempt_is_handed_to_a_ledger_that_takes_one(rig):
    client, app, ledger = rig
    seen = []

    def scan_chunk(job_id, seq, rows, attempt=None):
        seen.append(attempt)
        return {"ok": True}

    ledger.scan_chunk = scan_chunk
    job = make_job(app)
    url = f"/sorter/agent/ledger/scan/{job}/chunk"
    h = {**fleet(), "Content-Encoding": "gzip", "Content-Type": "application/json"}
    body = gzip.compress(b'{"rows": [], "seq": 0, "attempt": "tok-7"}')
    assert client.post(url, content=body, headers=h).status_code == 200
    assert client.post(url, content=gzip.compress(b'{"rows": [], "seq": 1}'), headers=h).status_code == 200
    assert seen == ["tok-7", None]


def test_a_ledger_that_takes_no_attempt_is_not_handed_one(rig):
    client, app, ledger = rig                                   # StubLedger.scan_chunk(job_id, seq, rows)
    job = make_job(app)
    r = client.post(f"/sorter/agent/ledger/scan/{job}/chunk", headers={**fleet(), "Content-Encoding": "gzip"},
                    content=gzip.compress(b'{"rows": [], "seq": 0, "attempt": "tok"}'))
    assert r.status_code == 200 and ledger.calls[-1] == ("scan_chunk", (job, 0, []))


def test_finish_and_progress_pass_the_attempt_in_their_bodies(rig):
    client, app, ledger = rig
    job = make_job(app)
    client.post(f"/sorter/agent/ledger/scan/{job}/finish", json={"complete": True, "attempt": "t"}, headers=fleet())
    client.post(f"/sorter/agent/ledger/scan/{job}/progress", json={"filesDone": 1, "attempt": "t"}, headers=fleet())
    assert [c[1][1]["attempt"] for c in ledger.calls] == ["t", "t"]


# ------------------------------------------------- 10. the chunk route's memory

def test_a_deeply_nested_chunk_is_a_400_not_a_500(rig):
    client, app, ledger = rig
    job = make_job(app)
    body = gzip.compress(b'{"rows":' + b"[" * 200000 + b"]" * 200000 + b',"seq":0}')
    assert len(body) < sorter.MAX_LEDGER_CHUNK_BYTES
    r = client.post(f"/sorter/agent/ledger/scan/{job}/chunk", content=body,
                    headers={**fleet(), "Content-Encoding": "gzip", "Content-Type": "application/json"})
    assert r.status_code == 400 and ledger.calls == []


def test_the_decompressed_cap_is_small_and_a_dense_chunk_stays_cheap():
    assert sorter.MAX_LEDGER_CHUNK_DECOMPRESSED <= 4 * 1024 * 1024
    n = (sorter.MAX_LEDGER_CHUNK_DECOMPRESSED - 40) // 3
    raw = b'{"rows":[' + b"{}," * (n - 1) + b'{}],"seq":0}'
    tracemalloc.start()
    t = time.time()
    body = sorter.decode_chunk_body(gzip.compress(raw), "gzip")
    _cur, peak = tracemalloc.get_traced_memory()
    tracemalloc.stop()
    assert len(body["rows"]) == n and peak < 100 * 2 ** 20 and time.time() - t < 10
    with pytest.raises(sorter.HTTPException) as e:
        sorter.decode_chunk_body(gzip.compress(raw + b" " * 4096), "gzip")
    assert e.value.status_code == 413


def test_a_real_sized_chunk_still_fits():
    rows = [[f"FieldBackup/Trip/Day {i % 40}/Camera A/C{i:06}_a-rather-long-clip-name.braw", 4_123_456_789, 1786236852123]
            for i in range(10000)]
    import json
    raw = json.dumps({"rows": rows, "seq": 0}).encode()
    assert len(raw) < sorter.MAX_LEDGER_CHUNK_DECOMPRESSED
    assert len(sorter.decode_chunk_body(gzip.compress(raw), "gzip")["rows"]) == 10000


# ------------------------------------------------- a fleet caller names a volume by serial only

def test_a_copy_cannot_name_a_volume_by_id_or_kind(rig):
    client, app, ledger = rig
    copy = {"volume": {"serial": "AAAA0001", "label": "FIELD", "id": "nas:thecreatorspool", "kind": "nas"},
            "path": "Trip/A001.braw", "name": "A001.braw", "size": 100, "mtime": 1}
    other = {"volume": {"id": "cloud:hetzner"}, "path": "x.mov", "size": 1}
    r = client.post("/sorter/agent/ledger/copies", json={"copies": [copy, other, "junk"], "machine": "pc"}, headers=fleet())
    assert r.status_code == 200
    _name, (machine, sent, editor) = ledger.calls[-1]
    assert sent[0]["volume"] == {"serial": "AAAA0001", "label": "FIELD"}
    assert sent[1]["volume"] == {} and sent[2] == "junk" and (machine, editor) == ("pc", "alex")
