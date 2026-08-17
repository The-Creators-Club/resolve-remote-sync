"""proxy_history tests: the ledger, its rollup and the rate estimate.

The properties under this file are the two that make a ledger worth having:
it must SURVIVE (a restart, a torn line, a totals file from another version)
and it must never be able to fail the encode it is recording. Everything
here drives real files in tmp_path -- the whole module is I/O, and a faked
filesystem would test nothing.
"""

from __future__ import annotations

import json

import pytest

from ccsync_companion import proxy_history


class _Clock:
    """A wall clock the test drives, so day boundaries and rates are exact."""

    def __init__(self, start=1_786_000_000.0):
        self.now = start

    def __call__(self):
        return self.now

    def tick(self, seconds):
        self.now += seconds
        return self.now


def _history(tmp_path, clock=None):
    return proxy_history.ProxyHistory(tmp_path / "state", wall_clock=clock or _Clock())


def _done(history, name="A001.MP4", src=1_000_000, proxy=100_000, duration=60.0,
          encode_s=10.0, project="2026/FF5/Nuclear"):
    history.record(
        proxy_history.RESULT_DONE, f"P:\\Projects\\{project}\\{name}",
        project=project, kind="own", encoder="hevc_nvenc",
        src_bytes=src, proxy_bytes=proxy, duration_s=duration, encode_s=encode_s,
    )


# -- writing ------------------------------------------------------------------


def test_a_finished_clip_lands_in_the_ledger_and_the_rollup(tmp_path):
    history = _history(tmp_path)
    _done(history)

    lines = (tmp_path / "state" / "proxy_history.jsonl").read_text(
        encoding="utf-8").splitlines()
    assert len(lines) == 1
    entry = json.loads(lines[0])
    assert entry["result"] == "done"
    assert entry["name"] == "A001.MP4"
    assert entry["project"] == "2026/FF5/Nuclear"
    assert entry["src_bytes"] == 1_000_000 and entry["proxy_bytes"] == 100_000

    totals = json.loads((tmp_path / "state" / "proxy_totals.json").read_text("utf-8"))
    assert totals["lifetime"]["done"] == 1
    assert totals["lifetime"]["src_bytes"] == 1_000_000


def test_the_rollup_survives_a_restart(tmp_path):
    """The whole point: `_generated` resets when the companion does, and
    'what has this machine made' must not reset with it."""
    clock = _Clock()
    first = _history(tmp_path, clock)
    _done(first)
    _done(first)

    second = _history(tmp_path, clock)          # a new companion process
    assert second.snapshot()["lifetime"]["done"] == 2
    _done(second)
    assert second.snapshot()["lifetime"]["done"] == 3


def test_a_failure_is_counted_and_keeps_its_reason(tmp_path):
    history = _history(tmp_path)
    history.record(proxy_history.RESULT_FAILED, "P:\\A002.MP4",
                   error="ffmpeg exited 1: no moov atom", encode_s=3.0)

    snap = history.snapshot()
    assert snap["lifetime"]["failed"] == 1 and snap["lifetime"]["done"] == 0
    entry = json.loads(
        (tmp_path / "state" / "proxy_history.jsonl").read_text("utf-8").splitlines()[0])
    assert "no moov atom" in entry["error"]


def test_the_day_bucket_follows_the_local_day(tmp_path):
    clock = _Clock()
    history = _history(tmp_path, clock)
    _done(history)
    day = history.today_key()
    assert history.snapshot()["today"]["done"] == 1

    clock.tick(48 * 3600)
    assert history.today_key() != day
    # A new day starts at zero, and yesterday's total is still in the rollup.
    assert history.snapshot()["today"]["done"] == 0
    assert history.snapshot()["lifetime"]["done"] == 1


def test_cjk_filenames_stay_readable_in_the_ledger(tmp_path):
    """The tree is full of them (P:\\...\\無人機課程\\), and a ledger full of
    \\uXXXX escapes is one nobody can grep."""
    history = _history(tmp_path)
    _done(history, name="無人機課程.MP4")
    text = (tmp_path / "state" / "proxy_history.jsonl").read_text(encoding="utf-8")
    assert "無人機課程.MP4" in text


# -- never raises -------------------------------------------------------------


def test_a_ledger_that_cannot_be_written_is_not_an_error(tmp_path):
    """Bookkeeping must never fail an encode that succeeded. The state dir
    is a FILE here, so every mkdir/open below it fails."""
    blocked = tmp_path / "state"
    blocked.write_text("not a directory", encoding="utf-8")
    history = proxy_history.ProxyHistory(blocked)
    _done(history)                                  # must not raise
    assert history.snapshot()["lifetime"]["done"] == 1   # still counted in memory


def test_a_torn_last_line_does_not_break_the_reader(tmp_path):
    history = _history(tmp_path)
    _done(history)
    with open(tmp_path / "state" / "proxy_history.jsonl", "a", encoding="utf-8") as fh:
        fh.write('{"at": "2026-08-17T02:00:0')   # killed mid-write
    rows = history.recent()
    assert len(rows) == 1 and rows[0]["name"] == "A001.MP4"


def test_a_totals_file_from_another_version_starts_from_zero(tmp_path):
    (tmp_path / "state").mkdir()
    (tmp_path / "state" / "proxy_totals.json").write_text(
        '{"lifetime": {"done": "lots"}, "days": "nope"}', encoding="utf-8")
    history = _history(tmp_path)
    assert history.snapshot()["lifetime"]["done"] == 0
    _done(history)                                  # and still usable
    assert history.snapshot()["lifetime"]["done"] == 1


def test_an_unreadable_totals_file_is_not_an_error(tmp_path):
    (tmp_path / "state").mkdir()
    (tmp_path / "state" / "proxy_totals.json").write_text("{{{", encoding="utf-8")
    assert _history(tmp_path).snapshot()["lifetime"]["done"] == 0


# -- rotation -----------------------------------------------------------------


def test_the_ledger_rotates_once_and_recent_reads_across_the_seam(tmp_path):
    history = proxy_history.ProxyHistory(
        tmp_path / "state", wall_clock=_Clock(), max_ledger_bytes=400)
    for index in range(12):
        _done(history, name=f"A{index:03d}.MP4")

    ledger = tmp_path / "state" / "proxy_history.jsonl"
    assert (tmp_path / "state" / "proxy_history.jsonl.1").exists()
    # ONE generation, so the oldest records are gone on purpose -- the live
    # file stays small rather than the history staying complete.
    live = ledger.read_text(encoding="utf-8").splitlines()
    assert len(live) < 12
    # Newest first, and reading on past the seam into the `.1` to fill the
    # request rather than stopping at the top of the current file.
    names = [row["name"] for row in history.recent(12)]
    assert names[0] == "A011.MP4"
    assert len(names) > len(live)
    # The rollup counts every clip, including the ones rotated out of reach:
    # that is the number the tray shows, and it must not fall when the
    # ledger rolls.
    assert history.snapshot()["lifetime"]["done"] == 12


# -- the rate estimate --------------------------------------------------------


def test_the_rate_needs_a_few_samples_before_it_answers(tmp_path):
    clock = _Clock()
    history = _history(tmp_path, clock)
    assert history.rate_per_hour() is None
    _done(history)
    clock.tick(60)
    _done(history)
    assert history.rate_per_hour() is None          # two is still noise


def test_the_rate_is_measured_from_completion_times(tmp_path):
    """One clip a minute is 60/h -- whether that is one worker or four, which
    is exactly what summing per-clip encode seconds would get wrong."""
    clock = _Clock()
    history = _history(tmp_path, clock)
    for _ in range(5):
        _done(history, encode_s=240.0)              # 4 workers, 4 min each
        clock.tick(60)
    assert history.rate_per_hour() == pytest.approx(60.0, rel=0.01)


def test_the_eta_is_the_queue_at_the_recent_rate(tmp_path):
    clock = _Clock()
    history = _history(tmp_path, clock)
    for _ in range(5):
        _done(history)
        clock.tick(60)
    assert history.eta_seconds(30) == pytest.approx(1800.0, rel=0.01)
    assert history.eta_seconds(0) is None
    assert history.eta_seconds(None) is None


def test_failures_do_not_count_toward_the_rate(tmp_path):
    """A ledger of failures completes instantly and would claim thousands of
    clips an hour, promising an ETA nothing can meet."""
    clock = _Clock()
    history = _history(tmp_path, clock)
    for _ in range(5):
        history.record(proxy_history.RESULT_FAILED, "P:\\bad.MP4", error="no")
        clock.tick(1)
    assert history.rate_per_hour() is None


# -- the snapshot (what the tray reads) ---------------------------------------


def test_the_snapshot_is_scalars_only(tmp_path):
    """It crosses into the dashboard report payload, where the size guard
    should never have to think about it."""
    history = _history(tmp_path)
    _done(history)
    snap = history.snapshot(10)
    for key, value in snap.items():
        if key in ("today", "lifetime"):
            assert all(isinstance(v, (int, float)) for v in value.values())
        else:
            assert value is None or isinstance(value, (int, float, str))


def test_the_snapshot_does_not_read_the_disk(tmp_path):
    """gap() calls this on the tray's refresh thread, where the win32 message
    loop stalls behind any I/O. Deleting the files must change nothing."""
    history = _history(tmp_path)
    _done(history)
    (tmp_path / "state" / "proxy_totals.json").unlink()
    (tmp_path / "state" / "proxy_history.jsonl").unlink()
    assert history.snapshot()["lifetime"]["done"] == 1


# -- the report ---------------------------------------------------------------


def test_the_report_names_what_was_made(tmp_path):
    history = _history(tmp_path)
    _done(history, name="A001.MP4", src=1_000_000_000, proxy=50_000_000)
    history.record(proxy_history.RESULT_FAILED, "P:\\A002.MP4", error="no moov atom")

    text = history.report()
    assert "A001.MP4" in text and "A002.MP4" in text
    assert "no moov atom" in text
    assert "1 proxies made" in text or "1 proxy" in text
    assert "failed" in text


def test_the_report_is_written_beside_the_ledger(tmp_path):
    history = _history(tmp_path)
    _done(history)
    path = history.write_report()
    assert path and path.endswith("proxy_history.txt")
    assert "CCSync" in (tmp_path / "state" / "proxy_history.txt").read_text("utf-8")


def test_an_empty_ledger_still_renders(tmp_path):
    assert "Nothing has been encoded" in _history(tmp_path).report()


def test_the_day_rollup_is_capped_and_the_lifetime_is_not(tmp_path):
    """A rig that has been running for a year keeps a quarter of it. The
    lifetime total is the number that is meant to keep growing."""
    clock = _Clock()
    history = _history(tmp_path, clock)
    for _ in range(proxy_history.MAX_DAYS + 10):
        _done(history)
        clock.tick(24 * 3600)

    assert history.snapshot()["lifetime"]["done"] == proxy_history.MAX_DAYS + 10
    on_disk = json.loads((tmp_path / "state" / "proxy_totals.json").read_text("utf-8"))
    assert len(on_disk["days"]) == proxy_history.MAX_DAYS
    # In memory too: the file and the object must not disagree about which
    # days exist.
    assert len(history._days) == proxy_history.MAX_DAYS


def test_human_helpers_never_raise_on_rubbish():
    assert proxy_history.human_bytes(None) == "0 B"
    assert proxy_history.human_bytes("x") == "0 B"
    assert proxy_history.human_duration(None) == "0s"
    assert proxy_history.human_duration(-5) == "0s"
    assert proxy_history.human_duration(3600) == "1h"
