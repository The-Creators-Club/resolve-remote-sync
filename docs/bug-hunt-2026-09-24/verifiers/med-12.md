# Verifier med-12 (2026-09-25)

Judged against HEAD (63d4290) via `git show HEAD:<path>`; nothing in the tree was edited.

## logic-ytdl-jobs-1 - CONFIRMED (medium)
`fleet_facts` (jobs.py:610) reads every `machine_state` row, and `fetch_capabilities_map` (db.py:11401) filters only `cap_at IS NOT NULL`. `grep reported_at|silent|stale jobs.py` finds no silence bound anywhere in fleet_facts, machine_facts, policy_refusal, ranked_machines or explain. A machine that last reported weeks ago is therefore ranked with its last `idle_seconds`, can make `explain` say "schedulable" or keep the worst-answer `idle_wait`/transient, and can win the 60 s rank grace. The job is still claimed by a live machine after the grace, so the damage is a misleading why/schedulable answer plus a delay, not a stuck queue: medium is right.
Evidence: jobs.py:487-676, 974-1010; db.py:11401-11413.

## logic-ytdl-jobs-2 - REFUTED (intended)
The mechanism is real (claim_next_job's NOT EXISTS counts a locally leased `downloading` row as the editor's busy job), but it is a documented decision: docs/YTDL_TERMS_AND_QUEUE.md section 4 says "a job an editor's machine is downloading is BUSY for its own editor (it is in the `downloading` phase) and invisible to the worker, which is both of the properties it had before", and claim_next_job's docstring scopes the lease clause to "does not queue the FLEET behind them". It is also the same one-job-per-editor rule a server-side download applies. This is a feature request (let searches run beside a local download), not a defect.
Evidence: ytdl/web/ytdlweb/db.py:341-348, 930-975; docs/YTDL_TERMS_AND_QUEUE.md:259-273.

## logic-ytdl-jobs-3 - CONFIRMED (medium)
`git show HEAD:ytdl/web/static/app.js | grep handed_back` finds nothing: `pollLocalProgress` stores the row in `state.localLive` and `localProgressLine` never reads `handed_back_reason` or a `handed_back` phase, and `ensureLocalProgress` only polls when `download_mode === 'local'`, so the pre-lease hand-backs (free space, unmounted tree, not our project) are never fetched at all. CR-171 built the companion half and LOOPBACK_API.md promises "a page that polls after the 202 learns why"; CR-172 (the page wave) never consumed it. One qualification: the claim-refusal half is deliberately silent (FleetClient.claim docstring: "none of them is an error the editor should see"), so that part is design, but the unconsumed reason alone keeps the finding real against the owner's "some feedback when it doesn't do it" ask.
Evidence: app.js:2668-2745; ytdl_executor.py:1127-1186, 1949-2061, 3296-3320; KNOWN_BUGS CR-171 / CR-172; docs/LOOPBACK_API.md:215-230.

## logic-release-2 - CONFIRMED (medium)
`retract_record` (publish_feed.py:723-743) pops `current[kind/platform]` when it names the retracted version and sets nothing in its place; the CLI branch (1146-1172) adds no replacement pointer either. `select_offered_records` (release_feed.py:648-674) falls back to the highest version when a pair has no pointer, so a newer STAGED record becomes what every `policy = current` site publishes and makes current (subject to the soak gate). publish_latest itself tells the operator a staged build is "offered to nobody, on any policy", so a retract that promotes it is a real surprise on the recall path.
Evidence: code read of both functions and `_apply_policy` (release_feed.py:947+).

## logic-release-3 - CONFIRMED (medium)
`record_offer_state` (release_feed.py:884-944) walks every `package_records(valid_records)` companion record into `feed_offered`, never `select_offered_records`, whereas `_apply_policy` uses the pointer. `_check_fleet_current_with_vendor` (invariants.py:814+) takes `_newest` of that list and reports "the vendor offers X and this server has not published it". A staged record (the documented publish_latest outcome without --make-current) or a pointer moved back therefore makes every customer's invariant, versions-behind alert and HEALTH box report a problem the server correctly is not acting on. The `feed_publish_refused` half is currently dormant because no record carries `requires_dashboard` (see logic-release-5).
Evidence: release_feed.py:866, 884-944, 947-975; invariants.py:797-860.

## logic-release-4 - CONFIRMED (medium)
`dashboard_update.status` (du.py:1652-1692) builds `code_updates` from every dashboard record newer than running, sorted highest first, and `_dashboard_auto_apply_reason` (release_feed.py:1078-1134) takes `updates[0]` after only the failed-before and soak-age checks; `channel_current` is never consulted for `dashboard/linux`, although the local feed/channel.json carries `"dashboard/linux": "0.7.44"`. A dashboard bundle published without --make-current is therefore auto-applied (with a container restart) at every image-mode `policy = current` site once the soak age passes, and a pointer moved back does not roll anything back.
Evidence: code read; `python` over feed/channel.json shows the current map includes dashboard/linux.

## logic-release-5 - DOWNGRADE (low)
Mechanism verified: publish_feed passes the manifest's `requires_dashboard` into sign_release in-process, which drops it with a NOTE on stderr unless `--emit-kind-extras`/`CCSYNC_EMIT_KIND_EXTRAS=1`; publish_latest never passes it and `publish()` writes `err` only on rc != 0. The local channel has 99 records, 0 with `requires_dashboard`. But the customer-side absence of the ordering check is the deliberate REL-4/REL-16 overlap policy documented at sign_release.py:369-389, not a new defect; what remains is a pre-publish gate that is advisory-only and a swallowed note. The false-refusal case (a) cannot fire today (REQUIRES_DASHBOARD is 0.7.23, below the 0.7.44 bundle) and has `--allow-behind`. Misleading tooling with an escape hatch: low.
Evidence: tools/sign_release.py:360-395; tools/publish_feed.py:178-215, 947-948, 1195-1205; tools/publish_latest.py:276-282, 428-445; companion config.py:173.

## logic-release-6 - CONFIRMED (medium)
In publish_latest's loop the `already` skip (lines ~446-450) runs before `publish()` and ignores `--make-current`, printing "nothing to do"; the success summary for a staged publish still says "Re-run with --make-current when you are ready". RELEASE_PATHWAYS.md step 4 already documents that the flag cannot be added after the fact and that the recovery is a per-record same-bytes publish_feed, so the tool's own advice contradicts the runbook and leaves the fleet on the old build while the operator believes it is live.
Evidence: tools/publish_latest.py:446-510; docs/RELEASE_PATHWAYS.md:48-63.

## Duplicates
None within the group. logic-release-7 (low, not mine) shares the root of logic-release-6 (no pointer-only move).
