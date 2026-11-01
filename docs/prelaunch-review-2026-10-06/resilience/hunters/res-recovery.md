# Pre-launch resilience pass - res-recovery (disaster recovery)

Lens: what happens when something large is lost at a customer site we cannot
reach - the NAS, the dashboard's data volume, the release key, the admin's
password, an editor's computer - and whether the backups and snapshots in
`docs/BACKUP_RESTORE.md` are actually restorable. Working tree as of
2026-10-06 (HEAD 08b40eb plus uncommitted changes).

Read: `docs/BACKUP_RESTORE.md` (whole), `docs/RELEASE.md` key sections,
`docs/APPLIANCE_INSTALL.md`, `docs/ANDROID.md` signing,
`dashboard/{auth,local_users,setup_api,setup_routes,account_password,secrets_boot,internal_sftp,dashboard_update,recovery,protection,release_feed,collector,db}.py`
(the relevant functions), `dashboard/static/cc/dashboard_update.js`,
`dashboard/templates/partials/admin_dashboard_update.html`,
`dashboard/deploy/compose.yaml`, `server/install_syncthing_app.py`,
`installer/windows_bootstrap.ps1` (NAS device seeding),
`companion/{site,identity,app(identity watch),release_pubkey}.py`,
`tools/release_key.py`, `ytdl/web/ytdlweb/db.py`. Checked against
`KNOWN_BUGS.md`, the 2026-08-28 and 2026-09-03 sweeps and the 2026-09-24
hunt so nothing here is a re-report of a fixed item. One probe: a missing
`dashboard.db` beside an existing `backups/` and `secrets/` is silently
recreated empty (confirmed).

Not covered: offsite replication mechanics, the Cards per-episode data's own
restore story, Synology-specific restore paths beyond reading the docs.

### res-recovery-1 - A local-auth (appliance) site whose only admin forgets the password has no way back in

- **Severity:** high
- **Confidence:** CONFIRMED
- **Where:** `dashboard/src/ccsync_dashboard/auth.py:150-180` (verify_credentials local branch), `auth.py:936-960` (is_admin), `dashboard/src/ccsync_dashboard/setup_api.py:64-104` (setup_admin refuses once any user exists), `dashboard/src/ccsync_dashboard/account_password.py:165-172`, `dashboard/src/ccsync_dashboard/local_users.py` (no CLI), `docs/APPLIANCE_INSTALL.md`
- **What:** Under `DASH_AUTH_METHOD=local` (the zero-touch appliance shape we will sell) the password check is a scrypt compare against `local_users`. The first-admin bootstrap closes for good once any account exists. `DASH_ADMIN_USERS` (the documented break-glass) grants the admin ROLE but still needs a local row with a password the person knows. There is no reset CLI in the dashboard package (no `__main__` other than app/collector), no email reset, no docs section. The only exits are a second admin, or sqlite surgery writing a scrypt hash by hand, or deleting `dashboard.db` (losing every account, SSH key and tick - see res-recovery-2).
- **Scenario:** A small studio with one admin (the owner) forgets the password after a holiday. Editors keep syncing, but nobody can approve a new computer, tick a project, publish an update or restore anything. Support has no supported instruction to give.
- **Recommendation:** Ship a supported recovery: e.g. `docker exec <container> python -m ccsync_dashboard.local_users reset-password <user>` (prints a one-time password, audits, revokes sessions), or a reset file dropped into `/data/secrets/` that the next boot consumes. Document it in APPLIANCE_INSTALL.md and in the sign-in page's "forgot password" text. Encourage a second admin in the wizard.
- **Known:** none (bug-hunt-2026-08-21 noted DB surgery as the only recovery for a different lock-out; not tracked as open).

### res-recovery-2 - A missing or empty dashboard.db is silently recreated, reopening the anonymous admin window and wiping accounts, SFTP keys and ticks without an alarm

- **Severity:** high
- **Confidence:** CONFIRMED (probed)
- **Where:** `dashboard/src/ccsync_dashboard/app.py:736-738` (lifespan: `db.connect` + `db.migrate`), `dashboard/src/ccsync_dashboard/db.py:710-730` (sqlite3.connect creates the file), `dashboard/src/ccsync_dashboard/setup_routes.py:91-119` (first_run_open), `dashboard/src/ccsync_dashboard/internal_sftp.py` (SFTP keys come from dashboard.db in local mode), `dashboard/src/ccsync_dashboard/secrets_boot.py` (a missing secrets file is regenerated)
- **What:** Nothing checks that the data volume a dashboard boots on is the one it ran on yesterday. A `/data` bind mount pointing at an empty directory (pool re-imported under another path, a dataset migration like CR-227 done wrong, a pasted compose file with a typo, a restore into the wrong place) boots cleanly: a fresh schema, fresh secrets, the first-run wizard. Probe: a missing `dashboard.db` next to an existing `backups/` and `secrets/` directory is created empty, `any_users_exist` is False and `selections_seeded` is unset.
- **Scenario:** Appliance site, local auth. After a NAS reboot the app's host path resolves to an empty folder. The dashboard comes up green. (a) The anonymous first-admin window is open again to anyone on the tailnet: whoever opens the page first becomes admin. (b) Every local account and every editor's SSH key is gone, so the SFTP sidecar's `AuthorizedKeysCommand` refuses everyone: lanes A and B stop fleet-wide. (c) A regenerated `DASH_SESSION_SECRET` 401s every companion report. (d) Ticks made since the last seed are gone. Nothing on any page says "this looks like a different database"; the admin sees a setup wizard.
- **Recommendation:** Write a volume identity (an instance id plus the last known schema/row counts) in two places, for example `dashboard.db` and `/data/secrets/instance`, and also echo it into the report reply so companions remember it. At boot, refuse to create a fresh database when `/data/backups/`, `/data/secrets/` or `/data/code/` already exist, or when companions present an instance id this database has never issued: show a "this is not the database this site was using" page with the restore options instead of the setup wizard. Keep the anonymous first-run window closed unless an explicit `DASH_FIRST_RUN=1` or a reset file is present.
- **Known:** none.

### res-recovery-3 - When the NAS Syncthing gets a new identity, lane C stops on every editor computer and only a per-machine reinstall fixes it

- **Severity:** high
- **Confidence:** CONFIRMED
- **Where:** `installer/windows_bootstrap.ps1:1849-1932` (Ensure-NasSyncthingDevice, the only writer), `installer/macos_bootstrap.sh`, `companion/src/ccsync_companion/site.py:14,75` (nas_syncthing_id cached, never used), `companion/src/ccsync_companion/sync/syncthing_admin.py` (no device add or update), `dashboard/src/ccsync_dashboard/collector.py:1244-1265` (myID adopted with no change detection), `server/install_syncthing_app.py:54-60` (config in an ix_volume), `docs/BACKUP_RESTORE.md` sections 1 and 8
- **What:** The NAS's Syncthing device id is its TLS cert, kept in a TrueNAS `ix_volume` that no snapshot covers (OPS-22, documented). It changes whenever that volume is lost, the app is reinstalled, or the NAS is replaced. Each editor's Syncthing learned the NAS device id once, when the bootstrap installed it. The companion fetches `nas_syncthing_id` in the site manifest, but nothing compares it to its local Syncthing config or re-seeds it, so every editor's Syncthing drops the new NAS as an "unknown device". The runbook's recovery (BACKUP_RESTORE section 8: reinstall the Syncthing app, approve each editor's device on the NAS) fixes only the NAS side. The collector adopts the new `myID` without noticing that it changed, so no notice or alert fires.
- **Scenario:** A customer's Apps pool fails, or they reinstall the Syncthing app. They follow section 8 and approve every pending device. Lane C (project files, subtitles, LUT and stills libraries) stays dead on every machine with no clear message. The fix is to re-run the bootstrap, or hand-edit Syncthing, on every editor computer, some of them remote. Nothing is lost, but the fleet silently stops sharing `.drp` files.
- **Recommendation:** Have the companion reconcile on each manifest refresh: if `nas_syncthing_id` is in the manifest and missing from its Syncthing devices, add it (keeping the old one until the new one connects). Have the collector record the last `myID` in `meta` and raise a notice or alert when it changes. Add both steps to section 8. Better still, back up the Syncthing cert and key (`cert.pem` / `key.pem`) into `<apps>/data/secrets/` at install, so a reinstall keeps the same identity.
- **Known:** OPS-22 (documented the gap; the editor-side half is not named anywhere).

### res-recovery-4 - The Resolve Project Server database, which holds every edit, is outside the backup story entirely

- **Severity:** high
- **Confidence:** CONFIRMED
- **Where:** `docs/BACKUP_RESTORE.md` section 1 table ("two datasets carry everything that matters"), `dashboard/src/ccsync_dashboard/protection.py` (no line for it), `dashboard/src/ccsync_dashboard/recovery.py` (no problem for it), `dashboard/deploy/compose.yaml:752-772` (optional profile, `POSTGRES_PASSWORD` default `DaVinci`), `docs/SERVER.md:460,547`, `docs/HOW_IT_WORKS.md:58-60,823-825`
- **What:** HOW_IT_WORKS tells customers the NAS hosts Resolve's shared project library. That Postgres database holds every timeline, i.e. the editors' actual work. It does not appear in the "what is protected" table. No `pg_dump` is taken anywhere. The protection panel, the RECOVERY page and `setup_snapshots.py` never mention it. On the studio's own site it runs as a separate TrueNAS app, administered separately; like Syncthing's, its storage is very likely an app volume outside both snapshot targets. With the compose profile it lands under the apps root, so it is covered only where that root is a real dataset (not on DSM, where snapshots are CANNOT VERIFY). A raw file snapshot of a live Postgres is restorable only if it is atomic for the whole data directory, and nobody has rehearsed it. The default password is Resolve's well-known one.
- **Scenario:** A NAS app reinstall, or a pool problem on the Apps pool, loses the project server's volume. Footage and proxies are all intact and every page is green, but every edit since the project began is gone. The restore drill on the protection panel would have passed, because it only copies a file from the tree.
- **Recommendation:** Name it in BACKUP_RESTORE's table. Add a scheduled logical backup (`pg_dumpall` into the snapshotted apps dataset, or Resolve's own Project Server backup schedule), plus a protection line "project database backed up within 25 h", and a RECOVERY problem "projects/timelines are gone". At minimum, make the protection panel say NOT COVERED when `[stack] project_server` is on. Change the default Postgres password at install.
- **Known:** none.

### res-recovery-5 - The dashboard's own database restore is only reachable as a code rollback: image mode only, the before-last-update copy only, and it rolls b-roll and music back too

- **Severity:** high
- **Confidence:** CONFIRMED
- **Where:** `dashboard/src/ccsync_dashboard/dashboard_update.py:1263-1287` (restore_backup), `:1589-1660` (rollback, the only caller, with a 409 in bind-mount mode and when `current.version` is empty), `:1885-1928` (route), `dashboard/templates/partials/admin_dashboard_update.html:105-112` (one checkbox, the schema backup only), `dashboard/static/cc/dashboard_update.js:255-275`, `dashboard/src/ccsync_dashboard/recovery.py:976-1003` ("it can put one back by itself"), `docs/BACKUP_RESTORE.md` callout row 3 and section 4c
- **What:** RECOVERY's "this dashboard has lost projects, editors or their ticks" sends the admin to Settings -> PACKAGES, promising that "it can put one back by itself" with no shell. In code, `restore_backup` is called only from `rollback()`, and only for the single backup taken before the last update (`schema.backup`). `rollback()` refuses in bind-mount mode and when the dashboard runs the image's own code, i.e. on any site that has never taken an OTA. The other backups `list_backups` knows about cannot be chosen. A restore always comes with a code rollback, and it overwrites `broll.db` and `music.db` as well, discarding newer index publishes and editors' queued music ingests. No safety copy of the current state is taken first, so a wrong choice cannot be undone. Backups exist only before updates; nothing takes a periodic one.
- **Scenario:** An admin deletes the wrong user, which cascades: their computers are forgotten and their ticks deleted. Or a bug wipes `selections`. The RECOVERY page sends them to PACKAGES. On a fresh image-mode install there is no rollback target, so there is nothing to click. On a site with OTA history the only option rolls the code back and returns all three databases to the moment before the last update, maybe weeks ago, losing every tick, machine, `cce1` token and b-roll publish since. Machines whose `cce1` tokens were minted after that moment start getting 401s. The fallback is a root shell, which the appliance customer does not have.
- **Recommendation:** Add a standalone "restore this dashboard's database" action, independent of code rollback. It should list every backup, restore `dashboard.db` alone by default (with the indexes as separate opt-in choices), and always take a `before-restore` backup first. Add a daily `backup_databases(label="daily")` so there is a point less than a day old even on DSM. Make the RECOVERY copy say exactly what is possible on this deployment.
- **Known:** none.

### res-recovery-6 - No plan for a compromised release key: one plaintext key signs both editor builds and dashboard code, with no revocation path

- **Severity:** high
- **Confidence:** CONFIRMED (code and docs facts; the threat itself is a judgement)
- **Where:** `tools/release_key.py:1-27` (no passphrase, by design), `companion/src/ccsync_companion/release_pubkey.py` (RELEASE_PUBKEYS list, no revocation), `dashboard/src/ccsync_dashboard/release_feed.py:1138-1260` (`policy = current` auto-applies dashboard bundles), `:499-525` (recalls name a version, not a key), `docs/RELEASE.md:700-835` (rotation only; "compromise" appears only as motivation), `docs/RELEASE_FEED.md:526-540`
- **What:** A single Ed25519 seed, stored unencrypted in a file in the owner's daily-use Windows profile (with a hand-copied twin on the Mac), signs companion builds, onboard installers AND the dashboard's own code bundles, which run inside every customer's container with all its secrets. Customers' dashboards pin that key in env (`DASH_RELEASE_PUBKEYS`) and companions bake it in. There is no revocation record (a recall withdraws one version, and a thief can sign recalls too), no second key held offline to sign a "distrust key X" statement, and no runbook for "the key leaked". The documented rotation assumes the old key is still trustworthy for the overlap release, and it ends with editing `DASH_RELEASE_PUBKEYS` by hand plus a `--recreate` on every customer dashboard.
- **Scenario:** The base rig is compromised (it runs many unattended tools with wide permissions, and the key file is readable by every process in the profile). Anyone who also gets feed or GitHub write access can push a signed dashboard bundle that `policy = current` customers apply unattended, and a signed companion every editor installs. Even after we notice, the fix is: hope our overlap release beats the attacker's, then visit every customer.
- **Recommendation:** Before the first paying customer: (a) write a compromise runbook. (b) Move signing to a hardware token or an offline machine, or at least encrypt the key at rest with the passphrase held in DPAPI or the OS keychain. (c) Bake a second, cold "revocation" key whose only power is to sign a key-distrust list, honoured by companions and dashboards. (d) Consider a separate key for dashboard bundles. (e) Make `DASH_RELEASE_PUBKEYS` updatable through a record signed by an already-trusted key, so a rotation does not need a visit to each site.
- **Known:** logic-release-1 (09-24, rotation steps) is fixed in the docs; compromise is not tracked anywhere.

### res-recovery-7 - ytdl.db is migrated by an update but never backed up, and rollback checks only the dashboard's schema

- **Severity:** medium
- **Confidence:** CONFIRMED
- **Where:** `dashboard/src/ccsync_dashboard/dashboard_update.py:659-686` (`_db_paths`: dashboard, broll, music only), `:1016-1039` (backup_databases), `:1570-1587` (schema_rollback_check reads the dashboard's version only), `ytdl/web/ytdlweb/db.py:448-481` (ensure_schema migrates on connect, FATAL on a newer user_version), `docs/BACKUP_RESTORE.md` section 3 ("copies ... broll.db / music.db / ytdl.db")
- **What:** The runbook says the pre-update backup includes `ytdl.db`. The code never includes it. `ytdlweb` applies its migrations on the first connection after an OTA. REL-10's rollback guard compares only `dashboard.db`'s schema with the target tree, so a rollback after a release that carried a ytdl, broll or music migration is called "safe". Where the old code refuses a newer `user_version`, as ytdl does, the old code meets a database it rejects, and there is no copy to restore.
- **Scenario:** Dashboard 0.7.x ships ytdl migration 016 and misbehaves. The admin rolls back. `/ytdl` raises "FATAL: database ... newer than this app supports" and the YouTube stack is down until the next forward update. A site that needs the old build cannot have YouTube at all.
- **Recommendation:** Add ytdl.db (and `client_shares.db`) to `_db_paths`. Extend `schema_rollback_check` to every sub-app's `user_version` and record them in the tree manifest. Correct section 3 of the runbook.
- **Known:** none.

### res-recovery-8 - Every customer dashboard shows a permanent BROKEN "release key not backed up" line it cannot fix truthfully

- **Severity:** medium
- **Confidence:** CONFIRMED
- **Where:** `dashboard/src/ccsync_dashboard/protection.py:483-505` (_check_key_backup), `docs/RELEASE.md:830-845` (image mode requires `DASH_RELEASE_PUBKEYS`), `dashboard/deploy/compose.appliance.yaml:36`
- **What:** The line is skipped only when no release key is configured. Every image-mode or appliance customer must pin the VENDOR's key, so every customer's protection panel says that nobody has confirmed the offline release key is backed up, and warns that losing it means no update can ever be published. That key is ours, on our workstation. The customer can clear the line only by "recording a backup" they never made. The panel's MISSING lines also feed alerts and notices.
- **Scenario:** A new customer's first view of PROTECTION, and their weekly report, carry a red line about something they cannot act on. They learn to ignore red lines on the panel, or tick it falsely. Both defeat the panel's purpose ("MISSING, never silence").
- **Recommendation:** Show this line only where this site signs its own builds (a site setting, or the presence of a site key different from the vendor's baked list). Otherwise show it as "vendor-held: not this site's responsibility". Track the vendor key's backup on our side (it already has `backup.json`).
- **Known:** none.

### res-recovery-9 - A dead NAS takes every original not on an editor's disk, and nothing in the product says offsite is missing

- **Severity:** medium
- **Confidence:** CONFIRMED
- **Where:** `dashboard/src/ccsync_dashboard/protection.py` (checks: snapshot tasks, recency, keys, drill, versioning, trash, alert sink; no replication line), `docs/BACKUP_RESTORE.md:122-125, 596-599`, `docs/HOW_IT_WORKS.md:826-827`
- **What:** Snapshots live on the same pool. Remote editors hold proxies and their own uploads, so the NAS is the only copy of every original that came from a wired machine, a card ingest or the b-roll archive. It is also the only copy of `dashboard.db`, `broll.db`, `client_shares.db`, `music.db` and the project server. Offsite is documented as a per-customer decision, but the panel that exists to turn "unverified" into MISSING renders all green without it. TrueNAS exposes `replication.query` / `cloudsync.query` through the same API the panel already reads snapshot tasks from.
- **Scenario:** Fire, theft, ransomware on the NAS admin account, or a two-disk loss on a RAIDZ1. The customer believed "the protection page is green" meant they were backed up.
- **Recommendation:** Add a protection line "a copy exists off this NAS": TrueNAS replication or cloud-sync tasks covering the tree and apps datasets with a recent successful run, otherwise MISSING with the click path. On DSM, an admin-acknowledged date like the key-backup line. Name the gap in the customer-facing install checklist and in the contract.
- **Known:** documented as deliberately out of scope (COMMERCIAL_READINESS item 8); no visibility item open.

### res-recovery-10 - A deploy-mode site's site.toml exists only on the operator's PC and is not in any backup list

- **Severity:** medium
- **Confidence:** CONFIRMED
- **Where:** `.gitignore:15` (`site.toml`), `server/install_dashboard_app.py:2154-2175, 2254` ("the container has no site.toml"), `docs/BACKUP_RESTORE.md` section 1 (not listed), `docs/INSTALL.md`
- **What:** For TrueNAS and Synology deploy-mode sites, `site.toml` is the persistent source of `[nas] ssh_hostkey` pins, dataset names, `[stack] mode`, `[features]` flags, b-roll shares, telemetry switches and more. Each redeploy re-derives the container env from it. It is gitignored and copied nowhere: not to the NAS, not into the dashboard, not into the backup table. The repo's own comments record a redeploy silently emptying a setting the file did not carry.
- **Scenario:** The machine the operator deploys a customer from dies or is reimaged. The next deploy, run from a reconstructed `site.toml`, silently turns off customer features, changes datasets (the protection panel then says CANNOT VERIFY), or re-pins the NAS host key on first use.
- **Recommendation:** At every deploy, upload a copy of the resolved `site.toml` (no secrets) to `<apps>/data/site.toml.deployed`, and expose a "download this site's settings" link on Settings. Have the installer warn when the local file differs from the deployed copy. Add it to the section 1 table.
- **Known:** none.

### res-recovery-11 - The Android signing keystore's password exists only as a DPAPI blob on one Windows profile

- **Severity:** low
- **Confidence:** CONFIRMED
- **Where:** `docs/ANDROID.md:128-133`, `%USERPROFILE%\.ccsync-release\android.keystore.pw.dpapi` (no backup record beside it, unlike `release.key`'s `backup.json`), `tools/release_key.py` (`backup` covers only `release.key`), `docs/BACKUP_RESTORE.md:75`
- **What:** The docs say to back the keystore up "the way release.key is". But its password is DPAPI-encrypted to this Windows user. A reimage, a new profile or a new machine loses the password even if the keystore file was copied, and the tooling has no backup command or record for either. Losing either means a new Play listing and every phone reinstalling.
- **Scenario:** The base rig is rebuilt. Someone restores `.ccsync-release` from the offline copy. `release.key` works, the keystore cannot be opened, and the Android app can never be updated again.
- **Recommendation:** Extend `release_key.py backup` (or add an Android twin) to export the keystore and print its password for the password manager, write a backup record, and add the keystore to the protection page's vendor-side checklist.
- **Known:** none.
