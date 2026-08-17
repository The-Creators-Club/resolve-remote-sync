# Zero-touch install — the customer installs Tailscale and one container, and nothing else

Written 2026-08-17, after `COMMERCIAL_READINESS.md` items 1–15 landed
(`b2d348a`). This is the plan for the next layer: **making CC Sync an
appliance.** It supersedes the install half of `SYNOLOGY_EASY_INSTALL.md`
(whose setup-checklist and invite designs it keeps) and it retires, over
time, most of `INSTALL.md`, `SERVER.md`, `SERVER-SYNOLOGY.md` and `RELEASE.md`
as customer-facing documents.

## 1. The bar

Three sentences, and every design choice below is judged against them.

1. **A customer admin installs Tailscale and the CC Sync container on their
   Synology or TrueNAS. That is the whole install.** Everything after that is
   a step-by-step wizard in the browser, like the one editors already get.
2. **Only we build anything.** No PyInstaller, no `docker build`, no git
   checkout, no Python, no signing key, no "base rig" on the customer side —
   ever, including for updates.
3. **Day 2 is clicks, not runbooks.** Invite an editor, publish an update,
   read a diagnostic, restore a file: all in the dashboard.

## 2. Where we are (the inventory, condensed)

Measured against `docs/INSTALL.md`, `SERVER*.md`, `RELEASE.md`, `TENANCY.md`
and every `server/*.py` on 2026-08-17:

- **41 manual admin steps**, on **2–3 machines** (NAS, a Windows "base rig"
  with the git repo + Python + PyInstaller, and a Mac if any editor is on
  macOS). Roughly 14 one-time, 5 per release, 8 per editor, 3 per project,
  5 recurring. Loading secrets recurs *per shell*.
- The customer is simultaneously **tenant, release engineer and signing
  authority**: `INSTALL.md` step 6 has them generate the Ed25519 release key,
  bake it into the companion *source*, build both clients themselves and PUT
  them into their own dashboard with an admin cookie.
- The upgrade channel is **push-only** — no vendor feed exists anywhere in
  the code, and there is **no dashboard self-update** of any kind: a
  dashboard update is `install_dashboard_app.py` SFTP-ing source trees over
  SSH and `docker restart`.
- The container is deployed **from** `site.toml` and can never edit it: every
  site value is compose env, so any change is `--recreate` from the base rig.
- There is **no local admin account**: "admin" is a NAS account whose password
  is verified by an SMB session on :445, because TrueNAS's middleware refuses
  auth for non-admin users. So the dashboard cannot exist without a NAS
  account and a known password *first*.
- The container **already does** a lot at runtime through APIs (create
  editor NAS accounts + keys, approve Syncthing devices, provision folders,
  create project trees), but everything privileged is still root-over-SSH
  from the base rig: `chown -R`/`chmod 2770`, sshd `Match Group editors`
  block, ZFS snapshots, `docker exec`, host directories, the compose
  lifecycle itself.
- The Dockerfile exists but has never been built; "there is no registry in
  this product"; the two GitHub release workflows build but deliberately
  do not publish.

## 3. The shape of the answer

### 3.1 One image, four services, zero host operations

The product becomes a compose stack of **vendor-built images with data
volumes only**. The NAS is storage plus a container runtime; nothing on the
NAS host is ever configured by us over SSH.

```
ccsync (compose project)
├── dashboard   ghcr.io/ccsync/ccsync:<ver>        FastAPI + broll/music/ytdl mounts
│               (the existing image, plus the SetupEngine and the release-feed client)
├── syncthing   syncthing/syncthing:1.30.0          the existing "bundled-syncthing" profile, always on
├── sftp        ghcr.io/ccsync/ccsync-sftp:<ver>   OpenSSH, internal-sftp only, tree mounted at /tree
└── tailscale   tailscale/tailscale:<pinned>        the stack's OWN tailnet node; Serve https:443 → dashboard
    ├─ syncthing and sftp run in its network namespace (network_mode: service:tailscale)
    └─ so :22000 and :22 are reachable on the node's tailnet IP with no host ports at all
```

Volumes: `<apps>/data` (dashboard DB, packages, secrets, syncthing config,
tailscale state) and `<tree>` (the project tree). **That is the entire
customer-supplied configuration: two paths.**

Why each piece is where it is:

- **Tailscale as a sidecar, not on the host.** Today the runbook has the
  admin install the Tailscale package on the NAS *and* run `tailscale serve`
  over SSH. A sidecar node (`TS_STATE_DIR` on the data volume,
  `TS_SERVE_CONFIG` for HTTPS→8480, `TS_SOCKET` shared with the dashboard so
  it can read login state over LocalAPI) means the customer configures
  nothing: the wizard shows the "sign this node into your tailnet" link that
  `tailscaled` prints, and once the node is up the dashboard *learns* its
  own URL (`https://ccsync-<studio>.<tailnet>.ts.net`) from LocalAPI. That
  kills the biggest chicken-and-egg in `site.toml` — `dashboard_url`,
  `sftp_host` and the Syncthing device id all become **self-derived**, and
  the loopback allow-list, the cookie `Secure` flag and `TS` TLS come for
  free. Userspace networking (the image default) needs no `/dev/net/tun` or
  `NET_ADMIN`, so it works in Container Manager and TrueNAS Apps as-is;
  kernel mode stays an opt-in for throughput. Where the customer already
  runs Tailscale on the NAS host, the two nodes coexist. **The customer's
  Tailscale work shrinks to: create a tailnet, install Tailscale on editor
  machines, click the sign-in link the wizard shows.**
- **Syncthing bundled, always.** The TrueNAS catalog app path (install the
  app, fish the API key out of its config, then secure its GUI by hand) goes
  away; the compose profile that already exists for Synology becomes the
  only shape. We generate `STGUIAPIKEY`; the GUI is not published at all
  (the dashboard is its admin surface).
- **SFTP as a sidecar is the decision that removes the most.** Lane A/B use
  rclone-over-SFTP to the NAS host's sshd today, which is why the product
  needs per-editor NAS accounts, home directories with StrictModes-correct
  modes, an `editors` group, `chown -R`/setgid on the tree, ACLs on DSM, an
  sshd `Match Group` block appended to a middleware-owned config file, and
  the "home directory trap" — all root work over SSH. An sshd *inside* the
  stack, mounting the tree, chrooted to it, `ForceCommand internal-sftp`,
  keys served by the dashboard (`AuthorizedKeysCommand` against an
  internal endpoint), needs none of that: the container is root *inside*
  itself and owns the tree mount, so tree ownership is its own business.
  Editors' files land owned by the service uid, exactly as Syncthing's and
  the dashboard's already do. Editors never touch the NAS's own SMB or SSH.
  Editor identity moves with it (§3.3).
- **The dashboard image is what already exists** (`dashboard/deploy/
  Dockerfile`, never built) plus the SetupEngine (§3.2), the feed client
  (§3.4) and a small root-in-container helper for tree ownership repair.
  ffmpeg stays a mount only if we cannot resolve the GPLv3 conveyance
  question (item 3); the pragmatic answer is a *separate* `ccsync-ffmpeg`
  image built from source with the offer attached, pulled by compose like
  any other layer, so the customer never fetches a binary by hand.

### 3.2 The SetupEngine: `server/*.py` moves into the container

Everything the eleven server scripts do that a customer needs is either
(a) already possible through the NAS's own HTTP API, (b) possible from a
root-inside process that owns the tree mount, or (c) not needed once SFTP
and Syncthing are in the stack. The engine is a set of idempotent, resumable
**tasks** with a status the wizard renders:

| Today (base rig, root SSH) | In the appliance | Needs NAS admin credential? |
|---|---|---|
| `install_dashboard_app.py` (host dirs, SFTP source trees, compose, `--recreate`) | gone — the image is the deploy; compose is the platform's own | no |
| `install_syncthing_app.py` + read API key + `secure_syncthing_gui.py` | bundled service; key generated at first boot; GUI unpublished | no |
| `setup_tree.py` (`mkdir` template, marker, `chown -R`/`chmod 2770`, DSM ACEs) | root-in-container helper on the `/tree` mount; per-project ACL model simplified (§5) | no |
| `setup_editor_account.py` (NAS user, key, home modes, sshd `Match` block, `nologin`) | dashboard-local identity + `AuthorizedKeysCommand`; **no NAS account** | no |
| `accept_device.py`, `setup_syncthing_folder.py` | already in the collector; the marker read that needed sudo reads `/tree` directly | no |
| `setup_snapshots.py` (ZFS `pool.snapshottask`, DSM Snapshot Replication) | task "Protect your data": TrueNAS via `pool.snapshottask.create`; DSM via its API where present, else the exact three clicks with a **Verify** button | **yes, optional** — offered, never required |
| `create_api_key.py` | the wizard's "Connect to your NAS" step: admin credential entered **once**, used to mint a scoped key (TrueNAS) or a service account (DSM), then discarded; stored 0600 on `/data` | yes, optional |
| `publish_db.py`, `check_health.py`, `write_marker.py`, backup/restore | dashboard-side: index upload page (stage-verify-swap inside the container), Diagnostics page, project identity repair page, `/data` backup export + snapshot-browse restore | no |
| `tailscale serve` by hand | sidecar + `TS_SERVE_CONFIG` | no |
| `openssl rand` × 5, `.env` 0600 root, `load_secrets.ps1` | generated at first boot into `/data/secrets/` (service uid, 0600); **the customer never sees a secret** | no |

Two consequences worth stating: the "connect to your NAS" step becomes
**optional** (it buys share creation, SMB users for admin browsing, and
snapshot scheduling — none of which lane A/B/C or the dashboard need), and
`site.toml` **stops existing** as a customer artefact. Its keys become
either derived (`dashboard_url`, `sftp_host`, device id, uid/gid, chunk
size, shell type), wizard answers (`org_name`, drive letter, tree name,
features), or defaults. The manifest at `GET /api/v1/site` stays exactly as
it is — clients need not change — but it is now served from the DB, editable
in the dashboard, no `--recreate`.

### 3.3 Identity moves into the dashboard

The SMB-probe login exists only because editors *had* to be NAS accounts.
With SFTP in the stack they don't, so the dashboard becomes the identity
provider:

- **Local accounts** with argon2 hashes in SQLite (the sessions, throttle,
  CSRF, per-editor tokens and admin scoping already exist and stay).
- **The first admin is created in the wizard** — break-glass, no NAS
  dependency, no `DASH_ADMIN_USERS` env.
- **OIDC stays** as the optional SSO path; `DASH_AUTH_METHOD=smb` is kept for
  the migration window (§6) and then removed.
- **SFTP auth**: pubkey only. The sftp sidecar's `AuthorizedKeysCommand`
  calls the dashboard's internal `GET /internal/sftp/keys/<user>` (on the
  compose network, token-guarded); revoking an editor is one row. Password
  auth on sshd is off, permanently.
- **Invites replace seven touchpoints** (unchanged from
  `SYNOLOGY_EASY_INSTALL.md` §"Editors"): admin clicks *Invite*, sends a
  link; the wizard redeems it, uploads its pubkey and device id, the
  dashboard installs the key and pre-approves the device; the editor picks
  a password on first sign-in.

### 3.4 The release feed: we publish once, every dashboard pulls

Today a build reaches a fleet because someone with the private key and an
admin cookie PUTs bytes into *that* dashboard. For N customers that is N
pushes and N passwords. Instead:

- A **vendor-hosted, signed feed** — `https://releases.ccsync.app/v1/channel.json`
  (or a public `ccsync-releases` GitHub repository's release assets; either
  is a static file host, no server code) listing, per platform and kind, the
  package records **already in the signed shape `sign_release.py` produces**
  (`kind, platform, version, filename, sha256, size_bytes, min_version,
  published_at, signed_binary`, signature, `pubkey_id`) plus a download URL,
  and the current dashboard image tag. The channel file itself carries a
  detached signature by the same release key.
- **The dashboard pulls it** (daily, and on the admin's "Check now"),
  verifies against the pubkeys it was *shipped with* (the same list baked
  into the companion), and shows *"Companion 0.9.0 available for your
  fleet — Publish"*. Publish = download artefact, verify sha and record
  signature, insert the row, optionally make current. **The existing PUT
  route stays for us** (and for air-gapped customers who upload a bundle);
  the feed is just a second, unattended writer that reuses
  `release_trust.verify_record` unchanged. Policy switch: manual / auto-stage
  / auto-current.
- **`min_version` floors and "different, not newer" rollback** keep working
  exactly as now — this changes who *delivers* records, not what companions
  verify.
- **Dashboard self-update** cannot be done by the container without a Docker
  socket, and we will not mount one (it is root on the NAS). So the
  dashboard *reports* — badge + the exact platform click ("Container Manager
  → Project ccsync → Build/Update"; "Apps → ccsync → Update") — and the
  compose file pins a **floating minor tag** (`ccsync:1`) so that click is
  the whole update. Package-native lifecycles (SPK, TrueNAS catalog) make it
  one click with an "Update available" badge in the NAS's own UI; that is
  Phase 3.
- **CI builds, we sign.** `release-windows.yml` / `release-macos.yml`
  already build both clients on hosted runners with `--require-hashes`; add
  the image build (`docker build`, cosign keyless, SBOM) and a
  `tools/publish_feed.py` step **run from the base rig** that downloads the
  CI artefacts, signs the records with the offline key exactly as
  `sign_release.py` does today, and uploads artefacts + `channel.json`. The
  private key never enters CI. The macOS build no longer needs anyone's
  MacBook — that dependency is gone.
- **What `ship.cmd` becomes**: `tools/release.cmd` — tag, wait for CI,
  sign, publish feed. Vendor-only. Nothing in it touches a customer NAS.

### 3.5 The wizard (first-run, in the browser)

First admin visit to `http://<nas>:8480` (or the ts URL once it exists) lands
on **Setup** and stays there until green. Each step is a SetupEngine task
with *Check* / *Do it* / *Skip*, resumable across restarts:

1. **Welcome, EULA** — versioned marker, same file as the clients ship.
2. **Create your admin account** — local, argon2, no NAS involved.
3. **Your studio** — name, short name, tree name (default = share name),
   drive letter (default `P:`, must be a letter), template folders (defaults
   shown, editable). Writes the site manifest.
4. **Connect to your tailnet** — shows the login URL from LocalAPI; polls;
   on success displays the dashboard URL editors will use, sets cookie
   `Secure`, allow-lists the origin. If Serve is gated on the tailnet, shows
   the one admin-console click ("Enable HTTPS") and retries.
5. **Storage check** — writes/reads/deletes a probe file in `/tree` as the
   service uid; reports free space; creates `Projects/`, `Assets/…` from the
   template; writes markers. Explains, in one line, that files will be owned
   by the CC Sync service user and are browsable over SMB with the NAS's own
   share permissions.
6. **Connect to your NAS (optional)** — kind auto-detected (TrueNAS API on
   :443 vs DSM on :5001 at the Docker gateway); admin credential once →
   scoped key / service account; enables **Snapshots** (schedule + verify)
   and **SMB browsing users**. Skippable with a clear "you can do these two
   things yourself" note.
7. **Protect your data** — snapshot schedule (via 6) or the three-click
   guide with Verify; `/data` backup export.
8. **Editors** — Invite flow; the first invite is offered right here.
9. **Software for editors** — feed check; publish current companion +
   onboard for Windows and macOS with one click; policy choice.
10. **Done** — Diagnostics button, "send a test file through all three
    lanes" once an editor is in.

Every step's *Do it* is a task the admin can re-run later from **Settings**;
the wizard is a linear view over the same tasks, not separate code.

### 3.6 The customer's install, end to end

**Synology:** Container Manager → Project → Create → paste the 30-line
compose (from `https://ccsync.app/install`, which asks *only* "which shared
folder is your project tree?" and emits the file) → Build. Open
`http://<nas>:8480`. Wizard. Phase 3: an SPK that does the paste for them
and puts an icon in DSM.

**TrueNAS SCALE:** Apps → Discover → Custom App → *Install via YAML* → paste
the same file → Install. Same wizard. Phase 3: a catalog entry.

**Editors:** unchanged in shape and better in detail — download the wizard
from *their* dashboard's `[ INSTALLER ]`, paste the invite link, done. Mac
editors get a build from the same feed as Windows editors, on the same day.

## 4. Work packages

Sized as an estimate for one engineer with agents; dependencies are the
arrows. Nothing here changes what the current fleet runs until §6.

| WP | What | Depends on | Size |
|---|---|---|---|
| **A. Image + registry** | First real `docker build` of `dashboard/deploy/Dockerfile`; fix any wheel without a manylinux build; push `ghcr.io/ccsync/ccsync`; cosign keyless + SBOM; `compose.image.yaml` becomes *the* compose (rename `compose.yaml` → `compose.dev.yaml` for bind-mount dev only); `ccsync-sftp` and `ccsync-ffmpeg` images; CI job on tag. | — | 1 wk |
| **B. Tailscale sidecar** | Service in compose; `TS_STATE_DIR`/`TS_SERVE_CONFIG`/`TS_SOCKET` on `/data`; dashboard reads LocalAPI (`Self.DNSName`, `BackendState`, `AuthURL`); derives `dashboard_url`, sets `DASH_COOKIE_SECURE`, trusted-proxy for `X-Forwarded-Proto` from Serve; spike S1 first. | A | 1 wk |
| **C. SFTP sidecar + local identity** | sshd image (chroot `/tree`, `internal-sftp`, `AuthorizedKeysCommand`); dashboard `users` table with argon2, `/internal/sftp/keys`; wizard admin creation; keep `smb` login behind a flag for migration; per-editor tokens unchanged; manifest `sftp_host` = ts node, `sftp_shell_type=none`, chunk size default 255Ki (the DSM 64Ki rule was about DSM's sshd — ours is OpenSSH, so measure once, spike S2). **Status (2026-08-17): identity half DONE** — `dashboard/src/ccsync_dashboard/local_users.py` (`users`/`user_ssh_keys`, migration v17, stdlib `hashlib.scrypt` not argon2 — no new dependency, no lockfile/license-gate churn), `DASH_AUTH_METHOD=local` wired through `auth.verify_credentials`/`auth.is_admin`, `setup_api.py`'s first-admin bootstrap (`POST /api/v1/setup/admin`), Admin ▸ Users' local branch (create/password/disable/keys, `docs/API.md` §5), and `internal_sftp.py`'s two bearer-token routes for the sidecar's `AuthorizedKeysCommand` (`docs/API.md` §5b). `smb` stays the default; nothing here is live until a fleet flips the env var (§6). **Still owed (agent A / the sshd image itself):** the `ccsync-sftp` image, chroot/`internal-sftp`/`AuthorizedKeysCommand` wiring against these two routes, and spike S2's chunk-size measurement. | A, B | 2 wk |
| **D. SetupEngine + wizard** | Task framework (id, check, run, status row, resumable); the ten steps in §3.5; site manifest **in the DB** (`site_settings` table) served by `/api/v1/site`, editable in Settings; secrets generated at first boot into `/data/secrets`; NAS connect (TrueNAS scoped key, DSM service account — both backends exist in `nas/`, add `pool.snapshottask` / share / SMB-user calls); tree ownership helper. | A, B, C | 3 wk |
| **E. Release feed** | `channel.json` schema + signer (`tools/publish_feed.py`), static hosting, dashboard feed client + Publish UI + policy, `min_version` handling, air-gapped bundle upload; `tools/release.cmd` replaces `ship.cmd` for the vendor path; retire the customer-side key generation from `INSTALL.md`; `release_key.py bake` becomes a vendor-only step. | A | 1.5 wk |
| **F. Invites** | Signed single-use token, `/join/<token>`, wizard changes in `onboarding/steps.py` (redeem → account + fleet token + pubkey/device upload), auto-approve device on authenticated invite. From `SYNOLOGY_EASY_INSTALL.md`. | C, D | 1.5 wk |
| **G. Diagnostics, backup, index publish** | Redacted bundle (versions, compose status via LocalAPI/health, lane health, last 500 lines); `/data` export/import; snapshot browse-and-restore for TrueNAS (API) and DSM (`#snapshot` / `@sharesnap` paths on `/tree`); broll/music index upload page doing what `publish_db.py` does, inside the container. | D | 1.5 wk |
| **H. Migration of this studio** | §6. | B–F | 1 wk + soak |
| **I. Native packages** | SPK (`INFO`, `preinst`, `install_uifile.sh` asking one question, `postinst` = compose up, `postupgrade` = pull, DSM icon); TrueNAS catalog entry. Trust-level toggle until signed. | A–E shipped | 2 wk |
| **J. Docs** | `INSTALL.md` → one page per platform with screenshots; `EDITOR_SETUP.md` → one page; `RELEASE.md` → vendor-only; delete `SERVER*.md` runbook steps that no longer exist; `ARCHITECTURE.md` §12 platform envelope updated. | as each WP lands | ongoing |

Critical path: **A → B → C → D**, ~7 weeks to a stack a stranger can install
from a compose paste; E and F in parallel from week 2. Everything in
`server/` except `common.py`'s pure helpers becomes vendor/dev tooling or is
deleted once H is through.

## 5. Decisions taken here, and what they cost

- **SFTP inside the stack, single service uid.** Cost: per-editor file
  ownership on the NAS disappears (everything is `ccsync:ccsync`), and
  `TENANCY.md`'s `project_acl = "per-project"` (POSIX groups + setgid) no
  longer has a mechanism. Replacement: **per-project authorisation in the
  dashboard** — the sftp sidecar exposes each editor a chroot with bind
  views of only their ticked projects (one `bind` mount per project inside
  the sidecar, driven by the same selection rows lane C enforcement uses),
  or, simpler and first, `internal-sftp` with a per-user chroot to `/tree`
  and the dashboard's selection as the only guard (today's `shared` posture,
  which every live site runs). Per-project isolation ships as a follow-up
  once bind views are spiked (S3). What we gain: no NAS accounts, no home
  dirs, no `chown -R`, no sshd config edits, no ACL API differences between
  platforms, no "home directory trap", and DSM/TrueNAS parity by
  construction.
- **Tailscale sidecar rather than host Tailscale.** Cost: a second node per
  NAS if the customer already runs one; userspace throughput lower than
  kernel mode (spike S1 measures; kernel mode is one `devices:` +
  `cap_add:` line for customers who want it). Gain: the entire access story
  is ours, and the URL is never typed by anyone.
- **No Docker socket, no self-recreate.** Cost: dashboard image updates are
  a click in the NAS UI, surfaced by us but not performed by us. Gain: the
  stack cannot become root on the NAS if the dashboard is compromised.
- **The customer's NAS admin credential is optional and one-shot.** Cost:
  without it, snapshots and SMB users are the customer's own three clicks.
  Gain: the product's minimum trust from the NAS is "a container with two
  volumes" — which is what a security review of an appliance expects.
- **The release key stays offline on our base rig; CI never holds it.**
  Cost: publishing needs a human at the base rig (one command). Gain: a
  compromised CI cannot sign a build the fleet would accept.
- **`site.toml` is retired as an interface**, kept only as an *export
  format* (Settings → Export) so a NAS migration is import-and-go.

## 6. Migrating this studio (and any fleet already on the old shape)

The current TrueNAS site runs NAS-native SFTP accounts, catalog Syncthing
and host Tailscale + a LAN URL. Migration is additive, then a switch:

1. Bring the new stack up **beside** the old (different apps root, same
   tree mount, its own ts node). Run the wizard; import `site.toml`.
2. Editors keep working against the old sshd. Publish a companion whose
   manifest consumer rewrites the rclone remote from `sftp_host`
   (`rclone_stanza_rewrite` already exists for this) and whose Syncthing
   device list gets the new node's id from `nas_syncthing_id` — both are
   manifest-driven today.
3. Move Syncthing's config volume (device id) into the stack so no editor
   re-accepts anything; approve nothing new.
4. Flip the manifest (`sftp_host`, `dashboard_url`) → editors' next report
   rewrites their remotes; watch lane A/B/C on the fleet grid.
5. Retire the old app; the old NAS editor accounts stay locked as SMB-only
   users for those who browse.

Rollback at every step is "flip the manifest back"; nothing is deleted
until step 5.

## 7. Spikes before committing code

- **S1 (day 1):** tailscale sidecar in userspace mode on the DS423+ and on
  TrueNAS: does an inbound connection to the node's tailnet IP:22000 reach a
  container sharing its netns? Serve `https:443 → 127.0.0.1:8480` from
  `TS_SERVE_CONFIG`? Login URL readable via `TS_SOCKET` LocalAPI? Measure
  SFTP throughput userspace vs kernel.
- **S2 (day 2):** OpenSSH sidecar as root with `/tree` bind-mounted:
  chroot + `internal-sftp` + `AuthorizedKeysCommand`, rclone lane A/B
  against it from an editor machine; ownership of written files; the
  255Ki/64Ki chunk-size question re-measured (it was DSM's sshd, not ours).
- **S3 (day 3):** per-project bind views inside the sidecar (mount
  propagation from a compose service, needs `SYS_ADMIN` inside the sidecar
  only) — decides whether per-project SFTP isolation ships in C or later.
- **S4:** `docker build` of the existing Dockerfile on a Linux runner; every
  wheel in `dashboard/deploy/requirements.lock` has a manylinux build?
  (`--require-hashes` forbids the fallback.)
- **S5:** Container Manager and TrueNAS "Install via YAML" both accept
  `network_mode: service:tailscale` and volume-mounted sockets (both run
  compose underneath since DSM 7.2 / SCALE 24.10 — confirm on the two boxes
  we have).

## 8. What this does NOT change

- Editors' experience beyond invites (the tray, lanes, popup, loopback API,
  upgrade verification) — untouched; the companion already trusts only
  baked keys and its own origin, which is exactly the property the feed
  relies on.
- The GPU indexers stay a vendor/pro-services thing on a GPU box (item 14);
  the appliance only *hosts* the indexes it is given.
- The legal layer (item 5), certificates (item 4) and YouTube posture
  (item 2) — orthogonal; the wizard's EULA step and feature switches are the
  places they plug in.
- One container per customer (`TENANCY.md` §1). The appliance is single
  tenant by design; multi-org is not on this plan.

## 9. Related

- `COMMERCIAL_READINESS.md` — items 1–15 (done) are the floor this stands on;
  this plan is item 16.
- `SYNOLOGY_EASY_INSTALL.md` — the setup checklist, invites and SPK design
  this reuses; its install-time `postinst` root work is superseded by §3.1.
- `DOCKER.md` — the image this plan finally builds.
- `ARCHITECTURE.md` §7 (upgrade channel), §5 (auth), §6 (site manifest) — the
  three sections this plan rewrites.
