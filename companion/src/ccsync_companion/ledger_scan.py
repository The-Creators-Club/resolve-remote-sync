"""The walker behind the `ledger-scan` fleet job: list a drive's roots, read-only.

Companion half of footage-sorter docs/LEDGER-BROWSER-DESIGN.md, "A listing
becomes a delta" and "The companion" item 2. The SERVER keeps the truth and
computes what is new, replaced, gone or back; this side only produces a FULL
listing of the roots, `[path, size, mtimeMs]` per tracked file, and streams it:

  GET  /sorter/agent/ledger/scan/<job>            {volumeId, roots, rules}
  POST /sorter/agent/ledger/scan/<job>/chunk      {rows, seq}   gzip, 5,000 rows
  POST /sorter/agent/ledger/scan/<job>/progress   {filesDone, bytesSeen, bps, current}   every 2 s
  POST /sorter/agent/ledger/scan/<job>/finish     {files, bytes, complete, unreadable}

Every post carries the manifest's `attempt` token when it names one: a job that was reclaimed gets
a new attempt, and the server refuses what an old attempt still sends.

RULES OF THE WALK, each with its reason:

  * **READ-ONLY.** `os.scandir` and a stat that scandir already holds. Nothing is
    opened, hashed, written or locked: a scan runs against a drive somebody is
    copying footage off, and a card can be a flaky reader.
  * **PATHS ARE RELATIVE TO THE VOLUME ROOT, '/'-separated, root prefix
    included** (`FieldBackup/Trip/A001.braw`), because that is what the ledger
    stores (`copies.path`). Never a drive letter: letters move, serials do not.
  * **THE SKIP RULES RUN HERE FIRST** (the manifest's `rules`, else a built-in
    copy of the ledger's), so a 4 TB drive of caches does not upload a million
    rows the server would throw away. The server re-applies its own rules, so
    this is only ever an optimisation: when in doubt a file is KEPT.
  * **`complete` IS FALSE FOR A REAL OMISSION, AND ONLY THEN.** A scan cut short (the drive
    vanished, a cancel, a halt, shutdown, a lost chunk) is recorded `partial` and marks nothing
    missing: the safe way to fail. A FOLDER THAT WOULD NOT OPEN (or an entry whose stat failed) is
    different: it is named in the finish's `unreadable` list (folders relative to the volume root,
    "" meaning the whole drive) and the server EXEMPTS those subtrees from "gone", so the scan stays
    `complete: true` and the rest of the drive is still brought up to date. The list is cut at 200
    folders; if there were more than that the rest are not exempted, so that scan is `complete:
    false`. A junction or other reparse point is NOT followed (it can lead off the volume, or round
    in a circle) and is not a failure; they are counted in `links`.
  * **LONG PATHS**: on Windows the walk uses the extended-length path prefix, so a path past
    260 characters is listed, not silently dropped.
  * **A SYSTEM VOLUME IS NEVER WALKED FROM ITS ROOT**: only the explicit roots a watch names.
  * **A CHUNK IS RETRIED UNDER THE SAME `seq`**, so the server (idempotent on
    seq) applies it once however many times the answer was lost.
  * **BOUNDED MEMORY**: one chunk of rows at a time, whatever the drive holds.
"""
from __future__ import annotations

import logging
import os
import re
import threading
import time
from typing import Any, Callable, Iterable, Optional

log = logging.getLogger("ccsync.ledgerscan")

KIND = "ledger-scan"          # the fleet job kind (dashboard db.JOB_KIND_LEDGER_SCAN)
CHUNK_ROWS = 5000
PROGRESS_SECONDS = 2.0
CHUNK_TRIES = 5
CHUNK_RETRY_SECONDS = 3.0
ALIVE_CHECK_SECONDS = 5.0
MAX_UNREADABLE_LISTED = 200
STALE_REASON = "this scan attempt is no longer current (the server gave the job to a newer attempt)"

# -- the built-in copy of the ledger's rules: footage-sorter `footage_sorter/ledger_rules.py`
#    (docs/LEDGER-BROWSER-DESIGN.md, "What is tracked"). The manifest's `rules` (that module's
#    `rules_doc()`) replaces every one of these; this copy is for a manifest that carries none.
MASTER_EXTS = {"braw", "r3d", "ari", "mxf", "mov", "mp4", "m4v", "mts", "m2ts", "avi",
               "crm", "dng", "arw", "cr3", "nef", "insv"}
AUDIO_EXTS = {"wav", "bwf", "aif", "aiff", "mp3", "m4a", "flac"}
PROXY_VIDEO_EXTS = {"mov", "mp4", "m4v", "mxf", "avi", "mts", "m2ts", "mkv", "webm"}
PROXY_DIRS = {"proxy", "proxies"}
SKIP_DIR_NAMES = {"cacheclip", "optimizedmedia", "_sorter_test", "thmbnl", "dupe-quarantine",
                  "$recycle.bin", "system volume information", "#recycle", ".git", "node_modules",
                  "__macosx", ".spotlight-v100", ".trashes", ".fseventsd", "lost+found", ".recycle",
                  "@eadir"}
SKIP_SUFFIXES = (".part", ".partial", ".interrupted", ".failed")
SKIP_PREFIXES = ("._",)
TEMP_PATTERN = r"\.tmp\.[^./\\]+$"


class ScanError(Exception):
    """The scan cannot continue and the job should fail (a refused chunk, not a vanished drive)."""

    def __init__(self, message: str, retryable: bool = True) -> None:
        super().__init__(message)
        self.retryable = retryable


class Rules:
    """What this walk keeps: the server's own rules (the manifest's `rules`: masterExts, audioExts,
    proxyVideoExts, proxyDirs, skipDirs, skipSuffixes, skipPrefixes, tempRe), with the built-in copy
    for any key that is missing or malformed. A file is kept when its extension is a master's or
    audio's, or a video's inside a Proxy folder; a temp file, a partial and a `._` twin never are.
    The server applies the same rules to every row again, so this only saves the upload."""

    def __init__(self, raw: Optional[dict[str, Any]] = None) -> None:
        raw = raw if isinstance(raw, dict) else {}

        def exts(key: str, default: set) -> set:
            got = _strings(raw.get(key))
            return {e.lstrip(".").lower() for e in got} if got else set(default)

        self.master = exts("masterExts", MASTER_EXTS)
        self.audio = exts("audioExts", AUDIO_EXTS)
        self.proxy_video = exts("proxyVideoExts", PROXY_VIDEO_EXTS)
        proxy_dirs = _strings(raw.get("proxyDirs"))
        self.proxy_dirs = {d.lower() for d in proxy_dirs} if proxy_dirs else set(PROXY_DIRS)
        dirs = _strings(raw.get("skipDirs"))
        self.skip_dirs = {d.lower() for d in dirs} if dirs else set(SKIP_DIR_NAMES)
        suffixes = _strings(raw.get("skipSuffixes"))
        self.skip_suffixes = tuple(x.lower() for x in suffixes) if suffixes else SKIP_SUFFIXES
        prefixes = _strings(raw.get("skipPrefixes"))
        self.skip_prefixes = tuple(x.lower() for x in prefixes) if prefixes else SKIP_PREFIXES
        pattern = raw.get("tempRe")
        try:
            self.temp_re = re.compile(pattern if isinstance(pattern, str) and pattern else TEMP_PATTERN, re.IGNORECASE)
        except re.error:
            self.temp_re = re.compile(TEMP_PATTERN, re.IGNORECASE)

    def skip_dir(self, name: str) -> bool:
        return name.lower() in self.skip_dirs

    def is_proxy_dir(self, name: str) -> bool:
        return name.lower() in self.proxy_dirs

    def keep_file(self, name: str, in_proxy: bool = False) -> bool:
        lower = name.lower()
        if lower.startswith(self.skip_prefixes) or lower.endswith(self.skip_suffixes) or self.temp_re.search(lower):
            return False
        i = lower.rfind(".")
        if i <= 0:
            return False
        ext = lower[i + 1:]
        if ext in self.audio or ext in self.master:
            return True
        return in_proxy and ext in self.proxy_video


def _strings(value: Any) -> list[str]:
    if not isinstance(value, (list, tuple)):
        return []
    return [str(v) for v in value if isinstance(v, str) and v.strip()]


def clean_roots(roots: Any) -> list[str]:
    """The manifest's roots -> safe relative '/' paths ("" = the whole volume). A root that is
    absolute or climbs out with `..` is dropped: it is the SERVER's list, but a path this side
    would walk outside the volume is never acceptable. No roots named at all is the whole volume;
    roots named and none of them safe is NO roots (the caller refuses the scan), never the whole
    volume by accident."""
    if not isinstance(roots, (list, tuple)):
        return [""]
    out: list[str] = []
    for r in roots:
        text = str(r or "").replace("\\", "/").strip("/")
        parts = [p for p in text.split("/") if p not in ("", ".")]
        if ".." in parts or re.match(r"^[A-Za-z]:", text):
            log.warning("ledger scan: ignoring the unsafe root %r", r)
            continue
        rel = "/".join(parts)
        if rel not in out:
            out.append(rel)
    return out or ([""] if not roots else [])


class Progress:
    """What the walk has done so far, for the 2-second post. Thread-safe; `snapshot()` is the body."""

    def __init__(self, clock: Callable[[], float] = time.monotonic) -> None:
        self._clock = clock
        self._lock = threading.Lock()
        self.files = 0
        self.bytes = 0
        self.dirs = 0
        self.current = ""
        self._mark_t = clock()
        self._mark_bytes = 0
        self._bps = 0.0

    def add(self, size: int) -> None:
        with self._lock:
            self.files += 1
            self.bytes += int(size)

    def visit(self, rel: str) -> None:
        with self._lock:
            self.dirs += 1
            self.current = rel

    def snapshot(self) -> dict[str, Any]:
        """{filesDone, bytesSeen, bps, current}; `bps` is listed bytes per second since the last
        snapshot, smoothed so one empty second does not read as a stalled walk."""
        with self._lock:
            now = self._clock()
            dt = now - self._mark_t
            if dt > 0.05:
                inst = (self.bytes - self._mark_bytes) / dt
                self._bps = inst if self._bps == 0.0 else 0.5 * self._bps + 0.5 * inst
                self._mark_t, self._mark_bytes = now, self.bytes
            return {"filesDone": self.files, "bytesSeen": self.bytes, "bps": round(self._bps, 1),
                    "current": self.current, "dirs": self.dirs}


BS = chr(92)
BS2 = BS + BS
REPARSE_POINT = 0x400


def long_path(path: str) -> str:
    """The Windows extended-length form of an absolute path (so the walk is not limited to 260
    characters); any other platform's path as it is."""
    if os.name != "nt" or path.startswith(BS2 + "?" + BS):
        return path
    full = os.path.abspath(path)
    if full.startswith(BS2):
        return BS2 + "?" + BS + "UNC" + BS + full[2:]
    return BS2 + "?" + BS + full


def is_link(entry: "os.DirEntry[str]") -> bool:
    """A symlink, an NTFS junction or any other reparse point: a directory that may lead off the
    volume or back round to a parent. Not followed."""
    try:
        if entry.is_symlink():
            return True
        junction = getattr(entry, "is_junction", None)
        if junction is not None and junction():
            return True
        return bool(getattr(entry.stat(follow_symlinks=False), "st_file_attributes", 0) & REPARSE_POINT)
    except OSError:
        return True                      # cannot tell: do not go in


def walk(volume_root: str, roots: Iterable[str], rules: Rules,
         should_stop: Callable[[], str] = lambda: "",
         progress: Optional[Progress] = None,
         on_unreadable: Optional[Callable[[str, OSError], None]] = None,
         on_link: Optional[Callable[[str], None]] = None) -> Iterable[list[Any]]:
    """Yield `[path, size, mtimeMs]` for every tracked file under each root, depth first.
    Stops (just returns) when `should_stop()` says anything. Never raises on a bad folder: a folder
    or entry that cannot be read goes to `on_unreadable(rel, exc)`. Links are not followed."""
    base = str(volume_root)
    for root in roots:
        start = os.path.join(base, *root.split("/")) if root else base
        stack = [(long_path(start), root, False)]
        while stack:
            if should_stop():
                return
            directory, rel_dir, in_proxy = stack.pop()
            if progress is not None:
                progress.visit(rel_dir)
            try:
                with os.scandir(directory) as it:
                    entries = list(it)
            except OSError as exc:
                if on_unreadable is not None:
                    on_unreadable(rel_dir, exc)
                continue
            for e in entries:
                name = e.name
                rel = f"{rel_dir}/{name}" if rel_dir else name
                try:
                    if e.is_dir(follow_symlinks=False):
                        if rules.skip_dir(name):
                            continue
                        if is_link(e):
                            if on_link is not None:
                                on_link(rel)
                            continue
                        stack.append((e.path, rel, in_proxy or rules.is_proxy_dir(name)))
                        continue
                    if not e.is_file(follow_symlinks=False) or not rules.keep_file(name, in_proxy):
                        continue
                    st = e.stat(follow_symlinks=False)
                except OSError as exc:
                    if on_unreadable is not None:
                        on_unreadable(rel_dir, exc)          # the FOLDER the entry is in: that is what is exempted
                    continue
                size = int(st.st_size)
                if progress is not None:
                    progress.add(size)
                yield [rel, size, int(round(st.st_mtime * 1000.0))]


class LedgerScan:
    """One scan: walk, chunk, send. Every seam is a parameter (the chunk sender, the clock, the
    waiter), so the suite runs it against a temp folder and a fake server.

    `send_chunk(seq, rows) -> int` posts one chunk and returns the HTTP status (it may raise on a
    transport failure); 200 is accepted, 5xx/429 and exceptions are retried under the same `seq`,
    any other status ends the scan with a ScanError (a refused chunk will not become acceptable).
    `alive()` -> is the drive still there (checked between folders, at most every few seconds).
    `should_stop()` -> a reason to stop ("" = carry on).
    """

    def __init__(
        self,
        send_chunk: Callable[[int, list[list[Any]]], int],
        should_stop: Callable[[], str] = lambda: "",
        alive: Optional[Callable[[], bool]] = None,
        clock: Callable[[], float] = time.monotonic,
        wait: Optional[Callable[[float], bool]] = None,
        rows_per_chunk: int = CHUNK_ROWS,
        progress: Optional[Progress] = None,
    ) -> None:
        self._send = send_chunk
        self._should_stop = should_stop
        self._alive = alive
        self._clock = clock
        self._wait = wait or (lambda seconds: (time.sleep(seconds), False)[1])
        self.rows_per_chunk = max(1, int(rows_per_chunk))
        self.progress = progress or Progress(clock)
        self.unreadable: list[str] = []
        self.unreadable_count = 0
        self._unreadable_seen: set[str] = set()
        self.links = 0
        self._last_alive = clock()
        self.chunks = 0
        self.stopped = ""
        self.vanished = False

    # -- the drive ---------------------------------------------------------
    def _check_alive(self) -> bool:
        """Is the drive still there? At most once per ALIVE_CHECK_SECONDS: asking per failing folder
        would hammer a dying drive (and the volume lister) once for every folder it cannot open.
        False, with `vanished` set, when it is gone."""
        if self._alive is None:
            return True
        now = self._clock()
        if now - self._last_alive < ALIVE_CHECK_SECONDS:
            return not self.vanished
        self._last_alive = now
        try:
            ok = bool(self._alive())
        except Exception:                                         # noqa: BLE001
            ok = False
        if not ok:
            self.vanished = True
        return ok

    def _stop_reason(self) -> str:
        reason = self._should_stop()
        if reason:
            return reason
        if not self._check_alive():
            return "the drive is gone"
        return ""

    def _note_unreadable(self, rel: str, exc: OSError) -> None:
        if isinstance(exc, FileNotFoundError):
            # the folder is not there (a deleted watch root, a folder removed mid-walk): it HAS no
            # files, which is an answer. Unless the whole drive left: that is checked, not assumed.
            self._check_alive()
            return
        if rel in self._unreadable_seen:
            return
        self._unreadable_seen.add(rel)
        self.unreadable_count += 1
        if len(self.unreadable) < MAX_UNREADABLE_LISTED:
            self.unreadable.append(rel)
        log.debug("ledger scan: cannot read %r (%s)", rel, exc)
        self._check_alive()                       # a folder that errors because the drive left is the drive leaving

    def _note_link(self, rel: str) -> None:
        self.links += 1

    # -- sending -----------------------------------------------------------
    def _send_with_retry(self, seq: int, rows: list[list[Any]]) -> None:
        last = ""
        for attempt in range(CHUNK_TRIES):
            try:
                status = int(self._send(seq, rows))
            except Exception as exc:                              # noqa: BLE001
                status, last = 0, f"{type(exc).__name__}: {exc}"
            else:
                last = f"HTTP {status}"
            if status == 200:
                return
            retryable = status == 0 or status == 429 or status >= 500
            if not retryable:
                raise ScanError(f"the dashboard refused scan chunk {seq} ({last})",
                                retryable=status in (401, 403))
            if attempt + 1 < CHUNK_TRIES:
                if self._wait(CHUNK_RETRY_SECONDS * (attempt + 1)):
                    raise ScanError("stopped while retrying a chunk", retryable=True)
        raise ScanError(f"scan chunk {seq} could not be delivered ({last})", retryable=True)

    # -- the run -----------------------------------------------------------
    def run(self, volume_root: str, roots: Any, rules: Optional[dict[str, Any]] = None) -> dict[str, Any]:
        """Walk and upload. -> {files, bytes, complete, reason, chunks, unreadable}.
        Raises ScanError when a chunk cannot be delivered; the caller still sends `finish`
        with complete false."""
        self._last_alive = self._clock()
        rule_set = rules if isinstance(rules, Rules) else Rules(rules)
        wanted = clean_roots(roots)
        if not wanted:
            raise ScanError("none of the scan's roots is a safe folder on the drive", retryable=False)
        files = total = 0
        seq = 0
        buf: list[list[Any]] = []

        def stop() -> str:
            reason = self._stop_reason()
            if reason:
                self.stopped = reason
            return reason

        for row in walk(volume_root, wanted, rule_set, stop, self.progress, self._note_unreadable, self._note_link):
            buf.append(row)
            files += 1
            total += int(row[1])
            if len(buf) >= self.rows_per_chunk:
                self._send_with_retry(seq, buf)
                seq += 1
                self.chunks = seq
                buf = []
        if not self.stopped:
            stop()                                  # the drive may have gone during the last folder
        if self.vanished and not self.stopped:
            self.stopped = "the drive is gone"
        if buf:                                     # a half-listing is sent too: the server records it partial
            self._send_with_retry(seq, buf)
            seq += 1
            self.chunks = seq
        reason = self.stopped
        if not reason and self.unreadable_count > len(self.unreadable):
            # more unreadable folders than the finish can name: the unnamed ones would be read as gone
            reason = f"{self.unreadable_count} folders could not be read (more than can be listed)"
        complete = not reason and not self.vanished
        return {"files": files, "bytes": total, "complete": complete, "reason": reason,
                "chunks": seq, "unreadable": list(self.unreadable),
                "unreadableCount": self.unreadable_count, "links": self.links}


def volume_alive(volume_root: str, serial: str,
                 volumes_fn: Callable[..., list[dict[str, Any]]]) -> bool:
    """Is the volume with this serial still readable at (or anywhere but) its root? A removed card
    reader's letter stays but the serial goes, and another card can take the letter."""
    if not os.path.isdir(volume_root):
        return False
    want = str(serial or "").upper()
    if not want:
        return True
    try:
        for v in volumes_fn("all", set()):
            if str(v.get("serial") or "").upper() == want:
                return True
    except Exception:                                             # noqa: BLE001
        return True                                               # cannot tell: not a verdict
    return False



# ---------------------------------------------------------------- the job
SCAN_PATH = "/sorter/agent/ledger/scan"
SORTER_TIMEOUT_SECONDS = 60.0
FINISH_TRIES = 4
FINISH_RETRY_SECONDS = 3.0

RequestFn = Callable[[str, str, Any, dict, float], tuple[int, Any]]


def gzip_chunk(rows: list[list[Any]], seq: int, attempt: Any = None) -> bytes:
    import gzip
    import json
    body: dict[str, Any] = {"rows": rows, "seq": seq}
    if attempt is not None:
        body["attempt"] = attempt
    return gzip.compress(json.dumps(body, separators=(",", ":")).encode("utf-8"))


class ScanJob:
    """One `ledger-scan` job, from the manifest to the finish. The glue in jobs_runner only
    supplies the seams: `request` (the dashboard call, bytes bodies allowed), `headers`, the
    stop test and the volume finder. Raises ScanError for a scan that cannot run; a scan that
    ran (even cut short) returns its result after `finish` has been posted."""

    def __init__(
        self,
        job_id: int,
        inputs: dict[str, Any],
        dashboard_url: str,
        request: RequestFn,
        headers: Callable[[], dict[str, str]],
        volumes_fn: Callable[..., list[dict[str, Any]]],
        should_stop: Callable[[], str] = lambda: "",
        clock: Callable[[], float] = time.monotonic,
        wait: Optional[Callable[[float], bool]] = None,
        rows_per_chunk: int = CHUNK_ROWS,
        progress_seconds: float = PROGRESS_SECONDS,
    ) -> None:
        self.job_id = int(job_id)
        self.inputs = inputs or {}
        self._url = dashboard_url.rstrip("/")
        self._request = request
        self._headers = headers
        self._volumes = volumes_fn
        self._should_stop = should_stop
        self._clock = clock
        self._wait = wait or (lambda seconds: (time.sleep(seconds), False)[1])
        self.rows_per_chunk = rows_per_chunk
        self.progress_seconds = float(progress_seconds)
        self.progress = Progress(clock)
        self.attempt: Any = None           # the manifest's token for THIS claim of the job
        self.stale = False                 # the server answered 409: this attempt is over, stop

    # -- the wire ----------------------------------------------------------
    def _path(self, suffix: str = "") -> str:
        return f"{self._url}{SCAN_PATH}/{self.job_id}{suffix}"

    def manifest(self) -> dict[str, Any]:
        try:
            status, parsed = self._request("GET", self._path(), None, self._headers(), SORTER_TIMEOUT_SECONDS)
        except Exception as exc:                                  # noqa: BLE001
            raise ScanError(f"could not fetch the scan manifest ({exc})", retryable=True) from exc
        if status in (404, 409, 410):
            raise ScanError(f"the sorter has no scan for this job (HTTP {status})", retryable=False)
        if status != 200 or not isinstance(parsed, dict):
            raise ScanError(f"the sorter answered HTTP {status} for the scan manifest", retryable=True)
        return parsed

    def _send_chunk(self, seq: int, rows: list[list[Any]]) -> int:
        headers = {**self._headers(), "Content-Encoding": "gzip"}
        status, _ = self._request("POST", self._path("/chunk"), gzip_chunk(rows, seq, self.attempt), headers,
                                  SORTER_TIMEOUT_SECONDS)
        return int(status)

    def _post_json(self, suffix: str, body: dict[str, Any]) -> int:
        if self.attempt is not None:
            body = {**body, "attempt": self.attempt}
        status, _ = self._request("POST", self._path(suffix), body, self._headers(), SORTER_TIMEOUT_SECONDS)
        return int(status)

    def _finish(self, result: dict[str, Any]) -> bool:
        body = {"files": int(result.get("files") or 0), "bytes": int(result.get("bytes") or 0),
                "complete": bool(result.get("complete"))}
        if result.get("reason"):
            body["reason"] = str(result["reason"])[:200]
        if result.get("unreadable"):
            body["unreadable"] = list(result["unreadable"])[:MAX_UNREADABLE_LISTED]
            body["unreadableCount"] = int(result.get("unreadableCount") or len(result["unreadable"]))
        for attempt in range(FINISH_TRIES):
            try:
                status = self._post_json("/finish", body)
                if status == 200:
                    return True
                if status in (404, 409, 410, 401, 403):
                    log.warning("ledger scan: the finish for job #%s was refused (HTTP %s)", self.job_id, status)
                    return False
            except Exception:                                     # noqa: BLE001
                log.debug("ledger scan: finish post failed", exc_info=True)
            if attempt + 1 < FINISH_TRIES and self._wait(FINISH_RETRY_SECONDS):
                break
        return False

    # -- the volume ----------------------------------------------------------
    def _serial(self, manifest: dict[str, Any]) -> str:
        serial = str(self.inputs.get("serial") or "").strip()
        if serial:
            return serial.upper()
        vid = str(manifest.get("volumeId") or self.inputs.get("volumeId") or "")
        return vid.split(":", 1)[1].upper() if vid.lower().startswith("vol:") else ""

    def _find_volume(self, serial: str) -> dict[str, Any]:
        if not serial:
            return {}
        for v in self._volumes("all", set()):
            if str(v.get("serial") or "").upper() == serial:
                return v
        return {}

    def _find_root(self, serial: str) -> str:
        return str(self._find_volume(serial).get("root") or "")

    # -- the run -------------------------------------------------------------
    def run(self) -> dict[str, Any]:
        manifest = self.manifest()
        self.attempt = manifest.get("attempt")
        serial = self._serial(manifest)
        volume = self._find_volume(serial)
        root = str(volume.get("root") or "")
        roots = manifest.get("roots", self.inputs.get("roots", [""]))
        if root and volume.get("system"):
            # NEVER A SYSTEM VOLUME'S ROOT: Windows, Program Files and every user's profile live there, and a
            # listing of it is a million rows of nothing the ledger tracks. Only folders a watch names.
            named = [r for r in clean_roots(roots) if r]
            if not named:
                result = {"files": 0, "bytes": 0, "complete": False, "chunks": 0, "unreadable": [],
                          "reason": "the system drive is only scanned through a watched folder, never from its root"}
                self._finish(result)
                raise ScanError(result["reason"], retryable=False)
            roots = named
        if not root:
            result = {"files": 0, "bytes": 0, "complete": False, "reason": "the drive is not plugged in here",
                      "chunks": 0, "unreadable": []}
            self._finish(result)
            raise ScanError(f"the drive {serial or '?'} is not plugged into this computer", retryable=False)
        rows_per_chunk = self.rows_per_chunk
        try:                                           # the server's own figure (5,000), within sane bounds
            asked = int(manifest.get("chunkRows"))
            if 100 <= asked <= 10000:
                rows_per_chunk = asked
        except (TypeError, ValueError):
            pass
        def should_stop() -> str:
            return self._should_stop() or (STALE_REASON if self.stale else "")

        scan = LedgerScan(
            self._send_chunk, should_stop,
            alive=lambda: volume_alive(root, serial, self._volumes),
            clock=self._clock, wait=self._wait, rows_per_chunk=rows_per_chunk, progress=self.progress)
        done = threading.Event()

        def post_progress() -> None:
            while not done.wait(self.progress_seconds):
                try:
                    if self._post_json("/progress", self.progress.snapshot()) == 409:     # best effort otherwise
                        self.stale = True                                                  # LedgerGone: stop this scan
                except Exception:                                 # noqa: BLE001
                    log.debug("ledger scan: progress post failed", exc_info=True)

        poster = threading.Thread(target=post_progress, name="ccsync-ledger-progress", daemon=True)
        poster.start()
        try:
            result = scan.run(root, roots, manifest.get("rules"))
        except ScanError as exc:
            done.set()
            self._finish({"files": scan.progress.files, "bytes": scan.progress.bytes, "complete": False,
                          "reason": str(exc), "unreadable": scan.unreadable,
                          "unreadableCount": scan.unreadable_count})
            raise
        finally:
            done.set()
        result["delivered"] = self._finish(result)
        return result
