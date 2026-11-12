# Dashboard: self-update, the package channel, AI providers and their set-up, and the container

Terms used throughout:

- **Vendor feed** (also "release feed"): a signed JSON list of builds that the software's vendor publishes on the internet (by default a GitHub Releases asset). The dashboard reads it on a timer.
- **Record**: one entry in the feed, describing one build (kind, platform, version, download URL, SHA-256 hash, size, signature).
- **Package**: a companion build (or onboarding wizard build) that the dashboard stores and offers to editor machines through its own upgrade channel.
- **Bundle**: a tarball of the dashboard's own source code, offered by the feed so the dashboard can update its code without a new container image.
- **Runtime id**: a fingerprint of the container image's Python dependency set. A bundle can only be applied over the air to an image with the same runtime id.
- **Image mode**: the dashboard runs from the container image built by the project's Dockerfile (it carries a runtime id). **Bind-mount mode**: the dashboard's code is copied onto the NAS by an install script and mounted read-only into a generic container; no runtime id.
- **`/data`**: the container's persistent volume (the directory holding the dashboard database).

## Dashboard self-update: what is running and how it is reported
(source: dashboard_update.py)

- The dashboard reports which code is answering: `running` (its version), `image` (the version of the code baked into the container image, read from the image's own files), `source` (`volume` = a bundle applied over the air, `image` = the container's own code, `checkout` = a developer tree), `runtime_id` (empty in bind-mount mode) and `commit` (the git commit, or null when unknown). This block appears in `/api/v1/health` under `code`.
  - `commit` for `volume` comes from the applied bundle's `manifest.json` key `git_commit`; for `image` from the environment variable `CCSYNC_GIT_SHA` (baked at image build); for `checkout` it is always null.
  - A commit value is accepted only if it is 7 to 40 lowercase hex characters; anything else (empty, `+dirty`, a branch name) is reported as null.
- Image mode is detected by the presence of a runtime-id marker file (default `/venv/.runtime-id`, overridable for tests by `CCSYNC_RUNTIME_ID_FILE`). Absent marker = bind-mount mode (or an image older than the feature), and every apply and rollback is refused.
- The image's code root defaults to `/app`; `CCSYNC_APP_ROOT` overrides it (test-only seam).
- Version comparison: dotted-numeric only. Anything not made of digits and dots compares lower than every real version.
- A bundle counts as "newer than the image" only when its version is strictly greater than the image's version. If the image's version cannot be read, every bundle counts as newer.

## Dashboard self-update: the update page data and routes
(source: dashboard_update.py)

- `GET /api/v1/admin/dashboard-update` (admin only): returns the full status body:
  - `image_mode`, `running`, `image`, `source`, `runtime_id`;
  - `current`: the applied bundle version, the previous one it can roll back to, when it was applied, `reverted_reason` (set when the boot selector automatically reverted), `revert_refused_reason` and `revert_refused_from` (set when the boot selector refused a revert), `retired_from` and `retired_reason` (set when the boot selector retired an applied version). All are empty strings when absent.
  - `code_updates`: feed bundles newer than both the image and the running version whose runtime id equals this image's runtime id (applyable over the air), newest first. Each with version, size, publish date, notes, runtime id.
  - `runtime_updates`: feed bundles newer than both the image and the running version whose runtime id differs (need a new container image), newest first.
  - `rollback_candidates`: feed bundles newer than the image but not newer than the running version, newest first.
  - Bundles equal to the running version, or not newer than the image, are left out of all three lists.
  - `nas_hint`: the per-platform sentence telling the admin how to update the container image (see the release feed's image hint below).
  - `in_progress`, `step`, `message`, `last_error` of the current or last update.
  - `backups`: the list of database backup folders (name, creation time, the version that took it, the databases in it, total size).
  - `boot_attempts`: the failed-boot counter for the tree currently on trial.
  - `data`: the `/data` gauge (path, free bytes, total bytes, used percent; `-1` when it cannot be measured).
  - `schema`: what rolling back to the previous tree would mean for the database (live schema, the target tree's schema, the backup to restore, `unknown`, `safe`).
- `GET /api/v1/admin/dashboard-update/status` (admin only): the same body; the progress panel polls it once a second while an update runs.
- `POST /api/v1/admin/dashboard-update/apply` (admin only), body `{version, force=false}`: runs every refusal check immediately, then performs the update in the background and returns `{ok, started, version, status}`. Refusals (HTTP status and condition):
  - 400 when the version is not dotted-numeric or contains `..` ("refusing ... as a version: dotted-numeric only (it names a directory)").
  - 409 in bind-mount mode: "this deployment updates from the base rig, not over the air: it is running in bind-mount mode (no /venv/.runtime-id), so its code comes from server/install_dashboard_app.py. Move it to the container image first (docs/DOCKER.md)."
  - 409 when another update is in progress ("an update to X is already in progress (step: S). Wait for it to finish or fail.").
  - 409 when the version is the one already running ("this dashboard is already running X").
  - 409 when the version is not newer than the image's code ("... the image always wins at boot ... To go back, roll back instead.").
  - 500 when `/data/code` is not writable.
  - 404 when no verified dashboard record of that version exists in the last feed check ("Run Check now first (the feed is re-verified on every check, and the cache is not kept across a restart).").
  - 409 when the record's runtime id differs from the image's ("dashboard X is a RUNTIME update ... Update the image from your NAS's own app manager instead.").
  - 409 when YouTube download jobs are mid-flight and `force` is false ("N YouTube job(s) are running: an update restarts the dashboard for about ten seconds and interrupts them. Wait, or apply again with force."). Busy phases counted: generating_terms, searching, enriching, filtering, downloading. `ready_for_review` does not count. An unreadable YouTube database counts as 0 jobs.
  - 507 when free space on `/data` is below (bundle size x 4 + total size of the live databases x 2) + 256 MiB. A volume whose free space cannot be measured is not refused.
  - Two admins pressing apply at the same moment get one update and one 409.
  - An admin's own apply clears the "do not auto-apply" mark for that version (see below); an apply started by the feed poller (starter name beginning `release-feed`) never does.
- `POST /api/v1/admin/dashboard-update/rollback` (admin only), body `{to_version="", restore_db="", acknowledge_schema=false}`: switches back to the previous applied tree (or the named one, or the image when there is no previous) and restarts. Refusals:
  - 409 in bind-mount mode.
  - 409 while an update is in progress ("rolling back underneath it would race the swap").
  - 409 when no bundle is applied ("this dashboard is already running the image's own code").
  - 400 for a malformed target version; 404 when no applied tree of that version is on disk.
  - 409 when the live dashboard database schema is above what the target tree knows, unless `restore_db` or `acknowledge_schema` is sent. The message names the backup to restore ("restore backup <name> alongside it") and says the restore takes today's reports back too. When the target's schema cannot be known (the image, or a tree applied before schema recording), the rollback is allowed and the answer is reported as `unknown`.
  - With `restore_db`: 400 for a name containing a slash or `.`/`..`; 404 for a missing backup ("no backup called X"); 404 when the backup holds none of the databases in use.
  - A rollback writes a "do not auto-apply" mark for the version it left (reason "rolled back by <admin>"), so the feed poller does not re-apply it.
  - Returns `{ok, version ("image" when going to the image), restored, rolled_back_from, schema}`.

## Dashboard self-update: the apply sequence
(source: dashboard_update.py)

- Steps, each recorded in `/data/code/update_state.json` (`step` values in order): `starting` ("queued"), `downloading`, `extracting`, `verifying` ("importing the new code and migrating database copies"), `backing-up`, `swapping`, `restarting`, then `done`; or `failed` with an error message.
- Download: only an `https://` URL is accepted ("the feed record's url is not https: refused"). The download is limited to 256 MiB and 600 seconds, and its SHA-256 must match the signed record (mismatch = 400; any other download failure = 502 "could not download the bundle").
- Extraction refuses (400) any member that is an absolute path, contains `..`, is a symlink, hardlink, device, fifo, or anything other than a regular file or folder. File modes and owners from the archive are ignored. A bundle with no readable `manifest.json` is refused.
- Cross-checks after extraction (each a 400 refusal): manifest kind must be `dashboard`; manifest version and runtime id must equal the signed record's; the manifest must list files with hashes; every listed file must exist and match its SHA-256.
- Stage-verify: the image's Python, with the new tree on its import path and `DASH_DEV_INSECURE=1`, imports the new dashboard app and runs every migration against COPIES of the live databases (dashboard, b-roll, music, each only if present). Limit 600 seconds. A timeout, a non-zero exit, unparseable output or any failed check refuses the update with "Nothing was swapped" and the failed checks named. It also reports the highest dashboard schema the new tree knows.
- Backups: every live database (dashboard, b-roll, music) is copied with SQLite's online backup method into `/data/backups/<UTC timestamp>-before-<version>/`, with a `backup.json` listing what was copied and what was skipped. A database that cannot be copied is skipped, not fatal.
- NAS snapshot before the swap (best effort, never fatal): only on TrueNAS, only when a NAS API key is configured (`DASH_NAS_API_KEY`) and the environment variable `DASH_UPDATE_SNAPSHOT_DATASET` names a dataset. Snapshot name `ccsync-dashboard-update-<version>-<YYYYmmdd-HHMMSS>`. Otherwise it reports skipped with the reason.
- The signed record is saved beside the tree as `record.json` (re-verified at every boot). The tree's manifest gains `schema_version` only when the verify step reported one.
- Swap: the staged folder becomes `/data/code/<version>/`; `/data/code/current.json` is rewritten with version, previous (the version it superseded; re-applying the same version keeps the old previous; empty means "the image"), when, by whom, the record's hash, the live database schema versions, the tree's schema version and the backup folder. The failed-boot counter is reset.
- Pruning after a swap (best effort): database backups keep at most 3 per label, at most 8 in total and at most 8 GiB in total, newest first; the newest backup is never deleted, and only folders carrying a `backup.json` are deleted. Code trees keep 3: the running one, the rollback target, and the newest others.
- Restart: the dashboard asks itself to shut down gracefully, then exits with code 75; the container's start script sees 75 and starts again, picking the code root afresh. Downtime is described as about ten seconds. The restart decision survives a full or read-only `/data` (held in memory as well as on disk).
- The temporary download and staging folders are deleted whatever happens.
- Stale "in progress" flags: a flag left by a process that no longer exists (container killed mid-download, NAS reboot) is cleared on the next read and recorded as `failed` with "interrupted by a restart at step S". A leftover "restart requested" flag from a dead process is recorded as `done`.

## Dashboard self-update: the boot watchdog and automatic revert
(source: dashboard_update.py)

- On every boot where `/data/code` exists, the dashboard waits 45 seconds, then probes its own `GET http://127.0.0.1:<port>/api/v1/health` (port from `DASH_PORT`, else the configured port, else 8480) every 3 seconds for up to 45 seconds, 10-second timeout per probe, redirects not followed. Healthy = HTTP 200 with JSON whose `version` equals this build's version (the `ok` field is not required).
- Healthy: the failed-boot counter (`/data/code/boot_attempts.json`) is deleted.
- Not healthy, and running from an applied bundle that is on trial: the process exits with code 75 so the next start counts the failure; two failed boots in a row revert to the previous tree or the image (the revert itself is done by the boot selector, see the container section). Running from the image or a checkout: it only logs.
- Exception: if the revert would itself be refused (the target tree knows an older database schema than the live one, or a revert from this version was already refused), the process stays up and logs "NOT exiting for a revert" so the admin pages keep answering.
- Startup deadline: when running a bundle on trial, startup must reach the watchdog within 600 seconds or the process exits 75 the same way.
- "Do not auto-apply" marks (`/data/code/no_auto_apply.json`): a per-version list of versions that must not be applied automatically by the feed poller, each with a reason and time. Written by the boot selector when it reverts and by an admin rollback. Cleared per version only by an admin's own apply of that version.

## Dashboard self-update: feed health and the runtime-mismatch banner
(source: dashboard_update.py)

- `/api/v1/health` carries `feed`: whether a feed is configured, when it was last read, age in days, the last error, how many verified records it carried, and `stale`. With no feed configured it says `configured: false` and `stale: false`.
- Stale = never checked, or last checked more than 7 days ago.
- "Every dashboard build on offer needs a new container image": when there are runtime updates and no code updates, the dashboard stores this condition (time, up to 5 versions, the NAS hint) for the fleet page banner; otherwise it clears it.
- Database backups listing and restore are also reachable only through the rollback route (`restore_db`); there is no separate restore route.

## Dashboard self-update: the space guard shared with publishing
(source: dashboard_update.py)

- One rule for anything that writes a large file to `/data` (a human package upload, the feed's automatic publish, the AI CLI install wizard): refused when free space is below (declared size x 3) + 256 MiB. A declared size of 0 still checks the 256 MiB floor. A volume that cannot be measured is never refused. Message: "not enough free space on the data volume: N MiB free, <what> needs about M MiB. Old builds are pruned on publish (current plus the two newest are kept); free some space and try again."

## The runtime id: when a code update is allowed
(source: runtime_id.py)

- A runtime id is a SHA-256 over the prefix `ccsync-runtime-id-v1\n`, the container's base image reference (the Dockerfile's `ARG BASE_IMAGE=` line, or a build-time override of it) and the SHA-256 of the dependency lockfile (line endings normalised to LF first, so a Windows checkout and a Linux build agree).
- The image writes its id to `/venv/.runtime-id` at build time; bundles are stamped with the id they were built against.
- Same id = "code update" (one button in the dashboard). Different id = "runtime update" (must be done by updating the container image in the NAS's own app manager). Building the image with a different `BASE_IMAGE` build argument therefore makes every bundle a runtime update, and the operator is told so.
- A Dockerfile without an `ARG BASE_IMAGE=` line cannot produce an id (the build fails rather than guessing).
- No id file = bind-mount mode or an image older than the feature: over-the-air code updates are refused with a reason.

## The vendor release feed: fetching and trusting it
(source: release_feed.py; setting names confirmed in settings.py)

- Configuration:
  - `DASH_RELEASE_FEED_URL`: the channel document's URL (resolved through a vendor default in settings; must be https). With it empty there is no feed at all: no poller thread, no network lookups, and the check and publish routes answer 503 "DASH_RELEASE_FEED_URL is not configured".
  - `DASH_RELEASE_FEED_SIG_URL`: optional explicit URL of the detached signature. Blank = derived by appending `.sig` to the channel URL's path (query string kept, fragment dropped).
  - `DASH_RELEASE_FEED_POLICY`: `manual` (default), `stage` or `current`. Any other value falls back to `manual`. An admin can override it at run time (stored in the database; the override wins).
  - `DASH_RELEASE_FEED_INTERVAL`: seconds between automatic checks, default 86400 (daily), never less than 60.
  - `DASH_RELEASE_PUBKEYS`: the release public keys every channel, record and package is verified against.
  - `DASH_RELEASE_SOAK_MINUTES`: default 30, see the soak rule in the package channel.
- Background check: starts 10 seconds after boot, then repeats every interval. A failed cycle is logged and the loop continues. Stopping waits up to 5 seconds for an in-flight check; a check that outlives that is never doubled by a restart of the poller.
- Fetch rules for the channel, its signature and every downloaded build:
  - https only; every redirect hop must also be https ("refusing a non-https redirect ... (scheme downgrade)"); at most 5 redirects; a redirect without a Location header is refused.
  - No credential of any kind is sent on any hop.
  - Channel document at most 1 MiB, 10-second timeout. Signature file at most 8 KiB.
  - Must be JSON with `schema` equal to 1 ("channel.json is not a schema=1 object").
  - The whole channel must verify with an Ed25519 signature (64 bytes, base64) against one of the configured release public keys, over canonical JSON with the prefix `ccsync-channel-v1\n`. Refusal texts include "no release public key is configured (DASH_RELEASE_PUBKEYS)" and "no configured release public key verifies this channel".
  - Pre-signed object URLs (query keys `X-Amz-Signature`, `X-Amz-Credential`, `AWSAccessKeyId`, `sig`) cannot have a derived `.sig` sibling; when the signature fetch fails for such a URL and no explicit signature URL was set, the error adds a sentence explaining this and suggesting a plain URL or a query token.
- Replay protection: the dashboard remembers the newest `generated_at` it has ever accepted. A channel that is older, or that has no readable `generated_at` after one was accepted, is refused as "a possible replay of an old channel" and nothing changes. Equal is accepted.
- Each package record inside the channel must also carry its own valid signature; unsigned or mis-signed records are dropped (counted in a log line).
- A record whose `kind` or `platform` is not already lower case is dropped AND reported: the check still answers ok, but the feed's last error becomes "N record(s) in the channel are not offered here: ... The feed has to republish them." (up to 5 named).
- A record whose `min_version` is above its own version is dropped.
- Builds the channel lists as `retracted` are dropped from what is offered.
- Records of kind `dashboard` are never published as packages; they are only offered to the dashboard self-update.
- The verified result is held in memory only; after a restart nothing is offered until the next check.
- After every check the dashboard records: when it checked, the last error (or empty), and the channel's `generated_at`.
- Provenance repair: for builds already published here with the same SHA-256, a stored "dirty build" mark is cleared when the feed record says the build is clean. It never marks a build dirty and never changes the commit. The feed's `git_dirty` and `signed_binary` flags are read as true for the strings `1`, `true`, `yes`, `on`, `dirty`, or any truthy non-string.

## The vendor release feed: what happens on every check
(source: release_feed.py)

- Recalls: every build in the channel's signed `retracted` list (kind, platform, version, reason, time) is un-made-current on this dashboard under every policy, including `manual`. The package file and row stay. Logged as "has been RECALLED by the vendor".
- "One offered record per kind and platform": the channel's signed `current` pointer (keys like `companion/windows`) names it; with no pointer, the highest version. A pointer naming a version the feed does not carry selects nothing for that pair.
- Policy `manual`: nothing is published automatically; only the admin's publish button writes.
- Policy `stage`: the one offered record per pair is downloaded and stored, not made current.
- Policy `current`: the same, and it is made current. If the build is already stored but not current, it is made current again (this is how the vendor withdraws a bad build by moving the pointer back); such an unattended promotion is written to the audit log as actor `release-feed`, action `package.make_current`. If making current is refused (for example by the soak rule), it is logged and skipped.
- A companion build that needs a newer dashboard than this one (`requires_dashboard`) is stored without being made current, and the check's result tags it "(STAGED)".
- A build already stored with a different SHA-256 for the same version is never replaced; a warning is logged ("same version, different bytes ... ask the vendor to publish a new version number").
- "What the vendor offers" is stored on every check (per platform, the companion versions at or below the offered one), used by the versions-behind alert and the "what is running" box.
- Notice `feed_publish_refused` (severity error), one per platform and version, when an offered companion build needs a newer dashboard: "A new CC Sync build for <platform> (<version>) is on offer but cannot be handed to the computers here: it needs dashboard X and this dashboard is Y. Until the dashboard is updated, every computer in the fleet stays on the build it has and this server reports them all as up to date." with the fix "On the dashboard: SETTINGS, PACKAGES, then update the DASHBOARD from the vendor feed. The companion build becomes available to the fleet straight after." Cleared automatically on the next check that no longer finds it.
- The runtime-mismatch banner state is refreshed (see self-update).
- Last, the dashboard's own unattended update (next group).

## The vendor release feed: the dashboard updating itself unattended
(source: release_feed.py)

- Only under policy `current`. It applies the dashboard bundle the channel offers (the signed `current["dashboard/linux"]` pointer, or the highest version when the channel has no dashboard pointer), using the same apply as the admin button with force off (so live YouTube jobs block it).
- It does not apply, and records one sentence why (shown on the health page's "what is running" box), when:
  - running in bind-mount mode: "this deployment updates from your wired computer, not over the air: run  tools\ship.cmd -DashboardOnly  there to update it";
  - an update is already running;
  - the only newer bundle is not the one the vendor currently offers (staged): "... is not taken automatically. "Update now" in the This dashboard panel on the Packages page takes it by hand";
  - the offered bundle needs a different container image: "... Update the image from your NAS's own app manager (docs/DOCKER.md), then check again";
  - the same version already failed here ("will not be retried automatically");
  - an admin rolled back from that version ("was rolled back by an admin ...; it will not be re-applied automatically");
  - that version crash-looped at boot and was reverted ("was installed here, would not start, and was reverted ...");
  - the soak has not passed: the bundle must have been published at least the soak minutes ago (default 30; 0 disables); a bundle with no or unreadable publish date is not taken while a soak is set.
- When it does start: note "taking dashboard X now: this server restarts for about ten seconds when it lands." If the apply is refused: "dashboard X was not applied: <reason>".

## The vendor release feed: admin routes and the feed panel
(source: release_feed.py)

- `GET /api/v1/admin/feed` (admin only): the feed panel data: whether configured, the feed URL, the effective policy, last check time, last error, the channel's generated time, `available` (verified package records not already published here), `sha_conflicts` (same version published here with different bytes: both hashes shown), `retracted` (every recall in the channel, whether or not this dashboard ever had it), and `image` (the vendor image tag, digest, sftp image digest, the exact image references, the update hint, and the running version).
- `POST /api/v1/admin/feed/check` (admin only): runs a check now. 503 when no feed is configured. Returns `ok`, `error`, `applied` (what the policy just published or re-made current), `retracted`, `refused` (builds that need a newer dashboard) and the refreshed view.
- `POST /api/v1/admin/feed/publish` (admin only), body `{kind="companion", platform, version, make_current=false}`: downloads and publishes one build from the last verified check (kind and platform are lower-cased). Refusals: 503 no feed configured; 400 for kind `dashboard` ("a dashboard code bundle is applied, not published ..."); 404 "no verified feed record for ...: run Check now first"; 409 already published (with a different-bytes variant naming both short hashes: "The vendor has to publish this build under a new version number."); 400 unsafe filename; 400 non-https URL; 507 not enough disk space (also recorded as the feed's last error, "could not take <kind> <version>: ..."); 400 hash mismatch; 502 download failure; plus every refusal of the package store (next groups). Download limit 200 MiB, 600 seconds. The published row records the admin's username as publisher (the poller records `release-feed`). Old builds are pruned after the publish.
- `POST /api/v1/admin/feed/policy` (admin only), body `{policy}`: sets the run-time policy override; 422 for anything other than manual, stage or current.
- The container image update hint (used on the Packages page, the dashboard-update panel, the fleet banner and alert mail):
  - When the signed channel names an image tag and digest: tells the admin to edit the compose project (Synology: "Container Manager > Project ccsync > Edit"; TrueNAS: "Apps > ccsync > Edit"; otherwise "your NAS's app or container manager"), paste the exact references `ghcr.io/the-creators-club/ccsync:<tag>@<digest>` (and `ghcr.io/the-creators-club/ccsync-sftp:<tag>@<digest>` for the sftp service), and warns that pressing Update or Build alone re-pulls the old pinned image; sites installed with `install_dashboard_app.py` are told to set `[stack] image` in `site.toml` and re-run the installer.
  - Without a digest: Synology "Container Manager > Project ccsync > Build"; TrueNAS "Apps > ccsync > Update"; otherwise "your NAS's own app or container manager's Update action".

## Release signatures: what a signed record covers
(source: release_trust.py, ed25519.py)

- Every published package is described by a record signed offline with the vendor's Ed25519 release key. The dashboard stores and serves the signature but cannot produce one.
- Signed fields for every record: kind, platform, version, filename, sha256, size_bytes, min_version, published_at, signed_binary. Canonical form: those fields as sorted compact JSON, prefixed `ccsync-release-record-v1\n`.
- A `dashboard` record additionally signs `runtime_id`.
- A `companion` record additionally signs `arch` (CPU architecture) and `requires_dashboard` (the dashboard version it needs) when present and non-blank; a blank value is treated as absent.
- Trusted keys are configuration (`DASH_RELEASE_PUBKEYS`, several allowed for key rotation). With no key configured, every verification fails ("no release public key is configured (DASH_RELEASE_PUBKEYS)") and publishing is refused.
- A key's id shown on pages is the first 16 hex characters of the SHA-256 of the raw key.
- Refusal texts for a bad signature: "signature is not valid base64", "signature is N bytes, not 64", "record is not signable (...)", "no configured release public key verifies this record".
- `min_version` (the downgrade floor companions learn) must be dotted-numeric; a record whose `min_version` is above its own version is refused everywhere.
- Version comparison is numeric per dotted part (0.10.0 is after 0.9.9); "cannot compare" is treated as a refusal, never as fine.
- The signature check is a self-contained Ed25519 verifier written in pure Python (no external crypto library). It never raises on malformed input (answers "not valid"), and rejects signature scalars at or above the group order. It also contains key derivation and signing, which the dashboard never calls (kept so the copy stays identical to the companion's).

## The package channel: publishing a build onto the shelf
(source: package_store.py)

- Every publish (a human upload through the publish route elsewhere, the feed's admin button, the feed's automatic policy, the release scripts) goes through one gate, in this order:
  1. Refused (400) when `min_version` is above the version: "min_version X is higher than the version being published (Y), so every companion that saw this offer would raise its downgrade floor above it and then refuse it. Nothing was published: re-sign with a min_version at or below Y."
  2. Refused (400) when the release signature does not verify over the exact record the server assembled (server-chosen filename, server-counted size, server-computed hash): "release signature REJECTED (<detail>): nothing was published. The signature must cover this exact record: kind=..., platform=..., ...". A declared key id that differs from the key that actually verified is only logged; the verifying key's id is stored.
  3. Same version already held: same bytes = success with the note "already published at this version, with these exact bytes."; different bytes = 409 "<kind> <version> for <platform> is already published on this server, from different bytes. Nothing on disk was replaced. Bump the version and rebuild, or delete the published record first if you meant to overwrite it."
  4. The row is stored with: version, platform, kind, filename, hash, size, publisher, publish time, signature, key id, min_version, signed_binary, requires_dashboard, arch, git commit and dirty flag (advisory, unsigned), and release notes (unsigned, display only).
  5. If "make current" was asked for, the make-current gate runs (next group). Refused = the build is still published but STAGED, and the publisher gets the note "published and STAGED: push it to one computer, let it soak, then MAKE CURRENT. <reason>". Allowed = it becomes current and an audit entry `package.make_current` is written.
  6. Optionally prune old builds of that platform and kind (the database keeps the current build plus the two newest), then commit.
  7. Only after the commit is the file moved into `<packages dir>/<platform>/<filename>` and the pruned builds' files deleted.
- Packages directory: `DASH_PACKAGES_DIR`, default `<folder of the database>/packages`.
- Any refusal deletes the uploaded temporary file; nothing is half-published.

## The package channel: the make-current gate and the soak
(source: package_store.py)

- Applies to every way a build becomes "current" (offered to the fleet): the JSON route, the Packages page button, the roll-back button, a publish asking for it, and the feed's `current` policy. Checked in this order:
  - 404 "no published <platform> <kind> package <version>".
  - 409 when the vendor recalled it: "<kind> <version> was RECALLED by the vendor: <reason>. It cannot be made current. Roll the fleet back to a build that was not recalled." No override.
  - 409 when a companion build needs a newer dashboard than the running one (an unreadable requirement also blocks): "<kind> <version> needs dashboard X and this dashboard is Y. Update the dashboard first, then make this build current." No override.
  - 409 when the build has no release signature, unless the admin forces it AND types the exact version into the confirmation box: "... has no release signature. Companions verify signatures, so making it current stops EVERY computer in the fleet from updating, silently. <instead> To make it current anyway, type the version number (X) into the confirmation box." The "instead" sentence is "Publish the signed build from AVAILABLE FROM THE VENDOR instead." when a feed is configured, otherwise "Republish it through tools\ship.cmd instead."
  - Allowed without a soak: a build that has been current before (a rollback).
  - Allowed without a soak, for unattended callers only (publish and feed): a build older than the current one (a vendor withdrawal), and the case where nothing is current yet for that platform and kind (a fresh site's first build).
  - Non-companion kinds (for example the onboarding wizard) are not soaked.
  - A human force without the exact typed version: 409 "to override the soak gate, type the version number (X) into the confirmation box. Nothing changed."
  - Soak minutes: the database setting `release_soak_minutes` wins over `DASH_RELEASE_SOAK_MINUTES` (default 30); 0 turns the soak off entirely; an unreadable value falls back to the default.
  - Otherwise the soak refuses (409 "<version> has not soaked yet: <detail> Make it current anyway by confirming the override.") with one of these details:
    - "no computer has reported X yet, so nothing has run it. Push it to one computer first, leave it for N min, then make it current."
    - "R of the M computers on X had to be rolled back off it by the crash-loop guard."
    - "M computers on X have reported C crash(es), and K of those computers have crashed since X started running there."
    - "C crash(es) are on record on the M computers on X and nothing says when they were written, so they cannot be told apart from this build's."
    - "no computer on X has reported its crash counter, so nothing here says the build stays up."
    - "M computers have been on X for T min; the soak is N min." optionally followed by "The C crash(es) on record there were all written before X started running, so none of them are its."

## The package channel: "what is running" on the health page
(source: package_store.py)

- A box answering "dashboard versus vendor, companions versus vendor, and who is on what":
  - the dashboard's running version, the version the vendor currently offers for it (per the channel's current pointer), whether it is behind, whether it is in image mode;
  - the time of the last feed check, and the last "why has this dashboard not updated itself" note;
  - per companion platform: the current build and when it was published here, the newest companion version the vendor offers, whether the fleet is behind the vendor, how many machines there are and how many are on the current build, and one line per build machines are actually running (with computer count, publish date, and whether it is current), including builds this server never published.
  - Empty values mean "not checked", never "up to date".
- Sentences it shows (the "disagreements"):
  - "A newer CC Sync build for <platform> (<v>) is on offer and the computers here are being offered <current>. Update the dashboard first: it is <D> and the vendor is offering <DV>." (when both the companion and the dashboard are behind);
  - "The vendor is offering <v> for <platform> and the computers here are being offered <current>.";
  - "<n> of <total> <platform> computers are on <current>.";
  - "This dashboard is <D> and the vendor is offering <DV>." (when only the dashboard is behind).

## The Android app link (Digital Asset Links)
(source: android.py)

- Purpose: lets a studio's Android app (the dashboard wrapped as a Trusted Web Activity) open without a browser address bar. If the statement is missing or wrong, the app still opens but with an address bar, and nothing says why.
- `GET /.well-known/assetlinks.json`: open, no sign-in needed. Returns a JSON array: empty `[]` unless BOTH an Android package name and at least one SHA-256 certificate fingerprint are configured; otherwise one statement granting `delegate_permission/common.handle_all_urls` to that package and those fingerprints (fingerprints trimmed and upper-cased). Header `Cache-Control: max-age=3600`.
- Settings panel "Android app" (on the admin settings page), two fields: package name and certificate fingerprints (a text box; one per line).
- `POST /api/v1/setup/android` (admin only, form fields `package_name`, `sha256_cert_fingerprints`), the SAVE button: validates and saves both values together into the site settings (`android.package_name`, `android.sha256_cert_fingerprints`); a validation failure saves nothing and re-renders the panel with the error and the admin's own typed text still in the boxes. On success writes an audit entry `site.android_save` (key names only) and shows "Saved. This site now serves an asset-links statement." or "Saved. Both a package name and at least one fingerprint are needed before this site serves a statement."
- `POST /api/v1/setup/android/check` (admin only), the CHECK button: shows what the site is serving right now (path, number of statements, package name, fingerprints, relation), the site's own dashboard URL, and a link to Google's asset-links check API for that URL (`https://digitalassetlinks.googleapis.com/v1/statements:list?source.web.site=<origin>&relation=...`), which the admin opens themselves; the server never calls Google. No link is shown when the site's dashboard URL is blank or not http(s).

## Timeline Cards native app updates
(source: cards_app.py)

- The Timeline Cards Windows and Android apps have a "check for update" that reads these two routes. Both are behind the dashboard's login (the app sends the editor's session).
- Builds live in the vault folder `<Timeline Cards vault root>/Apps/Timeline Cards/` together with a `latest.json` listing the newest build per platform. They are put there by a publishing script in the other repo; nothing is uploaded through the dashboard.
- `GET /cards/app/latest.json`: returns that file's contents plus `ok: true`, never cached. 404 `{"ok": false, "error": "no app builds have been published"}` when no vault root is configured or the file is missing or unreadable.
- `GET /cards/app/<name>`: serves one build file, only if its name is listed as a `file` in `latest.json` and matches a safe pattern (letters, digits, dot, underscore, space, hyphen; up to about 120 characters; ending `.apk` or `.exe`). `.apk` is served as an Android package, `.exe` as a binary download, never cached. 404 "no such app build" otherwise; 404 "that build is listed but missing" when listed but absent on disk.

## AI providers: the five backends and the order they are tried in
(source: ai_providers.py; the build lock confirmed in build_flavor.py)

- Five providers, in this fixed order (which is both the priority order and the display order on the Settings page):
  1. Claude Code (`claude_code`): a command-line tool (CLI) signed in with a personal Claude subscription. Executable name `claude`.
  2. Claude API (`anthropic_api`): an API key. Environment variable `ANTHROPIC_API_KEY`.
  3. Codex (`codex`): a CLI signed in with a ChatGPT subscription. Executable name `codex`.
  4. OpenAI API (`openai_api`): an API key. Environment variable `OPENAI_API_KEY`.
  5. DeepSeek API (`deepseek_api`): an API key. Environment variable `DEEPSEEK_API_KEY`.
- Automatic choice ("auto", the default): the first provider that is available wins. An API provider is available when it has a key; a CLI provider when it is installed and signed in. The reason given names the providers it was chosen over ("first available in the chain (ahead of ...)").
- Pin: an admin can pin one provider. A pinned provider that is not available is a refusal, never a fallback: "<label> is pinned but not available. Nothing else will be used in its place: clear the pin to fall back to the chain." An unknown stored pin reads as auto.
- Nothing available: "no provider has a working credential". Two more specific reasons replace it when they apply: a CLI that was too slow to start ("<label> was too slow to start (Ns): the server is busy. It is checked again on the next try; try again in a minute."), or a CLI that is installed but refused ("<label> is not signed in on this server (<the CLI's own words, with secrets redacted, up to 200 characters>). An admin must sign it in again on Settings -> AI providers").
- With a pin, only the pinned provider is checked (no other CLI is run). Without a pin, once one provider is found available, the CLIs further down are not run; their rows are answered from what is already known.
- Consumers: the YouTube downloader asks on every AI call which provider to use and receives the provider name, the reason, whether CLIs are enabled, and either the API key or the CLI path plus the CLI's environment additions (its private home folder and token). The API key leaves this part only towards that in-process sub-app. Other features (Timeline Cards, the server triage agent, gear identify) also read the provider state; the help text says Codex, OpenAI and DeepSeek serve the YouTube downloader only.

## AI providers: CLI providers behind two switches
(source: ai_providers.py, build_flavor.py)

- Build lock: unless the container's environment has `DASH_STUDIO_CLI_PROVIDERS=1`, the build is "locked": every CLI row shows "Claude Code and Codex are not available in this build. Use an API key (Claude API, OpenAI or DeepSeek).", pinning a CLI is refused with that sentence (422), a CLI pin stored earlier reads as auto (the stored value is kept), and the page hides every CLI row, the notice and the CLI switch. The vendor build is locked.
- Site switch `[features] ai_cli_providers` (database row first; else `DASH_SITE_AI_CLI_PROVIDERS`; fails closed; off in the vendor build). When off, CLI providers are NOT run at all and their rows say "CLI providers are off for this site. Tick 'Allow CLI providers (Claude Code, Codex)' below to enable them". A stored row of "0" beats an environment value of 1.
- Terms notice shown with the CLI rows: "Claude Code and Codex are signed in with a personal Claude or ChatGPT subscription. Using a personal subscription to power a service may breach its terms: that is your decision, not ours. Neither CLI is shipped, bundled or updated by CC Sync. SET UP downloads the publisher's own build, from the publisher's own servers, at your click, and checks it against the publisher's own checksum. The API keys above are the supported path."

## AI providers: API keys
(source: ai_providers.py)

- Keys are stored as files `<data>/secrets/ai/anthropic_api_key`, `openai_api_key`, `deepseek_api_key`, mode 0600.
- The environment variable always wins over a stored file; such a key shows as "set by the deployment (<VAR> in the container's environment); the value here cannot change it" and is not editable.
- A key is never shown back: the page and API show only a mask, the first 3 characters, an ellipsis and the last 4 (a key shorter than 12 characters is shown as just an ellipsis). Keys are never written to logs, never in the public site settings, never in a query string.
- Key validation (422, the message never quotes the key): blank ("the key is blank"); longer than 512 characters; control characters ("the key contains control characters: paste it again"); any whitespace ("the key contains a space: paste the key alone, with no 'Bearer' prefix"). The request body itself is capped at 2,048 characters.
- Help shown in the "add new" picker and wizard for each provider (what it is, what it costs, where to get a key, the key prefix, three steps):
  - Claude API: Anthropic Console, `https://console.anthropic.com/settings/keys`, prefix `sk-ant-`, "Pay per use, billed to your own Anthropic account. Answers the YouTube downloader and Timeline Cards."
  - OpenAI API: `https://platform.openai.com/api-keys`, prefix `sk-`, "YouTube downloader only."
  - DeepSeek API: `https://platform.deepseek.com/api_keys`, prefix `sk-`, "YouTube downloader only."
  - Claude Code: "Spends your Claude subscription, not a bill per call. Needs CLI tools allowed and about 300 MB on this server. The only one the server check can use."
  - Codex: "Spends your ChatGPT subscription. Needs CLI tools allowed. YouTube downloader only: Timeline Cards is written for Claude."

## AI providers: finding and checking a CLI
(source: ai_providers.py)

- Where the CLI executable is looked for, in order: a path the admin typed (it wins even over a wizard install; a typed path that is not a file means "not installed", never a download); the copy the SET UP wizard installed; the executable on the container's PATH.
- Status values (chip text): available, not configured, not installed, not signed in, disabled by site, unknown.
- "Is it installed": runs `<cli> --version`, limit 90 seconds. "Is it signed in": sends the prompt "Reply with the two characters: ok" with the arguments `-p --output-format text --disallowed-tools *` (Claude Code; override with `YTDL_CLAUDE_CODE_ARGS`) or `exec --sandbox read-only -` (Codex; override with `YTDL_CODEX_ARGS`), limit 60 seconds; signed in = exit 0 and some output. This is a real, subscription-billed one-token call.
- The CLI runs with the container's environment minus the API keys, plus the wizard's private home folder and token, so it never answers "signed in" on the strength of an API key.
- Results are remembered for 10 minutes per CLI. A timed-out check is remembered for only 30 seconds; and when the last good answer was "installed and signed in", a timeout keeps that answer (except when the admin pressed Test, which always reports the timeout).
- Only one check runs at a time per CLI; callers arriving meanwhile wait for its answer.
- A page or caller that must not run the CLI is answered from the last real check (even an expired one, marked "(not re-checked since)"), then from the wizard's record of install and sign-in ("signed in (wizard); not re-probed" or "signed in (credential on disk); not re-probed"), and only then "unknown". A real check that ran and was refused beats the wizard's record.
- "Not installed" detail: "not installed: no `<binary>` on this container's PATH. Click SET UP to install it from the publisher, or set the full path of a copy you installed yourself." When the sign-in check fails, the row offers the manual login command (`claude auth login` or `codex login`).
- Changing a typed path clears all remembered answers.

## AI providers: Settings routes
(source: ai_providers.py)

All admin only (401 "log in first" without a session, 403 "admins only" for a non-admin); writes are covered by the dashboard's CSRF check. Every route below answers with the full provider table.

- `GET /api/v1/admin/ai-providers`: every provider's row (name, label, kind, rank, status, status label, detail; for API: environment variable name, whether a key is present, its source, the mask, editable; for CLI: path setting, path, version, login command, typed path, whether the wizard can install it on this platform and why not, whether the wizard installed it and which version, sign-in state and signed-in account), the order, the pin, whether CLIs are enabled, whether the build locks them, the terms notice, the help texts, and the resolved choice (name, label, reason, pinned). This route runs the CLI checks (cached).
- `PUT /api/v1/admin/ai-providers/{name}/key`, body `{key}`: stores a key. 404 unknown provider; 400 for a CLI ("<label> is a CLI: it has no API key. Sign it in on the dashboard host instead."); 409 when the environment variable is set ("<VAR> is set in this container's environment and always wins. Change it there (or unset it): a key saved here would never be used."); 422 validation failures or "could not write the key to <dir> (...). That directory must be writable by the container's uid."
- `DELETE /api/v1/admin/ai-providers/{name}/key`: deletes the stored key. 404 unknown; 400 for a CLI; 422 when the file cannot be removed. An environment-set key is not affected.
- `POST /api/v1/admin/ai-providers/{name}/test`, the TEST button: one live check, answering `{ok, detail}` only.
  - API providers: a GET of the provider's model list (Anthropic `GET <base>/v1/models?limit=1` with `x-api-key` and `anthropic-version: 2023-06-01`; OpenAI `GET <base>/models`; DeepSeek `GET <base>/models`, both with a Bearer token). Base URLs default to `https://api.anthropic.com`, `https://api.openai.com/v1`, `https://api.deepseek.com`, overridable by `ANTHROPIC_BASE_URL`, `OPENAI_BASE_URL`, `DEEPSEEK_BASE_URL`. 20-second timeout; redirects are never followed. Answers: "<label> accepted the key" (plus " (set by the deployment)"); "no key is configured for <label>"; "the key was refused (HTTP 401/403). <body>"; "HTTP <code> from the provider. <body>"; "could not reach the provider from this container (...)".
  - CLI providers: a forced fresh check. Answers: "<label> answered (<version or path>)"; the not-installed detail; "installed but not signed in. Click SET UP and finish the sign-in step, or run `<login command>` on this host. [<detail>]"; or the build-lock sentence, or "CLI providers are off for this site ([features] ai_cli_providers)".
- `PUT /api/v1/admin/ai-providers/{name}/path`, body `{path}` (up to 1,024 characters): sets or clears (blank) the typed CLI path. 404 unknown; 400 for an API provider ("... is an API provider: it has no executable path"); 422 for control characters.
- `PUT /api/v1/admin/ai-providers/preference`, body `{preference}`: `auto` or one provider name; 422 otherwise, and 422 with the build-lock sentence for a CLI in a locked build.
- These provider settings (`ai_provider_preference`, `ai_claude_code_path`, `ai_codex_path`) are stored with the site settings but are never published in the public site manifest or its export.

## Gear identify: a packing-list entry from a phone photo
(source: gear_ai.py)

- Purpose: the studio's public website gear page sends a phone photo of a piece of production gear; the dashboard answers with a suggested packing-list entry.
- `POST /api/v1/gear/identify`, body `{image: base64 JPEG (a data: URL prefix is stripped), categories: [names]}`. Outside the normal login; requires the header `X-Gear-Token`.
  - The token is HMAC-SHA256 of the dashboard's session secret (`DASH_SESSION_SECRET`) over the text `gear-identify`, so rotating the session secret changes it. Wrong or missing token, or no session secret: 401 "bad gear token".
  - 400 "a JPEG image (base64, under 2 MB) is required" when the image is missing, not a string, or longer than 2,800,000 base64 characters.
  - Up to 40 category names (each cut to 40 characters) are passed to the model.
  - Answer: `{ok: true, suggestion: {name (up to 80 chars), category (up to 40), weight_g (integer 0 to 999,999, default 0), qty (integer 1 to 99, default 1), note (up to 200), confidence (high, medium or low; anything else becomes low)}}`.
  - Errors (`{ok: false, err}`): 503 "Claude Code is not installed on the NAS (Settings -> AI providers)"; 502 "Claude Code stopped; try again"; 504 "Claude Code did not answer within 120s"; 502 "Claude Code exited (is it signed in on the NAS?)"; 502 "Claude Code: <its error>"; 502 "Claude gave no suggestion", "Claude gave an unexpected answer", "Claude gave no name"; 502 "could not run Claude Code (<error type>)".
- Always uses the Claude Code CLI found the same way as the provider page (typed path, wizard install, PATH), never an API key and regardless of the provider chain, pin or CLI switches.
- Model: `DASH_GEAR_MODEL`, default `opus`. The CLI runs with no tools, no saved session, a fixed system prompt (identify the main item, reply with one JSON object with name, category, weight in grams of one unit, quantity, a one-line note, confidence), and the working folder `<data>/gear` (created on demand).
- One CLI process is kept running between photos: started by the first photo, reused for later photos (faster), closed one hour after the last photo (checked every 30 seconds), restarted after 40 photos, and closed when the dashboard stops. Photos are handled one at a time.
- Operator helper: running the module with `--token` prints the token for the current `DASH_SESSION_SECRET`, to paste into the website's configuration.

## AI CLI set-up wizard: what it installs and from where
(source: cli_tools.py)

- A per-CLI wizard on the Settings page (steps: notice, install, sign in, test) for Claude Code and Codex. Nothing is bundled with the product; the wizard downloads the publisher's own build at the admin's click.
- Claude Code source: `https://downloads.claude.ai/claude-code-releases`: `/latest` (a bare version string, at most 1 KiB), then `/<version>/manifest.json` (its per-platform SHA-256 checksum and exact size), then the binary at `/<version>/<platform>/<binary name>`. The version must be exactly three dotted numbers or it is refused ("the publisher answered ... where a version number was expected - refused"). A manifest missing the platform is refused naming the platforms it does carry; a platform entry with no usable SHA-256 is refused. Download cap 512 MiB; the size and the hash must both match the manifest.
- Codex source: the GitHub "latest release" API for `openai/codex`. The version is taken from the release tag (for example `rust-v0.147.0` becomes `0.147.0`). The asset is `codex-package-<x86_64|aarch64>-unknown-linux-musl.tar.gz`; its SHA-256 must be listed in the release's `codex-package_SHA256SUMS` asset. No checksum = refused: "the publisher published no checksum for <asset> in Codex <version>, so this install cannot be verified and was not done. Install Codex on the dashboard host yourself and type its full path below, or try again when the publisher ships codex-package_SHA256SUMS with the release." A release without the expected asset is refused ("... this build of the wizard cannot install Codex until the naming settles. Install it on the host and type its path below."). Download cap 400 MiB; unpacked size cap 1.5 GiB; the archive is extracted with path, link and device safety checks (any unsafe member refuses the whole archive: "the Codex archive was refused (...) - nothing was installed"); the executable bit is restored on `bin/codex`, `bin/codex-code-mode-host`, `codex-path/rg`, `codex-resources/bwrap`; an archive without `bin/codex` is refused.
- Every fetch: https only, at most 5 https redirects, no credential sent, JSON responses capped at 8 MiB, 60-second timeout for metadata, 900 seconds for the download.
- Platform checks (shown on the page before anyone clicks, and refused at install):
  - Not Linux: "this dashboard is running on <os>, and the wizard installs the Linux build the container uses. On a dev machine, install the CLI yourself and type its path below."
  - CPU other than x86_64/amd64 or aarch64/arm64: "... the publisher builds x86_64 and arm64 only."
  - A musl (Alpine) container: refused; "The wizard installs the glibc build only, which is what the shipped image uses. Install the CLI in the container yourself and type its path below."
  - Data folder not writable: "<dir> is not writable by this container. ..."
  - Not enough space: the shared space rule with the tool's approximate size (Claude Code 330 MiB, Codex 200 MiB) times 2 plus the 256 MiB floor. Without a tool named, only the floor is checked.
  - If the check itself fails unexpectedly: refused with "this server could not check whether there is room to install <label>: the check itself failed with an unexpected error (<type>). Nothing was installed. ...".
- Files it creates (all under `<data>/tools/<claude-code|codex>/`):
  - `<version>/` holding the binary (Claude Code) or the package tree (Codex); folders mode 0700, binary 0755;
  - `current`: a plain text pointer file `<version>/<binary path>` (not a symlink), switched only after the record is written;
  - `state.json`: installed version, SHA-256, size, install time, source URL, checksum source, whether the checksum was verified, binary path, and the replaced versions still waiting to be deleted;
  - `install.json`: written while an install is running, deleted when it ends any way;
  - `.staging/`: the partial download;
  - `home/` (mode 0700): the private home folder every run of a wizard-installed CLI uses, where the CLI keeps its sign-in;
  - `auto_update.json` (Claude Code only): the unattended updater's last look and outcome.
  - The long-lived token from the fallback sign-in is stored as `<data>/secrets/ai/<tool>_oauth_token` (mode 0600).

## AI CLI set-up wizard: installing, updating and removing
(source: cli_tools.py)

- One install at a time across both tools ("an install of <label> is already running. Wait for it to finish.", HTTP 409).
- The install runs in the background; the page polls the status: state (`idle`, `running`, `done`, `error`, `interrupted`), step text ("checking the publisher", "asking the publisher for the latest version", "reading the publisher's manifest", "downloading <version> (<platform>)", "verified, installing", "reading the publisher's checksums", "unpacking", "installed"), bytes, total, percent, error, start and finish times, checksum source, who started it ("" or "auto-update"), whether installed, installed path, version, install time, installed SHA-256, publisher, and `unverified` (true only for an old install recorded without a verified checksum).
- Download failures: "the download does not match the publisher's sha256 - refused. Nothing was installed."; "the download is N bytes and the publisher's manifest says M - refused. Nothing was installed."; "the download exceeded N bytes - refused"; transport errors from the fetch rules. A failed or killed install leaves the previous version in place.
- An unexpected failure becomes the status "the install of <label> stopped with an unexpected error (<type>) while <step>. Nothing was installed. Try again, or install it on the dashboard host yourself and type its full path below."
- Interrupted by a restart: when the in-progress record survives but no install is running, the status is `interrupted` with "the download of <label> was still running when this server restarted (started <time>). Nothing was installed and nothing was left half-installed. Start it again when you are ready." If the binary of that version is actually there, the record is simply cleared.
- Abandoned partial downloads older than 24 hours are deleted, once per process, on the first status read.
- After an install (and after a removal, sign-in or sign-out) every remembered "installed / signed in" answer of the provider page is forgotten.
- Old versions: after a successful install, every other version folder is deleted except the one just replaced (and any other replaced within the last hour); a replaced version is kept for 1 hour so a running call can finish, then deleted by a sweep that runs every 5 minutes from the background collector.
- Remove: deletes the whole tool folder (binary, record, private home with its sign-in) and the stored token, and cancels any sign-in. Refused (409) while that tool's install is running: "that install is still running. Cancel it by waiting for it to finish, then remove."
- Unattended Claude Code update: runs from the background collector. Only when both site features `ai_cli_providers` and `ai_cli_auto_update` are on (the latter off in the vendor build) and only over a wizard install (a CLI at a typed path is never updated). First look 5 minutes after the process starts, skipped if the last look was under 1 hour ago; then at most once every 24 hours. If the feature is off or nothing is installed, it asks again after 60 seconds. It compares the publisher's latest with the installed version; installs only a strictly newer one, through the same verified install (and refuses if the publisher's answer has moved back to an equal or older version by the time of the download: "the publisher now offers Claude Code X, which is not newer than the Y already installed. Nothing was changed."). It never runs while another install runs. Outcomes recorded in `auto_update.json`: `skipped` (installed version not recorded; or an install was already running), `failed` (with the reason), `up_to_date`, `started`, `updated` (with the previous version). The look is stamped before the network call, so a hang does not cause a retry storm.

## AI CLI set-up wizard: signing in
(source: cli_tools.py)

- The sign-in runs the CLI's own login under a pseudo-terminal (Linux only) in the tool's private home folder, 200 columns wide so the link is not wrapped, with the CLI's allow-listed environment and without any token already held. The dashboard reads the output, lifts the first complete `https://` link and shows it; the admin opens it, signs in with the publisher, and pastes the code back into the page, which types it into the CLI.
- Modes for Claude Code: "Claude subscription" (default) or "Anthropic Console (API billing)" (adds `--console`).
- Strategies, tried in order:
  - Claude Code: `claude auth login`, then, only if the first refused to run on a pseudo-terminal, `claude setup-token`, whose printed long-lived token (`sk-ant-...`) is captured and stored (0600) and then passed to every later run as `CLAUDE_CODE_OAUTH_TOKEN`.
  - Codex: `codex login --device-auth` (only if that build's `login --help` mentions it; the admin types a shown code on the publisher's page) then `codex login`; or `codex login` alone.
  - "Refused a pseudo-terminal" is recognised by phrases such as "raw mode", "not a tty", "requires a terminal", "not interactive", "unsupported terminal", "ink requires" before any link appeared.
- States: `starting`, `awaiting_url`, `awaiting_code` (or `awaiting_browser` for the device flow; switches to `awaiting_code` if a code prompt appears), `verifying`, then `signed_in`, `failed` or `cancelled`. A device user code shaped like `ABCD-EFGH` is shown when present. The status also carries the strategy, the redacted detail, the account, the mode and the seconds left.
- One sign-in at a time across both tools: "a sign-in for <label> is already open. Finish or cancel it first." (409).
- The first request waits up to 8 seconds for the link so it can usually answer with it directly.
- Time limit: 5 minutes from the start; then "the sign-in was not finished within 5 minutes and was stopped".
- Code validation: blank ("that code is blank"), longer than 512 characters ("that code is too long to be one"), control characters ("that code contains control characters - paste it again"); refused when the sign-in is not waiting for a code ("this sign-in is <state>, not waiting for a code") or is no longer running. The code is never logged, stored or echoed.
- Confirmation: success is decided by asking the CLI (`claude auth status --json`, or `codex login status`, 30-second limit), not by the login's exit code. The account e-mail is shown masked (first and last letter of the name, then the domain; a name of two letters or less shows only the domain); for Claude Code the sign-in method, organisation name and plan are also shown.
- Failure texts include "the CLI finished but printed no token", "<label> exited <code>", "the CLI still reports signed out", "the CLI reports signed out", "could not start <label> (...)". Any `sk-ant-` token in a transcript, status, error or log is replaced by `sk-ant-…`; error tails are at most 400 characters.
- Not on Linux, or no pseudo-terminal support: "signing in from this page needs a Linux host with a pty, which is what the container is. This dashboard is running somewhere else, so run the CLI's own login command on the host instead." Not installed by the wizard: "<label> is not installed yet. Install it first."
- Cancel: stops the CLI and records `cancelled`.
- Sign out: cancels any sign-in, runs `claude auth logout` or `codex logout` (60-second limit, best effort; its error is shown), and deletes the stored token either way.
- Surviving a restart: after a restart, "signed in" is read from the CLI's own credential file in the private home (`.claude/.credentials.json`, `.codex/auth.json`): "signed in earlier - the CLI's own credential is on disk (<file>, written <date> UTC)". A Claude Code credential file with no refresh token and an expired access token is reported as failed: "the saved sign-in has expired and cannot renew itself. Sign in again". A failed sign-in or a sign-out recorded by this process beats the file.

## AI CLI set-up wizard: the CLI's environment
(source: cli_tools.py)

- Every run of a CLI (status checks, Test, the YouTube downloader's real calls, sign-in, sign-out) gets an allow-listed environment: PATH, HOME, LANG, TZ, TERM, TMPDIR, the proxy variables (HTTP_PROXY, HTTPS_PROXY, NO_PROXY, ALL_PROXY, any case), every `LC_*`, `CLAUDE_*` and `CODEX_*` variable, and the Windows basics needed for a development run. Every other variable, including all dashboard and fleet secrets, is withheld. `ANTHROPIC_API_KEY`, `OPENAI_API_KEY`, `DEEPSEEK_API_KEY` and `ANTHROPIC_AUTH_TOKEN` are always removed.
- When the wizard's private home folder exists, `HOME` is set to it, and for Claude Code the stored token is added as `CLAUDE_CODE_OAUTH_TOKEN`. When it does not exist (a CLI the customer installed and signed in by hand), the container's own HOME is kept.

## AI CLI set-up wizard: routes and the notice
(source: cli_tools.py)

All admin only (401/403 as for the provider routes), CSRF-checked. 404 "'<name>' is not a CLI this wizard can set up" for anything but `claude_code` and `codex`. Tool refusals answer 409 for "busy" and 400 otherwise.

- `GET /api/v1/admin/ai-providers/{name}/setup`: everything the stepper needs without running the CLI: label, publisher, whether this host can install it and why not, whether CLIs are enabled, the notice (title, text, checkbox label), the install status, the sign-in status, whether signed in (a session or a stored token), the private home path, and the sign-in modes (Claude Code only).
- Notice shown as step 1: title "This uses YOUR subscription, on a shared server"; text explaining every YouTube search for every editor is spent on the account signed in, that using a personal subscription to power a service may breach its terms, that CC Sync does not ship, bundle or update either tool and the container downloads and checksum-verifies the publisher's own build only when INSTALL is clicked, and that the supported alternative is an API key; checkbox "I understand this uses my own subscription for a shared server".
- `POST /api/v1/admin/ai-providers/{name}/install`: starts an install or update to the publisher's latest. Requires CLI providers enabled for the site (409 "CLI providers are off for this site. Accept the notice in step 1 (or tick 'Allow CLI providers') before installing anything.", or the build-lock sentence) EXCEPT for Claude Code in a build-locked dashboard, where installing is allowed (sign-in stays locked). An unexpected server fault answers 503 "this server could not start the install of <label>: it hit an unexpected error (<type>). Nothing was left half-installed. Try again, or install <label> on the dashboard host yourself and type its full path below." and records a server-error notice.
- `GET /api/v1/admin/ai-providers/{name}/install-status`: the install status.
- `DELETE /api/v1/admin/ai-providers/{name}/install`: removes the install (see above); unexpected faults answer 503 the same way ("could not remove the install of").
- `POST /api/v1/admin/ai-providers/{name}/signin`, body `{mode="subscription"|"console"}`: starts a sign-in. Requires CLI providers enabled (409 otherwise, including in a locked build).
- `GET /api/v1/admin/ai-providers/{name}/signin`: the sign-in status (live session, else the last outcome, else the credential on disk, else idle).
- `POST /api/v1/admin/ai-providers/{name}/signin/code`, body `{code}` (up to 1,024 characters accepted by the body check, 512 by the code check): hands the code to the CLI.
- `POST /api/v1/admin/ai-providers/{name}/signin/cancel`: cancels the sign-in.
- `DELETE /api/v1/admin/ai-providers/{name}/signin`: signs the CLI out.
- The code, cancel, sign-out, status and remove routes do not check whether CLI providers are enabled.

## The container: the three ways to deploy it
(source: deploy/compose.yaml, deploy/compose.image.yaml, deploy/compose.appliance.yaml, deploy/Dockerfile)

- **Bind-mount mode** (`compose.yaml`, a template filled in by the studio's install script from `site.toml`): a stock `python:3.12.7-slim` container; the dashboard code, a dependency folder and the three sub-app code trees are host folders mounted in; dependencies are pip-installed at boot. No over-the-air code updates.
- **Image mode** (`compose.image.yaml`, chosen by `[stack] mode = "image"` or `--mode image`): the vendor image (`${CCSYNC_IMAGE}`, default rendered from `site.toml [stack] image`, vendor tag `ghcr.io/the-creators-club/ccsync:1`, a digest accepted). Code and dependencies are inside the image; only data folders are mounted. Over-the-air code updates possible. Same services, environment keys, ports, healthcheck and optional profiles as bind-mount mode. `APP_UID`/`APP_GID` are also passed as environment variables.
- **Appliance** (`compose.appliance.yaml`, pasted into a NAS's container manager): exactly two things to fill in, `CCSYNC_TREE` (the shared folder holding `Projects/`, `Assets/B-roll Archive/`, `Assets/Music/`) and `CCSYNC_DATA` (the stack's own state folder); `docker compose up` refuses to start without either, with a message naming it. Optional: `APP_UID`/`APP_GID` (default 3000:3001; must be set by hand to a real NAS account's ids, nothing writes them), `CCSYNC_IMAGE`, `CCSYNC_SFTP_IMAGE`, `DASH_NAS_API_TRANSPORT`, `DASH_TAILSCALE_SERVE`. No secrets are typed; site facts are entered in the dashboard's first-run wizard and stored in its database.

## The container: the dashboard image
(source: deploy/Dockerfile, deploy/requirements.txt, deploy/requirements.lock)

- Base `python:3.12.7-slim`, pinned by digest (amd64 and arm64). Dependencies installed into `/venv` from the hash-pinned lock (`--require-hashes`).
- Contents: dashboard code at `/app/src`, `/app/deploy`, `/app/templates`, `/app/static`; customer-facing documents `docs/HOW_IT_WORKS.md`, `docs/EDITOR_SETUP.md` and `docs/legal/` at `/app/docs`; b-roll web at `/broll-app`, music web at `/music-app`, YouTube downloader web at `/ytdl-app`. All read-only for everyone (no write permission).
- Markers: `/venv/.image-baked` (tells the start script not to pip install) and `/venv/.runtime-id` (the runtime id, printed during the build).
- Runs as uid:gid 3000:3000 by default (account `ccsync`); compose overrides with the site's ids. Port 8480 (documentation only). `CCSYNC_GIT_SHA` build argument becomes an environment variable (the commit reported by health; empty when not passed).
- Deliberately not in the image: ffmpeg, deno and any AI CLI (mounted or installed at run time).
- Dependency set (lock): a2wsgi, anthropic, bcrypt, cryptography, fastapi, httpx, jieba, jinja2, numpy, onnxruntime, opencc-python-reimplemented, paramiko, psycopg2-binary, pydantic, PyJWT, pynacl, pypinyin, python-multipart, rapidfuzz, requests, smbprotocol, starlette, uvicorn, websockets, yt-dlp (2026.8.19), zstandard, and their transitive packages. The optional YouTube "unblock" plugin `bgutil-ytdlp-pot-provider==1.3.1` is a separate lock, never baked in.

## The container: what happens at start (run.sh)
(source: deploy/run.sh)

- Ownership warning (never fatal): if the process uid differs from `APP_UID` (or, when unset, from the owner of `/data`), it prints warnings naming the cause and the fix (fix compose's `user:` line, or chown `/data`). Same for a gid differing from `APP_GID` ("the setgid /projects tree needs the editors group").
- `/venv` must be mounted: otherwise FATAL "... Re-run server/install_dashboard_app.py (--recreate) so the app gets the dedicated venv volume." and exit 1. Creates the venv if empty.
- Dependency install (bind-mount mode only): installs `requirements.lock` with hash checking (or `requirements.txt` if no lock) when its MD5 differs from the stamp `/venv/.requirements-hash`. A failure after a previous successful install: warning, starts with the old dependencies. A failure on a never-populated venv: FATAL, exit 1. Image mode never installs.
- YouTube unblock plugin, only when `DASH_SITE_YOUTUBE_UNBLOCK=1`: installs `requirements-unblock.lock` (hash-checked) into `/venv` (bind-mount) or into `/data/unblock-site` added to the import path (image mode), when its stamp changed or the plugin folder is missing. Up to 4 attempts with waits of 5, 15 and 30 seconds. Never fatal; on failure warns "/ytdl's PO-token path will bot-check-fail until this succeeds" and prints pip's output. Records the outcome (ok, time, attempts, error up to 4,000 characters, version) in `plugin_install.json` beside the plugin, whose path is exported as `YTDL_PLUGIN_INSTALL_MARKER` (read by the YouTube health route).
- yt-dlp nightly: unless `YTDL_YTDLP_NIGHTLY=0`, the root `/data/ytdlp-nightly` is exported as `YTDL_YTDLP_NIGHTLY_ROOT`; when `DASH_SITE_YOUTUBE_DOWNLOAD=1` or `DASH_SITE_YOUTUBE_UNBLOCK=1` a background install of the newest yt-dlp nightly starts (never blocks the boot; applies at the next start). The installed nightly named by `/data/ytdlp-nightly/current` (digits and dots only, and only if its `yt_dlp/version.py` exists) is appended to the import path, so it shadows the pinned yt-dlp.
- umask 077 for everything the process creates.
- Import path: `/app/src:/broll-app:/music-app:/ytdl-app` (plus the unblock site and the nightly). `PATH` gains `/opt/ffmpeg:/opt/claude:/opt/deno` in front.
- Access log off unless `DASH_ACCESS_LOG=1` (then announced).
- Starts `uvicorn` with one worker on `0.0.0.0:${DASH_PORT:-8480}`.
- Image mode: a loop. Each pass runs the boot selector (below) to choose the code root, starts the server as a child, forwards stop signals to it, and if it exits with code 75 (the dashboard asking for a restart) runs the selector again and restarts; any other exit code ends the container with that code. If the selector prints nothing, the image's own code is used with a warning.

## The container: choosing which code to boot (select_code_root.py)
(source: deploy/select_code_root.py)

- Runs before every image-mode boot, using only the image's own code. Prints the import path; everything else goes to the log.
- No applied bundle in `/data/code/current.json`: boot the image.
- An applied bundle whose version is not newer than the image: **retired** (current.json cleared, `retired_from` and `retired_reason` "X is not newer than the image's own Y -- the image carries it" recorded, files left on disk), boot the image. Not retired, and the refusal recorded instead, if the image knows an older database schema than the live database.
- A bundle is booted only if all hold: the version is dotted-numeric; `manifest.json` exists, is a dashboard bundle of that version; `record.json` exists ("an unsigned tree is never booted") and its signature verifies against the release keys; the record describes that dashboard version; the record's and manifest's runtime ids equal the image's; the version is newer than the image's; the four code folders exist.
- Release keys come from `DASH_RELEASE_PUBKEYS`; if empty, from `<data>/secrets/appliance_config.json`; if still empty and the variable is entirely absent, from the vendor defaults built into the image. Comma or space separated.
- Failed-boot counter (`/data/code/boot_attempts.json`): increased before each boot of a bundle; cleared by the running dashboard once healthy. When it has already reached 2, the selector reverts `current.json` to the previous tree or the image, records `reverted_from` and `reverted_reason` ("X failed to reach a healthy boot N times" or "X was refused N times: <reason>"), resets the counter, and adds the version to the "do not auto-apply" list.
- A refused bundle counts as a failed boot, except for two environment problems that are not counted: "DASH_RELEASE_PUBKEYS is not set, so no code tree can be verified" and "this image has no /venv/.runtime-id, so no bundle can be matched to it" (and a failure to load the image's own verifier).
- Never reverts into a tree (or image) that knows an older database schema than the live database (`PRAGMA user_version` of `DASH_DB_PATH`, default `/data/dashboard.db`; "cannot tell" does not refuse). Instead it stays on the applied tree and records `revert_refused_reason` ("... booting it would fail on every start. Restore the backup taken before this update and roll back from the dashboard, or deploy a newer image.") and `revert_refused_from`. That record is cleared on a later boot once the counter is back at 0.
- Any unexpected error: boots the image with a warning. A read-only `/data` only means nothing can be recorded.
- Test-only overrides: `CCSYNC_DATA_DIR`, `CCSYNC_APP_ROOT`, `CCSYNC_VENV_DIR`.

## The container: environment variables the dashboard service is given
(source: deploy/compose.yaml, deploy/compose.image.yaml, deploy/compose.appliance.yaml)

Template values marked `{{...}}` are filled from `site.toml` by the install script; `REPLACE_ME` values must be filled by hand when pasting the template. The appliance file sets only the ones marked (A).

- Sync and auth: `SYNCTHING_GUI_URL` (A: `http://tailscale:8384`), `SYNCTHING_API_KEY`, `DASH_REPORT_TOKEN` (the shared fleet token), `DASH_SHARED_REPORT_TOKEN_ENABLED` (whether that shared token is still accepted; "0" for a new site), `DASH_SESSION_SECRET` (login sessions; also derives the gear token), `DASH_ADMIN_USERS`, `DASH_SMB_HOST` (host the editor login checks passwords against; without it editor logins are refused), `DASH_COOKIE_SECURE` ("auto" honours X-Forwarded-Proto, "1" always Secure), `DASH_TRUSTED_PROXIES` (whose forwarded headers are believed), `DASH_AUTH_METHOD` (A: `local`, accounts kept by the dashboard; other values in other files' code: smb, oidc).
- Storage and port: `DASH_DB_PATH` `/data/dashboard.db` (A), `DASH_PORT` (A: 8480), `DASH_PROJECTS_DIR` `/projects` (A), `DASH_CRASH_DIR` `/data/crashes` (A; crash reports written locally, sent nowhere unless `DASH_SENTRY_DSN` is set, which is commented out), `DASH_PACKAGES_DIR` (commented out; default `/data/packages`).
- B-roll: `DASH_BROLL_ENABLED`, `BROLL_DATA_ROOT` `/broll-data`, `BROLL_SHARES` `broll:Main b-roll archive`, `BROLL_CREATORS_SHARES`, `BROLL_ARCHIVE_CREATORS_DIR`, `BROLL_DEFAULT_COLLECTION`, `BROLL_DEFAULT_COLLECTION_LABEL`, `BROLL_INGEST_TOKEN` (mandatory while b-roll is enabled; a blank, placeholder or short value stops the container starting).
- Music: `MUSIC_DATA_ROOT` `/music-data`, `MUSIC_SHARE_ROOT` `/music-share`, `MUSIC_PROXIES_DIR` `/music-proxies`, `MUSIC_TEXT_ENCODER_DIR` `/music-encoder`. No on/off switch: shipping the code tree is the switch.
- YouTube downloader: `YTDL_DATA_ROOT` `/ytdl-data`, `YTDL_PROJECTS_ROOT` `/projects`, `YTDL_DASH_DB` `/data/dashboard.db` (read-only), `ANTHROPIC_API_KEY`, `YTDL_CACHE_DIR` `/ytdl-data/cache`, `YTDL_LOCAL_DOWNLOAD` "1" (downloads tried on the requester's own computer first). Read by run.sh: `YTDL_YTDLP_NIGHTLY`. Read by the provider check: `YTDL_CLAUDE_CODE_ARGS`, `YTDL_CODEX_ARGS`.
- Timeline Cards: `DASH_CARDS_ENABLED`, `DASH_CARDS_SRC`, `DASH_CARDS_VAULT_ROOT`, `DASH_CARDS_ROOT`, `DASH_CARDS_PROJECT`, `DASH_CARDS_DB_HOST`, `DASH_CARDS_DB_NAME`, `DASH_CARDS_DB_WRITE_ALLOW`, `DASH_CARDS_DB_BACKUPS`, `DASH_CARDS_MEDIA_MAP`, `DASH_CARDS_SERVER_URL`, `DASH_CARDS_TOKEN`.
- Footage sorter: `DASH_SORTER_ENABLED`, `DASH_SORTER_SRC`, `DASH_SORTER_DATA`, `DASH_SORTER_CACHE`, `DASH_SORTER_SETTINGS` (one JSON object).
- Fleet jobs: `DASH_JOBS_ROOTS` (the root names this container can resolve for jobs it runs itself).
- Snapshots: `DASH_TREE_DATASET`, `DASH_UPDATE_SNAPSHOT_DATASET` (also the dataset the pre-update snapshot uses), `DASH_SNAPSHOT_DIR`, `DASH_SNAPSHOT_PROJECTS_SUBPATH`.
- Feature switches (all "0" in the vendor templates): `DASH_SITE_YOUTUBE_DOWNLOAD`, `DASH_SITE_YOUTUBE_UNBLOCK`, `DASH_SITE_AI_CLI_PROVIDERS`, `DASH_STUDIO_CLI_PROVIDERS` (the build lock), `DASH_SITE_AUTO_UPDATE` (companions may take a newer build unattended).
- Release channel: `DASH_RELEASE_PUBKEYS`, `DASH_VENDOR_CUSTOMER` ("1" = the vendor holds the release key, so the Protection page does not ask the customer to back it up), `DASH_RELEASE_FEED_URL`, `DASH_RELEASE_FEED_POLICY`, `DASH_VENDOR_DEFAULTS` (A: "1", absent feed URL and keys fall back to the vendor's built into the image).
- NAS access: `TRUENAS_HOST`, `TRUENAS_USER`, `TRUENAS_PW` (blank disables only the admin Users section), `DASH_NAS_KIND` (truenas or synology; left unset on the appliance to mean "wizard not run"), `DASH_NAS_HOST`, `DASH_NAS_USER`, `DASH_NAS_PW`, `DASH_NAS_SSH_PORT`, `DASH_NAS_SSH_HOSTKEY` (unset = trust on first use with a warning), `DASH_NAS_SSH_KEY_PROBE` ("0" stops an SSH session per Users page render), `DASH_NAS_HOMES_PARENT`, `DASH_NAS_SERVICE_USER`, `TRUENAS_API_KEY`/`DASH_NAS_API_KEY`, `TRUENAS_API_KEY_USER`/`DASH_NAS_API_KEY_USER`, `DASH_NAS_API_TRANSPORT` (A; auto, jsonrpc or rest), `TRUENAS_VERIFY_SSL` ("0" trust self-signed, "1", a CA bundle path, or a `sha256:` pin).
- Published to clients by the site route: `DASH_SITE_ORG_NAME`, `DASH_SITE_ORG_SHORT`, `DASH_SITE_SUPPORT_CONTACT`, `DASH_SITE_PRODUCT_NAME`, `DASH_SITE_BRAND_LOGO`, `DASH_SITE_TREE_NAME`, `DASH_SITE_TEMPLATE_FOLDERS`, `DASH_SITE_SHARED_ASSETS`, `DASH_SITE_CANONICAL_PREFIX`, `DASH_SITE_REMOTE_ROOT`, `DASH_SITE_SMB_UNC`, `DASH_SITE_SFTP_HOST`, `DASH_SITE_SFTP_PORT`, `DASH_SITE_SFTP_HOSTKEY`, `DASH_SITE_SFTP_CHUNK_SIZE` (255Ki TrueNAS, 64Ki Synology), `DASH_SITE_SFTP_CONCURRENCY`, `DASH_SITE_SFTP_SHELL_TYPE` (unix TrueNAS, none Synology), `DASH_SITE_RCLONE_REMOTE`, `DASH_SITE_NAS_SYNCTHING_ID` (fallback only), `DASH_SITE_DASHBOARD_URL`, `DASH_PROJECT_ACL`, `DASH_NAS_PROJECTS_ROOT`.
- Read by run.sh / the image only: `APP_UID`, `APP_GID`, `DASH_ACCESS_LOG`, `CCSYNC_GIT_SHA`.
- Other variables read by the code in this part: `DASH_GEAR_MODEL`, `ANTHROPIC_BASE_URL`, `OPENAI_BASE_URL`, `DEEPSEEK_BASE_URL`, `OPENAI_API_KEY`, `DEEPSEEK_API_KEY`, `DASH_RELEASE_FEED_SIG_URL`, `DASH_RELEASE_FEED_INTERVAL`, `DASH_RELEASE_SOAK_MINUTES`, `BROLL_DATA_ROOT`, `MUSIC_DB_PATH`, `MUSIC_DATA_ROOT`, `YTDL_DATA_ROOT` (database locations for backups), `CCSYNC_RUNTIME_ID_FILE` and `CCSYNC_APP_ROOT` (test only).

## The container: volumes and ports
(source: deploy/compose.yaml, deploy/compose.image.yaml, deploy/compose.appliance.yaml)

- Bind-mount and image mode volumes (host paths under the apps root or the tree root):
  - code, bind-mount mode only, read-only: `app` to `/app`, `broll-web` to `/broll-app`, `music-web` to `/music-app`, `ytdl-web` to `/ytdl-app`; and `venv` to `/venv` (writable, owner-only);
  - `data` to `/data` (database, packages, secrets, code bundles, backups, tools);
  - `<tree>/Projects` to `/projects` (read-write; the project-setup page creates folders there);
  - `<tree>/Assets/B-roll Archive` to `/broll-data` (read-write, the shared archive itself);
  - `music-data` to `/music-data` (rw), `music-encoder` and `music-proxies` (read-only, optional artefacts), `<tree>/Assets/Music` to `/music-share` (rw);
  - `ffmpeg` to `/opt/ffmpeg` (ro; empty is a supported state);
  - `ytdl-data` to `/ytdl-data` (rw);
  - `cards-web` to `/cards-app` (ro), `sorter-web` to `/sorter-app` (ro), `sorter-data` to `/sorter-data` (rw), in both modes (other repos' code). An empty folder means the feature reports itself absent.
  - Added per site by the install script only when configured: the Timeline Cards vault (`/vault`, rw) and footage share (`/media`, ro) with an extra group; the footage pool (`/pool`, rw, one bind); `/opt/deno` and the PO-token sidecar service `bgutil` only with `youtube_unblock`; a snapshot folder when given.
- Ports: one bind per configured interface (LAN and tailnet on TrueNAS; 127.0.0.1 only on Synology), never 0.0.0.0.
- Healthcheck: every 60 s, 10 s timeout, 3 retries, 120 s start grace; healthy only when `/api/v1/health` returns JSON with `ok` true (the status code alone is not enough).
- Logs capped at 5 files of 20 MB per service. `restart: unless-stopped`.
- Optional services in bind-mount and image mode, inactive unless their profile is named:
  - `bundled-syncthing`: Syncthing 1.30.0 as the app uid, API key from `SYNCTHING_API_KEY` (compose refuses to start without it), GUI on 127.0.0.1:8384 only, sync ports 22000 tcp/udp and 21027 udp, tree at `/data`, config in `syncthing-config`.
  - `project-server`: PostgreSQL 13 for Resolve's project library, bound to LAN and tailnet only, data in `postgres`; refuses to start when `PG_PASSWORD` is empty or `DaVinci`/`davinci` ("refusing to start: set PG_PASSWORD to a long random value, never the Resolve default"); on an existing database resets the `postgres` role's password to the configured one before starting, and refuses to start if that fails.
- Appliance volumes and ports: dashboard gets `${CCSYNC_DATA}/data` to `/data`, the sftp public host key folder read-only at `/sftp-hostkey-pub`, the three tree subfolders, and the tailnet daemon's socket volume at `/var/run/tailscale`; port 8480 on 127.0.0.1 only (reaching it from elsewhere is through the tailnet node once signed in). Same healthcheck and log cap.

## The container: the appliance's other services
(source: deploy/compose.appliance.yaml, deploy/sftp/*, deploy/tailscale/serve.json)

- `secrets-init` (one-shot, root, the dashboard image): creates `/data/secrets/syncthing.env` (`STGUIAPIKEY`, 32 hex characters) and `/data/secrets/internal.env` (`CCSYNC_INTERNAL_TOKEN`, url-safe random) only if missing; files 0600, folder 0700, owned by the app uid; makes `/data` owned by the app uid (mode 750, not recursive); creates and owns the tailnet state folder, the socket volume and the Syncthing config folder (failures only logged); creates `Projects`, `Assets`, `Assets/B-roll Archive`, `Assets/Music` in the tree only when missing, and chowns only the ones it created. Every other service waits for it to finish successfully.
- `syncthing`: always on, Syncthing 1.30.0 as the app uid, API key from the generated file, GUI on 0.0.0.0:8384 inside the tailnet node's network (the dashboard sets a GUI login, per the comment, in code outside this part), tree at `/data`. No host ports; reachable on the tailnet node's address.
- `sftp`: the `ccsync-sftp` image (Alpine 3.20 pinned by digest, OpenSSH). In the tailnet node's network (port 22 on the node's address, no host port). Has `SYS_ADMIN` and unconfined AppArmor for a future per-project view feature that nothing uses yet (DORMANT). Mounts the whole tree at `/jail/tree`, host keys at `/etc/ssh/keys` (persist), public key folder at `/etc/ssh/pub`.
  - At start: reads the internal token from `CCSYNC_INTERNAL_TOKEN_FILE` or `CCSYNC_INTERNAL_TOKEN` (missing = warning, every editor login then fails), stores it 0440 for the key lookup account; generates ed25519 and RSA-4096 host keys only if absent; publishes the ed25519 public key for the dashboard (best effort); makes sure an `editors` group has gid `APP_GID` (default 3001), renaming whatever group already has that gid, and exits with an error if that group is root, sftpkeys or sshd.
  - Accounts: asks `GET <CCSYNC_DASHBOARD_INTERNAL_URL, default http://dashboard:8480>/internal/sftp/users` (bearer token, 10 s limit) at start, every 30 seconds, and on a HUP signal to the container; creates each missing account with the given uid (shared uids allowed), group `editors`, no home, no shell, key-only. Never deletes an account. Unreachable dashboard: list left unchanged.
  - Login: key only (passwords, keyboard-interactive and root login off). Keys come from `GET /internal/sftp/keys/<user>` per connection (5 s limit; any failure = no key = refused); no key files are read. Every editor is locked into SFTP only, chrooted, starting in `/tree`, with files written 664 and folders 2775 (umask 002). No forwarding, tunnels or X11.
- `tailscale`: the stack's own tailnet node, `tailscale/tailscale:v1.102.2` pinned by digest, hostname `ccsync`, run as the app uid with userspace networking (no root, no host ports), state in `${CCSYNC_DATA}/tailscale`. Sits waiting for sign-in, which the dashboard drives (outside this part). Kernel networking is a commented-out option.
  - `DASH_TAILSCALE_SERVE` (e.g. `/config/serve.json`) is passed as `TS_SERVE_CONFIG`; `serve.json` publishes https on 443 to `http://dashboard:8480`. UNREACHABLE as shipped: the service runs `tailscaled` directly, which does not read that variable.
  - Known gap (stated in the file): if the tailnet daemon alone is restarted by Docker, Syncthing and sftp stay attached to the old network and are unreachable until the stack is brought up again by hand.

## The package's dependency groups (pyproject.toml)
(source: dashboard/pyproject.toml)

- Package `ccsync-dashboard` version 0.7.80, Python 3.12 or later, command `ccsync-dashboard` (runs the app).
- Always: fastapi, uvicorn, jinja2, requests, smbprotocol.
- Optional groups, each a feature: `broll` (numpy, rapidfuzz, jieba, opencc-python-reimplemented: b-roll search incl. Chinese word search), `music` (python-multipart, onnxruntime: music search and ingest), `ytdl` (anthropic, yt-dlp: YouTube downloader), `cards` (a2wsgi, psycopg2-binary, zstandard, pypinyin, httpx, websockets: Timeline Cards and its new editor), `ytdl_unblock` (bgutil-ytdlp-pot-provider 1.3.1, exact), `synology` (paramiko: Synology NAS backend), `oidc` (PyJWT: single sign-on login), `dev` (pytest, pytest-xdist, httpx, PyYAML).
- The deployed container's requirements file installs all of these except `ytdl_unblock` and `dev` on every site (paramiko and PyJWT included).

## Looks redundant or overlapping

- Three compose files carry the same ~90 environment keys and comments (bind-mount, image, appliance), plus the install script's own dictionary copy of the same structure.
- Two deploy modes (bind-mount with pip at boot, image) run side by side; bind-mount mode keeps a whole dependency-install path in run.sh that image mode skips.
- `DASH_NAS_*` and `TRUENAS_*` variables carry the same values twice, by design.
- Two backup/rollback mechanisms for the dashboard's code: the admin rollback route and the boot selector's automatic revert, each with its own schema guard (written twice, in two files, with the same rule).
- Version parsing and comparison is implemented separately in dashboard_update, select_code_root, release_feed, release_trust and cli_tools.
- Two "is the dashboard behind" surfaces: the self-update status (code/runtime updates) and package_store's "what is running" box, both reading the feed.
- Gear identify runs its own long-lived Claude Code process outside the provider chain, duplicating what ai_providers resolves for other features.
- The feed's admin "Publish" and the Packages page upload both publish packages (one store, two doors), and the feed's `current` policy is a third door that makes builds current.
- The Ed25519 verifier also contains signing and key derivation the dashboard never uses.
- `dashboard_update.py` defines the process-exit helper twice (the second definition replaces the first).

## Claims the code does not back

- compose.yaml / compose.image.yaml comments say "NOTHING IS EVER INSTALLED ... no binary in the image, no volume and no download" for CLI providers, and run.sh/compose say "/opt/claude is GONE ... there is no CLI subprocess": cli_tools.py downloads and runs Claude Code and Codex into `/data/tools`, and gear identify always runs Claude Code.
- `ai_providers.test_provider` docstring says DeepSeek is tested with a one-token completion; the code does a GET of `/models` for all three API providers.
- requirements.txt header says run.sh installs "exactly this file into the persistent /data/venv"; run.sh prefers the lock and installs into `/venv`.
- Dockerfile header says the image "has never been through docker build" and that bind-mount mode "is still the DEFAULT"; the release feed and self-update code are built around a published vendor image (cannot confirm from code which is the default).
- `dashboard_update._exit_process`'s first docstring says it calls `logging.shutdown()` first; a second definition later in the file replaces it and exits without that.
- compose.appliance.yaml describes the dashboard's tailnet login as "WP B, not yet built" in one comment and as existing (tailnet_serve.py) in another.
- release_feed's poller comment mentions an `auto` policy; only manual, stage and current exist.
- sftp/entrypoint.sh and sshd_config say a regenerated host key makes editors' rclone refuse the NAS; the appliance compose comment says rclone does not pin it (and later that it is now pinned via the site route). Not settled here.
- `cli_tools._auto_update_run` docstring says a failure is "surfaced as a notice"; this file only writes `auto_update.json` and logs.

## Could not determine

- Where the site switch `ai_cli_providers` is turned on by "accepting the wizard's notice" (the install route's refusal tells the admin to do so); no route in this part sets it.
- What consumes `auto_update.json`, the runtime-mismatch banner state and the `dashboard_auto_update_note` beyond the routes here (fleet page, alerts, health page are in other files).
- The `/internal/sftp/users` and `/internal/sftp/keys/<user>` routes and the Syncthing GUI login are implemented outside this part.
- Whether a recall entry whose `kind` has a capital letter is still dropped from the offered list (the recall list is lower-cased but the offered-record comparison uses the record's kind as written; such records are dropped anyway by the lower-case rule).
- Whether `requirements.lock` lines were read in full: only the package names and versions were extracted (the 1,322 hash lines were not read one by one).
