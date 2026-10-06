# MODULAR_UPDATES.md - test and ship one part of the dashboard without the rest

**Status: PLAN, 2026-10-06. Phase M1 (scoped test selection) is BUILT,
2026-10-06; section 9 says what it is and where it differs from this
plan. Everything else here is still plan.** Written after Alex
asked: *"can we split all the different modules of the dashboard out so they
can be updated separately, you don't need to do a full gate every time for
every change, only changes that affect certain modules of the dashboard?
Like the way you can update cards only"*, and then *"yes write up the plan
to be able to update modules separately"*.

Treated as the outcome wanted (a small change gets a small gate and a small
deploy), not as a verified design. Section 2 says where the request and the
code disagree, because that changes the order of the work.

Companion reading: `ZERO_DOWNTIME_DEPLOY.md` (removing the restart gap; this
plan leans on it), `CARDS_DEPLOY.md` (the one module that already ships
alone), `RELEASE.md` section 6 and `RELEASE_PATHWAYS.md` (how dashboard code
ships today), `CI.md`.

---

## What Alex gets (plain language)

- **A change gets the tests that can see it, not all of them.** A companion
  fix stops waiting 20 minutes for the dashboard's tests. A b-roll page fix
  runs the b-roll tests, the b-roll mount tests and a short "does everything
  still start" check. A change to something everything leans on (the
  database, the login, the page shell, the dependency lists) still runs
  everything, automatically.
- **Nothing rots unnoticed.** The full set of tests still runs every night
  and before anything goes to customers. A customer release can never be
  built from a commit that only passed a partial check.
- **You can ship a b-roll, music or YouTube-downloader fix on its own,** the
  way Cards ships today, even when the rest of the dashboard has unfinished
  work in it, and roll just that part back.
- **What does not change yet:** every deploy still restarts the dashboard for
  a few seconds. That goes away with the separate zero-downtime work, and
  this plan is built so the two fit together.
- **The honest headline:** the slow part today is the test gate, not the
  shipping. The dashboard already ships as one signed bundle in about ten
  seconds. So most of the benefit is phase 1 (scoped tests), and it applies
  to far more changes than the module split does (section 2).

---

## 1. Where things stand (verified 2026-10-06)

| Unit | Code lives | How it reaches the studio | How it reaches customers | Gate today |
|---|---|---|---|---|
| dashboard core | `dashboard/src`, `templates`, `static`, `deploy` | OTA bundle: `tools/build_dashboard_bundle.py` -> `tools/publish_feed.py --kind dashboard` -> Packages [ APPLY ] (image mode since 2026-08-18) | the same bundle from the vendor feed | CI runs all suites on every push; `ship.cmd` gates on `server/` |
| b-roll web (`/broll`) | `broll/web`, imported as top-level `app` | **inside the same bundle** (`TREES`: `broll/web -> broll-app`) | same | as above |
| music web (`/music`) | `music/web`, package `musicweb` | inside the bundle (`music-app`) | same | as above |
| ytdl web (`/ytdl`) | `ytdl/web`, package `ytdlweb` | inside the bundle (`ytdl-app`) | same | as above |
| Timeline Cards (`/cards`) | **another repo** (MulticamPipeline) | `install_dashboard_app.py --cards-commit <ref>`: `git archive` snapshot into `<host-root>/cards-web` with a `DEPLOYED_COMMIT` marker, mounted `:ro` at `/cards-app`, appended to `sys.path` by `cards._add_to_path`; **then a container restart** | not shipped to customers | that repo's own gate (`run_all.py --fast` for iteration) |
| Cards integration | `dashboard/src/ccsync_dashboard/cards*.py`, `templates/cards_landing.html` | part of the core bundle | same | as core |

Facts this plan rests on, each read from the tree:

- **Image mode has one signed code unit.** `select_code_root.py` (image code)
  verifies `/data/code/<version>/record.json` and prints all four roots
  (`src`, `broll-app`, `music-app`, `ytdl-app`) from that ONE bundle, or the
  image's own. The host trees `broll-web`, `music-web`, `ytdl-web` exist on
  the NAS but are bind-mode only: `IMAGE_MODE_CODE_MOUNTS` in
  `install_dashboard_app.py` drops them in image mode.
- **The mounts are already tri-state and never fatal.** `broll.mount_broll`,
  `music.mount_music`, `ytdl.mount_ytdl` / `load_ytdl_app` and
  `cards.mount_cards` each return `(status, detail)`; an import failure is
  ABSENT, a storage failure is DEGRADED, and `/api/v1/health` reports all
  four under `mounts`. That is the hook a version check plugs into.
- **The sub-apps do not import `ccsync_dashboard`** (grep, 2026-10-06). The
  coupling is by copied contract instead: `identity.py` in all three ("TWO
  PROPERTIES ARE COPIED FROM ccsync_dashboard.auth AND MUST NOT DRIFT"),
  `ytdlweb/routes_fleet.py` (copied `token_ok`), `ytdlweb/ai_backend.py`
  (allow-list copied from `cli_tools`), and hooks the dashboard calls into
  at mount time (`fleet_auth` / `routes_fleet.trust_gate_stamp`,
  `ai_backend.set_provider_lookup`).
- **The suites are cross-tree in both directions.** About 40 dashboard test
  files name `broll`, `music`, `ytdl` or `companion` (for example
  `test_broll_mount.py`, `test_help_doc_matches_the_companion.py`,
  `test_jobs_contract.py`), and the `broll/web`, `music/web` and `ytdl/web`
  conftests reach into `ccsync_dashboard`. A naive "folder -> its own suite"
  map would be wrong on day one.
- **Measured cost.** The latest CI run on `main` (0c37831, 2026-10-06): the
  dashboard suite alone is **5,973 tests in 20 min** on the Linux runner; the
  whole CI run is about 25 min wall clock. Every push runs all of it.
- **The full gate is red on `main` right now**: the last two CI runs failed
  the Linux job with 2 dashboard failures
  (`test_bug_hunt_2026_09_11_dash_api_jobs.py::test_a_cancelled_job_does_not_come_back_when_the_lease_expires`,
  `test_run_sh_restart_loop.py::test_an_exit_75_restart_picks_up_a_nightly_staged_while_the_app_ran`).
  Scoped gating needs a green baseline to diff against (phase M0).
- **The live commit is not on the wire.** `/api/v1/health`'s `code` block
  (`dashboard_update.health_code_block`) reports `running`, `image`,
  `source`, `runtime_id`, but not a commit. The bundle's `manifest.json`
  does record `git_commit` (`build_dashboard_bundle.py`), and the image is
  tagged with the short sha. The `v*` git tags stop at v0.7.44 while 0.7.73
  is live, so "the last shipped tag" is not a usable base.

## 2. What the request gets right, and where the code disagrees

Of the last 60 commits (classified by hand from `git log`, 2026-10-06), 17
were docs/ledger only. Of the 43 that touched code, roughly:

| Shape | Count | Would a module split help? | Would scoped tests help? |
|---|---|---|---|
| never touched the dashboard (companion, onboarding, installer, indexers, tools) | ~15 | no, nothing to deploy | **yes, skips the 20-min dashboard suite** |
| Cards integration only (`cards*.py` + its template) | ~3 | already ships separately | yes, `test_cards_*` instead of everything |
| b-roll / music / ytdl web only | ~0 to 2 | yes | yes |
| dashboard core, or core plus a module | ~25 | no, core has to ship anyway | some: skips the companion/onboarding/bench suites |

So the module split Alex pictured (b-roll, music and ytdl each shipped on
their own) would have applied to almost none of the last 60 commits, because
those trees rarely change alone. Scoped tests would have applied to about
half. That is why phase 1 is the test map and the deploy split comes second.

Two details the classification surfaced that the map must handle:

- **Every dashboard commit touches `dashboard/src/ccsync_dashboard/__init__.py`
  and `dashboard/pyproject.toml`** (the VERSION bump). If those count as
  "core", nothing is ever scoped. A diff whose only change in those files is
  the VERSION line is neutral.
- **`templates/shell.html` and `base.html` changed in Cards commits**
  (0c37831, 5a26e10). Every page extends `shell.html`, so those correctly
  force the wide gate even though the commit was "about Cards".

---

## 3. Part A: change-scoped test gating

### A.1 One map, data not ifs

`tools/test_map.toml`, read by one stdlib script, `tools/select_suites.py`.
Each **area** is a list of path globs and what they select. First match in
file order wins; **a path that matches no area selects the full gate** (fail
closed: an unmapped file is the map's bug, never a reason to skip tests).

The tiers, smallest to largest:

1. **neutral**: nothing but the smoke set.
2. **scoped**: the area's own suites and test files, plus the smoke set.
3. **dashboard-wide**: the whole dashboard suite plus every suite that
   imports `ccsync_dashboard` (`broll/web`, `music/web`, `ytdl/web`,
   `tools`, `server`), plus smoke. Not companion, onboarding, bench, the
   indexers or installer.
4. **full**: all 13 suites, `check_licenses.py`, `gen_notices.py --check`.

The starting map (a builder verifies each row against A.5 before trusting it):

| Area | Paths | Tier / selects |
|---|---|---|
| docs | `docs/**` except `docs/legal/**`, `KNOWN_BUGS.md`, `SPEC.md`, `*/README.md` | neutral + `tools/tests/test_docs_index.py` |
| version stamp | `dashboard/src/ccsync_dashboard/__init__.py`, `dashboard/pyproject.toml`, `companion/src/ccsync_companion/config.py`, `companion/pyproject.toml`, **only when the diff is the VERSION line alone** | neutral |
| companion | `companion/**` | companion suite (Windows + macOS jobs) + the dashboard files that read companion source: `test_help_doc_matches_the_companion.py`, `test_jobs_contract.py`, the telemetry field parity tests |
| onboarding | `onboarding/**` | onboarding suite + EULA copy parity |
| installer | `installer/**` | every `installer/tests/Test-*.ps1` and `test_*.sh` |
| server | `server/**` | server suite (through Git Bash, as today) |
| bench / indexers | `bench/**`, `broll/indexer/**`, `music/indexer/**` | their own suite |
| tools | `tools/**` except the gate files below | tools suite |
| b-roll web | `broll/web/**`, `broll/schema.sql`, `broll/migrations/**` | broll/web suite + dashboard `test_broll_*.py`, client-share and stage-a-folder tests |
| music web | `music/web/**` | music/web suite + dashboard `test_music_*.py` |
| ytdl web | `ytdl/web/**` except `ytdlweb/ytdlp_nightly.py` | ytdl/web suite + dashboard `test_ytdl_*.py` |
| Cards integration | `dashboard/src/ccsync_dashboard/cards*.py`, `templates/cards_landing.html`, Cards static | dashboard `test_cards_*.py` |
| dashboard core | everything else under `dashboard/src`, `dashboard/templates`, `dashboard/static`, `dashboard/tests`, `dashboard/design` | dashboard-wide |
| **shared** | see A.3 | full |

### A.2 The smoke set (always runs, whatever changed)

Small, fast, and aimed at the seams between modules, which is exactly what a
scoped run would otherwise miss:

- **boot and mounts**: `dashboard/tests/test_mount_status.py`,
  `test_broll_mount.py`, `test_music_mount.py`, `test_ytdl_mount.py`,
  `test_cards_mount.py`, `test_secrets_boot.py`, plus one new
  `test_smoke_boot.py`: build the app with all four mounts, GET each mount
  root, GET `/login`, an unauthenticated GET of a gated page redirects, and
  `/api/v1/health` lists all four mounts.
- **cross-module contracts**: `broll/web`, `music/web` and `ytdl/web`
  `tests/test_mounted_prefix.py` (document-relative URLs under the mount),
  the identity/fleet-auth parity tests ("MUST NOT DRIFT"), and the
  module-API range test from B.3.
- **owner rules**: every suite's em-dash scan (`dashboard/tests/test_no_em_dash.py`,
  `broll/web` and `music/web` `test_no_em_dashes.py`, `ytdl/web`
  `test_no_em_dash.py`), `tools/tests/test_docs_index.py`.

Phase M0 measures the smoke set's wall time with `--durations`; the target is
under two minutes. If a file in it is slow, split the fast assertions out
rather than dropping it.

### A.3 What forces the full gate

Anything every module leans on, or anything that decides what the tests
themselves mean:

- **schema and data**: `dashboard/src/ccsync_dashboard/db.py`, `schema.sql`
  (ytdl reads `projects`, `machine_state` and `editor_media_project` straight
  out of the dashboard's database: `ytdlweb/projects.py`).
- **process and routing**: `app.py`, `settings.py`, `site_store.py`,
  `secrets_boot.py`, `mount_status.py`, `dashboard/deploy/**` (`run.sh`,
  `Dockerfile`, `select_code_root.py`; `run.sh` also runs
  `ytdlweb.ytdlp_nightly` at boot, which is why that one ytdl file is here).
- **auth**: `auth.py`, `sessions.py`, `local_users.py`, `oidc.py`, the login
  gate, `loopback`-facing contracts.
- **the shell the UI hangs on**: `ui.py`, `ui_chrome.py`, `ui_assets.py`,
  `templates/shell.html`, `base.html`, `partials/topbar.html` (the SPAs fetch
  it from `/partials/topbar`), `static/sw.js` and the shared `cc` CSS.
- **AI and site switches**: `ai_providers.py`, `cli_tools.py`,
  `site.example.toml`, anything that reads `[features]`.
- **dependencies**: every `requirements.lock`, `requirements.txt`,
  `pyproject.toml` beyond the VERSION line.
- **the gate itself**: `tools/test_map.toml`, `tools/select_suites.py`,
  `tools/run_all_tests.ps1`, `tools/ship*.ps1`, `.github/workflows/**`, any
  `conftest.py`, `.gitattributes`.
- **shipped paperwork**: `docs/legal/**` (it travels in the bundle and in
  three byte-identical EULA copies).

### A.4 What the diff is taken against

Not `HEAD~1`. A scoped run is only safe if everything since the last
**proven-whole** state is inside its diff. The base is the older of:

1. **the commit live on the studio dashboard**, and
2. **the last commit that passed the full gate** (recorded by CI, A.6).

For (1) the dashboard has to say which commit it runs: add `commit` to
`dashboard_update.health_code_block`, read from the running bundle's
`manifest.json` `git_commit`, or from a `CCSYNC_GIT_SHA` the image build
bakes in when the image's own code is running. Small, and useful on its own
(the drift doctor `check_deploy_drift.ps1` can show it). Cards already has
its own answer in `DEPLOYED_COMMIT` and the base rig's deploy record.

The diff is `git diff --name-only <base>...HEAD` **plus** `git status
--porcelain` (uncommitted and untracked files), because a ship can run on a
dirty tree with `-AllowDirty`. If the base cannot be found (no network, no
record), the answer is the full gate.

### A.5 Keeping the map true: derive it, then check it

A hand map will miss a dependency. Two checks, both in the tools suite and
both in the full gate:

- **`tools/tests/test_test_map.py`**: every tracked file matches some area
  (so "unmapped means full" stays an exception, not the norm), and every
  area names suites and test files that exist.
- **an import-graph check**: walk each test file's imports with `ast`
  (stdlib), resolve them to repo files, and fail if a test imports a source
  file whose area does not select that test. Test files also read sources by
  path (`Path(...) / "broll" / "web"`, `parents[3] / "companion"`), so the
  check also scans string literals for repo paths. The failure message prints
  the row to add. This is how the map gets built in the first place: generate
  it, read it, commit it.

### A.6 Who reads the map

- **`tools/run_all_tests.ps1`** gains `-Changed [-Base <ref>]`: it calls
  `select_suites.py`, prints the plan ("scoped: broll/web + 6 dashboard files
  + smoke; reason: broll/web/app/routes_api.py"), then runs only those, with
  the same interpreters and the same Git Bash rule for `server/`. No flag
  means today's behaviour.
- **`tools/ship.ps1`**: its own gates (the `server/` suite before a deploy,
  `release.ps1`'s companion suite) run when the map selects them, and always
  when the tier is full. `-SkipTests` keeps its meaning.
- **CI (`.github/workflows/ci.yml`)**: a first small job computes the plan
  from the push's diff against the last full-green commit and exports it;
  the Windows, Linux and macOS jobs skip the steps not selected. Pull
  requests do the same against their merge base.
- **The builders' rule stays** ("tests run once, centrally", 2026-09-03): a
  builder still runs only the files it touched; the orchestrator's one
  central run becomes `run_all_tests.ps1 -Changed`.

### A.7 The full gate does not go away

- **Nightly**: add `schedule:` (cron) to `ci.yml`, full gate on `main`. A red
  nightly is mailed by GitHub to the owner; later it can feed the
  dashboard's alert registry as a notice.
- **Before anything reaches a customer**: CI records the tier it ran in the
  build artefact's manifest (`gate: full | scoped`).
  `tools/publish_latest.py` already refuses a run that is not green on
  `main`; it also refuses a scoped one. `build_dashboard_bundle.py` refuses
  to build a feed bundle from a commit with no full-green run (an
  `--allow-scoped` flag for a deliberate studio-only hotfix, recorded in the
  manifest the way `git_dirty` is).
- **On a `v*` tag and on `workflow_dispatch`**: full.
- **The studio dashboard may take a scoped-gated bundle.** That is the point
  of the exercise, and the nightly catches what it missed within a day.

---

## 4. Part B: shipping one module on its own (the studio)

### B.1 What each module is actually tied to

| Module | Imports dashboard code? | Hooks the dashboard installs | Database ties | UI ties | Own threads | Boot-time ties |
|---|---|---|---|---|---|---|
| b-roll web | no (by design) | `fleet_auth` trust stamp; `BrollGate` stamps identity headers | own `broll.db` (user_version, `_schema_too_new`), `client_shares.db` | `/partials/topbar`, `html.cc` look, mounted-prefix URLs | none | none |
| music web | no | `MusicGate` identity headers | own `music.db` (published by `publish_db.py`) | same | none (the text encoder is loaded in-process) | none |
| ytdl web | no | `trust_gate_stamp`, `set_provider_lookup` (ai_providers), `YtdlFeatureGate` per-request site switch | own `ytdl.db`, **and reads the dashboard's `projects`, `machine_state`, `editor_media_project`** | same | worker, canary, nightly (`worker.py`, `ytdl_canary.py`, `ytdlp_nightly.py`) | `run.sh` runs `ytdlweb.ytdlp_nightly install` with `PYTHONPATH=/ytdl-app` |
| Timeline Cards | `cards_ai` via `ai_providers`; bridge contract | `fleet_execute` seam (`cards_exec.py`), models catalogue (`set_catalogue`, probed with `getattr`) | per-episode `<data>/cards/<slug>` | own pages; landing page is core | engines, library sweep, ffmpeg worker, translators | none |

The copied contracts (identity, fleet token, the CLI allow-list, the
machine-mode SQL) are the real API between core and modules. Today nothing
names their version; B.3 does.

### B.2 Two ways to ship a module alone, and the recommendation

**B-1. A mixed-commit bundle (RECOMMENDED for b-roll, music and ytdl).**
The bundle is already a list of trees (`TREES` in
`build_dashboard_bundle.py`). Add `--module broll=<ref>` (repeatable): the
core trees come from the **live** commit (A.4), the named module's tree from
`git archive <ref>:broll/web`, exactly the way `export_cards_snapshot` takes
Cards. `manifest.json` records a commit per tree, health reports them under
`mounts.<name>.commit`, and the result is an ordinary signed bundle with a
new VERSION that goes through Packages [ APPLY ] like any other.

Why this rather than copying the Cards folder pattern:

- **no new mount, no new trust path.** It stays inside
  `select_code_root.py`'s signed-bundle rule; nothing on the NAS changes
  shape, and no image rebuild is needed.
- **customers can get it too**, unchanged (Part C).
- **rollback per module** is "build the same bundle with the old module
  ref", and the live core is untouched.
- **it tests what ships**: the gate runs in a temporary worktree assembled
  exactly as the bundle will be (live core + new module), with the module's
  area selected plus smoke.

Cost: every module ship is a VERSION bump on the dashboard (rule 5 of
`select_code_root.py`: a bundle must be newer than the image), and the core
that ships is the live one, not `main`. Both are features here.

**B-2. Cards-style host folders (an option, not the default).** Generalise
`--cards-commit` in `install_dashboard_app.py` to `--module <name>
--module-commit <ref>`: the same `export_cards_snapshot` /
`write_cards_marker` / `record_cards_deploy` steps, parameterised by subtree,
writing `<host-root>/modules/<name>/` with `DEPLOYED_COMMIT` and a
`module.json`. One new read-only mount (`<host-root>/modules:/modules:ro`)
added in `compose_config`, which costs one container recreate to introduce.
Each mount function gains a small shared helper (`module_override.py`): if
`/modules/<name>/module.json` exists and is compatible (B.3), **insert** it at
the front of `sys.path` before the import (b-roll's package is the top-level
name `app`, so the override must shadow the bundle's copy, unlike Cards,
which appends because it is never in the bundle); otherwise log why and
import the bundle's copy. Then `docker restart` and
`verify_dashboard_after_restart`, as the Cards deploy does.

B-2 is the right shape only if a module ever needs to move faster than
bundles can be built, which nothing today suggests. It is also studio-only
(the host folder is written over SSH by the base rig, the same trust Cards
has), and the ytdl override would not reach `run.sh`'s boot-time nightly
install, which reads `/ytdl-app`. **Recommendation: build B-1; keep B-2 on the
shelf.** Cards stays as it is: it is another repo, so it cannot be in the
bundle.

### B.3 The compatibility contract: a module says what core it needs

- **Core** gets `dashboard/src/ccsync_dashboard/module_api.py` with
  `MODULE_API = 1` and a short changelog: what level N means (the headers the
  gates stamp, the hooks called at mount, the dashboard tables a module may
  read, the topbar partial's contract). Any change to one of those bumps it.
- **Each module** declares the range it works with, next to its code:
  `MODULE_API_RANGE = (1, 1)` in `broll/web/app/__init__.py`,
  `musicweb/__init__.py`, `ytdlweb/__init__.py`, and a module constant in
  `multicam_pipeline.cards` for Cards.
- **Checked three times, before anything half-loads:**
  1. at **build** (`build_dashboard_bundle.py --module`, or the installer for
     B-2/Cards): refuse a module whose range excludes the core's level;
  2. in the **gate**: a smoke-set test pins that every in-repo module's range
     includes the current `MODULE_API`, so a core change that bumps the level
     fails until every module is updated or deliberately left behind;
  3. at **mount**: the declaration is read before the import (from
     `module.json`, written at build time, so no module code runs to answer
     it). Out of range means not imported; the mount reports `DEGRADED`
     with the sentence "b-roll was built for dashboard API 2-2, this server is
     1" and, for B-2, falls back to the bundle's own copy. If an import fails
     part way, the helper drops the module's entries from `sys.modules` and
     tries the bundled copy once (no threads have started at that point); if
     that fails too, `ABSENT` exactly as today.
- **Module schema**: a module ship that migrates its own database forward
  (b-roll's `ensure_schema`, music's, ytdl's) cannot be rolled back past that
  migration: the older code meets `user_version ... newer than this app
  supports` and the mount goes DEGRADED. `module.json` records the module's
  schema version and the build refuses a rollback across a migration without
  `--allow-schema-rollback`. This is the same rule as ZERO_DOWNTIME_DEPLOY
  ZD-1 (`online_safe`, `schema_floor`), applied to the module databases; build
  them together.

### B.4 The restart, honestly, and how this meets zero downtime

**Every module deploy restarts the dashboard until the zero-downtime work
lands.** B-1 is an OTA apply (SIGTERM self, exit 75, `run.sh` loop); B-2 and
the Cards deploy are a `docker restart`. The few-second gap, the Cards
engines rebuilt on next entry and the in-flight uploads lost
(ZERO_DOWNTIME_DEPLOY section 1) all still apply.

Once ZD-3 (the socket-handover supervisor) exists, a module ship is just
another handover: the new process boots with the new module, proves healthy,
and the old one drains. That covers every module the same way, which is why
this plan does **not** propose reloading a module inside the running
process. For the record, which modules could be swapped in-process and why
it is not worth building:

- **b-roll and music: possible in principle.** No threads, state on disk,
  and each sits behind a gate object that could be pointed at a fresh app.
  But the package names live in `sys.modules` (`app`, `musicweb`), module
  globals are set by mount-time hooks (`fleet_auth`, identity), and music
  would reload its text encoder (memory doubles for the swap). `ytdl`'s
  `YtdlFeatureGate` already loads its sub-app lazily on a request, so the
  pattern exists, but only for a first load.
- **ytdl: no.** Its worker, canary and nightly threads are singletons
  (ZERO_DOWNTIME_DEPLOY 3.3); a swap would need the lease machinery anyway.
- **Cards: never.** Its engines own threads that do not honour `stop()`
  (`cards_pool` refuses to evict for exactly this reason), and its writes to
  `<data>/cards/<slug>` are read-merge-write through a fixed `.tmp`.

So the two plans fit: this one makes the *gate* and the *unit* small; ZD
makes the *swap* free. Neither waits for the other.

---

## 5. Part C: customers and the signed OTA path

**Now: nothing new to build.** A B-1 mixed-commit bundle is still one
dashboard bundle: signed by the offline release key, carrying a
`runtime_id`, subject to the same `min_version` floor and the same
"newer than the image" rule, published with `publish_feed.py --kind
dashboard`. Customers take it exactly as they take any dashboard update.
The only rule that changes is A.7's: a feed bundle needs a full-green commit
for its core and its modules alike.

**Per-module signed records (a `dashboard-module` feed kind): later, if
ever.** What it would take, and why not now:

- `select_code_root.py` is image code, so teaching it to compose a code root
  from several signed records needs a new image on every customer's NAS
  first, and a runtime update there is a manual click (RELEASE.md section 6).
- every module gets its own version, floor and rollback, and a customer's
  dashboard becomes a combination nobody tested. The support matrix grows as
  the product of the module versions in the field.
- the Packages page, the soak gate, `[ UPDATE NOW ]` and recall each grow a
  per-module dimension.

At one studio plus a handful of feed sites, whole bundles assembled per
module (B-1) give customers the same outcome with none of that. Revisit when a
customer needs one module on a different cadence from the rest.

---

## 6. What could go wrong

| Risk | What it looks like | Mitigation |
|---|---|---|
| **the map misses a dependency** | a change ships with the test that would have caught it unselected | unmapped paths fail closed to full (A.1); the import-graph and path-literal check (A.5); the nightly full gate catches it within a day; a feed release needs a full-green commit |
| **a module shipped against an incompatible core** | the mount half-loads, or 500s every page | `MODULE_API` checked at build, in the gate and at mount, before import (B.3); an out-of-range module is not loaded and says why |
| **skew between the copied contracts** | identity headers or the fleet token check drift between core and a module | the parity tests are in the smoke set and run on every change, whatever the area |
| **module rollback across a migration** | the older module refuses its database; `/broll` DEGRADED | `module.json` schema version; the build refuses without an explicit flag (B.3); ZD-1's floor rule for the dashboard's own DB |
| **a red baseline** | scoped runs inherit failures nobody owns | M0 makes `main` green first; the nightly is the owner of "is the whole thing green" |
| **the smoke set grows until it is the full gate** | the win quietly disappears | a duration budget on the smoke set (two minutes), checked in M0 and in the nightly's timing output |
| **the live commit is unknown** | the selector cannot find a base | it answers "full gate", never "scoped from HEAD~1" |
| **a scoped studio bundle is mistaken for a feed release** | a partially tested bundle reaches customers | `gate: scoped` in the manifest; `publish_feed.py` / `publish_latest.py` refuse it |
| **B-2 only:** an override folder outlives its reason | the studio silently runs an old module over a newer bundle | health reports `source: override` and the commit per mount; the drift doctor flags an override older than the bundle's copy |

---

## 7. Build order

| Phase | What | Size | Depends on |
|---|---|---|---|
| **M0** | Make `main` green (the two failures above). Measure per-suite and per-file timings (`--durations=50`), confirm the smoke set fits two minutes. Add `commit` to the health `code` block. | small | nothing |
| **M1** (BUILT 2026-10-06, section 9) | `tools/test_map.toml`, `tools/select_suites.py` (stdlib), the VERSION-line rule, `run_all_tests.ps1 -Changed`, `test_test_map.py` + the import-graph and path-literal check, `test_smoke_boot.py` | medium | M0 |
| **M2** | CI: plan job, per-step skips, nightly `schedule`, full on `v*` and dispatch, `gate:` in artefact manifests, `publish_latest.py` and `build_dashboard_bundle.py` refuse scoped for the feed | small to medium | M1 |
| **M3** | `ship.ps1` reads the plan for its gates | small | M1 |
| **M4** | `module_api.py`, the ranges in each module, the build/gate/mount checks, `module.json` with schema version | small | M1 |
| **M5** | B-1: `build_dashboard_bundle.py --module <name>=<ref>` on the live core, per-tree commits in the manifest and in health, the assembled-worktree gate, rollback recipe in RELEASE.md | medium | M2, M4 |
| (M6) | B-2 host override folders, only if decision 4 says so | medium | M4 |
| (later) | per-module signed feed records | large | a new image everywhere |

Rough sizes: small is under a day for one builder, medium one to three days.
M0 to M3 deliver the part Alex will feel (most changes stop waiting on the
full gate) and are independent of ZERO_DOWNTIME_DEPLOY; ZD-5 (polite pages
through a restart) is still worth doing first on that side, and ZD-1's
schema-floor rule should land with M4.

---

## 8. Decisions for Alex (each with a default)

1. **Should the studio's own dashboard take changes that passed only the
   scoped tests?** Default: **yes**; the nightly full run backs it up, and
   customers never get a scoped build.
2. **When does the nightly full run happen, and who hears about a red one?**
   Default: **03:00 Taipei time on GitHub's runners, failure mail to
   the owner** (GitHub's own notification), a dashboard notice
   later.
3. **What is the diff measured from?** Default: **the older of "what is live
   on the studio dashboard" and "the last full-green commit"**, so nothing
   since the last proven-whole state is ever skipped.
4. **Ship a module alone by building a bundle with just that part newer (B-1)
   or with separate folders on the NAS like Cards (B-2)?** Default: **B-1**:
   no NAS change, works for customers too, same rollback story.
5. **Separate module downloads for customers?** Default: **not now**; whole
   bundles assembled per module give them the same result. Revisit when a
   customer needs one part on its own schedule.
6. **Fix the two failing tests on `main` before starting?** Default: **yes,
   first**; scoped testing needs a green starting point.

The owner took every default, 2026-10-06.

---

## 9. What M1 built (2026-10-06), and where it differs from this plan

**The pieces.**

- `tools/test_map.toml`: the 13 suites (pinned equal to
  `run_all_tests.ps1`'s rows), the `dashboard-wide` tier, the two full-gate
  checks, the smoke set, the audit's import roots, and 24 areas in
  first-match order.
- `tools/select_suites.py` (stdlib): `--base REF` (repeatable; the merge base
  of all of them and HEAD, i.e. the older), `--head REF` (a range, working
  tree ignored: the shape M2's CI plan will use), `--files PATH...`,
  `--json`, `--json-out FILE`, and `--audit` (A.5's check, printing the row
  to add).
- `tools/run_all_tests.ps1 -Changed [-Base <ref>,<ref>]`: prints the plan,
  then runs only the selected suites, whole or file by file, with the same
  interpreters and the same Git Bash rule for `server/`; under a full plan it
  also runs `check_licenses.py` (non-strict: not every lock is installed
  locally) and `gen_notices.py --check`. **No flag is the old run, byte for
  byte, all 13 suites and no checks.** `-Base` without `-Changed` is refused.
- `tools/tests/test_test_map.py` and `dashboard/tests/test_smoke_boot.py`.

**How the live commit gets in.** M0 adds `code.commit` to `/api/v1/health`;
until M2 records the last full-green commit, the caller passes both:
`tools\run_all_tests.ps1 -Changed -Base <live>,<last-green>`. No base, or a
base the clone does not have, is the full gate (A.4), so `-Changed` alone
runs everything and says why.

**Where the code differs from the design, and why.**

1. **The rows are wider than the starting map.** The audit found 169 tests
   that a change in some area would not have run, and every one was folded
   in as a `tests` entry (marked "found by select_suites.py --audit"). The
   big ones: the Cards row carries 30 more dashboard files (tests that import
   `cards_exec` / `cards_ai` / `cards_tunnel`, and the CSS, template and JS
   scans that read every file in `static/` and `templates/`); the docs row is
   no longer "smoke + the docs index" but 22 files across six suites that
   read a doc, `KNOWN_BUGS.md` or a `.gitignore`; the three SPAs each select
   the other two's `test_theme_css.py` / `test_cc_body.py` (they pin a shared
   copy). Section 2's estimate is therefore optimistic for docs-only and
   Cards-only commits, which now run a few dozen files instead of a handful;
   still far short of 5,973.
2. **b-roll web also runs the `broll/indexer` suite whole**: that suite's
   conftest builds its database from `broll/schema.sql`.
3. **The version-stamp row runs two tests.** `test_hardening.py` and
   companion `test_config.py` pin that the two copies of each VERSION agree;
   a bump that moves one copy is exactly what a neutral run must still catch.
   It is also the FIRST row (first match wins; below `dependencies` it could
   never match a pyproject). A changelog comment added to
   `ccsync_dashboard/__init__.py` is not the VERSION line, so it falls
   through to dashboard core, as written.
4. **`templates/base.html` is not in the map**: it was retired by the CC
   Terminal port, and `test_test_map.py` refuses a row that names a missing
   file.
5. **"Anything that reads `[features]`"** is taken as the readers:
   `settings.py`, `site_store.py`, `ai_providers.py`, `cli_tools.py`,
   `site.example.toml`. The consumers that only ask the shared predicate
   (`ytdl.py`, `cards_ai.py`, `triage.py`, `notices.py`) stay in their own
   areas; otherwise half the tree would be full-gate.
   **"`loopback`-facing contracts"** is the companion's `loopback_guard.py`
   (the dashboard origin allow-list). The three EULA copies, `LICENSE` and
   `.dockerignore` are full-gate too.
6. **Unmapped corners got rows rather than the full gate**: `broll/eval`,
   `broll/docs`, `broll/morning_report.py` go with the b-roll indexer,
   `music/eval` with the music indexer, `CLAUDE.md` and every `.gitignore`
   with docs. `test_test_map.py` fails on any file no row claims, so
   "unmapped means full" stays the exception.
7. **The smoke set gained `tools/tests/test_test_map.py`**, so a new
   cross-tree test or an unclaimed file fails the scoped run it arrives in
   rather than the nightly (about 5 s). The "identity / fleet-auth parity
   tests" are `broll/web` and `ytdl/web` `test_fleet_credentials.py` and
   `music/web` `test_fleet_ingest.py`: no dedicated parity files exist. The
   module-API range test arrives with M4.
8. **`test_smoke_boot.py` boots the REAL in-repo b-roll, music and ytdl
   trees** (with conftest's `YTDL_WORKER=0`, and removing what it imported
   afterwards), because the seam a scoped run misses is "this checkout's two
   halves no longer fit", which the fakes in `test_*_mount.py` cannot see.
   Cards is the exception: its code is another repo, so its half is the fake
   checkout `test_cards_mount.py` builds. 9 tests, about 7 s.
9. **The diff is the net `git diff <base>` plus untracked files**, not the
   union of `<base>...HEAD` and `git status`: the same set, except that a
   file changed and then changed back is (correctly) not a change.
10. **The audit is a heuristic, on purpose biased to over-select.** Direct
    imports (including function-level ones and `importlib.import_module`),
    plus whatever a test helper in a `tests/` directory imports; string
    paths resolved against each ancestor of the test file. Three
    simplifications keep it honest rather than noisy: a directory that is an
    import root (`parents[1] / "src"`) is a `sys.path` entry, not "every
    file in src"; a package directory counts as its `__init__.py` (the
    bundle tests copy the tree, they do not read every module); a
    module-level `DOCS = REPO / "docs"` used only as a prefix is not "all of
    docs". Traversal fixtures (`2.1.234/../..`) and URLs are ignored. The
    installer's PowerShell and bash tests are not scanned.

**Not done in M1, by design:** CI (M2), `ship.ps1` (M3), the nightly, and
the smoke set's two-minute budget measurement (M0).

## Related

- `ZERO_DOWNTIME_DEPLOY.md`: the handover that removes the restart; ZD-1's
  schema floor pairs with B.3.
- `CARDS_DEPLOY.md`: the snapshot deploy B-1 borrows `git archive` from.
- `RELEASE.md` section 6 and `RELEASE_FEED.md`: the bundle, the feed, the
  runtime-id rule.
- `CI.md`: what runs where today.
