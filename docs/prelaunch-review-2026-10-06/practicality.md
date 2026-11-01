# Pre-launch review 2026-10-06: practicality pass (does it work for real people)

This is the practicality pass of the pre-commercial-launch review. It covers the whole repo at HEAD `08b40eb` plus the working tree as it stood, which was uncommitted: alert-kind selection, companion fixes and `docs/ZERO_DOWNTIME_DEPLOY.md`. Dashboard is 0.7.73 and companion 0.9.84.

The owner asked for "every single thing that should be looked at or changed before going live commercially". In this pass, ten Opus hunters each walked one set of real journeys, playing the person who has to do them: a new customer's admin, a new editor, a working editor on deadline, the admin's week, and the vendor supporting ten customers. The lenses were:

- `prac-install`: customer server install, appliance and base rig
- `prac-editor-onboard`: an editor's first day
- `prac-editor-daily`: an editor's working day
- `prac-admin-daily`: the admin's week
- `prac-errors`: error and refusal copy
- `prac-docs`: customer-facing docs against the code
- `prac-config`: site.toml, env and Settings
- `prac-perf`: measured page and idle cost
- `prac-support`: vendor support for N customers
- `prac-simplify`: complexity that earns nothing

An adversarial Opus verifier was then asked to refute every critical and high. This synthesis merged duplicates across hunters; every merged item cites all of its source ids.

The pass was read-only throughout. Nothing touched the NAS, the deployed dashboard, Tailscale, GitHub or Resolve. Probes were small scratchpad scripts run against repo code, for example building appliance `Settings`, seeding a 10-editor fleet, and running the lane-error classifier. Raw reports are in `practicality/hunters/`, and the merged list is in `practicality/results.json`.

**Tally: 129 raw findings (2 critical, 41 high, 66 medium, 20 low), which merge to 99 distinct items.** After verification and dedupe: **1 critical, 12 high, 70 medium, 16 low.**

| Hunter | Raw | Crit | High | Med | Low |
|---|---|---|---|---|---|
| prac-install | 17 | 2 | 8 | 6 | 1 |
| prac-editor-onboard | 12 | 0 | 3 | 8 | 1 |
| prac-editor-daily | 11 | 0 | 1 | 8 | 2 |
| prac-admin-daily | 13 | 0 | 6 | 4 | 3 |
| prac-errors | 12 | 0 | 3 | 6 | 3 |
| prac-docs | 13 | 0 | 4 | 7 | 2 |
| prac-config | 16 | 0 | 8 | 5 | 3 |
| prac-perf | 7 | 0 | 1 | 6 | 0 |
| prac-support | 12 | 0 | 3 | 7 | 2 |
| prac-simplify | 16 | 0 | 4 | 7 | 5 |

**Verifier outcome on the 43 criticals and highs:**
- 17 were CONFIRMED at the claimed severity.
- 26 were real but DOWNGRADED: one critical to high (`prac-install-2`) and 25 highs to medium.
- 0 were refuted.

The downgrades mostly fall into four groups:
- A gap that is already openly labelled DRAFT.
- A gap that is documented and recoverable without data loss.
- Support friction rather than a blocker.
- A scenario overstated by the hunter. For example, Send to Resolve already unions the site's and the companion's own URLs, and suspended accounts are already refused per person.

Where verifiers on merged items disagreed, the item's severity and the reason are stated. Mediums and lows were not verified.

Running theme: **the appliance install path, the one the commercial product is built around, cannot complete for a new customer as shipped.**
- PRAC-1: it has no admin.
- PRAC-4: it has no tailnet publish.
- PRAC-5: the Syncthing URL is missing.
- PRAC-7: the Syncthing config folder is root-owned.
- PRAC-8: it has no uid step.
- PRAC-2 and PRAC-9: it has no vendor feed and a stale image.

The only working install, PRAC-3, needs a vendor engineer, the repo and the customer's NAS admin password. Decide the v1 install story before the first sale (PRAC-3), then fix the appliance blockers, or sell installs as a vendor service and say so.

---

## 1. Stop-ship

### PRAC-1 - The appliance boots in SMB login mode, so nobody can create the first admin or sign in
- **Sources:** `prac-install-1` (CONFIRMED critical), `prac-simplify-1` (CONFIRMED high)
- **Where:** `dashboard/deploy/compose.appliance.yaml` (dashboard env); `settings.py:807`; `setup_api.py:38-75`; `setup_routes.py:73-88`; `auth.py:158-165`; `docs/APPLIANCE_INSTALL.md:108-115`
- **What:** None of the compose file, the Dockerfile, `run.sh` or `secrets_boot` sets `DASH_AUTH_METHOD`, so it defaults to `smb` with an empty `DASH_SMB_HOST` and no `DASH_ADMIN_USERS`. The CR-57 first-admin window opens only in `local` mode.
- **Scenario:** This was probed with Settings built from the compose env. `setup/status` reports `users_exist=True`, so the wizard skips the admin step. `POST /setup/admin` returns 403 "only applies when DASH_AUTH_METHOD=local". `/setup` then redirects to `/login`, and every password goes to an SMB probe against `''`. A new customer is locked out at step 2. The appliance doc mentions the local-mode condition but never tells the customer to set it.
- **Recommendation:** Add `DASH_AUTH_METHOD: local` to the appliance env, or default to `local` when no NAS host is configured, keeping `smb` as the studio's explicit opt-in. Add a test that builds Settings from the exact compose env and creates the first admin.
- **Known:** CR-57 fixed local mode only. ZERO_TOUCH WP C chose "smb stays the default" for the studio fleet migration, and that choice was never undone for the appliance.

---

## 2. Before the first paying customer

### PRAC-2 - Customer installs have no vendor update channel, and INSTALL.md has the customer mint and bake their own release key
- **Sources:** `prac-install-4` (CONFIRMED), `prac-docs-1` (CONFIRMED), `prac-config-4` (CONFIRMED), `prac-support-2` (DOWNGRADED medium: the install_dashboard_app path does carry the values from site.toml and env), `prac-errors-1` (part)
- **Where:**
  - `docs/INSTALL.md` Step 6 (210-235)
  - `settings.py:910-919`, where the feed URL and pubkeys come from env only and default to empty
  - `compose.appliance.yaml`, which sets neither, and whose header claims the pubkey is "generated into data/secrets", which is impossible
  - `install_dashboard_app.py:1651-1665`, whose refusal text says `release_key.py pubkey`
  - `setup_engine._check_release_key` ("your release key ... docs/RELEASE.md")
  - `site.example.toml:244-262` (placeholder feed URL)
  - `admin_packages.html:258,474,476` and `package_store.py:228` (`tools\ship.cmd`)
  - `release_pubkey.py:53`
- **What:**
  - The vendor feed URL and the vendor public key are never defaulted, and no customer-facing doc states them.
  - INSTALL Step 6 walks the customer through `release_key.py new/pubkey/bake`.
  - Customer-visible copy says "your release key" and points at vendor-only scripts and docs.
  - ZERO_TOUCH WP E's item "retire customer-side key generation" was never done.
- **Scenario:** A customer who follows INSTALL pins their own key, so every vendor feed record fails verification and the shipped companion only trusts the vendor key anyway. A customer who sets nothing gets a 503 on every publish and has no feed. Either way the fleet stays on its install build, and security fixes need a vendor visit.
- **Recommendation:**
  - Bake the vendor feed URL and public key(s) into the image and the deploy as overridable defaults, and show them read-only in the wizard.
  - Move Step 6 to a vendor or self-build appendix in RELEASE.md, and fix the refusal text.
  - Replace "your release key", `docs/RELEASE.md` and `ship.cmd` in rendered copy with "the vendor's signing key".
  - Fix the compose comment.
- **Known:** ZERO_TOUCH_PLAN WP E (open); APPLIANCE_INSTALL lists it as NOT YET TRUE; COMMERCIAL_READINESS items 4/16 cover the mechanism only.

### PRAC-3 - There is no finished customer install path: the working one needs a vendor engineer, the repo, a Windows rig and the customer's NAS admin password
- **Sources:** `prac-install-10` (CONFIRMED), `prac-docs-2` (CONFIRMED), `prac-simplify-3` (DOWNGRADED medium), `prac-support-8` (medium)
- **Where:**
  - `docs/INSTALL.md` sections 1-3: `git clone`, `cd resolve-remote-sync` (the old name), site.toml with 12+ keys, ZFS, ssh-keyscan, exported secrets including `TRUENAS_PW`/`SYNO_PW`, about 12 server scripts and a release-key bake
  - `docs/APPLIANCE_INSTALL.md`, which is a DRAFT whose own header lists NOT YET TRUE items
  - `docs/README.md` "Getting started", which files a design, a plan and a draft beside INSTALL
  - `install_dashboard_app.py:9,1402-1407` and `site.example.toml [stack] mode`, which default to `bind`
  - `DOCKER.md:8-24`, which says "every live site uses" bind
  - `ZERO_DOWNTIME_DEPLOY.md:13-15,285`, which says bind is legacy
  - `dashboard_update.py:36-40`, which refuses dashboard OTA in bind mode
- **What:**
  - With the appliance unfinished, the base-rig path is the real install, and only a vendor engineer can run it.
  - Every later compose-level change is another `--recreate` with every secret supplied again.
  - The deploy's default mode (bind) is the one no live site runs and the one that cannot self-update, so every dashboard fix for a default-installed customer is an SSH session.
- **Scenario:** For ten customers the vendor holds ten NAS admin passwords and ten site.toml files on one rig. Every fix pass is ten SSH sessions.
- **Recommendation:**
  - Decide now. Either installs are a vendor-delivered service, with a vendor runbook, per-customer site.toml in a private ops repo, and the scoped API key or a DSM service account with the admin password dropped afterwards. Or finish the appliance (PRAC-1, 4-9) and make it the only customer path, run end to end by someone other than the author.
  - Either way: default new sites to image mode and mark bind as dev/legacy (the `:1` tag must exist first, see PRAC-9).
  - Fix the DOCKER.md and INSTALL prerequisites (no PyInstaller or Mac for customers), rename `resolve-remote-sync`, and move plans out of "Getting started".
  - Flag bind-mode customer sites on Health as unable to self-update.
- **Known:** COMMERCIAL_READINESS item 16 (open); ZERO_TOUCH section 1 states the target, but no decision is recorded; WPK-2..5 are open on the image path.

### PRAC-4 - The appliance dashboard is bound to the NAS loopback only, nothing publishes it on the tailnet, and the tailnet task still turns green
- **Sources:** `prac-install-2` (DOWNGRADED critical to high)
- **Where:** `compose.appliance.yaml` ports `127.0.0.1:8480`; no caller of `/localapi/v0/serve-config` exists anywhere; `setup_engine._check_tailnet`; `APPLIANCE_INSTALL.md` steps 3-4
- **What:**
  - The admin's laptop cannot open the wizard without SSH plus a tunnel.
  - Step 3 claims `http://<nas-ip>:8480` is reachable on the LAN and names a "Container Manager port-forward UI" that does not exist.
  - WP B (Serve) is unbuilt, so editors cannot reach the dashboard at all.
  - `_check_tailnet` returns ok as soon as the node is `Running`.
- **Scenario:** A studio owner without a terminal cannot open `/setup`. One who tunnels in finishes with a green tick and a dashboard no editor can reach.
- **Recommendation:**
  - Finish WP B: POST serve.json once the node is Running, handle "Serve is not enabled", write `dashboard_url`, and only then turn the task green.
  - Until then, require Serve or a tailnet `dashboard_url` for an ok.
  - Fix step 3 and add the manual `tailscale serve --bg http://dashboard:8480` fallback to step 4.
  - Do not sell the appliance as self-install until this lands.
- **Known:** APPLIANCE_INSTALL step 4 NOT YET TRUE; ZERO_TOUCH WP B (open). The misleading green tick is not recorded.

### PRAC-5 - The required "Sync engine" wizard step can never pass on the appliance, because SYNCTHING_GUI_URL is unset
- **Sources:** `prac-install-3` (CONFIRMED), `prac-errors-1` (part)
- **Where:** `compose.appliance.yaml` dashboard env; `settings.py:797`; `setup_engine.py:881-931`
- **What:** The bundled Syncthing listens at `http://tailscale:8384`, but the dashboard env never names it, and `syncthing_url` has no other source. The non-optional `syncthing` task stays at "SYNCTHING_GUI_URL not configured", Done never completes, `nas_syncthing_id` is never published, and the collector has no Syncthing.
- **Scenario:** Every appliance install stops at step 6 with a message naming an env var the customer was told never to edit.
- **Recommendation:** Set `SYNCTHING_GUI_URL=http://tailscale:8384` in the appliance env (the API key is already adopted from syncthing.env) and pin it in `test_compose_appliance.py`.
- **Known:** not recorded.

### PRAC-6 - Six wizard tasks can only be fixed by "set an env var and redeploy", which the appliance forbids
- **Sources:** `prac-install-8` (CONFIRMED), `prac-errors-1` (CONFIRMED)
- **Where:** `setup_engine.py` `_check_admin`, `_check_syncthing`, `_nas_client`, `_check_release_key`, `_run_software`, `_run_secrets` (`:599-605, 731, 753, 883, 899, 1211, 1538-1541`); `compose.appliance.yaml:35` ("NONE OF IT SHOULD BE EDITED")
- **What:**
  - The remedies for admin, sync engine, NAS connect, release key, software and secrets all need container env edits plus a recreate.
  - They name variables (`DASH_ADMIN_USERS`, `DASH_NAS_HOST`, `DASH_RELEASE_PUBKEYS`, ...), say "redeploy", and cite repo docs.
  - No customer doc says how to do any of it.
  - Two of these tasks are required: Admin and Sync engine.
- **Scenario:** The admin reads "set DASH_NAS_HOST and DASH_NAS_API_KEY, then redeploy", does not know where or how, and opens one support ticket per task.
- **Recommendation:**
  - Store these values in `site_settings` or `/data/secrets` behind forms on the tasks, and read them live.
  - Where a restart is unavoidable, exit 75 after saving (run.sh restarts on it).
  - Put variable names in an operator fold-out only.
  - Ship the vendor key and Syncthing URL as defaults (PRAC-2, PRAC-5).
- **Known:** not recorded. CR-57 fixed different setup bugs.

### PRAC-7 - The appliance's Syncthing cannot write its root-owned config bind mount and restart-loops
- **Sources:** `prac-install-6` (CONFIRMED by verifier; hunter PLAUSIBLE)
- **Where:** `compose.appliance.yaml` syncthing (`user: APP_UID`, `${CCSYNC_DATA}/syncthing-config:/var/syncthing/config`); secrets-init chowns only `/data`
- **What:** Docker creates the missing bind source as root:root 755. That is the very reason secrets-init exists, yet secrets-init never touches this directory. Syncthing started with `user:` cannot create its cert or config.xml. `install_dashboard_app.py:4739` pre-creates the folder on the base-rig path; the appliance path does not.
- **Scenario:** On the first `up` with a fresh CCSYNC_DATA, Syncthing restart-loops and lane C never starts. The fix is an SSH chown.
- **Recommendation:** Have secrets-init mount, mkdir and chown `syncthing-config`, and any other non-root bind source. Then run the appliance compose end to end on scratch DSM and SCALE boxes.
- **Known:** not recorded.

### PRAC-8 - The Synology appliance needs APP_UID/APP_GID set by hand, the doc says two variables, and the "wizard writes them back" claim is impossible
- **Sources:** `prac-install-7` (CONFIRMED)
- **Where:** `compose.appliance.yaml:71-79`; `APPLIANCE_INSTALL.md` step 2 ("Two variables, both required"); `templates/setup.html:62-68` (no uid field); `run.sh`, which warns only on a mismatch and is silent with the defaults
- **What:** The containers write the DSM-owned, ACL'd tree as non-existent uid 3000. The compose comment promises a wizard write-back that no code does and no container could do. The real fix is a dedicated DSM user and its ids.
- **Scenario:** A Synology customer follows the doc. The Storage check fails with a probe-write error, or SMB users see files they cannot open, and nothing names APP_UID.
- **Recommendation:** Document a "create a ccsync user, set APP_UID/APP_GID in the Environment tab" step with a screenshot, or have root secrets-init set permissions on the tree. Delete the write-back claim and name the cause in the Storage probe failure.
- **Known:** not recorded.

### PRAC-9 - The appliance pulls `ccsync:1`, which is v0.7.44 from 2026-09-11, about 29 versions behind; shipping never moves the tag
- **Sources:** `prac-install-5` (CONFIRMED), `prac-config-11` (medium)
- **Where:** `compose.appliance.yaml` (`ccsync:1`, `ccsync-sftp:1`); `.github/workflows/image.yml:162` (`:1` only on a `v*` tag); `ship.ps1` and `publish_latest.py` (no tagging); `CONFIG.md:187`, `DOCKER.md:482`, `install_dashboard_app.py:1415-1428,1621-1628` (still "`:1` does not exist yet, use `:edge`")
- **What:**
  - Releases go out as OTA bundles and sha images, so the floating tag is a month old.
  - With no feed (PRAC-2), an appliance cannot update itself.
  - The verifier could not confirm the tags were ever pushed to GHCR. If they were not, the appliance pull fails outright.
  - The deploy's NOTE steers customers to `:edge`.
- **Scenario:** The first paying customer installs a dashboard that predates the UI port and three fix waves. The vendor is then unknowingly supporting two code lines.
- **Recommendation:**
  - Push `vX.Y.Z` from ship.cmd and publish_latest, or pin the compose to a digest bumped per release.
  - Add a drift check of `:1` against the live version.
  - Delete the stale `:edge` note and fix CONFIG.md and DOCKER.md.
- **Known:** MODULAR_UPDATES notes the tag gap but not its effect on the appliance.

### PRAC-10 - The Synology footage-truncation setting is protected only by comments, and the template ships the unsafe value
- **Sources:** `prac-docs-4` (CONFIRMED high), `prac-install-11` (DOWNGRADED medium), `prac-config-3` (DOWNGRADED medium)
- **Severity:** high, before the first Synology customer. Verifiers split 1 high / 2 medium. The medium votes rest on: three docs warn about it, only lane-B proxies are hit (originals are safe), and no Synology customer is live yet. It is kept here because one missed line on a supported platform gives silent, fleet-wide, green-reporting corruption, and the guard is cheap.
- **Where:** `site.example.toml:154-155` (`sftp_chunk_size = "255Ki"`, `sftp_concurrency = 64`, uncommented); `install_dashboard_app.py:2295` (passes through); `server/backends/synology.py:43-46` (docstring only); companion `config.py:277` (255Ki default); INSTALL "minimum you must fill in" list omits it
- **What:** At 255Ki, DSM 7.2's OpenSSH 8.2 truncates lane-B downloads at 539,000,832 bytes while rclone reports success. Nothing derives the value from `nas_kind`, nothing refuses it, and neither check_health nor any alert flags it. The appliance's own ccsync-sftp sidecar (OpenSSH 9.6) is fine at 255Ki, so the rule depends on which sshd serves the lanes, not just on `nas_kind`.
- **Scenario:** A DSM customer fills in the listed minimum keys and deploys. Every proxy over 514 MiB arrives short while lane B shows green.
- **Recommendation:**
  - Derive transport defaults for Synology-on-DSM-sshd (64Ki/16/none) in the deploy and in `site_store._shape`.
  - Refuse anything above 64Ki there, both at deploy time and in Settings.
  - Add a check_health line and an alert kind.
  - Comment the lines out of the template and add the key to the minimum list.
- **Known:** measured in synology-spikes spike 6; documented in SERVER-SYNOLOGY.md. The enforcement gap is not recorded.

### PRAC-11 - The wizard says DONE but never connects Resolve to the project server or turns on scripting, and the tray's advice for that state cannot fix it
- **Sources:** `prac-editor-onboard-6` (CONFIRMED), `prac-editor-onboard-7` (medium, PLAUSIBLE)
- **Where:**
  - `onboarding/onboard.py:1781-1838` and `steps.finish_page_copy` (no Resolve steps)
  - `windows_bootstrap.ps1:2503-2508` (log-box lines only; External scripting is not mentioned)
  - `START_HERE.md:250-262` (user `postgres`)
  - `resolve_bridge.NO_SCRIPTING_MESSAGE` and `tray.py:1772-1860` ("quit and reopen Resolve", STOP WARNING ME)
  - `resolve_prefs.py`, which writes no scripting pref
- **What:**
  - The editor must, by hand: add the PostgreSQL project library, set External scripting = Local (Resolve's default is None, which kills the watcher, fixer, popup, Send to Resolve and proxy attach), and enable Prefer Proxies.
  - None of this is on either finish page.
  - Neither installer detects Resolve free or scripting = None. The companion then sends the editor round a restart loop and offers to silence a permanent setup error.
- **Scenario:** The editor closes a DONE wizard, sees only the local database in Resolve, phones the admin for the Postgres password, then gets RESOLVE SCRIPTING IS DOWN, restarts three times and clicks STOP WARNING ME. Their out-of-tree media never uploads.
- **Recommendation:**
  - Add a "connect Resolve" checklist to both finish pages, with the host taken from the site manifest.
  - Write the External scripting pref while Resolve is closed (as the Mac Mapped Mount already is).
  - Detect Resolve and its edition at install.
  - When a machine has never had a scripting connection, name the preference and the Studio requirement in place of the restart advice.
  - Optionally add a manifest block for the library and a non-superuser Postgres role.
  - Point to `/help`, not `docs/EDITOR_SETUP.md`.
- **Known:** not recorded.

### PRAC-12 - The 3-removal brake freezes ordinary unticks and Suspend fleet-wide, and only a container env var undoes it
- **Sources:** `prac-admin-daily-2` (CONFIRMED)
- **Where:** `collector.py:1529-1558, 1633-1662, 1693-1696`; `settings.py:625,939` (`DASH_ENFORCE_MAX_REMOVALS=3`); `ui.py:3440-3447` (Suspend promises unsharing "within a minute"); `fleet_grid.html:54-64`; `notices.py:344-346`
- **What:**
  - Removals are counted as (folder, device) pairs. Over 3, no removal anywhere is applied, every cycle.
  - Suspend works only through this cycle.
  - Fixes on offer: a container setting, or "untick fewer", which does not help once the diff is already over the limit.
- **Scenario:** An editor leaves and the admin presses Suspend. 6 projects x 2 computers = 12 removals. The departing editor keeps receiving every project, every other untick in the fleet freezes, and undoing it needs SSH or the vendor.
- **Recommendation:**
  - Pre-authorise removals that trace to an audited admin action in the cycle (untick, suspend, forget, delete, archive), and keep the brake for unexplained removals.
  - Add an admin "Apply these N removals" key on the refusal banner.
  - Make the limit a site setting that scales with fleet size.
- **Known:** DASH-3 made the refusal visible. Ordinary actions and Suspend tripping it are not recorded.

### PRAC-13 - The customer "product repo" cannot be produced, and its withheld list misses most internal documents
- **Sources:** `prac-docs-8` (CONFIRMED), `prac-simplify-11` (medium)
- **Where:** `tools/make_product_repo.ps1:141-185, 331, 347-351, 382-386`; `docs/PRODUCT_REPO.md`; `docs/SERVER.md:322-343`; named editors in TRANSFER_SPEED, MULTI_MACHINE_PLAN, CARDS_TWO_PROJECTS, SERVER_TRIAGE_AGENT, README
- **What:**
  - The tenant-marker gate refuses today: Creators_Club appears 909 times in 185 files, plus "ruskin" and "leso" under docs/ and the vendor IPs.
  - The denylist dates from 2026-08-17, and its `bug-hunt-*.md` glob does not cross `/`. So the sweep dirs, ledgers, plans, UI_PORT_LEDGER and this review's own directory would ship once the markers were cleaned.
  - The brand ruling (CR-25: the CC mark is the product brand) conflicts with "Creators Club" being a marker.
  - Scan and prune use different matchers.
  - The refusal text still mentions pystray.
- **Scenario:** INSTALL tells the customer to clone "your checkout of this repo". The vendor either hands over the engineering archive (defect maps, another customer's identity, named editors' machines) or has nothing to hand over.
- **Recommendation:** Decide whether any customer gets source in v1. If none does, archive the tool and remove the clone step (see PRAC-3). If some do, settle the brand question, switch to an allow-list built from the customer docs set (the published_docs pattern), scrub SERVER.md and the named editors, use one matcher, and run the export once from a tag before the first sale.
- **Known:** COMMERCIAL_READINESS item 10 ("a recipe, not run", open).

---

## 3. Soon after launch (mediums)

### 3.1 Server install and setup

- **PRAC-14 - TrueNAS "Install via YAML" has nowhere to set CCSYNC_TREE/CCSYNC_DATA** (`prac-install-9`, PLAUSIBLE). Where: `APPLIANCE_INSTALL.md` step 2; eight `${CCSYNC_TREE:?}` sites. SCALE's custom-app screen is a single text box with no .env, so the customer is left hand-editing eight paths. Fix: verify on SCALE 25.x; ship a TrueNAS variant with two literal paths at the top, or a catalog app (WP I).
- **PRAC-15 - Three tree folders must be made by hand before the first `up`, and the compose, doc and troubleshooting text disagree on who makes them** (`prac-install-12`). Where: `APPLIANCE_INSTALL.md` step 2 and Troubleshooting; compose header; `setup_engine._run_storage`. If they are missing, Docker makes them root-owned and the only symptom is a probe-write failure. Fix: root secrets-init creates and chowns them; name the cause in the probe detail.
- **PRAC-16 - The wizard never asks for the address editors use, and Done goes green without one** (`prac-install-13`). Where: `setup.html:62-68`; `_STUDIO_REQUIRED_KEYS`, `_check_done`. Editors' installers then get an empty `dashboard_url`/`sftp_host`. Fix: make it a required field (auto-filled from Serve on the appliance) and block Done while it is empty.
- **PRAC-17 - A lone tailscaled restart orphans Syncthing and SFTP until someone runs `docker compose up`** (`prac-install-15`). Where: compose `depends_on` (spike S5). Nothing alerts on it and the fix needs a terminal. Fix: `depends_on {condition: service_healthy, restart: true}` with a tailscale healthcheck, or a "Syncthing unreachable while tailscale is Running" notice.
- **PRAC-18 - The appliance's Syncthing GUI listens on 0.0.0.0 inside the tailnet node, with no GUI password** (`prac-install-16`, PLAUSIBLE; handed to the security lens). Any tailnet peer may get full Syncthing admin. Fix: secrets-init sets a GUI user and password; confirm with a probe from a peer.
- **PRAC-19 - INSTALL.md never installs the server scripts' Python dependencies** (`prac-docs-3`). Where: INSTALL section 1; `server/common.py:32` (top-level urllib3), paramiko and requests imported lazily; `server/requirements.lock` is referenced by no doc. Step 3 dies with ModuleNotFoundError on a clean machine. Fix: add a venv + `pip install --require-hashes -r server/requirements.lock` step, or a one-line hint in common.py.
- **PRAC-20 - "Tailscale Serve is the only supported TLS path", but the TrueNAS runbook never sets it up** (`prac-docs-11`). Where: `INSTALL.md:41-48`; SERVER.md (Serve only at :265); `SERVER-SYNOLOGY.md:213-241`. Fix: add a Serve section to SERVER.md (command, `DASH_COOKIE_SECURE=1`, `--recreate`, consequences for dashboard_url and loopback), or state that tailnet-only http is the supported TrueNAS default. Known: COMMERCIAL_READINESS item 6 operator step.
- **PRAC-21 - Client folder links need SSH, `sudo tailscale funnel` and a tailnet policy edit before a client can open one** (`prac-admin-daily-10`). Where: `CLIENT_FOLDERS.md:96-220` (not shipped); `routes_client_folders.py:116-140`. Any editor can mint a link that does not open, and the dashboard cannot tell whether the public door exists. Fix: a setup task that uses `tailscale_local.py` to check and enable Funnel (or prints the console grant link); show "reachable from the internet / tailnet only" on the folders screen; refuse to mint a link that cannot open.

### 3.2 Configuration and deploy

- **PRAC-22 - Editing site.toml and redeploying silently changes nothing after the first boot** (`prac-config-1`, DOWNGRADED from high). Where: `site_store.py:609-706, 850-875`; `install_dashboard_app.py:2189-2300, 2575-2585`; `site.example.toml:94-96, 392-395`. The first boot seeds every `DASH_SITE_*` (features as "0", sftp keys) into the DB, and the DB wins from then on. This is deliberate and documented in CONFIG section 1.1, but the example still says "change them here and redeploy", and nothing reports the drift. Probed: youtube_download, sftp_chunk_size and org_name do not change. Fix: re-seed rows still marked `seed:env` that no human has edited; show a deploy-vs-DB drift banner and print it after `up`; rewrite the example comments.
- **PRAC-23 - Settings suggests "Example: 64M" for SFTP chunk size, accepts it, and pushes it to every editor** (`prac-config-2`, DOWNGRADED). Where: `admin_settings.html:45-48`; `site_store.py:72` (plain string); companion `site.py:78-85`, `rclone_lane.py:600-612`. The concurrency example (8 against a default of 64) and the remote example (`ccnas`) are also wrong. It is reversible by clearing the field. Fix: validate as an rclone size of 32Ki-255Ki (at most 64Ki on DSM-sshd), use the real defaults as examples, and put transport keys behind an advanced fold.
- **PRAC-24 - SSO (OIDC) is sold as an install choice, but the shipped deploy cannot set it, nor most documented tunables** (`prac-config-5`, DOWNGRADED). Where: `INSTALL.md:357,366-381`; `CONFIG.md` sections 2.2-2.6; `install_dashboard_app.py` env dict `:2440-2680`; `auth.py:146-180`. Hand edits survive routine deploys and OTA but are lost on `--recreate` or `--mode`. The same applies to `DASH_ENFORCE_MAX_REMOVALS`, `DASH_JOBS_*`, `DASH_INTERVAL_*` and session lifetimes. Fix: `[auth]` and `[tuning]` tables in site.toml that the deploy projects (secrets stay in env), or carry existing `DASH_*` values through; until then mark OIDC as not available via the shipped deploy.
- **PRAC-25 - The documented secret-rotation recipe fails, because the deploy never forwards DASH_SESSION_SECRET_PREVIOUS** (`prac-config-6`, DOWNGRADED). Where: `SECRETS.md:20,106-135`; `settings.py:810-813`; `install_dashboard_app.py` (absent from the env dict, the Synology .env and `SECRET_ENV_VARS`). Following the doc gives the fleet-wide 401 that DASH-2 was built to prevent, during a security incident. Fix: forward and mask the variable; add a test pinning every variable SECRETS.md tells an operator to set. Known: DASH-2 (reader side only).
- **PRAC-26 - Settings that live only in the deploying shell revert silently on a recreate (admins, shared token, proxies)** (`prac-config-7`, DOWNGRADED). Where: `install_dashboard_app.py:5338, 2463-2471`; `auth.py:935-955`. `DASH_ADMIN_USERS` falls back to the NAS admin and `DASH_SHARED_REPORT_TOKEN_ENABLED` to "1". This happens only on `--recreate`/`--mode`, not on a plain deploy. Fix: move them into site.toml or the DB, or have the deploy read the running values and refuse to change them without a flag.
- **PRAC-27 - A redeploy with different secret values replaces the running ones unchecked, giving a fleet-wide 401** (`prac-config-8`, DOWNGRADED). Where: `install_dashboard_app.py:3116-3130, 2467, 6088-6104`; `INSTALL.md:280-281`; `load_secrets.ps1` (one store, not keyed by site). Exporting customer B's vault while `--site` points at A ends with a green transcript. Fix: read the running values; refuse a change without `--rotate-secret NAME`; fall back to the running values when the env is empty.
- **PRAC-28 - Keys documented and exampled as site.toml settings are never read by the deploy** (`prac-config-9`). Where: `site.example.toml:336-358`; `install_dashboard_app.py:5285-5297`; CONFIG `[telemetry]`, `[indexer]`. `ai_cli_auto_update`, the `[telemetry]` legal opt-outs and `[indexer] model_tier` all do nothing from site.toml. A DPO's telemetry opt-out set there is silently ignored. Fix: project them in `site_env()`, or mark them Settings-only; warn at deploy time on any unconsumed key.
- **PRAC-29 - `[tree] projects_dir` is offered as a choice; the server scripts obey it and the product refuses it** (`prac-config-10`, `prac-simplify-13` part). Where: `site.example.toml:85-89`; `server/common.py:199-200`; `settings.py:78-102`. Setting `projects_dir="Jobs"` makes the fleet sync nothing. Fix: refuse any other value in common.py with the SYS-20 sentence, and remove the key from the example and CONFIG. Known: SYS-20 (dashboard side only).
- **PRAC-30 - Routine settings the admin is told to change exist only as container env vars or restarts** (`prac-admin-daily-9`). Where: `admin_packages.html:325`; `fleet_grid.html:58-81`; `admin_report_tokens.html:18`; `project_setup_panel.html:45`; `admin_users.html:293-295`; `alerts.py:3653`; `notices.py:799,925`; `recovery.py:900-920`. Affected: shared-token switch, removal limit, previous-secret retirement, feed URL, "restart the container". Each is a vendor ticket per customer. Fix: move the routine ones to `site_settings` with controls; add a "Restart the dashboard" key on Health; bake in the feed URL; reword the rest as "contact <support_contact>" with the exact value to quote.
- **PRAC-31 - The companion has 147 config keys; 6 are in the settings window and 2 are settable remotely, so support means remote shells** (`prac-config-13`). Where: companion `config.py` (DEFAULTS, MODE_PROFILES `:904-915`); `settings_window.py`; `db.py:13233` (MACHINE_SETTING_KEYS). Examples that need a hand edit: base-rig `broll_ingest_staging_dir`, `remote_down`, `jobs_*` paths, `cards_agent`, `loopback_extra_origins`, `library_db_*`, sometimes with an rclone stanza and `rclone obscure`. Fix: base defaults in `MODE_PROFILES['base']`; extend MACHINE_SETTING_KEYS and the window; let the dashboard push the rclone stanza.

### 3.3 Editor onboarding

- **PRAC-32 - The installer can only be downloaded from a place the installer is meant to get you into** (`prac-editor-onboard-1`, DOWNGRADED). Where: `ui.py:3922-3990` (login-gated, tailnet-only); `START_HERE.md:10-16` vs `85-92`; `onboard.py:782-822`. START_HERE says click INSTALLER before section 1 "Join Tailscale". The workaround (join Tailscale first) is in the doc but in the wrong order. Fix: reorder START_HERE and INSTALL Step 7; tell the admin to send the Tailscale invite with the login; optionally an expiring per-editor download link.
- **PRAC-33 - The wizard makes the editor type the dashboard address it was downloaded from** (`prac-editor-onboard-2`). Where: `steps.py:156` (empty default); `onboard.py:612-627, 729-740`. The example given is `http://<your-dashboard>:8480`, not the `https://<name>.ts.net` Serve form. Fix: name the download with the site host and prefill from the filename (the signature covers bytes, not the name); use the site's real URL form in the example.
- **PRAC-34 - There is no "invite an editor" flow: about four or five separate hand-offs per new editor** (`prac-editor-onboard-3`, DOWNGRADED). Where: `EDITOR_SETUP.md:15-35`; `START_HERE.md:250-262`; no invite route. The hand-offs are the Tailscale invite, URL, credentials and Postgres host/password, and on one branch the device ID back. (The verifier corrected the count: the report token comes from /verify and the SSH key uploads itself.) Fix: Settings > Users > INVITE EDITOR producing one message (download link, URL, username with a one-time password, Tailscale invite). Known: ZERO_TOUCH and SYNOLOGY_PORT plans (unbuilt).
- **PRAC-35 - Two fleet credentials, and the weak one is the default: /verify hands every editor the shared fleet secret** (`prac-editor-onboard-4`, `prac-simplify-2` DOWNGRADED). Where: `api.py:2405-2460, 160-200`; `settings.py:135,805-806`; `steps.py:993-1068`; `onboard.py:1262-1280`. Per-person Suspend/Disable already limits a stolen laptop (shared token plus identity required), but a retired shared token makes every new machine need a minted, pasted `cce1` key or the install ends NOT READY. There are two credential branches in every fleet route. Fix: on a successful /verify (same throttle and audit), mint a bound, revocable per-machine `cce1` token; default the shared token off on new sites; remove the paste field. Known: CR-18 / CR-55 (design premise challenged).
- **PRAC-36 - Approval requests are invisible: device-ID busywork, no admin nudge, and the tray says "server rejected this computer's login"** (`prac-admin-daily-5` DOWNGRADED, `prac-editor-onboard-5`, `prac-errors-3` DOWNGRADED).
  - Where: `steps.py:2423-2456`; `windows_bootstrap.ps1:2487-2493`; `api.py:4313-4323, 4462-4478, 4940`; `admin_users.html:156-204, 301`; `notices.py:527-554`; `tray.py:596-599`.
  - An SSH-key request shows only on Users. The device request becomes a warn notice after 24 h, which is never emailed and not counted in the HUD.
  - The companion already reports the device ID, yet the finish page asks the editor to message a 56-character ID.
  - On a site with Syncthing configured but no NAS credential, the devices window is hidden while the notice points at it.
  - A tick before key approval reads as a broken install.
  - Fix:
    - Finish page: "your admin has been asked to approve this computer".
    - Add a `pending_ssh_key_approval` notice and alert kinds for both approvals, with one APPROVE that covers key and device.
    - Draw the devices window whenever `syncthing_url` is set.
    - Give the tray a "waiting for approval" state.
    - Consider auto-approving submissions from an editor's own `cce1` credential.
- **PRAC-37 - Onboarding a computer to a second dashboard keeps the first site's NAS path and fleet token, then says DONE** (`prac-editor-onboard-8`, probed). Where: `steps.py:3640-3646, 3612-3613, 1034-1044, 2074-2095`; `windows_bootstrap.ps1:2188-2194`. `remote_root` and `report_token` carry over, so the token step is skipped and every report 401s. Fix: detect a host change; warn; force `remote_root` from the new manifest; drop the old tokens; archive the old config; document one site per computer; mention signing Tailscale in to the right network in the unknown-host message. Known: CR-265 (drive letter and tree name only).
- **PRAC-38 - The Mac first-run advice "right-click, Open" no longer works on macOS 15+** (`prac-editor-onboard-9`). Where: `START_HERE.md:72-75`; `build_onboard_macos.sh:485-486`; `installer.html` (Windows SmartScreen note only). Fix: document System Settings > Privacy & Security > Open Anyway in START_HERE and on the /installer macOS card. Known: COMMERCIAL_READINESS item 4 (notarisation).
- **PRAC-39 - Mac: the install never asks for the Full Disk Access the sync tools need** (`prac-editor-onboard-10`, PLAUSIBLE). Where: `macos-first-run-2026-08-05.md:165,215-219`; bootstrap, wizard and docs silent; `app.py:3029-3062` (only after an upgrade). The first sign is a silent stall. Fix: the wizard tests access per binary and lists the apps, with an OPEN SETTINGS button (`Privacy_AllFiles`); re-check on every start. Known: KNOWN_BUGS macOS code-signing (per-upgrade loss only).
- **PRAC-40 - Every editor personally accepts the customer's B2B contract (indemnity, Taiwan courts, repo paths)** (`prac-editor-onboard-11`). Where: `onboarding/assets/EULA.md:16-19, 101-105, 121-126, 189-193`; `onboard.py:459-535`; `setup_engine.py:13,58-98`. A freelancer or the customer's legal team may refuse. Fix (for counsel): a short end-user notice that names `org_name` as controller, with the full EULA kept for the admin acceptance; link TELEMETRY and PRIVACY as served URLs. Known: CR-5 (drafting only).

### 3.4 An editor's working day

- **PRAC-41 - Send to Resolve is refused for anyone browsing at a different address, and the page blames the browser** (`prac-editor-daily-1` DOWNGRADED, `prac-errors-6`, `prac-config-12`).
  - Where: `loopback_guard.py:117-119, 205-249`; `broll_server.py:2066-2201`; `broll/web/static/app.js:1935-1949, 2076-2083`; `ingest.js:107-110`; CONFIG has no `loopback_extra_origins` row.
  - The allow-list is the union of the companion's own and the site's `dashboard_url`, refreshed every 30 s. (The verifier corrected the claim that moving to Serve breaks everyone.) A LAN-IP or MagicDNS bookmark that matches neither is refused.
  - The 403 carries no CORS headers, so the page lands in its "it's the browser" branch, and `/status` (sent with no Origin) answers ok and seems to confirm it.
  - The real cause is only in companion.log. The `loopback_origin_mismatch` alert is unbuilt.
  - Fix:
    - Publish a learned, admin-prunable `dashboard_origins` list in /api/v1/site, or redirect non-canonical Hosts.
    - Answer a refused Origin with a CORS-readable 403 naming the origin, and put the last refused origin in `/status` and on a tray line.
    - Build the alert.
  - Known: KNOWN_BUGS loopback ops note; 2026-09-03 sweep CMEDIA-5.
- **PRAC-42 - A b-roll clip that is not on disk yet is inserted only if the tab stays open, and lands wherever Resolve is by then** (`prac-editor-daily-2`). Where: `app.js:1869-2020`; `broll_server.py:1100-1112`; `broll_fetch.py:138-164, 519-529`; `HOW_IT_WORKS` 9.2. `FetchJob.cancel` is unreachable and every Send button is disabled for the whole download. Fix: the companion owns the pending insert (project, timeline and frame captured at the click; if they are no longer current, put the clip in the Archive bin and show a balloon); show pending sends with CANCEL; allow a queue; correct the doc. Known: 2026-09-03 sweep note (open).
- **PRAC-43 - "Pause syncing" is forgotten at every restart and does not pause folder sync** (`prac-editor-daily-3`). Where: `app.py:1723, 10075-10126`. An update or relaunch silently un-pauses, so a hotspot upload resumes. Fix: persist the pause with an optional end time; pause Syncthing folders too (or offer "pause everything"); never let an update clear it.
- **PRAC-44 - Pushed and unattended updates restart the companion in the middle of uploads, fetches and downloads** (`prac-editor-daily-4`). Where: `app.py:6948-7012, 8382-8470`. The only stand-down conditions are an open window or a consolidate, and an interrupted upload restarts from zero. Fix: on unattended paths, also stand down while `live_busy()`, a ytdl job, a fetch or a held job is active, capped at about 6 h; show "waiting for an upload" on the Packages row.
- **PRAC-45 - There is no "sync this project first"; the only deadline lever is unticking everything else** (`prac-editor-daily-5`). Where: `home_queue.html`; `sequencer.py:151`; EDITOR_SETUP section 3 (misdescribes the rotation). Fix: "Sync this first" on queue rows, optionally "only this one until done"; reword the hint and the doc to describe turns.
- **PRAC-46 - A misfiled upload can only be fixed by the admin, and the editor's natural self-fix duplicates it on the server** (`prac-editor-daily-6`). Where: `api.py:3035-3045`; EDITOR_SETUP section 7; FILE_MOVES section 1. Fix: an editor-requested move with one-click admin approval (auto-approved when only their own machines hold the files); the companion detects the same name and size reappearing at a new path and offers `file_moves` in place of re-uploading. Known: CR-87 (admin path only).
- **PRAC-47 - Every button in the Settings window closes the window** (`prac-editor-daily-7`). Where: `settings_window.py:20-31, 2010-2016`. One change becomes open, click, reopen, scroll, RESTART NOW. Fix: close-then-spawn only for buttons that open a dialog; run the rest on a worker with the window left open.

### 3.5 The admin's week and vendor support

- **PRAC-48 - Home "problems" counts only notices, and the HUD, home and Health show three different totals** (`prac-admin-daily-1`, DOWNGRADED). Where: `ui_home.py:260-280`; `fleet.html:67-73`; `topbar.html:22-25, 67-72`; `alerts.py:2197`; `admin_health.html:20`. Alert-only kinds (`machine_silent`, lane errors) never reach problems.log, which can say "All clear". `_check_notices` double-counts error notices. The alerts chip folds away below 900 px. Fix: one number everywhere (Health's open total), the top five rows plus a link on home, no double count.
- **PRAC-49 - No support contact anywhere in the product** (`prac-admin-daily-3` part, `prac-errors-2`, `prac-support-1`, all DOWNGRADED). Where: 12+ "send us" / "send to support" strings (`alerts.py`, `invariants.py:1200,1400`, `notices.py:1060,1456,1490,1585`); "ask the vendor" (`alerts.py:3316`, `release_feed.py:1290`, `admin_packages.html:162,375`); `ui_copy.DIAGNOSTICS` "for your admin"; no `support_contact` key; the only contact is EULA section 14. Fix: add a vendor-defaulted `support_contact` to the site manifest and render it on /help, the Health header, every "support" or "vendor" line (as a mailto prefilled with the notice), companion HELP and the wizard Done step; write `docs/SUPPORT.md` (the admin's checklist plus the vendor's triage runbook).
- **PRAC-50 - The dashboard log is not retained or downloadable, and there is no support bundle** (`prac-admin-daily-3` part, `prac-support-4`, DOWNGRADED). Where: `crash_report.py:28-30, 292-310` (`DASH_LOG_DIR` is opt-in and set nowhere); `ui.py:4555` (the crash zip shows only when there is a crash); `triage.py:678` (the evidence bundle cannot be downloaded). Many faults already surface as alerts (feed errors land in `last_error` and alerts), so this is mostly about support ergonomics. Fix: `DASH_LOG_DIR=/data/logs` in every compose shape; DOWNLOAD SUPPORT BUNDLE on Health (versions, sha, schema, open findings, log tail, crashes, newest diagnostics per computer, masked settings, scrubbed triage evidence). Known: bug-hunt-2026-08-21 recommended this; not done.
- **PRAC-51 - Fix text points admins at docs customers never get; there is no admin guide or other day-2 customer docs** (`prac-admin-daily-4` DOWNGRADED, `prac-docs-12`). Where: `published_docs.py:42-55` (ships only HOW_IT_WORKS, EDITOR_SETUP and legal/); references to DOCKER, RELEASE, SECRETS, BACKUP_RESTORE, RESOLVE_EDIT_SAFETY, INSTALL and APPLIANCE_INSTALL in `alerts.py`, `notices.py`, `protection.py`, `recovery.py` and `setup_engine.py`; `admin_packages.html:474` mentions `ship.cmd` even on feed sites. Also missing: a root README, customer release notes or changelog, a requirements and sizing sheet, and a vendor runbook for N customers (beta channel or soak, per-customer onboarding, feature enablement). Fix: write and publish `ADMIN_GUIDE.md` and the customer docs; replace `docs/` and `tools\` paths in user-visible strings; add a scan test; keep a per-component CHANGELOG that feeds the feed notes. Known: 2026-09-03 DUI.md:85 (templates only).
- **PRAC-52 - Originals that will never upload (same name, different size on the NAS) are a grey chip only** (`prac-admin-daily-6`, DOWNGRADED). Where: `fleet_grid.html:132`; `ui.py:451-454`; `health.py:1387-1390`; no alert kind; the dashboard stores only counts. The editor's tray does name the files and offers to open the folder. Fix: a "footage only on one computer" alert kind with sample names (error after 24 h); optionally an admin action "upload beside it as `<name> (from <machine>)`".
- **PRAC-53 - Home cannot answer "is any footage only on one computer"** (`prac-admin-daily-7`). Where: `ui_home.py:124-160, 217-232`; `ui.py:570-620`. "Moving" sums proxies coming down with originals not yet uploaded. Fix: show "not on the server yet: X GB on N computers, oldest Y h" (lane A owed plus uncertain rows shown as "cannot tell"), with the per-computer list one click away.
- **PRAC-54 - Feed policy "current" never makes a build current (no auto-canary), nothing alerts, and every release is a manual per-platform chore** (`prac-admin-daily-8`). Where: `release_feed.py:1026-1066`; `package_store.py:98-110, 357-360`; `alerts.py` `_check_soak`, `_check_rollout_stalled`; `admin_packages.html:330-336, 419-421`. A staged build waits for a canary for good, with only a log WARNING, and there is no "update all". Fix: auto-pick an audited canary per platform and promote after the soak; on manual policy raise a "staged, waiting for a trial" notice with an inline push key; add "update every computer that is behind"; rename the policy. Known: REL-1 (soak is an owner decision).
- **PRAC-55 - Every customer configured with the vendor key gets a permanent red "release key not backed up" finding** (`prac-support-3`). Where: `protection.py:483-505, 702-712`. They hold no private key, so the finding trains them to dismiss red. Fix: `not_checked` ("the vendor holds this key") when the configured key is the vendor default or the site has never published itself.
- **PRAC-56 - The companion diagnostics bundle names crashes but omits the message and traceback; the log tail is 40 lines** (`prac-support-5`). Where: `app.py:9700-9710, 9734`; `crash_report.py:243-264`. Fix: include the newest crash's message and about 30 traceback lines through `_redact_diagnostics`; raise the tail to about 200 lines; add OPEN CRASH FOLDER.
- **PRAC-57 - The vendor has no view across customers and learns of problems only by email** (`prac-support-6`). Where: `release_feed.py` (no identity on the fetch); `alerts.py:272-300` (sink none, heartbeat off); `EULA.md:136-138`. A recalled build means emailing every customer to find who has it. Fix: an opt-in daily "share health with the vendor" report (versions, schema, feed status, finding kinds), documented in TELEMETRY.md; meanwhile add the vendor as an alert or weekly recipient during onboarding.
- **PRAC-58 - There is no documented way to ship a fix to one customer only** (`prac-support-7`). Where: `publish_latest.py:46`; `RELEASE_FEED.md:61-62`; `RELEASE_PATHWAYS.md:27`; `release_feed.py:648-673`. Without a current pointer, highest-version-wins would push a staged hotfix to every auto-policy site. Fix: a "hotfix for one site" recipe; `publish_feed` refuses a staged publish when no current pointer exists; per-site channels later.
- **PRAC-59 - Failed editor installs are invisible to the admin and the vendor** (`prac-support-9`). Where: `onboard.py:1302-1336`; `steps.py:929-1382`. Fix: after /verify, POST the outcome, step, error and log tail to `/api/v1/diagnostics` with trigger `install`; show it under "what these computers said".
- **PRAC-60 - A release cannot be marked urgent, and the default feed policy is manual** (`prac-support-10`). Where: `publish_feed.py:1037-1134`; `settings.py:918`; `alerts.py:2548-2571`. A data-safety fix looks like a cosmetic one and waits for weeks. Fix: a signed severity field (routine/recommended/urgent) that drives a banner and an undigested alert; consider `stage` as the default policy for new sites.
- **PRAC-61 - Two companion release pathways, and the studio's usual one bypasses the feed every customer is on** (`prac-simplify-10`). Where: `RELEASE_PATHWAYS.md`; `ship.cmd`/`ship.ps1`; `build_editor_package.ps1 -Publish`. The studio's soak then no longer covers the bytes customers receive. Fix: once the first customer exists, the studio takes releases from the feed; pathway A stays only as a dev build and a one-machine upgrade. Known: COMMERCIAL_READINESS item 4.
- **PRAC-62 - KNOWN_BUGS.md (31,993 lines, 1,151 entries) cannot answer "what is open?"** (`prac-simplify-12`). Status lives in free-text titles that go stale (for example, CR-18 is still titled "unshipped"), and line endings are mixed. Fix: open items only, one line each, with closed entries moved into dated archive files; normalise the line endings.

### 3.6 Error messages

- **PRAC-63 - The tray's sign-in dialog shows raw urllib/WinError text** (`prac-errors-4`). Where: `identity.py:262-263, 321-323, 490`; `tray.py:1253-1256`; `api.py:2430` (`verify busy: {exc}`). Fix: reuse `onboarding/steps._classify_reach_error` ("Can't reach the dashboard at <url>. Check Tailscale is connected"); point a blank address at the Settings field; make the 503 detail generic.
- **PRAC-64 - Developer config-validation text reaches editors' tray lines, Settings and web toasts** (`prac-errors-5`). Where: `config.py:2071-2216`; `app.py:6423-6427`; `tray.py:716-763, 1439-1440`; `broll_fetch.py:207-212, 248`. Examples: "remote_root is not absolute", TOML parse errors, "edit ~/.ccsync/config.toml". Fix: two strings per problem, an editor sentence plus action, and the technical one sent to diagnostics and the fleet page; never point an editor at config.toml. Known: APP-5 (behaviour intentional; wording not).
- **PRAC-65 - The lane-error classifier tells editors the wrong thing for common local failures** (`prac-errors-7`, probed). Where: `tray.py:534-606`. A local "permission denied" maps to "server rejected this computer's login"; file-in-use, SSH_FX_FAILURE and a missing rclone config map to "Something went wrong"; "unexpected EOF" always blames Tailscale. Fix: classify local paths separately; add branches for in use, server full, missing config and macOS privacy; keep "login rejected" for auth errors only; pin the probe strings in a test.
- **PRAC-66 - B-roll fetch and upload failures put raw rclone stderr in the web toast** (`prac-errors-8`). Where: `broll_fetch.py:338,381,383`; `broll_upload.py:550,583`; `broll_server.py:1806,1918`. Fix: route them through the shared classifier with the clip name and an action; keep raw text for the log; "sync tools missing: re-run the installer".
- **PRAC-67 - A failed grade-swap restore leaves P: unmapped and tells the editor to "remap it by hand"** (`prac-errors-9`). Where: `drive_swap.py:571-582`; `tray.py:2214`. Fix: point at Settings > REPAIR P: NOW, then COPY DIAGNOSTICS; keep `subst` and `local_root` in the log only.

### 3.7 Customer-facing docs

- **PRAC-68 - EDITOR_SETUP.md (served in every customer's /help) and START_HERE.md describe the pre-wizard install and contradict the product** (`prac-docs-5`, `prac-simplify-9`, `prac-editor-onboard-12` low). Where: `EDITOR_SETUP.md` (CLI-only with `-DashboardToken` on argv, Mac `.sh`, `accept_device.py`, "TrueNAS username", "Do not map T:", tray "Scan whole project"/"Consolidate", "deletes DO propagate", cites COMMERCIAL_READINESS); `START_HERE.md:85-262, 300-306` (about 200 lines of package route, an obsolete upgrade path); bootstraps point at `docs/EDITOR_SETUP.md`. Fix: rewrite wizard-first (Installer, sign in, approval, tick); move the CLI path to an admin appendix with `CCSYNC_DASHBOARD_TOKEN`; "CC Sync username"; fix menu locations and delete semantics; point bootstrap output at /help; add a stale-term scan test.
- **PRAC-69 - HOW_IT_WORKS.md (/help) states several things the code does not do and names controls that moved** (`prac-docs-6`, `prac-editor-daily-9`). Where: `HOW_IT_WORKS.md:201,578` (30 days of versions vs 365 staggered); `:789-791` (token "valid for 30 days", per-computer revocation); `:463` (look switch); `:327` (Assignments); section 5 (wizard steps); 6.2 (IGNORE is now SKIP FOR NOW); 9.2 ("inserts it when it arrives"); 11 (YouTube terms moved to Settings); section 16 vs the page toast; drive-reminder wording; "delete them yourself" ignores REMOVE FROM THIS COMPUTER. Fix: correct each line; add a test asserting bold control names exist in UI strings. Known: CR-86 not reflected; UX-1/APP-2 fixed in-code strings only.
- **PRAC-70 - Admins get three different editor-onboarding procedures, and none covers the per-editor fleet key** (`prac-docs-7`). Where: `INSTALL.md` Step 7; `SERVER.md:411-470`; `EDITOR_SETUP` sections 0 and 3.5. Fix: one checklist (create account, set password, mint a report token if the shared one is retired, editor runs the Installer, approve device and key, tick projects); other docs point at it.
- **PRAC-71 - There is no boundary between customer docs and about 70 internal ledgers and plans, and the docs index has stale status lines** (`prac-install-14`, `prac-docs-9`, `prac-simplify-16` low). Where: no root README; `docs/README.md` (plans and drafts under Getting started; UI_PORT_REVIEW "nothing fixed" under Operating it; stale statuses); the vendor's tailnet name, LAN IP and domain in DOCKER.md (7), CONFIG.md (5) and BACKUP_RESTORE.md (5); `APPLIANCE_INSTALL` step 5 stale; `PROJECTS_CLEANUP_PLAN.md` belongs to the owner's E:\Projects tree. Fix: WP J (one customer page per platform with screenshots, one editor page, a shipped customer-docs folder); split the index into Customer / Operator / Vendor-internal; create `docs/archive/`; scrub vendor addresses. Known: ZERO_TOUCH WP J (open).

### 3.8 Performance

- **PRAC-72 - The admin transfers page re-sends uncompressed HTML every 2 s, about 2 MB on a large onboarding fleet** (`prac-perf-1`, DOWNGRADED; about 200 KB for a 3x3 fleet). Where: `transfers.html:30-35`; `ui.py:1793-1801`; `app.py` (no GZip); `db.py:11098`. Fix: `GZipMiddleware(minimum_size=1024)`; poll live rows every 2 s, the queue and history slower or on input change; load file names on expand.
- **PRAC-73 - Every home-page poll recomputes the whole fleet's file-level backlog (about 0.4 s each)** (`prac-perf-2`). Where: `ui_home.py:423-443`; `api.py:611-667, 1044`; `db.py:11098`. One admin tab costs about 20% of a core on a desktop CPU, more on the NAS. Fix: cache the backlog per scope keyed on its inputs, or compute it once per collector cycle; home-transfers reads active transfers only; scope the grid's owed count. Known: CR-351 (write side only).
- **PRAC-74 - A wired or base computer walks the whole NAS tree over SMB every 5 minutes, even with sync off** (`prac-perf-3`). Where: `app.py:2037-2042, 10175-10178`; `manifest.py:170-210, 368-372`; `proxy_scan.py:401`. The live base rig used 6,291 CPU-seconds in 14 h. Fix: skip the manifest and proxy-gap walks when mode is wired/base or `sync_enabled` is false; use `entry.stat()` and an mtime skip elsewhere.
- **PRAC-75 - The Timeline Cards agent polls the script-server probe at 10 Hz whenever Resolve is not connectable** (`prac-perf-4`). Where: MulticamPipeline `cards/resolve_engine.py:3396-3420`, `cards/config.py:80`; `timeline_cards_bridge.py:174-182`; `script_server.py:319-357`. That is about 4 full process snapshots a second, forever. Fix: back off from 1 s to 5 s, reset on a state change, or have the bridge answer `ready()` from a 1 s cache (CR-68-safe).
- **PRAC-76 - Asking "is onnxruntime installed?" commits about 740 MB in the companion** (`prac-perf-5`). Where: `music_clap_sidecar.py:342-353` (called from refresh, refusal, ensure; `music_ingest.py:135,145`; `broll_server.py:1900`). OpenBLAS reserves per-core buffers; the live base rig shows 832 MB private. Fix: `importlib.util.find_spec`; set `OPENBLAS_NUM_THREADS=1` and `OMP_NUM_THREADS=1` in `launcher.py`.
- **PRAC-77 - The frozen companion is a onefile exe: each start writes 2 x 116 MB to %TEMP%, and it restarts itself whenever Resolve quits** (`prac-perf-6`). Where: `build.spec:257-298`; `supervisor.py`; restart on Resolve exit (24 of 55 starts); 40 leftover `_MEI` dirs. It looks like a dropper to EDR. Fix: onedir in a versioned folder with a stable shim; a tiny separate supervisor stub; reconnect in-process in place of restarting.
- **PRAC-78 - Opening a Cards episode runs seconds of pure Python inside the dashboard process that serves everyone** (`prac-perf-7`, PLAUSIBLE). Where: `cards.py`, `cards_pool.py`; CR-351 (CPU half open). Fix: measure page p95 on the NAS during an episode open before selling Cards; one process per engine if it stalls.

### 3.9 Complexity to cut or gate for v1

- **PRAC-79 - The YouTube cookie sign-in and ytdl code still ships in every companion exe and dashboard image, dormant** (`prac-simplify-4`, DOWNGRADED). Where: companion `ytdl_*` modules (about 8k lines, including the DevTools Google-cookie exporter); `build.spec:248`; `ytdl/web` copied into the image. (The GPL bgutil plugin and Deno are not in the image.) Fix: leave the cookie sign-in (and ideally all ytdl) out of the vendor build, tied to counsel's review. Known: COMMERCIAL_READINESS item 2 (counsel owed).
- **PRAC-80 - The AI CLI door (personal-subscription Claude Code/Codex) and the email triage agent that depends on it** (`prac-simplify-5`). Where: `cli_tools.py` (2,593 lines); `ai_providers.py`; `triage.py:31-35, 190-204`; `triage_mail.py`; `triage_actions.py`. Triage runs only through the CLI, and the manifest itself warns about subscription terms. Fix: hide the CLI rows, the SET UP wizard and `alerts_triage` behind a vendor-only flag; port triage to the SDK or defer it. Known: CR-26 (open), COMMERCIAL_READINESS item 1.
- **PRAC-81 - The fleet job scheduler runs on every customer machine, and collects idle time, for jobs only Timeline Cards creates** (`prac-simplify-6`). Where: `api.py:11843`; `jobs.py`; `jobs_runner.py`; companion `config.py:833` (`jobs_enabled` True); `TELEMETRY.md:274-275`; `ui.py:267`. Fix: tie it to a job-producing feature, off by default; hide JOBS; collect no `input_idle`.
- **PRAC-82 - Timeline Cards cannot be set up at a customer, yet about 9,400 lines of its integration ship to every customer** (`prac-editor-daily-8`, `prac-simplify-7`). Where: `cards*.py` (8 modules); `timeline_cards_role.py`, `timeline_cards_bridge.py`; `compose.image.yaml:191,333`; `install_dashboard_app.py:517-566`; companion `config.py:838,873,1543`. It needs another repo's checkout on the server and the editor machine plus a hand-set `cards_agent`, and the handshake has never run live. Fix: declare it out of v1 scope (sales copy, HOW_IT_WORKS section 14); gate the mount, routes, tunnel and role behind a vendor-only `[features] timeline_cards`; productise it later.
- **PRAC-83 - The Android TWA needs a per-customer APK, keystore and fingerprint** (`prac-simplify-8`). Where: `android.py`; `admin_settings.html:271-277`; `android_settings.html`; `ANDROID.md`; `tools/android/`. Fix: remove the panel from customer builds; document the Chrome PWA install; keep the TWA vendor-side.

---

## 4. Polish (lows)

- **PRAC-84** (`prac-install-17`) Secrets generated in the wizard need a manual container restart: exit 75 at the next idle moment and tell the admin the page will come back.
- **PRAC-85** (`prac-editor-daily-10`) A dashboard tick defaults to "every computer" (`home_macros.html:62-69`): pre-select this computer via `?machine=` from the tray, or require a choice and name the disk cost.
- **PRAC-86** (`prac-editor-daily-11`) "Fleet jobs" is vendor jargon on editor surfaces and the YouTube button casing is mixed: use "Lend this computer to the team" / SHARED JOBS and normalise casing.
- **PRAC-87** (`prac-admin-daily-11`, PLAUSIBLE) Email alerts need raw SMTP settings: add Gmail/Workspace/M365 presets and consider a vendor relay.
- **PRAC-88** (`prac-admin-daily-12`) Lane meters on the grid are always full or empty (`fleet_grid.html:184`): draw owed vs total, or use a word.
- **PRAC-89** (`prac-admin-daily-13`, `prac-simplify-14`) 14 Settings pages; HEALTH, INVARIANTS, PROTECTION and ALERTS overlap; JOBS shows without Cards; the fleet stop is on Users: fold the overlaps into HEALTH tabs, hide JOBS, move the stop to home.
- **PRAC-90** (`prac-errors-10`) The clock-skew and never-accepted-report tray lines give no action (`tray.py:3609-3632`): give the per-OS time-sync path and use `ui_copy.DIAGNOSTICS`.
- **PRAC-91** (`prac-errors-11`) Developer phrasing in refusals now shown beside controls ("time(s)", "enforce cycle", `!r` quoting, "TrueNAS-style username"): extend the copy scans to `detail=` strings.
- **PRAC-92** (`prac-errors-12`) The product is spelled CCSync / CC Sync / "the companion": pick one name and one noun, and scan for it.
- **PRAC-93** (`prac-docs-10`, `prac-config-14`) CONFIG.md misses about 20 `DASH_*` vars and 22 companion keys; `project_server` is absent and gives a permanent check_health FAIL; stale lines (`resolve-remote-sync`, `C:\Users\alex`, "hardcoded by decision"); editor/base vs WIRED/REMOTE vocabulary: add the rows plus a doc-coverage test; consider defaulting `project_server` to false.
- **PRAC-94** (`prac-docs-13`) SERVER.md carries the studio's own operations, vendor build steps, stale "nothing updates silently" and misnumbered steps: move them to private ops notes and RELEASE.md.
- **PRAC-95** (`prac-config-15`, `prac-simplify-13`) Customer-specific defaults reach new sites: `creators_shares='mofa-disaster'`, `archive_creators_dir=Creators_Club`, `HOME_PARENT=TheCreatorsPool`, example `tree_name`: use neutral defaults derived from `org_short`, and put the studio's values in its own site.toml. Known: product-surface-3, COMMERCIAL_READINESS 10/11.
- **PRAC-96** (`prac-config-16`) Three boolean grammars, and a site.toml typo falls back to the default silently: warn in `site_bool`, and echo effective `[features]` values at deploy.
- **PRAC-97** (`prac-support-11`) Stored diagnostics have no copy or download control and do not identify the site: add buttons, `org_name` and the dashboard version.
- **PRAC-98** (`prac-support-12`) Crash-report sending (`crash_reporting`, `DASH_SENTRY_DSN`) is dead configuration (no `sentry_sdk` in any build): remove the keys and the PRIVACY row, or replace them with PRAC-50/57.
- **PRAC-99** (`prac-simplify-15`) Two b-roll indexing pipelines kept in step by vendored copies, and INSTALL says b-roll needs an API key and a base rig: document companion ingest as the customer path. Known: COMMERCIAL_READINESS item 14.

---

## 5. Refuted

None. No critical or high was refuted outright. Verifiers corrected parts of several findings; each correction is folded into its item above:

- `prac-editor-daily-1`: the allow-list already unions the site and companion URLs.
- `prac-editor-onboard-3`: the hand-off count is lower than claimed.
- `prac-admin-daily-5`: device approvals do reach home as warnings.
- `prac-config-7`: the revert happens only on `--recreate`.
- `prac-config-5`: hand edits survive OTA.
- `prac-perf-1`: the payload size depends on fleet size.
- `prac-simplify-4`: the GPL unblock plugin is not in the image.
- `prac-support-2`: the base-rig path does carry the feed values.

---

## Coverage gaps

What the hunters said they did not reach:

- **Live behaviour:** nothing ran on a real NAS, Container Manager, SCALE YAML, Synology backend deploy body, Syncthing image entrypoint, Resolve (NO_SCRIPTING vs NO_SERVER), AV-scanned laptop cold start, or NAS CPU. Page timings come from a faster desktop.
- **Editor side:** live installs, uninstall/upgrade scripts beyond their docs, the macOS .app build and Mac tray/companion specifics (RAM, startup), the music SPA send path line by line, the ytdl web flow end to end, Tk popup open time.
- **Admin side:** the account page beyond a skim, SYNC PLANS JS, the project page, the b-roll/music/ytdl/Cards SPAs, the triage mail loop (gated off), alert email bodies, an exhaustive pass over all ~300 dashboard `detail=` strings.
- **Docs:** SERVER-SYNOLOGY, TENANCY, SECRETS, BACKUP_RESTORE, SYNC_SAFETY and the component READMEs end to end; API.md shapes field by field; the rest of START_HERE.
- **Config and other:** the indexer config, the onboarding wizard's config writes, mobile/Android settings, the music indexer internals, the macOS installer scripts, most of `server/*.py`, the size of the legacy-migration code, Cards-specific diagnostics, and sync throughput (benchmarked elsewhere, CR-347).
- **Verification:** mediums and lows were not adversarially verified. Expect a few percent to be wrong in part, as the downgrades above show.
