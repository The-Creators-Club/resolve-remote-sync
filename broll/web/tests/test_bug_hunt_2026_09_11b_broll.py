"""Bug hunt 2026-09-11b, broll territory (CR-261).

A hunt OF the fix pass earlier the same day, so every test here is about the
half a fix landed:

  * **[ try the failed ones again ] claimed the batch with NO staging id**
    (comp-broll-music-1), so the companion built every item with no source and
    failed all of them twice. The drop was unrecoverable with the bytes still
    sitting in staging.
  * **the 409 branch beside it printed the one sentence that is almost always
    false** (broll-1), then set the panel running on a dispatch that failed.
  * **the held-batch refusal reached the editor as "[object Object]"**
    (broll-2): an `HTTPException(409, {...})` detail is an object and
    `Error.message` of an object is that string.
  * **the ledger's CREATE half was still the crash-unsafe shape broll-2 fixed
    the ALTER half of** (broll-3), and a failed backfill still retired the
    migration step (broll-6).
  * **the boot paths called `ensure_schema` bare** (broll-5), so a ledger
    locked for a second at boot took the whole /broll mount down with it, and
    the request-path guard only caught `sqlite3.Error` (regression-14).

The three JS findings are run, not read: ingest.js touches the DOM only inside
functions, so app.js + ingest.js load in a bare V8 and `ingestRetryFailedBatch`
can be called for real with `fetch` and the loopback stubbed - which is the
only way to see what the editor is actually shown.
"""
from __future__ import annotations

import json
import shutil
import sqlite3
import subprocess
from pathlib import Path

import pytest

from app import client_folders as cf
from app import main as app_main

STATIC = Path(__file__).resolve().parents[1] / "static"
MAIN_PY = (Path(__file__).resolve().parents[1] / "app" / "main.py").read_text(
    encoding="utf-8")


# --- the page: what the editor's press actually dispatches ----------------------

_HARNESS = """
const fs = require('fs'), vm = require('vm');
const scenario = JSON.parse(process.argv[4]);
const trace = {toasts: [], notices: [], loopback: [], fetches: [], polled: 0};
const ctx = {
  document: {addEventListener() {}},
  window: {location: {pathname: '/broll/', assign() {}}},
  console,
};
vm.createContext(ctx);
vm.runInContext(fs.readFileSync(process.argv[2], 'utf8'), ctx);   // app.js
vm.runInContext(fs.readFileSync(process.argv[3], 'utf8'), ctx);   // ingest.js
ctx.fetch = async (url, opts) => {
  trace.fetches.push({url: String(url), method: (opts && opts.method) || 'GET'});
  const r = scenario.server || {ok: true, status: 200, body: {retried: 3}};
  return {ok: !!r.ok, status: r.status, json: async () => r.body};
};
ctx.toast = (m, k) => trace.toasts.push({message: String(m), kind: k || ''});
ctx.ingestSetNotice = (t) => trace.notices.push(String(t));
ctx.ingestStartPolling = () => { trace.polled += 1; };
ctx.ingestLoadBatches = async () => {};
ctx.ingestLoopback = async (method, path, body) => {
  trace.loopback.push({method, path, body});
  const l = scenario.loopback || {};
  if (l.status) {
    const err = new Error(l.message || 'boom');
    err.status = l.status;
    throw err;
  }
  return {ok: true};
};
vm.runInContext(`ing.batchUid = ${JSON.stringify(scenario.batch_uid || '')};` +
                `ing.stagingId = ${JSON.stringify(scenario.staging_id || '')};` +
                `ing.runMode = 'idle'; ing.running = false;`, ctx);
(async () => {
  await vm.runInContext(
    `ingestRetryFailedBatch(${JSON.stringify(scenario.uid)})`, ctx);
  trace.ing = JSON.parse(vm.runInContext(
    'JSON.stringify({batchUid: ing.batchUid, running: ing.running})', ctx));
  console.log(JSON.stringify(trace));
})().catch((e) => { console.log(JSON.stringify({error: String(e && e.stack || e)})); });
"""

needs_node = pytest.mark.skipif(shutil.which("node") is None,
                                reason="node not installed")


def _press_retry(tmp_path, **scenario) -> dict:
    harness = tmp_path / "retry_harness.js"
    harness.write_text(_HARNESS, encoding="utf-8")
    done = subprocess.run(
        ["node", str(harness), str(STATIC / "app.js"), str(STATIC / "ingest.js"),
         json.dumps(scenario)],
        capture_output=True, text=True, encoding="utf-8", check=True)
    trace = json.loads(done.stdout)
    assert "error" not in trace, trace.get("error")
    return trace


@needs_node
def test_retry_failed_hands_the_companion_this_pages_staging_id(tmp_path):
    """comp-broll-music-1: `staging_id: null` is the one value that makes the
    claim useless - `_item_from_manifest` populates `local_path` out of
    `self._staging[staging_id]` and nowhere else, so every item of the batch
    is crunched with no source and fails immediately, twice."""
    trace = _press_retry(tmp_path, uid="b1", batch_uid="b1", staging_id="stg1")
    assert len(trace["loopback"]) == 1
    body = trace["loopback"][0]["body"]
    assert body["batch_uid"] == "b1"
    assert body["staging_id"] == "stg1", (
        "the bytes of the failed clips are in THIS page's staging entry")


@needs_node
def test_retry_failed_sends_no_staging_id_for_someone_elses_batch(tmp_path):
    """The guard the music page has: a batch this page did not stage has no
    staging entry here, and claiming one that belongs to a different drop
    would crunch the wrong files."""
    trace = _press_retry(tmp_path, uid="other", batch_uid="b1", staging_id="stg1")
    assert trace["loopback"][0]["body"]["staging_id"] is None


@needs_node
def test_a_busy_companion_is_quoted_and_the_panel_does_not_start_polling(tmp_path):
    """broll-1: `run()` answers "this computer is already indexing another
    batch" before it attempts any claim, and that is the 409 that reaches this
    branch - the remote-leaseholder case is refused by the server route above
    it. The page told the editor another of their computers would pick the
    clips up (nothing polls for queued batches, so nothing would) and then set
    the live panel polling a run that was never started."""
    trace = _press_retry(tmp_path, uid="b1", batch_uid="b1", staging_id="stg1",
                         loopback={"status": 409,
                                   "message": "this computer is already "
                                              "indexing another batch"})
    assert trace["notices"], "the editor is told what happened"
    assert "already indexing another batch" in trace["notices"][-1]
    assert "Another of your computers" not in " ".join(trace["notices"])
    assert trace["polled"] == 0, "nothing was dispatched, so nothing is running"
    assert trace["ing"]["running"] is False


@needs_node
def test_a_held_batch_reaches_the_editor_as_a_sentence(tmp_path):
    """broll-2: the refusal is an HTTPException with a DICT detail, and
    `new Error(object).message` is the string "[object Object]"."""
    detail = ("EDIT-01 is still working on this batch. Stop it first, then "
              "try the failed clips again.")
    trace = _press_retry(
        tmp_path, uid="b1", batch_uid="b1", staging_id="stg1",
        server={"ok": False, "status": 409,
                "body": {"detail": {"detail": detail, "reason": "held",
                                    "machine": "EDIT-01"}}})
    assert trace["toasts"], "the press is answered"
    assert trace["toasts"][-1]["message"] == detail
    assert trace["loopback"] == [], "a refused reset dispatches nothing"


# --- the ledger: a create that a kill cannot half-finish ------------------------

def test_a_kill_inside_the_create_leaves_nothing_behind(data_root):
    """broll-3: `executescript` runs in autocommit, so each CREATE was durable
    the instant it ran while `PRAGMA user_version = 2` was the last statement
    of the script. A container killed in there left tables at version 0, and
    every later entry raised `table client_folders already exists` for ever -
    a 500 on every client-folder route and every public share link."""
    path = cf.get_db_path()
    original_connect = sqlite3.connect

    class _KilledMidCreate:
        """Dies inside the create wherever the caller issues it from: one
        `executescript` (the old code) or one `execute` per statement (the
        new one). Two tables get made, the third is where the process stops."""

        def __init__(self, conn):
            self._conn = conn
            self._left = 2

        def _maybe_die(self, sql: str) -> None:
            if sql.strip().upper().startswith("CREATE"):
                if self._left <= 0:
                    raise sqlite3.OperationalError("killed mid-create")
                self._left -= 1

        def execute(self, sql, *args):
            self._maybe_die(sql)
            return self._conn.execute(sql, *args)

        def executescript(self, script):
            # Split here rather than through the app's own helper: this test
            # must fail on the OLD source for the reason it is about, not
            # because a helper the fix introduced is missing (tests-5).
            buffer = ""
            for line in script.splitlines(True):
                buffer += line
                if buffer.strip() and sqlite3.complete_statement(buffer):
                    self._maybe_die(buffer)
                    self._conn.execute(buffer)
                    buffer = ""

        def __getattr__(self, name):
            return getattr(self._conn, name)

    # A nested context, NOT this test's `monkeypatch`: the data_root fixture
    # takes the same function-scoped instance, so an undo() here would put the
    # data root back to the repo's own and write the rest of the test into it.
    with pytest.MonkeyPatch.context() as kill:
        kill.setattr(cf.sqlite3, "connect",
                     lambda *a, **k: _KilledMidCreate(original_connect(*a, **k)))
        with pytest.raises(sqlite3.OperationalError):
            cf.ensure_schema()

    after = sqlite3.connect(path)
    tables = [r[0] for r in after.execute(
        "SELECT name FROM sqlite_master WHERE type = 'table' "
        "AND name NOT LIKE 'sqlite_%'").fetchall()]
    version = after.execute("PRAGMA user_version").fetchone()[0]
    after.close()
    assert tables == [], (
        f"a create that did not finish left {tables} durable at version "
        f"{version}: the next entry raises 'already exists' for ever")

    # And the file is still usable: the next request creates it properly.
    cf.ensure_schema()
    done = sqlite3.connect(path)
    assert done.execute("PRAGMA user_version").fetchone()[0] == cf.SCHEMA_VERSION
    done.close()


def test_a_ledger_created_by_the_old_code_still_finishes(data_root):
    """The file the old code already left on a customer's NAS: tables durable,
    user_version 0. It must migrate rather than raise `already exists`."""
    path = cf.get_db_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    half = sqlite3.connect(path)
    half.executescript("CREATE TABLE client_folders (id INTEGER PRIMARY KEY, "
                       "token TEXT NOT NULL UNIQUE, title TEXT NOT NULL);")
    half.execute("PRAGMA user_version = 0")
    half.commit()
    half.close()

    cf.ensure_schema()

    done = sqlite3.connect(path)
    assert done.execute("PRAGMA user_version").fetchone()[0] == cf.SCHEMA_VERSION
    tables = {r[0] for r in done.execute(
        "SELECT name FROM sqlite_master WHERE type = 'table'").fetchall()}
    done.close()
    assert {"client_folders", "client_folder_items",
            "client_share_settings"} <= tables


def test_a_backfill_that_failed_is_not_retired_by_the_version_stamp(
        data_root, conn):
    """broll-6: the step was stamped whether or not it ran, so items curated
    before v2 lost the hash identity - the one that survives an
    /api/ingest/moved rename - silently and for ever."""
    from tests.factories import insert_video

    cf.ensure_schema()
    rel_path = "Inbox/A001.mp4"
    vid = insert_video(conn, share="broll", rel_path=rel_path, hash="a1b2c3",
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
    ledger.execute("PRAGMA user_version = 1")
    ledger.commit()
    ledger.close()

    # broll.db mid-publish_db.py rename: the index path is there and
    # sqlite3.connect raises on it, which is the real shape of the failure.
    decoy = Path(data_root) / "broll.db.publishing"
    decoy.mkdir()
    with pytest.MonkeyPatch.context() as mid_publish:
        mid_publish.setattr(cf.config, "get_db_path", lambda: decoy)
        cf.ensure_schema()

    mid = sqlite3.connect(cf.get_db_path())
    assert mid.execute("PRAGMA user_version").fetchone()[0] == 1, (
        "a migration step that did not run must be retried, not stamped done")
    mid.close()

    cf.ensure_schema()
    done = cf.open_connection()
    assert done.execute("PRAGMA user_version").fetchone()[0] == cf.SCHEMA_VERSION
    assert done.execute(
        "SELECT hash FROM client_folder_items").fetchone()["hash"] == "a1b2c3"
    done.close()


def test_the_share_door_survives_a_data_root_that_went_read_only(
        data_root, monkeypatch):
    """regression-14: the handler that holds the public share door open caught
    `sqlite3.Error` only, and the failure most likely to reach it - an
    unmounted or read-only dataset - raises OSError out of the `mkdir` and out
    of `sqlite3.connect`, before any sqlite error can happen."""
    cf.ensure_schema()

    def read_only(db_path=None):
        raise PermissionError(30, "Read-only file system")

    monkeypatch.setattr(cf, "ensure_schema", read_only)
    gen = cf.get_shares_db()
    conn = next(gen)
    try:
        assert conn.execute("PRAGMA user_version").fetchone()[0] >= 1
    finally:
        gen.close()


def test_a_ledger_problem_at_boot_does_not_degrade_the_whole_mount(
        data_root, monkeypatch):
    """broll-5: both boot paths called `ensure_schema` bare, so a ledger
    locked for the second the container starts either stopped the app booting
    or marked the WHOLE /broll mount DEGRADED - nav link hidden, home page
    blaming a data root that is fine - while every request worked."""
    calls = []

    def locked(db_path=None):
        calls.append(db_path)
        raise sqlite3.OperationalError("database is locked")

    monkeypatch.setattr(cf, "ensure_schema", locked)
    assert cf.ensure_schema_best_effort() is False
    assert calls, "it really did try"

    def read_only(db_path=None):
        raise OSError(30, "Read-only file system")

    monkeypatch.setattr(cf, "ensure_schema", read_only)
    assert cf.ensure_schema_best_effort() is False

    def too_new(db_path=None):
        raise RuntimeError("FATAL: user_version=99, newer than this app supports")

    monkeypatch.setattr(cf, "ensure_schema", too_new)
    with pytest.raises(RuntimeError):
        cf.ensure_schema_best_effort()


def test_the_standalone_boot_uses_the_best_effort_call(data_root, monkeypatch):
    """The lifespan itself, not only the helper: `uvicorn app.main:app` must
    come up with a ledger that cannot be opened."""
    import asyncio

    def locked(db_path=None):
        raise sqlite3.OperationalError("database is locked")

    monkeypatch.setattr(app_main.client_folders, "ensure_schema", locked)

    async def boot():
        async with app_main.lifespan(app_main.app):
            return True

    assert asyncio.run(boot()) is True
    assert "ensure_schema_best_effort" in MAIN_PY
