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
        "size": len(data), "verified": True}
    assert result["skipped"] == result["conflicts"] == result["failed"] == []
    assert not partials(w.pool)
    # the copy keeps the card file's modification time
    assert (os.stat(w.pool / "Footage/Day1/a.MP4").st_mtime_ns
            == os.stat(w.card / "PRIVATE/M4ROOT/CLIP/a.MP4").st_mtime_ns)


def test_a_same_size_destination_is_skipped_and_untouched(tmp_path):
    w = World(tmp_path)
    w.write(w.card, "a.MP4", b"12345")
    existing = w.write(w.pool, "Footage/Day1/a.MP4", b"abcde")     # same size, other bytes
    old = existing.stat().st_mtime_ns
    _, res = run_job(w, card_job([copy_item("a.MP4", "Footage/Day1/a.MP4", 5)]))
    result = res["result"]
    assert res["ok"] is True
    assert [s["src"] for s in result["skipped"]] == ["a.MP4"]
    assert result["copied"] == [] and result["conflicts"] == []
    assert existing.read_bytes() == b"abcde" and existing.stat().st_mtime_ns == old


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

def test_quick_verify_catches_a_difference_in_the_last_megabyte(tmp_path):
    a, b = tmp_path / "a", tmp_path / "b"
    data = bytearray(os.urandom(5 * MIB))
    a.write_bytes(bytes(data))
    assert card_copy.quick_verify(a, a, len(data)) == ""
    data[-10] ^= 0xFF
    b.write_bytes(bytes(data))
    assert "last megabyte" in card_copy.quick_verify(a, b, len(data))
    data[-10] ^= 0xFF
    data[5] ^= 0xFF
    b.write_bytes(bytes(data))
    assert "first megabyte" in card_copy.quick_verify(a, b, len(data))
    b.write_bytes(bytes(data)[:-1])
    assert "bytes" in card_copy.quick_verify(a, b, len(data))


def test_a_verify_mismatch_is_reported_failed_and_nothing_is_left(tmp_path, monkeypatch):
    w = World(tmp_path)
    w.write(w.card, "a.MP4", b"12345")
    monkeypatch.setattr(card_copy, "quick_verify",
                        lambda *a, **k: "the last megabyte differs from the source")
    _, res = run_job(w, card_job([copy_item("a.MP4", "Footage/Day1/a.MP4", 5)]))
    failed = res["result"]["failed"]
    assert failed == [{"src": "a.MP4", "dst": pool_ref("Footage/Day1/a.MP4"),
                       "why": "verify failed: the last megabyte differs from the source"}]
    assert res["result"]["copied"] == []
    assert not (w.pool / "Footage/Day1/a.MP4").exists()
    assert not partials(w.pool)


def test_a_file_that_appears_mid_copy_is_not_overwritten(tmp_path, monkeypatch):
    w = World(tmp_path)
    w.write(w.card, "a.MP4", b"12345")
    real = card_copy.quick_verify

    def verify(src, dst, size):
        # somebody else puts a file in place while ours is still a .partial
        w.write(w.pool, "Footage/Day1/a.MP4", b"theirs!")
        return real(src, dst, size)

    monkeypatch.setattr(card_copy, "quick_verify", verify)
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
    state = {"calls": 0}

    def halted():
        state["calls"] += 1
        return state["calls"] > 4               # after the first file's checks

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
    w.write(w.pool, "Footage/Day1/b.MP4", b"zz")
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
    assert set(post[2]) == {"copied", "skipped", "conflicts", "failed"}


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
