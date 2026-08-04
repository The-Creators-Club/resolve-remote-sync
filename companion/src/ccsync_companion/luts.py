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

Everything here is best-effort and never raises: an editor whose preferences
cannot be written keeps exactly the LUTs they have today, and the next check
tries again.
"""

from __future__ import annotations

import logging
import os
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
            if _resolved(path).startswith(library_resolved):
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
    ) -> None:
        self.cfg = cfg or {}
        self.local_root = Path(local_root).expanduser()
        self._prefs_factory = prefs_factory or resolve_prefs.ResolvePrefs
        self._refresh_fn = refresh_fn
        self._last_status = ""
        # Warn once per streak, not once per check: "the library hasn't
        # arrived yet" is normal for a new editor's first hours.
        self._warned: set[str] = set()

    @property
    def enabled(self) -> bool:
        return bool(self.cfg.get("lut_sync_enabled", True))

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
                return self._report(resolve_prefs.ALREADY, False, "")
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
