# Backup and restore

The backup floor under the authoritative tree, and the procedure for
publishing a search index onto a live NAS. Written 2026-08-17 for
`docs/COMMERCIAL_READINESS.md` item 8, which found the state of things at the
time: **zero references to snapshots, replication or restore anywhere in the
code or the docs.** Every recovery path this system had was a rename-aside, a
`.ccsync-trash` or Syncthing versioning — all downstream of the thing most
likely to destroy a customer's footage.

Read `docs/SERVER.md` (TrueNAS) or `docs/SERVER-SYNOLOGY.md` (DSM) first for
what the NAS holds and where.

> **START AT THE DASHBOARD, NOT AT THIS DOCUMENT** (SYS-15, 2026-08-29).
> **Settings -> RECOVERY** (`/admin/recovery`) is the primary route for
> getting something back. It names what is protected right now, asks what went
> wrong, and either performs the recovery itself or prints the commands below
> **with this NAS's real dataset, pool and platform already substituted in** -
> and it refuses to print a command built on a fact it could not verify.
>
> | What happened | Where to go |
> |---|---|
> | a file or folder was deleted, overwritten or changed on the server | RECOVERY -> restore into `<project>/.restored-<ts>/`. Nothing is overwritten. |
> | CC Sync changed clip paths in somebody's Resolve project | RECOVERY -> undo it on that computer, or their own tray. `docs/RESOLVE_EDIT_SAFETY.md` |
> | this dashboard lost projects, editors or ticks | Settings -> PACKAGES -> the dashboard's own database backups |
> | the b-roll or music search is wrong | `publish_db.py --rollback` (section 6) |
> | everything on the server is wrong since a moment | the only case that still needs a root shell: section 4b, via RECOVERY, which prints it |
> | rehearsing a restore | RECOVERY -> [ REHEARSE A RESTORE NOW ] (section 7) |
>
> **The rest of this document is the reference and the fallback**: what those
> commands do, what they cost, and what to do on a deployment the dashboard
> has not been given a snapshot mount for. Sections 4a to 4e are the shell
> procedures, and they are correct - they are simply no longer the first thing
> to reach for.
>
> Two things a deployment has to be given before the page can restore anything
> itself, because a container sees `/projects` and not the pool path behind it:
> `DASH_SNAPSHOT_DIR` (a read-only mount whose entries are snapshots) and
> `DASH_SNAPSHOT_PROJECTS_SUBPATH` (the path from a snapshot root to the
> Projects tree). Without them the page still runs the runbook and prints the
> commands; it just cannot do the copying. `docs/SELF_DIAGNOSIS.md` section 15
> is the full description.
>
> **`install_dashboard_app.py` sets both since 2026-09-04** (OPS-3). It asks
> the NAS which dataset the tree is in, checks that `<mountpoint>/.zfs/snapshot`
> is really there, mounts it read-only at `/snapshots` and works the subpath
> out from the paths it already has. Nothing is mounted where it could not
> verify the directory - docker CREATES a missing bind source, and a stray
> `.zfs` directory invented inside a customer's footage tree is not a thing a
> deploy may do - so the honest outcomes are a working RECOVERY page or a page
> that says **"this deployment was never given a snapshot mount"** and names
> the variable. Two cases need a hand: a **Synology** (share snapshots live
> under `/volume<N>/@sharesnap/<share>`, which no path here can derive) and a
> stack installed from a pasted compose file. Both are one key:
> `site.toml [tree] snapshot_dir` (plus `snapshot_projects_subpath`), and the
> mount line in the compose file if you pasted one.

---

## 1. What is protected, and what protects it

| What | Where it lives | Protected by |
|---|---|---|
| The project tree (all footage, projects, renders) | `<pool_root>/<tree_name>/Projects` | NAS snapshots (below) + Syncthing `ignoreDelete` + staggered versioning |
| The shared asset libraries (LUTs, stills, music, b-roll archive) | `<tree_name>/Assets/...` | NAS snapshots + Syncthing versioning (LUTs/Stills only) |
| `dashboard.db` — projects, editors, ticks, transfer history | `<apps_root>/data/dashboard.db` (container: `/data`) | NAS snapshots of the **apps** dataset, plus a backup-API copy into `<apps_root>/data/backups/<ts>-<label>/` before every dashboard self-update (§3) |
| `broll.db` — the b-roll search index | `<tree_name>/Assets/B-roll Archive/broll.db` | NAS snapshots + the `.prev-<ts>` a publish leaves behind |
| `music.db` — the music index (incl. editors' queued ingests) | `<apps_root>/music-data/music.db` | NAS snapshots + `.prev-<ts>` / `.old.<ts>` |
| `client_shares.db` — client folders and their links (`docs/CLIENT_FOLDERS.md`) | `<tree_name>/Assets/B-roll Archive/client_shares.db`, beside `broll.db` | NAS snapshots. **Deliberately not** in `broll.db`, so a publish cannot replace it; restore like any file (§4a), never one of the `-wal`/`-shm` pair without the other |
| `ytdl.db` | `<apps_root>/ytdl-data/ytdl.db` | NAS snapshots of the apps dataset |
| The deployed app code | `<apps_root>/app` | git, plus `app.old.<ts>` from the last deploy |
| An editor's local copy | `P:\` on their machine | **Nothing.** It is a replica, not a backup. |
| **Syncthing's own config** - every device pairing, every folder share, the GUI credentials | TrueNAS: a TrueNAS-managed `ix_volume` for the catalog app. DSM: inside the compose stack's own volume | **NOT covered.** It is outside both `[tree] pool_root` and `[apps] root`, which are the only two things `setup_snapshots.py` knows about, so it relies entirely on the TrueNAS Apps pool. Losing it loses every editor's pairing; the recovery is re-approving each device (§8) (OPS-22, 2026-09-03) |
| **The release signing key** (`release.key`) | one Windows profile on the base rig, `%USERPROFILE%\.ccsync-release\` | **Nothing.** Never on the NAS, in no snapshot, in no repo. A companion trusts only the public keys baked into the build it is running, so losing the private half means no signed publish for the fleet until every machine is reinstalled by hand, and `RELEASE.md`'s rotation needs the OLD key. **Copy it into a password manager** (OPS-8, `INSTALL.md` Step 6) |
| **The Android signing keystore**, if you build the mobile app | one Windows profile on the base rig | **Nothing**, for the release key's reasons. Google Play will not accept an app signed by a different key, so the answer to losing it is a new listing. Same password manager, same day |

Two datasets carry everything that matters: the **tree** dataset and the
**apps** dataset. Both are snapshotted on the same schedule — **provided each
one really is a dataset.**

> **Check this before believing the table above** (server-6, 2026-08-21). Every
> row that says "NAS snapshots" assumes the path is inside a dataset a periodic
> task can be created for. On this fleet's box `/mnt/tank/apps` is a plain
> **directory in the pool root**, not a dataset: `setup_snapshots.py` therefore
> refuses the `app` target ("that is a pool, not a dataset"), exits non-zero,
> and `dashboard.db`, `music.db` and `ytdl.db` have **no scheduled snapshot at
> all**. The `.zfs/snapshot` restore paths in §4b/§4c do not exist either — a
> snapshot of `tank` is browsable at `/mnt/tank/.zfs/snapshot/<snap>/apps/...`,
> not at `/mnt/tank/apps/.zfs/...`.
>
> The fix is one command on the NAS, then re-run §2:
>
> ```bash
> sudo zfs create -p tank/apps/ccsync-dashboard   # the [apps] root, as a dataset
> # move the existing contents in, or deploy into the fresh dataset
> ```
>
> `python setup_snapshots.py --list --apply` is the check: it must name a dataset with
> a slash in it for **both** targets.
>
> Since 2026-09-03 (CR-140) you do not have to remember to run it: the deploy
> puts both dataset names into the container (`DASH_TREE_DATASET`,
> `DASH_UPDATE_SNAPSHOT_DATASET`, §3) and the protection panel checks each one
> against the NAS's snapshot tasks on every collector cycle. The studio's own
> box is the case above - tree `tank/TheCreatorsPool` has hourly, daily and
> weekly tasks; apps is flat `tank` with **no task on it** - and the panel now
> says so instead of shrugging. On DSM both read CANNOT VERIFY permanently:
> Synology's snapshot schedules have no readable API.

### Cadence and retention

| | Naming | When | Kept |
|---|---|---|---|
| hourly | `ccsync-%Y%m%d-%H%M` | every hour, on the hour | 24 hours |
| daily | `ccsync-daily-%Y%m%d` | 03:10 | 30 days |
| pre-op | `ccsync-pre-<label>-<ts>` | before every privileged recursive op (§3) | until the pool prunes them by hand |

24 hourly + 30 daily is a **floor, not an archive**: it buys back the last day
at fine grain and the last month at daily grain, and it costs only the blocks
that changed. It is deliberately cheap enough that nobody turns it off.

**It is not offsite.** A snapshot on the same pool does not survive a fire, a
theft or a two-disk failure. Offsite replication (ZFS `replication.create` to a
second box, or DSM's Snapshot Replication to another Synology) is a separate,
per-customer decision — see §8.

---

## 2. Configuring it

From the base rig, against the NAS:

```powershell
cd server

# TrueNAS: dry-run first (this is the default -- it changes nothing)
python setup_snapshots.py
python setup_snapshots.py --apply

# Synology: same command, --nas-kind from site.toml or explicit
python setup_snapshots.py --nas-kind synology
python setup_snapshots.py --nas-kind synology --apply
```

Idempotent: a second `--apply` prints `snapshot task already correct,
skipping`. Verify at any time with:

```powershell
python setup_snapshots.py --list --apply
```

which prints, per dataset, how many snapshots exist and the newest one, and
since 2026-08-21 (server-6) also names any target that **cannot be scheduled at
all** and exits non-zero for it. **That listing is the check that backups are
working — not the exit code of the configure run.** `--apply` is what makes it
ask the NAS; without it the listing is a dry-run and reports nothing.

### TrueNAS

`setup_snapshots.py --apply` creates or updates two `pool.snapshottask`
entries per dataset over the REST API, keyed on `(dataset, naming_schema)`.
They appear in the UI under **Data Protection → Periodic Snapshot Tasks**.
Nothing else in this repo creates, edits or deletes them.

The dataset is resolved by asking the NAS (`df --output=source`), because the
paths in `site.toml` are mostly *directories inside* a dataset:
`/mnt/tank/TheCreatorsPool/Creators_Club` is a folder in `tank/TheCreatorsPool`
on this fleet's box. The script prints which dataset it settled on. A bare pool
(`/mnt/tank`) is refused: a recursive hourly task there is somebody's whole NAS.

That refusal is also what a target with **no dataset of its own** looks like,
and it is not cosmetic — nothing gets scheduled for it. The message names the
path and the `zfs create -p ...` that fixes it. See the callout in §1: the
`[apps]` root is the one that hits this on a box where `apps` was made as a
folder rather than a dataset.

The `df` probe runs **under `sudo`** (server-2, 2026-08-21). `statfs` needs
search permission on every component of the path, and the admin account has no
traverse on the 2770 tree — an unprivileged probe was refused for
`<tree>/Projects` on every run, fell back to a dataset name that does not
exist, and `setup_tree.py`'s pre-`chown -R` snapshot silently became a WARNING.

### Synology

DSM can **take** a share snapshot from base DSM — `SYNO.Core.Share.Snapshot
create`, no package needed — and that is what `snapshot_before` uses. But
**scheduling** belongs to the free *Snapshot Replication* package, and there is
no supported CLI for it. Where it is absent, `setup_snapshots.py` prints the
exact click path and **exits non-zero**, so "the script printed some advice"
can never be mistaken for "the customer has backups":

```
DSM > Package Center > install 'Snapshot Replication' (free), then:
  Snapshot Replication > Snapshots > pick the shared folder >
  Settings > Schedule:
    - Enable snapshot schedule, run every hour, every day
  Settings > Retention: 'Apply advanced retention policy' >
    - keep 24 hourly (latest 1 day), keep 30 daily (latest 30 days)
  Repeat for the shared folder holding the app stack.
Verify: Snapshots list is non-empty within the hour, and
  ls /volume1/@sharesnap/<share>/ over SSH shows timestamp dirs.
```

DSM snapshots land as an ordinary read-only tree at
`/volume<N>/@sharesnap/<share>/<GMT+NN-YYYY.MM.DD-HH.MM.SS>/`, so a single-file
restore is a plain `cp`. **`cp -a` does not carry a Synology ACL or the owner
— use `synoacltool -copy SRC DST` where that matters.**

---

## 3. The rule: snapshot before privileged operations

> Nothing in `server/` runs `chown -R`, replaces the live app tree, or deletes
> the stack without a point-in-time it can be put back to.

`common.snapshot_before(label, path)` enforces it. It is wired into:

| Script | Before what | Snapshots |
|---|---|---|
| `setup_tree.py` | the remote script's `chown -R` + recursive `chmod` | the tree dataset |
| `install_dashboard_app.py` | step 1 of the deploy — `mv app app.old.<ts>`, the recursive chown, the staging `rm -rf` | the apps dataset |
| `install_dashboard_app.py --recreate` | the same, labelled `recreate`, because the stack DELETE follows | the apps dataset |

**Best-effort by default.** A NAS whose snapshot API answers 403 must not be a
NAS where projects cannot be created, so a failure is a `WARNING` and the
operation proceeds. To make it a wall:

```powershell
python setup_tree.py ... --require-snapshot
python install_dashboard_app.py ... --require-snapshot
# or, for any script, without a flag:
$env:CCSYNC_REQUIRE_SNAPSHOT = "1"
```

With it, a failed snapshot is a refusal (exit 2) with nothing touched.
Recommended for a customer site once §2 is done and verified.

### The dashboard updating ITSELF is the fourth privileged operation

An OTA update applied from Settings -> PACKAGES runs inside the container, so
`server/common.snapshot_before` is not available to it. It takes the same
precaution twice over (`dashboard_update.py`):

1. **Database copies first.** `backup_databases()` copies every database the
   update could migrate - `dashboard.db`, and `broll.db` / `music.db` /
   `ytdl.db` where the deployment has them - into
   `/data/backups/<ts>-<label>/`, e.g. `20260828T101500Z-before-0.7.19`. Each
   copy goes through SQLite's **backup API**, never `shutil.copy`: all of them
   are open in WAL mode by a process still serving requests, and copying the
   `.db` alone silently loses exactly the rows an admin restoring would want.
   Per-database best effort - an index that could not be copied does not stop
   the update, and the result records which ones were skipped and why.
2. **Then a NAS snapshot**, `dashboard_update.snapshot_before()`, on the same
   best-effort terms as `server/common.snapshot_before`. A container cannot
   work out its own dataset (it sees `/data`, not the pool path), so this one
   is told: `DASH_UPDATE_SNAPSHOT_DATASET` plus `DASH_NAS_API_KEY`. Unset, the
   step reports **skipped, and why**, rather than pretending - and the
   `/data/backups/<ts>-<label>/` copies are then the whole recovery path.

Putting a backup back is deliberately NOT part of a code rollback: rolling the
code back is cheap and reversible, restoring a database throws away everything
that has happened since, so it is a separate explicit flag on the rollback
route (Settings -> PACKAGES lists the backups by name and date).
`prune_backups` keeps the newest 3 per label, then trims the directory to 8
entries or 8 GB, and never removes the newest one of all.

**Both dataset names are set by the deploy since 2026-09-03** (CR-140):
`[tree] dataset` and `[apps] dataset` in the site manifest, or, absent, the
installer derives them on TrueNAS from `df --output=source` over the mount
point, which returns blank rather than guessing a name that would send a
snapshot to the wrong place. They reach the container as `DASH_TREE_DATASET`
and `DASH_UPDATE_SNAPSHOT_DATASET`, and the protection panel checks each one
against the NAS's snapshot tasks: blank reads **CANNOT VERIFY**, never
"missing". The environment is baked at container create time, so changing
either needs a `--recreate` (an image-mode deploy implies one). Before CR-140
the finding told the operator to set variables the installer had no way to
set, i.e. to hand-edit a compose file the next deploy overwrote.

---

## 4. Restoring (the shell procedures)

Snapshots are **read-only trees**, so every restore below is a copy out of one.
Nothing here rolls a whole dataset back unless it says so.

**Try Settings -> RECOVERY first** (the callout at the top). For 4a it does
the whole thing without a shell and without the overwrite - it copies into
`<project>/.restored-<ts>/` and leaves the live files alone, so there is no
"is everything since this snapshot expendable" question to answer. What
follows is what to do when the dashboard cannot see the snapshots, when the
restore is larger than a page click should move, or when you want to know
exactly what the page is doing.

### 4a. One file, or one project

TrueNAS — every ZFS snapshot is browsable under the dataset's `.zfs` directory:

```bash
ls /mnt/tank/TheCreatorsPool/.zfs/snapshot/
cp -a "/mnt/tank/TheCreatorsPool/.zfs/snapshot/ccsync-20260817-1400/Creators_Club/Projects/2026/CCT/Season 1/Subs/ep3.srt" \
      "/mnt/tank/TheCreatorsPool/Creators_Club/Projects/2026/CCT/Season 1/Subs/"
chown broll:editors ".../Subs/ep3.srt"
```

Synology:

```bash
cp -a "/volume1/Creators_Club/../@sharesnap/Creators_Club/GMT+08-2026.08.17-14.00.00/Projects/.../ep3.srt" \
      "/volume1/Creators_Club/Projects/.../"
synoacltool -copy "<the live file beside it>" "<the restored file>"   # owner + ACL
```

Never `chmod`/`chown` a restored file on DSM — that deletes the share's ACL for
it. Copy the ACL across instead.

A whole project directory is the same command without the filename. After
restoring a project, re-run `server/setup_tree.py --project-rel-path ...` to
re-apply ownership/ACLs to everything under it.

### 4b. The whole tree

Only after deciding that everything written since the snapshot is expendable.

1. **Stop the fleet writing first.** Pause the sync lanes on every editor
   machine (tray → pause), or stop the Syncthing app/service on the NAS. A
   rollback under live Syncthing means the editors' copies immediately look
   "newer" and start pushing the deleted state back up.
2. TrueNAS: `zfs rollback -r tank/TheCreatorsPool@ccsync-20260817-1400`
   (`-r` destroys snapshots taken *after* the target — read the list first with
   `zfs list -t snapshot -r tank/TheCreatorsPool`).
   Synology: **Snapshot Replication → Snapshots → Restore**, or copy the
   `@sharesnap` tree back by hand for a partial restore.
3. Re-apply ownership: `server/setup_tree.py` per project, or the equivalent
   one-shot chown, since a rollback restores whatever ownership the snapshot
   had.
4. Read §5 before letting the fleet resume.

### 4c. The dashboard's data volume

`dashboard.db` **is** the fleet's provisioning state: projects, editors, ticks,
transfer history. Losing it does not lose footage, but it loses who is allowed
to sync what.

**Look at Settings -> PACKAGES first.** The dashboard backs its own databases
up before every update and can put one back by itself, with no shell and
without the NAS - and an update having gone wrong is what this almost always
is. RECOVERY's "this dashboard has lost projects, editors or their ticks"
question sends you there, and only prints what follows as the fallback.

```bash
# with the container stopped -- the dashboard holds this open
sudo docker stop ix-ccsync-dashboard-dashboard-1        # TrueNAS
# (Synology: docker compose -p ccsync -f <root>/compose.yaml stop dashboard)

# the .zfs directory belongs to the DATASET. If `apps` is a dataset:
sudo cp -a /mnt/tank/apps/.zfs/snapshot/<snap>/ccsync-dashboard/data/dashboard.db \
           /mnt/tank/apps/ccsync-dashboard/data/dashboard.db
# If `apps` is only a folder in the pool root (see the callout in §1), the
# snapshot is the POOL's and there is no /mnt/tank/apps/.zfs at all:
sudo cp -a /mnt/tank/.zfs/snapshot/<snap>/apps/ccsync-dashboard/data/dashboard.db \
           /mnt/tank/apps/ccsync-dashboard/data/dashboard.db
sudo chown 3000:3000 /mnt/tank/apps/ccsync-dashboard/data/dashboard.db
sudo chmod 660 /mnt/tank/apps/ccsync-dashboard/data/dashboard.db
sudo docker start ix-ccsync-dashboard-dashboard-1
```

`dashboard.db` is also WAL-mode: bring its `-wal`/`-shm` along with it, or
bring neither. A `-wal` belonging to a *different* `.db` is how a working
database becomes a corrupt one.

Afterwards the collector reconciles against the NAS on its next cycle; a
project whose folder exists but whose row was lost is re-discovered from its
`.ccsync-project` marker. **Editor↔project ticks are not re-discoverable** —
they only exist in `dashboard.db` and in the Syncthing folder shares, so check
the Projects page against Syncthing's device list after a restore.

### 4d. The search indexes

Prefer the publish script's own rollback (§6), which is a rename and takes a
second:

```powershell
cd server
python publish_db.py --which broll --rollback --apply
```

Falling back to a snapshot: copy `broll.db` / `music.db` out of the snapshot
exactly as in §4a, **with their `-wal`/`-shm` or without any of them**, then
`chown 3000:3000` + `chmod 660` for `music.db` (it is under the apps root), and
leave `broll.db`'s ownership alone on DSM (`synoacltool -copy`).

### 4e. The app code

Not a restore case: `git checkout <tag>` and redeploy. The previous deploy is
also still on the NAS as `<apps_root>/app.old.<ts>` until the next deploy
prunes it.

---

## 5. What Syncthing does after a restore

Lane C (Syncthing) carries project metadata — `.drp`/`.drb` files, subtitles,
notes — and it has two safety settings that change how a restore behaves:

- **`ignoreDelete: true` on every NAS-side folder** (2026-08-11,
  `docs/delete-protection-ignoredelete.md`). The NAS copy is authoritative and
  never applies a delete an editor made. So restoring a deleted file on the NAS
  *does* propagate out to editors, and an editor deleting it again only removes
  their own copy.
- **Staggered versioning, `maxAge` 1 year, at `.stversions/`** inside each
  folder on the NAS. Before reaching for a snapshot, look there: a file an
  editor overwrote an hour ago is usually still in `.stversions/` with a
  timestamp in its name.

Three consequences that bite:

1. **A whole-tree rollback under a live fleet fights the fleet.** Editors'
   copies are newer than the restored ones, so they push the pre-restore state
   back up. Pause the lanes first (§4b step 1).
2. **`.stversions/` is inside the folder and is snapshotted with it.**
   Staggered versioning does thin it out and does drop versions past `maxAge`,
   but `maxAge` on the NAS side is a **year** (`provision.py`,
   `setup_syncthing_folder.py`: `31536000`), so for pool-sizing purposes treat
   it as a year of every overwrite. Include it when sizing a pool.
3. **A restored file gets a new mtime.** Syncthing will re-send it to every
   editor who has that project ticked; a large restore is a real WAN transfer,
   not a metadata update.

`.ccsync-trash` on editor machines (lane B's `--backup-dir`) is **not** part of
this story: it is on the editor's own disk, it is never snapshotted, and it is
**pruned**. Since the CR-48 era `lane_guard.prune_trash` runs at the end of a
healthy lane B pass, at most every 6 h, and drops any batch older than
`trash_max_age_days` (**14**, `lane_guard.DEFAULT_TRASH_MAX_AGE_DAYS`), then
the oldest batches until what remains is under `trash_max_bytes` (**50 GB**) -
never the newest batch, and nothing at all while the breaker is tripped.
`docs/SYNC_SAFETY.md` section 2 is the full description. So it is a **14-day
undo window on one machine**, not a backup: if the answer to "can I get that
file back" is more than a fortnight old, the answer is a NAS snapshot (§4a),
not that folder. (This paragraph said "never pruned" until 2026-09-04, SYS-9
of the 09-03 sweep; it was wrong in the dangerous direction - an admin was
told to look for a copy that had been swept a fortnight earlier.)

---

## 6. Publishing a search index (`broll.db`, `music.db`)

The old recipe was one line in `broll/HANDOFF.md`:

```
copy E:\broll-queue\broll.db "P:\Assets\B-roll Archive\broll.db"
```

A plain file copy, over SMB, **on top of a WAL-mode SQLite database the
dashboard container holds open read-write**. Three ways to lose the index at
once: the live file's `-wal`/`-shm` survive the copy and then belong to a
database that no longer exists; the container's open handle points at bytes
being overwritten under it; and a truncated copy *is* the live index, with
nothing to go back to.

`server/publish_db.py` is that procedure, as code:

```powershell
cd server
python publish_db.py --which broll                 # dry-run (the default)
python publish_db.py --which broll --apply
python publish_db.py --which broll --source E:\broll-queue\broll.db --apply

python publish_db.py --which music --apply
```

What it does, in order:

1. `PRAGMA wal_checkpoint(TRUNCATE)` on the **source**, so everything the
   indexer committed is in the `.db` file (only the `.db` is shipped).
2. A consistent local snapshot via SQLite's own `backup()` API — safe even
   while the indexer is mid-write.
3. `PRAGMA quick_check` + row counts on that snapshot, locally.
4. Row counts of the **live** index, read through the dashboard container, and
   a refusal if a content table lost more than 10 % of its rows
   (`--shrink-pct`, `--allow-shrink`). That catches a half-finished indexer run
   and the wrong `--source`.
5. SFTP to a fresh staging dir, size-verified against what was sent.
6. `cp -a` to `<target>.new` — beside the live file, on the same filesystem, so
   the rename in step 8 is atomic.
7. **`PRAGMA quick_check` on the candidate, on the NAS**, through the
   container's own python3 (falling back to a host python3). If neither can
   answer, the publish **fails** and the live index is untouched. A database
   that is the right size and structurally broken is exactly what the old copy
   produced.
8. `mv <target> <target>.prev-<ts>` — with its `-wal`/`-shm`, which move with
   the file they belong to (SERVER-7) — then `mv <target>.new <target>`. The
   rename rolls back if it fails.

Roll back (a rename, seconds):

```powershell
python publish_db.py --which broll --rollback --apply
python publish_db.py --which broll --rollback --from-prev "<explicit .prev path>" --apply
```

Finding the newest `.prev-<ts>` is a **privileged** listing (server-1,
2026-08-21): both target directories are group-only (`2770` for the b-roll
archive, `770` for `music-data`) and the admin account cannot traverse either,
so the listing runs under `sudo` like every other filesystem probe in this
package. A directory that could not be *read* is now reported as exactly that,
and no longer as "there is nothing to roll back to". Without `--apply` the
rollback prints the listing command and the rename it would do; it does not
touch the NAS, so it cannot name the actual `.prev` yet.

`.prev-<ts>` files are **never deleted automatically**: unlike code, a database
that has been live may have rows the copy replacing it does not. Prune them by
hand when a pool gets tight.

### Does the running app notice? (`music-2`, 2026-08-21)

A publish and a rollback are both a **rename**, and a rename replaces the file
the *path* names while every already-open handle goes on reading the unlinked
old inode. That matters differently for the two indexes:

- **`music.db` — it notices by itself, on a current deployment.** `musicweb`
  stats the file once per connection (`db._check_swapped`) and fingerprints it
  plus its `-wal` for the derived search matrices (`db.file_state`), so a
  swapped index is picked up within a request or two, with a `WARNING` line
  naming the path. Before that, long-lived worker threads answered browse,
  facets, audio lookups and search from the deleted inode **indefinitely** —
  anyio reuses the most recently idle thread and the page polls every 2 s.
- **An OLDER deployment does not**, and neither does a `music-web` tree that
  was shipped before this landed. There the remedy is what the runbook used to
  say and nothing told anyone to do: `POST /music/api/reload`, or restart the
  dashboard container.
- **`broll.db`** reopens per connection, so a rename is normally enough.
  Restart the container if it does not pick it up.

Publishing does not require a restart in either case. If you are unsure which
deployment you are on, restarting the container is always correct and costs a
few seconds of the dashboard.

### Before publishing `music.db`

Editors queue uploads into the **NAS's** copy (`ingest_queue`), not the base
rig's. Drain them first or they are overwritten — `music/web/DEPLOY.md` has the
pull/drain/push loop. `publish_db.py` deliberately does not count
`ingest_queue` in the shrink check, precisely because those rows exist only on
the NAS.

### On DSM

`broll.db` lives inside the tree share, where a `chown` or `chmod` destroys the
ACL. The publish therefore emits neither there, and carries owner and ACL
across from the file being replaced with `synoacltool -copy`. `music.db` is
under the app root, so it keeps the deploy's `3000:3000 660`.

Step 5 stages under **`<apps_root>/staging`**, not `/tmp` (server-5,
2026-08-21). DSM chroots every SFTP account, the administrator included, to its
share view, where `/tmp` does not exist — every `--apply` used to abort at the
transfer with the live index untouched. The dashboard deploy has staged code
there since the first DSM bring-up; the publish does now too, and creates the
directory if the stack was installed by hand.

---

## 7. Verifying, on a schedule

Monthly, and after any change to storage:

```powershell
cd server
python setup_snapshots.py --list --apply   # non-empty, newest within the hour,
                                           # and every target schedulable
python check_health.py                  # the fleet's own checks
```

Yearly, or before a customer handover — **actually restore something**. A
backup nobody has restored from is a hypothesis.

Since 2026-08-29 (SYS-15d) the dashboard does this itself: **Settings ->
RECOVERY -> [ REHEARSE A RESTORE NOW ]** copies one real file out of the
newest snapshot into a scratch folder under `/data`, compares it byte for
byte, deletes it, and records the date. That date is the protection panel's
"somebody has actually restored from a backup this year" line, which reads
`[ MISSING ]` until something records one - a drill that fails records
nothing, deliberately.

By hand, on a deployment the dashboard has no snapshot mount on:

1. pick a file from a project, note its size and hash;
2. restore it out of a snapshot into a scratch directory (§4a);
3. compare; delete the scratch copy;
4. record it on Settings -> PROTECTION with [ RECORD A RESTORE ], or the
   panel goes on saying nobody ever has.

---

## 8. What is deliberately not here

- **Offsite / second-copy replication.** Per-customer, and a real cost
  decision. TrueNAS: Data Protection → Replication Tasks to a second box or a
  cloud target. DSM: Snapshot Replication to another Synology. Both replicate
  the snapshots this document configures, so setting them up is additive.
- **Syncthing's config volume** (OPS-22, 2026-09-03). Named in §1 as NOT
  covered rather than quietly omitted: on TrueNAS it belongs to a catalog app
  whose `ix_volume` lives on the Apps pool, outside anything this document
  schedules, and taking a periodic snapshot of somebody else's app volume is
  not something these scripts will do behind an operator's back. **The
  recovery path if it is lost is re-pairing, not restoring:** re-run
  `python server/install_syncthing_app.py --site site.toml`, then approve each
  editor's device again - Settings ▸ Users ▸ the pending-devices panel, or
  `python server/accept_device.py --site site.toml --device-id <id>` - and let
  the enforce cycle re-share every ticked project. No footage is at risk in
  that state: the editors' copies and the NAS copy both still exist, they
  simply stop replicating until the pairings are back. If your Apps pool
  itself has a snapshot schedule (TrueNAS ▸ Data Protection), that covers this
  volume, and it is worth ten seconds to check.
- **Backing up editor machines.** `P:` is a replica. Anything an editor keeps
  only on their own disk (Resolve local databases, scratch renders) is theirs
  to back up.
- **Automatic pruning of `.prev-<ts>`.** One per `publish_db.py` run, kept
  forever on purpose: an index publish is the operation with the longest gap
  between "done" and "somebody notices it was wrong", and `--rollback` reads
  the newest one. Sweep them by hand when the archive dataset gets tight.
  (Corrected 2026-09-04, SYS-9: this bullet used to name four things that
  "grow forever" and three of them do not. `app.old.<ts>` is pruned by the
  NEXT successful deploy, most recent kept and never one a container still
  has bind-mounted (OPS-2); `.stversions/` is staggered with a one-year
  `maxAge`; `.ccsync-trash` is pruned at 14 days / 50 GB, section 5.)
- **Automatic pruning of the dashboard's own `/data/backups/`** beyond what
  `dashboard_update.prune_backups` already does: newest 3 per label, then the
  whole directory trimmed to 8 entries or 8 GB, newest first, and never the
  newest of all.
