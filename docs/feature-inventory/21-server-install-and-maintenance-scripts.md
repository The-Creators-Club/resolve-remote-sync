# Operator scripts for the NAS: install, deploy, accounts, Syncthing, snapshots, publishing indexes

This section is in five pieces. This file covers every operator script and the parts of `install_dashboard_app.py` not listed below. Four companion files, in `docs/feature-inventory/_parts/`, belong to this section as they stand:

- `21a-nas-backends-truenas-vs-synology.md`: every per-NAS operation (users, groups, shares, ACLs, datasets, snapshots, app install and restart, Tailscale, Syncthing) on TrueNAS and on Synology side by side (source: `server/backends/`).
- `21b-install-dashboard-app-lines-4380-6040.md`: the deploy's ffmpeg, deno and node provisioning, code-tree upload, staging, swap, prune, document shipping, Synology host folders, container restart and mode switching (source: `install_dashboard_app.py` lines 4380 to 6040).
- `21c-install-dashboard-app-lines-2050-4400.md`: the deploy's image-mode preflight, health probe and rollback, container environment, the generated compose file, secrets, and the music database install (source: `install_dashboard_app.py` lines 2050 to 4400).
- `21d-common-and-truenas-rpc.md`: behaviour shared by every script: site.toml loading, SSH access, sudo, host-key pinning, the snapshot taken before privileged recursive commands, secret warnings, the error wrapper, and the TrueNAS API client (source: `common.py`, `truenas_rpc.py`).

Terms used throughout:

- **NAS**: the studio's network storage box, either TrueNAS SCALE or Synology DSM. It holds the project tree and runs the dashboard container.
- **Operator workstation**: the computer the operator runs these scripts on (in practice the studio's "base rig"). Every script here runs there and reaches the NAS over SSH or over HTTP APIs.
- **site.toml**: the site configuration file the scripts read for per-studio values (NAS host, pool, tree name, URLs). Selected with `--site` on every script.
- **Dry run**: `--dry-run`, offered by every script; prints what would be done instead of doing it.
- **Syncthing GUI URL / API key**: the address and secret of the NAS's Syncthing app REST API.
- Every script exits through a shared wrapper (see "Shared behaviour") that turns configuration errors into a one-line `FAILED` message and a non-zero exit.

## Approve an editor's Syncthing device (source: accept_device.py)

- Purpose: accept a pending editor Syncthing device on the NAS's Syncthing and give it a name; optionally (legacy) share one folder with it.
- Flags:
  - `--device-id` (required): the editor's Syncthing device ID. Trimmed and uppercased, then shape-checked: 8 groups of 7 characters from A-Z and 2-7 separated by dashes. The check characters are not verified (Syncthing verifies them). On a bad shape: `FAILED: --device-id '<value>' is not a Syncthing device ID.` plus an example ID and the hint that it is 63 characters; exit 1.
  - `--device-name` (default: the device ID itself): must be the editor's NAS username, because the dashboard maps a device to an editor account by this name and shares that editor's ticked projects with it.
  - `--folder-id` (default none): OPTIONAL, legacy. Also share this Syncthing folder with the device.
  - `--gui-url` (default env `SYNCTHING_GUI_URL`), `--api-key` (default env `SYNCTHING_API_KEY`). Both required unless `--dry-run`: `FAILED: --gui-url is required (or set SYNCTHING_GUI_URL)` / `FAILED: --api-key is required (or set SYNCTHING_API_KEY)`, exit 1.
  - `--site`, `--dry-run`.
- Passing `--api-key` on the command line prints the shared "secret on the command line" warning (see Shared behaviour).
- Device-name advice, always printed as `NOTE:` lines, never a refusal:
  - No name given: the device is UNMAPPED, the dashboard will not manage its folder shares.
  - Name not shaped like a username (lowercase letter first, then up to 31 of letters, digits, `.`, `_`, `-`): the dashboard will treat it as UNMAPPED.
  - Name shaped like a username: reminder that it must be the editor's username, not the machine name, and is honoured only if the dashboard already knows that editor account.
- Step 1 (informational): reads Syncthing's pending-devices list. Prints `device confirmed pending: <id>` or a NOTE that it was not found (already added, or not dialed in yet), and continues either way.
- Step 2: reads configured devices. Failure to read: `FAILED to list configured devices: HTTP <code> <body>`, exit 1.
- Step 3a (device already configured): prints `device already configured, skipping add`; if `--device-name` was given and differs from the stored name, renames it (`renamed device: 'old' -> 'new'`, or a `WARNING: could not rename device ...` on failure, which does not change the exit code).
- Step 3b (new device): adds it with the given name, address "dynamic", not an introducer. Prints `added device: <id> (<name>)`; on failure `FAILED to add device: HTTP ...`, exit 1. Adding the device is what "accepts" it in Syncthing.
- Without `--folder-id`: prints that no folder was touched and that the next step is ticking the editor's projects in the dashboard; exit 0.
- With `--folder-id`: prints a NOTE that the dashboard's enforcement may undo a hand-made share for a mapped editor; reads the folder (`FAILED to fetch folder ...` exit 1 on error); if the device is already on it prints `folder already shared with device, skipping`; otherwise appends the device and writes the folder back (`shared folder <f> with device <d>`, or `FAILED to share folder with device ...` exit 1).
- Dry run: no request is sent; the folder step prints `[dry-run] would ensure folder '<f>' shares to device '<d>'`.
- Idempotent: re-running with the same arguments changes nothing.

## One-command server health check (source: check_health.py)

- Purpose: validate the whole server side. Prints one `PASS:` or `FAIL:` line per check; the exit code is the number of failed checks (0 = all good). Warnings are printed as `WARN:` and never change the exit code.
- Flags and environment:
  - `--gui-url` / `--api-key` (default env `SYNCTHING_GUI_URL` / `SYNCTHING_API_KEY`).
  - `--dashboard-url` (default env `DASHBOARD_URL`, else site.toml `[net] dashboard_url`, else blank). Required in the end: a blank value is a configuration refusal naming `[net] dashboard_url` and `--dashboard-url`.
  - `--projects-root` (default: the site's tree root built from `[tree] pool_root/tree_name`). Required the same way.
  - `--tailscale-peer`: the NAS's tailnet hostname or IP for the "path from here" check. Default: the dashboard URL's host when it starts with `100.` or is a name, then site.toml `[net] tailnet_name`, else `truenas`.
  - `--host-key` (SSH host-key pin), `--site`, `--nas-kind`, `--dry-run`.
  - `TRUENAS_HOST` (printed in the opening line `Checking CC Sync server (<host>)...`), `TRUENAS_PW`, `DASH_REPORT_TOKEN` (optional; see check 8).
- Each check is run so that a check which crashes is reported as that check failing (`FAIL: <name>: the check could not run (<ErrorType>: <first 200 chars>)`) and the remaining checks still run. Configuration errors and "not supported on this NAS" still stop the whole run.
- Checks, in order:
  1. **Postgres** (the Resolve project server): skipped with an explanatory info line when site.toml `[stack] project_server = false` (default true). Otherwise a raw TCP connect to the NAS host on port 5432, 5 second timeout. `PASS: postgres reachable at host:5432` / `FAIL: postgres NOT reachable at ...`. Proves the port is open, not that login works.
  2. **Tailscale on the NAS**: asks the NAS's Tailscale for its status JSON (a container on TrueNAS, the DSM package on Synology). FAIL if the command fails, if the output is not JSON, or if the state is not `Running` (`tailscale NOT logged in (BackendState=...) -- run tailscale up in the container to re-auth`). PASS lists the NAS's tailnet IPs. Then one line per peer: offline peers are listed as `offline`; direct peers as `DIRECT via <addr>` (with home relay region); a peer whose traffic is relayed (no current direct address) produces a WARN explaining that every byte is proxied, to check UDP 41641 both ways, and to run `tailscale netcheck`.
  3. **Tailnet path from this workstation to the NAS**: runs the local `tailscale status --json` (15 second timeout). Skipped with an info line when there is no local `tailscale`, when it fails, when it is not JSON, or when the NAS peer is not found under any hint. Direct path prints `PATH: ... is DIRECT via ...`; relayed path is a WARN. Never a FAIL.
  4. **Syncthing**: FAIL (`syncthing GUI/API check skipped -- pass --gui-url/--api-key ...`) when either is missing. Otherwise pings the Syncthing API (FAIL when unreachable or non-2xx, including a connection error), then lists folders: `PASS: syncthing folders listed: N folder(s): [ids]`.
  5. **Project tree**: over SSH, using sudo, tests that the tree root directory exists. PASS/FAIL `project tree root exists|MISSING: <path>`. On Synology only, a follow-up checks the tree's access-control entries for the editors group (a PASS/FAIL, or a WARN when it cannot tell).
  6. **Editor accounts**: lists members of the `editors` group. On Synology through DSM; on TrueNAS through the REST API (finds the group by name, then every user whose group list contains the group's database id or whose primary group is it). FAIL when the group does not exist, cannot be listed, has no database id, or has no members (`group 'editors' exists but has no members yet`). PASS lists the usernames and the unix group id.
  7. **SFTP transport**: no output on TrueNAS when fine. On a Synology NAS whose site.toml `[net] sftp_chunk_size` / `sftp_concurrency` exceed what DSM's SSH server can serve: FAIL telling the operator to set `sftp_chunk_size = "64Ki"` and `sftp_concurrency = 16`, redeploy, and re-download any proxy over 514 MiB. On Synology when fine: `PASS: SFTP transport is within DSM's sshd limits (64Ki / 16)`.
  8. **Dashboard**: `GET <dashboard-url>/api/v1/health`, 10 second timeout, sending header `X-CCSync-Token` when `DASH_REPORT_TOKEN` is set. FAIL when unreachable, non-2xx, or not JSON. Without the token the dashboard answers liveness only, and the check reports `dashboard is up ... ok=<x>. Set DASH_REPORT_TOKEN to also check ...` (pass/fail by the `ok` field). With the token: PASS when the dashboard says it can reach Syncthing, FAIL `... its collector cannot see Syncthing, so lane C status and project provisioning are stale` otherwise.
- Non-ASCII peer names are degraded to the console's encoding rather than crashing the run (Windows consoles).
- End of run: `N/M checks passed.` and, when there were warnings, `K warning(s) -- nothing is broken, but something is slow:` with each listed.
- Dry run: each check prints what it would do (`[dry-run] would TCP-connect ...`, `[dry-run] would GET ...`, the SSH command, etc.), no connection is opened, and it ends `[dry-run] no checks were actually executed.` with exit 0.

## Mint a scoped TrueNAS API key for the dashboard (source: create_api_key.py)

- Purpose: create a TrueNAS API key the dashboard container can hold instead of the NAS admin password. TrueNAS only.
- Flags and environment:
  - `--name` (default `ccsync-dashboard`): the key's label in TrueNAS's API Keys list. Use a new name per rotation so the old key can be deleted by name.
  - `--username` (default empty): the account the key acts as (TrueNAS 24.10 and later).
  - `--allow-admin-key`: deliberately mint the key as the NAS admin account (root-equivalent).
  - `--shape` (`auto` default, `username`, `allowlist`): which request body to send. `auto` tries the username shape, then the allowlist shape.
  - `--host-key`, `--site`, `--nas-kind`, `--dry-run`.
  - `TRUENAS_USER` (the admin account name, used to detect "the key would be the admin"), `TRUENAS_PW` (required to mint), `TRUENAS_HOST`.
- Refusals:
  - NAS kind is not TrueNAS: `FAILED: API keys are a TrueNAS concept. DSM has none -- a Synology deployment keeps using the admin password in DASH_NAS_PW ...`, exit 2.
  - Username shape (auto or username) without `--username` and without `--allow-admin-key`: `FAILED: --username is required: name the dedicated non-shell account the key acts AS (holding only ACCOUNT_WRITE, FILESYSTEM_ATTRS_WRITE) ...`, exit 2.
  - `--username` equal (case-insensitive) to `TRUENAS_USER`: refused the same way unless `--allow-admin-key`, exit 2.
  - The allowlist shape needs no account, so it is never refused on these grounds.
- Warnings printed before minting:
  - When no `--username` is given or it equals `TRUENAS_USER`: `WARNING: --allow-admin-key: the key acts as the ADMIN (<name>), i.e. with root-equivalent rights.` This also prints for `--shape allowlist` without a username, where `--allow-admin-key` was not given.
  - Always: a residual-risk note. Even a dedicated account can reset any account's password and SSH keys (ACCOUNT_WRITE) and change permissions anywhere (FILESYSTEM_ATTRS_WRITE). The key's value is only that the admin password is not in the container, that it can be revoked by name, and that the account can be watched.
- Prints the scope: the seven allowed calls for the allowlist shape (GET/POST/PUT on users, GET/POST on groups, POST filesystem set-permission, GET job status), or the two roles `ACCOUNT_WRITE` and `FILESYSTEM_ATTRS_WRITE` for the username shape. The script does not create the account or grant the roles; the operator does that in the TrueNAS UI.
- Creation: sends a create-API-key request in each shape in turn. A rejected shape prints `NOTE: /api_key rejected the <shape> shape (HTTP <code> <first 300 chars>)` and the next shape is tried. Failures, each exit 1:
  - success but the answer is not JSON;
  - no `key` field in the answer, with advice to delete the key it just made and re-run;
  - every shape refused: `FAILED: could not create an API key. ...`, telling the operator not to guess and to look at the NAS's own API docs.
- Success output:
  - `created API key: <name>`.
  - The plaintext key, printed once (`SHOWN ONCE -- TrueNAS stores it hashed and will not show it again`).
  - Ready-to-paste lines: `export TRUENAS_API_KEY=<key>`, `export TRUENAS_API_KEY_USER=<username>`, `python server/install_dashboard_app.py`.
  - A reminder to revoke it in Credentials > API Keys.
  - The key is written nowhere.
- Dry run: prints `[dry-run] would POST /api_key in the <shape> shape` for each shape. It mints nothing, prints no key, and exits 0.

## Install the Syncthing app on TrueNAS (source: install_syncthing_app.py)

- Purpose: first-time install of the Syncthing app from TrueNAS's app catalog. Syncthing is "lane C", the Syncthing-based project sync. On Synology the script does nothing by design, because Syncthing is a service in the dashboard's own compose stack there.
- Flags:
  - `--gui-port` (default 8384): the Syncthing web GUI port.
  - `--host-path` (default: the tree root from site.toml `[tree] pool_root/tree_name`): the NAS directory bind-mounted into the app. A blank value is a configuration refusal naming `[tree] pool_root/tree_name` and `--host-path`.
  - `--container-mount` (default `/data`): where that directory appears inside the app.
  - `--site`, `--nas-kind`, `--dry-run`.
- Step 1: asks the NAS whether an app named `syncthing` is already installed.
  - If the NAS cannot answer, the script exits 1.
  - If installed: prints `app already installed, skipping: syncthing` and a note that changes (for example the GUI port) must be made in the TrueNAS UI; exit 0. This script only does first installs.
- Step 2: the NAS-kind backend performs the install itself: catalog lookup, payload shape check, create request, and a wait for the install job (see part 21a). Its return code is the script's exit code.
- Configured by part 21a's backend, not by this script: the site.toml `[syncthing] gui_bind` address restriction and the automatic GUI login.

## Put a login on the Syncthing GUI (source: secure_syncthing_gui.py)

- Purpose: require a username and password on the NAS's Syncthing web GUI, turn off "insecure admin access", and optionally change the address the GUI listens on. Uses Syncthing's own API, so it works on the TrueNAS app and on the Synology compose service alike. The API key is never changed, so everything that uses the API key keeps working.
- Flags and environment:
  - `--gui-url`: default env `SYNCTHING_GUI_URL`, then site.toml `[syncthing] gui_url`. A blank value is a configuration refusal naming `[syncthing] gui_url` / `--gui-url`.
  - `--api-key`: default env `SYNCTHING_API_KEY`. It is required (a missing-environment refusal) unless this is a dry run.
  - `--user` (default `ccsync-admin`).
  - `--password`: default env `SYNCTHING_GUI_PASSWORD`, then a generated 28-character password of letters and digits.
  - `--bind ADDR:PORT`: sets the GUI's listen address, for example `127.0.0.1:8384`. Unset keeps the current address.
  - `--show`: report only.
  - `--site`, `--dry-run`.
  - `CCSYNC_SYNCTHING_CREDS`: overrides where the credentials file is written.
  - Passing `--api-key` or `--password` on the command line prints the shared "secret on the command line" warning.
- First reads the GUI configuration. Failures, each exit 1:
  - `FAILED: GET /rest/config/gui answered HTTP <code>. A 403 means the API key is wrong; a connection error means <url> is not the GUI.`
  - The answer is not JSON.
  - The answer is not a JSON object.
- `--show`: prints the address, the user (`(none -- UNAUTHENTICATED)` when there is none) and the insecureAdminAccess value. With no user it adds a warning that anyone who can reach the address is a Syncthing administrator, and exits 1. With a user it exits 0. In a dry run it prints that it would report, and exits 0.
- Normal run:
  - Writes the GUI configuration back with the user, the password (Syncthing hashes it on save), insecureAdminAccess off, and the `--bind` address if given.
  - The write always replaces an existing login.
  - Failure: `FAILED: PUT /rest/config/gui answered HTTP <code> <text>`, exit 1.
- After success:
  - Writes `~/.ccsync/syncthing-gui.txt` on the workstation, mode 0600, holding the URL, user and password with a warning header.
  - Prints `Syncthing GUI at <url> now requires a login.` with the user and the password (`SHOWN ONCE`).
  - With `--bind`, prints a NOTE: on the TrueNAS catalog app the container must keep listening on 0.0.0.0, and the host side is restricted with site.toml `[syncthing] gui_bind` instead.
  - Prints that the API key was not changed.
- Then asks Syncthing whether a restart is required. If so it prints `Syncthing says a restart is required for this to take effect: restart the app (TrueNAS Apps > syncthing) or the container.`
- Dry run: prints the change it would make and the credentials path, and exits 0.
- The same action is also offered to the installers, with gentler rules. The installer flavour:
  - leaves a GUI that already has a login and has insecure access off untouched;
  - when only insecure access is on, turns it off and keeps the existing login;
  - writes the credentials file BEFORE changing the GUI;
  - removes a freshly written credentials file if the change then fails;
  - never raises an error.

## Snapshot schedules: the backup floor (source: setup_snapshots.py)

- Purpose: make sure periodic file-system snapshots exist for the project tree and for the dashboard's own data on the NAS.
- **Dry run is the default.** `--apply` makes changes.
- Flags:
  - `--tree-root` (default site.toml `[tree] pool_root`). Required: a blank value is a configuration refusal.
  - `--apps-root` (default `[apps] root`). Optional. When missing it prints `NOTE: no [apps] root in site.toml -- only the tree will be scheduled. The dashboard's dashboard.db (the fleet's projects, editors and ticks) then has no snapshot behind it.`
  - `--hourly-keep` (default 24 hours).
  - `--daily-keep` (default 30 days).
  - `--list`: report only.
  - `--snapshot-now NAME`: also take an immediate snapshot of each target with this name. Only acts with `--apply`.
  - `--apply`, `--host-key`, `--site`, `--nas-kind`.
- Policy, applied to each target, both recursive (child datasets are included):
  - hourly: on minute 0 of every hour, names `ccsync-%Y%m%d-%H%M`, kept 24 hours by default;
  - daily: at 03:10, names `ccsync-daily-%Y%m%d-%H%M`, kept 30 days by default.
  - How a schedule is installed on each NAS kind is in part 21a.
- Output, in order:
  - `NAS: <kind>`.
  - The targets.
  - The existing snapshots per target: either `<label>: NO snapshots found on <path> -- this dataset has no point-in-time behind it today.` or `<label>: N snapshot(s) on <path>; newest <name> (<created>)`. Not read in a dry run.
  - `Policy: hourly (...) keep Nh; daily (...) keep Nd; recursive`.
- `--list`:
  - Reports the existing snapshots.
  - Asks the backend, without changing anything, whether each target can be scheduled at all. Each one that cannot prints `CANNOT BE SCHEDULED -- <label>: <detail>` and then `Backups are NOT fully configured. See docs/BACKUP_RESTORE.md.`, exit 1.
  - Otherwise exit 0.
  - Live snapshot counts are only shown with `--list --apply`.
- Applying:
  - Each schedule result is either fine, "failed" or "manual". "Manual" is a step the operator must click, for example on DSM without the Snapshot Replication package.
  - Dry run: every failed or manual result is printed as `WOULD NOT SUCCEED -- ...`, then `[dry-run] nothing was changed. Re-run with --apply to create the tasks above.` Exit 1 if anything failed, else 0. A manual-only result exits 0 in a dry run.
  - Real run: prints `MANUAL STEP REQUIRED -- ...` and `FAILED -- ...` lines. If there are any, it prints `Backups are NOT fully configured. See docs/BACKUP_RESTORE.md.` and exits 1.
  - Clean: `Done. Verify within the hour with: python setup_snapshots.py --list --apply`, exit 0.
- `--snapshot-now`:
  - Prints `took: <id>` for each target.
  - A failure is added to the failed list as `immediate snapshot '<name>' failed`.

## Editor accounts on the NAS: create, update, migrate, revoke (source: setup_editor_account.py)

- Purpose: create or update the NAS user account for a remote editor, the account their companion uses for SFTP transfers (lanes A and B) and SMB. Re-running against an existing editor is the supported way to repair one. The per-NAS details (API calls, home-folder fix, sshd policy) are in part 21a.
- Always prints a banner naming the NAS being changed before connecting, and a TrueNAS version note.
- Flags:
  - `--name`: the editor's username. Lowercased; must start with a letter and contain only a-z, 0-9, `.`, `_`, `-`, at most 31 characters. Otherwise: `FAILED: invalid --name ...`, exit 1. A changed case prints `normalized --name 'X' -> 'x' ...`.
  - `--ssh-pubkey-file`: the editor's public key file. Unreadable: `FAILED to read --ssh-pubkey-file ...`, exit 1. A file whose first word does not start with `ssh-` gets a WARNING and the run continues.
  - `--full-name` (default `--name`).
  - `--tailnet-host` (default the placeholder `<TAILNET-HOSTNAME-OR-IP>`): only used in the printed rclone stanza.
  - `--project SLUG` (repeatable): add the editor to the per-project group `proj-<slug>` (see below).
  - `--migrate-existing`, `--revoke-key`, `--lock`, `--apply`, `--yes`, `--dry-run`, `--host-key`, `--site`, `--nas-kind`.
  - Argument errors (usage message, exit 2): `--migrate-existing` with `--name` or `--ssh-pubkey-file`; `--revoke-key` without `--name`; the normal mode without both `--name` and `--ssh-pubkey-file`.
  - Requires site.toml `[tree] pool_root` (the parent of editor homes, `<pool root>/homes`); blank is a configuration refusal.
  - Environment: `TRUENAS_HOST`, `TRUENAS_USER`, `TRUENAS_PW`.
- Create or update, in order:
  1. Ensures the group `editors` exists.
  2. If site.toml `[stack] editor_shell` is `sftp-only`, installs or refreshes the SSH server rule for the editors group (SFTP only, no password login). Prints `sshd policy installed/refreshed for group editors (...)`, `sshd policy already correct ...`, or a WARNING asking the operator to add the rule by hand.
  3. Existing user: updated in place (key, SMB flag, group membership): `user already exists, updating in place: <name> (uid N)` then `updated user: ...`; failure `FAILED to update user ...`, exit 1. New user: created with home under `<pool root>/homes`, the site's shell (no-login for SFTP-only sites), SMB on: `created user: <name> (uid N), group editors, shell <shell>, smb enabled`; failure `FAILED to create user ...`, exit 1.
  4. `--project` slugs: only acts when site.toml `[stack] project_acl` is `per-project`; otherwise a NOTE that every editor already reaches every project. On Synology a NOTE that per-project groups are partial and must be finished in DSM's User & Group and File Station. On TrueNAS: creates `proj-<slug>` if needed and adds the editor (`project access: <name> added to proj-<slug>`); an invalid slug, a missing account or a failed update is a WARNING.
  5. Re-reads the account and verifies it has the key, SMB on, and editors membership. Any gap: `WARNING: verification found issues after create/update:` with the list and `Not attempting to disable password login until the above is resolved.`, exit 1. Otherwise `verified: sshpubkey set, smb=True, member of editors`.
  6. Home folder: refuses to touch a home that is blank, `/`, `/nonexistent`, `/var/empty`, `/mnt`, `/root`, `/home` or the homes parent itself (`WARNING: refusing to touch permissions on home path ... Fix the account's home to <parent>/<name> and re-run.`). Otherwise sets it to mode 0700 owned by the editor (replacing the inherited permissions), then re-checks over SSH that the SSH server will accept it. A missing home, uid or group id is a WARNING.
  7. Tries to turn off password login. Prints one of: `set password_disabled=True (key-only SSH)`; a note that TrueNAS refuses this for SMB users and SSH is still key-only through the SSH server's own setting; a note that the platform manages it (Synology); or a WARNING.
  8. If the home folder is not acceptable: a WARNING that SFTP and rclone will fail with "unable to authenticate" until it is fixed. The exit code stays 0.
  9. Prints an rclone remote block for the editor's rclone.conf: remote name from `[net] rclone_remote` (default `ccsync_sftp`), type sftp, host from `--tailnet-host`, user, port from `[net] sftp_port` (default 22), key file `~/.ssh/ccsync_ed25519`, and shell type `none` on SFTP-only sites, else `[net] shell_type` (default `unix`).
- Dry run: does not read the key file, prints what it would create and set, and prints the rclone block; exit 0.
- `--migrate-existing` (converts existing editors to the SFTP-only shell). Report-only unless `--apply`:
  - Refused unless site.toml `[stack] editor_shell` is `sftp-only` (`FAILED: [stack] editor_shell is '...'. Set it to "sftp-only" in site.toml first ...`, exit 2).
  - Lists every account in the editors group, marking `->` those whose shell differs from the wanted one, and prints the "MANIFEST CONSEQUENCE" warning: rclone can no longer checksum over SSH, the dashboard must be redeployed so the site manifest says `sftp_shell_type = "none"`, and until each companion refreshes, the lane A/B logs show repeated `failed to calculate hash`.
  - Without `--apply`: `[report-only] would set shell=... on N account(s) and install the sshd Match block. Re-run with --apply.`
  - With `--apply`: installs the SSH server rule, converts each account (`converted: <name> -> <shell>` or `FAILED to convert ...`), exit 1 if any failed, else `All editors are SFTP-only. Redeploy the dashboard so the manifest says so.`
  - Failure to list the group: exit 1.
- `--revoke-key` (offboarding). Report-only unless `--apply`:
  - `FAILED: no account named '<name>'` exit 1 when the account does not exist (the account is looked up even in report-only mode).
  - Without `--apply`: says it would remove the key (and disable the account with `--lock`), and that lane C (Syncthing) is NOT affected and the device must be unshared in the dashboard as well.
  - With `--apply`: asks the operator to type the NAS's name (skipped with `--yes`; with no terminal and no `--yes` the run is refused; details in part 21d), then removes the installed public key; with `--lock` also disables the account (SMB and dashboard login stop too). Prints `revoked: ...` and a reminder to unshare the Syncthing device and delete the key from the editor's machine. Failure `FAILED to revoke ...`, exit 1.

## Create one Syncthing folder for a project (source: setup_syncthing_folder.py)

- Purpose: create or reconfigure the NAS Syncthing folder for one project (lane C) and set its ignore patterns.
- Flags and environment:
  - `--project-rel-path` (required): the project's path under `<tree root>/Projects`, any depth, for example `2025/FF4/Nuclear`. Backslashes become slashes. Each segment is validated; a bad path (for example containing `..`): `FAILED: invalid --project-rel-path ...`, exit 1.
  - `--gui-url`, `--api-key` (defaults env `SYNCTHING_GUI_URL`, `SYNCTHING_API_KEY`); required unless dry run, with the same FAILED lines as the device script.
  - `--container-mount` (default `/data`): where the tree appears inside the Syncthing app. The folder path is `<mount>/Projects/<rel>`.
  - `--label` (default the relative path).
  - `--force`: reconfigure an existing folder, including retargeting it to a new path.
  - `--slug`: the project's identity, given explicitly.
  - `--projects-root` (default the site's tree root `.../Projects`): the NAS-side path the marker is read from. Required; blank is a configuration refusal.
  - `--no-marker-read`: derive the id from the path without reading the marker.
  - `--host-key`, `--site`, `--dry-run`. `TRUENAS_HOST`/`TRUENAS_USER`/`TRUENAS_PW` are needed only for the marker read.
- Folder id, chosen in this order:
  1. `--slug`, validated (lowercase letters, digits, dashes). Invalid: `FAILED: invalid --slug: ...`, exit 1.
  2. The slug in the project's `.ccsync-project` marker file, read as root over SSH. Authoritative.
  3. The path turned into a slug, only when the directory has no marker. Prints a note suggesting `setup_tree.py` or `write_marker.py` to give the project a permanent identity.
  - Refusals, exit 1, nothing changed:
    - The marker exists but carries no valid slug: `REFUSING: this project HAS a .ccsync-project marker, but its identity could not be read.` with the advice to repair it or pass `--slug`.
    - The marker could not be read at all (no password, host down, permission denied, or the read said neither present nor absent): `REFUSING: could not read this project's .ccsync-project marker, so its identity is unknown.` listing three fixes (`--slug`, set `TRUENAS_PW`, `--no-marker-read`).
  - With `--no-marker-read`: prints that the id is only correct for a project that has never moved.
  - In a dry run the marker is not read; it prints that it would read it and shows the path-derived id, which differs for a moved project.
- Prints the relative path, the folder id with its source, and the folder path inside the app.
- Existing folder with the same id:
  - Same path: `folder id ... already points at the requested path`. Without `--force`: `folder already exists, skipping create ... (use --force to reconfigure)`.
  - Different path without `--force`: `REFUSING: folder id '...' already exists but points somewhere else.` with both paths and an explanation that different names can slugify to one id; exit 1. With `--force`: `--force given: RETARGETING folder ...`.
- Before any create or reconfigure: if a folder with a DIFFERENT id already points at the same path, refuses (`REFUSING: folder id 'X' already points at this exact path, but we were about to use 'Y'.`), explaining this is what a moved project looks like and to re-run with `--slug X`; exit 1. This applies to `--force` too.
- Folder settings written on create or reconfigure:
  - type send-and-receive, file-system watcher on, permissions ignored, full rescan every 3600 seconds;
  - at most 32 concurrent writes and 64 MiB of pending pulled data;
  - staggered versioning with a 3600 second clean interval and a maximum age of one year (31,536,000 seconds);
  - deletes made by editors are never applied on the NAS ("ignore delete");
  - on a reconfigure, the existing device shares are kept.
  - Prints `created folder: ...` or `updated folder: ... (sendreceive, staggered versioning, fsWatcher on)`. Failure `FAILED to create/update folder ...`, exit 1. Listing failure: `FAILED to list folders ...`, exit 1.
- Ignore patterns: always (re)applied, even when the folder already existed, which is how an existing folder picks up new lines. Prints the list (`.stignore (N lines):`). The list comes from a shared function (part 21d): one case-insensitive line per video file type, every `Proxy` folder, and in-flight download and partial files. Failure `FAILED to set ignore patterns ...`, exit 1.
- Ends `Done. Next: accept_device.py to share this folder with each editor's device ID.`
- Dry run: no request is sent; prints the same headings and ignore list.

## Create a project folder tree on the NAS (source: setup_tree.py)

- Purpose: create a project's standard folder template on the NAS, give it an identity marker, and make it writable by the editors group.
- Always prints a banner naming the NAS before connecting.
- Flags:
  - `--year`, `--series`, `--project`: the project path `<projects root>/<year>/<series>/<project>`. Names with spaces are fine.
  - `--project-rel-path`: any-depth alternative. Combining it with `--year`/`--series`/`--project` is a usage error, and so is giving neither form completely.
  - `--projects-root` (default the site's tree root `.../Projects`; blank is a configuration refusal).
  - `--owner` (default the site's dataset owner), `--group` (default `editors`).
  - `--require-snapshot`: stop, exit 2, nothing created, if the snapshot taken before the recursive ownership change cannot be made. The default is best effort: warn and continue.
  - `--yes`: skip typing the NAS's name to confirm.
  - `--host-key`, `--site`, `--nas-kind`, `--dry-run`.
- Prints the target, the slug derived from the path (`Project slug (marker identity): ...`, noted as written only if no marker exists), and the template folders.
- Template folders created inside the project (each reported as `created: <folder>` or `exists: <folder>`; the existence check runs as root): `AE`, `Audio/Music`, `Audio/Voiceover`, `B-roll`, `Interviewees`, `Render in Place`, `Subs`, `Youtube`. Site.toml `[tree] template_folders` replaces this list. `Proxy` folders are not created.
- Refusals, checked on the NAS before anything is created:
  - A directory between the projects root and the target already carries a `.ccsync-project` marker: `REFUSING: <dir> is already a project ...`, remote exit 3.
  - The target already contains a marker two or more levels below it: `found marker: <path>` and `REFUSING: <target> already CONTAINS at least one project ...`, remote exit 4.
  - Both print `Nothing was created.` and exit with that code.
  - A slug that fails validation: `FAILED: ...`, exit 1.
- The marker `.ccsync-project` is written only when absent; an existing identity is always kept.
- Per-project mode (site.toml `[stack] project_acl = "per-project"`): prints that the project will belong to `<owner>:proj-<slug>` and that the folders above it get the sticky bit; creates the group `proj-<slug>` on the NAS first.
- Ownership and permissions are re-applied recursively on every run, the NAS kind's way (part 21a): owner and group with mode 2770 on TrueNAS, inheritable ACL entries on Synology.
- Before running: asks the operator to confirm the NAS (`About to create <path> and re-apply ownership recursively (chown -R as root) under <root>.`, details in part 21d), then takes a snapshot of the whole tree (part 21d).
- Output: the remote script's lines; `FAILED (remote exit code N)` plus the snapshot verdict on failure; `Done.` plus the snapshot verdict on success.
- Dry run: no connection; prints the full remote script and the snapshot verdict; exit 0.

## Write or change a project's identity marker (source: write_marker.py)

- Purpose: write a project's `.ccsync-project` marker, or deliberately change its slug. It is the only tool that changes an existing identity. Used for adopting existing folders or repairing a moved project.
- Flags:
  - `--project-rel-path` (required).
  - `--slug` (default: the path turned into a slug), validated (lowercase letters, digits, dashes). Invalid: `FAILED: ...`, exit 1.
  - `--projects-root` (default the site's tree root; blank is a configuration refusal).
  - `--created-by` (default `write_marker`): recorded in the marker.
  - `--force`: required to change an existing slug.
  - `--host-key`, `--site`, `--dry-run`.
- Steps:
  1. Prints `Target:` and `Slug:`.
  2. Reads the existing marker as root. A failed read, or a read that says neither present nor absent, is `FAILED to read the existing marker ...` (`REFUSING to write a fresh one over it`), exit 1.
  3. If present: prints its content. The same slug prints `identity unchanged: ... (re-writing the same marker)`. A different slug prints `identity CHANGE: old -> new`; without `--force` it is refused (`REFUSING to change an existing project identity without --force.` explaining that every dashboard row and the Syncthing folder id are keyed on it, and suggesting `--slug <old>`), exit 3. With `--force`: `--force given: reassigning this project's identity.`
  4. If absent: `no existing marker at ... -- writing a fresh identity`.
  5. Keeps every other key already in the marker except `slug` and `created_by` (printing `preserving additive marker keys: ...`). A marker that is not valid JSON prints that its keys cannot be preserved.
  6. Writes the marker as root, after checking the project directory exists (`MISSING: <path>`, remote exit 2).
- Output: remote output, then `Done.` or `FAILED (remote exit code N)`.
- Dry run: no connection; the existing marker is not read; prints the remote script.

## Publish a search index onto the live NAS (source: publish_db.py, broll_drain.py)

- Purpose: replace the live b-roll search index (`broll.db`) or music search index (`music.db`) on the NAS with the workstation's copy. It must not corrupt the database the dashboard container holds open, it keeps the previous copy for rollback, and for b-roll it keeps rows that exist only on the NAS.
- **Dry run is the default.** Nothing on the NAS moves without `--apply`. `--dry-run` is accepted but changes nothing.

### The two indexes

| | `--which broll` | `--which music` |
|---|---|---|
| Source | `broll/web/data/broll.db` in the repo | `music/web/data/music.db` |
| Live file | `broll.db` in the b-roll archive folder under the tree root (site.toml `[tree] pool_root/tree_name`) | `<[apps] root>/music-data/music.db` |
| Container path | `/broll-data/broll.db` | `/music-data/music.db` |
| Tables checked for shrinking | `videos`, `segments`, `embeddings` | `tracks`, `windows`, `tags` |
| Drained (NAS-only rows kept) | yes | no |
| Older schema than live | refused | allowed (the music app updates a swapped file itself) |

- Missing site values are configuration refusals naming `[tree] pool_root/tree_name` or `[apps] root`.

### Flags and environment

- `--which broll|music` (required).
- `--source PATH` (default the in-repo database). Missing: `FAILED: no database at <path>. Pass --source, or build the index first.`, exit 1.
- `--allow-schema-skew`, `--allow-shrink`, `--shrink-pct N` (default 10), `--no-integrity-check`, `--allow-loss`.
- `--apply-drain BUNDLE`: skip the publish and only merge an existing drain bundle into the live index.
- `--rollback`, `--from-prev PATH`.
- `--apply`, `--dry-run`, `--host-key`, `--site`, `--nas-kind`.
- Environment: `TRUENAS_HOST`, `TRUENAS_USER`, `TRUENAS_PW`.

### Publish steps, in order

1. Prints `Publishing <what>`, `from:` and `to:` (with the container path).
2. Checkpoints the source database's write-ahead log into the main file, with a 30 second lock wait.
   - Prints `checkpointed <name> (WAL truncated)`.
   - Or a WARNING when it cannot checkpoint, or when another process holds a read lock. It then publishes what is in the file.
3. Takes a consistent local snapshot with SQLite's backup function. It goes into a temporary workstation folder (prefix `ccsync-publish-`), always deleted at the end.
4. Verifies the snapshot locally: an integrity quick check plus row counts of the checked tables.
   - Prints `local snapshot: <size>, quick_check <result>` and the counts.
   - Not `ok`: `FAILED: the local snapshot of <name> does not pass quick_check (...). Nothing was sent; the live index is untouched.`, exit 1.
5. Reads the live index's row counts and schema version through the dashboard container's Python.
   - On failure: `NOTE: could not read the live index's row counts (<why>). Publishing without the shrink check -- normal for a first publish, worth a look otherwise.`
6. Schema version check (SQLite `user_version`), only when both versions are readable:
   - Source newer than live: refused (`FAILED: the index you are publishing is schema vN and the deployed app has stepped its own to vM ... Deploy the dashboard first, then publish. Nothing was sent ...`).
   - Source older than live: refused for b-roll only. The running app would never update it, and every ingest push would fail on a missing column.
   - `--allow-schema-skew` turns the refusal into a printed note. A refusal exits 1.
7. Shrink check: for each checked table whose live count is non-zero and whose new count is lower by more than the threshold, prints `<table>: <before> rows live -> <after> in the new index (<pct>% fewer)` and refuses: `FAILED: the new index is more than N% smaller than the live one ... Pass --allow-shrink if the shrink is intended (a prune, a re-scope).`, exit 1. With `--allow-shrink` it prints a note and continues.
8. Creates a NAS staging folder:
   - Under `/tmp` on TrueNAS.
   - On Synology under `<[apps] root>/staging`. That folder is created as root, owned by the SSH user, mode 700; a failure there is only a NOTE.
   - No staging folder at all: `FAILED: no staging dir on the NAS -- the live index is untouched.`, exit 1.
9. Uploads the snapshot by SFTP, with an SSH timeout that grows with the file size.
   - Transport failure: `FAILED: the transfer did not finish (...) -- the live index is untouched (staging left at <dir>).`, exit 1.
   - Then compares the staged byte count with what was sent. A mismatch is `FAILED: the staged copy is X bytes, Y were sent -- ...`, exit 1. Success: `staged copy verified: N bytes`.
10. **b-roll only, the drain:** copies the rows that exist only in the live NAS copy into a bundle file beside the live index, `broll.db.drain-<YYYYmmddTHHMMSS>`. It is read through the container from the live file, opened read-only.
    - The bundle holds:
      - every video row that an ingest item points at, or whose share belongs to an ingest batch, with its segments, transcript segments, themes, quality flags and embeddings;
      - share roots that belong to ingest batches or carry a collection;
      - every ingest batch and ingest item;
      - a key list of every live video with its share and relative path;
      - the bundle version (1), the source path, the counts and the number of batches still open.
    - A live index older than the ingest tables yields "nothing exists only on the NAS". No live index yields "nothing to preserve".
    - Prints `drain taken: N fleet-ingested clips, B ingest batches (O still running), I items -> <bundle>`.
    - A drain that cannot be taken refuses the publish: `FAILED: could not drain the live broll.db (...). Nothing was swapped. ...`, naming the staging folder, exit 1. `--allow-loss` publishes anyway, with a note.
11. Builds the swap script. This is the deploy's database-swap script (part 21c):
    - The staged copy is copied beside the live file as `<target>.new`.
    - Owner and permissions:
      - On Synology the live file's owner and ACL are copied onto the candidate with `synoacltool -copy`. A failure is a NOTE; there is never a chown or chmod.
      - On TrueNAS b-roll is owned `<dataset owner>:editors`, mode 660.
      - Music is owned `<uid>:<private gid>`, mode 660.
    - Unless `--no-integrity-check`, an integrity check runs on the candidate on the NAS, through the container's Python, falling back to a host Python. Not `ok`: `PRAGMA quick_check on the staged <name> did not answer ok (got "...") -- ... The live index is UNTOUCHED.`, remote exit 11.
    - A path containing an apostrophe is refused before anything is sent.
    - The live file and its `-wal`/`-shm` are renamed to `<target>.prev-<stamp>`, then the candidate is renamed into place.
12. Runs the swap as root. On Synology it goes through the platform's root wrapper, so `docker` and the Synology tools are found; on TrueNAS through `sudo`.
    - Failure: `FAILED to install <name> (remote exit N): ... The live index is still in place -- it is only ever replaced by a rename, and that rename rolls back.` The exit code is the remote code.
    - Success: `published: <target> (<size>); previous index kept at <target>.prev-<stamp>`.
13. **b-roll only, the merge:** merges the drain into the newly live file in one transaction, with a 60 second lock wait.
    - A drained clip that is already present (same share and path) is left as published.
    - Other clips are inserted under new ids, and their "duplicate of" links are re-pointed. An unresolvable link becomes empty.
    - Child rows go only with clips that were inserted. An embedding whose own segment did not come across is dropped.
    - Share roots are added only when absent.
    - Ingest batches and items replace same-id rows, with their clip links re-pointed.
    - When any clip was inserted, the index's search-generation counter is raised by one.
    - Only columns both files have are copied.
    - Success: `drain applied: N clips put back (M were already in the new index), B batches, I items, E embeddings` and `the drain bundle is kept at <path>`.
    - Failure: `WARNING: the new index is live, but the drained rows have NOT been merged into it yet (...). Nothing is lost -- they are in <bundle>. Put them back with: python publish_db.py --which broll --apply-drain <bundle> --apply`, exit code **3**.
14. Ends with `Roll back with: python publish_db.py --which <which> --rollback --apply`, exit 0.

### Files, dry run, and the other two modes

- **Left on the NAS:** one `<name>.prev-<stamp>` (with its sidecars) per publish, never deleted by this script; b-roll drain bundles, never deleted; the staging folder.
- **Dry-run publish:**
  - Does every local step, plus the read of the live counts through the container, and the schema and shrink checks.
  - Then prints `[dry-run] would SFTP ...`, the drain description (b-roll), the full remote swap script, and `[dry-run] nothing was changed. Re-run with --apply.`
- **`--apply-drain BUNDLE`:**
  - Prints `Merging <bundle> into the live <name>` and merges as in step 13.
  - Failure: `FAILED to apply the drain (...). The live index is unchanged by this command: the merge is one transaction and it rolled back. The bundle is still at <path>.`, exit 1.
  - Safe to run twice. A dry run changes nothing.
- **`--rollback`:**
  - Finds the newest `<name>.prev-*` in the live folder with a root `find` (60 second timeout), ignoring `-wal`/`-shm` files. Or uses `--from-prev`.
  - Refusals, each exit 1 with nothing changed:
    - `--from-prev` naming a sidecar: `FAILED: <path> is a SQLite sidecar, not an index. ...`;
    - the folder cannot be listed: `FAILED: could not list <dir> to find the previous <name> (...). Nothing was changed. Name the .prev explicitly with --from-prev if you know it.`;
    - nothing found: `FAILED: no <name>.prev-* found in <dir> -- there is nothing to roll back to. ...`.
  - A dry run without `--from-prev` prints the listing command it would run and the rename it would make; exit 0.
  - Otherwise prints `Rolling back <target>`, `from: <prev>` and `keeping the current one as: <target>.rolledback-<stamp>`. The root script then:
    - moves the live file and its sidecars aside;
    - moves the `.prev` file and its sidecars into place;
    - a `.prev` that vanished in the meantime exits 6.
  - Timeout 300 seconds. Failure: `FAILED to roll back (remote exit N): ...`.
  - Success: `Done.`, plus one of:
    - for music: the app notices a swapped file by itself; an older deployment needs `POST /music/api/reload` or a restart;
    - for b-roll: `Restart the dashboard container if the app does not pick it up ...`.

## Deploy the dashboard: the command line and the order of steps (source: install_dashboard_app.py lines 6034 to 7528, `main`)

- Purpose: install or update the `ccsync-dashboard` app on the NAS. The app is the dashboard plus its add-ons: b-roll search, music search, the YouTube downloader, Timeline Cards, the Footage Sorter and the new Cards editor. Re-running it is the normal update. The helper behaviour each step relies on is in parts 21b and 21c and in the next section.
- **Two stack modes:**
  - "bind": the code trees are copied from this checkout onto the NAS and mounted into a stock Python container.
  - "image": a vendor image carries the code, and no code is copied.
  - In both modes the host code folders are left in place, as the rollback.

### Command-line flags

- `--port` (default 8480): the dashboard's HTTP port.
- `--host-root` (default site.toml `[apps] root`): the NAS folder that holds the app's code and data.
  - Blank is a configuration refusal naming `[apps] root` / `--host-root`.
  - It must match this NAS kind's allowed shape (part 21a). Otherwise: `REFUSING --host-root '<root>': it does not match this NAS's app root shape (...)`, exit 1.
- `--allow-any-host-root`: accept a host root outside that shape. Prints a WARNING that `<root>/app` will be replaced wholesale (moved aside to `app.old.<ts>`, not deleted) and `<root>/data` left alone.
- `--syncthing-gui-url` (default env `SYNCTHING_GUI_URL`, else site.toml `[syncthing] gui_url`): the Syncthing address as seen from inside the container.
- `--bind-lan` (default env `DASH_BIND_LAN`, else `[net] bind_lan`) and `--bind-tailnet` (default env `DASH_BIND_TAILNET`, else `[net] bind_tailnet`): the addresses the dashboard is published on. The NAS kind decides how they are used (part 21a), and a blank or unknown one is refused before anything is uploaded.
- `--image` (default env `DASH_IMAGE`, else `python:3.12.7-slim`): the base image, bind mode only.
- `--mode bind|image` (default site.toml `[stack] mode`, else `bind`). Passing it implies `--recreate` whenever the running app's image differs from the one the mode gives (part 21b).
- `--container-image` (default env `CCSYNC_IMAGE` / `[stack] image`, else `ghcr.io/the-creators-club/ccsync:1`): the vendor image for image mode. A digest pin is accepted.
- `--no-image-pull`: image mode only; skip the pull onto the NAS, for an air-gapped site.
- `--music-data` (default env `MUSIC_DATA_PUSH`, else `auto`): which music data pieces to ship.
  - `auto` ships only the ones the NAS lacks.
  - Other values: `none`, `all`, or a comma list of `db`, `encoder`, `proxies`.
  - A bad value: `FAILED: ...`, exit 1.
- `--cards-commit` (default env `CARDS_COMMIT`, else `main`): which Timeline Cards commit to ship.
- `--cards-src-dir`: ship a directory as it stands instead of a commit.
- `--sorter-commit` (default env `SORTER_COMMIT`, else `master`) and `--sorter-src-dir`: the same pair for the Footage Sorter.
- `--no-ffmpeg`, `--no-node`, `--no-ytdl-bins`: skip provisioning ffmpeg, Node, or deno.
- `--enable-youtube`: turn on the YouTube downloader for this deploy (same as site.toml `[features] youtube_download`).
- `--enable-youtube-unblock`: also provision the anti-blocking parts (same as `[features] youtube_unblock`).
- `--ffmpeg-fetch remote|local` (default env `MUSIC_FFMPEG_FETCH`, else `remote`) and `--push-ffmpeg-from-local`, which equals `--ffmpeg-fetch local`.
- `--rollback-on-unhealthy`: if the dashboard does not come back healthy on this checkout's version, put the previous app tree back and restart (part 21c).
- `--recreate`: delete and re-create the app so compose-level changes take effect. Host `app/` and `data/` survive.
- `--require-snapshot`: stop, exit 2, if the snapshot before the deploy cannot be taken. The default is best effort.
- `--with-host-binaries`: Synology only. Also push the about 1.4 GB of music data and the ffmpeg and deno binaries. On Synology they are skipped by default: without this flag, `--no-ffmpeg`, `--no-ytdl-bins` and `--music-data none` are forced.
- `--yes`: skip typing the NAS's name to confirm `--recreate`. A plain redeploy never asks.
- `--host-key`, `--site`, `--nas-kind`, `--dry-run`.

### Environment variables read in this part of the file

- `DASH_BROLL_ENABLED` (default `1`): turns the b-roll add-on on.
- `BROLL_INGEST_TOKEN`: required and strength-checked when b-roll is on.
- `BROLL_CREATORS_SHARES` (default blank, then site.toml).
- `ANTHROPIC_API_KEY`: optional; the YouTube downloader's AI calls use it.
- `DASH_CARDS_TOKEN`: optional; the Timeline Cards agent secret.
- `DASH_ADMIN_USERS`: who may use the dashboard's admin sections (rules in part 21c).
- `TRUENAS_API_KEY`: through the shared helper.
- `SYNCTHING_API_KEY`, `DASH_REPORT_TOKEN`, `DASH_SESSION_SECRET`, `TRUENAS_PW`: resolved together and masked in dry-run output (part 21c).

### Before anything changes on the NAS (each refusal leaves the NAS untouched)

1. Prints a banner naming the NAS, the site file and the tree (part 21d).
2. Resolves the stack mode and the container image (an unknown mode is refused), the publish addresses, and the NAS kind.
3. SFTP transport check: a site.toml `[net]` SFTP window the NAS cannot serve is refused with `REFUSING to deploy: [net] in site.toml: <why>. Set sftp_chunk_size = "64Ki" and sftp_concurrency = 16 (or remove both lines: a Synology site gets those by default).`, exit 1.
4. On Synology without `--with-host-binaries`, switches off ffmpeg, deno and music data.
5. Requires the tree root (`[tree] pool_root/tree_name`).
6. Requires the local `dashboard` folder: `FAILED: <path> not found -- run from the repo`, exit 1.
7. Prints the TrueNAS version note.
8. Image mode runs its preflight (part 21c). A problem is `FAILED: ...`, exit 1; in a dry run it is `[dry-run] would FAIL: ...` and the run continues. Bind mode prints `stack mode: bind -- the four code trees ship from this checkout and /venv is a host volume (docs/DOCKER.md)`.
9. **b-roll preflight** (when `DASH_BROLL_ENABLED=1`):
   - Bind mode only: the b-roll app must exist in this checkout (`broll/web/app/main.py`, or `BROLL_WEB_SRC`). Otherwise `FAILED: DASH_BROLL_ENABLED=1 but no b-roll app at <path> ...`, with the fixes (repair the checkout, `BROLL_WEB_SRC`, or `DASH_BROLL_ENABLED=0`).
   - Both modes: the ingest token must be strong (part 21b). Otherwise `FAILED: DASH_BROLL_ENABLED=1 but BROLL_INGEST_TOKEN <problem>. ... Generate one with openssl rand -hex 24, or set DASH_BROLL_ENABLED=0.`
   - Each is exit 1; a dry run reports `[dry-run] would FAIL` and goes on.
10. **Music and YouTube downloader:** a missing app in this checkout (`music/web/musicweb/main.py`, `ytdl/web/ytdlweb/main.py`, or `MUSIC_WEB_SRC` / `YTDL_WEB_SRC`) is a NOTE, and the deploy continues without that page. The dashboard reports the mount "absent" and hides its menu link. In image mode both are always considered present.
11. **Timeline Cards:**
    - Resolves the tree to ship (next section). An export error is `FAILED: ...`, exit 1.
    - Prints `Timeline Cards snapshot: <short sha> (<ref>) of <repo> -- <subject>; <ref> ... is now ... ahead of the shipped ...`.
    - A tree without `multicam_pipeline/cards/handler.py` is a NOTE (deploying without `/cards`), mentioning when the package is missing at that commit.
    - NOTEs:
      - `[timeline_cards] editor` set but `/cards` is not going out: the editor is left off;
      - `enabled` without `vault_host`: `/cards` will serve nothing;
      - `media_host` without `media_map`: either alone does nothing.
12. **Footage Sorter:**
    - The same resolution and `Footage Sorter snapshot: ...` line.
    - A tree without `footage_sorter/web.py` is a NOTE.
    - Each of the sorter's configuration problems is printed as a NOTE (next section).
13. Parses `--music-data`.
14. **Secrets and NAS credentials:**
    - On TrueNAS a scoped API key is mandatory unless the site manifest names the legacy password exception (part 21c). The refusal is `FAILED: ...`, exit 1.
    - With a key: prints `NAS credentials for the container: scoped API key (TRUENAS_API_KEY); the admin password is NOT written into the container environment.` and the password is not put in the container.
    - Without a key (only possible with site.toml `[security] allow_nas_password_in_container`): a NOTE that the container will hold the NAS admin password, and how to mint a key with `create_api_key.py`.
    - On Synology: a NOTE that DSM has no API keys, so the container holds the password of `[nas] admin_user`, which should be a dedicated non-admin account.
15. **Feature switches written into the container**, each "1" or "0":
    - `youtube_download`: `--enable-youtube` or `[features] youtube_download`.
    - `youtube_unblock`: `--enable-youtube-unblock` or `[features] youtube_unblock`.
    - `ai_cli_providers`: `[features] ai_cli_providers`, with no flag.
    - `studio_cli_providers`: `[studio] allow_cli_providers`, with no flag and no settings page.
    - `auto_update`: `[features] auto_update`, with no flag.
    - NOTEs: the downloader is on but `ANTHROPIC_API_KEY` is empty (`/ytdl will report 'no working Anthropic API key' until it is`); or unblock is on without download (nothing is provisioned for it).
16. **NAS certificate checking for the container** (part 21c):
    - A refusal is `FAILED: ...`, exit 1.
    - Verification off prints a NOTE recommending a `sha256:` pin.
    - A pin prints `NAS certificate pinned for the container: sha256:...`.
17. **Dashboard admins:** resolved from `DASH_ADMIN_USERS` and the NAS admin (part 21c). A refusal is `FAILED: ...`, exit 1.
18. If site.toml `[stack] project_acl` is `per-project` (the default for a new site), a NOTE: each editor must be added to each project's group with `setup_editor_account.py --name <editor> --project <slug>`, because the dashboard's tick does not add group membership yet.
19. Host-root shape check (see the flags above).
20. **Synology only, step 0:**
    - **Tree share:** when `[tree] share_name` and `pool_root` are both set, makes sure the tree share exists and is usable. Failure: `FAILED: the tree share '<name>' is not usable -- everything below depends on it.`, exit 1. When they are not both set, a NOTE that the share was not checked.
    - **SFTP:** grants SFTP to the editors group. Failure is a WARNING that lanes A and B will fail with "channel closed"; the deploy continues.
    - **Folders:** creates the tree root, Projects, the b-roll archive and the music library folders, as folder creation only. Failure: `FAILED to create the tree root ...`, exit 1. Success: `tree ready: <Projects> (ACL inherited from the share)`.
    - **Container identity:** reads the editors group id and ensures the service user (the site's dataset owner) on the live NAS, and runs the container as that uid:gid (`stack identity: the container will run as U:G (...), read from the NAS`). site.toml `[stack] uid/gid` is only the fallback a dry run shows.
21. **TrueNAS only:** checks that `[stack] uid/gid` match the live NAS accounts. A mismatch is `REFUSING to deploy: ...`, exit 1. When the NAS cannot answer, it is only a warning (part 21c).
22. Decides whether `--mode` implies `--recreate` (part 21b).

### Changes on the NAS, in order

23. With `--recreate`: asks the operator to confirm the NAS (`About to DELETE and re-create the ccsync-dashboard app (<host-root> <root> is not deleted).`).
24. Takes a snapshot of the host root labelled "deploy" or "recreate" (part 21d). This is best effort unless `--require-snapshot`.
25. **Step 1, host folders** (900 second timeout, because recursive ownership walks can be slow):
    - On TrueNAS:
      - Code folders, owned by root, mode 755, mounted read-only: `app`, `broll-web`, `music-web`, `music-encoder`, `music-proxies`, `ffmpeg`, `ytdl-web`, `cards-web`, `sorter-web`, `deno`, `node`. The host root itself is root-owned, mode 755.
      - `data` is owned by `<uid>:<private gid>`, set recursively, mode 770.
      - `venv` is owned the same way, set recursively, mode 700.
      - `music-data`, `ytdl-data` and `sorter-data` get `<uid>:<private gid>`, mode 770, non-recursive.
      - Every folder is created on every site, whether or not its feature is shipped, because a missing mount source stops the container.
    - On Synology the platform's own folder recipe is used (part 21b).
    - Failure: `FAILED to create host dirs: ...`, exit 1. Success: `host dirs ready: <list>`.
26. **Sorter backup folder** (TrueNAS, only when `[footage_sorter] backup_out` is set): created only if missing (next section). Failure: `FAILED to create the sorter's backup folder ...`, exit 1. Success: `sorter backup folder ready: <path> (control, snapshots), created only if missing`.
27. **Music data staging:** on TrueNAS, when music data may ship, `<root>/staging` is prepared (owned by the SSH user, mode 700) for staging it. A failure is a NOTE and `/tmp` is used instead. On Synology the code staging folder `<root>/staging` is always used.
28. **Old staging leftovers:** prunes those in `/tmp` and `<root>/staging` (part 21b).
29. **Shared asset folders:** creates `<tree root>/Assets` and each shared asset library under it (by default `Assets/Luts` and `Assets/Stills`; overridable in site.toml, part 21d).
    - TrueNAS: owner `<uid>:<gid>`, mode 2770. A chmod refusal only prints a NOTE that ownership was still applied.
    - Synology: folder creation only.
    - Any failure is a NOTE that Syncthing may not be able to create the LUT and Stills folders.
    - Success: `shared asset folders ready: Luts, Stills under <tree>/Assets`.
30. **b-roll archive** (when b-roll is on): creates the archive root and its `proxies`, `sprites`, `posters` and `sheets` subfolders, non-recursively.
    - TrueNAS: owner `<uid>:<gid>`, mode 2770, a chmod refusal tolerated.
    - Synology: creation only.
    - Failure: `FAILED to prepare the b-roll archive root ...`, exit 1.
    - Success says which posture was used.
31. **Music library root** `<tree>/Assets/Music` (when music ships): same treatment. Failure: `FAILED to prepare the music library root ...`, exit 1.
32. **ffmpeg:** provisioned when music or the YouTube downloader ships, unless `--no-ffmpeg` (part 21b; never fatal).
33. **deno:** provisioned only when the downloader ships, `youtube_unblock` is on, and `--no-ytdl-bins` is not given (part 21b).
34. **Node:** provisioned only when the new Cards editor is on, unless `--no-node` (part 21b).
35. **Old venv:** in both modes, a `venv` left inside `data/` by an old deployment is moved to `data/venv.quarantined.<YYYYmmddHHMMSS>` and set to mode 700 (`retired the old editor-writable venv to ...`). Failure: `FAILED to retire the old editor-writable venv ...`, exit 1.
36. **Image mode:** prints `image mode: shipping no code. /app, /venv, /broll-app, /music-app and /ytdl-app come from <image>; the host trees under <root> are left exactly as they are and are the rollback (--mode bind).`
37. **Step 2, bind mode only:** installs the dashboard code into `app` by stage, verify and swap (part 21b). Failure: exit 1 with nothing swapped.
38. **Step 2a, bind mode only:** ships the help and licence documents into the app tree. Never fatal.
39. **Steps 2b and 2c, bind mode only:** installs `broll-web` (when b-roll is on) and `music-web`, the same way. A failure after the app swap goes to the post-swap failure path (part 21b: restart onto the new code and report).
40. **Step 2d, music data:** in both modes, when music ships and `--music-data` is not `none`.
    - No local data folder: a NOTE that `/music` will mount empty and search will fail without the text encoder.
    - Otherwise it works out which pieces to ship (part 21c). Pieces absent locally get a NOTE.
    - Prints `music data to ship (forced|not on the NAS yet): db X, encoder Y ... -- total`, or `music data: nothing to ship (--music-data <mode>)`.
    - `db` goes through the database swap (part 21c). `encoder` and `proxies` go through stage, verify and swap into `music-encoder` and `music-proxies`.
41. **Step 2f, bind mode only:** installs `ytdl-web`.
42. **Step 2g, Timeline Cards** (in both modes, because the image cannot carry it):
    - Installs `cards-web`.
    - Writes the local deploy record (next section).
    - Prints `installed Timeline Cards: commit <short> (<ref>), marker DEPLOYED_COMMIT in <root>/cards-web; <moved-on note>`.
43. **Step 2g2, Footage Sorter:** the same for `sorter-web`, with its own record.
44. **Step 2h, image mode:** pulls the image onto the NAS unless `--no-image-pull`. Never fatal.
45. **Step 3, existing app:**
    - With `--recreate`: if the app exists it is deleted (`deleted app for re-create: ccsync-dashboard`). A delete failure prints the error and exits 1.
    - If the NAS cannot say whether the app is installed, this goes to the post-swap failure path.
46. **Existing app, no `--recreate` (the usual redeploy):**
    - Only restarts the container. The compose settings are NOT rewritten.
    - Prints `restarted container: <name>`, then one of two NOTEs:
      - image mode: a restart keeps the container's current image; a new one needs `--recreate`, `--mode image --container-image <new>`, or the NAS UI's update.
      - bind mode: `NOTE: only the CODE was updated. Compose-level changes -- bind addresses ..., image tag, healthcheck, env vars -- need --recreate to take effect ...`.
    - A failed restart: `NOTE: docker restart failed (...); restart the 'ccsync-dashboard' app from the TrueNAS UI to pick up the new code.` and the deploy exits 1.
    - Image mode then verifies how the container booted (part 21c).
    - Then verifies the dashboard answers healthy (part 21c). In image mode the expected version is the one that was serving before the restart.
    - Prints the snapshot verdict. Exit 1 if either check failed, else 0.
47. **New app, or after `--recreate`:**
    - Asks the NAS which datasets hold the tree and the host root, and whether a snapshot folder can be mounted for the dashboard's RECOVERY page.
      - Found: `snapshots for the recovery page: <host path> -> /snapshots (ro,rslave)` plus propagation advice.
      - Not found: `NOTE: this deploy found no snapshot directory it could mount, so Settings -> RECOVERY can only print commands. Name one with site.toml [tree] snapshot_dir.`
    - Warns when the tree or the app data has no snapshot schedule (next section).
    - When the sorter has a pool but no time zone, reads the NAS's time zone.
      - Read: `sorter time zone: <zone> (read from the NAS)`.
      - Not read: `NOTE: ... the sorter will run its 04:00/04:30 jobs in UTC, not the NAS script's local time.`
    - Builds the container definition (part 21c). It includes, among others:
      - the SSH host-key pin for the container: the operator's recorded key, else `[nas] ssh_hostkey`;
      - the SFTP port `[net] sftp_port` (default 22);
      - `[nas] ssh_key_probe` (default `1`).
    - **Synology only:** also renders a compose file whose secrets are references, and a separate secrets file. The secrets file is written only readable by root (mode 0600), and holds:
      - `SYNCTHING_API_KEY`, `DASH_REPORT_TOKEN`, `DASH_SESSION_SECRET`, `BROLL_INGEST_TOKEN`;
      - `TRUENAS_PW` and `DASH_NAS_PW`, both the NAS password;
      - `ANTHROPIC_API_KEY`, `DASH_CARDS_TOKEN`;
      - `PG_PASSWORD`, the Resolve project server password, generated once and kept in `~/.ccsync/pg_password` on the workstation (part 21d).
      - A real run prints a paragraph saying the Postgres password was generated, an existing database is re-keyed to it on start, it must be entered once in each editor's Resolve database entry, and port 5432 is published on the LAN and tailnet addresses only.
      - A dry run lists the secret names without values.
    - Creates the app (part 21a).
      - Failure: prints the snapshot-mount refusal hint when one applies, then the snapshot verdict, and exits with the create's code.
      - Dry run stops here with the snapshot verdict.
    - Image mode: verifies the boot (exit 1 on failure). Then verifies health (exit 1 on failure, after the snapshot verdict).
    - Success: `installed custom app: ccsync-dashboard on port <port>`, the snapshot verdict, and `Next: open http://<tailnet-ip>:<port>/ and check /api/v1/health; then set dashboard_url/dashboard_token in each editor's ~/.ccsync/config.toml.`

### Exit codes

- 0 is success.
- 1 is a refusal or failure.
- 2 is a configuration refusal or unconfirmed `--recreate`, through the shared wrapper (part 21d).
- When the create fails, the exit code is the create's own code.

## Deploy helpers for the add-ons, sources and constants (source: install_dashboard_app.py lines 1 to 2050; inventoried by a helper agent from those lines)

### Paths, exclusions and timeouts

- Code folders never uploaded: `.venv`, `__pycache__`, `.pytest_cache`.
- b-roll, music, YouTube downloader and Cards also exclude `.git`, `.github`, `tests` and `node_modules`.
- Music and the YouTube downloader also exclude `data`, so a developer's databases and downloads never ship.
- Cards also excludes `docs`, `deploy`, `scratch`, `golden`, `tools` and `.claude`.
- Remote tree steps get at least 300 seconds, scaled by size at 5 MiB per second.
- NAS staging folders named `ccsync-*-upload.*` older than 120 minutes are treated as leftovers of a failed run (pruned per part 21b).
- Local sources:
  - `dashboard/` in the repo.
  - b-roll: `broll/web`, or env `BROLL_WEB_SRC`.
  - music: `music/web`, or env `MUSIC_WEB_SRC`; music data defaults to `<music source>/data`, or env `MUSIC_DATA_SRC`.
  - YouTube downloader: `ytdl/web`, or env `YTDL_WEB_SRC`.

### Documents shipped into the app

- Required: `HOW_IT_WORKS.md`, `EDITOR_SETUP.md` and the whole `legal` docs folder, copied to `<root>/app/docs`.
- The optional extra list comes from the dashboard's own published-documents list in this checkout. When that list cannot be loaded, only the required set ships.

### Music data pieces

| Piece | What it is | Shipped to | Notes |
|---|---|---|---|
| `db` | `music.db` | (database swap, part 21c) | its `-wal`/`-shm` move with it |
| `encoder` | `text_encoder/` | `<root>/music-encoder` | about 482 MB |
| `proxies` | `proxies/` | `<root>/music-proxies` | about 906 MB |

- The music library is `<tree root>/Assets/Music`.

### Pinned downloads

- **ffmpeg:**
  - URL `https://johnvansickle.com/ffmpeg/releases/ffmpeg-7.0.2-amd64-static.tar.xz` with a fixed SHA-256.
  - Fetch mode `remote` by default (the NAS downloads it); `local` downloads on the workstation into `<repo>/.cache/ffmpeg` and pushes it over the LAN.
  - Remote install timeout 1800 seconds; local download timeout 300 seconds. Env `MUSIC_FFMPEG_URL`, `MUSIC_FFMPEG_SHA256`, `MUSIC_FFMPEG_FILE`, `MUSIC_FFMPEG_CACHE` override.
  - The local push prints a GPLv3 notice: the operator must accompany the binary with source or a written offer valid three years, with the source links.
- **deno** (the YouTube downloader's challenge solver):
  - Host folder `deno`, mounted at `/opt/deno`.
  - No pinned default: it needs env `YTDL_DENO_URL` and `YTDL_DENO_SHA256` (or `YTDL_DENO_FILE`); cache `<repo>/.cache/ytdl`.
- **Token-provider sidecar** for the downloader: image `brainicism/bgutil-ytdlp-pot-provider:1.3.1-deno`, port 4416. DORMANT unless downloading and unblocking are both on.
- **Node** for the new Cards editor:
  - Version 24.22.2 for Linux x64 from nodejs.org, with a fixed SHA-256 checked against the published `SHASUMS256.txt`.
  - Host folder `node`, mounted at `/opt/node`.

### Other constants

- Ingest token: at least 24 characters. These placeholders are refused: replace_me, replaceme, replace-me, change_me, changeme, change-me, changethis, todo, tbd, secret, password, token, test, example, your-token-here, xxx, none, null.
- Container healthcheck:
  - The container fetches `http://127.0.0.1:<port>/api/v1/health` with a 5 second timeout and passes when the answer's `ok` is true.
  - Every 60 seconds, timeout 10 seconds, 3 retries, start period 120 seconds.
- Container identity: `[stack] uid` (default 3000) and `[stack] gid` (default 3001). Private folders use `[stack] private_gid`, which defaults to the uid.

### Timeline Cards: what is shipped and how

- **site.toml `[timeline_cards]` keys** (all blank or false by default):
  - `enabled`, `src`, `vault_host`, `media_host`, `media_map`, `root`, `project`;
  - `db_host`, `db_name`, `db_write_allow`, `db_backups`;
  - `server_url`, `editor`;
  - `vault_gid` (default `3000`).
- **Which tree ships**, in order:
  1. `--cards-src-dir` or env `CARDS_SRC`. The directory ships as it stands and prints `Timeline Cards: shipping the DIRECTORY <path> as it stands (explicit override), not a commit snapshot.`
  2. `[timeline_cards] src`, read as a pointer into a git repository. The commit named by `--cards-commit` (default `main`) is exported with `git archive` into a temporary folder that is deleted when the program ends.
  3. A `src` folder that is not in a git repository prints a NOTE and ships the folder as it stands.
  4. No source configured: no Cards, and no complaint.
- **Refusals, before anything on the NAS moves:**
  - the source is not a directory;
  - it is not inside a git repository;
  - it could not be resolved against its repository;
  - the paths do not compare (for example a substituted drive or junction);
  - there is no such commit (`no commit '<ref>' in the Timeline Cards repository at <root> ... Pass --cards-commit with a branch, tag or hash that exists there.`);
  - that commit has no such subfolder;
  - `git archive` failed;
  - the snapshot could not be unpacked;
  - the snapshot is empty (`... is EMPTY. Shipping it would leave the NAS with an absent <mount> behind a green healthcheck, so nothing was shipped.`).
- **Uncommitted-work note:** when the exported commit is the current HEAD and the working copy has modified or untracked files under the shipped folder: `NOTE: N file(s) in <path> are modified or untracked and are therefore NOT in this deploy (first 6, and K more). The snapshot is commit <sha> (<ref>) and holds its tracked files only: commit them first if they were meant to ship.`
- **Marker file `DEPLOYED_COMMIT`**, written into the shipped tree on the NAS. It holds `commit`, `short`, `ref`, `repo`, `subtree`, `subject`, `committed`, `exported` and `dirty_at_export`.
- **Local deploy record** on the workstation: `~/.ccsync/state/cards_deployed.json` (env `CCSYNC_CARDS_RECORD` overrides).
  - It holds the same facts.
  - A directory deploy records an empty commit plus `override=<dir>`.
  - Not written in a dry run. Write failures are ignored.
- **"Moved on" note:** when the ref now points past the shipped commit: `<ref> in <repo> is now <sha> (N commits), ahead of the shipped <sha>`.
- **Container settings:**
  - `DASH_CARDS_ENABLED` is 1 only when `enabled` is set and a tree ships.
  - When enabled, the code is mounted at `/cards-app`.
  - The vault is mounted read-write at `/vault` when `vault_host` is set.
  - Media is mounted read-only at `/media` when `media_host` is set; the media map is passed only then.
  - `root`, `project`, the database keys and `server_url` are passed through as given.
  - `vault_gid` is added to the container's groups when there is a vault.
  - The fleet job roots become `vault=/vault` and `media=/media` for the mounts that exist.
- **New Cards editor:** on only when `editor` is true AND Cards is enabled. It then sets `DASH_CARDS_EDITOR=1` and `DASH_NODE=/opt/node/bin/node`.

### Footage Sorter: what is shipped and how

- **site.toml `[footage_sorter]` keys:**
  - `enabled`, `src`, `pool_host`, `dest_root`, `vault_root`, `pool_gid`, `cloud_state`, `backup_out`;
  - `backup_out_owner` (default `alex`);
  - `source_roots` (a string or a list);
  - `legacy_id_roots` (a table);
  - `timezone`.
- **Which tree ships:**
  - Shipped like Cards, from `--sorter-src-dir` / env `SORTER_SRC` / `[footage_sorter] src`. The default ref is `master`, or `--sorter-commit`.
  - Only the `footage_sorter` and `public` folders ship. A directory deploy copies those two without `__pycache__` or `.pyc` files.
  - Local record: `~/.ccsync/state/sorter_deployed.json` (env `CCSYNC_SORTER_RECORD`).
- **Container settings:**
  - `DASH_SORTER_ENABLED` is 1 only when `enabled` is set and a tree ships.
  - When enabled, the code is mounted at `/sorter-app`.
  - The data folder is `/sorter-data`, with a cache under it.
  - The settings are passed as JSON, and only when `pool_host` is set. They hold:
    - the source roots, the destination root, the staging root (the first source root);
    - the ffmpeg folder `/opt/ffmpeg`;
    - the legacy id roots and the vault root;
    - `/cloud-state` and `/backup-out` when mounted;
    - the time zone when known.
- **Mounts:**
  - The whole pool, read-write, at `/pool`.
  - The cloud state, read-only, at `/cloud-state`. Refused, and not mounted, when it lies inside the pool.
  - The backup folder, read-write, at `/backup-out`.
  - The pool group and the editors group are added to the container's groups when used.
- **Backup folder creation** (TrueNAS): `backup_out`, `backup_out/control` and `backup_out/snapshots` are created only when missing.
  - New folders are owned `<backup_out_owner>:editors`, mode 2770, and created under a temporary name and renamed into place.
  - An existing folder is left alone, except an empty root-owned one, which is given that owner and mode.
- **Time zone:** site.toml wins. Otherwise the NAS is asked over SSH, with a 30 second timeout: `/etc/timezone`, then `timedatectl`, then the `/etc/localtime` link. A failure prints `WARNING: could not read the NAS's time zone (...)`.
- **Configuration NOTEs, never fatal:**
  - enabled without `pool_host`;
  - `cloud_state` inside `pool_host` (not mounted);
  - `cloud_state` or `backup_out` not an absolute host path;
  - `backup_out` or `cloud_state` set without `pool_host`;
  - `pool_host` without `source_roots`, or without `dest_root`;
  - any root (source, destination or legacy id key) not under `/pool`, because a move across filesystems would fail.

### Snapshot support for the dashboard's RECOVERY page

- **Datasets:** the tree dataset is `[tree] dataset`, the app dataset is `[apps] dataset`. When blank, they are asked of the NAS at deploy time. Any failure, a Synology NAS, or a dry run gives blank.
- **Snapshot folder:** from `[tree] snapshot_dir` plus `[tree] snapshot_projects_subpath` (overrides everything). Otherwise `<dataset mount>/.zfs/snapshot`, with the subpath `<path inside dataset>/<projects folder>` (default `Projects`).
  - The NAS must confirm the folder exists, checked as root with a 60 second timeout. Any doubt means no mount.
- **Mount:** read-only at `/snapshots` with mount propagation `rslave`. Env `CCSYNC_SNAPSHOT_RSLAVE=0`/`no`/`false` drops `rslave`.
  - When a create is refused while `rslave` was asked for, a NOTE suggests re-running with that switch.
  - Whenever there is a snapshot mount, the deploy prints how to check propagation with `findmnt` and `docker exec <container> ls /snapshots/...`, warning that an empty listing makes RECOVERY report every project missing.
- **Snapshot schedule warning:** for the tree and the app data, `WARNING: no snapshot floor -- <label>: <detail>` and `Fix it, then re-check with: python setup_snapshots.py --list --apply`. Skipped in a dry run.

## What the scripts need on the workstation (source: requirements.txt, requirements.lock)

- Python with paramiko 3.4 or later (SSH and SFTP), requests 2.31 or later, urllib3 2.0 or later. pytest and PyYAML are listed for the test suite. The lock file pins exact, hash-checked versions.
- `git` is needed to ship Timeline Cards or the Footage Sorter as a commit snapshot.
- A local `tailscale` is used only by the health check's "path from here" check, and is optional.

## Looks redundant or overlapping

- **Folder sharing:** `accept_device.py --folder-id` shares a folder by hand, while its own output says the dashboard's enforcement owns sharing and will undo a hand-made share. `setup_syncthing_folder.py` overlaps the dashboard collector's own folder provisioning, including a duplicate copy of the WAN tuning values and the ignore-pattern list.
- **Two GUI-login paths:** `secure_syncthing_gui.py` exists as a script, and also as a gentler installer-called function with different rules (keeps an existing login, writes credentials first). One action, two behaviours.
- **Marker parsing:** `setup_syncthing_folder.py` and `write_marker.py` both read the `.ccsync-project` marker over SSH with near-identical present/absent/unavailable handling. `setup_tree.py` writes the same marker a third way (only if absent).
- **Safety defaults are inconsistent:**
  - Three scripts default to dry run with `--apply`: `publish_db.py`, `setup_snapshots.py`, and part of `setup_editor_account.py`.
  - The rest default to acting, with `--dry-run`.
  - `setup_editor_account.py` has both `--apply` and `--dry-run`, for different modes.
- **Cards and Footage Sorter shipping:** each has its own tree resolution, snapshot export, record file, marker and pre-flight notes, as near-duplicates.
- **Optional-binary provisioning:** ffmpeg, deno and Node are three separate provisioning paths, each with its own pin, cache and checksum rules.
- **Two Synology routes to the same container:** the deploy builds the container definition as a TrueNAS dictionary AND as a compose file, two descriptions kept in step by hand.
- **Health checking in two places:** `check_health.py` and the deploy's post-restart probe both check dashboard health, by different routes (HTTP from the workstation versus inside the NAS).
- **Many off-by-default add-ons in one deploy command:** YouTube downloader, unblock sidecar, deno, AI command-line providers, studio command-line providers, auto-update, Timeline Cards, the new Cards editor with Node, the Footage Sorter with cloud-state and backup mounts, music data, and project-server Postgres. All are wired into one deploy command.
- **b-roll index publishing:** the drain and merge (`broll_drain.py`) exists only because the published file replaces a live file the dashboard also writes. The music index solves the same problem the opposite way, with a separate tool.

## Claims the code does not back

- `accept_device.py`'s docstring says step 1 "confirms the device really is pending". It only prints a note and never blocks.
- `setup_syncthing_folder.py`'s docstring and final line say to use `accept_device.py` to share the folder with each editor's device. `accept_device.py` itself says folder sharing is no longer part of the normal workflow and is undone by the dashboard for mapped editors.
- The `setup_syncthing_folder.py` docstring lists the folder settings (send-receive, watcher, staggered versioning, ignore delete). The code also sets ignore-permissions, a 3600 second rescan, and two pull-tuning values the docstring does not mention.
- `publish_db.py`'s b-roll rollback message says "the b-roll app reopens the database per connection, so a rename is normally enough". A comment directly above it in the same file says that was never true of a long-lived connection, and the publish spec says `/broll` does not re-step a swapped file.
- `create_api_key.py` prints `WARNING: --allow-admin-key: the key acts as the ADMIN` whenever no `--username` is given. That includes `--shape allowlist` runs where `--allow-admin-key` was not passed and no account is involved.
- `secure_syncthing_gui.py`'s docstring says "THE PASSWORD IS SHOWN ONCE". The script mode also writes it to a plaintext file in the operator's home folder (as the docstring goes on to say). The script mode always replaces an existing GUI login, unlike the installer mode.
- `setup_snapshots.py`'s docstring says that on Synology, without the Snapshot Replication package, "this script prints the exact DSM click path and exits non-zero". In a dry run a "manual" result alone exits 0.
- `install_dashboard_app.py`'s `--with-host-binaries` help text mentions pushing "Claude" binaries. The Claude command-line binary is no longer provisioned anywhere in the deploy; only ffmpeg and deno are affected.
- `install_dashboard_app.py`'s module docstring: see part 21c and the 1-2050 notes. It describes bind mode as "THERE IS NO IMAGE BUILD" and "a stock pinned python:3.12.7-slim", which does not hold for image mode, and it omits the environment variables `CARDS_SRC`, `SORTER_SRC`, `CCSYNC_CARDS_RECORD`, `CCSYNC_SORTER_RECORD`, `CCSYNC_SNAPSHOT_RSLAVE` and `DASH_CARDS_TOKEN`.
- `install_dashboard_app.py` mentions `YTDL_CLAUDE_URL`, `YTDL_CLAUDE_SHA256` and `YTDL_CLAUDE_FILE` only in a comment; nothing reads them.
- `install_dashboard_app.py` comments say the Cards database-backups default is "beside the mirror on the app's own volume". The deploy passes the site value through as given, blank by default.
- The four part files carry their own "Claims the code does not back" lists for the code they cover.

## Could not determine

- Whether site.toml values that the deploy and the shared code read when the program loads are re-read after `--site` names a different file. Part 21d covers the loading rule; the deploy's module-level values are computed at import.
- Whether the snapshot folder guess `/mnt/<dataset>/.zfs/snapshot` is right on a NAS where a dataset has a custom mount point. A wrong guess simply gives no RECOVERY mount.
- Whether TrueNAS accepts the `ro,rslave` mount option for the snapshot folder. The code says this was not verified live.
- Whether the Syncthing app's `/data` mount (`install_syncthing_app.py --container-mount` and `setup_syncthing_folder.py --container-mount`) matches the current catalog chart. The code marks it as an assumption.
- What exactly the drain and merge in `publish_db.py` does to an ingest batch that starts between the drain and the rename. The code says such a batch is not seen, and the merge replaces batch rows by id.
- **Coverage of this file:**
  - Read line by line for this file: every file in `server/` except the four ranges covered by the part files, `install_dashboard_app.py` lines 1 to 2050, and the tests.
  - `install_dashboard_app.py` lines 1 to 2050 were inventoried by a helper agent from a full reading, and its notes are condensed here without a second reading.
  - `README.md` in `server/` was not used, by rule.
