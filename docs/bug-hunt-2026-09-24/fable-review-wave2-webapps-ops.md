# Fable review, wave 2: web apps + ops (broll/ music/ ytdl/ tools/ bench/ docs/)

Adversarial read-only review of the uncommitted wave-2 fix pass over HEAD
4462a2a, groups `broll`, `music-ytdl` and `release-tools` (tools/ half),
2026-09-25. Method: every hunk in `git diff -- broll music ytdl tools bench
docs` read against the finding it cites and the ledger's claim; the four new
regression files run against a `git archive HEAD` copy of the trees (with the
new test files dropped in) and against the working tree; one scratch probe
written for the gap found (below). Nothing in the repo was edited except this
file; no whole suite was run.

HEAD-copy results (the tests the builders say fail on HEAD):

| file | on HEAD copy | on working tree |
|---|---|---|
| broll/web/tests/test_bug_hunt_2026_09_24_w2_broll.py | 36 failed / 4 passed (the 4 are the declared guards) | 40 passed |
| broll/indexer/tests/test_bug_hunt_2026_09_24_w2_broll.py + test_http_backend.py | (ledger: 5 fail) | 14 passed |
| music/web/tests/test_bug_hunt_2026_09_24_w2_music-ytdl.py | 35 failed / 12 passed (guards) | 47 passed |
| ytdl/web/tests/test_bug_hunt_2026_09_24_w2_music-ytdl.py | (ledger: 13 fail) | 19 passed |
| tools/tests/test_bug_hunt_2026_09_24_w2_release-tools.py | 37 failed / 6 passed (the 6 negative guards) | 43 passed |

The tests are honest: none mocks away the thing that breaks (the client-folder
tests drive the real ledger + index through the routes; the music name tests
create real placeholder files under the session library; the ship.ps1 and
ci.yml tests EXECUTE the sliced script blocks; the publish_feed tests run the
dashboard's own `select_offered_records` on the produced channel).

## Verdict table

| finding / change | verdict | note |
|---|---|---|
| bug-broll-1 + logic-broll-music-1 (client-folder items resolved, not OR'd) | REAL-AND-SAFE | one rule (`_resolve_item`) now shared by draw / tick / add / remove / note / public caption; `reorder` still keys by stored `video_id`, which the panel receives from `resolve_items`, so a re-keyed (negative) id stays consistent; negative ids read as "no index row" everywhere |
| bug-broll-2 (HttpBackend posts the canonical id + path) | REAL-AND-SAFE | low skew note (#3 below); `http_remote_ids` is `CREATE TABLE IF NOT EXISTS` in the indexer's private shadow file, idempotent, not a schema migration of anything shared; ids are re-learned by every scan (`scanner.py:226` upserts every clip) |
| bug-broll-3 (stills keyed by a mint-twice id) | DEFERRED, correctly | four owners and a key-design choice; the ledger's warning that half of option (b) is unsafe is right |
| bug-wire-2 (retired session keys accepted) broll / music / ytdl | REAL-AND-SAFE | parse identical to `dashboard/settings.py:798`; accept-only; an unset current secret still refuses; mounted apps share the dashboard's environment |
| bug-broll-4 (cancelled release from a stale machine) | REAL-AND-SAFE for b-roll; **NOT closed on the same-shape music route** | see problem 1 |
| logic-broll-music-4 (curator's own open is not a client view) | REAL-AND-SAFE | `BrollGate.__call__` runs `_identified_scope` on EVERY http request (`dashboard/.../broll.py:393`), share paths included, so the header half works through the gate; `?preview=1` only ever hides a view |
| bug-wire-7 server halves (X-CCSync-Machine-Pct) broll + music | REAL-AND-SAFE | plain header wins; malformed escape names nobody (410 not 500); ytdl half NOT_A_DEFECT is right: `ytdl_executor` never sends the twin and `_machine_of` reads the body/query id |
| ui-broll-web-3 (hotkeys yield to drawers / focused buttons) | REAL-AND-SAFE | Space and Shift+Enter deliberately unchanged, reasoning holds |
| ui-broll-web-1, 2, 4..18, ui-dash-static-5 parity, drawer-close | REAL-AND-SAFE | static only; error toasts now persist until dismissed (deduped by kind+text, capped at 4): a behaviour change worth knowing, not a defect |
| bug-music-ytdl-2 (claim_dest + NAME_LOCK) | REAL-AND-SAFE | lock held for a stat loop and one transaction; both writers (browser `queue_one`, fleet `write_item_result`) and the inline base-rig path take it; low note #4 |
| bug-music-ytdl-3 (unlanded rows are not mount evidence) | REAL-AND-SAFE | the review-round narrowing (mkdir stays strict, plain-words refusal) is right; pre-004 falls back to the old query |
| bug-music-ytdl-4 + logic-broll-music-3 (cancel drops rows whose audio never landed) | REAL-BUT-BREAKS-X | the delete itself is guarded well (share readable, any spelling on disk keeps the row, FK cascade via `db.con()`), but it is now reachable through the unfixed music twin of bug-broll-4, which turns a lease-takeover race into deletion of the HOLDER's rows: problem 1 |
| ui-music-ytdl-web-2, 4, 5 (+review), 6, 7, 8, 9 (+review), 10 | REAL-AND-SAFE | web-5's review round (sort disabled under a ranked answer) is the right call; web-9's review scoping to `ranBatchUid`/`ranIds` closes the re-attach and mid-run-drop holes |
| ui-music-ytdl-web-1, 3 | REAL-AND-SAFE | web-3: every lock test is `=== false`, so a failed `loadProjects` (undefined) or an old server without `api/attestation` leaves the server as the gate, as documented |
| logic-ytdl-jobs-3 (page half: hand-back announced) | REAL-AND-SAFE (page) | 3 s poll for 240 s per 202 on the loopback, 1 s budget, 404 ends it; companion half OWED to c-ytdl (other reviewer's area) |
| logic-ytdl-jobs-4, ui-copy-5 | REAL-AND-SAFE | |
| logic-release-2 (retract of current refused without a successor) | REAL-AND-SAFE | checked after `--set-current`/`--make-current` have had their say; a retract of the only build still passes |
| logic-release-6 / -7 (`--set-current`, make-current on a staged version, key-rotation forwarding) | REAL-AND-SAFE | REL-7 check uses the pointer and records from BEFORE the run, so a same-run retract cannot dodge it; `--min-version`/`--notes` named as not applied on a pointer move |
| bug-ops-2 (+review) (ship -Resume past the publish) | REAL-AND-SAFE | `$prior` is only read where `Test-StepDone` can be true (it needs `$script:ResumeFrom`, set only under `-Resume`); the journal advances only on 2b exit 0/3; installer-version mismatch falls back to a full probe |
| bug-ops-3 (recall line parses) | REAL-AND-SAFE | built from the same constants `publish()` uses, parsed and RUN by the test |
| logic-release-5 (unsigned requires_dashboard is a NOTE) | REAL-AND-SAFE | stderr now echoed on success too |
| bug-ops-4 + ui-onboarding-11 (enumerate installer/tests/test_*.sh in run_all_tests.ps1 and ci.yml) | REAL-AND-SAFE | both run every file after a failure and fail on none found |
| docs/ (12 files) | REAL-AND-SAFE | the RELEASE.md rollback section matches the code's refusals; no em dash added to any visible string in my area (scanned the diff for U+2014: none) |

CLAUDE.md invariants checked across the area: no em dash in visible text
(clean); no schema migration on a shared database; no new REQUIRED wire key
(`item_id`, `share`/`rel_path`, `X-CCSync-Machine-Pct`, `?preview=1` are all
optional both ways; companion 0.9.77 against dashboard 0.7.58-in-repo is
unaffected, and every server change is server-only); no `scriptapp`; deploy
order: nothing here needs the companion first.

## Problems, ranked

### 1. MEDIUM. The music fleet route still accepts a cancelled release from a machine that no longer holds the batch, and since this wave that release DELETES the holder's track rows

- `music/web/musicweb/routes_fleet.py:283-291` (the `cancelled` branch of
  `release`): the check is `batch['editor'] != editor` only, exactly the shape
  bug-broll-4 fixed in `broll/web/app/routes_fleet.py:146-151`. Music's
  `claim` lets another of the editor's machines take an expired lease
  (`ingest_batches.py:733`: 409 only while `lease_live`), and
  `ingest_batches.release(state='cancelled')` now runs
  `_drop_unlanded_tracks` (`ingest_batches.py:1301-1330`).
- Failure scenario (probed, scratch test
  `probe_music_takeover_cancel.py` run from the music venv with the suite's
  conftest): EDIT-01 claims, its lease expires, EDIT-02 claims and posts a
  `result` (a `tracks` row with the embedding, windows, peaks; audio still
  uploading). EDIT-01 posts `release {state: cancelled}`. Working tree:
  **200**, batch `cancelled`, EDIT-02's `tracks` row **gone**, its
  `ingest_items.track_id` nulled. EDIT-02's `uploaded` will then hit a
  cancelled item, and the file it lands is an orphan with no row until a
  base-rig sweep. On HEAD the same call only cancelled the items and left
  the row (the ghost bug-music-ytdl-4 fixed), so this wave made the twin's
  consequence worse, not better.
- Trigger realism: same as bug-broll-4 (verified low there): the stale
  machine's companion has to run `cancel()` (tray, or a report-reply cancel
  command) after waking and before its first heartbeat 410s
  (`broll_ingest._lease_lost` does not release). The report-reply cancel is
  scoped to the holder (`cancel_requested_for` filters `machine = ?`), so it
  is the tray click. Narrow, but the cost is now the holder's work.
- Fix is the same eight lines as broll's, before `ingest_batches.release`:
  `if x_ccsync_machine and batch['machine'] and batch['machine'] !=
  x_ccsync_machine and ingest_batches.lease_live(batch): raise
  HTTPException(410, {... 'reason': 'other_machine' ...})`. `lease_live`
  exists at `ingest_batches.py:156` and `_leaseholder_or_410` already answers
  the same 410 for the non-cancelled path (`routes_fleet.py:114-117`). Plus
  the mirror of broll's two tests. The companion's `release` already treats a
  410 as "the server had already taken it back" (`broll_ingest.py:499-506`).

### 2. LOW. `_drop_unlanded_tracks` can delete a row whose audio is mid-flight as `<name>.partial`

- `music/web/musicweb/ingest_batches.py:1314`: `_disk_state(dest_name)` sees
  only the final name; rclone writes `<name>.partial` and renames on
  completion (`companion/.../broll_upload.py:164`). On the holder's own
  cancel this cannot happen (`cancel()` stops uploads before releasing), and
  on the sweep path (`expire_stale_leases` releasing a cancel-requested,
  silent batch) the companion may still be uploading; the outcome is an
  orphan file with no row, picked up by the next sweep, and the editor did
  ask to stop. Note only; the ledger's "deletion over retry" choice is
  defensible.

### 3. LOW. bug-broll-2 skew and the path-wins rule

- `broll/indexer/.../http_backend.py:_remote_ref`: a clip scanned BEFORE the
  upgrade has no mapping until the next scan; against an OLD web app
  `write_index_result` then posts `video_id: 0` and 404s (loud, and the right
  direction versus writing on the wrong clip). Against the new app it
  resolves by path. `routes_ingest._target_video_id` prefers the path even
  over a correct canonical id, so a shadow whose `rel_path` has gone stale
  versus the server 404s instead of updating by id. HttpBackend is dormant on
  the base rig (sqlite mode), so this is a note for whoever first runs the
  indexer over HTTP.

### 4. LOW. `claim_dest` can leave a 0-byte placeholder in the library

- `music/web/musicweb/db.py:claim_dest` creates the file O_EXCL and
  `routes_ingest.queue_one:389-395` removes it only when the move raises. A
  process death between the two leaves an empty `<name>` in the library that
  the next sweep will probe. Cheap to make the sweep skip 0-byte files; not
  this wave's problem.

### Information (not defects)

- Root `CLAUDE.md` "Running tests" still lists only
  `bash installer/tests/test_macos_site_values.sh`; `run_all_tests.ps1` and
  ci.yml now enumerate `installer/tests/test_*.sh` (the ledger flagged this
  for the orchestrator; CLAUDE.md belongs to no builder group).
- Two OWED items land in the other reviewers' areas and were not built here:
  logic-ytdl-jobs-3's companion half (claim refusals as hand-backs,
  `ytdl_executor.py`) and bug-music-ytdl-2's defence in depth
  (`--ignore-existing` on music uploads, `broll_upload.py`). Neither is
  needed for the fixes above to hold.
- The release-tools ledger's own observation stands: `merge_into_published`
  overlays the LOCAL feed dir's `current` over the published one, so a
  second rig with a stale `feed/` could re-point `current` after another
  rig's rollback. One rig publishes today.
- Behaviour change to be aware of, not a bug: b-roll error toasts persist
  until dismissed (deduped, at most 4).

## Should anything block the commit?

Problem 1 should be fixed **before** the commit: it is an eight-line twin of a
fix already in this wave, in the same route shape, and the wave itself is
what gave the gap a destructive consequence (`DELETE FROM tracks` on the
holder's rows). It is not a reason to hold the rest: every other change in
this area is a real fix of what it cites, its regression tests fail on the
HEAD copy and pass on the tree, and nothing here breaks an older companion, a
deploy order, or a CLAUDE.md invariant. Problems 2-4 are notes for the ledger.
