"""The copies this computer made that the dashboard's ledger has not heard about yet.

footage-sorter docs/LEDGER-BROWSER-DESIGN.md, "The companion" item 4: the field
page copies a card to three drives in a tent with no network. Each verified
copy is written HERE first, at once, and sent to

  POST {dashboard_url}/sorter/agent/ledger/copies   {copies: [...], machine}

whenever the dashboard is reachable (the route is idempotent on volume + path +
size + mtime, so a re-sent line costs nothing). The same outbox catches a
`drive-copy` whose receipt could not be delivered.

A SMALL, STABLE API, because more than one thing writes to it:

    append(copies, path=None) -> int     queue copies (durable before it returns)
    pending(path=None) -> int            how many are waiting
    flush(send=None, path=None, ...)     send what is waiting; keep what could not go
    OutboxFlusher(cfg, ...)              the thread that calls flush() while anything waits

A COPY is `{volume: {serial, label}, path, name, size, mtime, verified, tool, at}`:
`path` is '/'-separated and relative to the volume root, `mtime` is epoch
milliseconds (or None), `verified` is "listed" | "quick" | "full", `at` an ISO
time. `append` fills `name`, `tool` and `at` when they are missing and drops
what cannot be a ledger row (no serial, no path, a negative size).

THE FILE is `~/.ccsync/ledger-outbox.jsonl`, one JSON object per line
`{"copy": {...}, "queued": "<iso>"}`. Appends are one write + fsync under a lock;
a torn last line (power cut mid-write) is skipped on read, never fatal. Nothing
is deleted until the dashboard has said 200 for it; a batch the dashboard
REFUSES (a 4xx that is not about credentials) moves to
`ledger-outbox.rejected.jsonl` beside it, so a poison line cannot wedge the
queue and is not lost either.
"""
from __future__ import annotations

import json
import logging
import os
import platform
import threading
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable, Iterable, Optional

from . import config as config_mod

log = logging.getLogger("ccsync.ledgeroutbox")

FILENAME = "ledger-outbox.jsonl"
REJECTED_FILENAME = "ledger-outbox.rejected.jsonl"
AGENT_PATH = "/sorter/agent/ledger/copies"
BATCH = 500                      # copies per POST (the route takes 5,000; this keeps a body small)
MAX_QUEUED = 200_000
POST_TIMEOUT_SECONDS = 30.0
FLUSH_SECONDS = 60.0
NO_SORTER_BACKOFF_SECONDS = 600.0
VERIFIED_LEVELS = ("listed", "quick", "full")

_lock = threading.RLock()


def default_path() -> Path:
    return config_mod.CONFIG_DIR / FILENAME


def path_for(cfg: Optional[dict[str, Any]]) -> Optional[Path]:
    """Where a runner with this config keeps the outbox: `ledger_outbox_path` if set, else beside
    the log (`~/.ccsync`), else None (a harness with no log_path writes nothing into the home
    folder of whoever runs the suite)."""
    explicit = str((cfg or {}).get("ledger_outbox_path") or "").strip()
    if explicit:
        return Path(explicit).expanduser()
    if not str((cfg or {}).get("log_path") or "").strip():
        return None
    try:
        return config_mod.resolved_log_path(cfg or {}).parent / FILENAME
    except Exception:                                             # noqa: BLE001
        return None


def _now_iso() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def _p(path: Optional[Path | str]) -> Path:
    return Path(path) if path else default_path()


def normalize(copy: Any) -> Optional[dict[str, Any]]:
    """One copy -> the wire shape, or None when it cannot be a ledger row. Never raises."""
    try:
        if not isinstance(copy, dict):
            return None
        vol = copy.get("volume") if isinstance(copy.get("volume"), dict) else {}
        serial = str(vol.get("serial") or "").strip().upper()
        rel = str(copy.get("path") or "").replace("\\", "/").strip("/")
        if not serial or not rel or ".." in rel.split("/"):
            return None
        size = int(copy.get("size"))
        if size < 0:
            return None
        mtime = copy.get("mtime")
        mtime = None if mtime is None else int(round(float(mtime)))
        verified = str(copy.get("verified") or "full")
        if verified not in VERIFIED_LEVELS:
            verified = "listed"
        return {
            "volume": {"serial": serial, "label": str(vol.get("label") or "")},
            "path": rel,
            "name": str(copy.get("name") or rel.rsplit("/", 1)[-1]),
            "size": size,
            "mtime": mtime,
            "verified": verified,
            "tool": str(copy.get("tool") or "companion"),
            "at": str(copy.get("at") or _now_iso()),
        }
    except (TypeError, ValueError, OverflowError):
        return None


def key_of(copy: dict[str, Any]) -> tuple:
    """The route's own idempotency key: volume + path + size + mtime."""
    return (copy["volume"]["serial"], copy["path"], copy["size"], copy["mtime"])


def _read(path: Path) -> list[dict[str, Any]]:
    """Every readable line. A torn or foreign line is skipped (and left for the next rewrite to drop)."""
    out: list[dict[str, Any]] = []
    try:
        with open(path, "r", encoding="utf-8") as fh:
            for line in fh:
                line = line.strip()
                if not line:
                    continue
                try:
                    item = json.loads(line)
                except ValueError:
                    continue
                if isinstance(item, dict) and isinstance(item.get("copy"), dict):
                    out.append(item)
    except FileNotFoundError:
        pass
    except OSError:
        log.debug("ledger outbox: cannot read %s", path, exc_info=True)
    return out


def _write_all(path: Path, items: list[dict[str, Any]]) -> None:
    """Replace the file with exactly these lines (write a sibling, fsync, replace)."""
    tmp = path.with_name(path.name + ".tmp")
    if not items:
        try:
            path.unlink()
        except FileNotFoundError:
            pass
        return
    with open(tmp, "w", encoding="utf-8", newline="\n") as fh:
        for item in items:
            fh.write(json.dumps(item, separators=(",", ":")) + "\n")
        fh.flush()
        os.fsync(fh.fileno())
    os.replace(tmp, path)


def append(copies: Iterable[dict[str, Any]], path: Optional[Path | str] = None) -> int:
    """Queue copies, durably. -> how many were queued (a copy already waiting with the same key,
    or one that cannot be a ledger row, is not). Never raises: the copy it describes has
    already happened, and failing to note it must not fail the copy."""
    target = _p(path)
    try:
        with _lock:
            existing = _read(target)
            seen = {key_of(i["copy"]) for i in existing if _valid(i["copy"])}
            room = MAX_QUEUED - len(existing)
            lines: list[str] = []
            for raw in copies or ():
                c = normalize(raw)
                if c is None or key_of(c) in seen:
                    continue
                if room <= 0:
                    log.warning("ledger outbox: full (%d copies waiting), not queueing more", MAX_QUEUED)
                    break
                seen.add(key_of(c))
                room -= 1
                lines.append(json.dumps({"copy": c, "queued": _now_iso()}, separators=(",", ":")))
            if not lines:
                return 0
            target.parent.mkdir(parents=True, exist_ok=True)
            torn = False
            try:
                with open(target, "rb") as fh:                  # a torn last line has no newline: do not glue onto it
                    fh.seek(0, os.SEEK_END)
                    if fh.tell():
                        fh.seek(-1, os.SEEK_END)
                        torn = fh.read(1) != b"\n"
            except OSError:
                pass
            with open(target, "a", encoding="utf-8", newline="\n") as fh:
                fh.write(("\n" if torn else "") + "\n".join(lines) + "\n")
                fh.flush()
                os.fsync(fh.fileno())
            return len(lines)
    except Exception:                                             # noqa: BLE001
        log.warning("ledger outbox: could not queue copies", exc_info=True)
        return 0


def _valid(copy: dict[str, Any]) -> bool:
    try:
        key_of(copy)
        return True
    except (KeyError, TypeError):
        return False


def pending(path: Optional[Path | str] = None) -> int:
    with _lock:
        return len(_read(_p(path)))


def peek(path: Optional[Path | str] = None, limit: int = 100) -> list[dict[str, Any]]:
    """The waiting copies (oldest first), for a page that shows what is not yet in the ledger."""
    with _lock:
        return [i["copy"] for i in _read(_p(path))[:limit]]


SendFn = Callable[[list[dict[str, Any]]], tuple[int, Any]]


def flush(send: Optional[SendFn] = None, path: Optional[Path | str] = None,
          cfg: Optional[dict[str, Any]] = None,
          identity_token_fn: Optional[Callable[[], Optional[str]]] = None,
          batch: int = BATCH, machine: str = "") -> dict[str, Any]:
    """Send what is waiting. -> {sent, accepted, duplicates, rejected, remaining, status}.

    `send(copies) -> (status, parsed)` is the seam; without one, the dashboard in `cfg` is called
    with the fleet credential. 200 removes the batch. A transport failure, 5xx, 404/503 (no sorter
    here yet), 401 or 403 stops the flush and keeps everything. Another 4xx moves the batch to the
    rejected file (it will never be accepted as it is) and carries on. Never raises."""
    target = _p(path)
    out = {"sent": 0, "accepted": 0, "duplicates": 0, "rejected": 0, "remaining": 0, "status": None}
    if send is None:
        send = make_sender(cfg or {}, identity_token_fn, machine)
        if send is None:
            out["remaining"] = pending(target)
            return out
    try:
        while True:
            with _lock:
                items = _read(target)
            if not items:
                break
            chunk = items[:max(1, int(batch))]
            try:
                status, parsed = send([i["copy"] for i in chunk])
            except Exception as exc:                              # noqa: BLE001
                log.debug("ledger outbox: could not reach the dashboard (%s)", exc)
                break
            out["status"] = int(status)
            if status == 200:
                out["sent"] += len(chunk)
                if isinstance(parsed, dict):
                    out["accepted"] += int(parsed.get("accepted") or 0)
                    out["duplicates"] += int(parsed.get("duplicates") or 0)
                _drop(target, chunk)
                continue
            if status in (401, 403, 404, 503, 429) or status >= 500:
                break
            log.warning("ledger outbox: the dashboard refused %d copies (HTTP %s); set aside in %s",
                        len(chunk), status, REJECTED_FILENAME)
            _set_aside(target, chunk)
            out["rejected"] += len(chunk)
    except Exception:                                             # noqa: BLE001
        log.warning("ledger outbox: flush failed", exc_info=True)
    out["remaining"] = pending(target)
    return out


def _drop(target: Path, sent: list[dict[str, Any]]) -> None:
    """Remove exactly the lines that were sent, keeping anything appended while the POST was out."""
    with _lock:
        gone = {json.dumps(i, sort_keys=True) for i in sent}
        keep = [i for i in _read(target) if json.dumps(i, sort_keys=True) not in gone]
        _write_all(target, keep)


def _set_aside(target: Path, bad: list[dict[str, Any]]) -> None:
    with _lock:
        side = target.with_name(REJECTED_FILENAME)
        with open(side, "a", encoding="utf-8", newline="\n") as fh:
            for item in bad:
                fh.write(json.dumps(item, separators=(",", ":")) + "\n")
        _drop(target, bad)


def make_sender(cfg: dict[str, Any], identity_token_fn: Optional[Callable[[], Optional[str]]] = None,
                machine: str = "", request_fn: Optional[Callable[..., tuple[int, Any]]] = None
                ) -> Optional[SendFn]:
    """A `send` bound to the dashboard in `cfg`, or None when there is no dashboard or token."""
    url = str((cfg or {}).get("dashboard_url", "") or "").strip().rstrip("/")
    token = str((cfg or {}).get("dashboard_token", "") or "").strip()
    if not url or not token:
        return None

    def send(copies: list[dict[str, Any]]) -> tuple[int, Any]:
        request = request_fn
        if request is None:
            from .broll_ingest import default_request
            request = default_request
        identity = ""
        if identity_token_fn is not None:
            try:
                identity = str(identity_token_fn() or "")
            except Exception:                                     # noqa: BLE001
                log.debug("ledger outbox: identity_token_fn failed", exc_info=True)
        headers = {"Content-Type": "application/json", "X-CCSync-Token": str((cfg or {}).get("dashboard_token", "") or "").strip(),
                   "X-CCSync-Identity": identity}
        return request("POST", f"{url}{AGENT_PATH}",
                       {"copies": copies, "machine": machine or platform.node()},
                       headers, POST_TIMEOUT_SECONDS)
    return send


# ------------------------------------------------------------ from a receipt
def copies_from_receipt(receipt: dict[str, Any], volumes_fn: Callable[..., list[dict[str, Any]]],
                        tool: str = "") -> list[dict[str, Any]]:
    """The verified copies in a card_copy receipt that landed on a LOCAL drive (`local:<serial>`
    destinations: a `drive-copy`), as ledger copies. Pool destinations are the server's to record
    (it holds the pool); an unverified copy is not a backup and is skipped. The destination's
    mtime is read from the file itself. Never raises."""
    out: list[dict[str, Any]] = []
    try:
        vols = {str(v.get("serial") or "").upper(): v for v in volumes_fn("all", set())}
    except Exception:                                             # noqa: BLE001
        return out
    tool = tool or str(receipt.get("copier") or "python")
    for item in receipt.get("copied") or []:
        try:
            dst = item.get("dst") if isinstance(item.get("dst"), dict) else {}
            root = str(dst.get("root") or "")
            if not root.lower().startswith("local:") or not item.get("verified"):
                continue
            serial = root[6:].upper()
            vol = vols.get(serial)
            rel = str(dst.get("rel") or "").replace("\\", "/").strip("/")
            if vol is None or not rel:
                continue
            mtime = None
            try:
                mtime = int(round(os.stat(os.path.join(str(vol.get("root") or ""), *rel.split("/"))).st_mtime * 1000))
            except OSError:
                pass
            out.append({"volume": {"serial": serial, "label": str(vol.get("label") or "")},
                        "path": rel, "name": str(item.get("filename") or rel.rsplit("/", 1)[-1]),
                        "size": int(item.get("size") or 0), "mtime": mtime,
                        "verified": "full", "tool": tool, "at": _now_iso()})
        except (TypeError, ValueError, AttributeError):
            continue
    return out


# --------------------------------------------------------------- the flusher
class OutboxFlusher:
    """A thread that flushes the outbox every minute while anything waits, and at once on `kick()`."""

    def __init__(self, cfg: dict[str, Any], identity_token_fn: Optional[Callable[[], Optional[str]]] = None,
                 path: Optional[Path | str] = None, send: Optional[SendFn] = None,
                 clock: Callable[[], float] = time.monotonic, machine: str = "") -> None:
        self.cfg = cfg if cfg is not None else {}
        self._identity = identity_token_fn
        self._path = path
        self._send = send
        self._clock = clock
        self._machine = machine
        self._backoff_until = 0.0
        self._wake = threading.Event()
        self._stop = threading.Event()
        self._thread: Optional[threading.Thread] = None
        self.last: Optional[dict[str, Any]] = None

    @property
    def enabled(self) -> bool:
        raw = self.cfg.get("sorter_ledger_enabled", True)
        if isinstance(raw, str):
            return raw.strip().lower() not in ("0", "false", "no", "off", "")
        return bool(raw)

    def start(self) -> None:
        if self._thread is not None or not self.enabled:
            return
        self._stop.clear()
        self._thread = threading.Thread(target=self._loop, name="ccsync-ledger-outbox", daemon=True)
        self._thread.start()

    def stop(self) -> None:
        self._stop.set()
        self._wake.set()
        thread, self._thread = self._thread, None
        if thread is not None:
            thread.join(timeout=5.0)

    def kick(self) -> None:
        self._wake.set()

    def _loop(self) -> None:
        while not self._stop.is_set():
            self._wake.clear()
            try:
                self.tick()
            except Exception:                                     # noqa: BLE001
                log.exception("ledger outbox: the tick failed")
            self._wake.wait(FLUSH_SECONDS)

    def tick(self) -> Optional[dict[str, Any]]:
        """One pass. -> the flush result, or None when nothing waited / it is backing off."""
        if not self.enabled or self._clock() < self._backoff_until:
            return None
        path = self._path or path_for(self.cfg) or default_path()
        if pending(path) == 0:
            return None
        result = flush(self._send, path, self.cfg, self._identity, machine=self._machine)
        self.last = result
        if result.get("status") in (404, 503):
            self._backoff_until = self._clock() + NO_SORTER_BACKOFF_SECONDS
        return result
