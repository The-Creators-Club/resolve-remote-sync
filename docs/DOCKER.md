# DOCKER.md — the two ways the dashboard container gets its code and its deps

Written 2026-08-17 for `docs/COMMERCIAL_READINESS.md` item 12 ("ship a real
Dockerfile so the container is self-contained"). Section F of that document
recorded the state this replaces: *"No Dockerfile for the dashboard (pip-installs
into a bind-mounted venv at boot)"*.

There are now two modes. **Bind-mount mode is the default and every live site
uses it.** Nothing in this document changes a running deployment until an
operator deliberately switches.

| | bind-mount mode (default) | image mode (opt-in) |
|---|---|---|
| compose file | `dashboard/deploy/compose.yaml` | `dashboard/deploy/compose.image.yaml` |
| base image | stock `python:3.12.7-slim` | `ccsync-dashboard:<version>`, built here |
| code | bind-mounted `:ro` from the host | image layers |
| dependencies | `pip install` into a `/venv` volume on first boot | baked, `--require-hashes` |
| needs PyPI at boot | on the first boot, and after any requirements change | never for the base set; ONCE, on the first boot after a site turns `[features] youtube_unblock` on (see "What image mode does NOT bake in") |
| what a deploy ships | the code trees, over SFTP | an image, plus the code trees are unused |
| rollback | re-ship the previous tree | re-tag / re-pull the previous image |

Both run the **same entrypoint** (`/app/deploy/run.sh`), put the same four
trees on the same `PYTHONPATH` (`/app/src:/broll-app:/music-app:/ytdl-app`),
mount the same data volumes and expose the same healthcheck. That is
deliberate: one entrypoint means the two modes cannot drift, and every
`DEPLOY.md` in the repo stays true in both.

**Update, 2026-08-17 (`ZERO_TOUCH_PLAN.md` WP A):** `dashboard/deploy/Dockerfile`
has now actually been through `docker build` — on a hosted GitHub Actions
runner (`.github/workflows/image.yml`), because Docker Desktop is still not
installed on the base rig. That workflow is what turns "image mode" from a
build-it-yourself recipe (below, unchanged and still correct for a local
build) into a real, signed, published artefact — see "Published images (CI)"
further down, and `dashboard/deploy/compose.appliance.yaml` for the
third, fully-hands-off consumption shape this unlocks.

---

## Bind-mount mode (what runs today)

`server/install_dashboard_app.py` creates the host directories, SFTPs the
`dashboard/`, `broll/web`, `music/web` and `ytdl/web` trees into them, renders
`compose.yaml` from `site.toml`, and starts the stack. On boot, `run.sh`:

1. checks `/venv` is mounted (it is a *dedicated* volume, mode 700 — not a
   directory inside `/data`; a group-writable venv beside a group-writable
   `/data` was an editor→NAS-admin escalation, AUDIT C-2);
2. installs the dependency file **when its md5 changes** — preferring
   `requirements.lock` with `--require-hashes` and falling back to
   `requirements.txt` if no lock has been shipped;
3. execs uvicorn.

A pip failure after the venv has been populated once is a **warning, not a
crash**: a PyPI blip once crash-looped the whole fleet dashboard on every
restart, and the dashboard is the one service that tells everyone whether their
footage is syncing.

This mode is the right default while a deployment is being iterated on: a code
fix is an SFTP push and a restart, with no registry in the loop.

## Image mode (opt-in)

### Build

From **the repo root** — the image carries four trees from four directories,
and `.dockerignore` keeps the ~2 GB repo down to ~10 MB of context:

```bash
docker build -f dashboard/deploy/Dockerfile -t ccsync-dashboard:0.4.1 .
```

Two stages. The first creates `/venv` and runs
`pip install --require-hashes -r dashboard/deploy/requirements.lock`; the second
copies that venv plus the four code trees **and `dashboard/templates` +
`dashboard/static`**, writes `/venv/.runtime-id`, drops to a non-root user, and
sets `CMD ["/bin/sh", "/app/deploy/run.sh"]`.

> The two `COPY` lines for `templates/` and `static/` were **missing until
> 2026-08-18**. `ui.py` computes `TEMPLATES_DIR` as `parents[2]` of the
> package, i.e. `/app/templates`, which exists in bind-mount mode because the
> whole `dashboard/` tree is mounted at `/app` — so an image-mode container
> answered `/api/v1/health` perfectly and 500'd on every page. Found while
> building WP K's bundle, which has to carry the same two directories for the
> same reason. **Any image built before that fix is unusable for the UI.** The base image is pinned **by digest**
(`python:3.12.7-slim@sha256:60d9996b…`), not only by tag.

`--require-hashes` is the point of the exercise: it makes a compromised or
typo-squatted mirror a build failure instead of a shipped backdoor, and it
forbids any unpinned transitive dependency. Regenerate the lock with the recipe
in `docs/RELEASE.md` ("Refreshing the lockfiles"), never by hand.

### Get it onto the NAS

There is no registry in this product. Either push to one you control, or move
the image directly:

```bash
docker save ccsync-dashboard:0.4.1 | gzip > ccsync-dashboard-0.4.1.tar.gz
scp ccsync-dashboard-0.4.1.tar.gz <nas>:/tmp/
ssh <nas> 'gunzip -c /tmp/ccsync-dashboard-0.4.1.tar.gz | docker load'
```

On TrueNAS SCALE the app is installed through the middleware and the image must
exist on the host before the app is (re)deployed; on Synology `docker load`
then `docker compose up -d` is the whole story.

### Run it

`compose.image.yaml` is a template in the same grammar as `compose.yaml`
(`{{NAME}}` placeholders filled from `site.toml`). Render it:

```bash
python -c "import sys; sys.path.insert(0,'server'); \
  import install_dashboard_app as i, pathlib; \
  print(i.render_compose_yaml(template=pathlib.Path('dashboard/deploy/compose.image.yaml')))" \
  > /tmp/compose.yaml
```

Fill in the five `REPLACE_ME` values (`SYNCTHING_API_KEY`, `DASH_REPORT_TOKEN`,
`DASH_SESSION_SECRET`, `BROLL_INGEST_TOKEN`, and the NAS password in both
`TRUENAS_PW` and `DASH_NAS_PW`), set `CCSYNC_IMAGE` to the tag you loaded, and
`docker compose up -d`.

### What image mode does NOT bake in, and why

- **ffmpeg / ffprobe** stay a read-only mount at `/opt/ffmpeg`. The static build
  is GPLv3 and putting it inside a vendor image is *conveying* it, with all the
  source-offer obligations that implies (item 3, `docs/legal/THIRD_PARTY_NOTICES.md`).
- **The Claude Code CLI** at `/opt/claude` stays a mount because it must not be
  redistributed at all (item 1).
- **deno** at `/opt/deno` rides along with those two.
- **The YouTube "unblock" plugin (`bgutil-ytdlp-pot-provider`, GPLv3)** is
  NOT in the image layer either, for the exact same reason as ffmpeg above —
  and, unlike ffmpeg/deno/Claude, it is not even a *mount*: it is a pip
  package `run.sh` installs into `/venv` (the SAME venv the base
  `requirements.lock` populated, and the SAME mechanism — an md5-stamped,
  `--require-hashes` `pip install`), but only when `DASH_SITE_YOUTUBE_UNBLOCK=1`,
  which is only ever "1" on a site whose `site.toml` sets
  `[features] youtube_unblock` (2026-08-17, `docs/COMMERCIAL_READINESS.md`
  items 2/3 — see `dashboard/deploy/requirements-unblock.txt`'s own header
  and `docs/CI.md` for why the licence gate treats it as a separate,
  customer-opt-in target). Concretely: a fresh **image-mode** container never
  touches PyPI for the base app (`.image-baked` short-circuits that), but the
  first boot after a site flips `youtube_unblock` on DOES need PyPI reachable
  from the container — the same requirement bind-mount mode always had, now
  true for image mode too, but ONLY for this one optional feature. A future
  `ccsync-unblock` image layer that bakes this in as its own opt-in image is
  plausible follow-up work; it does not exist.
- **Every data volume.** `/data`, `/projects`, `/broll-data`, `/music-data`,
  `/music-encoder`, `/music-proxies`, `/music-share`, `/ytdl-data`,
  `/claude-home` are unchanged, byte for byte, from `compose.yaml`. The data is
  the half that cannot be rebuilt.

### Code root selection, and updating the code without the image

**Image mode only, added 2026-08-18 (`ZERO_TOUCH_PLAN.md` WP K).** The image
is the *runtime*: Python, `requirements.lock` installed with
`--require-hashes`, the sidecars. The *code* inside it can be replaced over
the air, from the same signed vendor feed the companion packages come from
(`docs/RELEASE_FEED.md` §2.1a), without touching the image at all.

Layout on the data volume:

```
/data/code/current.json          {version, previous, applied_at, record_sha}
/data/code/boot_attempts.json    {version, attempts}   the watchdog's counter
/data/code/update_state.json     what an in-flight update is doing
/data/code/<version>/            src/ templates/ static/ deploy/
                                 broll-app/ music-app/ ytdl-app/
                                 manifest.json  record.json (the SIGNED record)
/data/backups/<ts>-before-<v>/   the databases, copied with sqlite's backup API
```

On every boot `run.sh` runs **`/app/deploy/select_code_root.py`** — the
IMAGE's copy, with the IMAGE's python, importing the IMAGE's verifier and
reading the IMAGE's baked `/venv/.runtime-id`. The tree in `/data/code` is
the thing being judged and gets no vote in whether it is used. It prints the
four PYTHONPATH roots and nothing else; every doubt prints the image's own
roots and the reason on stderr:

| state | what boots |
|---|---|
| no `current.json`, or it names no version | the image (silently: this is the normal state) |
| `<version>/manifest.json` missing, unreadable, or not a dashboard bundle | the image |
| `<version>/record.json` missing | the image (an unsigned tree is never booted) |
| the record's signature does not verify against `DASH_RELEASE_PUBKEYS` | the image |
| the record's or the manifest's `runtime_id` is not `/venv/.runtime-id` | the image |
| the version is not NEWER than the image's own | the image (a bundle can never roll the image backwards) |
| one of the four roots is missing | the image |
| `DASH_RELEASE_PUBKEYS` unset, or no `/venv/.runtime-id` | the image |
| all of the above pass | `/data/code/<version>` |

**The boot watchdog.** `select_code_root.py` increments `boot_attempts.json`
before it hands a volume tree over; the app clears it once it has been up and
healthy for 45 s (`dashboard_update.start_boot_watchdog`, armed from the
lifespan). So the counter only ever survives a boot that did not work, and on
the **third** boot with two failures already recorded the script rewrites
`current.json` to the previous tree (or the image), with `reverted_reason`,
and boots that. Nobody has to be watching — the thing that failed to boot is
the thing an admin would have used to fix it. The failed tree's files are left
on disk deliberately: they are the evidence.

**Exit 75.** `run.sh` in image mode runs uvicorn as a child inside a loop
instead of `exec`ing it. Exit code 75 (`EX_TEMPFAIL`) means "I staged new
code, re-select the root and exec me again"; every other exit code exits the
container exactly as before, so `docker stop` and a crash-loop behave the way
every runbook says. The shell keeps PID 1 and forwards SIGTERM to the child
itself. **Bind-mount mode is untouched** — no `/venv/.image-baked`, no
selection, the same single `exec` it has always done, and the Dashboard
section of the Packages page says the deployment updates from the base rig.

An apply, in order (`dashboard_update.apply`): download with the record's
sha256 verified → extract with absolute paths, `..`, symlinks, hardlinks and
devices all refused → check the manifest against the signed record and every
file against the manifest → **stage-verify in a subprocess** on the new
PYTHONPATH (`import ccsync_dashboard.app`, then run each migration against a
*copy* of `dashboard.db`/`broll.db`/`music.db`) → back the live databases up
to `/data/backups/<ts>/` with sqlite's backup API (never a file copy: they are
open in WAL mode) → optional NAS snapshot → rename staging to final → write
`current.json` → exit 75. Everything that can fail happens before the live
tree is touched, so every failure leaves the running dashboard exactly as it
was.

### uid and gid

The image defaults to `3000:3000` so a bare `docker run` is still unprivileged,
but compose overrides it with the site's own `user: "<APP_UID>:<APP_GID>"` —
DSM assigns uids ≥ 1026 and will not let you pick 3000, so it must be read off
the live account, never assumed.

An unprivileged container **cannot setuid**, so there is no entrypoint that
reads `APP_UID` and switches to it. What `run.sh` does instead is *shout*: set
`APP_UID`/`APP_GID` in the environment (compose.image.yaml does) and it warns
loudly when the uid it actually got disagrees. That matters because the symptom
otherwise is silent and delayed — files written into `/projects` and
`/music-share` land owned by the wrong uid, and the editors browsing those
shares over SMB find files they cannot open.

---

## Migrating between the modes

Both directions are a compose-file swap. **No data moves and nothing is
deleted.**

Bind-mount → image:

1. Build and load the image (above).
2. `docker compose down` (or stop the app in the TrueNAS UI).
3. Bring the stack up with the rendered `compose.image.yaml`.
4. Check `/api/v1/health` returns `{"ok": true}` and that `/broll`, `/music`
   and `/ytdl` are present on the dashboard's nav.

The host's `app/`, `venv/`, `broll-web/`, `music-web/` and `ytdl-web/`
directories are simply unused afterwards. **Leave them there.** They are the
rollback: swapping back to `compose.yaml` uses them exactly as before, and
`/venv` still holds a populated venv, so the first boot back does not even need
PyPI.

Image → bind-mount: re-run `server/install_dashboard_app.py` to refresh the
code trees (they may be older than the image), then start with `compose.yaml`.

## What to check after either switch

```
docker compose ps                        # dashboard healthy, bgutil up
docker compose logs dashboard | head -40 # run.sh's own lines
curl -s localhost:8480/api/v1/health     # {"ok": true, ...}
```

`run.sh` announces which dependency file it chose and whether it skipped pip
because the venv came from the image. If it says it is *installing* in image
mode, the `/venv/.image-baked` marker is missing and something rebuilt the venv
volume over the layer — check that `compose.image.yaml` has no `/venv` mount.

In image mode it also prints one `run.sh: PYTHONPATH=...` line per boot, and
`select_code_root: ...` lines saying which code tree it chose and why. If the
Dashboard section of the Packages page offers nothing but the feed lists a
version, the reason is in those lines. `docker exec <c> cat /venv/.runtime-id`
against the record's `runtime_id` is the one comparison that decides it.

---

## Published images (CI) and the appliance stack

`.github/workflows/image.yml` builds **both** vendor images — the dashboard
(`dashboard/deploy/Dockerfile`) and the new `ccsync-sftp` sidecar
(`dashboard/deploy/sftp/Dockerfile`, `ZERO_TOUCH_PLAN.md` 3.1 — the chrooted
`internal-sftp` service that replaces NAS-native SFTP accounts entirely; see
`dashboard/deploy/sftp/README.md`) — on every push to `main`, on
`workflow_dispatch`, and on a `v*` tag. It pushes both to GHCR
(`ghcr.io/<owner-lowercased>/ccsync[-sftp]`, or the repo variables
`CCSYNC_IMAGE`/`CCSYNC_SFTP_IMAGE` if set — the vendor org that publishes
this may not be this GitHub repo's owner forever), signs each one **keylessly**
with `cosign` (sigstore Fulcio/Rekor — no key to manage or leak, unlike the
release-signing key `docs/RELEASE.md` describes for the companion), and
attaches an SBOM. The tags:

| trigger | dashboard | sftp |
|---|---|---|
| push to `main` | `:<short-sha>`, `:edge` | `:<short-sha>`, `:edge` |
| tag `v*` | `:<short-sha>`, `:<VERSION>`, `:1` | `:<short-sha>`, `:<VERSION>`, `:1` |

`:1` is a **deliberately fixed** floating tag, not "whatever VERSION's
leading digit is" (`VERSION` is `0.5.0` today — a `:0` tag would say the
wrong thing). It is the one long-lived tag
`dashboard/deploy/compose.appliance.yaml` pins, so that a customer's NAS
platform updating it (`docker compose pull && up -d`, or, in Phase 3, one
click in the platform's own app UI) is the entire update story — see
`ZERO_TOUCH_PLAN.md` 3.4. Every 0.x/1.x release moves `:1` until a
deliberately breaking cut earns a `:2`.

Verify a signature:

```bash
cosign verify --certificate-identity-regexp '.*' \
  --certificate-oidc-issuer https://token.actions.githubusercontent.com \
  ghcr.io/<owner>/ccsync@sha256:<digest>
```

**`dashboard/deploy/compose.appliance.yaml` is the third consumption shape**,
built on top of these published images, and it is the one this repo now
recommends for a *new* site — see `docs/APPLIANCE_INSTALL.md`. Unlike
`compose.image.yaml` it needs no rendering step and no `REPLACE_ME` values:
paste it, set two variables (`CCSYNC_TREE`, `CCSYNC_DATA`), and
`docker compose up -d`. It also brings up the `syncthing`, `sftp` and
`tailscale` sidecars `ZERO_TOUCH_PLAN.md` section 3.1 describes — none of
which `compose.yaml`/`compose.image.yaml` run by default. What it does
**not** yet do: run the first-run setup wizard (`ZERO_TOUCH_PLAN.md` WP D,
not built) — until that lands, `DASH_NAS_KIND` and everything the wizard
would ask stays unset, and the two secrets Syncthing/sftp need
(`STGUIAPIKEY`, `CCSYNC_INTERNAL_TOKEN`) are generated by a small `secrets-init`
service in that compose file rather than the dashboard's own first-boot code.

## Not done here

- **`ZERO_TOUCH_PLAN.md` WP B–J.** This page and `image.yml` are WP A only:
  the Tailscale sidecar reading LocalAPI to derive `dashboard_url` (WP B),
  the SetupEngine and wizard that would make `compose.appliance.yaml`
  actually self-configuring (WP D), the release feed (WP E) — none of that
  is here. `docs/APPLIANCE_INSTALL.md` marks each gap explicitly.
- **Spikes S1/S2/S5 ran on a real DS423+** (`docs/spikes/zero-touch-spikes-2026-08-17.md`,
  2026-08-17) and `compose.appliance.yaml` was updated against their
  findings: `tailscale` runs bare `tailscaled` (an `entrypoint:` override,
  no containerboot — the stock image's own `tailscale up` gives up after 60s
  with nobody having clicked the login link yet and crash-loops, minting a
  new AuthURL every cycle), pinned to the exact digest the spike resolved;
  `sftp` carries the `cap_add`/`security_opt` pair spike S3 proved makes
  per-project bind views possible (not yet wired to anything — that is WP
  C); the `ccsync-sftp` image itself picked up `openssh-sftp-server` (a
  package Alpine splits out), a dedicated `sftpkeys` account instead of
  `nobody`, `-p '*'` on every account `useradd` creates (a default-`!`
  shadow field is treated as LOCKED by sshd even for pubkey auth — measured
  directly), and `-u 002` on `ForceCommand internal-sftp`. **What the spike
  explicitly did NOT measure, because it needs a real tailnet login it was
  not authorised to create**: Serve actually terminating TLS on `:443` and
  proxying to the dashboard; an inbound connection to the node's own tailnet
  IP reaching a `network_mode: service:tailscale` sibling; userspace vs
  kernel SFTP/sync throughput through the node. Those three are WP B's
  first-day work, with a throwaway tailnet, before `compose.appliance.yaml`
  reaches a real customer.
- **`ccsync-ffmpeg` does not exist yet.** `compose.appliance.yaml` does not
  mount `/opt/ffmpeg` at all — music ingest transcoding is simply unwired on
  the appliance path for now (`ZERO_TOUCH_PLAN.md` 3.1's "pragmatic answer" —
  a separate GPLv3-with-source-offer image — is not built). Same for
  `/opt/deno` and the `youtube_unblock` feature's `bgutil` sidecar: neither
  appears in `compose.appliance.yaml`, matching the vendor build's own
  features-off default (`COMMERCIAL_READINESS.md` item 3), not a broken
  mount.
- **`music-data`/`ytdl-data` are not mounted on the appliance path either.**
  `compose.appliance.yaml` wires up the dashboard's own DB, the project tree,
  and the two Assets shares (b-roll archive, music library) — enough for the
  dashboard, lane A/B/C and the b-roll UI to boot healthy. `/music` and
  `/ytdl` staying unmounted is a scope boundary of WP A, not a bug; wiring
  them in is a small, separate change once WP D decides where under
  `${CCSYNC_DATA}` they should live.
- **The GPU indexers are a different image** — `tools/Dockerfile.indexer-gpu`
  and `tools/compose.indexer-gpu.yaml` (item 14). Nothing here builds them, and
  `music/indexer/requirements.lock` is deliberately the CPU / default-PyPI wheel
  set: the CUDA-index build belongs to that image, and CI does not install it.
- **`server/install_dashboard_app.py` does not deploy image mode.** Its
  `--image`/`DASH_IMAGE` switch changes the *tag* only; the mounts and the
  compose body it POSTs to the TrueNAS middleware are bind-mount mode's. Image
  mode is a rendered-compose deployment today. Wiring the install script to
  render `compose.image.yaml` on a flag is a small, separate change.
- **`broll/web/Dockerfile`** predates all of this and builds the *standalone*
  b-roll app on its own port. It is not part of the dashboard image and is not
  used by any deployment here.
