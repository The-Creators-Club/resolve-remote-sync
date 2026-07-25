# ccsync-dashboard

Fleet sync-status dashboard for Creators Club Sync. Runs on the NAS as a
TrueNAS custom app; shows every project (left sidebar), and per project every
editor's lane-C completion (%, files present vs total, exact missing-file
list from the server Syncthing's REST API) plus the lane A/B status each
editor's companion reports in. Tailnet-only, no login; the neon-red terminal
look matches the companion.

## Architecture

One FastAPI process (single uvicorn worker), three parts:

- **Collector** (`collector.py`) — in-process daemon thread polling the
  server Syncthing GUI API: `/rest/config` (folders/devices, 120s),
  `/rest/system/connections` (15s), `/rest/db/completion` per
  (folder × editor device) (30s), `/rest/db/remoteneed` for out-of-sync
  pairs (60s, capped at 500 files per pair with an honest "truncated"
  flag). Exponential backoff 15→300s when Syncthing is unreachable.
  When `DASH_PROJECTS_DIR` is set it also **auto-provisions** (300s): any
  `<year>/<series>/<project>` dir in that tree without a Syncthing folder
  gets one created (config identical to `server/setup_syncthing_folder.py`,
  duplicated in `provision.py`) and shared to every configured device.
  Existing folders are never modified.
- **SQLite** (`db.py`, `schema.sql`) — WAL mode, at `DASH_DB_PATH`.
  Current state plus 30 days of change-driven completion history
  (`should_snapshot` anti-bloat rules), pruned hourly. The collector is
  the only bulk writer; do not run more than one uvicorn worker.
- **Web** (`api.py`, `ui.py`) — JSON under `/api/v1/*`, server-rendered
  Jinja2 pages with vendored htmx polling for auto-refresh (detail 10s,
  sidebar 30s). `POST /api/v1/report` ingests companion lane reports,
  guarded by the `X-CCSync-Token` shared secret (`DASH_REPORT_TOKEN`).

Identity joins: Syncthing folder id = project slug (`server/common.py:
slugify`); Syncthing device name = TrueNAS username (via
`accept_device.py --device-name`); companion reports carry `editor_name`.
Devices not named after a username render as `[ UNMAPPED ]`.

## Env vars

| Var | Default | Notes |
|---|---|---|
| `SYNCTHING_GUI_URL` | — | e.g. `http://192.168.0.102:8384`; collector disabled if unset |
| `SYNCTHING_API_KEY` | — | same key the server scripts use |
| `DASH_DB_PATH` | `/data/dashboard.db` | SQLite file |
| `DASH_PORT` | `8480` | HTTP port |
| `DASH_REPORT_TOKEN` | — | shared secret for `POST /api/v1/report`; reports rejected if unset (set `DASH_REPORT_TOKEN_OPTIONAL=1` for lab use) |
| `DASH_PROJECTS_DIR` | `""` (off) | mounted Projects tree to scan for auto-provisioning (`/projects` in the app) |
| `DASH_PACKAGES_DIR` | `""` (= `<db dir>/packages`) | published companion builds (upgrade channel); default lands under `/data`, the persistent volume — only set to move them |
| `DASH_SYNCTHING_DATA_PREFIX` | `/data/Projects` | where the *Syncthing app* sees the same tree (folder `path` prefix for created folders) |
| `DASH_SESSION_SECRET` | `""` (login off) | HMAC secret for session cookies; keep stable across deploys |
| `DASH_ADMIN_USERS` | `""` | csv usernames who may manage anyone's project ticks (must be SMB-authable accounts) |
| `DASH_AUTH_METHOD` | `smb` | credential verification method; `smb` = SMB session probe on :445 (only method 25.10 allows for non-admin users) |
| `DASH_SMB_HOST` | `192.168.0.102` | host for the SMB auth probe |
| `DASH_INTERVAL_ENFORCE` | `60` | seconds between share-enforcement reconciliations |
| `TRUENAS_HOST` | `192.168.0.102` | backs the admin `/admin/users` section (create editor accounts, approve devices, set passwords) |
| `TRUENAS_USER` | `truenas_admin` | same |
| `TRUENAS_PW` | `""` (section off) | same -- leaving this unset disables only `/admin/users`, nothing else |

Selection model: editors log in (TrueNAS credentials), tick projects; the
`selections` table is the authority for which editor devices each Syncthing
folder is shared to (`enforce` collector cycle, first run seeds from
existing shares). New folders auto-provision unshared. The companion fetches
`GET /api/v1/selection/{editor}` (token auth) and syncs the queue one
project at a time; `queue`/`current_project`/per-lane progress come back in
its reports and render in MY QUEUE with speed + ETA.

## Run locally

```
python -m venv .venv && .venv/Scripts/pip install -e .[dev]
.venv/Scripts/python -m pytest                       # 31 tests, no network
SYNCTHING_GUI_URL=http://192.168.0.102:8384 SYNCTHING_API_KEY=... \
    .venv/Scripts/python -m ccsync_dashboard.collector --once --db ./dev.db
DASH_DB_PATH=./dev.db DASH_REPORT_TOKEN_OPTIONAL=1 \
    .venv/Scripts/python -m uvicorn --factory ccsync_dashboard.app:create_app --port 8480
```

## Deploy

`python server/install_dashboard_app.py` (see `docs/SERVER.md`). Manual
fallback: paste `deploy/compose.yaml` into TrueNAS UI > Apps > Install via
YAML. Redeploys re-upload `app/` and never touch `data/`.
