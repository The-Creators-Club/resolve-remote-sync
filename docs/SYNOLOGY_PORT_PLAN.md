# Synology port plan — running CC Sync against a Synology DSM 7.2 NAS

Written 2026-08-17. Companion to `COMMERCIAL_READINESS.md` (this is the
platform half of its item 12).

**Status, 2026-08-17 (same day):** the day-1 spikes are done and written up in
`docs/synology-spikes-2026-08-17.md` -- read that before this document, since
four of the eight came back differently from what is assumed below. WP0, WP1,
WP2, WP3 and the honest minimum of WP4 are implemented and were brought up on
a live DS423+: dashboard + bundled Syncthing running, tree created, an editor
writing to it over SFTP, `check_health.py` 7/7, and an editor created and
deleted through the deployed dashboard. The runbook that came out of it is
`docs/SERVER-SYNOLOGY.md`, which also lists what remains unverified (reboot
survival, `tailscale serve`, the reverse-proxy API shape). WP5-WP7 are open.

Target: DSM 7.2+, x86_64 Plus/XS/RS models with Container Manager.
Estimate: 5–6 weeks, one engineer who knows the repo, a Synology unit on the
desk from day 1. Out of scope: ARM models (no Container Manager), DSM 6, full
multi-tenancy, SSO.

## Shape of the work

The companion, installers, wizard, dashboard app, b-roll/music/ytdl, Syncthing
client, rclone lanes and SMB-probe auth are already NAS-agnostic. What is
TrueNAS-shaped is:

- **runtime**: `dashboard/src/ccsync_dashboard/truenas_client.py` (255 lines,
  6 call sites in `api.py:841,1515,1580` and `ui.py:879,929`) — admin editor
  provisioning via `/user`, `/group`, `/filesystem/setperm`, `/core/get_jobs`;
- **install-time**: ~5,000 lines under `server/` — app-catalog Syncthing
  install, custom-app compose POST + redeploy, `ix-<app>-1` container names,
  `HOST_ROOT_RE` on `/mnt/<pool>/apps/…`, `docker exec tailscale`, binaries
  pushed to host, `check_health.py`.

The port is: put both behind a backend interface, write the Synology
implementation, template `compose.yaml`, and spend a week discovering DSM's
quirks on hardware. The first port pays for the abstraction; Unraid/QNAP/plain
Linux afterwards are days each.

**Precondition:** the de-tenanting subset from `COMMERCIAL_READINESS.md`
(blank IP/ID defaults, compose as a template, a minimal site manifest). Doing
Synology on top of hardcoded `192.168.0.10`/`/mnt/tank` defaults is a fork,
not a port — that is WP0.

## Design decisions (make these first)

1. **One seam, two halves.** *Runtime* `NasBackend` (dashboard container →
   NAS): user/group provisioning, SSH-key install, home-perms fix, password
   set, editor listing. *Install-time* `ServerBackend` (base rig → NAS over
   SSH): deploy the compose stack, install Syncthing, create the tree/shares/
   ACLs, health checks. One `--nas-kind truenas|synology` switch.
2. **Synology identity via DSM Web API + SSH fallback.** Runtime backend uses
   the DSM Web API (`SYNO.API.Auth` → sid, `SYNO.Core.User`,
   `SYNO.Core.Group`) from inside the container over `https://nas:5001`. Core
   APIs are what DSM's own UI uses but are only semi-documented — apply the
   same shape-check-then-act discipline `server/install_syncthing_app.py:10-40`
   already uses. Home-dir permissions and ACLs go over SSH (`synoacltool`,
   `chmod`) because no clean API exists.
3. **Syncthing as a container in our compose stack**, not the SynoCommunity
   package: we control the version, the API key, the data mount (`/data`,
   matching `DASH_SYNCTHING_DATA_PREFIX`), and it deploys with everything
   else. `install_syncthing_app.py` becomes a no-op on Synology; the
   dashboard's Syncthing client is unchanged.
4. **Deploy via `docker compose` CLI over SSH.** DSM 7.2's Container Manager
   ships compose v2 (`/usr/local/bin/docker compose`). Stacks started from the
   CLI appear in Container Manager as containers (not as a UI "project") —
   acceptable. Reuse the existing SFTP stage-verify-swap deploy engine
   unchanged; only "tell the platform to (re)start the app" is backend-specific.
5. **Bind on loopback, publish with Tailscale Serve.** The Tailscale DSM
   package runs in userspace mode by default, so there is no tailnet interface
   IP for compose to bind (`compose.yaml:191-192` today). Bind
   `127.0.0.1:8480` and expose with `tailscale serve` — which also gives HTTPS
   (readiness item 6). Tailscale is the ONLY publish path for customers
   (decision 2026-08-17; verified same day after the tenant's "Enable HTTPS"
   click) -- no DSM reverse proxy, no DDNS. Note the spike found the package
   in TUN mode, so a tailnet-IP bind is also possible; Serve is still the
   answer because it brings the certificate.
6. **Btrfs + Snapshot Replication as a stated requirement.** The install path
   creates a scheduled snapshot task on the tree share and the apps share —
   closes readiness item 8 on Synology from day one.

## TrueNAS → Synology mapping

| Concern | TrueNAS today | Synology DSM 7.2 | Code |
|---|---|---|---|
| Privileged channel | SSH as `truenas_admin`, `echo $PW \| sudo -S`; REST `/api/v2.0` basic-auth | SSH as an *administrators*-group user (SSH is admin-only on DSM), `sudo -S` identical; DSM Web API `:5001` with sid (service account with 2FA off) | `server/common.py:432-495,556-620` |
| Create editor | `POST /user` {home_create, shell bash, smb, sshpubkey, random_password} | `SYNO.Core.User create` (or `synouser --add`); shell is `/sbin/nologin` by default (good — closes readiness H4); no sshpubkey field → write `authorized_keys` over SSH | `truenas_client.py:182-320`, `setup_editor_account.py:254-400` |
| Editors group | `POST /group` {smb:true} | `SYNO.Core.Group create` / `synogroup --add editors`; then grant the group the **FTP application privilege** (SFTP on DSM is gated by the FTP app permission) and shared-folder RW | `truenas_client.py:124-145` |
| Home dir + SSH key | TrueNAS creates `<pool>/homes/<u>`; `filesystem.setperm stripacl 700` to defeat NFSv4 ACL inheritance | Enable **User Home** service → `/var/services/homes/<u>` (= `/volume1/homes/<u>`); write `~/.ssh/authorized_keys`; `chmod 755 ~; 700 .ssh; 600 authorized_keys` — DSM sshd rejects keys on world-writable homes (the Synology analogue of the "home directory trap", `server/README.md:173-221`) | `truenas_client.py:289-320`, `setup_editor_account.py:156-240` |
| Password | `PUT /user/id/N` {password} | `SYNO.Core.User set` {password} or `synouser --setpw` | `truenas_client.py:330` |
| Editor password check | SMB session on :445 | **Unchanged** — DSM SMB answers the same probe; guest is off by default | `auth.py:72-107` |
| Tree root | `/mnt/tank/TheCreatorsPool/Creators_Club` (dataset) | `/volume1/<TreeShare>/<tree_name>`; shared folder via `synoshare --add` or UI, RW to `editors` | `common.py:40-46`, `setup_tree.py` |
| Group-write perms | `chown -R broll:editors` + `chmod 2770` (POSIX, on a stripped-ACL dataset) | Synology shared folders carry Windows-style ACLs (`synoacl`) which override mode bits → set an inheritable ACE for `editors` (`synoacltool -add <path> group:editors:allow:rwxpdDaARWc--:fd--`) and verify by writing as an editor over SFTP *and* SMB. **Spike this first.** | `setup_tree.py:167-180`, `install_dashboard_app.py:2461-2470` |
| Container platform | TrueNAS Apps: `POST /app {custom_app, custom_compose_config}`, `/app/redeploy`, `ix-ccsync-dashboard-1` | `sudo docker compose -p ccsync -f /volume1/<AppsShare>/ccsync/compose.yaml up -d`; containers `ccsync-dashboard-1` | `install_dashboard_app.py:111-125,2050-2116,2673-2688` |
| Host root safety regex | `^/mnt/[^/]+/apps/ccsync-dashboard(/…)*$` | `^/volume\d+/[^/]+/ccsync(/…)*$` — make it a backend property | `install_dashboard_app.py:202` |
| uid/gid in compose | `user: "3000:3001"` (broll/editors on this NAS) | Read the service user's uid and `editors` gid at install time (DSM assigns ≥1026); template `${APP_UID}:${APP_GID}` | `compose.yaml:68` |
| Syncthing | TrueNAS catalog app; API key read from UI | Container in our stack; API key generated by us and injected into both services | `install_syncthing_app.py`, `syncthing_client.py` |
| Tailscale | TrueNAS app; `docker exec tailscale tailscale status`; bind to tailnet IP | Official DSM package; binary `/var/packages/Tailscale/target/bin/tailscale`; userspace networking (inbound to NAS works; `tailscale configure-host` + boot task if TUN is needed); `tailscale serve --bg 8480` for HTTPS | `check_health.py:200-296`, `compose.yaml:191-192` |
| Postgres Project Server | TrueNAS postgres app, admin-managed | Container (`postgres:13`) — optional service under a `profiles:` switch, or admin-managed as now | `check_health.py:187` |
| SMB UNC for grade swap | Derived from `/mnt/<pool>/<rest>` → `\\host\<rest>` | `\\host\<TreeShare>\<tree_name>` — serve it from the site manifest instead of deriving | `drive_swap.py:470-491` (config key `server_p_unc` already exists) |
| Snapshots | None referenced | Snapshot Replication package: scheduled Btrfs snapshots on tree + apps shares | new |

## Work packages

### WP0 — De-tenant the seams this port needs (~1 week, precondition)

Not the whole readiness item 10 — just what makes a second NAS possible
without a fork.

1. Blank the identity defaults and fail loudly when unset:
   `dashboard/settings.py:30,44,45` (`smb_host`, `truenas_host`,
   `truenas_user`), `server/common.py:38-48`, `companion/config.py:175,651`,
   `onboarding/steps.py:104-106`, both bootstraps' `-DashboardUrl` /
   `NasSyncthingId` defaults, `tools/ship.ps1` (add `-DashboardUrl`).
2. Turn `dashboard/deploy/compose.yaml` into a template rendered by
   `compose_config()` from variables: `NAS_APPS_ROOT`, `NAS_TREE_ROOT`,
   `APP_UID/APP_GID`, `DASH_BIND` (list), `SYNCTHING_URL`; the 17 bind mounts
   become `${NAS_APPS_ROOT}/…` and `${NAS_TREE_ROOT}/…`.
3. Add a minimal `GET /api/v1/site` returning `{tree_name, remote_root,
   smb_unc, nas_syncthing_id, rclone_remote}`; companion reads `smb_unc` into
   `server_p_unc` instead of `derive_server_unc()`; installers fetch
   `nas_syncthing_id` at bootstrap when the flag is absent.
4. Site-level values (pool/share/tree name, apps root) into one `site.toml`
   read by every `server/` script (replacing per-script flags as defaults).

Done when: the TrueNAS deployment still ships end-to-end via `tools\ship.cmd`
with all values coming from `site.toml`/env and zero literal IPs, IDs, pool or
tree names left in shipped defaults (grep gate in CI).

### WP1 — Runtime `NasBackend` seam, TrueNAS behaviour unchanged (3 days)

- New package `dashboard/src/ccsync_dashboard/nas/`: `base.py` (a `Protocol`
  with `ping()`, `ensure_editors_group()`, `find_user()`, `list_editors()`,
  `is_editor()`, `create_or_update_editor(username, ssh_pubkey, full_name)`,
  `set_known_password()`, `fix_home_permissions()`, plus a shared `NasError`),
  `truenas.py` (move `truenas_client.py` verbatim), `factory.py`
  (`DASH_NAS_KIND=truenas|synology`).
- Settings: add `nas_kind`, `nas_host`, `nas_user`, `nas_pw`,
  `nas_verify_ssl`; keep `TRUENAS_*` env names as aliases for one release.
- Reroute the six call sites through the factory; `TrueNASError` → `NasError`.
- Keep `dashboard/tests/fake_truenas.py`; add a backend-parametrised fixture so
  `test_admin_users.py` and `test_auth.py` run against every backend fake.

Done when: the dashboard suite passes unchanged with `DASH_NAS_KIND=truenas`,
and the fixture runs the same admin-user tests against a second, stub backend.

### WP2 — Synology runtime backend (1 week; API shape unknown until probed)

- `nas/synology.py`: a small DSM client — `SYNO.API.Info query` to discover
  paths/versions, `SYNO.API.Auth login` (sid, `format=sid`, session name
  `ccsync`), `SYNO.Core.User list/create/set`, `SYNO.Core.Group
  list/create/member add`, `SYNO.Core.AppPriv` for the FTP privilege, logout
  on close. Version-gate every call: probe, compare to the recorded shape,
  refuse to guess.
- SSH-side operations the API doesn't cover — `authorized_keys` write,
  home-dir chmod, ACL verification — via a tiny paramiko helper using a
  dedicated admin key mounted into the container (paramiko becomes a
  dashboard dep; note its LGPL-2.1 for the NOTICE file). Same argv-hygiene as
  `server/common.py` (`shell_quote`, password on stdin, never in argv).
- `create_or_update_editor` semantics identical to TrueNAS: refuse to adopt an
  existing account not already in `editors`; never touch uid < 1026 or DSM
  built-ins (`admin`, `guest`, `anonymous`); return the same summary dict +
  warnings list.
- `dashboard/tests/fake_synology.py` mirroring `fake_truenas.py` (an HTTP fake
  for the Core API), so admin-user tests run offline.

Done when: from `/admin/users`, an admin can create an editor on a real DSM
box, and that editor can (a) log in to the dashboard (SMB probe), (b) `rclone
lsd` the tree over SFTP with their key, (c) is listed by `list_editors()`.

### WP3 — Install-time `ServerBackend` + Synology install path (2 weeks; largest)

`server/` keeps its shape (one script per job, `--dry-run` everywhere,
generated remote scripts tested under stub tools). Every platform-specific
step becomes a method on a backend object created from `site.toml`.

Interface (`server/backends/base.py`):

```python
class ServerBackend(Protocol):
    kind: str                       # "truenas" | "synology"
    host_root_re: re.Pattern        # deploy-target safety regex
    def ensure_share(self, name, path, group) ...          # dataset / shared folder
    def ensure_group(self, name) -> gid ...
    def ensure_service_user(self, name, group) -> uid ...  # the container's user
    def grant_sftp(self, group) ...                        # TrueNAS: no-op; DSM: FTP app priv
    def set_tree_acl(self, path, group) ...                # setperm/chmod vs synoacltool
    def install_syncthing(self, ...) ...                   # TrueNAS: catalog app; DSM: no-op (compose)
    def deploy_stack(self, project_dir, compose_yaml, env) # TrueNAS: POST /app; DSM: docker compose up -d
    def restart_stack(self) ...
    def stack_installed(self) -> bool ...
    def container_exec(self, name, argv) ...
    def tailscale_status_json(self) -> str ...
    def snapshot(self, path, label) ...                    # DSM: Snapshot Replication / btrfs; TrueNAS: zfs snapshot
```

Steps:

1. `backends/truenas.py`: lift the existing bodies out of
   `install_dashboard_app.py` (`app_installed`, `restart_dashboard_container`,
   the `POST /app`/`redeploy` block, `HOST_ROOT_RE`), `install_syncthing_app.py`,
   `setup_editor_account.py` (group/user/setperm), `setup_tree.py`
   (chown/chmod), `check_health.py:200-296` (tailscale via `docker exec`).
   Behaviour byte-identical; `server/tests` must stay green.
2. `backends/synology.py`:
   - `ensure_share`: `synoshare --add <name> "" /volume1/<name> "" "" 1 0` if
     missing (or refuse and instruct, if the CLI shape check fails);
     `synoshare --setuser <name> RW + editors`.
   - `ensure_group`/`ensure_service_user`: `synogroup --add`, `synouser --add`
     (nologin), read back uid/gid with `id`.
   - `grant_sftp`: FTP app privilege to `editors` (Web API `SYNO.Core.AppPriv`
     or documented one-time UI step if the API shape can't be pinned).
   - `set_tree_acl`: `synoacltool -add` inheritable RW ACE for `editors`,
     owner = service user; then a real write test as an editor via SFTP.
   - `deploy_stack`: upload compose + `.env` to `/volume1/<AppsShare>/ccsync/`,
     `sudo docker compose -p ccsync up -d --remove-orphans`; `stack_installed`
     = `docker compose ls`; `restart_stack` = `compose restart dashboard`.
   - `tailscale_status_json`: `sudo /var/packages/Tailscale/target/bin/tailscale
     status --json`.
   - `snapshot`: `synobtrfssnap` where available, else instruct to create the
     Snapshot Replication task; installer creates the scheduled task once.
3. Syncthing service in the compose template under
   `profiles: [bundled-syncthing]`: pinned `syncthing/syncthing:1.x`, `/data` =
   tree root, API key via `STGUIAPIKEY`, GUI bound to `127.0.0.1:8384`;
   `ignoreDelete`/versioning applied by the existing `setup_syncthing_folder.py`
   (unchanged — it speaks the Syncthing REST API).
4. Optional `postgres` service under `profiles: [project-server]`.
5. The deploy engine (`upload_tree`/`make_staging_dir`/`build_swap_script`/
   `build_prune_script`/ffmpeg + binaries push) stays as-is — plain SFTP +
   `sudo`, already portable; only its target root comes from the backend.
6. Tests: `server/tests` gains a `synology` parametrisation — generated remote
   scripts executed under stub `synoshare`/`synouser`/`synogroup`/
   `synoacltool`/`docker`, same Git-Bash harness (see CLAUDE.md's PATH note);
   shape-check refusals tested with a fake DSM API.

Done when: on a fresh DSM box, `install_dashboard_app.py --nas-kind synology`
brings up dashboard + Syncthing, `setup_tree.py` creates a project an editor
can write to over SFTP and SMB, `check_health.py` is green, and the TrueNAS
suite is still green.

### WP4 — Networking: loopback bind + Tailscale Serve + DSM firewall (3 days)

- Compose template: `DASH_BIND` defaults to `127.0.0.1` on Synology; installer
  runs `tailscale serve --bg --https=443 http://127.0.0.1:8480` (or the DSM
  reverse proxy for LAN) and records the resulting
  `https://<nas>.<tailnet>.ts.net` as the site's `dashboard_url`.
- Set `DASH_COOKIE_SECURE=1` when the published URL is https (the code already
  honours `X-Forwarded-Proto`).
- DSM firewall rules: allow 22 (SFTP), 445 (SMB), 22000/tcp+udp and 21027/udp
  (Syncthing) from the tailnet + LAN; deny 8480/8384 from anything but
  loopback.
- Document the `tailscale configure-host` + boot-task requirement if TUN is
  needed (subnet routes / outbound); inbound-only works in userspace mode.

Done when: a remote editor reaches the dashboard over https on the tailnet,
lanes A/B (SFTP) and C (Syncthing) connect direct or via DERP, and nothing on
the NAS listens on 0.0.0.0:8480.

### WP5 — Client-side touches (3 days)

- `companion/drive_swap.py:470-491`: prefer `server_p_unc` from the site
  manifest; keep the `/mnt/` derivation as the TrueNAS fallback and add a
  `/volume\d+/` one.
- `onboarding/steps.py` and both bootstraps: SFTP host/port from the manifest
  (DSM often runs SSH on a non-22 port — today the port is implicit); rclone
  stanza gains `port =`.
- `tools/check_deploy_drift.ps1`, `tools/ship.ps1`: read `site.toml`; drift
  check compares against the backend's container name (`ccsync-dashboard-1`
  vs `ix-…`).
- Docs: `SERVER.md` stays the TrueNAS runbook; new `SERVER-SYNOLOGY.md`;
  `installer/START_HERE.md` / `EDITOR_SETUP.md` lose their literal IPs
  (already in WP0) — the editor flow is otherwise unchanged.

Done when: a Windows and a Mac editor onboard against the Synology site with no
flags beyond the dashboard URL and their token, and the grade swap maps `P:`
to the DSM share.

### WP6 — On-device validation and performance (1 week; needs hardware)

- Matrix: fresh DSM 7.2 install → WP3 install → 2 editors (Win + Mac) → all
  three lanes → dashboard completion → b-roll insert + music send from the
  mounted UIs → "Remove from this machine" → uninstall. Repeat after a DSM
  reboot (does the compose stack auto-start with `restart: unless-stopped`?)
  and after a DSM minor update.
- Run `bench/` against the unit: `rclone_sftp` vs `rclone_smb` vs `syncthing`.
  DSM's sshd cipher set and the unit's CPU decide whether SFTP still wins; if
  not, lanes A/B may need the SMB runner promoted (the harness exists —
  `bench/ccbench/runners/`).
- Record every DSM quirk found into `GOTCHAS.md` with dates, as the repo does
  for TrueNAS.
- Snapshot + restore drill: delete a project folder, restore from the Btrfs
  snapshot, confirm Syncthing/ignoreDelete behaviour on the receivers.

Done when: the matrix passes twice on the same box, bench numbers are in
`SERVER-SYNOLOGY.md`, and the restore drill is written up.

### WP7 — Packaging the requirement and the release (2–3 days)

- Published requirements: DSM 7.2+, x86_64 model with Container Manager
  (Plus/XS/RS), Btrfs volume, ≥2.5 GbE recommended (a 1 GbE unit caps the
  whole pitch at ~110 MB/s shared), SSH enabled for an admin service account,
  User Home service on, SFTP enabled, Snapshot Replication installed,
  Tailscale package (or an https-published dashboard).
- CI: both backends' fakes in the dashboard and server suites; a "no literal
  IPs/pool names in shipped defaults" grep gate.
- Version bump + release notes; `ship.cmd` unchanged in shape (it already runs
  the server suite as its gate).

## Day-1 spikes on the device (before WP2/WP3 code)

Each is a half-day; together they retire most of the schedule risk. Write
results into `GOTCHAS.md` as you go.

| # | Question | How to answer it | If it goes badly |
|---|---|---|---|
| 1 | Do POSIX mode bits or synoacl govern a subfolder created over SFTP by editor A when editor B writes to it over SMB? | Create share, `synoacltool -add` inheritable ACE for `editors`, cross-write SFTP↔SMB as two users; inspect with `synoacltool -get` and `ls -l` | Model group-write purely as ACEs; drop the `chmod 2770` path on Synology |
| 2 | Can a non-admin (nologin) user SFTP with a pubkey, and what exactly gates it? | Create user, grant FTP privilege, write `authorized_keys`, `rclone lsd`; toggle User Home service, home perms, FTP privilege one at a time | Document as one-time UI steps; or fall back to password-auth SFTP (worse — avoid) |
| 3 | DSM Core API: exact request shape for `SYNO.Core.User create/set`, `SYNO.Core.Group member add`, `SYNO.Core.AppPriv` on this DSM version | Capture the DSM UI's own calls in browser dev tools while creating a user; replay with `curl`; record `maxVersion` from `SYNO.API.Info` | Provision purely over SSH with `synouser`/`synogroup` — slower to code, fully in our control |
| 4 | Tailscale package: does inbound work in userspace mode? Does `tailscale serve` work? Is `configure-host` needed? | Install package, `tailscale serve --bg 8480`, hit it from an editor; check `tailscale status --json` path (direct vs DERP) | DSM reverse proxy + own cert for https; treat NAS as inbound-only |
| 5 | Does `docker compose up` from SSH coexist with Container Manager, survive reboot, and bind `127.0.0.1`? | Bring up a hello-world stack; reboot; check Container Manager UI | Register the stack as a Container Manager project via `synowebapi` |
| 6 | SFTP throughput on the target CPU with rclone's `sftp_concurrency=16` / `chunk 255Ki` | `bench/` rclone_sftp + rclone_smb runners against the unit | Promote SMB (or Syncthing) for lane A/B on Synology; tune ciphers |
| 7 | Which uid/gid do the service user and `editors` get; do bind-mounted dirs keep them across DSM updates? | `id`, create files from the container, `ls -n`; run a DSM update if one is pending | Template `APP_UID/APP_GID` from live values at every deploy |
| 8 | Btrfs snapshots: can we schedule + restore a single subfolder from CLI? | Snapshot Replication task on the share; delete a project; restore | Require the UI-created task; still verify restore |

## Suggested sequence

- **Week 1:** unit on the desk. Spikes 1–8 in parallel with WP0. Decisions
  2/4/5 confirmed or revised from spike results.
- **Week 2:** WP1 (runtime seam, TrueNAS unchanged) → WP2 (Synology runtime
  backend + fake). First editor created from the dashboard on DSM.
- **Weeks 3–4:** WP3: server backend interface, TrueNAS lift-and-shift,
  Synology install path, bundled Syncthing. WP4 networking alongside.
- **Week 5:** WP5 client touches; WP6 validation matrix + bench + restore drill.
- **Week 6:** buffer for whatever the spikes underestimated; WP7 requirements
  doc, CI gates, release.

The estimate assumes the same engineer who built the TrueNAS path, a Synology
unit from day 1, and no scope creep into full multi-tenancy or SSO. If the DSM
Core API turns out too unstable to pin (spike 3), add ~3 days for an all-SSH
provisioning path.

## Risks worth naming

- **High — synoacl vs mode bits** can silently break the group-write model the
  way NFSv4 ACLs did on TrueNAS. Spike 1 exists for this reason.
- **Med — DSM Core API drift** across DSM minor versions; the
  shape-check-and-refuse pattern protects you, but each DSM release may need
  a recorded shape.
- **Med — throughput:** many Synology units are 1 GbE and CPU-light; the
  product's promise is bandwidth. State the hardware floor honestly.
- **Med — Tailscale userspace mode** changes the networking story enough that
  the "bind to two IPs" design has to go — the right change anyway.
- **Low — support surface:** two backends means every server-side bug is now
  "which NAS?" — keep the fakes and the parametrised suites honest so CI
  answers before a customer does.

## Definition of done for the port

- A fresh DSM 7.2 x86 unit + `site.toml` → one `install_dashboard_app.py
  --nas-kind synology` → dashboard, Syncthing, (optionally) Postgres up;
  snapshot task created.
- Admin creates an editor from `/admin/users`; that editor onboards on Windows
  and macOS with the stock installer; lanes A/B/C go green; grade swap maps
  `P:`; b-roll and music UIs work including "Send to Resolve";
  `check_health.py` passes.
- The TrueNAS deployment is unaffected: same ship command, suites green, no
  behaviour change.
- Both backends covered by offline fakes in CI; a grep gate keeps identity
  literals out of shipped defaults.
- `SERVER-SYNOLOGY.md` written from the validated run, with bench numbers and
  every quirk dated in `GOTCHAS.md`.

## WP8 — one-click install for non-technical owners (follow-on)

Designed separately in `SYNOLOGY_EASY_INSTALL.md` (2026-08-17): a Synology
Package (`.spk`) as the root-level bootstrap (wizard → shares/group/SFTP/ACL →
render the WP0 compose template → `compose up` → `tailscale serve` → snapshot
schedule → DSM app icon), a first-run **Setup checklist** page in the
dashboard, and **invite links** that replace the seven per-editor touchpoints.
Its hard prerequisite is a real container image (readiness item 12), which
should be pulled forward. Sequencing: after WP4, in parallel with WP5–WP7.
