# Pre-launch resilience review - lens res-concurrency (2026-10-06)

Scope: concurrency and races across the system, on HEAD 08b40eb plus the
uncommitted working tree (alert-kind selection, CR-356/CR-358 companion
changes). Read-only; no live systems touched.

What was read end to end: the companion single-instance guard (`app.py`
mutex + pid file, supervisor hand-off), `config.set_value` and every
config.toml writer (settings window, machine_settings, onboarding), identity
writes, `lane_guard` persistence, `UpgradeManager` serialisation; the
dashboard's SQLite model (`db.connect`, WAL, busy timeouts), the fleet-jobs
lease (claim / heartbeat / finish / fail / expire_leases, the claim and
heartbeat routes) and the companion runner's heartbeat and result posting,
the ytdl local-download lease, `_register_machine` / `upsert_machine` /
`adopt_renamed_machine`, delete-user and forget-machine, the server-side file
move, `cards_pool.py`, `cards_tunnel.py` and the engine's `agent_pending` /
`agent_state` in the MulticamPipeline repo, the collector watchdog, the OTA
`_APPLY_LOCK`, `run.sh` (`--workers 1`), `docs/ZERO_DOWNTIME_DEPLOY.md`
(design only), and the new alert-kind selection route/template.

Not covered: lane A/B/C file-level races inside rclone/Syncthing, the whisper
pipeline's own output atomicity (other repo), b-roll/music indexer
concurrency, the session store internals.

Already well handled and NOT reported: config.toml writer lock
(`_SET_VALUE_LOCK`), the jobs compare-and-set and fleet cap, the companion
self-upgrade predecessor wait (CR-120), Tk interpreter pinning (CR-93), the
OTA apply lock, the lane B breaker persistence, the cards pool's
closed-while-opening orphan handling.

### res-concurrency-1 - A dashboard outage longer than the lease kills every running fleet job and local YouTube download, and a result posted during a restart is never retried

- Severity: medium
- Confidence: CONFIRMED
- Where: dashboard/src/ccsync_dashboard/db.py:11607 (JOB_LEASE_SECONDS = 300), db.py:12153-12176 (`heartbeat_job` requires `lease_expires_at > now`), db.py:12274 (`expire_leases`), db.py:10300 (collector sweep), api.py:12126 (expire on every claim), api.py:12153-12181 (410 on a failed heartbeat); companion/src/ccsync_companion/jobs_runner.py:815-880 (`_heartbeat`: transport failure = keep going, 410 = stop), jobs_runner.py:886-923 (`_post_result`: one attempt, no retry); ytdl/web/ytdlweb/db.py:1175-1202 (`heartbeat_download`, same `lease_expires_at > ?` rule), ytdl/web/ytdlweb/config.py:240 (LEASE_SECONDS 180)
- What: the companion correctly treats an undeliverable heartbeat as a blip and keeps working, but the dashboard measures the lease in wall-clock time that keeps running while the dashboard itself is down. When it comes back, the first claim from any machine or the first collector cycle calls `expire_leases`, which re-queues every held job (attempt +1, machine cooldown), and even if the holder's heartbeat arrives first, `heartbeat_job` refuses because the lease is already past, so the answer is 410 and the companion kills its child. Separately, a result POST that lands during a restart is logged and dropped; the job then expires and runs again.
- Scenario: a customer NAS reboots for a TrueNAS update, or the dashboard image is updated with a slow pull, or the container crash-loops for six minutes. Every whisper pass in the fleet (minutes to an hour of GPU each) is thrown away on reconnection, each machine is put on cooldown as if it had failed, the jobs restart from zero elsewhere, and three such outages spend the retry budget and abandon or pin the job. Local YouTube downloads (180 s lease) are taken back by the server worker and can be downloaded twice. A plain 10 s OTA restart that coincides with a finishing job loses the result and costs a full rerun after 5 minutes.
- Recommendation: make lease time "dashboard-alive time": at boot, before anything can expire a lease, extend every held lease by the measured downtime (or record a `leases_valid_from = boot + grace` and have `expire_leases` and `heartbeat_job` ignore expiry for one lease length after boot); let `heartbeat_job` re-extend a lease that expired but whose row is still held by the same (editor, machine) and still in claimed/running. Do not count an expiry that spans a dashboard restart as an attempt or a cooldown. On the companion, retry `_post_result` with backoff (persist the pending result in jobs_recent.json) until a definitive answer. Same treatment for ytdl `heartbeat_download`.
- Known: not recorded (KNOWN_BUGS mentions lease expiry only for sleeping laptops; comp-ytdl-jobs-1 fixed the companion half only).

### res-concurrency-2 - Deleting a user in local mode holds the SQLite write lock across every Syncthing call, so the whole fleet's writes fail with "database is locked"

- Severity: medium
- Confidence: CONFIRMED
- Where: dashboard/src/ccsync_dashboard/api.py:5242-5258 (`local_users.delete_user` then `_remove_editor_devices`), local_users.py:339-340 (two DELETEs, uncommitted), api.py:5146-5175 (`_remove_editor_devices`), syncthing_client.py:194-228 (`remove_device`: config read, then GET + PUT per shared folder, then DELETE; 10 s timeout each), db.py:697-722 (BUSY_TIMEOUT_MS 5000 for request connections)
- What: step 1 of `delete_user_everywhere` deletes the local account rows on the request connection without committing, which opens a write transaction and takes SQLite's RESERVED lock. Step 2 then makes 2 + (2 x shared folders + 1) x devices HTTP calls to Syncthing, each with a 10 s timeout, before step 4 commits. Every other writer in the process waits on that lock: companion reports, file-move answers, job claims and heartbeats (5 s busy timeout, then a 500/503), sessions and the collector (20 s).
- Scenario: an admin deletes a departed editor who had two computers and 25 ticked projects: about 100 Syncthing calls. On a healthy NAS that is 10-30 s of held lock (each folder PUT is a config save); on a sluggish Syncthing it is minutes. For that whole time every report in the fleet fails, job heartbeats fail (feeding res-concurrency-1), and admins and editors signing in can be bounced. The person pressing DELETE sees a spinner; nobody connects the fleet-wide red chips to it.
- Recommendation: do the guard checks and the Syncthing removal with NO write transaction open: check the local-user guards read-only first, remove devices, then open one short write transaction for the account row, `forget_editor` and the audit, and commit. Rolling back "nothing deleted" on a Syncthing failure still works because nothing was written yet. Add a test that asserts `conn.in_transaction` is False whenever a Syncthing/NAS client call is made from a route.
- Known: not recorded (CR-76 introduced the flow; the 2026-09-03 "database is locked" incident was the report path, not this one).

### res-concurrency-3 - Nothing stops two dashboard processes from running on one /data

- Severity: medium
- Confidence: CONFIRMED (absence of a guard); scenario PLAUSIBLE
- Where: dashboard/deploy/run.sh:592-608 (`--workers 1` is the only single-instance measure), dashboard/src/ccsync_dashboard/app.py:810-840 (boot-time `release_pinned_jobs`, collector start), docs/ZERO_DOWNTIME_DEPLOY.md section 3.3 (the singleton inventory and the proposed `flock`, not built); grep for flock/singleton in dashboard/src finds nothing
- What: the whole concurrency model (db.py header: "a single uvicorn worker, and the collector thread as the only bulk writer") rests on there being one process per data directory, but nothing enforces it. A second container (or a stray `docker compose up` under a second project name, an app installed twice from the TrueNAS catalog and a custom compose, a migration from bind-mount to image mode that leaves the old one running) starts a second collector, a second enforce cycle, a second alert sender, a second release-feed poller, a second pinned executor, a second triage scheduler and a second Cards engine pool on the same files.
- Scenario: at a customer site the second dashboard boots, its `release_pinned_jobs` releases jobs the first one's executor is still encoding, both enforce cycles race each other's Syncthing config PUTs, every alert and the weekly report are mailed twice, both feed pollers apply the same OTA, and two Cards engines read-merge-write the same `<data>/cards/<slug>` docs. Nobody at the vendor can see it; the symptoms look like flapping shares and duplicate mail.
- Recommendation: take an exclusive `fcntl.flock` on `<data>/dashboard.lock` in the lifespan before anything else starts, held for the process lifetime (the kernel releases it on death, so a crash cannot strand it); a second process that cannot take it refuses to start (or serves read-only with a red banner) and logs which host/pid holds it. This is ZD-2's lease, and it is worth shipping on its own before launch, independent of the zero-downtime work.
- Known: design noted in docs/ZERO_DOWNTIME_DEPLOY.md (not built, not in KNOWN_BUGS).

### res-concurrency-4 - One editor with the Cards agent on two computers breaks the engine's one-agent assumption: edits are reported lost, the page flips between two timelines, and an edit goes to whichever computer polls first

- Severity: medium
- Confidence: CONFIRMED (both halves read); the wrong-timeline outcome is PLAUSIBLE
- Where: dashboard/src/ccsync_dashboard/cards_pool.py:417-488 (`_where`, `_handed` keyed by editor only), cards_tunnel.py:456-529 (`cards_agent_pending` routed by editor); MulticamPipeline multicam_pipeline/cards/agent.py:1167-1200 (`agent_pending`: "a poll while a request is OUT: the agent that took it is gone ... it is one agent per server"), agent.py:340-360 (`agent_state` overwrites `agent_name`, playhead and state from whichever agent pushed last)
- What: the tunnel identifies the caller as the PERSON, and the engine assumes exactly one agent per server. With the role on two of one editor's computers (the per-machine `cards_agent` switch allows it, and "one person, two editing machines" is a supported shape since MULTI_MACHINE_PLAN), both companions long-poll `/cards/agent/pending` for the same engine. The first poll takes the edit; the second poll, arriving while the first is applying it, hits the "request is OUT" branch, clears `_req` and publishes "the Resolve agent went away with that edit, it was never confirmed" for an edit that is being applied. Both computers push `agent_state` alternately, so the page's cards, playhead and agent name flip between two Resolve sessions.
- Scenario: an editor has the role on at the studio desktop and on their laptop at home, both signed in. They stage a cut on their phone: the edit may be applied by the laptop's Resolve (whichever poll was waiting), the page says it was lost, they press it again, and the second copy lands on the desktop. CLAUDE.md's own rule for conform/resolve-edit is that a keystroke moved to another machine is a keystroke into the wrong timeline.
- Recommendation: key agent routing by (editor, machine): `note_visit`/`_where` should remember which machine's agent the page is following, and `/pending` should hand edits only to that machine; a second agent of the same editor should get the empty answer plus a note, and the page should name both and let the editor choose. At minimum, refuse to start the role on a second machine while the first holds it (the dashboard can see both `agent_name`s), and make the engine's "lost" path compare the polling agent's name with the holder's before declaring an edit gone.
- Known: not recorded.

### res-concurrency-5 - The server-side file move checks the destination and then renames, and a Linux rename silently replaces whatever arrived in between

- Severity: medium
- Confidence: CONFIRMED (code path); the collision is rare
- Where: dashboard/src/ccsync_dashboard/api.py:3159-3262 (`move_project_files`: `if dest.exists(): 409` ... `src.rename(dest)`), api.py:3265 (`def` route, runs in the threadpool, so two moves run concurrently)
- What: `Path.rename` is rename(2), which on Linux atomically REPLACES an existing destination file. The existence check and the rename are separate steps with a DB commit in between, and nothing serialises moves. A file that appears at the destination after the check is destroyed without trace: two admins (or one admin double-submitting through two tabs) moving two different clips to the same name, or lane A / Syncthing landing a file at that path in the same second.
- Scenario: two producers tidy the same card dump at once and both move a `C0001.MP4` into `Interviews/`; the second rename deletes the first clip on the NAS, both moves are recorded as done, and every machine is told to follow. The only copy left may be on an editor's machine that is then told to move ITS copy, which refuses because the destination exists.
- Recommendation: never let the rename replace: use `os.link(src, dest)` then `os.unlink(src)` for files (link fails with EEXIST atomically), or `renameat2(..., RENAME_NOREPLACE)` via ctypes, and hold a module-level lock around the whole check-record-rename sequence. Directories are already safe only when the destination is non-empty; treat them the same way.
- Known: not recorded (DASH-1 fixed the ordering of record and rename, not this).

### res-concurrency-6 - Two of one editor's computers that share a hostname are merged into one registry row, and the enforce cycle follows whichever reported last

- Severity: medium
- Confidence: PLAUSIBLE
- Where: dashboard/src/ccsync_dashboard/db.py:5108-5133 (`upsert_machine` COALESCEs `machine_id` and `syncthing_device_id` onto the `(editor, machine)` row), api.py:7777-7890 (`_register_machine` detects one machine_id on two hostnames, never two machine_ids on one hostname); companion reporter.py:900, selection.py:38, jobs_runner.py:768 (`platform.node()` read per call); installer/macos_bootstrap.sh (never pins HostName/ComputerName)
- What: the clone detector covers "one identity, two names". The mirror image, "two identities, one name", is not looked for: each report overwrites the row's `machine_id` and `syncthing_device_id`, so the row alternates between two computers every report interval. The enforce cycle shares folders with the row's current device id, so the share set flaps between the two Syncthing devices, the plan is one plan for two computers, and job leases keyed on (editor, hostname) are shared between them. On macOS `platform.node()` can also change with the network (DHCP / reverse-DNS hostname when HostName is unset), and the jobs runner, reporter and selection client each read it independently, so a name change mid-job turns the holder's own heartbeat into a 410.
- Scenario: a customer editor owns two MacBook Pros both named `Annas-MacBook-Pro` (common: the default name is the owner's), on different networks so Bonjour never renames one. Lane C on each alternately gains and loses its folders; the grid shows one computer whose platform and progress jump; nobody is told.
- Recommendation: in `_register_machine`, when the stored `machine_id` is set and differs from the reported one and the stored row reported inside CLONE_ADOPTION_WINDOW, raise a `duplicate_hostname` notice and refuse to overwrite the id/device; tell the newer companion (report reply) to show "another of your computers has the same name, rename this one". On the companion, read the hostname once per process (or per job claim) and pin the macOS name via `scutil --get ComputerName`/LocalHostName rather than the DHCP-derived kernel hostname.
- Known: not recorded (SYS-18a / DASH-11 cover the clone direction only).

### res-concurrency-7 - The macOS single-instance guard is check-then-write, and the Windows one is per logon session

- Severity: low
- Confidence: PLAUSIBLE (race window is small; the code path is CONFIRMED)
- Where: companion/src/ccsync_companion/app.py:599-638 (`_acquire_lock_file`: read pid, liveness probe, `write_text` - no O_EXCL, no lock), app.py:307 (`Local\\ccsync-companion-single-instance`), broll_server.py:2888-2897 (8899 loopback)
- What: on macOS two companions started together (the LaunchAgent at login plus a Login Item or a double-click; the supervisor's direct-spawn fallback after a `launchctl kickstart` that reported failure but did start one) can both read a stale pid, both pass, and both write their own pid. The pid file is also the liveness proof for `_pid_looks_like_companion`, which still has to guess about pid reuse. On Windows the mutex is `Local\`, so a second logon session on the same PC (fast user switching, RDP into an edit bay) runs a second companion with the same hostname; whichever binds 127.0.0.1:8899 first then answers the OTHER user's browser, because the origin allow-list accepts the shared dashboard origin.
- Scenario: two companions on one Mac run two lane sets on the same tree and the same `~/.ccsync/state`, report under one identity, and can both self-upgrade the same bundle (the AUDIT_2 CORE-M7 list). On a shared Windows bay, user B's Send to Resolve inserts into user A's still-open Resolve.
- Recommendation: on posix, hold an `fcntl.flock(LOCK_EX | LOCK_NB)` on `companion.lock` for the process lifetime (released by the kernel at death, so no pid reuse question and no TOCTOU), keeping the pid inside only for the log. On Windows, decide deliberately: either `Global\` (one companion per PC) or document per-user and bind the loopback per-session (token header required, not origin alone).
- Known: not recorded.

### res-concurrency-8 - Closing and reopening the same Cards episode (or retrying a deadline-failed open) runs two engines' unstoppable workers against one episode

- Severity: low
- Confidence: PLAUSIBLE
- Where: dashboard/src/ccsync_dashboard/cards_pool.py:557-595 (`open` replaces a FAILED entry and starts a new build), cards_pool.py:371-392 (`_expire_stalled` fails a LOADING entry while its thread keeps running), cards_pool.py:707-730 (`drop`: "stop() sets a flag the library, tokens and translator threads do not read"), cards.py:239-260 (`data_dir_for` is per slug, not per engine); MulticamPipeline project_agent.py:686 (`stop` only sets a flag), library_engine.py:1779 (translator thread), project_pick.py:436-450 (`doc_save` read-merge-write through a fixed `.tmp`)
- What: the pool guarantees one LIVE entry per slug, not one set of workers per slug. After a close, the old engine's translator/library/tokens threads keep running (documented); a reopen of the same slug builds a second engine with the same data dir and the same episode root, and both sets of workers can write the episode's translations and docs. The same happens after BUILD_DEADLINE: the stuck builder eventually finishes, is correctly orphaned, but has already started workers on that slug's files.
- Scenario: an editor closes an episode mid-translation run to free a seat, reopens it a minute later and presses translate again; two translator threads write the same Script Docs, and `doc_save`'s shared `.tmp` lets one overwrite the other's pick.
- Recommendation: refuse to reopen a slug whose previous engine still has live worker threads (the pool can keep the closed engine object and ask its threads `is_alive()`), or give each engine instance its own tmp names and serialise `doc_save` per path with a process-wide lock until a real `stop()` lands upstream.
- Known: the thread leak is documented (docs/CARDS_TWO_PROJECTS.md section 6.1); the same-slug double writer is not recorded.

### res-concurrency-9 - The new alert-kind switches mute kinds the page never showed (a tab opened before an update, or a second admin's save)

- Severity: low
- Confidence: CONFIRMED
- Where: dashboard/src/ccsync_dashboard/ui.py (uncommitted, `partial_admin_alerts_kinds`: `muted = [k for k in everything if k not in send]`), dashboard/templates/partials/admin_alerts.html (uncommitted, page text "A check added in a later update starts ticked"), app.py:1125-1130 (`stale_page_gate` checks the look header, not the build)
- What: the route computes the muted set as "every kind THIS build knows minus the ticks", so the ticks are only correct for the build that rendered the page. An admin tab drawn before an OTA update (unattended under `policy = current`) has no checkbox for a kind the update added; saving it stores that kind as switched off, which is exactly the opposite of the promise printed on the page. Two admins editing at once is the same lost update.
- Scenario: a new error-severity check ships in an update overnight; the next morning an admin unticks one noisy warning in a tab left open since yesterday and saves; the new check is silently muted from its first finding. It is listed under "NOT SENT AS ALERTS" in the weekly report, which is easy to miss.
- Recommendation: post the list of kinds the page rendered (a hidden `shown` field per kind) and mute only `shown - send`, leaving any kind not shown untouched; or store a `rendered_version` and refuse a save from a different build with "this page is out of date, reload".
- Known: not recorded (the feature is new and uncommitted).

### res-concurrency-10 - A machine's lane A pass that runs before a server-side move reaches it puts the file back at the old path, and the resulting duplicate is dropped without a word

- Severity: low
- Confidence: PLAUSIBLE
- Where: docs/FILE_MOVES.md:76-83 (the old path is excluded only after the command is applied), dashboard/src/ccsync_dashboard/collector.py:2800-2822 (`a file that came BACK to the path it left (lane A re-uploading in the window before a command landed ...) is not a move. Both halves are dropped and nothing is recorded`)
- What: between the server rename and the holder's next report reply, lane A on that machine sees the file missing on the NAS and uploads it again at the old path. The collector recognises this exact case and deliberately records nothing; the companion later applies the move locally, so the NAS keeps two copies (old and new path) and every other machine with the project ticked downloads proxies for both.
- Scenario: an admin reorganises a 200 GB shoot; two remote editors' lane A passes run in the first minute; the NAS ends up with a second full copy at the old paths, the storage alert fires later, and nobody knows which copy Resolve projects point at.
- Recommendation: when the collector sees a comeback for a path that has a `file_moves` row less than a day old, raise a notice naming the move and the machine, and offer [ REMOVE THE OLD COPY ] (to `.trash`, never a delete) once every holder has answered `applied`.
- Known: acknowledged in a collector comment; not in KNOWN_BUGS.
