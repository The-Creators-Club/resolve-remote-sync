# Deploying the Footage Sorter on the NAS

The operator runbook for getting new Footage Sorter code onto the dashboard's
`/sorter` mount. It is `docs/CARDS_DEPLOY.md` with the sorter's names in it, on
purpose: the two are deployed by the same script, in the same step order, with
the same snapshot rules. Read that document for the reasoning behind each step;
this one records what differs.

**This is not a dashboard release and not a companion release.** Like Timeline
Cards, the sorter's code is another repo's (`E:\Projects\Editing\footage-sorter`),
so it ships separately from the image: **re-ship the commit into
`<host-root>/sorter-web` and RESTART the container**. `/sorter-app` is a mount in
image mode too.

What ships is `footage_sorter/` (the Python package) and `public/` (the page) of
ONE COMMIT, by `git archive`. The repo's `lib/`, `server.js`, `data/`, `cache/`,
`node_modules/`, `test/`, `tests/`, `tools/`, `docs/`, `cloud/` and `ingest/` do
not ship, by an allow-list, not a deny-list. The mounts, `pool_host` and why the
pool is ONE bind are in `docs/DOCKER.md`, "The Footage Sorter mounts".

```
/mnt/tank/apps/ccsync-dashboard/sorter-web   ->  /sorter-app:ro    (the commit)
/mnt/tank/apps/ccsync-dashboard/sorter-data  ->  /sorter-data:rw   (3000:3000, 770)
/mnt/tank/TheCreatorsPool                    ->  /pool:rw          (site.toml pool_host)
```


## One-time setup

1. **`site.toml`** (the studio's):

   ```toml
   [footage_sorter]
   enabled = true
   src = 'E:\Projects\Editing\footage-sorter'
   pool_host = "/mnt/tank/TheCreatorsPool"
   source_roots = ["/pool/Temp Transfer"]
   dest_root = "/pool/Creators_Club/Projects"
   legacy_id_roots = { "/pool/Temp Transfer" = "W:\\Temp Transfer", "/pool/Creators_Club" = "P:\\" }
   vault_root = "/vault/Vault/2026/FF5"
   # pool_gid = "3000"   # only if 3000:3001 cannot already write Temp Transfer
   ```

2. **Open the pool's directories to the container** (once, on the NAS; the
   recipe and the reason are in `docs/DOCKER.md`). `pool_host` must be the
   dataset root and `Temp Transfer` and `Projects` must be on the SAME
   filesystem, or every move is `EXDEV`:

   ```bash
   docker exec ix-ccsync-dashboard-dashboard-1 python -c "import os; \
   print(os.stat('/pool/Temp Transfer').st_dev == os.stat('/pool/Creators_Club/Projects').st_dev)"
   ```

3. The deploy creates `sorter-web` (root, 755) and `sorter-data` (3000:3000,
   770) on every site. **Bring the Node sorter's state across with the
   migration tool, not by copying `data/`.** Its JSON is full of `W:\` and
   `P:\` paths (140k of them in the catalog and clips), and those mean nothing
   on the NAS. The tool rewrites them through `legacy_id_roots`, read
   backwards, so clip ids, and with them every assignment, are unchanged (all
   35,936 checked, 2026-11-09). It also resets the catalog's journal offset,
   strips the PC's roots from `settings.json`, and leaves the old thumbnails
   behind; the backfill makes the new ones. On creator-1, with the Node
   sorter STOPPED so its files are still:

   ```powershell
   # roots.json holds the site's legacy_id_roots as JSON:
   #   {"/pool/Temp Transfer": "W:\\Temp Transfer", "/pool/Creators_Club": "P:\\"}
   cd E:\Projects\Editing\footage-sorter
   py -3.12 -m footage_sorter.migrate --from data --to $env:TEMP\sorter-data --roots "@roots.json"           # report only
   py -3.12 -m footage_sorter.migrate --from data --to $env:TEMP\sorter-data --roots "@roots.json" --write
   ```

   Then copy `$env:TEMP\sorter-data\*` into
   `/mnt/tank/apps/ccsync-dashboard/sorter-data/` and run `chown -R 3000:3000`
   on it before the first start. After the first start, run one scan
   (`Scan` on the page): it re-reads the pool under its `/pool` names, and the
   clip count should equal the Node sorter's.


## The usual deploy (the recipe)

From **creator-1**, in `E:\Projects\Editing\ccsync`. Same rules as
`docs/CARDS_DEPLOY.md` "The usual deploy": never a BARE
`install_dashboard_app.py`, secrets and deploy in ONE PowerShell command.

**1. Commit the sorter change** in `E:\Projects\Editing\footage-sorter`. The
snapshot is a commit: **an uncommitted or untracked file in `footage_sorter/` or
`public/` is not in it**, and the run says so ("N file(s) ... are modified or
untracked and are therefore NOT in this deploy"). The default ref is `master`
(that repo's trunk); a work branch is shipped with `--sorter-commit <branch>`.

**2. Read the LIVE image digest and the LIVE Cards commit off the NAS** (the
`live.sh` of CARDS_DEPLOY.md; add
`/mnt/tank/apps/ccsync-dashboard/sorter-web/DEPLOYED_COMMIT` to its `grep`).
Both are needed: **one run re-ships BOTH trees**, and an unpinned
`--cards-commit` would ship whatever Timeline Cards' `main` is today alongside
your sorter change.

**3. Dry run, then the real run:**

```powershell
. .\tools\load_secrets.ps1; dashboard\.venv\Scripts\python.exe server\install_dashboard_app.py --mode image --container-image ghcr.io/the-creators-club/ccsync@sha256:<live digest> --cards-commit <live cards sha> --sorter-commit <sha> --music-data none --yes --dry-run
. .\tools\load_secrets.ps1; dashboard\.venv\Scripts\python.exe server\install_dashboard_app.py --mode image --container-image ghcr.io/the-creators-club/ccsync@sha256:<live digest> --cards-commit <live cards sha> --sorter-commit <sha> --music-data none --yes
```

| flag | why |
|---|---|
| `--sorter-commit <sha>` | the commit to ship; default `master` (`SORTER_COMMIT` also works) |
| `--cards-commit <live sha>` | pins Timeline Cards at what is already live, so only the sorter changes |
| `--sorter-src-dir <path>` | the escape hatch: ship that checkout's `footage_sorter/` and `public/` AS THEY STAND (`SORTER_SRC` does the same). No `DEPLOYED_COMMIT` is written, and the record says `override` |

The others are CARDS_DEPLOY.md's. The run prints the snapshot before anything
moves (`Footage Sorter snapshot: <sha> (master) of E:\Projects\Editing\footage-sorter -- <subject>`)
and **refuses, before anything is touched**, if the ref does not exist or if
that commit has neither `footage_sorter/` nor `public/`. At the end:

```
installed Footage Sorter: commit <short> (master), marker DEPLOYED_COMMIT in .../sorter-web
```

A "health check FAILED" line seconds before the container goes healthy is the
same premature false alarm CARDS_DEPLOY.md describes: check `docker ps` first.


## Verify

1. **The right commit is live:** `cat
   /mnt/tank/apps/ccsync-dashboard/sorter-web/DEPLOYED_COMMIT`, or the local
   record `~/.ccsync/state/sorter_deployed.json`.
2. **The mount is up:** `GET /api/v1/health` reports `"/sorter": {"status":
   "mounted"}`. `absent` = no tree or an incomplete one; `disabled` names the
   setting that is off (usually `DASH_SORTER_ENABLED`, `DASH_SORTER_DATA` or
   `DASH_SORTER_SRC`).
3. **The pool is one filesystem:** the `st_dev` check above prints `True`.
4. **The page counts match** the Node sorter's (clips, assignments) on the
   migrated state.
5. **Nothing else on the dashboard moved.** `/sorter` is tri-state and never
   fatal: renaming `sorter-web` aside and restarting leaves a working
   dashboard with an `absent` `/sorter`.


## Rollback

Re-deploy the previous commit (`--sorter-commit <old sha>`, named in the old
tree's `DEPLOYED_COMMIT`), or rename the backup the deploy kept:
`mv sorter-web sorter-web.bad && mv sorter-web.old.<timestamp> sorter-web`, then
`docker restart ix-ccsync-dashboard-dashboard-1`. `sorter-data` is never
touched by a deploy.


## See also

* `docs/CARDS_DEPLOY.md` -- the recipe this follows, and the staged-verify-swap
  it shares.
* `docs/DOCKER.md`, "The Footage Sorter mounts" -- the pool, the EXDEV reason,
  the chown/group recipe.
* `docs/CONFIG.md` -- every `DASH_SORTER_*`.
* `dashboard/src/ccsync_dashboard/sorter.py` -- the mount and its tri-state.
* footage-sorter's `docs/DASHBOARD-MODULE-PLAN.md`.
