# bug-dash-db - dashboard/src/ccsync_dashboard/db.py (schema, migrations, queries)
Files read (approximate coverage): db.py - the whole diff since 0bebf74 (v56, v57,
CR-314 per-kind cap, CR-315 lane_a_skips, CR-320 auto_clear_notice); migrate /
_split_statements / _already_applied; time helpers and clamp_reported_at; report
tokens; machines registry (upsert, lost, device-id release, machine_id lookups,
update/lane-B/diagnostics requests, version_tuple, store_upgrade_state); file
moves (targets, offer, delivery, expiry, answer names, like-prefix); selections
(copy, adopt rename, bucket, add/remove, fetch_machine_selections); notices
(notice/clear/dismiss/auto_clear); packages (set_current, retract); prune;
evict/forget; media presence (replace_nas_media, replace_editor_media, media
tree, transfers, fetch_sync_backlog); the whole jobs section (create, queued,
retry, claim CAS, heartbeat, finish, fail, expire_leases, backpressure, pinned,
cancel, capabilities). Read across the wire where it mattered: api.py report
handler (manifest -> replace_editor_media), jobs.py offer loop, companion
manifest.py and sync/rclone_lane.py filter rules, cards_exec.py pinned loop.
Tests/probes run: two ad-hoc probes against an in-memory DB built by
`db.migrate` with the dashboard venv (scripts in the session scratchpad, nothing
written to the repo). The output of each is quoted under its finding.

## Findings

### bug-dash-db-1 - The scheduler only ever looks at the first 200 queued jobs, so a block of jobs nobody can run starves every job behind it
- Severity: medium
- Confidence: CONFIRMED
- Where: dashboard/src/ccsync_dashboard/db.py:10255 (`queued_jobs`, `limit: int = 200`), called with the default by db.py:10534 (`claim_next_job`) and dashboard/src/ccsync_dashboard/jobs.py:931 (the offer loop)
- What: `queued_jobs` returns the top 200 rows by `priority DESC, id ASC`, and both the offer builder and the claim CAS walk only that list. Queued jobs are never aged out (prune_jobs removes terminal rows only, on purpose), a job no machine can run never spends its retry budget (it is never claimed), and whisper never pins. So 200 or more queued jobs that nobody can run hold a window nothing else can get into, for as long as they stay queued.
- Failure scenario: a Timeline Cards episode queues 250 `whisper` jobs (requires a GPU) while the one GPU box is off for the week, then some `peaks` / `audio-extract` jobs for the same clips. Every report runs `jobs.offer` over the 200 whisper rows, refuses them all for capability, and never sees the cheap jobs. The base rig, which could run them, is never offered them and they never get pinned. `explain()` looks the job up by id, so the WHY page reports the peaks job as schedulable while nothing ever offers it: a queue that looks fine and never moves. The same happens with 200 queued jobs of a kind at its fleet cap (for example a 400-clip `proxy-480p` batch at cap 4): the other kinds wait until the backlog drops below 200.
- Evidence: probe - 200 `whisper` jobs with `requires={"gpu_vram_gb": 6}`, then one `peaks` job with no requirements. `len(db.queued_jobs(conn)) == 200` and the peaks id is not in the list. `db.claim_next_job(conn, "e", "m", capabilities={}, max_running={})` returned `None`, and still returned `None` with `allowed_ids=[peaks_id]`: even an explicit offer of that id cannot be claimed.
- Ledger: new (dash-db-4 of 2026-09-11 fixed the same window shape in `open_retry_of` only)
- Suggested fix: make the window work per kind, for example one `LIMIT` per kind (a `ROW_NUMBER() OVER (PARTITION BY kind ...)`), or a SQL pre-filter of kinds at cap. When `allowed_ids`/`ids` are given, have `claim_next_job` look those ids up directly instead of scanning the head of the queue.

### bug-dash-db-2 - A project with more than 2,000 proxies shows the extra proxies as downloads owed for ever, and the note says the total may be too low
- Severity: medium
- Confidence: CONFIRMED
- Where: dashboard/src/ccsync_dashboard/db.py:9699-9766 (`fetch_sync_backlog`, the `down` spec and `manifest_truncated`); companion/src/ccsync_companion/manifest.py:36 and 211-226 (per-kind cap 2000, sets `truncated`); dashboard/templates/partials/transfers.html:78
- What: the lane B backlog is "NAS proxies with no matching `editor_media` row". The companion lists at most 2,000 proxies per project and sets `truncated` when it holds more. Every NAS proxy past the listed 2,000 therefore counts as missing from the machine, even though it is on the machine's disk. The row carries `manifest_truncated`, and the template renders that as "totals may undercount". For the `down` direction the error runs the other way: the total is too high, with phantom downloads that never clear. CR-314 fixed the case where originals plus proxies together pass 2,000. One kind alone passing 2,000 is still broken.
- Failure scenario: ruskin's Energy Transition already holds 1,696 proxies. When it passes 2,000 (or any project with, say, 2,500 proxies on the NAS), a machine holding every proxy shows `[ QUEUED ] proxy download, 500 files` for good. That is the same symptom CR-314 was filed for, and the page says the count may be too low.
- Evidence: probe - 2,500 NAS proxies plus 10 originals. The machine holds all of them, and its manifest lists the first 2,000 proxies with `truncated=True`, exactly as `manifest.py` builds it. `fetch_sync_backlog` returned `down 500 5000 True` (500 files, 5,000 bytes, manifest_truncated).
- Ledger: related to CR-314 (fixed; this is the part it did not cover)
- Suggested fix: when the manifest is truncated, do not list a per-file `down` diff (or cap `n_files` at `max(0, nas_proxies - emp.n_proxies)` using the exact rollup counts the companion already sends). Make the template wording depend on direction: truncation means "may be too high" for downloads and "may be too low" for uploads.

### bug-dash-db-3 - Forgetting a computer or a person leaves their diagnostics bundles behind
- Severity: low
- Confidence: CONFIRMED
- Where: dashboard/src/ccsync_dashboard/db.py:8435-8439 (`_MACHINE_STATE_TABLES`), db.py:1114 (`diagnostics` table, columns `editor`/`machine`, not `editor_username`)
- What: `forget_machine` and `forget_editor` delete from every table in `_MACHINE_STATE_TABLES`. `diagnostics` is not in that tuple, and it could not be added as is because its columns are named `editor`/`machine`. Up to five bundles per machine, up to 256 KB of text each (paths, hostnames, log lines), stay for up to 30 days after the admin erased that person.
- Failure scenario: an admin deletes a departed editor (CR-76), which the docstring describes as "Erase a person from the fleet's records". Their machines' diagnostics text is still in the database and is served by `fetch_diagnostics` / `newest_diagnostics_per_machine` to anyone who opens that (editor, machine) view. A new user given the same username sees the old person's bundles.
- Evidence: read of `_MACHINE_STATE_TABLES`, `forget_machine`, `forget_editor` and the v33 `diagnostics` DDL. The only DELETE on the table is prune's 30-day age bound (db.py:8883).
- Ledger: new
- Suggested fix: in `forget_machine` / `forget_editor`, add `DELETE FROM diagnostics WHERE editor=? AND machine=?` (and `WHERE editor=?` for the person).

## Coverage note
Not reached in depth: `upsert_machine_state` (7564-7938) and the map readers
after it, `soak_state` / `rollout_status` / `machines_running_version`, the
Resolve undo and journal writers, `fetch_collector_status` /
`collector_stale_bound`, `adopt_renamed_machine` against SYS-18a in api.py, and
`record_standins_placed`. Checked and found sound: the v56/v57 steps (both
replay-safe); `auto_clear_notice`; the CR-315 skip globs against the companion's
lane A rules, including `--ignore-case` and proxy classification; the `open_retry_of`
LIKE prefilter; `_like_prefix` escaping; the claim CAS with the fleet cap;
`fail_job` / `expire_leases` cancel handling; `request_job_cancel`'s re-read;
`version_tuple` with two-digit minors. A noted design choice, not a finding:
`deactivate_missing_projects` lets an empty Syncthing folder list deactivate a
site with 2 or fewer active projects (ceiling `max(2, n//4)`), which its own
comment says it accepts.

## OUT OF TERRITORY
- dashboard/src/ccsync_dashboard/jobs.py:931: `offer` inherits bug-dash-db-1 (the 200-row window), and `explain` does not, so the two answers disagree for any job past row 200.
- dashboard/src/ccsync_dashboard/api.py:9611: two `local_manifest` keys that `_slug_for_rel` maps to the same slug (for example a project folder reported in two Unicode spellings) each run `replace_editor_media`, and the second deletes the first's rows (not verified end to end).
