# Tree layout as site data - removing the hard-coded names, and learning a customer's template from their own projects

Written 2026-08-19, the day after `TREE_LAYOUT_AGNOSTICISM.md` (the audit this
plan executes). The owner's ask:

> write out a detailed plan for how to remove hard-coded references to various
> title, and give the customer a way to just show the dashboard config one or
> multiple project directories and get it to extrapolate a working template
> for that customer.

Two deliverables, in that order because the second depends on the first:

1. **Every tree name the product uses is one value, published by the
   dashboard, read by every component** - `Projects`, `Proxy`, the `Assets/*`
   libraries, `Youtube`, the popup fixer's drop targets, the video extension
   list. Today they are literals in ~60 places across five components
   (`TREE_LAYOUT_AGNOSTICISM.md` §3-§6).
2. **A "Learn my layout" step in the dashboard's first-run Setup**: the admin
   points it at one or more of their existing project folders on the NAS; it
   scans them, proposes the `[tree]` configuration with evidence per line,
   the admin edits and confirms, and it writes the site keys, lays down
   project markers and asset folders, and publishes. No site.toml editing.

Related: `TREE_LAYOUT_AGNOSTICISM.md` (what is hard-coded, with line numbers),
`COMMERCIAL_READINESS.md` item 11 (the 2026-08-17 pass that did the tree root
and drive letter), `ZERO_TOUCH_PLAN.md` (the Setup page this plugs into),
`CONFIG.md` (keys), `SPEC.md` (lane model), `MULTI_MACHINE_PLAN.md` (how the
dashboard delivers a command to a companion, reused in WP4).

---

## STATUS

* Nothing built. This document is the plan; WP0 below is the audit, done.
* Decisions D1-D6 are **proposed** and need the owner's yes/no before WP1.

---

## 0. Two things the owner's phrasing could mean, and how this plan reads them

The ask says "one or multiple project directories". It can mean either:

* **(a) several *sample* projects to learn from** - "here are three of our
  projects, work out our template from them." That is the core of deliverable
  2 and is what WP3 builds. More samples = better inference (a folder present
  in 3 of 3 samples is template; in 1 of 3 is not).
* **(b) several *project roots*** - "our active projects are in `Work/`, our
  archive is in `Archive/`, sync both." The audit found this has no
  representation anywhere (§4.3: one `projects_dir` string, one bind mount,
  one Syncthing prefix, one `local_root` per companion). It is real work and
  is WP6, explicitly after everything else.

Both are in the plan. (a) ships first because it is what makes a customer's
first hour work; (b) is the one that changes schema.

One thing the learner **cannot** extrapolate and will instead *detect and
explain*: a customer whose proxies do not live in a sibling folder of the
media (a mirror tree, a `_proxy` suffix, Resolve's own cache-folder proxies).
The sibling-folder rule is the definition of the three sync lanes (audit
§4.1), and no template can express "proxies somewhere else". The learner
reports what it found and says plainly what the product supports. Widening
that is a separate project (audit item 8) and is out of scope here.

---

## 1. Decisions to make before building (challenge these)

The owner is not an engineer and has asked for outcomes; each of these is a
technical choice that falls out of the ask, stated so it can be overruled.

**D1. One layout object, published in the manifest, and the literals become
its defaults.** Every component gets a `TreeLayout` (companion
`layout.py`, dashboard `provision.Layout`, server `common.Layout`, b-roll /
music / ytdl read it from env the way they read `DASH_SITE_*` today). Its
fields carry today's names as defaults, so a dashboard that has never been
told anything behaves exactly as today and an old companion talking to a new
dashboard sees additive keys it ignores. Recommended; the alternative (a
flag per name) is what produced the half-wired `projects_dir`.

**D2. The dashboard container mounts the tree root, not `Projects/`.** Today
the container sees `<tree>/Projects` at `/projects` and nothing above it
(`install_dashboard_app.py:1178,1256`), which is why `Assets/*` are derived as
`projects_dir.parent` and why the learner could not look at a customer's tree
at all. Syncthing already mounts the tree root at `/data`
(`install_syncthing_app.py:108`). Proposal: the dashboard mounts the tree root
at `/tree` (rw - it already creates projects and asset folders) and derives
`projects_dir`, the assets prefix and the Syncthing prefixes from the layout
**at runtime, from the DB**, not from deploy-time env. Consequence: changing
the projects dir name no longer needs a redeploy. `/projects`, `/broll-data`
and `/music-share` stay as they are for one release and are retired once
nothing reads them.

**D3. `.ccsync-project` markers stay the definition of a project.** The
learner lays markers down; it does not replace them with "any folder at depth
N" or "any folder with a `.drp`". Markers are what make depth free, survive a
rename, and let a project move (`sync/repath.py`). Not negotiable in this
plan; noted because a customer will ask "why the hidden file".

**D4. The proxy folder is renameable, not relocatable.** The manifest gains
`proxy_dir_name` (default `Proxy`). Every filter, stignore line, scanner and
relinker reads it. `Proxies`, `proxy`, `PRX` all work. "Beside the
originals" does not (§0). The learner enforces this: it will not write a
layout it cannot sync.

**D5. A layout change is a fleet-wide flag day, made safe by a revision
number.** The manifest carries `layout_rev` (monotonic int, bumped on every
layout write). Each companion reports the rev it is running; the collector's
stignore repair and the companion's stignore writer both refuse to write a
`.stignore` for a rev they disagree on (today they would rewrite the file at
each other forever - SPEC.md's shared-asset note describes exactly this
failure). The dashboard shows machines on an old rev; the report reply
carries `commands.refresh_site` so a companion re-fetches without a restart
(today it fetches once per start, `app.py:4776`).

**D6. The learner proposes, the admin confirms, nothing moves.** It reads the
tree, shows a proposal with evidence, and on Apply writes: site rows, marker
files, `mkdir` of asset folders. It never renames, moves or deletes a
customer folder, and never touches a file that is not a marker. Dry-run list
first, `snapshot_before()` first on a NAS that has snapshots (the same call
`chown -R` and the deploy swap make).

---

## 2. The layout object

One shape, three languages of default. Field names are the manifest keys.

| Key | Default (today's literal) | Read by | Notes |
|---|---|---|---|
| `projects_dir` | `Projects` | server, dashboard, companion (17 sites), ytdl `app.js` | Rel to tree root. The half-wired key from audit §3.2 |
| `proxy_dir_name` | `Proxy` | companion (filters, stignore, scanner, relinker, generator, breaker, manifest), dashboard (`classify_media`, stignore), server (stignore), b-roll indexer/web (6 sites), ingest | Case-insensitive match, written in the configured case |
| `template_folders` | `AE, Audio/Music, Audio/Voiceover, B-roll, Interviewees, Render in Place, Subs, Youtube` | server, dashboard - ALREADY site data; companion does not need it | unchanged |
| `shared_assets` | `[{rel: "Assets/Luts", role: "luts"}, {rel: "Assets/Stills", role: "stills"}]` | server, dashboard (already), **companion `syncthing_admin`, `luts.py`, `stills.py` (new)** | Gains a **role** so the companion knows which one to point Resolve's LUT pref / gallery at. Roles: `luts`, `stills`, `broll_archive`, `music`, `other`. Today's CSV of rels keeps working (role inferred from the leaf name) |
| `broll_archive_rel` | `Assets/B-roll Archive` | server (2 binds), companion (`broll_server`, `broll_fetch`, ingest), b-roll web (`ingest_batches:688`) | Could be the `broll_archive` role's rel; kept as its own key because the archive is a mount, not a Syncthing folder |
| `music_library_rel` | `Assets/Music` | server bind, companion (`music_server`, `music_ingest`), music web (`config.py:38`, `ingest_batches:558`) | same |
| `youtube_dir` | `Youtube` | ytdl web (4 files + `app.js`), companion (`youtube_import`, `ytdl_executor`) | Only meaningful with `[features] youtube_download` |
| `fixer_targets` | `{audio: "Audio/Music", image: "B-roll/Stills", video: "B-roll/Editor Added/{editor}"}` | companion `fixer.py:70-86,207` | `{editor}` substituted from `editor_name` |
| `video_extensions` | the 16 in `dashboard/provision.py:27-31` | dashboard, server, companion (4 copies), b-roll | Today published read-only; becomes writable **additively** - a site may ADD extensions, never remove the built-ins (removing one would make lane C carry video) |
| `layout_rev` | `0` | everyone | D5 |
| `trash_dir`, marker filename, `.ccsync-tmp`, `.partial` | unchanged | - | Product internals, not the customer's layout; stay literal on purpose |

Not in the layout: the Resolve bin names (`B-Roll/Archive`, `Youtube`) - they
are media-pool labels, not folders; leave them until someone asks.

---

## 3. Work packages

Each is independently shippable and leaves the fleet working at every
commit. Estimates are for one engineer.

### WP0 - Audit. DONE 2026-08-19

`TREE_LAYOUT_AGNOSTICISM.md`. Every literal with a line number.

### WP1 - The layout object and the manifest (dashboard + server), 2 days

1. `dashboard/site_store.py`: add the keys in §2 to `KEYS` with types
   (`projects_dir` str, `proxy_dir_name` str, `broll_archive_rel` str,
   `music_library_rel` str, `youtube_dir` str, `fixer_targets` json,
   `video_extensions_extra` csv, `layout_rev` int). Validators: one safe path
   segment for names; rel paths refuse `..`, leading `/`, drive letters
   (reuse `_validate_tree_part` from `api.py:1714`); `proxy_dir_name` must
   not equal `projects_dir` or any template folder leaf.
2. `provision.py`: a `Layout` dataclass built from settings + DB
   (`site_store.resolved_manifest`), replacing `TEMPLATE_FOLDERS`,
   `SHARED_ASSET_FOLDERS`, the three `Proxy` stignore lines and
   `classify_media`'s `"proxy"`. `build_stignore_lines(layout)`,
   `classify_media(rel_parts, ext, layout)`. `syncthing_data_prefix` and
   `syncthing_assets_prefix` become `layout.syncthing_projects_prefix`
   derived from the `/data` mount + `projects_dir` (D2), with the env vars
   kept as overrides.
3. `api.py api_site`: publish the new keys. `schema` stays 1 (additive by
   contract, `site.py:46-48`); bump `layout_rev` on every `PUT /admin/site`
   that changes a layout key (`setup_routes.py:200`).
4. `server/common.py`: `PROJECTS_DIRNAME` already reads `projects_dir`; add
   `PROXY_DIR_NAME`, `BROLL_ARCHIVE_REL`, `MUSIC_LIBRARY_REL` from
   `[tree]`, route `build_stignore_lines` and `DEFAULT_BROLL_ARCHIVE_ROOT`
   (`:202`) and the two binds (`install_dashboard_app.py:1179-1180`) through
   them; `setup_syncthing_folder.py:374` uses `PROJECTS_DIRNAME`.
5. `site.example.toml` and `CONFIG.md`: document the keys; **delete the
   sentence "everything else is fixed by the product"** (`site.example.toml:69`,
   `CONFIG.md:49`).
6. `server/tests/test_cross_component.py`: the byte-identical stignore
   pin becomes "all three builders, given the same layout, emit the same
   lines" - parametrised over two layouts (default and a renamed one).

Exit: a site with `proxy_dir_name = "Proxies"` and `projects_dir = "Clients"`
in site.toml deploys, the collector provisions projects under `Clients/`,
every `.stignore` the dashboard writes says `Proxies`, `/api/v1/site` says so.
Companions still on the old build keep working because nothing on the NAS
has been renamed - the keys only *describe* the tree.

### WP2 - Companion reads the layout, 3 days

1. New `companion/layout.py`: `TreeLayout` from `site.cached_site()` with
   the §2 defaults; `layout()` cached per process and invalidated by
   `refresh_site()`. Every literal in audit §3.2-§3.5, §4.1 and §6 goes
   through it:
   * `Projects`: `sequencer.PROJECTS_PREFIX` becomes `layout().projects_prefix`
     and the other 16 sites use it (`lane_guard.py:70`, `fixer.py:164,201`,
     `selection.py:485`, `app.py:3427`, `repath.py:198`, `sequencer.py:1519`,
     `rclone_lane.py:1750,1771,1781`, `manifest.py:76,133`,
     `proxy_scan.py:527`, `ytdl_executor.py:572,607,609`,
     `youtube_import.py:354`, `broll_fetch.py:78`, `ytdl_server.py:64`).
   * `Proxy`: `proxy_relink.PROXY_DIR_NAME` becomes a function of the
     layout; the four lane-A/B filter rules (`rclone_lane.py:399,448-451`),
     the stignore lines (`syncthing_admin.py:101`), `lane_guard.py:158`,
     `manifest._is_proxy_path`, `proxy_scan._is_pruned_dir`, `proxy_gen`'s
     `PROXY_DIR_NAMES` and `broll_ingest.py:2023,2163` read it.
   * `Assets/*`: `syncthing_admin.SHARED_ASSET_FOLDERS` from the manifest
     list; `luts.py:57` / `stills.py:47` pick the `luts` / `stills` role;
     `broll_server.py:239`, `broll_fetch.py:66,69`, `music_server.py:55`,
     `music_ingest.py:62` from `broll_archive_rel` / `music_library_rel`.
   * `Youtube`, `fixer_targets`, `video_extensions` (one list, the four
     copies collapse to `layout().video_exts`).
   * `drive_swap.py:43 P_DRIVE` from `canonical_prefix` (audit §6).
2. `layout_rev` in the report body (`reporter.py`); stignore writer refuses
   to write when its rev differs from the dashboard's (`syncthing_admin`),
   logs one line naming both revs, tray line "Layout update pending".
3. Report reply `commands.refresh_site` → `refresh_site()` + invalidate
   (reuse the `commands.halt` / `commands.upgrade` path,
   `MULTI_MACHINE_PLAN.md` §9).
4. Wizard (`onboarding/steps.py`): the six literal-`P` guards read the
   manifest prefix (`:280,285,1298,1452,2444,246`); `macos_uninstall.sh:90`
   reads `config.toml`.
5. Tests: the companion suite's filter/stignore tests parametrised over two
   layouts; a test that an EMPTY manifest (old dashboard, 404) yields exactly
   today's literals - this is the compatibility guarantee.

Exit: the same companion build serves a default site and a renamed site; the
difference is entirely in `~/.ccsync/state/site.json`.

### WP3 - The layout learner (dashboard), 4 days

A pure module + an API + a Setup task. The module is the deliverable; the UI
is thin.

**`dashboard/layout_learn.py`** - `learn(tree_root: Path, samples: list[str], *, limit_files=20000) -> Proposal`.
Pure function over a filesystem; tests use `tmp_path` trees. For each sample
(a rel path under the tree root) it records:

* `subfolders`: top-level and second-level directory names (excluding
  dot-dirs, OS junk, any dir matching the proxy heuristic below);
* `media`: video files by extension (built-in list + anything in the
  `video-looking` set: `.braw .r3d .crm .mxf .mov .mp4 .mkv .avi .mts .m2ts .insv .360`),
  capped by `limit_files`;
* `proxy_hits`: for every directory whose name matches
  `^(proxy|proxies|prx|optimi[sz]ed|transcodes?)$` (case-insensitive), the
  count of files whose stem matches a video sibling in the PARENT directory.

From all samples it proposes, each line with its evidence:

| Proposal | Rule | Evidence shown |
|---|---|---|
| `projects_dir` | The deepest common ancestor of the samples, rel to the tree root. If the samples' common ancestor is the tree root itself (samples in different top-level dirs), propose the top-level dir of the majority and list the others as "these would need a second root (not supported yet, WP6)" | "all 3 samples are under `Clients/`" |
| nesting hint | Depth of each sample under `projects_dir`, and the segment names (`2026/FF4/Nuclear` → "year / series / project") - for the create-project browser's default depth and the docs only | "samples are 3 levels deep: `<year>/<series>/<project>`" |
| `template_folders` | A subfolder present in **every** sample is ticked; in a majority is listed unticked with its count; two-level entries (`Audio/Music`) when the child appears in every sample that has the parent | "`Audio/Music` 3/3, `Interviewees` 2/3, `Youtube` 1/3" |
| `proxy_dir_name` | The name with the most `proxy_hits`; ticked if hits ≥ 50 % of the sample's videos. If NO proxy dir is found but videos exist: "no proxy folder found in N clips - if your proxies live beside the originals or in a cache folder, CC Sync cannot sync them as proxies (see TREE_LAYOUT_AGNOSTICISM.md §4.1)". If both `Proxy` and `Proxies` occur: list both, make the admin choose, and say the losing one will sync as originals | "`Proxy/`: 412 of 430 clips have one (same stem)" |
| `video_extensions_extra` | Extensions seen on files ≥ 1 MB that are not in the built-in list and look like video (set above, or `ffprobe` says so if available) | "`.insv` (14 files) is not in the built-in list" |
| `shared_assets` | Sibling directories of `projects_dir` at the tree root that are not a project (no marker, no videos at depth ≤ 2): each offered with a guessed role by leaf name (`lut|luts|cube` → `luts`; `stills|gallery|grades` → `stills`; `b-roll|broll|archive|stock` → `broll_archive`; `music|audio library|sfx` → `music`; else `other`) | "`LUTs/` (312 .cube files) → LUT library" |
| `youtube_dir` | A template folder whose name matches `youtube|yt|downloads` if the feature is on; else omitted | |
| `fixer_targets` | `audio` → the template folder matching `music|audio`; `image` → `stills|images|graphics`; `video` → `b-roll|broll|footage` + `/Editor Added/{editor}`; fallbacks to today's defaults and says so | |
| markers | Every sample; plus "N sibling folders at the same depth look like projects (≥ 2 template folders or ≥ 1 video)" listed with a tick each, default ON for the ones matching ≥ 3 template folders | the list |

It refuses to run on more than 8 samples or more than `limit_files` files and
says what it skipped (no silent caps). It never follows symlinks out of the
tree, and it opens no media file (extension + size only; `ffprobe` is
optional and only for the unknown-extension question).

**API** (admin-only, `setup_routes.py`):
`GET /api/v1/admin/layout/browse?rel=` (tree-root browser, the
`/partials/project-setup/browse` pattern but rooted at `/tree`),
`POST /api/v1/admin/layout/learn {samples: [rel,...]}` → Proposal JSON,
`POST /api/v1/admin/layout/apply {proposal-with-edits, dry_run: bool}` →
the plan (what would be written) or the result. `GET /api/v1/admin/layout`
returns the current layout + rev + per-machine rev table.

**UI**: a Setup task `layout` titled "Your project layout" between "Your
studio" and "Storage check" (`setup_engine.py` `register(Task(...))`): a
folder picker with [ ADD AS SAMPLE ], a [ LEARN ] button, then the proposal
as an editable form - every line shows its evidence and can be changed - and
[ PREVIEW ] (dry run, lists every marker and folder it would write) then
[ APPLY ]. Also reachable later from Settings → Site as "Re-learn layout".
Copy follows the no-em-dash rule.

### WP4 - Apply, publish, propagate, 2 days

1. `apply()`: in order - `snapshot_before()` (best-effort; `--require-snapshot`
   posture not needed for marker files), write site rows via `site_store`
   (bumps `layout_rev`), `mkdir` asset folders (same posture as
   `_run_storage`: `exist_ok`, no chown), write markers with fresh slugs
   (reuse `provision.write_marker` / `api.adopt_folder`'s path so the
   `projects` row appears eagerly and the 15-minute deactivation grace
   applies), record an `audit` row with the full proposal JSON.
2. The collector's next provision cycle creates Syncthing folders for the new
   markers with the new stignore; `_ensure_ignores` writes the new rev.
3. Every machine's next report gets `commands.refresh_site`; the Setup task
   shows "N of M machines on layout rev R" until they all are (the same
   chip model as the Packages page's out-of-date machines).
4. Migration for a layout change on a LIVE fleet (ours, or a customer
   re-learning): document the order - dashboard first (it only describes),
   then companions (`docs/RELEASE.md` note) - and the one rename that needs
   care, `proxy_dir_name`: the product never renames folders, so a site that
   renames `Proxy` → `Proxies` in the manifest without renaming on disk has
   every old `Proxy/` dir sync as originals. The Apply preview says this in
   red and offers a one-shot `server/rename_proxy_dirs.py --dry-run` (rename
   on the NAS only; lane B carries the new name down; local old dirs are
   outside every filter and are listed by the tray for manual deletion).

### WP5 - Clean-up and docs, 1 day

`CONFIG.md`, `INSTALL.md` (the Setup flow gains a step), `EDITOR_SETUP.md:209`
and `TENANCY.md:74-77` stop showing `Projects/<year>/<series>/<project>` as
the shape, `SPEC.md` line 13 names the layout object, `TREE_LAYOUT_AGNOSTICISM.md`
gets a STATUS block pointing here. Retire the `/projects` bind once nothing
reads it (D2).

### WP6 - Multiple project roots (design only here; build after WP1-5 are live)

The learner's "would need a second root" line becomes a feature. Shape:
`projects_dirs` (list) in the manifest; `projects.root` column; the
Syncthing folder path is `/data/<root>/<rel>`; `collector._project_rel`
strips whichever root matches; companion `selection.py` receives
`root + rel`; `local_root` stays one path per machine (roots are under it);
lane B's marker check accepts any root; the create-project browser asks
which root. Migration: existing rows get root = `projects_dir`. Two weeks.
Out of scope until a customer asks for it with a real tree.

---

## 4. What the customer experiences

First run of a new dashboard, Setup page, after "Your studio":

1. **Your project layout** - "Pick two or three of your existing projects so
   CC Sync can learn how you organise them." Folder browser over the NAS tree.
   [ ADD AS SAMPLE ] ×3. [ LEARN ].
2. A proposal: "Your projects live under `Clients/`. Each project has
   `Footage/`, `Audio/`, `Graphics/`, `Exports/` (3 of 3) and `Interviews/`
   (2 of 3). Proxies are in a `Proxies/` folder beside the footage (188 of
   190 clips). Your LUT library is `LUTs/` beside `Clients/`. 14 other folders
   under `Clients/` look like projects." Each line editable.
3. [ PREVIEW ] lists the 17 marker files and 1 asset folder it will write.
   [ APPLY ]. Done; editors' companions pick it up on their next report.

Re-running it later is a Settings action and shows the diff against the
current layout.

---

## 5. Tests and gates

* `layout_learn` unit tests over synthetic trees: the default shape; a
  `Clients/<client>/<project>` shape with `Proxies/`; a flat shape with no
  proxies (must refuse the proxy line and say why); mixed `Proxy`/`Proxies`;
  a tree with `.insv`; samples under two top-level dirs (WP6 message);
  symlink escape; the file cap.
* Cross-component: `server/tests/test_cross_component.py` parametrised over
  layouts (WP1.6); a companion test that an empty manifest reproduces every
  literal from the audit byte-for-byte (WP2.5).
* A real run: one scratch tree on the dev Synology laid out as
  `Clients/<client>/<project>` with `Proxies/`, learned, applied, one editor
  VM synced against it - the audit's §7 qualification case, proven.
* Scan tests for em dashes in the new templates/strings.

---

## 6. Out of scope, stated

* Proxies anywhere other than a sibling folder (audit item 8).
* A pluggable b-roll archive taxonomy (audit item 9); the archive's
  `Creators_Club/` and `Downloads/` top levels stay as they are, `rel_path`
  unchanged.
* More than one music share.
* Renaming anything on a customer's disk except by the explicit, dry-run-first
  `rename_proxy_dirs.py` in WP4.4.

---

## 7. Order and size

| WP | Days | Ships alone? | Unblocks |
|---|---|---|---|
| WP1 manifest + dashboard + server | 2 | yes | everything |
| WP2 companion | 3 | yes (needs WP1 deployed first) | renamed sites in the field |
| WP3 learner | 4 | yes (useful even before WP2: it writes site rows) | the customer's first hour |
| WP4 apply/propagate | 2 | with WP3 | fleet-wide layout changes without a restart |
| WP5 docs/cleanup | 1 | - | - |
| WP6 multiple roots | ~10 | later | two-root shops |

About twelve working days for WP1-5. The first customer-visible result is at
the end of WP3 (day 9); WP1 alone removes the `projects_dir` trap.
