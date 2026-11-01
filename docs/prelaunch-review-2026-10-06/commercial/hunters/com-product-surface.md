# Pre-launch commercial review - lens `com-product-surface`

Date 2026-10-06. Tree: HEAD `08b40eb` plus the uncommitted working tree as it
stood. Read-only; no live system touched.

**What this lens covered.** What v1 actually sells: every feature graded
READY / BETA / HIDE FOR V1 / CUT on code maturity, open KNOWN_BUGS, test
depth, and dependence on one person's machine, repo or account; and the
platform matrix (OS, Resolve, NAS, browser, network) as the docs state it and
as the code enforces it. Sources read: `docs/COMMERCIAL_READINESS.md`,
`KNOWN_BUGS.md` (open headings + CR-5/6/137/280/333 + MUSIC-ING/BROLL-ING
open items), `docs/INSTALL.md`, `docs/APPLIANCE_INSTALL.md`,
`docs/RELEASE_FEED.md`, `docs/BACKUP_RESTORE.md`, `docs/CARDS_DEPLOY.md`,
`docs/SERVER_TRIAGE_AGENT.md`, `docs/ANDROID.md`, `docs/MOBILE.md`,
`docs/CLIENT_FOLDERS.md`, `docs/SERVER-SYNOLOGY.md`, `docs/LOOPBACK_API.md`,
`docs/legal/EULA.md` + `PRIVACY.md`, `installer/README.md`,
`site.example.toml`, `feed/channel.json`, and the code paths cited below
(`cards.py`, `cards_ai.py`, `settings.py`, `ui.py`, `topbar.html`,
`routes_client_folders.py`, `client_folders.py`, `broll_index/config.py`,
`claude_cli.py`, `resolve_prefs.py`, `sidecar_tools.py`, `config.py`,
`rescore.py`, `install_dashboard_app.py`, `publish_latest.py`). Test counts
are `def test_` greps per suite.

**Not covered:** pricing/entitlements (sibling `com-licensing-billing`),
security internals of each feature, a live check of GitHub/ghcr visibility,
the MulticamPipeline repo itself.

## Feature inventory and grade

| Feature | Grade | Why |
|---|---|---|
| Sync core (lanes A/B/C, tray, popup/fixer, proxy gen, BPG, LUT link, file moves, fleet halt, breaker, per-machine plans, upload-only ticks) | **READY** (Windows), BETA (macOS) | The product. ~6.3k companion + ~4.6k dashboard tests, eleven hunts, running on four machines. Many fixes are "FIXED in repo, unbuilt" (CR-350, 351, 356-361), so a release candidate must be cut; CR-333 open (low). Mac: see -8. BPG is Windows-only UI automation. |
| Dashboard admin (users, sync plans, packages, health, alerts, recovery, setup wizard, account page, data export/erase) | **READY** | Mature, scheduled self-diagnosis, LG-1..LG-5 built. JOBS page should be hidden with Cards (-2). |
| B-roll search + ingest (`/broll`) | **READY**, on by default | Generic taxonomy, local or API indexing, companion ingest. Open: BROLL-ING-3 (polish). |
| Client folders (`/broll/share`) | **HIDE FOR V1** until a rights gate exists | -4. |
| Music search + ingest (`/music`) | **BETA** (opt-in) | Tuned and evaluated on one 376-track library (`music/README.md`), source-bias axes keyed to one catalogue's naming (`rescore.py:225`), MUSIC-ING-1..4 open, base-rig GPU fallback. |
| YouTube downloader (`/ytdl`) | **CUT from v1** (keep dormant, do not sell) | -3. |
| Timeline Cards (`/cards`), cards agent, fleet jobs (whisper / proxy-480p / audio-extract / peaks) | **CUT from v1** | -2. |
| Server triage agent | **HIDE FOR V1** | -5. |
| Mobile PWA | **READY** (https sites only) | Same pages; needs Serve/TLS. |
| Android APK (TWA) | **HIDE FOR V1** | -6. |
| AI CLI providers / auto-update of Claude Code | **HIDE FOR V1** | Off by default; exists to serve Cards + triage, both cut/hidden. |
| OIDC sign-in | **BETA** | 17 tests vs an in-process IdP, never pointed at a real IdP (COMMERCIAL_READINESS item 12). |
| Synology DSM backend | **BETA** | Verified on one test DS423+ in August; reboot survival and uid stability untested (`SERVER-SYNOLOGY.md:435-441`). |
| Appliance install (`compose.appliance.yaml` + `/setup`) | **NOT READY** | DRAFT, never run by a non-author; Serve not automated (-7). |

---

### com-product-surface-1 - There is no defined v1: every feature, finished or experimental, ships in the same image and companion with nothing marking any of it as preview
- **Severity:** high
- **Confidence:** CONFIRMED
- **Where:** `site.example.toml:303-359` ([features]); `server/install_dashboard_app.py:5103` (b-roll on by default); `dashboard/templates/partials/topbar.html:37-40`; `dashboard/src/ccsync_dashboard/ui.py:257-284` (SETTINGS_NAV_GROUPS); `docs/legal/EULA.md` sections 1-2 (no beta / preview clause); `companion/src/ccsync_companion/config.py:833` (`jobs_enabled: True`)
- **What:** The vendor image carries `/app`, `/broll-app`, `/music-app` and `/ytdl-app`, and the companion carries ytdl, music, b-roll, jobs and the Cards agent. What a customer sees is decided by a mix of site flags, env vars and whether a directory happens to exist, not by a product decision. No document lists what v1 includes, what is preview, and what is unsupported. The EULA licenses "the Software" as a whole, with no carve-out for preview features or for features that depend on the customer's third-party accounts.
- **Scenario:** A buyer's evaluator turns on every switch in `site.example.toml` because they are documented there, hits a Cards page with no code behind it (`absent`) or a JOBS page whose job kinds can never run, and files the product as unfinished. Or support is asked to fix the YouTube downloader under the same SLA as sync.
- **Recommendation:** The owner decides the v1 feature list (the table above is a starting proposal). Publish it as a one-page product sheet. Mark preview features in the EULA ("provided as-is, may change or be withdrawn") and in the UI. Have CUT features compiled out of, or hard-disabled in, the vendor build, not left to a site flag.
- **Known:** none (COMMERCIAL_READINESS predates Cards, jobs, triage and Android)

### com-product-surface-2 - Timeline Cards, the cards agent and every fleet-job kind depend on a second repository that the image, the feed, CI and the licence gate never see
- **Severity:** high
- **Confidence:** CONFIRMED
- **Where:** `dashboard/src/ccsync_dashboard/cards.py` (imports `multicam_pipeline.cards.handler` from `DASH_CARDS_SRC`); `docs/CARDS_DEPLOY.md` ("the code is another repo's checkout", shipped by `install_dashboard_app.py` from `[timeline_cards] src`, a `git archive` from the operator's disk); `companion/src/ccsync_companion/config.py:833-873` (`jobs_mulcam_pipeline`, "the MulticamPipeline checkout whose pipeline.py does the work"); `tools/gen_notices.py` and `tools/check_licenses.py` (no MulticamPipeline coverage); `dashboard/src/ccsync_dashboard/ui.py:267` (JOBS always in Settings); `companion/src/ccsync_companion/tray.py:3070-3084` (volunteer item); KNOWN_BUGS CR-133..CR-137 (OPEN, CR-137: three Cards suites red)
- **What:** `/cards` imports code from `E:\Projects\Editing\Resolve\MulticamPipeline`, which ships only by an operator exporting a commit from their own disk into the NAS host tree. It is not in the vendor image, not in an OTA bundle, not in `release_feed`, and not under this repo's CI, lockfiles, `check_licenses.py` or `THIRD_PARTY_NOTICES`. All four job kinds need the same checkout on the editor's machine (`whisper` runs its `pipeline.py`; the three media kinds are Cards recipes). The feature is also documentary-specific: interview multicams, whisper, and `->EN` translation. Its handshake with Resolve has "still NEVER RUN LIVE" (CLAUDE.md, phase 2). Even so, the JOBS settings page and the tray's "Take fleet jobs now" show on every install.
- **Scenario:** A customer reads "Timeline Cards" in the docs and sets `[timeline_cards] enabled = true`. They have no MulticamPipeline, so `/cards` reports `absent`. An admin opens Settings, JOBS and sees a queue nothing can ever drain. If the vendor did ship Cards, its dependencies would go out with no licence check and no notices.
- **Recommendation:** Cut Cards, the cards agent and fleet jobs from v1. Hide the JOBS page and the tray volunteer item unless `cards_enabled`. Selling Cards later needs three things: its code inside the product repo or a versioned, signed artefact in the feed; its suites in CI; and its dependencies in the licence gate and notices.
- **Known:** CR-133..CR-137 open (Cards); the external-repo design is documented, not tracked as a defect

### com-product-surface-3 - The YouTube downloader is not sellable in v1: open legal items, a YouTube arms race, a broken Mac path, and Taiwan-specific defaults
- **Severity:** high
- **Confidence:** CONFIRMED
- **Where:** `ytdl/web/ytdlweb/vendor/PROVENANCE.md` ("a written licence grant is OWED"); `docs/legal/YOUTUBE_FEATURE_NOTICE.md` (draft for counsel); KNOWN_BUGS CR-2, CR-5, CR-80 (cookies flagged), CR-360, CR-361 (nightly yt-dlp, unbuilt), CR-280 (OPEN: Mac requester-first never ran); `ytdl/web/ytdlweb/claude_cli.py:566-637` (`DEFAULT_TERM_SCOPE = SCOPE_BOTH`, "8 to 12 queries in Traditional Chinese as used in TAIWAN")
- **What:** The flags default off, which is correct. But the feature still lives in the vendor image and has been marketed internally as a feature. It depends on the vendored `yt-credit-downloader`, which has no licence grant. Its attestation wording has not been reviewed by counsel. It has needed a fix wave roughly every week (CR-29..39, CR-73..84, CR-360/361) as YouTube changes, now down to nightly yt-dlp builds. Every search defaults to generating Taiwanese Traditional Chinese queries alongside English, so any non-Taiwan customer pays AI tokens for queries they cannot use.
- **Scenario:** A UK customer enables it. Each search spends tokens on 8-12 Chinese queries and returns Chinese results. A YouTube change breaks downloads fleet-wide until the vendor ships a nightly. The vendor is then supporting, under contract, a circumvention-adjacent feature it has no written right to sublicense.
- **Recommendation:** Cut it from v1 marketing and the support scope. For the vendor build, either strip it from the image or hard-disable it. If it ever returns: get the PROVENANCE grant signed (owner, as author, to the vendor entity), get counsel sign-off on the notice and attestation, make the second query language a site setting defaulting to none, and get a defined support stance on YouTube breakage.
- **Known:** CR-2 (fixed in repo, counsel owed), CR-5 (awaiting counsel), CR-280 (OPEN)

### com-product-surface-4 - Client folders let any editor publish any archive clip, including the YouTube-download shares, to a public internet link offered "to licence"
- **Severity:** high
- **Confidence:** CONFIRMED
- **Where:** `broll/web/app/routes_client_folders.py:98-113` (`create_folder`, `require_user`) and `:215-231` (`add_items`, `require_user`); `broll/web/app/client_folders.py:84` (contact line "to licence, contact ..."), `:590-626` (no collection/ownership check); `broll/indexer/broll_index/config.py:37-46` (share source "originals" is "the YouTube-archive shape"; "the YouTube downloads that already have their own `originals` shares"); `docs/CLIENT_FOLDERS.md` section 3 (publish via Tailscale Funnel)
- **What:** The b-roll archive is designed to hold third-party material: YouTube downloads are their own shares, and ingested third-party footage sits beside the studio's own shoots. Client folders exist so a client "who might want to licence it" can preview and request clips at a public URL. Any signed-in editor, not only an admin, can create a folder and add any clip from any collection. No admin approval step exists, and no collection is ever refused. The clip's provenance is not shown on the add path, and an expiry is optional.
- **Scenario:** An editor builds a "Taiwan aerials" folder from a search, and it includes clips from a YouTube-download share. The client gets a public link offering those clips "to licence". The customer has offered third-party copyright material for licence on the internet using a vendor feature built for that purpose. For a security reviewer, this is also the product's first internet-facing surface.
- **Recommendation:** Before v1 enables this: let only clips from collections an admin marks "owned / licensable" (e.g. `BROLL_DEFAULT_COLLECTION` and its owned shares) be added, and refuse the rest. Make creating or publishing a folder an admin action, or require admin approval. Show each clip's collection on the folder page. Default to an expiry. Add a rights clause to the EULA's acceptable use. Pen-test the Funnel surface before it is offered. Until then, HIDE.
- **Known:** none

### com-product-surface-5 - The server triage agent only runs through a consumer Claude Code CLI and acts on emailed replies; it is an owner's ops tool, not a v1 feature
- **Severity:** medium
- **Confidence:** CONFIRMED
- **Where:** `docs/SERVER_TRIAGE_AGENT.md` section 1 ("The Anthropic API provider is NOT a fallback"); `site.example.toml:324-334` (the product's own warning that a personal subscription powering a service may breach its terms); `dashboard/src/ccsync_dashboard/triage.py`, `triage_mail.py`, `triage_actions.py`
- **What:** The feature needs `ai_cli_providers` turned on and a signed-in Claude Code CLI on the dashboard host, which is the consumer-plan path that COMMERCIAL_READINESS item 1 removed as a ToS problem. It mails fleet data to an inbox, and an authenticated reply by email can run dashboard actions. It was designed around one owner's inbox and timezone (doc's decision table).
- **Scenario:** A customer enables it with a personal Claude subscription and is out of terms with Anthropic. Or a customer's security reviewer refuses email-driven admin actions outright, and the vendor has to defend a feature it did not need to sell.
- **Recommendation:** Hide it for v1: dark in the vendor build, as Cards should be. If it is wanted as a product, give it an API-key path (the SDK can do read-only analysis over a provided evidence bundle without file tools). Keep email-driven actions as a separate, explicitly opted-in switch, and put it through a security review.
- **Known:** none

### com-product-surface-6 - The Android app is a per-customer build the customer must make, sign and sideload themselves
- **Severity:** medium
- **Confidence:** CONFIRMED
- **Where:** `docs/ANDROID.md` sections 0-2 (origin baked in at build time; JDK + Android SDK or a GitHub `workflow_dispatch`; a signing keystore); `docs/BACKUP_RESTORE.md:75` (keystore "protected by nothing"); `.github/workflows/android.yml`; `dashboard/src/ccsync_dashboard/android.py`
- **What:** The TWA is bound to one origin at build time. So there is no vendor-published app: each customer would need a toolchain or this repo's CI, their own keystore, and a way to distribute an APK. It verifies only over https, and fails silently with a URL bar otherwise.
- **Scenario:** A customer is told "there is an Android app". They have no JDK, no access to the vendor's GitHub Actions, and no Play listing, so support ends up building APKs per customer and holding customer keystores.
- **Recommendation:** v1 sells the PWA only. Hide Settings, ANDROID and remove the app from the product sheet. If an app is wanted later, publish one vendor-signed app (Play or managed distribution) that reads its origin at runtime instead of baking it in.
- **Known:** none

### com-product-surface-7 - The documented customer install is an operator runbook from a source checkout, including generating your own release key, which contradicts the vendor-feed model; the appliance path is an unrun draft
- **Severity:** high
- **Confidence:** CONFIRMED
- **Where:** `docs/INSTALL.md:46-60` (Windows base rig, Python 3.11+, git, PyInstaller and a Mac for releases), `:89-93` (`git clone <your checkout of this repo>`), `:210-235` (Step 6: `release_key.py new` / `bake`; no mention of `DASH_RELEASE_FEED_URL`); `site.example.toml:244-261` (`[releases] feed_url`); `docs/RELEASE_FEED.md` section 1; `docs/APPLIANCE_INSTALL.md:1-20` ("DRAFT ... until somebody who is not the author has run this end to end", Serve NOT YET TRUE); `docs/PRODUCT_REPO.md` (squashed product repo recipe never run)
- **What:** There are two incompatible delivery stories. (a) The generic INSTALL guide makes the customer a release engineer: clone the repo, mint their own Ed25519 key, bake it into a companion they build themselves, and publish with PyInstaller (plus a Mac for Mac editors). (b) The vendor feed, where vendor-signed builds flow to every dashboard, which INSTALL never mentions. A customer who follows INSTALL bakes their own pubkey and cannot take vendor builds; a customer who takes vendor builds has no doc saying `DASH_RELEASE_PUBKEYS` must be the vendor's key. The appliance install that would replace all this is a draft. And "clone this repo" hands over the private engineering repo, since the product repo has never been cut.
- **Scenario:** The first customer follows INSTALL.md step by step and ends up on a self-signed fork. Each later vendor fix needs a manual rebuild at their site, or a reinstall of every editor machine to change the trust root.
- **Recommendation:** The owner decides that v1 is "vendor builds, vendor feed, customer runs a container". Then rewrite INSTALL.md around the feed: `feed_url`, `DASH_RELEASE_PUBKEYS` = vendor key, no key minting, no PyInstaller, no git clone. Move self-build to a "source licence / partners" appendix or delete it. Have a non-author run APPLIANCE_INSTALL end to end on clean TrueNAS and DSM boxes before signing anything, and cut the product repo with `make_product_repo.ps1`.
- **Known:** COMMERCIAL_READINESS item 16 (zero-touch, planned), item 10 (product repo recipe, not run)

### com-product-surface-8 - No platform support matrix exists, and the code checks none of it: Resolve versions, macOS versions and CPU, browsers and Tailscale plan are unstated; Windows 10 (end of life) is listed
- **Severity:** high
- **Confidence:** CONFIRMED
- **Where:** `docs/INSTALL.md:30,55,65` (only "TrueNAS SCALE 25.x / DSM 7.2+", "Windows 10/11 or macOS", "Resolve Studio"); `companion/src/ccsync_companion/resolve_prefs.py:28-30` (config.dat / .config.data keys "read off a live Resolve 20 install"); no `GetVersion`/Studio check anywhere in `companion/src`, `dashboard/src`, `onboarding`; `tools/release_macos.sh:683-697` (arm64 only, warns on x86_64); `installer/README.md:98-115` (macOS runtime sections A7-H unrun; one Mac in the field); KNOWN_BUGS CR-280 (OPEN; code mitigation `sidecar_tools.ensure_ca_bundle` unverified on a Mac build); `docs/SERVER-SYNOLOGY.md:435-441` (reboot survival, uid stability untested); `docs/LOOPBACK_API.md:306` (Chrome Local Network Access prompt, no browser statement); `docs/APPLIANCE_INSTALL.md` step 1 ("free tier is enough")
- **What:** A buyer's IT team needs a matrix, and support needs one to say "unsupported". Today the gaps are:
  - **Resolve.** No version range. The product rewrites Resolve's undocumented preference files (validated on Resolve 20 only), drives BPG through UI automation, and assumes a Postgres Project Server. Nothing detects the version or the free edition at runtime.
  - **Windows.** Windows 10 is listed, but its support ended in October 2025.
  - **macOS.** No minimum version. Builds are Apple-silicon only, which nothing tells an Intel-Mac customer. One Mac's worth of field runtime, and CR-280 (no HTTPS sidecar fetches) is still open.
  - **Browsers.** Not stated. Send-to-Resolve depends on a page reaching 127.0.0.1:8899, which Chrome's Local Network Access prompts for and which Safari may treat differently (not verified).
  - **NAS.** Only TrueNAS 25.10 and one DS423+ have been exercised.
  - **Tailscale.** Required as the perimeter, but the plan a business needs (seat count and price) is not stated.
- **Scenario:** A customer on Resolve 21, or the free Resolve, or an Intel Mac, or Safari, buys on the strength of "Windows or macOS + Resolve Studio". Prefs edits misfire or scripting is silently absent, and there is no documented line for support to point to.
- **Recommendation:** Write a SUPPORTED_PLATFORMS page and link it from the EULA and the order form. It should name Resolve Studio versions (e.g. 20.x tested), Windows 11 (decide on 10), macOS minimum + Apple silicon only, TrueNAS SCALE 25.10 / DSM 7.2.x tested builds, supported browsers (Chrome/Edge; say what happens on Safari/Firefox), and the Tailscale plan and seats a business needs. Then enforce what is cheap to enforce: read `resolve.GetVersion()`/`GetProductName()` after `connect()` and report and refuse unknown majors for prefs writes, and refuse an x86_64 Mac in the installer with a clear sentence. Verify CR-280 on a Mac build before listing macOS as supported.
- **Known:** CR-280 (OPEN); COMMERCIAL_READINESS item 12 stated the envelope only at NAS level

### com-product-surface-9 - Every binary in the vendor feed is unsigned, so a new customer's managed machines may refuse to install it
- **Severity:** high
- **Confidence:** CONFIRMED
- **Where:** `feed/channel.json` (12 of 12 records `"signed_binary": false`, 0 true); KNOWN_BUGS CR-6 ("no Authenticode or Developer ID certificate exists"); `tools/release_macos.sh:601-653` (ad-hoc signing, no notarization)
- **What:** The Ed25519 record signing protects the update channel. But the Windows companion and wizard carry no Authenticode signature, and the macOS bundles are ad-hoc signed and not notarized. Corporate endpoint protection, SmartScreen and Gatekeeper treat both as untrusted, and on macOS each upgrade can lose TCC grants.
- **Scenario:** A paying customer's IT blocks unsigned executables, so the wizard cannot run and the install fails at step one. A Mac editor double-clicks a downloaded bundle and Gatekeeper refuses it.
- **Recommendation:** The owner (as the legal entity) buys an OV/EV Authenticode certificate and an Apple Developer ID and enrols for notarization. Set the signing env vars already wired in CI. Drop `-AllowUnsignedBinary` from the release path before the first paid ship.
- **Known:** CR-6 (open: certificates not bought)

### com-product-surface-10 - The vendor's trust root and distribution channels sit on one person's Windows profile and one GitHub org, with no documented backup or succession
- **Severity:** high
- **Confidence:** CONFIRMED (key location and protection, from the docs); PLAUSIBLE (ghcr/feed visibility to customers, not checked live)
- **Where:** `docs/BACKUP_RESTORE.md:74-75` (release.key and Android keystore protected by "Nothing", "one Windows profile on the base rig"); `tools/publish_latest.py:46` (`FEED_REPO = "The-Creators-Club/ccsync-releases"`); `server/install_dashboard_app.py:1428` and `dashboard/deploy/compose.appliance.yaml:88,147,291` (`ghcr.io/the-creators-club/ccsync`, `-sftp`); `tools/gen_notices.py:523` ("Cablewrap Creative Ltd." as issuer)
- **What:** Every customer's fleet trusts only the public keys baked into the build it already runs. The single private key lives on the owner's base-rig profile, and the docs say nothing protects it. Images and the feed are hosted under a GitHub org whose ownership relative to the licensing entity is undocumented. (The notices name "Cablewrap Creative Ltd."; the feed and images are "The-Creators-Club".) Nothing in the repo confirms the ghcr packages and the releases repo are public to an unauthenticated customer pull.
- **Scenario:** The base rig's disk dies, or the profile is wiped. No signed build can reach any customer again until every editor machine at every customer is reinstalled by hand. Or the GitHub org's owner account is locked, and every customer's feed and image pull fails at once.
- **Recommendation:** Before the first sale: two offline backups of `release.key` (password manager plus a sealed offline copy) and a written key-custody and rotation procedure. Transfer the GitHub org, ghcr packages and releases repo to the licensing entity with two owners. Check, from a logged-out machine, that `docker pull ghcr.io/the-creators-club/ccsync:1` and the `channel.json` URL work. Record all of it in a vendor-side continuity doc.
- **Known:** OPS-8 (backup advice in INSTALL Step 6); CR-6 records the key, not its custody

### com-product-surface-11 - The product is sold at version 0.x, and HEAD holds many unbuilt fixes, so no release candidate exists to sell
- **Severity:** medium
- **Confidence:** CONFIRMED
- **Where:** `companion/src/ccsync_companion/config.py` (`VERSION` 0.9.8x; owner rule "after 0.9.9 comes 0.10.0, never 1.0"); dashboard 0.7.7x; KNOWN_BUGS CR-350, CR-351, CR-355..CR-358, CR-360, CR-361 ("FIXED in repo", "unbuilt" or "unshipped"); the uncommitted working tree (alerts selection, companion fixes)
- **What:** The fleet runs builds several fix waves behind HEAD, and HEAD itself is uncommitted. Selling "0.9.84" to an organisation reads as pre-release in procurement, and there is no named, frozen, fully gated build that the EULA, notices and support policy refer to.
- **Scenario:** The first customer installs whatever the feed holds that day. A week later support cannot reproduce a bug because the fleet, the feed and HEAD are three different trees.
- **Recommendation:** Freeze a v1 RC: commit, run the full gate, build, sign, soak on the studio fleet, then publish as the first customer-facing version. The owner decides the public version number; the "never 1.0" rule is the owner's to revisit for the product name/version shown to buyers. Keep a changelog customers can read.
- **Known:** none as a launch item

### com-product-surface-12 - Music search is tuned and measured on one 376-track library; ship it as beta, not as a headline feature
- **Severity:** low
- **Confidence:** CONFIRMED
- **Where:** `music/README.md` (376 tracks, re-index "needs the RTX 3080"); `music/web/musicweb/rescore.py:225-236` (source-bias groups by one catalogue's naming convention); KNOWN_BUGS MUSIC-ING-1..MUSIC-ING-4 (open)
- **What:** The vocabulary, debias axes and eval were built around one library. Companion-side ingest exists (ONNX in the feed), but its fallback is the base rig's GPU, tracks ingested on a companion carry no BPM, key or loudness, and only one progress window shows at a time.
- **Scenario:** A customer with a 20,000-track library from different catalogues gets search quality nobody has measured, and the BPM filter silently excludes everything ingested by companions.
- **Recommendation:** Label it beta in v1, and run the eval (`music/eval`) on a second, differently sourced library before marketing it. Fix MUSIC-ING-1 (BPM/key) before calling it ready.
- **Known:** MUSIC-ING-1..4 (open)
