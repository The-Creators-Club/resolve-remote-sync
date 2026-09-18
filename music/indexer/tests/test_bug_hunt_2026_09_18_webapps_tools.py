"""The 2026-09-18 hunt, the music indexer's half (webapps-tools, CR-286).

music-4: `make_proxies --dry-run` died on the files the real run survives, and
counted the ones it cannot decode as BUILT. No ffprobe or ffmpeg is run here -
both are the module's own seam and are substituted.
"""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from music_index import proxies                         # noqa: E402


def test_a_probe_that_times_out_is_an_unreadable_file_not_a_traceback(
        monkeypatch, tmp_path):
    def boom(*a, **k):
        raise subprocess.TimeoutExpired(cmd="ffprobe", timeout=120)

    monkeypatch.setattr(proxies.subprocess, "run", boom)
    assert proxies._ffprobe(tmp_path / "truncated.aac") == {}


def test_a_missing_ffprobe_binary_is_the_same_answer(monkeypatch, tmp_path):
    def boom(*a, **k):
        raise FileNotFoundError(2, "no such file", "ffprobe")

    monkeypatch.setattr(proxies.subprocess, "run", boom)
    assert proxies._ffprobe(tmp_path / "x.mp3") == {}


def test_the_full_decode_second_opinion_is_guarded_too(monkeypatch, tmp_path):
    def boom(*a, **k):
        raise subprocess.TimeoutExpired(cmd="ffmpeg", timeout=900)

    monkeypatch.setattr(proxies.subprocess, "run", boom)
    assert proxies.decoded_duration(tmp_path / "x.aac") == 0.0


def test_the_dry_run_parks_an_undecodable_file_as_the_run_does():
    """`is_pointless({})` is False, so a file with no audio stream was counted
    BUILT with duration 0 while the real run raises "no decodable audio
    stream" and counts it FAILED: an estimate that promises proxies that
    cannot be made. Pinned on the BRANCH's own source, because calling it
    needs a database, a config and argv, and a test that re-implements the
    loop would pass on a tree where the loop does not.
    """
    src = (Path(__file__).resolve().parents[1] / "make_proxies.py").read_text(
        encoding="utf-8")
    body = src[src.index("info = proxies.source_info(src)"):]
    body = body[:body.index("if proxies.is_pointless")]
    assert "if not info:" in body
    assert "proxies.FAILED" in body
