# Configuration reference

Every knob in CC Sync, in one place: the site manifest, the dashboard's
environment, the companion's `config.toml`, and the indexers' environment.

Written 2026-08-17 (`COMMERCIAL_READINESS.md` item 13). Read
[`INSTALL.md`](INSTALL.md) first if you are setting a deployment up — this is
the lookup table, not the walkthrough.

**Legend:** **R** required · **S** secret (never in a file the repo tracks) ·
**F** feature-gated (does nothing unless the feature is on) · *(blank)* optional.

---

## 1. `site.toml` — who this deployment is

**Where the loader lives:** `server/common.py`, functions `load_site()` and
`site_value()`. The annotated source of truth is
[`../site.example.toml`](../site.example.toml) — copy it, do not retype it.

**File search order:** `--site <path>` → `$CCSYNC_SITE` → `<repo>/site.toml`.
**Value search order:** the script's own flag → its environment variable →
this file → **a refusal that names the key**. It never falls back to another
site's value.

**No secrets in this file.** It is meant to be readable, diffable, and (if you
like) committed. Passwords, API keys and tokens live in the environment —
[§2.1](#21-secrets) and [`SECRETS.md`](SECRETS.md).

There is no machine validator today. A script that needs a key and cannot find
it stops and names it; that is the enforcement.

### `[nas]`

| Key | Default | Flag / env | Notes |
|---|---|---|---|
| `kind` | `truenas` | `--nas-kind` / `CCSYNC_NAS_KIND` | **R** in effect. `truenas` or `synology`. An unknown value is refused, never guessed |
| `host` | — | `TRUENAS_HOST` | **R**. LAN or tailnet address |
| `admin_user` | — | `TRUENAS_USER` | **R**. TrueNAS: `truenas_admin`. DSM: a member of `administrators`, **2FA off** (SSH is admin-only there) |
| `verify_ssl` | `"0"` | `TRUENAS_VERIFY_SSL` / `SYNO_VERIFY_SSL` | `"0"` trusts a self-signed cert — the out-of-box state of both platforms, **and warned about on every run since 2026-08-17**, because these calls carry the admin password. Point it at a CA bundle once the NAS has a real certificate |
| `ssh_hostkey` | — | `--host-key` / `CCSYNC_SSH_HOSTKEY` | Effectively **R**. An unpinned host not already in `~/.ccsync/known_hosts` is refused; use `--trust-host-key-on-first-use` (or `CCSYNC_SSH_TRUST_ON_FIRST_USE=1`) exactly once. A key that *changes* is always a refusal |

### `[tree]`

| Key | Default | Notes |
|---|---|---|
| `pool_root` | — | **R**. TrueNAS `/mnt/<pool>/<dataset>`, Synology `/volume<N>/<share>` |
| `tree_name` | — | **R**. The tree's own directory name — what an editor sees as `P:\` |
| `projects_dir` | `Projects` | The subdirectory holding projects. Everything else (`Assets/Luts`, `Assets/Stills`, `Assets/B-roll Archive`, `Assets/Music`) is **fixed by the product** |
| `template_folders` | product default | Subfolders every new project gets. Set here and the same list reaches `setup_tree.py`, the dashboard's create-project flow **and** `GET /api/v1/site` |
| `shared_assets` | `["Assets/Luts", "Assets/Stills"]` | Libraries shared with every editor automatically, no tick required. The Syncthing folder id is the slugified rel path |
| `homes_parent` | `<pool_root>/homes` | Where editor **home directories** live — the parent, never one editor's home. DSM: `/var/services/homes`. Not cosmetic: sshd's `StrictModes` decides whether an editor's key works at all |
| `share_name` | — | **R**. The SMB share name |
| `smb_unc` | — | **R**. The UNC path editors map as `P:`. Served rather than derived — the derivation only works on TrueNAS |

### `[apps]`

| Key | Default | Notes |
|---|---|---|
| `root` | — | **R**. Where the dashboard's host tree lives. Everything under `<root>/app` is **replaced as root on every deploy**, so the backend refuses a root that does not match its expected shape |

### `[net]`

| Key | Default | Notes |
|---|---|---|
| `dashboard_url` | — | **R**. Where editors reach the dashboard. `check_health.py` checks it; it goes into each editor's config |
| `bind_lan`, `bind_tailnet` | — | **R on TrueNAS.** The interfaces the container publishes on — **never `0.0.0.0`**. Both must be addresses the NAS actually has or Docker refuses to start the app, asynchronously, long after the deploy returns. **Leave unset on Synology**: the stack binds 127.0.0.1 and Tailscale Serve publishes it |
| `sftp_port` | `22` | Lanes A/B |
| `sftp_chunk_size` | `255Ki` | **Synology MUST set `64Ki`.** Measured 2026-08-17: at 255Ki on DSM 7.2.1 (OpenSSH 8.2p1) a download **truncates at 539,000,832 bytes and rclone reports success**. The server has no `limits@openssh.com`, so the client never learns the cap. Anything under OpenSSH 8.5 has the same hole |
| `sftp_concurrency` | `64` | Synology: `16` |
| `sftp_host` | *(unset)* | **Leave unset on a dual-homed site** — the wizard then uses the host of whichever dashboard URL the editor reached. Set it only to a name reachable from everywhere (MagicDNS / DNS), never a LAN IP |
| `rclone_remote` | `ccsync_sftp` | The remote *name* in each editor's `rclone.conf` |
| `shell_type` | `unix` | rclone's shell probing. **Ignored and forced to `none`** whenever `[stack] editor_shell = "sftp-only"` — a nologin editor cannot run `md5sum` whatever this says, and the two disagreeing is what produces "failed to calculate hash" on every pass |

### `[syncthing]`

| Key | Default | Notes |
|---|---|---|
| `gui_url` | — | The GUI **as seen from the dashboard container** (the NAS's own LAN address works; `localhost` does not) |
| `gui_bind` | *(unset)* | Which host address the GUI is published on. It is an **unauthenticated admin surface over every folder in the fleet** — bind it to one address, or to `127.0.0.1` and reach it by SSH tunnel. Then run `server/secure_syncthing_gui.py` |
| `device_id` | `""` | The NAS's Syncthing device ID (Actions ▸ Show ID). Fallback only: the live value read from Syncthing wins |

### `[site]`

| Key | Default | Notes |
|---|---|---|
| `org_name` | `""` | **Your** name — the dashboard topbar and the companion's tray |
| `org_short` | `""` | The same name where only a few characters fit. Blank = use `org_name` |
| `product_name` | `CC Sync` | **The vendor's** product name — the one brand string here with a non-blank default, because every deployment runs the same software. Set it only if you resell |
| `brand_logo` | `""` | **Your logo** in every editor's tray and window title bar. Blank wears the product's own mark. A bare name selects a mark the companion build already ships (`cc_mark_white.png`); anything with a separator is an absolute path on the **editor's** machine. Must be **white on transparent** — the tray tints it red/amber/green to carry sync status, so a pre-coloured logo renders as a solid blob. Per machine, `$CCSYNC_BRAND_LOGO` overrides it |
| `canonical_prefix` | `P:\` | The drive letter editors map the tree as. Hardcoded by decision (2026-07-26); published so no client has to assume it |

### `[features]`

| Key | Default | Notes |
|---|---|---|
| `youtube_download` | `false` | **F**. The `/ytdl` page. Off means the mount does not exist, the fleet routes 404, and companions hide their YouTube items. A legal decision, not a technical one — [`legal/YOUTUBE_FEATURE_NOTICE.md`](legal/YOUTUBE_FEATURE_NOTICE.md) |
| `youtube_unblock` | `false` | **F**. The PO-token provider, the deno n-challenge solver, the cookie sign-in. **The vendor build ships none of them installed.** Requires `youtube_download`; alone it does nothing and the manifest will not report it true |

### `[indexer]`

| Key | Default | Notes |
|---|---|---|
| `model_tier` | `good` | **F**-shaped (validated, not feature-gated). Which LOCAL vision model the b-roll indexer loads: `good` (Qwen3-VL 4B — needs an NVIDIA GPU with 8 GB VRAM, or Apple Silicon with 16 GB; ~20 s/clip on an RTX 3080) or `best` (Qwen3-VL 8B — needs 12 GB VRAM, or Apple Silicon with 24 GB; sharper on-screen text and vocabulary, ~2× slower). Chosen on **Settings** by how much VRAM the indexing machine has, published at `GET /api/v1/site` as `indexer.model_tier`; the indexer's own `config.toml` can override it per machine. An unrecognised value is refused on write (`site_store.SiteValidationError`), and falls back to `good` if it somehow reaches the manifest anyway |

### `[stack]`

| Key | Default | Notes |
|---|---|---|
| `uid`, `gid` | `3000`, `3001` | What the container runs as. DSM assigns ≥ 1026 — read the real values with `id <user>` there rather than assuming |
| `owner`, `group` | `broll`, `editors` | Their names, used for `chown -R` on the tree |
| `editor_shell` | `sftp-only` | `sftp-only` (nologin + an sshd `Match Group` block with `ForceCommand internal-sftp` and no password auth) or `shell`. Changing it changes what the manifest publishes as `sftp_shell_type`; redeploy afterwards. Migration: `setup_editor_account.py --migrate-existing [--apply]` |
| `project_acl` | `shared` | `shared` = one `editors` group, 2770 everywhere: **every editor can read, write and delete every other editor's project**. `per-project` adds a `proj-<slug>` group per project plus sticky bits. Read [`TENANCY.md`](TENANCY.md) first — it changes an existing tree. **This is not the multi-org switch** |

### 1.1 Appliance mode (`ZERO_TOUCH_PLAN.md` WP D, 2026-08-17): the manifest moves into the database

For a customer with no `site.toml` and no shell — the appliance bar §1 of
that plan is judged against — two things in this section stop being true.

**The site manifest is DB-first.** `GET /api/v1/site` used to republish
`DASH_SITE_*` verbatim; it now reads a `site_settings` table (`db.py`
migration v18) via `dashboard/src/ccsync_dashboard/site_store.py`, and per
key the precedence is **the DB row if one exists, else the `DASH_SITE_*`
value, else the built-in default**. The table starts empty, so this is
invisible to every deployment that already sets `DASH_SITE_*` in its compose
env (`tests/test_site.py` pins the response of an env-only app
byte-for-byte). On first boot, if the table is empty AND the process
environment carries any `DASH_SITE_*` variable, those values are copied into
the table once (`site_store.seed_from_env_once`, called from `app.py`'s
lifespan) — **after that the database is authoritative**: a later change to
the container's `DASH_SITE_*` env is not picked up automatically, on purpose
(the same "wrong-tenant support incident" this route already warns about,
just moved from "another site's value" to "a stale value from six deploys
ago"). Edit the manifest from **Settings** (`/admin/settings`,
admin-only) instead, which calls `PUT /api/v1/admin/site` — no `--recreate`
needed. **Settings → Export** produces `site.toml`-shaped text (same section
names as `site.example.toml`) for a NAS migration or a backup; **Import**
parses a pasted one back in. Which fields are auto-derived once WP B
(Tailscale sidecar) and WP C (SFTP sidecar) land — `dashboard_url`,
`sftp_host`, `nas_syncthing_id` — is `site_store.AUTO_DERIVED_KEYS`; the
Settings page greys those out only when a live value is actually available,
so a deployment without B/C never loses the ability to set them by hand.

**Secrets are generated, not required.** `DASH_SESSION_SECRET`,
`DASH_REPORT_TOKEN`, `BROLL_INGEST_TOKEN`, `SYNCTHING_API_KEY` and
`CCSYNC_INTERNAL_TOKEN` are still read from the environment first (§2.1
below is unchanged and still the right table for a hand-run deployment), but
`dashboard/src/ccsync_dashboard/secrets_boot.py`'s `ensure_secrets()` now
runs before `Settings.from_env()` on the real `run()` path: any of the five
NOT already in the environment is loaded from
`<DASH_DB_PATH's parent>/secrets/<lowercase name>`, or generated with
`secrets.token_urlsafe(32)` and persisted there 0600 if no file exists
either. **Env always wins over the file** — rotating a secret by setting the
env var stays possible. It also writes `secrets/syncthing.env`
(`STGUIAPIKEY=…`) and `secrets/sftp.env` (`CCSYNC_INTERNAL_TOKEN=…`,
`APP_UID=…`, `APP_GID=…`) as `env_file:` targets for the `syncthing` and
`sftp` sidecar services in agent A's compose (`ZERO_TOUCH_PLAN.md` §3.1) —
neither of those images reads `DASH_*` variables or generates its own
secret. This is a **no-op** for every deployment running today: it only
runs when `create_app` is called with no explicit `Settings` (every test in
this suite, and any hand-built deployment, passes one), and even then, a
container whose compose already sets all five leaves every one of them
untouched.

**The wizard.** `dashboard/src/ccsync_dashboard/setup_engine.py` is a task
registry (`GET /api/v1/setup/tasks`, `POST …/tasks/<id>/run|check|skip`,
`GET`/`POST /api/v1/setup/eula`) behind `/setup`, persisted in `setup_tasks`
(same migration). It is reachable with no session **only** in the narrow
window before any local admin account exists (reported by the identity
module `ZERO_TOUCH_PLAN.md` WP C adds — until it lands, every `/setup`
route is admin-only, fail-closed) — see `setup_routes.py`'s module
docstring. `docs/ZERO_TOUCH_PLAN.md` §3.2/§3.5 is the design; this
subsection is the config surface it added.

---

## 2. Dashboard environment

Read by `dashboard/src/ccsync_dashboard/settings.py` (`Settings.from_env`).
Written into the container's 0600 `.env` by `server/install_dashboard_app.py`.
The full annotated table, including the Synology-only rows, is in
[`../dashboard/README.md`](../dashboard/README.md).

### 2.1 Secrets

| Var | | Notes |
|---|---|---|
| `DASH_SESSION_SECRET` | **R S** | Signs session cookies **and** companion identity tokens. ≥ 24 chars, not a placeholder, enough variety to be random — **checked at boot, and a failure refuses to serve** (a weak value is a forgeable *admin* cookie). Must stay stable across deploys. Also read by the MOUNTED b-roll app (`broll/web` `config.get_session_secret`), which verifies the same identity tokens on its ingest fleet routes — unset there means those routes refuse, never run open |
| `DASH_REPORT_TOKEN` | **R S** | The shared fleet token companions present as `X-CCSync-Token`. Same boot check. Unset = reports refused — and, since 2026-08-18, b-roll ingest fleet calls too (`broll/web` `config.get_fleet_token`, fail-closed) |
| `SYNCTHING_API_KEY` | **R S** | Syncthing's GUI API key. The collector does nothing without it |
| `BROLL_INGEST_TOKEN` | **S F** | Mandatory when `DASH_BROLL_ENABLED=1`; `create_app` refuses to build an app with a blank, placeholder or short one rather than serve a write path a session cookie alone could reach |
| `DASH_NAS_PW` / `TRUENAS_PW` | **S** | Only `/admin/users` needs it. Unset = that section is 503, everything else works |
| `DASH_NAS_API_KEY` / `TRUENAS_API_KEY` | **S** | A **scoped** TrueNAS API key, **preferred over the password when both are set**. The password in the container is root-equivalent and readable with `docker inspect`; this UI only ever calls user/group/`sharing.smb`. Mint with `server/create_api_key.py`. TrueNAS only |
| `DASH_OIDC_CLIENT_SECRET` | **S F** | The confidential client's secret |
| `CCSYNC_INTERNAL_TOKEN` | **S** | Bearer token guarding `/internal/sftp/*` (WP C) — what the sftp sidecar's `AuthorizedKeysCommand` presents. Unset falls back to a file at `<db dir>/secrets/internal_token` (agent D's SetupEngine writes it at first boot; this dashboard only ever reads it). Neither configured = both routes answer `503`, never authenticate everyone |

### 2.2 Core

| Var | Default | Notes |
|---|---|---|
| `SYNCTHING_GUI_URL` | `""` | Collector disabled if unset |
| `DASH_DB_PATH` | `/data/dashboard.db` | SQLite, WAL |
| `DASH_PORT` | `8480` | |
| `DASH_PACKAGES_DIR` | `<db dir>/packages` | Published builds. The default lands under `/data`, the only volume that survives a redeploy |
| `DASH_PROJECTS_DIR` | `""` (off) | The mounted Projects tree to scan for auto-provisioning |
| `DASH_SYNCTHING_DATA_PREFIX` | `/data/Projects` | Where the **Syncthing** app sees the same tree. Must match the Syncthing install's container mount |
| `DASH_SYNCTHING_ASSETS_PREFIX` | `/data/Assets` | Same idea for the shared asset libraries. Blank disables shared-folder provisioning |
| `DASH_SYNCTHING_TAILNET_IP` | `""` | New device entries get `tcp://`/`quic://` on this address before `dynamic`, so editors dial the tailnet instead of learning a public address from global discovery. Only helps once the NAS's 22000 tcp+udp is reachable there — verify first |
| `DASH_SYNCTHING_TAILNET_ONLY` | `0` | **Opt-in and deliberately off.** Disables relays, global discovery and NAT traversal. Enabling it without a confirmed direct path *stops* lane C |

### 2.3 Auth

| Var | Default | Notes |
|---|---|---|
| `DASH_AUTH_METHOD` | `smb` | `smb`, `oidc`, or `local` (WP C, `docs/ZERO_TOUCH_PLAN.md` §3.3, 2026-08-17) — the dashboard's own accounts (`users`/`user_ssh_keys` tables), no NAS credential of any kind. `smb` stays the default until a fleet migrates (`ZERO_TOUCH_PLAN.md` §6); `local` is the appliance shape. The first local admin is created by the Setup wizard (`POST /api/v1/setup/admin`), not this env var — `DASH_ADMIN_USERS` still works additively as break-glass |
| `DASH_SMB_HOST` | `""` → NAS host | The SMB probe target. No tenant default since 2026-08-17 |
| `DASH_ADMIN_USERS` | `""` | csv, lowercase. Grants dashboard admin **and** decides who is `role: base` at `/api/v1/verify` |
| `DASH_SHARED_REPORT_TOKEN_ENABLED` | `1` | Whether the one shared `DASH_REPORT_TOKEN` is still accepted alongside per-editor tokens. **Only an explicit `"0"` turns it off** — a typo must not disconnect the fleet. Turn it off once Admin ▸ Users stops naming machines on the shared credential |
| `DASH_COOKIE_SECURE` | `auto` | `auto` = on for https. `1` forces it on **and refuses login over provable plain http**. Behind Tailscale Serve, use `1` |
| `DASH_TRUSTED_PROXIES` | `127.0.0.1,::1` | Whose `X-Forwarded-Proto` is believed. It used to be everyone's. A proxy on the *docker host* arrives from the bridge gateway (e.g. `172.17.0.1`) |
| `DASH_SESSION_IDLE_SECONDS` | `43200` (12h) | Refreshed by activity |
| `DASH_SESSION_ABSOLUTE_SECONDS` | `604800` (7d) | Never extended |
| `DASH_OIDC_ISSUER` | `""` | **F**. Blank + method `oidc` is refused at boot rather than silently falling back to passwords |
| `DASH_OIDC_CLIENT_ID` | `""` | **F** |
| `DASH_OIDC_SCOPES` | `openid profile email` | **F** |
| `DASH_OIDC_USERNAME_CLAIM` | `preferred_username` | **F**. **Must resolve to the NAS username** — a value containing `@` is refused rather than guessed |
| `DASH_OIDC_ADMIN_CLAIM` / `_VALUES` | `""` | **F**. Logged, **not obeyed**: admin comes from `DASH_ADMIN_USERS` |
| `DASH_OIDC_REDIRECT_URL` | `""` (derived) | Set it when something rewrites `Host` |
| `DASH_RELEASE_PUBKEYS` | `()` | Base64 Ed25519 public keys the publish route accepts signatures from, comma- or space-separated. **Entries that do not decode to a 32-byte key are dropped**, so a leftover `REPLACE_ME` produces "no release key configured" rather than "signature rejected". Empty = publishing is refused |
| `DASH_DEV_INSECURE` | `""` | **Lab/test only, and the only escape hatch there is.** Bypasses the boot secret floor, the server-side session rule and CSRF. Logged loudly at every boot; it must never be set on a deployment |
| `DASH_REPORT_TOKEN_OPTIONAL` | `""` | **No longer a shipped code path.** Ignored, with an error line, unless `DASH_DEV_INSECURE=1` is also set |

### 2.3a Release feed (`ZERO_TOUCH_PLAN.md` WP E, 2026-08-17)

Full writeup: [`RELEASE_FEED.md`](RELEASE_FEED.md).

| Var | Default | Notes |
|---|---|---|
| `DASH_RELEASE_FEED_URL` | `""` | absolute `https://` URL of `channel.json`. **Empty = the feed is entirely off** — no background thread, no network call, no admin-page section beyond "how to configure it" |
| `DASH_RELEASE_FEED_POLICY` | `manual` | `manual` \| `stage` \| `current`. An unrecognised value falls back to `manual`, never upward. Editable at runtime (`POST /api/v1/admin/feed/policy`), which overrides this default until cleared |
| `DASH_RELEASE_FEED_INTERVAL` | `86400` | seconds between background checks (floored at 60s) |

### 2.4 NAS backend

| Var | Default | Notes |
|---|---|---|
| `DASH_NAS_KIND` | `truenas` | `truenas` or `synology`; an unknown value is refused |
| `DASH_NAS_HOST`, `DASH_NAS_USER` | `""` | Blank is **warned about at boot, never fatal** — only `/admin/users` and the login probe need them |
| `DASH_NAS_VERIFY_SSL` | `0` | `1`, or a path to a CA bundle **inside the container** |
| `DASH_NAS_HOMES_PARENT` | `""` | From `[tree] homes_parent` |
| `DASH_NAS_SERVICE_USER` | `""` | The stack's own account, filtered out of every editor listing so a studio owner does not see the plumbing account beside their people |
| `DASH_NAS_SSH_PORT` / `_HOSTKEY` / `_KEY_PROBE` | `22` / `""` / `1` | Synology only |
| `TRUENAS_HOST` / `_USER` / `_PW` / `_VERIFY_SSL` | — | The previous spelling, honoured **for one release**. `DASH_NAS_*` wins when both are set |

### 2.5 Site manifest (`DASH_SITE_*`)

Projected from `site.toml` by the deploy; republished at `GET /api/v1/site`.
Each defaults to `""` — blank means "not configured", never another site's
value.

`DASH_SITE_ORG_NAME`, `_ORG_SHORT`, `_PRODUCT_NAME` (default `CC Sync`),
`_TREE_NAME`, `_CANONICAL_PREFIX` (default `P:\`), `_REMOTE_ROOT`, `_SMB_UNC`,
`_SFTP_HOST`, `_SFTP_PORT` (22), `_SFTP_CHUNK_SIZE`, `_SFTP_CONCURRENCY` (0),
`_SFTP_SHELL_TYPE`, `_RCLONE_REMOTE`, `_NAS_SYNCTHING_ID`, `_DASHBOARD_URL`.

Feature flags, both `"1"`-and-nothing-else (an unset, empty, misspelt or
`"true"`-shaped value all mean **off**, because off is the state it is safe to
be wrong about): `DASH_SITE_YOUTUBE_DOWNLOAD`, `DASH_SITE_YOUTUBE_UNBLOCK`.

`DASH_SITE_INDEXER_MODEL_TIER` — `good` (default) or `best` (2026-08-18, see
`[indexer]` above). Case-insensitive; anything else falls back to `good` with
a boot warning, the same "never coerce upward" rule as
`DASH_RELEASE_FEED_POLICY`.

### 2.6 Mounts and cadences

| Var | Default | Notes |
|---|---|---|
| `DASH_BROLL_ENABLED` | `1` at deploy time (`0` in `Settings`) | `"1"` and nothing else. Requires `BROLL_INGEST_TOKEN` |
| `BROLL_ARCHIVE_CREATORS_DIR` | `Creators_Club` | The top-level folder dashboard b-roll ingest files a shoot under: `<archive root>/<this>/<shoot>/…`. It is a literal in the indexer (`build_archive.CREATORS`) and every already-published file sits under it, so the default cannot change — but the name is one customer's, and item 4/10 says a second customer must not fork code to be called something else. Read only by NEW writes (2026-08-18) |
| *(music)* | — | **There is deliberately no `DASH_MUSIC_ENABLED`.** Ship the tree or don't |
| `DASH_INTERVAL_PROVISION` | `300` | |
| `DASH_INTERVAL_CONFIG` | `120` | |
| `DASH_INTERVAL_ENFORCE` | `60` | Share reconciliation |
| `DASH_INTERVAL_INVENTORY` | `900` | **900, not 300, on purpose**: the directory-signature check is mtime-only, so every file lane A uploads re-triggers a full per-file walk — 100k stats plus a full SQLite rewrite, on the box simultaneously serving SFTP and Syncthing. Trade-off: inventory freshness drops from 5 to 15 minutes |
| `DASH_INVENTORY_PROJECTS_PER_CYCLE` | `8` | |
| `DASH_INTERVAL_CONNECTIONS` | `15` | |
| `DASH_INTERVAL_COMPLETION` | `60` | **60, not 30**: completion polling scales as folders × devices and is computed on demand. Trade-off: percentages update half as often |
| `DASH_INTERVAL_REMOTENEED` | `60` | |
| `DASH_INTERVAL_PRUNE` | `3600` | |
| `DASH_BACKOFF_MAX` | `300` | |
| `DASH_ENFORCE_MAX_REMOVALS` | `3` | **Blast-radius brake.** An enforce pass that would unshare more than this many devices is refused (additions still apply) and logged as an ERROR. A mass unshare is never a normal outcome |

### 2.7 Deploy-time only

Read by `server/install_dashboard_app.py`, not by the running app:
`DASH_BIND_LAN` / `DASH_BIND_TAILNET` (blank is **refused, never guessed**),
`DASH_IMAGE`, `BROLL_WEB_SRC`, `MUSIC_WEB_SRC`, `MUSIC_DATA_SRC`,
`MUSIC_DATA_PUSH`, `MUSIC_FFMPEG_URL` / `_SHA256` / `_FETCH` / `_FILE` /
`_CACHE`, `YTDL_WEB_SRC`.

---

## 3. Companion `config.toml`

Lives at `~/.ccsync/config.toml` on every editor machine. The annotated
template is [`../companion/config.example.toml`](../companion/config.example.toml);
the per-key table with the reasoning is
[`../companion/README.md`](../companion/README.md).

Most of these are written by the onboarding wizard and then left alone. Values
the **site manifest** supplies (`remote`, `remote_root`, `smb_unc`,
`sftp_chunk_size`, `sftp_concurrency`, shell type, `canonical_prefix`) are
refreshed from `GET /api/v1/site` — change them on the server, not on twelve
laptops.

### Identity and paths

| Key | Default | Notes |
|---|---|---|
| `editor_name` | `""` | **R**. Must match the NAS account |
| `mode` | `editor` | `base` = the machine with direct NAS access; implies `sync_enabled = false` unless set explicitly. The out-of-tree popup stays **on** in base mode |
| `local_root` | `""` | **R**. This machine's tree root |
| `canonical_prefix` | `P:\` | The prefix Resolve's stored clip paths use |
| `remote` | `ccsync_sftp` | Must match the stanza in `rclone.conf` |
| `remote_root` | `""` | **R, and must be absolute.** A relative value resolves under the editor's home, which does not contain the tree |
| `server_p_unc` | *(from manifest)* | The UNC path, taken from `smb_unc` rather than derived |

### Lanes

| Key | Default | Notes |
|---|---|---|
| `scan_interval_up` / `_down` | `300` / `120` | Full-pass intervals (s) |
| `watch_debounce_seconds` | `10` | Lane A watchdog debounce |
| `lane_b_min_age_seconds` | `120` | Settle window — a file still copying off a card has a fresh mtime |
| `lane_b_enabled` | `true` | `false` on the base rig |
| `sync_enabled` | `true` | `false` = no lanes at all; the watcher, fixer and reporting still work |
| `transfers` / `checkers` | `4` / `16` | rclone parallelism |
| `sftp_chunk_size` / `sftp_concurrency` / `sftp_connections` | `255Ki` / `64` / `16` | **The server dictates the first two** via the manifest; a Synology site needs `64Ki`/`16` |
| `rclone_ignore_checksum` | `true` | |
| `order_by_up` / `_down` | `modtime,descending` / `size,ascending` | |
| `concurrent_lanes` | `true` | |
| `structure_clone_every_n_passes` | `10` | Replicates empty scaffolding lane B and lane C both drop |
| `lane_c_pause_scheme` | `none` | |
| `lane_c_max_folder_concurrency` | `2` | |
| `express_upload_enabled` / `_debounce_seconds` / `_max_batch` | `true` / `10.0` / `200` | The fast path for a just-added file |
| `orphan_scan_every_n_passes` | `20` | |

### Safety (see [`SYNC_SAFETY.md`](SYNC_SAFETY.md))

| Key | Default | Notes |
|---|---|---|
| `lane_b_max_deletes_per_pass` | `50` | Breaker: absolute count |
| `lane_b_max_delete_fraction` | `0.25` | Breaker: share of the local tree |
| `lane_b_remote_shrink_fraction` | `0.5` | Breaker: the remote itself shrank |
| `trash_max_age_days` | `14` | `.ccsync-trash` retention |
| `trash_max_bytes` | `53687091200` (50 GB) | |
| `trash_prune_interval_seconds` | `21600` | |

### Dashboard link

| Key | Default | Notes |
|---|---|---|
| `dashboard_url` | `""` | Blank disables the reporter thread entirely |
| `dashboard_token` / `report_token` | `""` | **S**. `X-CCSync-Token`. Prefer a per-editor token |
| `require_login` | `true` | |
| `dashboard_report_interval` | `60` | And `_active` = `5` while transferring |
| `manifest_refresh_interval` | `300` | |
| `media_tree_refresh_interval` | `120` | |
| `selection_poll_interval` | `60` | |
| `selection_fetch_ttl` / `project_roots_ttl` | `30` / `300` | |
| `project_rotation_seconds` | `600` | Starvation guard on the per-project rotation |
| `sequencer_idle_seconds` | `60` | |

### Syncthing (lane C)

`syncthing_url` (`http://127.0.0.1:8384`), `syncthing_api_key` (**S**, blank =
read it from Syncthing's own `config.xml`), `syncthing_folder_ids`, `projects`.

### Resolve integration

| Key | Default | Notes |
|---|---|---|
| `poll_interval` | `3` | Timeline poll (s) |
| `active_project` | `""` | Only the popup fixer's suggested destination — it does **not** scope what syncs |
| `popup_enabled` / `popup_snooze_seconds` | `true` / `300` | The media-outside-tree popup |
| `proxy_relink_enabled` | `true` | Repoints clips at the in-tree proxy. Repoint-only: never copies, moves or deletes |
| `resolve_scripting_warning` / `_interval` | `true` / `300` | |
| `bridge_auto_restart` | `true` | |
| `resolve_log_override` | `""` | |
| `ignored_resolve_projects` | `["Untitled Project", "New Doc"]` | Resolve's scratch projects, and their numbered duplicates |

### Proxies

`proxy_notify_enabled` (`true`, everywhere — it costs nothing and touches no
bytes), `proxy_gen_enabled` (**tri-state**: absent = `not lane_b_enabled`, so
on where the result lands on the NAS and off where lane B would sweep a
locally-made proxy into `.ccsync-trash`), `ffmpeg_path`, `proxy_scan_interval`
(900), `proxy_gen_idle_seconds` (300), `proxy_gen_min_age_seconds` (120),
`proxy_gen_max_height` (1080 — a ceiling, never an upscale),
`proxy_gen_bitrate` (`7M`), `proxy_gen_max_failures` (3, in-process only),
`proxy_gen_free_space_floor_gb` / `_pct`, `proxy_gen_stability_seconds`,
`proxy_gen_skip_while_resolve_running` (false), `proxy_notify_cooldown_seconds`
(86400), `proxy_dry_run`, `fixer_dry_run`.

Blackmagic Proxy Generator: `bpg_enabled`, `bpg_path`,
`bpg_manage_watch_folders` (true), `bpg_autostart` (true),
`bpg_settings_path`.

### YouTube (**F** — all inert unless the site enables the feature)

`youtube_import_enabled` (true), `youtube_import_scan_interval` (60),
`youtube_import_min_age_seconds` (120), `youtube_import_batch_limit`,
`youtube_import_max_failures`, `ytdl_local_downloads` (true), `ytdlp_path`,
`ytdl_cookies_file` (**S** — a cookie jar is a live sign-in).

### LUTs, stills, machine behaviour, loopback

`lut_sync_enabled` (true), `resolve_lut_dir`, `lut_location_override`,
`lut_check_interval` (900), `lut_index_repair_enabled` (true),
`stills_sync_enabled` (true), `shutdown_warning_enabled` (true),
`keep_awake_while_syncing` (true) with `keep_awake_stale_seconds` /
`_max_hold_seconds`, `broll_server_enabled` (true), `broll_server_port`
(**8899 — pinned on the web page's side too**, so changing it here alone just
switches the feature off), `rclone_path`, `log_path`, `log_level`,
`crash_reporting` (false) / `crash_dsn`.

---

## 4. Indexer environment

Only needed on the machine that **builds** an index (the base rig). Nothing in
the NAS container ever needs a GPU. Full context: [`INDEXERS.md`](INDEXERS.md).

Every path below is **required** as of 2026-08-17, and every refusal names both
the config key and the environment variable that would supply it.

### B-roll (`broll/indexer/config.yaml`)

| Env | Config key | What |
|---|---|---|
| `ANTHROPIC_API_KEY` | *(named by `anthropic.api_key_env`)* | **R S**. Never in `config.yaml` |
| `BROLL_DATA_ROOT` | `data_root` | **R**. Frames, proxies, posters, sprites, transcripts. Tens of GB — local disk, never the share |
| `BROLL_DB_PATH` | `db.path` | **R** when `db.mode: sqlite` |
| `BROLL_DB_URL` / `BROLL_DB_TOKEN` | `db.url` / `db.token` | **S** when `db.mode: api` |
| `CCSYNC_WHISPER_PYTHON` | `whisper.python` | **R**. The faster-whisper interpreter — a separate one on purpose (ctranslate2 pins its own CUDA runtime) |
| `CCSYNC_WHISPER_SCRIPT` | `whisper.script` | **R** |
| `CCSYNC_WHISPER_MODEL_DIR` | `whisper.model_dir` | **R**. ~1.6 GB for `large-v3-turbo` |
| `BROLL_MODEL_CACHE` | `embedding.cache_dir` | **R**. fastembed's ONNX weights |

### Music (`music/indexer/music_index/config.py`)

| Env | What |
|---|---|
| `MUSIC_DB_PATH` (or `--db`) | **R**. `index_music.py` refuses to pick one — guessing is how a drain reports "nothing to analyse" about a database nobody asked about |
| `MUSIC_DATA_ROOT` | **R**. Proxies, staging |
| `MUSIC_LIBRARY_ROOT` | **R**. Where this host has the music share mounted |
| `FFMPEG` / `FFPROBE` | **R** (else `PATH`). Checked up front rather than failing per track |
| `MUSIC_MODEL_CACHE` (or `HF_HOME`) | CLAP weights, ~600 MB |

---

## 5. Release tooling environment

Base rig only, and none of it reaches a customer's NAS.

| Var | | Notes |
|---|---|---|
| `CCSYNC_RELEASE_KEY` | **S** | Path to the Ed25519 private key. Default `%USERPROFILE%\.ccsync-release\release.key`, mode 0600, **outside the repo, never committed** |
| `TRUENAS_PW` / `SYNO_PW` | **R S** | The NAS admin password |
| `TRUENAS_SUDO_PW` | **S** | A different password for `sudo -S`, where the platform allows one |
| `DASH_REPORT_TOKEN`, `DASH_SESSION_SECRET`, `SYNCTHING_API_KEY` | **R S** | `tools/ship.cmd` refuses to start without them, before anything moves |
| `CCSYNC_SITE` | | Path to the site manifest |
| `CCSYNC_NAS_KIND` | | Overrides `[nas] kind` |
| `CCSYNC_SSH_HOSTKEY` / `CCSYNC_SSH_TRUST_ON_FIRST_USE` / `CCSYNC_KNOWN_HOSTS` | | Host-key pin, first-use escape hatch, and the pin file (default `~/.ccsync/known_hosts`) |
| Code-signing vars | **S** | See [`RELEASE.md`](RELEASE.md) "Code signing" |

**Do not `setx` any of these.** Read [`SECRETS.md`](SECRETS.md) for what to do
instead.

---

## See also

- [`INSTALL.md`](INSTALL.md) · [`ARCHITECTURE.md`](ARCHITECTURE.md) · [`API.md`](API.md)
- [`../site.example.toml`](../site.example.toml) — the annotated schema
- [`../companion/config.example.toml`](../companion/config.example.toml)
- [`../dashboard/README.md`](../dashboard/README.md) · [`../server/README.md`](../server/README.md)
- [`SECRETS.md`](SECRETS.md) · [`TENANCY.md`](TENANCY.md) · [`SYNC_SAFETY.md`](SYNC_SAFETY.md)
