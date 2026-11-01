# Pre-launch practicality pass, lens `prac-docs`: documentation accuracy and fitness

Hunter: prac-docs, 2026-10-06, against HEAD 08b40eb plus the uncommitted working tree. Read-only; nothing was changed except this file.

**What I covered.** I read these docs in full or close to it: `docs/README.md` (the index), `docs/INSTALL.md`, `docs/HOW_IT_WORKS.md`, `docs/EDITOR_SETUP.md`, `installer/START_HERE.md` (first 100 lines), `docs/APPLIANCE_INSTALL.md` (status sections), `docs/PRODUCT_REPO.md` and `tools/make_product_repo.ps1` (withheld list and markers), and `docs/RELEASE_PATHWAYS.md` (top). I read these selectively: `docs/SERVER.md` (onboarding, publishing, the studio-specific section), `docs/CONFIG.md` (env and companion tables), `docs/API.md` (credentials, gate, route tables), `docs/RELEASE_FEED.md` §1-2, `docs/ARCHITECTURE.md` (spot-checks), the retention tables in `docs/legal/TELEMETRY.md` and `PRIVACY.md`, and the `COMMERCIAL_READINESS.md` status lines.

I checked about 45 concrete claims against the code. Most matched:
- every server script flag in INSTALL and SERVER;
- the tray menu labels and the Settings window sections;
- the Settings navigation names;
- the defaults for report interval, rotation turn, trash, journal, sessions and snapshots;
- the legal retention constants;
- `DASH_*` names used in INSTALL;
- `/login?local=1`, and where the fleet halt lives.

The mismatches are the findings below. I also probed three things directly:
- the companion `DEFAULTS` against the CONFIG.md companion table;
- `DASH_*` names in the code against CONFIG.md;
- tenant-marker counts in the shippable tree.

**What I did not cover.** I did not read `SERVER-SYNOLOGY.md`, `TENANCY.md`, `SECRETS.md`, `BACKUP_RESTORE.md`, `SYNC_SAFETY.md` or the component READMEs end to end. I sampled API.md routes but did not verify request and response shapes field by field.

---

### prac-docs-1 - INSTALL.md tells a customer to make their own release key, which locks them out of the vendor's builds

- **Severity:** high
- **Confidence:** CONFIRMED
- **Where:** `docs/INSTALL.md` Step 6 and the §3 secrets table (`DASH_RELEASE_PUBKEYS`); `server/install_dashboard_app.py:1651-1660` (refusal text "Fix: $env:DASH_RELEASE_PUBKEYS = python tools/release_key.py pubkey"); `tools/release_key.py:285` (pubkey is derived from the LOCAL private key); `companion/src/ccsync_companion/release_pubkey.py:53` (one baked vendor key); `site.example.toml:244-262` (`[releases] feed_url`, unset by default).
- **What:** Step 6 of INSTALL is the "start here" guide. It tells the customer to:
  - run `release_key.py new`;
  - set `DASH_RELEASE_PUBKEYS` to the public half of their own key;
  - `bake` that key into the companion.

  Nowhere does INSTALL mention `[releases] feed_url`, the vendor feed, or the vendor's public key. The deploy script gives the same advice in its own refusal text.
- **Scenario:** A new customer admin follows INSTALL exactly, so `DASH_RELEASE_PUBKEYS` holds their own key and `feed_url` is blank. Two things then break:
  - Every record in the vendor feed is refused, because it was signed with the vendor key and does not verify against the customer's key.
  - Nothing reaches the fleet, because the shipped companion trusts only the baked vendor key (`GKNmk8...`), so any record the customer signs is useless to it. The customer cannot rebuild the companion with their key either, because only the vendor builds.

  The fleet sits on its install build until someone with the vendor's knowledge fixes `.env` by hand.
- **Recommendation:** Rewrite Step 6 for customers. Set `[releases] feed_url` to the vendor's channel URL, set `DASH_RELEASE_PUBKEYS` to the vendor public key (print it in the doc and on the vendor site), and pick a `policy`. Move `release_key.py new|bake` into vendor-only `RELEASE.md`. Change the refusal text in `install_dashboard_app.py` to name the vendor key, not `release_key.py pubkey`. Consider defaulting both values in the vendor build of the deploy.
- **Known:** COMMERCIAL_READINESS item 4 (signing) and item 16 (zero-touch) cover the mechanism, not this doc error. Not in KNOWN_BUGS.

### prac-docs-2 - There is no finished install path a customer can follow; the docs offer an engineering checkout or a draft

- **Severity:** high
- **Confidence:** CONFIRMED
- **Where:** `docs/INSTALL.md` §1-2 ("The base rig", `git clone <your checkout of this repo>`, `cd resolve-remote-sync`, the server scripts, `tools\release_key.py`). `docs/APPLIANCE_INSTALL.md:1-17`, `:144`, `:165` ("DRAFT", "NOT YET TRUE: Serve", "NOT YET TRUE is the doing"). `docs/README.md` "Getting started": it lists `SYNOLOGY_EASY_INSTALL.md` (a design), `ZERO_TOUCH_PLAN.md` (a plan) and `APPLIANCE_INSTALL.md` (a draft) beside INSTALL. `docs/PRODUCT_REPO.md` (the repo a customer would clone cannot currently be produced; see prac-docs-8).
- **What:** The only complete install guide assumes the reader has three things:
  - a Windows "base rig";
  - a git checkout of this repo, under its old name `resolve-remote-sync`;
  - the vendor's Python and PowerShell tooling.

  That contradicts the sales model stated everywhere else: the customer installs Tailscale plus one container, and only the vendor builds. The appliance path that matches that model is marked DRAFT. It does not publish the dashboard (no Serve), has no invite flow, publishes no companion and schedules no snapshots.
- **Scenario:** A paying customer's admin is handed the docs. They either:
  - clone a repo whose customer-facing export does not exist and run vendor tooling (and hit prac-docs-1 and prac-docs-3), or
  - follow APPLIANCE_INSTALL, whose own header says nobody but the author has run it.

  In practice every install needs the vendor present.
- **Recommendation:** Decide the v1 install story before launch and say it in one place:
  - **(a)** "the vendor installs, the customer receives an admin guide", or
  - **(b)** the appliance path, finished and run end to end by someone who is not the author.

  Write one customer runbook for that path. Mark INSTALL.md as the vendor or operator runbook. Fix `cd resolve-remote-sync` to `ccsync`. Move ZERO_TOUCH_PLAN, SYNOLOGY_EASY_INSTALL and the draft out of "Getting started".
- **Known:** COMMERCIAL_READINESS item 16 ("PLANNED, nothing built" as of 08-17; WP A/D landed since). Open.

### prac-docs-3 - INSTALL.md never installs the server scripts' Python dependencies, so Step 3 fails on a fresh machine

- **Severity:** medium
- **Confidence:** CONFIRMED
- **Where:** `docs/INSTALL.md` §1 "The base rig" ("Python 3.11+ and git") and §2 Step 3. `server/common.py:32` (`import urllib3` at module top), `:1158` (paramiko) and `:1345` (requests). `server/requirements.txt` and `server/requirements.lock` exist, but no doc names them (grep for `pip install` and `requirements` in INSTALL, SERVER, SERVER-SYNOLOGY and `server/README.md` finds nothing).
- **What:** Every server script imports `common`, which imports `urllib3` at its top line and paramiko and requests lazily. INSTALL lists only Python and git.
- **Scenario:** A new operator on a clean Windows machine with python.org Python 3.11 runs `python server/install_syncthing_app.py --site site.toml --dry-run`. It dies with `ModuleNotFoundError: No module named 'urllib3'` before printing anything useful. CLAUDE.md's workaround (borrow `dashboard\.venv`) is internal knowledge.
- **Recommendation:** Add this step to INSTALL §1: `python -m venv .venv-server && .venv-server\Scripts\pip install --require-hashes -r server/requirements.lock`, then use that interpreter in every Step 3-8 command. Alternatively make `common.py` fail with a one-line "run pip install -r server/requirements.lock" message.
- **Known:** none.

### prac-docs-4 - The Synology footage-truncation setting is protected only by a comment, and the template ships the unsafe value

- **Severity:** high
- **Confidence:** CONFIRMED
- **Where:**
  - `site.example.toml:154-155`: `sftp_chunk_size = "255Ki"  # Synology MUST set "64Ki"` and `sftp_concurrency = 64`, both uncommented.
  - `docs/INSTALL.md` Step 1 says to copy the template, and §6 has one checklist line about the setting.
  - `server/backends/synology.py:43-47` holds the warning only as a docstring.
  - `server/install_dashboard_app.py:2201-2205` passes the value through as written.
  - `dashboard/src/ccsync_dashboard/settings.py:325-331` defaults to "" (the companion then uses its own 255Ki, `companion/src/ccsync_companion/config.py:277`).

  Nothing in `server/common.py` or the deploy checks this value against `[nas] kind`.
- **What:** INSTALL's first step is "copy site.example.toml". That file sets the 255Ki/64 window explicitly. The docs themselves call that window silent data loss on DSM 7.2: downloads truncate at 539,000,832 bytes and rclone reports success. The only guards are an inline comment and item 7 of a hand checklist.
- **Scenario:** A Synology customer copies the template, sets `kind = "synology"` and misses the comment. Every proxy download over about 514 MiB is silently truncated on every editor machine. The lanes report green.
- **Recommendation:**
  - Comment the two lines out in the template.
  - Derive the defaults from `[nas] kind`: synology gets `64Ki`/`16`/`shell_type none`.
  - Make `install_dashboard_app.py` refuse `kind = synology` with a chunk size above 64Ki unless an override flag is given.
  - Keep the checklist line as a confirmation, not the only guard.
- **Known:** not in KNOWN_BUGS. Spike 6 in `synology-spikes-2026-08-17.md` measured it.

### prac-docs-5 - EDITOR_SETUP.md, served in every customer's /help, is a stale editor guide that contradicts the product

- **Severity:** medium
- **Confidence:** CONFIRMED
- **Where:** `docs/EDITOR_SETUP.md`. It is shipped to the customer server by `server/install_dashboard_app.py:307` (`SHIPPED_DOCS`), `dashboard/deploy/Dockerfile:121` and `dashboard/src/ccsync_dashboard/published_docs.py:77` (REQUIRED). Specific lines:
  - §2: the whole install is CLI bootstrap, the wizard is never mentioned, and the `-DashboardToken <token>` example puts the credential on argv.
  - :94: the Mac "Installer" download is described as a `.sh`.
  - :12-13: cites the withheld `COMMERCIAL_READINESS.md`.
  - :20 and :244: "Your TrueNAS username".
  - :137: "Do not map T:".
  - :180: "Settings -> Assignments".
  - :476 and :481: the tray's "Scan whole project" and "Consolidate pre-existing project".
  - :492-494: "renames and deletes there DO propagate".
- **What:** The document an editor finds at `/help` describes an older product:
  - It never mentions `onboard.exe` or the Mac `.app` wizard. Compare `installer/START_HERE.md:10`, and `tools/build_onboard_macos.sh:609`, which serves a `.zip`.
  - It tells the editor to pass the fleet token on the command line. `installer/windows_bootstrap.ps1:227-236` says that leaks the token to every process on the machine.
  - It sends editors to tray items that moved to Settings > ADVANCED (the CR-88 layout).
  - It says folder-sync deletes propagate. HOW_IT_WORKS §4 and §8.4 and the server's `ignoreDelete` say the opposite.
  - It names one studio's history (the `T:` collision) and a NAS brand that half the market does not run.
- **Scenario:** A Synology customer's editor opens Help and runs the bootstrap by hand with the token on argv. They then look for "Consolidate" in a tray that no longer has it, and believe that deleting a music cue removes it for everyone.
- **Recommendation:** Rewrite EDITOR_SETUP wizard-first: Installer, then the wizard pages, then sign in, then approval, then tick. Move the CLI bootstrap to an appendix that uses the environment-variable form (`CCSYNC_DASHBOARD_TOKEN`). Replace "TrueNAS username" with "your CC Sync username". Drop the `T:` and COMMERCIAL_READINESS lines. Fix the menu locations and the delete semantics. Add a test that scans the shipped docs for "Assignments", for tray items that do not exist, and for withheld doc names.
- **Known:** none (dash-mounts-ui-b-4 made it shipped; nothing reviewed its content).

### prac-docs-6 - HOW_IT_WORKS.md, the customer-facing explainer, states several things the code does not do

- **Severity:** medium
- **Confidence:** CONFIRMED
- **Where:** `docs/HOW_IT_WORKS.md`:
  - :201 and :578: "the NAS keeps 30 days of old versions".
  - :789-791: identity token "valid for 30 days", and "the admin can revoke one computer's access without touching the others".
  - :463: "(on Settings > Health instead, where the new terminal look is switched on for Settings)".
  - :327: "the Assignments grid".
  - :~ §14: "(section 6.6)" for the grade swap, which is in §6.7.
  - §5 step 3: "four-step wizard".

  The code it contradicts:
  - Versioning is staggered with `maxAge: "31536000"` (365 days) in `server/setup_syncthing_folder.py:458-463` and `dashboard/src/ccsync_dashboard/provision.py:285-288` and `:505-508`.
  - `dashboard/src/ccsync_dashboard/auth.py:376-391`: the identity token never expires, has no server row, and is revoked per ACCOUNT (or per editor report token).
  - `docs/legal/PRIVACY.md:315` already says "Identity tokens do not expire".
  - CLAUDE.md: the terminal look is the only look.
  - `onboarding/onboard.py:1123` (`show_privacy`): the wizard has a reporting-switches page, so it is not four steps.
- **What:** This is the document the product links to from every page and from the tray's HELP. It contradicts the legal privacy policy on token lifetime. It misstates the version-retention promise. It also promises a per-computer revocation that does not exist.
- **Scenario:** A customer's admin loses a laptop. They read §13, look for "revoke one computer" and find no such control. The only real lever is disabling the whole account, or revoking that person's report token. Separately, a customer's DPO reads §13 against PRIVACY.md and finds two different token lifetimes.
- **Recommendation:** Fix each line:
  - "keeps old versions for up to a year, thinning over time";
  - "does not expire; an admin takes a computer's access away by disabling the person or revoking their report token";
  - remove the terminal-look aside;
  - "Sync plans grid";
  - §6.7;
  - name the privacy page.

  Add the identity-token and versioning statements to whatever test pins HOW_IT_WORKS to code. If per-computer revocation is wanted, it is a feature: machine-bound tokens.
- **Known:** CR-86 changed the token lifetime; this doc was not updated.

### prac-docs-7 - Admins get three different editor-onboarding procedures, and none covers the per-editor fleet key

- **Severity:** medium
- **Confidence:** CONFIRMED
- **Where:**
  - `docs/INSTALL.md` §2 Step 7: Users page, or `setup_editor_account.py`.
  - `docs/SERVER.md:411-470`. Step 1 has the editor generate a keypair. Step 3 has the admin "set a known password". Step 4 has them "send the editor ... `dashboard_token`". Step 6 uses `accept_device.py`.
  - `docs/EDITOR_SETUP.md` §0 and §3.5: "your dashboard token" from the admin.

  Against the code:
  - `dashboard/src/ccsync_dashboard/api.py:2436-2456`: `/verify` hands the shared token to the wizard and stops once it is retired.
  - `onboarding/steps.py:1034-1066` and `onboarding/onboard.py:1265-1280`: the wizard then asks for a `cce1.` key and finishes "NOT READY" without one.
  - `onboarding/onboard.py:1555` (`_offer_ssh_key`): the wizard generates and submits the SSH key itself.
- **What:**
  - Today the wizard fetches the shared report token itself, so "send the editor the dashboard token" is obsolete.
  - INSTALL §5 recommends retiring the shared token. Once that is done, every new editor needs a per-editor key minted on Settings > Users and pasted into the wizard. No onboarding procedure says so.
  - SERVER.md's "generate a keypair and send me the .pub" is also obsolete: the wizard does it.
- **Scenario:** A careful admin retires the shared token as INSTALL advises, then onboards a new editor from INSTALL Step 7. The wizard asks for a "report token" nobody mentioned. The editor leaves it blank, and the finish page says NOT READY. The admin has no doc that tells them what to mint or where.
- **Recommendation:** Write one onboarding checklist in INSTALL (or the admin guide) and point the other two docs at it:
  1. Create the account.
  2. Set a password.
  3. If the shared token is retired, mint a report token (Users > report tokens) and send it.
  4. Editor runs the Installer.
  5. Approve the device and the SSH key in Users.
  6. Tick projects.

  Delete the obsolete steps from SERVER.md and EDITOR_SETUP.
- **Known:** none.

### prac-docs-8 - The customer-facing "product repo" cannot be produced, and its withheld list misses most internal documents

- **Severity:** high
- **Confidence:** CONFIRMED
- **Where:**
  - `tools/make_product_repo.ps1:144-184` (`$TenantFiles` / `$TenantGlobs`) and `:382-386` (refusal on any marker).
  - `docs/PRODUCT_REPO.md`.
  - `docs/COMMERCIAL_READINESS.md:271` ("the product-repo squash (a recipe, not run)").
  - `docs/SERVER.md:322-343` ("One line this studio owes", with a customer project slug).
  - `docs/TRANSFER_SPEED.md`, `docs/CARDS_TWO_PROJECTS.md`, `docs/MULTI_MACHINE_PLAN.md`, `docs/SERVER_TRIAGE_AGENT.md` and `docs/README.md` (named editors).
- **What:** Probed with `git grep -c` at HEAD, with the script's own exclusions applied.

  | Marker | Hits | Files |
  |---|---|---|
  | `Creators_Club` | 909 | 185 |
  | `Creators Club` | 52 | 33 |
  | `Cablewrap` | 34 | 14 |
  | `192.168.0.102` | 21 | 11 |
  | `100.71.216.3` | 18 | 7 |

  Under `docs/` alone, outside the bug-hunt archives, "ruskin" appears 90 times in 16 files and "leso" 28 times in 12 files. So the script refuses (exit 2).

  Even with the markers cleaned, the prune list was written on 2026-08-17. It does not withhold the internal documents added since: both sweep reports and their directories, `UI_PORT_REVIEW_2026-09-25.md`, `UI_PORT_LEDGER/`, `LEGAL_GAP_FEATURES_LEDGER/`, `ACCOUNT_PAGE_FEATURES_LEDGER/`, the plans, and this review's own `docs/prelaunch-review-2026-10-06/`.

  The owner's ruling that the CC mark is the product brand conflicts with `Creators Club` being a tenant marker. The marker scan uses git `glob` pathspecs, where `*` does not cross `/`, while the prune uses `-like`, where it does. So the scan and the prune disagree on the bug-hunt directories.
- **Scenario:** INSTALL Step 1 tells the customer to `git clone <your checkout of this repo>`. Either the vendor hands over this engineering repo, which carries defect maps, another customer's identity and named editors' machines, or there is nothing to hand over.
- **Recommendation:**
  - Settle the brand question, and update `$TenantMarkers` to match.
  - Turn the withheld list into an allow-list: ship only the docs marked customer-facing (see prac-docs-9), rather than deny-listing internal ones.
  - Scrub SERVER.md's studio section and the named editors from the docs that would ship.
  - Make the scan and the prune use the same matcher.
  - Run the export once from a tag before the first sale, and hand a customer only its output.
- **Known:** COMMERCIAL_READINESS item 10 (product repo "a recipe, not run"). Still open.

### prac-docs-9 - The docs index mixes customer, operator and vendor-internal material, with stale status lines

- **Severity:** medium
- **Confidence:** CONFIRMED
- **Where:** `docs/README.md`.
  - "Getting started" lists a design, a plan and a draft (prac-docs-2).
  - "Operating it" lists:
    - `UI_REDESIGN_PORT_PLAN.md`, `UI_PORT_REVIEW_2026-09-25.md` ("Review only, nothing fixed");
    - `LEGAL_GAP_FEATURES_PLAN.md`, `ACCOUNT_PAGE_FEATURES.md` (builder groups);
    - `TRANSFER_SPEED.md` ("measured ... from Ruskin's PC");
    - `PROJECTS_CLEANUP_PLAN.md`, which is about the owner's `E:\Projects` tree.
  - Stale statuses:
    - `PROJECTS_CLEANUP_PLAN.md` "A plan, not yet done", while the repo already sits at `E:\Projects\Editing\ccsync`;
    - `USABILITY_RESILIENCE_SWEEP_2026-09-03.md` "nothing built yet", although waves 0-5 were built 2026-09-04;
    - `YTDL_RESILIENCE_PLAN.md` "unshipped", although it shipped as dashboard 0.7.12;
    - `bug-hunt-2026-08-21.md` "unshipped".
  - `COMMERCIAL_READINESS.md:3` says "not maintained".
- **What:** There is no audience column. A customer, an operator and the vendor all land on the same list, where one-studio plans and internal reviews sit beside the install guide. `tools/tests/test_docs_index.py` pins that every doc is listed, not that it is filed correctly or that its status is current.
- **Scenario:** A customer's admin opens the index and reads the "Operating it" section. They find a UI review listing 3 high defects "nothing fixed", and a plan about the vendor's own folder tidy-up.
- **Recommendation:** Split the index into **Customer** (HOW_IT_WORKS, START_HERE, the admin guide and the legal docs), **Operator** (INSTALL, SERVER*, CONFIG, API, BACKUP, SYNC_SAFETY) and **Vendor internal** (everything else). Feed the Customer set into prac-docs-8's allow-list. Drop status claims from index lines, or have the test check a `Status:` header in each doc.
- **Known:** none.

### prac-docs-10 - CONFIG.md claims to list every key but misses about 20 dashboard env vars and 22 companion keys

- **Severity:** low
- **Confidence:** CONFIRMED
- **Where:** `docs/README.md` ("Every configuration key") and `docs/CONFIG.md` §2 and §3. Probed by diffing `"DASH_*"` literals in `dashboard/src`, `broll/web`, `music/web` and `ytdl/web` against CONFIG.md, and companion `config.DEFAULTS` (147 keys) against the backticked names in CONFIG.md §3.
- **What:**
  - **Undocumented dashboard env vars:**
    - Operator-relevant: `DASH_SESSION_SECRET_PREVIOUS` (only in SECRETS.md), `DASH_OIDC_ADMIN_VALUES`, `DASH_LOG_DIR`, `DASH_SENTRY_DSN`, `DASH_RELEASE_FEED_SIG_URL`, `DASH_RELEASE_SOAK_MINUTES`, `DASH_NAS_SSH_HOSTKEY`, `DASH_NAS_SSH_KEY_PROBE`, `DASH_ALERTS_SMTP_PASSWORD`.
    - Internal tuning and paths: `DASH_COLLECTOR_WATCHDOG_SECONDS`, `DASH_COLLECTOR_WEDGED_SECONDS`, `DASH_INTERVAL_ALERTS`, `DASH_INTERVAL_INVARIANTS`, `DASH_CRASH_DIR`, `DASH_SNAPSHOT_DIR`, `DASH_SNAPSHOT_PROJECTS_SUBPATH`, `DASH_TREE_DIR`, `DASH_CONTAINER_NAME`, `DASH_HELP_DOC`, `DASH_HELP_DOCS_ROOT`, `DASH_EULA_DOC`.
  - **Undocumented companion keys:** `library_db_host/name/user/password/port` and `library_walk` (EDITOR_SETUP §4 tells editors to set these), `drive_reminder_minutes` (cited in CLAUDE.md), `supervise`, `supervise_syncthing`, `lane_b_min_free_bytes`, `lane_b_idle_recheck_seconds`, `proxy_gen_free_space_floor_pct`, `dashboard_report_interval_active`, `express_*`, `keep_awake_max_hold_seconds`, `order_by_down`, `scan_interval_down`, `resolve_scripting_warning_interval`, `resolve_factory_luts_extra`, `ytdlp_max_age_days`, `broll_ingest_staging_retention_days`.
- **Scenario:** An OIDC customer whose IdP sends groups rather than usernames has no documented way to map admins. A support engineer told to "set `library_db_host`" finds no reference entry for it.
- **Recommendation:** Add the missing rows. Add a test that diffs `config.DEFAULTS` and the dashboard's `DASH_*` reads against CONFIG.md, with an explicit "internal, not a setting" list for the tuning knobs.
- **Known:** none.

### prac-docs-11 - "Tailscale Serve is the only supported TLS path", yet the TrueNAS runbook never sets it up

- **Severity:** medium
- **Confidence:** CONFIRMED
- **Where:** `docs/INSTALL.md:41-48`. `docs/SERVER.md` mentions Serve once (:265), and only in the trusted-proxies explanation. Only `docs/SERVER-SYNOLOGY.md:213-241` has the `tailscale serve` command and `DASH_COOKIE_SECURE=1`. `docs/CONFIG.md:70` (TrueNAS binds LAN and tailnet addresses directly).
- **What:** INSTALL declares Serve the only TLS publish path. The TrueNAS runbook, which is the primary platform, deploys on `bind_lan`/`bind_tailnet` over plain http and never says how to put Serve in front, or that `DASH_COOKIE_SECURE=1` follows.
- **Scenario:** A TrueNAS customer finishes the install with the dashboard and logins on plain http. They have no instructions to reach the configuration INSTALL calls the supported one, and no statement that plain http over the tailnet is acceptable.
- **Recommendation:** Do one of two things:
  - Add a "Publishing with Tailscale Serve on TrueNAS" section to SERVER.md: the command, the cookie flag, `--recreate`, and the `dashboard_url` change, with the loopback-origin consequence for companions.
  - Or state in INSTALL that a tailnet-only plain-http dashboard is the supported TrueNAS default, and why that is acceptable.
- **Known:** COMMERCIAL_READINESS item 6 "set `DASH_COOKIE_SECURE=1` ... on the Serve-published sites" (open, operator step).

### prac-docs-12 - Customer-facing documents a commercial product needs are missing

- **Severity:** medium
- **Confidence:** CONFIRMED
- **Where:** repo root and `docs/`. `git ls-files` has no root `README.md` and no `CHANGELOG*`. The release feed's only per-build text is a one-line `notes` (`docs/RELEASE_FEED.md` §2.1). HOW_IT_WORKS ends support at "send diagnostics to your admin". `docs/RELEASE_PATHWAYS.md` is written for "Alex, at the terminal" and "Claude on this rig". One public feed serves every customer (`tools/publish_latest.py`, `FEED_REPO`).
- **What:** Not written anywhere:
  - **(a)** A root README: what this is, the licence, where to start.
  - **(b)** Customer release notes or a changelog an admin can read before pressing Publish, or before choosing `policy = current`.
  - **(c)** A customer admin guide for day 2: users and report tokens, approving devices, packages and the feed, alerts and SMTP, the health page, restores. Today this is scattered across HOW_IT_WORKS §7, SERVER.md, SELF_DIAGNOSIS.md and SYNC_SAFETY.md, which are written for the vendor.
  - **(d)** A requirements and sizing sheet: NAS RAM and CPU for the container, ports, bandwidth per editor (TRANSFER_SPEED is a one-site measurement), Resolve versions supported.
  - **(e)** A support and escalation path from the customer admin to the vendor: what to send and where.
  - **(f)** A vendor runbook for N customers. It should cover a staged rollout, because a `policy = current` customer takes a bad build the moment it is made current. It should also cover a per-customer onboarding checklist and feature enablement (`youtube_download` "by agreement").
- **Scenario:** The vendor signs a third customer:
  - a broken build goes `current` on the single feed and reaches every `current`-policy fleet at once;
  - the customer's admin cannot tell what a Publish button will change;
  - when something breaks, the docs stop at "tell your admin".
- **Recommendation:** Write (a)-(e) as customer documents and (f) as a vendor runbook. For (b), keep a `CHANGELOG.md` per component, emitted into the feed's `notes`. For (f), add a beta channel (`channel` is already in the schema) or a soak period before `current`.
- **Known:** COMMERCIAL_READINESS item 13 ("docs for strangers") is marked done, but these were not in its scope.

### prac-docs-13 - SERVER.md, the TrueNAS customer runbook, carries this studio's own operations and steps a customer cannot run

- **Severity:** low
- **Confidence:** CONFIRMED
- **Where:**
  - `docs/SERVER.md:322-343`: "One line this studio owes its `site.toml`", which carries a customer project slug.
  - `:849-898`: "Publishing a companion update" via `build_editor_package.ps1 -RebuildExe -Publish`, a build that only the vendor can do.
  - `:851`: "nothing updates silently". `site.toml [features] auto_update` and Settings > Packages [ UPDATE NOW ] both exist (HOW_IT_WORKS §12).
  - `:477-550`: "Onboarding a new project" is numbered 1, 2, 4, 5.
  - `:514-515`: examples use this studio's series names.
- **What:** The runbook a customer's operator follows mixes vendor build steps, one studio's migration debts and stale update semantics into the platform instructions.
- **Scenario:** A customer's operator tries to "publish a companion update" by building one. Separately, they read "nothing updates silently" and do not know auto-update exists.
- **Recommendation:**
  - Move the studio section to the private ops notes.
  - Replace "Publishing a companion update" with "Taking a vendor update from the feed", and keep the build steps in RELEASE.md.
  - Correct the update semantics.
  - Renumber the project steps.
  - Use neutral examples.
- **Known:** none.
