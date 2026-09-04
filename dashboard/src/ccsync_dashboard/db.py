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
import logging
import re
import secrets
import sqlite3
import unicodedata
from pathlib import Path
from typing import Any, Container, Iterable, Mapping

SCHEMA_PATH = Path(__file__).with_name("schema.sql")

# This layer is deliberately silent: it is data, and every caller of it owns
# the sentence a human reads. The ONE exception is a decision this module
# makes on its own and nobody above it can see -- the machine cap's refusal
# to evict a registry row that still owes a plan or a share (DCORE-12,
# 2026-09-04), which is reached from inside a write helper and used to be
# invisible everywhere: no notice, no audit, no log line at all.
log = logging.getLogger("ccsync.dashboard.db")

# Caps + retention for the media-presence tables.
EDITOR_MEDIA_CAP = 2000          # per-file disk-manifest rows per (editor, machine, project)
MEDIA_TREE_CAP = 4000            # Resolve-bin clip rows per (editor, machine, project)
MEDIA_REPORT_MAX_AGE_DAYS = 14   # drop an editor's media rows after it stops reporting
ACTIVE_TRANSFER_STALE_SECONDS = 120  # a transfer row is "live" only this long past updated_at
JOBS_MAX_AGE_DAYS = 30           # how long a FINISHED fleet job is kept (v41)

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
# (ZERO_TOUCH_PLAN.md WP D, 2026-08-17).
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

# v19: the vendor release feed's client-side state (ZERO_TOUCH_PLAN.md WP E,
# 2026-08-17). "we publish once, every dashboard pulls" needs somewhere to
# remember the last poll -- otherwise a restart forgets whether the feed was
# ever reachable and the admin page has nothing to show before the first
# click. Singleton row (id=1, CHECK-enforced) rather than a `meta` key: this
# is a small, typed, frequently-read shape, not a scalar.
#
#   last_checked_at            when check_now() last ran (success OR failure)
#   last_error                 '' on success; the refusal reason otherwise --
#                               never surfaced to anyone but an admin, and
#                               NEVER a reason to serve unverified content
#   last_channel_generated_at  the feed's own `generated_at`, for "is this
#                               stale" without re-fetching
#   etag                       reserved for a future conditional GET; unused
#                               today (release_feed.py has no server to
#                               support If-None-Match against yet)
#   policy_override             '' = use DASH_RELEASE_FEED_POLICY; otherwise
#                               one of manual/stage/current, set from the
#                               admin page without a redeploy
SCHEMA_V19 = """
CREATE TABLE IF NOT EXISTS feed_state (
  id                         INTEGER PRIMARY KEY CHECK (id = 1),
  last_checked_at            TEXT,
  last_error                 TEXT,
  last_channel_generated_at  TEXT,
  etag                       TEXT,
  policy_override            TEXT
);
"""

# v20: b-roll ingest, flattened onto machine_state (BROLL_INGEST_PLAN.md §3.2,
# 2026-08-18). "which computers are indexing and their progress" is a fleet
# question the grid answers, so the companion's `broll_ingest` report section
# gets columns for the same reason v13's transport and v16's latches did: the
# grid sorts and alarms on this, and a JSON blob cannot be asked "who is
# indexing right now".
#
# `ingest_active` is written on EVERY report, not COALESCEd, and goes back to
# 0 when the section is absent -- the reporter omits an empty section, so
# "the batch finished" is spelled by silence and a latched 1 would leave a
# machine indexing forever on the grid (same lesson as halt_active/v16).
# `ingest_warning` carries the insufficient-VRAM refusal, which the owner
# asked to be visible even when nothing is running (§0 owner review (c)) --
# so it is shown by its own chip and survives `active` going false.
#
# proxy_missing/proxy_state/proxy_left come from the SAME fix: ReportIn never
# declared `proxy_coverage`, so every machine's missing-proxy count has been
# dropped on the floor since the generator shipped. Cheap to store now that
# the section is parsed at all.
SCHEMA_V20 = """
ALTER TABLE machine_state ADD COLUMN ingest_active INTEGER;
ALTER TABLE machine_state ADD COLUMN ingest_batch TEXT;
ALTER TABLE machine_state ADD COLUMN ingest_state TEXT;
ALTER TABLE machine_state ADD COLUMN ingest_gate TEXT;
ALTER TABLE machine_state ADD COLUMN ingest_done INTEGER;
ALTER TABLE machine_state ADD COLUMN ingest_total INTEGER;
ALTER TABLE machine_state ADD COLUMN ingest_failed INTEGER;
ALTER TABLE machine_state ADD COLUMN ingest_clip TEXT;
ALTER TABLE machine_state ADD COLUMN ingest_percent INTEGER;
ALTER TABLE machine_state ADD COLUMN ingest_tier TEXT;
ALTER TABLE machine_state ADD COLUMN ingest_warning TEXT;
ALTER TABLE machine_state ADD COLUMN ingest_at TEXT;
ALTER TABLE machine_state ADD COLUMN proxy_missing INTEGER;
ALTER TABLE machine_state ADD COLUMN proxy_state TEXT;
ALTER TABLE machine_state ADD COLUMN proxy_left INTEGER;
"""

# v21: music ingest, flattened onto machine_state exactly as v20 did for
# b-roll (docs/MUSIC_INGEST_PLAN.md step 3, 2026-08-18). A SECOND set of
# columns rather than a `kind` discriminator on v20's, because the two run at
# the same time: music needs no GPU, so a machine can be embedding an album
# while it indexes a camera card, and one row per machine has to be able to
# say both.
#
# `music_ingest_active` follows v20's rule and its reason: written on EVERY
# report, never COALESCEd, back to 0 when the section is absent -- the
# reporter omits an empty section, so "the batch finished" is spelled by
# silence and a latched 1 would leave a machine indexing forever on the grid.
#
# No `tier` column, deliberately: music has one model and nothing to choose,
# so the column would be empty on every row that ever existed.
SCHEMA_V21 = """
ALTER TABLE machine_state ADD COLUMN music_ingest_active INTEGER;
ALTER TABLE machine_state ADD COLUMN music_ingest_batch TEXT;
ALTER TABLE machine_state ADD COLUMN music_ingest_state TEXT;
ALTER TABLE machine_state ADD COLUMN music_ingest_gate TEXT;
ALTER TABLE machine_state ADD COLUMN music_ingest_done INTEGER;
ALTER TABLE machine_state ADD COLUMN music_ingest_total INTEGER;
ALTER TABLE machine_state ADD COLUMN music_ingest_failed INTEGER;
ALTER TABLE machine_state ADD COLUMN music_ingest_track TEXT;
ALTER TABLE machine_state ADD COLUMN music_ingest_percent INTEGER;
ALTER TABLE machine_state ADD COLUMN music_ingest_warning TEXT;
ALTER TABLE machine_state ADD COLUMN music_ingest_at TEXT;
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

# The collector kinds that run even in a Syncthing-less deployment, so a run of
# one of them is NOT evidence that Syncthing is reachable. It lives here rather
# than in collector.py (which re-exports it) because BOTH sides have to agree:
# collector.run_cycle uses it to decide what still runs without a Syncthing
# URL, and fetch_collector_status below uses it to decide what may not count as
# proof of reachability. They drifted -- the list grew from ("prune",) to three
# kinds with the resilience sweep while the query below still excluded only
# 'prune', so the `invariants`/`alerts` runs of the very first cycle made every
# Syncthing-less (or Syncthing-broken) dashboard report syncthing_reachable and
# ok=true on /api/v1/health, which is the exact fault the staleness check in
# fetch_collector_status exists to catch. It surfaced as a flaky
# test_api.py::test_health_endpoint: whether the first cycle's rows landed
# before the request was a thread race (2026-09-04).
SYNCTHING_FREE_KINDS = ("prune", "invariants", "alerts")

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


# SYS-4 / APP-13 (resilience sweep 2026-08-28). A companion's own wall clock
# reaches this server on every report and nothing anywhere compared it with
# ours. Two independent failures come out of that: a slow clock makes lane B
# transfer nothing at all (rclone's `--min-age` computes a remote file's age
# as local-clock-minus-modtime, so every file on the NAS looks like it was
# written in the future and is excluded, and the lane exits 0 and reports
# idle-and-green), and a wrong clock in a retention or ordering predicate
# either vanishes a live machine from the fleet grid or pins a dead one at
# the top of it.
#
# So the client's timestamp is STORED SEPARATELY from ours and clamped before
# it is: a VM resumed from a 2019 snapshot must not be able to write a value
# that sorts below every real row, and a dead CMOS battery claiming 2098 must
# not be able to write one that sorts above them. Past the clamp the stored
# value is our own received_at, and the real difference is kept as a number
# so the grid can chip it.
CLOCK_SKEW_CLAMP_SECONDS = 7 * 24 * 3600
# What the grid chips. Below a minute is NTP jitter and a laptop coming out of
# sleep; a minute is already twice the `--min-age 60s` lane B passes.
CLOCK_SKEW_WARN_SECONDS = 60.0


def clamp_reported_at(
    client_reported_at: str | None, received_at: str
) -> tuple[str | None, float | None, bool]:
    """(stored client timestamp, skew seconds, was it clamped).

    Skew is POSITIVE when the client's clock is AHEAD of this server's. An
    unparseable timestamp is not a crash and not a zero: it comes back as
    (None, None, True) -- "we could not read it" is its own answer, and
    rendering it as no-skew is the failure this exists to stop.
    """
    if not client_reported_at:
        return None, None, False
    try:
        skew = age_seconds(received_at, client_reported_at)
    except (ValueError, TypeError):
        return None, None, True
    if abs(skew) > CLOCK_SKEW_CLAMP_SECONDS:
        # Past the clamp the client's claim is not evidence of anything except
        # that its clock is broken, so it does not get to be a stored ordering
        # key. The measurement survives; the value does not.
        return received_at, skew, True
    return client_reported_at, skew, False


# How long a connection waits for the write lock before it gives up with
# "database is locked" (2026-09-03 database is locked, api_report held the
# lock). Two values on purpose:
#
#   BUSY_TIMEOUT_MS             an ad-hoc request connection. 5 s is the wait
#                               a person at a page is prepared to sit through.
#   BUSY_TIMEOUT_BACKGROUND_MS  the collector's long-lived connection and the
#                               session store's. Nobody is watching those, and
#                               a slow request beats a 500 on the fleet grid or
#                               a signed-in admin bounced to the login page.
BUSY_TIMEOUT_MS = 5000
BUSY_TIMEOUT_BACKGROUND_MS = 20000


def connect(path: str | Path, *, busy_ms: int = BUSY_TIMEOUT_MS) -> sqlite3.Connection:
    # check_same_thread=False: FastAPI may create a request's connection in a
    # threadpool worker but use it from an async handler on the event loop.
    # Each connection still serves exactly one request/thread at a time.
    conn = sqlite3.connect(str(path), timeout=busy_ms / 1000.0, check_same_thread=False)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute(f"PRAGMA busy_timeout={int(busy_ms)}")
    # synchronous=NORMAL is the standard setting for WAL, and the fsync it
    # drops was the single largest latency in a write here: /data is ZFS on
    # the NAS, where every commit's fsync waits on the pool (2026-09-03
    # database is locked, api_report held the lock -- the fsync was inside the
    # lock, so every other writer waited on it too). What it costs: on HOST
    # power loss the last transactions can be lost. It is NOT weaker against a
    # container restart or a process death -- the WAL is still there and is
    # replayed -- and it cannot corrupt the database either way.
    conn.execute("PRAGMA synchronous=NORMAL")
    conn.execute("PRAGMA foreign_keys=ON")
    return conn


# Ordered migration steps: (target user_version, script). `script=None` means
# "apply the base schema.sql" (the v0 -> v1 bootstrap). Each entry's
# user_version is committed IMMEDIATELY after that entry's script runs -- not
# once at the end -- so an upgrade interrupted between two steps (a
# `docker restart` mid-migration is routine) resumes on the next start
# instead of re-running an already-applied `ALTER TABLE ... ADD COLUMN` and
# crash-looping on `duplicate column name`. See the db.py migration finding.
# v22: the machine's ROLE, on the machine's own row (KNOWN_BUGS CR-28,
# 2026-08-18). `mode` ("base" | "editor") has ridden every report since 0.4.x
# and was only ever persisted onto `editor_media_project` -- one row per
# project, written only when a media manifest arrives. So the fleet's answer
# to "does this computer sync at all?" lived in a per-project table, and the
# two queue sources that did not join it showed the BASE RIG sitting in
# [ QUEUED ] with a [ GETTING READY ] chip, permanently: it never syncs, so it
# never gets a completion row, so "ticked and no completion yet" stays true
# forever. `editor_media_project.mode` stays exactly as it is
# (fetch_sync_backlog reads it) and both are written from the same report.
SCHEMA_V22 = """
ALTER TABLE machine_state ADD COLUMN mode TEXT;
"""

# v23: the MACHINE REGISTRY (docs/MULTI_MACHINE_PLAN.md WP1, 2026-08-18).
# One row per computer, which is the thing the fleet actually syncs to. Until
# now a machine existed only as a string on other tables' keys, learned from
# whatever `platform.node()` returned on the last report.
#
# Keyed `(editor_username, machine)` -- the SAME key machine_state,
# editor_media, editor_media_project, lane_report_current, active_transfers
# and media_tree_clips already use. A synthetic id as the primary key was the
# first design (see the plan's §3.1) and was dropped for exactly this reason:
# it would have made the plan the ONE thing that could not be joined to its
# siblings without a lookup, in queries that are already the widest in here.
#
# `machine_id` is therefore an ATTRIBUTE, not the key: a UUID the companion
# mints once into ~/.ccsync/machine.json and reports thereafter. It survives
# a hostname change and a Syncthing key regeneration, which is what makes
# "this is the same computer under a new name / a new device ID" answerable
# at all -- the 2026-07-27 stuck-lane-C incident took a day to diagnose for
# want of it. `syncthing_device_id` is the companion's own myID, which is what
# lets the enforce cycle share a folder with THAT machine rather than with
# every device carrying its owner's name.
#
# Backfilled from machine_state, so the fleet has its registry the moment
# this runs, without waiting for anyone to upgrade.
SCHEMA_V23 = """
CREATE TABLE IF NOT EXISTS machines (
  editor_username     TEXT NOT NULL,
  machine             TEXT NOT NULL,        -- hostname as reported; a LABEL
  machine_id          TEXT,                 -- companion-minted, stable across renames
  platform            TEXT,
  syncthing_device_id TEXT,
  first_seen          TEXT NOT NULL,
  last_seen           TEXT NOT NULL,
  PRIMARY KEY (editor_username, machine)
);
CREATE INDEX IF NOT EXISTS machines_by_machine_id ON machines(machine_id);
CREATE INDEX IF NOT EXISTS machines_by_device ON machines(syncthing_device_id);
INSERT OR IGNORE INTO machines
    (editor_username, machine, platform, first_seen, last_seen)
  SELECT editor_username, machine, platform, reported_at, reported_at
    FROM machine_state;
"""

# v24: the sync plan belongs to a COMPUTER, not to a person (WP2 + WP7).
# `selections` was keyed (editor_username, project_slug) while every consumer
# of it -- the lane A/B backlog, the lane C shares, the companion's own queue
# -- is per machine, so one person's two computers could not hold two
# different sets of projects. The fleet's answer until today was a SECOND
# ACCOUNT per machine (`alex` and `alex_laptop` are one human), which counts
# machines as people everywhere else in the product.
#
# The migration FANS OUT: one row per (existing tick x that editor's known
# machines), which leaves a fleet of one-machine editors byte-identical to
# what it had. A tick belonging to an editor with no machine on record keeps
# `machine = ''`.
#
# `machine = ''` is the UNASSIGNED bucket and the only inheritance in here: it
# applies to every machine of that editor that has no rows of its own. It
# exists for three real cases -- an editor who ticked before their companion
# ever reported, a companion too old to say which machine is asking, and the
# collector's one-shot seed from pre-existing Syncthing shares -- and a normal
# fleet has none of them after this migration. Resolution is spelled once, in
# selections_for_machine().
#
# editor_prefs follows the same reasoning (WP7): project_root_override is a
# property of a machine's Resolve setup, not of the person sitting at it.
SCHEMA_V24 = """
CREATE TABLE selections_v24 (
  editor_username TEXT NOT NULL,
  machine         TEXT NOT NULL DEFAULT '',   -- '' = unassigned (see above)
  project_slug    TEXT NOT NULL,
  position        INTEGER NOT NULL,
  created_at      TEXT NOT NULL,
  created_by      TEXT NOT NULL,
  PRIMARY KEY (editor_username, machine, project_slug)
);
INSERT OR IGNORE INTO selections_v24
    (editor_username, machine, project_slug, position, created_at, created_by)
  SELECT s.editor_username, m.machine, s.project_slug, s.position,
         s.created_at, s.created_by
    FROM selections s JOIN machines m ON m.editor_username = s.editor_username;
INSERT OR IGNORE INTO selections_v24
    (editor_username, machine, project_slug, position, created_at, created_by)
  SELECT s.editor_username, '', s.project_slug, s.position,
         s.created_at, s.created_by
    FROM selections s
   WHERE NOT EXISTS (SELECT 1 FROM machines m
                      WHERE m.editor_username = s.editor_username);
DROP TABLE selections;
ALTER TABLE selections_v24 RENAME TO selections;
CREATE INDEX IF NOT EXISTS selections_by_slug ON selections(project_slug);

CREATE TABLE editor_prefs_v24 (
  editor_username       TEXT NOT NULL,
  machine               TEXT NOT NULL DEFAULT '',
  project_root_override TEXT,
  updated_at            TEXT NOT NULL,
  updated_by            TEXT NOT NULL,
  PRIMARY KEY (editor_username, machine)
);
INSERT OR IGNORE INTO editor_prefs_v24
    (editor_username, machine, project_root_override, updated_at, updated_by)
  SELECT p.editor_username, m.machine, p.project_root_override,
         p.updated_at, p.updated_by
    FROM editor_prefs p JOIN machines m ON m.editor_username = p.editor_username;
INSERT OR IGNORE INTO editor_prefs_v24
    (editor_username, machine, project_root_override, updated_at, updated_by)
  SELECT p.editor_username, '', p.project_root_override, p.updated_at, p.updated_by
    FROM editor_prefs p
   WHERE NOT EXISTS (SELECT 1 FROM machines m
                      WHERE m.editor_username = p.editor_username);
DROP TABLE editor_prefs;
ALTER TABLE editor_prefs_v24 RENAME TO editor_prefs;
"""

# v25: PUSHED UPDATES (docs/MULTI_MACHINE_PLAN.md §OTA, 2026-08-18). Until
# now the only thing that could apply a published build was an editor
# clicking "Update now" in their own tray -- so a fleet-wide fix landed
# whenever each machine's owner happened to notice a balloon, and ruskin's
# PC sat two versions behind for a day while its lanes were parked.
#
# An admin asking for one machine to update is recorded HERE and delivered on
# that machine's next report, in the `commands` block the fleet halt already
# rides (api.py). No push infrastructure, no inbound connection to an editor's
# PC, and nothing new to authenticate.
#
# The request names a VERSION. A companion applies it only if the offer it is
# already holding -- signature-verified on arrival, floor-checked, from this
# dashboard -- is that version, so a pushed update can never install anything
# the editor's own tray click could not have.
SCHEMA_V25 = """
ALTER TABLE machines ADD COLUMN update_requested_version TEXT;
ALTER TABLE machines ADD COLUMN update_requested_at TEXT;
ALTER TABLE machines ADD COLUMN update_requested_by TEXT;
"""

# v26: RESUME PROXY DOWNLOAD FROM THE DASHBOARD (KNOWN_BUGS CR-45,
# 2026-08-20). Lane B's circuit breaker could only ever be cleared at the
# editor's own tray, so a machine that tripped one sat with proxy download
# stopped until its owner was next at the keyboard -- ruskin's PC spent a day
# like that on 2026-08-19, over a folder move that had deleted nothing.
#
# Recorded HERE and delivered in the `commands` block the fleet halt and the
# pushed update already ride. Nothing about the decision moves: resuming is
# still an operator asserting the server is worth syncing from, and the admin
# who just checked the NAS is the operator best placed to say so.
#
# The request is cleared when the machine reports its breaker no longer
# tripped, which is what keeps it from clearing a LATER, unrelated trip.
SCHEMA_V26 = """
ALTER TABLE machines ADD COLUMN lane_b_resume_requested_at TEXT;
ALTER TABLE machines ADD COLUMN lane_b_resume_requested_by TEXT;
"""

# v27: cross-project folder links (SHARED_FOLDERS_PLAN.md, 2026-08-23). A
# borrowing project's marker declares `includes`; the marker on the tree is
# the TRUTH and this table is the resolved cache the selection API and the UI
# read (exactly as projects.label mirrors the folder), rebuilt by the
# collector's _run_links every provision cycle. lender_slug/sub_rel are NULL
# unless status is ok or missing -- and they double as the fallback identity
# when the lender moves on the NAS and the declared path goes stale.
SCHEMA_V27 = """
CREATE TABLE IF NOT EXISTS project_links (
  borrower_slug TEXT NOT NULL,
  declared_path TEXT NOT NULL,
  lender_slug   TEXT,
  sub_rel       TEXT,
  status        TEXT NOT NULL,
  detail        TEXT,
  first_seen    TEXT NOT NULL,
  last_seen     TEXT NOT NULL,
  PRIMARY KEY (borrower_slug, declared_path)
);
CREATE INDEX IF NOT EXISTS ix_project_links_lender ON project_links(lender_slug);
"""

# v28: the upload-only tick (docs/UPLOAD_ONLY_TICK.md, 2026-08-27). A tick
# carries a MODE: `full` is what every tick was until now (lanes A, B and C);
# `upload_only` is lane A alone -- the editor has footage backed up locally
# and wants the originals on the server without the project's proxies and
# shared files coming down. Every existing row is `full` by the DEFAULT, so
# a dashboard upgraded ahead of its fleet changes nothing (the B16 rule).
SCHEMA_V28 = """
ALTER TABLE selections ADD COLUMN sync_mode TEXT NOT NULL DEFAULT 'full';
"""

# v29: dashboard-driven file moves (docs/FILE_MOVES.md, 2026-08-27). A file
# uploaded into the wrong project folder used to be un-fixable from the
# server side: lane A is a one-way copy that never deletes, so a move on the
# NAS was undone by the next pass of every machine still holding the file at
# the old path (leso's card dump, 2026-08-27). The move now happens HERE and
# fans out as a command to each machine that holds (or syncs) the project,
# which moves its own copy and relinks Resolve. `file_moves` is the record;
# `file_move_targets` is one row per computer the command must reach, with
# delivery and outcome. Paths are project-relative and posix; the two
# `*_project_rel` columns pin the project folders AS THEY WERE, because a
# project can be renamed on the NAS before a slow machine picks the move up.
SCHEMA_V29 = """
CREATE TABLE IF NOT EXISTS file_moves (
  id               INTEGER PRIMARY KEY AUTOINCREMENT,
  from_slug        TEXT NOT NULL,
  from_project_rel TEXT NOT NULL,
  from_rel         TEXT NOT NULL,
  to_slug          TEXT NOT NULL,
  to_project_rel   TEXT NOT NULL,
  to_rel           TEXT NOT NULL,
  is_dir           INTEGER NOT NULL DEFAULT 0,
  proxies_moved    INTEGER NOT NULL DEFAULT 0,
  requested_by     TEXT NOT NULL,
  requested_at     TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS ix_file_moves_from ON file_moves(from_slug, requested_at);
CREATE INDEX IF NOT EXISTS ix_file_moves_to ON file_moves(to_slug, requested_at);
CREATE TABLE IF NOT EXISTS file_move_targets (
  move_id         INTEGER NOT NULL,
  editor_username TEXT NOT NULL,
  machine         TEXT NOT NULL,
  delivered_at    TEXT,
  applied_at      TEXT,
  ok              INTEGER,
  detail          TEXT,
  PRIMARY KEY (move_id, editor_username, machine)
);
CREATE INDEX IF NOT EXISTS ix_file_move_targets_machine
  ON file_move_targets(editor_username, machine, applied_at);
"""

# v30: what the dashboard was throwing away (SYS-3 / SYNC-8 / SYS-4 /
# APP-6 / APP-13, resilience sweep 2026-08-28).
#
# `received_at` is the SERVER's clock for this row. machine_state has only
# ever had `reported_at`, and api.py has always written the server's own
# timestamp into it -- so the retention predicate and the eviction ordering
# read a column whose NAME says "the client said so", and the next hand that
# passed the companion's value in would have made both true. Naming the
# server clock explicitly is what lets `client_reported_at` hold the
# companion's own timestamp (clamped: a machine restored from a snapshot
# claims 2019, a dead CMOS battery claims 2098) and `clock_skew_seconds` hold
# the difference -- the only measurement of skew in either component. A slow
# clock switches lane B off completely and silently (rclone --min-age sees
# every remote file as written in the future, excludes all of them, and exits
# 0 having transferred nothing), so it has to be visible somewhere.
#
# The rest is telemetry the companion has been computing and sending for
# weeks that `extra="ignore"` dropped at the model boundary: the Syncthing
# supervisor's incident record (SYNC-8 -- the difference between "he
# rebooted" and "that machine has needed a human since Tuesday"), the crash
# counter, the unfiltered-folder list and the Syncthing conflict count. All
# nullable, so a companion too old to send any of it leaves them NULL, which
# is not the same answer as zero and must not be rendered as one.
SCHEMA_V30 = """
ALTER TABLE machine_state ADD COLUMN received_at TEXT;
ALTER TABLE machine_state ADD COLUMN client_reported_at TEXT;
ALTER TABLE machine_state ADD COLUMN clock_skew_seconds REAL;
ALTER TABLE machine_state ADD COLUMN supervisor_down_since TEXT;
ALTER TABLE machine_state ADD COLUMN supervisor_attempts INTEGER;
ALTER TABLE machine_state ADD COLUMN supervisor_last_error TEXT;
ALTER TABLE machine_state ADD COLUMN supervisor_supervising INTEGER;
ALTER TABLE machine_state ADD COLUMN crash_count INTEGER;
ALTER TABLE machine_state ADD COLUMN crash_newest TEXT;
ALTER TABLE machine_state ADD COLUMN folders_unfiltered INTEGER;
ALTER TABLE machine_state ADD COLUMN folders_unfiltered_names TEXT;
ALTER TABLE machine_state ADD COLUMN sync_conflicts INTEGER;
UPDATE machine_state SET received_at = reported_at WHERE received_at IS NULL;
"""

# v31: the fleet audit ledger (SYS-11 / DASH-8, resilience sweep 2026-08-28).
#
# There was no history of any state change anywhere: `selections` rows were
# DELETEd in place, and "who stopped this project syncing on Tuesday, and
# when" was unanswerable on a site with two admins. Append-only on purpose --
# nothing in the product ever UPDATEs or DELETEs a row here except the 180-day
# retention pass in prune().
#
# `detail_json` carries the shape each action needs (a plan change carries the
# BEFORE and AFTER placements, which is what makes the undo a restore rather
# than a guess); `subject` is the one thing a human filters on, so it holds
# the noun -- a project slug, an editor, a machine, a version.
#
# selections.changed_at records when a tick was last written or switched
# modes, which `created_at` cannot say. The enforce freeze deliberately does
# NOT read it -- see recent_plan_change_devices for the upload-only tick that
# proved freshness is not a reason to keep a share.
SCHEMA_V31 = """
CREATE TABLE IF NOT EXISTS fleet_audit (
  id          INTEGER PRIMARY KEY AUTOINCREMENT,
  at          TEXT NOT NULL,
  actor       TEXT NOT NULL,
  action      TEXT NOT NULL,
  subject     TEXT NOT NULL DEFAULT '',
  detail_json TEXT NOT NULL DEFAULT '{}'
);
CREATE INDEX IF NOT EXISTS ix_fleet_audit_at ON fleet_audit(at);
CREATE INDEX IF NOT EXISTS ix_fleet_audit_subject ON fleet_audit(subject, id);
CREATE INDEX IF NOT EXISTS ix_fleet_audit_action ON fleet_audit(action, id);
ALTER TABLE selections ADD COLUMN changed_at TEXT NOT NULL DEFAULT '';
"""

# SYS-1 / SYS-5 (resilience sweep 2026-08-28). The liveness contract's
# storage: a lane may not be green or amber without a monotonic progress
# token AND the server-clock time that token last changed, and a machine's
# free space is now on the wire instead of being invisible to every page.
#
# progress_token_since is OURS, not the companion's: it is the received_at of
# the first report that carried the CURRENT token (see upsert_lane_report),
# so a wrong clock on the machine cannot hide a stall and a companion whose
# sequencer thread has died cannot keep answering "still fresh" (SYS-2).
#
# rotation_seconds is the companion's own project_rotation_seconds, sent in
# sync_guard so the stall budget is 3 rotations rather than a number the
# server guessed; absent, health.lane_stall falls back to its 30 min floor.
#
# stalled_lane/stalled_seconds hold sync_guard.stalled -- the stall the
# COMPANION detected and killed (SYNC-1/SYS-17). Both are ADD COLUMN, which
# migrate() skips when the column exists, so the WHY/DIAGNOSTICS step may
# name them again without breaking the replay.
SCHEMA_V32 = """
ALTER TABLE lane_report_current ADD COLUMN progress_token TEXT;
ALTER TABLE lane_report_current ADD COLUMN progress_token_since TEXT;
ALTER TABLE lane_report_current ADD COLUMN state_since TEXT;
ALTER TABLE machine_state ADD COLUMN disk_root_free_bytes INTEGER;
ALTER TABLE machine_state ADD COLUMN disk_root_total_bytes INTEGER;
ALTER TABLE machine_state ADD COLUMN disk_system_free_bytes INTEGER;
ALTER TABLE machine_state ADD COLUMN disk_at TEXT;
ALTER TABLE machine_state ADD COLUMN rotation_seconds REAL;
ALTER TABLE machine_state ADD COLUMN stalled_lane TEXT;
ALTER TABLE machine_state ADD COLUMN stalled_seconds INTEGER;
ALTER TABLE machine_state ADD COLUMN stalled_killed INTEGER;
ALTER TABLE machine_state ADD COLUMN stalled_at TEXT;
"""

# v33: the WHY sentence's stored inputs and the diagnostics channel (SYS-7,
# resilience sweep 2026-08-28).
#
# blocked_* is `sync_guard.blocked` flattened (SYNC-15): the companion's OWN
# ranked answer to "why is nothing moving", which is the only end that can see
# the root guard's fourth answer, the licence park and its own transport.
# health.why_not_syncing prefers it over anything this server derives.
#
# restarts_* is the LaneWatchdog's record (SYS-2). It is here, on the machine's
# row, rather than only in a companion state file, because "this machine has
# needed its sync thread restarted three times an hour" is the difference
# between self-healing and a machine that needs a person, and the file it is
# written to is on the sick machine.
#
# `diagnostics` is append-only per machine and bounded twice over: the newest
# DIAGNOSTICS_KEEP_PER_MACHINE bundles per (editor, machine) at write time, and
# DIAGNOSTICS_MAX_AGE_DAYS in prune(). A bundle is build_diagnostics()'s text
# and nothing else -- it holds no credential (the companion redacts its own
# token), so it lives in the same DB rather than in a second store.
#
# The two `machines` columns are the one-shot ASK THIS MACHINE WHY request,
# modelled on lane_b_resume_requested_at down to the `requested_at` stamp: the
# companion compares it so a redelivered command is not re-run.
SCHEMA_V33 = """
ALTER TABLE machine_state ADD COLUMN blocked_reason TEXT;
ALTER TABLE machine_state ADD COLUMN blocked_detail TEXT;
ALTER TABLE machine_state ADD COLUMN blocked_since TEXT;
ALTER TABLE machine_state ADD COLUMN restarts_count_24h INTEGER;
ALTER TABLE machine_state ADD COLUMN restarts_last_at TEXT;
ALTER TABLE machine_state ADD COLUMN restarts_last_error TEXT;
ALTER TABLE machines ADD COLUMN diagnostics_requested_at TEXT;
ALTER TABLE machines ADD COLUMN diagnostics_requested_by TEXT;
CREATE TABLE IF NOT EXISTS diagnostics (
  id          INTEGER PRIMARY KEY AUTOINCREMENT,
  editor      TEXT NOT NULL,
  machine     TEXT NOT NULL,
  machine_id  TEXT NOT NULL DEFAULT '',
  trigger     TEXT NOT NULL DEFAULT '',
  at          TEXT NOT NULL DEFAULT '',
  received_at TEXT NOT NULL,
  text        TEXT NOT NULL DEFAULT ''
);
CREATE INDEX IF NOT EXISTS ix_diagnostics_machine
  ON diagnostics(editor, machine, id);
CREATE INDEX IF NOT EXISTS ix_diagnostics_received ON diagnostics(received_at);
"""

# v35: what happened when this computer last tried to take a build, and what
# happened when it last tried to report (REL-8 / DASH-2 / REL-16, resilience
# sweep 2026-08-28).
#
# `arch` is the report's new top-level field: an Intel Mac and an Apple-silicon
# one both report platform `macos`, so the channel had no way to avoid handing
# one the other's binary (REL-16). It is a property of the box, so it is
# COALESCEd like `platform`.
#
# upgrade_* is `sync_guard.upgrade` flattened (REL-8). The report payload
# carried NOTHING about upgrade outcomes, so a machine whose AV quarantines
# every downloaded exe looked exactly like one that had not seen the push yet:
# the admin's [ UPDATE NOW ] sat "pending" for ever while the machine
# downloaded 20 MB every ten minutes. `upgrade_reverted_from` is the crash-loop
# guard's answer (APP-5) and is sent ONCE, so it is kept (COALESCE) rather than
# latched -- the grid stops showing it by itself once the machine is running a
# build at or above the one it fell back from.
#
# The two `machines` columns are DASH-2's: a report refused ONLY because its
# identity token cannot be verified writes them and nothing else, so a fleet
# whose DASH_SESSION_SECRET was rotated says "this computer is trying to report
# and being refused" instead of showing a grid that quietly stops moving.
SCHEMA_V35 = """
ALTER TABLE machine_state ADD COLUMN arch TEXT;
ALTER TABLE machine_state ADD COLUMN upgrade_version TEXT;
ALTER TABLE machine_state ADD COLUMN upgrade_attempts INTEGER;
ALTER TABLE machine_state ADD COLUMN upgrade_last_error TEXT;
ALTER TABLE machine_state ADD COLUMN upgrade_last_attempt_at TEXT;
ALTER TABLE machine_state ADD COLUMN upgrade_reverted_from TEXT;
ALTER TABLE machines ADD COLUMN report_refused_at TEXT;
ALTER TABLE machines ADD COLUMN report_refused_reason TEXT;
"""

# v34: the release channel grows a rollout, a recall and two discriminators
# (REL-1/SYS-6, REL-3, REL-4/SYS-13, REL-16, REL-13; resilience sweep
# 2026-08-28).
#
# `rollout` is what a build IS to this fleet, not merely what it is pointed
# at: 'staged' means published and installable by name (a per-machine push)
# but offered to nobody, 'current' means the whole fleet is being offered it.
# is_current stays the served pointer -- one column, one meaning, and no
# dangling-pointer window -- and rollout is kept in step with it. Every row
# published before this migration was either current or superseded, which is
# exactly the two values, so the backfill below is lossless.
#
# `staged_at` starts the soak clock. The gate on MAKE CURRENT reads it
# together with machine_state.companion_version_since, which is the first
# report that carried THIS version from a machine (server clock, not the
# companion's: a wrong clock on a canary must not be able to shorten a soak).
#
# `requires_dashboard` and `arch` are the two SIGNED extras (release_trust.
# OPTIONAL_KIND_EXTRA_FIELDS) stored so they can be re-served verbatim in the
# offer -- the signature covers them, so a stored copy that differs by one
# character is a build no companion will install.
#
# `git_sha`/`git_dirty` are ADVISORY and deliberately unsigned (REL-13): they
# say which commit a build came from, and "+dirty" used to die at the publish
# boundary, leaving the fleet on a 0.9.55 that corresponds to no commit in the
# repo, permanently and invisibly.
#
# `retracted_at`/`retracted_reason` are the recall (REL-3). A retracted row is
# never served, never made current and says why on both admin pages; the row
# and its file stay, because the fleet may still be running it and an admin
# has to be able to see what they are rolling back FROM.
SCHEMA_V34 = """
ALTER TABLE companion_packages ADD COLUMN rollout TEXT NOT NULL DEFAULT 'staged';
ALTER TABLE companion_packages ADD COLUMN staged_at TEXT;
ALTER TABLE companion_packages ADD COLUMN requires_dashboard TEXT;
ALTER TABLE companion_packages ADD COLUMN arch TEXT;
ALTER TABLE companion_packages ADD COLUMN git_sha TEXT;
ALTER TABLE companion_packages ADD COLUMN git_dirty INTEGER;
ALTER TABLE companion_packages ADD COLUMN ever_current INTEGER NOT NULL DEFAULT 0;
ALTER TABLE companion_packages ADD COLUMN retracted_at TEXT;
ALTER TABLE companion_packages ADD COLUMN retracted_reason TEXT;
ALTER TABLE machine_state ADD COLUMN companion_version_since TEXT;
UPDATE companion_packages SET rollout='current', ever_current=1 WHERE is_current=1;
UPDATE companion_packages SET staged_at=published_at WHERE staged_at IS NULL;
UPDATE machine_state SET companion_version_since=COALESCE(received_at, reported_at)
 WHERE companion_version_since IS NULL AND companion_version IS NOT NULL;
"""

# v36: a file move becomes a two-phase record with a retry and an undo
# (DASH-1 / DASH-9 / UX-5 / UX-11 / RES-1 / RES-10, resilience sweep
# 2026-08-28).
#
# `state` is the SERVER half. The row used to be written after `src.rename`
# returned, so a rename that succeeded and then hit anything at all (a proxy
# sibling held open by a Resolve, a container restart, a full /data) left the
# original moved with NO record -- and therefore no command to any machine,
# which is precisely the "lane A never deletes, every holder re-uploads the
# old path" failure this feature exists to end, now with the original also
# gone from where the editors' Resolve projects point. The row is written
# `pending` and COMMITTED before the rename, flipped to `done` after, and
# `partial` when a proxy sibling could not follow. `pending` rows are
# reconciled by stat-ing both ends (api.reconcile_file_moves).
#
# The target columns are the MACHINE half. `attempts`/`last_error` carry the
# companion's retry (RES-1: a move Resolve blocked used to latch on the first
# PermissionError and was never tried again, and 24 h later lane A put the
# file back). `state` is the shape of that answer -- 'retrying' does not
# retire the command, 'blocked' does and says why. `expired_at` is UX-5: an
# UNDELIVERED move must never expire (the laptop was away for the shoot, and
# it is the one machine still holding the file at the old path), while a
# delivered-and-unanswered one ages so the project page can say that computer
# may re-upload the old path. `relink_pending` is RES-10: the copy moved but
# the project referencing it was not the one open, so nothing has repointed
# Resolve yet.
#
# `undo_of`/`undone_by` link the two rows of an undo (UX-11): the inverse move
# goes through the same machinery, so it is a file_moves row like any other,
# and the pair has to be readable from either end.
SCHEMA_V36 = """
ALTER TABLE file_moves ADD COLUMN state TEXT NOT NULL DEFAULT 'done';
ALTER TABLE file_moves ADD COLUMN state_detail TEXT;
ALTER TABLE file_moves ADD COLUMN undo_of INTEGER;
ALTER TABLE file_moves ADD COLUMN undone_by INTEGER;
ALTER TABLE file_move_targets ADD COLUMN attempts INTEGER NOT NULL DEFAULT 0;
ALTER TABLE file_move_targets ADD COLUMN last_error TEXT;
ALTER TABLE file_move_targets ADD COLUMN state TEXT;
ALTER TABLE file_move_targets ADD COLUMN expired_at TEXT;
ALTER TABLE file_move_targets ADD COLUMN relink_pending INTEGER NOT NULL DEFAULT 0;
"""

# v37: the notices ledger (UX-10, resilience sweep 2026-08-28).
#
# The dashboard refuses things for good reasons -- a stray marker on a
# container that hides three real projects, two Syncthing folders over one
# directory, an enforce pass whose blast radius tripped the brake -- and every
# one of those diagnoses was written to a container log a non-technical owner
# will never open. Sixteen already-written sentences reaching nobody.
#
# A TABLE rather than more `meta` keys because these have a set (one per
# subject: per slug, per folder), a first_seen/last_seen life and a DISMISS,
# none of which a single-value meta row can carry. Keyed (kind, subject) so a
# condition re-detected every five minutes is one row that ages, not a log.
# cleared_at is set both by the code that observes the condition gone and by
# an admin's [ DISMISS ]; a condition still true is written again and reopens,
# deliberately -- a dismissal must not be able to hide a live problem.
SCHEMA_V37 = """
CREATE TABLE IF NOT EXISTS notices (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  kind TEXT NOT NULL,
  severity TEXT NOT NULL DEFAULT 'warn',
  subject TEXT NOT NULL DEFAULT '',
  body TEXT NOT NULL DEFAULT '',
  fix TEXT NOT NULL DEFAULT '',
  first_seen TEXT NOT NULL,
  last_seen TEXT NOT NULL,
  cleared_at TEXT
);
CREATE UNIQUE INDEX IF NOT EXISTS idx_notices_key ON notices (kind, subject);
CREATE INDEX IF NOT EXISTS idx_notices_open ON notices (cleared_at, last_seen);
"""

# v38: the outbound voice's ledger, and the four report sections the
# companion's Resolve/ingest guards compute and had nowhere to land (SYS-8
# plus the wave-4 ingest contract, resilience sweep 2026-08-28).
#
# `alert_log` is what makes the dedup and the weekly schedule DURABLE rather
# than a counter in a process that gets replaced every deploy: "have we
# already told somebody about this breaker today" and "has this week's report
# gone out" are both answered by a row here, so a container restart at 07:59
# on Monday does not send the report twice and a flapping breaker does not
# send forty mails. `ok=0` rows are kept on purpose -- a sink that has been
# refusing for three days is the thing an admin most needs to see, and a
# failed send that left no trace is how "we thought alerts were on" happens.
#
# The machine_state columns are the ingest half. `resolve_*` is the companion's
# Resolve health scan (clips the open project references from OUTSIDE the
# tree, which lane A will never upload and no other editor will ever see);
# `stray_projects_*` and `moved_project_dirs_count` are project directories
# that are not where the tree says they should be; `ingest_staging_bytes` is
# footage sitting in a drop folder that has not been filed yet. Every one of
# them is a COUNT plus, where it helps, a size: the grid needs a chip and a
# tooltip, never the list of paths in a column.
SCHEMA_V38 = """
CREATE TABLE IF NOT EXISTS alert_log (
  id      INTEGER PRIMARY KEY AUTOINCREMENT,
  at      TEXT NOT NULL,
  kind    TEXT NOT NULL,
  subject TEXT NOT NULL DEFAULT '',
  sent_to TEXT NOT NULL DEFAULT '',
  ok      INTEGER NOT NULL DEFAULT 0,
  detail  TEXT NOT NULL DEFAULT ''
);
CREATE INDEX IF NOT EXISTS ix_alert_log_at ON alert_log(at);
CREATE INDEX IF NOT EXISTS ix_alert_log_kind ON alert_log(kind, subject, id);
ALTER TABLE machine_state ADD COLUMN resolve_out_of_tree INTEGER;
ALTER TABLE machine_state ADD COLUMN resolve_bad_prefix INTEGER;
ALTER TABLE machine_state ADD COLUMN resolve_missing INTEGER;
ALTER TABLE machine_state ADD COLUMN resolve_ignored INTEGER;
ALTER TABLE machine_state ADD COLUMN resolve_last_scan_at TEXT;
ALTER TABLE machine_state ADD COLUMN stray_projects_count INTEGER;
ALTER TABLE machine_state ADD COLUMN stray_projects_bytes INTEGER;
ALTER TABLE machine_state ADD COLUMN moved_project_dirs_count INTEGER;
ALTER TABLE machine_state ADD COLUMN ingest_staging_bytes INTEGER;
"""

# v39: the continuous invariant checker's ledger (SYS-9, resilience sweep
# 2026-08-28, wave 5, built 2026-08-29).
#
# Every cross-component fact in this system is enforced at the moment
# something WRITES it and never re-verified: a tick is written while
# Syncthing is unreachable, a project is renamed on the NAS by hand, a disk
# is cloned onto a second PC. `folder_tuning_drift` proves the pattern is
# understood -- it re-reads a folder's settings every cycle and repairs what
# drifted -- and it covers Syncthing folder tuning ALONE.
#
# A TABLE rather than notices alone because the page has to be able to show
# "checked and found nothing wrong" as well as "broken": the row for a
# healthy invariant is the EVIDENCE that separates [ OK ] from
# [ NOT CHECKED ], which is the load-bearing rule of this whole sweep. One
# row per (invariant, subject); subject '' is the invariant's own summary row
# and always exists, subject rows name what is broken and are capped by the
# writer. `ok` is 1/0/NULL, NULL meaning "not checked" -- the tri-state is in
# the data, so no reader can flatten it to a boolean by accident.
SCHEMA_V39 = """
CREATE TABLE IF NOT EXISTS invariant_results (
  invariant  TEXT NOT NULL,
  subject    TEXT NOT NULL DEFAULT '',
  ok         INTEGER,
  state      TEXT NOT NULL,
  detail     TEXT NOT NULL DEFAULT '',
  checked_at TEXT NOT NULL,
  PRIMARY KEY (invariant, subject)
);
CREATE INDEX IF NOT EXISTS ix_invariant_results_state
  ON invariant_results(state, checked_at);
"""

# v40: the admin-side Resolve undo (SYS-15b, resilience sweep 2026-08-28,
# built 2026-08-29 as wave 5).
#
# Undoing a clip-path change CC Sync made was a TRAY CLICK on the editor's
# own machine and nothing else (docs/RESOLVE_EDIT_SAFETY.md) -- while the
# lane B breaker, whose blast radius is smaller, got [ RESUME ] on the
# command channel in CR-45. So an owner who could see that a relink pass had
# gone wrong on someone else's computer had no way to undo it without that
# person being at their keyboard.
#
# A TABLE rather than a pair of columns on `machines` (the shape
# resume_lane_b and diagnostics use) because this command NAMES A THING: a
# journal id, on a machine that may hold several, and each request has its
# own outcome worth keeping after it is answered. It is the `file_moves`
# acknowledgement contract, deliberately: delivered on the reply, kept
# riding every report until the machine answers, `state='retrying'` records
# an attempt WITHOUT retiring the command (the undo refuses while the wrong
# project is open in Resolve, and that is a state that clears itself when
# the editor switches project).
#
# `machine_state.resolve_journals` is the other half: a companion cannot be
# asked what journals it holds -- there is no inbound connection to an
# editor's PC -- so it reports them, capped, on the same channel everything
# else rides. Without it the admin would have to type a filename they have
# no way to know.
SCHEMA_V40 = """
CREATE TABLE IF NOT EXISTS resolve_undo_requests (
  id              INTEGER PRIMARY KEY AUTOINCREMENT,
  editor_username TEXT NOT NULL,
  machine         TEXT NOT NULL,
  journal_id      TEXT NOT NULL,
  project_name    TEXT NOT NULL DEFAULT '',
  requested_by    TEXT NOT NULL,
  requested_at    TEXT NOT NULL,
  delivered_at    TEXT,
  applied_at      TEXT,
  ok              INTEGER,
  state           TEXT,
  attempts        INTEGER NOT NULL DEFAULT 0,
  detail          TEXT NOT NULL DEFAULT ''
);
CREATE INDEX IF NOT EXISTS ix_resolve_undo_machine
  ON resolve_undo_requests(editor_username, machine, applied_at, id);
ALTER TABLE machine_state ADD COLUMN resolve_journals TEXT;
"""

# v41: the FLEET JOB QUEUE (docs/TIMELINE-CARDS-INTO-CCSYNC.md §4.1, phase 0,
# 2026-08-29). Until now this dashboard had exactly one job concept -- ytdl's
# download lease -- and it is welded to that feature's own table. This is the
# general one: a row of work, a set of hard requirements, and a lease.
#
# The lease columns are ytdl's, deliberately, down to their names
# (`claimed_by` + `claimed_machine` + `lease_expires_at`): possession EXPIRES
# rather than being released, because the holder can vanish without telling
# anyone, and the key is (editor, MACHINE) because one person's laptop and
# desktop are two executors (CR-66).
#
# `inputs_json` carries (root name, relative path) PAIRS and never an absolute
# path (§4.1). The vault is X:\ on one machine, /vault in a container and
# a UNC path on the wire; a path on the wire would be right on exactly one
# computer. Same discipline as POST /music/send's {action, share, rel_path}.
#
# `requires_json` is the hard capability filter and `cost_json` an estimate
# nothing is yet allowed to schedule on -- both JSON because they are the
# fields whose shape is still being learned, and neither is ever sorted or
# alarmed on. Everything the grid or the scheduler reads IS a column.
SCHEMA_V41 = """
CREATE TABLE IF NOT EXISTS jobs (
  id               INTEGER PRIMARY KEY AUTOINCREMENT,
  kind             TEXT    NOT NULL,
  created_at       TEXT    NOT NULL,
  created_by       TEXT    NOT NULL DEFAULT '',
  priority         INTEGER NOT NULL DEFAULT 0,
  inputs_json      TEXT    NOT NULL DEFAULT '{}',
  requires_json    TEXT    NOT NULL DEFAULT '{}',
  cost_json        TEXT    NOT NULL DEFAULT '{}',
  state            TEXT    NOT NULL DEFAULT 'queued',
  claimed_by       TEXT,
  claimed_machine  TEXT,
  lease_expires_at TEXT,
  heartbeat_at     TEXT,
  attempts         INTEGER NOT NULL DEFAULT 0,
  last_error       TEXT    NOT NULL DEFAULT '',
  result_json      TEXT,
  updated_at       TEXT    NOT NULL
);
CREATE INDEX IF NOT EXISTS ix_jobs_state_kind ON jobs(state, kind, priority, id);
CREATE INDEX IF NOT EXISTS ix_jobs_holder
  ON jobs(claimed_by, claimed_machine, state);
CREATE INDEX IF NOT EXISTS ix_jobs_lease ON jobs(state, lease_expires_at);
"""

# v42: WHAT EACH MACHINE CAN DO (TIMELINE-CARDS-INTO-CCSYNC.md §4.3, phase 0,
# 2026-08-29). Flat columns on machine_state, exactly as v20 did for b-roll
# ingest and for the same stated reason: the grid sorts and alarms on this,
# and "which computers have a GPU" is a fleet question a JSON blob cannot be
# asked.
#
# The companion has been able to answer most of this since the b-roll indexer
# shipped -- `broll_vlm_sidecar.gpu()`, `proxy_gen._has_nvenc`,
# `idle.seconds_idle()` -- and none of it has ever reached this database
# except as a refusal string in `ingest_warning`. That is the gap this
# migration closes, and it is what makes the job scheduler's first filter
# possible at all.
#
# `cap_idle_seconds` IS NULLABLE ON PURPOSE and null is not zero: null means
# the machine cannot tell how long it has been idle, which every reader must
# treat as NOT IDLE (idle.py's contract). Zero means somebody is typing right
# now. A schema that folded them together would be the difference between
# using idle machines and transcoding under an editor's hands.
#
# `cap_at` is the marker column the write rule turns on: a report carrying the
# section replaces every value, a report without one changes nothing.
SCHEMA_V42 = """
ALTER TABLE machine_state ADD COLUMN cap_at TEXT;
ALTER TABLE machine_state ADD COLUMN cap_gpu_present INTEGER;
ALTER TABLE machine_state ADD COLUMN cap_gpu_name TEXT;
ALTER TABLE machine_state ADD COLUMN cap_gpu_vram_gb REAL;
ALTER TABLE machine_state ADD COLUMN cap_nvenc INTEGER;
ALTER TABLE machine_state ADD COLUMN cap_ffmpeg INTEGER;
ALTER TABLE machine_state ADD COLUMN cap_whisper INTEGER;
ALTER TABLE machine_state ADD COLUMN cap_whisper_detail TEXT;
ALTER TABLE machine_state ADD COLUMN cap_claude INTEGER;
ALTER TABLE machine_state ADD COLUMN cap_mounts TEXT;
ALTER TABLE machine_state ADD COLUMN cap_cpu_count INTEGER;
ALTER TABLE machine_state ADD COLUMN cap_idle_seconds REAL;
ALTER TABLE machine_state ADD COLUMN cap_load REAL;
ALTER TABLE machine_state ADD COLUMN cap_resolve_running INTEGER;
ALTER TABLE machine_state ADD COLUMN cap_resolve_project TEXT;
ALTER TABLE machine_state ADD COLUMN cap_jobs_enabled INTEGER;
"""

# v43: HOW FAR THROUGH A JOB IS, and one more capability (phase 1,
# 2026-08-30).
#
# `progress` is 0..1 and NULLABLE, and null is not zero: a runner that cannot
# say (a peaks pass reads its input in one gulp) leaves it null, and the grid
# then shows the job id rather than an invented "0%". It is a column and not
# the heartbeat's `note` because the note lands in `last_error` -- fine for a
# sentence about a failure, wrong for a number the fleet page renders every
# 15 s.
#
# `cap_ffprobe` is separate from `cap_ffmpeg` because the two recipes here
# need BOTH and they can genuinely be apart: ffprobe is what decides the
# proxy's GOP from the source's frame rate and what proves the extracted
# audio came out the same length it went in, and a machine with ffmpeg alone
# would claim the work and then guess.
SCHEMA_V43 = """
ALTER TABLE jobs ADD COLUMN progress REAL;
ALTER TABLE machine_state ADD COLUMN cap_ffprobe INTEGER;
"""

# v44: IS THIS COMPUTER SERVING THE TIMELINE CARDS PAGE (phase 2, 2026-08-30).
#
# Five flat columns beside the other capabilities, for the reason v42 gave and
# not a JSON blob: the grid renders them and an admin has to be able to ask
# "which machine has Resolve open on the cut" without decoding a document.
#
# `cap_cards_state` is the one that earns its keep. `connected` false is the
# normal state on every machine in the fleet, and the interesting question is
# always WHICH refusal: nobody turned it on, or a standalone agent is still
# running there and the companion stood down (CR-68). That is the [ VRAM ]
# chip's lesson again -- a capability that is off because of a machine's own
# state must say so somewhere other than a log on the machine nobody is at.
SCHEMA_V44 = """
ALTER TABLE machine_state ADD COLUMN cap_cards_connected INTEGER;
ALTER TABLE machine_state ADD COLUMN cap_cards_state TEXT;
ALTER TABLE machine_state ADD COLUMN cap_cards_timeline TEXT;
ALTER TABLE machine_state ADD COLUMN cap_cards_version INTEGER;
ALTER TABLE machine_state ADD COLUMN cap_cards_since REAL;
"""

# v45: BACKPRESSURE AND THE ALLOW-LIST (phase 4, 2026-08-30).
#
# Three columns, one idea between them: a scheduler needs to be able to say
# NO for a reason that is not "nothing can do this".
#
# `jobs_cooldown_until` is how long this machine is left alone after it hands
# a job back failed. Without it a machine with a broken ffmpeg is the FIRST
# to be offered the retry every time -- it is idle, after all, precisely
# because it is failing everything in seconds -- and a two-attempt budget is
# spent by one bad machine in under a minute. `jobs_cooldown_reason` is what
# the why page shows, because "this machine is cooling down" with no cause is
# the same unanswerable shrug the whole phase exists to remove.
#
# `cap_job_kinds` is the machine's OWN allow-list (`[jobs] kinds` in its
# config), reported like every other capability and honoured by the offer
# filter. Phase 1 left this open: today an editor's laptop can only be taken
# out of the fleet entirely (`jobs_enabled = false`), and "this laptop may
# transcode a proxy overnight but must never be handed a whisper pass" was
# unsayable. NULL means the machine never said, which is ALL KINDS -- a
# companion older than phase 4 keeps the behaviour it shipped with, and an
# empty JSON list means all kinds too, because that is what an unset config
# key spells over there.
# `cancel_requested_at` / `_by` are the other half of the same sentence: an
# admin can stop a job, and stopping one that is RUNNING is not a database
# write -- it is a message to the machine holding it, re-sent on every report
# until that machine answers. The columns are what makes the re-send possible
# across a dashboard restart, and what the jobs page shows as "cancelling".
SCHEMA_V45 = """
ALTER TABLE jobs ADD COLUMN cancel_requested_at TEXT;
ALTER TABLE jobs ADD COLUMN cancel_requested_by TEXT;
ALTER TABLE machine_state ADD COLUMN jobs_cooldown_until TEXT;
ALTER TABLE machine_state ADD COLUMN jobs_cooldown_reason TEXT;
ALTER TABLE machine_state ADD COLUMN cap_job_kinds TEXT;
"""

# v46: FORCE, TARGET AND VOLUNTEER (§10, 2026-08-30).
#
# Alex, after reading phase 4: "Is there an ability to force start the
# proxy/whisper workflow in the companion, without waiting for someone's idle
# PC to process it?" There was not. Everything the scheduler knows how to say
# was a reason to WAIT, and the only lever an admin had over a fleet of
# machines with people sitting at them was to go and ask one of them to stand
# up.
#
# Three columns, one idea between them: somebody may say "now".
#
# `jobs.forced` is the admin's. It skips the idle floor, the per-machine
# cooldown and the rank grace on every machine offered THIS job -- and
# nothing else: a fleet halt, a machine halt, an update waiting, a tripped
# breaker, `jobs_enabled`, the machine's own `jobs_kinds` and the capability
# filter all still refuse it. "Force" means "do not wait for anybody to leave
# their desk", never "run on a machine that cannot".
#
# It is `forced` and not `force` so the column name never argues with SQL,
# and it is a column rather than a flag inside `inputs_json` because the
# scheduler reads it on every offer of every job and the jobs page renders it.
#
# `jobs.target_machine` is the other half of the same lever: the job goes to
# ONE named machine and nobody else. An unknown name is accepted on purpose
# (the receipt says nobody by that name has reported) -- a machine that is
# switched off today may report tomorrow, and refusing the submission would
# make the admin guess at the exact spelling with nothing to check it against.
#
# `machine_state.cap_volunteer_until` is the PERSON's, and it is deliberately
# not a dashboard button: a machine's editor is the one who knows whether
# they mind their GPU being used while they work, so the lever is the tray's
# and this column only records what they chose. NULL is "not volunteering",
# which is what every companion older than 0.9.61 says by saying nothing.
SCHEMA_V46 = """
ALTER TABLE jobs ADD COLUMN forced INTEGER NOT NULL DEFAULT 0;
ALTER TABLE jobs ADD COLUMN target_machine TEXT;
ALTER TABLE machine_state ADD COLUMN cap_volunteer_until TEXT;
"""

# v47: IS THE 8899 LOOPBACK ACTUALLY HELD (CMEDIA-3, usability sweep
# 2026-09-04).
#
# Five flat columns beside the other guard sections rather than a JSON blob,
# for the reason v44 gives: the grid renders them, and "which machine cannot
# take a Send to Resolve" has to be answerable without decoding a document.
#
# `loopback_bound` false with `loopback_enabled` true is the whole point --
# the feature is on and the port is somebody else's (the absorbed standalone
# BRoll Companion is the known holder), so every click in the b-roll and
# music UIs fails in the browser and nothing on the fleet page says why.
# NULL everywhere means a companion too old to report it, which is not the
# same answer as "bound" and must never be rendered as one.
SCHEMA_V47 = """
ALTER TABLE machine_state ADD COLUMN loopback_enabled INTEGER;
ALTER TABLE machine_state ADD COLUMN loopback_bound INTEGER;
ALTER TABLE machine_state ADD COLUMN loopback_port INTEGER;
ALTER TABLE machine_state ADD COLUMN loopback_error TEXT;
ALTER TABLE machine_state ADD COLUMN loopback_since TEXT;
"""

# v48: when a build was handed to the fleet, and what a machine REFUSED
# (REL-6 / REL-3, usability sweep 2026-09-04).
#
# `made_current_at` is the clock every rollout question is asked against.
# `published_at` is the SIGNER's, `staged_at` is when the bytes landed, and
# neither is when the fleet was first offered this build -- a build can sit
# staged for a week and then be made current in a second, so "is anyone taking
# it" had no start time to measure from. Backfilled NULL on purpose: for a
# build already current when this migration runs we genuinely do not know, and
# a COALESCE onto published_at would date a rollout to a moment nobody was
# ever offered anything (which is exactly the false "stalled for six days"
# a rollout alert must never invent). NULL reads as "cannot tell".
#
# The three `upgrade_refused_*` columns are REL-3's half. An offer a companion
# refuses at RECEIPT (a signature it will not trust, a version below its
# downgrade floor, plain HTTP) produces no attempt, so `upgrade_attempts`
# stays 0 and the machine renders exactly like one that has simply not
# reported yet -- the one upgrade failure that can never self-heal was the one
# with no evidence anywhere but that editor's own log. They are the home for
# `sync_guard.upgrade.refused_version` / `refused_reason` / `refused_at`;
# every reader here treats absent/NULL as "not refusing", so a fleet whose
# companions are too old to send them is unchanged rather than wrong.
SCHEMA_V48 = """
ALTER TABLE companion_packages ADD COLUMN made_current_at TEXT;
ALTER TABLE machine_state ADD COLUMN upgrade_refused_version TEXT;
ALTER TABLE machine_state ADD COLUMN upgrade_refused_reason TEXT;
ALTER TABLE machine_state ADD COLUMN upgrade_refused_at TEXT;
"""

# v49: WHAT'S NEW, AND WHICH COMPUTER THAT TOKEN IS HOLDING (APP-16 /
# DCORE-14, usability sweep 2026-09-04).
#
# `notes` is the one-line "what changed" a publisher may attach to a build.
# UNSIGNED and stored beside the record rather than inside it, deliberately:
# the release signature covers a fixed field list that every companion in the
# field mirrors (release_trust.RECORD_FIELDS / OPTIONAL_KIND_EXTRA_FIELDS),
# and a record carrying a field an older build's canonicaliser does not know
# is REFUSED by that build with no over-the-air recovery (REL-7, and the
# overlap-release rule sign_release.py spells out for requires_dashboard).
# A sentence an editor reads in the update dialog must never be able to make
# a build uninstallable, so it rides outside the signature exactly as
# `git_sha` does. It is display-only: nothing anywhere decides anything from
# it.
#
# `report_auth.token_id` is which per-editor credential that computer's LAST
# report actually authenticated with. `editor_report_tokens.last_used_at`
# already said WHEN a token was used and could never say BY WHICH COMPUTER --
# one editor can own two machines and hold one token -- so [ REVOKE ] could
# not name what it was about to stop reporting. Empty for the shared token
# and for every row written before this migration: unknown, never "none".
#
# The four `cap_cards_*` columns are RES-6 (same sweep): `cap_cards_state`
# alone could say a cards agent was not running and never why. `gate_state`
# and `detail` are the role's own words for the refusal, `last_poll_at` and
# `last_http_status` are the tunnel's -- an agent that is "running" and has
# not polled since Tuesday, or is polling into a 401, is exactly the machine
# whose phone shows a blank page with nothing on the fleet grid to explain
# it. All NULL is a companion too old to say, which must never render as OK.
SCHEMA_V49 = """
ALTER TABLE companion_packages ADD COLUMN notes TEXT NOT NULL DEFAULT '';
ALTER TABLE report_auth ADD COLUMN token_id TEXT NOT NULL DEFAULT '';
ALTER TABLE machine_state ADD COLUMN cap_cards_gate_state TEXT;
ALTER TABLE machine_state ADD COLUMN cap_cards_detail TEXT;
ALTER TABLE machine_state ADD COLUMN cap_cards_last_poll_at TEXT;
ALTER TABLE machine_state ADD COLUMN cap_cards_http_status INTEGER;
"""

# v50: THE SECOND CUSTOMER'S FOUR (wave 5 of the usability sweep,
# 2026-09-04): DCORE-4, DCORE-5, OPS-2/UX-14 and CMEDIA-1.
#
# `known_editors.suspended_*` is DCORE-4. Suspension is deliberately NOT a
# column on `users`: `users` exists only on a DASH_AUTH_METHOD=local site,
# and the button an owner reaches for ("pause the freelancer until next
# month") has to exist on the shipped smb shape too, where the only control
# the Users page had was DELETE. It acts on FLEET state -- the report path
# refuses, the enforce cycle removes the shares -- so it belongs on the
# fleet's own record of who an editor is. The plan (`selections`) is
# untouched by design: [ RESUME ] has to put back exactly what was there.
#
# `projects.archived_at/by` is DCORE-5. Archiving sets `active=0`, which is
# the flag every reader in this file already filters on, and the stamp is
# what stops the next collector pass resurrecting it (upsert_project's
# ON CONFLICT sets active=1 on every scan of a folder that still exists --
# and the folder DOES still exist, because archiving keeps the folder and the
# marker). Nothing here deletes: [ UNARCHIVE ] clears the stamp and the next
# pass brings the row back with its inventory.
#
# `pending_ssh_keys` is OPS-2/UX-14's second half. The wizard generates the
# key an account needs before its lanes can run, and until now the account
# had to exist first WITH that key -- a circle an owner could only escape by
# generating a keypair themselves. The wizard posts its public half under the
# identity token it has just been issued, and it lands HERE, not on the
# account: a queue an admin approves in one click, exactly as a Syncthing
# device id is approved today. A row in this table grants nothing.
#
# `cap_jobs_gate_*` is CMEDIA-1's dashboard half, beside the v49 `cap_cards_*`
# columns and written the same way. `jobs.local_work_words` reads
# capabilities["jobs_gate"], which nothing persisted: a machine holding 12 GB
# of VLM weights looked to the scheduler exactly like an idle one.
SCHEMA_V50 = """
ALTER TABLE known_editors ADD COLUMN suspended_at TEXT;
ALTER TABLE known_editors ADD COLUMN suspended_by TEXT;
ALTER TABLE known_editors ADD COLUMN suspended_reason TEXT;
ALTER TABLE projects ADD COLUMN archived_at TEXT;
ALTER TABLE projects ADD COLUMN archived_by TEXT;
ALTER TABLE machine_state ADD COLUMN cap_jobs_gate_reason TEXT;
ALTER TABLE machine_state ADD COLUMN cap_jobs_gate_detail TEXT;
CREATE TABLE IF NOT EXISTS pending_ssh_keys (
  username     TEXT NOT NULL,
  fingerprint  TEXT NOT NULL,
  key_text     TEXT NOT NULL,
  machine      TEXT NOT NULL DEFAULT '',
  submitted_at TEXT NOT NULL,
  source       TEXT NOT NULL DEFAULT 'wizard',
  PRIMARY KEY (username, fingerprint)
);
"""

# v51: which rows went out in ONE message (CR-190, 2026-09-04). The owner
# configured SMTP and got eleven separate emails inside the same minute, one
# per open finding: "I'm getting spammed with emails now." Delivery is a
# DIGEST now, one message per check cycle, but `alert_log` still keeps one row
# per finding because the dedup (`alert_recently_sent`), the recovery
# comparison (`_is_open`) and the page all read a row per (kind, subject).
# `batch_id` is the only thing missing to show them as what they were: rows
# that shared a message. Its own column rather than a reuse of `detail` or
# `sent_to` -- both carry a sink's own words and both are rendered on the
# page -- and empty on every per-event row (a webhook POST per finding really
# was N separate messages, so grouping them would be a lie).
SCHEMA_V51 = """
ALTER TABLE alert_log ADD COLUMN batch_id TEXT NOT NULL DEFAULT '';
CREATE INDEX IF NOT EXISTS ix_alert_log_batch ON alert_log(batch_id, id);
"""

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
    # 17-19 landed together on 2026-08-17 from three parallel work packages
    # (ZERO_TOUCH_PLAN.md WP C / D / E), each written in its own worktree
    # with its number fixed in advance so they could merge without renumbering.
    (17, SCHEMA_V17),
    (18, SCHEMA_V18),
    (19, SCHEMA_V19),
    (20, SCHEMA_V20),
    (21, SCHEMA_V21),
    (22, SCHEMA_V22),
    (23, SCHEMA_V23),
    (24, SCHEMA_V24),
    (25, SCHEMA_V25),
    (26, SCHEMA_V26),
    (27, SCHEMA_V27),
    (28, SCHEMA_V28),
    (29, SCHEMA_V29),
    # 30 and 31 landed together from two parallel work packages of the same
    # sweep (resilience sweep 2026-08-28), each with its number fixed in
    # advance so the two could merge without renumbering -- exactly as 17-19
    # did.
    (30, SCHEMA_V30),
    (31, SCHEMA_V31),
    # 32 (liveness/disk) and 33 (why-not-syncing/diagnostics) are the second
    # pair of the same sweep, numbered in advance for the same reason.
    (32, SCHEMA_V32),
    (33, SCHEMA_V33),
    # 34 (the release channel: staged rollout, recall, ordering, arch) and 35
    # (dashboard self-update / auth) are the third pair of the same sweep,
    # numbered in advance so two work packages could land without renumbering.
    (34, SCHEMA_V34),
    (35, SCHEMA_V35),
    # 36 (file moves: state machine + retry/undo linkage), 37 (the notices
    # ledger) and 38 (alerts + the new report sections) are the fourth group
    # of the same sweep, each number fixed in advance so three work packages
    # could land in one commit without renumbering. They must ship TOGETHER:
    # a database that reached 37 without 36 having been in the list will
    # never run 36, because migrate() only ever moves forward.
    (36, SCHEMA_V36),
    (37, SCHEMA_V37),
    (38, SCHEMA_V38),
    # 39, 40 and 41 were WAVE 5's numbers, fixed in advance and reserved per
    # work package so the parallel packages could merge without renumbering --
    # the same discipline 17-19 and 36-38 used. Two were taken:
    #
    #   39  the continuous invariant checker's ledger (SYS-9).
    #   40  the recovery package's (SYS-15): the admin-side Resolve undo's
    #       request ledger, and the journals a machine reports so an admin can
    #       name one. The snapshot restore and the restore drill deliberately
    #       add no table -- they write files into a quarantine directory and a
    #       date into `meta`, and neither has history worth querying.
    #   41  UNUSED. It was the protection panel's (SYS-14), which chose `meta`
    #       instead: what that panel keeps is a small current picture (the last
    #       verdict per line) plus two admin-set dates, the same shape
    #       META_ALERTS_OPEN and NOTICE_CHECKS_META already use. A migration
    #       every customer's database has to run, to add a table a JSON blob
    #       holds, is a migration not worth the number.
    #
    # THE LIST MUST STAY GAPLESS (test_db's ordering test): a reserved number
    # that goes unused is renumbered away, never left as a hole, which is why
    # the recovery package moved down into 40 when the panel gave it up.
    (39, SCHEMA_V39),
    (40, SCHEMA_V40),
    # 41 is the fleet job queue (TIMELINE-CARDS-INTO-CCSYNC.md phase 0). The
    # number wave 5's protection panel gave up is taken here rather than left
    # as a hole -- THE LIST MUST STAY GAPLESS (test_db's ordering test).
    (41, SCHEMA_V41),
    # 42: the capabilities the scheduler filters on. It ships WITH 41 in
    # phase 0, but as its own step: the queue is useful with no capability
    # reported (every job simply waits, visibly), and the columns are useful
    # with no queue.
    (42, SCHEMA_V42),
    # 43: phase 1's two columns. One step, not two, because they ship
    # together and neither is useful before the other: a media job with no
    # ffprobe capability is never offered, and a job that is never offered
    # has no progress to report.
    (43, SCHEMA_V43),
    # 44: the cards role's own state (phase 2). Its own step because it is
    # its own feature: the queue and the media columns are useful on a fleet
    # that never serves a page, and these are useful on the one machine that
    # does.
    (44, SCHEMA_V44),
    # 45: phase 4's backpressure (the per-machine cooldown) and the
    # per-machine kind allow-list. One step: they are the same feature seen
    # from the two ends -- the server's reason to hold off, and the machine's
    # own.
    (45, SCHEMA_V45),
    # 46: the three levers of §10 (force, target, volunteer). One step: they
    # are one feature seen from the two ends -- the admin saying "now" and
    # the person at the machine saying "go ahead" -- and a database that had
    # one without the others would answer half of every scheduling question.
    (46, SCHEMA_V46),
    # 47: the loopback server's health (CMEDIA-3, usability sweep
    # 2026-09-04). Its own step, and gapless like every one before it.
    (47, SCHEMA_V47),
    # 48: the rollout clock and the refused offer (REL-6 / REL-3, usability
    # sweep 2026-09-04). One step, and gapless like every one before it.
    (48, SCHEMA_V48),
    # 49: the package note and the token's computers (APP-16 / DCORE-14,
    # usability sweep 2026-09-04). One step, and gapless like every one
    # before it: two unrelated columns, but a schema number is a shared
    # resource and a wave that takes one number per finding runs out of them.
    (49, SCHEMA_V49),
    # 50: the second customer's four (wave 5, 2026-09-04). ONE number for the
    # whole wave on purpose, and gapless like every one before it: this wave
    # runs five parallel work packages and a schema number is a shared
    # resource, so the four unrelated groups of columns land in one step
    # rather than four.
    (50, SCHEMA_V50),
    # 51: the alert digest's batch id (CR-190, 2026-09-04). One column, and
    # gapless like every one before it.
    (51, SCHEMA_V51),
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


# --------------------------------------------------- pending SSH keys (v50)
#
# OPS-2 / UX-14 (usability sweep 2026-09-04). Creating an editor account
# demanded an SSH public key that only the wizard generates, and the wizard
# cannot run until the account exists. The wizard posts its public half here
# under the identity token /api/v1/verify has just issued it; an admin
# approves it in one click on the Users page, exactly as they approve a
# Syncthing device id today.
#
# A ROW HERE GRANTS NOTHING. It is a queue, not a keystore: nothing reads it
# except the Users page and the approve button, and approving is what calls
# the account backend. Keyed on the fingerprint so a wizard re-run (or a
# second computer with its own key) is an upsert of the same row rather than
# a queue that grows every time somebody presses RETRY INSTALL.

PENDING_SSH_KEY_MAX_CHARS = 4096


def add_pending_ssh_key(
    conn: sqlite3.Connection, username: str, fingerprint: str, key_text: str, *,
    machine: str = "", source: str = "wizard", now: str | None = None,
) -> None:
    conn.execute(
        """INSERT INTO pending_ssh_keys
             (username, fingerprint, key_text, machine, submitted_at, source)
           VALUES (?, ?, ?, ?, ?, ?)
           ON CONFLICT(username, fingerprint) DO UPDATE SET
             key_text=excluded.key_text, machine=excluded.machine,
             submitted_at=excluded.submitted_at, source=excluded.source""",
        (str(username or "").strip().lower(), str(fingerprint or ""),
         str(key_text or "")[:PENDING_SSH_KEY_MAX_CHARS], str(machine or "")[:128],
         now or utcnow_iso(), str(source or "wizard")[:32]),
    )


def fetch_pending_ssh_keys(
    conn: sqlite3.Connection, username: str | None = None,
) -> list[dict[str, Any]]:
    q = "SELECT * FROM pending_ssh_keys"
    params: list[Any] = []
    if username is not None:
        q += " WHERE username=?"
        params.append(str(username).strip().lower())
    q += " ORDER BY submitted_at DESC, username"
    try:
        rows = conn.execute(q, params).fetchall()
    except sqlite3.OperationalError:
        return []
    return [dict(r) for r in rows]


def get_pending_ssh_key(
    conn: sqlite3.Connection, username: str, fingerprint: str,
) -> dict[str, Any] | None:
    row = conn.execute(
        "SELECT * FROM pending_ssh_keys WHERE username=? AND fingerprint=?",
        (str(username or "").strip().lower(), str(fingerprint or "")),
    ).fetchone()
    return dict(row) if row else None


def drop_pending_ssh_key(
    conn: sqlite3.Connection, username: str, fingerprint: str,
) -> bool:
    cur = conn.execute(
        "DELETE FROM pending_ssh_keys WHERE username=? AND fingerprint=?",
        (str(username or "").strip().lower(), str(fingerprint or "")),
    )
    return bool(cur.rowcount)


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


def report_token_id(token: str) -> str:
    """The PUBLIC half of a cce1 token, "" for anything else (DCORE-14).

    The id is not a secret (it is on the Users page already); the 48-hex
    second group is, and nothing outside this module ever needs it. Callers
    that want to record which credential a report used ask for this rather
    than slicing the string themselves."""
    match = _REPORT_TOKEN_RE.match(str(token or ""))
    return match.group(1) if match else ""


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
    now: str | None = None, token_id: str = "",
) -> None:
    """Which credential this machine's last report used. Migration telemetry.

    See count_shared_token_machines: the answer to "is it safe to turn
    DASH_SHARED_REPORT_TOKEN_ENABLED off yet" has to come from the fleet, not
    from an operator's memory of who they handed tokens to.

    `token_id` (v49, DCORE-14) is WHICH per-editor token, so [ REVOKE ] can
    name the computers it is about to stop. Empty for the shared token, which
    identifies nobody by construction."""
    name = str(editor or "").strip().lower()
    if not name or auth_kind not in ("shared", "editor"):
        return
    conn.execute(
        "INSERT INTO report_auth (editor_username, machine, auth_kind, at, token_id) "
        "VALUES (?, ?, ?, ?, ?) "
        "ON CONFLICT(editor_username, machine) DO UPDATE SET "
        "auth_kind = excluded.auth_kind, at = excluded.at, "
        "token_id = excluded.token_id",
        (name, str(machine or ""), auth_kind, now or utcnow_iso(),
         str(token_id or "")),
    )


def machines_by_report_token(conn: sqlite3.Connection) -> dict[str, list[dict[str, Any]]]:
    """token_id -> the computers whose LAST report used it (DCORE-14).

    What [ REVOKE ] needs in front of it: revoking a token that a MacBook is
    holding stops that machine reporting within a minute, and the only cure
    is handing its editor a new one by hand. Nothing here refuses anything --
    the point is to say it before the click, not to guard the click.

    Tolerates a database that predates `report_auth` or its v49 column (an
    older dashboard.db mid-redeploy) by answering nothing at all, which
    renders as "we cannot tell which" rather than as "none".
    """
    out: dict[str, list[dict[str, Any]]] = {}
    try:
        rows = conn.execute(
            "SELECT editor_username, machine, at, token_id FROM report_auth "
            "WHERE auth_kind = 'editor' AND token_id <> '' "
            "ORDER BY editor_username, machine"
        ).fetchall()
    except sqlite3.Error:
        return out
    for row in rows:
        out.setdefault(str(row["token_id"]), []).append({
            "editor_username": row["editor_username"],
            "machine": row["machine"],
            "at": row["at"],
        })
    return out


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


def machine_modes(conn: sqlite3.Connection) -> dict[tuple[str, str], str]:
    """(editor, machine) -> "base" | "editor", for every machine that has
    ever reported (CR-28, 2026-08-18).

    `machine_state.mode` (v22) is the answer; `editor_media_project.mode` is
    the fallback for a machine that reported manifests before v22 and has not
    reported since. A machine with neither is absent from this map, and every
    caller treats absent as "editor" -- an unknown machine must not be
    silently excluded from the queue, which is the direction that hides real
    work."""
    modes: dict[tuple[str, str], str] = {}
    for sql in (
        "SELECT DISTINCT editor_username, machine, mode FROM editor_media_project",
        "SELECT editor_username, machine, mode FROM machine_state",
    ):
        for row in conn.execute(sql):
            mode = str(row["mode"] or "").strip().lower()
            if mode:
                modes[(row["editor_username"], row["machine"])] = mode
    return modes


def base_machines(conn: sqlite3.Connection) -> set[tuple[str, str]]:
    """(editor, machine) pairs that are WIRED to the NAS (dash-admin-8 /
    data-model-1, 2026-08-21).

    The per-machine predicate CR-28 should have had. `machine_state.mode` has
    been per machine since v22, but every gate consumed it through the
    base_only_editors rollup, which is true only when EVERY one of a person's
    machines is wired -- and a site can have more than one wired machine and
    a person can own one of each (commit f27c181, MULTI_BASE_RIG_PLAN.md §5).
    Absent from machine_modes still means "editor": an unknown machine must
    not be silently excluded from the queue."""
    return {pair for pair, mode in machine_modes(conn).items() if mode == "base"}


def base_only_editors(conn: sqlite3.Connection) -> set[str]:
    """Usernames whose every known machine is a base rig.

    The base rig works directly off the NAS tree: it syncs nothing, so it can
    never make progress against a tick, and a tick on its account is what put
    `alex · 2026/FF5/Animals [ GETTING READY ]` on the fleet page permanently
    (CR-28). An account with NO machines at all is not base-only -- it is
    unknown, and unknown must not be treated as "cannot sync"."""
    by_editor: dict[str, set[str]] = {}
    for (editor, _machine), mode in machine_modes(conn).items():
        by_editor.setdefault(editor, set()).add(mode)
    return {editor for editor, modes in by_editor.items() if modes == {"base"}}


# ------------------------------------------------------ suspension (v50)
#
# DCORE-4 (usability sweep 2026-09-04). ONE predicate, the way CR-28 has
# `base_only_editors`: every reader that decides what a computer receives asks
# `suspended_editors` and drops those people, so "suspended" cannot mean one
# thing to the report path and another to the enforce cycle.
#
# It is NOT a login flag. Disabling an account (local sites only) is about
# signing in; this is about the fleet, and it is the only "stop this person"
# control an smb site has that is not DELETE.

def suspend_editor(conn: sqlite3.Connection, editor: str, *, by: str,
                   reason: str = "", now: str | None = None) -> bool:
    """Suspend `editor` (idempotent). False if there is no such editor.

    Records the row first when the fleet has never seen this name written
    down: an account created on the NAS and never used still has to be
    suspendable, and record_known_editor is the same evidence trail the
    approve and create paths write."""
    name = str(editor or "").strip().lower()
    if not name or not _USERNAME_RE.match(name):
        return False
    # An editor this dashboard has no record of is a typo, not a person to
    # suspend: known_editor_usernames is the same four-source evidence test
    # the device-approve guard uses (CR-91).
    if name not in known_editor_usernames(conn):
        return False
    record_known_editor(conn, name, "admin", now)
    cur = conn.execute(
        "UPDATE known_editors SET suspended_at=?, suspended_by=?, suspended_reason=? "
        "WHERE editor_username=?",
        (now or utcnow_iso(), str(by or "?"), str(reason or "")[:255], name),
    )
    return bool(cur.rowcount)


def unsuspend_editor(conn: sqlite3.Connection, editor: str) -> bool:
    """Lift a suspension. The plan was never touched, so there is nothing to
    put back: the next enforce cycle re-shares exactly what was ticked."""
    name = str(editor or "").strip().lower()
    cur = conn.execute(
        "UPDATE known_editors SET suspended_at=NULL, suspended_by=NULL, "
        "suspended_reason=NULL WHERE editor_username=? AND suspended_at IS NOT NULL",
        (name,),
    )
    return bool(cur.rowcount)


def suspended_editors(conn: sqlite3.Connection) -> set[str]:
    """Usernames whose fleet access is suspended.

    Tolerates a database that predates v50 (an empty set, i.e. nobody is
    suspended): this is called from the enforce cycle and from the report
    path, and a missing column must never be able to unshare a fleet or turn
    a machine away."""
    try:
        rows = conn.execute(
            "SELECT editor_username FROM known_editors WHERE suspended_at IS NOT NULL")
    except sqlite3.OperationalError:
        return set()
    return {str(r[0] or "").strip().lower() for r in rows if r[0]}


def editor_suspension(conn: sqlite3.Connection, editor: str) -> dict[str, Any] | None:
    """{at, by, reason} for a suspended editor, else None."""
    name = str(editor or "").strip().lower()
    try:
        row = conn.execute(
            "SELECT suspended_at, suspended_by, suspended_reason FROM known_editors "
            "WHERE editor_username=?", (name,)).fetchone()
    except sqlite3.OperationalError:
        return None
    if row is None or not row["suspended_at"]:
        return None
    return {"at": row["suspended_at"], "by": row["suspended_by"] or "",
            "reason": row["suspended_reason"] or ""}


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
    # AN ARCHIVED PROJECT STAYS ARCHIVED (DCORE-5, v50). Archiving keeps the
    # folder and the marker on the NAS -- that is the whole point, nothing
    # here deletes -- so the folder is still in Syncthing's config and this
    # upsert runs for it on every collector pass. A bare `active=1` would
    # therefore un-archive it within 60 seconds, silently, and the shares
    # would come back with it.
    conn.execute(
        """INSERT INTO projects (slug, label, path, first_seen, last_seen, active)
           VALUES (?, ?, ?, ?, ?, 1)
           ON CONFLICT(slug) DO UPDATE SET
             label=excluded.label, path=excluded.path, last_seen=excluded.last_seen,
             active=CASE WHEN projects.archived_at IS NULL THEN 1 ELSE 0 END""",
        (slug, label, path, now, now),
    )
    return conn.execute("SELECT id FROM projects WHERE slug=?", (slug,)).fetchone()[0]


# ------------------------------------------------------- archive (v50)
#
# DCORE-5 (usability sweep 2026-09-04). Any signed-in editor can create a
# project -- deliberately, it is how a shoot starts on a Friday night -- and
# until now NOTHING could remove one: a typo became a permanent row in every
# editor's tick list, in the assignments grid and in the queue, and the only
# cure was deleting the folder on the NAS by hand and waiting for
# deactivate_missing_projects (which the DASH-4 brake may itself refuse).
#
# Archiving is reversible and touches no data: the folder, the marker, the
# files and every `selections` row survive. What changes is `active`, which
# is the flag every reader in this file already filters on, plus the enforce
# cycle dropping its shares (collector._run_enforce) -- the same "under-
# sharing is the safe direction" path a removed tick uses.

def archive_project(conn: sqlite3.Connection, slug: str, *, by: str,
                    now: str | None = None) -> bool:
    """Mark a project archived. False if there is no such project."""
    cur = conn.execute(
        "UPDATE projects SET active=0, archived_at=?, archived_by=? "
        "WHERE slug=? AND archived_at IS NULL",
        (now or utcnow_iso(), str(by or "?"), str(slug or "")),
    )
    return bool(cur.rowcount)


def unarchive_project(conn: sqlite3.Connection, slug: str) -> bool:
    """Put an archived project back. `active` goes back to 1 here rather than
    waiting for the next collector pass, so the row (and the ticks that were
    never removed) reappear on the page that pressed the button."""
    cur = conn.execute(
        "UPDATE projects SET active=1, archived_at=NULL, archived_by=NULL "
        "WHERE slug=? AND archived_at IS NOT NULL",
        (str(slug or ""),),
    )
    return bool(cur.rowcount)


def archived_project_slugs(conn: sqlite3.Connection) -> set[str]:
    """Slugs an admin has archived. Empty on a pre-v50 database: a missing
    column must never be read as "everything is archived", which would
    unshare the fleet."""
    try:
        rows = conn.execute(
            "SELECT slug FROM projects WHERE archived_at IS NOT NULL")
    except sqlite3.OperationalError:
        return set()
    return {str(r[0]) for r in rows if r[0]}


def fetch_archived_projects(conn: sqlite3.Connection) -> list[dict[str, Any]]:
    """Archived projects with the tick count each still holds, newest first.

    The count is what the [ UNARCHIVE ] row shows and what the archive
    confirm quoted before the click: those ticks are still in the table, and
    nothing about archiving removed them."""
    try:
        rows = conn.execute(
            """SELECT p.slug, p.label, p.archived_at, p.archived_by,
                      (SELECT COUNT(DISTINCT s.editor_username) FROM selections s
                        WHERE s.project_slug = p.slug) AS editors
               FROM projects p WHERE p.archived_at IS NOT NULL
               ORDER BY p.archived_at DESC, p.label""").fetchall()
    except sqlite3.OperationalError:
        return []
    return [dict(r) for r in rows]


def project_tick_editors(conn: sqlite3.Connection, slug: str) -> list[str]:
    """Who has this project ticked, on any of their computers. The number the
    archive confirm has to name: "3 editors sync it" is the difference
    between a typo and somebody's Monday."""
    return [
        str(r[0]) for r in conn.execute(
            "SELECT DISTINCT editor_username FROM selections WHERE project_slug=? "
            "ORDER BY editor_username", (str(slug or ""),))
    ]


def replace_project_links(
    conn: sqlite3.Connection, borrower_slug: str, rows: list[dict[str, Any]], now: str,
) -> None:
    """This borrower's cross-project links become exactly `rows` (each
    {declared_path, lender_slug, sub_rel, status, detail}); first_seen is
    kept for surviving keys. A borrower whose marker lost the `includes`
    key passes [] and its rows clear (SHARED_FOLDERS_PLAN.md §2.3)."""
    keep = [r["declared_path"] for r in rows]
    placeholders = ",".join("?" * len(keep)) or "''"
    conn.execute(
        f"DELETE FROM project_links WHERE borrower_slug=? "
        f"AND declared_path NOT IN ({placeholders})",
        [borrower_slug, *keep],
    )
    for r in rows:
        conn.execute(
            """INSERT INTO project_links
                 (borrower_slug, declared_path, lender_slug, sub_rel, status, detail,
                  first_seen, last_seen)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?)
               ON CONFLICT(borrower_slug, declared_path) DO UPDATE SET
                 lender_slug=excluded.lender_slug, sub_rel=excluded.sub_rel,
                 status=excluded.status, detail=excluded.detail,
                 last_seen=excluded.last_seen""",
            (borrower_slug, r["declared_path"], r.get("lender_slug"), r.get("sub_rel"),
             r["status"], r.get("detail"), now, now),
        )


def clear_links_of_vanished_borrowers(
    conn: sqlite3.Connection, scanned_slugs: Iterable[str],
) -> int:
    """Drop link rows of borrowers that are BOTH missing from this cycle's
    marker scan AND inactive as projects -- i.e. properly deleted, past the
    deactivation grace. Requiring both is deliberate: a transiently
    unreadable marker leaves the projects row active, and clearing on that
    alone would unshare the lender's folder from a whole fleet of borrower
    machines over one bad read (the B16 shape)."""
    slugs = list(scanned_slugs)
    placeholders = ",".join("?" * len(slugs)) or "''"
    cur = conn.execute(
        f"""DELETE FROM project_links
            WHERE borrower_slug NOT IN ({placeholders})
              AND borrower_slug NOT IN (SELECT slug FROM projects WHERE active=1)""",
        slugs)
    return cur.rowcount


def fetch_links_for_borrowers(
    conn: sqlite3.Connection, slugs: Iterable[str] | None = None,
) -> dict[str, list[dict[str, Any]]]:
    """borrower_slug -> [link rows], each row joined with the lender's
    current label (None when the lender row is gone). All statuses -- the
    UI shows the broken ones; selection expansion filters to ok itself."""
    q = """SELECT l.*, p.label AS lender_label,
                  p.active AS lender_active
           FROM project_links l
           LEFT JOIN projects p ON p.slug = l.lender_slug
           ORDER BY l.borrower_slug, l.declared_path"""
    grouped: dict[str, list[dict[str, Any]]] = {}
    want = set(slugs) if slugs is not None else None
    for row in conn.execute(q):
        r = dict(row)
        if want is not None and r["borrower_slug"] not in want:
            continue
        grouped.setdefault(r["borrower_slug"], []).append(r)
    return grouped


def fetch_borrowers_of(conn: sqlite3.Connection, lender_slug: str) -> list[dict[str, Any]]:
    """Link rows whose lender is `lender_slug` (ok only), with the borrower's
    label -- the lender project page's SHARED INTO block."""
    rows = conn.execute(
        """SELECT l.*, p.label AS borrower_label
           FROM project_links l
           LEFT JOIN projects p ON p.slug = l.borrower_slug
           WHERE l.lender_slug=? AND l.status='ok'
           ORDER BY l.borrower_slug, l.declared_path""",
        (lender_slug,),
    )
    return [dict(r) for r in rows]


def fetch_borrowers_by_lender(conn: sqlite3.Connection) -> dict[str, set[str]]:
    """lender_slug -> {borrower_slug, ...} for ok links -- the enforce
    cycle's one question (SHARED_FOLDERS_PLAN.md §4.1)."""
    grouped: dict[str, set[str]] = {}
    for row in conn.execute(
        "SELECT lender_slug, borrower_slug FROM project_links WHERE status='ok'"
    ):
        grouped.setdefault(row["lender_slug"], set()).add(row["borrower_slug"])
    return grouped


def deactivate_missing_projects(
    conn: sqlite3.Connection,
    seen_slugs: Iterable[str],
    now: str | None = None,
    grace_seconds: int = 900,
    force: bool = False,
) -> dict[str, Any]:
    """Deactivate projects whose Syncthing folder is gone -- EXCEPT rows seen
    recently. The grace window exists for eagerly-created projects (the
    /project-setup page inserts the row immediately; the collector's
    provision cycle creates the Syncthing folder up to 5 minutes later --
    without the grace, this would flip the new project inactive in the gap
    and break the link/create flow that just made it).

    BLAST-RADIUS BRAKE (DASH-4, resilience sweep 2026-08-28), the same shape
    the enforce cycle has had one function up for a year. A Syncthing whose
    config was re-created or restored answers /rest/config with 200 and ZERO
    folders while myID is perfectly valid, so none of the empty-myID guards
    fire: `seen` was [], every project flipped active=0, and the hourly
    prune's purge_nas_media_for_inactive then deleted the whole NAS
    inventory. Everything downstream reads active=1, so the project list and
    the fleet grid emptied out, nobody appeared behind, and api_tick answered
    404 so an admin could not even re-tick -- all silently, for the one thing
    this dashboard exists to say. Two refusals now: an EMPTY `seen` against a
    database that has active projects (never a legitimate steady state), and
    a pass that would deactivate more than max(2, 25%) of them. The refusal
    is persisted for the banner, not just logged, and it does not clear
    itself: the next healthy pass does.

    Returns {"deactivated": n, "refused": <record or None>}. `force=True`
    applies the pass whatever its size (there is no caller today; it exists
    so an admin tool need not re-implement the query).
    """
    slugs = list(seen_slugs)
    placeholders = ",".join("?" * len(slugs)) or "''"
    now = now or utcnow_iso()
    cutoff = (parse_iso(now) - dt.timedelta(seconds=grace_seconds)).isoformat()
    n_active = conn.execute(
        "SELECT COUNT(*) AS n FROM projects WHERE active=1").fetchone()["n"]
    candidates = [
        r["slug"] for r in conn.execute(
            f"SELECT slug FROM projects WHERE active=1 AND last_seen < ? "
            f"AND slug NOT IN ({placeholders}) ORDER BY slug",
            [cutoff, *slugs],
        )
    ]
    ceiling = max(2, n_active // 4)
    reason = None
    if not force and len(candidates) > ceiling:
        # ONE trigger, two wordings. The size test is what governs, so a small
        # site can still lose its one or two projects legitimately (the floor
        # of 2 is the same floor the finding proposed); the empty-`seen` case
        # gets its own sentence because "Syncthing reported 0 folders" is the
        # signature an operator needs to read, not a percentage.
        if not slugs:
            reason = (f"Syncthing reported 0 of {n_active} folders - "
                      f"not deactivating anything")
        else:
            reason = (f"Syncthing reported {len(slugs)} of {n_active} folders - "
                      f"not deactivating {len(candidates)} project(s)")
    if reason is not None:
        record = {"at": now, "message": reason, "seen": len(slugs),
                  "active": n_active, "would_deactivate": len(candidates),
                  "ceiling": ceiling, "projects": candidates[:100]}
        meta_set_json(conn, META_DEACTIVATION_REFUSAL, record)
        return {"deactivated": 0, "refused": record}
    if candidates:
        conn.execute(
            f"UPDATE projects SET active=0 WHERE active=1 AND last_seen < ? "
            f"AND slug NOT IN ({placeholders})",
            [cutoff, *slugs],
        )
    # A pass that came in under the brake is the evidence the last refusal is
    # over; nothing else clears it.
    meta_delete(conn, META_DEACTIVATION_REFUSAL)
    return {"deactivated": len(candidates), "refused": None}


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
    progress_token: str | None = None,
    state_since: str | None = None,
) -> None:
    """`progress_token` is the lane's own monotonic "real work happened"
    marker (SYS-1, resilience sweep 2026-08-28).

    The column this dashboard actually judges a stall on is
    `progress_token_since`, which is written HERE from the server's
    `received_at` and ONLY when the token differs from the stored one. That is
    the whole point of the contract: the companion cannot tell us how long it
    has been stuck (the thread that would notice is the one that is wedged),
    and it cannot accidentally reset the clock by re-sending the same token
    every 30 s either.

    A report carrying no token clears the stamp rather than keeping
    yesterday's: the lane has gone quiet or the build is too old to say, and
    health.lane_stall answers "no verdict" to both.
    """
    prev = conn.execute(
        """SELECT state, last_error, progress_token, progress_token_since
           FROM lane_report_current
           WHERE editor_username=? AND machine=? AND lane=?""",
        (editor_username, machine, lane),
    ).fetchone()
    token_since: str | None = None
    if progress_token:
        if (prev is not None and prev["progress_token"] == progress_token
                and prev["progress_token_since"]):
            token_since = prev["progress_token_since"]
        else:
            token_since = received_at
    conn.execute(
        """INSERT INTO lane_report_current
             (editor_username, machine, lane, state, queued, transferring, last_error,
              last_sync, detail, companion_version, reported_at, received_at,
              current_project, bytes_done, bytes_total, speed_bps, eta_seconds,
              progress_token, progress_token_since, state_since)
           VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
           ON CONFLICT(editor_username, machine, lane) DO UPDATE SET
             state=excluded.state, queued=excluded.queued, transferring=excluded.transferring,
             last_error=excluded.last_error, last_sync=excluded.last_sync,
             detail=excluded.detail, companion_version=excluded.companion_version,
             reported_at=excluded.reported_at, received_at=excluded.received_at,
             current_project=excluded.current_project, bytes_done=excluded.bytes_done,
             bytes_total=excluded.bytes_total, speed_bps=excluded.speed_bps,
             eta_seconds=excluded.eta_seconds,
             progress_token=excluded.progress_token,
             progress_token_since=excluded.progress_token_since,
             state_since=excluded.state_since""",
        (editor_username, machine, lane, state, queued, transferring, last_error,
         last_sync, detail, companion_version, reported_at, received_at,
         current_project, bytes_done, bytes_total, speed_bps, eta_seconds,
         progress_token, token_since, state_since),
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


def meta_delete(conn: sqlite3.Connection, key: str) -> None:
    conn.execute("DELETE FROM meta WHERE key=?", (key,))


# ------------------------------------------------------- collector alarms
#
# DASH-3 / DASH-4 (resilience sweep 2026-08-28). Two of the collector's
# safety brakes -- the enforce blast-radius refusal and the new deactivation
# refusal -- used to fire into the container log and nowhere else, so
# `poll_runs`, /api/v1/health and every page said the cycle was fine while
# every genuine untick sat unapplied. A brake nobody can see is not a brake
# (the wave-1 rule: never make a safety latch in-memory-only). `meta` rather
# than a new table because each of these has exactly one CURRENT value and no
# history worth keeping, and because a schema version is a shared resource.
META_ENFORCE_REFUSAL = "collector_enforce_refusal"
META_ENFORCE_PLAN = "collector_enforce_plan"
META_DEACTIVATION_REFUSAL = "collector_deactivation_refusal"


def meta_set_json(conn: sqlite3.Connection, key: str, value: Any) -> None:
    meta_set(conn, key, json.dumps(value, sort_keys=True))


def meta_get_json(conn: sqlite3.Connection, key: str) -> Any | None:
    """The JSON value at `key`, or None. Unparseable is None, never a raise:
    these feed a banner, and a bad row must not be able to 500 the page that
    tells the fleet whether footage is syncing."""
    raw = meta_get(conn, key)
    if not raw:
        return None
    try:
        return json.loads(raw)
    except (ValueError, TypeError):
        return None


# ------------------------------------------------------------- notices
#
# UX-10 (resilience sweep 2026-08-28). The server's refusals were correct and
# their messages were excellent, and they went to a Docker log. This is the
# channel that puts them on the page an owner actually looks at.
#
# The severities, spelled once so the template, the writers and the tests
# agree: "error" is footage not moving or projects not visible, "warn" is a
# condition that will become that, "info" is a fact worth stating.
NOTICE_SEVERITIES = ("info", "warn", "error")

# THE REGISTRY (owner's instruction, 2026-08-28: "make the server as
# self-diagnosing as possible"). Every condition this server knows how to
# find, with the severity it is written at and one line of what it means.
#
# It exists so silence can be read as "checked and fine" rather than
# "unchecked", which is the difference between a dashboard that is trusted and
# one that is merely quiet. The PROBLEMS panel renders this list with a tick
# beside every kind that has no open notice; the alerts sink reads the
# severity; the tests walk it.
#
# `href` (DDIAG-8, usability sweep 2026-09-03) is optional and belongs to the
# KIND, not to the row: the panel used to tell a non-technical owner to
# navigate by memory to a page whose name was written in prose, three levels
# into a twelve-entry settings strip, when every one of those targets is a URL
# this codebase already knows. It is a str, or a callable taking the notice's
# SUBJECT and returning one (the enforce/inventory kinds, whose destination is
# the project the subject names). A column would have needed a migration for a
# fact that never varies per row. The prose stays: a mail body has no links to
# offer, and `fix` is what the sink sends.


def _slug_href(subject: str) -> str:
    """The project page when the subject IS a project slug, the fleet page
    otherwise (DDIAG-8). Deliberately a shape test and not a lookup: this runs
    per rendered row and must not take a database connection, and a link to
    the fleet page is a harmless miss where a 404 would not be."""
    slug = str(subject or "").strip()
    if slug and all(ch.isalnum() or ch in "._-" for ch in slug):
        return f"/project/{slug}"
    return "/fleet"


def _plan_pair_href(subject: str) -> str:
    """`plan_without_share`'s subject is "editor/machine -> slug", and the
    untick-and-re-tick its fix names is on that project's page."""
    _, _, slug = str(subject or "").partition("->")
    return _slug_href(slug.strip()) if slug.strip() else "/fleet"


NOTICE_KINDS: dict[str, dict[str, Any]] = {
    # -- discovery and provisioning (collector.py / provision.py) ----------
    "project_container_marker": {"severity": "error", "what":
        "a project marker dropped on a folder that CONTAINS projects, which hides them all"},
    "project_nested_marker": {"severity": "error", "what":
        "a project marker inside another project, which projects may not do"},
    "duplicate_syncthing_folder": {"severity": "error", "what":
        "two Syncthing folders over one directory, only one of which editors are on"},
    "duplicate_slug_dirs": {"severity": "error", "what":
        "one project identity claimed by two directories on the server"},
    "unreadable_project_marker": {"severity": "warn", "what":
        "a damaged .ccsync-project marker, so that folder is not a project to anyone"},
    "provision_failed": {"severity": "error", "what":
        "a project folder that could not be set up for syncing"},
    "shared_assets_failed": {"severity": "error", "what":
        "the shared asset libraries (the LUT library) could not be set up"},
    "project_links_failed": {"severity": "warn", "what":
        "a shared-folder link between projects could not be resolved"},
    # -- the collector itself ----------------------------------------------
    "collector_cycle_failed": {"severity": "error", "what":
        "one of the background jobs that keeps the fleet in step is failing",
        "href": "/fleet#fleet-diagnostics"},
    "collector_db_write_failed": {"severity": "error", "what":
        "the dashboard could not write to its own database",
        "href": "/admin/packages"},
    "collector_watchdog_restart": {"severity": "warn", "what":
        "the background job thread died and had to be restarted",
        "href": "/fleet#fleet-diagnostics"},
    "syncthing_unreachable": {"severity": "error", "what":
        "the sync engine on this server is not answering",
        "href": "/fleet#fleet-diagnostics"},
    # -- the tree -----------------------------------------------------------
    "projects_dir_missing": {"severity": "error", "what":
        "the projects folder on the server is missing or not mounted"},
    "inventory_refused": {"severity": "error", "what":
        "the server's file count collapsed, so the last good one is being kept",
        "href": _slug_href},
    "enforce_refusal": {"severity": "error", "what":
        "too many share removals in one pass, so none were applied",
        "href": _slug_href},
    "deactivation_refusal": {"severity": "error", "what":
        "too many projects would have been marked gone at once, so none were"},
    "ignored_report_sections": {"severity": "warn", "what":
        "a computer is sending information this dashboard is too old to store",
        "href": "/admin/packages"},
    # -- identity and plans --------------------------------------------------
    "duplicate_machine_id": {"severity": "error", "what":
        "one computer identity claimed by two hostnames (a cloned computer)",
        "href": "/fleet"},
    "duplicate_device_id": {"severity": "error", "what":
        "one Syncthing device id claimed by two computers",
        "href": "/fleet"},
    "pending_device_approval": {"severity": "warn", "what":
        "a computer has been waiting to be approved for the sync network",
        "href": "/admin/users"},
    "plan_without_share": {"severity": "error", "what":
        "a project is ticked for a computer that is not being sent it",
        "href": _plan_pair_href},
    "share_without_plan": {"severity": "warn", "what":
        "a computer is being sent a project nobody ticked for it",
        "href": "/fleet"},
    "editor_without_machine": {"severity": "info", "what":
        "an editor account no computer has ever reported for",
        "href": "/admin/users"},
    # -- the invariant checker (SYS-9, wave 5) --------------------------------
    "invariant_broken": {"severity": "error", "what":
        "a fact this system relies on has stopped being true (the invariant checks)",
        "href": "/admin/invariants"},
    "invariant_check_failed": {"severity": "error", "what":
        "one of the invariant checks could not run, so that fact is unchecked",
        "href": "/admin/invariants"},
    # -- what is protected (SYS-14, wave 5) -----------------------------------
    # The INVERTED default: a safety mechanism this server cannot positively
    # verify is reported, not passed over. `protection_unverifiable` is a warn
    # rather than an error because amber-forever is an honest answer on a NAS
    # whose schedules have no API (DSM), and an error would train an owner to
    # ignore the panel that carries the real ones.
    "protection_missing": {"severity": "error", "what":
        "a safety net this system relies on is not there (snapshots, signing, backups)",
        "href": "/admin/protection"},
    "protection_unverifiable": {"severity": "warn", "what":
        "a safety net this server cannot check, so it is unknown rather than fine",
        "href": "/admin/protection"},
    # -- space ---------------------------------------------------------------
    "dashboard_disk_low": {"severity": "error", "what":
        "the volume this dashboard writes to is nearly full",
        "href": "/admin/packages"},
    "machine_disk_low": {"severity": "warn", "what":
        "an editor's computer is nearly out of room for footage",
        "href": "/fleet"},
    "machine_trash_oversize": {"severity": "warn", "what":
        "deleted-file safety copies on a computer have grown large",
        "href": "/fleet"},
    # DDIAG-3 (usability sweep 2026-09-03). A machine that has been retired,
    # reinstalled under another hostname or taken on a three-week shoot was an
    # `error` ALERT re-mailed once a day for ever. Past the give-up line it
    # becomes this: a standing warn on the panel, naming the one action that
    # ends it. Written by notices._check_forgotten_machines.
    "machine_forgotten": {"severity": "warn", "what":
        "a computer stopped reporting long enough that we gave up asking about it",
        "href": "/fleet"},
    # -- the mounted apps (DDIAG-7, usability sweep 2026-09-03) ---------------
    # Each of /broll, /music, /ytdl and /cards computes a careful tri-state
    # with a sentence in `detail`, and that sentence went to the container log
    # and the authenticated health body only: on the page the topbar link
    # simply disappeared, so "where has B-ROLL gone" had no answer anywhere.
    "feature_not_mounted": {"severity": "warn", "what":
        "one of the extra pages (b-roll, music, YouTube, cards) did not start on this server",
        "href": "/fleet#fleet-diagnostics"},
    # -- the release channel ---------------------------------------------------
    "feed_unreachable": {"severity": "warn", "what":
        "the vendor release feed cannot be reached, so no new builds arrive",
        "href": "/admin/packages"},
    # SYS-2 (2026-09-04). "Deploy the dashboard before the companions" is a
    # refusal the feed poller makes correctly and used to state only in a log
    # line, on a site whose policy is `current` and where nobody clicks
    # anything: the fleet then reads as up to date for ever because the build
    # that would have made it outdated was never published here.
    "feed_publish_refused": {"severity": "error", "what":
        "a new build for the fleet cannot be handed out until this dashboard is updated",
        "href": "/admin/packages"},
    "feed_runtime_mismatch": {"severity": "warn", "what":
        "a build on offer was made for a different system than this one",
        "href": "/admin/packages"},
    # -- configuration and faults ---------------------------------------------
    "insecure_secret": {"severity": "error", "what":
        "a password or token in this server's configuration has quotes or spaces around it"},
    "dev_insecure": {"severity": "error", "what":
        "this server is running with its security checks relaxed"},
    "server_error": {"severity": "error", "what":
        "a page or an API call failed with an error",
        "href": "/fleet#fleet-diagnostics"},
    # DDIAG-1 (2026-09-04). The pass ran out of its delivery budget, so some
    # of what it found was left for the next cycle. Written by alerts.run_cycle
    # (never registered without its writer, finding 1 of the 08-28 fix pass).
    "alerts_delivery_slow": {"severity": "warn", "what":
        "sending the alerts took so long that some were left for the next pass",
        "href": "/admin/alerts"},
    # SYS-1(c) (usability sweep 2026-09-03). Every detector in this product
    # runs into an empty room on the vendor default, and the panel that
    # reports what is NOT there had no line for the mechanism that delivers
    # all the others. Written by notices._check_alerts_sink.
    "alerts_sink_none": {"severity": "warn", "what":
        "nobody is being told when this server finds a problem",
        "href": "/admin/alerts"},
    # DDIAG-10 (usability sweep 2026-09-03). crash_report.py has written
    # <data>/crashes/*.json since 2026-08-17 and nothing has ever read that
    # directory: the collector's own thread dying was visible only to somebody
    # with a shell in the container, which is the person this whole sweep
    # assumes does not exist.
    "server_crash_report": {"severity": "error", "what":
        "this server's own background tasks have crashed since it started",
        "href": "/admin/diagnostics/crash-reports.zip",
        "href_label": "[ DOWNLOAD CRASH REPORTS ]"},
}


def notice_kinds() -> list[dict[str, str]]:
    """Every condition the server checks for, with its severity and meaning.

    Rendered on the PROBLEMS panel as "what the server checks", ticked where
    nothing is open: an owner has to be able to tell a clean bill of health
    from a check nobody ever wrote."""
    return [
        {"kind": kind, "severity": spec["severity"], "what": spec["what"]}
        for kind, spec in sorted(NOTICE_KINDS.items())
    ]


def notice_href(kind: str, subject: str = "") -> tuple[str, str]:
    """(href, label) for one notice's [ TAKE ME THERE ] button, or ("", "").

    DDIAG-8. Never raises: a callable that cannot make sense of a subject
    costs a button, and a panel that 500s over a link is worse than one that
    tells you the page's name in words."""
    spec = NOTICE_KINDS.get(str(kind)) or {}
    href = spec.get("href")
    if callable(href):
        try:
            href = href(subject)
        except Exception:  # noqa: BLE001 - see the docstring
            href = ""
    href = str(href or "")
    if not href:
        return "", ""
    return href, str(spec.get("href_label") or "[ TAKE ME THERE ]")


def notice_counts(conn: sqlite3.Connection) -> dict[str, int]:
    """Open notices by severity, for /api/v1/health and the topbar."""
    counts = {sev: 0 for sev in NOTICE_SEVERITIES}
    for row in conn.execute(
        "SELECT severity, COUNT(*) AS n FROM notices WHERE cleared_at IS NULL "
        "GROUP BY severity"
    ):
        counts[str(row["severity"])] = int(row["n"])
    return counts
# What the home panel shows at most. A fleet that has generated more open
# notices than this has one underlying fault, not thirty independent ones.
NOTICE_PANEL_LIMIT = 25

# Finding 1 (resilience sweep 2026-08-28 fix pass). `plan_without_share` sat
# in NOTICE_KINDS with severity error and no writer, so the WHAT THE SERVER
# CHECKS panel ticked it [ OK ] every render -- the exact "unchecked rendered
# as fine" this registry exists to prevent, and true of any future kind
# registered before its writer lands. `notice`, `clear_notice` and
# `clear_notices_of_kind` are the only three functions any writer ever calls,
# each is called EXACTLY ONCE per kind per pass whether or not that pass found
# anything wrong (see collector.py's provisioning loop and every `_check_*` in
# notices.py), so stamping evidence inside them, rather than adding a fourth
# call every writer must remember, covers every kind for free. One meta row,
# not a table -- the same shape as META_ALERTS_OPEN: a small CURRENT picture
# with no history worth keeping.
NOTICE_CHECKS_META = "notice_last_checked"


def _mark_notice_checked(conn: sqlite3.Connection, kind: str, now: str) -> None:
    """Evidence that SOME pass evaluated `kind` this cycle, independent of
    whether it found anything. Never raises: recording evidence must not be
    able to break the pass it is evidence for."""
    try:
        seen = meta_get_json(conn, NOTICE_CHECKS_META)
        if not isinstance(seen, dict):
            seen = {}
        seen[str(kind)] = now
        meta_set_json(conn, NOTICE_CHECKS_META, seen)
    except sqlite3.Error:
        pass


def notice_check_times(conn: sqlite3.Connection) -> dict[str, str]:
    """{kind: last_checked_iso} for every kind some pass has actually
    evaluated. A kind absent here has no writer running anywhere in this
    build -- read by the WHAT THE SERVER CHECKS panel so that renders
    [ NOT CHECKED ] rather than a false [ OK ]."""
    seen = meta_get_json(conn, NOTICE_CHECKS_META)
    return {str(k): str(v) for k, v in seen.items()} if isinstance(seen, dict) else {}


def notice(
    conn: sqlite3.Connection, kind: str, severity: str, subject: str = "",
    body: str = "", fix: str | None = None, now: str | None = None,
) -> int:
    """Record that the server found a problem, or that it is still there.

    Upserts on (kind, subject): first_seen is kept, last_seen is bumped, and
    cleared_at is NULLed. That last part is deliberate -- a condition an admin
    dismissed and that is still true must come back, because the alternative
    is a dashboard that can be told to stop mentioning unsynced footage.

    Never raises on an unknown severity: this is called from inside the
    collector's per-slug try/except, and a notice that killed the cycle it was
    describing would be worse than no notice at all."""
    stamp = now or utcnow_iso()
    sev = str(severity or "warn").strip().lower()
    if sev not in NOTICE_SEVERITIES:
        sev = "warn"
    conn.execute(
        """INSERT INTO notices
             (kind, severity, subject, body, fix, first_seen, last_seen, cleared_at)
           VALUES (?, ?, ?, ?, ?, ?, ?, NULL)
           ON CONFLICT(kind, subject) DO UPDATE SET
             severity=excluded.severity,
             body=excluded.body,
             fix=excluded.fix,
             last_seen=excluded.last_seen,
             cleared_at=NULL""",
        (str(kind), sev, str(subject or ""), str(body or ""), str(fix or ""),
         stamp, stamp),
    )
    _mark_notice_checked(conn, kind, stamp)
    # Never `cur.lastrowid` (bug-hunt-2026-09-03 dash-db-2): SQLite does not
    # touch last_insert_rowid() on the DO UPDATE path, so on every re-assert
    # it holds the rowid of some unrelated row inserted earlier on this
    # connection (a fleet_audit or alert_log id), and it is truthy -- which
    # made this lookup dead code and the returned id a dismiss target
    # pointing at the wrong notice.
    row = conn.execute(
        "SELECT id FROM notices WHERE kind=? AND subject=?", (str(kind), str(subject or "")),
    ).fetchone()
    return int(row["id"]) if row else 0


def clear_notice(
    conn: sqlite3.Connection, kind: str, subject: str = "", now: str | None = None,
) -> bool:
    """The condition is gone: close the notice. True when one was open.

    Called from the same pass that would have written it, so a fixed stray
    marker stops shouting on the next cycle rather than waiting for a human to
    dismiss something that is no longer true. Stamps notice-check evidence for
    `kind` UNCONDITIONALLY, even when there was no open row to close: being
    asked to clear a kind is itself proof the pass that owns it ran (finding
    1, resilience sweep 2026-08-28 fix pass)."""
    stamp = now or utcnow_iso()
    cur = conn.execute(
        "UPDATE notices SET cleared_at=? WHERE kind=? AND subject=? AND cleared_at IS NULL",
        (stamp, str(kind), str(subject or "")),
    )
    _mark_notice_checked(conn, kind, stamp)
    return cur.rowcount > 0


def clear_notices_of_kind(
    conn: sqlite3.Connection, kind: str, keep_subjects: Iterable[str] = (),
    now: str | None = None,
) -> int:
    """Close every open notice of `kind` except the subjects still failing.

    For the pass-shaped writers (provisioning walks every slug each cycle): a
    slug that is no longer in the failing set has stopped failing, and nothing
    else in the code is in a position to say so.

    Stamps notice-check evidence for `kind` up front, UNCONDITIONALLY: a pass
    with nothing to close (nothing was ever open, or everything still open is
    in `keep_subjects`) is still a pass that checked, and the per-row loop
    below would otherwise never call `clear_notice` at all on a clean cycle
    (finding 1, resilience sweep 2026-08-28 fix pass)."""
    stamp = now or utcnow_iso()
    _mark_notice_checked(conn, kind, stamp)
    keep = {str(s) for s in keep_subjects}
    closed = 0
    for row in conn.execute(
        "SELECT subject FROM notices WHERE kind=? AND cleared_at IS NULL", (str(kind),),
    ).fetchall():
        if row["subject"] not in keep:
            closed += int(clear_notice(conn, kind, row["subject"], now=stamp))
    return closed


def open_notices(
    conn: sqlite3.Connection, limit: int = NOTICE_PANEL_LIMIT
) -> list[dict[str, Any]]:
    """Open notices, newest first. Read on every home render, so it is one
    indexed query and nothing else."""
    return [dict(r) for r in conn.execute(
        "SELECT * FROM notices WHERE cleared_at IS NULL "
        "ORDER BY last_seen DESC, id DESC LIMIT ?",
        (int(limit),),
    )]


def dismiss_notice(
    conn: sqlite3.Connection, notice_id: int, actor: str, now: str | None = None,
) -> dict[str, Any] | None:
    """[ DISMISS ]: the admin has read it. Returns the row, or None when the
    id names nothing open -- a dismissal that matched no notice must read as a
    failure rather than a silent success (the UX-20 lesson)."""
    stamp = now or utcnow_iso()
    row = conn.execute(
        "SELECT * FROM notices WHERE id=? AND cleared_at IS NULL", (int(notice_id),),
    ).fetchone()
    if row is None:
        return None
    conn.execute("UPDATE notices SET cleared_at=? WHERE id=?", (stamp, int(notice_id)))
    audit(conn, actor, "notice.dismiss", row["kind"],
          {"subject": row["subject"], "severity": row["severity"]}, now=stamp)
    return dict(row)


# ------------------------------------------------------ invariant results
#
# SYS-9 (resilience sweep 2026-08-28, wave 5). The registry, the checks and
# the wording all live in invariants.py; what is here is the ledger and the
# read the page and the alert kind share, on the same split db.py/notices.py
# already use. The three states are STORED, not derived: "could not check"
# read as "fine" is the mistake this whole sweep exists to end, and a reader
# that only ever sees `ok` as 1/0 cannot make it.

INVARIANT_OK = "ok"
INVARIANT_BROKEN = "broken"
INVARIANT_NOT_CHECKED = "not_checked"
INVARIANT_CHECK_FAILED = "check_failed"
INVARIANT_STATES = (INVARIANT_OK, INVARIANT_BROKEN, INVARIANT_NOT_CHECKED,
                    INVARIANT_CHECK_FAILED)

# Per invariant, per pass. One broken cross-component fact usually breaks it
# for many subjects at once (a Syncthing config restored empty breaks the
# share invariant for the whole fleet), and a page listing four hundred of
# them says less than a page listing twenty and a count.
INVARIANT_MAX_SUBJECTS = 20


def _invariant_ok_flag(state: str) -> int | None:
    if state == INVARIANT_OK:
        return 1
    if state == INVARIANT_BROKEN:
        return 0
    return None


def record_invariant_result(
    conn: sqlite3.Connection, invariant: str, state: str, detail: str = "",
    subjects: Iterable[tuple[str, str]] = (), now: str | None = None,
) -> None:
    """Write one invariant's verdict: the summary row plus a row per broken
    subject, and DELETE the subject rows this pass did not name.

    The delete is what makes the page reflect the present rather than
    everything that has ever been wrong: unlike `notices`, which is a ledger
    with a life and a DISMISS, this table is a picture of the last pass.

    It runs ONLY for a real verdict (ok / broken). bug-hunt-2026-09-03
    dash-collector-2: `evaluate()` turns an exception into a check_failed
    Outcome with NO subjects, so an unconditional delete wiped every broken
    subject of an invariant whose check merely crashed - and the fleet was
    then mailed "this has cleared" for a tick that is still unshared. A
    subject kept this way keeps its OLD `checked_at`, so the page's age
    wording cannot claim a fresh check. The summary row is still written, on
    every verdict: the page needs the check_failed state stamped.
    """
    stamp = now or utcnow_iso()
    verdict = state if state in INVARIANT_STATES else INVARIANT_CHECK_FAILED
    rows: list[tuple[str, str, int | None, str, str, str]] = [
        (invariant, "", _invariant_ok_flag(verdict), verdict, str(detail or ""), stamp)
    ]
    kept: list[str] = []
    for subject, subject_detail in list(subjects)[:INVARIANT_MAX_SUBJECTS]:
        kept.append(str(subject))
        rows.append((invariant, str(subject), _invariant_ok_flag(verdict), verdict,
                     str(subject_detail or ""), stamp))
    conn.executemany(
        """INSERT INTO invariant_results
             (invariant, subject, ok, state, detail, checked_at)
           VALUES (?, ?, ?, ?, ?, ?)
           ON CONFLICT(invariant, subject) DO UPDATE SET
             ok=excluded.ok, state=excluded.state, detail=excluded.detail,
             checked_at=excluded.checked_at""",
        rows,
    )
    if verdict in (INVARIANT_OK, INVARIANT_BROKEN):
        placeholders = ",".join("?" * len(kept)) or "''"
        conn.execute(
            f"""DELETE FROM invariant_results
                 WHERE invariant=? AND subject<>'' AND subject NOT IN ({placeholders})""",
            (invariant, *kept),
        )


def fetch_invariant_results(conn: sqlite3.Connection) -> dict[str, dict[str, Any]]:
    """{invariant: {state, detail, checked_at, subjects: [...]}}.

    A MISSING TABLE IS AN EMPTY PICTURE, not an error (the rule
    `alerts._rows` states): this is read by the admin page and by an alert
    check that may be running against a database an older build migrated."""
    out: dict[str, dict[str, Any]] = {}
    try:
        rows = list(conn.execute(
            "SELECT * FROM invariant_results ORDER BY invariant, subject"))
    except sqlite3.Error:
        return {}
    for row in rows:
        entry = out.setdefault(str(row["invariant"]), {
            "state": INVARIANT_NOT_CHECKED, "detail": "", "checked_at": "",
            "subjects": [],
        })
        if not row["subject"]:
            entry["state"] = str(row["state"])
            entry["detail"] = str(row["detail"] or "")
            entry["checked_at"] = str(row["checked_at"] or "")
        else:
            entry["subjects"].append(
                {"subject": str(row["subject"]), "detail": str(row["detail"] or "")})
    return out


def broken_invariants(conn: sqlite3.Connection) -> list[dict[str, Any]]:
    """Every currently broken invariant's subject rows, for the alert kind."""
    try:
        rows = list(conn.execute(
            "SELECT invariant, subject, detail, checked_at FROM invariant_results "
            "WHERE state=? AND subject<>'' ORDER BY invariant, subject",
            (INVARIANT_BROKEN,)))
    except sqlite3.Error:
        return []
    return [dict(r) for r in rows]


# --------------------------------------------------- site settings history
#
# UX-21 (resilience sweep 2026-08-28). [ IMPORT ] pasted a whole site.toml
# over the live one with no confirmation and no way back, and three of the
# keys in it (canonical_prefix, remote_root, tree_name) are read by both
# installers and every companion in the fleet. The values that were about to
# be overwritten are snapshotted here first, so "put it back" is a button
# rather than an archaeology exercise.
SITE_HISTORY_KEY = "site_history"
SITE_HISTORY_KEEP = 10


def record_site_change(
    conn: sqlite3.Connection, actor: str, action: str,
    before: Mapping[str, Any], after: Mapping[str, Any], now: str | None = None,
) -> dict[str, Any]:
    """Snapshot the values a save/import is ABOUT to replace.

    `before` is only the keys the write touches: an undo restores exactly what
    this write changed and does not resurrect anything else that has moved on
    since."""
    entry = {
        "at": now or utcnow_iso(),
        "actor": str(actor or "?"),
        "action": str(action or "save"),
        "before": {str(k): before[k] for k in before},
        "after": {str(k): after[k] for k in after},
    }
    entries = site_history(conn)
    entries.insert(0, entry)
    meta_set_json(conn, SITE_HISTORY_KEY, entries[:SITE_HISTORY_KEEP])
    return entry


def site_history(conn: sqlite3.Connection) -> list[dict[str, Any]]:
    """Newest first; never raises (it feeds a page)."""
    entries = meta_get_json(conn, SITE_HISTORY_KEY)
    if not isinstance(entries, list):
        return []
    return [e for e in entries if isinstance(e, dict)]


def record_enforce_refusal(
    conn: sqlite3.Connection, now: str, removals: Iterable[tuple[str, str]], limit: int,
) -> dict[str, Any]:
    """Persist "the enforce cycle refused N share removals this pass"."""
    pairs = [{"folder": slug, "device": device} for slug, device in sorted(removals)]
    record = {
        "at": now,
        "count": len(pairs),
        "limit": int(limit),
        "folders": sorted({p["folder"] for p in pairs}),
        "devices": sorted({p["device"] for p in pairs}),
        # Capped: an admin needs the shape, not 4000 rows in a meta value.
        "pairs": pairs[:200],
        "truncated": len(pairs) > 200,
    }
    meta_set_json(conn, META_ENFORCE_REFUSAL, record)
    return record


def clear_enforce_refusal(conn: sqlite3.Connection) -> None:
    meta_delete(conn, META_ENFORCE_REFUSAL)


def record_enforce_plan(
    conn: sqlite3.Connection, now: str, plan: Iterable[tuple[str, set[str], set[str]]],
) -> dict[str, Any]:
    """Persist the +/- an enforce cycle was about to apply (DASH-3's dry-run
    view). Read-only for the reader: computed from the same desired/actual
    sets the cycle itself uses, written once per cycle, never acted on."""
    folders = [
        {"folder": slug,
         "add": sorted(desired - actual),
         "remove": sorted(actual - desired)}
        for slug, desired, actual in plan
    ]
    record = {
        "at": now,
        "folders": folders[:100],
        "truncated": len(folders) > 100,
        "n_add": sum(len(f["add"]) for f in folders),
        "n_remove": sum(len(f["remove"]) for f in folders),
    }
    meta_set_json(conn, META_ENFORCE_PLAN, record)
    return record


# SYS-3 (resilience sweep 2026-08-28). A report section the companion has
# computed and sent for weeks was dropped by an undeclared pydantic field, in
# silence, for the THIRD time: B17 lost `transport_health` for months, then
# `proxy_coverage`/`youtube_import` "rode every heavy tick since their
# features shipped and reached nobody", then `sync_guard.syncthing_supervisor`
# (SYNC-8). Every one was found by a human reading the code.
#
# ReportIn now ACCEPTS extras and records the ones it does not read, so the
# next occurrence announces itself on the fleet page instead of waiting for a
# code review. `meta` for the same reason the collector alarms use it: one
# current value, no history worth keeping, and a schema version is a shared
# resource.
META_IGNORED_REPORT_SECTIONS = "ignored_report_sections"
# The keys are CLIENT-SUPPLIED strings on an endpoint with no rate limit, so
# every dimension of this record is bounded.
MAX_IGNORED_SECTIONS = 20
MAX_IGNORED_SECTION_KEY_CHARS = 64
MAX_IGNORED_SECTION_MACHINES = 10


def record_ignored_report_sections(
    conn: sqlite3.Connection, now: str, machine: str, keys: Iterable[str],
) -> dict[str, Any] | None:
    """Fold "this machine sent sections we do not read" into the meta record.

    Returns the stored record, or None when `keys` was empty (which is the
    normal case and writes nothing). Accumulates rather than replaces: the
    point is a section nobody noticed, and a single report from one machine
    naming it must not be overwritten by the next machine's clean one.
    """
    names = sorted({str(k)[:MAX_IGNORED_SECTION_KEY_CHARS] for k in keys if str(k)})
    if not names:
        return None
    record = meta_get_json(conn, META_IGNORED_REPORT_SECTIONS) or {}
    sections = record.get("sections")
    if not isinstance(sections, dict):
        sections = {}
    for name in names:
        entry = sections.get(name)
        if not isinstance(entry, dict):
            entry = {"machines": [], "reports": 0, "first_seen": now}
        machines = [m for m in entry.get("machines") or [] if isinstance(m, str)]
        if machine and machine not in machines:
            machines.append(machine)
        entry["machines"] = machines[:MAX_IGNORED_SECTION_MACHINES]
        entry["reports"] = int(entry.get("reports") or 0) + 1
        entry["last_seen"] = now
        entry.setdefault("first_seen", now)
        sections[name] = entry
    if len(sections) > MAX_IGNORED_SECTIONS:
        # Newest wins: an old name that has stopped arriving is the one whose
        # absence is safe to lose.
        keep = sorted(sections.items(), key=lambda kv: kv[1].get("last_seen") or "",
                      reverse=True)[:MAX_IGNORED_SECTIONS]
        sections = dict(keep)
    record = {"at": now, "sections": sections}
    meta_set_json(conn, META_IGNORED_REPORT_SECTIONS, record)
    return record


def ignored_report_sections(conn: sqlite3.Connection) -> dict[str, Any] | None:
    """The record the fleet banner renders, or None when nothing was ever
    dropped. Never raises: meta_get_json swallows an unparseable row."""
    record = meta_get_json(conn, META_IGNORED_REPORT_SECTIONS)
    if not isinstance(record, dict) or not record.get("sections"):
        return None
    return record


def clear_ignored_report_sections(conn: sqlite3.Connection) -> None:
    """For the deploy that declares the field: the banner has to be able to
    go away without waiting for a retention pass."""
    meta_delete(conn, META_IGNORED_REPORT_SECTIONS)


def collector_alarms(conn: sqlite3.Connection) -> dict[str, Any]:
    """The persisted brake state the fleet banner and /api/v1/health read."""
    return {
        "enforce_refusal": meta_get_json(conn, META_ENFORCE_REFUSAL),
        "enforce_plan": meta_get_json(conn, META_ENFORCE_PLAN),
        "deactivation_refusal": meta_get_json(conn, META_DEACTIVATION_REFUSAL),
    }


# The two cycles that decide what is SHARED with whom. A note from either is
# the difference between "the sharing you asked for is live" and "some of it
# is held", which is the whole of DCORE-16.
ENFORCE_NOTE_KINDS = ("config", "enforce")


def enforce_notes(
    conn: sqlite3.Connection, limit: int = 5, kinds: Iterable[str] = ENFORCE_NOTE_KINDS,
) -> list[dict[str, Any]]:
    """The recent config/enforce cycles that did NOT do everything they
    described, newest first (DCORE-16, usability sweep 2026-09-04).

    `poll_runs.error` carries a note on a SUCCESSFUL run too (collector_health
    says why), and until now the only place any of them was rendered was the
    collector health panel on the settings page -- so "applied 9 of 40;
    syncthing refused the rest", "refused 12 share removal(s)" and "skipped:
    empty myID" were invisible on the two pages where somebody is asking why
    a computer is not getting a project: the project page and the fleet
    diagnostics.

    A clean cycle has no note and appears nowhere here: an empty list means
    "nothing held", which is what the pages render as silence.
    """
    kinds = tuple(kinds)
    if not kinds:
        return []
    placeholders = ",".join("?" for _ in kinds)
    rows = conn.execute(
        f"""SELECT kind, ok, started_at, finished_at, error FROM poll_runs
             WHERE kind IN ({placeholders})
               AND error IS NOT NULL AND TRIM(error) <> ''
             ORDER BY id DESC LIMIT ?""",
        (*kinds, max(1, int(limit))),
    ).fetchall()
    return [
        {"at": r["finished_at"] or r["started_at"],
         "kind": r["kind"],
         "ok": bool(r["ok"]),
         "note": str(r["error"]).strip()}
        for r in rows
    ]


def collector_health(conn: sqlite3.Connection, now: str | None = None) -> dict[str, Any]:
    """Per-kind last poll WITH its note, plus the alarms (DASH-14).

    `poll_runs.error` carries a note on a SUCCESSFUL run too (the mechanism
    ops-efficiency-5 added for completion's "partial: ..."): "skipped: empty
    myID", "refused 12 removals" and "seed deferred" are three distinct "I did
    nothing" outcomes that read as "I reconciled everything" when only `ok` is
    rendered. A kind with a note is amber, not green.
    """
    status = fetch_collector_status(conn, now=now)
    kinds = []
    for kind, run in sorted(status["kinds"].items()):
        note = (run.get("error") or "").strip() or None
        kinds.append({
            "kind": kind,
            "ok": bool(run.get("ok")),
            "finished_at": run.get("finished_at"),
            "note": note,
            "status": "red" if not run.get("ok") else ("amber" if note else "green"),
        })
    return {
        "kinds": kinds,
        "syncthing_reachable": status["syncthing_reachable"],
        "collector_stale": status["collector_stale"],
        **collector_alarms(conn),
    }


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
    requires_dashboard: str = "",
    arch: str = "",
    git_sha: str = "",
    git_dirty: bool = False,
    staged_at: str = "",
    notes: str = "",
) -> None:
    # `now` is the SIGNER's published_at, not the server's clock: it is one of
    # the fields the release signature covers, so storing anything else would
    # serve a record that no longer verifies (item 4, 2026-08-17).
    #
    # rollout ALWAYS starts 'staged' (REL-1, 2026-08-28), even when the caller
    # is about to make this build current in the same transaction: publishing
    # is what puts a build on the shelf, and set_current_package is the one
    # place that hands it to the fleet. `staged_at` is the server's clock and
    # not `now`, because it starts a SOAK -- a signer's published_at hours in
    # the past would hand a fresh build a soak it never served.
    #
    # `notes` (v49, APP-16) is UNSIGNED: see SCHEMA_V49 for why a "what's new"
    # line must never be able to make a build unverifiable on a machine
    # running an older canonicaliser. Bounded here rather than at the route,
    # because both publish doors (the human PUT and the feed) come through
    # this one insert and a dialog on somebody's tray is what renders it.
    conn.execute(
        """INSERT INTO companion_packages
             (kind, version, platform, filename, sha256, size_bytes, published_at,
              published_by, signature, pubkey_id, min_version, signed_binary,
              rollout, staged_at, requires_dashboard, arch, git_sha, git_dirty, notes)
           VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 'staged', ?, ?, ?, ?, ?, ?)""",
        (kind, version, platform, filename, sha256, size_bytes, now, published_by,
         signature, pubkey_id, min_version, 1 if signed_binary else 0,
         staged_at or utcnow_iso(), requires_dashboard, arch, git_sha,
         1 if git_dirty else 0, package_notes(notes)),
    )


# One line, and a line an editor reads on their own screen: long enough for a
# real sentence, short enough that the update dialog stays a dialog.
MAX_PACKAGE_NOTES_CHARS = 300


def package_notes(notes: str | None) -> str:
    """A publisher's "what's new" line, bounded and single-line (APP-16).

    Newlines are folded rather than rejected: the value comes from a release
    script's `--notes`, and a stray one must cost a space, not a publish."""
    text = " ".join(str(notes or "").split())
    return text[:MAX_PACKAGE_NOTES_CHARS]


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
    conn: sqlite3.Connection, platform: str, version: str, kind: str = "companion",
    now: str | None = None,
) -> bool:
    """Point `current` at (kind, platform, version). False if that version is
    unknown, or has been RETRACTED by the vendor. Currency is per (kind,
    platform): making an onboard build current never touches which companion
    the fleet is offered, and vice versa.

    The retraction check is here, in the one writer, rather than only in the
    routes (REL-3, 2026-08-28): a recalled build must be un-currentable from
    every door, including the feed's `current` policy re-pointing at a version
    the vendor has since pulled.

    This is NOT the whole gate (bug-hunt-2026-09-03 dash-release-jobs-2): the
    `requires_dashboard` ordering check (REL-4) lives in
    `package_store.make_current`, and the REL-1 soak gate and the UX-9 unsigned
    confirmation in `api.make_current_refusal`. A caller that reaches this
    function directly bypasses them -- which is exactly how the feed's `current`
    policy made a build current that the dashboard was forbidden to offer. New
    callers go through `package_store.make_current`, never here.

    `rollout` moves with `is_current` in the same two statements: a build that
    is no longer offered to the fleet is back on the shelf, not current.

    `made_current_at` is stamped HERE, in the one writer, because it is the
    start of the rollout clock and every door has to start it (REL-6, usability
    sweep 2026-09-04): the question "did it actually reach the fleet" had no
    moment to count from, and published_at is the signer's. Re-pointing at a
    build restarts its clock -- a rollback is a new rollout of an old build.
    The rows it moves OFF keep their stamp: it says when they were last
    handed to the fleet, which is what a rollback needs to explain itself.
    """
    row = get_package(conn, platform, version, kind)
    if row is None or _row_value(row, "retracted_at"):
        return False
    conn.execute(
        "UPDATE companion_packages SET is_current=0, rollout='staged' "
        "WHERE kind=? AND platform=?",
        (kind, platform),
    )
    conn.execute(
        # `ever_current` is what makes a ROLLBACK cheap (REL-1): the soak gate
        # asks for evidence that a build the fleet has never been offered
        # actually runs, and a build it HAS been offered has already produced
        # that evidence -- refusing to go back to it would be the gate working
        # against the recovery it exists to make possible.
        "UPDATE companion_packages SET is_current=1, rollout='current', ever_current=1, "
        "made_current_at=? WHERE kind=? AND platform=? AND version=?",
        (now or utcnow_iso(), kind, platform, version),
    )
    return True


def _row_value(row: Any, key: str) -> Any:
    """A column an older database may not have yet. sqlite3.Row raises
    IndexError -- not KeyError -- for an unknown key, and this module is read
    by code that can meet a DB opened by a concurrently-starting older process
    during a redeploy (same reason api._row_value exists)."""
    try:
        return row[key]
    except (IndexError, KeyError, TypeError):
        return None


def retract_package(
    conn: sqlite3.Connection, kind: str, platform: str, version: str,
    reason: str, now: str, actor: str = "release-feed",
) -> bool:
    """Recall one published build (REL-3, resilience sweep 2026-08-28).

    Un-currents it, stamps why and when. The ROW AND THE FILE STAY: machines
    in the field are still running this build, and both admin pages have to be
    able to name what the fleet is being rolled back FROM. False when this
    dashboard never published that version -- a recall for a build nobody here
    holds is a no-op, not an error.

    Idempotent: a feed carrying the same retraction every day must not
    re-stamp it, or `retracted_at` would say "recalled 30 seconds ago" forever.
    """
    row = get_package(conn, platform, version, kind)
    if row is None:
        return False
    if _row_value(row, "retracted_at"):
        return False
    conn.execute(
        "UPDATE companion_packages SET is_current=0, rollout='staged', "
        "retracted_at=?, retracted_reason=? "
        "WHERE kind=? AND platform=? AND version=?",
        (now, str(reason or ""), kind, platform, version),
    )
    audit(conn, actor, "package.retract", version,
          {"kind": kind, "platform": platform, "version": version,
           "reason": str(reason or "")}, now=now)
    return True


def retracted_packages(
    conn: sqlite3.Connection, kind: str = "companion"
) -> dict[tuple[str, str], str]:
    """(platform, version) -> reason, for every recalled build of this kind.

    The fleet grid reads it to chip a machine that is RUNNING a recalled
    build, which is the whole point of a recall: the machines already holding
    it are the ones nobody could see.
    """
    rows = conn.execute(
        "SELECT platform, version, retracted_reason FROM companion_packages "
        "WHERE kind=? AND retracted_at IS NOT NULL AND retracted_at != ''",
        (kind,),
    ).fetchall()
    return {
        (r["platform"], r["version"]): str(r["retracted_reason"] or "")
        for r in rows
    }


DEFAULT_SOAK_MINUTES = 30

# What `crash_origin` answers. A crash counter is a LIFETIME high-water count
# of files in ~/.ccsync/crashes on the machine's own disk: it is not per-build
# and it only goes down when somebody empties the directory.
CRASHES_NONE = "none"           # every crash file predates this build here
CRASHES_SOME = "some"           # at least one was written since it started
CRASHES_UNKNOWN = "unknown"     # nothing on record says which

# `crash_newest` is the FILENAME crash_report.write_report chose:
# "<when with ':' and '-' stripped>-<thread>.json", e.g.
# "20260904T184500+0000-MainThread.json". Only the leading stamp is read, and
# it is UTC by construction (datetime.now(timezone.utc)).
_CRASH_NAME_STAMP = re.compile(r"^(\d{4})(\d{2})(\d{2})T(\d{2})(\d{2})(\d{2})")


def crash_file_time(crash_newest: str | None) -> str | None:
    """The UTC timestamp inside a reported crash FILENAME, or None.

    None for a name this server does not recognise: a machine's crash file
    naming is the companion's, and a future rename must read as "cannot tell"
    rather than as a time.
    """
    raw = str(crash_newest or "").strip()
    if not raw:
        return None
    match = _CRASH_NAME_STAMP.match(raw)
    if match is None:
        # A machine that reports a plain ISO timestamp instead of a filename
        # is answering the same question in the other shape. Accepted rather
        # than refused: this value is a companion's, and both spellings say
        # when the newest crash was.
        try:
            return parse_iso(raw).isoformat()
        except (ValueError, TypeError):
            return None
    y, mo, d, h, mi, s = match.groups()
    try:
        return dt.datetime(int(y), int(mo), int(d), int(h), int(mi), int(s),
                           tzinfo=dt.timezone.utc).isoformat()
    except ValueError:
        return None


def crash_origin(crash_count: Any, crash_newest: str | None,
                 since: str | None) -> str:
    """Do a machine's crash files belong to the build it is running NOW?
    (CR-191, 2026-09-04.)

    The soak gate used to read `crash_count` as "crashes on this build" and
    refuse to make one current on the strength of it. On the base rig that
    number was 16 UncleanExit markers from KNOWN_BUGS CR-144 -- the
    installer's Stop-Process during an upgrade, the Cards test gate sweeping
    port 8899, dev restarts -- every one of them written weeks ago by 0.9.66
    and older, and none of them evidence of anything at all about 0.9.70. The
    refusal was unanswerable except by overriding the gate, which is how a
    gate stops being believed.

    The evidence available server-side is the COUNT and the newest crash
    file's name, and that is enough for the question the gate actually asks:
    a newest crash that predates the moment this build started running here
    means none of them are its. Deliberately not a schema baseline and
    deliberately not a companion change: this has to answer correctly for
    builds already in the field tonight.

    UNKNOWN is not NONE. A companion too old to send a crash section, an
    unparseable `companion_version_since`, a crash counter with no newest
    name: none of those observed the build staying up, and the soak is a
    claim that something was observed.
    """
    if crash_count is None:
        return CRASHES_UNKNOWN
    try:
        count = int(crash_count)
    except (TypeError, ValueError):
        return CRASHES_UNKNOWN
    if count <= 0:
        return CRASHES_NONE
    newest = crash_file_time(crash_newest)
    if not newest or not since:
        return CRASHES_UNKNOWN
    try:
        # STRICTLY before: a crash file written in the same second the version
        # first appeared is the crash of the build that was replaced OR of the
        # new one, and "cannot tell" is the answer that keeps the gate honest.
        return CRASHES_NONE if age_seconds(newest, since) > 0 else CRASHES_SOME
    except (ValueError, TypeError):
        return CRASHES_UNKNOWN


def soak_state(
    conn: sqlite3.Connection, platform: str, version: str,
    soak_minutes: float, now: str | None = None,
) -> dict[str, Any]:
    """"canary: N machines on X for M min, C crashes" -- and whether that is
    enough to hand this build to the whole fleet (REL-1/SYS-6, 2026-08-28).

    A build passes when at least ONE machine has been reporting this exact
    version for `soak_minutes` with no crashes and no crash-loop revert. Not
    an average and not a majority: the question the gate answers is "has this
    build run somewhere real for long enough to have failed", and one machine
    that has is the whole evidence there is.

    Every "we could not tell" counts AGAINST passing (an unparseable
    companion_version_since, a machine that has never reported a crash
    section): a soak is a claim that something was observed, so an absence of
    observation can never satisfy it.

    THE CRASHES THAT COUNT ARE THIS BUILD'S (CR-191, 2026-09-04). `crashes`
    is still the lifetime figure, because that is what the machine reported
    and the page prints it; what the gate reads is `crash_origin` per machine,
    and a pile of markers written by an older build weeks ago no longer holds
    a release back. `crashes_on_version` and `crashes_unknown` count the
    machines, not the files: server-side there is one timestamp per machine to
    reason from, and one crash that IS this build's is already a refusal.
    """
    now = now or utcnow_iso()
    machines = machines_running_version(conn, platform, version)
    best_minutes = 0.0
    crashes = 0
    crashes_on_version = 0
    crashes_unknown = 0
    reverted = 0
    passed = 0
    for m in machines:
        crash_count = m.get("crash_count")
        crashes += int(crash_count or 0)
        origin = crash_origin(crash_count, m.get("crash_newest"), m.get("since"))
        m["crash_origin"] = origin
        if origin == CRASHES_SOME:
            crashes_on_version += 1
        elif origin == CRASHES_UNKNOWN:
            crashes_unknown += 1
        if m.get("reverted_from"):
            reverted += 1
        try:
            minutes = age_seconds(str(m.get("since") or ""), now) / 60.0
        except (ValueError, TypeError):
            minutes = 0.0
        minutes = max(0.0, minutes)
        m["minutes"] = minutes
        best_minutes = max(best_minutes, minutes)
        if (minutes >= float(soak_minutes)
                and origin == CRASHES_NONE
                and not m.get("reverted_from")):
            passed += 1
    return {
        "version": version,
        "platform": platform,
        "machines": len(machines),
        "minutes": int(best_minutes),
        "crashes": crashes,
        "crashes_on_version": crashes_on_version,
        "crashes_unknown": crashes_unknown,
        "reverted": reverted,
        "soak_minutes": int(soak_minutes),
        "passed": passed,
        "ok": passed > 0,
        "detail": [
            {"editor_username": m["editor_username"], "machine": m["machine"],
             "minutes": int(m.get("minutes") or 0), "crash_count": m.get("crash_count"),
             "crash_origin": m.get("crash_origin"),
             "crash_newest": m.get("crash_newest"),
             "reverted_from": m.get("reverted_from")}
            for m in machines
        ],
    }


def rollout_status(
    conn: sqlite3.Connection, now: str | None = None
) -> dict[str, Any]:
    """"did it actually reach the fleet" (REL-6, usability sweep 2026-09-04).

    Query-only. One channel per (kind, platform) that has a CURRENT build,
    each carrying the adoption line the Packages page, the drift doctor and
    the rollout alert all print from the same numbers:

        {"generated_at": iso,
         "channels": [{
            "kind": "companion", "platform": "windows",
            "current_version": "0.9.66",
            "made_current_at": iso or None,   # None = a build made current
                                              # before v48: cannot tell
            "machines_total": 7, "machines_on_current": 5,
            "reverts": 0, "failed_attempts": 0,
            "behind":   [{"editor", "machine", "version", "last_seen"}],
            "refusing": [{"editor", "machine", "version", "reason", "at"}],
         }]}

    Only `companion` channels are built: an editor's machine reports which
    companion it is running and nothing reports which INSTALLER it was
    installed from, so an onboard channel could only ever answer "0 of 0",
    which reads as a fleet that has taken nothing.

    `behind` is STRICTLY older by version_tuple, never "!= current": a base
    rig running tomorrow's build is not a machine that failed to upgrade, and
    counting it as one is how an adoption number stops being believed.

    `refusing` is the offer a companion turned down at receipt (REL-3) -- a
    signature it will not trust, a version below its downgrade floor. Read
    defensively: a companion too old to send it, or a database that has not
    grown the columns, is "not refusing", never "refusing for an unknown
    reason". A refusing machine is also in `behind`, because it IS behind;
    what the refusal adds is that no button on the page can fix it.
    """
    now = now or utcnow_iso()
    machines: list[dict[str, Any]] = []
    for r in conn.execute("SELECT * FROM machine_state").fetchall():
        machines.append({
            "editor": r["editor_username"],
            "machine": r["machine"],
            "version": r["companion_version"],
            "platform": str(_row_value(r, "platform") or "windows").strip().lower(),
            "last_seen": r["received_at"] or r["reported_at"],
            "reverted_from": _row_value(r, "upgrade_reverted_from"),
            "attempts": _row_value(r, "upgrade_attempts"),
            "refused_version": _row_value(r, "upgrade_refused_version"),
            "refused_reason": _row_value(r, "upgrade_refused_reason"),
            "refused_at": _row_value(r, "upgrade_refused_at"),
        })
    channels: list[dict[str, Any]] = []
    rows = conn.execute(
        "SELECT * FROM companion_packages WHERE kind='companion' AND is_current=1 "
        "ORDER BY platform"
    ).fetchall()
    for pkg in rows:
        platform = str(pkg["platform"] or "").strip().lower()
        current = str(pkg["version"] or "")
        current_key = version_tuple(current)
        mine = [m for m in machines if m["platform"] == platform and m["version"]]
        behind = []
        refusing = []
        on_current = 0
        reverts = 0
        attempts = 0
        for m in mine:
            if m["reverted_from"]:
                reverts += 1
            try:
                attempts += int(m["attempts"] or 0)
            except (TypeError, ValueError):
                pass
            if str(m["version"]) == current:
                on_current += 1
            elif current_key and version_tuple(m["version"]) < current_key:
                behind.append({"editor": m["editor"], "machine": m["machine"],
                               "version": m["version"], "last_seen": m["last_seen"]})
            if m["refused_version"]:
                refusing.append({
                    "editor": m["editor"], "machine": m["machine"],
                    "version": m["refused_version"],
                    "reason": str(m["refused_reason"] or ""),
                    "at": m["refused_at"],
                })
        channels.append({
            "kind": "companion",
            "platform": platform,
            "current_version": current,
            "made_current_at": _row_value(pkg, "made_current_at") or None,
            "machines_total": len(mine),
            "machines_on_current": on_current,
            "reverts": reverts,
            "failed_attempts": attempts,
            "behind": behind,
            "refusing": refusing,
        })
    return {"generated_at": now, "channels": channels}


def machines_running_version(
    conn: sqlite3.Connection, platform: str, version: str
) -> list[dict[str, Any]]:
    """Every machine whose LAST report said it is running this exact build.

    What [ ROLL THE FLEET BACK TO x ] iterates (REL-3) and what the soak gate
    counts (REL-1). Platform-scoped: a macOS recall must never write an update
    request onto a Windows box.
    """
    # SELECT * on purpose: `upgrade_reverted_from` is v35's column and this
    # function has to work on a v34 database, where naming it would be a
    # sqlite error rather than a missing answer.
    rows = conn.execute(
        """SELECT * FROM machine_state
            WHERE companion_version = ?
              AND LOWER(COALESCE(platform, 'windows')) = LOWER(?)""",
        (version, platform),
    ).fetchall()
    out: list[dict[str, Any]] = []
    for r in rows:
        entry = {
            "editor_username": r["editor_username"],
            "machine": r["machine"],
            "companion_version": r["companion_version"],
            "since": r["companion_version_since"] or r["received_at"] or r["reported_at"],
            "crash_count": r["crash_count"],
            # CR-191: the NAME of the newest crash file, which carries its UTC
            # stamp -- the only thing here that can say whether a lifetime
            # crash counter has anything to do with the build being soaked.
            "crash_newest": _row_value(r, "crash_newest"),
            # v35's column (the dashboard-self-update work package lands it
            # after this one): read defensively so this works before it
            # exists. A build the crash-loop guard had to undo is not a
            # successful soak, and "we could not tell" must not read as "no
            # revert" -- but a schema that has not grown the column yet
            # genuinely has no answer, which is what None says here.
            "reverted_from": _row_value(r, "upgrade_reverted_from"),
        }
        out.append(entry)
    return out


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


_FEED_STATE_DEFAULT = {
    "last_checked_at": None, "last_error": None,
    "last_channel_generated_at": None, "etag": None, "policy_override": None,
}


def get_feed_state(conn: sqlite3.Connection) -> dict[str, Any]:
    """The singleton feed_state row, or the all-None default before the
    first check ever ran (COMMERCIAL_READINESS.md v19, ZERO_TOUCH_PLAN.md
    WP E, 2026-08-17)."""
    row = conn.execute(
        "SELECT last_checked_at, last_error, last_channel_generated_at, etag, "
        "policy_override FROM feed_state WHERE id=1"
    ).fetchone()
    if row is None:
        return dict(_FEED_STATE_DEFAULT)
    return dict(row)


def set_feed_state(conn: sqlite3.Connection, **fields: Any) -> None:
    """Upsert the singleton row. Unknown keys are ignored (a caller passing
    a typo'd field silently does nothing rather than raising mid-poll, which
    would take the whole feed thread down over a spelling mistake); omitted
    keys keep their current value -- this is a partial update, not a
    replace."""
    current = get_feed_state(conn)
    current.update({k: v for k, v in fields.items() if k in current})
    conn.execute(
        """INSERT INTO feed_state
             (id, last_checked_at, last_error, last_channel_generated_at, etag, policy_override)
           VALUES (1, ?, ?, ?, ?, ?)
           ON CONFLICT(id) DO UPDATE SET
             last_checked_at=excluded.last_checked_at,
             last_error=excluded.last_error,
             last_channel_generated_at=excluded.last_channel_generated_at,
             etag=excluded.etag,
             policy_override=excluded.policy_override""",
        (current["last_checked_at"], current["last_error"],
         current["last_channel_generated_at"], current["etag"], current["policy_override"]),
    )


# The unassigned bucket: a plan row that names no machine applies to every
# machine of that editor which has none of its own (v24's comment). Spelled
# once, here, so no caller has to remember the empty string means something.
ANY_MACHINE = ""

# A tick's MODE (v28, docs/UPLOAD_ONLY_TICK.md). `full` is every lane;
# `upload_only` is lane A alone: originals go up, nothing comes down, and the
# Syncthing folder is never shared with that machine. Spelled here so the API,
# the enforce cycle, the queue builders and the templates all agree on the two
# strings the companion is also matching on.
SYNC_MODE_FULL = "full"
SYNC_MODE_UPLOAD_ONLY = "upload_only"
SYNC_MODES = (SYNC_MODE_FULL, SYNC_MODE_UPLOAD_ONLY)


def machines_of(conn: sqlite3.Connection, editor: str) -> list[str]:
    """This editor's known machines, oldest first. The registry is the
    authority; machine_state is not consulted, because v23 backfilled the
    registry from it and every report keeps it current."""
    return [
        r["machine"] for r in conn.execute(
            "SELECT machine FROM machines WHERE editor_username=? ORDER BY first_seen, machine",
            (editor,),
        )
    ]


def upsert_machine(
    conn: sqlite3.Connection, editor: str, machine: str, now: str,
    machine_id: str | None = None, platform: str | None = None,
    syncthing_device_id: str | None = None,
) -> None:
    """Record that this computer exists and was heard from (v23).

    Every learned attribute is COALESCEd: a light report carries no platform,
    an old companion carries no machine_id, and a companion whose Syncthing
    is momentarily unreachable carries no device id. None of those is
    evidence that what we already knew is wrong."""
    conn.execute(
        """INSERT INTO machines
             (editor_username, machine, machine_id, platform, syncthing_device_id,
              first_seen, last_seen)
           VALUES (?, ?, ?, ?, ?, ?, ?)
           ON CONFLICT(editor_username, machine) DO UPDATE SET
             machine_id=COALESCE(excluded.machine_id, machines.machine_id),
             platform=COALESCE(excluded.platform, machines.platform),
             syncthing_device_id=COALESCE(excluded.syncthing_device_id,
                                          machines.syncthing_device_id),
             last_seen=excluded.last_seen""",
        (editor, machine, machine_id or None, platform or None,
         syncthing_device_id or None, now, now),
    )


def fetch_machines(conn: sqlite3.Connection, editor: str | None = None) -> list[dict[str, Any]]:
    q = "SELECT * FROM machines"
    params: list[Any] = []
    if editor is not None:
        q += " WHERE editor_username=?"
        params.append(editor)
    q += " ORDER BY editor_username, first_seen, machine"
    return [dict(r) for r in conn.execute(q, params)]


# DASH-16 (resilience sweep 2026-08-28). An editor's PC dies, or an editor
# leaves and takes the laptop, and nobody tells the owner. The grid did the
# right thing for a day (`received_at | ago` plus a red lane chip after 15
# minutes); at 14 days the machine's media presence disappeared and at 30 its
# machine_state row was DELETED, so the computer quietly left the page --
# while its `machines` registry row, its `selections` plan and its Syncthing
# share all remained. The fleet then looks healthier than it is, and a device
# that still holds project data is shared with nothing watching it.
#
# The registry row is the anchor because it already survives every prune. A
# week is the threshold: past a holiday-length absence, and well short of the
# 14-day media age-out that is the first thing to visibly go.
LOST_MACHINE_DAYS = 7


def lost_machines(
    conn: sqlite3.Connection, now: str, days: int = LOST_MACHINE_DAYS
) -> list[dict[str, Any]]:
    """Registry rows whose last report is older than `days`, with the plan
    each one still holds.

    Says nothing about machine_state -- the caller decides whether a machine
    is ALSO still on the grid under its own row (see build_editors_view).
    `projects` is the tick list that is still being enforced for a computer
    nobody is watching, which is the actual reason this is worth a row.
    """
    cutoff = (parse_iso(now) - dt.timedelta(days=days)).isoformat()
    out: list[dict[str, Any]] = []
    for row in conn.execute(
        """SELECT * FROM machines WHERE last_seen < ?
           ORDER BY last_seen, editor_username, machine""",
        (cutoff,),
    ):
        machine = dict(row)
        machine["projects"] = [
            r["project_slug"] for r in conn.execute(
                """SELECT project_slug FROM selections
                   WHERE editor_username=? AND machine=?
                   ORDER BY project_slug""",
                (machine["editor_username"], machine["machine"]),
            )
        ]
        out.append(machine)
    return out


def machine_by_device_id(conn: sqlite3.Connection, device_id: str) -> dict[str, Any] | None:
    """Which computer is this Syncthing device? The enforce cycle's join
    (WP3): a folder is shared with a DEVICE, and only this mapping can say
    which of an editor's two computers that device is."""
    row = conn.execute(
        "SELECT * FROM machines WHERE syncthing_device_id=?", (device_id,)
    ).fetchone()
    return dict(row) if row else None


def release_device_id_elsewhere(
    conn: sqlite3.Connection, editor: str, machine: str, device_id: str
) -> list[str]:
    """Take a Syncthing device id off every OTHER machine row that still
    claims it; returns the rows it was taken from as "editor/machine".

    One device is one computer. Two rows could hold one id -- a refused
    rename adoption records the report under the new name and leaves the old
    row with its plan AND its device id (ultrareview 2026-08-19), a restored
    image carries another box's machine.json, a Mac's hostname gains a '-2'
    on a Bonjour clash -- and three readers assume it sits on one:
    machine_by_device_id fetchone()s, _run_enforce's machine_devices maps
    both rows to the same device (so it is handed the UNION of two plans
    while its own GET /selection returns one of them), and the lane C queue's
    LEFT JOIN shows the same backlog twice under two hostnames
    (data-model-5, 2026-08-21).

    The report is the fresher evidence, so the reporting row keeps the id and
    the others lose it. Nothing else on those rows is touched: their plans
    stay put, which is the same "a hostname collision is an admin decision,
    not a silent overwrite" rule adopt_renamed_machine follows."""
    if not device_id:
        return []
    losers = [
        f"{r['editor_username']}/{r['machine']}"
        for r in conn.execute(
            "SELECT editor_username, machine FROM machines "
            "WHERE syncthing_device_id=? AND NOT (editor_username=? AND machine=?)",
            (device_id, editor, machine),
        )
    ]
    if losers:
        conn.execute(
            "UPDATE machines SET syncthing_device_id=NULL "
            "WHERE syncthing_device_id=? AND NOT (editor_username=? AND machine=?)",
            (device_id, editor, machine),
        )
    return losers


def machine_by_machine_id(
    conn: sqlite3.Connection, editor: str, machine_id: str
) -> dict[str, Any] | None:
    """The same computer under a different hostname. Used when a report
    arrives whose minted id we know but whose name we do not -- somebody
    renamed their PC, and their plan should not silently become empty."""
    if not machine_id:
        return None
    # Most recently heard from FIRST. Two rows can carry one id after a
    # refused rename adoption (the renamed computer's report is recorded
    # under its new name, the old row keeps its plan): the live one is the
    # one that just reported, and returning it is what stops the rename
    # branch re-firing on every report (ultrareview 2026-08-19).
    row = conn.execute(
        """SELECT * FROM machines WHERE editor_username=? AND machine_id=?
           ORDER BY last_seen DESC, machine ASC LIMIT 1""",
        (editor, machine_id),
    ).fetchone()
    return dict(row) if row else None


def machines_by_machine_id(
    conn: sqlite3.Connection, editor: str, machine_id: str
) -> list[dict[str, Any]]:
    """EVERY row of this editor's registry carrying this minted id, most
    recently heard from first.

    The singular above answers "who holds this id", which is all the rename
    branch needed while an adoption could only ever leave one row. SYS-18a
    (2026-08-29) made the refusal leave two on purpose, and the verdict is
    now revisited on every report -- so the caller needs the OTHER rows, not
    the one that has just reported and would always sort first."""
    if not machine_id:
        return []
    return [dict(r) for r in conn.execute(
        """SELECT * FROM machines WHERE editor_username=? AND machine_id=?
           ORDER BY last_seen DESC, machine ASC""",
        (editor, machine_id),
    )]


def pending_machine_request(
    conn: sqlite3.Connection, editor: str, machine: str
) -> dict[str, Any]:
    """The three parked per-machine requests this computer already has
    outstanding (DCORE-13, usability sweep 2026-09-04).

    Read BEFORE the write that overwrites one, so an admin clicking a second
    time can be told they are re-arming a request that has been waiting since
    Tuesday rather than being congratulated twice on the same click. An
    unknown machine answers all-empty, exactly like a known one with nothing
    parked: the ROUTES are what refuse an unknown machine (404), and they do
    it on the write's own rowcount."""
    row = conn.execute(
        """SELECT update_requested_version, update_requested_at,
                  lane_b_resume_requested_at, diagnostics_requested_at
             FROM machines WHERE editor_username=? AND machine=?""",
        (editor, machine),
    ).fetchone()
    if row is None:
        return {"update": "", "update_at": None,
                "lane_b_resume": False, "diagnostics": False}
    return {
        "update": str(row["update_requested_version"] or ""),
        "update_at": row["update_requested_at"],
        "lane_b_resume": bool(row["lane_b_resume_requested_at"]),
        "diagnostics": bool(row["diagnostics_requested_at"]),
    }


def request_machine_update(
    conn: sqlite3.Connection, editor: str, machine: str, version: str,
    requested_by: str, now: str,
) -> bool:
    """Ask one machine to take `version` on its next report (v25).

    False when there is no such machine: a request that names nothing must
    read as a failure to the admin, not as a silent success."""
    cur = conn.execute(
        """UPDATE machines
              SET update_requested_version=?, update_requested_at=?,
                  update_requested_by=?
            WHERE editor_username=? AND machine=?""",
        (version, now, requested_by, editor, machine),
    )
    if cur.rowcount > 0:
        audit(conn, requested_by, "machine.update_push", machine,
              {"editor": editor, "machine": machine, "version": version}, now=now)
    return cur.rowcount > 0


def clear_machine_update_request(
    conn: sqlite3.Connection, editor: str, machine: str
) -> None:
    """Called when the machine reports the version that was asked for -- the
    request is DONE, and a standing one would re-apply the same build after
    every restart."""
    conn.execute(
        """UPDATE machines
              SET update_requested_version=NULL, update_requested_at=NULL,
                  update_requested_by=NULL
            WHERE editor_username=? AND machine=?""",
        (editor, machine),
    )


def machine_update_request(
    conn: sqlite3.Connection, editor: str, machine: str
) -> dict[str, Any] | None:
    row = conn.execute(
        """SELECT update_requested_version AS version, update_requested_at AS at,
                  update_requested_by AS by_user
             FROM machines WHERE editor_username=? AND machine=?""",
        (editor, machine),
    ).fetchone()
    if row is None or not row["version"]:
        return None
    return dict(row)


def request_lane_b_resume(
    conn: sqlite3.Connection, editor: str, machine: str,
    requested_by: str, now: str,
) -> bool:
    """Ask one machine to clear its lane B breaker on its next report (v26).

    False when there is no such machine, on the same reasoning as
    request_machine_update: a request that names nothing must read as a
    failure to the admin rather than a silent success."""
    cur = conn.execute(
        """UPDATE machines
              SET lane_b_resume_requested_at=?, lane_b_resume_requested_by=?
            WHERE editor_username=? AND machine=?""",
        (now, requested_by, editor, machine),
    )
    if cur.rowcount > 0:
        audit(conn, requested_by, "lane_b.resume_request", machine,
              {"editor": editor, "machine": machine}, now=now)
    return cur.rowcount > 0


def clear_lane_b_resume_request(
    conn: sqlite3.Connection, editor: str, machine: str
) -> None:
    """Called when the machine reports its breaker is no longer tripped.

    This is what bounds the request in time. A standing one would sit on the
    machine and silently clear the NEXT trip -- which could be the real one
    the breaker exists for -- so "resume" has to mean this trip and no
    other."""
    conn.execute(
        """UPDATE machines
              SET lane_b_resume_requested_at=NULL, lane_b_resume_requested_by=NULL
            WHERE editor_username=? AND machine=?""",
        (editor, machine),
    )


def lane_b_resume_request(
    conn: sqlite3.Connection, editor: str, machine: str
) -> dict[str, Any] | None:
    row = conn.execute(
        """SELECT lane_b_resume_requested_at AS at,
                  lane_b_resume_requested_by AS by_user
             FROM machines WHERE editor_username=? AND machine=?""",
        (editor, machine),
    ).fetchone()
    if row is None or not row["at"]:
        return None
    return dict(row)


# -- the WHY sentence and the diagnostics channel (v33, SYS-7) -------------
#
# SYS-7 (resilience sweep 2026-08-28): build_diagnostics() on the companion is
# genuinely good and went to the CLIPBOARD, so the one artefact that answers
# "why is my footage not syncing" existed only if a non-technical editor
# performed a manual step at the right moment, on the machine that was broken.

DIAGNOSTICS_KEEP_PER_MACHINE = 5
DIAGNOSTICS_MAX_AGE_DAYS = 30
# 256 KB. The route refuses a longer body outright (app._BODY_LIMITS); this is
# the second cut, applied to the text itself, so a body that arrives inside the
# ceiling with one enormous field cannot put a megabyte in a TEXT column.
DIAGNOSTICS_MAX_CHARS = 256 * 1024


def store_blocked_state(
    conn: sqlite3.Connection, editor: str, machine: str,
    guard: Mapping[str, Any] | None,
) -> None:
    """Write `sync_guard.blocked` + `sync_guard.restarts` onto the machine's row.

    Its own UPDATE rather than six more columns in upsert_machine_state's
    INSERT: that statement is edited by every work package that touches the
    report, and this pair has one rule of its own anyway.

    THE LATCH RULE, not COALESCE (the same reasoning as the breaker and the
    supervisor section): these are written by any report that carried a guard
    section at all, because an ABSENT `blocked` is how the companion spells
    "nothing is blocking me now" -- and a COALESCE could never express that,
    so "the sync drive is not there" would have stayed on the grid for ever
    after the drive came back.

    `guard` None (a companion with no sync_guard section at all) leaves every
    column alone: it has no opinion to record, and clearing another build's
    alarm on its behalf is exactly what must not happen.
    """
    if guard is None or not guard.get("at"):
        return
    conn.execute(
        """UPDATE machine_state
              SET blocked_reason=?, blocked_detail=?, blocked_since=?,
                  restarts_count_24h=?, restarts_last_at=?, restarts_last_error=?
            WHERE editor_username=? AND machine=?""",
        (guard.get("blocked_reason"), guard.get("blocked_detail"),
         guard.get("blocked_since"), guard.get("restarts_count_24h"),
         guard.get("restarts_last_at"), guard.get("restarts_last_error"),
         editor, machine),
    )


def version_tuple(text: Any) -> tuple[int, ...]:
    """Dotted-numeric to a comparable tuple; () for anything else, which sorts
    below every real version. Two-digit minors compare correctly (0.9.9 <
    0.10.0), which a string compare does not -- the companion's own versioning
    rule, and the reason this is not `<` on the text."""
    raw = str(text or "").strip()
    parts = raw.split(".")
    out: list[int] = []
    for part in parts:
        if not part.isdigit():
            return ()
        out.append(int(part))
    return tuple(out) if out else ()


def store_upgrade_state(
    conn: sqlite3.Connection, editor: str, machine: str,
    guard: Mapping[str, Any] | None, arch: str | None,
    running_version: str | None = None,
) -> None:
    """Write `sync_guard.upgrade` + the report's top-level `arch` onto the
    machine's row (v35, REL-8 / REL-16, resilience sweep 2026-08-28).

    Its own UPDATE for the reason store_blocked_state gives: the big INSERT is
    edited by every work package that touches the report, and this group has
    rules of its own.

    THE LATCH RULE for attempts/error/version (an absent `upgrade` section is
    how a companion that has nothing to say spells "no failed update", and a
    COALESCE could never express that, so "8 attempts failed" would have
    outlived the fix). `reverted_from` is the exception: the companion sends it
    ONCE and then clears it, so keeping it is the only way the grid can show
    the revert at all -- and the chip takes itself off once the machine is
    running a build at or above the one it fell back from (see the template).
    `arch` is a property of the box: COALESCEd like `platform`, because a
    build too old to report it must not blank it.
    """
    if guard is None or not guard.get("at"):
        if arch:
            conn.execute(
                "UPDATE machine_state SET arch=? WHERE editor_username=? AND machine=?",
                (arch, editor, machine),
            )
        return
    conn.execute(
        """UPDATE machine_state
              SET arch=COALESCE(?, arch),
                  upgrade_version=?, upgrade_attempts=?, upgrade_last_error=?,
                  upgrade_last_attempt_at=?,
                  upgrade_reverted_from=COALESCE(?, upgrade_reverted_from)
            WHERE editor_username=? AND machine=?""",
        (arch, guard.get("upgrade_version"), guard.get("upgrade_attempts"),
         guard.get("upgrade_last_error"), guard.get("upgrade_last_attempt_at"),
         guard.get("upgrade_reverted_from"), editor, machine),
    )
    # ...and the revert marker takes itself off once this machine is running a
    # build at or above the one it fell back from: the incident is over, and a
    # chip that needs a human to clear it is a chip that stays on the grid for
    # ever (the lesson the breaker's own latch rule is written from).
    row = conn.execute(
        "SELECT upgrade_reverted_from FROM machine_state "
        "WHERE editor_username=? AND machine=?", (editor, machine)).fetchone()
    reverted = row["upgrade_reverted_from"] if row else None
    if reverted and running_version:
        running = version_tuple(running_version)
        if running and running >= version_tuple(reverted):
            conn.execute(
                "UPDATE machine_state SET upgrade_reverted_from=NULL "
                "WHERE editor_username=? AND machine=?", (editor, machine))


# -- DASH-2: a report refused only because its identity cannot be verified ---
#
# Rotating DASH_SESSION_SECRET (or restoring /data from before it was
# generated) 401s every companion in the fleet: the identity token is an HMAC
# over that secret and never expires. Until this, the grid simply went stale --
# the same shape as a machine that had been switched off. The stamp says the
# opposite: this computer IS talking to us and we are turning it away.
#
# Nothing from the body is stored: the row is found by (editor, machine) and
# only these two columns are written, because at this point in api_report the
# report is UNVERIFIED and must not be able to create or alter fleet data.

def stamp_report_refused(
    conn: sqlite3.Connection, editor: str, machine: str, reason: str, now: str,
) -> bool:
    cur = conn.execute(
        """UPDATE machines SET report_refused_at=?, report_refused_reason=?
            WHERE editor_username=? AND machine=?""",
        (now, reason[:200], editor, machine),
    )
    return cur.rowcount > 0


def clear_report_refused(conn: sqlite3.Connection, editor: str, machine: str) -> None:
    """An accepted report is what clears it. Called on every accepted report:
    the alternative -- clearing it only when it is set -- needs a read first,
    and this runs once per machine per 30 s either way."""
    conn.execute(
        """UPDATE machines SET report_refused_at=NULL, report_refused_reason=NULL
            WHERE editor_username=? AND machine=? AND report_refused_at IS NOT NULL""",
        (editor, machine),
    )


def report_refusal_map(
    conn: sqlite3.Connection,
) -> dict[tuple[str, str], dict[str, Any]]:
    return {
        (r["editor_username"], r["machine"]): {
            "at": r["report_refused_at"], "reason": r["report_refused_reason"]}
        for r in conn.execute(
            "SELECT editor_username, machine, report_refused_at, report_refused_reason "
            "FROM machines WHERE report_refused_at IS NOT NULL").fetchall()
    }


# The rotation drain (DASH-2): which machines were last accepted on a RETIRED
# key. `meta` rather than a column, because it is one small current picture
# with no history worth keeping and a schema version is a shared resource.
META_RETIRED_KEY_IDENTITIES = "identity_retired_key_machines"


def record_retired_key_identity(
    conn: sqlite3.Connection, editor: str, machine: str, now: str, *, retired: bool,
) -> None:
    """Remember (or forget) that this machine's identity token was signed with
    a key that is now only in DASH_SESSION_SECRET_PREVIOUS. `retired=False` on
    an accepted CURRENT-key report is what makes the banner count DOWN as the
    fleet signs back in -- an operator has to be able to see the drain finish."""
    entries = meta_get_json(conn, META_RETIRED_KEY_IDENTITIES)
    entries = entries if isinstance(entries, dict) else {}
    key = f"{editor}/{machine}"
    if retired:
        entries[key] = now
    elif key not in entries:
        return
    else:
        entries.pop(key, None)
    # Bounded: a fleet is tens of machines, and a meta value is not a table.
    if len(entries) > 200:
        entries = dict(sorted(entries.items(), key=lambda kv: kv[1], reverse=True)[:200])
    meta_set_json(conn, META_RETIRED_KEY_IDENTITIES, entries)


def retired_key_identities(conn: sqlite3.Connection) -> dict[str, str]:
    entries = meta_get_json(conn, META_RETIRED_KEY_IDENTITIES)
    return entries if isinstance(entries, dict) else {}


# REL-11: the vendor feed's own age, for the banner. feed_state already holds
# the durable half; this is the derived question the banner asks.
META_FEED_RUNTIME_MISMATCH = "feed_runtime_mismatch"


def set_feed_runtime_mismatch(conn: sqlite3.Connection, payload: Any) -> None:
    """Written by the feed check: "every dashboard build on offer needs a new
    container image". None clears it."""
    if payload is None:
        meta_delete(conn, META_FEED_RUNTIME_MISMATCH)
        return
    meta_set_json(conn, META_FEED_RUNTIME_MISMATCH, payload)


def get_feed_runtime_mismatch(conn: sqlite3.Connection) -> dict[str, Any] | None:
    value = meta_get_json(conn, META_FEED_RUNTIME_MISMATCH)
    return value if isinstance(value, dict) else None


# SYS-2 (2026-09-04): what the VENDOR is offering, per platform, kept where a
# check that has only a database connection can read it. The verified feed
# records live in `app_state` (release_feed._cache), which is process memory
# the collector's alert pass cannot reach -- so "the fleet is behind the
# vendor" used to be measurable only from what this dashboard had managed to
# publish, and a dashboard that REFUSES to publish (a companion needing a
# newer dashboard) reported a fleet that was 0 releases behind for ever.
META_FEED_OFFERED = "feed_offered_versions"


def set_feed_offered(conn: sqlite3.Connection, offered: Any) -> None:
    """{platform: [version, ...]} for companion builds the vendor channel
    carries. Written by every feed check, including one that found nothing
    new: a stale picture is worse than none here."""
    if offered is None:
        meta_delete(conn, META_FEED_OFFERED)
        return
    meta_set_json(conn, META_FEED_OFFERED, offered)


def get_feed_offered(conn: sqlite3.Connection) -> dict[str, list[str]]:
    """{platform: [version, ...]}, empty when no feed check has ever run.
    Empty means UNKNOWN, never "the vendor has nothing": every caller falls
    back on what this dashboard has published rather than concluding the
    fleet is current."""
    value = meta_get_json(conn, META_FEED_OFFERED)
    if not isinstance(value, dict):
        return {}
    out: dict[str, list[str]] = {}
    for platform, versions in value.items():
        if isinstance(versions, list):
            out[str(platform)] = [str(v) for v in versions]
    return out


# How long an admin's pushed update may sit unanswered before the dashboard
# stops asking (REL-8). Long enough for a machine that is away for a fortnight;
# short enough that a request nobody can satisfy does not ride every report for
# ever, showing "pending" on the Packages page and re-arming a download loop on
# a machine that has failed it 2000 times.
MACHINE_UPDATE_REQUEST_MAX_AGE_DAYS = 14


def expire_machine_update_requests(conn: sqlite3.Connection, now: str) -> int:
    """Drop pushed-update requests older than MACHINE_UPDATE_REQUEST_MAX_AGE_DAYS,
    with the reason in the audit ledger -- an admin has to be able to find out
    why the request they made is no longer there."""
    cutoff = (parse_iso(now) - dt.timedelta(
        days=MACHINE_UPDATE_REQUEST_MAX_AGE_DAYS)).isoformat()
    rows = conn.execute(
        """SELECT editor_username, machine, update_requested_version,
                  update_requested_at, update_requested_by
             FROM machines
            WHERE update_requested_version IS NOT NULL
              AND update_requested_at IS NOT NULL
              AND update_requested_at < ?""",
        (cutoff,),
    ).fetchall()
    for row in rows:
        conn.execute(
            """UPDATE machines
                  SET update_requested_version=NULL, update_requested_at=NULL,
                      update_requested_by=NULL
                WHERE editor_username=? AND machine=?""",
            (row["editor_username"], row["machine"]),
        )
        audit(conn, "system", "machine.update_push_expired", row["machine"],
              {"editor": row["editor_username"], "machine": row["machine"],
               "version": row["update_requested_version"],
               "requested_at": row["update_requested_at"],
               "requested_by": row["update_requested_by"],
               "reason": f"not taken within {MACHINE_UPDATE_REQUEST_MAX_AGE_DAYS} days"},
              now=now)
    return len(rows)


def plan_summary_map(
    conn: sqlite3.Connection, keys: Iterable[tuple[str, str]]
) -> dict[tuple[str, str], dict[str, int]]:
    """(editor, machine) -> {count, full, upload_only} for the WHY sentence.

    Two queries for the whole fleet rather than selections_for_machine per row
    (the fleet grid rebuilds every 15 s for every open page), and it carries
    that function's ONE inheritance rule with it: a machine with rows of its
    own never also inherits the unassigned bucket, because that is what makes
    "untick this project on the laptop" expressible (docs/MULTI_MACHINE_PLAN.md).

    Distinguishing `full` from `upload_only` is the whole point: an
    upload-only machine's lane B is MEANT to be idle (CR-85), and a sentence
    that called that a fault would send an admin chasing a machine that is
    working exactly as ticked.
    """
    own: dict[tuple[str, str], dict[str, int]] = {}
    for r in conn.execute(
        "SELECT editor_username, machine, sync_mode, COUNT(*) AS n FROM selections "
        "WHERE machine <> ? GROUP BY editor_username, machine, sync_mode",
        (ANY_MACHINE,),
    ):
        own.setdefault((r["editor_username"], r["machine"]), {})[
            str(r["sync_mode"] or SYNC_MODE_FULL)] = int(r["n"])
    bucket: dict[str, dict[str, int]] = {}
    for r in conn.execute(
        "SELECT editor_username, sync_mode, COUNT(*) AS n FROM selections "
        "WHERE machine = ? GROUP BY editor_username, sync_mode",
        (ANY_MACHINE,),
    ):
        bucket.setdefault(r["editor_username"], {})[
            str(r["sync_mode"] or SYNC_MODE_FULL)] = int(r["n"])
    out: dict[tuple[str, str], dict[str, int]] = {}
    for editor, machine in keys:
        modes = own.get((editor, machine))
        if modes is None:
            modes = bucket.get(editor, {})
        out[(editor, machine)] = {
            "count": sum(modes.values()),
            "full": int(modes.get(SYNC_MODE_FULL, 0)),
            "upload_only": int(modes.get(SYNC_MODE_UPLOAD_ONLY, 0)),
        }
    return out


def request_diagnostics(
    conn: sqlite3.Connection, editor: str, machine: str,
    requested_by: str, now: str,
) -> bool:
    """[ ASK THIS MACHINE WHY ]: one-shot, delivered on the next report (v33).

    False when there is no such machine, on the same reasoning as
    request_lane_b_resume: a request that names nothing must read as a failure
    to the admin rather than as a silent success.

    Unlike the resume request this one is NOT cleared when the reply goes out:
    it clears when a bundle with trigger `admin_request` ARRIVES. Re-sending
    it costs one upload of a text file, and the failure it must not have is
    the one that matters here -- an admin clicking, nothing ever arriving, and
    no way to tell a lost reply from a machine that had nothing to say.
    """
    cur = conn.execute(
        """UPDATE machines
              SET diagnostics_requested_at=?, diagnostics_requested_by=?
            WHERE editor_username=? AND machine=?""",
        (now, requested_by, editor, machine),
    )
    if cur.rowcount > 0:
        audit(conn, requested_by, "diagnostics.request", machine,
              {"editor": editor, "machine": machine}, now=now)
    return cur.rowcount > 0


def clear_diagnostics_request(
    conn: sqlite3.Connection, editor: str, machine: str
) -> None:
    conn.execute(
        """UPDATE machines
              SET diagnostics_requested_at=NULL, diagnostics_requested_by=NULL
            WHERE editor_username=? AND machine=?""",
        (editor, machine),
    )


def diagnostics_request(
    conn: sqlite3.Connection, editor: str, machine: str
) -> dict[str, Any] | None:
    row = conn.execute(
        """SELECT diagnostics_requested_at AS at,
                  diagnostics_requested_by AS by_user
             FROM machines WHERE editor_username=? AND machine=?""",
        (editor, machine),
    ).fetchone()
    if row is None or not row["at"]:
        return None
    return dict(row)


def pending_diagnostics_requests(conn: sqlite3.Connection) -> set[tuple[str, str]]:
    """Which machines have an admin's ASK still in flight, so the button can
    say ASKED rather than inviting a second click at a machine that has
    simply not reported yet (the RESUME button's own rule)."""
    return {
        (r["editor_username"], r["machine"])
        for r in conn.execute(
            "SELECT editor_username, machine FROM machines "
            "WHERE diagnostics_requested_at IS NOT NULL"
        )
    }


def record_diagnostics(
    conn: sqlite3.Connection, *, editor: str, machine: str, machine_id: str,
    trigger: str, at: str, received_at: str, text: str,
) -> int:
    """Store one diagnostics bundle and keep only the newest N for that machine.

    Bounded at WRITE time and not only in prune(): the lane-error trigger can
    fire on every pass of a machine that fails every pass, which is precisely
    the machine whose bundles you want, and precisely the one that would
    otherwise fill /data with them. Newest N because the oldest bundle from a
    machine that has been broken for a week says less than the newest.
    """
    cur = conn.execute(
        "INSERT INTO diagnostics (editor, machine, machine_id, trigger, at, "
        "received_at, text) VALUES (?, ?, ?, ?, ?, ?, ?)",
        (editor, machine, str(machine_id or ""), str(trigger or ""), str(at or ""),
         received_at, str(text or "")[:DIAGNOSTICS_MAX_CHARS]),
    )
    conn.execute(
        """DELETE FROM diagnostics
            WHERE editor=? AND machine=? AND id NOT IN (
              SELECT id FROM diagnostics WHERE editor=? AND machine=?
               ORDER BY id DESC LIMIT ?)""",
        (editor, machine, editor, machine, DIAGNOSTICS_KEEP_PER_MACHINE),
    )
    return int(cur.lastrowid or 0)


def fetch_diagnostics(
    conn: sqlite3.Connection, editor: str | None = None,
    machine: str | None = None, limit: int = 50,
) -> list[dict[str, Any]]:
    """Bundles, newest first. `editor`/`machine` narrow it to one computer."""
    q = "SELECT * FROM diagnostics"
    where: list[str] = []
    params: list[Any] = []
    if editor:
        where.append("editor = ?")
        params.append(editor)
    if machine:
        where.append("machine = ?")
        params.append(machine)
    if where:
        q += " WHERE " + " AND ".join(where)
    q += " ORDER BY id DESC LIMIT ?"
    params.append(max(1, min(int(limit), 200)))
    return [dict(r) for r in conn.execute(q, params)]


def newest_diagnostics_per_machine(
    conn: sqlite3.Connection, limit: int = 50
) -> list[dict[str, Any]]:
    """The newest bundle from each computer that has ever sent one.

    What the admin partial renders: one row per machine, because the question
    it answers is "what did each of these say last", never "show me every
    bundle ever".
    """
    return [
        dict(r) for r in conn.execute(
            """SELECT d.* FROM diagnostics d
                 JOIN (SELECT editor, machine, MAX(id) AS newest FROM diagnostics
                        GROUP BY editor, machine) m
                   ON m.newest = d.id
                ORDER BY d.id DESC LIMIT ?""",
            (max(1, min(int(limit), 200)),),
        )
    ]


def diagnostics_stamp_map(
    conn: sqlite3.Connection
) -> dict[tuple[str, str], dict[str, Any]]:
    """(editor, machine) -> {id, trigger, received_at} of its newest bundle.

    The fleet grid needs "there is an answer for this machine, from N minutes
    ago" without carrying every bundle's text into a 15-second poll.
    """
    return {
        (r["editor"], r["machine"]): {
            "id": r["id"], "trigger": r["trigger"], "received_at": r["received_at"],
        }
        for r in conn.execute(
            """SELECT d.id, d.editor, d.machine, d.trigger, d.received_at
                 FROM diagnostics d
                 JOIN (SELECT editor, machine, MAX(id) AS newest FROM diagnostics
                        GROUP BY editor, machine) m
                   ON m.newest = d.id"""
        )
    }


# -- dashboard-driven file moves (v29, docs/FILE_MOVES.md) ------------------

FILE_MOVE_MAX_AGE_DAYS = 7
FILE_MOVE_COMMAND_LIMIT = 20

# The four states of the SERVER side of a move (v36, DASH-1).
FILE_MOVE_PENDING = "pending"      # written and committed; the rename has not returned yet
FILE_MOVE_DONE = "done"
FILE_MOVE_PARTIAL = "partial"      # the original moved, at least one proxy did not
FILE_MOVE_UNDONE = "undone"        # a later move put it back (UX-11)
# The states a MACHINE can be in beyond applied/not (v36, RES-1).
FILE_MOVE_TARGET_RETRYING = "retrying"
FILE_MOVE_TARGET_BLOCKED = "blocked"


def record_file_move(
    conn: sqlite3.Connection, *, from_slug: str, from_project_rel: str, from_rel: str,
    to_slug: str, to_project_rel: str, to_rel: str, is_dir: bool, proxies_moved: int,
    requested_by: str, now: str, targets: list[tuple[str, str]],
    state: str = FILE_MOVE_DONE, undo_of: int | None = None,
) -> int:
    """The record of a move and the list of computers that have to follow.

    DASH-1 (resilience sweep 2026-08-28): written with `state='pending'` and
    COMMITTED before the server-side rename, then flipped by
    `complete_file_move`. A row that exists while the rename is in flight is
    what makes the crash window recoverable at all -- before this, a rename
    that succeeded and then died left the file moved and nothing anywhere
    saying so. Returns the id."""
    cur = conn.execute(
        """INSERT INTO file_moves
             (from_slug, from_project_rel, from_rel, to_slug, to_project_rel, to_rel,
              is_dir, proxies_moved, requested_by, requested_at, state, undo_of)
           VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
        (from_slug, from_project_rel, from_rel, to_slug, to_project_rel, to_rel,
         int(bool(is_dir)), int(proxies_moved), requested_by, now, state,
         int(undo_of) if undo_of else None),
    )
    move_id = int(cur.lastrowid)
    for editor, machine in sorted(set(targets)):
        if not editor or not machine:
            # The unassigned bucket names no computer; nothing can be told.
            continue
        conn.execute(
            """INSERT OR IGNORE INTO file_move_targets (move_id, editor_username, machine)
               VALUES (?, ?, ?)""",
            (move_id, editor, machine),
        )
    # SYS-11 (2026-08-28): the move already has its own table, but the
    # timeline is where an incident is read, and "the file came back" starts
    # with when it was moved and by whom.
    audit(conn, requested_by, "file.move", from_slug,
          {"move_id": move_id, "from": f"{from_project_rel}/{from_rel}",
           "to": f"{to_project_rel}/{to_rel}", "is_dir": bool(is_dir),
           "machines": len({(e, m) for e, m in targets if e and m})}, now=now)
    return move_id


def _file_move_cutoff(now: str, max_age_days: int) -> str:
    try:
        stamp = dt.datetime.fromisoformat(now)
    except ValueError:
        # Microseconds dropped (bug-hunt-2026-09-03 dash-db-4): every stored
        # timestamp comes from utcnow_iso(), which strips them, and the
        # comparison against this cutoff is lexicographic -- a '.123456'
        # fraction sorts above the '+00:00' offset it displaces, expiring a
        # row delivered in the same second one second early.
        stamp = dt.datetime.now(dt.timezone.utc).replace(microsecond=0)
    return (stamp - dt.timedelta(days=max_age_days)).isoformat()


def complete_file_move(
    conn: sqlite3.Connection, move_id: int, *, state: str, proxies_moved: int = 0,
    detail: str = "",
) -> None:
    """Phase two of DASH-1: the server-side rename has returned. `state` is
    `done`, `partial` (the original moved, a proxy did not) or `undone`."""
    conn.execute(
        "UPDATE file_moves SET state=?, proxies_moved=?, state_detail=? WHERE id=?",
        (state, int(proxies_moved), (detail or "")[:512] or None, int(move_id)),
    )


def unfinished_file_moves(conn: sqlite3.Connection) -> list[dict[str, Any]]:
    """Rows still `pending`: the record was committed, the rename may or may
    not have happened, and nobody has been told either way. Read at boot and
    once per collector cycle (api.reconcile_file_moves)."""
    return [dict(r) for r in conn.execute(
        "SELECT * FROM file_moves WHERE state=? ORDER BY id", (FILE_MOVE_PENDING,))]


def pending_file_moves(
    conn: sqlite3.Connection, editor: str, machine: str, now: str,
    max_age_days: int = FILE_MOVE_MAX_AGE_DAYS, limit: int = FILE_MOVE_COMMAND_LIMIT,
) -> list[dict[str, Any]]:
    """The moves this computer has not yet reported applying, oldest first.

    UX-5 (resilience sweep 2026-08-28): bounded by DELIVERY, not by age. The
    old age cutoff dropped a command the machine had never even heard of --
    and that machine is exactly the one still holding the file at the old
    path, so lane A (which never deletes) put it straight back on the NAS the
    week after: the failure this whole feature exists to prevent. An old
    command is harmless because the companion refuses a move whose source is
    not where the command says. What DOES expire is a command that was
    delivered and never answered (`expired_at`, written by
    `expire_delivered_file_moves`), and that expiry is loud on the project
    page rather than silent, with a one-click re-issue.

    A `pending` move is never offered: its rename has not been confirmed, so
    telling a machine to follow it would be telling it to follow a move that
    may not have happened."""
    del max_age_days  # kept for callers; delivery, not age, is the bound now
    rows = conn.execute(
        """SELECT m.id, m.from_slug, m.from_project_rel, m.from_rel,
                  m.to_slug, m.to_project_rel, m.to_rel, m.is_dir,
                  m.requested_by, m.requested_at
             FROM file_move_targets t JOIN file_moves m ON m.id = t.move_id
            WHERE t.editor_username=? AND t.machine=? AND t.applied_at IS NULL
              AND t.expired_at IS NULL AND m.state IN (?, ?)
            ORDER BY m.id LIMIT ?""",
        (editor, machine, FILE_MOVE_DONE, FILE_MOVE_PARTIAL, limit),
    ).fetchall()
    return [dict(r) for r in rows]


def expire_delivered_file_moves(
    conn: sqlite3.Connection, now: str, max_age_days: int = FILE_MOVE_MAX_AGE_DAYS,
) -> list[dict[str, Any]]:
    """Age out targets that were TOLD and never answered (UX-5 / DASH-9).

    Returns the rows just expired, so the caller can say so. Undelivered
    targets are untouched, deliberately: those machines have not had their
    chance yet."""
    cutoff = _file_move_cutoff(now, max_age_days)
    rows = [dict(r) for r in conn.execute(
        """SELECT move_id, editor_username, machine, delivered_at
             FROM file_move_targets
            WHERE applied_at IS NULL AND expired_at IS NULL
              AND delivered_at IS NOT NULL AND delivered_at < ?""",
        (cutoff,),
    )]
    for row in rows:
        conn.execute(
            "UPDATE file_move_targets SET expired_at=? "
            " WHERE move_id=? AND editor_username=? AND machine=?",
            (now, row["move_id"], row["editor_username"], row["machine"]),
        )
    return rows


def reissue_file_move(
    conn: sqlite3.Connection, move_id: int, editor: str, machine: str, now: str,
    actor: str = "",
) -> bool:
    """Put an expired target back in the queue (DASH-9's one-click re-issue).
    Clears the delivery stamp too, so the age clock starts again from the
    machine's next report rather than from the delivery it never answered."""
    cur = conn.execute(
        """UPDATE file_move_targets
              SET expired_at=NULL, delivered_at=NULL, state=NULL
            WHERE move_id=? AND editor_username=? AND machine=? AND applied_at IS NULL""",
        (int(move_id), editor, machine),
    )
    if cur.rowcount and actor:
        audit(conn, actor, "file.move.reissue", f"{editor}/{machine}",
              {"move_id": int(move_id)}, now=now)
    return cur.rowcount > 0


def mark_file_moves_delivered(
    conn: sqlite3.Connection, move_ids: list[int], editor: str, machine: str, now: str,
) -> None:
    """First delivery only: the stamp says when the machine was first told,
    and the command keeps riding every report until it is APPLIED."""
    for move_id in move_ids:
        conn.execute(
            """UPDATE file_move_targets SET delivered_at=COALESCE(delivered_at, ?)
                WHERE move_id=? AND editor_username=? AND machine=?""",
            (now, move_id, editor, machine),
        )


def mark_file_move_applied(
    conn: sqlite3.Connection, move_id: int, editor: str, machine: str,
    ok: bool, detail: str | None, now: str, state: str | None = None,
    attempts: int | None = None, relink_pending: bool = False,
) -> bool:
    """The machine's answer.

    RES-1 (resilience sweep 2026-08-28): `state='retrying'` records the
    attempt and its error WITHOUT retiring the command -- a move Resolve is
    holding open is going to be tried again in ten minutes, and the old
    behaviour (any failure retires it for ever) is what let lane A put the
    file back the next day. `state='blocked'` is the companion having run out
    of attempts: an answer, and one the project page names as such rather
    than a success-shaped "FAILED" nobody reads. An old companion sends
    neither and keeps the original meaning: a failure is an answer.

    `relink_pending` (RES-10) means the copy moved but the project that
    references it was not open, so Resolve has not been repointed yet."""
    if state == FILE_MOVE_TARGET_RETRYING:
        cur = conn.execute(
            """UPDATE file_move_targets SET state=?, attempts=?, last_error=?, detail=?
                WHERE move_id=? AND editor_username=? AND machine=? AND applied_at IS NULL""",
            (state, int(attempts or 0), (detail or "")[:512] or None,
             (detail or "")[:512] or None, move_id, editor, machine),
        )
        return cur.rowcount > 0
    cur = conn.execute(
        """UPDATE file_move_targets
              SET applied_at=?, ok=?, detail=?, state=?, attempts=?,
                  last_error=?, relink_pending=?, expired_at=NULL
            WHERE move_id=? AND editor_username=? AND machine=? AND applied_at IS NULL""",
        (now, int(bool(ok)), (detail or "")[:512] or None, state,
         int(attempts or 0), None if ok else (detail or "")[:512] or None,
         int(bool(relink_pending)), move_id, editor, machine),
    )
    return cur.rowcount > 0


def file_moves_for_project(
    conn: sqlite3.Connection, slug: str, limit: int = 20,
) -> list[dict[str, Any]]:
    """Moves out of or into this project, newest first, each with its
    per-computer outcomes -- what the project page draws."""
    moves = [dict(r) for r in conn.execute(
        """SELECT * FROM file_moves WHERE from_slug=? OR to_slug=?
            ORDER BY id DESC LIMIT ?""",
        (slug, slug, limit),
    )]
    for move in moves:
        _hydrate_file_move(conn, move)
    return moves


def _hydrate_file_move(conn: sqlite3.Connection, move: dict[str, Any]) -> dict[str, Any]:
    move["targets"] = [dict(r) for r in conn.execute(
        """SELECT editor_username, machine, delivered_at, applied_at, ok, detail,
                  attempts, last_error, state, expired_at, relink_pending
             FROM file_move_targets WHERE move_id=?
            ORDER BY editor_username, machine""",
        (move["id"],),
    )]
    now = utcnow_iso()
    for target in move["targets"]:
        # The age of the WAIT, which is what the project page's amber/red chip
        # is drawn from (DASH-9). Delivery when there was one, the request
        # otherwise: a machine that has not been told yet is not late.
        target["waiting_days"] = (
            0.0 if target["applied_at"]
            else _days_between(target["delivered_at"] or move["requested_at"], now))
    move["waiting"] = sum(1 for t in move["targets"] if not t["applied_at"])
    move["failed"] = sum(1 for t in move["targets"] if t["applied_at"] and not t["ok"])
    move["expired"] = sum(1 for t in move["targets"] if t["expired_at"])
    move["blocked"] = sum(
        1 for t in move["targets"] if t["state"] == FILE_MOVE_TARGET_BLOCKED)
    move["relink_pending"] = sum(1 for t in move["targets"] if t["relink_pending"])
    # UX-11: the undo is offered only while every computer either has it or is
    # still waiting for it. A machine that FAILED or is BLOCKED has a local
    # copy at the old path, and moving the server copy back under it would
    # leave the fleet in a third state nobody asked for.
    move["undoable"] = (
        move["state"] in (FILE_MOVE_DONE, FILE_MOVE_PARTIAL)
        and not move["failed"] and not move["undone_by"]
    )
    return move


def file_move(conn: sqlite3.Connection, move_id: int) -> dict[str, Any] | None:
    row = conn.execute("SELECT * FROM file_moves WHERE id=?", (int(move_id),)).fetchone()
    return _hydrate_file_move(conn, dict(row)) if row is not None else None


def add_file_move_targets(
    conn: sqlite3.Connection, move_id: int, targets: list[tuple[str, str]],
) -> int:
    """Add computers to a move's target list (UX-11's undo).

    An undo has to reach the machines the ORIGINAL reached, and the inverse
    move's own source project is the destination project -- which some of
    them may not sync at all. Without this the undo would move the server
    copy back and leave every machine holding it at the other path, i.e. the
    duplicate the feature exists to prevent, made by the undo button."""
    added = 0
    for editor, machine in sorted(set(targets)):
        if not editor or not machine:
            continue
        cur = conn.execute(
            """INSERT OR IGNORE INTO file_move_targets (move_id, editor_username, machine)
               VALUES (?, ?, ?)""",
            (int(move_id), editor, machine),
        )
        added += cur.rowcount or 0
    return added


def mark_file_move_undone(
    conn: sqlite3.Connection, move_id: int, undo_id: int,
) -> None:
    conn.execute("UPDATE file_moves SET state=?, undone_by=? WHERE id=?",
                 (FILE_MOVE_UNDONE, int(undo_id), int(move_id)))


def file_moves_awaiting_machines(
    conn: sqlite3.Connection, now: str, limit: int = 50,
) -> list[dict[str, Any]]:
    """Every move some computer still has not applied, oldest first (DASH-9).

    This is the panel that used to not exist: a target with `applied_at IS
    NULL` was kept for ever and read by nobody, so "a move was never
    completed and that machine may re-upload the old path" was a question
    with no page that answered it. `waiting_days` is the age of the WAIT (the
    delivery when there was one, the request otherwise), which is what the
    amber/red chip is drawn from."""
    rows = [dict(r) for r in conn.execute(
        """SELECT t.move_id, t.editor_username, t.machine, t.delivered_at,
                  t.expired_at, t.attempts, t.last_error, t.state,
                  m.from_project_rel, m.from_rel, m.to_project_rel, m.to_rel,
                  m.from_slug, m.to_slug, m.requested_by, m.requested_at, m.state AS move_state
             FROM file_move_targets t JOIN file_moves m ON m.id = t.move_id
            WHERE t.applied_at IS NULL AND m.state IN (?, ?)
            ORDER BY m.requested_at, t.move_id LIMIT ?""",
        (FILE_MOVE_DONE, FILE_MOVE_PARTIAL, int(limit)),
    )]
    for row in rows:
        since = row["delivered_at"] or row["requested_at"]
        row["waiting_days"] = _days_between(since, now)
    return rows


def _days_between(then: str | None, now: str) -> float:
    if not then:
        return 0.0
    try:
        return max(0.0, (parse_iso(now) - parse_iso(then)).total_seconds() / 86400.0)
    except (ValueError, TypeError):
        return 0.0


# -- the admin-side Resolve undo (v40, SYS-15b, 2026-08-29) -----------------
#
# The same acknowledgement contract as `file_moves`, and for the same reason:
# the dashboard cannot reach an editor's PC, so a command is delivered on the
# report reply and keeps riding every report until the machine ANSWERS. A
# failure that is going to clear itself (Resolve is not open, or the wrong
# project is) answers `retrying` and stays on the books; a failure that will
# not answers once and retires.

RESOLVE_UNDO_COMMAND_LIMIT = 4
RESOLVE_UNDO_RETRYING = "retrying"
# RES-4 (usability sweep 2026-09-04): a THIRD answer that is not a failure.
# "retrying" means the companion tried and something got in the way; PARKED
# means it did not try at all, because no project is open in Resolve, and it
# will as soon as one is. Both keep the command on the books -- the
# difference is what an admin reads on the panel, where "retrying" for a
# machine whose editor simply has not opened Resolve today looks like
# something that is going wrong.
RESOLVE_UNDO_PARKED = "parked"
# The states that record an attempt WITHOUT retiring the command.
RESOLVE_UNDO_OPEN_STATES = (RESOLVE_UNDO_RETRYING, RESOLVE_UNDO_PARKED)
# What one machine reports about its own journals. Capped here because it is
# client-supplied and lands in a column: an editor who relinks daily holds 60
# days of them (resolve_journal.RETENTION_DAYS), and an admin picking one only
# ever wants the recent ones.
RESOLVE_JOURNALS_MAX = 20


def request_resolve_undo(
    conn: sqlite3.Connection, editor: str, machine: str, journal_id: str,
    project_name: str, requested_by: str, now: str,
) -> int:
    """Ask one machine to replay one undo journal in reverse. Returns the
    request id, or 0 when there is no such machine.

    0 rather than a silent success, on request_lane_b_resume's reasoning: a
    request that names nothing must read as a failure to the admin."""
    if machine not in machines_of(conn, editor):
        return 0
    cur = conn.execute(
        """INSERT INTO resolve_undo_requests
               (editor_username, machine, journal_id, project_name,
                requested_by, requested_at)
           VALUES (?,?,?,?,?,?)""",
        (editor, machine, journal_id[:256], (project_name or "")[:256],
         requested_by, now),
    )
    request_id = int(cur.lastrowid or 0)
    audit(conn, requested_by, "resolve.undo.request", f"{editor}/{machine}",
          {"journal": journal_id, "project": project_name}, now=now)
    return request_id


def pending_resolve_undos(
    conn: sqlite3.Connection, editor: str, machine: str,
    limit: int = RESOLVE_UNDO_COMMAND_LIMIT,
) -> list[dict[str, Any]]:
    """The undos this computer has not answered yet, oldest first.

    Bounded by DELIVERY and by nothing else, like pending_file_moves: an old
    command is harmless because the companion refuses a journal that is not
    where the command says, and the machine that has not answered is exactly
    the one still holding the wrong clip paths."""
    return [dict(r) for r in conn.execute(
        """SELECT id, journal_id, project_name, requested_by, requested_at
             FROM resolve_undo_requests
            WHERE editor_username=? AND machine=? AND applied_at IS NULL
            ORDER BY id LIMIT ?""",
        (editor, machine, int(limit)),
    )]


def mark_resolve_undos_delivered(
    conn: sqlite3.Connection, request_ids: list[int], now: str,
) -> None:
    """First delivery only: the stamp says when the machine was first told,
    and the command keeps riding until it is answered."""
    for request_id in request_ids:
        conn.execute(
            "UPDATE resolve_undo_requests SET delivered_at=COALESCE(delivered_at, ?) "
            " WHERE id=?", (now, int(request_id)))


def mark_resolve_undo_applied(
    conn: sqlite3.Connection, request_id: int, editor: str, machine: str,
    ok: bool, detail: str, now: str, state: str | None = None,
    attempts: int | None = None,
) -> bool:
    """The machine's answer.

    `state='retrying'` records the attempt WITHOUT retiring the command, the
    same way mark_file_move_applied does: "Resolve is not open" and "another
    project is open" are both states that clear themselves, and retiring the
    command on one of them would leave the wrong paths in place with the
    admin believing they had been undone.

    `state='parked'` (RES-4, 2026-09-04) is the same non-retiring write with
    an honest label: the companion did not attempt anything because no
    project is open. A companion too old to say `parked` sends `retrying`
    with the reason in `detail`, which is why this is additive and not a
    rename."""
    if state in RESOLVE_UNDO_OPEN_STATES:
        cur = conn.execute(
            """UPDATE resolve_undo_requests SET state=?, attempts=?, detail=?
                WHERE id=? AND editor_username=? AND machine=? AND applied_at IS NULL""",
            (state, int(attempts or 0), (detail or "")[:512],
             int(request_id), editor, machine))
        return cur.rowcount > 0
    cur = conn.execute(
        """UPDATE resolve_undo_requests
              SET applied_at=?, ok=?, detail=?, state=?, attempts=?
            WHERE id=? AND editor_username=? AND machine=? AND applied_at IS NULL""",
        (now, int(bool(ok)), (detail or "")[:512], state or ("done" if ok else "failed"),
         int(attempts or 0), int(request_id), editor, machine))
    return cur.rowcount > 0


def resolve_undos_for_machine(
    conn: sqlite3.Connection, editor: str, machine: str, limit: int = 20,
) -> list[dict[str, Any]]:
    """What has been asked of this computer and what came back, newest
    first -- what the machine's recovery panel draws."""
    return [dict(r) for r in conn.execute(
        """SELECT * FROM resolve_undo_requests
            WHERE editor_username=? AND machine=? ORDER BY id DESC LIMIT ?""",
        (editor, machine, int(limit)),
    )]


def store_resolve_journals(
    conn: sqlite3.Connection, editor: str, machine: str,
    journals: list[dict[str, Any]] | None,
) -> None:
    """What undo journals this machine holds (v40).

    ABSENT IS NOT EMPTY: a companion too old to report journals sends None,
    and overwriting the stored list with [] would tell an admin that a
    machine which has been relinking for weeks has nothing to undo. Only a
    report that CARRIED the section replaces it."""
    if journals is None:
        return
    text = json.dumps(journals[:RESOLVE_JOURNALS_MAX], separators=(",", ":"))
    conn.execute(
        "UPDATE machine_state SET resolve_journals=? "
        " WHERE editor_username=? AND machine=?", (text, editor, machine))


def machine_resolve_journals(
    conn: sqlite3.Connection, editor: str, machine: str,
) -> list[dict[str, Any]]:
    """The journals this machine last reported, or [] when it has reported
    none -- never a raise: a damaged blob must not break the page that is
    trying to recover from something."""
    row = conn.execute(
        "SELECT resolve_journals FROM machine_state "
        " WHERE editor_username=? AND machine=?", (editor, machine)).fetchone()
    if row is None or not row["resolve_journals"]:
        return []
    try:
        data = json.loads(row["resolve_journals"])
    except (ValueError, TypeError):
        return []
    return [d for d in data if isinstance(d, dict)] if isinstance(data, list) else []


def copy_machine_plan(
    conn: sqlite3.Connection, editor: str, source: str, target: str,
    copied_by: str, now: str,
) -> int:
    """Give `target` the same projects as `source`, replacing whatever it
    had. Returns how many projects it now holds.

    A new computer starts with an EMPTY plan on purpose (the plan doc's §3.2:
    inheritance would silently start a 50 GB download on a laptop nobody
    asked to fill). This is the affordance that makes that bearable -- the
    admin's "same as the desktop, please" in one click.

    Raises ValueError when the SOURCE is a wired machine (bug-hunt-2026-09-03
    dash-db-1): a base rig holds no tick, so since that fix its plan reads
    empty, and copying nothing while answering "ok, 0 projects" is the shape
    that makes an admin believe the laptop was filled. The target being wired
    is refused a layer up (api.api_copy_machine_plan, 409).

    Raises ValueError too when the source holds NO projects (DCORE-2,
    2026-09-04): the DELETE below runs either way, so "copy an empty plan"
    and "wipe this computer's plan" were the same call, and the route
    answered ok.
    """
    if (editor, source) in base_machines(conn):
        raise ValueError(
            f"{source!r} is wired to the server: it works directly off the NAS and "
            "holds no plan, so there is nothing to copy from it"
        )
    rows = selections_for_machine(conn, editor, source)
    if not rows:
        # DCORE-2 (usability sweep 2026-09-04): the DELETE below is
        # unconditional, so an EMPTY source does not copy nothing -- it
        # EMPTIES the target, and answered "ok, 0 projects" while doing it.
        # assignments.js asks first now, but a client-side refusal is one
        # curl away from bypassed and this is the shape that silently stops a
        # computer syncing.
        raise ValueError(
            f"{source} has no projects ticked - copying it would empty {target}."
        )
    conn.execute(
        "DELETE FROM selections WHERE editor_username=? AND machine=?",
        (editor, target),
    )
    # Inserted directly, NOT through add_selection: that materialises the
    # unassigned bucket onto a machine whose first own row is being written
    # (dash-core-1), and here the DELETE above has just made the target look
    # like one. "Replacing whatever it had" must mean the source's plan and
    # nothing else -- its modes included: an upload-only tick copied as a
    # full one would start the very download the source was ticked to avoid.
    for position, row in enumerate(rows, start=1):
        conn.execute(
            """INSERT OR IGNORE INTO selections
                 (editor_username, machine, project_slug, position, created_at,
                  created_by, sync_mode)
               VALUES (?, ?, ?, ?, ?, ?, ?)""",
            (editor, target, row["slug"], position, now, copied_by,
             row.get("sync_mode") or SYNC_MODE_FULL),
        )
    return len(rows)


def adopt_renamed_machine(
    conn: sqlite3.Connection, editor: str, old_machine: str, new_machine: str,
    *, same_computer: bool = False,
) -> bool:
    """Somebody renamed their PC. Carry what belongs to the COMPUTER across.

    Only the plan and the sticky root move: manifests, lane reports and
    transfers are observations of a moment and rebuild themselves under the
    new name within one report cycle (the stale rows age out through
    evict_extra_machines). The plan does not rebuild -- nobody re-ticks four
    projects because Windows was renamed -- so without this a rename reads as
    a brand-new computer with an empty plan, which is the one outcome that
    silently stops an editor syncing.

    REFUSED (returns False, nothing written) when `new_machine` is already a
    registered computer of this editor. Until 2026-08-19 this DELETEd
    whatever sat at the new name before moving the old rows across, so an
    editor who renamed PC B to PC A's name -- or restored an image carrying
    PC A's machine.json onto a box called B -- silently lost PC B's plan and
    sticky root, and upsert_machine then wrote A's identity over B's
    (ultrareview 2026-08-19). MULTI_MACHINE_PLAN.md §6 calls a same-person
    hostname collision "solved by construction"; it is not, because every
    table but this registry is keyed on the hostname. So the one thing this
    must never do is destroy a plan to resolve one: both stay, the collision
    is logged, and an admin copies or clears a plan by hand. Under-sharing is
    the safe direction.

    `same_computer=True` is the DEFERRED half of SYS-18a (2026-08-29). A
    rename now has its first report refused as a possible disk clone, which
    registers the new hostname; when the old row is still quiet a report or
    two later the rename is confirmed and adopted, and by then the new name
    is "taken" by the row that refusal created. So the existence test is
    replaced -- never weakened -- by the thing it was protecting: a row at
    the new name that has a PLAN or a sticky root of its own is a different
    computer, and is refused exactly as before. What is left to adopt onto is
    a registry row and nothing else, so this can still destroy nothing."""
    if not old_machine or not new_machine or old_machine == new_machine:
        return False
    taken = conn.execute(
        "SELECT 1 FROM machines WHERE editor_username=? AND machine=?",
        (editor, new_machine),
    ).fetchone()
    if taken is not None:
        if not same_computer:
            return False
        for table in ("selections", "editor_prefs"):
            own = conn.execute(
                f"SELECT 1 FROM {table} WHERE editor_username=? AND machine=? LIMIT 1",
                (editor, new_machine),
            ).fetchone()
            if own is not None:
                return False
    for table in ("selections", "editor_prefs"):
        conn.execute(
            f"DELETE FROM {table} WHERE editor_username=? AND machine=?",
            (editor, new_machine),
        )
        conn.execute(
            f"UPDATE {table} SET machine=? WHERE editor_username=? AND machine=?",
            (new_machine, editor, old_machine),
        )
    conn.execute(
        "DELETE FROM machines WHERE editor_username=? AND machine=?",
        (editor, old_machine),
    )
    return True


def materialise_bucket(
    conn: sqlite3.Connection, editor: str, machine: str
) -> int:
    """Give a machine that is INHERITING the unassigned bucket its own copy of
    it, before its first own row eclipses the lot (dash-core-1, 2026-08-21).

    selections_for_machine hands the bucket to a machine only while it has no
    rows of its own, so the FIRST own row silently replaced the whole
    inherited plan: an admin who ticked A and B for a new editor before their
    companion had reported, then ticked C a day later, left that machine with
    exactly [C] and the next enforce cycle unshared A and B from it. The
    mirror image was an untick of an inherited project deleting 0 rows and
    reporting changed=false while the project kept syncing.

    Copies rather than moves: the bucket still applies to this person's OTHER
    computers, and to the next one they register. created_at/created_by come
    across unchanged, because who asked for this project and when is the same
    fact it was before it was pinned to a machine."""
    if not machine or machine == ANY_MACHINE:
        return 0
    own = conn.execute(
        "SELECT 1 FROM selections WHERE editor_username=? AND machine=? LIMIT 1",
        (editor, machine),
    ).fetchone()
    if own is not None:
        return 0                      # has a plan of its own: nothing inherited
    copied = 0
    for row in conn.execute(
        """SELECT project_slug, position, created_at, created_by, sync_mode
             FROM selections
            WHERE editor_username=? AND machine=? ORDER BY position""",
        (editor, ANY_MACHINE),
    ).fetchall():
        cur = conn.execute(
            """INSERT OR IGNORE INTO selections
                 (editor_username, machine, project_slug, position, created_at,
                  created_by, sync_mode, changed_at)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?)""",
            (editor, machine, row["project_slug"], row["position"],
             row["created_at"], row["created_by"], row["sync_mode"],
             # NOT stamped as a change (DASH-8, resilience sweep 2026-08-28):
             # materialising the bucket writes the plan this machine was
             # already inheriting, so freezing the enforce cycle on it would
             # delay a share nobody asked to change.
             row["created_at"]),
        )
        copied += cur.rowcount
    return copied


def add_selection(
    conn: sqlite3.Connection, editor: str, slug: str, created_by: str, now: str,
    machine: str = ANY_MACHINE, sync_mode: str = SYNC_MODE_FULL,
) -> bool:
    """Tick, for ONE computer, in one MODE. Returns True when something
    changed: a new row, or an existing tick whose mode was switched.
    Position = end of that machine's queue (the order its sequencer works
    through); switching the mode of an existing tick keeps its position,
    because the queue order is a separate fact from what the tick carries."""
    if sync_mode not in SYNC_MODES:
        raise ValueError(f"unknown sync mode {sync_mode!r}")
    # dash-core-1: BEFORE the first own row, or this tick is the only project
    # this machine is left with.
    materialise_bucket(conn, editor, machine)
    next_pos = conn.execute(
        """SELECT COALESCE(MAX(position), 0) + 1 FROM selections
            WHERE editor_username=? AND machine=?""",
        (editor, machine),
    ).fetchone()[0]
    cur = conn.execute(
        """INSERT OR IGNORE INTO selections
             (editor_username, machine, project_slug, position, created_at,
              created_by, sync_mode, changed_at)
           VALUES (?, ?, ?, ?, ?, ?, ?, ?)""",
        (editor, machine, slug, next_pos, now, created_by, sync_mode, now),
    )
    if cur.rowcount > 0:
        return True
    cur = conn.execute(
        """UPDATE selections SET sync_mode=?, changed_at=?
            WHERE editor_username=? AND machine=? AND project_slug=? AND sync_mode<>?""",
        (sync_mode, now, editor, machine, slug, sync_mode),
    )
    return cur.rowcount > 0


def add_selection_for_person(
    conn: sqlite3.Connection, editor: str, slug: str, created_by: str, now: str,
    sync_mode: str = SYNC_MODE_FULL,
) -> bool:
    """Tick for EVERY computer this person has (the person-level control).

    The sidebar checkbox and a tick with no `?machine=` both mean "I want
    this project", which is every machine they use. Writing the unassigned
    bucket instead would be silently ineffective for anyone whose machines
    already have plans of their own -- the bucket only applies where there is
    no plan. An editor with no computer on record yet DOES get the bucket,
    which their first report adopts.

    A WIRED machine is skipped (dash-admin-8 / data-model-1, 2026-08-21): it
    works directly off the NAS tree, so a row for it can never make progress
    and never clears -- CR-28's permanent [ GETTING READY ] chip, one machine
    over. CR-28's own refusal is per PERSON and cannot see this: an account
    with a wired desktop AND a remote laptop is not base-only."""
    known = machines_of(conn, editor)
    wired = base_machines(conn)
    targets = [m for m in known if (editor, m) not in wired]
    if not known:
        targets = [ANY_MACHINE]
    # A list, not a generator: any() short-circuits, and the second computer
    # would never get its row.
    return any([
        add_selection(conn, editor, slug, created_by=created_by, now=now, machine=m,
                      sync_mode=sync_mode)
        for m in targets
    ])


def remove_selection(
    conn: sqlite3.Connection, editor: str, slug: str, machine: str | None = None
) -> bool:
    """Untick. `machine=None` means EVERY machine of this editor, including
    the unassigned bucket: it is what the person-level control does, and what
    an old companion's DELETE (which cannot name a machine) has to mean --
    under-sharing is the safe direction for a removal."""
    if machine is None:
        cur = conn.execute(
            "DELETE FROM selections WHERE editor_username=? AND project_slug=?",
            (editor, slug),
        )
    else:
        # dash-core-1: unticking a project this machine only holds by
        # INHERITANCE deleted nothing, answered changed=false, and left it
        # syncing. Materialise the bucket first and the delete lands -- and
        # only when the bucket really is where this tick came from, so a
        # no-op removal does not quietly end the inheritance.
        if machine != ANY_MACHINE and conn.execute(
            """SELECT 1 FROM selections
                WHERE editor_username=? AND machine=? AND project_slug=?""",
            (editor, ANY_MACHINE, slug),
        ).fetchone() is not None:
            materialise_bucket(conn, editor, machine)
        cur = conn.execute(
            """DELETE FROM selections
                WHERE editor_username=? AND machine=? AND project_slug=?""",
            (editor, machine, slug),
        )
    return cur.rowcount > 0


def selection_placements(
    conn: sqlite3.Connection, editor: str, slug: str, machine: str | None = None
) -> list[dict[str, str]]:
    """WHERE this project is ticked for this person right now, and in which
    mode: [{"machine": ..., "mode": ...}], the unassigned bucket included as
    machine "".

    Taken as a SNAPSHOT either side of a plan change, this is what makes
    DASH-8's undo a restore rather than a guess: an untick of a person-level
    tick removed rows from two computers in two different modes, and nothing
    anywhere recorded that. `machine=None` is every computer, matching
    remove_selection's own meaning of the word.
    """
    q = ("SELECT machine, sync_mode FROM selections "
         "WHERE editor_username=? AND project_slug=?")
    params: list[Any] = [editor, slug]
    if machine is not None:
        q += " AND machine=?"
        params.append(machine)
    return [{"machine": r["machine"], "mode": r["sync_mode"]}
            for r in conn.execute(q + " ORDER BY machine", params)]


# ---------------------------------------------------------------- fleet audit
# SYS-11 / DASH-8 (resilience sweep 2026-08-28). One append-only ledger for
# every state change an admin (or a companion) makes, written from the routes
# that already exist. The alternative -- and what this replaces -- is
# reconstructing an incident from four differently-shaped state tables and a
# container log that rotates.

AUDIT_MAX_AGE_DAYS = 180

# How long a plan change is left alone by the enforce cycle, so DASH-8's
# [ UNDO ] inside that window costs nothing on Syncthing: an unshare that
# never happened needs no re-share, and a re-share is what restarts the
# folder on every device holding it.
PLAN_FREEZE_SECONDS = 60

# How far back the fleet page's "recent plan changes" panel looks. An UNDO
# offered for a change made yesterday is not an undo, it is a second decision
# taken with less information than the first.
PLAN_UNDO_WINDOW_SECONDS = 3600

AUDIT_TICK = "plan.tick"
AUDIT_UNTICK = "plan.untick"
AUDIT_PLAN_UNDO = "plan.undo"
# DCORE-2 (usability sweep 2026-09-04). A copy is a BATCH of ticks and
# unticks, and it is recorded as one row per project in exactly that shape --
# that is what puts it in RECENT PLAN CHANGES with a working [ UNDO ] (which
# restores one project's placements) and what gives its removals the same
# 60 s enforce-cycle grace an untick gets. This kind is the SUMMARY row
# beside them, for the fleet timeline: "who replaced which computer's plan
# with which", which no per-project row can say.
AUDIT_PLAN_COPY = "plan.copy"


def audit(
    conn: sqlite3.Connection, actor: str, action: str, subject: str = "",
    detail: Mapping[str, Any] | None = None, now: str | None = None,
) -> int:
    """Append one row to the fleet audit ledger and return its id.

    Deliberately NOT wrapped in a try/except: it is one INSERT on the
    connection the change itself is being written on, so it lands in the same
    transaction and cannot record something that was then rolled back (nor
    lose the record of something that was not). Call it BEFORE the route's
    commit; a route that has already committed has to commit again.

    `actor` is the session's admin username, or the editor name for a write a
    companion originated. Never blank: "" would read as "the system did it",
    which is the answer this table exists to stop giving.
    """
    cur = conn.execute(
        "INSERT INTO fleet_audit (at, actor, action, subject, detail_json) "
        "VALUES (?, ?, ?, ?, ?)",
        (now or utcnow_iso(), str(actor or "?"), action, str(subject or ""),
         json.dumps(dict(detail or {}), sort_keys=True)),
    )
    return int(cur.lastrowid or 0)


def _audit_row(row: sqlite3.Row) -> dict[str, Any]:
    out = dict(row)
    try:
        out["detail"] = json.loads(out.get("detail_json") or "{}")
    except (ValueError, TypeError):
        # A row nothing can parse is still evidence that something happened:
        # show it as a raw string rather than dropping it from the timeline.
        out["detail"] = {"raw": out.get("detail_json")}
    return out


def fetch_audit(
    conn: sqlite3.Connection, limit: int = 200, subject: str | None = None,
    actions: tuple[str, ...] | None = None,
) -> list[dict[str, Any]]:
    """The timeline: newest first. `subject` is a substring match over the
    noun, the actor and the action, because what a human remembers is "FF4"
    or "ruskin", not which column it was stored in."""
    q = "SELECT * FROM fleet_audit"
    params: list[Any] = []
    where: list[str] = []
    if subject:
        where.append("(subject LIKE ? OR actor LIKE ? OR action LIKE ?)")
        like = f"%{subject}%"
        params += [like, like, like]
    if actions:
        where.append("action IN (%s)" % ", ".join("?" for _ in actions))
        params += list(actions)
    if where:
        q += " WHERE " + " AND ".join(where)
    q += " ORDER BY id DESC LIMIT ?"
    params.append(max(1, min(int(limit), 1000)))
    return [_audit_row(r) for r in conn.execute(q, params)]


def audit_entry(conn: sqlite3.Connection, audit_id: int) -> dict[str, Any] | None:
    row = conn.execute("SELECT * FROM fleet_audit WHERE id=?", (int(audit_id),)).fetchone()
    return _audit_row(row) if row is not None else None


def audit_since(
    conn: sqlite3.Connection, since: str, limit: int = 200,
    actions: tuple[str, ...] | None = None,
) -> list[dict[str, Any]]:
    """Audit rows at or after `since`, OLDEST first (SYS-8).

    Oldest first because the one consumer is a weekly report a person reads
    top to bottom as a week's story; every other reader of this table wants
    newest first and gets it from fetch_audit.
    """
    q = "SELECT * FROM fleet_audit WHERE at >= ?"
    params: list[Any] = [since]
    if actions:
        q += " AND action IN (%s)" % ", ".join("?" for _ in actions)
        params += list(actions)
    q += " ORDER BY id ASC LIMIT ?"
    params.append(max(1, min(int(limit), 1000)))
    return [_audit_row(r) for r in conn.execute(q, params)]


# ------------------------------------------------------------------- alerts
# SYS-8 (resilience sweep 2026-08-28). Every alarm this system raises has been
# PULL-ONLY: 0 of ~120 ledger entries were discovered by the system telling
# anybody. These three helpers are the durable half of alerts.py -- the dedup
# window and the weekly schedule both have to survive a container replacement,
# or a deploy at 07:59 on Monday sends the week's report twice and a flapping
# breaker sends forty mails.

ALERT_MAX_AGE_DAYS = 120

# What the LAST alert scan found, so the topbar can show a count without
# re-running forty checks on every page render. A meta row and not a table:
# it is one small current picture with no history worth keeping (the history
# is alert_log).
META_ALERTS_OPEN = "alerts_open_counts"

# How long one (kind, subject) stays quiet after it has been sent. A day, so a
# condition that is still true tomorrow says so again (an alert nobody acted
# on must not go silent for ever) and one that flaps hourly says it once.
ALERT_DEDUP_SECONDS = 24 * 3600


def record_alert(
    conn: sqlite3.Connection, kind: str, subject: str, sent_to: str,
    ok: bool, detail: str = "", now: str | None = None,
    batch_id: str = "",
) -> int:
    """Append one row and return its id. FAILURES ARE RECORDED TOO (ok=0):
    a sink that has been refusing since Tuesday is exactly what an admin needs
    on the page, and a send that left no trace is how a fleet ends up believing
    alerts are on.

    `batch_id` (v51, CR-190) is the message these rows shared. Empty means
    this row was its own message, which is what a per-event webhook send is.
    """
    cur = conn.execute(
        "INSERT INTO alert_log (at, kind, subject, sent_to, ok, detail, batch_id) "
        "VALUES (?, ?, ?, ?, ?, ?, ?)",
        (now or utcnow_iso(), str(kind or ""), str(subject or "")[:400],
         str(sent_to or "")[:400], 1 if ok else 0, str(detail or "")[:800],
         str(batch_id or "")[:64]),
    )
    return int(cur.lastrowid or 0)


def last_alert_at(
    conn: sqlite3.Connection, kind: str, subject: str | None = None,
    ok_only: bool = True,
) -> str | None:
    """When this (kind, subject) last went out, or None.

    `ok_only` because a send that FAILED has told nobody: suppressing the
    retry on the strength of it would be the dedup silencing the alert
    outright. `subject=None` asks about the kind as a whole, which is what the
    weekly schedule needs.
    """
    q = "SELECT at FROM alert_log WHERE kind=?"
    params: list[Any] = [str(kind or "")]
    if subject is not None:
        q += " AND subject=?"
        params.append(str(subject or ""))
    if ok_only:
        q += " AND ok=1"
    row = conn.execute(q + " ORDER BY id DESC LIMIT 1", params).fetchone()
    return None if row is None else row["at"]


def alert_recently_sent(
    conn: sqlite3.Connection, kind: str, subject: str, now: str,
    within_seconds: int = ALERT_DEDUP_SECONDS, ok_only: bool = True,
) -> bool:
    """Whether this (kind, subject) has already gone out inside the window.

    An unparseable stored timestamp reads as NOT recently sent: the failure
    direction of this predicate is "say it again", never "stay quiet".

    `ok_only=False` counts a FAILED attempt as "already said": alerts.send
    passes it so a site with a misconfigured sink does not re-attempt every
    open condition every cycle and fill this ledger with failures nobody can
    read through.
    """
    last = last_alert_at(conn, kind, subject, ok_only=ok_only)
    if not last:
        return False
    try:
        return parse_iso(last) >= parse_iso(_iso_minus(now, within_seconds))
    except (ValueError, TypeError):
        return False


def fetch_alerts(
    conn: sqlite3.Connection, limit: int = 50, since: str | None = None,
) -> list[dict[str, Any]]:
    """Newest first, for the Alerts settings page and the weekly report."""
    q = "SELECT * FROM alert_log"
    params: list[Any] = []
    if since:
        q += " WHERE at >= ?"
        params.append(since)
    q += " ORDER BY id DESC LIMIT ?"
    params.append(max(1, min(int(limit), 500)))
    return [dict(r) for r in conn.execute(q, params)]


def store_resolve_health(
    conn: sqlite3.Connection, editor: str, machine: str,
    guard: Mapping[str, Any] | None,
) -> None:
    """Write the v38 Resolve/stray/staging columns onto the machine's row.

    Its own UPDATE for the reason store_blocked_state gives: the big INSERT in
    upsert_machine_state is edited by every work package that touches the
    report, and this group has a rule of its own anyway.

    THE LATCH RULE, not COALESCE: these are written by any report that carried
    a guard section at all, because an ABSENT sub-section is how the companion
    spells "there is nothing outside the tree any more" -- and a COALESCE could
    never express that, so [ 12 CLIPS OUTSIDE THE TREE ] would stay on the grid
    for ever after the editor relinked them.

    `guard` None (a companion with no sync_guard at all) leaves every column
    alone: it has no opinion to record.
    """
    if guard is None or not guard.get("at"):
        return
    conn.execute(
        """UPDATE machine_state
              SET resolve_out_of_tree=?, resolve_bad_prefix=?, resolve_missing=?,
                  resolve_ignored=?, resolve_last_scan_at=?,
                  stray_projects_count=?, stray_projects_bytes=?,
                  moved_project_dirs_count=?, ingest_staging_bytes=?
            WHERE editor_username=? AND machine=?""",
        (guard.get("resolve_out_of_tree"), guard.get("resolve_bad_prefix"),
         guard.get("resolve_missing"), guard.get("resolve_ignored"),
         guard.get("resolve_last_scan_at"),
         guard.get("stray_projects_count"), guard.get("stray_projects_bytes"),
         guard.get("moved_project_dirs_count"), guard.get("ingest_staging_bytes"),
         editor, machine),
    )


def store_loopback_state(
    conn: sqlite3.Connection, editor: str, machine: str,
    guard: Mapping[str, Any] | None,
) -> None:
    """Write the v47 loopback columns onto the machine's row (CMEDIA-3,
    usability sweep 2026-09-04).

    Its own UPDATE for the reason store_resolve_health gives, and THE LATCH
    RULE for the same reason: these are written by any report that carried a
    guard section at all, so a machine that has taken 8899 back clears its
    chip. A COALESCE would leave [ SEND TO RESOLVE IS DEAD ] on the grid for
    ever after the editor closed the program that was holding the port.

    `guard` None (a companion with no sync_guard at all) leaves every column
    alone: it has no opinion to record, and neither has one too old to carry
    this section -- which is why an all-NULL row means "never said", not
    "bound".
    """
    if guard is None or not guard.get("at"):
        return
    conn.execute(
        """UPDATE machine_state
              SET loopback_enabled=?, loopback_bound=?, loopback_port=?,
                  loopback_error=?, loopback_since=?
            WHERE editor_username=? AND machine=?""",
        (guard.get("loopback_enabled"), guard.get("loopback_bound"),
         guard.get("loopback_port"), guard.get("loopback_error"),
         guard.get("loopback_since"), editor, machine),
    )


def recent_plan_changes(
    conn: sqlite3.Connection, now: str, window_seconds: int = PLAN_UNDO_WINDOW_SECONDS,
) -> list[dict[str, Any]]:
    """Tick/untick events inside the undo window, newest first, with the ones
    that have already been undone marked rather than hidden.

    Marked and not hidden because "somebody has already put that back" is
    itself the answer to the question the panel is being read for.
    """
    cutoff = _iso_minus(now, window_seconds)
    rows = [
        _audit_row(r) for r in conn.execute(
            "SELECT * FROM fleet_audit WHERE at >= ? AND action IN (?, ?) "
            "ORDER BY id DESC LIMIT 200",
            (cutoff, AUDIT_TICK, AUDIT_UNTICK),
        )
    ]
    undone = {
        int(_audit_row(r)["detail"].get("undid") or 0)
        for r in conn.execute(
            "SELECT * FROM fleet_audit WHERE at >= ? AND action = ?",
            (_iso_minus(now, window_seconds * 2), AUDIT_PLAN_UNDO),
        )
    }
    for row in rows:
        row["undone"] = row["id"] in undone
    return rows


def recent_plan_change_devices(
    conn: sqlite3.Connection, now: str, machine_devices: Mapping[tuple[str, str], str],
    window_seconds: int = PLAN_FREEZE_SECONDS,
) -> dict[str, frozenset[str]]:
    """{project_slug: {syncthing device id, ...}} for UNTICKS made in the last
    `window_seconds`: the (folder, device) pairs whose existing share the
    enforce cycle should leave exactly as it finds it this pass, so DASH-8's
    [ UNDO ] inside the window costs nothing.

    UNTICKS ONLY, and never `selections.changed_at`, both learned the same
    way (measured 2026-08-28): a row that is FRESH is not a row that should
    keep its share. An upload-only tick writes a fresh row for a machine
    whose share must be REMOVED (docs/UPLOAD_ONLY_TICK.md: no share at all,
    deliberately not a sendonly folder), and freezing on freshness held it --
    test_the_enforce_cycle_never_shares_a_folder_for_an_upload_only_tick.
    An untick is the one change whose undo needs the share to still be there;
    undoing a tick just removes what it added, which costs one cycle.
    """
    frozen: dict[str, set[str]] = {}
    cutoff = _iso_minus(now, window_seconds)
    for row in conn.execute(
        "SELECT subject, detail_json FROM fleet_audit WHERE at >= ? AND action = ?",
        (cutoff, AUDIT_UNTICK),
    ).fetchall():
        try:
            detail = json.loads(row["detail_json"] or "{}")
        except (ValueError, TypeError):
            continue
        slug = str(detail.get("slug") or row["subject"] or "")
        editor = str(detail.get("editor") or "")
        if not slug or not editor:
            continue
        machines = {str(p.get("machine") or "")
                    for side in ("before", "after")
                    for p in (detail.get(side) or [])}
        machines.add(str(detail.get("machine") or ""))
        for machine in machines:
            device_id = machine_devices.get((editor, machine))
            if device_id:
                frozen.setdefault(slug, set()).add(device_id)
    return {slug: frozenset(ids) for slug, ids in frozen.items()}


def selections_for_machine(
    conn: sqlite3.Connection, editor: str, machine: str
) -> list[dict[str, Any]]:
    """What THIS computer syncs: its own rows, plus the unassigned bucket if
    it has none of its own.

    The one inheritance rule in the model, and it is a migration/compat
    affordance rather than a feature: rows with machine='' come from an
    editor who ticked before their companion ever reported, a companion too
    old to say which machine is asking, or the collector's one-shot seed from
    pre-existing shares. A machine that has been given a plan of its own is
    never also handed the bucket -- that would make "untick this project on
    the laptop" impossible to express.

    A WIRED machine syncs nothing at all (CR-28, re-applied to the read side
    by bug-hunt-2026-09-03 dash-db-1). The tick and copy-plan routes already
    409 on one, so an own row here is legacy or hand-written; the bucket was
    the live route in. Under-sharing is the safe direction, so both are
    dropped rather than filtered."""
    if (editor, machine) in base_machines(conn):
        return []
    rows = _selection_rows(conn, editor, machine=machine)
    if rows:
        return rows
    return _selection_rows(conn, editor, machine=ANY_MACHINE)


def _selection_rows(
    conn: sqlite3.Connection, editor: str, machine: str | None
) -> list[dict[str, Any]]:
    q = """SELECT s.project_slug AS slug, s.machine, s.position, s.created_at,
                  s.created_by, s.sync_mode, p.label, p.active
             FROM selections s LEFT JOIN projects p ON p.slug = s.project_slug
            WHERE s.editor_username = ?"""
    params: list[Any] = [editor]
    if machine is not None:
        q += " AND s.machine = ?"
        params.append(machine)
    q += " ORDER BY s.position, s.machine"
    return [dict(r) for r in conn.execute(q, params)]


def fetch_selections(
    conn: sqlite3.Connection, editor: str, machine: str | None = None
) -> list[dict[str, Any]]:
    """Ticked projects in queue order, joined to project label/path.
    Selections whose project no longer exists or is inactive are kept in the
    row (slug only) but flagged, so the UI can surface them.

    `machine=None` is the UNION across this editor's computers -- what a
    companion too old to name itself gets, and what the person-level views
    show. Deliberately the union and not the intersection: an old build that
    over-syncs fills a drive, an old build that under-syncs is an editor who
    quietly cannot open a project (MULTI_MACHINE_PLAN.md §5)."""
    if machine is not None:
        return selections_for_machine(conn, editor, machine)
    rows = _selection_rows(conn, editor, machine=None)
    seen: set[str] = set()
    unique: list[dict[str, Any]] = []
    for row in rows:
        if row["slug"] in seen:
            continue
        seen.add(row["slug"])
        unique.append(row)
    return unique


def _sync_mode_clause(sync_modes: tuple[str, ...] | None) -> tuple[str, list[Any]]:
    """`AND sync_mode IN (...)` for the selection readers that take a mode
    filter; nothing when the caller wants every tick whatever it carries."""
    if not sync_modes:
        return "", []
    marks = ", ".join("?" for _ in sync_modes)
    return f" AND sync_mode IN ({marks})", list(sync_modes)


def fetch_all_selections(
    conn: sqlite3.Connection, sync_modes: tuple[str, ...] | None = None,
) -> dict[str, list[str]]:
    """slug -> [editor_username...] over all selections (deduped per editor).

    The person-level view the assignments grid and the project pages draw:
    "somebody's computer holds this". fetch_machine_selections is the
    per-computer answer. `sync_modes` narrows it to ticks in those modes --
    the enforce cycle asks for `full` only, because an upload-only tick is
    never a Syncthing share."""
    clause, params = _sync_mode_clause(sync_modes)
    grouped: dict[str, list[str]] = {}
    for row in conn.execute(
        "SELECT DISTINCT project_slug, editor_username FROM selections "
        f"WHERE 1=1{clause} ORDER BY editor_username", params,
    ):
        grouped.setdefault(row["project_slug"], []).append(row["editor_username"])
    return grouped


def fetch_all_selection_modes(conn: sqlite3.Connection) -> dict[str, dict[str, str]]:
    """slug -> {editor_username -> mode}, where mode is `full`, `upload_only`
    or `mixed` (one person, two computers, two answers). The project page and
    the sidebar mark upload-only ticks with it; the plan itself stays per
    computer."""
    seen: dict[str, dict[str, set[str]]] = {}
    for row in conn.execute(
        "SELECT project_slug, editor_username, sync_mode FROM selections"
    ):
        seen.setdefault(row["project_slug"], {}).setdefault(
            row["editor_username"], set()).add(row["sync_mode"] or SYNC_MODE_FULL)
    out: dict[str, dict[str, str]] = {}
    for slug, by_editor in seen.items():
        out[slug] = {
            editor: (next(iter(modes)) if len(modes) == 1 else "mixed")
            for editor, modes in by_editor.items()
        }
    return out


def fetch_machine_selections(
    conn: sqlite3.Connection, sync_modes: tuple[str, ...] | None = None,
) -> dict[str, list[tuple[str, str]]]:
    """slug -> [(editor_username, machine)...], the unassigned bucket
    resolved against each editor's machines. This is what the enforce cycle
    and the queue builders need: a share is made with a computer.

    `sync_modes` keeps only ticks in those modes. The bucket rule ("a machine
    with rows of its own is never handed the bucket") is decided on ALL of a
    machine's rows before the filter applies -- otherwise a laptop holding
    one upload-only tick would inherit every full tick in the bucket the
    moment a caller asked for full ticks only.

    A WIRED machine never inherits the bucket (bug-hunt-2026-09-03 dash-db-1):
    CR-28 was enforced on every write path only, so a `machine=''` row was
    fanned out to a base rig here and the enforce cycle -- which reads exactly
    this map and applies no mode filter of its own -- offered a Syncthing
    share to the computer whose tree root IS the NAS share."""
    wanted = set(sync_modes) if sync_modes else None
    wired = base_machines(conn)
    by_editor_machines: dict[str, list[str]] = {}
    for row in conn.execute("SELECT editor_username, machine FROM machines"):
        by_editor_machines.setdefault(row["editor_username"], []).append(row["machine"])
    own: dict[tuple[str, str], set[str]] = {}
    bucket: dict[str, set[str]] = {}
    has_own: set[tuple[str, str]] = set()
    for row in conn.execute(
        "SELECT editor_username, machine, project_slug, sync_mode FROM selections"
    ):
        if row["machine"] != ANY_MACHINE:
            has_own.add((row["editor_username"], row["machine"]))
        if wanted is not None and (row["sync_mode"] or SYNC_MODE_FULL) not in wanted:
            continue
        if row["machine"] == ANY_MACHINE:
            bucket.setdefault(row["editor_username"], set()).add(row["project_slug"])
        else:
            own.setdefault(
                (row["editor_username"], row["machine"]), set()
            ).add(row["project_slug"])
    grouped: dict[str, list[tuple[str, str]]] = {}
    for (editor, machine), slugs in own.items():
        for slug in slugs:
            grouped.setdefault(slug, []).append((editor, machine))
    for editor, slugs in bucket.items():
        machines = by_editor_machines.get(editor)
        if not machines:
            # No computer on record yet -- an editor who ticked before their
            # companion ever reported. The pair is kept with an EMPTY machine
            # rather than dropped: callers match it on the person, which is
            # all anyone can know here, and dropping it would read as "this
            # project is ticked for nobody" (the B16 direction).
            for slug in slugs:
                grouped.setdefault(slug, []).append((editor, ANY_MACHINE))
            continue
        for machine in machines:
            if (editor, machine) in has_own:
                continue          # has a plan of its own; the bucket does not apply
            if (editor, machine) in wired:
                continue          # dash-db-1: a base rig holds no tick, by any route
            for slug in slugs:
                grouped.setdefault(slug, []).append((editor, machine))
    for slug in grouped:
        grouped[slug] = sorted(set(grouped[slug]))
    return grouped


def set_project_root_override(
    conn: sqlite3.Connection, editor: str, slug: str | None, updated_by: str, now: str,
    machine: str = ANY_MACHINE,
) -> None:
    conn.execute(
        """INSERT INTO editor_prefs
             (editor_username, machine, project_root_override, updated_at, updated_by)
           VALUES (?, ?, ?, ?, ?)
           ON CONFLICT(editor_username, machine) DO UPDATE SET
             project_root_override=excluded.project_root_override,
             updated_at=excluded.updated_at, updated_by=excluded.updated_by""",
        (editor, machine, slug, now, updated_by),
    )


def get_project_root_override(
    conn: sqlite3.Connection, editor: str, machine: str | None = None
) -> str | None:
    """This machine's sticky destination root, falling back to the editor's
    unassigned one (v24/WP7: where a project lands is a property of the
    machine's Resolve setup, not of the person)."""
    if machine is not None:
        row = conn.execute(
            """SELECT project_root_override FROM editor_prefs
                WHERE editor_username=? AND machine=?""",
            (editor, machine),
        ).fetchone()
        if row is not None and row["project_root_override"]:
            return row["project_root_override"]
    row = conn.execute(
        """SELECT project_root_override FROM editor_prefs
            WHERE editor_username=? AND machine=? """,
        (editor, ANY_MACHINE),
    ).fetchone()
    if row is not None:
        return row["project_root_override"]
    if machine is None:
        # No bucket row: any machine's answer is better than none for the
        # person-level callers (the admin view).
        row = conn.execute(
            "SELECT project_root_override FROM editor_prefs WHERE editor_username=?",
            (editor,),
        ).fetchone()
        return row["project_root_override"] if row else None
    return None


def upsert_machine_state(
    conn: sqlite3.Connection, editor: str, machine: str,
    detected_project_root: str | None, now: str,
    resolve_project: str | None = None, verified: bool = False,
    platform: str | None = None, companion_version: str | None = None,
    mode: str | None = None,
    transport: Mapping[str, Any] | None = None,
    guard: Mapping[str, Any] | None = None,
    ingest: Mapping[str, Any] | None = None,
    proxy: Mapping[str, Any] | None = None,
    music: Mapping[str, Any] | None = None,
    client_reported_at: str | None = None,
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
    clear the alarm.

    `ingest` is flatten_broll_ingest()'s dict and `proxy` the proxy_coverage
    scalars (v20, BROLL_INGEST_PLAN.md §3.2). Same None-leaves-it-alone rule
    for every column EXCEPT `ingest_active`, which is written on every single
    report including the ones carrying no ingest section at all: the
    companion's reporter omits an empty section, so "the batch finished" is
    spelled by the section's ABSENCE and a COALESCEd flag would leave the
    machine indexing on the grid forever.

    `now` is the SERVER's clock and lands in both `reported_at` (which has
    always held it, whatever its name says) and the v30 `received_at`, which
    is what prune() and evict_extra_machines() order on. `client_reported_at`
    is the companion's own wall clock, clamped by clamp_reported_at, with the
    difference kept in `clock_skew_seconds` (SYS-4, resilience sweep
    2026-08-28)."""
    stored_client_at, skew, _clamped = clamp_reported_at(client_reported_at, now)
    t = dict(transport or {})
    g = dict(guard or {})
    i = dict(ingest or {})
    p = dict(proxy or {})
    # flatten_music_ingest()'s dict (v21). Same None-leaves-it-alone rule as
    # `ingest`, and the same exception for its `active` flag.
    m = dict(music or {})
    # REL-1 (resilience sweep 2026-08-28): when THIS build first appeared on
    # this machine, by the SERVER's clock. It has to be stamped before the
    # upsert overwrites `companion_version`, which is the only way to tell a
    # version change from another report of the same one -- and it is the
    # soak gate's whole input, so a machine's own clock (which SYS-4 proved
    # can be days out) must never be able to shorten a soak.
    if companion_version:
        conn.execute(
            """UPDATE machine_state SET companion_version_since=?
                WHERE editor_username=? AND machine=?
                  AND (companion_version_since IS NULL
                       OR companion_version IS NOT ?)""",
            (now, editor, machine, companion_version),
        )
    conn.execute(
        """INSERT INTO machine_state
             (editor_username, machine, detected_project_root, reported_at,
              resolve_project, verified, platform, companion_version,
              transport_relayed, transport_direct, orphan_partials,
              orphan_partial_bytes, express_dropped, express_last_error,
              transport_at,
              breaker_tripped, breaker_reason, breaker_at, trash_bytes,
              trash_count, halt_active, halt_scope, halt_reason,
              skipped_exists, guard_at,
              ingest_active, ingest_batch, ingest_state, ingest_gate,
              ingest_done, ingest_total, ingest_failed, ingest_clip,
              ingest_percent, ingest_tier, ingest_warning, ingest_at,
              proxy_missing, proxy_state, proxy_left,
              music_ingest_active, music_ingest_batch, music_ingest_state,
              music_ingest_gate, music_ingest_done, music_ingest_total,
              music_ingest_failed, music_ingest_track, music_ingest_percent,
              music_ingest_warning, music_ingest_at,
              mode,
              received_at, client_reported_at, clock_skew_seconds,
              supervisor_down_since, supervisor_attempts, supervisor_last_error,
              supervisor_supervising, crash_count, crash_newest,
              folders_unfiltered, folders_unfiltered_names, sync_conflicts,
              disk_root_free_bytes, disk_root_total_bytes,
              disk_system_free_bytes, disk_at, rotation_seconds,
              stalled_lane, stalled_seconds, stalled_killed, stalled_at)
           VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?,
                   ?, ?, ?, ?, ?, ?, ?, ?, ?, ?,
                   ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?,
                   ?, ?, ?,
                   ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?,
                   ?,
                   ?, ?, ?,
                   ?, ?, ?,
                   ?, ?, ?,
                   ?, ?, ?,
                   ?, ?, ?, ?, ?,
                   ?, ?, ?, ?)
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
             guard_at=COALESCE(excluded.guard_at, machine_state.guard_at),
             -- Written on EVERY report (see the docstring): silence means
             -- "not indexing", never "keep the last answer".
             ingest_active=excluded.ingest_active,
             ingest_batch=CASE WHEN excluded.ingest_at IS NULL
                               THEN machine_state.ingest_batch
                               ELSE excluded.ingest_batch END,
             ingest_state=CASE WHEN excluded.ingest_at IS NULL
                               THEN machine_state.ingest_state
                               ELSE excluded.ingest_state END,
             ingest_gate=CASE WHEN excluded.ingest_at IS NULL
                              THEN machine_state.ingest_gate
                              ELSE excluded.ingest_gate END,
             ingest_done=CASE WHEN excluded.ingest_at IS NULL
                              THEN machine_state.ingest_done
                              ELSE excluded.ingest_done END,
             ingest_total=CASE WHEN excluded.ingest_at IS NULL
                               THEN machine_state.ingest_total
                               ELSE excluded.ingest_total END,
             ingest_failed=CASE WHEN excluded.ingest_at IS NULL
                                THEN machine_state.ingest_failed
                                ELSE excluded.ingest_failed END,
             ingest_clip=CASE WHEN excluded.ingest_at IS NULL
                              THEN machine_state.ingest_clip
                              ELSE excluded.ingest_clip END,
             ingest_percent=CASE WHEN excluded.ingest_at IS NULL
                                 THEN machine_state.ingest_percent
                                 ELSE excluded.ingest_percent END,
             ingest_tier=CASE WHEN excluded.ingest_at IS NULL
                              THEN machine_state.ingest_tier
                              ELSE excluded.ingest_tier END,
             -- Cleared by a section that carries no warning: a refusal the
             -- editor has since fixed (chose the smaller tier) must not keep
             -- an amber chip on the grid forever.
             ingest_warning=CASE WHEN excluded.ingest_at IS NULL
                                 THEN machine_state.ingest_warning
                                 ELSE excluded.ingest_warning END,
             ingest_at=COALESCE(excluded.ingest_at, machine_state.ingest_at),
             proxy_missing=COALESCE(excluded.proxy_missing,
                                    machine_state.proxy_missing),
             proxy_state=COALESCE(excluded.proxy_state, machine_state.proxy_state),
             proxy_left=COALESCE(excluded.proxy_left, machine_state.proxy_left),
             -- v21, and every CASE below is v20's rule for the same reason:
             -- the flag is written on every report so a finished batch can
             -- clear it, and everything else is held unless this report
             -- carried a music section at all (music_ingest_at is the marker).
             music_ingest_active=excluded.music_ingest_active,
             music_ingest_batch=CASE WHEN excluded.music_ingest_at IS NULL
                                     THEN machine_state.music_ingest_batch
                                     ELSE excluded.music_ingest_batch END,
             music_ingest_state=CASE WHEN excluded.music_ingest_at IS NULL
                                     THEN machine_state.music_ingest_state
                                     ELSE excluded.music_ingest_state END,
             music_ingest_gate=CASE WHEN excluded.music_ingest_at IS NULL
                                    THEN machine_state.music_ingest_gate
                                    ELSE excluded.music_ingest_gate END,
             music_ingest_done=CASE WHEN excluded.music_ingest_at IS NULL
                                    THEN machine_state.music_ingest_done
                                    ELSE excluded.music_ingest_done END,
             music_ingest_total=CASE WHEN excluded.music_ingest_at IS NULL
                                     THEN machine_state.music_ingest_total
                                     ELSE excluded.music_ingest_total END,
             music_ingest_failed=CASE WHEN excluded.music_ingest_at IS NULL
                                      THEN machine_state.music_ingest_failed
                                      ELSE excluded.music_ingest_failed END,
             music_ingest_track=CASE WHEN excluded.music_ingest_at IS NULL
                                     THEN machine_state.music_ingest_track
                                     ELSE excluded.music_ingest_track END,
             music_ingest_percent=CASE WHEN excluded.music_ingest_at IS NULL
                                       THEN machine_state.music_ingest_percent
                                       ELSE excluded.music_ingest_percent END,
             music_ingest_warning=CASE WHEN excluded.music_ingest_at IS NULL
                                       THEN machine_state.music_ingest_warning
                                       ELSE excluded.music_ingest_warning END,
             music_ingest_at=COALESCE(excluded.music_ingest_at,
                                      machine_state.music_ingest_at),
             -- COALESCEd, not written blind: `mode` rides every report from a
             -- companion that has one, and a report from a build too old to
             -- send it must not silently re-label the base rig an editor
             -- machine -- which would put it back in [ QUEUED ] (CR-28).
             -- This only holds because api.py passes None (not "editor")
             -- when the report omitted it -- the default used to be applied
             -- there first, which made this a no-op (ultrareview 2026-08-19).
             mode=COALESCE(excluded.mode, machine_state.mode),
             -- v30. received_at is OURS, so it is written blind on every
             -- report; the two client-clock columns are written blind too,
             -- because "this report carried no timestamp we could read" has
             -- to be able to replace yesterday's answer (SYS-4).
             received_at=excluded.received_at,
             client_reported_at=excluded.client_reported_at,
             clock_skew_seconds=excluded.clock_skew_seconds,
             -- The supervisor section is EMPTY-WHEN-HEALTHY by the
             -- companion's own design (an absent section is how "the sync
             -- engine is up" is spelled), so these follow the LATCH rule and
             -- not the COALESCE rule: they are cleared by any report that
             -- carried a guard section without them. A COALESCE here would
             -- leave "sync engine down since Tuesday" on the grid for ever
             -- after the engine came back (SYNC-8).
             supervisor_down_since=CASE WHEN excluded.guard_at IS NULL
                                        THEN machine_state.supervisor_down_since
                                        ELSE excluded.supervisor_down_since END,
             supervisor_attempts=CASE WHEN excluded.guard_at IS NULL
                                      THEN machine_state.supervisor_attempts
                                      ELSE excluded.supervisor_attempts END,
             supervisor_last_error=CASE WHEN excluded.guard_at IS NULL
                                        THEN machine_state.supervisor_last_error
                                        ELSE excluded.supervisor_last_error END,
             supervisor_supervising=CASE WHEN excluded.guard_at IS NULL
                                         THEN machine_state.supervisor_supervising
                                         ELSE excluded.supervisor_supervising END,
             -- Same rule, same reason: a conflict the editor has since
             -- resolved, or a folder whose filter has since been written,
             -- must be able to take its own chip off the grid.
             folders_unfiltered=CASE WHEN excluded.guard_at IS NULL
                                     THEN machine_state.folders_unfiltered
                                     ELSE excluded.folders_unfiltered END,
             folders_unfiltered_names=CASE WHEN excluded.guard_at IS NULL
                                           THEN machine_state.folders_unfiltered_names
                                           ELSE excluded.folders_unfiltered_names END,
             sync_conflicts=CASE WHEN excluded.guard_at IS NULL
                                 THEN machine_state.sync_conflicts
                                 ELSE excluded.sync_conflicts END,
             -- Crashes are a HIGH-WATER count on the machine's own disk, not
             -- a current state: it only goes down when somebody empties
             -- ~/.ccsync/crashes, and the companion is the one counting. So
             -- this one is written from any guard-bearing report too, which
             -- is what lets an emptied directory clear the chip.
             crash_count=CASE WHEN excluded.guard_at IS NULL
                              THEN machine_state.crash_count
                              ELSE excluded.crash_count END,
             crash_newest=CASE WHEN excluded.guard_at IS NULL
                               THEN machine_state.crash_newest
                               ELSE excluded.crash_newest END,
             -- v32 (SYS-5 / SYS-1). The disk figures are a MEASUREMENT taken
             -- once per heavy tick, not an alarm that has to be able to
             -- clear, so they follow the COALESCE rule with disk_at as their
             -- own marker: a light report in between must not blank the last
             -- known free space and take the DISK chip off a nearly-full
             -- machine. Same for rotation_seconds, which is a config value.
             disk_root_free_bytes=CASE WHEN excluded.disk_at IS NULL
                                       THEN machine_state.disk_root_free_bytes
                                       ELSE excluded.disk_root_free_bytes END,
             disk_root_total_bytes=CASE WHEN excluded.disk_at IS NULL
                                        THEN machine_state.disk_root_total_bytes
                                        ELSE excluded.disk_root_total_bytes END,
             disk_system_free_bytes=CASE WHEN excluded.disk_at IS NULL
                                         THEN machine_state.disk_system_free_bytes
                                         ELSE excluded.disk_system_free_bytes END,
             disk_at=COALESCE(excluded.disk_at, machine_state.disk_at),
             rotation_seconds=COALESCE(excluded.rotation_seconds,
                                       machine_state.rotation_seconds),
             -- ...and the companion's own kill record follows the LATCH rule
             -- instead: a stall it killed and has since recovered from must
             -- be able to take its chip off the grid (SYNC-1/SYS-17).
             stalled_lane=CASE WHEN excluded.guard_at IS NULL
                               THEN machine_state.stalled_lane
                               ELSE excluded.stalled_lane END,
             stalled_seconds=CASE WHEN excluded.guard_at IS NULL
                                  THEN machine_state.stalled_seconds
                                  ELSE excluded.stalled_seconds END,
             stalled_killed=CASE WHEN excluded.guard_at IS NULL
                                 THEN machine_state.stalled_killed
                                 ELSE excluded.stalled_killed END,
             stalled_at=CASE WHEN excluded.guard_at IS NULL
                             THEN machine_state.stalled_at
                             ELSE excluded.stalled_at END""",
        (editor, machine, detected_project_root, now, resolve_project, int(verified),
         platform, companion_version,
         t.get("relayed"), t.get("direct"), t.get("orphan_partials"),
         t.get("orphan_partial_bytes"), t.get("express_dropped"),
         t.get("express_last_error"), t.get("at"),
         g.get("breaker_tripped"), g.get("breaker_reason"), g.get("breaker_at"),
         g.get("trash_bytes"), g.get("trash_count"), g.get("halt_active"),
         g.get("halt_scope"), g.get("halt_reason"), g.get("skipped_exists"),
         g.get("at"),
         int(bool(i.get("active"))), i.get("batch"), i.get("state"), i.get("gate"),
         i.get("done"), i.get("total"), i.get("failed"), i.get("clip"),
         i.get("percent"), i.get("tier"), i.get("warning"), i.get("at"),
         p.get("missing"), p.get("state"), p.get("left"),
         int(bool(m.get("active"))), m.get("batch"), m.get("state"),
         m.get("gate"), m.get("done"), m.get("total"), m.get("failed"),
         m.get("track"), m.get("percent"), m.get("warning"), m.get("at"),
         mode,
         now, stored_client_at, skew,
         g.get("supervisor_down_since"), g.get("supervisor_attempts"),
         g.get("supervisor_last_error"), g.get("supervisor_supervising"),
         g.get("crash_count"), g.get("crash_newest"),
         g.get("folders_unfiltered"), g.get("folders_unfiltered_names"),
         g.get("sync_conflicts"),
         g.get("disk_root_free_bytes"), g.get("disk_root_total_bytes"),
         g.get("disk_system_free_bytes"), g.get("disk_at"),
         g.get("rotation_seconds"),
         g.get("stalled_lane"), g.get("stalled_seconds"),
         g.get("stalled_killed"), g.get("stalled_at")),
    )
    # A machine reporting for the FIRST time has no row for the stamp above to
    # update, so its soak clock starts here instead (REL-1). Both halves are
    # "when this server first saw this version on this machine".
    if companion_version:
        conn.execute(
            """UPDATE machine_state SET companion_version_since=?
                WHERE editor_username=? AND machine=?
                  AND companion_version_since IS NULL""",
            (now, editor, machine),
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
            # v30 (SYNC-8 / APP-6 / APP-13 / SYNC-x, resilience sweep
            # 2026-08-28). Every one of these was already on the wire and
            # dropped at the model boundary. `supervising` and the skew are
            # TRI-STATE on purpose: None means this companion never told us,
            # which the grid must not render as "fine".
            "supervisor_down_since": r["supervisor_down_since"],
            "supervisor_attempts": r["supervisor_attempts"],
            "supervisor_last_error": r["supervisor_last_error"],
            "supervisor_supervising": (
                None if r["supervisor_supervising"] is None
                else bool(r["supervisor_supervising"])
            ),
            "crash_count": r["crash_count"],
            "crash_newest": r["crash_newest"],
            "folders_unfiltered": r["folders_unfiltered"],
            "folders_unfiltered_names": r["folders_unfiltered_names"],
            "sync_conflicts": r["sync_conflicts"],
            "clock_skew_seconds": r["clock_skew_seconds"],
            # v32 (SYS-5 / SYS-1). free/total are what the DISK chip reads;
            # `rotation_seconds` is what turns health.lane_stall's budget from
            # a guess into this machine's own 3 rotations.
            "disk_root_free_bytes": r["disk_root_free_bytes"],
            "disk_root_total_bytes": r["disk_root_total_bytes"],
            "disk_system_free_bytes": r["disk_system_free_bytes"],
            "disk_at": r["disk_at"],
            "rotation_seconds": r["rotation_seconds"],
            "stalled_lane": r["stalled_lane"],
            "stalled_seconds": r["stalled_seconds"],
            "stalled_killed": (
                None if r["stalled_killed"] is None else bool(r["stalled_killed"])
            ),
            "stalled_at": r["stalled_at"],
            # v33 (SYS-7 / SYNC-15). The companion's own ranked answer to
            # "why is nothing moving", which health.why_not_syncing prefers
            # over anything this server can derive, and the LaneWatchdog's
            # restart record (SYS-2) beside it: a machine that self-heals
            # three times an hour is a machine that needs a person.
            "blocked_reason": r["blocked_reason"],
            "blocked_detail": r["blocked_detail"],
            "blocked_since": r["blocked_since"],
            "restarts_count_24h": r["restarts_count_24h"],
            "restarts_last_at": r["restarts_last_at"],
            "restarts_last_error": r["restarts_last_error"],
            # v35 (REL-8 / REL-16, resilience sweep 2026-08-28). The report
            # payload carried nothing at all about upgrade outcomes, so a
            # machine that has failed the same build 140 times was
            # indistinguishable from one that had not seen the push yet.
            "arch": r["arch"],
            "upgrade_version": r["upgrade_version"],
            "upgrade_attempts": r["upgrade_attempts"],
            "upgrade_last_error": r["upgrade_last_error"],
            "upgrade_last_attempt_at": r["upgrade_last_attempt_at"],
            "upgrade_reverted_from": r["upgrade_reverted_from"],
            # v38 (wave 4's ingest contract, resilience sweep 2026-08-28).
            # Clips the open Resolve project references from OUTSIDE the tree
            # are footage lane A will never upload and nobody else on the
            # fleet will ever see; the stray/moved/staging counters are the
            # same class of quiet loss one level up, at the directory.
            "resolve_out_of_tree": r["resolve_out_of_tree"],
            "resolve_bad_prefix": r["resolve_bad_prefix"],
            "resolve_missing": r["resolve_missing"],
            "resolve_ignored": r["resolve_ignored"],
            "resolve_last_scan_at": r["resolve_last_scan_at"],
            "stray_projects_count": r["stray_projects_count"],
            "stray_projects_bytes": r["stray_projects_bytes"],
            "moved_project_dirs_count": r["moved_project_dirs_count"],
            "ingest_staging_bytes": r["ingest_staging_bytes"],
            # v47 (CMEDIA-3, usability sweep 2026-09-04). All NULL is "a
            # companion too old to say", which the reader must not render as
            # bound: the b-roll and music pages' one dependency on this
            # machine either works or it does not, and until now it failed
            # only in the editor's browser.
            "loopback_enabled": r["loopback_enabled"],
            "loopback_bound": r["loopback_bound"],
            "loopback_port": r["loopback_port"],
            "loopback_error": r["loopback_error"],
            "loopback_since": r["loopback_since"],
        }
        for r in conn.execute(
            """SELECT editor_username, machine, breaker_tripped, breaker_reason,
                      breaker_at, trash_bytes, trash_count, halt_active, halt_scope,
                      halt_reason, skipped_exists, guard_at,
                      supervisor_down_since, supervisor_attempts,
                      supervisor_last_error, supervisor_supervising,
                      crash_count, crash_newest, folders_unfiltered,
                      folders_unfiltered_names, sync_conflicts,
                      clock_skew_seconds,
                      disk_root_free_bytes, disk_root_total_bytes,
                      disk_system_free_bytes, disk_at, rotation_seconds,
                      stalled_lane, stalled_seconds, stalled_killed, stalled_at,
                      blocked_reason, blocked_detail, blocked_since,
                      restarts_count_24h, restarts_last_at, restarts_last_error,
                      arch, upgrade_version, upgrade_attempts, upgrade_last_error,
                      upgrade_last_attempt_at, upgrade_reverted_from,
                      resolve_out_of_tree, resolve_bad_prefix, resolve_missing,
                      resolve_ignored, resolve_last_scan_at,
                      stray_projects_count, stray_projects_bytes,
                      moved_project_dirs_count, ingest_staging_bytes,
                      loopback_enabled, loopback_bound, loopback_port,
                      loopback_error, loopback_since
               FROM machine_state"""
        )
    }


def machine_breaker_tripped(
    conn: sqlite3.Connection, editor: str, machine: str
) -> bool | None:
    """Did this machine's LAST report say its lane B breaker was tripped?

    None when there is no guard section on record at all (never reported, or
    a companion too old to send one), which is not the same answer as False
    and the caller must not treat it as one (comp-lanes-ab-2, 2026-08-21)."""
    row = conn.execute(
        "SELECT breaker_tripped, guard_at FROM machine_state "
        "WHERE editor_username=? AND machine=?",
        (editor, machine),
    ).fetchone()
    if row is None or not row["guard_at"]:
        return None
    return bool(row["breaker_tripped"])


def fetch_broll_ingest_map(conn: sqlite3.Connection) -> dict[tuple[str, str], dict[str, Any]]:
    """(editor, machine) -> the b-roll ingest state for the fleet grid (v20).

    "Admins see which computers are indexing and their progress"
    (BROLL_INGEST_PLAN.md §0) is one query: machine_state is already the one
    row per machine the grid reads, and a batch that is crunching on somebody
    else's laptop has no other trace on this server until its items land."""
    return {
        (r["editor_username"], r["machine"]): {
            "active": bool(r["ingest_active"]),
            "batch": r["ingest_batch"],
            "state": r["ingest_state"],
            "gate": r["ingest_gate"],
            "done": r["ingest_done"] or 0,
            "total": r["ingest_total"] or 0,
            "failed": r["ingest_failed"] or 0,
            "clip": r["ingest_clip"],
            "percent": r["ingest_percent"],
            "tier": r["ingest_tier"],
            "warning": r["ingest_warning"] or "",
            "at": r["ingest_at"],
        }
        for r in conn.execute(
            """SELECT editor_username, machine, ingest_active, ingest_batch,
                      ingest_state, ingest_gate, ingest_done, ingest_total,
                      ingest_failed, ingest_clip, ingest_percent, ingest_tier,
                      ingest_warning, ingest_at
               FROM machine_state"""
        )
    }


def fetch_music_ingest_map(conn: sqlite3.Connection) -> dict[tuple[str, str], dict[str, Any]]:
    """(editor, machine) -> the music ingest state for the fleet grid (v21).

    fetch_broll_ingest_map's twin, over its own columns, so the grid can show
    both chips at once -- which is the state a machine embedding an album while
    it indexes a card is actually in.
    """
    return {
        (r["editor_username"], r["machine"]): {
            "active": bool(r["music_ingest_active"]),
            "batch": r["music_ingest_batch"],
            "state": r["music_ingest_state"],
            "gate": r["music_ingest_gate"],
            "done": r["music_ingest_done"] or 0,
            "total": r["music_ingest_total"] or 0,
            "failed": r["music_ingest_failed"] or 0,
            "track": r["music_ingest_track"],
            "percent": r["music_ingest_percent"],
            "warning": r["music_ingest_warning"] or "",
            "at": r["music_ingest_at"],
        }
        for r in conn.execute(
            """SELECT editor_username, machine, music_ingest_active,
                      music_ingest_batch, music_ingest_state, music_ingest_gate,
                      music_ingest_done, music_ingest_total, music_ingest_failed,
                      music_ingest_track, music_ingest_percent,
                      music_ingest_warning, music_ingest_at
               FROM machine_state"""
        )
    }


def fetch_proxy_coverage_map(conn: sqlite3.Connection) -> dict[tuple[str, str], dict[str, Any]]:
    """(editor, machine) -> the missing-proxy scalars (v20).

    The companion has sent `proxy_coverage` on every heavy tick since the
    generator shipped and ReportIn dropped it undeclared, so "how much of
    this machine's footage still has no proxy" -- the number that decides
    whether anyone else can see that footage -- reached nobody."""
    return {
        (r["editor_username"], r["machine"]): {
            "missing": r["proxy_missing"] or 0,
            "state": r["proxy_state"],
            "left": r["proxy_left"] or 0,
        }
        for r in conn.execute(
            "SELECT editor_username, machine, proxy_missing, proxy_state, proxy_left "
            "FROM machine_state"
        )
    }


# The fleet halt lives in `meta`, not in a table of its own: it is exactly one
# row of state for the whole dashboard, and `meta` is where the collector
# already keeps that class of thing. JSON in the value so the reason and who
# set it travel with the flag (COMMERCIAL_READINESS.md item 9, 2026-08-17).
FLEET_HALT_KEY = "fleet_halt"

# UX-8 (resilience sweep 2026-08-28). The halt had no expiry, so "I will look
# at this on Monday" was a company that could not work all weekend and a
# switch nobody was reminded of. It expires by itself now; [ KEEP HALTED ]
# extends it by another window, which is a decision somebody makes rather than
# a state that persists because nobody remembered.
FLEET_HALT_DEFAULT_HOURS = 24
# Last 20 halts, in `meta`: "who stopped the fleet last month and why" is a
# question an owner asks, and one JSON value answers it without a table.
FLEET_HALT_HISTORY_KEY = "fleet_halt_history"
FLEET_HALT_HISTORY_KEEP = 20


def _halt_state(data: Any, now: str) -> dict[str, Any]:
    """Normalise a stored halt blob, applying the expiry.

    An expired halt reads as NOT active with `expired` set, which is what
    makes the report reply release it: the reply always carries
    `commands.halt.active`, and a companion treats false as "start again"."""
    if not isinstance(data, dict):
        data = {}
    expires_at = str(data.get("expires_at") or "")
    active = bool(data.get("active"))
    expired = False
    if active and expires_at:
        try:
            expired = parse_iso(now) >= parse_iso(expires_at)
        except (TypeError, ValueError):
            # An unparseable expiry is not evidence that the halt is over.
            expired = False
    return {
        "active": active and not expired,
        "expired": expired,
        "reason": str(data.get("reason") or ""),
        "set_by": str(data.get("set_by") or ""),
        "set_at": str(data.get("set_at") or ""),
        "expires_at": expires_at,
        "extended": int(data.get("extended") or 0),
    }


def get_fleet_halt(conn: sqlite3.Connection, now: str | None = None) -> dict[str, Any]:
    """{"active", "expired", "reason", "set_by", "set_at", "expires_at",
    "extended"} -- never None.

    A corrupt/absent value reads as NOT halted, deliberately: a dashboard
    that cannot parse its own flag must not silently stop the whole fleet
    from syncing, and an admin can always set it again."""
    stamp = now or utcnow_iso()
    raw = meta_get(conn, FLEET_HALT_KEY)
    if not raw:
        return _halt_state(None, stamp)
    try:
        data = json.loads(raw)
    except (TypeError, ValueError):
        return _halt_state(None, stamp)
    return _halt_state(data, stamp)


def fleet_halt_history(conn: sqlite3.Connection) -> list[dict[str, Any]]:
    """Newest first. Never raises: it feeds a banner."""
    entries = meta_get_json(conn, FLEET_HALT_HISTORY_KEY)
    if not isinstance(entries, list):
        return []
    return [e for e in entries if isinstance(e, dict)]


def _append_halt_history(conn: sqlite3.Connection, entry: dict[str, Any]) -> None:
    entries = fleet_halt_history(conn)
    entries.insert(0, entry)
    meta_set_json(conn, FLEET_HALT_HISTORY_KEY, entries[:FLEET_HALT_HISTORY_KEEP])


def set_fleet_halt(
    conn: sqlite3.Connection, active: bool, reason: str, by: str, now: str | None = None,
    hours: float | None = None, extend: bool = False,
) -> dict[str, Any]:
    """Engage, extend or release the fleet halt.

    `hours` is how long it stands for (default FLEET_HALT_DEFAULT_HOURS);
    `extend` is [ KEEP HALTED ], which keeps the original reason, who set it
    and when, and only moves the expiry -- so the banner still says how long
    the fleet has been stopped, not how long since the last click."""
    stamp = now or utcnow_iso()
    window = FLEET_HALT_DEFAULT_HOURS if hours is None else float(hours)
    prior = get_fleet_halt(conn, now=stamp)
    if active:
        if extend and not prior["active"] and len(str(reason or "").strip()) < 3:
            # UX-8 (resilience sweep 2026-08-28): a browser tab left open
            # across the halt's own expiry still shows [ KEEP HALTED ], which
            # submits no reason at all -- it means "keep the CURRENT halt
            # going", not "start a new one". Carrying that forward once the
            # halt has already ended would silently re-halt the whole fleet
            # with a blank reason, exactly the state UX-8 exists to prevent.
            # A real reason typed alongside extend=1 is treated as starting a
            # fresh halt, which is fine -- only the BLANK case is the trap.
            when = prior["expires_at"] or prior["set_at"]
            if when:
                raise ValueError(
                    f"Syncing already started again at {when}. To stop it "
                    f"again, give a reason."
                )
            raise ValueError(
                "Nothing is stopped, so there is nothing to keep stopped. "
                "Stop syncing with a reason."
            )
        expires_at = (parse_iso(stamp) + dt.timedelta(hours=window)).isoformat()
        state = {
            "active": True,
            "reason": str(reason or "")[:500],
            "set_by": str(by or "")[:64],
            "set_at": stamp,
            "expires_at": expires_at,
            "extended": int(prior.get("extended") or 0),
        }
        if extend and prior["active"]:
            state["reason"] = prior["reason"] or state["reason"]
            state["set_by"] = prior["set_by"] or state["set_by"]
            state["set_at"] = prior["set_at"] or stamp
            state["extended"] = int(prior.get("extended") or 0) + 1
    else:
        state = {
            "active": False,
            "reason": str(reason or "")[:500],
            "set_by": str(by or "")[:64],
            "set_at": stamp,
            "expires_at": "",
            "extended": 0,
        }
    meta_set(conn, FLEET_HALT_KEY, json.dumps(state))
    _append_halt_history(conn, {
        "at": stamp,
        "action": ("extend" if (active and extend and prior["active"])
                   else "halt" if active else "release"),
        "by": state["set_by"],
        "reason": state["reason"],
        "expires_at": state["expires_at"],
    })
    # Audited HERE rather than at the two call sites (SYS-11, 2026-08-28): the
    # JSON route and the Users page both pass their admin through this one
    # function, and a ledger the second door can skip is worse than none.
    audit(conn, by, "fleet.halt_set" if active else "fleet.halt_clear",
          "fleet", {"reason": state["reason"], "expires_at": state["expires_at"]},
          now=state["set_at"])
    return _halt_state(state, stamp)


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
    companion, which reports every 30s, can never be the row that goes.

    Ordered on the SERVER's `received_at` (v30, SYS-4): a machine whose clock
    is set to 2098 would otherwise pin itself as "most recent" for ever and
    evict its owner's genuinely live computers."""
    victims = [
        r["machine"] for r in conn.execute(
            """SELECT machine FROM machine_state WHERE editor_username=?
               ORDER BY COALESCE(received_at, reported_at) DESC, machine ASC
               LIMIT -1 OFFSET ?""",
            (editor, keep),
        )
    ]
    for machine in victims:
        conn.execute(
            "DELETE FROM machine_state WHERE editor_username=? AND machine=?",
            (editor, machine),
        )
        # The registry (v23) is filled from the same attacker-chosen string,
        # so it needs the same cap. Its PLAN is deliberately left alone: 20
        # machines back is far past any real fleet, but a laptop that has
        # been off for a month is not a reason to silently forget which
        # projects it holds -- and re-reporting under the same name picks the
        # rows straight back up.
        #
        # DCORE-12 (usability sweep 2026-09-04): NOT while that plan or a
        # Syncthing share still names it. A computer with no registry row has
        # no syncthing_device_id the enforce cycle can address, so its plan
        # falls back to the person-level share set and api_tick answers 404
        # "'leso' has no computer named 'LESO-MBP'" for a machine that is
        # still holding footage and still in Syncthing -- with no notice, no
        # audit and no log line anywhere. The row stays, which is exactly the
        # LOST state (lost_machines / DASH-16) the fleet grid already draws,
        # and the cap warning is raised instead of the fleet being reshaped.
        keeps = _machine_has_commitments(conn, editor, machine)
        if keeps:
            log.warning(
                "NOT evicting %s/%s past the %d-machine cap: %s. Its registry row is kept "
                "and it shows as LOST on the fleet page until somebody presses FORGET.",
                editor, machine, keep, keeps)
            continue
        conn.execute(
            "DELETE FROM machines WHERE editor_username=? AND machine=?",
            (editor, machine),
        )
    return len(victims)


def _machine_has_commitments(
    conn: sqlite3.Connection, editor: str, machine: str
) -> str:
    """Why this registry row may not be deleted, in words, or "" (DCORE-12).

    Two commitments: a sync plan of its own, and a Syncthing device id -- the
    only handle the enforce cycle has on the shares that device holds."""
    reasons: list[str] = []
    row = conn.execute(
        "SELECT COUNT(*) AS n FROM selections WHERE editor_username=? AND machine=?",
        (editor, machine)).fetchone()
    ticks = int((row or {"n": 0})["n"] or 0)
    if ticks:
        reasons.append(f"{ticks} project(s) still ticked for it")
    device = conn.execute(
        "SELECT syncthing_device_id FROM machines WHERE editor_username=? AND machine=?",
        (editor, machine)).fetchone()
    if device is not None and str(device["syncthing_device_id"] or "").strip():
        reasons.append("it still has a Syncthing device")
    return ", ".join(reasons)


# ---------------------------------------------------------- admin deletes
#
# The per-machine tables, i.e. everything keyed (editor_username, machine)
# that describes a computer's CURRENT state. lane_report_history and
# transfer_history are deliberately not here: they are append-only logs with
# their own age-out, and "what did that laptop upload last month" is a
# question an admin may still ask after the laptop is gone.
_MACHINE_STATE_TABLES = (
    "machines", "machine_state", "selections", "editor_prefs", "lane_report_current",
    "active_transfers", "editor_media_project", "editor_media", "media_tree_clips",
    "report_auth",
)


def forget_machine(conn: sqlite3.Connection, editor: str, machine: str) -> dict[str, Any] | None:
    """Erase one computer from the dashboard's records (admin "remove this
    computer", CR-76, 2026-08-24). None if the registry has no such machine.

    Returns what the CALLER still has to do: the machine's Syncthing device
    id, if it ever reported one, which api.forget_machine_everywhere takes
    out of Syncthing BEFORE this runs. Order matters: once these rows are
    gone the enforce cycle sees an unmapped device and leaves its shares
    alone (B16), so a device forgotten here but not there keeps receiving
    every project it was ticked for.

    The unassigned bucket (`machine = ''`) is NOT this machine's and is left
    alone: it belongs to the person and applies to their next computer.

    A companion still running on the computer registers it again on its
    next report: report tokens authenticate the PERSON (editor_report_tokens
    has no machine column), so "forget" is a record-keeping act, not a
    revocation. Deleting the user is the revocation."""
    row = conn.execute(
        "SELECT syncthing_device_id FROM machines WHERE editor_username=? AND machine=?",
        (editor, machine),
    ).fetchone()
    if row is None:
        return None
    if not machine or machine == ANY_MACHINE:
        return None
    deleted: dict[str, int] = {}
    for table in _MACHINE_STATE_TABLES:
        cur = conn.execute(
            f"DELETE FROM {table} WHERE editor_username=? AND machine=?",
            (editor, machine),
        )
        deleted[table] = cur.rowcount
    return {"editor": editor, "machine": machine,
            "syncthing_device_id": row["syncthing_device_id"], "deleted": deleted}


def editor_device_ids(conn: sqlite3.Connection, editor: str) -> list[str]:
    """Every Syncthing device id the dashboard associates with this person:
    the registry's per-machine ids plus the collector's name-resolved
    `devices` rows (a device approved under their username before any
    companion reported, or one whose companion never sent an id)."""
    ids: list[str] = []
    for sql in (
        "SELECT syncthing_device_id AS d FROM machines "
        "WHERE editor_username=? AND syncthing_device_id IS NOT NULL",
        "SELECT device_id AS d FROM devices WHERE editor_username=? AND is_server=0",
    ):
        for row in conn.execute(sql, (editor,)):
            if row["d"] and row["d"] not in ids:
                ids.append(row["d"])
    return ids


def forget_editor(conn: sqlite3.Connection, editor: str) -> dict[str, Any]:
    """Erase a person from the fleet's records: every computer of theirs
    (forget_machine), the unassigned bucket, their known_editors row and the
    collector's device mapping (CR-76, 2026-08-24).

    After this, known_editor_usernames() no longer returns them - all four
    of its sources are cleared here - so a device that still carries their
    name is unmapped from the enforce cycle's point of view. That is why the
    caller removes their devices from Syncthing FIRST (see forget_machine).

    Credentials are not this function's job: sessions and report tokens are
    revoked by api._purge_user_credentials, which must run after the commit
    (the session store writes through its own connection)."""
    machines = [
        r["machine"] for r in conn.execute(
            "SELECT machine FROM machines WHERE editor_username=?", (editor,))
    ]
    forgotten = [forget_machine(conn, editor, m) for m in machines]
    deleted: dict[str, int] = {}
    # Rows under a machine name the registry no longer holds (evicted, or
    # written by a report the registry rejected) plus the '' bucket: sweep
    # every per-machine table by editor, not just by registered machine.
    for table in _MACHINE_STATE_TABLES:
        cur = conn.execute(f"DELETE FROM {table} WHERE editor_username=?", (editor,))
        deleted[table] = cur.rowcount + sum(
            (f or {}).get("deleted", {}).get(table, 0) for f in forgotten)
    device_ids = [
        r["device_id"] for r in conn.execute(
            "SELECT device_id FROM devices WHERE editor_username=? AND is_server=0", (editor,))
    ]
    for device_id in device_ids:
        forget_device(conn, device_id)
    deleted["devices"] = len(device_ids)
    deleted["known_editors"] = conn.execute(
        "DELETE FROM known_editors WHERE editor_username=?", (editor,)).rowcount
    return {"editor": editor, "machines": [f["machine"] for f in forgotten if f],
            "deleted": deleted}


def forget_device(conn: sqlite3.Connection, device_id: str) -> None:
    """Drop the collector's mirror of one Syncthing device and the
    completion/missing-file rows hanging off it (they reference devices.id).
    The collector would re-create the row on its next config pass if the
    device were still in Syncthing's config, which is exactly why the caller
    removes it from Syncthing first."""
    row = conn.execute("SELECT id FROM devices WHERE device_id=?", (device_id,)).fetchone()
    if row is None:
        return
    for table in ("completion_current", "completion_history", "missing_files"):
        conn.execute(f"DELETE FROM {table} WHERE device_id=?", (row["id"],))
    conn.execute("DELETE FROM devices WHERE id=?", (row["id"],))


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


def prune(conn: sqlite3.Connection, now: str, pin: bool = False) -> None:
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
    # SYS-4 (resilience sweep 2026-08-28): `received_at` (v30), never the
    # client's clock. This predicate has always read the column named
    # `reported_at`, which api.py happens to fill with the server's own
    # timestamp -- one hand passing the companion's value in, and a machine
    # 30 days behind real time would have been DELETED from the fleet grid on
    # every prune while reporting perfectly. COALESCE covers a row written
    # before v30 backfilled (and any test that INSERTs by hand).
    conn.execute(
        "DELETE FROM machine_state WHERE COALESCE(received_at, reported_at) < ?",
        (cutoff(days=MACHINE_STATE_MAX_AGE_DAYS),),
    )
    conn.execute(
        "DELETE FROM missing_files WHERE refreshed_at < ?",
        (cutoff(days=MISSING_FILES_MAX_AGE_DAYS),),
    )
    # The audit ledger is append-only, so this is the ONLY statement in the
    # product that removes a row from it (SYS-11, 2026-08-28). 180 days: long
    # enough that "what changed the week an editor lost two days of syncing"
    # is still answerable, bounded so /data cannot grow without limit.
    conn.execute(
        "DELETE FROM fleet_audit WHERE at < ?", (cutoff(days=AUDIT_MAX_AGE_DAYS),),
    )
    # The alert ledger (v38, SYS-8). Shorter than the audit's 180 days because
    # nothing reads it past "did we already say this" and the last few weekly
    # reports; the dedup window is a single day, so this cannot shorten it.
    conn.execute(
        "DELETE FROM alert_log WHERE at < ?", (cutoff(days=ALERT_MAX_AGE_DAYS),),
    )
    # Diagnostics bundles (v33, SYS-7). Bounded at write time to the newest
    # DIAGNOSTICS_KEEP_PER_MACHINE per computer; this is the age bound, on the
    # SERVER's received_at rather than the companion's `at` -- a machine with a
    # wrong clock must not be able to keep its bundles for ever, nor lose them
    # on arrival (SYS-4's lesson, applied to a second table).
    conn.execute(
        "DELETE FROM diagnostics WHERE received_at < ?",
        (cutoff(days=DIAGNOSTICS_MAX_AGE_DAYS),),
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
    # REL-8 (resilience sweep 2026-08-28): a pushed update nobody could take
    # rode every report for ever and showed as "pending" on the Packages page
    # with no way to tell it from one made this morning. Expiring it here, in
    # the cycle that already bounds every other row, with the reason in the
    # audit ledger.
    expire_machine_update_requests(conn, now)
    # FLEET JOBS (phase 0): a lease whose holder has gone is re-queued here as
    # well as on the way into a claim. Both, deliberately -- the claim path
    # only runs when some OTHER machine asks for work, and a fleet with one
    # busy machine would otherwise leave a dead claim standing until somebody
    # opened a page. Finished rows age out after JOBS_MAX_AGE_DAYS; queued
    # ones never do, because a job nobody can run is the thing phase 0 exists
    # to make visible.
    expire_leases(conn, now, pin=pin)
    prune_jobs(conn, now, JOBS_MAX_AGE_DAYS)
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

def media_rel_key(rel_path: str) -> str:
    """The ONE Unicode spelling a media rel_path is stored and compared in.

    macOS hands filenames back DECOMPOSED (NFD): a Mac's disk manifest spells
    `Matej Simalcik` as S+caron, c+caron, i+acute, while the NAS inventory
    walk and every Windows machine spell the same directory composed (NFC).
    `fetch_sync_backlog` diffs those two tables as exact strings, so until
    CR-90 (2026-08-28) every file with an accented character in its path sat
    in [ QUEUED ] on a Mac forever: 12 files / 2.9 GB of FF5/Animals proxies
    that were already on the machine, byte for byte, behind a lane B that
    correctly reported "transferred 0 file(s)" every pass -- rclone folds the
    normalisations when it compares, and this diff did not. CJK folders were
    unaffected (no decomposed form), which is what made it read as a partial
    sync rather than as a comparison bug.

    Normalising on the way IN rather than in the SQL is safe for these two
    tables specifically: neither `nas_media.rel_path` nor
    `editor_media.rel_path` ever drives a filesystem operation -- they feed
    the backlog diff, the rollup counts, and the name list a human reads.
    Do not reach for this for a path something opens, renames or deletes;
    there the bytes on disk are the truth (`file_moves` keeps its own).
    """
    return unicodedata.normalize("NFC", str(rel_path or ""))


def replace_nas_media(
    conn: sqlite3.Connection,
    project_id: int,
    rows: list[tuple[str, str, str, int | None, int | None]],
    tree_sig: str,
    n_dirs: int,
    now: str,
    force: bool = False,
) -> bool:
    """rows: [(rel_path, kind, ext, size, mtime_ns)]. Replaces the project's
    inventory and recomputes the rollup in nas_inventory_state.

    REFUSES A COLLAPSE (DASH-5, resilience sweep 2026-08-28). Returns True if
    it replaced, False if it refused. When the ZFS dataset under
    /projects/<project> is not mounted (pool import ordering after a NAS
    reboot) or the directory is being renamed by hand mid-cycle, the parent
    bind mount still exists, the project dir exists and is EMPTY, and the
    walk returns []. This function used to DELETE the whole inventory and
    write the rollup as 0 originals / 0 proxies with last_error NULL, so
    every media-presence view said the NAS holds nothing and
    fetch_sync_backlog reported every original an editor holds as "the NAS is
    missing this" -- the page telling the owner his footage is not on the
    server. A project cannot lose all (or ~all) of its media between two
    cycles by any legitimate route, so the previous inventory is kept and the
    reason goes into nas_inventory_state.last_error, where the project page
    renders it. tree_sig is deliberately NOT updated on a refusal: the next
    cycle must walk again rather than believe it is up to date.
    """
    prev = conn.execute(
        """SELECT n_originals, n_proxies FROM nas_inventory_state
           WHERE project_id=?""", (project_id,)
    ).fetchone()
    prev_total = ((prev["n_originals"] or 0) + (prev["n_proxies"] or 0)) if prev else 0
    prev_originals = (prev["n_originals"] or 0) if prev else 0
    if not force and prev_total > 0:
        collapsed = (
            (prev_originals > 0 and not any(r[1] == "original" for r in rows))
            or len(rows) < prev_total * 0.1
        )
        if collapsed:
            message = (f"walk returned {len(rows)} of {prev_total} files - not replacing. "
                       f"The project directory looks unmounted or was renamed on the NAS.")
            conn.execute(
                """UPDATE nas_inventory_state SET walked_at=?, last_error=?
                   WHERE project_id=?""",
                (now, message, project_id),
            )
            return False
    conn.execute("DELETE FROM nas_media WHERE project_id=?", (project_id,))
    conn.executemany(
        """INSERT OR REPLACE INTO nas_media
             (project_id, rel_path, kind, ext, size, mtime_ns, refreshed_at)
           VALUES (?, ?, ?, ?, ?, ?, ?)""",
        [(project_id, media_rel_key(rel), kind, ext, size, mtime, now)
         for rel, kind, ext, size, mtime in rows],
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
    return True


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
        [(editor, machine, slug, media_rel_key(rel), kind, size, now)
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
    # last_error / walked_at ride along since DASH-5 (resilience sweep
    # 2026-08-28): the project page has to be able to say "this project's NAS
    # inventory is the one from before the dataset went missing", and every
    # caller of this function already hands the dict straight to a view.
    row = conn.execute(
        """SELECT n_originals, bytes_originals, n_proxies, bytes_proxies,
                  walked_at, last_error
           FROM nas_inventory_state WHERE project_id=?""",
        (project_id,),
    ).fetchone()
    if row is None:
        return {"n_originals": 0, "bytes_originals": 0, "n_proxies": 0, "bytes_proxies": 0,
                "walked_at": None, "last_error": None}
    return dict(row)


def project_proxy_bytes(conn: sqlite3.Connection, slug: str) -> int | None:
    """How many bytes of PROXIES this project holds on the NAS, or None.

    UX-1 (resilience sweep 2026-08-28): the figure the tick preflight needs.
    None means the collector has never walked this project (or the walk was
    refused and the rollup is deliberately stale-but-kept, see
    replace_nas_media), which the warning treats as "cannot say" rather than
    as zero -- a preflight that reads an un-walked 4 TB project as 0 GB is
    worse than no preflight.

    Proxies only, deliberately: lane B is what a tick brings DOWN to an
    editor's machine, and originals stay on the NAS.
    """
    row = conn.execute(
        """SELECT s.bytes_proxies AS b, s.walked_at AS walked_at
           FROM nas_inventory_state s JOIN projects p ON p.id = s.project_id
           WHERE p.slug = ?""",
        (slug,),
    ).fetchone()
    if row is None or not row["walked_at"]:
        return None
    return int(row["b"] or 0)


def project_proxy_bytes_map(conn: sqlite3.Connection) -> dict[str, int]:
    """slug -> NAS proxy bytes, for the pages that need every project at once
    (the assignment grid's preflight, UX-1). Only projects the collector has
    actually walked appear, so a missing key reads as "cannot say"."""
    return {
        r["slug"]: int(r["b"] or 0)
        for r in conn.execute(
            """SELECT p.slug AS slug, s.bytes_proxies AS b
               FROM nas_inventory_state s JOIN projects p ON p.id = s.project_id
               WHERE s.walked_at IS NOT NULL AND s.walked_at != ''"""
        )
    }


def machine_free_bytes(
    conn: sqlite3.Connection, editor: str, machine: str
) -> tuple[int | None, str | None]:
    """(free bytes on that computer's sync drive, when it was measured).

    (None, None) for a machine that has never reported a disk section -- every
    machine in the field until the companion half of SYS-5 ships. The tick
    warning stays silent for those rather than inventing a number.
    """
    row = conn.execute(
        """SELECT disk_root_free_bytes AS free, disk_at FROM machine_state
           WHERE editor_username=? AND machine=?""",
        (editor, machine),
    ).fetchone()
    if row is None:
        return None, None
    free = row["free"]
    return (None if free is None else int(free)), row["disk_at"]


def machine_disk_map(
    conn: sqlite3.Connection, editor: str | None = None
) -> dict[tuple[str, str], dict[str, Any]]:
    """(editor, machine) -> {free, total, at} for the assignment grid's
    column headers, so [ ALL ] can add a column's projects up in the browser
    without a request per cell (UX-1)."""
    q = ("SELECT editor_username, machine, disk_root_free_bytes AS free, "
         "disk_root_total_bytes AS total, disk_at FROM machine_state")
    params: list[Any] = []
    if editor is not None:
        q += " WHERE editor_username=?"
        params.append(editor)
    return {
        (r["editor_username"], r["machine"]): {
            "free": r["free"], "total": r["total"], "at": r["disk_at"]}
        for r in conn.execute(q, params)
    }


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
    # The selections join is per COMPUTER since v24: this machine's own plan,
    # or the unassigned bucket when it has none of its own (the SQL spelling
    # of selections_for_machine). Before that, one person's laptop was told
    # it was behind on everything their desktop was ticked for.
    pair_q = """SELECT emp.editor_username AS editor, emp.machine,
                       emp.project_slug AS slug, emp.truncated,
                       p.id AS project_id, p.label, s.sync_mode
                FROM editor_media_project emp
                JOIN selections s ON s.editor_username = emp.editor_username
                                 AND s.project_slug = emp.project_slug
                                 AND (s.machine = emp.machine
                                      OR (s.machine = ''
                                          AND NOT EXISTS (
                                            SELECT 1 FROM selections own
                                             WHERE own.editor_username = emp.editor_username
                                               AND own.machine = emp.machine)))
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
            if direction == "down" and pair["sync_mode"] == SYNC_MODE_UPLOAD_ONLY:
                # An upload-only tick never runs lane B, so the proxies it
                # lacks are not a backlog -- listing them would show a
                # download that is never going to start (the CR-28 shape).
                continue
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
    # The kinds that also run in a Syncthing-less deployment can never be
    # evidence that Syncthing is reachable -- read off the one list the
    # collector itself gates on, never a literal here (2026-09-04).
    placeholders = ",".join("?" for _ in SYNCTHING_FREE_KINDS)
    latest = conn.execute(
        f"SELECT ok, finished_at FROM poll_runs WHERE kind NOT IN ({placeholders})"
        " ORDER BY id DESC LIMIT 1", SYNCTHING_FREE_KINDS
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


# ======================================================================
# THE FLEET JOB QUEUE (v41, docs/TIMELINE-CARDS-INTO-CCSYNC.md phase 0)
#
# One row of work that some machine on the fleet may do. Everything here is
# the ytdl download lease generalised (`ytdl/web/ytdlweb/db.py` claim_download
# / heartbeat_download / expire_lease), because that queue is the one this box
# has actually run in anger -- including the evening it survived (CR-80).
#
# Three rules carried over verbatim, each of them paid for:
#
#   * EVERY WRITE IS A COMPARE-AND-SET with the whole rule in its WHERE
#     clause. Read-then-write is a race between two claimants, and "which
#     machine is transcribing this folder" is not a question two answers may
#     be given to.
#   * POSSESSION EXPIRES. A claimant can vanish without telling anyone (a
#     laptop lid, a power cut mid-encode), so the lease is a deadline the
#     holder must keep pushing, never a lock it must remember to drop.
#   * THE KEY IS (editor, MACHINE). One person's laptop and desktop are two
#     executors (CR-66/data-model-7); keying on the person is how both ended
#     up doing the same work.
#
# What is deliberately NOT here: any notion of which machine SHOULD do a job.
# That is jobs.py (capability match -> policy -> rank -> offer), so that this
# file stays "the queue" and the scheduler stays a thing with an opinion that
# can be tested without a database full of fleet state.
# ======================================================================

JOB_QUEUED = "queued"
JOB_CLAIMED = "claimed"
JOB_RUNNING = "running"
JOB_DONE = "done"
JOB_FAILED = "failed"
JOB_ABANDONED = "abandoned"
# Handed to the dashboard's OWN in-process executor after the fleet spent the
# retry budget (v45, phase 4, §4.4 rule 5). It is not terminal -- the work is
# still going to happen -- and it is not held by any machine, which is the
# whole point: a pinned job NEVER goes back to the fleet.
JOB_PINNED = "pinned"

# Held by a machine right now: a claim that has not yet been heartbeated as
# running is still possession, which is why both are in here.
JOB_HELD_STATES = (JOB_CLAIMED, JOB_RUNNING)
# Nothing will ever pick these up again.
JOB_TERMINAL_STATES = (JOB_DONE, JOB_FAILED, JOB_ABANDONED)

# The kinds this build knows. A job of any other kind is accepted into the
# table (a newer submitter must not be refused by an older dashboard) but is
# never offered to anybody -- see jobs.explain, which says exactly that.
JOB_KIND_WHISPER = "whisper"
# Phase 1 (2026-08-30): the three Timeline Cards media recipes. The names are
# the ones the plan's §4.2 table uses, hyphenated, and they are what a job row
# carries for ever -- renaming one later would strand every queued job written
# by an older submitter.
JOB_KIND_PROXY_480P = "proxy-480p"
JOB_KIND_AUDIO_EXTRACT = "audio-extract"
JOB_KIND_PEAKS = "peaks"
JOB_KINDS = (JOB_KIND_WHISPER, JOB_KIND_PROXY_480P, JOB_KIND_AUDIO_EXTRACT,
             JOB_KIND_PEAKS)

# What the fleet grid calls a kind. Data rather than a chain of ifs in the
# template, and NOT `kind.upper()`: "PROXY-480P" is the shape of a database
# value, and the chip is read by a person ("[ PROXY 480p: 62% ]").
JOB_KIND_LABELS = {
    JOB_KIND_WHISPER: "WHISPER",
    JOB_KIND_PROXY_480P: "PROXY 480p",
    JOB_KIND_AUDIO_EXTRACT: "AUDIO",
    JOB_KIND_PEAKS: "PEAKS",
}


def job_label(kind: str) -> str:
    return JOB_KIND_LABELS.get(str(kind or ""), str(kind or "JOB").upper())

# How long a claim is good for without a heartbeat. Five minutes, against the
# companion's 30 s heartbeat: ten missed beats is a machine that has gone,
# not a machine that is briefly busy. A whisper pass on an hour of audio runs
# for many multiples of this, which is exactly why the lease is refreshed
# rather than sized to the work.
JOB_LEASE_SECONDS = 300

# Attempts before a job is ABANDONED rather than re-queued. Per kind, because
# "how many times is it worth sending this to a machine that might not be the
# problem" is a property of the work: a whisper run that dies twice on two
# different machines is a bad input, not bad luck.
# The three media kinds get TWO, not three: a recipe is deterministic and
# cheap, so a second machine failing the same clip the same way is evidence
# about the CLIP (a file with no audio track, a rush half-written by a copy
# still in flight) and a third attempt only costs another editor's evening.
JOB_RETRY_BUDGET = {
    JOB_KIND_WHISPER: 3,
    JOB_KIND_PROXY_480P: 3,
    JOB_KIND_AUDIO_EXTRACT: 2,
    JOB_KIND_PEAKS: 2,
}
JOB_RETRY_BUDGET_DEFAULT = 3

# Ceiling on one submitted job's JSON fields. A queue row is written by an
# authenticated admin, so this is a sanity bound and not a security one -- but
# `inputs` is (root, rel_path) pairs and nothing legitimate is near it.
JOB_JSON_MAX_BYTES = 16 * 1024

# Per kind, and deliberately small. whisper is a whole GPU each; the media
# recipes are ffmpeg reading a rush over the share, and four of those is
# already the share's ceiling on this fleet's hardware. Overridable per
# deployment (DASH_JOBS_MAX_RUNNING) because "how many at once" is a fact
# about somebody's network, not about this code.
JOB_MAX_RUNNING = {
    JOB_KIND_WHISPER: 2,
    JOB_KIND_PROXY_480P: 4,
    JOB_KIND_AUDIO_EXTRACT: 4,
    JOB_KIND_PEAKS: 4,
}
JOB_MAX_RUNNING_DEFAULT = 4

# How long a machine is left alone after handing a job back failed. Two
# minutes: long enough that the same machine does not eat a two-attempt
# budget on its own, short enough that a fleet of one (the base rig, most
# evenings) is not parked for the night by one bad clip.
JOB_COOLDOWN_SECONDS = 120


def job_retry_budget(kind: str) -> int:
    return int(JOB_RETRY_BUDGET.get(str(kind or ""), JOB_RETRY_BUDGET_DEFAULT))


# WHICH KINDS MAY BE PINNED to the dashboard's own worker when the fleet has
# spent the budget (§4.4 rule 5, phase 4). The three media recipes, and
# never `whisper`: the executor is the dashboard container, which has ffmpeg
# and the two mounts and NO GPU. A whisper job pinned there would be a job
# that fails for ever in a new place -- so it is abandoned, visibly, which is
# the honest answer and the one an admin can act on.
JOB_PINNABLE_KINDS = (JOB_KIND_PROXY_480P, JOB_KIND_AUDIO_EXTRACT,
                      JOB_KIND_PEAKS)


def _spent_state(kind: str, pin: bool) -> str:
    """What becomes of a job whose retry budget is gone.

    `pin` is the CALLER saying there is an executor here at all (the
    Timeline Cards engine is mounted). Phase 1 shipped `abandoned` with the
    note that an abandoned job is visible, not handed to a NAS-side executor
    "because there is none"; there is one now, and abandoning is what happens
    when there is not.
    """
    if pin and str(kind) in JOB_PINNABLE_KINDS:
        return JOB_PINNED
    return JOB_ABANDONED


def _job_json(value: Any) -> str:
    """A job's JSON column, bounded. Never a raise on a value that will not
    serialise: a submitter that sends something exotic gets an empty object
    and a job that cannot run, not a 500 on the queue everything else uses."""
    try:
        text = json.dumps(value if value is not None else {},
                          separators=(",", ":"), sort_keys=True, default=str)
    except (TypeError, ValueError):
        return "{}"
    return text if len(text) <= JOB_JSON_MAX_BYTES else "{}"


def _job_loads(text: Any) -> Any:
    try:
        return json.loads(text) if text else None
    except (TypeError, ValueError):
        return None


def job_row(row: sqlite3.Row | None) -> dict[str, Any] | None:
    """A job row with its JSON fields parsed, or None.

    A damaged blob reads as an EMPTY requirement set and an empty input set,
    never as a raise: the page that lists jobs is the page you open when one
    has gone wrong."""
    if row is None:
        return None
    job = dict(row)
    job["inputs"] = _job_loads(job.get("inputs_json")) or {}
    job["requires"] = _job_loads(job.get("requires_json")) or {}
    job["cost"] = _job_loads(job.get("cost_json")) or {}
    job["result"] = _job_loads(job.get("result_json"))
    # v46. `forced` is a BOOL out here and an INTEGER in the column: every
    # reader of this row is a scheduler branch, a JSON body or a template,
    # and 0/1 in a JSON payload is the kind of thing the other half of a
    # contract gets subtly wrong. `target_machine` is "" and never None for
    # the same reason -- a name to compare against, or nothing to compare.
    job["forced"] = bool(job.get("forced"))
    job["target_machine"] = str(job.get("target_machine") or "")
    return job


def create_job(
    conn: sqlite3.Connection, kind: str, inputs: Mapping[str, Any],
    requires: Mapping[str, Any] | None = None,
    cost: Mapping[str, Any] | None = None,
    created_by: str = "", priority: int = 0, now: str | None = None,
    forced: bool = False, target_machine: str | None = None,
) -> int:
    """Queue one job. -> its id.

    `inputs` must spell paths as (root name, relative path) pairs; nothing
    here enforces that, because "is this an absolute path" is a question with
    a different answer on every platform in the fleet. The submitters
    (tools/jobs.py, and Timeline Cards later) build them, api.py's model
    bounds them, and docs/API.md is the contract.

    `forced` and `target_machine` are §10's two admin levers, and neither is
    validated here: an unknown machine name is a job that waits visibly with
    a receipt saying nobody by that name has reported, which is a better
    answer than a refusal at submit time to a person who cannot see the
    fleet's spelling of it.
    """
    now = now or utcnow_iso()
    cur = conn.execute(
        """INSERT INTO jobs (kind, created_at, created_by, priority, inputs_json,
                             requires_json, cost_json, state, attempts, updated_at,
                             forced, target_machine)
           VALUES (?, ?, ?, ?, ?, ?, ?, ?, 0, ?, ?, ?)""",
        (str(kind), now, str(created_by or ""), int(priority),
         _job_json(dict(inputs or {})), _job_json(dict(requires or {})),
         _job_json(dict(cost or {})), JOB_QUEUED, now,
         int(bool(forced)), (str(target_machine).strip()[:128] or None
                             if target_machine else None)),
    )
    return int(cur.lastrowid)


def get_job(conn: sqlite3.Connection, job_id: int) -> dict[str, Any] | None:
    return job_row(
        conn.execute("SELECT * FROM jobs WHERE id=?", (int(job_id),)).fetchone())


def list_jobs(
    conn: sqlite3.Connection, state: str | None = None, kind: str | None = None,
    machine: str | None = None, editor: str | None = None, limit: int = 200,
) -> list[dict[str, Any]]:
    """Newest first. `state='open'` is the useful one: everything unfinished."""
    where: list[str] = []
    args: list[Any] = []
    if state == "open":
        where.append("state NOT IN (%s)" % ",".join("?" * len(JOB_TERMINAL_STATES)))
        args.extend(JOB_TERMINAL_STATES)
    elif state:
        where.append("state=?")
        args.append(state)
    if kind:
        where.append("kind=?")
        args.append(kind)
    if editor:
        where.append("claimed_by=?")
        args.append(editor)
    if machine:
        where.append("claimed_machine=?")
        args.append(machine)
    sql = "SELECT * FROM jobs"
    if where:
        sql += " WHERE " + " AND ".join(where)
    sql += " ORDER BY id DESC LIMIT ?"
    args.append(max(1, min(int(limit), 1000)))
    return [job_row(r) for r in conn.execute(sql, args)]  # type: ignore[misc]


def queued_jobs(
    conn: sqlite3.Connection, kinds: Iterable[str] | None = None, limit: int = 200,
) -> list[dict[str, Any]]:
    """The candidates, in the order a scheduler should consider them: highest
    priority first, then oldest -- so a job that has been waiting is not
    starved by one submitted a second ago at the same priority."""
    sql = "SELECT * FROM jobs WHERE state=?"
    args: list[Any] = [JOB_QUEUED]
    kinds = list(kinds) if kinds is not None else None
    if kinds is not None:
        if not kinds:
            return []
        sql += " AND kind IN (%s)" % ",".join("?" * len(kinds))
        args.extend(kinds)
    sql += " ORDER BY priority DESC, id ASC LIMIT ?"
    args.append(max(1, min(int(limit), 1000)))
    return [job_row(r) for r in conn.execute(sql, args)]  # type: ignore[misc]


# How far back the JOBS page's [ SHOW FINISHED ] list and the abandoned count
# look (DDIAG-11, 2026-09-04). A day, because the question the count answers
# is "did the fleet give up on anything while I was not watching" and the
# person asking it looks once a morning.
JOB_FINISHED_WINDOW_HOURS = 24

# Where a re-queued job records the row it came from (DDIAG-11). In `inputs`
# and not a new column: a retry is a NEW row with the SAME inputs, every
# runner reads that dict by key and ignores what it does not know, and the
# alternative was a migration for a breadcrumb.
JOB_RETRY_OF = "retry_of"


def finished_jobs(
    conn: sqlite3.Connection, hours: float = JOB_FINISHED_WINDOW_HOURS,
    limit: int = 100, now: str | None = None,
) -> list[dict[str, Any]]:
    """Terminal jobs from the last `hours`, newest first.

    DDIAG-11 (2026-09-04): the jobs page listed OPEN jobs only, so a fleet
    that had spent its retry budget on twelve whisper jobs read "Nothing is
    queued or running." and the abandoned work was visible to nobody without
    a terminal.

    `updated_at` and not `created_at` is the window: a job queued on Monday
    and abandoned an hour ago is news this morning, and one queued an hour
    ago and finished then is not interesting twice.
    """
    now = now or utcnow_iso()
    args: list[Any] = [_iso_minus(now, int(max(0.0, float(hours)) * 3600))]
    args.extend(JOB_TERMINAL_STATES)
    args.append(max(1, min(int(limit), 1000)))
    sql = ("SELECT * FROM jobs WHERE updated_at >= ?"
           "   AND state IN (%s) ORDER BY id DESC LIMIT ?"
           % ",".join("?" * len(JOB_TERMINAL_STATES)))
    return [job_row(r) for r in conn.execute(sql, args)]  # type: ignore[misc]


def count_abandoned_jobs(
    conn: sqlite3.Connection, hours: float = JOB_FINISHED_WINDOW_HOURS,
    now: str | None = None,
) -> int:
    """How many jobs the fleet gave up on in the window (DDIAG-11).

    Its own query rather than a len() over `finished_jobs`, because this one
    is on every render of the queue head and the list is not."""
    now = now or utcnow_iso()
    row = conn.execute(
        "SELECT COUNT(*) AS n FROM jobs WHERE state=? AND updated_at >= ?",
        (JOB_ABANDONED,
         _iso_minus(now, int(max(0.0, float(hours)) * 3600)))).fetchone()
    return int(row["n"]) if row is not None else 0


def open_retry_of(conn: sqlite3.Connection, job_id: int) -> int | None:
    """The id of an unfinished job that is already a new attempt at this one.

    Read in Python and not with json_extract: the breadcrumb lives in a JSON
    column whose shape this code owns, the open queue is bounded, and a SQL
    function that is compiled out of some SQLite builds is not something to
    make a refusal depend on.
    """
    for row in list_jobs(conn, state="open", limit=1000):
        try:
            origin = int((row.get("inputs") or {}).get(JOB_RETRY_OF) or 0)
        except (TypeError, ValueError):
            continue
        if origin == int(job_id):
            return int(row["id"])
    return None


def retry_job(
    conn: sqlite3.Connection, job_id: int, created_by: str = "",
    now: str | None = None,
) -> tuple[int | None, str]:
    """Queue the same work again. -> (new job id, "") or (None, why not).

    DDIAG-11. THE OLD ROW IS NOT TOUCHED: a resurrection would rewrite the
    attempt history, and "this failed three times on two machines and then
    worked" is the only record anybody has of a bad clip. The new row carries
    the same kind, inputs, requirements, cost, priority and section 10 levers,
    plus `inputs.retry_of`.

    Two refusals, both sentences a person reads: a job that has not finished
    (cancel it first, and nothing forces a row terminal behind a live ffmpeg)
    and a job whose retry is still on the queue.
    """
    job = get_job(conn, int(job_id))
    if job is None:
        return None, ""
    state = str(job.get("state") or "")
    if state not in JOB_TERMINAL_STATES:
        return None, (f"job #{job_id} is {state} and has not finished, so there "
                      f"is nothing to try again yet. Cancel it first.")
    open_id = open_retry_of(conn, int(job_id))
    if open_id is not None:
        return None, (f"job #{open_id} is already a new attempt at job #{job_id} "
                      f"and it is still on the queue.")
    inputs = dict(job.get("inputs") or {})
    inputs[JOB_RETRY_OF] = int(job_id)
    new_id = create_job(
        conn, str(job.get("kind") or ""), inputs, dict(job.get("requires") or {}),
        dict(job.get("cost") or {}), created_by=created_by,
        priority=int(job.get("priority") or 0), now=now,
        forced=bool(job.get("forced")),
        target_machine=(str(job.get("target_machine") or "") or None))
    return new_id, ""


def job_requirements_met(
    requires: Mapping[str, Any] | None, capabilities: Mapping[str, Any] | None,
) -> tuple[bool, str]:
    """Does this machine meet a job's HARD requirements? -> (ok, why not).

    Pure, and deliberately in db.py rather than in the scheduler: it is what
    claim_next_job's compare-and-set consults, and the claim route must never
    be able to hand out a job on a looser rule than the one the offer was
    computed with.

    Four shapes, and everything unrecognised is a REFUSAL: a dashboard that
    does not understand a requirement must not decide it is satisfied. That
    is the difference between "no machine can run this yet" (visible, on the
    why page) and "we ran a GPU job on a machine with no GPU".

        gpu_vram_gb: 6        a number, >=
        cpu_count:   8        a number, >=
        mount: "vault"        a name that must appear in capabilities["mounts"]
        <anything else>: true/false/str   equality against the capability
    """
    caps = dict(capabilities or {})
    for key, want in dict(requires or {}).items():
        if key in ("mount", "mounts"):
            names = [str(m) for m in (caps.get("mounts") or [])]
            wanted = [want] if isinstance(want, str) else list(want or [])
            missing = [str(w) for w in wanted if str(w) not in names]
            if missing:
                return False, "this computer has no %s mount" % ", ".join(missing)
            continue
        have = caps.get(key)
        if isinstance(want, bool):
            if bool(have) != want:
                return False, "%s is %s on this computer" % (
                    key, "not available" if want else "set")
            continue
        if isinstance(want, (int, float)):
            try:
                if have is None or float(have) < float(want):
                    return False, f"{key} is {have!r}, the job needs at least {want}"
            except (TypeError, ValueError):
                return False, f"{key} is {have!r}, the job needs at least {want}"
            continue
        if str(have or "") != str(want):
            return False, f"{key} is {have!r}, the job needs {want!r}"
    return True, ""


def _job_lease_until(now: str, seconds: float) -> str:
    """now + seconds in the exact shape utcnow_iso() produces, which is what
    makes comparing these timestamps as STRINGS sound: one producer, one
    offset, one resolution, so lexicographic order is chronological order."""
    return (parse_iso(now) + dt.timedelta(seconds=max(0, int(seconds)))).isoformat()


def claim_job(
    conn: sqlite3.Connection, job_id: int, editor: str, machine: str,
    now: str | None = None, lease_seconds: float = JOB_LEASE_SECONDS,
) -> bool:
    """THE compare-and-set. -> did this caller get it.

    The whole rule is in the WHERE clause: the job must still be QUEUED. Two
    machines offered the same job both call this; SQLite serialises the
    writes, the second matches no row, and it moves on to the next candidate
    rather than being told a lie."""
    now = now or utcnow_iso()
    cur = conn.execute(
        """UPDATE jobs SET state=?, claimed_by=?, claimed_machine=?,
                           lease_expires_at=?, heartbeat_at=?, updated_at=?
            WHERE id=? AND state=?""",
        (JOB_CLAIMED, str(editor), str(machine),
         _job_lease_until(now, lease_seconds), now, now, int(job_id), JOB_QUEUED),
    )
    return bool(cur.rowcount)


def claim_next_job(
    conn: sqlite3.Connection, editor: str, machine: str,
    capabilities: Mapping[str, Any] | None = None,
    now: str | None = None, lease_seconds: float = JOB_LEASE_SECONDS,
    allowed_ids: Iterable[int] | None = None,
    kinds: Iterable[str] | None = None,
    ids: Iterable[int] | None = None,
) -> dict[str, Any] | None:
    """Claim the best queued job this machine can actually do, or None.

    `capabilities` is re-checked HERE and not merely at offer time: the offer
    rode a report reply up to a report interval ago, and the machine acting on
    it must not be handed work on the strength of a stale answer.

    `allowed_ids` narrows the candidates to what the scheduler offered (the
    policy filter -- halt, idleness, upgrades -- lives there); None means
    "capability match alone", which is what a caller with no fleet state in
    hand can honestly ask for.

    `ids` is the CLAIMANT's own narrowing (§10.2) and is INTERSECTED with
    `allowed_ids`, never substituted for it: a companion whose idle gate is
    closed claims the forced jobs and only those, and the fact that it asked
    for a job must never be able to widen what the scheduler was willing to
    give it.
    """
    now = now or utcnow_iso()
    allowed = None if allowed_ids is None else {int(i) for i in allowed_ids}
    wanted = None if ids is None else {int(i) for i in ids}
    for job in queued_jobs(conn, kinds=kinds):
        if allowed is not None and int(job["id"]) not in allowed:
            continue
        if wanted is not None and int(job["id"]) not in wanted:
            continue
        ok, _why = job_requirements_met(job.get("requires"), capabilities)
        if not ok:
            continue
        if claim_job(conn, int(job["id"]), editor, machine, now, lease_seconds):
            return get_job(conn, int(job["id"]))
    return None


def clamp_progress(value: Any) -> float | None:
    """0..1, or None for "this runner cannot say".

    None is NOT zero (the cap_idle_seconds rule again): a peaks pass reads its
    input in one gulp and has no honest fraction to report, and a grid showing
    it as 0% would say the machine is stuck when it is working.
    """
    if value is None:
        return None
    try:
        number = float(value)
    except (TypeError, ValueError):
        return None
    if number != number:                                  # NaN
        return None
    return max(0.0, min(1.0, number))


def heartbeat_job(
    conn: sqlite3.Connection, job_id: int, editor: str, machine: str,
    now: str | None = None, lease_seconds: float = JOB_LEASE_SECONDS,
    note: str | None = None, progress: Any = None,
) -> bool:
    """Extend a LIVE lease, and move a claim to `running`. -> did it happen.

    Deliberately NOT a re-claim (ytdl's heartbeat_download, and its reason):
    an expired lease is not extended here, because by then the job may have
    been re-queued and another machine may already be doing it. The companion
    is told the truth -- 410 -- and stops.
    """
    now = now or utcnow_iso()
    cur = conn.execute(
        """UPDATE jobs SET state=?, lease_expires_at=?, heartbeat_at=?,
                           updated_at=?, last_error=COALESCE(?, last_error),
                           progress=COALESCE(?, progress)
            WHERE id=? AND claimed_by=? AND claimed_machine=?
              AND state IN (?, ?) AND lease_expires_at > ?""",
        (JOB_RUNNING, _job_lease_until(now, lease_seconds), now, now, note,
         clamp_progress(progress),
         int(job_id), str(editor), str(machine), JOB_CLAIMED, JOB_RUNNING, now),
    )
    return bool(cur.rowcount)


def finish_job(
    conn: sqlite3.Connection, job_id: int, editor: str, machine: str,
    result: Mapping[str, Any] | None = None, now: str | None = None,
) -> bool:
    """Record a job DONE. -> did this caller still hold it.

    An expired lease may still finish a job: the work was done, the files are
    in the vault, and refusing the result would mean doing it twice. What an
    expired lease loses is the right to keep others off it, not the right to
    say what happened -- and the CAS on `state` stops a late finisher from
    overwriting a job another machine has since completed."""
    now = now or utcnow_iso()
    cur = conn.execute(
        """UPDATE jobs SET state=?, result_json=?, lease_expires_at=NULL,
                           heartbeat_at=?, updated_at=?
            WHERE id=? AND claimed_by=? AND claimed_machine=? AND state IN (?, ?)""",
        (JOB_DONE, _job_json(dict(result or {})), now, now,
         int(job_id), str(editor), str(machine), JOB_CLAIMED, JOB_RUNNING),
    )
    if cur.rowcount:
        # A machine that FINISHED one is not a machine to hold off from
        # (v45). The cooldown is about failure, and a success is the best
        # evidence there is that whatever went wrong last time is over.
        clear_machine_job_cooldown(conn, editor, machine)
    return bool(cur.rowcount)


def fail_job(
    conn: sqlite3.Connection, job_id: int, editor: str, machine: str,
    error: str = "", now: str | None = None, retryable: bool = True,
    cooldown_seconds: float = JOB_COOLDOWN_SECONDS, pin: bool = False,
) -> str | None:
    """One attempt failed. -> the job's new state, or None if this caller did
    not hold it.

    RETRY UNTIL THE BUDGET, THEN ABANDON. A job no machine can do must not
    ping-pong around the fleet for ever (§4.4 rule 5, and ytdl's breaker
    before it); a job that failed because one laptop went to sleep must not be
    lost. `retryable=False` is the runner saying the fault is in the JOB -- a
    folder with no audio in it -- which no number of machines will fix.
    """
    now = now or utcnow_iso()
    row = conn.execute(
        "SELECT kind, attempts FROM jobs WHERE id=? AND claimed_by=? "
        " AND claimed_machine=? AND state IN (?, ?)",
        (int(job_id), str(editor), str(machine), JOB_CLAIMED, JOB_RUNNING),
    ).fetchone()
    if row is None:
        return None
    attempts = int(row["attempts"] or 0) + 1
    spent = attempts >= job_retry_budget(row["kind"])
    state = (JOB_FAILED if not retryable
             else (_spent_state(row["kind"], pin) if spent else JOB_QUEUED))
    conn.execute(
        """UPDATE jobs SET state=?, attempts=?, last_error=?, claimed_by=NULL,
                           claimed_machine=NULL, lease_expires_at=NULL, updated_at=?
            WHERE id=? AND claimed_by=? AND claimed_machine=?""",
        (state, attempts, str(error or "")[:2000], now,
         int(job_id), str(editor), str(machine)),
    )
    # THE MACHINE IS LEFT ALONE FOR A WHILE (v45), but only when the fault
    # could be the machine's. `retryable=False` is the runner saying the
    # fault is in the JOB -- a clip with no audio track -- and cooling down a
    # good machine for a bad clip is how a fleet stops for a reason nobody
    # can see. A cancelled job comes back the same way, and must not punish
    # the machine that obeyed.
    if retryable and cooldown_seconds > 0:
        set_machine_job_cooldown(
            conn, editor, machine,
            f"job #{int(job_id)} ({row['kind']}) failed here: "
            f"{str(error or '')[:120]}", now, cooldown_seconds)
    return state


def expire_leases(
    conn: sqlite3.Connection, now: str | None = None, pin: bool = False,
    cooldown_seconds: float = JOB_COOLDOWN_SECONDS,
) -> list[dict[str, Any]]:
    """Re-queue (or abandon) every job whose holder has gone quiet.

    -> the jobs that moved, so the caller can log WHICH machine dropped what.
    An expiry COUNTS AS AN ATTEMPT: a machine that claims a job and dies three
    times running is a machine that cannot do it, and without the attempt the
    job would be re-offered to it for ever."""
    now = now or utcnow_iso()
    moved: list[dict[str, Any]] = []
    rows = conn.execute(
        "SELECT * FROM jobs WHERE state IN (?, ?) AND lease_expires_at IS NOT NULL "
        " AND lease_expires_at <= ?", (JOB_CLAIMED, JOB_RUNNING, now)).fetchall()
    for row in rows:
        attempts = int(row["attempts"] or 0) + 1
        spent = attempts >= job_retry_budget(row["kind"])
        state = _spent_state(row["kind"], pin) if spent else JOB_QUEUED
        cur = conn.execute(
            """UPDATE jobs SET state=?, attempts=?, claimed_by=NULL,
                               claimed_machine=NULL, lease_expires_at=NULL,
                               last_error=?, updated_at=?
                WHERE id=? AND state IN (?, ?) AND lease_expires_at <= ?""",
            (state, attempts,
             f"the lease held by {row['claimed_by']}/{row['claimed_machine']} "
             f"expired at {row['lease_expires_at']}", now,
             row["id"], JOB_CLAIMED, JOB_RUNNING, now),
        )
        if cur.rowcount:
            job = dict(row)
            job["state"] = state
            job["attempts"] = attempts
            moved.append(job)
            # A machine that went quiet mid-job gets the same cooldown a
            # machine that reported a failure does: it is the SAME evidence
            # (this computer did not finish what it took), and without it the
            # laptop that sleeps every evening is first in the queue for
            # every retry all night.
            if cooldown_seconds > 0 and row["claimed_machine"]:
                set_machine_job_cooldown(
                    conn, str(row["claimed_by"] or ""),
                    str(row["claimed_machine"]),
                    f"job #{row['id']} ({row['kind']}) lost its lease here",
                    now, cooldown_seconds)
    return moved


def machine_live_jobs(
    conn: sqlite3.Connection, editor: str, machine: str,
) -> list[dict[str, Any]]:
    """What this computer is holding right now. ONE AT A TIME is enforced on
    both sides: the runner refuses to claim a second, and the scheduler offers
    nothing to a machine that already holds one."""
    return [
        job_row(r) for r in conn.execute(  # type: ignore[misc]
            "SELECT * FROM jobs WHERE claimed_by=? AND claimed_machine=? "
            " AND state IN (?, ?) ORDER BY id",
            (str(editor), str(machine), JOB_CLAIMED, JOB_RUNNING))
    ]


# ------------------------------------------------------ backpressure (v45)
#
# THE QUEUE HAS TO BE ABLE TO PUSH BACK (phase 4, §4.4). Three separate
# brakes, because they answer three different runaways:
#
#   the fleet cap     how many jobs of one KIND may be in flight across the
#                     whole fleet at once. Not a per-machine limit (that is
#                     one, and always has been) -- this is the NAS's disk and
#                     the media share's bandwidth, which four simultaneous
#                     480p encodes reading rushes over SMB will find long
#                     before any one machine does.
#   the cooldown      how long a machine that just failed a job is left
#                     alone. Without it the machine with the broken ffmpeg is
#                     first in the queue for the retry, every time, because
#                     failing in two seconds is what keeps it idle.
#   the queue depth   what the companion is TOLD, so it can back off by
#                     itself: {queued, running, oldest_age_s} on the report
#                     reply.

def count_running_by_kind(conn: sqlite3.Connection) -> dict[str, int]:
    """kind -> how many are in flight on the fleet right now.

    Held states only. A PINNED job is deliberately not counted: it is not on
    anybody's machine, it is on this container's own worker, and letting it
    hold a fleet slot would be the dashboard blocking the fleet on work the
    fleet already refused."""
    return {row["kind"]: int(row["n"]) for row in conn.execute(
        "SELECT kind, COUNT(*) AS n FROM jobs WHERE state IN (?, ?) "
        " GROUP BY kind", JOB_HELD_STATES)}


def queue_depth(conn: sqlite3.Connection, now: str | None = None) -> dict[str, Any]:
    """{queued, running, pinned, oldest_age_s} -- the signal that rides the
    report reply so a companion can back off by itself.

    `oldest_age_s` is the number that matters and is null, never 0, on an
    empty queue: zero is "something arrived this second", and a companion
    that read the two the same way would treat an idle fleet as an urgent
    one.
    """
    now = now or utcnow_iso()
    counts: dict[str, int] = {}
    for row in conn.execute("SELECT state, COUNT(*) AS n FROM jobs "
                            " WHERE state NOT IN (%s) GROUP BY state"
                            % ",".join("?" * len(JOB_TERMINAL_STATES)),
                            JOB_TERMINAL_STATES):
        counts[str(row["state"])] = int(row["n"])
    oldest = conn.execute(
        "SELECT created_at FROM jobs WHERE state=? ORDER BY id ASC LIMIT 1",
        (JOB_QUEUED,)).fetchone()
    age: float | None = None
    if oldest is not None:
        try:
            age = max(0.0, (parse_iso(now)
                            - parse_iso(str(oldest["created_at"]))).total_seconds())
        except Exception:                                      # noqa: BLE001
            age = None
    return {
        "queued": counts.get(JOB_QUEUED, 0),
        "running": counts.get(JOB_CLAIMED, 0) + counts.get(JOB_RUNNING, 0),
        "pinned": counts.get(JOB_PINNED, 0),
        "oldest_age_s": None if age is None else round(age, 1),
    }


def set_machine_job_cooldown(
    conn: sqlite3.Connection, editor: str, machine: str, reason: str,
    now: str | None = None, seconds: float = JOB_COOLDOWN_SECONDS,
) -> str:
    """Leave this machine alone for a while. -> when it may claim again.

    Written even when the row does not exist yet (the UPDATE matches nothing
    and that is fine): a machine that has never reported is not being offered
    anything anyway."""
    now = now or utcnow_iso()
    until = _job_lease_until(now, seconds)
    conn.execute(
        "UPDATE machine_state SET jobs_cooldown_until=?, jobs_cooldown_reason=? "
        " WHERE editor_username=? AND machine=?",
        (until, str(reason or "")[:255], str(editor), str(machine)))
    return until


def clear_machine_job_cooldown(
    conn: sqlite3.Connection, editor: str, machine: str,
) -> None:
    """A machine that FINISHED a job is not a machine to hold off from. The
    cooldown is about failure, and letting a success clear it is what stops
    one bad clip from parking a good machine for two minutes."""
    conn.execute(
        "UPDATE machine_state SET jobs_cooldown_until=NULL, "
        "       jobs_cooldown_reason='' "
        " WHERE editor_username=? AND machine=?", (str(editor), str(machine)))


def machine_job_cooldown(
    conn: sqlite3.Connection, editor: str, machine: str,
) -> tuple[str, str]:
    """(until, reason) or ("", "")."""
    row = conn.execute(
        "SELECT jobs_cooldown_until, jobs_cooldown_reason FROM machine_state "
        " WHERE editor_username=? AND machine=?",
        (str(editor), str(machine))).fetchone()
    if row is None:
        return "", ""
    return (str(row["jobs_cooldown_until"] or ""),
            str(row["jobs_cooldown_reason"] or ""))


def fetch_running_jobs_map(
    conn: sqlite3.Connection,
) -> dict[tuple[str, str], dict[str, Any]]:
    """(editor, machine) -> the job that machine is holding, for the fleet
    grid's chip. The grid's other chips read machine_state; this one reads the
    queue, because a job is the SERVER's fact about a machine and not
    something the machine reports about itself."""
    out: dict[tuple[str, str], dict[str, Any]] = {}
    for r in conn.execute(
        "SELECT id, kind, state, claimed_by, claimed_machine, heartbeat_at, "
        "       lease_expires_at, inputs_json, progress FROM jobs "
        " WHERE state IN (?, ?) ORDER BY id", (JOB_CLAIMED, JOB_RUNNING)
    ):
        key = (r["claimed_by"] or "", r["claimed_machine"] or "")
        inputs = _job_loads(r["inputs_json"]) or {}
        fraction = clamp_progress(r["progress"])
        out[key] = {
            "id": r["id"], "kind": r["kind"], "state": r["state"],
            "label": job_label(r["kind"]),
            "at": r["heartbeat_at"], "lease_expires_at": r["lease_expires_at"],
            # None, never 0, when the runner cannot say -- the chip then shows
            # the job id instead of a percentage nobody measured.
            "percent": None if fraction is None else int(round(fraction * 100)),
            "rel_path": (str(inputs.get("rel_path") or "")
                         if isinstance(inputs, dict) else ""),
        }
    return out


# ------------------------------------------------- the pinned worker (v45)
#
# §4.4 rule 5: "N attempts, then mode_lock-style pinning to the NAS worker so
# a job that no machine can do does not ping-pong for ever". Phase 1 shipped
# the first half and wrote down why it could not ship the second: an
# abandoned job was visible, and there was no NAS-side executor to hand it
# to. Phase 3 built one -- the Timeline Cards engine runs IN THIS CONTAINER
# when /cards is mounted, with the vault and the footage share attached and
# its own single ffmpeg worker.
#
# THE PIN IS ONE-WAY. A pinned job never goes back to the fleet: `queued_jobs`
# only ever reads `queued`, so there is no path from here to an offer, and
# that is deliberate. The fleet has already spent the budget on it; putting it
# back would be the ping-pong the rule exists to end.
#
# The holder columns are re-used to mark "this container has it in hand"
# (PIN_HOLDER), so a restart mid-encode leaves a row that says WHO, and the
# same CAS discipline as a machine's claim decides between two ticks.

PIN_HOLDER = "(dashboard)"


def pinned_jobs(conn: sqlite3.Connection, limit: int = 50) -> list[dict[str, Any]]:
    """Pinned and not yet in hand, oldest first. The queue's own order
    (priority then age) does not apply: everything here has already waited
    through a whole retry budget."""
    return [job_row(r) for r in conn.execute(  # type: ignore[misc]
        "SELECT * FROM jobs WHERE state=? AND (claimed_machine IS NULL "
        "   OR claimed_machine='') ORDER BY id ASC LIMIT ?",
        (JOB_PINNED, max(1, min(int(limit), 500))))]


def take_pinned_job(
    conn: sqlite3.Connection, job_id: int, now: str | None = None,
) -> bool:
    """Mark a pinned job as in hand HERE. -> did this caller get it.

    A compare-and-set like every other write in this file, for the same
    reason: two ticks of the executor (a restarted thread, a second worker
    somebody adds later) must not both start the same ffmpeg."""
    now = now or utcnow_iso()
    cur = conn.execute(
        """UPDATE jobs SET claimed_by=?, claimed_machine=?, heartbeat_at=?,
                           updated_at=?
            WHERE id=? AND state=?
              AND (claimed_machine IS NULL OR claimed_machine='')""",
        (PIN_HOLDER, PIN_HOLDER, now, now, int(job_id), JOB_PINNED))
    return bool(cur.rowcount)


def pin_progress(
    conn: sqlite3.Connection, job_id: int, progress: Any = None,
    now: str | None = None,
) -> None:
    """How far through the pinned worker is. NO LEASE IS EXTENDED: this job
    is not on a lease, it is on this process, and inventing one would let
    expire_leases hand a job back to a fleet that already gave up on it."""
    now = now or utcnow_iso()
    conn.execute(
        "UPDATE jobs SET progress=COALESCE(?, progress), heartbeat_at=?, "
        "       updated_at=? WHERE id=? AND state=?",
        (clamp_progress(progress), now, now, int(job_id), JOB_PINNED))


def finish_pinned_job(
    conn: sqlite3.Connection, job_id: int, result: Mapping[str, Any] | None = None,
    now: str | None = None,
) -> bool:
    """The pinned worker finished it. -> did the row move.

    `done` and not a state of its own: the Timeline Cards client polling this
    row from another server has no idea which machine made the file, and
    should not have to -- the whole contract is "the row says done, now look
    on disk" (§7b.4)."""
    now = now or utcnow_iso()
    cur = conn.execute(
        """UPDATE jobs SET state=?, result_json=?, heartbeat_at=?, updated_at=?
            WHERE id=? AND state=?""",
        (JOB_DONE, _job_json(dict(result or {})), now, now,
         int(job_id), JOB_PINNED))
    return bool(cur.rowcount)


def fail_pinned_job(
    conn: sqlite3.Connection, job_id: int, error: str = "",
    now: str | None = None,
) -> bool:
    """The last executor failed it too. ABANDONED, always: there is nowhere
    else for it to go, and a pinned job that went back to the fleet would be
    the ping-pong rule 5 exists to end."""
    now = now or utcnow_iso()
    cur = conn.execute(
        """UPDATE jobs SET state=?, last_error=?, attempts=attempts+1,
                           claimed_by=NULL, claimed_machine=NULL, updated_at=?
            WHERE id=? AND state=?""",
        (JOB_ABANDONED, str(error or "")[:2000], now, int(job_id), JOB_PINNED))
    return bool(cur.rowcount)


def release_pinned_jobs(conn: sqlite3.Connection, now: str | None = None) -> int:
    """Put every in-hand pinned job back in the executor's queue. -> how many.

    Called at BOOT, not on a timer: a container that went down mid-encode
    leaves rows marked in-hand with nothing running, and the alternative to
    releasing them here is a job that is pinned for ever with no worker. The
    `.partial` discipline is what makes re-running one safe."""
    now = now or utcnow_iso()
    cur = conn.execute(
        "UPDATE jobs SET claimed_by=NULL, claimed_machine=NULL, updated_at=? "
        " WHERE state=? AND claimed_machine=?", (now, JOB_PINNED, PIN_HOLDER))
    return int(cur.rowcount or 0)


# ------------------------------------------------------------ cancel (v45)
#
# An admin can stop a job. What that MEANS depends on who has it, and the
# three answers are deliberately different:
#
#   queued    it is this row and nobody else's: it becomes `failed`, with the
#             admin's name in last_error, and it is never retried.
#   held      the machine holding it is the only thing that can stop it. The
#             row records the REQUEST, `commands.jobs.cancel` carries the id
#             on that machine's next report, and the companion kills its
#             child and posts failed(cancelled). Re-sent until the machine
#             answers -- the file_moves rule, because an admin clicking while
#             a laptop is asleep must not be a click that evaporates.
#   pinned    the dashboard's own executor is doing it; its should_stop()
#             reads the same flag on its next check.
#
# NOTHING HERE FORCES A ROW TERMINAL BEHIND A RUNNING PROCESS. A cancelled
# job whose machine never answers stays visible as "cancelling" until the
# lease expires, and the lease is what ends it. Lying about the state while
# an ffmpeg is still writing into the vault is how a half-made proxy gets
# published.

JOB_CANCELLED_ERROR = "cancelled"


def request_job_cancel(
    conn: sqlite3.Connection, job_id: int, by: str, now: str | None = None,
) -> str | None:
    """-> what happened: "failed" (it was queued and is over), "requested"
    (a machine or the pinned worker has to stop it), or None for a job that
    is already finished or does not exist."""
    now = now or utcnow_iso()
    job = get_job(conn, int(job_id))
    if job is None or job["state"] in JOB_TERMINAL_STATES:
        return None
    who = str(by or "an admin")[:64]
    if job["state"] == JOB_QUEUED:
        conn.execute(
            """UPDATE jobs SET state=?, last_error=?, cancel_requested_at=?,
                               cancel_requested_by=?, updated_at=?
                WHERE id=? AND state=?""",
            (JOB_FAILED, f"{JOB_CANCELLED_ERROR} by {who}", now, who, now,
             int(job_id), JOB_QUEUED))
        return JOB_FAILED
    conn.execute(
        """UPDATE jobs SET cancel_requested_at=?, cancel_requested_by=?,
                           updated_at=?
            WHERE id=? AND state IN (?, ?, ?)""",
        (now, who, now, int(job_id), JOB_CLAIMED, JOB_RUNNING, JOB_PINNED))
    return "requested"


def job_cancel_requested(conn: sqlite3.Connection, job_id: int) -> bool:
    """What the pinned executor's should_stop() asks."""
    row = conn.execute("SELECT cancel_requested_at FROM jobs WHERE id=?",
                       (int(job_id),)).fetchone()
    return bool(row is not None and row["cancel_requested_at"])


def pending_job_cancels(
    conn: sqlite3.Connection, editor: str, machine: str,
) -> list[int]:
    """The ids THIS machine is holding that an admin has asked to stop."""
    return [int(r["id"]) for r in conn.execute(
        "SELECT id FROM jobs WHERE claimed_by=? AND claimed_machine=? "
        "   AND state IN (?, ?) AND cancel_requested_at IS NOT NULL "
        " ORDER BY id", (str(editor), str(machine), JOB_CLAIMED, JOB_RUNNING))]


def prune_jobs(conn: sqlite3.Connection, now: str, max_age_days: int = 30) -> int:
    """Drop finished jobs older than `max_age_days`. -> how many went.

    Finished ONLY: a queued job nobody can run is the thing this whole phase
    exists to make visible, and pruning it would hide it."""
    cutoff = (parse_iso(now) - dt.timedelta(days=max(1, int(max_age_days)))).isoformat()
    cur = conn.execute(
        "DELETE FROM jobs WHERE state IN (%s) AND updated_at < ?"
        % ",".join("?" * len(JOB_TERMINAL_STATES)),
        (*JOB_TERMINAL_STATES, cutoff))
    return int(cur.rowcount or 0)




# ------------------------------------------------- machine capabilities (v42)
#
# What each computer can DO, flattened onto machine_state exactly as v20 did
# for b-roll ingest and for the same stated reason: the grid sorts and alarms
# on this, and a JSON blob cannot be asked "which machines have a GPU".
#
# WRITTEN WHOLESALE, never merged. `cap_at` is the marker: a report that
# carried the section replaces every column, and one that did not leaves them
# all alone. Merging would make "this machine no longer has a vault mounted"
# unsayable -- and a stale mount is how a job gets claimed by the one machine
# that cannot read a single file of it.

CAPABILITY_MOUNTS_MAX = 16


def store_machine_capabilities(
    conn: sqlite3.Connection, editor: str, machine: str,
    caps: Mapping[str, Any] | None, now: str,
) -> None:
    """The companion's `capabilities` section -> machine_state's flat columns.

    None (no section on this report) writes NOTHING: a companion too old to
    send one must not have its known hardware blanked, and an empty answer
    from a machine mid-restart must not take it off the offer list for a
    report interval.
    """
    if caps is None:
        return
    caps = dict(caps)
    resolve = caps.get("resolve") if isinstance(caps.get("resolve"), Mapping) else {}
    cards = caps.get("cards_agent") if isinstance(caps.get("cards_agent"), Mapping) else {}
    jobs_gate = caps.get("jobs_gate") if isinstance(caps.get("jobs_gate"), Mapping) else {}
    mounts = [str(m)[:32] for m in (caps.get("mounts") or [])][:CAPABILITY_MOUNTS_MAX]
    conn.execute(
        """UPDATE machine_state SET
             cap_at=?, cap_gpu_present=?, cap_gpu_name=?, cap_gpu_vram_gb=?,
             cap_nvenc=?, cap_ffmpeg=?, cap_ffprobe=?, cap_whisper=?,
             cap_whisper_detail=?,
             cap_claude=?, cap_mounts=?, cap_cpu_count=?, cap_idle_seconds=?,
             cap_load=?, cap_resolve_running=?, cap_resolve_project=?,
             cap_jobs_enabled=?, cap_job_kinds=?, cap_volunteer_until=?,
             cap_cards_connected=?, cap_cards_state=?,
             cap_cards_timeline=?, cap_cards_version=?, cap_cards_since=?,
             cap_cards_gate_state=?, cap_cards_detail=?,
             cap_cards_last_poll_at=?, cap_cards_http_status=?,
             cap_jobs_gate_reason=?, cap_jobs_gate_detail=?
            WHERE editor_username=? AND machine=?""",
        (now,
         int(bool(caps.get("gpu_present"))),
         str(caps.get("gpu_name") or "")[:128],
         caps.get("gpu_vram_gb"),
         int(bool(caps.get("nvenc"))),
         int(bool(caps.get("ffmpeg"))),
         int(bool(caps.get("ffprobe"))),
         int(bool(caps.get("whisper"))),
         str(caps.get("whisper_detail") or "")[:255],
         int(bool(caps.get("claude"))),
         json.dumps(mounts, separators=(",", ":")),
         caps.get("cpu_count"),
         # NULL means "this machine cannot tell", which every reader must
         # treat as NOT IDLE (idle.py's contract, carried end to end). It is
         # deliberately not coerced to 0: zero is "somebody is typing", and
         # the two must not become the same row.
         caps.get("idle_seconds"),
         caps.get("load"),
         int(bool((resolve or {}).get("running"))),
         str((resolve or {}).get("project") or "")[:255],
         int(bool(caps.get("jobs_enabled", True))),
         # THE MACHINE'S OWN ALLOW-LIST (v45, phase 4). NULL when the section
         # did not carry one, which is a companion older than phase 4 and
         # means ALL KINDS -- never "no kinds", which would silently take
         # every machine in the fleet out of the queue on the day the
         # dashboard is deployed ahead of the companions (the B16 shape).
         _job_kinds_json(caps.get("job_kinds")),
         # WHO SAID "GO AHEAD" (v46, section 10). A live value like
         # idle_seconds and NOT part of the companion's capability cache: a
         # deadline that went stale in a cache is a machine that keeps taking
         # work with somebody back at the keyboard. NULL is "not
         # volunteering", which is also what a companion older than 0.9.61
         # says by saying nothing at all.
         (str(caps.get("volunteer_until"))[:64]
          if caps.get("volunteer_until") else None),
         # The cards role (v44). Written wholesale like everything else here:
         # a companion that has STOPPED serving the page must be able to say
         # so, and a merge would leave the last timeline on the grid for ever.
         int(bool((cards or {}).get("connected"))),
         str((cards or {}).get("state") or "")[:32],
         str((cards or {}).get("timeline") or "")[:255],
         _as_int((cards or {}).get("version")),
         _as_float((cards or {}).get("since")),
         # RES-6 (2026-09-04): why it is in the state it is in. NULL rather
         # than "" when the companion did not say, so the grid can tell "this
         # build cannot answer" from "it answered with nothing".
         (str((cards or {}).get("gate_state"))[:32]
          if (cards or {}).get("gate_state") else None),
         (str((cards or {}).get("detail"))[:255]
          if (cards or {}).get("detail") else None),
         (str((cards or {}).get("last_poll_at"))[:64]
          if (cards or {}).get("last_poll_at") else None),
         _as_int((cards or {}).get("last_http_status")),
         # WHAT THIS MACHINE IS BUSY WITH ITSELF (CMEDIA-1, v50). The job
         # runner's gate answers `local_work` while a Qwen3-VL batch or a
         # proxy encode has the GPU, and nothing persisted it: the scheduler
         # ranked a saturated machine first on longest-idle, the job OOMed,
         # and the machine earned a cooldown for a fault it did not have.
         # NULL when the companion sent no `jobs_gate` (a build older than
         # the gate), which jobs.local_work_words reads as "did not say",
         # never as "idle".
         (str((jobs_gate or {}).get("reason"))[:32]
          if (jobs_gate or {}).get("reason") else None),
         (str((jobs_gate or {}).get("detail"))[:255]
          if (jobs_gate or {}).get("detail") else None),
         str(editor), str(machine)),
    )


def _capabilities_of(row: sqlite3.Row | None) -> dict[str, Any]:
    """One machine_state row -> the capabilities dict, or {}.

    Split out so the per-machine read and the whole-fleet map are ONE
    decoding: two of them is how "gpu_vram_gb" ends up a string in one place
    and a float in the other, and the scheduler compares it with >=."""
    if row is None or not row["cap_at"]:
        return {}
    try:
        mounts = json.loads(row["cap_mounts"]) if row["cap_mounts"] else []
    except (TypeError, ValueError):
        mounts = []
    return {
        "at": row["cap_at"],
        "gpu_present": bool(row["cap_gpu_present"]),
        "gpu_name": row["cap_gpu_name"] or "",
        "gpu_vram_gb": row["cap_gpu_vram_gb"],
        "nvenc": bool(row["cap_nvenc"]),
        "ffmpeg": bool(row["cap_ffmpeg"]),
        "ffprobe": bool(row["cap_ffprobe"]),
        "whisper": bool(row["cap_whisper"]),
        "whisper_detail": row["cap_whisper_detail"] or "",
        "claude": bool(row["cap_claude"]),
        "mounts": [str(m) for m in mounts] if isinstance(mounts, list) else [],
        "cpu_count": row["cap_cpu_count"],
        "idle_seconds": row["cap_idle_seconds"],
        "load": row["cap_load"],
        "jobs_enabled": bool(row["cap_jobs_enabled"]),
        # [] is "this machine did not say", which every reader must treat as
        # ALL KINDS (see _job_kinds_json).
        "job_kinds": _job_kinds_of(row["cap_job_kinds"]),
        # None is "not volunteering" (v46). The comparison against now lives
        # in jobs.is_volunteering and not here: this is a decoder.
        "volunteer_until": row["cap_volunteer_until"] or None,
        "resolve": {"running": bool(row["cap_resolve_running"]),
                    "project": row["cap_resolve_project"] or ""},
        # v44. `state` is meaningful with `connected` false and is the whole
        # value of the row: it names the refusal.
        # RES-6 (2026-09-04): the four fields beside `state` that say WHY.
        # None/"" is "this companion did not say", never "fine": a build too
        # old to send them renders as unknown on the grid.
        "cards_agent": {"connected": bool(row["cap_cards_connected"]),
                        "state": row["cap_cards_state"] or "",
                        "timeline": row["cap_cards_timeline"] or "",
                        "version": row["cap_cards_version"] or 0,
                        "since": row["cap_cards_since"],
                        "gate_state": _row_value(row, "cap_cards_gate_state") or "",
                        "detail": _row_value(row, "cap_cards_detail") or "",
                        "last_poll_at": _row_value(row, "cap_cards_last_poll_at"),
                        "last_http_status": _row_value(row, "cap_cards_http_status")},
        # CMEDIA-1 (v50). The shape jobs.local_work_words expects, and it is
        # read defensively there: only `local_work` refuses, an unknown
        # reason is not a refusal, and an absent one is a companion too old
        # to have the gate at all.
        "jobs_gate": {"reason": _row_value(row, "cap_jobs_gate_reason") or "",
                      "detail": _row_value(row, "cap_jobs_gate_detail") or ""},
    }


_CAPABILITY_COLUMNS = """cap_at, cap_gpu_present, cap_gpu_name, cap_gpu_vram_gb,
       cap_nvenc, cap_ffmpeg, cap_ffprobe, cap_whisper, cap_whisper_detail,
       cap_claude, cap_mounts, cap_cpu_count, cap_idle_seconds, cap_load,
       cap_resolve_running, cap_resolve_project, cap_jobs_enabled,
       cap_job_kinds, cap_volunteer_until,
       cap_cards_connected, cap_cards_state, cap_cards_timeline,
       cap_cards_version, cap_cards_since,
       cap_cards_gate_state, cap_cards_detail, cap_cards_last_poll_at,
       cap_cards_http_status,
       cap_jobs_gate_reason, cap_jobs_gate_detail"""


# A machine's allow-list is a handful of names; sixteen is already more kinds
# than this dashboard has ever had.
CAPABILITY_KINDS_MAX = 16


def _job_kinds_json(value: Any) -> str | None:
    """The `job_kinds` capability -> its column, or None for "not said".

    None and [] are the SAME ANSWER here on purpose (all kinds), because an
    editor's config with no `jobs_kinds` key and a companion too old to have
    one are the same machine as far as the fleet is concerned. The only way
    to be excluded from a kind is to name the kinds you do want.
    """
    if not value:
        return None
    try:
        names = [str(k)[:32] for k in list(value)][:CAPABILITY_KINDS_MAX]
    except TypeError:
        return None
    return json.dumps(names, separators=(",", ":")) if names else None


def _job_kinds_of(raw: Any) -> list[str]:
    try:
        names = json.loads(raw) if raw else []
    except (TypeError, ValueError):
        return []
    return [str(k) for k in names] if isinstance(names, list) else []


def machine_allows_kind(capabilities: Mapping[str, Any] | None, kind: str) -> bool:
    """May this machine be offered work of this kind? (v45, phase 4.)

    An EMPTY list is every kind: see _job_kinds_json. `jobs_enabled` is a
    different switch and is not read here -- the runner refuses everything
    when it is off, and the two answers must not be folded into one, because
    "this machine is out of the fleet" and "this machine does not do whisper"
    are different lines on the why page.
    """
    allowed = list((capabilities or {}).get("job_kinds") or [])
    return not allowed or str(kind) in allowed


def _as_int(value: Any) -> int | None:
    """A number a companion sent, or None. Never a string in a column the
    grid does arithmetic on."""
    try:
        return None if value is None else int(value)
    except (TypeError, ValueError):
        return None


def _as_float(value: Any) -> float | None:
    try:
        return None if value is None else float(value)
    except (TypeError, ValueError):
        return None


def machine_capabilities(
    conn: sqlite3.Connection, editor: str, machine: str,
) -> dict[str, Any]:
    """What this computer last told us it can do, or {} if it never has.

    {} is "unknown", which the scheduler reads as "offer it nothing that has
    a requirement" -- never as "it can do everything". A companion older than
    the capabilities section reports none, and must not be handed GPU work on
    the strength of a silence.
    """
    return _capabilities_of(conn.execute(
        f"SELECT {_CAPABILITY_COLUMNS} FROM machine_state "
        " WHERE editor_username=? AND machine=?",
        (str(editor), str(machine))).fetchone())


def fetch_capabilities_map(
    conn: sqlite3.Connection,
) -> dict[tuple[str, str], dict[str, Any]]:
    """(editor, machine) -> capabilities, for the fleet grid's chips.

    One query for the whole fleet: this builder runs every 15 s for every open
    fleet page (the same rule fetch_broll_ingest_map follows)."""
    return {
        (row["editor_username"], row["machine"]): _capabilities_of(row)
        for row in conn.execute(
            f"SELECT editor_username, machine, {_CAPABILITY_COLUMNS} "
            " FROM machine_state WHERE cap_at IS NOT NULL")
    }
