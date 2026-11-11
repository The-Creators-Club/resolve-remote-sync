# Footage Sorter: the loading message, a faster first load, and new clips without a full rescan

Written 2026-11-11 as a read-only plan, while another session was working in
the Footage Sorter repo. **Status the same evening: parts A and B are built**
(uncommitted in that repo, not deployed, by the owner's word; `FIXES.md` in
this folder has the list). **Part C is built too** (C7 and the page menu for "Rescan this folder" are not). A6 was dropped: the
server never reports a card as still being read. This file belongs in the
sorter's own `docs/` once it is committed there.

The owner, 2026-11-11: "fix everything taking so long to load on sorter. On
first load it takes a very long time, and there is no 'loading' - it just says
no clips match your current filter. I'm thinking it takes around half a second
at least." And: "is there a way to keep it up to date without rescanning
everything every time? I just copied clips onto fifi huang in projects 2026 and
they did not appear in footage sorter quickly, I had to do a full rescan."

Three separate things, in the order they should be built.

## What was measured

On a scratch copy of the local catalogue (35,762 clips, 13,595 assignments;
`scratchpad/sorter_measure.py`, not kept), on the workstation. The NAS has a
slower processor, so its times will be longer, not shorter. The destination
tree was not read off the NAS for this.

| What the page asks for | Not built yet | Already built |
|---|---|---|
| `api/state/meta?lean=1` | 386 ms | 0 ms (47 KB gzip) |
| `api/clips?location=source&slim=1` | 457 ms | 0 ms (29 KB gzip) |
| `api/clips?location=final&slim=1` (first click on a destination folder, a search, "All clips") | 618 ms | 0 ms (3.3 MB gzip) |
| `api/dest/detail` | 35 ms | 0 ms (309 KB gzip) |
| what the server builds ahead of time today (`state_blob("state")`) | 682 ms | not one of the above |
| `engine.load()` at start-up | 1.0 s | |

All of these are built while holding the engine's one lock, so the three
requests a page opens with wait for each other. "Not built yet" is the state
after every restart of the dashboard (there were four on 2026-11-11, from
Cards deploys) and after every scan.

Also measured: the page's own 14 files are 614 KB and go out uncompressed
(167 KB gzipped), each revalidated on every visit; the answer to every assign
and unassign is 2,847 KB uncompressed (310 KB gzipped).

## Part A. "No clips match the current filters" while it is still loading

This is a bug with one cause, plus three places with the same shape.

**The cause.** `public/grid.js` `init()` attaches a `ResizeObserver` to the
grid (line 48). An observer fires once when it starts, so 60 ms later
`relayout()` runs `layout()`, and `layout()` line 124 does
`emptyEl.classList.toggle('hidden', view.length > 0)` with an empty view. That
un-hides `#gridEmpty`, whose text in `index.html` is "No clips match the
current filters." It stays up until the state has arrived and `renderCenter()`
hides it. So the message is on screen for the whole of the first load, whatever
the filters are.

| | File | Change |
|---|---|---|
| A1 | `public/grid.js:124` | `emptyEl.classList.toggle('hidden', view.length > 0 \|\| !(window.App && App.loaded));` The empty message is only ever true once there is data to be empty. |
| A2 | `public/index.html:161` | `#gridStart` starts VISIBLE with a loading card already in the markup (`<div class="start-card"><div class="start-title"><span class="spin"></span> Loading your clips</div></div>`, `data-mode="boot"`), and `#gridViewport` starts with class `is-start`. Then there is a loading state before any script has run. |
| A3 | `public/app.js` `renderCenter()` (1545) | Two more modes ahead of the existing ones: `boot` while `!App.loaded` (leave the markup from A2 alone), and `failed` when the state did not load (title "The clips did not load", the error, a "Try again" button that calls `loadState()` and `applyFilters(true)`). |
| A4 | `public/app.js` `boot()` (4526) | On a failed `loadState()` set `App.loadError` and call `renderCenter()`. Today it shows a toast and then falls through to "No clips scanned yet - press Rescan", which is the wrong advice for a server that did not answer. |
| A5 | `public/ledger.js` `whereTest()` (395) and `renderCenter()` | Choosing a drive filters by that drive's clip list, fetched in pages of 5,000. Until it is here the test is `function () { return false; }`, so the grid says "No clips match". Export `wherePending(f)` (true when the set for `f.whereVol`, or the cloud volume for `nocloud`, is `'loading'` with no older copy) and give `renderCenter()` a `drive` mode: "Listing the clips on <drive name>". |
| A6 | `public/app.js` `renderCenter()` | A card chosen in Source while its session is still `scanning` has no clips yet: a `card` mode, "Reading the card". (`s.state === 'scanning'`, already used at `ingest.js:533`.) |
| A7 | `public/app.js:1935` | The empty text gets a third case: nothing to say while `!App.loaded`. |

Tests: `test/app.test.js` and `test/grid.test.js` (Node, fake DOM). One test
per row: the observer firing before the state does not un-hide the message;
the boot card is in the markup; a rejected state shows `failed` and its
button retries; a pending drive list shows `drive`.

## Part B. The first load

In order of what it saves.

| | File | Change | Saves |
|---|---|---|---|
| B1 | `footage_sorter/engine.py` `start()` (the `prewarm` loop, ~304) and the end of `run_scan()` | Build what the page actually asks for, not `/api/state`: `state_blob("meta", lean=True)`, `clips_view(("source",))`, `dest_blob("summary")`, `ensure_tree()`, then `clips_view(("final",))` and `dest_blob("detail")`. One function, called 1 s after start and after every scan (where `self.state_blob("state")` is called today). `state` itself last, and only while an old cached page can still ask for it. | 0.84 s off the first load after a restart or a scan, 0.65 s off the first destination view (workstation figures) |
| B2 | `footage_sorter/web.py` `_json()` (89) and the `endpoint` wrapper (~128) | Gzip any JSON body over 8 KB when the request accepts it (`Vary: Accept-Encoding`). `_json` has no request today, so the wrapper passes it. The dashboard has no compression in front of `/sorter`. | every assign and unassign: 2,847 KB to 310 KB; `api/desttree`, the drive lists, `api/cards`, `api/audio` |
| B3 | `footage_sorter/web.py` `index()` and `_PublicFiles` (576); `public/index.html` | (a) `index()` rewrites each `src="x.js"` and `href="style.css"` to `x.js?v=<version>`, the version being the deployed commit (the deploy writes `DEPLOYED_COMMIT` beside `public/`) or, without one, a hash of the files' sizes and times. (b) A request carrying `v=` is answered `Cache-Control: public, max-age=31536000, immutable`; anything else stays `no-cache`. (c) `.js`, `.css` and `.html` are gzipped once per file version and kept in memory. (d) `dev-mock.js` is loaded only with `?mock=1` (an inline loader in its place, so the order of the scripts holds). The URLs stay document-relative. | a return visit: 0 requests for the scripts instead of 11 revalidations; a first visit: 614 KB to 167 KB |
| B4 | `public/index.html` (the `window.__early` block), `public/ingest.js` `boot`, `public/ledger.js` `boot` | Start `api/ingest/sessions` and `api/ledger/volumes` with the other early requests, and let the two modules take those answers as `app.js` takes the meta. The Source panel's cards and drives then do not wait for nine scripts to arrive and run. | the Source panel is complete one round trip sooner |
| B5 | `public/app.js` `assign`/`unassign` (2068-2106) | `afterManifestChange()` runs once on the optimistic change and again on the reply; skip the second when the reply's entries for the edited clips are what was assumed. (Audit `sorter-page-3`.) | half the redraw work per edit |

Not proposed: bundling the scripts into one file. With B3 they are cached for
good after the first visit, and a bundle would be a build step the sorter does
not have.

Tests: `tests/py/test_web.py` (a body over the limit is gzipped only when
asked for, and round-trips; a `v=` request is `immutable`, a bare one is
`no-cache`; `index()` stamps every script and the style); a start-up test that
the lean meta and the source view are in the cache after the prewarm without a
request; `test/app.test.js` for B4 and B5.

To check on the NAS after it ships: open the page once, restart the dashboard,
open it again, and read the three first requests' times in the browser's
network panel. They should be in single milliseconds server-side.

## Part C. New clips without a full rescan

**Today.** Nothing rescans on its own. The clip list changes only when
somebody presses Rescan, after a move plan runs, and after a card copy lands.
A background loop re-reads the destination's FOLDERS every 60 s
(`refresh_tree`), so a new folder shows up in the tree, but the files in it do
not become clips. A full scan walks every root: 76,386 files in 978 folders
here.

**The idea.** Adding, removing or renaming a file changes the modified time of
the folder it is in. So a walk that looks only at folders (about 1,160 of
them, plus their `Proxy` folders) can say which folders changed since the last
look, and only those are rescanned. The scanner already works a folder at a
time: `scan.py` `_Scan.root()` groups the files of ONE directory, plus the
`Proxy` folders under it, into clips.

| | File | Change |
|---|---|---|
| C1 | `footage_sorter/scan.py` | Split the body of the `while stack:` loop in `_Scan.root()` (544-626) into `_Scan.directory(d, source_root) -> (clips, sub_dirs, proxy_dirs)`. `root()` becomes the loop that calls it. Add `scan_dirs(settings, [(source_root, abs_dir), ...], memo, id_for) -> {abs_dir: clips}`. No behaviour change for a full scan: pinned by the existing scan tests and one new test that the two paths give the same clips for the same folder. |
| C2 | new `footage_sorter/watch.py` | `DirWatch`: a map of folder to (modified time in ns, the folder that owns it; a `Proxy` folder is owned by its parent, as the scanner consumes it). `walk(roots, shallow_roots)` lists folders only, with the scanner's own skip rules (`SKIP_DIR_NAMES`, hidden names, the app's own folder), and answers `(changed, new, gone)`. Kept in `data/watch.json` (about 1,500 short entries) so a restart knows what changed while it was down. With no such file the first walk only records. |
| C3 | `footage_sorter/scan.py` | A full scan fills the same map as it goes (the folder's time is read BEFORE it is listed, so a file that lands during the listing is caught on the next look). |
| C4 | `footage_sorter/engine.py` | `watch_tick()`, on a loop every 20 s (`loop("watch", lambda: 20, self.watch_tick, first=15)`), skipped while a full scan runs. For the changed folders: `SC.scan_dirs(...)`; then, under the lock, replace those folders' clips in `self.clips` (and drop the clips of folders that are gone), `SC.regroup_card_files` (its docstring says idempotent; a card's `CLIP` and `THMBNL` folders are rescanned together), the scan's own sort, `_set_clips`, and the same three follow-ups a full scan runs (`reconcile_moves`, `link_staging_scan`, `adopt_out_of_band_moves`). Outside the lock: thumbnails for the new clips only, `refresh_tree()` when a folder appeared or went, the prewarm of B1. |
| C5 | `footage_sorter/engine.py` | **A file still being copied is not a clip yet.** A file whose size or time differs from the previous look, or whose time is within the last 20 s, is "arriving": its clip is held back and its folder stays on the list for the next look. So a 40 GB copy appears when it has finished, not as a broken half. `scan_status()` gains `watch: {lastAt, changed, arriving}` so the page can say "3 files still copying into Fifi Huang". |
| C6 | `footage_sorter/engine.py` | `clips.json` (32 MB) is rewritten at most once a minute after these small updates, and always at a full scan and at stop. Today every scan writes it twice (audit `sorter-py-9`). |
| C7 | `footage_sorter/ledger_sources.py` `start_nas_scan()` (212) | The ledger (which copy is on which drive) learns about pool files from a walk of the whole pool, nightly and after a move. Give it the changed folders as its scope: `_begin_scan(NAS_ID, [""], ...)` already takes a list, which looks like a list of pool-relative scopes. **To verify before building.** |
| C8 | `footage_sorter/web.py`, `public/app.js` | `POST /api/scan {"paths": [...]}` runs the same function on named folders: a "Rescan this folder" item in the destination tree's and the Source panel's right-click menus, for the cases the watch cannot see (below). |
| C9 | `footage_sorter/web.py`, `public/app.js` `pollDestTree()` (492) | `GET /api/changes` answers `{clips: <etag>, dests: <signature>, ledger: <version>, arriving: n}`, a few dozen bytes. The page asks it every 10 s while its tab is visible, INSTEAD of downloading the whole destination tree every 15 s (audit `sorter-page-2`, `sorter-py-8`), and fetches the rows or the tree only when their value moved (`refreshRows()` is already conditional). A toast names what arrived: "12 new clips in Fifi Huang". |
| C10 | `footage_sorter/engine.py` | A full scan once a night, at the ledger's nightly time, as the net under all of this. There is no automatic full scan today. |

**What it would have done for the Fifi Huang copy.** The copy changes that
folder's time on the NAS. Within 20 s the watch sees it; the files are still
growing, so nothing is shown yet; once they have stood still for one look, the
folder is rescanned (a few dozen files, well under a second), the clips are in
the list, and every open page shows them within 10 s. No button.

**What the watch cannot see, and what covers it.**

- A file replaced in place under the same name (a re-export over the old one)
  does not change its folder's time. Covered by the nightly full scan, by
  Rescan, and by "Rescan this folder".
- A root that is not mounted is skipped, exactly as a full scan skips it.
- The cost of the look itself: about 1,500 folder reads every 20 s. The 60 s
  folder walk that exists today does nearly the same reads, and the two can be
  one walk (the tree is a by-product of it). **Measure on the NAS** before
  settling on 20 s; if it is not small, 60 s is still a hundred times better
  than a button.

**Considered and not chosen: file-system notifications (inotify).** They would
be immediate, but need a watch per folder, a new dependency or a hand-written
binding, and behave differently on the Synology port. A walk of folder times
needs none of that and survives a restart.

Tests: `tests/py/test_scan.py` (C1, the equivalence); a new
`tests/py/test_watch.py` on a temp tree (a file added, removed, renamed; a
file added under `Proxy`; a new sub-folder; a folder removed; a file that is
still growing is held back and then appears; a restart with a saved map);
`tests/py/test_engine.py` (a tick replaces only the changed folder's clips and
leaves every other clip object as it was; the follow-ups run; the catalogue
write is debounced); `test/app.test.js` (C9).

## Order, and what each step needs

1. **Part A** (page only, six small edits). Ships with the next sorter deploy.
   Fixes the wrong message on its own.
2. **B1 and B2** (server, small). The first load after a restart, and every edit.
3. **B3, B4, B5.**
4. **Part C**, C1 to C6 first (it works without the page changing: the clips
   are simply there on the next load), then C8 to C10, then C7 once the
   ledger's scope argument is confirmed.

None of it is a change to the dashboard or the companion: the sorter is its
own snapshot, shipped by the Cards deploy command (`docs/CARDS_DEPLOY.md`).
The sorter's uncommitted work from the audit fix pass (the closed-card fix
among it) and the other session's downloads feature are in the same working
tree, and whichever is committed first decides what the next deploy carries.

## Open questions for the owner

- Is 20 s (plus the wait for a copy to finish) quick enough, or should a
  folder being copied into show its clips as they arrive, marked "copying"?
- Should the nightly full scan (C10) exist? It costs a walk of everything
  once a night and is what catches a file replaced in place.
