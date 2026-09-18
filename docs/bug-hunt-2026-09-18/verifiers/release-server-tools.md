# verdicts - release-server-tools

Scope: every finding in `hunters/dash-release-jobs.md` and
`hunters/server-tools.md`. Read-only pass; no repo state changed outside this
file. Cross-checked `tally.txt` (no other hunter reports any of this
territory) and `grep -an` on KNOWN_BUGS.md for each symptom.

## dash-release-jobs-1
- Verdict: CONFIRMED (medium), with two of the hunter's claims corrected
- Duplicate of: none
- Reasoning: the code reads exactly as reported. `finish_restart` ->
  `consume_restart_request` -> `_set_state` (`dashboard_update.py:1268`,
  `:551`) writes through the raw `_write_json`, not
  `_write_json_best_effort`, so an OSError on a full or read-only `/data`
  aborts before `_exit_process(RESTART_EXIT_CODE)`; the process then exits 0
  and `run.sh` does not re-exec the freshly swapped tree. CR-260g guarded only
  the healer's two writes, which is the read side of the same path, so the
  ledger entry does not close its own failure scenario. Two corrections to the
  report: (a) the OSError does NOT escape the lifespan - `app.py:809-811`
  wraps `finish_restart` in `try/except Exception` with `log.exception`, so
  the failure IS recorded, in the container log rather than the state file;
  (b) the trigger window is narrower than the write-up implies, because
  `preflight` has a free-space floor and every earlier step (extract, backup,
  `current.json`, `record.json`) writes to the same volume, so the disk has to
  fill (or fault read-only) between the swap and the SIGTERM shutdown. I kept
  medium anyway: the outcome is the applied code never starting while
  `current.json` already names it, which is the exact state CR-260g claims to
  have removed.
- Evidence: read of `_set_state`/`_fail_state` (`:551`, `:569` - both raw
  `_write_json`), `request_restart` (`:1264`), `finish_restart` (`:1290`) and
  the caller at `app.py:807-811`. The hunter's point about the two CR-260g
  regression tests is correct: `tests/test_bug_hunt_2026_09_11b_dash_release_jobs.py`
  exercises `read_state` with a dead `owner_pid` only, never `finish_restart`.
- Fix note: the suggested fix is right and safe - `consume_restart_request`
  must decide the exit code from the in-memory state and persist best effort.
  Also wrap `request_restart`'s `_set_state` and `_fail_state`'s write (a
  `_fail_state` that raises inside an `except` is the second half of this).
  A fix touches no other module, but `dashboard/tests/test_dashboard_update.py`
  (the `finish_restart` tests at :584/:588/:852) is where the new
  live-nonce + unwritable-state test belongs, and `app.py`'s `except` should
  stay - it is the last net, not the fix.

## dash-release-jobs-2
- Verdict: DOWNGRADED to low
- Duplicate of: none
- Reasoning: the mechanism is real and I could not refute it. `git_sha` and
  `git_dirty` are in neither `RECORD_FIELDS` (`release_trust.py:34-44`) nor
  `KIND_EXTRA_FIELDS`/`OPTIONAL_KIND_EXTRA_FIELDS` (`:64`, `:89`), so they are
  outside the Ed25519 canonical bytes, and `repair_provenance`
  (`release_feed.py:745-768`) writes both onto a locally published row on a
  bare sha256 match. The sha match proves only that the bytes agree; it says
  nothing about the two fields being copied, so the docstring's argument does
  not hold. I downgraded because nothing that decides behaviour moves: the
  signed fields, the version, `is_current` and the artefact are untouched, no
  code is installed or offered differently, and the worst outcome is an
  advisory `+dirty` chip cleared and a commit string rewritten on the Packages
  page - by an attacker who must already control the vendor feed host and who
  has far louder options there (a retraction suppression, a stale `current`).
  Real defect, cosmetic blast radius.
- Evidence: `grep -n "git_sha\|git_dirty" dashboard/src/ccsync_dashboard/release_trust.py`
  -> no match; `canonical_record` builds from `RECORD_FIELDS` + the kind
  extras only (`:101-105`); `tools/sign_release.py` adds the git pair to the
  record dict after signing.
- Fix note: the first suggested fix (restrict to rows with
  `published_by = 'release-feed'`) is the right shape and does not break the
  bug the function was written for only if those pre-2026-09-11 rows were in
  fact fed-published - worth checking before shipping it, or the repair stops
  repairing anything. The narrower alternative (only clear a `git_dirty` the
  `bool("0")` bug set, never write `git_sha`) is safer and needs no
  provenance column. A fix must also keep `api.py`'s human PUT publish route
  coercing the flag the same way `_feed_flag` does, or the two doors disagree
  (the hunter's own OUT OF TERRITORY note).

## dash-release-jobs-3
- Verdict: DOWNGRADED to low
- Duplicate of: none
- Reasoning: the code is as described - `published_assets`
  (`tools/publish_feed.py:746-758`) asks only for `\(.name)\t\(.size)` and the
  skip predicate is `held.get(p.name) == p.stat().st_size`
  (`:818-826`), with no asset `state`. The self-healing `--clobber` re-upload
  that used to cover an interrupted push is gone for any artefact this run did
  not itself sign. I could not verify the premise that GitHub leaves an
  interrupted asset at its declared size in state `starter` (the brief forbids
  touching GitHub and the feed), and that premise is the whole finding - a
  `starter` asset of a DIFFERENT size is re-uploaded by the existing predicate.
  The consequence is also fail-closed and traceable: a customer dashboard
  refuses the bytes with `FeedHashMismatch` and shows it as `last_error` on
  the feed page, rather than installing anything wrong. Low.
- Evidence: read of `published_assets`, `github_upload`'s `fresh`/`held`/
  `skipped` block and the `--clobber` argv that follows; `gh release view
  --json assets` does expose `state`, so the suggested jq change is available.
- Fix note: the fix is cheap and correct (`.state`, and treat only
  `uploaded` as held). `tools/tests/` pins `publish_feed`'s runner verb for
  verb, so the new `--jq` string and any extra `gh` call will need the feed
  tests updated in the same change; do not add a second `gh release view`
  call without checking those pins.

## dash-release-jobs-4
- Verdict: CONFIRMED (low), one claim corrected
- Duplicate of: none
- Reasoning: `channel_retractions` (`release_feed.py:474`) folds `platform`
  but leaves `kind` at `.strip()`, while `db.retract_package` ->
  `db.get_package` matches `kind` exactly against `companion_packages`, which
  stores it folded. So a recall entry spelled `Companion` un-currents nothing
  and `retract_package` returns False, which is indistinguishable from "we
  never published that" - nothing is logged either way. Correction: the
  hunter's second half is wrong. `_valid_records` builds both the `recalled`
  set and the record key with the RAW kind (`:519-524`), so a capitalised
  recall does still suppress a record spelled the same way; the two halves
  disagree only against the database. The entry also cannot be minted
  silently at the vendor end - `publish_feed.py:1101-1107` prints a NOTE when
  `--retract` matched no record on the channel - which is why I left it low.
- Evidence: read of `channel_retractions`, `apply_retractions`,
  `_valid_records` and `db.retract_package` (`db.py:4102-4127`);
  `tools/publish_feed.py:1084-1110` shows `--retract` takes the kind
  free-form from the command line with no folding or choices check.
- Fix note: folding `kind` in `channel_retractions` is right, but fold it in
  `publish_feed.note_retracted`/`retract_record` too, or the vendor keeps
  publishing the unfolded spelling and older dashboards still miss it. The
  suggested warning log is the valuable half. Check
  `dashboard/tests/test_release_feed.py`'s recall tests - they use canonical
  spellings, so nothing pins the old behaviour.

## dash-release-jobs-5
- Verdict: CONFIRMED (low), with the hunter's scenario replaced
- Duplicate of: none
- Reasoning: the arithmetic at `dashboard_update.py:1384` does blank
  `previous` when `previous == version`, and `""` means "the image" to both
  `rollback` (`:1463`) and `select_code_root.py`. But the hunter's scenario -
  "apply 0.7.49, apply 0.7.49 again" - is unreachable: `preflight` refuses
  with 409 "this dashboard is already running {version}" (`:674-675`), and
  `force` does not bypass it. The defect survives on a narrower path: after a
  swap whose restart did not happen (finding 1) or a boot that fell back to
  the image, the running `VERSION` is not `current.json`'s version, so
  re-applying the version `current.json` already names passes preflight and
  discards the real previous tree's name. Low stands.
- Evidence: read of `preflight` (`:658-680`), `apply`'s `current.json` write
  (`:1378-1395`) and `rollback` (`:1441-1470`), which falls back to
  `current.get("previous")` and treats "" as the image.
- Fix note: carrying the existing `previous` forward when
  `previous == version` is correct and touches nothing else; the trees
  themselves are still on disk (`prune_code_trees` keeps them), so the
  rollback target is recoverable by name today, which is the other reason this
  is low.

## dash-release-jobs-6
- Verdict: REFUTED
- Duplicate of: none
- Reasoning: the inconsistency is real (`cli_tools.py:1035` calls
  `spec(name).label` inside the handler, while `_unexpected` and
  `install_supported` use the guarded `TOOLS[name].label if name in TOOLS`
  form), but the failure needs `name not in TOOLS` inside a running worker
  thread, and that cannot happen. `TOOLS` is a module-level dict built at
  import and never mutated; the route validates with `_tool(name)`
  (`:1924-1928`, 404) and `start_install` re-validates with `spec(name)` on
  the request thread (`:984`) before the thread is created. The hunter's
  reachability story - "a partial deploy swapping the module under a running
  thread" - does not apply to CPython: a dashboard code update replaces files
  on disk and re-execs the process; the loaded module object a running thread
  holds is not swapped. No reachable input reaches the raise.
- Evidence: `grep`ed every caller of `start_install`/`_install_worker` (only
  `api_install` at `:2004`, which calls `_tool(name)` first); read `spec`
  (`:284-288`) and the `TOOLS` literal (`:167-179`).
- Fix note: the suggested change is harmless hygiene and I would take it as a
  one-line tidy, not as a bug fix; no test pins the current text beyond
  `tests/test_bug_hunt_2026_09_11b_cr266a_cli_tools.py`, which asserts the
  message shape and would need the label source left identical.

## server-tools-1
- Verdict: CONFIRMED (medium)
- Duplicate of: none (related to the OPEN CR-5, which this finding partly
  contradicts rather than repeats)
- Reasoning: every element checks out. `dashboard/deploy/requirements.lock`
  carries `psycopg2-binary==2.9.12`, the allowlist entry excuses it for
  `dashboard-container` while asserting the notice/licence text/written offer
  are "tracked in docs/legal/THIRD_PARTY_NOTICES.md", and that file has no
  psycopg2 row anywhere. `gen_notices.py --check` exists (`:349`) and its own
  header advertises it, but no workflow, no `ship.ps1`/`ship_gates.ps1`/
  `release.ps1` step and no test invokes it - `tools/tests/test_gen_notices.py`
  exercises `render`/`existing_hand_block` as pure functions against fixtures.
  So the only running gate passes on a promise written in a TOML file. It also
  makes KNOWN_BUGS CR-5's "`--check` as a CI gate" (`:499`) untrue, which is
  the ledger half of the finding.
- Evidence: `grep -n psycopg2 dashboard/deploy/requirements.lock` ->
  `2.9.12`; `dashboard/requirements.lock` -> `2.9.13`;
  `grep -n psycopg2 docs/legal/THIRD_PARTY_NOTICES.md` -> no match;
  `grep -rn gen_notices .github/workflows/ tools/*.ps1 tools/tests` -> only
  the `run_all_tests.ps1` comment and the unit test.
- Fix note: the suggested fix is right but incomplete on its own - adding
  `gen_notices.py --check` to `ci.yml` will fail the build until the file is
  regenerated, and regenerating it from the five component VENVS still prints
  2.9.13 rather than the 2.9.12 the container installs. So the change has to
  land together: `tools/gen_notices.py` (a lock-scanned `dashboard/deploy`
  component, or an honest header), the regenerated
  `docs/legal/THIRD_PARTY_NOTICES.md`, `.github/workflows/ci.yml`, and the
  CR-5 text in KNOWN_BUGS.md. `tools/tests/test_gen_notices.py` will need a
  case for whichever new inventory source is added.

## server-tools-2
- Verdict: CONFIRMED (medium)
- Duplicate of: none
- Reasoning: `publish_db.py:843-857` prints the WARNING and falls through to
  `return 0`, so a publish whose post-swap drain merge failed reports success
  to every scripted caller. The contrast the hunter draws is exact:
  `do_apply_drain` (`:625-631`) returns 1 for the identical `why` from the
  identical `apply_drain` call. And `test_broll_drain.py:426-440` feeds an
  `rc 5` "database is locked" merge and asserts `rc == 0`, so the suite pins
  the wrong answer rather than protecting the right one. The data at stake is
  real: `ingest_batches`/`ingest_items` exist only in the bundle until the
  merge lands.
- Evidence: read of both branches and of the test; the FakeBackend exec list
  shows the merge is the third exec, after the rename.
- Fix note: a distinct non-zero code is the right call (exit 1 already means
  "nothing was published" elsewhere in this CLI, so reusing it would mislead
  a caller that distinguishes). Any fix must change
  `server/tests/test_broll_drain.py:426-440` in the same commit, and check
  `docs/INDEXERS.md` / `docs/BACKUP_RESTORE.md` for any documented `&&` chain
  that would newly stop on the non-zero code.

## server-tools-3
- Verdict: CONFIRMED (low)
- Duplicate of: none
- Reasoning: `check_health.py:311` passes `text=True` with no `encoding=`, so
  the decode uses the process locale. I measured it on the interpreter this
  repo actually uses. The broad `except Exception` at `:312` then renders a
  hard decode failure as "skipped", which silently removes check 2b (the
  DERP-vs-direct probe) from a run that still exits 0 - a check that did not
  run reported as a check that was skipped for an environmental reason.
  Same class as the `git_out` fix in e050413, and the two neighbouring
  subprocess calls in the same tree already carry the encoding.
- Evidence: `dashboard/.venv/Scripts/python.exe` is 3.12.10 with
  `locale.getencoding() == 'cp1252'`, and
  `'母母女子'.encode('utf-8').decode('cp1252')` raises
  `UnicodeDecodeError: 'charmap' codec can't decode byte 0x8d`. A CJK peer
  name is therefore a raise, not a mis-decode, on this rig.
- Fix note: `encoding="utf-8", errors="replace"` is correct and cannot
  regress anything (tailscale emits UTF-8 JSON by contract). Doing the same to
  `tools/gen_notices.py`'s three `pip-licenses` calls is a good idea but is a
  separate file with its own tests; keep the two changes reviewable.

## server-tools-4
- Verdict: CONFIRMED (low)
- Duplicate of: none
- Reasoning: the code path is certain - `_rclone_common.remote_listing:211-219`
  decodes `rclone lsjson -R` (which contains every remote path) with the
  console codec and catches only `TimeoutExpired`/`OSError`, so the
  `UnicodeDecodeError` raised inside `subprocess.run` escapes the function
  that documents `None` as its failure answer. `base.run_subprocess:138-143`
  has the same shape with no guard at all. I kept it low rather than raising
  it: `bench/` is the ad-hoc harness, it runs nothing in the field, and the
  worst outcome is a crashed or falsely failed benchmark - no fleet data
  moves on this path.
- Evidence: same measurement as server-tools-3 (cp1252 raises on the fleet's
  own `母母女子`); read of the `except` tuple and of the docstring's promise.
- Fix note: `encoding="utf-8", errors="replace"` on all four call sites plus
  widening the `except` to `ValueError` is right. Note the widening is what
  actually matters: with `errors="replace"` the decode no longer raises but
  the paths silently become U+FFFD, which would then read as "every file is
  missing" from `verify_upload` - so do both, not one.

## server-tools-5
- Verdict: CONFIRMED (low)
- Duplicate of: none
- Reasoning: `ship_dashboard_docs` (`install_dashboard_app.py:4466-4473`)
  builds `missing` from `SHIPPED_DOCS` + `SHIPPED_DOC_TREES` together and
  returns False on any member, so an absent `EDITOR_SETUP.md` - promoted into
  `SHIPPED_DOCS` at `:307` in the 09-11b pass - now also withholds the
  `legal/` tree the first-run wizard gates on. The coupling is real and was
  not the subject of the change that created it. Reachability is what keeps it
  low: I checked `tools/make_product_repo.ps1` and its prune list strips the
  bug-hunt and plan documents, not `EDITOR_SETUP.md`, and the image build
  would fail its own `COPY` before reaching here - so this needs a hand-
  trimmed bind-mode checkout.
- Evidence: read of `:300-310` (the SHIPPED_DOCS comment naming dash-core-6)
  and `:4466-4490`; `grep -n docs tools/make_product_repo.ps1` shows no
  EDITOR_SETUP removal.
- Fix note: "ship what is present, NOTE what is not, refuse only for the
  legal tree" is the right shape. It must stay in step with
  `dashboard/src/ccsync_dashboard/published_docs.py` REQUIRED_DOCS (the
  comment at `:300` says the two lists are hand-synchronised) and with
  `dashboard/deploy/Dockerfile`'s COPY, or bind mode and image mode would
  disagree about which absence is fatal.

## Notes
- No finding in this group is a duplicate of another hunter's: `tally.txt`
  has no other entry touching `release_feed.py`, `dashboard_update.py`,
  `publish_feed.py`, `cli_tools.py`, `publish_db.py`, `check_health.py`,
  `bench/` or the notices generator.
- KNOWN_BUGS.md was grepped (`-an`) for each symptom: nothing open covers
  them. The one overlap is CR-5, whose text asserts the notices gate that
  server-tools-1 shows does not exist.
