"""BROLL-1 (2026-09-04): publishing broll.db must not delete the fleet's work.

`publish_db.py --which broll --apply` renames the base rig's copy over the live
one. The live one is the ONLY place drag-and-drop ingest exists: the `videos`
rows the dashboard mints at claim time, and the whole of
`ingest_batches`/`ingest_items`. The 10% shrink check cannot see the loss (200
ingested clips against 15,000 is 1.3%), so the swap took them silently.

Two groups:

  1. the drain itself, run END TO END against real databases -- take it, swap
     the file the way the remote script does, merge it back, and assert the
     ingested clips, their segments and embeddings, and every batch row are
     there afterwards. The same test asserts what the bug WAS, in the window
     between the swap and the merge;
  2. the refusal: a drain that could not be taken stops the publish before
     anything on the NAS is renamed.

Offline. Run from GIT BASH (see CLAUDE.md):
    cd E:\\Projects\\resolve-remote-sync\\server
    ../dashboard/.venv/Scripts/python.exe -m pytest tests/test_broll_drain.py -q
"""
import json
import os
import shutil
import sqlite3
import struct
import subprocess
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import broll_drain  # noqa: E402
import common  # noqa: E402
import install_dashboard_app as ida  # noqa: E402
import publish_db  # noqa: E402
from backends.truenas import TrueNASBackend  # noqa: E402

REPO_ROOT = Path(__file__).resolve().parents[2]
SCHEMA = REPO_ROOT / "broll" / "web" / "schema.sql"


# --------------------------------------------------------------------------
# Fixtures: two real b-roll indexes, on the real schema
# --------------------------------------------------------------------------

def make_index(path: Path, videos, ingest=(), schema=None):
    """A broll.db on the shipped schema. `videos` is [(share, rel_path)].

    `schema` overrides it, which is how the "a bundle outlives a migration"
    case is built.
    """
    if path.exists():
        path.unlink()
    conn = sqlite3.connect(str(path))
    conn.executescript(schema or SCHEMA.read_text(encoding="utf-8"))
    for share, rel in videos:
        conn.execute("INSERT INTO videos (share, rel_path, status) "
                     "VALUES (?,?,'indexed')", (share, rel))
    conn.commit()
    for share, rel in ingest:
        add_ingested_clip(conn, share, rel)
    conn.commit()
    conn.close()


def add_ingested_clip(conn, share, rel, batch_uid="batch-1"):
    """What the dashboard's ingest routes write into the LIVE file and nowhere
    else: a videos row minted at claim, its description, its vector, the share
    root, and the batch/item ledger."""
    conn.execute("INSERT OR IGNORE INTO ingest_batches "
                 "(uid, editor, share, settings_json, state, created_at) "
                 "VALUES (?,'alex',?,'{}','running','2026-09-04T10:00:00')",
                 (batch_uid, share))
    conn.execute("INSERT OR IGNORE INTO share_roots (share, root, collection) "
                 "VALUES (?, '/mnt/tank/x', 'owned')", (share,))
    vid = conn.execute("INSERT INTO videos (share, rel_path, status, category) "
                       "VALUES (?,?,'indexed','people')", (share, rel)).lastrowid
    seg = conn.execute(
        "INSERT INTO segments (video_id, t_start, t_end, description) "
        "VALUES (?,0,4,?)", (vid, "a drone shot of " + rel)).lastrowid
    conn.execute("INSERT INTO transcript_segments (video_id, t_start, t_end, text) "
                 "VALUES (?,0,4,'spoken words')", (vid,))
    conn.execute("INSERT INTO themes (video_id, text) VALUES (?, 'coastline')", (vid,))
    conn.execute("INSERT INTO embeddings (source, source_id, video_id, model, dim, vec) "
                 "VALUES ('segment',?,?,'bge-small',4,?)",
                 (seg, vid, struct.pack("<4f", 1.0, 0.0, 0.0, 0.0)))
    conn.execute(
        "INSERT INTO ingest_items (uid, batch_uid, ord, orig_name, source, "
        "video_id, state) VALUES (?,?,1,?,'upload',?,'live')",
        ("item-" + rel, batch_uid, rel, vid))
    return vid


def run_program(program, *args):
    """The programs run as `python3 -c` inside the container; here they run
    under the test interpreter, which is the same contract."""
    proc = subprocess.run([sys.executable, "-c", program, *[str(a) for a in args]],
                          capture_output=True, text=True)
    payload = {}
    lines = [ln for ln in proc.stdout.splitlines() if ln.strip()]
    if lines and lines[-1].lstrip().startswith("{"):
        payload = json.loads(lines[-1])
    return proc.returncode, payload, proc.stdout + proc.stderr


# --------------------------------------------------------------------------
# 1. The drain, end to end
# --------------------------------------------------------------------------

def test_a_publish_keeps_the_clips_and_batches_the_fleet_ingested(tmp_path):
    """The whole of BROLL-1 in one test: the base rig's copy has never seen the
    ingested shoot, and after the swap plus the merge the live index has both
    halves."""
    live = tmp_path / "broll.db"
    make_index(live, [("ff3", "A/001.MP4"), ("ff3", "A/002.MP4")],
               ingest=[("Wedding_2026", "day1/C001.MP4"),
                       ("Wedding_2026", "day1/C002.MP4")])
    # The base rig's copy: the archive as the indexer knows it, plus a clip the
    # last indexer pass added. No ingest tables content at all.
    candidate = tmp_path / "candidate.db"
    make_index(candidate, [("ff3", "A/001.MP4"), ("ff3", "A/002.MP4"),
                           ("ff3", "A/003.MP4")])

    bundle = tmp_path / "broll.db.drain-20260904T120000"
    rc, summary, log = run_program(broll_drain.EXPORT_PROGRAM, live, bundle)
    assert rc == 0, log
    assert summary["videos"] == 2 and summary["ingest_batches"] == 1
    assert summary["ingest_items"] == 2 and summary["open_batches"] == 1

    # The swap, exactly as build_db_swap_script does it: a rename over the live
    # path. THIS is the moment the bug happened.
    shutil.copy2(candidate, live)
    conn = sqlite3.connect(str(live))
    assert conn.execute("SELECT count(*) FROM ingest_batches").fetchone()[0] == 0
    assert conn.execute("SELECT count(*) FROM videos WHERE share='Wedding_2026'"
                        ).fetchone()[0] == 0
    conn.close()

    rc, report, log = run_program(broll_drain.APPLY_PROGRAM, live, bundle)
    assert rc == 0, log
    assert report["videos_inserted"] == 2
    assert report["batches"] == 1 and report["items"] == 2

    conn = sqlite3.connect(str(live))
    rows = conn.execute("SELECT rel_path FROM videos WHERE share='Wedding_2026' "
                        "ORDER BY rel_path").fetchall()
    assert [r[0] for r in rows] == ["day1/C001.MP4", "day1/C002.MP4"]
    # The clip the last indexer pass found is still there: the merge inserts,
    # it never replaces the published index.
    assert conn.execute("SELECT count(*) FROM videos WHERE share='ff3'"
                        ).fetchone()[0] == 3
    # The batch ledger, with its item still pointing at the right clip.
    state, share = conn.execute(
        "SELECT state, share FROM ingest_batches").fetchone()
    assert (state, share) == ("running", "Wedding_2026")
    vid, rel = conn.execute(
        "SELECT i.video_id, v.rel_path FROM ingest_items i JOIN videos v "
        "ON v.id = i.video_id WHERE i.uid='item-day1/C001.MP4'").fetchone()
    assert rel == "day1/C001.MP4"
    # Children came with their clip, and the vector still points at ITS segment.
    seg_id, desc = conn.execute(
        "SELECT id, description FROM segments WHERE video_id=?", (vid,)).fetchone()
    assert desc.endswith("day1/C001.MP4")
    assert conn.execute("SELECT source_id FROM embeddings WHERE video_id=?",
                        (vid,)).fetchone()[0] == seg_id
    assert conn.execute("SELECT count(*) FROM transcript_segments WHERE video_id=?",
                        (vid,)).fetchone()[0] == 1
    assert conn.execute("SELECT root FROM share_roots WHERE share='Wedding_2026'"
                        ).fetchone()[0] == "/mnt/tank/x"
    # The FTS mirrors are content-backed with triggers, so a merged clip is
    # findable rather than merely present.
    hit = conn.execute("SELECT rowid FROM segments_fts WHERE segments_fts "
                       "MATCH 'drone'").fetchall()
    assert seg_id in [r[0] for r in hit]
    conn.close()


def test_the_merge_can_be_run_twice(tmp_path):
    """The bundle is applied AFTER the rename, so a dropped ssh session leaves
    it un-merged; the operator's recovery is to run --apply-drain again. That
    is only safe if every write is keyed."""
    live = tmp_path / "broll.db"
    make_index(live, [("ff3", "A/001.MP4")],
               ingest=[("Wedding_2026", "day1/C001.MP4")])
    bundle = tmp_path / "bundle.db"
    assert run_program(broll_drain.EXPORT_PROGRAM, live, bundle)[0] == 0
    make_index(live, [("ff3", "A/001.MP4")])   # the swap

    first = run_program(broll_drain.APPLY_PROGRAM, live, bundle)
    second = run_program(broll_drain.APPLY_PROGRAM, live, bundle)
    assert first[0] == 0 and second[0] == 0, first[2] + second[2]
    assert second[1]["videos_inserted"] == 0
    assert second[1]["videos_already_there"] == 1

    conn = sqlite3.connect(str(live))
    assert conn.execute("SELECT count(*) FROM videos").fetchone()[0] == 2
    assert conn.execute("SELECT count(*) FROM segments").fetchone()[0] == 1
    assert conn.execute("SELECT count(*) FROM ingest_items").fetchone()[0] == 1
    conn.close()


def test_a_clip_the_new_index_already_has_keeps_the_published_row(tmp_path):
    """A shoot that has since been indexed on the base rig is in BOTH copies.
    The published row wins (that pass is the newer one) and its segments are
    not doubled."""
    live = tmp_path / "broll.db"
    make_index(live, [], ingest=[("Wedding_2026", "day1/C001.MP4")])
    bundle = tmp_path / "bundle.db"
    assert run_program(broll_drain.EXPORT_PROGRAM, live, bundle)[0] == 0

    candidate = tmp_path / "candidate.db"
    make_index(candidate, [("Wedding_2026", "day1/C001.MP4")])
    conn = sqlite3.connect(str(candidate))
    vid = conn.execute("SELECT id FROM videos").fetchone()[0]
    conn.execute("INSERT INTO segments (video_id, t_start, t_end, description) "
                 "VALUES (?,0,4,'the base rig description')", (vid,))
    conn.commit()
    conn.close()
    shutil.copy2(candidate, live)

    rc, report, log = run_program(broll_drain.APPLY_PROGRAM, live, bundle)
    assert rc == 0, log
    assert report["videos_inserted"] == 0 and report["videos_already_there"] == 1
    conn = sqlite3.connect(str(live))
    assert conn.execute("SELECT count(*) FROM segments").fetchone()[0] == 1
    assert conn.execute("SELECT description FROM segments").fetchone()[0] == (
        "the base rig description")
    # The batch ledger still came across, re-pointed at the published clip.
    assert conn.execute("SELECT video_id FROM ingest_items").fetchone()[0] == vid
    conn.close()


def test_no_live_index_yet_is_an_answer_not_a_failure(tmp_path):
    """A first publish onto a NAS with no broll.db has nothing to lose, and
    must not be turned into a refusal."""
    rc, payload, _log = run_program(broll_drain.EXPORT_PROGRAM,
                                    tmp_path / "nothing.db", tmp_path / "b.db")
    assert rc == broll_drain.RC_NO_LIVE
    assert payload == {"live": False}


def test_an_index_older_than_the_ingest_tables_drains_nothing(tmp_path):
    live = tmp_path / "broll.db"
    make_index(live, [("ff3", "A/001.MP4")])
    conn = sqlite3.connect(str(live))
    conn.executescript("DROP TABLE ingest_items; DROP TABLE ingest_batches;")
    conn.close()
    rc, payload, log = run_program(broll_drain.EXPORT_PROGRAM, live,
                                   tmp_path / "b.db")
    assert rc == 0, log
    assert payload["ingest_schema"] is False


def test_a_merge_that_fails_leaves_the_live_index_exactly_as_it_was(tmp_path):
    """One transaction: a bundle the live schema will not accept must roll the
    whole merge back, not leave half a shoot in the index. The case is real -- a
    bundle can outlive a migration, and here the published index no longer
    allows the item state the drained one wrote."""
    live = tmp_path / "broll.db"
    make_index(live, [], ingest=[("Wedding_2026", "day1/C001.MP4"),
                                 ("Wedding_2026", "day1/C002.MP4")])
    bundle = tmp_path / "bundle.db"
    assert run_program(broll_drain.EXPORT_PROGRAM, live, bundle)[0] == 0

    stricter = SCHEMA.read_text(encoding="utf-8").replace("'uploading','live',",
                                                          "'uploading',")
    make_index(live, [("ff3", "A/001.MP4")], schema=stricter)   # the swap
    rc, payload, _log = run_program(broll_drain.APPLY_PROGRAM, live, bundle)
    assert rc == broll_drain.RC_FAILED
    assert "IntegrityError" in payload["error"]
    conn = sqlite3.connect(str(live))
    assert conn.execute("SELECT count(*) FROM videos").fetchone()[0] == 1
    assert conn.execute("SELECT count(*) FROM ingest_items").fetchone()[0] == 0
    assert conn.execute("SELECT count(*) FROM segments").fetchone()[0] == 0
    conn.close()


def test_a_missing_bundle_is_its_own_exit_code(tmp_path):
    live = tmp_path / "broll.db"
    make_index(live, [])
    rc, payload, _log = run_program(broll_drain.APPLY_PROGRAM, live,
                                    tmp_path / "gone.db")
    assert rc == broll_drain.RC_NO_BUNDLE
    assert "no bundle" in payload["error"]


# --------------------------------------------------------------------------
# 2. The refusal
# --------------------------------------------------------------------------

class FakeBackend(TrueNASBackend):
    """A TrueNAS backend whose container_exec answers from a script."""

    def __init__(self, answers):
        module = type(sys)("fake_script")
        module.run_ssh = lambda cmd, dry_run=False, timeout=120: (0, "", "")
        super().__init__(calls=common.ScriptCalls(module))
        self.answers = list(answers)
        self.execs = []

    def container_exec(self, container, argv, dry_run):
        self.execs.append(argv)
        return self.answers.pop(0) if self.answers else (0, "{}", "")


def test_a_drain_that_could_not_be_taken_is_not_a_drain_of_nothing():
    """Three answers, not two -- the middle one is what the refusal keys on."""
    backend = FakeBackend([(1, "", "Error: No such container: dashboard")])
    drain, why = publish_db.take_drain(backend, "c", "/broll-data/broll.db",
                                       "/broll-data/broll.db.drain-x", False)
    assert drain == {}
    assert "No such container" in why

    backend = FakeBackend([(broll_drain.RC_NO_LIVE, '{"live": false}', "")])
    assert publish_db.take_drain(backend, "c", "/p", "/b", False) == ({}, "")

    backend = FakeBackend([(0, '{"live": true, "videos": 3, "ingest_batches": 1}', "")])
    drain, why = publish_db.take_drain(backend, "c", "/p", "/b", False)
    assert why == "" and drain["videos"] == 3


def test_the_drain_carries_its_paths_as_argv_not_as_source():
    """read_live_counts has to REFUSE a path with an apostrophe in it, because
    it interpolates into a python -c. The drain cannot refuse anything: it is
    the step whose absence loses data."""
    backend = FakeBackend([(0, "{}", "")])
    live = "/mnt/o'brien/broll.db"
    publish_db.take_drain(backend, "c", live, "/b", False)
    assert common.shell_quote(live) in backend.execs[0]


def _publish(monkeypatch, tmp_path, backend, extra=()):
    """publish_db.main() for a --which broll publish, with the NAS faked."""
    source = tmp_path / "source.db"
    make_index(source, [("ff3", "A/001.MP4")])
    ran = []

    def guarded(cmd, dry_run=False, timeout=120):
        ran.append(cmd)
        if cmd.startswith("wc -c"):
            return 0, str(os.path.getsize(sent[0])), ""
        return 0, "", ""

    sent = [""]

    class FakeSftp:
        def put(self, local, remote):
            sent[0] = local

        def close(self):
            pass

    class FakeClient:
        def open_sftp(self):
            return FakeSftp()

        def close(self):
            pass

    monkeypatch.setattr(publish_db, "get_backend", lambda args: backend)
    monkeypatch.setattr(ida, "run_ssh_guarded", guarded)
    monkeypatch.setattr(ida, "make_staging_dir",
                        lambda dry_run, name, parent="/tmp": "/tmp/staging-1")
    monkeypatch.setattr(publish_db, "truenas_conn_params",
                        lambda dry_run=False: ("nas", "root", "pw"))
    monkeypatch.setattr(publish_db, "ssh_client",
                        lambda host, user, pw: FakeClient())
    monkeypatch.setattr(sys, "argv", ["publish_db.py", "--which", "broll",
                                      "--source", str(source), "--apply",
                                      *extra])
    return publish_db.main(), ran


def test_a_publish_refuses_when_the_live_index_cannot_be_drained(
        monkeypatch, tmp_path, capsys):
    """The one that matters: a container that will not answer must stop the
    publish BEFORE the rename, not be waved through into a silent deletion."""
    backend = FakeBackend([
        (0, '{"videos": 1, "segments": 0, "embeddings": 0}', ""),   # live counts
        (1, "", "Error response from daemon: container not running"),  # the drain
    ])
    rc, ran = _publish(monkeypatch, tmp_path, backend)
    err = capsys.readouterr().err
    assert rc == 1
    assert "could not drain" in err and "not running" in err
    assert "--allow-loss" in err
    assert not any(".prev-" in cmd for cmd in ran), (
        "nothing may be renamed once the drain has failed")


def test_allow_loss_is_the_operator_saying_it_out_loud(
        monkeypatch, tmp_path, capsys):
    backend = FakeBackend([
        (0, '{"videos": 1, "segments": 0, "embeddings": 0}', ""),
        (1, "", "container not running"),
    ])
    rc, ran = _publish(monkeypatch, tmp_path, backend, extra=["--allow-loss"])
    out = capsys.readouterr()
    assert rc == 0, out.err
    assert "--allow-loss given" in out.err
    assert any(".prev-" in cmd for cmd in ran)


def test_a_publish_drains_and_then_merges_it_back(monkeypatch, tmp_path, capsys):
    backend = FakeBackend([
        (0, '{"videos": 1, "segments": 0, "embeddings": 0}', ""),
        (0, ('{"live": true, "ingest_schema": true, "videos": 12, '
             '"ingest_batches": 2, "ingest_items": 40, "open_batches": 1, '
             '"bundle": "/broll-data/broll.db.drain-x"}'), ""),
        (0, ('{"videos_inserted": 12, "videos_already_there": 0, "children": 30, '
             '"embeddings": 30, "share_roots": 1, "batches": 2, "items": 40}'), ""),
    ])
    rc, ran = _publish(monkeypatch, tmp_path, backend)
    out = capsys.readouterr().out
    assert rc == 0
    assert "drain taken: 12 fleet-ingested clips" in out
    assert "drain applied: 12 clips put back" in out
    # Order is load-bearing: export, then the swap, then the merge.
    swap = [i for i, cmd in enumerate(ran) if ".prev-" in cmd]
    assert swap, ran
    assert len(backend.execs) == 3


def test_a_merge_that_fails_after_the_swap_names_the_bundle_and_the_command(
        monkeypatch, tmp_path, capsys):
    """The new index is live and the rows are not lost -- they are in a file
    that is never deleted, and the operator is handed the command."""
    backend = FakeBackend([
        (0, '{"videos": 1, "segments": 0, "embeddings": 0}', ""),
        (0, ('{"live": true, "ingest_schema": true, "videos": 12, '
             '"ingest_batches": 2, "ingest_items": 40, "open_batches": 1}'), ""),
        (5, '{"error": "OperationalError: database is locked"}', ""),
    ])
    rc, _ran = _publish(monkeypatch, tmp_path, backend)
    err = capsys.readouterr().err
    assert rc == 0
    assert "have NOT been merged" in err and "database is locked" in err
    assert "--apply-drain" in err
