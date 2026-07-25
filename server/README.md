# server/ -- Creators Club Sync: server-side setup scripts

Scripts that provision the TrueNAS side of the Resolve remote-sync system:
project tree, editor accounts, the Syncthing app + per-project folders, and
a one-shot health check. See `../SPEC.md` (S1 Server setup) for the design
this implements.

**Live status.** Three of these have now been exercised against the real
NAS and carry the confirmation in their own source: `setup_editor_account.py`
(home-directory ACL behaviour confirmed against live 25.10),
`install_syncthing_app.py` (chart schema confirmed against the live TrueNAS
25.10.4 stable/syncthing 1.3.11 questions.yaml, 2026-07-22) and
`install_dashboard_app.py` (bind-mount inode behaviour seen live 2026-07-24).
The rest were written to spec, `python -m py_compile`'d, and unit-tested for
their pure logic (slug generation, template folder list, `.stignore` content)
only. Every script has a `--dry-run` flag that prints the exact SSH command /
API call it would make without opening any connection -- still worth running
first, especially for anything not in that confirmed list.

## Run order

For first-time setup:

1. `install_syncthing_app.py` -- once, installs Syncthing (lane C engine).
2. `install_dashboard_app.py` -- once, installs the sync dashboard (project
   selection, provisioning, share enforcement, the upgrade channel). Re-run
   to ship code changes; `--recreate` for compose/env changes.
3. `setup_tree.py --year Y --series S --project P` -- once per new project.
   (Or let an editor create it from the dashboard's `/project-setup` page.)
4. `setup_syncthing_folder.py --project-rel-path Y/S/P` -- once per new
   project, and only when the dashboard isn't deployed: with it running, the
   collector provisions the folder itself within ~5 minutes.
5. `setup_editor_account.py --name X --ssh-pubkey-file path.pub` -- once per
   new editor. Then **set them a known password** (dashboard `/admin/users`,
   or the TrueNAS UI) -- the account is created with a random one and every
   editor-facing login needs it.
6. Editor runs `onboard.exe` (or `installer/windows_bootstrap.ps1` /
   `installer/macos_bootstrap.sh`), sends back their Syncthing device ID.
7. `accept_device.py --device-id ... --device-name <username>` -- once per
   editor **machine**, not per project, and with **no `--folder-id`**: it
   accepts and names the device and shares nothing. Which projects reach
   them is decided by their dashboard ticks. The dashboard's
   `/admin/users` > **Approve device** is the same action from a browser.
8. `write_marker.py` -- as needed, to adopt an existing folder as a project
   or repair a lost marker with an explicit `--slug`.
9. `check_health.py` -- any time, to validate the whole server side.

See `../docs/SERVER.md` for the narrative admin-runbook version of this
(onboarding an editor end-to-end, onboarding a project, delete/rename rules).

**Steps 5 and 7 also have a dashboard equivalent.** If `ccsync-dashboard` is
deployed with `TRUENAS_PW` set, its admin-only `/admin/users` page can create
editor accounts, set them a known password, and approve/name pending
Syncthing devices from a browser instead of the CLI -- see "Admin: Users
section" in `../docs/SERVER.md`. It's a convenience layer over these same
two scripts' logic, not a replacement: the CLI scripts remain the tools of
record and work whether or not the dashboard is deployed. Note it
deliberately does NOT touch folder shares (step 7's old folder-sharing
behavior) -- see "Workflow change" in `../docs/SERVER.md`: sharing is decided
by the dashboard's per-editor selections, not by device approval.

## Env vars

| Var | Required | Default | Used by |
|---|---|---|---|
| `TRUENAS_PW` | yes | -- | every script that talks to TrueNAS (SSH password + REST API basic auth) |
| `TRUENAS_HOST` | no | `192.168.0.102` | same |
| `TRUENAS_USER` | no | `truenas_admin` | same |
| `SYNCTHING_GUI_URL` | no (or pass `--gui-url`) | -- | `setup_syncthing_folder.py`, `accept_device.py`, `check_health.py` |
| `SYNCTHING_API_KEY` | no (or pass `--api-key`) | -- | same, plus `install_dashboard_app.py` (required there) |
| `DASH_REPORT_TOKEN` | yes, for `install_dashboard_app.py` | -- | the shared secret companions present when POSTing status; same value goes in each editor's `dashboard_token` |
| `DASH_SESSION_SECRET` | yes, for `install_dashboard_app.py` | -- | signs editors' dashboard login cookies. Keep it **stable across deploys** -- changing it logs everyone out. Pass it again on `--recreate`. |

`TRUENAS_PW` is reused as the sudo password on the remote host (`SUDO_PW`
is exported in the SSH session and piped to `sudo -S`), matching the
existing pattern in `~/scripts/truenas_ssh.py` -- `truenas_admin`'s login
password and sudo password are the same account.

The Syncthing GUI URL + API key come from the TrueNAS Apps UI once
`install_syncthing_app.py` has run (Apps > syncthing > Web UI for the URL;
the API key is in Syncthing's own Settings > GUI, or its `config.xml`
inside the app's persistent storage).

## What each script assumes

- **`common.py`** -- shared helpers, not a script itself. Defines the
  template folder list, video extensions, `.stignore` builder, slugify,
  the SSH runner (paramiko, mirrors `~/scripts/truenas_ssh.py`), and thin
  wrappers around `requests` for the TrueNAS and Syncthing REST APIs. All
  credentials come from env vars; nothing is hardcoded.
- **`setup_tree.py`** -- assumes the `TheCreatorsPool` dataset and its
  mountpoint already exist (per SPEC, they do); only creates directories
  under `Creators_Club/Projects/<year>/<series>/<project>` and sets
  ownership (`broll:editors`) + mode (`2770`, setgid) recursively. Does
  **not** create `Proxy/` subfolders -- Blackmagic Proxy Generator creates
  those on demand.
- **`setup_editor_account.py`** -- assumes an `editors` group should exist
  (creates it if missing) and that TrueNAS's `/user` API accepts the field
  names used here (`sshpubkey`, `smb`, `password_disabled`, `groups`).
  Also repairs the new account's **home directory permissions**, which is
  not cosmetic -- see "The home directory trap" below. Safe and useful to
  re-run against an existing editor; that's the supported way to repair a
  broken home directory.

  *`password_disabled` -- resolved (was an open question).* TrueNAS 25.10
  refuses the combination outright rather than silently breaking SMB:

  ```
  HTTP 422  user_update.password_disabled:
    "Password authentication may not be disabled for SMB users."
  ```

  The script attempts it, treats that specific 422 as the expected answer,
  and leaves the account password-enabled with SMB working. SSH is still
  effectively key-only because sshd itself runs with
  `PasswordAuthentication no`.
- **`install_syncthing_app.py`** -- the app-create payload was confirmed
  against the live TrueNAS 25.10.4 chart (`stable/syncthing` 1.3.11
  `questions.yaml`) on 2026-07-22, so this is no longer the guesswork it was
  written as. It still does a GET first to find the catalog entry and
  validates the fields the create payload needs, failing with a clear
  message rather than guessing if the schema drifts. Two things to know:
  the in-container mount point for the bind-mounted `Creators_Club` host
  path is assumed to be `/data`, and the create POST returns a job the
  script does not currently wait on -- so "created" means "accepted".
  Check the app's state in the TrueNAS UI afterwards.
- **`install_dashboard_app.py`** -- deploys the `dashboard/` tree as a
  TrueNAS custom app (project selection, provisioning, share enforcement,
  the companion upgrade channel). Requires `SYNCTHING_API_KEY`,
  `DASH_REPORT_TOKEN` and `DASH_SESSION_SECRET` on top of the TrueNAS
  credentials. Re-run it to ship code changes; `--recreate` (deletes and
  re-creates the app) for compose/env changes -- host `app/` and `data/`
  survive that, so the SQLite DB does too. The bind-mounted `app/` dir's
  inode must be preserved, which is why the code is copied *into* the
  existing dir rather than swapped aside; that behaviour was worked out
  live on 2026-07-24.
- **`write_marker.py`** -- writes (or overwrites) a directory's
  `.ccsync-project` marker. Use it to adopt an existing folder as a project,
  or to repair a lost marker. The `slug` in that marker is the project's
  permanent identity and every dashboard row is keyed on it, so **always
  pass the original `--slug`** when repairing: a different slug orphans the
  project's ticks, Resolve root mappings, completion history and media
  inventory in one go.
- **`setup_syncthing_folder.py`** -- assumes the container mount point from
  `install_syncthing_app.py` (default `/data`, override with
  `--container-mount` if that assumption was wrong). Folder id is
  `slugify(project-rel-path)`. Sets staggered versioning + the `.stignore`
  equivalent (via `/rest/db/ignores`, not an actual `.stignore` file, since
  Syncthing's REST API manages ignores per-folder without needing SSH).
  Does not share the folder to any device -- with the dashboard deployed,
  sharing follows editors' ticks; without it, `accept_device.py --folder-id`
  is the manual fallback.
- **`accept_device.py`** -- assumes the editor's device ID was already
  obtained out-of-band (printed by their bootstrap script or `onboard.exe`).
  Use it to **accept and name** a device, once per machine:
  `--device-id ... --device-name <truenas-username>`. `--device-name` is
  load-bearing -- an unnamed device shows as `[ UNMAPPED ]` on the dashboard
  and enforcement never touches it, so it syncs nothing whatever gets
  ticked. **Workflow change:** stop running this once per (editor, project).
  `--folder-id` is now optional and legacy-only: the `enforce` cycle makes
  the selections table the authority for folder sharing and reconciles every
  mapped editor's shares within a minute, reverting hand-made ones. Reach
  for `--folder-id` only for an editor the dashboard doesn't manage, or a
  one-off repair while the dashboard is down. The dashboard's
  `/admin/users` > **Approve device** is the browser equivalent of the
  no-folder-id call.
- **`check_health.py`** -- read-only checks; the postgres check is a raw
  TCP connect (proves the port is open, not that auth works); the
  tailscale check assumes the app's container is literally named
  `tailscale` (per SPEC's "Current state" section) and execs `tailscale
  status --json` inside it via `docker exec` over SSH.

## The home directory trap (why `setup_editor_account.py` sets permissions)

Found the hard way onboarding the first real editor. Worth understanding
before touching account setup, because the failure is completely silent from
the editor's side.

`home_create=True` makes the new home inherit the parent `homes` dataset's
NFSv4 ACL. On this pool that ACL carries an inheritable
`everyone@:rwxp...:fd----I:allow` ACE, so every editor home is created:

```
drwxrwxrwx broll:broll  /mnt/tank/TheCreatorsPool/homes/<editor>
```

world-writable, and owned by the dataset owner rather than the editor. sshd
runs with `StrictModes yes`, which refuses public-key auth outright when the
home directory is group/world-writable or not owned by the authenticating
user. The only trace is in the NAS auth log:

```
Authentication refused: bad ownership or modes for directory
/mnt/tank/TheCreatorsPool/homes/<editor>
```

The editor sees only rclone's generic
`ssh: unable to authenticate, attempted methods [none publickey]` -- which is
**identical to what you get when no key was ever installed**, so it reads as
"the admin hasn't run the scripts yet" and sends you chasing the wrong thing.

Two further traps when fixing it by hand:

- **`chmod` doesn't work.** The dataset is `aclmode=restricted`, under which
  `chmod` on a non-trivial ACL fails with `Operation not permitted` even as
  root. (`chown` *does* work.) The script uses `filesystem.setperm` with
  `stripacl` to replace the inherited ACL with a trivial 0700.
- **`filesystem.setperm` is a job.** The POST returns a job id and 200 means
  "accepted", not "done" -- `common.wait_for_job()` polls `/core/get_jobs`
  for the real outcome.

The script verifies the result by re-reading the directory over SSH and
re-checking the exact two conditions sshd tests, rather than trusting the
job's success.

**Recommended, not done automatically:** the `homes` parent itself is still
`drwxrwxrwx broll:broll` with that inheritable `everyone@` ACE. Per-home
permissions are now set explicitly so new editors are fine either way, but
the parent being world-writable means any account on the NAS can create or
delete entries in it. Tightening it changes inheritance for everything under
`homes/`, so it's left as a deliberate admin decision.

## Local verification (already done for these scripts; re-run if you edit them)

```
cd E:\Projects\resolve-remote-sync\server
python -m py_compile common.py setup_tree.py setup_editor_account.py install_syncthing_app.py install_dashboard_app.py setup_syncthing_folder.py accept_device.py write_marker.py check_health.py
python -m pytest tests -v
python setup_tree.py --year 2025 --series FF4 --project Nuclear --dry-run
python setup_editor_account.py --name jsmith --ssh-pubkey-file <any file> --dry-run
python install_syncthing_app.py --dry-run
python install_dashboard_app.py --dry-run
python setup_syncthing_folder.py --project-rel-path 2025/FF4/Nuclear --gui-url http://x --api-key x --dry-run
python accept_device.py --device-id ABCD --device-name jsmith --gui-url http://x --api-key x --dry-run
python write_marker.py --project-rel-path 2025/FF4/Nuclear --slug 2025-ff4-nuclear --dry-run
python check_health.py --dry-run
```

These particular commands are the local, offline checks -- `--dry-run` opens
no connection, so nothing above touches `192.168.0.102`. For which scripts
have since been confirmed against the live NAS, see **Live status** at the
top of this file.
