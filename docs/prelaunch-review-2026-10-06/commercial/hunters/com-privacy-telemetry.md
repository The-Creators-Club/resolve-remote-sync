# Pre-launch commercial review 2026-10-06: privacy and telemetry (com-privacy-telemetry)

Lens: privacy engineering in code. What personal data each component collects,
where it goes, how long it stays, whether the LG-1 reporting switches do what
the disclosure says, what the triage agent sends to an AI provider, which logs
and stores hold personal data, and transfers to AI providers and to the vendor.

Covered (read end to end, or probed): `docs/legal/PRIVACY.md`,
`docs/legal/TELEMETRY.md`, `docs/COMMERCIAL_READINESS.md` (privacy and legal
items), the companion's report builder (`reporter.py:_build_payload`,
`capabilities.py`, `app.py:sync_guard`/`jobs_gate`/`job_capabilities`,
`jobs_runner.py` gate states), both copies of the telemetry field table
(`companion/.../telemetry_policy.py`, `dashboard/.../telemetry_fields.py`),
`triage.py` (bundle, scrub, CLI argv, prune), `cards_ai.py` (conversation
store, CLI session flags), `cli_tools.py` (the setup notice, `cli_env`),
`ai_providers.py` (order, DeepSeek scope), `db.py` prune and the subject-data
registry, `sessions.py` (IP and user-agent storage, prune), the ytdl database's
deletes, `syncthing_client.py`, the uninstallers, the rclone `remote_down`
route. One probe: `triage.build_bundle` + `triage.scrub` against a scratch
database (below, finding 2).

Not covered: the music/broll indexers' own logging, the Cards fork's on-disk
working records in the other repo, the Mac uninstaller's `--full` path in
detail, the contents of the dashboard's export file beyond the registry.

Already fixed and not re-reported: the four LG-1 switches exist and strip on
both sides for the fields they list; diagnostics bundles are redacted or
replaced under a switch; the export/erase registry is coverage-tested;
container logs are size-capped; access logs are off by default.

### com-privacy-telemetry-1 - The "idle time" switch does not stop the at-the-keyboard signal: `jobs_gate` reports `user_active`

- Severity: high
- Confidence: CONFIRMED
- Where: companion/src/ccsync_companion/capabilities.py:264-282 (`_withhold` blanks only `idle_seconds` and `resolve.project`), capabilities.py:321-368 (`jobs_gate` added live, unfiltered), companion/src/ccsync_companion/app.py:5951-5988 (`jobs_gate` returns `reason = state`), companion/src/ccsync_companion/jobs_runner.py:98,133,729-734 (`STATE_USER_ACTIVE` "Somebody is at this computer"), dashboard/src/ccsync_dashboard/telemetry_fields.py:78-80 (input_idle strips only `capabilities.idle_seconds`), dashboard/src/ccsync_dashboard/db.py:12745-12830 (persisted as `machine_state.cap_jobs_gate_reason/_detail`); also companion broll_ingest.py:1189/1248 (`broll_ingest.gate` can be `user_active`)
- What: With `report_input_idle = false` (computer) or the site TELEMETRY switch off, `capabilities.idle_seconds` goes as null, but the job runner still reads the idle probe locally and its verdict rides every tick as `capabilities.jobs_gate = {"reason": "user_active" | "ready" | "nothing_offered" | ...}`. The runner checks `_user_is_away()` before it checks whether anything is offered, so the state flips between `user_active` and `nothing_offered` purely on keyboard/mouse activity. The dashboard stores it per machine and shows it on the jobs `why` view and in the triage evidence. Neither the companion's nor the dashboard's field table lists `capabilities.jobs_gate` (or `broll_ingest.gate`) under `input_idle`, so the site switch's server-side strip does not remove it either.
- Scenario: a German customer's works council agrees to rollout on the condition that keyboard presence is not reported, and the admin turns off "time since last input" for the site. Every 5-60 s each editor's machine still reports `user_active` vs `nothing_offered` (the 5-minute `jobs_idle_seconds` threshold), stored on `machine_state` and readable by every admin: a presence log at 5-minute granularity. TELEMETRY.md and PRIVACY.md section 6 tell the DPO the opposite.
- Recommendation: Add `capabilities.jobs_gate` and `broll_ingest.gate`/`music_ingest.gate` to `input_idle` in BOTH tables, mapping `user_active` to a neutral value (e.g. `idle_unknown`) rather than removing the key (the scheduler reads its absence as "did not say"). Do the same server-side for old companions. Add a test that, with `input_idle` withheld, no report field varies with the idle probe. Re-read the "Still sent" paragraph after the fix.
- Known: not recorded (KNOWN_BUGS mentions jobs_gate only for CMEDIA-1/12 function, not privacy).

### com-privacy-telemetry-2 - The server triage agent sends the whole fleet's monitoring data to the AI provider twice a day, scrubbed only of secrets

- Severity: high
- Confidence: CONFIRMED (probed)
- Where: dashboard/src/ccsync_dashboard/triage.py:343-375 (`build_bundle` includes `api.build_editors_view` and `api.build_transfers_view` for every machine), triage.py:273-320 (`scrub` removes only keys named password/token/secret/api_key and sk-/cce1./ghp_ values), triage.py:207-213 (CLI reads `evidence.json` + the package source), docs/legal/PRIVACY.md section 5 row "AI providers"
- What: the evidence file is the full fleet grid: for every machine, including healthy ones, the editor's username, hostname, `capabilities` (`cap_idle_seconds`, `cap_resolve_project`, `cap_jobs_gate_reason`, Cards timeline), lane errors with file paths, and the live transfer list with file names. Probe: a scratch database with one green machine (`alice`, open project "Client X Embargoed", idle 1234 s, gate `user_active`): all four strings are present in `triage.scrub(build_bundle(...))`. Nothing is pseudonymised or minimised to what is actually "open, stuck or failing". PRIVACY.md describes it as "a scrubbed report of the dashboard's open problems, including editor and machine names and error text", which understates it.
- Scenario: a customer enables triage. At 06:00 and 18:00 the presence state and open-project name of every employee, and the names of client files moving, are sent to Anthropic (via the Claude Code CLI, see finding 3) and may be quoted in the emailed report to whatever mail provider the alert sink uses. A DPO reading PRIVACY.md would not know idle times and project names leave the building.
- Recommendation: Build the triage bundle from an allow-list. Drop `idle_seconds`, `resolve_project`/`cap_resolve_project`, `jobs_gate`, and Cards timeline; include machines only when they have a non-green chip, a notice or an alert; replace usernames/hostnames with stable per-run pseudonyms (map back in code when composing the email and validating actions); cap transfer names. Then correct PRIVACY.md section 5 to state exactly what is sent. Have counsel confirm whether triage needs its own line in the customer's record of processing.
- Known: not recorded.

### com-privacy-telemetry-3 - The CLI provider route sends transcripts, fleet evidence and mail replies under a personal subscription's terms, and the notice only mentions YouTube searches

- Severity: high
- Confidence: CONFIRMED (code); the consumer-terms consequences are a legal assessment for counsel
- Where: dashboard/src/ccsync_dashboard/cli_tools.py:2346-2361 (`SETUP_NOTICE`), dashboard/src/ccsync_dashboard/ai_providers.py:85 (`PROVIDER_ORDER` puts `claude_code` first), dashboard/src/ccsync_dashboard/cards_ai.py:530-550,922 (Cards over the CLI), triage.py:28-35 (triage needs the CLI, no API fallback), triage_mail.py:366 (owner replies interpreted by the CLI), docs/legal/PRIVACY.md section 5 ("billed to and logged under the Customer's own account")
- What: the wizard's notice says "Every YouTube search this dashboard runs ... will be spent on the account you are about to sign in" and frames the risk as ToS only. Once accepted, the CLI is the FIRST provider in auto order, so it also carries all three Timeline Cards features (full interview transcripts, translations, edit-chat prompts), the triage evidence (finding 2) and the text of the owner's email replies. A personal Claude or ChatGPT plan is governed by consumer terms: no data processing agreement, no zero-retention option, and (depending on the account's settings) conversations may be used for model training. Neither the notice nor PRIVACY.md says so.
- Scenario: a studio admin signs in Claude Code with a personal Pro account to try triage. From then on every Cards transcript of every interviewee goes to Anthropic under that individual's consumer account rather than under a commercial API agreement, possibly opted in to training, and the studio has no processor contract covering it. For a documentary customer whose interviews concern health or sexuality (the studio's own "Repro Rights" episode is an example) this is special-category data.
- Recommendation: Rewrite the notice to list every feature that will use the CLI and to state plainly that consumer plans have no DPA and may train on content unless the account has opted out; require the admin to tick that separately. Prefer the API key over the CLI in auto order whenever both exist, or make the CLI apply only to the features that need it (triage). Update PRIVACY.md section 5. Counsel: decide whether to support consumer-account CLIs for customer data at all.
- Known: COMMERCIAL_READINESS item 1 records the ToS question only, not data protection.

### com-privacy-telemetry-4 - The vendor's own support processing has no DPA, no transfer mechanism, and a "no sub-processor" claim that does not match how support is done

- Severity: high
- Confidence: PLAUSIBLE (the missing documents are CONFIRMED; how support is done comes from the owner's own workflow notes)
- Where: docs/legal/PRIVACY.md section 3 ("we engage no sub-processor for it ... can request one at contact@thecreatorsclub.co"), section 11 (Licensor in Taiwan), docs/legal/ (no DPA, no SCC annex, no sub-processor list)
- What: PRIVACY.md says the Licensor becomes a processor during support (diagnostics bundles, logs, database copies, remote access), engages no sub-processor, and offers an Art. 28 DPA on request. No DPA template exists in the repo. The Licensor is in Taiwan, which has no EU or UK adequacy decision, so an EU/UK customer sending a diagnostics bundle is making a restricted transfer that needs SCCs (Module 2, controller to processor) or the UK IDTA/Addendum, plus a transfer impact assessment. In practice support mail goes to a Google-hosted mailbox, support analysis is done with Claude Code (Anthropic), and remote access over SSH/Tailscale has been used on editor machines. Those are sub-processors and must be listed.
- Scenario: the first EU customer's procurement or DPO sends the standard vendor questionnaire: "Provide your DPA, SCCs and sub-processor list." Nothing exists, and the published policy states something that is not true of the vendor's practice. That blocks the contract, or exposes the vendor if signed as is.
- Recommendation: Counsel to produce: (1) a DPA template (Art. 28(3) terms, breach-notice timeline, deletion on close, audit clause); (2) SCC Module 2 plus the UK Addendum attached to it; (3) a short sub-processor list (mail host, Anthropic if Claude is used on customer data, GitHub if bundles ever land in issues, Tailscale if remote access is used); (4) an internal support-data procedure (where bundles are kept, how long, who deletes them). Owner decision: whether support analysis may use an AI tool on customer data at all, and under which account. Then fix PRIVACY.md section 3. The real legal entity name (KNOWN_BUGS ~507, COMMERCIAL_READINESS item 4) must be settled first, because it is the contracting party on all of these.
- Known: entity-name placeholder recorded (COMMERCIAL_READINESS item 4, CR-5); DPA, SCCs and sub-processors not recorded.

### com-privacy-telemetry-5 - AI conversation stores holding interview transcripts have no retention, and are missing from the privacy policy and the export/erase

- Severity: medium
- Confidence: CONFIRMED for `cards_sessions` and that the CLI sessions persist (Cards depends on `--resume`); the CLI's own cleanup period is from its documentation, not probed
- Where: dashboard/src/ccsync_dashboard/cards_ai.py:631-672,1209-1214 (`<data>/cards_sessions/<id>.json`, written, never pruned), cards_ai.py:922 (`--session-id`/`--resume`: Claude Code keeps the transcript under `<data>/tools/claude_code/home/.claude/projects/`), triage.py:211 and triage_mail.py:366 (`-p` without `--no-session-persistence`), docs/legal/PRIVACY.md section 4 table
- What: each Cards montage conversation, which is the corpus of interview transcripts plus the editor's prompts, is saved as JSON in `cards_sessions/` with no age or count limit. The CLI path additionally keeps its own session logs, including what triage read from `evidence.json`, in the CLI's HOME inside the data directory. Neither store is in PRIVACY.md section 4 or 7, nor in the export's `not_included` list as such, and erase/delete cannot reach them.
- Scenario: an interviewee withdraws consent and the studio deletes the footage and transcript. Their words remain in `cards_sessions/*.json` indefinitely and in the CLI's session store, in every NAS snapshot and backup of `/data`.
- Recommendation: Prune `cards_sessions` (e.g. 14 days since last turn) in the collector's retention pass; pass `--no-session-persistence` for one-shot CLI calls (triage, mail interpretation, ytdl) and set a short `cleanupPeriodDays` in the CLI HOME's settings for Cards; list both stores, with retention, in PRIVACY.md sections 4 and 7 and in the export's `not_included`. In PRIVACY.md, state that transcripts of interviews can be special-category data and point the customer to the journalistic exemption (Art. 85) as their own determination.
- Known: not recorded.

### com-privacy-telemetry-6 - IP addresses are collected and kept, but the privacy policy never lists them

- Severity: medium
- Confidence: CONFIRMED
- Where: dashboard/src/ccsync_dashboard/schema.sql:15-26 (`devices.address`, the address Syncthing last saw for each editor's device, no expiry), sessions.py:100,133-140 (`auth_sessions.client` = IP + user-agent), sessions.py:107 (`login_attempts` keyed by IP), auth.py:695, ui.py:1077, oidc.py:507, setup_api.py:100 (log lines "login for %r from %s"), docs/legal/PRIVACY.md section 2 and section 7
- What: section 2's personal-data list and section 7's retention table have no entry for IP addresses. For remote editors, `devices.address` is their home connection's public IP (approximate location), refreshed by the collector and kept until the device is forgotten. Session rows keep IP and browser, and container logs record username plus IP on every sign-in.
- Scenario: a data-subject access request or a DPO review asks "what location data do you hold?" The policy says none. The export does include `devices`, so the dashboard's own output contradicts the policy.
- Recommendation: Add IP addresses (device address, sign-in sessions, throttle records, log lines) to PRIVACY.md section 2, with retention per store in section 7. Consider clearing `devices.address` when a device has been disconnected for 30 days.
- Known: not recorded.

### com-privacy-telemetry-7 - YouTube downloader records are kept forever, and search terms survive erasure

- Severity: medium
- Confidence: CONFIRMED
- Where: ytdl/web/ytdlweb/db.py (no time-based delete; deletes only on job removal or `forget_*`), docs/legal/PRIVACY.md sections 4, 7 and 8 ("Indefinitely"; search text stays on job/download records and in folder names after erase)
- What: who searched for what, which machine downloaded which video, and rights attestations are kept with no retention period and no setting to add one. Erasure pseudonymises the requester but leaves the search text, and the folder names under `<project>/Youtube/<term>/` carry it permanently.
- Scenario: an editor's searches can reveal personal interests or the subject of an unannounced story. Indefinite retention with no stated purpose fails storage limitation (Art. 5(1)(e)) and is the first thing a DPO marks in the record of processing.
- Recommendation: Owner/counsel decision on a period (attestations: life of the feature plus a limitation period; job and search records: e.g. 90 days after the job finishes). Implement it in the collector's prune. Document that folder names are content the customer controls.
- Known: COMMERCIAL_READINESS item 3, "a retention policy for the records is still open" (OPEN).

### com-privacy-telemetry-8 - TELEMETRY.md has drifted from the code it says it was verified against

- Severity: medium
- Confidence: CONFIRMED
- Where: docs/legal/TELEMETRY.md "What is NOT sent" ("No EULA acceptance record. It is written and read locally only") vs companion/src/ccsync_companion/reporter.py:1113-1120 (`payload["eula"]`, LG-5) and dashboard api.py:9483 (`EulaIn`); TELEMETRY.md "Employee monitoring" point 6 ("cannot currently be switched off individually") vs its own "What can be turned off"; field table lacks `machine_settings` (reporter.py:1082), `eula`, `report_optouts`, `capabilities.jobs_gate`; "Still sent" omits `lanes[].last_error`/`detail` (rclone stderr tails with file paths, sync/rclone_lane.py:3431,4254) that a `local_manifest` opt-out does not remove
- What: the file's header says a disclosure that has drifted is worse than none. It has drifted in both directions: it denies sending something that is sent, and it tells the DPO the switches do not exist.
- Scenario: the customer hands the table to staff as their Art. 13 notice (as the document suggests). It is wrong about the EULA record and incomplete about file paths in errors and presence (finding 1).
- Recommendation: Re-verify the whole field table against `_build_payload`; add the missing sections; delete the stale sentence in point 6; add `lanes[].last_error`/`detail` to "Still sent". Add a test that fails when `_build_payload` gains a top-level key that TELEMETRY.md does not mention (the CLAUDE.md rule already asks for a row per new key; nothing enforces it).
- Known: not recorded.

### com-privacy-telemetry-9 - Privacy by default: everything is collected out of the box, and retention periods cannot be shortened per customer

- Severity: medium
- Confidence: CONFIRMED
- Where: companion/src/ccsync_companion/config.py:833 (`jobs_enabled = True`, so `idle_seconds` is sent), config.py:894-897 (all four `report_*` default true), dashboard/src/ccsync_dashboard/db.py:39,598,605,5521,7292 (retention periods are module constants, no site setting)
- What: a fresh customer reports the open project, the disk inventory, the bin tree and keyboard idle time from every machine unless someone turns them off. Retention is fixed at 14/30/180 days with no `site.toml` knob, so a customer whose works-council agreement or DPIA requires, say, 7 days cannot comply without a code change.
- Scenario: a German or Austrian customer must have works-council agreement before rollout (PRIVACY.md section 6 says so). The default configuration is the most invasive one, and the agreed retention period cannot be set.
- Recommendation: Add `[telemetry] retention_days_*` (only shorter than the defaults) to site settings, used by `db.prune`. Owner decision on defaults: at minimum ship `input_idle` off unless the site turns on fleet jobs, since idle time exists only for the scheduler. Note the defaults in PRIVACY.md section 6 (Art. 25(2)).
- Known: not recorded.

### com-privacy-telemetry-10 - No record of which admin looked at whose monitoring data, and no admin role without access to it

- Severity: low
- Confidence: PLAUSIBLE (no audit write found on the scope/view paths; not every route read)
- Where: dashboard/src/ccsync_dashboard/auth.py (`scope_for`, `?as=<editor>` focus), fleet grid, `/partials/project/{slug}/bins`, jobs `why`; `fleet_audit` records actions and exports only (subject_data_api.py:27)
- What: any admin sees every person's open project, presence and disk contents, and viewing is not logged. There is one admin tier.
- Scenario: a works council or DPA asks "who looked at employee X's activity in March?" The product cannot answer, and the purpose limitation PRIVACY.md section 6 asks the customer to enforce cannot be checked.
- Recommendation: Log admin views of another person's machine detail (`?as=`, bins, diagnostics) to `fleet_audit`, kept 180 days. Consider an "operator" role that manages sync without seeing `resolve_project`/idle/manifest fields.
- Known: not recorded.

### com-privacy-telemetry-11 - Third-party flows missing from PRIVACY.md section 5: Syncthing crash reports, the Claude Code CLI's own telemetry, and the Cloudflare download route

- Severity: low
- Confidence: PLAUSIBLE (the repo never sets these options; what the tools send by default comes from their documentation, not a probe)
- Where: no `crashReportingEnabled`/`urAccepted`/auto-upgrade setting anywhere outside bench/ (grep), dashboard/src/ccsync_dashboard/cli_tools.py:547-558 (`cli_env` sets no `DISABLE_TELEMETRY`/`CLAUDE_CODE_DISABLE_NONESSENTIAL_TRAFFIC`), companion/src/ccsync_companion/sync/rclone_lane.py:626-665 (`remote_down`: WebDAV through a Cloudflare tunnel)
- What: Syncthing on the NAS and on every workstation runs with its defaults, which include automatic crash reports to the Syncthing project and upgrade checks. The Claude Code CLI sends its own operational telemetry and error reports to Anthropic. `remote_down` is a shipped config key whose only deployment is a Cloudflare tunnel, where TLS ends at Cloudflare's edge, so Cloudflare can see the footage in plaintext. None of the three is in the section 5 table that claims to list everything that leaves.
- Scenario: a customer's security review compares outbound traffic with the policy and finds destinations it does not mention, which undermines trust in the rest of the document.
- Recommendation: Set Syncthing `crashReportingEnabled=false` (and decide on auto-upgrade) where the companion and server configure Syncthing, or disclose it. Set the CLI's non-essential-traffic variable in `cli_env_overlay`, or disclose it. Either mark `remote_down` internal or unsupported, or add a row saying the footage is visible to the tunnel provider.
- Known: the Cloudflare trial is recorded as a studio-only trial (memory cf-lane-b-trial-2026-09-25); privacy disclosure not recorded.

### com-privacy-telemetry-12 - Uninstalling leaves a live Google session, tokens and Resolve project names on the machine

- Severity: low
- Confidence: CONFIRMED
- Where: installer/windows_uninstall.ps1:15-36,724-740 (default mode keeps `~/.ccsync`; `-Full` keeps `~/.ccsync\state`), installer/macos_uninstall.sh:13-16, companion/src/ccsync_companion/ytdl_browser_login.py:110,192 (`~/.ccsync/yt-login-profile`, a Chromium profile signed in to Google), ytdl_cookies.py (`~/.ccsync/youtube-cookies.txt`)
- What: the default uninstall keeps the identity tokens, the YouTube cookies file and the signed-in browser profile. Even `-Full` keeps `state\`, which includes Resolve project names (`project_prompts.json`).
- Scenario: a freelancer leaves and IT uninstalls CC Sync from a machine that is then reassigned. The next user inherits a working Google session of the previous editor and their report token.
- Recommendation: Make the default uninstall remove credentials (`identity.json`, `youtube-cookies.txt`, `yt-login-profile`), keeping only non-personal state. Document `-Full`/`--full` in the customer offboarding runbook.
- Known: not recorded.
