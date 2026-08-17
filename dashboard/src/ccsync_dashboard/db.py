"""SQLite layer: connection, migration, writes, retention, and read queries.

Concurrency model (do not change casually): WAL mode, busy_timeout, a single
uvicorn worker, and the collector thread as the only bulk writer. Web requests
do reads plus the single-row report upsert. Every thread opens its own
connection.

All timestamps are ISO 8601 UTC strings; the fixed format makes lexicographic
comparison correct in SQL and in Python.
"""
from __future__ import annotations

import datetime as dt
import hashlib
import hmac
import json
import re
import secrets
import sqlite3
from pathlib import Path
from typing import Any, Container, Iterable, Mapping

SCHEMA_PATH = Path(__file__).with_name("schema.sql")

# Caps + retention for the media-presence tables.
EDITOR_MEDIA_CAP = 2000          # per-file disk-manifest rows per (editor, machine, project)
MEDIA_TREE_CAP = 4000            # Resolve-bin clip rows per (editor, machine, project)
MEDIA_REPORT_MAX_AGE_DAYS = 14   # drop an editor's media rows after it stops reporting
ACTIVE_TRANSFER_STALE_SECONDS = 120  # a transfer row is "live" only this long past updated_at

# v5: media presence + live transfers. The NAS filesystem walk (nas_media) is
# the authoritative "what exists"; editors report their own disk manifest,
# their Resolve bin tree (per-clip online/offline), and their live per-file
# transfers. Additive only.
SCHEMA_V5 = """
CREATE TABLE IF NOT EXISTS nas_media (
  project_id   INTEGER NOT NULL REFERENCES projects(id),
  rel_path     TEXT    NOT NULL,           -- posix, relative to the project dir
  kind         TEXT    NOT NULL,           -- 'original' | 'proxy'
  ext          TEXT    NOT NULL,
  size         INTEGER,
  mtime_ns     INTEGER,
  refreshed_at TEXT    NOT NULL,
  PRIMARY KEY (project_id, rel_path)
);
CREATE INDEX IF NOT EXISTS ix_nas_media_kind ON nas_media(project_id, kind);

CREATE TABLE IF NOT EXISTS nas_inventory_state (
  project_id      INTEGER PRIMARY KEY REFERENCES projects(id),
  tree_sig        TEXT,                     -- hash of dir (relpath, mtime_ns): skip walk when unchanged
  n_dirs          INTEGER,
  n_originals     INTEGER NOT NULL DEFAULT 0,
  bytes_originals INTEGER NOT NULL DEFAULT 0,
  n_proxies       INTEGER NOT NULL DEFAULT 0,
  bytes_proxies   INTEGER NOT NULL DEFAULT 0,
  walked_at       TEXT,
  last_error      TEXT
);

CREATE TABLE IF NOT EXISTS editor_media_project (
  editor_username TEXT NOT NULL,
  machine         TEXT NOT NULL,
  project_slug    TEXT NOT NULL,
  mode            TEXT NOT NULL DEFAULT 'editor',  -- 'base' | 'editor'
  n_originals     INTEGER NOT NULL DEFAULT 0,
  bytes_originals INTEGER NOT NULL DEFAULT 0,
  n_proxies       INTEGER NOT NULL DEFAULT 0,
  bytes_proxies   INTEGER NOT NULL DEFAULT 0,
  truncated       INTEGER NOT NULL DEFAULT 0,
  reported_at     TEXT NOT NULL,
  PRIMARY KEY (editor_username, machine, project_slug)
);

CREATE TABLE IF NOT EXISTS editor_media (
  editor_username TEXT NOT NULL,
  machine         TEXT NOT NULL,
  project_slug    TEXT NOT NULL,
  rel_path        TEXT NOT NULL,
  kind            TEXT NOT NULL,           -- 'original' | 'proxy'
  size            INTEGER,
  refreshed_at    TEXT NOT NULL,
  PRIMARY KEY (editor_username, machine, project_slug, rel_path)
);

CREATE TABLE IF NOT EXISTS media_tree_clips (
  editor_username TEXT NOT NULL,
  machine         TEXT NOT NULL,
  project_slug    TEXT NOT NULL,
  bin_path        TEXT NOT NULL,           -- '' = root bin
  clip_name       TEXT NOT NULL,
  file_path       TEXT,
  kind            TEXT,                    -- 'original' | 'proxy' | 'other'
  present         INTEGER NOT NULL DEFAULT 0,
  refreshed_at    TEXT NOT NULL,
  PRIMARY KEY (editor_username, machine, project_slug, bin_path, clip_name)
);

CREATE TABLE IF NOT EXISTS active_transfers (
  editor_username TEXT NOT NULL,
  machine         TEXT NOT NULL,
  lane            TEXT NOT NULL,
  name            TEXT NOT NULL,
  direction       TEXT NOT NULL,           -- 'up' | 'down'
  bytes_done      INTEGER,
  bytes_total     INTEGER,
  percentage      REAL,
  speed_bps       REAL,
  eta_seconds     REAL,
  project_slug    TEXT,
  updated_at      TEXT NOT NULL,           -- server clock; drives liveness
  PRIMARY KEY (editor_username, machine, lane, name)
);
CREATE INDEX IF NOT EXISTS ix_active_transfers_fresh ON active_transfers(updated_at);
"""

# v4: sticky per-Resolve-project destination roots. The FIRST auto-detection
# (Resolve project name matched to a tree project) is stored and becomes
# canonical; it never changes automatically -- only an admin edit changes it.
SCHEMA_V4 = """
CREATE TABLE IF NOT EXISTS project_roots (
  resolve_project TEXT PRIMARY KEY COLLATE NOCASE,  -- Resolve project name, trimmed
  project_slug    TEXT NOT NULL,                    -- tree project slug
  source          TEXT NOT NULL,                    -- 'auto' | 'admin'
  updated_at      TEXT NOT NULL,
  updated_by      TEXT NOT NULL                     -- 'auto' or admin username
);
ALTER TABLE machine_state ADD COLUMN resolve_project TEXT;
"""

# v6: companion machine-identity verification. `verified` = 1 when the
# companion presented a valid identity token (X-CCSync-Identity) whose
# username matched the reported editor_name.
SCHEMA_V6 = """
ALTER TABLE machine_state ADD COLUMN verified INTEGER NOT NULL DEFAULT 0;
"""

# v7: dashboard-hosted companion upgrade channel. One row per published
# build; the actual exe lives under Settings.packages_path()/<platform>/.
# is_current is a column (not a `meta` pointer) so "flip current" is a
# two-statement transaction and a deleted row can never leave a dangling
# pointer. platform is 'windows' today; the column exists so macOS can be
# added without a migration.
SCHEMA_V7 = """
CREATE TABLE IF NOT EXISTS companion_packages (
  id           INTEGER PRIMARY KEY AUTOINCREMENT,
  version      TEXT    NOT NULL,
  platform     TEXT    NOT NULL DEFAULT 'windows',
  filename     TEXT    NOT NULL,
  sha256       TEXT    NOT NULL,
  size_bytes   INTEGER NOT NULL,
  published_at TEXT    NOT NULL,
  published_by TEXT    NOT NULL,
  is_current   INTEGER NOT NULL DEFAULT 0,
  UNIQUE (platform, version)
);
"""

# v8: per-machine reported platform, so the fleet grid's "out of date" flag
# (build_editors_view) can compare a machine's companion_version against the
# CURRENT PACKAGE FOR THAT MACHINE'S PLATFORM instead of always "windows"
# (see X-5) -- a macOS companion must never be compared against the Windows
# release.
SCHEMA_V8 = """
ALTER TABLE machine_state ADD COLUMN platform TEXT;
"""

# v9: Syncthing's own folder health, per project. db_status already returned
# `state`/`error` on every completion cycle and the collector threw them away,
# so a folder that had STOPPED syncing ("folder marker missing" after a move)
# showed a stale-but-plausible completion % forever.
SCHEMA_V9 = """
ALTER TABLE projects ADD COLUMN folder_state TEXT;
ALTER TABLE projects ADD COLUMN folder_error TEXT;
ALTER TABLE projects ADD COLUMN folder_state_at TEXT;
"""

# v10: per-machine companion version in machine_state. lane_report_current
# already carried companion_version, but it is pruned after 30 silent days
# and is keyed per LANE -- machine_state is the one row per (editor, machine)
# that the fleet view wants for "which build is this box running", and it
# survives a lane-row prune. Optional: reports from companions that predate
# the field leave it NULL and the view shows "?" rather than lying.
SCHEMA_V10 = """
ALTER TABLE machine_state ADD COLUMN companion_version TEXT;
"""

# v11: package `kind` -- the upgrade channel now also hosts the onboarding
# installer (onboard.exe / the macOS bootstrap), which the dashboard's
# [ INSTALLER ] download serves. kind='companion' rows are what the fleet
# self-upgrades to (see api._upgrade_info); kind='onboard' rows are the
# full clean-install package a human downloads. The two are versioned
# independently (companion VERSION vs INSTALLER_VERSION), so the UNIQUE
# constraint must include kind -- which SQLite can only change by rebuild.
SCHEMA_V11 = """
CREATE TABLE companion_packages_v11 (
  id           INTEGER PRIMARY KEY AUTOINCREMENT,
  kind         TEXT    NOT NULL DEFAULT 'companion',
  version      TEXT    NOT NULL,
  platform     TEXT    NOT NULL DEFAULT 'windows',
  filename     TEXT    NOT NULL,
  sha256       TEXT    NOT NULL,
  size_bytes   INTEGER NOT NULL,
  published_at TEXT    NOT NULL,
  published_by TEXT    NOT NULL,
  is_current   INTEGER NOT NULL DEFAULT 0,
  UNIQUE (kind, platform, version)
);
INSERT INTO companion_packages_v11
  (id, kind, version, platform, filename, sha256, size_bytes, published_at, published_by, is_current)
  SELECT id, 'companion', version, platform, filename, sha256, size_bytes, published_at, published_by, is_current
  FROM companion_packages;
DROP TABLE companion_packages;
ALTER TABLE companion_packages_v11 RENAME TO companion_packages;
"""

# v12: transfer history + the server's own lane C need. transfer_history is
# the per-file completion feed the companions report (rclone Copied/Moved
# records); bounded by prune. projects.need_* is the NAS Syncthing folder's
# OWN needTotalItems/needBytes -- i.e. what editors are pushing TO the
# server, which no view could show before (a 400 MB mp3 uploading via lane
# C looked like "nothing happening", 2026-07-26).
SCHEMA_V12 = """
CREATE TABLE IF NOT EXISTS transfer_history (
  id              INTEGER PRIMARY KEY AUTOINCREMENT,
  editor_username TEXT NOT NULL,
  machine         TEXT NOT NULL,
  lane            TEXT NOT NULL,
  name            TEXT NOT NULL,
  direction       TEXT NOT NULL,
  completed_at    TEXT NOT NULL,
  received_at     TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS ix_transfer_history_at ON transfer_history(completed_at);
ALTER TABLE projects ADD COLUMN need_items INTEGER;
ALTER TABLE projects ADD COLUMN need_bytes INTEGER;
"""

# v13: two things nothing on the server could see.
#
# (a) transport_health -- the companion has computed and SENT this every heavy
#     tick since 0.4.x and ReportIn dropped it silently (KNOWN_BUGS B17), so
#     "this editor's lane C is riding the public relay pool at 1-5 MB/s" and
#     "this editor is just slow" looked identical on the fleet grid. Flattened
#     into machine_state rather than stored as a JSON blob: the grid needs to
#     sort/flag on these, and the raw structure is a diagnostic, not a record.
#     Same for the orphaned-.partial and express-lane failure counters, which
#     the companion documents as existing ONLY to give the server visibility.
#
# (b) known_editors -- an append-only record of usernames the dashboard has
#     CONFIRMED are editor accounts. resolve_editor_username() treats any
#     username-SHAPED Syncthing device name as an editor, so a device approved
#     as "editor-laptop" resolved to an editor with no selections rows and the
#     enforce cycle unshared it from every folder it was on (KNOWN_BUGS B16).
#     A name that is merely username-shaped is now treated as UNMAPPED (and
#     therefore left alone) until it appears here.
SCHEMA_V13 = """
ALTER TABLE machine_state ADD COLUMN transport_relayed INTEGER;
ALTER TABLE machine_state ADD COLUMN transport_direct INTEGER;
ALTER TABLE machine_state ADD COLUMN orphan_partials INTEGER;
ALTER TABLE machine_state ADD COLUMN orphan_partial_bytes INTEGER;
ALTER TABLE machine_state ADD COLUMN express_dropped INTEGER;
ALTER TABLE machine_state ADD COLUMN express_last_error TEXT;
ALTER TABLE machine_state ADD COLUMN transport_at TEXT;
CREATE TABLE IF NOT EXISTS known_editors (
  editor_username TEXT PRIMARY KEY,
  first_seen      TEXT NOT NULL,
  source          TEXT NOT NULL    -- 'report' | 'seed' | 'selection' | 'admin'
);
"""

# v16: the companion's SAFETY LATCHES, flattened onto machine_state
# (COMMERCIAL_READINESS.md item 9, 2026-08-17).
#
# A machine whose lane B circuit breaker has tripped looks EXACTLY like a
# healthy quiet one on the fleet grid -- lane B idle, no error, green -- and
# the same is true of one an editor has halted. Those are the two states an
# admin most needs to see and the two the grid could not show, so they get
# columns rather than a JSON blob: the grid sorts and alarms on them.
#
# Same shape as v13's transport columns and for the same reason (they are a
# CURRENT STATE per machine, not a history), including the COALESCE-on-update
# rule in upsert_machine_state -- except `breaker_tripped` and `halt_active`,
# which are sent on EVERY tick and must be able to go back to 0.
SCHEMA_V16 = """
ALTER TABLE machine_state ADD COLUMN breaker_tripped INTEGER;
ALTER TABLE machine_state ADD COLUMN breaker_reason TEXT;
ALTER TABLE machine_state ADD COLUMN breaker_at TEXT;
ALTER TABLE machine_state ADD COLUMN trash_bytes INTEGER;
ALTER TABLE machine_state ADD COLUMN trash_count INTEGER;
ALTER TABLE machine_state ADD COLUMN halt_active INTEGER;
ALTER TABLE machine_state ADD COLUMN halt_scope TEXT;
ALTER TABLE machine_state ADD COLUMN halt_reason TEXT;
ALTER TABLE machine_state ADD COLUMN skipped_exists INTEGER;
ALTER TABLE machine_state ADD COLUMN guard_at TEXT;
"""

# v18: the site manifest as DATA, and the SetupEngine's task state
# (ZERO_TOUCH_PLAN.md WP D, 2026-08-17). Owned by this work package only --
# v17 and v19 are other agents' migrations, added in their own worktrees; do
# not renumber this one to close the gap.
#
# site_settings is a plain key/value table (see site_store.py for the key
# list, validation and the DB-over-env precedence rule): GET /api/v1/site
# prefers a row here over the DASH_SITE_* environment variable it used to
# publish unconditionally, which is what lets the wizard's "Your studio"
# step (§3.5) and the Settings page write the manifest instead of requiring
# a container --recreate.
#
# setup_tasks is the wizard's own state: one row per SetupEngine task
# (`setup_engine.py`), so "which steps are done" survives a container
# restart mid-wizard exactly like a migration step does (see migrate()'s own
# resumability, above) -- a customer who closes the tab halfway through is
# not sent back to "Welcome".
SCHEMA_V18 = """
CREATE TABLE IF NOT EXISTS site_settings (
  key        TEXT PRIMARY KEY,
  value      TEXT NOT NULL,
  updated_at TEXT NOT NULL,
  updated_by TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS setup_tasks (
  id         TEXT PRIMARY KEY,
  status     TEXT NOT NULL DEFAULT 'todo',
  detail     TEXT NOT NULL DEFAULT '',
  at         TEXT,
  skipped    INTEGER NOT NULL DEFAULT 0
);
"""

# v14: the signed upgrade channel (COMMERCIAL_READINESS.md item 4,
# 2026-08-17). Every published package now carries an offline Ed25519
# signature over its whole record; the dashboard stores it and serves it
# alongside the fields it already served, and companions verify it BEFORE
# downloading anything. Additive and nullable on purpose -- rows published
# before this migration keep working for the [ INSTALLER ] download and stay
# visibly unsigned in the admin view instead of vanishing.
#
#   signature     base64 of the 64-byte Ed25519 signature
#   pubkey_id     which release key signed it (rotation/logging only)
#   min_version   the downgrade floor this release asserts
#   signed_binary whether the ARTIFACT carries Authenticode / Developer ID
#                 (distinct from the record signature above)
SCHEMA_V14 = """
ALTER TABLE companion_packages ADD COLUMN signature TEXT;
ALTER TABLE companion_packages ADD COLUMN pubkey_id TEXT;
ALTER TABLE companion_packages ADD COLUMN min_version TEXT;
ALTER TABLE companion_packages ADD COLUMN signed_binary INTEGER;
"""

# v15: per-editor report tokens (COMMERCIAL_READINESS.md item 15, 2026-08-17).
# Until now every companion in the fleet authenticated with ONE shared
# DASH_REPORT_TOKEN: it cannot be revoked for a single editor, a leaving
# contractor keeps it, and a leak means rotating every machine at once.
#
# The secret is stored HASHED (sha256 of the secret half) and shown to the
# admin exactly once, like an API key anywhere else -- the dashboard must not
# be a place a stolen backup yields working fleet credentials. `token_id` is
# the public half carried in the token string, so verification is one indexed
# lookup rather than a hash of every row.
#
# `report_auth` is the migration telemetry the shared token needs: one row per
# machine recording which credential its LAST report used, so an operator can
# see when the fleet has finished moving and it is safe to set
# DASH_SHARED_REPORT_TOKEN_ENABLED=0. Deliberately its own table rather than a
# column on machine_state -- it is a transitional fact with a shorter life than
# the fleet grid.
SCHEMA_V15 = """
CREATE TABLE IF NOT EXISTS editor_report_tokens (
  token_id        TEXT PRIMARY KEY,       -- public half, appears in the token
  editor_username TEXT NOT NULL,
  token_hash      TEXT NOT NULL,          -- sha256 hex of the secret half
  label           TEXT NOT NULL DEFAULT '',
  created_at      TEXT NOT NULL,
  created_by      TEXT NOT NULL,
  last_used_at    TEXT,
  revoked_at      TEXT,
  revoked_by      TEXT
);
CREATE INDEX IF NOT EXISTS ix_editor_report_tokens_editor
  ON editor_report_tokens(editor_username);
CREATE TABLE IF NOT EXISTS report_auth (
  editor_username TEXT NOT NULL,
  machine         TEXT NOT NULL,
  auth_kind       TEXT NOT NULL,          -- 'shared' | 'editor'
  at              TEXT NOT NULL,
  PRIMARY KEY (editor_username, machine)
);
"""

# v3: fix-destination project-root visibility/override. The companion
# auto-detects which project the editor is working in (Resolve project name
# matched against the tree) and reports it; an editor/admin can override it
# here when the auto-match is wrong.
SCHEMA_V3 = """
CREATE TABLE IF NOT EXISTS editor_prefs (
  editor_username       TEXT PRIMARY KEY,
  project_root_override TEXT,            -- project slug, NULL = auto
  updated_at            TEXT NOT NULL,
  updated_by            TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS machine_state (
  editor_username       TEXT NOT NULL,
  machine               TEXT NOT NULL,
  detected_project_root TEXT,            -- slug the companion auto-detected, NULL = none
  reported_at           TEXT NOT NULL,
  PRIMARY KEY (editor_username, machine)
);
"""

# v2: per-editor project selections + progress columns. Additive only --
# applied on top of live v1 databases.
SCHEMA_V2 = """
CREATE TABLE IF NOT EXISTS selections (
  editor_username TEXT NOT NULL,
  project_slug    TEXT NOT NULL,
  position        INTEGER NOT NULL,     -- per-editor monotonic tick counter = sync order
  created_at      TEXT NOT NULL,
  created_by      TEXT NOT NULL,        -- username who ticked, or 'seed'
  PRIMARY KEY (editor_username, project_slug)
);
CREATE TABLE IF NOT EXISTS meta (key TEXT PRIMARY KEY, value TEXT NOT NULL);
ALTER TABLE completion_current  ADD COLUMN rate_bytes_per_sec REAL;
ALTER TABLE lane_report_current ADD COLUMN current_project TEXT;
ALTER TABLE lane_report_current ADD COLUMN bytes_done INTEGER;
ALTER TABLE lane_report_current ADD COLUMN bytes_total INTEGER;
ALTER TABLE lane_report_current ADD COLUMN speed_bps REAL;
ALTER TABLE lane_report_current ADD COLUMN eta_seconds REAL;
"""

# v17: local accounts, the dashboard-native identity provider (WP C,
# docs/ZERO_TOUCH_PLAN.md §3.3, 2026-08-17). DASH_AUTH_METHOD=local reads and
# writes these two tables through local_users.py instead of probing a NAS's
# SMB service -- the appliance shape has no NAS credential by default at all.
#
#   users          one row per local account. password_hash is a stdlib
#                  hashlib.scrypt digest in the self-describing
#                  "scrypt$n$r$p$salt_b64$hash_b64" shape, never argon2/bcrypt
#                  -- a new dependency would need a requirements.lock bump and
#                  a tools/check_licenses.py pass this migration does not need
#                  to wait on. `role` gates auth.is_admin the same way
#                  DASH_ADMIN_USERS always has; `must_change_password` is
#                  read (not yet enforced anywhere) so a one-time generated
#                  password can be flagged for a future forced-reset prompt.
#   user_ssh_keys  the pubkeys the sftp sidecar's AuthorizedKeysCommand
#                  serves (internal_sftp.py). A user may hold more than one
#                  key (a laptop and a desktop); fingerprint is the primary
#                  handle an admin revokes by, so it is part of the key.
SCHEMA_V17 = """
CREATE TABLE IF NOT EXISTS users (
  username              TEXT PRIMARY KEY,
  password_hash         TEXT NOT NULL,
  role                  TEXT NOT NULL CHECK(role IN ('admin','editor')),
  created_at            TEXT NOT NULL,
  disabled              INTEGER NOT NULL DEFAULT 0,
  must_change_password  INTEGER NOT NULL DEFAULT 0
);
CREATE TABLE IF NOT EXISTS user_ssh_keys (
  username    TEXT NOT NULL REFERENCES users(username),
  key_text    TEXT NOT NULL,
  fingerprint TEXT NOT NULL,
  added_at    TEXT NOT NULL,
  label       TEXT NOT NULL DEFAULT '',
  PRIMARY KEY (username, fingerprint)
);
CREATE INDEX IF NOT EXISTS ix_user_ssh_keys_username ON user_ssh_keys(username);
"""

# A collector poll finished longer ago than this means the collector thread is
# dead or wedged -- "the last poll succeeded" then says nothing about NOW.
# 3x the slowest frequently-run cadence (remoteneed/enforce, 60s); connections
# runs every 15s, so a healthy collector is never anywhere near this.
COLLECTOR_STALE_SECONDS = 180.0

MISSING_FILES_CAP = 500
MISSING_FILES_MAX_AGE_DAYS = 7
HISTORY_MAX_AGE_DAYS = 30
HISTORY_THIN_AFTER_HOURS = 48
LANE_HISTORY_MAX_AGE_DAYS = 30
POLL_RUNS_KEEP = 2000
# machine_state had NO retention and NO cap, while `machine` is an
# attacker-chosen string of up to 128 chars on an endpoint (/api/v1/report)
# with no rate limit: one identity-token holder could mint unbounded rows
# that then show up forever in the fleet grid. Same 30-day cutoff as the lane
# tables, plus a hard per-editor ceiling applied at write time.
MACHINE_STATE_MAX_AGE_DAYS = 30
# Evict-oldest rather than refuse: a real editor swapping rigs must never be
# locked out of reporting by rows they can no longer delete, and a companion
# reporting every 30s can never be the row that gets evicted. 20 is far above
# any real editor's machine count (the fleet's busiest editor has 2).
MAX_MACHINES_PER_EDITOR = 20
# Shared non-trivial tokens required before an auto-match may be written as a
# permanent sticky mapping -- see match_project_label_confident.
MIN_CONFIDENT_TOKENS = 2

_DEVICE_ID_RE = re.compile(r"^[A-Z0-9]{7}(-[A-Z0-9]{7}){7}$")
_USERNAME_RE = re.compile(r"^[a-z][a-z0-9._-]{0,31}$")


def utcnow_iso() -> str:
    return dt.datetime.now(dt.timezone.utc).replace(microsecond=0).isoformat()


def parse_iso(ts: str) -> dt.datetime:
    return dt.datetime.fromisoformat(ts)


def age_seconds(ts: str, now: str) -> float:
    return (parse_iso(now) - parse_iso(ts)).total_seconds()


def connect(path: str | Path) -> sqlite3.Connection:
    # check_same_thread=False: FastAPI may create a request's connection in a
    # threadpool worker but use it from an async handler on the event loop.
    # Each connection still serves exactly one request/thread at a time.
    conn = sqlite3.connect(str(path), timeout=5.0, check_same_thread=False)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA busy_timeout=5000")
    conn.execute("PRAGMA foreign_keys=ON")
    return conn


# Ordered migration steps: (target user_version, script). `script=None` means
# "apply the base schema.sql" (the v0 -> v1 bootstrap). Each entry's
# user_version is committed IMMEDIATELY after that entry's script runs -- not
# once at the end -- so an upgrade interrupted between two steps (a
# `docker restart` mid-migration is routine) resumes on the next start
# instead of re-running an already-applied `ALTER TABLE ... ADD COLUMN` and
# crash-looping on `duplicate column name`. See the db.py migration finding.
_MIGRATION_STEPS: list[tuple[int, str | None]] = [
    (1, None),
    (2, SCHEMA_V2),
    (3, SCHEMA_V3),
    (4, SCHEMA_V4),
    (5, SCHEMA_V5),
    (6, SCHEMA_V6),
    (7, SCHEMA_V7),
    (8, SCHEMA_V8),
    (9, SCHEMA_V9),
    (10, SCHEMA_V10),
    (11, SCHEMA_V11),
    (12, SCHEMA_V12),
    (13, SCHEMA_V13),
    (14, SCHEMA_V14),
    (15, SCHEMA_V15),
    (16, SCHEMA_V16),
    (17, SCHEMA_V17),
    # 17 is another agent's migration (ZERO_TOUCH_PLAN.md WP C), landing in
    # its own worktree -- this step list will gain that entry on merge. This
    # worktree owns 18 only (see SCHEMA_V18's docstring); a DB that has not
    # seen 17 yet simply runs 16 -> 18 directly, which migrate()'s per-step
    # commit already tolerates (each target_version is independent DDL).
    (18, SCHEMA_V18),
]

SCHEMA_VERSION = _MIGRATION_STEPS[-1][0]

_ADD_COLUMN_RE = re.compile(
    r"^\s*ALTER\s+TABLE\s+(?P<table>[\w\"'`\[\]]+)\s+ADD\s+(?:COLUMN\s+)?(?P<column>[\w\"'`\[\]]+)",
    re.IGNORECASE,
)


def _split_statements(script: str) -> list[str]:
    """Split a migration script into individual statements.

    Uses sqlite's own completeness check rather than splitting on ';' -- the
    base schema has comments containing semicolons ("one row per (project,
    device); upserted every cycle"), and sqlite3_complete correctly ignores
    those (and string literals)."""
    statements: list[str] = []
    buffer = ""
    for line in script.splitlines(keepends=True):
        buffer += line
        if sqlite3.complete_statement(buffer):
            statements.append(buffer.strip())
            buffer = ""
    tail = buffer.strip()
    if tail:
        statements.append(tail)
    # Drop chunks that are only comments/whitespace (nothing to execute).
    return [
        s for s in statements
        if any(
            line.strip() and not line.strip().startswith("--")
            for line in s.splitlines()
        )
    ]


def _already_applied(conn: sqlite3.Connection, statement: str) -> bool:
    """True when an `ALTER TABLE x ADD COLUMN y` statement is already in
    effect. This is what makes a step REPLAYABLE: sqlite's executescript ran
    in autocommit, so an interrupt between two ADD COLUMNs left the column
    present while user_version stayed put -- and the replay then died on
    'duplicate column name', crash-looping the container forever (measured)."""
    stripped = "\n".join(
        line for line in statement.splitlines() if not line.strip().startswith("--")
    )
    match = _ADD_COLUMN_RE.match(stripped)
    if match is None:
        return False
    table = match.group("table").strip('"\'`[]')
    column = match.group("column").strip('"\'`[]')
    try:
        existing = {r[1] for r in conn.execute(f'PRAGMA table_info("{table}")')}
    except sqlite3.Error:
        return False
    return column in existing


def migrate(
    conn: sqlite3.Connection, steps: list[tuple[int, str | None]] | None = None
) -> None:
    """Apply schema migrations in order, one statement at a time.

    Each step runs as individual statements with the `user_version` bump in
    the SAME explicit transaction, and every `ADD COLUMN` is skipped when the
    column already exists -- so an interrupt anywhere (including *within* a
    step, which executescript's autocommit made unrecoverable) leaves a DB
    that the next start can simply replay. `steps` is overridable (tests
    only) so this behaviour can be exercised without depending on the real
    schema."""
    steps = _MIGRATION_STEPS if steps is None else steps
    version = conn.execute("PRAGMA user_version").fetchone()[0]
    target_max = max((v for v, _ in steps), default=0)
    if version > target_max:
        # A rollback to an older image against a newer schema: fail with a
        # clear message instead of 500ing later on the first query that
        # touches a column this build doesn't know about.
        raise RuntimeError(
            f"database schema is newer than this build: user_version={version}, "
            f"this build knows {target_max}. Deploy the matching (or a newer) image."
        )
    for target_version, script in steps:
        if version >= target_version:
            continue
        body = SCHEMA_PATH.read_text(encoding="utf-8") if script is None else script
        # BEGIN/COMMIT explicitly: the sqlite3 module would otherwise leave
        # DDL in autocommit, which is exactly the hole this closes. migrate()
        # runs at startup and owns its transaction outright -- never nest.
        if conn.in_transaction:
            conn.commit()
        conn.execute("BEGIN")
        try:
            for statement in _split_statements(body):
                if _already_applied(conn, statement):
                    continue
                conn.execute(statement)
            conn.execute(f"PRAGMA user_version = {target_version}")
        except Exception:
            conn.rollback()
            raise
        conn.commit()
        version = target_version


def resolve_editor_username(
    device_name: str, known_editors: Container[str] | None = None
) -> str | None:
    """Map a Syncthing device name to a TrueNAS username, or None if unmapped.

    Convention: accept_device.py --device-name <username>. When the flag was
    omitted the name is the device ID itself -- never treat that as a person.

    `known_editors` is the set of usernames the dashboard has a POSITIVE
    record of (see known_editor_usernames). Being username-SHAPED is not
    enough: machine names look exactly like usernames ("editor-laptop",
    "edit-pc"), and a device approved under one used to resolve to an editor
    account that does not exist, with no selections rows -- so the enforce
    cycle read it as "this editor is ticked for nothing" and unshared the
    device from every folder it was on (KNOWN_BUGS B16). An unresolvable name
    is UNMAPPED, and unmapped devices are never added or removed by enforce,
    which is the fail-safe direction.

    `known_editors=None` keeps the old shape-only behaviour, for the callers
    (and tests) that have no database to consult.
    """
    if _DEVICE_ID_RE.match(device_name):
        return None
    candidate = device_name.strip().lower()
    if not _USERNAME_RE.match(candidate):
        return None
    if known_editors is not None and candidate not in known_editors:
        return None
    return candidate


# Where a known-editor record can come from. 'report' means a companion
# reported under that name; 'admin' an explicit admin action; 'seed'/
# 'selection' a project tick.
KNOWN_EDITOR_SOURCES = ("report", "seed", "selection", "admin")


def record_known_editor(
    conn: sqlite3.Connection, editor: str, source: str, now: str | None = None
) -> None:
    """Remember that `editor` is a real editor account (append-only).

    Called from the paths where the dashboard has evidence rather than a
    guess: a report under a signed identity, an admin approving a device or
    creating an account, a project tick, and the one-shot share seed. The
    record must OUTLIVE the evidence -- an editor who unticks every project
    is still an editor, and enforce must still be willing to unshare their
    devices."""
    name = str(editor or "").strip().lower()
    if not name or not _USERNAME_RE.match(name):
        return
    conn.execute(
        "INSERT OR IGNORE INTO known_editors (editor_username, first_seen, source) "
        "VALUES (?, ?, ?)",
        (name, now or utcnow_iso(), source),
    )


# ----------------------------------------------------- per-editor report tokens
#
# Format: "cce1.<token_id>.<secret>" -- a version tag, a public id and the
# secret, all lowercase hex after the tag. The version tag is what lets a
# caller tell a per-editor token from the shared DASH_REPORT_TOKEN by LOOKING
# at it, before any database work: everything that authenticates a companion
# needs that discrimination (app.py's pre-body gate most of all, which must
# decide before it has spent a byte on the request).
#
# The secret is never stored. Only sha256(secret) is, so a stolen dashboard.db
# is not a set of working fleet credentials -- and the admin sees the value
# exactly once, at mint time (COMMERCIAL_READINESS.md item 15, 2026-08-17).
REPORT_TOKEN_PREFIX = "cce1."
_REPORT_TOKEN_RE = re.compile(r"^cce1\.([0-9a-f]{16})\.([0-9a-f]{48})$")


def looks_like_editor_report_token(token: str) -> bool:
    """Shape only -- says nothing about whether it is valid or revoked."""
    return bool(_REPORT_TOKEN_RE.match(str(token or "")))


def _hash_report_secret(secret: str) -> str:
    return hashlib.sha256(secret.encode("utf-8")).hexdigest()


def create_editor_report_token(
    conn: sqlite3.Connection, editor: str, created_by: str,
    label: str = "", now: str | None = None,
) -> tuple[str, dict[str, Any]]:
    """Mint a token for `editor`. -> (the token string, its row-as-dict).

    The token string is the ONLY time the secret exists outside the caller's
    hands; nothing stores it and no route ever answers with it again.
    """
    name = str(editor or "").strip().lower()
    if not name or not _USERNAME_RE.match(name):
        raise ValueError(f"{editor!r} is not a valid editor username")
    token_id = secrets.token_hex(8)
    secret = secrets.token_hex(24)
    created_at = now or utcnow_iso()
    conn.execute(
        "INSERT INTO editor_report_tokens "
        "(token_id, editor_username, token_hash, label, created_at, created_by) "
        "VALUES (?, ?, ?, ?, ?, ?)",
        (token_id, name, _hash_report_secret(secret), str(label or "").strip()[:64],
         created_at, str(created_by or "")),
    )
    row = {"token_id": token_id, "editor_username": name,
           "label": str(label or "").strip()[:64], "created_at": created_at,
           "created_by": str(created_by or ""), "last_used_at": None,
           "revoked_at": None, "revoked_by": None}
    return f"{REPORT_TOKEN_PREFIX}{token_id}.{secret}", row


def verify_editor_report_token(
    conn: sqlite3.Connection, token: str, now: str | None = None
) -> str | None:
    """The editor this token belongs to, or None.

    None covers every failure alike -- wrong shape, unknown id, wrong secret,
    revoked -- because a caller that could tell them apart would have an
    oracle for which token ids exist.
    """
    match = _REPORT_TOKEN_RE.match(str(token or ""))
    if match is None:
        return None
    token_id, secret = match.group(1), match.group(2)
    row = conn.execute(
        "SELECT editor_username, token_hash, revoked_at FROM editor_report_tokens "
        "WHERE token_id = ?", (token_id,)
    ).fetchone()
    if row is None or row["revoked_at"]:
        return None
    if not hmac.compare_digest(row["token_hash"], _hash_report_secret(secret)):
        return None
    return str(row["editor_username"])


def touch_editor_report_token(
    conn: sqlite3.Connection, token: str, now: str | None = None
) -> None:
    """Record that this token was just used. Best-effort, never raises.

    Separate from verify_ so the hot path can decide whether a write is worth
    it -- and so a read-only verification (the pre-body gate in app.py, which
    opens its own connection) does not have to write at all.
    """
    match = _REPORT_TOKEN_RE.match(str(token or ""))
    if match is None:
        return
    try:
        conn.execute("UPDATE editor_report_tokens SET last_used_at = ? WHERE token_id = ?",
                     (now or utcnow_iso(), match.group(1)))
    except sqlite3.Error:
        pass


def fetch_editor_report_tokens(
    conn: sqlite3.Connection, editor: str | None = None, include_revoked: bool = False
) -> list[dict[str, Any]]:
    """Token METADATA -- never a secret; there is no secret stored to leak."""
    sql = ("SELECT token_id, editor_username, label, created_at, created_by, "
           "last_used_at, revoked_at, revoked_by FROM editor_report_tokens")
    where, params = [], []
    if editor:
        where.append("editor_username = ?")
        params.append(str(editor).strip().lower())
    if not include_revoked:
        where.append("revoked_at IS NULL")
    if where:
        sql += " WHERE " + " AND ".join(where)
    sql += " ORDER BY editor_username, created_at DESC"
    return [dict(r) for r in conn.execute(sql, params)]


def revoke_editor_report_token(
    conn: sqlite3.Connection, token_id: str, revoked_by: str, now: str | None = None
) -> bool:
    """True if a live token was revoked. Revoking is a soft delete: the row
    stays so an admin can still see that the credential existed and when it
    was last used."""
    cur = conn.execute(
        "UPDATE editor_report_tokens SET revoked_at = ?, revoked_by = ? "
        "WHERE token_id = ? AND revoked_at IS NULL",
        (now or utcnow_iso(), str(revoked_by or ""), str(token_id or "")),
    )
    return cur.rowcount > 0


def record_report_auth(
    conn: sqlite3.Connection, editor: str, machine: str, auth_kind: str,
    now: str | None = None
) -> None:
    """Which credential this machine's last report used. Migration telemetry.

    See count_shared_token_machines: the answer to "is it safe to turn
    DASH_SHARED_REPORT_TOKEN_ENABLED off yet" has to come from the fleet, not
    from an operator's memory of who they handed tokens to."""
    name = str(editor or "").strip().lower()
    if not name or auth_kind not in ("shared", "editor"):
        return
    conn.execute(
        "INSERT INTO report_auth (editor_username, machine, auth_kind, at) "
        "VALUES (?, ?, ?, ?) "
        "ON CONFLICT(editor_username, machine) DO UPDATE SET "
        "auth_kind = excluded.auth_kind, at = excluded.at",
        (name, str(machine or ""), auth_kind, now or utcnow_iso()),
    )


def count_shared_token_machines(conn: sqlite3.Connection) -> dict[str, Any]:
    """{"shared": n, "editor": n, "machines": [...]} -- who is still on the
    shared fleet token. Tolerates a database that predates the table (an
    older dashboard.db mid-migration) by answering zeroes."""
    result: dict[str, Any] = {"shared": 0, "editor": 0, "machines": []}
    try:
        rows = conn.execute(
            "SELECT editor_username, machine, auth_kind FROM report_auth"
        ).fetchall()
    except sqlite3.Error:
        return result
    for row in rows:
        kind = row["auth_kind"]
        if kind in result:
            result[kind] += 1
        if kind == "shared":
            result["machines"].append(f"{row['editor_username']}/{row['machine']}")
    result["machines"].sort()
    return result


def known_editor_usernames(conn: sqlite3.Connection) -> set[str]:
    """Every username the dashboard has a positive record of.

    Four sources, all of them evidence that the account exists rather than
    that a string looks like a username: the append-only known_editors table,
    anyone with a project ticked, anyone with a stored preference, and anyone
    whose companion has reported (machine_state.editor_username comes from a
    verified identity token, or at minimum from a holder of the fleet report
    token -- never from a Syncthing device label, which is the thing being
    validated here)."""
    names: set[str] = set()
    for sql in (
        "SELECT DISTINCT editor_username FROM known_editors",
        "SELECT DISTINCT editor_username FROM selections",
        "SELECT DISTINCT editor_username FROM editor_prefs",
        "SELECT DISTINCT editor_username FROM machine_state",
    ):
        for row in conn.execute(sql):
            name = str(row[0] or "").strip().lower()
            if name:
                names.add(name)
    return names


def compute_rate_ema(
    prev_need_bytes: int | None,
    prev_rate: float | None,
    new_need_bytes: int,
    dt_seconds: float,
) -> float | None:
    """EMA of the byte drain rate for one (project, device) pair.

    Resets when need grows (new work arrived) or there is no history.
    Returns None when nothing can be computed (dt<=0 with no prior rate).
    """
    if prev_need_bytes is None or dt_seconds <= 0:
        return prev_rate
    sample = max(0, prev_need_bytes - new_need_bytes) / dt_seconds
    if prev_rate is None or new_need_bytes > prev_need_bytes:
        return sample
    return 0.3 * sample + 0.7 * prev_rate


# ---------------------------------------------------------------- writes

def upsert_project(conn: sqlite3.Connection, slug: str, label: str, path: str, now: str) -> int:
    conn.execute(
        """INSERT INTO projects (slug, label, path, first_seen, last_seen, active)
           VALUES (?, ?, ?, ?, ?, 1)
           ON CONFLICT(slug) DO UPDATE SET
             label=excluded.label, path=excluded.path, last_seen=excluded.last_seen, active=1""",
        (slug, label, path, now, now),
    )
    return conn.execute("SELECT id FROM projects WHERE slug=?", (slug,)).fetchone()[0]


def deactivate_missing_projects(
    conn: sqlite3.Connection,
    seen_slugs: Iterable[str],
    now: str | None = None,
    grace_seconds: int = 900,
) -> None:
    """Deactivate projects whose Syncthing folder is gone -- EXCEPT rows seen
    recently. The grace window exists for eagerly-created projects (the
    /project-setup page inserts the row immediately; the collector's
    provision cycle creates the Syncthing folder up to 5 minutes later --
    without the grace, this would flip the new project inactive in the gap
    and break the link/create flow that just made it)."""
    slugs = list(seen_slugs)
    placeholders = ",".join("?" * len(slugs)) or "''"
    now = now or utcnow_iso()
    cutoff = (parse_iso(now) - dt.timedelta(seconds=grace_seconds)).isoformat()
    conn.execute(
        f"UPDATE projects SET active=0 WHERE active=1 AND last_seen < ? "
        f"AND slug NOT IN ({placeholders})",
        [cutoff, *slugs],
    )


def set_folder_status(
    conn: sqlite3.Connection, project_id: int, state: str | None,
    error: str | None, now: str,
    need_items: int | None = None, need_bytes: int | None = None,
) -> None:
    """Record Syncthing's own health for this project's folder.

    `state` is Syncthing's folder state ('idle', 'scanning', 'error',
    'stopped'...) and `error` its folder-level error string ("folder marker
    missing" after a botched move). Surfaced by build_project_view and
    fetch_collector_status so a folder that has stopped syncing entirely
    can't keep showing a stale-but-plausible completion %."""
    conn.execute(
        """UPDATE projects SET folder_state=?, folder_error=?, folder_state_at=?,
             need_items=?, need_bytes=? WHERE id=?""",
        (state, (error or None), now, need_items, need_bytes, project_id),
    )


def upsert_device(
    conn: sqlite3.Connection, device_id: str, name: str, is_server: bool, now: str,
    known_editors: Container[str] | None = None,
) -> int:
    """`known_editors` is passed through to resolve_editor_username -- the
    collector computes it once per cycle rather than per device. Omitted, the
    mapping falls back to a shape check (see B16)."""
    conn.execute(
        """INSERT INTO devices (device_id, name, editor_username, is_server, first_seen, last_seen)
           VALUES (?, ?, ?, ?, ?, ?)
           ON CONFLICT(device_id) DO UPDATE SET
             name=excluded.name, editor_username=excluded.editor_username,
             is_server=excluded.is_server, last_seen=excluded.last_seen""",
        (device_id, name, resolve_editor_username(name, known_editors),
         int(is_server), now, now),
    )
    return conn.execute("SELECT id FROM devices WHERE device_id=?", (device_id,)).fetchone()[0]


def set_connections(
    conn: sqlite3.Connection, connected: Mapping[str, str | None], now: str
) -> None:
    """connected: device_id -> address (or None) for currently-connected devices.
    Every known device not in the mapping is marked disconnected."""
    conn.execute("UPDATE devices SET connected=0 WHERE connected=1")
    for device_id, address in connected.items():
        conn.execute(
            """UPDATE devices SET connected=1, address=?, last_connected_at=?
               WHERE device_id=?""",
            (address, now, device_id),
        )


def should_snapshot(
    last: Mapping[str, Any] | None, completion: float, need_items: int, now: str
) -> bool:
    """History anti-bloat rules; `last` is the newest completion_history row
    for this (project, device) pair or None."""
    if last is None:
        return True
    if completion >= 100 and last["completion"] >= 100:
        return age_seconds(last["ts"], now) >= 6 * 3600
    if int(completion) != int(last["completion"]):
        return True
    last_items = last["need_items"]
    if last_items == 0:
        if need_items > 0:
            return True
    elif abs(need_items - last_items) / last_items > 0.10:
        return True
    if completion < 100 and age_seconds(last["ts"], now) >= 15 * 60:
        return True
    return False


def upsert_completion(
    conn: sqlite3.Connection,
    project_id: int,
    device_id: int,
    *,
    completion: float,
    need_items: int,
    need_bytes: int,
    need_deletes: int,
    global_items: int | None,
    global_bytes: int | None,
    now: str,
) -> None:
    prev = conn.execute(
        """SELECT need_bytes, rate_bytes_per_sec, updated_at FROM completion_current
           WHERE project_id=? AND device_id=?""",
        (project_id, device_id),
    ).fetchone()
    rate = compute_rate_ema(
        prev["need_bytes"] if prev else None,
        prev["rate_bytes_per_sec"] if prev else None,
        need_bytes,
        age_seconds(prev["updated_at"], now) if prev else 0.0,
    )
    conn.execute(
        """INSERT INTO completion_current
             (project_id, device_id, completion, need_items, need_bytes, need_deletes,
              global_items, global_bytes, rate_bytes_per_sec, updated_at)
           VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
           ON CONFLICT(project_id, device_id) DO UPDATE SET
             completion=excluded.completion, need_items=excluded.need_items,
             need_bytes=excluded.need_bytes, need_deletes=excluded.need_deletes,
             global_items=excluded.global_items, global_bytes=excluded.global_bytes,
             rate_bytes_per_sec=excluded.rate_bytes_per_sec,
             updated_at=excluded.updated_at""",
        (project_id, device_id, completion, need_items, need_bytes, need_deletes,
         global_items, global_bytes, rate, now),
    )
    last = conn.execute(
        """SELECT completion, need_items, ts FROM completion_history
           WHERE project_id=? AND device_id=? ORDER BY ts DESC, id DESC LIMIT 1""",
        (project_id, device_id),
    ).fetchone()
    if should_snapshot(last, completion, need_items, now):
        conn.execute(
            """INSERT INTO completion_history
                 (project_id, device_id, ts, completion, need_items, need_bytes)
               VALUES (?, ?, ?, ?, ?, ?)""",
            (project_id, device_id, now, completion, need_items, need_bytes),
        )


def replace_missing_files(
    conn: sqlite3.Connection,
    project_id: int,
    device_id: int,
    files: list[tuple[str, int | None]],
    truncated: bool,
    now: str,
) -> None:
    conn.execute(
        "DELETE FROM missing_files WHERE project_id=? AND device_id=?", (project_id, device_id)
    )
    conn.executemany(
        """INSERT OR REPLACE INTO missing_files
             (project_id, device_id, name, size, truncated, refreshed_at)
           VALUES (?, ?, ?, ?, ?, ?)""",
        [(project_id, device_id, name, size, int(truncated), now)
         for name, size in files[:MISSING_FILES_CAP]],
    )


def clear_missing_files(conn: sqlite3.Connection, project_id: int, device_id: int) -> None:
    conn.execute(
        "DELETE FROM missing_files WHERE project_id=? AND device_id=?", (project_id, device_id)
    )


def upsert_lane_report(
    conn: sqlite3.Connection,
    *,
    editor_username: str,
    machine: str,
    lane: str,
    state: str,
    queued: int | None,
    transferring: int | None,
    last_error: str | None,
    last_sync: str | None,
    detail: str | None,
    companion_version: str | None,
    reported_at: str,
    received_at: str,
    current_project: str | None = None,
    bytes_done: int | None = None,
    bytes_total: int | None = None,
    speed_bps: float | None = None,
    eta_seconds: float | None = None,
) -> None:
    prev = conn.execute(
        """SELECT state, last_error FROM lane_report_current
           WHERE editor_username=? AND machine=? AND lane=?""",
        (editor_username, machine, lane),
    ).fetchone()
    conn.execute(
        """INSERT INTO lane_report_current
             (editor_username, machine, lane, state, queued, transferring, last_error,
              last_sync, detail, companion_version, reported_at, received_at,
              current_project, bytes_done, bytes_total, speed_bps, eta_seconds)
           VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
           ON CONFLICT(editor_username, machine, lane) DO UPDATE SET
             state=excluded.state, queued=excluded.queued, transferring=excluded.transferring,
             last_error=excluded.last_error, last_sync=excluded.last_sync,
             detail=excluded.detail, companion_version=excluded.companion_version,
             reported_at=excluded.reported_at, received_at=excluded.received_at,
             current_project=excluded.current_project, bytes_done=excluded.bytes_done,
             bytes_total=excluded.bytes_total, speed_bps=excluded.speed_bps,
             eta_seconds=excluded.eta_seconds""",
        (editor_username, machine, lane, state, queued, transferring, last_error,
         last_sync, detail, companion_version, reported_at, received_at,
         current_project, bytes_done, bytes_total, speed_bps, eta_seconds),
    )
    if prev is None or prev["state"] != state or prev["last_error"] != last_error:
        conn.execute(
            """INSERT INTO lane_report_history
                 (editor_username, machine, lane, state, queued, last_error, ts)
               VALUES (?, ?, ?, ?, ?, ?, ?)""",
            (editor_username, machine, lane, state, queued, last_error, received_at),
        )


def meta_get(conn: sqlite3.Connection, key: str) -> str | None:
    row = conn.execute("SELECT value FROM meta WHERE key=?", (key,)).fetchone()
    return row["value"] if row else None


def meta_set(conn: sqlite3.Connection, key: str, value: str) -> None:
    conn.execute(
        "INSERT INTO meta (key, value) VALUES (?, ?) "
        "ON CONFLICT(key) DO UPDATE SET value=excluded.value",
        (key, value),
    )


def insert_companion_package(
    conn: sqlite3.Connection,
    *,
    version: str,
    platform: str,
    filename: str,
    sha256: str,
    size_bytes: int,
    published_by: str,
    now: str,
    kind: str = "companion",
    signature: str = "",
    pubkey_id: str = "",
    min_version: str = "",
    signed_binary: bool = False,
) -> None:
    # `now` is the SIGNER's published_at, not the server's clock: it is one of
    # the fields the release signature covers, so storing anything else would
    # serve a record that no longer verifies (item 4, 2026-08-17).
    conn.execute(
        """INSERT INTO companion_packages
             (kind, version, platform, filename, sha256, size_bytes, published_at,
              published_by, signature, pubkey_id, min_version, signed_binary)
           VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
        (kind, version, platform, filename, sha256, size_bytes, now, published_by,
         signature, pubkey_id, min_version, 1 if signed_binary else 0),
    )


def fetch_companion_packages(
    conn: sqlite3.Connection, platform: str | None = None
) -> list[sqlite3.Row]:
    if platform is None:
        return conn.execute(
            "SELECT * FROM companion_packages ORDER BY kind, platform, published_at DESC"
        ).fetchall()
    return conn.execute(
        "SELECT * FROM companion_packages WHERE platform=? "
        "ORDER BY kind, published_at DESC",
        (platform,),
    ).fetchall()


def get_package(
    conn: sqlite3.Connection, platform: str, version: str, kind: str = "companion"
) -> sqlite3.Row | None:
    return conn.execute(
        "SELECT * FROM companion_packages WHERE kind=? AND platform=? AND version=?",
        (kind, platform, version),
    ).fetchone()


def get_current_package(
    conn: sqlite3.Connection, platform: str, kind: str = "companion"
) -> sqlite3.Row | None:
    return conn.execute(
        "SELECT * FROM companion_packages WHERE kind=? AND platform=? AND is_current=1",
        (kind, platform),
    ).fetchone()


def set_current_package(
    conn: sqlite3.Connection, platform: str, version: str, kind: str = "companion"
) -> bool:
    """Point `current` at (kind, platform, version). False if that version is
    unknown. Currency is per (kind, platform): making an onboard build current
    never touches which companion the fleet is offered, and vice versa."""
    if get_package(conn, platform, version, kind) is None:
        return False
    conn.execute(
        "UPDATE companion_packages SET is_current=0 WHERE kind=? AND platform=?",
        (kind, platform),
    )
    conn.execute(
        "UPDATE companion_packages SET is_current=1 WHERE kind=? AND platform=? AND version=?",
        (kind, platform, version),
    )
    return True


def delete_companion_package(
    conn: sqlite3.Connection, platform: str, version: str, kind: str = "companion"
) -> sqlite3.Row | None:
    """Delete the row and return it (so the caller can unlink the file).

    The caller must have already refused to delete the current version --
    this function doesn't re-check.
    """
    row = get_package(conn, platform, version, kind)
    if row is None:
        return None
    conn.execute(
        "DELETE FROM companion_packages WHERE kind=? AND platform=? AND version=?",
        (kind, platform, version),
    )
    return row


def prune_companion_packages(
    conn: sqlite3.Connection, platform: str, keep: int = 2, kind: str = "companion"
) -> list[sqlite3.Row]:
    """Delete all but the current package and the `keep` newest non-current
    ones of this kind. Returns the removed rows so the caller can unlink
    their files."""
    victims = conn.execute(
        """SELECT * FROM companion_packages
           WHERE kind=? AND platform=? AND is_current=0
           ORDER BY published_at DESC, id DESC
           LIMIT -1 OFFSET ?""",
        (kind, platform, keep),
    ).fetchall()
    for row in victims:
        conn.execute("DELETE FROM companion_packages WHERE id=?", (row["id"],))
    return victims


def add_selection(
    conn: sqlite3.Connection, editor: str, slug: str, created_by: str, now: str
) -> bool:
    """Tick. Returns False if already ticked. Position = end of the queue."""
    next_pos = conn.execute(
        "SELECT COALESCE(MAX(position), 0) + 1 FROM selections WHERE editor_username=?",
        (editor,),
    ).fetchone()[0]
    cur = conn.execute(
        """INSERT OR IGNORE INTO selections
             (editor_username, project_slug, position, created_at, created_by)
           VALUES (?, ?, ?, ?, ?)""",
        (editor, slug, next_pos, now, created_by),
    )
    return cur.rowcount > 0


def remove_selection(conn: sqlite3.Connection, editor: str, slug: str) -> bool:
    cur = conn.execute(
        "DELETE FROM selections WHERE editor_username=? AND project_slug=?", (editor, slug)
    )
    return cur.rowcount > 0


def fetch_selections(conn: sqlite3.Connection, editor: str) -> list[dict[str, Any]]:
    """Editor's ticked projects in queue order, joined to project label/path.
    Selections whose project no longer exists or is inactive are kept in the
    row (slug only) but flagged, so the UI can surface them."""
    rows = conn.execute(
        """SELECT s.project_slug AS slug, s.position, s.created_at, s.created_by,
                  p.label, p.active
           FROM selections s LEFT JOIN projects p ON p.slug = s.project_slug
           WHERE s.editor_username = ?
           ORDER BY s.position""",
        (editor,),
    )
    return [dict(r) for r in rows]


def fetch_all_selections(conn: sqlite3.Connection) -> dict[str, list[str]]:
    """slug -> [editor_username...] over all selections."""
    grouped: dict[str, list[str]] = {}
    for row in conn.execute(
        "SELECT project_slug, editor_username FROM selections ORDER BY editor_username"
    ):
        grouped.setdefault(row["project_slug"], []).append(row["editor_username"])
    return grouped


def set_project_root_override(
    conn: sqlite3.Connection, editor: str, slug: str | None, updated_by: str, now: str
) -> None:
    conn.execute(
        """INSERT INTO editor_prefs (editor_username, project_root_override, updated_at, updated_by)
           VALUES (?, ?, ?, ?)
           ON CONFLICT(editor_username) DO UPDATE SET
             project_root_override=excluded.project_root_override,
             updated_at=excluded.updated_at, updated_by=excluded.updated_by""",
        (editor, slug, now, updated_by),
    )


def get_project_root_override(conn: sqlite3.Connection, editor: str) -> str | None:
    row = conn.execute(
        "SELECT project_root_override FROM editor_prefs WHERE editor_username=?", (editor,)
    ).fetchone()
    return row["project_root_override"] if row else None


def upsert_machine_state(
    conn: sqlite3.Connection, editor: str, machine: str,
    detected_project_root: str | None, now: str,
    resolve_project: str | None = None, verified: bool = False,
    platform: str | None = None, companion_version: str | None = None,
    transport: Mapping[str, Any] | None = None,
    guard: Mapping[str, Any] | None = None,
) -> None:
    """`transport` is summarize_transport_health()'s flattened dict, or None.

    None leaves the stored transport columns ALONE rather than nulling them:
    the companion only computes transport_health on HEAVY ticks, so a LIGHT
    report must not wipe the relay/orphan state between two heavy ones (same
    rule the media tables follow).

    `guard` is flatten_sync_guard()'s dict -- the lane B breaker, the trash
    size, the halt and lane A's "skipped, exists" counter (v16,
    COMMERCIAL_READINESS.md item 9). Same None-leaves-it-alone rule, with one
    deliberate exception below: the two BOOLEAN latches are written on every
    guard-bearing report, because a breaker that clears has to be able to
    clear the alarm."""
    t = dict(transport or {})
    g = dict(guard or {})
    conn.execute(
        """INSERT INTO machine_state
             (editor_username, machine, detected_project_root, reported_at,
              resolve_project, verified, platform, companion_version,
              transport_relayed, transport_direct, orphan_partials,
              orphan_partial_bytes, express_dropped, express_last_error,
              transport_at,
              breaker_tripped, breaker_reason, breaker_at, trash_bytes,
              trash_count, halt_active, halt_scope, halt_reason,
              skipped_exists, guard_at)
           VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?,
                   ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
           ON CONFLICT(editor_username, machine) DO UPDATE SET
             detected_project_root=excluded.detected_project_root,
             reported_at=excluded.reported_at,
             resolve_project=excluded.resolve_project,
             verified=excluded.verified,
             platform=COALESCE(excluded.platform, machine_state.platform),
             companion_version=COALESCE(excluded.companion_version,
                                        machine_state.companion_version),
             transport_relayed=COALESCE(excluded.transport_relayed,
                                        machine_state.transport_relayed),
             transport_direct=COALESCE(excluded.transport_direct,
                                       machine_state.transport_direct),
             orphan_partials=COALESCE(excluded.orphan_partials,
                                      machine_state.orphan_partials),
             orphan_partial_bytes=COALESCE(excluded.orphan_partial_bytes,
                                           machine_state.orphan_partial_bytes),
             express_dropped=COALESCE(excluded.express_dropped,
                                      machine_state.express_dropped),
             express_last_error=CASE WHEN excluded.transport_at IS NULL
                                     THEN machine_state.express_last_error
                                     ELSE excluded.express_last_error END,
             transport_at=COALESCE(excluded.transport_at,
                                   machine_state.transport_at),
             -- The LATCHES are set from this report whenever it carried a
             -- guard section at all (guard_at is the marker), never
             -- COALESCEd: COALESCE cannot express "back to false", so a
             -- resumed breaker would have left the fleet alarm on forever.
             breaker_tripped=CASE WHEN excluded.guard_at IS NULL
                                  THEN machine_state.breaker_tripped
                                  ELSE excluded.breaker_tripped END,
             breaker_reason=CASE WHEN excluded.guard_at IS NULL
                                 THEN machine_state.breaker_reason
                                 ELSE excluded.breaker_reason END,
             breaker_at=CASE WHEN excluded.guard_at IS NULL
                             THEN machine_state.breaker_at
                             ELSE excluded.breaker_at END,
             halt_active=CASE WHEN excluded.guard_at IS NULL
                              THEN machine_state.halt_active
                              ELSE excluded.halt_active END,
             halt_scope=CASE WHEN excluded.guard_at IS NULL
                             THEN machine_state.halt_scope
                             ELSE excluded.halt_scope END,
             halt_reason=CASE WHEN excluded.guard_at IS NULL
                              THEN machine_state.halt_reason
                              ELSE excluded.halt_reason END,
             trash_bytes=COALESCE(excluded.trash_bytes, machine_state.trash_bytes),
             trash_count=COALESCE(excluded.trash_count, machine_state.trash_count),
             skipped_exists=COALESCE(excluded.skipped_exists,
                                     machine_state.skipped_exists),
             guard_at=COALESCE(excluded.guard_at, machine_state.guard_at)""",
        (editor, machine, detected_project_root, now, resolve_project, int(verified),
         platform, companion_version,
         t.get("relayed"), t.get("direct"), t.get("orphan_partials"),
         t.get("orphan_partial_bytes"), t.get("express_dropped"),
         t.get("express_last_error"), t.get("at"),
         g.get("breaker_tripped"), g.get("breaker_reason"), g.get("breaker_at"),
         g.get("trash_bytes"), g.get("trash_count"), g.get("halt_active"),
         g.get("halt_scope"), g.get("halt_reason"), g.get("skipped_exists"),
         g.get("at")),
    )
    evict_extra_machines(conn, editor)


def fetch_sync_guard_map(conn: sqlite3.Connection) -> dict[tuple[str, str], dict[str, Any]]:
    """(editor, machine) -> the safety-latch state for the fleet grid (v16).

    The alarm source: a tripped lane B breaker or a halted machine is
    indistinguishable from a healthy idle one on every other signal the grid
    has (COMMERCIAL_READINESS.md item 9, 2026-08-17)."""
    return {
        (r["editor_username"], r["machine"]): {
            "breaker_tripped": bool(r["breaker_tripped"]),
            "breaker_reason": r["breaker_reason"],
            "breaker_at": r["breaker_at"],
            "trash_bytes": r["trash_bytes"],
            "trash_count": r["trash_count"],
            "halt_active": bool(r["halt_active"]),
            "halt_scope": r["halt_scope"],
            "halt_reason": r["halt_reason"],
            "skipped_exists": r["skipped_exists"],
            "at": r["guard_at"],
        }
        for r in conn.execute(
            """SELECT editor_username, machine, breaker_tripped, breaker_reason,
                      breaker_at, trash_bytes, trash_count, halt_active, halt_scope,
                      halt_reason, skipped_exists, guard_at
               FROM machine_state"""
        )
    }


# The fleet halt lives in `meta`, not in a table of its own: it is exactly one
# row of state for the whole dashboard, and `meta` is where the collector
# already keeps that class of thing. JSON in the value so the reason and who
# set it travel with the flag (COMMERCIAL_READINESS.md item 9, 2026-08-17).
FLEET_HALT_KEY = "fleet_halt"


def get_fleet_halt(conn: sqlite3.Connection) -> dict[str, Any]:
    """{"active", "reason", "set_by", "set_at"} -- never None.

    A corrupt/absent value reads as NOT halted, deliberately: a dashboard
    that cannot parse its own flag must not silently stop the whole fleet
    from syncing, and an admin can always set it again."""
    raw = meta_get(conn, FLEET_HALT_KEY)
    if not raw:
        return {"active": False, "reason": "", "set_by": "", "set_at": ""}
    try:
        data = json.loads(raw)
    except (TypeError, ValueError):
        return {"active": False, "reason": "", "set_by": "", "set_at": ""}
    if not isinstance(data, dict):
        return {"active": False, "reason": "", "set_by": "", "set_at": ""}
    return {
        "active": bool(data.get("active")),
        "reason": str(data.get("reason") or ""),
        "set_by": str(data.get("set_by") or ""),
        "set_at": str(data.get("set_at") or ""),
    }


def set_fleet_halt(
    conn: sqlite3.Connection, active: bool, reason: str, by: str, now: str | None = None
) -> dict[str, Any]:
    state = {
        "active": bool(active),
        "reason": str(reason or "")[:500],
        "set_by": str(by or "")[:64],
        "set_at": now or utcnow_iso(),
    }
    meta_set(conn, FLEET_HALT_KEY, json.dumps(state))
    return state


def fetch_transport_map(conn: sqlite3.Connection) -> dict[tuple[str, str], dict[str, Any]]:
    """(editor, machine) -> the transport/orphan diagnostics for the fleet grid.

    Nothing in production could tell a RELAYED editor from a merely slow one:
    Syncthing devices are added with addresses:["dynamic"] and relays left at
    their `true` default, so lane C can silently ride the public relay pool at
    1-5 MB/s. `relayed` being non-zero is the whole answer (B17)."""
    return {
        (r["editor_username"], r["machine"]): {
            "relayed": r["transport_relayed"],
            "direct": r["transport_direct"],
            "orphan_partials": r["orphan_partials"],
            "orphan_partial_bytes": r["orphan_partial_bytes"],
            "express_dropped": r["express_dropped"],
            "express_last_error": r["express_last_error"],
            "at": r["transport_at"],
        }
        for r in conn.execute(
            """SELECT editor_username, machine, transport_relayed, transport_direct,
                      orphan_partials, orphan_partial_bytes, express_dropped,
                      express_last_error, transport_at
               FROM machine_state"""
        )
    }


def evict_extra_machines(
    conn: sqlite3.Connection, editor: str, keep: int = MAX_MACHINES_PER_EDITOR
) -> int:
    """Keep only this editor's `keep` most recently-reporting machines.

    `machine` is attacker-chosen (<=128 chars) and /api/v1/report is
    unthrottled, so without this one identity-token holder could grow
    machine_state without bound -- and every row shows up in the fleet grid.
    Evicting the OLDEST (rather than refusing the new row) means a live
    companion, which reports every 30s, can never be the row that goes."""
    victims = [
        r["machine"] for r in conn.execute(
            """SELECT machine FROM machine_state WHERE editor_username=?
               ORDER BY reported_at DESC, machine ASC LIMIT -1 OFFSET ?""",
            (editor, keep),
        )
    ]
    for machine in victims:
        conn.execute(
            "DELETE FROM machine_state WHERE editor_username=? AND machine=?",
            (editor, machine),
        )
    return len(victims)


def editor_reported_resolve_project(
    conn: sqlite3.Connection, editor: str, resolve_project: str
) -> bool:
    """True when one of THIS editor's machines has actually reported having
    this Resolve project open.

    Gate on the first-claim paths (PUT /project-roots, the /project-setup
    create+link flows): without it any signed-in editor could first-claim any
    unmapped Resolve project name -- including one only another editor's
    companion has ever reported -- and permanently fix where that editor's
    media gets written. Admins are exempt (they own the mapping table)."""
    name = (resolve_project or "").strip()
    if not name or not editor:
        return False
    row = conn.execute(
        """SELECT 1 FROM machine_state
           WHERE editor_username=? AND resolve_project IS NOT NULL
             AND TRIM(resolve_project) = ? COLLATE NOCASE LIMIT 1""",
        (editor, name),
    ).fetchone()
    return row is not None


def fetch_platform_map(conn: sqlite3.Connection) -> dict[tuple[str, str], str | None]:
    """(editor, machine) -> last-reported platform, or None if never reported
    (build_editors_view falls back to 'windows' for those -- see X-5)."""
    return {
        (r["editor_username"], r["machine"]): r["platform"]
        for r in conn.execute("SELECT editor_username, machine, platform FROM machine_state")
    }


def fetch_companion_version_map(
    conn: sqlite3.Connection,
) -> dict[tuple[str, str], dict[str, Any]]:
    """(editor, machine) -> {"companion_version", "platform", "reported_at"}.

    Survives a lane_report_current prune, so a machine that has gone quiet
    still shows the build it was last running (see the release-hygiene fleet
    view). companion_version is None for pre-v10 reports."""
    return {
        (r["editor_username"], r["machine"]): {
            "companion_version": r["companion_version"],
            "platform": r["platform"],
            "reported_at": r["reported_at"],
        }
        for r in conn.execute(
            "SELECT editor_username, machine, companion_version, platform, reported_at "
            "FROM machine_state"
        )
    }


def fetch_verified_map(conn: sqlite3.Connection) -> dict[tuple[str, str], bool]:
    return {
        (r["editor_username"], r["machine"]): bool(r["verified"])
        for r in conn.execute("SELECT editor_username, machine, verified FROM machine_state")
    }


def latest_machine_state(conn: sqlite3.Connection, editor: str):
    return conn.execute(
        """SELECT * FROM machine_state WHERE editor_username=?
           ORDER BY reported_at DESC LIMIT 1""",
        (editor,),
    ).fetchone()


def _label_tokens(text: str) -> set[str]:
    """Lowercase alnum tokens that carry identity.

    Tokens that carry no identity NEVER count: 4-digit years (a name
    containing "2026" is not evidence it belongs to every 2026 project) and
    short bare numbers ("1", "2" -- season/part counters). Without the
    latter rule, "Event 1 Videos" auto-matched "2026/Creator Profiles/
    Season 1" on the shared "1" alone and the sticky mapping wedged it
    there (seen live 2026-07-25)."""
    return {
        t for t in re.split(r"[^a-z0-9]+", text.lower())
        # all-digit tokens up to year length; any token with a letter is kept
        if t and not (t.isdigit() and len(t) <= 4)
    }


def match_project_label(resolve_project: str, labels: Iterable[str]) -> str | None:
    """Match a Resolve project name to a tree project label
    ("year/series/project"). Mirrors the companion's fixer.match_project_dir:
    lowercase alnum token overlap, best score wins, tie -> None.

    This is the LOOSE matcher and is only safe where a wrong answer is
    cheap. Anything that writes a permanent sticky mapping must go through
    match_project_label_confident instead."""
    name_tokens = _label_tokens(resolve_project)
    if not name_tokens:
        return None
    best: list[str] = []
    best_score = 0
    for label in labels:
        overlap = name_tokens & _label_tokens(label)
        score = len(overlap)
        if score == 0:
            continue
        if score > best_score:
            best, best_score = [label], score
        elif score == best_score:
            best.append(label)
    return best[0] if len(best) == 1 else None


def match_project_label_confident(
    resolve_project: str, labels: Iterable[str]
) -> str | None:
    """match_project_label, but only when the evidence is strong enough to
    write a PERMANENT, GLOBAL, sticky mapping nobody but an admin can change.

    match_project_label alone returns a winner on ONE shared non-trivial
    token, which is how "Nuclear Family Reunion" auto-mapped to
    "2025/FF4/Nuclear" on the token "nuclear" (verified 2026-07-25): every
    frame that editor shot then had a permanent destination inside an
    unrelated project. A single word is a coincidence, not a match, so the
    auto-map now requires one of:

      (a) at least MIN_CONFIDENT_TOKENS shared non-trivial tokens, or
      (b) the normalized Resolve name IS the project -- equal to the label's
          final path segment, or to the whole label.

    Below the threshold nothing is written: the report reply carries
    resolve_project_unmapped and a human picks the folder in /project-setup.
    """
    match = match_project_label(resolve_project, labels)
    if match is None:
        return None
    if len(_label_tokens(resolve_project) & _label_tokens(match)) >= MIN_CONFIDENT_TOKENS:
        return match
    # (b) exact-identity: "Season 2" for ".../CCT/Season 2", or the whole rel.
    name_key = " ".join(str(resolve_project or "").split()).casefold()
    segments = [s for s in str(match).replace("\\", "/").split("/") if s]
    candidates = {str(match).casefold()}
    if segments:
        candidates.add(segments[-1].casefold())
    return match if name_key in candidates else None


def sticky_project_root(
    conn: sqlite3.Connection,
    resolve_project: str,
    slug: str,
    now: str,
    source: str = "auto",
    updated_by: str = "auto",
) -> bool:
    """Store the FIRST mapping for a Resolve project. No-op if a mapping
    already exists (fixed once set). Returns True if inserted. INSERT OR
    IGNORE means two concurrent first-sets can't both win -- the loser gets
    False and should surface "already mapped". `source`/`updated_by` default
    to the original auto-match behavior; the /project-setup first-set path
    passes source="editor" with the editor's username."""
    resolve_project = resolve_project.strip()
    if not resolve_project or not slug:
        return False
    cur = conn.execute(
        """INSERT OR IGNORE INTO project_roots
             (resolve_project, project_slug, source, updated_at, updated_by)
           VALUES (?, ?, ?, ?, ?)""",
        (resolve_project, slug, source, now, updated_by),
    )
    return cur.rowcount > 0


def admin_set_project_root(
    conn: sqlite3.Connection, resolve_project: str, slug: str, admin: str, now: str
) -> None:
    conn.execute(
        """INSERT INTO project_roots (resolve_project, project_slug, source, updated_at, updated_by)
           VALUES (?, ?, 'admin', ?, ?)
           ON CONFLICT(resolve_project) DO UPDATE SET
             project_slug=excluded.project_slug, source='admin',
             updated_at=excluded.updated_at, updated_by=excluded.updated_by""",
        (resolve_project.strip(), slug, now, admin),
    )


def delete_project_root(conn: sqlite3.Connection, resolve_project: str) -> bool:
    cur = conn.execute(
        "DELETE FROM project_roots WHERE resolve_project=?", (resolve_project.strip(),)
    )
    return cur.rowcount > 0


def fetch_project_roots(conn: sqlite3.Connection) -> list[dict[str, Any]]:
    return [dict(r) for r in conn.execute(
        "SELECT * FROM project_roots ORDER BY resolve_project COLLATE NOCASE"
    )]


def fetch_unmapped_resolve_projects(conn: sqlite3.Connection) -> list[str]:
    """Resolve projects companions have reported that have no stored root."""
    return [r[0] for r in conn.execute(
        """SELECT DISTINCT resolve_project FROM machine_state
           WHERE resolve_project IS NOT NULL
             AND resolve_project NOT IN (SELECT resolve_project FROM project_roots)
           ORDER BY resolve_project COLLATE NOCASE"""
    )]


def get_detected_project_root(conn: sqlite3.Connection, editor: str) -> str | None:
    """Most recently reported auto-detected root across the editor's machines."""
    row = conn.execute(
        """SELECT detected_project_root FROM machine_state
           WHERE editor_username=? AND detected_project_root IS NOT NULL
           ORDER BY reported_at DESC LIMIT 1""",
        (editor,),
    ).fetchone()
    return row["detected_project_root"] if row else None


def record_poll_run(
    conn: sqlite3.Connection,
    kind: str,
    started_at: str,
    finished_at: str | None,
    ok: bool,
    error: str | None,
) -> None:
    conn.execute(
        "INSERT INTO poll_runs (kind, started_at, finished_at, ok, error) VALUES (?, ?, ?, ?, ?)",
        (kind, started_at, finished_at, int(ok), error),
    )


def prune(conn: sqlite3.Connection, now: str) -> None:
    def cutoff(days: int = 0, hours: int = 0, seconds: int = 0) -> str:
        return (parse_iso(now) - dt.timedelta(days=days, hours=hours, seconds=seconds)).isoformat()

    conn.execute("DELETE FROM completion_history WHERE ts < ?", (cutoff(days=HISTORY_MAX_AGE_DAYS),))
    conn.execute("DELETE FROM transfer_history WHERE received_at < ?", (cutoff(days=7),))
    # Thin rows older than 48h to one per (pair, hour); substr(ts,1,13) = YYYY-MM-DDTHH.
    conn.execute(
        """DELETE FROM completion_history WHERE ts < ? AND id NOT IN (
             SELECT MIN(id) FROM completion_history WHERE ts < ?
             GROUP BY project_id, device_id, substr(ts, 1, 13))""",
        (cutoff(hours=HISTORY_THIN_AFTER_HOURS), cutoff(hours=HISTORY_THIN_AFTER_HOURS)),
    )
    conn.execute(
        "DELETE FROM lane_report_history WHERE ts < ?", (cutoff(days=LANE_HISTORY_MAX_AGE_DAYS),)
    )
    # A machine that stopped reporting entirely (uninstalled, retired, or a
    # single bad report with a runaway lane count -- see SEC-4) must not keep
    # its lane_report_current rows forever; there was previously no retention
    # on this table at all.
    conn.execute(
        "DELETE FROM lane_report_current WHERE received_at < ?",
        (cutoff(days=LANE_HISTORY_MAX_AGE_DAYS),),
    )
    # machine_state had no retention at all, and `machine` is an
    # attacker-chosen string on an unthrottled endpoint: a retired (or bogus)
    # machine must age out of the fleet grid exactly like its lane rows do.
    # The write-time cap (evict_extra_machines) bounds the burst; this bounds
    # the long tail.
    conn.execute(
        "DELETE FROM machine_state WHERE reported_at < ?",
        (cutoff(days=MACHINE_STATE_MAX_AGE_DAYS),),
    )
    conn.execute(
        "DELETE FROM missing_files WHERE refreshed_at < ?",
        (cutoff(days=MISSING_FILES_MAX_AGE_DAYS),),
    )
    conn.execute(
        """DELETE FROM poll_runs WHERE id NOT IN
             (SELECT id FROM poll_runs ORDER BY id DESC LIMIT ?)""",
        (POLL_RUNS_KEEP,),
    )
    # Media-presence tables: drop an editor's rows after it stops reporting,
    # and expire stale live transfers.
    media_cutoff = cutoff(days=MEDIA_REPORT_MAX_AGE_DAYS)
    conn.execute("DELETE FROM editor_media_project WHERE reported_at < ?", (media_cutoff,))
    conn.execute("DELETE FROM editor_media WHERE refreshed_at < ?", (media_cutoff,))
    conn.execute("DELETE FROM media_tree_clips WHERE refreshed_at < ?", (media_cutoff,))
    conn.execute(
        "DELETE FROM active_transfers WHERE updated_at < ?",
        (cutoff(seconds=ACTIVE_TRANSFER_STALE_SECONDS),),
    )
    purge_nas_media_for_inactive(conn)


def purge_nas_media_for_inactive(conn: sqlite3.Connection) -> None:
    """Drop NAS inventory for projects that are no longer active (folder
    removed from Syncthing config)."""
    for table in ("nas_media", "nas_inventory_state"):
        conn.execute(
            f"DELETE FROM {table} WHERE project_id NOT IN "
            "(SELECT id FROM projects WHERE active=1)"
        )


# ---------------------------------------------------------------- media presence writes

def replace_nas_media(
    conn: sqlite3.Connection,
    project_id: int,
    rows: list[tuple[str, str, str, int | None, int | None]],
    tree_sig: str,
    n_dirs: int,
    now: str,
) -> None:
    """rows: [(rel_path, kind, ext, size, mtime_ns)]. Replaces the project's
    inventory and recomputes the rollup in nas_inventory_state."""
    conn.execute("DELETE FROM nas_media WHERE project_id=?", (project_id,))
    conn.executemany(
        """INSERT OR REPLACE INTO nas_media
             (project_id, rel_path, kind, ext, size, mtime_ns, refreshed_at)
           VALUES (?, ?, ?, ?, ?, ?, ?)""",
        [(project_id, rel, kind, ext, size, mtime, now) for rel, kind, ext, size, mtime in rows],
    )
    n_orig = sum(1 for r in rows if r[1] == "original")
    b_orig = sum((r[3] or 0) for r in rows if r[1] == "original")
    n_prox = sum(1 for r in rows if r[1] == "proxy")
    b_prox = sum((r[3] or 0) for r in rows if r[1] == "proxy")
    conn.execute(
        """INSERT INTO nas_inventory_state
             (project_id, tree_sig, n_dirs, n_originals, bytes_originals,
              n_proxies, bytes_proxies, walked_at, last_error)
           VALUES (?, ?, ?, ?, ?, ?, ?, ?, NULL)
           ON CONFLICT(project_id) DO UPDATE SET
             tree_sig=excluded.tree_sig, n_dirs=excluded.n_dirs,
             n_originals=excluded.n_originals, bytes_originals=excluded.bytes_originals,
             n_proxies=excluded.n_proxies, bytes_proxies=excluded.bytes_proxies,
             walked_at=excluded.walked_at, last_error=NULL""",
        (project_id, tree_sig, n_dirs, n_orig, b_orig, n_prox, b_prox, now),
    )


def nas_inventory_sig(conn: sqlite3.Connection, project_id: int) -> str | None:
    row = conn.execute(
        "SELECT tree_sig FROM nas_inventory_state WHERE project_id=?", (project_id,)
    ).fetchone()
    return row["tree_sig"] if row else None


def record_inventory_error(conn: sqlite3.Connection, project_id: int, error: str, now: str) -> None:
    conn.execute(
        """INSERT INTO nas_inventory_state (project_id, walked_at, last_error)
           VALUES (?, ?, ?)
           ON CONFLICT(project_id) DO UPDATE SET walked_at=excluded.walked_at,
             last_error=excluded.last_error""",
        (project_id, now, error),
    )


def upsert_editor_media_project(
    conn: sqlite3.Connection, *, editor: str, machine: str, slug: str, mode: str,
    n_originals: int, bytes_originals: int, n_proxies: int, bytes_proxies: int,
    truncated: bool, now: str,
) -> None:
    conn.execute(
        """INSERT INTO editor_media_project
             (editor_username, machine, project_slug, mode, n_originals, bytes_originals,
              n_proxies, bytes_proxies, truncated, reported_at)
           VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
           ON CONFLICT(editor_username, machine, project_slug) DO UPDATE SET
             mode=excluded.mode, n_originals=excluded.n_originals,
             bytes_originals=excluded.bytes_originals, n_proxies=excluded.n_proxies,
             bytes_proxies=excluded.bytes_proxies, truncated=excluded.truncated,
             reported_at=excluded.reported_at""",
        (editor, machine, slug, mode, n_originals, bytes_originals, n_proxies,
         bytes_proxies, int(truncated), now),
    )


def replace_editor_media(
    conn: sqlite3.Connection, editor: str, machine: str, slug: str,
    files: list[tuple[str, str, int | None]], now: str,
) -> None:
    """files: [(rel_path, kind, size)], capped at EDITOR_MEDIA_CAP."""
    conn.execute(
        "DELETE FROM editor_media WHERE editor_username=? AND machine=? AND project_slug=?",
        (editor, machine, slug),
    )
    conn.executemany(
        """INSERT OR REPLACE INTO editor_media
             (editor_username, machine, project_slug, rel_path, kind, size, refreshed_at)
           VALUES (?, ?, ?, ?, ?, ?, ?)""",
        [(editor, machine, slug, rel, kind, size, now)
         for rel, kind, size in files[:EDITOR_MEDIA_CAP]],
    )


def replace_media_tree(
    conn: sqlite3.Connection, editor: str, machine: str, slug: str,
    clips: list[tuple[str, str, str | None, str | None, bool]], now: str,
) -> None:
    """clips: [(bin_path, clip_name, file_path, kind, present)], capped at MEDIA_TREE_CAP."""
    conn.execute(
        "DELETE FROM media_tree_clips WHERE editor_username=? AND machine=? AND project_slug=?",
        (editor, machine, slug),
    )
    conn.executemany(
        """INSERT OR REPLACE INTO media_tree_clips
             (editor_username, machine, project_slug, bin_path, clip_name, file_path,
              kind, present, refreshed_at)
           VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)""",
        [(editor, machine, slug, bin_path, clip_name, file_path, kind, int(present), now)
         for bin_path, clip_name, file_path, kind, present in clips[:MEDIA_TREE_CAP]],
    )


def replace_active_transfers(
    conn: sqlite3.Connection, editor: str, machine: str,
    rows: list[dict[str, Any]], now: str,
) -> None:
    """Replace ALL of this (editor, machine)'s live transfers. An empty list
    clears them (transfer finished / lanes idle)."""
    conn.execute(
        "DELETE FROM active_transfers WHERE editor_username=? AND machine=?", (editor, machine)
    )
    conn.executemany(
        """INSERT OR REPLACE INTO active_transfers
             (editor_username, machine, lane, name, direction, bytes_done, bytes_total,
              percentage, speed_bps, eta_seconds, project_slug, updated_at)
           VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
        [(editor, machine, r["lane"], r["name"], r.get("direction", ""),
          r.get("bytes_done"), r.get("bytes_total"), r.get("percentage"),
          r.get("speed_bps"), r.get("eta_seconds"), r.get("project_slug"), now)
         for r in rows],
    )


# ---------------------------------------------------------------- media presence reads

def fetch_nas_media_summary(conn: sqlite3.Connection, project_id: int) -> dict[str, int]:
    row = conn.execute(
        """SELECT n_originals, bytes_originals, n_proxies, bytes_proxies
           FROM nas_inventory_state WHERE project_id=?""",
        (project_id,),
    ).fetchone()
    if row is None:
        return {"n_originals": 0, "bytes_originals": 0, "n_proxies": 0, "bytes_proxies": 0}
    return dict(row)


def fetch_editor_media_for_project(
    conn: sqlite3.Connection, slug: str, editor: str | None = None
) -> list[dict[str, Any]]:
    """Per (editor, machine) disk rollups for a project. editor filters to one."""
    q = "SELECT * FROM editor_media_project WHERE project_slug=?"
    params: list[Any] = [slug]
    if editor is not None:
        q += " AND editor_username=?"
        params.append(editor)
    return [dict(r) for r in conn.execute(q + " ORDER BY editor_username, machine", params)]


def fetch_media_tree_keys(
    conn: sqlite3.Connection, slug: str, editor: str | None = None
) -> list[tuple[str, str]]:
    """Distinct (editor, machine) that have reported a bin tree for a project
    but may have no disk-manifest rollup row."""
    q = "SELECT DISTINCT editor_username, machine FROM media_tree_clips WHERE project_slug=?"
    params: list[Any] = [slug]
    if editor is not None:
        q += " AND editor_username=?"
        params.append(editor)
    return [(r["editor_username"], r["machine"]) for r in conn.execute(q, params)]


def fetch_media_tree(
    conn: sqlite3.Connection, editor: str, machine: str, slug: str, now: str
) -> dict[str, Any]:
    """Bins -> clips for one editor/machine/project, with per-clip online +
    uploading (matched against fresh active_transfers by filename)."""
    uploading = {
        r["name"] for r in conn.execute(
            """SELECT name FROM active_transfers
               WHERE editor_username=? AND machine=? AND updated_at >= ?""",
            (editor, machine, _iso_minus(now, ACTIVE_TRANSFER_STALE_SECONDS)),
        )
    }
    bins: dict[str, dict[str, Any]] = {}
    for r in conn.execute(
        """SELECT bin_path, clip_name, file_path, kind, present FROM media_tree_clips
           WHERE editor_username=? AND machine=? AND project_slug=?
           ORDER BY bin_path, clip_name""",
        (editor, machine, slug),
    ):
        b = bins.setdefault(r["bin_path"], {"bin_path": r["bin_path"], "clips": [],
                                            "present": 0, "total": 0})
        base = (r["file_path"] or "").replace("\\", "/").rsplit("/", 1)[-1]
        is_up = base in uploading
        b["clips"].append({
            "clip_name": r["clip_name"], "file_path": r["file_path"], "kind": r["kind"],
            "present": bool(r["present"]), "uploading": is_up,
        })
        b["total"] += 1
        if r["present"]:
            b["present"] += 1
    return {"bins": [bins[k] for k in sorted(bins)]}


def _iso_minus(now: str, seconds: int) -> str:
    return (parse_iso(now) - dt.timedelta(seconds=seconds)).isoformat()


def fetch_active_transfers(
    conn: sqlite3.Connection, now: str, editor: str | None = None
) -> list[dict[str, Any]]:
    q = "SELECT * FROM active_transfers WHERE updated_at >= ?"
    params: list[Any] = [_iso_minus(now, ACTIVE_TRANSFER_STALE_SECONDS)]
    if editor is not None:
        q += " AND editor_username=?"
        params.append(editor)
    return [dict(r) for r in conn.execute(q + " ORDER BY speed_bps DESC", params)]


# ---------------------------------------------------------------- reads

def fetch_projects(conn: sqlite3.Connection) -> list[dict[str, Any]]:
    """All active projects with their per-device completion rows attached."""
    projects = [dict(r) for r in conn.execute(
        "SELECT * FROM projects WHERE active=1 ORDER BY label"
    )]
    for p in projects:
        p["editors"] = fetch_project_editors(conn, p["id"])
    return projects


def fetch_project(conn: sqlite3.Connection, slug: str) -> dict[str, Any] | None:
    row = conn.execute("SELECT * FROM projects WHERE slug=?", (slug,)).fetchone()
    if row is None:
        return None
    project = dict(row)
    project["editors"] = fetch_project_editors(conn, project["id"])
    return project


def fetch_project_editors(conn: sqlite3.Connection, project_id: int) -> list[dict[str, Any]]:
    """One row per non-server device sharing this folder, with completion and
    the device identity; lane reports are joined in by the caller via
    fetch_lane_reports (keyed on editor_username)."""
    rows = conn.execute(
        """SELECT d.id AS device_row_id, d.device_id, d.name, d.editor_username,
                  d.connected, d.address, d.last_connected_at,
                  c.completion, c.need_items, c.need_bytes, c.need_deletes,
                  c.global_items, c.global_bytes, c.rate_bytes_per_sec, c.updated_at
           FROM completion_current c
           JOIN devices d ON d.id = c.device_id
           WHERE c.project_id = ? AND d.is_server = 0
           ORDER BY COALESCE(d.editor_username, d.name)""",
        (project_id,),
    )
    return [dict(r) for r in rows]


def prune_completion_not_shared(
    conn: sqlite3.Connection, valid_pairs: list[tuple[int, int]]
) -> int:
    """Delete completion_current + missing_files rows for (project, device)
    pairs Syncthing no longer shares.

    The collector only ever UPSERTS completion rows for currently-shared
    pairs, so an untick (or a device removed from a folder) left the last
    row behind forever -- surfacing as phantom sidebar editors-behind marks
    and, worse, phantom [ QUEUED ] entries for projects the machine no
    longer syncs (44 GB of "lane C need" from a long-gone misconfiguration,
    2026-07-26). Returns the number of pairs removed."""
    keep = set(valid_pairs)
    victims = [
        (r["project_id"], r["device_id"])
        for r in conn.execute("SELECT project_id, device_id FROM completion_current")
        if (r["project_id"], r["device_id"]) not in keep
    ]
    for project_id, device_id in victims:
        conn.execute("DELETE FROM completion_current WHERE project_id=? AND device_id=?",
                     (project_id, device_id))
        conn.execute("DELETE FROM missing_files WHERE project_id=? AND device_id=?",
                     (project_id, device_id))
    return len(victims)


TRANSFER_HISTORY_CAP_PER_MACHINE = 300


def add_transfer_history(
    conn: sqlite3.Connection, editor: str, machine: str, entries: list[dict[str, Any]],
    now: str,
) -> None:
    """Append completed-file events, keeping only the newest
    TRANSFER_HISTORY_CAP_PER_MACHINE rows per (editor, machine)."""
    for e in entries:
        conn.execute(
            """INSERT INTO transfer_history
                 (editor_username, machine, lane, name, direction, completed_at, received_at)
               VALUES (?, ?, ?, ?, ?, ?, ?)""",
            (editor, machine, str(e.get("lane") or ""), str(e.get("name") or ""),
             str(e.get("direction") or ""), str(e.get("at") or now), now),
        )
    if entries:
        conn.execute(
            """DELETE FROM transfer_history WHERE editor_username=? AND machine=?
               AND id NOT IN (SELECT id FROM transfer_history
                              WHERE editor_username=? AND machine=?
                              ORDER BY id DESC LIMIT ?)""",
            (editor, machine, editor, machine, TRANSFER_HISTORY_CAP_PER_MACHINE),
        )


def fetch_transfer_history(
    conn: sqlite3.Connection, editor: str | None = None, limit: int = 50
) -> list[dict[str, Any]]:
    q = "SELECT * FROM transfer_history"
    params: list[Any] = []
    if editor is not None:
        q += " WHERE editor_username=?"
        params.append(editor)
    q += " ORDER BY id DESC LIMIT ?"
    params.append(limit)
    return [dict(r) for r in conn.execute(q, params)]


def fetch_sync_backlog(
    conn: sqlite3.Connection, editor: str | None = None, files_per_group: int = 50
) -> list[dict[str, Any]]:
    """File-level lane A/B backlog per (editor, machine, project): what the
    machine still needs from the NAS (proxies, lane B down) and what it
    holds that the NAS lacks (originals, lane A up) -- the rel_path diff of
    `nas_media` against `editor_media`.

    Scope: machines that have reported a per-file manifest for a SELECTED
    project (an editor_media_project row proves a manifest arrived; without
    one, "everything is missing" would just mean "no data yet"). Base-mode
    machines are excluded -- the base rig IS the NAS tree. Numbers are as
    fresh as the inputs: the NAS inventory walk (<= ~15 min) and the heavy
    report's manifest (<= ~5 min), and files currently mid-transfer (at most
    rclone's --transfers per lane) still count as queued until the next
    manifest refresh. `files_per_group` caps the per-group name list only;
    n_files/bytes are full totals."""
    pair_q = """SELECT emp.editor_username AS editor, emp.machine,
                       emp.project_slug AS slug, emp.truncated,
                       p.id AS project_id, p.label
                FROM editor_media_project emp
                JOIN selections s ON s.editor_username = emp.editor_username
                                 AND s.project_slug = emp.project_slug
                JOIN projects p ON p.slug = emp.project_slug AND p.active = 1
                WHERE emp.mode != 'base'"""
    params: list[Any] = []
    if editor is not None:
        pair_q += " AND emp.editor_username = ?"
        params.append(editor)
    pair_q += " ORDER BY emp.editor_username, emp.machine, p.label"

    down_totals_q = """SELECT COUNT(*), COALESCE(SUM(n.size), 0) FROM nas_media n
                       WHERE n.project_id=? AND n.kind='proxy'
                         AND NOT EXISTS (SELECT 1 FROM editor_media e
                                         WHERE e.editor_username=? AND e.machine=?
                                           AND e.project_slug=? AND e.rel_path=n.rel_path)"""
    down_files_q = down_totals_q.replace(
        "SELECT COUNT(*), COALESCE(SUM(n.size), 0)", "SELECT n.rel_path, n.size"
    ) + " ORDER BY n.rel_path LIMIT ?"
    up_totals_q = """SELECT COUNT(*), COALESCE(SUM(e.size), 0) FROM editor_media e
                     WHERE e.editor_username=? AND e.machine=? AND e.project_slug=?
                       AND e.kind='original'
                       AND NOT EXISTS (SELECT 1 FROM nas_media n
                                       WHERE n.project_id=? AND n.rel_path=e.rel_path)"""
    up_files_q = up_totals_q.replace(
        "SELECT COUNT(*), COALESCE(SUM(e.size), 0)", "SELECT e.rel_path, e.size"
    ) + " ORDER BY e.rel_path LIMIT ?"

    out: list[dict[str, Any]] = []
    for pair in conn.execute(pair_q, params):
        specs = [
            ("down", "proxy",
             (pair["project_id"], pair["editor"], pair["machine"], pair["slug"]),
             down_totals_q, down_files_q),
            ("up", "original",
             (pair["editor"], pair["machine"], pair["slug"], pair["project_id"]),
             up_totals_q, up_files_q),
        ]
        for direction, kind, args, totals_q, files_q in specs:
            n_files, total_bytes = conn.execute(totals_q, args).fetchone()
            if not n_files:
                continue
            files = [{"name": r[0], "size": r[1]}
                     for r in conn.execute(files_q, (*args, files_per_group))]
            out.append({
                "editor": pair["editor"], "machine": pair["machine"],
                "slug": pair["slug"], "label": pair["label"],
                "lane": "a" if direction == "up" else "b",
                "direction": direction, "kind": kind,
                "n_files": int(n_files), "bytes": int(total_bytes),
                "files": files, "truncated": int(n_files) > len(files),
                # The manifest itself was capped: the diff may UNDERCOUNT.
                "manifest_truncated": bool(pair["truncated"]),
            })
    return out


def fetch_missing(
    conn: sqlite3.Connection, project_id: int, device_row_id: int
) -> dict[str, Any]:
    rows = [dict(r) for r in conn.execute(
        """SELECT name, size, truncated, refreshed_at FROM missing_files
           WHERE project_id=? AND device_id=? ORDER BY name""",
        (project_id, device_row_id),
    )]
    return {
        "files": [{"name": r["name"], "size": r["size"]} for r in rows],
        "truncated": bool(rows and rows[0]["truncated"]),
        "refreshed_at": rows[0]["refreshed_at"] if rows else None,
    }


def fetch_lane_reports(conn: sqlite3.Connection) -> list[dict[str, Any]]:
    return [dict(r) for r in conn.execute(
        "SELECT * FROM lane_report_current ORDER BY editor_username, machine, lane"
    )]


def fetch_collector_status(
    conn: sqlite3.Connection, now: str | None = None,
    stale_after_seconds: float = COLLECTOR_STALE_SECONDS,
) -> dict[str, Any]:
    """Last poll_runs row per kind, plus overall syncthing reachability and
    any Syncthing folder-level errors.

    `syncthing_reachable` is True only when the most recent Syncthing-backed
    run succeeded AND it finished recently. Without the staleness check, a
    collector thread that died before entering its guarded loop (nothing
    restarts it) left /api/v1/health reporting ok forever off a poll run from
    hours ago -- see the syncthing_reachable staleness finding."""
    now = now or utcnow_iso()
    kinds: dict[str, dict[str, Any]] = {}
    for row in conn.execute(
        """SELECT p.* FROM poll_runs p
           JOIN (SELECT kind, MAX(id) AS id FROM poll_runs GROUP BY kind) m ON m.id = p.id"""
    ):
        kinds[row["kind"]] = dict(row)
    # 'prune' is the one kind that also runs in a Syncthing-less deployment,
    # so it can never be evidence that Syncthing is reachable.
    latest = conn.execute(
        "SELECT ok, finished_at FROM poll_runs WHERE kind <> 'prune' ORDER BY id DESC LIMIT 1"
    ).fetchone()
    reachable = bool(latest["ok"]) if latest is not None else False
    stale = False
    if reachable and latest["finished_at"]:
        try:
            stale = age_seconds(latest["finished_at"], now) >= stale_after_seconds
        except ValueError:
            stale = False
        if stale:
            reachable = False
    folder_errors = [
        dict(r) for r in conn.execute(
            """SELECT slug, label, folder_state, folder_error, folder_state_at
               FROM projects
               WHERE active=1 AND (folder_error IS NOT NULL
                                   OR folder_state IN ('error', 'stopped'))
               ORDER BY label"""
        )
    ]
    return {
        "kinds": kinds,
        "syncthing_reachable": reachable,
        "collector_stale": stale,
        "folder_errors": folder_errors,
    }
