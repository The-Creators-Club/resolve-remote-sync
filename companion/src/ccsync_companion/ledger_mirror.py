"""A small offline copy of the ledger, for the field page.

footage-sorter docs/LEDGER-BROWSER-DESIGN.md, "The companion" item 4: in the
field there may be no network, and the page still has to say "already on CIB_D1
and at home" and "safe to format". So when the dashboard IS reachable this
pulls the ledger's copies for this machine's volumes and the NAS:

  GET {dashboard_url}/sorter/agent/ledger/mirror?volumes=<ids>&since=<cursor>
      -> {rows: [...], cursor}

into `~/.ccsync/ledger-mirror.sqlite`, and `where(name, size, mtime)` answers
from it with no network at all.

    mirror = LedgerMirror(cfg, identity_token_fn=...)
    mirror.pull(["vol:1038701C", "nas:thecreatorspool"])    # when online
    mirror.where("A001C003.braw", 4_123_456_789, 1786236852123)   # any time

MATCHING is the ledger's rule: the same lower-cased name and exact size, and
mtime within 3 s when both sides have one (exFAT keeps 2 s). Only LIVE rows are
returned: not missing, not deleted. The server's row id is the key, so a row
that changed (went missing, was moved) replaces the old one, and the same pull
twice changes nothing.

THE CURSOR is the server's string ("seq:id", one sequence for the whole ledger),
stored with the set of volume ids it was taken for. A pull that fails halfway
keeps every page already applied and the cursor of the last applied page.

THE SET IS REMEMBERED, NOT JUST "WHAT IS PLUGGED IN NOW" (audit comp-field-7,
2026-11-11). A pull asks for the volumes attached now AND the ones it pulled
before and has seen within KEEP_DAYS, so a field drive that went into the bag
keeps its rows (and keeps hearing when one goes missing), which is what "a copy
on a drive that is away is believed" needs. Until then the set was the volumes
attached at that moment: every card in or out started the pull over from
nothing, the NAS's whole ledger included, and deleted the rows of whichever
drive had just been unplugged, so a card copied to two field drives dropped to
"one copy" the moment one of them was put away. A volume that is NEW to the set
is caught up on its own from the start (the cursor says nothing about its
history), and then the one cursor carries on for all of them. A volume not seen
for KEEP_DAYS, or one the caller says is not worth keeping (a camera card), is
dropped and its rows with it: nothing would ever tell this mirror they changed.

A row is read tolerantly (the sorter's field names are `volume_id`, `name_lc`,
`missing_since`..., and a camelCase spelling is accepted), and the whole row is
kept as JSON beside the columns the lookup uses, so the page can show anything
the server sent without this module learning about it.
"""
from __future__ import annotations

import json
import logging
import sqlite3
import threading
import time
from pathlib import Path
from typing import Any, Callable, Iterable, Optional
from urllib.parse import quote

from . import config as config_mod

log = logging.getLogger("ccsync.ledgermirror")

FILENAME = "ledger-mirror.sqlite"
AGENT_PATH = "/sorter/agent/ledger/mirror"
TIME_SLACK_MS = 3000
MAX_PAGES = 400
TIMEOUT_SECONDS = 60.0
KEEP_DAYS = 60                # an away volume's rows are kept, and kept fresh, this long
MAX_REMEMBERED = 150          # the server reads at most 200 volume ids per request

SCHEMA = """
CREATE TABLE IF NOT EXISTS copies (
  id INTEGER PRIMARY KEY,
  volume_id TEXT NOT NULL,
  path TEXT NOT NULL,
  name TEXT NOT NULL,
  name_lc TEXT NOT NULL,
  size INTEGER NOT NULL,
  mtime INTEGER,
  role TEXT,
  verified TEXT,
  at TEXT,
  missing_since TEXT,
  deleted_at TEXT,
  raw TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS copies_match ON copies(name_lc, size);
CREATE INDEX IF NOT EXISTS copies_vol ON copies(volume_id);
CREATE TABLE IF NOT EXISTS meta (key TEXT PRIMARY KEY, value TEXT);
"""


def default_path() -> Path:
    return config_mod.CONFIG_DIR / FILENAME


def path_for(cfg: Optional[dict[str, Any]]) -> Optional[Path]:
    """`ledger_mirror_path`, else beside the log (`~/.ccsync`), else None (a harness with no
    log_path writes nothing into the home folder of whoever runs the suite)."""
    explicit = str((cfg or {}).get("ledger_mirror_path") or "").strip()
    if explicit:
        return Path(explicit).expanduser()
    if not str((cfg or {}).get("log_path") or "").strip():
        return None
    try:
        return config_mod.resolved_log_path(cfg or {}).parent / FILENAME
    except Exception:                                             # noqa: BLE001
        return None


def _pick(row: dict[str, Any], *names: str) -> Any:
    for n in names:
        if n in row and row[n] is not None:
            return row[n]
    return None


def _page_rows(parsed: dict[str, Any]) -> list[Any]:
    """A mirror answer's rows as dicts. The server sends `cols` once and each row as a list in that
    order (`id, name_lc, size, mtime, volume_id, path, role, verified, missing, gone`); a page of
    dicts is read as it is."""
    rows = parsed.get("rows")
    if not isinstance(rows, list):
        return []
    cols = parsed.get("cols")
    if not isinstance(cols, list) or not cols:
        return rows
    out: list[Any] = []
    for r in rows:
        out.append(dict(zip(cols, r)) if isinstance(r, (list, tuple)) else r)
    return out


def _to_row(raw: Any) -> Optional[dict[str, Any]]:
    """A server row -> the columns, or None when it has no id/volume/path/size to key on."""
    if not isinstance(raw, dict):
        return None
    try:
        rid = int(_pick(raw, "id", "copyId"))
        volume = str(_pick(raw, "volume_id", "volumeId", "volume") or "")
        path = str(_pick(raw, "path") or "")
        size = int(_pick(raw, "size"))
    except (TypeError, ValueError):
        return None
    if not volume or not path:
        return None
    name = str(_pick(raw, "name") or path.rsplit("/", 1)[-1])
    mtime = _pick(raw, "mtime", "mtimeMs")
    try:
        mtime = None if mtime is None else int(round(float(mtime)))
    except (TypeError, ValueError):
        mtime = None
    deleted = _pick(raw, "deleted_at", "deletedAt")
    if deleted is None and raw.get("gone") in (1, True):
        deleted = "1"                      # replaced, moved or deleted: drop it from a mirror
    if deleted is None and raw.get("deleted") is True:
        deleted = "1"
    missing = _pick(raw, "missing_since", "missingSince")
    if missing is None and raw.get("missing") in (1, True):
        missing = "1"                      # not found by the last scan
    return {"id": rid, "volume_id": volume, "path": path, "name": name, "name_lc": name.lower(),
            "size": size, "mtime": mtime, "role": _pick(raw, "role"), "verified": _pick(raw, "verified"),
            "at": _pick(raw, "at"), "missing_since": None if missing is None else str(missing),
            "deleted_at": None if deleted is None else str(deleted),
            "raw": json.dumps(raw, separators=(",", ":"))}


class LedgerMirror:
    """The offline mirror. Every seam is a parameter (HTTP call, clock), so the suite needs no
    dashboard. Safe to use from several threads: a connection is opened per call."""

    def __init__(
        self,
        cfg: Optional[dict[str, Any]] = None,
        path: Optional[Path | str] = None,
        request_fn: Optional[Callable[..., tuple[int, Any]]] = None,
        identity_token_fn: Optional[Callable[[], Optional[str]]] = None,
        clock: Callable[[], float] = time.time,
    ) -> None:
        self.cfg = cfg if cfg is not None else {}
        self.path = Path(path) if path else (path_for(self.cfg) or default_path())
        self._request = request_fn
        self._identity = identity_token_fn
        self._clock = clock
        self._lock = threading.Lock()
        self._ready = False
        self._held = threading.local()

    # -- storage -----------------------------------------------------------
    def _connect(self) -> sqlite3.Connection:
        # The schema (and the WAL pragma, which is a property of the FILE) is run once per
        # process, and again whenever the file is not there: it used to run on every connect,
        # and a card verdict connects once per file on the card (audit comp-field-4, 2026-11-11).
        fresh = not self._ready or not self.path.exists()
        if fresh:
            self.path.parent.mkdir(parents=True, exist_ok=True)
        conn = sqlite3.connect(str(self.path), timeout=10.0)
        conn.row_factory = sqlite3.Row
        if fresh:
            try:
                conn.execute("PRAGMA journal_mode=WAL")
            except sqlite3.DatabaseError:
                pass
            try:
                conn.executescript(SCHEMA)
            except sqlite3.DatabaseError:
                conn.close()
                raise
            self._ready = True
        return conn

    def reading(self) -> "_Reading":
        """`with mirror.reading():` keeps ONE connection open for this thread's `where` calls
        inside the block, instead of one per call. For a caller about to ask a few thousand
        times (a card verdict). Nesting is fine; other threads are not affected."""
        return _Reading(self)

    def _meta(self, conn: sqlite3.Connection, key: str, default: str = "") -> str:
        row = conn.execute("SELECT value FROM meta WHERE key=?", (key,)).fetchone()
        return default if row is None else str(row["value"])

    def _set_meta(self, conn: sqlite3.Connection, key: str, value: str) -> None:
        conn.execute("INSERT INTO meta(key, value) VALUES(?, ?) ON CONFLICT(key) DO UPDATE SET value=excluded.value",
                     (key, value))

    def apply(self, rows: Iterable[Any]) -> int:
        """Upsert server rows by id. -> how many were stored (a row with no usable id/path/size is skipped)."""
        items = [r for r in (_to_row(x) for x in rows or ()) if r is not None]
        if not items:
            return 0
        with self._lock:
            conn = self._connect()
            try:
                with conn:
                    conn.executemany(
                        "INSERT INTO copies(id, volume_id, path, name, name_lc, size, mtime, role, verified, at,"
                        " missing_since, deleted_at, raw) VALUES(:id, :volume_id, :path, :name, :name_lc, :size,"
                        " :mtime, :role, :verified, :at, :missing_since, :deleted_at, :raw)"
                        " ON CONFLICT(id) DO UPDATE SET volume_id=excluded.volume_id, path=excluded.path,"
                        " name=excluded.name, name_lc=excluded.name_lc, size=excluded.size, mtime=excluded.mtime,"
                        " role=excluded.role, verified=excluded.verified, at=excluded.at,"
                        " missing_since=excluded.missing_since, deleted_at=excluded.deleted_at, raw=excluded.raw",
                        items)
            finally:
                conn.close()
        return len(items)

    # -- the pull ----------------------------------------------------------
    def _headers(self) -> dict[str, str]:
        identity = ""
        if self._identity is not None:
            try:
                identity = str(self._identity() or "")
            except Exception:                                     # noqa: BLE001
                log.debug("ledger mirror: identity_token_fn failed", exc_info=True)
        return {"Content-Type": "application/json",
                "X-CCSync-Token": str(self.cfg.get("dashboard_token", "") or "").strip(),
                "X-CCSync-Identity": identity}

    def _plan(self, attached: list[str], keep: Optional[Callable[[str], bool]]) -> dict[str, Any]:
        """Which volumes this pull asks for, and from where. Reads the meta, writes nothing."""
        now = self._clock()
        conn = self._connect()
        try:
            held = [v for v in self._meta(conn, "volumes").split(",") if v]
            cursor = self._meta(conn, "cursor")
            try:
                seen = json.loads(self._meta(conn, "volume_seen", "{}"))
            except ValueError:
                seen = {}
        finally:
            conn.close()
        if not isinstance(seen, dict):
            seen = {}
        here = set(attached)
        cutoff = now - KEEP_DAYS * 86400

        def wanted(vid: str) -> bool:
            try:
                last = float(seen.get(vid, now))      # a mirror from before 2026-11-11 has no stamps
            except (TypeError, ValueError):
                last = now
            if last < cutoff:
                return False
            if keep is None:
                return True
            try:
                return bool(keep(vid))
            except Exception:                                     # noqa: BLE001
                return True

        away = [v for v in held if v not in here and wanted(v)]
        away.sort(key=lambda v: -float(seen.get(v, now) or 0))
        ids = sorted(here | set(away[:max(0, MAX_REMEMBERED - len(here))]))
        stamps = {v: (now if v in here else float(seen.get(v, now) or now)) for v in ids}
        return {"ids": ids, "held": held, "cursor": cursor, "seen": stamps,
                # with no cursor the main pull starts from nothing and covers them all
                "new": [v for v in ids if v not in set(held)] if cursor else []}

    def _fetch(self, request: Callable[..., tuple[int, Any]], url: str, want: str, cursor: str,
               out: dict[str, Any], on_page: Callable[[dict[str, Any], str], None]) -> Optional[str]:
        """Page through one volume set from `cursor`. -> the last cursor, or None when the
        dashboard could not be asked (out["error"] says why; pages already applied stay)."""
        for _page in range(MAX_PAGES):
            q = f"{url}{AGENT_PATH}?volumes={quote(want, safe=',:')}&since={quote(cursor, safe='')}"
            try:
                status, parsed = request("GET", q, None, self._headers(), TIMEOUT_SECONDS)
            except Exception as exc:                              # noqa: BLE001
                out["error"] = f"could not reach the dashboard ({exc})"
                return None
            out["status"] = int(status)
            if status != 200 or not isinstance(parsed, dict):
                out["error"] = f"the dashboard answered HTTP {status}"
                return None
            rows = _page_rows(parsed)
            new_cursor = str(parsed.get("cursor") if parsed.get("cursor") is not None else cursor)
            self.apply(rows)
            out["rows"] += len(rows)
            out["pages"] += 1
            on_page(parsed, new_cursor)
            moved = new_cursor != cursor
            cursor = new_cursor
            more = parsed.get("more")
            if more is True and moved:
                continue                                   # the server says there is more: ask again at once
            if more is None and rows and moved:
                continue                                   # an answer with no `more`: until a page comes back empty
            break
        return cursor

    def _note_volumes(self, conn: sqlite3.Connection, parsed: dict[str, Any]) -> None:
        infos = parsed.get("volumes")
        if isinstance(infos, list) and infos:
            known = self._volume_info(conn)
            for v in infos:
                if isinstance(v, dict) and v.get("id"):
                    known[str(v["id"])] = {"label": v.get("label"), "kind": v.get("kind")}
            self._set_meta(conn, "volume_info", json.dumps(known))

    def pull(self, volumes: Iterable[str],
             keep: Optional[Callable[[str], bool]] = None) -> dict[str, Any]:
        """Fetch what changed since the last pull for these volume ids (the ones attached now),
        for the ones pulled before that are away (see the module's note on the remembered set),
        and for whatever the server adds. `keep(volume id)` False drops an AWAY volume from the
        set (a camera card: its copies never count). -> {ok, status, rows, pages, cursor, error}.
        Never raises; an unreachable dashboard is `ok: False` and leaves the mirror as it was."""
        out: dict[str, Any] = {"ok": False, "status": None, "rows": 0, "pages": 0, "cursor": "", "error": ""}
        url = str(self.cfg.get("dashboard_url", "") or "").strip().rstrip("/")
        token = str(self.cfg.get("dashboard_token", "") or "").strip()
        if not url or not token:
            out["error"] = "no dashboard is configured"
            return out
        attached = sorted({str(v).strip() for v in volumes or () if str(v).strip()})
        request = self._request
        if request is None:
            from .broll_ingest import default_request
            request = default_request
        try:
            plan = self._plan(attached, keep)
        except sqlite3.DatabaseError as exc:
            out["error"] = f"the mirror file cannot be read ({exc})"
            return out
        ids, cursor = plan["ids"], plan["cursor"]
        want = ",".join(ids)
        state = {"forgot": set(plan["held"]) <= set(ids)}

        def forget_dropped() -> None:
            # Rows of a volume no longer pulled would stay "live" for ever (nothing will ever tell
            # this mirror they went missing). Dropped only once the dashboard has answered, so a
            # pull that cannot reach it leaves the mirror as it was.
            if not state["forgot"]:
                self._forget_other_volumes(ids)
                state["forgot"] = True

        def caught_up(parsed: dict[str, Any], _cursor: str) -> None:
            forget_dropped()
            with self._lock:
                conn = self._connect()
                try:
                    with conn:
                        self._note_volumes(conn, parsed)
                finally:
                    conn.close()

        if plan["new"]:
            # their history first, from the start, on their own: the shared cursor is only moved
            # by the pull of the whole set below, so a catch-up that dies is simply done again
            if self._fetch(request, url, ",".join(plan["new"]), "", out, caught_up) is None:
                return out

        def stored(parsed: dict[str, Any], new_cursor: str) -> None:
            forget_dropped()
            with self._lock:
                conn = self._connect()
                try:
                    with conn:
                        self._set_meta(conn, "volumes", want)
                        self._set_meta(conn, "volume_seen", json.dumps(plan["seen"]))
                        self._set_meta(conn, "cursor", new_cursor)
                        self._set_meta(conn, "pulled_at", str(int(self._clock())))
                        self._note_volumes(conn, parsed)
                finally:
                    conn.close()

        last = self._fetch(request, url, want, cursor, out, stored)
        if last is None:
            return out
        out["ok"], out["cursor"] = True, last
        return out

    def _forget_other_volumes(self, keep: list[str]) -> None:
        with self._lock:
            conn = self._connect()
            try:
                with conn:
                    marks = ",".join("?" * len(keep))
                    if keep:
                        conn.execute(f"DELETE FROM copies WHERE volume_id NOT IN ({marks})", keep)
                    else:
                        conn.execute("DELETE FROM copies")
                    known = {k: v for k, v in self._volume_info(conn).items() if k in set(keep)}
                    self._set_meta(conn, "volume_info", json.dumps(known))
            finally:
                conn.close()

    # -- what the server called the volumes -------------------------------------
    def _volume_info(self, conn: sqlite3.Connection) -> dict[str, Any]:
        try:
            got = json.loads(self._meta(conn, "volume_info", "{}"))
        except ValueError:
            return {}
        return got if isinstance(got, dict) else {}

    def volume_info(self) -> dict[str, dict[str, Any]]:
        """{volume id: {label, kind}} for every volume a pull has named, so the field page can say
        "already on CIB_D1" without asking."""
        try:
            conn = self._connect()
        except sqlite3.DatabaseError:
            return {}
        try:
            return self._volume_info(conn)
        finally:
            conn.close()

    # -- the lookup ----------------------------------------------------------
    def where(self, name: str, size: int, mtime: Optional[float] = None) -> list[dict[str, Any]]:
        """Live copies of this file: [{id, volume_id, path, name, size, mtime, role, verified, at}].
        No network. `mtime` is epoch milliseconds, or None to match on name and size alone."""
        held = getattr(self._held, "conn", None)
        try:
            conn = held if held is not None else self._connect()
        except sqlite3.DatabaseError:
            return []
        try:
            rows = conn.execute(
                "SELECT id, volume_id, path, name, size, mtime, role, verified, at FROM copies"
                " WHERE name_lc=? AND size=? AND missing_since IS NULL AND deleted_at IS NULL ORDER BY id",
                (str(name).lower(), int(size))).fetchall()
        except sqlite3.DatabaseError:
            if held is None:
                raise
            return []                       # inside reading(): a broken mirror is an empty one
        finally:
            if held is None:
                conn.close()
        out = []
        for r in rows:
            if mtime is not None and r["mtime"] is not None and abs(int(r["mtime"]) - float(mtime)) > TIME_SLACK_MS:
                continue
            out.append(dict(r))
        return out

    def volumes_holding(self, name: str, size: int, mtime: Optional[float] = None) -> list[str]:
        """The distinct volume ids holding a live copy of the file, in the order first recorded."""
        seen: list[str] = []
        for r in self.where(name, size, mtime):
            if r["volume_id"] not in seen:
                seen.append(r["volume_id"])
        return seen

    def status(self) -> dict[str, Any]:
        try:
            conn = self._connect()
        except sqlite3.DatabaseError:
            return {"rows": 0, "cursor": "", "volumes": [], "pulled_at": None}
        try:
            n = conn.execute("SELECT COUNT(*) FROM copies").fetchone()[0]
            vols = [v for v in self._meta(conn, "volumes").split(",") if v]
            pulled = self._meta(conn, "pulled_at")
            return {"rows": int(n), "cursor": self._meta(conn, "cursor"), "volumes": vols,
                    "pulled_at": int(pulled) if pulled else None}
        finally:
            conn.close()


class _Reading:
    """See LedgerMirror.reading. The connection lives in a thread-local, so two threads inside
    two blocks never share one (a sqlite3 connection must stay on the thread that opened it)."""

    def __init__(self, mirror: LedgerMirror) -> None:
        self._mirror = mirror
        self._mine: Optional[sqlite3.Connection] = None

    def __enter__(self) -> "_Reading":
        held = self._mirror._held
        if getattr(held, "conn", None) is None:
            try:
                self._mine = held.conn = self._mirror._connect()
            except sqlite3.DatabaseError:
                self._mine = None             # where() falls back to a connection per call
        return self

    def __exit__(self, *_exc: Any) -> None:
        if self._mine is not None:
            self._mirror._held.conn = None
            try:
                self._mine.close()
            except sqlite3.Error:
                pass
            self._mine = None
