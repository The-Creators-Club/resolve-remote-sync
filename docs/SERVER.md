# Server Runbook -- Creators Club Sync

Admin-facing runbook for TrueNAS-side operations. All scripts referenced
live in `../server/`; see `../server/README.md` for env vars and per-script
assumptions. Every script supports `--dry-run` -- use it first.

## Onboarding a new editor, end to end

1. Get their SSH public key (`.pub` file -- they generate the keypair
   locally, per `docs/EDITOR_SETUP.md`; you only ever receive the public
   half).
2. Create their TrueNAS account:
   ```
   python server/setup_editor_account.py --name jsmith --ssh-pubkey-file jsmith.pub --tailnet-host <nas-tailnet-host>
   ```
   This creates (or updates) the user, adds them to the `editors` group
   (creating that group if it doesn't exist yet), installs their SSH key,
   enables SMB access, and -- critically -- fixes the home directory's
   ownership and mode. Without that last step sshd refuses the editor's key
   and lanes A/B fail with an error that looks exactly like "no key
   installed"; see **The home directory trap** in `../server/README.md`.
3. **Set them a known password.** `setup_editor_account.py` creates the
   account with a **random** password that nobody, including you, knows.
   Every editor-facing sign-in gate uses it: the wizard's account check, the
   tray's `Sign in…`, and the dashboard login. Skip this and the editor
   completes their whole install and is then rejected with no way past it.
   Set one from the dashboard's `/admin/users` > **Set a known password**,
   from TrueNAS UI > Credentials > Users, or with
   `PUT /api/v2.0/user/id/<id> {"password": "..."}`. Sync itself (SSH +
   rclone) never needs it -- that stays key-only.
4. Send the editor: the tailnet hostname of the NAS, their username and that
   password, the dashboard URL + `dashboard_token`, and the printed rclone
   remote stanza (they don't need to type that by hand --
   `installer/windows_bootstrap.ps1` / `installer/macos_bootstrap.sh`
   write it for them, they just need the tailnet host + their own
   username as script arguments).
5. Editor runs `onboard.exe` (or their bootstrap script -- see
   `docs/EDITOR_SETUP.md`) and sends you their Syncthing device ID.
6. Approve their device **once**, and give it their TrueNAS username. No
   `--folder-id`, no per-project step:
   ```
   python server/accept_device.py --device-id <their-id> --device-name <their-username> --gui-url <syncthing-gui-url> --api-key <syncthing-api-key>
   ```
   That accepts and names the device and touches no folders. Which projects
   reach the editor is decided by what they tick on the dashboard: the
   `enforce` collector cycle adds their device to the folders they ticked
   and removes it when they untick -- see **Workflow change** below. The
   dashboard's `/admin/users` > **Approve device** does exactly the same job
   from a browser.

   `--device-name` is the part that matters: an unnamed device shows as
   `[ UNMAPPED ]` and enforcement never touches it, so it will sync nothing
   no matter what gets ticked. `--folder-id` still exists, but only for the
   legacy case -- an editor not managed by the dashboard, or a one-off
   repair while the dashboard is down.
7. Give them the Resolve Project Server credentials (Postgres user/pass for
   whichever project database they're joining) -- this is managed via
   Resolve's own Project Server tooling, not by these scripts.
8. Run `python server/check_health.py` and confirm their account shows up
   under the editor-accounts check. Then check the dashboard: their machine
   should be reporting, and they need to have ticked at least one project --
   nothing syncs until both are true.

**Previously an open question, now resolved:** TrueNAS 25.10 refuses to
combine `password_disabled` with SMB at all, rejecting it with HTTP 422
*"Password authentication may not be disabled for SMB users."* The API blocks
the combination up front rather than silently breaking SMB, so there is
nothing to decide by hand: editor accounts keep password login enabled and
SMB working, and SSH is still effectively key-only because sshd itself runs
with `PasswordAuthentication no`. `setup_editor_account.py` treats that 422
as the expected answer.

## Onboarding a new project

Projects live anywhere under `Creators_Club/Projects/` at **any depth**
(e.g. `2026/CCT/Creator Profiles/Season 1`) — since 2026-07-25 a directory
is a project because it carries a hidden `.ccsync-project` **marker file**
(its `slug` field is the project's permanent identity), not because of its
depth. Containers/sub-categories nest freely; projects never nest. Moving
or renaming a project directory on the NAS is now safe: the marker travels
with it, the dashboard retargets the Syncthing folder automatically within
one provision cycle (~5 min), and editors' companions (v0.4.0+) move their
local copies to match. Bare folders without markers are invisible to sync
until claimed via the dashboard's `/project-setup` picker (LINK THIS
FOLDER) or `server/write_marker.py`.

**Self-serve path (added 2026-07-25):** when someone opens a Resolve project
the server doesn't recognize, their companion prompts them and deep-links to
the dashboard's `/project-setup` page, where any signed-in editor can either
**link** the Resolve project to an existing tree folder (first-set only —
changing an existing mapping stays admin-only) or **create** the
`Projects/<year>/<series>/<project>` folder right there, template subfolders
included (the dashboard's `/projects` mount is now **rw**; the container
runs as `broll:editors`, so ownership matches `setup_tree.py`'s). The
Syncthing folder then auto-provisions within ~5 minutes as usual. The tray
menu also offers "Set up '<project>' on the server…" whenever the open
project is unmapped. The CLI below remains the manual/fallback path.
Deploying this change needs `install_dashboard_app.py --recreate` (mount
change).

**Editors need no configuration change when a project is added** -- but a new
project does **not** sync to anyone by itself. Nothing is shared until an
editor ticks it on the dashboard; from then on all three lanes work on the
ticked projects only, one project at a time. So a new project appears in
every editor's dashboard list on the next provision cycle (~5 min), and
starts moving for whoever ticks it.

1. Create the folder tree:
   ```
   python server/setup_tree.py --year 2026 --series "Creator Profiles" --project "Season 1"
   python server/setup_tree.py --year 2025 --series FF4 --project Nuclear
   ```
   Creates `Creators_Club/Projects/<year>/<series>/<project>/{AE, Audio/Music,
   Audio/Voiceover, B-roll, Interviewees, Render in Place, Subs, Youtube}`,
   owned `broll:editors`, mode `2770` (setgid, so anything editors create
   stays group-writable for other editors too). `Proxy/` subfolders are
   **not** pre-created -- see "Where proxies come from" below. Quote any
   argument containing spaces; the script shell-quotes them on the remote
   side, so `Creator Profiles` and `Season 1` are handled correctly.
2. **Lane C is automatic when the dashboard is running.** The dashboard's
   collector scans the Projects tree every 5 minutes and creates the
   Syncthing folder for any marked project dir it finds -- same config the
   manual script produces (staggered versioning, ignore list of video
   extensions + `**/Proxy`). It is created **unshared**: the `enforce` cycle
   then shares it with the devices of whoever ticks it on the dashboard, and
   unshares it when they untick. The folder id is the marker's slug, normally
   the slugified relative path (`2026/Creator Profiles/Season 1` →
   `2026-creator-profiles-season-1`).

   Manual fallback (dashboard not deployed, or a nonstandard folder):
   ```
   python server/setup_syncthing_folder.py --project-rel-path "2026/Creator Profiles/Season 1" --gui-url <url> --api-key <key>
   ```
   Only when the dashboard is **not** deployed does sharing need doing by
   hand (`accept_device.py --folder-id …`); with the dashboard running,
   enforcement would revert it -- see **Workflow change** below.

   Note the trigger is the **tree**, not the Resolve project database --
   creating a project in Resolve's Project Manager does not create a media
   folder anywhere, and a Resolve project name carries no year/series path,
   so step 1 (setup_tree.py) is what makes the project real to the sync
   system and the dashboard.
4. Set up the Resolve Project Server database for this project (Resolve's
   own Project Manager tooling on the host, not scripted here) and the
   Blackmagic Proxy Generator watch folder (see below).
5. Give editors their DB credentials.

## Delete / rename rules (see SPEC.md "Flaws" #2)

This is the single most important thing to get right as an admin, because
it's asymmetric and easy to get bitten by:

- **Lane A (video originals, editor -> NAS, rclone)** never deletes
  anything on the NAS. This is intentional (archival safety net against a
  clumsy local delete propagating upstream). The consequence: **if an
  editor renames or moves a folder locally, the NAS ends up with the old
  copy *and* the new one** -- rclone just uploads under the new name/path
  and the stale original sits there forever.
- **Lane B (proxies, NAS -> editor, rclone)** mirrors the server exactly,
  so **reorganize projects on the server (host) side, never on an
  editor's machine.** When you rename/move something server-side, lane B
  will propagate that rename down to every editor automatically.
- **Lane C (everything else, bidirectional, Syncthing)** does propagate
  deletes and renames in both directions -- but the server keeps staggered
  versioning (a versioned trash), so a mistaken delete is recoverable from
  the server's Syncthing folder version history, not gone for good.

Practical rule for editors (documented for them too, in
`docs/EDITOR_SETUP.md`): reorganize video folders by asking the admin to do
it server-side; reorganize everything else (audio/AE/subs/etc.) locally,
it'll propagate correctly.

## Where proxies come from

The **Blackmagic Proxy Generator (BPG)** runs on the base rig (the host),
watching per-project folders under `P:` (the host's own SMB mount of the
same tree). It natively decodes BRAW (ffmpeg can't), is GPU-accelerated,
preserves timecode, and writes proxies into the existing in-place `Proxy/`
subfolder convention next to the source media -- exactly what Resolve
auto-links against (same filename + timecode in the adjacent `Proxy/`
folder). Output format is H.264 1080p for cross-platform compatibility.

This means: **BPG only proxies media it can see on `P:`.** Since editors'
uploads (lane A) land in the same tree on the NAS, and the host's `P:` is
just an SMB mount of that same NAS path, anything an editor uploads gets
picked up by BPG's watch folder automatically -- no separate step needed,
other than BPG being on and pointed at the right watch folders per
project. **BPG depends on the host PC being on** (there's Wake-on-LAN
configured for it as a mitigation); a NAS-side ffmpeg fallback container
for non-BRAW formats when the PC is off is a documented future nice-to-have,
not built yet.

## Health check

```
python server/check_health.py --gui-url <syncthing-gui-url> --api-key <syncthing-api-key>
```

Prints plain PASS/FAIL lines for: Postgres reachable on `:5432`, the
Tailscale app's container is logged in (and its tailnet IP), Syncthing app
reachable + its folder list, the project tree root exists, and the
`editors` group has members. Exit code is the number of failed checks (0 =
all good) -- wire this into whatever monitoring/cron you want later.

## Sync status dashboard

A web dashboard (`dashboard/` in the repo) runs on the NAS as a TrueNAS
custom app and shows live per-project, per-editor sync state: completion %,
who is fully synced, exactly which files each editor is missing (lane C from
the server Syncthing's REST API), plus each companion's reported lane A/B
status. Tailnet-only, and editors sign in with their TrueNAS account (see
"Login + per-editor project selection" below): `http://<tailnet-ip>:8480/`.

Install / redeploy (**code** changes are picked up by re-running the same
command; anything compose-level needs `--recreate` -- see Operational notes):

```
SYNCTHING_API_KEY=<key> DASH_REPORT_TOKEN=<shared-secret> \
    DASH_SESSION_SECRET=<session-secret> TRUENAS_PW=... \
    python server/install_dashboard_app.py [--dry-run]
```

`DASH_SESSION_SECRET` is **required** -- the install fails without it. It
signs editors' login cookies, so invent it once (`openssl rand -hex 32`) and
keep it stable across deploys: changing it logs every editor out. Setting it
also turns on report identity checking (see Operational notes below).

`DASH_REPORT_TOKEN` is a static shared secret you invent once (e.g.
`openssl rand -hex 24`); each editor puts the same value in
`~/.ccsync/config.toml` as `dashboard_token` (with `dashboard_url =
"http://<tailnet-ip>:8480"`) so their companion can POST lane A/B status.
Reports without the token are rejected -- the tailnet gates *reading* the
dashboard, the token gates *writing* to it. The token is no longer
sufficient on its own: the companion must also present the identity from the
editor's tray sign-in.

`TRUENAS_VERIFY_SSL` is an env var on the **deployed app** (written into the
compose config by the install script, default `0`). It controls whether the
dashboard verifies the NAS's TLS certificate when it calls the TrueNAS API
for the `/admin/users` section. `0` is the existing behaviour and the right
answer for the usual self-signed certificate over the tailnet; set it to `1`
once the NAS carries a certificate that actually validates.

Optional flags, each with an env-var equivalent:

| Flag | Env var | Default | What it's for |
|---|---|---|---|
| `--bind-lan` | `DASH_BIND_LAN` | `192.168.0.102` | The LAN address the dashboard is published on (the base rig reaches it here). |
| `--bind-tailnet` | `DASH_BIND_TAILNET` | `100.71.216.3` | The tailnet address remote editors reach it on. |
| `--image` | `DASH_IMAGE` | `python:3.12.7-slim` | Pinned base image for the container. |
| -- | `TRUENAS_VERIFY_SSL` | `0` | See above. |

The two bind addresses are deliberately never `0.0.0.0`, so a new NAS
interface can't silently expose the dashboard. The flip side: **when the
NAS's DHCP lease or its tailnet IP moves, these become wrong and Docker
refuses to start the app** with *"cannot assign requested address"* -- the
app is simply down until you re-deploy with the new values.

Operational notes:

- State lives in SQLite at `/mnt/tank/apps/ccsync-dashboard/data/dashboard.db`
  (survives redeploys; the `app/` dir is replaced on every install run,
  `data/` is never touched). Published companion builds sit alongside it in
  `data/packages/`.
- **Host-dir ownership** (the install script sets all of this; do not loosen
  it by hand):

  | dir     | owner       | mode  | why |
  | ------- | ----------- | ----- | --- |
  | `app/`  | `root:root` | `755` | the container's `command:` runs `app/deploy/run.sh` and mounts `/app` **:ro** -- a group-writable code dir was an editor→NAS-admin escalation (AUDIT C-1). |
  | `venv/` | `3000:3000` | `700` | run.sh execs `venv/bin/python`. Its own volume, mounted at `/venv`. |
  | `data/` | `3000:3000` | `770` | SQLite DB + `packages/`. Group **3000**, *not* 3001/`editors`. |

  The venv used to live at `data/venv` while `data/` was `3000:3001` mode
  `770` -- group `editors`, every one of whom has a real shell account on the
  NAS. Replacing that interpreter (or anything under its `site-packages`) was
  arbitrary code execution as the dashboard user, in a container holding
  `TRUENAS_PW` (AUDIT C-2). Re-running `install_dashboard_app.py` moves any
  pre-existing `data/venv` aside to `data/venv.quarantined.<ts>` (never
  deletes it) and rebuilds a clean one at `venv/`; a **`--recreate`** is
  required for the container to pick up the new `/venv` mount.
- **Auto-provisioning**: the collector scans the Projects tree (mounted
  **rw** at `/projects` -- see the self-serve path above) every 5 minutes and
  creates a Syncthing folder for any directory carrying a `.ccsync-project`
  marker, at **any depth**, that lacks one -- see "Onboarding a new project"
  above. Folders are created **unshared**; sharing is driven by editors'
  dashboard ticks via the `enforce` cycle, so a brand-new folder syncs to
  nobody until someone ticks it. Disable provisioning by removing
  `DASH_PROJECTS_DIR` from the app env. It never deletes a folder, but it
  does modify existing ones: it PATCHes a folder's path and label when its
  marker moves on the NAS (retargeting), and enforcement rewrites the folder's
  device list.
- **Everything compose-level is baked in when the container is created**:
  the two bind addresses, the image tag, the healthcheck, the mounts, the
  ports, and every env var (`DASH_BIND_LAN`, `DASH_BIND_TAILNET`,
  `DASH_IMAGE`, `TRUENAS_VERIFY_SSL`, the tokens, `DASH_ADMIN_USERS`…).
  Changing any of them needs
  `python server/install_dashboard_app.py --recreate`. A plain re-run only
  uploads code and restarts the container **with the old compose**, so the
  change appears to do nothing at all -- no error, same behaviour, and you
  will chase it somewhere else. The script prints a reminder to that effect
  after a plain re-run; believe it.
- `--recreate` deletes and re-creates the app; the host `app/` and `data/`
  dirs (and therefore the DB, the published packages and every editor's
  ticks) survive. **Supply `DASH_REPORT_TOKEN` and `DASH_SESSION_SECRET`
  again when you do** -- they are not read back off the running app, so
  omitting one silently deploys a fresh value: a changed report token stops
  every editor's companion reporting, and a changed session secret logs
  every editor out of the dashboard. Keep both stored somewhere you can
  paste from.
- The collector polls Syncthing every 15-60s per endpoint and keeps 30 days
  of completion history. If Syncthing is down the UI shows a "SYNCTHING
  UNREACHABLE" banner and the collector backs off to 5-minute retries.
- Health dots roll up red > amber > green: red = a lane error, an editor
  offline 15+ min while behind, or stale data; amber = syncing/behind;
  green = fully synced and idle. `GET /api/v1/health` is the
  machine-readable liveness endpoint. **Unauthenticated callers (the Docker
  healthcheck, `check_install.ps1`) get `{"ok", "version"}` only**; the full
  body -- per-project Syncthing folder errors, slugs and labels -- needs a
  session cookie or the companion's `X-CCSync-Token`, because the endpoint is
  open by design and that body was a readable client roster.
- **`/api/v1/verify` only mints an identity for fleet members.** The
  credential check is an SMB session setup, so any account the NAS's SMB
  service accepts used to get a machine-identity token *and* the shared
  report token. The account must now be in the `editors` group (or
  `DASH_ADMIN_USERS`); non-members get a 403 pointing at Admin > Users. With
  no `TRUENAS_PW` configured the check is skipped and logged (same
  degrade-don't-crash rule as the Users section); with TrueNAS configured but
  unreachable it answers 503 rather than opening up.
- Devices whose Syncthing name is not a TrueNAS username show as
  `[ UNMAPPED ]` -- always pass `--device-name <username>` to
  `accept_device.py` so the dashboard can attribute them.
- **Reports require the editor's tray sign-in, not just the token.**
  Whenever `DASH_SESSION_SECRET` is set (i.e. always, in production),
  `POST /api/v1/report` returns **401** unless the companion also sends a
  valid `X-CCSync-Identity` header matching its `editor_name`. The shared
  `DASH_REPORT_TOKEN` alone is no longer enough -- previously anyone holding
  it could post reports as any editor. Practical consequence: a machine that
  has never been signed in via the tray's `Sign in…` 401s on every report and
  **never appears on the fleet grid**.

**Troubleshooting: an editor is missing from the fleet grid.** Work down this
list -- it's almost always the first item:

1. **They haven't signed in from the tray.** Right-click tray icon →
   `Sign in…`; the tray must read `Signed in as <them>`. Without it the
   companion has no identity header, every report 401s, and the machine is
   invisible here even though it's installed and running. It also isn't
   syncing -- `require_login` gates the lanes on the same thing.
2. **They have no password to sign in with** -- see step 3 of "Onboarding a
   new editor" above; the account is created with a random one.
3. **No `dashboard_token`** in their `~/.ccsync/config.toml` (or a blank one
   written by a re-run of the wizard): reports are rejected before identity
   is even considered.
4. **An old companion.** Builds predating the identity header cannot satisfy
   the check and will show as rejected until the editor upgrades. Publish a
   build and have them click the tray's `Update now`.

### Login + per-editor project selection

Editors sign in with their **TrueNAS username/password** (verified via an SMB
authentication probe on :445 -- the only method 25.10 allows for non-admin
users; the middleware rejects them outright, verified 2026-07-24).

**Gotcha: `setup_editor_account.py` creates accounts with a RANDOM password**
(nobody knows it -- SSH is key-only and SMB was never used interactively).
Before an editor can log into the dashboard, set them a known password:
TrueNAS UI > Credentials > Users, or `PUT /api/v2.0/user/id/<id>
{"password": "..."}`. Sync itself never needs the password. Once
signed in, each editor ticks the projects they want synced; the queue syncs
**one project at a time, in tick order**. Env: `DASH_SESSION_SECRET`
(required, keep stable across deploys), `DASH_ADMIN_USERS` (csv of accounts
that may manage anyone's ticks -- note the account must be able to
SMB-authenticate, so `truenas_admin` only works if SMB-enabled; use an
SMB-enabled personal account otherwise), `DASH_AUTH_METHOD=smb`,
`DASH_SMB_HOST`.

The `enforce` collector cycle (60s) makes the selections table the authority
for folder sharing: tick -> the editor's device(s) are added to the folder;
untick -> removed (their local files remain). On its first ever run it
**seeds** selections from the folder shares that existed at upgrade time, so
nothing stops syncing on rollout. Devices not named after a TrueNAS username
are never touched by enforcement.

**Workflow change:** do not use `accept_device.py` to share folders anymore
-- enforcement would revert any hand-made share for a mapped editor within a
minute. It remains the tool for accepting + naming new devices. New folders
are auto-provisioned **unshared** and start syncing when someone ticks them.
- If the custom-app POST is ever rejected (middleware schema drift), paste
  `dashboard/deploy/compose.yaml` into TrueNAS UI > Apps > Install via YAML
  instead; the script prints this fallback.

### Admin: Users section

`/admin/users` (linked as `[ USERS ]` in the header for admins) replaces the
CLI for the two most common onboarding actions, when the dashboard has
`TRUENAS_PW` configured:

- **Create/update an editor account** -- username + SSH public key (+
  optional full name / known password). Same logic as
  `server/setup_editor_account.py`: ensures the `editors` group, installs the
  key, enables SMB, fixes home-directory ownership/mode (the "home directory
  trap" in `server/README.md`). One difference: this path cannot re-verify
  the fix over SSH (the dashboard has no SSH credentials, only the TrueNAS
  API), so it trusts the `filesystem.setperm` job's result; run
  `server/check_health.py` if you want the independent SSH-based check too.
- **Approve a pending/unmapped Syncthing device** -- assign it a username.
  Covers both a device dialing in for the first time (`pending`) and one
  that's configured but was never given a real username (`unmapped`, e.g.
  added by hand without `--device-name`). This does **not** share any
  folder with the device -- same reasoning as the `accept_device.py`
  workflow change above: sharing is the selections table's job. Once
  approved, the editor logs into the dashboard and ticks the projects they
  need.
- **Set a known password** on any existing editor account -- the same
  action the "Gotcha" above describes doing by hand via the TrueNAS UI or
  `PUT /api/v2.0/user/id/<id>`.

Leaving `TRUENAS_PW` unset on the dashboard app disables only this section
(shown as unavailable); everything else keeps working. The already-deployed
app needs `install_dashboard_app.py --recreate` (not a plain re-run) to pick
up newly-added env vars like `TRUENAS_HOST`/`TRUENAS_USER`/`TRUENAS_PW` --
see that script's docstring.

### Publishing a companion update (upgrade channel)

The dashboard hosts published companion builds under `/data/packages/` and
advertises the **current** one to every reporting companion; out-of-date
machines get an amber `[ OUT OF DATE ]` chip in the fleet grid and a tray
"Update now" item on the editor's machine (notify + one-click -- nothing
updates silently). Publish flow, from the base rig:

1. Bump `VERSION` in **both** `companion/src/ccsync_companion/config.py` and
   `companion/pyproject.toml` (publishing refuses on drift, and refuses to
   re-publish an existing version).
2. `.\installer\build_editor_package.ps1 -RebuildExe -Publish [-MakeCurrent]`
   -- builds, assembles the NAS package as usual, then prompts for the
   dashboard admin password and PUTs the exe to
   `/api/v1/admin/packages/windows/<version>`.
3. Without `-MakeCurrent`, the build is staged: flip `[ MAKE CURRENT ]` in
   the `[ COMPANION PACKAGES ]` box on `/admin/users` when ready.
4. Watch the fleet grid: each machine's VERSION cell goes amber until its
   editor takes the tray's offer ("Update available → vX.Y" when the
   published build is newer; "Roll back to vX.Y" when you have deliberately
   pointed CURRENT at an older build). The
   companion downloads via the dashboard (sha256-verified), swaps its own
   exe, and restarts itself; a failed swap rolls back and keeps the old
   build running.

**Publishing keeps every build.** Old versions are no longer pruned as a
side effect of publishing a new one -- the safer default, since rollback is
only as deep as the builds still on disk. To get the old "current + 2 newest
per platform" behaviour back, add `?prune=1` to the publish URL for that one
publish. Deleting a build stays a deliberate act (`[ DELETE ]` in
`[ COMPANION PACKAGES ]`); the current version can never be deleted.

**Nothing is offered to a companion that doesn't report its platform.**
An unknown platform used to be treated as `windows`, which meant a Mac could
be handed a `.exe`. It now simply gets no advertisement -- so older
companions that don't send a platform quietly stop being offered updates and
sit at their version until upgraded by hand (`windows_upgrade.ps1`).

**Rollback** = `[ MAKE CURRENT ]` on an older version -- the fleet is
offered the downgrade exactly like an upgrade ("different", not "newer").
Companions on the current version get no advertisement at all, so the tray
item disappears on its own within a report interval (~60s).
