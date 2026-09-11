# Tidying E:\Projects, and renaming this repo to `ccsync`

**REVISED TARGET, 2026-09-11 afternoon (owner's ruling, supersedes section 2 below):** the
categories are the FIVE EXISTING repos `Editing`, `Compositing`, `3D`, `Personal`,
`Utilities`, plus a new `legacy\` for everything retired or superseded; `ccsync` goes
INSIDE `Editing` (`E:\Projects\Editing\ccsync`), `AE Scripts` moves from Editing to
Compositing, and there is no `video\` / `writing\` / `tools\` layer. Done the same
afternoon: AE Scripts (committed in both repos, `Launcher\tools.json` repointed),
Scriptwriting into Editing, `_tools` into Utilities, broll-platform and music-tagger
into `legacy\` (music venv deleted), Editing-ship2 removed, `_worktrees` removed,
`E:\Projects\README.md` rewritten, footage-sorter into Editing (its own web server and
the Auto Backup tray were what held it open; both relaunched from the new path, the
Startup shortcut repointed), `E:\Projects\CLAUDE.md` written so future sessions file new
work into a category. Still owed: the ccsync move itself:
`E:\Projects\move-ccsync-into-editing.ps1` run from `E:\` with every session in ccsync
closed, then the same script with `-RebuildVenvs`, then the gate. The repo's own path
references already say `E:\Projects\Editing\ccsync`. Editing-ship stays until the
snapshot-based Cards deploy is verified, then `git worktree remove`. (That deploy is
BUILT as of 2026-09-11 - `server\install_dashboard_app.py` exports a commit with
`git archive` and nothing in this repo reaches for the worktree any more:
`docs\CARDS_DEPLOY.md`. The folder itself is still on disk and is the orchestrator's
to retire.)

**Status of the FIRST rename, 2026-09-11 morning (phases 0-4 complete: the folder became `E:\Projects\ccsync`, the Claude
memory directory and project key moved, the tray's rclone path and the global CLAUDE.md fixed,
tray restarted). Phase 5 (venv rebuild) and the gate followed the same day; section 9 is
still untouched.** Earlier progress note: Done the same day: 3.1 (no history
found on GitHub; CLAUDE.md and music/SPEC.md corrected), 3.2 (footage-sorter
committed and pushed to a new private GitHub repo), 3.3 (broll-platform pushed
with an upstream), Utilities' stray commit pushed, and section 6 items 3a-3d, 4
(task deleted, watchdog fallback edited), 6, 7 and 8 (the in-repo path sweep,
archives excluded), all applied against the FUTURE path. NOT done: the rename
itself and everything keyed on it (phases 0-5), because the session that ran
this plan had its own working directory inside the repo, and Windows refuses to
rename a folder a process is standing in. The hand-over is one script,
`E:\Projects\rename-to-ccsync.ps1`: close every Claude Code session in the
repo, open PowerShell at `E:\`, run it (phases 0-4 in one go; it stops and
restarts the tray), then run it again with `-RebuildVenvs` (phase 5, six venvs
including the new `broll\web\.venv`), then the gate. 3.4's checkpoint commit
was deliberately NOT made (owner's call: run the plan before committing).
Section 9, the categorisation moves, is untouched, per its own "live with the
rename first" rule.

It covers two jobs that are best done in one order but are separable:

- **(a)** rename `E:\Projects\resolve-remote-sync` to `E:\Projects\Editing\ccsync`;
- **(b)** sort the rest of `E:\Projects` into a small set of category folders.

Everything here rests on the survey taken on 2026-09-11 (inventory, sizes, git
state, every path reference that breaks on a move, and what each virtual
environment records about where it lives). Where this plan asserts a file and a
line number, that came from the survey and was spot-checked against the repo on
the same day.

---

## 1. Why

**The folder name no longer matches the product.** Everything in it, every
document, the tray app, the dashboard, the installer and the release feed call
it **CC Sync**. `resolve-remote-sync` is the name the very first version had,
when it was one script that pulled a Resolve project down from the NAS. You type
the path several times a day, and it is the name that shows up in every session
transcript and memory file.

**The rest of `E:\Projects` has grown a flat list of fifteen entries** that mixes
four different kinds of thing: live products, discipline folders, downloaded
toolchains, and leftovers (`_worktrees` is an empty shell; `Build Command.txt`
is a loose note). A flat list is fine at six entries and confusing at fifteen.

**What makes the rename worth planning rather than just doing:** five things on
this machine hold the old absolute path and fail *silently* if they are not
fixed. The worst of them is the running tray app, which would stop being able to
find `rclone.exe` and therefore stop syncing, without saying anything that names
the cause. That is the whole reason this document exists.

---

## 2. The target tree

```
E:\Projects\
├── ccsync\                     the product. Stays at the top level: it is what
│                               you open every day, and dozens of documents,
│                               tools and memory files name its path.
│
├── video\                      everything that makes a video
│   ├── Editing\                the video-post monorepo (Resolve, Rendering,
│   │                           AE Scripts, Catalog, Transcripts, Launcher).
│   │                           Timeline Cards lives inside it.
│   ├── Editing-ship\           a git worktree of Editing, used to stage a
│   │                           Timeline Cards deploy until 2026-09-11, when
│   │                           the deploy started exporting the commit itself
│   │                           (docs\CARDS_DEPLOY.md). Retired; nothing needs
│   │                           it, and moving it needs 5.4's repair.
│   ├── Editing-ship2\          the same, one week staler.
│   ├── footage-sorter\         sorts W:\Temp Transfer into project folders.
│   │                           Video ingest, so it belongs here.
│   ├── Compositing\            globe-studio / TERRA, a map-animation tool that
│   │                           exports to Resolve. Video output, video folder.
│   └── 3D\                     Blender automation + AutoTracker (matchmove).
│                               5.2 G of real scene data; not dead, just quiet.
│
├── writing\                    words, not pictures
│   ├── Scriptwriting\          AutoScriptTranslation, the screenplay splitter.
│   └── Personal\               Toughbuilt Boxes planner, imdb-page-plan.
│                               Not video work; this is where it stops being
│                               in the way.
│
├── tools\                      things other projects depend on
│   ├── Utilities\              FleetView, yt-credit-downloader, Auto-Backup,
│   │                           Aria2, Admin, ASCII-Video, AutoFormat.
│   └── _tools\                 android-sdk, jdk17, deno. A downloaded
│                               toolchain, not a project. Keeps its underscore
│                               so it sorts first inside tools\.
│
├── archive\                    finished, kept for history only
│   ├── broll-platform\         folded into ccsync\broll\ on 2026-08-10. Kept
│   │                           for its pre-fold git history.
│   └── music-tagger\           folded into ccsync\music\ on 2026-08-10. See
│                               the loose end in 3.1 - it has no history left.
│
└── README.md                   the index of the tree. Stale since 2026-06-28;
                                rewrite it as the last step of (b).
```

Deleted on the way: **`E:\Projects\_worktrees\`** (empty, and the three
documents that name it are already pointing at nothing).
Moved on the way: **`E:\Projects\Build Command.txt`** into `E:\Projects\Editing\ccsync\`
(it is a ship command for this repo; it uses a relative path, so it works
wherever it sits, but it should not sit at the top of the tree).

Top-level count goes from 15 entries to 6. That is the point.

> ### Challenge: "archive the four one-commit repos"
>
> The brief suggested `archive\` should hold the four repos whose only commit is
> "Initial commit" (`3D`, `Compositing`, `Personal`, `Scriptwriting`). I have
> not planned it that way, and I think that reading is wrong for two of them.
> "One commit" here means the *tracked* content is one commit; `3D` holds 5.2 G
> of untracked scene and video data for AutoTracker, and `Compositing` holds a
> working tool. Quiet is not dead. Archiving them would make an active thing
> harder to find in order to make the top level look tidier, and you would still
> have to go into `archive\` to use them.
>
> What I have put in `archive\` instead is the two folders that genuinely are
> finished: `broll-platform` and `music-tagger`, both superseded by folders
> inside `ccsync` on 2026-08-10.
>
> If you disagree, the change is one line each in the move script in section 9,
> and nothing else in this plan depends on it. Say the word and all four go to
> `archive\`.

> ### Challenge: three top-level folders would be enough
>
> `writing\` holds two small, idle repos (553 KB between them). A folder for
> 553 KB is arguably ceremony. The alternative is `archive\writing\`, or just
> leaving both where they are. I have kept `writing\` because you asked for
> categories and because "where do I put the next script tool" should have an
> answer. It is the cheapest thing here to change your mind about later.

---

## 3. Pre-flight: three loose ends and one dirty tree

**None of these are caused by the move. All of them get worse if a move happens
first.** Do this section on a day when nothing else is running.

### 3.1 `music-tagger` has no git history at all - OWNER DECISION

Both `E:\Projects\resolve-remote-sync\CLAUDE.md` and `music\SPEC.md:11` state
that the pre-fold history "stays in `E:\Projects\music-tagger`". It does not.
The folder has no `.git` directory: it is 5.2 G of which 5.2 G is `.venv`, plus
about 24 loose `.py` files. There is no history there to preserve.

Check it yourself:

```powershell
Test-Path E:\Projects\music-tagger\.git
```

Expect `False`. (If it says `True`, the survey was wrong and you can skip the
rest of this item.)

Two honest options, and you have to pick one:

- **Look for it.** If a copy exists on another disk, the NAS, or GitHub, that is
  the history and it should be put back before anything moves. Search:
  `gh repo list The-Creators-Club --limit 100` and look for `music-tagger`.
- **Correct the documents.** If it is gone, it is gone, and two documents that
  claim otherwise are worse than no claim. An agent can change the sentence in
  `CLAUDE.md` and in `music/SPEC.md:11` to say the pre-fold history was not
  preserved.

Either way the folder itself is safe to move; only the 5.2 G venv inside it
argues for deleting rather than moving (see 9.3).

### 3.2 `footage-sorter` exists on this disk only - OWNER

No git remote at all. 63 tracked files, 49 dirty entries, 31 untracked. If this
drive dies tonight, that project is gone, move or no move.

```powershell
cd E:\Projects\footage-sorter
git status
git add -A
git commit -m "footage-sorter: checkpoint before the E:\Projects reorganisation"
gh repo create The-Creators-Club/footage-sorter --private --source . --remote origin --push
```

Expect the last line to print a `https://github.com/...` URL. Check it worked:

```powershell
git -C E:\Projects\footage-sorter remote -v
git -C E:\Projects\footage-sorter status -sb
```

Expect a remote named `origin`, and a first line reading `## master...origin/master`
with no `[ahead N]`.

You have to do this one: `gh repo create` needs your GitHub account.

### 3.3 `broll-platform` is 7 commits ahead of its remote - OWNER

On branch `ff4-own-footage`, with no upstream set, plus one dirty entry. Those
seven commits are on this disk only.

```powershell
cd E:\Projects\broll-platform
git status
git add -A
git commit -m "broll-platform: checkpoint before the E:\Projects reorganisation"
git push -u origin ff4-own-footage
```

Expect `branch 'ff4-own-footage' set up to track 'origin/ff4-own-footage'`.
Check: `git -C E:\Projects\broll-platform status -sb` shows no `[ahead N]`.

### 3.4 This repo has 170 dirty entries - OWNER

A fix wave was in flight when the survey ran. **Commit or stash it before
anything moves**, so that if something goes wrong afterwards you can tell a
mistaken move from a mistaken edit.

```powershell
cd E:\Projects\resolve-remote-sync
git status
git add -A
git commit -m "checkpoint before the ccsync rename"
git push
```

Check: `git -C E:\Projects\resolve-remote-sync status -sb` prints
`## main...origin/main` and nothing else.

Also worth doing while you are here (both are one commit each, and both are
"ahead" of their remotes): `E:\Projects\Editing` has 3 dirty entries, and
`E:\Projects\Utilities` has 18 dirty entries and 1 unpushed commit.

### 3.5 End the borrowed venv (do this BEFORE the move, it is independent)

`broll/web`'s test suite, the licence gate and the third-party notices
generator all reach into `E:\Projects\broll-platform\web\.venv` - another repo's
virtual environment. That borrow is why moving `broll-platform` into `archive\`
would quietly shrink what the licence gate covers. `broll/web` already has its
own `requirements.lock`, so ending the borrow is easy and is worth doing on its
own merits.

An agent can do all of this:

```powershell
C:\Users\alex\AppData\Local\Programs\Python\Python312\python.exe -m venv E:\Projects\resolve-remote-sync\broll\web\.venv
E:\Projects\resolve-remote-sync\broll\web\.venv\Scripts\python.exe -m pip install --disable-pip-version-check --require-hashes -r E:\Projects\resolve-remote-sync\broll\web\requirements.lock
```

Then four references change from the borrowed path to the new one (exact
current text in the table in section 6, rows 3a to 3d):
`tools\run_all_tests.ps1:74`, `tools\check_licenses.py:163`,
`tools\gen_notices.py:61`, and the `broll/web` row of `CLAUDE.md`'s test table.

Check it worked:

```powershell
cd E:\Projects\resolve-remote-sync\broll\web
.venv\Scripts\python.exe -m pytest tests -q
```

Expect a green run, with `test_mounted_prefix.py` among the tests that ran (it
is the one that is silently skipped when there is no interpreter).

**Owner time for section 3: 20 to 40 minutes**, most of it waiting for two
pushes. The agent can prepare every command and run 3.5; the two `gh`/`git push`
steps are yours.

---

## 4. Is the GitHub repo renamed too? Recommendation: not now

The folder name and the GitHub repository name are separate decisions. The
GitHub repo is `https://github.com/The-Creators-Club/resolve-remote-sync.git`.

**What I checked, and what it means:**

| Question | Answer |
|---|---|
| Do the CI workflows contain the repo name or any `E:\Projects` path? | **No.** None of `android.yml`, `ci.yml`, `image.yml`, `release-dashboard.yml`, `release-macos.yml`, `release-windows.yml` mentions either. CI is path-agnostic and name-agnostic. |
| Does the vendor release feed embed the repo name? | **No - and this is the important one.** The feed lives in a *different* repository. `tools/publish_latest.py:46` sets `FEED_REPO = "The-Creators-Club/ccsync-releases"`, and `tools/ship.ps1:200` defaults `$FeedRepo` to the same. Every customer-facing URL is `https://github.com/The-Creators-Club/ccsync-releases/releases/download/ccsync-releases-v1/...`. Renaming the source repo does not touch a single signed URL. |
| Does anything else hardcode `OWNER/REPO` for the source repo? | `tools/publish_feed.py` takes it as a command-line argument and never guesses. `publish_latest.py` uses `gh run list`, which resolves the repo from the local git remote, and GitHub redirects an old name to the new one. |
| Is the name recorded anywhere on this machine? | `C:\Users\alex\.claude.json` mentions `the-creators-club/resolve-remote-sync`. Cosmetic. |

**So renaming the GitHub repo is cheap** - cheaper than the survey expected,
because the feed is a separate repository. GitHub keeps redirecting the old name
for clones, fetches, pushes and web links indefinitely, and every existing
`git remote` keeps working.

**Recommendation: rename the folder now, and leave the GitHub repo alone for at
least one full release cycle.** Not because renaming is expensive, but because
this plan already changes five things that fail silently, and there is no reason
to add a sixth variable to the same afternoon. Once you have shipped one release
from `E:\Projects\Editing\ccsync` and it went normally, rename the repo on GitHub
(Settings, Repository name, `ccsync`) and then run, once:

```powershell
cd E:\Projects\Editing\ccsync
git remote set-url origin https://github.com/The-Creators-Club/ccsync.git
git fetch origin
```

Expect `git fetch` to complete silently. Nothing else changes.

---

## 5. The rename, step by step

Phases run in this order. Do not start a phase until the previous one's check
passed.

### 5.1 Phase 0 - stop everything that holds the folder open - OWNER

1. **Quit the CC Sync tray.** Right-click the CC Sync icon in the system tray,
   choose Quit. Confirm it is gone:

   ```powershell
   Get-Process ccsync-companion -ErrorAction SilentlyContinue
   ```

   Expect no output. (If a `--supervise` process relaunches it, quit again from
   the tray menu - the supervisor stands down after a real Quit and only
   relaunches a companion that *crashed*.)

2. **Close every Claude Code session whose folder is inside the repo**, and any
   running test gate. A file handle in `dashboard\.venv` is enough to make
   `Rename-Item` fail with "being used by another process".

3. **Close any editor, Explorer window or terminal sitting inside the folder.**

Check nothing holds it:

```powershell
Rename-Item E:\Projects\resolve-remote-sync E:\Projects\resolve-remote-sync.test
Rename-Item E:\Projects\resolve-remote-sync.test E:\Projects\resolve-remote-sync
```

If both lines are silent, the folder is free. If the first errors, something is
still open; the message names the folder, not the process, so the usual culprit
is a terminal whose current directory is inside it.

**Owner time: 5 minutes.**

### 5.2 Phase 1 - rename the Claude Code memory directory FIRST

**This must happen before any Claude Code session opens in the new path.**
Claude Code derives its per-project directory name from the folder path. The
first time a session starts in `E:\Projects\Editing\ccsync`, it creates a fresh, empty
`E--Projects-ccsync` directory, and your 100 memory files stay stranded under
the old name.

```powershell
Rename-Item "C:\Users\alex\.claude\projects\E--Projects-resolve-remote-sync" "E--Projects-ccsync"
```

Check it: the new directory should hold `memory\MEMORY.md` and about 126
entries.

```powershell
(Get-ChildItem "C:\Users\alex\.claude\projects\E--Projects-ccsync").Count
Test-Path "C:\Users\alex\.claude\projects\E--Projects-ccsync\memory\MEMORY.md"
```

Expect a count around 126 and `True`.

Then the project entry keyed by path in `C:\Users\alex\.claude.json`. Check
whether it exists:

```powershell
(Get-Content C:\Users\alex\.claude.json -Raw | ConvertFrom-Json).projects.PSObject.Properties.Name | Select-String "resolve-remote-sync"
```

Expect one line: `E:/Projects/resolve-remote-sync`. That key holds 31
per-project flags and statistics (`hasTrustDialogAccepted`, `lastSessionId`,
`lastCost`); `allowedTools`, `mcpServers` and `history` are all empty. **Losing
it costs one re-trust prompt and nothing else.** An agent can rename the key
in place (forward slashes, not backslashes: `E:/Projects/Editing/ccsync`), or you can
simply accept the trust prompt next time. Back the file up first either way:

```powershell
Copy-Item C:\Users\alex\.claude.json "C:\Users\alex\.claude.json.bak-$(Get-Date -Format yyyyMMdd)"
```

Two other directories are named after the old path and are safe to leave or
delete: `C:\Users\alex\.claude\projects\E--Projects-resolve-remote-sync--claude-worktrees-agent-*`
(two stale agent worktrees) and the 3.4 G scratchpad at
`C:\Users\alex\AppData\Local\Temp\claude\E--Projects-resolve-remote-sync\`.
The scratchpad is temporary files only; deleting it reclaims 3.4 G.

### 5.3 Phase 2 - the rename itself

```powershell
Rename-Item E:\Projects\resolve-remote-sync E:\Projects\Editing\ccsync
```

Silent means it worked. Check:

```powershell
Test-Path E:\Projects\Editing\ccsync\CLAUDE.md
git -C E:\Projects\Editing\ccsync status -sb
```

Expect `True`, and `## main...origin/main` with a clean tree. Git itself does
not care where a repository lives; no repair is needed for `ccsync`.

**This is the reversible point.** Until the venvs are deleted in phase 5,
renaming back restores the previous state exactly.

### 5.4 Phase 3 - repair the Editing worktrees (only when `Editing` moves)

This does not apply to the `ccsync` rename at all - `ccsync` has no worktrees.
It applies in section 9, when `Editing`, `Editing-ship` and `Editing-ship2` move
into `video\`.

A worktree stores absolute paths in two directions: the worktree's `.git` is a
*file* containing `gitdir: E:/Projects/Editing/.git/worktrees/Editing-ship`, and
the main repo's `.git\worktrees\Editing-ship\gitdir` points back. Moving either
end breaks both. Git has one command for exactly this, run from the main repo
after everything is in its final place:

```powershell
cd E:\Projects\video\Editing
git worktree repair E:\Projects\video\Editing-ship E:\Projects\video\Editing-ship2
```

Expect either no output, or lines reading `repair gitdir file for ...`. Check:

```powershell
git -C E:\Projects\video\Editing worktree list
git -C E:\Projects\video\Editing-ship status -sb
```

Expect the list to show all three at their new paths, and the `-ship` status to
report a detached HEAD without complaining about a missing git directory.

### 5.5 Phase 4 - fix the five things that break

This is section 6. Do it immediately, in the order given there: item 2 (the
tray's rclone path) is the one that costs you syncing if it is forgotten.

### 5.6 Phase 5 - the venvs, LAST

Deleting the five virtual environments is what makes the rename irreversible, so
it comes after section 7's verification has passed **and** after you have run
one full test gate in the new location using the not-yet-deleted venvs.

Background, because it explains why the order is this way: a moved venv is not
completely broken. `Scripts\python.exe -m pytest` keeps working, because
`pyvenv.cfg` is found relative to the executable. What breaks is `activate`,
`activate.bat`, `Activate.ps1` and **every `Scripts\*.exe` console-script
launcher**, all of which have the old absolute path written into them.
CC Sync's documented test commands are all the surviving form; PyInstaller,
which `tools\release.ps1` and `build_editor_package.ps1` drive, is the form that
does not survive. Two venvs elsewhere in this tree (`Resolve_MCP`,
`yt-credit-downloader`) have already been moved once and are still in service in
exactly that half-working state, which is worth knowing but is not a reason to
leave five more like it.

Recreate all five from their hash-pinned lockfiles, **dashboard first** (it is
the substitute interpreter for `server\`, `ytdl\web` and `tools\`):

```powershell
$py = "C:\Users\alex\AppData\Local\Programs\Python\Python312\python.exe"

# 1. dashboard - do this one first
Remove-Item -Recurse -Force E:\Projects\Editing\ccsync\dashboard\.venv
& $py -m venv E:\Projects\Editing\ccsync\dashboard\.venv
E:\Projects\Editing\ccsync\dashboard\.venv\Scripts\python.exe -m pip install --disable-pip-version-check --require-hashes -r E:\Projects\Editing\ccsync\dashboard\requirements.lock

# 2. companion
Remove-Item -Recurse -Force E:\Projects\Editing\ccsync\companion\.venv
& $py -m venv E:\Projects\Editing\ccsync\companion\.venv
E:\Projects\Editing\ccsync\companion\.venv\Scripts\python.exe -m pip install --disable-pip-version-check --require-hashes -r E:\Projects\Editing\ccsync\companion\requirements.lock

# 3. music/web - deliberately torch-free, do not "fix" that
Remove-Item -Recurse -Force E:\Projects\Editing\ccsync\music\web\.venv
& $py -m venv E:\Projects\Editing\ccsync\music\web\.venv
E:\Projects\Editing\ccsync\music\web\.venv\Scripts\python.exe -m pip install --disable-pip-version-check --require-hashes -r E:\Projects\Editing\ccsync\music\web\requirements.lock

# 4. onboarding
Remove-Item -Recurse -Force E:\Projects\Editing\ccsync\onboarding\.venv
& $py -m venv E:\Projects\Editing\ccsync\onboarding\.venv
E:\Projects\Editing\ccsync\onboarding\.venv\Scripts\python.exe -m pip install --disable-pip-version-check --require-hashes -r E:\Projects\Editing\ccsync\onboarding\requirements.lock

# 5. bench
Remove-Item -Recurse -Force E:\Projects\Editing\ccsync\bench\.venv
& $py -m venv E:\Projects\Editing\ccsync\bench\.venv
E:\Projects\Editing\ccsync\bench\.venv\Scripts\python.exe -m pip install --disable-pip-version-check --require-hashes -r E:\Projects\Editing\ccsync\bench\requirements.lock
```

Every one of those five records `C:\Users\alex\AppData\Local\Programs\Python\Python312\python.exe`
(Python 3.12.10) as its creator, which is why one `$py` serves all of them. The
`--require-hashes` flag is what CI uses, and it is what makes a lockfile mean
anything: if a package's bytes do not match the hash in the lock, pip refuses
rather than installing something else.

Three of them (`bench`, `companion`, `dashboard`) previously also had the repo
installed in editable mode. CI does not do that and its suites pass, because
pytest is run from the component directory and puts the in-repo package first on
`sys.path`. If a suite reports `ModuleNotFoundError` for its own package after
the rebuild, add the editable install for that one component:

```powershell
cd E:\Projects\Editing\ccsync\dashboard
.venv\Scripts\python.exe -m pip install --no-deps -e .
```

Check each venv: `.venv\Scripts\python.exe -m pytest --version` prints a
version, and `.venv\Scripts\Activate.ps1` no longer mentions the old path:

```powershell
Select-String -Path E:\Projects\Editing\ccsync\*\.venv\Scripts\activate.bat -Pattern "resolve-remote-sync"
```

Expect no output.

**Agent time for phase 5: 20 to 40 minutes of downloading and installing.**
Nothing in it needs you.

---

## 6. What breaks, and the fix for each

Ordered by how silently it fails. Every "new value" below assumes the folder is
now `E:\Projects\Editing\ccsync`.

| # | What | Exactly where | What you would see if it is forgotten | The fix |
|---|---|---|---|---|
| **1** | **The running tray's rclone path** | `C:\Users\alex\.ccsync\config.toml:18` - `rclone_path = 'E:\Projects\resolve-remote-sync\companion\.tools\rclone.exe'` | **Lane A and lane B stop.** No file on this machine syncs up or down. Nothing in any test covers this file, and the tray does not shout about it. | Change the value to `'E:\Projects\Editing\ccsync\companion\.tools\rclone.exe'`. Do the same in the four backups beside it (`config.toml.bak`, `config.toml.bak-20260810232253`, `config.toml.bak-20260830-2335`, `config.toml.bak-testeditor`) so that restoring a backup does not reintroduce the fault. |
| **2** | **Claude Code project memory** | The directory **name** `C:\Users\alex\.claude\projects\E--Projects-resolve-remote-sync\` (786 M, 126 entries, 100 memory files including `MEMORY.md`) | Every memory file and session transcript orphaned. The next session starts with no memory of this project at all, and does not know that it should have some. | Phase 1 above. **Must be done before the first session opens in the new path.** |
| **3** | **The five in-repo venvs** | `bench\.venv`, `companion\.venv`, `dashboard\.venv`, `music\web\.venv`, `onboarding\.venv` (662 M) | `activate` scripts and every `Scripts\*.exe` launcher still point at the old path. Test commands keep working; **PyInstaller builds via `release.ps1` / `build_editor_package.ps1` do not.** | Phase 5 above: delete and recreate from each `requirements.lock`. |
| **3a** | Borrowed venv, in the test wrapper | `tools\run_all_tests.ps1:74` - `Py = "E:\Projects\broll-platform\web\.venv\Scripts\python.exe"` | Only breaks when `broll-platform` moves (section 9). It has a fallback to the dashboard venv, so the failure is a *silent substitution*, not an error. | `Py = "$repo\broll\web\.venv\Scripts\python.exe"` after section 3.5 creates it. Keep the dashboard fallback line as it is. |
| **3b** | Borrowed venv, in the licence gate | `tools\check_licenses.py:163` - `Path("E:/Projects/broll-platform/web/.venv")` in the `dashboard-container` target's `venvs=[...]` | A 50-package licence inventory silently reports "unscanned" instead of "clean". The gate still passes. | `REPO / "broll" / "web" / ".venv"` - matching the three sibling entries on the lines above it. |
| **3c** | Borrowed venv, in the notices generator | `tools\gen_notices.py:61` - `("broll/web", Path("E:/Projects/broll-platform/web/.venv"), "...borrowed from the pre-fold repo")` | `docs/legal/THIRD_PARTY_NOTICES.md` regenerates with the b-roll web dependencies missing. | `("broll/web", REPO / "broll" / "web" / ".venv", "b-roll search UI mounted at /broll")` - and drop "borrowed from the pre-fold repo" from the note, since it stops being true. |
| **3d** | Borrowed venv, in the instructions | `CLAUDE.md`, the `broll/web` row of the "Running tests" block, and the paragraph after it beginning "broll/web still borrows the old standalone repo's venv" | You (or an agent) follow a documented command that points at a folder in `archive\`. | `cd broll\web; .venv\Scripts\python.exe -m pytest tests -q`, and delete the "still borrows" paragraph. |
| **4** | **The `broll-indexer-watchdog` scheduled task** | Task action: `powershell.exe -NoProfile -ExecutionPolicy Bypass -File "E:\Projects\resolve-remote-sync\broll\indexer\watchdog.ps1"`, Start In: `E:\Projects\resolve-remote-sync\broll\indexer`. It is the only OS-level registration anywhere on this machine that names the repo. | Nothing today: the task is **Disabled**. It would fail the day you enabled it. | Either delete it (`Unregister-ScheduledTask -TaskName broll-indexer-watchdog -Confirm:$false`) or re-point it in Task Scheduler to the `ccsync` path. Deleting is the honest option for a task that has been off. Also update `broll\indexer\watchdog.ps1:40`, whose fallback is `$indexer = 'E:\Projects\resolve-remote-sync\broll\indexer'` (only a fallback; `$PSScriptRoot` wins first). |
| **5** | **The global Claude rule** | `C:\Users\alex\.claude\CLAUDE.md`, the "DaVinci Resolve scripting clients" section, which names `E:\Projects\resolve-remote-sync\companion\src\ccsync_companion\script_server.py` as THE reference implementation for every Resolve project on this machine | An agent in a *different* project is told to copy a guard from a file that is not there, and may decide the guard does not exist. | Change that path to `E:\Projects\Editing\ccsync\companion\src\ccsync_companion\script_server.py`. One line. |
| **6** | Two prototype scripts | `broll\docs\prototypes\local-vlm\run_local_vlm.py:14` and `run_llamacpp.py:13`, both `REPO = Path(r"E:/Projects/resolve-remote-sync")` | Each raises on the first path use. Prototypes, so nothing in production notices. | `Path(r"E:/Projects/Editing/ccsync")` in both. |
| **7** | This repo's own permission rule | `.claude\settings.local.json:7` - a `PowerShell(...)` allow-rule with `E:\\Projects\\resolve-remote-sync\\.claude\\settings.json` embedded twice | The rule stops matching, so one command starts asking for permission again. Harmless. | Replace both occurrences with the `ccsync` path. |
| **8** | Doc prose and docstring headers | 40 tracked files, 51 hits (`git grep -i resolve-remote-sync`). Including 10 `server\tests\test_*.py` whose docstrings say `cd E:\Projects\resolve-remote-sync\server`, plus `SPEC.md`, `docs\RELEASE.md`, `docs\INSTALL.md`, `server\README.md`, `docs\legal\THIRD_PARTY_NOTICES.md` (4 hits), `broll\OVERNIGHT.md`, `docs\MOBILE_PLAN.md`, `docs\mobile\SWEEP.md`, and several bug-hunt briefs | Nothing runs wrong; you follow a `cd` that fails. | One sweep, once, after everything else is verified: `git grep -l "resolve-remote-sync"` then replace in each. **Two exceptions to leave alone:** `docs/bug-hunt-*.md` and the sweep `BRIEF.md` files are archives and record what was true on their date (`docs/README.md` says so explicitly: "do not copy commands out of them"). And re-read the comment at `tools\make_product_repo.ps1:288-289`, which reasons specifically about `E:\Projects\resolve-remote-sync-product` not being a child of the repo - the reasoning survives the rename, but the names in it need updating together. |

**Things in this repo that name paths in OTHER projects** - they do not break
when `ccsync` is renamed, only when the other project moves in section 9:

| Where | Value | Moves in section 9? |
|---|---|---|
| `companion\tests\test_music_clap_sidecar.py:548` | `TORCH_VENV = Path(r"E:\Projects\music-tagger\.venv\Scripts\python.exe")` | Yes. The test skips cleanly when the path is absent, so the CLAP numeric gate would go quiet rather than red. Update it, or delete the 5.2 G venv and accept the skip (see 9.3). |
| `companion\tests\test_timeline_cards_role.py:217` | a literal `E:\Projects\Editing\Resolve\MulticamPipeline` in a fixture string | Yes. Update to `E:\Projects\video\Editing\...`. |
| `companion\config.example.toml:796`, `companion\src\ccsync_companion\config.py:1464`, `site.example.toml:461` | commented-out `jobs_mulcam_pipeline = "E:\\Projects\\Editing\\Resolve\\MulticamPipeline"` | Comments only - but they are what an operator copies, so update them. |
| `dashboard\tests\test_cards_page_prefix.py:38` | `FORK_CHECKOUT = Path(r"E:\Projects\_worktrees\Editing-fork\Resolve\MulticamPipeline")` | **Already dead** - that path does not exist today. Point it at a real checkout or delete the constant. A move cannot make it worse. |

And one reference pointing the other way, in the Timeline Cards repo:
`E:\Projects\Editing\Resolve\MulticamPipeline\tests\perf_e2e.js:243` has
`'E:\\Projects\\resolve-remote-sync'` in a candidate list - but it already
prefers a `--ccsync` flag and the `CCSYNC_REPO` environment variable, so it is a
last resort. Update it in the same pass as `docs\PERF-HARNESS.md:42` in that
repo. Note the Timeline Cards repo has three checkouts (`Editing`,
`Editing-ship`, `Editing-ship2`); fix it in `Editing` and let the others pick it
up when they next update.

---

## 7. What does NOT change

Written out so you are not afraid of the wrong things. Every row was checked.

| Thing | Why it is safe |
|---|---|
| **The GitHub Actions workflows** | None of the six contains `E:\Projects` or `resolve-remote-sync`. CI checks the repo out into its own runner path and always has. |
| **The signed vendor release feed** | It lives in a different repository: `The-Creators-Club/ccsync-releases`, tag `ccsync-releases-v1`. Every URL baked into a signed channel record points there. Renaming this folder, or even this GitHub repo, changes no customer-facing URL. |
| **The autostart entry** | `HKCU\...\CurrentVersion\Run` has `CCSyncCompanion` = `C:\Users\alex\AppData\Local\ccsync\bin\ccsync-companion.exe`. No repo path. |
| **The installed companion** | `%LOCALAPPDATA%\ccsync\` (`bin`, `tools`, `indexer`, `secrets`, `hf-cache`, `ytdl-info`, ...) contains **zero** references to the repo path. The installed build is fully self-contained. The repo is where it is *built*, not where it *runs*. |
| **Git remotes and history** | Renaming a folder does not touch `.git`. `origin` still points at GitHub, every commit, branch and tag is untouched, and `git status` is unchanged. |
| **The NAS, the dashboard container, Syncthing, rclone's remotes** | Everything on the server side addresses shares and container mounts, never `E:\Projects`. Editors' machines never knew this path. |
| **Every other editor in the fleet** | This is one workstation's folder name. Nobody else's machine is involved, and no deploy is required to make the rename real. |
| **PowerShell / bash profiles, Windows Terminal, VS Code** | None exists or none mentions `E:\Projects`. |
| **Scheduled tasks other than `broll-indexer-watchdog`** | There are none anywhere on the machine that name `E:\Projects`. |

Two that are **not** in the safe list, and belong to section 9 rather than the
rename:

- **`%APPDATA%\Claude\claude_desktop_config.json`** names
  `E:\Projects\Editing\Resolve\Resolve_MCP\src\server.py` and that venv's
  `python.exe`. Unaffected by the `ccsync` rename; **breaks the moment `Editing`
  moves**.
- **Two Startup-folder shortcuts**: `Auto Backup Utility.lnk` points at
  `E:\Projects\footage-sorter\ingest\tray\Start-Tray-Hidden.vbs`, and
  `resolve_lefthand.lnk` at
  `E:\Projects\Editing\Resolve\resolve-left-hand-keys\resolve_lefthand.ahk`.
  Neither touches this repo; both break when `footage-sorter` or `Editing` move.
  A shortcut is repointed by right-clicking it, Properties, and editing Target
  and Start in.

---

## 8. Verification

Run in this order. Do not ship anything until all four have passed.

**1. The full gate.** From a fresh terminal, so nothing has a stale working
directory:

```powershell
cd E:\Projects\Editing\ccsync
powershell -File tools\run_all_tests.ps1
```

Expect the summary table at the end and an exit code of 0 (the exit code is the
number of failed suites). Thirteen suites. Watch specifically for `broll/web`
reporting a real interpreter rather than falling back, and for `server`, which
the wrapper runs through Git's bash for you - run by hand from PowerShell, 18 of
its tests skip silently or fail falsely.

```powershell
$LASTEXITCODE
```

Expect `0`.

**2. The drift doctor.** Read-only; it compares repo, built, installed and live:

```powershell
cd E:\Projects\Editing\ccsync
powershell -File tools\check_deploy_drift.ps1
```

Expect the same verdict it gave before the move. This is also where a broken
package-signature state would show up.

**3. The tray, and its lanes** - OWNER. Start the companion:

```powershell
Start-Process "$env:LOCALAPPDATA\ccsync\bin\ccsync-companion.exe"
```

Then, two or three minutes later:

- Right-click the tray icon and read the status lines. Expect the normal
  "up to date" wording, **not** an error mentioning rclone.
- Open the dashboard, FLEET page, and confirm this machine reported recently and
  its lanes are green.
- Confirm the fix for item 1 actually took:

  ```powershell
  Select-String -Path C:\Users\alex\.ccsync\config.toml -Pattern rclone_path
  Test-Path E:\Projects\Editing\ccsync\companion\.tools\rclone.exe
  ```

  Expect the new path, and `True`.
- Check the log for the word `rclone` near any error:

  ```powershell
  Get-Content C:\Users\alex\.ccsync\companion.log -Tail 80
  ```

**4. Claude Code memory** - OWNER. Open a session in `E:\Projects\Editing\ccsync` and
ask it something only the memory knows, for example "what is CR-68 about". A
correct answer (the Resolve script-server launch window) means the memory
directory rename landed. A blank look means phase 1 was missed - stop, quit the
session, and check whether a new empty `E--Projects-ccsync` directory was
created alongside the old one; if so, delete the empty one and redo phase 1.

---

## 9. The categorisation moves, after `ccsync` is proven

**Do not start this until section 8 has passed and you have lived with the
rename for a day or two.** One variable at a time is the whole strategy here.

### 9.1 Create the folders

```powershell
New-Item -ItemType Directory E:\Projects\video
New-Item -ItemType Directory E:\Projects\writing
New-Item -ItemType Directory E:\Projects\tools
New-Item -ItemType Directory E:\Projects\archive
```

### 9.2 The easy ones, in this order

Nothing outside these folders references them, so each is a single line with no
follow-up. Do them first to build confidence.

```powershell
Move-Item E:\Projects\Scriptwriting E:\Projects\writing\Scriptwriting
Move-Item E:\Projects\Personal      E:\Projects\writing\Personal
Move-Item E:\Projects\Compositing   E:\Projects\video\Compositing
Move-Item E:\Projects\3D            E:\Projects\video\3D
Remove-Item E:\Projects\_worktrees            # empty; confirm with Get-ChildItem first
Move-Item "E:\Projects\Build Command.txt" E:\Projects\Editing\ccsync\
```

Check: `Get-ChildItem E:\Projects` and `git -C E:\Projects\video\3D status`
(expect the same clean status as before). Confirm `_worktrees` really is empty
before deleting it:

```powershell
Get-ChildItem E:\Projects\_worktrees -Force
```

Expect no output.

One follow-up: `E:\Projects\Personal\imdb-page-plan.md:3` names
`E:\Projects\Editing\Catalog\vimeo-browser\catalog.json`, which becomes
`E:\Projects\video\Editing\...`. Prose in a plan; update it when you next open
it.

### 9.3 `archive\` - the two folded-in predecessors

Prerequisites: section 3.5 (end the borrowed venv) must be done, and section 3.1
(the missing history) must be decided.

```powershell
Move-Item E:\Projects\broll-platform E:\Projects\archive\broll-platform
```

Then in `E:\Projects\archive\broll-platform`, `indexer\watchdog.ps1:22` has
`$indexer = 'E:\Projects\broll-platform\indexer'` and `OVERNIGHT.md:9,77` name
the old path. It is an archive, so updating them is optional; updating the
watchdog line is still worth two minutes in case it is ever run.

For `music-tagger`, **delete its 5.2 G `.venv` rather than move it**. It is a
build artefact, the folder is not a git repo, and the only thing that reads it
is one companion test that skips cleanly when it is gone:

```powershell
Remove-Item -Recurse -Force E:\Projects\music-tagger\.venv
Move-Item E:\Projects\music-tagger E:\Projects\archive\music-tagger
```

That drops the move from 5.2 G to about 40 MB and reclaims 5.2 G. The cost is
that `companion\tests\test_music_clap_sidecar.py:548` stops running its numeric
CLAP comparison and reports a skip instead. **Decide that deliberately**: if you
want the comparison kept, recreate the venv inside the archived folder
afterwards and point line 548 at
`E:\Projects\archive\music-tagger\.venv\Scripts\python.exe`.

### 9.4 `tools\`

```powershell
Move-Item E:\Projects\Utilities E:\Projects\tools\Utilities
Move-Item E:\Projects\_tools    E:\Projects\tools\_tools
```

Follow-ups, both inside `Utilities` itself:
`FleetView\README.md:14` and `FleetView\start.bat:3` both hardcode
`E:\Projects\Utilities\FleetView`. `start.bat` is executable - fix it, or
FleetView stops starting:

```powershell
# E:\Projects\tools\Utilities\FleetView\start.bat line 3 becomes:
cd /d E:\Projects\tools\Utilities\FleetView
```

Also note `Utilities\yt-credit-downloader\.venv` records a *third* path in its
`pyvenv.cfg` (`E:\Projects\yt-credit-downloader\.venv`) - it has been moved
before and still works in the half-working way described in 5.6. And
`yt-credit-downloader\downloads` is 13 G; consider emptying it before the move.

### 9.5 `video\` - `Editing` and its two worktrees, the delicate one

Do this last and in one sitting. Close Resolve, close the Timeline Cards agent,
and close any Claude Code session in any of the three.

```powershell
Move-Item E:\Projects\Editing       E:\Projects\video\Editing
Move-Item E:\Projects\Editing-ship  E:\Projects\video\Editing-ship
Move-Item E:\Projects\Editing-ship2 E:\Projects\video\Editing-ship2
Move-Item E:\Projects\footage-sorter E:\Projects\video\footage-sorter
```

Then, immediately:

```powershell
cd E:\Projects\video\Editing
git worktree repair E:\Projects\video\Editing-ship E:\Projects\video\Editing-ship2
git worktree list
```

Expect all three listed at their new paths. Then the follow-ups, all of which
are certain to be needed:

1. **Claude Desktop's MCP config** - `%APPDATA%\Claude\claude_desktop_config.json`
   names `E:\Projects\Editing\Resolve\Resolve_MCP\src\server.py` and that venv's
   `python.exe`. Both become `E:\Projects\video\Editing\...`. Restart Claude
   Desktop and confirm the Resolve MCP server connects.
2. **Two Startup shortcuts** - `Auto Backup Utility.lnk`
   (`footage-sorter\ingest\tray\Start-Tray-Hidden.vbs`) and `resolve_lefthand.lnk`
   (`Editing\Resolve\resolve-left-hand-keys\resolve_lefthand.ahk`). Right-click,
   Properties, fix Target and Start in. Test by running each shortcut.
3. **The dashboard's Timeline Cards mount** - `DASH_CARDS_SRC` points at one of
   these three checkouts on the NAS side of the deploy, and `docs/CARDS_DEPLOY.md:72`
   has a `src =` naming it. Nothing in CC Sync's code hardcodes the path (it is
   read from the environment at runtime), but the next Cards deploy will use
   whatever that setting says. Update it before the next Cards deploy, not after.
4. **The four CC Sync references to the `Editing` path** listed at the end of
   section 6.
5. **`perf_e2e.js:243`** inside the Cards repo, as described there.

Check: open Resolve, confirm the left-hand keys script still runs; run one
Timeline Cards page from the dashboard; run `tools\run_all_tests.ps1` in
`ccsync` once more, because two companion tests reference the `Editing` path.

### 9.6 Rewrite `E:\Projects\README.md`

It is stale since 2026-06-28 - its tree diagram predates `broll-platform`,
`music-tagger`, `footage-sorter`, `resolve-remote-sync` itself, `_tools`,
`_worktrees`, `Compositing` and both `Editing-ship` folders. Replace it with the
tree in section 2 of this document, plus the one-line description each folder
already has there. An agent can do this in five minutes, and it should be the
last commit of the whole exercise.

---

## 10. Rollback

**Up to and including phase 4, the rename is fully reversible**, because nothing
has been deleted. That is the reason the venv deletion is ordered last.

To undo:

```powershell
# 1. quit the tray again
Rename-Item E:\Projects\Editing\ccsync E:\Projects\resolve-remote-sync
Rename-Item "C:\Users\alex\.claude\projects\E--Projects-ccsync" "E--Projects-resolve-remote-sync"
```

Then put back the four edits from section 6 that live outside the repo:
`C:\Users\alex\.ccsync\config.toml` (`rclone_path`),
`C:\Users\alex\.claude\CLAUDE.md` (the `script_server.py` path), the
`.claude.json` project key if it was renamed, and the scheduled task if it was
re-pointed. Inside the repo, `git checkout -- .` undoes every in-repo edit in one
command, provided section 3.4's checkpoint commit was made first. That is what
the checkpoint is for.

**After phase 5 (venvs deleted and recreated), rolling back the folder name
means recreating the venvs again** - another 20 to 40 minutes of installing, not
a loss of anything. The repo itself, its history and the fleet are never at
risk at any point in this plan: nothing here touches the NAS, the dashboard, any
editor's machine, or a published release.

The one genuinely irreversible step in the whole document is deleting
`E:\Projects\music-tagger\.venv` in 9.3, and it is irreversible only in the
sense that recreating 5.2 G takes a long download.

---

## 11. Effort, and who does what

| Phase | Owner time | Agent time | Notes |
|---|---|---|---|
| 3. Pre-flight (loose ends) | 20-40 min | 20 min (section 3.5) | The two `git push` / `gh repo create` steps are yours: they need your GitHub account. |
| 5.1 Stop everything | 5 min | - | Only you can quit the tray and close the sessions. |
| 5.2 Memory directory | 2 min | 5 min | An agent can run the renames; you decide whether to edit `.claude.json`. |
| 5.3 The rename | 1 min | - | One command. |
| 5.5 / section 6 fixes | 5 min | 30-45 min | Items 1 and 5 touch files outside the repo; an agent can edit them, but you should read the diff. |
| 5.6 Venvs | - | 20-40 min | Unattended. Mostly downloading. |
| 8. Verification | 15 min | 30-60 min | The agent runs the gate and the drift check; **you** start the tray, read its lines, and confirm memory loads in a real session. |
| 9. Categorisation (9.2-9.4) | 5 min | 30 min | Low risk. |
| 9.5 `Editing` and the worktrees | 20 min | 30 min | You fix the two Startup shortcuts and confirm Resolve and Claude Desktop still work. |
| 9.6 README rewrite | - | 10 min | Unattended. |

**Total owner time: roughly 1.5 hours, spread over two sessions.** Total elapsed
time including the agent's work: most of an afternoon, plus a day of living with
the rename before section 9 starts.

**What an agent can do entirely unattended:** every file edit in section 6,
recreating all five venvs, the `git grep` sweep, `run_all_tests.ps1` and
`check_deploy_drift.ps1`, every `Move-Item` in section 9, and the README
rewrite.

**What needs you:** quitting the tray and closing sessions; `gh repo create` and
both `git push` commands; reading the tray's status lines afterwards; the two
Startup shortcuts; and the four decisions in section 12.

---

## 12. Open decisions for the owner

1. **`music-tagger`'s missing history** (3.1). Look for it, or correct the two
   documents that claim it is there? Recommendation: spend ten minutes looking
   (`gh repo list`, and any backup drive), then correct the documents.
2. **What belongs in `archive\`** (the first Challenge box). My proposal is the
   two folded-in predecessors only, leaving `3D` and `Compositing` in `video\`.
   The alternative is the brief's original: all four one-commit repos.
3. **Rename the GitHub repo too?** (section 4). My recommendation is yes, but
   after one clean release from the new folder, not on the same day. The cost is
   one `git remote set-url`, because the release feed lives in a separate
   repository and no signed URL is affected.
4. **`music-tagger\.venv`: delete or keep?** (9.3). Deleting reclaims 5.2 G and
   turns one companion test's CLAP numeric comparison into a skip. Keeping it
   means moving 5.2 G and updating one test's path.
5. **Does `writing\` earn its place?** (the second Challenge box). Two repos,
   553 KB. Keep, or fold into `archive\`.

Nothing in this plan should be started until 1 and 2 are answered; 3, 4 and 5
can be answered on the day.
