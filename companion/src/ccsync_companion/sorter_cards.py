"""The camera cards in this computer's readers, reported to the Footage Sorter.

Companion half of docs/DASHBOARD-MODULE-PLAN.md in the footage-sorter repo,
"Card ingest through the companion: the protocol" (2026-11-09), step 1. A card
is in a reader on this PC; only this process can read it, and only the sorter
(inside the dashboard) knows where its footage should go. So this module does
three things and nothing else:

  * FINDS the local volumes, removable AND fixed (CFexpress Type B and
    Blackmagic SSD readers present their cards as fixed disks: the tray's
    WatchDriveTypes = Removable, Fixed), never the system disk; a fixed volume
    counts only with a camera's layout on it (no `generic`). A volume that
    looks like nothing yet is looked at again for SLOW_MOUNT_RETRIES ticks
    (the tray's SlowMountRetries). For a `drive-copy`, any local volume by
    its serial;
  * CLASSIFIES each one with the Node ingest's predicates, ported from
    footage-sorter `lib/ingest/detect.js` (same order of precedence, same
    defaults), and LISTS it into the protocol's `files` / `texts` / `wav`
    shape, skipping what `footage_sorter/scan.py` skips;
  * POSTS the machine's FULL current set to `{dashboard_url}/sorter/agent/cards`
    when it changes and every five minutes while any card is present.

The listing is read-only. Three rules, each with its reason:

  * **A CARD BEING COPIED IS NEVER READ BY ANYTHING ELSE.** A card-ingest job
    registers its volume in `ingest_busy`; this loop then neither probes nor
    re-lists it, and reports the listing it already had. Two readers on a
    slow SD card double the copy time and make a flaky reader flakier.
  * **A 404 OR 503 IS A SITE WITHOUT A SORTER.** Not an error: the loop backs
    off for ten minutes and says nothing above DEBUG, because most
    dashboards will never have a sorter.
  * **A CARD IS IDENTIFIED BY ITS VOLUME SERIAL, never its drive letter.**
    Card readers keep their letter when empty and a different card gets it
    next; the serial is what the copy job names and what the wrong-card
    refusal checks.

`generic` and "not a card": the Node detector returned null for anything it
did not recognise; the protocol adds `generic`. A removable volume that none
of the four predicates matches is `generic` when it holds media files
(video, audio or photos, within four folders of the root) and is NOT
reported at all when it holds none -- a USB stick of documents is not a card.
"""
from __future__ import annotations

import hashlib
import json
import logging
import os
import platform
import re
import subprocess
import threading
import time
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable, Iterator, Optional

from . import config as config_mod

log = logging.getLogger("ccsync.sortercards")

# -- the ported detector (footage-sorter lib/ingest/detect.js DEFAULTS) ------
DEFAULTS: dict[str, Any] = {
    "sony": {"clipPath": "PRIVATE/M4ROOT/CLIP", "proxyPath": "PRIVATE/M4ROOT/SUB",
             "thumbPath": "PRIVATE/M4ROOT/THMBNL"},
    "drone": {"path": "DCIM", "exts": [".mp4", ".mov"]},
    "audio": {"patterns": ["*Wireless PRO*", r"^\d{6}_\d{3}$"], "exts": [".wav"]},
    "braw": {"exts": [".braw"]},
}
KINDS = ("sony", "bmcc", "drone", "audio", "generic")

# footage_sorter/scan.py: SKIP_DIR_NAMES, SKIP_FILE_NAMES, and its rule that a
# dot-directory and a macOS "._" twin are never footage.
SKIP_DIR_NAMES = {"$recycle.bin", "system volume information", "#recycle", ".git",
                  "node_modules", "__macosx", ".spotlight-v100", ".trashes",
                  ".fseventsd", "lost+found", "dupe-quarantine"}
SKIP_FILE_NAMES = {".ds_store", "thumbs.db", "desktop.ini", "sync.ffs_db"}

# What makes an otherwise unrecognised volume a `generic` card.
MEDIA_EXTS = {
    ".mp4", ".mov", ".mxf", ".mkv", ".avi", ".mts", ".m2ts", ".braw", ".r3d", ".webm",
    ".wav", ".mp3", ".aif", ".aiff", ".flac", ".m4a", ".aac",
    ".jpg", ".jpeg", ".png", ".heic", ".dng", ".arw", ".cr2", ".cr3", ".nef", ".raf",
    ".orf", ".rw2", ".tif", ".tiff",
}
GENERIC_DEPTH = 4

XML_BYTES = 4096

SCAN_SECONDS = 10.0        # how often the loop looks at the readers
RESEND_SECONDS = 300.0     # protocol: every 5 minutes while any card is present
RELIST_SECONDS = 300.0     # a card is re-read at most this often when nothing moved
# A volume that is not (yet) a card is looked at again on each of this many
# ticks before its "not a card" is believed for RELIST_SECONDS: a card that
# mounts before its files are readable must not be missed for five minutes.
# The tray's SlowMountRetries (footage-sorter ingest/tray/Config.psd1).
SLOW_MOUNT_RETRIES = 6
NO_SORTER_BACKOFF_SECONDS = 600.0
REFUSED_BACKOFF_SECONDS = 300.0
POST_TIMEOUT_SECONDS = 60.0
AGENT_PATH = "/sorter/agent/cards"


# ---------------------------------------------------------------- busy cards
_busy_lock = threading.Lock()
_busy: dict[str, str] = {}              # serial -> volume root being copied from
_known_drives: dict[str, str] = {}      # serial -> the root it was last seen at


@contextmanager
def ingest_busy(serial: str, root: str) -> Iterator[None]:
    """Mark a volume as being copied from, so nothing else reads it."""
    key = str(serial or "").upper()
    with _busy_lock:
        _busy[key] = str(root)
    try:
        yield
    finally:
        with _busy_lock:
            _busy.pop(key, None)


def busy_roots() -> set[str]:
    with _busy_lock:
        return set(_busy.values())


def busy_serials() -> set[str]:
    with _busy_lock:
        return set(_busy)


# Volumes a copy is WRITING to right now (root -> how many copies). Their free space moves with
# every file, which is the loop's "something changed, read it again" signal; a field drive that
# already holds a backup lists as a `generic` card, so it was walked in full, every .xml and WAV
# header read, and the whole listing posted, every tick for as long as the copy ran, competing
# with the copy for the same disk (audit comp-field-9, 2026-11-11). While a root is in here the
# listing it already had is reused; the tick after the copy ends reads it once.
_dest_busy: dict[str, int] = {}


def _root_key(root: str) -> str:
    return os.path.normcase(os.path.normpath(str(root or ""))).rstrip("\\/")


@contextmanager
def dest_busy(root: str) -> Iterator[None]:
    """Mark a volume as being written to by a copy, so its listing is not re-read meanwhile."""
    key = _root_key(root)
    if key:
        with _busy_lock:
            _dest_busy[key] = _dest_busy.get(key, 0) + 1
    try:
        yield
    finally:
        if key:
            with _busy_lock:
                left = _dest_busy.get(key, 0) - 1
                if left > 0:
                    _dest_busy[key] = left
                else:
                    _dest_busy.pop(key, None)


def dest_busy_roots() -> set[str]:
    """The roots being written to, as _root_key spells them (compare through _root_key)."""
    with _busy_lock:
        return set(_dest_busy)


def note_drive(serial: str, root: str) -> None:
    with _busy_lock:
        _known_drives[str(serial or "").upper()] = str(root)


def last_drive(serial: str) -> str:
    """Where this serial was last seen, or ""."""
    with _busy_lock:
        return _known_drives.get(str(serial or "").upper(), "")


# ------------------------------------------------------------------ volumes
def _now_iso() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace(
        "+00:00", "Z")


def _windows_volumes(scope: str, skip: set[str]) -> list[dict[str, Any]]:
    import ctypes
    from ctypes import wintypes

    kernel32 = ctypes.windll.kernel32                     # type: ignore[attr-defined]
    # An empty card reader must answer "no media" and not raise the system's
    # "There is no disk in the drive" box on somebody's desktop.
    old = wintypes.DWORD(0)
    try:
        kernel32.SetThreadErrorMode(1, ctypes.byref(old))     # SEM_FAILCRITICALERRORS
    except Exception:                                         # noqa: BLE001
        pass
    out: list[dict[str, Any]] = []
    system_drive = (os.environ.get("SystemDrive") or "C:").upper()
    try:
        mask = int(kernel32.GetLogicalDrives())
        for i in range(26):
            if not mask & (1 << i):
                continue
            drive = f"{chr(65 + i)}:"
            root = drive + "\\"
            if root in skip:
                continue
            dtype = int(kernel32.GetDriveTypeW(root))
            wanted = (2,) if scope == "removable" else (2, 3)
            if dtype not in wanted:
                continue
            label = ctypes.create_unicode_buffer(261)
            fsname = ctypes.create_unicode_buffer(64)
            serial = wintypes.DWORD(0)
            ok = kernel32.GetVolumeInformationW(
                root, label, 261, ctypes.byref(serial), None, None, fsname, 64)
            if not ok:
                continue                       # no media in the reader
            out.append({"serial": f"{serial.value:08X}", "label": label.value,
                        "drive": drive, "root": root, "removable": dtype == 2,
                        # the volume report's extras (scope "all"): the file system,
                        # "removable" | "fixed", and whether Windows lives here
                        "fs": fsname.value,
                        "drive_type": "removable" if dtype == 2 else "fixed",
                        "system": drive.upper() == system_drive})
    finally:
        try:
            kernel32.SetThreadErrorMode(old.value, None)
        except Exception:                                     # noqa: BLE001
            pass
    return out


def _mac_volumes(scope: str, skip: set[str]) -> list[dict[str, Any]]:
    import plistlib

    out: list[dict[str, Any]] = []
    base = Path("/Volumes")
    try:
        entries = sorted(base.iterdir())
    except OSError:
        return out
    for entry in entries:
        root = str(entry)
        probe = root
        if root in skip or not entry.is_dir():
            continue
        if entry.is_symlink():
            # `/Volumes/Macintosh HD` is a link to `/`: the startup disk. A card scan never wants
            # it, but "local"/"all" must list it, or a Mac's own drive (and every laptop folder on
            # it) has no volume. Its serial is the APFS Data volume's: the sealed system volume's
            # UUID changes with every macOS update, the Data volume's does not.
            if scope == "removable" or os.path.realpath(root) != "/" or "/" in skip:
                continue
            root = "/"
            probe = "/System/Volumes/Data" if os.path.isdir("/System/Volumes/Data") else "/"
        try:
            raw = subprocess.run(["diskutil", "info", "-plist", probe],
                                 capture_output=True, timeout=10).stdout
            info = plistlib.loads(raw)
        except Exception:                                     # noqa: BLE001
            continue
        removable = bool(info.get("RemovableMediaOrExternal")
                         or info.get("Removable") or info.get("Ejectable"))
        if scope == "removable" and not removable:
            continue
        uuid = str(info.get("VolumeUUID") or "").replace("-", "").upper()
        if not uuid:
            continue
        try:
            system = os.stat(root).st_dev == os.stat("/").st_dev
        except OSError:
            system = False
        out.append({"serial": uuid, "label": entry.name, "drive": root,
                    "root": root, "removable": removable,
                    "fs": str(info.get("FilesystemName") or info.get("FilesystemType") or ""),
                    "drive_type": "removable" if removable else "fixed",
                    "system": bool(info.get("SystemImage")) or system})
    return out


def list_volumes(scope: str = "removable",
                 skip: Optional[set[str]] = None) -> list[dict[str, Any]]:
    """Volumes this computer can see, each {serial, label, drive, root,
    capacity, free, removable, fs, drive_type, system}. `scope` is "removable"
    (card readers), "local" (also fixed drives, for a drive-copy) or "all" (what
    the ledger's volume report lists: the same set as "local", named for what it
    is for; `drive_type` is "removable" or "fixed", `system` flags the drive the
    OS lives on). Roots in `skip` are not touched. Never raises."""
    skip = set(skip or ())
    try:
        if os.name == "nt":
            found = _windows_volumes(scope, skip)
        elif platform.system() == "Darwin":
            found = _mac_volumes(scope, skip)
        else:
            found = []
    except Exception:                                         # noqa: BLE001
        log.debug("sorter cards: could not enumerate volumes", exc_info=True)
        return []
    import shutil
    for vol in found:
        try:
            usage = shutil.disk_usage(vol["root"])
            vol["capacity"], vol["free"] = int(usage.total), int(usage.free)
        except OSError:
            vol["capacity"], vol["free"] = 0, 0
    return found


# --------------------------------------------------------------- detection
def _pattern_to_regex(pat: str) -> Optional["re.Pattern[str]"]:
    """detect.js patternToRegex: a ^-prefixed pattern is a regex, anything else
    a case-insensitive wildcard (* and ?)."""
    text = str(pat or "")
    if not text:
        return None
    if text.startswith("^"):
        try:
            return re.compile(text, re.IGNORECASE)
        except re.error:
            return None
    body = re.escape(text).replace(r"\*", ".*").replace(r"\?", ".")
    return re.compile("^" + body + "$", re.IGNORECASE)


def _files_in(directory: Path) -> list[str]:
    try:
        return [e.name for e in os.scandir(directory)
                if e.is_file(follow_symlinks=False)]
    except OSError:
        return []


def _ext(name: str) -> str:
    i = name.rfind(".")
    return "" if i <= 0 else name[i:].lower()


def _stem(name: str) -> str:
    i = name.rfind(".")
    return name if i <= 0 else name[:i]


def _has_media(root: Path, depth: int = GENERIC_DEPTH) -> bool:
    stack = [(root, 0)]
    while stack:
        directory, level = stack.pop()
        try:
            entries = list(os.scandir(directory))
        except OSError:
            continue
        for e in entries:
            lower = e.name.lower()
            try:
                if e.is_file(follow_symlinks=False):
                    if (lower not in SKIP_FILE_NAMES and not e.name.startswith("._")
                            and _ext(e.name) in MEDIA_EXTS):
                        return True
                elif (e.is_dir(follow_symlinks=False) and level + 1 < depth
                      and lower not in SKIP_DIR_NAMES and not e.name.startswith(".")):
                    stack.append((Path(e.path), level + 1))
            except OSError:
                continue
    return False


def classify(root: "str | Path", defaults: Optional[dict[str, Any]] = None,
             generic: bool = True) -> Optional[str]:
    """What kind of card is the volume at `root`? -> a name in KINDS, or None
    when it is not a card.

    detect.js's order of precedence, and its rule that detection is by CONTENT
    and never by drive letter: a Sony structure wins if a drive somehow carries
    more than one; then a drone's DCIM\\NNNMEDIA with mp4/mov in it; then loose
    .braw files in the root (Blackmagic, named `bmcc` in the protocol); then
    loose WAVs named like a Wireless PRO or field recorder. An empty Sony card
    is still a Sony card -- an insertion somebody should hear about.

    `generic=False` (a FIXED volume: see SorterCards.current_cards) answers
    only for a camera's own layout, never "it holds media": an internal disk
    full of footage is not a card, and is not walked four folders deep.
    """
    d = {**DEFAULTS, **(defaults or {})}
    base = Path(root)
    sony = {**DEFAULTS["sony"], **(d.get("sony") or {})}
    drone = {**DEFAULTS["drone"], **(d.get("drone") or {})}
    audio = {**DEFAULTS["audio"], **(d.get("audio") or {})}
    braw = {**DEFAULTS["braw"], **(d.get("braw") or {})}

    if (base / sony["clipPath"]).is_dir():
        return "sony"

    dcim = base / (drone.get("path") or "DCIM")
    if dcim.is_dir():
        exts = {e.lower() for e in drone.get("exts") or []}
        try:
            subs = [e.name for e in os.scandir(dcim)
                    if e.is_dir() and re.fullmatch(r"\d{3}MEDIA", e.name, re.IGNORECASE)]
        except OSError:
            subs = []
        if any(_ext(f) in exts for s in subs for f in _files_in(dcim / s)):
            return "drone"

    root_files = _files_in(base)
    braw_exts = {e.lower() for e in braw.get("exts") or []}
    if any(_ext(n) in braw_exts and not n.startswith("._") for n in root_files):
        return "bmcc"

    audio_exts = {e.lower() for e in audio.get("exts") or [".wav"]}
    res = [r for r in (_pattern_to_regex(p) for p in audio.get("patterns") or []) if r]
    if any(_ext(n) in audio_exts and any(r.search(_stem(n)) for r in res)
           for n in root_files):
        return "audio"

    if not generic:
        return None
    return "generic" if _has_media(base) else None


# ----------------------------------------------------------------- listing
def list_card(root: "str | Path") -> dict[str, Any]:
    """Every file on the volume as the protocol's {files, texts, wav}.

    `files`: [rel path (forward slashes), size, mtimeMs]; `texts`: the first
    4096 bytes of every .xml; `wav`: each WAV's header duration in seconds,
    keyed by rel path. The skips are scan.py's, so what the sorter groups is
    what the Node scanner would have seen.

    `unreadable`: the folders (and single entries) that could NOT be read,
    as rel paths ("" is the card's own top folder). A listing with anything
    in it is PARTIAL: whatever sits in those folders is absent from `files`,
    so nobody may call the card backed up on the strength of it. Until
    2026-11-11 (audit comp-field-1) such a folder was logged at debug and
    skipped, and a DJI card whose DCIM/101MEDIA threw a read error was judged
    "Safe to format" on 100MEDIA alone. ledger_scan.walk has carried the
    same list for drives since it was written.
    """
    from .wav_header import wav_seconds

    base = Path(root)
    files: list[list[Any]] = []
    texts: dict[str, str] = {}
    wav: dict[str, float] = {}
    unreadable: list[str] = []

    def _rel(path: Any) -> str:
        try:
            rel = Path(path).relative_to(base).as_posix()
        except ValueError:
            rel = str(path)
        return "" if rel == "." else rel

    stack = [base]
    while stack:
        directory = stack.pop()
        try:
            entries = sorted(os.scandir(directory), key=lambda e: e.name)
        except OSError as exc:
            log.warning("sorter cards: cannot read %s (%s); the listing is partial", directory, exc)
            unreadable.append(_rel(directory))
            continue
        for e in entries:
            lower = e.name.lower()
            try:
                if e.is_dir(follow_symlinks=False):
                    if lower in SKIP_DIR_NAMES or e.name.startswith("."):
                        continue
                    stack.append(Path(e.path))
                    continue
                if not e.is_file(follow_symlinks=False):
                    continue
                if lower in SKIP_FILE_NAMES or e.name.startswith("._"):
                    continue
                st = e.stat(follow_symlinks=False)
            except OSError as exc:
                # a name every rule above skips is not footage whether or not
                # it will stat, and must not make a readable card partial
                if (lower in SKIP_DIR_NAMES or lower in SKIP_FILE_NAMES
                        or e.name.startswith(".")):
                    continue
                log.warning("sorter cards: cannot read %s (%s); the listing is partial", e.path, exc)
                unreadable.append(_rel(e.path))
                continue
            rel = Path(e.path).relative_to(base).as_posix()
            files.append([rel, int(st.st_size), round(st.st_mtime * 1000.0, 1)])
            ext = _ext(e.name)
            if ext == ".xml":
                try:
                    with open(e.path, "rb") as fh:
                        texts[rel] = fh.read(XML_BYTES).decode("utf-8", "replace")
                except OSError:
                    pass
            elif ext == ".wav":
                seconds = wav_seconds(e.path)
                if seconds is not None:
                    wav[rel] = round(seconds, 3)
    files.sort(key=lambda f: f[0])
    unreadable.sort()
    return {"files": files, "texts": texts, "wav": wav, "unreadable": unreadable}


def is_fixed(vol: dict[str, Any]) -> bool:
    """Windows calls this volume a fixed disk. CFexpress Type B and Blackmagic
    SSD readers present their cards as FIXED, not removable (2026-11-10: a
    CFexpress B card from a Blackmagic camera, H: on creator-1, was never
    seen). A volume that does not say is a removable one, as before."""
    return vol.get("removable", True) is False


def describe(vol: dict[str, Any], detected_at: str) -> Optional[dict[str, Any]]:
    """A volume -> the protocol's card object, or None when it is not a card.
    A fixed volume is a card only when it carries a camera's layout."""
    kind = classify(vol["root"], generic=not is_fixed(vol))
    if kind is None:
        return None
    listing = list_card(vol["root"])
    if not listing.get("unreadable"):
        # the card report's body is unchanged for a card that read in full;
        # only a partial listing says so (the sorter reads cards with .get)
        listing.pop("unreadable", None)
    return {"serial": vol["serial"], "label": vol.get("label", ""),
            "drive": vol["drive"], "kind": kind,
            "capacity": int(vol.get("capacity") or 0), "free": int(vol.get("free") or 0),
            "detectedAt": detected_at, **listing}


def set_hash(cards: list[dict[str, Any]]) -> str:
    """The change signal: serials and sizes (file count and total bytes), so a
    card that was written to or cleared is a change and the same card read
    twice is not."""
    parts = [[c["serial"], c.get("kind"), len(c.get("files") or []),
              sum(int(f[1]) for f in c.get("files") or [])] for c in cards]
    parts.sort()
    return hashlib.sha1(json.dumps(parts).encode("utf-8")).hexdigest()


# --------------------------------------------------------------------- loop
class SorterCards:
    """The background loop that reports this computer's cards.

    Every seam is a constructor parameter (HTTP call, volumes, clock, identity)
    so the suite needs no card reader and no dashboard, like JobRunner.
    """

    def __init__(
        self,
        cfg: dict[str, Any],
        request_fn: Optional[Callable[..., tuple[int, Any]]] = None,
        identity_token_fn: Optional[Callable[[], Optional[str]]] = None,
        volumes_fn: Optional[Callable[..., list[dict[str, Any]]]] = None,
        clock: Callable[[], float] = time.monotonic,
        machine_name: str = "",
    ) -> None:
        self.cfg = cfg if cfg is not None else {}
        self._request = request_fn
        self._identity_token_fn = identity_token_fn
        self._volumes = volumes_fn or list_volumes
        self._clock = clock
        self._machine_name = machine_name
        self.scan_seconds = config_mod.coerce_numeric(
            self.cfg, "sorter_cards_scan_seconds", SCAN_SECONDS)
        self._seen: dict[str, dict[str, Any]] = {}
        self._first_seen: dict[str, str] = {}
        self._last_hash: Optional[str] = None
        self._last_sent: Optional[float] = None
        self._backoff_until = 0.0
        self.last_status: Optional[int] = None
        self._stop = threading.Event()
        self._thread: Optional[threading.Thread] = None

    # -- config ----------------------------------------------------------
    @property
    def enabled(self) -> bool:
        return enabled(self.cfg)

    @property
    def _dashboard_url(self) -> str:
        return str(self.cfg.get("dashboard_url", "") or "").strip().rstrip("/")

    @property
    def _token(self) -> str:
        return str(self.cfg.get("dashboard_token", "") or "").strip()

    @property
    def machine(self) -> str:
        return self._machine_name or platform.node()

    def _headers(self) -> dict[str, str]:
        identity = ""
        if self._identity_token_fn is not None:
            try:
                identity = str(self._identity_token_fn() or "")
            except Exception:                                 # noqa: BLE001
                log.debug("sorter cards: identity_token_fn failed", exc_info=True)
        return {"Content-Type": "application/json",
                "X-CCSync-Token": self._token,
                "X-CCSync-Identity": identity}

    # -- the loop --------------------------------------------------------
    def start(self) -> None:
        if self._thread is not None or not self.enabled:
            return
        self._stop.clear()
        self._thread = threading.Thread(target=self._loop, name="ccsync-sorter-cards",
                                        daemon=True)
        self._thread.start()

    def stop(self) -> None:
        self._stop.set()
        thread, self._thread = self._thread, None
        if thread is not None:
            thread.join(timeout=5.0)

    def _loop(self) -> None:
        while not self._stop.is_set():
            try:
                self.tick()
            except Exception:                                 # noqa: BLE001
                log.exception("sorter cards: the tick failed")
            self._stop.wait(max(1.0, float(self.scan_seconds)))

    def current_cards(self) -> list[dict[str, Any]]:
        """Look at the readers; -> the card objects, re-reading only what
        moved. A volume being copied from is not touched: its last listing is
        reused."""
        now = self._clock()
        busy = busy_roots()
        # "local": removable AND fixed volumes. The tray watched both
        # (WatchDriveTypes = Removable, Fixed) because CFexpress / Blackmagic
        # readers present cards as fixed; the content check gates (describe).
        vols = self._volumes("local", busy)
        written = dest_busy_roots()
        present: dict[str, dict[str, Any]] = {}
        for vol in vols:
            if vol.get("system"):
                continue                       # the disk Windows lives on is never a card
            serial = vol["serial"]
            note_drive(serial, vol["root"])
            sig = (vol["root"], vol.get("capacity"), vol.get("free"))
            seen = self._seen.get(serial)
            settled = seen is not None and (seen["card"] is not None or seen["misses"] >= SLOW_MOUNT_RETRIES)
            fresh = (seen is not None and seen["sig"] == sig and settled
                     and now - seen["at"] < RELIST_SECONDS)
            if seen is not None and _root_key(vol["root"]) in written:
                fresh = True                   # a copy is writing to it: see _dest_busy
            if not fresh:
                first = self._first_seen.setdefault(serial, _now_iso())
                card = describe(vol, first)
                misses = 0 if card is not None else (seen["misses"] + 1 if seen is not None and seen["sig"] == sig else 1)
                seen = {"sig": sig, "at": now, "card": card, "misses": misses}
                self._seen[serial] = seen
            present[serial] = seen
        for serial, seen in list(self._seen.items()):
            if serial in present or seen.get("card") is None:
                continue
            if seen["sig"][0] in busy:
                present[serial] = seen          # being copied from: reuse
        for serial in list(self._seen):
            if serial not in present:
                self._seen.pop(serial, None)
                self._first_seen.pop(serial, None)
        cards = [s["card"] for s in present.values() if s.get("card")]
        cards.sort(key=lambda c: (c["drive"], c["serial"]))
        return cards

    def tick(self) -> Optional[int]:
        """One pass: look, and post when it is time. -> the HTTP status of the
        post, or None when nothing was sent."""
        if not self.enabled or not self._dashboard_url or not self._token:
            return None
        now = self._clock()
        if now < self._backoff_until:
            return None
        cards = self.current_cards()
        digest = set_hash(cards)
        due = (self._last_hash is None or digest != self._last_hash
               or (cards and self._last_sent is not None
                   and now - self._last_sent >= RESEND_SECONDS))
        if not due:
            return None
        return self._post(cards, digest, now)

    def _post(self, cards: list[dict[str, Any]], digest: str, now: float) -> Optional[int]:
        request = self._request
        if request is None:
            from .broll_ingest import default_request
            request = default_request
        body = {"cards": cards, "machine": self.machine}
        try:
            status, _parsed = request("POST", f"{self._dashboard_url}{AGENT_PATH}",
                                      body, self._headers(), POST_TIMEOUT_SECONDS)
        except Exception as exc:                              # noqa: BLE001
            log.debug("sorter cards: could not reach the dashboard (%s)", exc)
            self._backoff_until = now + 30.0
            return None
        self.last_status = int(status)
        if status in (404, 503):
            log.debug("sorter cards: the dashboard has no sorter (HTTP %s)", status)
            self._backoff_until = now + NO_SORTER_BACKOFF_SECONDS
            return int(status)
        if status in (401, 403):
            log.warning("sorter cards: the dashboard refused this computer's card "
                        "report (HTTP %s)", status)
            self._backoff_until = now + REFUSED_BACKOFF_SECONDS
            return int(status)
        if status != 200:
            log.debug("sorter cards: the card report answered HTTP %s", status)
            self._backoff_until = now + 60.0
            return int(status)
        self._last_hash, self._last_sent = digest, now
        return 200


def enabled(cfg: dict[str, Any]) -> bool:
    """`sorter_cards_enabled`, default on. Tolerates a hand-edited string."""
    raw = (cfg or {}).get("sorter_cards_enabled", True)
    if isinstance(raw, str):
        return raw.strip().lower() not in ("0", "false", "no", "off", "")
    return bool(raw)
