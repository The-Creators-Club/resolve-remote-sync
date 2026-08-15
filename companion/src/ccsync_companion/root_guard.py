"""Is the editor's synced tree actually here right now?

A macOS editor's local_root lives on an external SSD at
``/Volumes/<Name>/Creators_Club``, and that drive is ejected and re-plugged
routinely -- at the end of a day, between rooms, by a sleeping laptop. Every
part of the companion that touches the tree assumes it exists, and the one
that matters is lane B: `rclone sync <NAS> <local_root>` against an ABSENT
/Volumes/<Name> does not fail. macOS happily creates the directory on the
BOOT volume and rclone fills the Mac's internal disk with the project it was
supposed to put on the SSD. Everything else follows from the same mistake --
the watcher storms BAD_PREFIX warnings, the manifest reports an empty tree
(which reads as a mass deletion on the dashboard), and Syncthing sees every
folder marker vanish.

So one question, asked in one place, answered honestly:

  present    the tree is there -- and on macOS, ON THE VOLUME IT BELONGS TO.
             ``os.path.isdir`` alone is NOT enough there: the classic
             leftover from an unclean eject is an empty directory sitting at
             /Volumes/<Name> on the boot disk, and isdir() says yes to
             exactly the failure this module exists to defend against. The
             volume component must also be a real mount point.
  absent     the drive is unplugged (or the directory is a ghost). Nothing
             can sync; nothing SHOULD be attempted.
  misplaced  the drive IS mounted, but somewhere else -- /Volumes/T7 1,
             because a leftover directory already occupies /Volumes/T7.
             Syncing into the old path would fill the internal disk while
             the real drive sits there unused, and the numbered name changes
             between replugs so it must never be adopted as the new root.
             Only detectable when a volume UUID was recorded; without one,
             `absent` covers it (and says the same thing to the user, just
             with less detail).
  unknown    the PROBE failed -- not the drive. Callers treat this as "no
             new information" and change nothing, because a bug in here must
             never be able to pause an editor's sync indefinitely.

The volume record (~/.ccsync/volume.json) is seeded by
installer/macos_bootstrap.sh and refreshed here on every present sighting:
{"volume_uuid": ..., "mount_point": ..., "local_root": ...}, mode 600. The
UUID is what makes `misplaced` distinguishable from `absent`; the bootstrap
tolerates a volume that gives no UUID, so every consumer here must too.

Windows is untouched by all of this: the probe is a plain isdir() and the
record file is never written. Same never-raise, injectable-seam discipline as
shutdown_guard.py -- everything that touches the platform (subprocess,
os.path.ismount, the clock, the directory listing) arrives as a parameter so
the darwin behaviour is testable from any host.
"""

from __future__ import annotations

import errno
import json
import logging
import os
import plistlib
import re
import subprocess
import sys
import threading
import time
from pathlib import Path
from typing import Any, Callable, Optional

from . import config as config_mod

# "ccsync.root_guard", NOT __name__ -- setup_logging() only attaches handlers
# to the "ccsync" logger, and in the windowed build sys.stderr is None, so a
# record emitted under "ccsync_companion.root_guard" is swallowed outright
# (see shutdown_guard.py's note on the same trap).
log = logging.getLogger("ccsync.root_guard")

# RootState values.
ROOT_PRESENT = "present"
ROOT_ABSENT = "absent"
ROOT_MISPLACED = "misplaced"
ROOT_UNKNOWN = "unknown"

VOLUME_RECORD_FILENAME = "volume.json"

VOLUMES_DIR = "/Volumes"
# Absolute path: a PATH lookup inside a LaunchAgent's minimal environment is
# not something to rely on, and this binary has lived here since forever.
DISKUTIL_PATH = "/usr/sbin/diskutil"
DISKUTIL_TIMEOUT_SECONDS = 10.0

# How long a `diskutil info` answer is reused. Enumerating /Volumes and
# spawning diskutil per volume on every 5 s poll would be a process launch
# every few seconds for the whole session; a volume's UUID changes only when
# it is reformatted, so this is generous and still notices a replug well
# inside the time it takes a human to look at the tray.
DISKUTIL_CACHE_SECONDS = 30.0

# How often the guard asks. Cheap (one isdir, one ismount) in the steady
# state, and fast enough that "I plugged it back in" feels immediate.
POLL_SECONDS = 5.0


# --- volume record (~/.ccsync/volume.json) ---------------------------------

def volume_record_path() -> Path:
    """~/.ccsync/volume.json -- the same directory config.py's CONFIG_PATH
    and identity.py's identity.json live in (config_mod.CONFIG_DIR), which is
    also exactly where installer/macos_bootstrap.sh writes it."""
    return config_mod.CONFIG_DIR / VOLUME_RECORD_FILENAME


def read_volume_record(path: Optional[Path] = None) -> Optional[dict[str, Any]]:
    """The recorded volume, or None. Tolerant of everything: a missing file
    (Windows, or a Mac whose root is not on an external volume), an
    unreadable one, malformed JSON, or a JSON value that isn't an object."""
    try:
        target = Path(path) if path is not None else volume_record_path()
        # utf-8-sig for the same reason identity.load_identity uses it: a BOM
        # from some other tool must not make the file unparseable.
        data = json.loads(target.read_text(encoding="utf-8-sig"))
    except (OSError, ValueError):
        return None
    except Exception:
        log.debug("volume record: unreadable", exc_info=True)
        return None
    return data if isinstance(data, dict) else None


def write_volume_record(
    record: dict[str, Any], path: Optional[Path] = None
) -> bool:
    """Replace the volume record atomically, mode 600. Never raises.

    os.replace so a reader (this guard, on its own thread, or a second
    companion mid-upgrade) sees either the whole old file or the whole new
    one -- a truncate-then-write would hand it an empty record, i.e. "no UUID
    known", i.e. a misplaced drive silently downgraded to absent.
    """
    try:
        target = Path(path) if path is not None else volume_record_path()
        target.parent.mkdir(parents=True, exist_ok=True)
        tmp = target.with_name(f"{target.name}.{os.getpid()}.tmp")
        tmp.write_text(json.dumps(record, indent=2), encoding="utf-8")
        # Before the replace: the file must never exist world-readable, even
        # for the instant between the two calls. Best effort -- chmod is a
        # no-op on Windows beyond the read-only bit, and this file is never
        # written there anyway.
        try:
            os.chmod(tmp, 0o600)
        except OSError:
            log.debug("volume record: could not chmod 600 %s", tmp, exc_info=True)
        os.replace(tmp, target)
        return True
    except Exception:
        log.debug("volume record: could not write", exc_info=True)
        return False


def mount_point_for(local_root: Any) -> Optional[str]:
    """"/Volumes/<Name>" for a local_root under /Volumes, else None.

    None means "this root is not on an external volume" -- a home-directory
    root on a Mac, or anything at all on Windows -- and every mount-point
    check below is skipped for it.
    """
    text = str(local_root or "").strip().replace("\\", "/")
    prefix = VOLUMES_DIR + "/"
    if not text.startswith(prefix):
        return None
    name = text[len(prefix):].split("/", 1)[0]
    return f"{prefix}{name}" if name else None


def _same_path(left: Any, right: Any) -> bool:
    try:
        return os.path.normcase(os.path.normpath(str(left))) == os.path.normcase(
            os.path.normpath(str(right))
        )
    except Exception:
        return False


def local_root_is_removable(
    local_root: Any,
    record: Optional[dict[str, Any]] = None,
    is_darwin: Optional[bool] = None,
    record_path: Optional[Path] = None,
) -> bool:
    """Is this local_root one that legitimately COMES AND GOES?

    The question app.py asks before demoting "local_root does not exist" from
    a config error into a runtime state: an editor whose SSD is unplugged at
    login has a perfectly good install, and bricking sync until they restart
    the companion is the wrong answer. A typo'd local_root on an internal
    disk is still a config error and must stay one.

    True when the host is macOS and the root is under /Volumes, or when the
    volume record knows this exact root (which is only ever written for a
    root on an external volume). Never raises.
    """
    try:
        root = str(local_root or "").strip()
        if not root:
            return False
        darwin = sys.platform == "darwin" if is_darwin is None else bool(is_darwin)
        if darwin and mount_point_for(root) is not None:
            return True
        known = record if record is not None else read_volume_record(record_path)
        if isinstance(known, dict) and _same_path(known.get("local_root"), root):
            return True
    except Exception:
        log.debug("local_root_is_removable(%r) failed", local_root, exc_info=True)
    return False


# --- diskutil ---------------------------------------------------------------

_UUID_RE = re.compile(
    r"<key>VolumeUUID</key>\s*<string>([^<]*)</string>", re.IGNORECASE
)


def default_run(argv: list, timeout: float = DISKUTIL_TIMEOUT_SECONDS) -> Optional[bytes]:
    """Run `argv`, return stdout bytes, or None on ANY failure.

    None is the only failure signal on purpose: a missing binary, a non-zero
    exit, a timeout and a volume diskutil refuses to describe all mean the
    same thing here -- "no UUID for this mount point" -- and none of them may
    raise into a poll loop.
    """
    try:
        proc = subprocess.run(  # noqa: S603 -- fixed argv, no shell
            argv,
            capture_output=True,
            timeout=timeout,
            stdin=subprocess.DEVNULL,
        )
    except Exception:
        log.debug("root guard: %s failed", " ".join(str(a) for a in argv), exc_info=True)
        return None
    if proc.returncode != 0:
        return None
    return proc.stdout


def parse_volume_uuid(data: Any) -> Optional[str]:
    """The VolumeUUID out of `diskutil info -plist` output, or None.

    plistlib first (it is the format's own parser); the regex is the fallback
    for a truncated/odd payload, and mirrors macos_bootstrap.sh's own
    plutil-then-sed pair for exactly the same reason -- the UUID is what
    separates "mounted somewhere else" from "unplugged", and giving up on it
    costs the user a much less useful message.
    """
    if not data:
        return None
    try:
        parsed = plistlib.loads(data if isinstance(data, bytes) else str(data).encode("utf-8"))
        if isinstance(parsed, dict):
            uuid = str(parsed.get("VolumeUUID") or "").strip()
            if uuid:
                return uuid
    except Exception:
        log.debug("root guard: plistlib could not read diskutil output", exc_info=True)
    try:
        text = data.decode("utf-8", "replace") if isinstance(data, bytes) else str(data)
        match = _UUID_RE.search(text)
        if match:
            uuid = match.group(1).strip()
            return uuid or None
    except Exception:
        log.debug("root guard: could not scan diskutil output for a UUID", exc_info=True)
    return None


def volume_uuid(
    mount_point: str,
    run_fn: Optional[Callable[..., Any]] = None,
    clock: Callable[[], float] = time.monotonic,
    cache: Optional[dict] = None,
) -> Optional[str]:
    """The UUID of the volume mounted at `mount_point`, or None.

    `cache` is a plain dict owned by the caller (mount point -> (stamp,
    uuid)), so the TTL is explicit and testable rather than hidden in module
    state -- and so two guards in one process cannot poison each other's
    view. A None answer is cached too: a volume that gives no UUID would
    otherwise cost a diskutil spawn on every single poll.
    """
    runner = run_fn if run_fn is not None else default_run
    now = float(clock())
    if cache is not None:
        cached = cache.get(mount_point)
        if cached is not None and (now - cached[0]) < DISKUTIL_CACHE_SECONDS:
            return cached[1]
    uuid = parse_volume_uuid(runner([DISKUTIL_PATH, "info", "-plist", mount_point],
                                    DISKUTIL_TIMEOUT_SECONDS))
    if cache is not None:
        cache[mount_point] = (now, uuid)
    return uuid


def find_volume_by_uuid(
    uuid: str,
    expected_mount: Optional[str] = None,
    listdir_fn: Optional[Callable[[str], list]] = None,
    ismount_fn: Optional[Callable[[str], bool]] = None,
    run_fn: Optional[Callable[..., Any]] = None,
    clock: Callable[[], float] = time.monotonic,
    cache: Optional[dict] = None,
) -> Optional[str]:
    """Where the volume with this UUID is mounted, ignoring `expected_mount`.

    In other words: "the drive is not where it should be -- is it anywhere?"
    Returns the mount point (e.g. "/Volumes/T7 1") or None. Never raises: a
    /Volumes we cannot list is "don't know", which is the same answer as "not
    mounted" for every caller here.
    """
    target = str(uuid or "").strip()
    if not target:
        return None
    listdir = listdir_fn if listdir_fn is not None else os.listdir
    ismount = ismount_fn if ismount_fn is not None else os.path.ismount
    try:
        names = sorted(listdir(VOLUMES_DIR))
    except Exception:
        log.debug("root guard: could not list %s", VOLUMES_DIR, exc_info=True)
        return None
    for name in names:
        candidate = f"{VOLUMES_DIR}/{name}"
        if expected_mount is not None and _same_path(candidate, expected_mount):
            continue
        try:
            if not ismount(candidate):
                continue
        except Exception:
            continue
        if volume_uuid(candidate, run_fn=run_fn, clock=clock, cache=cache) == target:
            return candidate
    return None


# --- the probe --------------------------------------------------------------

def probe_root(
    local_root: Any,
    is_darwin: Optional[bool] = None,
    isdir_fn: Optional[Callable[[str], bool]] = None,
    ismount_fn: Optional[Callable[[str], bool]] = None,
    listdir_fn: Optional[Callable[[str], list]] = None,
    run_fn: Optional[Callable[..., Any]] = None,
    clock: Callable[[], float] = time.monotonic,
    record: Optional[dict[str, Any]] = None,
    record_path: Optional[Path] = None,
    cache: Optional[dict] = None,
) -> str:
    """One of ROOT_PRESENT / ROOT_ABSENT / ROOT_MISPLACED / ROOT_UNKNOWN.

    Never raises. ROOT_UNKNOWN means the probe itself broke (or there is no
    local_root configured to probe) -- callers must treat it as "no new
    information", never as a reason to act.
    """
    try:
        root = str(local_root or "").strip()
        if not root:
            # Nothing to answer for. A blank local_root is a CONFIG error
            # (validate_config says so, loudly); reporting it as "your drive
            # is disconnected" would send the editor hunting for a cable.
            return ROOT_UNKNOWN

        darwin = sys.platform == "darwin" if is_darwin is None else bool(is_darwin)
        isdir = isdir_fn if isdir_fn is not None else os.path.isdir
        present = bool(isdir(root))

        if not darwin:
            # Windows (and linux): a drive letter either resolves or it does
            # not, and there is no ghost-directory failure mode to defend
            # against. Byte-identical to the behaviour before this module.
            return ROOT_PRESENT if present else ROOT_ABSENT

        mount_point = mount_point_for(root)
        if mount_point is None:
            # An internal-disk root on a Mac (~/Creators_Club): same answer as
            # Windows, because there is no volume to be mounted or missing.
            return ROOT_PRESENT if present else ROOT_ABSENT

        ismount = ismount_fn if ismount_fn is not None else os.path.ismount
        try:
            mounted = bool(ismount(mount_point))
        except Exception:
            log.debug("root guard: ismount(%s) failed", mount_point, exc_info=True)
            return ROOT_UNKNOWN

        if present and mounted:
            return ROOT_PRESENT
        if present and not mounted:
            # THE GHOST DIRECTORY. isdir() said yes and it is a lie: this is
            # an empty leftover on the BOOT volume, and syncing into it fills
            # the Mac's internal disk. Never `present`.
            log.debug(
                "root guard: %s exists but %s is not a mount point -- treating the "
                "root as absent", root, mount_point,
            )

        known = record if record is not None else read_volume_record(record_path)
        recorded_uuid = str((known or {}).get("volume_uuid") or "").strip()
        if recorded_uuid:
            elsewhere = find_volume_by_uuid(
                recorded_uuid, expected_mount=mount_point, listdir_fn=listdir_fn,
                ismount_fn=ismount_fn, run_fn=run_fn, clock=clock, cache=cache,
            )
            if elsewhere:
                log.debug("root guard: the recorded volume is mounted at %s, not %s",
                          elsewhere, mount_point)
                return ROOT_MISPLACED
        # No UUID recorded (the bootstrap tolerates a volume diskutil gave
        # none for), or the volume is genuinely not mounted anywhere:
        # `absent` is the honest answer and tells the editor the same thing.
        return ROOT_ABSENT
    except Exception:
        log.exception("root guard: probe failed -- reporting unknown")
        return ROOT_UNKNOWN


# --- macOS is blocking us, as opposed to the drive being out ---------------
#
# Item 16. The companion is ad-hoc signed (`TeamIdentifier=not set`), so its
# Full Disk Access identity is a hash of the binary and EVERY self-upgrade
# presents to TCC as a different program needing a fresh grant. On a Mac
# whose sync root is an external volume -- the deployment this port exists
# for -- losing that grant makes the tree unreadable with no error anywhere
# naming the cause: the directory is right there, the drive is mounted, and
# every read comes back EPERM.
#
# That is NOT the drive being unplugged, which probe_root already answers as
# `absent`, and telling the editor to check the cable is the same dead end
# MAC-10's "DaVinci Resolve is not running" was. Until the companion can be
# signed with a stable identity, naming it is the fallback the bug asks for.

_DENIED_ERRNOS = (errno.EACCES, errno.EPERM)


def _read_is_denied(path: str, listdir: Callable[[str], Any]) -> bool:
    """Did reading `path` come back "not permitted", SPECIFICALLY?

    Only EACCES/EPERM count. A path that does not exist, a stale mount, a
    listdir that raised something exotic -- none of those is macOS refusing
    us, and claiming otherwise would put a Full Disk Access instruction in
    front of an editor whose drive is simply in their bag.
    """
    try:
        listdir(path)
    except PermissionError:
        return True
    except OSError as exc:
        return getattr(exc, "errno", None) in _DENIED_ERRNOS
    except Exception:
        log.debug("root guard: could not read %s", path, exc_info=True)
        return False
    return False


def access_is_blocked(
    local_root: Any,
    is_darwin: Optional[bool] = None,
    listdir_fn: Optional[Callable[[str], Any]] = None,
    ismount_fn: Optional[Callable[[str], bool]] = None,
) -> bool:
    """Is macOS refusing us the sync root while the volume is right there?

    True only for the narrow, actionable case: darwin, plus a read of the
    root (or of the volume it sits on) failing with EACCES/EPERM, plus that
    volume still being mounted. Everything else -- Windows, a drive that is
    genuinely out, a path that never existed, a probe that broke -- is
    somebody else's story and returns False.

    Never raises, and on Windows it returns before touching the disk. One
    listdir per call, so callers must keep it off hot paths (app.py runs it
    once, on a timer, after a self-upgrade).
    """
    try:
        root = str(local_root or "").strip()
        darwin = sys.platform == "darwin" if is_darwin is None else bool(is_darwin)
        if not root or not darwin:
            return False
        listdir = listdir_fn if listdir_fn is not None else os.listdir
        mount_point = mount_point_for(root)

        denied = _read_is_denied(root, listdir)
        if not denied and mount_point is not None and not _same_path(mount_point, root):
            # TCC can refuse the volume as a whole while the root inside it
            # merely reports ENOENT -- an unreadable parent hides its children.
            denied = _read_is_denied(mount_point, listdir)
        if not denied:
            return False

        if mount_point is None:
            # An internal-disk root (~/Creators_Club): there is no volume to
            # confirm, and "permission denied" there means the same thing --
            # TCC also covers Desktop/Documents/Downloads.
            return True

        ismount = ismount_fn if ismount_fn is not None else os.path.ismount
        try:
            if not ismount(mount_point):
                # The drive is out, or this is the ghost directory. probe_root
                # owns that story and says the right thing about it.
                return False
        except Exception:
            log.debug("root guard: ismount(%s) failed", mount_point, exc_info=True)
            return False
        return True
    except Exception:
        log.debug("root guard: could not tell whether access is blocked", exc_info=True)
        return False


def refresh_volume_record(
    local_root: Any,
    is_darwin: Optional[bool] = None,
    run_fn: Optional[Callable[..., Any]] = None,
    clock: Callable[[], float] = time.monotonic,
    cache: Optional[dict] = None,
    record_path: Optional[Path] = None,
) -> Optional[dict[str, Any]]:
    """Re-record the volume this root is on, if it has changed. Never raises.

    Called on every PRESENT sighting, and cheap because the diskutil answer
    is cached: the file is only rewritten when the UUID or the mount point
    actually differs from what is on disk, so a healthy machine writes it
    once ever. Returns the record now on disk (or None when there is nothing
    to record: Windows, or a root that is not on an external volume).
    """
    try:
        root = str(local_root or "").strip()
        darwin = sys.platform == "darwin" if is_darwin is None else bool(is_darwin)
        if not root or not darwin:
            return None
        mount_point = mount_point_for(root)
        if mount_point is None:
            return None
        uuid = volume_uuid(mount_point, run_fn=run_fn, clock=clock, cache=cache) or ""
        existing = read_volume_record(record_path) or {}
        record = {
            "volume_uuid": uuid,
            "mount_point": mount_point,
            "local_root": root,
        }
        if (
            str(existing.get("volume_uuid") or "") == uuid
            and _same_path(existing.get("mount_point"), mount_point)
            and _same_path(existing.get("local_root"), root)
        ):
            return dict(existing)
        if not uuid and str(existing.get("volume_uuid") or "").strip():
            # diskutil went quiet on a volume we DO have a UUID for. Keep the
            # old one: overwriting it with "" would throw away the only thing
            # that can tell `misplaced` from `absent` later.
            record["volume_uuid"] = str(existing["volume_uuid"])
        if write_volume_record(record, record_path):
            log.info("root guard: recorded the sync volume %s (uuid=%s)",
                     mount_point, record["volume_uuid"] or "unknown")
            return record
        return dict(existing) or None
    except Exception:
        log.debug("root guard: could not refresh the volume record", exc_info=True)
        return None


# --- the guard --------------------------------------------------------------

def state_is_absent(state: Any) -> bool:
    """Does this state mean "do not touch the tree"? (absent OR misplaced.)"""
    return str(state) in (ROOT_ABSENT, ROOT_MISPLACED)


class RootGuard:
    """Polls probe_root() and calls back on TRANSITIONS only.

    One callback per change of mind, never one per poll: on_present() when
    the tree comes back, on_absent(state) when it goes (or when `absent`
    turns out to be `misplaced`, which needs a different sentence). The first
    non-unknown sample always fires, so a companion that starts with the
    drive already unplugged is told about it immediately rather than at the
    next replug.

    ROOT_UNKNOWN is deliberately swallowed: it means the probe failed, and a
    failing probe must not be able to pause an editor's sync -- so the last
    known state simply stands.

    Never raises, out of the loop or out of a callback. Daemon thread; start()
    and stop() are idempotent.
    """

    def __init__(
        self,
        local_root: Any,
        on_present: Optional[Callable[[], None]] = None,
        on_absent: Optional[Callable[[str], None]] = None,
        poll_seconds: float = POLL_SECONDS,
        is_darwin: Optional[bool] = None,
        isdir_fn: Optional[Callable[[str], bool]] = None,
        ismount_fn: Optional[Callable[[str], bool]] = None,
        listdir_fn: Optional[Callable[[str], list]] = None,
        run_fn: Optional[Callable[..., Any]] = None,
        clock: Callable[[], float] = time.monotonic,
        record_path: Optional[Path] = None,
    ) -> None:
        self.local_root = local_root
        self._on_present = on_present
        self._on_absent = on_absent
        try:
            self._poll_seconds = float(poll_seconds)
            if self._poll_seconds <= 0:
                raise ValueError
        except (TypeError, ValueError):
            log.error("root guard: poll_seconds=%r is not positive -- using %r",
                      poll_seconds, POLL_SECONDS)
            self._poll_seconds = POLL_SECONDS
        self._is_darwin = is_darwin
        self._isdir_fn = isdir_fn
        self._ismount_fn = ismount_fn
        self._listdir_fn = listdir_fn
        self._run_fn = run_fn
        self._clock = clock
        self._record_path = record_path
        # mount point -> (stamp, uuid). Owned here so the TTL survives across
        # polls; see volume_uuid().
        self._diskutil_cache: dict = {}
        self._state: Optional[str] = None
        self._stop_event = threading.Event()
        self._thread: Optional[threading.Thread] = None

    @property
    def state(self) -> str:
        """The last non-unknown state, or ROOT_UNKNOWN before the first poll."""
        return self._state or ROOT_UNKNOWN

    @property
    def stop_event(self) -> threading.Event:
        return self._stop_event

    def present(self) -> bool:
        """Whether the tree is believed to be there RIGHT NOW.

        Unknown counts as present: this is read by the watcher gate and the
        shutdown-reason suppressor, and neither may be switched off by a
        probe that has not managed to answer yet.
        """
        return not state_is_absent(self._state)

    # -- the part worth testing --------------------------------------------

    def probe_once(self) -> str:
        """Probe, fire the callback if the answer CHANGED, return the state.

        Both stop-event checks are load-bearing (COMP-GUARD-4, 2026-08-14):
        the callbacks START LANES, and one firing during teardown leaves a
        sequencer and an rclone child running in a process that is exiting
        (app.shutdown's own comment states the requirement). stop() cannot
        provide that on its own -- it joins for 2.5 s and returns regardless,
        while a probe can easily run longer: on darwin the misplaced-drive
        path spawns `diskutil info -plist` per mounted volume at 10 s each,
        and on Windows an isdir() against a dropped SMB mapping blocks on the
        network timeout.
        """
        if self._stop_event.is_set():
            return self.state
        state = probe_root(
            self.local_root,
            is_darwin=self._is_darwin,
            isdir_fn=self._isdir_fn,
            ismount_fn=self._ismount_fn,
            listdir_fn=self._listdir_fn,
            run_fn=self._run_fn,
            clock=self._clock,
            record_path=self._record_path,
            cache=self._diskutil_cache,
        )
        if state == ROOT_UNKNOWN:
            # No new information. Deliberately does not become the current
            # state: a flapping probe would otherwise pause and resume an
            # editor's sync on alternate polls.
            return state
        if state == self._state:
            return state
        if self._stop_event.is_set():
            # stop() landed while this probe ran. Do NOT record the new state
            # either: a later start() would then see no transition and never
            # fire, so the lanes would stay down after the drive came back.
            log.info("root guard: %s seen during teardown -- not acting on it", state)
            return state
        previous, self._state = self._state, state
        log.info("root guard: %s -> %s (%s)", previous or "startup", state, self.local_root)
        self._fire(state)
        return state

    def _fire(self, state: str) -> None:
        if self._stop_event.is_set():
            # Belt and braces with probe_once's own check: every path to a
            # callback that starts lanes goes through here (COMP-GUARD-4).
            log.debug("root guard: not firing the %s callback -- stopping", state)
            return
        try:
            if state == ROOT_PRESENT:
                if self._on_present is not None:
                    self._on_present()
            elif self._on_absent is not None:
                self._on_absent(state)
        except Exception:
            # A callback that raises must not kill the poll thread -- the
            # guard would then never notice the drive coming back, which is
            # the one thing it exists to do.
            log.exception("root guard: %s callback failed", state)

    # -- lifecycle ----------------------------------------------------------

    def start(self) -> None:
        # is_alive(), not "is not None": same reason as every guard in
        # shutdown_guard.py -- a dead Thread object left here would make the
        # guard permanently un-restartable while reporting nothing.
        thread = self._thread
        if thread is not None and thread.is_alive():
            return
        self._stop_event.clear()
        try:
            self._thread = threading.Thread(
                target=self._loop, name="ccsync-root-guard", daemon=True
            )
            self._thread.start()
        except Exception:
            log.exception("root guard: could not start its thread")
            self._thread = None

    def stop(self) -> None:
        thread = self._thread
        self._stop_event.set()
        if thread is not None and thread.is_alive():
            thread.join(timeout=max(2.0, self._poll_seconds / 2))
            if thread.is_alive():
                # KEEP the reference (SYNC-15's precedent in
                # _WindowsShutdownGuard.stop): a probe can outlive this join,
                # and dropping it here let a later start() -- which clears
                # _stop_event -- spawn a SECOND poller alongside one that
                # never saw the set (COMP-GUARD-4, 2026-08-14).
                log.warning(
                    "root guard: its probe did not finish within %.1fs -- keeping the "
                    "thread rather than starting a second one",
                    max(2.0, self._poll_seconds / 2),
                )
                return
        self._thread = None

    def _loop(self) -> None:
        try:
            while True:
                self.probe_once()
                if self._stop_event.wait(self._poll_seconds):
                    break
        except Exception:
            log.exception("root guard: poll loop stopped")
