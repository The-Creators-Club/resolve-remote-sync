# bug-ytdl-web - pre-launch bug hunt, ytdl/web and its dashboard mount (2026-10-06)

Covered (read end to end): `ytdl/web/ytdlweb/routes_fleet.py` (claim, heartbeat, manifest, clip status, hand-back),
`db.py` (lease CAS functions, queue, cancel, boot recovery, ledger, subject/forget functions), `worker.py`
(loop, run_job, phase_start/terms/search/enrich/fill_from_search_page, the whole download phase, reclaim,
CR-360 hand-back retry, manifest writer), `routes_api.py` (create/url create, start_download, mode-lock,
cancel, poll, manifest, free-space and tree guards), `projects.py`, `identity.py`, `session.py`,
`ai_backend.py`, `ytdlp_nightly.py`, the canary header; `dashboard/src/ccsync_dashboard/ytdl.py` (YtdlGate,
YtdlFeatureGate, mount, store helpers), `ai_providers.lookup_payload/make_lookup`, the login_gate fleet
bypass in `app.py`, `dashboard/deploy/run.sh` nightly block, and the companion executor's heartbeat refusal
set. Checked against KNOWN_BUGS (CR-360/361, CR-286*), docs/bug-hunt-2026-09-24 (logic-ytdl-jobs-2 was
refuted as by-design and is not re-reported).
Not covered: `claude_cli.py` prompt bodies and parsers, `vendor/downloader.py` / `ytsearch.py` internals,
`static/app.js` beyond an innerHTML/href scan, the companion side of the executor (other lens).

### bug-ytdl-web-1 - Turning the YouTube downloader OFF does not stop the server downloading; it hands every in-flight local download to the server IP
- Severity: high
- Confidence: CONFIRMED
- Where: dashboard/src/ccsync_dashboard/ytdl.py:534-560 (YtdlFeatureGate._current / __call__), :806-819 (worker + canary started once, never stopped); ytdl/web/ytdlweb/worker.py:170-201, 244-277 (no feature check anywhere in the loop); ytdlp_nightly.py:440-470 (refresher checks only env); companion ytdl_executor.py:388 (404 = CredentialLost, stop)
- What: the site switch (`[features] youtube_download`, the customer's lawfulness decision per docs/legal/YOUTUBE_FEATURE_NOTICE.md) is enforced only by the ASGI gate returning 404. Once the sub-app has loaded, the worker thread, the canary and the nightly refresher keep running for the life of the process, and nothing they do checks the switch.
- Scenario: a customer's admin unticks the downloader on Settings because their counsel says it is not lawful for them. Jobs already `queued`/`downloading` carry on: the worker runs the next queued search (AI spend + YouTube requests) and downloads every pending clip from the NAS IP. Worse, a job a companion is downloading locally gets 404 on its next heartbeat, the companion stops (CredentialLost), the lease expires after 180 s, and `_phase_download` reclaims it and fetches the rest from the server. The "off" switch actively moves downloads onto the studio IP. Only a container restart stops it.
- Recommendation: make the worker loop (and `_tick`/`run_job`, canary, nightly refresher) ask the same feature predicate (cached a few seconds) and idle when it is off; on the transition to off, pause (do not reclaim) leased jobs, e.g. by not treating an expired lease as reclaimable while the feature is off. Add a test that flips the switch mid-job.
- Known: no (CR-361 adds the refresher to the same unguarded start).

### bug-ytdl-web-2 - A deleted person's username stays in manifest.json files in the footage tree
- Severity: medium
- Confidence: CONFIRMED
- Where: ytdl/web/ytdlweb/db.py:2085-2130 (manifest_json writes `created_by`), worker.py write_manifest; db.py:2323 forget_requester; dashboard ytdl.py forget_requester
- What: every finished download writes `manifest.json` / `manifest.<id>.json` beside the clips with `created_by: <username>`. The LG-3 delete pseudonymises the name in ytdl.db only; no code rewrites or regenerates those files, and the docstring says they "outlive the database".
- Scenario: a freelancer asks to be deleted; the dashboard reports the delete done; every Youtube/<term>/manifest.json they created in every project (synced to every editor by lane C) still names them. An erasure request that is reported complete but is not is the legal exposure LG-3 exists to remove.
- Recommendation: either stop writing the requester's name into the on-disk manifest (write the stand-in or nothing), or have forget_requester regenerate the manifests of the subject's jobs with the stand-in; list the files in the export too. Document it in PRIVACY.md either way.
- Known: no

### bug-ytdl-web-3 - A suspended editor's machine can still claim, heartbeat and finish downloads on the shared-token path
- Severity: medium
- Confidence: PLAUSIBLE (code path confirmed; depends on the deployment still using the shared DASH_REPORT_TOKEN for that editor)
- Where: dashboard/src/ccsync_dashboard/ytdl.py:246-279 (`_fleet_stamp`: the account bar is checked only for `cce1.` tokens; the shared token stamps `shared`); ytdl/web/ytdlweb/routes_fleet.py:136-180, 242-283 (`require_identity` verifies only the HMAC and expiry)
- What: security-1 closed the suspension hole for per-editor tokens only. A companion presenting the shared token plus that editor's 30-day signed identity token passes with no account check, and the attestation row (the only other gate on claim) survives suspension.
- Scenario: an admin suspends a freelancer whose laptop still holds the shared token. For up to 30 days the laptop can claim any `downloading` job by its sequential integer id (job sharing across editors is allowed by design), pull its manifest and download into the shared tree, which is exactly what security-1 said must stop.
- Recommendation: apply `api.account_bar_reason` to the identity-token editor on the shared-token path too (the gate can decode the identity header), or stamp `shared:<editor>` only after the check. The same gap exists in the broll/music gates.
- Known: related to security-1 (2026-09-11b), which fixed only the cce1 shape.

### bug-ytdl-web-4 - The server pulls and imports an unpinned yt-dlp nightly from PyPI into the process that holds every fleet secret
- Severity: medium
- Confidence: CONFIRMED (deliberate, owner decision)
- Where: ytdl/web/ytdlweb/ytdlp_nightly.py:85-90, 300-350 (`_child_env` keeps the full environment); dashboard/deploy/run.sh:384-423, 587-589
- What: `pip install --pre --upgrade --no-deps yt-dlp` with no version or hash, verified by importing it in a child that inherits the whole environment (DASH_SESSION_SECRET, DASH_REPORT_TOKEN, TRUENAS_API_KEY ...), then put on the dashboard's PYTHONPATH (ahead of site-packages) at the next start. The trust anchor is whoever can publish a `yt-dlp` pre-release on PyPI, and the code dir lives under /data, writable by the uid the app runs as.
- Scenario: a compromised nightly (or any file-write bug in the dashboard that can drop a file under /data/ytdlp-nightly/versions) becomes code in the dashboard process on every customer's NAS within a day, with the session secret (forge any admin) and the NAS API key in reach. This contradicts the repo's own trust-model-7 rule ("a checksum is a CONDITION") for anything it installs.
- Recommendation: decide this explicitly for customers before selling: ship it off in vendor builds (`YTDL_YTDLP_NIGHTLY=0`) or pin to nightlies the vendor has vetted and signed through the existing release feed; at minimum run the verify child with an allow-listed env (ai_backend's `_cli_env` rule) and keep the code dir read-only to the app uid.
- Known: CR-361 (BUILT, unshipped)

### bug-ytdl-web-5 - A job whose last owed clip is in the server's hands waits a full lease before it can finish
- Severity: low
- Confidence: CONFIRMED (by trace)
- Where: routes_fleet.py `_after_terminal` (hands back only when `remaining == 0`); worker.py `_phase_download` stand-down at the top of each iteration
- What: when the claim lands while the worker is mid-clip X (X already `downloading` on the server, so not in the companion's manifest), the companion's last status post sees `remaining == 1` and does not hand back; the worker finishes X, then sees the live lease and returns. Nobody ends the lease, so the job sits in `downloading` until it expires (180 s), then the worker reclaims, finds nothing pending and closes it.
- Scenario: a 2-clip paste with requester-first on: the page shows "downloading" for three extra minutes after both clips are on disk.
- Recommendation: in the worker, after finishing a clip and finding a live lease, re-check `unfinished_downloads == 0` and end the lease / close out itself.
- Known: no

### bug-ytdl-web-6 - The worker waits out the local-claim grace on jobs that can no longer be claimed
- Severity: low
- Confidence: CONFIRMED
- Where: worker.py `_await_local_claim` (checks `created_local` but not `mode_lock`)
- What: after a hand-back (`end_lease`), a reclaim, or an editor's "download on the server" pin, `mode_lock='server'` makes every claim 410, yet `_phase_download` still sleeps up to `LOCAL_CLAIM_GRACE_SECONDS` (4 s) on the single, fleet-serial worker thread.
- Scenario: every second-chance retry and every pinned job costs every editor in the fleet 4 s of queue time.
- Recommendation: return False from `_await_local_claim` when the row's `mode_lock` is `server`.
- Known: no

### bug-ytdl-web-7 - No cap on how many searches one editor can queue
- Severity: low
- Confidence: CONFIRMED
- Where: routes_api.py create_job / create_url_job (the one-job 409 became an unbounded queue, 2026-08-30)
- What: any signed-in editor can queue any number of searches; each runs AI calls billed to the customer's key and up to ~24 YouTube searches plus a metadata pass from the studio IP, which is what got the IP bot-checked before.
- Scenario: a script, a client retry loop or an impatient editor queues 50 searches; the fleet-serial worker spends hours on them, other editors wait, the AI bill grows and the IP gets flagged for everyone.
- Recommendation: a per-editor queue limit (for example 10 queued) answered with a 409 that names it.
- Known: no
