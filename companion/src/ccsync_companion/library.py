"""Read the open project's clips out of Resolve's project library, not its API.

Why this module exists (measured on the base rig, 2026-08-26, Resolve
21.0.1.11, library "FF5" on the fleet's postgres:13):

- The watcher's API walk of "Civil Defence - E1" (926 timeline items) takes
  11-14 s and holds fusionscript -- and therefore every other scripting
  client on the machine -- for all of it. The same walk read out of the
  library takes 7 ms and costs Resolve nothing.
- The API walk finds 3 usable file paths out of those 926, because a
  multicam item answers "" to GetClipProperty("File Path") and exposes
  nothing at all about its angles. The library has every angle.

See docs/LIBRARY_WALK_PLAN.md for the whole design; this module is its
reader. Nothing here writes: every statement is a SELECT.

Traps that cost time to find, so that nobody has to find them twice:

- `Sm2TiItem.MediaFilePath` is a PLACEMENT-TIME SNAPSHOT and goes stale on
  relink (10 items in Energy Transition still carry a P:\\ path the pool
  replaced with W:\\Creators_Club\\...). This module never reads it. The
  live path is only ever `BtVideoInfo.Clip` / `BtAudioInfo.Clip`.
- Those `Clip` values are a Resolve blob header followed by a **zstd frame**.
  Read raw they look like a path with letters missing -- those are
  back-references into the directory name. Decompress first.
- `Sm2MpMedia.FieldsBlob` holds the PROXY path, not the media path, and
  behind a second nested zstd frame inside a UTF-16 property bag. See
  `pool_items` for why we do not mine it.
- `Sm2Timeline.SM_Project_id` is NULL for every row in this library (24/24).
  The project -> timeline link is the association table
  `SM_Project_Sm2Timeline` (DbOwner = project, DbAssociate = timeline).
- `Sm2TiTrack.Sm2Sequence_id` is likewise NULL. A sequence reaches its
  tracks through `Sm2SequenceContainer` (`Sm2Sequence_id`) and the
  association `Sm2SequenceContainer_Sm2TiTrack`, whose `DbIndex` is the
  only place the track ORDER lives -- `Sm2TiTrack` has no index column and
  its `SubType` is uninitialised garbage (0x20202020 on V1 here).
- One library holds every project (FF5: five of them, 4005 pool clips).
  Always scope: timelines by the project association, the pool by the
  project's own folder tree.
- `Sm2TiTrack.Type` is not just 0/1: subtitle tracks are Type 2 (6 of the
  287 tracks in FF5, carrying 3360 items) and their `DbIndex` restarts at
  0 like every other kind's, so a subtitle track reported as "video"
  collides with a real V1/V2. Only Types 0 and 1 are walked.
- The library trails the UI by the Live Save interval (~0.3 s here), or
  until the next manual save with Live Save off.

`item_index` on a timeline item dict is the index of the TIMELINE ITEM
within its track, 0-based in Start order, counting the items the library
holds -- not the position of the dict in the returned list. Angles of a
multicam therefore all carry the index of the multicam item they were
expanded from (library walk review, 2026-08-26: the alternative, counting
emitted dicts, made every index after a multicam disagree with the API's
own item order, which is what consumers match against).

Driver choice: `pg8000` (BSD, pure Python) rather than psycopg2 -- the
licence gate has no LGPL entry and there is no compiled wheel to ship per
platform. Disk libraries are stdlib `sqlite3`.
"""

from __future__ import annotations

import logging
import os
import re
import threading
import time
import uuid
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Iterable, Optional

from . import luts

log = logging.getLogger("ccsync.library")

# Resolve frames every blob as <header bytes><zstd frame>. The header is not
# a fixed width across DbTypes, so we find the frame rather than skip N.
ZSTD_MAGIC = b"\x28\xb5\x2f\xfd"

# Resolve's own default library credentials on every machine in the fleet.
DB_DEFAULTS = {"user": "postgres", "password": "DaVinci", "port": 5432}

# Both are 5 s because the watcher polls every 3 s: a library that needs
# longer than one poll interval to answer is a library we should be falling
# back from, not waiting on.
CONNECT_TIMEOUT = 5.0
STATEMENT_TIMEOUT = 5.0

# A compound inside a multicam inside a compound is legal and does happen.
# The cap is not a correctness bound -- the seen-set is -- it is a bound on
# what a corrupt library can cost us.
MAX_EXPAND_DEPTH = 8

# Sm2TiTrack.Type. There is no enum in the schema; these are measured.
# Type 2 is subtitles (6 tracks / 3360 items in FF5) and is not walked.
_TRACK_VIDEO = 0
_TRACK_AUDIO = 1

# An unreadable Sm2TiItem.Start is worth exactly one line per process: it is
# a property of the library, so a watcher poll would otherwise repeat it
# every 3 s forever.
_WARNED_START = False


class LibraryUnavailable(Exception):
    """The library could not answer. The caller falls back to the API.

    Every public method of ProjectLibrary raises this and nothing else: a
    bare psycopg/sqlite/zstd exception reaching the watcher would be a
    crash, and the whole point of the library walk is that it is optional.
    """


@dataclass
class LibraryInfo:
    kind: str = ""             # "PostgreSQL" | "Disk"
    name: str = ""             # library name as Resolve's UI shows it
    host: str = ""             # PostgreSQL only
    port: int = 5432
    user: str = "postgres"
    password: str = ""         # Resolve's default when empty
    sqlite_path: str = ""      # Disk only: the project's Project.db

    def describe(self) -> str:
        if self.kind == "Disk":
            return "Disk %s (%s)" % (self.name or "?", self.sqlite_path or "?")
        return "PostgreSQL %s (%s:%d)" % (self.name or "?", self.host or "?", self.port)


# --------------------------------------------------------------------------
# blob decoding
# --------------------------------------------------------------------------

def _varint(buf: bytes, i: int) -> tuple[int, int]:
    result = shift = 0
    while True:
        byte = buf[i]
        i += 1
        result |= (byte & 0x7F) << shift
        if not byte & 0x80:
            return result, i
        shift += 7


def decompress_blob(blob: Any) -> Optional[bytes]:
    """Strip Resolve's blob header and inflate the zstd frame inside.

    Returns None for anything that is not a blob we recognise -- a caller
    that gets None simply has no path for that clip, which is a normal
    state (a generator, a title, an offline clip).
    """
    if blob is None:
        return None
    try:
        raw = bytes(blob)
    except Exception:
        return None
    start = raw.find(ZSTD_MAGIC)
    if start < 0:
        return None
    try:
        import zstandard
    except Exception:  # pragma: no cover -- packaged by track B
        log.warning("library: zstandard is not installed; no library walk", exc_info=True)
        return None
    try:
        return zstandard.ZstdDecompressor().decompressobj().decompress(raw[start:])
    except Exception:
        return None


def clip_path(payload: Optional[bytes]) -> str:
    """The media path out of a decompressed Clip blob. "" when there is none.

    The blob is a flat protobuf: field 1 (tag 0x0a) is the directory, field
    2 (tag 0x12) the file name, field 3 (0x1a) a date string we stop at.
    Both lengths are varints and BOTH can exceed 127 bytes -- a YouTube
    title in the file name routinely does, and a one-byte length reader
    silently truncated those before this was fixed.

    Both fields are collected and the loop stops at the first tag ABOVE 2
    (library walk review, 2026-08-26): protobuf does not promise field
    order, and stopping the moment field 2 arrived would have dropped the
    directory of any blob Resolve ever writes name-first.

    The two halves are joined with the DIRECTORY's own separator, never
    os.sep: a Mac reading a Windows-authored library must hand back the
    stored `P:\\...` spelling, because that is the string classify_path and
    the relink map are written against.
    """
    if not payload:
        return ""
    directory = name = ""
    i, end = 0, len(payload)
    try:
        while i < end:
            key, i = _varint(payload, i)
            tag, wire = key >> 3, key & 7
            if wire != 2 or tag > 2:
                break
            length, i = _varint(payload, i)
            value = payload[i:i + length]
            i += length
            if len(value) != length:
                return ""
            if tag == 1:
                directory = value.decode("utf-8", "replace")
            else:
                name = value.decode("utf-8", "replace")
    except (IndexError, ValueError):
        return ""
    if not directory:
        return name
    if not name:
        return directory
    sep = "\\" if "\\" in directory else "/"
    return directory.rstrip("\\/") + sep + name


# --------------------------------------------------------------------------
# locating the library
# --------------------------------------------------------------------------

# "Current project pointer changed to (Civil Defence) from project library
#  (FF5 : Network)"
_LOG_POINTER = re.compile(
    r"Current project pointer changed to \((?P<project>.+?)\) "
    r"from project library \((?P<lib>.+?) : (?P<kind>\w+)\)")
# "postgres project library FF5 at 100.71.216.3 version 13.23 (...)"
_LOG_PGLIB = re.compile(r"postgres project library (?P<lib>.+?) at (?P<ip>[0-9a-fA-F.:]+) ")


def _log_lines() -> Iterable[str]:
    """Resolve's own log, previous file first, oldest line first.

    luts.resolve_log_path() already knows the Windows and macOS locations,
    so this stays one implementation on both.
    """
    current = luts.resolve_log_path()
    if current is None:
        return
    for path in (current.with_suffix(current.suffix + ".1"), current):
        try:
            if not path.is_file():
                continue
            with open(path, "r", encoding="utf-8", errors="replace") as handle:
                for line in handle:
                    yield line
        except OSError:
            continue


def _info_from_log(project_name: str) -> Optional[LibraryInfo]:
    """Which library the open project came from, read off Resolve's log.

    Resolve 21.0.1 returns None from BOTH GetCurrentDatabase() and
    GetDatabaseList() (measured 2026-08-23 on 21.0.1.11; both worked in
    20.x). Without this fallback the library walk is dead on the exact
    version the fleet runs. The project-pointer line names the library and
    whether it is Network or Disk; the startup lines give each postgres
    library's host.

    The LAST matching pointer line wins: the log is append-only across a
    session and the editor may have opened three projects since launch.
    """
    library = kind = ""
    hosts: dict[str, str] = {}
    for line in _log_lines():
        match = _LOG_PGLIB.search(line)
        if match:
            hosts[match.group("lib")] = match.group("ip")
            continue
        match = _LOG_POINTER.search(line)
        if match and (not project_name or match.group("project") == project_name):
            library, kind = match.group("lib"), match.group("kind")
    if not library:
        return None
    if kind.lower() == "network" or library in hosts:
        return LibraryInfo(kind="PostgreSQL", name=library,
                           host=hosts.get(library, "127.0.0.1"))
    return LibraryInfo(kind="Disk", name=library)


def _info_from_api(resolve: Any) -> Optional[LibraryInfo]:
    """GetCurrentDatabase(), for the Resolve versions where it answers."""
    try:
        manager = resolve.GetProjectManager()
        info = manager.GetCurrentDatabase() if manager else None
    except Exception:
        return None
    if not isinstance(info, dict):
        return None
    kind = str(info.get("DbType") or "")
    if not kind:
        return None
    return LibraryInfo(kind=kind, name=str(info.get("DbName") or ""),
                       host=str(info.get("IpAddress") or ""))


def _resolve_support_dir() -> Optional[Path]:
    """Resolve's Support directory, derived from the log path we already know.

    Windows: %APPDATA%\\...\\DaVinci Resolve\\Support\\logs
    macOS:   ~/Library/Application Support/.../DaVinci Resolve/logs
    In both cases the directory that holds "Resolve Project Library" is the
    log directory's parent, so there is no second platform table to keep in
    step with luts.
    """
    log_path = luts.resolve_log_path()
    if log_path is None:
        return None
    return log_path.parent.parent


def _find_disk_db(library_name: str, project_name: str) -> str:
    """The Project.db of one project inside a disk library. "" when absent."""
    support = _resolve_support_dir()
    if support is None or not project_name:
        return ""
    base = support / "Resolve Project Library"
    roots = []
    if library_name and library_name != "Local Database":
        roots.append(base / library_name / "Resolve Projects")
    roots.append(base / "Resolve Projects")
    for root in roots:
        users = root / "Users"
        try:
            entries = sorted(users.iterdir())
        except OSError:
            continue
        for user_dir in entries:
            candidate = user_dir / "Projects" / project_name / "Project.db"
            try:
                if candidate.is_file():
                    return str(candidate)
            except OSError:
                continue
    return ""


def locate(resolve: Any, project_name: str, overrides: Optional[dict] = None) -> Optional[LibraryInfo]:
    """Work out which project library the open project lives in.

    Never raises. None means "no idea" and the caller keeps using the API.
    Order: the API when it answers, else Resolve's log, and config
    overrides win over both -- an override is the editor telling us the
    other two are wrong, which is the only reason to set one.
    """
    overrides = overrides or {}
    try:
        info = _info_from_api(resolve) if resolve is not None else None
        if info is None:
            info = _info_from_log(project_name)

        host = str(overrides.get("library_db_host") or "").strip()
        name = str(overrides.get("library_db_name") or "").strip()
        user = str(overrides.get("library_db_user") or "").strip()
        password = str(overrides.get("library_db_password") or "")
        try:
            port = int(overrides.get("library_db_port") or 0)
        except (TypeError, ValueError):
            port = 0

        if info is None:
            # A host override alone is enough to go on: it is the documented
            # escape hatch for a machine whose log we cannot read.
            if not (host or name):
                return None
            info = LibraryInfo(kind="PostgreSQL", name=name, host=host or "127.0.0.1")

        info = LibraryInfo(kind=info.kind, name=info.name, host=info.host,
                           port=info.port, user=info.user, password=info.password,
                           sqlite_path=info.sqlite_path)
        if name:
            info.name = name
        if host:
            info.host = host
            # An explicit host means postgres; nobody points a disk library
            # at an IP address.
            info.kind = "PostgreSQL"
        if port:
            info.port = port
        if user:
            info.user = user
        if password:
            info.password = password

        if info.kind == "Disk" and not info.sqlite_path:
            info.sqlite_path = _find_disk_db(info.name, project_name)
        return info
    except Exception:
        log.debug("library: locate failed", exc_info=True)
        return None


# --------------------------------------------------------------------------
# backends
# --------------------------------------------------------------------------

class _Backend:
    """One connection. Queries take :named parameters in BOTH dialects."""

    def query(self, sql: str, **params: Any) -> list[tuple]:
        raise NotImplementedError

    def uid(self, value: str) -> Any:
        """Adapt a uuid string for this dialect's parameter binding."""
        return value

    def close(self) -> None:
        raise NotImplementedError


class _PostgresBackend(_Backend):
    def __init__(self, info: LibraryInfo):
        try:
            import pg8000.native
        except Exception as exc:  # pragma: no cover -- packaged by track B
            raise LibraryUnavailable("pg8000 is not installed: %s" % exc) from exc
        try:
            self._conn = pg8000.native.Connection(
                user=info.user or DB_DEFAULTS["user"],
                password=info.password or DB_DEFAULTS["password"],
                host=info.host,
                port=info.port or DB_DEFAULTS["port"],
                database=info.name,
                timeout=CONNECT_TIMEOUT,
            )
            # Server-side, so it also bounds a query that has already been
            # handed off -- a client-side timer cannot cancel one of those.
            self._conn.run("SET statement_timeout = %d" % int(STATEMENT_TIMEOUT * 1000))
        except LibraryUnavailable:
            raise
        except Exception as exc:
            raise LibraryUnavailable("cannot open %s: %s" % (info.describe(), exc)) from exc

    def query(self, sql: str, **params: Any) -> list[tuple]:
        try:
            rows = self._conn.run(sql, **params)
        except Exception as exc:
            raise LibraryUnavailable("query failed: %s" % exc) from exc
        return [tuple(row) for row in (rows or [])]

    def uid(self, value: str) -> Any:
        # pg8000 sends a str as text and postgres will not compare text to
        # uuid; a real UUID object binds as the uuid type.
        try:
            return uuid.UUID(str(value))
        except (ValueError, AttributeError, TypeError) as exc:
            # Was `return None`, which bound NULL and made the query match
            # nothing at all -- an empty walk that looks exactly like "this
            # timeline has no media" and stops the bridge falling back
            # (library walk review, 2026-08-26). A malformed uid is a bug
            # in the caller or a corrupt library; say so.
            raise LibraryUnavailable("not a uuid: %r" % (value,)) from exc

    def close(self) -> None:
        try:
            self._conn.close()
        except Exception:
            pass


class _SqliteBackend(_Backend):
    def __init__(self, info: LibraryInfo):
        import sqlite3

        path = info.sqlite_path
        if not path or not os.path.isfile(path):
            raise LibraryUnavailable(
                "no Project.db for disk library %r / project (looked at %r)"
                % (info.name, path))
        try:
            # Read-only URI, so a bug here cannot corrupt an editor's
            # project even if it tried to write.
            self._conn = sqlite3.connect(
                "file:%s?mode=ro" % path.replace("\\", "/"),
                uri=True, timeout=CONNECT_TIMEOUT, check_same_thread=False)
        except Exception as exc:
            raise LibraryUnavailable("cannot open %s: %s" % (path, exc)) from exc
        self._deadline = 0.0
        # sqlite3 has no statement_timeout; the progress handler is the only
        # way to bound a query that is scanning rather than waiting on a lock.
        self._conn.set_progress_handler(self._tick, 10000)

    def _tick(self) -> int:
        return 1 if self._deadline and time.monotonic() > self._deadline else 0

    def query(self, sql: str, **params: Any) -> list[tuple]:
        self._deadline = time.monotonic() + STATEMENT_TIMEOUT
        try:
            cursor = self._conn.execute(sql, params)
            return [tuple(row) for row in cursor.fetchall()]
        except Exception as exc:
            raise LibraryUnavailable("query failed: %s" % exc) from exc
        finally:
            self._deadline = 0.0

    def close(self) -> None:
        try:
            self._conn.close()
        except Exception:
            pass


def _uid_str(value: Any) -> str:
    """Normalise a uuid column: pg8000 hands back UUID, sqlite hands back str."""
    if value is None:
        return ""
    return str(value).lower()


def _in_clause(prefix: str, values: list[str]) -> tuple[str, list[str]]:
    """`IN (:p0, :p1, ...)` -- portable where `= ANY(:ids)` is postgres-only."""
    names = ["%s%d" % (prefix, i) for i in range(len(values))]
    return "(%s)" % ", ".join(":" + n for n in names), names


# One bind variable per uid, so an IN list has to be chunked. 500 is well
# under sqlite's SQLITE_MAX_VARIABLE_NUMBER on every build we ship against
# (999 on the oldest, 32766 since 3.32) and irrelevant to postgres' 65535.
_IN_CHUNK = 500


# --------------------------------------------------------------------------
# the reader
# --------------------------------------------------------------------------

class ProjectLibrary:
    """One project's view of one project library. Read-only, thread-safe.

    Every public method raises LibraryUnavailable and nothing else.
    """

    def __init__(self, info: LibraryInfo, project_name: str):
        self.info = info
        self.project_name = project_name
        self._lock = threading.RLock()
        self._backend: Optional[_Backend] = None
        self._project_id = ""
        self._paths: Optional[dict[str, str]] = None
        self._fingerprint: Optional[tuple] = None
        self._connect()

    # -- connection --------------------------------------------------------

    def _connect(self) -> None:
        """Open the backend AND learn the project id, or leave nothing open.

        The post-connect work is inside a try that closes the backend on
        ANY failure (library walk review, 2026-08-26). It used to be bare:
        a _find_project_id that raised -- a project the library does not
        hold, a NAS that dropped the connection between connect and query
        -- propagated out of __init__ with self._backend still holding a
        live postgres session that nobody could reach to close. Measured:
        8 failed constructions left 8 sessions on the server until the gc
        happened to run. The watcher retries every 3 s and postgres ships
        with max_connections=100, so that is the whole fleet locked out of
        the library inside five minutes.
        """
        if self.info.kind == "PostgreSQL":
            backend: _Backend = _PostgresBackend(self.info)
        elif self.info.kind == "Disk":
            backend = _SqliteBackend(self.info)
        else:
            raise LibraryUnavailable("unsupported project library type %r" % self.info.kind)
        self._backend = backend
        try:
            self._project_id = self._find_project_id()
        except BaseException:
            self._backend = None
            self._project_id = ""
            try:
                backend.close()
            except Exception:
                log.debug("library: closing a half-open backend failed", exc_info=True)
            raise

    def _reconnect(self) -> None:
        """At most once per public call. A postgres connection that has been
        idle across the NAS's TCP timeout fails on its NEXT statement, not
        on a health check, so the only honest test is to retry the work."""
        if self._backend is not None:
            self._backend.close()
            self._backend = None
        self._project_id = ""
        self._paths = None
        self._connect()

    def _query(self, sql: str, **params: Any) -> list[tuple]:
        assert self._backend is not None
        return self._backend.query(sql, **params)

    def _uid(self, value: str) -> Any:
        assert self._backend is not None
        return self._backend.uid(value)

    def _query_in(self, sql_before: str, prefix: str, values: list[str],
                  sql_after: str = "") -> list[tuple]:
        """`sql_before IN (...) sql_after`, chunked over `values`."""
        rows: list[tuple] = []
        unique = list(dict.fromkeys(v for v in values if v))
        for start in range(0, len(unique), _IN_CHUNK):
            chunk = unique[start:start + _IN_CHUNK]
            clause, names = _in_clause(prefix, chunk)
            params = {name: self._uid(value) for name, value in zip(names, chunk)}
            rows.extend(self._query(sql_before + clause + sql_after, **params))
        return rows

    def _find_project_id(self) -> str:
        rows = self._query(
            'SELECT "SM_Project_id" FROM "SM_Project" WHERE "ProjectName" = :name',
            name=self.project_name)
        if not rows:
            raise LibraryUnavailable(
                "%s has no project named %r" % (self.info.describe(), self.project_name))
        # A library CAN hold two rows with one name (a restored copy). The
        # first is what Resolve's own project manager shows; picking it is
        # no worse than the API, which cannot tell them apart either.
        return _uid_str(rows[0][0])

    def _ready(self) -> None:
        """Connect if we are not, and refuse to query without a project id.

        Belt and braces for the same bug _connect() now prevents (library
        walk review, 2026-08-26). A ProjectLibrary that reached a query
        with _project_id == "" was not merely useless, it was silently
        wrong: self._uid("") binds NULL, `WHERE "SM_Project_id" = NULL`
        matches nothing, _read_fingerprint answers (None, None) so
        changed() is False forever and pool_paths() serves a cache frozen
        at whatever it last saw, and _folder_tree blames the project for
        "having no media pool". Falling back to the API is right; pretending
        to answer is not.
        """
        if self._backend is None:
            self._connect()
        if not self._project_id:
            raise LibraryUnavailable(
                "project id unknown for %r in %s"
                % (self.project_name, self.info.describe()))

    def _retrying(self, work):
        """Run `work`, and on a library failure reconnect once and rerun."""
        with self._lock:
            try:
                self._ready()
                return work()
            except LibraryUnavailable:
                try:
                    self._reconnect()
                except LibraryUnavailable:
                    raise
                except Exception as exc:
                    raise LibraryUnavailable("reconnect failed: %s" % exc) from exc
                try:
                    self._ready()
                    return work()
                except LibraryUnavailable:
                    raise
                except Exception as exc:
                    raise LibraryUnavailable("library read failed: %s" % exc) from exc
            except Exception as exc:
                raise LibraryUnavailable("library read failed: %s" % exc) from exc

    def close(self) -> None:
        with self._lock:
            if self._backend is not None:
                self._backend.close()
                self._backend = None
            self._paths = None

    # -- paths -------------------------------------------------------------

    def _load_paths(self) -> dict[str, str]:
        """uid -> live media path for EVERY clip in the library.

        Whole-library rather than per-project on purpose: it is one scan
        either way (there is no project column on BtVideoInfo), it measured
        22 ms for 3,873 video rows plus 11 ms for the 72 audio-only ones,
        and a timeline can legitimately reference a clip that lives in
        another project's bin.

        BtVideoInfo first, BtAudioInfo only for clips it did not cover: a
        clip with both has the same path in both, and the video row is the
        one that exists for 98% of them.
        """
        paths: dict[str, str] = {}
        for uid, blob in self._query(
                'SELECT "Sm2MpMedia_id", "Clip" FROM "BtVideoInfo" '
                'WHERE "Sm2MpMedia_id" IS NOT NULL'):
            path = clip_path(decompress_blob(blob))
            if path:
                paths[_uid_str(uid)] = path
        for uid, blob in self._query(
                'SELECT "Sm2MpMedia_id", "Clip" FROM "BtAudioInfo" '
                'WHERE "Sm2MpMedia_id" IS NOT NULL'):
            key = _uid_str(uid)
            if key in paths:
                continue
            path = clip_path(decompress_blob(blob))
            if path:
                paths[key] = path
        return paths

    def pool_paths(self) -> dict[str, str]:
        """uid -> live path, cached until changed() says the library moved."""
        def work():
            if self._paths is None:
                self._paths = self._load_paths()
            return dict(self._paths)
        return self._retrying(work)

    # -- change detection --------------------------------------------------

    def _read_fingerprint(self) -> tuple:
        rows = self._query(
            'SELECT "LastModTimeInSecs" FROM "SM_Project" WHERE "SM_Project_id" = :pid',
            pid=self._uid(self._project_id))
        modified = rows[0][0] if rows else None
        # DbSavedTime is a monotonic per-save counter, not a clock; it is
        # what actually moves when Live Save writes a sequence back, while
        # Sm2Sequence.LastChangedTime is 0 on every row here and
        # Sm2Timeline.ModTimeInSecs only updates on a timeline-level change.
        rows = self._query(
            'SELECT MAX(s."DbSavedTime") FROM "SM_Project_Sm2Timeline" a '
            'JOIN "Sm2Timeline" t ON t."Sm2Timeline_id" = a."DbAssociate" '
            'JOIN "Sm2Sequence" s ON s."Sm2Timeline_id" = t."Sm2Timeline_id" '
            'WHERE a."DbOwner" = :pid',
            pid=self._uid(self._project_id))
        saved = rows[0][0] if rows else None
        return (modified, saved)

    def changed(self) -> bool:
        """Has the library moved since the last read? ~3 ms, two indexed rows.

        The first call establishes the baseline and reports True, so that a
        caller written as `if lib.changed(): reread()` does its first read.
        """
        def work():
            current = self._read_fingerprint()
            moved = current != self._fingerprint
            self._fingerprint = current
            if moved:
                self._paths = None
            return moved
        return self._retrying(work)

    # -- timeline ----------------------------------------------------------

    def _sequence_for_timeline(self, timeline_uid: str) -> str:
        """The current sequence of one timeline. "" when the library has none.

        Live FF5 has exactly one row per timeline, but a timeline that has
        been through a version restore can hold more, and rows[0] of an
        unordered SELECT is whatever the planner felt like -- the walk
        would then wander between versions from poll to poll. Newest save
        wins, ties broken by uid so the answer is at least stable (library
        walk review, 2026-08-26).
        """
        rows = self._query(
            'SELECT "Sm2Sequence_id", "DbSavedTime" FROM "Sm2Sequence" '
            'WHERE "Sm2Timeline_id" = :tid',
            tid=self._uid(timeline_uid))
        if not rows:
            return ""
        ordered = sorted(rows, key=lambda r: (-int(r[1] or 0), _uid_str(r[0])))
        if len(ordered) > 1:
            log.info("library: timeline %s has %d sequences; taking the newest saved (%s)",
                     timeline_uid, len(ordered), _uid_str(ordered[0][0]))
        return _uid_str(ordered[0][0])

    def _sequences_for_clips(self, uids: list[str]) -> dict[str, str]:
        """pool uid -> sequence id, for the multicams / compounds among them.

        A multicam or compound pool clip owns a sequence of its own whose
        `Sm2MpMedia_id` is that clip. An ordinary clip owns none, so a uid
        missing from this dict is simply a leaf.

        Same tie-break as _sequence_for_timeline: newest DbSavedTime, then
        uid, so a clip with two sequences expands the same way on every
        poll instead of following row order (library walk review,
        2026-08-26).
        """
        rows = self._query_in(
            'SELECT "Sm2MpMedia_id", "Sm2Sequence_id", "DbSavedTime" FROM "Sm2Sequence" '
            'WHERE "Sm2MpMedia_id" IN ', "m", uids)
        best: dict[str, tuple] = {}
        for media, seq, saved in rows:
            if media is None:
                continue
            key = _uid_str(media)
            rank = (-int(saved or 0), _uid_str(seq))
            if key in best:
                log.info("library: pool clip %s owns more than one sequence; "
                         "taking the newest saved", key)
                if rank >= best[key][0]:
                    continue
            best[key] = (rank, _uid_str(seq))
        return {key: value[1] for key, value in best.items()}

    def _tracks(self, sequence_ids: list[str]) -> dict[str, list[tuple[str, int, int, str]]]:
        """sequence id -> [(track id, Type, index, name)] in display order.

        DbIndex on the container association is the ONLY ordering there is:
        Sm2TiTrack carries no index and its SubType is uninitialised memory
        (V1 of Civil Defence - E1 reports SubType 538976288, i.e. b"    ").

        Only Types 0 (video) and 1 (audio) come back. Subtitle tracks are
        Type 2 and their DbIndex restarts at 0 like every other kind's, so
        the old "audio if 1 else video" reported subtitle track 1 as V1 and
        two different tracks then claimed the same (track_type, track_index)
        (library walk review, 2026-08-26). Live FF5 has 6 of them holding
        3360 items; they escaped only because every one of those items has
        a NULL MediaRef, which is luck, not a guarantee.

        Batched over every sequence of one recursion level. Per-sequence it
        would be one round trip per multicam, and a 451-cut timeline has
        enough of those to put the library walk back into the seconds the
        API walk already costs.
        """
        rows = self._query_in(
            'SELECT c."Sm2Sequence_id", t."Sm2TiTrack_id", t."Type", a."DbIndex", '
            '       t."UserDefinedName" '
            'FROM "Sm2SequenceContainer" c '
            'JOIN "Sm2SequenceContainer_Sm2TiTrack" a '
            '  ON a."DbOwner" = c."Sm2SequenceContainer_id" '
            'JOIN "Sm2TiTrack" t ON t."Sm2TiTrack_id" = a."DbAssociate" '
            'WHERE c."Sm2Sequence_id" IN ', "s", sequence_ids)
        by_sequence: dict[str, list[tuple[str, int, int, str]]] = {}
        for seq, tid, kind, index, name in rows:
            if int(kind or 0) not in (_TRACK_VIDEO, _TRACK_AUDIO):
                continue
            by_sequence.setdefault(_uid_str(seq), []).append(
                (_uid_str(tid), int(kind or 0), int(index or 0), str(name or "")))
        for tracks in by_sequence.values():
            tracks.sort(key=lambda t: (t[1], t[2]))
        return by_sequence

    def _items(self, track_ids: list[str]) -> dict[str, list[tuple]]:
        """track id -> [(name, start, media ref)] sorted by Start.

        Start and Duration are varchar columns holding decimal frame counts
        ('355231'), so they sort as text unless they go through int().
        Through int(float(...)), in fact: nothing in the schema promises the
        string is integral, and int('355231.0') raises. A value we cannot
        read at all is logged once per process rather than silently becoming
        0, which would quietly move that item to the head of its track
        (library walk review, 2026-08-26).
        """
        rows = self._query_in(
            'SELECT "Sm2TiTrack_id", "Name", "Start", "MediaRef" FROM "Sm2TiItem" '
            'WHERE "Sm2TiTrack_id" IN ', "t", track_ids)
        by_track: dict[str, list[tuple]] = {}
        for track, name, start, media in rows:
            try:
                position = int(float(str(start or "0")))
            except (TypeError, ValueError):
                position = 0
                global _WARNED_START
                if not _WARNED_START:
                    _WARNED_START = True
                    log.warning("library: Sm2TiItem.Start %r is not a number; "
                                "that item sorts to the head of its track", start)
            by_track.setdefault(_uid_str(track), []).append(
                (str(name or ""), position, _uid_str(media)))
        for entries in by_track.values():
            entries.sort(key=lambda e: e[1])
        return by_track

    def timeline_items(self, timeline_uid: str) -> list[dict]:
        """Every item of one timeline, multicams and compounds expanded.

        Item order is (video tracks then audio, each by DbIndex), and
        within a track by Start. An item with no MediaRef -- a transition,
        a generator, a title -- is skipped: it has no media and every
        consumer of this list is looking for media.

        item_index counts TIMELINE ITEMS, so the angles of a multicam all
        carry the index of the multicam item they came from; see the module
        docstring.
        """
        def work():
            sequence_id = self._sequence_for_timeline(timeline_uid)
            if not sequence_id:
                raise LibraryUnavailable("no sequence for timeline %r" % timeline_uid)
            paths = self.pool_paths()
            graph = self._load_graph(sequence_id)
            tracks_of, items_of, seq_of = graph

            items: list[dict] = []
            # Every cut of one multicam carries the SAME MediaRef, so
            # expanding per occurrence returned the same 44 angles 451
            # times on Civil Defence - E1 (5,884 dicts for 926 items).
            # Angles are emitted at the multicam's first appearance; later
            # cuts of it come back as the multicam itself, which is what
            # the API reports for them too.
            done: set = set()
            for track_id, kind, index, track_name in tracks_of.get(sequence_id, []):
                track_type = "audio" if kind == _TRACK_AUDIO else "video"
                position = 0
                for name, _start, media_uid in items_of.get(track_id, []):
                    if not media_uid:
                        continue
                    for expanded in self._expand(media_uid, name, paths, graph, 0, set(), done):
                        expanded.update({
                            "track_type": track_type,
                            "track_index": index + 1,
                            "item_index": position,
                            "source": "library",
                        })
                        if track_name:
                            expanded.setdefault("track_name", track_name)
                        items.append(expanded)
                    position += 1
            return items
        return self._retrying(work)

    def _load_graph(self, sequence_id: str) -> tuple[dict, dict, dict]:
        """Prefetch every sequence/track/item the walk can reach, breadth-first.

        (tracks_of, items_of, seq_of). One round trip per LEVEL, not per
        item: expanding 7 multicams by asking the library about each one as
        the recursion reached it put a 926-item timeline back into hundreds
        of queries, which is exactly the shape this whole module exists to
        get away from.
        """
        tracks_of: dict[str, list] = {}
        items_of: dict[str, list] = {}
        seq_of: dict[str, str] = {}
        pending = [sequence_id]
        depth = 0
        while pending and depth <= MAX_EXPAND_DEPTH:
            level_tracks = self._tracks(pending)
            tracks_of.update(level_tracks)
            track_ids = [t[0] for tracks in level_tracks.values() for t in tracks]
            level_items = self._items(track_ids)
            items_of.update(level_items)
            # Every track we asked about, even the empty ones, so that a
            # later lookup does not re-query.
            for track_id in track_ids:
                items_of.setdefault(track_id, [])
            media = [entry[2] for entries in level_items.values() for entry in entries]
            fresh = [uid for uid in dict.fromkeys(media) if uid and uid not in seq_of]
            found = self._sequences_for_clips(fresh)
            for uid in fresh:
                seq_of[uid] = found.get(uid, "")
            pending = [seq for seq in dict.fromkeys(found.values())
                       if seq and seq not in tracks_of]
            depth += 1
        return tracks_of, items_of, seq_of

    def _expand(self, media_uid: str, name: str, paths: dict[str, str],
                graph: tuple[dict, dict, dict], depth: int, seen: set,
                done: set) -> list[dict]:
        """One timeline item, or the angles of the multicam/compound it is.

        Pure lookup against the prefetched graph -- no queries. The
        seen-set is per top-level item and is what makes a cyclic library
        terminate; MAX_EXPAND_DEPTH only bounds how much a corrupt one can
        cost. A multicam whose angles we cannot read is still returned as
        itself, so the item never silently vanishes from the walk -- and
        that now holds for the two stopping conditions too. They used to
        return [], which dropped the clip entirely and contradicted the
        sentence above: a nested compound the cap cut off simply was not in
        the walk, so the watcher never saw it was offline (library walk
        review, 2026-08-26).
        """
        tracks_of, items_of, seq_of = graph

        def leaf() -> list[dict]:
            return [{
                "file_path": paths.get(media_uid, ""),
                "media_pool_item": None,
                "media_pool_uid": media_uid,
                "clip_name": name,
                "via_multicam": None,
            }]

        if media_uid in seen or depth >= MAX_EXPAND_DEPTH:
            return leaf()
        sequence_id = seq_of.get(media_uid, "")
        if not sequence_id or media_uid in done:
            return leaf()
        seen = seen | {media_uid}
        done.add(media_uid)
        angles: list[dict] = []
        for track_id, _kind, _index, _track_name in tracks_of.get(sequence_id, []):
            for angle_name, _start, angle_uid in items_of.get(track_id, []):
                if not angle_uid:
                    continue
                for expanded in self._expand(angle_uid, angle_name, paths, graph,
                                             depth + 1, seen, done):
                    # The uid recorded is the clip THIS level was reached
                    # through, so a compound inside a multicam reports the
                    # compound -- that is the object the caller can act on.
                    if expanded.get("via_multicam") is None:
                        expanded["via_multicam"] = media_uid
                    angles.append(expanded)
        return angles or leaf()

    # -- media pool --------------------------------------------------------

    def _folder_tree(self) -> dict[str, str]:
        """folder id -> bin_path, for THIS project's folders only.

        How a project finds its root bin (open question 3, answered against
        the live FF5 library 2026-08-26): `SM_Project.MediaPool` is a uuid
        that appears as `Sm2MpFolder.Sm2MediaPool_id` on exactly ONE folder
        -- the root, named "Master", the only folder of the project with
        `Sm2MpFolder_Owner_id` NULL. Every other folder carries
        Sm2MediaPool_id NULL and hangs off its parent by
        Sm2MpFolder_Owner_id. So the root is a lookup and the tree is a
        descent; there is no project column on the folders.

        bin_path is "/"-joined names BELOW the root, so Master itself is "".
        """
        rows = self._query(
            'SELECT "MediaPool" FROM "SM_Project" WHERE "SM_Project_id" = :pid',
            pid=self._uid(self._project_id))
        pool_uid = _uid_str(rows[0][0]) if rows else ""
        if not pool_uid:
            raise LibraryUnavailable("project %r has no media pool" % self.project_name)
        rows = self._query(
            'SELECT "Sm2MpFolder_id", "Name", "Sm2MpFolder_Owner_id", "Sm2MediaPool_id" '
            'FROM "Sm2MpFolder"')
        names: dict[str, str] = {}
        children: dict[str, list[str]] = {}
        root = ""
        for folder_id, name, owner, media_pool in rows:
            key = _uid_str(folder_id)
            names[key] = str(name or "")
            children.setdefault(_uid_str(owner), []).append(key)
            if _uid_str(media_pool) == pool_uid and not _uid_str(owner):
                root = key
        if not root:
            raise LibraryUnavailable(
                "no root bin for project %r (media pool %s)" % (self.project_name, pool_uid))
        tree: dict[str, str] = {}
        stack = [(root, "")]
        while stack:
            folder_id, bin_path = stack.pop()
            if folder_id in tree:
                continue
            tree[folder_id] = bin_path
            for child in children.get(folder_id, []):
                child_path = (bin_path + "/" + names[child]) if bin_path else names[child]
                stack.append((child, child_path))
        return tree

    def pool_items(self) -> list[dict]:
        """Every clip in this project's bins.

        proxy_path / proxy_state are "" (open question 1, answered
        2026-08-26): `BtVideoInfo.Proxy` is a bare reference stub -- 197
        bytes of UTF-16 property bag holding UniqueId, DbType
        "BtVideoProxy" and DataManagerID, present on 3,873 of 3,873 rows
        whether the clip has a proxy or not, with no path and no state. The
        proxy path IS in `Sm2MpMedia.FieldsBlob`, but behind a SECOND
        nested zstd frame inside that property bag, and reading it costs 76
        ms for the library. Not worth it here: proxy relink already has the
        API for the two keys it needs.

        Filtering the folder set in Python rather than in SQL is deliberate
        -- postgres wants `= ANY(:ids)` and sqlite wants an IN list, and
        the whole Sm2MpMedia table is 4,005 rows / a few ms either way.
        """
        def work():
            tree = self._folder_tree()
            paths = self.pool_paths()
            rows = self._query(
                'SELECT "Sm2MpMedia_id", "Name", "Sm2MpFolder_id" FROM "Sm2MpMedia"')
            items = []
            for media_id, name, folder_id in rows:
                bin_path = tree.get(_uid_str(folder_id))
                if bin_path is None:
                    continue                      # another project's bin
                uid = _uid_str(media_id)
                items.append({
                    "file_path": paths.get(uid, ""),
                    "media_pool_item": None,
                    "media_pool_uid": uid,
                    "clip_name": str(name or ""),
                    "source": "library",
                    "resolve_project_name": self.project_name,
                    "bin_path": bin_path,
                    "proxy_path": "",
                    "proxy_state": "",
                })
            return items
        return self._retrying(work)
