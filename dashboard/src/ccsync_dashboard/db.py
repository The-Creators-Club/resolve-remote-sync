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
import unicodedata
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


def record_file_move(
    conn: sqlite3.Connection, *, from_slug: str, from_project_rel: str, from_rel: str,
    to_slug: str, to_project_rel: str, to_rel: str, is_dir: bool, proxies_moved: int,
    requested_by: str, now: str, targets: list[tuple[str, str]],
) -> int:
    """The server-side move has already happened; this is the record of it
    and the list of computers that still have to follow. Returns the id."""
    cur = conn.execute(
        """INSERT INTO file_moves
             (from_slug, from_project_rel, from_rel, to_slug, to_project_rel, to_rel,
              is_dir, proxies_moved, requested_by, requested_at)
           VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
        (from_slug, from_project_rel, from_rel, to_slug, to_project_rel, to_rel,
         int(bool(is_dir)), int(proxies_moved), requested_by, now),
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
        stamp = dt.datetime.now(dt.timezone.utc)
    return (stamp - dt.timedelta(days=max_age_days)).isoformat()


def pending_file_moves(
    conn: sqlite3.Connection, editor: str, machine: str, now: str,
    max_age_days: int = FILE_MOVE_MAX_AGE_DAYS, limit: int = FILE_MOVE_COMMAND_LIMIT,
) -> list[dict[str, Any]]:
    """The moves this computer has not yet reported applying, oldest first.

    Bounded in TIME as well as count: a machine that was off for a month
    must not come back and shuffle files that have been shuffled again since
    -- and the companion refuses a move whose source is not where the
    command says anyway, so an expired one costs nothing but a log line."""
    cutoff = _file_move_cutoff(now, max_age_days)
    rows = conn.execute(
        """SELECT m.id, m.from_slug, m.from_project_rel, m.from_rel,
                  m.to_slug, m.to_project_rel, m.to_rel, m.is_dir,
                  m.requested_by, m.requested_at
             FROM file_move_targets t JOIN file_moves m ON m.id = t.move_id
            WHERE t.editor_username=? AND t.machine=? AND t.applied_at IS NULL
              AND m.requested_at >= ?
            ORDER BY m.id LIMIT ?""",
        (editor, machine, cutoff, limit),
    ).fetchall()
    return [dict(r) for r in rows]


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
    ok: bool, detail: str | None, now: str,
) -> bool:
    """The machine's answer. A FAILED move is applied too, in the sense that
    the machine has answered and the command stops: the detail is on the
    project page for the admin, and the fix is a human's (the local file is
    still where it was, which is the one outcome that loses nothing)."""
    cur = conn.execute(
        """UPDATE file_move_targets SET applied_at=?, ok=?, detail=?
            WHERE move_id=? AND editor_username=? AND machine=? AND applied_at IS NULL""",
        (now, int(bool(ok)), (detail or "")[:512] or None, move_id, editor, machine),
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
        move["targets"] = [dict(r) for r in conn.execute(
            """SELECT editor_username, machine, delivered_at, applied_at, ok, detail
                 FROM file_move_targets WHERE move_id=?
                ORDER BY editor_username, machine""",
            (move["id"],),
        )]
        move["waiting"] = sum(1 for t in move["targets"] if not t["applied_at"])
        move["failed"] = sum(1 for t in move["targets"] if t["applied_at"] and not t["ok"])
    return moves


def copy_machine_plan(
    conn: sqlite3.Connection, editor: str, source: str, target: str,
    copied_by: str, now: str,
) -> int:
    """Give `target` the same projects as `source`, replacing whatever it
    had. Returns how many projects it now holds.

    A new computer starts with an EMPTY plan on purpose (the plan doc's §3.2:
    inheritance would silently start a 50 GB download on a laptop nobody
    asked to fill). This is the affordance that makes that bearable -- the
    admin's "same as the desktop, please" in one click."""
    rows = selections_for_machine(conn, editor, source)
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
    conn: sqlite3.Connection, editor: str, old_machine: str, new_machine: str
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
    the safe direction."""
    if not old_machine or not new_machine or old_machine == new_machine:
        return False
    taken = conn.execute(
        "SELECT 1 FROM machines WHERE editor_username=? AND machine=?",
        (editor, new_machine),
    ).fetchone()
    if taken is not None:
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
    the laptop" impossible to express."""
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
    moment a caller asked for full ticks only."""
    wanted = set(sync_modes) if sync_modes else None
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
                      restarts_count_24h, restarts_last_at, restarts_last_error
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
    # Audited HERE rather than at the two call sites (SYS-11, 2026-08-28): the
    # JSON route and the Users page both pass their admin through this one
    # function, and a ledger the second door can skip is worse than none.
    audit(conn, by, "fleet.halt_set" if active else "fleet.halt_clear",
          "fleet", {"reason": state["reason"]}, now=state["set_at"])
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
        conn.execute(
            "DELETE FROM machines WHERE editor_username=? AND machine=?",
            (editor, machine),
        )
    return len(victims)


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
