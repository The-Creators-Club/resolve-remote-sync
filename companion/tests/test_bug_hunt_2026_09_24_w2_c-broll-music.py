"""Bug hunt 2026-09-24, fix wave 2 (mediums and lows), group c-broll-music.

One section per finding, each test failing on 4462a2a's code. The ingest
doubles come from the ingest suites rather than being re-invented, so the
regression tests run the REAL orchestrator against the queue model the rest of
the suite uses.
"""

from __future__ import annotations

import sys
from pathlib import Path

import numpy as np
import pytest

from ccsync_companion import (broll_fetch, broll_ingest, broll_server,
                              broll_standins, music_clap_sidecar, music_server,
                              music_worker)

sys.path.insert(0, str(Path(__file__).resolve().parent))

from test_broll_ingest import (FakeQueue, FakeServer,  # noqa: E402
                               OriginalUploadDies, make_ingestor,
                               stage_one_clip)
from test_music_worker import _occupy, stack  # noqa: E402,F401  (fixture)


# ---------------------------------------------------------------------------
# bug-comp-broll-2 - the server's rel_dir is not this machine's
# ---------------------------------------------------------------------------

def _staged(name, rel_dir, path, ord_, size=None, hash_=None):
    return {"name": name, "rel_dir": rel_dir, "path": path, "ord": ord_,
            "size": size, "hash": hash_}


def _row(name, rel_dir, ord_, size=None, hash_=None):
    return {"orig_name": name, "rel_dir": rel_dir, "ord": ord_,
            "size_bytes": size, "hash": hash_}


def test_keep_subfolders_unticked_still_finds_the_staged_file():
    """`create_batch` blanks rel_dir when "keep sub-folders" is off, and the
    staged entry keeps `Day1`: on HEAD no tier matched, `local_path` was ""
    and every clip failed "not on this computer any more"."""
    staged = {"c1": _staged("C0001.MP4", "Shoot/Day1", "S/c1.mp4", 0)}
    got = broll_ingest.match_manifest_rows([_row("C0001.MP4", "", 0)], staged)
    assert got[0] is not None and got[0]["path"] == "S/c1.mp4"


def test_a_folder_name_safe_name_rewrote_still_finds_the_staged_file():
    """`_clean_rel_dir` on the server runs safe_name per component: a
    trailing dot goes, a colon is replaced."""
    staged = {"c1": _staged("A.MP4", "Shoot A.", "S/c1.mp4", 0),
              "c2": _staged("B.MP4", "A:B", "S/c2.mp4", 1)}
    rows = [_row("A.MP4", "Shoot A", 0), _row("B.MP4", "A_B", 1)]
    got = broll_ingest.match_manifest_rows(rows, staged)
    assert [g["path"] for g in got] == ["S/c1.mp4", "S/c2.mp4"]


def test_the_folder_blind_tiers_pair_in_order_and_by_size_first():
    """Two cards' `C0001.MP4` from two folders, flattened: size tells them
    apart when it can, the page's order does when it cannot, and each staged
    file is used once."""
    staged = {"a": _staged("C0001.MP4", "CardA", "S/a.mp4", 0, size=10),
              "b": _staged("C0001.MP4", "CardB", "S/b.mp4", 1, size=20)}
    rows = [_row("C0001.MP4", "", 0, size=20), _row("C0001.MP4", "", 1, size=10)]
    got = broll_ingest.match_manifest_rows(rows, staged)
    assert [g["path"] for g in got] == ["S/b.mp4", "S/a.mp4"]

    rows = [_row("C0001.MP4", "", 0), _row("C0001.MP4", "", 1)]
    got = broll_ingest.match_manifest_rows(rows, staged)
    assert [g["path"] for g in got] == ["S/a.mp4", "S/b.mp4"]


def test_the_folder_blind_tiers_never_take_a_provably_different_file():
    staged = {"a": _staged("C0001.MP4", "Day1", "S/a.mp4", 0, hash_="aaa")}
    got = broll_ingest.match_manifest_rows(
        [_row("C0001.MP4", "", 0, hash_="bbb")], staged)
    assert got == [None]


def test_an_exact_folder_match_is_not_stolen_by_a_folder_blind_one():
    """Row 0 has no exact-folder file, row 1 does: the weak tier runs only
    after every exact one has consumed its file."""
    staged = {"x": _staged("C.MP4", "Day2", "S/x.mp4", 0),
              "y": _staged("C.MP4", "Day1", "S/y.mp4", 1)}
    rows = [_row("C.MP4", "Other", 0), _row("C.MP4", "Day2", 1)]
    got = broll_ingest.match_manifest_rows(rows, staged)
    assert got[1]["path"] == "S/x.mp4"
    assert got[0]["path"] == "S/y.mp4"


# ---------------------------------------------------------------------------
# bug-comp-broll-4 - a held drop is released when the original lands
# ---------------------------------------------------------------------------

def _run_to_release(ing, server, rounds=12):
    before = len(server.released())
    for _ in range(rounds):
        ing.tick()
        if len(server.released()) > before:
            return
    raise AssertionError("the batch never finished")


def test_an_original_retried_to_the_archive_releases_the_hold(tmp_path):
    server = FakeServer()
    server.status_codes = {broll_ingest.ITEM_FAILED: 400}
    ing = make_ingestor(tmp_path, server=server, queue=OriginalUploadDies())
    staging = stage_one_clip(ing, tmp_path)
    ing.run("b" * 32, staging, "foreground")
    _run_to_release(ing, server, broll_ingest.MAX_UPLOAD_ATTEMPTS + 4)
    assert ing._staging[staging]["held_for_base_rig"] == ["A001.MP4"]

    # RETRY FAILED: the same batch and drop, and this time the link holds.
    ing._new_queue = lambda: FakeQueue()
    ing.run("b" * 32, staging, "foreground")
    _run_to_release(ing, server)

    uploaded = [c["body"] for c in server.calls if c["url"].endswith("/uploaded")]
    assert uploaded[-1]["original_uploaded"] is True
    assert not ing._staging[staging].get("held_for_base_rig")
    # ...so the button the disk-full message names can free it now.
    result = ing.prune_staging(max_age_days=0)
    assert result["removed"] == 1 and result["held"] == 0


def test_a_hold_stays_while_a_same_named_clip_still_owes_its_original(tmp_path):
    ing = make_ingestor(tmp_path)
    ing._staging["s1"] = {"dir": str(tmp_path), "held_for_base_rig": ["C0001.MP4"]}
    landed = {"name": "C0001.MP4", "original_failed": "x"}
    still_owed = {"name": "C0001.MP4", "original_failed": "rclone exited"}
    batch = {"staging_id": "s1", "items": [landed, still_owed]}

    ing._original_landed(batch, landed)

    assert ing._staging["s1"]["held_for_base_rig"] == ["C0001.MP4"]
    assert "original_failed" not in landed


def test_held_staging_is_not_blamed_on_clear_finished_staging(tmp_path, monkeypatch):
    ing = make_ingestor(tmp_path)
    held_dir = tmp_path / "held"
    held_dir.mkdir()
    (held_dir / "A001.MP4").write_bytes(b"x" * 2048)
    ing._staging["s1"] = {"dir": str(held_dir), "ended_at": "2026-09-01T00:00:00Z",
                          "held_for_base_rig": ["A001.MP4"]}
    monkeypatch.setattr(broll_server, "_free_bytes_at", lambda d: 0)

    report = ing.staging_report()
    assert report["finished_bytes"] == 0
    assert report["held_bytes"] == 2048
    message = ing._space_refusal(tmp_path)
    assert "CLEAR FINISHED STAGING" not in message
    assert "does not have those files yet" in message
    assert "\u2014" not in message


# ---------------------------------------------------------------------------
# bug-comp-broll-6 - the upload queue does not outlive its batch
# ---------------------------------------------------------------------------

def test_a_finished_batch_puts_its_upload_queue_down(tmp_path):
    server = FakeServer()
    queue = FakeQueue()
    ing = make_ingestor(tmp_path, server=server, queue=queue)
    staging = stage_one_clip(ing, tmp_path)
    ing.run("b" * 32, staging, "foreground")
    _run_to_release(ing, server)

    assert ing._uploader is None
    assert queue.stopped is True


def test_a_claim_applies_its_pause_flag_to_a_queue_that_is_still_up(tmp_path):
    """A queue left paused (the constructor's here) was never resumed: the
    heartbeat acts only on a CHANGE from `_upload_paused`, which run() had
    just set to the server's value."""
    queue = FakeQueue()
    queue.pause()
    ing = make_ingestor(tmp_path, queue=queue)
    staging = stage_one_clip(ing, tmp_path)
    ing.run("b" * 32, staging, "foreground")
    assert queue._paused is False


# ---------------------------------------------------------------------------
# bug-comp-broll-5 - an encode's ceiling scales with the clip
# ---------------------------------------------------------------------------

def test_the_encode_ceiling_is_proxy_gens_rule():
    assert broll_ingest.encode_timeout_seconds(25 * 60) == 25 * 60 * 60
    assert broll_ingest.encode_timeout_seconds(10) == 1800
    assert broll_ingest.encode_timeout_seconds(None) == 1800


def test_the_proxy_encodes_run_under_the_duration_scaled_ceiling(tmp_path):
    seen = []

    def runner(cmd, timeout=900, child_sink=None):
        seen.append((cmd[0], timeout))
        Path(cmd[1]).write_bytes(b"encoded")
        return 0, ""

    ing = make_ingestor(tmp_path, run_media_fn=runner)
    item = {"name": "long.MP4", "uid": "u1", "video_id": 7}
    probe = {"duration_s": 1500.0}
    ing._verify_proxy = lambda path, probe: True
    ing._frames_missing = lambda *a, **k: None

    got = ing._encode_verified(
        item, str(tmp_path / "src.MP4"), tmp_path / "out.mp4",
        lambda partial, nvenc: ["proxy", str(partial)], probe, "preview")

    assert got == str(tmp_path / "out.mp4")
    assert seen and seen[0][1] == 1500 * 60


def test_a_runner_without_a_timeout_keyword_still_runs(tmp_path):
    calls = []
    ing = make_ingestor(tmp_path, run_media_fn=lambda cmd: calls.append(cmd) or (0, ""))
    assert ing._run_media(["x"], timeout=5000) == (0, "")
    assert calls == [["x"]]


# ---------------------------------------------------------------------------
# bug-wire-7 - a hostname that is not Latin-1
# ---------------------------------------------------------------------------

def test_a_cjk_hostname_never_reaches_http_client_as_a_header(tmp_path):
    server = FakeServer()
    ing = make_ingestor(tmp_path, server=server)
    ing.deps._machine_name = "\u526a\u8f2f-PC"
    headers = ing._client()._headers()

    for value in headers.values():
        value.encode("latin-1")  # what http.client does; HEAD raised here
    assert "X-CCSync-Machine" not in headers
    assert headers["X-CCSync-Machine-Pct"] == "%E5%89%AA%E8%BC%AF-PC"


def test_a_latin1_hostname_keeps_the_header_the_server_checks(tmp_path):
    ing = make_ingestor(tmp_path)
    ing.deps._machine_name = "EDIT-1"
    headers = ing._client()._headers()
    assert headers["X-CCSync-Machine"] == "EDIT-1"
    assert "X-CCSync-Machine-Pct" not in headers


# ---------------------------------------------------------------------------
# bug-comp-broll-3 - a finished fetch is reaped and its intent row settled
# ---------------------------------------------------------------------------

@pytest.fixture
def ledger(tmp_path):
    led = broll_standins.configure(tmp_path / "state" / "broll_standins.json")
    yield led
    broll_standins.configure(broll_standins.default_state_path())


def _editor_cfg(tmp_path):
    return {"local_root": str(tmp_path), "mode": "editor",
            "canonical_prefix": "P:\\", "remote": "creators_club_sftp",
            "remote_root": "/mnt/tank/creators_club", "rclone_path": "rclone"}


def _done_job(dest):
    job = broll_fetch.FetchJob(str(dest), "cc/ff5/Proxy/clip.mp4")
    job.state = broll_fetch.STATE_DONE
    with broll_fetch._JOBS_LOCK:
        broll_fetch._JOBS[broll_fetch._job_key(str(dest))] = job
    return job


def test_the_poll_that_finds_the_file_settles_the_intent_and_pops_the_job(
        tmp_path, ledger, monkeypatch):
    monkeypatch.setattr(broll_server, "start_proxy_upgrade", lambda *a, **k: True)
    cfg = _editor_cfg(tmp_path)
    mounts = broll_server.resolve_mounts({}, cfg)
    dest = tmp_path / "Assets" / "B-roll Archive" / "cc" / "ff5" / "clip.mov"
    dest.parent.mkdir(parents=True)
    broll_standins.record(dest, share="broll", rel_path="cc/ff5/clip.mov",
                          pending_fetch=True, size=None)
    dest.write_bytes(b"the preview's bytes")     # rclone renamed it into place
    _done_job(dest)
    seen = {}

    def caller(action, **kwargs):
        seen["row"] = dict(broll_standins.get(dest))
        return {"ok": True, "message": "inserted"}

    try:
        status, body = broll_server.build_insert_response(
            {"share": "broll", "rel_path": "cc/ff5/clip.mov", "in_frame": 0,
             "out_frame": 10, "mode": "append",
             "insert": {"original_rel": "cc/ff5/clip.mov",
                        "preview_rel": "cc/ff5/Proxy/clip.mp4",
                        "edit_proxy_rel": "cc/ff5/Proxy/clip.mov",
                        "original_is_edit_weight": False}},
            mounts, ccsync_cfg=cfg,
            fetcher=lambda *a, **k: pytest.fail("nothing to fetch"),
            caller=caller)
        assert status == 200 and body["ok"] is True
        # Settled BEFORE the import, with the real size.
        assert seen["row"]["pending_fetch"] is False
        assert seen["row"]["size"] == len(b"the preview's bytes")
        assert broll_standins.is_standin(dest) is True
        assert broll_fetch.job_state(str(dest)) is None
    finally:
        with broll_fetch._JOBS_LOCK:
            broll_fetch._JOBS.pop(broll_fetch._job_key(str(dest)), None)


def test_a_deleted_fetched_track_is_fetched_again_not_share_mounted(tmp_path):
    """The music twin: the stale DONE left by the poll that found the file
    answered the next send of that (deleted) track with "is the share
    mounted?"."""
    local = tmp_path / "Assets" / "Music" / "a.mp3"
    local.parent.mkdir(parents=True)
    local.write_bytes(b"mp3")
    _done_job(local)
    try:
        broll_fetch_state = broll_fetch.reap_finished(str(local))
        assert broll_fetch_state == broll_fetch.STATE_DONE
        assert broll_fetch.job_state(str(local)) is None
        # A running job is never reaped.
        job = _done_job(local)
        job.state = broll_fetch.STATE_DOWNLOADING
        assert broll_fetch.reap_finished(str(local)) is None
        assert broll_fetch.job_state(str(local)) == broll_fetch.STATE_DOWNLOADING
    finally:
        with broll_fetch._JOBS_LOCK:
            broll_fetch._JOBS.pop(broll_fetch._job_key(str(local)), None)


def test_the_music_send_reaps_a_finished_job_for_a_track_in_place(tmp_path, monkeypatch):
    root = tmp_path / "tree"
    local = root / "Assets" / "Music" / "a.mp3"
    local.parent.mkdir(parents=True)
    local.write_bytes(b"mp3")
    monkeypatch.setattr(music_server, "local_path_for",
                        lambda share, rel, mounts: str(local))
    _done_job(local)
    try:
        status, _body = music_server.build_send_response(
            {"action": "bin", "share": "music", "rel_path": "a.mp3"}, {},
            caller=lambda action, **kw: {"ok": True, "note": "ok"})
        assert broll_fetch.job_state(str(local)) is None
    finally:
        with broll_fetch._JOBS_LOCK:
            broll_fetch._JOBS.pop(broll_fetch._job_key(str(local)), None)


# ---------------------------------------------------------------------------
# logic-broll-music-2 - equal geometry proves nothing at 1080 lines or fewer
# ---------------------------------------------------------------------------

HD = {"width": 1920, "height": 1080, "fps": 25.0, "frames": 250}


def _hd_intent(tmp_path, name="dnx.mov"):
    media = tmp_path / "Assets" / "B-roll Archive" / "cc" / name
    media.parent.mkdir(parents=True, exist_ok=True)
    broll_standins.record(media, share="broll", rel_path=f"cc/{name}",
                          geometry=dict(HD), pending_fetch=True, size=None)
    media.write_bytes(b"1080p bytes of some kind")
    return media


def test_a_1080p_h264_header_is_not_taken_for_the_original(tmp_path, ledger):
    """The preview of a heavy 1080p original is 1920x1080 H.264 too: equal
    geometry retired the row on HEAD and left the preview unmarked."""
    media = _hd_intent(tmp_path)
    header = {"width": 1920, "height": 1080, "codec": "h264"}

    assert broll_standins.settle_intents(
        probe_fn=lambda p: dict(header), job_state_fn=lambda d: None) == 0
    assert broll_standins.get(media)["pending_fetch"] is True
    assert broll_standins.is_standin(media) is True

    # The job record is what answers it, as for a row with no geometry.
    assert broll_standins.settle_intents(
        probe_fn=lambda p: dict(header),
        job_state_fn=lambda d: broll_fetch.STATE_DONE) == 1
    assert broll_standins.get(media)["pending_fetch"] is False
    assert broll_standins.is_standin(media) is True


def test_a_1080p_header_in_another_codec_is_the_original(tmp_path, ledger):
    media = _hd_intent(tmp_path)
    assert broll_standins.settle_intents(
        probe_fn=lambda p: {"width": 1920, "height": 1080, "codec": "dnxhd"},
        job_state_fn=lambda d: broll_fetch.STATE_DONE) == 1
    assert broll_standins.get(media) is None


def test_a_taller_original_still_settles_by_geometry(tmp_path, ledger):
    media = tmp_path / "Assets" / "B-roll Archive" / "cc" / "big.mov"
    media.parent.mkdir(parents=True, exist_ok=True)
    geometry = {"width": 6064, "height": 3424}
    broll_standins.record(media, share="broll", rel_path="cc/big.mov",
                          geometry=geometry, pending_fetch=True, size=None)
    media.write_bytes(b"6K")
    assert broll_standins.settle_intents(
        probe_fn=lambda p: {"width": 6064, "height": 3424, "codec": "h264"},
        job_state_fn=lambda d: broll_fetch.STATE_DONE) == 1
    assert broll_standins.get(media) is None


# ---------------------------------------------------------------------------
# bug-comp-media-6 - insert with the playhead inside a clip
# ---------------------------------------------------------------------------

def test_insert_refuses_a_clip_that_straddles_the_playhead(stack):
    timeline, pool, _project, cue = stack
    _occupy(timeline, 2, 50, 100)          # 50..150, playhead at 100
    _occupy(timeline, 2, 200, 40)

    out = music_worker.run_request({"action": "insert", "path": cue})

    assert out["ok"] is False
    assert "playhead is inside a clip on A2" in out["error"]
    assert "place underneath" in out["error"]
    assert "\u2014" not in out["error"]
    # Refused BEFORE anything was deleted or placed.
    assert pool.append_calls == []
    assert [i.GetStart() for i in timeline.tracks[2]] == [50, 200]


def test_insert_at_a_cut_still_ripples(stack):
    timeline, _pool, _project, cue = stack
    _occupy(timeline, 2, 0, 100)           # ends exactly at the playhead
    _occupy(timeline, 2, 100, 40)          # starts exactly at it

    out = music_worker.run_request({"action": "insert", "path": cue})

    assert out["ok"] is True
    assert [i.GetStart() for i in timeline.tracks[2]] == [0, 100, 200]


# ---------------------------------------------------------------------------
# bug-comp-media-7 - decode memory and the capped duration
# ---------------------------------------------------------------------------

class _Completed:
    def __init__(self, stdout=b""):
        self.stdout, self.stderr, self.returncode = stdout, b"", 0


def test_decode_makes_one_copy_not_two(monkeypatch, tmp_path):
    raw = np.array([0.25, np.nan, 0.5], dtype=np.float32).tobytes()
    monkeypatch.setattr(music_clap_sidecar, "_run", lambda *a, **k: _Completed(raw))
    calls = {"copy": 0}
    real_copy = np.ndarray.copy

    class Counting(np.ndarray):
        def copy(self, *a, **k):
            calls["copy"] += 1
            return real_copy(self, *a, **k)

    real_nan_to_num = np.nan_to_num
    monkeypatch.setattr(np, "nan_to_num",
                        lambda *a, **k: real_nan_to_num(*a, **k).view(Counting))

    got = music_clap_sidecar.decode("ffmpeg", tmp_path / "a.wav")

    assert calls["copy"] == 0
    assert got.flags.writeable
    assert np.asarray(got).tolist() == [0.25, 0.0, 0.5]


def test_a_decode_cut_at_the_cap_takes_the_longer_probed_duration(monkeypatch):
    monkeypatch.setattr(music_clap_sidecar, "MAX_DECODE_SECONDS", 10)
    monkeypatch.setattr(music_clap_sidecar, "probe",
                        lambda ffmpeg, path: {"duration": 9000.0})
    capped = np.zeros(10 * 100, dtype=np.float32)
    assert music_clap_sidecar._duration_of(capped, 100, "ffmpeg", "x") == 9000.0

    short = np.zeros(4 * 100, dtype=np.float32)
    assert music_clap_sidecar._duration_of(short, 100, "ffmpeg", "x") == 4.0

    # A probe that answers less (or nothing) never shortens the decoded count.
    monkeypatch.setattr(music_clap_sidecar, "probe",
                        lambda ffmpeg, path: {"duration": 0.0})
    assert music_clap_sidecar._duration_of(capped, 100, "ffmpeg", "x") == 10.0


# ---------------------------------------------------------------------------
# Owed round, bug-comp-ui-1 (from c-ui) - a busy picker is named, not "broken"
# ---------------------------------------------------------------------------

def test_a_busy_picker_names_the_open_window_not_a_broken_picker(monkeypatch):
    from ccsync_companion import popup

    def busy(kind, timeout=300, **_kw):
        raise popup.PickerBusy()

    monkeypatch.setattr(popup, "pick_media_sources", busy)
    status, body = broll_server.pick_ingest_sources("folder")
    assert status == 200
    assert body["ok"] is False
    assert body["message"] == popup.PICKER_BUSY_MESSAGE
    assert "could not be opened" not in body["message"]
    assert "—" not in body["message"]


def test_a_picker_that_really_fails_still_says_so(monkeypatch):
    from ccsync_companion import popup

    def broken(kind, timeout=300, **_kw):
        raise RuntimeError("no display")

    monkeypatch.setattr(popup, "pick_media_sources", broken)
    status, body = broll_server.pick_ingest_sources("files")
    assert (status, body["ok"]) == (200, False)
    assert "could not be opened" in body["message"]
