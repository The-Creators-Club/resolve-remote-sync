# logic-resolve - Resolve journeys: FIX ALL / relink / undo, LUT link, b-roll and music Send to Resolve, Timeline Cards role (logic + usability)
Files read (approximate coverage): companion fixer.py (all), popup.py (180-840, 930-1000, 1420-1610), resolve_journal.py (1-560), resolve_undo.py (all), resolve_bridge.py undo_last_relink (2572-2700), app.py undo/LUT/diagnostics paths (3401-3440, 5070-5100, 5670-5692, 8736-8756, 9770-9800, 10270-10320), luts.py (all), broll_server.py (686-1420 insert planning + upgrade lane, 2739-2760), music_server.py build_send_response, timeline_cards_role.py (1-200, 310-420), config.py active_project warning, sync/rclone_lane.py lane A scope (3380-3420).
Tests/probes run (companion venv, temp dirs only, nothing live touched):
- p1: `fixer.fix_clip` three times on one source with a relinker that refuses -> three copies `A001.mov`, `A001 (2).mov`, `A001 (3).mov`; `popup.summarize_fix_results` on a partial-relink result -> "0 of 1 copied in, 1 skipped by you".
- p2: `resolve_journal.record` with an injected clock, four FIX ALL relinks with a 10-minute gap before the third -> two journal files of 2 entries each; `describe_latest` names only the last 2.
- read-only `luts.stray_luts` against this rig's Resolve LUT folder and `P:\Assets\Luts` (0 strays today), plus a listing of `P:\Assets\Luts` (it holds Resolve's factory folders).

## Findings

### logic-resolve-1 - RETRY FAILED and "run FIX ALL again" copy the whole file in a second time when only the relink failed
- Severity: medium
- Confidence: CONFIRMED
- Where: companion/src/ccsync_companion/fixer.py:1449-1491 (results that carry `copied_to`), companion/src/ccsync_companion/popup.py:1466-1480 (`_failed_rows` = failures + aborted, retried as whole rows)
- What: `fix_clip` has two outcomes where the copy has landed in the tree but the clip is still not pointed at it: a relink failure (`ok: False`, `copied_to` set) and a relink stopped part way (`aborted`, `partial_relink`, `copied_to` set, message "Run FIX ALL again to finish the rest"). Both go into `_failed_rows`, and RETRY FAILED (or the next popup) runs `fix_clip` again from the start. Nothing checks for the copy already made, so `_claim_destination_path` picks `name (2).ext` and copies the full file again.
- Failure scenario: a 40 GB BRAW whose ReplaceClip returns False (a locked bin, or a .srt, which the memory notes ReplaceClip always refuses), or a clip in two media pool items where the editor pressed CANCEL ALL during the relinks. Each RETRY FAILED press, and each later popup for the same clip, adds another full copy (`A001 (2).braw`, `A001 (3).braw` ...). Lane A uploads every one, and lane C fans them out to every editor on the project. The editor was told to press the button that does this.
- Evidence: probe p1 above (three presses gave three copies). Code: fix_clip always goes through `_claim_destination_path` and has no "reuse copied_to" path. popup:1467 puts these results into the retry set.
- Ledger: new (related to the memory "FIX ALL is copy-only, no relink-to-existing")
- Suggested fix: carry `copied_to` into the retried row and add a relink-only path to fix_clip (verify the size against the source, then relink without copying). At the least, keep rows that have `copied_to` out of RETRY FAILED and say where the copy is.

### logic-resolve-2 - UNDO LAST FIX only undoes the last two minutes of a FIX ALL, and a second press says the clips left the media pool
- Severity: medium
- Confidence: CONFIRMED
- Where: companion/src/ccsync_companion/resolve_journal.py:60-63,386-420 (SESSION_GAP_SECONDS = 120), companion/src/ccsync_companion/resolve_bridge.py:2596-2692 (undo_last_relink replays `latest_session` and never marks it undone), companion/src/ccsync_companion/popup.py:244,1538 (UNDO_POINTER)
- What: journal "bursts" end after 120 s with no edit, and the module says that is "longer than the gap between clips in a FIX ALL". But a FIX ALL relinks each clip right after its own copy, so any copy that takes more than 120 s (about 4 GB at the SMB speed the code quotes, 33 MB/s, or any Google Drive hydration) starts a new journal file. The popup tells the editor "To undo: Settings, RESOLVE, [ UNDO LAST FIX ]", and that button only replays the NEWEST file. Nothing marks a file as undone, so a second press replays the same file: nothing is found at the `new` paths, and the message reads "Put 0 clip path(s) back ... N could not be undone: those clips are no longer in this project's media pool". The earlier bursts of the same FIX ALL cannot be reached from the tray at all.
- Failure scenario: FIX ALL on 12 camera clips of 6-40 GB each gives about 12 journal files. The editor presses UNDO LAST FIX and 1 clip goes back. They press it again and are told the clips have left the media pool, which is false. The other 11 relinks stay, and the button stays in Settings for good. The automatic proxy-relink pass can also start the newest session after a FIX ALL, so "last fix" can be a proxy repoint the editor never asked for.
- Evidence: probe p2 (a 10-minute gap split one FIX ALL into two sessions of 2 entries each). Code reading of undo_last_relink: it does not retire the replayed session, and on a replay `undone == 0` it gives the "no longer in this project's media pool" sentence.
- Ledger: new
- Suggested fix: give each FIX ALL batch one journal session by passing a batch id from perform_fix_all to replace_clip, not by timing gaps. Mark a replayed session as undone so the button moves to the next one or disappears. Give the "already put back" case its own sentence.

### logic-resolve-3 - Share LUTs offers Resolve's factory LUTs, and a Resolve version mismatch turns that into an offer that can never clear
- Severity: medium
- Confidence: CONFIRMED
- Where: companion/src/ccsync_companion/luts.py:266-315 (stray_luts), 451-457 (search_dirs = Resolve's own LUT directory), 346-383 (copy_into_library skips an existing dest), companion/src/ccsync_companion/app.py:10270-10320 (share_stray_luts)
- What: the search directory for "strays" is Resolve's factory LUT folder (`ProgramData\...\Support\LUT`), and that folder also holds everything Resolve ships (ACES, Arri, Blackmagic Design, Canon/Sony/Panasonic ...). Nothing excludes factory content. The first editor to press SHARE copies all of it into the shared library, which the module's own docstring forbids ("a factory LUT copied into the library would appear twice in the LUT browser"). After that, a strays match needs the same name AND size. On any machine running a different Resolve build, whose factory LUT files differ in size, those LUTs count as strays, and `copy_into_library` skips each one because the dest exists. So the tray keeps offering "N LUTs only on this machine", and SHARE answers "Shared 0 LUTs with the team" every time.
- Failure scenario: this has already happened. `P:\Assets\Luts` holds `ACES`, `Arri`, `Astrodesign`, `Blackmagic Design`, `DCI`, `HDR ST 2084`, `Invert Color.ilut`, `Canon Log to Rec709.ilut` ..., the same entries as this rig's factory folder. Every editor's LUT browser now shows each factory LUT twice. An editor on a newer Resolve gets a permanent Share LUTs item that does nothing.
- Evidence: listing of `P:\Assets\Luts` against `C:\ProgramData\Blackmagic Design\DaVinci Resolve\Support\LUT`. Code: stray_luts has no factory exclusion, and copy_into_library increments `skipped` when the dest exists while the next find_strays still reports the item.
- Ledger: new
- Suggested fix: exclude the factory set (Resolve's shipped top-level folders and files, or anything not newer than the Resolve install). Count a name that already exists in the library as shared whatever its size. Separately, the owner should decide whether to remove the factory copies from `P:\Assets\Luts`.

### logic-resolve-4 - With no matched project, FIX ALL's default destination is the tree root, which lane A never uploads, and the dialog still says Fixed
- Severity: medium
- Confidence: CONFIRMED
- Where: companion/src/ccsync_companion/fixer.py:426-442 (pick_project_prefix falls back to "" = tree root), 296-317 (suggest_destination), companion/src/ccsync_companion/popup.py:343-395, companion/src/ccsync_companion/sync/rclone_lane.py (lane A walks only `Projects/<selected rel>`)
- What: the destination falls back in this order: dashboard mapping, then a token match of the Resolve project name against the tree, then `active_project` (blank by default), then "". With "", the suggested destination is `B-roll/Editor Added/<editor>` at the ROOT of local_root, outside `Projects/`. That is the exact place `list_destination_dirs`' own docstring (CORE-H3) says "never reach[es] another editor": lane A only uploads under selected project rels. The dialog header promises that FIX ALL fixes "will NOT sync". The run ends with "Fixed" and closes, and nothing says the copies are still stranded. The only warning is a config-validation log line ("active_project is blank").
- Failure scenario: an editor's Resolve project is called "Rough cut v3" (no token shared with the tree), or two tree projects tie on the match, and the dashboard has no sticky mapping for it. FIX ALL copies 30 clips into `D:\Creators_Club\B-roll\Editor Added\ruskin\` and relinks Resolve there. Everything plays on the laptop, and none of it ever reaches the NAS or the other editors. The dialog promised to solve exactly that.
- Evidence: code path traced (pick_project_prefix -> "" -> suggest_destination without prefix). Lane A's per-rel iteration under `Projects/`. The CORE-H3 note in fixer.list_destination_dirs states the same outcome for bare destinations.
- Ledger: new (the CORE-H3 fix removed the bare dropdown entries but not the bare DEFAULT)
- Suggested fix: when the prefix is "", make the editor choose a project (a dropdown of the dashboard-selected rels) before FIX ALL is enabled, or at the least show a red line saying the chosen folder is outside every project and will not sync.

### logic-resolve-5 - A relink stopped part way is reported as "you skipped it, nothing was copied in or relinked", with no undo pointer
- Severity: low
- Confidence: CONFIRMED
- Where: companion/src/ccsync_companion/fixer.py:1449-1464 (`aborted: True, partial_relink: True, copied_to`), companion/src/ccsync_companion/popup.py:226,1500-1505,1534-1538
- What: CANCEL ALL during the relink loop returns `aborted: True` with a copy on disk and some clips relinked. The popup counts every `aborted` result as a skip. It prints "You skipped: X. Nothing was copied in or relinked for them, and the half-copied files were deleted", while fix_clip's own message for that result says it was copied and N clips were repointed. The undo pointer only appears when some result is `ok`, so a batch where this was the only change shows no way back, although those relinks are journaled and can be undone.
- Failure scenario: an editor cancels during the relinks of a clip used in several media pool items. The screen tells them nothing changed, so they do not check the project and do not undo. In fact the file is in the tree (and uploading) and some clips point at it. Pressing RETRY FAILED then leads into logic-resolve-1.
- Evidence: probe p1 (summarize_fix_results on a partial_relink result gives "0 of 1 copied in, 1 skipped by you"). popup:1500-1505 text.
- Ledger: new
- Suggested fix: treat `partial_relink` as its own outcome in the summary and blocks, show its own message, and show UNDO_POINTER whenever any result has `copied_to` or `relinked > 0`.

## Coverage note
Not reached in depth: proxy_gen.py / proxy_relink.py / proxy_scan.py / proxy_history.py (the auto proxy-link journey and its daily cap), resolve_prefs.py, timeline_cards_bridge.py and most of timeline_cards_role.py after line 420 (health and watchdog), broll_server's upgrade lane after line 1420, and watcher.py's popup triggering and latches. The b-roll insert planning (plan_insert) has been hunted and patched many times (CR-283..CR-288). I read it and found no new logic defect.

## OUT OF TERRITORY
- companion/src/ccsync_companion/popup.py:365: build_popup_rows calls `fixer.list_project_dirs(local_root)` without `extra_rels`, so dashboard-selected projects whose `.ccsync-project` marker has not synced down yet cannot be matched. This adds to logic-resolve-4.
- companion/src/ccsync_companion/app.py:5098 / 8752: "skipped ever" is never decremented when a skipped clip is later fixed, so the diagnostics count grows for ever and cannot tell current strays from historical ones.
