# Refreshing Timeline Cards on the NAS

The operator runbook for getting new Timeline Cards code onto the dashboard's
`/cards` mount. Written 2026-09-03, when the 2026-09-03 cards wave
(KNOWN_BUGS CR-122..CR-137) needed shipping and there was no doc that said
how.

**This is not a dashboard release and not a companion release.** Three
different things are shipped three different ways, and reaching for the wrong
one is the usual mistake:

| what | how | where it is written down |
|---|---|---|
| the dashboard (`ccsync_dashboard`) | image-mode OTA: `build_dashboard_bundle.py` -> `publish_feed.py --kind dashboard` -> Settings -> Packages -> [ APPLY ] | `docs/RELEASE.md` §6, "Deploy the dashboard" |
| **Timeline Cards** | **re-ship the checkout into `<host-root>/cards-web` and RESTART the container** | this document |
| companions | `tools\ship.cmd` / the upgrade channel | `docs/RELEASE.md`, `docs/RELEASE_PATHWAYS.md` |

`docs/RELEASE_PATHWAYS.md` ("Neither pathway is 'the dashboard's own code'")
says the same in one sentence: *Timeline Cards ships separately again
(`install_dashboard_app.py` re-ships `[timeline_cards] src` -> `cards-web`
even in image mode)*.


## Why it works this way

`dashboard/src/ccsync_dashboard/cards.py`'s module docstring is the contract,
and the part that matters here is that **the code is another repo's
checkout**. The mount does not import a package from the image or from an OTA
bundle; `checkout_src()` reads `DASH_CARDS_SRC`, `_add_to_path()` appends it
to `sys.path` (appended, never prepended), and `import_cards()` then does:

```python
handler = importlib.import_module("multicam_pipeline.cards.handler")
project_agent = importlib.import_module("multicam_pipeline.cards.project_agent")
```

`docs/CONFIG.md` on `DASH_CARDS_SRC`: *the MulticamPipeline checkout
`multicam_pipeline.cards` is imported from -- `/cards-app` in the container,
shipped there by `install_dashboard_app.py` from `[timeline_cards] src`. **Not
on `PYTHONPATH`**: another repo's tree is never in the image or in a code
bundle, so `cards.py` appends this to `sys.path` itself.*

`docs/DOCKER.md` ("The Timeline Cards mounts") has the mount table:

| what | where it comes from | mount |
|---|---|---|
| the code (another repo's checkout) | `CARDS_SRC` / `[timeline_cards] src` -> `<host-root>/cards-web` | `/cards-app:ro` |
| the vault | `[timeline_cards] vault_host` | `/vault:rw` |
| the footage share | `[timeline_cards] media_host` | `/media:ro` |

and the line that makes this doc necessary: **`/cards-app` is a mount in IMAGE
MODE TOO -- the only code mount that is.** The vendor image carries `/app`,
`/broll-app`, `/music-app` and `/ytdl-app` as layers; it cannot carry a tree
from a different repository. So on this studio's image-mode stack, a dashboard
OTA update ships everything EXCEPT Timeline Cards.

On the TrueNAS host today (`site.toml`: `[apps] root =
"/mnt/tank/apps/ccsync-dashboard"`), that tree is:

```
/mnt/tank/apps/ccsync-dashboard/cards-web        ->  /cards-app:ro
```

It is root-owned and world-readable, mounted read-only, and it is **not a git
checkout** -- nothing on the NAS pulls, and there is no remote to pull from.
It is a copy of the MulticamPipeline working tree on the base rig, which is
what `[timeline_cards] src` names:

```toml
[timeline_cards]
enabled = true
src = 'E:\Projects\Editing\Resolve\MulticamPipeline'
```


## What gets copied

**The minimal set the mount needs is the `multicam_pipeline` package** --
`cards.py` imports exactly two modules out of it
(`multicam_pipeline.cards.handler` and `multicam_pipeline.cards.project_agent`)
and they pull the rest of the package in themselves, which is why `cards.py`
imports by NAME and holds no list of the twenty modules involved. The deploy's
own pre-flight tests for one file and nothing else
(`server/install_dashboard_app.py`):

```python
ship_cards = bool(cards_src and (cards_src / "multicam_pipeline" / "cards"
                                 / "handler.py").is_file())
```

**What is actually shipped is the whole checkout minus an exclude list**, and
that is fine -- a read-only copy of a package tree, not an install:

```python
CARDS_EXCLUDE_DIRS = BROLL_EXCLUDE_DIRS | {
    "docs", "deploy", "scratch", "golden", "tools", ".claude",
}
```

(plus `.venv`, `__pycache__`, `.pytest_cache` from `EXCLUDE_DIRS`). Note what
is NOT excluded: **`tests/` goes to the NAS**. Nothing imports it there and it
costs a few MB; leave it, so that a served page can be diffed against the
golden files that describe it. Do not add `tests` to that list to "tidy up" --
`tests/golden/page.html` is the only thing on the NAS that says what the page
should look like. (verify: no code reads `/cards-app/tests` at runtime; this
is a read of the imports, not a measurement.)


## The supported route: re-run the deploy from the base rig

One command, from the repo root on the base rig, with the usual secrets in the
shell (`tools\load_secrets.ps1` -- `docs/SECRETS.md`):

```powershell
.\tools\load_secrets.ps1
dashboard\.venv\Scripts\python.exe server\install_dashboard_app.py --dry-run
dashboard\.venv\Scripts\python.exe server\install_dashboard_app.py
```

Do the `--dry-run` first and read what it says about `cards-web`. What this
does for Timeline Cards (step 2g in `install_dashboard_app.py`) is the same
staged-verify-swap every code tree gets:

1. upload the checkout (minus the excludes) into a fresh `mktemp` staging dir;
2. verify the staged copy by **file count AND total bytes** against the local
   manifest -- a transfer that wrote every file but truncated the last one
   passes a count-only check;
3. build `cards-web.new` from it and verify that;
4. `mv cards-web cards-web.old.<timestamp>` then `mv cards-web.new cards-web`
   -- an atomic rename, and it rolls back if the second `mv` fails;
5. prune older backups, **always keeping the one just replaced**;
6. restart the container (step 3 of the deploy).

The SSH host key is pinned by the toolchain itself (`[nas] ssh_hostkey` in
`site.toml`, per CLAUDE.md: a changed key is a refusal, never a re-trust), so
there is nothing to do about host keys on this route. That is the main reason
to prefer it.

**On this image-mode stack the run also touches the dashboard container.** It
pushes no dashboard code in image mode (`push_code = not image_mode`) but it
does restart the app, which is exactly what step 3 below needs anyway. If the
repo's dashboard VERSION is ahead of what is live, deploy the dashboard first
(`docs/RELEASE.md` §6) -- that is the deploy order in KNOWN_BUGS' batch header:
dashboard, then this, then the companions.


## The by-hand route (emergency only)

Used on 2026-09-02 for a one-file fix (KNOWN_BUGS CR-101). It is a staged copy
plus an atomic rename, done by hand, and it exists for the case where the
whole deploy cannot be run. **Everything in this section is marked (verify):
it is reconstructed from what the supported route does, not from a scripted
path in this repo.**

```bash
# (verify) from the base rig, in Git Bash. The host key must already be
# trusted for OpenSSH; the pin the toolchain uses is [nas] ssh_hostkey in
# site.toml and it is an ed25519 key.
SRC='/e/Projects/Editing/Resolve/MulticamPipeline'
NAS=truenas_admin@192.168.0.102
ROOT=/mnt/tank/apps/ccsync-dashboard

rsync -a --delete \
  --exclude .git --exclude .venv --exclude __pycache__ --exclude .pytest_cache \
  --exclude docs --exclude deploy --exclude scratch --exclude golden \
  --exclude tools --exclude .claude \
  "$SRC/" "$NAS:/tmp/cards-web.new/"                      # (verify)

ssh "$NAS" "sudo sh -c '
  test -f /tmp/cards-web.new/multicam_pipeline/cards/handler.py &&
  rm -rf $ROOT/cards-web.prev &&
  mv $ROOT/cards-web $ROOT/cards-web.prev &&
  mv /tmp/cards-web.new $ROOT/cards-web &&
  chown -R root:root $ROOT/cards-web'"                     # (verify)
```

Three things about that, each of which has bitten someone:

* **The `test -f` is the point.** An empty or half-copied `cards-web` is a
  silently absent feature behind a green healthcheck: `/cards` reports
  `absent`, the nav link disappears, and nothing errors.
* **`--delete` into a staging dir, never into the live tree.** The live tree
  is only ever replaced by a rename. `rsync --delete` straight onto
  `cards-web` is the "no step may leave the live tree gutted" rule broken.
* **Keep the previous tree.** The supported route keeps it as
  `cards-web.old.<timestamp>`; by hand, `cards-web.prev` (above) is the same
  idea and the rollback in the last section assumes it.

A single PAGE file (`multicam_pipeline/cards/page/*.js`, `cards.css`,
`cards.html`) is the one thing that can be copied in place without a restart:
`render_page` re-reads it on mtime. That is what CR-101 did (previous file
kept as `.bak-20260902`). It does **not** generalise to a `.py`.


## Restart the container -- this is not optional

**Python modules load once.** `cards.py` imports
`multicam_pipeline.cards.handler` and `...project_agent` at mount time, and
the mounted app holds a live `ProjectAgentEngine` with background threads
(the library sweep, the ffmpeg worker, the translation and search runs). New
`.py` bytes on disk change nothing at all in a running dashboard.

There is a second reason, and it applies even to a pure page-file change made
through the supported route: **the swap changes the directory's inode, and the
container bind-mounts it**, so the running container keeps serving the OLD
inode until it is restarted (`install_tree`'s docstring; a redeploy alone was
observed not to do it, 2026-07-24). `docker restart` re-resolves bind mounts.

The supported route restarts as part of the deploy (`restart_dashboard_container`
-> a direct `docker restart` on TrueNAS, because `/app/redeploy` was observed
NOT to restart the container on TrueNAS 25.10). By hand:

```bash
ssh "$NAS" 'sudo docker restart ix-ccsync-dashboard-dashboard-1'
```

The container name is `ix-<app_name>-dashboard-1` -- the TrueNAS Apps compose
convention, `truenas.TruenasBackend.dashboard_container`, and `ccsync-dashboard`
is `APP_NAME`. `sudo docker ps` confirms it if a DSM/TrueNAS update ever
changes the convention.

Give it ~20 s. `/cards`' engine starts with the mount, and a restart also
re-runs the picker's memory read from `/data/cards/cards_ui.json`, so the page
comes back on the same episode root it was on.


## Verify

In this order. The first two are cheap and catch the two failure shapes that
look like nothing.

1. **The mount is up.** `GET /api/v1/health` reports
   `"/cards": {"status": "mounted"}`. `absent` means the tree is not there or
   is incomplete (an operator problem, and it logs at WARNING); `disabled`
   names which setting is off.
2. **The page is the NEW page.** `GET /cards/` with a session cookie and
   compare its size against the checkout's `tests/golden/page.html`, which the
   2026-09-03 wave regenerated from **691 497 -> 748 009 bytes**. The golden is
   generated from a standalone server on an empty root, so it is not
   byte-identical to what the mount serves; treat the number as "the page grew
   by ~56 KB, not 'the page is 691 KB again'". (verify: no check in this repo
   compares the served page to that golden.)
3. **Markers carry `kind`.** `GET /cards/api/state` and look at a `## §`
   heading's marker: it must have `"kind": "section"` (CR-122). This is the
   single best proof that the SERVER half of the wave is live -- a page
   refresh cannot fake it.
4. **The categories strip renders.** Open `/cards/`, go to the staged shelf:
   `#scats` (the chip strip) is a sibling of `#slist` and is drawn by
   `page/12-cats.js`; right click a staged card offers **add to category**
   (CR-131). This is the proof that the PAGE half is live and that the browser
   is not on a cached bundle -- hard reload if in doubt.
5. **A section recoloured Red is still a heading**, in the page and in the
   file (CR-122), and the overview drag of a section actually moves it
   (CR-127). These are the two the owner reported; do them by hand once.
6. **Nothing else on the dashboard moved.** The restart takes the whole
   dashboard with it, so glance at FLEET: the grid answers and lanes report.
   "The dashboard is what tells everyone whether their footage is syncing"
   outranks `/cards`.


## Rollback

The previous tree is still on the NAS -- that is what the rename buys.

```bash
# (verify) supported route: the backup is named in the deploy's own output,
# "installed code: <target> (previous code kept at <target>.old.<ts>)".
ssh "$NAS" "sudo sh -c '
  mv $ROOT/cards-web $ROOT/cards-web.bad &&
  mv $ROOT/cards-web.old.<timestamp> $ROOT/cards-web'"
ssh "$NAS" 'sudo docker restart ix-ccsync-dashboard-dashboard-1'
```

By hand, the same with `cards-web.prev`. The prune step keeps the most recent
backup and never one a container is still reading, so the copy you want is
there until the NEXT successful deploy, and only then.

If the tree is beyond saving, **`/cards` failing is not the dashboard
failing**: the mount is tri-state and never fatal (`cards.py`, and
ARCHITECTURE.md §4's three rules). Renaming `cards-web` aside and restarting
gives an `absent` `/cards` and a working dashboard, which is a legitimate
place to stand while the checkout is sorted out.


## See also

* `dashboard/src/ccsync_dashboard/cards.py` -- the mount, its docstring, and
  the tri-state.
* `docs/DOCKER.md`, "The Timeline Cards mounts" -- the three mounts, the vault
  chown, and why `/media` and `media_map` are useless apart.
* `docs/CONFIG.md` -- every `DASH_CARDS_*`.
* `docs/TIMELINE-CARDS-INTO-CCSYNC.md` -- why any of this is in the dashboard
  at all (phase 3), and §9.4 for the original go-live runbook.
* `docs/RELEASE.md` §6 -- the dashboard's own release, which this is not.
* `site.example.toml`, `[timeline_cards]` -- the order to configure it in, and
  the two settings that fail in ways that look like something else.
* `KNOWN_BUGS.md` CR-100/CR-101 and CR-121..CR-137 -- what has actually gone
  wrong with this mount so far.
