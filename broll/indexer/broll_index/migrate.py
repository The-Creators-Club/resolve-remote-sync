"""`broll-index migrate` — apply pending schema migrations to an existing sqlite DB in place.

schema.sql at the repo root is a *fresh-install* script: SqliteBackend._ensure_schema runs
it in full (and sets PRAGMA user_version straight to the latest version) whenever it opens
a brand-new (user_version == 0) database — see storage/sqlite_backend.py. That path never
needs a migration step.

This module covers the other case: an existing v1 (or v2, v3, v4) database (created
before on-screen text, local transcription, hybrid search, and/or duplicate detection
existed — e.g. a real archive that has been indexing for a while) that needs bringing
forward to the latest version *without* losing its rows. That's exactly what
migrations/002_onscreen_text.sql, migrations/003_transcripts.sql,
migrations/004_hybrid_search.sql, and migrations/005_duplicates.sql do, applied in
order, and this module is what runs them.

Migration files are looked up at the repo root first (migrations/NNN_*.sql, the single
source of truth per SPEC.md), falling back to a bundled copy shipped inside this package
(broll_index/migrations/) for installs where the rest of the repo isn't checked out.
"""

from __future__ import annotations

import sqlite3
from pathlib import Path

LATEST_VERSION = 10

# from_version -> migration filename (looked up via _find_migration_file)
_MIGRATION_STEPS: dict[int, str] = {
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

# indexer/broll_index/migrate.py -> parents[1] == indexer/ -> parents[2] == repo root
_REPO_ROOT_MIGRATIONS_DIR = Path(__file__).resolve().parents[2] / "migrations"
_BUNDLED_MIGRATIONS_DIR = Path(__file__).resolve().parent / "migrations"


class MigrationError(RuntimeError):
    pass


def _find_migration_file(filename: str, migrations_dir: str | Path | None = None) -> Path:
    if migrations_dir is not None:
        explicit = Path(migrations_dir) / filename
        if explicit.exists():
            return explicit
        raise MigrationError(f"migration file {filename!r} not found at {explicit}")

    repo_path = _REPO_ROOT_MIGRATIONS_DIR / filename
    if repo_path.exists():
        return repo_path
    bundled_path = _BUNDLED_MIGRATIONS_DIR / filename
    if bundled_path.exists():
        return bundled_path
    raise MigrationError(
        f"migration file {filename!r} not found at repo root ({repo_path}) "
        f"or bundled fallback ({bundled_path})"
    )


def migrate_sqlite_db(db_path: str | Path, migrations_dir: str | Path | None = None) -> str:
    """Apply every pending migration to `db_path` in place. Returns a human-readable report.

    Idempotent: a no-op (report says so, nothing written) when PRAGMA user_version is
    already >= LATEST_VERSION. Each migration script runs inside its own transaction — the
    script text is wrapped in an explicit BEGIN/COMMIT so a mid-script failure (including
    the trailing `PRAGMA user_version = N`) rolls back cleanly and the DB is left exactly
    as it was, ready to retry.
    """
    conn = sqlite3.connect(str(db_path))
    try:
        version = conn.execute("PRAGMA user_version").fetchone()[0]

        if version >= LATEST_VERSION:
            return f"migrate: database already at user_version {version}, nothing to do"

        if version == 0:
            return (
                "migrate: database has no schema yet (user_version 0) — this isn't an "
                "existing database to upgrade in place. Run any broll-index command "
                "against it (e.g. `scan`) to initialize it fresh at the latest schema "
                "instead of `migrate`."
            )

        applied: list[str] = []
        while version < LATEST_VERSION:
            filename = _MIGRATION_STEPS.get(version)
            if filename is None:
                raise MigrationError(
                    f"no migration registered to advance user_version {version} -> "
                    f"{version + 1} (LATEST_VERSION={LATEST_VERSION})"
                )
            script_path = _find_migration_file(filename, migrations_dir)
            sql = script_path.read_text(encoding="utf-8")

            # Wrap the whole script in one transaction. conn.executescript() always
            # issues an implicit COMMIT for any *already-pending* transaction before it
            # runs — so we must NOT call conn.execute("BEGIN") separately first (that
            # would just get committed away); instead the BEGIN/COMMIT has to be part of
            # the text handed to executescript itself.
            wrapped = f"BEGIN;\n{sql}\nCOMMIT;\n"
            try:
                conn.executescript(wrapped)
            except Exception as e:
                conn.rollback()
                raise MigrationError(f"migration {filename} failed, rolled back: {e}") from e

            applied.append(filename)
            new_version = conn.execute("PRAGMA user_version").fetchone()[0]
            if new_version <= version:
                # The script ran but didn't advance the version — it is missing its
                # trailing `PRAGMA user_version = N`. Without this guard the loop would
                # pick the same file again and re-apply it; fail loudly instead.
                raise MigrationError(
                    f"{filename} ran but left user_version at {new_version} — it is "
                    f"missing a trailing `PRAGMA user_version = {version + 1};`"
                )
            version = new_version

        return f"migrate: applied {', '.join(applied)} (now at user_version {version})"
    finally:
        conn.close()
