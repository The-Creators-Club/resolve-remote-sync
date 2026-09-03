# dash-db — dashboard schema/migrations, selections model, jobs queue, provisioning

Files read (with approximate coverage):
- `dashboard/src/ccsync_dashboard/db.py` (~55%: all of the migration machinery
  and `_MIGRATION_STEPS` v1..v46 headers, `connect`/`migrate`/`_split_statements`/
  `_already_applied`, the selections block 4740-5520, notices 2689-2860,
  file_moves 4272-4600, machines registry 3500-3700, forget/evict 6320-6470,
  media_rel_key + replace_* 6780-6960, jobs 7429-8200, capabilities 8330-8570,
  `fetch_sync_backlog` 7260-7350)
- `dashboard/src/ccsync_dashboard/provision.py` (100%)
- `dashboard/src/ccsync_dashboard/syncthing_client.py` (100%)
- `dashboard/src/ccsync_dashboard/assignments.py` (100%)
- `dashboard/src/ccsync_dashboard/links.py` (100%)
- `dashboard/src/ccsync_dashboard/internal_sftp.py` (100%)
- `dashboard/src/ccsync_dashboard/local_users.py` (~55%, reads + hashing)
- Callers traced out of territory to verify: `api.py` (report reply, claim
  route, copy-plan route, file-move route), `collector.py::_run_enforce`,
  `notices.py`, `invariants.py`, `jobs.py`, `server/common.py` (stignore parity)
- `dashboard/tests/test_db.py` (migration tests), `test_unicode_paths.py`

Tests run:
`dashboard\.venv\Scripts\python.exe -m pytest tests/test_db.py tests/test_multi_machine.py tests/test_jobs.py tests/test_provision.py tests/test_unicode_paths.py -q`
-> **179 passed, 1 skipped** (111 s). No regressions found by the suite.

## Findings

### dash-db-1 — the unassigned bucket is fanned out to WIRED (base-rig) machines, bypassing CR-28
- Severity: medium
- Confidence: CONFIRMED (db-level behaviour proven; downstream share is a direct read of `_run_enforce`)
- Where: `dashboard/src/ccsync_dashboard/db.py:5440` (`fetch_machine_selections`,
  the `for machine in machines:` bucket loop) and `db.py:5332`
  (`selections_for_machine`); contrast `db.py:4927` (`add_selection_for_person`,
  which *does* skip wired machines) and `api.py:4489` (copy-plan 409).
- What: CLAUDE.md's "a base rig can hold no tick" (CR-28) is enforced on every
  WRITE path — `add_selection_for_person` filters `base_machines()`, the tick
  route and the copy-plan route 409 — but the bucket-inheritance READ path
  applies no such filter. `fetch_machine_selections` fans `machine=''` rows out
  to *every* row of `machines` for that editor that has no plan of its own,
  wired machines included, and `selections_for_machine(editor, base_machine)`
  returns the bucket for the same reason.
- Failure scenario: an editor account with a wired desktop and a remote laptop
  (an explicitly supported shape since f27c181 / MULTI_BASE_RIG_PLAN §5). A
  bucket row exists for that person — an admin ticked before any companion
  reported, a companion too old to name its machine, or the collector's
  one-shot seed from pre-existing Syncthing shares, all three of which db.py
  documents as bucket sources. The wired desktop then (a) is handed that
  project by `GET /selection`, and (b) is added to `desired` in
  `collector._run_enforce` (which reads exactly this map and has no base
  filter), so the NAS starts Syncthing-sharing a project folder with the
  machine whose tree root *is* the NAS share. It can never make progress
  against the tick, which is CR-28's permanent [ GETTING READY ] shape arriving
  by the one route the write-side guards cannot see.
- Evidence: run from the dashboard venv against a fresh migrated db:
  ```
  base_machines {('ed', 'DESK')}
  base_only_editors set()
  # bucket tick, machine=''
  machine selections FULL: {'projx': [('ed', 'DESK'), ('ed', 'LAP')]}   <-- DESK is wired
  selections_for_machine DESK: ['projx']
  # person-level tick, for contrast
  ->  {'projx': [('ed','DESK'), ('ed','LAP')], 'projy': [('ed','LAP')]}  <-- projy correctly skips DESK
  ```
  `collector.py:1273-1345` consumes `fetch_machine_selections` and only ever
  filters on `sync_modes` and on device mapping; `base_machines`/`machine_modes`
  appear nowhere in the enforce cycle.
- Ledger: related to CR-28 (recorded FIXED) — the fix covered the write paths
  only; new for the bucket path.
- Suggested fix: in `fetch_machine_selections`'s bucket loop, skip
  `(editor, machine)` present in `base_machines(conn)` (and make
  `selections_for_machine` return `[]` for a wired machine), so "a base rig
  holds no tick" is one predicate on both the write and the read side.

### dash-db-2 — `db.notice()` returns a bogus id whenever the notice already exists
- Severity: low
- Confidence: CONFIRMED
- Where: `dashboard/src/ccsync_dashboard/db.py:2744-2750`
- What: after `INSERT ... ON CONFLICT(kind, subject) DO UPDATE`, SQLite does
  not update `last_insert_rowid()` on the DO-UPDATE path, so
  `cur.lastrowid` returns the rowid of the last *real* insert on that
  connection — typically an unrelated row in `fleet_audit`, `alert_log` or
  `diagnostics` written earlier in the same request. `notice()` returns that
  number, and the `SELECT id FROM notices WHERE kind=? AND subject=?` fallback
  written to handle exactly this case is unreachable dead code (the stale
  lastrowid is truthy).
- Failure scenario: the second and every later cycle in which a condition is
  still true. `notice(conn, "plan_without_share", ...)` returns e.g. 50 (a
  `fleet_audit` id) instead of the notice's own id. No caller in this build
  uses the return value, so today it is latent; the first caller that passes it
  to `dismiss_notice()` or renders it as a [ DISMISS ] target dismisses the
  wrong notice or none at all.
- Evidence:
  ```
  first insert lastrowid 1
  upsert-update lastrowid 50 rowcount 1     # 50 rows inserted into another table between
  real id [(1,)]                            # sqlite 3.49.1, dashboard venv
  ```
  and `grep -n "lastrowid" db.py` shows `notice()` is the only upsert among the
  seven `lastrowid` sites (the other six are plain INSERTs).
- Ledger: new.
- Suggested fix: drop the `if cur.lastrowid:` shortcut and always do the
  `SELECT id ... WHERE kind=? AND subject=?` lookup (or gate the shortcut on
  `cur.rowcount == 1 and` a pre-existence check).

### dash-db-3 — `.ccsync-project.tmp` is written inside a sendreceive/ignoreDelete Syncthing folder that does not ignore `*.tmp`
- Severity: low
- Confidence: PLAUSIBLE (race window is small; the failure mode has precedent)
- Where: `dashboard/src/ccsync_dashboard/provision.py:write_marker_data`
  (`tmp = Path(directory) / (MARKER_FILENAME + ".tmp")`) vs
  `provision.build_stignore_lines()` / `server/common.py:build_stignore_lines`
- What: the atomic marker write drops a temp file in the project ROOT. A
  project folder's `.stignore` lists video, `*.partial`, the ytdl patterns and
  `Proxy`, but **not** `*.tmp` — that pair exists only in
  `ASSET_JUNK_IGNORE_LINES`, which is applied to the shared asset folders. The
  project folders carry `ignoreDelete: True`, so anything Syncthing's fsWatcher
  picks up between `write_text` and `os.replace` is replicated to every ticked
  editor and its later removal is *never* propagated.
- Failure scenario: a marker rewrite (self-heal, adopt, repair, or a link-
  authoring endpoint) on a busy project while Syncthing's watcher fires inside
  the write window leaves a permanent `.ccsync-project.tmp` on every editor's
  disk that no cycle can clean up — the same shape as the 27 orphaned `.part`
  files that produced `YTDL_IGNORE_LINES`.
- Evidence: `grep -n "\.tmp" server/common.py` -> only line 545, inside
  `ASSET_JUNK_IGNORE_LINES`; `build_stignore_lines()` (both copies) appends
  only VIDEO + PARTIAL + YTDL + Proxy lines.
- Ledger: new (same class as KNOWN_BUGS B12 / the 2026-08-13 ytdl orphans).
- Suggested fix: write the temp file as `.ccsync-project.ccsync-tmp` (already an
  ignored suffix in the asset list) *and* add the `*.ccsync-tmp` pair to
  `build_stignore_lines()` in all three components, or write it to the parent
  `Projects` dir and `os.replace` across — keeping `server/common.py`,
  `provision.py` and the companion byte-identical (test_cross_component pins them).

### dash-db-4 — `_file_move_cutoff`'s error fallback produces a string that mis-sorts against every stored timestamp
- Severity: low
- Confidence: CONFIRMED (by inspection; the branch is only reached on an
  unparseable `now`)
- Where: `dashboard/src/ccsync_dashboard/db.py:4315-4321`
- What: every stored timestamp comes from `utcnow_iso()`, which strips
  microseconds. The happy path (`dt.datetime.fromisoformat(now)`) preserves
  that shape, so the lexicographic `delivered_at < cutoff` comparison in
  `expire_delivered_file_moves` is sound. The `except ValueError` fallback uses
  `dt.datetime.now(dt.timezone.utc)` **without** `.replace(microsecond=0)`, so
  the cutoff gains a `.123456` fraction; `'.'` (0x2E) sorts above `'+'` (0x2B),
  so a target delivered in the same second as the cutoff compares as older than
  it and is expired one whole second early.
- Failure scenario: cosmetic in practice (one second at a 7-day cutoff), but the
  same fallback shape copied into a shorter window would silently expire live
  rows. Called out because `_job_lease_until` right below documents the "one
  producer, one offset, one resolution" rule that this line breaks.
- Evidence: `utcnow_iso()` -> `.replace(microsecond=0).isoformat()`;
  `_file_move_cutoff`'s fallback has no such replace.
- Ledger: new.
- Suggested fix: `dt.datetime.now(dt.timezone.utc).replace(microsecond=0)` in
  the fallback (or reuse `parse_iso(utcnow_iso())`).

## Things I checked and found SOUND (so the merge does not re-hunt them)

- **Migration idempotence / half-failure.** Each step runs its statements one at
  a time inside an explicit `BEGIN`, with the `PRAGMA user_version` bump in the
  same transaction, and `_already_applied` skips an `ALTER TABLE ... ADD COLUMN`
  whose column exists. `test_db.py` covers: idempotence, gapless numbering,
  per-step version commit, mid-step replay, atomicity of step+bump, and refusal
  of a newer schema. I additionally proved that `sqlite3.complete_statement`
  correctly ignores `;` and apostrophes inside `--` comments, and that no chunk
  produced by `_split_statements` over the *real* v1..v46 scripts contains two
  executable statements (script below in evidence terms: 0 merged chunks). Note
  that if one ever did, `conn.execute` raises `ProgrammingError` loudly rather
  than silently dropping the second half — so that trap is fail-loud.
- **Old code vs new db.** `migrate()` raises `RuntimeError` when
  `user_version > max(steps)`; the only production caller is the FastAPI
  `lifespan`, so the container refuses to boot rather than 500-ing per query.
- **`sync_modes=(SYNC_MODE_FULL,)` audit.** Every reader that decides what comes
  DOWN passes it: `collector._run_enforce` (1273/1274), `notices._check_plan_without_share`
  (450), `invariants` (235, 518), `api` report reply (477). The callers that
  deliberately omit it are all "either mode" reads — the assignments grid
  (`assignments.py:61,67`), the file-move target set (`api.py:2484`, correct: an
  upload-only machine is exactly the one holding the card dump), the link-write
  permission check (`api.py:2341`), and `invariants._check_machine_has_plan`
  (279, where any tick is a plan). `fetch_sync_backlog` handles it inline
  (`db.py:7331`). **No reader forgot it.**
- **`fetch_machine_selections`'s bucket rule.** `has_own` is computed over ALL
  of a machine's rows *before* the mode filter, so a laptop holding one
  upload-only tick does not inherit the bucket's full ticks. I traced the four
  combinations by hand; all match `selections_for_machine`.
- **Jobs CAS.** `claim_job`'s `UPDATE ... WHERE id=? AND state=?` + `rowcount`
  is a genuine compare-and-set; a second connection serialises behind the write
  lock (`busy_timeout=5000`). Lease timestamps are produced by one function in
  `utcnow_iso()`'s exact shape, so the string comparisons are chronological.
  `claim_next_job` re-checks capabilities; the route passes the scheduler's
  `allowed_ids` so `target_machine` (v46) cannot be bypassed. `job_requirements_met`
  coerces defensively and refuses unknown requirement keys.
- **`media_rel_key` NFC.** Applied on the way IN in both `replace_nas_media` and
  `replace_editor_media`, the only two tables `fetch_sync_backlog` diffs, and
  never on a path something opens. `api.py:538/549` normalises both sides of the
  transfer-name join. The `editor_media` lookup in the file-move target query
  (`api.py:2487`) compares raw `from_rel`, but both ends of that comparison
  originate from the NAS walk (already NFC), so it is not exposed.
- **SQL by string formatting.** Every `f"..."` SQL in db.py interpolates a
  module-level constant table name or `_CAPABILITY_COLUMNS`; all user data is
  bound. `syncthing_client._seg` percent-encodes folder/device ids into REST
  path segments.
- **Threading.** Connections are per-request / per-task (`Depends(get_conn)`,
  or a fresh `db.connect` per collector/background job); `check_same_thread=False`
  is only there for FastAPI's threadpool hop, WAL + a 5 s busy timeout are set on
  every connection.
- **`store_machine_capabilities`** writes wholesale (so an allow-list can be
  cleared) and is a bare `UPDATE`, correctly a no-op before the machine_state row
  exists.

## Coverage note

Not covered: `local_users.py`'s write half (create/disable/key add-remove) past
line 200; the release-channel/package half of db.py (v7/v11/v14/v34) and
`soak_state`; `prune()` and the retention passes; `record_invariant_result` and
the alerts helpers; `internal_sftp`'s interaction with a real sidecar. I ran the
five most relevant suites, not the whole dashboard suite.

What the suite does not cover, and which would have caught the findings above:
- No test asserts that a **wired machine never inherits the unassigned bucket**
  (`test_multi_machine.py` covers the bucket rule and CR-28's write-side 409s,
  but never the two together). A test like
  `fetch_machine_selections(...)` over an editor with one `base` machine and one
  `editor` machine plus a `machine=''` row would fail today.
- Nothing asserts `db.notice()`'s returned id equals the row's id on the
  re-assert path — `test_notices.py` checks the row's contents, not the return.
- `test_provision.py` does not assert that every file a provisioning write can
  leave behind in a project root is matched by `build_stignore_lines()`.

## OUT OF TERRITORY

- `dashboard/src/ccsync_dashboard/collector.py:1273-1345` (`_run_enforce`): the
  enforce cycle applies no `base_machines`/`machine_modes` filter to the plan it
  gets from `fetch_machine_selections`, which is the half of dash-db-1 that
  turns a wrong read into an actual Syncthing share. Fixing it in db.py is
  enough, but a belt-and-braces filter here would also cover the `editor_selections`
  (person-level) fallback path used for unmapped devices.
- `dashboard/src/ccsync_dashboard/api.py:2487`: the `editor_media` file-move
  target query compares `rel_path` with a raw `from_rel` rather than through
  `db.media_rel_key` — safe today because both sides come from the NAS walk, but
  it is the one exact-path comparison on that table left outside the normaliser.
