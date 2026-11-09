"""The `ledger-scan` job: the walker, its rules, the gzip chunks, and the runner's own lane for it.

Protocol: footage-sorter docs/LEDGER-BROWSER-DESIGN.md, "The companion" item 2. A temp folder stands in for
a drive; the dashboard is test_jobs_runner's fake plus the sorter's scan routes.
"""
from __future__ import annotations

import gzip
import json
import os
import threading
import time
from pathlib import Path

import pytest

from ccsync_companion import card_copy, ledger_scan, sorter_cards
from ccsync_companion import jobs_runner as runner_mod

from test_card_copy import IngestDash, World, card_job, copy_item, runner
from test_jobs_runner import FakeDashboard, FakeIdle

SERIAL = "BEEF0001"


@pytest.fixture(autouse=True)
def _clean_registry():
    sorter_cards._busy.clear()
    yield
    sorter_cards._busy.clear()


def tree(root: Path, files: dict) -> Path:
    for rel, data in files.items():
        p = root / rel
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_bytes(data if isinstance(data, bytes) else b"x" * int(data))
    return root


def listing(root, roots=("",), rules=None, **kw):
    sent = []

    def send(seq, rows):
        sent.append((seq, rows))
        return 200

    scan = ledger_scan.LedgerScan(send, **kw)
    result = scan.run(str(root), list(roots), rules)
    return scan, result, sent


def all_rows(sent):
    return [r for _, rows in sent for r in rows]


# ------------------------------------------------------------------ the rules

def test_only_tracked_files_are_listed_with_paths_relative_to_the_volume(tmp_path):
    tree(tmp_path, {"FieldBackup/Trip/A001.braw": 10, "FieldBackup/Trip/A001.BRAW.part": 3,
                    "FieldBackup/Trip/notes.txt": 4, "FieldBackup/Trip/a.mov": 7, "Rec/ZOOM0001.WAV": 5,
                    "Rec/take.tmp.mp4": 9, "Rec/.DS_Store": 1, "Rec/._ZOOM0001.WAV": 1,
                    "$RECYCLE.BIN/x.mov": 2, "node_modules/y.mp4": 2, "CacheClip/c.mov": 2,
                    "OptimizedMedia/o.mov": 2, "Proxy/p.mp4": 6, "Proxy/p.mkv": 8, "Other/q.mkv": 9,
                    "Proxies/Sub/r.webm": 4, "Proxy/photo.jpg": 3})
    _scan, result, sent = listing(tmp_path)
    got = {r[0]: r[1] for r in all_rows(sent)}
    assert got == {"FieldBackup/Trip/A001.braw": 10, "FieldBackup/Trip/a.mov": 7, "Rec/ZOOM0001.WAV": 5,
                   "Proxy/p.mp4": 6, "Proxy/p.mkv": 8, "Proxies/Sub/r.webm": 4}      # a .mkv is only kept inside a Proxy folder
    assert result["files"] == 6 and result["bytes"] == 40 and result["complete"] is True
    for path, size, mtime in all_rows(sent):
        assert "\\" not in path and not path.startswith("/")
        assert isinstance(mtime, int) and mtime > 10 ** 12          # epoch milliseconds


def test_the_mtime_is_epoch_milliseconds_of_the_file(tmp_path):
    tree(tmp_path, {"a.braw": 5})
    os.utime(tmp_path / "a.braw", (1_786_236_852, 1_786_236_852.123))
    _s, _r, sent = listing(tmp_path)
    assert all_rows(sent) == [["a.braw", 5, 1_786_236_852_123]]


def test_roots_limit_the_walk_and_keep_their_prefix(tmp_path):
    tree(tmp_path, {"FieldBackup/a.braw": 1, "Other/b.braw": 1, "FieldBackup/Sub/c.mov": 1})
    _s, result, sent = listing(tmp_path, roots=["FieldBackup"])
    assert sorted(r[0] for r in all_rows(sent)) == ["FieldBackup/Sub/c.mov", "FieldBackup/a.braw"]
    # backslashes and slashes at the edges are the same root
    _s, _r, sent = listing(tmp_path, roots=["\\FieldBackup\\Sub\\"])
    assert [r[0] for r in all_rows(sent)] == ["FieldBackup/Sub/c.mov"]


def test_a_root_that_climbs_out_or_names_a_drive_is_dropped():
    assert ledger_scan.clean_roots(["../x", "C:/Windows", "ok/dir", "ok\\dir", ""]) == ["ok/dir", ""]
    assert ledger_scan.clean_roots(None) == [""]
    assert ledger_scan.clean_roots(["../x"]) == []             # named roots, none safe: no roots, never the whole drive
    assert ledger_scan.clean_roots([]) == [""]
    with pytest.raises(ledger_scan.ScanError):
        ledger_scan.LedgerScan(lambda s, r: 200).run(".", ["../x"])


def test_a_root_that_is_not_there_lists_nothing_and_still_completes(tmp_path):
    tree(tmp_path, {"a.braw": 1})
    _s, result, sent = listing(tmp_path, roots=["Gone"])
    assert all_rows(sent) == [] and result["complete"] is True and result["unreadable"] == []      # absent = empty, an answer


def test_the_manifest_rules_are_the_servers_and_override_the_built_in_ones(tmp_path):
    tree(tmp_path, {"a.braw": 1, "b.xyz": 2, "keep/c.xyz": 3, "skipme/d.xyz": 4, "e.xyz.bak": 5, "Prox/f.mkv": 6,
                    "g.xyz.tmpfile": 7})
    rules = {"masterExts": ["XYZ"], "audioExts": [], "proxyVideoExts": ["mkv"], "proxyDirs": ["prox"],
             "skipDirs": ["skipme"], "skipSuffixes": [".bak"], "skipPrefixes": ["g."], "tempRe": r"\.tmpfile$"}
    _s, _r, sent = listing(tmp_path, rules=rules)
    assert sorted(r[0] for r in all_rows(sent)) == ["Prox/f.mkv", "b.xyz", "keep/c.xyz"]
    # a malformed rules object is the built-in rules, not an error
    _s, _r, sent = listing(tmp_path, rules={"masterExts": "braw", "skipDirs": 7, "tempRe": "("})
    assert [r[0] for r in all_rows(sent)] == ["a.braw"]
    # the rules the sorter really sends parse
    rules_doc = {"masterExts": ["braw", "mov"], "audioExts": ["wav"], "proxyVideoExts": ["mov", "mp4"],
                 "proxyDirs": ["proxies", "proxy"], "proxyNameRe": r"\dS\d{2}\.mp4$", "skipDirs": ["cacheclip"],
                 "skipSuffixes": [".part"], "tempRe": r"\.tmp\.[^./\\]+$", "skipPrefixes": ["._"], "slackMs": 3000}
    _s, _r, sent = listing(tmp_path, rules=rules_doc)
    assert [r[0] for r in all_rows(sent)] == ["a.braw"]


def test_the_scan_reads_and_never_writes(tmp_path):
    tree(tmp_path, {"a.braw": 1, "d/b.mov": 2})
    before = sorted((str(p.relative_to(tmp_path)), p.stat().st_mtime_ns) for p in tmp_path.rglob("*"))
    listing(tmp_path)
    after = sorted((str(p.relative_to(tmp_path)), p.stat().st_mtime_ns) for p in tmp_path.rglob("*"))
    assert before == after


# ------------------------------------------------------------------ chunks

def test_rows_go_out_in_chunks_with_a_running_seq(tmp_path):
    tree(tmp_path, {f"d{i % 3}/c{i:03}.mov": 1 for i in range(23)})
    scan, result, sent = listing(tmp_path, rows_per_chunk=10)
    assert [seq for seq, _ in sent] == [0, 1, 2]
    assert [len(rows) for _, rows in sent] == [10, 10, 3]
    assert result["chunks"] == 3 and result["files"] == 23


def test_the_default_chunk_is_five_thousand_rows():
    assert ledger_scan.CHUNK_ROWS == 5000 and ledger_scan.PROGRESS_SECONDS == 2.0


def test_a_chunk_is_retried_under_the_same_seq(tmp_path):
    tree(tmp_path, {"a.mov": 1, "b.mov": 1})
    calls = []
    statuses = iter([503, 0, 200, 200])

    def send(seq, rows):
        calls.append(seq)
        status = next(statuses)
        if status == 0:
            raise OSError("down")
        return status

    waits = []
    scan = ledger_scan.LedgerScan(send, rows_per_chunk=1, wait=lambda s: waits.append(s) or False)
    result = scan.run(str(tmp_path), [""])
    assert calls == [0, 0, 0, 1] and result["complete"] is True and len(waits) == 2


def test_a_chunk_the_dashboard_refuses_ends_the_scan(tmp_path):
    tree(tmp_path, {"a.mov": 1})
    scan = ledger_scan.LedgerScan(lambda seq, rows: 422, wait=lambda s: False)
    with pytest.raises(ledger_scan.ScanError) as e:
        scan.run(str(tmp_path), [""])
    assert e.value.retryable is False
    scan = ledger_scan.LedgerScan(lambda seq, rows: 403, wait=lambda s: False)
    with pytest.raises(ledger_scan.ScanError) as e:
        scan.run(str(tmp_path), [""])
    assert e.value.retryable is True


def test_a_chunk_that_never_gets_through_fails_retryably(tmp_path):
    tree(tmp_path, {"a.mov": 1})
    n = []
    scan = ledger_scan.LedgerScan(lambda seq, rows: n.append(1) or 500, wait=lambda s: False)
    with pytest.raises(ledger_scan.ScanError) as e:
        scan.run(str(tmp_path), [""])
    assert e.value.retryable is True and len(n) == ledger_scan.CHUNK_TRIES


# ------------------------------------------------------------------ cut short

def test_a_stop_ends_the_walk_incomplete_with_the_reason(tmp_path):
    tree(tmp_path, {f"d{i}/a.mov": 1 for i in range(6)})
    state = {"n": 0}

    def stop():
        state["n"] += 1
        return "cancelled" if state["n"] > 3 else ""

    scan, result, sent = listing(tmp_path, should_stop=stop)
    assert result["complete"] is False and result["reason"] == "cancelled"
    assert 0 < result["files"] < 6


def test_a_drive_that_vanishes_mid_scan_is_incomplete(tmp_path):
    tree(tmp_path, {f"d{i}/a.mov": 1 for i in range(6)})
    gone = {"yes": False}
    real = os.scandir

    def flaky(path):
        if gone["yes"]:
            raise OSError(5, "the device is not ready")
        return real(path)

    clock = {"t": 0.0}

    def tick():
        clock["t"] += 10.0                 # every look at the drive is past the alive-check interval
        return clock["t"]

    seen = {"n": 0}

    def alive():
        seen["n"] += 1
        if seen["n"] > 2:
            gone["yes"] = True
        return not gone["yes"]

    import ccsync_companion.ledger_scan as mod
    orig = mod.os.scandir
    mod.os.scandir = flaky
    try:
        scan, result, sent = listing(tmp_path, alive=alive, clock=tick)
    finally:
        mod.os.scandir = orig
    assert result["complete"] is False and "gone" in result["reason"]
    assert scan.vanished is True


def test_an_unreadable_folder_is_named_and_the_scan_stays_complete(tmp_path, monkeypatch):
    tree(tmp_path, {"ok/a.mov": 1, "locked/b.mov": 1})
    real = os.scandir

    def deny(path):
        if str(path).endswith("locked"):
            raise PermissionError(13, "denied")
        return real(path)

    monkeypatch.setattr(ledger_scan.os, "scandir", deny)
    _s, result, sent = listing(tmp_path, alive=lambda: True)
    assert [r[0] for r in all_rows(sent)] == ["ok/a.mov"]
    # a folder that would not open is NAMED, and the server exempts it from "gone": the scan stays complete
    assert result["complete"] is True and result["unreadable"] == ["locked"] and result["unreadableCount"] == 1


# ------------------------------------------------------------------ progress

def test_progress_reports_files_bytes_rate_and_the_folder():
    t = {"now": 0.0}
    p = ledger_scan.Progress(lambda: t["now"])
    p.visit("Trip/Day1")
    p.add(1000)
    p.add(3000)
    t["now"] = 2.0
    snap = p.snapshot()
    assert snap["filesDone"] == 2 and snap["bytesSeen"] == 4000 and snap["current"] == "Trip/Day1"
    assert snap["bps"] == 2000.0
    t["now"] = 4.0                                    # nothing new: the rate falls, it does not jump to zero
    assert 0 < p.snapshot()["bps"] < 2000.0


# ------------------------------------------------------------------ the job against a fake dashboard

class ScanDash(IngestDash):
    """The fleet job routes plus the sorter's scan routes. Records gunzipped chunks."""

    def __init__(self, job, manifest):
        super().__init__(job)
        self.manifest = manifest
        self.scan_calls: list[tuple[str, str, object, dict]] = []
        self.chunks: list[dict] = []
        self.progress: list[dict] = []
        self.finish: list[dict] = []
        self.chunk_statuses: list = []
        self.manifest_status = 200

    def request(self, method, url, body, headers, timeout):
        if "/sorter/agent/ledger/scan/" in url:
            self.scan_calls.append((method, url, body, headers))
            if method == "GET":
                return (self.manifest_status, self.manifest if self.manifest_status == 200 else {"detail": "no"})
            if url.endswith("/chunk"):
                assert isinstance(body, bytes) and headers.get("Content-Encoding") == "gzip"
                status = self.chunk_statuses.pop(0) if self.chunk_statuses else 200
                if status == "boom":
                    raise OSError("network down")
                if status == 200:
                    self.chunks.append(json.loads(gzip.decompress(body)))
                return status, {"ok": True}
            if url.endswith("/progress"):
                self.progress.append(body)
                return 200, {"ok": True}
            if url.endswith("/finish"):
                self.finish.append(body)
                return 200, {"ok": True}
        return super().request(method, url, body, headers, timeout)


class Rig:
    """A drive with a serial, the runner with the ledger capability, and a scan job on offer."""

    def __init__(self, tmp_path, files, roots=("",), job_id=41):
        self.world = World(tmp_path)
        self.drive = tree(self.world.drive, files)
        self.serial = self.world.drive_serial
        self.job = {"id": job_id, "kind": "ledger-scan",
                    "inputs": {"volumeId": f"vol:{self.serial}", "serial": self.serial, "roots": list(roots), "scanId": 5}}
        self.dash = ScanDash(dict(self.job), {"volumeId": f"vol:{self.serial}", "roots": list(roots), "rules": {}})
        self.job_id = job_id

    def volumes(self, scope, skip=()):
        return [{"serial": self.serial, "label": "FIELD", "drive": "D:", "root": str(self.drive),
                 "capacity": 1, "free": 1, "removable": False, "fs": "NTFS", "drive_type": "fixed", "system": False}]

    def runner(self, **over):
        r = runner(self.world, self.dash, caps={"sorter_cards": True, "sorter_ledger": True}, **over)
        r._volumes_fn = self.volumes
        return r

    def run(self, **over):
        r = self.runner(**over)
        r.note_report_reply({"commands": {"jobs": {"offered": [self.job_id]}}})
        r.tick()
        t = r._scan_thread
        assert t is not None
        t.join(timeout=20)
        assert not t.is_alive()
        return r


def test_a_scan_job_uploads_the_listing_and_finishes_complete(tmp_path):
    rig = Rig(tmp_path, {"a.braw": 10, "sub/b.mov": 20, "notes.txt": 3})
    rig.run()
    rows = [r for c in rig.dash.chunks for r in c["rows"]]
    assert sorted(r[0] for r in rows) == ["a.braw", "sub/b.mov"]
    assert [c["seq"] for c in rig.dash.chunks] == [0]
    assert rig.dash.finish == [{"files": 2, "bytes": 30, "complete": True}]
    res = rig.dash.results[-1]
    assert res["ok"] is True and res["result"]["files"] == 2 and res["result"]["complete"] is True
    # every call carries the fleet credential
    for _m, _u, _b, h in rig.dash.scan_calls:
        assert h["X-CCSync-Token"] == "tok" and h["X-CCSync-Identity"] == "ident"
    assert rig.dash.scan_calls[0][:2] == ("GET", "http://dash.example/sorter/agent/ledger/scan/41")


def test_the_manifests_roots_win_over_the_job_row(tmp_path):
    rig = Rig(tmp_path, {"FieldBackup/a.braw": 1, "Other/b.braw": 1}, roots=("",))
    rig.dash.manifest["roots"] = ["FieldBackup"]
    rig.dash.manifest["chunkRows"] = 100
    rig.run()
    assert [r[0] for c in rig.dash.chunks for r in c["rows"]] == ["FieldBackup/a.braw"]


def test_progress_goes_out_while_the_scan_runs(tmp_path, monkeypatch):
    monkeypatch.setattr(ledger_scan, "PROGRESS_SECONDS", 0.05)
    rig = Rig(tmp_path, {"a.braw": 10})
    release = threading.Event()
    real_send = ledger_scan.LedgerScan._send_with_retry

    def slow(self, seq, rows):
        release.wait(5)
        return real_send(self, seq, rows)

    monkeypatch.setattr(ledger_scan.LedgerScan, "_send_with_retry", slow)
    r = rig.runner()
    r.note_report_reply({"commands": {"jobs": {"offered": [rig.job_id]}}})
    r.tick()
    deadline = time.time() + 5
    while not rig.dash.progress and time.time() < deadline:
        time.sleep(0.02)
    release.set()
    r._scan_thread.join(timeout=10)
    assert rig.dash.progress, "no progress was posted while the chunk was held"
    assert set(rig.dash.progress[0]) >= {"filesDone", "bytesSeen", "bps", "current"}


def test_a_scan_of_a_drive_that_is_not_here_finishes_incomplete_and_fails_without_retry(tmp_path):
    rig = Rig(tmp_path, {"a.braw": 1})
    rig.serial = "NOPE0000"
    rig.dash.manifest["volumeId"] = "vol:NOPE0000"
    rig.job["inputs"]["serial"] = "NOPE0000"
    rig.dash.job["inputs"]["serial"] = "NOPE0000"
    r = rig.runner()
    r._volumes_fn = lambda scope, skip=(): []
    r.note_report_reply({"commands": {"jobs": {"offered": [rig.job_id]}}})
    r.tick()
    r._scan_thread.join(timeout=10)
    assert rig.dash.finish and rig.dash.finish[0]["complete"] is False
    res = rig.dash.results[-1]
    assert res["ok"] is False and res["retryable"] is False


def test_a_cancel_finishes_the_scan_incomplete_and_is_not_retried(tmp_path):
    rig = Rig(tmp_path, {f"d{i}/a.mov": 1 for i in range(5)})
    r = rig.runner()
    r.note_report_reply({"commands": {"jobs": {"offered": [rig.job_id], "cancel": [rig.job_id]}}})
    r.tick()
    r._scan_thread.join(timeout=10)
    assert rig.dash.finish and rig.dash.finish[-1]["complete"] is False
    res = rig.dash.results[-1]
    assert res["ok"] is False and res["error"] == runner_mod.CANCELLED_ERROR and res["retryable"] is False


def test_a_manifest_the_sorter_does_not_have_fails_the_job_without_retry(tmp_path):
    rig = Rig(tmp_path, {"a.braw": 1})
    rig.dash.manifest_status = 404
    rig.run()
    res = rig.dash.results[-1]
    assert res["ok"] is False and res["retryable"] is False and rig.dash.chunks == []


def test_a_finish_that_cannot_be_delivered_fails_the_job_retryably(tmp_path, monkeypatch):
    monkeypatch.setattr(ledger_scan, "FINISH_TRIES", 1)
    rig = Rig(tmp_path, {"a.braw": 1})
    real = rig.dash.request

    def request(method, url, body, headers, timeout):
        if url.endswith("/finish"):
            return 500, None
        return real(method, url, body, headers, timeout)

    rig.dash.request = request
    rig.run()
    res = rig.dash.results[-1]
    assert res["ok"] is False and res["retryable"] is True


def test_a_drive_a_card_copy_owns_is_not_scanned(tmp_path):
    rig = Rig(tmp_path, {f"d{i}/a.mov": 1 for i in range(5)})
    with sorter_cards.ingest_busy(rig.serial, str(rig.drive)):
        rig.run()
    assert rig.dash.finish and rig.dash.finish[-1]["complete"] is False
    assert "copied from" in rig.dash.results[-1]["error"]


# ------------------------------------------------------------------ the lane

def test_a_long_scan_does_not_hold_a_card_copy_behind_it(tmp_path, monkeypatch):
    """The scan runs on its own thread: tick() returns at once and the same runner then claims
    and runs a card-ingest while the scan is still walking."""
    rig = Rig(tmp_path, {"a.braw": 10})
    w = rig.world
    w.write(w.card, "a.MP4", b"12345")
    release = threading.Event()
    real_send = ledger_scan.LedgerScan._send_with_retry

    def held(self, seq, rows):
        release.wait(10)
        return real_send(self, seq, rows)

    monkeypatch.setattr(ledger_scan.LedgerScan, "_send_with_retry", held)
    dash = rig.dash
    plan = {"copies": [copy_item("a.MP4", "Footage/Day1/a.MP4", 5)], "folders": [{"root": "pool", "rel": "Footage/Day1"}]}
    dash.plan = plan
    queue = [dict(rig.job), {"id": 42, "kind": "card-ingest", "inputs": {"serial": w.card_serial, "label": "SD-3",
                                                                          "mode": "final", "verify": "quick", "files": 1}}]
    real_claim = dash.request

    def request(method, url, body, headers, timeout):
        if url.endswith("/api/v1/jobs/claim"):
            kinds = body.get("kinds") or []
            for j in list(queue):
                if j["kind"] in kinds:
                    queue.remove(j)
                    return 200, {"job": j}
            return 200, {"job": None}
        return real_claim(method, url, body, headers, timeout)

    dash.request = request

    def volumes(scope, skip=()):
        return rig.volumes(scope, skip) + [v for v in w.volumes("removable", skip)]

    r = runner(w, dash, caps={"sorter_cards": True, "sorter_ledger": True})
    r._volumes_fn = volumes
    r.note_report_reply({"commands": {"jobs": {"offered": [41, 42]}}})
    started = time.time()
    r.tick()                                           # claims the scan; returns without waiting for it
    assert time.time() - started < 5 and r._scan_running()
    assert "ledger-scan" not in r.runnable_kinds()     # one scan at a time per machine
    assert "card-ingest" in r.runnable_kinds()
    r.note_report_reply({"commands": {"jobs": {"offered": [42]}}})
    r.tick()                                           # ...and the card copy runs while the scan is held
    assert (w.pool / "Footage/Day1/a.MP4").read_bytes() == b"12345"
    assert any(x["ok"] for x in dash.results if x.get("result", {}).get("copied") == 1)
    assert r._scan_running()
    release.set()
    r._scan_thread.join(timeout=10)
    assert dash.finish and dash.finish[-1]["complete"] is True
    assert "ledger-scan" in r.runnable_kinds()


def test_the_kind_needs_the_capability_and_the_machines_allow_list(tmp_path):
    rig = Rig(tmp_path, {"a.braw": 1})
    on = rig.runner()
    assert "ledger-scan" in on.runnable_kinds()
    off = runner(rig.world, rig.dash, caps={"sorter_cards": True})
    assert "ledger-scan" not in off.runnable_kinds()
    narrow = runner(rig.world, rig.dash, caps={"sorter_cards": True, "sorter_ledger": True, "job_kinds": ["card-ingest"]})
    assert "ledger-scan" not in narrow.runnable_kinds()


# ------------------------------------------------------------------ outbox from a receipt

def test_a_drive_copy_whose_receipt_cannot_be_delivered_queues_its_local_copies(tmp_path, monkeypatch):
    from ccsync_companion import ledger_outbox
    monkeypatch.setattr(runner_mod, "RECEIPT_RETRY_SECONDS", 0)
    monkeypatch.setattr(runner_mod, "RECEIPT_TRIES", 1)
    w = World(tmp_path)
    w.write(w.pool, "Footage/D/a.mov", b"hello")
    job = {"id": 32, "kind": "drive-copy", "inputs": {"copies": [
        {"src": {"root": "pool", "rel": "Footage/D/a.mov"},
         "dst": {"root": f"local:{w.drive_serial}", "rel": "restore/a.mov"}, "size": 5}],
        "folders": [{"root": f"local:{w.drive_serial}", "rel": "restore"}]}}
    dash = IngestDash(job)
    dash.receipt_statuses = [503]
    box = tmp_path / "state" / "ledger-outbox.jsonl"
    r = runner(w, dash, ledger_outbox_path=str(box))

    def volumes(scope, skip=()):
        return w.volumes("local", skip)

    r._volumes_fn = volumes
    r.note_report_reply({"commands": {"jobs": {"offered": [32]}}})
    r.tick()
    assert dash.results[-1]["ok"] is False and dash.results[-1]["retryable"] is True
    queued = ledger_outbox.peek(box)
    assert len(queued) == 1
    assert queued[0]["volume"] == {"serial": w.drive_serial, "label": "SCRATCH"}
    assert queued[0]["path"] == "restore/a.mov" and queued[0]["size"] == 5 and queued[0]["verified"] == "full"
    assert queued[0]["mtime"] == int(round((w.drive / "restore/a.mov").stat().st_mtime * 1000))


def test_a_delivered_receipt_queues_nothing(tmp_path):
    from ccsync_companion import ledger_outbox
    w = World(tmp_path)
    w.write(w.pool, "Footage/D/a.mov", b"hello")
    job = {"id": 33, "kind": "drive-copy", "inputs": {"copies": [
        {"src": {"root": "pool", "rel": "Footage/D/a.mov"},
         "dst": {"root": f"local:{w.drive_serial}", "rel": "r/a.mov"}, "size": 5}],
        "folders": [{"root": f"local:{w.drive_serial}", "rel": "r"}]}}
    dash = IngestDash(job)
    box = tmp_path / "ledger-outbox.jsonl"
    r = runner(w, dash, ledger_outbox_path=str(box))
    r.note_report_reply({"commands": {"jobs": {"offered": [33]}}})
    r.tick()
    assert dash.results[-1]["ok"] is True and ledger_outbox.pending(box) == 0
