"""Lane B's circuit breaker, `.ccsync-trash` retention, and the sync halt.

COMMERCIAL_READINESS.md item 9 (2026-08-17). Three separate safety devices
that all had to live somewhere outside `rclone_lane.py`'s 3,400 lines, and
that share one property: they are STATE THAT MUST SURVIVE A RESTART. A
breaker that forgets it tripped when the tray is upgraded is not a breaker,
and a halt an editor can clear by quitting CCSync is not a halt.

Why a breaker at all, when lane B already carries `--max-delete 100` /
`--max-delete-size 20G`: that pair is a PER-PASS CAP, not a stop. A wrong
`remote_root`, a NAS that lists empty while its pool is still importing, or a
project unshared behind the companion's back all present to `rclone sync` as
"the source no longer has these files" -- and the cap then walks the editor's
whole local proxy set into `.ccsync-trash` at 20 GB per pass, one pass at a
time, forever. The cap bounds ONE pass; nothing bounded the sequence. See
`LaneBBreaker`.

The trash prune reverses a decision that was correct when it was made and is
no longer: `_backup_dir`'s original comment says "nothing ever prunes it --
deleting the recovery copy would defeat its whole purpose". That held while
the trash was the ONLY thing standing between a mis-sync and permanent loss.
With the breaker in front of it the trash is a 14-day undo window rather than
an archive, and an unbounded one filled editor SSDs (the 2026-07-26 ‛-name
transition alone moved ~30 GB into it). Age first, size cap second, both
configurable, every deletion logged -- and the breaker is deliberately the
gate: `prune_trash` refuses to run while lane B is tripped, because that is
exactly the window in which someone is about to need what is in there.
"""

from __future__ import annotations

import json
import logging
import os
import shutil
import threading
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable, Iterable, Optional

log = logging.getLogger("ccsync.sync.guard")

# -- lane B circuit breaker ------------------------------------------------
#
# Deliberately WELL under rclone's own `--max-delete 100`: the cap is the
# blast radius of the pass that trips this, so the breaker has to fire on
# something the cap would still have allowed. 50 deletions in one pass is
# already far outside normal -- a healthy pass trashes the handful of proxies
# a re-render superseded.
DEFAULT_MAX_DELETES_PER_PASS = 50
# ...or this fraction of the proxies actually present locally under the scope
# being synced, whichever is SMALLER. The absolute number is what catches a
# large project; the fraction is what catches a small one, where deleting 40
# of 45 proxies is a catastrophe that never reaches 50.
DEFAULT_MAX_DELETE_FRACTION = 0.25
# Below this many local proxies the fraction is not applied at all: on a
# project holding 3 proxies, "25%" is 0 and every ordinary cleanup trips.
DEFAULT_MIN_LOCAL_SAMPLE = 20
# The NAS listing shrank to less than this share of what we last saw at the
# same scope -> the remote is not in a state anyone should sync FROM.
DEFAULT_REMOTE_SHRINK_FRACTION = 0.5
# ...but only once we have seen enough to have an opinion. A scope we have
# only ever seen 2 entries at tells us nothing about "half of it vanished".
DEFAULT_MIN_REMOTE_SAMPLE = 4
# Top-level names that must exist under `remote_root` before lane B is
# allowed to sync the whole tree. This is the `remote_root` typo check: a
# root that answers but holds no `Projects/` is somebody's home directory,
# not the tree, and syncing from it deletes everything.
DEFAULT_REMOTE_MARKER_DIRS = ("Projects",)

# -- .ccsync-trash retention ----------------------------------------------
DEFAULT_TRASH_MAX_AGE_DAYS = 14
DEFAULT_TRASH_MAX_BYTES = 50 * 1024**3
# How often the companion is allowed to spend a trash walk. The prune is
# cheap (a stat walk plus the odd rmtree) but it is not free, and nothing
# about a 14-day window needs hourly precision.
DEFAULT_TRASH_PRUNE_INTERVAL_SECONDS = 6 * 3600.0

TRASH_DIR_NAME = ".ccsync-trash"

# -- lane B's free-space floor (SYS-5 / SYNC-7, resilience sweep 2026-08-28) --
#
# Every other subsystem that writes bytes already has one of these
# (proxy_gen_free_space_floor_gb, broll_ingest_free_space_floor_gb,
# broll_server._free_bytes_at); the three lanes that move the actual footage
# had none. Below the floor rclone fails per file with an ENOSPC line, the
# lane goes red with a raw rclone string, and `.ccsync-trash` -- up to
# DEFAULT_TRASH_MAX_BYTES of recovery copies on the SAME volume -- is never
# reclaimed, because the prune only ran at the tail of a HEALTHY pass.
#
# 20 GB, not a percentage: the number that matters is "can the next few
# proxies land", and on a 1 TB laptop SSD 2% is 20 GB while on a 20 TB base
# rig it is 400. A percentage would park a machine that has room and let a
# small one fill.
DEFAULT_LANE_B_MIN_FREE_BYTES = 20 * 1024**3
# The park clears ITSELF at twice the floor. One threshold would re-park on
# the next pass after the editor deleted a single clip, so the sentence would
# flicker on and off for an afternoon; the same hysteresis the breaker gets
# from needing a human.
DISK_FLOOR_CLEAR_MULTIPLE = 2.0

BREAKER_STATE_FILENAME = "lane_b_breaker.json"
HALT_STATE_FILENAME = "sync_halt.json"
DISK_FLOOR_STATE_FILENAME = "lane_b_disk_floor.json"


def adopt_legacy_latch(new_path: Path, legacy_path: Path) -> Path:
    """Carry a latch file forward from its pre-2026-08-28 location, once.
    Returns `new_path` either way; never raises.

    APP-3 (resilience sweep 2026-08-28). Both latches used to live under
    `<log dir>/state/` -- the ONE directory this codebase's own comments say
    a support session is most likely to be told to delete ("close CCSync,
    delete ~/.ccsync/state, start it again"). So the two devices that were
    made persistent precisely so a restart could not clear them (the
    breaker only a human may reset, and a FLEET halt an admin set) were
    sitting where a restart-adjacent ritual clears them. They now live in
    config_mod.CONFIG_DIR beside machine.json and upgrade_floor.json, for
    the same reason upgrade.py moved the downgrade floor there.

    Without this adoption the move itself would CLEAR a live latch on every
    machine that had one -- the one direction a latch must never fail --
    so the old file is moved, not read: an upgrade must not leave a stale
    copy that a downgrade would then latch on again."""
    try:
        new_path = Path(new_path)
        legacy_path = Path(legacy_path)
        if new_path == legacy_path or new_path.exists() or not legacy_path.exists():
            return new_path
        new_path.parent.mkdir(parents=True, exist_ok=True)
        try:
            os.replace(legacy_path, new_path)
        except OSError:
            # A `log_path` on a second drive puts the legacy file on another
            # volume, where replace() cannot rename across the boundary.
            shutil.move(str(legacy_path), str(new_path))
        log.warning(
            "moved the sync latch %s out of %s and into %s -- state/ is the "
            "directory support sessions are told to delete (APP-3)",
            new_path.name, legacy_path.parent, new_path.parent,
        )
    except Exception:
        log.debug("could not adopt the legacy latch %s", new_path, exc_info=True)
    return Path(new_path)

HALT_SCOPE_LOCAL = "local"
HALT_SCOPE_FLEET = "fleet"


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _cfg_float(cfg: Optional[dict], key: str, default: float) -> float:
    try:
        value = float((cfg or {}).get(key, default))
    except (TypeError, ValueError):
        log.warning("%s=%r is not a number -- using %s", key, (cfg or {}).get(key), default)
        return default
    return value


def _cfg_int(cfg: Optional[dict], key: str, default: int) -> int:
    return int(_cfg_float(cfg, key, float(default)))


def _read_json(path: Path) -> dict:
    """Load a small JSON state file, or {} when it is absent/unreadable.

    Never raises: every caller here is on a path where a corrupt state file
    must degrade to "no remembered state", not to a dead lane."""
    try:
        data = json.loads(Path(path).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}
    return data if isinstance(data, dict) else {}


def _write_json(path: Path, data: dict) -> bool:
    """Persist a small state file ATOMICALLY. Returns False (and logs) on
    failure.

    tmp + os.replace (sync-safety-8, 2026-08-21). This used to write in
    place, arguing that a torn write degrades to `_read_json` returning {}
    and that the trip is "re-derived from the next pass's evidence anyway".
    That argument does not hold for trigger 1: the same file carries
    `remote_counts`, the ONLY memory of how big the NAS listing was last
    time, and losing it means the empty/shrink probes have nothing to
    compare against and cannot fire at all until a pass re-seeds them.
    Losing a live `sync_halt.json` mid-write releases a fleet halt on one
    machine. Both are the direction a latch must never fail, and
    os.replace is atomic on NTFS and APFS, so there is no reason to accept
    either."""
    target = Path(path)
    tmp = target.with_name(target.name + ".tmp")
    try:
        target.parent.mkdir(parents=True, exist_ok=True)
        tmp.write_text(json.dumps(data, indent=1), encoding="utf-8")
        os.replace(tmp, target)
        return True
    except OSError as exc:
        log.warning("could not persist %s: %s", path, exc)
        try:
            tmp.unlink()
        except OSError:
            pass
        return False


# -- how much of the local proxy set is at stake ---------------------------
def count_local_proxies(
    local_root: str, subpath: Optional[str] = None, max_entries: int = 200000
) -> int:
    """Files under any `Proxy/` directory in the scope lane B is about to sync.

    The denominator of the breaker's fraction rule -- i.e. exactly the set
    `rclone sync` is authorised to delete, and nothing else. Bounded, and
    returns 0 rather than raising on an unreadable tree (the absolute
    per-pass cap still applies when this is 0)."""
    base = Path(local_root)
    sub = (subpath or "").strip("/\\")
    if sub:
        base = base / Path(*sub.split("/"))
    if not base.is_dir():
        return 0
    count = 0
    try:
        for dirpath, dirnames, filenames in os.walk(base):
            # Never walk into the recovery copies: they are full of proxies
            # by construction, so counting them would inflate the
            # denominator by exactly the files already deleted.
            dirnames[:] = [d for d in dirnames if d != TRASH_DIR_NAME]
            parts = {p.lower() for p in Path(dirpath).parts}
            if "proxy" not in parts:
                continue
            count += len(filenames)
            if count >= max_entries:
                return max_entries
    except OSError as exc:
        log.debug("proxy count failed under %s: %s", base, exc)
        return count
    return count


class LaneBBreaker:
    """Trips lane B off and keeps it off until an operator says otherwise.

    Three independent triggers, in the order they can fire:

      1. `check_remote()` -- BEFORE the run. The NAS listing failed, came
         back empty where it was not empty before, shrank past
         `remote_shrink_fraction`, or `remote_root` holds none of the marker
         directories. This is the only trigger that fires before a single
         byte moves, and it is the one that catches the two failures the
         audit named: a wrong `remote_root` and an empty listing.
      2. `note_pass()` -- AFTER a run, on that pass's deletions. rclone's
         `--max-delete` cap has already bounded this pass; the breaker
         stops the NEXT one.
      3. `note_pass()` again, on the cumulative deletions since the counters
         were last cleared -- a slow bleed of 20 proxies a pass never trips
         (2) and is still a mis-sync.

    Everything is kept in one small JSON file so a tripped breaker survives
    the tray restart an editor will absolutely try first.
    """

    def __init__(
        self,
        state_path: Path,
        cfg: Optional[dict] = None,
        on_trip: Optional[Callable[[str], None]] = None,
    ) -> None:
        self.state_path = Path(state_path)
        self.max_deletes_per_pass = _cfg_int(
            cfg, "lane_b_max_deletes_per_pass", DEFAULT_MAX_DELETES_PER_PASS)
        self.max_delete_fraction = _cfg_float(
            cfg, "lane_b_max_delete_fraction", DEFAULT_MAX_DELETE_FRACTION)
        self.min_local_sample = _cfg_int(
            cfg, "lane_b_min_local_sample", DEFAULT_MIN_LOCAL_SAMPLE)
        self.remote_shrink_fraction = _cfg_float(
            cfg, "lane_b_remote_shrink_fraction", DEFAULT_REMOTE_SHRINK_FRACTION)
        self.min_remote_sample = _cfg_int(
            cfg, "lane_b_min_remote_sample", DEFAULT_MIN_REMOTE_SAMPLE)
        markers = (cfg or {}).get("lane_b_remote_marker_dirs", DEFAULT_REMOTE_MARKER_DIRS)
        if isinstance(markers, str):
            markers = [markers]
        self.marker_dirs = [str(m).strip().strip("/") for m in (markers or []) if str(m).strip()]
        # Cumulative deletions allowed before the breaker trips on the slow
        # bleed. 4x the per-pass cap: enough passes of legitimate cleanup to
        # never fire on the ‛-name-transition class of event, few enough that
        # a wrong remote cannot quietly empty a project over an afternoon.
        self.max_deletes_cumulative = _cfg_int(
            cfg, "lane_b_max_deletes_cumulative", self.max_deletes_per_pass * 4)
        self._on_trip = on_trip
        self._lock = threading.Lock()
        state = _read_json(self.state_path)
        self._tripped = bool(state.get("tripped"))
        self._reason = str(state.get("reason") or "")
        self._tripped_at = str(state.get("tripped_at") or "")
        self._deletes = int(state.get("deletes") or 0)
        self._bytes = int(state.get("bytes") or 0)
        self._last_pass_deletes = int(state.get("last_pass_deletes") or 0)
        self._resumed_at = str(state.get("resumed_at") or "")
        # The dashboard's [ RESUME ] is a STANDING request: it rides every
        # report reply until the admin clears it, so the companion has to
        # remember which one it already honoured or it would re-resume the
        # breaker on every report (CR-45's delivery channel, comp-lanes-ab-2,
        # 2026-08-21). Persisted with the latch, because a tray restart is
        # exactly when the standing request is re-read.
        self._applied_resume_request = str(state.get("applied_resume_request") or "")
        remote = state.get("remote_counts")
        self._remote_counts: dict[str, int] = (
            {str(k): int(v) for k, v in remote.items()} if isinstance(remote, dict) else {}
        )

    # -- state ---------------------------------------------------------
    @property
    def tripped(self) -> bool:
        with self._lock:
            return self._tripped

    @property
    def reason(self) -> str:
        with self._lock:
            return self._reason

    def report(self) -> dict[str, Any]:
        """The `sync_guard.lane_b_breaker` block of the report payload, and
        the tray's source for the same sentence. Cheap; never raises."""
        with self._lock:
            return {
                "tripped": self._tripped,
                "reason": self._reason or None,
                "tripped_at": self._tripped_at or None,
                "deletes": self._deletes,
                "bytes": self._bytes,
                "last_pass_deletes": self._last_pass_deletes,
                "resumed_at": self._resumed_at or None,
            }

    def _persist_locked(self) -> None:
        _write_json(self.state_path, {
            "tripped": self._tripped,
            "reason": self._reason,
            "tripped_at": self._tripped_at,
            "deletes": self._deletes,
            "bytes": self._bytes,
            "last_pass_deletes": self._last_pass_deletes,
            "resumed_at": self._resumed_at,
            "applied_resume_request": self._applied_resume_request,
            # Bounded: one int per project scope this machine syncs, and the
            # sequencer's scope set is the editor's selection.
            "remote_counts": dict(list(self._remote_counts.items())[:512]),
        })

    def trip(self, reason: str) -> bool:
        """Latch the breaker off. Idempotent; returns True on the EDGE only,
        so callers can fire exactly one toast per trip."""
        with self._lock:
            if self._tripped:
                return False
            self._tripped = True
            self._reason = str(reason)
            self._tripped_at = _now_iso()
            self._persist_locked()
        log.error(
            "lane B CIRCUIT BREAKER TRIPPED: %s -- proxy download is stopped on this "
            "machine until someone resumes it from the tray. Uploads (lane A) and the "
            "assets lane (C) keep running; nothing has been deleted beyond what is "
            "already in %s.", reason, TRASH_DIR_NAME,
        )
        if self._on_trip is not None:
            try:
                self._on_trip(str(reason))
            except Exception:
                log.exception("lane B breaker: on_trip callback failed")
        return True

    def resume(self, by: str = "tray", request_id: Optional[str] = None) -> bool:
        """Operator says the remote is fine. Clears the latch AND every
        counter the triggers compare against. Returns False when it was not
        tripped, or when `request_id` has already been applied.

        Clearing the counters is not tidiness: resuming without clearing them
        re-trips on the next pass and reads as "the button doesn't work".
        That was only half done. `_remote_counts` -- the remembered SIZE of
        each scope's NAS listing -- was left alone, so a trigger-1 trip
        ("shrank from 10 to 3", "listed EMPTY and it held 10") re-tripped
        against the identical listing the instant the lane ran again, with no
        way out but deleting this file while the companion was stopped
        (comp-lanes-ab-1, 2026-08-21). An operator who resumes has asserted
        that the server is in the state it should be synced from, so the next
        listing is the new baseline.

        `request_id` is the dashboard's standing resume request (its
        `requested_at`): the same request rides every report reply until an
        admin clears it, so applying it more than once would fight the
        breaker forever. Recorded (and persisted) BEFORE the latch clears, so
        a crash in between can only ever cost the request, never repeat it.
        """
        rid = str(request_id or "").strip()
        with self._lock:
            if rid and rid == self._applied_resume_request:
                return False
            if rid:
                self._applied_resume_request = rid
                self._persist_locked()
            if not self._tripped:
                return False
            reason, self._reason = self._reason, ""
            self._tripped = False
            self._tripped_at = ""
            self._deletes = 0
            self._bytes = 0
            self._last_pass_deletes = 0
            self._remote_counts.clear()
            self._resumed_at = _now_iso()
            self._persist_locked()
        log.warning("lane B breaker RESUMED by %s (was: %s)", by, reason)
        return True

    # -- trigger 1: the remote itself ----------------------------------
    def check_remote(self, scope: str, entries: Optional[Iterable[str]]) -> Optional[str]:
        """Sanity-probe the NAS listing for `scope` before a pass runs.

        `entries` is the top-level listing of the remote side (rclone lsf),
        or None when the listing FAILED. Returns the trip reason, or None
        when the remote looks like itself. Trips as a side effect.

        A failed listing is deliberately NOT a trip: rclone would fail the
        run too, and a flapping tailnet must not need an operator to clear
        it. It is the listing that SUCCEEDS and says "there is nothing here"
        that destroys a proxy set.
        """
        key = str(scope or "")
        if entries is None:
            log.info(
                "lane B: could not list the remote for %s -- skipping the sanity probe "
                "(a failed listing fails the run on its own)", key or "the whole tree")
            return None
        names = [str(e).strip().strip("/") for e in entries]
        names = [n for n in names if n]
        with self._lock:
            last = int(self._remote_counts.get(key, 0))
        if not key and self.marker_dirs:
            lowered = {n.lower() for n in names}
            if not any(m.lower() in lowered for m in self.marker_dirs):
                return self._trip_and_return(
                    f"the NAS root does not look like the tree: none of "
                    f"{', '.join(self.marker_dirs)} is under remote_root "
                    f"(saw {len(names)} entr{'y' if len(names) == 1 else 'ies'}). "
                    "Check remote_root in config.toml."
                )
        if not names:
            if last > 0:
                return self._trip_and_return(
                    f"the NAS listed {key or 'the whole tree'} as EMPTY, and it held "
                    f"{last} entries last time. Syncing from it would move every local "
                    "proxy here into the trash."
                )
            return None
        if (
            last >= self.min_remote_sample
            and len(names) < last * self.remote_shrink_fraction
        ):
            return self._trip_and_return(
                f"the NAS listing for {key or 'the whole tree'} shrank from {last} to "
                f"{len(names)} entries since the last pass -- that is not a normal "
                "change, so proxy download stopped before anything was deleted."
            )
        with self._lock:
            self._remote_counts[key] = len(names)
            self._persist_locked()
        return None

    def _trip_and_return(self, reason: str) -> str:
        self.trip(reason)
        return reason

    # -- triggers 2 and 3: what a pass actually did ---------------------
    def note_pass(
        self, scope: str, deleted: int, moved_bytes: int, local_proxies: int = 0,
        relocation_probe: Optional[Callable[[], int]] = None,
    ) -> Optional[str]:
        """Account one lane B pass. Returns the trip reason, or None.

        `local_proxies` is the proxy count under the same scope BEFORE the
        pass (see count_local_proxies); 0 disables the fraction rule and
        leaves the absolute caps.

        `relocation_probe` answers "how many of the files this pass trashed
        are still on the NAS, at a different path?" -- i.e. how many were a
        REORGANISATION rather than a deletion (2026-08-20, KNOWN_BUGS CR-44).
        It is called at most once per pass, and only when the pass would
        otherwise trip or when it trashed at least half the per-pass cap
        (see `eager` below), because it costs a recursive listing of the
        scope: on the ~99% of passes that are nowhere near a limit it must
        not be spent at all. A move is the common benign shape -- an editor drags a
        folder in Explorer and every proxy under it "disappears" from the
        server at once -- and it was tripping the breaker on exactly the
        event the breaker has nothing to say about."""
        deleted = max(0, int(deleted or 0))
        moved_bytes = max(0, int(moved_bytes or 0))
        with self._lock:
            self._last_pass_deletes = deleted
            self._deletes += deleted
            self._bytes += moved_bytes
            cumulative = self._deletes
            self._persist_locked()
        if deleted <= 0:
            return None
        limit = self.max_deletes_per_pass
        if local_proxies >= self.min_local_sample:
            limit = min(limit, max(1, int(local_proxies * self.max_delete_fraction)))
        would_trip = deleted > limit or cumulative > self.max_deletes_cumulative
        # ...and a pass that is NOT about to trip, but trashed enough files
        # to be a reorganisation rather than a cleanup, is probed too
        # (comp-lanes-ab-5, 2026-08-21). The probe stayed lazy to the point
        # of being useless for trigger 3: everything a sub-limit pass trashed
        # went onto the cumulative counter permanently, moves included, so a
        # week of 40-file Explorer drags filled it with files that are all
        # still on the NAS and the next handful of REAL deletions tripped
        # "a slow leak of 208 file(s)". Discount them as they happen. The
        # threshold is the ABSOLUTE per-pass cap's half, never the
        # fraction-narrowed `limit`: on a 12-proxy project that would spend a
        # recursive listing on a two-file cleanup.
        eager = deleted >= max(2, self.max_deletes_per_pass // 2)
        if not (would_trip or eager):
            return None
        # About to trip on one rule or the other -- NOW it is worth asking
        # whether what left the folder actually left the server.
        relocated = self._count_relocations(relocation_probe, deleted)
        if relocated:
            deleted, cumulative = self._discount_relocations(relocated)
        if deleted > limit:
            return self._trip_and_return(
                f"one proxy-download pass moved {deleted} file(s) out of "
                f"{scope or 'the tree'} into {TRASH_DIR_NAME} (the limit is {limit}"
                + (f" of {local_proxies} local proxies" if local_proxies else "")
                + (f"; a further {relocated} were moved to a new folder on the NAS "
                   "rather than deleted" if relocated else "")
                + "). Nothing was deleted -- they are all recoverable -- but proxy "
                  "download is stopped until someone checks the server."
            )
        if cumulative > self.max_deletes_cumulative:
            return self._trip_and_return(
                f"proxy download has moved {cumulative} file(s) into {TRASH_DIR_NAME} "
                f"since it was last checked (the limit is {self.max_deletes_cumulative}). "
                "That is a slow leak rather than one bad pass; it is stopped until "
                "someone checks the server."
            )
        return None

    def _count_relocations(
        self, probe: Optional[Callable[[], int]], deleted: int
    ) -> int:
        """Run the relocation probe, clamped and never raising.

        A probe that throws, or that answers nonsense, must leave the
        breaker exactly as strict as it was without one: this is the code
        path that decides NOT to stop a lane that is deleting files, so
        every failure here has to fall back to 0 (= "treat them all as
        deletions")."""
        if probe is None:
            return 0
        try:
            relocated = int(probe() or 0)
        except Exception:
            log.exception("lane B breaker: the relocation probe failed -- "
                          "treating every trashed file as a deletion")
            return 0
        if relocated <= 0:
            return 0
        # Clamp: the probe counts files it found on the remote, and a bug
        # there must not be able to talk the breaker out of a real trip by
        # claiming more relocations than the pass had deletions.
        return min(relocated, deleted)

    def _discount_relocations(self, relocated: int) -> tuple[int, int]:
        """Take `relocated` back off this pass's and the cumulative counters.

        The cumulative rule is the one that would otherwise punish a big
        reorganisation twice: once on the pass it happened, and again for
        every pass afterwards because the count never came back down."""
        with self._lock:
            self._last_pass_deletes = max(0, self._last_pass_deletes - relocated)
            self._deletes = max(0, self._deletes - relocated)
            deleted = self._last_pass_deletes
            cumulative = self._deletes
            self._persist_locked()
        log.info(
            "lane B: %d of this pass's trashed file(s) are still on the NAS under a "
            "different path -- a folder was reorganised, not emptied; not counting "
            "them against the breaker", relocated,
        )
        return deleted, cumulative


# -- free disk space (SYS-5 / SYNC-7, resilience sweep 2026-08-28) ---------
def system_drive_path() -> str:
    """The OS volume, for the second half of the disk report.

    Reported alongside the sync drive because they are frequently the same
    volume (a Windows editor whose tree is on C:, a Mac whose root is not on
    an external SSD) and because a full BOOT disk breaks Resolve, Syncthing
    and the companion's own log before it breaks a lane -- and the fleet grid
    could see neither."""
    if os.name == "nt":
        drive = os.environ.get("SystemDrive") or "C:"
        return drive.rstrip("\\/") + "\\"
    return "/"


def free_bytes_at(path: Any) -> Optional[int]:
    """Free bytes on the volume holding `path`, or None.

    None is "could not measure", and every caller must keep it distinct from
    zero: a machine whose disk_usage raises must never render as a machine
    with no space left (nor as a machine that is fine)."""
    try:
        return int(shutil.disk_usage(str(path)).free)
    except Exception:
        log.debug("could not measure free space at %s", path, exc_info=True)
        return None


def disk_report(
    local_root: Any,
    system_path: Optional[str] = None,
    usage_fn: Optional[Callable[[str], Any]] = None,
) -> dict[str, Any]:
    """The report's `sync_guard.disk` block. Never raises.

    One `shutil.disk_usage` per volume, called once per HEAVY report tick --
    not per lane pass. `root_free_bytes`/`root_total_bytes` are None when the
    sync drive could not be measured at all (it is unplugged, or wedged), and
    the dashboard has to render that as "unknown", never as 0 (the sweep's
    "could not check must never look like fine" rule)."""
    usage = usage_fn if usage_fn is not None else shutil.disk_usage
    out: dict[str, Any] = {
        "root_free_bytes": None,
        "root_total_bytes": None,
        "system_free_bytes": None,
        "at": _now_iso(),
    }
    try:
        info = usage(str(local_root))
        out["root_free_bytes"] = int(info.free)
        out["root_total_bytes"] = int(info.total)
    except Exception:
        log.debug("disk report: could not measure %s", local_root, exc_info=True)
    try:
        out["system_free_bytes"] = int(usage(str(system_path or system_drive_path())).free)
    except Exception:
        log.debug("disk report: could not measure the system drive", exc_info=True)
    return out


def _gb(value: Any) -> str:
    """Binary GB, because `lane_b_min_free_bytes` is written that way in
    config.toml and a floor an operator set to 20 must read back as 20."""
    try:
        return f"{float(value) / 1024**3:.0f}"
    except (TypeError, ValueError):
        return "?"


class DiskFloorLatch:
    """Lane B stands down when the sync drive is nearly full.

    Deliberately the BREAKER's shape and not an error (SYS-5 / SYNC-7,
    resilience sweep 2026-08-28): `paused`, so lanes A and C keep running and
    the fleet grid does not paint a red dot on a machine that is not broken;
    persisted, so the tray restart an editor tries first cannot clear it; and
    clearable by the same [ RESUME ] the breaker uses, because an editor who
    has just emptied their Downloads folder should not have to wait for a
    poll to find out whether it worked.

    Unlike the breaker it ALSO clears itself, at
    DISK_FLOOR_CLEAR_MULTIPLE x the floor. The breaker guards a judgement no
    machine can make ("is the server in a state worth syncing from"); this
    guards a number, and a number that has gone back up is the whole answer.
    """

    def __init__(
        self,
        state_path: Path,
        cfg: Optional[dict] = None,
        on_park: Optional[Callable[[str], None]] = None,
    ) -> None:
        self.state_path = Path(state_path)
        self.min_free_bytes = max(0, _cfg_int(
            cfg, "lane_b_min_free_bytes", DEFAULT_LANE_B_MIN_FREE_BYTES))
        self.clear_free_bytes = int(self.min_free_bytes * DISK_FLOOR_CLEAR_MULTIPLE)
        self._on_park = on_park
        self._lock = threading.Lock()
        state = _read_json(self.state_path)
        self._parked = bool(state.get("parked"))
        self._reason = str(state.get("reason") or "")
        self._at = str(state.get("at") or "")
        free = state.get("free_bytes")
        self._free_bytes: Optional[int] = int(free) if isinstance(free, (int, float)) else None

    @property
    def enabled(self) -> bool:
        """A floor of 0 turns the whole device off, like every other knob
        here."""
        return self.min_free_bytes > 0

    @property
    def parked(self) -> bool:
        with self._lock:
            return self._parked

    @property
    def reason(self) -> str:
        with self._lock:
            return self._reason

    def report(self) -> dict[str, Any]:
        with self._lock:
            return {
                "parked": self._parked,
                "reason": self._reason or None,
                "at": self._at or None,
                "free_bytes": self._free_bytes,
                "floor_bytes": self.min_free_bytes,
            }

    def _persist_locked(self) -> None:
        _write_json(self.state_path, {
            "parked": self._parked,
            "reason": self._reason,
            "at": self._at,
            "free_bytes": self._free_bytes,
        })

    def _sentence(self, free_bytes: int) -> str:
        return (f"this drive has {_gb(free_bytes)} GB free, and proxy download needs "
                f"{_gb(self.min_free_bytes)} GB")

    def check(self, free_bytes: Optional[int]) -> Optional[str]:
        """Account one measurement. Returns the park reason, or None.

        `free_bytes=None` is "could not measure" and changes NOTHING in
        either direction: it must not park a machine whose disk_usage raised,
        and it must not release one that is genuinely full. A park already in
        place keeps answering with its sentence."""
        if not self.enabled:
            return None
        if free_bytes is None:
            with self._lock:
                return self._reason or None if self._parked else None
        free = max(0, int(free_bytes))
        with self._lock:
            if self._parked:
                self._free_bytes = free
                if free >= self.clear_free_bytes:
                    reason, self._reason = self._reason, ""
                    self._parked = False
                    self._at = _now_iso()
                    self._persist_locked()
                    log.warning(
                        "lane B free-space park CLEARED: %s GB free is back above %s GB "
                        "(was: %s)", _gb(free), _gb(self.clear_free_bytes), reason)
                    return None
                self._persist_locked()
                return self._reason or None
            if free >= self.min_free_bytes:
                if self._free_bytes != free:
                    self._free_bytes = free
                return None
            self._parked = True
            self._reason = self._sentence(free)
            self._at = _now_iso()
            self._free_bytes = free
            reason = self._reason
            self._persist_locked()
        log.error(
            "lane B is NOT downloading proxies: %s. Uploads (lane A) and the assets "
            "lane (C) keep running. It starts again on its own once %s GB is free, or "
            "when someone resumes it from the tray.", reason, _gb(self.clear_free_bytes))
        if self._on_park is not None:
            try:
                self._on_park(reason)
            except Exception:
                log.exception("lane B disk floor: on_park callback failed")
        return reason

    def resume(self, by: str = "tray") -> bool:
        """The editor (or an admin) says to try anyway. Returns True on the
        edge only.

        Honest about what it can and cannot do: if the drive is still under
        the floor the next pass parks it again with the same sentence. That
        is not the breaker's "the button doesn't work" defect -- there are no
        counters here to clear, and the number is checked against the disk,
        not against a memory of it. What the click buys is the pass that
        proves it, immediately, instead of at the next rotation."""
        with self._lock:
            if not self._parked:
                return False
            reason, self._reason = self._reason, ""
            self._parked = False
            self._at = _now_iso()
            self._persist_locked()
        log.warning("lane B free-space park RESUMED by %s (was: %s)", by, reason)
        return True


# -- .ccsync-trash retention ----------------------------------------------
def batch_stamp(name: Any) -> Optional[float]:
    """The epoch seconds encoded in a `%Y%m%d-%H%M%S` batch directory name.

    SYNC-16 (resilience sweep 2026-08-28). `trash_entries` yielded 0.0 for a
    batch whose every stat failed, which made it the OLDEST thing in the
    trash -- so the size rule deleted a batch created seconds ago before one
    created a fortnight back. The directory name is `_backup_dir`'s own
    record of when the batch was made and it needs no filesystem at all.

    Naive-local on purpose: `_backup_dir` names the directory from the local
    clock, and this has to be comparable with st_mtime, which is also local
    wall-clock derived. Returns None for anything that is not that format."""
    try:
        return datetime.strptime(str(name).strip(), "%Y%m%d-%H%M%S").timestamp()
    except (TypeError, ValueError):
        return None


def trash_entries(local_root: str) -> list[tuple[Path, float, int]]:
    """(dir, mtime, bytes) for each timestamped batch under `.ccsync-trash`.

    `_backup_dir` makes one directory per RUN, named `%Y%m%d-%H%M%S`, so a
    batch is the unit of both retention and recovery -- pruning individual
    files inside one would leave a half-recoverable run, which is worse than
    either keeping or dropping it whole."""
    base = Path(local_root) / TRASH_DIR_NAME
    out: list[tuple[Path, float, int]] = []
    if not base.is_dir():
        return out
    try:
        children = sorted(base.iterdir())
    except OSError as exc:
        log.debug("trash listing failed for %s: %s", base, exc)
        return out
    for child in children:
        if not child.is_dir():
            continue
        total = 0
        newest = 0.0
        try:
            newest = child.stat().st_mtime
        except OSError:
            pass
        try:
            for dirpath, _dirnames, filenames in os.walk(child):
                for name in filenames:
                    try:
                        st = os.stat(os.path.join(dirpath, name))
                    except OSError:
                        continue
                    total += st.st_size
                    newest = max(newest, st.st_mtime)
        except OSError:
            pass
        if not newest:
            # Every stat in this batch failed (an unreadable directory, a
            # volume that answers listdir and nothing else) -- or the batch is
            # empty and its own mtime is the epoch. Either way 0.0 would make
            # it the oldest thing here and the size rule would delete it
            # FIRST, which for a batch made minutes ago is exactly backwards
            # (SYNC-16, resilience sweep 2026-08-28).
            newest = batch_stamp(child.name) or 0.0
        out.append((child, newest, total))
    return out


def prune_trash(
    local_root: str,
    max_age_days: float = DEFAULT_TRASH_MAX_AGE_DAYS,
    max_bytes: int = DEFAULT_TRASH_MAX_BYTES,
    now: Optional[float] = None,
    breaker: Optional[LaneBBreaker] = None,
    min_free_bytes: int = 0,
    free_bytes_fn: Optional[Callable[[Any], Optional[int]]] = None,
) -> dict[str, Any]:
    """Age-then-size retention over `<local_root>/.ccsync-trash`.

    Policy, and it is a deliberate reversal of `_backup_dir`'s original
    "nothing ever prunes it" (COMMERCIAL_READINESS.md item 9, 2026-08-17):

      * a batch older than `max_age_days` goes;
      * if what remains is still over `max_bytes`, the OLDEST batches go
        until it is not -- the newest batch is never pruned by the size
        rule, however big it is, because that is the one an editor is most
        likely to be about to ask for;
      * nothing is pruned at all while the breaker is tripped: a trip means
        something deleted more than it should have, i.e. precisely when the
        recovery copies matter.

    `min_free_bytes` is the third trigger (SYNC-16 / SYNC-7, resilience sweep
    2026-08-28): DISK PRESSURE prunes even when neither age nor the size cap
    has anything to say. The 50 GB the trash is allowed to hold is 50 GB the
    editor cannot use, and disk-full is precisely the state in which a
    fortnight-old recovery copy is worth less than the ability to download a
    proxy. Oldest first, never the last batch standing -- the same two rules
    the size cap follows.

    Every removal is logged with its size. Returns a summary dict; never
    raises.
    """
    if breaker is not None and breaker.tripped:
        log.info("trash prune skipped: the lane B breaker is tripped, keeping every copy")
        return {"skipped": "breaker tripped", "removed": 0, "removed_bytes": 0}
    now = time.time() if now is None else now
    entries = trash_entries(local_root)
    removed = 0
    removed_bytes = 0
    cutoff = now - max(0.0, float(max_age_days)) * 86400.0
    keep: list[tuple[Path, float, int]] = []
    for path, mtime, size in entries:
        if max_age_days > 0 and mtime and mtime < cutoff:
            if _remove_tree(path, size, f"older than {max_age_days:g} days"):
                removed += 1
                removed_bytes += size
            continue
        keep.append((path, mtime, size))
    total = sum(size for _p, _m, size in keep)
    if max_bytes > 0 and total > max_bytes:
        # Oldest first, and never the last one standing.
        for path, _mtime, size in sorted(keep, key=lambda e: e[1])[:-1]:
            if total <= max_bytes:
                break
            if _remove_tree(path, size, f"trash over the {max_bytes / 1e9:.0f} GB cap"):
                removed += 1
                removed_bytes += size
                total -= size
                keep = [e for e in keep if e[0] != path]
    if min_free_bytes > 0 and len(keep) > 1:
        measure = free_bytes_fn if free_bytes_fn is not None else free_bytes_at
        free = measure(local_root)
        if free is None:
            log.debug("trash prune: could not measure free space under %s", local_root)
        elif free < min_free_bytes:
            log.warning(
                "trash prune: only %s GB free under %s (the floor is %s GB) -- dropping "
                "recovery copies the age and size rules would have kept (SYNC-16)",
                _gb(free), local_root, _gb(min_free_bytes))
            for path, _mtime, size in sorted(keep, key=lambda e: e[1])[:-1]:
                if free >= min_free_bytes:
                    break
                if _remove_tree(path, size, f"under the {_gb(min_free_bytes)} GB free-space floor"):
                    removed += 1
                    removed_bytes += size
                    total -= size
                    free += size
    return {
        "removed": removed,
        "removed_bytes": removed_bytes,
        "kept": max(0, len(entries) - removed),
        "kept_bytes": total,
        "at": _now_iso(),
    }


def _remove_tree(path: Path, size: int, why: str) -> bool:
    try:
        shutil.rmtree(path)
    except OSError as exc:
        log.warning("could not prune %s: %s", path, exc)
        return False
    log.info("pruned %s from the trash (%.2f GB, %s)", path.name, size / 1e9, why)
    return True


# -- the halt --------------------------------------------------------------
class HaltState:
    """"Stop all sync" -- the thing "Pause syncing" is not.

    Pause stops the rclone rotation and the express upload; lane C (Syncthing)
    keeps running, because pause exists for "my laptop is on a hotspot", not
    for "STOP". This is the other one: lanes A and B stop AND every lane C
    folder is paused through Syncthing's own REST API, the state is written to
    disk, and it is re-applied on the next start. Two scopes:

      * `local` -- the editor pressed it, the editor can clear it;
      * `fleet` -- an admin set it on the dashboard (`/api/v1/fleet/halt`);
        the companion adopts it from the report reply and REFUSES to clear it
        locally, because a fleet halt is usually somebody stopping a mistake
        from spreading and one editor's tray must not be able to override it.
    """

    def __init__(self, state_path: Path) -> None:
        self.state_path = Path(state_path)
        self._lock = threading.Lock()
        state = _read_json(self.state_path)
        self._active = bool(state.get("active"))
        self._scope = str(state.get("scope") or HALT_SCOPE_LOCAL)
        self._reason = str(state.get("reason") or "")
        self._at = str(state.get("at") or "")

    @property
    def active(self) -> bool:
        with self._lock:
            return self._active

    @property
    def scope(self) -> str:
        with self._lock:
            return self._scope

    @property
    def reason(self) -> str:
        with self._lock:
            return self._reason

    def report(self) -> dict[str, Any]:
        with self._lock:
            return {
                "active": self._active,
                "scope": self._scope if self._active else None,
                "reason": self._reason or None,
                "at": self._at or None,
            }

    def _persist_locked(self) -> None:
        _write_json(self.state_path, {
            "active": self._active, "scope": self._scope,
            "reason": self._reason, "at": self._at,
        })

    def engage(self, reason: str, scope: str = HALT_SCOPE_LOCAL) -> bool:
        """Returns True on the EDGE (so the caller stops the lanes once), and
        also when a LOCAL halt is upgraded to a FLEET one -- the reason
        changes and every tray has to say the new one."""
        scope = HALT_SCOPE_FLEET if scope == HALT_SCOPE_FLEET else HALT_SCOPE_LOCAL
        with self._lock:
            changed = (
                not self._active
                or (scope == HALT_SCOPE_FLEET and self._scope != HALT_SCOPE_FLEET)
                or str(reason) != self._reason
            )
            self._active = True
            self._scope = scope
            self._reason = str(reason)
            if changed:
                self._at = _now_iso()
            self._persist_locked()
        if changed:
            log.warning("SYNC HALTED (%s): %s", scope, reason)
        return changed

    def release(self, by: str = "tray", force: bool = False) -> tuple[bool, str]:
        """Clear the halt. `force` is the dashboard's release of a fleet halt;
        without it a fleet halt refuses, with the sentence the tray shows."""
        with self._lock:
            if not self._active:
                return False, "sync is not halted"
            if self._scope == HALT_SCOPE_FLEET and not force:
                return False, (
                    "your administrator halted syncing for the whole fleet"
                    + (f": {self._reason}" if self._reason else "")
                    + ". Only they can start it again."
                )
            reason, self._reason = self._reason, ""
            self._active = False
            self._scope = HALT_SCOPE_LOCAL
            self._at = _now_iso()
            self._persist_locked()
        log.warning("sync halt RELEASED by %s (was: %s)", by, reason)
        return True, "syncing will start again"

    def note_fleet_flag(self, halt: Any) -> Optional[bool]:
        """Adopt (or drop) the dashboard's fleet halt from a report reply.

        Returns True when the halt was newly engaged, False when it was
        newly released, None when nothing changed -- so app.py runs the
        expensive stop/start exactly on the edges. A reply that carries no
        `commands.halt` key at all (an older dashboard) is `None` here and
        must NOT clear a live fleet halt: absence of the field is absence of
        information, not a release.
        """
        if halt is None:
            return None
        if isinstance(halt, dict):
            active = bool(halt.get("active"))
            reason = str(halt.get("reason") or "")
        else:
            active = bool(halt)
            reason = ""
        if active:
            return True if self.engage(
                reason or "your administrator stopped syncing across the fleet",
                HALT_SCOPE_FLEET,
            ) else None
        with self._lock:
            was_fleet = self._active and self._scope == HALT_SCOPE_FLEET
        if not was_fleet:
            return None
        ok, _msg = self.release(by="dashboard", force=True)
        return False if ok else None
