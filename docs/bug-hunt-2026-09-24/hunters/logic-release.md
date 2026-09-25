# logic-release - the release + upgrade pathway: can an operator be misled into shipping or rolling back the wrong thing?
Files read (approximate coverage): tools/publish_latest.py (all), tools/publish_feed.py (docstring, parse_args, main through the record checks, merge/retract/current helpers, write_channel), tools/release_key.py (all), tools/sign_release.py (kind-extras emission), tools/ship.ps1 (steps 0 to 3, resume journal), dashboard release_feed.py (channel_current, select_offered_records, _valid_records, record_offer_state, _apply_policy, dashboard auto-apply), dashboard_update.status, package_store.what_is_running (feed half), invariants._check_fleet_current_with_vendor, alerts._check_versions_behind, docs/RELEASE_PATHWAYS.md (all), docs/RELEASE.md (pathway B, recall, rotation, floor), docs/RELEASE_FEED.md §2.1. Skimmed only: companion upgrade.py (floor helpers), supervisor.py, release_trust.py, release.ps1.
Tests/probes run: a snippet from the dashboard venv calling publish_feed.retract_record + release_feed.select_offered_records on a three-record channel (result below); a read of this rig's feed/channel.json (the last-published channel) to count which signed fields the live records actually carry; publish_feed.py argparse on the printed recall line (duplicate of bug-ops-3, not re-reported).

## Findings

### logic-release-1 - The documented key rotation signs the "overlap" release with the NEW key, and the refusal then tells the operator to override it
- Severity: high
- Confidence: CONFIRMED
- Where: docs/RELEASE.md:675-678; tools/release_key.py:109-121 (cmd_new --force); tools/publish_feed.py:1250-1265 (REL-7 refusal text)
- What: Rotation step 1 says run `release_key.py new --force` then `bake --add`, and then "Ship this build with the OLD key still signing". But `new --force` moves the old key to `release.key.superseded` and writes the new key at `release.key`. Every signer (`sign_release.py`, `publish_feed.write_channel`, `publish_latest`, `build_editor_package.ps1`) reads `release.key`, so the overlap build is signed with the new key. Nothing in the runbook says how to sign with the old one (`--key` / `CCSYNC_RELEASE_KEY` pointing at `.superseded`). `publish_latest.py` has no `--key` option at all.
- Failure scenario: the operator follows step 1 and publishes. REL-7 refuses correctly: "signed with key X, which v<current> does not trust ... A rotation costs an overlap release: bake --add, ship THAT (it trusts both keys) ... Pass --allow-key-rotation if this is that deliberate step". The operator is shipping exactly what they think is that overlap build, so they pass `--allow-key-rotation`. Every machine on the current build then refuses it permanently. On the feed path the CHANNEL itself is also re-signed with the new key, so every customer dashboard whose `DASH_RELEASE_PUBKEYS` pins the vendor's old key rejects the whole channel. The result is fleet-wide stranding with no over-the-air recovery, reached by following the runbook step by step.
- Evidence: release_key.py:118-121 (`path.replace(backup)`, then `write_secret(path, new)`); publish_feed.py:413 and sign_release.py:414 read `release_key_mod.key_path(args.key)`, whose default is release.key; RELEASE.md:675-678; publish_latest.py has no key passthrough (its argparse, lines 285-326).
- Ledger: new (related to REL-7, CR-59)
- Suggested fix: rewrite step 1 as "generate the new key to a SIDE path (`new --path ...new.key`), `bake --add` its public half, and keep signing with release.key". Make the REL-7 refusal say "if the build you are publishing already bakes both keys, you must sign it with the OLD key; --allow-key-rotation is only for the release AFTER the fleet has taken that overlap build".

### logic-release-2 - Retracting the build the channel points `current` at makes every `policy = current` site auto-publish a newer build the vendor had only STAGED
- Severity: medium
- Confidence: CONFIRMED
- Where: tools/publish_feed.py:723-743 (retract_record pops the pointer); dashboard/src/ccsync_dashboard/release_feed.py:648-674 (select_offered_records: no pointer means the highest version wins)
- What: `retract_record` removes the retracted record AND the `current[kind/platform]` entry, and sets no replacement. On a customer dashboard, a (kind, platform) with no pointer falls back to "highest version on the channel". If the vendor has a newer build on the channel that was published WITHOUT `--make-current` (staged: "nobody is offered this yet, on any policy", as publish_latest says), that staged build becomes the selection.
- Failure scenario: channel has 0.9.77, 0.9.78 (current) and 0.9.79 (staged for internal testing). 0.9.78 turns out bad, and the vendor runs `--retract companion/windows/0.9.78`. Every `policy = current` site now downloads 0.9.79, which the vendor never promoted, and makes it current as soon as its soak gate passes (immediately with `soak_minutes = 0`). The operator believed they were rolling the fleet BACK. Probe: select_offered_records gives 0.9.78 before the retract, and 0.9.79 after it with `pointer: {}`.
- Evidence: the snippet above, run in the dashboard venv; publish_feed.py:739-742.
- Ledger: new (related to release-pipeline-5 / REL-3)
- Suggested fix: when `--retract` removes the current record, require the operator to name the new current (`--make-current-version`), or default the pointer to the highest remaining version that was EVER current, and print which one customers will now receive.

### logic-release-3 - A STAGED vendor record (and a pointer moved back) counts as "offered" on every customer dashboard: invariant, alert and notice cry wolf
- Severity: medium
- Confidence: CONFIRMED
- Where: dashboard/src/ccsync_dashboard/release_feed.py:909-937 (record_offer_state walks every record, not select_offered_records); invariants.py:812 (_check_fleet_current_with_vendor takes the max of `feed_offered`); alerts.py:2379 (_check_versions_behind counts them); package_store.py:600-653 (what_is_running `newest_offered` / `behind_vendor`, dashboard half too)
- What: `record_offer_state` writes EVERY companion version on the channel into `feed_offered` and raises `feed_publish_refused` for any of them that needs a newer dashboard. It ignores the channel's signed `current` pointer, which `_apply_policy` uses to decide what is actually on offer. Every downstream reader then takes the highest one as "what the vendor offers".
- Failure scenario: (a) the vendor runs `publish_latest.py` without `--make-current` (a documented staged publish). Every customer dashboard's invariant 11 fires "the vendor offers 0.9.79 and this server has not published it". The HEALTH box says the fleet is behind the vendor, and computers count one more release behind, although `_apply_policy` correctly never offers it. (b) The vendor rolls back by moving the pointer backwards (the mechanism the `_apply_policy` comment names). From then on every customer permanently reports "published here but not current", or "has not published it", for the build that was withdrawn by pointer. The next action the notice gives ("update from the vendor feed") does not exist. Non-technical admins are told the server is wrong when it is right.
- Evidence: code read; `_apply_policy` uses `select_offered_records(package_records(valid_records), channel)` while `record_offer_state(conn, valid_records, now)` loops `package_records(valid_records)` without it.
- Ledger: new (related to CR-156 / SYS-2)
- Suggested fix: build `feed_offered` and the refusal notices from `select_offered_records(...)`, the one record per pair the pointer names, so "offered" means what the auto-publish acts on. Do the same for the dashboard `newest_offered`.

### logic-release-4 - The dashboard's own auto-update ignores the channel's `current` pointer, so a STAGED dashboard bundle is applied fleet-wide
- Severity: medium
- Confidence: CONFIRMED
- Where: dashboard/src/ccsync_dashboard/dashboard_update.py:1652-1692 (status builds code_updates from every dashboard record, highest first); release_feed.py:1078-1135 (_dashboard_auto_apply_reason takes `code_updates[0]`)
- What: `publish_feed.py` maintains `current["dashboard/linux"]` (this rig's last published channel has it at 0.7.44), and RELEASE_FEED.md §2.1 says a record published without `--make-current` is STAGED. On `policy = current`, `apply_dashboard_policy` applies the HIGHEST verified dashboard bundle newer than the running code once the soak age has passed, and never consults `channel_current`. A dashboard bundle cannot be staged or held, and a pointer moved back does not roll a customer dashboard back either.
- Failure scenario: the vendor publishes dashboard 0.7.57 with `publish_feed.py --kind dashboard ...` and no `--make-current`, as the two-step in RELEASE_PATHWAYS.md:81-84 shows. The intent is to try it on the studio first. Every customer on `policy = current` applies it after `soak_minutes`, which restarts their container, while the operator was told a staged record is offered to nobody.
- Evidence: code read (status() loops `release_feed.dashboard_records(...)` with no pointer lookup); feed/channel.json `current` carries a `dashboard/linux` key that nothing on the dashboard side reads.
- Ledger: new
- Suggested fix: in `_dashboard_auto_apply_reason`, auto-apply only the version `channel_current` names for `dashboard/linux`, falling back to the highest only when the channel has no pointer. Keep the other versions as manual [ APPLY ] rows.

### logic-release-5 - publish_latest's dashboard-ordering gate judges a `requires_dashboard` that is never signed, and hides the note that says so
- Severity: medium
- Confidence: CONFIRMED
- Where: tools/publish_latest.py:428-445 (SYS-7 gate reads `meta["requires_dashboard"]`); tools/sign_release.py:379-389 (drops it unless --emit-kind-extras / CCSYNC_EMIT_KIND_EXTRAS=1); tools/publish_latest.py:80-89 and 276-282 (stderr shown only on a non-zero exit)
- What: the CI manifest always carries `requires_dashboard` (release.ps1:805 / release_macos.sh:742), and publish_latest refuses or passes on it, with text saying customers "would publish this build and never offer it". But `publish_latest` never passes `--emit-kind-extras`, so `sign_release` strips the field from the signed record. Its NOTE goes to stderr, which `publish_latest.run()` captures and discards on success. None of the 99 records on this rig's last-published channel carries `requires_dashboard` (0 records), nor `arch`.
- Failure scenario: (a) REQUIRES_DASHBOARD is bumped to a version above the newest dashboard BUNDLE on the channel (0.7.44 today, while dashboards actually move by image to 0.7.56). publish_latest refuses and sends the operator to publish a dashboard bundle first, a requirement no customer would enforce. (b) The gate passes, and the operator believes the ordering rule protects customers, but a customer on an older dashboard is offered and made current on the new companion with no check at all. The one line that says so is swallowed.
- Evidence: python over feed/channel.json: "0 records carry requires_dashboard, 26 carry baked_pubkey_ids, 0 arch"; publish_latest.publish() writes `err` only when rc != 0.
- Ledger: new (related to REL-4 / SYS-7 / CR-247)
- Suggested fix: run the SYS-7 gate only when kind extras will actually be emitted, and otherwise print one line: "requires_dashboard X is NOT signed into this record (kind extras off): customers get no ordering check". Always echo publish_feed's stderr.

### logic-release-6 - "Re-run with --make-current when you are ready" is a no-op: the re-run skips the version as already published
- Severity: medium
- Confidence: CONFIRMED
- Where: tools/publish_latest.py:491-494 (the STAGED advice); tools/publish_latest.py:446-450 (the `already` skip, which ignores --make-current)
- What: after a staged publish the summary tells the operator to re-run with `--make-current`. On the re-run, `(kind, plat, version) in already` is true, so it prints "already on the published channel -- nothing to do" and never calls publish_feed. The pointer is not moved and the summary lists it as "skipped", with no word that it is still staged. RELEASE_PATHWAYS.md:53-63 records this trap, and says the recovery is a same-bytes republish per record through publish_feed.py by hand, yet the tool still gives the advice that does not work. With `--force` it works only while the same run is still the newest green one; otherwise it hits the different-bytes refusal.
- Failure scenario: Alex (or a session) publishes staged, is told the re-run makes it current, runs `publish_latest.py --make-current`, sees "nothing to do", and concludes it is live. Customers on `policy = current` keep being offered the previous build indefinitely.
- Evidence: code read of the loop order (skip at 446 precedes publish at 462; `extra` carries `--make-current` but is never used on the skip path).
- Ledger: new
- Suggested fix: when `--make-current` is given and the version is already on the channel with the same sha256 as this run's artifact, call publish_feed to move the pointer (same bytes pass the replace check). When the bytes differ, print the exact per-record recovery command instead of "nothing to do".

### logic-release-7 - `--allow-older` is documented as the rollback, but publish_latest cannot roll the vendor feed back, and no tool moves the pointer alone
- Severity: low
- Confidence: CONFIRMED
- Where: docs/RELEASE.md:182; tools/publish_latest.py:452-460; tools/publish_feed.py:1323-1325 (set_current only inside the `--artifact` branch)
- What: publish_latest only ever takes the newest green CI run, so a rollback target (an older, already published version) is either skipped as "already published" or is not the run it looks at. `--allow-older` only fires when the newest CI build happens to carry a lower version, which is the trap RELEASE_PATHWAYS warns about, not a rollback. publish_feed can only move `current` while publishing an artifact, so rolling the channel back means finding and re-uploading the old asset's exact bytes with `--make-current`, a procedure no doc names.
- Failure scenario: a bad 0.9.78 is current on the feed. The operator reads RELEASE.md "--allow-older for a deliberate rollback", runs `publish_latest.py --allow-older --make-current`, and gets "v0.9.78 is already on the published channel -- nothing to do". The fleet stays on the bad build while the operator believes a rollback was attempted, and then reaches for `--retract`, which triggers logic-release-2.
- Evidence: code read.
- Ledger: new
- Suggested fix: add `publish_feed.py --set-current KIND/PLATFORM/VERSION` (sign the channel only, no artifact) and point RELEASE.md's rollback line at it. Reword `--allow-older` as "publish a CI build whose version is lower", not "rollback".

## Coverage note
Not reached in depth: companion upgrade.py beyond the floor helpers, supervisor.py, release.ps1, release_trust.py, dashboard_update apply/rollback flow, check_deploy_drift.ps1. Two defects in my territory are already in this hunt and were NOT re-reported: bug-ops-2 (`ship.cmd -Resume` blocked by the step-0 "already published" check) and bug-ops-3 (publish_latest's printed recall command does not parse). Also seen and not reported: publish_latest aborts mid-loop through fail() after earlier sources were already published, so the summary (what was published, the recall hint) is never printed. And it prints "WARNING: tests skipped" for a build that publish_feed then refuses with exit 3, with no --allow-untested passthrough.

## OUT OF TERRITORY
- tools/publish_feed.py:265-305 merge_into_published: the local feed/ dir OVERRIDES the published `current` pointer and records per key ("anything both have is taken from the local copy"). A stale feed/ on this rig re-asserts an old pointer after a publish from anywhere else, and the --allow-replace check compares against the merged local copy rather than the published record.
