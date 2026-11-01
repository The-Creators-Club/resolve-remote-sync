# Pre-launch commercial review: com-ops-at-scale

Lens: running N customers as a small vendor. Manual steps per new customer,
per release and per incident; dependence on the base rig and Alex's terminal
(ship.cmd password prompt, DPAPI secrets, offline release key); the vendor's
view of customer health (or the deliberate lack of one); bus factor; what has
to be automated before customer 3 and before customer 10.

Read: `docs/COMMERCIAL_READINESS.md` (whole), `docs/RELEASE_PATHWAYS.md`,
`docs/RELEASE.md` (whole-release, publish_latest, staged rollout/soak/recall,
code signing), `docs/INSTALL.md` §1-2, `docs/APPLIANCE_INSTALL.md`,
`docs/ZERO_TOUCH_PLAN.md` (work packages), `docs/SECRETS.md` (still owed),
`docs/PRODUCT_REPO.md` (owed), `docs/RELEASE_FEED.md` §7, `docs/CARDS_DEPLOY.md`,
`dashboard/deploy/compose.appliance.yaml`, `.github/workflows/image.yml`,
`dashboard/src/ccsync_dashboard/{release_feed,package_store,setup_engine,settings}.py`
(the parts on the feed, the policy, the soak gate and the wizard's
software/release-key tasks), `tools/{release_key,publish_latest,ship,load_secrets}.*`,
`companion/src/ccsync_companion/config.py` (`REQUIRES_DASHBOARD`), the local
feed mirror `feed/channel.json` (generated 2026-09-26), `git tag`, KNOWN_BUGS
(CR-66 deferred list, CR-6). Checked that `~/.ccsync-release/release.key`
exists and what its ACL is. I did not read the key.

Not covered: the live channel on GitHub, the live GHCR tags, or any customer
site. These were deliberately not touched. Legal, pricing and the security
surface are left to the other lenses, except where they set how much
operating effort each customer costs.

---

### com-ops-at-scale-1 - An appliance customer gets no updates at all unless they hand-edit two vendor constants into a compose file that says "do not edit"

- **Severity:** high
- **Confidence:** CONFIRMED
- **Where:** `dashboard/deploy/compose.appliance.yaml:35-42,160-174`; `dashboard/src/ccsync_dashboard/settings.py:429,438,913-916`; `dashboard/src/ccsync_dashboard/setup_engine.py:1476-1545`; `dashboard/deploy/Dockerfile` (no `DASH_RELEASE_*` ENV)
- **What:** `release_feed_url` defaults to `""` and `release_pubkeys` to `()`. The image sets neither, and neither does the appliance compose. Its header says "NOTHING ELSE ON THIS FILE ... SHOULD BE EDITED" and claims `DASH_RELEASE_PUBKEYS` is "generated" at first boot, but nothing generates or adopts it. It cannot be generated anyway, because it has to be the vendor's public key. With the URL unset, the feed thread never starts (`app.py:866`). The wizard's "Signing key for updates" task then tells the customer to set "the public half of your release key" and redeploy, pointing at `docs/RELEASE.md`, which is the vendor's internal runbook.
- **Scenario:** A new customer follows APPLIANCE_INSTALL.md exactly. The wizard ends with "Software for editors: no companion build is current" and "no release signing key". The customer has no `[ INSTALLER ]` to give editors and never gets a dashboard OTA, a companion update or a recall. Each of these becomes a support ticket, and each fix is a compose edit plus a redeploy that the vendor has to talk them through.
- **Recommendation:** Bake the vendor feed URL and the vendor public key(s) into the image as defaults (ENV in the Dockerfile, or constants in settings.py), with the environment variable as an override for air-gapped or test sites. Change the setup_engine copy so it no longer says "your release key". Add a test that pins the appliance stack booting with a configured feed.
- **Known:** not recorded. Related: WPK-2 ("the first OTA needs DASH_RELEASE_FEED_URL set and one manual redeploy"), which describes this per-site step as expected rather than as a defect.

### com-ops-at-scale-2 - The generic customer install guide tells the customer to mint their own release key, which cuts them off from the vendor feed

- **Severity:** high
- **Confidence:** CONFIRMED
- **Where:** `docs/INSTALL.md:210-236` (Step 6); `docs/ZERO_TOUCH_PLAN.md:284` (WP E: "retire the customer-side key generation from INSTALL.md; release_key.py bake becomes a vendor-only step")
- **What:** `INSTALL.md` is described as the guide for "someone who has never seen this repository". Its Step 6 runs `release_key.py new`, sets `DASH_RELEASE_PUBKEYS` to that key and `bake`s it into the companion. In other words, the customer becomes their own release authority and builds their own companion. Every vendor-feed record is signed with the vendor key, so the customer's dashboard rejects all of them (`release_feed._valid_records`). Vendor-built companions trust only the vendor key, so the customer's own signed publishes are refused by any companion they downloaded from us. WP E said to remove this step. It is still there.
- **Scenario:** Customer 2 follows INSTALL.md. Their dashboard silently drops every vendor record ("release signature rejected" in the log), the Packages page shows nothing from the vendor, and the only working path left is to build PyInstaller binaries themselves. That is unsupportable, and it voids the code-signing story.
- **Recommendation:** Rewrite Step 6 as "pin the vendor key", with the published vendor public key and its id printed in the doc and on the feed. Move key generation into RELEASE.md as a vendor-only step. Use the same text in APPLIANCE_INSTALL.md and in the wizard.
- **Known:** not recorded (WP E lists it as owed).

### com-ops-at-scale-3 - Customers are frozen on dashboard 0.7.44 while the studio runs 0.7.73: the customer release train is a set of manual side steps that stopped being run

- **Severity:** high
- **Confidence:** CONFIRMED (local feed mirror as of its last publish on 2026-09-26, and local tags. The live GitHub channel and GHCR were not read.)
- **Where:** `feed/channel.json` (dashboard/linux 0.7.44 published 2026-09-11; `dashboard_image.tag` 0.7.24); `git tag` (newest `v0.7.44`); `.github/workflows/image.yml` (`:1` moves only on a `v*` tag); `tools/publish_latest.py` (does not sweep dashboard bundles, per its SOURCES comment and RELEASE_PATHWAYS.md); `companion/src/ccsync_companion/config.py:174` (`REQUIRES_DASHBOARD = "0.7.23"`); `tools/publish_latest.py:508-520` (kind extras off, so `requires_dashboard` is never signed)
- **What:** A customer's server code reaches them in three ways. Each is a separate hand-run step and none runs automatically: (a) `build_dashboard_bundle.py` plus `publish_feed.py --kind dashboard`, (b) a `v*` git tag that moves the `:1` image every appliance pulls, and (c) `dashboard_image` in the channel. The studio deploys itself by digest and by snapshot, so its own releases never pass through (a), (b) or (c). Feed and `:1` customers are therefore 29 dashboard versions behind, which covers every hunt fix since 2026-09-11 (CR-282..CR-361, the 09-18/09-24 highs, LG-1's site-side strip of withheld report fields, the account page). Meanwhile companions keep flowing (0.9.82 current, 0.9.84 staged). CLAUDE.md repeatedly says "deploy the dashboard before the companions", but that ordering is not enforced for customers: `REQUIRES_DASHBOARD` was not raised past 0.7.23 when the account page / `commands.machine_settings` (dashboard 0.7.60, companion 0.9.80) landed, and kind extras are off, so the field is dropped from the signed record anyway.
- **Scenario:** A customer installs today. They get dashboard 0.7.44 (or older on `:1`) with companion 0.9.82. This is the "old dashboard, new companion" combination CLAUDE.md warns about for v28, v36, v58 and LG-1. Their GDPR-relevant site-side field stripping does not exist, and none of the fixed security highs reach them.
- **Recommendation:** Make "release to customers" one command that does all three (bundle plus feed record, tag plus `:1`, channel `dashboard_image`), and gate it on the same green CI run. Add a CI or ship check that fails when the feed's dashboard trails `main` by more than N versions. Raise `REQUIRES_DASHBOARD` to what 0.9.80+ actually needs. Decide the kind-extras overlap now, while the install base is one studio, because it gets more expensive with every customer. Settle the `:1` tagging policy (release-pipeline-9) before customer 1.
- **Known:** release-pipeline-9 (KNOWN_BUGS CR-66, deferred, OPEN) covers the `:1` half. The stall itself is not recorded.

### com-ops-at-scale-4 - The soak gate makes every release a manual step at every customer: `policy = "current"` stages and waits for that customer's own canary

- **Severity:** high
- **Confidence:** CONFIRMED
- **Where:** `dashboard/src/ccsync_dashboard/release_feed.py:1030-1090` (`_apply_policy` goes through `package_store.make_current`); `dashboard/src/ccsync_dashboard/package_store.py:79-118,172-350` (soak refusal; `force` is never passed by the unattended door; the exceptions are rollback and bootstrap only)
- **What:** Since REL-1 (2026-09-04), a feed record cannot become current at a site until at least one machine at that site has run that exact version for 30 minutes with no crashes. On a `current` site, the poller stages the build and logs a warning. A machine only runs a staged build if a local admin presses `[ PUSH TO ONE MACHINE ]`, waits, then presses `[ MAKE CURRENT ]`. The vendor's own soak on the studio fleet is not carried in the signed record, so every customer has to repeat it.
- **Scenario:** With 10 customers, each release needs 10 admins to notice a staged build, pick a canary, wait 30 minutes and click. Most will not do it. Their fleets stay on the old build while the grid reads "up to date" against their own current pointer. A security fix then reaches almost nobody, and the vendor cannot see that (see -6).
- **Recommendation:** Have the vendor sign a soak attestation into the channel (for example `soaked: {machines, minutes, at}` after the studio canary passes), and let a `current` site accept that as evidence, with the local soak kept as an opt-in for cautious customers. Alternatively ship a staged-ring policy (`current-after-vendor-soak`). Whichever is chosen, document the per-customer behaviour in the customer docs and the wizard.
- **Known:** REL-1 / SYS-6 (FIXED as designed). The per-customer operating cost is not recorded.

### com-ops-at-scale-5 - There is no supported way for a new customer to install without the vendor at Alex's terminal holding the customer's NAS admin credentials

- **Severity:** high
- **Confidence:** CONFIRMED
- **Where:** `docs/APPLIANCE_INSTALL.md:1-17,152-175` (DRAFT; "NOT YET TRUE": no Serve, no invites, nothing publishes builds, nothing schedules snapshots; never run by a non-author); `docs/INSTALL.md:26-63,85-95` (needs a Windows "base rig" with a git checkout of this repo, Python, PyInstaller and a Mac for Mac editors); `docs/PRODUCT_REPO.md:229-259` (product repo export blocked); `docs/ZERO_TOUCH_PLAN.md:280-289` (WP B half, C sshd half, E, F, G, I owed)
- **What:** There are two install paths. The appliance path cannot publish the dashboard on the tailnet, so editors cannot reach it. It also has no invite flow, no snapshot schedule and no feed (see -1). The base-rig path assumes the customer has this proprietary repository, a Windows build box and the skill to run `install_dashboard_app.py`, `setup_snapshots.py`, `secure_syncthing_gui.py` and the rest over SSH. In practice, then, every install is Alex (or a Claude session on his rig) holding the customer's `TRUENAS_PW` or API key in a DPAPI store on the studio's editing workstation, with a per-customer `site.toml` and `load_secrets -Path`. That is hours of skilled work per customer, plus custody of a root-equivalent credential for each customer's storage.
- **Scenario:** Customer 3 is signed. The vendor has to schedule a remote session, collect their NAS admin password, run eight install steps and a per-platform runbook from the studio rig, and repeat the work by hand for every site change (`--recreate`). By customer 10 the vendor rig holds ten NAS root credentials, which is a single point of compromise.
- **Recommendation:** Before the first sale, either (a) finish WP B (Serve), WP F (invites), WP G (snapshot/backup) and com-ops-at-scale-1 so the appliance is self-install, and have a non-author run it end to end on clean TrueNAS and DSM boxes, or (b) state in writing that installs are vendor-performed, price it, and write a credential-custody policy (scoped API keys only, deleted after install, a per-customer vault rather than DPAPI on a workstation). Decide which before signing anyone.
- **Known:** ZERO_TOUCH_PLAN WPs B, C, E, F, G, I (owed, OPEN). Not in KNOWN_BUGS as a launch gate.

### com-ops-at-scale-6 - The vendor has no view of its install base: no customer registry, no versions, no health. Fleet-wide decisions are made against one studio's fleet page

- **Severity:** high
- **Confidence:** CONFIRMED (by absence: the feed fetch carries no site identity, there is no phone-home or heartbeat route, and crash-report send is "opt-in the shipped builds cannot even satisfy")
- **Where:** `dashboard/src/ccsync_dashboard/release_feed.py:160-250` (anonymous GET, no site id or version header); `docs/COMMERCIAL_READINESS.md:331` (crash reporting local only); `docs/RELEASE.md:966-985` (kind extras: "turn it on only once every machine on the fleet page reports 0.9.55"); `docs/RELEASE.md:712+` (key rotation needs an overlap release); `docs/ZERO_TOUCH_PLAN.md:286` (WP G redacted support bundle, unbuilt)
- **What:** Several vendor-side actions are only safe when you know the oldest companion and dashboard in the field: signing kind extras, rotating the release key, raising `min_version`, dropping a migration shim, retiring the shared fleet token. The tooling answers those questions from the studio's own fleet page. Across N customers the vendor cannot tell who is on what, who took a recall, whose fleet is crash-looping, or whether anyone is still on a build that would refuse the next record format. Support has the per-machine diagnostics and a crash-reports zip, but each one has to be requested by hand from the customer admin. There is no site-level support bundle.
- **Scenario:** The vendor enables kind extras once the studio is on 0.9.55+. A customer with an old laptop on 0.9.40 now refuses every future record with "release signature rejected". The EULA says there is no over-the-air recovery, and the vendor finds out from an angry email weeks later.
- **Recommendation:** Decide the policy explicitly (privacy and EULA say the Licensor receives nothing). Then build either an opt-in, documented, minimal heartbeat (site id, dashboard version and runtime_id, the companion version histogram, count of open alerts, no names or paths) sent with the feed poll, or a one-click "send support bundle to vendor" (WP G) and a vendor-side customer registry of contacts, versions and contract. Add the heartbeat fields to `docs/legal/TELEMETRY.md` and PRIVACY. Needed before customer 3. Without it every overlap release is guesswork.
- **Known:** WP G (unbuilt). SYS sweep proposal at `docs/resilience-sweep-2026-08-28/SYS.md:88-93` (partly built for machines, not for the vendor).

### com-ops-at-scale-7 - One plaintext release key on the studio's everyday editing workstation signs code that every machine at every customer will run

- **Severity:** high
- **Confidence:** CONFIRMED (location, format and ACL. A backup is recorded: `backup.json` dated 2026-09-26.)
- **Where:** `tools/release_key.py:1-27,95-106` (raw base64 seed, no passphrase by design, "0600", which on Windows sets no ACL); `%USERPROFILE%\.ccsync-release\release.key` (ACL: SYSTEM, BUILTIN\Administrators and alex all have full control, inherited); `docs/RELEASE_PATHWAYS.md` ("CI builds, this rig signs"); `docs/INSTALL.md:225-232` (losing it means reinstalling every machine)
- **What:** The same Ed25519 key authorises companion binaries, onboarding installers and dashboard OTA code bundles for every customer. It sits as a plaintext file on `creator-1`, which is also the studio's base rig: it edits footage, runs the GPU indexers, runs Resolve and runs autonomous Claude Code sessions with wide file access, including sessions that process untrusted text (YouTube titles, customer transcripts). Any process running as `alex`, or any administrator, can read it. One leak means signed code execution on every editor workstation and every dashboard container across all customers. Recovery would be a manual reinstall of every machine at every customer, because companions trust only keys already baked in.
- **Scenario:** A malicious dependency in an unrelated project on the rig, or a prompt-injected agent session, copies `release.key`. The attacker signs a companion "0.9.99". Every `current`-policy site stages it, and every admin who presses MAKE CURRENT pushes it to the whole fleet.
- **Recommendation:** Move signing to a dedicated device before customer 1: a YubiKey or HSM-backed Ed25519 key, or an offline signing laptop that is used for nothing else, with the seed escrowed in two physical places. Consider a root key plus a short-lived signing subkey so a compromise can be revoked without reinstalling everyone. Write a "key compromised" runbook covering the feed recall, the advisory, the overlap release and customer comms. Keep agent sessions off the signing machine. The future Authenticode EV token raises the same custody question (`RELEASE.md` release-pipeline-11, undecided).
- **Known:** CR-6 (signing, OPEN for certificates). Custody on a shared workstation is not recorded.

### com-ops-at-scale-8 - Bus factor of one, and no support or incident operating model behind the EULA's "support plan"

- **Severity:** high
- **Confidence:** CONFIRMED (artefacts absent; dependencies read from the tools)
- **Where:** `docs/legal/EULA.md:128-130` ("Support and updates are provided as described in your order or support plan". No such document exists in the repo, and there is no SLA, support contact or status page anywhere in `docs/`); `tools/ship.ps1` (interactive admin password, by design); `tools/load_secrets.ps1` (DPAPI, this Windows account on this machine only); `tools/publish_latest.py` (needs `gh auth` on this rig plus the local key); `docs/RELEASE.md:1218-1230` (EV token physically at the signing machine)
- **What:** Every release and every incident action needs things that exist only on one Windows account on one machine: the release key, the `gh` login to the org that hosts the feed and the image, the DPAPI operator secrets, the interactive dashboard password, and (later) the EV token. The owner has said he is non-technical and that engineering is done by AI sessions working from CLAUDE.md, KNOWN_BUGS.md (about 12k lines) and memory notes. There is no second human operator, no "vendor unavailable" runbook, no on-call, no severity matrix, no response targets, no customer-facing support channel and no source escrow. A buyer's due diligence, or their procurement team, will ask for each of these.
- **Scenario:** The rig's disk dies, or Alex is away for two weeks, during an incident at a customer (for example a lane B deletion regression). No one can sign a fixed build, move the channel pointer or reach the customer's admins, and the customer has no contractual expectation to measure against.
- **Recommendation:** Non-code artefacts, all for the owner, with counsel on (c) and (d): (a) a support policy with severity levels, hours, response targets, channel and contact; (b) a second named operator (a contractor is enough) with documented, tested access to a backup signing path and the GitHub org; (c) source and key escrow terms for enterprise buyers; (d) the "order form / support plan" document the EULA points to. Code: a rig-independent restore drill (rebuild the release rig from docs on a clean box and publish a no-op build), run before customer 1.
- **Known:** not recorded.

### com-ops-at-scale-9 - A recall reaches customers within a day at best, and does not stop the bad build running

- **Severity:** medium
- **Confidence:** CONFIRMED
- **Where:** `dashboard/src/ccsync_dashboard/release_feed.py:499-523` (`apply_retractions` un-currents only); `dashboard/src/ccsync_dashboard/settings.py:463` (`release_feed_interval` 86400 s); `dashboard/src/ccsync_dashboard/alerts.py:2711-2723` (the `retracted_running` alert, delivered only if the site configured a sink); `docs/RELEASE.md:936-945` (`[ ROLL THE FLEET BACK ]` is a click)
- **What:** The vendor's only lever over customer fleets is the signed channel. A recall is seen at the next daily poll. It stops the build being offered, but machines already on it keep running it until the site admin presses ROLL THE FLEET BACK. On a `manual` site (the default) the previous build does not automatically become current again either. The feed has no advisory field, and the vendor has no list of customer admins to email.
- **Scenario:** A companion release has a data-destroying lane bug (the CR-11/B16 class). The studio sees it within an hour and retracts. Customers poll up to 24 hours later, their alert sink is "none" (the vendor default), and their fleets keep running the bad build for days.
- **Recommendation:** Poll the small `channel.json` hourly (it is a few KB), or at least re-check retractions more often than full records. When the site previously had an `ever_current` older build, have a recall automatically move current back to it (a rollback, which the soak gate already exempts). Add a signed `advisories[]` field that renders as a banner and an alert. Keep a vendor-side contact list (from -6) for out-of-band notice.
- **Known:** REL-3 (recall, FIXED as designed). Latency and the absence of auto-rollback are not recorded.

### com-ops-at-scale-10 - Vendor infrastructure lives in the studio's GitHub org and is baked into every customer's compose

- **Severity:** medium
- **Confidence:** CONFIRMED
- **Where:** `dashboard/deploy/compose.appliance.yaml:88,147,291` (`ghcr.io/the-creators-club/ccsync`); `server/install_dashboard_app.py:1428` (`DEFAULT_CONTAINER_IMAGE`); `tools/publish_latest.py:46`, `tools/ship.ps1:205` (`The-Creators-Club/ccsync-releases`); `site.toml:47`; `docs/legal/EULA.md:16,200` (Licensor = Cablewrap Creative Ltd.)
- **What:** The feed, the image registry, CI and the signing workflow all sit under `The-Creators-Club`, which is the studio, while the EULA names a different contracting entity. The image path is a default in every customer's compose, and the feed URL is typed into every site. Moving to a vendor-owned org or domain later would break `:1` pulls and feed polling at every site that does not hand-edit its config.
- **Scenario:** The studio and the vendor separate (sale, dispute, account suspension, or a competitor studio as a buyer that objects). Every customer's update path dies with the org, and the vendor has no channel left to tell them (see -9).
- **Recommendation:** Before customer 1, put the feed behind a vendor-owned domain (for example `releases.<vendor>.com`, which can 302 to wherever it is hosted) and the image behind a vendor-owned registry namespace, owned by the contracting entity with at least two admins. Put those names, not GitHub paths, into the image defaults (-1).
- **Known:** image.yml's own comment notes "the org that publishes it may not be this GitHub org forever". Not recorded as a launch item.

### com-ops-at-scale-11 - No entitlement: anyone with the public feed, image and key gets updates for ever, and finance has nothing to enforce a subscription with

- **Severity:** medium
- **Confidence:** CONFIRMED (anonymous feed GET; `install_dashboard_app.py:1415` notes the GHCR package is public; no licence key, seat count or customer id anywhere in dashboard or companion source)
- **Where:** `dashboard/src/ccsync_dashboard/release_feed.py` (no credential on the fetch); `.github/workflows/image.yml`; `docs/legal/EULA.md:40,181` ("fees", "term of your licence or subscription")
- **What:** The EULA sells a term licence or subscription. Nothing in the product knows who the customer is, whether they have paid, or when the term ends. A churned customer, or anyone who copies one compose file, keeps receiving signed builds and dashboard OTAs. The vendor also cannot count installs for billing.
- **Scenario:** A customer stops paying after year 1 and keeps updating. A reseller deploys it to a third studio. The vendor cannot tell either case apart from a paying customer.
- **Recommendation:** This is a business decision first (owner and finance): perpetual plus maintenance, or a subscription. If updates are gated, issue a per-customer feed token (an authenticated feed URL, or a signed entitlement the dashboard presents), expiry-aware, failing open for security recalls. This can share the plumbing with the heartbeat in -6.
- **Known:** not recorded (the com-licensing-billing lens may cover the pricing side).

### com-ops-at-scale-12 - Timeline Cards cannot be delivered to a customer by any release channel

- **Severity:** medium
- **Confidence:** CONFIRMED
- **Where:** `docs/CARDS_DEPLOY.md:1-40`; CLAUDE.md "Timeline Cards" (`DASH_CARDS_SRC`, "never in the image or an OTA bundle"); the Dockerfile, bundle builder and appliance compose have no cards content
- **What:** `/cards` imports another repo's checkout that the studio's installer copies to `<host-root>/cards-web`. No feed record, image or bundle carries it, so a feed or appliance customer cannot get it and a vendor-installed customer gets a snapshot that only a base-rig re-ship updates.
- **Scenario:** Sales demos the phone cut-staging feature from the studio. The customer installs and `/cards` is absent (tri-state "not configured"). Or the vendor hand-ships it to each site and has to re-ship it by SSH on every Cards change.
- **Recommendation:** Decide whether Cards is in v1. If yes, vendor it into the image or bundle as a pinned wheel, or as a fourth signed feed kind. If no, hide the menu entry and the marketing copy for customers.
- **Known:** not recorded.

### com-ops-at-scale-13 - No staging environment: the studio's production fleet is the only TrueNAS test bed, and the DSM target is a borrowed box

- **Severity:** medium
- **Confidence:** PLAUSIBLE (no staging or lab NAS appears in docs or tooling. The DSM unit at the `SYNOLOGY_PORT_PLAN.md` target is described in `PRODUCT_REPO.md` as "someone else's live box".)
- **Where:** `docs/RELEASE.md` (soak = studio machines); `docs/APPLIANCE_INSTALL.md:15-17`; `docs/PRODUCT_REPO.md` marker table (192.168.0.104)
- **What:** Every release is tested on the studio's live NAS and editors. Nothing exercises a fresh appliance install, an upgrade from the oldest supported customer version, or a DSM site before a build reaches the feed. With N customers on varied TrueNAS and DSM versions, the first sign of a platform-specific regression will be a customer's broken fleet.
- **Recommendation:** Buy or reserve one TrueNAS SCALE box and one DSM box (or VMs) for the vendor. Script a release gate on them: a fresh appliance install, an upgrade from the oldest supported version, one editor on each OS. Run it before every `--make-current` to the feed.
- **Known:** not recorded.

### com-ops-at-scale-14 - Customers get one-line notes, no changelog and no security advisories

- **Severity:** low
- **Confidence:** CONFIRMED
- **Where:** `docs/RELEASE.md:1396-1416` (`--notes`, one line, unsigned); repo root (no CHANGELOG); KNOWN_BUGS.md is internal and withheld from the product repo (`docs/PRODUCT_REPO.md`)
- **What:** An admin deciding whether to press MAKE CURRENT, or whether to do a runtime update in the NAS UI, sees one sentence. There is no per-release page saying what changed, what order to deploy in, or what is security-relevant.
- **Recommendation:** Publish customer-facing release notes per version (generated from a curated section, not from KNOWN_BUGS), link them from the record's `notes`, and keep a security advisories page. These feed -9's advisory banner.
- **Known:** not recorded.

### com-ops-at-scale-15 - Every fresh install greets the customer's IT with "Windows protected your PC" and Gatekeeper refusals, and where the cert key will live is undecided

- **Severity:** medium
- **Confidence:** CONFIRMED
- **Where:** `docs/RELEASE.md:1201-1327` ("none of this has ever run against a real certificate"; release-pipeline-11 undecided); `feed/channel.json` records `signed_binary: false`
- **What:** Per customer, this is a recurring support load: allowlisting requests, AV quarantine and Mac Full Disk Access re-grants. The decision between signing on the rig (EV token at Alex's desk, which deepens -8) and signing in CI (contradicts the release-key policy) is still open.
- **Recommendation:** Buy the certificates. Decide release-pipeline-11 together with -7's signing-device decision, so one dedicated signing station holds both keys. Do one real signed and notarised build end to end before customer 1.
- **Known:** CR-6 (OPEN for the purchase), release-pipeline-11 (OPEN).

---

## What must be automated, by milestone

- **Before customer 1:** -1, -2, -3 (one customer-release command; `:1` policy), -5 (pick self-install or vendor-install, in writing), -7 (signing device), -8 (support policy, second operator), -10 (vendor-owned namespace), -15.
- **Before customer 3:** -4 (vendor soak attestation), -6 (registry plus opt-in heartbeat or support bundle), -9 (faster recall, auto-rollback, advisory), -11 (entitlement decision), -13 (lab NAS release gate).
- **Before customer 10:** credential custody out of DPAPI on a workstation (vault), an installs-per-week capacity plan (each vendor-run install is hours), and -12/-14 settled.
