"""The copier behind the `card-ingest` and `drive-copy` fleet jobs.

Step 3 of "Card ingest through the companion: the protocol"
(footage-sorter docs/DASHBOARD-MODULE-PLAN.md, 2026-11-09). A portable
replacement for TeraCopy (which was Windows-only): plain Python, large
buffers, no subprocess.

Rules, each with its reason:

  * **NEVER OVERWRITE.** A destination that exists at the same size is
    `skipped`; anything else there is a `conflict` and is left alone. Footage
    is irreplaceable and a copier that "fixes" a mismatch by writing over it
    has destroyed whichever side was right.
  * **A FILE APPEARS ONLY WHEN IT IS WHOLE AND VERIFIED.** Bytes go to
    `<dst>.partial`, are fsynced, quick-verified (size, plus the first and
    last 1 MiB byte-identical to the source: the verification Alex chose for
    footage), and only then renamed into place. A halt, a verify mismatch or
    an error deletes the `.partial`; none is ever left behind. The rename
    cannot clobber (Windows `rename` refuses an existing name; elsewhere a
    hard link is made and the partial unlinked), so a file that arrived
    between the check and the rename is a conflict, not a casualty.
  * **THE WRONG CARD IS REFUSED.** The job names a card by volume serial. If
    the drive now holds another card, or the card is not in a reader here,
    nothing is copied and the failure is not retryable: the job was aimed at
    this machine and another machine cannot fix it.
  * **THE VOLUME IS NOT READ BY ANYTHING ELSE WHILE IT IS COPIED**
    (`sorter_cards.ingest_busy`).

Roots in a copy's `src` / `dst`: `{"root": "pool"|"vault"|"media"|"tree", "rel"}`
placed by job_paths; `local:<volume serial>` for a PC drive (a `drive-copy`);
and, for a card-ingest, a bare string `src` is a path on the card named by
`inputs.serial`. A `drive-copy` with bare-string sources reads them from
`inputs.src_root` (`local:<serial>`).
"""
from __future__ import annotations

import logging
import os
from pathlib import Path
from typing import Any, Callable, Optional

from . import job_paths, sorter_cards

log = logging.getLogger("ccsync.cardcopy")

KIND_CARD_INGEST = "card-ingest"
KIND_DRIVE_COPY = "drive-copy"
CARD_KINDS = (KIND_CARD_INGEST, KIND_DRIVE_COPY)

BUFFER_BYTES = 8 * 1024 * 1024
VERIFY_BYTES = 1024 * 1024
PARTIAL_SUFFIX = ".partial"


class CardJobError(Exception):
    """The job cannot run here. `retryable` as job_paths.JobPathError."""

    def __init__(self, message: str, retryable: bool = False):
        super().__init__(message)
        self.retryable = bool(retryable)


class _Stopped(Exception):
    def __init__(self, reason: str):
        super().__init__(reason)
        self.reason = reason


class Progress:
    """done / of files, bytes processed / total. Read by the heartbeat thread,
    written by the copy thread; plain ints, so a torn read is merely a beat
    that is one file stale."""

    def __init__(self, of: int = 0, total_bytes: int = 0):
        self.of = int(of)
        self.total_bytes = int(total_bytes)
        self.done = 0
        self.bytes = 0

    def snapshot(self) -> dict[str, int]:
        return {"done": int(self.done), "of": int(self.of), "bytes": int(self.bytes)}

    @property
    def fraction(self) -> Optional[float]:
        if self.total_bytes > 0:
            return max(0.0, min(1.0, self.bytes / self.total_bytes))
        if self.of > 0:
            return max(0.0, min(1.0, self.done / self.of))
        return None


# -------------------------------------------------------------- primitives
def _read_exact_at(fh: Any, offset: int, n: int) -> bytes:
    fh.seek(offset)
    return fh.read(n)


def quick_verify(src: Path, dst: Path, size: int) -> str:
    """-> "" when `dst` matches `src` by quick verify, else the reason."""
    try:
        dst_size = dst.stat().st_size
    except OSError as exc:
        return f"the copy cannot be read back ({exc})"
    if dst_size != size:
        return f"the copy is {dst_size} bytes and the source {size}"
    if size == 0:
        return ""
    n = min(VERIFY_BYTES, size)
    try:
        with open(src, "rb") as a, open(dst, "rb") as b:
            if _read_exact_at(a, 0, n) != _read_exact_at(b, 0, n):
                return "the first megabyte differs from the source"
            if size > n:
                tail = min(VERIFY_BYTES, size)
                if (_read_exact_at(a, size - tail, tail)
                        != _read_exact_at(b, size - tail, tail)):
                    return "the last megabyte differs from the source"
    except OSError as exc:
        return f"the copy could not be verified ({exc})"
    return ""


def _publish(partial: Path, dst: Path) -> None:
    """Rename `partial` to `dst` WITHOUT replacing anything. Raises
    FileExistsError when `dst` has appeared."""
    if os.name == "nt":
        os.rename(partial, dst)         # refuses an existing name
        return
    try:
        os.link(partial, dst)
    except FileExistsError:
        raise
    except OSError:
        # No hard links here (exFAT, some network mounts): the best left is a
        # check immediately before the rename.
        if os.path.lexists(dst):
            raise FileExistsError(str(dst))
        os.rename(partial, dst)
        return
    os.unlink(partial)


def _discard(path: Path) -> None:
    try:
        path.unlink()
    except FileNotFoundError:
        pass
    except OSError:
        log.warning("card copy: could not remove %s", path)


def copy_file(src: Path, dst: Path, size: int, should_stop: Callable[[], str],
              on_bytes: Callable[[int], None]) -> str:
    """Copy `src` to `<dst>.partial`, fsync, verify, publish. -> "" on success,
    else the reason it failed (the `.partial` is gone either way). Raises
    _Stopped when `should_stop` says so, after discarding the partial, and
    FileExistsError when `dst` appeared mid-copy."""
    partial = dst.with_name(dst.name + PARTIAL_SUFFIX)
    _discard(partial)                    # a corpse from a crashed run is ours
    written = 0
    try:
        buf = bytearray(BUFFER_BYTES)
        view = memoryview(buf)
        with open(src, "rb") as a, open(partial, "xb") as b:
            while True:
                reason = should_stop()
                if reason:
                    raise _Stopped(reason)
                n = a.readinto(buf)
                if not n:
                    break
                b.write(view[:n])
                written += n
                on_bytes(n)
            b.flush()
            os.fsync(b.fileno())
        if written != size:
            raise OSError(f"read {written} bytes but the source is {size}")
        try:
            st = os.stat(src)
            os.utime(partial, ns=(st.st_atime_ns, st.st_mtime_ns))
        except OSError:
            pass
        why = quick_verify(src, partial, size)
        if why:
            _discard(partial)
            return f"verify failed: {why}"
        _publish(partial, dst)
        return ""
    except BaseException:
        _discard(partial)
        raise


# ------------------------------------------------------------------- paths
def _under(base: Path, rel: str) -> Path:
    raw = str(rel or "").strip().replace("\\", "/")
    if not raw:
        raise job_paths.JobPathError("the job named no path inside the volume",
                                     retryable=False)
    if any(ord(c) < 32 or ord(c) == 127 for c in raw):
        raise job_paths.JobPathError(
            f"{rel!r} has a control character in it", retryable=False)
    if raw.startswith("/") or (len(raw) > 1 and raw[1] == ":") or os.path.isabs(raw):
        raise job_paths.JobPathError(
            f"a job's path must be relative, and {rel!r} is absolute", retryable=False)
    parts = [p for p in raw.split("/") if p not in ("", ".")]
    if any(p == ".." for p in parts) or not parts:
        raise job_paths.JobPathError(
            f"{rel!r} climbs out of its volume", retryable=False)
    return base.joinpath(*parts)


class CardJob:
    """One card-ingest or drive-copy job. Every seam is a parameter, like
    MediaJob, so the suite needs no card and no dashboard."""

    def __init__(
        self,
        cfg: dict[str, Any],
        should_stop: Callable[[], str] = lambda: "",
        volumes_fn: Optional[Callable[..., list[dict[str, Any]]]] = None,
        progress: Optional[Progress] = None,
    ) -> None:
        self.cfg = cfg or {}
        self._should_stop = should_stop
        self._volumes = volumes_fn or sorter_cards.list_volumes
        self.progress = progress or Progress()
        self.stopped = ""
        self._vol_cache: dict[tuple[str, str], Path] = {}

    # -- placing ---------------------------------------------------------
    def _find_card(self, serial: str) -> Path:
        want = str(serial or "").strip().upper()
        if not want:
            raise CardJobError("the job named no card serial")
        vols = self._volumes("removable", set())
        for vol in vols:
            if str(vol["serial"]).upper() == want:
                sorter_cards.note_drive(want, vol["root"])
                return Path(vol["root"])
        known = sorter_cards.last_drive(want)
        for vol in vols:
            if known and vol["root"] == known:
                raise CardJobError(
                    f"drive {vol['drive']} now holds a different card "
                    f"({vol['serial']}), not {want}: nothing was copied")
        raise CardJobError(
            f"card {want} is not in a card reader on this computer, so nothing "
            f"was copied")

    def _find_local(self, serial: str) -> Path:
        want = str(serial or "").strip().upper()
        for vol in self._volumes("local", set()):
            if str(vol["serial"]).upper() == want:
                return Path(vol["root"])
        raise CardJobError(
            f"the drive with serial {want or '(none)'} is not on this computer",
            retryable=True)

    def _volume(self, kind: str, serial: str) -> Path:
        key = (kind, str(serial).upper())
        if key not in self._vol_cache:
            self._vol_cache[key] = (self._find_card(serial) if kind == "card"
                                    else self._find_local(serial))
        return self._vol_cache[key]

    def _place(self, root: str, rel: str) -> Path:
        name = str(root or "").strip()
        lowered = name.lower()
        if lowered.startswith("card:"):
            return _under(self._volume("card", name[5:]), rel)
        if lowered.startswith("local:"):
            return _under(self._volume("local", name[6:]), rel)
        return job_paths.resolve(self.cfg, name, rel)

    def _src_ref(self, kind: str, inputs: dict[str, Any], item: dict[str, Any]) -> tuple[str, str]:
        src = item.get("src")
        if isinstance(src, dict):
            return str(src.get("root") or ""), str(src.get("rel") or "")
        if kind == KIND_CARD_INGEST:
            return f"card:{inputs.get('serial') or ''}", str(src or "")
        root = str(inputs.get("src_root") or "")
        if not root and inputs.get("serial"):
            root = f"local:{inputs['serial']}"
        if not root:
            raise CardJobError("a drive-copy must name its source (a local:<serial> root)")
        return root, str(src or "")

    # -- the run ---------------------------------------------------------
    def run(self, kind: str, inputs: dict[str, Any]) -> dict[str, Any]:
        """-> the protocol's result {copied, skipped, conflicts, failed}.
        `self.stopped` holds the reason when a halt/cancel ended it early
        (the lists then hold what was done before it)."""
        if kind not in CARD_KINDS:
            raise CardJobError(f"{kind!r} is not a card copy kind")
        copies = inputs.get("copies")
        if not isinstance(copies, list):
            raise CardJobError("the job has no copies list")
        folders = inputs.get("folders") or []
        if kind == KIND_CARD_INGEST:
            # Find the card FIRST and fail before a folder is made if it is
            # the wrong one.
            self._volume("card", str(inputs.get("serial") or ""))
        result: dict[str, list] = {"copied": [], "skipped": [], "conflicts": [], "failed": []}
        total = sum(int(c.get("size") or 0) for c in copies if isinstance(c, dict))
        self.progress.of, self.progress.total_bytes = len(copies), total

        busy_serial, busy_root = "", ""
        if kind == KIND_CARD_INGEST:
            busy_serial = str(inputs.get("serial") or "")
            busy_root = str(self._volume("card", busy_serial))
        # Every destination root must be placeable HERE before a byte moves: a
        # pool that is not mounted is "not this machine" (retryable), not a
        # job whose every file fails one by one.
        for root in dict.fromkeys(
                str((c.get("dst") or {}).get("root") or "")
                for c in copies if isinstance(c, dict)):
            self._place(root, "probe")
        try:
            if busy_serial:
                with sorter_cards.ingest_busy(busy_serial, busy_root):
                    self._do(kind, inputs, folders, copies, result)
            else:
                self._do(kind, inputs, folders, copies, result)
        except _Stopped as stop:
            self.stopped = stop.reason
        return result

    def _do(self, kind: str, inputs: dict[str, Any], folders: list,
            copies: list, result: dict[str, list]) -> None:
        for folder in folders:
            if not isinstance(folder, dict):
                continue
            target = self._place(str(folder.get("root") or ""), str(folder.get("rel") or ""))
            try:
                target.mkdir(parents=True, exist_ok=True)
            except OSError as exc:
                raise CardJobError(f"could not make the folder {target}: {exc}",
                                   retryable=True) from exc
        for item in copies:
            reason = self._should_stop()
            if reason:
                raise _Stopped(reason)
            if not isinstance(item, dict):
                continue
            self._one(kind, inputs, item, result)
            self.progress.done += 1

    def _one(self, kind: str, inputs: dict[str, Any], item: dict[str, Any],
             result: dict[str, list]) -> None:
        src_wire = item.get("src")
        dst_wire = item.get("dst") if isinstance(item.get("dst"), dict) else {}
        want = int(item.get("size") or 0)

        def record(bucket: str, **extra: Any) -> None:
            result[bucket].append({"src": src_wire, "dst": dst_wire, **extra})

        def fail(why: str) -> None:
            result["failed"].append({"src": src_wire, "dst": dst_wire, "why": why})
            self.progress.bytes += want

        try:
            src_root, src_rel = self._src_ref(kind, inputs, item)
            src = self._place(src_root, src_rel)
            dst = self._place(str(dst_wire.get("root") or ""), str(dst_wire.get("rel") or ""))
        except CardJobError:
            raise
        except (job_paths.JobPathError, ValueError, OSError) as exc:
            fail(str(exc))
            return
        try:
            st = src.stat()
            if not src.is_file():
                fail("the source is not a file")
                return
        except OSError as exc:
            fail(f"the source cannot be read ({exc})")
            return
        size = int(st.st_size)
        if want and want != size:
            fail(f"the source is {size} bytes now and the job listed {want}: "
                 f"it changed since it was scanned")
            return
        if os.path.lexists(dst):
            try:
                same = dst.is_file() and dst.stat().st_size == size
            except OSError:
                same = False
            if same:
                record("skipped", size=size, verified=False)
            else:
                record("conflicts", size=size, verified=False,
                       why="a different file is already there; it was left alone")
            self.progress.bytes += size
            return
        try:
            dst.parent.mkdir(parents=True, exist_ok=True)
        except OSError as exc:
            fail(f"could not make the destination folder ({exc})")
            return
        before = self.progress.bytes

        def on_bytes(n: int) -> None:
            self.progress.bytes += n

        try:
            why = copy_file(src, dst, size, self._should_stop, on_bytes)
        except _Stopped:
            self.progress.bytes = before
            raise
        except FileExistsError:
            self.progress.bytes = before + size
            record("conflicts", size=size, verified=False,
                   why="a file appeared at the destination during the copy; it was left alone")
            return
        except OSError as exc:
            self.progress.bytes = before + size
            fail(f"the copy failed ({exc})")
            return
        self.progress.bytes = before + size
        if why:
            result["failed"].append({"src": src_wire, "dst": dst_wire, "why": why})
            return
        record("copied", size=size, verified=True)
