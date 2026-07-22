# server/ -- Creators Club Sync: server-side setup scripts

Scripts that provision the TrueNAS side of the Resolve remote-sync system:
project tree, editor accounts, the Syncthing app + per-project folders, and
a one-shot health check. See `../SPEC.md` (S1 Server setup) for the design
this implements.

**None of these scripts have been run against the NAS.** They were written
to spec, `python -m py_compile`'d, and unit-tested for their pure logic
(slug generation, template folder list, `.stignore` content) only. Every
script also has a `--dry-run` flag that prints the exact SSH command / API
call it would make without opening any connection -- use that first against
the real NAS before trusting a live run.

## Run order

For first-time setup:

1. `install_syncthing_app.py` -- once, installs Syncthing (lane C engine).
2. `setup_tree.py --year Y --series S --project P` -- once per new project.
3. `setup_syncthing_folder.py --project-rel-path Y/S/P` -- once per new project.
4. `setup_editor_account.py --name X --ssh-pubkey-file path.pub` -- once per new editor.
5. Editor runs `installer/windows_bootstrap.ps1` or `installer/macos_bootstrap.sh`,
   sends back their Syncthing device ID.
6. `accept_device.py --device-id ... --folder-id ...` -- once per (editor, project)
   they need access to.
7. `check_health.py` -- any time, to validate the whole server side.

See `../docs/SERVER.md` for the narrative admin-runbook version of this
(onboarding an editor end-to-end, onboarding a project, delete/rename rules).

## Env vars

| Var | Required | Default | Used by |
|---|---|---|---|
| `TRUENAS_PW` | yes | -- | every script that talks to TrueNAS (SSH password + REST API basic auth) |
| `TRUENAS_HOST` | no | `192.168.0.102` | same |
| `TRUENAS_USER` | no | `truenas_admin` | same |
| `SYNCTHING_GUI_URL` | no (or pass `--gui-url`) | -- | `setup_syncthing_folder.py`, `accept_device.py`, `check_health.py` |
| `SYNCTHING_API_KEY` | no (or pass `--api-key`) | -- | same |

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
  **Open question, not resolved by this script:** TrueNAS's
  `password_disabled` flag may also disable SMB auth for the same account
  (SMB is password-hash based). The script sets `password_disabled=True`
  only after verifying `smb` is still `True` afterward; if it isn't, it
  rolls back and prints a warning asking a human to choose. See the
  script's docstring for detail.
- **`install_syncthing_app.py`** -- **the riskiest script here** because
  TrueNAS SCALE's Apps API schema is not something this environment could
  inspect live (no NAS calls were made while writing this). It does a GET
  first to find the catalog entry and validates it has the fields the
  assumed create-payload needs; if the shape doesn't match, it fails with
  a clear message instead of guessing. The assumed create payload, and the
  assumed in-container mount point (`/data`) for the bind-mounted
  `Creators_Club` host path, are documented at the top of the script --
  **confirm both against the live API before trusting this beyond
  `--dry-run`.**
- **`setup_syncthing_folder.py`** -- assumes the container mount point from
  `install_syncthing_app.py` (default `/data`, override with
  `--container-mount` if that assumption was wrong). Folder id is
  `slugify(project-rel-path)`. Sets staggered versioning + the `.stignore`
  equivalent (via `/rest/db/ignores`, not an actual `.stignore` file, since
  Syncthing's REST API manages ignores per-folder without needing SSH).
  Does not share the folder to any device -- that's `accept_device.py`.
- **`accept_device.py`** -- assumes the editor's device ID was already
  obtained out-of-band (printed by their bootstrap script). Safe to re-run
  per project as new editors join.
- **`check_health.py`** -- read-only checks; the postgres check is a raw
  TCP connect (proves the port is open, not that auth works); the
  tailscale check assumes the app's container is literally named
  `tailscale` (per SPEC's "Current state" section) and execs `tailscale
  status --json` inside it via `docker exec` over SSH.

## Local verification (already done for these scripts; re-run if you edit them)

```
cd E:\Projects\resolve-remote-sync\server
python -m py_compile common.py setup_tree.py setup_editor_account.py install_syncthing_app.py setup_syncthing_folder.py accept_device.py check_health.py
python -m pytest tests -v
python setup_tree.py --year 2025 --series FF4 --project Nuclear --dry-run
python setup_editor_account.py --name jsmith --ssh-pubkey-file <any file> --dry-run
python install_syncthing_app.py --dry-run
python setup_syncthing_folder.py --project-rel-path 2025/FF4/Nuclear --gui-url http://x --api-key x --dry-run
python accept_device.py --device-id ABCD --folder-id 2025-ff4-nuclear --gui-url http://x --api-key x --dry-run
python check_health.py --dry-run
```

None of these were run against the real NAS -- `TRUENAS_PW` was never set
and no network call to `192.168.0.102` was made from this session.
