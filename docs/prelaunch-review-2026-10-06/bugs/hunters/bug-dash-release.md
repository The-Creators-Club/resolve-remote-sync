# Pre-launch bug hunt 2026-10-06: lens `bug-dash-release`

Territory: the release/upgrade trust chain. Read end to end:
`dashboard/src/ccsync_dashboard/{release_feed,release_trust,package_store,dashboard_update,android,ed25519}.py`,
the package routes in `api.py` (`api_publish_package`, `_upgrade_info`,
`api_download_package`, `targeted_staged_package`), the package/feed helpers in
`db.py` (`set_current_package`, `retract_package`, `prune_companion_packages`,
feed state), `dashboard/deploy/select_code_root.py` (boot-time tree check),
the companion's `upgrade.py` floor/verify path, `tools/publish_latest.py`,
`tools/publish_feed.py`, `tools/release_key.py`, the signing/publish section of
`installer/build_editor_package.ps1`, the dirty/feed sections of
`tools/ship.ps1`, the trigger/permission blocks of every
`.github/workflows/*.yml`, and `docs/RELEASE_FEED.md` / `docs/DOCKER.md` for
the claims the code is meant to keep. One probe (scratchpad, against
`publish_feed.merge_into_published`). Not covered in depth: `tools/release.ps1`
beyond its signing hooks, the Windows bootstrap's first-install trust,
`release_macos.sh`.

Checked against KNOWN_BUGS.md, docs/RELEASE*.md and the 2026-09-24 hunt; one
finding below is a known, still-open deferral (release-pipeline-8) and says so.

### bug-dash-release-1 - Auto-update re-applies a dashboard bundle that just crash-looped and was reverted, forever

- Severity: high
- Confidence: CONFIRMED (code path read end to end)
- Where: dashboard/src/ccsync_dashboard/release_feed.py:1144-1153 (`_dashboard_auto_apply_reason` "failed" guard), dashboard_update.py:1338-1374 (`request_restart` / `consume_restart_request` set step "done"), dashboard/deploy/select_code_root.py:427-441 (`revert` writes only current.json + boot_attempts), release_feed.py:107 (`POLLER_FIRST_CHECK_DELAY = 10.0`)
- What: the only thing that stops `policy = current` from re-applying a bundle is `read_state().step == "failed"` for that version. A bundle that passes stage-verify but fails to BOOT (lifespan crash, a new env var it refuses to start without, a bug after migration) never produces that state: the apply ends in `request_restart`, the shutdown's `consume_restart_request` writes `step: "done"`, and the boot selector's revert after `MAX_BOOT_ATTEMPTS` (2) rewrites only `current.json` (`reverted_from`, `reverted_reason`) and the boot-attempt counter. Nothing in `_dashboard_auto_apply_reason` reads `reverted_from`.
- Scenario: vendor publishes dashboard X with `--make-current`; it imports and migrates fine in stage-verify but its lifespan raises. Every customer on `policy = current` (and this studio) applies X after the soak, restarts, X fails twice, select_code_root reverts to the previous tree, the good tree boots, the feed poller checks 10 s later, sees X offered, `step == "done"`, soak long passed, and starts the apply again: download, stage-verify, DB backup, a ZFS snapshot (`snapshot_before`, when configured, never pruned here), swap, restart, two failed boots, revert... The dashboard that "tells everyone whether their footage is syncing" is down for most of every cycle, indefinitely, with a NAS snapshot per loop.
- Recommendation: treat `current.json.reverted_from == version` (and a boot-attempt refusal for it) as "tried and failed" in `_dashboard_auto_apply_reason`, exactly like `step == "failed"`; better, have select_code_root's `revert` also write a durable "do not auto-apply X" marker the poller honours until a newer version or an admin's explicit APPLY. Add a test that drives apply -> revert -> next poll.
- Known: no

### bug-dash-release-2 - The container image path bypasses the offline release key; `:1` moves on any `v*` tag and the documented cosign check verifies nothing

- Severity: high
- Confidence: CONFIRMED (workflow + compose + doc read)
- Where: .github/workflows/image.yml:57-63 (triggers), :147-176 (tag computation, `:1` on any tag), :177-230 (third-party actions pinned by mutable tag with `packages: write` + `id-token: write`); dashboard/deploy/compose.appliance.yaml:88,147,291 (`ccsync:1`); docs/DOCKER.md:560-565 (`cosign verify --certificate-identity-regexp '.*'`)
- What: every editor binary and every OTA dashboard bundle has to pass the offline ed25519 key ("CI builds, this rig signs"). The appliance image customers actually run does not: `image.yml` pushes `:<VERSION>` and moves the floating `:1` on ANY pushed `v*` tag, on any commit (no ancestry-to-main check, no test job, no environment approval), and the appliance compose pins `:1`. The image wins over any volume tree at boot, so it is the dashboard code. The only signature is cosign keyless, and the verification command the docs give accepts any certificate identity from any GitHub Actions workflow in any repository, so it proves nothing about who built the image. The docker/* and sigstore actions are pinned by tag in the job that holds `packages: write`.
- Scenario: anyone with push access (a contractor, a leaked PAT, a compromised action tag) pushes tag `v0.7.99` on a branch commit; within one CI run `ghcr.io/the-creators-club/ccsync:1` is that code, and every customer NAS that updates its app (the documented "one click is the whole update story") runs it with the dashboard's secrets, NAS API key and fleet authority. Nothing on the customer side can tell, and a customer who follows DOCKER.md's verify step gets "Verified OK".
- Recommendation: before selling, put the image under the same gate as everything else: restrict `:1`/`:<VERSION>` to tags whose commit is an ancestor of main and whose CI is green, behind a protected environment with required reviewers; pin third-party actions by commit SHA; fix the documented verify to `--certificate-identity https://github.com/The-Creators-Club/ccsync/.github/workflows/image.yml@refs/tags/v...` (exact identity); and consider having the vendor rig sign the image digest with the offline key into the channel (`dashboard_image` already rides the signed channel) so a customer dashboard can say "this image is not the one the vendor signed".
- Known: no

### bug-dash-release-3 - The downgrade floor is 0.0.0 on every record, so any old genuinely-signed build can be pushed back onto the fleet

- Severity: medium
- Confidence: CONFIRMED
- Where: tools/publish_feed.py:1042 (`--min-version` default `0.0.0`), tools/sign_release.py:281, tools/publish_latest.py:381/419 (no default passed), installer/build_editor_package.ps1:1043-1044, tools/release_macos.sh:838; companion upgrade.py:726-776 (`note_floor` / `below_floor`)
- What: the companion's monotonic floor is the only anti-downgrade defence (it accepts "different, not newer" offers by design). Every publisher defaults `min_version` to 0.0.0 and none of the routine pathways (publish_latest, ship, CI) sets it, so in practice the floor is never raised. The release key's stated purpose is that "a compromised dashboard, or a customer's own admin, can publish nothing a companion will install"; with no floor, they can still install every build ever signed since 2026-08-17, including ones carrying since-fixed security holes (loopback/CORS, cleartext transport LG-4, the trust-model fixes).
- Scenario: an attacker with a customer dashboard (or a replayed channel, see -4) makes an old signed companion current; every editor machine verifies its genuine signature, sees it above floor 0.0.0, and installs it on the next report, reopening whichever hole that build had.
- Recommendation: release-pipeline-8's own fix: a tracked `MIN_VERSION` constant in the repo, read by all three signers, raised on every release that fixes something security-relevant (and at launch to the first build you are willing to support); make publish_latest/ship print the floor they are stamping.
- Known: KNOWN_BUGS release-pipeline-8 (deferred 2026-08-21, still open)

### bug-dash-release-4 - No freshness check on the channel: a feed host can replay an old signed channel to roll back `policy = current` fleets and suppress later recalls

- Severity: medium
- Confidence: CONFIRMED
- Where: dashboard/src/ccsync_dashboard/release_feed.py:395-433 (`fetch_and_verify_channel`, no generated_at comparison), :870-875 (stores `last_channel_generated_at`, never compares), :1010-1023 (`_apply_policy` follows a backwards pointer), package_store.py:251-261 (downgrade by an unattended door skips the soak gate); docs/RELEASE_FEED.md:231-235 and :503-505 ("a stale channel just means no update is offered, not a wrong one")
- What: the threat model calls the feed host untrusted. A channel is accepted if its signature verifies, regardless of whether it is older than the one this dashboard already acted on. Because a backwards `current` pointer is deliberately honoured ("how a bad build is withdrawn"), and `make_current_refusal(bootstrap_ok=True)` waves an unattended downgrade past the soak gate, a replayed channel is an active rollback, not a stale view. Recalls in channels newer than the replayed one are never seen by a dashboard that had not fetched them yet.
- Scenario: vendor ships 0.9.85 fixing a security bug, then 0.9.86 later. Whoever controls the GitHub release assets (or a CDN/bucket in front) serves the signed channel from the day 0.9.84 was current. Every `policy = current` dashboard makes 0.9.84 current again (it is in the rows, `ever_current` or a downgrade, no soak), and every companion takes it (floor 0.0.0, -3). The docs tell operators this cannot happen.
- Recommendation: persist the highest `generated_at` accepted and refuse (as `last_error`, with a notice) any channel whose signed `generated_at` is lower; optionally refuse channels older than N days for the auto policies. Correct RELEASE_FEED.md's threat model either way.
- Known: no (RELEASE_FEED.md mentions replay but misstates its effect)

### bug-dash-release-5 - publish_feed's merge lets a stale local feed/ dir overwrite the live channel's `current` pointer and records

- Severity: medium
- Confidence: CONFIRMED (probe)
- Where: tools/publish_feed.py:275-314 (`merge_into_published`: local `current` keys and same-key records win), :1186-1198 (merge on every upload), :1567-1578 (`shrink_report` only checks removals)
- What: the published channel is the base, but the rig's `feed/channel.json` is overlaid on top: every non-empty local `current[kind/platform]` replaces the published one and every local record replaces the published record with the same key. The local dir is whatever THIS rig last wrote. A pointer move or a record correction made from any other machine (a second operator, the owner's laptop, a Mac, a fresh clone, which the docstring itself names as expected) is silently reverted by the next publish from this rig, of anything. The shrink guard does not see it because nothing is removed.
- Scenario: 0.9.83 goes bad; the owner withdraws it from a laptop with `publish_feed.py --set-current companion/windows/0.9.82` (the documented withdrawal, no retract). Next day the base rig runs `publish_latest.py --kind onboard`; merge restores `current["companion/windows"] = "0.9.83"` from the rig's stale feed dir, the channel is re-signed and uploaded, and every `policy = current` customer is re-offered the withdrawn build. Probe: published current 0.9.82 + local 0.9.83 -> merged current 0.9.83, `shrink_report` = [].
- Recommendation: overlay only what THIS run changed (the record being published, the pointer it was told to move), never the whole local document; or refuse when a local `current` key / record differs from the published one and this run did not ask to change it.
- Known: no

### bug-dash-release-6 - `ship.cmd -PublishFeed` puts a dirty or untested onboard installer CURRENT on the vendor feed, past every gate

- Severity: medium
- Confidence: CONFIRMED (code read)
- Where: tools/ship.ps1:1019-1046 (onboard item has no Manifest, always `--make-current`, no dirty flag passed), tools/publish_feed.py:962-973 (dirty/untested gates live only in `_apply_manifest`), tools/ship.ps1:375-390 (REL-13's `-IReallyMeanDirtyCurrent` only governs the studio PUT)
- What: in the feed mirror step the companion is published with `--manifest` (so publish_feed refuses a dirty or `tests_run=false` build) but the onboard installer is published with `--platform/--version` only, so neither gate runs, `--make-current` is always passed, and no `--git-dirty` reaches the record. REL-13 made "a dirty build becomes current" a second, explicit decision; for the vendor feed's onboard it is no decision at all.
- Scenario: `tools\ship.cmd -AllowDirty -PublishFeed` (or `-SkipTests -PublishFeed`) for a hotfix: the studio gets it STAGED as designed, the companion feed publish is refused, but `onboard.exe`, which bundles the dirty companion, is signed, made current on the vendor channel and handed to every new editor at every customer, with a clean provenance chip.
- Recommendation: pass the onboard's provenance (a manifest, or `--git-dirty`/tests flags) so the same gates apply; never pass `--make-current` to the feed when the ship itself refused to make the build current; skip the onboard when the companion feed publish failed.
- Known: no

### bug-dash-release-7 - Concurrent publishes of one version escape as IntegrityError: .part orphaned, check_now raises

- Severity: low
- Confidence: CONFIRMED (read; race window is short)
- Where: dashboard/src/ccsync_dashboard/package_store.py:470-494 (`held` check, then `insert_companion_package`), release_feed.py:1043-1074 (`_apply_policy` catches only PackageStoreError), :886 (`check_now` has no guard around `_apply_policy`)
- What: the dash-api-6 fix checks `get_package` and then inserts, without a lock or an `INSERT OR IGNORE`. Two writers in that window (the feed poller and an admin's Check now / PUBLISH, or a retried publish_latest landing with the first) both pass the check; the second insert waits for the first commit and raises `sqlite3.IntegrityError`, which is not a PackageStoreError: the `.part` (up to 200 MiB, in the packages dir, swept only by the PUT route) is left behind, the connection's transaction is left open, and on the feed path the exception leaves `check_now` (a 500 on Check now, "poller cycle failed" in the log) instead of "already published".
- Scenario: admin presses [ CHECK NOW ] at the moment the daily poller is storing the same record on a `stage` site.
- Recommendation: catch IntegrityError inside store_verified_package, roll back, unlink the part and re-run the `held` comparison; or serialise the tail with a process lock.
- Known: no (dash-api-6 addressed the file-swap half of this race)

### bug-dash-release-8 - Boot-time tree check verifies the signed record but never the files it boots

- Severity: low
- Confidence: CONFIRMED
- Where: dashboard/deploy/select_code_root.py:219-279 (`check_tree`), dashboard_update.py:846-867 (`verify_extracted_tree` runs once, at apply)
- What: the record's sha256 is of the tarball, which is deleted after extraction; at every boot `check_tree` re-verifies `record.json` and compares manifest fields, but never re-hashes the extracted tree against `manifest.files_sha256` (and the manifest itself is unsigned on disk). Any write to `/data/code/<v>/src` is booted as a "verified" tree, and the comment "an unsigned tree is never booted" overstates what is checked.
- Scenario: a bug or a compromised process that can write the data volume modifies `/data/code/0.7.80/src/ccsync_dashboard/*.py`; it runs on every restart and survives until an image newer than the tree is pulled.
- Recommendation: re-hash the tree against `files_sha256` at boot (or at least record and compare a single tree digest signed into the record), refusing on mismatch like any other check_tree failure.
- Known: no

### bug-dash-release-9 - Prune deletes recalled rows and soak-pushed builds

- Severity: low
- Confidence: CONFIRMED
- Where: dashboard/src/ccsync_dashboard/db.py:5021-5035 (`prune_companion_packages`), db.py:4639-4690 (`retract_package` "THE ROW AND THE FILE STAY", `retracted_packages`), api.py:6326-6354 (`targeted_staged_package`)
- What: prune keeps the current build plus the two newest non-current by `published_at`, with no exception for retracted rows or for a version an admin has pushed to one machine to soak. Prune runs on every publish, including every unattended feed publish.
- Scenario: (a) 0.9.81 is recalled while some laptops are offline; two staged releases later the 0.9.81 row is pruned, `retracted_packages` no longer lists it, and the fleet grid's "running a recalled build" chip vanishes from the laptops still on it. (b) An admin pushes staged 0.9.84 to one canary; two more vendor builds arrive on a `stage` site, 0.9.84 is pruned, the canary's targeted offer silently resolves to nothing.
- Recommendation: exclude `retracted_at IS NOT NULL` rows and versions named by a pending machine push from the prune victims (or keep the row and drop only the file for retracted builds).
- Known: no
