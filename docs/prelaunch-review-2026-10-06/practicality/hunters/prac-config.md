# Pre-launch practicality pass - configuration surface (prac-config)

Lens: the configuration surface a customer's admin, an editor and the vendor
actually touch - `site.toml` / `site.example.toml`, the dashboard environment
(`DASH_*`) as `server/install_dashboard_app.py` writes it, the DB-backed site
manifest (`site_store.py`) and the Settings page, the companion's
`config.toml` (147 default keys) and its settings window, and the docs that
describe them (`docs/CONFIG.md`, `docs/INSTALL.md`, `docs/SECRETS.md`).
Working tree as of 2026-10-06 (HEAD 08b40eb plus uncommitted changes).

Probed: `site_store.seed_from_env_once` + `feature_enabled` +
`resolved_manifest` against a scratch DB (scratchpad `probe_seed.py`); the
companion's `config.DEFAULTS` against the keys `settings_window.py` touches.
Read: the deploy's environment dict and `.env` composition, the truenas
backend's `deploy_stack`, `auth.is_admin`, `loopback_guard.allowed_origins`,
the Settings template's help strings, `server/common.py`'s site loader.
Not covered: the appliance compose path end to end (`compose.appliance.yaml`
+ `/setup` wizard), the Synology backend's deploy body, the indexers' config.

### prac-config-1 - Editing site.toml and redeploying silently changes nothing after the first boot

- **Severity:** high
- **Confidence:** CONFIRMED (probed)
- **Where:** dashboard/src/ccsync_dashboard/site_store.py:609-706 (`seed_from_env_once`), :850-875 (`feature_enabled`); server/install_dashboard_app.py:2189-2300, :2575-2585; site.example.toml:94-96, :392-395; docs/CONFIG.md §1.1
- **What:** At first boot the dashboard copies every `DASH_SITE_*` value into `site_settings`, including features written as `"0"` and every sftp/manifest key, and from then on a DB row wins over the environment. The deploy keeps projecting `site.toml` into `DASH_SITE_*` on every run, and `site.example.toml` keeps telling the operator to change things there ("change them here, not in one component", "Redeploy the dashboard after changing this so editors pick it up"). Nothing compares the two or says that the edit was ignored. The reverse is also true: a change made on Settings never reaches `site.toml`, which the deploy and every `server/` script still read.
- **Scenario:** A customer deploys with `[features] youtube_download = false`, later sets it `true` and redeploys. The deploy provisions the unblock sidecars, but `feature_enabled` reads the seeded `"0"` row: `/ytdl` stays off and companions hide the menu. The probe shows the same for `sftp_chunk_size` (redeployed `64Ki`, manifest still serves `255Ki`) and `org_name`. On a Synology site that is trying to fix its chunk size, the fix never reaches an editor (see prac-config-3). The owner has already hit this class once (CR-99, the dashboard URL).
- **Recommendation:** Pick one source of truth per key and enforce it. Simplest: make the deploy authoritative for the keys it projects. On every boot, compare the env with the row seeded from it (`updated_by = "seed:env"`) and re-seed when the env changed and no human has edited the row since. Show a Settings banner for "deploy says X, this page says Y". Have the deploy print the drift after `up` (read `GET /api/v1/admin/site`). Change the site.example.toml comments to say where each key really lives.
- **Known:** related to CR-99 (FIXED; a different symptom of the same two-source design). No open entry.

### prac-config-2 - Settings tells an admin to set SFTP chunk size to "64M", accepts it, and pushes it to every editor

- **Severity:** high
- **Confidence:** CONFIRMED (wiring read end to end; rclone's behaviour at 64M against a given sshd not measured)
- **Where:** dashboard/templates/admin_settings.html:45 (and :46 `sftp_concurrency` "Example: 8", :48 `rclone_remote` "Example: ccnas"); dashboard/src/ccsync_dashboard/site_store.py:72 (`"sftp_chunk_size": "str"`, no validator); companion/src/ccsync_companion/site.py:78-85 (server-owned key); companion/src/ccsync_companion/sync/rclone_lane.py:600-612
- **What:** The help text for the one knob that is documented to lose footage when set wrong gives `64M` as its example. The real values are `255Ki` (TrueNAS) and `64Ki` (Synology), and `64M` is 256 times the measured-good ceiling. The key is validated as a plain string. The manifest value overrides every companion's `config.toml`, and lanes A/B pass it straight to `rclone --sftp-chunk-size`. The `sftp_concurrency` example (8, default 64) quietly gives up most of the tailnet window. The `rclone_remote` example names a stanza no editor's `rclone.conf` contains.
- **Scenario:** An admin tunes for speed from the help text and saves `64M`. Within one manifest refresh, every editor's uploads and proxy downloads run with a chunk size no server is measured against. The best case is every transfer failing. The worst case is the spike-6 shape: truncation with rclone reporting success. `rclone_ignore_checksum` defaults to true, so nothing catches it.
- **Recommendation:** Validate `sftp_chunk_size` as an rclone size of 32Ki to 255Ki, and refuse anything above 64Ki when `nas_kind = synology`. Give the real defaults as the examples. Move the three transport keys behind an "advanced / vendor support only" fold.
- **Known:** none.

### prac-config-3 - A Synology site loses footage unless the operator remembers to set one key; nothing enforces it

- **Severity:** high
- **Confidence:** CONFIRMED (no enforcement anywhere; the truncation itself is the measured spike-6 result)
- **Where:** site.example.toml:154-155 (`sftp_chunk_size = "255Ki"  # Synology MUST set "64Ki"`); server/backends/synology.py:43-46 (a docstring only); server/install_dashboard_app.py:2295; server/check_health.py (no chunk check); companion/src/ccsync_companion/config.py:277
- **What:** Synology is a supported platform. On it, the shipped default `255Ki` silently truncates lane-B downloads at 539,000,832 bytes and rclone reports success. The only protection is a comment in the example file. `[nas] kind = "synology"` does not change the default, the deploy does not refuse the combination, `check_health.py` does not flag it, and no dashboard notice covers it. `shell_type` has the same shape (it must be "none" on DSM): at least `editor_shell = "sftp-only"` forces that one, but nothing forces the chunk size.
- **Scenario:** A customer on DSM copies `site.example.toml`, fills in the required keys and leaves `[net]` alone. Every editor's proxy over 514 MiB arrives short, Resolve refuses or plays the media short, and the dashboard shows lane B green.
- **Recommendation:** Derive the transport defaults from `nas_kind` (Synology gives 64Ki/16/none) in both the deploy and `site_store._shape`. Refuse at deploy time, and in the Settings validator, a chunk above 64Ki on a Synology site. Add a `check_health` line and an alert kind for the mismatch.
- **Known:** documented as a requirement (synology-spikes-2026-08-17 spike 6); no KNOWN_BUGS entry for the missing enforcement.

### prac-config-4 - A new customer is told to make their own release key; the vendor key and feed URL they actually need are never given

- **Severity:** high
- **Confidence:** CONFIRMED
- **Where:** docs/INSTALL.md:210-235 (Step 6); server/install_dashboard_app.py:1651-1665 (image-mode refusal: "Fix: $env:DASH_RELEASE_PUBKEYS = python tools/release_key.py pubkey"); site.example.toml:256 (`feed_url` placeholder `<org>/<releases-repo>`); companion/src/ccsync_companion/release_pubkey.py:53 (the vendor key is baked here); docs/CONFIG.md §2.5b (music ingest needs the feed); docs/ZERO_TOUCH_PLAN.md:284
- **What:** Two values decide whether a customer's fleet ever receives a build: `DASH_RELEASE_PUBKEYS` (must be the VENDOR's public key) and `[releases] feed_url` (the vendor feed). INSTALL Step 6 walks the customer through `release_key.py new`, then `pubkey`, then `bake`. A customer cannot bake into a vendor build, and their own key verifies nothing the vendor signs. The image-mode refusal sends them to the same command, which needs the private key file only the vendor holds. The feed URL is a placeholder, and blank means the feed is off, so there are no updates. Local music ingest on editors' machines is also dead, because the CLAP model URL is derived from the feed. ZERO_TOUCH_PLAN WP E listed "retire the customer-side key generation from INSTALL.md" and it is still there.
- **Scenario:** A paying customer follows INSTALL.md exactly and generates a key. Every signed vendor record then fails verification, or with no feed URL is never fetched. The fleet stays on the install build forever, and a security fix cannot reach them without a vendor visit.
- **Recommendation:** Default both values in the deploy to the vendor's: the baked `RELEASE_PUBKEYS` and the vendor `channel.json` URL. Keep overrides for a self-building site. Move Step 6 into a "vendor / self-build only" appendix. Change the refusal text to name the vendor key.
- **Known:** ZERO_TOUCH_PLAN.md WP E (open plan item); COMMERCIAL_READINESS item 9 status line ("set DASH_RELEASE_PUBKEYS on both live dashboards") is the vendor's own fleet only.

### prac-config-5 - SSO / local accounts are sold as an install choice but the deploy cannot turn them on

- **Severity:** high
- **Confidence:** CONFIRMED
- **Where:** docs/INSTALL.md:357, :366-381 ("Decide this before the first editor signs in"); docs/CONFIG.md §2.3; server/install_dashboard_app.py (no `DASH_AUTH_METHOD` / `DASH_OIDC_*` anywhere; the TrueNAS environment dict at :2440-2680 is a fixed list); dashboard/deploy/compose*.yaml (neither key); dashboard/src/ccsync_dashboard/auth.py:146-180 (env-only `settings.auth_method`)
- **What:** `DASH_AUTH_METHOD=oidc|local` and the eleven `DASH_OIDC_*` variables are read only from the container environment. The supported deploy builds that environment from a fixed dict and a fixed `.env`, with no `site.toml` key, no passthrough and no Settings field. The TrueNAS backend POSTs the whole compose config, so a hand edit in the TrueNAS Apps UI is replaced on the next deploy. The same applies to every tunable in CONFIG.md §2.2-2.6 that the deploy does not name: `DASH_ENFORCE_MAX_REMOVALS`, `DASH_JOBS_*`, the `DASH_INTERVAL_*` family, `DASH_SYNCTHING_TAILNET_IP/_ONLY`, `DASH_SESSION_*_SECONDS`, `DASH_CARDS_ENGINES`, `DASH_RELEASE_SOAK_MINUTES`.
- **Scenario:** A customer with Entra ID reads INSTALL §5, picks OIDC, and finds no supported way to set it. If a vendor engineer edits the app config by hand, it works until the next deploy (or a vendor-run one), which silently drops every editor back to SMB passwords. Editors who never had NAS passwords are then locked out.
- **Recommendation:** Add an `[auth]` table to `site.toml` (method, issuer, client id, scopes, claims, allowed groups; secret via env) and a `[tuning]` table for the documented knobs, projected by the deploy. Or make the deploy carry through any `DASH_*` already in the running app's environment that it does not itself own. Until then, mark OIDC "not available through the shipped deploy" in INSTALL.md.
- **Known:** none.

### prac-config-6 - The documented secret-rotation recipe cannot be followed: the deploy never forwards DASH_SESSION_SECRET_PREVIOUS

- **Severity:** high
- **Confidence:** CONFIRMED
- **Where:** docs/SECRETS.md:20, :106-135; dashboard/src/ccsync_dashboard/settings.py:810-813; server/install_dashboard_app.py (no occurrence of `SESSION_SECRET_PREVIOUS`; the env dict :2467 and the Synology `.env` :6088-6104 carry only `DASH_SESSION_SECRET`)
- **What:** DASH-2 added the accept-only predecessor so a rotation does not 401 the fleet. SECRETS.md says to "re-deploy with the old value in `DASH_SESSION_SECRET_PREVIOUS`". The deploy has no code that reads that variable or writes it into the container.
- **Scenario:** After a suspected leak, the operator exports the new secret plus `DASH_SESSION_SECRET_PREVIOUS=<old>` and runs the deploy. The container gets only the new secret. Every companion's never-expiring identity token fails, `POST /api/v1/report` 401s fleet-wide, and the halt / push / resume command channel dies. This is exactly the outage DASH-2 was built to prevent, and it now happens during a security incident.
- **Recommendation:** Forward `DASH_SESSION_SECRET_PREVIOUS` (and `DASH_CARDS_TOKEN`-style secrets) into the `.env` / env dict and add it to `SECRET_ENV_VARS` for masking. Add a deploy test that pins every env var SECRETS.md tells an operator to set.
- **Known:** DASH-2 (FIXED in the dashboard; this deploy-side gap is not recorded).

### prac-config-7 - Settings that live only in the deploying shell revert silently on the next deploy (admins, shared token, proxies)

- **Severity:** high
- **Confidence:** CONFIRMED (revert mechanism); PLAUSIBLE (admin lock-out depends on whether the NAS admin can pass the SMB/editors-group login)
- **Where:** server/install_dashboard_app.py:5338 (`admin_users = os.environ.get("DASH_ADMIN_USERS") or truenas_user`), :2463-2464 (`DASH_SHARED_REPORT_TOKEN_ENABLED ... or "1"`), :2471; dashboard/src/ccsync_dashboard/auth.py:935-955 (in smb/oidc mode, admin comes from env alone); docs/INSTALL.md:381-389
- **What:** Who is an admin, whether the shared fleet token is still accepted, which proxies are trusted, whether b-roll is on and which shares are "our footage" are all read from the shell that runs the deploy. None is in `site.toml`, `load_secrets.ps1` or the INSTALL secrets table. A deploy from a shell that lacks them writes the fallback without a word: the admin list becomes the NAS admin account, and the shared token is re-enabled after INSTALL told the operator to turn it off "once the Users page shows no machines on it".
- **Scenario:** The vendor redeploys a customer's dashboard from their own terminal to ship a fix. `DASH_ADMIN_USERS` is not exported, so the studio owner and their producer lose admin (Settings, Users, halts) and only `truenas_admin` remains. The customer's hardening step (`DASH_SHARED_REPORT_TOKEN_ENABLED=0`) is undone in the same run.
- **Recommendation:** Move these into `site.toml` (`[auth] admin_users`, `[auth] shared_report_token`, plus the existing `[net] trusted_proxies`, `[broll]`). Or keep admins in the database with a Settings page, as local mode already does. At minimum, the deploy should read the running container's values and refuse to change them unless a flag says so.
- **Known:** none.

### prac-config-8 - A redeploy with different secret values replaces the running ones without a check: fleet-wide 401

- **Severity:** high
- **Confidence:** CONFIRMED (no comparison exists in the deploy)
- **Where:** server/install_dashboard_app.py:3116-3130 (`require_env` only), :2467, :6088-6104; docs/INSTALL.md:280-281 ("Generate each with `openssl rand -hex 24`")
- **What:** The deploy needs `DASH_SESSION_SECRET`, `DASH_REPORT_TOKEN`, `SYNCTHING_API_KEY` and `BROLL_INGEST_TOKEN` in the shell, checks only that they are present and strong, and writes them over whatever the NAS holds. It never reads the running app's values to confirm they match. The operator's vault is the only copy of record, and INSTALL's instruction to generate them sits one paragraph from "must stay stable across deploys".
- **Scenario:** The vendor runs ten customers' deploys from one terminal and exports customer B's secrets while `--site` points at customer A. Or a new operator re-generates the values on a fresh machine. Customer A's every companion 401s on report and identity, Syncthing calls 403, and the b-roll indexer's writes fail, all at once and with a green deploy transcript.
- **Recommendation:** Before `up`, read the current secret values from the running app (TrueNAS app config / Synology `.env`) and refuse any change unless `--rotate-secret NAME` is passed. When the env is empty, fall back to the existing values, so a redeploy needs no secrets in the shell at all. That also removes most of SECRETS.md's burden.
- **Known:** none (DASH-2 covers rotation on purpose, not by accident).

### prac-config-9 - Keys documented and exampled as site.toml settings that the deploy never reads

- **Severity:** medium
- **Confidence:** CONFIRMED
- **Where:** site.example.toml:336-358 (`ai_cli_auto_update = false`); server/install_dashboard_app.py:5285-5297 (projects youtube_download, youtube_unblock, ai_cli_providers, auto_update only); docs/CONFIG.md §`[telemetry]` (:140-142 admits it), §`[indexer]` (:171-175)
- **What:** `[features] ai_cli_auto_update` sits in the example's `[features]` block next to four keys that work, but no deploy code projects it (`DASH_SITE_AI_CLI_AUTO_UPDATE` appears nowhere in `server/`). `[telemetry]` (the legal opt-out switches) and `[indexer] model_tier` are documented as `site.toml` tables, but the deploy ignores both. They take effect only if the file is pasted into Settings → Import.
- **Scenario:** A customer sets `ai_cli_auto_update = true`, redeploys, and the CLI is never updated, so Timeline Cards refuses a new model. A customer's DPO sets `[telemetry] resolve_project = false` in `site.toml` as instructed, the deploy succeeds, and project names keep being collected. That is a privacy commitment silently not honoured.
- **Recommendation:** Project all three in `site_env()`, or remove them from the `site.toml` schema and say "Settings only". Add a deploy-side check that warns on any `site.toml` key the deploy does not consume.
- **Known:** CONFIG.md records the telemetry gap as deferred ("server/ was out of scope on 2026-09-25"); no KNOWN_BUGS entry.

### prac-config-10 - `[tree] projects_dir` is offered as a choice; the server scripts obey it and the product refuses it

- **Severity:** medium
- **Confidence:** CONFIRMED
- **Where:** site.example.toml:85-89; server/common.py:199-200; server/install_dashboard_app.py:1127, :2394; dashboard/src/ccsync_dashboard/settings.py:78-102; docs/CONFIG.md:50
- **What:** The example presents `projects_dir = "Projects"` as "The subdirectory under the tree root that holds projects". CONFIG.md says it is fixed and refused (SYS-20). The dashboard refuses a non-default value, but `server/common.py` accepts any value, so `setup_tree.py` and the deploy's mounts build `<tree>/<value>` without complaint.
- **Scenario:** A customer whose house style is `Jobs/` sets it. `setup_tree.py` creates `Jobs/`, the dashboard's projects mount points there, and every companion lane, the fixer and the manifest look in `Projects/`. The result is a tree the fleet syncs nothing from, which is the silent failure SYS-20 was meant to end.
- **Recommendation:** Refuse any value other than `Projects` in `server/common.py` with the SYS-20 sentence, and remove the key from the example (or comment it out with "fixed").
- **Known:** SYS-20 (fixed for the dashboard side only).

### prac-config-11 - Image defaults and deploy notes steer a customer to the wrong image and the source-checkout mode

- **Severity:** medium
- **Confidence:** CONFIRMED
- **Where:** server/install_dashboard_app.py:1621-1628 (the ":1 does not exist yet ... use :edge" note, measured 2026-08-18), :1428; site.example.toml:410-446 (`mode` default `bind`, NOTE about `:1`); docs/CONFIG.md:186-187; .github/workflows/image.yml:162 (pushes `:1` on every `v*` tag; tags v0.6.1..v0.7.44 exist)
- **What:** `:1` has been pushed by every `v*` tag since, yet every image-mode deploy on the default prints that it does not exist and to use `:edge`, the floating build of every push to main. The default `mode = "bind"` ships code trees from the operator's own checkout of the source repo over SFTP, while the vendor fleet and the CI pipeline run `image`. A customer is steered either to unreleased code or to needing the whole source tree.
- **Scenario:** A customer's installer follows the printed NOTE, switches to `:edge`, and runs whatever was merged that afternoon. Or they stay on `bind` and every update needs a repo checkout plus a redeploy.
- **Recommendation:** Delete the stale note. Make `image` the default for new sites and pin `:1` or a vendor-published digest. Keep `bind` as a documented vendor/dev mode.
- **Known:** none.

### prac-config-12 - Send to Resolve works from one address only, while the deploy publishes the dashboard on two or three

- **Severity:** medium
- **Confidence:** CONFIRMED (code); the 403 is what CLAUDE.md and LOOPBACK_API.md describe
- **Where:** companion/src/ccsync_companion/loopback_guard.py:205-248 (`allowed_origins` = `dashboard_url` from config and manifest plus per-machine `loopback_extra_origins`); site.example.toml:133-141 (`dashboard_url` plus `bind_lan` plus `bind_tailnet`); docs/CONFIG.md (no `loopback_extra_origins` row); companion/src/ccsync_companion/settings_window.py (no field)
- **What:** The stack listens on the LAN address, the tailnet address and (behind Serve) a `*.ts.net` name. The loopback guard allows only the single `dashboard_url` host. An editor who opens the dashboard by any other address gets a 403 on every Send to Resolve / music send. The only fix is a per-machine `loopback_extra_origins` list that appears in no doc table and has no UI.
- **Scenario:** An in-office editor bookmarks `http://192.168.0.10:8480` because it is faster than the tailnet. B-roll "Send to Resolve" fails with an origin refusal that only the companion log explains, and support has to remote in and hand-edit `config.toml`.
- **Recommendation:** Publish every origin the site serves on (`dashboard_url`, `bind_lan:port`, `bind_tailnet:port`, the Serve name) in the manifest as `dashboard_origins`, and allow-list that. Alternatively, have the dashboard redirect any non-canonical Host to `dashboard_url`.
- **Known:** none (LOOPBACK_API.md documents the single-origin rule, not this case).

### prac-config-13 - 147 companion keys, 6 in the settings window, 2 settable remotely: vendor support means remote shells

- **Severity:** medium
- **Confidence:** CONFIRMED
- **Where:** companion/src/ccsync_companion/config.py (DEFAULTS: 147 keys; MODE_PROFILES :904-915); companion/src/ccsync_companion/settings_window.py (touches `dashboard_url`, `mode`, `fixer_dry_run`, `jobs_enabled`, `jobs_volunteer_minutes`, `ytdl_local_downloads`, plus the four privacy switches); dashboard/src/ccsync_dashboard/db.py:13233 (`MACHINE_SETTING_KEYS = ("jobs_enabled", "jobs_kinds")`); docs/CONFIG.md:818 ("The base rig needs this"), :594-686 (`remote_down` recipe), :850-862 (jobs paths), :899-902 (`cards_agent`)
- **What:** Several features are documented as working only after a hand edit of `~/.ccsync/config.toml` plus a restart on the right machine, sometimes together with an rclone.conf stanza and `rclone obscure`. Examples: the base rig's `broll_ingest_staging_dir` (without it every original crosses SMB twice, and the `base` profile does not set it), `remote_down` / `remote_down_root`, `jobs_whisper_python` / `jobs_mulcam_pipeline` / `jobs_vault_root` / `jobs_media_root`, `cards_agent`, `loopback_extra_origins`, `ffmpeg_path`, `library_db_*`. None is in the tray settings, the setup wizard, or the dashboard's per-computer ask.
- **Scenario:** A customer asks the vendor to put one remote editor on the faster download route, or to make the base rig take whisper jobs. Each request is a remote-desktop session, a text editor, a password typed into `rclone obscure`, and a companion restart. Across ten customers that is the support load.
- **Recommendation:** Put the base-rig defaults into `MODE_PROFILES["base"]` (local staging dir). Extend `MACHINE_SETTING_KEYS` and the settings window with the per-machine paths a feature needs (jobs roots, cards_agent, remote_down with a dashboard-pushed rclone stanza). For each documented hand edit, either a UI or a dashboard ask should exist before launch.
- **Known:** none.

### prac-config-14 - Docs and examples a customer reads carry stale, wrong or vendor-only values

- **Severity:** low
- **Confidence:** CONFIRMED
- **Where:** site.example.toml:240-242 (`canonical_prefix` "Hardcoded to P: by decision (2026-07-26)"; CONFIG.md:96 says that has been false since 2026-08-17); docs/INSTALL.md:88 (`cd resolve-remote-sync`; the repo is `ccsync`); docs/CONFIG.md:853 (`C:\Users\alex\tools\whisper\...` "On creator-1"); docs/INSTALL.md:113-115 + server/check_health.py:227 (`[stack] project_server`, default true, missing from site.example.toml and CONFIG.md, so a site without a Resolve Project Server gets a permanent health FAIL); site.example.toml:449-515 (`[timeline_cards]` example points at `E:\Projects\Editing\Resolve\MulticamPipeline`, `FF5`, `/mnt/tank/TheCreatorsPool`: a separate vendor repo a customer does not have); docs/CONFIG.md:343 (`TRUENAS_*` "honoured for one release", still read); companion `mode` is `editor`/`base` in config and CONFIG.md and `WIRED TO THE SERVER`/`REMOTE EDITOR` in the settings window; env vars read by the dashboard but in no doc table: `DASH_RELEASE_SOAK_MINUTES`, `DASH_RELEASE_FEED_SIG_URL`, `DASH_SENTRY_DSN`, `DASH_COLLECTOR_WATCHDOG_SECONDS`, `DASH_COLLECTOR_WEDGED_SECONDS`, `DASH_INTERVAL_ALERTS`, `DASH_INTERVAL_INVARIANTS`, `DASH_ALERTS_SMTP_PASSWORD`, `DASH_LOG_DIR`, `DASH_CRASH_DIR`
- **What:** Each one is small, but together they are the reference a customer's admin or a reseller works from, and several (project_server, the Cards block, the personal path) send a stranger down a wrong path.
- **Scenario:** A customer without a Resolve Project Server runs Step 8's `check_health.py` and gets a FAIL whose opt-out key exists nowhere in the schema they were told to copy.
- **Recommendation:** Add `project_server` to `site.example.toml` and CONFIG.md (and consider defaulting it to false). Fix the stale lines. Mark `[timeline_cards]` "vendor fleet only / not available to customers yet". Add a doc-coverage test like the env-key one that fails on a `DASH_*` read with no CONFIG.md row. Use the UI's WIRED/REMOTE vocabulary in the docs.
- **Known:** none.

### prac-config-15 - Customer-specific defaults still reach a new customer's deploy

- **Severity:** low
- **Confidence:** CONFIRMED
- **Where:** server/install_dashboard_app.py:2157-2183 (`LEGACY_BROLL_CREATORS_SHARES = "mofa-disaster"` when the manifest has no `[broll]` table; INSTALL.md's "minimum you must fill in" never mentions `[broll]`); broll/web/app/config.py:206 and CONFIG.md:104/:530 (`archive_creators_dir` defaults to `Creators_Club`); dashboard/src/ccsync_dashboard/nas/truenas.py:44 (`HOME_PARENT = "/mnt/tank/TheCreatorsPool/homes"` fallback); site.example.toml:76 (`tree_name = "Creators_Club"` as the example value)
- **What:** CLAUDE.md's "No customer's name in code" rule still has these exceptions. A customer who writes a minimal `site.toml` (no `[broll]` table) gets the vendor's project name as their own-footage share. A new customer's own shoots are ingested under a `Creators_Club` folder in their own archive unless they find `archive_creators_dir`.
- **Scenario:** A second studio's editors drop their shoot on the b-roll page and find it filed under "Creators_Club" in their archive. The folder name is visible over SMB and in every Resolve clip path from then on.
- **Recommendation:** Add `[broll] creators_shares = "mofa-disaster"` to the vendor's own `site.toml` and delete the legacy branch. Make `archive_creators_dir` default to `org_short` / `org_name` (slugified) for sites with no existing archive. Change the example's `tree_name` to a neutral value.
- **Known:** product-surface-3 (2026-08-21) introduced the transitional exception "and it expires"; not yet expired.

### prac-config-16 - Three boolean grammars, and site.toml typos fall back silently

- **Severity:** low
- **Confidence:** CONFIRMED
- **Where:** server/common.py:144-150 (`site_bool`: an unrecognised value returns the default, no warning); docs/CONFIG.md:356-368 (feature env `"1"`-only, telemetry env `"0"`-only); docs/CONFIG.md:761 (companion wrong-typed value reads as off)
- **What:** `site.toml` takes true/false/yes/on, the dashboard environment takes `"1"` only for features and `"0"` only for telemetry, and the companion reads wrong types as off. In `site.toml` a typo (`project_server = "flase"`, `youtube_download = "ture"`) is silently the default. The per-key direction is deliberate, but the operator sees none of it.
- **Scenario:** `auto_update = "True "` with a trailing space stays off, and the customer believes their fleet updates itself.
- **Recommendation:** Have `site_bool` print a warning naming the key and the unparsed value. Have the deploy echo the effective value of every `[features]` key it projects.
- **Known:** none.
