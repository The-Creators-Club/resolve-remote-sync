# Dashboard-driven file moves

Written 2026-08-27, from what happened the same day:

> leso put files in the wrong folder. He put it in `P:\Projects\2026\Base
> Drone\B-roll` and it all uploaded. I then moved the uploaded files to the
> correct folder `P:\Projects\2026\FF5\Animals\Interviewees\Pangolin\臺北動物園`
> - obviously, ccsync then started uploading them again into the incorrect
> folder.

Built the same day: dashboard 0.7.14 (schema v29), companion 0.9.54.
Reworked 2026-08-28 by the resilience sweep (schema v36; DASH-1, DASH-9,
UX-5, UX-11, RES-1, RES-10) - see §6 for what changed and why.
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

1. **Records the move first, then moves it on the server.** The `file_moves`
   row is written `state='pending'` and COMMITTED before `src.rename`, and
   flipped to `done` after (`api.move_project_files`). One file, or a whole
   folder with everything in it. A file's proxies (`Proxy/<stem>.*` beside
   it) go with it, because that adjacency is what Resolve's auto-link and
   both rclone lanes are built on; a proxy that could not follow makes the
   move `partial` and the answer a 207 naming exactly which proxies stayed.
   Refused rather than guessed: a destination that already exists, a folder
   into itself, a `Proxy` folder as either end, the project marker, anything
   that escapes the tree. A rename that fails takes its own reservation with
   it, so a 503 still means nothing moved.
2. **Records the move** (`file_moves`, v29/v36) with one target row per computer
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
  wired into lane A's filter as `- /<old rel>`) after an applied move, and
  for as long as a move is UNRESOLVED on that machine (`retryable` or
  `blocked`, RES-1). This is what closes the race: a machine whose lane A
  pass runs before the command arrives, or whose move could not be applied,
  cannot put the file back while the admin sorts it out.
- **A failure is retried, not latched** (RES-1). A file Resolve is holding
  open cannot be moved; the companion records `retryable` with an attempt
  count and a next-attempt stamp (10 minutes, then hourly), tries again on
  every report, and gives up after 20 attempts or seven days with a distinct
  `blocked` answer the project page shows. The old behaviour re-answered the
  first `PermissionError` for ever, and the file re-uploaded itself a day
  later.
- **Bounded by DELIVERY, not by age** (UX-5). An UNDELIVERED command never
  expires: the laptop that was away for a two-week shoot is precisely the
  machine still holding the file at the old path. A command that WAS
  delivered and never answered ages out after seven days into `expired_at`,
  which the project page shows as
  `[ NOT APPLIED - THIS COMPUTER MAY RE-UPLOAD THE OLD PATH ]` with an
  [ ASK THAT COMPUTER AGAIN ] button. The companion refuses any move whose
  source is not where the command says, which is what makes an old command
  harmless.
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
  keep re-uploading. The retry (`retrying`, RES-1) and the relink-later
  answer (RES-10) need 0.9.55. Deploy the dashboard (schema v36) BEFORE
  that companion: a pre-v36 dashboard drops the unknown `state` field, reads
  a `retrying` answer as `ok=false`, stamps `applied_at` and never resends
  the command - the old one-shot latch, relocated to the server.
- It does not detect a move made in Explorer on the NAS (see above). Nor
  does it delete anything, ever, on either end.

## 5. Tests

`dashboard/tests/test_file_moves.py` (the move, its refusals, who is told and
for how long, the two-phase ordering, the partial-proxy 207, reconciliation,
expiry and re-issue, the undo round trip and its audit row, the page),
`companion/tests/test_file_moves.py` (the move, the ledger, the lane A
exclusion, the retry schedule and its cap, once-per-move, the refusal, the
deferral, pending relinks, the report), `companion/tests/test_watcher.py`
(a MISSING clip a move took away is offered for relink).

## 6. What the resilience sweep changed (2026-08-28, schema v36)

- **DASH-1, two-phase.** The row used to be written AFTER the rename
  returned. A rename that succeeded and then met anything at all (a proxy
  held open, a container restart, a full `/data`) moved the original with no
  record anywhere, so no machine was ever told: every holder re-uploaded the
  old path while the editors' Resolve projects pointed at a file that was no
  longer there. The row now exists, committed, while the rename runs, and
  `api.reconcile_file_moves` (boot and every collector cycle) stats both ends
  of every `pending` row: only the destination present means the rename
  happened, so it is completed and fanned out; only the source means it did
  not, so the reservation is dropped; both (or neither) is quarantined with a
  red `[ UNFINISHED ON THE SERVER ]` banner on the project page and nothing
  sent to anyone. A proxy that cannot follow is a `partial` move and a 207
  naming it, never a 503 claiming nothing happened.
- **UX-5 / DASH-9, expiry.** Delivery, not age (see §3). The project page
  grows a MOVES AWAITING MACHINES panel with age chips, and an expired
  target has a one-click re-issue.
- **UX-11, the confirm and the undo.** The confirm is built from the form
  values ("Move '<path>' from <project> to <project>/<folder> ... and tell N
  computers ..."), rather than one fixed sentence in front of a free-text box
  and a destination select that keeps the last project you looked at.
  `POST /projects/{slug}/moves/{id}/undo` issues the inverse move through the
  same machinery (the record carries both ends and `is_dir`), inherits the
  original's target machines, is audited (`db.audit`, `file.move.undo`),
  takes a NAS snapshot first for a directory move, and is offered only while
  every computer has applied the move or is still waiting for it.
- **RES-1, the retry.** See §3.
- **RES-10, the relink that was never revisited.** `_relink_moved` only ever
  walked the media pool that happened to be OPEN. A move of project B's
  footage while project A was open answered "Resolve not relinked (not
  open)", the ledger called it done, and the clip was simply offline the next
  time anyone opened B. An applied move now stays `relink_pending` in the
  ledger (and on the project page) until a media pool walk has actually
  matched it, or 30 days pass; `on_project_changed` re-runs it. And the
  watcher, which classified that clip `MISSING` and wrote a DEBUG line, now
  asks the ledger: a missing path a move took away gets a toast and a
  one-click relink, because the new path is known exactly. The relink itself
  is still `resolve_bridge.replace_clip`, the one door every media pool write
  goes through.
