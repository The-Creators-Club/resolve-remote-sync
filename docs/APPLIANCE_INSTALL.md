# APPLIANCE_INSTALL.md — the paste-and-click install (DRAFT, WP A only)

`ZERO_TOUCH_PLAN.md` section 3.6, written down as customer-facing steps.
**This is a draft that is honest about what is not built yet** — it
describes the install as `dashboard/deploy/compose.appliance.yaml` and
`.github/workflows/image.yml` (WP A) actually make it work TODAY, and marks
every place a later work package (`ZERO_TOUCH_PLAN.md` section 4) changes
the story. Do not hand this to a real customer until at least WP B–D have
landed — the sections marked **NOT YET TRUE** below are not cosmetic.

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

If `CCSYNC_TREE` does not have `Projects/`, `Assets/B-roll Archive/` and
`Assets/Music/` subfolders yet, **NOT YET TRUE**: the wizard's "Storage
check" step (`ZERO_TOUCH_PLAN.md` 3.5 step 5, WP D) is what would create
them automatically. Until WP D exists, create those three subfolders by hand
before the first `docker compose up`, or the `dashboard`, `syncthing` and
`sftp` services will start against missing mount targets.

### 3. Open the dashboard

`http://<nas-ip>:8480` — reachable on the NAS's own LAN address only, via
the one loopback-bound port the compose file publishes
(`127.0.0.1:8480:8480`) reached through Container Manager's own port-forward
UI or an SSH tunnel, **until step 4 below is done**.

**NOT YET TRUE:** there is no first-run wizard at this URL today. What is
actually there is whatever the dashboard shows an unconfigured install —
the SetupEngine wizard (`ZERO_TOUCH_PLAN.md` 3.5, WP D) does not exist yet.
Treat this step, for now, as "confirm the container is healthy"
(`docker compose ps`, or `curl http://<nas-ip>:8480/api/v1/health`
from the NAS itself) rather than "click through setup".

### 4. Connect to your tailnet

**NOT YET TRUE.** The plan (`ZERO_TOUCH_PLAN.md` 3.5 step 4, WP B) is: the
wizard shows the sign-in link `tailscaled` prints, you click it, and the
dashboard then *derives* its own public URL
(`https://ccsync-<studio>.<tailnet>.ts.net`) from the node's own LocalAPI —
no URL to type anywhere. Today, reaching that link requires an operator to
read the `tailscale` service's container logs by hand
(`docker compose logs tailscale`) and complete the login manually; nothing
in the dashboard surfaces it yet.

### 5. Editors, software, protection

**NOT YET TRUE**, all three (`ZERO_TOUCH_PLAN.md` 3.5 steps 6–9, WP D/E/F/G):
inviting an editor, publishing a companion build to this fleet, and
snapshot/backup protection all still need work packages this repo has not
built. Until then this appliance stack is a working `dashboard` +
`syncthing` + `sftp` + `tailscale` compose project with no admin account,
no invite flow and no feed-published companion — useful for verifying the
stack itself comes up, not yet a product a customer can run their fleet on.

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

## Troubleshooting (today's reality, not the wizard's)

```
docker compose ps                          # all five services; secrets-init "Exited (0)" is normal
docker compose logs secrets-init           # confirms the two .env files were generated
docker compose logs tailscale              # the sign-in link, and Serve/LocalAPI state
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
