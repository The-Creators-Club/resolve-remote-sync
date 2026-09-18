# verdicts - comp-sync-app

Verifier for `hunters/comp-sync.md` and `hunters/comp-app.md`. All 13 findings
reached. Read-only on the repo apart from this file; the one scratch pytest
file was written into `companion/` for a single run and deleted (git status
unchanged).

## comp-sync-1
- Verdict: CONFIRMED (high)
- Duplicate of: none - but it is the companion half of dash-api-1, whose failure scenario walks through this exact code path from the dashboard side. The two fixes are independent and both are needed.
- Reasoning: `locate()` (dashboard/src/ccsync_dashboard/locate.py:80-101) selects every `nas_media` row across every ACTIVE project with a matching size and basename, with no exclusion of the asking machine's own project or of the path the file was just trashed from. `_relocate_trashed` (rclone_lane.py:4014-4030) treats "exactly one place" as "it moved there" without comparing that place with the source; `_local_destination` then rebuilds bit-for-bit the path rclone just emptied, and `_move_out_of_trash` finds it absent and renames the file back. `as_of` is carried "for the log line rather than for a decision" (server_locate.py:57-60), so nothing anywhere bounds the staleness window. The design doc's own §4a premise is wrong in the same way: for a move (or a delete) NEWER than the last walk the inventory still holds the OLD path, so the answer is "found at the old path", not the "not found" the doc assumes.
- Evidence: reproduced with the suite's own helpers (`_lane_with_trash` / `_locator` / `_found`) with one place naming the SOURCE project and rel_path, run under `companion\.venv`: `restored to the path just trashed from: True / still in trash: False / moved_out_of_trash: 1 / relocations: 1`. The relocation block of `companion/tests/test_rclone_lane.py:2113-2265` has no such case. `grep -an` of KNOWN_BUGS: CR-268b (line 24090) is BUILT and lists its owed work; nothing there covers this.
- Fix note: the suggested fix (drop a place whose `_local_destination` equals the source path, NFC-folded and normcased, and do not add its key to `_server_relocated_keys`) is right and is the one that holds even when the inventory is healthy but merely 14 minutes old. Two other files are involved: `_count_relocations` must not count such a file (same module, `_server_relocated_keys`), and `companion/tests/test_rclone_lane.py` needs the missing case. Note rule 2 of `_count_relocations` already excuses a file the REMOTE LISTING still shows at the same rel path - that rule must be left alone; this is about the dashboard's stale inventory, not the live listing.

## comp-sync-2
- Verdict: CONFIRMED (medium)
- Duplicate of: none
- Reasoning: `_heal_missing_paths(folders)` has exactly one caller, `syncthing_lane.py:711`, and it sits below the `if not expected: return` at :667-684. `expected` is `_effective_folder_ids()` -> `sequencer.expected_folder_slugs()`, which is selection slugs minus upload-only (sequencer.py:810-822) and has never contained a shared or borrowed asset folder id. So on the exact machine shape the docstring names - an editor whose only path-missing folder is `assets-luts` - the heal cannot run. The same early return also fires on a transient empty selection after a restart.
- Evidence: `grep -rn "_heal_missing_paths"` -> definition at :374 and the single call at :711. The CR-278 tests (`tests/test_syncthing_lane.py`, around :863/:890) call `_heal_missing_paths` directly, so no test can see the gate.
- Fix note: hoisting `config = self._get("/rest/config")` + the heal above the early return is correct and safe - the heal needs no selection, is rate-limited by `PATH_HEAL_INTERVAL_SECONDS` and only rescans. It does add one `/rest/config` GET per poll on a machine with no selection; put the fetch in its own try so a config read failure keeps the existing "no project folders to check yet" status rather than turning it into an error. A test must exercise it through `reconcile()` with `expected_folder_ids_fn` returning `[]`, otherwise the gate stays invisible.

## comp-sync-3
- Verdict: DOWNGRADED to low
- Duplicate of: none
- Reasoning: the factual half is right and not refutable - POSIX `rename(2)` replaces an existing destination silently, `FileExistsError` on rename is a Windows behaviour, `sys.platform` is never consulted here, and the Mac companion runs this code. So the docstring's "NOTHING here overwrites ... a destination that appeared between the check and the rename is a refusal rather than a file lost" is false on every Mac in the fleet. What I cannot support is medium: the window is between `dest.exists()` and `os.rename` (microseconds), the writer would have to be another process landing that exact path in that window, and the file it loses is another copy of the same clip (a different-SIZE file present at check time is already refused). The defect that is certain is the false guarantee, which invites the next caller to trust it.
- Evidence: code read of `_move_out_of_trash` (rclone_lane.py:4102-4119); CPython `os.rename` documentation ("On Unix, if dst exists and is a file, it will be replaced silently"). Not reproducible on this Windows rig.
- Fix note: the suggested `os.link` + `os.unlink` is the right shape (it fails with EEXIST on POSIX and is a metadata operation on one volume, which the trash-under-local_root layout guarantees), but it needs a fallback for a filesystem or destination that refuses hard links (exFAT, SMB), and `os.link` on Windows needs the same care - so keep the `os.rename` path there. At minimum the docstring must stop claiming the guarantee. No other file is on the wire; `test_rclone_lane.py`'s "a copy already at the destination" test pins only the checked case, not the raced one.

## comp-sync-4
- Verdict: CONFIRMED (low)
- Duplicate of: none (comp-app's OUT OF TERRITORY note names the same line - same hunt, two hunters, one defect; comp-sync-4 is the reported one)
- Reasoning: `app._project_rel_for_slug` (app.py:4010-4026) iterates `sequencer.rel_to_slug`, which `_build_borrowed`/`_update_known_selection` keep free of borrowed rels on purpose (sequencer.py:472-477, 800-808). A file hand-moved into a subtree this machine borrows therefore resolves to None and stays in `.ccsync-trash` although the folder is on the disk. Real, and low is right: a borrowed subtree is the rarest destination and the cost is a re-download, not a loss.
- Evidence: read of the three sites plus `_build_borrowed` (sequencer.py:1551-1603).
- Fix note: THE SUGGESTED FIX IS WRONG AND WOULD BREAK THE COMMON CASE. `_borrowed_rel_to_slug` maps the LENDER's subpath to the BORROWER's slug (`borrowed_rel_to_slug[sub] = slug`, sequencer.py:1596), so `rel_to_slug_with_borrowed()` contains `{lender_sub: borrower_slug}`. Iterated by `_project_rel_for_slug`, a lookup of the borrower's own slug would return the LENDER's subpath first (the merged dict puts borrowed keys first), planting files from project P under the lender's tree. It also does not fix the stated scenario: locate answers with the LENDER's project slug, which is not a value in that map at all unless the lender is itself selected. A correct fix has to resolve the lender's rel (`sequencer.borrowed_lenders()[lender]["rel"]` plus the declared `subs`) and accept the place only when the server's rel_path falls under a borrowed sub. Touching `sequencer.py`'s accessors is not needed; a new, explicitly-named accessor is.

## comp-sync-5
- Verdict: CONFIRMED (low)
- Duplicate of: none
- Reasoning: the two comment lines carry `C3 85 C2 A0 ... C3 84 C2 8D C3 83 C2 AD`, i.e. `Š`/`č`/`í` decoded as latin-1 and re-encoded as UTF-8 by commit 34a3c8f. Cosmetic at runtime, but it destroys the worked example in the two comments whose only job is to document CR-90.
- Evidence: `git diff 18e69f3..34a3c8f -- companion/src/ccsync_companion/file_moves.py | cat -v` shows only those two lines changed, from `M-EM- imalM-DM-^MM-CM--k` to `M-CM-^EM-BM- imalM-CM-^DM-BM-^MM-CM-^CM-BM--k`. `grep -rl $'\xc3\x85\xc2\xa0'` over every .py and .md in the repo matches `file_moves.py` alone, so the corruption is contained.
- Fix note: the suggested restore is right. Nothing reads these bytes, so no test or wire is involved; worth checking that whatever tool wrote that commit is UTF-8 clean before the next fix pass touches an accented comment.

## comp-sync-6
- Verdict: CONFIRMED (low), with the hunter's own PLAUSIBLE confidence intact
- Duplicate of: none
- Reasoning: `syncthing_lane.py:402` does hardcode `.stfolder` and does require a DIRECTORY, and `markerName` appears nowhere in the product (`grep -rn markerName` over companion, server, installer, bench: no hits), so a folder with a custom marker or a pre-v1.0 marker file never heals. What weakens it: the same `.stfolder` assumption is already systemic - `rclone_lane.py:1113/:1140/:1213/:1321` filter on it and `tray.py:521` reasons about it - so a site with a custom markerName is broken in more places than the heal, and on such a site the heal simply does not fire, which is the pre-CR-278 behaviour rather than a regression. The `~` half is plausible (Syncthing stores the configured path as given) but I did not reproduce it.
- Evidence: reads of the loop and of the five other `.stfolder` sites; `grep -rn "markerName"` -> nothing.
- Fix note: `marker = str(folder.get("markerName") or ".stfolder")`, accepting a file as well as a directory, plus `os.path.expanduser(path)`, is cheap and correct. A fix that claims to make the product markerName-aware must also touch `rclone_lane.py`'s four filter/recreate sites, or say in the comment that it only covers the heal.

## comp-app-1
- Verdict: DOWNGRADED to low
- Duplicate of: none (related to comp-broll-tiers-2 and res-companion-1, which are about the same ledger from the other end)
- Reasoning: the structural claim holds - `_resume_broll_proxy_upgrades` has exactly one call site (app.py:4449), inside `_relink_proxies_once`'s try, below two early returns, and `broll_server.resume_pending_upgrades` needs no Resolve at all. With `proxy_relink_enabled = false` a pending row is never resumed, and the insert path that CREATES the row is not gated on that flag, so the state is reachable. What I refute is the second trigger: `proxy_relink.frame_counter(path)` (proxy_relink.py:285-309) only closes over the path and imports `ffmpeg_tools`; the inner `count` swallows every exception, so a bad `ffmpeg_path` cannot make it raise at construction, and a persistently-raising `plan_relinks` is speculative. That leaves a single non-default config key plus an interrupted download as the whole trigger, which is low, not medium.
- Evidence: `grep -rn "resume_pending_upgrades"` -> app.py:4937 and the definition at broll_server.py:1259, no other caller. `config.py:419` default True, `:1125` in the shipped config template. Read of `frame_counter`.
- Fix note: hoisting the call beside `_relink_proxies_once` at app.py:4155-4156 in its own try is right and independent of both flags. `_local_root_is_broken()` should still gate it in some form (the download destination is under local_root), so hoist the call, not the guard. `companion/tests/test_app.py` has no test that asserts the resume runs, so the fix should add one with `proxy_relink_enabled = false`.

## comp-app-2
- Verdict: DOWNGRADED to low
- Duplicate of: comp-app-5 is the second half of this finding, reported separately
- Reasoning: the asymmetry is real - `write_history` (supervisor.py:196-213) is a bare `write_text` while `write_relaunch_note` (:242-268) eleven lines below is tmp+replace, with a docstring that says why. But the harm needs a kill inside the microsecond window of one sub-100-byte write, and the consequence is bounded: the ceiling resets to zero for one hour, on a build that is already crash-looping, and `merge_history`'s argv source covers the warm chain. Nothing is lost permanently and nothing false is asserted. That is low.
- Evidence: both functions read side by side; `read_history`'s `except Exception: return []` does cover both the parse and the coercion. KNOWN_BUGS line 20471 confirms the 09-11b work fixed the unwritable-file case, not the half-written one.
- Fix note: the suggested tmp+replace is right and matches `write_relaunch_note` byte for byte, including the tmp cleanup in the failure branch. Fix comp-app-5 in the same edit. `companion/tests/test_supervisor.py` pins the return-bool contract from the 09-11b pass; a new test must write a truncated file rather than monkeypatching the writer.

## comp-app-3
- Verdict: DOWNGRADED to low
- Duplicate of: none (the hunter's own OUT OF TERRITORY note points the wire decision at dash-api)
- Reasoning: the mechanism is exactly as described. `_upgrade_info` (api.py:5751-5775) has four `return None` paths in which a package EXISTS but is withheld, `note_report_response` (upgrade.py:1560-1578) reads a reply with no `upgrade` key as "nothing is being refused" and calls `_clear_refusal()`, and `_store_upgrade_guard` (api.py:7988-8012) latches whatever the companion last said, so the chip and the `upgrade_refused` alert go out. What keeps it off medium: in all four states nothing IS being offered, so "refusing X" is arguably stale rather than wrong; and the machine does not disappear - `versions_behind` (alerts.py:3271) still fires on a machine sitting on an old build. What is lost is the ERROR-level "and here is why", in four uncommon dashboard states.
- Evidence: read of both sides in full, plus `_check_upgrade_refused` (alerts.py:2570-2618) and the latch rule's own docstring. Neither regression test in `test_bug_hunt_2026_09_11b_comp_ytdl_jobs.py` builds a reply from a dashboard in one of the four states.
- Fix note: the "add an `upgrade_none_reason` to the reply" half is the right shape but reaches every build in the field, and `_upgrade_info`'s own comment explains why the protocol has no "refused offer" shape - so the change belongs on the DASHBOARD side as an additive key that old companions ignore, with the companion clearing only on its absence. The cheap alternative in the finding ("clear only when running == current can be inferred") is not available to the companion: the reply does not carry the channel's current version when the key is withheld. A fix touches `dashboard/src/ccsync_dashboard/api.py`, `companion/upgrade.py` and the two regression tests.

## comp-app-4
- Verdict: DOWNGRADED to low
- Duplicate of: none
- Reasoning: the count is right (65 `CCSync` literals in app.py, 32 modules) but the central claim - "the vendor-neutral brand helper is used once" - is not. `grep -c "notify_title" app.py` -> 85 and `drive_phrase` -> 13, i.e. app.py routes 101 calls through `site_mod`, and `site.notify_title()` already resolves org_short -> product_name for the TITLE of every balloon and dialog (site.py:405-417). CLAUDE.md's invariant is "no CUSTOMER's name in code", and the owner's 2026-08-18 ruling is the opposite of what this finding assumes: the product mark appears on every customer's build, like Resolve or Premiere. So "CCSync" in body copy is not a leak of a customer's name. The residue that is a genuine defect is the SPELLING: the product is `CC Sync` in `site.DEFAULT_PRODUCT_NAME` and `CCSync` in ~60 sentences, two vocabularies in one dialog whose title may already say "Acme".
- Evidence: the greps above; `site.py:335`, `:372-391`, `:405-417`, `:438-446`.
- Fix note: a `site.app_name()` plus a scan test is more change than the defect warrants and would churn 32 modules for no user-visible gain; the honest fix is to settle one spelling and, where a sentence names the product beside an org-branded title, use the helper. If a scan test is added it must exempt log lines, comments and `CCSync-SubstP` / `X-CCSync-*` (protocol and task names, app.py:4675 and every fleet header), or it will fail on strings that are not copy at all.

## comp-app-5
- Verdict: CONFIRMED (low)
- Duplicate of: comp-app-2 (its second paragraph is this finding)
- Reasoning: `read_history` builds `[float(t) for t in ...]` inside the same try that returns `[]`, while `merge_history`, written in the same pass for the same data, skips a bad item and keeps the rest (`except (TypeError, ValueError): continue`). The two readers of one list disagree. Low is right: only a hand edit or a future field produces a non-float entry (a half-written file produces invalid JSON, which is the comp-app-2 path), and the cost is one hour of ceiling.
- Evidence: supervisor.py:190-194 against :236-240.
- Fix note: correct as suggested, and it should land in the same edit as comp-app-2. Handing the result to `merge_history` regardless is already what `decide`'s callers do; no other file is involved.

## comp-app-6
- Verdict: CONFIRMED (low)
- Duplicate of: none
- Reasoning: the toast (app.py:9109-9116) tells the editor to send their log to their admin and says the file is repairable, and never mentions that Settings has [ repair ] behind a confirm dialog (settings_window.py:479-509). Both halves shipped in the same fix pass. The one counter I looked for is in the button's own comment - "this is the place a HUMAN presses, deliberately - never the toast, because ... a one-click identity change is not a decision to take from a notification" - but that forbids ACTING from the toast, not naming where the repair lives, so it does not refute the finding.
- Evidence: read of both call sites; `grep -rn "remint"` -> the only entry point is settings_window.py:497.
- Fix note: right, and the added sentence must not read as an instruction to press it (the dialog's own "if your admin is still looking at the old file, wait for them" is the tone to match). `ui_copy`/no em dashes apply; `companion/tests/test_app.py` pins the toast text in the comp-app-8 regression test from 09-11b, so that assertion moves with the copy.

## comp-app-7
- Verdict: REFUTED
- Duplicate of: none
- Reasoning: the finding's failure scenario cannot happen. `_cache` is stored at capabilities.py:317 as `dict(section)` BEFORE `jobs_gate` is added at :325, so a cached section never contains `jobs_gate`; `answer = dict(cached[1])` in the cache-hit branch therefore starts with the field absent, and `if gate:` failing leaves it absent, which is precisely the contract `_jobs_gate`'s docstring demands ("ABSENT, not a guess"). No report can carry "the last jobs_gate this process assembled" - there is nothing for an empty answer to fail to displace. The hunter half-saw this ("the practical effect is limited to the first 45 s after a cache fill") but the effect is zero, in that window too.
- Evidence: capabilities.py:277-280 against :313-326; the same ordering comment ("AFTER the cache is stored, like the three above") is what makes it safe.
- Fix note: the suggested `answer.pop("jobs_gate", None)` is harmless but fixes nothing; adding it to the FRESH branch as well would be actively wrong (it would pop a key that was just computed if the pop landed after the assignment). If anything is worth doing it is a comment saying why `if gate:` is safe here, so the next reader does not file this again.
