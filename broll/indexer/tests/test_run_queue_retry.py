"""What run_queue does with a stage that exited non-zero.

The decision used to be `any(k in out.lower() for k in (... "429" ...))` over the
child's ENTIRE tee'd transcript. parallel_claude prints "N videos to index" and a
"[i/N] ... last=<vid>:<status>" progress line every fifth video, so on a queue of
429 (or 1429, or 4290-something) videos — or one touching any of the 35 live ids
containing those digits — the string was in the output no matter WHY the stage
died. A permanent failure (expired login, exhausted credit, a bad model name)
then read as a transient limit: sleep 15 minutes, relaunch, burn another full set
of concurrent failing calls, repeat, while the watchdog saw a live run_queue and
stayed quiet (BROLL-IDX-3, 2026-08-14).
"""
from __future__ import annotations

import sys

import pytest
import run_queue
import yaml

# Verbatim shapes from a real run: the counter and the per-video line that put
# "429" in the output of a stage that never saw a rate limit.
PROGRESS = (
    "429 videos to index, 12 workers\n"
    "[429/2024] 3.1/min  eta 8.6h  ok=400 err=2 skip=27  last=4291:ok\n"
    "\ndone 400, errors 2, skipped 27, not-started 0 in 129.0 min (3.10/min)\n"
)
AUTH_FAILURE = PROGRESS + "claude stage aborted: API error: authentication_error: invalid x-api-key\n"
SESSION_LIMIT = PROGRESS + "claude stage aborted: API error 429: You've hit your session limit\n"


def _config(tmp_path) -> str:
    p = tmp_path / "c.yaml"
    p.write_text(yaml.safe_dump({"db": {"path": str(tmp_path / "b.db")}}), encoding="utf-8")
    return str(p)


def _drive(monkeypatch, tmp_path, outcomes, *, remaining_values=None):
    """Run main() over a scripted sequence of (rc, output) stage results.

    Returns (exit code, sleeps taken, number of stage launches).
    """
    calls, sleeps = [], []
    seq = list(outcomes)

    def fake_run_cmd(cmd):
        calls.append(cmd)
        return seq[min(len(calls) - 1, len(seq) - 1)]

    counter = iter(remaining_values) if remaining_values is not None else None

    def fake_remaining(_db):
        return next(counter) if counter is not None else 100

    monkeypatch.setattr(run_queue, "run_cmd", fake_run_cmd)
    monkeypatch.setattr(run_queue, "remaining", fake_remaining)
    monkeypatch.setattr(run_queue, "counts", lambda _db: {})
    monkeypatch.setattr(run_queue.time, "sleep", lambda s: sleeps.append(s))
    monkeypatch.setattr(sys, "argv", ["run_queue.py", "--config", _config(tmp_path),
                                      "--stages", "claude"])
    return run_queue.main(), sleeps, len(calls)


def test_the_abort_line_is_what_is_matched_not_the_progress_chatter():
    assert run_queue.abort_reason(PROGRESS) is None
    assert run_queue.abort_reason(AUTH_FAILURE) == \
        "API error: authentication_error: invalid x-api-key"
    assert run_queue.abort_reason(SESSION_LIMIT) == \
        "API error 429: You've hit your session limit"


def test_the_serial_paths_traceback_tail_counts_as_an_abort_line():
    """`broll-index run` does not catch FatalRunError, so the traceback carries it."""
    out = (
        "run: processing\nTraceback (most recent call last):\n"
        "  File \"cli.py\", line 75, in cmd_run\n"
        "broll_index.pipeline.FatalRunError: claude exited 1: API error 429: "
        "You've hit your session limit\n"
    )
    assert run_queue.abort_reason(out).startswith("claude exited 1: API error 429")


def test_the_last_abort_line_wins():
    out = SESSION_LIMIT + AUTH_FAILURE
    assert "authentication_error" in run_queue.abort_reason(out)


def test_a_permanent_failure_stops_even_when_429_is_in_the_progress_lines(
    tmp_path, monkeypatch
):
    """The bug, exactly: an expired login on a 429-video queue looked transient."""
    rc, sleeps, launches = _drive(monkeypatch, tmp_path, [(1, AUTH_FAILURE)])

    assert rc == 1, "an auth failure must stop the run, not park it"
    assert sleeps == [], "and it must not sleep on a limit that never happened"
    assert launches == 1, "nor relaunch a stage that will fail identically"


def test_a_real_session_limit_still_waits_and_resumes(tmp_path, monkeypatch):
    rc, sleeps, launches = _drive(monkeypatch, tmp_path, [(1, SESSION_LIMIT), (0, "done")])

    assert rc == 0
    assert sleeps == [run_queue.RETRY_WAIT_S], "no parseable reset time -> the blind poll"
    assert launches == 2


def test_a_stage_that_never_says_why_it_died_stops_as_before(tmp_path, monkeypatch):
    """No abort line and no progress: the pre-existing "failed with no progress"
    path, unchanged."""
    rc, sleeps, _ = _drive(monkeypatch, tmp_path, [(2, "unknown share(s): ff9\n")])

    assert rc == 1
    assert sleeps == []


def test_endless_limits_with_no_progress_eventually_stop(tmp_path, monkeypatch):
    """A limit that never clears is not a limit. Without a ceiling this looped
    every 15 minutes forever while nothing was indexed."""
    rc, sleeps, _ = _drive(monkeypatch, tmp_path, [(1, SESSION_LIMIT)])

    assert rc == 1
    assert sum(sleeps) <= run_queue.MAX_LIMIT_WAIT_S
    assert len(sleeps) == run_queue.MAX_LIMIT_WAIT_S // run_queue.RETRY_WAIT_S


def test_a_bursty_run_that_keeps_indexing_is_never_cut_off(tmp_path, monkeypatch):
    """The normal multi-day shape: index some, hit the limit, wait, index some
    more. Progress resets the ceiling, so it can run for as long as it needs."""
    # Every attempt places videos before hitting the limit again, for far longer
    # than the ceiling would otherwise allow, then finishes clean.
    rounds = int(run_queue.MAX_LIMIT_WAIT_S // run_queue.RETRY_WAIT_S) * 3
    outcomes = [(1, SESSION_LIMIT)] * rounds + [(0, "done")]
    remaining_values = []
    left = 1000
    for _ in range(rounds + 1):
        remaining_values += [left, left - 5]
        left -= 5

    rc, sleeps, launches = _drive(monkeypatch, tmp_path, outcomes,
                                  remaining_values=remaining_values)

    assert rc == 0
    assert len(sleeps) == rounds
    assert launches == rounds + 1


@pytest.mark.parametrize("message", [
    "ffprobe failed on C0429.MP4: moov atom not found",
    "claude response is not valid JSON: Expecting ',' delimiter (char 429)",
])
def test_a_stage_aborting_on_a_429_shaped_filename_is_not_a_limit(tmp_path, monkeypatch,
                                                                  message):
    """The BROLL-IDX-1 triggers, seen from this side: even as a genuine abort
    line, a local failure carrying those digits must not park the run."""
    rc, sleeps, _ = _drive(monkeypatch, tmp_path,
                           [(1, f"claude stage aborted: {message}\n")])

    assert rc == 1
    assert sleeps == []
