"""Regression tests for the second adversarial review of the ledger browser's companion half (2026-11-09).

One section per finding; each was a failing script in the review's folder before the fix.
"""
from __future__ import annotations

import json
import os
import subprocess
import threading
from pathlib import Path

import pytest

from ccsync_companion import ledger_mirror, ledger_outbox as ob, ledger_scan, sorter_cards, sorter_volumes

from test_ledger_scan import Rig, listing, tree, all_rows  # noqa: F401  (Rig is the fake drive + dashboard)

windows_only = pytest.mark.skipif(os.name != "nt", reason="NTFS junctions and the extended-length prefix")


# ---------------------------------------------------------------- 3. junctions are not followed

@windows_only
def test_a_junction_out_of_the_volume_and_a_junction_cycle_are_not_followed(tmp_path):
    vol, outside = tmp_path / "vol", tmp_path / "outside"
    (vol / "Footage").mkdir(parents=True)
    outside.mkdir()
    (outside / "SECRET.mov").write_bytes(b"x" * 10)
    (vol / "Footage" / "A001.mov").write_bytes(b"x" * 10)
    for link, target in (("jout", outside), ("loop", vol / "Footage")):
        subprocess.check_call(["cmd", "/c", "mklink", "/J", str(vol / "Footage" / link), str(target)],
                              stdout=subprocess.DEVNULL)
    try:
        scan, result, sent = listing(vol)
    finally:
        for link in ("jout", "loop"):
            os.rmdir(vol / "Footage" / link)                     # removes the junction, not its target
    assert [r[0] for r in all_rows(sent)] == ["Footage/A001.mov"]
    assert result["links"] == 2 and result["complete"] is True    # skipping a link is not a failure
    assert (outside / "SECRET.mov").exists()


def test_a_symlink_to_a_folder_is_not_followed_either(tmp_path):
    (tmp_path / "vol").mkdir()
    (tmp_path / "out").mkdir()
    (tmp_path / "out" / "x.mov").write_bytes(b"x")
    try:
        os.symlink(tmp_path / "out", tmp_path / "vol" / "ln", target_is_directory=True)
    except (OSError, NotImplementedError):
        pytest.skip("no symlink privilege here")
    _s, _r, sent = listing(tmp_path / "vol")
    assert all_rows(sent) == []


# ---------------------------------------------------------------- 2. incomplete when anything was not listed

def test_a_failed_stat_names_the_folder_and_the_scan_stays_complete(tmp_path, monkeypatch):
    tree(tmp_path, {"ok.mov": 1, "bad.mov": 1})
    real = os.scandir

    class Entry:
        def __init__(self, e):
            self._e, self.name, self.path = e, e.name, e.path

        def is_dir(self, follow_symlinks=True):
            return self._e.is_dir(follow_symlinks=follow_symlinks)

        def is_file(self, follow_symlinks=True):
            return self._e.is_file(follow_symlinks=follow_symlinks)

        def is_symlink(self):
            return self._e.is_symlink()

        def stat(self, follow_symlinks=True):
            if self.name == "bad.mov":
                raise PermissionError(13, "denied")
            return self._e.stat(follow_symlinks=follow_symlinks)

    class Scan:
        def __init__(self, path):
            self._it = real(path)

        def __enter__(self):
            return [Entry(e) for e in self._it.__enter__()]

        def __exit__(self, *a):
            return self._it.__exit__(*a)

    monkeypatch.setattr(ledger_scan.os, "scandir", lambda p: Scan(p))
    _s, result, sent = listing(tmp_path, alive=lambda: True)
    assert [r[0] for r in all_rows(sent)] == ["ok.mov"]
    assert result["complete"] is True and result["unreadable"] == [""]          # the folder it is in: "" = the volume root


def test_the_finish_carries_the_unreadable_folders_and_stays_complete(tmp_path, monkeypatch):
    rig = Rig(tmp_path, {"ok/a.mov": 1, "locked/b.mov": 1})
    real = os.scandir

    def deny(path):
        if str(path).endswith("locked"):
            raise PermissionError(13, "denied")
        return real(path)

    monkeypatch.setattr(ledger_scan.os, "scandir", deny)
    rig.run()
    fin = rig.dash.finish[-1]
    assert fin["complete"] is True and fin["unreadable"] == ["locked"] and fin["unreadableCount"] == 1
    assert rig.dash.results[-1]["ok"] is True


def test_an_unreadable_drive_root_is_named_by_the_empty_string(tmp_path, monkeypatch):
    (tmp_path / "x.mov").write_bytes(b"x")
    real = os.scandir

    def deny_root(path):
        if str(path).replace(chr(92) * 2 + "?" + chr(92), "").rstrip(chr(92) + "/") == str(tmp_path):
            raise PermissionError(13, "denied")
        return real(path)

    monkeypatch.setattr(ledger_scan.os, "scandir", deny_root)
    _s, result, _sent = listing(tmp_path, alive=lambda: True)
    assert result["unreadable"] == [""] and result["complete"] is True      # "" = the whole drive, exempted by the server


def test_the_unreadable_list_is_bounded_but_counted(tmp_path, monkeypatch):
    for i in range(ledger_scan.MAX_UNREADABLE_LISTED + 30):
        (tmp_path / f"d{i:04}").mkdir()
    real = os.scandir

    def deny(path):
        if Path(str(path)).name.startswith("d"):
            raise PermissionError(13, "denied")
        return real(path)

    monkeypatch.setattr(ledger_scan.os, "scandir", deny)
    scan, result, _sent = listing(tmp_path, alive=lambda: True)
    assert len(result["unreadable"]) == ledger_scan.MAX_UNREADABLE_LISTED
    assert result["unreadableCount"] == ledger_scan.MAX_UNREADABLE_LISTED + 30
    # folders past the cut are NOT named, so the server would read their files as gone: that is incomplete
    assert result["complete"] is False and "more than can be listed" in result["reason"]


@windows_only
def test_a_path_past_260_characters_is_listed(tmp_path):
    deep = tmp_path / "vol"
    for _ in range(14):
        deep = deep / ("d" * 20)                                    # > 280 characters of folders
    os.makedirs(ledger_scan.long_path(str(deep)))
    with open(ledger_scan.long_path(str(deep / "A001.braw")), "wb") as fh:
        fh.write(b"x" * 7)
    assert len(str(deep)) > 260
    _s, result, sent = listing(tmp_path / "vol")
    rows = all_rows(sent)
    assert len(rows) == 1 and rows[0][0].endswith("/A001.braw") and rows[0][1] == 7 and result["complete"] is True
    assert ledger_scan.long_path("C:/x").startswith(chr(92) * 2 + "?" + chr(92))
    assert ledger_scan.long_path(ledger_scan.long_path("C:/x")) == ledger_scan.long_path("C:/x")


def test_the_drive_check_is_rate_limited_when_folders_keep_failing(tmp_path, monkeypatch):
    for i in range(300):
        (tmp_path / f"d{i:03}").mkdir()
    real = os.scandir

    def deny(path):
        if Path(str(path)).name.startswith("d"):
            raise PermissionError(13, "denied")
        return real(path)

    monkeypatch.setattr(ledger_scan.os, "scandir", deny)
    calls = []
    _s, result, _sent = listing(tmp_path, alive=lambda: calls.append(1) or True)      # real clock: the whole walk is < 5 s
    assert result["unreadableCount"] == 300 and len(calls) <= 2


# ---------------------------------------------------------------- 5. the attempt token is echoed

def test_the_manifests_attempt_rides_every_post(tmp_path):
    rig = Rig(tmp_path, {"a.braw": 10})
    rig.dash.manifest["attempt"] = "tok-7"
    rig.run()
    assert [c["attempt"] for c in rig.dash.chunks] == ["tok-7"]
    assert rig.dash.finish[-1]["attempt"] == "tok-7"


def test_progress_carries_the_attempt_and_a_manifest_without_one_sends_none(tmp_path):
    rig = Rig(tmp_path, {"a.braw": 10})
    job = ledger_scan.ScanJob(41, {}, "http://dash.example", rig.dash.request, lambda: {}, rig.volumes)
    job.attempt = "tok-9"
    job._post_json("/progress", {"filesDone": 1})
    assert rig.dash.progress[-1]["attempt"] == "tok-9" and rig.dash.progress[-1]["filesDone"] == 1
    (tmp_path / "p").mkdir()
    plain = Rig(tmp_path / "p", {"a.braw": 10})
    plain.run()
    assert "attempt" not in plain.dash.chunks[0] and "attempt" not in plain.dash.finish[-1]


def test_a_409_on_progress_stops_the_scan_as_stale(tmp_path, monkeypatch):
    rig = Rig(tmp_path, {f"d{i}/a.mov": 1 for i in range(3)})
    rig.dash.manifest["attempt"] = "old"
    real = rig.dash.request

    def request(method, url, body, headers, timeout):
        if url.endswith("/progress"):
            return 409, {"detail": "that scan is already finished"}
        return real(method, url, body, headers, timeout)

    rig.dash.request = request
    job = ledger_scan.ScanJob(41, rig.job["inputs"], "http://dash.example", request, lambda: {}, rig.volumes,
                              progress_seconds=0.01)
    release = threading.Event()
    orig = ledger_scan.LedgerScan._send_with_retry

    def held(self, seq, rows):
        release.wait(3)
        return orig(self, seq, rows)

    monkeypatch.setattr(ledger_scan.LedgerScan, "_send_with_retry", held)
    monkeypatch.setattr(ledger_scan, "ALIVE_CHECK_SECONDS", 1e9)
    t = threading.Timer(0.3, release.set)
    t.start()
    # 3 files, a chunk of 1 each: the progress thread has said 409 before the second chunk is walked
    job.rows_per_chunk = 1
    result = job.run()
    t.cancel()
    assert result["complete"] is False and "no longer current" in result["reason"]


def test_a_stale_attempt_409_stops_the_scan_without_retry(tmp_path):
    rig = Rig(tmp_path, {"a.braw": 10})
    rig.dash.manifest["attempt"] = "old"
    rig.dash.chunk_statuses = [409]
    rig.run()
    res = rig.dash.results[-1]
    assert res["ok"] is False and res["retryable"] is False


# ---------------------------------------------------------------- 6. a system volume is never walked from its root

def _system_rig(tmp_path, files, roots):
    rig = Rig(tmp_path, files, roots=roots)
    base = rig.volumes

    def volumes(scope, skip=()):
        return [dict(v, system=True) for v in base(scope, skip)]

    rig.volumes = volumes
    return rig


def test_a_system_volume_is_refused_from_its_root(tmp_path):
    rig = _system_rig(tmp_path, {"Windows/x.mov": 1, "FieldBackup/a.braw": 1}, roots=("",))
    rig.run()
    assert rig.dash.chunks == []
    fin = rig.dash.finish[-1]
    assert fin["complete"] is False and "system drive" in fin["reason"]
    res = rig.dash.results[-1]
    assert res["ok"] is False and res["retryable"] is False


def test_a_system_volume_walks_only_the_roots_a_watch_names(tmp_path):
    rig = _system_rig(tmp_path, {"Windows/x.mov": 1, "FieldBackup/a.braw": 1}, roots=("", "FieldBackup"))
    rig.run()                                                        # the whole-volume root is dropped, the watch stays
    assert [r[0] for c in rig.dash.chunks for r in c["rows"]] == ["FieldBackup/a.braw"]
    assert rig.dash.finish[-1]["complete"] is True


def test_a_non_system_volume_is_unchanged(tmp_path):
    rig = Rig(tmp_path, {"Windows/x.mov": 1, "FieldBackup/a.braw": 1})
    rig.run()
    assert sorted(r[0] for c in rig.dash.chunks for r in c["rows"]) == ["FieldBackup/a.braw", "Windows/x.mov"]


# ---------------------------------------------------------------- 7. virtual drives are not reported

def vol(serial, label="X", fs="NTFS", capacity=10 ** 12, drive="D:"):
    return {"serial": serial, "label": label, "fs": fs, "capacity": capacity, "drive": drive, "root": drive + chr(92),
            "removable": False, "drive_type": "fixed", "system": False, "free": 1}


@pytest.mark.parametrize("v", [
    vol("19831116", "Google Drive", "FAT32", 4 * 1024 ** 4),         # the real one seen on this laptop
    vol("12345678", "Google Drive"), vol("12345678", "My Drive (alex)"), vol("12345678", "OneDrive - Club"),
    vol("12345678", "Dropbox"), vol("12345678", "iCloud Drive"),
    vol("12345678", "Disk", "FAT32", 4 * 1024 ** 4),                  # a made-up FAT32 of 4 TiB
    vol("00000000"), vol(""), vol("19831116", "Whatever"),            # no serial / the denylisted serial
    vol("12345678", "Share", "FUSE"), vol("12345678", "Share", "WebDAV"),
])
def test_virtual_drives_are_recognised(v):
    assert sorter_volumes.is_virtual(v)


@pytest.mark.parametrize("v", [
    vol("6880882B", "CIB_D1", "exFAT", 14 * 10 ** 12), vol("4C603CDC", "OS"), vol("409C181E", "G011", "exFAT"),
    vol("AAAA0001", "Card", "FAT32", 128 * 10 ** 9), vol("AAAA0002", "My Passport"),
])
def test_real_drives_are_kept(v):
    assert not sorter_volumes.is_virtual(v)


def test_the_report_leaves_virtual_drives_out():
    posts = []
    cfg = {"dashboard_url": "http://dash.example", "dashboard_token": "t"}
    r = sorter_volumes.VolumeReporter(
        cfg, request_fn=lambda m, u, b, h, t: posts.append(b) or (200, {}),
        volumes_fn=lambda scope, skip=(): [vol("6880882B", "CIB_D1", "exFAT"),
                                           vol("19831116", "Google Drive", "FAT32", 4 * 1024 ** 4, "I:"),
                                           vol("00000000", "Ghost", "NTFS", 1, "Z:")])
    r.tick()
    assert [v["serial"] for v in posts[0]["volumes"]] == ["6880882B"]


# ---------------------------------------------------------------- 4. the outbox: only a verdict sets copies aside

def copies(n=5):
    return [{"volume": {"serial": "6880882B"}, "path": f"Field/A{i:04d}.braw", "size": 100 + i, "mtime": 1} for i in range(n)]


@pytest.mark.parametrize("status", [300, 301, 302, 303, 307, 308, 401, 403, 404, 408, 409, 410, 415, 418, 429, 500, 502, 503])
def test_nothing_but_400_413_422_sets_copies_aside(tmp_path, status):
    p = tmp_path / ob.FILENAME
    ob.append(copies(), p)
    res = ob.flush(lambda b: (status, None), p)
    assert res["remaining"] == 5 and res["rejected"] == 0
    assert not (tmp_path / ob.REJECTED_FILENAME).exists()


@pytest.mark.parametrize("status", [400, 413, 422])
def test_a_malformed_verdict_does_set_the_batch_aside(tmp_path, status):
    p = tmp_path / ob.FILENAME
    ob.append(copies(), p)
    res = ob.flush(lambda b: (status, None), p)
    assert res["rejected"] == 5 and res["remaining"] == 0 and (tmp_path / ob.REJECTED_FILENAME).exists()


def test_a_303_does_not_drain_a_big_outbox(tmp_path):
    p = tmp_path / ob.FILENAME
    ob.append([{"volume": {"serial": "6880882B"}, "path": f"F/A{i:04d}.braw", "size": 100 + i, "mtime": 1} for i in range(1200)], p)
    calls = []
    res = ob.flush(lambda b: calls.append(len(b)) or (303, None), p)
    assert calls == [500] and res["remaining"] == 1200 and res["rejected"] == 0     # one post, then stop


def test_rejected_copies_can_be_queued_again(tmp_path):
    p = tmp_path / ob.FILENAME
    ob.append(copies(3), p)
    ob.flush(lambda b: (422, None), p)
    assert ob.pending(p) == 0
    assert ob.requeue_rejected(p) == 3 and ob.pending(p) == 3
    assert not (tmp_path / ob.REJECTED_FILENAME).exists()
    assert ob.requeue_rejected(p) == 0                                # nothing left to bring back


def test_a_new_dashboard_version_brings_the_rejected_copies_back(tmp_path):
    p = tmp_path / ob.FILENAME
    ob.append(copies(4), p)
    ob.flush(lambda b: (422, None), p)
    sent = []
    version = {"v": "1.0"}
    f = ob.OutboxFlusher({}, path=p, send=lambda b: sent.append(len(b)) or (200, {"accepted": len(b)}),
                         version_fn=lambda: version["v"])
    assert f.tick() is None and sent == []                            # first sight of a version: no change, nothing waiting
    assert (tmp_path / ob.REJECTED_FILENAME).exists()
    version["v"] = "1.1"
    assert f.tick()["sent"] == 4 and sent == [4]                      # the new dashboard gets them again
    assert not (tmp_path / ob.REJECTED_FILENAME).exists()
    f.tick()
    assert sent == [4]
    # the same version again changes nothing, and a dashboard that names no version is no verdict
    ob.append(copies(2), p)
    ob.flush(lambda b: (422, None), p)
    f2 = ob.OutboxFlusher({}, path=p, send=lambda b: (200, {}), version_fn=lambda: "")
    assert f2.tick() is None and (tmp_path / ob.REJECTED_FILENAME).exists()


# ---------------------------------------------------------------- 8. a bad byte costs a line, not the file

def test_a_non_utf8_byte_is_one_lost_line_not_a_wedged_outbox(tmp_path):
    p = tmp_path / ob.FILENAME
    ob.append(copies(3), p)
    with open(p, "ab") as fh:
        fh.write(b'{"copy":{"volume":{"serial":"X"},"path":"' + bytes([0xE6, 0x97]))     # torn mid-character
    assert ob.pending(p) == 3
    assert ob.append([{"volume": {"serial": "AB"}, "path": "x/new.braw", "size": 5}], p) == 1
    assert ob.pending(p) == 4
    out = ob.flush(lambda b: (200, {"accepted": len(b)}), p)
    assert out["sent"] == 4 and out["remaining"] == 0


def test_a_bad_byte_in_the_middle_skips_only_that_line(tmp_path):
    p = tmp_path / ob.FILENAME
    ob.append(copies(2), p)
    data = p.read_bytes().split(b"\n")
    p.write_bytes(data[0] + b"\n\xff\xfe garbage\n" + data[1] + b"\n")
    assert ob.pending(p) == 2


def test_the_rewrite_temp_name_is_unique_per_process_and_thread(tmp_path, monkeypatch):
    seen = []
    real = os.replace
    monkeypatch.setattr(ob.os, "replace", lambda a, b: (seen.append(Path(a).name), real(a, b))[1])
    p = tmp_path / ob.FILENAME
    ob.append(copies(2), p)
    ob._write_all(p, ob._read(p))
    t = threading.Thread(target=lambda: ob._write_all(p, ob._read(p)))
    t.start()
    t.join()
    assert len(seen) == 2 and seen[0] != seen[1] and all(str(os.getpid()) in n for n in seen)


# ---------------------------------------------------------------- 11. the mirror drops volumes it no longer pulls

def test_rows_of_a_volume_no_longer_pulled_are_dropped(tmp_path):
    T0 = 1_786_236_852_123
    rows = [[1, "a001.braw", 5, T0, "vol:AAAA", "Trip/A001.braw", "master", "full", 0, 0],
            [2, "a001.braw", 5, T0, "nas:thecreatorspool", "P/A001.braw", "master", "full", 0, 0]]
    cols = ["id", "name_lc", "size", "mtime", "volume_id", "path", "role", "verified", "missing", "gone"]
    asked = []

    def req(method, url, body, headers, timeout):
        asked.append(url)
        want = url.split("volumes=")[1].split("&")[0].replace("%2C", ",").split(",")
        mine = [r for r in rows if r[4] in want]
        return 200, {"cols": cols, "rows": mine, "cursor": f"9:{len(mine)}", "more": False,
                     "volumes": [{"id": v, "label": v, "kind": "ours"} for v in want]}

    m = ledger_mirror.LedgerMirror({"dashboard_url": "http://x", "dashboard_token": "t"},
                                   path=tmp_path / "m.sqlite", request_fn=req)
    m.pull(["vol:AAAA", "nas:thecreatorspool"])
    assert m.volumes_holding("A001.braw", 5, T0) == ["vol:AAAA", "nas:thecreatorspool"]
    # 2026-11-11 (audit comp-field-7): a drive that is merely AWAY keeps its rows and stays in the
    # pull, so "a copy on a drive that is away is believed" holds. This test used to assert the
    # opposite: unplugging a field drive deleted its rows, and a card copied to two drives dropped
    # to one copy the moment one went into the bag.
    m.pull(["nas:thecreatorspool"])                                    # the drive went into the bag
    assert m.volumes_holding("A001.braw", 5, T0) == ["vol:AAAA", "nas:thecreatorspool"]
    assert "vol:AAAA" in asked[-1]
    # ...and a volume the caller says is not worth keeping (a camera card) IS dropped, rows and all
    m.pull(["nas:thecreatorspool"], keep=lambda vid: vid != "vol:AAAA")
    assert m.volumes_holding("A001.braw", 5, T0) == ["nas:thecreatorspool"]
    assert set(m.volume_info()) == {"nas:thecreatorspool"} and m.status()["rows"] == 1


def test_a_pull_that_cannot_reach_the_dashboard_keeps_everything_even_for_a_new_set(tmp_path):
    m = ledger_mirror.LedgerMirror({"dashboard_url": "http://x", "dashboard_token": "t"}, path=tmp_path / "m.sqlite",
                                   request_fn=lambda *a: (_ for _ in ()).throw(OSError("no network in the tent")))
    m.apply([{"id": 1, "volume_id": "vol:AAAA", "path": "p/a.mov", "name": "a.mov", "size": 3, "mtime": 1}])
    assert m.pull(["nas:x"])["ok"] is False
    assert m.where("a.mov", 3)                                          # not dropped until the dashboard has answered
