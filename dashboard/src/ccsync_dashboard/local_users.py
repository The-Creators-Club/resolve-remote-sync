"""Local accounts: the dashboard's own identity provider (WP C, docs/
ZERO_TOUCH_PLAN.md §3.3, 2026-08-17).

The SMB probe (auth.py) exists only because editors *had* to be NAS
accounts; the appliance shape (docs/ZERO_TOUCH_PLAN.md §3.1/§3.3) has no NAS
credential by default at all, so DASH_AUTH_METHOD=local reads and writes the
`users` / `user_ssh_keys` tables here instead (db.py migration v17).

Password hashing is stdlib `hashlib.scrypt` -- NOT argon2/bcrypt/passlib.
Every component in this repo carries a hash-pinned `requirements.lock` and a
new dependency has to clear `tools/check_licenses.py` (CLAUDE.md); scrypt
needs neither, and Python's own docs recommend it for exactly this. The
encoded form is self-describing (`scrypt$n$r$p$salt_b64$hash_b64`) so the
cost parameters can be raised later without a migration -- a verify reads
them back out of the stored hash rather than assuming today's constants.

Functions here take a connection rather than opening their own: every caller
already has one (a FastAPI route's `Depends(get_conn)`, or a short-lived one
opened by auth.py for the handful of call sites -- login, is_admin -- that
run before a request has one). Nothing here commits; callers own the
transaction, same convention as the rest of db.py's write helpers.
"""
from __future__ import annotations

import base64
import hashlib
import hmac
import logging
import re
import secrets
import sqlite3
from typing import Any

from . import db
from .nas.base import looks_like_ssh_pubkey

log = logging.getLogger("ccsync.dashboard.local_users")

ROLES = ("admin", "editor")

# scrypt cost parameters (2026-08-17): N=2**15 (32768), r=8, p=1 is the
# "interactive login, 2020s hardware" point on the RFC 7914 curve -- roughly
# 64 MB of memory and low tens of milliseconds per hash on the appliance's
# own CPU, which is what this dashboard's single worker pays on every /login
# and every /api/v1/verify. Encoded into every hash (see _hash_password) so
# raising them later re-hashes only on next successful login, never a
# migration that touches a password nobody here can read.
SCRYPT_N = 2 ** 15
SCRYPT_R = 8
SCRYPT_P = 1
_SALT_BYTES = 32
_DKLEN = 32
# hashlib.scrypt needs 128*N*r*p bytes of working memory -- exactly 32 MiB at
# the constants above -- and OpenSSL's own default ceiling is exactly 32 MiB
# too, so the boundary itself raises "memory limit exceeded" (measured
# 2026-08-17, Windows/OpenSSL build). maxmem is passed explicitly, with
# headroom, so the cost parameters are never fighting a library default that
# happens to sit right on top of them.
_SCRYPT_MAXMEM = 64 * 1024 * 1024

# Mirrors db._USERNAME_RE / nas.base.USERNAME_RE exactly: a local account
# must be mappable the same way a NAS one is, because known_editors,
# selections and the fleet grid all key on this shape.
_USERNAME_RE = re.compile(r"^[a-z][a-z0-9._-]{0,31}$")


class LocalUserError(ValueError):
    """A local-account operation refused for a reason worth showing an
    admin verbatim (bad username, weak password, unknown account, duplicate
    key). Callers turn this into a 422/404, same convention as
    provision.ProjectSetupError."""


# --------------------------------------------------------------- hashing

def _hash_password(password: str) -> str:
    salt = secrets.token_bytes(_SALT_BYTES)
    derived = hashlib.scrypt(
        password.encode("utf-8"), salt=salt, n=SCRYPT_N, r=SCRYPT_R, p=SCRYPT_P, dklen=_DKLEN,
        maxmem=_SCRYPT_MAXMEM,
    )
    return "$".join((
        "scrypt", str(SCRYPT_N), str(SCRYPT_R), str(SCRYPT_P),
        base64.b64encode(salt).decode("ascii"),
        base64.b64encode(derived).decode("ascii"),
    ))


def _check_password_hash(password: str, encoded: str) -> bool:
    """Constant-time compare against a stored `scrypt$...` hash. Any
    malformed/foreign encoding is a refusal, never an exception -- a hand-
    edited or corrupted row must not 500 a login."""
    try:
        scheme, n_s, r_s, p_s, salt_b64, hash_b64 = (encoded or "").split("$")
        if scheme != "scrypt":
            return False
        n, r, p = int(n_s), int(r_s), int(p_s)
        salt = base64.b64decode(salt_b64)
        expected = base64.b64decode(hash_b64)
    except Exception:  # noqa: BLE001 - malformed stored hash, not our problem
        return False
    derived = hashlib.scrypt(
        password.encode("utf-8"), salt=salt, n=n, r=r, p=p, dklen=len(expected),
        maxmem=_SCRYPT_MAXMEM,
    )
    return hmac.compare_digest(derived, expected)


def _fingerprint(key_text: str) -> str:
    """SHA256 fingerprint in the `ssh-keygen -l` shape (base64, unpadded),
    computed over the key BLOB (the second whitespace-separated field), not
    the whole line -- so a trailing comment never changes the fingerprint an
    admin revokes by."""
    parts = key_text.strip().split()
    if len(parts) < 2:
        raise LocalUserError("does not look like an OpenSSH public key")
    try:
        blob = base64.b64decode(parts[1], validate=True)
    except Exception as exc:  # noqa: BLE001
        raise LocalUserError("does not look like an OpenSSH public key") from exc
    digest = hashlib.sha256(blob).digest()
    return "SHA256:" + base64.b64encode(digest).decode("ascii").rstrip("=")


# ----------------------------------------------------------------- reads

def any_users_exist(conn: sqlite3.Connection) -> bool:
    """Whether the first-admin bootstrap window (setup_api.setup_admin) is
    still open."""
    return conn.execute("SELECT 1 FROM users LIMIT 1").fetchone() is not None


def get_user(conn: sqlite3.Connection, username: str) -> dict[str, Any] | None:
    username = (username or "").strip().lower()
    row = conn.execute(
        "SELECT username, password_hash, role, created_at, disabled, must_change_password "
        "FROM users WHERE username = ?", (username,),
    ).fetchone()
    return dict(row) if row is not None else None


def keys_for(conn: sqlite3.Connection, username: str) -> list[dict[str, Any]]:
    username = (username or "").strip().lower()
    rows = conn.execute(
        "SELECT key_text, fingerprint, added_at, label FROM user_ssh_keys "
        "WHERE username = ? ORDER BY added_at", (username,),
    ).fetchall()
    return [dict(r) for r in rows]


def list_users(conn: sqlite3.Connection) -> list[dict[str, Any]]:
    """Every local account, with its SSH keys -- the shape the admin Users
    page and internal_sftp.py both read. password_hash is never included."""
    rows = conn.execute(
        "SELECT username, role, created_at, disabled, must_change_password "
        "FROM users ORDER BY username",
    ).fetchall()
    out: list[dict[str, Any]] = []
    for r in rows:
        d = dict(r)
        d["disabled"] = bool(d["disabled"])
        d["must_change_password"] = bool(d["must_change_password"])
        # "ssh_keys", not "keys": a plain dict handed to Jinja resolves
        # `u.keys` to the dict's OWN .keys() method before it ever tries
        # `u["keys"]`, so a field literally named "keys" silently returns a
        # bound method instead of the list (measured 2026-08-17, template
        # TypeError: 'builtin_function_or_method' object is not iterable).
        d["ssh_keys"] = keys_for(conn, d["username"])
        out.append(d)
    return out


def is_local_admin(conn: sqlite3.Connection, username: str) -> bool:
    """True when `username` is an ENABLED local account with role='admin'.
    A disabled admin is not an admin -- same as a disabled account not being
    able to sign in at all (see verify_password)."""
    user = get_user(conn, username)
    return bool(user) and not user["disabled"] and user["role"] == "admin"


# ---------------------------------------------------------------- writes

def create_user(conn: sqlite3.Connection, username: str, password: str, role: str, *,
                created_by: str = "", now: str | None = None) -> dict[str, Any]:
    """Create a local account. Raises LocalUserError for anything an admin
    (or the setup wizard) should see verbatim; never raises sqlite3.Error for
    an ordinary duplicate-username mistake."""
    from . import auth  # deferred: auth imports this module at load time

    username = (username or "").strip().lower()
    if not _USERNAME_RE.match(username):
        raise LocalUserError(
            "username must start with a letter and contain only lowercase letters, "
            "digits, '.', '_', '-'"
        )
    if role not in ROLES:
        raise LocalUserError(f"role must be one of {ROLES}")
    problem = auth.check_password(password)
    if problem:
        raise LocalUserError(problem)
    if get_user(conn, username) is not None:
        raise LocalUserError(f"{username!r} already exists")
    now = now or db.utcnow_iso()
    conn.execute(
        "INSERT INTO users (username, password_hash, role, created_at, disabled, "
        "must_change_password) VALUES (?, ?, ?, ?, 0, 0)",
        (username, _hash_password(password), role, now),
    )
    log.info("local user %r created as %s by %r", username, role, created_by or "?")
    return {"username": username, "role": role, "created_at": now}


def set_password(conn: sqlite3.Connection, username: str, password: str, *,
                 must_change: bool = False) -> None:
    from . import auth  # deferred, see create_user

    username = (username or "").strip().lower()
    if get_user(conn, username) is None:
        raise LocalUserError(f"{username!r} is not a local account")
    problem = auth.check_password(password)
    if problem:
        raise LocalUserError(problem)
    conn.execute(
        "UPDATE users SET password_hash = ?, must_change_password = ? WHERE username = ?",
        (_hash_password(password), 1 if must_change else 0, username),
    )


def verify_password(conn: sqlite3.Connection, username: str, password: str) -> bool:
    """Constant-time scrypt check. False for an unknown OR a disabled
    account -- the wire never distinguishes the two, same posture as the SMB
    probe (auth._verify_smb) it replaces."""
    if not username or not password:
        return False
    user = get_user(conn, username)
    if user is None or user["disabled"]:
        return False
    return _check_password_hash(password, user["password_hash"])


def disable_user(conn: sqlite3.Connection, username: str, disabled: bool = True) -> None:
    username = (username or "").strip().lower()
    if get_user(conn, username) is None:
        raise LocalUserError(f"{username!r} is not a local account")
    conn.execute("UPDATE users SET disabled = ? WHERE username = ?",
                (1 if disabled else 0, username))


def add_ssh_key(conn: sqlite3.Connection, username: str, key_text: str, *,
                label: str = "", now: str | None = None) -> dict[str, Any]:
    """The key the sftp sidecar's AuthorizedKeysCommand will hand back for
    this user (internal_sftp.py). Idempotent on (username, fingerprint) --
    re-adding the same key just refreshes its label/added_at."""
    username = (username or "").strip().lower()
    if get_user(conn, username) is None:
        raise LocalUserError(f"{username!r} is not a local account")
    key_text = (key_text or "").strip()
    if not looks_like_ssh_pubkey(key_text):
        raise LocalUserError("does not look like an OpenSSH public key")
    fingerprint = _fingerprint(key_text)
    now = now or db.utcnow_iso()
    conn.execute(
        "INSERT OR REPLACE INTO user_ssh_keys (username, key_text, fingerprint, added_at, label) "
        "VALUES (?, ?, ?, ?, ?)",
        (username, key_text, fingerprint, now, label or ""),
    )
    return {"fingerprint": fingerprint, "label": label or "", "added_at": now}


def remove_ssh_key(conn: sqlite3.Connection, username: str, fingerprint: str) -> bool:
    """True if a row was actually removed -- revoking a key that is already
    gone is not an error (an admin double-clicking, or two tabs open)."""
    username = (username or "").strip().lower()
    cur = conn.execute(
        "DELETE FROM user_ssh_keys WHERE username = ? AND fingerprint = ?",
        (username, (fingerprint or "").strip()),
    )
    return cur.rowcount > 0


def warn_missing_admin_users(conn: sqlite3.Connection, admin_users) -> None:
    """DASH_ADMIN_USERS is still honoured ADDITIVELY in local mode (break-
    glass: an operator locked out of every local account can still get in by
    naming themselves here) -- but a name that matches no local account is
    very likely a leftover from an smb-mode deployment or a typo, and
    granting it silently nothing is worse than saying so once at boot."""
    for name in sorted(u.strip().lower() for u in (admin_users or ()) if u.strip()):
        if get_user(conn, name) is None:
            log.warning(
                "DASH_ADMIN_USERS names %r, which has no local account -- it is a valid "
                "break-glass entry (grants admin the moment that account exists) but grants "
                "nothing today. Create the account, or drop it from DASH_ADMIN_USERS.",
                name,
            )
