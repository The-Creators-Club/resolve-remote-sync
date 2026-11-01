# Pre-launch commercial review - lens com-licensing-billing

Date 2026-10-06, HEAD 08b40eb plus the uncommitted working tree. Read-only.

**Covered:** `docs/COMMERCIAL_READINESS.md` (items 1-15, the licensing-debt and
AI-provider items), `LICENSE`, `docs/legal/{EULA,PRIVACY}.md`,
`docs/LEGAL_GAP_FEATURES_PLAN.md` (LG-19, D7), `docs/RELEASE_FEED.md`,
`docs/DOCKER.md` (the registry section), `docs/PRODUCT_REPO.md`,
`.github/workflows/image.yml`, `tools/publish_feed.py` and
`tools/publish_latest.py` (feed repo), `dashboard/deploy/Dockerfile` and
`.dockerignore`, `dashboard/src/ccsync_dashboard/{site_store,release_feed,ai_providers,cards_ai,setup_engine,db}.py`,
`companion/build.spec`. I grepped the whole tree (outside `.venv`/tests) for
licence key, entitlement, seat, trial, expiry, activation, install/site id,
budget, spend and usage code, and checked `KNOWN_BUGS.md` and the LG plan for
licensing ids.

**Not covered:** live registry and feed visibility (no network calls allowed:
the "public" claims come from `docs/DOCKER.md`'s 2026-08-18 measurement and
from `release_feed.py`, which sends no credential by design); the actual dollar
cost of a Cards or indexer run (no live key); counsel questions on copyright
in AI-written code.

**Summary.** There is no licensing of any kind in the product. No licence key,
seat count, entitlement, trial, expiry, install identity or per-customer
feature tier exists in code. LG-19 ("licence entitlement display") and D7
("seats") were deferred. The whole product, as images, companion installers
and the OTA dashboard bundle, is distributed publicly with no credential. The
EULA sells "the number of workstations and servers covered by your order",
but no order exists and nothing counts. AI spend is the customer's (good), but
it has no cap, no meter and no attribution. The privacy policy promises "no
licence check is sent to the Licensor", so the licensing model has to be an
**offline, signed licence file**, never an activation server. The
recommended model is in com-licensing-billing-1.

---

### com-licensing-billing-1 - No licence, seat count, entitlement, trial or expiry exists anywhere in the product

- **Severity:** high
- **Confidence:** CONFIRMED
- **Where:** whole tree (grep: no `licence_key`, `entitlement`, `seat`, `trial`, `expires_at` outside b-roll share links, `activation`, `install_id`); `docs/legal/EULA.md` section 2; `docs/LEGAL_GAP_FEATURES_PLAN.md:960` (LG-19 deferred), `:1229` (D7 seats deferred)
- **What:** The EULA grants a licence "on the number of workstations and servers covered by your order ... for the term of your subscription or licence". No code knows an order, a number or a term. The setup wizard's `eula` task records acceptance. `machine_state.eula_json` records per-computer acceptance. Neither is tied to a customer, a quantity or a date. Every install is unlimited and perpetual in practice.
- **Scenario:** A customer buys 5 seats and enrols 25 editors. The product does not notice, and the vendor cannot find out without asking. A trial cannot end. A customer who stops paying keeps full function forever, and the vendor's only remedy is a contract claim in the Taiwan courts.
- **Recommendation:** The minimum viable model is a signed licence file. It fits the existing trust model and the privacy promise.
  1. The vendor issues `licence.json` plus a detached Ed25519 signature, made by a **separate** offline licence key (not the release key; `release_key.py` and `ed25519.py` already exist to reuse). Fields: `licence_id`, `org_name`, `issued_at`, `not_after` (term), `updates_until` (maintenance), `seats` (counted computers with a non-empty `machines` row, or editor accounts, decided once), `features` (list), `kind` (`trial|subscription|perpetual`), `bound_to` (the site's `dashboard_url` host and/or tailnet name).
  2. Code needed:
     - a `licence.py` in the dashboard: load from `<data>/licence/`, verify against baked pubkeys, expose state.
     - an upload box on Settings, shown as a LICENCE panel (this is LG-19).
     - a `licence` row in `/api/v1/health`.
     - a seat counter over `machines` / `local_users`.
     - an alerts registry row (`licence_expiring`, `licence_over_seats`).
     - a gate at ONE place, machine enrolment (`db.upsert_machine` / editor token minting `db.create_editor_report_token`).
  3. **Enforcement must be soft and never touch sync.** Over seats: refuse NEW computers with a clear message, and show a banner. Expired subscription: banner and alert first. After a grace period (for example 30 days), block new enrolment and stop offering feed updates. NEVER stop lanes A/B/C, never halt the fleet, never delete anything ("never gut the live thing"; a licence lapse that stops footage syncing is a liability event of its own).
  4. A trial is the same file with `kind=trial` and a 30-day `not_after`.
- **Known:** LG-19 / D7 (deferred, open)

### com-licensing-billing-2 - The entire product is publicly downloadable with no credential, including full source in the image

- **Severity:** high
- **Confidence:** CONFIRMED (code + the repo's own recorded measurement; not re-probed live per the rules)
- **Where:** `docs/DOCKER.md:474-480` ("the package is public ... A NAS pulls them without a docker login"); `.github/workflows/image.yml` (pushes `ghcr.io/<owner>/ccsync[-sftp]`); `docs/RELEASE_FEED.md:404` ("A private repo will NOT work: the fetch deliberately sends no credential"); `tools/publish_latest.py:46` (`FEED_REPO = "The-Creators-Club/ccsync-releases"`); `dashboard/deploy/Dockerfile:87-125` (`COPY dashboard/src`, `broll/web`, `music/web`, `ytdl/web` as plain `.py`); `LICENSE` ("PROPRIETARY AND CONFIDENTIAL")
- **What:** The dashboard image is on a public GHCR package. The signed companion installers (Windows/macOS), the onboarding wizard and the OTA dashboard bundle are on a public GitHub Releases feed, and must be public because `release_feed.py` sends no credential. The image carries the complete, unobfuscated Python source of the dashboard, b-roll, music and ytdl apps. Anyone on the internet can pull a working CC Sync and read all of its code. No agreement is involved and no EULA is shown until the wizard.
- **Scenario:** A competitor or a non-paying studio runs `docker pull ghcr.io/the-creators-club/ccsync:edge`, downloads the companion from the releases repo and runs the whole product. The "PROPRIETARY AND CONFIDENTIAL" claim in `LICENSE` is weakened. Trade-secret protection needs reasonable secrecy measures, and public distribution of the source is the opposite. With com-licensing-billing-1, nothing in the binary limits use either.
- **Recommendation:** Pick one, explicitly:
  - **(a) Keep distribution public and rely on the licence file (billing-1) as the control.** This is acceptable for B2B, but have counsel confirm the trade-secret posture and drop "CONFIDENTIAL" if it cannot be honoured.
  - **(b) Make distribution per-customer.** Use a private GHCR package with a per-customer read-only pull token, and a feed that accepts a per-customer bearer token. That means `release_feed.py` gains an `Authorization` header from `<data>/secrets/feed_token`, and the "no credential" sentences in `RELEASE_FEED.md` §5 and `PRIVACY.md` §5 are updated. Costs to budget: private GHCR storage/egress is billed, and private-repo Actions minutes (especially macOS) are billed.
  - Recommendation: (a) for launch plus the licence file, and (b) when a second paying customer exists.
  - Either way, consider shipping `.pyc`-only or a compiled build of the dashboard trees. This is a speed bump, not protection, so it is optional.
- **Known:** not recorded

### com-licensing-billing-3 - Nothing binds an install to a customer: a container copied to a second site is indistinguishable

- **Severity:** high
- **Confidence:** CONFIRMED
- **Where:** `dashboard/src/ccsync_dashboard/settings.py:109` (`_SITE_IDENTITY_ENV`, site identity is env-supplied and free text); no `install_id` / `site_id` / `instance_id` anywhere in `dashboard/src`; `site_store.py` (org_name, dashboard_url are admin-editable rows)
- **What:** A dashboard has no identity the vendor issued. `org_name`, `dashboard_url` and the tailnet name are whatever the operator types. A data volume, an image and a `site.toml` are everything needed to stand up an identical second site, or a fresh one with no data.
- **Scenario:** A customer with two offices licenses one. It clones the stack (or the NAS app config) to the second office's NAS with a different `dashboard_url`. Both run with full function, and the vendor has no signal.
- **Recommendation:**
  - Bind the licence file (billing-1) to the site's `dashboard_url` host (already normalised for the loopback guard) and to the Tailscale node name when present.
  - On a mismatch: banner, alert, and refuse new enrolment after a grace period; never stop sync.
  - Mint a random `install_id` at first boot (a meta row) and show it on the LICENCE panel and in `/api/v1/health`. Then a support request names the install, and a licence can list the ids it covers.
  - Accept that a determined customer can edit the Python. The goal is honest-customer compliance and evidence, not DRM.
- **Known:** not recorded

### com-licensing-billing-4 - No maintenance/update entitlement: a lapsed customer keeps receiving every release forever

- **Severity:** high
- **Confidence:** CONFIRMED
- **Where:** `dashboard/src/ccsync_dashboard/release_feed.py` (one shared public `channel.json` for every customer, no customer identity in the request); `docs/RELEASE_FEED.md` §2-§5; EULA section 2/12 ("for the term of your subscription")
- **What:** The feed is one channel for all customers and the vendor's own studio. Any dashboard pointed at it receives and can auto-publish every signed build to its fleet. No field in a record or in the channel limits who may take it.
- **Scenario:** The vendor wants an annual subscription or "perpetual licence plus 12 months of updates". A customer who does not renew keeps auto-updating via `DASH_RELEASE_FEED_POLICY=current` or the [ UPDATE NOW ] button. Renewal has no product lever, and recurring revenue depends entirely on goodwill.
- **Recommendation:**
  - Add `updates_until` to the licence (billing-1).
  - Have `release_feed._apply_policy` skip records whose `published_at` is after `updates_until`. Show them as "available with a renewed licence" and never as an error.
  - Security fixes are the exception: give records a `security: true` flag that is always allowed. Withholding a security fix from a lapsed customer is a liability the vendor does not want.
  - Pair this with a per-customer feed token if option (b) of billing-2 is chosen.
- **Known:** not recorded

### com-licensing-billing-5 - No commercial paperwork exists for the EULA to refer to: order form, price, subscription/MSA terms, support terms, DPA template

- **Severity:** high
- **Confidence:** CONFIRMED
- **Where:** `docs/legal/EULA.md` sections 2, 10, 12, 13 ("covered by your order", "fees paid by you ... in the twelve months", "term of your subscription", "together with your order, is the entire agreement"); `docs/legal/PRIVACY.md:110-112` (a DPA "can request one"); no order form, price list, quote template, support/SLA policy or DPA anywhere in the repo
- **What:** The EULA is final text (v1.1), but it delegates the commercial terms to an "order" that has never been drafted. The liability cap is "fees paid in the twelve months" with no fee defined. Support response, availability and update obligations are undefined. A GDPR Art. 28 DPA is promised on request but no template exists.
- **Scenario:** The first buyer's procurement asks for an order form, a price per seat, payment terms, renewal/termination, a support SLA and a signed DPA before purchase. The vendor has none of them. Alternatively, a dispute arises and the liability cap is computed against an undefined fee.
- **Recommendation:** Owner and counsel to produce:
  1. **Price list and unit:** per editing computer (matches `machines` and the seat counter), plus a per-site base fee. Optional add-ons only if billing-6 is built.
  2. **Order form / quote template:** licence id, seats, term, `updates_until`, features, fees, payment terms, renewal, governing law per EULA.
  3. **Subscription/support terms:** support hours and channel, response targets, what "updates" includes, security-fix policy.
  4. **DPA template:** Art. 28, for support access.
  5. **Invoicing process:** Taiwan uniform invoice (統一發票) obligations for domestic sales, cross-border VAT/withholding for foreign B2B customers, currency. This needs an accountant's answer.
- **Known:** not recorded

### com-licensing-billing-6 - Feature flags are customer-controlled switches, not vendor entitlements: no tier or add-on can be sold

- **Severity:** medium
- **Confidence:** CONFIRMED
- **Where:** `dashboard/src/ccsync_dashboard/site_store.py:834-868` (`FEATURE_SETTINGS_ATTRS`, `feature_enabled`, DB row then env); `site_store.py:81-100`; CLAUDE.md "Optional features are off in the vendor build and turned on per customer"
- **What:** `[features]` (youtube_download, youtube_unblock, ai_cli_providers, auto_update) are switches the customer's own admin flips on Settings or in site.toml. They exist for legal opt-in, which is correct for that purpose. The large product surfaces (b-roll search, music search, Timeline Cards, client folders, fleet jobs, triage agent) have no flag at all. "Turned on per customer" means the customer turns it on.
- **Scenario:** The vendor wants to sell "Sync" and "Sync + Search + Cards" as two prices. Every customer gets everything regardless of what they paid for, and a lower tier cannot be enforced.
- **Recommendation:**
  - If tiers are wanted, `licence.features` (billing-1) becomes a second AND-term inside `site_store.feature_enabled` (licensed AND switched on). The legal opt-in flags stay customer switches.
  - Add flags for the mounts (`broll`, `music`, `cards`, `client_folders`) to their tri-state mount functions. They already fail absent and never fatal, so "not licensed" is just another absent state with a reason.
  - If no tiers are wanted, decide that explicitly and price one SKU. That is a valid choice and costs no code.
- **Known:** not recorded

### com-licensing-billing-7 - No seat or usage statement the vendor can invoice from

- **Severity:** medium
- **Confidence:** CONFIRMED
- **Where:** `dashboard/src/ccsync_dashboard/db.py:5108` (`upsert_machine`), `db.py:9358-9390` (`set_machine_eula`, `machine_eula_map`), `local_users.py:193`; no export or count surface for licensing
- **What:** The dashboard knows exactly how many computers and editors exist, and which computers accepted which EULA version. Nothing turns that into a statement. Machines that have not reported for months still count in `machines`, and there is no rule for what a "seat" is (computer vs person vs active-in-30-days). LG-18 (identity rows age out) is deferred too.
- **Scenario:** At renewal the vendor asks "how many seats?". The admin counts rows on the FLEET page by hand, including dead laptops. The customer disputes the invoice, and neither side has an authoritative number.
- **Recommendation:**
  - Define a seat as a computer that reported in the last N days (the decision D7 deferred).
  - Add a LICENCE panel count and a downloadable **signed usage statement**: counts, licence id, install id, date, signed by a key generated per install at first boot. The customer emails it at renewal, which keeps the "no phone-home" promise.
  - Add an alert at 90% and 100% of seats.
- **Known:** LG-18, LG-19, D7 (deferred, open)

### com-licensing-billing-8 - AI spend is uncapped, unmetered and unattributed; the customer pays, but nothing tells them how much or lets them stop it

- **Severity:** medium
- **Confidence:** CONFIRMED (code); dollar amounts not measured
- **Where:** `dashboard/src/ccsync_dashboard/cards_ai.py:113` (`MAX_TOKENS = 16000`), `:429-469` (usage only written to a log line), model picker sonnet/opus/fable for any Cards user; `dashboard/src/ccsync_dashboard/ai_providers.py` (keys, first-available fallback; no budget); `ytdl/web/ytdlweb/ai_backend.py:469,569`; `broll/indexer` (`anthropic` backend, usage.jsonl on the base rig only); `triage.py` (Claude Code at an interval); grep for budget/spend/cap: none
- **What:** Every AI call runs on the customer's key or subscription, which is right: the vendor carries no AI cost in ordinary operation. But:
  - no feature records spend per user/feature/month where an admin can see it;
  - no monthly cap or soft stop exists;
  - an admin cannot restrict editors to cheaper models (Opus is one click on the Cards panel);
  - first-available fallback can move spend to a provider the admin did not intend when a key is added.
- **Scenario:** An editor runs whole-corpus concept searches on Opus all week, a b-roll back-catalogue indexes via the API, and the triage agent runs every few hours. The customer receives a large Anthropic invoice and blames the vendor, because nothing in the product warned them. In a support desk's terms, that is a refund conversation.
- **Recommendation:**
  - Code: an `ai_usage` table written by `cards_ai._sdk`, `ai_backend`, triage, and the indexer's usage.jsonl merge, with token counts per (provider, model, feature, user, day). A Settings → AI providers "this month" view priced from a small rate table. A per-site monthly soft cap that refuses new AI calls with a clear message once hit. An admin model allow-list for Cards.
  - Paper: the order form and EULA state that third-party AI usage is billed to the customer by their provider, not by the Licensor. If the vendor ever offers "AI included", it must not be sold until this meter exists.
- **Known:** not recorded

### com-licensing-billing-9 - LICENSE is still a 2026-08-17 draft with a placeholder licensor; chain of title for the code and the distribution accounts is undocumented

- **Severity:** medium
- **Confidence:** CONFIRMED (LICENSE text); PLAUSIBLE (chain-of-title gaps, for counsel)
- **Where:** `LICENSE:1-8` ("DRAFT FOR COUNSEL ... NOT YET EXECUTABLE", "TODO(legal): replace 'Cablewrap Creative' ... almost certainly NOT the correct contracting entity"), `LICENSE` copyright line "Cablewrap Creative" vs `docs/legal/EULA.md` "Cablewrap Creative Ltd. (捲獻新媒體有限公司)"; `tools/publish_latest.py:46` and `docs/DOCKER.md:477` (distribution under the `The-Creators-Club` GitHub org); `docs/PRODUCT_REPO.md` (contributor identities in history)
- **What:**
  - The EULA was finalised (v1.1, 2026-09-25), but `LICENSE`, the copyright notice a buyer and the product repo will see, still says it is a non-executable draft and names a placeholder entity.
  - Distribution (GHCR package, release repo, signing keys on one workstation) sits under a GitHub org branded for the studio, not the licensor company. Nothing records that those accounts and the copyright belong to Cablewrap Creative Ltd.
  - The code was largely written by AI agents. Copyrightability and ownership of that output is a counsel question that bears directly on what is being licensed.
- **Scenario:**
  - Due diligence (a buyer, an investor, an acquirer) asks who owns the code and the distribution accounts. The only copyright notice disclaims itself.
  - If the GitHub org is personally owned and that person leaves, the feed every customer reads moves with them.
- **Recommendation:**
  - Owner: replace `LICENSE` with the final text naming Cablewrap Creative Ltd. (tax ID as in the EULA), matching the EULA.
  - Counsel: written IP assignment from every human contributor, and an opinion on protection of AI-generated code (trade secret plus contract may carry more weight than copyright).
  - Put the GitHub org, GHCR package, Apple/Authenticode identities and the offline release/licence keys in the company's name, with a documented second custodian.
- **Known:** COMMERCIAL_READINESS item 3 ("real legal entity name" outstanding, partly done for the EULA only)

### com-licensing-billing-10 - Windows companion and wizard executables carry no version resource (CompanyName, ProductName, LegalCopyright)

- **Severity:** low
- **Confidence:** PLAUSIBLE (no `version=` argument found in `companion/build.spec`; the built exe was not inspected)
- **Where:** `companion/build.spec` (EXE call, no `version=` / VSVersionInfo file); onboarding spec likewise
- **What:** PyInstaller writes no Windows version-info block unless given one. The exe's Properties → Details then shows no publisher, product name, version or copyright.
- **Scenario:** A customer's IT department inventories software for licence compliance (SAM tools read this block), or writes an AppLocker/Defender allow rule by publisher. The exe shows as an unknown, unattributed binary. This also weakens the copyright notice in the shipped artefact.
- **Recommendation:** Generate a VSVersionInfo file from `config.VERSION` at build time (CompanyName = the licensor entity, ProductName "CC Sync", LegalCopyright) and pass it as `version=` in both specs. Do it in the same change that adds Authenticode signing.
- **Known:** not recorded
