"""Install the "originals on request" Resolve menu scripts (SELECTIVE_ORIGINALS.md 12.1).

The companion writes Lua files into Resolve's per-user Scripts folder; Resolve
lists them under Workspace > Scripts > CC Sync on the Edit page the next time
it starts. Nothing here talks to Resolve (CR-68: the only scriptapp() caller
is resolve_bridge.connect()), so installing is safe while Resolve is running
or rendering.

Each shipped entry script carries a ``--@@CCSYNC_COMMON@@`` line that is
replaced here by ``_originals_common.lua``: the installed file is
self-contained because nothing documents how Resolve's menu runner names a
script's chunk, so a dofile() relative to the script could not be trusted.
"""

from __future__ import annotations

import logging
import os
import sys
from pathlib import Path

log = logging.getLogger("ccsync.resolve_menu")

PACKAGE_DIR_NAME = "resolve_menu"
COMMON_NAME = "_originals_common.lua"
SPLICE_MARKER = "--@@CCSYNC_COMMON@@"
# First line of every script we install. Removal keys on it, so a script the
# editor (or another tool) put in our folder by hand is never deleted.
OWNED_MARKER = "-- CC Sync menu script. Installed and rewritten by the CC Sync companion"
MENU_SUBDIR = ("Edit", "CC Sync")
_TMP_SUFFIX = ".ccsync-tmp"


def _source_dir() -> Path | None:
    # Same lookup order as theme.asset_path: a onefile build extracts the
    # datas declared in build.spec under sys._MEIPASS, a source or pip install
    # has them beside this module (pyproject package-data).
    candidates = []
    meipass = getattr(sys, "_MEIPASS", None)
    if meipass:
        candidates.append(Path(meipass) / "ccsync_companion" / PACKAGE_DIR_NAME)
    candidates.append(Path(__file__).resolve().parent / PACKAGE_DIR_NAME)
    for candidate in candidates:
        if (candidate / COMMON_NAME).is_file():
            return candidate
    return None


def scripts_root(platform: str | None = None) -> Path | None:
    """Resolve's per-user Fusion/Scripts folder, or None on an unsupported OS.

    The README (Developer/Scripting, "Specific user") writes the Windows one
    as ``%APPDATA%\\Roaming\\...``, which doubles the Roaming that %APPDATA%
    already ends in; the real folder is ``%APPDATA%\\Blackmagic Design\\...``.
    """
    platform = platform or sys.platform
    if platform.startswith("win"):
        appdata = os.environ.get("APPDATA")
        if not appdata:
            return None
        return (Path(appdata) / "Blackmagic Design" / "DaVinci Resolve"
                / "Support" / "Fusion" / "Scripts")
    if platform == "darwin":
        return (Path.home() / "Library" / "Application Support"
                / "Blackmagic Design" / "DaVinci Resolve" / "Fusion" / "Scripts")
    return None


def _read_text(path: Path) -> str:
    # A Windows checkout under core.autocrlf=true hands us CRLF and a Mac one
    # LF; normalising means the installed bytes are the same everywhere and a
    # checkout flip never reads as "changed".
    return path.read_bytes().decode("utf-8").replace("\r\n", "\n")


def render_scripts(source: Path | None = None) -> dict[str, bytes]:
    """{installed file name: bytes} for every shipped menu script."""
    source = source or _source_dir()
    if source is None:
        raise FileNotFoundError(f"{PACKAGE_DIR_NAME}/{COMMON_NAME} is not in this build")
    common = _read_text(source / COMMON_NAME)
    if not common.endswith("\n"):
        common += "\n"
    out: dict[str, bytes] = {}
    for entry in sorted(source.glob("*.lua")):
        if entry.name == COMMON_NAME or entry.name.startswith("_"):
            continue
        text = _read_text(entry)
        lines = text.split("\n")
        if SPLICE_MARKER not in (line.strip() for line in lines):
            raise ValueError(f"{entry.name} has no {SPLICE_MARKER} line")
        if not text.startswith(OWNED_MARKER):
            raise ValueError(f"{entry.name} does not start with the ownership line")
        spliced = "\n".join(common.rstrip("\n") if line.strip() == SPLICE_MARKER else line
                            for line in lines)
        if not spliced.endswith("\n"):
            spliced += "\n"
        out[entry.name] = spliced.encode("utf-8")
    if not out:
        raise FileNotFoundError(f"no menu scripts found in {source}")
    return out


def _is_owned(path: Path) -> bool:
    try:
        with path.open("rb") as fh:
            head = fh.read(len(OWNED_MARKER.encode("utf-8")))
    except OSError:
        return False
    return head == OWNED_MARKER.encode("utf-8")


def _write_atomic(path: Path, data: bytes) -> None:
    tmp = path.with_name(path.name + _TMP_SUFFIX)
    with tmp.open("wb") as fh:
        fh.write(data)
        fh.flush()
        os.fsync(fh.fileno())
    os.replace(tmp, path)


def _ensure_request_dir() -> None:
    # The scripts can only create a folder through bmd.createdir or a shelled
    # mkdir (a console flash on Windows); having it already there spares them.
    try:
        (Path.home() / ".ccsync" / "requests" / "originals").mkdir(parents=True, exist_ok=True)
    except OSError as exc:
        log.info("resolve menu: could not create the request folder: %s", exc)


def install_menu_scripts(root: Path | None = None) -> dict:
    """Write the menu scripts under ``<root>/Edit/CC Sync/``. Never raises.

    Returns ``{"ok", "installed", "removed", "message"}``; ``installed`` and
    ``removed`` list file names actually written or deleted this call, so an
    unchanged install reports two empty lists.
    """
    result: dict = {"ok": False, "installed": [], "removed": [], "message": ""}
    try:
        root = Path(root) if root is not None else scripts_root()
        if root is None:
            result["message"] = "Resolve menu scripts are not supported on this system."
            return result
        # Resolve creates <...>/Fusion on first launch. Its absence means
        # Resolve was never run by this user, and building the tree ourselves
        # would leave a Blackmagic folder on a machine without Resolve.
        if not root.parent.is_dir():
            result["message"] = f"DaVinci Resolve does not seem to be installed for this user ({root.parent} is missing)."
            return result
        scripts = render_scripts()
        target = root.joinpath(*MENU_SUBDIR)
        target.mkdir(parents=True, exist_ok=True)
        for name, data in scripts.items():
            path = target / name
            try:
                if path.is_file() and path.read_bytes() == data:
                    continue
            except OSError:
                pass
            _write_atomic(path, data)
            result["installed"].append(name)
        for path in sorted(target.iterdir()):
            if not path.is_file():
                continue
            stale_tmp = path.name.endswith(_TMP_SUFFIX)
            stale_script = (path.suffix.lower() == ".lua" and path.name not in scripts
                            and _is_owned(path))
            if stale_tmp or stale_script:
                try:
                    path.unlink()
                    if stale_script:
                        result["removed"].append(path.name)
                except OSError as exc:
                    log.info("resolve menu: could not remove %s: %s", path, exc)
        _ensure_request_dir()
        result["ok"] = True
        if result["installed"] or result["removed"]:
            result["message"] = (f"Resolve menu scripts updated in {target} "
                                 f"({len(result['installed'])} written, {len(result['removed'])} removed).")
        else:
            result["message"] = f"Resolve menu scripts already up to date in {target}."
        log.info("resolve menu: %s", result["message"])
    except Exception as exc:  # noqa: BLE001 - a menu install must never stop the companion starting
        result["ok"] = False
        result["message"] = f"Could not install the Resolve menu scripts: {exc}"
        log.warning("resolve menu: %s", result["message"])
    return result
