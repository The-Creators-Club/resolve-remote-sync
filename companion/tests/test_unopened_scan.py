"""CR-383 (2026-11-08): clips only on this computer, in projects nobody has open.

The incident: "Animals - Pangolins and Bears" in the shared library FF5 held
45 music clips linked to ruskin's Desktop, and the out-of-tree popup never
saw them because it only looks at the project OPEN on that machine. These
tests pin the sweep's verdict (who is flagged, who stays silent), the
reminder's cadence, and the report key's "not looked yet" None.

Every library here is injected: conftest's _no_live_project_library guard
keeps the real discovery functions away from the developer's own Resolve log
and the fleet's NAS.
"""

from __future__ import annotations

import logging
from pathlib import Path

import pytest

from ccsync_companion import library
from ccsync_companion import resolve_bridge
from ccsync_companion import unopened_scan as us
from ccsync_companion.app import CompanionApp

PANGOLINS = "Animals - Pangolins and Bears"


@pytest.fixture()
def tree(tmp_path):
    """A sync tree, a project folder in it, and a Desktop beside it."""
    root = tmp_path / "root"
    project = root / "Projects" / "2026" / "Animals" / "Pangolins"
    project.mkdir(parents=True)
    (project / "A001.braw").write_bytes(b"x")
    desktop = tmp_path / "Users" / "user" / "Desktop" / "Music Docs"
    desktop.mkdir(parents=True)
    for n in range(3):
        (desktop / f"track{n}.wav").write_bytes(b"x")
    return {"root": str(root), "project": project, "desktop": desktop}


def _item(path, name="clip"):
    return {"file_path": str(path), "clip_name": name, "bin_path": "Music"}


def _pools(**projects):
    return library.LibraryPools(pools=dict(projects), duplicates=[], no_pool=[])


class Clock:
    def __init__(self):
        self.now = 1000.0

    def __call__(self):
        return self.now


def _scan(tree, pools_by_library, open_project=None, ignored=None, interval=1800.0,
          nag_allowed=True, clock=None, notes=None):
    """An UnopenedScan over injected libraries. `pools_by_library` maps a
    library name to LibraryPools, or to an exception to raise."""
    notes = notes if notes is not None else []
    infos = [library.LibraryInfo(kind="PostgreSQL", name=name, host="10.0.0.1")
             for name in pools_by_library]

    def reader(info):
        value = pools_by_library[info.name]
        if isinstance(value, Exception):
            raise value
        return value

    state = {"open": open_project}
    scan = us.UnopenedScan(
        interval_fn=lambda: interval,
        local_root_fn=lambda: tree["root"],
        canonical_prefix_fn=lambda: "",
        open_project_fn=lambda: state["open"],
        ignored_projects_fn=lambda: ignored or ["Untitled Project", "New Doc"],
        libraries_fn=lambda: infos,
        notify_fn=lambda msg, title: notes.append((msg, title)),
        nag_allowed_fn=lambda: nag_allowed,
        reader=reader,
        clock=clock or Clock(),
        wall_now=lambda: "2026-11-08T10:00:00Z",
    )
    scan._test_state = state
    scan._test_notes = notes
    return scan


def _pangolins(tree, extra=()):
    return [_item(tree["project"] / "A001.braw", "A001.braw")] + [
        _item(tree["desktop"] / f"track{n}.wav", f"track{n}.wav") for n in range(3)
    ] + list(extra)


# ------------------------------------------------------------ the verdict

def test_a_tree_project_with_clips_only_here_is_flagged(tree):
    scan = _scan(tree, {"FF5": _pools(**{PANGOLINS: _pangolins(tree)})})
    found = scan.sweep_once()
    assert [(f.project, f.count, f.library) for f in found] == [(PANGOLINS, 3, "FF5")]
    # The folder the clips sit in, shortened for the balloon.
    assert found[0].where.replace("/", "\\") == "Desktop\\Music Docs"


def test_one_file_cut_in_twice_counts_once(tree):
    twice = _pangolins(tree, extra=[_item(tree["desktop"] / "track0.wav", "track0 copy")])
    scan = _scan(tree, {"FF5": _pools(**{PANGOLINS: twice})})
    assert scan.sweep_once()[0].count == 3


def test_a_personal_project_entirely_off_the_tree_stays_silent(tree):
    """CR-232: footage nobody meant to sync is the editor's own business."""
    personal = [_item(tree["desktop"] / f"track{n}.wav") for n in range(3)]
    scan = _scan(tree, {"FF5": _pools(**{"My Wedding Edit": personal})})
    assert scan.sweep_once() == []
    assert scan.report() == ([], "2026-11-08T10:00:00Z")


def test_a_file_that_is_not_on_this_computer_stays_silent(tree):
    """Only the machine holding the file can fix it: editor A must never be
    told about editor B's Desktop."""
    elsewhere = [_item(tree["project"] / "A001.braw"),
                 _item(r"C:\Users\someone-else\Desktop\not-here-at-all\gone.wav")]
    scan = _scan(tree, {"FF5": _pools(**{PANGOLINS: elsewhere})})
    assert scan.sweep_once() == []


def test_a_clip_in_the_tree_but_not_under_a_project_root_does_not_make_a_tree_project(tree):
    assets = Path(tree["root"]) / "Assets" / "Music"
    assets.mkdir(parents=True)
    (assets / "lib.wav").write_bytes(b"x")
    items = [_item(assets / "lib.wav")] + [
        _item(tree["desktop"] / f"track{n}.wav") for n in range(3)]
    scan = _scan(tree, {"FF5": _pools(**{"Personal": items})})
    assert scan.sweep_once() == []


def test_the_project_open_here_is_left_to_the_watcher(tree):
    scan = _scan(tree, {"FF5": _pools(**{PANGOLINS: _pangolins(tree)})},
                 open_project=PANGOLINS)
    assert scan.sweep_once() == []


def test_scratch_projects_are_skipped(tree):
    scan = _scan(tree, {"FF5": _pools(**{"New Doc 3": _pangolins(tree)})})
    assert scan.sweep_once() == []


def test_findings_are_largest_first_across_libraries(tree):
    small = [_item(tree["project"] / "A001.braw"), _item(tree["desktop"] / "track0.wav")]
    scan = _scan(tree, {"FF5": _pools(**{"Small": small}),
                        "FF4": _pools(**{PANGOLINS: _pangolins(tree)})})
    assert [(f.project, f.count) for f in scan.sweep_once()] == [(PANGOLINS, 3), ("Small", 1)]


def test_a_sweep_that_is_not_ready_keeps_the_previous_answer(tree):
    scan = _scan(tree, {"FF5": _pools(**{PANGOLINS: _pangolins(tree)})})
    scan.sweep_once()
    scan._ready_fn = lambda: False
    assert scan.sweep_once() is None
    assert scan.report()[0] == [{"project": PANGOLINS, "count": 3}]


# ------------------------------------------------------------ unreachable

def test_an_unreachable_library_is_logged_once_and_skipped(tree, caplog):
    scan = _scan(tree, {
        "Dead": library.LibraryUnavailable("cannot open PostgreSQL Dead: timeout"),
        "FF5": _pools(**{PANGOLINS: _pangolins(tree)}),
    })
    with caplog.at_level(logging.WARNING, logger="ccsync.unopened_scan"):
        for _ in range(3):
            found = scan.sweep_once()
    assert [f.project for f in found] == [PANGOLINS]
    assert sum("cannot read" in r.getMessage() for r in caplog.records) == 1


def test_nothing_readable_is_not_a_clean_answer(tree):
    scan = _scan(tree, {"Dead": library.LibraryUnavailable("down")})
    assert scan.sweep_once() is None
    assert scan.report() == (None, None)


def test_a_reader_that_raises_anything_never_escapes(tree):
    scan = _scan(tree, {"FF5": RuntimeError("zstd blew up")})
    assert scan.sweep_once() is None
    scan.tick()                                   # and the loop survives it


# ------------------------------------------------------------- the report

def test_the_report_is_none_until_a_sweep_has_completed(tree):
    scan = _scan(tree, {"FF5": _pools(**{PANGOLINS: _pangolins(tree)})})
    assert scan.report() == (None, None)
    scan.sweep_once()
    entries, at = scan.report()
    assert entries == [{"project": PANGOLINS, "count": 3}]
    assert at == "2026-11-08T10:00:00Z"
    # Names and counts only: no path ever leaves the machine this way.
    assert "Desktop" not in repr(entries)


def test_the_report_is_capped(tree):
    pools = {f"Project {n:02d}": _pangolins(tree) for n in range(30)}
    scan = _scan(tree, {"FF5": _pools(**pools)})
    scan.sweep_once()
    assert len(scan.report()[0]) == us.MAX_REPORTED


def test_switching_the_sweep_off_forgets_the_verdict(tree):
    scan = _scan(tree, {"FF5": _pools(**{PANGOLINS: _pangolins(tree)})})
    scan.tick()
    assert scan.report()[0]
    scan._interval_fn = lambda: 0.0
    scan.tick()
    assert scan.report() == (None, None)


def test_interval_seconds_reads_minutes_and_falls_back_on_garbage():
    assert us.interval_seconds({"unopened_scan_minutes": 30}) == 1800.0
    assert us.interval_seconds({"unopened_scan_minutes": 0}) == 0.0
    assert us.interval_seconds({"unopened_scan_minutes": "soon"}) == 1800.0
    assert us.interval_seconds({"unopened_scan_minutes": -5}) == 1800.0
    assert us.interval_seconds({}) == 1800.0


# ----------------------------------------------------------- the reminder

def test_the_reminder_fires_at_once_then_every_half_hour_until_clean(tree):
    clock = Clock()
    pools = {"FF5": _pools(**{PANGOLINS: _pangolins(tree)})}
    scan = _scan(tree, pools, clock=clock, interval=1800.0)
    notes = scan._test_notes

    scan.tick()
    assert len(notes) == 1
    message, title = notes[0]
    assert f"3 clips in '{PANGOLINS}' are only on this computer" in message
    assert "FIX ALL" in message
    assert "footage only on this computer" in title

    clock.now += 29 * 60
    scan.tick()
    assert len(notes) == 1
    clock.now += 60
    scan.tick()                                   # 30 min: sweeps and reminds
    assert len(notes) == 2

    # Fixed: the next sweep is clean and the reminders stop.
    pools["FF5"] = _pools(**{PANGOLINS: [_item(tree["project"] / "A001.braw")]})
    clock.now += 1800
    scan.tick()
    clock.now += 3600
    scan._next_sweep_at = clock.now + 10_000      # no further sweep in this test
    scan.tick()
    assert len(notes) == 2

    # And a NEW finding is a first finding again: reminded at once.
    pools["FF5"] = _pools(**{PANGOLINS: _pangolins(tree)})
    scan._next_sweep_at = None
    clock.now += 60
    scan.tick()
    assert len(notes) == 3


def test_the_reminder_never_names_the_project_open_now(tree):
    scan = _scan(tree, {"FF5": _pools(**{PANGOLINS: _pangolins(tree)})})
    scan.sweep_once()
    scan._test_state["open"] = PANGOLINS          # opened between two sweeps
    assert scan.maybe_nag() is False
    assert scan.visible() == []
    # ...and the report still says what the last sweep found.
    assert scan.report()[0] == [{"project": PANGOLINS, "count": 3}]


def test_no_reminder_where_there_is_no_fix_all_to_press(tree):
    scan = _scan(tree, {"FF5": _pools(**{PANGOLINS: _pangolins(tree)})}, nag_allowed=False)
    scan.tick()
    assert scan._test_notes == []
    assert scan.report()[0]                       # the report still carries it


def test_the_message_has_no_em_dash_and_fits_a_balloon():
    long_name = "A" * 200
    many = [us.Finding("FF5", long_name, 45, "Desktop\\Music Docs"),
            us.Finding("FF5", "Other", 2)]
    for findings in ([many[0]], many, [us.Finding("FF5", "One", 1)]):
        text = us.nag_message(findings)
        assert "\u2014" not in text and "\u2013" not in text
        assert len(text) <= 250
    assert us.nag_message([us.Finding("FF5", "One", 1)]).startswith("1 clip in 'One' is ")
    assert "1 other project" in us.nag_message(many)


# --------------------------------------------------------------- discovery

def test_discover_libraries_dedupes_by_name_and_applies_overrides(monkeypatch):
    monkeypatch.setattr(library, "postgres_libraries_from_log", lambda: [
        library.LibraryInfo(kind="PostgreSQL", name="FF5", host="100.71.216.3"),
        library.LibraryInfo(kind="PostgreSQL", name="FF4", host="10.0.0.9")])
    monkeypatch.setattr(library, "disk_project_dbs", lambda: [
        ("Local Database", "/x/Reef/Project.db")])
    api = [library.LibraryInfo(kind="PostgreSQL", name="FF5", host="10.1.1.1")]
    found = us.discover_libraries(api, {"library_db_password": "hunter2"})
    assert [(i.kind, i.name, i.host) for i in found] == [
        ("PostgreSQL", "FF5", "10.1.1.1"),        # the API wins over the log
        ("PostgreSQL", "FF4", "10.0.0.9"),
        ("Disk", "Local Database", "")]
    assert {i.password for i in found if i.kind == "PostgreSQL"} == {"hunter2"}
    assert found[2].sqlite_path == "/x/Reef/Project.db"


def test_discover_libraries_never_raises(monkeypatch):
    def boom():
        raise OSError("no log")
    monkeypatch.setattr(library, "postgres_libraries_from_log", boom)
    monkeypatch.setattr(library, "disk_project_dbs", boom)
    assert us.discover_libraries(None, None) == []


# ------------------------------------------------------------- in the app

def _app(tmp_path, **overrides) -> CompanionApp:
    root = tmp_path / "root"
    root.mkdir(parents=True, exist_ok=True)
    cfg = {"editor_name": "owen", "local_root": str(root), "canonical_prefix": "P:\\",
           "remote": "creators_club_sftp", "remote_root": "/mnt/tank/Creators_Club",
           "active_project": "", "poll_interval": 3,
           "log_path": str(tmp_path / "companion.log"), "dashboard_url": "",
           "popup_enabled": True, "sync_enabled": False, "lane_b_enabled": False}
    cfg.update(overrides)
    return CompanionApp(cfg)


def test_resolve_health_says_none_before_the_first_sweep(tmp_path):
    app = _app(tmp_path)
    health = app.resolve_health()
    assert health["unopened_out_of_tree"] is None
    assert health["unopened_scan_at"] is None


def test_resolve_health_carries_the_sweeps_answer(tmp_path):
    app = _app(tmp_path)
    app._unopened_scan._findings = [us.Finding("FF5", PANGOLINS, 45, "Desktop\\Music Docs")]
    app._unopened_scan._scan_at = "2026-11-08T10:00:00Z"
    health = app.sync_guard()["resolve_health"]
    assert health["unopened_out_of_tree"] == [{"project": PANGOLINS, "count": 45}]
    assert health["unopened_scan_at"] == "2026-11-08T10:00:00Z"


def test_the_app_asks_resolve_for_its_libraries_only_on_a_connected_bridge(tmp_path, monkeypatch):
    """CR-68: a background sweep must never be what knocks on Resolve's door."""
    app = _app(tmp_path)
    calls = []

    class Manager:
        def GetDatabaseList(self):
            return [{"DbType": "PostgreSQL", "DbName": "FF5", "IpAddress": "10.1.1.1"}]

    class Resolve:
        def GetProjectManager(self):
            return Manager()

    def connect():
        calls.append("connect")
        return Resolve()

    monkeypatch.setattr(resolve_bridge, "connect", connect)
    monkeypatch.setattr(app.watcher, "bridge_is_connected", lambda: None, raising=False)
    assert app._unopened_scan_libraries() == []
    assert calls == []

    monkeypatch.setattr(app.watcher, "bridge_is_connected", lambda: True, raising=False)
    found = app._unopened_scan_libraries()
    assert calls == ["connect"]
    assert [(i.name, i.host) for i in found] == [("FF5", "10.1.1.1")]


def test_the_sweep_stands_down_when_the_sync_folder_is_unusable(tmp_path):
    app = _app(tmp_path)
    assert app._unopened_scan_ready() is True
    app._root_absent = True
    assert app._unopened_scan_ready() is False


def test_the_tray_line_counts_the_other_projects():
    from ccsync_companion import tray

    assert tray.resolve_count_phrases({"unopened_out_of_tree": None}) == []
    assert tray.resolve_count_phrases({"unopened_out_of_tree": []}) == []
    assert tray.resolve_count_phrases({"unopened_out_of_tree": [
        {"project": PANGOLINS, "count": 45}]}) == ["1 other project with clips only here"]


def test_the_settings_window_names_them(tmp_path):
    from ccsync_companion import settings_window

    app = _app(tmp_path)
    app._unopened_scan._findings = [us.Finding("FF5", PANGOLINS, 45, r"Desktop\Music Docs")]
    app._unopened_scan._scan_at = "2026-11-08T10:00:00Z"
    lines = [getattr(i, "text", "") for i in settings_window._resolve_section(app, {})]
    assert any(f"45 clips in '{PANGOLINS}' are only on this computer" in str(t)
               for t in lines), lines
