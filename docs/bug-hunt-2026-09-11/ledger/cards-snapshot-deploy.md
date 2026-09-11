## Timeline Cards deploys a COMMIT, not a working copy, 2026-09-11

The `/cards` mount is another repo's code (`E:\Projects\Editing`, subtree
`Resolve/MulticamPipeline`), shipped to `<host-root>/cards-web` by
`server/install_dashboard_app.py`. Until today the only thing keeping
unfinished edits out of that ship was operator discipline: a second checkout,
`E:\Projects\Editing-ship`, a detached git worktree moved to the commit being
deployed and `git clean`ed by hand. When the discipline held it worked; when
it did not, a working copy shipped, and either way nothing on the NAS said
which commit was live.

The deploy now takes the snapshot itself. `git archive <commit>:<subtree>`
contains the tracked files of one commit and nothing else - no untracked, no
dirty, no ignored, no `.git` - so the property that used to be a habit is now
a property of the tool.

### What changed

* `server/install_dashboard_app.py`
  * `export_cards_snapshot(src, ref)` - finds the git repo holding
    `[timeline_cards] src`, derives the subtree prefix from it (never
    hardcoded), verifies the ref, verifies the subtree exists at that commit,
    exports into a fresh temp directory and refuses an empty result. Each
    refusal is a sentence naming the ref and the repo, and it happens before
    anything on the NAS has moved.
  * `write_cards_marker` / `read_cards_marker` - `DEPLOYED_COMMIT` in the
    shipped tree (`commit`, `short`, `ref`, `repo`, `subtree`, `subject`,
    `committed`, `exported`, as `key=value` lines).
  * `resolve_cards_tree(args)` - the three-way decision: explicit directory
    override, snapshot (the default), or a named `src` that is not in a git
    repo, which still ships as a directory with a NOTE so a site whose Cards
    tree is a plain copy keeps its `/cards`.
  * `write_cards_deploy_record` / `cards_deploy_record_path` /
    `cards_head_moved_on` - the same facts at
    `~/.ccsync/state/cards_deployed.json` (best effort, like the snapshot
    log), because the drift doctor has no NAS shell.
  * `git_out`, `cards_repo_for` - small stdlib helpers; a missing git is an
    ordinary refusal, not a traceback.
  * CLI: `--cards-commit <ref>` (also `CARDS_COMMIT`) and `--cards-src-dir
    <path>` (also `CARDS_SRC`). Main's pre-flight prints the snapshot line,
    fails the deploy on a bad ref, and step 2g prints the installed commit and
    writes the local record.
* `tools/check_deploy_drift.ps1` - a new TIMELINE CARDS section: the deployed
  commit, its subject, when it shipped, and whether that ref has moved past it
  (with the re-ship command). No record is NOT CHECKED, never OK. It calls git
  through `&` rather than `cmd /c`, because cmd eats the caret in
  `main^{commit}` and the comparison then silently answers "cannot compare" -
  found by running it.
* `docs/CARDS_DEPLOY.md` - the worktree recipe is replaced by the snapshot
  one: the default, the `--cards-commit` pin, the refusals, the escape hatch,
  the marker, a re-deploy-the-old-commit rollback, a drift-doctor verify step,
  and a one-paragraph history note saying what `Editing-ship` was. The
  by-hand emergency route exports the commit too instead of rsyncing a
  checkout.
* `docs/CONFIG.md` (`DASH_CARDS_SRC`), `docs/DOCKER.md` (the mounts table),
  `site.example.toml` (`[timeline_cards] src` is a pointer now),
  `docs/PROJECTS_CLEANUP_PLAN.md` (the worktree is retired; the folder itself
  is the orchestrator's to remove).
* Tests: `server/tests/test_cards_snapshot.py` (new, 11 tests),
  `tools/tests/test_release_scripts.py` (a class for the doctor's section).

### How the operator deploys now

```powershell
.\tools\load_secrets.ps1
dashboard\.venv\Scripts\python.exe server\install_dashboard_app.py --dry-run
dashboard\.venv\Scripts\python.exe server\install_dashboard_app.py
```

That ships the `main` head of the Timeline Cards repo: commit in that repo
first, then run this. To pin another commit (a rollback, a branch under test):

```powershell
dashboard\.venv\Scripts\python.exe server\install_dashboard_app.py --cards-commit 8cac87f
```

To ship a directory as it stands (not a git checkout, or a working copy on
purpose): `--cards-src-dir <path>`, or `CARDS_SRC` in the shell. The container
still has to be restarted, which the deploy does.

### What still references Editing-ship

Nothing operational. Three places name it on purpose:

* `docs/CARDS_DEPLOY.md` - the history paragraph ("what this replaced").
* `docs/PROJECTS_CLEANUP_PLAN.md` - the folder-layout plan, now annotated as
  retired.
* `tools/tests/test_release_scripts.py` - an assertion that the drift doctor
  does NOT name it.

No script, no site file and no deploy path reaches for the worktree. It is
still on disk and was not removed here.

### How it was verified

* `server/tests/test_cards_snapshot.py`, 11 passed. Each test builds a
  throwaway git repo in `tmp_path` with a `Resolve/MulticamPipeline` subtree
  and a working copy that is mid-something (an uncommitted edit to
  `handler.py`, an untracked `experiment.py`, an ignored `scratch/`), and
  proves: the snapshot carries the COMMITTED `handler.py` and neither of the
  other two, nor `.git`; the marker parses back to the right commit, ref, repo
  and subtree; a ref that does not exist is refused in a sentence naming it
  and `--cards-commit`; a commit predating the subtree is refused naming
  `Resolve/MulticamPipeline`; a stubbed empty archive is refused; the explicit
  directory override still ships the working copy; a non-git `src` still
  ships; no named `src` is still silence; the local record round-trips and
  `cards_head_moved_on` names the new head once the repo moves on; an
  unwritable record is not a failed deploy.
* `tools/tests/test_release_scripts.py`, 61 passed (4 new).
* `tools/tests/test_bug_hunt_2026_09_11_server_tools.py`, 19 passed, and
  `server/tests/test_logic.py`, 28 passed - the two files nearest the changed
  code that were already green.
* `check_deploy_drift.ps1` run end to end against a fabricated record in the
  scratchpad, pointed at an unreachable dashboard so nothing live was touched:
  the OK branch (record == head) and the DRIFT branch (record three commits
  behind, "3 commits") both render. This is what caught the `cmd /c` caret.
* `py_compile` on every Python file touched; the PowerShell parser on
  `check_deploy_drift.ps1`; `--help` shows both new flags.

Not verified: a real deploy. Nothing here was run against the NAS.
