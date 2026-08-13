"""Read and edit DaVinci Resolve's preference files.

Resolve keeps its preferences in two plain-text files that must agree:

  ``config.dat``      the engine's mirror   (``Custom.LUT.Path.Count`` /
                                             ``Custom.LUT.Path.<n>``)
  ``.config.data``    the GUI's own form    (``CustomLutNum`` /
                                             ``CustomLutPath_<n>``)

Editing ``config.dat`` alone has no lasting effect: the GUI form is what
Resolve rewrites ``config.dat`` from on the next launch. This is the same
pairing, and the same constraint, that installer/macos_bootstrap.sh's mapping
helper deals with for the Mapped Mount preference -- see SPEC.md flaw 7.

Two rules are absolute and both are enforced here:

  * **Resolve must be quit.** It rewrites both files from memory on exit, so
    an edit made while it is running is silently thrown away. Every write
    path refuses with RESOLVE_RUNNING rather than appearing to succeed.
  * **Never create the files.** A missing ``config.dat`` means Resolve has
    never completed a first run, and first-run onboarding regenerates the
    whole config anyway. Report CONFIG_MISSING and let the caller wait.

Edits are lossless (unknown keys, comments, blank-line structure, spacing and
line-ending style all survive), atomic (tempfile + os.replace) and preceded
by a timestamped backup of both files.

The key names here are not guesses: they were read off a live Resolve 20
install that already had a LUT location configured (Leso's Mac, 2026-08-05)
and cross-checked against a second install with none (the base rig).
"""

from __future__ import annotations

import os
import platform
import re
import shutil
import subprocess
import tempfile
import time
from pathlib import Path
from typing import Optional

CONFIG_DAT_NAME = "config.dat"
CONFIG_DATA_NAME = ".config.data"

# Outcomes. Strings rather than an enum so they travel straight into log
# lines, the tray and the reporter without conversion.
OK = "ok"
ALREADY = "already-present"
RESOLVE_RUNNING = "resolve-running"
CONFIG_MISSING = "config-missing"
FORMAT_UNRECOGNISED = "format-unrecognised"
IO_ERROR = "io-error"

# config.dat / .config.data key pairs for the "LUT Locations" list in
# Preferences -> System -> General.
LUT_COUNT_KEY_DAT = "Custom.LUT.Path.Count"
LUT_ITEM_KEY_DAT = "Custom.LUT.Path.{n}"
LUT_COUNT_KEY_DATA = "CustomLutNum"
LUT_ITEM_KEY_DATA = "CustomLutPath_{n}"

# Where Resolve keeps the gallery (stills). System.Gallery.DtMgr.FileSys is a
# 1-based index INTO THE MEDIA STORAGE LIST (Site.1.FS.<i>), and
# System.Gallery.Folder is a directory name under that entry's root -- so the
# stills actually live at <Site.1.FS.<FileSys>.Root>/<Folder>. Two machines
# whose first media storage locations differ therefore have different stills
# locations, which is what Resolve complains about at launch when they share
# a project database.
GALLERY_FS_KEY = "System.Gallery.DtMgr.FileSys"
GALLERY_FOLDER_KEY = "System.Gallery.Folder"
MEDIA_ROOT_KEY = "Site.1.FS.{n}.Root"
MEDIA_MAPPED_KEY = "Site.1.FS.{n}.MappedRoot"
MEDIA_TYPE_KEY = "Site.1.FS.{n}.Type"
MEDIA_DIO_KEY = "Site.1.FS.{n}.DIO"
MEDIA_COUNT_KEY = "Site.1.FS.Count"

# .config.data's form of the same media storage list.
DATA_FS_COUNT_KEY = "IoFsNum"
DATA_MOUNT_KEY = "IoFsMount_{n}"
DATA_MAPPED_KEY = "IoFsMappedMount_{n}"
DATA_DIO_KEY = "IoFsDirectIO_{n}"

# Resolve appends its own filesystem entry -- /Volumes on macOS, the
# ResolveVirtual pseudo-mount on Windows -- and expects it LAST. Ours goes in
# front of it. Same constant, same reason, as the installer's mapping helper.
TRAILING_ROOTS = ("/Volumes", "ResolveVirtual")


class PrefsError(Exception):
    def __init__(self, status: str, message: str) -> None:
        super().__init__(message)
        self.status = status
        self.message = message


def config_dir() -> Optional[Path]:
    """Resolve's preferences directory on this platform, or None.

    Windows keeps a "Preferences" subfolder; macOS does not. An explicit
    ``BMD_RESOLVE_CONFIG_DIR`` wins on both -- it is the override the
    installer's mapping helper already documents, and the hook tests use.
    """
    override = os.environ.get("BMD_RESOLVE_CONFIG_DIR", "").strip()
    if override:
        return Path(override)
    system = platform.system()
    if system == "Windows":
        base = os.environ.get("APPDATA", "")
        if not base:
            return None
        return Path(base) / "Blackmagic Design" / "DaVinci Resolve" / "Preferences"
    if system == "Darwin":
        home = Path.home()
        candidates = [
            home / "Library/Preferences/Blackmagic Design/DaVinci Resolve",
            home / ("Library/Containers/com.blackmagic-design.DaVinciResolve/Data/"
                    "Library/Preferences/Blackmagic Design/DaVinci Resolve"),
        ]
        for candidate in candidates:
            if (candidate / CONFIG_DAT_NAME).is_file():
                return candidate
        return candidates[0]
    return None


def resolve_process_state() -> Optional[bool]:
    """True = seen, False = definitely absent, None = could not tell.

    The honest three-valued answer behind resolve_is_running()'s two-valued
    one. Most callers want the fail-closed collapse below; anything that
    NAGS the editor on the strength of "Resolve is running" wants this
    instead, and must act only on a positive sighting -- an unsupported
    platform or a tasklist that will not spawn is not evidence of a running
    Resolve, and treating it as one turns a periodic warning into a
    permanent one on exactly the machines least able to diagnose it
    (app._maybe_warn_scripting_dead).
    """
    system = platform.system()
    try:
        if system == "Windows":
            out = subprocess.run(
                ["tasklist", "/FI", "IMAGENAME eq Resolve.exe", "/NH"],
                capture_output=True, text=True, timeout=20,
                creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
            )
            return "Resolve.exe" in (out.stdout or "")
        if system == "Darwin":
            out = subprocess.run(
                ["pgrep", "-x", "DaVinci Resolve"], capture_output=True, text=True, timeout=20
            )
            return out.returncode == 0
    except Exception:
        return None
    return None


def resolve_is_running() -> bool:
    """Whether DaVinci Resolve is running. Fails CLOSED -- an inconclusive
    check reports True, because writing prefs under a running Resolve loses
    the edit silently, while a false "it's running" only defers it."""
    return resolve_process_state() is not False


class PrefFile:
    """One preference file as an ordered list of lines, edited in place.

    Line-based rather than parsed-and-regenerated, which is what makes the
    edits lossless: anything this module does not understand (comments like
    config.dat's trailing "//Custom settings added by the user", keys from a
    newer Resolve, the blank lines that group sections) is never rewritten
    because it is never touched.
    """

    _KEY_RE = re.compile(r"^(?P<indent>\s*)(?P<key>[A-Za-z0-9_.]+)(?P<sep>\s*=\s*)(?P<value>.*)$")

    def __init__(self, path: Path) -> None:
        self.path = Path(path)
        raw = self.path.read_bytes()
        self.newline = "\r\n" if b"\r\n" in raw else "\n"
        self.trailing_newline = raw.endswith(b"\n") or raw.endswith(b"\r\n")
        text = raw.decode("utf-8", "surrogateescape")
        self.lines = text.splitlines()
        self._index: dict[str, int] = {}
        self._sep: dict[str, str] = {}
        for i, line in enumerate(self.lines):
            match = self._KEY_RE.match(line)
            if match:
                key = match.group("key")
                # FIRST occurrence wins, matching how Resolve reads them.
                self._index.setdefault(key, i)
                self._sep.setdefault(key, match.group("sep"))
        self.dirty = False

    # -- reads ---------------------------------------------------------
    def get(self, key: str) -> Optional[str]:
        i = self._index.get(key)
        if i is None:
            return None
        match = self._KEY_RE.match(self.lines[i])
        return match.group("value").strip() if match else None

    def get_int(self, key: str, default: int = 0) -> int:
        try:
            return int(str(self.get(key) or "").strip())
        except (TypeError, ValueError):
            return default

    def has(self, key: str) -> bool:
        return key in self._index

    # -- writes --------------------------------------------------------
    def set(self, key: str, value: str) -> None:
        """Update a key in place, or append it. An existing key keeps its own
        indentation and spacing -- Resolve's files use " = " throughout, but
        matching what is actually there is what keeps a diff to one line."""
        i = self._index.get(key)
        if i is not None:
            match = self._KEY_RE.match(self.lines[i])
            assert match is not None
            new = f"{match.group('indent')}{key}{match.group('sep')}{value}"
            if new != self.lines[i]:
                self.lines[i] = new
                self.dirty = True
            return
        self._append(key, value)

    def _append(self, key: str, value: str) -> None:
        sep = self._sep.get(next(iter(self._sep), ""), " = ") if self._sep else " = "
        self.lines.append(f"{key}{sep}{value}")
        self._index[key] = len(self.lines) - 1
        self._sep[key] = sep
        self.dirty = True

    def insert_after(self, anchor_key: str, key: str, value: str) -> None:
        """Add `key` immediately after `anchor_key`, so a counted list's items
        stay next to their count instead of drifting to the end of the file.
        Falls back to appending when the anchor is absent."""
        anchor = self._index.get(anchor_key)
        if anchor is None:
            self._append(key, value)
            return
        sep = self._sep.get(anchor_key, " = ")
        self.lines.insert(anchor + 1, f"{key}{sep}{value}")
        self._reindex()
        self.dirty = True

    def remove(self, key: str) -> None:
        i = self._index.get(key)
        if i is None:
            return
        del self.lines[i]
        self._reindex()
        self.dirty = True

    def _reindex(self) -> None:
        self._index.clear()
        self._sep.clear()
        for i, line in enumerate(self.lines):
            match = self._KEY_RE.match(line)
            if match:
                self._index.setdefault(match.group("key"), i)
                self._sep.setdefault(match.group("key"), match.group("sep"))

    def save(self, backup_suffix: str = "") -> bool:
        """Atomic write, preceded by a backup. Returns False when nothing
        changed (no backup, no write -- a no-op reconcile must leave no
        trace)."""
        if not self.dirty:
            return False
        if backup_suffix:
            try:
                shutil.copy2(self.path, self.path.with_name(self.path.name + backup_suffix))
            except OSError as exc:
                raise PrefsError(IO_ERROR, f"could not back up {self.path}: {exc}") from exc
        text = self.newline.join(self.lines)
        if self.trailing_newline:
            text += self.newline
        fd, tmp = tempfile.mkstemp(dir=str(self.path.parent), prefix=".ccsync-", suffix=".tmp")
        try:
            with os.fdopen(fd, "w", encoding="utf-8", errors="surrogateescape", newline="") as fh:
                fh.write(text)
            # Preserve the original mode: on the first real Mac .config.data
            # was 666 and owned by root while config.dat beside it was the
            # user's, and a replace that dropped the mode locked Resolve out
            # of its own preferences.
            try:
                shutil.copymode(self.path, tmp)
            except OSError:
                pass
            os.replace(tmp, self.path)
        except Exception:
            try:
                os.unlink(tmp)
            except OSError:
                pass
            raise
        return True


class ResolvePrefs:
    """Both preference files together, kept in agreement."""

    def __init__(self, directory: Optional[Path] = None) -> None:
        self.dir = Path(directory) if directory is not None else config_dir()
        if self.dir is None:
            raise PrefsError(CONFIG_MISSING, "no known Resolve preferences directory for this platform")
        self.dat_path = self.dir / CONFIG_DAT_NAME
        self.data_path = self.dir / CONFIG_DATA_NAME
        if not self.dat_path.is_file():
            raise PrefsError(
                CONFIG_MISSING,
                f"{self.dat_path} does not exist -- launch Resolve once, quit it, and retry",
            )
        try:
            self.dat = PrefFile(self.dat_path)
            # .config.data is absent on an install that has never saved
            # preferences from the GUI. That is survivable for reads; writes
            # below refuse rather than create it.
            self.data = PrefFile(self.data_path) if self.data_path.is_file() else None
        except OSError as exc:
            raise PrefsError(IO_ERROR, f"could not read Resolve preferences: {exc}") from exc

    # -- LUT locations -------------------------------------------------
    def lut_locations(self) -> list[str]:
        """The configured additional LUT directories, in order."""
        count = self.dat.get_int(LUT_COUNT_KEY_DAT, 0)
        found: list[str] = []
        for n in range(1, count + 1):
            value = self.dat.get(LUT_ITEM_KEY_DAT.format(n=n))
            if value:
                found.append(value)
        return found

    def has_lut_location(self, path: str) -> bool:
        want = _normcase(path)
        return any(_normcase(p) == want for p in self.lut_locations())

    def add_lut_location(self, path: str, backup_suffix: str = "") -> str:
        """Append `path` to the LUT Locations list in BOTH files.

        Returns OK, ALREADY, RESOLVE_RUNNING or FORMAT_UNRECOGNISED. Appends
        rather than replaces: an editor's own LUT location (Leso had one
        pointing at a pack under ~/Documents) is theirs, and silently
        dropping it would take away LUTs they are using.
        """
        if self.has_lut_location(path):
            return ALREADY
        if self.data is None:
            return FORMAT_UNRECOGNISED
        if resolve_is_running():
            return RESOLVE_RUNNING

        count = self.dat.get_int(LUT_COUNT_KEY_DAT, 0)
        data_count = self.data.get_int(LUT_COUNT_KEY_DATA, 0)
        if data_count != count:
            # The two files disagree about how many locations there are.
            # Resolve rebuilds config.dat from the GUI form, so the GUI form
            # is the authority -- but a mismatch means something else has
            # been editing these files, and appending to both would produce a
            # different list in each. Refuse.
            return FORMAT_UNRECOGNISED

        n = count + 1
        self.dat.set(LUT_COUNT_KEY_DAT, str(n))
        self.dat.insert_after(
            LUT_ITEM_KEY_DAT.format(n=count) if count else LUT_COUNT_KEY_DAT,
            LUT_ITEM_KEY_DAT.format(n=n), path,
        )
        self.data.set(LUT_COUNT_KEY_DATA, str(n))
        self.data.insert_after(
            LUT_ITEM_KEY_DATA.format(n=count) if count else LUT_COUNT_KEY_DATA,
            LUT_ITEM_KEY_DATA.format(n=n), path,
        )
        self._save_both(backup_suffix)
        return OK

    # -- gallery / stills ----------------------------------------------
    def media_storage(self) -> list[dict]:
        """The media storage list: [{"index", "root", "mapped_root"}...].

        Index is Resolve's own 1-based FS number, which is what
        System.Gallery.DtMgr.FileSys refers to.
        """
        count = self.dat.get_int(MEDIA_COUNT_KEY, 0)
        entries = []
        for n in range(1, count + 1):
            root = self.dat.get(MEDIA_ROOT_KEY.format(n=n))
            if root is None:
                continue
            entries.append({
                "index": n,
                "root": root,
                "mapped_root": self.dat.get(MEDIA_MAPPED_KEY.format(n=n)) or "",
            })
        return entries

    def gallery_location(self) -> dict:
        """Where this machine keeps its gallery stills.

        {"fs_index", "root", "mapped_root", "folder", "path", "mapped_path"}
        -- `path` is the real local directory, `mapped_path` is what the
        shared project database sees (the P:\\ form) when the entry carries a
        mapped root. Two machines whose `mapped_path` differ are what makes
        Resolve complain that the stills location does not match.
        """
        index = self.dat.get_int(GALLERY_FS_KEY, 0)
        folder = self.dat.get(GALLERY_FOLDER_KEY) or ".gallery"
        entry = next((e for e in self.media_storage() if e["index"] == index), None)
        root = entry["root"] if entry else ""
        mapped = entry["mapped_root"] if entry else ""
        return {
            "fs_index": index,
            "root": root,
            "mapped_root": mapped,
            "folder": folder,
            "path": _join(root, folder) if root else "",
            "mapped_path": _join(mapped, folder, windows=True) if mapped else "",
        }

    def ensure_media_storage(
        self, root: str, mapped_root: str = "", backup_suffix: str = ""
    ) -> tuple[str, int]:
        """Make sure a media storage entry for `root` exists; return
        (status, index).

        Appended IN FRONT of Resolve's own trailing entry (`/Volumes` on
        macOS, `ResolveVirtual` on Windows), which Resolve expects last --
        the same rule installer/macos_bootstrap.sh's mapping helper follows.
        Never touches entry 1: that is the scratch disk, and RenderCaching
        points at it by index.

        Both files, and the .config.data list is renumbered to match. Note
        that .config.data legitimately holds FEWER entries than config.dat
        (Resolve's auto-added trailing entry is absent from the GUI form),
        so the two counts are not expected to agree -- only the entries they
        share are.
        """
        existing = next(
            (e for e in self.media_storage() if _normcase(e["root"]) == _normcase(root)), None
        )
        if existing is not None:
            return ALREADY, existing["index"]
        if self.data is None:
            return FORMAT_UNRECOGNISED, 0
        if resolve_is_running():
            return RESOLVE_RUNNING, 0

        entries = self.media_storage()
        if not entries:
            return FORMAT_UNRECOGNISED, 0
        position = len(entries)
        last_root = (entries[-1]["root"] or "").strip()
        if last_root in TRAILING_ROOTS or any(
            last_root.startswith(r + "/") for r in TRAILING_ROOTS
        ):
            position = len(entries) - 1
        new_index = position + 1

        # config.dat: shift every entry at or after the insertion point up
        # one, then write the new one into the gap.
        for n in range(len(entries), position, -1):
            for key_fmt in (MEDIA_ROOT_KEY, MEDIA_MAPPED_KEY, MEDIA_TYPE_KEY, MEDIA_DIO_KEY):
                value = self.dat.get(key_fmt.format(n=n))
                if value is not None:
                    self.dat.set(key_fmt.format(n=n + 1), value)
        self.dat.set(MEDIA_TYPE_KEY.format(n=new_index), "IOFileSys")
        self.dat.set(MEDIA_ROOT_KEY.format(n=new_index), root)
        self.dat.set(MEDIA_MAPPED_KEY.format(n=new_index), mapped_root)
        self.dat.set(MEDIA_DIO_KEY.format(n=new_index), "1")
        self.dat.set(MEDIA_COUNT_KEY, str(len(entries) + 1))

        # .config.data: the GUI form. Its own numbering, its own count.
        data_count = self.data.get_int(DATA_FS_COUNT_KEY, 0)
        data_position = data_count
        for n in range(1, data_count + 1):
            mount = (self.data.get(DATA_MOUNT_KEY.format(n=n)) or "").strip()
            if mount in TRAILING_ROOTS:
                data_position = n - 1
                break
        data_index = data_position + 1
        for n in range(data_count, data_position, -1):
            for key_fmt in (DATA_MOUNT_KEY, DATA_MAPPED_KEY, DATA_DIO_KEY):
                value = self.data.get(key_fmt.format(n=n))
                if value is not None:
                    self.data.set(key_fmt.format(n=n + 1), value)
        self.data.set(DATA_MOUNT_KEY.format(n=data_index), root)
        self.data.set(DATA_MAPPED_KEY.format(n=data_index), mapped_root)
        self.data.set(DATA_DIO_KEY.format(n=data_index), "1")
        self.data.set(DATA_FS_COUNT_KEY, str(data_count + 1))

        self._save_both(backup_suffix)
        return OK, new_index

    def set_gallery_filesys(self, index: int, folder: str = ".gallery",
                            backup_suffix: str = "") -> str:
        """Point the gallery at media storage entry `index`.

        config.dat only: the gallery keys have no counterpart in
        .config.data's GUI form (verified on two installs), so unlike the LUT
        list there is nothing to keep in step here.
        """
        if resolve_is_running():
            return RESOLVE_RUNNING
        if not any(e["index"] == index for e in self.media_storage()):
            return FORMAT_UNRECOGNISED
        if self.dat.get_int(GALLERY_FS_KEY, 0) == index and (
            (self.dat.get(GALLERY_FOLDER_KEY) or "") == folder
        ):
            return ALREADY
        self.dat.set(GALLERY_FS_KEY, str(index))
        self.dat.set(GALLERY_FOLDER_KEY, folder)
        self._save_both(backup_suffix)
        return OK

    # -- shared --------------------------------------------------------
    def _save_both(self, backup_suffix: str = "") -> None:
        suffix = backup_suffix or f".ccsync-bak-{time.strftime('%Y%m%d-%H%M%S')}"
        self.dat.save(suffix)
        if self.data is not None:
            self.data.save(suffix)


def _normcase(path: str) -> str:
    """Compare two Resolve path strings. Case-insensitive and separator
    -insensitive: these are typed by humans into a GUI field and pasted
    between a Windows and a macOS machine."""
    return str(path or "").replace("\\", "/").rstrip("/").lower()


def _join(base: str, leaf: str, windows: bool = False) -> str:
    sep = "\\" if windows or ("\\" in base and "/" not in base) else "/"
    return f"{str(base).rstrip('/' + chr(92))}{sep}{leaf}"
