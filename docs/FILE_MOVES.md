# Dashboard-driven file moves

Written 2026-08-27, from what happened the same day:

> leso put files in the wrong folder. He put it in `P:\Projects\2026\Base
> Drone\B-roll` and it all uploaded. I then moved the uploaded files to the
> correct folder `P:\Projects\2026\FF5\Animals\Interviewees\Pangolin\臺北動物園`
> - obviously, ccsync then started uploading them again into the incorrect
> folder.

Built the same day: dashboard 0.7.14 (schema v29), companion 0.9.54.
Related: `SPEC.md` (the three lanes), `docs/SYNC_SAFETY.md` (what a lane will
never do), `docs/UPLOAD_ONLY_TICK.md` (the other change of the day),
`KNOWN_BUGS.md` CR-87.

---

## 1. Why a move on the NAS is undone

Lane A is `rclone copy --ignore-existing`, one way, editor to server, and it
never deletes anything anywhere (`docs/SYNC_SAFETY.md` §5). On every pass it
uploads whatever video sits on the editor's disk that the server does not
have *at that path*. Move a file on the server and the server no longer has
it at that path; the editor's disk still does; so the next pass uploads it
again, to the old place. Every machine that holds a copy will do this, after
every move, for as long as its copy stays where it was.

That is not a bug in lane A. It is what "never deletes, never mirrors a
removal" means, and it is the property that has kept footage safe through
every incident in this ledger. The fix therefore cannot be "make lane A
notice". The fix is to make the move happen on BOTH ends.

## 2. What it does now

On the project page, an admin has `MOVE: <path> to <project> / <folder>
[ MOVE ON THE SERVER AND ON EVERY MACHINE ]`. Pressing it:

1. **Moves the file or folder on the server**, inside the mounted Projects
   tree (`api.move_project_files`). One file, or a whole folder with
   everything in it. A file's proxies (`Proxy/<stem>.*` beside it) go with
   it, because that adjacency is what Resolve's auto-link and both rclone
   lanes are built on. Refused rather than guessed: a destination that
   already exists, a folder into itself, a `Proxy` folder as either end, the
   project marker, anything that escapes the tree.
2. **Records the move** (`file_moves`, v29) with one target row per computer
   that has to follow (`file_move_targets`): every machine with the source
   project ticked, in either mode (an upload-only machine is exactly the one
   holding a card dump at the old path), plus any machine whose manifest
   says it holds the file even though its plan no longer does.
3. **Tells each of those machines** through the report reply
   (`commands.file_moves`, beside the halt and the pushed update). The
   command rides every report until the machine answers, so a lost reply
   costs one interval and never a copy left re-uploading itself.
4. **The companion follows** (`file_moves.py`, `app._apply_file_moves`): it
   moves its own copy the same way, proxies with it, repoints every Resolve
   media pool clip that referenced the old path through `replace_clip` (save
   point + undo journal, like every Resolve mutation), and answers in its
   next report (`file_moves_applied`). The editor sees one tray balloon.
5. **The project page shows the outcome** per computer: waiting for its next
   report, told but not done yet, moved, or FAILED with the reason.

## 3. The rules that keep it safe

- **Nothing deletes, anywhere.** The server side is a rename. The companion
  refuses a move whose destination already exists on that machine and leaves
  the file where it was, reporting why. A refusal is an answer, and the
  admin reads it on the page.
- **Once per move.** The companion's ledger (`~/.ccsync/state/file_moves.json`)
  answers a redelivered command with the outcome it already had. A restart
  between the move and the report does not move it twice.
- **The old path stays out of lane A for a day** (`FileMoveLedger.recent_excludes`,
  wired into lane A's filter as `- /<old rel>`), applied or refused. This is
  what closes the race: a machine whose lane A pass runs before the command
  arrives, or whose move was refused, still cannot put the file back while
  the admin sorts it out.
- **Bounded in time.** A command older than seven days is not delivered
  (`db.pending_file_moves`): a machine that was away for a month must not
  come back and shuffle files that have been shuffled again since. The
  companion also refuses any move whose source is not where the command
  says, so an expired one costs a log line.
- **A missing sync drive defers**, it does not answer: "nothing at the old
  path" would be a lie with the disk unplugged.
- **Admins only.** A move rewrites the tree and reaches into every machine
  holding the file; the editor who mis-filed the card asks the admin.

## 4. What it does not do

- It does not detect a move made in Explorer on the NAS. Move through the
  dashboard, or the old behaviour applies. (Automatic detection between two
  inventory walks is possible and was deliberately left out: a rename plus a
  copy, or two cards with an `A001.MOV` of the same size, would be misread.)
- It does not move a file across two projects on a machine that has only
  the destination ticked and not the source: there is nothing there to
  move, and lane B / lane C will deliver the file at its new place normally.
- Companions older than 0.9.54 ignore the command; their copies stay put and
  keep re-uploading. Deploy the dashboard, then push the companion.
- A Resolve that is closed at the time is not relinked; the file has still
  moved, and the clip goes offline in that project until the editor opens
  it and the fixer popup meets it like any other offline clip. The answer on
  the page says "Resolve not relinked (not open)".

## 5. Tests

`dashboard/tests/test_file_moves.py` (the move, its refusals, who is told and
for how long, the page), `companion/tests/test_file_moves.py` (the move, the
ledger, the lane A exclusion, once-per-move, the refusal, the deferral, the
report).
