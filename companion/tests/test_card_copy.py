"""The `card-ingest` and `drive-copy` fleet jobs.

Protocol: footage-sorter docs/DASHBOARD-MODULE-PLAN.md, "Card ingest through
the companion", step 3. Temp dirs stand in for the card, the pool and a PC
drive; the dashboard is test_jobs_runner's fake.
"""
from __future__ import annotations

import os
from pathlib import Path

import pytest

from ccsync_companion import card_copy, sorter_cards
from ccsync_companion import jobs_runner as runner_mod

from test_jobs_runner import FakeDashboard, FakeIdle


class IngestDash(FakeDashboard):
    """The fleet job routes plus the sorter's copy list and receipt routes.
    The job row carries only small inputs; `copies`/`folders` are moved out
    of them and served from GET /sorter/agent/ingest/<id>."""

    def __init__(self, job=None):
        super().__init__(job)
        self.plan = {}
        if job:
            inputs = job["inputs"]
            for key in ("copies", "folders", "src_root"):
                if key in inputs:
                    self.plan[key] = inputs.pop(key)
            inputs.setdefault("files", len(self.plan.get("copies", [])))
        self.receipts: list[dict] = []
        self.plan_status = 200
        self.receipt_statuses: list = []       # popped per receipt attempt
        self.sorter_calls: list[tuple[str, str, dict, dict]] = []

    def request(self, method, url, body, headers, timeout):
        if "/sorter/agent/ingest/" in url:
            self.sorter_calls.append((method, url, body, headers))
            if url.endswith("/receipt"):
                status = self.receipt_statuses.pop(0) if self.receipt_statuses else 200
                if status == "boom":
                    raise OSError("network down")
                if status == 200:
                    self.receipts.append(body)
                return status, {"ok": True}
            if self.plan_status != 200:
                return self.plan_status, {"detail": "no"}
            return 200, {"serial": SERIAL, "label": "SD-3", "mode": "final",
                         "verify": "quick", **self.plan}
        return super().request(method, url, body, headers, timeout)


def final(dash):
    """The result post, with `result` swapped for the full receipt so the
    tests can read copied/skipped/conflicts/failed."""
    res = dict(dash.results[-1])
    res["small"] = res["result"]
    if dash.receipts:
        res["result"] = dash.receipts[-1]
    return res

SERIAL = "1038701C"
MIB = 1024 * 1024


@pytest.fixture(autouse=True)
def _clean_registry():
    sorter_cards._busy.clear()
    sorter_cards._known_drives.clear()
    yield
    sorter_cards._busy.clear()
    sorter_cards._known_drives.clear()


class World:
    """A card, a pool and a PC drive on tmp_path."""

    def __init__(self, tmp_path: Path):
        self.card = tmp_path / "card"
        self.drive = tmp_path / "pcdrive"
        self.pool = tmp_path / "pool"
        for d in (self.card, self.drive, self.pool, tmp_path / "tree"):
            d.mkdir()
        self.card_serial = SERIAL
        self.drive_serial = "AAAA0001"
        self.tmp = tmp_path

    def volumes(self, scope, skip=()):
        out = []
        if self.card_serial:
            out.append({"serial": self.card_serial, "label": "SD-3", "drive": "L:",
                        "root": str(self.card), "capacity": 1, "free": 1,
                        "removable": True})
        if scope == "local":
            out.append({"serial": self.drive_serial, "label": "SCRATCH", "drive": "D:",
                        "root": str(self.drive), "capacity": 1, "free": 1,
                        "removable": False})
        return [v for v in out if v["root"] not in skip]

    def cfg(self, **over):
        base = {"local_root": str(self.tmp / "tree"),
                "dashboard_url": "http://dash.example", "dashboard_token": "tok",
                "jobs_pool_root": str(self.pool), "jobs_idle_seconds": 300,
                "jobs_skip_while_resolve_running": True}
        base.update(over)
        return base

    def write(self, root: Path, rel: str, data: bytes) -> Path:
        path = root / rel
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(data)
        return path


def pool_ref(rel):
    return {"root": "pool", "rel": rel}


def card_job(copies, folders=None, serial=SERIAL, job_id=21, kind="card-ingest", **extra):
    inputs = {"serial": serial, "label": "SD-3", "mode": "final", "verify": "quick",
              "copies": copies, "folders": folders or [pool_ref("Footage/Day1")]}
    inputs.update(extra)
    return {"id": job_id, "kind": kind, "inputs": inputs}


def copy_item(src, dst_rel, size, clip="c1"):
    return {"src": src, "dst": pool_ref(dst_rel), "size": size, "clipId": clip}


CAPS = {"sorter_cards": True}


def runner(world, dash, idle=900, halted=lambda: False, caps=None, **over):
    return runner_mod.JobRunner(
        world.cfg(**over), request_fn=dash.request, identity_token_fn=lambda: "ident",
        capabilities_fn=lambda: (CAPS if caps is None else caps),
        idle_probe=FakeIdle(idle), resolve_running_fn=lambda: False,
        halted_fn=halted, machine_name="EDIT-PC", volumes_fn=world.volumes)


def run_job(world, job, **kw):
    dash = IngestDash(job)
    r = runner(world, dash, **kw)
    r.note_report_reply({"commands": {"jobs": {"offered": [job["id"]]}}})
    r.tick()
    return dash, final(dash)


def partials(root: Path):
    return [p for p in root.rglob("*") if p.name.endswith(".partial")]


# ----------------------------------------------------------- what is copied

def test_a_card_ingest_copies_creates_folders_and_reports(tmp_path):
    w = World(tmp_path)
    data = os.urandom(3 * MIB + 17)
    w.write(w.card, "PRIVATE/M4ROOT/CLIP/a.MP4", data)
    w.write(w.card, "PRIVATE/M4ROOT/CLIP/b.MP4", b"bee")
    job = card_job([copy_item("PRIVATE/M4ROOT/CLIP/a.MP4", "Footage/Day1/a.MP4", len(data)),
                    copy_item("PRIVATE/M4ROOT/CLIP/b.MP4", "Footage/Day1/b.MP4", 3, "c2")],
                   folders=[pool_ref("Footage/Day1"), pool_ref("Footage/Day1/Proxy")])
    dash, res = run_job(w, job)
    assert res["ok"] is True
    assert (w.pool / "Footage/Day1/a.MP4").read_bytes() == data
    assert (w.pool / "Footage/Day1/Proxy").is_dir()
    result = res["result"]
    assert [c["src"] for c in result["copied"]] == [
        "PRIVATE/M4ROOT/CLIP/a.MP4", "PRIVATE/M4ROOT/CLIP/b.MP4"]
    assert result["copied"][0] == {
        "src": "PRIVATE/M4ROOT/CLIP/a.MP4",
        "dst": {"root": "pool", "rel": "Footage/Day1/a.MP4"},
        "size": len(data), "verified": True, "filename": "a.MP4"}
    assert result["copier"] == "python"
    assert result["skipped"] == result["conflicts"] == result["failed"] == []
    assert not partials(w.pool)
    # the copy keeps the card file's modification time
    assert (os.stat(w.pool / "Footage/Day1/a.MP4").st_mtime_ns
            == os.stat(w.card / "PRIVATE/M4ROOT/CLIP/a.MP4").st_mtime_ns)


def test_a_same_size_identical_destination_is_skipped_and_verified(tmp_path):
    w = World(tmp_path)
    w.write(w.card, "a.MP4", b"12345")
    existing = w.write(w.pool, "Footage/Day1/a.MP4", b"12345")
    old = existing.stat().st_mtime_ns
    _, res = run_job(w, card_job([copy_item("a.MP4", "Footage/Day1/a.MP4", 5)]))
    result = res["result"]
    assert res["ok"] is True
    assert [s["src"] for s in result["skipped"]] == ["a.MP4"]
    # compared against the card, byte for byte, so it can say verified
    assert result["skipped"][0]["verified"] is True
    assert result["copied"] == [] and result["conflicts"] == []
    assert existing.read_bytes() == b"12345" and existing.stat().st_mtime_ns == old


def test_a_same_size_destination_with_other_bytes_is_a_conflict_not_assumed_identical(tmp_path):
    w = World(tmp_path)
    w.write(w.card, "a.MP4", b"12345")
    existing = w.write(w.pool, "Footage/Day1/a.MP4", b"abcde")     # same size, other bytes
    old = existing.stat().st_mtime_ns
    _, res = run_job(w, card_job([copy_item("a.MP4", "Footage/Day1/a.MP4", 5)]))
    result = res["result"]
    assert [c["src"] for c in result["conflicts"]] == ["a.MP4"]
    assert "same size" in result["conflicts"][0]["why"]
    assert result["skipped"] == [] and result["copied"] == []
    assert existing.read_bytes() == b"abcde" and existing.stat().st_mtime_ns == old


def test_a_difference_deep_inside_a_same_size_destination_is_still_a_conflict(tmp_path):
    w = World(tmp_path)
    data = bytearray(os.urandom(5 * MIB))
    w.write(w.card, "a.MP4", bytes(data))
    data[2 * MIB + 7] ^= 0xFF               # not in the first or last MiB
    w.write(w.pool, "Footage/Day1/a.MP4", bytes(data))
    _, res = run_job(w, card_job([copy_item("a.MP4", "Footage/Day1/a.MP4", 5 * MIB)]))
    assert len(res["result"]["conflicts"]) == 1 and res["result"]["skipped"] == []


def test_a_different_file_at_the_destination_is_a_conflict_and_left_alone(tmp_path):
    w = World(tmp_path)
    w.write(w.card, "a.MP4", b"12345")
    existing = w.write(w.pool, "Footage/Day1/a.MP4", b"different size")
    _, res = run_job(w, card_job([copy_item("a.MP4", "Footage/Day1/a.MP4", 5)]))
    result = res["result"]
    assert [c["src"] for c in result["conflicts"]] == ["a.MP4"]
    assert result["conflicts"][0]["dst"] == pool_ref("Footage/Day1/a.MP4")
    assert result["copied"] == []
    assert existing.read_bytes() == b"different size"
    assert not partials(w.pool)


def test_a_directory_at_the_destination_is_a_conflict(tmp_path):
    w = World(tmp_path)
    w.write(w.card, "a.MP4", b"12345")
    (w.pool / "Footage/Day1/a.MP4").mkdir(parents=True)
    _, res = run_job(w, card_job([copy_item("a.MP4", "Footage/Day1/a.MP4", 5)]))
    assert len(res["result"]["conflicts"]) == 1


def test_a_missing_source_is_a_failed_item_not_a_failed_job(tmp_path):
    w = World(tmp_path)
    w.write(w.card, "b.MP4", b"bee")
    _, res = run_job(w, card_job([copy_item("gone.MP4", "Footage/Day1/gone.MP4", 5),
                                  copy_item("b.MP4", "Footage/Day1/b.MP4", 3)]))
    assert res["ok"] is True
    assert [f["src"] for f in res["result"]["failed"]] == ["gone.MP4"]
    assert "cannot be read" in res["result"]["failed"][0]["why"]
    assert res["result"]["failed"][0]["dst"] == pool_ref("Footage/Day1/gone.MP4")
    assert [c["src"] for c in res["result"]["copied"]] == ["b.MP4"]


def test_a_source_that_changed_size_since_the_scan_is_failed(tmp_path):
    w = World(tmp_path)
    w.write(w.card, "a.MP4", b"123456789")
    _, res = run_job(w, card_job([copy_item("a.MP4", "Footage/Day1/a.MP4", 5)]))
    assert res["result"]["failed"][0]["src"] == "a.MP4"
    assert not (w.pool / "Footage/Day1/a.MP4").exists()


def test_a_job_that_climbs_out_of_the_card_fails_the_item(tmp_path):
    w = World(tmp_path)
    w.write(w.tmp, "secret.txt", b"s")
    _, res = run_job(w, card_job([copy_item("../secret.txt", "Footage/Day1/s.txt", 1)]))
    assert res["result"]["failed"][0]["src"] == "../secret.txt"
    assert not (w.pool / "Footage/Day1/s.txt").exists()


# ----------------------------------------------------------------- verifying

def test_verify_whole_catches_a_difference_anywhere(tmp_path):
    a, b = tmp_path / "a", tmp_path / "b"
    data = bytearray(os.urandom(5 * MIB))
    a.write_bytes(bytes(data))
    h = card_copy._new_hash()
    h.update(bytes(data))
    stop = lambda: ""           # noqa: E731
    assert card_copy.verify_whole(a, len(data), h.digest(), stop) == ""
    for where in (5, 2 * MIB + 3, len(data) - 10):      # first MiB, the middle, last MiB
        flipped = bytearray(data)
        flipped[where] ^= 0xFF
        b.write_bytes(bytes(flipped))
        assert "differs" in card_copy.verify_whole(b, len(data), h.digest(), stop)
    b.write_bytes(bytes(data)[:-1])
    assert "bytes" in card_copy.verify_whole(b, len(data), h.digest(), stop)


def test_a_verify_mismatch_is_reported_failed_and_nothing_is_left(tmp_path, monkeypatch):
    w = World(tmp_path)
    w.write(w.card, "a.MP4", b"12345")
    monkeypatch.setattr(card_copy, "verify_whole",
                        lambda *a, **k: "the copy read back differs from the source")
    _, res = run_job(w, card_job([copy_item("a.MP4", "Footage/Day1/a.MP4", 5)]))
    failed = res["result"]["failed"]
    assert failed == [{"src": "a.MP4", "dst": pool_ref("Footage/Day1/a.MP4"),
                       "why": "verify failed: the copy read back differs from the source"}]
    assert res["result"]["copied"] == []
    assert not (w.pool / "Footage/Day1/a.MP4").exists()
    assert not partials(w.pool)


def test_a_file_that_appears_mid_copy_is_not_overwritten(tmp_path, monkeypatch):
    w = World(tmp_path)
    w.write(w.card, "a.MP4", b"12345")
    real = card_copy.verify_whole

    def verify(path, size, digest, should_stop):
        # somebody else puts a file in place while ours is still a .partial
        w.write(w.pool, "Footage/Day1/a.MP4", b"theirs!")
        return real(path, size, digest, should_stop)

    monkeypatch.setattr(card_copy, "verify_whole", verify)
    _, res = run_job(w, card_job([copy_item("a.MP4", "Footage/Day1/a.MP4", 5)]))
    assert len(res["result"]["conflicts"]) == 1
    assert (w.pool / "Footage/Day1/a.MP4").read_bytes() == b"theirs!"
    assert not partials(w.pool)


# ------------------------------------------------------------ the right card

def test_a_different_card_in_the_drive_is_refused_not_retryable(tmp_path):
    w = World(tmp_path)
    w.write(w.card, "a.MP4", b"12345")
    sorter_cards.note_drive(SERIAL, str(w.card))        # the loop saw it there
    w.card_serial = "FFFF9999"                          # ...and the drive now holds another
    dash, res = run_job(w, card_job([copy_item("a.MP4", "Footage/Day1/a.MP4", 5)]))
    assert res["ok"] is False and res["retryable"] is False
    assert "different card" in res["error"] and "FFFF9999" in res["error"]
    assert not (w.pool / "Footage").exists()            # not even the folders


def test_a_card_that_is_not_in_any_reader_is_refused_not_retryable(tmp_path):
    w = World(tmp_path)
    w.card_serial = ""
    _, res = run_job(w, card_job([copy_item("a.MP4", "Footage/Day1/a.MP4", 5)]))
    assert res["ok"] is False and res["retryable"] is False
    assert "not in a card reader" in res["error"]


def test_a_pool_this_machine_lacks_fails_the_job_retryably_before_any_copy(tmp_path):
    w = World(tmp_path)
    w.write(w.card, "a.MP4", b"12345")
    _, res = run_job(w, card_job([copy_item("a.MP4", "Footage/Day1/a.MP4", 5)]),
                     jobs_pool_root="")
    assert res["ok"] is False and res["retryable"] is True
    assert "pool" in res["error"]


def test_the_card_is_marked_busy_while_it_is_copied(tmp_path, monkeypatch):
    w = World(tmp_path)
    w.write(w.card, "a.MP4", b"12345")
    seen = []
    real = card_copy.copy_file

    def spy(*a, **k):
        seen.append(sorter_cards.busy_serials())
        return real(*a, **k)

    monkeypatch.setattr(card_copy, "copy_file", spy)
    run_job(w, card_job([copy_item("a.MP4", "Footage/Day1/a.MP4", 5)]))
    assert seen == [{SERIAL}]
    assert sorter_cards.busy_serials() == set()


# ----------------------------------------------------------- halt and cancel

def test_a_halt_mid_copy_stops_it_and_discards_the_partial(tmp_path, monkeypatch):
    w = World(tmp_path)
    monkeypatch.setattr(card_copy, "BUFFER_BYTES", 1024)
    w.write(w.card, "a.MP4", os.urandom(64 * 1024))
    w.write(w.card, "b.MP4", b"bee")
    halted = {"now": False}
    real = card_copy.copy_file

    def copy_then_halt(src, dst, size, should_stop, on_bytes):
        count = {"n": 0}

        def stop():
            count["n"] += 1
            if count["n"] == 5:                 # a few chunks in
                halted["now"] = True
            return should_stop()

        return real(src, dst, size, stop, on_bytes)

    monkeypatch.setattr(card_copy, "copy_file", copy_then_halt)
    dash = IngestDash(card_job([copy_item("a.MP4", "Footage/Day1/a.MP4", 64 * 1024),
                                   copy_item("b.MP4", "Footage/Day1/b.MP4", 3, "c2")]))
    r = runner(w, dash, halted=lambda: halted["now"])
    r.note_report_reply({"commands": {"jobs": {"offered": [21]}}})
    r.tick()
    res = final(dash)
    assert res["ok"] is False and res["retryable"] is True
    assert "halt" in res["error"]
    assert not partials(w.pool)
    assert not (w.pool / "Footage/Day1/a.MP4").exists()
    assert not (w.pool / "Footage/Day1/b.MP4").exists()     # never started
    assert sorter_cards.busy_serials() == set()


def test_a_halt_keeps_what_finished_before_it_in_the_result(tmp_path):
    w = World(tmp_path)
    w.write(w.card, "a.MP4", b"aaa")
    w.write(w.card, "b.MP4", b"bbb")
    def halted():
        return (w.pool / "Footage/Day1/a.MP4").exists()     # once the first file has landed

    dash = IngestDash(card_job([copy_item("a.MP4", "Footage/Day1/a.MP4", 3),
                                   copy_item("b.MP4", "Footage/Day1/b.MP4", 3, "c2")]))
    r = runner(w, dash, halted=halted)
    r.note_report_reply({"commands": {"jobs": {"offered": [21]}}})
    r.tick()
    res = final(dash)
    assert res["ok"] is False
    assert [c["src"] for c in res["result"]["copied"]] == ["a.MP4"]
    assert not (w.pool / "Footage/Day1/b.MP4").exists()
    assert not partials(w.pool)


def test_an_admin_cancel_is_not_retryable(tmp_path, monkeypatch):
    w = World(tmp_path)
    w.write(w.card, "a.MP4", b"aaa")
    dash = IngestDash(card_job([copy_item("a.MP4", "Footage/Day1/a.MP4", 3)]))
    r = runner(w, dash)
    r.note_report_reply({"commands": {"jobs": {"offered": [21], "cancel": [21]}}})
    r.tick()
    res = final(dash)
    assert res["ok"] is False and res["retryable"] is False
    assert res["error"] == runner_mod.CANCELLED_ERROR


def test_a_stale_partial_from_a_crashed_run_is_replaced(tmp_path):
    w = World(tmp_path)
    w.write(w.card, "a.MP4", b"12345")
    w.write(w.pool, "Footage/Day1/a.MP4.partial", b"corpse")
    _, res = run_job(w, card_job([copy_item("a.MP4", "Footage/Day1/a.MP4", 5)]))
    assert len(res["result"]["copied"]) == 1
    assert (w.pool / "Footage/Day1/a.MP4").read_bytes() == b"12345"
    assert not partials(w.pool)


# ------------------------------------------------------- forced and targeted

def test_a_forced_card_ingest_is_claimed_with_the_editor_present(tmp_path):
    w = World(tmp_path)
    w.write(w.card, "a.MP4", b"12345")
    job = card_job([copy_item("a.MP4", "Footage/Day1/a.MP4", 5)])
    # idle 0: somebody is at the keyboard. Offered and not forced: not claimed.
    dash = IngestDash(job)
    r = runner(w, dash, idle=0)
    r.note_report_reply({"commands": {"jobs": {"offered": [21]}}})
    assert r.tick() is None and dash.claims == 0
    # Forced: claimed, by id, and run.
    r.note_report_reply({"commands": {"jobs": {"offered": [21], "forced": [21]}}})
    assert r.tick() is not None
    assert dash.calls[0][1]["ids"] == [21]
    assert dash.results[-1]["ok"] is True
    assert (w.pool / "Footage/Day1/a.MP4").read_bytes() == b"12345"


def test_the_runner_asks_for_the_card_kinds_only_where_cards_can_be_read(tmp_path):
    w = World(tmp_path)
    r = runner(w, FakeDashboard())
    assert set(r.runnable_kinds()) == {"card-ingest", "drive-copy"}
    r2 = runner(w, FakeDashboard(), caps={"whisper": True})
    assert "card-ingest" not in r2.runnable_kinds()


def test_this_machines_allow_list_can_exclude_the_card_kinds(tmp_path):
    w = World(tmp_path)
    r = runner(w, FakeDashboard(), caps={"sorter_cards": True, "job_kinds": ["whisper"]})
    assert r.runnable_kinds() == []


# ---------------------------------------------------------------- heartbeat

def test_the_heartbeat_carries_done_of_and_bytes(tmp_path, monkeypatch):
    w = World(tmp_path)
    w.write(w.card, "a.MP4", b"aaa")
    w.write(w.card, "b.MP4", b"bbb")
    monkeypatch.setattr(runner_mod, "HEARTBEAT_SECONDS", 0.05)
    real = card_copy.copy_file
    import time

    def slow(src, dst, size, should_stop, on_bytes):
        out = real(src, dst, size, should_stop, on_bytes)
        time.sleep(0.4)
        return out

    monkeypatch.setattr(card_copy, "copy_file", slow)
    dash, res = run_job(w, card_job([copy_item("a.MP4", "Footage/Day1/a.MP4", 3),
                                     copy_item("b.MP4", "Footage/Day1/b.MP4", 3, "c2")]))
    beats = [b for s, b in dash.calls if s.endswith("/heartbeat")]
    assert beats
    assert all(b.get("of") == 2 for b in beats)
    assert any(b.get("done") == 1 and b.get("bytes") == 6 and b.get("progress") == 1.0
               for b in beats)
    assert any(b.get("done") == 0 and b.get("bytes") == 3 and b.get("progress") == 0.5
               for b in beats)


# --------------------------------------------------------------- drive-copy

def test_a_drive_copy_reads_a_local_drive_by_serial_and_writes_the_pool(tmp_path):
    w = World(tmp_path)
    w.write(w.drive, "shoot/a.mov", b"hello")
    job = {"id": 31, "kind": "drive-copy", "inputs": {"copies": [
        {"src": {"root": f"local:{w.drive_serial}", "rel": "shoot/a.mov"},
         "dst": pool_ref("Footage/D/a.mov"), "size": 5}],
        "folders": [pool_ref("Footage/D")]}}
    _, res = run_job(w, job)
    assert res["ok"] is True
    assert res["result"]["copied"][0]["src"] == {
        "root": f"local:{w.drive_serial}", "rel": "shoot/a.mov"}
    assert (w.pool / "Footage/D/a.mov").read_bytes() == b"hello"


def test_a_drive_copy_can_go_back_to_a_local_drive(tmp_path):
    w = World(tmp_path)
    w.write(w.pool, "Footage/D/a.mov", b"hello")
    job = {"id": 32, "kind": "drive-copy", "inputs": {"copies": [
        {"src": pool_ref("Footage/D/a.mov"),
         "dst": {"root": f"local:{w.drive_serial}", "rel": "restore/a.mov"}, "size": 5}],
        "folders": [{"root": f"local:{w.drive_serial}", "rel": "restore"}]}}
    _, res = run_job(w, job)
    assert res["ok"] is True
    assert (w.drive / "restore/a.mov").read_bytes() == b"hello"


def test_a_drive_copy_with_bare_sources_reads_them_from_src_root(tmp_path):
    w = World(tmp_path)
    w.write(w.drive, "a.mov", b"hello")
    job = {"id": 33, "kind": "drive-copy", "inputs": {
        "src_root": f"local:{w.drive_serial}",
        "copies": [{"src": "a.mov", "dst": pool_ref("Footage/D/a.mov"), "size": 5}]}}
    _, res = run_job(w, job)
    assert res["ok"] is True and (w.pool / "Footage/D/a.mov").exists()


def test_a_drive_that_is_not_here_fails_the_drive_copy_retryably(tmp_path):
    w = World(tmp_path)
    job = {"id": 34, "kind": "drive-copy", "inputs": {"copies": [
        {"src": {"root": "local:NOPE0000", "rel": "a.mov"},
         "dst": pool_ref("Footage/D/a.mov"), "size": 5}]}}
    _, res = run_job(w, job)
    assert res["ok"] is False and res["retryable"] is True


# -------------------------------------------- the copy list and the receipt

def test_the_job_row_is_small_and_the_receipt_goes_to_the_sorter(tmp_path):
    w = World(tmp_path)
    w.write(w.card, "a.MP4", b"12345")
    w.write(w.card, "b.MP4", b"bb")
    w.write(w.pool, "Footage/Day1/b.MP4", b"bb")
    dash, res = run_job(w, card_job([copy_item("a.MP4", "Footage/Day1/a.MP4", 5),
                                     copy_item("b.MP4", "Footage/Day1/b.MP4", 2, "c2")]))
    small = res["small"]
    assert {k: small[k] for k in ("copied", "skipped", "conflicts", "failed", "receipt")} == {
        "copied": 1, "skipped": 1, "conflicts": 0, "failed": 0, "receipt": True}
    assert res["ok"] is True
    fetch = [c for c in dash.sorter_calls if c[0] == "GET"][0]
    assert fetch[1] == "http://dash.example/sorter/agent/ingest/21"
    assert fetch[3]["X-CCSync-Token"] == "tok" and fetch[3]["X-CCSync-Identity"] == "ident"
    post = [c for c in dash.sorter_calls if c[0] == "POST"][0]
    assert post[1] == "http://dash.example/sorter/agent/ingest/21/receipt"
    assert post[3]["X-CCSync-Token"] == "tok"
    assert set(post[2]) == {"copied", "skipped", "conflicts", "failed", "copier"}
    assert post[2]["copier"] == "python"
    assert small["copier"] == "python"


@pytest.mark.parametrize("status,retryable", [(404, False), (409, False), (500, True)])
def test_a_copy_list_that_cannot_be_had_fails_the_job(tmp_path, status, retryable):
    w = World(tmp_path)
    dash = IngestDash(card_job([copy_item("a.MP4", "Footage/Day1/a.MP4", 5)]))
    dash.plan_status = status
    r = runner(w, dash)
    r.note_report_reply({"commands": {"jobs": {"offered": [21]}}})
    r.tick()
    res = dash.results[-1]
    assert res["ok"] is False and res["retryable"] is retryable
    assert not (w.pool / "Footage").exists()


def test_the_receipt_is_retried_on_a_network_error(tmp_path, monkeypatch):
    monkeypatch.setattr(runner_mod, "RECEIPT_RETRY_SECONDS", 0)
    w = World(tmp_path)
    w.write(w.card, "a.MP4", b"12345")
    dash = IngestDash(card_job([copy_item("a.MP4", "Footage/Day1/a.MP4", 5)]))
    dash.receipt_statuses = ["boom", 503]
    r = runner(w, dash)
    r.note_report_reply({"commands": {"jobs": {"offered": [21]}}})
    r.tick()
    assert len(dash.receipts) == 1
    assert dash.results[-1]["ok"] is True and dash.results[-1]["result"]["receipt"] is True


def test_a_receipt_that_never_lands_fails_the_job_retryably(tmp_path, monkeypatch):
    monkeypatch.setattr(runner_mod, "RECEIPT_RETRY_SECONDS", 0)
    w = World(tmp_path)
    w.write(w.card, "a.MP4", b"12345")
    dash = IngestDash(card_job([copy_item("a.MP4", "Footage/Day1/a.MP4", 5)]))
    dash.receipt_statuses = ["boom"] * runner_mod.RECEIPT_TRIES
    r = runner(w, dash)
    r.note_report_reply({"commands": {"jobs": {"offered": [21]}}})
    r.tick()
    res = dash.results[-1]
    assert res["ok"] is False and res["retryable"] is True
    assert res["result"]["receipt"] is False
    assert (w.pool / "Footage/Day1/a.MP4").read_bytes() == b"12345"


@pytest.mark.parametrize("rel", ["DCIM/E:/Projects/evil.MP4", "DCIM/D:x.MP4", "DCIM/C:/Windows/x", "a/b.MP4:stream",
                                 "../x", "a/../../x", "/abs/x", "C:/x"])
def test_under_refuses_drives_streams_and_climbs(tmp_path, rel):
    with pytest.raises(card_copy.job_paths.JobPathError):
        card_copy._under(tmp_path, rel)


def test_under_keeps_an_ordinary_card_path(tmp_path):
    assert card_copy._under(tmp_path, "PRIVATE\\M4ROOT/CLIP/C0001.MP4") == tmp_path / "PRIVATE" / "M4ROOT" / "CLIP" / "C0001.MP4"


# ============================================================ write modes (Python copier)

def with_mode(item, mode):
    return {**item, "mode": mode}


def test_a_collision_is_written_beside_the_existing_file_under_a_renamed_name(tmp_path):
    w = World(tmp_path)
    data = os.urandom(MIB + 5)
    w.write(w.card, "a.MP4", data)
    existing = w.write(w.pool, "Footage/Day1/a.MP4", b"another clip")
    old = existing.stat().st_mtime_ns
    _, res = run_job(w, card_job([with_mode(copy_item("a.MP4", "Footage/Day1/a.MP4", len(data)), "collision")]))
    result = res["result"]
    assert res["ok"] is True and result["conflicts"] == [] and result["failed"] == []
    assert existing.read_bytes() == b"another clip" and existing.stat().st_mtime_ns == old
    assert (w.pool / "Footage/Day1/a (2).MP4").read_bytes() == data
    # the receipt echoes the PLANNED dst and carries the name actually written
    assert result["copied"] == [{"src": "a.MP4", "dst": pool_ref("Footage/Day1/a.MP4"),
                                 "size": len(data), "verified": True, "filename": "a (2).MP4"}]
    assert not partials(w.pool)


def test_a_collision_skips_to_the_next_free_name(tmp_path):
    w = World(tmp_path)
    w.write(w.card, "a.MP4", b"12345")
    w.write(w.pool, "Footage/Day1/a.MP4", b"one")
    w.write(w.pool, "Footage/Day1/a (2).MP4", b"another one")
    _, res = run_job(w, card_job([with_mode(copy_item("a.MP4", "Footage/Day1/a.MP4", 5), "collision")]))
    assert res["result"]["copied"][0]["filename"] == "a (3).MP4"
    assert (w.pool / "Footage/Day1/a (3).MP4").read_bytes() == b"12345"


def test_a_collision_run_again_finds_its_earlier_renamed_copy(tmp_path):
    w = World(tmp_path)
    w.write(w.card, "a.MP4", b"12345")
    w.write(w.pool, "Footage/Day1/a.MP4", b"other")
    w.write(w.pool, "Footage/Day1/a (2).MP4", b"12345")       # an interrupted run already made it
    _, res = run_job(w, card_job([with_mode(copy_item("a.MP4", "Footage/Day1/a.MP4", 5), "collision")]))
    result = res["result"]
    assert result["copied"] == [] and not (w.pool / "Footage/Day1/a (3).MP4").exists()
    assert result["skipped"] == [{"src": "a.MP4", "dst": pool_ref("Footage/Day1/a.MP4"), "size": 5,
                                  "verified": True, "filename": "a (2).MP4"}]


def test_a_collision_with_nothing_there_is_an_ordinary_copy(tmp_path):
    w = World(tmp_path)
    w.write(w.card, "a.MP4", b"12345")
    _, res = run_job(w, card_job([with_mode(copy_item("a.MP4", "Footage/Day1/a.MP4", 5), "collision")]))
    assert res["result"]["copied"][0]["filename"] == "a.MP4"


def test_a_resume_appends_to_the_partial_and_verifies_the_whole_file(tmp_path):
    w = World(tmp_path)
    data = os.urandom(3 * MIB + 17)
    w.write(w.card, "a.MP4", data)
    have = MIB + 5
    part = w.write(w.pool, "Footage/Day1/a.MP4", data[:have])
    _, res = run_job(w, card_job([with_mode(copy_item("a.MP4", "Footage/Day1/a.MP4", len(data)), "resume")]))
    result = res["result"]
    assert result["copied"] == [{"src": "a.MP4", "dst": pool_ref("Footage/Day1/a.MP4"),
                                 "size": len(data), "verified": True, "filename": "a.MP4"}]
    assert part.read_bytes() == data and not partials(w.pool)


def test_a_resume_of_a_file_that_is_not_the_start_is_a_conflict_and_left_alone(tmp_path):
    w = World(tmp_path)
    data = os.urandom(2 * MIB)
    w.write(w.card, "a.MP4", data)
    other = os.urandom(MIB)
    part = w.write(w.pool, "Footage/Day1/a.MP4", other)
    _, res = run_job(w, card_job([with_mode(copy_item("a.MP4", "Footage/Day1/a.MP4", len(data)), "resume")]))
    assert len(res["result"]["conflicts"]) == 1 and res["result"]["copied"] == []
    assert part.read_bytes() == other


def test_a_resume_with_a_destination_larger_than_the_source_is_a_conflict(tmp_path):
    w = World(tmp_path)
    w.write(w.card, "a.MP4", b"123")
    part = w.write(w.pool, "Footage/Day1/a.MP4", b"123456")
    _, res = run_job(w, card_job([with_mode(copy_item("a.MP4", "Footage/Day1/a.MP4", 3), "resume")]))
    assert len(res["result"]["conflicts"]) == 1 and part.read_bytes() == b"123456"


def test_a_resume_with_no_partial_there_is_an_ordinary_copy(tmp_path):
    w = World(tmp_path)
    w.write(w.card, "a.MP4", b"12345")
    _, res = run_job(w, card_job([with_mode(copy_item("a.MP4", "Footage/Day1/a.MP4", 5), "resume")]))
    assert len(res["result"]["copied"]) == 1
    assert (w.pool / "Footage/Day1/a.MP4").read_bytes() == b"12345"


def test_a_resume_that_fails_its_verify_leaves_the_short_file_as_it_was(tmp_path, monkeypatch):
    w = World(tmp_path)
    data = os.urandom(2 * MIB)
    w.write(w.card, "a.MP4", data)
    part = w.write(w.pool, "Footage/Day1/a.MP4", data[:MIB])
    monkeypatch.setattr(card_copy, "verify_whole", lambda *a, **k: "the copy read back differs from the source")
    _, res = run_job(w, card_job([with_mode(copy_item("a.MP4", "Footage/Day1/a.MP4", len(data)), "resume")]))
    assert res["result"]["failed"][0]["why"].startswith("verify failed")
    assert part.read_bytes() == data[:MIB] and not partials(w.pool)


def test_a_halt_during_a_resume_leaves_the_short_file_alone_and_no_full_length_file(tmp_path, monkeypatch):
    w = World(tmp_path)
    monkeypatch.setattr(card_copy, "BUFFER_BYTES", 1024)
    data = os.urandom(64 * 1024)
    w.write(w.card, "a.MP4", data)
    part = w.write(w.pool, "Footage/Day1/a.MP4", data[:4096])
    halted = {"now": False}
    real = card_copy.resume_file

    def resume_then_halt(src, dst, size, have, should_stop, on_bytes):
        n = {"n": 0}

        def stop():
            n["n"] += 1
            if n["n"] == 12:
                halted["now"] = True
            return should_stop()

        return real(src, dst, size, have, stop, on_bytes)

    monkeypatch.setattr(card_copy, "resume_file", resume_then_halt)
    dash = IngestDash(card_job([with_mode(copy_item("a.MP4", "Footage/Day1/a.MP4", len(data)), "resume")]))
    r = runner(w, dash, halted=lambda: halted["now"])
    r.note_report_reply({"commands": {"jobs": {"offered": [21]}}})
    r.tick()
    assert final(dash)["ok"] is False
    assert part.read_bytes() == data[:4096]                  # untouched: never a full-length unverified file
    assert not partials(w.pool)


def test_an_unknown_mode_fails_the_item_and_writes_nothing(tmp_path):
    w = World(tmp_path)
    w.write(w.card, "a.MP4", b"12345")
    _, res = run_job(w, card_job([with_mode(copy_item("a.MP4", "Footage/Day1/a.MP4", 5), "overwrite")]))
    assert "overwrite" in res["result"]["failed"][0]["why"]
    assert not (w.pool / "Footage/Day1/a.MP4").exists()


# ============================================ a job that stops early posts what landed

def test_a_halted_job_posts_its_receipt_not_final_and_fails_retryably(tmp_path):
    w = World(tmp_path)
    w.write(w.card, "a.MP4", b"aaa")
    w.write(w.card, "b.MP4", b"bbb")
    dash = IngestDash(card_job([copy_item("a.MP4", "Footage/Day1/a.MP4", 3),
                                copy_item("b.MP4", "Footage/Day1/b.MP4", 3, "c2")]))
    r = runner(w, dash, halted=lambda: (w.pool / "Footage/Day1/a.MP4").exists())
    r.note_report_reply({"commands": {"jobs": {"offered": [21]}}})
    r.tick()
    res = final(dash)
    assert res["ok"] is False and res["retryable"] is True
    assert dash.receipts[-1]["final"] is False and dash.receipts[-1]["copier"] == "python"
    assert [c["src"] for c in dash.receipts[-1]["copied"]] == ["a.MP4"]


def test_the_retry_after_a_halt_reports_the_landed_file_as_skipped_and_verified(tmp_path):
    w = World(tmp_path)
    w.write(w.card, "a.MP4", b"aaa")
    w.write(w.card, "b.MP4", b"bbb")
    copies = [copy_item("a.MP4", "Footage/Day1/a.MP4", 3), copy_item("b.MP4", "Footage/Day1/b.MP4", 3, "c2")]
    dash = IngestDash(card_job(copies))
    r = runner(w, dash, halted=lambda: (w.pool / "Footage/Day1/a.MP4").exists())
    r.note_report_reply({"commands": {"jobs": {"offered": [21]}}})
    r.tick()
    retry_dash, res = run_job(w, card_job(copies))      # the retry: the same list, nothing halted
    result = res["result"]
    assert [s["src"] for s in result["skipped"]] == ["a.MP4"] and result["skipped"][0]["verified"] is True
    assert [c["src"] for c in result["copied"]] == ["b.MP4"]
    assert "final" not in retry_dash.receipts[-1]


def test_a_finished_job_posts_no_final_flag(tmp_path):
    w = World(tmp_path)
    w.write(w.card, "a.MP4", b"aaa")
    dash, res = run_job(w, card_job([copy_item("a.MP4", "Footage/Day1/a.MP4", 3)]))
    assert "final" not in dash.receipts[-1]


def test_a_card_pulled_mid_copy_stops_the_job_and_posts_what_landed(tmp_path, monkeypatch):
    w = World(tmp_path)
    w.write(w.card, "a.MP4", b"aaa")
    w.write(w.card, "b.MP4", b"bbb")
    w.write(w.card, "c.MP4", b"ccc")
    real = card_copy.copy_file

    def pull_the_card(src, dst, size, should_stop, on_bytes):
        if src.name == "b.MP4":
            w.card_serial = None                         # out of the reader
            raise OSError(22, "The device is not ready")
        return real(src, dst, size, should_stop, on_bytes)

    monkeypatch.setattr(card_copy, "copy_file", pull_the_card)
    job = card_job([copy_item(n, f"Footage/Day1/{n}", 3, n) for n in ("a.MP4", "b.MP4", "c.MP4")])
    dash = IngestDash(job)
    r = runner(w, dash)
    r.note_report_reply({"commands": {"jobs": {"offered": [21]}}})
    r.tick()
    res = final(dash)
    assert res["ok"] is False and res["retryable"] is True and "taken out" in res["error"]
    body = dash.receipts[-1]
    assert body["final"] is False and [c["src"] for c in body["copied"]] == ["a.MP4"]
    assert body["failed"] == []                           # not three failures: one stop
    assert not (w.pool / "Footage/Day1/c.MP4").exists()


# ====================================================== the TeraCopy copier (fake TeraCopy)

class FakeTeraCopy:
    """Stands in for teracopy.TeraCopy: copies with shutil and answers like the
    history database would, so the whole CardJob path runs without TeraCopy."""

    def __init__(self, result=3, halt=None):
        self.calls: list[tuple[list[str], str, str]] = []
        self.result = result
        self.halt = halt

    def copy_group(self, files, dest, switch, tag="", on_tick=None, expect_verify=True, should_stop=None):
        import shutil
        self.calls.append((list(files), dest, switch))
        self.should_stop = should_stop
        receipts = []
        for f in files:
            target = Path(dest) / Path(f).name
            filename = None
            if target.exists() and switch == "/RenameCopied":
                n = 2
                while card_copy.renamed(target, n).exists():
                    n += 1
                target = card_copy.renamed(target, n)
                filename = target.name
            shutil.copy2(f, target)
            receipts.append({"source": f, "size": target.stat().st_size, "is_folder": False,
                             "result": self.result, "verified": self.result == 3, "hash": "AA",
                             "filename": filename, "message": None})
        if on_tick:
            on_tick({"state": "done"}, 1)
        if self.halt:
            self.halt()
        return {"code": 0 if self.result == 3 else 10, "status": {}, "receipts": receipts,
                "list_file": "x.txt", "since": 1}


windows_only = pytest.mark.skipif(os.name != "nt", reason="TeraCopy is Windows-only")


@pytest.fixture()
def fake_tc(monkeypatch):
    from ccsync_companion import teracopy as teracopy_mod
    box = {"tc": FakeTeraCopy()}
    monkeypatch.setattr(teracopy_mod, "detect", lambda cfg=None: (box["tc"], ""))
    return box


@windows_only
def test_teracopy_copies_when_it_is_available_and_the_receipt_says_so(tmp_path, fake_tc):
    w = World(tmp_path)
    data = os.urandom(MIB + 3)
    w.write(w.card, "a.MP4", data)
    w.write(w.card, "b.MP4", b"bee")
    _, res = run_job(w, card_job([copy_item("a.MP4", "Footage/Day1/a.MP4", len(data)),
                                  copy_item("b.MP4", "Footage/Day1/Proxy/b.MP4", 3, "c2")],
                                 folders=[pool_ref("Footage/Day1"), pool_ref("Footage/Day1/Proxy")]))
    result = res["result"]
    assert result["copier"] == "teracopy" and res["small"]["copier"] == "teracopy"
    assert [c["verified"] for c in result["copied"]] == [True, True]
    assert (w.pool / "Footage/Day1/a.MP4").read_bytes() == data
    calls = fake_tc["tc"].calls
    assert [(Path(d).name, sw) for _, d, sw in calls] == [("Day1", "/SkipAll"),
                                                         ("Proxy", "/SkipAll")]


@windows_only
def test_one_teracopy_job_per_folder_and_switch_with_modes_mapped(tmp_path, fake_tc):
    w = World(tmp_path)
    for n in "abcd":
        w.write(w.card, f"{n}.MP4", n.encode() * 4)
    w.write(w.pool, "Footage/Day1/c.MP4", b"zz")                 # collides with c
    w.write(w.pool, "Footage/Day1/d.MP4", b"dd")                 # a partial of d
    job = card_job([copy_item("a.MP4", "Footage/Day1/a.MP4", 4, "1"),
                    copy_item("b.MP4", "Footage/Day1/b.MP4", 4, "1"),
                    with_mode(copy_item("c.MP4", "Footage/Day1/c.MP4", 4, "2"), "collision"),
                    with_mode(copy_item("d.MP4", "Footage/Day1/d.MP4", 4, "3"), "resume")])
    _, res = run_job(w, job)
    calls = fake_tc["tc"].calls
    by_switch = {sw: [Path(f).name for f in files] for files, _, sw in calls}
    assert by_switch == {"/SkipAll": ["a.MP4", "b.MP4"], "/OverwriteDiffSize": ["d.MP4"],
                         "/RenameCopied": ["c.MP4"]}
    assert [sw for _, _, sw in calls] == ["/SkipAll", "/OverwriteDiffSize", "/RenameCopied"]   # copies first
    assert len(calls) == 3
    got = {c["src"]: c["filename"] for c in res["result"]["copied"]}
    assert got == {"a.MP4": "a.MP4", "b.MP4": "b.MP4", "c.MP4": "c (2).MP4", "d.MP4": "d.MP4"}
    assert (w.pool / "Footage/Day1/c.MP4").read_bytes() == b"zz"        # never over the existing


@windows_only
def test_what_cannot_be_copied_never_reaches_teracopy(tmp_path, fake_tc):
    w = World(tmp_path)
    w.write(w.card, "same.MP4", b"12345")
    w.write(w.card, "diff.MP4", b"12345")
    w.write(w.card, "new.MP4", b"12345")
    w.write(w.pool, "Footage/Day1/same.MP4", b"12345")           # identical: skipped by a real compare
    w.write(w.pool, "Footage/Day1/diff.MP4", b"abcde")           # same size, other bytes: a conflict
    _, res = run_job(w, card_job([copy_item(n, f"Footage/Day1/{n}", 5, n)
                                  for n in ("same.MP4", "diff.MP4", "new.MP4")]))
    result = res["result"]
    assert [Path(f).name for files, _, _ in fake_tc["tc"].calls for f in files] == ["new.MP4"]
    assert [s["src"] for s in result["skipped"]] == ["same.MP4"] and result["skipped"][0]["verified"] is True
    assert [c["src"] for c in result["conflicts"]] == ["diff.MP4"]
    assert (w.pool / "Footage/Day1/diff.MP4").read_bytes() == b"abcde"


@windows_only
def test_a_partial_that_is_not_the_start_is_not_handed_to_teracopy_to_rewrite(tmp_path, fake_tc):
    w = World(tmp_path)
    w.write(w.card, "a.MP4", os.urandom(2 * MIB))
    other = w.write(w.pool, "Footage/Day1/a.MP4", os.urandom(MIB))
    _, res = run_job(w, card_job([with_mode(copy_item("a.MP4", "Footage/Day1/a.MP4", 2 * MIB), "resume")]))
    assert fake_tc["tc"].calls == [] and len(res["result"]["conflicts"]) == 1
    assert other.stat().st_size == MIB


@windows_only
def test_a_copy_teracopy_did_not_verify_is_reported_unverified(tmp_path, fake_tc):
    fake_tc["tc"] = FakeTeraCopy(result=1)
    w = World(tmp_path)
    w.write(w.card, "a.MP4", b"12345")
    _, res = run_job(w, card_job([copy_item("a.MP4", "Footage/Day1/a.MP4", 5)]))
    assert res["result"]["copied"][0]["verified"] is False
    assert res["result"]["failed"] == []


@windows_only
def test_a_file_teracopy_left_short_is_failed_not_copied(tmp_path, fake_tc):
    class Short(FakeTeraCopy):
        def copy_group(self, files, dest, *a, **k):
            out = super().copy_group(files, dest, *a, **k)
            (Path(dest) / Path(files[0]).name).write_bytes(b"12")     # cut short after the "verify"
            return out

    fake_tc["tc"] = Short()
    w = World(tmp_path)
    w.write(w.card, "a.MP4", b"12345")
    _, res = run_job(w, card_job([copy_item("a.MP4", "Footage/Day1/a.MP4", 5)]))
    assert res["result"]["copied"] == [] and "verified but" in res["result"]["failed"][0]["why"]


@windows_only
def test_a_halt_between_teracopy_jobs_launches_no_more_and_posts_not_final(tmp_path, fake_tc):
    w = World(tmp_path)
    w.write(w.card, "a.MP4", b"aaa")
    w.write(w.card, "b.MP4", b"bbb")
    state = {"halt": False}
    fake_tc["tc"] = FakeTeraCopy(halt=lambda: state.update(halt=True))
    dash = IngestDash(card_job([copy_item("a.MP4", "Footage/Day1/a.MP4", 3),
                                copy_item("b.MP4", "Footage/Day1/Proxy/b.MP4", 3, "c2")],
                               folders=[pool_ref("Footage/Day1"), pool_ref("Footage/Day1/Proxy")]))
    r = runner(w, dash, halted=lambda: state["halt"])
    r.note_report_reply({"commands": {"jobs": {"offered": [21]}}})
    r.tick()
    res = final(dash)
    assert res["ok"] is False and res["retryable"] is True
    assert len(fake_tc["tc"].calls) == 1                       # the second folder's job was never launched
    body = dash.receipts[-1]
    assert body["final"] is False and body["copier"] == "teracopy"
    assert [c["src"] for c in body["copied"]] == ["a.MP4"]


@windows_only
def test_a_file_that_appears_before_its_group_launches_is_a_conflict_not_overwritten(tmp_path, fake_tc):
    w = World(tmp_path)
    w.write(w.card, "a.MP4", b"aaa")
    w.write(w.card, "b.MP4", b"bbbb")

    class Racing(FakeTeraCopy):
        def copy_group(self, files, dest, *a, **k):
            out = super().copy_group(files, dest, *a, **k)
            if len(self.calls) == 1:         # another machine lands its own proxy meanwhile
                w.write(w.pool, "Footage/Day1/Proxy/b.MP4", b"OTHER")
            return out

    fake_tc["tc"] = Racing()
    _, res = run_job(w, card_job([copy_item("a.MP4", "Footage/Day1/a.MP4", 3),
                                  copy_item("b.MP4", "Footage/Day1/Proxy/b.MP4", 4, "c2")],
                                 folders=[pool_ref("Footage/Day1"), pool_ref("Footage/Day1/Proxy")]))
    assert len(fake_tc["tc"].calls) == 1
    assert [c["src"] for c in res["result"]["conflicts"]] == ["b.MP4"]
    assert (w.pool / "Footage/Day1/Proxy/b.MP4").read_bytes() == b"OTHER"


@windows_only
def test_two_plain_copies_to_one_name_in_a_group_the_later_is_a_conflict(tmp_path, fake_tc):
    w = World(tmp_path)
    w.write(w.card, "100/DSC1.JPG", b"1" * 3)
    w.write(w.card, "101/DSC1.JPG", b"2" * 4)
    _, res = run_job(w, card_job([copy_item("100/DSC1.JPG", "F/DSC1.JPG", 3, "c1"),
                                  copy_item("101/DSC1.JPG", "F/dsc1.jpg", 4, "c2")],
                                 folders=[pool_ref("F")]))
    assert [c["src"] for c in res["result"]["copied"]] == ["100/DSC1.JPG"]
    assert [c["src"] for c in res["result"]["conflicts"]] == ["101/DSC1.JPG"]
    assert [Path(f).name for f in fake_tc["tc"].calls[0][0]] == ["DSC1.JPG"]


@windows_only
def test_a_stop_during_the_teracopy_wait_posts_only_verified_files_and_not_final(tmp_path, fake_tc):
    w = World(tmp_path)
    w.write(w.card, "a.MP4", b"aaa")
    w.write(w.card, "b.MP4", b"bbb")

    class Stopped(FakeTeraCopy):
        def copy_group(self, files, dest, *a, **k):
            out = super().copy_group(files, dest, *a, **k)
            out["receipts"][1].update(verified=False, result=1, landed=False)
            out.update(code=13, stopped="a fleet halt stopped this job")
            return out

    fake_tc["tc"] = Stopped()
    dash = IngestDash(card_job([copy_item("a.MP4", "Footage/Day1/a.MP4", 3),
                                copy_item("b.MP4", "Footage/Day1/b.MP4", 3, "c2")],
                               folders=[pool_ref("Footage/Day1")]))
    r = runner(w, dash)
    r.note_report_reply({"commands": {"jobs": {"offered": [21]}}})
    r.tick()
    body = dash.receipts[-1]
    assert body["final"] is False
    assert [c["src"] for c in body["copied"]] == ["a.MP4"] and body["failed"] == []
    assert final(dash)["ok"] is False


def test_a_resume_stopped_after_appending_leaves_no_full_length_file(tmp_path, monkeypatch):
    monkeypatch.setattr(card_copy, "BUFFER_BYTES", 1024)
    data = os.urandom(8 * 1024)
    src, dst = tmp_path / "s.bin", tmp_path / "d.bin"
    src.write_bytes(data)
    dst.write_bytes(data[:2048])
    n = {"n": 0}

    def stop():                      # let the prefix check and the whole append through, stop in the read-back
        n["n"] += 1
        return "halt" if n["n"] > 2 + 6 + 1 else ""

    with pytest.raises(card_copy._Stopped):
        card_copy.resume_file(src, dst, len(data), 2048, stop, lambda k: None)
    assert dst.read_bytes() == data[:2048] and not partials(tmp_path)
    assert card_copy.resume_file(src, dst, len(data), 2048, lambda: "", lambda k: None) == ""
    assert dst.read_bytes() == data and not partials(tmp_path)


@windows_only
def test_a_file_whose_name_changes_goes_to_the_python_copier(tmp_path, fake_tc):
    w = World(tmp_path)
    w.write(w.card, "a.MP4", b"12345")
    _, res = run_job(w, card_job([copy_item("a.MP4", "Footage/Day1/renamed.MP4", 5)]))
    assert fake_tc["tc"].calls == []
    assert res["result"]["copier"] == "python" and len(res["result"]["copied"]) == 1


@windows_only
def test_a_teracopy_that_cannot_run_fails_its_files_not_the_job(tmp_path, fake_tc):
    class Broken(FakeTeraCopy):
        def copy_group(self, *a, **k):
            raise ValueError("teracopy: unusable path (empty, or contains a quote)")

    fake_tc["tc"] = Broken()
    w = World(tmp_path)
    w.write(w.card, "a.MP4", b"12345")
    _, res = run_job(w, card_job([copy_item("a.MP4", "Footage/Day1/a.MP4", 5)]))
    assert res["ok"] is True and "could not be run" in res["result"]["failed"][0]["why"]


def test_the_python_copier_is_used_when_there_is_no_teracopy(tmp_path):
    w = World(tmp_path)
    w.write(w.card, "a.MP4", b"12345")
    _, res = run_job(w, card_job([copy_item("a.MP4", "Footage/Day1/a.MP4", 5)]))
    assert res["result"]["copier"] == "python"


# ================================================== live progress and speed to the sorter

def test_the_poster_reports_bytes_files_current_phase_and_speed_over_the_window():
    prog = card_copy.Progress(of=4, total_bytes=1000)
    prog.copier = "teracopy"
    t = {"now": 100.0}
    poster = card_copy.ProgressPoster(prog, lambda: t["now"])
    assert poster.body()["bps"] == 0                       # one sample: no speed yet
    t["now"], prog.bytes, prog.done, prog.current = 102.0, 400, 1, "A/b.MP4"
    body = poster.body()
    assert body == {"bytesDone": 400, "bytesTotal": 1000, "filesDone": 1, "filesTotal": 4,
                    "current": "A/b.MP4", "bps": 200, "phase": "copy", "copier": "teracopy"}
    t["now"], prog.bytes = 110.0, 400                      # stalled for 8 s: the old samples age out
    poster.body()
    t["now"] = 112.0
    assert poster.body()["bps"] == 0
    prog.phase = "verify"
    t["now"], prog.bytes = 114.0, 900
    assert poster.body()["bps"] == 0                       # no speed claimed for a read-back


def test_a_progress_post_that_fails_is_dropped_not_raised(tmp_path):
    w = World(tmp_path)

    class Down(IngestDash):
        def request(self, method, url, body, headers, timeout):
            if url.endswith("/progress"):
                raise OSError("network down")
            return super().request(method, url, body, headers, timeout)

    r = runner(w, Down())
    assert r._post_progress(21, {"bytesDone": 1}) is False


def test_a_copy_posts_progress_while_it_runs_and_a_refused_post_does_not_fail_it(tmp_path, monkeypatch):
    import time as _t
    w = World(tmp_path)
    w.write(w.card, "a.MP4", b"aaa")
    monkeypatch.setattr(runner_mod, "PROGRESS_SECONDS", 0.01)
    real = card_copy.copy_file

    def slow(*a, **k):
        _t.sleep(0.15)
        return real(*a, **k)

    monkeypatch.setattr(card_copy, "copy_file", slow)

    class Refuses(IngestDash):
        def request(self, method, url, body, headers, timeout):
            if url.endswith("/progress"):
                self.sorter_calls.append((method, url, body, headers))
                return 409, {"detail": "no"}
            return super().request(method, url, body, headers, timeout)

    dash = Refuses(card_job([copy_item("a.MP4", "Footage/Day1/a.MP4", 3)]))
    r = runner(w, dash)
    r.note_report_reply({"commands": {"jobs": {"offered": [21]}}})
    r.tick()
    assert final(dash)["ok"] is True
    posts = [c for c in dash.sorter_calls if c[1].endswith("/ingest/21/progress")]
    assert posts and posts[0][0] == "POST" and posts[0][2]["bytesTotal"] == 3
    assert posts[0][2]["copier"] == "python" and posts[0][3]["X-CCSync-Token"] == "tok"
