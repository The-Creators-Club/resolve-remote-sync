# Pre-launch resilience review, lens `res-time-scale` (2026-10-06)

Read-only review of the working tree at 08b40eb plus the uncommitted changes.
Lens: time and scale. That covers clock skew (editor vs NAS), DST and
timezones in schedules, expiring halts, tokens and leases, and calendar edges.
On the scale side it covers 50 editors, 500k files, 10 TB projects, 100k
b-roll clips, multi-GB SQLite, large reports, and dashboards that run for
months.

**What I read:** `db.prune` and every table's retention, the report caps
(`api._truncate_report_sections`, `app._BODY_LIMITS`), `fetch_sync_backlog`
and its callers, the owed-files cache, the alerts weekly, heartbeat and triage
schedulers (DST handling via `ZoneInfo`), lease expiry, the session store, the
client-share expiry, the clock-skew path on both sides (`reporter._note_clock_skew`,
`health._why_sentence`, `alerts._check_clock_skew`), the companion's lane A,
lane B and proxy-gen age gates, the manifest walk, the supervisor relaunch
window, crash and journal retention, module-level caches and thread creation in
the dashboard, the Cards pool, b-roll semantic search, and snapshot policy.

**What I probed** (throwaway scripts in the session scratchpad, no live system):
- `probe_backlog.py` built a synthetic dashboard DB: 50 machines, 6 ticked
  projects each, and 20k proxies + 20k originals per project on the NAS. It
  then timed `fetch_sync_backlog`, `build_transfers_view` and the owed-files
  count.
- `probe_semantic.py` timed `SemanticSearch._ensure_index` over 500k 384-dim
  embeddings and measured its memory.

**What I found already handled** (and so did not report): the weekly and
triage slots across DST, halt expiry and its alert, the supervisor window under
clock jumps (it uses `abs`), retention on almost every table, server-clock
retention predicates (SYS-4), report truncation instead of rejection (B6), and
completion-poll budgets.

**What I did NOT get to:** Syncthing's own memory and CPU at 500k files across
50 devices on the NAS, report-handler write-lock time at 50 machines, the
music CLAP index (same shape as b-roll, not measured), and the Resolve
media-pool walk cost at 10k+ clips (needs Resolve).

### res-time-scale-1 - The fleet-wide owed-files diff costs about 6 s per call at 50 editors, and the admin home page asks for it every 2 s
- **Severity:** high
- **Confidence:** CONFIRMED (measured)
- **Where:**
  - `dashboard/src/ccsync_dashboard/db.py:11098` (`fetch_sync_backlog`)
  - `dashboard/src/ccsync_dashboard/api.py:975-1060` (`_OWED_CACHE`, `_owed_inputs_fingerprint`, `_count_owed_files`)
  - `dashboard/src/ccsync_dashboard/ui_home.py:423`
  - `dashboard/templates/fleet.html:99-100`
  - `dashboard/src/ccsync_dashboard/alerts.py:1142`
- **What:** `fetch_sync_backlog` runs two `NOT EXISTS` diffs per (machine,
  ticked project), and each diff walks every NAS file of that project.
  - **Admin home.** When an admin opens the home page with no `?as=`, the call
    covers the whole fleet. `/partials/home-transfers` polls it every 2 s.
  - **Owed-files count.** The fleet grid, `/account` and the alerts cycle all
    use this count. It has a 15 s TTL cache, but the cache only hits when its
    fingerprint is unchanged. The fingerprint is `SELECT *` over
    `editor_media_project`, which includes `reported_at`, and every machine
    rewrites that row at least every 600 s (`SECTION_RESEND_SECONDS`).
  - **Measured.** With 50 machines, the fingerprint changes about every 12 s,
    so at fleet scale the cache almost never hits. There is no single-flight
    on a miss, so concurrent pages all recompute.
  - On this desktop, with 50 machines x 6 projects x 20k files:

    | Call | Time |
    |---|---|
    | `fetch_sync_backlog` (admin scope) | 5.9-7.0 s |
    | `build_transfers_view` (admin scope) | 6.6 s |
    | `_owed_files_by_machine` | 5.6 s |
    | one editor's scope | 0.1 s |

    A NAS CPU will be slower.
- **Scenario:** A 50-editor customer with 10 TB projects (about 20k clips
  each). The owner leaves the home page open. Each tab keeps a threadpool
  worker and a core busy without a break. Every `/account` and fleet-grid
  refresh adds another 6 s computation. The collector's alert cycle spends
  about 6 s per cycle on the same count.
  - **Effect.** The dashboard slows for everyone, including the report
    endpoint that keeps the fleet grid live.
  - **Second-order (PLAUSIBLE).** Several admin tabs or admins overlapping
    6 s readers mean the WAL may never find a reader-free moment to reset, so
    `dashboard.db-wal` can grow until a quiet period comes.
- **Recommendation:**
  - Keep per-(editor, machine, project) owed counts up to date at write time.
    `replace_nas_media` and `replace_editor_media` already know exactly which
    pair or project changed.
  - Key the cache on a generation counter bumped by those writers, not on row
    contents that include `reported_at`. Add single-flight.
  - Give `/partials/home-transfers` admin scope only live transfers (the
    cheap half), and `hx-sync="this:drop"`. Leave the queued totals on the
    /transfers page with a slower poll.
- **Known:** not recorded. `ops-efficiency-*` and `logic-sync-truth-5`
  introduced the cache, but its fingerprint defeats it at fleet scale.

### res-time-scale-2 - The b-roll semantic index is rebuilt whole, in the dashboard process and under a lock, after every ingest write: 7 s and 1.7 GB peak at 500k embeddings
- **Severity:** medium
- **Confidence:** CONFIRMED (measured)
- **Where:**
  - `broll/web/app/semantic.py:207-250` (`_ensure_index`), `:318`
  - `broll/web/app/routes_ingest.py:289`
  - `broll/web/app/ingest_batches.py:1141,1336` (`bump_search_generation`)
- **What:** The cache key includes `meta.search_generation`, which every
  ingest write bumps. The next search then does a `fetchall()` of every
  embedding blob and copies it into a new float32 matrix, while holding
  `self._lock`, inside the dashboard container (`/broll` is mounted
  in-process).
  - **Measured at 500k x 384:** 7.1 s rebuild, 860 MB held, 1.73 GB peak
    (rows plus matrix).
  - **Extrapolated to 100k clips at ~10 vectors each (1M embeddings):**
    about 14 s, about 1.7 GB held, about 3.5 GB peak.
  - During a live ingest (local Qwen indexing posts clip by clip), nearly
    every search pays the full rebuild, and every concurrent search queues
    behind the lock.
- **Scenario:** A customer with a 100k-clip archive keeps indexing new shoots.
  Editors searching get 10-15 s answers. The dashboard process repeatedly
  allocates several GB. On a NAS with modest RAM (or a container memory
  limit), it can be OOM-killed. That takes down the sync dashboard with it, so
  "the dashboard is what tells everyone whether their footage is syncing" is
  outranked by search.
- **Recommendation:**
  - Append new rows incrementally (rows above the high-water mark) and
    rebuild only on deletes or replacements.
  - Stream rows instead of using `fetchall()`. Consider float16 or a
    memory-mapped matrix.
  - Rebuild on a background thread and swap atomically, serving the old
    index meanwhile.
  - Publish a measured memory ceiling per 100k clips in the install docs. The
    music CLAP index (`music/web/musicweb/db.py:341-365`) has the same shape
    and should be checked the same way.
- **Known:** BROLL-17 and R2 cover correctness of the key, not cost.

### res-time-scale-3 - Footage with a future mtime (camera clock ahead or in another timezone) is never uploaded by lane A, and never proxied, until the clock catches up, and nothing says so
- **Severity:** medium
- **Confidence:** CONFIRMED (code path; rclone `--min-age` excludes modtime > now - age)
- **Where:**
  - `companion/src/ccsync_companion/sync/rclone_lane.py:2042` (lane A `--min-age 120s`), `:6792` (express gate)
  - `companion/src/ccsync_companion/proxy_scan.py:446` (`if mtime > cutoff: continue`)
  - `companion/src/ccsync_companion/proxy_gen.py:1836`
- **What:** All three "settle" gates compute age as `now - mtime`.
  - A file whose mtime is in the future counts as "still being written" for
    as long as it stays in the future.
  - FAT/exFAT card timestamps come from the camera's clock. They are often
    hours out (a camera left on another country's time) and sometimes years
    out. Explorer and Finder copies keep that mtime.
  - **Lane A:** the periodic `rclone copy` excludes the file. The express
    path defers it, then hands it to the periodic pass, which excludes it
    again. The lane reports green with nothing transferred.
  - **proxy_scan:** the clip is not even counted as a proxy gap, so no proxy
    is made.
  - The dashboard's upload backlog does list the file as owed, but no surface
    says why it is not moving.
- **Scenario:** A documentary shot in Taiwan with the camera on local time,
  ingested by an editor in Europe. Every clip is 7-8 hours in the future, so
  no upload and no proxies until evening, with the tray green. With a camera
  clock a year ahead, the footage stays only on that laptop for a year.
- **Recommendation:**
  - Treat `mtime > now + small tolerance` as "future-dated". For those, use
    the size-stability check alone, which the express path and `_still_growing`
    already implement.
  - Count future-dated files and report them (tray line, guard key, a grid
    chip naming the clip and how far ahead it is).
  - For the periodic pass, list future-dated files into the express path's
    `--files-from-raw` set rather than relying on `--min-age`.
- **Known:** not recorded.

### res-time-scale-4 - Past 2000 files per project, the per-file sync truth turns permanently "uncertain", and at commercial project sizes that is every project
- **Severity:** medium
- **Confidence:** CONFIRMED
- **Where:**
  - `companion/src/ccsync_companion/manifest.py:36` (`MAX_PER_FILE_ENTRIES = 2000`, first 2000 in `os.walk` order)
  - `dashboard/src/ccsync_dashboard/db.py:37` (`EDITOR_MEDIA_CAP`), `:11055-11095`, `:11160-11260`
- **What:** The companion lists at most 2000 originals and 2000 proxies per
  ticked project, in walk order. It does not prioritise files the NAS lacks,
  or the newest ones.
  - Once a project passes 2000 files of either kind, the dashboard can no
    longer prove that nothing is owed for that pair:
    - the upload row is flagged `uncertain` (logic-sync-truth-2);
    - the proxy row becomes a rollup lower bound with no names
      (bug-dash-db-2).
  - Both are honest, but a 10 TB project of ~500 MB clips is about 20k
    files. At customer scale, "Safe to close" and the per-file queue never
    give a definite answer on any big project.
  - The owed upload is also counted only within whichever 2000 the walk
    happened to list, so the number shown undercounts.
- **Scenario:** An editor finishing a shoot asks the dashboard whether it is
  safe to close the laptop. Every large project reads "cannot tell" forever,
  and editors learn to ignore it, which is the cry-wolf outcome the feature
  was built to avoid.
- **Recommendation:**
  - Spend the 2000 slots on the files that matter. List originals newest
    first (they are the ones possibly not yet uploaded), and send a
    per-directory digest (count, bytes, max mtime) for the rest, so the server
    can compare directories without the names.
  - Alternatively, have the companion send only files not confirmed on the
    NAS: it can ask `GET /files/locate` or keep the last NAS inventory hash.
- **Known:** the cap mechanics are known (CR-314, bug-dash-db-2,
  logic-sync-truth-2). Its consequence at commercial project sizes is not
  recorded as an open item.

### res-time-scale-5 - A wrong NAS clock turns the whole fleet red with "this computer's clock is out", and the remedy text tells 50 editors to fix clocks that are correct
- **Severity:** medium
- **Confidence:** CONFIRMED
- **Where:**
  - `companion/src/ccsync_companion/reporter.py:794-822`
  - `companion/src/ccsync_companion/tray.py:159,3620-3636`
  - `companion/src/ccsync_companion/app.py:7808-7815`
  - `dashboard/src/ccsync_dashboard/health.py:709-715`
  - `dashboard/src/ccsync_dashboard/alerts.py:1628-1648`
- **What:** Skew is measured as editor clock minus the dashboard's
  `received_at`. Nothing anywhere checks the server's own clock (no NTP
  status, no comparison with an external time source, no fleet consensus).
  - **Cause:** TrueNAS and Synology NTP blocked by a customer firewall, RTC
    drift on a NAS that has been off, or a VM host.
  - **Effect on every machine:**
    - `clock_skew` becomes a blocked RED reason in the tray;
    - the grid's why-sentence reads "Not syncing: this computer's clock is N
      out";
    - one `clock_skew` alert per computer says "On that computer, turn on Set
      time automatically".
  - Lane B ages remote files by their own mtimes, which editor machines
    wrote, so sync largely still works. The red is mostly false, and its
    remedy points at the wrong box.
  - An editor who sets their clock by hand to match the server makes their
    real timestamps wrong.
- **Scenario:** A customer's NAS loses NTP and drifts 10 minutes over a
  month. Every editor's tray turns red on the same day, the owner gets one
  alert per computer, and support is told "all our computers have the wrong
  time".
- **Recommendation:**
  - When three or more machines report skew of the same sign and similar
    size, raise a single "the server's clock looks wrong" notice and suppress
    the per-machine reasons.
  - Have the dashboard compare its clock to an independent source it already
    talks to (the HTTPS `Date` header of the release feed or GitHub, or
    Tailscale), and add that as a self-diagnosis notice.
  - Word the per-machine remedy so it covers both possibilities.
- **Known:** SYS-4 and APP-13 (fixed) added measurement. This direction is not
  recorded.

### res-time-scale-6 - The 14-day media age-out deletes the only record that a silent laptop holds originals the NAS never got
- **Severity:** medium
- **Confidence:** CONFIRMED
- **Where:**
  - `dashboard/src/ccsync_dashboard/db.py:39` (`MEDIA_REPORT_MAX_AGE_DAYS = 14`), `:10273-10275` (prune)
  - `db.py:5157-5190` (`lost_machines`: projects only)
  - `db.py:11262` (`_backlog_not_reported` covers opt-outs only)
  - `dashboard/src/ccsync_dashboard/api.py:1340-1347`
- **What:** While a machine reports, `fetch_sync_backlog` can say "LAPTOP-X
  holds N originals / B bytes the NAS lacks".
  - After 14 days of silence (stolen, broken, a long shoot abroad, the
    companion uninstalled), `prune` deletes `editor_media` and
    `editor_media_project`. That machine then drops out of every backlog and
    queue view, as if it owed nothing.
  - DASH-16's LOST row keeps the machine on the grid with its ticked
    projects, but carries no "it still owed uploads" fact. The evidence is
    erased exactly when the machine becomes a risk.
- **Scenario:** An editor's laptop with three days of un-uploaded interviews
  dies on a shoot. Three weeks later the owner checks the project page before
  archiving the episode: no machine owes anything. The LOST row shows only a
  tick list.
- **Recommendation:**
  - Before pruning a pair's media rows, snapshot its last owed-upload summary
    (n, bytes, last report time, first few names) onto the `machines` registry
    row, which survives every prune.
  - Render it on the LOST row and in the weekly report ("LAPTOP-X last said it
    held 41 originals (88 GB) the server does not have").
  - Add an alert kind for "lost machine with owed originals".
- **Known:** not recorded. DASH-16 and DCORE-12 cover the row's visibility,
  not the owed footage.

### res-time-scale-7 - Every Cards episode switch leaks its engine's threads and memory for the life of the container, so a dashboard that runs for months grows without bound
- **Severity:** medium (if Timeline Cards is offered to customers; low otherwise)
- **Confidence:** CONFIRMED (documented in code)
- **Where:**
  - `dashboard/src/ccsync_dashboard/cards_pool.py:28-34`, `:615-627`, `:707-731` (`drop`)
  - `docs/CARDS_TWO_PROJECTS.md` section 6.1
- **What:** The pool cap is a refusal, so a seat is freed only by `drop()`.
  `drop()` documents that the upstream library, tokens and translator threads
  keep running for the life of the process.
  - The memory notes measured about +128 MB and 15 threads per engine.
  - Since security-2, non-admins can close idle episodes themselves, so
    switching episodes is routine. Each switch leaks one engine.
- **Scenario:** A studio moves between 20-30 episodes over a quarter. The
  dashboard container accumulates several GB and hundreds of threads until it
  is OOM-killed or restarted. Sync monitoring goes down with it.
- **Recommendation:**
  - Land a real `stop()` upstream before selling Cards.
  - Until then, count leaked engines and raise a notice ("restart the
    dashboard to reclaim N MB") past a threshold. Or recycle the dashboard
    process at a quiet hour once leaked engines exceed K, using the
    zero-downtime deploy path.
- **Known:** design limitation recorded in `docs/CARDS_TWO_PROJECTS.md`, not
  in KNOWN_BUGS as a launch item.

### res-time-scale-8 - The base rig re-walks its whole tree over SMB every 5 and 15 minutes with one extra stat round trip per video file
- **Severity:** low
- **Confidence:** PLAUSIBLE (not measured over SMB)
- **Where:**
  - `companion/src/ccsync_companion/manifest.py:117,253` (`size_fn=os.path.getsize`), `:206-247`, `:393-400` (300 s loop)
  - `companion/src/ccsync_companion/proxy_scan.py:400-440`
- **What:** `ManifestCache` runs on every machine, including the base rig,
  whose `local_root` is the NAS share (P:\). It `os.walk`s up to 64 projects
  and calls `os.path.getsize` per video file. On Windows over SMB, that is an
  open/query/close round trip per file, although `os.scandir` already returned
  the size for free in the directory listing. `proxy_scan` repeats a full walk
  with `os.stat` every 900 s.
- **Scenario:** With 64 projects at 500k files in total, a walk can take
  longer than its 300 s interval. The base rig's SMB session and the NAS stay
  busy around the clock, and editors on the same share feel it.
- **Recommendation:** Walk with `os.scandir` and use `entry.stat()` (cached
  on Windows). Skip the per-file lists entirely in base mode, since the base
  rig's tree IS the NAS and `fetch_sync_backlog` ignores base machines. Also
  consider skipping rollups for projects whose directory mtimes have not
  changed.
- **Known:** the duplicate walk is known and accepted (bug-hunt-2026-08-14).
  The per-file stat cost is not recorded.

### res-time-scale-9 - The site timezone is never asked for, so a customer's weekly report, triage checks and daily heartbeat run on UTC
- **Severity:** low
- **Confidence:** CONFIRMED
- **Where:**
  - `dashboard/src/ccsync_dashboard/alerts.py:719-746` (`timezone_name` defaults to `UTC`)
  - `dashboard/src/ccsync_dashboard/triage.py:130-136` (hours 6 and 18)
  - `dashboard/templates/partials/admin_alerts.html:68`
  - setup wizard: no timezone step
- **What:** `alerts_timezone` is a free-text field on the alerts settings
  page. No setup step and no container `TZ` populate it. Out of the box, a
  California customer gets the "Monday 08:00" report at 01:00 Monday, and
  triage at 23:00 and 11:00.
- **Scenario:** The first paying customer outside UK and Europe hours sees
  reports at odd times and nightly triage mail.
- **Recommendation:** Ask for the timezone in the setup wizard, pre-filled
  from the browser's `Intl.DateTimeFormat().resolvedOptions().timeZone`, and
  store it as `alerts_timezone`.
- **Known:** not recorded.

### res-time-scale-10 - The snapshot policy assumes the apps dataset changes by "kilobytes per hour"; at fleet scale the dashboard DB rewrites hundreds of MB per hour into 54 retained snapshots
- **Severity:** low
- **Confidence:** PLAUSIBLE (not measured on ZFS)
- **Where:**
  - `server/setup_snapshots.py:19-27,73-93` (24 hourly + 30 daily, recursive)
  - `dashboard/src/ccsync_dashboard/db.py:10676` (`replace_editor_media`: DELETE + INSERT of up to 4000 rows per ticked project per resend)
  - `replace_nas_media`
- **What:** At 50 machines x 6 ticked projects with at least one resend per
  600 s, plus `nas_media` replacement, most of `dashboard.db`'s pages change
  every hour. The synthetic fleet DB in res-time-scale-1 was 173 MB. Each
  hourly and daily snapshot then pins roughly a full copy of the changed
  pages. That is several GB on what is often a small apps or boot pool, with
  nothing watching `usedbysnapshots` there.
- **Recommendation:**
  - Measure on the reference NAS.
  - Consider keeping volatile tables (`editor_media`, `media_tree_clips`,
    `nas_media`, `transfer_history`) in a separate SQLite file on a dataset
    with no or short snapshot retention. They are rebuildable from the next
    reports.
  - Add `usedbysnapshots` on the apps dataset to the capacity check.
- **Known:** not recorded.
