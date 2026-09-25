# logic-ytdl-jobs - YouTube download (ytdl/web, dashboard ytdl.py, companion ytdl_*) and the fleet job queue (dashboard jobs.py, companion jobs_runner/jobs_media): logic + usability

Files read (approximate coverage): dashboard/src/ccsync_dashboard/jobs.py (all);
dashboard db.py job section (10020-11120, prune 8786-8920); api.py job routes
(10590-11070) and the report-reply jobs block (9960-10035);
ytdl/web/ytdlweb/routes_fleet.py (180-884), routes_api.py (684-812, 1700-1919),
db.py (queue, lease, claim, reclaim: 330-1360), worker.py (1425-1730);
ytdl/web/static/app.js (dispatch / progress / mode badge, 2370-2760);
companion jobs_runner.py (560-1120), ytdl_executor.py (claim, _run,
_download_all, _label_is_ours, start, progress_row), app.py job-runner and ytdl
Deps wiring, tray.py menu builder; KNOWN_BUGS CR-145 / CR-171; the other
hunters' 2026-09-24 reports (to avoid duplicates).
Tests/probes run: two ad-hoc probes in the scratchpad (no repo writes):
- dashboard venv: `jobs.explain` over a temp DB with one machine that last
  reported 2026-08-01 and one live machine.
- dashboard venv with `PYTHONPATH=ytdl/web`: ytdlweb.db queue with a live local
  lease on the editor's first job.

## Findings

### logic-ytdl-jobs-1 - The scheduler judges a computer by its LAST report however old it is, so a machine switched off weeks ago keeps a job "schedulable" or "transient" for ever
- Severity: medium
- Confidence: CONFIRMED
- Where: dashboard/src/ccsync_dashboard/jobs.py:610 (fleet_facts), :974-1112 (explain), :722-747 (first_refusal)
- What: `fleet_facts` reads every `machine_state` row with its stored capabilities (including `idle_seconds`) and has no `reported_at` bound, and nothing downstream asks whether the machine is still there. `ranked_machines`/`explain` therefore count a machine that has not reported in a month as able, using the idle number it sent on its last report. `GET /jobs/machines` computes `online` for the picker (alerts.SILENT_SECONDS) but the scheduler never uses that idea.
- Failure scenario: A laptop last reported on 2026-08-01 with ffmpeg and `idle_seconds: 900`, then was put in a drawer. A proxy job is queued while the one live editor PC has somebody at it. `explain` answers `schedulable: true`, reason `""`, "1 computer can take this job; it is waiting to be claimed on their next report", and marks the drawer laptop "can take it, and is first choice". Timeline Cards reads `schedulable` and keeps waiting. The laptop will never send another report, so it never claims. If its last report was NOT idle, the code is `idle_wait`, `transient: true`, and worst-answer-wins means one dead laptop keeps the job transient even when every live machine lacks the capability. For the first 60 s the dead machine can also win the rank grace (nvenc, or `mode == base`), so live machines get `another_machine_is_preferred`. This is the "a scheduler that quietly assigns nothing looks like a fleet with nothing to do" failure the module was written to prevent.
- Evidence: probe output: `True '' 1 computer can take this job; it is waiting to be claimed on their next report` / `leso MBP True this computer can take it, and is first choice`. The second scenario gave `False 'idle_wait' True`. Also: no staleness predicate in fleet_facts, policy_refusal or ranked_machines.
- Ledger: new
- Suggested fix: Put a silence bound in `fleet_facts`/`machine_facts` (reported_at older than about alerts.SILENT_SECONDS, or a few report intervals, is a policy refusal `machine_silent`, mapped to a NON-transient reason). Leave it out of the rank grace too, and say "has not reported since X" on the why page.

### logic-ytdl-jobs-2 - An editor's own requester-first download blocks that editor's queued searches while the server worker has nothing to do
- Severity: medium
- Confidence: CONFIRMED
- Where: ytdl/web/ytdlweb/db.py:348 (BUSY), :930-975 (claim_next_job), :537 (busy_job); routes_api.py:735 (_queued_answer)
- What: `BUSY` is defined as "the phases a WORKER is actually inside", and `downloading` is in it. But a `downloading` job under a live local lease is not in the worker at all: claim_next_job hides it on purpose. The queue's NOT EXISTS still counts it as that editor's busy job, so the editor's next `queued` search cannot start until their own machine finishes downloading, even though searching, enriching and filtering can only run on the server and the worker is idle.
- Failure scenario: Sam presses DOWNLOAD on 40 clips. His companion claims them and spends 40 minutes downloading. He starts a second search for tomorrow's shoot. The job sits at `queued` with `queued_behind: 1`, `fleet_ahead: 0`, and nothing runs for 40 minutes, although the NAS worker is idle and would have finished the search (and put him at review) long before his download ends. Other editors' jobs go through in the meantime, so the wait looks random.
- Evidence: probe: with job A `downloading` under a live local lease for sam, `claim_next_job` hands out ann's job; once that is done it returns `None` while sam's queued job B stays waiting (`fleet_ahead: 0`, `busy_job` = A).
- Ledger: new
- Suggested fix: In the queue predicate (claim_next_job and fleet_ahead), leave out of "busy" a `downloading` row whose `download_mode='local'` with an unexpired lease, since that row is already hidden from the worker. Or define "busy" as "the worker is inside it" instead of by phase alone.

### logic-ytdl-jobs-3 - The page never shows why the editor's own computer gave a download back: `handed_back_reason` has no consumer, and claim refusals set no reason at all
- Severity: medium
- Confidence: CONFIRMED
- Where: ytdl/web/static/app.js:2593 (dispatchLocal returns true on 202), :2668-2750 (ensureLocalProgress / localProgressLine); companion/src/ccsync_companion/ytdl_executor.py:2040 (hand_back), :1127-1186 (FleetClient.claim), :3296 (progress_row)
- What: CR-171 (CYT-11) gave the companion one sentence for each of the seven whole-job hand-backs and documented that "the page that has had its 202 learns WHY the badge is about to flip" (LOOPBACK_API.md). `app.js` never reads `handed_back_reason`, and a `phase: handed_back` row is never rendered. The loopback is only polled while `download_mode === 'local'`, and several hand-backs happen before a lease exists (capability, free space), so the row is never even fetched. The claim itself runs after the 202, and its refusals (403 yt-dlp below the fleet floor, 409 "already downloading on your other computer", 410 skew/out of scope/created on the server, 403 attestation) call no `hand_back`. They exist only in the companion log.
- Failure scenario: The owner asked (2026-08-19) for "an error and some feedback for when it doesn't do it", because clips the server downloads stay on the NAS and no lane brings them down. The editor presses DOWNLOAD and gets a 202. Their companion then finds the disk below 5 GB free, or that its tree is unmounted, or that the server refuses the claim over a stale yt-dlp. The page stays silent: no toast. In the after-claim cases the badge says "downloading on your computer" with no progress until the lease runs out (up to 180 s), then flips to the server. The editor never learns that the clips will not be on their disk.
- Evidence: `grep handed_back ytdl/web/static/app.js` finds nothing; `FleetClient.claim` returns None after a `log.info` on every non-200; `_run` returns on `lease is None` without calling `hand_back`.
- Ledger: related to CR-171 (the page half of CYT-11 was never built)
- Suggested fix: After a 202, keep polling `/ytdl/progress` for that job id for a short window whatever `download_mode` says, and pass `handed_back_reason` through `noteLocalSkipped`. In `_run`, turn a refused claim into `hand_back()` with the server's `detail` (it is already editor-readable, for example `_already_downloading`).

### logic-ytdl-jobs-4 - The download-terms toast sends the editor to a right-click menu item that has not existed since the CR-88 menu reduction, and ignores the companion's correct route
- Severity: low
- Confidence: CONFIRMED
- Where: ytdl/web/static/app.js:2406-2411 (explainCompanionRefusal); companion/src/ccsync_companion/ytdl_executor.py:365 (REASON_NOT_ATTESTED), ui_copy.py:56
- What: When the companion refuses because the YouTube terms are not accepted, it sends a reason that already names the route (`ui_copy.YOUTUBE_TERMS` = "Tray > Settings > Accept YouTube Terms"). The SPA drops that reason and shows its own hardcoded sentence: "right-click the tray icon, then 'Accept YouTube Terms'". The right-click menu (tray.py 4680-4880, the ten-item CR-88 layout) has no such item. It lives only in the Settings window. CR-145 fixed this for every companion string. This browser copy was missed, as the 2026-09-03 YTWEB sweep note predicted ("that string breaks silently").
- Failure scenario: An editor whose download fell back to the server is told to right-click the tray and pick an item that is not there. It is the one refusal they could fix in ten seconds. They give up, and every download keeps landing on the NAS only.
- Evidence: tray.py menu builder has no terms item; `action_youtube_terms` is reached from settings_window.py:1492; the toast text at app.js:2409.
- Ledger: related to CR-145 (a remaining instance, browser side)
- Suggested fix: Show the companion's own `body.reason` (which carries the ui_copy route), or copy the route string "Tray > Settings > Accept YouTube Terms" and add it to the test that pins the SPA copy.

### logic-ytdl-jobs-5 - The collector's lease sweep ignores DASH_JOBS_COOLDOWN_SECONDS, so an operator cannot turn the cooldown off for the commonest way a lease ends
- Severity: low
- Confidence: CONFIRMED
- Where: dashboard/src/ccsync_dashboard/db.py:8914 (prune -> expire_leases(conn, now, pin=pin)); compare api.py:10970-10972
- What: `expire_leases` cools down the machine whose lease ran out. The claim route passes `settings.jobs_cooldown_seconds`. The collector's `prune()`, which is the path that normally runs (its own comment says the claim path only runs "when some OTHER machine asks for work"), passes nothing and gets the 120 s default. The operator setting only takes effect on the less common path.
- Failure scenario: An operator whose fleet is one base rig and one laptop sets `DASH_JOBS_COOLDOWN_SECONDS=0` so that a sleeping laptop is not parked. The laptop sleeps mid-job and the collector expires the lease. The laptop is still cooled down for 120 s, and `why` shows "cooling down until ..." for a setting the operator switched off.
- Evidence: the call sites above; `settings.jobs_cooldown_seconds` has no other reader.
- Ledger: new
- Suggested fix: Give `prune()` the settings value (the collector has settings in hand), or read it inside `expire_leases` through one helper that both callers use.

### logic-ytdl-jobs-6 - The why page tells an admin that a lower-ranked machine will be "offered the job anyway once it has waited 60s" when that is not how the job is scheduled
- Severity: low
- Confidence: CONFIRMED
- Where: dashboard/src/ccsync_dashboard/jobs.py:1052-1059
- What: Every able machine ranked below first gets the same sentence, "(choice N of M; ...; it is offered the job anyway once it has waited 60s)". But `first_refusal` gives a forced or targeted job no grace window at all, and a job older than RANK_GRACE_SECONDS is already offered to every able machine. For those jobs the sentence describes a wait that does not exist. The admin cannot tell "second choice, still inside the grace" from "offered to it right now".
- Failure scenario: An admin RUN NOWs (forces) a proxy job and opens why to see who will take it. It says the second machine will only be offered the job after 60 s, and they wait for something that has already happened.
- Evidence: the sentence is built without reading `job["forced"]`, `target_of(job)` or `job_age_seconds`.
- Ledger: new
- Suggested fix: Build that clause from `first_refusal`'s own inputs: "offered now" when forced, targeted or past the grace, otherwise "offered in Ns".

## Coverage note
- Not re-reported: bug-comp-media-2 (same hunt) already records that the companion's gate ignores the dashboard's base-rig idle exemption and per-kind floors. The logic consequence on the why side is worth adding to that fix: the base rig with somebody at it (this workstation) is "first choice, waiting to be claimed" in `explain` for ever, and for audio-extract/peaks it takes the 60 s rank grace from every other machine (`near_media`).
- Not read in depth: ytdl/web worker search/enrich/filter phases, claude_cli.py/ai_backend.py, ytdl_cookies/ytdl_browser_login, jobs_media recipes (another hunter owns their bugs), cards_exec pinning (bug-dash-cards-jobs-3 covers the stall), tools/jobs.py, and the Settings -> JOBS template.
- The requester-first claim/lease/reclaim path has been hunted five times. I looked for rule contradictions and found none beyond -2 and -3.

## OUT OF TERRITORY
- none
