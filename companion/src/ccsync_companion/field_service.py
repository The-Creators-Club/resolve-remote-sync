"""Field backup: what the page shows, and what its buttons do.

Glue between the pure rules (field_mode), the copy engine (field_copy), the sorter's card
detection (sorter_cards), and the ledger plumbing (ledger_mirror, ledger_outbox). The HTTP layer
(field_server) is a thin skin over `FieldService`; everything here is callable and testable with
no server, no card reader and no dashboard (every seam is a constructor parameter).

WHAT THE PAGE KNOWS, and from where:

  * CARDS: removable volumes that `sorter_cards.classify` recognises, listed with
    `sorter_cards.list_card`. A removable volume that is plainly a field drive (labelled CIB_D<n>
    or WD-<n>, or marked by the person) is a drive, not a card, even though it holds footage.
  * DESTINATIONS: every attached non-system volume (labelled from the ledger when it knows the
    volume), the laptop folders (config `field_dest_folders` plus those added on the page), and
    the NAS pool (`jobs_pool_root`) when it can be reached. Which were ticked last is remembered
    per machine (field_mode.FieldStore).
  * THE VERDICT: from the offline mirror plus what this machine copied itself, never the network.
    A copy made here counts the moment it is verified (field_mode.LocalCopies).

THE LEDGER LEG. Each lane's verified copies go to the outbox (`tool: field`) and, if the dashboard
answers, to the ledger at once; a successful delivery is followed by a mirror pull so the verdicts
catch up. Offline, nothing is lost and nothing blocks: the outbox keeps them, the next flush sends.
"""
from __future__ import annotations

import logging
import os
import platform
import shutil
import threading
import time
from pathlib import Path
from typing import Any, Callable, Optional

from . import config as config_mod
from . import field_copy, field_mode, ledger_mirror, ledger_outbox, sorter_cards
from . import teracopy as teracopy_mod

log = logging.getLogger("ccsync.fieldservice")

SCAN_TTL_SECONDS = 4.0
CARD_TTL_SECONDS = 30.0
VERDICT_TTL_SECONDS = 20.0
SYNC_EVERY_SECONDS = 300.0
PROBE_SECONDS = 2.5
DRIVE_FOLDER = "FieldBackup"


def enabled(cfg: dict[str, Any]) -> bool:
    """`field_server_enabled`, default on. Tolerates a hand-edited string."""
    raw = (cfg or {}).get("field_server_enabled", True)
    if isinstance(raw, str):
        return raw.strip().lower() not in ("0", "false", "no", "off", "")
    return bool(raw)


def probe_dir(path: str, timeout: float = PROBE_SECONDS) -> bool:
    """Is this a reachable directory? A dead SMB share can hang a stat for half a minute, so the
    look is made on a thread and given up on."""
    box: list[bool] = []

    def look() -> None:
        try:
            box.append(os.path.isdir(path))
        except OSError:
            box.append(False)

    t = threading.Thread(target=look, daemon=True, name="ccsync-field-probe")
    t.start()
    t.join(timeout)
    return bool(box and box[0])


def physical_key(root: str) -> str:
    """Which physical disk holds this volume ("disk:3"), or "" when it cannot be told. Windows:
    IOCTL_STORAGE_GET_DEVICE_NUMBER on the volume, which needs no rights. Two partitions of one disk
    share a key; two USB drives never do."""
    if os.name != "nt":
        return ""
    try:
        import ctypes
        from ctypes import wintypes

        letter = os.path.splitdrive(str(root))[0]
        if len(letter) != 2 or letter[1] != ":":
            return ""
        k32 = ctypes.windll.kernel32                              # type: ignore[attr-defined]
        k32.CreateFileW.restype = wintypes.HANDLE
        k32.CreateFileW.argtypes = [wintypes.LPCWSTR, wintypes.DWORD, wintypes.DWORD, ctypes.c_void_p,
                                    wintypes.DWORD, wintypes.DWORD, wintypes.HANDLE]
        k32.DeviceIoControl.argtypes = [wintypes.HANDLE, wintypes.DWORD, ctypes.c_void_p, wintypes.DWORD,
                                        ctypes.c_void_p, wintypes.DWORD, ctypes.POINTER(wintypes.DWORD),
                                        ctypes.c_void_p]
        k32.CloseHandle.argtypes = [wintypes.HANDLE]
        handle = k32.CreateFileW(f"\\\\.\\{letter}", 0, 3, None, 3, 0, None)
        if handle in (None, ctypes.c_void_p(-1).value, -1):
            return ""

        class DeviceNumber(ctypes.Structure):
            _fields_ = [("DeviceType", wintypes.DWORD), ("DeviceNumber", wintypes.DWORD),
                        ("PartitionNumber", wintypes.DWORD)]

        info, got = DeviceNumber(), wintypes.DWORD(0)
        try:
            ok = k32.DeviceIoControl(handle, 0x002D1080, None, 0, ctypes.byref(info),
                                     ctypes.sizeof(info), ctypes.byref(got), None)
        finally:
            k32.CloseHandle(handle)
        return f"disk:{info.DeviceNumber}" if ok else ""
    except Exception:                                             # noqa: BLE001
        return ""


def _norm(path: str) -> str:
    return os.path.normcase(os.path.normpath(str(path))).rstrip("\\/")


def _under(path: str, root: str) -> bool:
    p, r = _norm(path), _norm(root)
    return p == r or p.startswith(r + os.sep) or (r.endswith(":") and p.startswith(r))


class FieldService:
    def __init__(
        self,
        cfg: dict[str, Any],
        identity_token_fn: Optional[Callable[[], Optional[str]]] = None,
        volumes_fn: Optional[Callable[..., list[dict[str, Any]]]] = None,
        classify_fn: Optional[Callable[..., Optional[str]]] = None,
        list_card_fn: Optional[Callable[..., dict[str, Any]]] = None,
        mirror: Optional[ledger_mirror.LedgerMirror] = None,
        store: Optional[field_mode.FieldStore] = None,
        local: Optional[field_mode.LocalCopies] = None,
        request_fn: Optional[Callable[..., tuple[int, Any]]] = None,
        teracopy_fn: Optional[Callable[[], tuple[Optional[teracopy_mod.TeraCopy], str]]] = None,
        outbox_path: Optional["str | Path"] = None,
        physical_fn: Optional[Callable[[str], str]] = None,
        probe_fn: Optional[Callable[[str], bool]] = None,
        free_fn: Optional[Callable[[str], int]] = None,
        alive_fn: Optional[Callable[[str], bool]] = None,
        machine_name: str = "",
        clock: Callable[[], float] = time.time,
        auto_sync: bool = True,
    ) -> None:
        self.cfg = cfg if cfg is not None else {}
        self._identity = identity_token_fn
        self._volumes = volumes_fn or sorter_cards.list_volumes
        self._classify = classify_fn or sorter_cards.classify
        self._list_card = list_card_fn or sorter_cards.list_card
        self.store = store or field_mode.FieldStore(self.cfg.get("field_state_path") or None)
        self.local = local or field_mode.LocalCopies(self.cfg.get("field_copies_path") or None)
        self.mirror = mirror or ledger_mirror.LedgerMirror(
            self.cfg, request_fn=request_fn, identity_token_fn=identity_token_fn)
        self._request = request_fn
        self._teracopy_fn = teracopy_fn
        self._outbox_path = Path(outbox_path) if outbox_path else (
            ledger_outbox.path_for(self.cfg) or ledger_outbox.default_path())
        self._physical = physical_fn or physical_key
        self._probe = probe_fn or probe_dir
        self._clock = clock
        self._machine = machine_name or platform.node()
        self._auto_sync = auto_sync
        self._lock = threading.RLock()
        self._vols: list[dict[str, Any]] = []
        self._vols_at = 0.0
        self._cards: dict[str, dict[str, Any]] = {}          # serial -> {sig, at, card, files, root}
        self._guesses: dict[str, str] = {}
        self._verdicts: dict[str, tuple[float, str, dict[str, Any]]] = {}
        self._verdict_gen = 0
        self._physical_cache: dict[str, str] = {}
        self.sync_info: dict[str, Any] = {"at": None, "online": None, "error": "", "flushed": 0,
                                          "pending": 0, "pulledRows": 0, "running": False}
        self._sync_lock = threading.Lock()
        self._last_sync_try = 0.0
        self._info: tuple[float, dict[str, Any]] = (-1e9, {})
        self.resolver = field_mode.KindResolver(
            overrides=self.store.kinds, info=self._volume_info, guesses=lambda: self._guesses)
        self.view = field_mode.LedgerView(self.mirror, self.local)
        self.copier = field_copy.FieldCopier(field_copy.Services(
            cfg=self.cfg, view=self.view, volumes_fn=self._volumes, teracopy_fn=teracopy_fn,
            record_fn=self._record, on_lane_done=self._lane_done, on_run_done=self._run_done,
            free_fn=free_fn or (lambda p: int(shutil.disk_usage(p).free)),
            alive_fn=alive_fn or os.path.isdir))

    def _volume_info(self) -> dict[str, Any]:
        """What the ledger calls each volume ({id: {label, kind}}), re-read from the mirror at most
        every few seconds: a verdict asks for a kind per file."""
        now = self._clock()
        if now - self._info[0] > SCAN_TTL_SECONDS:
            try:
                self._info = (now, self.mirror.volume_info())
            except Exception:                                     # noqa: BLE001
                self._info = (now, {})
        return self._info[1]

    # ----------------------------------------------------------------------- volumes and cards
    def _scan(self, force: bool = False) -> list[dict[str, Any]]:
        now = self._clock()
        with self._lock:
            if not force and self._vols and now - self._vols_at < SCAN_TTL_SECONDS:
                return self._vols
            try:
                vols = list(self._volumes("all", sorter_cards.busy_roots()))
            except Exception:                                     # noqa: BLE001
                log.debug("field: could not list volumes", exc_info=True)
                vols = []
            # a card being copied from is not touched: it is reported as last seen
            seen = {str(v.get("serial", "")).upper() for v in vols}
            for serial in sorter_cards.busy_serials():
                held = self._cards.get(serial)
                if serial not in seen and held and held.get("vol"):
                    vols.append(held["vol"])
            self._vols, self._vols_at = vols, now
            # a volume that holds a laptop folder you configured IS the laptop's, whatever it is called
            with_folder = set()
            for folder in self.configured_folders():
                holder = self._volume_for_path(folder, vols)
                if holder is not None and holder.get("serial"):
                    with_folder.add(str(holder["serial"]).upper())
            for v in vols:
                serial = str(v.get("serial") or "").upper()
                if serial:
                    guess = field_mode.guess_kind(
                        v.get("label", ""), removable=bool(v.get("removable")), system=bool(v.get("system")))
                    if serial in with_folder and guess in ("unknown", "card"):
                        guess = "laptop"
                    self._guesses[f"vol:{serial}"] = guess
            return vols

    def _cards_from(self, vols: list[dict[str, Any]]) -> list[dict[str, Any]]:
        """Cards in readers, as {serial, label, root, drive, kind, capacity, free, files, ...}."""
        now = self._clock()
        out: list[dict[str, Any]] = []
        present: set[str] = set()
        busy = sorter_cards.busy_serials()
        for v in vols:
            serial = str(v.get("serial") or "").upper()
            if not serial or not v.get("removable") or v.get("system"):
                continue
            present.add(serial)
            vid = f"vol:{serial}"
            if self.resolver.kind(vid) in ("ours", "client", "laptop", "nas"):
                continue                                          # a field drive, not a card
            sig = (v.get("root"), v.get("capacity"), v.get("free"))
            held = self._cards.get(serial)
            if held and (serial in busy or (held["sig"] == sig and now - held["at"] < CARD_TTL_SECONDS)):
                card = held["card"]
            else:
                kind = self._classify(v["root"])
                if kind is None:
                    self._cards[serial] = {"sig": sig, "at": now, "card": None, "vol": v}
                    continue
                listing = self._list_card(v["root"])
                files = listing.get("files") or []
                card = {"serial": serial, "label": str(v.get("label") or ""), "drive": str(v.get("drive") or ""),
                        "root": str(v["root"]), "kind": kind, "capacity": int(v.get("capacity") or 0),
                        "free": int(v.get("free") or 0), "files": files}
                self._cards[serial] = {"sig": sig, "at": now, "card": card, "vol": v}
                self._verdict_gen += 1
            if card:
                out.append(card)
        for serial in list(self._cards):
            if serial not in present and serial not in busy:
                self._cards.pop(serial, None)
        out.sort(key=lambda c: (c["drive"], c["serial"]))
        return out

    # ------------------------------------------------------------------------------ destinations
    def _volume_for_path(self, path: str, vols: list[dict[str, Any]]) -> Optional[dict[str, Any]]:
        best, best_len = None, -1
        for v in vols:
            root = str(v.get("root") or "")
            if root and _under(path, root) and len(_norm(root)) > best_len:
                best, best_len = v, len(_norm(root))
        return best

    def _lane_key(self, root: str, fallback: str) -> str:
        if root not in self._physical_cache:
            self._physical_cache[root] = self._physical(root) or ""
        return self._physical_cache[root] or fallback

    def _label_for(self, vid: str, vol: dict[str, Any]) -> str:
        known = self.resolver.label(vid, "")
        if known and known != vid:
            return known
        return str(vol.get("label") or "").strip() or str(vol.get("drive") or vid)

    def pool_volume_id(self) -> str:
        explicit = str(self.cfg.get("field_pool_volume_id") or "").strip()
        if explicit:
            return explicit
        try:
            for vid in self._volume_info():
                if str(vid).startswith("nas:"):
                    return str(vid)
        except Exception:                                         # noqa: BLE001
            pass
        return field_mode.DEFAULT_POOL_VOLUME

    def configured_folders(self) -> list[str]:
        raw = self.cfg.get("field_dest_folders") or []
        if isinstance(raw, str):
            raw = [raw]
        out = [str(x).strip() for x in raw if str(x).strip()]
        for f in self.store.folders():
            if f.lower() not in {o.lower() for o in out}:
                out.append(f)
        return out

    def destinations(self, vols: Optional[list[dict[str, Any]]] = None,
                     cards: Optional[list[dict[str, Any]]] = None) -> list[field_copy.Destination]:
        vols = self._scan() if vols is None else vols
        cards = self._cards_from(vols) if cards is None else cards
        card_serials = {c["serial"] for c in cards if c["kind"] != "generic"}
        out: list[field_copy.Destination] = []
        for v in vols:
            serial = str(v.get("serial") or "").upper()
            if not serial or v.get("system") or serial in card_serials:
                continue
            vid = f"vol:{serial}"
            root = str(v.get("root") or "")
            label = self._label_for(vid, v)
            out.append(field_copy.Destination(
                id=vid, kind="drive", label=label, root=root, subdir=DRIVE_FOLDER, volume_id=vid,
                volume_label=label, volume_root=root, volume_kind=self.resolver.kind(vid), serial=serial,
                lane=self._lane_key(root, vid)))
        for folder in self.configured_folders():
            v = self._volume_for_path(folder, vols)
            name = Path(folder).name or folder
            if v is not None:
                serial = str(v.get("serial") or "").upper()
                vid = f"vol:{serial}" if serial else ""
                vol_label = (f"{self._machine} {v.get('drive')}" if self.resolver.kind(vid) == "laptop"
                             or not vid else self._label_for(vid, v))
                kind = self.resolver.kind(vid) if vid else "unknown"
                if kind in ("unknown", "card"):
                    kind = "laptop"                               # a folder you configured on a laptop's drive
                out.append(field_copy.Destination(
                    id=f"folder:{_norm(folder)}", kind="folder", label=name, root=folder, subdir="",
                    volume_id=vid, volume_label=vol_label, volume_root=str(v.get("root") or ""),
                    volume_kind=kind, serial=serial, lane=self._lane_key(str(v.get("root")), vid or folder),
                    recordable=bool(vid)))
            else:
                out.append(field_copy.Destination(
                    id=f"folder:{_norm(folder)}", kind="folder", label=name, root=folder, subdir="",
                    volume_id="", volume_kind="unknown", lane=f"path:{_norm(folder)}", recordable=False))
        pool = str(self.cfg.get("jobs_pool_root") or "").strip()
        if pool:
            sub = str(self.cfg.get("field_pool_folder") or DRIVE_FOLDER).strip().strip("\\/")
            out.append(field_copy.Destination(
                id="pool", kind="pool", label="NAS pool", root=pool, subdir=sub,
                volume_id=self.pool_volume_id(), volume_label="NAS pool", volume_root=pool,
                volume_kind="nas", lane="pool", recordable=False))
        return out

    def _dest_public(self, d: field_copy.Destination, vols: list[dict[str, Any]],
                     last: set[str], busy: set[str]) -> dict[str, Any]:
        present, why, free, capacity = True, "", None, None
        if d.kind == "pool":
            present = self._probe(d.root)
            why = "" if present else "The NAS pool cannot be reached from here."
        elif d.kind == "folder":
            v = self._volume_for_path(d.root, vols)
            present = v is not None
            why = "" if present else "That folder's drive is not connected."
            if present and not self._probe(d.root):
                # the folder is not made yet: its drive is there, the copy makes it
                present = os.path.isdir(str(v.get("root") or ""))
        if present:
            try:
                probe = d.root if os.path.isdir(d.root) else (d.volume_root or d.root)
                u = shutil.disk_usage(probe)
                free, capacity = int(u.free), int(u.total)
            except OSError:
                free = capacity = None
        kind = d.volume_kind
        return {"id": d.id, "type": d.kind, "label": d.label,
                "detail": (str(Path(d.root, d.subdir)) if d.subdir else d.root),
                "volumeId": d.volume_id, "kind": kind, "counts": kind in field_mode.COUNTS,
                "kindSource": ("you" if d.volume_id in self.store.kinds() else
                               ("ledger" if (self._volume_info().get(d.volume_id) or {}).get("kind") else "guess")),
                "settable": d.kind != "pool" and bool(d.volume_id), "present": present, "why": why,
                "free": free, "capacity": capacity, "lane": d.lane, "ticked": d.id in last,
                "busy": d.id in busy, "removable": d.kind == "folder", "recordable": d.recordable}

    # --------------------------------------------------------------------------------- verdicts
    def card_verdict(self, card: dict[str, Any], dests: list[field_copy.Destination]) -> dict[str, Any]:
        stamp = (f"{self._verdict_gen}:{len(self.local)}:{len(dests)}:{sorted(self.store.kinds().items())}"
                 f":{sorted(self._guesses.items())}")
        held = self._verdicts.get(card["serial"])
        now = self._clock()
        if held and held[1] == stamp and now - held[0] < VERDICT_TTL_SECONDS:
            return held[2]
        v = field_mode.card_verdict(
            card["files"], self.view.copies, self.resolver.kind,
            dest_volumes={d.id: d.volume_id for d in dests if d.volume_id},
            exclude_volumes=[f"vol:{card['serial']}"])
        mstat = self.mirror.status()
        if not mstat.get("rows") and not mstat.get("pulled_at"):
            v["notes"].append("This laptop has not heard from the ledger yet, so only copies made here count.")
        self._verdicts[card["serial"]] = (now, stamp, v)
        return v

    def invalidate(self) -> None:
        with self._lock:
            self._verdict_gen += 1
            self._verdicts.clear()

    # -------------------------------------------------------------------------------------- state
    def copier_info(self) -> dict[str, Any]:
        try:
            tc, why = (self._teracopy_fn or (lambda: teracopy_mod.detect(self.cfg)))()
        except Exception as exc:                                  # noqa: BLE001
            tc, why = None, str(exc)
        if tc is not None:
            return {"name": "TeraCopy", "verify": "TeraCopy's own hash check after every file", "why": ""}
        return {"name": "built-in copier", "verify": "every file read back in full and compared", "why": why}

    def state(self, refresh: bool = False) -> dict[str, Any]:
        vols = self._scan(force=refresh)
        with self._lock:
            cards = self._cards_from(vols)
        dests = self.destinations(vols, cards)
        last = set(self.store.last_dests())
        busy = self.copier.busy_dest_ids()
        public_dests = [self._dest_public(d, vols, last, busy) for d in dests]
        by_id = {p["id"]: p for p in public_dests}
        out_cards = []
        runs = {r["card"]["serial"]: r for r in self.copier.snapshot()}
        for c in cards:
            usable = [d for d in dests if by_id[d.id]["present"]]
            verdict = self.card_verdict(c, usable)
            files = c["files"]
            out_cards.append({
                "serial": c["serial"], "label": c["label"] or c["serial"], "drive": c["drive"], "kind": c["kind"],
                "capacity": c["capacity"], "free": c["free"], "files": len(files),
                "bytes": sum(int(f[1]) for f in files), "folder": field_mode.card_folder_name(
                    c["label"], c["serial"], field_mode.card_day(files)),
                "verdict": verdict, "copying": bool(runs.get(c["serial"], {}).get("running")),
            })
        if self._auto_sync and self._clock() - self._last_sync_try > SYNC_EVERY_SECONDS \
                and not any(r["running"] for r in self.copier.snapshot()):
            self.sync_soon()
        ms = self.mirror.status()
        return {
            "ok": True, "machine": self._machine, "now": self._clock(), "cards": out_cards,
            "destinations": public_dests, "runs": self.copier.snapshot(), "copier": self.copier_info(),
            "sync": {**self.sync_info, "pending": ledger_outbox.pending(self._outbox_path),
                     "mirrorRows": ms.get("rows", 0), "mirrorPulledAt": ms.get("pulled_at"),
                     "dashboard": bool(str(self.cfg.get("dashboard_url") or "").strip())},
            "folders": self.configured_folders(), "lastDests": list(last),
        }

    # ---------------------------------------------------------------------------------- actions
    def start_copy(self, serial: str, dest_ids: list[str]) -> dict[str, Any]:
        """Start a run. Raises ValueError with a sentence for anything that stops it."""
        serial = str(serial or "").strip().upper()
        vols = self._scan(force=True)
        with self._lock:
            cards = self._cards_from(vols)
        card = next((c for c in cards if c["serial"] == serial), None)
        if card is None:
            raise ValueError("that card is not in a reader any more. Put it back and look again.")
        wanted = [str(i) for i in dest_ids or [] if isinstance(i, str)]
        if not wanted:
            raise ValueError("tick at least one destination")
        dests = self.destinations(vols, cards)
        by_id = {d.id: d for d in dests}
        chosen: list[field_copy.Destination] = []
        for i in dict.fromkeys(wanted):
            d = by_id.get(i)
            if d is None:
                raise ValueError("one of the ticked destinations is not available any more. Look again.")
            if d.volume_id == f"vol:{serial}":
                raise ValueError("a card cannot be a destination for itself")
            pub = self._dest_public(d, vols, set(), set())
            if not pub["present"]:
                raise ValueError(f"{d.label}: {pub['why'] or 'not available'}")
            if d.kind == "folder":
                try:
                    os.makedirs(d.root, exist_ok=True)
                except OSError as exc:
                    raise ValueError(f"{d.label}: the folder cannot be made ({exc})") from None
            chosen.append(d)
        self.store.remember_dests([d.id for d in chosen])
        folder = field_mode.card_folder_name(card["label"], serial, field_mode.card_day(card["files"]))
        run = self.copier.start(card, chosen, folder)
        return run.snapshot()

    def cancel(self, run_id: str) -> bool:
        return self.copier.cancel(run_id)

    def add_folder(self, path: str) -> list[str]:
        text = str(path or "").strip().strip('"')
        if not text or not os.path.isabs(text) or ".." in Path(text).parts:
            raise ValueError("give the full path of a folder, like D:\\FieldBackup")
        vols = self._scan()
        if self._volume_for_path(text, vols) is None:
            raise ValueError("that folder is not on a drive this computer has right now")
        out = self.store.add_folder(os.path.normpath(text))
        self._vols_at = 0.0                                       # look again: the kinds follow the folders
        return out

    def remove_folder(self, path: str) -> list[str]:
        out = self.store.remove_folder(str(path or ""))
        self._vols_at = 0.0
        self.invalidate()
        return out

    def set_kind(self, volume_id: str, kind: str) -> None:
        if not str(volume_id).startswith("vol:"):
            raise ValueError("only a drive's kind can be set")
        if kind not in field_mode.USER_KINDS:
            raise ValueError("a drive is ours, a laptop's, a client's or unknown")
        self.store.set_kind(volume_id, kind)
        self.invalidate()

    def remember(self, dest_ids: list[str]) -> None:
        self.store.remember_dests([str(i) for i in dest_ids if isinstance(i, str)])

    def stop_all(self) -> None:
        for r in self.copier.snapshot():
            if r["running"]:
                self.copier.cancel(r["id"])

    # ------------------------------------------------------------------------- the ledger leg
    def _record(self, dest: field_copy.Destination, entries: list[dict[str, Any]]) -> int:
        """Called by a lane with its verified copies: noted here at once (they count now), queued in
        the outbox (when the volume has a serial), and sent if the dashboard answers."""
        if not entries or not dest.volume_id:
            return 0
        kind = self.resolver.kind(dest.volume_id) if dest.volume_id.startswith("vol:") else "nas"
        at = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())
        self.local.add([{"volume_id": dest.volume_id, "label": dest.volume_label, "kind": kind,
                         "path": e["path"], "name": e["name"], "size": e["size"], "mtime": e["mtime"],
                         "verified": e["verified"], "at": at} for e in entries])
        if dest.recordable and dest.serial:
            ledger_outbox.append(
                [{"volume": {"serial": dest.serial, "label": dest.volume_label, "kind": kind},
                  "path": e["path"], "name": e["name"], "size": e["size"], "mtime": e["mtime"],
                  "verified": e["verified"], "tool": "field", "at": at} for e in entries],
                self._outbox_path)
        self.invalidate()
        return len(entries)

    def _lane_done(self, lane: field_copy.Lane) -> None:
        self.invalidate()

    def _run_done(self, run: field_copy.FieldRun) -> None:
        self.invalidate()
        if self._auto_sync:
            self.sync_soon()

    def sync_soon(self) -> bool:
        """Deliver the outbox and pull the mirror, on a thread. -> False if one is already running."""
        if not self._sync_lock.acquire(blocking=False):
            return False
        self._last_sync_try = self._clock()
        self.sync_info["running"] = True
        threading.Thread(target=self._sync_thread, daemon=True, name="ccsync-field-sync").start()
        return True

    def _sync_thread(self) -> None:
        try:
            self.sync()
        finally:
            self.sync_info["running"] = False
            self._sync_lock.release()

    def sync(self) -> dict[str, Any]:
        """Flush the outbox, then (if the dashboard answered) pull the mirror. Never raises."""
        info: dict[str, Any] = {"at": self._clock(), "online": False, "error": "", "flushed": 0,
                                "pulledRows": 0}
        try:
            url = str(self.cfg.get("dashboard_url") or "").strip()
            token = str(self.cfg.get("dashboard_token") or "").strip()
            if not url or not token:
                info["error"] = "No dashboard is set up on this computer."
            else:
                send = ledger_outbox.make_sender(self.cfg, self._identity, self._machine, self._request)
                res = ledger_outbox.flush(send, self._outbox_path, self.cfg, self._identity, machine=self._machine)
                info["flushed"] = int(res.get("sent") or 0)
                reached = res.get("status") == 200
                ids = {f"vol:{str(v.get('serial') or '').upper()}" for v in self._scan() if v.get("serial")}
                ids.add(self.pool_volume_id())
                pulled = self.mirror.pull(ids)
                info["online"] = bool(reached or pulled.get("ok"))
                info["pulledRows"] = int(pulled.get("rows") or 0)
                if not info["online"]:
                    info["error"] = ("The dashboard could not be reached. Copies are kept here and sent "
                                     "when it can.")
                elif not pulled.get("ok"):
                    info["error"] = f"The ledger was not refreshed: {pulled.get('error')}"
        except Exception as exc:                                  # noqa: BLE001
            log.debug("field: sync failed", exc_info=True)
            info["error"] = f"Could not sync: {exc}"
        info["pending"] = ledger_outbox.pending(self._outbox_path)
        self.sync_info.update(info)
        self._info = (-1e9, {})                                   # the pull may have named volumes
        self.invalidate()
        return dict(self.sync_info)
