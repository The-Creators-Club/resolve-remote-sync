# Pre-launch review 2026-10-06: commercial pass, lens `com-legal`

**Scope.** The legal paperwork in `docs/legal/` (EULA 1.1, PRIVACY 1.0,
TELEMETRY 1.0, THIRD_PARTY_NOTICES, YOUTUBE_FEATURE_NOTICE, `licenses/`),
the root `LICENSE`, and whether the code does what the paperwork says. Read
against `docs/COMMERCIAL_READINESS.md`, `docs/LEGAL_GAP_FEATURES_PLAN.md`
and its ledger (`docs/LEGAL_GAP_FEATURES_LEDGER/`), KNOWN_BUGS CR-2, CR-5
and CR-6, and the code paths each document cites: the report wire
(`reporter.py`, `api.ReportIn`, `eula.report_block`), the subject-data
routes (`subject_data_api.py`), the dashboard's first-run EULA task
(`setup_engine.py`), triage and CLI tooling (`triage.py`, `cli_tools.py`,
`ai_providers.py`), the Resolve library reader (`library.py`), the public
image (`Dockerfile`, `.dockerignore`, `install_dashboard_app.py`), the
product-repo scrubber (`tools/make_product_repo.ps1`), the vendored ytdl
code's `PROVENANCE.md`, and the git authorship.

**Not covered.** I did not compare every field row in TELEMETRY.md against
every `sync_guard` producer (the ledger's own "still sent" list says that
gap exists). I did not re-audit the licence-compliance reasoning counsel
already cleared (GPL/LGPL modes). I did not look at pricing or billing
mechanics (another hunter, `com-licensing-billing`). Nothing here is legal
advice. Each finding names the decision or document needed and who has to
produce it.

**Standing.** Counsel cleared the five documents on 2026-09-25. EULA 1.1
names the real entity, Cablewrap Creative Ltd. (Taiwan). The tier-1
legal-gap features (switches, export, erase, cleartext refusal, retention
visibility) are built and in the code. What is still open is mostly outside
the five documents: contracts, data-transfer terms, IP title, regulatory
duties, and drift since the documents were cleared.

---

### com-legal-1 - TELEMETRY.md no longer matches the wire it certifies
- **Severity:** medium
- **Confidence:** CONFIRMED
- **Where:** docs/legal/TELEMETRY.md:109-110, :262, :352-354; companion/src/ccsync_companion/reporter.py:1072-1120; companion/src/ccsync_companion/eula.py:263-287; dashboard/src/ccsync_dashboard/api.py:9483-9527, 9852-9990; companion/tests/test_telemetry_disclosure.py
- **What:** The document calls itself "verified line by line" and says drift "is worse than none". It has drifted in four ways:
  1. It says "No EULA acceptance record. It is written and read locally only". Since LG-5 the companion sends an `eula` section on every report (version, accepted_at, eula_sha256), and the dashboard stores it with `db.set_machine_eula`.
  2. The top-level keys `eula`, `machine_settings` and `report_optouts` appear in no payload table.
  3. The jobs row (:262) says a machine with `jobs_enabled = false` "still reports ... `idle_seconds`". The switches paragraph and the D4 build say it is null.
  4. The DPO section (:352) still says the four categories "cannot currently be switched off individually". The section above it documents exactly those switches.

  The LG-16 drift tests pin the key lists. They do not check that the document names the keys, so this passed green.
- **Scenario:** A customer's DPO or works council goes through the field table with a packet capture or the API model. They find a key that is not disclosed, and a sentence the code contradicts. The disclosure's credibility goes, and the DPIA built on it with it. Employees given this document as their Art. 13 notice receive a statement that is false.
- **Recommendation:** Engineering: fix the four statements and add rows for the three keys. Extend `test_telemetry_disclosure.py` so that every pinned key must appear in TELEMETRY.md. Owner: send the changed paragraphs to counsel together with com-legal-2's list, and bump the document version.
- **Known:** Partly recorded in LEGAL_GAP_FEATURES_LEDGER/G9.md "(counsel) items" and FABLE_REVIEW.md item 4 (open, not in KNOWN_BUGS).

### com-legal-2 - The "cleared" documents were edited after clearance, with an open counsel list and no version bump
- **Severity:** high
- **Confidence:** CONFIRMED
- **Where:** git `b9503c9..HEAD -- docs/legal` (PRIVACY +109/-, TELEMETRY +102/-, THIRD_PARTY +169/-); docs/LEGAL_GAP_FEATURES_PLAN.md §8.7 and D12; docs/LEGAL_GAP_FEATURES_LEDGER/G9.md:151-175, G6.md:263-272, FABLE_REVIEW.md:222-228; docs/legal/THIRD_PARTY_NOTICES.md:426-427, 634; docs/legal/PRIVACY.md:287; KNOWN_BUGS.md CR-5
- **What:** Counsel cleared the texts at b9503c9. The same day, about 380 lines across PRIVACY, TELEMETRY and THIRD_PARTY were rewritten (the ENG-GAP replacements and LG-5/LG-12). Decision D12 deliberately sent them to counsel "as information; the release does not wait". The ledger then collected a counsel list that is still unanswered:
  - PRIVACY §8 "Objection" still says objecting means "excluding that person's workstation from reporting", although per-category switches exist.
  - THIRD_PARTY says rclone and editor-side Syncthing are "resolved at install time". Both installers pin a version and a sha256.
  - THIRD_PARTY says the psycopg2 libraries load "unmodified". On macOS, PyInstaller rewrites install names and re-signs them.
  - The TELEMETRY items in com-legal-1.

  Every document still says "Version 1.0, 2026-09-25", so a customer cannot tell which text it was given (PRIVACY §12 promises that it can). KNOWN_BUGS CR-5 still reads "awaiting counsel". No record says who cleared the documents, for which jurisdictions, or on what scope. The texts rely on EU, UK and German law (EDPB, BetrVG §87), and a Taiwan adviser may not be qualified to sign that off.
- **Scenario:** A buyer's procurement asks for the version history and for confirmation of legal review. The vendor can show neither for the text actually shipped. In a dispute, a statement counsel never saw, such as "switching one off also deletes what the dashboard already held", is the vendor's alone.
- **Recommendation:** Owner and counsel:
  - Send counsel the whole diff since b9503c9 plus the collected list, and get a dated written sign-off that names the jurisdictions it covers. For any EU, UK or US market counsel does not cover, get local review.
  - Then bump PRIVACY, TELEMETRY and NOTICES to 1.1 with dates, and keep a change log section.
  - Update CR-5's status line.
- **Known:** CR-5 (status stale); LEGAL_GAP_FEATURES_PLAN §8.7 (open).

### com-legal-3 - The root LICENSE is still the unreviewed draft with a placeholder licensor, and the product-repo tooling still treats the licensor as a tenant
- **Severity:** high
- **Confidence:** CONFIRMED
- **Where:** LICENSE:1-13; tools/make_product_repo.ps1:202-206, 311-336, 666-668; dashboard/deploy/Dockerfile:70-73
- **What:**
  - `LICENSE` opens with "DRAFT FOR COUNSEL - NOT LEGAL ADVICE, NOT YET EXECUTABLE", carries a `TODO(legal)` to replace "Cablewrap Creative", and asserts "Copyright (c) 2026 Cablewrap Creative" with no "Ltd.". The EULA names "Cablewrap Creative Ltd." with a tax ID.
  - `make_product_repo.ps1`, the documented way to produce what customers, contractors and auditors receive, will not produce a clean repo. It refuses without a root `NOTICE` (none exists; the notices live in docs/legal). It also flags "Cablewrap" and "Creators Club" as tenant identity, though both are now the licensor's legal name and the product brand (CR-25).
  - The public image is labelled `org.opencontainers.image.licenses="NOASSERTION"` and `source="https://example.invalid/ccsync"`.
- **Scenario:** An auditor or customer reads LICENSE first. It says, in capitals, that the copyright notice is a non-executable draft naming an entity that may be wrong. Separately, the product-repo build either refuses, or is run with `-AllowTenantMarkers` and then cannot tell a real leak from the legal name.
- **Recommendation:**
  - Owner and counsel: issue the final LICENSE, matching the EULA's entity line exactly.
  - Engineering: drop "Cablewrap" and "Creators Club" from the tenant-marker list, keeping the real tenant markers. Accept `docs/legal/THIRD_PARTY_NOTICES.md` as the NOTICE, or add a root NOTICE pointer. Set the image's licence label to `LicenseRef-Proprietary` and give it a real source or vendor URL.
- **Known:** COMMERCIAL_READINESS item 10 "open conflict" note (never closed).

### com-legal-4 - No DPA, no international-transfer mechanism and no support-data procedure, though the privacy policy promises the first
- **Severity:** high
- **Confidence:** CONFIRMED
- **Where:** docs/legal/PRIVACY.md §3 (lines ~310-322), §9, §11; docs/legal/ (no DPA file)
- **What:** PRIVACY §3 makes the Licensor a processor whenever a customer sends a diagnostics bundle, log or database copy, or grants remote access. Bundles hold names, paths and the open project. It promises a signed Art. 28 DPA "on request", but no DPA template exists anywhere. The Licensor is in Taiwan, which has no EU or UK adequacy decision. Every EU or UK support hand-off is therefore a restricted transfer that needs EU SCCs (Module 2, controller to processor) or the UK IDTA/Addendum, plus a transfer-risk note. PRIVACY has no international-transfers section at all. The commitments in §3 ("delete it when the request is closed", "no sub-processor", breach notice "without undue delay") are not backed by any procedure:
  - support mail sits in a Google Workspace mailbox, which is itself a sub-processor;
  - there is no deletion log;
  - there is no remote-access policy.

  The vendor's own practice on its home fleet is SSH plus Tailscale into editor PCs.
- **Scenario:** The first EU or UK customer's DPO asks for the DPA and SCCs before signing. There are none, so the sale stalls. If support handles an EU bundle without them, the transfer is unlawful, and the controller (the customer) carries the exposure and will pass it back to the vendor contractually.
- **Recommendation:** Counsel to produce:
  - a DPA template with SCC Module 2 and the UK Addendum annexed;
  - Annex I/II (data categories from TELEMETRY; technical measures);
  - a short transfer impact note for Taiwan;
  - a list of the vendor's own sub-processors (mail host, file transfer, any ticketing).

  The owner writes a one-page support-data procedure: where bundles live, who can see them, deletion on close, and remote-access rules. PRIVACY gets a "Transfers" paragraph.
- **Known:** none.

### com-legal-5 - EU Cyber Resilience Act reporting duties are live, and nothing is in place for them
- **Severity:** high
- **Confidence:** CONFIRMED (absence verified; applicability is a counsel call)
- **Where:** repo-wide (no SECURITY.md, no security.txt, no vulnerability-handling or support-period document); .github/workflows/image.yml:210,234 (SBOM for the image only); docs/legal/EULA.md §14 and PRIVACY §10 (one shared mailbox); KNOWN_BUGS CR-6 (Authenticode certificates not bought)
- **What:** Regulation (EU) 2024/2847 (CRA) covers software with network functions placed on the EU market commercially. The Art. 14 reporting obligations apply from 11 September 2026: actively exploited vulnerabilities and severe incidents go to the CSIRT/ENISA single reporting platform within 24 h, with a 72 h update. The full essential requirements follow on 11 December 2027: SBOM, vulnerability handling, a declared support period, security updates, the CE/conformity route, and possibly an important-product class for a network-management tool. Today:
  - security reports go to the same `contact@thecreatorsclub.co` used for sales and privacy;
  - there is no published coordinated vulnerability disclosure policy;
  - there is no support or end-of-security-update period anywhere in the EULA or docs;
  - the companion exe has no SBOM;
  - Windows binaries ship unsigned (`-AllowUnsignedBinary`).
- **Scenario:** An EU customer's security review asks for the CVD policy, SBOM and support period. Or a vulnerability is exploited in a customer's fleet and the vendor misses the 24 h report, which carries fines of up to EUR 15M or 2.5%.
- **Recommendation:**
  - Counsel: confirm CRA classification (default or Class I) and EU-market status.
  - Owner: publish SECURITY.md plus `/.well-known/security.txt` on the vendor site, with a dedicated monitored security address. State a support period per major version in the EULA or order form. Set up an ENISA-reporting runbook with an owner and a deputy.
  - Engineering: generate an SBOM (CycloneDX) for the companion and wizard builds, as already done for the image. Buy the Authenticode certificate (CR-6).
- **Known:** CR-6 (certificates, open).

### com-legal-6 - Chain of title to the code is unproven: author is a person, a second contributor exists, and the vendored-code grant is still owed
- **Severity:** high
- **Confidence:** CONFIRMED
- **Where:** `git log` authorship (582 commits "Alex <alex@cablewrapcreative.com>", 8 commits "廖少軒 <leso@...MacBook-Pro.local>" on 2026-08-04/05 touching popup.py, tray.py, ui_dispatch.py, resolve_bridge.py, macos_bootstrap.sh, onboarding); ytdl/web/ytdlweb/vendor/PROVENANCE.md:3-6 ("a written licence grant is OWED"); upstream remote `github.com/The-Creators-Club/Utilities`
- **What:** The EULA has Cablewrap Creative Ltd. grant licences and claim ownership (§4). No document shows the company owns the code:
  - Every commit is authored by an individual. Whether his work vests in the company depends on his employment or director status under Taiwan Copyright Act Arts. 11-12 and on any contract.
  - A second person authored shipped companion, installer and wizard code.
  - The vendored YouTube code's upstream lives under a different GitHub organisation, "The-Creators-Club", and PROVENANCE.md still says the grant is owed.
  - The code is substantially AI-generated. US Copyright Office guidance (2023-2025) denies protection to purely machine-generated expression, which weakens the "all rights reserved" posture unless human authorship and selection are documented.
- **Scenario:** A larger buyer's legal due diligence, or a future investor or acquirer, asks for IP assignment deeds. None exist, the deal stalls, and the second contributor or the other organisation could later assert rights.
- **Recommendation:** Counsel (Taiwan) to draft:
  1. a confirmatory copyright assignment from Alex to Cablewrap Creative Ltd., covering all past and future CC Sync and `yt-credit-downloader` code;
  2. an assignment or work-for-hire confirmation from 廖少軒 for his commits;
  3. a licence or assignment from whoever holds "The-Creators-Club" GitHub org's code, per PROVENANCE.md's six points.

  The owner should keep a short note of the human direction of the AI-assisted work.
- **Known:** CR-2 / CR-5 (the yt-credit-downloader grant, open).

### com-legal-7 - The product depends on reverse-engineered internals of Resolve, with no record that Blackmagic's licence was reviewed
- **Severity:** high
- **Confidence:** PLAUSIBLE (facts confirmed; the legal conclusion is counsel's)
- **Where:** companion/src/ccsync_companion/library.py:1-60, 81 (`DB_DEFAULTS = {"user": "postgres", "password": "DaVinci"}`), 224-230; companion/src/ccsync_companion/resolve_prefs.py (direct `config.dat` / `.config.data` edits); KNOWN_BUGS/CLAUDE.md on `conform`/`resolve-edit` synthetic keystrokes; docs/legal/EULA.md §5; COMMERCIAL_READINESS table E ("med - EULA read on automation")
- **What:** Three things go beyond Resolve's documented scripting API:
  - The companion logs into Resolve's PostgreSQL project library with Blackmagic's default credentials. It reads undocumented internal tables (`Sm2TiItem`, `BtVideoInfo.Clip` zstd blobs, association tables) whose layout was worked out by inspection. The Cards stack writes to the library through psycopg2.
  - Resolve's private preference files are rewritten.
  - UI keystroke automation drives the GUI.

  EULA §5 puts compliance with Blackmagic's terms "including any terms governing scripting and automation" on the customer. But it is the vendor that designed and ships these mechanisms. Nothing in the repo records anyone reading Blackmagic's Software Licence Agreement (its reverse-engineering and modification clauses) or asking Blackmagic. The readiness audit flagged it on 2026-08-17. LG-6 (edition detection) is deferred.
- **Scenario:** Blackmagic objects to a commercial product built on its private database format and default password, or changes the schema and breaks every customer at once. In either case the vendor, not the customer, is the one exposed, and the EULA's §5 shift does not bind Blackmagic.
- **Recommendation:**
  - Counsel: read the current Blackmagic SLA for Resolve Studio against the three mechanisms and advise.
  - Owner: decide whether the library reader and writer ship enabled. Keep it opt-in per site with a note in the EULA or order form, or seek Blackmagic's developer programme or written comfort.
  - Engineering: keep the API path as the fallback, which it already is.
- **Known:** COMMERCIAL_READINESS table E (open, never actioned); LG-6 deferred.

### com-legal-8 - YouTube "unblock" code is distributed, dormant, in every build and in the public image
- **Severity:** high
- **Confidence:** PLAUSIBLE (facts confirmed; legal exposure is counsel's call)
- **Where:** docs/legal/YOUTUBE_FEATURE_NOTICE.md ("Nothing is stripped from the build. The code for all three stays in the tree"); dashboard/deploy/compose.yaml:348, 675-688 (bgutil sidecar); dashboard/deploy/requirements-unblock.txt; ytdl/web/ytdlweb/vendor/downloader.py; dashboard/deploy/Dockerfile:125 (`COPY ytdl/web /ytdl-app` into the public GHCR image)
- **What:** The notice's defence is that the vendor does not *install* the PO-token minter, the deno n-challenge solver or cookie sign-in. But the code that provisions and wires all three is in every build and in a publicly pullable image. Anti-circumvention law reaches *trafficking* in tools primarily designed to get past a technological measure, not only their use: DMCA §1201(a)(2)/(b), EU InfoSoc Directive Art. 6(2), Taiwan Copyright Act Art. 80-2. A German court (LG Hamburg, 2021, the youtube-dl hosting case) treated YouTube's signature cipher as an effective measure. Counsel cleared the notice's *wording*, but a notice cannot cure distribution. The LG-8 acknowledgement and LG-10 ledger retention are both deferred.
- **Scenario:** A rights holder or YouTube sends a claim to the vendor, not the customer. The public image is the evidence, and an EU or US customer's procurement refuses a product that ships circumvention tooling.
- **Recommendation:**
  - Owner: decide before sale whether the commercial SKU carries the YouTube downloader at all. If it does, the `make_product_repo` / image build should strip the unblock code paths rather than ship them dormant.
  - Counsel: give a specific opinion for the US, EU (DE) and Taiwan on (a) the dormant code and (b) the basic downloader.
- **Known:** CR-2 (counsel review owed); LEGAL_GAP_FEATURES_PLAN LG-8, LG-10 (deferred).

### com-legal-9 - The EULA presupposes an order, fees, seat counts and a support plan, and none exist
- **Severity:** high
- **Confidence:** CONFIRMED
- **Where:** docs/legal/EULA.md §2 ("number of workstations and servers covered by your order", "payment of any applicable fees", "term of your subscription"), §8 ("as described in your order or support plan"), §13 ("together with your order, is the entire agreement"); repo-wide (no order form, MSA, SLA, support policy or price list; no entitlement code, LG-19 deferred)
- **What:** The EULA hands the commercial terms to an "order" that does not exist: scope, seats, term, fees, support and updates. §13 makes the order part of the entire agreement, so without one there is no agreed scope, price, term, renewal, payment terms, refund, SLA, update entitlement or data-return on exit. Buyers will also expect clauses the EULA lacks:
  - an IP-infringement indemnity from the vendor (the EULA has only the customer's one-way indemnity, §6);
  - confidentiality;
  - audit rights for seat counts;
  - a security/breach clause;
  - an assignment clause.

  Technically nothing limits use to an order: the update feed and the GHCR image are public and need no credential (com-legal-12).
- **Scenario:** The first customer asks for the order form and support terms. The vendor improvises a quote email, which then becomes the "order" the EULA relies on, with every gap above undefined. A dispute about scope, renewal or a refund has no agreed text.
- **Recommendation:** Counsel to draft an order form template with seats, term, fees, payment, renewal and support tier, plus a short support and maintenance policy (hours, response targets, update entitlement, support period per com-legal-5). Counsel should also consider a vendor IP indemnity with the usual carve-outs. The owner sets prices and seat definitions (per editor? per machine? per site?).
- **Known:** LEGAL_GAP_FEATURES_PLAN LG-19 (licence entitlement display, deferred).

### com-legal-10 - EULA formation and forum: employees accept as "the Customer", there is no B2B-only clause, and the forum is a Taiwan court
- **Severity:** medium
- **Confidence:** CONFIRMED (text); the forum point is a judgement for counsel
- **Where:** docs/legal/EULA.md preamble ("the individual or organisation installing or using"), §6, §10, §13; companion/onboarding EULA gate (each editor's wizard page 0)
- **What:**
  1. Every editor must click ACCEPT in the wizard before sync starts. The EULA defines whoever accepts as the "Customer", who warrants rights in all Customer Content, indemnifies the Licensor (§6), and is the GDPR controller (§7). An employee has no authority to bind the organisation, and should not personally be the indemnitor or controller.
  2. The text admits "individuals" but has no business-use-only statement. Against a consumer or sole trader in the EU or UK, the "AS IS" disclaimer and the 12-month-fees cap are unenforceable (UK Consumer Rights Act 2015 ss.34-47 on digital content; EU Directive 2019/770), and in UK B2B the cap must pass the UCTA reasonableness test.
  3. Exclusive jurisdiction of the New Taipei District Court. Taiwan is not party to the New York Convention, and a Taiwanese judgment's enforcement in the EU, UK or US depends on local recognition rules. The vendor may hold a judgment it cannot enforce against a non-paying foreign customer, and foreign buyers will negotiate this clause first.
- **Scenario:** A UK editor-freelancer installs and accepts, then sues over lost media. Or a US customer stops paying, and the vendor must sue in Taipei and then re-litigate recognition in the US.
- **Recommendation:** Counsel:
  - split the editor's click into an end-user acknowledgement that does not make the clicker the Customer, with the organisation contracting through the order form (com-legal-9);
  - add "for business use only; not for consumers";
  - consider arbitration (e.g. SIAC, HKIAC or ICC, seated outside Taiwan) for foreign customers.

  EULA 1.2 bumps every fleet, so batch it with the other wording changes.
- **Known:** none.

### com-legal-11 - The organisation's EULA acceptance records no person, no organisation and no text digest
- **Severity:** medium
- **Confidence:** CONFIRMED
- **Where:** dashboard/src/ccsync_dashboard/setup_engine.py:433-490 (`_check_eula`, `_accept_eula`); dashboard/src/ccsync_dashboard/setup_routes.py:11-16, 214-231
- **What:** The dashboard's first-run EULA task is the closest thing to the *organisation's* acceptance. It runs in the anonymous setup window, before the admin account exists, and stores only `setup_tasks(id='eula', status='ok', detail='accepted v1.1', at=...)`. That record has:
  - no accepting username;
  - no organisation name;
  - no source address;
  - no digest of the text shown.

  By contrast, the companion records a sha256 and the YouTube attestation records user, version and digest. A version bump with unchanged text, or a different text under the same marker, is indistinguishable afterwards.
- **Scenario:** In a dispute, the vendor must prove that the customer organisation accepted EULA 1.1 and what it said. The only evidence is a row saying someone, unnamed, accepted "v1.1" at a time.
- **Recommendation:** Engineering: record the text's sha256, the org name the setup collects (`org_name`), and, after the admin step, the admin username confirming acceptance. Re-prompt when the sha changes, not only when the version changes. Owner and counsel: decide whether the order form (com-legal-9) is the binding acceptance instead, which is the stronger answer.
- **Known:** none.

### com-legal-12 - The public image and update feed distribute the proprietary software to anyone, and EULA §8 overstates verification
- **Severity:** medium
- **Confidence:** CONFIRMED
- **Where:** server/install_dashboard_app.py:1409-1428 ("the GHCR package IS public"); dashboard/deploy/compose.appliance.yaml:88,147,291; dashboard/deploy/Dockerfile:70-73, 87-125; LICENSE ("PROPRIETARY AND CONFIDENTIAL"); docs/legal/EULA.md §8; dashboard/src/ccsync_dashboard/release_feed.py
- **What:** `ghcr.io/the-creators-club/ccsync` is anonymously pullable and carries the full dashboard, b-roll, music and ytdl source as readable Python, with every push to main published as `:edge`. The release feed is unauthenticated GitHub Releases. So the "confidential" software reaches anyone without an order or an EULA click, and the vendor has no record of who holds it. Two side effects:
  - The publishing account is "The-Creators-Club", not the licensor (com-legal-6).
  - EULA §8 says "Every build is verified against the Licensor's release signing key before it is installed". That holds for companion packages and OTA code bundles. The base image is pulled by the NAS's docker by tag (`:1`, `:edge`), and no Licensor key check happens on that path.
- **Scenario:** A non-customer runs the product indefinitely from the public image and feed. Or a customer's security reviewer finds the §8 claim is untrue for the install and runtime-update path.
- **Recommendation:**
  - Owner: decide public versus private distribution. A private registry with per-customer pull tokens fits both the confidentiality clause and seat control.
  - Engineering: if the image stays public, cosign-sign it with a vendor key and verify the signature in `install_dashboard_app.py`, or narrow §8's wording to "every update package".
  - Counsel: align LICENSE "confidential" with what is actually public.
- **Known:** none.

### com-legal-13 - The Claude Code / Codex consent covers YouTube searches only, but the same login runs Timeline Cards and the server triage agent
- **Severity:** medium
- **Confidence:** CONFIRMED
- **Where:** dashboard/src/ccsync_dashboard/cli_tools.py:2349 ("Every YouTube search this dashboard runs, for every editor, will be spent on the account"); dashboard/src/ccsync_dashboard/triage.py:30-35, 191-200 (CLI-only by design); dashboard/src/ccsync_dashboard/cards_ai.py:17-18, 326; cli_tools.py:1447-1454 (`ai_cli_auto_update`); docs/legal/YOUTUBE_FEATURE_NOTICE.md ("nothing is fetched until an administrator asks for it")
- **What:** Accepting the wizard notice is what turns `ai_cli_providers` on. The notice tells the admin that YouTube searches will be spent on the personal subscription. Two products built by the vendor also run on that login:
  - Timeline Cards (translation, search, edit chat over interview transcripts).
  - The twice-daily triage agent, which by design has no API-key path: "The Anthropic API provider is deliberately NOT a fallback".

  So the vendor ships a feature that can only run headless, on a schedule, as a service for a whole studio, on a CLI that the wizard signs in to a personal subscription. With `ai_cli_auto_update`, the product also fetches new CLI builds unattended, which the notice says never happens without a click.
- **Scenario:** Anthropic or OpenAI treats a consumer seat powering a multi-user service as a terms breach and suspends it. The customer says the vendor's own notice understated what the account would be used for, and the vendor's design shows it induced the breach.
- **Recommendation:**
  - Engineering: give triage an API-key route. Claude Code accepts `ANTHROPIC_API_KEY`, so pass the customer's API key to the CLI when one is configured.
  - Owner and counsel: reword the notice per tool (YouTube, Cards, triage) and cover auto-update. This is LG-9's design, which needs the counsel step it was deferred for.
- **Known:** LEGAL_GAP_FEATURES_PLAN LG-9 (deferred).

### com-legal-14 - Third parties' speech goes to AI providers, and the "decide before rollout" list omits it
- **Severity:** medium
- **Confidence:** PLAUSIBLE
- **Where:** docs/legal/PRIVACY.md §2 ("No special category data is collected by design"), §5 AI row and the two-item "deserve a written decision" list; dashboard/src/ccsync_dashboard/cards_ai.py; broll/indexer/broll_index/claude_client.py
- **What:** Timeline Cards sends interview transcripts to Anthropic for translation, search and summaries. The b-roll API backend sends transcripts and frames. Interviewees in documentary work are third-party data subjects who never saw any notice from the customer. Their speech routinely contains special-category data: political opinion, health, religion. The AI row discloses the flow. But PRIVACY's list of the two flows that "deserve a written decision by the Customer before rollout" covers relays and b-roll frames only. It does not mention transcripts going to a US provider, and §2's "no special category data by design" reads as reassurance. I did not find a per-site switch that keeps Cards transcripts local while leaving Cards on.
- **Scenario:** A broadcaster customer's DPO approves the rollout on the strength of the two-item list. Interview transcripts with health or political content then leave the EU under the studio's API account with no Art. 9 condition and no transfer assessment.
- **Recommendation:** Counsel: add transcripts-to-AI as a third "written decision" item and qualify the §2 sentence. Engineering: confirm whether Cards' AI calls can be switched off per site without disabling Cards. If they cannot, add a `[features]` flag that defaults off in the vendor build, consistent with the rest of the product.
- **Known:** none.

### com-legal-15 - The documents give EU guidance only; Taiwan, the UK specifics and US monitoring-notice laws are missing
- **Severity:** medium
- **Confidence:** CONFIRMED (absence)
- **Where:** docs/legal/PRIVACY.md §6, §8; docs/legal/TELEMETRY.md "Employee monitoring: for the customer's DPO"
- **What:** The monitoring guidance is entirely GDPR, EDPB and works councils. A customer in the vendor's other stated markets gets nothing on:
  - **Taiwan:** PDPA notification duties (Art. 8). The vendor's own processing of support data is also under the PDPA, and PRIVACY never mentions it.
  - **UK:** ICO "Employment practices: monitoring workers" (2023).
  - **US:** written notice before electronic monitoring of employees in New York (Civil Rights Law §52-c, with posting and acknowledgement), Connecticut (§31-48d) and Delaware (19 Del. C. §705); CCPA/CPRA notice at collection for California employees.

  There is also no ready-to-hand staff notice template or DPIA template, though TELEMETRY says the field table "can be handed to them directly".
- **Scenario:** A New York customer rolls the product out under the EU-flavoured docs, without the statutory written notice and acknowledgement, and asks the vendor why its "read this twice" section did not mention it.
- **Recommendation:** Counsel (or local counsel per market):
  - a short per-jurisdiction annex, covering at least the US state notice laws and the Taiwan PDPA;
  - a one-page staff notice template;
  - a DPIA starter template built from TELEMETRY's tables.

  These are sales-enablement artefacts as much as compliance ones.
- **Known:** none.

### com-legal-16 - Several stores keep personal data forever, with no setting to change it
- **Severity:** medium
- **Confidence:** CONFIRMED (as documented; code not re-probed)
- **Where:** docs/legal/PRIVACY.md §7 table ("Indefinitely" rows); docs/legal/YOUTUBE_FEATURE_NOTICE.md "Settled positions" 3; LEGAL_GAP_FEATURES_PLAN LG-10, LG-18 (deferred)
- **What:** These stores have no expiry and no admin-set retention:
  - YouTube attestations and the download ledger, including each requester's search terms (which also survive erasure in folder names);
  - `known_editors`;
  - Resolve-project-to-folder mappings (named after productions);
  - machine registry rows.

  The documents disclose this honestly, so it is not a transparency defect. But storage limitation (Art. 5(1)(e)) puts the burden on the customer, and the product gives the customer no knob short of deleting a person.
- **Scenario:** A customer's DPIA concludes that "indefinite" is disproportionate for the YouTube ledger. The only remedy is SQL on the NAS, which the vendor's support would then have to supply.
- **Recommendation:** Engineering: build LG-10 (prune finished `jobs`, `job_terms`, `job_videos` and `job_video_terms` after a site-set period) and LG-18 (identity rows age out after N days without a report). Expose both as Settings values with documented defaults. Counsel approves the PRIVACY §7 change.
- **Known:** LG-10, LG-18 (deferred).

### com-legal-17 - Syncthing's public relays and global discovery are on by default for customer footage
- **Severity:** medium
- **Confidence:** CONFIRMED (documented)
- **Where:** docs/legal/PRIVACY.md §5 Syncthing row and "written decision" item 1; server/accept_device.py (`addresses: ["dynamic"]`); LEGAL_GAP_FEATURES_PLAN LG-7 (deferred)
- **What:** By default the commercial product routes customers' encrypted footage and device metadata through volunteer-run third-party relays. Turning that off is a manual per-device Syncthing change the product does not support (LG-7 deferred, because doing it wrongly stops lane C). Disclosure is fine. The commercial problems are two:
  - Embargoed or client-confidential footage transits unknown third parties by default, which security questionnaires reject.
  - A paid product leans on donated community relay capacity for bulk video.
- **Scenario:** A broadcaster's security questionnaire asks "does any customer content transit third-party infrastructure by default?" The honest answer is yes, with no supported off switch.
- **Recommendation:** Owner: decide the commercial default. Engineering: build LG-7 to its recorded prerequisites, or ship a vendor-run relay or tailnet-only addressing for new sites.
- **Known:** LG-7 (deferred).

### com-legal-18 - No trademark clearance for "CC Sync" or the "Creators Club" mark, and the brand owner is not the licensor
- **Severity:** medium
- **Confidence:** PLAUSIBLE
- **Where:** docs/legal/EULA.md (no trademark clause for the vendor's own marks); dashboard/deploy/Dockerfile:71 ("Creators Club Sync"); CR-25 (the Creators Club mark is the product brand); contact domain thecreatorsclub.co; GitHub org The-Creators-Club
- **What:** The product ships under "CC Sync" and the Creators Club logo on every customer's tray and taskbar. No clearance search is recorded. Two existing uses are worth checking:
  - "Creators Club" is an established third-party mark in other classes, for example the adidas Creators Club loyalty programme.
  - "CC" is heavily associated with Adobe Creative Cloud in exactly this market.

  The mark appears to belong to the studio brand "The Creators Club", while the licensor is Cablewrap Creative Ltd. If they are different legal persons, a trademark licence or assignment is needed. Nothing registers either mark in Taiwan (TIPO), the EU, the UK or the US.
- **Scenario:** After launch, a rights holder objects in class 9/42 and the product must be renamed across bundle ids, installers and the tray, which CLAUDE.md shows is costly. Or a competitor registers "CC Sync" first in a target market.
- **Recommendation:** Owner: commission a trademark clearance search (TW, EU, UK, US; classes 9 and 42) and file for the chosen marks. Confirm which entity owns the Creators Club mark, and put a licence in place if it is not the licensor. Add a sentence on the vendor's own marks to the EULA.
- **Known:** none.
