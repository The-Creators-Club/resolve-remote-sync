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
/mnt/tank/backups/cloud                      ->  /cloud-state:ro   (site.toml cloud_state, optional)
/mnt/tank/backups/sorter                     ->  /backup-out:rw    (site.toml backup_out, optional)
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
   # cloud_state = "/mnt/tank/backups/cloud"   # ledger browser: the cloud backup's state, read-only
   # backup_out = "/mnt/tank/backups/sorter"   # what the sorter writes for the cloud upload script
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

4. **The cloud backup (ledger browser; optional).** The sorter decides WHEN
   the nightly cloud upload runs and shows its progress; the NAS script
   (footage-sorter `nas/cloud-backup.sh`, v2) does the upload and holds the
   restic password. Three pieces, in this order:

   * **Folders and mounts.** Set `cloud_state = "/mnt/tank/backups/cloud"`
     (mounted `/cloud-state:ro`) and `backup_out = "/mnt/tank/backups/sorter"`
     (mounted `/backup-out:rw`) in `[footage_sorter]`. The deploy creates
     `backup_out`, `control/` and `snapshots/` ONLY IF MISSING, as
     `alex:editors` mode `2770` (setgid; `backup_out_owner` names another user),
     and never chowns or chmods one that exists. The container runs as
     `broll:editors` and also gets the `editors` group as a supplementary group
     (`group_add`), with the gid read from the NAS at install time and never
     written down, so it can write there and alex, who runs the upload script,
     can read what it writes. Check after the deploy:

     ```bash
     ls -ld /mnt/tank/backups/sorter /mnt/tank/backups/sorter/{control,snapshots}   # alex editors drwxrws---
     docker exec ix-ccsync-dashboard-dashboard-1 sh -c 'id; touch /backup-out/control/.t && rm /backup-out/control/.t && echo writable'
     ```

   * **The v2 script.** Install it by writing a temp file beside the live one
     and `mv`-ing it over; NEVER edit the live file in place (a running `sh`
     keeps reading the old inode, and an in-place edit changes what it reads
     next):

     ```bash
     cp footage-sorter/nas/cloud-backup.sh /mnt/tank/backups/bin/cloud-backup.sh.new   # from creator-1, e.g. over scp
     chmod 755 /mnt/tank/backups/bin/cloud-backup.sh.new
     mv /mnt/tank/backups/bin/cloud-backup.sh.new /mnt/tank/backups/bin/cloud-backup.sh
     ```

   * **The schedule.** v2 is started by TrueNAS cron job 4 every 10 minutes
     and uploads only when the sorter has asked (`control/run-now`) or the
     nightly time in `control/schedule.json` has passed (`flock` makes a run
     that is still going skip every start). Change the job from its old nightly
     schedule:

     ```bash
     midclt call cronjob.query '[["id","=",4]]'          # read the current job first
     midclt call cronjob.update 4 '{"schedule": {"minute": "*/10", "hour": "*", "dom": "*", "month": "*", "dow": "*"}}'
     ```

   * **The clock.** The dashboard container sets no `TZ` and runs UTC, but the NAS script and its cron run in the
     NAS's local time, and the sorter's 04:00 ledger snapshot and 04:30 NAS scan must agree with them. The deploy
     passes the sorter a `timezone` setting: `[footage_sorter] timezone` if set, otherwise the NAS's own zone read at
     install time (`/etc/timezone`, else `timedatectl`), never a literal. The container needs a zone database for it
     (the `python:3.12-slim` base carries `/usr/share/zoneinfo`; check, don't assume):

     ```bash
     docker exec ix-ccsync-dashboard-dashboard-1 python -c "import zoneinfo; print(zoneinfo.ZoneInfo('$(cat /etc/timezone)'))"
     ```

   Once `/sorter` shows the cloud panel with real numbers (progress, last
   snapshot, box usage), retire the `cloud-backup-status` app on :8798: stop
   and delete the app, then remove its entry from whatever links to it. The
   panel reads the same `progress.json` and `last-summary.json`.


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
