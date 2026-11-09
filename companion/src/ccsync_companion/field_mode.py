"""Field backup: the rules, with no I/O to a dashboard and no threads.

Companion half of footage-sorter docs/LEDGER-BROWSER-DESIGN.md, "The companion" item 4
(Alex, 2026-11-09: "we need some way of making the card backup flexible so for example I can
still use it in the field onto field drives"). This module is the part of it that is pure
enough to test to the byte:

  * WHAT A CARD HAS THAT NEEDS BACKING UP (`tracked`): the ledger's own rules, from
    ledger_scan.Rules (masters and audio; a proxy, a sidecar, a `._` twin and a temp file are not);
  * WHAT KIND A VOLUME IS (`KindResolver`) and what counts: the October rules, ported from
    the razer laptop's lib/ledger.js and cloud/ledger/src/index.js `verdict()`:
        safe = at home (a `nas` copy), or two live copies on DIFFERENT volumes that count
               (`ours`, `laptop`, `nas`); client drives, cards and unknown drives never count;
        a result that rests on laptop copies alone is flagged (`laptopOnly`);
  * THE CARD'S VERDICT (`card_verdict`): "safe to format" only when EVERY tracked file is safe;
  * WHERE A CARD LANDS (`card_folder_name`): `<day> <card label or serial>`, as the October field
    tools named a loose card (`2026-10-20 F614401B loose`), with the card's own tree beneath it;
  * THE QUICK VERIFY Alex chose in the field (`quick_compare`, a port of lib/ingest/quickverify.js):
    size, first and last MiB, and for QuickTime/MP4/BRAW the moov box. Never a full read-back;
  * what this machine has copied that the ledger mirror cannot know yet (`LocalCopies`), and the
    little file that remembers the last destinations (`FieldStore`).

A COPY THIS MACHINE JUST MADE COUNTS AT ONCE. The mirror only learns of it after the outbox is
delivered AND the next pull, which in a tent is never; so `LocalCopies` keeps what was verified
here and `LedgerView` merges it with the mirror. An entry the mirror has caught up with is dropped
(it would say the same thing twice); an old one expires, so a file deleted since does not stay
"safe" forever.
"""
from __future__ import annotations

import json
import logging
import os
import re
import threading
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable, Iterable, Optional

from . import config as config_mod
from . import ledger_scan

log = logging.getLogger("ccsync.fieldmode")

# -- the October rules (rules.js COUNTS / TIME_SLACK_MS) ------------------------------------------
KINDS = ("nas", "ours", "laptop", "client", "card", "unknown")
USER_KINDS = ("ours", "laptop", "client", "unknown")   # what a person may set on a destination
COUNTS = frozenset({"ours", "laptop", "nas"})
TIME_SLACK_MS = 3000          # the ledger's match window (exFAT keeps 2 s)
EXISTING_SLACK_MS = 2500      # "already there": the copy's mtime vs the card's
LOCAL_COPY_DAYS = 30
MAX_LOCAL_COPIES = 60_000
DEFAULT_POOL_VOLUME = "nas:thecreatorspool"

PROXY_DIRS = frozenset({"proxy", "proxies", "sub", "thmbnl"})
_PROXY_NAME = re.compile(r"S03\.mp4$", re.IGNORECASE)
_GENERIC_LABELS = frozenset({
    "", "no name", "noname", "untitled", "eos_digital", "nikon", "lumix", "canon", "sd", "sdcard",
    "sd card", "usb drive", "removable disk", "disk", "new volume", "card", "dcim"})

_RULES = ledger_scan.Rules()


# -- what is tracked ----------------------------------------------------------------------------
def is_proxy_path(rel: str) -> bool:
    """A proxy by where it lives (a Proxy folder, a Sony SUB folder) or what it is called (…S03.MP4)."""
    parts = str(rel or "").replace("\\", "/").split("/")
    if any(p.lower() in PROXY_DIRS for p in parts[:-1]):
        return True
    return bool(_PROXY_NAME.search(parts[-1]))


def is_tracked(rel: str) -> bool:
    """Does the ledger track this file as a MASTER or AUDIO (what "safe to format" is about)?"""
    name = str(rel or "").replace("\\", "/").rsplit("/", 1)[-1]
    return _RULES.keep_file(name) and not is_proxy_path(rel)


def is_recordable(rel: str) -> bool:
    """Would the ledger accept this file as a copy (masters, audio, and the proxies it tracks)?
    A proxy is recorded when it is a video in a proxy folder; nothing else is."""
    name = str(rel or "").replace("\\", "/").rsplit("/", 1)[-1]
    if is_tracked(rel):
        return True
    return is_proxy_path(rel) and _RULES.keep_file(name, in_proxy=True)


def tracked_files(files: Iterable[Any]) -> list[list[Any]]:
    """[rel, size, mtimeMs] rows -> only the tracked ones."""
    return [list(f) for f in files if is_tracked(str(f[0]))]


# -- naming ---------------------------------------------------------------------------------------
_BAD_NAME = re.compile(r'[<>:"/\\|?*\x00-\x1f]+')


def clean_name(text: Any) -> str:
    return _BAD_NAME.sub("_", str(text or "")).strip(" .").strip()


def card_day(files: Iterable[Any], fallback: Optional[datetime] = None) -> str:
    """The shooting day of a card (local date of its newest file), YYYY-MM-DD. A card copied
    again tomorrow lands in the SAME folder, so the second run finds what the first one did."""
    newest = 0.0
    for f in files:
        try:
            newest = max(newest, float(f[2]))
        except (TypeError, ValueError, IndexError):
            continue
    if newest > 0:
        try:
            return datetime.fromtimestamp(newest / 1000.0).strftime("%Y-%m-%d")
        except (OverflowError, OSError, ValueError):
            pass
    return (fallback or datetime.now()).strftime("%Y-%m-%d")


def card_folder_name(label: str, serial: str, day: str) -> str:
    """`2026-10-20 F614401B`: the day and the card's label, or its serial when the label says
    nothing ("NO NAME", "EOS_DIGITAL"), so two blank cards never share a folder."""
    lab = clean_name(label)
    ident = clean_name(serial) if lab.lower() in _GENERIC_LABELS else lab
    return f"{day} {ident or 'card'}".strip()


# -- kinds ----------------------------------------------------------------------------------------
def guess_kind(label: str = "", removable: bool = False, system: bool = False,
               folder: bool = False, pool: bool = False) -> str:
    """The October `kindOf`, from what the machine can say about a drive:
    a label CIB_D<n> is ours; WD-<n> or a Passport is a client's; a card reader is a card; the
    NAS pool is the NAS; a folder on a laptop's own drive is the laptop. Anything else is
    `unknown` (it counts for nothing) until a person says what it is."""
    lab = str(label or "")
    if pool:
        return "nas"
    if re.fullmatch(r"CIB_D\d+", lab, re.IGNORECASE):
        return "ours"
    if re.fullmatch(r"WD-\d+", lab, re.IGNORECASE) or re.search(r"passport", lab, re.IGNORECASE):
        return "client"
    if removable and not folder:
        return "card"
    if folder or system:
        return "laptop"
    return "unknown"


class KindResolver:
    """volume id -> kind. A person's choice wins, then what the ledger says, then what this
    machine can tell from the drive itself. Never raises."""

    def __init__(self, overrides: Optional[Callable[[], dict[str, str]]] = None,
                 info: Optional[Callable[[], dict[str, dict[str, Any]]]] = None,
                 guesses: Optional[Callable[[], dict[str, str]]] = None) -> None:
        self._overrides = overrides or (lambda: {})
        self._info = info or (lambda: {})
        self._guesses = guesses or (lambda: {})

    def kind(self, volume_id: str) -> str:
        try:
            chosen = str(self._overrides().get(volume_id) or "")
            if chosen in KINDS:
                return chosen
            known = str((self._info().get(volume_id) or {}).get("kind") or "")
            if known in KINDS and known != "unknown":
                return known
            guess = str(self._guesses().get(volume_id) or "")
            if guess in KINDS:
                return guess
            if volume_id.startswith("nas:"):
                return "nas"
        except Exception:                                         # noqa: BLE001
            log.debug("field: kind lookup failed for %s", volume_id, exc_info=True)
        return "unknown"

    def label(self, volume_id: str, fallback: str = "") -> str:
        try:
            got = str((self._info().get(volume_id) or {}).get("label") or "")
        except Exception:                                         # noqa: BLE001
            got = ""
        return got or fallback or volume_id


# -- the verdict ----------------------------------------------------------------------------------
def file_verdict(copies: list[dict[str, Any]], kind_of: Callable[[str], str]) -> dict[str, Any]:
    """One file's standing, from its live copies (each `{volume_id, ...}`; the card's own volume is
    expected to be excluded by the caller, and a card never counts anyway):
    {safe, home, onLaptop, laptopOnly, counted, volumes}."""
    vols: dict[str, str] = {}
    for c in copies:
        vid = str(c.get("volume_id") or "")
        if vid and vid not in vols:
            vols[vid] = kind_of(vid)
    counted = {v for v, k in vols.items() if k in COUNTS}
    home = any(k == "nas" for k in vols.values())
    on_laptop = any(k == "laptop" for k in vols.values())
    elsewhere = any(k in ("ours", "nas") for k in vols.values())
    return {"safe": home or len(counted) >= 2, "home": home, "onLaptop": on_laptop,
            "laptopOnly": on_laptop and not elsewhere, "counted": len(counted),
            "volumes": sorted(vols)}


def card_verdict(files: list[list[Any]], copies_of: Callable[[str, int, Any], list[dict[str, Any]]],
                 kind_of: Callable[[str], str], dest_volumes: Optional[dict[str, str]] = None,
                 exclude_volumes: Iterable[str] = (), sample: int = 40) -> dict[str, Any]:
    """The card's verdict from the ledger's copies of its tracked files.

    `copies_of(name, size, mtime)` is the lookup (mirror + this machine's own); `dest_volumes`
    is {destination id: volume id} so the answer can say how much each destination already holds.
    `exclude_volumes` are the card's own volume id(s). Returns

      {tracked, bytes, safe, home, single, none, laptopOnly, safeToFormat, state, headline,
       flags, perDest: {dest id: {have, of}}, atRisk: [{path, size, copies: n}]}

    `state`: "safe" | "unsafe" | "empty" (nothing on the card to back up). `safeToFormat` is only
    true when EVERY tracked file is safe -- one stray file and the card is not."""
    skip = set(exclude_volumes)
    dests = dest_volumes or {}
    out: dict[str, Any] = {"tracked": 0, "bytes": 0, "safe": 0, "home": 0, "single": 0, "none": 0,
                           "laptopOnly": 0, "uncounted": 0, "safeToFormat": False, "state": "empty",
                           "headline": "", "flags": [], "perDest": {d: {"have": 0, "of": 0} for d in dests},
                           "atRisk": [], "notes": []}
    uncounted_labels: set[str] = set()
    for rel, size, mtime, *_rest in files:
        if not is_tracked(rel):
            continue
        size, name = int(size), str(rel).rsplit("/", 1)[-1]
        rows = [c for c in copies_of(name, size, mtime) if c.get("volume_id") not in skip]
        v = file_verdict(rows, kind_of)
        out["tracked"] += 1
        out["bytes"] += size
        held = set(v["volumes"])
        for d, vid in dests.items():
            out["perDest"][d]["of"] += 1
            if vid in held:
                out["perDest"][d]["have"] += 1
        for vid in held:
            if kind_of(vid) not in COUNTS:
                uncounted_labels.add(vid)
        if v["safe"]:
            out["safe"] += 1
            out["home"] += 1 if v["home"] else 0
            out["laptopOnly"] += 1 if v["laptopOnly"] else 0
            continue
        n = len(held)
        if n == 0:
            out["none"] += 1
        else:
            out["single"] += 1
        if v["counted"] < 2 and n > v["counted"]:
            out["uncounted"] += 1
        if len(out["atRisk"]) < sample:
            out["atRisk"].append({"path": rel, "size": size, "copies": n, "counted": v["counted"]})
    t = out["tracked"]
    if t == 0:
        out["headline"] = "Nothing on this card needs backing up."
        return out
    if out["safe"] == t:
        out["state"], out["safeToFormat"] = "safe", True
        if out["laptopOnly"]:
            out["flags"].append("laptop-only")
        if out["home"] == t:
            out["headline"] = f"Safe to format: all {t} files are at home."
        elif out["laptopOnly"]:
            out["headline"] = (f"Safe to format, but {out['laptopOnly']} of {t} files rest on the laptop "
                               f"alone. Put one on a field drive when you can.")
        else:
            out["headline"] = f"Safe to format: all {t} files are on two drives that count."
        return out
    out["state"] = "unsafe"
    bits = []
    if out["none"]:
        bits.append(f"{out['none']} with no copy")
    if out["single"]:
        bits.append(f"{out['single']} with one copy")
    out["headline"] = f"Not safe to format yet: {t - out['safe']} of {t} files are short ({', '.join(bits)})."
    if out["uncounted"]:
        out["notes"].append("Some copies are on drives that do not count (a client's drive, a card, "
                            "or a drive with no kind set).")
    return out


# -- the quick verify -------------------------------------------------------------------------------
MIB = 1 << 20
ISO_EXTS = frozenset({".mp4", ".mov", ".m4v", ".braw"})
MOOV_MAX = 64 * MIB


def _read_at(fh: Any, pos: int, length: int) -> bytes:
    fh.seek(pos)
    got = b""
    while len(got) < length:
        chunk = fh.read(length - len(got))
        if not chunk:
            break
        got += chunk
    return got


def walk_boxes(fh: Any, size: int) -> dict[str, Any]:
    """The top-level ISO-BMFF boxes (lib/ingest/health.js walkBoxes). Bodies are never read."""
    boxes: list[dict[str, Any]] = []
    off = 0
    n = 0
    while n < 256 and off < size:
        n += 1
        head = _read_at(fh, off, 16)
        if len(head) < 8:
            return {"boxes": boxes, "stop": "short", "at": off}
        length = int.from_bytes(head[0:4], "big")
        kind = head[4:8]
        if not all(0x20 <= b <= 0x7E for b in kind):
            return {"boxes": boxes, "stop": "garbage", "at": off}
        if length == 1:
            if len(head) < 16:
                return {"boxes": boxes, "stop": "short", "at": off}
            length = int.from_bytes(head[8:16], "big")
        elif length == 0:
            length = size - off
        if length < 8:
            return {"boxes": boxes, "stop": "garbage", "at": off}
        if off + length > size:
            return {"boxes": boxes, "stop": "overrun", "at": off}
        boxes.append({"type": kind.decode("latin1"), "off": off, "len": length})
        off += length
    return {"boxes": boxes, "stop": "eof" if off >= size else "limit", "at": off}


def _same_range(a: Any, b: Any, pos: int, length: int, what: str) -> Optional[str]:
    x, y = _read_at(a, pos, length), _read_at(b, pos, length)
    if len(x) != length:
        return f"read failed: the source gave {len(x)} of {length} bytes of the {what}"
    if x != y:
        return f"the copy's {what} differs from the source's"
    return None


def quick_compare(src: "str | Path", dst: "str | Path", ext: str = "") -> dict[str, Any]:
    """Alex's simple verification of a copy (2026-10-18): the size, the first and last MiB, and for
    QuickTime-family files the moov box (Sony and BMCC write it AFTER the media, so the head alone
    never reaches it). -> {ok, error?, warning?, checked, unreadable?}. Never a full read-back."""
    checked: list[str] = []
    try:
        with open(src, "rb") as a, open(dst, "rb") as b:
            size_a, size_b = os.fstat(a.fileno()).st_size, os.fstat(b.fileno()).st_size
            if size_a != size_b:
                return {"ok": False, "error": f"the copy is {size_b} bytes, the source {size_a}",
                        "checked": checked}
            size = size_a
            checked.append("size")
            n = min(MIB, size)
            err = _same_range(a, b, 0, n, "first 1 MiB")
            if err:
                return {"ok": False, "error": err, "checked": checked}
            checked.append("head")
            if size > n:
                err = _same_range(a, b, size - n, n, "last 1 MiB")
                if err:
                    return {"ok": False, "error": err, "checked": checked}
            checked.append("tail")
            kind = (ext or Path(str(src)).suffix).lower()
            if kind not in ISO_EXTS:
                return {"ok": True, "checked": checked}
            ws = walk_boxes(a, size)
            moov = next((x for x in ws["boxes"] if x["type"] == "moov"), None)
            if moov is None:
                return {"ok": True, "checked": checked,
                        "warning": "the source has no moov (index): the clip itself is damaged, "
                                   "not the copy"}
            wd = walk_boxes(b, size)
            m2 = next((x for x in wd["boxes"] if x["type"] == "moov"), None)
            if m2 is None or m2["off"] != moov["off"] or m2["len"] != moov["len"]:
                return {"ok": False, "checked": checked,
                        "error": "the copy's moov (index) is not where the source's is"}
            if wd["stop"] not in ("eof", "limit"):
                return {"ok": False, "checked": checked,
                        "error": f"the copy's boxes do not run to its end ({wd['stop']} at {wd['at']})"}
            if moov["len"] <= MOOV_MAX:
                err = _same_range(a, b, moov["off"], moov["len"], "moov")
            else:
                err = (_same_range(a, b, moov["off"], MIB, "start of the moov")
                       or _same_range(a, b, moov["off"] + moov["len"] - MIB, MIB, "end of the moov"))
            if err:
                return {"ok": False, "error": err, "checked": checked}
            checked.append("moov")
            return {"ok": True, "checked": checked}
    except OSError as exc:
        return {"ok": False, "error": f"cannot read it ({exc})", "unreadable": True, "checked": checked}


def same_mtime(a_ms: Any, b_ms: Any, slack_ms: int = EXISTING_SLACK_MS) -> bool:
    try:
        return abs(float(a_ms) - float(b_ms)) <= slack_ms
    except (TypeError, ValueError):
        return False


# -- the small files ----------------------------------------------------------------------------------
def default_state_path() -> Path:
    return config_mod.CONFIG_DIR / "field-state.json"


def default_copies_path() -> Path:
    return config_mod.CONFIG_DIR / "field-local-copies.jsonl"


def _atomic_write(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name(path.name + f".{os.getpid()}.tmp")
    with open(tmp, "w", encoding="utf-8", newline="\n") as fh:
        fh.write(text)
        fh.flush()
        os.fsync(fh.fileno())
    os.replace(tmp, path)


class FieldStore:
    """What the page remembers on this machine: the last destinations ticked, the laptop folders
    added from the page, and the kinds a person set. One small JSON file, written atomically; a
    torn or foreign file reads as empty. Never raises."""

    def __init__(self, path: Optional["str | Path"] = None) -> None:
        self.path = Path(path) if path else default_state_path()
        self._lock = threading.RLock()

    def _load(self) -> dict[str, Any]:
        try:
            doc = json.loads(self.path.read_text(encoding="utf-8-sig"))
        except (OSError, ValueError):
            return {}
        return doc if isinstance(doc, dict) else {}

    def _save(self, doc: dict[str, Any]) -> None:
        try:
            _atomic_write(self.path, json.dumps(doc, indent=1, sort_keys=True))
        except OSError:
            log.warning("field: could not save %s", self.path, exc_info=True)

    def get(self, key: str, default: Any) -> Any:
        with self._lock:
            got = self._load().get(key, default)
        return got if isinstance(got, type(default)) else default

    def put(self, key: str, value: Any) -> None:
        with self._lock:
            doc = self._load()
            doc[key] = value
            self._save(doc)

    def last_dests(self) -> list[str]:
        return [str(x) for x in self.get("last_dests", []) if isinstance(x, str)]

    def remember_dests(self, ids: Iterable[str]) -> None:
        self.put("last_dests", [str(i) for i in ids])

    def folders(self) -> list[str]:
        return [str(x) for x in self.get("folders", []) if isinstance(x, str) and x]

    def add_folder(self, path: str) -> list[str]:
        with self._lock:
            have = self.folders()
            if path.lower() not in {h.lower() for h in have}:
                have.append(path)
                self.put("folders", have)
            return have

    def remove_folder(self, path: str) -> list[str]:
        with self._lock:
            keep = [h for h in self.folders() if h.lower() != path.lower()]
            self.put("folders", keep)
            return keep

    def kinds(self) -> dict[str, str]:
        raw = self.get("kinds", {})
        return {str(k): str(v) for k, v in raw.items() if str(v) in KINDS}

    def set_kind(self, volume_id: str, kind: str) -> None:
        with self._lock:
            raw = dict(self.get("kinds", {}))
            if kind in USER_KINDS and kind != "unknown":
                raw[volume_id] = kind
            else:
                raw.pop(volume_id, None)
            self.put("kinds", raw)


def _iso_to_epoch(text: Any) -> float:
    try:
        return datetime.fromisoformat(str(text).replace("Z", "+00:00")).timestamp()
    except (TypeError, ValueError):
        return 0.0


class LocalCopies:
    """The verified copies THIS machine made, kept until the ledger mirror has them too.

    One JSON line per copy: {volume_id, label, kind, path, name, size, mtime, verified, at}.
    Appended durably as each lane finishes; loaded once; an entry is dropped when the mirror
    returns a live row for the same volume, or after LOCAL_COPY_DAYS."""

    def __init__(self, path: Optional["str | Path"] = None,
                 clock: Callable[[], float] = time.time) -> None:
        self.path = Path(path) if path else default_copies_path()
        self._clock = clock
        self._lock = threading.RLock()
        self._rows: Optional[list[dict[str, Any]]] = None

    def _all(self) -> list[dict[str, Any]]:
        if self._rows is None:
            rows: list[dict[str, Any]] = []
            cutoff = self._clock() - LOCAL_COPY_DAYS * 86400
            try:
                with open(self.path, "r", encoding="utf-8") as fh:
                    for line in fh:
                        try:
                            row = json.loads(line)
                        except ValueError:
                            continue
                        if isinstance(row, dict) and row.get("volume_id") and row.get("name"):
                            if _iso_to_epoch(row.get("at")) >= cutoff or not row.get("at"):
                                rows.append(row)
            except OSError:
                pass
            self._rows = rows[-MAX_LOCAL_COPIES:]
        return self._rows

    def add(self, copies: Iterable[dict[str, Any]]) -> int:
        added = 0
        with self._lock:
            rows = self._all()
            lines = []
            for c in copies:
                try:
                    row = {"volume_id": str(c["volume_id"]), "label": str(c.get("label") or ""),
                           "kind": str(c.get("kind") or ""), "path": str(c["path"]),
                           "name": str(c.get("name") or str(c["path"]).rsplit("/", 1)[-1]),
                           "size": int(c["size"]),
                           "mtime": None if c.get("mtime") is None else int(c["mtime"]),
                           "verified": str(c.get("verified") or "quick"),
                           "at": str(c.get("at") or datetime.now(timezone.utc).replace(
                               microsecond=0).isoformat().replace("+00:00", "Z"))}
                except (KeyError, TypeError, ValueError):
                    continue
                rows[:] = [r for r in rows if not (r["volume_id"] == row["volume_id"]
                                                   and r["path"] == row["path"])]
                rows.append(row)
                lines.append(json.dumps(row, separators=(",", ":")))
                added += 1
            if lines:
                try:
                    self.path.parent.mkdir(parents=True, exist_ok=True)
                    with open(self.path, "a", encoding="utf-8", newline="\n") as fh:
                        fh.write("\n".join(lines) + "\n")
                        fh.flush()
                        os.fsync(fh.fileno())
                except OSError:
                    log.warning("field: could not note the copies made here", exc_info=True)
        return added

    def matching(self, name: str, size: int, mtime: Any = None) -> list[dict[str, Any]]:
        lc = str(name).lower()
        with self._lock:
            hits = [r for r in self._all() if r["name"].lower() == lc and r["size"] == int(size)]
        out = []
        for r in hits:
            if mtime is not None and r.get("mtime") is not None \
                    and abs(int(r["mtime"]) - float(mtime)) > TIME_SLACK_MS:
                continue
            out.append(dict(r))
        return out

    def forget(self, rows: Iterable[dict[str, Any]]) -> None:
        """Drop entries the mirror now covers."""
        gone = {(r["volume_id"], r["path"]) for r in rows}
        if not gone:
            return
        with self._lock:
            keep = [r for r in self._all() if (r["volume_id"], r["path"]) not in gone]
            self._rows = keep
            try:
                _atomic_write(self.path, "".join(json.dumps(r, separators=(",", ":")) + "\n" for r in keep)
                              if keep else "")
            except OSError:
                log.debug("field: could not rewrite %s", self.path, exc_info=True)

    def __len__(self) -> int:
        with self._lock:
            return len(self._all())


class LedgerView:
    """The mirror and this machine's own copies, as one lookup: `copies(name, size, mtime)` ->
    live copies `[{volume_id, path, verified, source}]`. No network."""

    def __init__(self, mirror: Any, local: LocalCopies) -> None:
        self.mirror = mirror
        self.local = local

    def copies(self, name: str, size: int, mtime: Any = None) -> list[dict[str, Any]]:
        try:
            rows = [dict(r, source="mirror") for r in self.mirror.where(name, size, mtime)]
        except Exception:                                         # noqa: BLE001
            log.debug("field: the mirror could not be read", exc_info=True)
            rows = []
        have = {r["volume_id"] for r in rows}
        mine = self.local.matching(name, size, mtime)
        covered = [m for m in mine if m["volume_id"] in have]
        if covered:
            self.local.forget(covered)
        for m in mine:
            if m["volume_id"] not in have:
                rows.append(dict(m, source="local"))
        return rows
