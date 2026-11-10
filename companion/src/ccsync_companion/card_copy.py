"""The copier behind the `card-ingest` and `drive-copy` fleet jobs.

Step 3 of "Card ingest through the companion: the protocol"
(footage-sorter docs/DASHBOARD-MODULE-PLAN.md, 2026-11-09).

TWO COPIERS (Alex, 2026-11-09). On Windows, when TeraCopy is installed with
verify on (teracopy.detect) and the destination is a Windows path, TeraCopy
copies: footage goes over SMB to the NAS and the plain-Python copier, which
reads and writes strictly in turn through one buffer, is too slow for that.
Everywhere else (a Mac, a PC with no TeraCopy, `card_copier = "python"`) the
Python copier below runs. The receipt says which: `"copier": "teracopy"|"python"`.

Each copy carries a write `mode` from the sorter's plan (a missing one is
`copy`):

  copy       write the file. An existing destination is never replaced: the
             same size and byte-identical is `skipped`; anything else is a
             `conflict` and is left alone. TeraCopy gets `/SkipAll` for it, and
             each group's destinations are looked at again just before it
             launches (a file that appeared meanwhile is a conflict).
  resume     the destination is a partial of this very file. Python: check
             that it is the start of the card's file, build `<dst>.partial`
             from it plus the rest, verify the whole file, then swap it in for
             the short one. TeraCopy: `/OverwriteDiffSize` rewrites it
             (run.js's resume), after the same start-of-file check on a sample.
  collision  a DIFFERENT file is at the destination: write beside it under a
             renamed name (`name (2).ext`, as TeraCopy's `/RenameCopied`),
             never over it. The receipt's `filename` is the name written. A
             renamed copy that an earlier, interrupted run already made is
             found and reported `skipped`, not copied a third time.

Rules, each with its reason:

  * **NEVER OVERWRITE.** See the modes. A same-size destination is NOT assumed
    identical: it is read back against the card, and a mismatch is a conflict.
    (TeraCopy's skip path verifies nothing with `TestSkippedFiles=0`, which is
    why this compare is done here, in both copiers.)
  * **A FILE APPEARS ONLY WHEN IT IS WHOLE AND VERIFIED** (Python copier).
    Bytes go to `<dst>.partial`, are fsynced, read back IN FULL against a
    hash taken while copying (not first and last MiB: the fallback is the slow
    path anyway and correctness wins), and only then renamed into place. A
    halt, a verify mismatch or an error deletes the `.partial`. The rename
    cannot clobber (Windows `rename` refuses an existing name; elsewhere a
    hard link is made and the partial unlinked). A resume builds its own
    `.partial` from the short file and swaps it in only once verified.
    TeraCopy writes IN PLACE with no `.partial`, as it did under the Node
    original (lib/teracopy.js); a job that stops mid-file leaves a short file
    at the final name, which the sorter's next plan sees as `partial` and
    resumes. `verified: true` from TeraCopy means its own hash verify
    (Target.result 3), nothing weaker.
  * **THE WRONG CARD IS REFUSED.** The job names a card by volume serial. If
    the drive now holds another card, or the card is not in a reader here,
    nothing is copied and the failure is not retryable: the job was aimed at
    this machine and another machine cannot fix it.
  * **THE VOLUME IS NOT READ BY ANYTHING ELSE WHILE IT IS COPIED**
    (`sorter_cards.ingest_busy`).
  * **A CARD PULLED MID-COPY STOPS THE JOB** (retryable) instead of failing
    every remaining file one by one; the caller posts what landed first.

Roots in a copy's `src` / `dst`: `{"root": "pool"|"vault"|"media"|"tree", "rel"}`
placed by job_paths; `local:<volume serial>` for a PC drive (a `drive-copy`);
and, for a card-ingest, a bare string `src` is a path on the card named by
`inputs.serial`. A `drive-copy` with bare-string sources reads them from
`inputs.src_root` (`local:<serial>`).
"""
from __future__ import annotations

import hashlib
import logging
import os
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable, Optional

from . import job_paths, sorter_cards
from . import teracopy as teracopy_mod

log = logging.getLogger("ccsync.cardcopy")

KIND_CARD_INGEST = "card-ingest"
KIND_DRIVE_COPY = "drive-copy"
CARD_KINDS = (KIND_CARD_INGEST, KIND_DRIVE_COPY)

BUFFER_BYTES = 8 * 1024 * 1024
PARTIAL_SUFFIX = ".partial"


class CardJobError(Exception):
    """The job cannot run here. `retryable` as job_paths.JobPathError."""

    def __init__(self, message: str, retryable: bool = False):
        super().__init__(message)
        self.retryable = bool(retryable)


# -- the automatic backup's home check (footage-sorter docs/AUTO-BACKUP-PLAN.md) --
SMB_PORT = 445
HOME_TRIES = 3


def _pool_host(cfg: dict[str, Any]) -> str:
    """The host of the share the pool root is on: a UNC root directly, or a mapped drive's UNC. '' when unknown."""
    root = str((cfg or {}).get(job_paths.ROOT_KEYS[job_paths.POOL]) or "").strip()
    unc = root
    if len(root) >= 2 and root[1] == ":" and os.name == "nt":
        try:
            import ctypes
            buf = ctypes.create_unicode_buffer(1024)
            size = ctypes.c_ulong(len(buf))
            if ctypes.windll.mpr.WNetGetConnectionW(root[:2], buf, ctypes.byref(size)) == 0:   # type: ignore[attr-defined]
                unc = buf.value
        except Exception:                                   # noqa: BLE001
            unc = root
    unc = unc.replace("/", "\\")
    if unc.startswith("\\\\"):
        return unc[2:].split("\\", 1)[0]
    return ""


def at_home(host: str, rtt_ms: float = 15.0, connect: Optional[Callable[[str, int, float], float]] = None) -> tuple[bool, str]:
    """Is this computer on the NAS's home network? Three TCP connects to the SMB port; the median round trip
    under `rtt_ms` is "the same network". From elsewhere over Tailscale it is many times that, and an address
    that does not answer at all is not home either. -> (home, why not)."""
    import socket
    import time as _time

    def _connect(h: str, port: int, timeout: float) -> float:
        t = _time.perf_counter()
        with socket.create_connection((h, port), timeout=timeout):
            return (_time.perf_counter() - t) * 1000.0
    probe = connect or _connect
    times: list[float] = []
    for _ in range(HOME_TRIES):
        try:
            times.append(probe(host, SMB_PORT, 0.5))
        except OSError:
            continue
    if not times:
        return False, f"the NAS's home address {host} did not answer"
    med = sorted(times)[len(times) // 2]
    if len(times) < 2 or med >= rtt_ms:
        return False, f"the NAS's home address {host} answered in {med:.0f} ms, not like the same network (under {rtt_ms:g} ms)"
    return True, ""


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
        # for the live progress the sorter shows (ProgressPoster)
        self.current = ""            # the card-relative file in hand
        self.phase = "copy"          # "copy" | "verify"
        self.copier = "python"

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
MODES = ("copy", "resume", "collision")
MAX_RENAMES = 99
HEAD_TAIL_BYTES = 1024 * 1024           # a TeraCopy resume's start-of-file sample


class _Conflict(Exception):
    """A file there that must be left alone (a partial that is not the start of
    the card's file, say). Reported as a `conflict`, never a failure."""


def _new_hash() -> Any:
    return hashlib.blake2b(digest_size=32)


def verify_whole(path: Path, size: int, digest: bytes, should_stop: Callable[[], str]) -> str:
    """Read `path` back IN FULL and compare with `digest`, the hash taken of the
    source while it was copied. -> "" when it matches, else the reason."""
    try:
        got = path.stat().st_size
    except OSError as exc:
        return f"the copy cannot be read back ({exc})"
    if got != size:
        return f"the copy is {got} bytes and the source {size}"
    h = _new_hash()
    try:
        with open(path, "rb") as fh:
            while True:
                reason = should_stop()
                if reason:
                    raise _Stopped(reason)
                chunk = fh.read(BUFFER_BYTES)
                if not chunk:
                    break
                h.update(chunk)
    except OSError as exc:
        return f"the copy could not be verified ({exc})"
    if h.digest() != digest:
        return "the copy read back differs from the source"
    return ""


def files_identical(a: Path, b: Path, size: int, should_stop: Callable[[], str]) -> str:
    """Compare two files byte for byte, stopping at the first difference.
    -> "" when identical, else why not. Reads both sides in full otherwise."""
    try:
        if a.stat().st_size != size or b.stat().st_size != size:
            return "the sizes differ"
        with open(a, "rb") as fa, open(b, "rb") as fb:
            while True:
                reason = should_stop()
                if reason:
                    raise _Stopped(reason)
                ca = fa.read(BUFFER_BYTES)
                cb = fb.read(BUFFER_BYTES)
                if ca != cb:
                    return "the bytes differ"
                if not ca:
                    return ""
    except OSError as exc:
        return f"it could not be read ({exc})"


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


def _stamp(src: Path, dst: Path) -> None:
    try:
        st = os.stat(src)
        os.utime(dst, ns=(st.st_atime_ns, st.st_mtime_ns))
    except OSError:
        pass


def copy_file(src: Path, dst: Path, size: int, should_stop: Callable[[], str],
              on_bytes: Callable[[int], None]) -> str:
    """Copy `src` to `<dst>.partial`, fsync, read it all back against the hash
    taken while copying, publish. -> "" on success, else the reason it failed
    (the `.partial` is gone either way). Raises _Stopped when `should_stop`
    says so, after discarding the partial, and FileExistsError when `dst`
    appeared mid-copy."""
    partial = dst.with_name(dst.name + PARTIAL_SUFFIX)
    _discard(partial)                    # a corpse from a crashed run is ours
    written = 0
    h = _new_hash()
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
                h.update(view[:n])
                b.write(view[:n])
                written += n
                on_bytes(n)
            b.flush()
            os.fsync(b.fileno())
        if written != size:
            raise OSError(f"read {written} bytes but the source is {size}")
        _stamp(src, partial)
        why = verify_whole(partial, size, h.digest(), should_stop)
        if why:
            _discard(partial)
            return f"verify failed: {why}"
        _publish(partial, dst)
        return ""
    except BaseException:
        _discard(partial)
        raise


def resume_file(src: Path, dst: Path, size: int, have: int, should_stop: Callable[[], str],
                on_bytes: Callable[[int], None]) -> str:
    """Finish a partial `dst` of `have` bytes WITHOUT touching it until the
    result is proven: build `<dst>.partial` from `dst`'s bytes (each compared with
    the card's, so a file that is not the start of `src` is a _Conflict) plus
    the rest of `src`, read the WHOLE file back against the source's hash, and
    only then swap it in for the short file (checked unchanged just before).
    -> "" on success, else why not. The `.partial` is gone on every other exit
    and `dst` is as it was: a stop mid-way costs the appended bytes, but never
    leaves a full-length file that nothing verified."""
    partial = dst.with_name(dst.name + PARTIAL_SUFFIX)
    _discard(partial)                    # a corpse from a crashed run is ours
    h = _new_hash()
    try:
        with open(src, "rb") as a, open(dst, "rb") as old, open(partial, "xb") as b:
            if os.fstat(old.fileno()).st_size != have:
                raise _Conflict("the partial changed size while it was being checked")
            pos = 0
            while pos < have:
                reason = should_stop()
                if reason:
                    raise _Stopped(reason)
                n = min(BUFFER_BYTES, have - pos)
                ca, cb = a.read(n), old.read(n)
                if ca != cb or len(ca) != n:
                    raise _Conflict("the file already there is not the start of the card's file")
                h.update(ca)
                b.write(ca)
                pos += n
                on_bytes(n)
            buf = bytearray(BUFFER_BYTES)
            view = memoryview(buf)
            written = have
            while True:
                reason = should_stop()
                if reason:
                    raise _Stopped(reason)
                n = a.readinto(buf)
                if not n:
                    break
                h.update(view[:n])
                b.write(view[:n])
                written += n
                on_bytes(n)
            b.flush()
            os.fsync(b.fileno())
        if written != size:
            raise OSError(f"read {written} bytes but the source is {size}")
        _stamp(src, partial)
        why = verify_whole(partial, size, h.digest(), should_stop)
        if why:
            _discard(partial)
            return f"verify failed: {why}"
        if dst.stat().st_size != have:
            raise _Conflict("the partial changed size while it was being resumed")
        os.replace(partial, dst)         # the short prefix of this very file, and nothing else
        return ""
    except BaseException:
        _discard(partial)
        raise


def renamed(dst: Path, n: int) -> Path:
    """`clip.MP4` -> `clip (2).MP4`: the names TeraCopy's /RenameCopied makes."""
    return dst.with_name(f"{dst.stem} ({n}){dst.suffix}")


def _sample_matches(src: Path, dst: Path, have: int) -> bool:
    """Is `dst` (a partial of `have` bytes) the start of `src`? Compared at its
    first and last MiB: TeraCopy rewrites a resumed file whole, so this only has
    to catch a file that is plainly some other file."""
    n = min(HEAD_TAIL_BYTES, have)
    try:
        with open(src, "rb") as a, open(dst, "rb") as b:
            for off in {0, max(0, have - n)}:
                a.seek(off)
                b.seek(off)
                if a.read(n) != b.read(n):
                    return False
    except OSError:
        return False
    return True


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
    # a ":" in ANY part is a drive (`DCIM/E:/x` re-roots a Windows join onto E:) or an alternate data stream
    if any(":" in p for p in parts) or any(os.path.isabs(p) for p in parts):
        raise job_paths.JobPathError(
            f"{rel!r} has a drive or stream marker in it", retryable=False)
    out = base.joinpath(*parts)
    try:
        out.resolve().relative_to(base.resolve())
    except (ValueError, OSError):
        raise job_paths.JobPathError(
            f"{rel!r} resolves outside its volume", retryable=False) from None
    return out


class CardJob:
    """One card-ingest or drive-copy job. Every seam is a parameter, like
    MediaJob, so the suite needs no card and no dashboard."""

    def __init__(
        self,
        cfg: dict[str, Any],
        should_stop: Callable[[], str] = lambda: "",
        volumes_fn: Optional[Callable[..., list[dict[str, Any]]]] = None,
        progress: Optional[Progress] = None,
        teracopy_fn: Optional[Callable[[], tuple[Optional[teracopy_mod.TeraCopy], str]]] = None,
    ) -> None:
        self.cfg = cfg or {}
        self._should_stop = should_stop
        self._volumes = volumes_fn or sorter_cards.list_volumes
        self.progress = progress or Progress()
        self.stopped = ""
        # whether a stop is worth retrying (a cancel is decided by the caller)
        self.stop_retryable = True
        # which copier ran, for the receipt; `teracopy_fn` -> (TeraCopy | None, why not)
        self.teracopy_used = False
        self._teracopy_fn = teracopy_fn or (lambda: teracopy_mod.detect(self.cfg))
        self._ingest_serial = ""
        self._vol_cache: dict[tuple[str, str], Path] = {}
        # the automatic backup's home check, a seam for the suite: (host, rtt_ms) -> (home, why not)
        self._at_home: Optional[Callable[[str, float], tuple[bool, str]]] = None

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
        """-> the protocol's result {copied, skipped, conflicts, failed, copier}.
        `self.stopped` holds the reason when a halt/cancel/lost card ended it
        early (the lists then hold what was done before it)."""
        if kind not in CARD_KINDS:
            raise CardJobError(f"{kind!r} is not a card copy kind")
        copies = inputs.get("copies")
        if not isinstance(copies, list):
            raise CardJobError("the job has no copies list")
        folders = inputs.get("folders") or []
        if kind == KIND_DRIVE_COPY and inputs.get("homeOnly"):
            # an automatic backup copies only at home (footage-sorter docs/AUTO-BACKUP-PLAN.md): over a slow link
            # it would take all day, and a laptop away from home tries again an hour later
            host = str(inputs.get("homeHost") or "") or _pool_host(self.cfg)
            if not host:
                raise CardJobError("away from home: cannot tell, no homeHost and no pool share to find the NAS by")
            home, why = (self._at_home or at_home)(host, float(inputs.get("homeRttMs") or 15))
            if not home:
                raise CardJobError(f"away from home: {why}; nothing was copied")
        if kind == KIND_CARD_INGEST:
            # Find the card FIRST and fail before a folder is made if it is
            # the wrong one.
            self._volume("card", str(inputs.get("serial") or ""))
        result: dict[str, Any] = {"copied": [], "skipped": [], "conflicts": [], "failed": []}
        total = sum(int(c.get("size") or 0) for c in copies if isinstance(c, dict))
        self.progress.of, self.progress.total_bytes = len(copies), total

        busy_serial, busy_root = "", ""
        if kind == KIND_CARD_INGEST:
            busy_serial = str(inputs.get("serial") or "")
            busy_root = str(self._volume("card", busy_serial))
            self._ingest_serial = busy_serial
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
        except CardJobError as exc:
            # Mid-run (a folder that cannot be made): what landed before it
            # still has to be reported, so it is a stop and not a raise.
            self.stopped, self.stop_retryable = str(exc), exc.retryable
        result["copier"] = "teracopy" if self.teracopy_used else "python"
        return result

    def _pick_teracopy(self) -> Optional[teracopy_mod.TeraCopy]:
        tc, why = self._teracopy_fn()
        if tc is None:
            log.info("card copy: using the Python copier (%s)", why)
        return tc

    def _card_gone(self) -> bool:
        """Is the card this job reads no longer in a reader here? Asked only
        after an I/O error, so a pulled card stops the job instead of failing
        every remaining file."""
        if not self._ingest_serial:
            return False
        try:
            vols = self._volumes("removable", set())
        except Exception:                                       # noqa: BLE001
            return False
        return not any(str(v["serial"]).upper() == self._ingest_serial.upper() for v in vols)

    def _stop_if_card_gone(self) -> None:
        if self._card_gone():
            raise _Stopped("the card was taken out of its reader")

    def _do(self, kind: str, inputs: dict[str, Any], folders: list,
            copies: list, result: dict[str, Any]) -> None:
        for folder in folders:
            if not isinstance(folder, dict):
                continue
            target = self._place(str(folder.get("root") or ""), str(folder.get("rel") or ""))
            try:
                target.mkdir(parents=True, exist_ok=True)
            except OSError as exc:
                raise CardJobError(f"could not make the folder {target}: {exc}",
                                   retryable=True) from exc
        tc = self._pick_teracopy()
        pending: list[_Work] = []
        for item in copies:
            reason = self._should_stop()
            if reason:
                raise _Stopped(reason)
            if not isinstance(item, dict):
                continue
            work = self._prepare(kind, inputs, item, result)
            if work is None:
                self.progress.done += 1
            elif tc is None or not self._teracopy_can(work):
                self._python_one(work, result)
                self.progress.done += 1
            else:
                pending.append(work)
        if pending and tc is not None:
            self._run_teracopy(tc, pending, result)

    # -- one file: the part both copiers share -----------------------------
    def _note(self, result: dict[str, Any], bucket: str, w: "_Work", **extra: Any) -> None:
        result[bucket].append({"src": w.src_wire, "dst": w.dst_wire, **extra})

    def _fail(self, result: dict[str, Any], w: "_Work", why: str) -> None:
        self._note(result, "failed", w, why=why)
        self.progress.bytes += w.want

    def _prepare(self, kind: str, inputs: dict[str, Any], item: dict[str, Any],
                 result: dict[str, Any]) -> Optional["_Work"]:
        """Place and stat one copy. -> the work, or None after recording why not."""
        src_wire = item.get("src")
        dst_wire = item.get("dst") if isinstance(item.get("dst"), dict) else {}
        want = int(item.get("size") or 0)
        mode = str(item.get("mode") or "copy").strip().lower()
        stub = _Work(src_wire, dst_wire, Path("."), Path("."), want, 0, mode)
        if mode not in MODES:
            self._fail(result, stub, f"{mode!r} is not a write mode this companion knows")
            return None
        try:
            src_root, src_rel = self._src_ref(kind, inputs, item)
            src = self._place(src_root, src_rel)
            dst = self._place(str(dst_wire.get("root") or ""), str(dst_wire.get("rel") or ""))
        except CardJobError:
            raise
        except (job_paths.JobPathError, ValueError, OSError) as exc:
            self._fail(result, stub, str(exc))
            return None
        try:
            st = src.stat()
            if not src.is_file():
                self._fail(result, stub, "the source is not a file")
                return None
        except OSError as exc:
            self._stop_if_card_gone()
            self._fail(result, stub, f"the source cannot be read ({exc})")
            return None
        size = int(st.st_size)
        if want and want != size:
            self._fail(result, stub, f"the source is {size} bytes now and the job listed {want}: "
                       f"it changed since it was scanned")
            return None
        return _Work(src_wire, dst_wire, src, dst, want, size, mode)

    def _decide(self, w: "_Work", tc_names: bool = False) -> "_Decision":
        """What to do about what is (or is not) at the destination. Never
        replaces anything. `tc_names`: TeraCopy will pick a collision's new
        name itself, so a free one is not chosen here."""
        dst = w.dst
        try:
            exists = os.path.lexists(dst)
            if not exists:
                return _Decision("write", dst)
            is_file = dst.is_file() and not dst.is_symlink()
            have = dst.stat().st_size if is_file else -1
            if w.mode == "collision":
                # An earlier, interrupted run may already have made the copy:
                # the plain name, then `name (2)` ... that is byte-identical.
                if is_file and have == w.size and not files_identical(
                        w.src, dst, w.size, self._should_stop):
                    return _Decision("skipped", dst)
                for n in range(2, MAX_RENAMES + 1):
                    cand = renamed(dst, n)
                    if not os.path.lexists(cand):
                        return _Decision("write", dst if tc_names else cand, renamed=True)
                    if cand.is_file() and cand.stat().st_size == w.size and not files_identical(
                            w.src, cand, w.size, self._should_stop):
                        return _Decision("skipped", cand)
                return _Decision("conflict", why=f"{MAX_RENAMES} renamed copies of it are already there")
            if not is_file:
                return _Decision("conflict", why="a folder or link is already there; it was left alone")
            if have == w.size:
                # NOT assumed identical: read it back against the card.
                why = files_identical(w.src, dst, w.size, self._should_stop)
                if not why:
                    return _Decision("skipped", dst)
                return _Decision("conflict", why=f"a different file of the same size is already "
                                 f"there ({why}); it was left alone")
            if w.mode == "resume" and have < w.size:
                return _Decision("write", dst, resume_from=have)
            return _Decision("conflict", why="a different file is already there; it was left alone")
        except OSError as exc:
            return _Decision("failed", why=f"the destination cannot be read ({exc})")

    def _settle(self, result: dict[str, Any], w: "_Work", d: "_Decision") -> bool:
        """Record a decision that needs no copy. -> True when it did not."""
        if d.kind == "skipped":
            self._note(result, "skipped", w, size=w.size, verified=True, filename=d.dst.name)
        elif d.kind == "conflict":
            self._note(result, "conflicts", w, size=w.size, verified=False, why=d.why)
        elif d.kind == "failed":
            self._note(result, "failed", w, why=d.why)
        else:
            return False
        self.progress.bytes += w.size
        return True

    # -- the Python copier -------------------------------------------------
    def _python_one(self, w: "_Work", result: dict[str, Any]) -> None:
        d = self._decide(w)
        if self._settle(result, w, d):
            return
        self._python_write(w, d, result)

    def _python_write(self, w: "_Work", d: "_Decision", result: dict[str, Any]) -> None:
        dst = d.dst
        try:
            dst.parent.mkdir(parents=True, exist_ok=True)
        except OSError as exc:
            self._fail(result, w, f"could not make the destination folder ({exc})")
            return
        before = self.progress.bytes
        self.progress.current = str(w.src_wire or "")
        self.progress.phase = "copy"
        seen = {"n": 0}

        def on_bytes(n: int) -> None:
            self.progress.bytes += n
            seen["n"] += n
            if seen["n"] >= w.size:        # everything is written: the read-back is next
                self.progress.phase = "verify"

        try:
            if d.resume_from:
                why = resume_file(w.src, dst, w.size, d.resume_from, self._should_stop, on_bytes)
            else:
                why = copy_file(w.src, dst, w.size, self._should_stop, on_bytes)
        except _Stopped:
            self.progress.bytes = before
            raise
        except _Conflict as exc:
            self.progress.bytes = before + w.size
            self._note(result, "conflicts", w, size=w.size, verified=False,
                       why=f"{exc}; it was left alone")
            return
        except FileExistsError:
            self.progress.bytes = before + w.size
            self._note(result, "conflicts", w, size=w.size, verified=False,
                       why="a file appeared at the destination during the copy; it was left alone")
            return
        except OSError as exc:
            self.progress.bytes = before
            self._stop_if_card_gone()
            self.progress.bytes = before + w.size
            self._note(result, "failed", w, why=f"the copy failed ({exc})")
            return
        self.progress.bytes = before + w.size
        self.progress.phase = "copy"
        if why:
            self._note(result, "failed", w, why=why)
            return
        self._note(result, "copied", w, size=w.size, verified=True, filename=dst.name)

    # -- the TeraCopy copier -----------------------------------------------
    @staticmethod
    def _teracopy_can(w: "_Work") -> bool:
        """TeraCopy keeps the source name and copies flat into one folder, and
        needs a Windows path; anything else goes to the Python copier."""
        if os.name != "nt" or not os.path.splitdrive(str(w.dst))[0]:
            return False
        return w.dst.name.lower() == w.src.name.lower()

    def _run_teracopy(self, tc: teracopy_mod.TeraCopy, works: list["_Work"],
                      result: dict[str, Any]) -> None:
        """One TeraCopy job per (destination folder, switch), one at a time,
        masters before proxies as run.js ordered them."""
        groups: dict[tuple[str, str], list[tuple[_Work, _Decision]]] = {}
        for w in works:
            reason = self._should_stop()
            if reason:
                raise _Stopped(reason)
            d = self._decide(w, tc_names=True)
            if self._settle(result, w, d):
                self.progress.done += 1
                continue
            if self._bad_resume(w, d, result):
                continue
            groups.setdefault((str(w.dst.parent), self._switch_for(w)), []).append((w, d))
        order = {teracopy_mod.SWITCH_SKIP: 0, teracopy_mod.SWITCH_OVERWRITE_DIFF: 1,
                 teracopy_mod.SWITCH_RENAME: 2}     # plain copies claim their names before renames
        for (folder, switch), members in sorted(
                groups.items(), key=lambda kv: (len(kv[0][0]), kv[0][0], order.get(kv[0][1], 9))):
            reason = self._should_stop()
            if reason:
                raise _Stopped(reason)
            members = self._recheck(members, result)
            if members:
                self._teracopy_group(tc, folder, switch, members, result)

    @staticmethod
    def _switch_for(w: "_Work") -> str:
        if w.mode == "collision":
            return teracopy_mod.SWITCH_RENAME
        return teracopy_mod.SWITCH_OVERWRITE_DIFF if w.mode == "resume" else teracopy_mod.SWITCH_SKIP

    def _bad_resume(self, w: "_Work", d: "_Decision", result: dict[str, Any]) -> bool:
        if d.resume_from and not _sample_matches(w.src, d.dst, d.resume_from):
            self._note(result, "conflicts", w, size=w.size, verified=False,
                       why="the file already there is not the start of the card's file; "
                           "it was left alone")
            self.progress.bytes += w.size
            self.progress.done += 1
            return True
        return False

    def _recheck(self, members: list[tuple["_Work", "_Decision"]],
                 result: dict[str, Any]) -> list[tuple["_Work", "_Decision"]]:
        """Look at each destination again just before its group launches: a
        file that appeared since the plan (another card's copy, say) is skipped
        or a conflict, never overwritten. Two members that would write one name
        (case-blind) in a plain copy: the later is a conflict."""
        keep: list[tuple[_Work, _Decision]] = []
        names: set[str] = set()
        for w, _old in members:
            reason = self._should_stop()
            if reason:
                raise _Stopped(reason)
            d = self._decide(w, tc_names=True)
            if self._settle(result, w, d):
                self.progress.done += 1
                continue
            if self._bad_resume(w, d, result):
                continue
            if w.mode != "collision":
                key = str(w.dst).lower()
                if key in names:
                    self._note(result, "conflicts", w, size=w.size, verified=False,
                               why="another file in this job is going to the same name; "
                                   "it was left alone")
                    self.progress.bytes += w.size
                    self.progress.done += 1
                    continue
                names.add(key)
            keep.append((w, d))
        return keep

    def _teracopy_group(self, tc: teracopy_mod.TeraCopy, folder: str, switch: str,
                        members: list[tuple["_Work", "_Decision"]],
                        result: dict[str, Any]) -> None:
        self.teracopy_used = True
        self.progress.copier = "teracopy"
        base = self.progress.bytes
        files_base = self.progress.done
        total = sum(w.size for w, _ in members)
        try:
            known = set(os.listdir(folder))
        except OSError:
            known = set()

        def tick(status: dict[str, Any], _elapsed: int) -> None:
            # TeraCopy writes in place, so the bytes on disk are the progress.
            # The history DB says which phase it is in (Run rows: copy done,
            # verify seen) and how many files have verified (Target rows).
            got = 0
            current = ""
            for w, d in members[:64]:
                try:
                    n = min(w.size, os.stat(d.dst).st_size)
                except OSError:
                    n = 0
                got += n
                if not current and n < w.size:
                    current = str(w.src_wire or "")
            verifying = bool(status) and (status.get("copy_done") or status.get("verify_seen"))
            self.progress.phase = "verify" if verifying else "copy"
            self.progress.current = current or str(members[-1][0].src_wire or "")
            self.progress.bytes = base + min(total, got)
            if verifying:
                self.progress.done = files_base + min(len(members), int(status.get("ok") or 0))

        tag = os.path.basename(folder.rstrip("\\/")) or "job"
        try:
            out = tc.copy_group([str(w.src) for w, _ in members], folder, switch, tag,
                                on_tick=tick, expect_verify=not self._unverified_ok(),
                                should_stop=self._should_stop)
        except (OSError, ValueError) as exc:
            self._stop_if_card_gone()
            self.progress.bytes = base + total
            for w, _ in members:
                self._note(result, "failed", w, why=f"TeraCopy could not be run ({exc})")
                self.progress.done += 1
            return
        by_src = {_key(r["source"]): r for r in out["receipts"]}
        stopped = str(out.get("stopped") or "")
        lost = 0
        for w, d in members:
            r = by_src.get(_key(w.src))
            landed = self._landed_name(w, r, switch, known)
            path = w.dst.with_name(landed) if landed else w.dst
            try:
                have: Optional[int] = path.stat().st_size
            except OSError:
                have = None
            if r is not None and r.get("verified") and have == w.size:
                self._note(result, "copied", w, size=w.size, verified=True, filename=path.name)
            elif r is not None and r.get("verified"):
                self._note(result, "failed", w,
                           why=f"TeraCopy reported it verified but {path.name} is "
                               f"{'missing' if have is None else str(have) + ' bytes'} at the destination")
            elif stopped:
                continue            # not verified when the wait ended: NOT landed
            elif r is not None and r.get("result") not in (None, teracopy_mod.RESULT_COPIED):
                self._note(result, "failed", w,
                           why=r.get("message") or f"TeraCopy gave result {r.get('result')} for it")
            elif have == w.size:
                # on disk at the right size, not hash-verified by TeraCopy
                self._note(result, "copied", w, size=w.size, verified=False, filename=path.name)
            else:
                lost += 1
                self._note(result, "failed", w,
                           why="it did not reach the destination whole"
                               + ("" if have is None else f" ({have} of {w.size} bytes)"))
            self.progress.done += 1
        self.progress.bytes = base + total
        if stopped:
            raise _Stopped(stopped)
        if lost:
            self._stop_if_card_gone()

    def _unverified_ok(self) -> bool:
        return teracopy_mod._truthy(self.cfg.get("teracopy_allow_unverified"))

    @staticmethod
    def _landed_name(w: "_Work", r: Optional[dict[str, Any]], switch: str,
                     known: set[str]) -> str:
        """The name a TeraCopy-written file has: its record's `filename` when it
        renamed one, else the planned name. With no record for a collision job
        (the history was unreadable), the new file beside it of the right size."""
        if r is not None and r.get("filename"):
            return str(r["filename"])
        if switch == teracopy_mod.SWITCH_RENAME and (r is None or r.get("result") is None):
            for n in range(2, MAX_RENAMES + 1):
                cand = renamed(w.dst, n)
                if cand.name not in known and cand.is_file():
                    try:
                        if cand.stat().st_size == w.size:
                            return cand.name
                    except OSError:
                        pass
        return ""


class ProgressPoster:
    """Builds the body of POST /sorter/agent/ingest/<job>/progress from a
    Progress: bytes and files, the file in hand, copy or verify, and the speed
    over the last ~5 s. The clock is a parameter; the poster itself is
    jobs_runner's (best effort: a failed post never touches the copy)."""

    WINDOW_SECONDS = 5.0

    def __init__(self, progress: Progress, clock: Callable[[], float]):
        self.progress = progress
        self._clock = clock
        self._samples: list[tuple[float, int]] = []

    def body(self) -> dict[str, Any]:
        p = self.progress
        now, done = self._clock(), int(p.bytes)
        self._samples.append((now, done))
        while len(self._samples) > 2 and now - self._samples[1][0] >= self.WINDOW_SECONDS:
            self._samples.pop(0)
        t0, b0 = self._samples[0]
        bps = int((done - b0) / (now - t0)) if now - t0 > 0 and done >= b0 else 0
        return {"bytesDone": done, "bytesTotal": int(p.total_bytes), "filesDone": int(p.done),
                "filesTotal": int(p.of), "current": p.current or "",
                "bps": max(0, bps) if p.phase == "copy" else 0, "phase": p.phase, "copier": p.copier}


def _key(path: Any) -> str:
    return str(path).replace("/", "\\").rstrip("\\").lower()


@dataclass
class _Work:
    """One copy, placed and stat'ed."""
    src_wire: Any
    dst_wire: dict
    src: Path
    dst: Path
    want: int
    size: int
    mode: str = "copy"


@dataclass
class _Decision:
    """What to do about a copy's destination."""
    kind: str                       # write | skipped | conflict | failed
    dst: Path = Path(".")
    resume_from: int = 0
    why: str = ""
    renamed: bool = False
