"""What the proxy generator has actually made -- the ledger it never had.

Until this module the only record of a night's encoding was `companion.log`,
which rotates at 5 MB: the 1046-clip base-rig run of 2026-08-11 is already in
`companion.log.1`, and the run before it is gone. Everything else the
generator knew about its own work was in-process -- `_generated`, `_failed`
and `_failures` all reset on restart -- so after a companion upgrade nothing
anywhere could answer "what did it make?", "is it keeping up?" or "which
clips does it keep failing on?" (2026-08-17).

Two files, both in the state dir beside proxy_notify.json:

  proxy_history.jsonl   one line per finished clip, append-only, rotated at
                        MAX_LEDGER_BYTES into a single `.1` generation --
                        the companion.log idiom, for the same reason.
  proxy_totals.json     the rollup: lifetime and per local day. Small,
                        rewritten in full on every event, and the ONLY file
                        read at startup.

The rollup is mirrored IN MEMORY and answered from there, because its one
caller in the hot path is ProxyGenerator.gap() -- called on the tray's
refresh thread, where the win32 backend's message loop stalls behind any
I/O (the right-click freeze of 2026-07-26). Nothing in snapshot() touches
the disk. The ledger itself is only ever read by report(), which the tray
runs on a spawned thread.

The day key is LOCAL, not UTC: an editor asking what their machine did
"today" means their day, and on a UTC+8 rig an overnight run is exactly the
case where the two disagree. Every `at` timestamp in the ledger is UTC ISO
so the file itself stays unambiguous.

Never raises. A ledger that cannot be written must not fail an encode that
succeeded -- this whole module is bookkeeping bolted onto the thing that
actually makes the proxies (proxy_gen.py's rule 3).

Added 2026-08-17.
"""

from __future__ import annotations

import collections
import json
import logging
import os
import threading
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable, Optional

# "ccsync.proxy_history", NOT __name__ -- setup_logging() only attaches
# handlers to the "ccsync" logger (proxy_gen.py:71's note).
log = logging.getLogger("ccsync.proxy_history")

LEDGER_FILENAME = "proxy_history.jsonl"
TOTALS_FILENAME = "proxy_totals.json"
REPORT_FILENAME = "proxy_history.txt"

# One rotation, at 2 MB. A record is ~250 bytes, so that is ~8000 clips of
# history live plus another 8000 in the `.1` -- comfortably more than the
# biggest run this fleet has ever done, and still a file Notepad opens.
MAX_LEDGER_BYTES = 2_000_000

# How many local days the rollup keeps. Long enough to answer "how much did
# we get through last month", short enough that the file stays a few KB.
MAX_DAYS = 90

# Completion timestamps kept for the rate estimate. 60 is ~15 minutes of a
# fast NVENC drain and several hours of a slow CPU one -- long enough to
# average out one 20-minute clip, short enough to react when the drain
# demotes to a single worker because Resolve opened.
RATE_WINDOW = 60

# A rate computed from a window that short is noise; and a span of zero
# would be a division by zero on a machine whose clock has no resolution.
MIN_RATE_SAMPLES = 3

RESULT_DONE = "done"
RESULT_FAILED = "failed"

# The rollup's numeric fields. One list, used to build a zeroed bucket, to
# add an event into it and to merge buckets -- so a field added here is
# added everywhere at once.
_COUNTERS = ("done", "failed", "src_bytes", "proxy_bytes", "encode_s", "media_s")

_TOTALS_VERSION = 1


def _empty_bucket() -> dict[str, Any]:
    return {key: 0 for key in _COUNTERS}


def _iso(when: float) -> str:
    return datetime.fromtimestamp(when, timezone.utc).isoformat(timespec="seconds")


def human_bytes(value: Any) -> str:
    """"1.2 TB". Never raises -- it renders tray text and report lines."""
    try:
        size = float(value or 0)
    except (TypeError, ValueError):
        return "0 B"
    for unit in ("B", "KB", "MB", "GB", "TB"):
        if abs(size) < 1024.0 or unit == "TB":
            return f"{size:.0f} {unit}" if unit == "B" else f"{size:.1f} {unit}"
        size /= 1024.0
    return f"{size:.1f} TB"


def human_duration(seconds: Any) -> str:
    """"2h 40m" / "18m" / "45s". None-safe, for an ETA that may not exist."""
    try:
        total = float(seconds or 0)
    except (TypeError, ValueError):
        return "0s"
    if total < 0:
        total = 0.0
    if total < 60:
        return f"{total:.0f}s"
    minutes = int(total // 60)
    if minutes < 60:
        return f"{minutes}m"
    hours, minutes = divmod(minutes, 60)
    if hours < 24:
        return f"{hours}h {minutes:02d}m" if minutes else f"{hours}h"
    days, hours = divmod(hours, 24)
    return f"{days}d {hours}h" if hours else f"{days}d"


class ProxyHistory:
    """The ledger. record() from any worker thread, snapshot() from the tray.

    `state_dir` is the companion's state dir; both files are created lazily,
    so a machine that never encodes never grows them.
    """

    def __init__(
        self,
        state_dir: Any,
        *,
        wall_clock: Callable[[], float] = time.time,
        max_ledger_bytes: int = MAX_LEDGER_BYTES,
    ) -> None:
        self.dir = Path(state_dir)
        self.ledger_path = self.dir / LEDGER_FILENAME
        self.totals_path = self.dir / TOTALS_FILENAME
        self.report_path = self.dir / REPORT_FILENAME
        self._wall_clock = wall_clock
        self._max_bytes = int(max_ledger_bytes)

        # Guards every field below AND the two files: the drain runs up to 8
        # workers, and two of them finishing in the same millisecond would
        # otherwise interleave a line or lose a totals rewrite.
        self._lock = threading.Lock()
        self._lifetime = _empty_bucket()
        self._days: dict[str, dict[str, Any]] = {}
        self._first_at: str = ""
        self._last_at: str = ""
        # Wall-clock completion times, for the rate estimate. In memory only:
        # a rate carried across a restart would describe a machine that is no
        # longer encoding anything.
        self._recent: Any = collections.deque(maxlen=RATE_WINDOW)
        self._load()

    # -- persistence -------------------------------------------------------
    def _load(self) -> None:
        """Read the rollup, or start empty. Never raises: a totals file from
        a future version, or a half-written one, means the counts restart --
        which costs a number on a tray line, not an encode."""
        try:
            data = json.loads(self.totals_path.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            return
        if not isinstance(data, dict):
            return
        try:
            self._lifetime = self._coerce_bucket(data.get("lifetime"))
            days = data.get("days")
            if isinstance(days, dict):
                for key, bucket in list(days.items())[-MAX_DAYS:]:
                    self._days[str(key)] = self._coerce_bucket(bucket)
            self._first_at = str(data.get("first_at") or "")
            self._last_at = str(data.get("last_at") or "")
        except Exception:
            log.debug("proxy history: %s could not be read", self.totals_path,
                      exc_info=True)

    @staticmethod
    def _coerce_bucket(raw: Any) -> dict[str, Any]:
        """A bucket with every counter present and numeric, whatever was on
        disk. A hand-edited or older-version file must not make every later
        += raise."""
        bucket = _empty_bucket()
        if not isinstance(raw, dict):
            return bucket
        for key in _COUNTERS:
            try:
                value = raw.get(key) or 0
                bucket[key] = float(value) if key.endswith("_s") else int(value)
            except (TypeError, ValueError):
                bucket[key] = 0
        return bucket

    def _save_totals_locked(self) -> None:
        # Trimmed in MEMORY as well as on disk, so a long-running companion
        # and the file it just wrote never disagree about which days exist:
        # `lifetime` is the number that is meant to keep growing.
        if len(self._days) > MAX_DAYS:
            self._days = {key: self._days[key] for key in sorted(self._days)[-MAX_DAYS:]}
        payload = {
            "version": _TOTALS_VERSION,
            "first_at": self._first_at,
            "last_at": self._last_at,
            "lifetime": self._lifetime,
            # Oldest first, capped: a rig that has been running for a year
            # keeps a quarter of it rather than an unbounded dict.
            "days": {key: self._days[key] for key in sorted(self._days)[-MAX_DAYS:]},
        }
        try:
            self.dir.mkdir(parents=True, exist_ok=True)
            # Same shape as _record_notify: a small file, written whole. No
            # tmp+replace, because the only reader is _load() and it already
            # treats a malformed file as "start from zero".
            self.totals_path.write_text(json.dumps(payload, indent=1), encoding="utf-8")
        except OSError as exc:
            log.debug("proxy history: could not write %s: %s", self.totals_path, exc)

    def _rotate_locked(self) -> None:
        """Roll the ledger at MAX_LEDGER_BYTES, keeping one generation."""
        try:
            if self.ledger_path.stat().st_size < self._max_bytes:
                return
        except OSError:
            return
        backup = self.ledger_path.with_suffix(self.ledger_path.suffix + ".1")
        try:
            os.replace(self.ledger_path, backup)
        except OSError as exc:
            # Rotation failing means the file keeps growing, which is a
            # nuisance and not a fault -- the encode it belongs to is done.
            log.debug("proxy history: could not rotate the ledger: %s", exc)

    # -- writing -----------------------------------------------------------
    def record(
        self,
        result: str,
        path: Any,
        *,
        project: str = "",
        kind: str = "",
        encoder: str = "",
        src_bytes: Any = 0,
        proxy_bytes: Any = 0,
        duration_s: Any = 0.0,
        encode_s: Any = 0.0,
        error: str = "",
    ) -> None:
        """Append one finished clip. Never raises.

        `result` is RESULT_DONE or RESULT_FAILED -- skipped and interrupted
        clips are deliberately NOT recorded: both mean "no work happened",
        both are routine (lane B delivered the proxy first; the editor came
        back), and a ledger full of them would bury the ones that matter.
        """
        try:
            self._record(result, path, project, kind, encoder, src_bytes,
                         proxy_bytes, duration_s, encode_s, error)
        except Exception:
            log.debug("proxy history: could not record %r", path, exc_info=True)

    def _record(self, result, path, project, kind, encoder, src_bytes,
                proxy_bytes, duration_s, encode_s, error) -> None:
        now = float(self._wall_clock())
        stamp = _iso(now)
        entry = {
            "at": stamp,
            "result": str(result or ""),
            "project": str(project or ""),
            "name": os.path.basename(str(path or "")),
            "path": str(path or ""),
            "kind": str(kind or ""),
            "encoder": str(encoder or ""),
            "src_bytes": int(src_bytes or 0),
            "proxy_bytes": int(proxy_bytes or 0),
            "duration_s": round(float(duration_s or 0.0), 2),
            "encode_s": round(float(encode_s or 0.0), 2),
        }
        if error:
            # Bounded: a failure reason is up to 500 characters of ffmpeg
            # stderr already, and the ledger is meant to stay readable.
            entry["error"] = str(error)[:300]

        day = time.strftime("%Y-%m-%d", time.localtime(now))
        with self._lock:
            bucket = self._days.setdefault(day, _empty_bucket())
            for target in (self._lifetime, bucket):
                if entry["result"] == RESULT_DONE:
                    target["done"] += 1
                    target["src_bytes"] += entry["src_bytes"]
                    target["proxy_bytes"] += entry["proxy_bytes"]
                    target["media_s"] += entry["duration_s"]
                else:
                    target["failed"] += 1
                target["encode_s"] += entry["encode_s"]
            if not self._first_at:
                self._first_at = stamp
            self._last_at = stamp
            if entry["result"] == RESULT_DONE:
                self._recent.append(now)
            self._append_locked(entry)
            self._save_totals_locked()

    def _append_locked(self, entry: dict[str, Any]) -> None:
        try:
            self.dir.mkdir(parents=True, exist_ok=True)
            self._rotate_locked()
            with open(self.ledger_path, "a", encoding="utf-8") as handle:
                # No indent and ensure_ascii off: one line per record is what
                # makes the file greppable, and the tree is full of CJK
                # filenames that \uXXXX escaping would make unreadable.
                handle.write(json.dumps(entry, ensure_ascii=False) + "\n")
        except OSError as exc:
            log.debug("proxy history: could not append to the ledger: %s", exc)

    # -- reading (no I/O) --------------------------------------------------
    def rate_per_hour(self) -> Optional[float]:
        """Clips finished per hour over the recent window, or None.

        Measured from COMPLETION TIMES rather than from summed encode
        seconds, which is what makes it correct while the drain is parallel:
        four workers finishing a clip each per minute is 240/h, and the
        per-clip encode_s would say 60/h.
        """
        with self._lock:
            samples = list(self._recent)
        if len(samples) < MIN_RATE_SAMPLES:
            return None
        span = samples[-1] - samples[0]
        if span <= 0:
            return None
        # n-1 intervals between n samples.
        return (len(samples) - 1) / span * 3600.0

    def eta_seconds(self, remaining: Any) -> Optional[float]:
        """How long `remaining` clips would take at the recent rate."""
        try:
            left = int(remaining or 0)
        except (TypeError, ValueError):
            return None
        if left <= 0:
            return None
        rate = self.rate_per_hour()
        if not rate:
            return None
        return left / rate * 3600.0

    def today_key(self) -> str:
        return time.strftime("%Y-%m-%d", time.localtime(float(self._wall_clock())))

    def snapshot(self, remaining: Any = 0) -> dict[str, Any]:
        """The block gap()/coverage() embed. Cached, lock-guarded, NO I/O.

        Scalars only -- this crosses into the dashboard report payload, and
        the reporter's size guard should never have to think about it.
        """
        try:
            day = self.today_key()
            with self._lock:
                today = dict(self._days.get(day) or _empty_bucket())
                lifetime = dict(self._lifetime)
                first_at, last_at = self._first_at, self._last_at
            rate = self.rate_per_hour()
            return {
                "today": today,
                "lifetime": lifetime,
                "day": day,
                "first_at": first_at,
                "last_at": last_at,
                "rate_per_hour": round(rate, 1) if rate else None,
                "eta_seconds": self.eta_seconds(remaining),
            }
        except Exception:
            log.debug("proxy history: snapshot failed", exc_info=True)
            return {"today": _empty_bucket(), "lifetime": _empty_bucket(),
                    "day": "", "first_at": "", "last_at": "",
                    "rate_per_hour": None, "eta_seconds": None}

    # -- reading (the ledger itself) ---------------------------------------
    def recent(self, limit: int = 50) -> list[dict[str, Any]]:
        """The last `limit` records, newest first. Reads the file -- callers
        are report() and anything driving this by hand, never gap()."""
        rows: list[dict[str, Any]] = []
        try:
            count = max(0, int(limit))
        except (TypeError, ValueError):
            count = 50
        if not count:
            return rows
        for source in (self.ledger_path,
                       self.ledger_path.with_suffix(self.ledger_path.suffix + ".1")):
            try:
                with open(source, "r", encoding="utf-8") as handle:
                    lines = handle.readlines()
            except OSError:
                continue
            for line in reversed(lines):
                line = line.strip()
                if not line:
                    continue
                try:
                    entry = json.loads(line)
                except ValueError:
                    continue  # a torn last line from a kill mid-write
                if isinstance(entry, dict):
                    rows.append(entry)
                if len(rows) >= count:
                    return rows
        return rows

    def report(self, limit: int = 60) -> str:
        """A human-readable summary of the ledger. Plain text on purpose:
        its consumer is an editor double-clicking a tray item, and the file
        it renders is JSON."""
        try:
            return self._report(limit)
        except Exception:
            log.exception("proxy history: could not render the report")
            return "The proxy history could not be read."

    def _report(self, limit: int) -> str:
        snap = self.snapshot()
        today, lifetime = snap["today"], snap["lifetime"]
        lines = [
            "CCSync — proxies made on this machine",
            "=" * 46,
            "",
            f"Ledger:  {self.ledger_path}",
        ]
        if snap["first_at"]:
            lines.append(f"Since:   {snap['first_at']}   (last: {snap['last_at']})")
        lines += ["", f"TODAY ({snap['day']})", self._bucket_lines(today), "",
                  "ALL TIME", self._bucket_lines(lifetime), ""]
        rate = snap["rate_per_hour"]
        if rate:
            lines += [f"Recent rate: {rate:.0f} clips/hour", ""]

        days = self._days_desc()
        if days:
            lines += ["BY DAY", "-" * 46]
            for key, bucket in days[:14]:
                failed = int(bucket.get("failed") or 0)
                saved = self._saved_ratio(bucket)
                line = f"  {key}   {int(bucket.get('done') or 0):5d} made"
                if failed:
                    line += f", {failed} failed"
                line += (
                    f"   {human_bytes(bucket.get('src_bytes'))} → "
                    f"{human_bytes(bucket.get('proxy_bytes'))}"
                )
                if saved:
                    line += f"  ({saved})"
                lines.append(line)
            lines.append("")

        rows = self.recent(limit)
        if rows:
            lines += [f"LAST {len(rows)} CLIPS (newest first)", "-" * 46]
            for entry in rows:
                mark = "ok  " if entry.get("result") == RESULT_DONE else "FAIL"
                stamp = str(entry.get("at") or "")[:19].replace("T", " ")
                lines.append(
                    f"  {mark} {stamp}  {entry.get('name') or ''}"
                    f"  [{entry.get('project') or '?'}]"
                )
                if entry.get("result") == RESULT_DONE:
                    lines.append(
                        f"        {human_bytes(entry.get('src_bytes'))} → "
                        f"{human_bytes(entry.get('proxy_bytes'))}"
                        f"   {entry.get('encoder') or '?'}"
                        f"   {human_duration(entry.get('encode_s'))} to encode"
                    )
                elif entry.get("error"):
                    lines.append(f"        {entry['error']}")
        else:
            lines.append("Nothing has been encoded on this machine yet.")
        return "\n".join(lines) + "\n"

    def _days_desc(self) -> list[tuple[str, dict[str, Any]]]:
        with self._lock:
            return sorted(self._days.items(), reverse=True)

    @staticmethod
    def _saved_ratio(bucket: dict[str, Any]) -> str:
        src = float(bucket.get("src_bytes") or 0)
        proxy = float(bucket.get("proxy_bytes") or 0)
        if src <= 0 or proxy <= 0:
            return ""
        return f"{src / proxy:.0f}× smaller"

    def _bucket_lines(self, bucket: dict[str, Any]) -> str:
        done, failed = int(bucket.get("done") or 0), int(bucket.get("failed") or 0)
        parts = [f"  {done} proxy made" if done == 1 else f"  {done} proxies made"]
        if failed:
            parts.append(f"{failed} failed")
        text = ", ".join(parts)
        if done:
            saved = self._saved_ratio(bucket)
            text += (
                f"\n  {human_bytes(bucket.get('src_bytes'))} of footage → "
                f"{human_bytes(bucket.get('proxy_bytes'))} of proxies"
                + (f"  ({saved})" if saved else "")
            )
            text += (
                f"\n  {human_duration(bucket.get('media_s'))} of footage covered, "
                f"{human_duration(bucket.get('encode_s'))} spent encoding"
            )
        return text

    def write_report(self, limit: int = 60) -> Optional[str]:
        """Render the report next to the ledger and return its path.

        A FILE rather than a dialog: it is long, it is worth keeping, and the
        tray's other "show me" actions (Open log) all hand the editor
        something their own editor opens. None if it could not be written.
        """
        try:
            self.dir.mkdir(parents=True, exist_ok=True)
            self.report_path.write_text(self.report(limit), encoding="utf-8")
            return str(self.report_path)
        except OSError:
            log.exception("proxy history: could not write %s", self.report_path)
            return None
