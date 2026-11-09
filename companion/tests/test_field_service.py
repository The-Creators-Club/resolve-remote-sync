"""The field page's brain: cards, destinations, verdicts from the offline mirror, the last choices,
the outbox and the pull. No server, no reader and no dashboard: drives are temp folders."""
from __future__ import annotations

import json
import os
from pathlib import Path

import pytest

from ccsync_companion import field_mode, field_service, ledger_mirror, ledger_outbox, sorter_cards
from ccsync_companion.field_service import FieldService

SERIAL = "CARD0001"
T0 = 1_760_000_000
NAS = "nas:thecreatorspool"


@pytest.fixture(autouse=True)
def _clean_registry():
    sorter_cards._busy.clear()
    sorter_cards._known_drives.clear()
    yield
    sorter_cards._busy.clear()
    sorter_cards._known_drives.clear()


class Net:
    """The dashboard, as far as the field page talks to it."""

    def __init__(self):
        self.up = True
        self.calls: list[tuple[str, str]] = []
        self.copies: list[dict] = []
        self.mirror_rows: list = []

    def request(self, method, url, body, headers, timeout):
        self.calls.append((method, url))
        if not self.up:
            raise OSError("no route to host")
        if url.endswith("/sorter/agent/ledger/copies"):
            self.copies += body["copies"]
            return 200, {"ok": True, "accepted": len(body["copies"]), "duplicates": 0}
        if "/sorter/agent/ledger/mirror" in url:
            return 200, {"rows": self.mirror_rows, "cursor": "1", "more": False,
                         "volumes": [{"id": NAS, "label": "NAS pool", "kind": "nas"}]}
        return 404, None


class World:
    def __init__(self, tmp: Path, **cfg):
        self.tmp = tmp
        self.card = tmp / "card"
        self.drives = {"A": tmp / "ours", "B": tmp / "client", "L": tmp / "laptop-d"}
        for d in [self.card, *self.drives.values()]:
            d.mkdir()
        (self.card / "PRIVATE" / "M4ROOT" / "CLIP").mkdir(parents=True)
        self.files = {}
        for i, (n, size) in enumerate({"C0001.MP4": 300_000, "C0002.MP4": 250_000}.items()):
            p = self.card / "PRIVATE" / "M4ROOT" / "CLIP" / n
            self.files[n] = os.urandom(size)
            p.write_bytes(self.files[n])
            os.utime(p, (T0 + i, T0 + i))
        (self.card / "PRIVATE" / "M4ROOT" / "CLIP" / "C0001M01.XML").write_text("<x/>")
        self.net = Net()
        self.extra: list[dict] = []
        self.cfg = {"dashboard_url": "http://dash.test", "dashboard_token": "tok", **cfg}
        self.pool = tmp / "pool"
        self.svc = self.build()

    def vols(self, scope="removable", skip=None):
        skip = skip or set()
        out = [
            {"serial": SERIAL, "label": "A001", "drive": "Z:", "root": str(self.card), "removable": True,
             "capacity": 64 * 10 ** 9, "free": 10 ** 9, "fs": "exFAT", "drive_type": "removable", "system": False},
            {"serial": "SYS00001", "label": "OS", "drive": "C:", "root": str(self.tmp / "sys"), "removable": False,
             "capacity": 10 ** 12, "free": 10 ** 11, "fs": "NTFS", "drive_type": "fixed", "system": True},
            {"serial": "AAAA0001", "label": "CIB_D1", "drive": "J:", "root": str(self.drives["A"]), "removable": False,
             "capacity": 14 * 10 ** 12, "free": 10 ** 12, "fs": "NTFS", "drive_type": "fixed", "system": False},
            {"serial": "BBBB0001", "label": "WD-3", "drive": "K:", "root": str(self.drives["B"]), "removable": False,
             "capacity": 4 * 10 ** 12, "free": 10 ** 12, "fs": "NTFS", "drive_type": "fixed", "system": False},
            {"serial": "LLLL0001", "label": "Data", "drive": "D:", "root": str(self.drives["L"]), "removable": False,
             "capacity": 10 ** 12, "free": 10 ** 11, "fs": "NTFS", "drive_type": "fixed", "system": False},
        ] + self.extra
        return [v for v in out if v["root"] not in skip and (scope != "removable" or v["removable"])]

    def build(self, **over):
        kw = dict(cfg=self.cfg, volumes_fn=self.vols, mirror=self.mirror(),
                  store=field_mode.FieldStore(self.tmp / "state.json"),
                  local=field_mode.LocalCopies(self.tmp / "local.jsonl"),
                  request_fn=self.net.request, outbox_path=self.tmp / "outbox.jsonl",
                  physical_fn=lambda root: "", machine_name="razer", auto_sync=False)
        kw.update(over)
        return FieldService(**kw)

    def mirror(self):
        return ledger_mirror.LedgerMirror(self.cfg, path=self.tmp / "mirror.sqlite", request_fn=self.net.request)

    def add_folder(self):
        folder = self.drives["L"] / "FieldBackup"
        self.svc.add_folder(str(folder))
        return f"folder:{os.path.normcase(os.path.normpath(str(folder))).rstrip(chr(92) + '/')}"

    def finish(self, run_snapshot):
        run = self.svc.copier.get(run_snapshot["id"])
        assert self.svc.copier.wait(run), "the run did not finish"
        return run


def card_of(state, serial=SERIAL):
    return next(c for c in state["cards"] if c["serial"] == serial)


def dest_of(state, dest_id):
    return next(d for d in state["destinations"] if d["id"] == dest_id)


# ------------------------------------------------------------------------- cards and drives
def test_the_card_in_the_reader_is_listed_with_where_it_will_land(tmp_path):
    w = World(tmp_path)
    st = w.svc.state()
    c = card_of(st)
    assert (c["label"], c["kind"], c["files"]) == ("A001", "sony", 3)
    assert c["folder"] == field_mode.card_folder_name("A001", SERIAL, field_mode.card_day(
        sorter_cards.list_card(w.card)["files"]))
    assert c["verdict"]["state"] == "unsafe" and c["verdict"]["none"] == 2


def test_attached_drives_are_destinations_the_system_drive_and_the_card_are_not(tmp_path):
    w = World(tmp_path)
    st = w.svc.state()
    ids = {d["id"] for d in st["destinations"]}
    assert ids == {"vol:AAAA0001", "vol:BBBB0001", "vol:LLLL0001"}
    a, b = dest_of(st, "vol:AAAA0001"), dest_of(st, "vol:BBBB0001")
    assert (a["kind"], a["counts"]) == ("ours", True) and (b["kind"], b["counts"]) == ("client", False)
    assert a["free"] > 0 and a["present"]


def test_a_drive_the_ledger_has_named_is_labelled_from_it(tmp_path):
    w = World(tmp_path)
    conn = w.svc.mirror._connect()
    with conn:
        w.svc.mirror._set_meta(conn, "volume_info", json.dumps({"vol:LLLL0001": {"label": "razer D:", "kind": "laptop"}}))
    conn.close()
    d = dest_of(w.svc.state(), "vol:LLLL0001")
    assert d["label"] == "razer D:" and d["kind"] == "laptop" and d["kindSource"] == "ledger"


def test_a_removable_drive_full_of_footage_that_is_ours_is_a_drive_not_a_card(tmp_path):
    w = World(tmp_path)
    usb = tmp_path / "usb"
    (usb / "Shoot").mkdir(parents=True)
    (usb / "Shoot" / "a.mp4").write_bytes(b"x" * 10)
    w.extra.append({"serial": "USB00001", "label": "CIB_D2", "drive": "M:", "root": str(usb), "removable": True,
                    "capacity": 10 ** 12, "free": 10 ** 11, "fs": "NTFS", "drive_type": "removable", "system": False})
    st = w.svc.state(refresh=True)
    assert [c["serial"] for c in st["cards"]] == [SERIAL]
    assert dest_of(st, "vol:USB00001")["kind"] == "ours"


def test_a_generic_removable_volume_with_footage_shows_as_a_card_and_as_a_drive(tmp_path):
    w = World(tmp_path)
    usb = tmp_path / "stick"
    (usb / "clips").mkdir(parents=True)
    (usb / "clips" / "a.mp4").write_bytes(b"x" * 10)
    w.extra.append({"serial": "STICK001", "label": "STICK", "drive": "N:", "root": str(usb), "removable": True,
                    "capacity": 10 ** 11, "free": 10 ** 10, "fs": "exFAT", "drive_type": "removable", "system": False})
    st = w.svc.state(refresh=True)
    assert {c["serial"] for c in st["cards"]} == {SERIAL, "STICK001"}
    assert "vol:STICK001" in {d["id"] for d in st["destinations"]}


def test_no_card_in_the_reader_is_an_empty_list_not_an_error(tmp_path):
    w = World(tmp_path)
    w.card_present = False
    w.svc = w.build(volumes_fn=lambda scope="removable", skip=None: [v for v in w.vols(scope, skip) if v["serial"] != SERIAL])
    st = w.svc.state()
    assert st["cards"] == [] and st["ok"]
    with pytest.raises(ValueError, match="not in a reader"):
        w.svc.start_copy(SERIAL, ["vol:AAAA0001"])


# ----------------------------------------------------------------------------- folders and pool
def test_a_laptop_folder_is_added_remembered_and_counts_as_the_laptop(tmp_path):
    w = World(tmp_path)
    fid = w.add_folder()
    st = w.svc.state()
    f = dest_of(st, fid)
    assert f["type"] == "folder" and f["kind"] == "laptop" and f["counts"] and f["present"] and f["removable"]
    assert fid in {d["id"] for d in w.build().state()["destinations"]}           # remembered per machine


def test_folders_from_the_config_are_offered_too(tmp_path):
    w = World(tmp_path)
    w.cfg["field_dest_folders"] = [str(w.drives["L"] / "FieldBackup")]
    assert any(d["type"] == "folder" for d in w.svc.state()["destinations"])


@pytest.mark.parametrize("bad", ["", "relative/path", "..\\x", "Q:\\not-a-drive-we-have\\x"])
def test_a_folder_that_is_not_a_real_place_is_refused_in_words(tmp_path, bad):
    w = World(tmp_path)
    with pytest.raises(ValueError):
        w.svc.add_folder(bad)


def test_the_nas_pool_is_offered_when_configured_and_reachable(tmp_path):
    w = World(tmp_path)
    w.pool.mkdir()
    w.cfg["jobs_pool_root"] = str(w.pool)
    st = w.svc.state()
    p = dest_of(st, "pool")
    assert (p["type"], p["kind"], p["counts"], p["present"]) == ("pool", "nas", True, True)
    assert p["recordable"] is False                                      # the server's scan records the pool
    w.svc._probe = lambda path: False
    p = dest_of(w.svc.state(), "pool")
    assert not p["present"] and "cannot be reached" in p["why"]
    with pytest.raises(ValueError, match="cannot be reached"):
        w.svc.start_copy(SERIAL, ["pool"])


def test_without_a_configured_pool_there_is_no_nas_destination(tmp_path):
    assert "pool" not in {d["id"] for d in World(tmp_path).svc.state()["destinations"]}


def test_a_drive_nobody_has_named_has_no_kind_until_a_person_sets_it(tmp_path):
    w = World(tmp_path)
    w.extra.append({"serial": "ODD00001", "label": "Seagate", "drive": "P:", "root": str(tmp_path / "odd"),
                    "removable": False, "capacity": 10 ** 12, "free": 10 ** 11, "fs": "NTFS",
                    "drive_type": "fixed", "system": False})
    (tmp_path / "odd").mkdir()
    st = w.svc.state(refresh=True)
    assert dest_of(st, "vol:ODD00001")["kind"] == "unknown"
    w.svc.set_kind("vol:ODD00001", "ours")
    d = dest_of(w.svc.state(refresh=True), "vol:ODD00001")
    assert d["kind"] == "ours" and d["kindSource"] == "you" and d["counts"]
    with pytest.raises(ValueError):
        w.svc.set_kind("vol:ODD00001", "nas")
    with pytest.raises(ValueError):
        w.svc.set_kind("nas:x", "ours")


# ------------------------------------------------------------------------------- the lanes
def test_two_folders_on_one_physical_disk_are_one_lane_and_two_disks_are_two(tmp_path):
    w = World(tmp_path)
    w.svc = w.build(physical_fn=lambda root: "disk:7" if root in (str(w.drives["L"]), str(w.drives["A"])) else "disk:9")
    st = w.svc.state()
    assert dest_of(st, "vol:AAAA0001")["lane"] == "disk:7" == dest_of(st, "vol:LLLL0001")["lane"]
    assert dest_of(st, "vol:BBBB0001")["lane"] == "disk:9"


# --------------------------------------------------------------------------- a whole copy
def test_copy_to_two_destinations_makes_the_card_safe_to_format_and_remembers_the_choice(tmp_path):
    w = World(tmp_path)
    fid = w.add_folder()
    run = w.finish(w.svc.start_copy(SERIAL, ["vol:AAAA0001", fid]))
    assert all(l.state == "done" for l in run.lanes)
    folder = card_of(w.svc.state())["folder"]
    assert (w.drives["A"] / "FieldBackup" / folder / "PRIVATE" / "M4ROOT" / "CLIP" / "C0001.MP4").read_bytes() == w.files["C0001.MP4"]
    assert (w.drives["L"] / "FieldBackup" / folder / "PRIVATE" / "M4ROOT" / "CLIP" / "C0002.MP4").read_bytes() == w.files["C0002.MP4"]
    v = card_of(w.svc.state())["verdict"]
    assert v["safeToFormat"] and v["flags"] == []                      # ours + laptop: safe, not laptop-only
    assert v["perDest"]["vol:AAAA0001"] == {"have": 2, "of": 2}
    assert w.build().store.last_dests() == ["vol:AAAA0001", fid]
    assert set(w.build().state()["lastDests"]) == {"vol:AAAA0001", fid}
    assert dest_of(w.svc.state(), "vol:AAAA0001")["ticked"]


def test_one_copy_is_not_enough_and_a_client_drive_does_not_make_two(tmp_path):
    w = World(tmp_path)
    w.finish(w.svc.start_copy(SERIAL, ["vol:AAAA0001"]))
    v = card_of(w.svc.state())["verdict"]
    assert v["state"] == "unsafe" and v["single"] == 2
    w.finish(w.svc.start_copy(SERIAL, ["vol:BBBB0001"]))
    v = card_of(w.svc.state())["verdict"]
    assert v["state"] == "unsafe" and any("do not count" in n for n in v["notes"])
    w.svc.set_kind("vol:BBBB0001", "ours")                              # ...until a person says it is ours
    assert card_of(w.svc.state())["verdict"]["safeToFormat"]


def test_two_laptop_copies_are_safe_but_flagged_laptop_only(tmp_path):
    w = World(tmp_path)
    w.add_folder()
    w.svc.set_kind("vol:AAAA0001", "laptop")                            # a person calls this drive a laptop's
    w.finish(w.svc.start_copy(SERIAL, ["vol:AAAA0001", w.add_folder()]))
    v = card_of(w.svc.state())["verdict"]
    assert v["safeToFormat"] and v["flags"] == ["laptop-only"]


def test_one_copy_at_home_in_the_pool_is_enough(tmp_path):
    w = World(tmp_path)
    w.pool.mkdir()
    w.cfg["jobs_pool_root"] = str(w.pool)
    w.finish(w.svc.start_copy(SERIAL, ["pool"]))
    folder = card_of(w.svc.state())["folder"]
    assert (w.pool / "FieldBackup" / folder / "PRIVATE" / "M4ROOT" / "CLIP" / "C0001.MP4").exists()
    v = card_of(w.svc.state())["verdict"]
    assert v["safeToFormat"] and "at home" in v["headline"]


def test_what_the_ledger_already_knows_counts_with_no_network(tmp_path):
    w = World(tmp_path)
    w.net.up = False
    mirror = w.svc.mirror
    t = int(T0 * 1000)
    mirror.apply([{"id": 1, "volume_id": NAS, "path": "Trip/C0001.MP4", "name": "C0001.MP4", "size": 300_000, "mtime": t},
                  {"id": 2, "volume_id": NAS, "path": "Trip/C0002.MP4", "name": "C0002.MP4", "size": 250_000, "mtime": t + 1000}])
    conn = mirror._connect()
    with conn:
        mirror._set_meta(conn, "volume_info", json.dumps({NAS: {"label": "NAS pool", "kind": "nas"}}))
    conn.close()
    v = card_of(w.svc.state())["verdict"]
    assert v["safeToFormat"] and "at home" in v["headline"]


def test_a_card_with_every_file_already_on_the_drive_elsewhere_is_not_copied_again(tmp_path):
    w = World(tmp_path)
    old = w.drives["A"] / "OldTrip"
    old.mkdir()
    for n, data in w.files.items():
        (old / n).write_bytes(data)
        i = 0 if n == "C0001.MP4" else 1
        os.utime(old / n, (T0 + i, T0 + i))
    t = int(T0 * 1000)
    w.svc.mirror.apply([{"id": 1, "volume_id": "vol:AAAA0001", "path": "OldTrip/C0001.MP4", "name": "C0001.MP4", "size": 300_000, "mtime": t},
                        {"id": 2, "volume_id": "vol:AAAA0001", "path": "OldTrip/C0002.MP4", "name": "C0002.MP4", "size": 250_000, "mtime": t + 1000}])
    run = w.finish(w.svc.start_copy(SERIAL, ["vol:AAAA0001"]))
    lane = run.lanes[0]
    assert lane.counts["there"] == 2 and lane.counts["copied"] == 1          # only the XML sidecar is new
    assert not (w.drives["A"] / "FieldBackup" / card_of(w.svc.state())["folder"] / "PRIVATE" / "M4ROOT" / "CLIP" / "C0001.MP4").exists()


# ----------------------------------------------------------------------------- start refusals
def test_copy_refuses_with_a_sentence(tmp_path):
    w = World(tmp_path)
    with pytest.raises(ValueError, match="at least one"):
        w.svc.start_copy(SERIAL, [])
    with pytest.raises(ValueError, match="not available"):
        w.svc.start_copy(SERIAL, ["vol:NOPE0000"])
    with pytest.raises(ValueError, match="not in a reader"):
        w.svc.start_copy("OTHER001", ["vol:AAAA0001"])
    with pytest.raises(ValueError, match="not available"):                # a card is never its own destination
        w.svc.start_copy(SERIAL, [f"vol:{SERIAL}"])


def test_a_destination_whose_drive_is_gone_is_refused_by_name(tmp_path):
    w = World(tmp_path)
    fid = w.add_folder()
    w.svc = w.build(volumes_fn=lambda scope="removable", skip=None: [v for v in w.vols(scope, skip) if v["serial"] != "LLLL0001"])
    st = w.svc.state(refresh=True)
    assert not dest_of(st, fid)["present"] and "not connected" in dest_of(st, fid)["why"]
    with pytest.raises(ValueError, match="not connected"):
        w.svc.start_copy(SERIAL, [fid])


# ------------------------------------------------------------------------------- the ledger
def test_each_verified_copy_is_queued_for_the_ledger_with_the_fields_the_design_names(tmp_path):
    w = World(tmp_path)
    w.net.up = False
    w.finish(w.svc.start_copy(SERIAL, ["vol:AAAA0001"]))
    queued = ledger_outbox.peek(w.tmp / "outbox.jsonl")
    assert sorted(c["name"] for c in queued) == ["C0001.MP4", "C0002.MP4"]     # the XML is not tracked
    c = queued[0]
    folder = card_of(w.svc.state())["folder"]
    assert c["volume"] == {"serial": "AAAA0001", "label": "CIB_D1", "kind": "ours"}
    assert c["path"].startswith(f"FieldBackup/{folder}/PRIVATE/M4ROOT/CLIP/")
    assert c["tool"] == "field" and c["verified"] == "full" and c["size"] > 0 and isinstance(c["mtime"], int)
    assert w.svc.state()["sync"]["pending"] == 2


def test_offline_nothing_is_lost_and_the_page_says_so(tmp_path):
    w = World(tmp_path)
    w.net.up = False
    w.finish(w.svc.start_copy(SERIAL, ["vol:AAAA0001"]))
    info = w.svc.sync()
    assert info["online"] is False and "could not be reached" in info["error"] and info["pending"] == 2
    assert w.svc.state()["sync"]["online"] is False


def test_when_the_dashboard_answers_the_outbox_is_sent_and_the_mirror_pulled(tmp_path):
    w = World(tmp_path)
    w.net.up = False
    w.finish(w.svc.start_copy(SERIAL, ["vol:AAAA0001"]))
    w.net.up = True
    info = w.svc.sync()
    assert info["online"] is True and info["flushed"] == 2 and info["pending"] == 0
    assert {c["name"] for c in w.net.copies} == {"C0001.MP4", "C0002.MP4"}
    assert any("/ledger/mirror" in url for _, url in w.net.calls)
    assert w.svc.mirror.status()["pulled_at"]
    assert w.svc.state()["sync"]["pending"] == 0


def test_a_copy_still_counts_after_it_has_been_sent_and_before_the_mirror_has_it(tmp_path):
    w = World(tmp_path)
    w.add_folder()
    fid = w.add_folder()
    w.finish(w.svc.start_copy(SERIAL, ["vol:AAAA0001", fid]))
    w.svc.sync()                                                         # sent; the (fake) mirror answers with no rows
    assert card_of(w.svc.state())["verdict"]["safeToFormat"]


def test_sync_without_a_dashboard_says_so_and_does_nothing(tmp_path):
    w = World(tmp_path)
    w.cfg.pop("dashboard_url")
    info = w.svc.sync()
    assert info["online"] is False and "No dashboard" in info["error"]
    assert w.net.calls == []


def test_sync_soon_runs_one_sync_at_a_time(tmp_path):
    w = World(tmp_path)
    assert w.svc.sync_soon() is True
    for _ in range(200):
        if not w.svc.sync_info["running"]:
            break
        import time
        time.sleep(0.02)
    assert w.svc.sync_info["running"] is False and w.svc.sync_info["at"]


def test_the_copier_in_use_is_named(tmp_path):
    w = World(tmp_path)
    assert w.svc.copier_info()["name"] == "built-in copier"
    from test_card_copy import FakeTeraCopy
    w2 = w.build(teracopy_fn=lambda: (FakeTeraCopy(), ""))
    assert w2.copier_info()["name"] == "TeraCopy"


def test_the_page_can_be_switched_off():
    assert field_service.enabled({}) and not field_service.enabled({"field_server_enabled": False})
    assert not field_service.enabled({"field_server_enabled": "off"})


def test_the_state_is_json_able_and_a_big_card_does_not_ship_its_file_list(tmp_path):
    w = World(tmp_path)
    w.finish(w.svc.start_copy(SERIAL, ["vol:AAAA0001"]))
    blob = json.dumps(w.svc.state())
    assert "C0001.MP4" in blob                                          # only inside the at-risk sample / lanes
    assert "files" in card_of(w.svc.state()) and isinstance(card_of(w.svc.state())["files"], int)


def test_checking_a_thousand_file_card_against_the_mirror_is_quick_enough(tmp_path):
    import time

    w = World(tmp_path)
    clip = w.card / "PRIVATE" / "M4ROOT" / "CLIP"
    for i in range(1000):
        (clip / f"X{i:04d}.MP4").write_bytes(b"x" * (100 + i))
    rows = [{"id": i + 10, "volume_id": "vol:AAAA0001", "path": f"T/X{i:04d}.MP4", "name": f"X{i:04d}.MP4", "size": 100 + i, "mtime": None}
            for i in range(1000)]
    w.svc.mirror.apply(rows)
    t0 = time.monotonic()
    st = w.svc.state(refresh=True)
    assert card_of(st)["files"] == 1003
    assert time.monotonic() - t0 < 20
