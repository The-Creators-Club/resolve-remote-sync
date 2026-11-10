"""The TeraCopy driver: a port of footage-sorter test/teracopy.test.js.

SAFETY: nothing here launches TeraCopy, reads the real %APPDATA% history or
touches footage. Every job database is a fixture built under tmp_path to the
same schema as the real ones (Files/Run/Target/Source, from
%APPDATA%\\TeraCopy\\History), the clock, the process check and the spawn are
injected, and the sleep moves a fake clock instead of waiting.
"""
from __future__ import annotations

import os
import sqlite3
import time
from pathlib import Path

import sys

import pytest

from ccsync_companion import teracopy as tc_mod
from ccsync_companion.teracopy import (
    TeraCopy, copy_command, harvest, ini_get, parse_options_ini, read_status)

# A Windows FILETIME, as TeraCopy really stores Files.Created/Modified/Accessed
# (past 2**53: the Node original had to name its columns to avoid a throw; here
# the fixtures carry it so a regression to `select *` is at least exercised).
# Launching TeraCopy is Windows-only (it is a Windows program; a Mac copies with the Python copier).
WINDOWS_ONLY = pytest.mark.skipif(sys.platform != "win32", reason="TeraCopy runs on Windows only")

FILETIME = 134304963240000000

# The real schema, copied from %APPDATA%\TeraCopy\History\*.db.
SCHEMA = """
CREATE TABLE Files ( Source TEXT, Offset INTEGER, Visibility INTEGER, Size INTEGER,
  Attributes INTEGER, IsFolder INTEGER, Created INTEGER, Modified INTEGER,
  Accessed INTEGER, Checksum TEXT, Marked INTEGER DEFAULT 0, Selected INTEGER DEFAULT 1 );
CREATE TABLE "Run" ( "mode" INTEGER, "target" TEXT, "options" TEXT, "started" DATETIME,
  "finished" DATETIME, "speed" REAL, "results" TEXT );
CREATE TABLE "Source" ( "file" INTEGER UNIQUE, "result" INTEGER, "hash" TEXT,
  "message" TEXT, PRIMARY KEY("file") );
CREATE TABLE "Target" ( "file" INTEGER, "id" INTEGER, "result" INTEGER, "hash" TEXT,
  "message" TEXT, "filename" TEXT, UNIQUE("file","id") );
"""

COPY, VERIFY = 1, 4
STARTED = "2026-08-13T15:17:57.570Z"
FINISHED = "2026-08-13T15:18:12.199Z"
DEST = "W:\\Temp Transfer\\2026-08-05 BMCC"
CLOCK0 = 1786000000.0


def since() -> float:
    return time.time() - 60          # fixtures are created now, so they match


def make_db(file: Path, files=(), runs=(), targets=()) -> Path:
    file.parent.mkdir(parents=True, exist_ok=True)
    db = sqlite3.connect(file)
    db.executescript(SCHEMA)
    for f in files:
        db.execute("insert into Files (Source,Offset,Visibility,Size,Attributes,IsFolder,Created,"
                   "Modified,Accessed,Checksum,Marked,Selected) values (?,?,?,?,?,?,?,?,?,?,?,?)",
                   (f["source"], 0, 0, f.get("size", 0), 32, 1 if f.get("folder") else 0,
                    FILETIME, FILETIME, FILETIME, "", 0, 1))
    for r in runs:
        db.execute("insert into Run (mode,target,options,started,finished,speed,results)"
                   " values (?,?,?,?,?,?,?)",
                   (r["mode"], r["target"], '{"hash":"xxHash3-64"}', STARTED,
                    r.get("finished"), 382.07, None))
    for t in targets:
        db.execute("insert into Target (file,id,result,hash,message,filename) values (?,?,?,?,?,?)",
                   (t["file"], 0, t["result"], t.get("hash", ""), t.get("message", ""),
                    t.get("filename", "")))
        db.execute("insert into Source (file,result,hash,message) values (?,?,?,?)",
                   (t["file"], 10, t.get("hash", ""), ""))
    db.commit()
    db.close()
    return file


def both_phases(dest=DEST):
    return [{"mode": COPY, "target": dest, "finished": FINISHED},
            {"mode": VERIFY, "target": dest, "finished": FINISHED}]


class Clock:
    """Moves only when the driver sleeps: no test ever waits for real."""

    def __init__(self):
        self.t = CLOCK0

    def now(self):
        return self.t

    def sleep(self, seconds):
        self.t += float(seconds)


def status_of(**extra):
    base = {"state": "running", "found": True, "copy_done": False, "verify_seen": False,
            "verify_done": False, "total": 0, "ok": 0, "bad": 0, "db_path": None,
            "db_name": None, "error": None}
    base.update(extra)
    return base


@pytest.fixture()
def exe(tmp_path):
    # a fake TeraCopy.exe with a space in its path, so the quoting is real
    p = tmp_path / "Program Files" / "TeraCopy" / "TeraCopy.exe"
    p.parent.mkdir(parents=True)
    p.write_bytes(b"MZ fake")
    return str(p)


@pytest.fixture()
def driver(tmp_path, exe):
    def make(**over):
        clock = Clock()
        logs: list[str] = []
        calls: list[str] = []

        class Child:
            pid = 77

        def spawn(cmd):
            """The stub: records the command and, like TeraCopy, registers the job in its history
            (a database listing the job's files and destination) so the launch's wait is over."""
            calls.append(cmd)
            parts = [p for p in cmd.split('"') if p.strip() and not p.strip().startswith("/")]
            listing, target = parts[-2].lstrip("*"), parts[-1]
            try:
                srcs = Path(listing).read_text(encoding="utf-8").splitlines()
            except OSError:
                srcs = []
            hdir = Path(kw["history_dir"])
            if hdir.name == "no-history":
                make_db(hdir / f"auto-{len(calls)}.db", [{"source": f, "size": 1} for f in srcs if f],
                        [{"mode": COPY, "target": target}])
            return Child()

        kw = dict(history_dir=str(tmp_path / "no-history"), options_ini=str(tmp_path / "Options.ini"),
                  list_dir=str(tmp_path / "lists"), now=clock.now, sleep=clock.sleep,
                  is_running=lambda: True, spawn=spawn,
                  log_fn=lambda msg, level="info": logs.append(str(msg)))
        kw.update(over)
        t = TeraCopy(exe, **kw)
        return t, clock, logs, calls
    return make


def hist(tmp_path, name) -> Path:
    d = tmp_path / "hist" / name
    d.mkdir(parents=True)
    return d


# --------------------------------------------------------------- read_status
def test_no_job_to_see(tmp_path):
    assert read_status(tmp_path / "nope", DEST, since())["state"] == "missing"
    assert read_status(tmp_path / "nope", DEST, since())["error"] == "no-history-dir"
    assert read_status(hist(tmp_path, "empty"), DEST, since())["state"] == "missing"
    assert read_status(hist(tmp_path, "empty2"), DEST, "not-a-time")["state"] == "missing"


def test_a_database_older_than_since_is_not_this_job(tmp_path):
    d = hist(tmp_path, "older")
    make_db(d / "260813-071756-981-400.db", [{"source": "L:\\a.MP4", "size": 10}], both_phases(),
            [{"file": 1, "result": 3, "hash": "F437D984042F8648"}])
    st = read_status(d, DEST, time.time() + 100)
    assert st["state"] == "missing" and st["found"] is False
    assert read_status(d, DEST, since())["state"] == "done"
    assert read_status(d, DEST, time.time() + 3)["state"] == "done"      # the 5 s slack


def test_a_database_that_existed_before_the_launch_is_excluded(tmp_path):
    # found live 2026-11-09: a job launched right after an identical one read
    # its predecessor's finished record and returned at once
    d = hist(tmp_path, "exclude")
    make_db(d / "old.db", [{"source": "L:\\a.MP4", "size": 1}], both_phases(),
            [{"file": 1, "result": 3, "hash": "AA"}])
    assert read_status(d, DEST, since())["state"] == "done"
    assert read_status(d, DEST, since(), exclude={"old.db"})["state"] == "missing"


def test_a_fresh_database_with_no_run_row_is_queued(tmp_path):
    d = hist(tmp_path, "queued")
    make_db(d / "q.db", [{"source": "L:\\a.MP4", "size": 10}])
    st = read_status(d, DEST, since())
    assert st["state"] == "queued" and st["found"] is False


def test_copy_phase_unfinished_is_running(tmp_path):
    d = hist(tmp_path, "running")
    make_db(d / "r.db", [{"source": "L:\\a.MP4", "size": 10}, {"source": "L:\\b.MP4", "size": 20}],
            [{"mode": COPY, "target": DEST}], [{"file": 1, "result": 1, "hash": "AA"}])
    st = read_status(d, DEST, since())
    assert (st["state"], st["copy_done"], st["total"], st["ok"], st["bad"]) == ("running", False, 2, 0, 2)


def test_copy_finished_without_a_verify_pass_is_copied(tmp_path):
    d = hist(tmp_path, "copied")
    make_db(d / "c.db", [{"source": "L:\\a.MP4", "size": 10}],
            [{"mode": COPY, "target": DEST, "finished": FINISHED}], [{"file": 1, "result": 1, "hash": "AA"}])
    st = read_status(d, DEST, since())
    assert (st["state"], st["verify_seen"], st["verify_done"], st["bad"]) == ("copied", False, False, 1)


def test_verify_started_but_unfinished_is_still_copied(tmp_path):
    d = hist(tmp_path, "verifying")
    make_db(d / "v.db", [{"source": "L:\\a.MP4", "size": 10}],
            [{"mode": COPY, "target": DEST, "finished": FINISHED}, {"mode": VERIFY, "target": DEST}],
            [{"file": 1, "result": 1, "hash": "AA"}])
    st = read_status(d, DEST, since())
    assert (st["state"], st["verify_seen"], st["verify_done"]) == ("copied", True, False)


def test_copy_and_verify_finished_with_every_result_3_is_done(tmp_path):
    d = hist(tmp_path, "done")
    make_db(d / "d.db",
            [{"source": "L:\\PRIVATE\\M4ROOT\\CLIP\\fx3_20260806_0756.MP4", "size": 67687924},
             {"source": "L:\\PRIVATE\\M4ROOT\\CLIP\\fx3_20260806_0756M01.XML", "size": 2294},
             {"source": "L:\\PRIVATE\\M4ROOT\\CLIP", "size": 0, "folder": True}],
            both_phases(), [{"file": 1, "result": 3, "hash": "5640D6C2B31C1792"},
                            {"file": 2, "result": 3, "hash": "6D7210C00E0CBB88"}])
    st = read_status(d, DEST, since())
    assert (st["state"], st["found"], st["total"], st["ok"], st["bad"], st["db_name"]) == (
        "done", True, 2, 2, 0, "d.db")
    assert st["db_path"] == str(d / "d.db")


def test_a_file_with_no_target_row_counts_as_bad(tmp_path):
    d = hist(tmp_path, "untouched")
    make_db(d / "d.db", [{"source": f"L:\\{n}.MP4", "size": 1} for n in "abc"], both_phases(),
            [{"file": 1, "result": 3, "hash": "AA"}, {"file": 2, "result": 3, "hash": "BB"}])
    st = read_status(d, DEST, since())
    assert (st["bad"], st["ok"], st["total"]) == (1, 2, 3)


def test_a_job_into_another_folder_is_not_this_job(tmp_path):
    d = hist(tmp_path, "other-target")
    other = "W:\\Temp Transfer\\SOMEWHERE ELSE"
    make_db(d / "d.db", [{"source": "L:\\a.MP4", "size": 1}], both_phases(other),
            [{"file": 1, "result": 3, "hash": "AA"}])
    assert read_status(d, DEST, since())["state"] == "missing"


@pytest.mark.parametrize("dest", ["w:\\temp transfer\\2026-08-05 bmcc", DEST + "\\", DEST + "/", DEST + "\\\\"])
def test_the_destination_match_is_case_and_trailing_separator_blind(tmp_path, dest):
    d = hist(tmp_path, "case")
    make_db(d / "d.db", [{"source": "L:\\a.MP4", "size": 1}], both_phases(),
            [{"file": 1, "result": 3, "hash": "AA"}])
    assert read_status(d, dest, since())["state"] == "done"


def test_the_newest_matching_database_wins(tmp_path):
    d = hist(tmp_path, "newest")
    make_db(d / "a-old.db", [{"source": "L:\\old.MP4", "size": 1}], both_phases(),
            [{"file": 1, "result": 3, "hash": "AA"}])
    time.sleep(0.05)
    make_db(d / "z-new.db", [{"source": "L:\\n1.MP4", "size": 1}, {"source": "L:\\n2.MP4", "size": 2}],
            [{"mode": COPY, "target": DEST, "finished": FINISHED}], [{"file": 1, "result": 3, "hash": "BB"}])
    st = read_status(d, DEST, since())
    assert (st["db_name"], st["state"], st["total"]) == ("z-new.db", "copied", 2)


def test_two_cards_copying_into_one_folder_read_their_own_records(tmp_path):
    d = hist(tmp_path, "two-cards")
    make_db(d / "a-cardH.db", [{"source": "H:\\PRIVATE\\M4ROOT\\CLIP\\A001.MP4", "size": 1}],
            both_phases(), [{"file": 1, "result": 3, "hash": "AA"}])
    time.sleep(0.05)
    make_db(d / "b-cardN.db", [{"source": "N:\\PRIVATE\\M4ROOT\\CLIP\\B001.MP4", "size": 1},
                               {"source": "N:\\PRIVATE\\M4ROOT\\CLIP\\B002.MP4", "size": 1}],
            [{"mode": COPY, "target": DEST}])
    H = ["H:\\PRIVATE\\M4ROOT\\CLIP\\A001.MP4"]
    N = ["n:\\private\\m4root\\clip\\B001.mp4", "N:\\PRIVATE\\M4ROOT\\CLIP\\B002.MP4"]
    assert read_status(d, DEST, since())["db_name"] == "b-cardN.db"      # the old hazard
    h = read_status(d, DEST, since(), H)
    assert (h["db_name"], h["state"]) == ("a-cardH.db", "done")
    n = read_status(d, DEST, since(), N)
    assert (n["db_name"], n["state"]) == ("b-cardN.db", "running")
    assert read_status(d, DEST, since(), ["K:\\DCIM\\100MEDIA\\DJI_0001.MP4"])["state"] == "missing"


def test_a_folder_job_is_matched_by_the_files_inside_the_folder(tmp_path):
    d = hist(tmp_path, "folder-job")
    make_db(d / "seq.db", [{"source": "J:\\SEQ_001\\frame_0001.dng", "size": 1}], both_phases(),
            [{"file": 1, "result": 3, "hash": "AA"}])
    assert read_status(d, DEST, since(), ["J:\\SEQ_001"])["state"] == "done"
    assert read_status(d, DEST, since(), ["J:\\SEQ_00"])["state"] == "missing"


def test_an_unreadable_database_is_locked_never_a_finished_job(tmp_path):
    d = hist(tmp_path, "locked")
    (d / "x.db").write_text("this is not a sqlite file, it is half-written rubbish")
    st = read_status(d, DEST, since())
    assert st["state"] == "locked" and st["found"] is False


def test_a_broken_neighbour_does_not_hide_a_readable_job(tmp_path):
    d = hist(tmp_path, "locked-plus-good")
    (d / "a-broken.db").write_text("rubbish")
    make_db(d / "b-good.db", [{"source": "L:\\a.MP4", "size": 1}], both_phases(),
            [{"file": 1, "result": 3, "hash": "AA"}])
    st = read_status(d, DEST, since())
    assert (st["state"], st["db_name"]) == ("done", "b-good.db")


def test_teracopys_own_main_db_is_never_a_job_record(tmp_path):
    d = hist(tmp_path, "main-db")
    make_db(d / "main.db", [{"source": "L:\\a.MP4", "size": 1}], both_phases(),
            [{"file": 1, "result": 3, "hash": "AA"}])
    assert read_status(d, DEST, since())["state"] == "missing"


# ------------------------------------------------------------------- harvest
def test_harvest_reports_each_file(tmp_path):
    d = hist(tmp_path, "harvest")
    db = make_db(d / "h.db",
                 [{"source": "L:\\PRIVATE\\M4ROOT\\CLIP\\fx3_20260806_0756.MP4", "size": 67687924},
                  {"source": "L:\\PRIVATE\\M4ROOT\\CLIP\\fx3_20260806_0757.MP4", "size": 201907194},
                  {"source": "L:\\PRIVATE\\M4ROOT\\CLIP\\never_reached.MP4", "size": 123},
                  {"source": "L:\\PRIVATE\\M4ROOT\\CLIP", "size": 0, "folder": True}],
                 both_phases(),
                 [{"file": 1, "result": 3, "hash": "5640D6C2B31C1792"},
                  {"file": 2, "result": 1, "hash": "EEFCA28F4CD0DBF0",
                   "filename": "fx3_20260806_0757 (2).MP4"}])
    rows = harvest(db)
    assert len(rows) == 4
    assert rows[0]["source"].endswith("fx3_20260806_0756.MP4") and rows[0]["size"] == 67687924
    assert rows[0]["verified"] is True and rows[0]["hash"] == "5640D6C2B31C1792"
    assert rows[0]["filename"] is None and rows[0]["is_folder"] is False
    assert rows[1]["verified"] is False                       # result 1: copied, not verified
    assert rows[1]["filename"] == "fx3_20260806_0757 (2).MP4" and rows[1]["hash"] == "EEFCA28F4CD0DBF0"
    assert rows[2]["verified"] is False and rows[2]["result"] is None and rows[2]["hash"] is None
    assert rows[3]["is_folder"] is True


# ---------------------------------------------------------------- wait_for_job
def test_done_on_the_first_poll_returns_at_once(driver):
    t, clock, logs, _ = driver(read_status_fn=lambda *a: status_of(state="done", total=3, ok=3))
    ticks = []
    st = t.wait_for_job(DEST, 1, tag="A-CAM", on_tick=lambda s, e: ticks.append((s["state"], e)))
    assert st["state"] == "done" and clock.t == CLOCK0 and ticks == [("done", 0)] and logs == []


def test_a_copy_with_no_verify_pass_gives_up_after_the_verify_grace(driver):
    t, clock, logs, _ = driver(read_status_fn=lambda *a: status_of(
        state="copied", copy_done=True, total=3, ok=2, bad=1))
    ticks = []
    st = t.wait_for_job(DEST, 1, tag="A-CAM", on_tick=lambda s, e: ticks.append(1))
    assert st["state"] == "copied"
    assert clock.t - CLOCK0 == 180 and len(ticks) == 37
    assert any("copy finished but no verify pass after 180s." in m for m in logs)
    assert any(m == "TeraCopy (A-CAM): copied, 2/3 file(s) verified, 1 min elapsed." for m in logs)
    assert len([m for m in logs if "min elapsed" in m]) == 2


def test_with_verify_off_the_wait_ends_when_the_copy_does(driver):
    t, clock, logs, _ = driver(read_status_fn=lambda *a: status_of(state="copied", copy_done=True))
    st = t.wait_for_job(DEST, 1, expect_verify=False)
    assert st["state"] == "copied" and clock.t == CLOCK0


def test_teracopy_gone_with_a_job_on_record_ends_the_wait_at_the_idle_grace(driver):
    t, clock, logs, _ = driver(read_status_fn=lambda *a: status_of(state="running"),
                               is_running=lambda: False)
    st = t.wait_for_job(DEST, 1, tag="A-CAM")
    assert st["state"] == "running" and clock.t - CLOCK0 == 60
    assert not any("process gone" in m for m in logs)


def test_teracopy_gone_and_no_record_falls_back_to_a_destination_check(driver):
    t, clock, logs, _ = driver(read_status_fn=lambda *a: status_of(state="missing", found=False),
                               is_running=lambda: False)
    st = t.wait_for_job(DEST, 1, tag="A-CAM")
    assert st["state"] == "missing" and clock.t - CLOCK0 == 60
    assert any("process gone; falling back to a destination check." in m for m in logs)


def test_nothing_ever_appearing_gives_up_at_the_start_grace(driver):
    t, clock, logs, _ = driver(read_status_fn=lambda *a: status_of(state="missing", found=False),
                               is_running=lambda: False, idle_grace_seconds=100000)
    st = t.wait_for_job(DEST, 1, tag="A-CAM")
    assert st["state"] == "missing" and clock.t - CLOCK0 == 120
    assert any("no job started within 120s." in m for m in logs)


def test_a_job_that_never_finishes_gives_up_at_the_timeout(driver):
    t, clock, logs, _ = driver(read_status_fn=lambda *a: status_of(state="running", total=10, ok=4),
                               timeout_minutes=1)
    st = t.wait_for_job(DEST, 1, tag="A-CAM")
    assert st["state"] == "running" and clock.t - CLOCK0 == 60
    assert any("still unfinished after 1 min; giving up waiting." in m for m in logs)


def test_a_job_that_starts_late_is_waited_out(driver):
    n = {"n": 0}

    def reader(*a):
        n["n"] += 1
        if n["n"] < 4:
            return status_of(state="queued", found=False)
        if n["n"] < 8:
            return status_of(state="running", total=2)
        return status_of(state="done", copy_done=True, verify_done=True, total=2, ok=2)

    t, clock, _, _ = driver(read_status_fn=reader)
    assert t.wait_for_job(DEST, 1, tag="A-CAM")["state"] == "done"
    assert clock.t - CLOCK0 == 35


def test_a_tick_that_raises_does_not_break_the_wait(driver):
    t, _, _, _ = driver(read_status_fn=lambda *a: status_of(state="done"))

    def boom(*a):
        raise RuntimeError("ui")

    assert t.wait_for_job(DEST, 1, on_tick=boom)["state"] == "done"


# ---------------------------------------------------------------------- launch
@WINDOWS_ONLY
def test_launch_writes_the_list_and_builds_the_exact_command(driver, tmp_path, exe):
    t, clock, _, calls = driver(list_dir=str(tmp_path / "data" / "lists"))
    dest = str(tmp_path / "W" / "Temp Transfer" / "2026-08-05 BMCC")
    files = [str(tmp_path / "card" / "fx3_20260806_0756.MP4"),
             "L:\\PRIVATE\\鍾綺 interview\\陳昭姿 0001.MP4"]
    res = t.launch(files, dest, "/OverwriteDiffSize", "A-CAM 21.25")
    assert res["since"] == int(clock.t) and res["pid"] == 77
    assert res["list_file"] == str(tmp_path / "data" / "lists" / f"A-CAM_21_25-{res['since']}.txt")
    raw = Path(res["list_file"]).read_bytes()
    assert raw[:3] != b"\xef\xbb\xbf"                        # no BOM
    assert raw.decode("utf-8") == "\r\n".join(files) + "\r\n"
    assert not [n for n in os.listdir(tmp_path / "data" / "lists") if ".tmp" in n]
    assert os.path.isdir(dest)
    assert calls == [f'"{exe}" Copy *"{res["list_file"]}" "{dest}" /OverwriteDiffSize /Close']


@WINDOWS_ONLY
def test_two_jobs_with_one_tag_in_one_second_get_two_list_files(driver, tmp_path):
    t, _, _, _ = driver()
    a = t.launch(["H:\\a.MP4"], str(tmp_path / "d"), tag="Interview")
    b = t.launch(["N:\\b.MP4"], str(tmp_path / "d"), tag="Interview")
    assert a["list_file"] != b["list_file"]
    assert Path(a["list_file"]).read_bytes() == b"H:\\a.MP4\r\n"
    assert Path(b["list_file"]).read_bytes() == b"N:\\b.MP4\r\n"


@WINDOWS_ONLY
def test_launch_snapshots_the_history_so_the_job_can_exclude_its_predecessors(driver, tmp_path):
    d = hist(tmp_path, "snap")
    make_db(d / "old.db", [{"source": "L:\\a.MP4", "size": 1}])
    t, _, _, _ = driver(history_dir=str(d))
    assert t.launch(["L:\\a.MP4"], str(tmp_path / "d"), tag="x")["known"] == {"old.db"}


def test_an_empty_list_or_a_quote_in_a_path_is_refused(driver, tmp_path):
    t, _, _, _ = driver()
    with pytest.raises(ValueError):
        t.launch([], str(tmp_path / "x"))
    assert copy_command("T.exe", "L.txt", 'W:\\a"b', "/OverwriteDiffSize") is None
    assert copy_command("T.exe", "L.txt", "", "/OverwriteDiffSize") is None
    assert copy_command("T.exe", "L.txt", "D", "/RenameCopied") == \
        '"T.exe" Copy *"L.txt" "D" /RenameCopied /Close'


def test_a_launch_that_fails_is_logged_not_raised(driver, tmp_path):
    def spawn(cmd):
        raise OSError("no such exe")

    t, _, logs, _ = driver(spawn=spawn)
    res = t.launch(["L:\\a.MP4"], str(tmp_path / "d"), tag="x")
    assert res["pid"] is None and any("could not launch" in m for m in logs)


# ----------------------------------------------------------------- check_landed
def test_check_landed(tmp_path):
    src = tmp_path / "src"
    out = tmp_path / "landed"
    src.mkdir()
    out.mkdir()
    a, b = src / "fx3_0001.MP4", src / "陳昭姿 0002.MP4"
    a.write_bytes(b"a" * 10)
    b.write_bytes(b"b" * 20)
    (out / a.name).write_bytes(a.read_bytes())
    (out / b.name).write_bytes(b.read_bytes())
    r = TeraCopy.check_landed([str(a), str(b)], str(out))
    assert (r["checked"], r["missing"], r["wrong_size"]) == (2, 0, 0)
    assert all(f["landed"] for f in r["files"]) and r["files"][0]["dst"] == str(out / a.name)
    (out / b.name).write_bytes(b"short")
    r2 = TeraCopy.check_landed([str(a), str(b)], str(out))
    assert r2["wrong_size"] == 1 and r2["files"][1]["landed"] is False
    assert (r2["files"][1]["src_size"], r2["files"][1]["dst_size"]) == (20, 5)
    (out / b.name).unlink()
    assert TeraCopy.check_landed([str(a), str(b)], str(out))["missing"] == 1
    r4 = TeraCopy.check_landed([str(a), str(src / "gone.MP4")], str(out))
    assert (r4["checked"], r4["missing"], len(r4["files"]), r4["files"][1]["landed"]) == (1, 0, 2, False)


# -------------------------------------------------------------------- copy_group
def _files(tmp_path):
    src = tmp_path / "src"
    src.mkdir()
    a, b = src / "fx3_0001.MP4", src / "陳昭姿 0002.MP4"
    a.write_bytes(b"a" * 10)
    b.write_bytes(b"b" * 20)
    return str(a), str(b)


def test_nothing_to_copy_launches_nothing(driver, tmp_path):
    t, _, _, calls = driver()
    r = t.copy_group([], str(tmp_path / "d"))
    assert r["code"] is None and r["list_file"] is None and calls == []


@WINDOWS_ONLY
def test_a_verified_job_is_code_0_and_reads_its_own_record(driver, tmp_path):
    a, b = _files(tmp_path)
    d = hist(tmp_path, "cg-done")
    db = make_db(d / "g.db", [{"source": a, "size": 10}, {"source": b, "size": 20}], both_phases(),
                 [{"file": 1, "result": 3, "hash": "AA"}, {"file": 2, "result": 3, "hash": "BB"}])
    asked = {}

    def reader(dest, sin, sources, exclude=None):
        asked["sources"], asked["exclude"] = sources, exclude
        return read_status(d, DEST, since(), sources)

    t, _, logs, calls = driver(read_status_fn=reader)
    r = t.copy_group([a, b], str(tmp_path / "dest-done"), "/OverwriteDiffSize", "A-CAM")
    assert asked["sources"] == [a, b] and asked["exclude"] == set()
    assert r["code"] == 0 and r["status"]["db_path"] == str(db)
    assert [x["verified"] for x in r["receipts"]] == [True, True] and r["receipts"][0]["hash"] == "AA"
    assert len(calls) == 1 and os.path.exists(r["list_file"])
    assert any("2/2 file(s) copied and verified." in m for m in logs)


@WINDOWS_ONLY
def test_a_finished_job_with_an_unverified_file_is_code_10(driver, tmp_path):
    a, b = _files(tmp_path)
    d = hist(tmp_path, "cg-unver")
    make_db(d / "g.db", [{"source": a, "size": 10}, {"source": b, "size": 20}], both_phases(),
            [{"file": 1, "result": 3, "hash": "AA"}, {"file": 2, "result": 1, "hash": "BB"}])
    t, _, logs, _ = driver(read_status_fn=lambda *x: read_status(d, DEST, since()))
    r = t.copy_group([a, b], str(tmp_path / "dest-unver"), tag="A-CAM")
    assert r["code"] == 10 and r["receipts"][1]["verified"] is False
    assert any("finished with 1 of 2 file(s) not verified." in m for m in logs)


@WINDOWS_ONLY
def test_no_record_but_every_file_present_is_code_12_unconfirmed(driver, tmp_path):
    a, b = _files(tmp_path)
    dest = tmp_path / "dest-fallback"
    dest.mkdir()
    (dest / os.path.basename(a)).write_bytes(Path(a).read_bytes())
    (dest / os.path.basename(b)).write_bytes(Path(b).read_bytes())
    t, _, logs, _ = driver(read_status_fn=lambda *x: read_status(tmp_path / "no-history", DEST, since()),
                           is_running=lambda: False)
    r = t.copy_group([a, b], str(dest), tag="A-CAM")
    assert r["code"] == 12
    assert all(x["landed"] is True and x["verified"] is False and x["hash"] is None for x in r["receipts"])
    assert any("UNCONFIRMED" in m for m in logs)


@WINDOWS_ONLY
def test_a_file_missing_from_the_destination_is_code_11(driver, tmp_path):
    a, b = _files(tmp_path)
    dest = tmp_path / "dest-missing"
    dest.mkdir()
    (dest / os.path.basename(a)).write_bytes(Path(a).read_bytes())
    t, _, logs, _ = driver(read_status_fn=lambda *x: read_status(tmp_path / "no-history", DEST, since()),
                           is_running=lambda: False)
    r = t.copy_group([a, b], str(dest), tag="A-CAM")
    assert r["code"] == 11 and [x["landed"] for x in r["receipts"]] == [True, False]
    assert any("1 file(s) missing and 0 with a different size" in m for m in logs)


@WINDOWS_ONLY
def test_verify_off_and_allowed_reports_the_copy_as_unverified(driver, tmp_path):
    a, b = _files(tmp_path)
    d = hist(tmp_path, "cg-noverify")
    make_db(d / "g.db", [{"source": a, "size": 10}],
            [{"mode": COPY, "target": DEST, "finished": FINISHED}], [{"file": 1, "result": 1, "hash": "AA"}])
    t, clock, _, _ = driver(read_status_fn=lambda *x: read_status(d, DEST, since()))
    r = t.copy_group([a], str(tmp_path / "dest-nv"), tag="x", expect_verify=False)
    assert r["code"] == 10 and r["receipts"][0]["verified"] is False and clock.t == CLOCK0


# ------------------------------------------------------- options.ini / install
def test_parse_options_ini():
    ini = "\r\n".join(["; TeraCopy options", "", "[Main]", "Language=en", "", "[Transfer]",
                       "TestAlways=1", "Jobs=1", "", "[OnFinish]", "SaveReport.Enabled=0",
                       "# trailing comment"])
    p = parse_options_ini(ini)
    assert p["Transfer"]["TestAlways"] == "1" and p["OnFinish"]["SaveReport.Enabled"] == "0"
    assert p["Transfer"]["Jobs"] == "1"
    assert ini_get(p, "transfer", "TestAlways") == "1" and ini_get(p, "Transfer", "testalways") == "1"
    assert ini_get(p, "Transfer", "Nope") is None and ini_get(p, "Nope", "TestAlways") is None
    assert parse_options_ini("\ufeff[Transfer]\nTestAlways=1")["Transfer"]["TestAlways"] == "1"
    assert parse_options_ini("[A]\nk=a=b")["A"]["k"] == "a=b"
    assert list(parse_options_ini("")) == [""]


def test_check_a_full_install(driver, tmp_path):
    (tmp_path / "Options.ini").write_text("[Transfer]\r\nTestAlways=1\r\nJobs=1\r\n")
    h = hist(tmp_path, "check")
    t, _, _, _ = driver(history_dir=str(h))
    c = t.check()
    assert (c["ok"], c["exe_present"], c["verify_on"], c["warnings"]) == (True, True, True, [])


def test_check_verify_off_says_how_to_fix_it(driver, tmp_path):
    (tmp_path / "Options.ini").write_text("[Transfer]\r\nTestAlways=0\r\n")
    t, _, _, _ = driver(history_dir=str(hist(tmp_path, "check2")))
    c = t.check()
    assert c["verify_on"] is False and c["ok"] is True
    assert any("TestAlways=1" in w for w in c["warnings"])


def test_check_with_no_install_warns_about_three_things(tmp_path):
    t = TeraCopy(str(tmp_path / "nope" / "TeraCopy.exe"), history_dir=str(tmp_path / "nope" / "History"),
                 options_ini=str(tmp_path / "nope" / "Options.ini"))
    c = t.check()
    assert (c["ok"], c["exe_present"], c["verify_on"], len(c["warnings"])) == (False, False, False, 3)


def test_constructing_with_nothing_installed_never_raises():
    TeraCopy("Q:\\nope.exe", history_dir="Q:\\nope", options_ini="Q:\\nope.ini")


# ------------------------------------------------------------------ detect
@pytest.mark.skipif(os.name != "nt", reason="TeraCopy is Windows-only")
class TestDetect:
    @pytest.fixture(autouse=True)
    def _real_detect(self, monkeypatch, tmp_path, exe):
        # a fake install and a temp Options.ini, never the real %APPDATA%
        monkeypatch.setenv("APPDATA", str(tmp_path / "appdata"))
        (tmp_path / "appdata" / "TeraCopy").mkdir(parents=True)
        self.exe, self.ini = exe, tmp_path / "appdata" / "TeraCopy" / "Options.ini"

    def test_found_when_installed_with_verify_on(self):
        self.ini.write_text("[Transfer]\nTestAlways=1\n")
        t, why = tc_mod.detect_here({"teracopy_path": self.exe})
        assert t is not None and t.exe == self.exe and why == ""

    def test_not_used_with_verify_off_unless_allowed(self):
        self.ini.write_text("[Transfer]\nTestAlways=0\n")
        t, why = tc_mod.detect_here({"teracopy_path": self.exe})
        assert t is None and "TestAlways=1" in why
        assert tc_mod.detect_here({"teracopy_path": self.exe, "teracopy_allow_unverified": True})[0] is not None

    def test_the_python_copier_can_be_chosen(self):
        self.ini.write_text("[Transfer]\nTestAlways=1\n")
        assert tc_mod.detect_here({"teracopy_path": self.exe, "card_copier": "python"})[0] is None

    def test_a_missing_exe_is_not_found(self, tmp_path):
        assert tc_mod.detect_here({"teracopy_path": str(tmp_path / "nope.exe")})[0] is None

    def test_capabilities_report_install_and_verify(self):
        self.ini.write_text("[Transfer]\nTestAlways=1\n")
        assert tc_mod.status_for_capabilities({"teracopy_path": self.exe}) == (True, True)
        self.ini.write_text("[Transfer]\nTestAlways=0\n")
        assert tc_mod.status_for_capabilities({"teracopy_path": self.exe}) == (True, False)
        assert tc_mod.status_for_capabilities({"teracopy_path": "Q:\\none.exe"}) == (False, False)


# ------------------------------------------- stop, time limit, verify in progress
def test_a_stop_ends_the_wait_on_the_next_poll_without_killing_anything(driver):
    t, clock, logs, _ = driver(read_status_fn=lambda *a: status_of(state="running", total=2))
    polls = {"n": 0}

    def stop():
        polls["n"] += 1
        return "a fleet halt stopped this job" if polls["n"] >= 3 else ""

    st = t.wait_for_job(DEST, 1, tag="A-CAM", should_stop=stop)
    assert st["stopped"] == "a fleet halt stopped this job" and polls["n"] == 3
    assert clock.t - CLOCK0 == 10                         # two sleeps, then out


def test_a_wait_has_the_limit_it_is_given_and_a_verify_pass_is_inside_it(driver):
    t, clock, logs, _ = driver(read_status_fn=lambda *a: status_of(
        state="copied", copy_done=True, verify_seen=True, total=2, ok=1, bad=1))
    st = t.wait_for_job(DEST, 1, tag="A-CAM", max_seconds=900)
    assert st["state"] == "copied" and clock.t - CLOCK0 == 900      # not cut at the 180 s grace
    assert any("still unfinished after 15 min" in m for m in logs)
    assert not any("no verify pass" in m for m in logs)


def test_a_verify_pass_that_finishes_after_the_grace_is_waited_for(driver):
    n = {"n": 0}

    def reader(*a):
        n["n"] += 1
        if n["n"] < 100:                                  # 500 s of verifying
            return status_of(state="copied", copy_done=True, verify_seen=True, total=1, bad=1)
        return status_of(state="done", copy_done=True, verify_seen=True, verify_done=True, total=1, ok=1)

    t, clock, _, _ = driver(read_status_fn=reader)
    assert t.wait_for_job(DEST, 1, max_seconds=3600)["state"] == "done"
    assert clock.t - CLOCK0 > 180


def test_the_default_limit_is_30_minutes_plus_20_mb_a_second():
    assert tc_mod.wait_limit_seconds(0) == 1800
    assert tc_mod.wait_limit_seconds(20 * 1024 * 1024 * 100) == 1800 + 100


@WINDOWS_ONLY
def test_copy_group_gives_up_at_the_scaled_default_limit(driver, tmp_path):
    a, b = _files(tmp_path)
    t, clock, logs, _ = driver(read_status_fn=lambda *a: status_of(state="running", total=2))
    t.copy_group([a, b], str(tmp_path / "dest-hang"), tag="x")
    assert 1800 <= clock.t - CLOCK0 < 1810


@WINDOWS_ONLY
def test_a_stopped_copy_group_reports_unverified_files_as_not_landed(driver, tmp_path):
    a, b = _files(tmp_path)
    d = hist(tmp_path, "cg-stop")
    make_db(d / "g.db", [{"source": a, "size": 10}, {"source": b, "size": 20}],
            [{"mode": COPY, "target": DEST, "finished": FINISHED}],
            [{"file": 1, "result": 3, "hash": "AA"}, {"file": 2, "result": 1, "hash": "BB"}])
    t, _, _, _ = driver(read_status_fn=lambda *x: read_status(d, DEST, since()))
    r = t.copy_group([a, b], str(tmp_path / "dest-stop"), tag="x", should_stop=lambda: "halt")
    assert r["code"] == tc_mod.CODE_STOPPED and r["stopped"] == "halt"
    assert [(x["verified"], x["landed"]) for x in r["receipts"]] == [(True, True), (False, False)]


def test_a_plain_copy_defaults_to_skipall():
    assert tc_mod.DEFAULT_SWITCH == "/SkipAll" == tc_mod.SWITCH_SKIP


@WINDOWS_ONLY
def test_launches_from_several_threads_go_to_teracopy_one_at_a_time(tmp_path):
    """Field mode launches lanes off one card at the same moment. TeraCopy's
    single instance loses all but one of several stubs handed over at once
    (found live 2026-11-09), so a launch holds the next one back until its
    job's history database has appeared."""
    import threading as _t
    import time as _time
    hist = tmp_path / "History"
    hist.mkdir()
    exe = tmp_path / "TeraCopy.exe"
    exe.write_bytes(b"")
    active = []
    overlaps = []
    counter = iter(range(100))
    src = tmp_path / "card" / "A.MP4"

    def spawn(command):
        active.append(command)
        if len(active) > 1:
            overlaps.append(list(active))
        _time.sleep(0.05)                       # the stub hands over...
        target = [p for p in command.split('"') if p.strip() and not p.strip().startswith("/")][-1]
        make_db(hist / f"job-{next(counter)}.db", [{"source": str(src), "size": 1}],   # ...and TeraCopy registers it
                [{"mode": COPY, "target": target}])
        _time.sleep(0.05)
        active.remove(command)

        class P:
            pid = 1
        return P()

    t = TeraCopy(str(exe), history_dir=str(hist), options_ini=str(tmp_path / "x.ini"),
                 list_dir=str(tmp_path / "lists"), spawn=spawn)
    src.parent.mkdir()
    src.write_bytes(b"x")
    out = []
    threads = [_t.Thread(target=lambda d=d: out.append(t.launch([str(src)], str(tmp_path / d), tag="CLIP")))
               for d in ("a", "b", "c")]
    for th in threads:
        th.start()
    for th in threads:
        th.join()
    assert overlaps == []
    assert len({o["list_file"] for o in out}) == 3          # three lists, none replaced another
    assert len(list(hist.glob("*.db"))) == 3


# ------------------------------------------------- a launch counts only when ITS job registered
def _launcher(tmp_path, spawn, history=None, **kw):
    exe = tmp_path / "TeraCopy.exe"
    exe.write_bytes(b"")
    hist_dir = history if history is not None else tmp_path / "History"
    if history is None:
        hist_dir.mkdir(exist_ok=True)
    clock = Clock()
    logs: list[str] = []
    t = TeraCopy(str(exe), history_dir=str(hist_dir), options_ini=str(tmp_path / "x.ini"),
                 list_dir=str(tmp_path / "lists"), spawn=spawn, now=clock.now, sleep=clock.sleep,
                 log_fn=lambda m, level="info": logs.append(str(m)), **kw)
    return t, logs, Path(hist_dir)


class _P:
    pid = 5


@pytest.fixture(autouse=True)
def _fresh_launch_state():
    tc_mod._CLAIMED.clear()
    tc_mod._BROKEN_AT = None
    yield
    tc_mod._CLAIMED.clear()
    tc_mod._BROKEN_AT = None


def test_an_empty_database_is_not_a_registered_job_and_the_job_is_launched_again(tmp_path):
    spawns = []
    holder = {}

    def spawn(cmd):
        spawns.append(cmd)
        hist_dir = holder["hist"]
        if len(spawns) == 1:                                  # TeraCopy woke, made a database, lost the job
            make_db(hist_dir / "a.db", [], [])
        else:
            make_db(hist_dir / "b.db", [{"source": "H:\a.MP4", "size": 1}], [{"mode": COPY, "target": str(tmp_path / "d")}])
        return _P()

    t, logs, h = _launcher(tmp_path, spawn)
    holder["hist"] = h
    res = t.launch(["H:\a.MP4"], str(tmp_path / "d"), tag="x")
    assert len(spawns) == 2 and "a.db" in res["known"]        # the empty one is excluded from the wait
    assert any("launching it again" in m for m in logs)


def test_another_lanes_late_database_is_not_this_jobs(tmp_path):
    spawns = []
    holder = {}

    def spawn(cmd):
        spawns.append(cmd)
        # the only database that ever shows belongs to a job into ANOTHER destination
        if len(spawns) == 1:
            make_db(holder["hist"] / "other.db", [{"source": "H:\a.MP4", "size": 1}],
                    [{"mode": COPY, "target": str(tmp_path / "elsewhere")}])
        return _P()

    t, logs, h = _launcher(tmp_path, spawn)
    holder["hist"] = h
    t.launch(["H:\a.MP4"], str(tmp_path / "d"), tag="x")
    assert len(spawns) == tc_mod.LAUNCH_TRIES                  # never registered: launched again, then given up
    assert tc_mod._BROKEN_AT is not None


def test_a_cold_teracopy_has_no_history_folder_and_the_launch_waits_for_it(tmp_path):
    hist_dir = tmp_path / "ColdHistory"                        # does not exist yet
    spawns = []
    t, logs, _ = _launcher(tmp_path, lambda cmd: (spawns.append(cmd), _P())[1], history=hist_dir)
    polls = {"n": 0}
    real_sleep = t._sleep

    def sleep(step):
        polls["n"] += 1
        if polls["n"] == 8:                                    # TeraCopy finishes starting: folder, then job
            hist_dir.mkdir()
            make_db(hist_dir / "j.db", [{"source": "H:\a.MP4", "size": 1}], [{"mode": COPY, "target": str(tmp_path / "d")}])
        real_sleep(step)

    t._sleep = sleep
    t.launch(["H:\a.MP4"], str(tmp_path / "d"), tag="x")
    assert len(spawns) == 1 and polls["n"] >= 8                # waited for the cold start, did not skip or re-launch


def test_a_broken_teracopy_does_not_hold_every_later_launch_for_the_full_wait(tmp_path):
    t, logs, _ = _launcher(tmp_path, lambda cmd: _P())
    waits = []
    real = t._await_registration

    def spy(*a, **k):
        waits.append(k.get("seconds"))
        return real(*a, **k)

    t._await_registration = spy
    t.launch(["H:\a.MP4"], str(tmp_path / "d1"), tag="x")
    first = waits[0]
    waits.clear()
    t.launch(["H:\b.MP4"], str(tmp_path / "d2"), tag="x")
    assert first == tc_mod.REGISTER_SECONDS and waits[0] == tc_mod.REGISTER_AGAIN_SECONDS


def test_a_cancel_is_heard_while_a_launch_waits_for_registration(tmp_path):
    spawns = []
    t, logs, _ = _launcher(tmp_path, lambda cmd: (spawns.append(cmd), _P())[1])
    res = t.launch(["H:\a.MP4"], str(tmp_path / "d"), tag="x", should_stop=lambda: "cancelled")
    assert res["stopped"] is True and len(spawns) == 1
