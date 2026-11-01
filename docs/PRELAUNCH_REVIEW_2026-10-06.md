# Pre-launch review 2026-10-06: the go-live checklist (all four passes, merged)

The owner asked for "every single thing that should be looked at or changed
before going live commercially". Four review passes ran on 2026-10-06 against
HEAD `08b40eb` (dashboard 0.7.73, companion 0.9.84) plus the uncommitted
working tree as it stood (alert-kind selection, the CR-356/357/358 companion
fixes taking the companion to 0.9.85, the CR-356 folder-ignore retirement,
`docs/ZERO_DOWNTIME_DEPLOY.md`). This file is the one list to work from. It
merges the four pass reports, removes the items that several passes found
independently, and sorts everything into what must happen before the first
sale and who has to do it.

**How the review ran.** Four passes, 56 Opus hunters in all, each hunter on
its own territory or lens. Every critical and high finding (171 of them) was
then given to an adversarial Opus verifier told to disprove it. None was
disproved; many were downgraded (real, but less severe than first claimed).
Mediums and lows were not verified; past passes refuted about 3% of theirs.
Read-only throughout: no code, test, KNOWN_BUGS.md entry or live system was
touched. Probes ran in a scratchpad against repo code only, so nothing here
was checked against the live dashboard, the NAS, the tailnet, GitHub or a
running Resolve (see section 5).

| Pass | Report | Hunters | Raw (crit / high / med / low) | Distinct after merge and verification (stop-ship / high / med / low) |
|---|---|---|---|---|
| Bugs, by code territory | [`bugs.md`](prelaunch-review-2026-10-06/bugs.md) | 22 | 175 (2 / 27 / 81 / 65) | 162 (1 / 11 / 90 / 60) |
| Resilience, by failure mode | [`resilience.md`](prelaunch-review-2026-10-06/resilience.md) | 12 | 116 (0 / 31 / 59 / 26) | 111 (0 / 5 / 80 / 26) |
| Practicality, by real person's journey | [`practicality.md`](prelaunch-review-2026-10-06/practicality.md) | 10 | 129 (2 / 41 / 66 / 20) | 99 (1 / 12 / 70 / 16) |
| Commercial, by buyer / lawyer / support desk | [`commercial.md`](prelaunch-review-2026-10-06/commercial.md) | 12 | 159 (3 / 65 / 69 / 22) | 96 (0 / 15 / 70 / 11) |
| **All four** | | **56** | **579 (7 / 164 / 275 / 133)** | **468 (2 / 43 / 310 / 113)** |

Each pass keeps its raw hunter reports in `docs/prelaunch-review-2026-10-06/<pass>/hunters/`
and a machine-readable list in `<pass>/results.json`.

**After merging across passes (this document):**
- **Stop-ship: 1** (the two per-pass stop-ships are the same defect).
- **Before the first paying customer: 58 checklist items** - 36 code items
  in six fix waves (track A), 12 owner / counsel / money decisions (track B),
  and 10 real-world proofs (track C, which are runs, not defects). The 43
  per-pass highs collapse to 38 distinct problems; a few are split into a
  code half (track A) and an owner half (track B), and one item that is
  medium in every pass (GL-25b, the downgrade floor) is pulled into a wave
  because it shares its fix.
- **Soon after launch: about 265 distinct mediums** (310 counted per pass;
  about 45 are the same problem found by two or more passes, or are folded
  into a high above). Section 4 groups them into themes and points into the
  pass reports.
- Lows (113) are not repeated here; each pass report lists them under "Polish".

**The one-sentence verdict.** The sync product itself is close; the things
that stop a sale are around it: the self-install appliance cannot complete for
a new customer, a customer cannot receive vendor updates on any documented
path, three removal paths can delete footage that never reached the server,
the trust and signing story is not yet something a buyer's security review
would pass, and the business paperwork (order form, support terms, signing
certificates, a second person who can ship a fix) does not exist yet.

Ids are cited as the pass reports give them: `bug-*` (bugs pass), `PL-RES-*`
(resilience), `PRAC-*` (practicality), `COM-H*` / `COM-M*` (commercial), with
hunter ids such as `res-dataloss-1` where a pass merged several. The `GL-*`
ids below are new and belong to this document only.

---

## 1. Cross-pass dedupe

The same defect found by several passes, merged. Severity is the highest
verified severity any pass gave it. The `GL-` column says where it lives in
this checklist; "M" means section 4 (soon after launch).

| Subject | Sources (all passes) | Severity | Here |
|---|---|---|---|
| Appliance boots in SMB login mode: no first admin, nobody can sign in (no `DASH_AUTH_METHOD` in the compose) | `bug-server-1`; `PRAC-1` (`prac-install-1`, `prac-simplify-1`) | stop-ship | GL-00 |
| Appliance has no vendor feed URL and no vendor public key; compose comment falsely says the key is generated at first boot | `bug-server-2` (part); `PL-RES-35` (`res-upgrade-4`); `PRAC-2` (part: `prac-install-4`, `prac-config-4`, `prac-errors-1`); `COM-H9` (`com-release-4`, `com-ops-at-scale-1`) | high | GL-02 |
| INSTALL.md Step 6 has the customer mint and bake their own release key, cutting them off from the vendor feed | `PRAC-2` (`prac-docs-1`); `COM-H11` (`com-ops-at-scale-2`, `com-product-surface-7`) | high | GL-03 |
| Appliance dashboard is loopback-only; Tailscale Serve never configured; the tailnet task still turns green | `bug-server-2` (part); `PRAC-4` (`prac-install-2`) | high | GL-04 |
| Appliance never tells the dashboard where its own Syncthing is (`SYNCTHING_GUI_URL`), so the required wizard step never passes | `bug-server-2` (part); `PRAC-5` (`prac-install-3`, `prac-errors-1`) | high | GL-01 |
| Syncthing GUI is an unauthenticated admin surface (appliance: 0.0.0.0 in the tailnet netns; TrueNAS: every interface, no password) | `bug-server-3`; `PRAC-18` (`prac-install-16`) | high | GL-08 |
| Appliance Syncthing cannot write its root-owned config folder and restart-loops | `PRAC-7` (`prac-install-6`) | high | GL-05 |
| Stale customer channel: `ccsync:1` and the feed's dashboard are v0.7.44 (2026-09-11), draft EULA served, companion newer than its dashboard; shipping never moves the tag | `PRAC-9` (`prac-install-5`, `prac-config-11`); `COM-H8` (`com-release-3`, `com-ops-at-scale-3`, `com-quality-gates-1`) | high | GL-24, GL-50 |
| The `:1` image tag moves on any `v*` tag push with no test gate; actions tag-pinned; cosign check accepts any identity | `COM-H10` (`com-release-6`, `com-quality-gates-3`, `com-security-2`); `bug-dash-release-2` (+ `bug-tools-ci-1`, `-2`, `-7`); `bug-tools-ci-3` | high | GL-25 |
| One plaintext release signing key on the everyday, agent-running workstation; no revocation or compromise runbook | `bug-comp-trust-1`; `PL-RES-41` (`res-recovery-6`, `res-security-adversity-6`); `COM-H4` (`com-security-1`, `com-release-7`, `com-ops-at-scale-7`) | high | GL-17, GL-42 |
| Shared fleet token on by default plus never-expiring identity tokens: a suspended, disabled or deleted editor's computer keeps fleet access; a deleted smb/oidc editor re-registers | `bug-comp-ytdl-1` (+ `bug-ytdl-web-3`); `bug-dash-api-1` (+ `bug-dash-auth-5`); `bug-dash-auth-2` (+ `bug-dash-api-7`); `PL-RES-79` (`res-security-adversity-2`); `PRAC-35` (`prac-editor-onboard-4`, `prac-simplify-2`); `COM-H15` (part); `COM-M26` | high | GL-15 |
| Remove from this machine deletes originals younger than 120 s or with a future date (camera clock), which lane A also never uploads | `bug-sync-1`; `PL-RES-06` (`res-dataloss-3`, `res-time-scale-3`) | high | GL-12 |
| Remove from this machine on an upload-only project deletes every non-video file (WAVs, stills, docs) under a dialog saying nothing will be lost | `bug-sync-2`; `PL-RES-01` (`res-dataloss-1`) | high | GL-13 |
| TrueNAS REST API v2.0, which TrueNAS 26 removes; no version check | `COM-H2` (`com-thirdparty-tos-3`); `PL-RES-69` (`res-deps-3`) | high | GL-11, GL-46 |
| Wizard says DONE but never connects Resolve to the project server or turns on External scripting; Resolve Free / scripting None never detected, editor told to restart Resolve forever | `PRAC-11` (`prac-editor-onboard-6`, `-7`); `PL-RES-58` | high | GL-29 |
| Claude Code / Codex subscription relay (claude.ai sign-in, stored OAuth token) and the CLI-only triage agent | `COM-H1` (`com-thirdparty-tos-1`, `-2`, `com-legal-13`, `com-privacy-telemetry-3`, `com-product-surface-5`); `PRAC-80` (`prac-simplify-5`) | high | GL-31, GL-45 |
| No support contact anywhere in the product; EULA points at an order and support plan that do not exist | `COM-H12` (`com-licensing-billing-5`, `com-customer-experience-1`, `com-legal-9`); `PRAC-49` (`prac-admin-daily-3`, `prac-errors-2`, `prac-support-1`) | high | GL-34, GL-43 |
| No finished customer install path; installs are in practice vendor-performed with the customer's NAS admin password | `PRAC-3` (`prac-install-10`, `prac-docs-2`, `prac-simplify-3`, `prac-support-8`); `COM-H11`; `COM-M61` | high | GL-40 |
| Product repo export cannot be produced; withheld list misses most internal docs | `PRAC-13` (`prac-docs-8`, `prac-simplify-11`); `COM-M42` (`com-tenancy-3`) | high | GL-35 |
| NAS uid/gid assumed (Synology needs APP_UID/APP_GID by hand; TrueNAS runs as 3000:3001 unchecked) | `PRAC-8` (`prac-install-7`); `COM-M45` (`com-tenancy-6`) | high | GL-06 |
| Postgres project server: optional profile publishes a superuser with Resolve's default password on all interfaces; outside the backup story | `bug-server-8`; `PL-RES-27`; `COM-H15` (part) | high (as part of COM-H15) | GL-19 |
| Release-key "not backed up" shows a permanent red line on every customer dashboard, which holds no private key | `PL-RES-30`; `PRAC-55` | medium | GL-02 (same fix) |
| Downgrade floor is 0.0.0 on every signed record; no channel freshness check (a replayed old channel rolls fleets back) | `bug-comp-trust-2` (+ `bug-dash-release-3`); `bug-dash-release-4`; `PL-RES-40`; `COM-M33` | medium | GL-25b (with release wave) |
| `requires_dashboard` opt-in and stale; feed ordering and arch checks off | `PL-RES-36`; `COM-M51` (`com-release-5`, `com-quality-gates-2`) | medium | M (release chain) |
| A licence-version bump stops sync on every machine until each editor clicks | `PL-RES-37`; `COM-M10` | medium | M (release chain) |
| Pushed and unattended updates restart the companion in the middle of uploads, fetches and jobs | `PL-RES-38`; `PRAC-44`; related `bug-app-b-2` | medium | M (companion lifecycle) |
| yt-dlp nightly taken daily with no pin or rollback (editor machines and inside the dashboard process); notices mislabel the editor binary | `bug-comp-ytdl-5`; `bug-ytdl-web-4` (+ `bug-server-14`); `PL-RES-72`; `COM-M32`; `COM-M22` | medium | M (dependencies) |
| No browser security headers / Content-Security-Policy anywhere, public share viewer included | `bug-dash-ui-2`; `PL-RES-81`; `COM-M29` | medium | M (dashboard security) |
| Package "make current" / "roll back" routes are CSRF-exempt and skip the Origin check | `bug-dash-api-2`; `COM-M28` | medium | M (dashboard security) |
| No second factor and no step-up for admin actions | `PL-RES-85`; `COM-M25` | medium | M (dashboard security) |
| Site `dashboard_url` (admin-editable or spoofed on plain-http LAN) becomes a trusted loopback origin | `PL-RES-82`; `bug-comp-trust-5`; related `PRAC-41` | medium | M (dashboard security) |
| Triage agent: read-only scope not enforced, fleet text unfenced, whole-fleet data to the AI provider | `bug-dash-ops-4`; `PL-RES-83`; `PL-RES-84`; `COM-M14`; `COM-L6` | medium | M (and cut for v1, GL-48) |
| `publish_db.py --which music` deletes every fleet-ingested track | `bug-music-1`; `PL-RES-09` | medium | M (backups and data) |
| Closing a Cards episode leaks the engine (threads, ~128 MB) until OOM | `bug-dash-jobs-cards-4`; `PL-RES-77` | medium | M (scale; Cards cut for v1) |
| Fleet-wide owed-files backlog recomputed on every home-page poll (0.4 s now, ~6 s at 50 editors) | `PL-RES-74`; `PRAC-73` | medium | M (scale) |
| SMTP port 465 recommended but cannot work | `bug-dash-ops-6`; `PL-RES-56` | medium | M (observability) |
| Every wizard install blocks all inbound SMB on the editor's PC, no notice or opt-out | `bug-installer-7`; `COM-M56` | medium | M (installers) |
| rclone/Syncthing pins are a last resort; editor Syncthing self-upgrades every 12 h and reports crashes upstream | `PL-RES-42`; `PL-RES-45` (`res-deps-2`, `res-network-7`); `COM-M18`; `COM-L10`; related `bug-installer-2`, `-3` | medium | GL-28 (pins), M |
| No admin guide; customer-shipped docs are internal runbooks; fix text cites unshipped docs | `PRAC-51`; `PRAC-68`..`PRAC-71`; `COM-M55` | medium | M (docs) |
| The vendor cannot see its install base | `PRAC-57`; `COM-M62` | medium | M (vendor ops) |
| KNOWN_BUGS.md cannot say what is open | `PRAC-62`; `COM-M68` | medium | M (process) |
| Timeline Cards, fleet jobs, YouTube downloader and the Android app should not be in v1 | `PRAC-79`, `PRAC-81`, `PRAC-82`, `PRAC-83`; `COM-M7`, `COM-M48`, `COM-M50` | medium | GL-48 |
| A wired or base computer walks the whole NAS tree over SMB every 5 minutes | `PRAC-74`; `PL-RES-107` | medium | M (scale) |
| Intel Macs get an arm64 companion with no check; no supported-platform statement | `bug-wire-3`; `COM-M52` | medium | GL-50, M |

Related but kept apart on purpose, as the passes did: `bug-comp-ui-1`
(shutdown re-entry) vs `bug-app-b-4`; `bug-app-b-2` (upgrade stand-down) vs
`bug-comp-ui-2` (Quit during consolidate); `PL-RES-02` (WON'T UPLOAD set) vs
`PRAC-52` (the same set is only a grey chip for the admin).

---

## 2. Stop-ship

Nothing may be sold while this is open.

- [x] **GL-00 - The appliance cannot be signed in to by anyone.** A new
  customer who follows `docs/APPLIANCE_INSTALL.md` gets a dashboard whose
  setup page sends them to a login that no password can pass: the compose
  file never says "local accounts", so the dashboard expects NAS (SMB) logins
  against an empty NAS address, and the create-the-first-admin window stays
  shut.
  - Where: `dashboard/deploy/compose.appliance.yaml:153-173` (checked:
    no `DASH_AUTH_METHOD`); `settings.py:807` (default `smb`, checked);
    `setup_routes.py:60-90`; `auth.py:158-165`.
  - Fix: set `DASH_AUTH_METHOD: "local"` in the appliance compose; pin it in
    `tools/tests/test_compose_appliance.py` with a test that builds Settings
    from the exact compose env and creates the first admin; have
    `check_boot_secrets` refuse `smb` with an empty SMB host.
  - Ids: `bug-server-1`, `PRAC-1` (`prac-install-1`, `prac-simplify-1`).
  - Status: Done 2026-10-07 as CR-362 (unshipped). Remains: the live appliance
    install (GL-60).

Note on what is NOT here: the passes raised five other criticals and every
verifier downgraded them to high, so they sit in section 3 - the Windows
installer's permissions bug (`bug-installer-1`, GL-27), the appliance's
missing tailnet publish (`PRAC-4`, GL-04), the Claude subscription relay
(`COM-H1`, GL-31/GL-45), unsigned binaries (`COM-H6`, GL-30/GL-41) and the
stale customer channel (`COM-H8`, GL-24). "High" here still means "before the
first paying customer", not "later".

---

## 3. Before the first paying customer

### Track A - Code (builders can do these)

Grouped into fix waves by area. Each item: what it means in plain words, the
fix in one line, and the ids. File references are in the pass reports under
the cited id; the main ones are repeated here.

#### Wave A1 - The appliance install path (the self-install customer route)

The running theme of the practicality pass: the install route the commercial
product is built around cannot complete for a new customer as shipped. GL-00
is the first of these.

- [x] **GL-01 - The appliance's dashboard is never told where its own sync
  engine is.** The required "Sync engine" wizard step can never pass, nothing
  is shared, folder sync never works. Fix: set
  `SYNCTHING_GUI_URL=http://tailscale:8384` in the appliance env and pin it
  in the compose test. Ids: `PRAC-5`, `bug-server-2` (part).
  Where: `compose.appliance.yaml` (checked: absent); `settings.py:797`;
  `setup_engine.py:881-931`.
  Status: Done 2026-10-07 as CR-362 (unshipped). Remains: the live appliance
  install (GL-60).
- [x] **GL-02 - The appliance has no vendor feed address and no vendor public
  key, so a new customer can never install an editor or receive an update or
  a recall.** The compose comment saying the key is "generated on first boot"
  is false (checked, line 171-173). Fix: bake the vendor feed URL and public
  key(s) into the image as defaults the environment can override; fix the
  comment and the wizard copy ("the vendor's signing key", not "your release
  key"); test that the appliance boots with a configured feed; make the
  "release key not backed up" finding read "the vendor holds this key"
  (`PL-RES-30`, `PRAC-55`). Ids: `COM-H9`, `PRAC-2`, `PL-RES-35`,
  `bug-server-2` (part).
  Status: Done 2026-10-07 as CR-362 (unshipped). Remains: the live install
  (GL-60); VENDOR_FEED_URL stays a placeholder until GL-47's vendor domain;
  polish: the wizard's key-box hint does not set the customer flag (INSTALL.md
  Step 6 gives the right path).
- [x] **GL-03 - INSTALL.md tells the customer to make their own release
  key.** A customer who follows it ends up on a self-signed fork that rejects
  every vendor build. Fix: rewrite Step 6 as "pin the vendor key"; move key
  generation into vendor-only `RELEASE.md`; same text in APPLIANCE_INSTALL and
  the wizard; fix the refusal text in `install_dashboard_app.py:1651-1665`.
  Ids: `PRAC-2` (`prac-docs-1`), `COM-H11`. Where: `docs/INSTALL.md:210-236`
  (checked).
  Status: Done 2026-10-07 as CR-362 (unshipped).
- [x] **GL-04 - Nobody but the NAS itself can reach the appliance
  dashboard.** It listens on the NAS loopback only and nothing publishes it on
  the tailnet, yet the wizard's tailnet task turns green. Fix: finish ZERO_TOUCH
  WP B (configure Serve once the node is Running, write `dashboard_url`, only
  then go green); until then require Serve or a tailnet `dashboard_url` for
  the tick and document the manual `tailscale serve` fallback. Ids: `PRAC-4`,
  `bug-server-2` (part). Where: `compose.appliance.yaml:203` (checked).
  Status: Done 2026-10-07 as CR-363 (unshipped). tailscaled now runs as
  APP_UID:APP_GID. Remains: GL-60's live check that LocalAPI accepts the Serve
  and sign-in POSTs from the dashboard's uid on real DSM and SCALE, and that a
  recreated tailscale service gets its socket.
- [x] **GL-05 - The appliance's sync engine restart-loops on a fresh
  install** because Docker creates its config folder owned by root. Fix:
  `secrets-init` creates and chowns `syncthing-config` and the three tree
  folders (`PRAC-15`). Ids: `PRAC-7`.
  Status: Done 2026-10-07 as CR-363 (unshipped). Remains: the live check
  (GL-60).
- [x] **GL-06 - On Synology the container runs as a user that does not
  exist.** The doc says two variables and promises a write-back no code does.
  Fix: a documented "create a ccsync user, set APP_UID/APP_GID" step, or
  root `secrets-init` sets tree permissions; name the cause in the storage
  probe failure; check the uid on TrueNAS deploys too. Ids: `PRAC-8`,
  `COM-M45`.
  Status: Done 2026-10-07 as CR-364 (unshipped). Remains: a container run on a
  real DSM box (GL-61): the sidecar with APP_GID=100 and a login landing in
  the chroot.
- [x] **GL-07 - Six wizard tasks can only be fixed by editing container
  settings and redeploying, which the appliance forbids.** Fix: store those
  values from forms in the wizard (site settings or `/data/secrets`), restart
  with exit 75 where needed, and keep variable names in an operator fold-out.
  Ids: `PRAC-6`.
  Status: Done 2026-10-07 as CR-363 (unshipped).
- [x] **GL-08 - The sync engine's admin page is open to anyone on the
  tailnet (appliance) or the LAN (TrueNAS).** Anyone there can share any
  project folder to their own device. Fix: bind the GUI to 127.0.0.1 or have
  the dashboard set a GUI user and random password at boot; make
  `install_syncthing_app` run the secure step itself. Ids: `bug-server-3`,
  `PRAC-18`. Where: `compose.appliance.yaml:265` (checked: `0.0.0.0:8384`).
  Status: Done 2026-10-07 as CR-363 (unshipped). Remains: the live check
  (GL-60). Owner awareness: the studio's next dashboard deploy puts a random
  login on its TrueNAS Syncthing GUI unless DASH_SYNCTHING_GUI_SECURE=0 is set
  first.
- [x] **GL-09 - Nothing watches the server's own tailnet connection.** On day
  180 (Tailscale key expiry) or after a NAS update stops the Tailscale app,
  the whole fleet goes silent and the admin gets one "computer has gone
  quiet" mail per machine after 24 h, naming nothing. Fix: read
  KeyExpiry/BackendState/Serve and alert 14 days ahead; have the wizard tell
  the admin to disable expiry; add one "most machines went silent at once"
  alert; offer the dead-man heartbeat in setup (`PL-RES-52`). Ids:
  `PL-RES-05` (`res-deps-4`, `res-network-4`).
  Status: Done 2026-10-07 as CR-363 (unshipped). The no-node "most machines
  went silent at once" alert needs half the silent cluster to have been
  mid-transfer, a recorded trade against end-of-day false alerts.
- [x] **GL-10 - A Synology setting the template ships can silently cut every
  proxy over 514 MiB short while lane B reports green.** Fix: derive safe
  transport defaults for Synology's own sshd (64Ki / 16), refuse larger values
  at deploy and in Settings, add a health line and alert, comment the lines
  out of `site.example.toml`. Ids: `PRAC-10` (`prac-docs-4`, `prac-install-11`,
  `prac-config-3`).
  Status: Done 2026-10-07 as CR-364 (unshipped). Remains: a proxy over 514 MiB
  checked byte for byte on real DSM (GL-61).
- [x] **GL-11 - TrueNAS 26 removes the API every TrueNAS install and admin
  action uses.** Fix now: a NAS version check that refuses with a named reason.
  Then (soon after launch): port to the JSON-RPC API. Ids: `COM-H2`,
  `PL-RES-69`. Owner half: GL-46.
  Status: Done 2026-10-07 as CR-365 (unshipped). Remains: a live run on real
  TrueNAS 25.10 and 26 boxes (login_ex, jobs over the websocket, the snapshot
  method, core.ping).

#### Wave A2 - Data loss on "Remove from this machine"

The one destructive editor action with no undo. All three paths below were
traced by a verifier to a permanent `rmtree` after a dialog that says nothing
will be lost.

- [x] **GL-12 - Footage younger than 2 minutes, or dated in the future by a
  wrong camera clock, is deleted.** The check reuses lane A's "older than
  120 s" rule, so those files count as "nothing pending"; future-dated clips
  also never upload at all and nothing reports it. Fix: run the removal dry
  run without `--min-age`/`--min-size`; detect and report future-dated video
  in lane A. Ids: `bug-sync-1`, `PL-RES-06`. Where:
  `sync/rclone_lane.py:1792-1854, 2042` (checked: the gate reuses
  `build_up_command`'s floors).
  Status: Done 2026-10-07 as CR-366 (unshipped). The deletion is closed and
  future-dated video is detected and reported with true advice. Deferred: lane
  A still does not upload far-future files, and the dashboard chip needs a
  report key (dashboard first).
- [x] **GL-13 - On an upload-only project, every sound recording, still and
  document is deleted.** Upload-only carries video only, and the gate checks
  nothing else. Fix: block (behind the typed override, naming the files) when
  the folder holds files no lane carries; make the dialog claim only what was
  checked; decide UPLOAD_ONLY_TICK.md section 5 (widen lane A for upload-only).
  Ids: `bug-sync-2`, `PL-RES-01`.
  Status: Done 2026-10-07 as CR-366 (unshipped).
- [x] **GL-14 - Same-name files that will never upload (a re-export, two
  cameras writing C0001.MP4) count as uploaded and are deleted.** Fix: run
  `scan_size_mismatches` inside `removal_blockers` and block on any hit; fail
  closed if it cannot run. Ids: `PL-RES-02`; related `PRAC-52`.
  Status: Done 2026-10-07 as CR-366 (unshipped).
- [ ] *Same wave, medium:* the removal gate's folder-sync half trusts
  Syncthing's index without a scan (`PL-RES-07`); file moves trash an
  unverified single file or a whole folder on a failed listing (`bug-sync-4`,
  `bug-sync-5`). Same code, same reviewers.

#### Wave A3 - Trust: tokens, logins, keys, credentials

- [x] **GL-15 - Removing a person does not cut off their computer.** By
  default every editor shares one fleet secret, and each computer's identity
  token never expires and cannot be revoked; a suspended, disabled or deleted
  editor can still claim YouTube jobs, read manifests and post results, and a
  deleted smb/oidc editor re-registers on the next report. Fix: per-identity
  revocation (a generation counter or deny-list) checked by every fleet door
  (b-roll, music, ytdl gates and `login_gate`); a durable removal tombstone;
  on a successful `/verify`, mint a bound per-machine `cce1` token; ship new
  sites with the shared token off. Ids: `bug-comp-ytdl-1`, `bug-dash-api-1`,
  `bug-dash-auth-2`, `PL-RES-79`, `PRAC-35`, `COM-H15`, `COM-M26`. Where:
  `auth.py:74` (checked: identity TTL 100 years), `settings.py:806` (checked:
  shared token on unless `=0`).
  Status: Done 2026-10-07 as CR-367 (unshipped). Deferred, owner calls: the
  membership half of bug-dash-auth-2 (a never-deleted smb guest or bookkeeper
  account can still sign in to the browser UI; gating it changes who may open
  the UI), retiring the studio's shared token, and whether disable or a
  password reset revokes identity tokens.
- [x] **GL-16 - On an SSO (OIDC) site, the JSON login accepts any NAS
  password**, skipping the identity provider, MFA and group rules the
  customer chose SSO for. Fix: one helper for both login routes (OIDC is
  admin-only break-glass, plaintext refusal). Ids: `bug-dash-auth-1`.
  Status: Done 2026-10-07 as CR-367 (unshipped).
- [ ] **GL-17 - The release signing key: the engineering half.** Generate a
  new production key on whatever the owner chooses in GL-42, retire the
  2026-08-17 key in an overlap release, bake a second cold recovery public
  key, and write a key-compromise runbook. At minimum before then, wrap the
  existing key with DPAPI and keep `.ccsync-release` out of agent scope. Ids:
  `bug-comp-trust-1`, `COM-H4`, `PL-RES-41`.
  Status: Beta half done 2026-10-07 as CR-378 (base-rig release tools, nothing
  shipped): the release key is a passphrase-protected file, asked once per
  signing run by ship and publish_latest. Owner one-time step owed: `python
  tools\release_key.py encrypt`, two `backup --to` USB copies, the passphrase
  on paper kept apart, every older plaintext copy destroyed. Not done (GL-42's
  paid-release half): a hardware-token production key, retiring the 2026-08-17
  key in an overlap release, a cold recovery key and the compromise runbook.
- [x] **GL-18 - The container holds a NAS root-equivalent credential by
  default, and the dashboard admin is by default the NAS admin.** Fix: make
  `TRUENAS_API_KEY` mandatory on TrueNAS (password only for deploy-time SSH);
  separate dashboard admin from NAS admin; pin the NAS certificate at install;
  a non-admin service account on DSM where possible. Ids: `COM-H5`; related
  `bug-server-9` (the "scoped" key is still root-equivalent), `bug-dash-ops-5`.
  Status: Done 2026-10-07 as CR-368 (unshipped). Remains: live-NAS
  verification (TLS pin, group reconcile, Postgres ALTER ROLE); the DSM
  non-admin service account.
- [x] **GL-19 - The other insecure defaults a buyer's security review will
  list.** Editor lanes trust any NAS host key; NAS TLS is not verified; the
  optional Postgres profile publishes `postgres`/`DaVinci` on every interface;
  `project_acl=shared` lets any editor delete any project; no tailnet ACL
  template. Fix (minimum): pin host keys on editor lanes, verify NAS TLS with
  a fingerprint option, random Postgres password bound to LAN and tailnet,
  per-project ACL, ship `TAILNET_POLICY.md`. Ids: `COM-H15`, `bug-server-8`,
  `PL-RES-27`. Owner half (a decision per open trust-model id): GL-49.
  Status: Done 2026-10-07 as CR-367 (token half) and CR-368 (unshipped).
  Remains: live-NAS verification; the project-grant UI is DONE (2026-10-07: the admin-only "project access" window on each project page, audited);
  COM-H15 is narrowed, not closed, because a self-service tick still joins
  any active project's group (to be stated in TENANCY.md, decided under
  GL-49).

#### Wave A4 - Upgrades that roll back, and a release pipeline a customer can rely on

- [x] **GL-20 - A dashboard update that crashes on boot is reverted, then
  re-applied 10 seconds later, forever** at every default-policy site. Fix:
  treat `current.json reverted_from == version` as tried-and-failed; a durable
  do-not-auto-apply marker cleared only by a newer version or an admin APPLY;
  an apply-revert-poll test. Ids: `bug-dash-release-1`.
  Status: Done 2026-10-07 as CR-369 (unshipped). Remains: the deliberately
  broken bundles on staging (GL-66).
- [x] **GL-21 - A dashboard update that boots but cannot serve is never
  reverted**, because nothing restarts the wedged process. Fix: in
  volume-tree mode, exit (75) when the boot probe fails so the next start
  reverts; a lifespan deadline. Ids: `PL-RES-04`.
  Status: Done 2026-10-07 as CR-369 (unshipped). Remains: GL-66.
- [x] **GL-22 - A companion build that dies at start-up is never rolled back,
  and no release step ever launches the built exe.** Fix: a `--self-test`
  launch of the frozen exe in `release.ps1`, `release-windows.yml` and
  `release_macos.sh`; record the start at the top of `run()`; the supervisor
  relaunches an exit-1 death of a just-upgraded build; replace the 2 s
  hand-off grace with a "started" marker. Ids: `PL-RES-03`.
  Status: Done 2026-10-07 as CR-370 (unshipped). Remains: a frozen exe built
  and launched with --self-test on Windows and a Mac, and the dies-at-import
  companion on staging (GL-66).
- [x] **GL-23 - Quit, Restart and self-upgrade exit before teardown finishes**,
  leaving an rclone child running beside the new build's lane B (the
  two-rclone race closed earlier) and reading as a crash loop. Fires on every
  self-upgrade. Fix: the repeat `shutdown()` waits on a done-event (bounded),
  or only the main thread tears down; regression test. Ids: `bug-comp-ui-1`.
  Status: Done 2026-10-07 as CR-370 (unshipped). Remains: GL-66's self-upgrade
  during a lane B run.
- [x] **GL-24 - Make a customer release one gated event.** Today the customer
  channel is a month behind (feed dashboard 0.7.44, image tag `v0.7.44` is the
  newest git tag - both checked locally; the live feed was not queried) and
  customers would get a draft EULA. Fix: one "release to customers" command
  that, from one green commit, publishes the dashboard bundle first, then the
  companion and both installers, tags `v*`, moves `dashboard_image` and
  `current` together; a CI check that fails when the feed's dashboard trails
  main; move the studio onto the customer channel. Ids: `COM-H8`, `PRAC-9`.
  Owner half (the `:1` tag policy): GL-50.
  Status: Done 2026-10-07 as CR-371 (unshipped). Remains: moving the
  studio's soak onto a working image-mode route (the owner's act), and a
  first live run of release_customers.py.
- [x] **GL-25 - The dashboard image and OTA bundle publish with no test gate.**
  Fix: tag builds need green CI plus a required-reviewer environment; pin
  every action to a commit SHA; a `docker run` + health + headless `/setup`
  smoke test; publish refuses a commit without a full-green CI run; fix the
  cosign identity; `publish_latest` checks CI was green for that commit;
  reorder `ship.ps1` so no deploy precedes its suite. Ids: `COM-H10`,
  `bug-dash-release-2`, `bug-tools-ci-3`.
  Status: Done 2026-10-07 as CR-371 (unshipped). Remains: the
  customer-release environment with a reviewer and FEED_READ_TOKEN (owner
  setup); COM-H10 extras (pip-audit/osv, SBOM, provenance) not built.
- [x] **GL-25b - Raise the downgrade floor and add a channel freshness check**
  (medium in all three passes, but it is the same release-tooling change and
  without it any old signed build, or an old replayed channel, can roll a
  fleet back). Ids: `bug-comp-trust-2`, `bug-dash-release-4`, `PL-RES-40`,
  `COM-M33`.
  Status: Done 2026-10-07 as CR-371 (unshipped). Remains: confirming the
  placeholder launch floors.
- [ ] **GL-26 - Even with certificates, the customer pathway cannot produce a
  signed build.** Only `ship.ps1` checks for unsigned binaries; Windows CI can
  only sign from a PFX (no longer possible for OV/EV keys); macOS CI never
  imports a certificate. Fix: decide where signing happens (cloud HSM in an
  approval-gated CI environment, or a re-sign step on the rig in
  `publish_latest`), implement it for all four artefacts with notarisation and
  stapling, and refuse unsigned on `--make-current`. Ids: `COM-H7`. Depends on
  GL-41.

#### Wave A5 - Installers and an editor's first day

- [x] **GL-27 - Every Windows wizard install makes the companion's own state
  folder unreadable.** `icacls /inheritance:r` without `(OI)(CI)` leaves
  existing files with an empty permission list: the EULA re-asks, the install
  log stops, and the safety latches (lane B breaker, fleet halt, drive
  reminder) can no longer be saved. Fix: grant with `(OI)(CI)` or harden files
  only; ship a repair in the next bootstrap, `windows_upgrade.ps1` and at
  companion start; an installer test with a pre-existing child. Ids:
  `bug-installer-1` (critical, verifier: high). Where:
  `installer/windows_bootstrap.ps1:564` (checked).
  Status: Done 2026-10-07 as CR-372 (unshipped). Remains: a stock Windows 11
  VM (GL-63).
- [x] **GL-28 - On a stock Windows 11 machine (which has winget), the first
  install ends NOT READY with no folder sync**, and when winget succeeds the
  machine runs winget's build, not the pinned, checksum-verified one. Fix:
  prefer the pinned verified download; winget only as a fallback with a PATH
  refresh; write the absolute rclone path into config. Ids: `bug-installer-2`;
  related `bug-installer-3`, `PL-RES-42`, `PL-RES-45`.
  Status: Done 2026-10-07 as CR-372 (unshipped). Remains: a stock Windows 11
  VM (GL-63) and the macOS bootstrap on a real Apple silicon Mac (GL-64).
- [x] **GL-29 - The wizard says DONE but Resolve is not connected**: the
  editor still has to add the Postgres project library and switch on External
  scripting (Resolve's default is off, which silently disables the watcher,
  fixer, popup and Send to Resolve), and the tray then sends them round a
  restart loop. Fix: a "connect Resolve" checklist on both finish pages with
  the host from the site manifest; write the scripting preference while
  Resolve is closed; detect Resolve and its edition at install; when a machine
  has never had a scripting connection, name the preference and the Studio
  requirement instead of "restart Resolve". Ids: `PRAC-11`, `PL-RES-58`.
  Status: Done 2026-10-07 as CR-373 (unshipped). Remains: live fresh-seat and
  macOS wizard runs (GL-63, GL-64).
- [x] **GL-30 - Binaries show "Unknown publisher" and the installer page
  teaches "Run anyway".** Code half: a version resource (CompanyName,
  ProductName, LegalCopyright from the legal entity) in both specs, Publisher
  set to the legal entity in Apps & features (`COM-M59`), and remove the "Run
  anyway" text the day a signed build ships. Ids: `COM-H6`. Owner half: GL-41.
  Status: Done 2026-10-07 in its beta form as CR-373 (unshipped); certificates
  wait for the paid release (beta decision) and the unsigned-build notes go
  the day a signed build ships. Still owed: the INSTALL.md SmartScreen and
  System Settings click-through guide (CR-377 deferral).

#### Wave A6 - Everything else that blocks a sale

- [x] **GL-31 - Take the Claude.ai / ChatGPT subscription sign-in relay out
  of the commercial build.** Keep Console sign-in or an API key only; let
  triage pass a capped `ANTHROPIC_API_KEY`; rewrite the notice per tool (Cards,
  triage, consumer data terms, auto-update); hide the CLI rows and triage
  behind a vendor-only flag; correct COMMERCIAL_READINESS item 1. Ids:
  `COM-H1`, `PRAC-80`. Owner half: GL-45. Where:
  `ai_providers.py:85` (checked: `claude_code` first in `PROVIDER_ORDER`).
  Status: Done 2026-10-07 as CR-374 (unshipped). Remains: the owner's
  choice on a one-time grandfather record for the studio, and the studio's
  site.toml `allow_cli_providers` setting before its first deploy. The
  triage question is answered (Round-2 answers).
- [x] **GL-32 - psycopg2 (LGPL) is frozen into the one-file companion,** so
  the "replaceable library" premise counsel cleared is untrue and the LGPL
  text is missing. Fix: add the LGPL-3.0 text now; then load psycopg2 from a
  user-replaceable directory, ship it outside the exe, or offer the relink
  archive; inspect the macOS dylibs. Ids: `COM-H3`. Counsel half: GL-51.
  Status: Done 2026-10-07 as CR-375 (unshipped). Remains: a real frozen build
  on Windows and on a Mac must confirm psycopg2 ships outside the exe and
  loads; counsel re-review under GL-51.
- [x] **GL-33 - More than 3 removals in one cycle freezes every untick and
  Suspend fleet-wide,** and only a container setting undoes it. Suspending one
  editor with 6 projects on 2 computers trips it. Fix: pre-authorise removals
  that trace to an audited admin action; an "apply these N removals" button;
  a site setting that scales with fleet size. Ids: `PRAC-12`.
  Status: Done 2026-10-07 as CR-376 (unshipped). Remains: a live click-through
  of the Sharing safety tab and the Apply button.
- [x] **GL-34 - A support contact in the product.** Add a vendor-defaulted
  `support_contact` (reseller override) to the site manifest and show it on
  /help, the Health header, beside every "send to support" line, in the
  companion help and on the wizard Done step. Ids: `COM-H12`, `PRAC-49`.
  Status: Done 2026-10-07 as CR-374 (unshipped); the vendor default is
  support@thecreatorsclub.co (owner to create the mailbox). Remains: the
  bootstrap closing texts do not show the support line yet.
- [x] **GL-35 - The customer "product repo" cannot be produced, and what it
  would withhold is out of date.** Fix after the owner decides whether any
  customer gets source (GL-40): if none, archive the tool and remove the
  clone step; if some, switch to an allow-list built from the customer docs
  set and scrub the studio's names and addresses. Ids: `PRAC-13`, `COM-M42`.
  Status: Done 2026-10-07 as CR-375 (unshipped).

### Track B - Owner, counsel and money (nobody can code these)

Each needs Alex, a lawyer, an accountant or a purchase. Several unblock code
in track A.

**Owner decisions, 2026-10-07** (asked one by one; these override the
proposals in the items below where they differ):

| Item | Decision |
|---|---|
| GL-40 install story | **Customer self-installs.** Wave A1 (GL-01..GL-11) is in full scope, and GL-60 must pass before the first sale. GL-62 (vendor-service install) is not needed. |
| GL-45 AI billing | **Studio keeps the CLIs, customers get API only.** One codebase, not a fork: the customer (vendor) build HARD-DISABLES the Claude Code and Codex CLI providers (not a site flag a customer can flip); the studio's own `site.toml` keeps both on. GL-45's "turn `ai_cli_providers` off on the studio's dashboard" is withdrawn. |
| GL-44 pricing unit | **Flat price per site**, regardless of computer count. |
| GL-44 enforcement | **By contract for v1**: no seat or expiry checks in code; downloads get a credential (the product stops being publicly downloadable). |
| GL-48 v1 scope | **Keep every feature and get it ready.** Nothing is CUT or HIDDEN: YouTube downloader, Timeline Cards, cards agent, fleet jobs, client share links (needs its rights gate, `COM-M49`), triage agent and Android all ship, so their fixes join track A. YouTube still needs the Google/YouTube terms read (`COM-M7`, section 5). |
| GL-35 / GL-41 source and entity | **No customer gets source** (retire the product-repo tool and its clone step). **Cablewrap Creative Ltd** signs and contracts: D-U-N-S, Authenticode, Apple Developer ID in its name. |
| GL-42 key custody | **Beta: a passphrase-protected key file** (revised 2026-10-07 from "hardware token"): the release key stays a file on the base rig but encrypted with a passphrase asked once per signing, plus **two offline backups** in different places. **Before the paid release: move it to a hardware token** (check the token supports the key's algorithm first). GL-17's engineering half for the beta is the passphrase support in `tools/release_key.py` and the signing paths; the token half waits. |
| GL-50 updates | **Pin customers by digest, vendor soak** on the studio fleet before a build is offered. |
| GL-50 version number | **Stays below 1.0 for the open beta** (2026-10-07, revising the same day's "reverse the rule"): the launch is an open beta, so the 2026-08-18 rule stands (0.9.x then 0.10.0); 1.0 waits for the paid release. |
| GL-50 platforms | **Accepted 2026-10-07:** Windows 10 22H2 and 11, x64; macOS on Apple silicon; unmanaged machines only (no MSI/pkg or AppLocker), stated in the beta terms. |
| Launch shape | **Free open beta after the track A fixes**, not a 1.0 commercial release. **Fully unsigned during the beta, both platforms**: no Authenticode certificate and no Apple Developer Program, so GL-41's purchases and GL-26 wait for the paid release. The install docs need a SmartScreen click-through for Windows and a step-by-step "allow it in System Settings" guide for macOS, which may be needed again after an update. |
| GL-43 / GL-44 in the beta | **Deferred to the paid release:** order form, invoicing, tax and the flat per-site price. For the beta, counsel writes a short beta agreement (as-is, no uptime promise, may need re-setup, ends on notice) and the beta gets a best-effort support address. Normal operation sends the vendor nothing (PRIVACY.md: no vendor telemetry, the data stays in the studio); the DPA is needed ONLY because support may, case by case, receive a diagnostics bundle or log or take a remote session (owner, 2026-10-07). So counsel drafts the DPA with SCC / UK transfer annexes (`COM-M4`) before the first EU or UK beta site, plus a one-page support-data procedure (what may be requested, where it is kept, when it is deleted). |
| GL-46 TrueNAS 26 | **Port to JSON-RPC before launch**, so 26 is supported on day one. |
| GL-47 second operator | **Deferred, accepted risk.** The vendor domain, registry namespace and org move still happen before customer 1. |
| GL-13 upload-only | **Lane A carries every file** for an upload-only project (decides UPLOAD_ONLY_TICK.md section 5), plus the removal block naming anything not on the server. |
| COM-M27 / GL-49 security | **Tailscale-only, no LAN-only SKU; new sites get every COM-H15 secure default**; the studio keeps its legacy values in its own `site.toml`. |
| Round-2 answers (2026-10-07) | **Support address:** a separate `support@thecreatorsclub.co` mailbox (owner to create it), never the owner's personal inbox. **Triage agent on customer builds:** allowed when it runs on the site's own Anthropic API key; only the subscription sign-in is locked off. **Legal drafts** (beta agreement, DPA, support-data procedure) stay OUT of the in-product published set until counsel clears each one. **Support data:** no AI tools read customer logs or bundles; kept until 30 days after the ticket closes, then deleted. |

Still open with nobody to ask: the beta agreement, the DPA and the rest of
GL-51 (one counsel visit) are tasks, not choices.

- [ ] **GL-40 - Decide the v1 install story.** Either installs are a
  vendor-performed service (with a vendor runbook, a private ops repo for
  per-customer settings, scoped keys and a credential-custody policy, the
  customer's NAS admin password dropped after install), or the appliance is
  finished (wave A1) and becomes the only customer path. Until wave A1 lands
  and GL-60 has passed, do not sell the appliance as self-install. Either way
  default new sites to image mode. Ids: `PRAC-3`, `COM-H11`, `COM-M61`.
- [ ] **GL-41 - Code-signing certificates and the legal entity behind them.**
  Settle which entity signs (the licensor is Cablewrap Creative Ltd; the brand
  and GitHub org are the studio's), get a D-U-N-S number, buy an OV/EV
  Authenticode certificate (cloud HSM or Azure Trusted Signing, because OV/EV
  keys cannot be exported to the PFX the CI expects), enrol in the Apple
  Developer Program for Developer ID and notarisation. Lead time is weeks:
  start now. Unblocks GL-26, GL-30. Ids: `COM-H6`, `COM-H7`.
- [ ] **GL-42 - Release-key custody.** Choose a hardware token, HSM or cloud
  KMS, or a dedicated offline signer that runs no agents; escrow the seed
  twice; record a key ceremony; decide together with GL-41. Unblocks GL-17.
  Ids: `COM-H4`, `bug-comp-trust-1`, `PL-RES-41`.
  Status: Beta half decided (a passphrase file, two offline backups) and its
  engineering built as CR-378; the owner's one-time encrypt and backups are
  owed; a hardware token before the paid release.
- [ ] **GL-43 - Order form, support terms, DPA, support address, invoicing.**
  The cleared EULA 1.1 ties seats, support and updates to "your order or
  support plan", and neither exists. With counsel: a price list and unit, an
  order form template (licence id, seats, term, updates-until, features, fees,
  renewal, refunds), subscription and support terms (hours, channel, response
  targets, security-fix policy), the Art. 28 DPA with a sub-processor list
  (`COM-M4`), a separate support mailbox that someone reads. With an
  accountant: Taiwan uniform invoice for domestic sales, cross-border VAT,
  withholding, currency. Ids: `COM-H12`, `COM-M4`.
  Status: Drafts (beta agreement, DPA, support data procedure, supported
  platforms, PRIVACY 1.1) written 2026-10-07 as CR-377 and passed round-2
  oversight; support address support@thecreatorsclub.co (owner to create it);
  the three drafts are refused by /help until counsel clears each; beta
  acceptance is by email at sign-up until an in-product step exists. Owner and
  counsel item.
- [ ] **GL-44 - The pricing and licensing model.** Nothing in the product
  counts seats, checks an entitlement or expiry, or produces a usage statement
  to invoice from; feature flags are switches the customer controls; the
  whole product including Python source is publicly downloadable under a
  LICENSE that says "confidential"; AI spend is uncapped and unattributed.
  Decide: what is sold (per editing computer plus a per-site base is the
  pass's suggestion), whether licences are enforced in code or by contract
  for v1, and whether downloads need a credential. Ids: `COM-M34`..`COM-M38`
  (medium in the pass; the decision is needed before the first quote).
- [ ] **GL-45 - The Claude Code subscription path.** Decide that the
  commercial build uses Console / API billing only (GL-31); accept Anthropic's
  Commercial Terms; get written confirmation from Anthropic if any CLI path
  stays; turn `ai_cli_providers` off on the studio's own dashboard, which runs
  the relay live today. Ids: `COM-H1`.
- [ ] **GL-46 - TrueNAS 26.** State supported TrueNAS (and DSM) versions in
  the order form and support matrix, tell customers not to upgrade to 26 yet,
  and schedule the JSON-RPC port. Ids: `COM-H2`, `PL-RES-69`.
  Status: JSON-RPC port done 2026-10-07 as CR-365 (unshipped);
  SUPPORTED_PLATFORMS.md (a CR-377 draft) states 25.x and 26 supported from
  launch; the first live 26 run is owed.
- [ ] **GL-47 - Bus factor and the vendor's GitHub org.** Every release and
  incident action needs the release key, the gh login, the DPAPI secrets and
  an interactive password, all on one Windows account. Name a second operator
  with a tested route to the key backup and org access; move the GitHub org,
  GHCR packages and releases repo to the contracting entity with two owners;
  put the feed behind a vendor-owned, redirectable domain and registry
  namespace **before customer 1** (both are baked into every customer's
  compose, so a later move breaks every site's updates); escrow terms for
  larger customers; a rig-rebuild drill from the docs. Ids: `COM-H13`.
- [ ] **GL-48 - Which features ship in v1.** The commercial pass graded the
  product surface (`com-product-surface-1`, `COM-M47`); proposed starting
  point:

  | Feature | Proposed v1 grade |
  |---|---|
  | Sync core (lanes, tray, popup/fixer, proxies, LUT link, file moves, halt, breaker, per-machine plans, upload-only) | READY on Windows, BETA on macOS |
  | Dashboard admin (users, plans, packages, health, alerts, recovery, setup wizard, account page, export/erase) | READY |
  | B-roll search and ingest | READY |
  | Client folders (public share links) | HIDE until a rights gate exists (`COM-M49`) |
  | Music search and ingest | BETA (tuned on one 376-track library) |
  | YouTube downloader | CUT (keep dormant, do not sell; `COM-M7`, `PRAC-79`) |
  | Timeline Cards, cards agent, fleet jobs | CUT (`COM-M48`, `PRAC-81`, `PRAC-82`) |
  | Server triage agent | HIDE |
  | Mobile PWA | READY (https sites only) |
  | Android app | HIDE (`COM-M50`, `PRAC-83`) |
  | AI CLI providers, Claude Code auto-update | HIDE |
  | OIDC sign-in | BETA (never pointed at a real IdP) |
  | Synology backend | BETA (one test box) |
  | Appliance install | NOT READY (GL-40) |

  Mark BETA features as preview in the EULA and the UI; make CUT features
  hard-disabled in the vendor build, not left to a site flag. Publish the
  result as a one-page product sheet.
- [ ] **GL-49 - A decision per open trust-model item.** Many CR-66 items were
  deferred on purpose and never re-decided for a commercial launch: fix,
  document as a limitation, or accept with a reason (list in `COM-H15`).
  Unblocks the rest of GL-19.
- [ ] **GL-50 - Release and platform policy.** The `:1` tag policy (move per
  release, or pin customers by digest) (`COM-H8`); vendor soak and canary
  instead of a manual canary at every customer (`COM-M60`, `PRAC-54`); whether
  managed-IT customers (MSI/pkg, AppLocker) are a launch target or "unmanaged
  machines only" goes in the order form (`COM-M54`); a supported-platforms
  page (Resolve Studio versions, Windows 11 x64, Apple silicon only or
  universal, macOS minimum, Tailscale plan, NAS versions) referenced from the
  EULA (`COM-M52`, `bug-wire-3`); the customer-facing version number (0.x
  reads as pre-release, `COM-M53`).
  Status: Digest pinning and the dashboard half of the vendor soak built
  2026-10-07 as CR-371 (unshipped, passed round-3 oversight); the
  companion half of the soak needs an owner choice; the supported-platforms
  page is a CR-377 draft.
- [ ] **GL-51 - One counsel visit for the rest.** Most are medium in the
  commercial pass but cheap and needed before the first contract: the root
  LICENSE is still a draft with a placeholder licensor, no IP assignment, the
  yt-credit-downloader grant owed (`COM-M3`); re-review psycopg2 on the
  one-file fact (`COM-H3`); a short end-user notice instead of every
  freelancer accepting the B2B EULA (`PRAC-40`, `COM-M8`, `COM-M9`); the
  "cleared" documents edited after clearance (`COM-M2`); vulnerability
  disclosure and EU CRA reporting (`COM-M5`); the Blackmagic licence
  (`COM-M6`); Tailscale's free tier is non-commercial, so customers need a paid
  plan (`COM-M39`); brand clearance (`COM-M11`).

### Track C - Proof (things that must be run for real before selling)

Nothing in this review touched a live system. These are the runs that turn
"traced in code" into "works for a customer".

- [ ] **GL-60 - A fresh appliance install on TrueNAS SCALE, by someone who
  did not write it**, on a clean box: compose up, wizard to Done, one Windows
  and one Mac editor onboarded, first sync of all three lanes, first OTA,
  first rollback. Needs wave A1. Covers `COM-H14`, `PRAC-4`/`-5`/`-7`/`-14`,
  KNOWN_BUGS WPK-3. Also check **LocalAPI write as APP_UID** (CR-363 round 2):
  from the dashboard container, `POST /localapi/v0/serve-config` and the
  sign-in POST must be accepted by tailscaled running as the same uid, not
  403 "serve config denied".
  Also recreate only the tailscale service and confirm its socket appears
  (a fresh named volume can come up root-owned; CR-363 round 2).
- [ ] **GL-61 - The same on Synology DSM**, plus a reboot, the uid step and a
  proxy over 514 MiB checked byte for byte (`PRAC-8`, `PRAC-10`; reboot
  survival and uid stability are untested per `SERVER-SYNOLOGY.md`).
- [ ] **GL-62 - If installs are a vendor service (GL-40): the base-rig install
  on a clean TrueNAS from the rewritten INSTALL.md**, with only the vendor key
  and feed, including the server-script Python dependencies (`PRAC-19`).
- [ ] **GL-63 - Editor onboarding on stock machines:** a stock Windows 11 with
  winget (GL-27, GL-28), a machine with Smart App Control or an EDR (GL-30),
  a non-English Windows (`COM-M58`), and Resolve Free / External scripting
  None / an older Resolve (`PL-RES-58`, `PL-RES-64`).
- [ ] **GL-64 - A Mac run:** `MACOS_FIRST_RUN` A7-H; the quit-event path
  (`bug-comp-ui-3`); the `pgrep -x` Resolve probe (`bug-resolve-5`); the CR-68
  launch-window guard on a live Mac (`PL-RES-68`); Full Disk Access at install
  and after an update (`PRAC-39`, `COM-H6`); CR-280 certifi on a frozen build;
  an Intel Mac refused cleanly (`bug-wire-3`). onboard/macos is at 1.0.44
  against 1.0.46 on Windows and lacks the LG-1 privacy page (`COM-M52`).
- [ ] **GL-65 - A staging site the studio does not depend on:** vendor-owned
  TrueNAS and DSM boxes or VMs plus Windows and Mac editor VMs, and a CI job
  that runs `compose up` with the built image, completes `/setup` headless
  and sends a stub-companion report (`COM-H14`). Every release candidate runs
  GL-60's script here before `--make-current`.
- [ ] **GL-66 - Deliberately broken releases on staging:** a dashboard bundle
  that crashes on boot (GL-20), one that boots but cannot serve (GL-21), a
  companion that dies at import (GL-22), and a self-upgrade during a lane B
  run (GL-23).
- [ ] **GL-67 - Live checks the passes could not make:** query the live
  vendor feed, GHCR tags and branch protection (the stale-channel evidence is
  the local `feed/channel.json` of 2026-09-26 and the git tags; the `PRAC-9`
  verifier could not confirm `:1` was ever pushed); probe the appliance
  Syncthing GUI from another tailnet peer (`bug-server-3`); point OIDC at a
  real IdP (`COM-M25`); scan the built images (syft/trivy); confirm
  the `support@thecreatorsclub.co` mailbox exists and is read (Round-2
  answers), and the Q: key backup is truly offline.
- [ ] **GL-68 - Measure on real hardware:** page timings and the owed-files
  backlog on NAS CPU at a realistic fleet size (`PL-RES-74`, `PRAC-73`,
  `PRAC-78`); report timeouts on a lossy link (`PL-RES-44`); power loss on
  NTFS and APFS (`PL-RES-14`, `PL-RES-15`); the threadpool claim under many
  Cards agents only if Cards ships (`bug-dash-jobs-cards-3`).
- [ ] **GL-69 - Run the full gate once on the release candidate.** None of the
  four passes ran the 13 suites (only targeted files); about 1,050 lines of
  live-incident fixes sit uncommitted with the dashboard bytes changed but
  VERSION still 0.7.73 (`COM-M69`). Commit, bump, run
  `tools\run_all_tests.ps1`, and only then cut the RC.

---

## 4. Soon after launch

About 265 distinct mediums. Grouped by theme with the ids to read; the full
text, file references and fixes are in the pass reports. Themes are roughly
in the order they hurt a customer.

1. **Companion: sync lifecycle, pauses, halts and shutdown.** Resume can leave
   no sequencer; licence accept or halt release starts lanes with nobody
   signed in; a fleet halt release erases a local halt; Pause is forgotten at
   restart; updates restart mid-transfer; Quit kills a running consolidate;
   macOS quit events bypass shutdown; whisper workers orphaned. Ids:
   `bug-app-a-1`..`-4`, `bug-app-b-1`, `-2`, `bug-comp-ui-2`, `-3`,
   `bug-comp-media-1`, `PRAC-43`, `PRAC-44` = `PL-RES-38`, `PL-RES-34`,
   `PL-RES-37` = `COM-M10`, `PL-RES-39`. (bugs.md section 3; resilience.md
   "Upgrades and the release chain".)
2. **Footage safety beyond removal.** Borrowed folders re-pointed at an empty
   skeleton, file moves trashing un-synced files, lane B trashing locally
   generated proxies and tripping the breaker, power-loss zeroed files spread
   by size-only checks, safety state not fsynced, SMB logins can delete
   originals with no recycle bin, the 14-day age-out of the only record that
   a laptop holds originals. Ids: `bug-sync-3`..`-7`, `PL-RES-07`..`PL-RES-18`,
   `PRAC-46`, `PRAC-52`, `PRAC-53`. (resilience.md "Footage and project data
   safety".)
3. **Resolve integration.** Undo that undoes nothing or hides older undos,
   library cache never refreshed, a save point per b-roll insert, relinks
   that do not check the clip still points where judged, third-party scripting
   clients, no supported Resolve version stated. Ids: `bug-resolve-1`..`-5`,
   `PL-RES-59`..`PL-RES-67`. (bugs.md "Companion: Resolve"; resilience.md
   "Resolve integration".)
4. **Dashboard security and accounts.** Security headers and CSP
   (`bug-dash-ui-2` = `PL-RES-81` = `COM-M29`), CSRF-exempt package routes
   (`bug-dash-api-2` = `COM-M28`), login throttle race (`bug-dash-auth-3`),
   mutable OIDC username (`bug-dash-auth-4`), Syncthing device takeover
   (`bug-dash-api-3`), no MFA (`PL-RES-85` = `COM-M25`), loopback trust
   (`bug-comp-trust-3`..`-5`, `PL-RES-82`, `PRAC-41`), public client links
   (`PL-RES-80`, `COM-M31`, `COM-M49`), audit trail (`COM-M30`), plain HTTP on
   LAN (`COM-M27`), uninstall leaves credentials (`COM-M19`).
5. **Backups, restore and recovery.** No integrity check on `dashboard.db`,
   a missing DB silently recreated with the first-admin window reopened,
   migrations with no backup, ytdl.db never backed up, a forgotten local-admin
   password with no way back, NAS free space never measured, Resolve project
   server outside backups, no offsite warning, the NAS Syncthing identity
   change stopping every editor. Ids: `PL-RES-19`..`PL-RES-32`, `bug-music-1`
   = `PL-RES-09`. (resilience.md "Dashboard backups, restore and recovery".)
6. **Release chain and dependencies.** `requires_dashboard` stale
   (`PL-RES-36` = `COM-M51`), recall takes a day and does not stop the bad
   build (`COM-M63`), no urgent flag (`PRAC-60`), one-site hotfix
   (`PRAC-58`), publish_feed merge and ship flags (`bug-dash-release-5`,
   `-6`), OTA tree never re-verified (`bug-server-6`), licence gate is a
   denylist (`bug-tools-ci-4`), CI runs pwsh 7 not 5.1 (`bug-tools-ci-5`),
   yt-dlp nightly with no pin (`bug-comp-ytdl-5`, `bug-ytdl-web-4`,
   `PL-RES-72`, `COM-M32`), appliance sidecar images with no update path
   (`PL-RES-73`), AI provider failure and compiled-in model ids (`PL-RES-70`,
   `PL-RES-71`), Syncthing relays and self-upgrade (`COM-M18`, `PL-RES-45`).
7. **Telling the right person.** Failed alert sends not retried, restarts
   leave no trace, the dead-man heartbeat off by default, a failing check
   still shows OK, warn-level never pushed, rejected reports read as "switched
   off", wrong NAS clock turns the fleet red, SMTP 465, three different problem
   totals, no support bundle, no dashboard log retention, failed editor
   installs invisible, vendor cannot see its install base. Ids:
   `PL-RES-50`..`PL-RES-57`, `bug-dash-ops-6`, `bug-dash-db-2`, `-3`,
   `PRAC-48`, `PRAC-50`, `PRAC-56`, `PRAC-57` = `COM-M62`, `PRAC-59`.
8. **Configuration and deploy.** Editing site.toml silently changes nothing
   after first boot, wrong examples in Settings, OIDC and tunables not
   settable by the shipped deploy, secret rotation recipe fails, settings
   revert on `--recreate`, documented keys never read (including the telemetry
   opt-outs), `projects_dir` offered but refused, 147 companion keys with 6 in
   the window. Ids: `PRAC-22`..`PRAC-31`, `bug-server-7`, `bug-server-10`.
9. **Editor onboarding and customer docs.** The installer download sits
   behind the tailnet it is meant to join, the wizard asks for the address it
   came from, no invite flow, approvals invisible, a second site keeps the
   first site's token, macOS 15 first-run advice wrong, EDITOR_SETUP and
   HOW_IT_WORKS out of date, no admin guide, no customer/internal docs
   boundary. Ids: `PRAC-32`..`PRAC-39`, `PRAC-68`..`PRAC-71`, `PRAC-51` =
   `COM-M55`, `COM-M57` (no customer offboarding path).
10. **An editor's working day and error copy.** Send to Resolve refused at an
    unlisted address and blamed on the browser, b-roll insert needs the tab
    open, no "sync this first", Settings buttons close the window, raw
    urllib/rclone text in dialogs and toasts, a misleading lane-error
    classifier. Ids: `PRAC-41`..`PRAC-47`, `PRAC-63`..`PRAC-67`,
    `bug-comp-ytdl-3`, `-4`.
11. **Scale and performance.** Backlog recomputed per poll (`PL-RES-74` =
    `PRAC-73`), b-roll index rebuilt whole per ingest (`PL-RES-75`), per-file
    truth "uncertain" past 2,000 files (`PL-RES-76`), write lock held across
    SMTP/Syncthing calls (`bug-dash-ops-1`..`-3`, `PL-RES-47`), transfers page
    uncompressed (`PRAC-72`), base rig walks the NAS every 5 min (`PRAC-74`),
    onnxruntime probe costs 740 MB (`PRAC-76`), one-file exe extracts 232 MB
    per start and looks like a dropper to EDR (`PRAC-77`).
12. **B-roll, music and YouTube sub-apps.** Archive name collisions by case,
    partial upserts wiping metadata, a publish losing an ingest batch, music
    on a site with no GPU, music index rebuilds, the YouTube switch not
    stopping the server worker. Ids: `bug-broll-1`..`-7`, `bug-music-1`..`-7`,
    `bug-ytdl-web-1`, `-2`, `bug-comp-media-2`, `-3`, `bug-comp-ytdl-2`.
13. **Server and installer mediums.** Editor-account script can take over
    admin/root, docker stop kills uvicorn early, Postgres profile, live DBs in
    an editor-writable share, wizard re-run downgrades the companion, drive
    letter held by a real volume read as free, any running Syncthing taken as
    ours, all inbound SMB blocked (`bug-installer-7` = `COM-M56`), Windows long
    paths (`PL-RES-12`), read-only sync root (`PL-RES-13`). Ids:
    `bug-server-4`..`-10`, `bug-installer-3`..`-7`, `PL-RES-11`..`PL-RES-13`.
14. **Legal, privacy and open-source notices.** TELEMETRY.md no longer matches
    the wire, the idle switch leaks a signal, transcripts kept indefinitely in
    AI stores, retention not configurable, IPs not listed, GPL packages in the
    images without a notice, CLAP model unlicensed in the inventory, yt-dlp
    and llama.cpp mislabelled, Cards code outside every licence document. Ids:
    `COM-M1`, `COM-M2`, `COM-M12`..`COM-M24`, `COM-M40`. (commercial.md
    "Legal", "Privacy", "Open-source".)
15. **First-studio assumptions (tenancy).** Tree layout, `Creators_Club`
    archive folder, Taiwan Chinese query expansion by default, real names in
    fixtures, studio defaults reaching new sites. Ids: `COM-M41`..`COM-M46`,
    `PRAC-95`, `COM-L1`, `COM-L7`, `COM-L8`.
16. **Engineering process.** No release exit criteria while each hunt still
    finds about ten highs, no code review or protected main, no per-test
    timeouts, skipped tests leave CI green, KNOWN_BUGS.md cannot say what is
    open (`PRAC-62` = `COM-M68`), no release checklist or version-skew test.
    Ids: `COM-M64`..`COM-M70`.

---

## 5. Coverage gaps (merged from all four passes)

What no hunter reached, so a clean result there means "not looked at", not
"fine". Track C covers the parts that matter most for the first sale.

- **Nothing live.** No pass touched the deployed dashboard, a NAS, a tailnet,
  GitHub, a running Resolve, a real frozen exe or a real container. The
  appliance findings were traced in compose and code, not run. Page timings
  came from a desktop, not NAS CPU. The live vendor feed, GHCR tags and branch
  protection were not queried.
- **Platforms.** No real Mac run anywhere (Mac tray, quit events, TCC, the
  CR-68 probe, psycopg2 dylibs, Developer ID). macOS SMB hard mounts, exFAT
  normalisation, APFS power loss; Synology btrfs quotas, DSM restore paths and
  DSM API depth; whether TrueNAS middleware escapes `$`; Windows long paths
  (this rig has them enabled); no non-English Windows; no screen reader.
- **Companion code not read in depth.** `syncthing_lane.py`,
  `syncthing_supervisor.py`, `drive_reminder.py`, `server_locate.py`, express
  batching; `proxy_scan.py`, library.py timeline SQL, `luts.py`; most tray
  line producers and dialog builders; b-roll stand-ins, `bpg.py`, the VLM
  sidecar lifecycle, the rest of proxy_gen; config.py DEFAULTS; every process
  wait having a time limit beyond rclone and jobs.
- **Dashboard code not read in depth.** api.py view builders, the queue view,
  `upsert_machine_state`, cards/ytdl/triage tables, invariants 8 and 10+, the
  64 alert checks (sampled), `health.py` why-not-syncing, the NAS client API
  shapes, the setup engine's tailnet login, `cli_tools` pty sign-in, the
  sub-apps' own auth, session store internals, the ~300 `detail=` strings, a
  full innerHTML/XSS audit of the four SPAs, phone-width layout, and SQLite
  contention and WAL checkpointing under 50 machines.
- **Sub-apps and other repos.** Most of the b-roll and music indexers and
  their own SQLite writers, the CLAP index at scale, ytdl prompts and parsers,
  the Timeline Cards engine side of the agent protocol (other repo, no CI),
  Cards edit-chat prompt injection, Android, the macOS wizard internals.
- **Server, install and release tooling.** `check_health.py`,
  `install_syncthing_app` beyond the GUI binding, `build_editor_package.ps1`,
  most of `macos_bootstrap.sh`, `release_macos.sh`, `ship.ps1`,
  `ship_gates.ps1`, `publish_package.py`, `sign_release.py`,
  `build_dashboard_bundle.py`, the body of `publish_feed.py`; images never
  built or scanned.
- **Third-party terms not read in full.** Blackmagic, Google/YouTube, OpenAI,
  DeepSeek, Synology DSM; the yt-dlp combined-binary licence and CLAP training
  data terms come from the hunters' knowledge.
- **Verification depth.** Only criticals and highs were adversarially
  verified; mediums and lows carry the hunters' own confidence. The full test
  suites were not run by any pass.

Per-pass detail: bugs.md "Coverage gaps", resilience.md "Coverage gaps",
practicality.md "Coverage gaps", commercial.md "Coverage gaps".

---

## 6. Suggested order of work

1. **Commit the tree and fix the stop-ship (GL-00, GL-69 first half).** It is
   a one-line compose fix plus a test, and nothing else can be proved on the
   appliance until someone can sign in. Commit the uncommitted CR-356..358
   work with its version bumps first, so every wave below starts from a clean,
   gated base.
2. **Start the long-lead owner items the same day (GL-41, GL-42, GL-47,
   GL-43).** Certificates take weeks and need the legal entity settled; the
   key ceremony and the vendor domain/org move must happen before customer 1
   because both are baked into what customers install; the order form and
   support terms gate the first quote. None of these needs code to start.
3. **Wave A2, data loss on removal (GL-12..GL-14).** Small, contained,
   companion-only, and the only items where a customer permanently loses
   footage behind a promise that nothing will be lost. Ship it to the studio
   fleet straight away; it helps today, not just at launch.
4. **Decide the install story and v1 scope (GL-40, GL-48, GL-45).** These
   decide how much of wave A1 is needed and what can be hard-disabled instead
   of fixed (Cards, YouTube, triage and the CLI relay leave scope, which also
   retires GL-31's harder half and several mediums).
5. **Waves A3 and A4 together (trust and release pipeline, GL-15..GL-26).**
   They touch the same release and auth code, and GL-17, GL-24 and GL-26 all
   wait on the owner items in step 2. Order inside: GL-20..GL-23 (rollback)
   first, because every later fix reaches customers through that path.
6. **Wave A1, the appliance (GL-01..GL-11), then GL-60/GL-61 on the staging
   boxes (GL-65).** If step 4 chose a vendor-performed install, do GL-02,
   GL-03, GL-08, GL-10 and GL-11 (they apply to both paths) and run GL-62
   instead.
7. **Wave A5, installers (GL-27..GL-30), then GL-63/GL-64** on stock Windows
   and a Mac. GL-27 also wants a repair shipped to the studio's own machines.
8. **Wave A6 (GL-32..GL-35) and the counsel visit (GL-51), then cut the
   release candidate**: full gate, sign, soak on the studio fleet, run GL-66
   and GL-67, publish. Then work section 4 theme by theme, starting with
   themes 1, 2 and 5 (they are about not losing work).
