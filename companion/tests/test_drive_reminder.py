"""drive_reminder.py -- the sync drive went out with work still to go (CR-92).

Everything here runs without a thread except the one test that proves the
thread wakes on the interval; the rest drive remind_now() by hand.
"""

from __future__ import annotations

import json
import threading
import time

from ccsync_companion import drive_reminder as dr
from ccsync_companion.sync.base import LaneStatus


def _status(name, state="syncing", **kw):
    return LaneStatus(name=name, state=state, **kw)


class _Notes:
    def __init__(self):
        self.sent: list[tuple[str, str]] = []

    def __call__(self, message, title):
        self.sent.append((message, title))


def _reminder(tmp_path, interval=0.0, **kw):
    notes = _Notes()
    reminder = dr.DriveReminder(
        notify_fn=notes,
        drive_phrase_fn=lambda: "Your Studio drive",
        interval=interval,
        state_path=tmp_path / "state" / dr.STATE_FILENAME,
        **kw,
    )
    return reminder, notes


# --- what "unfinished" means -------------------------------------------------

def test_nothing_busy_is_none():
    assert dr.unfinished_work([]) is None
    assert dr.unfinished_work(None) is None


def test_counts_name_the_lane_and_sum_the_bytes():
    work = dr.unfinished_work([
        _status("lane_a_video_up", transferring=2, bytes_total=3_000_000_000,
                bytes_done=1_000_000_000),
        _status("lane_c_syncthing", queued=14),
    ])
    assert work is not None
    assert work.items == ["2 uploads", "14 other files"]
    assert work.bytes_left == 2_000_000_000
    assert work.summary() == "2 uploads and 14 other files (1.9 GB left)"


def test_a_syncing_lane_with_zero_counters_still_counts_as_one():
    """rclone's `queued` is 0 during and after every run and `transferring`
    is empty between stats ticks -- the STATE is the fact."""
    work = dr.unfinished_work([_status("lane_b_proxy_down")])
    assert work is not None
    assert work.summary() == "1 proxy download"


def test_three_items_read_as_a_list():
    work = dr.unfinished_work([
        _status("lane_a_video_up", transferring=1),
        _status("lane_b_proxy_down", transferring=3),
        _status("lane_c_syncthing", queued=2),
    ])
    assert work.summary() == "1 upload, 3 proxy downloads and 2 other files"


def test_an_idle_lane_with_no_backlog_is_skipped_and_garbage_does_not_raise():
    work = dr.unfinished_work([_status("lane_a_video_up", state="idle"), object(), None])
    assert work is None


def test_the_sentences_carry_the_drive_phrase_and_no_em_dash():
    first = dr.first_warning("Your Studio drive", "2 uploads (1.9 GB left)")
    again = dr.reminder("Your Studio drive", "2 uploads (1.9 GB left)")
    assert first.startswith("Your Studio drive was disconnected before syncing finished")
    assert "2 uploads (1.9 GB left) still to go" in first
    assert first.endswith("Plug it back in to finish syncing.")
    assert again.startswith("Your Studio drive is still disconnected")
    assert again.endswith("Plug it back in to finish syncing.")
    for text in (first, again, dr.notify_title()):
        assert "—" not in text
        assert len(text) < 250


# --- the interval knob ---------------------------------------------------------

def test_interval_defaults_to_thirty_minutes_and_zero_is_legal():
    assert dr.interval_seconds({}) == 30 * 60.0
    assert dr.interval_seconds(None) == 30 * 60.0
    assert dr.interval_seconds({"drive_reminder_minutes": 0}) == 0.0
    assert dr.interval_seconds({"drive_reminder_minutes": "5"}) == 300.0


def test_a_bad_interval_falls_back_without_raising():
    assert dr.interval_seconds({"drive_reminder_minutes": -3}) == 30 * 60.0
    assert dr.interval_seconds({"drive_reminder_minutes": "soon"}) == 30 * 60.0


# --- the episode -----------------------------------------------------------------

def test_begin_warns_once_records_and_is_idempotent(tmp_path):
    reminder, notes = _reminder(tmp_path)

    reminder.begin("2 uploads (1.9 GB left)")
    reminder.begin("something else")  # same episode: ignored

    assert reminder.active
    assert reminder.summary == "2 uploads (1.9 GB left)"
    assert len(notes.sent) == 1
    message, title = notes.sent[0]
    assert "was disconnected before syncing finished: 2 uploads (1.9 GB left)" in message
    assert title == dr.notify_title()
    record = json.loads((tmp_path / "state" / dr.STATE_FILENAME).read_text())
    assert record["summary"] == "2 uploads (1.9 GB left)"


def test_an_empty_summary_starts_nothing(tmp_path):
    reminder, notes = _reminder(tmp_path)
    reminder.begin("")
    reminder.begin(None)
    assert not reminder.active
    assert notes.sent == []
    assert not (tmp_path / "state" / dr.STATE_FILENAME).exists()


def test_remind_now_repeats_the_plug_it_back_in_sentence(tmp_path):
    reminder, notes = _reminder(tmp_path)
    reminder.begin("1 upload")

    assert reminder.remind_now() is True
    assert reminder.remind_now() is True

    assert reminder.reminders_sent == 2
    assert len(notes.sent) == 3
    assert all("still disconnected" in m for m, _t in notes.sent[1:])
    assert all(m.endswith("Plug it back in to finish syncing.") for m, _t in notes.sent[1:])


def test_clear_stops_the_reminders_and_forgets_the_record(tmp_path):
    reminder, notes = _reminder(tmp_path)
    reminder.begin("1 upload")
    reminder.clear()

    assert not reminder.active
    assert reminder.summary is None
    assert reminder.remind_now() is False
    assert not (tmp_path / "state" / dr.STATE_FILENAME).exists()
    assert len(notes.sent) == 1
    # Clearing with nothing open is a no-op, not an error.
    reminder.clear()


def test_suspend_keeps_the_record_and_a_new_instance_resumes_it(tmp_path):
    """A companion that quits (self-upgrade, reboot) with the drive out owing
    work restarts with the drive out owing work: the reminders carry on,
    starting with one straight away, and NOT with the first warning again."""
    first, _notes = _reminder(tmp_path)
    first.begin("2 uploads")
    first.suspend()
    assert (tmp_path / "state" / dr.STATE_FILENAME).exists()

    second, notes = _reminder(tmp_path)
    assert second.resume_remembered() is True
    assert second.active
    assert second.summary == "2 uploads"
    assert len(notes.sent) == 1
    assert "still disconnected" in notes.sent[0][0]
    assert "was disconnected before" not in notes.sent[0][0]


def test_resume_with_no_record_is_false_and_silent(tmp_path):
    reminder, notes = _reminder(tmp_path)
    assert reminder.resume_remembered() is False
    assert notes.sent == []


def test_a_corrupt_record_is_ignored(tmp_path):
    path = tmp_path / "state" / dr.STATE_FILENAME
    path.parent.mkdir(parents=True)
    path.write_text("{not json", encoding="utf-8")
    reminder, notes = _reminder(tmp_path)
    assert reminder.resume_remembered() is False
    path.write_text(json.dumps([1, 2, 3]), encoding="utf-8")
    assert reminder.resume_remembered() is False
    assert notes.sent == []


def test_a_notifier_that_raises_costs_nothing_else(tmp_path):
    def boom(message, title):
        raise RuntimeError("no tray")

    reminder = dr.DriveReminder(boom, lambda: "Your drive", interval=0.0,
                                state_path=tmp_path / dr.STATE_FILENAME)
    reminder.begin("1 upload")
    assert reminder.active
    assert reminder.remind_now() is True


def test_no_state_path_means_no_record_and_no_error():
    notes = _Notes()
    reminder = dr.DriveReminder(notes, lambda: "Your drive", interval=0.0, state_path=None)
    reminder.begin("1 upload")
    assert reminder.active
    assert reminder.resume_remembered() is False
    reminder.clear()


# --- the thread ------------------------------------------------------------------

def test_the_thread_reminds_on_the_interval_and_stops_on_clear(tmp_path):
    reminder, notes = _reminder(tmp_path, interval=0.05)
    reminder.begin("1 upload")
    thread = reminder._thread
    assert thread is not None and thread.is_alive() and thread.daemon

    deadline = time.monotonic() + 3.0
    while reminder.reminders_sent < 2 and time.monotonic() < deadline:
        time.sleep(0.01)
    assert reminder.reminders_sent >= 2

    reminder.clear()
    assert not thread.is_alive()
    sent = reminder.reminders_sent
    time.sleep(0.15)
    assert reminder.reminders_sent == sent


def test_interval_zero_means_first_warning_only(tmp_path):
    reminder, notes = _reminder(tmp_path, interval=0)
    reminder.begin("1 upload")
    assert reminder._thread is None
    assert len(notes.sent) == 1
    reminder.clear()


def test_begin_after_clear_is_a_fresh_episode(tmp_path):
    reminder, notes = _reminder(tmp_path, interval=0.05)
    reminder.begin("1 upload")
    reminder.clear()
    reminder.begin("3 other files")
    assert reminder.active and reminder.summary == "3 other files"
    assert reminder._thread is not None and reminder._thread.is_alive()
    assert threading.active_count() >= 2
    reminder.clear()
