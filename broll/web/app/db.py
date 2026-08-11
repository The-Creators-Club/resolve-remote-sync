"""SQLite connection management + stepped schema migrations.

Contract (SPEC.md "Database"): schema.sql at repo root is the single source
of truth, applied via PRAGMA user_version migrations (v0 -> v4 directly, or
stepped for an existing DB: v1 -> v2 via migrations/002_onscreen_text.sql,
v2 -> v3 via migrations/003_transcripts.sql, v3 -> v4 via
migrations/004_hybrid_search.sql), WAL mode.

Because this component may be deployed as a standalone Docker image that
only has the `web/` directory baked into it (no repo root available), we
also keep bundled copies at `web/schema.sql` and `web/migrations/`.
Resolution order for both the full schema and any individual migration file:

1. repo root (sibling of `web/`) -- the authoritative copy when running from
   a checkout of the whole repo (local dev, tests).
2. bundled copy under `web/` -- used in Docker/standalone deployments.

If neither is present we fail loudly at startup rather than silently
running with a missing schema/migration.

Migration steps (PRAGMA user_version):
    0 -> 4   apply schema.sql in full (a brand-new DB gets the current
             schema directly; schema.sql itself sets user_version = 4).
    1 -> 2   apply migrations/002_onscreen_text.sql (adds on-screen text
             columns + the dual-tokenizer FTS tables to an existing v1 DB)
    2 -> 3   apply migrations/003_transcripts.sql (adds transcript_segments
             + its own dual-tokenizer FTS, for locally-transcribed speech)
    3 -> 4   apply migrations/004_hybrid_search.sql (adds search_norm
             columns -- word-segmented, script-normalized CJK text, see the
             migration's own header -- and the `embeddings` table for
             semantic search). Column-for-column equivalent to what a fresh
             v0 -> v4 schema.sql application produces, so both paths land on
             an identical schema.
    4 -> 9   duplicates, share roots, archive/original path, sprite geometry
             -- one file each, see _MIGRATIONS below
    9 -> 10  apply migrations/010_search_generation.sql (adds the `meta`
             key/value table seeded with `search_generation`, the counter the
             semantic/fuzzy caches key on -- see bump_search_generation below)
    10 -> 10 no-op, already current

A DB is stepped through every migration in this chain in one ensure_schema()
call regardless of its starting version -- e.g. a real v1 production DB goes
straight to v4 on next startup. Anything above the highest version this code
knows about is a hard failure (e.g. a DB migrated by a newer version of this
app) rather than silently limping along.
"""
from __future__ import annotations

import sqlite3
from collections.abc import Iterator
from pathlib import Path

from app import config

# Highest schema version this codebase knows how to run against.
CURRENT_SCHEMA_VERSION = 10

# Maps "user_version found" -> migration filename that advances it to the
# next version. Resolved via find_migration_path() (repo-root-first, then
# bundled).
#
# This MUST be kept in step with the repo-root schema.sql and with the
# indexer's broll_index/migrate.py — all three describe the same database. A
# fresh install runs schema.sql (which lands straight on the latest version)
# while an existing database walks this chain, so a version added in one place
# and not the other produces a startup failure on exactly one of those two
# paths. That has happened once already.
_MIGRATIONS: dict[int, str] = {
    1: "002_onscreen_text.sql",
    2: "003_transcripts.sql",
    3: "004_hybrid_search.sql",
    4: "005_duplicates.sql",
    5: "006_share_roots.sql",
    6: "007_archive_path.sql",
    7: "008_original_path.sql",
    8: "009_sprite_geometry.sql",
    9: "010_search_generation.sql",
}

# The `meta` key holding the search-cache generation counter (migration 010).
SEARCH_GENERATION_KEY = "search_generation"

# Upsert-and-increment. The ON CONFLICT arm is the normal path; the INSERT arm
# only fires on a DB whose seed row went missing, and starts it at 1 rather than
# leaving the caches with nothing to notice.
_BUMP_SEARCH_GENERATION_SQL = (
    "INSERT INTO meta (key, value) VALUES (?, '1') "
    "ON CONFLICT(key) DO UPDATE SET value = CAST(CAST(meta.value AS INTEGER) + 1 AS TEXT)"
)


def bump_search_generation(conn: sqlite3.Connection) -> None:
    """Mark the semantic/fuzzy caches stale. MUST be executed inside the same
    transaction as the write that made them stale -- a bump that commits
    separately can be seen by a reader that has not yet seen the rows (or,
    worse, rolled back while the rows survived).

    Every path that inserts/replaces/deletes `embeddings`, or the
    segments/transcript_segments rows the fuzzy vocabulary is built from, calls
    this: routes_ingest here, and the indexer's sqlite_backend twin. It is
    deliberately loud (no try/except) -- a silently skipped bump is exactly the
    staleness this exists to end (KNOWN_BUGS R2, the BROLL-17 residual).
    """
    conn.execute(_BUMP_SEARCH_GENERATION_SQL, (SEARCH_GENERATION_KEY,))


def read_search_generation(conn: sqlite3.Connection) -> int:
    """Current counter value, 0 if it cannot be read.

    Read-side only, and deliberately the mirror image of the write side: this
    is called from app.semantic/app.fuzzy on the query path, which must never
    500 (see their module docstrings), so a DB predating migration 010 or a
    non-integer value degrades to "generation 0" -- the count/high-water
    components of those cache keys still work on their own, exactly as they did
    before this counter existed.
    """
    try:
        row = conn.execute(
            "SELECT value FROM meta WHERE key = ?", (SEARCH_GENERATION_KEY,)
        ).fetchone()
    except sqlite3.Error:
        return 0
    if row is None:
        return 0
    try:
        return int(row[0])
    except (TypeError, ValueError):
        return 0


def find_schema_path() -> Path:
    repo_root_candidate = config.WEB_DIR.parent / "schema.sql"
    bundled_candidate = config.WEB_DIR / "schema.sql"
    if repo_root_candidate.exists():
        return repo_root_candidate
    if bundled_candidate.exists():
        return bundled_candidate
    raise RuntimeError(
        "FATAL: schema.sql not found. Looked at repo root "
        f"({repo_root_candidate}) and bundled copy ({bundled_candidate}). "
        "The web app cannot initialize its database without the schema. "
        "If deploying web/ standalone (e.g. Docker), make sure web/schema.sql "
        "is present in the image."
    )


def find_migration_path(filename: str) -> Path:
    repo_root_candidate = config.WEB_DIR.parent / "migrations" / filename
    bundled_candidate = config.WEB_DIR / "migrations" / filename
    if repo_root_candidate.exists():
        return repo_root_candidate
    if bundled_candidate.exists():
        return bundled_candidate
    raise RuntimeError(
        f"FATAL: migration {filename!r} not found. Looked at repo root "
        f"({repo_root_candidate}) and bundled copy ({bundled_candidate}). "
        "The web app cannot migrate its database without this file. "
        "If deploying web/ standalone (e.g. Docker), make sure "
        "web/migrations/ is present in the image."
    )


def _apply_full_schema(conn: sqlite3.Connection) -> None:
    """v0 -> current: a brand-new/empty DB, so there is nothing to roll back
    to -- run it exactly like the original single-shot schema application.
    Not wrapped in an explicit transaction because schema.sql opens with
    `PRAGMA journal_mode = WAL`, which SQLite refuses to run inside one.
    """
    schema_path = find_schema_path()
    schema_sql = schema_path.read_text(encoding="utf-8")
    conn.executescript(schema_sql)


def _apply_migration(conn: sqlite3.Connection, filename: str) -> None:
    """Apply one stepped migration file inside an explicit transaction.

    Unlike the v0 full-schema case, these migrations run against a DB that
    may already hold real data (segments, videos, etc.), so a failure
    partway through (e.g. an ALTER TABLE that can't apply) must not leave
    the schema half-migrated. We wrap the whole script in BEGIN/COMMIT
    ourselves (executescript() does not do this for us -- it commits any
    pending transaction *before* running, then executes each statement
    largely as its own auto-committed unit unless the script itself
    contains explicit BEGIN/COMMIT), and roll back on any error.
    """
    migration_path = find_migration_path(filename)
    migration_sql = migration_path.read_text(encoding="utf-8")
    try:
        conn.executescript("BEGIN;\n" + migration_sql + "\nCOMMIT;\n")
    except Exception:
        conn.rollback()
        raise


def ensure_schema(db_path: Path | None = None) -> None:
    """Open (creating if needed) the DB at db_path and step it up to
    CURRENT_SCHEMA_VERSION via PRAGMA user_version. Safe to call repeatedly
    (no-op once current). Fails loudly if the DB is newer than this code
    knows how to handle.
    """
    path = db_path or config.get_db_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(path)
    try:
        conn.execute("PRAGMA journal_mode = WAL")
        version = conn.execute("PRAGMA user_version").fetchone()[0]

        if version == 0:
            _apply_full_schema(conn)
            version = conn.execute("PRAGMA user_version").fetchone()[0]

        while version in _MIGRATIONS:
            _apply_migration(conn, _MIGRATIONS[version])
            new_version = conn.execute("PRAGMA user_version").fetchone()[0]
            if new_version <= version:
                raise RuntimeError(
                    f"FATAL: migration for user_version={version} did not "
                    f"advance the schema version (still {new_version}) -- "
                    "refusing to loop forever."
                )
            version = new_version

        if version > CURRENT_SCHEMA_VERSION:
            raise RuntimeError(
                f"FATAL: database at {path} has user_version={version}, "
                f"newer than this app supports (max {CURRENT_SCHEMA_VERSION}). "
                "Refusing to run against a DB migrated by a newer version of "
                "this app -- upgrade the web app before pointing it at this DB."
            )
    finally:
        conn.close()


def open_connection(db_path: Path | None = None) -> sqlite3.Connection:
    """Open a fresh connection to the DB for a single request/operation.

    Assumes ensure_schema() has already been called for this db_path.
    """
    path = db_path or config.get_db_path()
    conn = sqlite3.connect(path, check_same_thread=False)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    return conn


def get_db() -> Iterator[sqlite3.Connection]:
    """FastAPI dependency yielding a per-request connection."""
    conn = open_connection()
    try:
        yield conn
    finally:
        conn.close()
