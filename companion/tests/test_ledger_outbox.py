"""The ledger outbox: copies made while the dashboard could not be reached, sent when it can be.

footage-sorter docs/LEDGER-BROWSER-DESIGN.md, "The companion" item 4. Part D's field page writes here too, so
this pins the module API: append(), pending(), peek(), flush(), OutboxFlusher.
"""
from __future__ import annotations

import json
import threading
import time

import pytest

from ccsync_companion import ledger_outbox as ob


def copy(path="Trip/A001.braw", serial="6880882b", size=100, mtime=1_786_236_852_123, **extra):
    c = {"volume": {"serial": serial, "label": "CIB_D1"}, "path": path, "size": size, "mtime": mtime,
         "verified": "full", "tool": "teracopy", "at": "2026-11-09T10:00:00Z"}
    c.update(extra)
    return c


@pytest.fixture
def box(tmp_path):
    return tmp_path / "state" / "ledger-outbox.jsonl"


class Server:
    def __init__(self, *statuses):
        self.statuses = list(statuses)
        self.got = []

    def __call__(self, copies):
        status = self.statuses.pop(0) if self.statuses else 200
        if status == "boom":
            raise OSError("network down")
        if status == 200:
            self.got.append(copies)
        return status, {"accepted": len(copies), "duplicates": 0}


# ------------------------------------------------------------------ append

def test_append_is_durable_and_normalises(box):
    assert ob.append([copy(path="\\Trip\\A001.braw"), copy(path="b.braw", mtime=None)], box) == 2
    lines = [json.loads(l) for l in box.read_text(encoding="utf-8").splitlines()]
    first = lines[0]["copy"]
    assert first["volume"] == {"serial": "6880882B", "label": "CIB_D1"}      # serial upper-cased
    assert first["path"] == "Trip/A001.braw" and first["name"] == "A001.braw"
    assert lines[1]["copy"]["mtime"] is None and lines[0]["queued"]
    assert ob.pending(box) == 2 and [c["path"] for c in ob.peek(box)] == ["Trip/A001.braw", "b.braw"]


def test_defaults_are_filled_and_junk_is_dropped(box):
    bare = {"volume": {"serial": "AA"}, "path": "x.mov", "size": 5}
    junk = [{"path": "x"}, {"volume": {"serial": ""}, "path": "x", "size": 1}, copy(path="../escape.mov"),
            copy(size=-1), copy(size="big"), "not a dict", None, copy(path="")]
    assert ob.append([bare] + junk, box) == 1
    c = ob.peek(box)[0]
    assert c["tool"] == "companion" and c["verified"] == "full" and c["at"].endswith("Z") and c["mtime"] is None
    assert ob.append([copy(verified="bogus")], box) == 1
    assert ob.peek(box)[1]["verified"] == "listed"


def test_the_same_copy_is_queued_once(box):
    assert ob.append([copy(), copy()], box) == 1
    assert ob.append([copy()], box) == 0
    assert ob.append([copy(mtime=1)], box) == 1                              # another mtime is another copy
    assert ob.pending(box) == 2


def test_a_torn_last_line_is_skipped_not_fatal(box):
    ob.append([copy()], box)
    with open(box, "a", encoding="utf-8") as fh:
        fh.write('{"copy": {"vol')                                           # power cut mid-write
    assert ob.pending(box) == 1
    assert ob.append([copy(path="next.braw")], box) == 1
    assert ob.pending(box) == 2


def test_append_never_raises(tmp_path):
    blocked = tmp_path / "file"
    blocked.write_text("x")
    assert ob.append([copy()], blocked / "inside" / "ledger-outbox.jsonl") == 0


def test_appends_from_several_threads_lose_nothing(box):
    def work(n):
        for i in range(25):
            ob.append([copy(path=f"t{n}/f{i}.mov")], box)

    threads = [threading.Thread(target=work, args=(n,)) for n in range(6)]
    [t.start() for t in threads]
    [t.join() for t in threads]
    assert ob.pending(box) == 150


# ------------------------------------------------------------------ flush

def test_flush_sends_everything_and_empties_the_file(box):
    ob.append([copy(path=f"f{i}.mov") for i in range(7)], box)
    srv = Server()
    out = ob.flush(srv, box, batch=3)
    assert [len(b) for b in srv.got] == [3, 3, 1]
    assert out["sent"] == 7 and out["accepted"] == 7 and out["remaining"] == 0 and out["status"] == 200
    assert not box.exists()
    assert ob.flush(srv, box)["sent"] == 0                                    # nothing waiting: no call
    assert len(srv.got) == 3


@pytest.mark.parametrize("status", ["boom", 503, 404, 500, 403, 401, 429])
def test_flush_keeps_everything_when_the_dashboard_cannot_take_it(box, status):
    ob.append([copy(path="a.mov"), copy(path="b.mov")], box)
    out = ob.flush(Server(status), box)
    assert out["sent"] == 0 and out["remaining"] == 2 and ob.pending(box) == 2


def test_flush_resumes_where_it_stopped(box):
    ob.append([copy(path=f"f{i}.mov") for i in range(4)], box)
    srv = Server(200, 503)
    out = ob.flush(srv, box, batch=2)
    assert out["sent"] == 2 and out["remaining"] == 2
    assert [c["path"] for c in ob.peek(box)] == ["f2.mov", "f3.mov"]
    out = ob.flush(srv, box, batch=2)
    assert out["remaining"] == 0


def test_copies_appended_while_a_post_is_out_are_kept(box):
    ob.append([copy(path="old.mov")], box)

    def send(copies):
        ob.append([copy(path="new.mov")], box)                               # the field page, mid-flush
        return 200, {"accepted": len(copies), "duplicates": 0}

    out = ob.flush(send, box, batch=1)
    assert out["sent"] == 2 and out["remaining"] == 0                        # the loop picked the new one up too


def test_a_batch_the_dashboard_refuses_is_set_aside_not_lost_and_not_blocking(box):
    ob.append([copy(path="bad.mov"), copy(path="good.mov")], box)
    srv = Server(422, 200)
    out = ob.flush(srv, box, batch=1)
    assert out["rejected"] == 1 and out["sent"] == 1 and out["remaining"] == 0
    aside = box.with_name(ob.REJECTED_FILENAME)
    assert [json.loads(l)["copy"]["path"] for l in aside.read_text(encoding="utf-8").splitlines()] == ["bad.mov"]


def test_flush_with_a_cfg_posts_to_the_copies_route_with_the_credentials(box):
    ob.append([copy()], box)
    seen = []

    def request(method, url, body, headers, timeout):
        seen.append((method, url, body, headers))
        return 200, {"accepted": 1, "duplicates": 0}

    cfg = {"dashboard_url": "http://dash.example/", "dashboard_token": "tok"}
    send = ob.make_sender(cfg, lambda: "ident", "razer", request_fn=request)
    out = ob.flush(send, box)
    assert out["sent"] == 1
    method, url, body, headers = seen[0]
    assert (method, url) == ("POST", "http://dash.example/sorter/agent/ledger/copies")
    assert body["machine"] == "razer" and body["copies"][0]["path"] == "Trip/A001.braw"
    assert headers["X-CCSync-Token"] == "tok" and headers["X-CCSync-Identity"] == "ident"


def test_no_dashboard_means_no_sender_and_nothing_is_lost(box):
    assert ob.make_sender({}, None) is None
    ob.append([copy()], box)
    out = ob.flush(None, box, cfg={"dashboard_url": "", "dashboard_token": ""})
    assert out["remaining"] == 1


# ------------------------------------------------------------------ the config's path

def test_the_path_follows_the_log_or_an_explicit_setting(tmp_path):
    assert ob.path_for({}) is None                                           # a harness: never the real home
    assert ob.path_for({"ledger_outbox_path": str(tmp_path / "x.jsonl")}) == tmp_path / "x.jsonl"
    p = ob.path_for({"log_path": str(tmp_path / "companion.log")})
    assert p == tmp_path / ob.FILENAME
    assert ob.default_path().name == "ledger-outbox.jsonl" and ob.default_path().parent.name == ".ccsync"


# ------------------------------------------------------------------ from a receipt

def test_copies_from_a_receipt_keep_verified_local_drive_copies_only(tmp_path):
    drive = tmp_path / "drive"
    (drive / "restore").mkdir(parents=True)
    f = drive / "restore" / "a.mov"
    f.write_bytes(b"hello")
    receipt = {"copier": "teracopy", "copied": [
        {"src": "a.mov", "dst": {"root": "local:AAAA0001", "rel": "restore/a.mov"}, "size": 5, "verified": True},
        {"src": "b.mov", "dst": {"root": "local:AAAA0001", "rel": "restore/b.mov"}, "size": 5, "verified": False},
        {"src": "c.mov", "dst": {"root": "pool", "rel": "Footage/c.mov"}, "size": 5, "verified": True},
        {"src": "d.mov", "dst": {"root": "local:ZZZZ9999", "rel": "d.mov"}, "size": 5, "verified": True},
        {"src": "e.mov", "dst": "weird", "size": 5, "verified": True}]}

    def volumes(scope, skip=()):
        return [{"serial": "AAAA0001", "label": "SCRATCH", "root": str(drive)}]

    got = ob.copies_from_receipt(receipt, volumes)
    assert len(got) == 1
    c = got[0]
    assert c["volume"] == {"serial": "AAAA0001", "label": "SCRATCH"} and c["path"] == "restore/a.mov"
    assert c["size"] == 5 and c["verified"] == "full" and c["tool"] == "teracopy"
    assert c["mtime"] == int(round(f.stat().st_mtime * 1000))
    assert ob.normalize(c) is not None
    assert ob.copies_from_receipt(receipt, lambda scope, skip=(): 1 / 0) == []


# ------------------------------------------------------------------ the flusher

def test_the_flusher_sends_on_a_kick_and_backs_off_a_site_without_a_sorter(box):
    ob.append([copy()], box)
    srv = Server()
    t = {"now": 0.0}
    f = ob.OutboxFlusher({}, path=box, send=srv, clock=lambda: t["now"])
    assert f.tick()["sent"] == 1 and srv.got
    assert f.tick() is None                                                  # nothing waiting
    ob.append([copy(path="two.mov")], box)
    nosorter = Server(404)
    f2 = ob.OutboxFlusher({}, path=box, send=nosorter, clock=lambda: t["now"])
    assert f2.tick()["status"] == 404
    assert f2.tick() is None                                                 # backing off ten minutes
    t["now"] += ob.NO_SORTER_BACKOFF_SECONDS + 1
    nosorter.statuses = []
    assert f2.tick()["sent"] == 1


def test_the_flusher_thread_flushes_when_kicked_and_stops(box):
    srv = Server()
    f = ob.OutboxFlusher({}, path=box, send=srv)
    f.start()
    try:
        ob.append([copy()], box)
        f.kick()
        deadline = time.time() + 5
        while not srv.got and time.time() < deadline:
            time.sleep(0.02)
    finally:
        f.stop()
    assert srv.got and f._thread is None


def test_the_flusher_is_off_when_the_ledger_is_off(box):
    ob.append([copy()], box)
    srv = Server()
    f = ob.OutboxFlusher({"sorter_ledger_enabled": False}, path=box, send=srv)
    assert f.tick() is None and f.start() is None and f._thread is None and not srv.got
