# NAS backends: TrueNAS and Synology side by side

Everything here runs from the operator's workstation against the NAS. There are two channels:

- **SSH as the NAS admin.** Every privileged command is `echo "$SUDO_PW" | sudo -S ...`. The password goes to the remote shell's standard input, so it never appears on the remote command line.
- **The NAS web API.** On TrueNAS this is `https://<host>/api/v2.0/...` through `common.truenas_api`. On Synology it is the DSM Web API through `common.synology_api`.

Unless noted, failure lines go to stderr.

## Choosing the backend (source: `__init__.py`, `base.py`, `common.get_backend`/`nas_kind`)
- The NAS kind comes from, in order: the `--nas-kind` flag, the environment variable `CCSYNC_NAS_KIND`, site.toml `[nas] kind`, and finally the default `truenas`. Only `truenas` and `synology` are accepted. Anything else is refused with "unknown NAS kind '<k>': expected one of truenas, synology".
- The Synology backend reports itself as ready, so it is never refused for being unfinished. The old "not yet" refusal text (`PENDING`, "the Synology backend is implemented as of 2026-08-17 -- see docs/SERVER-SYNOLOGY.md") is kept but nothing raises it. **UNREACHABLE.**
- A step a platform deliberately does not automate raises an "unsupported on this backend" error. The error text tells the operator what to do instead.
- Dry-run contract, as stated in `base.py`: in dry-run every operation prints what it would do and returns the same shape as a real run. On the TrueNAS side, `run_ssh` in dry-run prints `[dry-run] ssh <user>@<host>[ -p <port>]: <cmd>` and returns success. `truenas_api` in dry-run prints `[dry-run] <METHOD> https://<host>/api/v2.0<path> params=... body=... auth=api-key|basic:<user>` and returns nothing.

## Where the dashboard app may be deployed (deploy-target guard) (source: `truenas.py` L32-35, `synology.py` L57-61, L161-172)
- **TrueNAS:** the app root must match `^/mnt/[^/]+/apps/ccsync-dashboard(/[^/]+)*$`. The install replaces everything under `<host-root>/app` as root, so a mistyped root is refused before anything moves. The refusal itself is printed by the calling script.
- **Synology:** the app root must match `^/volume\d+/[^/]+/ccsync(/[^/]+)*$`.
  - Pointing the stack at a directory refuses with "refusing to manage a compose stack at '<root>': it does not match this NAS's app root shape (<regex>). Use /volume<N>/<share>/ccsync (site.toml [apps] root)."
  - The stack directory defaults to site.toml `[apps] root`.

## Dashboard container name (source: `truenas.py` L78-81, `synology.py` L130-151)
- **TrueNAS:** `ix-<app_name>-dashboard-1`. The app name defaults to `ccsync-dashboard`, giving `ix-ccsync-dashboard-dashboard-1`.
- **Synology:** the compose project is always called `ccsync`, so the container is `ccsync-dashboard-1`. The stack files are `<stack dir>/compose.yaml` and `<stack dir>/.env`.

## Is the app installed? (source: `truenas.py` L87-105, `synology.py` L209-239)
- **TrueNAS:**
  - Calls `GET /app` for the full list, with no server-side filter, and matches on `name` locally.
  - If the query fails it prints "FAILED to query installed apps: HTTP <code> <text>" and answers "could not tell".
  - In dry-run the answer is always "not installed".
- **Synology:**
  - Runs `docker compose ls --format json --all` as root (timeout 60 s) and looks for a project named `ccsync`.
  - The app name it is given is ignored: there is one stack. Asking "is the dashboard installed" and "is Syncthing installed" is the same question.
  - A command failure prints "FAILED to list compose projects on the NAS: <err>" and answers "could not tell".
  - Output that is not JSON prints "FAILED: `docker compose ls --format json` was not JSON: <first 200 chars>" and answers "could not tell".
  - In dry-run the answer is always "not installed".

## Remove the app for `--recreate` (source: `truenas.py` L107-129, `synology.py` L241-256)
- **TrueNAS:**
  - Calls `DELETE /app/id/<name>` with `{"remove_ix_volumes": false}`, so app volumes are kept.
  - If the response is a job id, it waits for the job (timeout 180 s, poll 2 s).
  - Failure messages: "FAILED to delete app for --recreate: HTTP <code> <text>" and "FAILED: app delete job ended <state>: <err>".
  - In dry-run it reports success.
- **Synology:**
  - Runs `docker compose --env-file <.env> -p ccsync -f <compose.yaml> down --remove-orphans` as root (timeout 300 s).
  - It never passes `-v`, so volumes and the database are kept.
  - Failure message: "FAILED to bring the stack down for --recreate: <err or 'exit N'>".

## Deploy (create) the dashboard stack (source: `truenas.py` L180-241, `synology.py` L258-359, L1455-1502, L1409-1434)
- **TrueNAS:**
  - Calls `POST /app` with `{custom_app: true, app_name, custom_compose_config: <compose dict>}`. The rendered compose file text and env values passed in are ignored.
  - Dry-run prints "[dry-run] would create custom app <name> on port <port>".
  - If the POST fails it prints "FAILED to create custom app: HTTP ...", followed by "Manual fallback: TrueNAS UI > Apps > Discover Apps > (...) > Install via YAML, paste dashboard/deploy/compose.yaml and fill in SYNCTHING_API_KEY and DASH_REPORT_TOKEN." The return code is 1.
  - If the response is a job id, it prints "app create job <id> accepted; waiting for it to finish (the image pull can take a few minutes)..." and waits up to 900 s, polling every 5 s.
  - If the job does not succeed it prints:
    - "FAILED: app create job <id> ended <state>: <err>";
    - a note that a bind address the NAS does not have fails at this point with 'cannot assign requested address', and to check Apps > <name> in the TrueNAS UI (a partially created app may need deleting);
    - the manual-fallback line again.
    The return code is 1.
  - If the response is not a job id it prints "NOTE: POST /app returned <x> rather than a job id, so the install could not be waited on -- confirm <name> is actually running in the TrueNAS UI before continuing." It still returns 0.
- **Synology:**
  - **Refusals:**
    - No rendered compose.yaml: "FAILED: the Synology deploy needs a RENDERED compose.yaml (install_dashboard_app.render_compose_yaml) -- refusing to invent one."
    - Stack directory outside the app-root pattern: "FAILED: the stack directory '<root>' does not match <regex>".
  - **Staging:** creates `<stack dir>/.stack-stage` as root, owned by the SSH user, mode 700 (timeout 60 s). Failure: "FAILED to prepare <stage>: ...".
  - **Upload:** SFTPs `compose.yaml`, plus `.env` if there are env values, into the stage. The path is translated for DSM's SFTP view (see "Synology SFTP path translation" below). Failure: "FAILED to upload compose.yaml/.env to <stage> -- nothing was changed on the NAS."
  - **Install into place, as root (timeout 120 s):** `install -o root -g root -m 0644` for compose.yaml, `install ... -m 0600` for .env, then `rm -rf` the stage. Failure: "FAILED to install compose.yaml/.env into <root>: ...". Success: "stack files installed: <compose> (0644 root), <.env> (0600 root)".
  - **.env file format:**
    - Six header comment lines saying it holds the session secret, the report token, the Syncthing API key, the b-roll ingest token and the NAS admin password, and must not be copied anywhere.
    - Then one `NAME='value'` line per variable, sorted by name, every value single-quoted.
    - A value containing a newline or a single quote is refused: "<NAME> contains a newline|a single quote, which a .env value cannot carry safely."
    - For `TRUENAS_PW` and `DASH_NAS_PW` the refusal adds that this is the NAS admin password, so the fix is to set one without that character in Control Panel > User & Group and re-run.
    - For any other variable it says to replace it with a fresh one from `openssl rand -hex 24`.
  - **Bring up:** prints "bringing up the ccsync stack (the image pull can take a few minutes)..." and runs `docker compose ... --profile bundled-syncthing up -d --remove-orphans` as root (timeout 1800 s). It prints the last 2000 characters of compose's output.
  - If compose fails it prints "FAILED: `docker compose up -d` exited <rc>." plus a manual fallback command `sudo docker compose -p ccsync -f <compose> --profile bundled-syncthing up -d`. The return code is 1.
  - **After success:** runs `docker compose ... ps --format json` (timeout 120 s) and prints one line per container: "  <Name>: <State> <Status>". It reads both the one-object-per-line and the JSON-array output shapes.
  - **Dry-run:** prints the planned SSH commands and "[dry-run] would bring up the ccsync stack on port <p> from <compose> (profile bundled-syncthing)".

## Restart the dashboard container (source: `truenas.py` L131-146, `synology.py` L361-370)
- **TrueNAS:** `sudo docker restart ix-<app>-dashboard-1` (timeout 120 s). It does not use the app redeploy API.
- **Synology:** `docker compose ... restart dashboard` as root (timeout 300 s).
- On both, a transport error is returned as a failure result (a "guarded" call) rather than a crash, when the calling script provides that. Dry-run counts as success.

## Read the running container's image (source: `truenas.py` L148-158, `synology.py` L372-381)
- Both run `docker inspect --format '{{.Config.Image}}' <dashboard container>` as root (timeout 60 s) and return the last output line.
- Any failure or exception returns an empty string. Read-only.

## Run a command inside a container (source: `truenas.py` L160-165, `synology.py` L383-385)
- **TrueNAS:** `sudo docker exec <container> <argv>`.
- **Synology:** the same command with Synology's tool paths added (see "Synology root commands" below).
- The command arguments are inserted unquoted, as given.

## Addresses the dashboard is published on (source: `truenas.py` L37-49, L167-174, `synology.py` L387-417)
- **TrueNAS:**
  - The LAN address comes from `--bind-lan`, else site.toml `[net] bind_lan`. The tailnet address comes from `--bind-tailnet`, else `[net] bind_tailnet`.
  - Both are mandatory. A blank one refuses with "[net] bind_lan is not configured. Set it in <site file>, or pass --bind-lan. Copy site.example.toml to site.toml and fill it in -- there are deliberately no built-in defaults for site identity (host, pool, tree)." The tailnet message is the same with its own key and flag.
  - Returns `DASH_BIND_LAN=<lan>` and `DASH_BIND_TAILNET=<tailnet>`.
- **Synology:**
  - Both addresses are optional and come from the same flags and keys. Blank ones are skipped. If both are blank it binds 127.0.0.1 only.
  - The values `0.0.0.0`, `::` and `*` are refused: "refusing to publish the dashboard on '<a>': bind it to 127.0.0.1 (the Synology default) or to a specific address. DSM's nginx owns the LAN ports and `tailscale serve` / the DSM reverse proxy is how editors reach it -- see docs/SERVER-SYNOLOGY.md."
  - TrueNAS has no such wildcard check.

## Synology SFTP path translation (source: `synology.py` L197-202; TrueNAS L176-178)
- **TrueNAS:** the path is used unchanged.
- **Synology:** the leading `/volumeN` is stripped, because DSM's SFTP shows every account (the admin included) only its shares. For example `/volume1/docker/ccsync` becomes `/docker/ccsync`, and `/tmp` cannot be reached.

## Synology root commands (source: `synology.py` L63-72, L178-195)
- Every root command runs as `sudo -S -p "" /bin/sh -c 'export PATH=/usr/syno/bin:/usr/syno/sbin:/usr/local/bin:${PATH:-/usr/bin:/bin:/sbin:/usr/sbin}; <cmd>'`.
- Without that PATH, the DSM tools (`synoacltool`, `synowebapi`) and `docker` are not found under sudo.
- The default timeout is 120 s.

## Install Syncthing (source: `truenas.py` L51-59, L243-444, `synology.py` L96-100, L423-444)
- **TrueNAS (catalog app `syncthing`, catalog `TRUENAS`, train `stable`):**
  - **Find the catalog entry:**
    - Tries `GET /app/available?catalog=TRUENAS&train=stable` first, then `GET /catalog/apps` with the same parameters.
    - A 404, a missing response or non-JSON moves on to the next endpoint. Any other failure prints "NOTE: <path> returned HTTP <code>, trying next candidate endpoint".
    - An entry matches on `name`, `id` or `app_name`.
    - In dry-run it prints the lookup it would do and pretends to find version `<unknown-in-dry-run>`.
  - **Refusals:**
    - Not found: "FAILED: could not find catalog entry for 'syncthing' in catalog=TRUENAS train=stable via either /app/available or /catalog/apps. The Apps API shape may have changed again -- ...". Return code 1.
    - Entry missing `name` or `latest_version` (real runs only): "FAILED: catalog entry for 'syncthing' is missing expected field(s) [...]. Found keys: [...]. Refusing to guess a create payload against an unfamiliar schema -- ...". Return code 1.
  - Prints "found catalog entry: syncthing version <v> (catalog=TRUENAS, train=stable)".
  - **Create:** `POST /app` with `{app_name, catalog_app, train, version, values}`. The values are:
    - run as uid site.toml `[stack] uid` (default **3000**) and gid `[stack] gid` (default **3001**);
    - web port: published at the given GUI port; if site.toml `[syncthing] gui_bind` is set it is bound to that one address (`host_ips`), otherwise on every interface;
    - sync port: TCP and UDP **22000**, published; no host networking;
    - config storage: a TrueNAS-managed volume, dataset `config`, no ACL;
    - one extra mount: host path → container mount, no ACL.
  - Dry-run prints "[dry-run] container mount for --host-path would be assumed at: <mount>" and "[dry-run] (CONFIRM this against the real chart before running setup_syncthing_folder.py)".
  - **Failures:**
    - POST fails: "FAILED to install syncthing: HTTP ..." plus a hint about 422/400 payload-shape errors. Return code 1.
    - The create job is waited on (900 s, poll 5 s, "app create job <id> accepted; waiting for it to finish (image pull can take a few minutes)..."). A failed job prints "FAILED: app create job <id> ended <state>: <err>" and "Check Apps > syncthing in the TrueNAS UI -- a partially created app may need deleting...". Return code 1.
    - A response that is not a job id gives the same "NOTE: POST /app returned ..." line as the dashboard deploy.
  - **Success:** "installed app: syncthing version <v>, GUI port <p>, host path <h> -> container mount <m>", then "Next: fetch the GUI's API key (TrueNAS UI > Apps > syncthing > Web UI, or the app's config file) and pass it to setup_syncthing_folder.py / accept_device.py / check_health.py."
  - **Securing the GUI right away:**
    - Needs environment variable `SYNCTHING_API_KEY` and a GUI address from `SYNCTHING_GUI_URL`, else site.toml `[syncthing] gui_url`.
    - If both are present it calls `secure_syncthing_gui.secure_gui` and prints "Syncthing GUI: <msg>" on success, or "WARNING: Syncthing GUI not secured: <msg>" on failure.
    - When a password was generated it adds "(the generated password is in the credentials file named above; it is not printed here)".
    - An exception prints "NOTE: could not secure the Syncthing GUI yet (<exc>)."
  - **If it was not secured:**
    - With no `gui_bind`: a WARNING that the GUI is published on EVERY interface (port <p>) with no password, that the dashboard sets one on its first cycle once given `SYNCTHING_GUI_URL` and the key, and the command `SYNCTHING_API_KEY=... python server/secure_syncthing_gui.py`, plus advice to set `[syncthing] gui_bind`.
    - With `gui_bind`: "Then: SYNCTHING_API_KEY=... python server/secure_syncthing_gui.py -- the GUI has no password until you do ...".
    - The return code is 0 either way.
- **Synology:** does nothing on purpose and returns 0. Syncthing is the `bundled-syncthing` profile inside the ccsync stack. It prints:
  - that Syncthing is part of the compose stack, not a package;
  - that it mounts the tree at <mount>, with its GUI on 127.0.0.1:<port> only;
  - a tunnel command `ssh -L <p>:127.0.0.1:<p> <admin>@<nas>`;
  - that the API key is the `SYNCTHING_API_KEY` in <.env>;
  - that the GUI has no login yet, with the `secure_syncthing_gui.py` command.
  - It does not run the secure step itself.

## Editors group: find and ensure (source: `truenas.py` L450-488, `synology.py` L454-544)
- **TrueNAS:**
  - Find: `GET /group?group=<name>`, matched exactly. A failure prints "FAILED to query group '<n>': HTTP ..." and **exits the process (code 1)**. In dry-run it returns nothing.
  - Ensure:
    - Dry-run prints "[dry-run] would ensure group '<n>' exists" and returns (-1, -1).
    - An existing group prints "group already exists, skipping: <n> (gid <gid>, id <id>)".
    - Otherwise `POST /group {"name": n, "smb": true}`, then a re-read to learn the unix gid. Prints "created group: <n> (id <id>, gid <gid>)".
    - A failed create prints "FAILED to create group ..." and exits 1.
  - The group's database id and its unix gid are different numbers. The user endpoints need the database id.
- **Synology:**
  - Find: `SYNO.Core.Group get name=[<n>]`. Error 3205 means "no such group". Any other error prints "FAILED to query group '<n>': <exc>" and exits 1. The gid doubles as the id.
  - Ensure:
    - Dry-run prints "[dry-run] would ensure group '<n>' exists (SYNO.Core.Group create)".
    - An existing group prints "group already exists, skipping: <n> (gid <g>)".
    - Otherwise `SYNO.Core.Group create` (POST). Error 3206 ("already exists", created meanwhile) is tolerated. Any other error prints FAILED and exits 1.
    - The gid comes from the create response, else a re-read. If the group still is not listed: "FAILED: group '<n>' was created but DSM does not list it" and exit 1.
    - Success prints "created group: <n> (gid <g>)".
    - DSM allocates groups from 65536.
  - Adding a user to the group calls `SYNO.Core.Group.Member add group=<g> name=[<user>]` and then always reads membership back with `SYNO.Core.User.Group get`. The add call reports success even when it does nothing, so the read-back is the real check.

## Editor accounts: find and get (source: `truenas.py` L490-504, `synology.py` L550-616)
- **TrueNAS:**
  - Find: `GET /user?username=<n>`, matched exactly. A failure prints "FAILED to query user ..." and exits 1.
  - Get: `GET /user/id/<id>`. A failure returns "HTTP <code>".
- **Synology:**
  - Find: pages through `SYNO.Core.User list type=local` 200 at a time, with the extra fields email, description, expired and uid. It deliberately does not use `SYNO.Core.User get`, which sometimes reports an existing user as missing.
  - The name match is **case-insensitive**.
  - The returned record reports:
    - id = username, home `/var/services/homes/<u>`;
    - group gids from one group lookup;
    - `sshpubkey` = "(installed)" if `~/.ssh/authorized_keys` is non-empty (checked over SSH, timeout 60 s), else empty;
    - `smb` always true;
    - locked when `expired` is anything but "normal";
    - shell always `/sbin/nologin`.
  - Get: the same lookup by username. Not found returns "DSM does not list a user called '<id>'".

## Create an editor account (source: `truenas.py` L506-550, `synology.py` L618-693, L799-854, L1513-1520)
- **TrueNAS:** `POST /user` with:
  - the given username and full name; primary and supplementary group = the editors group's database id; no new group created;
  - `home` = the homes parent folder, with home creation on (TrueNAS appends the username itself);
  - shell: `/usr/bin/bash` when site.toml `[stack] editor_shell` is `shell`, otherwise `/usr/sbin/nologin`. The default is `sftp-only`, which gives nologin. Any other value refuses with "[stack] editor_shell is '<x>'; expected one of sftp-only, shell (...)";
  - password not disabled, a random password, the given SSH public key, SMB on, not locked.
  - A failure returns "HTTP <code> <text>".
- **Synology:**
  - Dry-run prints "[dry-run] would create DSM user '<u>' (nologin, home under /var/services/homes), add it to <editors> and write /var/services/homes/<u>/.ssh/authorized_keys".
  - **Refusals, checked before anything is created:**
    - Reserved names, matched case-insensitively (`admin`, `guest`, `anonymous`, `root`, `system`, `http`): "'<u>' is a DSM built-in account -- refusing to create it."
    - Names starting with `sc-`: "'<u>' looks like a DSM package account (sc-*) -- refusing to create it."
    - An existing account with uid outside **1024 to 169999**: "'<u>' is a system or package account (uid <uid>) -- refusing to create it."
    - An existing account not in the editors group: "'<u>' already exists on the NAS and is not in the 'editors' group -- refusing to take over an account this script did not create. Add it to the group in DSM first, or pick a different username."
  - **Create:** `SYNO.Core.User create` (POST) with:
    - a random password: 24 random URL-safe bytes plus "aA1", which satisfies DSM's mixed-case-and-digit policy;
    - description = the full name (or the username), empty email, not expired;
    - the user may change their password; the password never expires; no email notification; the password is not sent.
  - Error 3107: "DSM says '<u>' already exists but does not list it as a local account -- it is probably a package account. Pick a different username."
  - **Then:**
    - Adds the user to the editors group with read-back. On failure: "created '<u>' but DSM did not add it to 'editors' (Group.Member add reports success even when it ignored its arguments -- this is the read-back failing)".
    - Installs the SSH key (next bullet).
  - **Installing the SSH key, over SSH as root (timeout 60 s):**
    - Refuses an empty key: "no SSH public key given".
    - If the home folder does not exist: "/var/services/homes/<u> does not exist -- DSM's User Home service is off, so the account has nowhere to keep an authorized_keys. Turn it on in Control Panel > User & Group > Advanced and re-run."
    - Otherwise, with any failure stopping the script, it:
      - sets umask 077;
      - creates `~/.ssh`;
      - writes the key to `~/.ssh/.authorized_keys.ccsync`, then moves it over `authorized_keys`;
      - chowns `~/.ssh` recursively to `<u>:users`, chmods `.ssh` to 700 and `authorized_keys` to 600;
      - reads the file back to confirm the key line is there.
    - Failure: "installing the SSH key failed (exit <rc>): <detail or 'the key was not there when it was read back'>". Success: "installed SSH key: <home>/.ssh/authorized_keys (0600, owned by <u>)".
    - The key file is **replaced**, not appended to.
  - Every Synology user's primary group is `users` (gid 100). The editors group is supplementary.

## Update an existing editor (source: `truenas.py` L552-563, `synology.py` L695-712)
- **TrueNAS:** `PUT /user/id/<id>` with `{sshpubkey, smb: true, groups: existing groups + editors}`. The key is replaced.
- **Synology:**
  - Dry-run prints "[dry-run] would re-add '<u>' to <editors> and rewrite its authorized_keys".
  - The same refusals as create apply, with the wording "refusing to modify it".
  - Re-adds the user to the editors group with read-back ("DSM did not add '<u>' to 'editors' (read-back failed)"), then rewrites authorized_keys.

## Make SSH key-only (source: `truenas.py` L565-575, `synology.py` L783-795)
- **TrueNAS:**
  - `PUT /user/id/<id> {"password_disabled": true}`. Success = "ok".
  - A 422 whose text contains "SMB" = "smb-refused". This is the expected answer, because TrueNAS refuses this for SMB users.
  - Anything else = "failed" with the HTTP details.
- **Synology:** always "not-applicable", with "DSM has no password_disabled flag; the account's password is used only for SMB and the dashboard login. SSH stays key-only."

## Editor login shell (source: `truenas.py` L506-516, L617-636, `synology.py` L714-724, L760-765)
- **TrueNAS:**
  - The shell for new accounts comes from `[stack] editor_shell`, as described under "Create an editor account".
  - Changing an existing editor's shell (used only by setup_editor_account's `--migrate-existing`) calls `PUT /user/id/<id> {"shell": <s>}`.
  - On a 422 it adds a hint to check `GET /api/v2.0/user/shell_choices` for this release's name for nologin.
- **Synology:**
  - The shell is always reported as `/sbin/nologin`.
  - Asking for nologin returns success with "already nologin (DSM's default for a local account)".
  - Asking for any other shell refuses: "DSM does not offer editors an interactive shell at all -- SSH is administrators-only there, whatever /etc/passwd says. Leave [stack] editor_shell = "sftp-only" on a Synology site."

## List the editors (source: `truenas.py` L577-594, `synology.py` L726-734)
- **TrueNAS:**
  - `GET /user`, keeping accounts whose `groups` contain the editors group id, or whose primary `group` is that id (as a plain number or inside an object).
  - Errors: "HTTP ..." and "GET /user: response was not JSON". In dry-run it returns an empty list.
- **Synology:** meant to list the members of `[stack] group` (default `editors`) with shell nologin. **In a real run it crashes** because of a tuple-count mismatch: the member listing returns three values and this code expects two. The only caller is setup_editor_account.py L379 (`--migrate-existing`). **UNREACHABLE in practice: it always raises.** In dry-run it returns an empty list.

## Offboarding: revoke an editor's key (source: `truenas.py` L596-615, `synology.py` L736-758)
- **TrueNAS:** `PUT /user/id/<id> {"sshpubkey": ""}`, with `"locked": true` added when locking is requested.
- **Synology:**
  - Empties `~/.ssh/authorized_keys` if it exists; the file is kept (timeout 60 s). Failure: "could not clear <home>/.ssh/authorized_keys: ...".
  - With locking requested it also calls `SYNO.Core.User set expired=now`. Failure: "key removed, but the account could not be expired: <exc>".
  - Dry-run prints "[dry-run] would truncate <home>/.ssh/authorized_keys[ and expire the account]".

## sshd policy for the editors group (source: `truenas.py` L638-709, `synology.py` L767-781)
- **TrueNAS:**
  - Manages a block inside the SSH service's "Auxiliary Parameters" (`GET /ssh` / `PUT /ssh {"options": ...}`). The block is:
    - begin marker `# --- ccsync editors policy (managed by setup_editor_account.py) ---`;
    - `Match Group <group>` with ForceCommand internal-sftp, PasswordAuthentication no, AllowTcpForwarding no, X11Forwarding no, PermitTunnel no, PermitTTY no;
    - end marker `# --- end ccsync editors policy ---`.
  - There is no ChrootDirectory.
  - Only the text between the markers is replaced; the operator's other parameters are kept. Without markers the block is appended after a blank line.
  - Results: "unchanged" if identical, "ok" after a PUT. Failures: "GET /ssh: HTTP ...", "GET /ssh: response was not JSON", "PUT /ssh: HTTP ...".
  - Dry-run prints "[dry-run] would GET /ssh and ensure its auxiliary parameters carry:" followed by the block.
- **Synology:** does nothing and returns "unchanged". It prints "sshd policy: nothing to install on DSM -- <group> members are nologin, interactive SSH is administrators-only, and lanes A/B use the SFTP subsystem. Keep 'Enable SFTP service' on and SSH restricted in Control Panel > Terminal & SNMP."

## Home folder permissions for sshd (source: `truenas.py` L61-64, L711-793, `synology.py` L856-930)
- **TrueNAS, ensure:**
  - `POST /filesystem/setperm` with `{path: home, mode: "700", uid, gid, options: {stripacl: true, recursive: false, traverse: false}}`.
  - Waits for the job (timeout 120 s, poll 2 s).
  - Failures: "FAILED to set permissions on <home>: HTTP ..." or "...: job <id> ended <state>: <err>".
  - Success: "home permissions set: <home> -> <u>:<gid> mode 0700 (ACL stripped)".
- **TrueNAS, verify:**
  - Runs `sudo stat -c "%a %U" <home>`.
  - Warnings: "WARNING: could not stat <home> to verify permissions: ...", "WARNING: unexpected stat output ...", "WARNING: could not parse mode ...".
  - Problems detected: the mode is group- or world-writable, or the owner is not the user. These print "WARNING: <home> will be REJECTED by sshd StrictModes: ..." plus "The editor's key is installed but public-key auth will fail with 'bad ownership or modes for directory' in the NAS auth log."
  - Success: "verified: home <home> is mode 0<m>, owned by <o> (sshd StrictModes will accept it)".
- **Synology, ensure:**
  - Touches only `~/.ssh`: mkdir, chown -R `<u>:users`, chmod 700, and chmod 600 on authorized_keys if it exists (timeout 60 s). The home folder itself is never changed.
  - Failure: "FAILED to set permissions on <home>/.ssh: ...".
  - Success: "home permissions set: <ssh_dir> -> <u>:users mode 0700 (the home itself is left alone -- chmod would delete its Synology ACL)".
  - The uid and gid arguments are ignored.
- **Synology, verify:**
  - Stats the home, `.ssh` and `authorized_keys`.
  - Problems detected: the home is group- or world-writable or not owned by the user; `.ssh` is not (700, user); `authorized_keys` is not (600, user).
  - The warning adds "DSM logs NOTHING for a StrictModes refusal -- the editor will just see 'Authentication failed'. Repair ~/.ssh with chmod; repair the HOME with `synoacltool -enforce-inherit`, never chmod."
  - Success: "verified: <home> is 0<m> owned by <o>, .ssh 0700, authorized_keys 0600 (sshd StrictModes will accept it)".

## Service account the container runs as (source: `truenas.py` L795-800, `synology.py` L932-1015)
- **TrueNAS:** not supported. It refuses with: the '<name>' service account is created once, by hand, when the pool is built (server/README.md); no script on TrueNAS creates it, and the container's uid/gid come from site.toml `[stack] uid/gid`.
- **Synology:**
  - Dry-run prints "[dry-run] would ensure service account '<n>' exists (synouser --add, nologin) and read its uid" and returns -1.
  - Checks for the account with `id -u <name>`.
  - **If it is missing**, it runs `synouser --add <name> <random password> 'CC Sync service account' 0 '' 0` (timeout 120 s). The password is briefly visible on the remote command line; it is random and never stored.
    - Failure: "could not create the service account '<n>' on the NAS: ...".
    - If no uid can be read afterwards: "created '<n>' but the NAS does not report a uid for it".
    - Success: "created service account: <n> (uid <uid>, /sbin/nologin)".
  - Otherwise it prints "service account already exists, skipping: <n> (uid <uid>)".
  - A uid outside 1024 to 169999 refuses: "refusing to run the stack as uid <uid> ('<n>'): DSM local accounts start at 1024 and package accounts live at 170000+. Pick a normal local account."
  - **Tree share permission:** if site.toml `[tree] share_name` is set, it gives the account its own read-write permission on that share (`SYNO.Core.Share.Permission set`, local_user). Success prints "service account '<n>' has its own RW permission on '<share>'"; failure prints a "NOTE: could not grant ..." line and carries on.
  - **Editors group:** if the account is in the editors group it is removed (`SYNO.Core.Group.Member remove`) and the removal is read back.
    - Success: "removed service account '<n>' from '<group>' (it is not an editor)".
    - Still a member afterwards: "NOTE: '<n>' is still in '<group>' after remove -- take it out in DSM so it stops listing as an editor."
    - Errors give a "NOTE: could not check/remove ..." line.
  - Returns the uid.

## SFTP access (source: `truenas.py` L802-806, `synology.py` L1017-1065, L1437-1452)
- **TrueNAS:** nothing to do; always succeeds.
- **Synology:**
  - Dry-run prints the plan.
  - **Service:** `SYNO.Core.FileServ.FTP.SFTP get`.
    - If it is enabled: "SFTP service already enabled (port <portnum or 22>)".
    - Otherwise it calls `set enable=true portnum=<port or 22>` and prints "enabled DSM's SFTP service on port <p> -- lanes A and B are rclone over SFTP, and with it off key auth SUCCEEDS and the channel is then closed with nothing in any log".
    - An error prints "FAILED to check/enable the SFTP service: ..." and fails.
  - **Privilege rules:** `SYNO.Core.AppPriv.Rule list app_id=SYNO.SFTP`.
    - If they cannot be read: "NOTE: could not read the SYNO.SFTP privilege rules (...) -- check Control Panel > Application Privileges > SFTP by hand." This still counts as success.
    - A rule counts as a deny when it lists deny addresses and no allow addresses, and applies to everyone or to this group. Per-user rules and other groups' rules are ignored.
    - Any such rule fails with "FAILED: an application-privilege rule DENIES SYNO.SFTP to '<group>': [...]. Lanes A and B would fail with 'channel closed' and nothing in any log. Remove the rule in Control Panel > Application Privileges > SFTP."
    - Otherwise: "verified: no SYNO.SFTP deny rule covers '<group>' (the privilege is granted by default on DSM)".

## Create the share or dataset (source: `truenas.py` L812-818, `synology.py` L1071-1132)
- **TrueNAS:** not supported. It refuses with: datasets and SMB shares are created in the TrueNAS UI (Datasets > Add, Shares > Windows Shares); nothing here creates '<name>' at '<path>'.
- **Synology:**
  - The path must be `/volumeN/<name>`. Otherwise: "FAILED: '<path>' is not /volume<N>/<name> -- a DSM shared folder IS a top-level directory on a volume, so the share name and the path cannot disagree."
  - Dry-run prints the plan.
  - **Look up the share:** `SYNO.Core.Share get` (extra fields: ACL support, snapshot support). Error codes 402, 3301 or 0 mean "not there". Any other error prints "FAILED to query share ...".
  - **If it exists:** "shared folder already exists, skipping: <n> (<vol_path>)".
  - **Otherwise create it:** `SYNO.Core.Share create` with description "CC Sync tree", Btrfs copy-on-write on, recycle bin off, not hidden, compression off. Prints "created shared folder: <n> at <path> (Btrfs CoW on, no recycle bin)".
  - **Then the group permission:** `SYNO.Core.Share.Permission set` (local_group, the group read-write, no deny), then reads back `list` (offset 0, limit 100).
    - Error: "FAILED to set share permissions ...".
    - Not writable on read-back: "FAILED: DSM accepted the permission call but still does not list '<g>' as writable on '<n>'".
    - Success: "share permissions verified: <g> has RW on <n> (which is what installs the inheritable editors ACE -- no chmod is involved anywhere)".

## Project tree permissions (shell lines returned to setup_tree.py) (source: `truenas.py` L820-867, `synology.py` L90-94, L1134-1208)
- **TrueNAS:**
  - `sudo chown -R <owner>:<group> <base>`, echoing "ownership set: <owner>:<group> on <base>". In per-project mode the group is the project group (`proj-<slug>`) instead of the editors group.
  - Each folder above the project gets `chmod 3770` (setgid plus sticky bit):
    - echoes "container protected: 3770 (setgid+sticky) on <dir> -- one editor can no longer delete the project directory of another";
    - or "container NOT protected: chmod blocked on <dir> (likely ZFS aclmode=restricted) -- see docs/TENANCY.md".
  - Then `find <base> -type d -exec chmod 2770` for every directory:
    - echoes "permissions set: 2770 (setgid) on all directories under <base>";
    - or "permissions NOT set: chmod blocked on this dataset (likely ZFS aclmode=restricted) -- ownership above is still correct, only the setgid bit is missing".
  - Both chmod steps are non-fatal.
- **Synology:** no chmod and no chown, ever. The owner argument is ignored.
  - **Ensure the editors permission entry:** checks `synoacltool -get <base>` for `group:<g>:allow`.
    - If present: "ACL ok: <g> already has an inherited allow ACE on <base> (...)".
    - Else it runs `synoacltool -enforce-inherit <base>` and re-checks: "ACL repaired by inheritance: synoacltool -enforce-inherit <base>".
    - Else it adds `group:<g>:allow:rwxpdDaARWc--:fd--` with `synoacltool -add`: "ACL set: <ace> on <base>".
  - **Linux-mode warning:** if the ACL output contains "It's Linux mode", it prints to stderr "WARNING: <base> is in Linux mode -- its Synology ACL was destroyed by a mode/ownership change. New files there inherit nothing and land world-writable (DSM sftp runs umask 000). Repair: synoacltool -enforce-inherit".
  - **Per-project mode is only partly supported:**
    - It adds the same kind of entry for the project group if missing ("ACL ok: ..." or "ACL set: ...").
    - It always prints "OPERATOR TODO (docs/TENANCY.md): <proj> can now write <base>, but the share-wide <g> ACE is INHERITED here and still grants every editor. Break inheritance on this folder in File Station (...) and remove the <g> entry. DSM exposes no scripted way to do it."
    - The folders above the project are ignored (no sticky bit).

## Synology tree ACL health check (source: `synology.py` L1210-1234)
- Runs `synoacltool -get <path>`.
- Answers:
  - could not read: "could not read the ACL of <path>: ...";
  - Linux mode: "<path> is in Linux mode -- something chmod'd it and its Synology ACL is GONE. ... Repair with `synoacltool -enforce-inherit <path>`.";
  - no editors entry: "<path> has no allow ACE for group '<g>' -- editors cannot write there. Repair with `synoacltool -add <path> 'group:<g>:allow:rwxpdDaARWc--:fd--'`.";
  - ok: "<path> carries an allow ACE for <g> (Synology ACL intact)".
- TrueNAS has no equivalent.
- **UNREACHABLE from scripts:** no script in `server/` calls it; only the tests do.

## Synology group member listing (source: `synology.py` L1236-1250)
- `SYNO.Core.Group.Member list` (offset 0, limit 200). Error 3205 returns "group '<g>' does not exist -- no editor accounts yet".
- Its only callers are the broken Synology editor listing (above) and the tests.

## Take a snapshot before something risky (source: `truenas.py` L869-1001, `synology.py` L1252-1312)
- **TrueNAS:**
  - **Which dataset:** the path must start with `/mnt/`. The dataset is found on the NAS with `sudo df --output=source <path> | tail -n 1` (timeout 60 s). If that answer is empty, a device path or contains whitespace, it falls back to the path with `/mnt/` removed.
  - When the dataset differs from the plain path it prints "<path> is inside dataset <ds> (not a dataset of its own) -- snapshotting <ds>".
  - **Name:** the one-call form names the snapshot `ccsync-pre-<label>-YYYYmmdd-HHMMSS`. The label defaults to "manual", with non-`[A-Za-z0-9_.-]` characters turned into "-".
  - **Refusals:**
    - "FAILED: '<path>' is not under /mnt, so there is no ZFS dataset to snapshot."
    - A name not matching `^[A-Za-z0-9][-A-Za-z0-9_.:]*$`: "FAILED: '<name>' is not a usable snapshot name (letters, digits and -_.: only)."
  - **Take it:** `sudo zfs snapshot <ds>@<name>` (timeout 120 s). An "exists" error counts as success. Other failures: "FAILED to snapshot <ident>: ...". Success: "snapshot taken: <ds>@<name>".
  - Dry-run prints "[dry-run] would take a ZFS snapshot: <ident> (...may snapshot the parent dataset...)".
  - There is a strict variant of the dataset lookup that returns empty instead of falling back. It is not used in these files.
- **Synology:**
  - The path must be under `/volumeN/<share>`. Otherwise: "FAILED: '<path>' is not under a /volume<N>/<share> path, so there is no shared folder to snapshot."
  - **Take it:** `SYNO.Core.Share.Snapshot create name=<share> desc=<label or name>`. DSM names the snapshot from the clock itself, so the requested name becomes the description. The result lives at `/volumeN/@sharesnap/<share>/<timestamp>/`.
  - Prints "snapshot taken: <share> @ <when> (/volume?/@sharesnap/<share>/<when>)" or "snapshot taken: <share> @ <when> (<name>)".
  - Failure: "FAILED to snapshot share '<share>': ...".
  - Dry-run returns `<share>@<dsm-timestamp>`.

## List existing snapshots (source: `truenas.py` L1003-1024, `synology.py` L1314-1337)
- **TrueNAS:**
  - `sudo zfs list -H -t snapshot -s creation -o name,used,creation -d 1 <ds>` (timeout 120 s), oldest first.
  - Failure prints "could not list snapshots of <ds>: ..." and returns an empty list.
- **Synology:**
  - `ls -1 /volumeN/@sharesnap/<share>` as root (timeout 60 s), not through the API.
  - "Created" is the directory name; "used" is blank.
  - Failure prints "could not list snapshots of <share>: ...".
  - It sorts nothing itself, so the order is whatever `ls` gives.

## Scheduled (periodic) snapshot tasks (source: `truenas.py` L887-890, L1026-1124, L1136-1152, `synology.py` L1339-1397)
- The retention policy (labels, naming schema, schedule, how long to keep, recursive) comes from setup_snapshots.py, not from here.
- **TrueNAS:**
  - **Refusals:**
    - Not under `/mnt`: "'<path>' is not under /mnt -- no dataset to schedule".
    - A dataset with no `/` in it (a whole pool): "refusing to schedule snapshots on '<ds>': that is a pool, not a dataset, and a recursive task there would snapshot everything on it. <path> is a plain directory in '<ds>', so it has NO snapshot floor of its own. Give it a dataset: `zfs create -p <...>` ... The paths come from site.toml [tree] pool_root and [apps] root."
  - **Read existing tasks:** `GET /pool/snapshottask`, filtered to this dataset. Failures: "could not read existing snapshot tasks: HTTP ..." and "GET /pool/snapshottask did not answer JSON".
  - **Per policy entry**, the task is:
    - dataset; recursive (default true); how long to keep (value and unit); naming schema; schedule;
    - enabled = true;
    - allow_empty = true.
  - Tasks are matched by naming schema.
  - New task: `POST /pool/snapshottask`, printing "created snapshot task: <ds> <schema> (keep <v> <unit>)".
  - Matching task, compared only on the fields the code sets:
    - identical: "snapshot task already correct, skipping: ...";
    - otherwise `PUT /pool/snapshottask/id/<id>`, printing "updated snapshot task: <ds> <schema> (<changed fields>)".
  - Each entry's result is created, updated, unchanged or failed (with the HTTP code and up to 200 characters).
  - Dry-run prints "[dry-run] would ensure a periodic snapshot task on <ds>: <label> -- <schema>, keep <v> <unit>(s), at <m h dom mon dow>".
- **Synology:**
  - Non-share path: "'<path>' is not under /volume<N>/<share>".
  - **Per policy entry**, it tries `SYNO.Core.Share.Snapshot.Setting set` with a schedule of `{enable: true, hour (default "*"), minute (default "0")}` and `keep_count` = the "how long to keep" number.
  - Any exception gives "manual" with "DSM would not schedule <label> snapshots of '<share>' from here (<exc>). Do it once by hand:" followed by the click path:
    - install "Snapshot Replication" (free) from Package Center;
    - Snapshots > share > Settings > Schedule: every hour, every day;
    - Retention: advanced policy, keep 24 hourly and 30 daily;
    - repeat for the share holding the app stack;
    - verify with `ls /volume1/@sharesnap/<share>/`.
  - Success: "scheduled snapshots: <share> (<label>)", result "created".
  - The naming schema, time unit, recursive flag, day-of-month, month and day-of-week are all **ignored**.
  - It never reports "updated" or "unchanged".

## Tailscale status (diagnostics) (source: `truenas.py` L1130-1133, `synology.py` L102-103, L1403-1406)
- **TrueNAS:** `sudo docker exec tailscale tailscale status --json`. Tailscale is a TrueNAS app container named `tailscale`.
- **Synology:** `/var/packages/Tailscale/target/bin/tailscale status --json` as root (timeout 60 s). Tailscale is a DSM package here.

## Settings read in these files
- **site.toml keys:**
  - `[net] bind_lan`, `[net] bind_tailnet`
  - `[syncthing] gui_bind`, `[syncthing] gui_url`
  - `[stack] uid` (default 3000), `[stack] gid` (default 3001)
  - `[stack] editor_shell` (default sftp-only)
  - `[stack] group` (default editors)
  - `[tree] share_name` (Synology only)
  - `[apps] root` (Synology's default stack directory)
  - `[nas] kind`
- **Environment variables:** `SYNCTHING_API_KEY`, `SYNCTHING_GUI_URL`, `CCSYNC_NAS_KIND`.
- **Flags:** `--bind-lan` and `--bind-tailnet` are named in refusal text; `--nas-kind` selects the backend.

## Supported on one platform only
- **TrueNAS refuses:**
  - creating the service account;
  - creating the share or dataset.
- **TrueNAS does nothing for:**
  - granting SFTP.
- **Synology does nothing (deliberately) for:**
  - installing Syncthing;
  - the sshd policy;
  - making SSH key-only ("not-applicable");
  - changing an editor's shell, except to nologin.
- **Synology falls back to manual steps for** scheduled snapshots when the Snapshot Replication package is missing.
- **Synology only:** the tree ACL health check and the group member listing.

## Looks redundant or overlapping
- On both platforms, the one-call snapshot and the snapshot-with-name operations do the same work. On Synology the two bodies are near-duplicates.
- Synology's ensure and verify of home permissions overlap with the key-install step, which already does the same chown and chmod on `~/.ssh`.
- The TrueNAS app-create job wait, its "NOTE ... rather than a job id" line and its failure text are duplicated between the dashboard deploy and the Syncthing install.
- `PENDING` and `_UNSUPPORTED` in synology.py are kept-for-import leftovers and are never used.

## Claims the code does not back
- truenas.py L506-509 says both nologin spellings "are checked" against the allowed shells. The code always uses `/usr/sbin/nologin` and checks nothing.
- synology.py L719-721 says `editor_shell = "shell"` "is refused rather than silently ignored". New Synology accounts get nologin whatever the setting says. Only the change-shell operation refuses.
- synology.py L217-223 says install_syncthing_app "correctly reports 'already installed'". That depends on the caller; this backend's own install reports "nothing to install".
- base.py says every operation returns the same shape in dry-run and opens no connection. TrueNAS user get, create, update and key-only mode have no dry-run branch. In dry-run they would reach `resp.status_code` on an empty response (`truenas_api` returns nothing in dry-run) and crash.
- base.py describes snapshot listing as "oldest first". Synology returns `ls` order.
- Synology snapshot scheduling is described as "Idempotent by (dataset, naming_schema)" in the base interface. The Synology version ignores the naming schema and always reports "created".
- `__init__.py` calls synology.py a "stub the port fills in". It is fully implemented and reports itself ready.

## Could not determine
- Whether any caller hands the Synology backend a stack directory through the deploy guard; that happens in install_dashboard_app.py, which was not read.
- Whether any script calls the Synology tree ACL health check: none in `server/*.py` does.
- What `secure_syncthing_gui.secure_gui` does: not read.
- The exact error codes `synology_api` raises (it may raise code 0); not read.
- Whether the Synology snapshot API's response really has `data` or `time` fields: the code falls back to `<unknown>`.

## Lines read
- `__init__.py`: 1-17, all of it.
- `base.py`: 1-231, all of it.
- `truenas.py`: 1-1152, all of it, in three chunks.
- `synology.py`: 1-1532, all of it, in four chunks.
- `common.py`, to settle meaning only: L250-355, L2100-2181, plus the `truenas_api`, `ok`, `wait_for_job` (defaults 120 s timeout, 2 s poll) and `run_ssh` headers.
- One grep of `server/` for callers of the editor listing, the tree ACL check and the group member listing.
