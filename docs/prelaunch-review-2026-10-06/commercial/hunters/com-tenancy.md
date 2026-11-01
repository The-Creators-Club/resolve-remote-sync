# Pre-launch commercial review - lens com-tenancy (single-customer assumptions)

Date 2026-10-06, HEAD 08b40eb plus the uncommitted working tree. Read-only.

**What was covered.** I grepped every tracked file for the tenant markers in
`tools/make_product_repo.ps1`: Creators_Club, Creators Club, creatorsclub,
Cablewrap, the NAS and Synology IPs, /mnt/tank, TheCreatorsPool, C:\Users\alex,
DESKTOP-LQQ41TC, SAMDISK, tail26290e, leso, ruskin and alex. I added FF1-6,
creator-1, Creator_1, Razer, LESO-MBP, mofa, P:\, private and tailnet IP
literals, e-mail addresses, GitHub and GHCR owners, Taiwan, zh and Asia/Taipei.
Each hit was split into shipped code, tests and docs. I then read the code
paths behind every hit that is executable rather than a comment: the TrueNAS
homes fallback, the b-roll creators dir, the stack uid/gid, the ytdl term
languages, the site manifest defaults, the installers' tree name and prefix
fallbacks, the appliance compose, the Dockerfile and .dockerignore (what the
image ships), and the product-repo export script.

**What was not covered.** Live systems were not touched, so I could not check
whether the GHCR image is still public. I did not review the MulticamPipeline
repo. I did not re-audit the legal texts beyond their naming of the vendor.

**Headline.** The 2026-08-17 pass (COMMERCIAL_READINESS item 10/11) holds for
*executable defaults*: no customer IP, hostname, account or e-mail is a
compiled-in default any more, and every user-visible string goes through the
site manifest. What has regressed or was never finished:

- **Identity in shipped artefacts.** Staff names, machine names, the tailnet
  name and the NAS address now appear in hundreds of docstrings and comments.
  These ship as source in the dashboard image and as .pyc docstrings in the
  companion.
- **The product-repo scrub.** It can no longer pass.
- **Structural assumptions.** A handful of structural assumptions belong to
  one studio: the tree layout, Taiwan-Chinese search, the "Creators_Club"
  archive folder, and uid 3000:3001.

---

### com-tenancy-1 - The project tree layout is the first studio's, and the plan to make it site data has not started
- **Severity:** high
- **Confidence:** CONFIRMED
- **Where:** `companion/src/ccsync_companion/sync/lane_guard.py:70` (`DEFAULT_REMOTE_MARKER_DIRS = ("Projects",)`); `companion/src/ccsync_companion/fixer.py:253-269,401` (`Audio/Music`, `B-roll/Stills`, `B-roll/Editor Added/<editor>`); `ytdl/web/ytdlweb/db.py:1810` (`YOUTUBE_DIR = 'Youtube'`); `dashboard/src/ccsync_dashboard/settings.py:78-94` (refuses any `projects_dir` other than `Projects`); `docs/TREE_LAYOUT_PLAN.md:32-35` ("Nothing built").
- **What:** The tree root name and the drive letter are site data. The *shape* of the tree is still hard-coded:
  - `Projects/` as the first segment;
  - `Assets/{Luts,Stills,B-roll Archive,Music}` as its siblings;
  - the `Proxy/` sibling-folder rule that defines lanes A/B/C;
  - `Youtube/`, `Audio/Music` and `B-roll/Editor Added/<editor>` inside a project;
  - exactly one project root.

  The 2026-08-19 audit says so (`TREE_LAYOUT_AGNOSTICISM.md` section 1). The plan that fixes it says "Nothing built. Decisions D1-D6 are proposed". SYS-20 turned a wrong `projects_dir` into a boot refusal. That is honest, but a refusal is not support.
- **Scenario:** Studio B keeps projects under `Jobs/<client>/<job>/` with Resolve's "Generate Proxy Media" cache folders, not `Proxy/` beside the media. The dashboard refuses to boot with any `projects_dir` but `Projects`. Even after a rename, lane B treats nothing as a proxy, so proxies never come down. The audit itself puts this at "weeks, and touches the companion, the dashboard and the NAS scripts in lockstep".
- **Recommendation:** Pick one before selling. Either (a) build TREE_LAYOUT_PLAN WP1-WP5 (the plan sizes it at roughly 12 days), or (b) make the layout a written **system requirement**. That means one page in the order form or onboarding checklist that sales and the customer both sign: "Projects/ at the root, Proxy/ beside media, one project root, Assets/ siblings". Add a pre-sale qualification question to match. The owner has to take decisions D1-D6, and sales owns the requirement text.
- **Known:** `docs/TREE_LAYOUT_AGNOSTICISM.md`, `docs/TREE_LAYOUT_PLAN.md` (open, unbuilt); KNOWN_BUGS SYS-20 (partial: refusal only, and still open on `server/common.py`).

### com-tenancy-2 - Shipped artefacts carry staff names, machine names, the tailnet name and the NAS address in source docstrings and comments
- **Severity:** high
- **Confidence:** CONFIRMED for the content; PLAUSIBLE for "the image is public" (measured 2026-08-18, not re-probed)
- **Where:**
  - `dashboard/deploy/Dockerfile:87,97-98,123-125` copies `dashboard/src`, `broll/web`, `music/web` and `ytdl/web` as .py source. `.dockerignore` strips tests, data and docs, not comments.
  - `server/install_dashboard_app.py:1414-1418` says "the GHCR package IS public".
  - Examples:
    - `dashboard/src/ccsync_dashboard/ui.py:4754-4756`: `https://truenas.tail26290e.ts.net:9443` and `http://100.71.216.3:8480`.
    - `dashboard/src/ccsync_dashboard/alerts.py:1069,1660,3340`: `ruskin/DESKTOP-LQQ41TC`, `alex/Creator_1`, `alex/Razer`.
    - `dashboard/src/ccsync_dashboard/api.py:2815,5598`: `LESO-MBP`.
    - `dashboard/src/ccsync_dashboard/cards_pool.py:283-285,424-425`.
    - `companion/src/ccsync_companion/watcher.py:173` names ruskin's machine and the production "Reproductive Rights Fight".
    - `companion/src/ccsync_companion/sync/shared_folders.py:236`: `SAMDISK`.
    - `companion/src/ccsync_companion/library.py:229`: the NAS IP.
    - `ytdl/web/ytdlweb/vendor/PROVENANCE.md:20-23`: the private upstream path, git remote and author.
- **What:** Counts of the bare words in the image's code trees (dashboard/src, templates, static, broll/web, music/web, ytdl/web; tests and data excluded): ruskin 26, leso 12, alex 43, creator-1 3, DESKTOP-LQQ41TC 3, FF5 17. In `companion/src`: ruskin 18, leso 9, creator-1 6, FF5 20. Every one is a comment or docstring, so no behaviour depends on them. But:
  - the dashboard image ships them verbatim as `.py` source;
  - the companion's PyInstaller build keeps docstrings, because neither `.spec` sets `optimize`.

  Named people are personal data under any privacy regime. The tailnet name plus the NAS addresses are a map of the vendor's own network. `PRIVACY.md` and the product-repo design (`make_product_repo.ps1` header) both promise that customers get "no tenant identity". The images and companion builds are built from *this* engineering repo by CI, not from the scrubbed product repo, so that promise never reaches the artefacts customers actually run.
- **Scenario:** A buyer's security reviewer runs `docker pull ghcr.io/the-creators-club/ccsync:1` with no login, because the package was measured public, and greps `/app/src`. They find the vendor's tailnet name, its NAS IP, and named staff with their machine names. They also find unrelated incident narratives ("ruskin's PC sat two versions behind for a day"). The reviewer reports a confidentiality and data-handling failure. The named editors never agreed to be in a product shipped to third parties.
- **Recommendation:**
  1. Make the GHCR packages private, or move them to a registry with pull credentials per customer. That is a licensing decision too: a public image *is* the product.
  2. Add a CI gate that runs the tenant-marker scan over **build outputs**: the image's `/app` tree and the companion `dist/`. Fail on any hit.
  3. Scrub the markers from `dashboard/src`, `broll/web`, `music/web`, `ytdl/web`, `companion/src` and `onboarding`. Replace them with role words ("an editor's PC", "the base rig") and keep the dates and CR ids. Alternatively, ship byte-compiled code with `-OO` and no `.py`, but the scrub is cleaner.
  4. Set `optimize=2` in both PyInstaller specs, after checking that nothing reads `__doc__` at runtime.

  The owner signs off on the replacement wording. The vendor's privacy lead (or counsel) confirms the staff-name exposure is closed.
- **Known:** none open. COMMERCIAL_READINESS item 10 section B claimed the names were scrubbed on 2026-08-17, and they have been reintroduced since.

### com-tenancy-3 - The product-repo export (tools/make_product_repo.ps1) can no longer produce a clean repo
- **Severity:** medium
- **Confidence:** CONFIRMED (the scan was rerun read-only with `git grep -F` and the script's own exclusions)
- **Where:** `tools/make_product_repo.ps1:145-218` (TenantFiles, TenantGlobs, TenantMarkers), `:347-351` (the scan's `:(exclude,glob)` pathspecs).
- **What:** Outside the script's own exclusions, the working tree now holds:
  - `ruskin` 889 hits in 95 files, `leso` 323 in 62, `alex` 385 in 112, `DESKTOP-LQQ41TC` 23 in 13, `tail26290e` 46 in 22;
  - `Creators_Club` 825 hits, `/mnt/tank` 331, `TheCreatorsPool` 103, `100.71.216.3` 18, `192.168.0.102` 21.

  The header says these were "scrubbed out of source, tests and docs on 2026-08-17". Three more gaps:
  1. **Stale exclusions.** `docs/bug-hunt-*.md` is a file glob, but the hunts are now directories: `docs/bug-hunt-2026-09-24/` alone is 96 files. Under `:(glob)` the `*` does not cross `/`, so these files are still scanned. Other directories are neither scanned out nor pruned: `docs/UI_PORT_LEDGER/` (38), `docs/mobile/` (52), `docs/usability-resilience-sweep-2026-09-03/`, `docs/resilience-sweep-2026-08-28/`, `docs/LEGAL_GAP_FEATURES_LEDGER/`, `docs/ACCOUNT_PAGE_FEATURES_LEDGER/` and this `docs/prelaunch-review-2026-10-06/`. They name editors, the NAS and open vulnerabilities, and they would ship.
  2. **Escaped-backslash blind spot.** `C:\Users\alex` is matched as a fixed string, so the JSON-escaped `C:\\Users\\alex` in `broll/eval/local_vlm/config.base-rig.json` passes.
  3. **Missing markers.** FF5/FF4/Framing Formosa, `Creator_1`/`CREATOR-1`, `Razer`, `LESO-MBP`, `mofa-disaster`, and real interviewee names (see com-tenancy-4).

  The only way through today is `-AllowTenantMarkers`, which defeats the gate.
- **Scenario:** An escrow agent, an acquirer's due diligence, or a contractor needs the source. The operator runs the export, sees thousands of hits, passes `-AllowTenantMarkers` to get a repo out, and hands over the ledgers, the staff names and the network map.
- **Recommendation:** Prune `docs/` by allowlist, not denylist: ship only the customer documents that `published_docs.py` already names plus ARCHITECTURE/INSTALL. Add the missing markers, and add a regex variant that matches `\\`-escaped paths. Run the scan in CI on every push to main, so a regression is found the day it lands. Combine this with the scrub in com-tenancy-2.
- **Known:** none.

### com-tenancy-4 - Real third-party personal data (interviewee names) and the studio's catalogue sit in tracked fixtures and eval data
- **Severity:** medium
- **Confidence:** CONFIRMED
- **Where:**
  - `broll/eval/local_vlm/clips.json`: 38 `Interviewees/` paths. Shares ff2/ff3/ff4/mofa-disaster, for example `Taroko/Interviewees/Lee Hui-lian/...`.
  - `broll/docs/prototypes/local-vlm/*.json`.
  - `broll/indexer/tools/make_own_proxies.py:77-93` (the FF2 episode folder list) and `broll/indexer/tools/run_backcatalogue.sh:24-79` (`Q:/FF2`).
  - Tests: `companion/tests/test_sequencer.py`, `dashboard/tests/test_provision.py`, `dashboard/tests/test_unicode_paths.py` and others. Names seen: `李桂林 Lee Kui-lin`, `潘忠政 Pan Zhong-cheng`, `黃志文 Huang Chi-wen`, `Matej Šimalčík`, `Lin Tsung-yi`, `Wu Cheng-wen`, `Yu Chi-hsiang`, `Aha Chu` (52 hits).
- **What:** These are real interview subjects of the studio's documentaries, not invented names, and they are used as test fixtures and eval data. `make_product_repo.ps1` withholds `broll/eval/queries_*.yaml` for exactly this reason ("the queries name their productions"). It does not withhold `broll/eval/local_vlm/*` or the indexer tools, and it has no way to catch names in tests. Tests are excluded from the image, so this is a source-distribution and privacy-hygiene issue, not a runtime one.
- **Scenario:** The source goes to an auditor, escrow or a contractor, or is shown in a sales due-diligence data room. Third parties' names and the topics they spoke on are disclosed with no lawful basis. For sensitive productions (civil defence, reproductive rights) that matters more.
- **Recommendation:**
  - Replace the names in fixtures with synthetic ones. The NFC/NFD tests need a decomposable Latin name and a CJK one: invent both.
  - Move `broll/eval/local_vlm/clips.json`, `config.base-rig.json`, `broll/docs/prototypes/local-vlm/*.json`, `make_own_proxies.py`'s presets and `run_backcatalogue.sh` to the git-ignored `private/`, as was done for `config.queue.yaml` on 2026-08-17.

  Engineering does the work. The owner decides whether history needs rewriting, and the squashed product repo makes that unnecessary.
- **Known:** none.

### com-tenancy-5 - Own-footage archive folder is "Creators_Club" for every customer: the appliance path cannot change it, and the indexer ignores the setting
- **Severity:** medium
- **Confidence:** CONFIRMED
- **Where:** `broll/web/app/config.py:191-206` (`get_archive_creators_dir` defaults to `"Creators_Club"`); `broll/web/app/ingest_batches.py:264-266`; `broll/indexer/build_archive.py:54,179` (`CREATORS = "Creators_Club"`, a literal); `dashboard/deploy/compose.appliance.yaml` (no `BROLL_ARCHIVE_CREATORS_DIR`; grep finds nothing); `dashboard/src` (no site_store key for it); `server/install_dashboard_app.py:2281` (only the base-rig deploy passes it).
- **What:** Ingest of a customer's own shoots files clips under `<archive>/<creators_dir>/<share>/...`. The folder name comes from an env var that defaults to the first studio's name. The zero-touch appliance path has no wizard field, site_store row or compose variable for it, so every appliance customer gets a `Creators_Club` folder in their `P:\Assets\B-roll Archive`. A customer who does set it through the base-rig deploy gets a split archive: the indexer's `build_archive.py` still writes `Creators_Club/` as a literal.
- **Scenario:** Studio B ingests its first shoot. Editors browse `P:\Assets\B-roll Archive\Creators_Club\...`, another company's name inside their own archive. If the vendor sets the env var for them, indexed shoots file under `Creators_Club/` and ingested ones under their own name.
- **Recommendation:** Make the default neutral for new sites, for example `Own_Footage` or the tree name. Keep `Creators_Club` only behind the same "no [broll] table" transitional branch that `creators_shares` uses. Add it to the site_store and wizard keys. Read the same value in `build_archive.py`.
- **Known:** KNOWN_BUGS (around line 2726: "This studio's own site.toml owes a [broll] block") covers the studio's own migration, not the appliance gap or the indexer literal.

### com-tenancy-6 - TrueNAS deploys run the container as 3000:3001 (this fleet's broll:editors) with no check against the live box
- **Severity:** medium
- **Confidence:** CONFIRMED for the code path; PLAUSIBLE for the impact on a given box
- **Where:** `server/install_dashboard_app.py:1500-1501` (`APP_UID = site_int("stack","uid",3000)`, `APP_GID ... 3001`), `:5358-5419` (only the Synology branch reads ids from the NAS); `server/backends/truenas.py:748-753` (`ensure_service_user` raises: "uid/gid ... come from [stack] uid/gid in site.toml"); `dashboard/deploy/compose.appliance.yaml:71-79` (`${APP_UID:-3000}:${APP_GID:-3001}`, "TrueNAS SCALE's default is already right"); `site.example.toml:361-367`.
- **What:** The Synology path reads the real uid/gid of `broll` and `editors` from the NAS, after spike 7. The TrueNAS path and the appliance compose take the first fleet's numbers on trust. TrueNAS SCALE hands the *first locally created user* uid 3000, so on a box whose admin created a personal account before following `server/README.md`, 3000 is that person. Meanwhile `chown -R <owner>:<group>` uses *names*. The numbers the container runs as and the names the tree is chowned to can therefore point at different accounts.
- **Scenario:** A customer's TrueNAS has `jane` as 3000 and `broll` as 3002. The dashboard writes downloads, ingests and file moves as `jane`. If `editors` is not gid 3001, the container cannot write into the 2770 `broll:editors` tree at all, and ytdl, ingest and the file move "MOVE ON THE SERVER" fail with permission errors.
- **Recommendation:** On TrueNAS, resolve `[stack] owner` and `group` to ids through the API (`/user?username=`, `/group?group=`) at deploy time, as the Synology branch does. Refuse when they disagree with an explicitly configured uid/gid. Have the appliance wizard ("Your studio" step) do the same and write `APP_UID`/`APP_GID` back. Remove the "already right" claim.
- **Known:** KNOWN_BUGS around line 2311 fixed hard-coded chown ids, not this.

### com-tenancy-7 - YouTube search expands every term into Taiwan Traditional Chinese by default
- **Severity:** medium
- **Confidence:** CONFIRMED
- **Where:** `ytdl/web/ytdlweb/claude_cli.py:566-628` (`TERM_SCOPES`, `DEFAULT_TERM_SCOPE = SCOPE_BOTH`, the prompt "8 to 12 queries in Traditional Chinese as used in TAIWAN"); `ytdl/web/ytdlweb/worker.py:448`; `ytdl/web/static/app.js` (the scope labels "english + chinese").
- **What:** The only languages the YouTube term expansion knows are English and Taiwan-variant Traditional Chinese, and the default spends half the candidate budget on Chinese queries. That is the first studio's market built into a product feature. The feature is off in the vendor build (`youtube_download`), which limits who hits it.
- **Scenario:** A UK or German studio turns the feature on and searches "flood defences". Half the results come from Taiwanese Chinese-language queries the editors cannot read, and their own language is not offered.
- **Recommendation:** Make the expansion languages a site setting: a list of BCP-47 tags with a "variant" note. The default is the site's own language, or English alone. Derive the scope labels from that setting. The owner decides the default; engineering builds it.
- **Known:** none.

### com-tenancy-8 - Vendor identity is three different names, the LICENSE still carries a placeholder, and the IP chain is unwritten
- **Severity:** high
- **Confidence:** CONFIRMED for the inconsistency and the TODO; PLAUSIBLE for the trademark risk
- **Where:**
  - `LICENSE:1-22` ("TODO(legal): replace 'Cablewrap Creative' ... almost certainly NOT the correct contracting entity").
  - `docs/legal/EULA.md:16,200` and `PRIVACY.md:13,349` say "Cablewrap Creative Ltd.".
  - The brand "Creators Club" / "CC Sync": `companion/src/ccsync_companion/theme.py:86-99` (the CC mark is the default on every build), `dashboard/deploy/Dockerfile:71`.
  - The GitHub org and image `ghcr.io/the-creators-club/*`: `compose.appliance.yaml:88,147,291`, `tools/publish_latest.py:46`.
  - `ytdl/web/ytdlweb/vendor/PROVENANCE.md` ("a written licence grant is OWED ... author, vendor and only customer are the same party").
- **What:** Customers will see the brand "Creators Club", which is also the name of the vendor's own studio and first customer. The legal licensor is "Cablewrap Creative Ltd.". The code is published under "The-Creators-Club". The repo LICENSE says a different spelling and calls itself a placeholder. Most of the code was written by one individual, and PROVENANCE.md shows that at least one vendored piece has no grant from that individual to anyone. Nothing in the repo records an assignment of the codebase's copyright, or of the CC mark, to the Ltd that grants the EULA. "Creators Club" is also a widely used name (adidas used it for a membership programme, for one), so trademark clearance for the product name and mark is not obvious.
- **Scenario:**
  - A buyer's lawyer asks who owns the software being licensed and gets four names and no assignment.
  - A trademark holder objects to "Creators Club" software after launch, and every build wears the mark.
  - Bundle ids `com.ccsync.*` use a domain the vendor may not own.
- **Recommendation:**
  - The **owner with counsel** decides the selling entity and the product's trade name.
  - Produce an **IP assignment deed**: the author (and The Creators Club, if it is a separate party) assigns the codebase, the vendored upstream and the CC mark to the selling entity.
  - Run a **trademark clearance search** for "CC Sync" and "Creators Club" in the target markets.
  - Fix `LICENSE` to match the EULA, and add the ytdl licence grant.
  - Engineering then aligns the GHCR org, feed repo, image labels and bundle-id domain with the chosen entity.
- **Known:** COMMERCIAL_READINESS item 3 (LICENSE draft) and item 2 / CR-2 (the ytdl grant), both still open. The IP assignment and the trademark clearance are not recorded anywhere I found.

### com-tenancy-9 - The customer templates and the in-app help use the first studio's identity as their examples
- **Severity:** low
- **Confidence:** CONFIRMED
- **Where:**
  - `site.example.toml:37,76,111-112,140,198` (`host`/`bind_lan`/`gui_url` = `192.168.0.10`, the live fleet's LAN address per `companion/src/ccsync_companion/transport.py:8` and `server/common.py:50`; `tree_name`/`share_name` = `Creators_Club`), and `:293,301,492,498` (`mofa-disaster`, `/mnt/tank/TheCreatorsPool/Creators_Club`, `db_host = "192.168.0.102"`, `db_name = "FF5"`).
  - `companion/config.example.toml:22-24` (`C:\Creators_Club`); `onboarding/steps.py:173` (`LEGACY_DEFAULT_LOCAL_ROOT = r"C:\Creators_Club"`).
  - `docs/HOW_IT_WORKS.md:179` and `docs/EDITOR_SETUP.md:213` (served at /help in the image) use `2026/FF5/Elections` and `2025/FF4/Nuclear`.
- **What:** The files a new customer copies, and the help their editors read, name another studio's tree, NAS address, project library and productions. `192.168.0.10` is a common LAN address. An operator who leaves it in place aims the deploy at whatever device holds that address on their LAN. The deploy does refuse a blank value, but not a wrong one.
- **Scenario:** A new operator copies `site.example.toml`, edits what looks site-specific, keeps `tree_name = "Creators_Club"`, and their editors' drive shows "Creators_Club".
- **Recommendation:** Use neutral placeholders: `tree_name = "Studio_Projects"` (the admin template already uses that), RFC 5737 addresses (`192.0.2.10`, `100.64.0.1`), and `Projects/2026/Series/Episode` in the help. Keep `LEGACY_DEFAULT_LOCAL_ROOT` only as the migration matcher it is.
- **Known:** none.

### com-tenancy-10 - Timeline Cards and fleet whisper jobs exist only for the vendor's own studio
- **Severity:** low
- **Confidence:** CONFIRMED
- **Where:** `dashboard/src/ccsync_dashboard/cards.py` (code from `DASH_CARDS_SRC`, "another repo's checkout", never in the image or an OTA bundle per CLAUDE.md); `server/install_dashboard_app.py:543,560` (`SITE_CARDS_SRC`, `vault_gid` default `"3000"`); `companion/src/ccsync_companion/config.py:836-838` (`jobs_mulcam_pipeline`: "the MulticamPipeline checkout whose pipeline.py does the work"); `companion/src/ccsync_companion/job_paths.py:8` (vault `X:\` on creator-1).
- **What:** Two whole features depend on a private repo, MulticamPipeline, that is in no customer artefact: Timeline Cards (`/cards`, the `cards_agent` role) and the `whisper` fleet job kind. The topbar link is gated on `cards_mounted`, so customers do not see a broken page. The jobs UI and docs still describe `whisper` as a fleet capability.
- **Scenario:** A customer reads `/help` or Settings -> JOBS, expects fleet transcription, and finds that no machine can ever be capable of it.
- **Recommendation:** The owner decides whether these features are part of the commercial offer. If they are not, keep them out of the customer docs, EULA feature lists and sales material, and hide `whisper` from JOBS when no machine can run it. If they are, bring the code into a shipped, licensed artefact.
- **Known:** none.

### com-tenancy-11 - The TrueNAS client still falls back to the first fleet's homes dataset
- **Severity:** low
- **Confidence:** CONFIRMED
- **Where:** `dashboard/src/ccsync_dashboard/nas/truenas.py:36-44,104-109` (`HOME_PARENT = "/mnt/tank/TheCreatorsPool/homes"`, used with only a warning when `DASH_NAS_HOMES_PARENT` is unset).
- **What:** If a TrueNAS deployment does not get `DASH_NAS_HOMES_PARENT`, editor accounts are created with `home=/mnt/tank/TheCreatorsPool/homes`. Examples are a hand-written compose, or a future wizard path that stores the NAS kind in the DB rather than the env. That path is the first customer's pool. The base-rig deploy derives the value from `pool_root`, which is why this has not bitten.
- **Scenario:** A second TrueNAS site provisions its first editor. TrueNAS either rejects the user create (no such path) or, if `tank` exists, creates homes in the wrong place.
- **Recommendation:** Refuse provisioning with a sentence naming the missing setting, instead of falling back. Update the tests that rely on the literal to pass the parent explicitly.
- **Known:** none.
