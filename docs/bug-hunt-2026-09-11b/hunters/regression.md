# regression - did the 2026-09-11 fix pass (18e69f3) actually close the 131 findings it claims?

Files read (with approximate coverage): `docs/bug-hunt-2026-09-11.md` (the ten
highs in full, every territory section skimmed), `docs/bug-hunt-2026-09-11/{tally,verdicts}.txt`
(all 131 ids), `docs/bug-hunt-2026-09-11/ledger/*.md` (spot), `KNOWN_BUGS.md`
CR-233..CR-248, and the fix site of every id via `grep -rn <id>`. Code read in
depth for the eleven final-severity highs: `dashboard/src/ccsync_dashboard/`
`published_docs.py`, `help.py`, `ui.py` (help routes), `alerts.py`
(`_check_out_of_tree`, `Ctx`, `deliver`, `sink_deliverable`, `run_cycle`,
`ALERT_KINDS` order), `api.py` (`_rollout_block`, `_rollout_platforms_block`,
`_update_push_done`, `roll_fleet_back`, report handler), `db.py` (v52,
`request_machine_update`, `claim_job`, `claim_next_job`,
`expire_machine_update_requests`), `nas/synology.py`; `tools/ship.ps1`,
`tools/ship_gates.ps1`; `server/install_dashboard_app.py`;
`broll/web/app/client_folders.py`; `music/web/musicweb/ingest_batches.py`;
`companion/src/ccsync_companion/{broll_ingest,music_ingest}.py`;
`onboarding/steps.py`. Plus a mechanical sweep: every one of the 131 ids
against every source file, to find ids the ledger claims fixed that no code
cites.

Tests run: `cd dashboard; .venv\Scripts\python.exe -m pytest tests/test_help_page.py -q`
-> 38 passed, 1 skipped. (Other suites deliberately left to the central gate.)

## Findings

### regression-1 - the CR-241 fix for dash-collector-alerts-1 silences the catch-all "this computer is not syncing and we cannot say why" alert
- Severity: medium
- Confidence: CONFIRMED
- Where: `dashboard/src/ccsync_dashboard/alerts.py:1941` (`_check_out_of_tree`,
  the new `if ctx.name(who) not in ctx.open_alert_subjects("out_of_tree"): continue`),
  against `alerts.py:1122` (`Ctx.name`) and `alerts.py:2909`
  (`_check_red_unexplained`: `if who in ctx.named or ... : continue`)
- What: the fix spells "say nothing about a subject nothing was ever said
  about" as `ctx.name(who) not in ctx.open_alert_subjects(...)`, and
  `Ctx.name()` is not a predicate - it MUTATES, adding the machine to
  `ctx.named`. At 40f931a the `continue` sat one line ABOVE `who = ctx.name(who)`,
  so a skipped machine was never named. `_check_red_unexplained` is the
  registry's last kind (`ALERT_KINDS`: `out_of_tree` at :2993,
  `red_unexplained` at :3067) and exists precisely to catch machines no other
  check named, so a machine `out_of_tree` deliberately said nothing about is
  now excluded from the only check that would have spoken.
- Failure scenario: an editor's machine reports `resolve_health.out_of_tree = 40`
  and has a personal (non-tree) project open - the exact CR-232 case - and its
  lanes have been RED for over `RED_UNEXPLAINED_SECONDS`. `out_of_tree`
  `continue`s (no finding, correctly) but has already named the machine, so
  `_check_red_unexplained` skips it. The fleet's one "green while dead"
  backstop emits nothing: the editor is not syncing and nobody is told, by
  either kind.
- Evidence: `git show 40f931a:.../alerts.py` line 1779-1781 has `continue`
  before `who = ctx.name(who)`; HEAD has the `ctx.name(who)` call inside the
  membership test at :1941. `Ctx.name` (:1121-1123) is
  `self.named.add(subject); return subject`. `_check_red_unexplained` (:2907-2909)
  filters on `who in ctx.named`. Registry order confirmed at :2993 / :3067.
  The regression test
  (`tests/test_bug_hunt_2026_09_11_dash_collector_alerts.py:138`) never puts
  the machine in `health.RED`, so it cannot see this.
- Ledger: CR-241 (dash-collector-alerts-1 / res-fleet-3) opens a neighbour
- Suggested fix: ask the question without naming - `who_raw = _who(e)` and test
  `who_raw not in ctx.open_alert_subjects("out_of_tree")` before any
  `ctx.name()`; name only on the paths that actually emit a finding (the quiet
  branch should still name, because it holds an open row).

### regression-2 - the broll-2 fix hardens the migration but the door it was written to protect still falls over on a non-sqlite error
- Severity: low
- Confidence: CONFIRMED
- Where: `broll/web/app/client_folders.py:275-277` (`get_shares_db`'s
  `except sqlite3.Error`), against `:154` (`ensure_schema`'s
  `path.parent.mkdir(parents=True, exist_ok=True)`)
- What: the fix's own docstring says "a sqlite failure HERE is not allowed to
  take the public share door out", and the `except` catches `sqlite3.Error`
  only. `ensure_schema`'s first act is a `mkdir` on the data root, which
  raises `OSError` (`PermissionError`, `FileNotFoundError`, `OSError: Read-only
  file system`), not `sqlite3.Error` - and so does `sqlite3.connect` on a path
  whose parent cannot be traversed.
- Failure scenario: the NAS dataset holding `BROLL_DATA_ROOT` is unmounted or
  remounted read-only (the same bind-mount ownership failure music-1's
  verifier used). Every `/broll/share/<token>/...` request - the client-folder
  link an editor has already sent a customer - 500s with a traceback instead
  of the routes answering on their own merits, which is the exact outcome the
  `try/except` was added to prevent.
- Evidence: read `get_shares_db` and `ensure_schema` at HEAD; `mkdir` and
  `sqlite3.connect` are outside any handler in `ensure_schema`, and `OSError`
  is not a subclass of `sqlite3.Error`.
- Ledger: CR-245 does not fully fix broll-2 (the migration half is sound)
- Suggested fix: widen to `except (sqlite3.Error, OSError)` - the "newer
  user_version" `RuntimeError` stays deliberately uncaught either way.

### regression-3 - CR-242b/CR-242c cite the wrong finding ids, and dash-release-jobs-5 has no ledger entry at all
- Severity: low
- Confidence: CONFIRMED
- Where: `KNOWN_BUGS.md:18710` (CR-242b, labelled `dash-release-jobs-3`),
  `KNOWN_BUGS.md:18723` (CR-242c, labelled `dash-release-jobs-4`), and the same
  wrong id in the code comment at
  `dashboard/src/ccsync_dashboard/release_feed.py:1264`
- What: per `tally.txt`, dash-release-jobs-3 is the per-kind fleet cap race,
  -4 the `.sig` URL string concatenation, -5 the `FeedPoller.start()/stop()`
  idempotence. CR-242b describes -4's defect under -3's id and CR-242c
  describes -5's under -4's, so the ledger is shifted by one across two
  entries: -5 appears nowhere and -3's real fix (`db.claim_job`'s correlated
  `COUNT(*)`, `db.py:9293-9313`, correctly cited there) has no CR entry.
- Failure scenario: anyone auditing the fix pass by id - this hunt, the next
  one, or the shipping note - reads CR-242b as "the fleet cap race is fixed"
  and CR-242c as "the `.sig` URL is fixed", and cannot find -5 at all. All
  three fixes happen to exist in the code, so this costs nothing today and
  costs a re-hunt the first time one of them regresses.
- Evidence: `grep -an "^### CR-242" KNOWN_BUGS.md` against
  `docs/bug-hunt-2026-09-11/tally.txt`; `grep -n "dash-release-jobs-" release_feed.py`
  -> `:218` (2026-09-03's -5), `:1264` "dash-release-jobs-4 (2026-09-11): clear
  the event and drop the dead thread" (which is -5's fix).
- Ledger: CR-242b / CR-242c mislabel their findings; dash-release-jobs-5 unledgered
- Suggested fix: renumber the two ids in `KNOWN_BUGS.md` and in the
  `release_feed.py:1264` comment, and add the missing one-line CR for
  dash-release-jobs-3's `claim_job` change.

## Coverage note
