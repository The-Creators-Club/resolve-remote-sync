"""The sync drive went out with work still owed. Say so, and keep saying so.

root_guard.py notices an external SSD being unplugged and app.py pauses the
lanes with one calm "Sync paused: your drive is disconnected" balloon -- the
right sentence for a drive taken away at the end of a finished day, and the
wrong one for a drive pulled mid-upload. Before this module (CR-92,
2026-08-28) the two cases were indistinguishable on screen: an editor who
ejected the SSD with three camera originals part-uploaded got the same
balloon as one whose machine was up to date, and nothing ever reminded them.
rclone has no resume for SFTP uploads, so every one of those files starts
again from zero when the drive comes back -- IF the drive comes back before
the project is needed. Meanwhile the fleet page shows the machine behind,
and the only person who can fix it is looking at a tray icon that reads
"paused", which is what they asked for.

So, two things, both owned here:

  * The FIRST warning names what was still to go at the moment the drive
    disappeared -- "2 uploads and 14 other files, 2.3 GB left" -- and tells
    the editor what to do about it: plug it back in.
  * A REMINDER every drive_reminder_minutes (default 30) for as long as the
    drive stays out, with the same sentence, because a balloon seen once at
    18:02 is gone by 18:03. The interval is a config key: editors run a
    prebuilt exe, and "every half hour is too often for my one-drive
    laptop" must not need a rebuild. 0 keeps the first warning and drops
    the recurrence.

What counts as "unfinished" is NOT this module's decision: the caller hands
in the lanes that shutdown_guard.PendingTracker judged to be genuinely
alive. That matters because of CR-91 -- a lane can sit in `syncing` for
hours with nothing moving, and a reminder every half hour about an upload
that was never real is the cry-wolf failure that gets the real one ignored.
The tracker's liveness bound (keep_awake_stale_seconds) is what keeps this
honest; this module only renders and repeats.

The verdict is written to ~/.ccsync/state/drive_unfinished.json, because
the companion restarts (self-upgrade, a reboot, a Quit) and a drive that
was out with work owed is still out with work owed afterwards. root_guard
fires on_absent at startup when the drive is missing; the app then asks
here what was remembered, and the reminders carry on. The drive coming
back is the only thing that clears the file. Never a safety latch -- losing
this file costs a reminder, never data -- so it is written best-effort.

Same discipline as root_guard.py and shutdown_guard.py: injectable clock,
injectable notifier, never raises out of any public method, and every
failure path means "one fewer reminder", never a stuck thread or a paused
sync.
"""

from __future__ import annotations

import json
import logging
import os
import re
import threading
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Callable, Iterable, Optional

from . import site as site_mod

log = logging.getLogger("ccsync.drive_reminder")

STATE_FILENAME = "drive_unfinished.json"

# Default recurrence. A config key (drive_reminder_minutes) rather than a
# constant editors cannot reach; see the module docstring.
DEFAULT_REMINDER_MINUTES = 30.0

# Balloon titles are 64 WCHARs on Windows (tray_native cuts at 60); the
# message is 250. Everything rendered here stays well inside both.
def notify_title() -> str:
    """The reminder's balloon title. A FUNCTION, not a constant: read at
    import time it would be the title from before this machine ever fetched
    its site manifest (UX-4, sweep 2026-09-04)."""
    return site_mod.notify_title("sync unfinished")

# Lane key -> (singular, plural) noun for the sentence. Anything not listed
# (a lane added later) falls back to "files". Lane C is TWO-WAY, so its key
# carries the direction LaneStatus.direction names (see _lane_key): a
# download and an upload are different nouns, and a lane C episode whose
# direction is unknown or both keeps the plain "other files" it always had.
LANE_C = "lane_c_syncthing"
LANE_C_UP = LANE_C + ":up"
LANE_C_DOWN = LANE_C + ":down"
_LANE_NOUNS = {
    "lane_a_video_up": ("upload", "uploads"),
    "lane_b_proxy_down": ("proxy download", "proxy downloads"),
    LANE_C_UP: ("other file upload", "other file uploads"),
    LANE_C_DOWN: ("other file download", "other file downloads"),
    LANE_C: ("other file", "other files"),
}

# logic-sync-truth-6 (2026-09-25): which owed work earns the RECURRING
# reminder. An owed UPLOAD is a file whose only copy may be on the drive in
# the editor's bag: lane A's footage (rclone has no resume for it) and, the
# review round found, lane C's upload direction too - lane C carries every
# non-video file up (SPEC.md: its stignore drops only video and Proxy), so a
# recorder WAV or a project file is as much at risk as the footage. An owed
# DOWNLOAD already exists on the server and simply carries on when the drive
# is back, which is the dashboard's own safe-to-close rule; a half-hourly
# balloon about one is the cry-wolf this module's docstring warns about.
# So an episode recurs UNLESS everything it owes is a known download. A lane
# this module cannot place, and lane C with no direction (no peer, or both
# ways at once), recur: the safe direction for a reminder about footage.
UPLOAD_LANE = "lane_a_video_up"
DOWNLOAD_LANES = frozenset({"lane_b_proxy_down", LANE_C_DOWN})

# The download nouns, longest first so "other file downloads" is never read
# as "other file" + a stray word. Used only to recover the decision for an
# episode whose caller passed a bare summary (app.py passes
# `work.summary()`) or whose record predates the `lanes` key (a 0.9.77
# record read after an upgrade). Pinned to _LANE_NOUNS, this module's own
# producer of the sentence.
_DOWNLOAD_NOUNS = sorted(
    (n for lane in DOWNLOAD_LANES for n in _LANE_NOUNS[lane]), key=len, reverse=True)
_DOWNLOAD_ITEM = re.compile(
    r"\d+ (?:%s)" % "|".join(map(re.escape, _DOWNLOAD_NOUNS)))
_BYTES_CLAUSE = re.compile(r"\s*\([^()]*\bleft\)\s*$")


def _lane_key(name: str, direction: str) -> str:
    """The lane's key in _LANE_NOUNS: lane C with its direction attached."""
    if name == LANE_C and direction in ("up", "down"):
        return f"{name}:{direction}"
    return name


def owes_an_upload(lanes: Optional[Iterable], summary: str = "") -> bool:
    """Whether an unfinished-work episode earns the recurring reminder.

    `lanes` (Unfinished.lanes) when known decides: every lane a known
    download means no cadence; anything else - an upload, lane C with no
    known direction, a lane added later - recurs. When `lanes` is None the
    summary is read back the same way: it recurs unless every item in it is
    a known download noun. The "(2.3 GB left)" clause is not an item."""
    if lanes is not None:
        try:
            names = [str(x) for x in lanes]
        except TypeError:
            names = None
        if names:
            return not all(name in DOWNLOAD_LANES for name in names)
    text = _BYTES_CLAUSE.sub("", str(summary or "").strip())
    if not text:
        return True
    head, _sep, last = text.rpartition(" and ")
    items = [part.strip() for part in head.split(", ")] if head else []
    items.append(last.strip())
    return not all(_DOWNLOAD_ITEM.fullmatch(item) for item in items if item)


@dataclass
class Unfinished:
    """What was still to go when the drive disappeared. `items` is the
    human list ("2 uploads", "14 other files"); `bytes_left` is the sum of
    the byte counters that were known, or 0 when none were (lane C reports
    none)."""
    items: list = field(default_factory=list)
    bytes_left: int = 0
    lanes: list = field(default_factory=list)

    def summary(self) -> str:
        """"2 uploads and 14 other files (2.3 GB left)" -- the clause both
        sentences share. Never empty for a non-empty Unfinished."""
        items = list(self.items) or ["files"]
        if len(items) == 1:
            joined = items[0]
        else:
            joined = ", ".join(items[:-1]) + " and " + items[-1]
        if self.bytes_left > 0:
            joined += f" ({human_bytes(self.bytes_left)} left)"
        return joined


def human_bytes(n: Any) -> str:
    """1.2 GB / 340.0 MB / 12 B -- shutdown_guard's rendering, repeated here
    rather than imported so this module has no dependency on the power
    guards (a cycle waiting to happen: app.py imports both)."""
    try:
        size = float(n or 0)
    except (TypeError, ValueError):
        return "?"
    for unit in ("B", "KB", "MB", "GB", "TB"):
        if size < 1024 or unit == "TB":
            return f"{size:.0f} {unit}" if unit == "B" else f"{size:.1f} {unit}"
        size /= 1024
    return "?"


def unfinished_work(busy: Iterable) -> Optional[Unfinished]:
    """Render the lanes the tracker judged alive into what the editor sees.

    `busy` is already the LIVENESS-FILTERED list (PendingTracker.live_busy);
    passing raw lane statuses here would reintroduce CR-91's phantom upload.
    Returns None when nothing was outstanding, which is the common case and
    the one that must stay silent.

    An rclone lane's `queued` is 0 during and after every run and
    `transferring` is the live count, so a lane in `syncing` with both at
    zero (between stats ticks) still counts as ONE thing in flight -- the
    state is the fact, the counters are detail. Lane C has no byte counters
    at all and its queued is Syncthing's need count, which is the only
    number it has. Never raises; a malformed status is skipped.
    """
    result = Unfinished()
    for status in busy or []:
        try:
            name = str(getattr(status, "name", "") or "")
            state = str(getattr(status, "state", "") or "")
            count = int(getattr(status, "transferring", 0) or 0)
            if count <= 0:
                count = int(getattr(status, "queued", 0) or 0)
            if count <= 0:
                if state != "syncing":
                    continue
                count = 1
            # Lane C is two-way: its direction picks the noun and whether
            # the episode recurs (review round of logic-sync-truth-6).
            key = _lane_key(name, str(getattr(status, "direction", "") or ""))
            singular, plural = _LANE_NOUNS.get(key, ("file", "files"))
            result.items.append(f"{count} {singular if count == 1 else plural}")
            result.lanes.append(key)
            total = getattr(status, "bytes_total", None)
            done = getattr(status, "bytes_done", None)
            if total:
                remaining = int(total) - int(done or 0)
                if remaining > 0:
                    result.bytes_left += remaining
        except Exception:
            log.debug("drive reminder: skipping unreadable lane status", exc_info=True)
            continue
    return result if result.items else None


def first_warning(drive: str, summary: str) -> str:
    """The balloon at the moment the drive goes. `drive` is
    site.drive_phrase(capitalised=True): "Your Creators Club drive"."""
    return (f"{drive} was disconnected before syncing finished: {summary} still "
            f"to go. Plug it back in to finish syncing.")


def reminder(drive: str, summary: str) -> str:
    """The balloon every interval after that, for as long as it stays out."""
    return (f"{drive} is still disconnected and syncing is unfinished: {summary} "
            f"still to go. Plug it back in to finish syncing.")


def wedged_reminder(drive: str) -> str:
    """The reminder for a drive that is PLUGGED IN and not answering
    (SYNC-120, sweep 2026-09-03).

    Its own sentence, because "still disconnected" sends the editor to check
    a cable that is fine and leaves the one thing that does fix it unsaid.
    This is the harder failure of the two: an absent drive is obvious, a
    wedged one is not, and the editor keeps working in Resolve against it
    with their footage on one disk for as long as it lasts."""
    return (f"{drive} is still not answering, so nothing is syncing. Reconnect it "
            f"or restart this computer.")


def interval_seconds(cfg: Optional[dict], default_minutes: float = DEFAULT_REMINDER_MINUTES) -> float:
    """drive_reminder_minutes -> seconds. 0 disables the recurrence (the
    first warning is unconditional); a negative or unreadable value falls
    back to the packaged default with a log line, never an exception --
    this runs at construction, and construction must survive a hand-edited
    config (config.coerce_numeric's contract, repeated here because 0 is
    legal and coerce_numeric rejects it)."""
    raw = None
    try:
        raw = (cfg or {}).get("drive_reminder_minutes", default_minutes)
        minutes = float(raw)
        if minutes < 0:
            raise ValueError
        return minutes * 60.0
    except (TypeError, ValueError, AttributeError):
        log.error("config: drive_reminder_minutes=%r is not a number >= 0 (0 disables "
                  "the reminders) -- using %r", raw, default_minutes)
        return float(default_minutes) * 60.0


class DriveReminder:
    """One episode at a time: begin(summary) when the drive goes with work
    owed, clear() when it comes back, suspend() at teardown (keeps the
    record so the next start can carry on).

    `notify_fn(message, title)` is app._notify_tray; `clock` is only for
    tests. The thread is a daemon and wakes on a stop event, so clear() and
    suspend() return promptly regardless of the interval.
    """

    def __init__(
        self,
        notify_fn: Callable[[str, str], None],
        drive_phrase_fn: Callable[[], str],
        interval: float = DEFAULT_REMINDER_MINUTES * 60.0,
        state_path: Optional[Path] = None,
        clock: Callable[[], float] = time.time,
    ) -> None:
        self._notify = notify_fn
        self._drive_phrase = drive_phrase_fn
        try:
            self._interval = max(0.0, float(interval))
        except (TypeError, ValueError):
            self._interval = DEFAULT_REMINDER_MINUTES * 60.0
        self._state_path = Path(state_path) if state_path is not None else None
        self._clock = clock
        self._lock = threading.Lock()
        self._stop_event = threading.Event()
        self._thread: Optional[threading.Thread] = None
        self._summary: Optional[str] = None
        self._since: Optional[float] = None
        # SYNC-120: an episode can also be opened by a STATE that persists
        # rather than by work that was owed. `_sentence` is what remind_now()
        # says; `_kind` is what may end it. The two are kept apart from
        # `_summary` on purpose -- the tray renders the summary as "<N> still
        # to go", and a state has nothing to go.
        self._sentence: Optional[str] = None
        self._kind = ""
        # comp-sync-16 (2026-09-11): episode identity was `_since`, a
        # time.time() float -- and Windows' clock ticks at 15.6 ms, so two
        # reads in one tick are byte-identical (99,996 of 100,000 measured).
        # A new episode that began in the same tick as the muted one ended
        # inherited its mute: Settings said "reminders about this drive are
        # off" and hid both buttons while begin()'s thread was in fact still
        # ballooning. A counter cannot collide with itself.
        self._episode_id = 0
        self._muted_episode: Optional[int] = None
        # logic-sync-truth-6 (2026-09-25): which lanes the open unfinished
        # episode owes (None: not known, see owes_an_upload) and whether it
        # earns the recurring reminder. A state episode always recurs.
        self._lanes: Optional[list] = None
        self._recurs = True
        self.reminders_sent = 0

    # -- what the tray asks --------------------------------------------------

    @property
    def summary(self) -> Optional[str]:
        """The clause currently owed ("2 uploads (2.3 GB left)"), or None
        when nothing is -- read by the tray snapshot on every render, so it
        is a plain attribute read."""
        return self._summary

    @property
    def active(self) -> bool:
        return self._sentence is not None

    # -- episode control -----------------------------------------------------

    def begin(self, summary: str, announce: bool = True,
              lanes: Optional[Iterable] = None) -> None:
        """The drive just went with `summary` still to go. Warns now (unless
        `announce` is False: a restart carrying on a remembered episode
        goes straight to the reminder cadence, since the first warning was
        already shown before the restart), records it, starts the timer.
        Idempotent within an episode: a second begin() with the drive still
        out changes nothing.

        `lanes` is Unfinished.lanes. The first warning always goes; the
        recurring reminder only while an upload is owed (logic-sync-truth-6,
        owes_an_upload). Omitted, the summary is read back instead."""
        try:
            summary = str(summary or "").strip()
            if not summary:
                return
            try:
                lane_list = None if lanes is None else [str(x) for x in lanes]
            except TypeError:
                lane_list = None
            with self._lock:
                if self._sentence is not None:
                    return
                self._lanes = lane_list
                self._recurs = owes_an_upload(lane_list, summary)
                self._summary = summary
                self._sentence = reminder(self._drive_phrase(), summary)
                self._kind = "unfinished"
                self._since = self._clock()
                self._episode_id += 1  # comp-sync-16
            self._write_record()
            if announce:
                self._say(first_warning(self._drive_phrase(), summary))
            self._start_thread()
        except Exception:
            log.exception("drive reminder: could not begin")

    def resume_remembered(self, state: Optional[str] = None) -> bool:
        """At startup with the drive already out: pick up the episode the
        previous run recorded, if any. Returns whether one was.

        `state` is what the root guard is reporting RIGHT NOW (comp-sync-8,
        2026-09-11). A STATE episode belongs to its state -- SYNC-120 says so
        and `end_state_episode` enforces it, except at startup, where that
        guard runs before the record has been read and is a no-op. So a drive
        that wedged with nothing owed and was then quit and unplugged came
        back reminding "your drive is still not answering, reconnect it or
        restart this computer" every 30 minutes about a drive in the editor's
        bag, and only plugging it in ever ended it. A restored state episode
        is therefore kept only when the drive is in that state now; with no
        `state` given there is no basis for the claim, and the caller's own
        first announcement re-opens the right episode a moment later. The
        unfinished-work branch is untouched: work owed outlives every state
        change, which is the whole of CR-92."""
        try:
            record = self._read_record()
            if not record:
                return False
            summary = str(record.get("summary") or "").strip()
            if not summary:
                # A state episode (SYNC-120) has no owed work to name. Carry
                # it on with the sentence it was opened with, and one
                # reminder now for the same reason the unfinished branch
                # below gives one.
                sentence = str(record.get("sentence") or "").strip()
                if not sentence:
                    return False
                kind = str(record.get("kind") or "state")
                if str(state or "") != kind:
                    log.info("drive reminder: dropping the remembered %r episode -- "
                             "the drive is %s now", kind, state or "in an unknown state")
                    self._delete_record()
                    return False
                self.begin_state(kind, sentence)
                if self.active:
                    self.remind_now()
                return self.active
            log.info("drive reminder: the drive was out with work owed when the "
                     "companion last ran (%s) -- reminders carry on", summary)
            # Not the FIRST warning again (that was shown before the
            # restart), but one reminder right now: the editor has just
            # started the machine, and "still disconnected, plug it back in"
            # is the sentence they need before anything else -- then the
            # usual cadence. That one startup reminder goes for downloads
            # too: it replaces the "Sync paused" balloon this start would
            # otherwise have given, and only the CADENCE is upload-only
            # (logic-sync-truth-6). A record from before `lanes` was kept
            # (0.9.77) has none, and begin() reads its summary instead.
            raw_lanes = record.get("lanes")
            self.begin(summary, announce=False,
                       lanes=raw_lanes if isinstance(raw_lanes, list) else None)
            if self.active:
                self.remind_now()
            return self.active
        except Exception:
            log.exception("drive reminder: could not resume the remembered episode")
            return False

    def begin_state(self, state: str, sentence: str) -> None:
        """The drive is in a state that will not fix itself, and nothing was
        owed (SYNC-120). Reminds on the same cadence with `sentence`.

        No first warning: the caller has just sent one (that is the whole
        reason this arm exists), and a second balloon in the same second
        would be the thing that teaches an editor to ignore both. An
        unfinished-work episode always WINS -- it names what is at risk --
        so this never displaces one.
        """
        try:
            text = str(sentence or "").strip()
            if not text:
                return
            with self._lock:
                if self._sentence is not None:
                    return
                self._sentence = text
                self._kind = str(state or "state")
                self._lanes = None
                self._recurs = True
                self._since = self._clock()
                self._episode_id += 1  # comp-sync-16
            log.info("drive reminder: %s and nothing was owed -- reminding every "
                     "%.0f min until it answers", self._kind, self._interval / 60.0)
            self._write_record()
            self._start_thread()
        except Exception:
            log.exception("drive reminder: could not begin a state episode")

    def end_state_episode(self) -> None:
        """The state that opened a state episode has changed. Ends it, and
        ONLY it: an unfinished-work episode outlives every state change,
        because the work is still owed whatever the drive is doing now."""
        with self._lock:
            if self._kind in ("", "unfinished"):
                return
        self.clear()

    def clear(self) -> None:
        """The drive is back. Stops the reminders and forgets the episode."""
        try:
            with self._lock:
                had = self._summary or self._sentence
                self._summary = None
                self._sentence = None
                self._kind = ""
                self._since = None
                self._lanes = None
                self._recurs = True
                # comp-sync-16: the mute belongs to the episode that is
                # ending. Leaving it set was the other half of the collision.
                self._muted_episode = None
            self._stop_thread()
            self._delete_record()
            if had:
                log.info("drive reminder: cleared (%s)", had)
        except Exception:
            log.exception("drive reminder: could not clear")

    def suspend(self) -> None:
        """Teardown: stop the thread, KEEP the record. The next start reads
        it back through resume_remembered()."""
        try:
            self._stop_thread()
        except Exception:
            log.exception("drive reminder: could not suspend")

    # -- the reminder itself -------------------------------------------------

    def remind_now(self) -> bool:
        """One reminder, if an episode is open. Public so a test can drive
        the cadence without a clock; the thread calls this."""
        with self._lock:
            sentence = self._sentence
        if not sentence:
            return False
        self._say(sentence)
        self.reminders_sent += 1
        return True

    def _say(self, message: str) -> None:
        try:
            self._notify(message, notify_title())
        except Exception:
            log.debug("drive reminder: notify failed", exc_info=True)
        log.warning("%s", message)

    def _start_thread(self) -> None:
        if not self._recurs:
            log.info("drive reminder: nothing owed is an upload, so the first "
                     "warning stands alone; what is owed carries on when the "
                     "drive is back")
            return
        if self._interval <= 0:
            log.info("drive reminder: drive_reminder_minutes is 0 -- the first warning "
                     "stands alone, no reminders")
            return
        thread = self._thread
        if thread is not None and thread.is_alive():
            return
        self._stop_event.clear()
        try:
            self._thread = threading.Thread(
                target=self._loop, name="ccsync-drive-reminder", daemon=True
            )
            self._thread.start()
        except Exception:
            log.exception("drive reminder: could not start its thread")
            self._thread = None

    def _stop_thread(self) -> None:
        thread = self._thread
        self._stop_event.set()
        if thread is not None and thread.is_alive():
            thread.join(timeout=2.0)
        self._thread = None

    def _loop(self) -> None:
        try:
            while not self._stop_event.wait(self._interval):
                if not self.remind_now():
                    break
        except Exception:
            log.exception("drive reminder: loop stopped")

    # -- the record ----------------------------------------------------------

    def _write_record(self) -> None:
        if self._state_path is None:
            return
        try:
            self._state_path.parent.mkdir(parents=True, exist_ok=True)
            payload = {
                "summary": self._summary,
                # Persisted so a restart with the drive still wedged carries
                # on saying the same thing (SYNC-120): the episode outlives
                # the process, which is the case the record exists for.
                "sentence": self._sentence,
                "kind": self._kind,
                # logic-sync-truth-6: so a restart keeps the upload-only
                # cadence decision instead of re-deriving it from the words.
                "lanes": self._lanes,
                "since": self._since,
                "since_iso": time.strftime("%Y-%m-%dT%H:%M:%S", time.localtime(self._since or 0)),
            }
            tmp = self._state_path.with_suffix(".tmp")
            tmp.write_text(json.dumps(payload, indent=2), encoding="utf-8")
            os.replace(tmp, self._state_path)
        except Exception:
            log.debug("drive reminder: could not write %s", self._state_path, exc_info=True)

    def _read_record(self) -> Optional[dict]:
        if self._state_path is None:
            return None
        try:
            data = json.loads(self._state_path.read_text(encoding="utf-8-sig"))
        except (OSError, ValueError):
            return None
        except Exception:
            log.debug("drive reminder: unreadable record", exc_info=True)
            return None
        return data if isinstance(data, dict) else None

    def _delete_record(self) -> None:
        if self._state_path is None:
            return
        try:
            self._state_path.unlink()
        except FileNotFoundError:
            pass
        except Exception:
            log.debug("drive reminder: could not delete %s", self._state_path, exc_info=True)

    # -- SYNC-117: the editor can turn the repetition off, for THIS episode --
    #
    # Deliberately at the end of the class and written to touch nothing above
    # it (wave 4, 2026-09-04: another builder owns the sentences in this
    # module at the same time). The mute is a property of the OPEN EPISODE,
    # not a setting: it is not written to the record, so a restart with the
    # drive still out reminds again, and the drive coming back ends it with
    # everything else clear() ends. drive_reminder_minutes stays the way to
    # turn the cadence down for good.

    def mute_episode(self, minutes: float = 0.0) -> bool:
        """Stop reminding about the episode that is open. Returns whether
        there was one.

        `minutes > 0` is [ REMIND ME LATER ]: silence now, one reminder when
        it elapses, then the usual cadence. `0` is [ STOP REMINDING ME ABOUT
        THIS DRIVE ]: silence for the rest of the episode. Neither touches
        the record, the summary or `active`, so the standing warning line in
        the tray and in Settings stays exactly where it was - the editor
        turned off the balloon, not the fact that work is owed."""
        try:
            with self._lock:
                if self._sentence is None:
                    return False
                episode = self._episode_id
            self._stop_thread()
            try:
                wait_seconds = max(0.0, float(minutes)) * 60.0
            except (TypeError, ValueError):
                wait_seconds = 0.0
            # A SNOOZE is not a mute: the reminders are coming back, so the
            # window keeps offering both buttons rather than saying they are
            # off.
            self._muted_episode = episode if wait_seconds <= 0 else None
            if wait_seconds <= 0 or not self._recurs:
                # logic-sync-truth-6: an episode with no upload owed has no
                # cadence to come back to, so a snooze would start one.
                log.info("drive reminder: reminders muted for this episode by the "
                         "editor; the warning line stays and the drive coming back "
                         "still clears everything")
                return True

            def _snooze() -> None:
                try:
                    if self._stop_event.wait(wait_seconds):
                        return
                    if not self.remind_now():
                        return
                    # Back to the normal cadence, in this same thread: _loop
                    # is the cadence, and starting a second thread for it
                    # would leave two of them reminding.
                    self._loop()
                except Exception:
                    log.exception("drive reminder: the snooze stopped")

            self._stop_event.clear()
            thread = threading.Thread(
                target=_snooze, name="ccsync-drive-reminder", daemon=True)
            self._thread = thread
            thread.start()
            log.info("drive reminder: reminders snoozed for %.0f min", minutes)
            return True
        except Exception:
            log.exception("drive reminder: could not mute the episode")
            return False

    @property
    def reminders_muted(self) -> bool:
        """Whether THIS episode is the one that was muted. Compared against
        the episode's own start time rather than a bare flag: an episode that
        ended and a new one that began must not inherit the answer."""
        muted = getattr(self, "_muted_episode", None)
        if self._sentence is not None and not getattr(self, "_recurs", True):
            # logic-sync-truth-6: nothing owed is an upload, so no reminder is
            # coming; Settings then says so instead of offering to mute one.
            return True
        return (self._sentence is not None and muted is not None
                and muted == self._episode_id)
