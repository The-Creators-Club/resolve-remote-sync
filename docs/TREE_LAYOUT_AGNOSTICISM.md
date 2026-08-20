# How file-tree agnostic is CC Sync?

Written 2026-08-19, answering the owner's question:

> look into how file-tree agnostic this product is - how easily would it be
> for a customer to adapt the product to their own way of storing projects

Scope: every component (companion, dashboard, NAS scripts, ytdl service,
b-roll web + indexer, music web + indexer, installers, wizard). Method: three
parallel code sweeps for every hard-coded folder name, depth rule, proxy rule
and drive literal, each finding checked against the source. Line numbers are
HEAD at the time of writing. Related: `COMMERCIAL_READINESS.md` item 11 (the
2026-08-17 pass that made the tree root and drive letter site data),
`SPEC.md` (the lane model), `CONFIG.md` (the keys), `MULTI_MACHINE_PLAN.md`.
The plan that acts on this audit is `TREE_LAYOUT_PLAN.md` (2026-08-19).

---

## 1. The short answer

The product is **agnostic about where the tree is and what it is called, and
about how deep projects nest. It is NOT agnostic about the shape of a project
or the shape of the tree root.** Concretely, a customer can change by config
alone:

* the NAS pool/dataset/share, the tree's directory name, the SMB share and
  UNC, the editor drive letter (or a POSIX prefix) - `site.toml [tree]`,
  `[site] canonical_prefix`;
* the subfolders a new project is created with - `[tree] template_folders`;
* which fleet-wide asset libraries exist - `[tree] shared_assets` (one level
  under `Assets/` only, see §3);
* how deep projects nest under the projects dir - marker-identified, any
  depth up to 8, `Clients/<client>/<project>/` works today.

They **cannot** change by config, and in most cases cannot change by a small
patch:

* the name `Projects` as the first segment of every project path (the
  manifest key exists but only the NAS side honours it - §3.1);
* `Assets/Luts`, `Assets/Stills`, `Assets/B-roll Archive`, `Assets/Music` as
  siblings of `Projects/` under one root;
* **the `Proxy/` sibling-folder convention** - a video is a proxy if and only
  if some path segment is named `Proxy`. This is the definition of the three
  sync lanes, not a preference (§4);
* the `Youtube/` project subfolder the downloader writes into (§3.4);
* the fixer's drop targets `Audio/Music`, `B-roll/Stills`,
  `B-roll/Editor Added/<editor>` (§3.5);
* the b-roll archive's internal taxonomy and the music library root (§5);
* **more than one project root** - no representation anywhere (§4.3).

Rule of thumb for a sales conversation: a customer whose projects are
*folders of footage with a `Proxy/` folder beside the media* - which is the
convention DaVinci Resolve's own adjacent-proxy auto-link and the Blackmagic
Proxy Generator both use - can be onboarded with a `site.toml` plus a day or
two of contained renames. A customer whose proxies live elsewhere (Resolve's
"Generate Proxy Media" output in a cache folder, a mirror tree, a `_proxy`
suffix) or who keeps projects under two roots needs the media model
redesigned, which is weeks, and touches the companion, the dashboard and the
NAS scripts in lockstep.

---

## 2. What "the tree" means to each component

```
<pool_root>/<tree_name>/                 site.toml [tree]; editors see it as <canonical_prefix>
    <projects_dir>/                      site.toml [tree] projects_dir -- NAS side ONLY
        <any>/<depth>/<project>/         a project = a dir carrying .ccsync-project (JSON, slug)
            <template_folders...>        site.toml [tree] template_folders
            **/Proxy/<stem>.mov|.mp4     THE lane split: lane A = video outside Proxy/,
                                         lane B = Proxy/ only, lane C = everything else
            Youtube/<term>/              literal (ytdl service + companion)
            Audio/Music, B-roll/Stills,  literal (the popup fixer's targets)
            B-roll/Editor Added/<name>
    Assets/                              literal, sibling of the projects dir
        Luts/, Stills/                   defaults of [tree] shared_assets (Syncthing fleet-wide)
        B-roll Archive/                  literal; the b-roll mount, the proxies/sprites/posters/sheets
        Music/                           literal; the music mount
    .ccsync-trash/                       literal; lane B's backup dir at the tree root
```

Every component reads `local_root` / `canonical_prefix` (companion config),
`DASH_PROJECTS_DIR` / `DASH_SYNCTHING_DATA_PREFIX` (dashboard), or
`[tree] pool_root` + `tree_name` (NAS scripts) for the root. Below the root the
names above are literals in code.

---

## 3. Findings, by how hard the change is

### 3.1 Config-only today (works, no code)

| What a customer might want | How | Evidence |
|---|---|---|
| A different tree root, share, UNC, drive letter | `[tree] pool_root`, `tree_name`, `share_name`, `smb_unc`; `[site] canonical_prefix` (drive letter OR POSIX path) | `server/common.py:193-198`, `site_store.py:127-140` validator, both installers since item 11 |
| Projects nested by client / year / series / anything, 1 to 8 levels deep | Markers. A dir is a project because it carries `.ccsync-project`; discovery prunes at markers; containers nest freely, projects never nest | `dashboard/provision.py:269,357-388`, `companion/fixer.py:149-183`, `rclone_lane.py:1719-1771` (longest-known-rel-prefix) |
| Different per-project scaffolding, including no `Youtube/` or `Interviewees/` | `[tree] template_folders` reaches `setup_tree.py`, the dashboard create flow and `/api/v1/site` from one place | `server/common.py:410`, `dashboard/provision.py:72`, `api.py:1994` |
| Different fleet-wide asset libraries (LUTs, stills, fonts...) | `[tree] shared_assets`, Syncthing folder id = slugified rel | `server/common.py:456-458`, `provision.py:181-192` |
| Editor home directories elsewhere (DSM) | `[tree] homes_parent` | `server/common.py:209-210` |

Caveats on the "works": dropping `Youtube` from `template_folders` breaks the
ytdl feature (it assumes the folder exists, `ytdl/web/ytdlweb/routes_api.py:535`)
but only if `[features] youtube_download` is on. `shared_assets` entries must
be exactly `Assets/<one-segment>`: `collector.py:408` splits on the first `/`
and treats the remainder as the leaf under the assets prefix, so
`Library/Luts` silently mounts `Assets/Luts`.

### 3.2 Looks configurable, is not: `projects_dir`

`site.toml [tree] projects_dir` is read in exactly one place,
`server/common.py:197`, and reaches exactly one consumer, the compose bind
source (`install_dashboard_app.py:1178`). It is **not** in the keys the
dashboard publishes in `/api/v1/site` (`site_store.py` `KEYS`), so no
companion ever hears about it, and:

* the dashboard's own `syncthing_data_prefix` defaults to the literal
  `/data/Projects` (`settings.py:363`) and nothing in `server/` ever writes
  `DASH_SYNCTHING_DATA_PREFIX`; `setup_syncthing_folder.py:374` re-hardcodes
  `Projects` despite importing `DEFAULT_PROJECTS_ROOT`;
* the companion hard-codes `"Projects"` in 17 sites across 12 modules
  (`sync/sequencer.py:57 PROJECTS_PREFIX`, `lane_guard.py:70`, `fixer.py:164`,
  `selection.py:485`, `app.py:3427`, `sync/repath.py:198`,
  `sequencer.py:1519`, `rclone_lane.py:1750,1771,1781`, `manifest.py:76,133`,
  `proxy_scan.py:527`, `ytdl_executor.py:572,607,609`, `youtube_import.py:354`,
  `broll_fetch.py:78`). `PROJECTS_PREFIX` already exists as a constant and is
  used by three of them;
* `rclone_lane.py:1750` gates the express/watchdog lane on
  `parts[0].lower() == "projects"` in both the marker regime and the legacy
  regime - a file under any other first segment waits for the periodic pass;
* `lane_guard.py:70 DEFAULT_REMOTE_MARKER_DIRS = ("Projects",)`: lane B refuses
  to sync a NAS that has no `Projects/` at the root;
* eight dashboard template strings and `ytdl/web/static/app.js:1867`
  (`'Projects\\' + ...`, with the hint `(P: on Windows)`) spell it out.

**Net effect:** a site that sets `projects_dir = "Clients"` today gets a NAS
mount at `<tree>/Clients`, a collector that strips a `/data/Projects` prefix
that never matches, a lane B that refuses the whole tree, and a fleet of
companions joining `local_root/Projects/...`. It is a silent breakage, not a
refusal. This is the single most misleading key in `site.example.toml` and
should either be plumbed end to end or removed from the example until it is.

Contained fix, roughly a day: publish the key in the manifest, have
`install_dashboard_app.site_env` emit `DASH_SYNCTHING_DATA_PREFIX` /
`_ASSETS_PREFIX`, make the companion read it into the one constant, and make
the two gates above use it.

### 3.3 Code change, contained: the `Assets/*` siblings

`Assets/Luts` and `Assets/Stills` are overridable via `shared_assets` on the
server and dashboard, but the companion ignores the manifest's copy
(`sync/syncthing_admin.py:114-121` is a hard-coded two-entry list;
`luts.py:57`, `stills.py:47`, `stills.py:58` join the literal tuple onto
`canonical_prefix`). The manifest keys `template_folders` and
`shared_asset_folders` are fetched, validated and cached by
`companion/site.py:102,144` **and read by no companion module**. They are dead
wire on the client.

`Assets/B-roll Archive` and `Assets/Music` are literals with no key anywhere:
`server/common.py:202`, `install_dashboard_app.py:422,1179-1180,3978-3981`
(bind sources; archive substructure `proxies/sprites/posters/sheets`),
`companion/broll_server.py:239`, `broll_fetch.py:66,69,78`,
`music_server.py:55`, `music_ingest.py:62`. The companion's loopback servers
do have a per-machine escape hatch - `~/.broll-companion.json` `mounts` /
`music_mounts` / `ytdl_mounts` - but that is a per-editor file, not site data.

### 3.4 Code change, contained: `Youtube/`

`Youtube` is a literal in the ytdl service (`ytdlweb/db.py:1160 YOUTUBE_DIR`,
`worker.py:581,1023`, `config.py:32-34`, `app.js:1867`) and the companion
(`youtube_import.py:71 YOUTUBE_DIR_NAME`, `ytdl_executor.py:579`). The walk is
depth-2 by contract (`Youtube/` + `Youtube/<term>/`, `worker.py:1005-1023`,
`youtube_import.py:548-560`). `_term_dir_of` parses `parts[0] == 'Youtube'`
from stored `rel_path`s, so a rename touches ledger data, not just code. Six
or so sites, one day, but only matters where the feature is on.

### 3.5 Code change, contained: the popup fixer's drop targets

The out-of-tree-media popup copies audio into `Audio/Music`, images into
`B-roll/Stills`, video into `B-roll/Editor Added/<editor_name>`
(`fixer.py:70-86,207`); only the leaf editor name is configurable. A customer
whose template has no `Audio/` or `B-roll/` gets folders created that are not
in their template. Wants a config list keyed by media kind; two functions.

### 3.6 Heuristics tuned to `year/series/project`

Not breakages, degradations: the Resolve-project-name to tree-label matcher
(`dashboard/db.py:2556-2617`, `companion/fixer.py:104-112`) drops all-digit
tokens of length 4 or less ("a name containing 2026 is not evidence") and
scores token overlap. On `Clients/<client>/<project>` the client name is a
token on every one of that client's projects, so confident matches get rarer
and `resolve_project_unmapped` prompts get commoner. Tunable
(`MIN_CONFIDENT_TOKENS`), not structural. `server/common.py:590-606
project_path(root, year, series, project)` is a hard 3-level helper, but
`project_path_rel` and `setup_tree.py --project-rel-path` are the
arbitrary-depth path and the dashboard uses those.

---

## 4. Deep structural assumptions (a redesign, not a patch)

### 4.1 `Proxy/` is the definition of the lane split

A video file is a proxy **iff** any path segment is named `Proxy`
(case-insensitive). That one predicate is:

* lane A's filter: `- **/Proxy/**`, `- /Proxy/**`, then `+ *<ext>` for every
  video extension (`rclone_lane.py:399-400`) - "video, except under Proxy";
* lane B's filter: `+ /Proxy/ + /Proxy/** + **/Proxy/ + **/Proxy/**` then
  `- **` (`rclone_lane.py:448-451`) - "Proxy, and nothing else", and this is
  `rclone sync`, so a non-proxy it finds under `Proxy/` is deletable;
* lane C's `.stignore`: `(?i)Proxy`, `(?i)**/Proxy`, `(?i)**/Proxy/**` plus the
  video extensions, **byte-identical in three components**
  (`server/common.py:527-529`, `dashboard/provision.py:151-153`,
  `companion/sync/syncthing_admin.py:101`) and pinned by
  `server/tests/test_cross_component.py`;
* the NAS inventory: `provision.classify_media` (`provision.py:76-83`) is the
  only definition of proxy vs original, and the `media`/`editor_media` schema
  is binary on `kind` (`db.py:39,79,92`); the transfers view's "what is
  missing" is `kind='proxy'` down / `kind='original'` up (`db.py:3147-3162`);
  fleet health colouring is proxy counts (`health.py:36-58`);
* the companion's presence manifest (`manifest.py _is_proxy_path`), the lane B
  circuit-breaker denominator (`lane_guard.py:158 "proxy" not in parts`), the
  missing-proxy scanner's walk prune (`proxy_scan.py:279-286`), the relinker
  (`proxy_relink.py:126-135 expected_proxy_paths`: `dirname/Proxy/stem.mov|mp4`,
  no suffix scheme, no mirror tree), `resolve_bridge._attach_adjacent_proxy`
  (`:1647-1690`), the generator's output path and its "never encode a proxy"
  refusal (`proxy_gen.py:215,252-275`), and the b-roll ingest's archive
  proxies (`broll_ingest.py:2023,2163`).

Proxies beside originals, or in a mirror tree, or with a suffix, are not a
rename: lanes A and B collapse onto the same file set (lane A uploads the
proxy as an original; lane B sweeps the original as a deletable non-proxy;
the generator starts proxying proxies; the dashboard counts every proxy as a
missing original and colours the fleet amber). Supporting a second
discriminator means a new predicate threaded through every site above, in all
three components at once, with the cross-component test updated. Estimate:
two to three weeks, plus a migration story for existing trees.

Two external constraints make the current convention less arbitrary than it
looks: Resolve's adjacent-`Proxy/` auto-link is Resolve's own rule (same stem,
same timecode, sibling `Proxy/` folder), and the Blackmagic Proxy Generator
only writes and recognises `Proxy/<stem>.mov` (`bpg.py:48-49`), which is the
only way a BRAW/R3D/CRM clip gets a proxy at all. So the convention is the
one Blackmagic's tooling produces. What it does NOT cover is the other
Blackmagic convention: Resolve's in-app *Generate Proxy Media* writes to the
project's "proxy generation location", a cache folder by default, and those
projects arrive with absolute proxy paths `proxy_relink` repoints but lane B
never carries. That case is common among editors who never used BPG and is
worth naming in the sales qualification.

Renaming `Proxy` to, say, `Proxies` is the easy half: `proxy_relink.PROXY_DIR_NAME`
is already the constant `proxy_scan` and `proxy_gen` import, and
`proxy_gen.py:215` already tolerates `proxies` on read. The six string-literal
filter/stignore rules and `lane_guard.py:158` would need to become f-strings
and the three stignore copies changed together. A day, but it is a
fleet-wide flag day because the NAS and every companion must agree.

### 4.2 `Assets/*` beside the projects dir, under one root

`setup_engine.py:484` derives `tree_root = Path(projects_dir).parent`;
`collector.py:407-410` derives the assets prefix as the data prefix's parent
plus `Assets`; both `settings.py` prefix defaults and all four installer bind
sources assume one root holding `Projects` and `Assets` as siblings; lane B's
`--backup-dir` is anchored at `local_root/.ccsync-trash`
(`rclone_lane.py:68`). A customer whose LUT library lives on a different share
than their projects has no way to express it.

### 4.3 One projects root

`projects_dir` is a single string in dashboard `Settings`, a single bind
mount, a single scan root, a single Syncthing path prefix
(`provision.build_folder_config`, `collector._project_rel`), and a single
`local_root` on every companion. Two project roots (say, `Active/` and
`Archive/`, or two shares) have no representation anywhere. Schema, plumbing
and UI; not a config change.

### 4.4 The manifest's layout keys are fetched and ignored

Item 11's 2026-08-17 work published `template_folders` and
`shared_asset_folders` in `/api/v1/site` and taught `companion/site.py` to
accept them. No consumer was written. Making layout server-driven is not "wire
up the manifest": it is writing the consumers, and deciding what a companion
does when the manifest is 404 or stale (today `site.py` degrades to `[]`,
which for a folder list would mean "no tree").

---

## 5. B-roll archive, music library, installers, wizard

### 5.1 The `<share>/<rel_path>` pair is clean; everything above it is not

Both web apps and both companion loopback servers resolve a clip as
`<share>` + `<rel_path>` through one validated join
(`musicweb/config.py:309-391 SHARE_ROOTS/safe_join/resolve_path`, mirrored in
`broll_server.py`); `rel_path` is produced as `fpath.relative_to(root)`
(`broll/indexer/broll_index/scanner.py:113`) with no shape assumed. That
abstraction is genuinely layout-agnostic. The archive *built on top of it* is
not:

* **Two fixed taxonomies, not pluggable.** `build_archive.dest_dir()`
  (`broll/indexer/build_archive.py:162-180`) hard-codes own footage as
  `Creators_Club/<share>/<shoot dirs>/<name>` and downloads as
  `Downloads/<subject slug>`. `CREATORS = "Creators_Club"` and
  `DOWNLOADS = "Downloads"` (`:53-54`) have no override in the indexer;
  `broll/web/app/config.py:174-195 BROLL_ARCHIVE_CREATORS_DIR` renames the
  top level for NEW ingest writes only, and its own comment says the indexer
  literal cannot move because published files sit under it. The per-share
  `archive_name` (`broll_index/config.py:102`) renames the second level.
  A customer wanting `Clients/<client>/<year>/` inside the archive has no
  seam; `_shoot_tree` (`routes_api.py:166-227`, `SHOOT_TREE_DEPTH = 3` at
  `:163`) and `build_shoot_clause` (`search.py:388-421`) are written against
  the two shapes.
* **`Proxy/` again, five more times.** `build_archive.py:100 PROXY_DIR`,
  `:175-176` (folds `proxy` out of every own-footage path), `:183-214`
  (`<folder>/Proxy/<name>.mp4` beside the original), `ingest_batches.py:85`
  (third copy of the constant), `routes_api.py:198` and `:44-60`
  (`_insert_target`: if `preview.parent.name == "Proxy"` look for the
  original one level up, else insert the preview), `search.py:400-416`
  (re-inserts `Proxy` at every position to undo the folding). The indexer's
  scanner classifies proxies by a folder-name regex
  (`scanner.py:132-135 PROXY_DIR_RE`: `proxy|proxies|optimized|optimised|
  transcode|...`) and `origins.py:12-16` finds the camera original "one
  directory up with a different extension". No `Proxy/` folder means every
  file is `discovered` and both halves of every pair get indexed.
* **Archive root == the web app's `DATA_ROOT`**, with `posters/` and
  `sprites/` at its top level (`build_archive.py:20-25,109-111`,
  `routes_media.py:50-58`, `install_dashboard_app.py:3978-3981`). Moving the
  archive means moving those with it; nothing splits them.
* The Resolve bin is `("B-Roll", "Archive")` (`resolve_bridge.py:1391`), the
  archive share slug is `"broll"` (`routes_api.py:21`), and the work order
  handed to companions says `"archive_remote_rel": "Assets/B-roll Archive"`
  (`ingest_batches.py:688`) - all literals.

Config-driven here: which shares are own footage (`BROLL_CREATORS_SHARES`,
plus `share_roots.source='proxies'`), the UI collection slug/label
(`BROLL_DEFAULT_COLLECTION`), the subject taxonomy content
(`taxonomy.rules.yaml`, though `routes_api.py:305` assumes `group/leaf`
slugs), and the roots per host (`BROLL_DATA_ROOT`, `BROLL_DB_PATH`).

### 5.2 Music is the cleanest layer

The tagger imposes no folder taxonomy (`index_music.py:60` flat walk; the
only folder it knows is `EXCLUDE_DIRS = {'_stems'}`,
`music_index/config.py:62`). Its roots are env (`MUSIC_LIBRARY_ROOT`,
`MUSIC_DB_PATH`; the old `W:\Creators_Club\Assets\Music` probe is gone,
`musicweb/config.py:32-36`). What is literal: the leaf `Assets/Music`
(`musicweb/config.py:38`, `music_server.py:55`, `music_ingest.py:62`,
`musicweb/ingest_batches.py:558`), `CANONICAL_PREFIX` defaulting to `P:\`
(`config.py:39`, env `CCSYNC_CANONICAL_PREFIX`), and **exactly one share**
(`config.py:320 SHARE_ROOTS = {SHARE: MUSIC_ROOT}`): two music libraries
have no config path.

### 5.3 Installers and wizard create nothing tree-shaped

`windows_bootstrap.ps1:1176 Ensure-Dir $CCRoot` and
`macos_bootstrap.sh:411 mkdir -p "$path"` are the only tree directories
either bootstrap creates; `Projects/`, `Assets/`, template folders and
`Proxy/` all arrive by sync or are created server-side by `setup_tree.py`.
`local_root` defaults derive from the manifest's `tree_name`
(`steps.py:220-231`, `windows_bootstrap.ps1:808`, `macos_bootstrap.sh:348`);
`remote_root` is seeded from the manifest with a deliberately blank default
(`steps.py:258,2239-2241`); the drive letter, logon task, loopback share name
and "is this drive ours?" guard in the Windows bootstrap all derive from
`canonical_prefix` (`:777-789,1200-1304`). The bootstrap refuses a
non-drive-letter prefix on Windows (`:780-786`) - correct, since Windows
editors must get a letter. Resolve prefs written: the LUT location and
gallery root (via the companion, literal `Assets/Luts`/`Assets/Stills` joined
onto `canonical_prefix`) and, on macOS, the Mapped Mount
(`macos_bootstrap.sh:1405-1453`) - no media-storage paths.

Where the wizard still says `P`, see §6.

---

## 6. Drive-letter / prefix literals that survived item 11

* `companion/drive_swap.py:43 P_DRIVE = "P:"`, used at `:314` (`net use P:
  /delete`, `subst P: /D`), `:447`, `:459`, and in five user-visible strings.
  **It never reads `canonical_prefix`**: on a `Q:\` site the grade swap
  unmaps whatever is on `P:` and maps the NAS there. Bug, not design; one
  module.
* The wizard's own `P:` guard, unlike the bootstrap's, is not derived from
  the manifest: `onboarding/steps.py:280 SUBST_TASK_NAME = "CCSync-SubstP"`,
  `:285 "CCSyncSubstP"`, `:1452 OUR_LOOPBACK_SHARE = r"\\localhost\CCSync_P"`,
  `:1298 if role != "base" and drive == "P"`, `:2444 startswith("P:")`,
  `:246 DEFAULT_BASE_LOCAL_ROOT = "P:\\"`. The bootstrap names its task and
  share `CCSync-Subst$DriveLetter` / `CCSync_$DriveLetter`
  (`windows_bootstrap.ps1:1200-1213`), so on a `Q:` site the install works
  and the wizard then fails to recognise its own loopback share. Also
  `installer/macos_uninstall.sh:90 CANONICAL_PREFIX='P:\'` (the Windows
  uninstaller reads `config.toml`; the Mac one does not).
* `app.py:1798,1970,2905`: "Your P: drive (Windows) or Mapped Mount ..." in
  popup/tray copy, literal.
* `music/web/musicweb/config.py:39` defaults `CCSYNC_CANONICAL_PREFIX` to
  `P:\`; `broll/indexer/fix_10bit_proxies.py:41` and
  `fix_proxy_timecode.py:38` default to `P:\Assets\B-roll Archive`.
* `ytdl/web/static/app.js:1868`: "(P: on Windows)".
* `dashboard/nas/truenas.py:44 HOME_PARENT = "/mnt/tank/TheCreatorsPool/homes"`:
  a real tenant literal, labelled legacy fallback behind `homes_parent`.
* `installer/build_editor_package.ps1:102 $Destination = "P:\Assets\Software\CC_Sync"`.
* Four independent copies of the video-extension list in the companion
  (`rclone_lane.py:49`, `syncthing_admin.py:45`, `youtube_import.py:90`,
  `broll_server.py:194`), the canonical one being `dashboard/provision.py:27-31`,
  published read-only in the manifest and never read by the companion.

`canon.py` and `paths.py` - the `P:\` ↔ `local_root` translation that every
Resolve write goes through - are genuinely generic (`canon.py:39-41`) and
already handle a Windows prefix on a Mac and a POSIX prefix; nothing there
needs to change for any layout.

---

## 7. What to tell a prospect, and what to build

**Qualification questions** (the answers decide whether it is a config file
or a project):

1. Is every project a folder, with the footage inside it? (Yes: fine. "Our
   footage is in a shared pool and projects reference it": out of scope.)
2. Where do your proxies live? Adjacent `Proxy/` folder (BPG, or Resolve's
   auto-link convention): fine. Anywhere else: redesign, §4.1.
3. Is there one projects root, and are your shared libraries beside it on
   the same share? Two roots or split shares: §4.2/4.3.
4. Do you use Resolve's own "Generate Proxy Media"? If so, those proxies are
   not synced today; the missing-proxy generator would make a second set.

**Recommended order of work**, cheapest first, each independently shippable:

| # | Work | Size | Unlocks |
|---|---|---|---|
| 1 | Plumb `projects_dir` end to end or delete it from `site.example.toml` (§3.2) | 1 day | stops a silent-breakage key being offered to customers |
| 2 | `drive_swap.py` and the wizard's six `P` guards read `canonical_prefix`; `macos_uninstall.sh` reads `config.toml` (§6) | half a day | non-`P:` sites on Windows |
| 3 | Companion consumes `shared_asset_folders` from the manifest; `Assets/B-roll Archive` and `Assets/Music` become `[tree]` keys served in the manifest (§3.3) | 1-2 days | renamed/extra libraries |
| 4 | Fixer drop targets from config (§3.5) | half a day | templates without `Audio/`/`B-roll/` |
| 5 | `Youtube` dir from config, ledger migration (§3.4) | 1 day | only with the feature on |
| 6 | A rename of `Proxy` (not a relocation) as one constant per component + the three stignore copies, behind a manifest key with a fleet-wide flag day (§4.1 last para) | 1-2 days | `Proxies/` shops |
| 7 | Companion `luts.py`/`stills.py` read the manifest's `shared_asset_folders`; `B-Roll/Archive` bin, `SHOOT_TREE_DEPTH`, `Creators_Club`/`Downloads` archive top levels become keys (§3.3, §5.1) | 1-2 days | renamed libraries actually reach Resolve; new-install archive naming |
| 8 | A second proxy discriminator (mirror tree / suffix / sidecar) through lanes, inventory, scanner, `build_archive`, ingest (§4.1, §5.1) | 2-3 weeks + migration | proxies-elsewhere shops |
| 9 | Pluggable archive taxonomy (own footage / downloads shapes in `build_archive.dest_dir`, `_shoot_tree`, `build_shoot_clause`) | 1-2 weeks | customers who want their own archive shape |
| 10 | Multiple project roots; more than one music share | schema + plumbing, weeks | two-root shops |

Items 1-7 are the "day or two of contained renames" in §1 (about a week in
total if all are done). Items 8-10 are the product decision: the current
lane model is built on Blackmagic's own convention and does one thing very
safely; widening it trades that simplicity for market. Note that a customer
who accepts "projects are folders with a `Proxy/` folder beside the media"
needs none of 8-10, and the archive taxonomy only matters if they adopt the
b-roll platform - the sync product alone is items 1-6.
