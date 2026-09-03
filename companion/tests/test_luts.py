"""luts: registering the shared library with Resolve, and finding strays."""
from __future__ import annotations

from pathlib import Path

import pytest

from ccsync_companion import luts
from ccsync_companion import resolve_prefs as rp


class FakePrefs:
    """A ResolvePrefs stand-in. Tracks what was asked of it."""

    def __init__(self, existing=None, add_result=rp.OK):
        self.locations = list(existing or [])
        self.add_result = add_result
        self.added: list[str] = []

    def has_lut_location(self, path):
        want = path.replace("\\", "/").rstrip("/").lower()
        return any(p.replace("\\", "/").rstrip("/").lower() == want for p in self.locations)

    def add_lut_location(self, path, backup_suffix=""):
        self.added.append(path)
        if self.add_result == rp.OK:
            self.locations.append(path)
        return self.add_result

    def lut_locations(self):
        return list(self.locations)


def _library(tmp_path: Path) -> Path:
    library = tmp_path / "root" / "Assets" / "Luts"
    library.mkdir(parents=True)
    return library


def _manager(tmp_path, prefs=None, cfg=None, running=False, log_path=None):
    # running=False by default so no test reaches the real tasklist/Resolve
    # through the stale-index repair -- that path talks to a live Resolve.
    return luts.LutLinkManager(
        cfg if cfg is not None else {},
        tmp_path / "root",
        prefs_factory=lambda: prefs or FakePrefs(),
        refresh_fn=lambda: True,
        log_path=log_path,
        running_fn=lambda: running,
    )


# -- the location string ---------------------------------------------------

def test_windows_uses_the_canonical_prefix(tmp_path):
    """Every Windows editor writes the SAME string, which is what makes a
    LUT applied on one machine resolvable on the next."""
    assert luts.library_location_string(
        {"canonical_prefix": "P:\\"}, tmp_path, windows=True
    ) == "P:\\Assets\\Luts"


def test_non_windows_uses_the_real_local_path(tmp_path):
    """A Mac has no P: -- the Mapped Mount preference covers media paths,
    not this one."""
    result = luts.library_location_string(
        {"canonical_prefix": "P:\\"}, tmp_path, windows=False
    )
    assert result == str(tmp_path / "Assets" / "Luts")


def test_override_wins(tmp_path):
    assert luts.library_location_string(
        {"canonical_prefix": "P:\\", "lut_location_override": "Q:\\Luts"},
        tmp_path, windows=True,
    ) == "Q:\\Luts"


# -- check() ---------------------------------------------------------------

def test_adds_the_location_when_the_library_exists(tmp_path):
    _library(tmp_path)
    prefs = FakePrefs()
    result = _manager(tmp_path, prefs).check()
    assert result["changed"] is True
    assert len(prefs.added) == 1


def test_waits_for_the_library_to_sync(tmp_path):
    """Pointing Resolve at a directory that is not there yet is worse than
    waiting: the entry would sit in the UI resolving to nothing."""
    prefs = FakePrefs()
    result = _manager(tmp_path, prefs).check()   # no library on disk
    assert result["status"] == "no-library"
    assert prefs.added == []


def test_is_a_no_op_once_the_location_is_present(tmp_path):
    _library(tmp_path)
    prefs = FakePrefs(existing=["P:\\Assets\\Luts"])
    manager = luts.LutLinkManager(
        {"canonical_prefix": "P:\\", "lut_location_override": "P:\\Assets\\Luts"},
        tmp_path / "root",
        prefs_factory=lambda: prefs,
        running_fn=lambda: False,
    )
    result = manager.check()
    assert result["changed"] is False
    assert prefs.added == []


def test_reports_resolve_running_without_failing(tmp_path):
    _library(tmp_path)
    prefs = FakePrefs(add_result=rp.RESOLVE_RUNNING)
    result = _manager(tmp_path, prefs).check()
    assert result["status"] == rp.RESOLVE_RUNNING
    assert result["changed"] is False
    assert "closed" in result["message"]


def test_disabled_does_nothing(tmp_path):
    _library(tmp_path)
    prefs = FakePrefs()
    manager = _manager(tmp_path, prefs, cfg={"lut_sync_enabled": False})
    assert manager.check()["status"] == "disabled"
    assert prefs.added == []


# -- strays ----------------------------------------------------------------

def test_finds_a_lut_the_library_does_not_have(tmp_path):
    library = _library(tmp_path)
    (library / "Editor2").mkdir()
    (library / "Editor2" / "shared.cube").write_text("x" * 10)

    lut_dir = tmp_path / "resolve-lut"
    lut_dir.mkdir()
    (lut_dir / "mine.cube").write_text("y" * 20)

    found = luts.stray_luts([lut_dir], library)
    assert [f["name"] for f in found] == ["mine.cube"]


def test_matches_by_basename_so_a_regrouped_lut_is_not_offered_again(tmp_path):
    """The library keeps LUTs in pack folders; an editor's copy is often
    loose. Same name and size means same LUT -- prompting forever would be
    noise."""
    library = _library(tmp_path)
    (library / "Editor2").mkdir()
    (library / "Editor2" / "CC Base.cube").write_text("x" * 10)

    lut_dir = tmp_path / "resolve-lut"
    lut_dir.mkdir()
    (lut_dir / "CC Base.cube").write_text("x" * 10)

    assert luts.stray_luts([lut_dir], library) == []


def test_ignores_non_lut_files_and_dctls(tmp_path):
    """.dctl is excluded deliberately: Resolve loads DCTLs only from its own
    LUT/DCTL directory, never from an additional LUT location, so copying one
    into the library puts it where Resolve does not look."""
    library = _library(tmp_path)
    lut_dir = tmp_path / "resolve-lut"
    (lut_dir / "DCTL").mkdir(parents=True)
    (lut_dir / "DCTL" / "thing.dctl").write_text("code")
    (lut_dir / "readme.txt").write_text("hi")

    assert luts.stray_luts([lut_dir], library) == []


def test_never_offers_the_library_back_to_itself(tmp_path):
    library = _library(tmp_path)
    (library / "a.cube").write_text("x")
    assert luts.stray_luts([library], library) == []


def test_a_sibling_directory_that_merely_extends_the_library_path_is_not_the_library(
    tmp_path,
):
    """COMP-GUARD-6: the containment test was a bare startswith, so
    "…/Assets/Luts Local" read as INSIDE "…/Assets/Luts" -- every file in it
    was silently dropped, the tray never rendered "N LUTs only on this
    machine", and nothing was logged. canon._is_under documents the same trap
    for media paths."""
    library = _library(tmp_path)
    sibling = tmp_path / "root" / "Assets" / "Luts Local"
    sibling.mkdir(parents=True)
    (sibling / "GR Film.cube").write_text("y" * 20)

    found = luts.stray_luts([sibling], library)
    assert [f["name"] for f in found] == ["GR Film.cube"]


def test_a_nested_copy_inside_the_library_is_still_skipped(tmp_path):
    """The containment test still has to do its actual job."""
    library = _library(tmp_path)
    nested = library / "Editor2"
    nested.mkdir()
    (nested / "inside.cube").write_text("z" * 12)

    assert luts.stray_luts([nested], library) == []


def test_copy_into_library_preserves_the_pack_folder(tmp_path):
    library = _library(tmp_path)
    lut_dir = tmp_path / "resolve-lut"
    (lut_dir / "GR FILM").mkdir(parents=True)
    (lut_dir / "GR FILM" / "one.cube").write_text("data")

    entries = luts.stray_luts([lut_dir], library)
    result = luts.copy_into_library(entries, library)

    assert result["copied"] == 1
    assert (library / "GR FILM" / "one.cube").read_text() == "data"
    # The editor's own copy is untouched -- Resolve already knows about it.
    assert (lut_dir / "GR FILM" / "one.cube").exists()


def test_copy_never_overwrites(tmp_path):
    library = _library(tmp_path)
    (library / "one.cube").write_text("library version")
    lut_dir = tmp_path / "resolve-lut"
    lut_dir.mkdir()
    (lut_dir / "one.cube").write_text("my version")

    result = luts.copy_into_library(
        [{"path": str(lut_dir / "one.cube"), "dest_rel": "one.cube"}], library
    )
    assert result["copied"] == 0 and result["skipped"] == 1
    assert (library / "one.cube").read_text() == "library version"


def test_copy_refuses_a_destination_outside_the_library(tmp_path):
    """bug-hunt-2026-09-03 comp-ui-4: the join honours `..`, and the only
    producer of dest_rel today happens never to emit one. adopt() takes
    whatever entries it is handed, and the destination is a Syncthing-shared
    tree, so a miss here is a file the whole fleet replicates."""
    library = _library(tmp_path)
    lut_dir = tmp_path / "resolve-lut"
    lut_dir.mkdir()
    (lut_dir / "one.cube").write_text("data")
    outside = library.parent / "one.cube"

    result = luts.copy_into_library(
        [{"path": str(lut_dir / "one.cube"), "dest_rel": "../one.cube"}], library
    )

    assert result["copied"] == 0
    assert result["errors"] and "outside" in result["errors"][0]
    assert not outside.exists()


def test_copy_still_takes_a_nested_pack_folder(tmp_path):
    """The containment check must not refuse the ordinary case."""
    library = _library(tmp_path)
    lut_dir = tmp_path / "resolve-lut"
    lut_dir.mkdir()
    (lut_dir / "one.cube").write_text("data")

    result = luts.copy_into_library(
        [{"path": str(lut_dir / "one.cube"), "dest_rel": "GR FILM/one.cube"}], library
    )

    assert result["copied"] == 1
    assert (library / "GR FILM" / "one.cube").exists()


def test_copy_leaves_no_partial_file_visible(tmp_path, monkeypatch):
    """Syncthing is watching this directory: a half-copied LUT must never be
    indexed, which is why the copy lands on .ccsync-tmp first (a name the
    folder's .stignore excludes)."""
    library = _library(tmp_path)
    lut_dir = tmp_path / "resolve-lut"
    lut_dir.mkdir()
    (lut_dir / "one.cube").write_text("data")

    seen = {}

    real_copy = luts.shutil.copy2

    def spy(src, dst, *args, **kwargs):
        seen["dst"] = str(dst)
        return real_copy(src, dst, *args, **kwargs)

    monkeypatch.setattr(luts.shutil, "copy2", spy)
    luts.copy_into_library(
        [{"path": str(lut_dir / "one.cube"), "dest_rel": "one.cube"}], library
    )
    assert seen["dst"].endswith(".ccsync-tmp")
    assert (library / "one.cube").exists()
    assert not list(library.glob("*.ccsync-tmp"))


# -- the stale LUT index (an editor's rig, 2026-08-11) ------------------------
#
# Resolve scans its LUT locations once at startup. Launch it before P: is
# mapped and the shared library is missing for the whole session while the
# preference still reads perfectly -- so none of the check() tests above can
# see it. These cover the log-reading detector and the repair.

LOCATION = r"P:\Assets\Luts"


def _session(stamp="2026-08-11 13:32:02,593"):
    return (f"[0x000043f4] | Main                 | INFO  | {stamp} | "
            "Running DaVinci Resolve Studio v21.0.4.0005 (Windows/MSVC x86_64)")


def _no_dir(stamp="2026-08-11 13:32:05,788", location=LOCATION):
    return (f"[0x00007eec] | SyManager.Lut        | ERROR | {stamp} | "
            f"{location} : no dir")


def _noise(stamp="2026-08-11 13:32:04,275"):
    return (f"[0x00004224] | Fusion               | INFO  | {stamp} | "
            "Fusion Build: edc1ae3a_0004")


def _log(tmp_path, *lines):
    path = tmp_path / "davinci_resolve.log"
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    return path


def test_detects_a_session_that_launched_without_the_library(tmp_path):
    """The measured shape: launch at 13:32:02, scan fails at 13:32:05."""
    path = _log(tmp_path, _session(), _noise(), _no_dir())
    assert luts.stale_lut_index(LOCATION, path) == "2026-08-11 13:32:02,593"


def test_a_restart_after_the_miss_is_not_stale(tmp_path):
    """The 'no dir' belongs to the PREVIOUS session; this one scanned fine.
    Repairing here would fire on every check for the rest of the day."""
    path = _log(
        tmp_path,
        _session("2026-08-11 12:52:55,717"),
        _no_dir("2026-08-11 12:52:59,728"),
        _session("2026-08-11 13:32:02,593"),
        _noise(),
    )
    assert luts.stale_lut_index(LOCATION, path) is None


def test_another_locations_miss_is_ignored(tmp_path):
    """An editor's own unreachable LUT folder is their business."""
    path = _log(tmp_path, _session(), _no_dir(location=r"F:\Editing Assets\gamut"))
    assert luts.stale_lut_index(LOCATION, path) is None


def test_separator_and_case_differences_still_match(tmp_path):
    """These strings are GUI-typed and travel between machines."""
    path = _log(tmp_path, _session(), _no_dir(location="p:/assets/luts/"))
    assert luts.stale_lut_index(LOCATION, path) is not None


def test_no_session_line_in_the_tail_reports_nothing(tmp_path):
    """Cannot tell which session the miss belongs to -- so do nothing."""
    path = _log(tmp_path, _noise(), _no_dir())
    assert luts.stale_lut_index(LOCATION, path) is None


def test_a_missing_log_is_not_an_error(tmp_path):
    assert luts.stale_lut_index(LOCATION, tmp_path / "nope.log") is None
    assert luts.stale_lut_index(LOCATION, None) is None
    assert luts.read_log_tail(tmp_path / "nope.log") == []


def test_only_the_tail_is_read_and_the_split_line_is_dropped(tmp_path):
    """Resolve's log grows without bound; a seek into the middle lands
    mid-line, and half a timestamp must not read as a session start."""
    path = _log(tmp_path, _session("2026-08-11 09:00:00,000"),
                *[_noise() for _ in range(400)], _session(), _no_dir())
    lines = luts.read_log_tail(path, tail_bytes=2000)
    assert 0 < len(lines) < 400
    assert all(line.startswith("[0x") for line in lines)
    assert luts.stale_lut_index(LOCATION, path, tail_bytes=2000) == "2026-08-11 13:32:02,593"


def test_repair_refreshes_once_per_resolve_session(tmp_path):
    """RefreshLUTList is cheap but not free, and the loop runs every 15
    minutes for as long as that Resolve stays open."""
    path = _log(tmp_path, _session(), _no_dir())
    calls = []
    manager = luts.LutLinkManager(
        {"lut_location_override": LOCATION}, tmp_path / "root",
        prefs_factory=lambda: FakePrefs(existing=[LOCATION]),
        refresh_fn=lambda: calls.append(1) or True,
        log_path=path, running_fn=lambda: True, location_exists_fn=lambda p: True,
    )
    assert manager.repair_stale_index() is True
    assert manager.repair_stale_index() is False
    assert len(calls) == 1


def test_a_new_session_with_the_same_fault_is_repaired_again(tmp_path):
    path = _log(tmp_path, _session(), _no_dir())
    calls = []
    manager = luts.LutLinkManager(
        {"lut_location_override": LOCATION}, tmp_path / "root",
        prefs_factory=lambda: FakePrefs(existing=[LOCATION]),
        refresh_fn=lambda: calls.append(1) or True,
        log_path=path, running_fn=lambda: True, location_exists_fn=lambda p: True,
    )
    assert manager.repair_stale_index() is True
    _log(tmp_path, _session(), _no_dir(),
         _session("2026-08-11 16:00:00,000"), _no_dir("2026-08-11 16:00:03,000"))
    assert manager.repair_stale_index() is True
    assert len(calls) == 2


def test_a_refresh_that_did_not_take_is_retried(tmp_path):
    """No project open yet is routine -- and must not burn the one attempt."""
    path = _log(tmp_path, _session(), _no_dir())
    calls = []
    manager = luts.LutLinkManager(
        {"lut_location_override": LOCATION}, tmp_path / "root",
        prefs_factory=lambda: FakePrefs(existing=[LOCATION]),
        refresh_fn=lambda: calls.append(1) and False,
        log_path=path, running_fn=lambda: True, location_exists_fn=lambda p: True,
    )
    assert manager.repair_stale_index() is False
    assert manager.repair_stale_index() is False
    assert len(calls) == 2


def test_no_repair_while_resolve_is_closed(tmp_path):
    """Nothing to refresh, and the stale index dies with the process."""
    path = _log(tmp_path, _session(), _no_dir())
    calls = []
    manager = luts.LutLinkManager(
        {"lut_location_override": LOCATION}, tmp_path / "root",
        prefs_factory=lambda: FakePrefs(existing=[LOCATION]),
        refresh_fn=lambda: calls.append(1) or True,
        log_path=path, running_fn=lambda: False,
    )
    assert manager.repair_stale_index() is False
    assert calls == []


def test_repair_can_be_switched_off(tmp_path):
    path = _log(tmp_path, _session(), _no_dir())
    calls = []
    manager = luts.LutLinkManager(
        {"lut_location_override": LOCATION, "lut_index_repair_enabled": False},
        tmp_path / "root",
        prefs_factory=lambda: FakePrefs(existing=[LOCATION]),
        refresh_fn=lambda: calls.append(1) or True,
        log_path=path, running_fn=lambda: True, location_exists_fn=lambda p: True,
    )
    assert manager.repair_stale_index() is False
    assert calls == []


def test_check_repairs_even_though_the_preference_is_already_right(tmp_path):
    """The regression this whole section exists for: check() used to return
    ALREADY and touch nothing, so a correct pref meant a Resolve blind to the
    library stayed blind until someone restarted it."""
    _library(tmp_path)
    path = _log(tmp_path, _session(), _no_dir())
    calls = []
    prefs = FakePrefs(existing=[LOCATION])
    manager = luts.LutLinkManager(
        {"lut_location_override": LOCATION}, tmp_path / "root",
        prefs_factory=lambda: prefs,
        refresh_fn=lambda: calls.append(1) or True,
        log_path=path, running_fn=lambda: True, location_exists_fn=lambda p: True,
    )
    result = manager.check()
    assert result["status"] == rp.ALREADY
    assert result["changed"] is True
    assert prefs.added == []          # the preference was never rewritten
    assert len(calls) == 1


def test_the_log_override_wins(tmp_path):
    path = _log(tmp_path, _session(), _no_dir())
    manager = luts.LutLinkManager(
        {"lut_location_override": LOCATION, "resolve_log_override": str(path)},
        tmp_path / "root",
        prefs_factory=lambda: FakePrefs(existing=[LOCATION]),
        refresh_fn=lambda: True, running_fn=lambda: True, location_exists_fn=lambda p: True,
    )
    assert manager.log_path() == path
    assert manager.repair_stale_index() is True


def test_no_repair_while_the_drive_is_still_down(tmp_path):
    """RefreshLUTList would report success against an unreachable location.
    Marking the session repaired there costs the editor the retry they need
    when P: comes back -- and avoiding a Resolve restart is the entire point."""
    path = _log(tmp_path, _session(), _no_dir())
    calls = []
    reachable = {"yes": False}
    manager = luts.LutLinkManager(
        {"lut_location_override": LOCATION}, tmp_path / "root",
        prefs_factory=lambda: FakePrefs(existing=[LOCATION]),
        refresh_fn=lambda: calls.append(1) or True,
        log_path=path, running_fn=lambda: True,
        location_exists_fn=lambda p: reachable["yes"],
    )
    assert manager.repair_stale_index() is False
    assert calls == []
    reachable["yes"] = True                     # the mapping comes back
    assert manager.repair_stale_index() is True
    assert len(calls) == 1


# -- warning cadence (bug-hunt-2026-09-03 comp-ui-3) -------------------------

def test_a_recurring_failure_warns_again_after_the_streak_ends(tmp_path, caplog):
    """`_warned` used to be a set of statuses cleared only on a successful
    add, so a transient miss at boot silenced the SAME status for the life of
    the process: the library could then be unreachable all day with nothing in
    companion.log about it."""
    import logging

    m = _manager(tmp_path)
    with caplog.at_level(logging.WARNING, logger="ccsync.luts"):
        m._report("no-library", False, "the LUT library has not synced yet")
        m._report(rp.ALREADY, False, "")          # the streak ends
        m._report("no-library", False, "the LUT library has not synced yet")

    lines = [r.message for r in caplog.records if r.name == "ccsync.luts"]
    assert len(lines) == 2, lines


def test_the_same_failure_every_cycle_is_logged_hourly_not_every_time(tmp_path, caplog, monkeypatch):
    import logging

    now = [1000.0]
    monkeypatch.setattr(luts.time, "monotonic", lambda: now[0])
    m = _manager(tmp_path)
    with caplog.at_level(logging.WARNING, logger="ccsync.luts"):
        for _ in range(5):
            now[0] += 60.0
            m._report("no-library", False, "the LUT library has not synced yet")
        assert len([r for r in caplog.records if r.name == "ccsync.luts"]) == 1
        now[0] += luts.WARN_RELOG_SECONDS
        m._report("no-library", False, "the LUT library has not synced yet")

    assert len([r for r in caplog.records if r.name == "ccsync.luts"]) == 2
