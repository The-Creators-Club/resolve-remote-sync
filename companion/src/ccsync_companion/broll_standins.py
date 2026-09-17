"""The stand-ins this machine has placed: a preview's bytes under an original's name.

WHY THIS EXISTS (2026-09-17, docs/BROLL_PROXY_TIERS_PLAN.md section 6). The
phase 0 spike settled it: Resolve will not create, repoint or import a
media-pool clip whose file it cannot open, by any route, and it refuses
silently. So the only way a remote editor gets a b-roll clip whose File Path
is the canonical original -- which is what makes the project portable to the
wired rig that holds the real file -- is to put the PREVIEW's bytes at the
original's own local path and name and import that. The clip is right; the
file underneath it is a 1080p H.264 lie.

A lie the companion has to remember, because three other readers would
otherwise believe the file:

  * broll_fetch's `local_path.is_file()` calls the original present, so the
    next Send to Resolve would never fetch anything again;
  * lane A uploads video originals, and a stand-in must never go up (today
    lane A only ever runs over `Projects/<rel>` and the archive is not a
    project, which is why that reader is a TEST and not code -- see
    tests/test_broll_standins.py);
  * a render on this machine would render 1080p H.264 under a 6K name.

Hence this ledger, `~/.ccsync/state/broll_standins.json`, keyed by the
NORMALISED local path (CR-90: NFC first, because a Mac's listdir is NFD and
`Matej Simalcik` in two spellings is two byte strings, then canon.norm for
case and separators). The RAW path is what is stored and opened; only the
key is normalised.

Staleness is a SIZE comparison, and that is what makes the ledger safe to
outlive the lie: an entry whose file on disk is a different size is an entry
whose stand-in has been replaced by something else (the real original
arriving by any route), so `is_standin` answers False and `is_stale` answers
True -- which is what tells the relink pass that the clip's stored geometry
is the stand-in's and needs one `replace_clip` on its own path (spike, second
half). A file that is absent leaves the entry standing: the path is still one
we lied about, and "absent" is what the insert table wants there anyway.

Never in memory only, and never fatal: a corrupt file is an EMPTY ledger plus
one warning (latched, so a file nobody repairs does not write a line per
poll), a write that fails costs a forgotten stand-in and never an insert, and
no method here raises.
"""

from __future__ import annotations

import json
import logging
import os
import threading
import time
import unicodedata
from pathlib import Path
from typing import Any, Optional

from . import canon
from . import config as config_mod

log = logging.getLogger("ccsync.broll")

STATE_FILENAME = "broll_standins.json"

# Where the archive sits inside the tree. The same pair as
# broll_server.BROLL_ARCHIVE_REL and broll_fetch.ARCHIVE_REMOTE_REL, repeated
# here rather than imported because broll_server imports THIS module and the
# watcher imports it too -- a cycle for one constant. test_broll_standins.py
# pins the three together, the way test_broll_fetch.py already pins the pair.
ARCHIVE_REL = ("Assets", "B-roll Archive")

# The background editing-proxy upgrade's state on an entry (plan section 6,
# step 5). A pending upgrade is the whole point of persisting it: Resolve
# being closed, or the companion restarting, must only DELAY the swap from
# the preview to the editing proxy, never lose it.
UPGRADE_PENDING = "pending"
UPGRADE_DONE = "done"
UPGRADE_FAILED = "failed"


def normalise_key(local_path: Any) -> str:
    """The comparison key for a local path. CR-90's normaliser, in order.

    NFC first (a path a Mac reported is not `==` a path anything else
    reported), then canon.norm, which folds case and separators in the
    spelling the string is WRITTEN in -- so a canonical `P:\\...` folds with
    ntpath even on a Mac. Never the key anything OPENS: the bytes on disk are
    the truth there, and `entry["local_path"]` keeps them.
    """
    text = str(local_path or "")
    if not text:
        return ""
    try:
        text = unicodedata.normalize("NFC", text)
    except Exception:
        pass
    try:
        return canon.norm(os.path.abspath(text))
    except Exception:
        return canon.norm(text)


def default_state_path(ccsync_cfg: Optional[dict] = None) -> Path:
    """`<log dir>/state/broll_standins.json`, the directory every other
    companion state file lives in (app.py derives it the same way).

    Reads config.toml only if there IS one: `load_config` creates it with
    defaults on first run, so a lazy read here would be a tool, a test or a
    bare import writing the installer's file (library walk review 2,
    2026-08-26, and resolve_bridge._config_without_creating's own note).
    """
    cfg = ccsync_cfg
    try:
        if cfg is None:
            cfg = (config_mod.load_config() if config_mod.CONFIG_PATH.exists()
                   else dict(config_mod.DEFAULTS))
        return config_mod.resolved_log_path(cfg).parent / "state" / STATE_FILENAME
    except Exception:
        return config_mod.CONFIG_DIR / "state" / STATE_FILENAME


def _size_of(path: Any) -> Optional[int]:
    try:
        return int(os.path.getsize(str(path)))
    except OSError:
        return None
    except Exception:
        return None


class StandinLedger:
    """The `broll_standins.json` file, with a memory in front of it.

    Re-read whenever the file's (mtime, size) changes, so a second process
    (the one-shot Resolve worker, a future CLI) writing an entry is seen here
    without this one holding the file open. Every write is tmp + os.replace
    with a pid-unique temporary name, for comp-sync-1's reason: two
    companions overlapping across a self-upgrade otherwise write the same
    `<name>.tmp` and one replaces the other's half-written bytes.
    """

    def __init__(self, path: Any):
        self.path = Path(path)
        self._lock = threading.RLock()
        self._entries: dict[str, dict[str, Any]] = {}
        self._stamp: Optional[tuple[float, int]] = None
        self._loaded = False
        # One warning per corrupt file, not one per read: the watcher asks
        # this question every 3 s.
        self._warned_corrupt = False

    # -- disk ---------------------------------------------------------------

    def _file_stamp(self) -> Optional[tuple[float, int]]:
        try:
            stat = self.path.stat()
            return (float(stat.st_mtime), int(stat.st_size))
        except OSError:
            return None
        except Exception:
            return None

    def _load_locked(self, force: bool = False) -> None:
        stamp = self._file_stamp()
        if self._loaded and not force and stamp == self._stamp:
            return
        self._stamp = stamp
        self._loaded = True
        if stamp is None:
            self._entries = {}
            return
        try:
            data = json.loads(self.path.read_text(encoding="utf-8-sig"))
        except (OSError, ValueError):
            if not self._warned_corrupt:
                self._warned_corrupt = True
                log.warning(
                    "b-roll stand-ins: %s is not readable JSON -- treating it as "
                    "empty. A clip inserted as a stand-in before now will look "
                    "like the real original to this companion", self.path,
                )
            self._entries = {}
            return
        entries = (data or {}).get("standins") if isinstance(data, dict) else None
        if not isinstance(entries, dict):
            self._entries = {}
            return
        self._entries = {
            str(key): dict(value)
            for key, value in entries.items()
            if isinstance(value, dict)
        }
        self._warned_corrupt = False

    def _persist_locked(self) -> bool:
        payload = {"version": 1, "standins": self._entries}
        target = self.path
        tmp = target.with_name(f"{target.name}.{os.getpid()}.tmp")
        try:
            target.parent.mkdir(parents=True, exist_ok=True)
            tmp.write_text(json.dumps(payload, indent=1), encoding="utf-8")
            os.replace(tmp, target)
        except OSError as exc:
            log.warning("b-roll stand-ins: could not persist %s: %s", target, exc)
            try:
                tmp.unlink()
            except OSError:
                pass
            return False
        self._stamp = self._file_stamp()
        return True

    # -- the ledger ---------------------------------------------------------

    def record(
        self,
        local_path: Any,
        share: str = "",
        rel_path: str = "",
        original_rel: Optional[str] = None,
        preview_rel: Optional[str] = None,
        edit_proxy_rel: Optional[str] = None,
        geometry: Optional[dict] = None,
        upgrade: Optional[str] = None,
        size: Optional[int] = None,
    ) -> dict[str, Any]:
        """Remember that `local_path` holds a preview's bytes. Never raises.

        Called BEFORE the import, always: a stand-in Resolve has already
        imported and the ledger does not know about is the one failure this
        module exists to prevent, and the cost of an entry whose import then
        failed is one stale row that `is_stale` retires.
        """
        key = normalise_key(local_path)
        entry = {
            "local_path": str(local_path or ""),
            "share": str(share or ""),
            "rel_path": str(rel_path or ""),
            "original_rel": original_rel if original_rel is None else str(original_rel),
            "preview_rel": preview_rel if preview_rel is None else str(preview_rel),
            "edit_proxy_rel": (edit_proxy_rel if edit_proxy_rel is None
                               else str(edit_proxy_rel)),
            "geometry": dict(geometry) if isinstance(geometry, dict) else None,
            "placed_at": time.time(),
            "placed_at_iso": time.strftime("%Y-%m-%dT%H:%M:%S"),
            # The stand-in's own size, which is what makes the entry
            # falsifiable later: a different size at that path means the lie
            # has been replaced (see the module docstring).
            "size": size if isinstance(size, int) else _size_of(local_path),
            "upgrade": upgrade,
            "upgrade_note": "",
        }
        if not key:
            return entry
        with self._lock:
            self._load_locked()
            self._entries[key] = entry
            self._persist_locked()
        log.warning(
            "b-roll stand-in: %s now holds the PREVIEW's bytes, not the original. "
            "Resolve will read its geometry from that file, and a render on this "
            "computer would render it (plan section 6, 2026-09-17)",
            entry["local_path"],
        )
        return entry

    def forget(self, local_path: Any) -> bool:
        """Drop the entry for this path. True when there was one."""
        key = normalise_key(local_path)
        if not key:
            return False
        with self._lock:
            self._load_locked()
            if key not in self._entries:
                return False
            self._entries.pop(key, None)
            self._persist_locked()
        return True

    def get(self, local_path: Any) -> Optional[dict[str, Any]]:
        key = normalise_key(local_path)
        if not key:
            return None
        with self._lock:
            self._load_locked()
            entry = self._entries.get(key)
            return dict(entry) if entry is not None else None

    def is_standin(self, local_path: Any) -> bool:
        """Is the file at this path one of ours, and still the preview?

        False for a path with no entry, and false for an entry whose file has
        since become a different size -- that is the real original arriving,
        and calling it a stand-in would keep the insert refusing to import a
        file that is now perfectly good.
        """
        entry = self.get(local_path)
        if entry is None:
            return False
        return not self._entry_is_stale(entry)

    def is_stale(self, local_path: Any) -> bool:
        """Is there an entry whose file is no longer the stand-in we placed?

        The relink pass's signal that the clip at this path was BORN from a
        stand-in and still carries the stand-in's geometry: only
        `replace_clip(<the same path>)` makes Resolve re-read a file that
        changed underneath it (spike, second half).
        """
        entry = self.get(local_path)
        if entry is None:
            return False
        return self._entry_is_stale(entry)

    @staticmethod
    def _entry_is_stale(entry: dict[str, Any]) -> bool:
        recorded = entry.get("size")
        if not isinstance(recorded, int):
            # We never knew the size, so nothing about the file can falsify
            # the entry. Treat it as still a stand-in: under-trusting the
            # file is the safe direction (no upload, no render, no import of
            # a file we believe is a lie).
            return False
        actual = _size_of(entry.get("local_path"))
        if actual is None:
            return False  # absent: the entry still stands (module docstring)
        return actual != recorded

    def all(self) -> list[dict[str, Any]]:
        """Every entry, newest first. Copies, never the live dicts."""
        with self._lock:
            self._load_locked()
            entries = [dict(value) for value in self._entries.values()]
        entries.sort(key=lambda item: float(item.get("placed_at") or 0.0), reverse=True)
        return entries

    def set_upgrade(self, local_path: Any, state: Optional[str],
                    note: str = "") -> bool:
        """Mark the background editing-proxy upgrade pending/done/failed."""
        key = normalise_key(local_path)
        if not key:
            return False
        with self._lock:
            self._load_locked()
            entry = self._entries.get(key)
            if entry is None:
                return False
            entry["upgrade"] = state
            entry["upgrade_note"] = str(note or "")
            self._entries[key] = entry
            self._persist_locked()
        return True

    def pending_upgrades(self) -> list[dict[str, Any]]:
        """Entries whose editing proxy is still owed. A restart, or a Resolve
        that was closed when the download finished, only DELAYS the upgrade:
        this is what the next cycle drains."""
        return [entry for entry in self.all()
                if entry.get("upgrade") == UPGRADE_PENDING
                and entry.get("edit_proxy_rel")]


# -- the process's ledger ----------------------------------------------------
#
# One instance, because the file is one file and the memory in front of it is
# worth sharing between the 8899 request threads, the upgrade thread and the
# watcher's poll. `configure()` is for app startup and for tests; everything
# else uses the default path.

_LEDGER_LOCK = threading.Lock()
_LEDGER: Optional[StandinLedger] = None


def ledger(path: Any = None) -> StandinLedger:
    global _LEDGER
    with _LEDGER_LOCK:
        if path is not None:
            if _LEDGER is None or Path(path) != _LEDGER.path:
                _LEDGER = StandinLedger(path)
            return _LEDGER
        if _LEDGER is None:
            _LEDGER = StandinLedger(default_state_path())
        return _LEDGER


def configure(path: Any) -> StandinLedger:
    """Point the process's ledger at `path` (app startup, tests)."""
    global _LEDGER
    with _LEDGER_LOCK:
        _LEDGER = StandinLedger(path)
        return _LEDGER


def record(local_path: Any, **kwargs: Any) -> dict[str, Any]:
    return ledger().record(local_path, **kwargs)


def forget(local_path: Any) -> bool:
    return ledger().forget(local_path)


def get(local_path: Any) -> Optional[dict[str, Any]]:
    return ledger().get(local_path)


def is_standin(local_path: Any) -> bool:
    """Module-level form, and the one every reader outside this file uses.

    Never raises: a ledger that cannot be read answers False, i.e. "an
    ordinary file", which is what every caller did before this existed.
    """
    try:
        return ledger().is_standin(local_path)
    except Exception:
        log.debug("b-roll stand-ins: is_standin failed for %r", local_path,
                  exc_info=True)
        return False


def is_stale(local_path: Any) -> bool:
    try:
        return ledger().is_stale(local_path)
    except Exception:
        log.debug("b-roll stand-ins: is_stale failed for %r", local_path,
                  exc_info=True)
        return False


def all() -> list[dict[str, Any]]:  # noqa: A001 - the plan names this reader
    try:
        return ledger().all()
    except Exception:
        log.debug("b-roll stand-ins: could not read the ledger", exc_info=True)
        return []


def set_upgrade(local_path: Any, state: Optional[str], note: str = "") -> bool:
    try:
        return ledger().set_upgrade(local_path, state, note)
    except Exception:
        log.debug("b-roll stand-ins: could not record the upgrade state",
                  exc_info=True)
        return False


def pending_upgrades() -> list[dict[str, Any]]:
    try:
        return ledger().pending_upgrades()
    except Exception:
        log.debug("b-roll stand-ins: could not read the pending upgrades",
                  exc_info=True)
        return []


def is_under_archive(path: Any, local_root: Any = "",
                     canonical_prefix: Any = "") -> bool:
    """Is this path inside the b-roll archive, by either spelling?

    The archive is the ONE place a stand-in can be, and the one place an
    offline original is the designed steady state rather than a problem
    (audit F4): the watcher subtracts these from the missing count.
    """
    text = str(path or "")
    if not text:
        return False
    for root in (str(local_root or ""), str(canonical_prefix or "")):
        if not root:
            continue
        plat = canon.plat_for(root)
        archive = plat.join(root, *ARCHIVE_REL)
        # Judged in the ROOT's spelling, the way canon.is_canonical judges the
        # prefix: `p:/assets/b-roll archive/x.mov` is under `P:\Assets\...` on
        # a Mac exactly as it is on Windows.
        if canon._is_under(text, archive, plat):
            return True
    return False
