"""Regression tests for the 2026-09-24 fix wave, comp-media group.

One group per finding, named after what the defect DID. Each of these fails on
HEAD (63d4290) and passes with the fix; the ledger entry
`docs/bug-hunt-2026-09-24/ledger/comp-media.md` says how that was checked.
(bug-comp-ytdl-1's tests live in test_ytdl_executor.py, beside the fixtures
they need.)

Nothing here spawns a real process: every spawn seam is replaced by a
recorder, and the "managed ffmpeg" is an empty file in tmp_path.
"""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path

import pytest

from ccsync_companion import (broll_ingest, broll_ingest_media, ffmpeg_tools,
                              jobs_media, proxy_gen, sidecar_tools)

sys.path.insert(0, str(Path(__file__).resolve().parent))

from test_broll_ingest import FakeQueue, FakeServer, make_ingestor  # noqa: E402


# ---------------------------------------------------------------------------
# bug-comp-media-1 - the bare "ffmpeg" at argv[0] on a sidecar-only machine
# ---------------------------------------------------------------------------

@pytest.fixture
def sidecar_only(tmp_path, monkeypatch):
    """A machine with no ffmpeg on PATH whose only copy is the managed one
    sidecar_tools installed (CR-53): the normal vendor-build laptop."""
    tools = tmp_path / "tools"
    tools.mkdir()
    for stem in ("ffmpeg", "ffprobe"):
        (tools / f"{stem}.exe").write_text("managed")
    monkeypatch.setattr(ffmpeg_tools.shutil, "which", lambda *_a, **_k: None)
    monkeypatch.setattr(sidecar_tools, "managed_path",
                        lambda tool="ffmpeg": tools / f"{tool}.exe")
    ffmpeg_tools.reset_ffmpeg_available_cache()
    ffmpeg_tools.reset_encoder_cache()
    yield str(tools / "ffmpeg.exe")
    ffmpeg_tools.reset_ffmpeg_available_cache()
    ffmpeg_tools.reset_encoder_cache()


class _Recorder:
    """Stands in for subprocess.Popen / subprocess.run: records argv, then
    behaves like a process that ran and exited 0."""

    def __init__(self):
        self.argvs: list = []

    def __call__(self, argv, *args, **kwargs):
        self.argvs.append(list(argv))
        return subprocess.CompletedProcess(argv, 0, "", "")


def _capability_binary(monkeypatch) -> str:
    """What ffmpeg_available (the probe capabilities.py reports from) says
    this machine will run."""
    monkeypatch.setattr(ffmpeg_tools.subprocess, "run", _Recorder())
    ok, resolved = ffmpeg_tools.ffmpeg_available("ffmpeg", use_cache=False)
    assert ok, resolved
    return resolved


def test_a_media_job_spawns_the_ffmpeg_the_capability_report_advertised(
        sidecar_only, monkeypatch):
    """proxy-480p / audio-extract / peaks: the machine reported ffmpeg true
    from the managed fallback, claimed, and Popen'd the bare name -> WinError
    2, retryable, a cooldown, and the job toured the fleet."""
    advertised = _capability_binary(monkeypatch)
    popen = _Recorder()
    monkeypatch.setattr(jobs_media.subprocess, "Popen", popen)

    jobs_media._popen(jobs_media.peaks_cmd("ffmpeg", "in.mov"))
    jobs_media._popen(jobs_media.audio_copy_cmd("ffmpeg", "in.mov", "out.m4a"))

    assert advertised == sidecar_only
    assert [argv[0] for argv in popen.argvs] == [sidecar_only, sidecar_only]


def test_the_proxy_generator_spawns_the_managed_ffmpeg(sidecar_only, monkeypatch):
    """proxy_gen's gate read RUNNING off the same fallback, then every clip's
    encode and verify failed to start and three attempts capped each clip."""
    popen = _Recorder()
    monkeypatch.setattr(proxy_gen.subprocess, "Popen", popen)
    if sys.platform != "win32":
        monkeypatch.setattr(proxy_gen.os, "setpriority", lambda *a: None,
                            raising=False)

    proxy_gen._default_popen(ffmpeg_tools.verify_decodes_cmd("ffmpeg", "p.mov"))

    assert popen.argvs[0][0] == sidecar_only
    # the argv builders themselves are untouched (the indexer parity tests
    # pin them flag for flag); resolution is the spawn's job
    assert ffmpeg_tools.verify_decodes_cmd("ffmpeg", "p.mov")[0] == "ffmpeg"


def test_broll_ingest_spawns_the_managed_ffmpeg(sidecar_only, monkeypatch):
    """The out-of-territory note on broll_ingest.py:750, confirmed: its
    proxies, sprites and posters went through the same unresolved argv."""
    run = _Recorder()
    monkeypatch.setattr(broll_ingest_media.subprocess, "run", run)

    code, _err = broll_ingest_media.run_ffmpeg(
        broll_ingest_media.poster_cmd("ffmpeg", "in.mov", "p.jpg", 10.0))

    assert code == 0
    assert run.argvs[0][0] == sidecar_only


def test_nvenc_is_detected_through_the_managed_ffmpeg(sidecar_only, monkeypatch):
    """detect_encoders ran the bare name too, so a managed-only machine with a
    GPU reported nvenc false to the scheduler for ever."""
    run = _Recorder()
    monkeypatch.setattr(ffmpeg_tools.subprocess, "run", run)

    ffmpeg_tools.detect_encoders("ffmpeg")

    assert run.argvs[0][0] == sidecar_only


def test_an_explicit_path_that_is_missing_is_not_swapped_for_another_binary(
        sidecar_only, tmp_path):
    """spawn_argv resolves; it never substitutes. An explicit ffmpeg_path that
    does not exist stays what it was, so the spawn fails with the real error
    (the _managed_binary rule)."""
    missing = str(tmp_path / "nope" / "ffmpeg.exe")
    assert ffmpeg_tools.spawn_argv([missing, "-version"])[0] == missing


# ---------------------------------------------------------------------------
# bug-comp-broll-1 - two clips with the same name in one batch
# ---------------------------------------------------------------------------

CLIP_DIR = "PRIVATE/M4ROOT/CLIP"


@pytest.fixture(autouse=True)
def _plenty_of_disk(monkeypatch):
    from ccsync_companion import broll_server
    monkeypatch.setattr(broll_server, "_free_bytes_at", lambda _d: 10 ** 12)


def _two_cards(ingestor):
    """Card A's C0001.MP4, then card B's, dropped into one batch."""
    status, body = ingestor.prepare({"items": [
        {"local_id": "cardA", "name": "C0001.MP4", "size": 4, "source": "upload",
         "rel_dir": CLIP_DIR},
        {"local_id": "cardB", "name": "C0001.MP4", "size": 6, "source": "upload",
         "rel_dir": CLIP_DIR},
    ]})
    assert status == 202, body
    staging_id = body["staging_id"]
    directory = Path(ingestor.staging_dir(staging_id))
    (directory / "cardA.mp4").write_bytes(b"AAAA")
    (directory / "cardB.mp4").write_bytes(b"BBBBBB")
    ingestor.note_upload(staging_id, "cardA", 4)
    ingestor.note_upload(staging_id, "cardB", 6)
    return staging_id, directory


def _row(ord_, size, hash_, stem):
    return {"uid": f"{ord_}" * 32, "ord": ord_, "orig_name": "C0001.MP4",
            "rel_dir": CLIP_DIR, "size_bytes": size, "hash": hash_,
            "video_id": 100 + ord_, "share": "creators",
            "rel_path": f"shoot/{CLIP_DIR}/{stem}.MP4",
            "archive_dir": f"creators/shoot/{CLIP_DIR}", "archive_stem": stem,
            "state": "pending", "duplicate_of": None, "source": "upload",
            "attempts": 0}


@pytest.mark.parametrize("hashes", [(None, None), ("hashA", "hashB")],
                         ids=["no-hashes-yet", "page-relayed-hashes"])
def test_two_same_named_clips_are_each_indexed_from_their_own_file(tmp_path, hashes):
    """bug-comp-broll-1: both manifest rows were paired with card A's staged
    file (first match on name + rel_dir), so card A was indexed twice, once
    under card B's hash, and card B never."""
    server = FakeServer(items=[_row(0, 4, hashes[0], "C0001"),
                               _row(1, 6, hashes[1], "C0001_2")])
    ing = make_ingestor(tmp_path, server=server, queue=FakeQueue())
    staging_id, directory = _two_cards(ing)
    if hashes[0]:
        # what prepare's worker would have computed and the page relayed
        items = ing._staging[staging_id]["items"]
        items["cardA"]["hash"], items["cardB"]["hash"] = hashes

    status, body = ing.run("b" * 32, staging_id)

    assert status == 202, body
    paths = [Path(i["local_path"]).name for i in ing._batch["items"]]
    assert paths == ["cardA.mp4", "cardB.mp4"]


def test_the_row_order_is_reversed_and_the_bytes_still_decide(tmp_path):
    """Pairing is by evidence, not position: rows arriving in the other order
    still get their own files."""
    server = FakeServer(items=[_row(0, 6, None, "C0001"), _row(1, 4, None, "C0001_2")])
    ing = make_ingestor(tmp_path, server=server, queue=FakeQueue())
    staging_id, _directory = _two_cards(ing)

    ing.run("b" * 32, staging_id)

    assert [Path(i["local_path"]).name for i in ing._batch["items"]] == [
        "cardB.mp4", "cardA.mp4"]


def test_indistinguishable_rows_still_never_share_one_file():
    """No hash, no size: the old key, but consuming. Two rows can never both
    be handed one staged file."""
    staged = {
        "a": {"local_id": "a", "ord": 0, "name": "C0001.MP4", "rel_dir": "", "path": "A"},
        "b": {"local_id": "b", "ord": 1, "name": "C0001.MP4", "rel_dir": "", "path": "B"},
    }
    rows = [{"ord": 0, "orig_name": "C0001.MP4", "rel_dir": ""},
            {"ord": 1, "orig_name": "C0001.MP4", "rel_dir": ""},
            {"ord": 2, "orig_name": "C0001.MP4", "rel_dir": ""}]

    matched = broll_ingest.match_manifest_rows(rows, staged)

    assert [m and m["path"] for m in matched] == ["A", "B", None]


def test_a_file_with_a_different_known_hash_is_never_paired():
    """A staged file whose hash is known and differs from the row's is
    provably another clip: better no local file (the item fails, visibly)
    than the wrong footage indexed silently."""
    staged = {"a": {"ord": 0, "name": "C0001.MP4", "rel_dir": "", "path": "A",
                    "hash": "aaaa", "size": 4}}
    rows = [{"ord": 0, "orig_name": "C0001.MP4", "rel_dir": "", "hash": "bbbb",
             "size_bytes": 4}]

    assert broll_ingest.match_manifest_rows(rows, staged) == [None]
