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

import logging
import os
import re
import shutil
import time
import uuid
from pathlib import Path
from typing import Any, Callable, Iterable, Optional

from . import resolve_bridge

log = logging.getLogger("ccsync.fixer")

AUDIO_EXTS = {".wav", ".mp3", ".aif", ".aiff", ".flac", ".m4a", ".ogg"}
IMAGE_EXTS = {".png", ".jpg", ".jpeg", ".tif", ".tiff", ".psd", ".exr"}

_TOKEN_RE = re.compile(r"[A-Za-z0-9]+")
_YEAR_RE = re.compile(r"^(19|20)\d{2}$")


class IgnoreTracker:
    """Per-session suppression, keyed by normalized path.

    Shared between the watcher (so an ignored path isn't re-popped) and the
    popup's "Ignore" button. Intentionally in-memory only — SPEC.md calls
    this out as per-session, not persisted.
    """

    def __init__(self) -> None:
        self._ignored: set[str] = set()

    def is_ignored(self, path: str) -> bool:
        return resolve_bridge._norm_path(path) in self._ignored

    def ignore(self, path: str) -> None:
        self._ignored.add(resolve_bridge._norm_path(path))

    def clear(self) -> None:
        self._ignored.clear()


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
    rels: set[str] = set()

    try:
        for dirpath, dirnames, filenames in os.walk(projects_dir):
            rel = Path(dirpath).relative_to(projects_dir)
            dirnames[:] = [d for d in dirnames if not d.startswith(".")]
            if rel == Path("."):
                continue
            if MARKER_FILENAME in filenames:
                rels.add(rel.as_posix())
                dirnames[:] = []
    except OSError:
        pass

    for extra in extra_rels or ():
        extra = str(extra).strip().strip("/")
        if extra and (projects_dir / Path(*extra.split("/"))).is_dir():
            rels.add(extra)
    return sorted(rels)


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


PLACEHOLDER_FAILURE_MESSAGE = (
    "Google Drive (or your cloud drive) couldn't download this file. Right-click it "
    "in the Google Drive folder → \"Available offline\", wait for it to finish, then "
    "run tray → Scan whole project again."
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


def sweep_stale_tmp_files(
    local_root: str,
    max_age_seconds: float = STALE_TMP_AGE_SECONDS,
    now_fn: Callable[[], float] = time.time,
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

    Returns the paths found (oldest first). Never raises."""
    found: list[tuple[float, str]] = []
    if not str(local_root).strip():
        return []
    now = now_fn()
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
                if (now - stat.st_mtime) < max_age_seconds:
                    continue
                found.append((stat.st_mtime, full))
    except Exception:
        log.debug("stale .ccsync-tmp sweep failed under %s", local_root, exc_info=True)
        return []

    found.sort()
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


def _dest_dir_is_contained(dest_dir: Path, local_root_resolved: Path) -> bool:
    """True iff `dest_dir`, once resolved, is local_root itself or somewhere
    under it. dest_rel is free text from an editable combobox (popup.py) --
    an absolute path, a drive-relative "\\Escaped\\Dir" (pathlib re-roots on
    the current drive when the right-hand side starts with a separator), or
    a "..\\..\\" traversal must all be rejected rather than silently copied
    (and Resolve relinked) outside the tree (AUDIT D-6)."""
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


def fix_clip(
    file_path: str,
    dest_rel: str,
    local_root: str,
    media_pool_items: Any,
    copy_fn=None,
    replace_clip_fn=resolve_bridge.replace_clip,
    on_bytes: Optional[Callable[[int, int], None]] = None,
    should_abort: Optional[Callable[[], bool]] = None,
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
    """
    if copy_fn is None:
        def copy_fn(s, d):
            copy_with_progress(s, d, on_bytes=on_bytes, should_abort=should_abort)
    items_raw = media_pool_items if isinstance(media_pool_items, list) else [media_pool_items]
    items: list[Any] = []
    seen_ids: set[int] = set()
    for mpi in items_raw:
        if id(mpi) in seen_ids:
            continue
        seen_ids.add(id(mpi))
        items.append(mpi)

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
                "so it won't copy anything. Tray → Copy diagnostics for your admin."
            ),
            "copied_to": None,
        }

    try:
        local_root_resolved = Path(local_root).resolve()
    except OSError as exc:
        return {"ok": False, "message": f"bad local_root: {exc}", "copied_to": None}

    dest_dir = Path(local_root) / dest_rel.replace("/", os.sep)
    if not _dest_dir_is_contained(dest_dir, local_root_resolved):
        return {
            "ok": False,
            "message": f"refusing destination outside local_root: {dest_rel}",
            "copied_to": None,
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
    try:
        copy_fn(src, tmp_path)
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

    failures: list[str] = []
    for media_pool_item in items:
        relink_result = replace_clip_fn(media_pool_item, str(dest_path))
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
