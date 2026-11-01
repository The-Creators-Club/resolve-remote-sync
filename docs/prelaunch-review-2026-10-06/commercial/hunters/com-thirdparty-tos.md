# Pre-launch commercial review, 2026-10-06: third-party terms and platform risk (com-thirdparty-tos)

Lens: what a buyer's lawyer, a security reviewer or a platform's trust-and-safety
team would raise about the third parties CC Sync depends on. Read-only review of
the working tree at HEAD 08b40eb plus uncommitted changes.

**Covered:** `docs/COMMERCIAL_READINESS.md` items 1-3, 10, 12 and the third-party
table; `LICENSE`; `docs/legal/{EULA,PRIVACY,YOUTUBE_FEATURE_NOTICE}.md`;
`docs/LEGAL_GAP_FEATURES_PLAN.md` (counsel status, LG-8/9/10);
`dashboard/src/ccsync_dashboard/{ai_providers,cli_tools,cards_ai,triage,site_store,settings}.py`
(the parts about providers and features); `dashboard/deploy/run.sh` (unblock plugin, yt-dlp
nightly); `server/install_dashboard_app.py` (unblock env); `ytdl/web/ytdlweb/vendor/{downloader,ytsearch,PROVENANCE}`;
`ytdl/web/ytdlweb/config.py`; `companion/src/ccsync_companion/{ytdlp_manager,ytdl_executor,library,bpg}.py`
(the relevant parts); `docs/RELEASE_FEED.md` §3; `.github/workflows/image.yml`; `dashboard/deploy/compose.appliance.yaml`;
`docs/APPLIANCE_INSTALL.md`; `docs/CLIENT_FOLDERS.md` §3; `docs/CONFIG.md` (download route);
`docs/legal/THIRD_PARTY_NOTICES.md` (the models); KNOWN_BUGS (grep). Checked against the
publishers' current terms: Anthropic's Claude Code legal and compliance page, Tailscale pricing
and the Funnel KB page, Cloudflare's service-specific terms, and the TrueNAS 26 deprecations page.

**Not covered:** the Timeline Cards repo itself (it is not shipped to customers); a line-by-line
read of the Blackmagic, Google/YouTube, OpenAI and DeepSeek terms (I name what counsel has to
read); live state of the GitHub org and GHCR package visibility (I made no GitHub calls);
Synology DSM terms.

---

### com-thirdparty-tos-1 - The Claude Code / Codex "subscription" path does what Anthropic's published policy forbids third-party developers to do
- **Severity:** critical
- **Confidence:** CONFIRMED (code read end to end; policy text fetched 2026-10-06 from code.claude.com/docs/en/legal-and-compliance)
- **Where:** `dashboard/src/ccsync_dashboard/cli_tools.py:71-86` (pty sign-in that relays the claude.ai code through the dashboard page), `:280-285` (`<data>/secrets/ai/claude_code_oauth_token`), `:434-446` (`STRIPPED_ENV_VARS`: the API key is removed *so that the subscription is spent*), `:499-501`, `:1729-1745` (`setup-token` strategy, `captures_token=True`); `ai_providers.py:85` (`PROVIDER_ORDER` puts `claude_code` FIRST), `:148-152` (UI copy: "Spends your Claude subscription, not a bill per call"); `cards_ai.py:17`; `triage.py:30-35,193-227`; `docs/legal/YOUTUBE_FEATURE_NOTICE.md` "CLI providers"
- **What:** Anthropic's Claude Code legal page now says: "Anthropic does not permit third-party developers to offer Claude.ai login into their own applications, or to route requests through Free, Pro, or Max plan credentials on behalf of their users. Moreover, developers may not collect, store, or intermediate Claude.ai credentials or session tokens - sign-in to a Claude account must complete through Anthropic's own flow." It also says that running Claude Code inside your product requires the vendor to accept the Commercial Terms, and that "each end user must authenticate with their own" credential. CC Sync's SET UP wizard does all three prohibited things. It offers Claude.ai login inside the dashboard. It relays the one-time code through its own page into a pty. Its `setup-token` fallback captures the long-lived OAuth token and stores it on disk. The dashboard then routes every editor's YouTube searches, every Timeline Cards translation, search and summary, and the twice-daily triage run through that one admin's subscription. The resolver ranks this path first. The UI sells it as cheaper. `cli_env` strips `ANTHROPIC_API_KEY` from the CLI's environment on purpose, so the CLI path can never run on a key. The notice's position, "that is your decision, not ours", answers the customer's consumer terms. It does not answer a policy that is addressed to the developer. Codex signed in with ChatGPT and serving many editors raises the same problem under OpenAI's account-sharing terms.
- **Scenario:** A customer enables `ai_cli_providers` as the page invites them to. Anthropic detects one subscription token serving a multi-user server, and enforcement comes "without prior notice": the customer's Claude account is suspended. Their Cards, YouTube and triage features stop. The customer then points at the vendor's wizard as the thing that told them to do it. The vendor's own studio runs this path in production (`site.toml` sets the flag), so the vendor's own Anthropic relationship is exposed too. If Anthropic names the product, every customer's CLI path dies at once.
- **Recommendation:** Before the first sale, remove the subscription path from the commercial build. Delete the `setup-token` capture and the stored OAuth token. Stop relaying sign-in codes. Hide or remove the Codex and Claude Code subscription rows. If Claude Code is kept because triage needs its read-only tools, run it on the customer's `ANTHROPIC_API_KEY`: stop stripping the key for that use, and keep the binary unmodified. The vendor (Cablewrap Creative Ltd) should accept Anthropic's Commercial Terms and get written confirmation from Anthropic sales for the remaining design. Rewrite the notice and the Settings copy to drop "spends your subscription". Turn the flag off on the studio's own dashboard. Owner decision plus a code change; Anthropic sales contact for the confirmation.
- **Known:** COMMERCIAL_READINESS item 1 (the 2026-08-18 follow-up reintroduced this path; it treats the question as only the customer's). LG-9 is deferred notice wording only. No open ledger entry covers the developer-side prohibition.

### com-thirdparty-tos-2 - The server triage agent can only run on a consumer subscription: a sold feature with no compliant mode
- **Severity:** high
- **Confidence:** CONFIRMED
- **Where:** `dashboard/src/ccsync_dashboard/triage.py:30-35` ("The Anthropic API provider is deliberately NOT a fallback"), `:193-227`; `cli_tools.py:434-446`; `ai_providers.py:150` ("The only one the server check can use"); `dashboard/templates/partials/admin_alerts.html:93`
- **What:** Triage is a scheduled, unattended, twice-daily `claude -p` run under a person's Claude login. It needs `ai_cli_providers`, and the API key is stripped from its environment. Under the policy quoted in finding 1, it has no configuration a customer can lawfully use. Claude Code itself supports API-key authentication, so this limit comes from the product's design, not from the tool.
- **Scenario:** The product's feature list or demo includes "the server checks itself and emails you". Every customer who turns it on is in breach from the first run.
- **Recommendation:** Let triage run Claude Code (unmodified) with the customer's API key: an explicit `ANTHROPIC_API_KEY` passed only to this call, metered and capped. Or run it through the SDK with a tool loop the dashboard owns. Until then, keep `alerts_triage` out of the commercial feature list.
- **Known:** none (the triage design doc records the choice; it does not record the terms issue).

### com-thirdparty-tos-3 - Every TrueNAS integration uses the REST API that TrueNAS 26 removes
- **Severity:** high
- **Confidence:** CONFIRMED (code). The vendor's own docs say REST "do[es] not function in 26 and later". 25.10.1+ already raises a deprecation alert on every REST call.
- **Where:** `server/common.py:4,1339`; `server/install_dashboard_app.py:143-155`; `server/install_syncthing_app.py:10-35`; `server/setup_editor_account.py:6`; `server/create_api_key.py:140`; `dashboard/src/ccsync_dashboard/nas/truenas.py:10,100,113`; `nas/factory.py:25`
- **What:** The installer, Syncthing app install, editor-account provisioning, API-key creation and the dashboard's own NAS backend are all `/api/v2.0` REST. iXsystems deprecated REST in 25.04 and removes it in TrueNAS 26. That release is in early release now. It also deprecates `auth.login_with_api_key` in favour of `auth.login_ex`. The platform envelope says "TrueNAS SCALE 25.x". A buyer will read that as "supported until 25.x is EOL", not "do not upgrade your NAS".
- **Scenario:** A new customer on TrueNAS 26 cannot install at all. An existing customer upgrades their NAS through the TrueNAS UI and loses provisioning, account setup and every NAS action the dashboard takes. A customer on 25.10.1+ gets a TrueNAS alert on every call in the meantime.
- **Recommendation:** Port `nas/truenas.py` and `server/common.py` to the JSON-RPC 2.0 WebSocket API (`/api/current`, `auth.login_ex` with `API_KEY_PLAIN`) before launch. Add a version probe that refuses with a named message on an unsupported release. Put a supported-versions matrix in the order form, and tell customers not to upgrade to TrueNAS 26 until the port ships.
- **Known:** none found (grep for REST deprecation / 26.04 / json-rpc in KNOWN_BUGS and docs: no hits).

### com-thirdparty-tos-4 - The YouTube stack still exposes the vendor to circumvention-trafficking claims; the "customer decides" framing covers less than the notice implies
- **Severity:** high
- **Confidence:** PLAUSIBLE (legal conclusion). The facts are CONFIRMED.
- **Where:** `dashboard/deploy/requirements.lock:1199` (yt-dlp in every image); `ytdl/web/ytdlweb/vendor/downloader.py:229-231`, `vendor/ytsearch.py:43-45` (JS runtimes + `remote_components ejs:github`, unconditional); `dashboard/deploy/run.sh:157-200,353-407` (GPLv3 PO-token plugin; nightly yt-dlp); `companion/src/ccsync_companion/ytdlp_manager.py:68-84`; `ytdl_executor.py:3182-3250` (player-client workarounds, CR-39/CR-80); `docs/legal/YOUTUBE_FEATURE_NOTICE.md`
- **What:** The notice argues that the vendor ships nothing whose purpose is to get past YouTube's measures. Three things weaken that. First, yt-dlp is installed in every vendor image, and every build carries the integration code for the PO-token sidecar, the cookie path and the challenge solver ("Nothing is stripped from the build"). Second, the vendor runs an ongoing engineering programme whose subject is YouTube's anti-bot changes. KNOWN_BUGS CR-39, CR-73/74, CR-80, CR-83 and CR-361 cover pinned player clients, PO tokens, cookie jars and an owner decision to track yt-dlp *nightly* "to get the latest". That is the vendor doing the circumventing, then handing the customer the switch. Third, the server's yt-dlp options fetch the EJS challenge solver and enable `node` with no unblock check (see finding 12). Counsel "cleared the five documents", but the cleared drafts and the governing law are Taiwanese. The first export markets will judge DMCA §1201(a)(2)/(b) and EUCD Art. 6(2) trafficking on what the vendor *offers*. The RIAA/GitHub youtube-dl takedown (2020) and the Hamburg court rulings show this is enforced in practice.
- **Scenario:** A rights holder or Google sends a §1201 notice. It names the vendor's GitHub org, which hosts the source, the public release feed and the GHCR image (finding 10). GitHub disables the org, and every customer's update channel and new installs go with it, including customers who never enabled YouTube.
- **Recommendation:** Get a written opinion from US and EU counsel on the YouTube feature specifically, before selling into those markets. Ship the commercial SKU without the ytdl package and its unblock integration: a separate, customer-installed add-on, or none. In the EULA, exclude it from support, warranty and SLA. Keep the studio's own use on a private build. Owner decision plus counsel.
- **Known:** COMMERCIAL_READINESS item 2 ("outside-counsel read before it is sold"). LG-8 (gating every cookie and POT reader) is deferred. CR-361 is the nightly decision.

### com-thirdparty-tos-5 - The customer install guide says Tailscale's free tier is enough; Tailscale's free plan is non-commercial only, and Funnel is a beta with bandwidth caps
- **Severity:** medium
- **Confidence:** CONFIRMED (doc text; Tailscale pricing and Funnel KB fetched 2026-10-06)
- **Where:** `docs/APPLIANCE_INSTALL.md:35`; `docs/CLIENT_FOLDERS.md:96-215`; `docs/legal/EULA.md` §5 ("Some of them require a paid plan at your scale")
- **What:** Tailscale states the Personal plan is "only suitable for non-commercial use". Businesses need Standard ($8/user/month) or Premium ($18/user/month). The product makes Tailscale the security perimeter and the *only* supported publish path (memory: "Serve is the only publish path, customers included"). Every customer therefore owes Tailscale a per-user subscription, and the install doc says the opposite. The client-folders feature publishes customer-to-client video previews through Funnel. Tailscale documents Funnel as beta, with "non-configurable bandwidth limits", on three ports only.
- **Scenario:** A customer follows the guide and runs their studio on a Personal tailnet, in breach of Tailscale's terms. Their quoted TCO is wrong by roughly $100-200/month for a 10-editor studio. A client review link stalls on a large preview because of Funnel's cap, and the customer blames CC Sync.
- **Recommendation:** Fix the doc. Put "Tailscale Standard or higher, per user, billed by Tailscale" in the order form and the pricing sheet. Label Funnel delivery as beta and capped, and document a non-Funnel option (reverse proxy on the customer's own domain). Finance and sales must include Tailscale in quotes.
- **Known:** none.

### com-thirdparty-tos-6 - The documented Cloudflare-tunnel download route for proxies likely breaches Cloudflare's CDN terms for video
- **Severity:** medium
- **Confidence:** PLAUSIBLE (Cloudflare's terms let it limit or disable non-Enterprise CDN use "to serve video or a disproportionate percentage of ... large files" without its paid media services; Tunnel traffic goes through that proxy)
- **Where:** `docs/CONFIG.md:585-660` ("Download route (`remote_down`, trial from 2026-09-25)"); `companion/src/ccsync_companion/sync/rclone_lane.py:631-650`; `dashboard/src/ccsync_dashboard/api.py:9957`
- **What:** Lane B can pull proxies (video, tens to hundreds of GB) through a Cloudflare Tunnel in front of `rclone serve webdav`. CONFIG.md documents this as a customer-settable option, measured at about 52 MB/s against 18 MB/s.
- **Scenario:** A customer copies the recipe onto a Free or Pro Cloudflare account. Cloudflare throttles or disables the zone, and lane B parks on every machine using the route. The circuit breaker handles that safely, but the speed the vendor sold disappears.
- **Recommendation:** Mark the route studio-only or unsupported in customer docs until Cloudflare confirms it in writing, or use a product licensed for the purpose (R2, or Enterprise). Do not quote the 52 MB/s figure to buyers.
- **Known:** none (the studio trial is recorded in memory only).

### com-thirdparty-tos-7 - Reading Resolve's undocumented project database and driving the proxy generator by UI automation: Blackmagic EULA and version-break exposure
- **Severity:** medium
- **Confidence:** PLAUSIBLE (licence reading). The facts are CONFIRMED.
- **Where:** `companion/src/ccsync_companion/library.py:1-81,436-442` (reads `Sm2*` tables, decodes zstd blobs, default `postgres`/`DaVinci` credentials); `companion/src/ccsync_companion/bpg.py:13-39,157,254` (UIAutomation against `Resolve.exe -pg`); `docs/legal/EULA.md` §5
- **What:** Besides the public scripting API, the companion reverse-engineers Resolve's private project-library schema and blob format and logs in with Resolve's default database credentials. It also drives the Blackmagic Proxy Generator through Windows UI Automation. Blackmagic's licence prohibits reverse engineering. Whether reading the customer's own database for interoperability falls under an exception (EU Software Directive Art. 6, DMCA §1201(f)) is a counsel question. Commercially, none of this is a supported interface: the module's own notes list schema traps such as NULL foreign keys and garbage `SubType`.
- **Scenario:** A Resolve point release changes the schema or the blob framing. The library walk silently reads wrong or empty data at every customer at once. Blackmagic support refuses to help a customer whose project database a third-party tool reads.
- **Recommendation:** Get a counsel note on the interoperability position. Add a supported-Resolve-versions matrix to the order form, plus a version gate in `library.py` that falls back to the API walk on an unknown Resolve build. Consider asking Blackmagic developer relations. Disclose in the EULA that the companion reads Resolve's project database.
- **Known:** none.

### com-thirdparty-tos-8 - Chain of title: the vendored YouTube code's licence grant is still owed, and nothing assigns the author's code to the licensing company
- **Severity:** medium
- **Confidence:** CONFIRMED (documents)
- **Where:** `ytdl/web/ytdlweb/vendor/PROVENANCE.md:3-7,52-75` ("a written licence grant is OWED"); `docs/legal/YOUTUBE_FEATURE_NOTICE.md` "Vendored code" (states it is the vendor's own); `LICENSE` (copyright "Cablewrap Creative", still marked DRAFT FOR COUNSEL); `docs/legal/EULA.md` §14 (Cablewrap Creative Ltd.)
- **What:** The notice tells customers the vendored code is "part of the Software". PROVENANCE.md, unchanged since 2026-08-17, says the grant from its author (Alex, as an individual) has not been signed. The same gap applies to the whole product: the author writes the code personally, and the EULA licenses it from Cablewrap Creative Ltd. A buyer's IP due diligence will ask for an assignment of code and marks from the individual to the company. It will also ask about AI-generated portions (most of the code is written with Claude), because copyright in purely machine-generated output is uncertain in the US. `LICENSE` still carries the placeholder entity name and the draft banner, while the EULA has the real one.
- **Scenario:** A customer's lawyer asks for the IP warranty and the assignment deed, and the sale stalls. Or a later dispute with the author's estate or a partner finds no written transfer.
- **Recommendation:** Alex signs a one-page IP assignment (ccsync, yt-credit-downloader and any other repo whose code ships) to Cablewrap Creative Ltd. Update `PROVENANCE.md` and `LICENSE` to the registered entity. Counsel drafts the assignment and the EULA's IP warranty with the AI-authorship caveat in mind.
- **Known:** COMMERCIAL_READINESS item 3 ("a written licence grant for the vendored yt-credit-downloader"): still open.

### com-thirdparty-tos-9 - The Creators Club mark ships on every customer build with no trademark ownership, clearance or EULA clause behind it
- **Severity:** medium
- **Confidence:** PLAUSIBLE
- **Where:** `companion` and dashboard brand defaults (`cc_mark_white.png`, CR-25); `docs/legal/EULA.md` (names only Blackmagic's marks); `LICENSE`; GitHub org `The-Creators-Club`, image `ghcr.io/the-creators-club/ccsync`, contact `contact@thecreatorsclub.co`
- **What:** The owner ruled (CR-25) that the Creators Club mark is the product brand on every build. Yet no legal document says who owns "Creators Club", "CC Sync" or the CC mark, or that the licensee gets no rights in them. The contracting entity has a different name. "Creators Club" is a crowded term: adidas ran a loyalty programme under that name, and there are other creator programmes. "CC" next to creative software invites comparison with Adobe's "CC". I found no evidence of a clearance search or registration.
- **Scenario:** After launch, a prior rights holder in class 9/42 objects in a target market, forcing a rebrand of binaries, bundle ids, the GitHub org and the image path that live installs depend on. Or a buyer cannot tell from the paperwork who the supplier is.
- **Recommendation:** Run a trademark clearance search for "CC Sync" and "Creators Club" (word and logo) in Taiwan, the US, the EU and the UK, classes 9 and 42. File in the entity's name. Add a marks clause to the EULA naming the owner. Make sure the GitHub org, the domain and GHCR are owned by the entity with at least two admins, not one personal account.
- **Known:** CR-25 (the branding decision). Ownership and clearance are not recorded anywhere.

### com-thirdparty-tos-10 - Distribution is public and unauthenticated on one GitHub org: the "confidential" source is world-readable, nothing checks entitlement, and one takedown stops every fleet
- **Severity:** medium
- **Confidence:** CONFIRMED (by design; GitHub-side visibility not probed)
- **Where:** `docs/RELEASE_FEED.md:404-406` ("A private repo will NOT work ... the assets must be world-readable"); `site.toml:47` (`The-Creators-Club/ccsync-releases`); `dashboard/deploy/compose.appliance.yaml:88,147,291` (credential-less GHCR pulls); `.github/workflows/image.yml:47-128`; `dashboard/src/ccsync_dashboard/dashboard_update.py` (OTA bundle is the Python code tree); `LICENSE` ("PROPRIETARY AND CONFIDENTIAL"); no licence-key or seat check anywhere (grep)
- **What:** The dashboard OTA tarballs and the container image carry the full dashboard, b-roll, music and ytdl Python source. Both are published where anyone can download them without credentials. `LICENSE` calls that source confidential. No code anywhere checks a licence key, a seat count or an order, so the EULA's "number of workstations ... covered by your order" cannot be enforced. All of it (source repo, feed, image) sits in one GitHub org, with the YouTube-circumvention integration code inside it (finding 4).
- **Scenario:** A competitor or a lapsed customer pulls `ghcr.io/the-creators-club/ccsync:1` and runs the product indefinitely. Or GitHub disables the org after a DMCA notice or an account-security event: new installs fail to pull, and every dashboard's feed check 404s.
- **Recommendation:** Owner decision. Either declare the source "source-available under the EULA" and drop "confidential", or move to authenticated distribution: per-customer registry tokens and a feed token, with the trade-off for the unauthenticated-fetch design in RELEASE_FEED §5 recorded. Add at least a contractual audit right, or a signed per-site licence file the dashboard checks. Keep an off-GitHub mirror of the feed and image (the feed URL is baked into signed channels, so plan the move now). Have finance and legal decide the enforcement model.
- **Known:** none.

### com-thirdparty-tos-11 - Platform signing accounts are still not in place (Authenticode, Apple Developer ID)
- **Severity:** medium
- **Confidence:** CONFIRMED (ledger)
- **Where:** `KNOWN_BUGS.md` CR-6 ("STILL OPEN: no Authenticode or Developer ID certificate exists"); `tools\ship.cmd -AllowUnsignedBinary`
- **What:** Shipping to other organisations needs two third-party accounts in the company's name. One is the Apple Developer Program as an organisation, which needs a D-U-N-S number for Cablewrap Creative Ltd and takes weeks. The other is an Authenticode certificate. Since 2023, CA/B rules require the private key to sit in an HSM or a cloud signing service, which does not fit a key-file-on-the-rig signing model. Unsigned or ad-hoc builds trigger SmartScreen and Gatekeeper warnings, and many corporate endpoint policies refuse them outright.
- **Scenario:** The first customer's IT department blocks `onboard.exe`, or macOS refuses the unnotarised bundle, and the install fails on day one.
- **Recommendation:** Start D-U-N-S and Apple org enrolment now. Buy an OV certificate on a cloud HSM (or Azure Trusted Signing, if eligible), and wire it into `release-windows.yml` and `ship.cmd`. Owner/finance.
- **Known:** CR-6 (OPEN).

### com-thirdparty-tos-12 - The YouTube notice says the challenge solver is "unblock only", but the server enables it without that flag
- **Severity:** low
- **Confidence:** CONFIRMED (code); runtime effect depends on a JS runtime being present
- **Where:** `ytdl/web/ytdlweb/vendor/downloader.py:229-231`, `vendor/ytsearch.py:43-45` vs `docs/legal/YOUTUBE_FEATURE_NOTICE.md` table ("deno, the n-challenge JavaScript solver: No")
- **What:** Every server-side yt-dlp call passes `js_runtimes {deno, node}` and `remote_components ["ejs:github"]`, whatever `youtube_unblock` says. If any `node` is on the container's PATH, the EJS solver is downloaded from GitHub and run with only `youtube_download` on. That can happen in bind mode, through an admin-installed CLI, or in a future image. The companion side is correctly gated (deno is installed only with unblock). The notice is a customer-facing legal statement, so it has to be exact.
- **Scenario:** A customer who deliberately left unblock off is running the solver anyway, against what the vendor's notice told them.
- **Recommendation:** Build these two options from `unblock_enabled()`, the LG-8 design, and pin the behaviour with a test.
- **Known:** LG-8 (deferred) covers the cookie and POT readers, not these two options.

### com-thirdparty-tos-13 - yt-dlp nightly runs in the dashboard process and on every editor machine with integrity-only verification
- **Severity:** medium
- **Confidence:** CONFIRMED
- **Where:** `dashboard/deploy/run.sh:353-407,488-490`; `ytdl/web/ytdlweb/ytdlp_nightly.py:7-26,80-89`; `ytdl/web/ytdlweb/worker.py:196-198`; `companion/src/ccsync_companion/ytdlp_manager.py:68-92,689-704`
- **What:** With `youtube_download` on, the dashboard pip-installs whatever yt-dlp pre-release PyPI serves (`--pre`, no hash pin; the hash comes from the same index) and puts it on the dashboard's own PYTHONPATH. That is the process holding the fleet's tokens, AI keys and the TrueNAS credential. Companions pull the newest nightly from a GitHub release and check it only against that same release's own `SHA2-256SUMS`. This deliberately sets aside the hash-pinned-lock promise (COMMERCIAL_READINESS item 13). A security questionnaire will ask: "do you execute unreviewed third-party code within 24 h of publication?"
- **Scenario:** A compromised yt-dlp maintainer account or CI publishes a malicious nightly. Within a day it runs inside every YouTube-enabled customer's dashboard and on every editor's workstation.
- **Recommendation:** For the commercial build, track yt-dlp stable with a short vendor-reviewed pin cadence, or run the downloader in a separate container that holds no fleet secrets. If nightly is kept, make it a customer opt-in and disclose it in the security documentation.
- **Known:** CR-361 (deliberate owner decision 2026-10-05; the commercial implications are not recorded).

### com-thirdparty-tos-14 - DeepSeek is offered as a provider with no jurisdiction or data-residency label
- **Severity:** low
- **Confidence:** PLAUSIBLE
- **Where:** `dashboard/src/ccsync_dashboard/ai_providers.py:140-143,187-198`; `docs/legal/PRIVACY.md:141`
- **What:** The Settings picker presents DeepSeek on the same footing as Anthropic and OpenAI, with nothing saying that processing happens in the PRC. Several governments restrict DeepSeek on public-sector and contractor systems, including Taiwan's public sector (the vendor's home market) and several US states. What it receives here (YouTube topics and titles) is low-sensitivity. A buyer's procurement checklist will still flag it.
- **Recommendation:** Add a one-line jurisdiction note to the DeepSeek row, and a site feature to hide it in the vendor build.
- **Known:** none.

### com-thirdparty-tos-15 - Lane C relies on Syncthing's volunteer-run public relays and discovery for customer media by default
- **Severity:** low
- **Confidence:** CONFIRMED (disclosed in PRIVACY.md:144,155)
- **Where:** `companion/src/ccsync_companion/app.py:7195`; `server/accept_device.py`; `docs/legal/PRIVACY.md:144`
- **What:** A commercial product routes customers' encrypted media through community-donated relay infrastructure when direct paths fail. The PRIVACY doc discloses this. A buyer's security review will still ask why a tailnet-only product leaves relays and global discovery on, and the volunteer relays carry no service commitment.
- **Recommendation:** Default commercial sites to tailnet-only: relays off, global discovery off, tailnet addresses. This is the LG-7 "private mode" work, which the plan says must first fix its lane C prerequisites.
- **Known:** LG-7 (deferred).
