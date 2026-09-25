# Legal-gap features plan

**2026-09-25. Status: PLAN, revision 2 (after three audits). Nothing below is
built.**

Counsel has cleared the five documents in `docs/legal/`. The owner's
instruction the same day was: "Map out the features that don't exist yet with
some agents and make a plan, audit the plan, then make the fixes."

Revision 1 was built from three mapper reports that read the **committed**
legal documents (`git show HEAD:docs/legal/...`, still marked DRAFT FOR
COUNSEL, with 17 TODO/DRAFT hits in PRIVACY alone). The documents counsel
cleared are the **working-tree** copies, written at 12:19 the same day and not
yet committed (796 changed lines across all five). Three auditors
(correctness, safety, buildability) found that most of revision 1's text
targets no longer existed, and that several designs would have stopped sync or
made false promises. This revision is rebuilt against the working-tree
documents. The "Audit response" section at the end says what was accepted,
what was changed and what was rejected.

Contents:
1. [What the cleared documents actually leave open](#1-what-the-cleared-documents-actually-leave-open)
2. [Ground rules for every builder](#2-ground-rules-for-every-builder)
3. [Schema, wire and deploy order](#3-schema-wire-and-deploy-order)
4. [Tier 1: the six ENG-GAP features](#4-tier-1-the-six-eng-gap-features) (LG-1, LG-2, LG-3, LG-4, LG-11, LG-17)
5. [Tier 2a: document-neutral work built in the same release](#5-tier-2a-document-neutral-work-built-in-the-same-release) (LG-5, LG-12, LG-13, LG-16)
6. [Tier 2b: deferred, with the corrected design on record](#6-tier-2b-deferred-with-the-corrected-design-on-record)
7. [Builder groups and hand-offs](#7-builder-groups-and-hand-offs)
8. [Replacement wording for the ENG-GAP paragraphs](#8-replacement-wording-for-the-eng-gap-paragraphs)
9. [Open decisions for the owner](#9-open-decisions-for-the-owner)
10. [Audit response](#10-audit-response)

---

## 1. What the cleared documents actually leave open

Facts re-checked against the working tree on 2026-09-25:

- All five documents carry "Version 1.0, 2026-09-25" (the EULA is at
  `EULA-VERSION: 1.1`). They already carry:
  - the licensor's full name, Chinese name, tax ID and registered office
    (No. 111, Minquan Road, Zhuwei Village, Tamsui District, New Taipei City
    251, Taiwan (R.O.C.));
  - contact@thecreatorsclub.co for privacy and security reports;
  - the "no data protection officer" sentence (PRIVACY §11);
  - the ffmpeg **and** psycopg2 written offers (THIRD_PARTY_NOTICES);
  - model-weight licence rows (THIRD_PARTY_NOTICES ~419-423 and "what actually
    ships");
  - no `DRAFT FOR COUNSEL` and no `TODO(legal|engineering|operator)`.
- The documents describe the product **as it is today**, honestly. For
  example: relays are on by default, YouTube attestations and the ledger are
  kept indefinitely, and there is no telemetry switch. Where a missing feature
  would change a statement, the document marks it with an HTML comment
  `<!-- ENG-GAP: <id> -->`. The maintainer note at the top of PRIVACY and
  TELEMETRY says: "ENG-GAP markers flag statements that describe a missing
  feature; update them when the feature ships."
- There are exactly **six** ENG-GAP ids:

| ENG-GAP id | Where | Feature |
|---|---|---|
| `telemetry-opt-out-switches` | PRIVACY §6 (~198); TELEMETRY "What can be turned off" (~265) | LG-1 |
| `telemetry-export` | PRIVACY §8 (~247); TELEMETRY retention (~210) | LG-2 |
| `per-editor-telemetry-purge` | PRIVACY §8 (~253); TELEMETRY retention (~209) | LG-3 |
| `refuse-cleartext-dashboard-url` | PRIVACY §10 (~311); TELEMETRY "Transport" (~142) | LG-4 |
| `companion-frozen-psycopg2` | THIRD_PARTY_NOTICES (~611) | LG-11 |
| `prune-last-run-visibility` | PRIVACY §7 caveat 2 (~235); TELEMETRY caveat 2 (~199) | LG-17 |

**Consequences for this plan:**

1. **Tier 1 (must build) is the six ENG-GAP features.** They are the only
   features the cleared documents say are missing.
2. **Each ENG-GAP feature replaces exactly the paragraph after its marker,
   and removes the marker** (section 8). Nothing else in the cleared text
   changes.
3. Any change to cleared wording **outside** an ENG-GAP paragraph is marked
   "(counsel)" and is not made by a builder. It goes to the owner as a list
   for counsel. There is one such item in this plan (section 8.7).
4. Revision 1's other features were mapper findings against the old drafts.
   They are useful, but no cleared statement depends on them:
   - features that change no document text are built in the same release
     (Tier 2a);
   - features that would change cleared text, or that carry real risk to
     sync, are deferred with their corrected design recorded (Tier 2b,
     decision D1).
5. Revision 1's §5 items X1 to X19 are **dropped**. The cleared text already
   covers them. The address facts stay only in this section, for reference.
   The registered address is "251新北市淡水區竹圍里民權路111號", in English
   "No. 111, Minquan Road, Zhuwei Village, Tamsui District, New Taipei City
   251, Taiwan (R.O.C.)".

**The EULA is not changed by this plan.** Every feature below was checked
against EULA 1.1 (§7 points to TELEMETRY for what can be switched off; §5
covers AI providers and Resolve Studio; §8 covers the feed).

## 2. Ground rules for every builder

- **Timing.** Start nothing until the /account work is committed. That work
  covers v58, `account_api.py`, `machine_settings.py` and the templates in
  `git status`, and several files below are ones it edits. After it lands,
  `sessions.py` and `partials/account_*.html` are owned as section 7 says.
- **Versions are placeholders.** /account will almost certainly ship as the
  next dashboard and companion release. This plan's release is **`<DASH>` /
  `<COMP>`**, the one after that. The overseer fills in the numbers at
  release time, in code comments and docs.
  - Nothing in code compares a version. Capability is decided the /account
    way (its §4.6): a machine is known to support a feature when that
    feature's column is non-NULL.
  - No legal wording names a companion version.
- **Editor-visible copy.**
  - No em dashes in any tray string, template, HTTP `detail` or wizard line.
    The per-suite scan tests enforce this.
  - No customer name in code.
- **Defaults.**
  - A companion reading an absent key keeps today's behaviour.
  - A dashboard hearing from an old companion reads "not reported". That is
    never "no", never "zero" and never "not accepted".
- **Safety.**
  - Nothing here may stop sync, stop reports, or make the dashboard fail to
    boot.
  - The one refusal in this plan is LG-4's refusal to talk to a dashboard
    over plain http **on the public internet**. That refusal cannot touch a
    LAN or tailnet fleet (section 4.4).
- **Collect, then withhold.** A telemetry switch never stops a companion
  pass from **running**. It only withholds the pass's result from the cache
  write and from the report. This is what keeps the bridge recovery, proxy
  relink and conflict scan working (section 4.1).
- **Tests.** Builders run only the test files they touch (owner rule
  2026-09-03). The overseer runs `tools\run_all_tests.ps1` once after merge.
- **Comments.** They explain constraints and history, and cite `LG-n` and
  this file.

## 3. Schema, wire and deploy order

### 3.1 One migration: v59 (G0 owns it)

The migration comes after /account's v58. If something else takes v59 first,
use the next free number and rename it everywhere in this file.

```sql
-- v59: legal-gap features (docs/LEGAL_GAP_FEATURES_PLAN.md, 2026-09-25).
ALTER TABLE machine_state ADD COLUMN report_optouts TEXT;
  -- LG-1: JSON sorted list of withheld categories, the union of the
  -- machine's own switches and the site policy. NULL = the machine has never
  -- sent the section AND the site withholds nothing (i.e. nothing known).
ALTER TABLE machine_state ADD COLUMN report_optouts_local TEXT;
  -- LG-1: the machine's own list exactly as sent; NULL = old build.
ALTER TABLE machine_state ADD COLUMN report_via TEXT;
  -- LG-4: 'https' | 'http_local' | 'http_public', how this machine's last
  -- report reached the dashboard; NULL = not seen since v59.
ALTER TABLE machine_state ADD COLUMN eula_json TEXT;
  -- LG-5: {"version","accepted_at","eula_sha256"}; NULL = not reported.
```

Rules:
- The migration is idempotent. It runs on a fresh database, on a v58 one,
  and twice.
- It backfills nothing.
- The pseudonym salt (LG-3) is **not** a schema change. `db.pseudonym_salt(conn)`
  mints 32 random bytes into `meta['pseudonym_salt']` on first use and never
  rotates them. It is deliberately **not** the session secret, which rotates
  (`session_secrets_previous`).
- Rollback: an older image refuses a v59 database, the same stance as v58.

### 3.2 Wire: tolerant sections, same convention as /account

There is **no** new negotiation mechanism. Revision 1's `report_accepts` is
dropped (buildability M1). New report keys follow /account §4.1 and §4.6
exactly:

- Each new key is registered in `api._TOLERANT_SECTIONS` and in
  `ReportIn._a_bad_section_never_422s`. A malformed section is dropped with a
  warning, and the rest of the report lands.
- The new keys are `report_optouts` (a list of str, intersected with the four
  known names) and `eula` (LG-5).
- **Old dashboard, new companion:** the extra keys show on the SYS-3 "REPORT
  SECTION(S) IGNORED" banner. This is harmless but noisy, so the dashboard is
  deployed first, as /account already requires.
- **New dashboard, old companion:** the columns stay NULL and show as "not
  reported". **The site policy is still enforced.** The dashboard strips
  switched-off categories on arrival from every build (section 4.1, H3).

### 3.3 `/api/v1/site` additions

```json
"telemetry": {"resolve_project": true, "local_manifest": true, "media_tree": true, "input_idle": true}
```

- **G1a** extends `companion/site.py normalise()` to carry `telemetry` (four
  bools; anything else is dropped). Without this, `normalise` silently throws
  the block away (buildability H2).
  - A test covers the whole round trip: fetch, normalise, `save_site`,
    `cached_site()`. A `false` must survive it.
- Absent keys, a lost cache, or a cache written by an older build mean "all
  true", which is today's behaviour. That is safe because the dashboard also
  enforces the site policy on arrival. Only the companion's "do not even
  send" half depends on the cache.
- **G2b** adds the same four keys to `site_store`. They are also accepted from
  `site.toml [telemetry]`, with the `DASH_SITE_*` fallbacks in `settings.py`.
  They are published in `api_site`.
- `dashboard/tests/test_site.py` pins the response byte for byte. G2b updates
  that pin.
- There is **no** `net` block in this release. `require_https` and
  `syncthing_private` are deferred (Tier 2b).

### 3.4 Deploy order

1. **Wave −1 (docs only):** the overseer commits the five working-tree legal
   documents, the two EULA asset copies and `tools/gen_notices.py` as one
   docs commit, before any builder starts. See decision D11 on what that
   means for EULA 1.1 reaching editors.
2. **/account** ships through its own plan.
3. **This plan's dashboard `<DASH>`** (v59) ships. Its check: the site keys
   are published, and a report from an old companion under a site switch
   arrives stripped.
4. **Companion `<COMP>` and onboard**, Windows and Mac. Checked against the
   **deployed** build: the PRIVACY block, the About → licences file, the
   `scan_frozen` line in the release log, and the Cards role still reading the
   project library.

---

## 4. Tier 1: the six ENG-GAP features

### 4.1 LG-1. Telemetry switches (`telemetry-opt-out-switches`)

**User story.** A studio's works council wants editors' open Resolve project
names and local file lists kept off the admin's screen. The admin switches
them off for the whole site. The dashboard forgets what it already held, from
every computer and whatever its companion version, and sync carries on. An
editor can also switch them off for their own computer.

#### The four categories and every field that carries each

This table is the contract. G1a pins it in `telemetry_policy.FIELDS`, and
LG-16's payload pin fails when a new report key is added without a row here.

| Category | Fields withheld by the companion and stripped by the dashboard | What happens instead |
|---|---|---|
| `resolve_project` | top-level `resolve_project`; `capabilities.resolve.project`; `sync_guard.resolve_health.open_project` and `.project_open`; `resolve_journals[].project` (see note J); the whole of `media_tree` (its keys are project names, so this category **implies** `media_tree`) | Empty or absent. The dashboard NULLs `machine_state.resolve_project` and `cap_resolve_project`, and deletes the `meta` row `resolve_health:<editor>/<machine>` |
| `local_manifest` | `local_manifest`; `sync_guard.resolve_health.missing_clips` and `.non_canonical_refused` (paths); `sync_guard.sync_conflicts.paths` (the **count** is still sent); `stray_projects`; `moved_project_dirs`; the inventory excerpts in diagnostics | The dashboard deletes `editor_media` and `editor_media_project` rows for the machine and the path lists in the `resolve_health:` meta row. `machine_state.sync_conflicts` keeps the count, which is all it ever stored |
| `media_tree` | `media_tree`; bin excerpts in diagnostics | The dashboard deletes `media_tree_clips` for the machine |
| `input_idle` | `capabilities.idle_seconds` (also withheld whenever `jobs_enabled` is false: decision D4) | The dashboard NULLs `cap_idle_seconds`. NULL already means "cannot tell, so NOT IDLE" end to end |

**Still sent, and named in the wording, because sync or an editor's own
action needs them:**
- the names of files being transferred and recently transferred
  (`active_transfers`, `completed[]`), which drive the transfers page;
- `file_moves_applied`, the answer to a move the dashboard itself ordered;
- a project name the editor types or sends themselves when setting up a
  project;
- the project and timeline the Timeline Cards agent is driving, when an editor
  has turned that agent on for their computer (`cards_agent`, off
  everywhere by default).

**Note J (journals).** Before building, G2a checks whether the dashboard's
undo route (`resolve_undo_requests`) keys on the journal id or on the project
name.
- If it keys on the id, G1a sends `project: ""` and undo still works.
- If it keys on the name, G1a withholds `resolve_journals` entirely. The
  wording then lists "undoing CC Sync's Resolve fixes from the dashboard" as a
  cost. G2a records which case applied in its hand-back.

#### Companion (G1a)

- **Config.** Add four keys to `config.py` `DEFAULTS`, all `True`:
  `report_resolve_project`, `report_local_manifest`, `report_media_tree` and
  `report_input_idle`. `validate_config` checks that each is a bool.
- **Policy.** `telemetry_policy.py` (new):
  - `effective(cfg, site) -> dict[str, bool]` = local AND site, and
    `resolve_project` off forces `media_tree` off. This is the only copy of
    the rule.
  - `strip(payload, eff) -> payload` applies the FIELDS table. The companion
    and the dashboard use **the same table**; G2a imports a copy of it, pinned
    equal by a test on each side.
  - `redact_text(text, names, roots)` is a **new** helper. There is no
    existing `_redact` in `app.py`. `crash_report.redact` and
    `drive_swap._redacted` do other jobs and are not reused. It replaces the
    project name, and path segments under the tree root and the local media
    roots, with `<project>` and `<file>`.
- **Gates.**
  - `reporter._build_payload` calls `strip()` last, then adds
    `report_optouts: [...]`, the sorted withheld names, **always**. The list is
    empty when nothing is withheld, so "nothing withheld" can be told apart
    from "old build".
  - `capabilities` blanks `resolve.project` and sets `idle_seconds = None`
    per the table.
  - `app.build_diagnostics` drops the excerpts and runs `redact_text` over log
    lines when any of the first three categories is off.
- **What does NOT change (safety H2).**
  - `_refresh_media_tree_once` still runs every pass. It is the only caller of
    `_maybe_recover_stale_bridge()` (the 2026-08-12 stale-fusionscript
    lesson), and it also runs `_relink_proxies_once` and
    `_classify_pool_once`. With `media_tree` off, only the cache write the
    reporter reads is skipped.
  - The `ManifestCache` walk still runs. `guard.sync_conflicts` depends on it
    (app.py ~7339), and absent is how "no conflicts" is spelled, so skipping
    the walk would break "absent is never zero".
- **UI.** `settings_window.py`, THIS COMPUTER, gets a PRIVACY block with four
  ticks through `action_set_report_switch(app, name, on)`.
  - Where the site has switched a category off, that tick is disabled and
    labelled "Turned off for everyone by your administrator".
  - The right-click menu stays the ten-item CR-88 layout.
- **Never remote-controlled (safety L2).** The four `report_*` keys are
  **never** added to `db.MACHINE_SETTING_KEYS`. The dashboard cannot switch
  an editor's privacy switches back on. A comment in `config.py` says so, and
  a companion test asserts the keys are not in the machine-settings
  allow-list.

#### Dashboard

**G2a (`api.py`):**
- **Strip before any write, from every companion version (correctness H3,
  safety M3).**
  - `api_report` reads the site's `telemetry.*` through
    `site_store.telemetry_policy(conn, settings)`, which G2b adds.
  - It computes `withheld = site_off ∪ report_optouts_local`, applies
    `telemetry_policy.strip` to the parsed report, and only then writes any
    section.
  - Then, in the same transaction and after the section writes, it calls
    `db.apply_report_optouts(conn, editor, machine, withheld, local)` (G0).
- **The strip runs in `api_report` itself.** The companion switches are the
  "do not even collect or send" half. The dashboard strip is what makes the
  site switch true for a 0.9.79 machine.
- **Upload-only tick (correctness H4).** For a machine that withholds
  `local_manifest`:
  - An upload-only tick is **not** listed as a "preparing" queue entry
    (`api.py` ~736-760). Without this it would sit in a permanent fake queue:
    the CR-28 "GETTING READY forever" shape.
  - Its row shows "not reported". The lane A status from
    `lane_report_current` still shows as today.
- **First claim and NEW PROJECT (correctness H4, safety M4).** These are not
  worked around. They are listed as costs in the wording:
  - With `resolve_project` withheld, `resolve_project_unmapped` is never set
    (`api.py` ~10348), so the NEW PROJECT prompt does not appear.
  - `may_first_claim` (`api.py` ~3743) cannot see the name, so an editor
    cannot make the first mapping for a project. An admin can.
  - Sticky auto-mapping (`api.py` ~9986-10006) does not run for that
    machine.
- **`delete_user_everywhere`** is extended per LG-3.

**G2b (site settings and views):**
- `site_store` gains the four keys and `telemetry_policy(conn, settings) ->
  set[str]` (the categories that are off).
- **Settings → Site** gets a TELEMETRY block with four ticks, in
  `static/site_settings.js`, `setup_routes.py` `PUT /admin/site`, and
  `admin_settings.html`.
- **Switching a category off clears everything at once, for every machine**,
  whether or not it is online.
  - `setup_routes`'s save path calls `db.apply_site_optouts(conn, names)`
    (G0).
  - Import (`POST /admin/site/import`) and undo
    (`POST /admin/site/undo-last-change`) go through the same
    `site_store.set_many` hook. They cannot bypass the clear.
- **Fleet grid.** `fleet_grid.html` shows one grey chip, "NOT REPORTED BY
  THIS COMPUTER", on each withheld section.
  - It is never a fault colour, and never an alert or notice.
  - It is not listed as an open issue ("Nothing ticked is fine" applies in
    spirit).

#### G0 (`db.py`)

- **`apply_report_optouts(conn, editor, machine, withheld, local)`:**
  - stores both columns;
  - deletes or NULLs per the table above;
  - when a category is **newly** withheld, deletes that machine's stored
    `diagnostics` bundles, because they may carry what is now withheld.
- **`apply_site_optouts(conn, names)`** does the same for every machine.
- **`withheld(conn, editor, machine) -> set[str]`** is the one reader
  predicate. Every "cannot tell" reader below calls it:
  1. **File moves (safety M2).** `db.file_move_target_machines` already
     targets ticked projects. The rule is now:
     - a machine that withholds `local_manifest` is a target for every move
       in **every active project**, ticked or not, because the FILE_MOVES
       failure comes from files it still holds in projects it has since
       unticked;
     - wired machines stay excluded exactly as `for_enforce` requires
       (dash-db-1).

     The companion's not-found arm is already harmless.
  2. **Sync backlog, proxy stand-ins, `red_unexplained`**
     (`fetch_sync_backlog`, the `broll_standins` readers, and `alerts.py`
     ~1174). An opted-out machine's holdings are unknown: the row shows "not
     reported", and it never adds zero to a total.
  3. **The upload-only preparing rule** (G2a above) reads it.

#### Tests

- **Companion** (`test_telemetry_policy.py`, new):
  - every combination of local and site values;
  - `resolve_project` off implies `media_tree` off;
  - each FIELDS row is stripped;
  - `report_optouts` is always present;
  - `redact_text`;
  - **the passes still run while switched off**, asserted by call counts on
    `_maybe_recover_stale_bridge`, `_relink_proxies_once` and the
    ManifestCache walk;
  - the `site.normalise` round trip;
  - the `report_*` keys are not in the machine-settings allow-list.
- **Dashboard** (`test_report_optouts.py`, new):
  - a 0.9.79-shaped report under a site switch arrives stripped;
  - the site switch clears offline machines at save, and through import and
    undo;
  - the `resolve_health:` meta row is deleted;
  - diagnostics are deleted on a new withhold;
  - an absent key changes nothing;
  - unknown names are dropped;
  - the file-move rule covers every active project and excludes wired
    machines;
  - backlog "not reported" is not zero;
  - no upload-only preparing entry appears for an opted-out machine;
  - the FIELDS copy equals the companion's;
  - the em-dash scan.

### 4.2 LG-2. Export of a person's data (`telemetry-export`)

**User story.** An editor asks what the studio's dashboard holds about them.
An admin exports it from the Users page, or the editor downloads their own
copy from /account.

**The table list (G0): `db.SUBJECT_TABLES`.** This is one registry of
`(table, match_sql, kind, columns_excluded)`, used by export and erasure
alike. `kind` is one of:
- `history`: erased by LG-3;
- `current`: rewritten by the next report, so never erased;
- `identity`: removed only by delete;
- `evidence`: pseudonymised on delete.

Its contents:
- **Machine and current state:** every table in `_MACHINE_STATE_TABLES`,
  `machines`, `devices` (editor and IP address), `selections`, `editor_prefs`,
  `report_auth`, `known_editors`, `user_profiles`, the /account
  `machine_setting_requests`.
- **History:** `lane_report_history`, `transfer_history`, `completion_history`
  (via `editor_device_ids`), `missing_files`, `diagnostics`.
- **Credentials, with secrets excluded by column name:**
  - `editor_report_tokens`: the hash is excluded;
  - `user_ssh_keys` and `pending_ssh_keys`: public keys only;
  - `users`: `password_hash` and any other secret column are excluded (safety
    M8).
- **Audit and alerts:** `fleet_audit` (actor or subject), `alert_log`,
  `notices` (by subject, or by one of the person's machines), and
  `triage_runs`, `triage_replies` and `triage_actions` by run id and sender.
- **Requests:** `jobs` (created or claimed), `file_moves.requested_by`,
  `resolve_undo_requests.requested_by`, `setup_tasks`,
  `project_roots.updated_by`, `companion_packages.published_by`.
- **Sessions:** `auth_sessions` and `login_attempts` are in
  `sessions.SCHEMA`, not `db.migrate`. They are read through
  `SessionStore.subject_rows(username)`, which G2a adds after /account. The
  sid and its hash are excluded. IP-keyed `login_attempts` rows cannot be
  tied to a person, and `not_included` says so.

**The coverage test (G0, correctness M1, buildability M4).** It scans the
table definitions in:
- `schema.sql` and every `db.py` migration;
- `sessions.SCHEMA`;
- `ytdl/web/schema.sql`;
- the broll and music schemas;
- `client_shares`.

It fails when a column matching `*editor*`, `*user*`, `*_by`, `actor`,
`subject`, `holder`, `owner`, `sender`, `from_addr` or `contractor` sits in a
table that is neither in `SUBJECT_TABLES` (or its per-store equivalent) nor
in `NOT_SUBJECT_TABLES` with a written reason. A planted `editor_username`
column must fail it.

**Collection (G3): `subject_data.collect(conn, username)`.** It adds:
- `ytdl.subject_rows(username)` (G4): `jobs.created_by` and `claimed_by`,
  `job_terms` (what they typed), `job_videos.download_host`,
  `downloads.downloaded_by`, and `attestations.username`;
- read-only opens of `client_shares.db` (`client_folders.created_by`,
  `client_folder_items.added_by`) and of `broll.db` and `music.db`
  `ingest_batches` (editor, machine);
- triage run ids only.

The output is `{"generated_at", "dashboard_version", "subject", "tables",
"not_included"}`. `not_included` lists, in words:
- the computer's own `~/.ccsync`;
- the storage server's files and Syncthing's own database;
- triage report bodies;
- Timeline Cards turn and chat records under `<data>/cards/<slug>` (they are
  per episode, not per person);
- IP-keyed sign-in throttle rows;
- server snapshots.

**Routes (G3, `subject_data_api.py`).**
- `POST /api/v1/admin/users/{username}/export` (admin) and
  `POST /api/v1/me/export` (safety M8).
- Both are POSTs behind the CSRF gate.
- `/me/export` takes the subject from `get_session_user`, **never** from
  `auth.Scope`. For an admin, `Scope.editor` is None (meaning everyone), and
  `?as=` would change the subject.
- One export at a time per user, and at most 5 per user per hour. Over that
  returns 429.
- The file is built in memory with a 50 MB cap. Over the cap returns 413
  with a detail that says so.
- The response is `Content-Disposition: attachment;
  filename="ccsync-data-<username>-<date>.json"`.
- Each export writes a `fleet_audit` row, `user.export`, holding counts only.

**UI (G3).**
- `partials/admin_users.html` gets `[ EXPORT DATA ]`.
- `partials/account_you.html` gets "Download everything the dashboard holds
  about you".

**Tests** (`test_subject_data.py`):
- every registry table appears in the export;
- the secret columns are absent;
- the admin `?as=` does not change `/me`;
- a non-admin gets 403 on another user;
- 413 and 429;
- the audit row;
- the routes are POST-only with CSRF.

### 4.3 LG-3. Erase history, and a complete delete (`per-editor-telemetry-purge`)

**Erase history, keep the account (safety M1: history only).**
`db.purge_subject_history(conn, username) -> dict[str,int]` (G0) deletes only
`kind="history"` rows:
- `lane_report_history`, `transfer_history`, `completion_history`,
  `missing_files`, `diagnostics`;
- `auth_sessions` rows that are revoked or expired, through
  `SessionStore.purge_user(username, revoked_only=True)`. G2a adds it to
  `sessions.py`, and it runs **after** the db commit because the store uses
  its own connection (buildability M2);
- past `login_attempts` for the username, **except** rows whose
  `blocked_until` is in the future (safety L1). An active lockout survives.
- ytdl: finished jobs' `jobs`, `job_terms`, `job_videos` and
  `job_video_terms` rows the person created, through
  `ytdl.forget_history(username)` (G4).

It **never** touches:
- `machine_state` or any `current` row. Those carry `mode` (CR-28),
  `guard_at` and `breaker_tripped` (RESUME), `halt_active`, `verified`, and
  the v58 `cfg_*` columns. The next report rewrites them anyway.
- `editor_media*` and `media_tree_clips`. Deleting them would briefly make
  the machine a non-holder for file moves.
- `downloads`, the "ALREADY IN" dedupe ledger and credit record
  (correctness M2, safety M6).
- attestations, live sessions, tokens, `machines`, `selections`, or
  `editor_prefs`.

The honest limit, shown in the confirm step and in the wording: current state
is what the computer reports now, and LG-1's switches are what stop it.

**Delete, completed (G0 `forget_editor`, G2a `delete_user_everywhere`):**
- **History:** the same history rows as erase, plus all `auth_sessions` and
  `login_attempts` by username (`SessionStore.purge_user(username)`, after the
  commit).
- **Revoked tokens (safety L6):** deleted in a step **after**
  `delete_user_everywhere` revokes them (step 4, `api.py` ~5060-5100). The
  revocation is not moved. A missing token row is already refused
  (`db.py` ~2496).
- **Evidence rows are pseudonymised, not deleted (D2).** The pseudonym is
  `deleted-user-<first 10 hex of HMAC-SHA256(pseudonym_salt, username)>`.
  - **Subject columns** in `fleet_audit`, `alert_log` and `notices`, and the
    requester columns in `jobs`, `file_moves` and `resolve_undo_requests`,
    are pseudonymised.
  - **Free text** is pseudonymised too, as whole words: `fleet_audit.detail_json`,
    `alert_log.detail`, `notices.body` and `notices.fix`, including
    `editor/machine` subject shapes. The person's machine names are replaced
    as well, with `deleted-machine-<hmac>`.
  - **Notices collision:** `notices` is UNIQUE(kind, subject). When a
    rewrite collides, the older row is deleted, because notices are
    transient.
  - **Actor columns of privileged actions keep the real name** until the
    normal 180-day audit prune (safety M5). That keeps the security trail
    intact. The wording says so.
- **ytdl:** `ytdl.forget_requester(username)` (G4):
  - first releases or cancels any **live** lease the person holds;
  - then pseudonymises `jobs.created_by` and `claimed_by` on finished jobs,
    `downloads.downloaded_by` and `attestations.username`;
  - deletes `job_terms` for their jobs;
  - keeps `downloads` (dedupe) and attestations (evidence).
- **Client folders:** `subject_data.forget_shares(username)` (G3)
  pseudonymises `created_by` and `added_by` in `client_shares.db`. Links keep
  working.
- **Not covered, and said so in the wording:**
  - `broll.db` and `music.db` `ingest_batches`. `publish_db.py` replaces them
    wholesale from the base rig, so an in-place edit would be undone at the
    next publish.
  - Timeline Cards records under `<data>/cards/`.
  - Triage runs, which age out in 60 days.
  - Server snapshots of the apps dataset (CR-227), which age out on their own
    schedule.

**Pruning (G0).** `db.prune` deletes `editor_report_tokens` revoked more than
180 days ago (`REVOKED_TOKEN_MAX_AGE_DAYS`).

**Route and UI (G3).**
- `POST /api/v1/admin/users/{username}/erase-history`, admin only, behind
  CSRF. It writes `user.erase_history` to the audit log with counts only.
- The confirm step reads: "This removes their past activity. Their computers
  keep reporting their current state unless you switch reporting off for
  them."

**Tests.**
- `test_legal_db.py` (G0):
  - erase keeps every `current` column, including `mode`, `guard_at`,
    `breaker_tripped` and `cfg_*`, and keeps `editor_media`;
  - the pseudonym is stable across a session-secret rotation;
  - whole-word text pseudonymisation does not corrupt `alice2` when
    replacing `alice`;
  - a notices collision is handled;
  - the revoked-token prune.
- `test_subject_data.py` (G3): the route is admin-only, and export after
  erase has no history rows.
- ytdl: an active lease is released first, and `downloads` survives.
- sessions: an active block survives `purge_user`.

### 4.4 LG-4. Cleartext dashboard address (`refuse-cleartext-dashboard-url`)

**Scope, narrowed after audit (safety H3, buildability H6).** The companion
**refuses** a dashboard address that is plain http **on the public
internet**. It **warns** for plain http on the studio network or tailnet.

"Require https for the whole site" is **deferred** to Tier 2b. As designed in
revision 1, one tick could silence the live `http://192.168.0.10:8480` fleet,
and the report reply is the only way a fix could reach those machines.

**Companion (G1b owns `transport.py` and the opener migration; G1a owns
config and UI):**
- **`transport.py` (new).**
  - The body of `upgrade._host_is_local` moves here. `upgrade.py` keeps the
    alias, so the updater's tests still pass. That brings `.lan`,
    `.internal` and `.home.arpa` along (correctness low).
  - `classify(url) -> "https" | "loopback" | "http_local" | "http_public" |
    "invalid"`.
  - **A name the rule does not recognise** (for example a split-horizon DNS
    name) is classified by its resolved addresses, cached for 10 minutes. It
    is `http_public` **only** on positive evidence: an IP literal that is
    public, or a name whose every resolved address is public. When resolution
    fails, the result is `http_local`. The refusal therefore never fires on
    doubt (safety H3).
- **One choke point.** `transport.CleartextGuard` is a urllib `BaseHandler`
  whose `http_request` raises `transport.CleartextRefused` for `http_public`.
  - It is installed in `upgrade.build_no_redirect_opener()`, which
    `reporter`, `selection`, `site`, `broll_ingest`, `ytdl_executor` and
    `ytdlp_manager` already use.
  - G1b moves every other module that sends the fleet credential to
    `dashboard_url` onto that opener: `identity`, `jobs_runner`,
    `project_setup`, `timeline_cards_role` (its tunnel calls only) and
    `sync/server_locate`.
  - A test asserts that no module in the package calls `urlopen` or
    `build_opener` against `dashboard_url` outside the shared opener.
  - HTTPS, loopback and LAN/tailnet http pass untouched. The guard therefore
    cannot affect the live fleet.
- **G1a.**
  - The tray line on refusal: "Not sent: the dashboard address is plain http
    on the internet. Ask your admin for its https address."
  - `config.validate_config` returns an **error** for `http_public`, which
    blocks the save in the settings window only (start is never blocked), and
    a **warning** for `http_local`.
  - `settings_window.py` shows beside the address: "This address is not
    https. It is fine on your studio network or tailnet."
  - `identity._warn_if_plaintext` is deleted; the guard does its job now.
- **Wizard (G8).** `onboarding/steps.py` calls `transport.classify`.
  `http_public` cannot be saved, and `http_local` shows the same note.

**Dashboard (G2a and G2b): record, do not nag (correctness M7, safety M7,
buildability M12).**
- **G2a.** `api_report` classifies how the report arrived:
  - the scheme is `X-Forwarded-Proto` only from `auth.trusted_proxy`,
    otherwise the socket scheme;
  - the host is the `Host` header, classified with the same rule, which is
    ported into `dashboard/netclass.py` (new, G2a) with a parity test against
    the companion's table.
  - It stores the result in `machine_state.report_via`, **only when it
    changes**, inside the report's existing write. There is no middleware
    and no per-request write.
- **G2b.**
  - Settings → Site shows an **informational** line: "N computers reach this
    dashboard over plain http on your network or tailnet. Serving it over
    https (Tailscale Serve does this) is recommended." There is no notice and
    no alert for `http_local`.
  - One alert kind, `dashboard_reached_over_public_http`, is registered with
    its evaluator in `alerts.ALERT_KINDS`. It fires when any machine's
    `report_via` is `http_public`, which only an older companion can still
    produce. That is a real exposure of a password path.
- **Pre-ship check (overseer).** After `<DASH>` is live and before `<COMP>`
  goes current, no machine may show `report_via = 'http_public'`. On the live
  fleet all four machines are expected to be `http_local` or `https`. A
  HiNet-forwarded-port address would show up here.

**Tests.**
- Companion `test_transport.py`:
  - the classify table;
  - split-horizon and failed-resolution cases;
  - the guard is refused only on public;
  - the no-stray-opener scan;
  - the updater alias.
- Wizard: public is refused, LAN is accepted.
- Dashboard: `report_via` is written only on change; X-Forwarded-Proto from an
  untrusted peer is ignored; the alert fires only for `http_public`; the
  classification matches the companion's.

### 4.5 LG-11. One dependency truth for psycopg2 (`companion-frozen-psycopg2`)

**What the gap is.** The cleared paragraph is accurate about what the
base-rig build contains, and it already makes the written offer. What is
wrong underneath it:
- `psycopg2-binary` is in `companion/pyproject.toml` and `build.spec` but
  **not** in `companion/requirements.lock`. So:
  - CI and vendor-feed builds, which install from the lock, do not contain it,
    and their Cards role fails with "No module named 'psycopg2'";
  - `tools/check_licenses.py` cannot see it;
  - `license_allowlist.toml [allow.psycopg2-binary]` targets only
    `dashboard-container`.
- `tools/release.ps1` installs with `pip install -e .`, not from the lock. So
  ship.cmd builds and feed builds are different bytes.

**Decision D6, flipped from revision 1: keep psycopg2 and make it one truth.**
- The pg8000 shim is not a drop-in (correctness H6, safety H4, buildability
  L6):
  - pg8000 takes `timeout`, not `connect_timeout`;
  - it returns `uuid.UUID` where the engine compares against `str`
    (`library_writer._partner_of`);
  - it binds on the server, where the engine relies on client-side
    interpolation (`= ANY(%s)` with lists, `%%`, `memoryview`).
- The engine **writes** into real Resolve project libraries.
- Counsel has already cleared the psycopg2 disclosure and the written offer.

Keeping psycopg2 removes all of that risk. The shim, with the auditors'
requirements, is recorded under Tier 2b in case the owner later wants no LGPL
in the freeze.

**Design (G6).**
1. **Relock** `companion/requirements.lock` with `psycopg2-binary`, using the
   docs/RELEASE.md "Refreshing the lockfiles" steps. Wheels exist for
   win_amd64 and macOS arm64; G6 confirms both in the lock's hashes.
2. **`license_allowlist.toml`.** `[allow.psycopg2-binary]` `targets` gains
   `companion`. Its reason restates the cleared THIRD_PARTY paragraph:
   - separate extension and shared-library files, extracted at run time,
     unmodified;
   - psycopg2's own linking exception;
   - the notice and the written offer.

   `check_licenses.py --strict` passes.
3. **`tools/release.ps1`** installs `pip install --require-hashes -r
   requirements.lock`, then `pip install --no-deps -e .`, the same as CI. The
   macOS scripts do the same.
4. **`tools/scan_frozen.py` (new).** It reads the PyInstaller TOCs and
   **fails** when a top-level distribution is frozen that is not in the
   component's lock. It **passes** psycopg2 only when the allowlist names the
   component as a target. It runs in `release.ps1`, `build_onboard*.ps1`, the
   macOS scripts and the CI release workflows.
5. **Deployed-build check (house rule).** The Cards role reads a project
   library from the `<COMP>` **feed** build on the base rig before it goes
   current.

**Tests.**
- `tools/tests/test_scan_frozen.py`: fixture TOCs for "in the lock" (pass),
  "not in the lock" (fail), and "LGPL without an allowlisted target" (fail).
- A companion test: every `build.spec` hidden import is satisfiable from the
  lock.

### 4.6 LG-17. Retention visibility (`prune-last-run-visibility`)

**Design (G0 and G2b).**
- **`db.collector_health`** keeps its statuses: `red`, `amber` and `green`.
  - It adds `amber` with `note="overdue"` when the latest run was ok and its
    age exceeds `collector_stale_bound`'s observed-cadence bound (reused, not
    re-invented; correctness low, buildability L3).
  - **Only scheduled kinds** can go amber. A kind whose feature is off is
    left out (safety L5).
- **Alerts.** A failed kind already alerts (`collector_kind_failed`,
  `alerts.py` ~3740). The new `collector_kind_overdue` covers only "overdue
  while the last run was ok", and is registered with its evaluator.
- **The home page's collector panel** (`partials/collector_health.html`)
  gets one line: "Retention last ran <time>", taken from the `prune` kind.

**Tests.** Overdue just past the bound and ok just inside it; unscheduled
kinds are never overdue; the alert fires; the line renders.

---

## 5. Tier 2a: document-neutral work built in the same release

None of these changes a cleared sentence. All four are low risk.

### LG-5. EULA acceptance visible fleet-wide

- **Companion.**
  - `eula.report_block()` (G1a owns `eula.py` now that G1b's other work is
    deferred) returns `{"version", "accepted_at", "eula_sha256"}` from the
    on-disk record, or None. There is no path and no text.
  - It is sent as the tolerant section `eula` at the heavy-section cadence.
- **Dashboard.**
  - G2a adds `ReportIn.eula` (tolerant) and `db.set_machine_eula` (G0).
  - G2b shows on the fleet grid one of:
    - "Licence <v> accepted <date>", which is green when the version equals
      the bundled `EULA-VERSION`;
    - "Older licence accepted" (amber);
    - "Not reported" (grey).
  - **The version alone is judged.** The sha is shown and not judged
    (buildability M5), so no second hashing rule is invented.
  - "Not accepted" is never inferred from this column. It remains only the
    existing `licence_pending` block reason.
- **The editor's own machine row on /account** (`partials/account_computer.html`)
  shows the same line. G2b owns that partial after /account commits
  (correctness M12).
- `setup_engine._accept_eula` naming the admin is **dropped**. `SetupContext`
  carries no user.
- **Tests:** stored, rendered, absent shows "Not reported", amber on
  mismatch, never "not accepted".

### LG-12. Licence texts travel with every binary

- **Generating the texts (G6).** `gen_notices.py --write-texts` writes
  `docs/legal/licenses/<component>/<dist>-<version>.txt` and one
  `THIRD_PARTY_LICENSES.txt` per frozen component. The non-pip parts
  (CPython, Tcl/Tk, OpenSSL, libpq) come from `tools/notices_extra/*.txt`.
- **Bundling (G6).** `build.spec`, the onboard spec and the macOS scripts add
  the notices and the concatenated texts as datas.
- **Where they show.**
  - The tray: G1a adds "Open-source licences" to the settings window's About.
  - The wizard: its last page links the file (G8).
- **Dashboard (G2b).** `published_docs.is_published` and `help.py` accept
  `.txt` under `legal/licenses/` only, with a test. Today SUFFIX is `.md`, so
  revision 1's "one-line change" was wrong (correctness M8, buildability L1).
- **Single files (G6):**
  - `dashboard/static/htmx.LICENSE`;
  - `music/web/data/text_encoder/{NOTICE,LICENSE}`, with the modification
    statement "exported to ONNX, text tower only".
- **No wording change.** The cleared "Licence texts" section, which offers
  copies on request, stays true. A sentence pointing at the bundled copy is
  a (counsel) item: section 8.7.

### LG-13. gen_notices hygiene (generated half only)

G6 does the following, **after** wave −1 has committed the working-tree
`gen_notices.py`:
- PEP 503 name normalisation on both the lock side and the venv side;
- drops the `ytdl/web` row, with a comment;
- a generated "Binaries the installer fetches" table, read from the code by
  symbol name. `--check` fails when a pin moves without the notice changing.

**Only the generated half of THIRD_PARTY_NOTICES changes.** Where the
generated table contradicts a cleared hand-section sentence, G6 lists the
contradiction for the owner as a (counsel) item. G6 does **not** edit it.
Regeneration runs after the overseer bumps the versions.

### LG-16. Drift tests

- **Payload pin (G1a).** `companion/tests/test_telemetry_disclosure.py`
  builds a full payload and pins the sorted top-level and `capabilities` key
  sets. It also asserts that every key is either in
  `telemetry_policy.FIELDS` or in an explicit "not personal" list.
  - The failure text reads: "update TELEMETRY.md's payload table, the FIELDS
    table, then this list."
- **Model pin (G2a).** The declared `ReportIn` fields are pinned the same way.
- **Legal docs test (G9, not G2; buildability M11).**
  `dashboard/tests/test_legal_docs.py` asserts:
  - the version lines parse, and `EULA-VERSION` parses;
  - the set of `ENG-GAP` ids present equals `EXPECTED_ENG_GAPS`, which is
    empty after this release;
  - the three EULA copies are byte-identical. There are exactly three:
    `docs/legal/EULA.md`, which `setup_engine._find_eula` also reads, and the
    companion and onboarding assets (correctness low).

---

## 6. Tier 2b: deferred, with the corrected design on record

These wait for the owner (D1). Each one either changes cleared wording or
carries risk this release should not take on. The corrections the auditors
required are recorded here, so a later plan starts from them.

- **Require https for the whole site (was LG-4 part).** If built:
  - the scheme is recorded per machine (`report_via` already does this);
  - Settings refuses the tick unless the page itself is served over https
    **and** every machine seen in 7 days has `report_via='https'`;
  - `/api/v1/site` and the update check are never gated;
  - the appliance default turns on only after Tailscale Serve is verified.
- **LG-6 Resolve edition detection.** Measured on the base rig (Resolve
  21.0.10011, used with the scripting API): nothing on disk says "Studio".
  - The uninstall DisplayName, the `Resolve.exe` ProductName and
    FileDescription all read "DaVinci Resolve".
  - The HKLM key holds only `Version`.

  If built:
  - "studio" comes only from `GetProductName()` inside
    `resolve_bridge.connect()`;
  - the file probe reports only installed or not, plus the version;
  - "free" is never inferred;
  - fixtures come from a real free-edition machine on Windows and on Mac
    before any probe is written.
- **LG-7 Syncthing private-network mode.** It would change PRIVACY §5's
  Syncthing row. If built, the prerequisites are:
  - `syncthing_tailnet_ip` is set;
  - **every** device entry on both sides is rewritten from `dynamic` to
    `tcp://<tailnet>:22000, quic://...`, including `server/accept_device.py`,
    `syncthing_admin`, and `syncthing_client.DEFAULT_DEVICE_ADDRESSES`;
  - the options as they were are saved (NAS in `meta`, editors in
    `~/.ccsync/state`) and restored exactly;
  - the companion applies the mode only on "present and true" and reverts
    only its own change;
  - crash reporting and auto-upgrade are also turned off;
  - the refusal checks for a verified direct tailnet path per machine, not
    the relayed list;
  - it reuses and renames the unread `syncthing_tailnet_only`
    (`DASH_SYNCTHING_TAILNET_ONLY`).
- **LG-8 YouTube acknowledgement and live "unblock".** It would change
  YOUTUBE_FEATURE_NOTICE "Turning it on". If built:
  - enforce it in `site_store.set_many(..., acks=)`, so import and undo
    cannot bypass it;
  - grandfather **once**, behind a `meta` flag. After that, an
    unacknowledged non-UI source records `source=site.toml|env` with no name;
  - route every cookie and POT reader through the injected
    `unblock_enabled()`: `worker.py`, `config.py`, `vendor/ytsearch.py:58`,
    `vendor/downloader.py:118` (marked `# [vendor]` per PROVENANCE.md),
    `ytdl_canary.py:139-142` and `routes_api.py:443`.
- **LG-9 CLI notice wording.** It would change the notice. If built:
  - split the sentence by tool, because Cards and triage use only Claude;
  - record acceptance as `feature="ai_cli_providers"`;
  - the re-prompt is display-only and **never** turns `ai_cli_providers`
    off;
  - "about once a day";
  - grandfather the live `ai_cli_auto_update`;
  - drop `dashboard/design/site.html`, which is the redesign bench.
- **LG-10 YouTube ledger retention.** It would change PRIVACY §7 and the
  notice. If built:
  - prune only `jobs`, `job_terms`, `job_videos` and `job_video_terms` for
    finished jobs;
  - never `downloads` or attestations.

  The delete-time pseudonymising is already in LG-3.
- **LG-14 Server-side uninstall.** If built:
  - a dry run lists the product's objects by their known names and patterns,
    with a confirmation per item;
  - G7 also owns `install_syncthing_app.py`, `setup_syncthing_folder.py`,
    `setup_editor_account.py` and `setup_snapshots.py`, and the dashboard
    records what it provisions;
  - TrueNAS only at first, with Synology documented as manual;
  - the project tree and b-roll archive datasets are never in scope;
  - `--purge-data` requires a named backup that lives off the dataset.
- **LG-15 Triage pseudonymisation.** It would change PRIVACY §5's triage row.
  If built:
  - the mapping is stored **outside** the run folder and the package folder,
    where the agent's Read and Glob cannot reach it;
  - tokens are unambiguous (`«EDITOR-1»`, `«MACHINE-1»`) and mapped back
    **before** `validate_actions`;
  - the wording says "user names and computer names";
  - `alerts.py`'s triage keys and `triage_mail.py` go to the triage group.
- **pg8000 shim (the D6 alternative).** If built:
  - `connect_timeout` is mapped to `timeout`;
  - uuid in-adapters (OID 2950 and its array) return `str`;
  - `autocommit` is supported;
  - MulticamPipeline's `tests/test_library_edits.py` runs against the shim
    on a scratch Postgres library;
  - a live write-and-read on a scratch library is run from the deployed
    build;
  - a config switch turns the Cards role off cleanly, with a tray line, if
    the shim fails.
- **LG-18** (identity rows age out) and **LG-19** (licence entitlement
  display) stay deferred as in revision 1.

---

## 7. Builder groups and hand-offs

### 7.1 Waves

- **Wave −1 (overseer, no builder).** Commit the five legal documents, the
  two EULA asset copies and `tools/gen_notices.py` as one docs commit.
- **Wave 0: G0 alone.** v59 and every `db` helper. Committed before wave 1.
  The only other thing in wave 0 is G1b's `transport.py`, a leaf module with
  no imports from the package. G8 and G2a's parity test depend on it, so it
  lands in the same wave (buildability M11).
- **Wave 1 (parallel):** G1a, G1b (the opener migration), G2a, G2b, G3, G4,
  G6 and G8. Each codes against the names in 7.3.
- **Wave 2:** G9 (docs and `test_legal_docs.py`). Then the overseer bumps the
  versions, runs G6's regeneration and runs the full gate.

### 7.2 File ownership (disjoint)

| Group | Owns | Features |
|---|---|---|
| **G0 db** | `dashboard/src/ccsync_dashboard/db.py`; NEW `dashboard/tests/test_legal_db.py` | v59; `pseudonym_salt`, `pseudonym`; `apply_report_optouts`, `apply_site_optouts`, `withheld`; `set_machine_eula`, `set_machine_report_via`; `SUBJECT_TABLES` / `NOT_SUBJECT_TABLES` + the coverage test (reads every schema listed in 4.2); `purge_subject_history`; extended `forget_editor` (text pseudonymising, notices collision, revoked-token delete helper); the file-move rule; backlog "not reported"; `collector_health` amber/overdue; the revoked-token prune |
| **G1a companion telemetry + UI** | `companion/src/ccsync_companion/{config.py, reporter.py, capabilities.py, app.py, settings_window.py, site.py, eula.py}`; NEW `telemetry_policy.py`; NEW tests `test_telemetry_policy.py`, `test_telemetry_disclosure.py`, `test_eula_report.py`; edits to existing tests of those modules | LG-1 companion, LG-4 config validation and UI, LG-5 companion, the LG-12 About action, the LG-16 payload pin |
| **G1b companion transport** | NEW `companion/src/ccsync_companion/transport.py` (wave 0); `upgrade.py`, `identity.py`, `jobs_runner.py`, `project_setup.py`, `timeline_cards_role.py`, `sync/server_locate.py` (opener migration only); NEW `test_transport.py` | LG-4 guard and opener migration |
| **G2a dashboard wire** | `dashboard/src/ccsync_dashboard/{api.py, sessions.py, netclass.py (NEW), telemetry_fields.py (NEW, the dashboard's FIELDS copy)}`; NEW tests `test_report_optouts.py`, `test_report_via.py`, `test_report_model_pin.py`, `test_sessions_purge.py` | LG-1 strip, apply, upload-only and costs; LG-3 `delete_user_everywhere` and `SessionStore.purge_user`/`subject_rows`; LG-4 `report_via`; LG-5 section; LG-16 model pin |
| **G2b dashboard settings + views** | `dashboard/src/ccsync_dashboard/{site_store.py, settings.py, setup_routes.py, alerts.py, health.py, published_docs.py, help.py}`; `dashboard/static/{site_settings.js, setup.js, style.css (chips only)}`; `dashboard/templates/{admin_settings.html, partials/fleet_grid.html, partials/collector_health.html, partials/account_computer.html}`; edits to `tests/test_site.py`; NEW tests `test_site_telemetry.py`, `test_legal_alerts.py`, `test_published_licenses.py` | LG-1 site policy, clear-on-save, chips; LG-4 Settings line and alert; LG-5 views; LG-12 `.txt` publishing; LG-17 panel and alert |
| **G3 subject rights** | NEW `dashboard/src/ccsync_dashboard/{subject_data.py, subject_data_api.py}`; `dashboard/src/ccsync_dashboard/app.py` (the `include_router` line only); `dashboard/templates/partials/{admin_users.html, account_you.html}`; NEW `dashboard/tests/test_subject_data.py` | LG-2, the LG-3 route, UI and `forget_shares` |
| **G4 ytdl** | `ytdl/web/ytdlweb/db.py`; `dashboard/src/ccsync_dashboard/ytdl.py`; NEW `ytdl/web/tests/test_ytdl_subject.py` | `subject_rows`, `forget_history`, `forget_requester` (lease release first) |
| **G6 release + notices** | `companion/{requirements.lock, build.spec}`; onboarding build spec; `tools/{release.ps1, gen_notices.py, check_licenses.py, license_allowlist.toml, scan_frozen.py (NEW), build_onboard*.ps1, release_macos.sh, build_onboard_macos.sh}`; `tools/notices_extra/` (NEW); `tools/tests/{test_scan_frozen.py, test_gen_notices.py}`; `.github/workflows/release-*.yml`; `dashboard/static/htmx.LICENSE` (NEW); `music/web/data/text_encoder/{NOTICE,LICENSE}` (NEW); `docs/legal/licenses/` (generated); the generated half of `THIRD_PARTY_NOTICES.md` | LG-11, LG-12 (build side), LG-13 |
| **G8 wizard** | `onboarding/{steps.py, onboard.py}`; NEW `onboarding/tests/test_legal_steps.py` | the LG-1 privacy step (writes the four `report_*` keys), the LG-4 address check, the LG-12 licences link |
| **G9 docs (wave 2)** | `docs/legal/PRIVACY.md` and `TELEMETRY.md` **(the ENG-GAP paragraphs only)**; the hand half of `THIRD_PARTY_NOTICES.md` **(the ENG-GAP paragraph only)**; NEW `dashboard/tests/test_legal_docs.py`; `docs/CONFIG.md`, `docs/API.md`, `docs/GOTCHAS.md` (a Cards-agent note), `KNOWN_BUGS.md` (one CR per shipped item), `CLAUDE.md` (one invariant line each for LG-1 "collect then withhold; site strip on arrival" and LG-4) | section 8 |

Files **nobody** edits:
- `docs/legal/EULA.md` and its two asset copies.
- `docs/legal/YOUTUBE_FEATURE_NOTICE.md`.
- Every cleared paragraph outside an ENG-GAP marker.
- `account_api.py`, `account_ui.py`, `auth.py`, `account.html`, and the
  /account partials other than the three assigned above.
- `server/*`: there is no G7 in this release.
- `design/*`.

### 7.3 Hand-offs

| From → To | Contract |
|---|---|
| G0 → G2a, G2b, G3, G4 | the `db.*` names in G0's row, with the signatures in section 4; G0 commits first |
| G1b → G1a, G8, G2a | `transport.classify(url) -> str`, `transport.CleartextGuard`, `transport.CleartextRefused`; the classification table G2a's `netclass` must match |
| G1a → G2a | the `telemetry_policy.FIELDS` table; G2a's `telemetry_fields.py` copy is pinned equal by a test on each side |
| G1a → G8 | the four `report_*` config key names |
| G2b → G2a | `site_store.telemetry_policy(conn, settings) -> set[str]` |
| G2a → G0 | `SessionStore.purge_user(username, revoked_only=False)` and `SessionStore.subject_rows(username)`, both called after the db commit |
| G3 → G2a | `subject_data.forget_shares(username)`, called from `delete_user_everywhere` |
| G4 → G2a, G3 | `ytdl.forget_requester(username)`, `ytdl.forget_history(username)`, `ytdl.subject_rows(username)` |
| G6 → G1a | the bundled path `assets/THIRD_PARTY_LICENSES.txt` |
| G2a → G1a | note J's answer (does undo key on the journal id?) before G1a finalises the journals row |

---

## 8. Replacement wording for the ENG-GAP paragraphs

G9 replaces **exactly** the paragraph after each marker, removes the marker,
and changes nothing else. Placeholders: `<DASH>`, `<COMP>`. There are none in
the wording itself, which names no version. Every sentence below was checked
against the design in section 4, not against an ideal one.

### 8.1 `telemetry-opt-out-switches`

**PRIVACY §6** (replaces "Data minimisation (Art. 5(1)(c)). CC Sync does not
currently provide a setting ...", through "... should weigh this before
deploying."):

> **Data minimisation (Art. 5(1)(c)).** Four kinds of reporting can be
> switched off without stopping sync, for one computer or for the whole site:
> the name of the open Resolve project wherever it is reported, the list of
> media files on the computer's disk and the file names in its Resolve and
> conflict checks, the Resolve bin structure, and the time since the last
> keyboard or mouse input. Switching one off also deletes what the dashboard
> already held about it. `docs/legal/TELEMETRY.md`, "What can be turned off",
> says how, what still goes to the dashboard, and what each switch costs.

**TELEMETRY "What can be turned off"** (replaces "Everything else cannot
currently be turned off. ..." through "... to the workstations concerned."):

> **Four more switches, per computer or for the whole site.** On a computer:
> Settings, THIS COMPUTER, PRIVACY (or the setup wizard's privacy step). For
> the whole site: the dashboard's Settings, Site, TELEMETRY. They are:
> `resolve_project` (the open project's name, wherever the companion reports
> it, including Resolve health and fix journals), `local_manifest` (the disk
> file list, plus the file names in the Resolve health and sync-conflict
> checks, which are then sent only as counts), `media_tree` (the bin
> structure; switching off the project name switches this off too, because
> the bin structure is organised by project name), and `input_idle` (the idle
> time, which is also not sent while `jobs_enabled` is false). Sync is not
> affected.
>
> A switched-off item is not sent. The dashboard also discards it on arrival
> from any computer while the site switch is off, including computers whose
> companion predates these switches. It deletes what it already held: for a
> site switch at once for every computer, and for a computer's own switch on
> that computer's next report, together with that computer's stored
> diagnostics bundles. A site switch can only switch items off; a computer
> cannot switch back on what the site has switched off, and the dashboard
> cannot switch a computer's own switches back on.
>
> Still sent, because sync or the editor's own action needs them: the names
> of files being transferred and recently transferred, the result of a file
> move the dashboard ordered, a project name the editor types or sends when
> setting up a project, and, only if an editor turns on the Timeline Cards
> agent for their computer, the project and timeline it is driving.
>
> The costs are deliberate. With the file list off, the dashboard sends every
> file move in every active project to that computer, and shows its holdings
> and upload progress as "not reported". With the project name off, the
> dashboard does not offer to set up a new project for it, the editor cannot
> be the first to map a Resolve project to a folder (an administrator can),
> and projects are not mapped automatically from that computer. With the idle
> time off, that computer is not offered background jobs that wait for an
> idle computer.

(If note J finds that undo keys on the project name, G9 adds to the costs:
"and CC Sync's fixes to that computer's Resolve projects cannot be undone
from the dashboard".)

### 8.2 `telemetry-export`

**PRIVACY §8, access and portability** (replaces the bullet's text after the
bold lead):

> **Access and portability (Arts. 15, 20).** An administrator can download
> everything the dashboard holds about a person as one JSON file (Settings,
> Users, Export data), and each person can download their own from their
> account page. The file lists what it does not include: files on the
> person's own computer and on the storage server, Syncthing's own database,
> the text of server triage reports, Timeline Cards working records (kept per
> episode, not per person), sign-in throttle records kept by network address,
> and server snapshots.

**TELEMETRY retention** (the paragraph under both markers, rewritten together
with 8.3):

> An administrator can export everything the dashboard holds about a person,
> erase their activity history while keeping their account, or delete them
> entirely, as described under "Data-subject rights" in
> `docs/legal/PRIVACY.md`. Each person can also export their own data from
> their account page.

### 8.3 `per-editor-telemetry-purge`

**PRIVACY §8, erasure** (replaces the bullet's text after the bold lead):

> **Erasure (Art. 17).** An administrator can erase a person's activity
> history while keeping their account (Settings, Users, Erase history). That
> removes their computers' past lane and transfer history, completion and
> missing-file records, stored diagnostics bundles, expired sign-in sessions,
> past failed sign-ins (an active sign-in lockout is kept), and the finished
> YouTube requests they made. It does not remove their computers' current
> state, which the computers report again on each report; the switches in
> section 6 are what stop that.
>
> Deleting a person on the Users page removes them from the whole product:
> their account (including their NAS account), every one of their computers'
> records, their Syncthing devices, their known-editor entry, their sessions,
> their history as above, and every credential that could act as them. Where
> the dashboard keeps a record of something done (the audit log, alerts and
> notices, background and YouTube jobs, file moves, YouTube downloads and
> rights attestations, and client-folder entries), the person's name and
> their computers' names are replaced by a fixed stand-in, except that an
> administrator's name stays on the audit entries for actions they took until
> those entries expire after 180 days.
>
> Not covered by either action: the b-roll and music indexes' record of which
> computer indexed a batch (replaced when the index is next published),
> Timeline Cards working records, server triage runs (deleted after 60 days),
> and snapshots of the dashboard's storage, which expire on their own
> schedule. Revoked credentials are deleted 180 days after revocation.

### 8.4 `refuse-cleartext-dashboard-url`

**PRIVACY §10** (replaces the bullet's text after "**Transport.**"):

> **Transport.** The companion refuses to send anything, including an
> editor's password, to a dashboard whose address is plain `http://` on the
> public internet, and says so on the tray. The setup wizard will not accept
> such an address. Over plain `http://` to an address on the studio's own
> network or tailnet it works, and shows a note in its Settings; tailnet
> traffic is encrypted underneath by WireGuard. The dashboard records how
> each computer reaches it, shows how many use plain http, and raises an
> alert if any computer reaches it over plain http from the public internet.
> The supported deployment serves the dashboard over HTTPS with Tailscale
> Serve.

**TELEMETRY "Transport and authentication"** (replaces the bullet after the
marker):

> **Plain http is refused on the internet and noted on a private network.**
> Every request the companion makes to `dashboard_url` goes through one guard
> (`transport.py`): a plain `http://` address on the public internet is
> refused before anything is sent, and `config.validate_config` rejects it; an
> address on the local machine, the studio's network or a tailnet is allowed
> with a note in Settings. A name is judged public only when every address it
> resolves to is public. The dashboard stores, per computer, whether its last
> report arrived over https, plain http on a private network, or plain http
> from the internet (`machine_state.report_via`).

### 8.5 `companion-frozen-psycopg2`

**THIRD_PARTY_NOTICES** (the marker is removed. The cleared paragraph is kept
word for word, and one sentence is appended to it):

> Every companion build, whether built on the Licensor's own machine or by
> its build service for the release feed, is built from the same locked list
> of dependencies, which names psycopg2, and a release build fails if it
> freezes a package that list does not name.

### 8.6 `prune-last-run-visibility`

**PRIVACY §7, caveat 2** (replaces the text after the marker):

> `db.prune` runs only inside the dashboard's collector. The home page's
> collector panel shows when retention last ran, turns amber when it is
> overdue, and the dashboard raises an alert, on its home page and through
> the configured alert channel, when it fails or is overdue.

**TELEMETRY, caveat 2** (keeps the first three sentences, and replaces "The
dashboard does not currently show ... reports no stopped collector." with):

> The collector panel on the home page shows when retention last ran and turns
> amber when it is overdue, and a failed or overdue retention pass raises an
> alert.

### 8.7 (counsel) items, not made by any builder

The overseer sends these to the owner as one list for counsel. None of them
blocks the release.
1. **PRIVACY §8, Objection.** It still says objection "in practice means
   excluding that person's workstation from reporting". A suggested
   replacement: "A person who objects to a category of reporting can have it
   switched off for their computer (section 6) without leaving the system."
   This is outside an ENG-GAP marker.
2. **THIRD_PARTY "Licence texts".** An optional added sentence: "Each binary
   also carries these texts (About, Open-source licences, on the tray; the
   last page of the setup wizard; the dashboard's Help, Legal)."
3. Any contradiction G6's generated pin table finds in the cleared hand
   section (LG-13).
4. **(D12) A light read of the six replacement paragraphs above.** The
   default is that they ship on the ENG-GAP convention counsel approved.
   Counsel is sent them as information, and the release does not wait.

---

## 9. Open decisions for the owner

Each decision has a default. A builder proceeds on the default unless the
owner says otherwise before wave 1.

| # | Decision | Recommended default | Why |
|---|---|---|---|
| D1 | Scope of this release | **Tier 1 (the six ENG-GAP features) + Tier 2a (LG-5, LG-12, LG-13, LG-16). Tier 2b waits** | Tier 1 is everything the cleared documents say is missing. Tier 2b either reopens counsel-cleared wording or, like private mode, risks stopping lane C |
| D2 | Audit, alert, YouTube and client-folder rows on delete | **Pseudonymise and keep**, with an HMAC stand-in keyed on a dedicated salt; admin actors kept until the 180-day prune | They are the studio's record of what was done; the stand-in removes the person |
| D3 | Plain http | **Refuse public, note private; no site-wide "require https" yet** | A require-https tick could silence the live `http://192.168.0.10:8480` fleet with no over-the-air way back |
| D4 | Idle time | **Keep seconds; stop sending when jobs are off; add the switch** | The scheduler ranks by longest idle |
| D6 | psycopg2 in the companion | **Keep it, put it in the lock and the allowlist, scan every build** (flipped from revision 1) | Counsel already cleared its disclosure and offer; the pg8000 shim would bind differently inside Resolve's own project database |
| D11 | When EULA 1.1 reaches editors | **With the next companion release (the /account one)**, after telling editors they will be asked to accept once | Committing the cleared documents (wave −1) puts 1.1 in the next build. Its acceptance stops that computer's sync lanes until the editor accepts, and admins already see this as the `licence_pending` block reason. The alternative is to hold the two asset copies at 1.0 until `<COMP>`, which means stashing them for the /account ship (ship.cmd refuses a dirty tree) |
| D12 | Counsel review of the six replacement paragraphs | **Send as information; the release does not wait** | ENG-GAP was counsel's own convention for exactly this update |
| D15 | Erase-history scope | **History only; current state stays (the switches stop it)** | Deleting current state loses base-rig mode, breaker and halt state, and briefly hides a holder from file moves, for nothing: the next report rewrites it |

D5 (relays default), D7 (seats), D8 (identity ageing), D9 (triage
pseudonymising), D10 (ledger retention), D13 (EULA 1.2) and D14 (turning on
private or https mode) belong to Tier 2b features. They are not open for this
release.

---

## 10. Audit response

All three audits (correctness, safety, buildability) were checked point by
point. Accepted points are folded into sections 1 to 9. This list says where
each went, and which were rejected or answered differently.

**Correctness audit**
- **H1** (written against the old drafts): **accepted in full.**
  - The plan now targets the working-tree text and the six ENG-GAP markers
    (sections 1 and 8).
  - X1 to X19 are dropped (X19 re-derived: the model rows already exist).
  - LG-16's test checks ENG-GAP ids and version lines.
  - Wording outside a marker is (counsel).
- **H2** (the project name and file lists leave by other routes): **accepted.**
  The FIELDS table in 4.1 names every carrier, gated in one place, with a new
  redaction helper. **Partly answered differently:** transfer file names and
  `file_moves_applied` are kept, because sync needs them, and the wording
  names them instead of claiming they stop.
- **H3** (enforce on the dashboard): **accepted.** It is the strip in
  `api_report` and the clear-on-save.
- **H4** (missing readers): upload-only and conflicts are **accepted**.
  - First claim: **rejected** as a workaround ("accept the name the companion
    POSTs in the popup flow"). The popup is triggered by
    `resolve_project_unmapped`, which needs the very name that is withheld,
    so that flow never starts. It is listed as a cost in the wording instead.
- **H5** (private mode breaks lane C): **accepted.** LG-7 is deferred, with
  the corrected prerequisites in section 6.
- **H6** (pg8000 is not a drop-in): **accepted, answered by D6.** psycopg2 is
  kept, and the shim requirements are recorded in section 6.
- **H7** (erasure wording over-promises): **accepted.** Erase history is
  worded exactly, with the uncovered stores listed (8.3).
- **M1** (the coverage columns and a stable salt): **accepted** (4.2, 3.1).
- **M2** (ytdl column names): **accepted** (4.3).
- **M3, M4, M5** (YouTube and CLI): **accepted** into the deferred LG-8 and
  LG-9 designs.
- **M6** (every module that talks to the dashboard): **accepted** as one
  guard in the shared opener, plus a migration and a scan test.
- **M7** (a flapping notice): **accepted**, answered by removing the notice
  entirely (`report_via` plus a public-only alert).
- **M8** (`.txt` publishing): **accepted.**
- **M9** (the uninstaller removes nothing): **accepted** into the deferred
  LG-14.
- **M10** (triage tokens): **accepted** into the deferred LG-15.
- **M11** (the edition probe): **accepted** into the deferred LG-6.
- **M12** (unowned files): **accepted.** Section 7.2 now owns
  `account_computer.html` and `help.py`. The ytdl vendor files and
  `accept_device.py` belong to deferred features.
- **Lows:** all accepted.
  - LG-4 uses "the same function".
  - LG-17 uses amber with a note, not a new status.
  - "About once a day" is in the deferred LG-9.
  - X10 is dropped: the Sentry row is kept as cleared.
  - There are three EULA copies.
  - The `login_attempts` lockout is kept.

**Safety audit**
- **H1** (private mode): **accepted.** LG-7 is deferred with the corrected
  design. The "present and true" contradiction goes with it.
- **H2** (collectors must keep running): **accepted.** "Collect, then
  withhold" is a ground rule and a test.
- **H3** (require-https silences the fleet): **accepted.** Require-https is
  deferred, and the public-only refusal is classified by resolved address and
  never fires on doubt.
- **H4** (the pg8000 shim writes into Resolve's database): **accepted**, via
  D6.
- **H5** (the mapping is readable by the triage agent): **accepted** into the
  deferred LG-15.
- **M1** (erase wipes safety state): **accepted** (D15, 4.3).
- **M2** (the file-move rule): **accepted.** Every active project, wired
  machines excluded.
- **M3** (site policy dropped silently): **accepted** (`normalise` plus the
  dashboard strip).
- **M4** (wording not true of the design): **accepted** (FIELDS, costs and
  the "still sent" list).
- **M5** (pseudonyms): **accepted.** Salt, text fields and actor retention.
- **M6** (the ledger prune and column names): **accepted.**
- **M7** (the middleware notice): **accepted.** No middleware, write on
  change, trusted-proxy only.
- **M8** (the export route): **accepted.** POST, CSRF, session user, limits,
  `password_hash` excluded.
- **M9** (the CLI re-prompt): **accepted** into the deferred LG-9.
- **L1 to L7:** all accepted. L3, the purge-data scope, is in the deferred
  LG-14. L4, never inferring free, is in the deferred LG-6.

**Buildability audit**
- **H1** (the version numbers): **accepted.** Placeholders, capability by
  column, and no versions in the wording.
- **H2** (`normalise`): **accepted.**
- **H3** (unowned settings files; the acknowledgement at `set_many`): the
  files are **accepted** and owned by G2b. The acknowledgement moves with
  LG-8 to Tier 2b. Clear-on-save goes through `set_many`, so import and undo
  are covered.
- **H4** (the edition probe): **accepted** (deferred, with the measurement
  recorded).
- **H5** (other carriers of the project name): **accepted** (FIELDS, the
  journals note J, and the costs).
- **H6** (the require-https promise): **accepted** (narrowed; require-https
  deferred).
- **H7** (EULA 1.1 sequencing): **accepted as an explicit owner decision
  (D11) rather than the proposed hold.** Holding the asset copies at 1.0 while
  `docs/legal/EULA.md` is 1.1 breaks the three-copy byte-identity pin and the
  `/setup` copy. The admin-side visibility the audit wanted already exists as
  `licence_pending`. The recommended default is therefore to let 1.1 ride the
  next companion release, with editors told first. The hold remains the
  alternative.
- **H8** (G2 too large): **accepted.** It is split into G2a (wire) and G2b
  (settings and views). The router line goes to G3. There is no server-ops
  group this release.
- **M1** (a second negotiation mechanism): **accepted.** `report_accepts` is
  dropped in favour of /account's tolerant-section convention (3.2).
- **M2** (session tables): **accepted.** `SessionStore.purge_user` and
  `subject_rows`, after the commit.
- **M3** (pseudonymisation detail): **accepted.**
- **M4** (missed tables): **accepted.**
- **M5** (LG-5 ownership and the sha): **accepted.** The version alone is
  judged, `account_computer.html` goes to G2b, and the setup-detail change is
  dropped.
- **M6** (the LG-7 restore path): **accepted** into the deferred design.
- **M7, M8, M10:** **accepted** into the deferred LG-8, LG-9 and LG-15.
- **M9** (LG-14): **accepted** into the deferred design.
- **M11** (the waves are not independent): **accepted.**
  - `transport.py` moves to wave 0.
  - `test_legal_docs.py` moves to G9.
  - G3 and G4 depend only on G0 names.
  - G4 no longer needs site keys this release.
- **M12** (the notice fires permanently): **accepted** (no notice).
- **L1 to L7:** all accepted.
  - L2's stale references are fixed: auto-map is at ~9986-10006, there is no
    `_redact`, and the CR-68 test is not needed now that LG-6 is deferred.
  - L4's `kind` field is added.
  - L5's `test_site.py` is listed.
  - L6 is answered by D6.
  - L7: wave −1 commits `gen_notices.py`.

**Rejected outright:** none. Two proposals were replaced by a different
answer to the same concern: the first-claim popup workaround (correctness H4)
and holding EULA 1.1 at 1.0 (buildability H7). The reasons are given above.
