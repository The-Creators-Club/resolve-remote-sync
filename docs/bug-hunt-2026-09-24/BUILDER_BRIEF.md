# Fix-pass brief (2026-09-24): the eleven highs - read fully before editing anything

Repo: E:\Projects\Editing\ccsync. You are ONE of FOUR builders, each owning a
FILE GROUP, fixing the HIGH findings of the eleventh hunt
(`docs/bug-hunt-2026-09-24.md`, "The confirmed highs"; full text under
`### <id>` in `docs/bug-hunt-2026-09-24/hunters/<hunter>.md`, where the
hunter is the id without its trailing number; the verifier's reasoning is in
`docs/bug-hunt-2026-09-24/results.json`). Read the finding, the verifier's
reason, and the code, and trace the defect yourself before touching it: a
finding is a pointer, not a spec. If you find the mechanism is not what the
finding says, fix what is really there and say so in the ledger.

At the same time, read-only verifiers are judging the hunt's MEDIUMS against
`git show HEAD:<path>`. That is fine; they do not edit.

## Rules

1. Edit only files in your group (below) and their tests. If a correct fix
   needs a change in another group's file, make the smallest change in your
   own files and write the rest under OWED in your ledger. Never edit a file
   another group owns. `companion/src/ccsync_companion/app.py` is SHARED by
   `comp-halt-repath` and `comp-upgrade-moves`: each touches only the
   functions its own findings name, and re-reads the file right before every
   edit, because the other builder may have changed it.
2. Do NOT bump versions, edit `KNOWN_BUGS.md`, commit, push, or run
   `git stash/checkout/reset`. The orchestrator does the versions, the ledger
   entries (CR-322 onward) and the commit.
3. Every fix gets a REGRESSION TEST that FAILS on HEAD's code and passes on
   yours. Say in your ledger how you know it fails on HEAD (you ran it
   against `git show HEAD:<file>` in a scratch copy, or you reasoned it
   through line by line: say which). A test that pins the new behaviour
   without proving the old bug is gone is not a regression test. Follow each
   suite's existing conftest patterns (the companion suite must never spawn a
   real Tk dialog or touch live Resolve).
4. Run ONLY the test files you touched or that exercise the functions you
   changed (owner rule: the full gate runs once, centrally). Interpreters per
   component are in CLAUDE.md "Running tests"; `server/` from Git Bash.
5. The code comment at each fix cites the finding id and the date
   (`# bug-comp-app-1 (2026-09-24): ...`) and explains the constraint or the
   failure mode, never what the next line does (CLAUDE.md).
6. Version skew: the field runs companion 0.9.77 against dashboard 0.7.56.
   Any new wire key must be optional on read and harmless when ignored, in
   BOTH directions. No new user-visible em dash anywhere.
7. Do not touch `~/.ccsync`, `%LOCALAPPDATA%\ccsync`, the NAS, the live
   dashboard, Resolve, or any live process. This machine is the studio's
   base rig and its companion is running.

## Groups

**comp-halt-repath** - `companion/src/ccsync_companion/sync/sequencer.py`,
`sync/repath.py`, `sync/syncthing_lane.py`, `sync/syncthing_admin.py`, the
halt functions of `app.py` (`halt_all_sync`, `_stop_lanes`, `toggle_pause`,
`_root_pause_lanes`, `_start_lanes`, `_pause_lane_c_folders`, `shutdown`'s
stop call) and their tests.
- `bug-comp-app-1`: a halt's paused folders are unpaused by any later
  `sequencer.stop()/pause()`, and a restart with a persisted halt never
  re-pauses them. The halt must hold across every stop/pause path AND across
  a restart (the persisted latch must re-pause on start).
- `bug-comp-rclone-1`: a blocked repath is "finished" on the next pass by
  pointing Syncthing at the directory lane B or the structure clone created.

**comp-upgrade-moves** - `companion/src/ccsync_companion/upgrade.py`,
`supervisor.py`, `crash_report.py`, the upgrade/revert functions of `app.py`
(those `bug-comp-core-1` names), `file_moves.py`, `sync/lane_guard.py` (the
trash retention only), `docs/HAND_MOVES_ON_THE_SERVER.md`, `docs/FILE_MOVES.md`,
and their tests.
- `bug-comp-core-1`: a crash-loop revert does not stop the machine
  re-installing the build it just fled (offer, push and auto_update paths).
- `bug-comp-core-2` (verified real, downgraded to medium, fixed here because
  it is the same mechanism): the APP-5 rollback copy is deleted seconds
  after start, so the revert cannot fire on an online machine.
- `logic-plans-3`: section 4b trashes a whole local folder, including
  never-uploaded originals, and trash is kept 14 days, not what the doc
  says. Nothing lane A still owes may be binned: leave un-uploaded originals
  where lane A will still find them (or refuse the 4b trash and report it),
  and make the doc and the retention agree.

**comp-media** - `companion/src/ccsync_companion/ytdl_executor.py`,
`youtube_import.py`, `ytdl_common.py`, `sync/rclone_lane.py`,
`jobs_media.py`, `jobs_runner.py`, `proxy_gen.py`, `ffmpeg_tools.py`,
`sidecar_tools.py`, `broll_ingest.py`, `broll_ingest_media.py`,
`broll/web/static/ingest.js`, `broll/web/app/ingest_batches.py` (and the
b-roll web routes that call it), and their tests.
- `bug-comp-ytdl-1`: a conversion longer than 120 s leaves the
  pre-conversion original eligible for lane A and the Resolve importer under
  its final name.
- `bug-comp-media-1`: media jobs and proxy generation spawn the bare name
  `ffmpeg`; a machine whose only ffmpeg is the managed sidecar copy reports
  the capability, claims, and fails. One resolver for every spawn, and the
  capability report must agree with what the spawn will use.
- `bug-comp-broll-1`: a batch holding two clips with the same name indexes
  the first clip twice and never the second (companion manifest mapping,
  the page's drop handling, and the server's name assignment: find which
  side keys on the name and fix it there; both sides if both do).

**webapps-ops** - `ytdl/web/*`, `server/*`, `tools/*`, `docs/RELEASE.md`,
`docs/RELEASE_PATHWAYS.md`, `dashboard/templates/*`, `dashboard/static/*`
EXCEPT `cards_landing.*`, and their tests.
- `bug-music-ytdl-1`: the "share vanished" guard runs after the download
  phase has created the project folder, so it can never fire.
- `bug-ops-1`: `publish_db.py --rollback` picks the `.prev-<ts>-wal`
  sidecar and renames it over the live index.
- `logic-release-1`: the documented key rotation signs the overlap release
  with the NEW key, and the REL-7 refusal tells the operator to override.
  Make the doc's procedure the one that works (overlap release signed by
  the OLD key, carrying both public keys) and make the refusal's sentence
  point at it, not at an override.
- `ui-dash-admin-1`: a project name with an apostrophe breaks the ARCHIVE
  confirm. Fix it, then SWEEP every template for the same shape (a
  server-rendered value inside an inline `on*=` handler or a `<script>`
  string without `| tojson`) and fix each; list them in the ledger.

## Output

Write `docs/bug-hunt-2026-09-24/ledger/<group>.md`, one section per finding:

```
## <finding-id> - <title>
- Mechanism (as you traced it): ...
- Fix: ... (files:lines)
- Regression test: <file>::<test> - fails on HEAD because ...
- Other tests run: <command> -> <result>
- Skew / deploy order: ...
- OWED: <to whom, what> | none
```

Then return the same as structured output.
