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
3. Send the editor: the tailnet hostname of the NAS, their username, and
   the printed rclone remote stanza (they don't need to type it by hand --
   `installer/windows_bootstrap.ps1` / `installer/macos_bootstrap.sh`
   write it for them, they just need the tailnet host + their own
   username as script arguments).
4. Editor runs their bootstrap script (`docs/EDITOR_SETUP.md`) and sends
   you their Syncthing device ID.
5. For each project they need:
   ```
   python server/accept_device.py --device-id <their-id> --folder-id <project-folder-id> --gui-url <syncthing-gui-url> --api-key <syncthing-api-key>
   ```
   (`<project-folder-id>` is the slug printed by `setup_syncthing_folder.py`
   when the project was created, e.g. `2026-creator-profiles-season-1`.)
   Only lane C needs this per-project step -- lanes A and B already replicate
   the whole tree, so the editor sees every project without further setup.
6. Give them the Resolve Project Server credentials (Postgres user/pass for
   whichever project database they're joining) -- this is managed via
   Resolve's own Project Server tooling, not by these scripts.
7. Run `python server/check_health.py` and confirm their account shows up
   under the editor-accounts check.

**Previously an open question, now resolved:** TrueNAS 25.10 refuses to
combine `password_disabled` with SMB at all, rejecting it with HTTP 422
*"Password authentication may not be disabled for SMB users."* The API blocks
the combination up front rather than silently breaking SMB, so there is
nothing to decide by hand: editor accounts keep password login enabled and
SMB working, and SSH is still effectively key-only because sshd itself runs
with `PasswordAuthentication no`. `setup_editor_account.py` treats that 422
as the expected answer.

## Onboarding a new project

Projects live at `Creators_Club/Projects/<year>/<series>/<project>` — any
year, any series, any project name, including names with spaces. Nothing is
hardcoded to a particular show; the examples below just use two real ones.

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

**Editors need no configuration change when a project is added.** Lanes A and
B replicate `Creators_Club` as a whole tree, so a new project appears on
every editor's machine on the next pass. Only lane C (Syncthing) is
per-project, which is what steps 2 and 3 set up.

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
   Syncthing folder for any new project dir it finds -- same config the
   manual script produces (staggered versioning, ignore list of video
   extensions + `**/Proxy`), shared to **every** configured editor device.
   The folder id is the slugified relative path (`2026/Creator Profiles/
   Season 1` → `2026-creator-profiles-season-1`). Editors just accept the
   share prompt in their local Syncthing.

   Manual fallback (dashboard not deployed, or a nonstandard folder):
   ```
   python server/setup_syncthing_folder.py --project-rel-path "2026/Creator Profiles/Season 1" --gui-url <url> --api-key <key>
   python server/accept_device.py --device-id <their-id> --folder-id 2026-creator-profiles-season-1 --gui-url <url> --api-key <key>
   ```

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

The **Blackmagic Proxy Generator (BPG)** runs on Alex's PC (the host),
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
status. Tailnet-only, no login: `http://<tailnet-ip>:8480/`.

Install / redeploy (code changes are picked up by re-running the same
command):

```
SYNCTHING_API_KEY=<key> DASH_REPORT_TOKEN=<shared-secret> TRUENAS_PW=... \
    python server/install_dashboard_app.py [--dry-run]
```

`DASH_REPORT_TOKEN` is a static shared secret you invent once (e.g.
`openssl rand -hex 24`); each editor puts the same value in
`~/.ccsync/config.toml` as `dashboard_token` (with `dashboard_url =
"http://<tailnet-ip>:8480"`) so their companion can POST lane A/B status.
Reports without the token are rejected -- the tailnet gates *reading* the
dashboard, the token gates *writing* to it.

Operational notes:

- State lives in SQLite at `/mnt/tank/apps/ccsync-dashboard/data/dashboard.db`
  (survives redeploys; the `app/` dir is replaced on every install run,
  `data/` is never touched).
- **Auto-provisioning**: the collector scans the Projects tree (mounted
  read-only at `/projects`) every 5 minutes and creates + shares a Syncthing
  folder for any `<year>/<series>/<project>` dir that lacks one -- see
  "Onboarding a new project" above. Disable by removing `DASH_PROJECTS_DIR`
  from the app env. It never modifies or deletes existing folders.
- Compose changes (env vars, mounts, ports) need
  `python server/install_dashboard_app.py --recreate` -- a plain re-run only
  refreshes code. `--recreate` deletes and re-creates the app; the host
  `app/` and `data/` dirs (and therefore the DB) survive. Pass the existing
  `DASH_REPORT_TOKEN` when re-creating or editors' tokens stop matching.
- The collector polls Syncthing every 15-60s per endpoint and keeps 30 days
  of completion history. If Syncthing is down the UI shows a "SYNCTHING
  UNREACHABLE" banner and the collector backs off to 5-minute retries.
- Health dots roll up red > amber > green: red = a lane error, an editor
  offline 15+ min while behind, or stale data; amber = syncing/behind;
  green = fully synced and idle. `GET /api/v1/health` is the
  machine-readable liveness endpoint.
- Devices whose Syncthing name is not a TrueNAS username show as
  `[ UNMAPPED ]` -- always pass `--device-name <username>` to
  `accept_device.py` so the dashboard can attribute them.

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
   editor clicks the tray's "Update available → vX.Y — Update now". The
   companion downloads via the dashboard (sha256-verified), swaps its own
   exe, and restarts itself; a failed swap rolls back and keeps the old
   build running.

**Rollback** = `[ MAKE CURRENT ]` on an older version -- the fleet is
offered the downgrade exactly like an upgrade ("different", not "newer").
The server auto-prunes to the current + 2 newest other versions per
platform; the current version can never be deleted. Companions on the
current version get no advertisement at all, so the tray item disappears on
its own within a report interval (~60s).
