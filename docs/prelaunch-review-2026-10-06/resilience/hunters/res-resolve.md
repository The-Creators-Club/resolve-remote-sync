# Pre-launch resilience review - lens res-resolve (Resolve-side failure)

Date 2026-10-06, HEAD 08b40eb + uncommitted working tree, read-only.

**Covered:** `companion/src/ccsync_companion/script_server.py` (whole),
`resolve_bridge.py` (bridge lock/wedge, connect, disconnection explainer,
library walk integration, uid map, save point, replace_clip, link/unlink
proxy, undo replay), `library.py` (locator, both backends, blob decoding,
timeline/pool walks), `resolve_journal.py`, `resolve_undo.py`,
`resolve_prefs.py` (process probe), `bpg.py` launch path, `music_worker.py`
connection, `fixer.fix_clip` relink loop, `popup.perform_fix_all`, the
app.py scripting-dead nag and stale-bridge restart, `resolve_health()` and
the diagnostics bundle, the dashboard's alert registry and fleet grid for
anything Resolve-related; installers/wizard for Resolve edition/scripting
checks; docs INSTALL/EDITOR_SETUP/HOW_IT_WORKS/LIBRARY_WALK_PLAN. Compared
against the 08-28 and 09-03 RES sweeps and KNOWN_BUGS CR-68.

**Not covered:** Timeline Cards role/bridge internals (feature is off
everywhere), b-roll/music insert placement logic, proxy_relink planning
internals, live behaviour of any Resolve build (no Resolve was touched;
claims about Free/None/18.x behaviour are marked PLAUSIBLE).

### res-resolve-1 - A seat with Resolve Free or "External scripting = None" is never detected and is told to restart Resolve
- **Severity:** high
- **Confidence:** CONFIRMED (code path); the exact Free/None runtime answer is PLAUSIBLE
- **Where:** `resolve_bridge.py:362-432` (connect), `:536-604` (NO_SCRIPTING_MESSAGE, describe_disconnection), `app.py:4704-4785` (_maybe_warn_scripting_dead), `tray.py:1806-1824`; `installer/windows_bootstrap.ps1` (no Resolve/edition/scripting check), `onboarding/steps.py` (none); `docs/EDITOR_SETUP.md:7-18`
- **What:** Every Resolve feature needs Studio plus *Preferences > System > General > External scripting using = Local*, a manual per-seat step that only the docs mention. Nothing installs, checks or detects either. With Resolve registered on 1144 (READY) but scripting refused, `scriptapp()` returns None, `connect()` logs it at DEBUG, and the explainer can only say "starting up or shutting down" (10 min) and then "isn't accepting scripting connections. Quit and reopen Resolve... restart the companion". A modal dialog repeats this every 5 minutes. The Windows bootstrap does not even check that Resolve is installed (the macOS one does).
- **Scenario:** a new customer installs CC Sync on 6 seats. Two run Resolve Free and one has never changed the scripting preference. Those three get a nag every 5 minutes telling them to restart Resolve and the companion, which never helps. The out-of-tree guard, proxy attach, b-roll/music/YouTube send and undo are silently off. The admin sees "not connected" in the fleet grid's detail line, with no reason, no "never connected this session" and no alert. If a refused `scriptapp()` also blocks for its ~4 s retry, that happens under `_API_LOCK` on every 3 s poll.
- **Recommendation:** Classify the failure. Keep "READY but scriptapp returned None at every attempt since process start" apart from "connected once, then lost". For the first, say "External scripting is off or this is DaVinci Resolve (free): set Preferences > System > General > External scripting using to Local (Studio required)". Have the wizard and the Windows bootstrap check that Resolve is installed and say which edition and scripting setting are needed. The scripting preference may be settable through `resolve_prefs` the way LUT/Mapped Mount are; verify that live. Report `ever_connected` and the reason category to the dashboard and add an alert kind "Resolve is open but scripting has never worked on <machine>".
- **Known:** none (CR-68 covers the launch-window cause only)

### res-resolve-2 - The library walk is validated on one Resolve build and has no sanity check, so a format difference makes the out-of-tree guard silently blind
- **Severity:** high
- **Confidence:** PLAUSIBLE (absence of check CONFIRMED; trigger is a Resolve version difference)
- **Where:** `library.py:144-216` (decompress_blob/clip_path return ""/None on anything unrecognised), `:691-725` (_load_paths), `resolve_bridge.py:1427-1508` (_library_timeline_items), `:1810-1847` (_library_pool_read); `config.py:803` (`library_walk` default True); `docs/LIBRARY_WALK_PLAN.md` (measured on 21.0.1.11, postgres FF5 only)
- **What:** The watcher and the pool pass read the open project out of Resolve's undocumented database schema. That is on by default and was measured on one build (21.0.1, one postgres library). A renamed table or column raises and falls back to the API, which is fine. But a change in the `Clip` blob (different compression, a different protobuf field order, a different header) makes `decompress_blob` return None and `clip_path` return "", with no error. `_load_paths` returns `{}`, every item is filtered as "no path", and the walk answers `ok: True, items: []`. No warning, no fallback and no source change are visible. The ratio of items with paths is normally low (44 of 994), so nobody would notice.
- **Scenario:** a customer is on Resolve 19.1 or 20.x, or the fleet takes Resolve 21.1/22, and the blob encoding differs. Every timeline and pool walk returns zero clips. Media cut in from the Desktop is never flagged. The editor gets no FIX ALL popup, and the dashboard's out-of-tree alert reads zero. The footage never syncs, and nobody finds out until another editor opens the project to Media Offline.
- **Recommendation:** Add a plausibility gate. If `BtVideoInfo`/`BtAudioInfo` returned rows but zero paths decoded, or a timeline has media-bearing items and none resolve to a path, raise `LibraryUnavailable("format not recognised")` so the API walk answers, and log it at WARNING once. Periodically cross-check the library walk against one API walk (for example the existing `_FULL_WALK_EVERY_POLLS` valve every Nth time) and switch the walk off for the process on disagreement. Record the Resolve version (`GetVersionString()`) with the library state, and keep the walk on only for builds that were measured.
- **Known:** related to 09-03 RES-12 (fallback invisible), not the same defect

### res-resolve-3 - Unprompted and FIX ALL relinks overwrite whatever the clip points at now, with no check that it still points at the path that was judged
- **Severity:** medium
- **Confidence:** CONFIRMED (code); depends on stale input (library trailing unsaved edits, or a popup row hours old)
- **Where:** `resolve_bridge.py:2341-2467` (replace_clip reads `before` but never compares it to an expected old path), `app.py:3559-3615` (_canon_relink_loop), `fixer.py:1531-1561`
- **What:** `replace_clip` short-circuits only when the live path already equals the new one. Callers decide what to relink from a library walk that trails the UI until the next save (Live Save off, 08-28 RES-11) or from popup rows that can be hours old. The live path is not compared with the path those callers judged.
- **Scenario:** a clip sits at `W:\Creators_Club\...\A001.mov`, which is non-canonical. The editor relinks it by hand to a different take and has not saved. The 120 s pool pass reads the stale library path, classifies it NON_CANONICAL and relinks the clip back to `P:\...\A001.mov` (the original take), unprompted. The same thing happens with FIX ALL on a popup left open while the editor fixed the clip themselves.
- **Recommendation:** Give `replace_clip` an `expected_old` argument (it already reads `before` under the lock). On mismatch, return `{"ok": False, "reason": "changed_since"}` without writing, and make every automatic caller and `fix_clip` pass the path they judged.
- **Known:** 08-28 RES-11 (library cannot see unsaved edits, OPEN) is the input side; this compare-and-swap gap is new

### res-resolve-4 - Undo marks a journal "done" after a partial replay, blaming "no longer in the media pool" for transient refusals
- **Severity:** medium
- **Confidence:** CONFIRMED
- **Where:** `resolve_bridge.py:2662-2815` (replay uses `replace_clip(..., tries=1)`; `ok = undone > 0 or ...`; `mark_undone`), `resolve_undo.py:200-212` (ok becomes "done")
- **What:** The replay runs each inverse ReplaceClip once. replace_clip's own docstring says a large project returns "busy" for seconds, so one try is the path most likely to fail transiently. Any failure is counted as "skipped" and the message says those clips "are no longer in this project's media pool". If even one clip was put back, the journal is marked undone and the admin command is answered "done". The tray's "undo last" then skips that journal ("already been put back"), and the remote command is retired.
- **Scenario:** an admin undoes a 158-clip bad auto-relink on a busy editor machine. 120 go back and 38 hit a transient refusal. The dashboard shows "done" and the editor's tray says everything is back. 38 clips stay on the wrong paths, and there is no retry path short of hand-editing JSON.
- **Recommendation:** Use replace_clip's normal retry budget for the replay. Count "refused" apart from "not in the pool". Mark a journal undone only when nothing was refused, or record which entries remain and let the next undo replay only those. Answer "retrying" (not "done") to the dashboard while any entry is refused.
- **Known:** adjacent to 08-28 RES-6 (below), new

### res-resolve-5 - Undo over-counts and leaves clips unrestored when one file is in the pool twice (still open)
- **Severity:** medium
- **Confidence:** CONFIRMED
- **Where:** `resolve_bridge.py:2745-2770` (`by_path.setdefault`, never drops the `new` key)
- **What:** As described in 08-28 RES-6. It is unchanged in the working tree: the second journal entry for the same path finds the already-restored clip, replace_clip answers "Already linked" and `ok`, and `undone` is incremented.
- **Scenario:** a file imported into two bins, both relinked by FIX ALL. Undo says "Put 2 back". One clip is still at the copy, which goes offline for everyone if the copy is later removed.
- **Recommendation:** Map each path to a list of items, pop one per entry, and do not count an "Already linked" answer as an undo.
- **Known:** 08-28 RES-6 - OPEN

### res-resolve-6 - The companion launches Resolve.exe -pg (BPG) without the CR-68 guard, and a BPG-only machine reads as "Resolve running" (still open)
- **Severity:** high
- **Confidence:** PLAUSIBLE (whether -pg spawns its own fuscript on 1144 has never been measured)
- **Where:** `bpg.py:763-835` (maybe_launch: no `script_server` call), `script_server.py:94-110` (is_resolve_name matches BPG's `resolve.exe`), `resolve_prefs.py:128-162` (tasklist on image name only), `app.py:4787-4815` (stale-bridge restart needs `resolve_is_running()` False)
- **What:** BPG is `Resolve.exe -pg`, started by the companion while the editor is away and "never stopped by us". Three consequences. (a) If it brings up a script server, the editor's real Resolve launched afterwards can lose port 1144 and scripting for its whole session. (b) It counts as "Resolve running", so the scripting-dead nag fires every 5 minutes with Resolve closed. (c) The stale-bridge self-restart that protects the next Resolve session (R12) never runs while BPG is up.
- **Scenario:** a base rig or wired editor's companion starts BPG overnight for BRAW clips. In the morning the editor opens Resolve: either scripting is dead for the day, or the editor is nagged with Resolve closed and the stale fusionscript state survives into the next launch.
- **Recommendation:** Do as 08-28 RES-4/RES-5 proposed. Refuse a BPG launch unless `script_server.state()` is ABSENT. Exclude `-pg` processes (the command line is already read by `bpg._cim_command_lines`) from `resolve_process_state()` and from `classify()`. Measure once on a live rig whether `-pg` opens 1144.
- **Known:** 08-28 RES-4 and RES-5 - OPEN; CR-68 "not done (c)"

### res-resolve-7 - Bridge import/environment failures are DEBUG-only and reported as "restart Resolve"; Resolve 18's DaVinciResolveScript likely cannot load under the bundled Python 3.12
- **Severity:** medium
- **Confidence:** CONFIRMED (logging/explainer); PLAUSIBLE (Resolve 18 incompatibility)
- **Where:** `resolve_bridge.py:408-432` (import and scriptapp failures at `log.debug`), `:586-604` (no message for "environment/import broken", although the comment block at :505-513 lists it as a distinct cause)
- **What:** The explainer's own comment names four causes, but only "not running / starting / no server / no scripting" can be produced. A wrong `RESOLVE_SCRIPT_LIB`, a Resolve installed outside `C:\Program Files`, or a `DaVinciResolveScript.py` that does not import under Python 3.12 all show up as "DaVinci Resolve is running but isn't accepting scripting connections". The cause is logged only at DEBUG, below the shipped log level. Resolve 21's module uses `importlib`. Older builds' modules used the `imp` module, which Python 3.12 removed, so on those builds the import would fail on every machine.
- **Scenario:** a customer seat on Resolve 18.6, or Resolve installed on `D:\`. The bridge never connects, the nag says restart Resolve, and the diagnostics bundle says "NOT CONNECTED -- isn't accepting scripting connections". Support cannot tell from the bundle that the import failed.
- **Recommendation:** Log import/environment failures at WARNING once per process, with the module path and exception, and surface them as their own message ("CC Sync could not load Resolve's scripting library: <reason>"). Load `fusionscript` directly with `importlib.machinery.ExtensionFileLoader` rather than trusting the installed `DaVinciResolveScript.py`. Find the install directory from the registry/uninstall key rather than assuming `PROGRAMFILES`. State a minimum supported Resolve version (see res-resolve-9).
- **Known:** none

### res-resolve-8 - Disk-library locator falls back to the Local Database and takes the first same-named project, so it can read a different project's database
- **Severity:** medium
- **Confidence:** CONFIRMED (code); harm PLAUSIBLE (needs a same-named project)
- **Where:** `library.py:315-338` (_find_disk_db), contrast `:631-651` (postgres refuses duplicate names, bug-comp-resolve-8)
- **What:** For a disk library, the locator looks in `Resolve Project Library/<name>/Resolve Projects` and then unconditionally in the Local Database root. It takes the first user directory, alphabetically, that holds `Projects/<project name>/Project.db`. Projects inside project-manager folders are never found. A disk library stored anywhere other than Support (an external SSD or a NAS share, which is the normal place for one) is therefore matched against a same-named project in the Local Database, or in another user's folder. The postgres path refuses that ambiguity, but the disk path does not.
- **Scenario:** an editor migrated "Ep 3" from the Local Database to a library on their SSD and kept the old copy. The pool pass reads the old copy's media pool and offers FIX ALL for clips that are not in the open project. Each copy runs (multi-GB, into the tree, uploaded by lane A) and then the relink fails "not in the media pool". If timeline uids happen to match, the watcher reads the old timeline.
- **Recommendation:** Search only the library the pointer names. If it is not under Support, return "" so the walk falls back. Refuse when more than one candidate `Project.db` exists. Verify the choice by checking that the open timeline's uid exists in that database before trusting it.
- **Known:** none

### res-resolve-9 - No supported Resolve version is stated, recorded or reported
- **Severity:** medium
- **Confidence:** CONFIRMED
- **Where:** no `GetVersion`/`GetVersionString`/`GetProductName` call anywhere in `companion/src`; `docs/INSTALL.md`, `docs/EDITOR_SETUP.md` say "Studio" with no version; `library.py` comments rely on 21.0.1 behaviour (GetCurrentDatabase returns None, log-line formats)
- **What:** The integration depends on version-specific behaviour: GetCurrentDatabase answering or not, the wording of Resolve's log lines that `_info_from_log` regexes, the library schema and blob format, the `ExportProject`/`UnlinkProxyMedia` presence, and the `DaVinciResolveScript.py` shape. Nothing records which Resolve version a machine runs. It is not in the report, the diagnostics bundle or the fleet grid. No minimum or maximum is published for customers.
- **Scenario:** a customer reports "the companion does nothing in Resolve". Support cannot see that the seat runs 18.6 or a 22 beta, and the customer was never told what is supported.
- **Recommendation:** Read `GetVersionString()` and `GetProductName()` once per connection, and put them in `resolve_health`, the diagnostics bundle and the fleet grid. Publish a supported range in INSTALL.md and test the library walk and the bridge against each listed major. Show an unsupported-version note in the tray and on the dashboard.
- **Known:** none

### res-resolve-10 - A third-party scripting client on a customer seat can kill Resolve scripting at launch, and nothing names it
- **Severity:** medium
- **Confidence:** CONFIRMED (no client listing anywhere); mechanism per CR-68
- **Where:** `script_server.py:126-158` (classify sees every ESTABLISHED row on 1144 and discards the pids), `app.py:9545-9547` (diagnostics carry no probe phase or 1144 clients); `docs/GOTCHAS.md` §15
- **What:** CR-68's rule is that every client on the machine must carry the guard, and one unguarded poller kills scripting for the whole session. At a customer site, other tools (MCP servers, asset managers, review tools, the customer's own scripts) are outside our control. When one of them kills the server, the companion's message after 10 minutes is "quit and reopen Resolve, then restart the companion". The other tool does it again on the next launch. The TCP table the probe already reads names every client's pid, but that is never recorded.
- **Scenario:** a studio runs a Resolve automation tool that polls at login. Every morning scripting is dead on that seat, the companion keeps giving restart advice, and support has no evidence pointing at the other tool.
- **Recommendation:** Keep the set of non-companion, non-Resolve pids connected to 1144 (with exe names) from the last probes, plus the probe phase timeline around the launch. Put both in the diagnostics bundle. When the session has never connected and another client was seen in STARTING, say so: "another program (<exe>) connected to Resolve while it was starting".
- **Known:** CR-68 (fixed for our own clients); this gap is new

### res-resolve-11 - The macOS CR-68 probe has still never run against a live Mac
- **Severity:** medium
- **Confidence:** CONFIRMED (status), PLAUSIBLE (impact)
- **Where:** `script_server.py:247-302`; KNOWN_BUGS CR-68 "Not done (a)"
- **What:** The `lsof +c 0 -F pcRnT` parse has never been checked against a real Mac. Every parse failure fails OPEN (UNKNOWN), which on a Mac means connecting during the launch window, the exact CR-68 kill.
- **Scenario:** Mac editors at a customer site get the restart dance CR-68 fixed on Windows, and the log says the probe "could not tell".
- **Recommendation:** Run the CR-68 harness once on a Mac (launch Resolve with a 0.5 s poller, guarded) before selling to Mac seats. Count UNKNOWN answers in `resolve_health` so a blind guard is visible fleet-wide.
- **Known:** CR-68 (a) - OPEN

### res-resolve-12 - FIX ALL keeps copying after Resolve has gone away, and the project-mismatch guard passes with no Resolve
- **Severity:** low
- **Confidence:** CONFIRMED
- **Where:** `popup.py:737-830` (loop; `_open_project_mismatch` treats "" as no mismatch), `fixer.py:1531-1561`
- **What:** If Resolve crashes or is quit during a FIX ALL batch, each later row still copies its file in full. That can be hours over SMB. Its relink then fails with "Resolve didn't answer". Nothing stops the batch on the first disconnection message. The copies are reused later (`find_existing_copy`), so no footage is lost, but the editor waits through every copy for a result that is all failures.
- **Scenario:** Resolve crashes on clip 3 of a 40-clip, 600 GB FIX ALL. The dialog keeps copying for hours, then reports 37 failed relinks.
- **Recommendation:** After a relink returns a disconnection or `_SCRIPTING_ERROR_MESSAGE`, stop the batch before the next copy and say "Resolve closed: N files copied, run FIX ALL again when it is open". Treat an empty `current_project_fn()` as "stop", not as "matches".
- **Known:** none

### res-resolve-13 - The undo journal rewrites the whole file per entry and silently stops at 5000
- **Severity:** low
- **Confidence:** CONFIRMED
- **Where:** `resolve_journal.py:490-534`
- **What:** `record()` reads and rewrites the whole session JSON for every entry, so cost grows quadratically: a 4000-clip pass rewrites up to roughly 1.5 MB thousands of times, on the relink thread. Past `MAX_ENTRIES_PER_SESSION` it returns with no log line (08-28 RES-14), and the edit is still made, so it cannot be undone.
- **Scenario:** a wrong `canonical_prefix` on a large project (the "Energy Transition" shape). The relink pass slows down, and edits past 5000 cannot be undone, with nothing saying so.
- **Recommendation:** Append JSON lines (one entry per line) instead of rewriting, and log a WARNING when the cap is hit. Better still, stop the burst at the cap rather than make edits nobody can undo.
- **Known:** 08-28 RES-14 - OPEN (cap half); the write amplification is new
