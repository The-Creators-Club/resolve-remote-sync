# ZERO_DOWNTIME_DEPLOY.md - updating the dashboard without taking it down

Investigation, 2026-09-30. Nothing here is built yet. This is the design and
the case for it, written so a build can start from it.

## 1. What goes down today, and why

There are three ways new dashboard code reaches a running container. All
three stop the old process before the new one can answer.

| Path | Who uses it | What happens | Gap |
|---|---|---|---|
| **OTA code bundle** (`dashboard_update.py`, ZERO_TOUCH_PLAN WP K) | the studio (image mode since 2026-08-18) and every feed customer; unattended under `policy = current` | stage + verify off to the side, then SIGTERM self, exit 75, `run.sh` loops, `select_code_root.py`, new uvicorn boots | drain + shutdown + boot (WP K's estimate: about 10 s) |
| **Image / runtime update** | any change to the venv, the base image or the image's own `deploy/` | the container is recreated from the NAS app manager (or `docker restart` from `install_dashboard_app.py`) | stop + create + boot, plus the image pull if it was not done first |
| **Bind-mount deploy** (`tools\ship.cmd -DashboardOnly`) | legacy sites only | `mv app app.old.<ts> && mv app.new app`, then `docker restart` (the bind mount follows the old INODE, OPS-2, so a restart is the only way the container sees the new tree) | stop + boot |

Where the seconds go on the OTA path, read from the code:

1. **The listener closes first.** uvicorn's shutdown stops accepting
   immediately, then waits for open connections. From that moment every new
   request is refused, and Tailscale Serve (`:9443`, the address editors and
   companions use) answers 502.
2. **The drain has no bound of ours.** `timeout_graceful_shutdown` is unset
   (uvicorn 0.52.3's default is to wait for every connection), and there is
   always a long one open: the Cards agent's `/cards/agent/pending` long poll
   (`?wait=25`), the ytdl progress polls, an admin's open page.
3. **Lifespan shutdown**, in order: watchdog, collector, pinned executor,
   Cards engine pool, feed poller, then `finish_restart` and exit 75.
4. **Boot**: `select_code_root.py` verifies the bundle's signature, a fresh
   Python imports the app and the four mounts (b-roll, music, ytdl, Cards),
   `db.migrate`, the boot-time reconcilers, then uvicorn starts listening.
   uvicorn runs the whole lifespan startup BEFORE it binds (`Server.startup`,
   `await self.lifespan.startup()` comes first), so nothing answers until all
   of it is done.

Measured here (base rig, Windows, warm disk, no mounts configured, fresh
database): **1.1 s** from process start to the first `/api/v1/health`
answer, three runs out of three. That is the floor, not the live figure. The
live figure includes the NAS's slower disk, the four mounts, the migration
and the drain, and it was **not measured** for this document: reading the
container log needs `sudo docker`, which needs the NAS admin password, and
measuring it for real means causing a restart. Section 7 has the one-command
way to measure it during the next ordinary update.

What the gap costs is more than the seconds:

- Every open dashboard tab errors on its next htmx poll (2 s cadence).
- Every Cards phone session loses its engine; the engine is rebuilt lazily
  on the next entry to that episode, and the agent's tunnel reconnects.
- An upload in flight (a package publish, a b-roll ingest, a music push)
  fails and has to be started again.
- A server-side YouTube download in the `ytdl-worker` thread dies with the
  process (which is why WP K refuses to apply while one is running, and why
  an unattended update can be held off indefinitely by a busy queue).
- Companions retry their reports, so sync itself is untouched. That part
  already works and nothing below changes it.

The unattended `policy = current` path makes this matter more, not less: a
customer's dashboard restarts itself at a time nobody chose.

## 2. The options

### A. Hand the listening socket to the new process, inside the container (RECOMMENDED)

PID 1 stops being a shell loop and becomes a small supervisor that binds
`:8480` **once** and keeps the socket for the life of the container. Each
uvicorn child is given that socket instead of binding its own. For an
update, the supervisor starts the NEW child on the SAME socket while the OLD
one is still serving, waits until the new one proves it is healthy, and only
then tells the old one to stop.

The kernel does the rest. There is one accept queue for the socket, not one
per process; while both children are alive either may accept, and when the
old one closes its copy the socket itself stays open because the supervisor
and the new child still hold it. A connection that arrives at any moment of
the switch is queued and answered. This is the same mechanism gunicorn's
USR2 re-exec, systemd socket activation and einhorn use.

It fits this codebase unusually well:

- **uvicorn already supports it.** `Server.serve(sockets=[...])` takes
  pre-bound sockets, and because the lifespan runs before serving, a child
  handed the shared socket takes no traffic until its startup is complete.
  No framework change.
- **The trust rule survives unchanged.** The supervisor is image code
  (`/app/deploy/`, like `select_code_root.py`), never code from `/data/code`.
  The volume tree still gets no vote in whether it is used.
- **A bad bundle stops costing an outage.** Today a bundle that imports but
  cannot serve takes the dashboard down until the boot watchdog reverts it
  two boots later. With a handover, the new child has to pass a health probe
  BEFORE the old one is touched; if it fails, it is killed and the old
  process never noticed. Rollback becomes "do nothing".
- **No Docker socket, no second container, no proxy change.** ZERO_TOUCH
  section 5's rule stands, the `:8480` LAN bind and the `:9443` Serve line
  are untouched, and nothing on a customer's NAS changes shape.

What it does NOT cover: an image update. A new venv or base image is a new
container, and a new container cannot inherit a socket from the old one.
That stays a restart (section 5 says what to do about it).

### B. Blue-green containers behind a switch

Two containers (`dashboard-a` on 8480, `dashboard-b` on 8481), with Tailscale
Serve repointed from one to the other. It is the only option that covers
image updates too, but:

- someone has to create and remove containers, which means the base rig over
  SSH with `sudo docker` (the studio only) or the NAS app manager (a
  customer, by hand), because the dashboard itself may not hold the Docker
  socket;
- `tailscale serve` reconfiguration resets connections in flight, and the
  LAN address `http://192.168.0.102:8480` would have to move between
  containers or become a third thing to switch;
- both containers bind-mount the same `/data`, so every singleton problem in
  section 3 exists here too, across containers instead of across processes;
- memory for two full dashboards for as long as both are up.

It is the right shape for a multi-host deployment, which this is not.
Rejected for now; worth revisiting if image updates become frequent.

### C. A small reverse proxy inside the container

`:8480` answered by a tiny asyncio proxy that forwards to whichever uvicorn
is current on a private port. It can do everything A does, plus hold a
request open across a gap, but it is an extra hop on every request (the
report path runs every 5 s per syncing machine), it has to handle websockets,
Range/206 for music audio and chunked uploads correctly, and it is several
hundred lines of code in the request path. A gets the same result with the
kernel doing the queueing. Rejected.

### D. Make the gap polite instead of removing it

Pages that see a 502/connection error show "the server is restarting, back
in a moment" and retry, instead of the htmx error state; the Cards page does
the same. This is worth doing whatever else is chosen, because an image
update will still restart the container, and it is small. It is not an
answer on its own: uploads and the ytdl worker still die.

## 3. The design for A

### 3.1 The supervisor (`dashboard/deploy/supervise.py`, image code)

- Replaces the image-mode loop at the end of `run.sh`: `run.sh` keeps all its
  checks and then `exec`s the supervisor (bind-mount mode keeps its plain
  `exec uvicorn` until it is retired or migrated; see 3.6).
- Binds `0.0.0.0:$DASH_PORT` once. Also binds one PRIVATE loopback socket
  per child (`127.0.0.1:0`), passed as a second socket, so the supervisor can
  probe a specific child. Probing through the shared port would reach
  whichever child accepted, which proves nothing about the new one.
- Starts a child as `python -m ccsync_dashboard.serve_child --fd N --probe-fd
  M` (a few lines around `uvicorn.Server(config).serve(sockets=[...])`),
  with `pass_fds`, the PYTHONPATH `select_code_root.py` printed, and
  `timeout_graceful_shutdown` set (proposed 30 s: longer than the 25 s long
  poll, shorter than Docker's own kill).
- On SIGTERM/SIGINT (`docker stop`): forwards to the current child, waits,
  exits with its code. On SIGCHLD from an unexpected death: restarts it the
  way `restart: unless-stopped` would, with the same boot-attempt counting
  `select_code_root.py` already does.
- On **SIGHUP** (the handover request): section 3.2.

Stdlib only, no import from `ccsync_dashboard`: it runs before and between
the children, and a supervisor that imports the app would reload the app's
bugs into PID 1.

### 3.2 The handover, step by step

1. The app finishes staging exactly as it does today (download, sha256,
   signature, extract, stage-verify on database copies, back-ups,
   `current.json`). Instead of SIGTERM-self-and-exit-75 it sends **SIGHUP to
   PID 1** (same uid, so this is allowed) and keeps serving.
2. The supervisor re-runs `select_code_root.py` and starts child B on the
   shared socket, with `CCSYNC_HANDOVER=1` in its environment.
3. B runs its lifespan startup: imports, `db.migrate` (3.4 says when it may),
   reconcilers. It does NOT start any singleton (3.3); those wait for a lease.
   Only after the lifespan completes does uvicorn start accepting, on both
   sockets.
4. The supervisor probes B's private socket: `/api/v1/health` must answer
   200 with the version `current.json` names, retried for up to the existing
   `BOOT_HEALTH_PROBE_SECONDS` (45 s). A few page routes are worth probing
   too (REL-6's lesson: a tree that imports and 500s every page passed
   stage-verify).
5. **Probe passes:** the supervisor SIGTERMs A. A stops accepting (its copy
   of the socket closes; the socket stays open), finishes in-flight requests
   within the graceful timeout, runs its lifespan shutdown, stops its
   singletons and releases the lease. B's lease waiter wins and starts them.
6. **Probe fails, or B exits:** the supervisor kills B and records why in
   `update_state.json`; `current.json` goes back to the previous entry (the
   watchdog's revert, done at once instead of two boots later). A was never
   touched. The Packages page shows the failure the same way it shows one
   today.

The window in which new connections can be refused is **zero**. The window
in which background work is not running is A's drain plus its shutdown,
bounded by the graceful timeout.

### 3.3 Singletons: one lease, held by one process

Two processes will be alive at once, so everything that must run once per
dashboard has to be behind one lock. A `fcntl.flock` on
`/data/singletons.lock`, taken by a thread in B that blocks until A's
shutdown releases it (the kernel releases a flock when a process dies, so a
crashed A cannot strand it). The inventory, read from the tree on
2026-09-30:

| Singleton | Where | Why it must be single |
|---|---|---|
| collector + its watchdog | `collector.py`, `app.CollectorWatchdog` | alerts, prune, enforce cycle, notices: two would double-send mail and race the Syncthing enforce |
| pinned executor | `cards_exec.py` | claims jobs; `release_pinned_jobs` at boot would release A's live ones |
| Cards engine pool | `cards_pool.py` | engines own `<data>/cards/<slug>`, whose `project_pick.doc_save` is a read-merge-write through a fixed `.tmp` |
| release feed poller | `release_feed.py` | would apply the same update twice |
| code-boot watchdog | `dashboard_update.start_boot_watchdog` | clears `boot_attempts.json` |
| ytdl worker + canary | `ytdlweb/worker.py`, `ytdl_canary.py` | job leases are in the DB, but two workers double the NAS's download load |
| triage scheduler + reply poller | `triage.py` | would mail two reports and act on a reply twice |
| CLI auto-update | `cli_tools.py` | two installs into one `<data>/tools/<tool>/` |

Two consequences worth stating:

- **Boot-time "release what the previous process held" steps must move
  behind the lease** (`release_pinned_jobs`, `reconcile_file_moves`). Run
  from B's lifespan while A is alive, they would release or finish work A
  is still doing. They were written for "the previous process is dead", and
  under a handover that is only true once the lease is held.
- **A Cards request that reaches B before the lease** waits for it for a
  bounded time and then answers 503 with `Retry-After`, the same answer the
  pool already gives when every engine slot is busy. The Cards landing page
  needs no engine and answers throughout. The agent's `/pending` long poll
  ending with A is normal: the agent reconnects and reaches B.

A new singleton added later must take the lease too; a test that walks
`threading.enumerate()` after lifespan startup under `CCSYNC_HANDOVER=1` and
fails on any unlisted long-lived thread is the way to keep that true.

### 3.4 Migrations: old code has to keep working on the new schema

A is serving while B migrates the live database. SQLite in WAL mode is fine
with two processes, and a prepared statement re-prepares on a schema change,
so the mechanics hold. The question is whether A's code still works on B's
schema.

- **Additive steps are safe**: a new table, a new nullable column, a new
  index. Most of `_MIGRATION_STEPS` is this.
- **Rebuild steps are not**: v11 (`companion_packages`) and v24
  (`selections`, `editor_prefs`) drop and rename tables. Old code reading a
  table mid-rebuild, or writing a column the rebuild dropped, breaks.

So each step gets a flag, `online_safe`, default **False**. B computes the
pending steps before migrating; if any is not online-safe it tells the
supervisor "cold restart needed" (a distinct exit code) and the supervisor
falls back to today's stop-then-start, with the Packages page saying "this
update needs a short restart" before the admin presses anything. A test pins
that no step containing `DROP`, `RENAME` or a table rebuild is marked safe.
The same applies to `broll.db`'s and `music.db`'s own migrations, which run
in the mounted apps.

One more thing has to change for rollback to stay possible. `db.migrate`
refuses to boot on a schema newer than it knows (`user_version` check,
db.py). After a handover whose B migrated and then failed its probe, A keeps
running (fine), but A's NEXT boot would refuse the newer schema. Record the
lowest version whose code can run the database (`meta.schema_floor`, raised
only by a step that is not online-safe) and refuse only when the floor is
above what this build knows. Only builds that carry this rule benefit, so it
has to ship one release before the first handover is relied on.

This is the classic expand/contract rule and it constrains how migrations
are written from now on: a column is dropped one release after the code stops
reading it, never in the same one.

### 3.5 The ytdl refusal becomes a wait

Today an apply is refused while a YouTube job runs (unless forced), because
the restart kills it. Under a handover, A finishes in-flight HTTP requests,
but the worker thread's download is not a request. The worker is a singleton,
so the choice is: A's shutdown waits for the current download up to a bound
(the graceful timeout is too short for a long download), or the job is
released back to the queue and B's worker resumes it (yt-dlp resumes a
partial). The second is simpler and matches the lease model the job queue
already has. To decide at build time.

### 3.6 Bind-mount mode

The handover cannot see new code in bind-mount mode: the container's `/app`
is the old inode after the base rig's rename (OPS-2), so only a container
restart makes the new tree visible. It could be made to work (mount the
parent directory and switch a `current` symlink), but every live site is in
image mode and bind-mount is the legacy path. Recommendation: leave it as it
is and say so; retiring it is a separate decision.

### 3.7 Memory

For the seconds of overlap there are two processes. The Cards engines are
the big item (measured 2026-09-14: +128 MB and 15 threads per engine), and B
builds none until it holds the lease, by which time A has stopped its own.
The music text encoder is the other: if it loads at import rather than on
first query, B should defer it too. The NAS has room for one extra
dashboard's worth of Python for a minute; this is a note, not a blocker.

## 4. Work packages

| WP | What | Size |
|---|---|---|
| ZD-0 | **Measure the live gap** before building anything (section 7), so the win is a number | an evening |
| ZD-1 | `online_safe` on every migration step (dashboard, broll, music), `schema_floor`, the refuse-rule change, the pinning test. Ships alone, one release ahead of ZD-3 | small |
| ZD-2 | the singleton lease and moving every singleton and "release the previous process's work" step behind it; the thread-inventory test | medium, the careful part |
| ZD-3 | `supervise.py` + `serve_child`, `run.sh` hand-off, SIGHUP from `dashboard_update` in place of exit 75, the cold-restart fallback, graceful timeout. Needs a new image (the supervisor is image code), so it rides the next runtime update | medium |
| ZD-4 | Packages page: "applies without a restart" vs "needs a short restart", and the probe-failure report | small |
| ZD-5 | option D: pages and the Cards page retry politely through a 502 instead of showing an error | small, independent, worth doing first |

Tests: the supervisor and fd passing are Linux-only (`os.set_inheritable`,
`pass_fds`, SIGHUP), so they run in CI's Linux job and are skipped on the
Windows base rig, the same way the `server/` suite's shell tests depend on
where they run. One integration test is worth its cost: start the
supervisor, hammer `/api/v1/health` from a thread, trigger a handover, and
assert zero refused connections and a version change.

## 5. What still restarts, and what to do about it

- **An image (runtime) update** recreates the container. Keep it rare by
  keeping dependency changes batched, pull the image before recreating (the
  deploy already can), and let ZD-5 make the gap polite. If image updates
  ever become frequent, option B is the route.
- **An update whose migration is not online-safe** takes the cold path,
  announced in advance.
- **The supervisor itself** changes only with the image.

## 6. Risks and open questions

- **A singleton missed in the inventory** runs twice for the length of the
  overlap. The thread-inventory test is the guard; the table in 3.3 is the
  starting list, not a proof.
- **In-memory state that is not a thread**: caches, rate-limit counters,
  anything a module keeps in a global. Most state here is in SQLite on
  purpose (`SYNC_SAFETY.md`'s "never in-memory only" rule), but an audit of
  module-level mutable globals belongs in ZD-2.
- **The unattended path** (`policy = current`) gets safer, since a bad
  bundle no longer takes the dashboard down. The soak rule stays.
- **Is the ytdl job resumed or waited for** (3.5): open.
- **Is the live gap big enough to matter?** If ZD-0 measures a couple of
  seconds and nobody notices it, ZD-5 alone may be the proportionate answer,
  and the rest of this plan waits. The Cards engine loss and the killed
  uploads are the argument that it matters regardless of the seconds.

## 7. Measuring the live gap (ZD-0)

During the next ordinary OTA apply, from any machine on the tailnet:

```bash
# one line per 100 ms; count the non-200 lines afterwards
while :; do
  printf '%s %s\n' "$(date +%T.%N | cut -c1-12)" \
    "$(curl -s -o /dev/null -m 2 -w '%{http_code}' https://truenas.tail26290e.ts.net:9443/api/v1/health)"
  sleep 0.1
done | tee gap.log
```

The run of non-200 lines is the outage as editors see it through Serve. Run
it once more against `http://192.168.0.102:8480/api/v1/health` to separate
the dashboard's own gap from anything Serve adds.

## Related

- `ZERO_TOUCH_PLAN.md` WP K: the OTA code update this builds on, and
  section 5's "no Docker socket" rule it keeps.
- `DOCKER.md`: image mode vs bind-mount mode, the Serve recipe.
- `RELEASE.md`: the image-mode release flow and the `policy = current` soak.
- `CARDS_TWO_PROJECTS.md`: the engine pool and why eviction leaks threads.
- `SYNC_SAFETY.md`: why latches and state live on disk.
