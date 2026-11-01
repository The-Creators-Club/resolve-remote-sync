"""`lane_b_originals_down`: docs/SELECTIVE_ORIGINALS.md sections 4.2, 4.3, 11, 12.

The companion list from section 11: the argv is `copy` with
`--ignore-existing` and never a filter flag, every list entry passes the
Python rules, a name absent from the NAS listing never reaches the list, the
NFC/NFD spellings match (CR-90), the disk floor parks it, lane B's filter is
unchanged, lane A's exclude hook receives the names, the drive reminder and
the power guards see the lane, and an unknown `originals` shape fails closed.
No real rclone, no Resolve.
"""

from __future__ import annotations

import json
import threading
import unicodedata
from pathlib import Path
from types import SimpleNamespace

import pytest

from ccsync_companion import drive_reminder
from ccsync_companion import shutdown_guard
from ccsync_companion import tray
from ccsync_companion.sync import lane_guard
from ccsync_companion.sync import originals_lane as ol
from ccsync_companion.sync import rclone_lane
from ccsync_companion.sync.base import (
    STATE_ERROR,
    STATE_IDLE,
    STATE_PAUSED,
    STATE_SYNCING,
    LaneStatus,
)

PROJECT = "2026/Beyond Nights"
NAME_NFC = unicodedata.normalize("NFC", "Matej Šimalčík")
NAME_NFD = unicodedata.normalize("NFD", "Matej Šimalčík")
FILTER_FLAGS = ("--filter", "--filter-from", "--include", "--include-from",
                "--exclude", "--exclude-from", "--min-age", "--max-age",
                "--min-size", "--max-size", "--files-from", "--exclude-if-present",
                "--delete", "--ignore-case")


def _cfg(tmp_path: Path) -> dict:
    root = tmp_path / "root"
    root.mkdir(exist_ok=True)
    return {"local_root": str(root), "remote": "nas", "remote_root": "/mnt/tank/tree",
            "rclone_path": "rclone"}


def _item(originals, slug="beyond-nights", rel=PROJECT, mode="full"):
    item = {"slug": slug, "rel_path": rel, "position": 0, "sync_mode": mode}
    if originals is not ...:
        item["originals"] = originals
    return item


def _listing(files: dict) -> str:
    return "".join(f"{size};2026-10-30 12:00:00;{rel}\n" for rel, size in files.items())


class FakeProc:
    """A finished rclone: it writes every listed file into dest, then says
    `Copied (new)` for each, exactly as the real JSON log does."""

    def __init__(self, cmd, sizes, code=0, land=True, hold=None):
        self.cmd = cmd
        self.killed = False
        self._code = code
        self._hold = hold
        list_file = Path(cmd[cmd.index("--files-from-raw") + 1])
        self.listed = list_file.read_text(encoding="utf-8").splitlines()
        dest = Path(cmd[3])
        lines = []
        for rel in self.listed:
            if land:
                target = dest.joinpath(*rel.split("/"))
                target.parent.mkdir(parents=True, exist_ok=True)
                target.write_bytes(b"x" * sizes.get(rel, 1))
                lines.append(json.dumps({"level": "info", "msg": "Copied (new)",
                                         "object": rel}) + "\n")
        lines.append(json.dumps({"level": "notice", "msg": "stats", "stats": {
            "bytes": sum(sizes.get(r, 1) for r in self.listed), "transferring": []}}) + "\n")
        self.stderr = iter(lines)

    def wait(self, timeout=None):
        if self._hold is not None and not self.killed:
            if not self._hold.wait(timeout or 0):
                import subprocess
                raise subprocess.TimeoutExpired("rclone", timeout)
        return -9 if self.killed else self._code

    def kill(self):
        self.killed = True
        if self._hold is not None:
            self._hold.set()


def _lane(tmp_path, selection, nas_files, *, popen=None, free=4 * 1024**4,
          floor_cfg=None, halted=False, refusal=None):
    cfg = _cfg(tmp_path)
    spawned: list[FakeProc] = []

    def _popen(cmd, **kwargs):
        proc = (popen or (lambda c: FakeProc(c, nas_files)))(cmd)
        spawned.append(proc)
        return proc

    listings: list[list[str]] = []

    def _list(cmd, timeout):
        listings.append(cmd)
        return _listing(nas_files)

    floor = lane_guard.DiskFloorLatch(tmp_path / "state" / "floor.json",
                                      floor_cfg or {"lane_b_min_free_bytes": 0})
    lane = ol.OriginalsDownLane(
        cfg, tmp_path / "state", selection_fn=lambda: selection,
        disk_floor=floor, halted_fn=lambda: halted,
        remote_list_fn=_list, popen_factory=_popen,
        free_bytes_fn=lambda path: free,
        refusal_fn=lambda c, dest: refusal,
    )
    return lane, spawned, listings, cfg


# -- the argv -----------------------------------------------------------------

def test_argv_is_copy_ignore_existing_and_never_a_filter_flag(tmp_path):
    cfg = _cfg(tmp_path)
    cmd = ol.build_originals_command(cfg, PROJECT, cfg["local_root"], tmp_path / "l.txt")
    assert cmd[1] == "copy"
    assert "sync" not in cmd and "move" not in cmd
    assert "--ignore-existing" in cmd
    assert "--no-traverse" in cmd
    assert cmd[cmd.index("--files-from-raw") + 1] == str(tmp_path / "l.txt")
    assert cmd[cmd.index("--transfers") + 1] == "2"
    assert cmd[cmd.index("--partial-suffix") + 1] == ol.ORIGINALS_PARTIAL_SUFFIX
    assert ol.ORIGINALS_PARTIAL_SUFFIX.endswith(".partial")
    assert len(ol.ORIGINALS_PARTIAL_SUFFIX) <= 16
    assert "--max-duration" in cmd
    for arg in cmd:
        assert not any(arg == flag or arg.startswith(flag + "=") for flag in FILTER_FLAGS), arg
    assert cmd[2] == "nas:/mnt/tank/tree/Projects/2026/Beyond Nights"
    assert cmd[3] == str(Path(cfg["local_root"]) / "Projects" / "2026" / "Beyond Nights")


def test_argv_reads_through_the_download_route(tmp_path, monkeypatch):
    cfg = _cfg(tmp_path)
    monkeypatch.setattr(rclone_lane, "down_route", lambda c: rclone_lane.DownRoute(
        "tunnel", "/", rclone_lane.VIA_REMOTE_DOWN))
    cmd = ol.build_originals_command(cfg, PROJECT, cfg["local_root"], tmp_path / "l.txt")
    # rclone_lane._join_remote_path: the same join lane B uses on this route.
    assert cmd[2] == "tunnel:Projects/2026/Beyond Nights"
    assert "--disable-http2" in cmd


# -- the Python rules ---------------------------------------------------------

@pytest.mark.parametrize("rel", [
    "Footage/A001.braw", "A001.MOV", f"{NAME_NFC}/C0001.MP4", "Day 1/Cam A/clip;1.mxf",
])
def test_rule_accepts_originals(rel):
    assert ol.list_rule_reason(rel) is None


@pytest.mark.parametrize("rel", [
    "Footage/Proxy/A001.mov", "proxy/A001.mov", "Footage/A001.braw.partial",
    "Footage/A001.mov.orig.partial", ".ccsync-trash/x/A001.mov", "Footage/._A001.mov",
    "Footage/.stversions/A001.mov", "Audio/zoom.wav", "Footage/notes.txt",
    "../outside.mov", "/abs/A001.mov", "C:/x/A001.mov", "Footage\\A001.mov",
    "Footage//A001.mov", "", ".ccsync-move-1/A001.mov", "Footage/A001.tmp",
])
def test_rule_refuses_everything_lane_b_and_a_would_filter(rel):
    assert ol.list_rule_reason(rel) is not None


def test_every_list_entry_passes_the_rules_and_absent_names_never_reach_it(tmp_path):
    nas = {
        "Footage Lusty/A001.braw": 100,
        "Footage Lusty/A002.braw": 200,
        "Footage Lusty/Proxy/A001.mov": 5,
        "Footage Lusty/A003.braw.partial": 7,
        ".ccsync-trash/old/A009.braw": 9,
        "Audio/zoom.wav": 3,
    }
    wanted = list(nas) + ["Footage Lusty/GONE.braw"]
    lane, spawned, listings, _ = _lane(tmp_path, [_item(wanted)], nas)
    lane.cycle()
    assert len(spawned) == 1
    listed = spawned[0].listed
    assert sorted(listed) == ["Footage Lusty/A001.braw", "Footage Lusty/A002.braw"]
    assert all(ol.list_rule_reason(rel) is None for rel in listed)
    assert "Footage Lusty/GONE.braw" not in listed
    # The NAS was listed for this run, recursively, under the project.
    assert listings and listings[0][-1] == "nas:/mnt/tank/tree/Projects/2026/Beyond Nights"
    assert "-R" in listings[0]


def test_nfd_and_nfc_spellings_match_and_the_nas_spelling_is_listed(tmp_path):
    nas_rel = f"{NAME_NFD}/A001.braw"
    wanted_rel = f"{NAME_NFC}/A001.braw"
    assert nas_rel != wanted_rel
    lane, spawned, _, _ = _lane(tmp_path, [_item([wanted_rel])], {nas_rel: 10})
    lane.cycle()
    assert spawned and spawned[0].listed == [nas_rel]


def test_a_file_already_here_is_skipped_and_a_different_one_left_alone(tmp_path):
    nas = {"F/same.braw": 4, "F/differs.braw": 4, "F/new.braw": 4}
    lane, spawned, _, cfg = _lane(tmp_path, [_item(list(nas))], nas)
    base = Path(cfg["local_root"]) / "Projects" / "2026" / "Beyond Nights" / "F"
    base.mkdir(parents=True)
    (base / "same.braw").write_bytes(b"1234")
    (base / "differs.braw").write_bytes(b"123456")
    lane.cycle()
    assert spawned[0].listed == ["F/new.braw"]
    assert (base / "differs.braw").read_bytes() == b"123456"


def test_nothing_missing_locally_lists_nothing_and_runs_nothing(tmp_path):
    nas = {"F/a.braw": 1}
    lane, spawned, listings, cfg = _lane(tmp_path, [_item(list(nas))], nas)
    base = Path(cfg["local_root"]) / "Projects" / "2026" / "Beyond Nights" / "F"
    base.mkdir(parents=True)
    (base / "a.braw").write_bytes(b"1")
    lane.cycle()
    assert not listings and not spawned
    assert lane.status().state == STATE_IDLE


# -- fail closed --------------------------------------------------------------

@pytest.mark.parametrize("originals", ["F/a.braw", [1, 2], {"F/a.braw": 1}, [None], ...])
def test_an_unknown_or_absent_originals_shape_downloads_nothing(tmp_path, originals):
    lane, spawned, listings, _ = _lane(tmp_path, [_item(originals)], {"F/a.braw": 1})
    lane.cycle()
    assert not spawned and not listings
    assert lane.status().state == STATE_IDLE


def test_an_upload_only_tick_brings_nothing_down(tmp_path):
    lane, spawned, _, _ = _lane(tmp_path, [_item(["F/a.braw"], mode="upload_only")],
                                {"F/a.braw": 1})
    lane.cycle()
    assert not spawned


def test_an_unknown_sync_mode_brings_nothing_down(tmp_path):
    lane, spawned, _, _ = _lane(tmp_path, [_item(["F/a.braw"], mode="later")],
                                {"F/a.braw": 1})
    lane.cycle()
    assert not spawned


# -- the guards ---------------------------------------------------------------

def test_the_shared_disk_floor_parks_it(tmp_path):
    lane, spawned, _, _ = _lane(tmp_path, [_item(["F/a.braw"])], {"F/a.braw": 1},
                                free=1 * 1024**3,
                                floor_cfg={"lane_b_min_free_bytes": 20 * 1024**3})
    lane.cycle()
    status = lane.status()
    assert not spawned
    assert status.state == STATE_PAUSED
    assert "(disk)" in status.detail
    # The SAME latch lane B reads: it is parked for proxies too.
    assert lane.disk_floor.parked


def test_a_run_that_would_not_fit_above_the_floor_is_refused_naming_both_numbers(tmp_path):
    lane, spawned, _, _ = _lane(tmp_path, [_item(["F/a.braw"])], {"F/a.braw": 50 * 1024**3},
                                free=60 * 1024**3,
                                floor_cfg={"lane_b_min_free_bytes": 20 * 1024**3})
    lane.cycle()
    status = lane.status()
    assert not spawned
    assert status.state == STATE_PAUSED
    assert "50.0 GB" in status.detail and "40.0 GB" in status.detail
    assert not lane.disk_floor.parked


def test_a_halt_parks_it(tmp_path):
    lane, spawned, listings, _ = _lane(tmp_path, [_item(["F/a.braw"])], {"F/a.braw": 1},
                                       halted=True)
    lane.cycle()
    assert not spawned and not listings
    assert lane.status().state == STATE_PAUSED


def test_the_trays_pause_parks_it(tmp_path):
    lane, spawned, listings, _ = _lane(tmp_path, [_item(["F/a.braw"])], {"F/a.braw": 1})
    lane._paused_fn = lambda: True
    lane.cycle()
    assert not spawned and not listings
    assert lane.status().state == STATE_PAUSED
    assert "paused" in lane.status().detail


def test_the_root_guard_refusal_parks_it(tmp_path):
    lane, spawned, _, _ = _lane(tmp_path, [_item(["F/a.braw"])], {"F/a.braw": 1},
                                refusal="this computer's tree isn't mounted right now")
    lane.cycle()
    assert not spawned
    assert lane.status().state == STATE_PAUSED
    assert "mounted" in lane.status().detail


def test_a_failed_listing_is_an_error_not_a_download(tmp_path):
    lane, spawned, _, _ = _lane(tmp_path, [_item(["F/a.braw"])], {"F/a.braw": 1})
    lane._remote_list_fn = lambda cmd, timeout: None
    lane.cycle()
    assert not spawned
    assert lane.status().state == STATE_ERROR


# -- the run ------------------------------------------------------------------

def test_a_run_lands_files_and_writes_the_ledger_atomically(tmp_path):
    nas = {"F/a.braw": 3, "F/b.braw": 5}
    lane, spawned, _, cfg = _lane(tmp_path, [_item(list(nas))], nas)
    lane.cycle()
    assert len(spawned) == 1
    ledger = json.loads((tmp_path / "state" / ol.LEDGER_FILENAME).read_text(encoding="utf-8"))
    rows = sorted(ledger["files"].values(), key=lambda r: r["rel"])
    assert [r["rel"] for r in rows] == ["F/a.braw", "F/b.braw"]
    assert [r["size"] for r in rows] == [3, 5]
    assert all(r["nas_mtime"] == "2026-10-30 12:00:00" and r["arrived_at"] for r in rows)
    assert not list((tmp_path / "state").glob("originals.json.*.tmp"))
    assert not list((tmp_path / "state").glob("originals_*.txt")), "the list file is removed"
    status = lane.status()
    assert status.state == STATE_IDLE
    assert status.last_sync is not None


def test_lane_a_exclude_hook_receives_in_flight_and_just_landed_names(tmp_path):
    nas = {f"{NAME_NFC}/a.braw": 3}
    seen_during: list[list[str]] = []
    holder = {}

    def _popen(cmd):
        seen_during.append(holder["lane"].lane_a_excludes("Projects/2026/Beyond Nights"))
        return FakeProc(cmd, nas)

    lane, _spawned, _, _ = _lane(tmp_path, [_item(list(nas))], nas, popen=_popen)
    holder["lane"] = lane
    lane.cycle()
    nfc_rel = f"{NAME_NFC}/a.braw"
    nfd_rel = unicodedata.normalize("NFD", nfc_rel)
    assert nfc_rel in seen_during[0] and nfd_rel in seen_during[0]
    # After the run: just landed, still excluded, relative to whatever root asks.
    assert nfc_rel in lane.lane_a_excludes("Projects/2026/Beyond Nights")
    assert nfc_rel in lane.lane_a_excludes("2026/Beyond Nights")
    assert f"Projects/2026/Beyond Nights/{nfc_rel}" in lane.lane_a_excludes(None)
    assert lane.lane_a_excludes("Projects/2026/Other") == []
    # ...and not for ever.
    lane._clock = lambda: 10**12
    assert lane.lane_a_excludes(None) == []


def test_the_app_hook_hands_lane_a_both_sources():
    from ccsync_companion.app import CompanionApp

    fake = SimpleNamespace(
        file_moves=SimpleNamespace(recent_excludes=lambda sub: ["moved.mov"]),
        _originals_lane=SimpleNamespace(lane_a_excludes=lambda sub: ["pulled.braw", "moved.mov"]),
    )
    assert CompanionApp._lane_a_extra_excludes(fake, "Projects/x") == ["moved.mov", "pulled.braw"]


def _app_cfg(tmp_path, **over):
    root = tmp_path / "root"
    root.mkdir(parents=True, exist_ok=True)
    cfg = {"editor_name": "owen", "local_root": str(root), "canonical_prefix": "P:\\",
           "remote": "creators_club_sftp", "remote_root": "/mnt/tank/Creators_Club",
           "active_project": "", "poll_interval": 3,
           "log_path": str(tmp_path / "companion.log"),
           "dashboard_url": "http://dash.example.com", "popup_enabled": True,
           "sync_enabled": False, "lane_b_enabled": True}
    cfg.update(over)
    return cfg


def test_a_managed_app_carries_the_lane_the_hook_and_the_inbox(tmp_path):
    from ccsync_companion.app import CompanionApp

    app = CompanionApp(_app_cfg(tmp_path))
    names = [lane.name for lane in app.lanes]
    assert names[-1] == ol.LANE_NAME and names.count(ol.LANE_NAME) == 1
    assert ol.LANE_NAME in [s.name for s in app.lane_statuses()]
    assert app.sequencer.on_selection == app._originals_lane.note_selection
    assert app.originals_inbox is not None
    # The disk floor is lane B's own object, not a copy (4.2).
    assert app._originals_lane.disk_floor is app.disk_floor is app._lane_b.disk_floor


def test_a_machine_without_lane_b_has_no_originals_lane(tmp_path):
    from ccsync_companion.app import CompanionApp

    app = CompanionApp(_app_cfg(tmp_path, lane_b_enabled=False))
    assert ol.LANE_NAME not in [lane.name for lane in app.lanes]


def test_un_picking_stops_the_download_and_keeps_the_files(tmp_path):
    nas = {"F/a.braw": 3}
    hold = threading.Event()
    procs = []

    def _popen(cmd):
        proc = FakeProc(cmd, nas, land=False, hold=hold)
        procs.append(proc)
        return proc

    selection = [_item(list(nas))]
    lane, _spawned, _, cfg = _lane(tmp_path, selection, nas, popen=_popen)
    keep = Path(cfg["local_root"]) / "Projects" / "2026" / "Beyond Nights" / "kept.braw"
    keep.parent.mkdir(parents=True)
    keep.write_bytes(b"k")
    worker = threading.Thread(target=lane.cycle)
    worker.start()
    for _ in range(200):
        if procs and lane._proc is not None:
            break
        threading.Event().wait(0.01)
    lane.note_selection([_item([])])
    worker.join(timeout=10)
    assert not worker.is_alive()
    assert procs[0].killed
    assert keep.exists(), "un-picking never deletes"
    assert lane.status().state in (STATE_IDLE, STATE_PAUSED)


def test_a_pick_change_wakes_the_lane(tmp_path):
    lane, _s, _l, _ = _lane(tmp_path, [], {})
    lane._wake.clear()
    lane.note_selection([_item(["F/a.braw"])])
    assert lane._wake.is_set()
    lane._wake.clear()
    lane.note_selection([_item(["F/a.braw"])])
    assert not lane._wake.is_set(), "only a CHANGE wakes it"


def test_the_sequencer_hands_every_selection_read_to_the_hook():
    from ccsync_companion.sync import sequencer as seq_mod

    got = []
    fake = SimpleNamespace(
        selection=SimpleNamespace(get=lambda: ([{"slug": "s"}], "live")),
        _now=lambda: 0.0, on_selection=got.append, _selection_cache=None)
    assert seq_mod.Sequencer._selection_get(fake) == ([{"slug": "s"}], "live")
    assert got == [[{"slug": "s"}]]
    fake.on_selection = lambda sel: 1 / 0
    assert seq_mod.Sequencer._selection_get(fake)[1] == "live", "a broken hook costs nothing"


# -- lane B is untouched ------------------------------------------------------

def test_lane_b_filter_is_unchanged():
    assert rclone_lane.build_filter_rules_down() == [
        "- ._*",
        "- /.ccsync-trash/**",
        "- *.tmp", "- *.lock", "- *.partial",
        "- *.part",
        "- *.ytdl",
        "- .ccsync-move-*",
        "+ /Proxy/",
        "+ /Proxy/**",
        "+ **/Proxy/",
        "+ **/Proxy/**",
        "- **",
    ]


# -- everything that reads lane statuses sees it ------------------------------

def _syncing_status():
    return LaneStatus(name=ol.LANE_NAME, state=STATE_SYNCING, transferring=2, queued=10,
                      bytes_done=10, bytes_total=1000,
                      detail=ol.progress_sentence(12, 80, 140 * 1024**3))


def test_drive_reminder_names_it_and_does_not_recur_for_it():
    work = drive_reminder.unfinished_work([_syncing_status()])
    assert work is not None
    assert work.items == ["2 original downloads"]
    assert ol.LANE_NAME in drive_reminder.DOWNLOAD_LANES
    assert drive_reminder.owes_an_upload(work.lanes) is False
    assert drive_reminder.owes_an_upload(None, work.summary()) is False


def test_the_power_guards_keep_the_pc_awake_for_it():
    status = _syncing_status()
    assert shutdown_guard.busy_lanes([status]) == [status]
    tracker = shutdown_guard.PendingTracker()
    assert [s.name for s in tracker.live_busy([status])] == [ol.LANE_NAME]


def test_the_tray_line_reads_the_lanes_sentence():
    status = _syncing_status()
    line = tray.originals_line([status])
    assert line == "Bringing originals: 12 of 80, 140.0 GB to go"
    assert "\u2014" not in line
    status.state = STATE_IDLE
    assert tray.originals_line([status]) is None
    assert tray.lane_label(ol.LANE_NAME) != ol.LANE_NAME.replace("_", " ")


def test_its_status_is_a_lane_status_the_report_can_copy(tmp_path):
    lane, _s, _l, _ = _lane(tmp_path, [], {})
    status = lane.status()
    assert isinstance(status, LaneStatus)
    copy = LaneStatus(**vars(status))
    assert copy.name == "lane_b_originals_down"
    assert copy.transfers == [] and copy.current_project is None
    # app.py stamps every lane's detail through these two.
    with lane._lock:
        lane._status.detail = "sync disabled"
    assert lane.status().detail == "sync disabled"
