"""Bug hunt 2026-09-11, broll territory (CR-245).

Six findings, three seams:

  * **the ledger's own migration could only be run once** (broll-2). The
    v1 -> v2 step ALTERs, backfills, then writes `user_version`, and CPython's
    sqlite3 commits DDL the instant it runs: a container killed mid-backfill
    left a file with the column and version 1, and every later entry into
    `ensure_schema` raised `duplicate column name: hash` at a 500 on every
    client-folder route AND every public `/broll/share/<token>/...` link.
  * **the backfill was a scan of the archive** (broll-6), one unindexed
    UPDATE per hashed `videos` row, inside a request, holding the ledger's
    write lock - which is also what made broll-2's window wide.
  * **"try the N failed again" sent the server's item uids to a companion
    that only knows the browser's local ids** (broll-1): 200/retried:0, so
    the page's 404 fallback never fired and the batch sat in `queued`.

Plus the small ones: the discovery route nothing ever called (broll-3) with
its docstring's wrong fact about the gate (broll-4), and a retry-failed that
took a live lease away underneath the machine holding it (broll-5).
"""
from __future__ import annotations

import sqlite3
from pathlib import Path

import pytest

from app import client_folders as cf
from app import ingest_batches, routes_fleet
from tests.conftest import fleet_headers
from tests.factories import insert_video

INGEST_JS = (Path(__file__).resolve().parents[1] / "static" / "ingest.js").read_text(
    encoding="utf-8")
FLEET_PY = (Path(__file__).resolve().parents[1] / "app" / "routes_fleet.py").read_text(
    encoding="utf-8")

BASE = "/api/fleet/ingest/batches"


# --- broll-2: a migration that can be run twice, and finished after a crash ------

def _v1_ledger(data_root: Path, *, alter_applied: bool) -> Path:
    """A client_shares.db as 2026-09-02 left it, optionally with the v2 ALTER
    already durable but `user_version` still 1 - which is exactly what a
    container killed inside the backfill leaves behind."""
    cf.ensure_schema()
    path = cf.get_db_path()
    conn = sqlite3.connect(path)
    conn.execute("ALTER TABLE client_folder_items DROP COLUMN hash")
    if alter_applied:
        conn.execute(
            "ALTER TABLE client_folder_items ADD COLUMN hash TEXT NOT NULL DEFAULT ''")
    conn.execute("PRAGMA user_version = 1")
    conn.commit()
    conn.close()
    return path


def _one_item(data_root, conn, *, rel_path="Inbox/A001.mp4", video_hash="a1b2c3"):
    """An indexed clip and a curated item pointing at it, written straight into
    both files so no route (and no migration) is involved in the setup."""
    vid = insert_video(conn, share="broll", rel_path=rel_path, hash=video_hash,
                       duration_s=12.0)
    ledger = cf.open_connection()
    ledger.execute(
        "INSERT INTO client_folders (token, title, description, contact, "
        "created_by, created_at, updated_at) VALUES ('t0', 'Acme', '', '', "
        "'jsmith', '2026-09-01T00:00:00+00:00', '2026-09-01T00:00:00+00:00')")
    ledger.execute(
        "INSERT INTO client_folder_items (folder_id, video_id, share, rel_path, "
        "ord, added_by, added_at) VALUES (1, ?, 'broll', ?, 1, 'jsmith', "
        "'2026-09-01T00:00:00+00:00')", (vid, rel_path))
    ledger.commit()
    ledger.close()
    return vid


def test_a_ledger_half_migrated_by_a_crash_is_completed_by_the_next_run(
        data_root, conn):
    """broll-2: the ALTER is durable the moment it runs, so a process death
    inside the backfill leaves the column present at user_version 1. That file
    must migrate, not raise for ever."""
    _v1_ledger(data_root, alter_applied=False)
    _one_item(data_root, conn)
    # Re-apply the ALTER by hand: the crash happened after it and before the
    # PRAGMA, with nothing backfilled.
    half = sqlite3.connect(cf.get_db_path())
    half.execute(
        "ALTER TABLE client_folder_items ADD COLUMN hash TEXT NOT NULL DEFAULT ''")
    half.execute("PRAGMA user_version = 1")
    half.commit()
    half.close()

    cf.ensure_schema()

    done = cf.open_connection()
    assert done.execute("PRAGMA user_version").fetchone()[0] == cf.SCHEMA_VERSION
    assert done.execute("SELECT hash FROM client_folder_items").fetchone()["hash"] \
        == "a1b2c3", "the interrupted backfill was never completed"
    done.close()


def test_ensure_schema_can_be_run_twice_over_the_same_v1_file(data_root, conn):
    """The second run is the one that used to raise: it must be a no-op, and
    the backfill it repeats must be idempotent."""
    _v1_ledger(data_root, alter_applied=True)
    _one_item(data_root, conn)

    cf.ensure_schema()
    cf.ensure_schema()
    cf.ensure_schema()

    done = cf.open_connection()
    rows = done.execute("SELECT hash FROM client_folder_items").fetchall()
    assert [r["hash"] for r in rows] == ["a1b2c3"]
    assert done.execute("PRAGMA user_version").fetchone()[0] == cf.SCHEMA_VERSION
    done.close()


def test_a_ledger_that_will_not_migrate_does_not_take_the_share_door_out(
        data_root, monkeypatch):
    """One bad ledger must not 500 every public `/broll/share/<token>/` link.
    The deliberately fatal refusal - a file from a NEWER deployment - still
    comes through."""
    cf.ensure_schema()

    def boom(db_path=None):
        raise sqlite3.OperationalError("disk I/O error")

    monkeypatch.setattr(cf, "ensure_schema", boom)
    gen = cf.get_shares_db()
    conn = next(gen)
    try:
        assert conn.execute("PRAGMA user_version").fetchone()[0] >= 1
    finally:
        gen.close()

    def too_new(db_path=None):
        raise RuntimeError("FATAL: user_version=99, newer than this app supports")

    monkeypatch.setattr(cf, "ensure_schema", too_new)
    with pytest.raises(RuntimeError):
        next(cf.get_shares_db())


# --- broll-6: the backfill is sized by the folders, not by the archive ----------

def test_the_backfill_does_not_touch_the_ledger_once_per_archive_row(
        data_root, conn):
    """broll-6: it used to issue one unindexed UPDATE per hashed `videos` row
    (tens of thousands on a real archive) while holding the ledger's write
    lock. It must be sized by the few hundred curated items instead."""
    _v1_ledger(data_root, alter_applied=True)
    _one_item(data_root, conn)
    for i in range(60):
        insert_video(conn, share="broll", rel_path=f"Nature/B{i:03d}.mp4",
                     hash=f"deadbeef{i:03d}", duration_s=3.0)
    conn.commit()

    ledger = cf.open_connection()
    statements: list[str] = []
    ledger.set_trace_callback(statements.append)
    cf._backfill_hashes(ledger)
    ledger.commit()
    ledger.set_trace_callback(None)

    writes = [s for s in statements if s.lstrip().upper().startswith("UPDATE")]
    assert len(writes) <= 2, (
        f"{len(writes)} writes for 1 curated item and 61 archive rows: the "
        "backfill is still iterating the index")
    assert ledger.execute(
        "SELECT hash FROM client_folder_items").fetchone()["hash"] == "a1b2c3"
    ledger.close()


# --- broll-1: the retry button reaches a path the companion understands ---------

def _retry_fn() -> str:
    body = INGEST_JS[INGEST_JS.index("async function ingestRetryFailedBatch"):]
    return body[:body.index("\n}\n")]


def test_the_retry_button_dispatches_the_take_over_call_not_item_uids():
    """broll-1: `retry-failed` answers with `ingest_items.uid`s, and the
    companion's `/broll/ingest/retry` matches its `items` against the
    BROWSER's local ids - two namespaces that cannot intersect, so it answered
    200/retried:0 and the page's 404 fallback never fired."""
    again = _retry_fn()
    assert '"/broll/ingest/retry"' not in again, (
        "the companion's retry route rewrites the staging ledger and knows "
        "only local ids: the uids this page holds mean nothing to it")
    assert "items: answer.items" not in again
    assert '"/broll/ingest/run"' in again and "batch_uid: uid" in again, (
        "the claim is what starts the work again, on every build in the fleet")
    assert "staging_id: null" in again


def test_retry_failed_does_not_claim_its_uids_are_the_companions_body(client, conn):
    source = (Path(__file__).resolve().parents[1] / "app"
              / "ingest_batches.py").read_text(encoding="utf-8")
    assert "companion's `/broll/ingest/retry` takes" not in source


# --- broll-3 / broll-4: the discovery route and its docstring's wrong fact ------

def test_the_fleet_router_carries_no_route_without_a_caller():
    """broll-3: `GET /api/fleet/ingest/batches` shipped with no client - no
    `FleetClient` call anywhere - and a login-gate carve-out that existed for
    nobody. A companion that discovered and claimed its own work would also
    change who decides what a machine works on (plan: possession is won by a
    claim the PAGE dispatches), so the route goes rather than grows a caller."""
    for route in routes_fleet.router.routes:
        assert "GET" not in getattr(route, "methods", set()), (
            f"{route.path} has no caller in companion/: "
            "every fleet route is a POST a companion actually issues")


def test_the_fleet_docstrings_do_not_claim_the_gate_needs_widening():
    """broll-4: the NOTE said the dashboard's login_gate carve-out still had
    to be widened for a companion to reach the route, and a wrong fact about a
    security gate is what gets a correct gate "fixed".

    Corrected 2026-09-11b: the original wording of this docstring claimed the
    gate "was widened in the same commit", which was a second wrong fact about
    the same gate - the route the carve-out was for was DELETED that commit
    (broll-3) and `_broll_fleet_list_re` was left behind. What this file must
    say is the rule, which is what the assertions below now check.

    Hand-off wave, same day: the third wrong fact was the CORRECTION's own
    tense. The note said the gate "still admits" the unauthenticated GET
    "onto a 404 today", written while dash-core was deleting the regex in the
    same pass (security-2, CR-257h). A file that describes a gate as open
    when it is shut is how the next reader re-opens it "to match the
    comment", which is the exact failure mode broll-4 is about. The note is
    history now and says which change closed it.
    """
    assert "needs that regex widened" not in FLEET_PY
    assert "before a companion behind the dashboard can reach it" not in FLEET_PY
    assert "_broll_fleet_list_re" in FLEET_PY and "broll-4" in FLEET_PY, (
        "the file that owns the path shape records why the gate's carve-out "
        "for it is gone, so the next GET at that path does not inherit it")
    assert "onto a 404 today" not in FLEET_PY, (
        "the carve-out is deleted (security-2): nothing here may describe it "
        "as a gate that is still open")
    assert "security-2" in FLEET_PY, (
        "name the change that deleted the dashboard half, so the next reader "
        "can check the gate instead of trusting this paragraph's tense")


# --- broll-5: a retry does not take a live lease away --------------------------

def _queue(client, editor="jsmith", n=2):
    client.headers.update({"X-CCSync-User": editor})
    items = [{"local_id": f"l{i}", "name": f"A00{i}.MP4", "size": 10 + i,
              "hash": None, "source": "upload", "rel_dir": ""} for i in range(n)]
    r = client.post("/api/ingest-batches",
                    json={"share": "E2E", "settings": {"tier": "good"},
                          "items": items})
    assert r.status_code == 200, r.text
    return r.json()["uid"]


def test_a_retry_is_refused_while_a_machine_still_holds_the_batch(client, conn):
    """broll-5: the route used to null `lease_expires_at` and set `queued`
    underneath the machine that was still working, so a second machine could
    win a claim beside it and both would index the same clips."""
    uid = _queue(client)
    assert client.post(f"{BASE}/{uid}/claim", headers=fleet_headers(),
                       json={"machine": "EDIT-01", "companion_version": "0.9.67",
                             "tier": "good", "capabilities": {}}).status_code == 200
    item = ingest_batches.list_items(conn, uid)[0]
    assert client.post(f"{BASE}/{uid}/items/{item['uid']}/status",
                       headers=fleet_headers(),
                       json={"state": "failed", "error": "ffmpeg exited 1"}
                       ).status_code == 200

    r = client.post(f"/api/ingest-batches/{uid}/retry-failed")
    assert r.status_code == 409, r.text
    assert "EDIT-01" in r.text
    batch = ingest_batches.get_batch(conn, uid)
    assert batch["lease_expires_at"], "the leaseholder's possession was taken away"
    assert ingest_batches.get_item(conn, uid, item["uid"])["state"] == "failed"


def test_a_retry_is_allowed_once_the_lease_is_gone(client, conn):
    """The batch a machine abandoned is exactly the case the button is for."""
    uid = _queue(client)
    client.post(f"{BASE}/{uid}/claim", headers=fleet_headers(),
                json={"machine": "EDIT-01", "companion_version": "0.9.67",
                      "tier": "good", "capabilities": {}})
    item = ingest_batches.list_items(conn, uid)[0]
    client.post(f"{BASE}/{uid}/items/{item['uid']}/status", headers=fleet_headers(),
                json={"state": "failed", "error": "ffmpeg exited 1"})
    conn.execute("UPDATE ingest_batches SET lease_expires_at = NULL WHERE uid = ?",
                 (uid,))
    conn.commit()

    r = client.post(f"/api/ingest-batches/{uid}/retry-failed")
    assert r.status_code == 200, r.text
    assert r.json()["retried"] == 1
