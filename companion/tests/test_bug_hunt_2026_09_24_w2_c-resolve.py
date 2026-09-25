"""Wave 2 of the 2026-09-24 hunt's fix pass, group c-resolve, chunk 1.

bug-comp-resolve-1..4 and logic-resolve-1..4. Each test names its finding and
fails on HEAD 4462a2a's code. No live Resolve anywhere: the fakes model only
what each finding turns on.
"""
from __future__ import annotations

import json
import os
from pathlib import Path

import pytest

from ccsync_companion import (fixer, luts, resolve_bridge, resolve_journal,
                              resolve_undo, timeline_cards_bridge,
                              timeline_cards_role)


@pytest.fixture(autouse=True)
def _fresh(monkeypatch):
    resolve_journal.reset_for_tests()
    resolve_bridge.reset_timeline_cache()
    monkeypatch.setattr(resolve_bridge, "_project_name_cache", None, raising=False)
    monkeypatch.setattr(resolve_bridge.ui_state, "wait_while_menu_open",
                        lambda *a, **kw: None)
    yield
    resolve_journal.reset_for_tests()
    resolve_bridge.reset_timeline_cache()


# ------------------------------------------------------ bug-comp-resolve-1

def test_an_undo_in_resolves_launch_window_is_retried_not_failed(tmp_path):
    """"DaVinci Resolve is starting up" (CR-68's launch-window answer) matched
    none of RES-4's hint substrings, so the admin's undo was recorded FAILED
    and the dashboard retired the command."""
    journal = tmp_path / "j.json"
    journal.write_text("{}", encoding="utf-8")
    for message in resolve_bridge.DISCONNECTION_MESSAGES:
        ok, detail, state = resolve_undo.apply_undo(
            {"journal": "x/y.json"},
            undo_fn=lambda session_path, m=message: {"ok": False, "message": m},
            resolver=lambda _id: journal)
        assert (ok, state) == (False, resolve_undo.STATE_RETRYING), message
        assert detail == message


def test_a_real_refusal_still_fails(tmp_path):
    journal = tmp_path / "j.json"
    journal.write_text("{}", encoding="utf-8")
    _ok, _detail, state = resolve_undo.apply_undo(
        {"journal": "x/y.json"},
        undo_fn=lambda session_path: {"ok": False, "message": "j.json records no changes."},
        resolver=lambda _id: journal)
    assert state == "failed"


# ------------------------------------------------------ bug-comp-resolve-2

class _Item:
    def __init__(self, path, name="A001"):
        self.path = path
        self.name = name

    def GetClipProperty(self, key=None):
        props = {"File Path": self.path, "Proxy Media Path": ""}
        return props if key is None else props.get(key, "")

    def GetName(self):
        return self.name

    def ReplaceClip(self, new_path):
        self.path = new_path
        return None


class _Project:
    def __init__(self, name):
        self.name = name

    def GetName(self):
        return self.name


class _Manager:
    def __init__(self, project):
        self.project = project

    def GetCurrentProject(self):
        return self.project

    def SaveProject(self):
        return True

    ExportProject = None


class _Resolve:
    def __init__(self, manager):
        self.manager = manager

    def GetProjectManager(self):
        return self.manager


def test_a_relink_just_after_a_project_switch_is_journalled_under_the_new_project(
        monkeypatch):
    manager = _Manager(_Project("A"))
    monkeypatch.setattr(resolve_bridge, "connect", lambda: _Resolve(manager))
    # The tray's undo line (or the proxy pass) warms the 20 s cache in A...
    assert resolve_bridge.current_project_name() == "A"
    # ...the editor opens B, and B's first relink runs inside that window.
    manager.project = _Project("B")
    resolve_bridge.replace_clip(_Item(r"F:\b.mov"), r"P:\b.mov", tries=1,
                                source="auto-canonical")
    assert resolve_journal.latest_session("A") is None
    path = resolve_journal.latest_session("B")
    assert path is not None
    assert resolve_journal.read_session(path)["project"] == "B"


# ------------------------------------------------------ bug-comp-resolve-3

def test_the_cards_sweep_never_takes_the_api_walk(monkeypatch):
    """With no library answer, get_timeline_items() falls through to the API
    walk under _API_LOCK before sweep_items could refuse it."""
    walks = []
    monkeypatch.setattr(resolve_bridge, "_library_timeline_items",
                        lambda allow_cached=False, count_poll=True: None)
    monkeypatch.setattr(resolve_bridge, "_get_timeline_items_locked",
                        lambda allow_cached=False: walks.append(1) or
                        {"ok": True, "items": [], "timeline_uid": "T"})
    assert timeline_cards_bridge.CardsBridge({}).sweep_items("T") is None
    assert walks == []


def test_a_library_read_for_cards_does_not_advance_the_watchers_valve():
    fingerprint = ("library", "P", "T", "uid", 1)
    resolve_bridge._remember_timeline_result(
        fingerprint, {"ok": True, "items": [], "timeline_uid": "uid"})
    for _ in range(20):
        assert resolve_bridge._cached_timeline_result(
            fingerprint, count_poll=False) is not None
    assert resolve_bridge._polls_since_full_walk == 0
    # The watcher's own polls still count, and still meet the valve.
    for _ in range(resolve_bridge._FULL_WALK_EVERY_POLLS - 1):
        assert resolve_bridge._cached_timeline_result(fingerprint) is not None
    assert resolve_bridge._cached_timeline_result(fingerprint) is None


def test_library_timeline_items_passes_the_non_counting_flag(monkeypatch):
    seen = {}

    def fake(allow_cached=False, count_poll=True):
        seen.update(allow_cached=allow_cached, count_poll=count_poll)
        return {"ok": True, "items": [], "timeline_uid": "T"}

    monkeypatch.setattr(resolve_bridge, "_library_timeline_items", fake)
    assert resolve_bridge.library_timeline_items()["ok"] is True
    assert seen == {"allow_cached": True, "count_poll": False}


# ------------------------------------------------------ bug-comp-resolve-4

def _role(tmp_path, request):
    cfg = {"cards_agent": True, "dashboard_url": "https://dash.invalid",
           "dashboard_token": "companion-token-not-a-real-one",
           "jobs_mulcam_pipeline": str(tmp_path / "MP"),
           "jobs_vault_root": str(tmp_path / "vault")}
    return timeline_cards_role.TimelineCardsRole(cfg, request_fn=request)


def test_a_replaced_clients_loop_is_refused_before_it_fetches_work(tmp_path):
    calls = []
    role = _role(tmp_path, lambda *a: calls.append(a) or (200, {"cmd": "move"}))
    old, new = object(), object()
    role._client = new
    with pytest.raises(timeline_cards_role.CardsTunnelError):
        role.call("/agent/pending?wait=25", None, 45, caller=old)
    assert calls == []
    assert role.call("/agent/pending?wait=25", None, 45, caller=new) == {"cmd": "move"}


def test_a_long_poll_in_flight_at_the_restart_is_not_handed_to_the_old_client(tmp_path):
    role = _role(tmp_path, None)
    old = object()
    role._client = old

    def request(*_a):
        role._client = object()     # the watchdog restarted the role meanwhile
        return 200, {"cmd": "move"}

    role._request = request
    with pytest.raises(timeline_cards_role.CardsTunnelError):
        role.call("/agent/pending?wait=25", None, 45, caller=old)


def test_the_tunnel_client_names_itself(tmp_path):
    seen = {}

    class _Agent:
        class AgentClient:
            def __init__(self, *a):
                pass

    class _FakeRole:
        dashboard_url = "https://dash.invalid"
        machine = "m"

        def call(self, path, doc=None, timeout=30, caller=None):
            seen["caller"] = caller
            return {}

    client = timeline_cards_role.make_tunnel_client(_Agent, _FakeRole(), object())
    client._req("/agent/state", {}, 5)
    assert seen["caller"] is client


# ------------------------------------------------------- logic-resolve-1

def _src(tmp_path, data=b"camera bytes " * 1000, name="A001.braw"):
    src = tmp_path / "card" / name
    src.parent.mkdir(parents=True, exist_ok=True)
    src.write_bytes(data)
    return src


def test_retry_after_a_failed_relink_relinks_the_copy_instead_of_copying_again(tmp_path):
    src = _src(tmp_path)
    root = tmp_path / "root"
    root.mkdir()
    copies = []

    def copy(s, d):
        copies.append(d)
        import shutil
        shutil.copyfile(s, d)

    first = fixer.fix_clip(str(src), "Projects/X/B-roll", str(root), [object()],
                           copy_fn=copy, dry_run=False,
                           replace_clip_fn=lambda m, p: {"ok": False, "message": "locked"})
    assert first["ok"] is False and first["copied_to"]
    relinked = []
    second = fixer.fix_clip(str(src), "Projects/X/B-roll", str(root), [object()],
                            copy_fn=copy, dry_run=False,
                            replace_clip_fn=lambda m, p: relinked.append(p) or {"ok": True})
    assert second["ok"] is True
    assert second["copied_to"] == first["copied_to"]
    assert second["reused_copy"] is True
    assert len(copies) == 1
    assert sorted(p.name for p in (root / "Projects/X/B-roll").iterdir()) == ["A001.braw"]


def test_a_same_named_same_sized_different_clip_is_not_reused(tmp_path):
    src = _src(tmp_path, data=b"a" * 4096)
    root = tmp_path / "root"
    dest = root / "Projects" / "X"
    dest.mkdir(parents=True)
    (dest / "A001.braw").write_bytes(b"b" * 4096)
    result = fixer.fix_clip(str(src), "Projects/X", str(root), [object()],
                            dry_run=False, replace_clip_fn=lambda m, p: {"ok": True})
    assert result["ok"] is True and result["reused_copy"] is False
    assert result["copied_to"].endswith("A001 (2).braw")


# ------------------------------------------------------- logic-resolve-2

class _FakeTime:
    """resolve_journal's `time`, and only its: the journal's own defaults
    that are bound at def time are passed a clock explicitly instead."""

    def __init__(self, t=1_000_000.0):
        self.t = t

    def time(self):
        return self.t

    def monotonic(self):
        return self.t


def test_a_fix_all_with_long_copies_is_one_journal(monkeypatch, tmp_path):
    clock = _FakeTime()
    monkeypatch.setattr(resolve_journal, "time", clock)

    def slow_copy(s, d):
        clock.t += 600.0             # a 20 GB clip over SMB
        import shutil
        shutil.copyfile(s, d)

    def relink(_mpi, path):
        resolve_journal.record(resolve_journal.KIND_REPLACE_CLIP, "FF5",
                               old_path="F:/x", new_path=path, source="fix-all",
                               clock=clock.time)
        return {"ok": True}

    root = tmp_path / "root"
    root.mkdir()
    for i in range(3):
        src = _src(tmp_path, data=bytes([i + 1]) * 100, name=f"A00{i}.braw")
        fixer.fix_clip(str(src), "Projects/X", str(root), [object()],
                       copy_fn=slow_copy, dry_run=False, replace_clip_fn=relink)
    found = resolve_journal.sessions("FF5")
    assert len(found) == 1
    assert len(resolve_journal.read_session(found[0])["entries"]) == 3


def test_a_burst_that_went_quiet_before_the_hold_is_not_revived():
    clock = _FakeTime()
    resolve_journal.record(resolve_journal.KIND_REPLACE_CLIP, "FF5", new_path="a",
                           clock=clock.time)
    clock.t += 3600.0
    with resolve_journal.hold_sessions(clock=clock.time):
        clock.t += 600.0
        resolve_journal.record(resolve_journal.KIND_REPLACE_CLIP, "FF5", new_path="b",
                               clock=clock.time)
    assert len(resolve_journal.sessions("FF5")) == 2


def _undo_setup(monkeypatch, items, project="FF5"):
    manager = _Manager(_Project(project))
    monkeypatch.setattr(resolve_bridge, "connect", lambda: _Resolve(manager))
    monkeypatch.setattr(resolve_bridge, "get_media_pool_items", lambda: {
        "ok": True, "message": "", "project_name": project,
        "items": [{"file_path": i.path, "clip_name": i.name, "media_pool_item": i}
                  for i in items]})


def test_a_second_undo_press_moves_on_instead_of_blaming_the_media_pool(monkeypatch):
    first, second = _Item(r"P:.mov", "A"), _Item(r"P:.mov", "B")
    clock = _FakeTime()
    resolve_journal.record(resolve_journal.KIND_REPLACE_CLIP, "FF5", clip_name="A",
                           old_path=r"F:.mov", new_path=r"P:.mov", clock=clock.time)
    clock.t += 3600.0
    resolve_journal.record(resolve_journal.KIND_REPLACE_CLIP, "FF5", clip_name="B",
                           old_path=r"F:.mov", new_path=r"P:.mov", clock=clock.time)
    assert len(resolve_journal.sessions("FF5")) == 2

    _undo_setup(monkeypatch, [first, second])
    one = resolve_bridge.undo_last_relink()
    assert one["undone"] == 1 and second.path == r"F:.mov" and first.path == r"P:.mov"
    _undo_setup(monkeypatch, [first, second])
    two = resolve_bridge.undo_last_relink()
    assert two["undone"] == 1 and first.path == r"F:.mov"
    assert "no longer in" not in two["message"]
    _undo_setup(monkeypatch, [first, second])
    three = resolve_bridge.undo_last_relink()
    assert three["ok"] is False
    assert "already been put back" in three["message"]
    assert resolve_journal.describe_latest("FF5") == ""


def test_replaying_a_journal_whose_clips_are_already_back_says_so(monkeypatch):
    item = _Item(r"F:\a.mov")
    _undo_setup(monkeypatch, [item])
    resolve_bridge.replace_clip(item, r"P:\a.mov", tries=1)
    path = resolve_journal.latest_session("FF5")
    item.path = r"F:\a.mov"          # put back by hand / an older companion
    _undo_setup(monkeypatch, [item])
    result = resolve_bridge.undo_last_relink(session_path=path)
    assert result["ok"] is True and result["already_back"] == 1
    assert "no longer in" not in result["message"]


# ------------------------------------------------------- logic-resolve-3

def test_resolves_factory_luts_are_never_offered(tmp_path):
    factory = tmp_path / "LUT"
    (factory / "Arri").mkdir(parents=True)
    (factory / "Arri" / "LogC.cube").write_text("x", encoding="utf-8")
    (factory / "Invert Color.ilut").write_text("x", encoding="utf-8")
    (factory / "Studio Look.cube").write_text("mine", encoding="utf-8")
    library = tmp_path / "Luts"
    library.mkdir()
    names = [s["name"] for s in luts.stray_luts([factory], library)]
    assert names == ["Studio Look.cube"]


def test_a_lut_already_in_the_library_at_its_destination_is_not_offered_again(tmp_path):
    """A different Resolve build's copy differs in size; copy_into_library
    skips it because the destination exists, so the offer never cleared."""
    here = tmp_path / "LUT"
    (here / "Pack").mkdir(parents=True)
    (here / "Pack" / "Look.cube").write_text("newer build, longer", encoding="utf-8")
    library = tmp_path / "Luts"
    (library / "Pack").mkdir(parents=True)
    (library / "Pack" / "Look.cube").write_text("older", encoding="utf-8")
    assert luts.stray_luts([here], library) == []


def test_the_factory_list_can_be_extended_from_config(tmp_path):
    here = tmp_path / "LUT"
    (here / "Vendor X").mkdir(parents=True)
    (here / "Vendor X" / "a.cube").write_text("x", encoding="utf-8")
    library = tmp_path / "root" / "Assets" / "Luts"
    library.mkdir(parents=True)
    manager = luts.LutLinkManager({"resolve_lut_dir": str(here),
                                   "resolve_factory_luts_extra": "vendor x"},
                                  tmp_path / "root")
    assert manager.find_strays() == []


# ------------------------------------------------------- logic-resolve-4

def test_a_fix_into_the_tree_root_says_it_will_not_sync(tmp_path):
    src = _src(tmp_path, data=b"q" * 64)
    root = tmp_path / "root"
    root.mkdir()
    result = fixer.fix_clip(str(src), fixer.suggest_destination(str(src), "ruskin", ""),
                            str(root), [object()], dry_run=False,
                            replace_clip_fn=lambda m, p: {"ok": True})
    assert result["ok"] is True
    assert result["stays_local"] is True
    assert "will not reach the server" in result["message"]


def test_a_fix_into_a_project_says_nothing_extra(tmp_path):
    src = _src(tmp_path, data=b"q" * 64)
    root = tmp_path / "root"
    root.mkdir()
    result = fixer.fix_clip(str(src), "Projects/2026/FF5/Ep1/B-roll", str(root),
                            [object()], dry_run=False,
                            replace_clip_fn=lambda m, p: {"ok": True})
    assert result["stays_local"] is False
    assert "will not reach" not in result["message"]


@pytest.mark.parametrize("rel,local", [
    ("B-roll/Editor Added/ruskin", True), ("Audio/Music", True), ("", True),
    ("Projects/2026/FF5/Ep1/Audio", False), ("projects\\x", False),
    ("Assets/Music", False),
])
def test_destination_stays_local(rel, local):
    assert fixer.destination_stays_local(rel) is local


# ===================================================== chunk 2 (2026-09-25)
# bug-comp-resolve-5, -6, -8, -9 and logic-cards-9. -7 is DEFERRED (needs a
# live Resolve) and logic-resolve-5 is owed to popup.py, so neither has a
# test here.

import errno  # noqa: E402
import logging  # noqa: E402
import shutil  # noqa: E402
import sqlite3  # noqa: E402
import threading  # noqa: E402
import time  # noqa: E402

from ccsync_companion import library, script_server  # noqa: E402


# ------------------------------------------------------ bug-comp-resolve-5

# conftest's _no_live_resolve stubs connect(); these want the real one,
# captured at import time as test_resolve_bridge_launch_window does.
_REAL_CONNECT = resolve_bridge.connect


def _record_lock_at_probe(monkeypatch, phase):
    monkeypatch.setattr(resolve_bridge, "connect", _REAL_CONNECT)
    monkeypatch.setattr(resolve_bridge, "_starting_since", None, raising=False)
    held: list[bool] = []

    def state():
        held.append(resolve_bridge._API_LOCK._is_owned())
        return (phase, "test")

    monkeypatch.setattr(script_server, "state", state)
    return held


def test_the_cr68_probe_never_runs_under_the_bridge_lock(monkeypatch):
    """On a Mac the probe is an lsof spawn with a 5 s timeout, and connect()
    ran it inside `with _bridge_call("connect")` -- every watcher poll, pool
    refresh, b-roll insert and Cards sweep queued behind a subprocess."""
    held = _record_lock_at_probe(monkeypatch, script_server.ABSENT)
    assert resolve_bridge.connect() is None
    assert held and not any(held), held


def test_a_connect_nested_in_a_public_call_uses_the_answer_taken_before_the_lock(
        monkeypatch):
    held = _record_lock_at_probe(monkeypatch, script_server.ABSENT)
    with resolve_bridge._bridge_call("get_timeline_items"):
        assert resolve_bridge.connect() is None
        assert resolve_bridge.connect() is None
    assert held == [False], held


def test_a_stale_primed_answer_is_not_acted_on(monkeypatch):
    """A lock wait longer than the bound (a wedge) must not connect on an
    answer that old: it probes again, under the lock, as before the fix."""
    held = _record_lock_at_probe(monkeypatch, script_server.STARTING)
    with resolve_bridge._bridge_call("outer"):
        answer = resolve_bridge._primed_probe.answer
        resolve_bridge._primed_probe.answer = (
            answer[0] - resolve_bridge._PRIMED_PROBE_MAX_AGE - 1.0,
            (script_server.READY, "stale"))
        assert resolve_bridge.connect() is None      # STARTING, freshly asked
    assert held == [False, True]


def test_the_primed_answer_does_not_outlive_its_call(monkeypatch):
    _record_lock_at_probe(monkeypatch, script_server.ABSENT)
    with resolve_bridge._bridge_call("outer"):
        pass
    assert getattr(resolve_bridge._primed_probe, "answer", None) is None


# ------------------------------------------------------ bug-comp-resolve-6

def _blip_first_stat(monkeypatch, target: Path):
    real_stat = Path.stat
    calls = {"n": 0}

    def stat(self, *a, **kw):
        if (os.path.normcase(str(self)) == os.path.normcase(str(target))
                and calls["n"] == 0):
            calls["n"] += 1
            raise OSError(errno.EIO, "the share went away for a moment")
        return real_stat(self, *a, **kw)

    monkeypatch.setattr(Path, "stat", stat)


def test_a_stat_blip_at_the_recheck_leaves_no_empty_reservation(tmp_path, monkeypatch):
    """HEAD claimed `clip (2).braw` and left our 0-byte `clip.braw` behind,
    where lane A uploads it and no sweep can find it (no tmp beside it)."""
    reserved = fixer._claim_destination_path(tmp_path, "clip.braw")
    with pytest.MonkeyPatch.context() as mp:
        _blip_first_stat(mp, reserved)
        landed = fixer.reclaim_if_reservation_lost(tmp_path, reserved, "clip.braw")
    tmp = tmp_path / "clip.braw.1-abc.ccsync-tmp"
    tmp.write_bytes(b"footage")
    os.replace(tmp, landed)
    empties = [p.name for p in tmp_path.glob("*.braw") if p.stat().st_size == 0]
    assert empties == [], empties
    assert landed.name == "clip.braw"


def test_a_stat_blip_never_removes_an_arrival_with_content(tmp_path, monkeypatch):
    reserved = fixer._claim_destination_path(tmp_path, "clip.braw")
    reserved.write_bytes(b"another editor's clip")   # lane C landed on it
    with pytest.MonkeyPatch.context() as mp:
        _blip_first_stat(mp, reserved)
        landed = fixer.reclaim_if_reservation_lost(tmp_path, reserved, "clip.braw")
    assert reserved.read_bytes() == b"another editor's clip"
    assert landed.name == "clip (2).braw"


# ------------------------------------------------------ bug-comp-resolve-8

_PROJECT_DDL = """
CREATE TABLE "SM_Project" (
    "SM_Project_id" TEXT, "ProjectName" TEXT, "MediaPool" TEXT,
    "LastModTimeInSecs" INTEGER, "UpToDate" INTEGER);
"""


def _library_with(tmp_path, rows):
    path = tmp_path / "Project.db"
    conn = sqlite3.connect(str(path))
    conn.executescript(_PROJECT_DDL)
    for pid, name in rows:
        conn.execute('INSERT INTO "SM_Project" VALUES (?,?,?,?,?)',
                     (pid, name, "", 1, 0))
    conn.commit()
    conn.close()
    return library.LibraryInfo(kind="Disk", name="Local", sqlite_path=str(path))


def test_two_projects_with_one_name_are_refused_not_guessed(tmp_path):
    """rows[0] was taken, so the pool walk could read the OTHER folder's
    "Interviews" and plan every relink on uids the open pool does not hold."""
    info = _library_with(tmp_path, [
        ("11111111-1111-1111-1111-111111111111", "Interviews"),
        ("22222222-2222-2222-2222-222222222222", "Interviews"),
    ])
    with pytest.raises(library.LibraryUnavailable) as caught:
        library.ProjectLibrary(info, "Interviews")
    assert "2 projects named" in str(caught.value)


def test_one_project_of_that_name_still_opens(tmp_path):
    info = _library_with(tmp_path, [
        ("11111111-1111-1111-1111-111111111111", "Interviews"),
        ("22222222-2222-2222-2222-222222222222", "Other"),
    ])
    lib = library.ProjectLibrary(info, "Interviews")
    assert lib._project_id == "11111111-1111-1111-1111-111111111111"


# ------------------------------------------------------ bug-comp-resolve-9

def _stray_lut(tmp_path):
    src = tmp_path / "stray" / "Look.cube"
    src.parent.mkdir()
    src.write_text("LUT_3D_SIZE 2\n", encoding="utf-8")
    lib = tmp_path / "Luts"
    lib.mkdir()
    return src, lib


def test_a_failed_lut_copy_leaves_no_tmp_in_the_library(tmp_path, monkeypatch):
    src, lib = _stray_lut(tmp_path)

    def dies_part_way(a, b, *args, **kw):
        Path(b).write_text("LUT_3D", encoding="utf-8")
        raise OSError(errno.ENOSPC, "No space left on device")

    monkeypatch.setattr(shutil, "copy2", dies_part_way)
    out = luts.copy_into_library([{"path": str(src), "dest_rel": "Look.cube"}], lib)
    assert out["copied"] == 0 and out["errors"]
    assert list(lib.rglob("*.ccsync-tmp")) == []


def test_a_refused_rename_leaves_no_tmp_either(tmp_path, monkeypatch):
    src, lib = _stray_lut(tmp_path)

    def locked(a, b):
        raise PermissionError(errno.EACCES, "locked")

    with pytest.MonkeyPatch.context() as mp:
        mp.setattr(luts.os, "replace", locked)
        out = luts.copy_into_library([{"path": str(src), "dest_rel": "Look.cube"}], lib)
    assert out["errors"]
    assert list(lib.rglob("*.ccsync-tmp")) == []
    assert not (lib / "Look.cube").exists()


# ------------------------------------------------------ logic-cards-9

def _cards_role(answer):
    role = timeline_cards_role.TimelineCardsRole.__new__(
        timeline_cards_role.TimelineCardsRole)
    role._lock = threading.RLock()
    role._wall = time.time
    role._last_http_status = None
    role._last_error = ""
    role._last_poll_at = None
    role._not_attached = ""
    role._last_refusal = ""
    role._seen = None
    role._timeline = ""
    role._project = ""
    role._state = timeline_cards_role.STATE_RUNNING
    role._detail = "serving the page"
    role._threads = [threading.current_thread()]
    role._since = time.time()
    role._loop_error = ""
    role._machine_name = "EDIT-1"
    role.cfg = {"dashboard_url": "https://dash.example",
                "dashboard_token": "t" * 32}
    role.answer = answer
    role._request = lambda method, url, body, headers, timeout: (200, role.answer)
    role._headers = lambda: {}
    return role


_NO_ENGINE = ("alex is not in a Timeline Cards episode on this dashboard -- "
              "open one at /cards/ and this agent attaches to it")


def test_a_stale_result_refusal_is_not_called_discarding(caplog):
    """`/agent/result` answers `{"ok": false, "error": "that request is no
    longer open"}` for an edit the engine already let go. That was logged as
    "the dashboard is discarding this computer's pushes" and became the fleet
    grid's detail."""
    role = _cards_role({"ok": False, "error": "that request is no longer open"})
    with caplog.at_level(logging.INFO, logger=timeline_cards_role.log.name):
        role.call("/agent/result", {"id": "e1", "ok": True})
    assert "discarding" not in caplog.text
    assert "no longer open" in caplog.text
    assert role.health()[1] == "serving the page"


def test_an_engine_answer_clears_a_not_attached_state():
    role = _cards_role({"error": _NO_ENGINE})
    role.call("/agent/state", {"state": {"timeline": "E1", "project": "FF5"}})
    assert role.health()[1] == _NO_ENGINE
    role.answer = {"error": "KeyError: 'track'"}      # an engine raised
    role.call("/agent/state", {"state": {"timeline": "E1", "project": "FF5"}})
    assert role.health()[1] == "serving the page"
    assert role._timeline == "", "a refused push is still not traffic served"


@pytest.mark.parametrize("answer", [
    {"error": _NO_ENGINE},
    {"note": _NO_ENGINE},
    {"attached": False, "error": "no episode open for this editor"},
])
def test_the_tunnels_no_engine_answer_is_still_not_attached(answer, caplog):
    role = _cards_role(answer)
    with caplog.at_level(logging.WARNING, logger=timeline_cards_role.log.name):
        role.call("/agent/state", {"state": {"timeline": "E1", "project": "FF5"}})
    assert "discarding" in caplog.text
    assert role.health()[1] == (answer.get("error") or answer.get("note"))


def test_attached_true_wins_over_the_sentence():
    role = _cards_role({"attached": True, "error": _NO_ENGINE})
    role.call("/agent/state", {"state": {"timeline": "E1", "project": "FF5"}})
    assert role.health()[1] == "serving the page"


# ------------------------------------------------ ui-copy-4 (owed round)
#
# c-ytdl's sweep of "machine"/"parked"/"halted" left these two modules to
# this group. The shared scan (test_sweep_2026_09_04_copy) is applied here to
# the two modules until that file's owner adds them to its MODULES.

import sys as _sys  # noqa: E402

_sys.path.insert(0, str(Path(__file__).resolve().parent))
import test_sweep_2026_09_04_copy as _vocab  # noqa: E402
from test_timeline_cards_role import a_cfg as _cards_cfg  # noqa: E402


@pytest.mark.parametrize("name", ["resolve_undo.py", "timeline_cards_role.py"])
def test_no_retired_word_in_a_resolve_sentence(name):
    """HEAD: "Parked: ..." in resolve_undo; "the fleet is halted, so this
    machine ..." and "this machine's processes ..." in the Cards role."""
    bad = [t for t in _vocab._sentences(_vocab.SRC / name)
           if t not in _vocab.VOCABULARY_ALLOWED and _vocab._WORD_RE.search(t)]
    assert not bad, f"{name} says a retired word to an editor: {bad}"


def test_the_parked_undo_says_waiting():
    assert resolve_undo.PARKED_DETAIL.startswith("Waiting: ")
    assert "Parked" not in resolve_undo.PARKED_DETAIL


def test_the_halt_refusal_uses_the_owner_words(tmp_path):
    role = timeline_cards_role.TimelineCardsRole(
        _cards_cfg(tmp_path), processes_fn=lambda: [], halted_fn=lambda: True)
    state, detail = role.refusal()
    assert state == timeline_cards_role.STATE_HALTED
    assert detail.startswith("syncing is stopped by your admin, so this "
                             "computer is not taking work")
    assert "halted" not in detail and "machine" not in detail


@pytest.mark.parametrize("processes", [
    lambda: None,                                   # the probe cannot tell
    lambda: (_ for _ in ()).throw(OSError("wmic")),  # the probe raised
    lambda: ["4312\tpython.exe\tC:\\Python\\python.exe reorder_web.py --agent"],
])
def test_no_bug_id_in_a_standalone_refusal(tmp_path, processes):
    role = timeline_cards_role.TimelineCardsRole(
        _cards_cfg(tmp_path), processes_fn=processes)
    state, detail = role.refusal()
    assert state == timeline_cards_role.STATE_STANDALONE_AGENT
    assert "CR-68" not in detail and "machine" not in detail


def test_a_probe_that_raised_is_still_cannot_tell_not_a_sighting(tmp_path):
    def boom():
        raise OSError("process list refused")
    role = timeline_cards_role.TimelineCardsRole(
        _cards_cfg(tmp_path), processes_fn=boom)
    detail = role.refusal()[1]
    assert "may be running here" in detail
    assert "already driving Resolve" not in detail


# ====================================================================
# Owed round 3 (2026-09-25)
# ====================================================================

from types import SimpleNamespace as _NS  # noqa: E402

from ccsync_companion import popup as _popup  # noqa: E402


def test_a_relink_that_repointed_some_clips_says_how_many(tmp_path):
    """logic-resolve-5 owed: the relink-failure return carried no `relinked`,
    so popup's undo pointer (which reads only that count) never showed for a
    fix that HAD journaled some clips."""
    src = _src(tmp_path)
    root = tmp_path / "root"
    root.mkdir()
    answers = iter([{"ok": True}, {"ok": False, "message": "locked"}, {"ok": True}])
    result = fixer.fix_clip(str(src), "Projects/X/B-roll", str(root),
                            [object(), object(), object()], dry_run=False,
                            replace_clip_fn=lambda m, p: next(answers))
    assert result["ok"] is False and result["copied_to"]
    assert result["relinked"] == 2
    assert "relink failed for 1 of 3" in result["message"]
    assert _popup._changed_something(result) is True


def test_a_relink_that_repointed_nothing_says_zero(tmp_path):
    src = _src(tmp_path)
    root = tmp_path / "root"
    root.mkdir()
    result = fixer.fix_clip(str(src), "Projects/X/B-roll", str(root), [object()],
                            dry_run=False,
                            replace_clip_fn=lambda m, p: {"ok": False, "message": "locked"})
    assert result["relinked"] == 0
    assert _popup._changed_something(result) is False


class _NoBridgeEngine:
    def __init__(self, root):
        self.root = root


class _BridgeEngine:
    def __init__(self, root, bridge=None):
        self.root = root


@pytest.mark.parametrize("engine_mod", [
    _NS(ResolveEngine=_BridgeEngine),                              # no contract
    _NS(BRIDGE_CONTRACT_VERSION=99, ResolveEngine=_BridgeEngine),  # other version
    _NS(BRIDGE_CONTRACT_VERSION=timeline_cards_bridge.CONTRACT_VERSION,
        SyncEngine=_NoBridgeEngine),                               # no bridge arg
])
def test_the_contract_refusals_carry_no_bug_id_or_doc_section(engine_mod):
    """HEAD: "(CR-68)", "(docs/TIMELINE-CARDS-INTO-CCSYNC.md §7c)" and
    "(§7c: SyncEngine(root, bridge=...))" in text the dashboard's machine row
    shows an admin."""
    with pytest.raises(timeline_cards_role.CardsRoleError) as info:
        timeline_cards_role.check_contract(engine_mod)
    text = str(info.value)
    assert "CR-68" not in text and "7c" not in text and "docs/" not in text
    assert "SyncEngine(root" not in text
    assert "—" not in text
