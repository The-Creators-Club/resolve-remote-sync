# CR-283 - the ninth hunt's companion-core mediums and lows - FIXED in repo 2026-09-18 (companion 0.9.75, unshipped)

Second wave of the 2026-09-18 fix pass, `companion-core` group: the sync
lanes' own files, the tray and its Windows icon, the supervisor, the upgrade
client, the stills helper and `app.py`'s watchdog/guard halves, plus the three
items the LIVE dashboard put on this group (`hunters/live.md`) and live-5,
added by the owner mid-pass, and the two halves owed IN by companion-media
(CR-283W and CR-283X). Eighteen assigned findings, four live items and two
owed-in halves, plus res-fleet-3 (the one medium left with no disposition
anywhere): twenty-four fixed, one declined with a reason (comp-app-4),
one half of CR-279 declined as the design decision its own ledger entry says
it is.

### CR-283A (comp-sync-2) - CR-278's path-missing heal never ran on the machine its docstring describes - FIXED (companion/src/ccsync_companion/sync/syncthing_lane.py)

`_heal_missing_paths` is documented as covering "every configured folder, not
just the selection: the shared asset libraries (assets-luts on leso's Mac) sit
in the same error and no selection names them" - and its single call site sat
several branches BELOW `if not expected: return`, where `expected` is the
ticked full-mode PROJECT slugs. So the one machine the heal was written for -
an editor between projects whose only path-missing folder is a shared asset
library - could never run it, and neither could a machine whose selection
fetch had not landed yet after a restart. The `/rest/config` read and the heal
now happen once, above the no-selection return, and the folder verdict below
reuses that same read (no extra GET). A config read that fails is carried down
to the verdict, which is where a failure is allowed to become a lane error:
the no-selection branch still answers "no project folders to check yet" rather
than turning into an error on a machine that has nothing ticked.

### CR-283B (comp-ui-2) - a failed Explorer-restart re-add left the companion permanently headless - FIXED (companion/src/ccsync_companion/tray_native.py)

comp-ui-1 (2026-09-11b) correctly stopped a failed re-add from setting
`_ccsync_stop`, and its justification - "the next TaskbarCreated broadcast can
still succeed" - was the ONLY recovery in the process: `_add_icon` had exactly
two callers, and the branch's own comment says that next broadcast "may be
never". After one late Explorer the editor had no icon, no menu, no Settings
and no Quit for the life of the process, every toast dropped, on a companion
that went on syncing correctly. A failed re-add now arms a `SetTimer` on the
tray window (`_CCSYNC_READD_TIMER_ID`, 60 s) and the WM_TIMER retries NIM_ADD
until it takes, then kills the timer. ONE attempt per tick, not the flat six:
this runs on the pump thread, where every slept second is a frozen tray, and
it means one log line a minute rather than six. No `_announce_failure` on a
retry, which is why this had to land with CR-283N.

### CR-283C (res-companion-4) - a wedged thread was "restarted" without being stopped, so the watchdog stacked duplicate writers into Resolve - FIXED (companion/src/ccsync_companion/app.py)

`LaneWatchdog._restart` called `target.restart()` and nothing else, for the
DIED branch and the silent-but-alive branch alike. For the media tree that
meant `_start_media_tree_thread`, whose first statement CLEARS the shared stop
event before it overwrites the thread reference: the orphan went on looping
once it unblocked, so two threads walked the same media pool and both reached
`apply_relinks` -> `resolve_bridge.replace_clip` / `link_proxy_media`, two
unprompted writers into one Resolve project, while the new thread's heartbeat
made the wedge read as healed. `_SupervisedThread` now carries an `abandon`
callable; the media tree's is `_abandon_media_tree_thread`, which bumps a
generation counter the loop was born with, so the old thread exits at its next
check (before a pass and after it, since the pass is where the wedge happens)
instead of running beside its replacement. A live thread with NO way to retire
it is no longer "restarted" at all: the sequencer refuses a second thread
outright and the watcher shares the process-wide stop event, so a restart of
either was never anything but an ERROR line and a `sync_guard.restarts` record
(see CR-283T). It is logged once per change of answer, as the ceiling is.

### CR-283D (comp-app-1) - the b-roll editing-proxy resume was gated behind the relink feature flag - FIXED (companion/src/ccsync_companion/app.py)

`_resume_broll_proxy_upgrades` had one call site and it was the third
statement inside `_relink_proxies_once`'s `try`, below its two early returns.
`proxy_relink_enabled = false` is a supported config key, and the insert path
that CREATES a pending row is not gated on it, so on such a machine a stand-in
queued by Send to Resolve and interrupted by a restart stayed `pending` for
ever: an editor cutting on a 1080p H.264 lie under a 6K name with no path back
but a re-insert. The call is now its own statement in the 120 s media-pool
cycle. `broll_server.resume_pending_upgrades` needs no Resolve connection at
all, so nothing is lost by moving it out; the `_local_root_is_broken()` guard
came WITH it (the download lands under local_root) and lives inside the
function now.

### CR-283E (comp-app-2, comp-app-5) - the relaunch ceiling's own file was written in place, and one bad stamp cost the whole history - FIXED (companion/src/ccsync_companion/supervisor.py)

`write_relaunch_note` was given tmp+replace in the 09-11b pass with the stated
reason "a kill mid-write cannot leave half a note behind either", and
`write_history` - `<state>/supervisor.json`, the source `decide()` reads on a
cold chain, written by the one process that exists BECAUSE machines die
abruptly - was left a bare `write_text`. A power cut inside that write left
truncated JSON, `read_history` answered `[]`, and a build that could not stay
up got three more relaunches an hour with nothing anywhere saying the ceiling
had been lost. It is tmp+replace now, tmp cleanup included, byte for byte like
its neighbour. In the same edit, `read_history` coerces per item
(`except (TypeError, ValueError): continue`) exactly as `merge_history` - same
pass, same data - already did, so one hand-edited or future entry costs one
entry rather than the ceiling.

### CR-283F (comp-app-3) - a standing upgrade refusal was cleared by the four replies that mean "there IS a build, we are just withholding it" - FIXED (companion/src/ccsync_companion/upgrade.py)

comp-ytdl-jobs-1 (2026-09-11b) reads a reply with no `upgrade` key as "the
dashboard says there is nothing to take" and clears `last_refusal`.
`api._upgrade_info` returns None in four further states in which a package
EXISTS and is being withheld - it is retracted, it needs a newer dashboard,
its arch does not match the reporter, the reported platform is unknown - and
its own comment calls three of them "silent to the companion on purpose". In
all four the build is never re-offered, so the cleared refusal could not come
back: the chip and the `upgrade_refused` alert went out and the operator was
told nothing was wrong about a machine that is refusing to upgrade and will
never be offered anything. The companion now clears only when the reply
carries neither `upgrade` nor `upgrade_none_reason`. The key is ADDITIVE and
the dashboard does not send it yet (OWED, below), so a companion on this build
against any dashboard in the field behaves exactly as 0.9.74 did.

### CR-283G (comp-app-4) - "CCSync" is hardcoded in ~60 user-visible strings - NOT FIXED (declined)

The verifier downgraded this to low and refuted its central claim: `app.py`
routes 101 calls through `site_mod` (`notify_title` 85, `drive_phrase` 13),
`site.notify_title()` already resolves org_short -> product_name for the TITLE
of every balloon and dialog, and the owner's 2026-08-18 ruling is that the
product mark appears on every customer's build, like Resolve or Premiere - so
"CCSync" in body copy is not a customer's name leaking. What is left is a
SPELLING inconsistency (`CC Sync` in `site.DEFAULT_PRODUCT_NAME`, `CCSync` in
~60 sentences), and settling it means touching 32 modules and every test that
pins a sentence, for no user-visible gain, in a time-boxed pass. Left for the
owner to decide; see "Owner decisions".

### CR-283H (comp-app-6) - the unreadable-id toast did not mention the repair that shipped beside it - FIXED (companion/src/ccsync_companion/app.py)

comp-app-8's two halves shipped in one pass: a once-per-process tray warning
and a [ repair ] button in the Settings window. The warning's copy predated
the button - "Send your log to your admin: the file is repairable and CCSync
will not overwrite it on its own" - so the editor was told to wait for
somebody else while the fix was two clicks away. The sentence now names
Settings as the place the repair lives, and deliberately does not read as an
instruction to press it: the button's own comment is that a one-click identity
change is not a decision to take from a notification, and the dialog's "if
your admin is still looking at the old file, wait for them" tone is kept.

### CR-283I (comp-sync-3) - `_move_out_of_trash` claimed it could never overwrite; on macOS it could - FIXED (companion/src/ccsync_companion/sync/rclone_lane.py)

The docstring said "NOTHING here overwrites and nothing here deletes --
os.rename, never os.replace, so a destination that appeared between the check
and the rename is a refusal rather than a file lost". That is a WINDOWS
behaviour: POSIX rename(2) replaces an existing destination silently, and this
code runs on every Mac in the fleet, so `dest.exists()` was a TOCTOU check
selling a guarantee the call could not keep - lane B's own express run for
another project, Syncthing or the editor landing that path in the window
destroyed the fresh copy with the trashed one, silently, in a case the
function's contract calls impossible. On POSIX the move is now `os.link` +
`os.unlink` (EEXIST is the refusal we wanted, and the trash lives under
local_root, so it is always one volume), falling back to the plain rename when
hard links are refused (exFAT, an SMB mount) and on Windows, where rename
already IS the refusal. The docstring says which is which.

### CR-283J (comp-sync-4) - a file moved into a BORROWED project had a home on this disk and was trashed anyway - FIXED (companion/src/ccsync_companion/app.py, sync/rclone_lane.py)

`_project_rel_for_slug` - lane B's answer to "the server says this file moved
into project X, do I sync X?" - read `sequencer.rel_to_slug`, which holds
SELECTED projects only by design (it is the manifest and proxy-scan scope). A
hand move into a project this machine borrows from therefore resolved to None,
and the editor's copies sat in `.ccsync-trash` for 14 days as "no home on this
disk" while lane C downloaded them again, which is the exact cost CR-268b
exists to avoid. The hunter's suggested `rel_to_slug_with_borrowed()` would
have been WRONG (the verifier caught it): that map is LENDER subpath ->
BORROWER slug, so a lookup by the slug the server named answers somebody
else's directory. A borrowed project is only PARTLY on this disk, so the
question cannot be answered by slug alone: `_project_rel_for_slug(slug, rel)`
now falls through to `_borrowed_rel_for_slug`, which resolves the lender's own
rel from `sequencer.borrowed_lenders()` and accepts the place only when the
file's project-relative path is inside one of the subtrees this machine
actually borrows. Lane B passes the rel with the slug; a callable that takes
the slug alone still works.

### CR-283K (comp-sync-5) - the 09-11b pass wrote mojibake into two `file_moves.py` comments - FIXED (companion/src/ccsync_companion/file_moves.py)

Commit 34a3c8f re-encoded `Matej Simalcik.mov`'s accented spelling by decoding
it as latin-1 and encoding it again as UTF-8, in the two comments whose only
job is to document CR-90's NFC/NFD rule. Harmless at runtime and fatal to the
one worked example a future reader will look for - and evidence that an
editing tool in that pass was not UTF-8 clean. Both lines are back to their
pre-34a3c8f bytes, and a scan test now fails on any of the three sequences
that corruption produces, anywhere in `src/ccsync_companion`.

### CR-283L (comp-sync-6) - the path-missing heal hardcoded `.stfolder` - FIXED (companion/src/ccsync_companion/sync/syncthing_lane.py)

The "is the drive really back?" test was `os.path.isdir(path/".stfolder")`.
The marker name is a per-folder Syncthing config field (`markerName`, in the
very dict the loop already holds), it was a plain FILE before Syncthing 1.0,
and Syncthing stores the folder path as configured, `~` included - so a folder
created outside our installer never healed, silently. The heal now reads the
folder's own `markerName`, accepts a file as well as a directory, and expands
`~`. This covers the HEAL only: `rclone_lane`'s four filter sites and
`tray.py` still assume `.stfolder`, so the product is not markerName-aware,
and the comment says so.

### CR-283M (comp-ui-1) - every toast raised during the 105 s registration window was discarded - FIXED (companion/src/ccsync_companion/tray_native.py)

`notify()` refuses to emit while `_added` is False and there was no queue, no
replay and no reader anywhere. comp-ui-1 (2026-09-11) changed the FIRST
registration to twelve attempts across 105.5 s and `run()` does not enter the
message pump until `_add_icon` returns, so everything raised in that window
was lost with one WARNING: app.py's +3 s post-upgrade line, the crash-loop
rollback sentence (the ONE line that explains a silent downgrade), and any
safety latch that trips at startup. A bounded deque (5, oldest dropped first)
now holds them and every successful `_add_icon` flushes it. The DROPPED
warning is unchanged - a queue that evicts must still say what it dropped, and
the 2026-09-11 test asserts on that wording.

### CR-283N (comp-ui-3) - a self-recovering re-add failure wrote a crash report and printed the terminal remedy - FIXED (companion/src/ccsync_companion/tray.py)

`fatal` gated only the `_ccsync_stop` assignment: the ERROR line ("Sign out
and back in, or restart CCSync, to get it back") and the
`crash_report.write_report({"type": "TrayIconUnavailable"})` both ran
unconditionally. So a failure the same fix pass declared self-recovering told
the editor to restart, and an Explorer crash-loop wrote one crash file per
broadcast - counted by `crash_summary()`, reported as `sync_guard.crashes` on
every tick, shown in Settings and on the grid, and `_prune` keeps only the
newest 20, so the transient failures silently deleted the real crash reports
an admin needed. A non-fatal failure is now a WARNING that says the icon will
be re-added automatically (which CR-283B makes true) and writes no crash
report; the terminal path is unchanged.

### CR-283O (comp-ui-4) - a terminal registration failure leaked the tray window and its HICON cache - FIXED (companion/src/ccsync_companion/tray_native.py)

`run()`'s happy path frees the window, its per-instance window class and every
cached HICON in `_pump`'s `finally`; the `except` arm announced, set
`_stopped` and returned with all of them held for the life of the process.
`_teardown()` is called there now, BEFORE `_stopped.set()` - the verifier's
catch - so a `stop()` waiter cannot return while the window is still alive.

### CR-283P (comp-ui-5) - the FIX ALL bar read a flat 0% for a whole rehearsal, under the word "Copying" - FIXED (companion/src/ccsync_companion/popup.py)

comp-resolve-b-1 (2026-09-11b) correctly stopped a rehearsal from crediting
bytes it never copied, and left `batch_bytes_total` at the real size of
everything - so under `fixer_dry_run` the batch bar sat at 0 of 800 GB for the
whole run, `RateEstimator` never saw a moving sample, and the file line said
`Copying "A001_C012.braw": 0 B of 12.7 GB` for each clip in turn. One
misleading screen was swapped for another, on the run whose whole purpose
(RES-15) is a screen an admin can trust. The loop now learns from the first
`dry_run` answer, publishes `rehearsing` with no byte totals in the PROGRESS
keys only (the final publish still carries `rehearsal`/`fixed`/`skipped` for
`_fix_done` and `summarize_fix_results`), the bar counts CLIPS, and
`format_file_progress` says `Checking "..."` behind a flag rather than an edit
to the string the real copy path shares.

### CR-283Q (comp-ui-6) - the stills "gallery moved" line joined a POSIX path with a backslash - FIXED (companion/src/ccsync_companion/stills.py)

On macOS `root` is the real local path (`/Users/<them>/.../Assets/Stills`) and
the message hard-coded a backslash, so the one line telling a Mac editor where
their gallery went named a path that exists in no spelling - pasted into
Finder's Go to Folder it simply fails. The separator follows `self._windows`,
which the manager already carries. `canonical_stills_path`'s hard-coded
backslash is a different thing and is untouched: that string has to match
between machines.

### CR-283R (regression-6) - the companion half of tests-3's neutered assertions - FIXED (companion/tests/test_app.py)

tests-3 named two `or True` assertions; CR-255k's entry and ledger describe
only the dashboard one, and the companion line survived verbatim. Deleted
rather than enabled, on the verifier's reasoning: as written it banned every
hyphen, and a hyphen with spaces is the owner's own recommended replacement
for an em dash - the `(em dash)` assertion beside it is the real check, and it
stays. The third one, written by the fix pass itself into
`dashboard/tests/test_bug_hunt_2026_09_11b_dash_release_jobs.py:329`, is
another group's file and is OWED below. `grep -rn "or True" companion/tests`
now returns lambdas only.

### CR-283S (live-1, companion half) - a stall killed and recovered from a week ago was reported as a CURRENT blockage, for ever - FIXED (companion/src/ccsync_companion/sync/rclone_lane.py, app.py)

SYNC-1 made the stall record persistent so a restart could not erase the
evidence, and gave it no expiry and no "the lane has since completed a pass"
condition. ruskin/DESKTOP-LQQ41TC: one lane A upload killed on 2026-09-11
16:26 UTC, and on 2026-09-18 with all three lanes idle and nothing owed the
row still said `blocked_reason=lane_stalled since 2026-09-11`, the mail "still
not fixed after 4 day(s)" had gone out four days running and his tray was red,
with nothing any editor or admin could do about it. leso's Mac had the same
shape. Two conditions now end the CLAIM (never the evidence): a completed pass
of THAT lane stamps `recovered_at` on the record - lane A and lane B share one
state dir and one file, so the label must match, and an express run clears an
express stall - and nothing is reported after 24 h in any case.
`stall_report()` returns None in both cases, i.e. the field is ABSENT, which
is how "nothing is stalled" is spelled on this wire; app.py's own fallback,
which reads the FILE when the guard carries no section, applies the same two
rules. Deliberately NOT a `recovered_at` on the wire: a 0.7.49 dashboard reads
any record it is sent as a current blockage, so that would have fixed nothing
until every dashboard was updated.

### CR-283T (CR-279, queueing half) - the alert that fired for all three editor machines - PARTLY FIXED (companion/src/ccsync_companion/app.py); the starvation half stays a design decision

The live dashboard showed `thread_restarts` for all three editor machines
(leso 8, Razer 5, ruskin 3 in 24 h). What the alert counts is the watchdog
"restarting" a sequencer that is busy with one long upload: `sequencer.start()`
answers "start() while a sequencer thread is still alive -- ignoring", so no
restart ever happened - only an ERROR line and a `sync_guard.restarts` record
per backoff, on a healthy machine uploading 32.7 GB. CR-283C's rule ends that:
a live thread with no way to retire it is not restarted and not recorded, and
says so once at WARNING. The other half of CR-279's open item - that every
other project waits behind a lane A child that is past its budget but still
moving - is NOT fixed here: its own entry calls it "a design decision, not a
patch" (it touches the repath-before-lane-A ordering, AUDIT_2 C-1), and a
time-boxed fix pass is the wrong place for it. It stays open in KNOWN_BUGS,
with the alert noise gone.

### CR-283U (CR-280) - every HTTPS download from the frozen macOS companion fails certificate verification - FIXED in repo, UNVERIFIED (companion/src/ccsync_companion/sidecar_tools.py, app.py)

leso's Mac, first seen 2026-09-07 and still there on 0.9.73:
`CERTIFICATE_VERIFY_FAILED ... unable to get local issuer certificate` for
yt-dlp's SHA2-256SUMS and the ffmpeg / ffprobe / deno sidecars on every start,
so requester-first YouTube downloads have never run on a Mac. The frozen
Python has no CA bundle to load into `ssl.create_default_context()`.
`sidecar_tools.ensure_ca_bundle()` (called once from `run()`, after logging and
before any HTTPS fetch) sets `SSL_CERT_FILE`/`SSL_CERT_DIR` to the first
bundle it finds - `certifi.where()` when certifi happens to be importable,
then the platform's own (`/etc/ssl/cert.pem` on macOS, the Homebrew and Linux
paths after it). `SSL_CERT_FILE` is read by `load_default_certs()` at context
construction, so one call covers EVERY urllib caller in the process: the
sidecars, the yt-dlp checksums, the upgrade channel and the release feed, with
no context threaded through any of them. An environment that already names a
bundle always wins, and no bundle anywhere is a WARNING, never a refusal to
start. **What cannot be verified here**: that a frozen macOS build actually
finds `/etc/ssl/cert.pem` and that leso's downloads then succeed - this rig
has no Mac and PyInstaller does not cross-compile. certifi is deliberately NOT
imported as a hard dependency: it is not in `requirements.lock` and adding one
is a lockfile plus licence-gate change (OWED below). If the Mac build still
fails after this, certifi in the bundle is the next move, not a different
mechanism.

### CR-283V (live-5) - the tray coloured a computer with nothing ticked ORANGE - FIXED (companion/src/ccsync_companion/tray.py)

CR-267f (2026-09-11) made the dashboard treat `no_selection` as informational
(`health.WHY_INFORMATIONAL`) on the owner's words "Alex laptop just happens to
have no synced projects, not an error", and the tray was never given the same
rule: on an editor machine `no_selection` still coloured the icon amber, the
colour every real fault shares, and the line wore the warning glyph.
alex/Razer has been amber since 2026-09-17 with everything working as planned.
The owner restated the rule on 2026-09-18 ("a computer having nothing ticked
is FINE"), so `_BLOCKED_INFORMATIONAL` now exempts `no_selection` from the
colour on EVERY machine, not just the base rig, and `_blocked_line` renders
its sentence as a plain line. Nothing else is softened: every other blocked
reason keeps its colour and its glyph. Nothing is owed on the dashboard side.

### CR-283W (comp-resolve-5, owed in by companion-media) - a refresh-only pass reported "nothing to do" and `attached: 0` - FIXED (companion/src/ccsync_companion/app.py, settings_window.py)

`apply_relinks` answers `refreshed` as well as `relinked`/`failed` - the phase
3 geometry re-read of a clip whose file changed under it, which is what makes
a stand-in replaced by the real original usable - and `_note_proxy_attach`
kept only the other two. So a pass that did nothing but refresh published
`attached: 0, failed: 0`, and every surface reading that block (the Settings
window's RESOLVE section, the tray, the fleet grid) said the pass had done
nothing at all. `refreshed` is now an ADDED key on `_proxy_attach`, never
replacing the two beside it, and the Settings line says "N clips re-read after
the file changed". Companion-only in effect; the key rides inside the reported
`proxy_attach` block, so the dashboard's `ProxyAttachIn` has to declare it or
`ignored_report_sections` opens (OWED below).

### CR-283X (comp-broll-tiers-5, owed in by companion-media) - a stand-in whose editing proxy gave up reached the log and nothing else - FIXED (companion/src/ccsync_companion/app.py, tray.py, settings_window.py)

`broll_standins.given_up_upgrades()` is the list of clips whose editing-proxy
upgrade has failed or has run out of attempts: an editor holding one is
cutting on the 1080p preview believing it is the 6K original, under the
original's own name. `broll_server`'s `GET /status` carries it as
`standins_owed`, which nothing an editor sees reads. `app.standins_owed()`
gives it RES-3's shape - a COUNT and one sentence, never the list, and `{}`
rather than a zero when nothing is owed, which is what clears the line - and
it is rendered in the two places `proxy_attach` already is: the tray's
`resolve_count_phrases` ("2 clips still on a preview copy") and the Settings
window's RESOLVE section, which names the reason and says to send them to
Resolve again. No new tray path, no new thread, no new file. Same wire caveat
as CR-283W: it rides in the reported `resolve_health` section, so
`ResolveHealthIn` must declare it (OWED below).

### CR-283Y (res-fleet-3, companion half) - a move into a project this machine does not sync built an invisible orphan and reported it as done - FIXED (companion/src/ccsync_companion/file_moves.py, app.py)

`db.file_move_target_machines` picks its targets from the SOURCE project's
ticks and never asks about the destination's, so a hand move between two
projects reaches every machine that holds the file - including the ones that
do not sync where it is going. `apply_move` had no plan argument at all and
did `dest.parent.mkdir(parents=True, exist_ok=True)` unconditionally: it built
`P:\Projects\2026\FF5 Talent Gap\...` on an editor who syncs neither, moved
the file in and answered ok/"moved". Nothing in the product writes
`.ccsync-project`, so that directory is invisible to `fixer.list_project_dirs`,
to the media manifest and to both lanes - the file is a permanent orphan on
the editor's disk, filling the disk lane B's 20 GB floor parks on, while the
MOVES history says that computer followed the move.
`docs/HAND_MOVES_ON_THE_SERVER.md` section 4b has always said what to do
instead, and only lane B's relocation path ever did it.

`apply_move` takes an optional `project_rels` (keyword, None default, so the
positional `(move, root, ledger)` every existing caller uses is untouched and
None keeps today's behaviour for an unmanaged companion). When the
destination is not one this machine syncs, the local copy goes to the LANE B
TRASH under its own project path - never deleted, recoverable for the same
fourteen days, aged out by the same `lane_guard.prune_trash` - and the answer
is `ok=True`, "trashed locally, destination not synced here", with no paths,
so nothing relinks Resolve to a file in the trash.

The plan is `sequencer.rel_to_slug_with_borrowed()`, never `rel_to_slug`: a
borrowed subtree is on this disk too, and the selection-only map would grow
comp-sync-4's bug from the other end. The test is on the destination PATH
rather than the destination project, which is what lets one rule cover both -
a selected project's rel is a prefix of everything in it, and a borrowed
entry's key is the lender's subpath, so a move into the borrowed folder falls
under it and a move into the rest of that lender's project does not.

**The state word is gated on the dashboard's own version.**
`FileMoveResultIn.state` is a `Literal` and `file_moves_applied` is NOT one of
`ReportIn`'s tolerant sections, so a word an older dashboard has never heard
of is not a dropped field: it 422s the WHOLE report - the lanes, the presence,
the alarms - every thirty seconds, until somebody upgrades the dashboard. That
is the trap `applying` walked into and answered with "THE DASHBOARD DEPLOYS
FIRST", which is a rule about people rather than a property of the code. So
the companion remembers `dashboard_version` off each report reply (additive,
added by the dashboard builder in the same wave) and sends
`state: "not_synced_here"` only when it parses to 0.7.50 or above; an absent
or unrankable version means an older dashboard and the answer is exactly
today's shape - `ok=True`, the sentence, no state key. The LEDGER records the
word either way: it is this machine's own record, nothing validates it, and
the redelivery after the dashboard is upgraded then says so.

### Verification

Companion venv, run from `companion/`. Every line below fails on the source as
it was before its fix and passes now (the three checked by reverting the hunk
and re-running are marked "reverted and re-run").

- tests/test_bug_hunt_2026_09_18_companion_core.py::test_the_heal_runs_on_a_machine_whose_selection_names_no_project -> fails before (no rescan is ever posted), passes now  (reverted and re-run)
- tests/test_bug_hunt_2026_09_18_companion_core.py::test_a_config_read_that_fails_still_answers_no_project_folders -> guard for the same fix (the no-selection branch must not become an error)
- tests/test_bug_hunt_2026_09_18_companion_core.py::test_a_failed_re_add_keeps_trying_until_explorer_takes_it -> fails before the fix, passes now  (reverted and re-run)
- tests/test_lane_watchdog.py::test_a_wedged_media_tree_thread_is_restarted_on_its_heartbeat -> now also asserts the old thread was retired first; fails before the fix
- tests/test_lane_watchdog.py::test_the_sequencer_bound_is_three_rotations_or_thirty_minutes and ::test_a_wedged_watcher_is_restarted_on_its_heartbeat -> rewritten to the new contract (a live thread with no way to retire it is not restarted and not recorded); both fail on the old code for the new assertions
- tests/test_bug_hunt_2026_09_18_companion_core.py::test_a_retired_media_tree_thread_exits_instead_of_looping -> fails before the fix (the loop took no generation), passes now
- tests/test_bug_hunt_2026_09_18_companion_core.py::test_the_editing_proxy_resume_runs_with_proxy_relink_turned_off -> fails before the fix, passes now  (reverted and re-run)
- tests/test_bug_hunt_2026_09_18_companion_core.py::test_the_resume_still_waits_for_a_local_root -> guard for the same fix
- tests/test_bug_hunt_2026_09_18_companion_core.py::test_a_truncated_history_is_never_what_a_kill_leaves_behind -> fails before the fix, passes now
- tests/test_bug_hunt_2026_09_18_companion_core.py::test_one_bad_stamp_costs_one_stamp_not_the_ceiling -> fails before the fix, passes now
- tests/test_bug_hunt_2026_09_18_companion_core.py::test_a_withheld_build_does_not_retire_the_standing_refusal -> fails before the fix, passes now
- tests/test_bug_hunt_2026_09_18_companion_core.py::test_the_unreadable_id_toast_says_where_the_repair_is -> fails before the fix, passes now
- tests/test_bug_hunt_2026_09_18_companion_core.py::test_a_destination_that_appeared_mid_move_is_a_refusal_not_a_loss -> can only FAIL on POSIX, which is where the defect is (the macOS and Linux runners run this suite); on Windows it pins the behaviour that was already right
- tests/test_bug_hunt_2026_09_18_companion_core.py::test_a_file_moved_into_a_borrowed_folder_is_not_trashed -> fails before the fix, passes now
- tests/test_bug_hunt_2026_09_18_companion_core.py::test_lane_b_asks_with_the_path_and_still_accepts_an_older_callable -> pins the (slug, rel) call and the one-argument fallback
- tests/test_bug_hunt_2026_09_18_companion_core.py::test_no_companion_source_file_carries_latin1_mojibake -> fails before the fix, passes now
- tests/test_bug_hunt_2026_09_18_companion_core.py::test_the_heal_reads_the_folders_own_marker_name and ::test_a_home_relative_folder_path_is_expanded_before_the_marker_test -> both fail before the fix, pass now  (reverted and re-run)
- tests/test_bug_hunt_2026_09_18_companion_core.py::test_toasts_raised_during_registration_arrive_when_the_icon_does -> fails before the fix, passes now
- tests/test_bug_hunt_2026_09_18_companion_core.py::test_the_held_toasts_are_bounded_and_oldest_first -> bounds the queue
- tests/test_bug_hunt_2026_09_18_companion_core.py::test_the_retry_never_writes_a_crash_report -> fails before the fix, passes now  (reverted and re-run)
- tests/test_bug_hunt_2026_09_18_companion_core.py::test_the_recoverable_wording_does_not_send_the_editor_to_a_restart -> fails before the fix, passes now  (reverted and re-run)
- tests/test_bug_hunt_2026_09_18_companion_core.py::test_a_terminal_registration_failure_frees_the_window -> fails before the fix, passes now  (reverted and re-run)
- tests/test_bug_hunt_2026_09_18_companion_core.py::test_a_rehearsal_says_checking_and_moves_its_bar -> fails before the fix, passes now
- tests/test_stills.py::test_the_gallery_moved_line_is_a_path_the_editor_can_open -> fails before the fix, passes now
- tests/test_app.py::test_a_moved_project_folder_reaches_the_report_and_the_one_sentence (the regression-6 line) -> the `or True` assertion is gone; `grep -rn "or True" companion/tests` returns lambdas only
- tests/test_rclone_lane.py::test_a_completed_pass_ends_the_stall_it_is_still_reporting -> fails before the fix, passes now  (reverted and re-run)
- tests/test_rclone_lane.py::test_a_stall_nothing_has_run_past_still_ages_out -> fails before the fix, passes now  (reverted and re-run)
- tests/test_rclone_lane.py::test_the_other_lanes_pass_does_not_end_this_lanes_stall -> guard: lane A and lane B share one record file
- tests/test_bug_hunt_2026_09_18_companion_core.py::test_a_recovered_or_old_stall_is_not_why_this_machine_is_not_syncing -> fails before the fix, passes now
- tests/test_bug_hunt_2026_09_18_companion_core.py::test_the_process_is_pointed_at_a_ca_bundle_when_it_has_none, ::test_an_environment_that_already_names_a_bundle_always_wins, ::test_no_bundle_anywhere_is_a_warning_not_a_refusal_to_start -> the function did not exist before
- tests/test_bug_hunt_2026_09_18_companion_core.py::test_an_editor_machine_with_nothing_ticked_is_green -> fails before the fix (amber), passes now
- tests/test_bug_hunt_2026_09_18_companion_core.py::test_the_nothing_ticked_line_is_not_a_warning and ::test_a_real_blockage_is_still_amber_and_still_warns -> the second is the guard that nothing else was softened

- tests/test_settings_window.py::test_a_refresh_only_pass_and_a_given_up_stand_in_reach_the_settings_window -> fails before the fix (neither line is drawn), passes now  (reverted and re-run)
- tests/test_bug_hunt_2026_09_18_companion_core.py::test_a_refresh_only_pass_is_not_nothing_to_do -> fails before the fix (KeyError: the verdict had no `refreshed`), passes now  (reverted and re-run)
- tests/test_bug_hunt_2026_09_18_companion_core.py::test_a_stand_in_whose_proxy_gave_up_reaches_the_editor -> `standins_owed()` did not exist before the fix; also pins that nothing owed draws no line

- tests/test_file_moves.py::test_a_move_into_a_project_this_machine_does_not_sync_is_trashed -> fails before the fix (the file is moved into a directory that is not a project here), passes now  (reverted and re-run)
- tests/test_file_moves.py::test_the_trashed_outcome_is_recorded_with_its_own_word -> fails before the fix, passes now  (reverted and re-run)
- tests/test_file_moves.py::test_a_move_into_a_BORROWED_folder_is_carried_out_normally -> the guard that the fix does not grow comp-sync-4 from the other end
- tests/test_file_moves.py::test_the_rest_of_a_lenders_project_is_still_not_synced_here -> fails before the fix, passes now  (reverted and re-run)
- tests/test_file_moves.py::test_no_plan_at_all_keeps_the_old_behaviour -> pins the positional signature and the None default
- tests/test_file_moves.py::test_the_app_answers_a_not_synced_destination_with_its_own_state_word -> through the real command path; fails before the fix  (reverted and re-run)
- tests/test_file_moves.py::test_the_state_word_is_withheld_from_a_dashboard_that_would_422_on_it -> fails before the version gate (0.7.49, an absent version and an unrankable one all got the word), passes now  (reverted and re-run)
- tests/test_file_moves.py::test_a_dashboard_that_knows_the_word_is_told -> 0.7.50, 0.7.51 and 0.8.0 are told
- tests/test_file_moves.py::test_the_ledger_keeps_the_word_even_when_the_wire_cannot -> fails before the version gate, passes now  (reverted and re-run)

Suites re-run whole after the edits (all green): test_bug_hunt_2026_09_18_companion_core.py (29), test_rclone_lane.py (125), test_syncthing_lane.py, test_sequencer.py, test_lane_watchdog.py, test_supervisor.py, test_tray.py, test_stills.py, test_popup.py, test_app.py, test_app_contract.py, test_settings_window.py, test_bug_hunt_2026_09_11_comp_ui.py, test_bug_hunt_2026_09_11b_comp_ui.py, test_bug_hunt_2026_09_11b_comp_ytdl_jobs.py, test_bug_hunt_2026_09_18_companion.py (the first wave's). `py_compile` on every source file touched.

### Not fixed

- comp-app-4: declined. The verifier refuted its central claim (the brand helper is used 101 times in app.py, and the product mark on every customer's build is the owner's 2026-08-18 ruling); what is left is one spelling in ~60 sentences across 32 modules, which is more churn than the defect warrants inside a time box. See "Owner decisions".
- CR-279, starvation half: its own ledger entry calls it a design decision (letting the sequencer leave a lane A past its budget but still moving touches the repath-before-lane-A ordering, AUDIT_2 C-1). The alert-noise half IS fixed (CR-283T).
- CR-280 is fixed in repo but cannot be VERIFIED without a Mac build: see CR-283U.

### OWED TO ANOTHER GROUP

- dashboard: `dashboard/src/ccsync_dashboard/api.py`, `_upgrade_info`: add an additive `upgrade_none_reason` (a short string: `retracted` / `needs_newer_dashboard` / `arch_mismatch` / `unknown_platform`) to the report reply on each of the four paths where a package EXISTS but is withheld, so the companion can tell them from "there is nothing to take". Old companions ignore it. THE DASHBOARD DEPLOYS FIRST; until it does, CR-283F is inert and behaviour is exactly 0.9.74's. (comp-app-3)
- dashboard: `dashboard/tests/test_bug_hunt_2026_09_11b_dash_release_jobs.py:329`: delete the `assert not hasattr(settings, "release_feed_sig_url") or True` line - the third neutered assertion, written by the 09-11b fix pass itself. Nothing reads it. (regression-6)
- webapps-tools: `companion/requirements.lock` + the macOS build (`tools/release_macos.sh` / `companion/build.spec`): add `certifi` and bump `tools/check_licenses.py`'s inputs with it, so the frozen Mac bundle carries a CA bundle of its own rather than depending on `/etc/ssl/cert.pem` being where we think it is. `sidecar_tools.ca_bundle_path()` already prefers `certifi.where()` when it is importable, so the code side needs no further change. Companion-only; either side deploys first. (CR-280)
- dashboard: `dashboard/src/ccsync_dashboard/api.py`, `ProxyAttachIn`: declare `refreshed: int | None = Field(default=None, ge=0)`. The companion sends it from 0.9.75 and an undeclared key inside a sub-model is what `ignored_report_sections` exists to catch (live-4 is the same shape). DASHBOARD FIRST. (CR-283W)
- dashboard: `dashboard/src/ccsync_dashboard/api.py`, `ResolveHealthIn`: declare `standins_owed` as a bounded sub-model - `count: int | None = Field(default=None, ge=0)` and `why: str | None = Field(default=None, max_length=300)`, the whole shape the companion sends. Storing it is optional; DECLARING it is not, for the same reason as above. DASHBOARD FIRST. (CR-283X)
- dashboard (already in that group's own list, noted for the join): live-1's dashboard half (`health._why_code`, `alerts._check_lane_stalled` age gate) stops the mails and the red chips FLEET-WIDE in one deploy; CR-283S only clears them for machines running 0.9.75 or later. Deploy the dashboard half first for that reason.

### Deploy order

- Dashboard first, for two reasons: comp-app-3's `upgrade_none_reason` is a dashboard-side key the companion reads, and live-1's dashboard half fixes the whole fleet at once while the companion half only fixes upgraded machines. Nothing here requires a companion ahead of a dashboard.
- **res-fleet-3 (CR-283Y) makes that a hard order, not a preference.** The
  companion only puts `state: "not_synced_here"` on the wire when the report
  reply says the dashboard is 0.7.50 or above, so a 0.9.75 companion against
  today's 0.7.49 is safe - but that gate depends on the dashboard builder's
  additive `dashboard_version` on the report reply landing in the same
  release. If that key is dropped from the dashboard half, the companion
  simply never sends the word (absent means old), which is the safe failure.
  Nothing in this pass sends an unknown state word to an old dashboard.
- Everything else in CR-283 is companion-local and safe against every dashboard in the field (0.7.34..0.7.49): the only wire change is the ABSENCE of `sync_guard.stalled` once a stall is recovered or a day old, which every dashboard already reads as "nothing is stalled".

### Owner decisions

- comp-app-4 (the "CCSync" vs "CC Sync" spelling) is left for you: settling it means editing ~60 sentences in 32 modules and the tests that pin them. My reading is that the vendor build should say "CC Sync" everywhere, as `site.DEFAULT_PRODUCT_NAME` already does, and that it is worth one dedicated pass rather than a corner of this one.
- CR-283S keeps the stall record on disk (stamped `recovered_at`) rather than deleting it, and stops REPORTING it, rather than sending `recovered_at` on the wire. That is what makes the fix work against today's dashboards; if you would rather the dashboard see the recovery explicitly, that is a wire addition and a second deploy.
- CR-283C now REFUSES to restart a wedged watcher (it shares the process-wide stop event, so it cannot be retired without stopping the companion) where it used to spawn a second one. A duplicate watcher is a second unprompted writer into Resolve, so refusing is the safe direction; the cost is that a genuinely wedged watcher stays wedged until the companion is restarted, and the log now says so once.
- One thing NOT on the finding list, fixed because it blocked the tests and is one line: `sync/syncthing_lane.py` imported `syncthing_admin` at module scope while `syncthing_admin` imports three helpers back out of it, so `import ccsync_companion.sync.syncthing_lane` FIRST was an ImportError - the cycle only resolved because something else always imported the other module first. Both uses are inside functions, so the import moved into them.
