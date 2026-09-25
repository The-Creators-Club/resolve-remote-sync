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

# comp-broll-tiers-2 (2026-09-18): how many times the 120 s cycle may re-try
# one entry's editing-proxy upgrade before it stops asking.
#
# `run_proxy_upgrade` deliberately leaves an entry PENDING when the download
# landed but Resolve would not link it (Resolve closed, or open on another
# project), and `resume_pending_upgrades` is called from the relink cycle for
# every pending row. A row that can never link - the clip is not in this
# project, the rel was the stem convention's guess and no such file exists -
# therefore cost one thread and one Resolve worker CHILD every two minutes,
# for ever, with nothing that retired it. The count lives on the entry rather
# than in memory because a restart must not hand back the budget. An insert
# of that clip by the editor is an explicit ask and resets it.
UPGRADE_MAX_ATTEMPTS = 8

# comp-broll-tiers-5 (2026-09-18): when an entry whose file is GONE is
# dropped. Both conditions, in this order: a file that is merely absent is
# still a path we lied about (the module docstring's rule, and
# `_entry_is_stale` returns False for it), so absence alone can never retire
# a row. Age is what makes it safe: a month after we placed it, a path with
# no file has been deleted, moved or re-synced by some other route, and the
# entry is describing nothing.
PRUNE_AFTER_SECONDS = 30 * 24 * 3600.0

# proxy-tiers-1 (2026-09-18b): how long an INTENT row - one written before
# the fetch, with no size, by the insert path - may claim a file it has never
# seen. The whole point of a size is that a different one falsifies the row;
# a row with none can be falsified by nothing at all, not even the real 6 K
# original arriving at that path, and `_prune_locked` would only retire it 30
# days later. `settle_intents` is what answers it: a file that has appeared
# is measured (the row becomes an ordinary, falsifiable one), and a path with
# no file after this long is a download that never landed.
#
# Generous on purpose. It only ever runs while the tree is DEMONSTRABLY
# there, and settling costs one stat per intent row on the 120 s cycle, so
# the expiry is reached only by a row nothing ever landed for.
INTENT_EXPIRY_SECONDS = 6 * 3600.0

# proxy-tiers-4 (2026-09-18): how many archive rels one report may carry in
# `sync_guard.standins_placed`. The dashboard's bound for the same section and
# for its `standins_known` answer, written down on both sides so a truncation
# is a decision and not a surprise (docs/bug-hunt-2026-09-18/ledger/dashboard.md,
# "proxy-tiers-4 contract").
FLEET_REPORT_MAX = 200


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


def archive_rel_of(path: Any, local_root: Any = "",
                   canonical_prefix: Any = "") -> Optional[str]:
    """This file's path RELATIVE TO THE ARCHIVE, forward slashes, NFC.

    proxy-tiers-4 (2026-09-18): the fleet's key for a stand-in fact. Never an
    absolute path - the vault is a drive letter here and a container mount
    there - and NFC because a Mac's listdir is NFD and the two spellings of
    one name are two byte strings (CR-90). Only ever compared or reported, so
    normalising it is right; nothing opens it.

    None when the path is not under the archive by either spelling.
    """
    text = str(path or "")
    if not text:
        return None
    for root in (str(local_root or ""), str(canonical_prefix or "")):
        if not root:
            continue
        plat = canon.plat_for(root)
        archive = plat.join(root, *ARCHIVE_REL)
        if not canon._is_under(text, archive, plat):
            continue
        rel = text[len(archive):].lstrip("\\/")
        rel = rel.replace("\\", "/")
        if not rel:
            continue
        try:
            return unicodedata.normalize("NFC", rel)
        except Exception:
            return rel
    return None


def placed_report(local_root: Any = "", canonical_prefix: Any = "",
                  limit: int = FLEET_REPORT_MAX) -> dict[str, Any]:
    """`sync_guard.standins_placed`: which archive ORIGINALS this machine has
    stood in for. Never raises.

    proxy-tiers-4. A stand-in is placed on the REMOTE editor's machine and the
    ledger row is written there and nowhere else, so the plan's last table row
    ("or the ledger says so") could never fire on the wired rig - the only
    machine that needs it, and the machine whose ledger is empty for exactly
    these clips by construction. This is the fact leaving the machine that
    lied.

    Every entry is listed, stale or not: the question a wired rig is asking is
    "was this clip ever placed as a stand-in by anybody", and a row this
    machine has since replaced still describes a project cut against the
    stand-in's geometry. An EMPTY list is a positive statement ("none here"),
    which is what lets the dashboard replace this machine's set; the section
    is therefore always sent.
    """
    rels: list[str] = []
    seen: set[str] = set()
    try:
        for entry in all():
            rel = None
            for key in ("original_rel", "rel_path"):
                value = entry.get(key)
                if isinstance(value, str) and value.strip():
                    rel = value.strip().replace("\\", "/")
                    break
            if rel is None:
                rel = archive_rel_of(entry.get("local_path"), local_root,
                                     canonical_prefix)
            if not rel:
                continue
            try:
                rel = unicodedata.normalize("NFC", rel)
            except Exception:
                pass
            if rel in seen:
                continue
            seen.add(rel)
            rels.append(rel)
            if len(rels) >= max(0, int(limit)):
                break
    except Exception:                                          # noqa: BLE001
        log.debug("b-roll stand-ins: could not build the fleet report",
                  exc_info=True)
    return {"rels": rels,
            "checked_at": time.strftime("%Y-%m-%dT%H:%M:%S", time.gmtime())}


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


def _attempts_of(entry: dict[str, Any]) -> int:
    """How many upgrade attempts this entry has spent. An entry written by
    0.9.74 has no such field, and 0 is the right reading of that."""
    try:
        return int(entry.get("upgrade_attempts") or 0)
    except (TypeError, ValueError):
        return 0


def _isdir(path: Any) -> bool:
    """Is this a directory right now? Never raises, and never guesses."""
    try:
        return os.path.isdir(str(path))
    except Exception:
        return False


def _archive_root_of(path: Any) -> Optional[str]:
    """The `.../Assets/B-roll Archive` this entry's file hangs off, or None.

    comp-broll-tiers-1 (2026-09-18b): the ledger holds no local_root, so the
    root is recovered from the entry's own path by walking up to the ARCHIVE_REL
    pair. None means "cannot tell where this file's tree is", which is the one
    answer that must never be read as "the tree is there".
    """
    text = str(path or "")
    if not text:
        return None
    plat = canon.plat_for(text)
    wanted = [part.lower() for part in ARCHIVE_REL]
    current = plat.dirname(text)
    for _ in range(64):
        if not current:
            return None
        probe, matched = current, True
        for name in reversed(wanted):
            head, tail = plat.split(probe)
            if tail.lower() != name or not head:
                matched = False
                break
            probe = head
        if matched:
            return current
        head = plat.dirname(current)
        if head == current:
            return None
        current = head
    return None


def _geometry_wh(geometry: Any) -> Optional[tuple[int, int]]:
    """(width, height) as a pair of positive ints, or None for "no answer".

    proxy-tiers-1 (2026-09-18b): the one comparison `settle_intents` makes,
    and a missing or unparseable half must read as "cannot tell", never as a
    zero that happens to differ from everything.
    """
    if not isinstance(geometry, dict):
        return None
    try:
        width = int(geometry.get("width") or 0)
        height = int(geometry.get("height") or 0)
    except (TypeError, ValueError):
        return None
    return (width, height) if width > 0 and height > 0 else None


# The browsing preview a stand-in is made of: `ffmpeg_tools.preview_proxy_cmd`
# (and the indexer's build_proxy), `scale=-2:trunc(min(PROXY_HEIGHT,ih)/2)*2`,
# always H.264 (h264_nvenc or libx264). Read from ffmpeg_tools where it can
# be, so the settlement moves if the preview spec ever does.
PREVIEW_CODEC = "h264"


def _preview_height() -> int:
    try:
        from . import ffmpeg_tools  # noqa: PLC0415

        return int(ffmpeg_tools.PROXY_HEIGHT)
    except Exception:  # noqa: BLE001
        return 1080


def _preview_keeps_geometry(original_wh: tuple[int, int]) -> bool:
    """Whether the preview of an original this size has its exact WxH.

    logic-broll-music-2 (2026-09-25): never upscaled, even height, and the
    width follows the height with `-2` (even), so an original of at most the
    preview height with even sides comes out the same size.
    """
    width, height = original_wh
    return height <= _preview_height() and height % 2 == 0 and width % 2 == 0


def _default_probe(path: Any) -> Optional[dict]:
    """The file's HEADER, through the companion's configured ffmpeg. Never
    raises and never a full demux: `probe_video` is one open, and the question
    is only "is this the preview or the 6K original"."""
    try:
        from . import ffmpeg_tools

        cfg = config_mod.load_config()
        ffmpeg_path = str(cfg.get("ffmpeg_path", "ffmpeg") or "ffmpeg").strip()
        return ffmpeg_tools.probe_video(ffmpeg_path or "ffmpeg", str(path))
    except Exception:
        return None


def _default_job_state(dest: str) -> Optional[str]:
    """What broll_fetch's registry says about this destination, or None.
    Read-only: it never starts a download and never pops a finished one."""
    try:
        from . import broll_fetch

        return broll_fetch.job_state(dest)
    except Exception:
        return None


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
        self._prune_locked()

    def _prune_locked(self) -> None:
        """Drop entries whose file is gone AND which are older than
        PRUNE_AFTER_SECONDS (comp-broll-tiers-5). Never persists by itself:
        the next write carries it, so a read-only pass costs no I/O.

        Order matters and is the module docstring's: absence alone leaves an
        entry standing. Only the pair - no file, and long enough ago that no
        download or lane B pass is still owed - retires one.

        comp-broll-tiers-1 (2026-09-18b): and only while the TREE IS THERE.
        "Cannot be stat'ed" is not "has been deleted": an external sync drive
        pulled (CR-92), a share not yet mapped at companion start (the
        LUT-index startup race), an SMB blip or a NAS reboot makes every entry
        unstattable at once, and this prune would then drop every old row and
        let the next write persist it - after which a 1080p H.264 lie reads as
        the real original for ever. A prune that cannot tell does nothing.
        """
        cutoff = time.time() - PRUNE_AFTER_SECONDS
        stale = []
        roots: dict[str, bool] = {}
        for key, entry in self._entries.items():
            try:
                placed = float(entry.get("placed_at") or 0.0)
            except (TypeError, ValueError):
                placed = 0.0
            if placed > cutoff:
                continue
            if _size_of(entry.get("local_path")) is not None:
                continue
            root = _archive_root_of(entry.get("local_path"))
            if root is None:
                continue  # cannot tell where this file's tree is
            if root not in roots:
                roots[root] = _isdir(root)
            if not roots[root]:
                continue  # the tree is not here, so nothing here is gone
            stale.append(key)
        for key in stale:
            self._entries.pop(key, None)
        if stale:
            log.info("b-roll stand-ins: forgot %d entr(ies) whose file has been "
                     "gone for over %d days", len(stale),
                     int(PRUNE_AFTER_SECONDS // 86400))

    def _persist_locked(self) -> bool:
        payload = {"version": 1, "standins": self._entries}
        target = self.path
        tmp = target.with_name(f"{target.name}.{os.getpid()}.tmp")
        try:
            target.parent.mkdir(parents=True, exist_ok=True)
            tmp.write_text(json.dumps(payload, indent=1), encoding="utf-8")
            os.replace(tmp, target)
        except (OSError, TypeError, ValueError) as exc:
            # tests-4 (2026-09-18): TypeError/ValueError are in here because
            # `json.dumps` is, and a value json cannot encode (a geometry
            # field off the wire that is not a number) used to come back out
            # of `record()` as an exception - the ONE method in this module
            # that could raise, against a docstring that says none can, on
            # the path that writes the ledger row BEFORE the import.
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
        pending_fetch: bool = False,
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
            # proxy-tiers-1 (2026-09-18b): this row is an INTENT - written
            # before the fetch, about a file that is not there yet - and it
            # carries no size, so nothing about the file can falsify it.
            # `settle_intents` is the only thing that answers such a row, and
            # this flag is how it tells one from an ordinary entry whose size
            # simply could not be read.
            "pending_fetch": bool(pending_fetch),
            "upgrade": upgrade,
            "upgrade_note": "",
        }
        if not key:
            return entry
        with self._lock:
            self._load_locked()
            previous = self._entries.get(key)
            self._entries[key] = entry
            if not self._persist_locked():
                # tests-4: the entry went into the in-memory dict BEFORE the
                # write, so a payload the writer cannot serialise used to
                # poison every later persist in the process too - every
                # subsequent stand-in silently unwritten, and `is_standin`
                # answering True from a dict no file agrees with. Put the
                # previous state back and let the caller see the entry it
                # asked for; a lost row is this module's stated cost of a
                # failed write.
                if previous is None:
                    self._entries.pop(key, None)
                else:
                    self._entries[key] = previous
        log.warning(
            "b-roll stand-in: %s now holds the PREVIEW's bytes, not the original. "
            "Resolve will read its geometry from that file, and a render on this "
            "computer would render it (plan section 6, 2026-09-17)",
            entry["local_path"],
        )
        return entry

    def settle_intents(self, probe_fn: Optional[Any] = None,
                       job_state_fn: Optional[Any] = None) -> int:
        """Answer every pre-fetch INTENT row. Returns how many it changed.

        proxy-tiers-1 (2026-09-18b). The insert path writes the ledger row
        BEFORE the fetch, so a download nobody polls again (tab closed, laptop
        asleep, companion restarted) is still remembered - but with no size,
        and `_entry_is_stale` reads a non-int size as "still a stand-in"
        unconditionally, so such a row could be falsified by nothing at all,
        not even the real original arriving at that path.

        SETTLED BY IDENTITY, NEVER BY PRESENCE (2026-09-18b). A file appearing
        at that path is not proof the fetch landed: after a fetch that failed
        unobserved, lane B or the editor's own copy can put the REAL ORIGINAL
        there, and measuring that would record the original's size as the
        stand-in's - permanently, because the size then never changes again.
        `is_standin` would answer True for the real 6K file, the preview would
        be attached as its proxy and the rel broadcast to the fleet, which is
        proxy-tiers-1's exact outcome reached through the settlement.
        "Under-trusting a file is the safe direction" is NOT true of a real
        original.

        So the file's own header is read (`probe_video`, one open, never
        `-count_packets`) and compared with the geometry the row carries.
        NOTE THE POLARITY: that geometry is the ORIGINAL's, not the
        preview's - it comes from the `videos` row, which the indexer probed
        from the source clip (docs/BROLL_PROXY_TIERS_PLAN.md line 294, and
        `routes_api._insert_object`). So:

          * the header MATCHES the row's geometry -> this is the real
            original, and the row is RETIRED with a line saying so -- except
            for an original no taller than the preview, whose preview has
            the same geometry: there a codec other than the preview's H.264
            retires it and anything else asks the job record
            (logic-broll-music-2, 2026-09-25);
          * the header DIFFERS -> the preview's bytes under the original's
            name, i.e. the stand-in we meant to place, so the row is MEASURED
            and becomes falsifiable by size again;
          * no geometry on the row, or a header that cannot be read -> ask
            `broll_fetch`'s own job record for that destination: DONE
            measures, FAILED retires, and anything else (no such job, which
            after a restart is every job there ever was) LEAVES THE ROW
            PENDING. A row that cannot be settled is not guessed at.

        A path with no file at all after INTENT_EXPIRY_SECONDS is a download
        that never landed and is retired - and only while the tree is
        demonstrably there, for comp-broll-tiers-1's reason.

        Called from the 120 s relink cycle, which is why the window can be
        hours: a fetch that lands is settled within two minutes of landing.
        """
        changed = 0
        now = time.time()
        roots: dict[str, bool] = {}
        with self._lock:
            self._load_locked()
            for key, entry in list(self._entries.items()):
                if not entry.get("pending_fetch"):
                    continue
                path = entry.get("local_path")
                size = _size_of(path)
                if size is not None:
                    verdict = self._what_landed(entry, probe_fn, job_state_fn)
                    if verdict is None:
                        continue  # cannot tell: the row stays pending
                    if verdict is False:
                        self._entries.pop(key, None)
                        changed += 1
                        log.info("b-roll stand-ins: the real original arrived "
                                 "at %s, so the stand-in entry goes", path)
                        continue
                    entry["pending_fetch"] = False
                    entry["size"] = size
                    self._entries[key] = entry
                    changed += 1
                    log.info("b-roll stand-ins: the download for %s landed "
                             "while nobody was watching -- %d bytes, and the "
                             "entry can be falsified again", path, size)
                    continue
                try:
                    placed = float(entry.get("placed_at") or 0.0)
                except (TypeError, ValueError):
                    placed = 0.0
                if not placed or now - placed <= INTENT_EXPIRY_SECONDS:
                    continue
                root = _archive_root_of(path)
                if root is None:
                    continue
                if root not in roots:
                    roots[root] = _isdir(root)
                if not roots[root]:
                    continue  # the tree is away; nothing here is an answer
                self._entries.pop(key, None)
                changed += 1
                log.info("b-roll stand-ins: no file ever arrived at %s -- the "
                         "download did not happen, so the entry goes", path)
            if changed:
                self._persist_locked()
        return changed

    @staticmethod
    def _what_landed(entry: dict[str, Any], probe_fn: Optional[Any],
                     job_state_fn: Optional[Any]) -> Optional[bool]:
        """True: the stand-in we placed. False: the real original. None:
        cannot tell, which is the answer that leaves the row alone.

        The two questions in order, and every failure in either falls through
        to the next rather than to a guess (proxy-tiers-1).
        """
        path = entry.get("local_path")
        wanted = _geometry_wh(entry.get("geometry"))
        if wanted:
            probe = probe_fn if probe_fn is not None else _default_probe
            try:
                header = probe(path)
            except Exception:
                header = None
            measured = _geometry_wh(header)
            if measured:
                if measured != wanted:
                    # Not the original's geometry: the preview's bytes.
                    return True
                if not _preview_keeps_geometry(wanted):
                    # The original's own geometry at the original's own path
                    # is the original: the preview of anything taller than
                    # the preview height is scaled down and cannot match.
                    return False
                # logic-broll-music-2 (2026-09-25): but the preview is scaled
                # to min(1080, ih) and NEVER upscaled, so for an original of
                # 1080 lines or fewer the stand-in has the original's exact
                # geometry, and such an original is still "heavy" whenever
                # its codec is not h264/hevc/prores or its bitrate is over
                # the cap (DNxHD, 1080p H.264 at 50 Mbps). Equal geometry
                # retired the row as "the real original arrived" and left
                # the preview's bytes under the original's name, unmarked:
                # proxy-tiers-1's outcome, which CR-288B/2 set out to
                # prevent. Geometry cannot tell the two apart here. The
                # preview is always H.264, so any other codec IS the
                # original; H.264 or unknown falls through to the job
                # record below, and a row nothing can settle stays pending.
                codec = str((header or {}).get("codec") or "").strip().lower()
                if codec and codec != PREVIEW_CODEC:
                    return False
        ask = job_state_fn if job_state_fn is not None else _default_job_state
        try:
            state = ask(str(path or ""))
        except Exception:
            state = None
        if state == "done":
            return True
        if state == "failed":
            return False
        return None

    def settle_landed(self, local_path: Any) -> bool:
        """The fetch THIS process ran for an intent row has landed: measure
        the row now. True when a row changed.

        bug-comp-broll-3 (2026-09-25): the insert's documented "BEFORE the
        import, always" rewrite runs only on a poll that reads the job as
        DONE, and that poll never happens (see `broll_fetch.reap_finished`),
        so the clip was imported while its row was still a sizeless intent.
        If the dashboard sent no geometry and the companion restarted inside
        the 120 s `settle_intents` window, nothing could ever settle it:
        `job_state` answers None after a restart. Called only with the job
        record's own DONE for this destination, which is the same evidence
        `settle_intents` accepts; the upgrade state is left to the insert.
        """
        key = normalise_key(local_path)
        if not key:
            return False
        with self._lock:
            self._load_locked()
            entry = self._entries.get(key)
            if not isinstance(entry, dict) or not entry.get("pending_fetch"):
                return False
            size = _size_of(entry.get("local_path") or local_path)
            if size is None:
                return False
            entry = dict(entry)
            entry["pending_fetch"] = False
            entry["size"] = size
            self._entries[key] = entry
            self._persist_locked()
        log.info("b-roll stand-ins: the download for %s landed -- %d bytes, "
                 "and the entry can be falsified again", local_path, size)
        return True

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
                    note: str = "", count_attempt: bool = False,
                    reset_attempts: bool = False) -> bool:
        """Mark the background editing-proxy upgrade pending/done/failed.

        `count_attempt` records that one full attempt was spent and got
        nowhere (comp-broll-tiers-2); `reset_attempts` hands the budget back,
        and only an editor asking for that clip again does that.
        """
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
            if reset_attempts:
                entry["upgrade_attempts"] = 0
            elif count_attempt:
                entry["upgrade_attempts"] = _attempts_of(entry) + 1
            self._entries[key] = entry
            self._persist_locked()
        return True

    def pending_upgrades(self) -> list[dict[str, Any]]:
        """Entries whose editing proxy is still owed. A restart, or a Resolve
        that was closed when the download finished, only DELAYS the upgrade:
        this is what the next cycle drains.

        An entry that has spent UPGRADE_MAX_ATTEMPTS is NOT in here
        (comp-broll-tiers-2): it stays `pending` so the next insert of that
        clip picks it up, but the cycle stops spawning a thread and a Resolve
        worker child for it every two minutes.
        """
        return [entry for entry in self.all()
                if entry.get("upgrade") == UPGRADE_PENDING
                and entry.get("edit_proxy_rel")
                and _attempts_of(entry) < UPGRADE_MAX_ATTEMPTS]

    def given_up_upgrades(self) -> list[dict[str, Any]]:
        """Entries whose editing proxy will not arrive without a new ask:
        `failed`, or pending past the attempt ceiling.

        comp-broll-tiers-5: an editor in this state is cutting on a 1080p
        preview believing it is the editing proxy, and until now that fact
        reached the log and nothing else.
        """
        out = []
        for entry in self.all():
            if entry.get("upgrade") == UPGRADE_FAILED:
                out.append(entry)
            elif (entry.get("upgrade") == UPGRADE_PENDING
                  and _attempts_of(entry) >= UPGRADE_MAX_ATTEMPTS):
                out.append(entry)
        return out


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
    """Never raises, like its five siblings below (tests-4, 2026-09-18).

    This was the one public wrapper in the file without the guard, against a
    module docstring that says no method here raises - and it is the one
    called on the insert path, before the import, with values that came off
    the wire.
    """
    try:
        return ledger().record(local_path, **kwargs)
    except Exception:
        log.debug("b-roll stand-ins: could not record %r", local_path,
                  exc_info=True)
        return {}


def settle_landed(local_path: Any) -> bool:
    try:
        return ledger().settle_landed(local_path)
    except Exception:
        log.debug("b-roll stand-ins: could not settle %r", local_path,
                  exc_info=True)
        return False


def forget(local_path: Any) -> bool:
    try:
        return ledger().forget(local_path)
    except Exception:
        log.debug("b-roll stand-ins: could not forget %r", local_path,
                  exc_info=True)
        return False


def get(local_path: Any) -> Optional[dict[str, Any]]:
    return ledger().get(local_path)


def settle_intents(probe_fn: Optional[Any] = None,
                   job_state_fn: Optional[Any] = None) -> int:
    try:
        return ledger().settle_intents(probe_fn=probe_fn,
                                       job_state_fn=job_state_fn)
    except Exception:
        log.debug("b-roll stand-ins: could not settle the intent rows",
                  exc_info=True)
        return 0


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


def set_upgrade(local_path: Any, state: Optional[str], note: str = "",
                count_attempt: bool = False, reset_attempts: bool = False) -> bool:
    try:
        return ledger().set_upgrade(local_path, state, note,
                                    count_attempt=count_attempt,
                                    reset_attempts=reset_attempts)
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


def given_up_upgrades() -> list[dict[str, Any]]:
    try:
        return ledger().given_up_upgrades()
    except Exception:
        log.debug("b-roll stand-ins: could not read the given-up upgrades",
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
