"""Regression tests for the 2026-09-24 hunt's fix pass, wave 2 (mediums and
lows), group c-media: bug-comp-media-3, -4, -5 and -8.

Each fails on HEAD (4462a2a) and passes with the fix; the ledger entry
`docs/bug-hunt-2026-09-24/ledger2/c-media.md` says how that was checked. The
runner tests reuse test_jobs_runner.py's fakes (a dict for a dashboard, a
recipe that records), so nothing here spawns a process except the two tests
that ask a real ffmpeg what it does with a video-only file, and those go
through the suite's ffmpeg gate.
"""

from __future__ import annotations

import os
import shutil
import re
import subprocess
import sys
from pathlib import Path

import pytest

from ccsync_companion import ffmpeg_tools, job_paths, jobs_media, proxy_gen

sys.path.insert(0, str(Path(__file__).resolve().parent))

from test_jobs_runner import (FakeDashboard, FakeRecipe,  # noqa: E402
                              a_media_job, media_runner)
from test_proxy_gen import _make_gen  # noqa: E402

from conftest import require_ffmpeg_or_skip  # noqa: E402

FFMPEG = shutil.which("ffmpeg")
FFPROBE = shutil.which("ffprobe")


def _run(runner, dash):
    runner.note_report_reply({"commands": {"jobs": {"offered": [9]}}})
    runner.tick()
    return dash.results[-1]


# ---------------------------------------------------------------------------
# bug-comp-media-3 - out_stem appended to the output directory unchecked
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("stem", [
    "C:/Windows/Temp/evil",      # replaced out_dir entirely on Windows
    "/etc/evil",                 # the same on a Mac
    "../../../escaped",          # climbed out of it
    "Interview 1/2",             # a folder the recipe never made
    "..",
    "nul\x00byte",
])
def test_an_out_stem_that_is_not_a_plain_name_is_refused_for_the_whole_fleet(
        tmp_path, monkeypatch, stem):
    FakeRecipe.calls = []
    monkeypatch.setattr(jobs_media, "MediaJob", FakeRecipe)
    dash = FakeDashboard(a_media_job("peaks", out_stem=stem))
    posted = _run(media_runner(tmp_path, dash), dash)
    assert posted["ok"] is False
    # NOT retryable: the same name is wrong on every machine, and a tour of
    # the fleet only buys each claimant a cooldown.
    assert posted["retryable"] is False
    assert "plain file name" in posted["error"]
    assert FakeRecipe.calls == [], "the recipe must never see the stem"


def test_an_ordinary_multicam_name_still_names_the_output(tmp_path, monkeypatch):
    FakeRecipe.calls = []
    monkeypatch.setattr(jobs_media, "MediaJob", FakeRecipe)
    dash = FakeDashboard(a_media_job(out_stem="Interview 3 (cam B) - Take.2"))
    posted = _run(media_runner(tmp_path, dash), dash)
    assert posted["ok"] is True
    assert posted["result"]["files"] == [
        "V/Ep/Script Docs/remote_audio/source/Interview 3 (cam B) - Take.2.480p.mp4"]


# Review round (2026-09-25): ':' and a backslash are Windows-only hazards. Refusing
# them fleet-wide made a name a Mac or the dashboard's pinned Linux engine
# can write into a permanent FAILED (db.fail_job: retryable=False -> FAILED,
# never pinned). On Windows they are "not here"; elsewhere they are a name.
WINDOWS_ONLY_STEMS = ["Q&A: Ruskin", "C:x", "back\\slash", "a\\..\\..\\b"]


@pytest.mark.parametrize("stem", WINDOWS_ONLY_STEMS)
def test_a_windows_only_character_is_not_here_on_windows(stem):
    with pytest.raises(job_paths.JobPathError) as caught:
        job_paths.safe_stem(stem, windows=True)
    assert caught.value.retryable is True, (
        "a Mac or the pinned engine can still write this name")


@pytest.mark.parametrize("stem", WINDOWS_ONLY_STEMS)
def test_a_windows_only_character_is_a_plain_name_elsewhere(stem):
    assert job_paths.safe_stem(stem, windows=False) == stem


def test_a_multicam_name_with_a_colon_is_left_for_another_machine(
        tmp_path, monkeypatch):
    # Through the real runner on THIS platform: on Windows the job goes back
    # to the queue (retryable) for a Mac or the pinned engine; on a Mac or
    # Linux the recipe runs with the name exactly as Cards sent it.
    FakeRecipe.calls = []
    monkeypatch.setattr(jobs_media, "MediaJob", FakeRecipe)
    dash = FakeDashboard(a_media_job("peaks", out_stem="Q&A: Ruskin"))
    posted = _run(media_runner(tmp_path, dash), dash)
    if os.name == "nt":
        assert posted["ok"] is False
        assert posted["retryable"] is True
        assert FakeRecipe.calls == []
    else:
        assert posted["ok"] is True


def test_safe_stem_returns_the_name_unchanged():
    # Refused or kept, never rewritten: a sanitised name is a file the page
    # will never look for.
    assert job_paths.safe_stem("Framing Formosa A004") == "Framing Formosa A004"
    with pytest.raises(job_paths.JobPathError) as caught:
        job_paths.safe_stem("   ")
    assert caught.value.retryable is False


# ---------------------------------------------------------------------------
# bug-comp-media-8 - a path Path() rejects escaped the runner with no result
# ---------------------------------------------------------------------------

def test_a_nul_in_a_media_rel_path_posts_a_non_retryable_failure(tmp_path, monkeypatch):
    monkeypatch.setattr(jobs_media, "MediaJob", FakeRecipe)
    dash = FakeDashboard(a_media_job(rel_path="FF5/Inter\x00view.mp4"))
    posted = _run(media_runner(tmp_path, dash), dash)
    assert posted["ok"] is False
    assert posted["retryable"] is False
    assert "control character" in posted["error"]


def test_a_nul_in_a_whisper_rel_path_posts_a_non_retryable_failure(tmp_path):
    from test_jobs_runner import a_job, a_pipeline, a_vault, make
    a_pipeline(tmp_path)
    a_vault(tmp_path)
    dash = FakeDashboard(a_job(tmp_path, rel_path="Vault/2026/FF5/Ep/\x00x"))
    r = make(tmp_path, dash)
    r.note_report_reply({"commands": {"jobs": {"offered": [7]}}})
    r.tick()
    posted = dash.results[-1]
    assert posted["ok"] is False
    assert posted["retryable"] is False


@pytest.mark.parametrize("exc, retryable", [
    (ValueError("embedded null character in path"), False),
    (OSError("the share went away"), True),
])
def test_any_placement_error_is_answered_not_dropped(tmp_path, monkeypatch,
                                                     exc, retryable):
    """Belt and braces past job_paths: whatever Path raises, the dashboard
    hears about it. On HEAD a plain ValueError escaped tick() and nothing was
    posted, so every claimant dropped the job until its lease expired."""
    def boom(_job):
        raise exc

    dash = FakeDashboard(a_media_job())
    r = media_runner(tmp_path, dash)
    monkeypatch.setattr(r, "_media_paths", boom)
    posted = _run(r, dash)
    assert posted["ok"] is False
    assert posted["retryable"] is retryable


def test_a_root_this_machine_lacks_is_still_retryable_elsewhere(tmp_path, monkeypatch):
    monkeypatch.setattr(jobs_media, "MediaJob", FakeRecipe)
    dash = FakeDashboard(a_media_job())
    r = media_runner(tmp_path, dash)
    r.cfg["jobs_media_root"] = str(tmp_path / "not-mounted")
    posted = _run(r, dash)
    assert posted["retryable"] is True


# ---------------------------------------------------------------------------
# bug-comp-media-4 - peaks on a video-only clip toured the fleet
# ---------------------------------------------------------------------------

class _Proc:
    """A finished ffmpeg: exit code, empty stdout, stderr lines."""

    def __init__(self, code, stderr):
        import io
        self.returncode = code
        self.stdout = io.BytesIO(b"")
        self.stderr = io.StringIO(stderr)

    def poll(self):
        return self.returncode

    def wait(self, timeout=None):
        return self.returncode

    def kill(self):
        pass


def _peaks_job(monkeypatch, codec, code, stderr):
    monkeypatch.setattr(jobs_media, "probe_audio", lambda *_a: (codec, None))
    return jobs_media.MediaJob(ffmpeg_path="ffmpeg",
                               popen=lambda *a, **k: _Proc(code, stderr))


_NO_STREAM = ("[out#0/s16le @ 0000] Output file does not contain any stream\n"
              "Error opening output file -.\n")


def test_peaks_of_a_clip_with_no_audio_is_not_retryable(tmp_path, monkeypatch):
    src = tmp_path / "drone.mp4"
    src.write_bytes(b"x")
    job = _peaks_job(monkeypatch, None, 1, _NO_STREAM)
    with pytest.raises(jobs_media.MediaJobError) as caught:
        job.run("peaks", src, tmp_path / "out", "Drone")
    assert caught.value.retryable is False
    assert str(caught.value) == "no audio track"


def test_ffmpeg4s_spelling_of_the_same_refusal_counts_too(tmp_path, monkeypatch):
    src = tmp_path / "drone.mp4"
    src.write_bytes(b"x")
    job = _peaks_job(monkeypatch, None, 1,
                     "Output file #0 does not contain any stream\n")
    with pytest.raises(jobs_media.MediaJobError) as caught:
        job.run("peaks", src, tmp_path / "out", "Drone")
    assert caught.value.retryable is False


@pytest.mark.parametrize("codec, stderr", [
    # ffprobe could not run (codec None) and ffmpeg failed for another reason:
    # that is this machine's trouble, not the file's.
    (None, "Error reading header: I/O error\n"),
    # The probe saw audio, so a "no stream" sentence is not the whole story.
    ("aac", _NO_STREAM),
])
def test_other_peaks_failures_stay_retryable(tmp_path, monkeypatch, codec, stderr):
    src = tmp_path / "clip.mp4"
    src.write_bytes(b"x")
    job = _peaks_job(monkeypatch, codec, 1, stderr)
    with pytest.raises(jobs_media.MediaJobError) as caught:
        job.run("peaks", src, tmp_path / "out", "Clip")
    assert caught.value.retryable is True


def test_a_real_video_only_file_is_refused_permanently(tmp_path):
    """The verifier's reproduction, as a test: the exact peaks argv on a real
    video-only mp4."""
    if not (FFMPEG and FFPROBE):
        require_ffmpeg_or_skip("no ffmpeg/ffprobe here")
    src = tmp_path / "vonly.mp4"
    subprocess.run([FFMPEG, "-y", "-loglevel", "error", "-f", "lavfi", "-i",
                    "testsrc=size=64x64:rate=5:duration=1", "-c:v", "libx264",
                    "-pix_fmt", "yuv420p", str(src)], check=True, timeout=120)
    with pytest.raises(jobs_media.MediaJobError) as caught:
        jobs_media.MediaJob(ffmpeg_path=FFMPEG).run(
            "peaks", src, tmp_path / "out", "Drone")
    assert caught.value.retryable is False


# ---------------------------------------------------------------------------
# bug-comp-media-5 - proxy_gen's gate asked for ffmpeg and not ffprobe
# ---------------------------------------------------------------------------

def test_ffmpeg_without_ffprobe_is_not_running(tmp_path, monkeypatch, caplog):
    monkeypatch.setattr(ffmpeg_tools, "ffprobe_for", lambda _p: "ffprobe")
    asked: list = []

    def available(path):
        asked.append(path)
        return (path != "ffprobe", "found" if path != "ffprobe" else "missing")

    gen = _make_gen(tmp_path, available_fn=available)
    with caplog.at_level("WARNING", logger="ccsync.proxy_gen"):
        assert gen._check_ffmpeg() is False
        assert gen._gate() == proxy_gen.STATE_NO_FFMPEG
    assert "ffprobe" in asked
    warnings = [r.getMessage() for r in caplog.records if r.levelname == "WARNING"]
    assert len(warnings) == 1 and "ffprobe is not" in warnings[0]


def test_ffmpeg_and_ffprobe_together_pass_the_gate(tmp_path, monkeypatch):
    monkeypatch.setattr(ffmpeg_tools, "ffprobe_for", lambda _p: "ffprobe")
    gen = _make_gen(tmp_path, available_fn=lambda path: (True, path))
    assert gen._check_ffmpeg() is True


# -- ui-copy-4 (owed by c-ytdl): the proxy toast says "computer" -------------

def test_the_proxy_toast_says_computer_not_machine(tmp_path):
    """The editor's word is "computer" (the tray's THIS COMPUTER). Both
    variants that named the machine are asserted: the split count and the
    no-ffmpeg tail."""
    gen = _make_gen(tmp_path)
    gen.generation_enabled = True
    gen._ffmpeg_ok = False
    text = gen._notify_text("Episodes/Energy Transition", {"missing": 40},
                            project_missing=12)
    assert "(40 on this computer)" in text
    assert "This computer has no ffmpeg" in text
    assert "machine" not in text.lower()


def test_the_low_space_balloon_does_not_say_lane(tmp_path):
    """Review round: the same generator's other tray balloon, the low-space
    one, said "so the sync lanes and Resolve's cache do not run out". Driven
    through free_space_shortfall -> _surface_low_space -> notify, the path an
    editor actually sees. Plural-aware on purpose: the copy scan's word regex
    is `\blane\b` and does not see "lanes"."""
    import collections
    usage = collections.namedtuple("usage", "total used free")
    gb = 1024 ** 3
    shown = []
    gen = _make_gen(tmp_path, notify=lambda *a, **k: shown.append(a[0]),
                    disk_usage_fn=lambda _p: usage(500 * gb, 499 * gb, 1 * gb))
    why = gen.free_space_shortfall(str(tmp_path / "Proxy" / "A.mp4.partial"))
    assert why is not None
    gen._surface_low_space(why)
    assert len(shown) == 1
    text = shown[0].lower()
    assert "so syncing and resolve's cache do not run out" in text
    assert re.search(r"\blanes?\b", text) is None
    assert re.search(r"\bmachines?\b", text) is None
