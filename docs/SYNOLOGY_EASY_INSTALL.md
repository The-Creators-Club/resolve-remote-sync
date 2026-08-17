# Synology easy-install — making CC Sync installable by a non-technical studio owner

Written 2026-08-17, alongside `SYNOLOGY_PORT_PLAN.md` (which gets the *code*
running on Synology). This doc is about the *experience*: what a studio owner
with a Synology and no terminal skills goes through, from "I bought this" to
"my editors are syncing". It is a design, not a status — nothing here exists
yet. Where a step depends on a readiness item in `COMMERCIAL_READINESS.md`,
it says so.

## The bar

Today, standing up the server side takes an operator who can SSH as root, set
five secrets in env vars, run six Python scripts in order and read a 476-line
runbook (`SERVER.md`); onboarding one editor takes ~7 touchpoints, three of
them out-of-band messages (see the audit's §F). The target for a Synology
customer:

- **Server:** Package Center → Manual Install → pick the `.spk` → answer four
  questions → "Open". No SSH, no terminal, no env vars, no YAML.
- **Editors:** the admin clicks "Invite editor" in the dashboard, sends the
  resulting link; the editor runs the wizard and pastes the link. No pubkey
  emailing, no device-ID emailing, no separate "approve" step, no Postgres
  credentials typed by hand.
- **Day 2:** updates arrive through Package Center like every other Synology
  app; backups are snapshots the package set up; "something's wrong" is a
  Diagnostics button, not a log file.

## Why a Synology Package (SPK) is the right bootstrap

Every non-technical Synology owner already knows one install path: Package
Center. An SPK gives us exactly the three things the plan's `ServerBackend`
needs on the host and that a container cannot do by itself:

1. **Root on the host at install/upgrade/start time** — `postinst`,
   `postupgrade` and `start-stop-status` run as root, so the package can
   create the shared folder and group, enable SFTP, write the ACL, start the
   compose stack, run `tailscale serve`, and schedule snapshots — the same
   operations `server/backends/synology.py` performs over SSH from the base
   rig, just invoked locally.
2. **A native install wizard** — `WIZARD_UIFILES/install_uifile.sh` generates
   the wizard JSON *at install time as root*, so it can list the box's
   existing shared folders in a dropdown, pre-fill the free-space figure, and
   detect whether Tailscale is installed. Fields it needs: studio name, tree
   share (existing or "create new"), drive letter (default `P:`), and access
   mode is not a question at all -- Tailscale is the only supported way
   editors reach the dashboard (decision 2026-08-17). Everything else is
   derived.
3. **Lifecycle** — Package Center handles update (new SPK = new pinned image
   tag; `postupgrade` pulls and recreates), stop/start, uninstall (data kept
   unless the user ticks the box), and shows an icon in DSM's app menu that
   opens the dashboard.

Declared dependencies (`INFO`: `install_dep_packages="ContainerManager"`,
`arch="x86_64"`, `os_min_ver="7.2-64570"`) mean Package Center itself refuses
ARM units and DSM 6 with a clear message — no support ticket.

Two costs, both one-time:

- **Trust level.** DSM 7 defaults Package Center to "Synology Inc." publishers.
  Until the package is signed through Synology's partner programme, the owner
  must set Package Center → Settings → Trust Level → *Any publisher* (one
  toggle, one screenshot in the guide). Long-term: get it signed.
- **Toolchain.** `pkgscripts-ng`/`spksrc` to build the SPK; the SPK payload is
  small (compose file, helper scripts, icons) because the real code ships as
  container images.

The alternative — asking the owner to create a Container Manager "Project",
paste a compose file, then create shares/users/ACLs by hand — was rejected: it
is the SSH runbook with more clicking.

## What the package does, step by step

`preinst`: check DSM ≥ 7.2, x86_64, Container Manager present, ≥ 50 GB free
on the chosen volume, ports 8480/22000 free (this box has host `:5432` and
`:8080` taken — the postgres profile must not assume 5432). Refuse with a
plain-English reason.

`install_uifile.sh` (wizard): studio name; tree share (dropdown of existing
shares + "create `<Studio>_Projects`"); drive letter; access mode
("Private network via Tailscale — recommended" if the Tailscale package is
detected, else the two screenshots that get it installed and logged in);
"Also host the DaVinci
Resolve project library on this NAS" checkbox.

`postinst` (root, = `ServerBackend.synology` locally):
1. Create group `editors`, service user `ccsync-svc` (nologin) — the stack's
   `APP_UID/APP_GID`.
2. Create/adopt the tree share; write the inheritable `editors` ACE with
   `synoacltool`; create `Projects/`, `Assets/…` from the template list.
3. Enable SFTP (`SYNO.Core.FileServ.FTP.SFTP`), grant `editors` the FTP
   application privilege (spike 2 decides the exact calls).
4. Create a DSM **service account** in `administrators` (`ccsync-admin`,
   generated password, 2FA exempt) — this is the runtime `DASH_NAS_PW`
   equivalent; the human admin's password is never stored.
5. Generate all secrets (`DASH_SESSION_SECRET`, `DASH_REPORT_TOKEN`,
   `SYNCTHING_API_KEY`, `BROLL_INGEST_TOKEN`) into
   `/volume1/docker/ccsync/.env` mode 600 root — the customer never sees them.
6. Render `compose.yaml` from the WP0 template with `NAS_APPS_ROOT=/volume1/
   docker/ccsync`, `NAS_TREE_ROOT=/volume1/<share>/<tree>`, `DASH_BINDS=
   127.0.0.1`, profiles `bundled-syncthing` (+ `project-server` if ticked);
   `docker compose up -d`.
7. Access: `tailscale serve --bg --yes --https=443 http://127.0.0.1:8480`
   and record `https://<nas>.<tailnet>.ts.net` as `dashboard_url`, with
   `DASH_COOKIE_SECURE=1`. If Serve is gated ("Serve is not enabled on your
   tailnet" -- the normal state of a fresh tailnet), the checklist shows the
   one admin-console click ("Enable HTTPS") and retries; there is no other
   publish path (decision 2026-08-17: Tailscale only, verified on the DS423+).
8. Snapshots: create a DSM Task Scheduler entry (`SYNO.Core.TaskScheduler`) —
   or Snapshot Replication schedule if that package is present — hourly/daily
   Btrfs snapshots of the tree share and `/volume1/docker/ccsync/data`.
9. Register the DSM app icon (`ui/config`) pointing at `dashboard_url`.

`start-stop-status`: `docker compose up -d` / `down`; re-apply `tailscale
serve` on start (Serve config survives, but be idempotent).

`postupgrade`: pull the new pinned image tags, `up -d`; run DB migrations
inside the container (the dashboard already migrates on boot).

`preuninst`: `compose down`; keep `/volume1/docker/ccsync/data` and the tree
unless the wizard's "delete my data" box was ticked; remove the serve rule.

## First-run in the dashboard: the setup checklist

The SPK gets the stack up; the dashboard's first admin login lands on a
**Setup** page (new, `ui.py`) rather than the fleet grid, and stays until the
checklist is green:

- NAS: tree share writable as `editors` (a real SFTP write test from the
  container), snapshots scheduled, SFTP on.
- Access: the dashboard URL editors will use (copy button); Tailscale peer
  status if applicable.
- Resolve project library: if hosted here, the host/port/user/password to
  paste into Resolve → Project Manager → Add Project Library (Resolve's API
  cannot add a library, so this stays a copy-paste; the page makes it one).
- Editors: the invite flow below.
- A "Send a test file through all three lanes" button once the first editor
  is in.

Also on that page: **Diagnostics** (a redacted bundle: versions, compose
status, lane health, last 500 log lines — the companion's `copy_diagnostics`
already exists on the tray; this is the server twin) and **Site config
export/import** (`site.toml` + `.env`, encrypted with a passphrase) for
moving to a new NAS.

## Editors: invites replace seven touchpoints

Today's per-editor admin work: create account → set a known password
separately → receive pubkey → receive Syncthing device ID → approve device →
hand over Postgres creds → verify. Proposed:

1. Admin clicks **Invite editor**, types a name and picks the projects to
   pre-tick. The dashboard creates the NAS account (via `NasBackend`), a
   one-time password, and a signed invite token; shows a link
   `https://<dashboard>/join/<token>` and a QR code.
2. The editor runs `onboard.exe` / the macOS wizard and pastes the link (or
   the wizard is launched *from* the link if the URL scheme is registered).
   The wizard fetches `/api/v1/site` for everything it used to be told by
   flags, redeems the token for the account + password + fleet token, uploads
   its SSH pubkey and Syncthing device ID **to the dashboard**, which installs
   the key (`NasBackend.create_or_update_editor`) and pre-approves the device
   (`syncthing_client` already knows how to accept a pending device — this
   makes it automatic when the device ID arrived over an authenticated
   invite).
3. Password: the token flow sets a real password the editor chooses on
   first sign-in (the dashboard's admin password-set path already exists),
   so "set a known password separately" disappears.
4. Resolve library details are shown in the wizard's last page and in the
   tray menu, copy-ready.

Net: admin does one click, editor pastes one link. `docs/EDITOR_SETUP.md`
shrinks to a page.

## What still cannot be hidden, and how to make it painless

- **Tailscale.** Non-technical owners will not run a tailnet on their own,
  but the pieces are all GUI: Package Center → Tailscale → "Log in"; admin
  console → DNS → "Enable HTTPS" (once); editors install Tailscale and accept
  the admin's invite email. The setup checklist detects the three states
  (package missing / logged out / HTTPS not enabled) and shows the click for
  each. There is deliberately **no** DDNS/QuickConnect/reverse-proxy option:
  the dashboard and the Syncthing GUI beside it never go on the public
  internet (decision 2026-08-17).
- **DaVinci Resolve Studio + external scripting.** Per seat, by hand
  (Preferences → System → General → External scripting: Local). The editor
  wizard already checks for Resolve; add a check for the scripting
  preference and a one-line fix instruction.
- **Prefer Proxies / Mapped Mount on macOS.** Existing wizard pages; keep.
- **Trust-level toggle** for the unsigned SPK — one screenshot until signed.

## Prerequisites this design creates for the code work

- A real container image (readiness item 12: `Dockerfile` for the dashboard,
  pushed to a registry with pinned tags) — the SPK cannot pip-install into a
  bind-mounted venv at first boot the way `run.sh` does today; the customer's
  NAS may not have outbound access to PyPI, and the install must be
  deterministic. **This is the single biggest enabler and should move up the
  order.**
- The compose template + `site.toml` (WP0, in progress) — the SPK renders the
  same template.
- `NasBackend.synology` (WP2) — used at runtime by invites; the SPK's postinst
  is the install-time twin (WP3's `synology.py`), and the two must share the
  DSM-API shape knowledge from the spikes.
- The `/api/v1/site` manifest (WP0.3, in progress) — the editor wizard reads
  it instead of flags.
- Invite tokens (new): a signed, single-use, expiring token minted by the
  dashboard; redemption endpoint returns account + fleet token; wizard changes
  in `onboarding/steps.py`.
- TLS by default (readiness item 6) — Serve gives it; the LAN-http path goes
  away for new installs.
- Signing the SPK and the client binaries (readiness item 4).

## Suggested sequencing

1. Finish port phase 1–2 (WP0–WP4) — that produces `synology.py` and the
   template the SPK reuses.
2. Dockerfile + registry image (readiness 12) — small, unblocks everything.
3. SPK: `INFO`, `preinst`, `install_uifile.sh`, `postinst`, `start-stop-status`,
   `postupgrade`, icons; build with `pkgscripts-ng`; test on the 192.168.0.11
   unit (Manual Install with trust level lowered).
4. Dashboard Setup page + Diagnostics + invites (dashboard + onboarding work).
5. Docs rewrite for the customer: a 2-page "Install on Synology" with
   screenshots, and a 1-page "Join as an editor".
6. Signing (Synology partner programme; Authenticode/Developer ID for the
   client wizard).

Rough size: SPK 1–2 weeks once `synology.py` exists; Setup page + invites 2
weeks; image + docs 1 week. It fits as a **WP8** after the port plan's WP7.
