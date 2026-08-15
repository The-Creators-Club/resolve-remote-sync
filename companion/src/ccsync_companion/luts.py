"""Make Resolve read the shared, synced LUT library.

Syncing files to ``<local_root>/Assets/Luts`` does nothing on its own:
Resolve only looks in the LUT directories it has been told about. It has a
supported list of extra ones -- Preferences -> System -> General -> **LUT
Locations** -- so the library is added there. Nothing on disk is moved,
renamed or linked, Resolve's own factory LUTs are untouched, and an editor
can see and remove the entry in the UI like any other preference.

That list has no scripting API, but it is plain text in Resolve's two
preference files (``Custom.LUT.Path.*`` in ``config.dat``,
``CustomLutPath_*`` in ``.config.data``), which resolve_prefs.py edits
losslessly while Resolve is quit.

Two consequences follow from using the supported mechanism, and both are
deliberate:

  * **The library must hold only LUTs Resolve does not already ship.** An
    additional location is searched IN ADDITION to the factory directory, so
    a factory LUT copied into the library would appear twice in the LUT
    browser.
  * **The location string should be identical on every machine.** On Windows
    that is ``P:\\Assets\\Luts`` for everyone, because ``P:`` is the fleet's
    canonical drive (SPEC.md "Path canon"). A Mac has no P:, so it gets its
    real local path -- the one case where the string differs.

A correct preference is not enough on its own. **Resolve scans its LUT
locations once, at startup, and caches the result for the whole session**, so
a machine whose P: mapping is not up yet when Resolve launches runs blind to
the library until it is restarted -- with the preference reading perfectly all
the while. That is Ruskin's 2026-08-11 "LUTs missing": the pref said
``P:\\Assets\\Luts``, the files were on disk, and every graded frame logged
``Failed to read Shaper LUT``. stale_lut_index() below detects exactly that
from Resolve's own log and repairs it with RefreshLUTList(), no restart.

Everything here is best-effort and never raises: an editor whose preferences
cannot be written keeps exactly the LUTs they have today, and the next check
tries again.
"""

from __future__ import annotations

import logging
import os
import platform
import re
import shutil
from pathlib import Path
from typing import Any, Optional

from . import resolve_prefs

log = logging.getLogger("ccsync.luts")

# Where the shared library lives under local_root, matching the Syncthing
# folder id in sync/shared_folders.py.
LIBRARY_REL = ("Assets", "Luts")

# What counts as a LUT when deciding whether a stray file should be offered
# to the library. .dctl is deliberately ABSENT: Resolve loads DCTLs only from
# the LUT/DCTL directory, never from an additional LUT location, so copying
# one into the library would put it somewhere Resolve does not look.
LUT_EXTENSIONS = frozenset({".cube", ".ilut", ".olut", ".3dl", ".dat", ".mga", ".cms", ".lut"})


# -- the stale-index detector ----------------------------------------------
#
# Resolve logs one line per session start and one per LUT location it could
# not scan, both stamped "YYYY-MM-DD HH:MM:SS,mmm". That format sorts
# correctly as a plain string, so the "did this session fail to scan?"
# comparison needs no date parsing, no locale and no timezone.
_LOG_STAMP = re.compile(r"\|\s*(\d{4}-\d{2}-\d{2} \d{2}:\d{2}:\d{2},\d+)\s*\|")

# Emitted by Resolve's Main logger at every launch. Its stamp is what
# identifies the session, so a repair is attempted once per Resolve run and
# not once per check.
SESSION_START_MARKER = "Running DaVinci Resolve"

# "SyManager.Lut | ERROR | <stamp> | P:\Assets\Luts : no dir"
LUT_LOGGER_MARKER = "SyManager.Lut"
NO_DIR_SUFFIX = ": no dir"

# How much of the log to read. Only the tail matters, and a session that has
# outrun this much logging is one where the startup lines are gone anyway --
# in which case the detector reports "cannot tell" and does nothing.
LOG_TAIL_BYTES = 2 * 1024 * 1024


def resolve_log_path() -> Optional[Path]:
    """Resolve's own log file, or None on a platform we do not know.

    The Windows path is measured (Ruskin's machine, 2026-08-11); the macOS one
    is Blackmagic's documented location. Both fail safe: a path that is not
    there simply means no stale-index repair, never an error.
    """
    system = platform.system()
    if system == "Windows":
        base = os.environ.get("APPDATA", "")
        if not base:
            return None
        return (Path(base) / "Blackmagic Design" / "DaVinci Resolve"
                / "Support" / "logs" / "davinci_resolve.log")
    if system == "Darwin":
        return (Path.home() / "Library" / "Application Support" / "Blackmagic Design"
                / "DaVinci Resolve" / "logs" / "davinci_resolve.log")
    return None


def _same_location(path: str) -> str:
    """Compare a path as it appears in Resolve's log against one from its
    preferences. Same rule resolve_prefs uses for the LUT Locations list:
    these are GUI-typed strings that travel between machines."""
    return str(path or "").replace("\\", "/").rstrip("/").lower()


def _log_stamp(line: str) -> str:
    match = _LOG_STAMP.search(line)
    return match.group(1) if match else ""


def _no_dir_location(line: str) -> str:
    """The directory named by a 'X : no dir' line, or ''."""
    body = line.rsplit("|", 1)[-1].strip()
    if not body.endswith(NO_DIR_SUFFIX):
        return ""
    return body[: -len(NO_DIR_SUFFIX)].strip()


def read_log_tail(log_path: Path | str | None, tail_bytes: int = LOG_TAIL_BYTES) -> list[str]:
    """The last `tail_bytes` of Resolve's log, as lines. Never raises."""
    if not log_path:
        return []
    path = Path(log_path)
    try:
        if not path.is_file():
            return []
        size = path.stat().st_size
        with path.open("rb") as handle:
            if size > tail_bytes:
                handle.seek(size - tail_bytes)
                # The seek lands mid-line; drop that fragment so a truncated
                # timestamp cannot be mistaken for a session start.
                handle.readline()
            raw = handle.read()
    except OSError:
        return []
    return raw.decode("utf-8", "replace").splitlines()


def stale_lut_index(
    location: str, log_path: Path | str | None, tail_bytes: int = LOG_TAIL_BYTES
) -> Optional[str]:
    """The running session's stamp if Resolve failed to scan `location` at
    startup, else None.

    Resolve caches the LUT list at launch. A location that was unreachable
    then -- P: not mapped yet, the library still syncing -- stays missing for
    the whole session even after it comes back, and every grade referencing a
    LUT from it fails to render while the preference reads perfectly.

    Returns the session-start stamp rather than a bare True so the caller can
    repair once per Resolve run instead of once per check.

    Conservative on every ambiguity: no log, no session line in the tail, or a
    'no dir' older than the current session all return None. A missed repair
    costs one Resolve restart; a spurious one runs on every check forever.
    """
    want = _same_location(location)
    if not want:
        return None
    session = ""
    no_dir = ""
    for line in read_log_tail(log_path, tail_bytes):
        if SESSION_START_MARKER in line:
            stamp = _log_stamp(line)
            if stamp:
                session = stamp
        elif LUT_LOGGER_MARKER in line and NO_DIR_SUFFIX in line:
            if _same_location(_no_dir_location(line)) == want:
                stamp = _log_stamp(line)
                if stamp:
                    no_dir = stamp
    if not session or not no_dir:
        return None
    # Lexicographic on purpose -- see _LOG_STAMP. ">=" because the scan
    # happens within the same second as the launch line often enough
    # (13:32:02 launch, 13:32:05 scan, measured) that "after" is too strict
    # only in theory, while equality is real.
    return session if no_dir >= session else None


def library_dir(local_root: Path | str) -> Path:
    return Path(local_root).expanduser().joinpath(*LIBRARY_REL)


def library_location_string(
    cfg: dict[str, Any], local_root: Path | str, windows: Optional[bool] = None
) -> str:
    """The string to put in Resolve's LUT Locations list.

    The canonical ``P:\\Assets\\Luts`` wherever the canonical prefix is a real
    path on this machine, so every Windows editor's preference (and so every
    LUT reference stored against it) reads identically. A Mac reaches the
    tree through a Mapped Mount, which applies to media paths and not to this
    preference, so it gets the real local path instead.

    An explicit `lut_location_override` wins over both, for the machine whose
    layout does not fit either case.

    `windows` is a parameter rather than a bare `os.name` check so the
    cross-platform behaviour is testable from either host -- the canonical
    spelling is the thing most likely to break silently, and it is exactly
    the case a Windows-only test run cannot reach.
    """
    override = str((cfg or {}).get("lut_location_override", "") or "").strip()
    if override:
        return override
    if windows is None:
        windows = os.name == "nt"
    prefix = str((cfg or {}).get("canonical_prefix", "") or "").strip()
    if prefix and windows:
        return prefix.rstrip("\\/") + "\\" + "\\".join(LIBRARY_REL)
    return str(library_dir(local_root))


def is_lut_file(path: Path) -> bool:
    return path.suffix.lower() in LUT_EXTENSIONS


def relative_key(path: Path, base: Path) -> Optional[str]:
    try:
        return path.relative_to(base).as_posix().lower()
    except ValueError:
        return None


def library_index(library: Path) -> dict[str, int]:
    """{relative posix path (lowercased) -> size} for every LUT in the
    library. The key for "is this LUT already shared?" -- by name and size,
    not by content hash: a 40 MB pack would otherwise be re-hashed on every
    check, and two different LUTs with the same name AND size is not a case
    worth the cost."""
    index: dict[str, int] = {}
    if not library.is_dir():
        return index
    for path in library.rglob("*"):
        if not path.is_file() or not is_lut_file(path):
            continue
        key = relative_key(path, library)
        if key is None:
            continue
        try:
            index[key] = path.stat().st_size
        except OSError:
            index[key] = -1
    return index


def stray_luts(search_dirs: list[Path], library: Path, max_results: int = 200) -> list[dict]:
    """LUTs sitting outside the library that the library does not have.

    `search_dirs` are the places an editor actually drops a LUT -- Resolve's
    own LUT directory above all, because "Open LUT Folder" in Resolve's
    dropdown is still the obvious way to add one and it lands there, on that
    machine only.

    Matched by BASENAME anywhere in the library, not by relative path: an
    editor dropping "Ruskin CC.cube" loose in Resolve's LUT folder has the
    same LUT as the library's "Ruskin/Ruskin CC.cube", and prompting to copy
    it in again would be noise forever.
    """
    by_name: dict[str, list[int]] = {}
    for key, size in library_index(library).items():
        by_name.setdefault(key.rsplit("/", 1)[-1], []).append(size)

    found: list[dict] = []
    library_resolved = _resolved(library)
    for directory in search_dirs:
        if not directory or not Path(directory).is_dir():
            continue
        base = Path(directory)
        if _resolved(base) == library_resolved:
            continue
        for path in base.rglob("*"):
            if len(found) >= max_results:
                return found
            if not path.is_file() or not is_lut_file(path):
                continue
            # Never offer something that is already inside the library
            # (a search dir could contain it, e.g. a link or a nested copy).
            if _is_under(_resolved(path), library_resolved):
                continue
            try:
                size = path.stat().st_size
            except OSError:
                continue
            if size in by_name.get(path.name.lower(), []):
                continue
            found.append({
                "path": str(path),
                "name": path.name,
                "size": size,
                # Where it would land: the pack folder it sits in, preserved
                # one level deep, so "GR FILM LUTS/x.cube" stays grouped and
                # a loose file lands loose.
                "dest_rel": _dest_rel(path, base),
            })
    return found


def _dest_rel(path: Path, base: Path) -> str:
    rel = path.relative_to(base)
    return rel.as_posix()


def _is_under(resolved: str, base_resolved: str) -> bool:
    """Path containment on already-normcased strings, WITH the separator.

    A bare startswith made `P:\\Assets\\Luts Local` read as inside
    `P:\\Assets\\Luts`, so an editor who pointed Resolve's LUT folder at a
    sibling directory had every stray silently discarded and was never
    offered the "N LUTs only on this machine" item (COMP-GUARD-6,
    2026-08-14). canon._is_under documents the same trap for media paths.
    """
    if not base_resolved:
        return False
    if resolved == base_resolved:
        return True
    return resolved.startswith(base_resolved.rstrip("\\/") + os.sep)


def _resolved(path: Path) -> str:
    try:
        return os.path.normcase(str(Path(path).resolve()))
    except OSError:
        return os.path.normcase(str(path))


def copy_into_library(entries: list[dict], library: Path) -> dict:
    """Copy chosen strays into the library. Never overwrites, never deletes
    the original: the editor keeps their local copy, and the library gains
    one. Returns {"copied": n, "skipped": n, "errors": [...]}"""
    copied = skipped = 0
    errors: list[str] = []
    for entry in entries:
        src = Path(str(entry.get("path", "")))
        rel = str(entry.get("dest_rel") or src.name)
        dest = library.joinpath(*[p for p in rel.split("/") if p])
        try:
            if dest.exists():
                skipped += 1
                continue
            dest.parent.mkdir(parents=True, exist_ok=True)
            # Copy to a temp name and rename, so a half-copied LUT is never
            # visible to Syncthing (which is watching this directory) -- the
            # .ccsync-tmp suffix is in the folder's .stignore for exactly
            # this reason.
            tmp = dest.with_name(dest.name + ".ccsync-tmp")
            shutil.copy2(src, tmp)
            os.replace(tmp, dest)
            copied += 1
        except OSError as exc:
            errors.append(f"{src.name}: {exc}")
    return {"copied": copied, "skipped": skipped, "errors": errors}


class LutLinkManager:
    """Keeps the LUT library registered with Resolve, and finds strays.

    Periodic rather than once-at-startup for two reasons: the library may not
    have finished syncing when the companion launches (pointing Resolve at a
    directory that is not there yet is worse than waiting), and a Resolve
    upgrade can rewrite its preferences.
    """

    def __init__(
        self,
        cfg: dict[str, Any],
        local_root: Path | str,
        prefs_factory=None,
        refresh_fn=None,
        log_path=None,
        running_fn=None,
        location_exists_fn=None,
    ) -> None:
        self.cfg = cfg or {}
        self.local_root = Path(local_root).expanduser()
        self._prefs_factory = prefs_factory or resolve_prefs.ResolvePrefs
        self._refresh_fn = refresh_fn
        self._log_path = log_path
        self._running_fn = running_fn or resolve_prefs.resolve_is_running
        # Whether the LOCATION STRING resolves right now -- which on Windows
        # is P:\..., not the local path library() returns. Injected because
        # the canonical P: exists on the base rig, so a test asserting against
        # it would pass there and nowhere else.
        self._location_exists_fn = location_exists_fn or os.path.isdir
        self._last_status = ""
        # Warn once per streak, not once per check: "the library hasn't
        # arrived yet" is normal for a new editor's first hours.
        self._warned: set[str] = set()
        # The Resolve session whose stale LUT index we have already repaired.
        # In-process only: a companion restart re-reading the same log and
        # refreshing once more is harmless, while a marker persisted to disk
        # would suppress the repair after the one restart that needed it.
        self._repaired_session = ""

    @property
    def enabled(self) -> bool:
        return bool(self.cfg.get("lut_sync_enabled", True))

    @property
    def repair_enabled(self) -> bool:
        return bool(self.cfg.get("lut_index_repair_enabled", True))

    def log_path(self):
        configured = str(self.cfg.get("resolve_log_override", "") or "").strip()
        if configured:
            return Path(configured).expanduser()
        return self._log_path if self._log_path is not None else resolve_log_path()

    def library(self) -> Path:
        return library_dir(self.local_root)

    def location_string(self) -> str:
        return library_location_string(self.cfg, self.local_root)

    def search_dirs(self) -> list[Path]:
        """Where to look for strays: Resolve's own LUT directory."""
        configured = str(self.cfg.get("resolve_lut_dir", "") or "").strip()
        if configured:
            return [Path(configured).expanduser()]
        default = _default_resolve_lut_dir()
        return [default] if default else []

    def check(self) -> dict[str, Any]:
        """One idempotent reconcile of the LUT Locations preference.

        Never raises. Returns {"status", "changed", "message"}.
        """
        if not self.enabled:
            return {"status": "disabled", "changed": False, "message": ""}
        library = self.library()
        if not library.is_dir():
            return self._report(
                "no-library", False,
                f"the LUT library {library} has not synced to this machine yet")
        location = self.location_string()
        try:
            prefs = self._prefs_factory()
        except resolve_prefs.PrefsError as exc:
            return self._report(exc.status, False, exc.message)
        except Exception as exc:
            log.debug("luts: could not read Resolve preferences", exc_info=True)
            return self._report("error", False, str(exc))

        try:
            if prefs.has_lut_location(location):
                # The preference is right, which is NOT the same as Resolve
                # having read the library -- see repair_stale_index().
                repaired = self.repair_stale_index(location)
                return self._report(resolve_prefs.ALREADY, repaired, "")
            status = prefs.add_lut_location(location)
        except resolve_prefs.PrefsError as exc:
            return self._report(exc.status, False, exc.message)
        except Exception as exc:
            log.debug("luts: could not add the LUT location", exc_info=True)
            return self._report("error", False, str(exc))

        if status == resolve_prefs.OK:
            log.info("luts: added %s to Resolve's LUT Locations", location)
            self._warned.clear()
            self.refresh_resolve()
            return self._report(status, True, f"added {location} to Resolve's LUT Locations")
        if status == resolve_prefs.RESOLVE_RUNNING:
            return self._report(
                status, False,
                "Resolve is running -- its LUT Locations will be set the next time it is "
                "closed (Resolve overwrites its own preferences on exit)")
        if status == resolve_prefs.FORMAT_UNRECOGNISED:
            return self._report(
                status, False,
                "Resolve's preference files are not in the expected shape -- add "
                f"{location} by hand in Preferences > System > General > LUT Locations")
        return self._report(status, False, "")

    def _report(self, status: str, changed: bool, message: str) -> dict[str, Any]:
        self._last_status = status
        if message and status not in self._warned:
            self._warned.add(status)
            log.warning("luts: %s", message)
        return {"status": status, "changed": changed, "message": message}

    def status(self) -> str:
        return self._last_status

    def find_strays(self) -> list[dict]:
        """LUTs on this machine that the shared library does not have."""
        if not self.enabled:
            return []
        try:
            return stray_luts(self.search_dirs(), self.library())
        except Exception:
            log.debug("luts: stray scan failed", exc_info=True)
            return []

    def adopt(self, entries: list[dict]) -> dict:
        """Copy strays into the library and tell Resolve to re-read."""
        result = copy_into_library(entries, self.library())
        if result.get("copied"):
            self.refresh_resolve()
        return result

    def repair_stale_index(self, location: Optional[str] = None) -> bool:
        """Re-scan the LUT list if THIS Resolve session launched without it.

        The case the preference check cannot see: Resolve scans its LUT
        locations once at startup, so an editor who opened Resolve before P:
        finished mapping has a session-long hole where the shared library
        should be. The pref reads correctly, the files are on disk, and every
        graded frame logs "Failed to read Shaper LUT" (Ruskin, 2026-08-11).

        RefreshLUTList() closes it without restarting Resolve or touching a
        preference file -- so, unlike the rest of this module, it works while
        the editor is mid-edit, which is exactly when they hit this.

        Never raises. Returns whether a repair was actually made.
        """
        if not self.enabled or not self.repair_enabled:
            return False
        try:
            location = location or self.location_string()
            # Nothing to refresh in a Resolve that is not running, and the
            # stale index dies with the process anyway.
            if not self._running_fn():
                return False
            session = stale_lut_index(location, self.log_path())
            if not session or session == self._repaired_session:
                return False
            # The drive may still be down. Refreshing now would "succeed"
            # against an unreadable location, and marking the session repaired
            # would then cost the editor the retry they actually need once it
            # comes back -- the whole point being to avoid a Resolve restart.
            if not self._location_exists_fn(location):
                log.debug("luts: %s is still unreachable -- deferring the re-scan", location)
                return False
            if not self.refresh_resolve():
                # Routine -- no project open yet, most likely. Leave the
                # marker unset so the next check tries this session again.
                log.debug("luts: stale LUT index found but the refresh did not take")
                return False
            self._repaired_session = session
            log.warning(
                "luts: Resolve started at %s without %s (it was not reachable yet) -- "
                "re-scanned its LUT list", session, location,
            )
            return True
        except Exception:
            log.debug("luts: stale-index repair failed", exc_info=True)
            return False

    def refresh_resolve(self) -> bool:
        """Ask a running Resolve to re-read its LUT directories. Never raises."""
        try:
            if self._refresh_fn is not None:
                return bool(self._refresh_fn())
            from . import resolve_bridge
            return bool(resolve_bridge.refresh_lut_list())
        except Exception:
            log.debug("luts: RefreshLUTList failed", exc_info=True)
            return False


def _default_resolve_lut_dir() -> Optional[Path]:
    """Resolve's own LUT directory -- where "Open LUT Folder" drops a LUT,
    and so where strays collect."""
    import platform

    system = platform.system()
    if system == "Windows":
        base = os.environ.get("PROGRAMDATA", r"C:\ProgramData")
        return Path(base) / "Blackmagic Design" / "DaVinci Resolve" / "Support" / "LUT"
    if system == "Darwin":
        return Path("/Library/Application Support/Blackmagic Design/DaVinci Resolve/LUT")
    return None
