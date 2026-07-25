# resolve-remote-sync — Audit Round 2

**Tree audited:** working tree at `b989422` ("Fix verified AUDIT.md findings across all subsystems; v0.4.4, installer 1.0.3")
**Date:** 2026-07-25
**Predecessor:** `AUDIT.md` (round 1). This document supersedes nothing in it — round 1 findings that are genuinely fixed are *not* repeated here.

## Brief

Four questions, asked in this order of priority:

1. **Can this software delete anything?** The stated hard requirement is that it must never delete, truncate, or overwrite user data. Any path that can is treated as the top severity class regardless of likelihood.
2. **Functionality and usage bugs** — including whether round 1's fixes actually hold.
3. **UX** — can a non-engineer editor succeed, understand state, and recover without messaging Alex.
4. **Transfer and sync speed** — against the stated target of beating Blackmagic Cloud's observed ~60 mb/s.

## Method

Eight independent auditors, scoped so no two owned the same files, each required to cite `file:line` plus a concrete triggering scenario rather than a category of concern. All read-only; no source file was modified. Empirical verification used the repo's own bundled `companion/.tools/rclone.exe` (v1.74.4) against scratch trees outside the repo.

| Auditor | Scope | Status |
|---|---|---|
| **DEL** | Deletion sweep across all code | ✅ |
| **CORE** | Companion runtime (app/tray/popup/fixer/config/identity/upgrade/consolidate/bridge) | ✅ |
| **DASH** | Dashboard backend (api/db/schema/auth/collector/provision/clients/templates) | ✅ |
| **UX** | Editor-facing experience across tray, popups, dashboard, docs | ✅ |
| **LANE** | `companion/sync/` lanes, sequencer, repath, watcher | ✅ |
| **INST** | Installers, onboard.exe, `server/` scripts, docs-vs-reality | ✅ |
| **PERF** | Transfer/sync throughput | ✅ |
| **REGR** | Adversarial verification of `b989422`'s AUDIT.md fixes | ✅ |

**Test baseline:** companion 536, dashboard 160, onboarding 74, server 24, bench 40 (+4 skipped) — all passing. Green, and — as in round 1 — proving less than it appears to. This document names **five** tests that pass while asserting the wrong behaviour: `test_role.py::test_editor_role_overrides_a_base_flagged_config` (§1 CORE-C1), `test_rclone_lane.py::test_start_is_noop_when_periodic_thread_still_alive` (§5 L-2), `test_auth.py::test_report_marks_machine_verified_with_identity` (§2 DASH-H9), `test_syncthing_admin.py::test_accept_folder_leaves_folder_paused_when_set_ignores_fails` (§5 L-3 — asserts a guarantee its own caller breaks 1 ms later), and `test_syncthing_lane.py::test_check_once_no_expected_folders_is_idle` (§5 L-6).

**Note on the bench suite:** 44 tests collected here (40 pass / 4 skip); round 1's baseline table said 56. `bench/` was untouched by `b989422`, so either that baseline was wrong or the bench venv is silently under-collecting on a missing optional dep. Worth five minutes before anyone says "all green".

## Confidence tiers

- **[verified]** — the orchestrator independently re-read the code or ran a check. Listed in §0.
- **[measured]** — the auditor executed a real command (rclone against scratch trees, PowerShell encoding checks, SQLite migration replays) and pasted the output.
- Unmarked — single-auditor code read, with a required `file:line` + failure path. Treat the **mechanism** as reliable and the **severity** as an estimate.

---

# §0. Independently verified by the orchestrator

These were re-read or re-run directly, not taken on an auditor's word:

| Claim | Anchor | Status |
|---|---|---|
| **The delete guard's own subprocess call never got the UTF-8 fix** — `text=True`, no `encoding=`, while `rclone_lane.py:109,137` did get it | `consolidate.py:144` | ✅ confirmed — and it is the *only* remaining un-encoded rclone call in companion code |
| Structure clone has no hidden-directory filter — will recreate `.stfolder` / `.stversions` | `sync/rclone_lane.py:200-205` | ✅ confirmed — loop guards only `..` and absolute |
| Editor-side Syncthing folders get **no** versioning | `sync/syncthing_admin.py:133` | ✅ confirmed — `"type": "sendreceive"`, no `versioning` key |
| Dashboard role can force-*enable* sync lanes on a base rig | `app.py:632` — `self._sync_enabled = (role != "base")` | ✅ confirmed — non-monotonic |
| Consolidate's lane-A upload runs with `subpath=None` | `app.py:451` (`or None`) → `app.py:489` (unconditional `run_once`) | ✅ confirmed |
| Lane B is a destructive `rclone sync` with no `--backup-dir` | `sync/rclone_lane.py:283-294` | ✅ confirmed |
| Docs promise a *move* where the code *copies* | `installer/START_HERE.md:115` | ✅ confirmed |
| Tray shows green + `OK` when not signed in / paused / disabled | `tray.py:82`, `tray.py:39-45` | ✅ confirmed |

---

# §1. Deletion and data-destruction

The user's hard requirement: **this system must never delete anything.** Findings here are ordered by (blast radius × likelihood). The first three are new — round 1 did not find them — and the first one means round 1's flagship data-loss fix does not work.

## DEL-0 — Round 1's D-1 fix does not hold: one non-ASCII filename blinds the delete guard, and Consolidate deletes proxies while reporting zero deletions — **CRITICAL** [verified + reproduced live]

`companion/src/ccsync_companion/consolidate.py:144`.

**Mechanism.** The D-1 fix works as designed: `parse_dry_run_stats` reads `deletes`/`deletedDirs`, `reconcile_with_nas` sets `skip_lane_b`, and `app.py:492` genuinely honours `lane_b_allowed()`. But the deletes counter is read from `_default_run`'s return value, and `_default_run` is **the one rclone call in companion code that never received the S-6 encoding fix**:

```python
# consolidate.py:144  — compare rclone_lane.py:109 and :137, which both got
#   encoding="utf-8", errors="replace"
proc = subprocess.run(cmd, capture_output=True, text=True, timeout=timeout)
return proc.stderr or ""
```

`text=True` with no `encoding=` decodes using the console codepage (cp1252 here) with `errors="strict"`. rclone logs UTF-8. The decode raises **inside `subprocess`'s own reader thread**, which does not propagate — `communicate()` returns `proc.stderr is None`, exit code 0, no exception. So `_default_run` returns `""`, `parse_dry_run_stats("")` reports `deletes=0`, `skip_lane_b=False`, and `lane_b_allowed()` returns `True`.

**Reproduced live** against real rclone 1.74.4 on scratch trees, with one file named `Proxy/台北_代理.mov`:

```
A. real rclone output decoded utf-8 ....... deletes = 2  → skip_lane_b would be: True
B. what consolidate._default_run returns .. stderr length = 0 → deletes = 0
                                            lane_b_allowed(reconcile) = True
C. dialog shown to the editor ............. "0 proxy file(s) will download from the NAS (0 B)"
                                            "Originals are COPIED, never moved — your files stay put."
D. real lane B run ........................ files remaining locally: ['keep.mov']
```

Both local-only proxies were deleted, while the consent dialog the editor clicked through reported zero deletions. This is round 1's D-1 scenario reproducing *with the fix in place*, and the trigger — a CJK filename — is close to guaranteed in this production context (Traditional-Taiwanese-Mandarin documentary work).

**Fix (one line).** `consolidate.py:144` → `subprocess.run(cmd, capture_output=True, encoding="utf-8", errors="replace", timeout=timeout, creationflags=rclone_lane._win_creationflags())`. That `creationflags` addition also closes the last `CREATE_NO_WINDOW` gap (§7) — Consolidate currently flashes two console windows from the windowed build.

**Second, independent hardening (do both).** Make a zero-length dry-run stderr **fail closed**: if `parse_dry_run_stats` saw no `stats` record at all, set `ok=False` rather than reporting zeros. A guard that reports "0 deletions" when it received no data at all is the shape of defect that produced this finding, and the one-line encoding fix does not prevent the next cause of empty output (timeout, killed process, rclone crash).

**Also note the guard is TOCTOU.** The dry run happens before the confirm dialog and before `run_consolidation()`. Proxies rendered by BPG while the dialog sits open are deleted unwarned.

## DEL-1 — The structure clone recreates `.stfolder`, disabling Syncthing's only mass-delete guard — **CRITICAL** [measured]

`companion/src/ccsync_companion/sync/rclone_lane.py:200-213`, invoked every pass for every project from `sync/sequencer.py:455` → `:476-491`.

**Mechanism.** `clone_directory_tree` lists the NAS project dir with `rclone lsf --dirs-only -R` and `mkdir`s every path returned. Measured against the bundled binary, that listing includes dot-directories:

```
.stfolder/      <-- Syncthing's folder marker
.stversions/    <-- server-side versioned trash skeleton
Audio/ B-roll/ B-roll/Proxy/ ...
```

The loop's only guards are `".." in parts` and `is_absolute()` — nothing filters hidden directories. `.stfolder` is precisely the file Syncthing requires before it will scan a folder. Its absence is the guard that makes "local folder is empty or missing" a *stopped folder with an error* instead of *"the user deleted 5,000 files — propagate that."* The companion recreates it.

**Concrete trigger (normal user action).** An editor's local Syncthing folder has a populated index at `C:\Creators_Club\Projects\2026\CCT\Season 1`. The editor moves or renames that folder — to free disk space, to "back it up" to an external drive, to restore an older copy — or the drive holding `local_root` is briefly a stale empty mount point. Normally Syncthing halts with *"Folder marker missing."* Instead the next sequencer pass (≤10 min) runs `_clone_structure` first, recreating the tree **including `.stfolder`**; `_lane_c_turn` then unpauses the folder; Syncthing scans, finds every indexed file gone, marks them deleted, and propagates the deletions to the NAS **and to every other editor sharing the folder**.

The deleted content is exactly the irreplaceable lane-C set — Audio, AE, GFX, Subs, `.drp` project files, docs (video is `.stignore`d). NAS copies land in `.stversions`. **Editor copies are gone permanently** — see DEL-6.

**Fix.** One line, next to the existing `".." in parts` guard: skip any rel whose parts start with `.` (at minimum `.stfolder`, `.stversions`, `.syncthing.*`, `.stignore`).

## DEL-2 — Lane B is an unguarded `rclone sync` whose filter file is rewritten non-atomically before every run — **CRITICAL** [measured]

`sync/rclone_lane.py:283-294` (`"sync"`, no `--backup-dir`); `:88-91` (`write_filter_file` → `Path.write_text`, i.e. truncate-then-write); `:424-426` (`_ensure_filter_file` rewrites the same fixed path `~/.ccsync/state/filter_down.txt` immediately before every run).

**Mechanism, measured.** With the intended filter, lane B's blast radius is correctly narrow — only `**/Proxy/**` files are deleted at the destination (`local_original_not_yet_uploaded.mov`, `track.wav`, `loose_project.drp` all survived). With a **zero-byte** filter file, the same command deletes everything the source lacks:

```
Deleted: 4 (files), 4 (dirs), 11 B (freed)   # incl. the un-uploaded original and the .drp
```

`--filter-from` is read once at rclone startup, and `write_text` leaves the file at 0 bytes for the duration of the write.

**Concrete trigger.** Two companion processes share that one path: the self-upgrade spawns the new exe and only *then* requests shutdown (`upgrade.py:245-257`), and `windows_upgrade.ps1` taskkills the companion — leaving its `rclone.exe` child alive — then relaunches immediately. The new process's `_ensure_filter_file()` truncates `filter_down.txt` in the exact window where the other process's freshly-spawned rclone parses it. Lane B then runs with an empty filter and deletes every local file the NAS doesn't have: every camera original still queued for lane A (`--min-age 30s`), every `.drp`, everything. Same outcome if a process is killed mid-`write_text` and another rclone starts before the rewrite.

**Fix.** (a) Add `--backup-dir <local_root>/.ccsync-trash/<ts>` to `build_down_command` — measured to convert every lane-B delete into a recoverable move. (b) Write the filter atomically (tmp + `os.replace`), and refuse to build the command unless the file is non-empty and its last rule is `- **`. Better: pass the rules as repeated `--filter` argv entries and drop the file entirely.

**Scope note on round 1.** AUDIT D-1/D-2 hardened *only* the Consolidate path (`consolidate.reconcile_with_nas` + `lane_b_allowed`, honoured at `app.py:492-501`). The **routine** lane-B path (`sequencer.py:466-470`, and `app.py:876-880` in unmanaged mode) has no dry-run pre-check, no delete-count guard, and no backup dir. The destructive verb runs unguarded on a 120 s timer, forever.

## CORE-C1 — A dashboard-supplied `role="editor"` force-*enables* sync lanes on the base rig, pointing a deleting `rclone sync` at the live NAS share — **CRITICAL** [verified]

`app.py:610-632`, enshrined by `tests/test_role.py:69-76`.

**Mechanism.** `_apply_identity_role()` sets `self._sync_enabled = (role != "base")` — unconditionally, ignoring what the config said. So a sign-in by anyone not in `DASH_ADMIN_USERS` **overrides `mode="base"` / `sync_enabled=false`**, and `on_signed_in()` → `_start_lanes()` runs the lanes. On the base rig, `onboarding/steps.py:784-787` forces `local_root = canonical_prefix = T:\Creators_Club` (the live NAS SMB share) and never writes `remote_root`/`lane_b_enabled`, so config leaves `remote_root=""` and `lane_b_enabled=true`.

**Concrete trigger.** An editor — or the admin's own second account, not in `DASH_ADMIN_USERS` — signs in via the tray on the base rig. Lanes start. Lane A `rclone copy T:\Creators_Club → creators_club_sftp:` uploads the entire company tree into that user's SFTP home. Lane B is `rclone sync` **downward** (`sync/rclone_lane.py:283-287`) from the empty home dir into `T:\Creators_Club\Projects\<rel>`, **deleting the NAS's real `Proxy/` files under every selected project.** With `require_login=false` and a stale `identity.json` carrying `role="editor"`, this happens at startup with no user action at all (`app.py:135`).

`test_role.py:69-76` (`test_editor_role_overrides_a_base_flagged_config`) asserts this precise behaviour is correct — **a green test asserting the wrong thing.** Related to AUDIT X-4, but the opposite and far more dangerous direction: X-4 covers only the role *disabling* sync.

**Fix.** Make the role monotonic — it may only ever *disable* sync: `self._sync_enabled = self._configured_sync_enabled and (role != "base")`. Delete or invert that test.

## DEL-3 — `validate_config`'s "errors that STOP syncing" stop nothing; a typo'd `remote_root` makes lane B delete every local proxy — **HIGH**

`app.py:983-995` — errors are logged, assigned to `self.config_problems`, and then `self.start()` runs unconditionally. `config.py:397-421` classifies a blank `local_root` and a blank or non-absolute `remote_root` as errors.

**Concrete trigger.** `remote_root = "/mnt/tank/TheCreatorsPool"` — one path component missing, a plausible typo; blank is AUDIT S-1's scenario. The remote path exists and contains no `Proxy/` dirs at matching rels, so lane B `sync` deletes **every `**/Proxy/**` file under `local_root`, whole-tree** (unmanaged mode passes `subpath=None`). Unrecoverable per DEL-2 (no `--backup-dir`). That is hours of BPG GPU time per project, and every editor on "Prefer Proxies" instantly loses playback of media whose originals they don't hold.

With a blank `local_root`, `Path("") / subpath` yields a **CWD-relative** destination — lane B then syncs into the autostart working directory, and the repather computes `expected` as a relative path (feeds DEL-5).

**Round 1 note.** AUDIT S-1's fix went in on the installer side (seeding `remote_root`). The gate S-1's own analysis called for — *"classifies it as a sync-stopping error but only logs it"* — is still missing.

**Fix.** In `run()`: if `errors`, do not start lanes or the sequencer (mirror the existing `_mark_lanes_pending_login()` pattern), surface it on the tray, keep the reporter and tray alive.

## CORE-C2 — Consolidate's whole-tree refusal covers the dry run but not the actual upload — **CRITICAL** [verified]

`app.py:451` → `app.py:489`.

`consolidate_project` computes `subpath = project_prefix.strip("/")… or None`. AUDIT D-2's fix made `reconcile_with_nas` hard-abort on `None` (`consolidate.py:207-211`), and `lane_b_allowed()` then returns False — closing the lane-B *deletion* half. But line 489 unconditionally calls `self._lane_a.run_once(subpath)` with that same `None`, which builds `rclone copy <local_root> remote:<remote_root>` — **the entire local tree**.

**Concrete trigger.** Blank `active_project`, and the open Resolve project has no server root mapping. The confirm dialog reads `(could not check the NAS: no active project resolved — refusing whole-tree consolidate)` — and still offers the button. The user clicks `CONSOLIDATE & UPLOAD`. Every file under `local_root` uploads to the NAS, unquantified and unmentioned by the dialog they consented to.

**Fix.** `if subpath is None: notify + return` before the confirm dialog, or gate both lane runs on `reconcile.get("ok")`.

## DASH-H1 — A transient `set_ignores` failure permanently leaves a folder with no `.stignore`, and lane C then deletes NAS video — **HIGH**

`dashboard/src/ccsync_dashboard/collector.py:234-241`. AUDIT §11's *"failed `set_ignores` … never retried"* — **not fixed.**

`set_ignores` is called *only* in the `existing is None` branch. If `add_folder` (238) succeeds and `set_ignores` (239) raises, `_timed` catches it, marks the cycle failed, and every subsequent cycle takes the `elif` retarget/label branches (242-256) — which never call `set_ignores`. There is no ignores verification anywhere in the codebase (`grep set_ignores` → one call site, zero tests).

**Concrete trigger.** Syncthing drops one HTTP request while provisioning `2026/CCT/Season 2`. The folder exists; `.stignore` is empty. An editor ticks it. Lane C — bidirectional `sendreceive` (`provision.py:150`) — now indexes `*.braw`/`*.mov` and every `Proxy/` dir, i.e. exactly the content lanes A and B exist to carry. The editor's Resolve or OS removes a local proxy or original, and **Syncthing propagates the delete to the NAS.** Server-side staggered versioning is the only thing between that and permanent loss of camera originals. Also: multi-GB duplicate downloads to every ticked editor.

**Fix.** In the `existing is not None` path, `GET /rest/db/ignores` and re-`set_ignores` whenever it doesn't match `build_stignore_lines()`. Make ignore repair unconditional per cycle.

## DEL-4 / DASH-H2 — The dashboard retargets a Syncthing folder to wherever a marker appears, with no content sanity check — **HIGH**

`collector.py:242-251` — `put_folder` with `path`/`label` swapped in, every 5 minutes.

The retarget fires purely on "marker slug X is at rel R, folder X's path ≠ prefix/R". It never checks that the old path is gone, that the new dir carries Syncthing's own `.stfolder`, or that the new dir's content is remotely comparable to the `nas_inventory_state.n_originals/n_proxies` the dashboard already stores (`db.py:44-54`).

**Concrete trigger.** SPEC tells the host to do folder reorganisations server-side. The admin copies or moves `Projects/2025/FF4/Nuclear` to `Projects/2026/CCT/Nuclear` over SMB. `.ccsync-project` is tiny and copies early, so the provision cycle can fire when 5% of the media has arrived. The folder is retargeted to the half-populated path; the server's Syncthing rescans, marks the ~95% not-yet-copied files **deleted**, and propagates that to every editor sharing the folder. Because the delete originates from the server's own rescan, nothing is written to `.stversions` — and editors have no versioning at all (DEL-6).

Single-directory variant (so the duplicate-slug guard at `:216-230` does not trigger): a move interrupted after `.ccsync-project` and `.stfolder` land but before the 400 GB of media, with the source then removed. Exactly one dir claims the slug; the retarget proceeds; `.stfolder` came along so Syncthing's health check passes.

Secondary outcome when `.stfolder` is *absent*: Syncthing errors the folder ("folder marker missing") and stops syncing — and **nothing in the dashboard surfaces Syncthing folder error state** (`db_status` is consumed for `globalFiles`/`globalBytes` only, `collector.py:427-429`), so the project shows a stale-but-plausible completion % forever.

Chains with AUDIT SEC-7 (editor-writable marker), also unfixed — `read_marker` (`provision.py:77-87`) still does no charset or shape validation on the slug.

**Fix.** Before retargeting, require **both** that the folder's current path no longer exists on disk **and** that `(new_dir/".stfolder").exists()`. Refuse and log loudly when the new dir's media count is < 50% of the stored inventory. Surface folder-error state in `fetch_collector_status`.

## DASH-H3 — Marker self-heal stamps a project's identity into whatever directory happens to sit at the folder's configured path — **HIGH**

`collector.py:192-203`. `_run_provision` step 1 writes `write_marker(local, folder["id"])` for any existing folder whose path is a directory lacking a marker — no emptiness check, no `.stfolder` check, no content check.

**Concrete trigger.** The real `2025/FF4/Nuclear` was moved by hand and its marker travelled with it, but before the next cycle someone (or `/project-setup`'s create flow, `api.py:809-812`) creates a fresh dir at the old path. Self-heal writes slug `2025-ff4-nuclear` into the empty dir. Now two dirs claim the slug, so the duplicate branch (`:216-230`) computes `current_rel` = the empty dir, finds `matching` non-empty, logs "keeping current" — and **the real project can never be retargeted again.** The genuine directory is invisible to discovery forever; the folder points at an empty dir, which is DEL-4's deletion path.

**Fix.** Self-heal only when the dir contains `.stfolder` (proof Syncthing has been serving *this* dir) and no marker for that slug exists anywhere else.

## DEL-5 — Repath re-points the local Syncthing folder even when the directory move failed — **HIGH**

`sync/repath.py:133-153` (`_move_dir`: `dst.exists()` → return; `except OSError:` → "re-pointing anyway"), then `:122` `set_folder_path(slug, expected)`.

**Concrete trigger.** A project is moved server-side. `os.rename` of the local project dir fails — routine on Windows when Resolve, Explorer, or AV holds a file inside it (`ERROR_ACCESS_DENIED` / sharing violation), or when the target already exists. The code then re-points the local Syncthing folder at `expected` — an empty or unrelated directory — while all the content stays at the old path. `_process_project` immediately runs `_clone_structure`, which creates that directory **plus `.stfolder`** (DEL-1). The folder becomes valid-but-empty, and Syncthing propagates deletion of the whole project's lane-C content to the NAS and every other editor.

**Fix.** Call `set_folder_path` only when the move actually succeeded (or when the source was already absent *and* the target holds the folder's content). On failure, leave the folder paused and log for a human. Return a success flag from `_move_dir` instead of `None`.

## L-7 — A `..`- or `\`-bearing `rel_path` moves the editor's project directory *outside* `local_root`, and reaches lane A's source path — **MEDIUM** [measured]

`sync/repath.py:106`, and the same string reaches `sequencer.py:443`.

`expected = str(Path(self.local_root) / "Projects" / Path(*rel.split("/")))` where `rel = item.get("rel_path","").strip().strip("/")`. `strip("/")` does not strip backslashes, and pathlib never collapses `..`. Measured with `local_root=C:\Creators_Club`:

| `rel_path` | resulting `os.rename` destination |
|---|---|
| `../../../Windows/Temp/x` | `C:\Windows\Temp\x` |
| `2026/../../../evil` | `C:\evil` |
| `\evil` | `C:\evil` |

`reconcile` then calls `_move(actual, expected)` — moving the editor's whole project directory out of the tree — and `set_folder_path(slug, expected)` re-points Syncthing at it. The same string reaches `sequencer.py:443` as `subpath` → `Path(local_root) / _local_subpath(subpath)`, which strips only leading/trailing separators, so `..` survives into lane A's `local_side`: `rclone copy C:\ nas:…` under the video filter would upload every video on the editor's C: drive to the NAS — which lane A never deletes.

Reachability is via the dashboard's `projects.label`; a filesystem walk cannot produce `..`, so this needs a DB or API write path with an unvalidated rel. Round 1 graded the identical class of bug in `fixer.py` as HIGH (D-6) and fixed it there; the same guard is absent on both of these paths.

**Fix.** In `_item_is_valid` (both `repath.py:56` and `sequencer.py:61`) reject any `rel_path` whose `/`- and `\`-split segments include `""`, `.`, `..`, a drive letter, or a leading separator; assert `os.path.commonpath([local_root, expected]) == local_root` before moving.

## DEL-6 — Editor-side Syncthing folders are created with no versioning; every propagated delete is permanent on the editor — **HIGH** [verified]

`sync/syncthing_admin.py:129-141`. `accept_folder`'s config sets `type: sendreceive`, `fsWatcherEnabled`, `ignorePerms`, `paused`, `devices` — and **no `versioning` key** (Syncthing's default: none). Server-side folders *do* get staggered versioning (`dashboard/.../provision.py:154-157`, `server/setup_syncthing_folder.py:109-115`). The safety net exists in exactly one direction.

Any of DEL-1/4/5 — or a plain human delete on the NAS, or another editor's delete — removes the file on every editor machine with no `.stversions` copy.

**This is also the single cheapest mitigation for the criticals above.**

**Fix.** Add `"versioning": {"type": "staggered", "params": {"cleanInterval": "3600", "maxAge": "2592000"}}` to `accept_folder`'s config, and PATCH it onto already-accepted folders. If "never delete" is to be literal, also evaluate `receiveonly` / ignore-delete semantics for editor folders — editor deletions currently propagate upward by design (see §1.1).

## CORE-H5 — The D-5 fix introduced a partial-media file that lane C propagates to the NAS and every editor — **HIGH**

`fixer.py:331-334` + `sync/syncthing_admin.py:38-47`.

`fix_clip` copies to `<dest>.ccsync-tmp` then `os.replace`. `STIGNORE_LINES` matches `(?i)*.mov`, `(?i)*.braw` … by **extension**, so `A001.braw.ccsync-tmp` matches nothing — lane C syncs it. Nothing ever cleans up an orphaned `.ccsync-tmp`.

**Concrete trigger.** FIX ALL is copying a 40 GB BRAW when the process dies (self-upgrade shutdown — see CORE-H8 — reboot, or Quit). A 12 GB `A001.braw.ccsync-tmp` is left in `Projects/…/B-roll/Editor Added/<name>/`, and Syncthing uploads all 12 GB of garbage to the NAS and fans it out to every other ticked editor, permanently.

**Fix.** Add `(?i)**/*.ccsync-tmp` to `STIGNORE_LINES` and the rclone filters; sweep stale `*.ccsync-tmp` under `local_root` at startup.

## CORE-H1 — With a blank `local_root`, FIX ALL copies media into the process CWD and relinks Resolve there — **HIGH** [measured]

`fixer.py:308-318`. AUDIT D-6's containment check is a no-op when `local_root` is blank: `Path("").resolve()` == CWD, so `local_root_resolved` becomes the working directory and `_dest_dir_is_contained` happily approves `CWD/Audio/Music`. Measured:

```
fix_clip(src, "Audio/Music", "", [mpi]) -> copied_to 'Audio\Music\take1.mp4'   # under CWD
```

`validate_config` flags a blank `local_root` as an error but `run()` only logs it and starts anyway (DEL-3). With `local_root=""`, `classify_path` returns `OUT_OF_TREE` for **every** existing clip (`paths.py:83,86`), so the popup lists the whole timeline and one FIX ALL scatters the project's media into the autostart exe's working directory — `C:\Windows\system32` for a Run-key launch — relinking Resolve to paths nothing will ever sync.

**Fix.** `fix_clip` returns `ok=False` when `not str(local_root).strip()`; suppress the popup entirely while `config_problems` mentions `local_root`.

## DEL-7 — `fix_clip` TOCTOU: the collision-safe name is chosen before a multi-GB copy, then `os.replace` clobbers whatever arrived meanwhile — **MEDIUM**

`fixer.py:325-334` — `unique_destination_path()` … `copy_fn(src, tmp)` (minutes for a 10 GB original over SMB) … `os.replace(tmp, dest_path)`.

**Concrete trigger.** FIX ALL or Consolidate copies `track.wav` into `Audio/Music`. During the copy, lane C syncs down a *different* `track.wav` from another editor to that exact path. `os.replace` silently overwrites it, and Syncthing then propagates the overwrite fleet-wide — recoverable only from the server's `.stversions`. The `.ccsync-tmp` + replace was AUDIT D-5's fix; it closed the truncated-file hole but opened a silent-overwrite window the pre-existing `while candidate.exists()` loop no longer covers.

**Fix.** Re-run `unique_destination_path` immediately before the replace, or create the final name with `O_CREAT|O_EXCL` first and copy into it.

## CORE-M1 — Closing the popup during FIX ALL releases the lock while the worker keeps mutating the project — **MEDIUM**

`popup.py:318-380`. `_on_fix_all` starts a daemon worker. Closing the X destroys the root, `mainloop()` returns, `show_popup` returns, and `app._show_out_of_tree_popup`'s `finally` **releases `_popup_active_lock`** — while `perform_fix_all` is still copying and calling `ReplaceClip`. A second popup, `scan_whole_project`, or `consolidate_project` can then open and start its own copy/relink pass over the same clips.

**Concrete trigger.** Two overlapping FIX ALLs for the same source name: both `unique_destination_path` calls see `x.mp4` absent (TOCTOU at `fixer.py:239`), both write `x.mp4.ccsync-tmp` (same name), interleave writes, and both `os.replace` into `x.mp4` — a corrupted mixed file under a name Resolve is relinked to. Compounds with CORE-H4.

**Fix.** `root.protocol("WM_DELETE_WINDOW", …)` refusing to close while `self._fixing`; make the tmp name unique (pid/uuid) and `os.open(..., O_EXCL)` the final name.

## DEL-8 — `setup_tree.py` unconditionally overwrites an existing project marker, destroying the project's immutable identity — **MEDIUM**

`server/setup_tree.py:74-76` → `server/common.py:143-157` (`printf '%s' <json> > <base>/.ccsync-project`, as root, no `test -e`). `write_marker.py` is documented as "write (or overwrite)"; `setup_tree.py` is not.

**Concrete trigger.** An admin re-runs `setup_tree.py --project-rel-path 2026/CCT/Nuclear` on a project created at `2025/FF4/Nuclear` — to add template folders after a move. The marker's slug flips to `2026-cct-nuclear`. Every slug-keyed row — selections/ticks, `project_roots` Resolve mappings, completion history, media inventory — is orphaned; the old Syncthing folder is left pointing at a dead path; a brand-new *unshared* folder is provisioned, and editors silently lose the share. Feeds DEL-4 if the marker also lands somewhere partially populated.

**Fix.** In `build_remote_script`, write the marker only when absent (`[ -e marker ] || printf …`), printing the existing slug when it differs. Keep deliberate identity changes in `write_marker.py`, where `--slug` is explicit.

## DEL-9 — Root-level `find … -delete` on an unvalidated `--host-root` — **MEDIUM**

`server/install_dashboard_app.py:268-279` — `sudo sh -c "mkdir -p <root>/app && find <root>/app -mindepth 1 -delete && cp -a …"`. AUDIT D-7's fix (staged file-count check at `:260-267`) correctly prevents a partial upload from gutting `/app`, but nothing constrains `root`: a mistyped `--host-root /mnt/tank/TheCreatorsPool/Creators_Club` deletes everything under `…/Creators_Club/app` as root — no backup, no confirmation. Bounded to an `app` subdirectory, hence MEDIUM.

**Fix.** Require `root` to match `^/mnt/[^/]+/apps/ccsync-dashboard` (or an explicit `--i-know-what-im-doing`), and refuse when `<root>/app` holds anything absent from the last upload's manifest.

## DASH-M9 — Publishing a package silently deletes older build artifacts, before the transaction commits — **MEDIUM**

`db.py:617-631`, called from `api.py:1214-1215`. `prune_companion_packages(keep=2)` runs on every publish, and `_unlink_package_file` unlinks immediately — before `conn.commit()` (1216).

Given the hard no-deletion requirement: (a) rollback further back than two versions becomes impossible, as a side effect of an unrelated action; (b) if the commit fails, the exe is gone while the row survives → `[ FILE MISSING ]` (`admin_packages.html:17`) and a companion that downloads the "current" version 404s (`api.py:1280-1281`).

**Fix.** Commit first, then unlink. Make auto-prune opt-in (`?prune=1`), or archive rather than unlink.

## Lower-severity destructive paths

- **`bench/` purges config-derived remote paths with no scratch-path guard** — *low*. `bench/ccbench/runners/_rclone_common.py:84-88` runs **`rclone purge <remote_root>`** as both pre-clean and post-run cleanup; `runners/robocopy_smb.py:94,102,145`, `matrix.py:126`, `selftest.py:110-111` `shutil.rmtree` config paths. Targets are always `<configured path>/<dataset>/<up|down>`, so a live-tree `remote_path`/`unc_path` — the example config points at `Creators_Club/_bench`, one edit from `Creators_Club` — purges real project subtrees. **Fix:** assert the path's last-but-two component contains `_bench`, or require `--allow-destructive-endpoint`.
- **Onboarding "clean slate" reaches into the media root** — *low*. `onboarding/steps.py:545-598` adds `local_root`, `C:\Creators_Club` and `P:\` as deletion-candidate dirs; `:669-691` deletes/renames matches. Only the three exact names in `COMPANION_FILE_NAMES` are touched, and AUDIT D-9's `role != "base"` guard is present — but that guard depends on the dashboard-supplied role, so a blank or unknown role on an editor-labelled base rig deletes `T:\Creators_Club\ccsync-companion.exe` off the NAS share. **Fix:** also skip any candidate dir that is a network/SMB drive, or whose root differs from `%SystemDrive%`.
- **`upgrade.py:185-193`** writes `<exe dir>/ccsync-companion.new.exe` with `"wb"` and `_replace(exe, exe+".old")` unconditionally — truncating anything already at those two names. Harmless in the canonical `%LOCALAPPDATA%\ccsync\bin`; not harmless if an editor keeps the exe in a working folder.
- **`windows_bootstrap.ps1:716` force-kills `explorer.exe`** to refresh the P: label. Any Explorer-initiated file copy in flight is aborted mid-file, leaving a truncated destination file — which lane A can then upload and, thanks to `--ignore-existing`, never replace. **Fix:** `SHChangeNotify`, or warn first.
- **`db.py:915` / `918-925`** — `purge_nas_media_for_inactive` discards NAS inventory whenever a project flips inactive. A transient Syncthing config regression outliving the 900 s grace therefore throws away the walk results; they rebuild, but MEDIA PRESENCE reads "NAS has 0 originals" in the meantime — maximally alarming exactly when something is already wrong.
- **`_safe_rel` uses a string prefix check** (`api.py:727`): `str(target).startswith(str(projects_dir.resolve()))` would accept a sibling `…/Projects-old`. Not currently exploitable (segments are validated against `/`, `\`, `..`, control chars), but it should be `Path.is_relative_to`.

## §1.1 Intentional deletes — decisions for the user, not bugs

Tests assert each of these, so they are deliberate. Given the hard requirement, each deserves an explicit yes/no:

1. **Lane B mirrors server renames by deleting the old local name** — `companion/tests/test_rclone_filters.py:405` (*"old name must be deleted locally"*). This is *why* lane B is `sync`, and the only reason a destructive verb exists in the routine path. A `--backup-dir` (DEL-2) preserves the behaviour while making it recoverable.
2. **Lane C propagates deletions both ways** (`sendreceive` at both ends). Server folders carry staggered versioning with `maxAge` 1 year; editor folders carry none (DEL-6). SPEC "Flaws #2" documents the asymmetry as a rule editors must know. This is currently the system's largest *intended* delete surface.
3. **Consolidate deliberately aborts lane B when a dry run reports deletions** — `consolidate.py:229-251`, `test_consolidate.py:156-192`. Good precedent; not applied to routine lane B.
4. **Dashboard retention** — `db.prune` (completion/lane/missing-file/media/transfer history, 30 d), `purge_nas_media_for_inactive`, and **companion package auto-prune to current+2**, which deletes older published exes from `/data/packages` (DASH-M9).
5. **Onboarding/uninstall removal** — companion exes, HKCU Run values, the `CCSync-SubstP` task, `%LOCALAPPDATA%\ccsync\bin`, and with `-Full` the Syncthing identity + `~/.ccsync`. Deleting `syncthing-config` discards the device identity and index — files survive, but re-approval is needed.
6. **`identity.sign_out()` deletes `identity.json`** — credential, not data.
7. **`--recreate` deletes and re-creates the TrueNAS app** (`install_dashboard_app.py:286-294`, `remove_ix_volumes: False`) — host `app/` + `data/` survive.

## §1.2 Verified clean — do not re-audit

- **Lane A is `copy` + `--ignore-existing` + `--min-age 30s`, never `sync`/`move`** (`rclone_lane.py:250-265`). No rclone `move`/`moveto`/`delete`/`deletefile`/`rmdir`/`rmdirs`/`--delete-*`/`--delete-excluded`/`--track-renames` anywhere in companion or dashboard code. Lane B's filter scoping re-verified empirically: only `**/Proxy/**` is deleted; originals, audio and `.drp` at the destination are untouched. A missing filter file makes rclone exit CRITICAL before doing anything; a missing source dir makes `sync` fail with "directory not found" and delete nothing.
- **`fixer.fix_clip` never deletes or moves the source.** `_dest_dir_is_contained` correctly rejects absolute, drive-relative and `..` destinations across drives (D-6 fixed — but see CORE-H1); tmp+replace prevents truncated finals (D-5 fixed — but see DEL-7, CORE-H5); `unique_destination_path` never overwrites.
- **`repath._default_move` is `os.rename`, not `os.renames`** — no parent pruning, `local_root` can't be removed (D-3 fixed, regression-tested at `test_repath.py:109`). `_item_is_valid` in both `repath.py:56-68` and `sequencer.py:61-72` blocks a null/blank `rel_path` reaching a path join (D-4 fixed).
- **`consolidate.reconcile_with_nas` hard-aborts on a blank subpath** (D-2's dry-run half fixed — but see CORE-C2) and separates delete objects from transfer objects (D-1 fixed); `app.py:492-501` genuinely honours `lane_b_allowed`.
- **The dashboard never removes a Syncthing folder or unshares a device destructively.** `syncthing_client` has no delete verb; `_run_enforce` read-modify-writes only `devices`; `_run_provision` never deletes (`test_provision.py:173` proves a vanished dir leaves the folder alone); `put_folder` always writes back the live dict, so `versioning`/`ignorePerms` survive.
- **Dashboard filesystem writes on the rw `/projects` mount are create-only.** `create_tree_project` / `adopt_folder` / marker self-heal only `mkdir` and write a marker when absent or slug-identical; `provision.write_marker` is tmp+`os.replace`; nesting, duplicate-slug and identity-collision cases raise `ProjectSetupError` rather than guessing.
- **Package publish** streams to `<name>.part` + `os.replace`, filename derived server-side from a `^\d+\.\d+\.\d+$` version (no traversal), sha256-verified before anything becomes visible, 409 on version reuse, current version undeletable.
- **SQLite**: no `DROP TABLE`; migrations are `CREATE TABLE IF NOT EXISTS` / `ADD COLUMN` under `user_version` gating; every `DELETE FROM` is a scoped retention or replace-set statement.
- **Installers**: `windows_bootstrap.ps1` and `macos_bootstrap.sh` guard every config write with an existence check (rclone.conf is *appended* with explicit UTF-8-no-BOM; `config.toml`/plists written only when absent). `Remove-Item -Recurse -Force` is confined to `$env:TEMP` extract dirs; `New-Item -Force` is used only on directories, and the registry-key case explicitly avoids the value-wiping `-Force` (`:701-707`). `windows_uninstall.ps1` never touches `C:\Creators_Club`, detects a real NAS-mapped `P:` and leaves it alone (D-8 fixed). `windows_upgrade.ps1`'s config migration is line-preserving. No `robocopy /MIR|/PURGE|/MOV|/MOVE` anywhere (bench uses `/E`).
- **Server scripts**: `setup_tree.py` is `test -d`-guarded `mkdir -p` + `chown -R`/`chmod` only (no `rm`, no `find -delete` on the tree); `accept_device.py` read-modify-writes the devices list; `install_syncthing_app.py` has no destructive call.
- **Companion misc**: `watcher.py`, `popup.py`, `manifest.py`, `selection.py`, `reporter.py`, `tray.py`, `sync/syncthing_lane.py` contain no filesystem-destructive call; `config.ensure_config_exists` is existence-guarded; `sequencer.stop/pause` unpause-sweeps are ordered against `_in_lane_c_turn` (AUDIT §4 fixed) so folders can't be left stuck paused; the stderr reader kills rclone rather than deadlocking (S-6 fixed).

---

# §2. Functionality and silent-failure bugs

## Companion runtime

### CORE-H2 — `setup_logging()` is itself unguarded, so a bad `log_path` still makes the windowed exe vanish with no log, no tray, no toast — **HIGH** [measured]

`app.py:1051`. AUDIT S-10's fix is incomplete: `run()`'s first statement after `load_config()` is `setup_logging(cfg)`, outside any `try`. Measured:

```
log_path = 5                        -> TypeError
log_path = ["x"]                    -> TypeError
log_path = "Q:\nope\dir\...log"     -> FileNotFoundError [WinError 3]
log_path = ""                       -> PermissionError [Errno 13]
```

`resolved_log_path` does `Path(cfg["log_path"])` with no type coercion (`load_config` coerces only list fields), and `setup_logging` does `log_path.parent.mkdir(parents=True)`. A hand-edited or installer-written `log_path` on a drive not yet mounted at logon reproduces the exact S-10 symptom the fix was written to eliminate.

**Fix.** Wrap `setup_logging` in `try/except` falling back to `config_mod.DEFAULTS["log_path"]`; validate `log_path` is a non-blank str in `validate_config`.

### CORE-H3 — FIX ALL can report success for media that is never uploaded — **HIGH**

`popup.py:190` + `fixer.py:211-228`. AUDIT §6's "un-prefixed dropdown defaults" — **not fixed.** `PopupDialog.__init__` still calls `fixer.list_destination_dirs(local_root, "")` — no `project_prefix`, and a hardcoded empty `editor_name`. The dropdown therefore offers bare `Audio/Music`, `B-roll/Stills`, `B-roll/Editor Added/Unknown` alongside the correctly-prefixed suggestion, plus every directory in the tree.

**Concrete trigger.** The editor picks `Audio/Music` from the list. The file lands at `<local_root>\Audio\Music\track.mp3` — outside `Projects/` — so `_project_rel_for_path` yields None, the watchdog drops the event, and no `run_once(subpath)` ever covers it. The dialog says "Fixed", Resolve plays it locally, and no other editor ever receives it. The `Unknown` label also contradicts the real suggested destination in the same window.

**Fix.** Pass the row's `effective_prefix` and `editor_name` into `list_destination_dirs`.

### CORE-H4 — Nothing serialises the Resolve API; four threads call it concurrently — **HIGH**

`resolve_bridge.py` (whole module — no `threading` import). AUDIT §6 — **not fixed.** Callers: the watcher (`get_timeline_items` every `poll_interval`), the media-tree thread (`get_media_pool_items` every 120 s, `app.py:600-607`), tray daemon threads (`scan_whole_project`, `consolidate_project`), and the FIX-ALL worker (`replace_clip`, `popup.py:341-345`).

**Concrete trigger.** FIX ALL is 3 clips into a 30-clip batch calling `ReplaceClip` while the watcher poll and the media-tree refresh both re-enter `scriptapp("Resolve")` and walk the same `fusionscript` C extension. The module's own `_pin_frozen_python3_home` docstring documents this DLL faulting `0xc0000005`. A segfault takes the whole companion down with **zero** log output (windowed build, `sys.stderr is None`).

**Fix.** Module-level `threading.RLock` around `connect`, `get_timeline_items`, `get_media_pool_items`, `replace_clip`.

### CORE-H6 — The rollback copy is deleted before the new build has proven it works — **HIGH**

`app.py:975` + `upgrade.py:69-88`. `CompanionApp.run()` calls `cleanup_old_exe()` as its third statement — before `validate_config`, before `start()`, before the tray. Nothing restores `.old` if the new build fails.

**Concrete trigger.** An admin publishes a build that crashes in `CompanionApp.__init__` (CORE-M4's unvalidated `poll_interval`, a bad bundled dep, an AV hold on a bundled DLL). The new exe starts, deletes `ccsync-companion.exe.old`, then dies. The Run-key autostart now points at a permanently broken exe; the machine has **no working companion and no rollback copy**, silently drops off the fleet grid, and the only fix is re-running the installer on the editor's machine. If it crashes *earlier* than line 975, `.old` survives but nothing renames it back and the autostart still targets the broken name.

AUDIT §5's `.old`-race finding is also unfixed (single-attempt `unlink`; the stale "Update complete — now running v0.4.4" toast still fires on an unrelated later restart).

**Fix.** Move `cleanup_old_exe()` to after the tray starts (or behind a ~60 s uptime timer), retry the unlink, and derive `just_upgraded` from a version marker file rather than the unlink result.

### CORE-H7 — `_rollback` can leave the machine with no exe at the companion's own path — **HIGH**

`upgrade.py:259-270`. AUDIT §5's `_rollback` finding — **not fixed.** Still `except OSError`, still leaks the download. `_replace` is an injectable callable and `os.replace` can raise non-`OSError` (e.g. `TypeError`/`ValueError` from a surrogate path, or any wrapper). A raise inside `_rollback` escapes `_apply_inner` → `apply()` (whose `finally` only clears `_applying`) → `app.apply_upgrade()` (no try, `app.py:836`) → `tray._show_update_dialog` (no try around line 279). The tray daemon thread dies to invisible stderr **while `exe` does not exist** — renamed to `.old`, with the new build parked at `.new.exe`. The ~20 MB `.new.exe` is never unlinked after a spawn failure. `test_upgrade.py:180-197` asserts the restore but checks neither.

**Fix.** `except Exception` in `_rollback`, unlink `aside` after a successful restore, wrap `apply_upgrade` in the tray callbacks.

### CORE-H8 — The update dialog's own failure path applies the upgrade with no confirmation, killing an in-flight FIX ALL — **HIGH**

`tray.py:219-279`. `_show_sign_in_dialog` and `_show_update_dialog` each create their own `tk.Tk()` on a tray daemon thread with no reference to `app._popup_active_lock`, which `popup.show_popup` / `confirm_dialog` / `ProjectSetupPrompter` all honour. The code's own comments state that `tk.Tk()` *"can raise (or wedge Tcl) when other Tk roots have run on sibling threads in this process — seen live 2026-07-25"* — i.e. the failure is caused by exactly the condition the lock exists to prevent. And on that failure the handler calls `app.apply_upgrade()` directly (`tray.py:226`, `:274-276`).

**Concrete trigger.** The fixer popup is open (or was, this session) copying 60 GB via FIX ALL. The editor clicks "Update now". `tk.Tk()` raises. The upgrade downloads, swaps the exe, and calls `request_shutdown()` with **no confirmation dialog ever shown**. The main loop exits ~1 s later and the daemon FIX-ALL thread is killed mid-`shutil.copy2`, leaving CORE-H5's partial `.ccsync-tmp` and a project where some clips are relinked and some are not.

**Fix.** Acquire `_popup_active_lock` (non-blocking) in both dialogs; on dialog failure, notify and abort rather than applying; refuse `apply()` while `_fixing` or consolidate is in flight.

### CORE-H9 — Project-root mapping silently degrades to a token guess, and is frozen for the process lifetime on base rigs — **HIGH**

`selection.py:179-216`. AUDIT §6 — **not fixed.** On any failure `get_project_roots()` returns `{}` and `popup.build_popup_rows:92-97` falls through to `fixer.match_project_dir`'s token-overlap guess, so during a dashboard outage the *same* clip gets a *different* destination than five minutes earlier. Additionally `_last_response` is set once by the base-rig one-shot fetch (`:190-199`) and, because the sequencer never runs there, is never refreshed — after an admin re-maps a project root, the base rig keeps filing media under the old root until restart, with no indication.

**Concrete trigger.** Admin corrects a project root; the base-rig operator runs Consolidate; gigabytes are copied and lane-A-uploaded under the stale or guessed `Projects/2025/FF4/Nuclear` instead of the mapped root.

**Fix.** Distinguish "no mapping" from "unreachable" and block destination resolution in the latter; TTL the cached response.

### Companion — medium

- **CORE-M2 — the popup still blocks the watcher thread, and the snooze is written before the lock is attempted** (`app.py:296-319, 339-365`; AUDIT §5 not fixed). The editor leaves the popup on screen over lunch: `last_resolve_project` freezes (the dashboard reports a project already closed), no further out-of-tree detection, `_stop_event` unobserved (so shutdown/self-upgrade can't stop the watcher cleanly), and `ProjectSetupPrompter` starves on the same lock. A batch that loses the lock race is snoozed the full 300 s despite never being shown. **Fix:** dispatch the popup on its own daemon thread; stamp the snooze after acquiring the lock.
- **CORE-M3 — the no-display fallback docstring lies, and `PopupDialog.__init__` leaks a Tk root** (`popup.py:436-457`; AUDIT §5 not fixed). The docstring promises items are "auto-ignored so we don't spin forever re-popping the same clips"; the `except` branch only `print()`s (a no-op when `sys.stdout is None`) and never touches `ignore_tracker`. `self.root = tk.Tk()` at `:176` is never `destroy()`ed if a later line raises — so every 300 s snooze expiry leaks another partially-built root, which is exactly the state that makes subsequent `tk.Tk()` calls fail (CORE-H8).
- **CORE-M4 — the numeric validation loop omits every key that actually crashes construction** (`config.py:480-491`). Measured: `poll_interval="fast"`, `transfers="four"`, `scan_interval_up="soon"`, `watch_debounce_seconds=None` all yield `errors == []`, then raise inside `CompanionApp.__init__`/`_build_lanes` (`app.py:218`, `:263-266`). `run()`'s own comment at `app.py:1044-1046` names `poll_interval = "fast"` as the case it protects against.
- **CORE-M5 — AUDIT S-7's trap survives in the reference config** (`config.example.toml:148`). `DEFAULT_TOML_TEXT` correctly comments `sync_enabled` out so `MODE_PROFILES["base"]` can apply; the example still writes `sync_enabled = true` (and `lane_b_enabled = true` at `:143`), and its own header says it may be "copied by hand and edited". Anyone following it with `mode = "base"` gets a dead profile — full sync lanes on a machine whose `local_root` is the NAS share (CORE-C1's blast radius).
- **CORE-M6 — `PYTHONHOME`/`PYTHON3HOME` leak into every child process, including the self-upgrade spawn** (`resolve_bridge.py:80-82`). `upgrade._default_spawn` filters only `_PYI*`/`_MEI*` (`upgrade.py:300-304`) — precisely because of the vanished-extraction-dir failure documented there — but passes `PYTHONHOME` pointing at the **outgoing** process's `_MEI…` dir, which the bootloader deletes seconds later. Also inherited by every `rclone` child, `os.startfile`, and `webbrowser.open`.
- **CORE-M7 — no single-instance guard anywhere in the companion.** No mutex, lock file, or pid check. Two instances = two watchers hammering the Resolve API from four more threads (CORE-H4), two rclone lane sets writing the same tree and the same `state/` files, two reporters POSTing under one identity, two competing self-upgrades renaming the same exe. Trigger: the editor double-clicks the desktop exe while the Run-key instance is live — the most likely action after "it looks like it's not running".
- **CORE-M8 — the `try/finally` that runs `shutdown()` starts after `start()` and the tray block** (`app.py:995-1026`). `self._watcher_thread.start()` (`:950-953`) and `timer.start()` (`:1025`) are unwrapped. An exception there propagates past `run()` with `shutdown()` never called: daemon threads die with the process, but the `subprocess.Popen`-spawned **rclone children are not daemons** and keep transferring against the tree after the companion is gone.
- **CORE-M9 — every tray callback spawns a bare `threading.Thread` with no `try/except`** (`tray.py:291-326`). `consolidate_project` in particular is not exception-safe. The editor clicks "Consolidate pre-existing project…", nothing at all happens, and `companion.log` has no entry — indistinguishable from a dead tray.
- **CORE-M10 — an absolute `upgrade.url` from a plain-HTTP report response is followed to any host, and the sha256 that "verifies" it comes from the same response** (`upgrade.py:99-110, 174-179`). `dashboard_url` defaults to `http://100.71.216.3:8480`. Anyone able to answer or alter one `POST /api/v1/report` response can hand the companion an arbitrary exe **plus** its matching hash, which is renamed over the running companion and launched detached. Tailnet-only limits exposure; the code offers no origin check at all. **Fix:** require the `url` to be relative, or to share `dashboard_url`'s scheme+host+port.
- **CORE-M11 — token expiry is never re-checked on a timer** (`identity.py:132-143` + `app.py:610-632`; AUDIT §5 not fixed). At the instant the token expires: `editor_identity()` → None, the reporter silently skips every cycle so the machine vanishes from the fleet grid, `_apply_identity_role()` is *not* re-run so the lanes keep running under the stale role, and `effective_mode()` silently reverts to config `mode`. Clock skew produces the same state instantly, reported as "dashboard returned a malformed or already-expired token" with no hint that the clock is the cause.
- **CORE-M12 — no ceiling on `local_manifest` + `media_tree` against a hardcoded `timeout=5.0`** (`reporter.py:207-218`). A 2000-clip project's media tree plus per-file manifest will exceed 5 s on any real WAN link, so those two sections never reach the dashboard — one WARNING for the whole streak, then DEBUG forever.
- **CORE-M13 — Consolidate ignores `_sync_enabled`, `_paused` and `config_problems`, and holds `_popup_active_lock` for the whole copy** (`app.py:417-502`). Lane A runs even on a `sync_enabled=false` base rig where `remote_root` is blank, and even while the user has Pause ticked. The lock is held across `run_consolidation` — potentially hours — during which every watcher popup is dropped with "A popup is already open" and the new-project prompt starves.

### Companion — low

- `tray.py:406` — `_ccsync_stop` is never assigned anywhere in the repo (AUDIT §5 unfixed, re-verified). The 5 s refresh thread outlives `icon.stop()` and keeps calling `app.lane_statuses()` and assigning `icon.menu` on a dead icon through the entire shutdown/self-upgrade window.
- `app.py:108, 993` — `config_problems` is written and never read (AUDIT §5 unfixed). The comment at `:106-108` claims it's "surfaced in the tray tooltip"; `tray.py` never references it, so a half-configured install is invisible unless you open the log.
- `app.py:84, 317` — `_popup_snooze` grows without bound: one interned path string per distinct out-of-tree clip ever seen, never evicted.
- `project_setup.py:109-115` — `_prompt_in_flight` can stick `True` for the process lifetime: set before `Thread.start()`, cleared only in the worker's `finally`. If `start()` raises, the once-ever new-project prompt never fires again.
- `resolve_bridge.py` — still no logger at all. A wrong `RESOLVE_SCRIPT_LIB`, a missing `fusionscript.dll`, and a failed import are indistinguishable from "Resolve isn't running": same message, nothing in the log, impossible to diagnose remotely.
- `fixer.py:331` — the `.ccsync-tmp` suffix adds 11 characters, so a `dest_path` that fits inside `MAX_PATH` can now fail where the pre-D-5 direct copy succeeded. A PyInstaller exe does not necessarily inherit `python.exe`'s `longPathAware` manifest.
- `selection.py:121-130` — `_write_cache` uses a bare `write_text` (truncate-then-write) while `identity.save_identity` correctly does tmp+replace. A crash mid-write leaves a truncated `selection.json`; a dashboard outage right afterwards leaves the sequencer with no selection at all.
- `identity.py:234-257` — `_identity` is read from the reporter thread and reassigned from tray threads with no lock; a `sign_out()` landing between the guard and the `.get` raises `AttributeError`. Currently contained by the reporter's per-getter `try/except`.
- `build.spec:88` — `upx=True` on a self-updating, unsigned exe maximises AV heuristic hits, and an AV quarantine of the freshly-renamed exe is the one failure mode CORE-H6 has no recovery from.
- `upgrade.py:169-203` — the download has no size ceiling and no free-space check.
- `app.py:955-966` — `shutdown()` never joins the watcher or media-tree threads, so a self-upgrade can exit the process while `get_media_pool_items()` is inside the `fusionscript` C extension.

## Dashboard

### DASH-H4 — The one-shot selection seed sets its "done" flag even when it seeded zero rows, and the next enforce cycle unshares every editor from every folder — **HIGH**

`collector.py:300-309`. The meta flag is written unconditionally after the loop. `test_seed_once_from_existing_shares` (`tests/test_enforce.py:33`) covers only the happy path.

**Concrete trigger.** First container start races Syncthing's own startup. `GET /rest/config` returns 200 with the device list not yet loaded (or the admin hasn't approved devices yet). `seeded = 0`, flag set, `_timed` commits. Devices get approved an hour later. Enforce now reads an empty `selections` table as authoritative and PUTs every folder with every mapped editor device removed. **All lane-C sync stops fleet-wide** until each editor manually re-ticks — and nobody is told, because "nobody ticked it" is a legitimate state the UI renders as normal (`my_queue.html:29`).

**Fix.** Set the flag only when `folders` is non-empty *and* at least one mapped editor device was present in the snapshot. Additionally, refuse an enforce pass that would remove shares from more than N devices without a logged override.

### DASH-H5 — A SQLite write transaction is held open across every Syncthing HTTP call and every NAS `os.walk` — **HIGH**

`collector.py:417-451` and `:361-372`. AUDIT §11 — **not fixed.** `db.upsert_completion` (437) opens the implicit transaction on the first row, then the loop keeps issuing `self.client.db_status` (427) and `self.client.completion` (434) — 10 s timeout each — before `_timed` commits at 162. Same shape in `_run_inventory`: `record_inventory_error`/`replace_nas_media` bracket up to `inventory_projects_per_cycle=8` full recursive walks of a ZFS/NFS tree. `_run_remoteneed` (472) likewise.

**Concrete trigger.** 20 folders × 5 devices ≈ 120 sequential requests. Any editor's `POST /api/v1/report` (which writes via `db.connect`, `busy_timeout=5000`) hits `sqlite3.OperationalError: database is locked` → unhandled → **500**, and that minute's lane A/B status is lost. Ticking a project in the browser fails the same way.

**Fix.** Gather all HTTP/filesystem results in memory first, then write and commit in one short burst per cycle.

### DASH-H6 — `/api/v1/report` accepts an unbounded body — **HIGH**

`api.py:1292-1366`. AUDIT SEC-4 — **partially fixed.** The fix bounded `lanes` (`max_length=32`) and `transfers` (`max_length=256`). Still uncapped: `LaneReportIn.last_error`, `.detail`, `.last_sync`, `.current_project`; `TransferIn.name`; `MediaClipIn.clip_name`/`file_path`/`bin_path`; `ManifestProjectIn.originals`/`proxies`; and critically `local_manifest: dict[str, ManifestProjectIn]` and `media_tree: dict[str, list[MediaClipIn]]` — arbitrary key count. Starlette imposes no body limit.

**Concrete trigger.** Any holder of the shared report token — which `/api/v1/verify` hands to **every** editor on sign-in (`api.py:496`; AUDIT SEC-6, unfixed) — POSTs a 2 GB `local_manifest` with 500,000 keys. The single-worker container OOMs (`run.sh:35`), or with a 200 MB `last_error` grows the SQLite file on `/data` past the dataset quota and takes the DB down with it. `replace_editor_media`'s `EDITOR_MEDIA_CAP` caps rows *per slug* only, so unbounded dict keys defeat it.

### DASH-H7 — Both `/project-setup` mutation handlers do full-tree NAS I/O directly on the event loop — **HIGH**

`ui.py:369-442`. AUDIT §7 — **not fixed, and regressed from threadpool to event loop.** `partial_project_setup_link` and `partial_project_setup_create` are `async def` and call, un-threadpooled: `adopt_folder` → `provision.scan_project_dirs(projects_dir)` (`api.py:842`, depth-8 `os.walk` of the whole tree), `write_marker`, `mkdir` × 8 template dirs, then `_setup_context` → `_browse_context` → `target.iterdir()` plus an extra `child.iterdir()` **per row** (`ui.py:284-291`). The SEC-13/§11 blocking fix was applied to the four admin/login handlers but these two were missed.

**Concrete trigger.** An editor clicks `[ LINK THIS FOLDER ]` while the NAS is under proxy-render load. The walk takes 25 s. For those 25 s the event loop is blocked: every companion's `/api/v1/report` times out, every htmx poll hangs, `/login` doesn't respond. Two editors onboarding at once makes it 50 s.

### DASH-H8 — An interrupted migration *within* a step still bricks the DB — **HIGH** [measured]

`db.py:259-276` + `SCHEMA_V2/V3/V4`. AUDIT §7 — **partially fixed.** The fix commits `user_version` after each step, closing the *between-step* case. But `executescript` runs a multi-statement script in autocommit. Measured:

```
executescript raised: OperationalError near "THIS": syntax error
user_version: 0            # not bumped
a cols: ['x', 'z']         # but the ALTER persisted
replay raised: OperationalError duplicate column name: z
```

`SCHEMA_V2` (185-201) contains 2 `CREATE` + **6** `ALTER TABLE … ADD COLUMN`; V3 has 2 `CREATE`; V4 a `CREATE` + an `ALTER`.

**Concrete trigger.** `install_dashboard_app.py`'s routine `docker restart` lands between two `ADD COLUMN`s. `user_version` is still 1. The next start replays SCHEMA_V2 → `duplicate column name` → raised in the lifespan handler → `restart: unless-stopped` **crash-loops forever**, recoverable only by manual `PRAGMA user_version` surgery.

`test_migration_commits_user_version_after_each_step` (`tests/test_db.py:170-207`) uses **single-statement** steps only, so it cannot catch this — the test's docstring claims a guarantee broader than what it proves.

**Fix.** Split every step into individual statements run under an explicit `BEGIN`/`COMMIT` with the `user_version` bump in the same transaction; or make each `ADD COLUMN` idempotent via `PRAGMA table_info`.

### DASH-H9 — The report endpoint still lets one editor write as another — **MEDIUM-HIGH**

`api.py:1394-1401`. AUDIT SEC-5 — **partially fixed.** The fix rejects a report whose `X-CCSync-Identity` is valid but names a different editor. It does **not require the header.** With no header, `id_user is None`, the guard is skipped, `verified=False`, and the report is written under whatever `editor_name` the body claims.

**Concrete trigger.** Editor `bob` — who legitimately holds the shared token from `/api/v1/verify` — POSTs `{"editor_name":"alice", …, "state":"error", "last_error":"disk failure"}` with no identity header. Alice's row goes red on the fleet grid, and `replace_active_transfers`/`upsert_machine_state`/`replace_media_tree` overwrite her real presence data. The only tell is a small `[ UNVERIFIED ]` chip that pre-upgrade companions also show.

### Dashboard — medium

- **DASH-M1 — one failing device aborts and rolls back the entire completion cycle** (`collector.py:417-451`). Unlike `_run_remoteneed`, `_run_completion` has no per-pair isolation; `self.client.completion` raising for one device propagates to `_timed`, which calls `conn.rollback()` — discarding rows already written for every *other* project/device. After 5 minutes `health.editor_status` returns RED for every editor on every project, uniformly, with no explanation.
- **DASH-M2 — a device that didn't really answer is recorded as 0% complete** (`collector.py:435-442`). `float(comp.get("completion", 0.0))` silently coerces a 200-with-unexpected-body into "0% synced, 0 files needed, nothing missing". A newly approved device before its first index exchange shows `[░░░░░░░░░░] 0%` *and* "nothing missing" simultaneously — indistinguishable from real data loss.
- **DASH-M3 — no guard on an empty `myID`** (`collector.py:288, 260`). The NAS becomes an "editor": `desired` omits the server device from every folder → a `put_folder` on **every folder on every enforce cycle** (Syncthing restarts a folder on each config change, so nothing ever settles), the NAS appears as an editor row with a completion bar, and the collector polls Syncthing for its completion against itself.
- **DASH-M4 — the inventory walk uses `projects.label`, not the authoritative `projects.path`** (`collector.py:363`; AUDIT §11 not fixed). Any folder whose label isn't the rel path makes `projects_dir / label` miss → `record_inventory_error` every cycle → MEDIA PRESENCE stuck at "NAS has 0 original(s)" forever, and `health.presence_status` returns GREEN for a base rig holding nothing.
- **DASH-M5 — with `SYNCTHING_GUI_URL` unset, no retention runs at all** (`app.py:40-42` + `collector.py:481-482`; AUDIT §7 not fixed). `db.prune` is reachable only from `_run_prune`. In a Syncthing-less configuration — which `settings.py:17` and the report/login paths fully support — eight tables grow without bound on `/data`.
- **DASH-M6 — `machine_state` has no retention, and its key is attacker-controlled** (`db.py:873-915`). PK is `(editor_username, machine)`, both free-form strings from the report body. A token holder loops reports with random `machine` values and grows the table permanently; `fetch_platform_map`/`fetch_verified_map` then load the whole table into a dict on **every** fleet-grid render.
- **DASH-M7 — sharing state is keyed on the mutable Syncthing device *name*, so renaming a device silently unshares it from every folder** (`db.py:279-290, 348-359` + `syncthing_client.py:62-85`). `selections` is keyed on `editor_username`, never on the immutable `device_id`, and `approve_device` renames a configured device in place — the documented admin flow for fixing an unmapped name. Admin approves `jsmith`, notices the account is `j.smith`, re-approves: within one enforce interval that device maps to `j.smith`, who has no selections → removed from every folder. All sync stops while the fleet grid shows the machine reporting normally.
- **DASH-M8 — `create_tree_project` doesn't check for marked descendants** (`api.py:765-816`). `adopt_folder` scans for marked children; `create_tree_project` checks only ancestors, and `target.mkdir(exist_ok=True)` happily reuses an existing directory. An editor "creates" `2026/CCT` — which already exists and holds three marked projects. A marker lands on the container, `scan_project_dirs` prunes at it, the three real projects vanish from discovery, and a new Syncthing folder is provisioned whose path **contains** three existing folders' paths.
- **DASH-M10 — package upload has no size cap and writes to disk on the event loop** (`api.py:1154-1206`). `/data` also holds `dashboard.db`; a misdirected `-Publish` fills it and SQLite hits `SQLITE_FULL`.
- **DASH-M11 — `syncthing_reachable` is "did the last poll_run succeed", with no staleness check, so a dead collector reads as healthy forever** (`db.py:1206-1219`). If `Collector._loop`'s pre-`try` `db.connect`/`db.migrate` raises, the thread dies before entering the guarded loop; nothing restarts it, `/api/v1/health` reports `ok: true` with an old `finished_at`, and `deploy/compose.yaml` has **no `healthcheck:`** (AUDIT §11, not fixed) so Docker never restarts the container.
- **DASH-M12 — the SMB probe never checks session flags, so a guest-mapped session authenticates any password** (`auth.py:57-80`). `smbprotocol` does not reject a response carrying `SMB2_SESSION_FLAG_IS_GUEST`/`IS_NULL`. If the NAS's SMB service is ever configured to map bad passwords to guest, **every** password is accepted for every username, including anyone in `DASH_ADMIN_USERS`. **Fix:** assert `session.session_flags == 0`. (Correct-but-worth-stating: with the NAS down `verify_credentials` fails closed — nobody can log in, but existing 7-day sessions and 30-day identity tokens keep working, and there is no revocation, so a password change invalidates nothing.)
- **DASH-M13 — the auth endpoints run a 10 s blocking SMB probe with no concurrency cap** (`api.py:433-509`). Both are unauthenticated and in `_OPEN_EXACT`; the per-username throttle bounds rate, not concurrency, and is bypassed by rotating usernames. 60 concurrent `POST /api/v1/verify` against a blackholing SMB host block all 40 anyio workers for 10 s, queueing every sync route behind them.
- **DASH-M14 — home permissions are fixed only `if not warnings`** (`truenas_client.py:193-206`; AUDIT §11 not fixed). A not-yet-propagated `sshpubkey` on the re-fetch appends a warning, so `_fix_home_permissions` never runs, the home stays group-readable, sshd `StrictModes` rejects the key, and lanes A/B fail with a generic auth error — while the admin banner mentions only the sshpubkey.
- **DASH-M15 — "create editor account" silently hijacks any existing TrueNAS account** (`truenas_client.py:146-155`; AUDIT §11 not fixed). `is_valid_username` checks only the charset, so typing `truenas_admin` overwrites its `sshpubkey`, force-adds it to `editors`, and attempts `password_disabled: True`.
- **DASH-M16 — `verify=False` on every TrueNAS call, including those carrying the admin password** (`truenas_client.py:76`; AUDIT §11 / SEC-3 not fixed).
- **DASH-M17 — folder/device IDs interpolated into REST paths unencoded** (`syncthing_client.py:85, 106, 109, 113`; AUDIT §11 not fixed). Slugs come from editor-writable marker JSON with no charset validation; a slug containing `/`, `?` or `#` yields a malformed `PUT /rest/config/folders/<slug>` — silently addressing a different folder, or 404ing forever.
- **DASH-M18 — authorization is inconsistent.** `/api/v1/transfers`, `/api/v1/projects/{slug}/presence`, `/partials/transfers` and `/partials/project/{slug}/bins` scope via `auth.scope_for`; `/api/v1/projects`, `/api/v1/projects/{slug}`, `/api/v1/editors`, `/api/v1/projects/{slug}/devices/{id}/missing`, `/api/v1/project-roots` and `/partials/project/{slug}/missing/{device_id}` have **no scoping** — any signed-in editor reads every other editor's completion %, device IDs, addresses, machine names, companion versions and full missing-file listings. `_require_selection_read` lets any holder of the shared report token read **any** editor's selection. Privacy/enumeration, not privilege escalation — fix uniformly or document as intentional.
- **DASH-M19 — "TICK FOR ME" destroys the polling wrapper and the media panel** (`partials/project_detail.html:11-13`; AUDIT §11 not fixed). `hx-target="closest main" hx-swap="innerHTML"` with a response of just `project_detail.html` overwrites `<main>`'s children, deleting `project.html:8`'s `hx-trigger="every 10s"` wrapper *and* the entire MEDIA PRESENCE block. After one tick the page is frozen and the bins section is gone until manual reload.

### Dashboard — low

- `ui.py:121-127` — `_safe_next` accepts `/\evil.com`. Round 1 concluded Starlette percent-encodes `\` so it isn't exploitable; still true, but the guard is one character from correct: also reject `raw[1] in "/\\"`.
- `collector.py:95-99` — backoff *replaces* the interval (AUDIT §11, not fixed). One failed prune moves `next_due` to `now+15 s`, so the hourly retention cycle retries 240× more often than its cadence.
- `db.py:638-648` — `add_selection` computes `MAX(position)+1` in a separate statement; the browser and companion can both tick and land two slugs on the same `position`, making "sync in tick order" ambiguous.
- `db.py:1158-1164` — `fetch_project` has no `active=1` filter while `fetch_projects` does: a deactivated project looks live on its own page but is absent from the sidebar.
- `db.py:259-276` — no guard for `user_version > SCHEMA_VERSION`. A rollback to an older image runs silently against a newer schema and 500s on the first query touching a removed column.
- `db.py:113-124` — `project_roots` PK is `resolve_project`, a mutable Resolve project *name*. Renaming the project in Resolve orphans the sticky mapping and lets any signed-in editor first-write-wins a new one. Schema comments still document `source` as `'auto' | 'admin'` while `'editor'` is written (AUDIT X-8, not fixed).
- `api.py:1462, 1384` — `machine` is used raw (not stripped); `" PC"` and `"PC"` become two machines across four tables.
- `api.py:1089-1109` — `_upgrade_info` coerces an absent/unknown `platform` to `"windows"`. A macOS companion that doesn't report `platform` is offered a Windows `.exe` (AUDIT X-5's fix landed in `build_editors_view` but not here).
- `db.py:873-915` — `active_transfers` liveness is 120 s but pruning is hourly, so up to an hour of dead rows accumulate; every `(editor, machine)` can hold 32 lanes × 256 transfers.
- `ui.py:284-298` — the browse panel still renders a partial listing alongside the error banner, so a `PermissionError` on one child can lead an editor to LINK the wrong folder; the per-row `child.iterdir()` is also an N+1 syscall over the mount.
- `truenas_client.py:96, 118, 128, 178, 184, 228, 239` — bare `resp.json()` after an `ok()` check: a 2xx non-JSON body raises `JSONDecodeError`, which escapes `except TrueNASError` and 500s instead of showing the intended banner.
- `collector.py:374-386` — the change-detection signature hashes directory mtimes only: re-rendering a proxy in place leaves `nas_media.size/mtime_ns` stale indefinitely.
- `api.py:433-454` — `api_login` lowercases but never validates the username *shape* before minting a cookie. A username containing `/` (accepted by SMB, rejected by `db._USERNAME_RE`) produces a session whose `session_user` is interpolated into `hx-post="/partials/selection/{{ session_user }}/…"`, silently 404ing every tick.
- `api.py:814, 862`; `ui.py:302` — error strings interpolate `OSError` text and container absolute paths into 422 details and the browse banner, visible to any signed-in editor.
- `deploy/compose.yaml:17` — `image: python:3.12-slim` unpinned (AUDIT §11, not fixed).
- `ui.py:184-188` — session cookie has no CSRF token and no `Secure`; `SameSite=Lax` covers the POST-only mutating routes today.

## §2.1 Verified clean

**Companion.** `config.load_config` BOM/CRLF/malformed-TOML handling and list coercion; `fixer.match_project_dir` token matching and `list_project_dirs` marker discovery; `popup.dedupe_out_of_tree_items`; `paths.classify_path` all four outcomes including the subst-realpath path and the trailing-separator boundary; `identity.parse_token` v2-only parsing and atomic `save_identity`; `upgrade.parse_upgrade` validation (same-version rejection → no upgrade loop), sha256-mismatch discard, non-frozen refusal, `_applying` re-entrancy guard; reporter fault isolation and `stop()` semantics; `resolve_bridge`'s never-raise contract at every level, the depth-64 recursion cap, and its copy-not-move guarantee on `ReplaceClip` failure; `theme.py`, `__main__.py`, `launcher.py`.

*Round-1 items verified genuinely fixed in the companion:* `paths.py` BAD_PREFIX storm; `toggle_pause` no longer starting disabled lanes; managed `_stop_lanes()` stopping lane A; `popup_snooze_seconds` present everywhere; the `\s` invalid escape in `DEFAULT_TOML_TEXT`; **S-11** tray startup catching bare `Exception`; **S-15** blank `editor_name`; **D-1** `skip_lane_b`; **X-7** `_refresh_media_tree_once` honouring `ignored_resolve_projects`; §6 `ReplaceClip` per-occurrence dedupe; §6 selection under `editor_name_fn`; §6 dry-run `--verbose` flood.

**Dashboard.** Fresh and upgraded DBs converge (v1 + `SCHEMA_V2…V8` produce byte-identical schemas; `test_v1_to_v2_migration_preserves_data` genuinely exercises v1→v8). No XSS surface: no `|safe`, no `Markup`, no `{% autoescape false %}`, no `{{ }}` inside `<script>`; all attribute interpolations quoted; URL-bearing ones `| urlencode`'d. No GET mutates. Template context completeness cross-checked route by route (except DASH-M19). Path traversal in `/project-setup` correctly rejected by `_safe_rel` + `_validate_tree_part` + the post-`resolve()` prefix check. Enforce never touches unmapped devices and modifies only a folder's `devices` list. `should_snapshot`/`prune` retention math correct and bounded. `compute_rate_ema` resets correctly. `match_project_label`'s trivial-token rule correctly prevents the "Event 1 Videos" → "Season 1" mis-match. `check_same_thread=False` usage is sound (one connection per request/thread, WAL + `busy_timeout` + `workers 1`). `_OPEN_EXACT` gating has no case or trailing-slash bypass.

*Round-1 items verified genuinely fixed in the dashboard:* SEC-1 (purpose-claimed tokens); S-9 (b64url username); SEC-12 (`_evict_expired_failures`); `_validate_tree_part` control chars; X-3 (`_slug_for_rel` label lookup); X-5's `build_editors_view` half; C-1 (`/app:ro`); collector `_incomplete` rebuilt fresh + per-pair try/except; collector-thread fault isolation; `run.sh` deps-only hash-stamped install; compose port bind narrowed; unbounded `/login` body; four admin/login handlers moved to `run_in_threadpool`; `LaneReportIn._known_lane`.

---

# §3. UX

Ordered by impact on a real editor's ability to get work done. The audience is video editors working remotely, often unsupervised.

## Tier 1 — the editor is stuck or actively misled

### UX-1 — A companion doing *nothing* shows a green icon and three lanes saying "OK" — [verified]

`require_login = true` by default (`config.py:88`). With nobody signed in, `app.py:917-930` calls `_mark_lanes_pending_login()`, which writes only to `LaneStatus.detail` and leaves `state` at `"idle"`. `tray.py:82` renders idle as `f"{label}: OK" + (f" ({status.detail})" if status.detail else "")`, so the tray reads:

```
lane a video up: OK (sign in required -- use the tray's "Sign in..." to authenticate before syncing)
lane b proxy down: OK (sign in required -- ...)
lane c syncthing: OK (sign in required -- ...)
```

and `compute_overall_color` (`tray.py:39-45`) returns **green**, because green is "no error and nothing syncing". The word `OK` is the first thing on every line. A green icon plus three `OK`s is the universal signal for "everything is fine" — while literally nothing syncs. Same defect for `"sync disabled: this machine works directly off the NAS"` (`app.py:687`) and `"disabled: direct NAS access"` (`app.py:719`).

**Fix (cheap).** Stop reusing `OK`. Render `f"{label}: NOT SYNCING — sign in first"` for the pending-login detail, `"up to date"` otherwise, and make `compute_overall_color` return `"orange"` whenever identity is invalid, `_paused` is set, or `_sync_enabled` is false. The icon must never be green unless the machine is signed in, unpaused and caught up.

### UX-2 — "Pause sync" is invisible after you click it

`app.toggle_pause()` (`app.py:885-913`) flips `_paused`, but no lane ever sets `state = "paused"` — `STATE_PAUSED` is defined in `sync/base.py:18` and used only by the sequencer's internal state and by a **dead branch** at `tray.py:80-81`. After Pause, all three lanes still read `OK`, the icon stays green, and the only evidence is a menu checkmark most users never register.

**Fix (cheap).** Check `app.is_paused()` first in `_format_lane_line`; return `"orange"` while paused; put the state in the label: `"⏸ Pause syncing"` / `"▶ Resume syncing (currently PAUSED)"`.

### UX-3 — Lane C reports green permanently and reports nothing real

`SyncthingLane.check_once()` (`sync/syncthing_lane.py:146-209`) computes `queued` by looping over `self.expected_folder_ids`, which comes from `cfg["syncthing_folder_ids"]` — default `[]` (`config.py:69`), and written as `[]` by **every** installer (`windows_bootstrap.ps1:906`, `macos_bootstrap.sh:521`, `config.example.toml:89`). Nothing ever populates it; managed mode learns folders from the dashboard selection, not this key. So the loop body never executes, `queued` is always `0`, and every poll lands on `STATE_IDLE, queued=0, last_sync=now`.

The tray shows `lane c syncthing: OK` while 200 GB of project assets are mid-download — and shows the identical thing when Syncthing has zero folders shared. This is the lane carrying **all** audio, GFX, AE and subtitles.

**Fix (real work, small).** In managed mode feed the lane the sequencer's live folder set (`expected_folder_ids_fn`), evaluated per poll; or drop the filter and sum `needTotalItems` over all folders present in `/rest/config`.

### UX-4 — The sequencer's entire state is computed and then thrown away

`Sequencer.status_detail()` (`sync/sequencer.py:215-236`) produces exactly the strings an editor needs — `"no selection (dashboard unreachable, no cache)"`, `"syncing 2026/CCT/… (2/5)"`, `"idle between passes"`, `"paused"`. `grep status_detail` across the repo returns **two** hits: the definition and `test_sequencer.py:358`. It appears in no tray line, no log line, no report payload, and nowhere on the dashboard.

Worse, the reporter *does* send `queue` and `current_project` (`reporter.py:193-194`) and the dashboard explicitly discards them — `api.py:1359`: `# informational; selections table is the truth`. So the server cannot tell whether an editor's sequencer is running, parked on "no selection", or stuck on "dashboard unreachable".

On the rotation question — does an editor whose project isn't current know they're waiting, and for how long? **No.** The tray says nothing about the queue. MY QUEUE shows `[ SYNCING NOW ]` on one row and, for the others, a progress bar with no "waiting" marker and no estimate; a 0% project at position 4 looks identical to a stalled one.

**Fix.** Add `sequencer_state`/`sequencer_detail` to the report payload and `lane_report_current`; render as a pinned first tray line. In `my_queue.html:12`, add `[ WAITING — N ahead ]` for non-current rows plus a one-line explainer: *"Projects sync one at a time, top to bottom. Each gets up to 10 minutes before the next takes a turn."*

### UX-5 — When a clip is offline there is no path to *why*, and the data to answer it is already in the DB

The single most important question in the system. End to end:

1. The clip is red in Resolve. Resolve says nothing about CCSync.
2. **Tray:** three lane lines plus `Sync now` / `Scan whole project` / `Consolidate…`. Nothing about clips. No "show why offline". `Sync now` in managed mode calls `sequencer.trigger_pass_now()` (`app.py:872`) with zero feedback.
3. **Dashboard → project → `[ MEDIA PRESENCE ]`** (`partials/bins.html:29-31`): a red dot with `title="offline"`. That is the terminal state of the entire diagnostic path — no reason, no next action, and `title` is invisible on touch.
4. There is no step 4. `[ MISSING FILES ]` exists but is lane-C-only (Syncthing `remoteneed`), so it never lists a missing proxy or original. The button an editor would click is exactly the one that can't answer.

The data is already there: `nas_media` (`db.py:32-42`) holds per-file `rel_path` + `kind ∈ {original, proxy}`; `editor_media` (`db.py:70-80`) the same per editor/machine; `media_tree_clips` (`db.py:81-93`) the clip. A join over basename answers it in four states:

| Condition | What the editor must be told |
|---|---|
| no NAS proxy, no NAS original | "Nobody has uploaded this clip to the server yet. It's still on whoever added it." |
| original on NAS, no proxy | "Uploaded, but the proxy hasn't been generated yet. Alex's proxy machine has to be on — minutes to hours." |
| proxy on NAS, not in your `editor_media` | "The proxy is ready on the server and hasn't reached you yet." + queue position. |
| in `editor_media` but `present = 0` | "You have this file but Resolve can't see it — your Mapped Mount / P: drive is probably wrong. See EDITOR_SETUP §6." |

**Fix (real work — highest-value single change in this audit).** Make the red dot a button: `hx-get="/partials/clip/{{ slug }}/why?name=…"`, a new builder doing the join, rendering one sentence plus one action. Add a tray item `Why is a clip offline?…` deep-linking to `/project/<slug>#presence`.

### UX-6 — The editor's project folder is silently moved out from under them

`sync/repath.py:110-131`: when a project moves on the NAS, the companion pauses the folder, `os.rename`s the editor's local project directory, and re-points Syncthing. The only trace is a `log.warning`. What the editor experiences: their whole project folder vanishes, and if Resolve is open every clip goes offline at once, mid-session, for no visible reason. The conflict path is worse — `repath.py:143-148` logs *"target %s already exists; leaving old dir %s in place (reconcile by hand)"*: a log-only instruction, to a person who will never read the log, about two directories they don't know exist.

**Fix (cheap).** Pass `notify=app._notify_tray` into `ProjectRepather`. Before: *"'Season 1' moved on the server — moving your local copy to match. Close it in Resolve first if it's open."* After: *"Done. If clips went offline, close and reopen the project in Resolve."* Conflict: *"Couldn't move 'Season 1' — a folder already exists at the new location. Message Alex; nothing was deleted."*

### UX-7 — Expired dashboard sessions inject a login form into the middle of the page, forever

`dashboard/src/ccsync_dashboard/app.py:53-80` redirects **every** non-open path, including `/partials/*`, with a 303 to `/login?next=…`. The fleet page polls `/partials/sidebar` every 30 s, `/partials/queue` every 10 s, `/partials/fleet` every 15 s (`fleet.html:4,9,14`). Once the cookie is gone, htmx transparently follows the 303, receives the **login page** HTML, and swaps it into the sidebar and queue divs — repeatedly. The editor sees a login form inside the page with the old chrome around it and stale numbers where the swap didn't reach.

The 4xx paths are the mirror problem: `ui.py:242` raises `HTTPException(403, "admins only: destination roots are fixed once set")` and `ui.py:206` raises `401`. htmx does not swap on 4xx by default, so the user clicks `[ SET ]` and **nothing happens at all.**

**Fix (cheap).** Branch on `hx-request` in the middleware and return `401` with an `HX-Redirect` header; render permission failures as a visible banner with status 200 rather than raising. Every 4xx an editor can trigger must produce visible text.

### UX-8 — macOS editors have no wizard, and the mandatory sign-in step is documented nowhere

`onboarding/onboard.py` is Windows-only (`winget`, `subst`, `schtasks`). Mac editors get `macos_bootstrap.sh` plus prose: ten manual steps, four values they can't produce themselves (invite link, tailnet IP, dashboard token, Postgres password), one blocking wait on Alex — and one silent hard gate:

**Step 10 is Tray → "Sign in…", which appears in neither `docs/EDITOR_SETUP.md` nor `installer/START_HERE.md`.** Grep for "sign in" in both returns only the Tailscale invite and the *dashboard* login. With `require_login = true`, **no lane starts until this happens.** Combined with UX-1, a Mac editor completes every documented step, sees a green tray with three `OK`s, and nothing ever syncs. AUDIT S-14 flagged this; it is still not in either file.

**Fix.** Immediately, in both docs, *before* the dashboard step: *"Right-click the tray icon → **Sign in…** and enter your TrueNAS username and password. Until the tray says `Signed in as <you>`, nothing syncs — this is the switch that turns sync on."* Then either ship a mac `onboard` app, or have `macos_bootstrap.sh` accept `--dashboard-url`/`--dashboard-token` and write them (it already writes the file at `:506-521`), collapsing step 5.

### UX-9 — FIX ALL: all-or-nothing, no bytes, no filename, no cancel

`popup.py:225-228` offers exactly two buttons: `IGNORE` and `FIX ALL`. There is no per-row skip — an editor with 30 out-of-tree clips, one of which they want left alone, must fix all 30 or ignore all 30 (`perform_ignore_all` ignores every row).

Progress is `FIXING 3/30 — copying media…` (`popup.py:333, 337-339`). For BRAW originals over SMB this can sit on `0/1` for twenty minutes with no filename, no byte count, no speed, and no cancel. *"do not close…"* while the window looks frozen is precisely the state that makes a user force-quit — which per CORE-H5 leaves a multi-GB `.ccsync-tmp` that lane C then uploads.

Failure output is raw internals: `popup.py:356-357` prints `"ReplaceClip returned False for C:\..."` verbatim.

**Fix.** Per-row checkbutton (default on); buttons `[ COPY SELECTED IN ]` / `[ SKIP FOR NOW ]`. `perform_fix_all` already takes `progress_fn(done, total, result)` — widen it to carry the filename and use `os.path.getsize` for a byte total: `Copying 3 of 30 — "A001_C012.braw" (4.1 GB of 38.2 GB done)`. Add `[ STOP AFTER THIS FILE ]`. Translate failures: `ReplaceClip returned False` → *"Copied the file in, but Resolve wouldn't relink it. Close the clip's timeline and use tray → Scan whole project again."*

### UX-10 — Consolidate: the flagship onboarding flow runs for hours with zero progress

`app.consolidate_project()` (`app.py:417-502`) — the "I already had this project" path. Its entire user-visible surface is four toasts: `"Checking the NAS…"`, the confirm dialog, `"Uploading originals to the NAS…"`, `"Consolidate & upload finished."`

`consolidate.run_consolidation` **accepts** `progress_fn` (`consolidate.py:309`) and `app.py:474` passes none. Then `self._lane_a.run_once(subpath)` uploads potentially hundreds of GB with no surfaced progress, even though `rclone_lane.py:651-654` populates `bytes_done`/`speed_bps`/`eta_seconds` every 10 s. Between the third and fourth toast there can be a multi-hour silence, no cancel, and no warning if the editor quits the tray mid-run.

Dead ends: `consolidate.py:209`'s abort renders as `"(could not check the NAS: no active project resolved — refusing whole-tree consolidate)"` and the dialog **still offers** `[ CONSOLIDATE & UPLOAD ]` (which per CORE-C2 then uploads the whole tree). Cancel produces no feedback at all. `"12/30 consolidated, 18 failed — see log."` — "see log" is not an action for this audience.

**Fix.** Pass `progress_fn` through; show a real progress window (`Copying 4 of 22 — "interview_A.mov" · 12.3 GB of 61 GB · 48 MB/s · ~17 min left`) with `[ STOP AFTER THIS FILE ]`. During lane A, poll `self._lane_a.status()` every 2 s and show the same line. Replace *"see log"* with *"Tray → Copy diagnostics, then send that to Alex."* When `reconcile["ok"]` is false, **disable** the confirm button.

## Tier 2 — wrong mental model, avoidable support pings

### UX-11 — `queued` never moves on lanes A and B

`rclone_lane.py:574` sets `self._status.queued = 0` at the end of every run and **nothing ever increments it.** `tray.py:79` renders `f"{label}: syncing ({status.queued} queued)"`, so the tray's only during-sync text is permanently `syncing (0 queued)` — a counter reading zero while transferring. Meanwhile the fields that *are* live (`bytes_done`, `bytes_total`, `speed_bps`, `eta_seconds`, `transfers`) are displayed nowhere.

**Fix (cheap).** Replace the queued count with the live stats, and add a pinned line showing `status.current_project` — the tray currently never says *which project* is syncing, despite `LaneStatus.current_project` carrying it.

### UX-12 — Lane letters A/B/C are internal jargon and the editor sees them everywhere

Tray menu literally reads `lane a video up: OK` (`tray.py:75` does `name.replace("_", " ")`). Dashboard chips render `A:idle B:syncing C:error` (`api.py:25-28`, `fleet_grid.html:35`). Column headers say `SYNC (LANE C)` and `LANES A/B`. `EDITOR_SETUP.md` and `SERVER.md` use "lane A"/"lane C" throughout. **No legend exists anywhere.** An editor cannot know that C failing means their music won't arrive but their proxies still will.

**Fix (cheap).** One rename pass, no logic change — keep internal names on the wire, change only `LANE_LABELS` and `tray._format_lane_line`:

| internal | editor-facing |
|---|---|
| `lane_a_video_up` / A | **Uploads** (your footage → server) |
| `lane_b_proxy_down` / B | **Proxies** (server → you) |
| `lane_c_syncthing` / C | **Everything else** (audio, graphics, subs — both ways) |

### UX-13 — Words that make an editor think something got deleted

The hard requirement is that nothing is ever deleted. Independent of what the code does, these labels break that promise at the UI layer:

| Where | Current | Problem | Replace with |
|---|---|---|---|
| `tray.py:376` | `Consolidate pre-existing project…` | In Resolve, "Consolidate" means Media Management → Consolidate, which **trims and deletes** unused media. The most dangerous single word in the product. | `Bring an existing project's media into the synced folder…` |
| `app.py:469` | title `CONSOLIDATE PROJECT`, button `CONSOLIDATE & UPLOAD` | same | `COPY THIS PROJECT'S MEDIA IN` / `COPY & UPLOAD` |
| `consolidate.py:299` | *"Originals are COPIED, never moved — your scattered files stay put."* | Correct text, but it's the **last** line, after the scary numbers and a `!!! WARNING … DELETE !!!` block | move to line 2 of `build_report`, right under the title |
| `popup.py:215-217` | *"…FIX ALL copies them in and relinks Resolve."* | says "copies" but never says the original survives | append *"Your original file is left exactly where it is — nothing is moved or deleted."* |
| `popup.py:225` | `IGNORE` | scope unstated (session-only, `fixer.py:34-40`) | `SKIP FOR NOW (this session)` |
| **`START_HERE.md:113-116`** | *"it pops up and offers to **move it into the right place for you**. Say yes"* | **Directly contradicts the code** — `fix_clip` copies and its docstring says "Never delete/move the original". Editors will delete their Desktop original believing it moved. **[verified]** | *"…offers to **copy it into the right place** and relink Resolve. Say yes — that's what makes your added media appear for everyone else. Your original stays where it is; delete it yourself later if you want."* |
| `START_HERE.md:15-20`, `onboard.py:149-156, 360-368` | *"removes every trace of older CCSync versions"*, *"clean slate"* | reads like a wipe; `build_cleanup_plan` only removes exe copies, shims, autostart entries and the P: mapping | add *"Nothing you've synced is touched — your Creators_Club folder, proxies, sign-in, Syncthing identity and SSH key all stay exactly as they are. Only the old app files are replaced."* |
| `windows_uninstall.ps1:17-21, 40` | `-Full -- wipe everything` | an editor with 400 GB of proxies will not run this | `-Full -- also remove your saved sign-in and Syncthing identity (a reinstall then needs Alex to re-approve you). Neither mode ever deletes your synced media in C:\Creators_Club.` |
| `my_queue.html:22-23` | `[ UNTICK ]` | nothing says whether downloaded files survive | add *"Unticking stops a project syncing to this machine. Files already on your disk stay there."* |
| `project_roots.html:21` | `— remove (re-detect) —` | "remove" reads as deleting a project | `— clear this mapping (detect again) —` |
| `project_detail.html:4` | `[ FOLDER REMOVED ]` | sounds like someone deleted the project | `[ NOT FOUND ON THE NAS ]` |
| `my_queue.html:13` | `[ GONE ]` | same | `[ MISSING ON SERVER ]` |
| `admin_packages.html:41` | `[ DELETE ]` with **no confirmation** — `ui.py:754-781` unlinks from disk | one mis-click permanently destroys a published build | add `hx-confirm="Permanently delete companion {{ p.version }}? The file is removed from the server."` |

Also unlabelled: the sequencer **pauses the editor's other Syncthing folders** during each rotation (`sequencer.py:509-518`). An editor who opens the Syncthing web UI sees their projects marked "Paused" and will reasonably try to un-pause or remove them. Nothing anywhere explains this. Add a line to `EDITOR_SETUP.md §7`, and set the Syncthing folder comment to *"Paused/unpaused automatically by CCSync — don't change this by hand."*

### UX-14 — `[ SYNCING NOW ]` lies whenever the sequencer is idle or paused

`api.build_queue_view` derives "current" from lane rows (`api.py:372`), but `RcloneLane._run_once_locked` sets `current_project = subpath` (`rclone_lane.py:531`) and **never clears it.** After a pass completes and the sequencer parks for 60 s — or after pause, or sign-out — the last-synced project keeps wearing `[ SYNCING NOW ]` indefinitely.

**Fix (cheap).** Reset `current_project = None` alongside the other resets at `rclone_lane.py:572-580`, and drive the chip from the sequencer's own `current_slug` (UX-4).

### UX-15 — `[ OUT OF DATE ]` doesn't say what to do

`fleet_grid.html:39` has the action only in an invisible-on-touch `title`. The tray *does* grow `Update available → vX — Update now` (`tray.py:356-358`), and the chip never mentions it. **Fix:** `[ UPDATE IN YOUR TRAY → v{{ … }} ]` with a `title` spelling out the right-click.

### UX-16 — Raw internals surfaced in editor-facing toasts

Fifteen strings, with replacements. The highest-value ones:

| Location | Current | Replace with |
|---|---|---|
| `app.py:323-327` | `"clip on canonical prefix (P:\) doesn't resolve under local_root (C:\Creators_Club): <path>"` | *"Resolve is looking for media on P:\ but that path doesn't land in your sync folder. Your P: drive (Windows) or Mapped Mount (Mac) is wrong — see EDITOR_SETUP step 6. Nothing will sync until this is fixed."* |
| `syncthing_lane.py:153` | `"no Syncthing API key (checked C:\Users\x\AppData\...\config.xml)"` | *"Syncthing isn't set up on this machine — audio/graphics can't sync. Re-run onboard.exe."* |
| `syncthing_lane.py:161` | `"Syncthing not running"` | *"Syncthing isn't running — audio, graphics and subtitles won't sync. Log off and back on, or re-run onboard.exe."* |
| `syncthing_lane.py:189` | `"folder(s) not configured/shared: 2026-cct-season-1 (not shared with any device)"` | *"Alex hasn't approved this machine for <project> yet — send him your device ID (tray → Copy diagnostics)."* |
| `rclone_lane.py:587` | `f"rclone exited {returncode}"` + the last 300 chars of rclone stderr, shown verbatim in the tray | classify: *"Can't reach the server. Check the Tailscale tray icon is connected."* for network/auth, *"Your disk is full."* for ENOSPC, generic + diagnostics otherwise |
| `rclone_lane.py:525` | `"project dir not yet local: <sub>"` — renders as `OK (project dir not yet local: …)` | *"waiting for the server to share this project"* |
| `app.py:837-840` | `"Update failed — still running the current version. See companion.log."` | *"Update failed — you're still on v{VERSION}, nothing is broken. Tray → Copy diagnostics and send it to Alex."* |
| `project_detail.html:30` | `[ UNMAPPED ]`, title `"run accept_device.py --device-name"` | editors see a CLI command they can't run → `title="Alex needs to link this machine to your username."` |
| `project_detail.html:56` | `"…share it with accept_device.py."` | *"Nobody's machine is set up for this project yet. Alex needs to approve at least one device."* |
| `fleet_grid.html:47` | `"no companion reports yet — set dashboard_url in each editor's ~/.ccsync/config.toml"` | *"No machines are reporting yet."* (keep the config hint behind `session_is_admin`) |

Also: `resolve_bridge.py:239, 351` `f"Resolve scripting error: {exc}"` → *"Resolve didn't answer. Make sure a project is open, then try again."*

### UX-17 — Tray menu: nine items, wrong order, three that appear and disappear

Current order puts the version string first, the two rarest and most dangerous actions (`Consolidate`, `Scan whole project`) above the most common ones, and the conditional `Update available…` item **directly above `Quit`** — the one item you must never mis-click. Missing entirely: open my project folder, copy diagnostics, why is a clip offline, and any indication of what is currently syncing. `Quit` (`tray.py:385`) gives no hint that quitting stops all syncing until next login.

**Proposed order:**

```
Signed in as <name>            (or ► NOT SIGNED IN — click to sign in)
──────
Sequencer: syncing "Season 1" (2 of 5)              ← UX-4
Uploads: 4.1 GB of 38 GB · 48 MB/s · ~11 min left   ← UX-11
Proxies: up to date
Everything else: 12 files to go
──────
Sync now
⏸ Pause syncing                (label carries state — UX-2)
Open my project folder         ← NEW
Open dashboard
Why is a clip offline?…        ← NEW (UX-5)
──────
Update available → v0.4.5 (install)   ← never adjacent to Quit
──────
Copy diagnostics for Alex      ← NEW (UX-19)
Open log
Advanced ▸ Scan whole project / Bring an existing project's media in…
──────
Quit CCSync (stops syncing)
```

## Tier 3 — dashboard polish, accessibility, doc drift

### UX-18 — Dashboard first-run and empty states

- A brand-new editor logs in to `/`: the sidebar says *"no projects yet — waiting for first poll"*, MY QUEUE says *"Nothing ticked — nothing syncs to this machine. Tick a project below."* — and if `queue.available` is empty, **there is nothing below** (`my_queue.html:49` guards the whole list). Dead end. Add `{% else %}No projects exist on the server yet — Alex has to create one first.`
- `[ FIX DESTINATION ROOT ]` and the whole `[ PROJECT ROOTS ]` box render for *any* signed-in user (`fleet.html:17-21`) but are admin-only concepts. A non-admin sees a table they can't act on. Gate on `session_is_admin`; reduce the editor's version to one sentence in MY QUEUE.
- **No legend for the health dots anywhere.** Add one line under `FLEET OVERVIEW`: *"● green = caught up · ● amber = transferring · ● red = broken or offline too long"*.

### UX-19 — There is no one-click diagnostics gather

The log rotates properly (5 MB × 3, `~/.ccsync/companion.log`) and is readable. But the instruction everywhere is *"message Alex with a screenshot of the tray menu"* (`START_HERE.md:168-170`, `FIRST_UPGRADE.md:45-47`) — and per UX-1/UX-11 that screenshot is three lines saying `OK`.

**Fix (cheap, high leverage).** A tray item `Copy diagnostics for Alex` assembling to the clipboard: companion version, platform, `effective_mode()`, signed-in username + token expiry, `config_problems` (already collected at `app.py:993`), all three `LaneStatus` dicts, sequencer state/detail, current Resolve project, Syncthing reachability, `rclone_available()`, selected project rels, and the last 40 log lines. This single item removes most of the round trips this system will otherwise generate.

### UX-20 — Accessibility basics

- **Color-only status.** Every health dot is a bare `<span class="dot green">●</span>` with no `title`, `aria-label`, or text (`sidebar.html:12`, `fleet_grid.html:2,10`, `my_queue.html:10`, `project_detail.html:2,27`, `bins.html:10`). Add labels and differentiate the glyph (`●`/`◐`/`▲`) so state survives greyscale.
- **Contrast.** `--muted: #6f6f7a` on `--bg: #0a0a0d` is ≈**3.98:1** — below WCAG AA — and used at 11–12 px for load-bearing text (timestamps, every empty state, all explanatory copy). Use `#9a9aa8` (≈7.1:1) in `static/style.css:13`, mirrored in `theme.py:22`.
- **Focus states.** `.btn` (`style.css:128-137`) has `:hover` only; `.dot`, `.card`, `details.bin > summary` likewise. In the tray/popup, `theme.neon_button` (`theme.py:70-92`) sets `highlightthickness=0`, removing tkinter's only focus affordance — keyboard users cannot see what's focused in the fixer dialog.
- **Non-focusable controls.** The folder browser uses `<a class="btn" hx-get=…>` with no `href` (`project_setup_panel.html:47-51, 67-73`) — not tab-reachable, not Enter-activatable. Use `<button type="button">`.
- **Hit targets.** `.btn` is 12 px with zero padding; `.chip` 11 px. On mobile (`style.css:252-255`), `[ UNTICK ]` is ~30×16 px. Add `min-height: 44px` inside the mobile query.
- **PopupDialog keyboard.** No `<Return>`/`<Escape>` bindings and no `WM_DELETE_WINDOW` handler (`popup.py:152-383`), unlike the sign-in and update dialogs which do bind Return. `confirm_dialog` also has no Return binding.

### UX-21 — Doc drift that will actively mislead

- **`docs/EDITOR_SETUP.md:114-126`**: *"You do not need to list projects. The whole tree replicates. Lanes A and B sync `local_root` against `remote_root` as complete trees."* That is legacy non-managed behaviour. With `dashboard_url` set — the default (`config.py:79`) — the sequencer syncs **only ticked projects, one at a time.** Section 3.5 then contradicts itself 30 lines later with the ticking instructions. Same stale claim at `docs/SERVER.md:34-36`.
- **`installer/START_HERE.md:109-125`** tells the editor to copy the exe by hand, re-run the bootstrap script, and paste a `dashboard_token` into `config.toml` — all of which `onboard.exe` already does (`onboard.py:434-451, 478-495`). The recommended path and the documented path disagree in the same file.
- **`installer/README.md:11-16`** still says the macOS script "has **not** been run on an actual Mac". Fine for the repo; make sure no Mac editor is handed this file.
- `EDITOR_SETUP.md:239-243` correctly says Consolidate copies and never moves — keep that wording and propagate it to the tray label (UX-13).

## §3.1 UX — cheap vs real work

**High impact, cheap** (copy plus a handful of lines; no new data flows): UX-1, UX-2, UX-11, UX-12, UX-13 (the whole wording table), UX-14, UX-15, UX-16, UX-17, UX-18, UX-20, UX-21, and UX-8's documentation half.

**High impact, real work:** UX-3 (real lane-C folder set), UX-4 (sequencer state on the wire), UX-5 (the offline-clip explainer), UX-6 (repath notifications), UX-7 (htmx auth handling), UX-9 (FIX ALL selection + progress + cancel), UX-10 (consolidate progress), UX-19 (Copy diagnostics), UX-8's macOS parity half.

## §3.2 The five UX changes to make first

1. **UX-1 + UX-2 + UX-11 — make the tray tell the truth.** The one artifact this product asks the editor to look at says `OK` on all three lines and shows green when the machine isn't signed in, is paused, or has lane C doing nothing knowable. Every other finding is downstream: the docs tell editors to send Alex a screenshot of a menu that cannot express failure.
2. **UX-8's documentation half** — the tray "Sign in…" step, in both editor docs, before the dashboard step. One paragraph. Currently the difference between "works" and "silently never syncs" for every editor who didn't run `onboard.exe`, i.e. every Mac editor.
3. **UX-13 — the wording pass**, starting with `Consolidate` and `START_HERE.md`'s "move it into the right place". Pure text. Removes the two places where the UI promises the opposite of the no-deletion guarantee, and the one place where the docs contradict the code in a way that gets an editor's original footage deleted by their own hand.
4. **UX-5 — the offline-clip explainer.** The question the system exists to answer; the terminal state today is a red dot whose tooltip reads `offline`; every input is already in SQLite. Biggest reduction in "message Alex" volume per unit of work.
5. **UX-19 — `Copy diagnostics for Alex`.** ~40 lines assembling state that already exists in memory. Converts every remaining unknown failure from a multi-message diagnostic conversation into a single paste — which is what makes the rest of this list survivable while it's being fixed.

---

# §4. Transfer and sync performance

Target per SPEC: beat Blackmagic Cloud's observed ~60 mb/s up/down.

**The headline is that the biggest losses are not in rclone's flags.** They are three structural facts:

1. **Lanes A, B and C are serialized** when A and B are *opposite directions* and C is a separate process — up to 50% wall-clock loss plus multi-minute-to-hour starvation.
2. **rclone's SFTP transport has no multi-thread upload support**, so a single 40 GB BRAW rides one SSH stream with a 2 MiB in-flight window — a hard per-file ceiling of `window / RTT` that one flag fixes 8×.
3. **Lane C is probably not on the tailnet at all.** Syncthing devices are added with `addresses: ["dynamic"]` and relays plus global discovery left at their `true` defaults — so the "relay trap" suspected for Tailscale DERP is literally present in Syncthing's own public relay pool.

## §4.1 Bugs actively costing throughput

### P1 — The SFTP single-stream window caps every large upload; `--sftp-chunk-size` is never set — [measured]

`sync/rclone_lane.py:250-264` (lane A argv), `:283-293` (lane B argv), `installer/windows_bootstrap.ps1:806-814` (the generated `rclone.conf` stanza sets only `type/host/user/port/key_file/shell_type`).

rclone's multi-thread *upload* is implemented only for `local, s3, azureblob, b2, oracleobjectstorage, smb` — **sftp is not on that list.** So lane A moves each file over exactly one SFTP stream whose in-flight window is `--sftp-chunk-size × --sftp-concurrency = 32 KiB × 64 = 2 MiB` (both defaults verified against the bundled binary). Per-file ceiling ≈ window / RTT:

| RTT | ceiling now (2 MiB) | with `chunk-size 255Ki` (16.3 MiB) |
|---|---:|---:|
| 10 ms | 210 MB/s | not limiting |
| 30 ms | 70 MB/s | 545 MB/s |
| 60 ms | 35 MB/s | 272 MB/s |
| 150 ms | **14 MB/s (112 Mb/s)** | 109 MB/s |

`--transfers 4` multiplies across *files*, not within one — so the 40 GB single-file case, which is lane A's whole purpose, gets zero benefit from it. rclone's own help text says raising `chunk_size` to `255k` "will increase transfer speed dramatically on high latency links… includes OpenSSH."

**Magnitude: up to 8× on lane A for large files at WAN RTT. Confidence: high.** Note how well the 150 ms row matches the observed ~60 mb/s ceiling this project exists to beat.

### P2 — Every transferred file triggers a full-file re-read on the NAS, for a hash rclone doesn't need — [measured]

`rclone_lane.py:250-264`, `:283-293` (no `--ignore-checksum` / `--sftp-disable-hashcheck`); `windows_bootstrap.ps1:813` sets `shell_type = unix`, so rclone probes and uses `md5sum` over SSH.

rclone verifies size **and hash** after every transfer when a common hash exists — measured: a local→local copy logs `big.mov: md5 = … OK`, and the line disappears under `--ignore-checksum`. With `shell_type=unix` the SFTP backend gets MD5 by shelling out `md5sum <path>` on the NAS, so **the NAS re-reads the entire file it just received** (lane A) or just sent (lane B), serialized after the transfer with no progress reported.

A 40 GB original ⇒ +90-150 s of pure NAS disk+CPU per file. A lane B pass of 200 × 500 MB proxies ⇒ ~100 GB of extra NAS reads. Plus 2 extra SSH command executions per session just to probe hash support.

**Magnitude: +10-25% lane wall-clock on big files, and the single largest source of NAS I/O contention between editors. Confidence: high on mechanism, medium on the percentage (depends on ARC hit rate).**

### P3 — Lane C is probably relaying: relays and global discovery left on, no explicit tailnet addresses

`dashboard/.../syncthing_client.py:80` and `server/accept_device.py:80` (`"addresses": ["dynamic"]`); `windows_bootstrap.ps1:754` runs `syncthing generate` and then never touches `/rest/config/options`. **Nothing anywhere in production sets `relaysEnabled` / `globalAnnounceEnabled` / `localAnnounceEnabled` / `natEnabled`** — the only hits in the repo are `bench/ccbench/runners/syncthing.py:184-187`, i.e. the loopback benchmark only.

`dynamic` means discover via global discovery, so the editor learns the NAS's *public* address, not its `100.x` tailnet address. HiNet's inbound is blackholed except forwarded high ports, and nothing forwards 22000 tcp/udp. Syncthing then falls back to the **public relay pool** (`relaysEnabled` defaults to `true`) — typically 1-5 MB/s, shared, rate-limited. Compounding it, the NAS Syncthing app runs `host_network: False` with published 22000 tcp/udp (`server/install_syncthing_app.py:166-168`) while Tailscale is a *separate* container, so even a correct address needs the DNAT path to work.

**Magnitude: lane C throughput possibly 10-30× below the tailnet path. This is the most likely literal explanation of a ~60 mb/s-class ceiling. Confidence: high that the config permits and prefers relaying; medium that it currently is** — one `GET /rest/system/connections` settles it, and the `type` field will read `relay-client`.

### P4 — The pause/unpause-one-folder-at-a-time scheme is a self-inflicted rescan storm and a 50-minute stall

`sync/sequencer.py:494-532` (`_lane_c_turn`), `:552-575` (`_wait_for_folder_sync`, bounded by `project_rotation_seconds=600`), `syncthing_admin.py:100-101` (`PATCH {"paused": …}`). Four separate costs, all real:

1. **Config churn** — per pass with N projects: `N` unpauses + `N(N-1)` pauses. N=6 ⇒ 36 config commits per pass ≈ **1000/hour** at a 2-minute steady-state pass.
2. **Rescan on every unpause** — resuming a folder restarts the folder runner, which rescans from the beginning. N=6 ⇒ ~180 full tree walks/hour on the editor's disk, competing for IOPS with lanes A and B.
3. **Latency** — any project that is not current has its folder paused in *both* directions. With N=6, a project's small files (Resolve project files, audio, subs — the latency-sensitive content) can sit unsent for **~50 minutes**.
4. **Collateral config damage** — `PATCH /rest/config/folders/<id> {"paused":…}` is known to reset unrelated folder fields (`rescanIntervalS` → 3600, watch-for-changes → enabled) in Syncthing 2.0.8. So this scheme silently rewrites folder settings ~1000×/hour.

### P5 — Lane C's turn ends before the editor's *uploads* drain, then the folder is paused mid-send

`sequencer.py:558-563`. The turn's exit condition is `folder_status(slug).needTotalItems == 0` — what **this device needs to download**. It says nothing about what the *server* still needs from this editor. So a turn can complete while the editor's outgoing files are half-sent; the next `_lane_c_turn` then pauses this folder (`:516`) and the upload is cut until that folder's next turn, up to N×600 s later.

**Fix.** Also require `GET /rest/db/completion?folder=<id>&device=<server-id>` to report `needBytes == 0`.

### P6 — Editor-side `.stignore` is only ever set at accept time, so an ignore-less folder re-hashes all video forever

`syncthing_admin.py:129-142` — `set_ignores` is called from `accept_folder` and **nowhere else**. A folder accepted by hand, accepted by an older companion, or whose ignores were lost has no video/Proxy exclusion locally. Syncthing then SHA-256-hashes every `.braw`/`.mov` in the project — 40 GB files — on every scan and offers them to the server. Ignore patterns are per-device and are *not* synced by Syncthing, so there is no self-healing. This is the throughput face of §5's L-3 and §2's DASH-H1.

**Magnitude: catastrophic on an affected machine (hours of hashing stealing directly from lanes A/B), zero on a healthy one.**

### P7 — Lanes A/B/C serialized per project, with one direction always idle

`sequencer.py:455-474` — `clone_structure` → `lane_a.run_once` → `lane_b.run_once` → `_lane_c_turn`, strictly in series, one project at a time.

Lane A is up-only and lane B is down-only. Tailscale/WireGuard is full duplex, so these can overlap essentially for free. Today, while a 40 GB upload saturates upstream for an hour, **downstream sits idle** — and vice versa. Expected saving for a project with work on both lanes ≈ `min(t_A, t_B)`, i.e. **up to 50% of pass wall clock**. Lane C is a separate process and needs no serialization at all beyond Syncthing's own `maxFolderConcurrency`.

### P8 — `project_rotation_seconds` does not bound lanes A/B: a 40 GB file blocks every other project

`sequencer.py:460`, `:468` — `run_once(subpath)` has no timeout; the 600 s rotation bounds only `_wait_for_folder_sync` (`:565`).

Answering the rotation question directly: **the 40 GB upload is not killed mid-transfer and does not restart from zero** on rotation — good. But it holds the entire sequencer, and therefore every other project's lane A, lane B *and* lane C turn, for its full duration. On a genuine kill (`stop()`/`pause()` from sign-out, shutdown or self-upgrade), `RcloneLane.stop()` (`:482-498`) sets an event and joins 5 s but **never kills the `Popen`** — so the child rclone keeps running orphaned. If it *is* killed, rclone's default `--inplace=false` leaves `<name>.partial` on the NAS and the next pass restarts from byte 0 (SFTP uploads do not resume). Those orphan `.partial` files are never cleaned, because lane A never deletes.

### P9 — Time-to-first-byte for a new clip is one whole pass; the debounce knob is dead in managed mode

`rclone_lane.py:725-741` (watchdog → `on_change` → `sequencer.notify_change`), `sequencer.py:245-262` (promotes the project to *next*, no preemption), `rclone_lane.py:752-758` (`_schedule_debounced_run` — unreachable once `on_change` is set, so **`watch_debounce_seconds` is a dead knob in managed mode**).

An editor drops a clip in and the upload starts only when the sequencer reaches that project: minutes at best, a full pass at worst. The watchdog already knows the exact path — that is a `--files-from` express upload waiting to happen (C-2).

Two more dead knobs, worth deleting or documenting: `scan_interval_up` / `scan_interval_down` (`config.py:58-59`) start no periodic loop in managed mode (`app.py:691-706`).

### P10 — Full destination traversal plus full local walk on every tick, for every project, forever — [measured]

`rclone_lane.py:250-264` / `:283-293` (no `--no-traverse`), `sequencer.py:455` + `rclone_lane.py:153-213` (`clone_directory_tree`).

Measured on 60 dirs / 600 files: default lane-A-shaped copy = `Checks: 300/300, Listed 843`; with `--no-traverse` = `Listed 422`. The destination tree is fully listed on every pass. Over SFTP that is `dirs / checkers × RTT` per project (400 dirs, 8 checkers, 30 ms ⇒ ~1.5 s) — and it happens **three times per project per pass** (lsf, lane A dest, lane B source).

Good news, also measured: the `- **/Proxy/**` rule **does** prune at directory level (`B-roll/day03/Proxy: Excluded`), so filter cost is not the problem. The problem is unconditional repetition — `clone_directory_tree` is fully redundant after the first pass in steady state.

**Important caveat measured here:** rclone 1.74 sets *directory* modtimes on the destination. With traverse it touches only dirs that received transfers (2 in the fixture); with `--no-traverse` it touched **all 61**. So `--no-traverse` alone is a pessimisation on a full pass — recommend it only paired with `--no-update-dir-modtime`, and only on express runs.

### P11 — `selection.get()` does a live HTTP fetch *and* rewrites a JSON file every 5 seconds

`selection.py:164-176` (`get()` always calls `fetch()`), `:121-130` (`_write_cache` on every success); called from `sequencer.py:413` and — the expensive one — `:568`, inside the 5-second poll loop.

While waiting out a 600 s lane C turn: **120 HTTP requests + 120 disk writes per project per pass, per editor**, versus the intended `selection_poll_interval = 60`. With 5 editors that is ~1 req/s hitting the dashboard *on the NAS* precisely while transfers are running. `write_text` truncates first, so a companion killed at that instant leaves a zero-byte `selection.json` → `load_cached()` returns None → next start with the dashboard down means `STATE_NO_SELECTION` and lanes A/B never run.

### P12 — The NAS re-walks a project's entire file tree every 5 minutes *while it is being uploaded into*

`collector.py:367-386` (`_dir_signature` = `os.walk` + `stat` every dir) + `:388-406` (`_walk_media_files` = `stat` every file), `settings.py:67-68` (`interval_inventory=300`, 8 projects/cycle).

The signature is `(dir_relpath, mtime_ns)`. Every new file changes its directory's mtime, so **during an active lane A upload the signature changes every cycle and the full per-file walk runs every 5 minutes**, then `db.replace_nas_media` rewrites all rows. For a 100k-file project that is 100k `stat`s plus a large SQLite rewrite every 5 minutes, on the box simultaneously serving SFTP and Syncthing.

### P13 — Completion polling scales as folders × devices every 30 s

`collector.py:417-451`, `settings.py:70` (`interval_completion=30`), plus `_run_enforce` calling `config()` + `system_status()` every 60 s and `_run_config` every 120 s. 20 projects × 5 editors ⇒ 120 Syncthing REST calls every 30 s (~4/s), and `/rest/db/completion` is computed on demand. Cheap per call, but it is CPU on the Syncthing app that is supposed to be moving lane C bytes.

### P14 — Nothing in production ever verifies the Tailscale path is direct

`server/check_health.py:65-87` checks only `BackendState == "Running"`. The only direct-vs-DERP check in the repo is `bench/ccbench/runners/iperf3.py:180-194`, a manual one-shot CLI — and it decides "direct" purely from `Peer[].Relay == ""`, when the robust signal is `CurAddr != ""` (a peer can carry a home-DERP region *and* a direct address). A path that starts direct can silently flap to DERP after a NAT rebind mid-transfer, and nothing notices, nothing reports it, and the dashboard shows a slow editor with no cause.

### P15 — `--ignore-existing` makes any truncated upload permanent

`rclone_lane.py:256` + `:260`. The only stability gate on lane A is `--min-age 30s`. A camera-card copy that stalls >30 s mid-file gets uploaded truncated, and `--ignore-existing` guarantees rclone will **never** correct it. Not a throughput bug, but it is the failure mode that most *looks* like one: "the NAS copy is broken and re-syncing doesn't fix it." See §5 L-14 for the measured detail — rclone does catch the mid-write case via hash mismatch, so the real costs are wasted upstream bandwidth and a scary recurring `corrupted on transfer` error; a file *pre-allocated* to its final size is the one that gets permanently frozen.

## §4.2 Tuning table

Lane A = `build_up_command` (`rclone_lane.py:250-264`); lane B = `build_down_command` (`:283-293`). **None of these exist as config keys today** — add them (`sftp_chunk_size`, `sftp_concurrency`, `checkers`, `transfers_small`) rather than hardcoding, so benchmark results can actually be applied (C-5).

| Location | Current | Recommended | Expected effect | Risk |
|---|---|---|---|---|
| both lanes | unset → 32 KiB | `--sftp-chunk-size 255Ki` | **The big one.** 8× in-flight window; per-file ceiling 70→545 MB/s @30 ms, 14→109 MB/s @150 ms | Some servers cap at 32 KiB; OpenSSH is fine. Watch for `failed to send packet payload: EOF`; fall back to 128Ki |
| both lanes | unset → 64 | keep 64, or 128 on ≥100 ms links | Window ×2 again | Memory is `chunk × concurrency × streams` — 255Ki×128 = 32 MiB/stream. Don't pair 255Ki with 256 |
| both lanes | unset | `--sftp-disable-hashcheck` | Removes the post-copy `md5sum` full-file re-read (P2) and 2 SSH probes/session; −10-25% wall clock on big files, large NAS I/O relief | **Integrity trade-off, no deletion risk:** end-to-end verification drops to size-only. SSH already MACs every packet; ZFS checksums at rest. To keep the belt, use `--ignore-checksum` instead — same saving, keeps hash-based comparison available |
| lane A | `--transfers 4` | 4 for originals; **16-32 for many-small-files** | Small-file SFTP is round-trip bound (~4-6 RTT/file ⇒ ~5 files/s/stream @30 ms). 4→32 streams ≈ 20→160 files/s | More sshd sessions — see the `--sftp-connections` row |
| both lanes | unset → `--checkers 8` | `--checkers 16` | Halves destination-traverse wall clock (P10) | Pair with `--sftp-connections 16` |
| both lanes | unset → unlimited | `--sftp-connections 16` | Caps rclone's SSH pool so wide checkers/transfers can't trip TrueNAS sshd `MaxStartups 10:30:100` | Or raise the sshd limits on the NAS instead |
| lane A | unset | `--no-traverse --no-update-dir-modtime`, **express runs only** (C-2) | Express run becomes 1 stat + 1 upload instead of a full tree listing | `--no-traverse` alone is a *pessimisation* on a full pass (measured: 61 dir-modtime setstats vs 2). Never ship it unpaired |
| lane A | unset | `--order-by modtime,descending` | The clip the team is waiting on goes first instead of in walk order | Needs the backlog; harmless |
| lane B | unset | `--order-by size,ascending` | Editor gets many usable proxies sooner on a cold project | None |
| lane B | unset | `--track-renames --track-renames-strategy modtime` | SPEC mandates reorganisations happen server-side, so renames *do* propagate down; converts delete+re-download into a local rename | Medium confidence — measure. Does **not** change delete semantics |
| lane B (`rclone sync`) | unset | **`--max-delete 100 --max-delete-size 20G`** | Not speed — a guard. Bounds DEL-2/DEL-3's blast radius | **Safety-positive.** Only cost: a legitimately huge server-side cleanup needs one manual override |
| both lanes | multi-thread unset | leave alone for SFTP (**no-op** — sftp is not a multi-thread-upload backend); if lane A moves to SMB, `--multi-thread-streams 8 --multi-thread-cutoff 256M` | On SMB this is what unlocks a single 40 GB file | — |
| both lanes | unset | `--fast-list` — **do not add** | No-op: SFTP has no `ListR` | — |
| both lanes | unset | `--use-server-modtime` — **do not add** | No-op for SFTP | — |
| both lanes | `--retries 3`, `--low-level-retries 10` | add `--retries-sleep 10s` | Stops a hot retry loop burning a pass when the tailnet flaps | None |
| both lanes | `--bwlimit` unset | consider 85% of measured upstream on lane A | **Deliberate sacrifice:** a saturated uplink adds hundreds of ms of bufferbloat to the Postgres/Resolve session on the same link (SPEC flaw #5) | −15% peak lane A |
| `rclone_lane.py:509` | `rclone_available()` spawns `rclone version` on **every** `run_once` | cache the probe | ~2N process spawns/pass saved | None |
| editor folder `syncthing_admin.py:129-138`; server `provision.py:142-159` | `maxConcurrentWrites`/`pullerMaxPendingKiB` unset | `maxConcurrentWrites: 32`, `pullerMaxPendingKiB: 65536` on WAN folders; leave `copiers`/`hashers` at 0 (auto) | Modest small-file gain | Low |
| **Syncthing global options — nothing sets these today** | `relaysEnabled=true`, `globalAnnounceEnabled=true`, `natEnabled=true` (defaults) | `relaysEnabled=false`, `globalAnnounceEnabled=false`, `natEnabled=false`; keep `localAnnounceEnabled=true` for the base rig | **Forces lane C onto the tailnet or fails loudly** instead of silently relaying (P3) | If the tailnet path is broken, lane C stops rather than degrading. That is the desired visible behaviour, but it *is* a behaviour change |
| device entries `syncthing_client.py:80`, `accept_device.py:80` | `["dynamic"]` | `["tcp://100.x.x.x:22000", "quic://100.x.x.x:22000", "dynamic"]` — tailnet first | Direct tailnet connection; removes the relay fallback | Requires the NAS's 22000 tcp+udp to be reachable on its tailnet IP through the container NAT — verify first |
| device entries | `compression` unset → `metadata` | keep `metadata` | Correct as-is | — |
| Syncthing global | `maxFolderConcurrency` unset (=GOMAXPROCS) | **1-2**, and delete the pause/unpause scheme | Gets "one project at a time" I/O *without* config churn, folder restarts, rescans, or 50-minute stalls (P4) | Ordering becomes Syncthing's choice, not tick order. A real loss of control — weigh against P4's cost |
| `sequencer.py:558-563` | `needTotalItems == 0` | also require server-side `completion.needBytes == 0` | Editor uploads finish before the folder is paused (P5) | None |
| `set_ignores` call sites | only at accept | re-assert per turn, or verify via `GET /rest/db/ignores` | Prevents an ignore-less folder SHA-256ing every 40 GB original (P6) | One extra REST call per turn |
| `settings.py:67` `interval_inventory=300` | unconditional full walk on any dir-mtime change | 900 s; skip projects with active transfers; or include file count + total size in the signature | Removes 100k stats + full SQLite rewrite every 5 min during uploads (P12) | Inventory freshness drops to 15 min |
| `settings.py:70` `interval_completion=30` | 30 s | 60 s (120 s with no editor connected); skip paused/unshared folders | Halves-to-quarters Syncthing REST CPU during transfers (P13) | Dashboard percentages update more slowly |
| `selection.py:164-176` | live fetch + file write per call | 30 s TTL; write only on change | Kills 120 requests + 120 disk writes per project per pass (P11) | Selection changes land ≤30 s later |
| `config.py:114` `project_rotation_seconds=600` | 600 | 180-300 **once P4/P7 are done** | Fairness across projects | Only safe *after* the pause scheme is gone |
| `config.py:62` `watch_debounce_seconds`, `:58-59` `scan_interval_*` | dead in managed mode | wire to the express run (C-2) or delete | Removes knobs that silently do nothing | — |
| `sequencer.py:578-611` | `_POLL_CHUNK_SECONDS = 0.05` — the sequencer is always in one of these waits, so the process wakes 20×/s indefinitely | wait on a single `_interrupt` Event with the full remaining timeout | Laptop battery, and needless wakeups | None |

## §4.3 Architectural changes

**C-1 — Run lanes A and B concurrently; stop pausing Syncthing folders.** *(effort: ~1 day; payoff: very high)* Two threads in `_process_project` (`sequencer.py:455-474`), joined before the next project. A and B are opposite directions over disjoint file sets (`**/Proxy/**` vs everything else) in separate processes — there is no correctness reason to serialize them. What genuinely must stay serialized: `repather.reconcile()` **before** lane A for the same project (`sequencer.py:447` — otherwise lane A re-uploads a stale tree to a dead NAS path), and two lane A runs on the same project (already handled by `_run_lock`). Lane C should simply be left running for all selected folders, with `maxFolderConcurrency` doing the pacing. **Expected: up to 50% pass wall-clock reduction, lane C latency from ~50 min to seconds, ~1000 fewer Syncthing config writes/hour, ~180 fewer folder rescans/hour.** Risk: upstream and downstream now compete for editor CPU/disk; cap with `--bwlimit` if it bites.

**C-2 — Express lane A for watchdog events (`--files-from`).** *(medium effort; high payoff)* The watchdog already has the exact path (`rclone_lane.py:716-741`). Write it to a list file and run a second short-lived rclone: `copy --files-from-raw list.txt --no-traverse --no-update-dir-modtime --ignore-existing --min-age 30s`. That is 1 stat + 1 upload instead of a full-tree traverse, starting seconds after the file settles rather than at the next pass. Keep the periodic full pass as the safety net. Turns P9's "minutes to an hour" into ~40 s. Risk: needs its own lock — don't reuse `_run_lock` or you serialize behind the 40 GB upload.

**C-3 — Make `clone_directory_tree` conditional.** *(small; medium)* Gate it on first-pass-after-startup, after a repath, or every M passes (M≈10); or compare the returned dir count/hash to a cached value and skip the mkdir loop when unchanged. Saves ~1.5 s × N per pass plus N SSH handshakes. Also add `--exclude ".stversions/**" --exclude ".stfolder/**"` — which is DEL-1's fix, and independently a large listing saving, since `.stversions` on the NAS accumulates a deep mirror of every deleted file's directory structure.

**C-4 — Benchmark SMB honestly for lane A.** *(small; potentially very high)* `rclone_smb` **is** a multi-thread-upload backend; `rclone_sftp` is not. For the single-40 GB-BRAW case that is a structural advantage the current bench explicitly disables (see §4.4). Also worth measuring: SMB multichannel, and `robocopy /MT` as the raw baseline. `rclone serve` is *not* the answer — `serve sftp` is documented as fixed at a 32 k payload, exactly the limit you're trying to escape.

**C-5 — Make bench output applyable.** *(small; high)* Add config keys in `companion/config.py` for every flag the report recommends. Today `transfers` is the only tunable that survives the trip from bench to production.

**C-6 — Verify and monitor the network path continuously.** *(small; high diagnostic value)* Add to the companion's report payload: `tailscale status --json` for the NAS peer (direct iff `CurAddr != ""`), and Syncthing's `/rest/system/connections` `type` per device (`tcp-client`/`quic-client` vs **`relay-client`**). Surface both on the fleet strip. Without this you cannot distinguish a slow editor from a relayed one, and P3/P14 make either plausible right now. Also fix `iperf3.py:187` to key on `CurAddr`, not `Relay == ""`.

**C-7 — Kill the child rclone on stop; *report* orphan `.partial` files.** *(small)* `RcloneLane.stop()` should terminate the `Popen` (or use a Windows job object) so a self-upgrade doesn't leave two rclones fighting over the same tree — which for lane B means two concurrent `sync`s of the same destination deleting each other's partials. **On the `.partial` cleanup: recommend reporting, not deleting.** It is the one performance suggestion that would add a delete-on-NAS path, and the hard requirement outranks the hygiene gain.

## §4.4 Benchmark validity — round 1's §10 is entirely unfixed, plus two new defects

`git log --oneline -- bench/` shows **one** commit (the initial build). **Every §10 critical is present verbatim:** dest not emptied before the timed download (`_rclone_common.py:126` + `matrix.py:125-126`), `num_bytes = manifest_bytes` on exit-0 (`:146`), `_seed_remote` swallowing rc/timeouts (`:69-81`), purge-after-every-run warming the ARC (`:177-178`), `max()` across repeats (`report.py:42-57`), `verified=True` on exit code for "up" (`:152-156`), lane re-derived by dataset substring (`report.py:22-35`), Syncthing benchmarked on loopback, `mb_per_s` MiB-vs-MB (`base.py:144-147`), unwrapped `runner.run` (`matrix.py:108`).

Two additional defects round 1 did not name:

- **`bench.toml.example:80` — `sftp_chunk_size_mb = [4, 32]`.** The unit is *megabytes*; the SFTP protocol max total packet is **256 KiB**, and rclone's guidance is `255k`. So the sweep tests 4 MB and 32 MB — values that will error or degrade — and **can never express the one value that matters (P1)**. `_rclone_common.py:65` and `report.py:70` both hardcode the `M` suffix.
- **`_rclone_common.py:45` — `mts_options = mts_raw if direction == "down" else [0]`.** Forcing `--multi-thread-streams 0` on "up" is a harmless no-op for SFTP but **handicaps `rclone_smb`, which is multi-thread-upload capable.** The A/B test meant to decide SFTP-vs-SMB for lane A systematically disables SMB's main advantage.

**Would bench's winner be the real winner? No.** It measures the wrong flag space (no `sftp-chunk-size` in a valid unit, no `sftp-concurrency`, no `checkers`, no `disable-hashcheck`, no small-file `transfers` sweep past 16), with the production argv absent (`--ignore-existing`, `--min-age`, filters, `--stats`), against a NAS whose cache it warms itself, reporting manifest bytes rather than moved bytes. **Nothing currently in `results/` should be used to pick anything.**

## §4.5 What to measure, in order

Each step is cheap and unblocks the next.

1. **Path check first (5 min).** `tailscale status --json` on an editor → NAS peer: is `CurAddr` non-empty? Then `/rest/system/connections` on both sides: is any device `type: relay-client`? If yes, **P3 is your 60 mb/s and no rclone flag matters yet.**
2. **Raw ceiling and RTT (10 min).** `iperf3 -c <nas-tailnet> -P 1` and `-P 8`, both directions, plus `ping`. The RTT turns P1's table into a number: `2 MiB / RTT` is your current per-file lane A ceiling. If observed ≈ that value, P1 is confirmed outright.
3. **P1 A/B (20 min).** One 8-20 GB file, `--sftp-chunk-size 32Ki` vs `255Ki`, everything else identical, fresh file each run. Expect a multiple, not a percentage.
4. **P2 A/B (15 min).** Same file ± `--sftp-disable-hashcheck`; record wall clock *and* NAS disk reads (`zpool iostat 1`) — the hash pass shows as a big read burst after the transfer with no network traffic.
5. **Small-file sweep (20 min).** 2000 × 200 KB, lane-A argv, `--transfers ∈ {4,8,16,32}`. Plot files/s; should track `transfers / (5 × RTT)` until sshd or CPU caps it. This decides whether rclone or Syncthing should own small files.
6. **Steady-state overhead (30 min, nothing to move).** Time `_clone_structure`, each `run_once`, each `_lane_c_turn`; count Syncthing config writes and folder scans per hour. Estimate for N=6: ~25-40 s overhead per pass, ~180 rescans/hour. Confirm before and after C-1.
7. **Concurrency win (1 h).** A project with both a pending upload and pending proxies: time serial vs C-1 concurrent. Confirm sum-of-throughput at the interface exceeds either lane alone — that proves you're duplex-limited, not CPU-limited.
8. **Lane C latency (15 min).** Touch a small file in a *non-current* project, time until it lands on the NAS. Today: up to `(N-1) × rotation`. After C-1: `fsWatcherDelayS` + transfer.
9. **NAS-side contention (during 7).** `docker stats` on the syncthing and dashboard containers while lane A runs. If P12's inventory walk or P13's polling is a meaningful slice, apply the interval changes and re-measure.
10. **Only then re-run bench** — after §4.4's criticals are fixed, `sftp_chunk_size` takes a real unit, and SMB's handicap is removed. Report median-of-repeats, and label loopback Syncthing rows non-comparable.

---

# §5. Sync lanes and sequencer

Filter correctness was verified empirically against the bundled rclone 1.74.4 with the exact argv the code emits — see §5.1. Three thread-lifecycle defects were reproduced live.

### L-1 — `Sequencer.start()` after a timed-out `stop()` spawns a **second live sequencer thread** and orphans the first forever — **CRITICAL** [reproduced live]

`sequencer.py:137-143`. `stop()` joins with `timeout=10` (`:154`); `start()` then does `_stop_event.clear()` + `threading.Thread(...)` with **no liveness guard**. `RcloneLane.start():444` and `SyncthingLane.start():213` both received that guard in round 1's §4 fix; `Sequencer.start()` did not.

Reproduced with `lane_a.run_once` taking 15 s — a trivially realistic rclone run:

```
stop() took 10.0s
old thread still alive after stop(): True
new thread: True | both alive: True True
live sequencer threads after 4s: 2
```

Thread #1 is now looping against a *cleared* `_stop_event` and can never exit.

**Concrete trigger.** The editor uses tray Sign out → Sign in (or any self-upgrade / re-auth) while lane A is mid-upload of a 40 GB `.braw` — minutes to hours, so `join(10)` always times out. Two sequencers now race: both run `_lane_c_turn`, so thread #1 pauses folder set {A,C} while thread #2 unpauses B and pauses {A,C}… Syncthing folders flip paused/unpaused several times a second, `_in_lane_c_turn` (a single bool) is corrupted by whichever thread wrote last, and both drive `lane_a.run_once`/`lane_b.run_once` back to back — serialized only by `_run_lock`, so rotation collapses entirely. **Each subsequent sign-out/sign-in adds another permanent thread.**

**Fix.** Copy `RcloneLane.start()`'s guard verbatim: `if self._thread is not None and self._thread.is_alive(): return` before `_stop_event.clear()`.

### L-2 — Round 1's thread-leak fix turned the leak into **permanent lane death** — **HIGH** [reproduced live] **[REGRESSION]**

`rclone_lane.py:443-451`, `syncthing_lane.py:212-219`.

`stop()` sets `_stop_event`, joins for 5 s, and sets `_observer = None` (`:498`) — but leaves `_periodic_thread` non-None. If the join times out, `start()` hits the new liveness guard and returns **without clearing `_stop_event` and without calling `_start_watchdog()`**. Thread #1 then finishes its run, sees the still-set event, and exits. Nobody ever starts a replacement.

Reproduced with an 8 s run and `stop()`/`start()` 0.5 s apart:

```
stop() took 5.0s, old thread alive: True
after start(): _periodic_thread is old thread? True | stop_event set? True | observer: None
old thread alive now: False   (exited)
lane._periodic_thread alive: False
```

The fix's own comment says an rclone run "can take minutes", so the 5 s join routinely times out. After **one** Pause→Resume or sign-out→sign-in during a lane run, lane A/B has no periodic thread, no watchdog, and a latched `_stop_event`. It never syncs again for the process lifetime. **The tray shows the last status (`idle`), so it looks healthy.** This is strictly worse than the leak it replaced.

`test_start_is_noop_when_periodic_thread_still_alive` (`test_rclone_lane.py:364`) **asserts this state is correct** (`assert lane._stop_event.is_set()`). The test for the real scenario (`test_stop_then_start_does_not_leak_the_old_thread:415`) sets `scan_interval = 0.01` so the join always succeeds — it never exercises the case the fix comment describes.

**Fix.** Make `start()` idempotent *and* recoverable: if a thread is alive, `join(timeout=…)`; if still alive, log but **clear `_stop_event` and re-arm the watchdog**; otherwise fall through to a fresh thread. Better: give each generation its own `threading.Event`, so a stale thread can never be re-armed and a new one can always start.

### L-3 — The sequencer unpauses a folder whose `.stignore` failed to land, defeating round 1's fix — **HIGH**

`sequencer.py:507` + `:524` vs `syncthing_admin.py:115-142`.

`accept_folder` was fixed to create the folder `paused: True` → `set_ignores` → unpause, and its docstring promises "if it raises, the folder is left paused rather than silently syncing unfiltered." But `_lane_c_turn` calls `_maybe_auto_accept(slug, rel_path)` — which swallows the exception (`:549-550`) — and then, ~1 ms later at `:524`, unconditionally does `self.admin.set_folder_paused(slug, False)`.

`test_syncthing_admin.py:90` asserts the guarantee the caller immediately breaks.

**Concrete trigger.** The `POST /rest/db/ignores` call times out (default `timeout=5.0`, `syncthing_admin.py:51`; a Syncthing config commit on a rig with many folders regularly exceeds that). `accept_folder` raises after the folder is created; `_maybe_auto_accept` logs and returns; `_lane_c_turn` unpauses it. The folder is no longer in `pending_folders()`, so **nothing ever retries `set_ignores`** — it runs with no ignores for the life of the install. The editor's Syncthing indexes and block-hashes every `.braw`/`.mov` original and every `Proxy/` file (terabytes of hashing — see §4 P6). And if the *server*-side folder is also missing its ignores — the collector sets them create-only (DASH-H1), so one failed call there is equally permanent — **video flows down to the editor and proxies flow up: a straight lane-direction violation.**

**Fix.** Have `_maybe_auto_accept` return a bool and skip the `set_folder_paused(slug, False)` at `:524` when accept failed. Additionally re-assert `set_ignores` for the current folder once per turn, so folders accepted by an older companion, by hand in the Syncthing GUI, or after a repath get reconciled — **nothing in the current code ever sets ignores on a folder it didn't itself accept.**

### L-4 — `_process_project` is unbounded, so `project_rotation_seconds` prevents neither starvation nor indefinitely-paused folders — **HIGH**

`sequencer.py:434-474`. `project_rotation_seconds` caps only `_wait_for_folder_sync` (`:565`). `_clone_structure`, `lane_a.run_once` and `lane_b.run_once` have **no time budget**, and `_run_popen`'s `proc.wait()` (`rclone_lane.py:635`) has no timeout.

**Concrete trigger.** Four ticked projects; project 2 receives a 200 GB card ingest, so lane A takes ~18 h on HiNet upstream. Project 1's `_lane_c_turn` has already paused folders 2/3/4 and unpaused 1; the pass advances to project 2 and blocks inside `lane_a.run_once` for 18 h. **Folders 3 and 4 stay paused that whole time** — the only unpause sweeps are `_lane_c_turn`'s single-folder unpause and the between-passes `_unpause_all` (`:296`), neither of which is reached. So lane C silently does not sync audio/GFX/AE/subs for two of four projects for 18 hours, while `status_detail()` reports `syncing <project 2> (2/4)` and lane C's `LaneStatus` reports `idle` (L-6). Projects 3 and 4 also get no lane A/B pass in that window.

**Fix.** Give lanes A/B a per-project budget (`--max-duration` on the argv, or kill the subprocess past `project_rotation_seconds` and resume next pass), and unpause the full selection before any long lane A/B run rather than only between passes.

### L-6 — Lane C reports `idle` / `last_sync=now` unconditionally for every managed editor — **HIGH**

`syncthing_lane.py:146-209` + `app.py:288`. `expected_folder_ids = cfg.get("syncthing_folder_ids", [])`, whose default is `[]` (`config.py:69`) and which every installer writes as a literal `[]`. Nothing in managed mode ever populates it — the sequencer owns the slugs and the lane never learns them. So `check_once` skips the configured/shared checks (`:170-177`), the `queued` loop (`:195-200`) iterates nothing, and `:204-207` returns `STATE_IDLE, queued=0, last_sync=datetime.now()` on every 15 s poll as long as `/rest/system/ping` answers.

`test_check_once_no_expected_folders_is_idle` (`:167`) enshrines this.

**Consequence.** Every editor's lane C dot is green with "last synced: just now" while — per L-3, L-4, L-8 — folders are paused, un-ignored, in `error` state, or hours behind. Even *with* folder IDs configured, `check_once` never reads the folder's `paused` flag or `db/status`'s `state`/`errors` fields, and per-folder `db/status` failures are swallowed to `log.debug` leaving `queued=0` → still `idle`.

**Fix.** Feed the lane the sequencer's live slugs (`sequencer.rel_to_slug` values); report `STATE_PAUSED` when the folder config says paused and `STATE_ERROR` when `db/status.state == "error"` or `errors > 0`; never emit `last_sync` when `expected_folder_ids` is empty. This is the same defect UX-3 reaches from the user's side.

### L-8 — A failed move still re-points Syncthing, leaving the folder aimed at a path that doesn't exist — **MEDIUM**

`repath.py:149-153`. `_move_dir` catches `OSError`, logs, and **returns normally**; `reconcile` then executes `set_folder_path(slug, expected)` and unpauses. `_default_move` is `os.rename`, which raises `EXDEV` for a cross-volume move (a `subst`ed `P:` whose target is on another drive, or a reconfigured `local_root`) and `EACCES` when Resolve or Explorer holds a handle inside the project dir — routine, since the editor is usually working in that project.

**Concrete trigger.** Repath fires while Resolve has the project's media open → rename fails with a sharing violation → Syncthing is re-pointed to `…\Projects\<new rel>`, which does not exist and has no `.stfolder`. Lane C goes to `error: folder marker missing` for that project **permanently** — the compare at `:107` now matches, so reconcile never retries — while all the editor's files sit in the old directory. Per L-6, lane C still reports `idle`. Meanwhile `_clone_structure` mkdirs the new empty tree (and per DEL-1 lays down a local `.stfolder`, masking the very error that was the only signal), lane A uploads nothing, and lane B `rclone sync`s the NAS proxies into the new empty dir — so the editor sees an apparently-fine but content-free project.

**Fix.** Return a bool from `_move_dir` and call `set_folder_path` only on success; on failure leave the folder pointed at `actual` and log a user-visible error. Add `shutil.move` as the cross-volume fallback.

### L-10 — `notify_change` re-prepends the project being written to; a mid-pass selection change restarts the pass from position 0 — **MEDIUM**

`sequencer.py:245-262` + `369-423`. `notify_change` rebuilds `_queue` with the changed project at the head, with no check that it was already processed this pass. Lane A's watchdog fires `on_created`/`on_modified` per write chunk (`rclone_lane.py:707-714`).

**Concrete trigger.** The editor ingests a card into project 1 of 5. Thousands of `on_modified` events per minute each take the sequencer `_lock` and re-prepend project 1, so the queue is `[P1, P2, …]` at essentially every pop and **projects 3-5 never reach `_lane_c_turn` for the duration of the ingest.** Separately, `_run_pass:420-423` on any selection change discards `processed` and restarts from `ordered[0]`, re-running `_clone_structure` and both rclone lanes for already-done projects; a selection that changes once per pass (an editor toggling ticks, or DASH's `add_selection` position race) permanently starves the tail.

**Fix.** Ignore `notify_change` for slugs already processed in the current pass; on restart, skip already-processed slugs whose entry is unchanged.

### L-11 — A slow pause-sweep can leave **every** folder paused, and unaccepted slugs produce a traceback per project per pass — **MEDIUM**

`sequencer.py:504-529` + `syncthing_admin.py:100`. `set_folder_paused` PATCHes with a 5 s timeout; Syncthing commits and restarts the folder on that PATCH, which on a rig with many folders routinely exceeds 5 s. `_lane_c_turn` pauses N-1 folders then unpauses the current one — if *that last* call times out or 404s because the folder isn't accepted locally, the current folder stays paused too: **all selected folders paused, lane C fully stopped**, until the between-passes `_unpause_all` — which issues the same fragile calls and whose failures are only `log.exception`'d. If the pass is long (L-4), that sweep is hours away or never.

Separately, both sweeps are called for slugs the editor has not accepted, where Syncthing returns 404 → `HTTPError` → `log.exception` writes a full traceback. With 5 selected projects that is ~10 tracebacks per pass in `companion.log`, burying real errors.

**Fix.** Raise the admin timeout for config writes, verify the resulting paused state via `get_config()` at the end of the turn, and downgrade "folder not configured locally" to a single `log.debug`.

### L-12 — No timeout on the rclone subprocess, and `stop()` never kills it — **MEDIUM**

`rclone_lane.py:599-637`. `proc.wait()` (`:635`) is unbounded and the legacy path passes `timeout=None` explicitly (`:545`). `RcloneLane.stop()` (`:482`) sets the stop event and joins the *thread* but never touches the child. rclone's own `--timeout 5m` idle default usually saves this, but not for a peer that ACKs and stalls (a Tailscale DERP flap, a TrueNAS SFTP subsystem hang), and not for `lsf` over a wedged mount.

Two consequences: (a) an unkillable run holds `_run_lock` and blocks the sequencer forever — L-4's mechanism with no upper bound; (b) at shutdown or self-upgrade the rclone child **survives the parent's exit on Windows**, so the newly-spawned companion starts a second rclone against the same tree and the same NAS path. `--ignore-existing` limits the damage on lane A, but **lane B is `rclone sync` — two concurrent syncs of the same destination will delete and re-fetch each other's `.partial` files.**

**Fix.** Keep a handle to the live `Popen` and `terminate()`/`kill()` it in `stop()`; add `--timeout`/`--contimeout`/`--max-duration`.

### L-13 — Lane B's routine `rclone sync` deletes local `Proxy/` content and prunes its directories — **MEDIUM** [measured]

Ran the **exact** argv `build_down_command` produces against a scratch tree. Containment is correct — non-proxy media is safe:

```
Sub/Proxy/local_only_proxy.mov : deleted
Local/Proxy/orphan.mov         : deleted   (+ "Local/Proxy", "Local" removed as dirs)
Audio/Music/precious.wav       : untouched
Local/original_master.braw     : untouched   [confirmed by a real, non-dry run]
```

A **non-existent** remote source aborts safely (`Failed to sync: directory not found`, no deletions). An **empty** remote source deletes every local proxy (`Deleted: 6 files, 14 dirs`).

So any proxy an editor generated locally that the NAS has never seen is destroyed on the first lane B pass, and the directories that held it are removed — the structure clone recreates them next pass, so the churn is invisible. Regenerable content, hence MEDIUM. But it is DEL-2/DEL-3's mechanism reached from the **normal sequencer path**, not just Consolidate.

### L-14 — `--min-age 30s` is not a file-stability guard for mtime-preserving ingests — **LOW** [measured]

`rclone_lane.py:260`. Windows `CopyFile`, Explorer, `shutil.copy2` and card-ingest tools preserve the source mtime, so a 40 GB `.braw` copied into the tree satisfies `--min-age 30s` from the instant it appears.

Measured: rclone **does** catch the resulting mid-write read — it errors `corrupted on transfer: md5 hashes differ`, removes the `.partial`, and exits 1. So no truncated original is ever committed and the next pass re-uploads correctly. The real costs are (a) the full partial transfer is wasted upstream bandwidth, repeated every scan interval or watchdog fire for the whole ingest, and (b) each attempt sets `STATE_ERROR` with a scary `corrupted on transfer` message on the dashboard. **The dangerous variant:** a file *pre-allocated* to its final size before being filled would pass the size and hash check against whatever it contained, and then be permanently frozen by `--ignore-existing` (§4 P15).

**Fix.** Wait for two consecutive size-stable observations (or raise to `--min-age 120s`). Note `.partial` files left by a hard kill accumulate on the NAS forever, since lane A never deletes.

### L-15 — Round 1's BAD_PREFIX fix silently removed the SPEC-mandated warning for an unmapped `P:` — **MEDIUM** **[REGRESSION]**

`watcher.py:138-147` + `paths.py:88-121`. The notification storm is genuinely fixed (`paths.py:97-111` returns `MISSING` for a canonical-prefix path that doesn't exist), and the comment openly accepts the ambiguity. But round 1's prescribed fix was *"return `MISSING` when the prefix resolves correctly but the file is simply not downloaded."* The implemented version returns `MISSING` whenever the file doesn't exist, **regardless of whether the prefix resolves at all.**

SPEC component 2 requires a mapping-health warning for exactly this case. The *primary* failure — `subst P:` didn't run at login, or the Mac Mapped Mount is unset — now produces `MISSING` for every clip: **zero warnings, zero tray notifications**, every clip offline, nothing in the log above `debug`. `BAD_PREFIX` is now reachable only when the file *exists* at the same rel path under a wrongly-targeted mount, so `watcher.py`'s `on_mapping_warning` → `app.py:315` tray balloon is effectively dead code. The rewritten tests assert this.

**Fix.** Probe the prefix, not the file: `if not exists: return MISSING if _is_under(_norm(realpath(canonical_prefix)), norm_root, sep) else BAD_PREFIX` — one `realpath` on `P:\` per call, cacheable. Do this once per poll rather than per clip.

### Lanes — low

- **L-5** — `sequencer.py:568` re-fetches the selection over HTTP **and rewrites `state/selection.json`** on every 5 s poll tick (round 1 §4 item 1, not fixed). See §4 P11 for the arithmetic and the zero-byte-cache failure.
- **L-16** — `manifest.py:140-150`: `start()` after `stop()` is a silent no-op (round 1 §6, not fixed). `stop()` never clears `_thread` or joins, so a sign-out→sign-in leaves the manifest thread dead while `get()` keeps serving the last scan as current — the dashboard's per-editor "has X of Y originals" freezes at a stale value indefinitely.
- **L-17** — `watcher.py:77,141`: `_warned_mapping` grows without bound and warns once per *process lifetime*, so a mapping that breaks, is fixed, then breaks again is never reported again.
- **L-18** — `sequencer.py:578-611`: both interruptible waits poll at 20 Hz forever (`_POLL_CHUNK_SECONDS = 0.05`). The sequencer is always in one of them, so the process wakes 20×/s indefinitely on a laptop. `_wait_for_lane_c_turn_idle:189` uses a bare `time.sleep`.

## §5.1 Filters — verified clean, empirically

Round 1's S-4 and S-5 are **genuinely fixed**, and this was confirmed against the real binary with the exact argv the code emits, both lanes, both sides of the filter:

```
LANE A + --ignore-case:  CLIP.MOV ✅ CAM.Mp4 ✅ clip2.mov ✅ A001.BRAW ✅
                         Sub/proxy/* excluded ✅  PROXY/* excluded ✅
LANE A baseline (no flag): CLIP.MOV / CAM.Mp4 / A001.BRAW dropped; proxy/* wrongly uploaded
LANE B + --ignore-case:  PROXY/root_upper.mov, Sub/proxy/p_lower.mov, Sub/proxy/P_UPPER.MOV ✅
LANE B baseline:         nothing pulled
```

Lane A uploaded exactly the 7 non-proxy video files and nothing else, including `Space Dir/clip with space.mov` and `Interviewees/a&b^c.mov`; it excluded root-level `Proxy/`, nested `Sub/Proxy/`, depth-4 `A/B/C/Proxy/`, and case-variant `Interviewees/PROXY/`. Lane B pulled only Proxy contents at every depth including root and `PROXY`.

First-match-wins ordering is correct (the two Proxy excludes precede the video includes; `- **` is last). The `**/` + `/`-anchored pair for root-level Proxy is necessary and correct. The `.stignore` twins were already correct — `(?i)` in all three generators (`syncthing_admin.py:44-47`, `provision.build_stignore_lines`, `server/common.py:89`) — so there is no gap there. **However:** `test_rclone_filters.py`'s fixture tree is entirely lowercase `.mov` with correctly-cased `Proxy`, and only asserts `"--ignore-case" in cmd`. There is no mixed-case integration test anywhere; the empirical check above is the only real coverage.

## §5.2 Lanes — other verified-clean items

Paths with spaces, `&` and `^` transfer correctly; no `shell=True` anywhere in scope; every invocation is an argv list. Filter files are per-direction and per-purpose, so there is no concurrent-writer race *within* one process (DEL-2's race is cross-process). `_run_lock` correctly serializes the periodic loop against watchdog-debounced runs. Round 1's S-6 is fixed in `rclone_lane.py` (all four spawn sites carry `encoding="utf-8", errors="replace"`, and `_reader` wraps the loop in try/except + `proc.kill()`) — the miss is `consolidate.py:144` (DEL-0). §4's `CREATE_NO_WINDOW` fix landed at all four `rclone_lane` sites. Exit-code interpretation is correct: `returncode` is authoritative, transient `Attempt n/3 failed` lines don't fail a successful run, `parse_json_log` tolerates non-JSON and partial lines, malformed `--stats` lines are skipped without raising. `_local_subpath` correctly prevents a leading separator discarding `local_root`; `_join_remote_path` never double-slashes; `clone_directory_tree` rejects absolute and `..`-bearing entries and returns `None` rather than raising. `_project_rel_for_path`'s longest-known-rel-prefix attribution is correct at any depth, case-insensitively. Lane directions are structurally sound (`up` is only ever `copy` local→remote with `--ignore-existing`; `down` only `sync` remote→local; both derived from a constructor-asserted `direction`). `LaneStatus` snapshots don't alias the live `transfers` list. `watcher.py` never raises (bridge call, both callbacks and the loop body individually guarded) and correctly doesn't re-fire `on_project_changed` on a Resolve flap. `manifest.py` never raises on a bad `local_root`, rollups stay exact when per-file lists are truncated, and `refresh_once` failures leave the previous cache intact. No `except: pass` swallowing in scope; nothing under `state/` grows unbounded from these modules; everything is slug-keyed, not name-keyed.

---

# §6. Installers, onboarding, and server scripts

All four `.ps1` files tokenize clean under `PSParser::Tokenize` on PS 5.1.26100; `bash -n macos_bootstrap.sh` clean; `server/tests` 24 passed, `onboarding/tests` 74 passed. These scripts run **once** on a real machine, so a silent misconfiguration here is permanent from the editor's point of view.

## Critical

### INST-1 — Every doc tells the editor to run the bootstrap **elevated**, which is the one way to make the `P:` mapping invisible to Resolve

`windows_bootstrap.ps1:557-565` (comment), `:626`, `:658`; `START_HERE.md:47-48`; `docs/EDITOR_SETUP.md:49-51`; `installer/README.md:83`, `:113`.

The script's own comment is correct and load-bearing: *"the `net use` MAPPING must run in THIS process at the user's normal integrity level — a drive mapped by an elevated token is invisible to the user's unelevated session (UAC linked-token isolation), which would leave Resolve staring at a missing `P:`."* But the whole script runs in one process, so "THIS process" is elevated whenever the editor follows the documented instruction. Both mapping styles are per-logon-session, so `subst` (`:658`) is affected identically.

**Concrete trigger.** The editor follows START_HERE step 2 in an admin PowerShell. The script prints `mapped P: -> \\localhost\CCSync_P (persistent — no logon task needed)` and `labelled P: as 'TheCreatorsClub'` — because section 5b's `Get-PSDrive -Name P` succeeds *in the elevated session*. The editor opens Resolve, unelevated: **no `P:` drive, every clip in the shared project offline.** Nothing in the output hints at it; `Test-Path P:\` from their normal shell says no. They conclude the installer failed and re-run it — same result, forever, until they happen to reboot. It also launches Explorer (`:718`) and the companion (`:1007`) at High integrity for the rest of the session.

**Fix.** Either drop the elevation recommendation from all three docs and let the script's UAC helper do the share (which is what the `onboard.exe` path does, correctly), or detect `$IsElevated` at `:625` and either re-run just the `net use` unelevated or print a loud "you ran this elevated — log off and back on before opening Resolve."

### INST-2 — A `-LocalRoot` containing a space silently breaks the `P:` logon remap forever — [measured]

`windows_bootstrap.ps1:513` → `:640` and `:208`/`:652`.

```powershell
$SubstCommand = "subst P: $CCRoot"                                                # :513
$action = New-ScheduledTaskAction -Execute "cmd.exe" -Argument "/c $SubstCommand" # :640
$cmdBody = "@echo off" + "`r`n" + $CommandLine + "`r`n"                           # :208
```

Measured: the same string through `cmd /c "<exe> P: D:\My Media\Creators_Club"` yields `ARG1=[P:] ARG2=[D:\My] ARG3=[Media\Creators_Club]`. The direct call at `:658` is fine — PowerShell auto-quotes there, **which is exactly why the install looks successful.**

**Concrete trigger.** `EDITOR_SETUP.md:48` and `START_HERE.md:59-63` both invite `-LocalRoot <other drive>`; `onboard.py:379` offers a free-text field. The editor uses `D:\Video Projects\Creators_Club`. The first run maps `P:` correctly. At **every subsequent logon** the task/shim runs `subst P: D:\Video` → "Path not found", no window, no log. The machine boots with no `P:`, Resolve fully offline — and the companion, whose `local_root` is the real path, reports green, so the dashboard says the editor is healthy.

**Fix.** `$SubstCommand = "subst P: `"$CCRoot`""` and quote in the `-Argument` string. Reject a `-LocalRoot` containing `"`.

### INST-3 — `windows_upgrade.ps1` double-encodes every non-ASCII value in `config.toml` — [measured] **[REGRESSION]**

`windows_upgrade.ps1:137` (`$lines = @(Get-Content -LiteralPath $ConfigPath)`), same at `:204`.

`Get-Content` with no `-Encoding` auto-detects a BOM and otherwise falls back to the system ANSI codepage. The file is now UTF-8 **no-BOM** — that half of round 1's S-2 was fixed — so this read is newly wrong. **Before `b989422` the bootstrap wrote a BOM, so the round-trip preserved non-ASCII; it merely broke `tomllib`. Now it corrupts.** Measured round-trip on this rig:

```
on-disk (utf-8 no BOM):      editor_name = "台北-alex"
Get-Content (no -Encoding) → editor_name = "å°åŒ—-alex"
written back →               editor_name = "å°åŒ—-alex"     ← permanently mangled
Get-Content -Encoding UTF8 → editor_name = "台北-alex"     ← correct
```

The result is still *valid* UTF-8 and *valid* TOML, so nothing errors anywhere. **Every `windows_upgrade.ps1` run now corrupts a non-ASCII `editor_name`** (dashboard reports and selections then go to a nonexistent editor, silently), or a `local_root`/`log_path` under a non-ASCII Windows profile — in which case `validate_config` logs `local_root does not exist: D:\RenÃ©e Media\…` into a log nobody reads, and `log_path` may not even land where the docs say.

**Fix.** `Get-Content -LiteralPath $ConfigPath -Encoding UTF8` at `:137` and `:204` (verified: PS 5.1's `-Encoding UTF8` on *read* strips a BOM if present and decodes BOM-less UTF-8 correctly; only *writes* add a BOM). Same at `windows_bootstrap.ps1:818`, where `Get-Content -Raw` on the now-UTF-8-appended `rclone.conf` makes the `-match` duplicate detection miss and append a second `[remote]` block.

### INST-4 — A fresh manual install syncs nothing, and no editor-facing doc mentions the tray sign-in

`config.py:88` (`require_login: True`), `app.py:917-928`; `windows_bootstrap.ps1:867-917` (the seeded config omits `require_login`); `START_HERE.md:120-125`; `EDITOR_SETUP.md:151-159`.

`require_login` defaults true and the bootstrap-seeded config never sets it, so `app.py` refuses to start the lanes and sequencer until `identity.json` exists. **Only `onboard.exe` writes that file.** The manual path — the one both editor docs describe, and the documented repair path — leaves the companion permanently gated.

Both docs point the editor at the *web* dashboard instead (`START_HERE.md:120`: *"Right-click the tray icon → Open dashboard to sign in"*; `EDITOR_SETUP.md:151`: *"Open the dashboard in a browser and sign in"*). Neither mentions the tray's `Sign in…` item (`tray.py:364`); only `FIRST_UPGRADE.md:25-27` does, and only for upgraders. This is round 1's S-14, still open, and it converges with UX-8 and UX-1: the editor sees `[ NOT SIGNED IN ]` with no explanation anywhere, a green tray with three `OK`s, and nothing ever downloads. From the admin's side the machine never reports, so it looks never-installed.

**Fix.** Add the tray `Sign in…` step to `START_HERE` §3 and `EDITOR_SETUP` §3.5 as a mandatory step distinct from the browser login, and have the bootstrap print it in the "Remaining manual steps" block at `:1092-1101`.

## High

### INST-5 — The wizard reports **DONE** for a bootstrap that installed neither rclone nor Syncthing

`onboard.py:499-505`; `windows_bootstrap.ps1:350`, `:466`, `:477`, `:749`.

`windows_bootstrap.ps1` `exit 1`s in exactly one place (`:292` — no winget *and* no Tailscale, unreachable for editors since `onboard.py`'s Tailscale page gates Next). Every other failure is `Write-Warn2` and carry on: no Syncthing download URL (`:466`), no `rclone.exe` in the zip (`:350`), unknown `$syncthingPath` (`:749`, the S-3 guard). All exit 0, and `onboard.py` branches only on `exit_code != 0`.

**Concrete trigger.** GitHub's API is rate-limited (60/hr/IP — the script's own comment) *and* the redirect sniff fails behind a captive portal. The editor gets no Syncthing (lane C dead), device ID "(not found automatically)", a green DONE page, and a machine that will never sync audio/AE/subs. **The clean-slate step has already deleted the previous working install.**

**Fix.** Scan `output` for `WARNING:` and surface a "completed with N warnings — do not tell the admin you're ready yet" state; better, accumulate a failure count in the bootstrap and exit non-zero on any hard-capability miss.

### INST-6 — macOS editors cannot get a companion at all

`build_editor_package.ps1:174-188`; `macos_bootstrap.sh:41`, `:419-420`; `installer/README.md:216-221`; `companion/dist/` contains only `ccsync-companion.exe`.

The package ships `macos_bootstrap.sh` and `START_HERE.md:27` says *"or you're on a Mac, follow the manual steps below."* The mac script expects `$HOME/Applications/CCSyncCompanion.app`, which **nothing builds, nothing ships, and no doc explains how to produce**. `installer/README.md:216-221` still calls the `.app` bundle a *"placeholder assumption"*.

**Concrete trigger.** A Mac editor runs the script, gets `WARNING: companion app not found at … -- skipping autostart registration`, and ends with rclone.conf plus a Syncthing daemon and **no** sync lanes, no popup fixer, no dashboard reporting, no project selection — while the script prints "Bootstrap complete" and a device ID, so they believe they are set up.

**Fix.** Either build and ship a `.app` (plus notarization or a documented `xattr -dr com.apple.quarantine`, which is absent everywhere in the tree), or make macOS explicitly unsupported in START_HERE/EDITOR_SETUP and have `macos_bootstrap.sh` say so at the top rather than half-configuring a machine.

### INST-7 — macOS: `rclone_path = "rclone"` is unresolvable in a LaunchAgent's PATH

`macos_bootstrap.sh:523`; `rclone_lane.py:99-103`. The seeded config writes `rclone_path = "rclone"` and `rclone_available()` does `shutil.which()` for a non-absolute path. A LaunchAgent-spawned process gets launchd's default `PATH=/usr/bin:/bin:/usr/sbin:/sbin` — neither `/opt/homebrew/bin` nor `$HOME/.local/ccsync/bin` is in it, and the script never exports either. Lanes A/B report "rclone not found on PATH" forever on every Mac; it works only if the editor launches the app from a Terminal that happens to have brew's PATH. **Fix:** write the resolved absolute path (`rclone_path = "$RCLONE_BIN"`).

### INST-8 — macOS: a failed Syncthing install writes a permanently broken LaunchAgent that no later run can repair

`macos_bootstrap.sh:296-344` (guard at `:315`), `:307`, `:330`. With `set -u` but no `set -e`, a failed brew/curl/unzip leaves `SYNCTHING_BIN=""`. `:307` runs `"" generate` (error, ignored); `:321-341` then writes the plist with `<string></string>` as `ProgramArguments[0]`. Because `:315` is `if [ -f "$SYNCTHING_PLIST" ]; then skip`, **every subsequent run — including one after the editor installs Syncthing by hand — prints `SKIP: Syncthing LaunchAgent already present` and never fixes it.** Same trap for the companion plist (`:422`). This is round 1's S-12, untouched. **Fix:** don't write the plist when `-z "$SYNCTHING_BIN"`, and make the guard compare the plist's embedded program path against `$SYNCTHING_BIN`, rewriting + `launchctl bootout`/`bootstrap` on mismatch.

### INST-9 — `START_HERE.md` tells the editor to put the companion in the project tree

`START_HERE.md:109-118`: *"Copy `ccsync-companion.exe` somewhere permanent (e.g. into your `Creators_Club` folder) and run it."* This is the exact layout `windows_bootstrap.ps1:61-69` documents as the historical bug (*"left machines with copies in two places and an autostart entry racing the subst logon task at boot"*), and it is one of the paths `steps.build_cleanup_plan` reaches into and deletes (`steps.py:552-561`). Line 118 (*"Re-run the setup script after copying it and it'll add the app to auto-start"*) is also wrong: `:967-969` only ever looks at `$CompanionExePath`. **Fix:** rewrite §3 to `%LOCALAPPDATA%\ccsync\bin\`, or tell them to pass `-CompanionExeSource`.

### INST-10 — `docs/SERVER.md`'s onboarding flow omits the step without which onboarding is impossible, and contradicts itself

`docs/SERVER.md:7-41` vs `:234-239` and `:254-257`; `server/README.md:25-26`; `setup_editor_account.py:262-266`.

1. **"Set a known password" is missing.** `setup_editor_account.py:266` creates the account with `"random_password": True` and never prints or sets a knowable password. The entire editor install gate (`onboard.exe` → `/api/v1/verify` → SMB probe) requires that password. It *is* documented — 200 lines later, under "Gotcha" — but not in the numbered sequence, not in the script's output, and not in `server/README.md`. The admin follows steps 1-7 and tells the editor to go; the wizard's sign-in rejects them with no clue why, and there is no way past it. (Round 1's S-13.)
2. **Step 5 tells the admin to do what `:254` forbids.** `:29-36` instructs `accept_device.py … --folder-id …` per project; `:254-257` says *"**Workflow change:** do not use `accept_device.py` to share folders anymore — enforcement would revert any hand-made share for a mapped editor within a minute."* `server/README.md:25-26` has the same stale instruction, and `windows_bootstrap.ps1:1088-1089` + `macos_bootstrap.sh:583-584` still print *"…so they can approve it with server/accept_device.py for each project you're working on."*

### INST-11 — Re-running `onboard.exe` can wipe a working `dashboard_token`

`onboard.py:346` → `steps.py:780`. `self.report_token = result.get("report_token") or ""`, then `forced["dashboard_token"] = _toml_string(dashboard_token)` — and `merge_config_text` *replaces* the existing line. Any verify response without `report_token` (older dashboard, a field rename) silently rewrites a good token to `""`. The editor re-runs the installer to fix something unrelated; afterwards the companion posts with no token, the dashboard rejects every report, the fleet grid shows them offline, the sequencer gets no selection, nothing syncs — and the wizard says DONE. **Fix:** skip the key when `report_token` is empty.

### INST-12 — `write_marker.py` silently reassigns a project's immutable identity

`write_marker.py:42`, `:47-51`; `common.py:143-156`. `--slug` is accepted verbatim with no charset validation and no read-back of the existing marker. The tool exists *because* the slug must be preserved, but it will overwrite a marker carrying slug `X` with slug `Y`, and will write a slug containing spaces/`/`/uppercase that can never be a valid Syncthing folder ID (which is also DASH-M17's injection vector). The admin repairs a moved project and mistypes or omits `--slug`; `slugify(rel)` produces the *new* path-derived slug; the dashboard sees an unknown project, creates a new folder, and the old slug's ticks, `project_roots`, completion history and media rows are all orphaned — **the never-delete invariant broken for state rather than files, with no output line saying anything changed.** **Fix:** read the existing marker first, print `old → new`, require `--force` to change it, and validate against `^[a-z0-9-]+$`.

### INST-13 — `setup_tree.py` will mark a *container* directory as a project, hiding every real project under it

`setup_tree.py:106-121`. `project_path_rel` validates segments but nothing checks depth, ancestor markers, or descendant markers. Since discovery *prunes at markers*, `setup_tree.py --project-rel-path 2026/CCT` writes `.ccsync-project` at the container level — an easy slip given the arbitrary-depth flag. Within one provision cycle the container becomes one "project" and every real project beneath it is invisible to discovery and to `/project-setup`; their selections stop being enforceable. Nothing is deleted, but every editor's ticked project vanishes from the dashboard. This is DASH-M8's CLI twin. **Fix:** `test -e` for `.ccsync-project` in any ancestor under `Projects/` or any descendant, and refuse with an explanation.

## Medium

- **INST-14 — the bootstrap adds `BinDir` to the *registry* PATH but not `$env:Path`** (`windows_bootstrap.ps1:361-376`, `:1007`), yet launches the companion as a child of that process with a config saying `rclone_path = "rclone"`. From install until the next logon, lanes A/B report `rclone not found on PATH` and the tray is red on a machine that is actually fine. **Fix:** `$env:Path = "$env:Path;$BinDir"` before section 9.
- **INST-15 — the bootstrap tears down `P:` with no "is it ours" guard** (`:547-548`), an incomplete fix of round 1's D-8: `windows_uninstall.ps1:120-130` and `steps.build_cleanup_plan:597` both got the guard, the bootstrap didn't. Running it where `P:` is a real NAS mapping (the base rig, or an editor who ignored the drive-letter warning) destroys that mapping and replaces it with a loopback share of a local folder — **every `P:\Projects\…` path in the Resolve DB now resolves to a nearly-empty local tree.**
- **INST-16 — `Get-SyncthingDeviceId` swallows its own output via a fatal `2>&1`** (`:1035`, `:1044`) — [measured] Under `$ErrorActionPreference = "Stop"`, `<native> 2>&1 | Out-String` throws `NativeCommandError` on the *first* stderr line (un-redirected stderr is harmless — also verified). One stderr line from `syncthing generate` aborts the assignment; the legacy fallback uses the identical construct and dies the same way. The editor gets "could not determine the Syncthing device ID" and `onboard.py`'s Finish page can't hand the admin the value it says is mandatory.
- **INST-17 — a corrected `-EditorName`/`-TailnetHost` never reaches `rclone.conf` on a re-run** (`windows_bootstrap.ps1:816-826`; `macos_bootstrap.sh:393-408`). Both skip the whole stanza if `[creators_club_sftp]` exists, without comparing `host`/`user`. The single most likely reason to re-run is a typo'd editor name — which the script warns loudly about at `:241` — and that re-run is a silent no-op for the one file carrying the username.
- **INST-18 — `Stop-Process -Force` on Explorer, from a possibly-elevated session** (`:716-719`). Kills every Explorer in reach (all sessions when elevated — other logged-in users lose their shell and it is never restarted), force-closes any in-progress Explorer copy (see §1's truncated-file note), and re-parents the shell at High integrity. All for a cosmetic drive label.
- **INST-19 — no timeouts or progress suppression on the two big downloads** (`:345`, `:472`). No `-TimeoutSec`, no `-UseBasicParsing`, no `$ProgressPreference = 'SilentlyContinue'` — while the URL-*resolution* calls at `:400`/`:414` do pass `-TimeoutSec 30`. PS 5.1's progress rendering costs an order of magnitude on multi-MB downloads, and a half-open TCP connection hangs until the wizard's 1800 s timeout kills the install. Neither zip's hash is verified.
- **INST-20 — cleanup kills the editor's *other* Syncthing and never brings it back** (`steps.py:591`, `:634-635`). `kill_process_names` includes `syncthing`, force-killed for both roles. An editor with their own Syncthing — normal for this population — has it stopped, our instance started with our home, and theirs never restarted.
- **INST-21 — `onboard.exe` never validates `local_root`** (`onboard.py:379`, `:428`, `:443`; `steps.py:790`). Free text, forced into `config.toml` and passed as `-LocalRoot`. `P:\Creators_Club` — plausible, since the docs talk about `P:` constantly — means cleanup unmounts `P:` and then `Ensure-Dir` fails on a nonexistent drive under `EAP=Stop`. **Fix:** validate absolute + drive-letter + drive-exists + not-`P:` + no trailing whitespace before enabling BEGIN INSTALL.
- **INST-22 — `ensure_ssh_key` ignores `ssh-keygen`'s result** (`steps.py:232-249`; `onboard.py:466-468`). No `check`, no returncode inspection, then `return pub_path` unconditionally. Missing OpenSSH client → the editor can only hit RETRY forever. Existing private key + missing `.pub` → `ssh-keygen -f <existing>` prompts "Overwrite (y/n)?" against closed stdin, aborts, and the Finish page shows "(no SSH public key found)" while still saying DONE — so the editor sends the admin one of the two required values and lanes A/B never authenticate. **Fix:** check the returncode; regenerate the `.pub` with `ssh-keygen -y -f` rather than overwriting.
- **INST-23 — `powershell` invoked without `-NoProfile` / `-NonInteractive`** (`steps.py:360-368`), inside a captured-stdin subprocess. A user profile script that prompts, errors, or sets `Set-StrictMode` alters or hangs the install, and the failure appears as an unrelated bootstrap error. `_quiet_run`'s inline PowerShell at `:637-642` does pass `-NoProfile`.
- **INST-24 — `install_syncthing_app.py` reports success for an app-create job it never waited on** (`:192-206`). `POST /app` returns a job id; `ok(resp)` only means accepted. `common.wait_for_job` exists for this and `install_dashboard_app.py:296-304` uses it for DELETE. Separately, the docstring's `ASSUMED_APP_CREATE_PAYLOAD` (`:23-58`, *"the single place to edit"*) bears no resemblance to the payload actually sent (`:162-190`) — an admin debugging a 422 edits the wrong thing.
- **INST-25 — `DASH_SESSION_SECRET` is required by the code and absent from every doc** (`install_dashboard_app.py:30-35`, `:216`; `SERVER.md:189-193`, `:216`; `server/README.md:45-51`). `require_env` makes it a hard failure, but the script's own env docstring, the runbook's copy-paste install command, and the README env table list only the other three. It appears once, at `SERVER.md:240`, inside a paragraph about login. `SERVER.md:216` reminds you to pass `DASH_REPORT_TOKEN` on `--recreate` but not this one — and re-creating with a fresh secret logs every editor out, which that same line warns about for the other token.
- **INST-26 — `server/README.md` claims none of these scripts has ever been run against the NAS** (`:8-13`, `:96-105`, `:186-187`). False in the current tree: `setup_editor_account.py:22`, `install_syncthing_app.py:158-161`, `install_dashboard_app.py:246-255` all record live confirmation. The README also still calls `install_syncthing_app.py` *"the riskiest script here"*. The admin either distrusts working tooling or assumes the rest of the doc is equally stale. `install_dashboard_app.py` and `write_marker.py` are missing entirely from the run order and the per-script list.
- **INST-27 — `docs/SERVER.md`'s "Operational notes" describe the pre-marker, pre-selection dashboard** (`:206-211`). Three stale claims in one bullet: `/projects` described as *"mounted read-only"* (the compose mount is `:rw`, and `:72-76` of the same doc says so); provisioning described as triggered by any `<year>/<series>/<project>` dir (markers-only at any depth per `:54-64`); folders described as *"creates + shares … to every configured editor device"* and *"never modifies existing folders"* (contradicted by `:257` and by the documented retarget PATCH). An admin reading this will not understand why a newly created folder syncs to nobody. Round 1's X-6, still open — `SPEC.md:73` carries the same read-only claim.
- **INST-28 — the packaged `EDITOR_SETUP.md` gives paths that don't exist in the package** (`:45`, `:55`, `:39`, `:249`; copied flat by `build_editor_package.ps1:181`). The doc says `-File installer\windows_bootstrap.ps1` and links `../SPEC.md`, so the editor's first command fails with "The argument … does not exist." (`START_HERE.md` gets this right.) Also internally contradictory: `:16-17` says fill in `projects` and `active_project`; `:113-114` says *"You do not need to list projects."*
- **INST-29 — `installer/README.md`'s package contents and parameter table have drifted.** Contents lists 6 files; `build_editor_package.ps1:174-188` copies 10 — missing `onboard.exe` (now the primary path), `FIRST_UPGRADE.md`, `windows_upgrade.ps1`, `windows_uninstall.ps1`. The parameter table omits `-CompanionExeSource`, `-DashboardUrl` and `-DashboardToken`; the last is the difference between a reporting install and a silently unmanaged one, and START_HERE's step-2 command doesn't pass it either.
- **INST-31 — round 1's D-7 fix covers one of its three named triggers** (`install_dashboard_app.py:256-283`). The staged-file-count check closes the partial-SFTP hole, but the sequence is still `find <app> -mindepth 1 -delete && cp -a …`, so a **`cp -a` failure** (full dataset, I/O error) still leaves `/app` gutted with only a `FAILED to install code` line. The count check is also file-count only: a partial transfer that wrote all files but truncated the last passes verification. See also DEL-9 for the unvalidated `--host-root`.

## Round-1 security carry-overs, still present verbatim

- **SEC-8** — `setup_tree.py:67`, `:78`, `write_marker.py:49`: `{rel}`/`{base}`/`{owner}` still interpolated raw inside double-quoted `echo` in a **root-run** remote script. `project_path` rejects only `/` and `\`, so `--project 'A$(id)'` still substitutes on the NAS.
- **SEC-9** — `setup_editor_account.py:152`: `{home!r}` still used as shell quoting, while `shell_quote` sits in the same import list.
- **SEC-14** — `macos_bootstrap.sh:481-533`: `cat > ~/.ccsync/config.toml` under the default umask, so the fleet `dashboard_token` is world-readable. One line: `chmod 700` the dir, `chmod 600` the file.
- **SEC-2 / SEC-3** — `install_dashboard_app.py:89-91` still ships `TRUENAS_PW` into the container env (readable via `docker inspect`), and `common.py:220` / `install_dashboard_app.py:148` still use `paramiko.AutoAddPolicy()` while sending that password. `common.py:224` additionally puts the password on the remote command line (`export SUDO_PW=…`), visible in `ps` to any local NAS account.
- **§9 slug collisions** — `setup_syncthing_folder.py:85`: `2026/CCT/Season 1`, `Season-1` and `Season_1` still collapse to one id, and the "already exists, skipping create" branch never compares paths.
- **§9 `_clean_slate` has no rollback** — `onboard.py:424-432`. Now the single largest amplifier of INST-1/2/5: **every failure after this point leaves the machine strictly worse than before a "safe to re-run" installer was started.**
- **§9 requirements floors** — `server/requirements.txt:1-4` unpinned, for scripts that run as root against the NAS.

## Installers — low

- `windows_upgrade.ps1:139-166`, `:181` — new keys appended at EOF. Harmless for installer-written configs, but any hand-added `[section]` swallows the appended `mode`/`dashboard_url`/`dashboard_token`, which then read as `section.mode` and are silently ignored.
- `windows_upgrade.ps1:190` — `Start-Process $CompanionExePath` under `EAP=Stop` with no guard: where the copy failed 5× and no prior exe exists, the script dies before printing the summary that would have explained why.
- `windows_uninstall.ps1:120` — `Test-Path "P:\"` is false for a mapped-but-dead drive, so a stale mapping survives the uninstall.
- `windows_uninstall.ps1` — never removes `%LOCALAPPDATA%\ccsync\bin` from the user PATH that `bootstrap:373` added, and `:162-173` deletes the whole `MountPoints2\##localhost#CCSync_P` key recursively rather than just `_LabelFromReg`.
- `build_editor_package.ps1:292-293` — `& git … 2>$null` is the PowerShell-level native redirection that becomes a fatal `NativeCommandError` under `EAP=Stop` (measured); inside a `try`, so the only symptom is a silently missing provenance line.
- `build_editor_package.ps1:312-320` — `Select-String` is case-insensitive and `$m.Matches[0]` on a multi-match result is ambiguous; a second `version = "…"` line in `pyproject.toml` could make the drift check compare the wrong pair.
- `build_onboard.spec:8-9` — docstring says `dist/onboard/onboard.exe (one-folder build)`; there is no `COLLECT` and it produces `dist/onboard.exe`. `upx=True` on an unsigned onefile exe is also the classic SmartScreen/AV false-positive shape for a binary a remote editor must download and run (same note as `build.spec:88`).
- `steps.py:783-793` — the base-rig branch never forces `remote_root`, so a base config keeps `remote_root = ""` and `validate_config` logs a sync-stopping error on every start of a machine that legitimately has no remote. Conversely `:793` now force-overwrites a *customised* `remote_root` on every re-run (§7 new-defect 10).
- `server/check_health.py` — no check of the dashboard itself (`GET /api/v1/health`), despite it now gating login, selection, provisioning and the upgrade channel; "the whole server side" no longer means what it says.
- `setup_editor_account.py:202` — `--name` is neither lowercased nor validated, while both bootstrap scripts lowercase aggressively and warn about exactly this asymmetry. `--name JSmith` creates a unix account no editor's rclone.conf will ever match.
- `accept_device.py:37` — `--device-id` accepted with no shape validation; a truncated paste surfaces only as a Syncthing 400.

## §6.1 Installers — verified clean

All four `.ps1` files tokenize clean; no `&&`/`||`, ternary, `??` or `?.` anywhere; every here-string delimiter is at column 0; `#requires -Version 5.1` on all four. **S-2's write side is fixed** — both writers use `[IO.File]::WriteAllText` with `UTF8Encoding $false`, byte-verified (`101,100,105…` vs the old `Set-Content -Encoding UTF8`'s `239,187,191…`), `AppendAllText` inserts no BOM, and `config.load_config` reads `utf-8-sig`. **S-3 is fixed** — `$syncthingPath` is re-probed after winget and both consumers are hard-guarded. **S-1 is fixed** — `forced["remote_root"]` in `ensure_config`'s editor branch. **§9 non-ASCII shims fixed** — `Write-ShimFile` writes OEM for `.cmd` and ANSI for `.vbs` with a round-trip check (verified: OEM CP 850 and ANSI CP 1252 differ on this box, `José` round-trips, CJK warns loudly). **§9 upgrade copy fixed** — 5× retry, steps 3-5 always run. **§9 bootstrap timeout fixed** — 1800 s, reported as a normal failed install. **§9 `Add-Content`/`New-Item -Force` fixed.** **D-9 / SEC-10 / SEC-11 fixed** — base-rig `local_root` excluded from cleanup candidates, compose binds explicit IPs, staging is `mktemp -d` with a prefix assertion.

**Config-key contract:** every key the two bootstrap scripts and `ensure_config` write exists in `config.DEFAULTS` with the same type; TOML backslash escaping is correct on both platforms (`C:\\Creators_Club`; the bash heredoc's `"P:\\\\"` correctly emits `\\`); `remote = "creators_club_sftp"` matches both the rclone stanza and the companion default. No blank-value-shadowing-a-default cases beyond INST-11.

**Idempotency:** `Ensure-Dir`, the rclone-stanza and companion-config guards, `find_folder`/`find_user`/`find_group` skips, `setup_tree`'s per-dir `test -d`, `syncthing generate` re-run safety, and `execute_cleanup`'s tolerate-everything design all re-run cleanly. **Nothing under `local_root`, `~/.ccsync`, `syncthing-config`, `~/.ssh`, or the NAS media tree is deleted by any script in scope**; `-Full` is opt-in and correctly documented.

**Interactive-hang review:** no `Read-Host`/`Get-Credential` on any editor path (the only `Read-Host` is admin-invoked with `-Publish`); every destructive cmdlet passes `-Confirm:$false`; native-command stderr redirection is correctly pushed *inside* `cmd /c` at `bootstrap:547-548`, `:626` and `uninstall:138-139`. **`common.shell_quote` is used correctly everywhere paths are passed** (including the nested `sudo sh -c` in `build_marker_write_cmd`); only the `echo` message strings are unquoted (SEC-8). **`--dry-run` genuinely opens no connection** in all seven server scripts.

---

# §7. Round-1 fix verification

Every `AUDIT.md` finding was classified against the current tree.

| Status | Count |
|---|---|
| **FIXED** (verified individually) | 44 |
| **PARTIAL** | 9 |
| **REGRESSION** | 3 |
| **NOT FIXED** | ~55 |
| **DEFERRED (declared in the commit message)** | 6 |
| **STALE** | 1 |
| **New defects introduced by the fix diffs** | 12 |

The commit's claim — *"all listed were confirmed real … all green"* — holds for test-suite state. But **three of the four Tier-1 data-loss / silent-failure fixes do not hold in production, and one of them is nullified by a sibling of a bug the same commit claims to have fixed.**

## The three regressions

| # | Regression | Anchor | Detail |
|---|---|---|---|
| 1 | Lane `start()` liveness guard converts a thread *leak* into permanent lane *death* | `rclone_lane.py:444`, `syncthing_lane.py:213` | §5 L-2 — reproduced live; the new test asserts the broken state |
| 2 | `windows_upgrade.ps1` now reads UTF-8 as ANSI, corrupting config on every upgrade | `windows_upgrade.ps1:137` | §6 INST-3 — measured; the BOM that previously masked this was removed by the S-2 fix |
| 3 | The mapping-health warning became unreachable | `paths.py:99` | §5 L-15 — `BAD_PREFIX` now fires only when the file *exists* under a wrongly-targeted mount |

## The nine partial fixes

| Round-1 id | Status | What's missing |
|---|---|---|
| **D-1** | **WRONG in production** | The guard reads `_default_run`'s output, and that call never got the S-6 encoding fix → empty stderr → `deletes=0` → lane B proceeds. **§1 DEL-0, reproduced live.** |
| **D-2** | PARTIAL | `reconcile_with_nas` aborts on a `None` subpath, but `app.py:489` still runs lane A with it — whole-tree upload. **§1 CORE-C2.** No test covers `consolidate_project()` with a blank `active_project` at all. |
| **D-7** | PARTIAL | Staged file-count check added; a `cp -a` failure still guts `/app`, the check is count-only (a truncated last file passes), and `--host-root` is unvalidated. **§6 INST-31, §1 DEL-9.** |
| **S-2** | PARTIAL + REGRESSION | Write side genuinely fixed and byte-verified. Read side is now wrong. **§6 INST-3.** |
| **S-6** | PARTIAL | `rclone_lane.py` fully fixed. Missed: `consolidate.py:144` (the D-1 nullifier) and `onboarding/steps.py:189, 247, 375, 628` — `:375` captures the bootstrap's echo of `$CCRoot`/`$EditorName`/`$SyncthingHome`, so a `C:\Users\José` profile raises `UnicodeDecodeError` out of the worker thread **after `_clean_slate()` has removed the working install.** |
| **S-7** | PARTIAL | `DEFAULT_TOML_TEXT` fixed and tested. Twin missed: `config.example.toml:148` still has a bare `sync_enabled = true` (**§2 CORE-M5**). And the fix relies on the *template* changing, so `mode = "base"` stays dead forever on every config written by installer ≤1.0.2. |
| **SEC-5** | PARTIAL (proved) | Mismatched identity rejected; the header isn't *required*. Proved against the real app — a shared-token holder with no identity header wrote as another editor, wiping their `editor_media` rows and rollups and injecting `state=error, last_error="FAKE: your NAS is broken"`, all with a 200. **§2 DASH-H9.** `test_auth.py:198-208` asserts the vulnerable behaviour as correct. |
| **SEC-10** | PARTIAL by design | `0.0.0.0` → two explicit binds in both compose and installer (round 1 wanted both). But it is **LAN + tailnet**, not tailnet-only, so the unauthenticated `/api/v1/verify` credential oracle stays exposed to the whole studio LAN — which was SEC-10's substance. The comment says so, so treat it as accepted risk, not closed. |
| **§7 migration** | PARTIAL | `user_version` committed after each step closes the seven-step window; it is **not inside that step's transaction**, because `executescript` autocommits the DDL before the PRAGMA runs. A restart in that gap still yields `duplicate column name` on next boot. **§2 DASH-H8, measured.** |
| **§4 `CREATE_NO_WINDOW`** | PARTIAL | Three of four rclone spawn sites got it; `consolidate.py:144` didn't, so Consolidate still flashes two console windows from the windowed build. Fixed by the same one-line change as DEL-0. |

## Verified genuinely fixed (44)

**Data loss:** D-3 (`os.rename` + parent mkdir; test proves `2026/`, `Projects/` and `local_root` all survive), D-4 (`_item_is_valid` in both twins), D-5 (tmp + `os.replace` + `unlink(missing_ok)`; but see §1 CORE-H5, DEL-7), D-6 (`commonpath` on normcased resolved paths, cross-drive `ValueError` handled; but see §1 CORE-H1), D-8 (`Get-PSDrive`/`DisplayRoot` leaves a real NAS mapping alone), D-9.

**Silent failure:** S-1, S-3, **S-4 / S-5 (verified empirically, both lanes, both filter sides — see §5.1)**, S-8 (`quote(editor_name, safe="")`), S-9 (`john.doe` round-trips both token kinds), S-10 (but see §2 CORE-H2), S-11, S-15.

**Security:** SEC-1 (`v2.<purpose>.…` split; verified both directions), SEC-4 (`lanes` 32 / `transfers` 256 caps, `LANE_LABELS` whitelist, `lane_report_current` pruned; but see §2 DASH-H6), SEC-11, SEC-12, SEC-13 (the verifier — but see §2 DASH-H7 for the two handlers that regressed), C-1 (`/app:ro`, `chown root:root`, and `run.sh` no longer needs write access or PyPI).

**§4-§11:** lane-C indefinite pause (join-then-unpause + `_in_lane_c_turn` + stop re-checks inside the sweep — the sweep race is sound; the remaining leak is §5 L-4's, via a long lane A/B run); leading `/` in subpath, applied to all three consumers; `accept_folder` creates paused → ignores → unpause (but see §5 L-3, whose caller breaks it); `popup_snooze_seconds` everywhere; `config.py` invalid escape; reporter `_last_heavy_at` on attempt; `ReplaceClip` de-duped by `id()`; consolidate dry run drops `--verbose` and caps `objects` (safe — verified the `stats` record and all `Skipped …` lines are NOTICE-level, so `--stats-log-level NOTICE` still delivers them); `_validate_tree_part` control chars; managed `_stop_lanes` stops lane A; `toggle_pause` delegates correctly; collector `_incomplete` rebuilt per cycle + per-pair try/except; collector loop body wrapped; four blocking handlers threadpooled; X-3, X-5's `build_editors_view` half, X-7; §9 ASCII shims, `AppendAllText`, registry guard, upgrade copy retry, bootstrap timeout.

## Stale (1)

`ui.py:124` `_safe_next` open redirect (a SEC-15 row) — round 1's own §11 "explicitly checked and clean" section supersedes it, since `RedirectResponse` percent-encodes `\`. Correctly left alone.

## New defects introduced by the fix commit

Beyond the three regressions above, nine more that round 1 never covered:

1. **`.ccsync-tmp` bypasses every `.stignore`** — the D-5 temp name is `A001.braw.ccsync-tmp` and all three generators match only `(?i)*<ext>` and `Proxy`, so lane C indexes and pushes a growing 40 GB copy. **§1 CORE-H5.** Fix in all three twins.
2. **`parse_dry_run_stats` misclassifies directory removals** — `consolidate.py:122` splits on `"delete" in msg.lower()`, but rclone emits `"Skipped remove directory as --dry-run is set"`, which lands in the "would upload/download" list. Harmless to the guard (which uses the stats counters) but the sample list shown to a human is wrong, contradicting the docstring's claim that deletions are never hidden among uploads. Match `"remove directory"` too.
3. **One unknown lane name now 422s the entire report** — `LaneReportIn._known_lane` rejects at the model level, so all three valid lanes are lost with it, and `test_report_rejects_unknown_lane_name` asserts `COUNT(*) == 0`. Round 1's §8 explicitly recorded that pydantic's `extra="ignore"` made new-companion→old-dashboard skew safe; this breaks that property. **Any future 4th lane makes every companion shipping it go completely dark against an un-upgraded dashboard**, logging one WARNING then DEBUG forever. Filter unknown lanes out of the list instead of rejecting the payload.
4. **False comment in `config.py:311-313`** — *"the root logger buffers records emitted before setup_logging() configures handlers, so this is never lost."* Python does not buffer; `logging.lastResort` writes to `sys.stderr`, which is `None` in the windowed build, so the `load_config` ERROR *is* dropped. The outcome is only OK because `run()` re-surfaces it via `validate_config`. Delete or correct the claim before someone relies on it.
5. **`_slug_for_rel`'s label lookup is unconstrained** — `api.py:1523`: `SELECT slug FROM projects WHERE label = ?` with no `active=1`, no `ORDER BY`, no uniqueness constraint on `label`. Two projects sharing a label, or a deactivated one, yields an arbitrary slug. It also inherits `collector._run_config`'s `folder.get("label") or slug`, so X-3 recurs for exactly the hand-created folders DASH-M4 is about.
6. **Two hardcoded IPs in the container's port bindings** — `compose.yaml:45-46` and `install_dashboard_app.py:59-60` pin `192.168.0.102` and `100.71.216.3`. A NAS DHCP change or tailnet IP rotation makes Docker fail with `cannot assign requested address` and the app never starts — **a hard outage where the previous `0.0.0.0` was merely over-exposed.** Make them settings with these as defaults.
7. **`ensure_config` now force-overwrites a customised `remote_root`** — `steps.py:793` puts it in the *forced* dict, so any admin who pointed an editor at a different pool path has it silently reset on every `onboard.exe` re-run. It is also a third copy of that path (with `windows_bootstrap.ps1:99` and `config.py`), with no test asserting they agree.
8. **`dashboard/deploy/requirements.txt` duplicates `pyproject.toml` deps with no drift guard.** They match today. Add a dependency to `pyproject.toml` only and the container boots then fails at import — and `run.sh`'s hash stamp means it won't even re-run pip. A one-line parity test would be cheap; `test_packages.py` already does work of this kind.
9. **`fix_clip` with a blank `local_root`** — reachable precisely when S-1/S-2 have blanked the config. **§1 CORE-H1**, measured.

**Tests added that assert the wrong thing:** `test_start_is_noop_when_periodic_thread_still_alive` (asserts the latched `_stop_event`, i.e. regression 1); `test_report_marks_machine_verified_with_identity` (asserts 200 + `verified: False` for an unauthenticated identity header, i.e. the open half of SEC-5).

**Cheap tests that were not written:** no mixed-case integration test anywhere for S-4/S-5 (the fixture tree is entirely lowercase; only `"--ignore-case" in cmd` is asserted); no test for `consolidate_project()` with a blank `active_project` (D-2's live path); no test that `consolidate._default_run` survives non-ASCII output (D-1's nullifier).

## Not fixed — the long tail

**Installer/server:** S-12, S-13, S-14, SEC-7, SEC-8, SEC-9, SEC-14, §9 slug collisions, §9 `_clean_slate` rollback, §9 requirements floors. **SEC-15 table:** all rows open — confirmed `api.py:1376` is still `token != settings.report_token` with no `compare_digest`.

**Companion §4/§5:** `sequencer.py:568` per-tick selection fetch; `popup.py:453-458` console fallback still doesn't call `perform_ignore_all` and doesn't `destroy()` the root; `upgrade.py`'s `.old` race and `_rollback`; the popup on the watcher thread; identity expiry; `tray.py:406` `_ccsync_stop`; `_warned_mapping` / `_popup_snooze` unbounded; **`config_problems` still written at `app.py:993` and read nowhere — notable because `config.py:313`'s new docstring claims it is what makes a config load error visible.**

**Companion §6:** `fixer.list_destination_dirs` prefix; `popup.py`'s `editor_name=""`; the synchronous unbounded `os.walk` on the Tk thread; `manifest.py` base-rig scan and `stop()`; `resolve_bridge` lock and logger; `get_project_roots` silent degradation; no reporter payload ceiling.

**Dashboard §7/§11:** retention dies with the collector; the write transaction across network I/O; `collector.py:239` `set_ignores` create-only (the dashboard twin of the `accept_folder` window that *was* fixed); `projects/link` full walk; `add_selection` SELECT-then-INSERT; `fetch_project` missing `active=1`; queue N+1; inventory keyed on `label`; mtime-only signature; backoff replaces the interval; unquoted REST path segments; TrueNAS `verify=False`, bare `resp.json()`, `if not warnings` home-perm gate, account hijack; no `healthcheck:`; unpinned base image; no CSRF token; "TICK FOR ME" swapping `closest main`.

**§8 cross-cutting:** X-4 (and now inverted — §1 CORE-C1), X-6, X-8, X-9, X-10.

**§10 bench:** all deferred, correctly flagged in the commit message. See §4.4 — the deferral means no existing benchmark number is usable.

---


# §8. Suggested fix order

Ordered by (blast radius × likelihood), not by severity label alone.

## Tier 0 — the four one-line changes to make today

Each is a single line or a single config key, and each closes a path that destroys data or permanently disables sync with no user error required.

| # | Change | Anchor | Why |
|---|---|---|---|
| 1 | Add `encoding="utf-8", errors="replace"` (and `creationflags`) | `consolidate.py:144` | **DEL-0.** Round 1's flagship delete guard currently reads nothing and reports zero deletions while lane B deletes proxies. Reproduced live. Also closes the last `CREATE_NO_WINDOW` gap. |
| 2 | Add `"versioning": {"type": "staggered", …}` | `syncthing_admin.py:129-141` | **DEL-6.** Converts every deletion in this document from permanent to recoverable on the editor side. Highest safety-per-character in the codebase. |
| 3 | Skip dot-directories in the mkdir loop | `rclone_lane.py:200-205` | **DEL-1.** Today the companion actively re-arms a fleet-wide delete by recreating `.stfolder`. |
| 4 | `Get-Content … -Encoding UTF8` | `windows_upgrade.ps1:137`, `:204` | **INST-3.** Every upgrade run currently corrupts non-ASCII config values, silently and permanently. |

## Tier 1 — before the next sync pass runs anywhere

Can destroy irreplaceable media. Several need no user error at all.

| # | Finding | Why |
|---|---|---|
| 5 | **DEL-2** `--backup-dir` on lane B + atomic filter write (+ `--max-delete`) | Makes the one destructive verb in the routine path recoverable, and closes the empty-filter cross-process race |
| 6 | **CORE-C1** make the identity role monotonic | A tray sign-in on the base rig points a deleting `rclone sync` at the live NAS share. Fix the code **and** the test that blesses it |
| 7 | **CORE-C2** gate Consolidate's lane A on `subpath is not None` | The dialog says it refuses; the upload proceeds whole-tree |
| 8 | **DEL-3** actually stop syncing on config errors | Turns a typo'd `remote_root` from "deletes every proxy" into "reports a config problem" |
| 9 | **DASH-H1 + L-3 + P6** verify/repair `.stignore` every cycle, both sides; don't unpause a folder whose ignores failed | One dropped HTTP request currently puts camera originals under Syncthing's delete propagation *and* costs terabytes of hashing. Three auditors reached this from three directions |
| 10 | **DEL-4 / DASH-H2 / DASH-H3** guard retarget + marker self-heal on content plausibility | A partially-copied server-side move propagates mass deletion — and SPEC instructs the host to do exactly that operation |
| 11 | **DEL-5 / L-8** re-point Syncthing only on a successful move | Chains with DEL-1 to produce an empty-but-valid folder |
| 12 | **CORE-H5** `.ccsync-tmp` in all three `.stignore` generators + startup sweep | A killed FIX ALL fans a 12 GB partial file out to the whole fleet |
| 13 | **L-7** validate `rel_path` segments in both twins | Moves a project directory outside `local_root`; the `fixer.py` equivalent was graded HIGH in round 1 |

## Tier 2 — silent total failure

Sync stops or state corrupts while everything reports healthy.

**L-1** (two live sequencer threads after one sign-out/sign-in) and **L-2** (lane permanently dead after one Pause→Resume — a regression, with a test asserting it) come first: both are reproduced, both are triggered by an ordinary tray action, and both leave the tray green.

Then: **L-6 / UX-3** (lane C reports `idle`+`last_sync=now` unconditionally — the lane carrying all audio/GFX/AE/subs), **DASH-H4** (a zero-row seed unshares every editor fleet-wide), **DASH-H5** (write transaction across network I/O → 500s on every report), **DASH-H8** (migration crash-loop), **CORE-H2** (invisible startup death), **CORE-H6/H7** (no working exe, no rollback), **CORE-H4** (unserialized Resolve API segfault), **CORE-H3** (FIX ALL reports success for media that never uploads), **DASH-H7** (event-loop stall), **L-4** (unbounded project processing starves lane C for hours), **INST-4** (a manual install never syncs at all), **INST-1/2** (a `P:` mapping that looks installed and isn't), **INST-5** (DONE for an install with no rclone and no Syncthing), **DEL-7 / CORE-M1** (the media-corruption TOCTOU pair), **L-15** (mapping-health warning unreachable — regression).

## Tier 3 — performance, cheapest first

**Measure before changing anything** — §4.5 step 1 is five minutes and may explain the entire 60 mb/s ceiling by itself.

1. **P3 / P14** — check whether lane C is relaying and whether Tailscale is direct. If either is wrong, no rclone flag matters yet. Then pin tailnet addresses and disable relays/global discovery, and add both signals to the report payload (C-6).
2. **P1** — `--sftp-chunk-size 255Ki`. One flag, up to 8× on large-file uploads at WAN RTT.
3. **P2** — `--sftp-disable-hashcheck` or `--ignore-checksum`. Read the integrity trade-off in the table first; this is the one tuning change with a real cost.
4. **P7 / C-1** — run lanes A and B concurrently and stop pausing Syncthing folders. Up to 50% of pass wall clock, and lane C latency from ~50 minutes to seconds.
5. **P9 / C-2** — express lane A via `--files-from` on watchdog events. Time-to-first-byte from "up to an hour" to ~40 s.
6. **P10-P13** — the redundant-work set: conditional structure clone, cached rclone probe, selection TTL, inventory and completion intervals.
7. **§4.4** — fix the bench criticals and the `sftp_chunk_size` unit before trusting any measurement, and stop handicapping SMB (C-4). Nothing currently in `results/` should be used to pick anything.

## Tier 4 — UX, in this order

**UX-1/2/11** (make the tray tell the truth — everything else is downstream of a status display that cannot express failure), **UX-8 + INST-4 docs** (the tray sign-in step, in both editor docs), **UX-13** (the wording pass, starting with `Consolidate` and `START_HERE.md:115`'s move-vs-copy contradiction), **UX-5** (the offline-clip explainer), **UX-19** (Copy diagnostics for Alex). Rationale in §3.2.

## Tier 5 — security

**DASH-H6** (unbounded report body), **DASH-H9** (report spoofing — proved), **CORE-M10** (unpinned upgrade origin: an altered report response installs an arbitrary exe *plus* its matching hash), **DASH-M12** (guest-session auth bypass), **DASH-M13** (SMB probe threadpool exhaustion), **SEC-8/SEC-9** (shell injection into root-run remote scripts), **DASH-M16 / SEC-2 / SEC-3** (`verify=False` and the admin password in the container env and on the remote command line), **SEC-14** (world-readable `dashboard_token` on macOS), **DASH-M15** (account hijack), **DASH-M17 / INST-12** (unvalidated slugs → unencoded REST paths), **DASH-M18** (inconsistent scoping).

## Tier 6 — documentation, before the next editor is onboarded

Cheap, and currently the difference between a working and a silently-broken install: **INST-4/UX-8** (sign-in step), **UX-13**'s `START_HERE.md:115` (which will get an editor's original footage deleted by their own hand), **INST-9** (don't put the exe in the project tree), **INST-10** (the missing "set a known password" step and the `accept_device.py` self-contradiction), **UX-21 / INST-27/28/29** (whole-tree-replication claims that are two architectures out of date, packaged paths that don't exist, and drifted parameter tables).

## Tier 7 — everything else, roughly in severity order.

## A standing rule for Tier 3

**No speed change may widen a deletion window.** Where the two conflict, the no-deletion requirement wins. Concretely: don't drop `--ignore-existing` to fix truncated uploads (fix the stability gate instead), don't collapse lane B into one whole-tree `rclone sync` (a filter bug then deletes across projects the editor never ticked), and *report* orphan `.partial` files rather than deleting them.

---

# Appendix: limits of this audit

- **Coverage:** all tracked files. Eight auditors, scoped disjointly. Round-1 findings verified fixed are recorded in §1.2, §2.1, §5.1-5.2, §6.1 and §7 rather than repeated.
- **Read-only:** no source file was modified. `AUDIT_2.md` is the only file created.
- **Reproduced live** (not merely reasoned): the D-1 delete-guard bypass end to end, with real rclone, a CJK filename, and two proxies actually deleted while the dialog reported zero (DEL-0); two concurrent sequencer threads after one sign-out/sign-in (L-1); a permanently dead lane after one Pause→Resume (L-2); the SEC-5 cross-editor report spoof against the real app, wiping another editor's media rows (DASH-H9).
- **Measured** (a real command was run and its output pasted): rclone `lsf --dirs-only -R` listing dot-directories, and lane-B delete scoping with and without a filter (DEL-1, DEL-2, L-13); the full mixed-case filter matrix on both lanes (§5.1); `--sftp-chunk-size`, hash-check, and `--no-traverse` behaviour against the bundled v1.74.4 (§4 P1, P2, P10); `--min-age` versus a mid-write copy (L-14); PowerShell 5.1 byte-level encoding round trips and `2>&1` NativeCommandError behaviour (INST-2, INST-3, INST-16); `subst` argument splitting on a spaced path (INST-2); `fix_clip` with a blank `local_root` (CORE-H1); `setup_logging` failure modes (CORE-H2); SQLite `executescript` partial-migration replay (DASH-H8); `config.py` numeric validation gaps (CORE-M4); path-traversal destinations from a `..`-bearing rel (L-7); and all five test suites.
- **Not exercised:** no runtime test against a real Resolve instance, a real TrueNAS, a real Syncthing pair, or a real editor machine. The remaining concurrency findings (Resolve bridge re-entrancy, the collector transaction, the DEL-2 cross-process filter-file race) are reasoned from the code and not reproduced under load — treat the mechanism as reliable and the probability as an estimate. The §4 throughput numbers are analytic given RTT and a measured window size; §4.5 step 2 converts them into a measurement.
- **The test suites are green** (536 + 160 + 74 + 24 + 40) and **five** tests are named here as passing while asserting the wrong behaviour. Green does not mean Tier 0 and Tier 1 are theoretical — the Tier 0 item at the top was reproduced deleting real files.
- **Where several auditors found the same defect from different sides**, all anchors are kept — they usually need separate fixes. The clearest case is the missing `.stignore` reassertion, found independently as a deletion path (DASH-H1), a lane-direction violation (L-3), and a throughput sink (P6).
