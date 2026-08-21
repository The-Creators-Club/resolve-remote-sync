"""Server-side, revocable browser sessions and the login throttle.

Why this exists (COMMERCIAL_READINESS.md item 6 / H1, 2026-08-17): the session
cookie was a self-contained HMAC token with a 7-day expiry and NOTHING behind
it, so a stolen cookie was valid for a week and neither the editor nor an admin
could do a thing about it -- "log out" only deleted the browser's copy. The
cookie is now a bearer token whose SERVER-SIDE record decides: logout revokes
it, "log out everywhere" revokes every one of a user's, and an admin can revoke
somebody else's from the Users page.

The row is keyed by a DERIVED id (auth.session_id_for = HMAC(secret, cookie))
rather than by an id embedded in the cookie, deliberately: the wire format of
the session cookie does not change, so every existing cookie, the identity
token, and all the format tests keep meaning exactly what they meant. The id is
a keyed digest, so the sessions table never holds anything that can be replayed
as a cookie -- reading the whole table gives an attacker no session.

The login throttle lives here too, for two reasons the in-process dict could
not give: it survives a container restart (a restart used to clear every
failure budget -- and the dashboard restarts on every deploy), and it has an
IP budget as well as a username one, so spraying one password across a hundred
usernames is bounded too.

Storage is the dashboard's own SQLite file, and every operation opens its own
short-lived connection -- the same thing api.get_conn does per request. A
long-lived shared connection would need a lock held across the event loop and
the collector thread; measured against ~2.5 opens/second at fleet scale, that
complexity buys nothing.
"""
from __future__ import annotations

import datetime as dt
import logging
import sqlite3
import threading
from pathlib import Path

from . import db

log = logging.getLogger("ccsync.dashboard.sessions")

# Lifetimes (seconds). Idle = time since the last request on this session;
# absolute = time since login, which no amount of activity extends. 12h idle
# means an editor who leaves the dashboard open over lunch stays signed in and
# one who leaves for the weekend does not; 7d absolute keeps the previous
# ceiling, so this change shortens sessions, never lengthens them.
DEFAULT_IDLE_SECONDS = 12 * 3600
DEFAULT_ABSOLUTE_SECONDS = 7 * 24 * 3600

# Sliding refresh writes last_seen at most this often. Without it every htmx
# poll (/partials/transfers every 2s, per open tab) would be a write to the
# single-writer SQLite file -- the collector is the only bulk writer here by
# design, and a session touch is not allowed to compete with it.
TOUCH_INTERVAL_SECONDS = 60.0

# Login throttle. Budgets are counted per username AND per client IP; whichever
# is exhausted first blocks. Backoff doubles per failure past the limit so a
# patient attacker gets minutes, not seconds, between guesses.
LOGIN_FAILURE_LIMIT = 5
# ...but the IP budget is deliberately MUCH larger than the username one
# (trust-model-3, 2026-08-21). One address here is very often one GATEWAY:
# the shipped TrueNAS shape publishes the dashboard through Tailscale Serve
# on the docker host, so every editor and every companion arrives from the
# bridge gateway (172.17.0.1) unless DASH_TRUSTED_PROXIES names it. At five,
# one editor with caps lock on put the WHOLE FLEET into exponential backoff:
# /login and /api/v1/verify 429 for everybody. The bucket still bounds a
# spray -- 40 wrong passwords from one address in an hour is not a fleet
# fat-fingering, and the per-username budget of 5 is untouched.
LOGIN_FAILURE_LIMIT_IP = 40
LOGIN_BACKOFF_BASE_SECONDS = 60.0
LOGIN_BACKOFF_MAX_SECONDS = 3600.0
# A failure older than this stops counting at all, so an editor who fat-fingers
# a password twice a month is never throttled.
LOGIN_FAILURE_WINDOW_SECONDS = 3600.0

SCOPE_USER = "user"
SCOPE_IP = "ip"

# Additive, idempotent DDL owned by the auth layer rather than a db.py
# migration step: these two tables are created with CREATE TABLE IF NOT EXISTS
# at boot and carry no data any other module reads, so they need no
# user_version bump and no replay logic.
SCHEMA = """
CREATE TABLE IF NOT EXISTS auth_sessions (
  sid        TEXT PRIMARY KEY,     -- HMAC(session_secret, cookie); never the cookie itself
  username   TEXT NOT NULL,
  created_at TEXT NOT NULL,
  last_seen  TEXT NOT NULL,
  client     TEXT NOT NULL DEFAULT '',  -- "<ip> <short user-agent>", for the admin view
  revoked    INTEGER NOT NULL DEFAULT 0,
  revoked_at TEXT,
  revoked_by TEXT
);
CREATE INDEX IF NOT EXISTS ix_auth_sessions_user ON auth_sessions(username);

CREATE TABLE IF NOT EXISTS login_attempts (
  scope         TEXT NOT NULL,     -- 'user' | 'ip'
  key           TEXT NOT NULL,
  failures      INTEGER NOT NULL DEFAULT 0,
  first_failure TEXT NOT NULL,
  last_failure  TEXT NOT NULL,
  blocked_until TEXT,
  PRIMARY KEY (scope, key)
);
"""

# Serialises this module's writes against each other. Two requests failing a
# login in the same instant used to read-modify-write the same counter dict
# with no lock at all; SQLite would serialise the statements but not the
# read-then-write pair, so a burst could undercount failures.
_write_lock = threading.Lock()

_UA_SUMMARY_CHARS = 80


def summarize_client(ip: str | None, user_agent: str | None) -> str:
    """A one-line "who is this" for the admin session list. Deliberately
    lossy: the full User-Agent is a fingerprint we have no use for, and the
    column is rendered into a page."""
    ua = (user_agent or "").strip().replace("\n", " ").replace("\r", " ")
    if len(ua) > _UA_SUMMARY_CHARS:
        ua = ua[:_UA_SUMMARY_CHARS] + "..."
    return f"{(ip or '?').strip()} {ua}".strip()


class SessionStore:
    """Every method is safe to call before the table exists (`ensure_schema`
    runs at boot, and again lazily on the first "no such table")."""

    def __init__(self, db_path: str | Path,
                 idle_seconds: float = DEFAULT_IDLE_SECONDS,
                 absolute_seconds: float = DEFAULT_ABSOLUTE_SECONDS) -> None:
        self.db_path = str(db_path)
        self.idle_seconds = float(idle_seconds)
        self.absolute_seconds = float(absolute_seconds)
        self._schema_ready = False

    # ------------------------------------------------------------- plumbing

    def _connect(self) -> sqlite3.Connection:
        return db.connect(self.db_path)

    def ensure_schema(self, conn: sqlite3.Connection | None = None) -> None:
        own = conn is None
        conn = self._connect() if own else conn
        try:
            conn.executescript(SCHEMA)
            conn.commit()
            self._schema_ready = True
        finally:
            if own:
                conn.close()

    def _run(self, fn, write: bool = False):
        """Open a connection, run `fn(conn)`, and self-heal the one failure
        that is expected in practice: a database whose auth tables have not
        been created yet (a fresh /data, or a test that built its own DB)."""
        for attempt in (0, 1):
            conn = self._connect()
            try:
                result = fn(conn)
                if write:
                    conn.commit()
                return result
            except sqlite3.OperationalError as exc:
                if attempt or "no such table" not in str(exc).lower():
                    raise
                conn.close()
                conn = None
                self.ensure_schema()
                continue
            finally:
                if conn is not None:
                    conn.close()
        return None

    # ------------------------------------------------------------- sessions

    def create(self, sid: str, username: str, client: str = "",
               now: str | None = None) -> None:
        now = now or db.utcnow_iso()

        def go(conn: sqlite3.Connection) -> None:
            conn.execute(
                "INSERT OR REPLACE INTO auth_sessions "
                "(sid, username, created_at, last_seen, client, revoked, revoked_at, revoked_by) "
                "VALUES (?,?,?,?,?,0,NULL,NULL)",
                (sid, username.lower(), now, now, client),
            )

        with _write_lock:
            self._run(go, write=True)

    def validate(self, sid: str, now: str | None = None) -> str | None:
        """The username this session belongs to, or None when it is unknown,
        revoked, idle-expired or past its absolute lifetime. Slides last_seen
        (at most once per TOUCH_INTERVAL_SECONDS) as a side effect."""
        now = now or db.utcnow_iso()

        def go(conn: sqlite3.Connection):
            return conn.execute(
                "SELECT username, created_at, last_seen, revoked FROM auth_sessions WHERE sid = ?",
                (sid,),
            ).fetchone()

        row = self._run(go)
        if row is None or row["revoked"]:
            return None
        try:
            idle = db.age_seconds(row["last_seen"], now)
            age = db.age_seconds(row["created_at"], now)
        except ValueError:
            return None
        if idle > self.idle_seconds or age > self.absolute_seconds:
            # Expired sessions are deleted rather than left to accumulate: the
            # row exists to be revocable, and an expired one is not.
            self.delete(sid)
            return None
        if idle >= TOUCH_INTERVAL_SECONDS:
            def touch(conn: sqlite3.Connection) -> None:
                conn.execute("UPDATE auth_sessions SET last_seen = ? WHERE sid = ?", (now, sid))

            with _write_lock:
                self._run(touch, write=True)
        return row["username"]

    def delete(self, sid: str) -> None:
        def go(conn: sqlite3.Connection) -> None:
            conn.execute("DELETE FROM auth_sessions WHERE sid = ?", (sid,))

        with _write_lock:
            self._run(go, write=True)

    def revoke(self, sid: str, by: str = "", now: str | None = None) -> int:
        now = now or db.utcnow_iso()

        def go(conn: sqlite3.Connection) -> int:
            cur = conn.execute(
                "UPDATE auth_sessions SET revoked = 1, revoked_at = ?, revoked_by = ? "
                "WHERE sid = ? AND revoked = 0",
                (now, by, sid),
            )
            return cur.rowcount

        with _write_lock:
            return int(self._run(go, write=True) or 0)

    def revoke_user(self, username: str, by: str = "", except_sid: str | None = None,
                    now: str | None = None) -> int:
        """Revoke every live session for `username`. `except_sid` is how "log
        out everywhere ELSE" keeps the tab the editor is looking at."""
        now = now or db.utcnow_iso()

        def go(conn: sqlite3.Connection) -> int:
            sql = ("UPDATE auth_sessions SET revoked = 1, revoked_at = ?, revoked_by = ? "
                   "WHERE username = ? AND revoked = 0")
            params: list = [now, by, username.lower()]
            if except_sid:
                sql += " AND sid <> ?"
                params.append(except_sid)
            return conn.execute(sql, params).rowcount

        with _write_lock:
            return int(self._run(go, write=True) or 0)

    def list_for_user(self, username: str) -> list[dict]:
        def go(conn: sqlite3.Connection):
            return conn.execute(
                "SELECT sid, username, created_at, last_seen, client FROM auth_sessions "
                "WHERE username = ? AND revoked = 0 ORDER BY last_seen DESC",
                (username.lower(),),
            ).fetchall()

        return [dict(r) for r in (self._run(go) or [])]

    def list_all(self, limit: int = 200) -> list[dict]:
        """Every live session, newest activity first -- the admin Users view.
        Capped: this renders into a page, and a fleet with a runaway client
        must not turn that page into a megabyte of table."""
        def go(conn: sqlite3.Connection):
            return conn.execute(
                "SELECT sid, username, created_at, last_seen, client FROM auth_sessions "
                "WHERE revoked = 0 ORDER BY last_seen DESC LIMIT ?",
                (int(limit),),
            ).fetchall()

        return [dict(r) for r in (self._run(go) or [])]

    def live_counts(self) -> dict[str, int]:
        """username -> live session count, for the admin Users page."""
        def go(conn: sqlite3.Connection):
            return conn.execute(
                "SELECT username, COUNT(*) AS n FROM auth_sessions "
                "WHERE revoked = 0 GROUP BY username",
            ).fetchall()

        return {r["username"]: int(r["n"]) for r in (self._run(go) or [])}

    def prune(self, now: str | None = None) -> int:
        """Drop rows no request can ever revive: past the absolute lifetime,
        or revoked long enough ago that nobody is going to audit them."""
        now = now or db.utcnow_iso()
        created_cutoff = _shift(now, -self.absolute_seconds)
        revoked_cutoff = _shift(now, -DEFAULT_ABSOLUTE_SECONDS)

        def go(conn: sqlite3.Connection) -> int:
            return conn.execute(
                "DELETE FROM auth_sessions WHERE created_at < ? "
                "OR (revoked = 1 AND revoked_at IS NOT NULL AND revoked_at < ?)",
                (created_cutoff, revoked_cutoff),
            ).rowcount

        with _write_lock:
            return int(self._run(go, write=True) or 0)

    # -------------------------------------------------------- login throttle

    def throttled(self, username: str, ip: str | None = None,
                  now: str | None = None) -> float:
        """Seconds the caller must wait, or 0.0 when the budget is clear.

        Both budgets are consulted; the longer wait wins. A username budget
        alone let an attacker spray one password across every username in the
        fleet from one host at full speed (COMMERCIAL_READINESS item 15)."""
        now = now or db.utcnow_iso()
        keys = [(SCOPE_USER, (username or "").lower())]
        if ip:
            keys.append((SCOPE_IP, ip))

        def go(conn: sqlite3.Connection):
            rows = []
            for scope, key in keys:
                row = conn.execute(
                    "SELECT blocked_until FROM login_attempts WHERE scope = ? AND key = ?",
                    (scope, key),
                ).fetchone()
                if row is not None:
                    rows.append(row["blocked_until"])
            return rows

        worst = 0.0
        for blocked_until in (self._run(go) or []):
            if not blocked_until:
                continue
            try:
                remaining = -db.age_seconds(blocked_until, now)
            except ValueError:
                continue
            worst = max(worst, remaining)
        return worst if worst > 0 else 0.0

    def record_failure(self, username: str, ip: str | None = None,
                       now: str | None = None) -> None:
        now = now or db.utcnow_iso()
        keys = [(SCOPE_USER, (username or "").lower())]
        if ip:
            keys.append((SCOPE_IP, ip))

        cutoff = _shift(now, -LOGIN_FAILURE_WINDOW_SECONDS)

        def go(conn: sqlite3.Connection) -> None:
            # Sweep here, not only at boot: a spray against random usernames
            # writes one row each, and the container can run for months. This
            # is the same "evict on every attempt" discipline the in-process
            # dict had (SEC-12), and it only runs on a FAILED login.
            conn.execute(
                "DELETE FROM login_attempts WHERE last_failure < ? "
                "AND (blocked_until IS NULL OR blocked_until < ?)", (cutoff, now))
            for scope, key in keys:
                row = conn.execute(
                    "SELECT failures, first_failure, last_failure FROM login_attempts "
                    "WHERE scope = ? AND key = ?", (scope, key)).fetchone()
                failures = 1
                first = now
                if row is not None:
                    try:
                        stale = db.age_seconds(row["last_failure"], now) > LOGIN_FAILURE_WINDOW_SECONDS
                    except ValueError:
                        stale = True
                    if not stale:
                        failures = int(row["failures"]) + 1
                        first = row["first_failure"]
                blocked_until = None
                limit = LOGIN_FAILURE_LIMIT_IP if scope == SCOPE_IP else LOGIN_FAILURE_LIMIT
                if failures >= limit:
                    delay = min(
                        LOGIN_BACKOFF_BASE_SECONDS * (2 ** (failures - limit)),
                        LOGIN_BACKOFF_MAX_SECONDS,
                    )
                    blocked_until = _shift(now, delay)
                conn.execute(
                    "INSERT OR REPLACE INTO login_attempts "
                    "(scope, key, failures, first_failure, last_failure, blocked_until) "
                    "VALUES (?,?,?,?,?,?)",
                    (scope, key, failures, first, now, blocked_until),
                )

        with _write_lock:
            self._run(go, write=True)

    def clear_failures(self, username: str, ip: str | None = None) -> None:
        keys = [(SCOPE_USER, (username or "").lower())]
        if ip:
            keys.append((SCOPE_IP, ip))

        def go(conn: sqlite3.Connection) -> None:
            for scope, key in keys:
                conn.execute("DELETE FROM login_attempts WHERE scope = ? AND key = ?",
                             (scope, key))

        with _write_lock:
            self._run(go, write=True)

    def prune_attempts(self, now: str | None = None) -> int:
        now = now or db.utcnow_iso()
        cutoff = _shift(now, -LOGIN_FAILURE_WINDOW_SECONDS)

        def go(conn: sqlite3.Connection) -> int:
            return conn.execute(
                "DELETE FROM login_attempts WHERE last_failure < ? "
                "AND (blocked_until IS NULL OR blocked_until < ?)",
                (cutoff, now),
            ).rowcount

        with _write_lock:
            return int(self._run(go, write=True) or 0)


def _shift(iso: str, seconds: float) -> str:
    return (db.parse_iso(iso) + dt.timedelta(seconds=seconds)).replace(
        microsecond=0).isoformat()
