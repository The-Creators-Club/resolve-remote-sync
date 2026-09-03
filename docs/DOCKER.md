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
| chosen by | nothing (the default) | `[stack] mode = "image"`, or `--mode image` |
| compose file | `dashboard/deploy/compose.yaml` | `dashboard/deploy/compose.image.yaml` |
| base image | stock `python:3.12.7-slim` | `ccsync-dashboard:<version>`, built here |
| code | bind-mounted `:ro` from the host | image layers |
| dependencies | `pip install` into a `/venv` volume on first boot | baked, `--require-hashes` |
| needs PyPI at boot | on the first boot, and after any requirements change | never for the base set; ONCE, on the first boot after a site turns `[features] youtube_unblock` on (see "What image mode does NOT bake in") |
| what a deploy ships | the code trees, over SFTP | an image, plus the code trees are unused |
| rollback | re-ship the previous tree | re-pin the previous image/digest — or `--mode bind`, which is the whole mode's rollback |

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
  redistributed at all (item 1). Since 2026-08-18 there is a second, better
  place it can come from and it is still not the image: the Settings page's
  SET UP wizard downloads the publisher's own build into the **data volume**
  (`<data>/tools/claude-code/…`, `docs/CONFIG.md` §2.5a) at an admin's click.
  That deliberately survives an image update and is never baked into one: an
  image layer containing somebody's proprietary 313 MB binary is the thing
  item 1 forbids, whoever pressed the button.
- **deno** at `/opt/deno` rides along with those two.
- **The YouTube "unblock" plugin (`bgutil-ytdlp-pot-provider`, GPLv3)** is
  NOT in the image layer either, for the exact same reason as ffmpeg above —
  and, unlike ffmpeg/deno/Claude, it is not even a *mount*: it is a pip
  package `run.sh` pip-installs (md5-stamped, `--require-hashes`), but only
  when `DASH_SITE_YOUTUBE_UNBLOCK=1`,
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
  plausible follow-up work; it does not exist. **Where it lands differs by
  mode** (CR-84, 2026-08-26): bind-mount mode installs it into `/venv`, the
  same venv the base lock populated; image mode CANNOT (that `/venv` is an
  `a+rX` image layer and the container is uid 3000 — it failed with
  `[Errno 13] Permission denied` on every boot of the v0.7.11 image), so there
  it goes to `/data/unblock-site` with `--no-deps --target`, stamped at
  `/data/.requirements-unblock-hash`, and `run.sh` appends that directory to
  PYTHONPATH — which is all yt-dlp needs, since it discovers a plugin by
  walking `sys.path` for a `yt_dlp_plugins` package. It therefore survives an
  image update, like `<data>/tools/` above.
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

**All three are bounded** (REL-5, 2026-08-28). `/data/backups` keeps the
newest 3 per label, 8 in total and 8 GiB, whichever bites first; `/data/code`
keeps the running tree, the one `current.json` can roll back to, and one more;
`/data/packages` is pruned on every publish to the current build plus the two
newest (`?prune=0` opts out). A publish is refused with **507** below the same
free-space floor an apply already refused at, and `/api/v1/health` and the
Packages page both carry a `/data` free-space gauge. A full `/data` is a
SQLite write failure on the database that tells the whole fleet whether its
footage is syncing, so nothing on this path is allowed to grow without limit.

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
before it hands a volume tree over; the app clears it once it has been up for
45 s **and has proved it can serve** — one loopback
`GET http://127.0.0.1:$DASH_PORT/api/v1/health` that must answer 200 with this
build's own `version`, retried for up to 45 s more
(`dashboard_update.start_boot_watchdog`, armed from the lifespan). Before
2026-08-28 the watchdog only proved the process had not exited, so a tree that
imported cleanly (exactly what stage-verify tested), bound the port and then
500'd every request was marked permanently healthy and never reverted (REL-6). So the counter only ever survives a boot that did not work, and on
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

`current.json` also records the live `user_version` of each database and the
schema version the applied tree knows (asked of the new code during
stage-verify, written into its `manifest.json`). That is what makes a
**rollback** honest: going back to a tree that predates the schema the live
database is now on is **refused** unless the admin either names a backup to
restore alongside it (the checkbox on the Packages page) or acknowledges the
consequence explicitly. Additive columns survive a backwards code swap; a
rename or a NOT NULL one does not, and before 2026-08-28 nothing checked and
the UI said nothing (REL-10).

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

## The Timeline Cards mounts (`/cards`)

New 2026-08-30 (`docs/TIMELINE-CARDS-INTO-CCSYNC.md` phase 3). The dashboard
now hosts the Timeline Cards page in-process at `/cards`, on the same terms as
`/broll` and `/music` — and it is the only mount that needs **shares this
container never had**: the vault it writes into, and the footage share it
reads audio out of. All of it is optional; a site that configures none of it
gets `/cards: {"status": "disabled"}` on `GET /api/v1/health` and no other
change at all.

| what | where it comes from | mount |
|---|---|---|
| the code (another repo's checkout) | `CARDS_SRC` / `[timeline_cards] src` → `<host-root>/cards-web` | `/cards-app:ro` |
| the vault | `[timeline_cards] vault_host` | `/vault:rw` |
| the footage share | `[timeline_cards] media_host` | `/media:ro` |

Three things about that table are load-bearing:

* **`/cards-app` is a mount in IMAGE MODE TOO** — the only code mount that is.
  The image carries `/app`, `/broll-app`, `/music-app` and `/ytdl-app` as
  layers; it cannot carry a tree from a different repository. It is also
  **not on `PYTHONPATH`**: `select_code_root.py` re-derives those four roots on
  every image-mode boot and knows nothing about this one, so
  `ccsync_dashboard.cards` appends `DASH_CARDS_SRC` to `sys.path` itself.
* **`/media` is useless without `media_map`, and vice versa.** The agent names
  each clip as WINDOWS sees it (`P:\Projects\…`); the map is how the container
  finds the same bytes. Set one alone and the symptom is a lane with no audio
  on every clip that has no rendered WAV — which looks like a broken clip.
* **`/vault` is `rw` on purpose.** `Script Docs/` is where the draft, the saved
  plans, the notes and the translation caches are written. A `:ro` mount there
  loses every plan at the moment of saving.

### The chown, and why it is needed BEFORE the first deploy

The dashboard runs as **3000:3001** (`broll:editors`). The vault —
`tank/web` on this NAS — is **Alex's own SMB share**, `3003:3000`, because
files the page writes should look like his own writes (Timeline Cards'
`docs/TRUENAS-APP-PLAN.md` §0.1, which is why its standalone container ran as
3003:3000 in the first place). Two different uids, one share, and an
unprivileged container cannot setuid or setgid itself.

So the deploy adds the vault's **group** to the container
(`group_add: ["3000"]`, from `[timeline_cards] vault_gid`), and the host has to
make that group able to write. **On the NAS, once, as root:**

```bash
# 1. Everything under the vault belongs to the group the container joins.
#    (Ownership of the FILES is left alone -- they stay Alex's.)
chgrp -R 3000 /mnt/tank/web

# 2. The group may write, and NEW directories keep the group (setgid) --
#    without the setgid bit, a folder the page creates would belong to the
#    container's primary group and Alex would be locked out of his own vault
#    over SMB the next day.
chmod -R g+w /mnt/tank/web
find /mnt/tank/web -type d -exec chmod g+s {} +
```

On a dataset with NFSv4 ACLs (TrueNAS SCALE's default), `aclmode` can ignore
`chmod` outright — check with `getfacl` afterwards, and if the mode bits did
not take, grant it as an ACL instead:

```bash
setfacl -R -m group:3000:modify_set:fd:allow /mnt/tank/web
getfacl /mnt/tank/web | head            # ...and READ what it says
```

**Neither half works alone**: `group_add` without the group's write bit is a
page whose every save is refused with `EACCES`, and the chmod without
`group_add` changes nothing at all. The failure is quiet on both sides — the
page shows "the plan did not save" and the container log shows a permission
error nobody is watching — which is why this is a step in the runbook rather
than a note.

### ffmpeg

Already there, and nothing new is needed: `/opt/ffmpeg` is on `PATH`
(`run.sh`), and Timeline Cards' `media.ffmpeg_path()` / `ffprobe_path()` look
on `PATH` first. Both binaries are used — ffmpeg for the lane's Opus copies,
the `.peaks` and the audio pulled out of a clip's own media, ffprobe to prove
an extraction came out the length it went in.

### node and the Claude CLI: still not here

The standalone Timeline Cards image bundles node 22 and a pinned
`@anthropic-ai/claude-code`. **This one does not, and will not**
(`COMMERCIAL_READINESS.md` item 1). Its three Claude features — the exact
`→EN` translations, the transcript's semantic search and the overview's
section summaries — are routed through `ai_providers` instead, which is the
site's own `ANTHROPIC_API_KEY` through the SDK, or the customer's own Claude
Code CLI when `[features] ai_cli_providers` is on and an admin has installed
one from the Settings page. With neither, `/cards` reports
`claude: {ok: false, why: "…"}` and the page dims those three buttons, which
is exactly what it does on a machine with no CLI today.

---

## Migrating between the modes

**Two commands, one each way** (2026-08-18). `server/install_dashboard_app.py`
deploys both shapes now — the "Not done here" entry that used to say otherwise
is gone. **No data moves and nothing is deleted, in either direction.**

```bash
# bind-mount -> image
python server/install_dashboard_app.py --mode image \
    --container-image ghcr.io/the-creators-club/ccsync:edge

# image -> bind-mount (the rollback)
python server/install_dashboard_app.py --mode bind
```

`--mode` **implies `--recreate`**: the mode is a compose-level setting, baked
in when the app is created, so a plain restart would keep the old one and
report success. `--recreate` deletes and re-creates the *app definition*; the
host directories, the database, the tree and the archive are untouched — and
the deploy takes a snapshot first (`snapshot_before`), as it does for every
`--recreate`.

Everything the two commands need in their environment is what a deploy always
needs (`SYNCTHING_API_KEY`, `DASH_REPORT_TOKEN`, `DASH_SESSION_SECRET`,
`BROLL_INGEST_TOKEN`, `TRUENAS_PW` — pass them again on a `--recreate` or every
editor is logged out), **plus `DASH_RELEASE_PUBKEYS` for image mode**, which is
a refusal rather than a warning: see the pre-flight below.

To make the mode stick without repeating the flag, put it in the manifest:

```toml
[stack]
mode  = "image"
image = "ghcr.io/the-creators-club/ccsync@sha256:…"   # a tag works; a digest is better
```

### What each direction actually does

| | `--mode image` | `--mode bind` |
|---|---|---|
| code trees shipped | none (steps 2, 2b, 2c, 2f skipped) | all four, staged-verify-swap as always |
| compose | the vendor image, **no** `/app`, `/venv`, `/broll-app`, `/music-app`, `/ytdl-app` mounts | today's body, unchanged |
| host dirs | still created, never removed | reused |
| music data, ffmpeg, deno | provisioned exactly as before | unchanged |
| image | `docker pull`ed onto the NAS first | not touched |

### The pre-flight (image mode only)

Before anything moves, the deploy:

- **refuses an empty `DASH_RELEASE_PUBKEYS`.** In bind-mount mode an unset
  value only costs the upgrade channel (publishes 503). In image mode it also
  costs the dashboard its own updates: `select_code_root.py` will not boot a
  tree it cannot verify, so with no keys **the image always wins and no
  over-the-air update can ever apply** — a site that migrated in order to get
  self-updating dashboards would have migrated for nothing, and nothing in the
  running system would say so (`ZERO_TOUCH_PLAN.md` WP K).
- **warns on a blank `[releases] feed_url`.** Image mode without a feed is a
  perfectly valid deployment — it just updates from the base rig, like bind
  mode — so this is not a refusal.
- **prints the runtime id this checkout would bake**, so
  `docker exec <container> cat /venv/.runtime-id` has something to be compared
  against after boot. A different value is not an error; it means the image
  came from another checkout, and every code bundle built here will be refused
  as a *runtime* change rather than offered as a code update.
- **notes a tag rather than a digest.** A tag is mutable: two deploys a week
  apart can run different code from the same compose body.

### After the switch, automatically

The deploy reads the container back and reports:

- which code root `run.sh` chose (`run.sh: PYTHONPATH=…` plus the
  `select_code_root: …` lines) — `/app/src` is the image, `/data/code/<v>` is a
  bundle applied over the air, and **no such line at all** means the container
  is not in image mode: `/venv/.image-baked` is missing, i.e. a `/venv` mount
  is shadowing the image's layer;
- `/venv/.runtime-id`, against the expected value;
- `/api/v1/health` from inside the container.

A failure prints the rollback command and **never reverts anything**. Reverting
a deploy automatically is how you end up with two half-applied states instead
of one known one.

### What happens to the host code trees

The host's `app/`, `venv/`, `broll-web/`, `music-web/` and `ytdl-web/`
directories are simply unused after a switch to image mode. **Leave them
there.** They are the rollback: `--mode bind` re-ships them, and `/venv` still
holds a populated venv, so the first boot back does not even need PyPI.
`tools/check_deploy_drift.ps1` knows this and does not report them as drift
when `[stack] mode = "image"`.

`--mode bind` re-ships all four trees from the checkout you run it from, so the
rollback also refreshes code that may be older than the image was.

### The registry

The vendor images are on GHCR and the package is **public** — measured
2026-08-18 with no credentials on the wire (`GET
https://ghcr.io/token?scope=repository:the-creators-club/ccsync:pull` returns a
token, and that token reads the manifest). A NAS pulls them without a
`docker login`.

**`:1` does not exist yet.** `image.yml` pushes `:1` only on a `v*` tag and no
`v*` tag has been pushed, so today the registry holds `:edge` (every push to
main) and the short-sha tags. Until the first `v*` release, deploy with
`--container-image ghcr.io/the-creators-club/ccsync:edge` — or, better, the
digest that tag currently resolves to.

The pull itself is a plain `docker pull` over the deploy's existing root SSH,
run before the app is created. TrueNAS's middleware does have its own
(`app.pull_images`, and the app **create** job pulls by itself — the create
wait in `backends/truenas.py` says as much), but a plain **restart** never
pulls, which is the path a routine redeploy takes; and the REST v2.0 argument
shape for a multi-parameter middleware method is not verified from here, while
this file's standing rule is to print a fallback rather than guess at API
shapes. `docker pull` is unambiguous, identical on TrueNAS and DSM, and
idempotent alongside whatever the create job does. `--no-image-pull` skips it
for an air-gapped site that loaded the image with `docker save | docker load`.

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

Two things to check after an IMAGE update specifically (CR-84, 2026-08-26,
where both were regressions the image reintroduced): `docker exec <c>
/venv/bin/python -c "import yt_dlp; print(yt_dlp.version.__version__)"` - the
image installs `dashboard/deploy/requirements.lock`, the third and only
image-relevant one of this repo's three yt-dlp locks - and, on a
`youtube_unblock` site, that run.sh's plugin install succeeded: in image mode
it goes to `/data/unblock-site` (`--no-deps --target`, stamped at
`/data/.requirements-unblock-hash`, appended to PYTHONPATH), because `/venv` is
an `a+rX` image layer this uid-3000 container cannot write.

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

## Serving the dashboard over https (the studio recipe)

A phone will not install the dashboard from `http://`. A service worker, the
"Add to Home screen" prompt and a Trusted Web Activity all require a secure
origin, and each of them fails **silently** without one (`MOBILE_PLAN.md`
section 1, `docs/MOBILE.md`). The studio's NAS already terminates TLS for the
Timeline Cards page inside its TrueNAS `tailscale` app container, so the
dashboard's origin is one more `serve` line in the same container:

```bash
# On the NAS. :443 is the Timeline Cards page and :8443 is an unrelated
# Funnel (2026-08-29), so the dashboard takes the next free port.
sudo docker exec tailscale tailscale serve --bg --https=9443 http://192.168.0.102:8480
sudo docker exec tailscale tailscale serve status
```

That publishes `https://truenas.tail26290e.ts.net:9443/`. The memorable
address is a redirect in front of it, not a second hostname:
`https://thecreatorsclub.co/dash` 302s here from the site repo's
`public/_redirects` (`X:\sites\TheCreatorsClub`, deployed by a push to
main; 2026-09-02). It carries this port literally, so a serve port change
is a two-repo change. A hostname of our own in front would need a
certificate Tailscale cannot issue and a reverse proxy the 2026-08-17
decision ruled out, and would 403 every Send-to-Resolve call until every
companion's `dashboard_url` followed. Then, in
`site.toml` on the deploying machine:

```toml
[net]
dashboard_url = "https://truenas.tail26290e.ts.net:9443"
```

and redeploy (`python server/install_dashboard_app.py --mode bind`), because
`dashboard_url` is what every editor's `~/.ccsync/config.toml` is written
from **and** what each companion builds its loopback CORS allow-list out of
(`COMMERCIAL_READINESS.md` item 156): until a companion is restarted with the
new URL, Send-to-Resolve from the new origin is a 403. Restart the
companions after the change; `loopback_extra_origins` is the per-machine
escape hatch if one editor has to keep both.

**The cookie flag is the part that fails quietly.** `DASH_COOKIE_SECURE`
defaults to `auto`, which means "Secure when the request is https" -- and
behind Serve the request the container receives is plain http with
`X-Forwarded-Proto: https` on it. `auth.request_is_https` believes that
header **only from a peer inside `DASH_TRUSTED_PROXIES`**, whose default is
loopback alone. On this deploy path the list is built for you --
`install_dashboard_app.trusted_proxies_for` writes
`127.0.0.1,::1,<docker_bridge_cidr>,<bind_tailnet>` and `[net]
docker_bridge_cidr` defaults to `172.16.0.0/12`, which covers the bridge
gateway a container-side Serve arrives from -- so usually there is nothing to
add. Check rather than assume: if the dashboard's log carries

```
X-Forwarded-For from 192.168.0.102, which is not in DASH_TRUSTED_PROXIES (...)
```

then Serve is reaching the container from an address the list does not
cover, and the session cookie is going out without `Secure`. Fix it by
naming that address in `[net] trusted_proxies` (keep the loopback and bridge
entries), not by widening the range to the studio LAN. Setting
`DASH_COOKIE_SECURE=1` instead is the blunt version and has one consequence
worth knowing: `auth.refuse_plaintext_login` then **refuses** any login that
does not arrive as https, so `http://192.168.0.102:8480` stops being a way in
from the LAN.

Verify the whole origin, from a machine that can reach the tailnet, before
picking up a phone:

```bash
python tools/check_mobile_origin.py https://truenas.tail26290e.ts.net:9443
```

Seven lines, first FAIL wins, exit 1 on any of them. `docs/MOBILE.md` says
what each line means.

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
  reaches a real customer. **The Serve config itself now exists** (2026-08-30,
  `MOBILE_PLAN.md` M6): `dashboard/deploy/tailscale/serve.json` is the
  TLS-on-443 to `dashboard:8480` document, wired into the `tailscale`
  service read-only at `/config`, and `TS_SERVE_CONFIG` comes from
  `DASH_TAILSCALE_SERVE`, which is **empty by default** -- so nothing about
  this changed for anyone who does not set it, the unmeasured thing is still
  unmeasured, and what lands the day WP B gets a tailnet is a value, not a
  design. Turning it on wants containerboot (the `entrypoint:` override
  above is what stops that image's own `tailscale up` crash-looping) plus a
  `TS_AUTHKEY`; the studio's own path, which runs today and needs neither, is
  the section above.
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
- ~~**`server/install_dashboard_app.py` does not deploy image mode.**~~ **Done
  2026-08-18** — `--mode image|bind` and `[stack] mode`, above. `--image` /
  `DASH_IMAGE` still means the *base* image and applies to bind mode only;
  image mode takes `--container-image` / `[stack] image` / `$CCSYNC_IMAGE`.
- **`broll/web/Dockerfile`** predates all of this and builds the *standalone*
  b-roll app on its own port. It is not part of the dashboard image and is not
  used by any deployment here.
