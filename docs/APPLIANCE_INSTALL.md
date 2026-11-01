# APPLIANCE_INSTALL.md — the paste-and-click install (DRAFT, WP A only)

`ZERO_TOUCH_PLAN.md` section 3.6, written down as customer-facing steps.
**This is a draft that is honest about what is not built yet** — it
describes the install as `dashboard/deploy/compose.appliance.yaml` and
`.github/workflows/image.yml` (WP A) actually make it work TODAY, and marks
every place a later work package (`ZERO_TOUCH_PLAN.md` section 4) changes
the story. **WP D — the `/setup` wizard — has since landed** (2026-08-17, its
last placeholder steps 2026-08-18), so steps 2 and 3 below describe something
that exists; they were rewritten on 2026-08-21 (CR-67). **WP B has still not landed**, but its
worst edge is gone: the wizard's own "Connect to your tailnet" task asks the
bundled node for a sign-in link and puts it on the page (UX-21, 2026-09-04),
so step 4 no longer sends anybody to `docker compose logs` to read a URL out
of a log. What WP B still owes is Serve: nothing publishes this dashboard on
the tailnet automatically. **The DRAFT label stays until somebody who is not
the author has run this end to end** — the sections marked **NOT YET TRUE**
below are not cosmetic.

## The bar this is judged against

> A customer admin installs Tailscale and the CC Sync container on their
> Synology or TrueNAS. That is the whole install. Everything after that is a
> step-by-step wizard in the browser.
> — `ZERO_TOUCH_PLAN.md` section 1

## Steps, as of WP A

### 1. Install Tailscale (on the NAS, or plan to use the bundled node)

The stack runs its **own** Tailscale node as a sidecar container
(`ZERO_TOUCH_PLAN.md` 3.1) — the customer does not need Tailscale installed
on the NAS host itself for the appliance to be reachable. What the customer
does need, before or after pasting the compose file:

- A Tailscale account and tailnet (free tier is enough for one appliance
  node plus editor machines).
- Editors' own machines already get Tailscale from the existing installer
  flow — unchanged by this plan.

### 2. Paste the compose file

Copy `dashboard/deploy/compose.appliance.yaml` in full.

**Synology (Container Manager):** Project → Create → paste the compose text
→ set the two environment variables below → Build.

**TrueNAS SCALE (Apps):** Discover → Custom App → *Install via YAML* → paste
the compose text → fill in the same two variables → Install.

Two variables are required (the compose file refuses to start with either
one unset, naming which):

```
CCSYNC_TREE=/volume1/Projects        # the shared folder for Projects/,
                                      # Assets/B-roll Archive/, Assets/Music/
CCSYNC_DATA=/volume1/docker/ccsync   # where the stack keeps its OWN state
```

**Synology (and any box whose users are not numbered 3000/3001): a third and
fourth variable, set by hand.** The containers run as
`${APP_UID:-3000}:${APP_GID:-3001}`. DSM numbers its local accounts from 1026,
so uid 3000 does not exist there and the stack would write your shared folder
as a user nobody owns (GL-06, CR-364, 2026-10-07). Nothing writes these two
back for you: a container cannot edit the project that runs it. Once, before
the first Build:

1. DSM Control Panel > User & Group > Create: an account named `ccsync` (no
   other privileges needed).
2. Control Panel > Shared Folder > the shared folder behind `CCSYNC_TREE` >
   Edit > Permissions: give `ccsync` Read/Write. Do the same for the folder
   behind `CCSYNC_DATA`.
3. Over SSH on the NAS, run `id ccsync`. It prints something like
   `uid=1032(ccsync) gid=100(users)`.
4. In Container Manager's Environment settings for the project, add
   `APP_UID=1032` and `APP_GID=100` (your numbers), then Build.

If you skip this, the wizard's Storage check fails with a message naming the
account the container runs as, the account that owns the folder, and this
step. On TrueNAS SCALE the defaults are right only if your service account
really is uid 3000 and your editors group gid 3001; the script-driven TrueNAS
deploy (`server/install_dashboard_app.py`) now reads the live ids and refuses
a mismatch.

**You no longer create `Projects/`, `Assets/B-roll Archive/` and `Assets/Music/`
under `CCSYNC_TREE` by hand** (GL-05 / CR-363, 2026-10-07). Those three paths
are **bind-mount sources**, resolved by Docker before the container starts, and
a missing one is invented by the daemon as a **root-owned** directory the
unprivileged container then cannot write. The one-shot `secrets-init` service
is root on purpose: it now makes any of the three that is missing, gives each
the ownership of `APP_UID`/`APP_GID`, and does the same for the sync engine's
config folder (`${CCSYNC_DATA}/syncthing-config`), which is the other thing
Docker used to create as root and which sent Syncthing into a restart loop on
a fresh install. A folder that already exists is the customer's own data and is
never touched. If you ever see "could not write/read/delete a probe file" on
the Storage check, the folder's owner is not the account the containers run as:
see the APP_UID/APP_GID step above.

What the step *does* do, once those three exist: write-probe the tree and
delete the probe again, report the free space, and create this site's
`Assets/...` leaves (`Assets/Luts`, `Assets/Stills`, ...) from the manifest's
`shared_assets` list. Where the tree root is not visible to the container at
all it says so and stops, rather than creating those folders under the
container's own rootfs (`dash-admin-1`, 2026-08-21).

### 3. Open the dashboard

`http://127.0.0.1:8480` **from the NAS itself** (its own browser, or an SSH
tunnel: `ssh -L 8480:127.0.0.1:8480 <nas>` then open `http://localhost:8480` on
your laptop). That is the only way in until step 4 is done: the compose file
publishes one loopback-bound port (`127.0.0.1:8480:8480`) and nothing on your
LAN. There is no Container Manager "port-forward UI" for this. **After step 4
the dashboard is on your tailnet** at `https://<node-name>.<tailnet>.ts.net`
and that is the address you and your editors use.

**There is a first-run wizard at `/setup`** (`ZERO_TOUCH_PLAN.md` 3.5, WP D
— `setup_engine.py` + `setup_routes.py`; the last five steps stopped being
placeholders on 2026-08-18). It is a resumable task list, in order:

| | Step | What it does |
|---|---|---|
| 1 | Welcome, EULA | Records acceptance of the version in the EULA's own marker |
| 2 | Create your admin account | The one step that closes the anonymous window below |
| 3 | Your studio | The site manifest: name, tree, URLs (writes `site_settings`, which beats every `DASH_SITE_*` value the compose file carries) |
| 4 | Storage check | Write-probes the tree, reports free space, lays down the `Assets/...` leaves |
| 5 | Secrets | Confirms the five credentials exist; backfills any this boot is still missing (the update signing key is the vendor's public key, baked in, not one of these) |
| 6 | Sync engine | Reaches the Syncthing already in the stack |
| 7 | Done | |

...then five **optional** ones — Connect your tailnet, Connect to your NAS,
Protect your data, Editors, Software for editors — each a real check with a
real answer, not a placeholder.

Every state is persisted in `setup_tasks` (`db.py` migration v18) keyed by
task id, so a container restart mid-wizard — routine on an appliance — resumes
where it left off instead of replaying "Welcome". Every check answers from
what this container can already see: its databases, its settings, the tree
mount, a unix socket, and at most one **3-second** call to a NAS or Syncthing
it already holds a credential for. Nothing dials out speculatively, so no step
can hang the page on a deployment that is not on a tailnet yet, and a check
that fails reports one line naming the next action rather than a traceback.

**Who may open it.** Steps 1 and 2 are reachable with **no session** — but
only in the narrow window before any local account exists, and only under
`DASH_AUTH_METHOD=local`. On `smb` and `oidc` deployments that window is
treated as closed (a NAS or an IdP can already authenticate an admin, so an
anonymous window would be a second way in) and every `/api/v1/setup/*` route
requires an admin session. `require_setup_access` fails **closed** wherever
the answer is unknown. The window shuts for good the instant the first
account exists, re-checked under `BEGIN IMMEDIATE`.

Still worth doing first: confirm the stack is healthy (`docker compose ps`, or
`curl http://<nas-ip>:8480/api/v1/health` from the NAS itself).

### 4. The wizard does the rest

Work down the checklist on `/setup`. Everything from here is a page in the
browser; the shell commands that used to be steps are kept below each one as
the fallback for when something cannot start.

**Connect to your tailnet.** The bundled `tailscale` service runs bare
`tailscaled` and attempts no login of its own — the stock image's `tailscale
up` was measured to give up after 60 seconds and crash-loop otherwise
(`docs/spikes/zero-touch-spikes-2026-08-17.md` S1). Press
**[ SIGN IN OR PUBLISH ]** on that task: the dashboard asks the node over its
own LocalAPI socket, starts the interactive login and shows you the
`login.tailscale.com` link. Open it, sign in, then press the same button again:
once the node is signed in it **publishes the dashboard on your tailnet through
Tailscale Serve** and records the `https://<node-name>.<tailnet>.ts.net` address
as the site's dashboard URL (only if you have not set one). The task turns green
only when the dashboard is actually reachable that way (GL-04 / CR-363,
2026-10-07; it used to turn green the moment the node was signed in). The
button is also what puts it back if it is ever lost, and the server does that
by itself every minute or so.

Two things Tailscale itself needs, once, in its admin console: **HTTPS
certificates must be enabled for your tailnet** (if Serve is not turned on the
task says so and quotes the link Tailscale gives), and **disable key expiry**
for this node (Machines, this node, Disable key expiry). A default key lasts
180 days, and on that day the server drops off the tailnet and every editor
goes quiet at once. The task shows the expiry date, and the server warns by
email 14 days ahead.

*If the bundled node cannot start* — no link after a second press, or the task
says there is no node here — do it from a shell on the NAS instead:

```
docker compose exec tailscale tailscale --socket=/var/run/tailscale/tailscaled.sock up
docker compose logs tailscale          # the same URL, as the "AuthURL is ..." line
```

*If Serve cannot be configured from the button* (the message names the reason),
publish by hand from a shell on the NAS, then press CHECK:

```
docker compose exec tailscale tailscale --socket=/var/run/tailscale/tailscaled.sock serve --bg http://dashboard:8480
```

**Fill-in forms instead of "redeploy".** A step that needs a value from you
(the admin account name on a NAS-login site, the sync engine address, the NAS
address and key, the update signing key, the vendor feed address) shows a form
on its own row. Saving stores the value in `/data/secrets/appliance_config.json`
(private to the container, never shown back) and restarts the server for a few
seconds; the page reloads itself. A value the container's own environment
already sets wins over a stored one. The Secrets step has a **[ RESTART SERVER ]**
button for the same reason. You never edit the compose file for these.

**The sync engine's admin page has a password.** The bundled Syncthing's own
web page (port 8384) is reachable by anyone on your tailnet, so the dashboard
sets a login on it by itself on its first cycle (user `ccsync-admin`; the
random password is in `/data/secrets/syncthing_gui_password`). You never need
it: the dashboard talks to the engine with its API key. Set
`DASH_SYNCTHING_GUI_SECURE=0` only if you must keep the old behaviour.

**The daily "still here" message.** The alerts step offers one short email a
day (ticked by default). It is the only message whose absence is the news: if
it stops arriving, the server itself is down.

**Editors, software, protection.** The last three optional tasks, described
in step 5 below.

### 5. Editors, software, protection

**The wizard CHECKS all three; it does not yet DO any of them.** The
`editors`, `software` and `snapshots` steps stopped being placeholders on
2026-08-18: each reports where this deployment actually stands (who the
dashboard has positive evidence of as an editor; which companion build is
current for Windows **and** macOS, so a studio with no Mac sees "macos: none
published" rather than a green tick that becomes a lie the day someone joins
on one; whether anything is scheduled or exported to protect `/data`) and
names the next action. Only `software` has a button at all, and it is
labelled CHECK NOW.

**NOT YET TRUE** is the doing of two things (`ZERO_TOUCH_PLAN.md` 3.5 steps
6-9, WP F/G): there is no invite flow, and nothing schedules a snapshot on this
deployment shape. Until those land, the appliance stack is a working
`dashboard` + `syncthing` + `sftp` + `tailscale` project that can be configured
through the browser but still needs the NAS's own tools for snapshots.

**Releases are NOT on that list any more** (CR-362 / GL-02, 2026-10-07): the
image carries the vendor's public key and feed address, so an admin publishes
the vendor's companion builds from Packages > From the vendor (policy
`manual`: nothing installs until someone clicks), and a recall the vendor
issues is honoured. A customer needs no base rig and no key of their own.

## Secure defaults on the appliance path (CR-368 follow-up, 2026-10-07)

* **Per-project access is NOT in force on the appliance yet.** The SFTP sidecar
  runs every editor as one account in one `editors` group, so every editor who
  can sign in can read every project (`dashboard/deploy/sftp/README.md`,
  "Per-project bind views are proven, not built"). Per-project groups (ticks
  and admin grants) apply to a TrueNAS NAS reached over SMB, not to this
  sidecar. Treat every editor you invite as trusted with the whole tree.
* **NAS certificate.** Your NAS presents a self-signed certificate. The
  dashboard records its SHA-256 fingerprint the first time it connects, writes
  it to the log, and refuses a different certificate afterwards. To pin it
  yourself, enter `sha256:` and the 64-digit fingerprint in the "Connect to
  your NAS" step; there is no setting that turns verification off. If you
  replace the NAS certificate on purpose, remove that NAS's entry from
  `<data>/secrets/nas_cert_pins.json` and restart the dashboard.
* **Admin account.** The dashboard admin must not be the NAS's own admin
  account, and a TrueNAS NAS is connected with an API key, never its password;
  the wizard refuses both.
* **Editor lanes.** The sftp service publishes its public host key into
  `sftp-hostkey-pub` in your data folder; the dashboard serves it as
  `sftp_hostkey` and both editor installers pin rclone to it. Editors who
  installed before this need to re-run the installer once.

## Updating the container image (digest-pinned)

`compose.appliance.yaml` is pinned by digest (`ghcr.io/.../ccsync:<version>@sha256:...`,
written by `tools/release_customers.py`), so the NAS's Update or Build button
re-pulls the SAME image and changes nothing. Most dashboard updates need no
image change: the bundle is applied from Settings > Packages. When a build on
offer does need a new image, the dashboard says so (Packages, the fleet
banner, the alert mail) and prints the exact replacement lines from the vendor's
signed channel: `ghcr.io/the-creators-club/ccsync:<version>@sha256:...` and, when
the channel carries it, the matching `ccsync-sftp` line. Open the project's
compose file, put those references on the `image:` of the `secrets-init` and
`dashboard` services (the dashboard image) and `sftp` (the sftp image), save, and
redeploy. A security fix in the base image reaches a site the same way, through
a new release that re-pins.

## What IS true today (WP A's actual scope)

- `docker compose up -d` brings up all five services (`secrets-init` runs
  once and exits 0; `dashboard`, `syncthing`, `sftp`, `tailscale` stay up).
- The dashboard image and the `ccsync-sftp` sidecar image are both real,
  built and signed by `.github/workflows/image.yml`, pulled from GHCR —
  nothing here needs a local `docker build` (`docs/DOCKER.md`, "Published
  images (CI)").
- `syncthing` and `sftp` share the `tailscale` container's network
  namespace, so once the tailnet node is signed in, lane C (`:22000`) and
  lanes A/B (`:22`, chrooted `internal-sftp`) are reachable on the node's
  own tailnet IP with **zero** host ports published for either.
- No `REPLACE_ME` anywhere in the compose file, and no secret is typed by
  an operator: `secrets-init` generates Syncthing's `STGUIAPIKEY` and the
  sftp sidecar's `CCSYNC_INTERNAL_TOKEN` into
  `${CCSYNC_DATA}/data/secrets/` on the very first `up`.
- **Sign-in is accounts this dashboard keeps** (`DASH_AUTH_METHOD=local`,
  CR-362 / GL-00, 2026-10-07). Before that line was in the compose file the
  dashboard expected NAS logins against an empty NAS address, and a new
  customer reached a login nothing could pass. Wizard step 2 creates the first
  admin, and the dashboard refuses to boot in `smb` mode with no NAS address.
- **The dashboard knows where its own Syncthing is**
  (`SYNCTHING_GUI_URL=http://tailscale:8384`, GL-01): the Syncthing container
  shares the tailnet node's network namespace, so the dashboard reaches it by
  that service name. Wizard step 6 can pass.
- **The vendor's signing key and feed address are baked into the image**
  (`DASH_VENDOR_DEFAULTS=1`, GL-02, `vendor_defaults.py`). You type neither,
  and you do not make a key of your own: this dashboard only accepts builds the
  vendor signed, which is how it installs editors and receives updates and
  recalls. Setting `DASH_RELEASE_FEED_URL` or `DASH_RELEASE_PUBKEYS` yourself
  overrides the baked value (only do that when the vendor tells you to). The
  Protection page reads "the vendor holds the update signing key" for this
  key: there is nothing for you to back up. `docs/INSTALL.md` step 6 is the
  same rule for the non-appliance install.
- `syncthing`/`sftp` wait for `tailscale` to have STARTED before they do
  (`depends_on: tailscale: condition: service_started`), which covers a
  deliberate `docker compose up`/`restart`. It does **not** cover
  `tailscaled` crashing and Docker restarting just that one container on
  its own — the netns those two services attached to goes with it, and they
  need a manual restart too until a later work package makes that
  automatic (`docs/spikes/zero-touch-spikes-2026-08-17.md` S5; see
  `compose.appliance.yaml`'s own comment on this).

## Troubleshooting (today's reality, not the wizard's)

```
docker compose ps                          # all five services; secrets-init "Exited (0)" is normal
docker compose logs secrets-init           # confirms the two .env files were generated
docker compose logs tailscale              # the sign-in link (step 4's fallback), and Serve/LocalAPI state
docker compose logs dashboard | head -40   # run.sh's own boot lines
curl -s http://127.0.0.1:8480/api/v1/health # {"ok": true, ...} from ON the NAS
```

If `dashboard`/`syncthing`/`sftp` refuse to start citing a missing
`${CCSYNC_TREE}/Projects` (or the two `Assets/…` paths), read
`docker compose logs secrets-init`: it creates them on the first `up` (GL-05)
and says when it could not. If `syncthing` restart-loops, the same log line
about its config folder is the cause (the folder must be owned by `APP_UID`).

## See also

- `ZERO_TOUCH_PLAN.md` — the plan this document is one page of, and the
  authoritative list of what each remaining work package changes here.
- `docs/DOCKER.md` — where the images come from, what CI publishes, and the
  three consumption shapes (bind-mount, image, appliance) side by side.
- `dashboard/deploy/sftp/README.md` — the sftp sidecar's chroot layout and
  uid model, referenced from step 2 and the troubleshooting section above.
- `docs/INSTALL.md` / `docs/SERVER.md` / `docs/SERVER-SYNOLOGY.md` —
  the base-rig-and-SSH install this document supersedes, retired page by
  page as each work package here lands (`ZERO_TOUCH_PLAN.md`'s own opening
  paragraph).
