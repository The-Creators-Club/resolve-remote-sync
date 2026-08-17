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

---

## 1. What is protected, and what protects it

| What | Where it lives | Protected by |
|---|---|---|
| The project tree (all footage, projects, renders) | `<pool_root>/<tree_name>/Projects` | NAS snapshots (below) + Syncthing `ignoreDelete` + staggered versioning |
| The shared asset libraries (LUTs, stills, music, b-roll archive) | `<tree_name>/Assets/...` | NAS snapshots + Syncthing versioning (LUTs/Stills only) |
| `dashboard.db` — projects, editors, ticks, transfer history | `<apps_root>/data/dashboard.db` (container: `/data`) | NAS snapshots of the **apps** dataset |
| `broll.db` — the b-roll search index | `<tree_name>/Assets/B-roll Archive/broll.db` | NAS snapshots + the `.prev-<ts>` a publish leaves behind |
| `music.db` — the music index (incl. editors' queued ingests) | `<apps_root>/music-data/music.db` | NAS snapshots + `.prev-<ts>` / `.old.<ts>` |
| `ytdl.db` | `<apps_root>/ytdl-data/ytdl.db` | NAS snapshots of the apps dataset |
| The deployed app code | `<apps_root>/app` | git, plus `app.old.<ts>` from the last deploy |
| An editor's local copy | `P:\` on their machine | **Nothing.** It is a replica, not a backup. |

Two datasets carry everything that matters: the **tree** dataset and the
**apps** dataset. Both are snapshotted on the same schedule.

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
python setup_snapshots.py --list
```

which prints, per dataset, how many snapshots exist and the newest one. **That
listing is the check that backups are working — not the exit code of the
configure run.**

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

---

## 4. Restoring

Snapshots are **read-only trees**, so every restore below is a copy out of one.
Nothing here rolls a whole dataset back unless it says so.

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

```bash
# with the container stopped -- the dashboard holds this open
sudo docker stop ix-ccsync-dashboard-dashboard-1        # TrueNAS
# (Synology: docker compose -p ccsync -f <root>/compose.yaml stop dashboard)

sudo cp -a /mnt/tank/apps/.zfs/snapshot/<snap>/ccsync-dashboard/data/dashboard.db \
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
2. **`.stversions/` is inside the folder and is snapshotted with it** — it also
   grows forever and nothing prunes it. Include it when sizing a pool.
3. **A restored file gets a new mtime.** Syncthing will re-send it to every
   editor who has that project ticked; a large restore is a real WAN transfer,
   not a metadata update.

`.ccsync-trash` on editor machines (lane B's `--backup-dir`) is **not** part of
this story and is never pruned — that is a companion-side item, tracked
separately.

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

`.prev-<ts>` files are **never deleted automatically**: unlike code, a database
that has been live may have rows the copy replacing it does not. Prune them by
hand when a pool gets tight.

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

---

## 7. Verifying, on a schedule

Monthly, and after any change to storage:

```powershell
cd server
python setup_snapshots.py --list        # non-empty, newest within the hour
python check_health.py                  # the fleet's own checks
```

Yearly, or before a customer handover — **actually restore something**. A
backup nobody has restored from is a hypothesis:

1. pick a file from a project, note its size and hash;
2. restore it out of a snapshot into a scratch directory (§4a);
3. compare; delete the scratch copy.

---

## 8. What is deliberately not here

- **Offsite / second-copy replication.** Per-customer, and a real cost
  decision. TrueNAS: Data Protection → Replication Tasks to a second box or a
  cloud target. DSM: Snapshot Replication to another Synology. Both replicate
  the snapshots this document configures, so setting them up is additive.
- **Backing up editor machines.** `P:` is a replica. Anything an editor keeps
  only on their own disk (Resolve local databases, scratch renders) is theirs
  to back up.
- **Automatic pruning of `.prev-<ts>`, `app.old.<ts>`, `.stversions/` or
  `.ccsync-trash`.** All four grow forever, on purpose in three cases and as an
  open defect in the fourth (`.ccsync-trash`, companion-side).
