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

Two variables, both required (the compose file refuses to start with either
one unset, naming which):

```
CCSYNC_TREE=/volume1/Projects        # the shared folder for Projects/,
                                      # Assets/B-roll Archive/, Assets/Music/
CCSYNC_DATA=/volume1/docker/ccsync   # where the stack keeps its OWN state
```

**Create `Projects/`, `Assets/B-roll Archive/` and `Assets/Music/` under
`CCSYNC_TREE` by hand, before the first `docker compose up`.** The wizard's
"Storage check" step exists now (`setup_engine.py`'s `storage` task) but it
cannot do this one: those three paths are **bind-mount sources**, resolved by
Docker before the container starts, and a missing one is invented by the
daemon as a **root-owned** directory the unprivileged container (uid 3000)
then cannot write. The symptom is a stack that comes up healthy and a Storage
check that says "could not write/read/delete a probe file".

What the step *does* do, once those three exist: write-probe the tree and
delete the probe again, report the free space, and create this site's
`Assets/...` leaves (`Assets/Luts`, `Assets/Stills`, ...) from the manifest's
`shared_assets` list. Where the tree root is not visible to the container at
all it says so and stops, rather than creating those folders under the
container's own rootfs (`dash-admin-1`, 2026-08-21).

### 3. Open the dashboard

`http://<nas-ip>:8480` — reachable on the NAS's own LAN address only, via
the one loopback-bound port the compose file publishes
(`127.0.0.1:8480:8480`) reached through Container Manager's own port-forward
UI or an SSH tunnel, **until step 4 below is done**.

**There is a first-run wizard at `/setup`** (`ZERO_TOUCH_PLAN.md` 3.5, WP D
— `setup_engine.py` + `setup_routes.py`; the last five steps stopped being
placeholders on 2026-08-18). It is a resumable task list, in order:

| | Step | What it does |
|---|---|---|
| 1 | Welcome, EULA | Records acceptance of the version in the EULA's own marker |
| 2 | Create your admin account | The one step that closes the anonymous window below |
| 3 | Your studio | The site manifest: name, tree, URLs (writes `site_settings`, which beats every `DASH_SITE_*` value the compose file carries) |
| 4 | Storage check | Write-probes the tree, reports free space, lays down the `Assets/...` leaves |
| 5 | Secrets | Confirms the five credentials exist; backfills any this boot is still missing |
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
**[ GET A SIGN-IN LINK ]** on that task: the dashboard asks the node over its
own LocalAPI socket, starts the interactive login and shows you the
`login.tailscale.com` link. Open it, sign in, then press CHECK on the task and
it reports the node's tailnet name (UX-21, 2026-09-04).

*If the bundled node cannot start* — no link after a second press, or the task
says there is no node here — do it from a shell on the NAS instead:

```
docker compose exec tailscale tailscale --socket=/var/run/tailscale/tailscaled.sock up
docker compose logs tailscale          # the same URL, as the "AuthURL is ..." line
```

**Still NOT YET TRUE: Serve.** `POST /localapi/v0/serve-config` refuses until
the node is signed in (`netMap is nil`), and nothing calls it afterwards, so
even a signed-in node leaves this dashboard on its loopback bind
(`127.0.0.1:8480`) rather than published on the tailnet. That is WP B's
remaining half.

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

**NOT YET TRUE** is the doing (`ZERO_TOUCH_PLAN.md` 3.5 steps 6–9, WP E/F/G):
there is no invite flow, nothing publishes a companion build to this fleet
from the appliance, and nothing schedules a snapshot on this deployment
shape. Until those land, the appliance stack is a working `dashboard` +
`syncthing` + `sftp` + `tailscale` project that can now be configured through
the browser but still needs the base rig for releases and the NAS's own tools
for snapshots.

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
`${CCSYNC_TREE}/Projects` (or the two `Assets/…` paths), see step 2 above —
the wizard that would create them (WP D) does not exist yet, so they must
already exist on the NAS before the first `up`.

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
