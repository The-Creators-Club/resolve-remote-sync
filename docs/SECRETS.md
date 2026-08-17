# Operator secrets: where they live, and where they must not

Audience: whoever runs `tools\ship.cmd` and the `server/` scripts for a
deployment — the "base rig" operator. Written 2026-08-17 for
`COMMERCIAL_READINESS.md` item 15 ("base-rig secrets via `setx`").

Companion docs: `SERVER.md` (what each secret is for), `RELEASE.md` (the ship
runbook), `site.example.toml` (everything that is **not** a secret).

## The five secrets

Nothing in this repo has ever had a secret committed to it, and nothing may.
These five live only in the operator's environment and in the NAS:

| Variable | What it opens | Rotate by |
|---|---|---|
| `TRUENAS_PW` | the NAS admin account: SSH `sudo` **and** the REST API. Full control of the pool. | changing the account password on the NAS |
| `SYNCTHING_API_KEY` | Syncthing's GUI API on the NAS — lane C's folder and device config for the whole fleet | Syncthing GUI → Actions → Settings → API key |
| `DASH_REPORT_TOKEN` | the fleet report endpoint every companion posts to; also the shared token in every editor's `config.toml` | re-deploy the dashboard, then re-issue editor configs |
| `DASH_SESSION_SECRET` | dashboard login cookies. A weak or leaked value = a forged admin session | re-deploy; every session is invalidated |
| `BROLL_INGEST_TOKEN` | the b-roll write path (`/broll` ingest). Optional — a site without the b-roll mount never sets it | re-deploy |

`site.toml` holds addresses, paths and names. **No secret ever goes in it**;
that is why it is safe to read, diff and (if you like) commit.

## Do not `setx` them

Every doc in this repo used to say "set each once with `setx`". That was
convenient and wrong. `setx` writes the value **in clear text** into
`HKCU\Environment`, where it:

- stays until somebody deliberately deletes it, long after the machine has
  stopped being a release box;
- is readable by **any** process running as that user — including anything a
  browser, a build tool, an installer or a game launcher runs;
- is **inherited by every process the user launches** from then on, so the NAS
  admin password ends up in the environment of DaVinci Resolve, of the
  companion tray, and of everything they in turn spawn;
- travels with a roaming profile, a profile backup, and any disk image of the
  machine;
- shows up in `Get-ChildItem env:` output, which is exactly what gets pasted
  into a support thread.

There is no threat model in which a NAS admin password belongs in the
registry permanently. `tools\ship.ps1` no longer tells you to put it there.

`CCSYNC_DASHBOARD_URL` and `CCSYNC_ADMIN_USER` are **not** secrets — an
address and a username. `setx` is fine for those two, and convenient.

## What to do instead

### The three-line route (no extra software)

```powershell
.\tools\load_secrets.ps1 -Save     # prompts once per secret, never echoes
. .\tools\load_secrets.ps1         # note the leading dot: loads THIS window
.\tools\ship.cmd
```

`-Save` prompts with `Read-Host -AsSecureString` (so nothing is echoed and
nothing enters the PSReadLine history file) and writes
`%LOCALAPPDATA%\ccsync\secrets\operator.xml` with `ConvertFrom-SecureString`.
That is **DPAPI at `CurrentUser` scope**: the ciphertext can only be decrypted
by that Windows account on that machine. Copy the file elsewhere, or read it
as another local user, and you get nothing. The directory and the file also
get `icacls /inheritance:r` down to you + SYSTEM.

Dot-sourcing sets the variables in the **current window only**. Close it and
they are gone; no child process inherits them tomorrow.

Useful flags: `-Clear` deletes the store and unsets the variables;
`-Path <file>` puts the store somewhere else.

### What this is not

`load_secrets.ps1` is not a secrets manager. DPAPI protects the value at rest
against another user and against a copied file; it does **not** protect it
from malware already running as you, and it is per-machine, so it does not
help a second operator or a CI runner.

A customer running this at any scale should keep the five values in whatever
vault they already have and export them into the shell that runs `ship`:

```powershell
# Windows: PowerShell SecretManagement + any vault extension
$env:TRUENAS_PW = Get-Secret -Name ccsync/truenas-pw -AsPlainText
```

```bash
# CI / Linux: the runner's own secret store, session-scoped
export TRUENAS_PW="$(vault kv get -field=password ccsync/truenas)"
```

The contract `ship.ps1` and the `server/` scripts care about is only "these
names are in the environment of the process that runs me". Anything that
satisfies that is fine.

## How the secrets reach the NAS

Worth knowing, because it is the part that is already careful:

- `server/common.py` pipes the sudo password over **stdin**, never on a
  command line — a native process's argv is readable by any unprivileged
  process on Windows (`Get-CimInstance Win32_Process`).
- `onboard.exe` hands the fleet token to `windows_bootstrap.ps1` in the
  **environment**, not on argv, and the bootstrap clears it immediately so
  nothing it launches inherits it (AUDIT SEC-2).
- Editor-side, the fleet token lands in `~/.ccsync/config.toml` and
  `~/.ccsync/identity.json`. macOS `chmod 600`s both; since 2026-08-17 the
  Windows bootstrap and `windows_upgrade.ps1` run `icacls /inheritance:r` on
  them too (they used to inherit the profile's ACL and set nothing).

## Still owed

- **All five server secrets sit in the TrueNAS/DSM app's compose environment
  in plaintext**, readable by anyone who can `docker inspect` the container.
  That is `COMMERCIAL_READINESS.md` item 6 and is not fixed here; it needs a
  per-tenant secret store on the NAS side, or Docker secrets.
- **One shared fleet token for every editor** — `DASH_REPORT_TOKEN` is the
  same string on every machine, so revoking one editor means re-issuing all of
  them. Per-editor tokens are item 15's other half.
- The code-signing secrets (`CCSYNC_SIGN_*`, `RELEASE.md`) deserve the same
  treatment; they are the signing agent's to move.
