# Pre-launch practicality pass: prac-install (day one for a new customer)

Lens: a new customer's admin going from nothing to a working dashboard on TrueNAS SCALE and on
Synology DSM. Reviewed at HEAD 08b40eb plus the uncommitted working tree, 2026-10-06.

What I read: `docs/APPLIANCE_INSTALL.md`, `docs/INSTALL.md`, `docs/SYNOLOGY_EASY_INSTALL.md`,
`docs/ZERO_TOUCH_PLAN.md` (sections 3-4 and the WP status lines), `docs/SERVER-SYNOLOGY.md` (Install,
Publishing), the `docs/SERVER.md` outline, the relevant parts of `docs/DOCKER.md`, `docs/CONFIG.md`,
`docs/RELEASE_FEED.md` and `docs/MODULAR_UPDATES.md`, `dashboard/deploy/compose.appliance.yaml` in full,
`dashboard/deploy/run.sh`, `setup_engine.py` (all tasks), `setup_routes.py` (access gate), `setup_api.py`,
`settings.py` (`from_env`), `auth.py` (verify and boot checks), `templates/setup.html`, `site_store.py`
(auto-derived keys), `tools/release_key.py`, `.github/workflows/image.yml` (tags), the Synology chunk-size
plumbing (companion `site.py`/`config.py`, `server/install_dashboard_app.py`), and KNOWN_BUGS CR-57/CR-58.

Probe: `scratchpad/probe_appliance.py` built `Settings.from_env` from exactly the dashboard
`environment:` block of `compose.appliance.yaml` and called the real `setup_api` router. Result:
`auth_method: smb`, `syncthing_url: ''`, `release_feed_url: ''`, `pubkeys: ()`;
`GET /api/v1/setup/status` -> `{'auth_method': 'smb', 'users_exist': True}`;
`POST /api/v1/setup/admin` -> `403 first-admin setup only applies when DASH_AUTH_METHOD=local`.

Not covered: the editor's side of onboarding past "the dashboard exists" (the invite flow and
device approval belong to the editor-onboarding lens), live behaviour of Container Manager or TrueNAS
custom-app YAML (no live systems), and the Syncthing image's entrypoint (I reasoned from what I know of
it and did not pull it).

Step count, as of today. **Appliance path:** 2 env vars plus 3 hand-made folders, an SSH tunnel to
reach the wizard, then a wizard that cannot be signed in to (finding 1). It does not reach a working
dashboard. **Base-rig path** (`INSTALL.md`, the only path that works): about 25 terminal touchpoints
from a Windows machine holding a source checkout and the customer's NAS admin password. These are:
clone, write `site.toml` (12+ keys), `zfs create`, `ssh-keyscan`, export 5 secrets, install Syncthing,
read its API key out of a web GUI and export it, dry-run and real-run the dashboard install, `setup_tree`,
`setup_snapshots` x3, `secure_syncthing_gui`, `release_key new/pubkey/bake` plus a companion rebuild,
redeploy, `check_health`, Tailscale Serve by hand, set `dashboard_url`, `--recreate`.

---

### prac-install-1 - The appliance stack boots in SMB login mode, so nobody can ever create an admin or sign in

- **Severity:** critical
- **Confidence:** CONFIRMED (probed)
- **Where:** `dashboard/deploy/compose.appliance.yaml` (dashboard `environment:`, no `DASH_AUTH_METHOD`), `dashboard/src/ccsync_dashboard/settings.py:807` (`DASH_AUTH_METHOD` defaults to `smb`), `setup_api.py:62-72` (403 unless local), `setup_api.py:43-55` (status reports `users_exist: True` for non-local), `setup_routes.py:73-88` (`first_run_open` is False for smb), `auth.py:158-165` (SMB probe against an empty `DASH_SMB_HOST`)
- **What:** The appliance compose file does not set `DASH_AUTH_METHOD=local`, and neither does the Dockerfile. So the dashboard runs in `smb` mode with no SMB host. CR-57 fixed the first-admin bootstrap only for `local` mode, and that fix never reaches the appliance.
- **Scenario:** A new customer pastes the compose file, sets the two variables and opens `/setup`. `first_run_open` is False under smb, so `/setup` redirects to `/login`. Login runs an SMB probe against `''`, which fails for every password. If the wizard JS reads `/api/v1/setup/status`, it is told `users_exist: True` and skips step 2. A direct `POST /api/v1/setup/admin` returns 403. The `admin` task (if anyone could see it) says "set DASH_ADMIN_USERS to the NAS account(s) ... then redeploy". The appliance has no NAS accounts, which is the whole point of WP C. The install is dead at step 2.
- **Recommendation:** Add `DASH_AUTH_METHOD: "local"` to the appliance's dashboard `environment:` block. Better still, make `local` the default when `DASH_NAS_KIND` is unset, which is the appliance's own marker that the wizard has not run. Add a test in `tools/tests/test_compose_appliance.py` that builds Settings from the compose env and asserts that `POST /api/v1/setup/admin` succeeds on an empty DB. My probe is that test in 20 lines.
- **Known:** CR-57 (FIXED for local mode). This gap is not recorded.

### prac-install-2 - The appliance dashboard is reachable only from the NAS's own loopback, and nothing ever publishes it

- **Severity:** critical
- **Confidence:** CONFIRMED (code and docs)
- **Where:** `compose.appliance.yaml` `ports: "127.0.0.1:8480:8480"`. The dashboard is not in the tailscale netns. `grep serve-config dashboard/src` finds only a docstring. `docs/APPLIANCE_INSTALL.md` step 3 ("`http://<nas-ip>:8480` ... via Container Manager's own port-forward UI or an SSH tunnel") and step 4 ("Still NOT YET TRUE: Serve"). `setup_engine._check_tailnet` reports ok on "node signed in".
- **What:** On day one the admin's laptop cannot open `http://<nas-ip>:8480`, because the port is bound to 127.0.0.1. Container Manager has no "port-forward UI" that re-publishes a loopback bind: changing it means editing the YAML, which the file says never to do. So the first step needs SSH enabled on the NAS plus `ssh -L`. After the wizard, nothing calls `serve-config`, so the dashboard is never on the tailnet either. Editors' companions and browsers can never reach it. Meanwhile the "Connect to your tailnet" task turns green ("the bundled Tailscale node is signed in as ...") when the node signs in, and that tick suggests editors can now connect.
- **Scenario:** A studio owner with no terminal skills cannot open the wizard. One who can still finishes with a dashboard no editor can reach, behind a green tailnet tick.
- **Recommendation:** Do not sell the appliance path until WP B's second half lands. After `BackendState == Running`, the tailnet task's run should POST `deploy/tailscale/serve.json` to `/localapi/v0/serve-config`. It should handle the "Serve is not enabled on your tailnet" response by showing the one admin-console click, write `dashboard_url = https://<node>.<tailnet>.ts.net` into site_settings, and go green only once Serve answers. For the first visit, choose and document one path that needs no terminal. For example, publish `0.0.0.0:8480` until the first admin exists and then refuse non-loopback requests, or have the wizard print an SSH one-liner. Until then, remove "Container Manager's own port-forward UI" from the doc, because it does not exist.
- **Known:** APPLIANCE_INSTALL "NOT YET TRUE" / ZERO_TOUCH WP B (open). The green tailnet tick is not recorded.

### prac-install-3 - The required "Sync engine" step can never pass on the appliance (no SYNCTHING_GUI_URL)

- **Severity:** high
- **Confidence:** CONFIRMED
- **Where:** `compose.appliance.yaml` (dashboard env has no `SYNCTHING_GUI_URL`), `settings.py:797`, `setup_engine.py:881-931` (`_check_syncthing`/`_run_syncthing` return `todo "SYNCTHING_GUI_URL not configured"`), `syncthing` is a non-optional task
- **What:** The compose file bundles Syncthing in the tailscale netns, reachable from the dashboard at `http://tailscale:8384`, but it never tells the dashboard so. The `syncthing` task is required. It stays `todo` forever, so `outstanding_required` never empties and `done` never says "setup complete". `nas_syncthing_id` is never written to site_settings, so `/api/v1/site` publishes no NAS device id to editor wizards, and the collector has no Syncthing to read.
- **Scenario:** Every appliance install stops at step 6, with a message naming an environment variable the customer was told not to set and a value nobody gave them.
- **Recommendation:** Set `SYNCTHING_GUI_URL: "http://tailscale:8384"` in the appliance's dashboard environment. The API key is already adopted from `syncthing.env` via `secrets_boot.SIDECAR_ENV_FILES`. Pin this in `test_compose_appliance.py` alongside a check that the task goes ok against a stub.
- **Known:** not recorded.

### prac-install-4 - No install path ships the vendor's feed URL and public key, and INSTALL.md tells customers to mint and bake their own release key

- **Severity:** high
- **Confidence:** CONFIRMED
- **Where:** `docs/INSTALL.md` "Step 6 - the release signing key" (`release_key.py new / pubkey / bake`). `tools/release_key.py` (BAKE_TARGET is the companion source). `compose.appliance.yaml` (no `DASH_RELEASE_FEED_URL`, no `DASH_RELEASE_PUBKEYS`, and the header comment claims they are "generated"). `site.example.toml:244-256` (`feed_url` commented out). `setup_engine._check_release_key` ("the public half of your release key ... docs/RELEASE.md"). `_run_software` ("no vendor feed is configured"). ZERO_TOUCH_PLAN WP E row ("retire the customer-side key generation from INSTALL.md; release_key.py bake becomes a vendor-only step").
- **What:** The commercial model is that the vendor builds and signs and every customer dashboard pulls the signed feed. But the product never carries the vendor's feed URL or public key. Both default to empty on both deploy paths, and no customer-facing doc states either value. INSTALL.md still has the customer generate their own Ed25519 key and bake it into the companion source. That only makes sense if the customer builds the companion themselves (PyInstaller, plus a Mac). A key that customer makes cannot verify vendor-signed builds. The wizard's release-key task reinforces this by asking for "your release key".
- **Scenario:** A customer follows INSTALL.md. Either they set their own pubkey, and every vendor build from the feed is rejected as unsigned, or they set nothing, and every publish 503s. In both cases editors have nothing to install from Settings, then Packages. The software task says "no vendor feed is configured (DASH_RELEASE_FEED_URL)", and only the vendor knows that value.
- **Recommendation:** Bake the vendor feed URL and the vendor public key(s) into the image as defaults (env still overrides, for air-gapped or rotated sites). Make the release-key task read "vendor key present: id X". Delete INSTALL.md Step 6 for customers and move it to RELEASE.md as a vendor-only step, as WP E already decided. Remove the "generated" claim about `DASH_RELEASE_PUBKEYS` from the compose header.
- **Known:** ZERO_TOUCH_PLAN WP E (the doc half was never done). Not in KNOWN_BUGS.

### prac-install-5 - The appliance pulls `ccsync:1`, which is v0.7.44 from 2026-09-11, and the ship process never moves it

- **Severity:** high
- **Confidence:** CONFIRMED (the tag fact comes from the repo's own docs plus local tags; I did not query GHCR)
- **Where:** `compose.appliance.yaml` (`image: ghcr.io/the-creators-club/ccsync:1`), `.github/workflows/image.yml:162` (`:1` only on `v*` tags), `git tag` (latest `v0.7.44`; 74 commits since; `__init__.VERSION = 0.7.73`), `docs/MODULAR_UPDATES.md:96` ("The `v*` git tags stop at v0.7.44 while 0.7.73 is live"), `docs/CONFIG.md:187` and `docs/DOCKER.md:482` (both still say "`:1` does not exist yet")
- **What:** Releases ship as OTA bundles and image-mode deploys by sha. No `v*` tag has been pushed since 2026-09-11, so the floating `:1` the appliance pins is 29 dashboard versions old. It predates the CC Terminal UI port and three bug-hunt fix waves. It also cannot self-update (finding 4: no feed). Two docs still say the tag does not exist, which contradicts MODULAR_UPDATES.
- **Scenario:** The first paying customer installs a month-old dashboard with already-fixed defects. The vendor then supports two code lines without knowing it.
- **Recommendation:** Make tagging part of the release pathway (`ship.cmd` / `publish_latest.py` pushes `vX.Y.Z` so `:1` follows), or pin the appliance compose to a digest bumped per release. Add a drift check that fails when `:1`'s version differs from the live dashboard's. Fix CONFIG.md and DOCKER.md.
- **Known:** MODULAR_UPDATES.md notes the tag gap but not its effect on the appliance.

### prac-install-6 - Syncthing in the appliance probably cannot write its own config directory (root-owned bind mount, non-root user)

- **Severity:** high
- **Confidence:** PLAUSIBLE
- **Where:** `compose.appliance.yaml`: the `syncthing` service runs as `user: ${APP_UID}:${APP_GID}` with `${CCSYNC_DATA}/syncthing-config:/var/syncthing/config`. `secrets-init` chowns only `/data` (= `${CCSYNC_DATA}/data`). There is no end-to-end run of this file in `docs/spikes/` (S5 tested `user:` with a pre-chowned dir).
- **What:** Docker creates a missing bind-mount source as root:root 755. That is the same reason the file gives for `secrets-init` existing at all. `syncthing-config` is never chowned. The Syncthing image only fixes ownership (PUID/su-exec) when it starts as root, and here it starts as uid 3000. So Syncthing cannot create `config.xml` and restart-loops. Lane C never comes up and step 6 fails even after finding 3 is fixed.
- **Scenario:** First `up` on a fresh `CCSYNC_DATA`: `syncthing` is in a restart loop, and `docker compose logs syncthing` shows a permission denied error.
- **Recommendation:** Have `secrets-init` (already root) `mkdir -p` and chown `syncthing-config` too (it would need that mount). Then run the appliance compose end to end on a scratch Synology and a scratch SCALE before anything else in this list is called done. APPLIANCE_INSTALL's DRAFT label says nobody but the author has done this.
- **Known:** not recorded.

### prac-install-7 - On Synology the appliance needs APP_UID/APP_GID set by hand, the install doc says there are only two variables, and the "wizard writes them back" claim is impossible

- **Severity:** high
- **Confidence:** CONFIRMED
- **Where:** `compose.appliance.yaml` header ("the wizard's 'Your studio' step reads the REAL uid/gid ... and writes it back as APP_UID/APP_GID ... Until the wizard exists (WP D), set them by hand from `id <the DSM account>`"). `docs/APPLIANCE_INSTALL.md` step 2 ("Two variables, both required"). `templates/setup.html:62-68` (studio form: org name, short name, tree name, drive letter, templates; no uid). `run.sh` (only warns).
- **What:** A container cannot edit its own compose file, and the wizard has no such field. The doc tells a Synology customer about two variables. The compose comments, which a customer pasting into Container Manager never reads, say a third and fourth are needed. Those must come from `id` of "the DSM account Container Manager actually used", and no such account exists: Container Manager runs as root. With uid 3000, which DSM does not have, the dashboard and the sftp sidecar write into an ACL'd share as an unknown uid. The result is files editors browsing over SMB cannot open, or writes refused outright.
- **Scenario:** A Synology customer follows the doc. Storage check fails or passes depending on the share's ACL, and later, SMB users see files they cannot open.
- **Recommendation:** Choose a fixed contract: either the doc tells Synology users to create a `ccsync` user and set `APP_UID`/`APP_GID` in the Environment tab (with a screenshot), or `secrets-init` sets permissions on the tree mount itself. Remove the "wizard writes it back" sentence.
- **Known:** not recorded.

### prac-install-8 - Half the wizard's fixes are "set an environment variable and redeploy", which an appliance customer is told never to do

- **Severity:** high
- **Confidence:** CONFIRMED
- **Where:** `setup_engine.py`: `_check_admin` ("set DASH_ADMIN_USERS ... then redeploy"), `_check_syncthing` ("SYNCTHING_GUI_URL not configured"), `_nas_client` ("set DASH_NAS_HOST and DASH_NAS_API_KEY ... then redeploy"), `_check_release_key` ("Set it and redeploy"), `_run_software` ("DASH_RELEASE_FEED_URL"), `_run_secrets` ("Restart the container to load them"). Compose header: "NOTHING ELSE ON THIS FILE ... SHOULD BE EDITED".
- **What:** The appliance's promise is that everything after the paste is a page in the browser. But six of the thirteen tasks can only be fixed by editing container environment and recreating. That is Container Manager's Environment tab (which needs the project stopped and rebuilt) or TrueNAS's YAML editor. A "redeploy" on the appliance is not defined anywhere in the customer docs.
- **Scenario:** An admin reads "set DASH_NAS_HOST and DASH_NAS_API_KEY ... then redeploy" and has no idea where to set them or how to redeploy. They open a support ticket for each one.
- **Recommendation:** Move each of these into site_settings or the `/data/secrets` store with a form on the task (the NAS credential, the alert destination already works this way), and read them live. Where a restart is truly needed, the dashboard should exit 75 itself after saving (run.sh already treats 75 as restart) rather than tell the admin to do it. Any env-var wording left in the wizard should name the exact Container Manager / TrueNAS click path.
- **Known:** not recorded.

### prac-install-9 - TrueNAS "Install via YAML" has nowhere to put the two variables the doc says to fill in

- **Severity:** medium
- **Confidence:** PLAUSIBLE (not checked against a live SCALE UI)
- **Where:** `docs/APPLIANCE_INSTALL.md` step 2 ("TrueNAS SCALE (Apps): Discover -> Custom App -> Install via YAML -> paste the compose text -> fill in the same two variables"). The compose header says "a plain `.env` beside this file on TrueNAS's 'Install via YAML'". There are eight `${CCSYNC_TREE:?...}`/`${CCSYNC_DATA:?...}` sites in the file.
- **What:** As far as I know, SCALE's custom-app YAML screen is one text box. The middleware renders the file into its own app-config directory, the admin cannot place a `.env` beside it, and there are no variable fields. Interpolation therefore fails with the `:?` message, and the only fix is to hand-replace every occurrence with literal paths.
- **Scenario:** A TrueNAS customer pastes the file, gets "set CCSYNC_TREE to the shared folder ..." and has no field to put it in.
- **Recommendation:** Verify on a SCALE 25.x box. If confirmed, ship a TrueNAS variant with two clearly marked literal paths at the top (YAML anchors), or a catalog app (WP I) with a form. Change the doc to match what the screen actually offers.
- **Known:** not recorded.

### prac-install-10 - The only install that works today needs a vendor engineer, ~25 terminal steps, a Windows rig with the source, and the customer's NAS admin password

- **Severity:** high
- **Confidence:** CONFIRMED (counted from INSTALL.md / SERVER-SYNOLOGY.md)
- **Where:** `docs/INSTALL.md` sections 1-2 (base rig: Windows, Python 3.11, git, "git clone <your checkout of this repo>", `cd resolve-remote-sync`), section 3 (`TRUENAS_PW`/`SYNO_PW` exported on the base rig; "SYNCTHING_API_KEY is produced by Step 3.1", read from the GUI between steps), `docs/SERVER-SYNOLOGY.md` "Publishing the dashboard" (Serve by hand over SSH, then `--recreate`)
- **What:** With the appliance not working (findings 1-3, 6), the installable product is the base-rig path. It assumes the customer has a source checkout (the vendor's whole repo, including internal docs and history), a Windows machine with Python, comfort with PowerShell, SSH, `zfs`, `ssh-keyscan`, and a secrets vault, and the patience to export a value from one tool's GUI in the middle of the sequence. Realistically the vendor will do this remotely, holding each customer's NAS admin password, from one rig. For ten customers that is ten admin passwords and ten `site.toml` files on the vendor's machine, and every redeploy is a vendor SSH session.
- **Scenario:** The vendor sells to customer #2. Install is a multi-hour remote session, and every later "change the dashboard URL" or "turn b-roll on" is another vendor session with `--recreate`.
- **Recommendation:** Make a launch decision and write it down. Either (a) "install is a vendor-delivered service" for the first customers: then write a vendor runbook with one `site.toml` per customer kept in a private ops repo, a checklist, and a plan for how the customer's admin password is held and dropped afterwards (the scoped TrueNAS API key, a DSM service account). Or (b) fix findings 1-3, 5-7 and ship the appliance path as the only customer path. Do not hand INSTALL.md to a customer in its current form: it says "assumes you have never seen this repository" while starting with `git clone`.
- **Known:** ZERO_TOUCH_PLAN section 1 (target), SYNOLOGY_EASY_INSTALL "The bar" (states this cost). No decision recorded.

### prac-install-11 - The Synology 64Ki chunk size that prevents silent truncation is a manual site.toml line, defaulting to the size that loses footage

- **Severity:** high
- **Confidence:** CONFIRMED
- **Where:** `site.example.toml:154` (`sftp_chunk_size = "255Ki"      # Synology MUST set "64Ki"`), `server/install_dashboard_app.py:2295` (passes the value through), `server/backends/synology.py:44` (documents it, does not enforce it), `docs/INSTALL.md` section 6 checklist ("`[net] sftp_chunk_size` is **`64Ki` on a Synology site**"), companion `site.py:77-84`
- **What:** On a DSM site (base-rig path; the appliance's own sshd is not affected), 255Ki makes DSM 7.2's OpenSSH 8.2 truncate every lane-B download at 539,000,832 bytes while rclone reports success. The safe value depends only on `nas_kind`, which the installer already knows (`--nas-kind synology`). Yet it is left to the admin to remember, and the example file pre-fills the dangerous value. The only guard is a line in a hand-run verification checklist.
- **Scenario:** A Synology customer copies `site.example.toml`, changes the keys INSTALL.md's "minimum you must fill in" list names (chunk size is not on it), and deploys. Every proxy over 514 MiB arrives truncated with no error.
- **Recommendation:** When `nas_kind == synology` and DSM's sshd is in use, `install_dashboard_app.py` should default `sftp_chunk_size` to 64Ki and refuse an explicit value above it, and `site_store.validate` should do the same for the Settings page. Add it to INSTALL.md's "minimum you must fill in" in the meantime.
- **Known:** documented as a rule in SERVER-SYNOLOGY.md; no enforcement recorded.

### prac-install-12 - The appliance needs three folders made by hand before the first `up`, and the files disagree about who makes them

- **Severity:** medium
- **Confidence:** CONFIRMED
- **Where:** `docs/APPLIANCE_INSTALL.md` step 2 ("Create `Projects/`, `Assets/B-roll Archive/` and `Assets/Music/` ... by hand"), the same doc's Troubleshooting ("the wizard that would create them (WP D) does not exist yet"), the `compose.appliance.yaml` header ("If it does not have those subfolders yet, the wizard's 'Storage check' step ... creates them"), `setup_engine._run_storage` (on the appliance shape `_tree_root` is None, so it creates nothing)
- **What:** Three sources give three stories. The compose header (what the customer pastes) promises the wizard creates them. The doc says it cannot, because Docker invents them root-owned. The troubleshooting section says WP D does not exist. When they are missing, the stack still comes up healthy, and the only signal is a probe-write failure in the wizard.
- **Scenario:** A customer who reads only the compose file skips the folders. The dashboard cannot write `/projects`, and the Storage check says "could not write/read/delete a probe file: Permission denied" with no hint about the cause.
- **Recommendation:** `secrets-init` is already root. Mount `${CCSYNC_TREE}` there too, `mkdir -p` the three paths and chown them to `APP_UID:APP_GID` when it creates them, which removes the manual step entirely. Make the probe failure detail name the root-owned-folder cause. Fix the compose header and the troubleshooting text.
- **Known:** not recorded.

### prac-install-13 - The wizard's "Your studio" step never asks for the address editors will use, and Done can go green without one

- **Severity:** medium
- **Confidence:** CONFIRMED
- **Where:** `templates/setup.html:62-68` (org name, short name, tree name, drive letter, templates), `setup_engine._STUDIO_REQUIRED_KEYS` (no `dashboard_url`/`sftp_host`), `_check_done` (gates on required tasks plus release_key/snapshots/alerts, not on a URL), `docs/APPLIANCE_INSTALL.md` step 3 table ("name, tree, URLs")
- **What:** `dashboard_url` and `sftp_host` are what every editor's installer and companion are written from (and the loopback CORS allow-list). The wizard never collects them, and `done` does not require them. The only prompt is inside the optional tailnet task ("set dashboard_url on the Settings page").
- **Scenario:** An admin finishes the wizard, sees "setup complete" and sends editors the installer. Their wizards fetch `/api/v1/site` with no dashboard URL or SFTP host, and onboarding fails or writes a LAN address.
- **Recommendation:** Make "the address editors use" a required wizard field. On the appliance, auto-fill it from Serve once finding 2 is fixed. Have `done` refuse while it is empty. Correct the doc table.
- **Known:** not recorded.

### prac-install-14 - Customer-facing install docs are mixed with internal history, contradict each other, and carry the vendor's own addresses

- **Severity:** medium
- **Confidence:** CONFIRMED
- **Where:** No repo-root README. `docs/README.md:17` sends a newcomer to INSTALL.md as "Start here". `docs/INSTALL.md` (`cd resolve-remote-sync`, which is not the repo's name; Step 6 as in finding 4). `docs/APPLIANCE_INSTALL.md` step 5 ("Only `software` has a button at all", which is stale: `tailnet` and `alerts` have buttons) and the Troubleshooting WP D line. `docs/INSTALL.md` platform table links SYNOLOGY_EASY_INSTALL.md (a design that says "nothing here exists yet") as "the packaged-installer design". `docs/DOCKER.md` (7 hits: `truenas.tail26290e.ts.net`, `192.168.0.102`, `thecreatorsclub.co/dash`), `docs/CONFIG.md` (5) and `docs/BACKUP_RESTORE.md` (5) carry studio-specific addresses.
- **What:** A customer gets the whole `docs/` tree: about 70 files, mostly bug-hunt ledgers and plans, with no line between "for customers" and "for us". The install pages still disagree with each other and with the code.
- **Scenario:** A customer admin follows the wrong page (INSTALL.md instead of APPLIANCE_INSTALL.md, or the reverse) and hits contradictions on step 2. A reader of DOCKER.md sees another studio's tailnet name.
- **Recommendation:** ZERO_TOUCH WP J: one customer install page per platform (screenshots, no history, no ids, no "WP" language), one editor page, and a customer docs folder that ships, separate from the internal `docs/`. Until then, at least fix the stale lines named above and add a top-level README that routes customers.
- **Known:** ZERO_TOUCH_PLAN WP J (open).

### prac-install-15 - If the bundled tailscaled restarts on its own, Syncthing and SFTP silently drop off the tailnet until someone runs `docker compose up`

- **Severity:** medium
- **Confidence:** CONFIRMED (documented in the compose file from spike S5; not re-measured)
- **Where:** `compose.appliance.yaml` comments on `syncthing.depends_on` and `sftp.depends_on` ("goes unreachable on the tailnet until an admin runs `docker compose up` ... by hand"), `docs/APPLIANCE_INSTALL.md` "What IS true today"
- **What:** Lanes A, B and C ride the tailscale container's netns. A crash and restart of only that container orphans both sidecars. No alert covers this, and the fix needs a terminal. An appliance customer will not know to do it.
- **Scenario:** tailscaled crashes on a Saturday. The dashboard looks fine on the LAN tunnel, but every editor's sync stops until the vendor is called.
- **Recommendation:** Use `depends_on: tailscale: {condition: service_healthy, restart: true}` (Compose 2.17+, so it is in the 2.20.1 that Container Manager ships) with a tailscale healthcheck. Or have the dashboard detect "Syncthing unreachable while tailscale is Running" and raise a notice naming the one-click restart. Verify on the DS423+.
- **Known:** documented in the compose file as "real, not-yet-built follow-up work". Not in KNOWN_BUGS.

### prac-install-16 - The appliance's Syncthing GUI listens on 0.0.0.0 inside the tailnet node's namespace, with no GUI password step

- **Severity:** medium
- **Confidence:** PLAUSIBLE (handing to the security lens)
- **Where:** `compose.appliance.yaml` (`STGUIADDRESS: "0.0.0.0:8384"`, `network_mode: service:tailscale`, comment "The GUI ... is deliberately never exposed anywhere outside this namespace"), `docs/INSTALL.md` Step 5 (the base-rig path secures the GUI with `secure_syncthing_gui.py`; the appliance wizard has no equivalent)
- **What:** The namespace this binds in is the tailnet node's own. In userspace-networking mode, tailscaled delivers inbound tailnet TCP to local listeners, so the GUI (admin over every folder) is likely reachable at `<node>:8384` from any tailnet peer. It has no GUI username or password, because the appliance has no "secure the GUI" step.
- **Scenario:** Any device on the customer's tailnet (every editor's laptop) opens `http://ccsync:8384` and gets full Syncthing admin.
- **Recommendation:** Bind `STGUIADDRESS` to `127.0.0.1:8384` only if the dashboard can still reach it (it is not in that netns, so it cannot). Otherwise keep 0.0.0.0 but have secrets-init set a GUI user and password (or `STGUIAPIKEY`-only with `insecureAdminAccess=false` plus a password), and confirm with one probe from a tailnet peer.
- **Known:** not recorded.

### prac-install-17 - "Secrets" generated during the wizard need a container restart the admin is told to do by hand

- **Severity:** low
- **Confidence:** CONFIRMED
- **Where:** `setup_engine._run_secrets` ("generated N just now. Restart the container to load them")
- **What:** On a stack where the admin has no shell, "restart the container" means finding the project in Container Manager or SCALE Apps. Meanwhile the running process has no session secret and the like.
- **Scenario:** Rare (secrets-init and boot normally generate everything), but when it happens the admin is stuck.
- **Recommendation:** After generating, exit 75 on the next idle moment (run.sh and the restart policy already handle it) and tell the admin "restarting, this page will come back".
- **Known:** not recorded.
