"""The offline ledger mirror: pull the ledger's copies for this machine's volumes, answer `where()` with no network.

footage-sorter docs/LEDGER-BROWSER-DESIGN.md, "The companion" item 4.
"""
from __future__ import annotations

import pytest

from ccsync_companion import ledger_mirror as lm
from ccsync_companion.ledger_mirror import LedgerMirror

T0 = 1_786_236_852_123


def row(i, volume="vol:6880882B", path=None, name="A001.braw", size=100, mtime=T0, **extra):
    r = {"id": i, "volume_id": volume, "path": path or f"Trip/{name}", "name": name, "size": size,
         "mtime": mtime, "role": "master", "verified": "full", "at": "2026-11-09T10:00:00Z"}
    r.update(extra)
    return r


class Server:
    """GET /sorter/agent/ledger/mirror: pages of rows, an opaque cursor."""

    def __init__(self, pages):
        self.pages = list(pages)          # list of (rows, cursor)
        self.last = ""
        self.calls = []
        self.status = 200

    def __call__(self, method, url, body, headers, timeout):
        self.calls.append((method, url, headers))
        if isinstance(self.status, Exception):
            raise self.status
        if self.status != 200:
            return self.status, {"detail": "no"}
        rows, cursor = self.pages.pop(0) if self.pages else ([], self.last)     # no news: the cursor stays
        self.last = cursor
        return 200, {"rows": rows, "cursor": cursor}


def mirror(tmp_path, server, **cfg):
    base = {"dashboard_url": "http://dash.example", "dashboard_token": "tok"}
    base.update(cfg)
    return LedgerMirror(base, path=tmp_path / "state" / "ledger-mirror.sqlite", request_fn=server,
                        identity_token_fn=lambda: "ident")


def test_a_pull_stores_rows_and_where_answers_offline(tmp_path):
    srv = Server([([row(1), row(2, volume="nas:thecreatorspool", path="Projects/Trip/A001.braw"),
                    row(3, name="B002.braw", size=7)], "3")])
    m = mirror(tmp_path, srv)
    out = m.pull(["vol:6880882B", "nas:thecreatorspool"])
    assert out["ok"] is True and out["rows"] == 3 and out["cursor"] == "3"
    srv.status = OSError("no network in the tent")
    holders = m.where("a001.BRAW", 100, T0 + 2000)
    assert [h["volume_id"] for h in holders] == ["vol:6880882B", "nas:thecreatorspool"]
    assert m.volumes_holding("A001.braw", 100, T0) == ["vol:6880882B", "nas:thecreatorspool"]
    assert m.where("B002.braw", 7)[0]["path"] == "Trip/B002.braw"            # no mtime: name and size


def test_the_ledgers_matching_rule_name_size_and_mtime_within_three_seconds(tmp_path):
    m = mirror(tmp_path, Server([]))
    m.apply([row(1), row(2, name="x.mov", size=5, mtime=None)])
    assert m.where("A001.braw", 100, T0 + 3000) and not m.where("A001.braw", 100, T0 + 3001)
    assert m.where("A001.braw", 100, T0 - 3000) and not m.where("A001.braw", 100, T0 - 3001)
    assert not m.where("A001.braw", 101, T0)                                 # another size
    assert m.where("x.mov", 5, 12345)                                        # a copy with no mtime matches any
    assert m.where("A001.braw", 100, None)                                   # asking without one matches any


def test_missing_and_deleted_copies_do_not_count(tmp_path):
    m = mirror(tmp_path, Server([]))
    m.apply([row(1, missing_since="2026-11-09T12:00:00Z"), row(2, volume="vol:2", deleted_at="2026-11-09"),
             row(3, volume="vol:3", missing=True), row(4, volume="vol:4", deleted=True), row(5, volume="vol:5")])
    assert m.volumes_holding("A001.braw", 100, T0) == ["vol:5"]


def test_a_changed_row_replaces_the_old_one_and_a_repeat_changes_nothing(tmp_path):
    m = mirror(tmp_path, Server([]))
    assert m.apply([row(1)]) == 1
    assert m.apply([row(1)]) == 1 and m.status()["rows"] == 1
    m.apply([row(1, missing_since="2026-11-09T12:00:00Z")])
    assert m.where("A001.braw", 100) == [] and m.status()["rows"] == 1
    m.apply([row(1)])                                                        # seen again: back
    assert len(m.where("A001.braw", 100)) == 1


def test_camel_case_rows_and_junk_rows(tmp_path):
    m = mirror(tmp_path, Server([]))
    n = m.apply([{"id": 9, "volumeId": "vol:9", "path": "p/a.mov", "size": 3, "mtimeMs": T0, "missingSince": None},
                 {"id": "x"}, {"volume_id": "v"}, "nope", None, {"id": 10, "volume_id": "v", "path": "p", "size": "big"}])
    assert n == 1
    assert m.where("a.mov", 3, T0)[0]["volume_id"] == "vol:9"


def test_the_whole_server_row_is_kept(tmp_path):
    import json
    m = mirror(tmp_path, Server([]))
    m.apply([row(1, label="CIB_D1", kind="ours")])
    conn = m._connect()
    try:
        raw = json.loads(conn.execute("SELECT raw FROM copies WHERE id=1").fetchone()["raw"])
    finally:
        conn.close()
    assert raw["kind"] == "ours" and raw["label"] == "CIB_D1"


def test_the_cursor_carries_over_and_pages_are_followed(tmp_path):
    srv = Server([([row(1), row(2)], "2"), ([row(3)], "3"), ([], "3")])
    m = mirror(tmp_path, srv)
    out = m.pull(["vol:A", "nas:x"])
    assert out["pages"] == 3 and out["rows"] == 3 and m.status()["rows"] == 3
    urls = [c[1] for c in srv.calls]
    assert urls[0].endswith("?volumes=nas:x,vol:A&since=")
    assert urls[1].endswith("&since=2") and urls[2].endswith("&since=3")
    assert srv.calls[0][2]["X-CCSync-Token"] == "tok" and srv.calls[0][2]["X-CCSync-Identity"] == "ident"
    # next time: only what is new
    srv2 = Server([([row(4)], "4")])
    m._request = srv2
    m.pull(["nas:x", "vol:A"])
    assert srv2.calls[0][1].endswith("&since=3") and m.status()["rows"] == 4


def test_a_new_volume_is_caught_up_on_its_own_and_the_rest_carry_on(tmp_path):
    """Audit comp-field-7 (2026-11-11): a different set used to start the whole pull over from
    nothing, the NAS's ledger included, every time a card went in or out of a reader."""
    srv = Server([([row(1, volume="vol:A")], "7")])
    m = mirror(tmp_path, srv)
    m.pull(["vol:A"])
    srv2 = Server([([row(2, volume="vol:B", name="B.braw")], "3"), ([], "3"), ([row(3, volume="vol:A", name="C.braw")], "9")])
    m._request = srv2
    out = m.pull(["vol:A", "vol:B"])
    urls = [c[1] for c in srv2.calls]
    assert urls[0].endswith("?volumes=vol:B&since=")            # vol:B alone, from the start
    assert urls[2].endswith("?volumes=vol:A,vol:B&since=7")     # then everything, from where it was
    assert out["ok"] and m.status()["cursor"] == "9" and m.status()["volumes"] == ["vol:A", "vol:B"]
    assert m.where("A001.braw", 100) and m.where("B.braw", 100) and m.where("C.braw", 100)


def test_a_drive_that_went_into_the_bag_keeps_its_rows_and_stays_in_the_pull(tmp_path):
    """The other half of comp-field-7: unplugging a drive deleted its rows, so a card copied to
    two field drives dropped to "one copy" the moment one of them was put away."""
    srv = Server([([row(1, volume="vol:A"), row(2, volume="vol:B", name="B.braw")], "5")])
    m = mirror(tmp_path, srv)
    m.pull(["vol:A", "vol:B"])
    srv2 = Server([([], "5")])
    m._request = srv2
    m.pull(["vol:A"])                                           # vol:B is in the bag
    assert srv2.calls[0][1].endswith("?volumes=vol:A,vol:B&since=5")
    assert m.where("B.braw", 100) and m.status()["volumes"] == ["vol:A", "vol:B"]


def test_an_away_volume_is_dropped_when_it_is_a_card_or_long_gone(tmp_path):
    now = [1_000_000.0]
    srv = Server([([row(1, volume="vol:A"), row(2, volume="vol:CARD", name="B.braw"),
                    row(3, volume="vol:OLD", name="C.braw")], "5")])
    m = LedgerMirror({"dashboard_url": "http://dash.example", "dashboard_token": "tok"},
                     path=tmp_path / "m.sqlite", request_fn=srv, clock=lambda: now[0])
    m.pull(["vol:A", "vol:CARD", "vol:OLD"])
    m._request = Server([([], "5")])
    m.pull(["vol:A", "vol:OLD"], keep=lambda vid: vid != "vol:CARD")     # the card came out
    assert m.where("B.braw", 100) == [] and m.where("C.braw", 100)
    assert m.status()["volumes"] == ["vol:A", "vol:OLD"]
    now[0] += (lm.KEEP_DAYS + 1) * 86400
    m._request = Server([([], "5")])
    m.pull(["vol:A"])                                           # vol:OLD not seen for two months
    assert m.where("C.braw", 100) == [] and m.status()["volumes"] == ["vol:A"]


def test_a_catch_up_that_dies_is_done_again_and_moves_no_cursor(tmp_path):
    srv = Server([([row(1, volume="vol:A")], "7")])
    m = mirror(tmp_path, srv)
    m.pull(["vol:A"])
    down = Server([])
    down.status = OSError("dropped")
    m._request = down
    out = m.pull(["vol:A", "vol:B"])
    assert out["ok"] is False and m.status()["cursor"] == "7" and m.status()["volumes"] == ["vol:A"]
    srv3 = Server([([row(2, volume="vol:B", name="B.braw")], "3"), ([], "3"), ([], "7")])
    m._request = srv3
    assert m.pull(["vol:A", "vol:B"])["ok"] and srv3.calls[0][1].endswith("?volumes=vol:B&since=")


def test_a_verdicts_lookups_share_one_connection(tmp_path, monkeypatch):
    """Audit comp-field-4 (2026-11-11): one connection, one WAL pragma and the whole schema per
    file on the card."""
    srv = Server([([row(1)], "1")])
    m = mirror(tmp_path, srv)
    m.pull(["vol:6880882B"])
    opened = []
    real = lm.sqlite3.connect
    monkeypatch.setattr(lm.sqlite3, "connect", lambda *a, **k: (opened.append(1), real(*a, **k))[1])
    with m.reading():
        for _ in range(200):
            assert len(m.where("A001.braw", 100, T0)) == 1
    assert len(opened) == 1
    assert len(m.where("A001.braw", 100, T0)) == 1 and len(opened) == 2     # outside: one per call, as before


def test_a_failed_pull_keeps_what_it_had_and_says_why(tmp_path):
    srv = Server([([row(1)], "1")])
    m = mirror(tmp_path, srv)
    m.pull(["vol:A"])
    for status, words in ((OSError("down"), "could not reach"), (503, "HTTP 503"), (403, "HTTP 403")):
        srv.status = status
        out = m.pull(["vol:A"])
        assert out["ok"] is False and words in out["error"]
    assert m.status()["rows"] == 1 and m.status()["cursor"] == "1" and m.where("A001.braw", 100)


def test_a_pull_that_dies_halfway_keeps_the_pages_it_applied(tmp_path):
    class Dying(Server):
        def __call__(self, method, url, body, headers, timeout):
            if len(self.calls) == 1:
                self.calls.append(url)
                raise OSError("dropped")
            return super().__call__(method, url, body, headers, timeout)

    srv = Dying([([row(1)], "1"), ([row(2)], "2")])
    m = mirror(tmp_path, srv)
    out = m.pull(["vol:A"])
    assert out["ok"] is False and m.status()["rows"] == 1 and m.status()["cursor"] == "1"


def test_no_dashboard_is_a_clean_no(tmp_path):
    m = mirror(tmp_path, Server([]), dashboard_url="")
    assert m.pull(["vol:A"])["ok"] is False
    assert m.where("a", 1) == []                                             # an empty mirror, not an error


def test_a_corrupt_file_is_an_empty_mirror_not_a_crash(tmp_path):
    path = tmp_path / "state" / "ledger-mirror.sqlite"
    path.parent.mkdir()
    path.write_bytes(b"this is not a database" * 100)
    m = LedgerMirror({}, path=path, request_fn=Server([]))
    assert m.where("a", 1) == []
    assert m.status()["rows"] == 0
    assert m.pull(["vol:A"])["ok"] is False


def test_the_path_follows_the_log_or_an_explicit_setting(tmp_path):
    assert lm.path_for({}) is None
    assert lm.path_for({"ledger_mirror_path": str(tmp_path / "m.sqlite")}) == tmp_path / "m.sqlite"
    assert lm.path_for({"log_path": str(tmp_path / "companion.log")}) == tmp_path / lm.FILENAME
    assert lm.default_path().name == "ledger-mirror.sqlite" and lm.default_path().parent.name == ".ccsync"


def test_the_lookup_uses_the_index(tmp_path):
    m = mirror(tmp_path, Server([]))
    m.apply([row(i, name=f"f{i}.mov", size=i) for i in range(1, 50)])
    conn = m._connect()
    try:
        plan = conn.execute("EXPLAIN QUERY PLAN SELECT id FROM copies WHERE name_lc=? AND size=? AND missing_since IS NULL"
                            " AND deleted_at IS NULL", ("f3.mov", 3)).fetchall()
    finally:
        conn.close()
    assert any("copies_match" in str(tuple(r)) for r in plan)


# ----------------------------------------------- the sorter's own answer shape (cols + list rows, cursor "seq:id", more)

COLS = ["id", "name_lc", "size", "mtime", "volume_id", "path", "role", "verified", "missing", "gone"]


class SorterServer(Server):
    """engine.ledger.mirror's shape: `cols` once, each row a list, `more` while there is another page."""

    def __call__(self, method, url, body, headers, timeout):
        self.calls.append((method, url, headers))
        rows, cursor, more = self.pages.pop(0) if self.pages else ([], self.last, False)
        self.last = cursor
        return 200, {"cols": COLS, "rows": rows, "cursor": cursor, "more": more,
                     "volumes": [{"id": "vol:6880882B", "label": "CIB_D1", "kind": "ours"},
                                 {"id": "nas:thecreatorspool", "label": "The Creators Pool", "kind": "nas"}]}


def test_list_rows_with_cols_are_read_and_more_is_followed(tmp_path):
    srv = SorterServer([
        ([[1, "a001.braw", 100, T0, "vol:6880882B", "Trip/A001.braw", "master", "full", 0, 0],
          [2, "a001.braw", 100, T0, "nas:thecreatorspool", "Projects/Trip/A001.braw", "master", "full", 0, 0]], "5:2", True),
        ([[3, "b.braw", 7, T0, "vol:6880882B", "Trip/b.braw", "master", "listed", 1, 0],
          [4, "c.braw", 8, T0, "vol:6880882B", "Trip/c.braw", "master", "listed", 0, 1]], "9:4", False),
    ])
    m = mirror(tmp_path, srv)
    out = m.pull(["vol:6880882B", "nas:thecreatorspool"])
    assert out["ok"] and out["pages"] == 2 and out["rows"] == 4 and out["cursor"] == "9:4"
    assert srv.calls[1][1].endswith("&since=5%3A2")                                  # the cursor goes back as it came
    assert m.volumes_holding("A001.braw", 100, T0) == ["vol:6880882B", "nas:thecreatorspool"]
    assert m.where("b.braw", 7) == []                                                # missing: not found by the last scan
    assert m.where("c.braw", 8) == []                                                # gone: replaced, moved or deleted
    assert m.status()["rows"] == 4 and m.status()["cursor"] == "9:4"


def test_the_volume_names_come_with_the_pull_and_accumulate(tmp_path):
    srv = SorterServer([([], "0:0", False)])
    m = mirror(tmp_path, srv)
    assert m.volume_info() == {}
    m.pull(["vol:6880882B"])
    info = m.volume_info()
    assert info["vol:6880882B"] == {"label": "CIB_D1", "kind": "ours"} and info["nas:thecreatorspool"]["kind"] == "nas"
