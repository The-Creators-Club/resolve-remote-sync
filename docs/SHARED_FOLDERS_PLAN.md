# Shared folders between projects - one folder on the NAS, synced into two projects, no second copy

Written 2026-08-23 against HEAD `a30fb6e`. The owner's ask, from the
footage-sorter side:

> what would be the best way of making the same files appear in two places
> at once ... the main reason is syncing, ccsync will only sync files which
> are inside the specified project directory

The case: `Projects/2026/FF5/Civil Defence/Interviewees/朱福銘 Aha Chu` is an
interview shot for Civil Defence and reused in the Elections episode. Today
the only way an editor ticked on Elections receives it is a second copy of
the folder under `Projects/2026/FF5/Elections/...`, which doubles the bytes
on the pool and drifts the moment anyone renames or deletes one side. Every
filesystem trick is closed: Windows cannot make hard links or junctions across
SMB, and ccsync never follows symlinks (no `--links` on any rclone lane,
Syncthing at its default, every walk is `os.walk(followlinks=False)`).

Deliverable: a project can **declare that it borrows a folder from another
project**. Any editor with either project ticked receives the folder, at its
one true path, through the same three lanes, with no relinking in Resolve.

Related: `TREE_LAYOUT_PLAN.md` (WP style; D3 "markers stay the definition of
a project"; its WP2 `layout().projects_prefix` is what every `Projects/`
literal below will eventually read), `TREE_LAYOUT_AGNOSTICISM.md` §4.1 (the
lane split), `SYNC_SAFETY.md` (breaker, trash, remove-gate),
`delete-protection-ignoredelete.md`, `SPEC.md` "Shared asset libraries" (the
closest existing shape: a Syncthing folder that is not a project and not in
the rotation).

---

## STATUS

* **BUILT 2026-08-24** (WP1, WP2, WP3, WP5; owner approved D1-D7 by asking
  for the build). WP4 (footage-sorter writes the declaration) tracked
  separately in that repo. In repo, tests green, **UNSHIPPED** - deploy the
  dashboard before the companions, as ever.
* WP0 (the audit below) is done; every claim carries a file:line against
  `a30fb6e`.
* **The D4 spike ran 2026-08-24** against Syncthing v2.1.2 (the fleet
  installs v2.1.3), two live instances, one shared folder:
  - (a) CONFIRMED: negations ahead of a trailing `**` un-ignore the subtree,
    and the STIGNORE_LINES prefix still keeps video/Proxy out inside it;
  - (b) REFUTED, in the good direction: **no ancestor `!` lines are needed**
    - Syncthing descends into `**`-ignored directories on its own when a
    negation could match below. Worse, the drafted `!/Interviewees` line is
    WRONG: a pattern matching a directory matches everything within it, so
    it un-ignored the ancestor's every sibling (measured:
    `Interviewees/Other/skip.txt` synced). The shipped recipe is
    `STIGNORE_LINES + ["!/<sub>", "!/<sub>/**", "**"]`
    (`syncthing_admin.restricted_ignore_lines`);
  - (c) CONFIRMED: completion reads 100% on both sides once the subset is
    in (`needItems` 0).
* Two deliberate deviations from the draft below, both documented at the
  code: the selection response MARKS an include `covered: true` when its
  lender is selected on the machine instead of omitting it (the tray's
  removal gate needs the relationship; the companion still never runs a
  covered include), and `_run_links` clears the rows of a vanished borrower
  only when its projects row is ALSO inactive (a transiently unreadable
  marker must not unshare a lender's folder fleet-wide - the B16 shape).
* Still open: WP4 (footage-sorter), WP6 items, and KNOWN_BUGS CR-71
  (borrowed files not counted in the borrower's MEDIA column).

---

## 0. What the code does today (verified)

| Fact | Where |
|---|---|
| A project is a dir carrying `.ccsync-project` = `{"slug","created_by","created_at"}`; the slug is the Syncthing folder id and the key of every DB row. Marker readers look only at `slug` and tolerate extra keys | `dashboard/src/ccsync_dashboard/provision.py:269-298,339-354`; `server/common.py:625-646,690-712`; readers: `companion/src/ccsync_companion/sync/rclone_lane.py:1782-1801`, `fixer.py:149-183`, `provision.read_marker` |
| Selection response is `{editor, machine, machines, generated_at, project_roots, selection:[{slug,label,rel_path,position,active}]}`; `rel_path` is under `Projects/`. The companion requires only a `selection` list, so additive keys are safe | `dashboard/src/ccsync_dashboard/api.py:1477-1499,1600-1614`; `companion/src/ccsync_companion/selection.py:167-240` |
| Per project the sequencer builds `subpath = "Projects/" + rel_path` and runs repath, structure clone, lanes A and B (concurrently), orphan scan, then the lane C turn | `sync/sequencer.py:60,1192-1234,1236-1283` |
| Lane A = `rclone copy local -> NAS`, filter "video outside Proxy/"; lane B = `rclone sync NAS -> local`, filter "Proxy/ only", `--backup-dir local_root/.ccsync-trash/<ts>/<subpath>`, `--max-delete`, breaker scoped per subpath | `rclone_lane.py:379-453,1329-1377,1530-1593,2179-2197,2625-2655` |
| Lane A's express/watchdog attributes a path to a project by longest known rel from `sequencer.known_rels()` and promotes via `notify_change` | `rclone_lane.py:1804-1867,3462-3500`; `sequencer.py:496-500,554-588,859-890` |
| Lane C: one Syncthing folder per project, id = slug, NAS path `<data_prefix>/<rel>`, shared with exactly the devices of machines that ticked it; `.stignore` = video exts + Proxy + partials, repaired every cycle; the companion accepts the offer at `local_root/Projects/<rel>`, asserts the ignores (missing-lines check, extra lines tolerated) and unpauses only after they are confirmed | `collector.py:828-1066,676-709`; `provision.py:147-154,391-423`; `sequencer.py:1448-1550,1552-1632,1634-1671,1696-1733`; `syncthing_admin.py:91-102,168-188,424-487` |
| The collector refuses to provision a Syncthing folder inside another project: "projects cannot nest" | `collector.py:646-674`; `api.py:1847-1870` |
| Shared asset folders are the existing "folder that is not a project": hard-coded list, reconciled once per pass before the selection check, never in the rotation, paused by a halt, fail-closed on ignores | `sync/shared_folders.py`; `sequencer.py:513-536,605` |
| Symlinks are never followed | `provision.py:357-388`, `fixer.py:168`, `collector.py:1141-1169` |
| `paths.classify_path` returns OK for any canonical path under `local_root`, MISSING for a canonical path not yet downloaded; only OUT_OF_TREE feeds the popup | `companion/src/ccsync_companion/paths.py:282-290,311-329,354-362`; `app.py:2313,3065` |
| "Remove from this machine" unticks, removes the local folder config, then `rmtree(local_root/Projects/<rel>)`, gated by `removal_blockers` | `app.py:3406-3479,3538-3643` |
| Repath moves `local_root/Projects/<old>` to `<new>` for selected items only | `sync/repath.py:174-245` |
| footage-sorter already detects "this clip is byte-identical at a final path in another folder" (`state: 'elsewhere'`) and today offers a second copy. Move plans are `{destRoot:"P:\\Projects", folders:[...], entries:[{src,dst,...}]}` | `E:\Projects\footage-sorter\lib\ingest\plan.js:205-222`; `data/moveplan-one-clip.json` |

---

## 1. Decisions (challenge these)

**D1. The link is declared in the BORROWING project's `.ccsync-project`,
key `includes`.**

| Option | For | Against |
|---|---|---|
| Marker of the borrower (recommended) | Travels with the project (survives a move, a DB rebuild, a new dashboard); one file, written by whoever creates the relationship (dashboard, footage-sorter, a human); same discovery path as the slug (provision already reads every marker every 5 min); additive JSON key every existing reader ignores | A plain file on a share any editor can write, so the server validates it and never trusts it (the slug's posture today, `provision.py:271-277`) |
| Dashboard DB only | Admin UI is natural; validation at write time | Lost on DB rebuild; invisible on the NAS; footage-sorter would need a dashboard API and auth to write it; contradicts TREE_LAYOUT_PLAN D3 (the tree is the truth, the DB mirrors it) |
| A file in the LENDING project | The lender "knows" who borrows | The intent lives with the borrower (it is the borrower that is incomplete without the folder); a deleted lender takes the declaration with it; two borrowers of one dir means two writers of one file |

The dashboard DB gets a **mirror table** (`project_links`) so the selection
API and the UI never parse markers at request time. Marker = truth, DB =
resolved cache, exactly as `projects.label` mirrors the folder today.

**D2. Borrowed content lands at its ORIGINAL path**
`local_root/Projects/<lender-rel>/<sub>/...`. No symlinks, no second local
copy, no relink. The canon `P:\Projects\2026\FF5\Civil Defence\Interviewees\朱福銘 Aha Chu\clip.mp4`
stays true on every machine, which is the whole point. Consequence: an
editor's tree may hold a **partial lending project** (the lender's dir with
only the borrowed subtree populated, and no `.ccsync-project` in it because
lane C is restricted). §3.3 lists every reader of the tree and what it does
with that.

**D3. Lanes A and B treat a borrowed dir as an extra subpath run** inside the
borrowing project's turn: `Projects/<lender-rel>/<sub>`. Same filters, breaker
scope, trash layout and budget. Nothing in `rclone_lane.py` changes; the
sequencer issues more `run_once(subpath)` calls.

**D4. Lane C reuses the LENDER's Syncthing folder, restricted by `.stignore`
on the borrowing device.** A second Syncthing folder over a subdirectory is
exactly what `collector._creatable` refuses (`collector.py:646-674`), and its
`.stfolder` would sync into every other copy of the lender. So the dashboard
shares the lender's folder (id = lender slug) with the borrowing device; the
companion accepts it at the true path with ignores =
`STIGNORE_LINES + ["!/<sub>", "!/<sub>/**", "**"]` (plus a `!` line per
ancestor of `<sub>`), pulling only the borrowed subtree. `.stignore` is
device-local and never synced, so the NAS and other devices are untouched. If
the editor later ticks the lender, the restriction is lifted and the folder
becomes a normal selected project. **Spike in WP3** confirms: (a) negations
ahead of a trailing `**` un-ignore the subtree, (b) ancestor `!` lines are
needed for Syncthing to descend, (c) completion reads 100% once the subset is
in (ignored items are excluded from `needItems`).

**D5. The server resolves links; the companion stays dumb.**
`GET /api/v1/selection/{editor}` gains `includes` per item, already
validated, already deduped against the rest of this machine's plan, `ok`
rows only. The companion never reads `includes` from a marker and never walks
the NAS to find lenders. Same division as `project_roots` today.

**D6. Uploads INTO a borrowed dir are allowed** (lane A runs up from the
borrower's machine for the borrowed subpath). The common case is one editor
who owns both projects; refusing would silently strand a card ingest. Lane A
is copy-only with `--ignore-existing`, so the worst case is an extra file in
the lender's folder, never an overwrite. A read-only flag is WP6.

**D7. Expansion is one level and non-transitive.** A borrower's includes are
never expanded through the lender's own includes. Cycles are impossible by
construction and the selection response stays bounded.

---

## 2. The declaration

### 2.1 File format

`.ccsync-project` of the borrowing project, additive key:

```json
{
  "slug": "2026-ff5-elections",
  "created_by": "dashboard",
  "created_at": "2026-08-01T09:00:00+00:00",
  "includes": [
    {
      "path": "Projects/2026/FF5/Civil Defence/Interviewees/朱福銘 Aha Chu",
      "note": "interview reused in the Elections episode",
      "added_by": "footage-sorter",
      "added_at": "2026-08-23T00:26:00+00:00"
    }
  ]
}
```

* `includes` is a list; an entry is an object with `path` (required) or, as
  shorthand, a bare string.
* `path` is the **tree-relative posix path including the projects dir name**
  (`Projects/...`): the canonical `P:\Projects\...` with the prefix stripped
  and `\` flipped to `/`. It is the one spelling identical on the NAS, on
  Windows and on macOS, and the one footage-sorter derives from its `dst`
  strings. After TREE_LAYOUT_PLAN WP1 the leading segment is
  `layout.projects_dir` (default `Projects`).
* `note`, `added_by`, `added_at` are informational; unknown keys are kept.
* Writers MUST preserve every other key, `slug` above all.
  `provision.write_marker` overwrites the whole file today; WP1 makes it
  merge, and `server/write_marker.py --force` learns the same.

### 2.2 Validation (server-side, `dashboard/src/ccsync_dashboard/links.py`, pure functions)

`parse_includes(raw) -> list[str]`, then
`resolve_include(projects_dir, borrower_rel, include_path, layout) -> LinkResult(status, lender_rel, sub_rel, detail)`:

1. Type: list; items str or dict with str `path`; else `invalid`. Cap 32
   entries per marker, the rest dropped as `invalid: too many`.
2. Normalise: `\` to `/`, strip whitespace and trailing `/`, NFC-normalise
   unicode (NAS, Windows and macOS agree on NFC for these names; never NFD).
3. Refuse (`invalid`): empty; leading `/`; any segment that is `.`, `..`,
   empty, starts with `.`, contains a control char or `:` (drive letter), or
   is over 255 bytes. Reuse `api._validate_tree_part` (`api.py:1792-1805`).
4. Must start with `<projects_dir>/` and carry at least two more segments:
   a bare project dir is not an include ("tick both projects instead");
   anything outside `Projects/`, notably `Assets/...`, is
   `invalid: only folders inside a project can be shared` (§7).
5. No segment equal to `proxy` (case-insensitive): lane A's `- **/Proxy/**`
   is relative to the run root, so a run rooted inside `Proxy/` would upload
   proxies as originals. `invalid: cannot share a Proxy folder; share its parent`.
6. Lender: `provision.marked_ancestor(projects_dir, rel, include_self=False)`
   must return a project rel (`lender_rel`) that is not the borrower's own
   (`invalid: that folder is inside this project already`).
   `sub_rel = rel[len(lender_rel)+1:]`. No marked ancestor:
   `invalid: not inside a project`. A marked descendant inside `sub_rel`
   (`provision.marked_descendants`): `invalid: contains a project`.
7. Existence: `(projects_dir / rel).is_dir()` and `realpath` still under
   `projects_dir` (no symlink escape); else `missing` (kept, shown amber,
   not expanded).
8. Lender row: `projects.slug == read_marker(lender dir)` and `active == 1`;
   else `lender-inactive`.
9. Overlap within one marker: drop an include equal to or below another of
   the same marker (log `duplicate`). Overlap with a selection is per machine
   at response time (§4.2).
10. Cycles: none possible under D7. A borrower that is also a lender is fine
    and tested.

Statuses: `ok | missing | invalid | lender-inactive`. Only `ok` reaches a
companion.

### 2.3 Where it is parsed and stored

* `provision.read_marker_data(directory) -> dict | None` (new);
  `read_marker` becomes a wrapper returning `data["slug"]`.
* `collector._run_provision` (`collector.py:372-479`) already scans every
  marker each cycle. New step 6 after the shared-folder step:
  `self._run_links(conn, scanned_by_rel)`: for every marker with `includes`,
  resolve and `db.replace_project_links(conn, borrower_slug, rows, now)`; a
  borrower without the key loses its rows. Per-slug fault isolation as in
  `_provision_slug`.
* Schema `SCHEMA_V27` in `db.py` (`_MIGRATION_STEPS`, `db.py:790-822`):

```sql
CREATE TABLE IF NOT EXISTS project_links (
  borrower_slug TEXT NOT NULL,
  declared_path TEXT NOT NULL,     -- normalised, as written in the marker
  lender_slug   TEXT,              -- NULL unless status in (ok, missing)
  sub_rel       TEXT,              -- below the lender dir, posix
  status        TEXT NOT NULL,     -- ok | missing | invalid | lender-inactive
  detail        TEXT,
  first_seen    TEXT NOT NULL,
  last_seen     TEXT NOT NULL,
  PRIMARY KEY (borrower_slug, declared_path)
);
CREATE INDEX IF NOT EXISTS ix_project_links_lender ON project_links(lender_slug);
```

* `db.replace_project_links`, `db.fetch_links_for_borrowers(slugs)`,
  `db.fetch_borrowers_of(lender_slug)`, `db.fetch_borrowers_by_lender()`.
* **Lender moved on the NAS.** The collector retargets the lender's folder by
  slug (`collector.py:600-612`). On the next links pass the declared path no
  longer resolves, but the row's `lender_slug` + `sub_rel` still do.
  Resolution order: (a) declared path; (b) failing that, and only when the
  row already has a `lender_slug`, `projects.label(lender_slug) + "/" + sub_rel`.
  If (b) exists: status `ok`, `detail = "declared path is stale; the folder moved to ..."`,
  and the UI shows an "update the declaration" hint. The product never
  rewrites a customer's marker for this (TREE_LAYOUT_PLAN D6).

---

## 3. How each lane handles a borrowed dir

### 3.1 Selection expansion on the companion (`sync/sequencer.py`)

`_update_known_selection` (`:859-890`) additionally builds:

* `self._borrowed_by_slug: dict[str, list[dict]]`: per borrower, the
  includes that pass `_include_is_valid(entry)`:
  `normalized_safe_rel(entry["subpath"])` is not None, at least 3 segments,
  no `proxy` segment, `lender_slug` is a str. Anything else is dropped with
  one warning per pass. Fail closed, never widen.
* `self._borrowed_lenders: dict[str, BorrowedLender(rel, subs, borrowers)]`
  for lenders NOT in the selection (a selected lender needs nothing extra).
* `self._rel_to_slug` gains `borrowed_rel -> borrower_slug`, so
  express/watchdog attribution (`rclone_lane.py:1844-1857`, longest prefix
  wins) and `notify_change` (`:554-588`) work for a file dropped into a
  borrowed dir. `known_rels()` therefore returns borrowed rels too;
  `_selected_project_rels` (the manifest and proxy-scan input,
  `app.py:949,1050`) must NOT: it stays the selection's own rels (§3.3).

`_process_project` (`:1192-1234`): after `self._run_lanes_a_and_b(subpath, budget)`
and before `_maybe_scan_orphans`:

```python
for inc in self._borrowed_includes(slug):          # already deduped, see 4.2
    sub = f"{PROJECTS_PREFIX}{inc['subpath']}"
    self._maybe_clone_structure(sub, f"{slug}::{inc['subpath']}", forced=False)
    if stop/pause: return
    self._run_lanes_a_and_b(sub, budget)
    self._maybe_scan_orphans(sub, f"{slug}::{inc['subpath']}")
```

`_clone_ages` / `_orphan_ages` are keyed by that compound key and pruned with
the slug (`_prune_bookkeeping`, `:892-923`: drop keys whose part before `::`
is not live). Budget: `project_rotation_seconds` is per `run_once`, so a
borrower with N includes gets N+1 budgets; acceptable for v1, shown in the
tray detail as "shares N folders". Offline detection (`_note_transport`,
`:1300-1318`) is per `_run_lanes_a_and_b` call and unchanged.

### 3.2 Lanes A (up) and B (down)

* No change to `build_filter_rules_up/down`, `build_up_command`,
  `build_down_command`, `_join_remote_path`. The subpath is just deeper.
* Lane A's "project dir not yet local" check (`rclone_lane.py:2625-2635`) is
  satisfied by the structure clone that precedes it.
* Lane B: `--backup-dir` becomes
  `.ccsync-trash/<ts>/Projects/<lender-rel>/<sub>/...`; breaker scope is the
  sub subpath (`:2642-2655`); `count_local_proxies(local_root, sub)` counts
  only that subtree. The "remote shrank" memory (`lane_guard.py:62-65`) is
  per scope, so the first pass on a new scope has no opinion, same as a
  newly ticked project.
* Deletes: lane B may trash local proxies under the borrowed subtree that the
  NAS lacks, identical to a ticked project and recoverable from trash. Lane A
  never deletes. Nothing ever deletes on the NAS.
* Express: `path_matches_lane_a_filter` + `_project_rel_for_path(known_rels)`
  attribute a write under a borrowed dir to `Projects/<borrowed rel>`;
  `_express_run` uploads local_root-relative paths (`:3958-4041`), so the
  NAS path is the lender's. Correct.
* Both projects selected: the server omits the include (§4.2) and the
  companion also drops any include equal to or under a selected rel or under
  another include of the same machine (`_dedupe_includes`, longest prefix),
  so a stale cache cannot double-run. Two concurrent lane A runs on one
  subtree are already impossible (`_run_lock`).
* `removal_blockers` / `pending_uploads(subpath)` (`app.py:3431-3479`): for
  a borrower, also dry-run each include subpath so "remove from this
  machine" cannot destroy un-uploaded footage in a borrowed dir. Removal
  itself only rmtree's the borrower's own dir (`app.py:3626`); the partial
  lender dir is never deleted automatically (§5).

### 3.3 Lane C (Syncthing): `sync/borrowed_folders.py` (new, modelled on `shared_folders.py`)

`BorrowedFolderManager(admin, local_root, lenders_fn, selected_slugs_fn, halted)`;
`reconcile()` runs once per sequencer pass right after
`_reconcile_shared_folders()` (`sequencer.py:605`) and at startup.

For each lender in `lenders_fn()` (lenders not in the selection):

1. `want_path = local_root/Projects/<lender_rel>`;
   `want_ignores = restricted_ignore_lines(subs)`:
   ```
   STIGNORE_LINES...                       # video, Proxy, partials, tmp: first match wins, keep these first
   !/Interviewees                          # one line per ancestor of each sub
   !/Interviewees/朱福銘 Aha Chu
   !/Interviewees/朱福銘 Aha Chu/**
   **                                      # everything else in the lender stays out
   ```
   Glob specials in names (`*`, `?`, `[`, `{`, `\`) are escaped with `\`;
   no `(?i)` prefix on the negations (case-exact path). Helpers
   `restricted_ignore_lines(subs)` and `is_restricted(fetched)` (true when
   the last line is `**` and at least one `!` line is present) live in
   `syncthing_admin.py` next to `missing_ignore_lines`.
2. Folder absent: `pending_folders()`; accept from the offering device (the
   NAS shared it because the borrower is ticked, §4.1) with
   `accept_folder(lender_slug, label=lender_rel, local_path=want_path, ..., ignore_lines=want_ignores)`
   (`syncthing_admin.py:424-487`: create paused, set ignores, unpause).
   `mkdir` first, as `shared_folders._accept` does.
3. Folder present: path mismatch, so pause, move the dir if old exists and
   new does not (reuse `repath.ProjectRepather._move_dir`), `set_folder_path`;
   ensure versioning and ignoreDelete (existing admin helpers); ignores: if
   `get_ignores` lacks any `want_ignores` line or is not restricted,
   `set_ignores(want_ignores)`; unpause only if ignores are confirmed and
   not `halted()`.
4. A lender that drops out of the borrowed set and is not selected:
   `remove_folder(lender_slug)` (config only; files stay). A lender that
   becomes selected is handed to the sequencer (below).

Sequencer side, for a SELECTED folder that still carries a restriction (the
editor just ticked a lender they were borrowing from): `_ignores_state`
(`sequencer.py:1634-1671`) returns `IGNORES_MISSING` when
`is_restricted(fetched)`, and `_reassert_folder_policy` writes the full
`STIGNORE_LINES` (`set_ignores` replaces the whole list).
`_verify_startup_ignores` gets the same check. The folder stays paused until
the rewrite lands. Fail closed.

The partial lending project on disk, and every reader of the tree:

| Reader | Behaviour with a partial lender dir | Change |
|---|---|---|
| `fixer.list_project_dirs` (`fixer.py:152-183`) | No marker at `Projects/<lender-rel>` (lane C never pulls it: `!/<sub>` does not un-ignore the root file), so not a project. If the editor once had the lender ticked and later unticked, the marker is on disk and it is listed, as today | none; `extra_rels` must be the selection's rels only |
| `manifest.scan_local_manifest` (`manifest.py:98-134`) | As above; borrowed files are reported under no slug | none in v1 (§7) |
| `proxy_scan` / `proxy_gen` (`proxy_scan.py:517-527`) | Not walked on editors (no marker); walked under the lender on the base rig, where proxies are made | none |
| `removable_projects` (`app.py:3406-3429`) | Selection items only; a partial lender is never offered for removal | none |
| Rotation / pause (`_lane_c_turn` rotate scheme, `_unpause_all`) | Only selection slugs are paused or released; the restricted lender folder belongs to the manager | `halt_folder_ids()` (`sequencer.py:513-536`) adds the manager's `folder_ids()` so a halt pauses them |
| `repath.reconcile` | Selection items only | manager step 3 handles a moved lender |
| Structure clone | Creates only the borrowed subtree (`clone_directory_tree(subpath=sub)`) | none |
| `paths.classify_path` | Under local_root and canonical: OK / MISSING | none (§5) |

### 3.4 Who owns what

| Concern | Owner |
|---|---|
| Uploads into a borrowed dir | borrower's machine, lane A, allowed (D6); express included |
| Proxies down | lane B on the borrower's turn, sub subpath |
| Everything else | lender's Syncthing folder, restricted by `.stignore` on the borrower's device, sendreceive with ignoreDelete both ends (as today) |
| Local deletes | lane B's `rclone sync` under the sub subpath only (trash + breaker); nothing else deletes; NAS never |
| Both selected | include omitted server-side and companion-side; the lender's full folder and normal runs cover it |

---

## 4. Selection API and dashboard

### 4.1 Enforce (who receives the lender's Syncthing folder)

`collector._run_enforce` (`collector.py:947-1024`): when computing `desired`
for folder `slug`, add the devices of every (editor, machine) whose
selection includes a **borrower** of `slug` with an `ok` link:

```python
borrowers_of = db.fetch_borrowers_by_lender(conn)       # lender_slug -> {borrower_slug,...}
for borrower in borrowers_of.get(slug, ()):
    for editor, machine in selections.get(borrower, []):
        ... same device resolution as the selected branch ...
```

Same unapproved-device warning, same blast-radius brake. A borrowing device
is shared the whole lender folder; its local `.stignore` restricts what it
pulls (D4).

### 4.2 Selection response (additive)

`_selection_view` (`api.py:1477-1499`) gains, per item:

```json
{
  "slug": "2026-ff5-elections",
  "label": "2026/FF5/Elections",
  "rel_path": "2026/FF5/Elections",
  "position": 2,
  "active": true,
  "includes": [
    {
      "subpath": "2026/FF5/Civil Defence/Interviewees/朱福銘 Aha Chu",
      "lender_slug": "2026-ff5-civil-defence",
      "lender_label": "2026/FF5/Civil Defence",
      "sub_rel": "Interviewees/朱福銘 Aha Chu"
    }
  ]
}
```

* `subpath` is spelled like `rel_path` (under `Projects/`), so the companion
  does `PROJECTS_PREFIX + subpath` exactly as at `:1205`.
* `ok` rows only; rows whose `lender_slug` is in this machine's selection are
  omitted; rows nested under another include of the same machine are omitted
  (longest prefix wins). Computed in `_expand_includes(conn, rows)`, unit
  tested.
* `schema` stays 1 (additive by contract, `site.py:46-48`).
* The companion's cached `selection.json` carries it automatically
  (`selection.py:269-293`).

### 4.3 UI

* `partials/sidebar.html` `project_row`: chip `[ +N ]`,
  `title="shares N folder(s) from other projects"` when `p.links_ok`; red
  `[ LINK ]` chip when any link is `invalid`, `missing` or `lender-inactive`.
* `partials/project_detail.html`: after SELECTED BY, a `SHARES FROM:` block
  (one row per link: sub_rel, lender label linked, status chip, `detail`)
  and a `SHARED INTO:` block on a lender's page. Data from
  `build_project_view` (`api.py:291`) via `db.fetch_links_for_borrowers` /
  `fetch_borrowers_of`.
* `partials/my_queue.html`: under each queued item, muted sub-lines
  `shares Interviewees/朱福銘 Aha Chu from 2026/FF5/Civil Defence` from
  `item.includes` (added in `build_queue_view`, `api.py:1236-1256`).
* No editing UI before WP5. WP5 adds `[ SHARE A FOLDER INTO THIS PROJECT ]`
  on the project-setup browser (`partials/project_setup_panel.html`,
  `ui.py:490-501` browse pattern), writing the marker through the same
  `links.py` validator and the merging `provision.write_marker`.
* Copy follows the no-em-dash rule (`test_no_em_dash.py` in both suites).

---

## 5. Path canon, fixer, popup, guards

* **Canon and classification (verified):** `classify_path` (`paths.py:282-290`)
  returns OK for a downloaded borrowed file at `P:\Projects\<lender>\...`
  and MISSING for a not-yet-downloaded original (`:311-329`), never
  OUT_OF_TREE; the popup is fed only by OUT_OF_TREE (`app.py:2313,3065`), so
  it never offers to copy borrowed media into the borrower. `canon.py` is
  path-shape agnostic (`TREE_LAYOUT_AGNOSTICISM.md` §6). One regression test
  in `test_paths.py` names the borrowed shape explicitly.
* **Consolidate (`app.py:2386`)** scans OUT_OF_TREE only; unaffected.
  `fixer.pick_project_prefix` is for out-of-tree clips; unaffected.
* **Proxy relink (`proxy_relink.py`)** works on in-tree originals with a
  sibling `Proxy/`; borrowed originals are in-tree. Unaffected.
* **Rotation / pause / halt:** lender folders borrowed on this machine are
  never in `ordered_selected`, so the rotate scheme cannot pause them; a halt
  must (WP2: `halt_folder_ids`). `_unpause_all` cannot release them; the
  manager does, gated by `halted()` and confirmed ignores.
* **Removing a lender from a machine while a borrower is selected:**
  `removal_blockers(lender)` adds
  `"part of this project ('Interviewees/...') is shared into 2026/FF5/Elections, which is still selected here"`.
  Blocked; override allowed and logged; the next pass re-pulls the borrowed
  subtree through the manager. Removing the borrower: rmtree of the
  borrower's own dir only; the partial lender dir stays; the manager drops
  the lender's local Syncthing config on the next pass (no borrower left);
  files untouched.
* **Move of the lending folder on the NAS:** the server re-resolves via
  `lender_slug + sub_rel` (§2.3); the companion manager re-points or moves
  the local partial dir (§3.3 step 3). A rename of the SUB folder inside the
  lender (`朱福銘 Aha Chu` to `Aha Chu`) is a lane C rename on the lender's
  folder and a `missing` link on the borrower until the declaration is
  updated; the dashboard says so.
* **Deleting the lending project:** folder gone, `projects.active=0` after
  the grace, link `lender-inactive`, not expanded; the borrower shows the
  red chip; the manager removes the local lender folder config; local files
  stay.
* **stignore:** the NAS-side `.stignore` is unchanged (`_ensure_ignores`
  byte-equality intact); the restriction exists only on the borrowing
  device. The companion's missing-lines check is a superset test, so
  restricted and full lists both pass it; `is_restricted` is the extra,
  fail-closed test for selected folders.
* **Fail-closed filter validation:** an include that fails
  `_include_is_valid` is dropped, never widened to the lender root; lanes A/B
  still pass `validate_filter_file`; a lender whose restricted ignores cannot
  be confirmed stays paused.
* **Layout rev:** under TREE_LAYOUT_PLAN D5 the restricted list is derived
  from `STIGNORE_LINES` of the current layout, so it inherits the rev guard.

### Tests to add

| File | Cases |
|---|---|
| `dashboard/tests/test_links.py` (new) | shorthand and object entries; each refusal in §2.2 (3-6, proxy segment, bare project, outside Projects, inside own project, contains a project, symlink escape); `missing`; `lender-inactive`; duplicate and nested includes in one marker; stale declared path resolved via slug; unicode NFC |
| `dashboard/tests/test_collector.py` | `_run_links` replaces rows per borrower and deletes when the key disappears; one bad marker does not abort the cycle; enforce shares the lender folder with a borrower's device and unshares when the borrower is unticked; the brake counts those removals |
| `dashboard/tests/test_selection_api.py` | `includes` present and shaped as §4.2; omitted when the lender is selected on that machine; nested include dedupe; `?machine=` per-machine difference; old-shape cache still parses |
| `dashboard/tests/test_db.py` | V27 migration replayable; `fetch_borrowers_of` |
| `dashboard/tests/test_provision.py` | `write_marker` preserves `includes` and unknown keys; `read_marker_data` |
| `companion/tests/test_sequencer.py` | include runs lanes A/B after the project's own, compound subpath; invalid include dropped and logged; include equal to a selected rel skipped; budget per run; `known_rels` includes borrowed rels and `_selected_project_rels` does not; `halt_folder_ids` includes borrowed lenders; a selected lender with restricted ignores is rewritten before unpause |
| `companion/tests/test_borrowed_folders.py` (new) | accept with restricted ignores, paused until confirmed; re-point on path change; remove config when no borrower is left; halted stays paused; `restricted_ignore_lines` escaping and ancestor lines |
| `companion/tests/test_rclone_express.py` | a write under a borrowed dir is attributed to `Projects/<borrowed rel>`, not the lender root |
| `companion/tests/test_rclone_lane.py` | `_backup_dir` and breaker scope for a 5-segment subpath |
| `companion/tests/test_paths.py` | borrowed canonical path: OK / MISSING, never OUT_OF_TREE |
| `companion/tests/test_app.py` | `removal_blockers(lender)` blocked by a selected borrower; `removal_blockers(borrower)` dry-runs include subpaths |
| `server/tests/test_cross_component.py` | `restricted_ignore_lines` starts with the exact `STIGNORE_LINES` prefix (the lane split stays byte-identical) |
| Real run (gate for WP3) | dev Synology: lender + borrower, one editor VM ticks only the borrower: proxies arrive at the true path, a `.wav` in the interviewee dir arrives via lane C, nothing else of the lender arrives; tick the lender, the restriction lifts; untick both, folder configs removed, files stay |

---

## 6. Work packages

### WP0 - Audit. DONE 2026-08-23 (this document)

### WP1 - Declaration, validation, mirror table, read-only UI (dashboard). 2 days

Files: `dashboard/src/ccsync_dashboard/links.py` (new), `provision.py`
(`read_marker_data`, merging `write_marker`), `db.py` (`SCHEMA_V27`,
`replace_project_links`, `fetch_links_for_borrowers`, `fetch_borrowers_of`,
`fetch_borrowers_by_lender`), `collector.py` (`_run_links` as step 6 of
`_run_provision`), `api.py` (`build_project_view`, `build_queue_view` carry
`links`), `templates/partials/sidebar.html`, `project_detail.html`,
`my_queue.html`, `server/write_marker.py` (merge under `--force`),
`docs/CONFIG.md` (marker format section), tests per §5.

Acceptance: a hand-written `includes` in a marker on the dev NAS shows on the
borrower's project page with status `ok` within one provision cycle; each
refusal in §2.2 shows its reason; deleting the key clears the rows; nothing
reaches any companion yet.

### WP2 - Selection expansion and lanes A/B (dashboard + companion). 2 days

Files: `api.py` (`_expand_includes`, `_selection_view`), `collector.py`
(`_run_enforce` borrower devices),
`companion/src/ccsync_companion/sync/sequencer.py` (`_update_known_selection`,
`_process_project`, `_include_is_valid`, `_dedupe_includes`,
`_prune_bookkeeping`, `halt_folder_ids`), `app.py` (`removal_blockers`
include dry-runs and the lender block), tests per §5.

Acceptance: an editor VM with only the borrower ticked: lane B pulls
`.../Interviewees/朱福銘 Aha Chu/Proxy/*` to the true path; a clip dropped
there is express-uploaded to the lender's NAS dir; ticking the lender too
produces no duplicate runs (one subpath per pass in the log); a `../` or
`Proxy` include in a tampered cache is dropped with a warning and nothing
runs outside the declared scope. Lane C for the borrowed dir is NOT yet on:
enforce shares the lender's folder but nothing accepts it; the offer sits
pending, harmless.

### WP3 - Lane C restricted folder (companion). 3 days incl. the Syncthing spike

Files: `companion/src/ccsync_companion/sync/borrowed_folders.py` (new),
`syncthing_admin.py` (`restricted_ignore_lines`, `is_restricted`, glob
escaping), `sequencer.py` (`_reconcile_borrowed_folders`, `_ignores_state`
restriction check, `_verify_startup_ignores`), `app.py` (construct the
manager beside `SharedFolderManager`, wire `halted`), `docs/SYNC_SAFETY.md`
(new section "borrowed folders"), `docs/delete-protection-ignoredelete.md`
note, tests per §5.

Spike first (half a day): confirm D4's three assumptions against the bundled
Syncthing. If (a) fails, plan B is a second Syncthing folder created by the
collector at the sub path, with the lender's folder given an ignore line for
`/<sub>/.stfolder`. Documented, not built unless needed.

Acceptance: the real-run gate in §5.

### WP4 - footage-sorter writes the declaration. 1 day

Files in `E:\Projects\footage-sorter`: `lib/ingest/ccsyncLink.js` (new:
`findProjectMarker(absPath)` walks up to the nearest `.ccsync-project` under
`destRoot`; `toTreeRel(absPath)` strips `destRoot`'s parent (`P:\`), flips to
posix, prefixes `Projects/`; `addInclude(markerPath, includePath, note)`
reads the JSON, appends if absent, writes tmp + rename, preserves every
key), `lib/ingest/plan.js` (`elsewhere` records gain
`linkable: {borrowerMarker, includePath}` when the existing path's
containing dir and the planned dest resolve to two different marked
projects), `server.js` (`POST /api/link-folder {clipId}`: the ONE write
outside `data/` the app makes, called out against `README.md`'s read-only
rule), `public/app.js` (review row: `[ LINK FOLDER INSTEAD ]` next to the
"already on P: elsewhere" hint), `SPEC.md`, tests for `toTreeRel` (unicode,
trailing slash, `W:` vs `P:` source) and for the marker merge preserving
`slug`.

Granularity is the directory: the sorter links the folder that already holds
the clip (its parent dir), never a file. It refuses when the existing path is
under `Proxy/` (offers the parent) or is not inside a marked project, with
the same messages as `links.py`. Keep the rule list in one comment block in
both repos, with a test in each.

Acceptance: assigning the Aha Chu interview to Elections in the sorter
writes the `includes` entry into
`P:\Projects\2026\FF5\Elections\.ccsync-project`; the dashboard shows it
within a cycle; no bytes are copied.

### WP5 - Dashboard authoring and docs. 1 day

Files: `api.py` (`POST /api/v1/projects/{slug}/links {path}`, `DELETE ...`;
admin or the project's ticked editor), `ui.py` and
`partials/project_setup_panel.html` (browse-and-link),
`docs/HOW_IT_WORKS.md` and `EDITOR_SETUP.md` ("Sharing a folder between two
projects"), `TREE_LAYOUT_PLAN.md` §2 table gains `includes` as marker data
(not layout data), `KNOWN_BUGS.md` carry-over: borrowed files are not
counted in the borrower's MEDIA column (§7).

### WP6 - Out of scope (design notes only)

Read-only includes; includes of `Assets/*`; reporting borrowed files under
the borrower in the presence manifest; transitive includes; file-level
links.

### Rollout and rollback

Dashboard first: WP1 is inert for old companions (`includes` is an unread
key); WP2's enforce change shares a lender folder with a device whose
companion ignores the pending offer, harmless. Then companions: WP2 and WP3
ship together or apart; a WP2-only companion runs lanes A/B for borrowed
dirs and leaves the Syncthing offer pending. No NAS-side script changes
beyond the `write_marker.py` merge. Nothing on disk moves, so rollback is:
remove the key from the marker; rows clear on the next cycle; companions stop
running the sub subpaths on their next selection fetch; local partial lender
dirs remain and the tray lists them as "borrowed folders no longer in use"
(WP3).

---

## 7. Order and size

| WP | Days | Ships alone? | Unblocks |
|---|---|---|---|
| WP1 declaration + mirror + UI | 2 | yes | everything |
| WP2 expansion + lanes A/B | 2 | yes (WP1 deployed) | the Aha Chu case for video and proxies |
| WP3 lane C restricted folder | 3 | yes (WP2) | audio, subs and docs in a borrowed dir |
| WP4 footage-sorter | 1 | yes (WP1) | the declaration written where the decision is made |
| WP5 authoring + docs | 1 | - | editors without the sorter |

About nine working days. First customer-visible result at the end of WP2
(day 4). Until then the stop-gap for the Aha Chu case is a plain second copy
made by the sorter, with the duplicate removed once WP2 lands.
