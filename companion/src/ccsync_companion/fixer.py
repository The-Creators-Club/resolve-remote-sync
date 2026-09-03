"""Fixer logic for OUT_OF_TREE clips — Component 2 of SPEC.md's companion app
(the non-GUI half; popup.py wires this to a tkinter dialog).

Contract, per SPEC.md:
  - destination suggested by extension (audio/stills/video-or-other).
  - destination dropdown lists existing directories under local_root (minus
    any "Proxy" dirs) plus the type defaults; free text is allowed by popup.
  - "Fix all": copy file to local_root/<dest>/<filename>, collision -> append
    " (2)", " (3)", ... then relink via mediaPoolItem.ReplaceClip(new_path).
  - Never delete/move the original — copy only, even on ReplaceClip failure.
  - "Ignore": per-session suppression, keyed by normalized path.
"""

from __future__ import annotations

import json
import logging
import os
import re
import shutil
import threading
import time
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable, Iterable, Optional

from . import canon
from . import ui_copy
from . import resolve_bridge
from .sync.rclone_lane import nfc_key

log = logging.getLogger("ccsync.fixer")

AUDIO_EXTS = {".wav", ".mp3", ".aif", ".aiff", ".flac", ".m4a", ".ogg"}
IMAGE_EXTS = {".png", ".jpg", ".jpeg", ".tif", ".tiff", ".psd", ".exr"}

_TOKEN_RE = re.compile(r"[A-Za-z0-9]+")
_YEAR_RE = re.compile(r"^(19|20)\d{2}$")


# Both files live under <log dir>/state/. Deliberately NOT beside config.toml
# where APP-3 moved the two safety latches: deleting either of these costs the
# editor nothing worse than being re-offered clips they had dismissed, which is
# the safe direction, and neither is a latch only a human may clear.
FIXER_IGNORES_FILENAME = "fixer_ignores.json"
SKIPPED_CLIPS_FILENAME = "skipped_clips.json"

# Ceiling on the persisted skip ledger. It is a RECORD, not a suppression list
# (see IgnoreTracker.ignore), so losing the oldest entries costs a count, never
# a decision -- and an editor cutting from a 40 000-file stock library must not
# be able to grow a JSON file in ~/.ccsync without bound.
_MAX_SKIPPED_RECORDED = 5000


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _read_json(path: Path) -> dict[str, Any]:
    """Whatever is on disk, or {}. A corrupt or unreadable file is not worth
    a failed poll: the cost of answering {} is that some dismissed clips are
    offered again, and that is the direction this has to fail in."""
    try:
        with open(path, "r", encoding="utf-8") as fh:
            data = json.load(fh)
        return data if isinstance(data, dict) else {}
    except FileNotFoundError:
        return {}
    except Exception:
        log.warning("could not read %s -- starting from empty", path, exc_info=True)
        return {}


def _write_json_atomic(path: Path, payload: dict[str, Any]) -> bool:
    """tmp + os.replace, the identity.py shape. Never raises: a machine that
    cannot write its state dir still has a working session-level tracker."""
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        tmp = path.with_name(path.name + ".tmp")
        with open(tmp, "w", encoding="utf-8") as fh:
            json.dump(payload, fh, indent=2)
            fh.flush()
            os.fsync(fh.fileno())
        os.replace(tmp, path)
        return True
    except Exception:
        log.warning("could not write %s", path, exc_info=True)
        return False


def _folder_of(path: str) -> str:
    r"""The directory part, in the spelling THIS path is written in (CR-90 /
    canon.plat_for: a canonical `P:\...` string reaching a Mac must not be
    dirname'd by posixpath, which would answer the whole string)."""
    return canon.plat_for(path).dirname(str(path or ""))


class IgnoreTracker:
    """Suppression for out-of-tree clips, in two layers.

    Layer 1 is the per-SESSION set SPEC.md describes: SKIP FOR NOW, keyed by
    normalized path, gone when the process is. Layer 2 (RES-12, resilience
    sweep 2026-08-28) is the persisted FOLDER list an editor who keeps a
    personal stock library outside the tree can set once instead of dismissing
    the same 300 clips at every start; it is undone from the Settings window's
    [ FORGET ] and nowhere else.

    Alongside both, a persisted LEDGER of what has been skipped
    (`skipped_clips.json`, UX-4). That ledger suppresses nothing -- the button
    still says "this session" and still means it. It exists so a tray restart
    does not erase the fact that 40 clips on this machine are not syncing, and
    so `sync_guard.resolve_health` and the tray line can say so.

    Thread-safe: the watcher thread reads `is_ignored` on every poll while a
    popup thread writes through `ignore`/`ignore_folder`.
    """

    def __init__(self, state_dir: Optional[Any] = None) -> None:
        self._ignored: set[str] = set()
        self._lock = threading.RLock()
        self._state_dir = Path(state_dir) if state_dir else None
        self._folders: list[dict[str, Any]] = []
        self._skipped: dict[str, dict[str, Any]] = {}
        self._load()

    # -- persistence ---------------------------------------------------
    @property
    def folders_path(self) -> Optional[Path]:
        return None if self._state_dir is None else self._state_dir / FIXER_IGNORES_FILENAME

    @property
    def skipped_path(self) -> Optional[Path]:
        return None if self._state_dir is None else self._state_dir / SKIPPED_CLIPS_FILENAME

    def _load(self) -> None:
        if self._state_dir is None:
            return
        folders = _read_json(self.folders_path).get("folders")
        if isinstance(folders, list):
            self._folders = [
                {
                    "folder": str(entry.get("folder") or ""),
                    "reason": str(entry.get("reason") or ""),
                    "when": str(entry.get("when") or ""),
                }
                for entry in folders
                if isinstance(entry, dict) and str(entry.get("folder") or "").strip()
            ]
        clips = _read_json(self.skipped_path).get("clips")
        if isinstance(clips, dict):
            self._skipped = {
                str(key): {
                    "path": str((value or {}).get("path") or ""),
                    "when": str((value or {}).get("when") or ""),
                    "how": str((value or {}).get("how") or "skip"),
                }
                for key, value in clips.items()
                if isinstance(value, dict)
            }

    def _save_folders(self) -> bool:
        path = self.folders_path
        if path is None:
            return False
        return _write_json_atomic(path, {"folders": self._folders})

    def _save_skipped(self) -> bool:
        path = self.skipped_path
        if path is None:
            return False
        return _write_json_atomic(path, {"clips": self._skipped})

    # -- session layer -------------------------------------------------
    def is_ignored(self, path: str) -> bool:
        with self._lock:
            if resolve_bridge._norm_path(path) in self._ignored:
                return True
            return self._folder_ignored_locked(path)

    def ignore(self, path: str, how: str = "skip") -> None:
        """SKIP FOR NOW: suppress for THIS session, and record it for ever.

        The record is not the suppression (UX-4): an editor who restarts the
        tray is offered the clip again, exactly as the button's label
        promises. What survives is the COUNT, which is the only way anyone --
        the editor at the tray line, the owner on the fleet grid -- learns
        that this machine holds media that will never reach the server.
        """
        key = resolve_bridge._norm_path(path)
        with self._lock:
            self._ignored.add(key)
            if self._state_dir is None or not str(path or "").strip():
                return
            record = self._skipped.get(key)
            if record is not None:
                record["when"] = _now_iso()
                record["how"] = str(how or "skip")
            else:
                if len(self._skipped) >= _MAX_SKIPPED_RECORDED:
                    oldest = min(self._skipped,
                                 key=lambda k: self._skipped[k].get("when") or "")
                    self._skipped.pop(oldest, None)
                self._skipped[key] = {"path": str(path), "when": _now_iso(),
                                      "how": str(how or "skip")}
            self._save_skipped()

    def clear(self) -> None:
        """Forget the SESSION skips. Nothing persisted is touched.

        APP-2 (resilience sweep 2026-08-28): "Scan whole project" is the
        explicit "show me everything", so it calls this first -- an editor who
        pressed SKIP FOR NOW at nine o'clock used to get "all media is in the
        tree" from the scan at noon, with 65 clips hidden behind a set nothing
        in the product could clear short of restarting the tray. The persisted
        FOLDER ignores are deliberately NOT cleared here: those are a standing
        decision with a [ FORGET ] of their own, not a dismissal.
        """
        with self._lock:
            self._ignored.clear()

    def session_count(self) -> int:
        with self._lock:
            return len(self._ignored)

    def skipped_count(self) -> int:
        """How many distinct clips have EVER been skipped on this machine."""
        with self._lock:
            return len(self._skipped)

    # -- folder layer (RES-12) -----------------------------------------
    def _folder_ignored_locked(self, path: str) -> bool:
        text = str(path or "")
        if not text:
            return False
        for entry in self._folders:
            folder = entry.get("folder") or ""
            if folder and canon._is_under(text, folder, canon.plat_for(text)):
                return True
        return False

    def folders(self) -> list[dict[str, Any]]:
        with self._lock:
            return [dict(entry) for entry in self._folders]

    def folder_count(self) -> int:
        with self._lock:
            return len(self._folders)

    def ignore_folder(self, folder: str, reason: str = "") -> bool:
        """"Always leave clips in this folder alone on this machine."

        Returns False when there is nowhere to persist it: a decision that
        says "always" and survives only until the next restart is worse than
        no button at all, so the caller is told rather than the editor being
        left to find out in a month.
        """
        text = str(folder or "").strip()
        if not text:
            return False
        with self._lock:
            key = canon.norm(text)
            if any(canon.norm(e.get("folder") or "") == key for e in self._folders):
                return True
            self._folders.append({"folder": text, "reason": str(reason or ""),
                                  "when": _now_iso()})
            if not self._save_folders():
                self._folders = [e for e in self._folders
                                 if canon.norm(e.get("folder") or "") != key]
                return False
        return True

    def forget_folder(self, folder: str) -> bool:
        """Undo one [ ALWAYS LEAVE THIS FOLDER ALONE ]. The clips come back on
        the next poll, which is the whole point of the button."""
        key = canon.norm(str(folder or ""))
        with self._lock:
            before = len(self._folders)
            self._folders = [e for e in self._folders
                             if canon.norm(e.get("folder") or "") != key]
            if len(self._folders) == before:
                return False
            self._save_folders()
        return True


def classify_ext(path: str) -> str:
    ext = os.path.splitext(path)[1].lower()
    if ext in AUDIO_EXTS:
        return "audio"
    if ext in IMAGE_EXTS:
        return "image"
    return "other"  # video + anything else share the same default per SPEC.md


def suggest_destination(path: str, editor_name: str, project_prefix: str = "") -> str:
    """Return a local_root-relative destination dir, '/'-separated.

    audio -> "Audio/Music"
    still image -> "B-roll/Stills"
    video / other -> "B-roll/Editor Added/<editor_name>"

    `project_prefix` (e.g. "Projects/2025/FF4/Nuclear") is prepended when
    set — destinations must land INSIDE the active project, not at the
    Creators_Club root, or editor media uploads to an orphan path on the
    NAS that no Resolve project references.
    """
    kind = classify_ext(path)
    if kind == "audio":
        dest = "Audio/Music"
    elif kind == "image":
        dest = "B-roll/Stills"
    else:
        editor = editor_name or "Unknown"
        dest = f"B-roll/Editor Added/{editor}"
    prefix = (project_prefix or "").strip("/").replace("\\", "/")
    return f"{prefix}/{dest}" if prefix else dest


def _tokenize(text: str) -> set[str]:
    """Lowercase alnum-only tokens, split on any run of non-alnum chars."""
    return {t.lower() for t in _TOKEN_RE.findall(text or "")}


def match_project_dir(resolve_project_name: str, project_rel_paths: list[str]) -> Optional[str]:
    """Best-effort match of the LIVE Resolve project name to one of the
    tree's Projects/<year>/<series>/<project> directories, by token overlap.

    Both sides are normalized to lowercase alnum-only tokens (split on any
    run of non-alnum characters) before comparing. A candidate must share at
    least one NON-YEAR token with `resolve_project_name` to qualify — a
    project name that happens to contain a 4-digit year is not, by itself,
    grounds to file media under every project from that year. The candidate
    with the most overlapping tokens wins; a tie (or no qualifying
    candidate) returns None rather than guessing.

    Example: resolve_project_name="CCT Creator Profiles" matches tree dir
    "2026/Creator Profiles/Season 1" (tokens creator+profiles overlap) and
    NOT "2025/FF4/Nuclear" (no overlap).
    """
    if not resolve_project_name or not project_rel_paths:
        return None

    name_tokens = _tokenize(resolve_project_name)
    if not name_tokens:
        return None

    best_score = 0
    best_matches: list[str] = []
    for rel in project_rel_paths:
        path_tokens = _tokenize(rel)
        overlap = name_tokens & path_tokens
        # Trivial tokens never count toward a match: 4-digit years AND short
        # bare numbers ("1", "2" -- season/part counters). Without the
        # latter, "Event 1 Videos" matched ".../Season 1" on the shared "1"
        # alone (seen live 2026-07-25 on the dashboard's twin of this
        # matcher, db.match_project_label -- keep the two in sync).
        meaningful = {
            t for t in overlap if not (t.isdigit() and len(t) <= 4)
        }
        if not meaningful:
            continue
        score = len(meaningful)
        if score > best_score:
            best_score = score
            best_matches = [rel]
        elif score == best_score:
            best_matches.append(rel)

    if best_score == 0 or len(best_matches) != 1:
        return None
    return best_matches[0]


# Intentional copy of the dashboard's provision.MARKER_FILENAME convention
# (see that module's marker docs) -- markers sync to editors via lane C, so
# a local project dir self-identifies at any depth. Keep in sync.
MARKER_FILENAME = ".ccsync-project"


def list_project_dirs(local_root: str, extra_rels: Iterable[str] = ()) -> list[str]:
    """Project rel-paths ('/'-separated, sorted) under local_root/Projects.

    Since 2026-07-25 a project is any directory carrying the
    .ccsync-project marker, at ANY depth (descent prunes at markers -- no
    nested projects; hidden dirs skipped). `extra_rels` (e.g. the
    dashboard-selected rels, which are authoritative) are unioned in for
    dirs whose marker hasn't synced down yet. Tolerant of a missing/partial
    tree — never raises, just returns fewer (or no) entries.
    """
    if not local_root:
        return []
    projects_dir = Path(local_root) / "Projects"
    # bug-hunt-2026-09-03 comp-core-3 (CR-90's shape at the project-rel level):
    # the two sources spell Unicode differently -- os.walk on a Mac hands back
    # NFD, the dashboard's selection is NFC -- and the extras' only membership
    # test is is_dir(), which succeeds on APFS/HFS+ for EITHER spelling. A set
    # of raw strings therefore held one project twice, and the dashboard turned
    # the two spellings into two slugs: a real project plus a phantom, both
    # eating a slot against MAX_PROJECTS. Keyed by the folded spelling,
    # VALUED by the walked one: what is returned is the bytes on disk, because
    # callers walk these paths.
    rels: dict[str, str] = {}

    try:
        for dirpath, dirnames, filenames in os.walk(projects_dir):
            rel = Path(dirpath).relative_to(projects_dir)
            dirnames[:] = [d for d in dirnames if not d.startswith(".")]
            if rel == Path("."):
                continue
            if MARKER_FILENAME in filenames:
                rels[nfc_key(rel.as_posix())] = rel.as_posix()
                dirnames[:] = []
    except OSError:
        pass

    for extra in extra_rels or ():
        extra = str(extra).strip().strip("/")
        if not extra or nfc_key(extra) in rels:
            continue
        if (projects_dir / Path(*extra.split("/"))).is_dir():
            rels[nfc_key(extra)] = extra
    return sorted(rels.values())


def pick_project_prefix(
    resolve_project_name: str,
    project_rel_paths: list[str],
    project_prefix: str = "",
) -> str:
    """Fallback order for the popup suggestion base, per SPEC: the tree
    project dir matching the CURRENT Resolve project name -> the configured
    `active_project` (`project_prefix`) -> the tree root (no prefix, "").

    Pure — `project_rel_paths` is expected to come from list_project_dirs,
    kept as a separate argument here so this stays filesystem-free and
    trivially testable.
    """
    matched = match_project_dir(resolve_project_name, project_rel_paths)
    if matched:
        return f"Projects/{matched}"
    return project_prefix or ""


def default_destination_dirs(editor_name: str, project_prefix: str = "") -> set[str]:
    editor = editor_name or "Unknown"
    dests = {"Audio/Music", "B-roll/Stills", f"B-roll/Editor Added/{editor}"}
    prefix = (project_prefix or "").strip("/").replace("\\", "/")
    if prefix:
        dests = {f"{prefix}/{d}" for d in dests}
    return dests


def list_destination_dirs(
    local_root: str, editor_name: str, project_prefix: str = ""
) -> list[str]:
    """Existing directories under local_root ('/'-separated, relative),
    excluding any directory literally named "Proxy" (and its contents), plus
    the three type-default destinations (present even if they don't exist
    yet, so the dropdown always offers a sane choice).

    `project_prefix` (e.g. "Projects/2026/CCT/Season 1") is REQUIRED for a
    correct dropdown when one is known. popup.py used to call this with no
    prefix and a hardcoded empty editor_name, so the list offered bare
    "Audio/Music", "B-roll/Stills" and "B-roll/Editor Added/Unknown"
    alongside the correctly-prefixed suggestion -- picking one filed the
    media OUTSIDE Projects/, where _project_rel_for_path yields None, the
    watchdog drops the event and no run_once(subpath) ever covers it. The
    dialog still said "Fixed" and Resolve still played it locally, so
    nothing surfaced that the file would never reach another editor
    (AUDIT_2 CORE-H3). When a prefix is given, only directories inside it
    are offered.
    """
    dirs: set[str] = set(default_destination_dirs(editor_name, project_prefix))

    prefix = (project_prefix or "").strip("/").replace("\\", "/")
    root = Path(local_root) if local_root else None
    if root is not None and root.is_dir():
        walk_root = root / Path(*prefix.split("/")) if prefix else root
        if walk_root.is_dir():
            for dirpath, dirnames, _filenames in os.walk(walk_root):
                dirnames[:] = [d for d in dirnames if d.lower() != "proxy"]
                rel = os.path.relpath(dirpath, root)
                if rel == os.curdir:
                    continue
                dirs.add(rel.replace(os.sep, "/"))

    return sorted(dirs)


def unique_destination_path(dest_dir: Path, filename: str) -> Path:
    """Pick a non-colliding path in dest_dir for filename, appending
    " (2)", " (3)", ... before the extension as needed. Does not create
    dest_dir or the file — pure path arithmetic, easy to unit test.
    """
    stem, ext = os.path.splitext(filename)
    candidate = dest_dir / filename
    n = 2
    while candidate.exists():
        candidate = dest_dir / f"{stem} ({n}){ext}"
        n += 1
    return candidate


# Suffix for in-progress copies. Matched by the rclone filters and by
# syncthing_admin.STIGNORE_LINES so a partial never syncs anywhere.
TMP_SUFFIX = ".ccsync-tmp"

# 8 MB: big enough that the per-chunk Python overhead is noise against SMB
# throughput, small enough that a progress bar moves ~4x/second at 33 MB/s.
COPY_CHUNK_BYTES = 8 * 1024 * 1024

# Windows file attributes meaning "this file is not really on this disk".
# Cloud filesystems (Google Drive File Stream, OneDrive Files On-Demand,
# Dropbox Smart Sync) leave a placeholder and HYDRATE it -- download it --
# only when something opens it.
#
# This is the measured root cause of the live 2026-07-25 incident: the
# companion's read side matched GoogleDriveFS's read side byte for byte
# (222 MB/10 s each), i.e. FIX ALL was blocked inside open()/read() waiting
# for Drive to materialise online-only source clips. Nothing said so, so a
# working copy was indistinguishable from a hang, and the per-file byte bar
# legitimately sits at 0% for the whole hydration.
FILE_ATTRIBUTE_OFFLINE = 0x1000
FILE_ATTRIBUTE_RECALL_ON_OPEN = 0x40000
FILE_ATTRIBUTE_RECALL_ON_DATA_ACCESS = 0x400000
PLACEHOLDER_ATTRIBUTES = (
    FILE_ATTRIBUTE_OFFLINE
    | FILE_ATTRIBUTE_RECALL_ON_OPEN
    | FILE_ATTRIBUTE_RECALL_ON_DATA_ACCESS
)


def is_placeholder(path: str) -> bool:
    """True when `path` is a cloud placeholder that must be downloaded before
    it can be read. False on any platform or filesystem that doesn't report
    it -- this is a diagnostic, never a gate: a false negative just means the
    old (silent) behaviour, and a false positive must never block a copy."""
    try:
        attrs = getattr(os.stat(path), "st_file_attributes", 0)
    except (OSError, ValueError):
        return False
    return bool(attrs & PLACEHOLDER_ATTRIBUTES)


# UX-1: the route is ui_copy's to spell, so the next menu move edits one file.
PLACEHOLDER_FAILURE_MESSAGE = (
    "Google Drive (or your cloud drive) couldn't download this file. Right-click it "
    "in the Google Drive folder → \"Available offline\", wait for it to finish, then "
    f"run {ui_copy.SCAN_WHOLE_PROJECT} again."
)


def classify_copy_failure(exc: BaseException, placeholder: bool) -> str:
    """A sentence an editor can act on, instead of `FAILED`.

    The popup previously rendered failures as a bare count plus raw
    exception text (and in the no-display path, a print() that is a no-op in
    the windowed build), so the single most common real cause -- a cloud
    placeholder that never hydrated -- was completely invisible."""
    if placeholder:
        return PLACEHOLDER_FAILURE_MESSAGE
    text = str(exc)
    low = text.lower()
    if isinstance(exc, PermissionError) or "permission" in low:
        return ("Windows wouldn't let CCSync read or write this file. It may be open in "
                "another program. Close it and try again.")
    if "no space" in low or "not enough space" in low or getattr(exc, "errno", None) == 28:
        return "Your disk is full. Free up space and try again."
    if isinstance(exc, FileNotFoundError):
        return "The file isn't there any more. It may have been moved or renamed."
    if "network" in low or "semaphore" in low or "device is not ready" in low:
        return ("Lost the connection to the drive this file lives on. Reconnect it and "
                "try again.")
    return f"Couldn't copy this file: {text}"


class CopyAborted(Exception):
    """The user abandoned THIS file mid-copy ([ SKIP THIS FILE ] /
    [ CANCEL ALL ]).

    A distinct exception type, not a generic failure, because the caller owes
    the abort something a failure doesn't: the partial destination MUST be
    removed. Mid-file abort was forbidden outright until now precisely
    because an orphaned multi-GB partial is what lane C would fan out to the
    whole fleet (CORE-H5); it is allowed only in exchange for that cleanup
    (see fix_clip's abort branch)."""


def copy_with_progress(
    src,
    dst,
    on_bytes: Optional[Callable[[int, int], None]] = None,
    chunk_size: int = COPY_CHUNK_BYTES,
    should_abort: Optional[Callable[[], bool]] = None,
) -> None:
    """shutil.copy2 semantics, but reporting bytes as it goes.

    shutil.copy2 reports NOTHING, so a 40 GB BRAW over SMB parked the fixer
    dialog's "FIXING 35/69" counter for twenty-plus minutes and looked
    exactly like a hang -- which is precisely the state that makes a user
    force-quit, and per CORE-H5 a force-quit mid-copy leaves a multi-GB
    partial behind (AUDIT_2 UX-9; hit live 2026-07-25 at 35/69).

    `on_bytes(copied, total)` is called after every chunk AND once at zero
    before the first read, so a caller can render "0 of 12.7 GB" immediately
    rather than showing an empty bar until the first chunk lands. It must be
    cheap and must not raise; exceptions from it are swallowed rather than
    failing a copy that is otherwise fine.

    `should_abort()` is polled ONCE PER CHUNK (and once before the first
    read). A chunk is 8 MB, so the button the user just clicked responds
    inside a second on any real link. When it returns True the copy stops and
    CopyAborted is raised AFTER both file handles are closed -- raising from
    inside the `with` would leave the caller trying to unlink `dst` while a
    Windows handle to it is still open, which fails with "in use by another
    process" and strands exactly the partial the abort exists to remove. Like
    `on_bytes` it must be cheap and must not raise; an exception from it is
    swallowed and read as "don't abort" (never abandon a copy because a UI
    predicate misbehaved).

    Metadata is copied with copystat afterwards, matching copy2. The source
    is opened read-only and never modified.
    """
    try:
        total = os.path.getsize(src)
    except OSError:
        total = 0

    def report(done: int) -> None:
        if on_bytes is None:
            return
        try:
            on_bytes(done, total)
        except Exception:
            log.debug("copy progress callback failed", exc_info=True)

    def aborting() -> bool:
        if should_abort is None:
            return False
        try:
            return bool(should_abort())
        except Exception:
            log.debug("copy abort callback failed", exc_info=True)
            return False

    copied = 0
    aborted = False
    report(0)
    with open(src, "rb") as fsrc, open(dst, "wb") as fdst:
        while True:
            if aborting():
                aborted = True
                break
            chunk = fsrc.read(chunk_size)
            if not chunk:
                break
            fdst.write(chunk)
            copied += len(chunk)
            report(copied)
    if aborted:
        # Handles are closed by now (see above) -- the caller can unlink.
        raise CopyAborted(f"copy of {src} abandoned by the user after {copied} bytes")
    # copy2 == copyfile + copystat (mtime/atime/mode/flags).
    shutil.copystat(src, dst)
# Stale-tmp sweep age: anything younger might be an in-flight copy from a
# concurrent FIX ALL (or another companion mid-restart).
STALE_TMP_AGE_SECONDS = 3600.0

# How long the `.ccsync-tmp` beside a 0-byte reservation must have gone
# UNTOUCHED before the reservation counts as crash residue rather than an
# in-flight copy (COMP-GUARD-1, 2026-08-14). Seconds, deliberately not the
# hour above: lane A picks the reservation up --min-age 120s after it is
# created and --ignore-existing then makes the empty file permanent on the
# NAS, so a sweep that waits an hour is a sweep that always loses the race.
# A live copy rewrites its tmp continuously, so an idle one is a dead one.
RESERVATION_IDLE_SECONDS = 30.0

# `<final name>.<pid>-<uuid8>.ccsync-tmp` -- the name fix_clip builds (the
# pid+uuid half is AUDIT_2 CORE-M1's fix for two overlapping FIX ALLs).
_RESERVATION_TMP_RE = re.compile(
    r"^(?P<final>.+)\.(?P<pid>\d+)-[0-9a-f]+" + re.escape(TMP_SUFFIX) + r"$"
)


def reserved_name_for_tmp(tmp_path: str) -> tuple[Optional[str], Optional[int]]:
    """(final destination path, writing pid) for one `*.ccsync-tmp`, or
    (None, None) when the name is not one fix_clip built.

    The tmp is `<final>.<pid>-<uuid8>.ccsync-tmp` and the final name is the
    O_EXCL reservation _claim_destination_path created BEFORE the copy
    started -- which is the whole point: the pair identifies both halves of
    one interrupted fix_clip. Older, pre-CORE-M1 tmps carry no pid segment
    and are deliberately not matched: without it there is nothing tying the
    tmp to a specific writer."""
    directory, name = os.path.split(str(tmp_path))
    m = _RESERVATION_TMP_RE.match(name)
    if not m:
        return None, None
    try:
        pid = int(m.group("pid"))
    except ValueError:
        return None, None
    return os.path.join(directory, m.group("final")), pid


def _claim_destination_path(dest_dir: Path, filename: str) -> Path:
    """Pick a non-colliding name AND create it atomically (O_CREAT|O_EXCL),
    so the name is ours from this instant on.

    unique_destination_path() alone is TOCTOU: the name was chosen, then a
    multi-GB copy ran for minutes, and only then did os.replace() land --
    silently clobbering whatever had arrived at that exact path meanwhile.
    Lane C syncing down a DIFFERENT track.wav from another editor into
    Audio/Music during the copy is the concrete case, and Syncthing then
    propagates the overwrite fleet-wide (AUDIT_2 DEL-7). Creating the final
    name up front makes the collision loop authoritative: no second writer
    can pick the same name, because it already exists.

    Raises OSError if a slot can't be claimed."""
    stem, ext = os.path.splitext(filename)
    n = 1
    while True:
        candidate = dest_dir / (filename if n == 1 else f"{stem} ({n}){ext}")
        try:
            fd = os.open(str(candidate), os.O_CREAT | os.O_EXCL | os.O_WRONLY)
        except FileExistsError:
            n += 1
            if n > 10000:
                raise OSError(f"could not find a free name for {filename} in {dest_dir}")
            continue
        os.close(fd)
        return candidate


def walk_ccsync_tmp_files(local_root: str) -> list[tuple[float, str]]:
    """(mtime, path) for every `*.ccsync-tmp` under local_root, oldest first.

    Split out so the two sweeps below -- stale partials and orphaned name
    reservations -- share ONE walk of the tree at startup instead of two
    (COMP-GUARD-1, 2026-08-14). Never raises; an unreadable tree is [].
    """
    found: list[tuple[float, str]] = []
    if not str(local_root).strip():
        return []
    try:
        for dirpath, dirnames, filenames in os.walk(local_root):
            dirnames[:] = [d for d in dirnames if not d.startswith(".")]
            for name in filenames:
                if not name.endswith(TMP_SUFFIX):
                    continue
                full = os.path.join(dirpath, name)
                try:
                    stat = os.stat(full)
                except OSError:
                    continue
                found.append((stat.st_mtime, full))
    except Exception:
        log.debug("stale .ccsync-tmp walk failed under %s", local_root, exc_info=True)
        return []
    found.sort()
    return found


def sweep_orphan_reservations(
    local_root: str,
    idle_seconds: float = RESERVATION_IDLE_SECONDS,
    now_fn: Callable[[], float] = time.time,
    tmp_files: Optional[list[tuple[float, str]]] = None,
) -> list[str]:
    """DELETE the 0-byte final names stranded beside an interrupted copy.

    fix_clip reserves the FINAL destination name with O_CREAT|O_EXCL before
    the multi-GB copy starts (DEL-7's fix for the TOCTOU that let lane C land
    on that exact path mid-copy) and removes it on both of its failure exits
    -- but a process that simply DIES (self-upgrade shutdown, reboot, Quit,
    force-quit, power loss) removes nothing, and the tmp sweep above has
    never known reservations existed (COMP-GUARD-1, 2026-08-14).

    The residue is a real video-extension file: lane A's up-filter matches
    it, --min-age 120s releases it, and --ignore-existing then guarantees the
    real bytes can NEVER replace it on the NAS -- from where lane C fans the
    0-byte clip out to every editor, and the 2026-08-11 ignoreDelete retrofit
    makes it effectively immortal (R5/R15). The editor's next FIX ALL files
    the real copy as `<name> (2).ext`, so the project keeps the empty one.

    THE ONE DELETION THIS MODULE MAKES UNPROMPTED, and deliberately the
    narrowest possible: the file must be exactly 0 bytes (the same "provably
    not the editor's data" test remove_reserved_name applies), must sit
    beside OUR `<name>.<pid>-<uuid>.ccsync-tmp` for that same name, that tmp
    must have gone untouched for `idle_seconds` (a live copy rewrites it
    continuously), and the pid must not be this process. Anything else is
    logged and left alone. Returns the paths removed; never raises.
    """
    if not str(local_root).strip():
        return []
    if tmp_files is None:
        tmp_files = walk_ccsync_tmp_files(local_root)
    now = now_fn()
    my_pid = os.getpid()
    removed: list[str] = []
    for mtime, tmp in tmp_files:
        if (now - mtime) < idle_seconds:
            continue
        final, pid = reserved_name_for_tmp(tmp)
        if final is None:
            continue
        if pid == my_pid:
            # This process's own FIX ALL, stalled but alive. Its reservation
            # is the thing keeping the name ours.
            continue
        try:
            stat = os.stat(final)
        except OSError:
            continue
        if stat.st_size:
            log.info(
                "leftover reservation %s is not empty, so it is not ours to remove "
                "-- left in place", final,
            )
            continue
        try:
            os.remove(final)
        except OSError as exc:
            log.warning(
                "COULD NOT REMOVE the empty placeholder file at %s (%s) -- delete it "
                "by hand; a 0-byte file under that name uploads to the server and "
                "--ignore-existing means the real footage can never replace it",
                final, exc,
            )
            continue
        removed.append(final)
        log.warning(
            "removed the 0-byte placeholder an interrupted FIX ALL left under the "
            "final name: %s (its half-copied %s is reported above, NOT deleted)",
            final, os.path.basename(tmp),
        )
    return removed


def sweep_stale_tmp_files(
    local_root: str,
    max_age_seconds: float = STALE_TMP_AGE_SECONDS,
    now_fn: Callable[[], float] = time.time,
    tmp_files: Optional[list[tuple[float, str]]] = None,
) -> list[str]:
    """REPORT (do not delete) leftover `*.ccsync-tmp` files under local_root.

    A FIX ALL killed mid-copy (self-upgrade shutdown, reboot, Quit) leaves a
    partial multi-GB file behind and nothing ever cleaned it up (AUDIT_2
    CORE-H5). The `.stignore`/rclone-filter half of that fix landed in
    sync/, so these no longer sync anywhere -- which leaves only the wasted
    disk space, and that is not worth weighing against the hard "never
    delete user data" rule. DELIBERATE CHOICE: this reports and logs; it
    does not unlink. A partial BRAW is still the editor's data, we cannot
    prove from the filesystem alone that some other process isn't writing
    it, and an automatic delete here would be the system's only unprompted
    removal of a file under local_root.

    The 0-byte final-name RESERVATION the same interrupted copy leaves is a
    different animal and has its own sweep -- see sweep_orphan_reservations.

    Returns the paths found (oldest first). Never raises."""
    if not str(local_root).strip():
        return []
    if tmp_files is None:
        tmp_files = walk_ccsync_tmp_files(local_root)
    now = now_fn()
    found = [
        (mtime, path) for mtime, path in tmp_files
        if (now - mtime) >= max_age_seconds
    ]
    for mtime, path in found:
        log.warning(
            "leftover partial copy from an interrupted FIX ALL: %s (%.1f MB, last written %s) "
            "-- NOT deleted; remove it by hand once you're sure nothing is using it",
            path, os.path.getsize(path) / 1_000_000 if os.path.exists(path) else 0,
            time.strftime("%Y-%m-%d %H:%M", time.localtime(mtime)),
        )
    return [path for _mtime, path in found]


def remove_partial(path: Path) -> Optional[str]:
    """Delete one artifact of an aborted copy. Returns None when the file is
    gone (including "was never there"), or the path as a string when it could
    NOT be removed.

    Best-effort-but-LOUD, and never raises: this is the whole price of
    allowing a mid-file abort at all. A partial that survives is a multi-GB
    file sitting under a final name inside local_root, which lane A would
    upload and lane C would fan out to the fleet (CORE-H5) -- so if it can't
    be removed the caller must say so to the user rather than reporting a
    tidy "skipped"."""
    try:
        path = Path(path)
        if not path.exists():
            return None
        path.unlink()
        log.info("removed the partial copy left by an abandoned file: %s", path)
        return None
    except Exception as exc:
        log.warning(
            "COULD NOT REMOVE the half-copied file at %s (%s) -- delete it by hand; "
            "until you do it wastes the space and may upload to the server", path, exc,
        )
        return str(path)


def remove_reserved_name(path: Path) -> Optional[str]:
    """Remove the 0-byte final name _claim_destination_path reserved, after
    an aborted copy. Same return contract as remove_partial().

    ONLY when it is still empty. DEL-7's whole point is that another writer
    can land on that exact path -- lane C syncing down a same-named file from
    another editor is the concrete case -- and this module's hardest rule is
    that it never deletes data it did not write. A non-empty file under our
    reserved name is therefore left alone and logged: it is not our partial.
    Never raises."""
    try:
        path = Path(path)
        if not path.exists():
            return None
        if path.stat().st_size:
            log.warning(
                "aborted copy: %s is not empty, so it is NOT ours to delete "
                "(something else wrote there during the copy) -- left in place", path,
            )
            return None
        path.unlink()
        log.info("removed the reserved name left by an abandoned copy: %s", path)
        return None
    except Exception as exc:
        log.warning(
            "COULD NOT REMOVE the empty placeholder file at %s (%s) -- delete it by "
            "hand; a 0-byte file under that name would upload to the server", path, exc,
        )
        return str(path)


def reclaim_if_reservation_lost(dest_dir: Path, dest_path: Path,
                                filename: str) -> Path:
    """The reservation re-check, run AFTER the copy and BEFORE os.replace.

    `_claim_destination_path` creates the final name with O_EXCL before the
    copy starts, which is what makes the collision loop authoritative
    (DEL-7). It does not, and cannot, stop a writer that ignores the
    reservation: rclone and Syncthing both overwrite a 0-byte file happily,
    and a multi-GB copy gives lane B/C minutes to do it. os.replace() would
    then silently destroy whatever arrived -- the exact outcome the O_EXCL
    claim was added to prevent, one step later in the sequence
    (COMMERCIAL_READINESS.md item 9, 2026-08-17).

    So: if the reserved name is still the empty file we made, it is ours and
    the caller replaces into it. Anything else -- content, or gone entirely --
    means the claim did not hold, and a FRESH name is claimed instead. The
    copy lands beside the arrival under `name (2).ext` rather than on top of
    it, and the relink follows the returned path.
    """
    try:
        if dest_path.exists() and dest_path.stat().st_size == 0:
            return dest_path
    except OSError:
        # Cannot tell (an SMB blip mid-copy) -- treat the claim as lost. A
        # spare copy beside the original costs disk; a wrong os.replace costs
        # somebody else's file.
        log.warning("fix_clip: could not re-check the reserved name %s -- claiming a "
                    "fresh one rather than replacing into it", dest_path)
    else:
        log.warning(
            "fix_clip: %s is no longer the empty name CCSync reserved (something "
            "else wrote or removed it during the copy) -- putting our copy under a "
            "new name instead of overwriting it", dest_path,
        )
    return _claim_destination_path(dest_dir, filename)


def sample_source(src: Any) -> Optional[tuple[int, float]]:
    """(size, mtime) for the source, or None when it cannot be read.

    Taken BEFORE the copy so verify_copy() can tell "we copied it wrong" from
    "it changed while we copied"."""
    try:
        stat = os.stat(src)
        return (int(stat.st_size), float(stat.st_mtime))
    except OSError:
        return None


def verify_copy(src: Any, dest_path: Any,
                src_before: Optional[tuple[int, float]] = None) -> Optional[str]:
    """None when `dest_path` is a faithful copy of `src`, else why not.

    Checked BEFORE the ReplaceClip, because relinking Resolve to a truncated
    file is worse than not relinking at all: the clip goes from "offline, and
    the editor knows" to "online, and wrong", and lane A then uploads the
    truncation under a name it can never replace (`--ignore-existing`).

    Size is the signal for the copy itself. `src_before` catches the other
    failure -- a source still being written (a card mid-ingest, a download in
    flight): sizes can agree by luck, but the mtime moving means the bytes we
    read were a snapshot of something unfinished. Both come back as a failed
    fix and the caller removes what it wrote.
    (COMMERCIAL_READINESS.md item 9, 2026-08-17.)
    """
    try:
        src_stat = os.stat(src)
        dest_stat = os.stat(dest_path)
    except OSError as exc:
        return f"the copy could not be checked ({exc})"
    if src_stat.st_size == 0:
        return "the original is empty"
    if src_stat.st_size != dest_stat.st_size:
        return (f"the copy is {dest_stat.st_size} bytes of a {src_stat.st_size}-byte "
                f"original -- it was cut short")
    if src_before is not None:
        before_size, before_mtime = src_before
        if before_size != src_stat.st_size or before_mtime != src_stat.st_mtime:
            return ("the original changed while it was being copied -- it is still "
                    "being written. Try again once it has finished")
    return None


def _dest_dir_is_contained(dest_dir: Path, local_root_resolved: Path,
                           dest_rel: str | None = None) -> bool:
    """True iff `dest_dir`, once resolved, is local_root itself or somewhere
    under it. dest_rel is free text from an editable combobox (popup.py) --
    an absolute path, a drive-relative "\\Escaped\\Dir" (pathlib re-roots on
    the current drive when the right-hand side starts with a separator), or
    a "..\\..\\" traversal must all be rejected rather than silently copied
    (and Resolve relinked) outside the tree (AUDIT D-6).

    Pass `dest_rel` (the un-joined right-hand side) wherever it is available:
    a drive-rooted spelling like "C:/Windows/Temp" is caught by pathlib's
    re-rooting on Windows, but on posix it is an ordinary relative directory
    name, so the join lands INSIDE the tree and this check would approve it.
    The spelling has to be refused before the join (MAC-3, 2026-08-04)."""
    if dest_rel is not None and canon.is_drive_rooted(dest_rel):
        return False
    try:
        resolved = dest_dir.resolve()
    except OSError:
        return False
    try:
        common = os.path.commonpath(
            [os.path.normcase(str(resolved)), os.path.normcase(str(local_root_resolved))]
        )
    except ValueError:
        # Different drives (e.g. dest resolves onto C: while local_root is
        # on T:) -- os.path.commonpath raises rather than returning "".
        return False
    return common == os.path.normcase(str(local_root_resolved))


def canonical_clip_path(dest_path: Any, local_root: str, canonical_prefix: str) -> str:
    """The path to STORE IN RESOLVE for a file that physically lives at
    `dest_path` under `local_root`.

    Resolve project databases travel between machines, but local_root does
    not: an editor's tree is D:\\Creators_Club while the base rig's is P:\\
    directly -- only the canonical P:\\ drive resolves everywhere (SPEC's
    path canon). Relinking to the PHYSICAL path meant a clip fixed on the
    laptop opened as offline on every other machine (seen live 2026-07-26).
    Falls back to the physical path when no prefix is configured or the
    file isn't under local_root; when canonical_prefix IS local_root (the
    base rig) this is the identity.

    canon.local_to_canonical owns the spelling: joining the prefix to the
    relative part with the HOST separator emits `P:\\Projects/2026/x.braw` on
    a Mac, and that mixed spelling goes straight into every other machine's
    project database via ReplaceClip."""
    return canon.local_to_canonical(dest_path, local_root, canonical_prefix)


# `fixer_dry_run` from config.toml, resolved ONCE per process and cached.
# Read here rather than threaded down from CompanionApp because every caller
# of fix_clip -- popup.perform_fix_all, consolidate, the tests' doubles --
# would otherwise need a new kwarg, and a rehearsal switch that only some
# call sites honour is worse than none (item 9, 2026-08-17).
_dry_run_default: Optional[bool] = None


def dry_run_default() -> bool:
    """Is FIX ALL in rehearsal mode on this machine?"""
    global _dry_run_default
    if _dry_run_default is None:
        try:
            from . import config as config_mod
            _dry_run_default = bool(config_mod.load_config().get("fixer_dry_run", False))
        except Exception:
            _dry_run_default = False
        if _dry_run_default:
            log.warning("fixer_dry_run = true: FIX ALL will report its plan and copy "
                        "NOTHING until that setting is removed from config.toml")
    return _dry_run_default


def reset_dry_run_cache() -> None:
    """Forget the cached `fixer_dry_run` answer (tests, and a config reload)."""
    global _dry_run_default
    _dry_run_default = None


def _relink_for_fix_all(media_pool_item, new_path: str) -> dict[str, Any]:
    """fix_clip's default relinker. Named so the undo journal can say WHICH
    of the companion's four media-pool writers made an entry (item 9)."""
    return resolve_bridge.replace_clip(media_pool_item, new_path, source="fix-all")


def fix_clip(
    file_path: str,
    dest_rel: str,
    local_root: str,
    media_pool_items: Any,
    copy_fn=None,
    replace_clip_fn=_relink_for_fix_all,
    on_bytes: Optional[Callable[[int, int], None]] = None,
    should_abort: Optional[Callable[[], bool]] = None,
    canonical_prefix: str = "",
    dry_run: Optional[bool] = None,
) -> dict[str, Any]:
    """Copy `file_path` into local_root/dest_rel (collision-safe) once, then
    relink EVERY DISTINCT media pool item in `media_pool_items` to that one
    copy via ReplaceClip.

    `media_pool_items` may be a single item (back-compat with callers/tests
    that only ever deal with one) or a list — the same source file can be
    referenced by several timeline items (e.g. the same clip cut onto
    multiple places in the sequence), and popup.py collapses those into one
    row per unique path (see popup.dedupe_out_of_tree_items) by TIMELINE
    OCCURRENCE, not by underlying MediaPoolItem -- a clip cut in 50 times
    would otherwise trigger 50 identical ReplaceClip calls, each forcing a
    re-conform (AUDIT §6). De-duplicate here by object identity (id()) so
    each distinct item is relinked exactly once.

    Returns {"ok": bool, "message": str, "copied_to": Optional[str]}. Never
    raises — every failure path (missing source, copy error, ReplaceClip
    failure) is reported in the returned dict. The original file at
    `file_path` is NEVER deleted or moved, regardless of outcome.

    `on_bytes(copied, total)` reports progress DURING the copy (UX-9); it is
    only consulted by the default copier. `copy_fn` (a 2-arg src/dst
    callable) overrides the copier entirely, for tests.

    `should_abort()` is the [ SKIP THIS FILE ] / [ CANCEL ALL ] predicate,
    polled per chunk by the default copier. On abort NOTHING is relinked (no
    ReplaceClip), BOTH artifacts of the attempt are deleted -- the partial
    `.ccsync-tmp` and the 0-byte O_EXCL name reservation -- and the result
    comes back as {"ok": False, "aborted": True}, i.e. a third outcome that
    is neither fixed nor failed. `leftover_paths` names anything the delete
    could not remove, so the dialog can tell the user rather than leaving a
    multi-GB orphan for lane A to upload (CORE-H5).

    `dry_run` (config `fixer_dry_run`, COMMERCIAL_READINESS.md item 9,
    2026-08-17) runs every check and every refusal and then STOPS: no name is
    claimed, no byte is copied, no clip is relinked. The plan comes back in
    the result as `would_copy_to` with `ok: False`, `dry_run: True`, and is
    logged. It exists because FIX ALL is the companion's largest destructive
    action and had no way to be rehearsed on a machine whose local_root or
    destination mapping is in doubt -- and "run it and see" costs a
    multi-GB copy per clip.
    """
    if copy_fn is None:
        def copy_fn(s, d):
            copy_with_progress(s, d, on_bytes=on_bytes, should_abort=should_abort)
    items_raw = media_pool_items if isinstance(media_pool_items, list) else [media_pool_items]
    items: list[Any] = []
    # De-duplicate by UID when the entry is an item dict and by object
    # identity when it is a MediaPoolItem (library walk, 2026-08-26): two
    # timeline items of one clip are two DIFFERENT dicts carrying the SAME
    # uid, and keying those by id() would put the clip cut in 50 times back
    # to 50 identical ReplaceClips -- the re-conform storm AUDIT 6 asked
    # this dedupe for.
    seen: set[Any] = set()
    for entry in items_raw:
        if isinstance(entry, dict) and str(entry.get("media_pool_uid") or ""):
            key: Any = ("uid", str(entry["media_pool_uid"]))
        else:
            key = ("id", id(entry))
        if key in seen:
            continue
        seen.add(key)
        items.append(entry)

    src = Path(file_path)
    if not src.is_file():
        return {"ok": False, "message": f"source file not found: {file_path}", "copied_to": None}

    # A blank local_root makes the D-6 containment check a NO-OP:
    # Path("").resolve() is the process CWD, so _dest_dir_is_contained
    # happily approves "<CWD>/Audio/Music". With local_root="" every clip
    # also classifies as OUT_OF_TREE, so one FIX ALL scatters the whole
    # project's media into the autostart exe's working directory --
    # C:\Windows\system32 for a Run-key launch -- and relinks Resolve to
    # paths nothing will ever sync (AUDIT_2 CORE-H1). Refuse outright; there
    # is no correct destination when we don't know where the tree is.
    if not str(local_root).strip():
        return {
            "ok": False,
            "message": (
                "CCSync doesn't know where your sync folder is (local_root is not set), "
                f"so it won't copy anything. {ui_copy.DIAGNOSTICS}."
            ),
            "copied_to": None,
        }

    try:
        local_root_resolved = Path(local_root).resolve()
    except OSError as exc:
        return {"ok": False, "message": f"bad local_root: {exc}", "copied_to": None}

    dest_dir = Path(local_root) / dest_rel.replace("/", os.sep)
    if not _dest_dir_is_contained(dest_dir, local_root_resolved, dest_rel):
        return {
            "ok": False,
            "message": f"refusing destination outside local_root: {dest_rel}",
            "copied_to": None,
        }

    if dry_run is None:
        dry_run = dry_run_default()
    if dry_run:
        planned = dest_dir / src.name
        log.info("fix_clip [dry-run]: would copy %s -> %s and relink %d media pool "
                 "item(s) to %s", file_path, planned, len(items),
                 canonical_clip_path(planned, local_root, canonical_prefix))
        return {
            "ok": False,
            "dry_run": True,
            "message": (f"Dry run: would copy to {planned} and relink "
                        f"{len(items)} clip reference(s). Nothing was changed."),
            "copied_to": None,
            "would_copy_to": str(planned),
            "would_relink_to": canonical_clip_path(planned, local_root, canonical_prefix),
        }

    try:
        dest_dir.mkdir(parents=True, exist_ok=True)
    except OSError as exc:
        return {"ok": False, "message": f"copy failed: {exc}", "copied_to": None}

    try:
        dest_path = _claim_destination_path(dest_dir, src.name)
    except OSError as exc:
        return {"ok": False, "message": f"copy failed: {exc}", "copied_to": None}

    # Copy to a temp name in the same dir, then atomically replace into the
    # final name -- a copy that dies mid-way (disk full, SMB drop) must
    # never leave a truncated file under the final name, which lane A would
    # otherwise upload once its --min-age guard expires and could then never
    # replace (lane A uses --ignore-existing) (AUDIT D-5).
    #
    # The tmp name carries pid+uuid: two overlapping FIX ALLs for the same
    # source name both wrote "<name>.ccsync-tmp", interleaved their writes,
    # and both os.replace'd into the same final name -- a corrupted mixed
    # file under a name Resolve was then relinked to (AUDIT_2 CORE-M1).
    tmp_path = dest_path.with_name(
        f"{dest_path.name}.{os.getpid()}-{uuid.uuid4().hex[:8]}{TMP_SUFFIX}"
    )
    placeholder = is_placeholder(str(src))
    src_before = sample_source(src)
    try:
        copy_fn(src, tmp_path)
        dest_path = reclaim_if_reservation_lost(dest_dir, dest_path, src.name)
        os.replace(tmp_path, dest_path)
    except CopyAborted:
        # THE CORE-H5 BARGAIN. Mid-file abort is only acceptable because
        # every artifact of the attempt goes away here: the partial
        # `<dest>.<pid>-<uuid>.ccsync-tmp` the copy was writing, and the
        # 0-byte final name _claim_destination_path reserved up front (which
        # os.replace never reached, so it is empty and unambiguously ours).
        # Leave either behind and the editor is back to an orphan under
        # local_root -- the tmp is filtered out of every lane, but the
        # reservation is not: a 0-byte .braw under the final name would
        # upload on lane A and could then never be replaced (--ignore-existing).
        # The reservation goes through remove_reserved_name, which refuses to
        # delete it if something else wrote there meanwhile (DEL-7).
        leftovers = [p for p in (remove_partial(tmp_path),
                                 remove_reserved_name(dest_path)) if p]
        log.info("fix_clip: %s abandoned by the user mid-copy%s", file_path,
                 f" (LEFTOVERS: {', '.join(leftovers)})" if leftovers else
                 " -- the half-copied file was removed")
        message = "Skipped by you. The half-copied file was removed. Nothing was relinked."
        if leftovers:
            message = (
                "Skipped by you, but CCSync couldn't delete the half-copied file at "
                + "; ".join(leftovers)
                + ". Delete it by hand."
            )
        return {
            "ok": False,
            "aborted": True,
            "message": message,
            "copied_to": None,
            "leftover_paths": leftovers,
        }
    except Exception as exc:
        try:
            tmp_path.unlink(missing_ok=True)
        except OSError:
            pass
        # dest_path is our O_EXCL-created reservation and nothing else's --
        # remove it so a failed copy doesn't leave a 0-byte file behind.
        try:
            if dest_path.exists() and dest_path.stat().st_size == 0:
                dest_path.unlink()
        except OSError:
            pass
        # WARNING with the path: "12 failed" with no filenames left the user
        # unable to see WHICH files failed, and the destination sits on an
        # SMB share whose metadata isn't refreshed until the handle closes,
        # so the filesystem cannot answer it either -- only this process can.
        log.warning("fix_clip: copy failed for %s (cloud placeholder=%s): %s",
                    file_path, placeholder, exc, exc_info=True)
        return {
            "ok": False,
            "message": classify_copy_failure(exc, placeholder),
            "copied_to": None,
            "placeholder": placeholder,
        }

    # THE LAST GATE BEFORE RESOLVE IS TOLD ANYTHING (item 9, 2026-08-17).
    # Everything above protects the destination; this protects the project
    # database. A short copy or a source that moved under us must not become
    # a relink -- see verify_copy.
    bad = verify_copy(src, dest_path, src_before)
    if bad is not None:
        removed_note = ""
        try:
            os.remove(dest_path)
        except OSError as exc:
            removed_note = f" It is still at {dest_path} ({exc}); delete it by hand."
        log.warning("fix_clip: refusing to relink %s -- %s", file_path, bad)
        return {
            "ok": False,
            "message": (f"Copied {src.name}, but {bad}. Nothing was relinked and the "
                        f"bad copy was removed.{removed_note}"),
            "copied_to": None,
            "verify_error": bad,
        }

    failures: list[str] = []
    relink_path = canonical_clip_path(dest_path, local_root, canonical_prefix)
    for entry in items:
        # Resolved at the moment of the native call, not when the batch was
        # collected (library walk, 2026-08-26): an entry may be an item dict
        # carrying only a uid. A clip that cannot be found is a FAILURE, not
        # a silent success -- the copy landed, so the editor has to be told
        # their project was NOT repointed at it.
        media_pool_item = resolve_bridge.resolve_media_pool_item(entry)
        if media_pool_item is None:
            name = (entry.get("clip_name") if isinstance(entry, dict) else "") or src.name
            log.warning("fix_clip: no media pool item for %s -- not relinked", name)
            failures.append(f"could not find {name} in the media pool")
            continue
        relink_result = replace_clip_fn(media_pool_item, relink_path)
        if not relink_result.get("ok"):
            failures.append(relink_result.get("message", "unknown error"))

    if failures:
        return {
            "ok": False,
            "message": (
                f"copied to {dest_path} but relink failed for {len(failures)}/{len(items)} "
                f"item(s): {'; '.join(failures)}"
            ),
            "copied_to": str(dest_path),
        }

    return {
        "ok": True,
        "message": f"Fixed: copied to {dest_path} and relinked {len(items)} item(s)",
        "copied_to": str(dest_path),
    }
