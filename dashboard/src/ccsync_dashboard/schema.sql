-- Creators Club Sync dashboard schema, version 1.
-- Timestamps are ISO 8601 UTC strings ("2026-07-24T12:00:00+00:00");
-- the fixed format makes lexicographic comparison correct in SQL.

CREATE TABLE IF NOT EXISTS projects (
  id INTEGER PRIMARY KEY,
  slug TEXT NOT NULL UNIQUE,          -- syncthing folder id, e.g. '2025-ff4-nuclear'
  label TEXT NOT NULL,                -- folder label = rel path, e.g. '2025/FF4/Nuclear'
  path TEXT NOT NULL,                 -- server-side folder path
  first_seen TEXT NOT NULL,
  last_seen TEXT NOT NULL,
  active INTEGER NOT NULL DEFAULT 1   -- 0 when the folder disappears from /rest/config
);

CREATE TABLE IF NOT EXISTS devices (
  id INTEGER PRIMARY KEY,
  device_id TEXT NOT NULL UNIQUE,     -- syncthing device ID
  name TEXT NOT NULL,
  editor_username TEXT,               -- NULL = unmapped (device not named after a username)
  is_server INTEGER NOT NULL DEFAULT 0,
  first_seen TEXT NOT NULL,
  last_seen TEXT NOT NULL,
  connected INTEGER NOT NULL DEFAULT 0,
  address TEXT,
  last_connected_at TEXT
);

-- Current lane-C completion, one row per (project, device); upserted every cycle.
CREATE TABLE IF NOT EXISTS completion_current (
  project_id INTEGER NOT NULL REFERENCES projects(id),
  device_id INTEGER NOT NULL REFERENCES devices(id),
  completion REAL NOT NULL,           -- 0..100
  need_items INTEGER NOT NULL,
  need_bytes INTEGER NOT NULL,
  need_deletes INTEGER NOT NULL,
  global_items INTEGER,               -- folder totals, for "has X of Y"
  global_bytes INTEGER,
  updated_at TEXT NOT NULL,
  PRIMARY KEY (project_id, device_id)
);

-- History, appended only on meaningful change (see db.should_snapshot).
CREATE TABLE IF NOT EXISTS completion_history (
  id INTEGER PRIMARY KEY,
  project_id INTEGER NOT NULL,
  device_id INTEGER NOT NULL,
  ts TEXT NOT NULL,
  completion REAL NOT NULL,
  need_items INTEGER NOT NULL,
  need_bytes INTEGER NOT NULL
);
CREATE INDEX IF NOT EXISTS ix_hist ON completion_history(project_id, device_id, ts);

-- Bounded per-editor missing-file cache; wholesale-replaced per refresh.
CREATE TABLE IF NOT EXISTS missing_files (
  project_id INTEGER NOT NULL,
  device_id INTEGER NOT NULL,
  name TEXT NOT NULL,
  size INTEGER,
  truncated INTEGER NOT NULL DEFAULT 0,  -- 1 on every row of a capped listing
  refreshed_at TEXT NOT NULL,
  PRIMARY KEY (project_id, device_id, name)
);

-- Companion-reported lane status (lanes A/B, plus the editor's local view of C).
CREATE TABLE IF NOT EXISTS lane_report_current (
  editor_username TEXT NOT NULL,
  machine TEXT NOT NULL,
  lane TEXT NOT NULL,
  state TEXT NOT NULL,                -- idle | syncing | error | paused
  queued INTEGER,
  transferring INTEGER,
  last_error TEXT,
  last_sync TEXT,
  detail TEXT,
  companion_version TEXT,
  reported_at TEXT NOT NULL,          -- client clock, informational only
  received_at TEXT NOT NULL,          -- server clock; all freshness logic uses this
  PRIMARY KEY (editor_username, machine, lane)
);

CREATE TABLE IF NOT EXISTS lane_report_history (
  id INTEGER PRIMARY KEY,
  editor_username TEXT NOT NULL,
  machine TEXT NOT NULL,
  lane TEXT NOT NULL,
  state TEXT NOT NULL,
  queued INTEGER,
  last_error TEXT,
  ts TEXT NOT NULL
);

-- Collector run log; drives the "SYNCTHING UNREACHABLE" banner.
CREATE TABLE IF NOT EXISTS poll_runs (
  id INTEGER PRIMARY KEY,
  kind TEXT NOT NULL,                 -- config | connections | completion | remoteneed
  started_at TEXT NOT NULL,
  finished_at TEXT,
  ok INTEGER,
  error TEXT
);
