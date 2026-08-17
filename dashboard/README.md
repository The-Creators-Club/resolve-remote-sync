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

- **NAS seam** (`nas/`) — `base.py` is the `NasBackend` Protocol and
  `NasError`; `truenas.py` is today's TrueNAS client (moved from
  `truenas_client.py`, which is now an import shim kept for one release);
  `synology.py` is the DSM 7.2+ client (WP2, live-verified 2026-08-17);
  `factory.py` picks one from `DASH_NAS_KIND`.
  `api.py`/`ui.py` name no backend — see `docs/SYNOLOGY_PORT_PLAN.md`.

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
| `DASH_SMB_HOST` | `""` | host for the SMB auth probe. **No default since 2026-08-17** -- see "Site identity" below |
| `DASH_INTERVAL_ENFORCE` | `60` | seconds between share-enforcement reconciliations |
| `DASH_NAS_KIND` | `truenas` | which NAS backend the admin section provisions against: `truenas` or `synology` (see below). An unknown value is refused, never guessed |
| `DASH_NAS_HOST` | `""` | backs the admin `/admin/users` section (create editor accounts, approve devices, set passwords) |
| `DASH_NAS_USER` | `""` | same |
| `DASH_NAS_PW` | `""` (section off) | same -- leaving this unset disables only `/admin/users`, nothing else |
| `DASH_NAS_VERIFY_SSL` | `0` | verify the NAS's TLS cert on those calls; `1`, or a path to a CA bundle inside the container |
| `TRUENAS_HOST` / `TRUENAS_USER` / `TRUENAS_PW` / `TRUENAS_VERIFY_SSL` | — | the previous spelling of the four above, still honoured **for one release** (SYNOLOGY_PORT_PLAN.md WP1, 2026-08-17). `DASH_NAS_*` wins when both are set |
| `DASH_NAS_SSH_PORT` | `22` | Synology only: DSM's SSH port, for the half of provisioning that has no API |
| `DASH_NAS_SSH_HOSTKEY` | `""` | Synology only: the NAS's SSH host key (`ssh-keyscan -t ed25519 <nas>` output, with or without the type prefix). Unset = trust on first use, with a WARNING per connection |
| `DASH_NAS_SSH_KEY_PROBE` | `1` | Synology only: let `/admin/users` open one SSH session per render to answer "does this editor have a key installed". `0` turns it off; the column then reads as no key |

### Synology (DSM 7.2+)

`DASH_NAS_KIND=synology` points the admin Users section at DSM's web API on
`https://<nas>:5001` instead of TrueNAS's REST API. Set `DASH_NAS_USER` to a
DSM account in `administrators` **with 2FA off**, and install the extra:
`pip install 'ccsync-dashboard[synology]'` (paramiko; the container needs it
in `deploy/requirements.txt`).

What it does per editor: `SYNO.Core.User create` (DSM's default shell is
`/sbin/nologin`, which is what we want), `SYNO.Core.Group.Member add` to
`editors` **with a read-back**, then SSH to write
`/var/services/homes/<u>/.ssh/authorized_keys` — DSM has no API for that, and
a file written through FileStation is owned by the admin, which sshd's
StrictModes silently refuses.

Three things it will not do, each because the hardware said so
(`docs/synology-spikes-2026-08-17.md`):

- **it never chmods a home or anything under a shared folder.** `chmod` on a
  Synology path DELETES the ACL (`Archive: None`, "It's Linux mode"), and
  DSM's sftp runs with umask 000 — the two together leave every new file
  world-writable. Only `~/.ssh` and `authorized_keys` are chmodded, which is
  what sshd reads. Repair a chmodded path with
  `synoacltool -enforce-inherit`, never with another chmod.
- **it refuses a DSM whose `SYNO.API.Auth` tops out below version 7.** A v6
  sid reads fine and is refused (105) on every mutation, so such a box
  produces accounts that exist, are in no group and have no key.
- **it refuses to adopt an account it did not create** — a built-in
  (`admin`, `guest`, `root`), a package account (`sc-*`, uid ≥ 170000), a uid
  below 1024, or an existing account that is not already in `editors`.

Prerequisites on the NAS: SSH enabled, the **User Home** service on (no home,
nowhere to put a key), and the **SFTP service** on — with SFTP off, an
editor's key authenticates and the channel is then closed, and DSM logs
nothing at all. `SynologyClient.sftp_enabled()` answers the last one.
`SYNO.SFTP` is an application privilege that is granted by default; only an
explicit deny matters.

### Site identity

Blanked 2026-08-17 (COMMERCIAL_READINESS.md item 10 / SYNOLOGY_PORT_PLAN.md
WP0): `DASH_SMB_HOST`, `DASH_NAS_HOST` and `DASH_NAS_USER` used to default to
*this* fleet's NAS, so a second deployment silently inherited it. They now
default to `""`, and `Settings.from_env` logs one WARNING naming whichever is
unset. It is a warning, not a refusal to start: the dashboard is what tells
everyone whether their footage is syncing, and it does that with no NAS
credentials at all -- only editor login (the SMB probe) and `/admin/users`
need these.

### Site manifest (`GET /api/v1/site`)

Read-only, unauthenticated, no secrets -- the installer, the onboarding wizard
and the companion all read it before (or without) a login, exactly as they do
`/api/v1/health`. Every value defaults to `""` so an unconfigured deployment
says "I have not been told" rather than handing out another site's addresses.
`nas_syncthing_id` prefers the live Syncthing's `myID` over the env var (a
regenerated Syncthing config changes it); `template_folders` and
`shared_asset_folders` come from `provision.py`, so they cannot drift from
what `/project-setup` creates.

| Var | Default | Response key |
|---|---|---|
| `DASH_SITE_ORG_NAME` | `""` | `org_name` |
| `DASH_SITE_TREE_NAME` | `""` | `tree_name` |
| `DASH_SITE_CANONICAL_PREFIX` | `P:\` | `canonical_prefix` (the editor drive letter, hardcoded by decision 2026-07-26) |
| `DASH_SITE_REMOTE_ROOT` | `""` | `remote_root` (e.g. `/mnt/tank/TheCreatorsPool/Creators_Club`) |
| `DASH_SITE_SMB_UNC` | `""` | `smb_unc` -- the companion reads this into `server_p_unc` instead of deriving it |
| `DASH_SITE_SFTP_HOST` | `""` | `sftp_host` |
| `DASH_SITE_SFTP_PORT` | `22` | `sftp_port` (DSM often moves sshd) |
| `DASH_SITE_SFTP_CHUNK_SIZE` | `""` | `sftp_chunk_size` — rclone chunk size the NAS's sshd tolerates; Synology (OpenSSH 8.2) needs `64Ki`, TrueNAS takes `255Ki`; blank = companion default |
| `DASH_SITE_SFTP_CONCURRENCY` | `0` | `sftp_concurrency`; 0 = companion default |
| `DASH_SITE_SFTP_SHELL_TYPE` | `""` | `sftp_shell_type` for the rclone remote: `unix` on TrueNAS, `none` on Synology (nologin editors); blank = installer default `unix` |
| `DASH_SITE_RCLONE_REMOTE` | `""` | `rclone_remote` |
| `DASH_SITE_NAS_SYNCTHING_ID` | `""` | `nas_syncthing_id` (fallback only; live value wins) |
| `DASH_SITE_DASHBOARD_URL` | `""` | `dashboard_url` (trailing slash stripped) |

The response also carries `schema` (currently `1` -- bump it, never reshape in
place: clients on three OSes upgrade at their own pace) and `nas_kind`.

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
