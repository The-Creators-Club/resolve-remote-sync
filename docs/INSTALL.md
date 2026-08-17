# Installing CC Sync

CC Sync — fleet sync for DaVinci Resolve®. Requires DaVinci Resolve Studio on
every editing machine (collaboration and the scripting API do not exist in the
free version).

This is the **generic** install guide: it assumes you have never seen this
repository, and it names no addresses of ours. Everything site-specific comes
out of one file you write — `site.toml` — and every command below reads it.

Two NAS platforms are supported, and they differ enough to have their own
runbooks. Do the ordering and the secrets here; do the per-platform steps
there:

| Your NAS | Runbook |
|---|---|
| TrueNAS SCALE 25.x | [`SERVER.md`](SERVER.md) |
| Synology DSM 7.2+ | [`SERVER-SYNOLOGY.md`](SERVER-SYNOLOGY.md) — and [`SYNOLOGY_EASY_INSTALL.md`](SYNOLOGY_EASY_INSTALL.md) for the packaged-installer design |

Written 2026-08-17 (`COMMERCIAL_READINESS.md` item 13). If a step here and a
step in a per-platform runbook disagree, the runbook is right about *how* and
this file is right about *what order*.

---

## 1. What you need before you start

### The NAS

- **TrueNAS SCALE 25.x**, or **Synology DSM 7.2+**. One box. It holds the
  canonical project tree, runs the dashboard container, and runs Syncthing.
- An **admin account** the install scripts SSH in as and call the platform API
  with. On TrueNAS that is `truenas_admin`; on DSM it must be a member of
  `administrators` (DSM allows SSH for admins only) **with 2FA off**.
- Disk: the whole project tree plus proxies. There is no built-in quota.
- SSH enabled, and SMB enabled (editor logins are verified by an SMB session
  setup — see [Auth](#5-authentication-choices)).

### The network

- **Tailscale** on the NAS, on the base rig, and on every editor machine.
  Tailscale is the security perimeter of this product, not an optional
  transport: the dashboard has no public listener, and
  **Tailscale Serve is the only supported way to publish it with TLS**
  (decision 2026-08-17; see `SERVER-SYNOLOGY.md` "Publishing the dashboard").
  A LAN-only, plain-HTTP deployment works and is what a single-site studio
  usually runs, but then *the LAN is the perimeter* — say so out loud before
  you choose it.

### The base rig

The machine an operator runs the install and release scripts from. It is also
where the optional GPU indexers run.

- Windows 10/11 (the release tooling is PowerShell; the server scripts are
  plain Python and run anywhere, but the *shipped* path is Windows).
- **Python 3.11+** and **git**.
- Direct access to the NAS share (this machine mounts the tree rather than
  syncing it).
- For releases only: PyInstaller, and a **Mac** if you have Mac editors —
  macOS bundles cannot be cross-built (see [`RELEASE.md`](RELEASE.md)).

### Every editor machine

- **DaVinci Resolve Studio** (paid). Windows 10/11 or macOS.
- Tailscale, signed in to your tailnet.
- Room for proxies of everything they touch: think hundreds of GB.
- Nothing else — the wizard installs rclone, Syncthing and the companion.

### Optional, only if you turn the feature on

| Feature | Extra requirement |
|---|---|
| B-roll search (`/broll`) | An Anthropic API key on the **base rig** for the indexer; a GPU is optional but the indexers assume one. See [`INDEXERS.md`](INDEXERS.md). |
| Music search (`/music`) | A CUDA GPU on the base rig for CLAP embedding. The container only embeds *query text* (CPU, ~18 ms). |
| YouTube downloader (`/ytdl`) | Off by default and a **legal decision**, not a technical one — read [`legal/YOUTUBE_FEATURE_NOTICE.md`](legal/YOUTUBE_FEATURE_NOTICE.md) before enabling. |
| Single sign-on | An OIDC IdP (Keycloak, Authentik, Entra …) that can publish the **NAS username** as a claim. |

---

## 2. The order of operations

Do these in order. Each one is safe to re-run.

### Step 1 — write `site.toml`

```sh
git clone <your checkout of this repo>
cd resolve-remote-sync
cp site.example.toml site.toml
$EDITOR site.toml
```

`site.example.toml` is the annotated schema; every key is explained inline and
again in [`CONFIG.md`](CONFIG.md). The file is meant to be readable, diffable
and committable — **it holds no secrets**.

The search order for the file is `--site <path>`, then `$CCSYNC_SITE`, then
`<repo>/site.toml`. The search order for a *value* is the script's own flag,
then its env var, then this file — and if a script needs a value it cannot
find anywhere, it stops and names the key. It never falls back to some other
site's NAS.

Minimum you must fill in: `[nas] kind/host/admin_user`, `[tree] pool_root`,
`tree_name`, `share_name`, `smb_unc`, `[apps] root`, `[net] dashboard_url`,
and (TrueNAS) `[net] bind_lan` / `bind_tailnet`.

Pin the NAS's SSH host key while you are here:

```sh
ssh-keyscan -t ed25519 <nas>          # paste the "<type> <base64>" half
```

into `[nas] ssh_hostkey`. Since 2026-08-17 an unpinned host that is not
already in `~/.ccsync/known_hosts` is **refused** — that channel carries the
admin password on its stdin. For a genuinely first connection, run once with
`--trust-host-key-on-first-use` (or `CCSYNC_SSH_TRUST_ON_FIRST_USE=1`); the key
is recorded and printed, and a key that later *changes* is a refusal.

### Step 2 — export the secrets into your shell

See [§3](#3-the-secrets-and-where-they-live). Nothing below works without them.

### Step 3 — the server scripts, per backend

Run these from the base rig, against the NAS, in this order. The
per-platform runbook has the full text; this is the shape:

```sh
# 1. Syncthing -- the lane C engine. TrueNAS: installs the catalog app, and
#    this is where SYNCTHING_API_KEY comes from, so it must come FIRST.
#    Synology: a NO-OP that says so -- there Syncthing is a service inside the
#    same compose stack the next step deploys.
python server/install_syncthing_app.py --site site.toml --dry-run
python server/install_syncthing_app.py --site site.toml

# 2. the dashboard stack: shared folder / dataset, service account, host dirs,
#    code, compose. Read the dry-run first -- it prints every remote command
#    with secrets masked.
python server/install_dashboard_app.py --site site.toml --dry-run
python server/install_dashboard_app.py --site site.toml

# 3. the project tree skeleton + your first project
python server/setup_tree.py --site site.toml --project-rel-path "2026/Demo/First Project"
```

Re-running any of these is safe. Compose-level changes (env, mounts, ports)
need `install_dashboard_app.py --recreate`, not a plain re-run — and
`--recreate` re-reads the secrets from your environment, so pass them again.

TrueNAS specifics (datasets, the `broll:editors` service account, the app
catalog, `--recreate`): [`SERVER.md`](SERVER.md).
Synology specifics (shared-folder ACLs, `SYNO.SFTP` privilege, the bundled
Syncthing profile, 127.0.0.1 binding): [`SERVER-SYNOLOGY.md`](SERVER-SYNOLOGY.md).

### Step 4 — snapshots, before anything else writes

```sh
python server/setup_snapshots.py --site site.toml            # DRY RUN is the default
python server/setup_snapshots.py --site site.toml --apply    # ...and this does it
```

The rule this product runs on is **snapshot before any privileged operation**.
Configure the schedule now, not after the first incident.
[`BACKUP_RESTORE.md`](BACKUP_RESTORE.md) is the whole story, including how to
restore one file, one project, or the fleet database.

### Step 5 — put a login on the Syncthing GUI

The Syncthing GUI is an **unauthenticated admin surface over every folder in
the fleet**. Bind it to one address (`[syncthing] gui_bind`, or `127.0.0.1`
plus an SSH tunnel), then:

```sh
python server/secure_syncthing_gui.py --site site.toml
```

That sets a GUI username/password and does **not** touch the API key, so
nothing automated notices.

### Step 6 — the release signing key, and `DASH_RELEASE_PUBKEYS`

The upgrade channel hands every editor machine an executable that gets renamed
over the running companion. It is signed, and the dashboard verifies the
signature **on publish**:

```powershell
python tools\release_key.py new              # %USERPROFILE%\.ccsync-release\release.key (0600)
python tools\release_key.py pubkey --quiet   # the value for DASH_RELEASE_PUBKEYS
python tools\release_key.py bake             # bake the public half into the companion
```

Put that public key in the container's environment as `DASH_RELEASE_PUBKEYS`
(comma-separated; list two during a key rotation) and redeploy. With it unset,
`PUT /api/v1/admin/packages/...` answers **503 and says so** — it does not
fall back to accepting unsigned builds. Full detail:
[`RELEASE.md`](RELEASE.md) "The release signing key".

### Step 7 — the first editor

1. **Create the account.** Dashboard ▸ Admin ▸ Users ▸ add editor (needs
   `DASH_NAS_PW` or `DASH_NAS_API_KEY` configured), or from the base rig:
   `python server/setup_editor_account.py --site site.toml --name <editor>
   --ssh-pubkey-file <their key.pub>` (`--dry-run` first).
   Editors are **SFTP-only** by default (`[stack] editor_shell = "sftp-only"`):
   nologin, `ForceCommand internal-sftp`, no password auth. See
   [`TENANCY.md`](TENANCY.md).
2. **Send them the installer.** They sign in to the dashboard and click
   `[ INSTALLER ]`, which serves the right package for their OS. The
   walkthrough written for the editor is
   [`../installer/START_HERE.md`](../installer/START_HERE.md); the operator
   view is [`EDITOR_SETUP.md`](EDITOR_SETUP.md).
3. **Approve them.** The wizard ends by showing the editor their **Syncthing
   device ID** and **SSH public key**. Approve the device from Admin ▸ Users
   (or `python server/accept_device.py`), and the SSH key goes on the account.
4. **Tick their projects.** Nothing syncs to a machine until a project is
   ticked for that editor.

### Step 8 — verify

Run the checklist in [§6](#6-verification-checklist).

---

## 3. The secrets, and where they live

Six values. **None of them belongs in `site.toml`, in the repo, or in a
`setx`-style persistent user environment variable** — read
[`SECRETS.md`](SECRETS.md), which explains why and what to use instead
(SecretManagement + a vault on Windows, the runner's own store in CI).

| Env var | Needed by | What it is |
|---|---|---|
| `TRUENAS_PW` (`SYNO_PW` on a Synology site) | every server script | the NAS admin password: SSH `sudo -S` **and** REST/DSM API auth |
| `SYNCTHING_API_KEY` | `install_dashboard_app.py`, `setup_syncthing_folder.py`, `check_health.py` | Syncthing's GUI API key |
| `DASH_REPORT_TOKEN` | `install_dashboard_app.py` | the shared secret companions present as `X-CCSync-Token`. ≥ 24 chars, checked at boot |
| `DASH_SESSION_SECRET` | `install_dashboard_app.py` | signs dashboard session + companion identity tokens. ≥ 24 chars, and **must stay stable across deploys** — a new value logs everyone out |
| `BROLL_INGEST_TOKEN` | `install_dashboard_app.py`, when b-roll is on | guards the indexer's write path into `broll.db`. Mandatory when `DASH_BROLL_ENABLED=1` |
| `DASH_RELEASE_PUBKEYS` | `install_dashboard_app.py` | *public*, not secret — but it is passed the same way. Without it, publishing is refused |

Generate each with `openssl rand -hex 24`.

Optional, and preferred where it exists:

- `TRUENAS_API_KEY` — a **scoped** TrueNAS API key minted by
  `python server/create_api_key.py`, so the dashboard container holds
  something that can only touch user/group/SMB-share endpoints instead of the
  root-equivalent admin password. TrueNAS only; DSM has no API-key concept.
- `TRUENAS_SUDO_PW` — a *different* password for `sudo -S` on the NAS, where
  the platform allows one.
- `CCSYNC_SSH_HOSTKEY` / `CCSYNC_SSH_TRUST_ON_FIRST_USE` / `CCSYNC_KNOWN_HOSTS`
  — the host-key pin, the first-use escape hatch, and where the pin file
  lives (default `~/.ccsync/known_hosts`).

`install_dashboard_app.py` writes the container's `.env` **mode 0600, root
owned**. It is the only place these land on the NAS.

---

## 4. Feature switches

Optional features are **off unless this site turns them on**. Both live in
`site.toml`, and both are published to clients by `GET /api/v1/site` so a
companion that cannot read the key behaves as if the feature is off:

```toml
[features]
youtube_download = false   # the /ytdl page: search, review, download
youtube_unblock  = false   # PO-token provider, deno n-challenge solver, cookie sign-in
```

- **`youtube_download`** — off because the *customer*, not the vendor, is the
  party who decides whether downloading third-party YouTube material is lawful
  for their footage in their jurisdiction under YouTube's Terms. Off means the
  dashboard does not mount `/ytdl` at all, the fleet download routes 404, and
  every companion hides its YouTube menu items and refuses the loopback
  actions. Read [`legal/YOUTUBE_FEATURE_NOTICE.md`](legal/YOUTUBE_FEATURE_NOTICE.md).
- **`youtube_unblock`** — the components that exist to get past YouTube's
  anti-automation measures. **The vendor build ships none of them installed.**
  Setting this (or `--enable-youtube-unblock`) is the customer asserting they
  have the right to. It requires `youtube_download`; on its own it does
  nothing, and the manifest will not report it true alone.

Two more switches that are not in `[features]` but decide the shape of the
deployment:

```toml
[stack]
editor_shell = "sftp-only"   # or "shell" -- see docs/TENANCY.md before changing
project_acl  = "shared"      # or "per-project"
```

`project_acl = "shared"` (the default, and today's behaviour) means **every
editor can read, write and delete every other editor's project**. If that is
not acceptable to your customer, read [`TENANCY.md`](TENANCY.md) *before*
flipping it — it rewrites ownership on an existing tree.

### What is optional

| Component | How to leave it out | Consequence |
|---|---|---|
| **B-roll search** | `DASH_BROLL_ENABLED=0` on the deploy | no `/broll` mount, no ingest token needed. The dashboard boots identically |
| **Music search** | ship no `music/web` tree (there is deliberately no `DASH_MUSIC_ENABLED`) | `/music` is simply absent |
| **YouTube downloader** | `[features] youtube_download = false` (the default) | `/ytdl` unmounted, companion menus hidden |
| **OIDC / SSO** | leave `DASH_AUTH_METHOD` at `smb` | editors sign in with their NAS password |
| **GPU indexers** | do not run them | search UIs still serve whatever index you ship; see [`INDEXERS.md`](INDEXERS.md) "Customers without a GPU" |

A broken or absent optional mount must **never** stop the dashboard booting.
That is a design rule, and each mount reports `mounted` / `absent` /
`degraded` rather than raising.

---

## 5. Authentication choices

Decide this before the first editor signs in.

- **`DASH_AUTH_METHOD=smb` (default).** Editors sign in with their NAS
  username and password, verified by an SMB session setup on port 445. This is
  the only credential check that works for non-admin accounts on TrueNAS
  25.10 — the middleware refuses them outright. `DASH_SMB_HOST` defaults to
  the NAS.
- **`DASH_AUTH_METHOD=oidc`.** Authorization code + PKCE against your IdP.
  The claim named by `DASH_OIDC_USERNAME_CLAIM` (default `preferred_username`)
  **must be the NAS username** — every join in the product is one, and an
  email address there produces an editor nothing matches. Admin rights still
  come from `DASH_ADMIN_USERS`. `/login?local=1` stays as break-glass for
  admins only, so an IdP outage cannot lock the operator out.
- **Admins** are whoever is listed in `DASH_ADMIN_USERS` (csv, lowercase).
  Admins see the whole fleet; everyone else sees only themselves.

Companions authenticate separately, with `X-CCSync-Token` plus an
`X-CCSync-Identity` token minted by signing in from the tray. Prefer
**per-editor report tokens** (Admin ▸ Users) over the one shared
`DASH_REPORT_TOKEN`: they are revocable one person at a time and they *bind*,
so a token cannot report as somebody else. Once the Users page shows no
machines still on the shared credential, set
`DASH_SHARED_REPORT_TOKEN_ENABLED=0`. See [`API.md`](API.md).

---

## 6. Verification checklist

Run the automated one first:

```sh
python server/check_health.py --site site.toml \
    --gui-url http://<nas>:8384 --api-key "$SYNCTHING_API_KEY"
```

Exit code = number of failed checks. It covers: the project database port,
Tailscale logged in *and whether each peer path is direct or relayed*, the
tailnet path from this machine, Syncthing reachable, Syncthing folders listed,
the project tree present, the `editors` group populated, and the dashboard's
`/api/v1/health`.

Then check by hand:

- [ ] `GET <dashboard>/api/v1/site` returns **your** `org_name`, `tree_name`,
      `smb_unc` and `rclone_remote` — not blanks, and not somebody else's.
- [ ] `GET <dashboard>/api/v1/health` reports `ok: true` and a version.
      Authenticated, it also shows `collector_stale: false` and no
      `folder_errors`.
- [ ] Signing in to the dashboard with an editor's NAS credentials works, and
      that editor sees only their own rows.
- [ ] Admin ▸ Users lists your editors and **not** the stack's service
      account (it is filtered out on purpose).
- [ ] Publishing a build is refused with a clear 503 when
      `DASH_RELEASE_PUBKEYS` is unset — then works once it is set.
- [ ] The Syncthing GUI asks for a password, and is not reachable from
      outside the address you bound it to.
- [ ] `site.toml`'s `[net] sftp_chunk_size` is **`64Ki` on a Synology site**.
      At 255Ki, DSM 7.2's OpenSSH 8.2 truncates downloads at 539,000,832
      bytes and rclone reports success — a silent data-loss bug.
- [ ] A snapshot exists, and you have restored one file from it once.
- [ ] The first editor's tray shows all three lanes green, and a ticked
      project appears on their drive.
- [ ] `.ccsync-trash` and the lane B breaker are understood by whoever
      operates this — [`SYNC_SAFETY.md`](SYNC_SAFETY.md).

---

## 7. Where to go next

| You want to | Read |
|---|---|
| Understand the system | [`ARCHITECTURE.md`](ARCHITECTURE.md) |
| Look up a config key | [`CONFIG.md`](CONFIG.md) |
| Call the API | [`API.md`](API.md), [`LOOPBACK_API.md`](LOOPBACK_API.md) |
| Set an editor up | [`EDITOR_SETUP.md`](EDITOR_SETUP.md), [`../installer/START_HERE.md`](../installer/START_HERE.md) |
| Ship a companion build | [`RELEASE.md`](RELEASE.md) |
| Not lose footage | [`SYNC_SAFETY.md`](SYNC_SAFETY.md), [`BACKUP_RESTORE.md`](BACKUP_RESTORE.md), [`RESOLVE_EDIT_SAFETY.md`](RESOLVE_EDIT_SAFETY.md) |
| Debug something weird | [`GOTCHAS.md`](GOTCHAS.md) |
| Everything else | [`README.md`](README.md) — the docs index |

---

DaVinci Resolve is a registered trademark of Blackmagic Design Pty Ltd. CC Sync
is not affiliated with, endorsed by, or sponsored by Blackmagic Design.
