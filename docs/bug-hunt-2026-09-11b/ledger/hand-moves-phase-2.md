# Hand moves on the server, phase 2: the locate call and lane B following it (2026-09-11)

`docs/HAND_MOVES_ON_THE_SERVER.md` section 7 phase 2, plus sections 4a and
4b. Built after the design; phase 1 (detection in the collector) and phase 3
(the grid and the breaker message) are other builders' and are NOT here.
Dashboard version untouched (the coordinator bumped it to 0.7.45); companion
bumped **0.9.72 -> 0.9.73**.

## What the phase is for

A folder moved by hand on the NAS presents to an editor's lane B as a
deletion: the files left the path that machine syncs, so `rclone sync` walks
the local copies into `.ccsync-trash` and, past 50 in one pass, the breaker
parks the lane (CR-45, and Ruskin's PC on 2026-09-11). CR-44's relocation
probe already asks "were they moved?", but it asks by re-listing the SCOPE,
and every move that has actually cost an editor a day went to a DIFFERENT
project. This phase asks the same question of the dashboard, which holds an
inventory of the whole tree, and then FOLLOWS the answer.

## 1. `POST /api/v1/files/locate` (dashboard)

New module `dashboard/src/ccsync_dashboard/locate.py`; the route is fourteen
lines at the end of `api.py`, on `_require_fleet_caller` - the same gate the
jobs claim uses (fleet token AND a signed `X-CCSync-Identity`), because the
answer spans every active project and drives a rename on an editor's disk.
`app.py` carries the two lines every fleet route needs: the login gate's
exact-path allowance and the CSRF exemption. **No edit to `db.py`,
`collector.py`, `ui.py` or any template.**

Request, and the answer:

```json
{"files": [{"name": "A002_C048.mp4", "size": 734003200}]}

{"walked": true, "as_of": "2026-09-11T18:45:02Z",
 "files": [{"name": "A002_C048.mp4", "size": 734003200,
            "found": [{"project_slug": "2026-ff5-talent-gap",
                       "rel_path": "Interviewees/Proxy/A002_C048.mp4"}]}]}
```

- `name` is a basename (a path sent in is reduced to one: the path is
  precisely what stopped being true), compared NFC through `db.media_rel_key`
  (CR-90). `rel_path` comes back in the server's own spelling, because that is
  what the companion renames to.
- `found` is every place that name+size sits, `[]` when none. **Ambiguity is
  reported, never resolved here** - the mover on the far end refuses a file
  with more than one candidate (design section 6).
- `walked: false` = this dashboard has never completed an inventory walk, so
  "not found" means "not known". `as_of` = the newest `refreshed_at` in
  `nas_media`, i.e. how stale the picture is.
- Cap 2000 files, **413 with a sentence** past it. A silent truncation would
  have the caller read the unanswered half as deleted, which is the one wrong
  conclusion this route exists to prevent.
- Read-only, `nas_media` only, no NAS filesystem call.

**The query is a size prefilter plus a basename match in Python**, chunked at
900 parameters, not a `LIKE '%/name'` per file: `nas_media` is keyed on
`(project_id, rel_path)` and has no basename column, so one scan bounded by
the caller's own cap beats two thousand index-less lookups. Adding an index
would be a schema change in a module that must not own one this week.

## 2. The breaker's probe is tree-wide (companion)

New `companion/src/ccsync_companion/sync/server_locate.py`: `ServerLocator`,
built from `cfg` + `identity.token` exactly as `jobs_runner._headers` does,
calling through `broll_ingest.default_request` (no redirects ever followed).
10 s timeout, one call per pass, at most 2000 pairs.

`rclone_lane._count_relocations` keeps its two existing rules (same rel path
on the remote; same basename+size elsewhere IN THE SCOPE) and gains a third:
the file is in the set the SERVER found somewhere in the tree. The set is
filled once per pass by `_relocate_trashed`, so the locate call is never made
twice. A failed listing of the scope no longer zeroes the whole probe - the
server's answer is a different question and still counts.

**Every failure contributes 0**: no dashboard URL, no token, a transport
error, a non-200, an unparseable body, `walked: false`. That is CR-44's own
rule ("every failure falls back to treat them all as deletions"), and this is
the code path that decides NOT to stop a lane that is removing files. The
`min(relocated, deleted)` clamp in `lane_guard` is untouched.

## 3. Lane B moves instead of trashing (companion)

`RcloneLane._relocate_trashed(subpath)` runs after the pass and before the
breaker accounting, on the trash rclone has just filled (so the "move" is a
rename out of `.ccsync-trash` into the new folder - one volume, and nothing
was ever deleted at any point). Per file:

| The server says | This machine | What happens | Breaker |
|---|---|---|---|
| one place | syncs that project (either sync mode) | renamed into `<local_root>/Projects/<project rel>/<rel_path>`, folders created as needed | relocation |
| one place | does not sync it (section 4b) | stays in `.ccsync-trash`, quietly | relocation |
| one place, something already there with the same size | either | the local copy is a duplicate: stays in the trash | relocation |
| several places | either | nothing moves (section 6) | relocation |
| nowhere, or no usable answer | either | exactly 0.9.72's behaviour | deletion |

`os.rename`, never `os.replace`: a destination that appeared between the
check and the rename is a refusal, not a file lost. A destination with a
DIFFERENT size at the new path is left alone too, with a warning naming it.
A `rel_path` that escapes `local_root` (a `..`, a rooted component) is
refused - the answer arrives over the network and drives a rename, so it is
input, not instruction. One INFO line per pass: `moved N,
trashed-as-duplicate N, trashed-not-synced-here N, found in more than one
place N, deleted N`.

Wiring: `app.py` builds the `ServerLocator` and passes
`project_rel_fn=self._project_rel_for_slug`, which reads the sequencer's
`rel_to_slug` (both sync modes - an upload-only project is still a folder on
this disk). Both constructor arguments are optional and default to None, so a
lane built by a test, by consolidate or by an older caller behaves exactly as
0.9.72.

## Files changed

- `dashboard/src/ccsync_dashboard/locate.py` (new)
- `dashboard/src/ccsync_dashboard/api.py` (import, `LocateFileIn`/`LocateIn`, one route)
- `dashboard/src/ccsync_dashboard/app.py` (login gate + CSRF exemption, two entries)
- `companion/src/ccsync_companion/sync/server_locate.py` (new)
- `companion/src/ccsync_companion/sync/rclone_lane.py` (two constructor args,
  `_relocate_trashed`, `_local_destination`, `_move_out_of_trash`, the probe's
  third rule, the call site in `run_once`)
- `companion/src/ccsync_companion/sync/lane_guard.py` (comment only: what the
  probe costs now)
- `companion/src/ccsync_companion/app.py` (wiring + `_project_rel_for_slug`)
- `companion/src/ccsync_companion/config.py`, `companion/pyproject.toml` (0.9.73)
- `docs/API.md` (the route, in section 2 beside `/report`), `docs/SYNC_SAFETY.md`
  (the CR-44 paragraph in the runbook)
- `dashboard/tests/test_locate.py` (new, 11 tests),
  `companion/tests/test_rclone_lane.py` (+15)

## Tests

`dashboard`: `tests/test_locate.py` + `tests/test_no_em_dash.py` - 140 passed.
`companion`: `tests/test_rclone_lane.py` + `tests/test_lane_guard.py` - 210
passed; `tests/test_app.py` - 384 passed (the wiring).
`dashboard`: `tests/test_auth.py` + `tests/test_hardening.py` - 84 passed (the
login gate).

## Left out, deliberately

- **`docs/LOOPBACK_API.md` is not touched.** It documents the companion's own
  127.0.0.1:8899 listener, not the dashboard routes a companion calls; those
  live in `docs/API.md`.
- **The breaker message does not name where the files went**, and there is no
  `[ IT WAS A MOVE, CARRY ON ]`. That is phase 3.
- **proxy_pairs does not use locate yet** (phase 3 as well).
- **Nothing here writes `file_moves`.** A relocation lane B follows on its own
  is not recorded as a move, and the `file_move_targets` note in section 4b
  ("trashed locally, destination not synced here") belongs to phase 1's rows.
  A machine that follows a DETECTED move through `commands.file_moves` is
  unaffected by any of this.
- **The locate call is made on every pass that trashed anything**, not only on
  passes near a breaker limit: the move-instead-of-trash half is worth more
  than the round trip, and a pass that trashed nothing makes no call at all.
