# resolve-remote-sync — Full Repository Audit

**Commit audited:** `a5e1a7a` (branch `main`)
**Date:** 2026-07-25
**Scope:** entire repository (~31.6k lines) — `companion/`, `dashboard/`, `server/`, `installer/`, `onboarding/`, `bench/`
**Method:** eight parallel read-only auditors, one per subsystem plus one cross-cutting contract auditor. No files were modified. Findings that could be checked empirically were checked (marked **[verified]**).

---

## How to use this document

This is a work queue, not a narrative. Every finding has:
- a precise `file:line` anchor,
- a **concrete failure scenario** (inputs/state → wrong outcome),
- a suggested fix.

Findings are grouped by subsystem. Severity is the auditor's, spot-checked by the orchestrator. Nothing here has been fixed — the repository is exactly as audited.

**Start at §12 (Suggested fix order)** for a prioritised queue, then read the referenced findings in full. Sections §1–§3 cut across subsystems (data loss, silent failure, security); §4–§11 are per-subsystem; the Appendix records what was verified how.

Roughly 130 findings: 11 critical, ~30 high, the remainder medium/low.

**Section map**

| § | Area |
|---|---|
| 1 | Data-loss and destructive actions (9) |
| 2 | Silent total failure (15) |
| 3 | Security (14 + hardening table) |
| 4 | companion — sync lanes |
| 5 | companion — core runtime |
| 6 | companion — project logic, Resolve bridge, reporting |
| 7 | dashboard — backend |
| 8 | Cross-cutting contract drift |
| 9 | installer / onboarding / server scripts |
| 10 | bench — measurement validity |
| 11 | dashboard — collector, clients, templates, deploy |
| 12 | **Suggested fix order** |

---

## Baseline: the test suite is green and proves less than it appears to

All suites pass at the audited commit, using each subsystem's own `.venv`:

| Suite | Result |
|---|---|
| `companion` | 472 passed |
| `dashboard` | 134 passed |
| `bench` | 56 passed |
| `onboarding` | 69 passed |
| `server` | 24 passed |
| **Total** | **755 passed, 0 failed** |

A recurring theme below: **several of the most severe bugs are covered by a passing test that asserts the wrong thing**, or that uses an input a real install never produces. Specific instances are called out inline (e.g. `test_config.py:225`, `test_watcher.py:77`, `test_build_up_command_subpath_no_double_slash_with_trailing_slash_root`). Treat "there is a test for it" as no evidence at all for the items below.

### Environment note (not a bug)

With the *system* Python rather than the project venvs, `companion/tests/test_tray.py` fails to collect (no `pystray`) and 9 dashboard test modules fail to collect (no `fastapi`). This is a local environment artifact, not a repo defect — the venvs have the right dependencies.

---

## Uncommitted work in the tree

The working tree at audit time is **not** clean:

```
 M dashboard/src/ccsync_dashboard/api.py     (+19)
 M dashboard/tests/test_project_setup.py     (+18)
?? rcta/                                     (untracked scratch: src/, dst/, filter.txt)
```

The `api.py` change adds a server-side `IGNORED_RESOLVE_PROJECTS = {"untitled project", "new doc"}` filter applied to `resolve_project` and to `media_tree` in `api_report`. This **partially mitigates** finding **X-7** below, but only for those two hardcoded names — it does not honour a user's configured `ignored_resolve_projects`, and the companion-side gap it compensates for is still open.

---

# §1. Data-loss and destructive-action findings

These can destroy an editor's media, an editor's project tree, or the shared NAS tree. They are first regardless of subsystem.

### D-1 — `consolidate.py:95-96, 179-192` — "Consolidate" previews a destructive sync but only counts transfers, never deletions — **CRITICAL**

`_dry_run_command(DIRECTION_DOWN, …)` builds `build_down_command`, i.e. **`rclone sync remote → local`** (`rclone_lane.py:240`), which *deletes* local files matching the proxy filter that don't exist on the NAS. `parse_dry_run_stats` reads only `stats["totalTransfers"]` and `stats["totalBytes"]` — never `deletes` / `deletedDirs`. **[verified: confirmed by reading `parse_dry_run_stats`, `consolidate.py:88-101` — no deletes key is read.]**

**Failure scenario:** An editor onboards a pre-existing project containing locally-generated proxies the NAS has never seen. The consent dialog reports "0 proxy file(s) will download from the NAS" and reassures them "Originals are COPIED, never moved — your scattered files stay put". They accept; `app.py:481` runs the real `_lane_b.run_once(subpath)`, and their entire local proxy library is deleted. Onboarding a pre-existing project is *precisely* the case where this is guaranteed to bite.

**Fix:** Parse and surface rclone's `deletes` counter (and the `Skipped delete as --dry-run is set` object lines already landing in `objects`) in `build_report`; refuse or skip the lane-B leg when deletions are non-zero.

---

### D-2 — `consolidate.py:131-140` (trigger `app.py:438`) — a blank `active_project` silently widens Consolidate from one project to the whole tree — **CRITICAL**

```python
subpath = project_prefix.strip("/").replace("\\", "/") or None
```

`project_prefix` comes from `cfg["active_project"]`, which **ships blank** (`config.py:51`) and which `validate_config` only *warns* about (`config.py:378-380`).

**Failure scenario:** On any machine with a blank `active_project` whose open Resolve project has no server root mapping, "Consolidate pre-existing project…" calls `reconcile_with_nas(cfg, None, …)`, then `_lane_a.run_once(None)` — uploading the entire local tree — and `_lane_b.run_once(None)` — a whole-tree `rclone sync` down that deletes every local `Proxy/` file absent from the NAS, **across all projects**, not just the one being onboarded. Combined with D-1, the dialog under-reports both halves.

**Fix:** Make a `None` subpath a hard abort in `consolidate_project()` rather than a whole-tree fallback.

---

### D-3 — `repath.py:45` — the default `move_fn = os.renames` can delete `local_root` itself — **HIGH**

`os.renames` documents that it "prunes away directories corresponding to the rightmost path segments of the old name" via `os.removedirs`.

**Failure scenario:** A one-project editor's project moves from `Projects/2026/Season 1` → `Projects/2026/CCT/Season 1`. After the rename, `os.renames` removes the now-empty `2026`, then `Projects`, then `C:\Creators_Club` — **the `subst P:` target** — leaving every `P:\…` path in the Resolve database dead. The existing test escapes this only because its chosen new path happens to keep `2026` non-empty.

**Fix:** Use `shutil.move` / `os.rename` with an explicit `dst.parent.mkdir(parents=True)`.

---

### D-4 — `sequencer.py:387` + `repath.py:66` — a null `rel_path` moves the editor's project directory to `…\Projects\None` — **HIGH**

`str(item.get("rel_path", ""))` yields the literal string `"None"` when the dashboard sends `rel_path: null`. `dashboard/…/db.py:637` `fetch_selections` LEFT-JOINs `projects`, so a selection row whose project row is absent yields `label = NULL` → `api.py:525` emits `"rel_path": None`. The sequencer also never checks the `active` flag.

**Failure scenario:** `expected = local_root/Projects/None` ≠ actual → pause → `os.renames(real_project_dir, …\Projects\None)` → `set_folder_path` re-points Syncthing at the bogus path. Compounds with D-3.

**Fix:** Skip selection items whose `rel_path` is falsy or non-str (and whose `active` is False) in both `_process_project` and `ProjectRepather.reconcile`.

---

### D-5 — `fixer.py:276-281` — a failed copy leaves a truncated media file that lane A then uploads and can never replace — **HIGH**

`copy_fn(src, dest_path)` inside `try/except OSError` returns `{"ok": False, "copied_to": None}` **without unlinking the partial `dest_path`**.

**Failure scenario:** Disk-full or an SMB drop halfway through a 40 GB BRAW leaves a truncated original inside the project folder. Because `shutil.copy2`'s `copystat` never ran, its mtime is the failure time, so lane A's `--min-age 30s` guard expires 30 s later and rclone uploads the truncated file. Lane A uses `--ignore-existing` (`rclone_lane.py:218`), so **the good copy can never replace it on the NAS**. Neither `popup._fix_done` nor `consolidate.run_consolidation` can clean up a file they were told doesn't exist.

**Fix:** Copy to a temp name and `os.replace()` on success; unlink the temp in the failure path.

---

### D-6 — `fixer.py:275` — `fix_clip` never checks the destination stays under `local_root` — **HIGH**

`Path(local_root) / dest_rel.replace("/", os.sep)` — pathlib discards the left side when the right is absolute, and re-roots when it starts with a separator. **[verified by the auditor:]** `PureWindowsPath(r"T:\Creators_Club") / r"C:\Windows\Temp"` → `C:\Windows\Temp`; `/ r"\Escaped\Dir"` → `T:\Escaped\Dir`; `/ r"..\..\Elsewhere"` is not collapsed.

**Failure scenario:** The dest field is an *editable* `ttk.Combobox` (`popup.py:290`; `fixer.py:8` says "free text is allowed"). An editor pastes an absolute path; their media is copied outside the tree, Resolve is relinked to it, and the popup reports "Fixed: copied to … and relinked" — silently recreating the exact out-of-tree condition the popup exists to eliminate. A `\`-leading `active_project` or server `rel_path` reaches the same line.

**Fix:** Resolve the joined path and reject it unless `os.path.commonpath` places it under `local_root`.

---

### D-7 — `install_dashboard_app.py:218-232` — root-level `find … -delete` before the copy, with no backup — **HIGH**

`find <app_dir> -mindepth 1 -delete` runs as root *before* `cp -a` from the staging dir.

**Failure scenario:** If `cp -a` fails (staging incomplete from a partial SFTP, disk full, staging removed by a concurrent/aborted run), the live bind-mounted `/app` is left empty. The running container keeps serving from memory and the dashboard dies at the next restart, recoverable only by re-running the deploy.

**Fix:** Copy into `app.new` and swap only after the copy exits 0.

---

### D-8 — `windows_uninstall.ps1:113-124` — the uninstaller unmaps `P:` on the base rig, killing real NAS mappings — **MEDIUM**

Unconditionally runs `subst P: /D` **and** `net use P: /delete /y`, with no notion of editor vs base rig. `onboarding/steps.py:561` deliberately guards this (`unmount_p=(role == "editor")`) because on the base rig `P:`/`T:` are real SMB mappings of the NAS.

**Failure scenario:** Running the uninstaller on the base rig deletes the persistent NAS mapping, so every `P:\Projects\…` path stored in the Resolve project database goes offline until remapped by hand.

**Fix:** Add a `-Role` / `-KeepDriveMapping` switch, or detect a `net use` mapping and refuse to delete one the installer did not create.

---

### D-9 — `onboarding/steps.py:515-519` — a base-rig install treats the NAS share as a cleanup candidate — **LOW**

For `role == "base"`, `local_root` (`T:\Creators_Club`, an SMB mapping of the NAS) is added to `candidate_dirs`, contradicting the invariant stated at `:522-524`.

**Failure scenario:** A base-rig install deletes `ccsync-companion.exe` / `.old` / `.new.exe` from the shared NAS tree root. Blast radius is three fixed filenames — bounded, but it is a delete on shared storage the code claims never to touch.

**Fix:** Skip `local_root` as a cleanup candidate when `role == "base"`.

---

# §2. Silent total-failure findings

Nothing crashes, nothing logs usefully, and the system simply does not do its job. These are the hardest to diagnose in the field and several affect *every* install.

### S-1 — `onboard.py:471` vs `windows_bootstrap.ps1:710` — **every `onboard.exe`-installed editor gets a blank `remote_root`** — **CRITICAL** **[verified]**

`_clean_slate` → `_write_config_and_identity` (`onboard.py:471`) writes `~/.ccsync/config.toml` **before** `run_bootstrap()` at `:488`. The bootstrap's config-seeding branch then hits `Write-Skip "companion config already exists"` (`windows_bootstrap.ps1:711`) and never applies its `-RemoteRoot` default `/mnt/tank/TheCreatorsPool/Creators_Club` (`:99`).

`steps.ensure_config()` (`steps.py:719-760`) forces `editor_name`, `dashboard_url`, `dashboard_token`, `mode`, `local_root`, `canonical_prefix`, `remote` — **but not `remote_root`**, whose default is `""` (`config.py:47`, and `config.py:176` in `DEFAULT_TOML_TEXT`).

**[Verified by the orchestrator:** the forced dict at `steps.py:740-754` contains no `remote_root`; `config.py:47` is `"remote_root": ""`; the bootstrap skip at `:710` is unconditional on file existence.**]**

**Failure scenario:** `validate_config` classifies a blank `remote_root` as a sync-stopping error (`config.py:357-364`) but **only logs it** — lanes A/B still run. rclone therefore targets `remote:` bare, i.e. the editor's **SFTP home directory**, silently uploading originals to `/mnt/tank/TheCreatorsPool/homes/<editor>/` instead of the project tree.

**Fix:** Add `"remote_root": _toml_string(remote_root or DEFAULT_REMOTE_ROOT)` to `ensure_config`'s editor `forced` dict. Separately, make a sync-stopping validation error actually stop the lanes.

---

### S-2 — `windows_bootstrap.ps1:775` and `windows_upgrade.ps1:144` — PowerShell writes a UTF-8 **BOM**; `tomllib` rejects it; the companion silently falls back to defaults — **CRITICAL** **[verified by two auditors independently]**

PS 5.1 `Set-Content -Encoding UTF8` emits `EF BB BF` even when overwriting a BOM-less file. `ccsync_companion.config.load_config` reads the file in binary via `tomllib.load`, which raises `TOMLDecodeError: Invalid statement (at line 1, column 1)` on a BOM — and `load_config` **catches it and returns `merged = dict(DEFAULTS)` with no log line at all**.

The codebase already knows this hazard: `identity.py:71` reads with `utf-8-sig`, explicitly citing "PowerShell Set-Content… the installer" prepending a BOM.

**Failure scenario:** An editor runs `windows_upgrade.ps1` (which rewrites the whole file to add `dashboard_url` / `mode`). After relaunch the companion has `local_root=""`, `remote_root=""`, `editor_name=""`, `dashboard_token=""` — nothing syncs, nothing reports — while `~/.ccsync/config.toml` looks perfectly correct to a human, and the upgrade printed "config updated". The standalone bootstrap (the documented repair path in `installer/README.md`) produces the same result on a fresh machine.

**Fix (both halves):** read with `encoding="utf-8-sig"` + `tomllib.loads()`, **and** write with `[System.IO.File]::WriteAllText($path, $text, (New-Object System.Text.UTF8Encoding $false))` in both scripts.

---

### S-3 — `windows_bootstrap.ps1:612` (root cause `:416-427`) — `& $null` aborts the installer at step 6 after the clean slate — **CRITICAL** **[verified]**

After a **successful winget install** of Syncthing, `$syncthingPath` is never assigned — only the direct-zip branch at `:451` sets it. `& $syncthingPath generate` therefore executes `& $null`.

**[Verified by the orchestrator:** the winget branch sets `$installed = $true` but leaves `$syncthingPath` unset; `:612` uses it unguarded. The auditor separately confirmed `& $null <arg>` throws a terminating `RuntimeException`.**]**

**Failure scenario:** With `$ErrorActionPreference = "Stop"` and no try/catch, the script aborts at step 6, so steps 7–10 (rclone.conf stanza, seeded companion config, companion install/autostart/launch, device-ID print) never run and PowerShell exits non-zero. `onboarding/steps.py:355` reports this as a failed install — *after* `_clean_slate` has already deleted the previous working installation. The same hole opens when both Syncthing URL lookups fail (`:434-436`). macOS gets this right (`macos_bootstrap.sh:226`).

**Fix:** Set `$syncthingPath` in the winget branch (re-probe `Get-Command` / `$env:ProgramFiles\Syncthing\syncthing.exe`) and hard-guard steps 6 and 10.

---

### S-4 — `rclone_lane.py:60` — lane A's video filters are **case-sensitive**, so uppercase camera extensions never leave the editor's machine — **CRITICAL** **[verified]**

`VIDEO_EXTS` is entirely lowercase (`rclone_lane.py:43-46`) and the rules are `+ *{ext}` — rclone filters are case-sensitive by default. Meanwhile `syncthing_admin.py:45` writes the lane C ignore as `(?i)*.mov` — case-**in**sensitive.

**[Verified live by the auditor** against the repo's own `companion/.tools/rclone.exe` v1.74.4: with the exact `build_filter_rules_up()` rule set, `Sub/CLIP.MOV` is silently dropped while `Sub/clip2.mov` transfers. **Verified by the orchestrator:** `VIDEO_EXTS` at `:43-46` is all-lowercase.**]**

**Failure scenario:** A Sony/Canon/GoPro `.MOV` / `.MP4` / `.MXF` / `.MTS` original is excluded from lane A *and* from lane C. It never leaves the editor's machine, and **no lane reports an error**.

**Fix:** Append `--ignore-case` to `build_up_command` / `build_down_command` (the auditor verified `CLIP.MOV` then transfers), or emit both `+ *{ext}` and `+ *{ext.upper()}`.

---

### S-5 — `rclone_lane.py:59, 67-72` — a lowercase `proxy/` directory **inverts both lanes** — **HIGH** **[verified live]**

The `Proxy` directory rules are case-sensitive in both directions.

**[Verified live by the auditor:** with a `Sub/proxy/` dir, lane A's filters **uploaded both proxy files to the NAS as originals** (`- **/Proxy/**` didn't match) while lane B's filters pulled **nothing** (`+ **/Proxy/` didn't match).**]**

**Failure scenario:** The NAS is case-sensitive ZFS and macOS editors are in scope, so this is reachable. It burns HiNet upstream bandwidth and **permanently pollutes the NAS**, since per SPEC lane A never deletes.

**Fix:** The same `--ignore-case`, which also aligns both rule sets with the `(?i)Proxy` stignore.

---

### S-6 — `rclone_lane.py:532, 535-538, 544` — one non-ASCII filename **deadlocks the lane forever** — **CRITICAL** **[verified on this machine]**

`Popen(cmd, stderr=subprocess.PIPE, text=True)` decodes with the ANSI codepage and `errors='strict'`. rclone logs UTF-8.

**[Verified by the orchestrator on this rig:** `locale.getpreferredencoding(False)` → `cp1252`; piping `"台北.mov".encode("utf-8")` through a `text=True` stderr pipe raises `UnicodeDecodeError: 'charmap' codec can't decode byte 0x8f in position 1`.**]**

**Failure scenario:** The exception fires inside `_reader`, which has **no try/except**. The reader thread dies; nobody drains the pipe; rclone blocks on write once the 64 KB pipe buffer fills; `proc.wait()` at `:544` never returns — **while `_run_lock` is held**, so the whole sequencer stalls permanently on that project. Given the Taiwanese-Mandarin production context, non-ASCII filenames are expected, not exotic.

Same bug, milder, at `rclone_lane.py:120`: `_run_lsf` raises, so `clone_directory_tree` silently returns `None` and structure cloning never works for trees with non-ASCII directory names.

**Fix:** Pass `encoding="utf-8", errors="replace"` to `Popen`/`subprocess.run`, and wrap `_reader`'s loop in try/except.

---

### S-7 — `config.py:307` + `:146` — the `mode = "base"` role profile is **dead** for any config written from the companion's own template — **HIGH** **[verified]**

```python
MODE_PROFILES = {"editor": {}, "base": {"sync_enabled": False}}
...
for key, value in profile.items():
    if not isinstance(data, dict) or key not in data:
        merged[key] = value
```

The profile applies only when the key is **absent** from the file — but `DEFAULT_TOML_TEXT`, written verbatim by `ensure_config_exists` (`config.py:283`), contains an explicit `sync_enabled = true`.

**[Verified by the orchestrator:** `MODE_PROFILES["base"] = {"sync_enabled": False}` at `config.py:146`; the template contains a literal `sync_enabled = true`. `test_config.py:225` passes only because it writes a bare one-line file that a real install never has.**]**

**Failure scenario:** An admin sets `mode = "base"` in a real first-run config and gets `sync_enabled=True` — the base rig starts full rclone lanes and mirrors the entire NAS tree onto itself.

*Note:* the live config on this workstation was **not** written from that template (it lacks the key), so this rig is currently unaffected — but any install seeded from `DEFAULT_TOML_TEXT` is.

**Fix:** Comment out the profile-controlled keys in `DEFAULT_TOML_TEXT`, or track "explicitly set" separately from "present in the template".

---

### S-8 — `selection.py:80` — an editor name with a space or non-ASCII character permanently breaks all syncing — **HIGH**

The editor name is interpolated into the selection URL without `quote()`. `project_setup.py:135` gets this right with `quote(name, safe='')`; `selection.py` does not.

**[Verified by the auditor** against `http.client`: `"…/selection/alex chen"` raises `InvalidURL: URL can't contain control characters`; a CJK name raises `UnicodeEncodeError: 'ascii' codec can't encode`.**]**

**Failure scenario:** `config.py:154` documents `editor_name` as a free-text "name/handle", so a space is entirely plausible. `fetch()` catches the error, logs one WARNING then DEBUG forever, returns `None`; `get()` falls back to a cache that was never written and returns `(None, "none")`; the sequencer parks on `STATE_NO_SELECTION` and **nothing ever syncs**.

**Fix:** `urllib.parse.quote(self.editor_name, safe="")`.

---

### S-9 — `auth.py:115` — any username containing a dot can log in but can **never** hold a session — **HIGH** **[verified]**

`make_session_cookie` builds `v1.<user>.<exp>.<sig>`; `read_session_cookie` does `cookie.split(".")` and requires exactly 4 parts. The username regex explicitly permits dots (`db.py:203`, `truenas_client.py:31`: `^[a-z][a-z0-9._-]{0,31}$`), and `api_admin_create_user` advertises them (`api.py:1001`).

**[Verified by the orchestrator:** `read_session_cookie(S, make_session_cookie(S, "john.doe"))` → `None`.**]**

**Failure scenario:** Editor `jane.doe` gets a 200/303 + cookie from `/login`, then every subsequent request fails the middleware and bounces back to `/login` — an infinite redirect loop. Her machine is also silently forced to `verified=0` at `api.py:1391-1392`. The companion side fails worse: `identity.parse_token` (`identity.py:106-116`) reads `parts[2]="doe"`, `int()` raises, and `sign_in` returns *"dashboard returned a malformed or already-expired token"* — so with `require_login=true` **her lanes never start at all**.

**Fix:** `cookie.rsplit(".", 2)`, or base64url-encode the username in the payload. Fix `identity.parse_token` identically.

---

### S-10 — `app.py:980` — the app is constructed **before** logging is set up, so config-driven startup crashes are invisible — **HIGH** **[verified]**

```python
def run() -> None:
    cfg = config_mod.load_config()
    app = CompanionApp(cfg)     # <-- any exception here has no logging
    app.run()                   # <-- setup_logging() is the first line in here
```

**[Verified by the orchestrator:** `setup_logging(self.config)` is the first statement of `CompanionApp.run()`, and `validate_config` runs later still, at `app.py:926` — both *after* construction.**]**

**Failure scenario:** A hand-edited `poll_interval = "fast"` / `transfers = "many"` hits `float()`/`int()` at `app.py:205/250/154` and raises before logging exists. In the windowed PyInstaller build `sys.stderr` is `None`, so **the exe vanishes with no log line, no tray, no toast**. Worst case is right after a self-upgrade: the new exe dies silently and the old one has already shut down. These are exactly the values `validate_config()` exists to catch.

**Fix:** Call `setup_logging()` and `validate_config()` in module-level `run()` before constructing `CompanionApp`, and wrap the construction in a logging try/except.

---

### S-11 — `app.py:944-951` — only `ImportError` is caught around tray startup, so any other tray failure skips the entire shutdown path — **HIGH** **[verified]**

**[Verified by the orchestrator:** the `except ImportError:` at `app.py:949` sits *outside* the `try/finally` that calls `self.shutdown()`.**]**

**Failure scenario:** `pystray.Icon(...)` / `_make_icon_image` / `_build_menu` can raise `OSError` / `TclError` / PIL errors (no interactive session, Explorer's tray not up yet at login, shell restart). The exception propagates out of `run()` past the try block at `:964`, so lanes, the sequencer, the reporter and the watchdog observer are **never stopped**, and the process dies with a traceback into a `None` stderr — the same silent-death signature already chased in commit `859bf49`.

**Fix:** Catch `Exception` and continue headless.

---

### S-12 — `macos_bootstrap.sh:307, 315-344` — a failed Syncthing download writes a broken LaunchAgent that later runs **never repair** — **HIGH**

If the download failed, `SYNCTHING_BIN` is `""` (the `set -u` guard doesn't catch empty; there is no `set -e`), so the script writes a LaunchAgent whose first `ProgramArguments` string is empty — and `:315` skips rewriting the plist forever after.

**Failure scenario:** Lane C is permanently dead on that Mac. Every later, otherwise-successful re-run prints "Syncthing LaunchAgent already present" and never repairs it. Neither the editor nor the admin sees an error.

**Fix:** Bail out of the plist/daemon block when `SYNCTHING_BIN` is empty, and compare the plist's `ProgramArguments` against the current binary rather than testing only for file existence.

---

### S-13 — `setup_editor_account.py:264` — accounts created by the CLI tool of record can never authenticate — **HIGH**

New accounts are created with `"random_password": True` and the password is never set, printed, or returned.

**Failure scenario:** `server/README.md`'s run order makes this step 4, but the editor's very next step (`onboard.exe` → `POST /api/v1/verify`, and the dashboard login) authenticates by **SMB password** (`auth.py:41 _verify_smb`). An editor onboarded via this script therefore cannot get past the install gate at all. Only the dashboard path works, because it has an explicit `set_known_password` (`api.py:1010`).

**Fix:** Add a `--password` flag (or generate and print one) and call the same `user.set_password` path the dashboard uses.

---

### S-14 — `docs/EDITOR_SETUP.md:105-160` — the editor-facing doc omits the mandatory tray "Sign in…" step — **HIGH**

With `require_login = true` (the default, `config.py:85`), `start()` calls `_mark_lanes_pending_login()` and never starts lanes, and `post_once()` returns early when `editor_identity()` is `None` (`reporter.py:234-236`).

**Failure scenario:** §3.5 says lane status is reported "once a minute" once `dashboard_url`/`dashboard_token` are set, and the doc describes only the *browser* login. An editor following the script-based path verbatim (`windows_bootstrap.ps1` writes no `identity.json`) ends up with a companion that syncs nothing and is invisible on the fleet grid — the only evidence a single INFO line in `companion.log`.

**Fix:** Add a "sign in from the tray" step to §3.5, or have the bootstrap path set `require_login = false`.

---

### S-15 — `api.py:1313` vs `config.py:372-377` — a blank `editor_name` makes the dashboard 422 every report, forever, silently — **MEDIUM**

`ReportIn.editor_name` is `Field(min_length=1)`, but the companion's validator calls a blank `editor_name` a warning that leaves "syncing unaffected".

**Failure scenario:** With `require_login = false`, `editor_identity()` returns `cfg["editor_name"]` i.e. `""` (`app.py:628-630`) — which is not `None`, so `post_once` proceeds and every report is rejected 422. `_run_cycle` logs one WARNING then DEBUG forever (`reporter.py:308-313`), so the machine is simply absent from the dashboard with no visible cause.

**Fix:** Have `editor_identity()` return `None` for a blank name, and correct the warning text.

---

# §3. Security findings

The dashboard is described in SPEC.md as tailnet-only, which lowers but does not remove exposure — several of these are exploitable by any *legitimate editor* against other editors, or by anyone who reads a file off a laptop.

### SEC-1 — `auth.py:104-108` + `:132-134` — the companion's identity token **is** a 30-day dashboard session cookie — **CRITICAL** **[verified]**

`make_identity_token()` is literally `make_session_cookie(..., ttl=IDENTITY_TTL_SECONDS)` (30 days), and `get_session_user()` validates it with the same `read_session_cookie()`. The docstring states this is deliberate ("Same verifiable format as the session cookie, so read_session_cookie validates it too") — the *privilege consequence* appears unintended.

**[Verified by the orchestrator:** `read_session_cookie(S, make_identity_token(S, "alex"))` returns `"alex"` — a full authenticated session.**]**

**Failure scenario:** `POST /api/v1/verify` hands this token to anyone who can SMB-authenticate; the companion writes it in **plaintext** to `~/.ccsync/identity.json` (`identity.py:83-90`). Paste it into the `ccsync_session` cookie → authenticated as that user for 30 days, with **no re-auth and no revocation**. On the base rig the identity belongs to an admin (`api.py:483` returns `role: "base"` for `DASH_ADMIN_USERS` members), so a stolen file yields 30 days of admin: create/delete TrueNAS editor accounts, set arbitrary user passwords, publish companion executables to the entire fleet.

**Fix:** Put a purpose claim in the signed payload (`v1.session.` vs `v1.identity.`) and have `get_session_user` reject anything not signed as a session.

---

### SEC-2 — `install_dashboard_app.py:84-86` — the TrueNAS **admin password** is baked into the dashboard container's environment — **HIGH**

`TRUENAS_PW` (root-equivalent) is placed in the compose `environment`.

**Failure scenario:** It is persisted in the TrueNAS app config and readable via `docker inspect`, the Apps UI, and `/proc/<pid>/environ` inside the container. Any RCE / SSRF / path-traversal in the FastAPI app (which runs as `3000:3001`) escalates directly to full NAS admin.

**Fix:** Use a TrueNAS API key scoped to user management, mounted as a secret file rather than an env var.

---

### SEC-3 — `server/common.py:219-222` and `install_dashboard_app.py:121-124` — `paramiko.AutoAddPolicy()` with the admin password on the wire — **HIGH**

`AutoAddPolicy` + `look_for_keys=False`, then the admin password is sent as the SSH password *and* exported as `SUDO_PW`.

**Failure scenario:** No host-key pinning at all. Anyone able to ARP-spoof or DNS-spoof `192.168.0.102` on the studio LAN captures the `truenas_admin` password on the **first connection of every script**, plus root command execution on the impostor.

**Fix:** Load `~/.ssh/known_hosts`, use `RejectPolicy`, and document a one-time fingerprint pin.

---

### SEC-4 — `api.py:1291, 1318` + `db.py:834-869` — one report can permanently wedge the dashboard — **HIGH**

`LaneReportIn.name` is capped at 64 chars, but `ReportIn.lanes` has **no `max_length`**, and the PK is `(editor_username, machine, lane)`. `db.prune()` clears `completion_history`, `lane_report_history`, `missing_files`, `poll_runs`, media tables and `active_transfers` — but **never `lane_report_current`**.

**Failure scenario:** One `POST /api/v1/report` with 200k distinct lane names inserts 200k permanent rows. `db.fetch_lane_reports()` (`db.py:1153`) then does an unbounded `SELECT *` on every call — and it is called by `build_projects_view`, `build_editors_view`, `build_queue_view` and every UI page. The token needed is the shared one every editor holds (and which `/api/v1/verify` hands to anyone who can SMB-auth).

**Fix:** `Field(max_length=…)` on `lanes`/`transfers`, whitelist lane names against `LANE_LABELS`, and prune `lane_report_current` by `received_at`.

---

### SEC-5 — `api.py:1329-1344` — the report endpoint authenticates the *fleet*, not the *editor* — **MEDIUM**

Only the static shared `X-CCSync-Token` is checked; `editor_name` is taken verbatim from the body. The `X-CCSync-Identity` header proves identity but is **never required**.

**Failure scenario:** Any editor can `POST /api/v1/report` as `editor_name: "alex"`. `db.replace_active_transfers` (`db.py:998`), `db.replace_media_tree` (`:978`) and `db.replace_editor_media` (`:960`) all **delete-then-insert** by `(editor, machine)` — wiping another editor's presence data — plus flip their `machine_state.verified` to 0 and inject fake lane errors that turn their status dots red.

**Fix:** When an identity token is present, require it to match `editor_name`; reject writes for an editor whose machine has previously verified if the header is absent.

---

### SEC-6 — `api.py:474-478` — `/api/v1/verify` hands the fleet-wide token to any SMB-authenticating account — **MEDIUM**

The auth probe doesn't check group membership, so *any* TrueNAS account that can complete an SMB session setup receives the shared `report_token`.

**Failure scenario:** That token grants: reading any editor's project selection (`api.py:535-542` — the token path skips the `can_manage` check entirely), downloading published companion binaries (`:1230-1240`), and all of SEC-4/SEC-5's write powers.

**Fix:** Gate `/verify` on membership of the `editors` group and issue a per-editor report token.

---

### SEC-7 — `provision.py:77-87, 136` — an editor-writable marker file can hijack another project's Syncthing folder — **MEDIUM**

`read_marker()` accepts any non-empty string as a slug and `collector.py:228/239` feeds it straight into `build_folder_config`, `set_ignores` and `db.upsert_project`. Editors have SMB write access to the tree by construction. `api.adopt_folder` has an explicit guard for exactly this (`api.py:841-848`); the collector path does not.

**Failure scenario:** Plant a marker whose slug matches an existing project, then rename the legitimate directory so the collector's self-heal (`:183-194`) can't rewrite the original marker. The provision cycle **retargets the real project's Syncthing folder to the attacker's directory** — shares, ticks and history follow, and the real content stops syncing fleet-wide.

**Fix:** Reject markers whose slug isn't `^[a-z0-9-]{1,64}$`, and refuse to retarget onto a path whose slug was not previously registered at that rel.

---

### SEC-8 — `setup_tree.py:78, 86`; `write_marker.py:49` — shell injection into a root-run remote script — **MEDIUM**

`{base}` / `{owner}` / `{group}` are interpolated raw inside double-quoted `echo` strings in the remote shell script, while the same values are correctly `shell_quote`d elsewhere on the same lines.

**Failure scenario:** `setup_tree.py --year 2025 --series 'A$(id > /tmp/x)' --project P` executes the substitution on the NAS — `project_path` only rejects `/` and `\`. `write_marker.py:49`'s `echo "MISSING: {base}"` fires on the failure branch, which is exactly the branch a crafted path takes.

**Fix:** Route these through `shell_quote`.

---

### SEC-9 — `setup_editor_account.py:152` — `repr()` used as shell quoting — **MEDIUM**

`f'... stat -c "%a %U" {home!r}'`. Python's `repr()` switches to double quotes when the string contains a single quote and `\x`-escapes non-ASCII, producing a shell word the remote shell re-interprets (`$` / backtick expansion inside double quotes).

**Failure scenario:** A home path with either character injects, or silently mis-reads — and `verify_home_permissions` returning False is the difference between "the editor's SSH works" and a silent lane A/B failure.

**Fix:** Use the module's own `shell_quote`.

---

### SEC-10 — `install_dashboard_app.py:88` — the dashboard binds `0.0.0.0`, contradicting "tailnet-only" — **MEDIUM**

`"ports": [f"{port}:{port}"]`.

**Failure scenario:** SPEC.md describes the dashboard as tailnet-only, but this exposes the whole LAN to the unauthenticated pages, to `/api/v1/verify` (a credential oracle), and to the admin endpoints.

**Fix:** Bind explicitly to the tailnet address: `"<tailnet-ip>:8480:8480"`.

---

### SEC-11 — `install_dashboard_app.py:57` — predictable world-writable staging dir becomes root-owned executed code — **MEDIUM**

`STAGING_DIR = "/tmp/ccsync-dashboard-upload"` is fixed and predictable; its contents are later `cp -a`'d **as root** into `/app`, which the container executes (`command: ["/bin/sh", "/app/deploy/run.sh"]`).

**Failure scenario:** Any local account on the NAS pre-creates that directory mode 0777 (or as a symlink) before an admin deploy and drops files that become root-owned code in the executed app tree.

**Fix:** Use `mktemp -d` on the remote host and refuse to proceed if the staging path already exists.

---

### SEC-12 — `auth.py:36, 83-84` — unauthenticated unbounded memory growth in the login throttle — **MEDIUM**

`login_throttled()` prunes only the queried username's list and *creates* the dict entry; nothing ever evicts them (`clear_login_failures` only fires on success). `/api/v1/login` is in `_OPEN_EXACT` and accepts 64-char usernames.

**Failure scenario:** Failed logins with fresh random usernames add a permanent dict entry each. The 5/60s limit is also per-username only, so spraying one password across many accounts is entirely unthrottled.

**Fix:** Evict expired/empty entries on every call and add an IP-keyed limiter.

---

### SEC-13 — `auth.py:41-64` — blocking SMB verification stalls the whole event loop — **MEDIUM**

`_verify_smb` does a blocking TCP+SMB session setup with a 10 s timeout, called from `async def page_login_submit` (`ui.py:151`).

**Failure scenario:** Unauthenticated. When TrueNAS SMB is slow or unreachable, each `POST /login` blocks the entire uvicorn event loop for up to 10 s **serially**; a handful of concurrent posts with distinct usernames (the throttle is per-username) takes the dashboard offline for everyone, including companions' `/api/v1/report`.

**Fix:** `await run_in_threadpool(verifier, …)` and cap concurrent verifications with a semaphore.

---

### SEC-14 — `macos_bootstrap.sh:481-533` — the config containing `dashboard_token` is written world-readable — **LOW**

`cat > ~/.ccsync/config.toml` under the default umask.

**Failure scenario:** Any other local account on the Mac reads the fleet-wide report token and can post fabricated fleet status or fetch selections.

**Fix:** `chmod 600` the file and `chmod 700 ~/.ccsync`.

---

### SEC-15 — assorted lower-severity hardening

| Finding | File | Severity |
|---|---|---|
| Token comparison uses `==`, not `hmac.compare_digest` | `app.py:63,68`; `api.py:538,1236,1336` | low |
| Session cookie set without `secure=True` | `api.py:425-432` | low |
| `_safe_next` blocks `//host` but not `/\host` (open redirect) | `ui.py:124` | low |
| Containment check is a bare `startswith` after `.resolve()`; symlink escapes | `api.py:700-702` | low |
| `/api/v1/health` unauthenticated, echoes raw internal error strings | `api.py:282-292` | low |
| Missing-files endpoint not scoped by `auth.scope_for` (other editors' filenames) | `api.py:325-337` | low |
| Package publish streams unbounded body to disk on the event loop | `api.py:1129-1180` | low |
| TrueNAS REST uses `verify=False` with admin basic-auth; warning suppressed | `common.py:253-256`, `:29` | medium |
| `export SUDO_PW=<admin pw>` for the whole remote session | `common.py:224` | low |
| Admin password POSTed over plain HTTP; BSTR never zeroed | `build_editor_package.ps1:348-355` | medium |
| rclone/Syncthing downloads have no checksum or signature verification | `windows_bootstrap.ps1:322,441`; `macos_bootstrap.sh:187,279` | low |
| Predictable `/tmp/ccsync-*` download/extract paths (symlink attack) | `macos_bootstrap.sh:181-190, 269-282` | medium |
| SMB password passed as argv to `rclone obscure` / `rclone copy` | `rclone_smb.py:33-40, 55` | low |
| Folder id unvalidated; `../..` escapes the tree root | `setup_syncthing_folder.py:86` | low |

**Explicitly checked and clean** (dashboard backend): no SQL injection anywhere — every query is parameterised, and the only f-string SQL (`db.py:314, 876, 247`) interpolates generated placeholders, a literal table tuple, and an int constant. No secrets in defaults or log statements. CSRF is adequately covered by `SameSite=Lax` (there are no state-changing GET routes). Admin routes all call `_require_admin` / `_require_admin_page`.

---

# §4. companion — sync lanes

Beyond S-4, S-5, S-6 and D-3, D-4 above.

- **`sequencer.py:498` — `_wait_for_folder_sync` re-fetches the selection on every poll tick** — *medium*. `self.selection.get()` is a live HTTP fetch **plus** a `selection.json` disk write, per tick. With shipped defaults (5 s poll, 600 s rotation) that is ~120 dashboard requests and 120 cache rewrites per project per pass per editor, instead of the intended `selection_poll_interval = 60 s`. **Fix:** rate-limit the in-loop re-check.

- **`rclone_lane.py:408-412, 426-436` and `syncthing_lane.py:212-218` — every sign-out/sign-in leaks a live polling thread** — *medium*. `stop()` never joins the thread while `start()` clears `_stop_event`. Sequence: `sign_out()` sets the event; the periodic thread is mid-`run_once()` (an rclone run can take minutes); `on_signed_in()` clears the event and starts thread #2; thread #1 then evaluates `self._stop_event.wait(scan_interval)` against a *cleared* event and loops forever. **Fix:** join with timeout in `stop()`; make `start()` a no-op when a thread is alive.

- **`rclone_lane.py:531` — rclone spawned without `CREATE_NO_WINDOW` from a windowed build** — *medium*. `build.spec:91` sets `console=False`, and `upgrade.py:282-291` already applies this flag for exactly this reason. Every lane run and every `rclone_available()` probe (`:97`) flashes a black console window on the editor's desktop, several times per rotation. **Fix:** pass the same creationflags in `_run_popen`, `_run_lsf`, and `rclone_available`.

- **`sequencer.py:129,139` vs `:447-454` — lane C folders can be left paused indefinitely** — *medium*. `stop()`/`pause()` run `_unpause_all()` *before* the worker has actually stopped; if the worker is inside a long `lane_a.run_once()` it proceeds into `_lane_c_turn` afterwards and re-pauses every non-current project. Those folders stay paused until the next launch's `_startup_unpause`, so **lane C silently doesn't sync while the companion is off**. **Fix:** join first, then unpause; re-check `_stop_event` inside `_lane_c_turn`.

- **`rclone_lane.py:207` (also `:236`, `:166`) — a leading `/` in `subpath` silently discards `local_root`** — *low*. `str(Path(local_root) / subpath)`: pathlib treats a rooted component as absolute. The remote side is normalised (`_join_remote_path` strips slashes); the local side is not. Not reachable from the sequencer today (`PROJECTS_PREFIX` guarantees no leading slash) but **is** from `consolidate.py:121`. Note `test_build_up_command_subpath_no_double_slash_with_trailing_slash_root` passes exactly this input and only asserts the remote side. **Fix:** `subpath.strip("/")` before joining locally.

- **`syncthing_admin.py:128-129` — a window with no `.stignore`** — *low*. `accept_folder` POSTs the folder with `"paused": False` and only *then* calls `set_ignores`; if `set_ignores` raises, the state is permanent. A hand-provisioned or older server folder would let lane C start pulling the video/`Proxy` content lanes A/B own, duplicating the transfer. **Fix:** create paused, set ignores, then PATCH `paused: false`.

---

# §5. companion — core runtime

Beyond S-7, S-10, S-11 above.

- **`paths.py:98` — the *designed* steady state on an editor rig is classified `BAD_PREFIX`, producing a notification storm** — *high*. SPEC's lane A is upload-only, so a remote editor never has the originals locally. Resolve's `File Path` for every video clip is `P:\Projects\…\A001.braw`, which fails `_is_under(local_root)`, fails `exists`, and lands at `:98` → `watcher.py:143` fires `on_mapping_warning` → `app.py:315` raises a tray balloon **per distinct clip path**. Opening a 400-clip project produces 400 "mapping health" notifications on a perfectly healthy machine, destroying the signal for a genuinely broken `subst`. (`test_watcher.py:77` enshrines this as correct because it tests only one path.) **Fix:** return `MISSING` when the prefix resolves correctly but the file is simply not downloaded.

- **`app.py:855-859` — Pause→Resume starts disabled lanes and permanently adds a periodic thread each cycle** — *medium*. `toggle_pause` calls `lane.start()` on *every* lane, ignoring `lane_b_enabled` (`_start_lanes` at `:676` correctly skips it). On a base rig with `lane_b_enabled = false`, one Pause→Resume starts lane B and begins mirroring proxies config says must never be mirrored. Separately `RcloneLane.start()` unconditionally spawns a new `_periodic_thread` after clearing `_stop_event`, so a thread still in `wait()` sees the clear and keeps looping. **Fix:** delegate to `_stop_lanes()`/`_start_lanes()`; guard `start()` on thread liveness.

- **`popup.py:449-457` — the no-display fallback contradicts its own docstring and leaks a Tk root per retry** — *medium*. The docstring promises items are "auto-ignored so we don't spin forever re-popping the same clips", but nothing is added to `ignore_tracker`; `print()` is a no-op because `sys.stdout is None` in the windowed build. `popup_snooze_seconds` expires after 300 s and the watcher retries a failing `tk.Tk()` forever, leaking a partially-constructed root each time (`PopupDialog.__init__` assigns `self.root = tk.Tk()` at `:176` and never destroys it if a later line raises). **Fix:** call `perform_ignore_all(rows, ignore_tracker)` in the `except` branch and `destroy()` the root on failure.

- **`upgrade.py:82-88` + `app.py:922` — the `.old` cleanup races the outgoing process, so the "Update complete" toast fires on the wrong start** — *medium*. `_apply_inner` spawns the new exe (`:245`) and only then requests shutdown; the old process needs up to 1 s+ to exit. The new instance's `cleanup_old_exe()` runs while Windows still has the old image mapped → `unlink` raises `PermissionError` → caught → `just_upgraded` is `False`. The user never sees the toast, the `.old` persists, and the *next* unrelated restart shows a stale "Update complete — now running v0.4.3". A persisting `.old` also makes the next `os.replace(exe, old)` fail if still locked. **Fix:** retry the unlink briefly and derive the toast from a version marker file.

- **`app.py:333-352` — the out-of-tree popup blocks the watcher thread for its entire lifetime** — *medium*. `_show_out_of_tree_popup` runs the blocking Tk mainloop on the watcher thread (invoked from `TimelineWatcher.run`, `app.py:897`) while holding `_popup_active_lock`. While an editor leaves the popup on screen: `last_resolve_project` freezes (the dashboard keeps reporting a project that may already be closed), no further out-of-tree detection happens, `stop_event` is not observed, and `project_setup`'s prompt starves on the same lock. The snooze is also recorded at `:303-304` *before* the lock is attempted, so a batch that loses the race is suppressed for a full 300 s. **Fix:** dispatch onto its own daemon thread; record the snooze after acquiring the lock.

- **`app.py:696-705` — managed-mode `_stop_lanes()` never stops lane A** — *medium*. The watchdog observer started at `:670` keeps running after tray Sign out (`:755`), calling `sequencer.notify_change` on a stopped sequencer; a self-upgrade leaves it live in the outgoing process alongside the new instance's observer on the same tree. Asymmetric with `_start_lanes`. **Fix:** call `self._lane_a.stop()` in the managed branch.

- **`identity.py:119-130` + `app.py:618-630` — token expiry is indistinguishable from sign-out and is never re-checked** — *medium*. The moment the token expires, `editor_identity()` returns `None`, the reporter silently skips every cycle (the machine drops off the fleet grid), `_apply_identity_role()` is **not** re-run (it fires only in `__init__`/`sign_in`/`sign_out`), and the lanes keep running under the stale role while `effective_mode()` silently reverts to config `mode`. The only cue is the tray label. **Fix:** check expiry on a timer, notify, and re-gate lanes.

- **`tray.py:405-413` — the refresh loop's stop flag is never set anywhere in the repo** — *low* **[verified: `_ccsync_stop` occurs exactly once, at `tray.py:406`]**. The 5 s refresh thread outlives `icon.stop()` and keeps calling `app.lane_statuses()` (taking the sequencer lock) and assigning `icon.menu`/`icon.icon` on a stopped icon throughout shutdown and the entire self-upgrade window. **Fix:** use a `threading.Event`.

- **`upgrade.py:259-270` — `_rollback` leaks the download and only catches `OSError`** — *low*. After a spawn failure the ~20 MB `.new.exe` is left forever, and since `_replace` is an injectable callable, a non-`OSError` failure escapes `_rollback` and propagates out on a tray daemon thread, leaving the companion with **no exe at its own path**. **Fix:** unlink the aside file; catch `Exception`.

- **`watcher.py:77` / `app.py:84` — `_warned_mapping` and `_popup_snooze` grow without bound** — *low*. Combined with the `paths.py:98` finding, a long-lived companion accumulates one interned path string per clip ever seen. `_warned_mapping` also means a genuinely broken mapping is warned about exactly once per process lifetime, so a mapping that breaks later is never reported. **Fix:** evict expired entries.

- **`app.py:97,940` — `config_problems` is written and never read** — *low* **[verified: only those two occurrences]**. The comment claims it is "surfaced in the tray tooltip so a misconfigured install is visible without opening the log"; it is not. **Fix:** surface it in `tray._build_menu`.

- **`app.py:85` — `popup_snooze_seconds` is read but absent from `DEFAULTS`, the template, `config.example.toml`, and `validate_config`** — *low*. Undiscoverable, invisible to `test_config.py:78`'s parity test, and a bad value raises inside `__init__` (see S-10). **Fix:** add it to `DEFAULTS` and the validation loop.

- **`config.py:149,199` — invalid escape sequence in a non-raw string** — *low* **[verified by the orchestrator: reproduces as a `SyntaxWarning` on every test run]**. `DEFAULT_TOML_TEXT` is a plain (non-raw) triple-quoted string and line 199 contains `ccsync\syncthing-config`; `\s` is not a valid escape. Harmless today (Python leaves it literal) but scheduled to become a hard `SyntaxError`. **Fix:** make it a raw string or escape the backslash.

---

# §6. companion — project logic, Resolve bridge, reporting

Beyond D-1, D-2, D-5, D-6, S-8 above.

- **`reporter.py:300, 317` — a failing heavy post is never marked sent, so the full payload re-sends every tick forever** — *high*. `_last_heavy_at` starts at `0.0` and is updated only in `_run_cycle`'s success branch, so `light = active_tick and (now - self._last_heavy_at) < self.report_interval` is **always `False`**. If the heavy payload exceeds `timeout=5.0` — a multi-project `local_manifest` can carry `2000 × 2 × N` per-file entries (`manifest.py:35`) plus the whole `media_tree` — every socket timeout is followed by another full-size POST 5 s later, forever, with a single WARNING for the entire streak. **Fix:** update `_last_heavy_at` on *attempt*, and add a payload-size ceiling.

- **`fixer.py:217` (via `popup.py:190`) — the destination dropdown's built-in defaults are un-prefixed, filing media outside every project** — *medium*. `list_destination_dirs` seeds from `default_destination_dirs(editor_name)` without `project_prefix`, so the list offers bare `Audio/Music` / `B-roll/Stills` beside the prefixed suggestion. Picking the bare one writes to `<local_root>/Audio/Music` — not under `Projects/` — so `_project_rel_for_path` returns `None` (`rclone_lane.py:306`), the watchdog drops the event, and **no per-project `run_once(subpath)` ever covers it**. The clip is relinked, reported "Fixed", and never uploaded — exactly the orphan-path failure `suggest_destination`'s docstring warns about. Separately `popup.py:190` hardcodes `editor_name=""`, so the dropdown shows `B-roll/Editor Added/Unknown` while the suggestion shows the real name. **Fix:** pass `project_prefix` and the real editor name through.

- **`fixer.py:211-228` (from `popup.py:190`) — an unbounded `os.walk` of the whole tree runs synchronously on the Tk thread inside `PopupDialog.__init__`** — *medium*. Only directories named `proxy` are pruned; hidden dirs, AE caches and render folders are all walked into one combobox. On the base rig `local_root` is an SMB mount, so raising the popup walks the entire company media tree over the network before the window draws — and repeats for every popup. `list_project_dirs` (`popup.py:84`) adds a second full walk. **Fix:** cache a background scan (as `ManifestCache` already does) and cap depth/entries.

- **`manifest.py:72-85` — the manifest rescans the whole tree every 300 s even on base rigs** — *medium*. `ManifestCache.start()` is called from `app.py:885` regardless of mode; on a base rig `local_root` is the NAS SMB share, so this walks and `getsize`s a multi-terabyte tree over SMB every five minutes to produce rollups the base rig never uses (`include_files` is always `False` there). **Fix:** skip when `effective_mode() == "base"`; scale the interval with observed scan duration.

- **`resolve_bridge.py:117, 181, 319` — nothing serialises access to the Resolve scripting API, which three threads call concurrently** — *medium*. `connect()` re-runs `scriptapp("Resolve")` on every call with no lock. The watcher polls `get_timeline_items()` every 3 s (`watcher.py:76`), the media-tree thread calls `get_media_pool_items()` every 120 s (`app.py:543`), and tray actions call it from a third thread — all walking the same `fusionscript` C extension at once. The module's own `_pin_frozen_python3_home` docstring documents how badly this DLL fails under mismatched runtime state (0xc0000005). A segfault takes the whole companion down with no log entry. **Fix:** guard every public entry point with a module-level `threading.RLock`.

- **`selection.py:58` — the selection is fetched under the raw config name while everything else uses the verified sign-in username** — *medium* (see also X-3). `identity.py`'s docstring says the verified username "becomes this companion's identity for reporting/**selection**", and the reporter honours that via `get_editor_name=self.editor_identity` (`app.py:198`) — but `SelectionClient` is built once from `cfg` (`app.py:135`) and never updated by `sign_in()`. Sign in as anything other than the exact `editor_name` in config and the companion **reports under one identity while fetching another's tick list**; with a blank name it requests `/api/v1/selection/` → 404 → no sync forever, while the fleet grid shows the machine healthy. **Fix:** take an `editor_name_fn` and read it per fetch.

- **`selection.py:160-197` — `get_project_roots()` degrades silently from the authoritative mapping to a token-guess heuristic** — *medium*. On failure it returns `{}`; `popup.build_popup_rows:92-97` then falls through to `fixer.pick_project_prefix` → `match_project_dir`'s token overlap. During a dashboard outage the same clip gets a *different* destination than minutes earlier, so FIX ALL / consolidate copies gigabytes into whichever project the token matcher guessed, and lane A uploads it there. The user sees no indication. **Fix:** distinguish "no mapping exists" from "could not reach the dashboard", and block destination resolution in the latter case.

- **`consolidate.py:104-107` — the dry run buffers the entire `--verbose` rclone log in memory with a fixed 120 s timeout** — *low*. `_dry_run_command` inherits `--verbose` and `--use-json-log`, so rclone emits a JSON line per file; `capture_output=True` holds all of it and `parse_dry_run_stats` appends every object name to an unbounded list. On a whole-tree dry run (D-2) that is hundreds of thousands of lines, and the 120 s cap usually fires first — leaving "could not check the NAS" and a confirm dialog that still proceeds. **Fix:** drop `--verbose`, stream stderr, cap `objects`.

- **`fixer.py:284-287` — `ReplaceClip` is called once per *timeline occurrence*, not per distinct media pool item** — *low*. `popup.dedupe_out_of_tree_items:56-58` appends the item for every timeline reference sharing a path, and those references almost always share one `MediaPoolItem`. A clip cut in 50 times triggers 50 identical `ReplaceClip` calls, each forcing a re-conform. If Resolve returns `False` on a redundant relink, `fix_clip` reports "relink failed for 49/50 item(s)", the popup re-enables FIX ALL (`popup.py:351-353`), and a second click makes **another full multi-GB copy** under a `" (2)"` name. **Fix:** de-duplicate by object identity.

- **`resolve_bridge.py:111-119` — `connect()` swallows every exception and the module has no logger at all** — *low*. A wrong `RESOLVE_SCRIPT_LIB`, a missing `fusionscript.dll`, or a failed import is indistinguishable from "Resolve isn't running": same tray status, nothing in the log. Diagnosing a permanently-dead bridge on a remote editor's machine becomes impossible without remoting in — the very thing the reporter exists to avoid. **Fix:** add a module logger and `log.debug(exc_info=True)`.

- **`project_setup.py:111-117` — `_prompt_in_flight` can stick `True` for the process lifetime** — *low*. Set before `Thread.start()`, cleared only in the worker's `finally`; if `start()` raises, the once-ever new-project prompt never fires again. **Fix:** reset in an `except` around `start()`.

- **`manifest.py:141-142, 149-150` — `start()` after `stop()` is a silent no-op** — *low*. `start()` returns early when `self._thread is not None` and `stop()` never clears it, so a stop/start cycle leaves the manifest frozen at its last scan while `get()` keeps serving it as current. **Fix:** clear `self._thread = None` in `stop()`.

---

# §7. dashboard — backend

Beyond SEC-1, SEC-4 – SEC-7, SEC-12, SEC-13, S-9 above.

- **`db.py:230-248` — migration is neither idempotent nor transactional; an interrupted upgrade bricks the database** — *high*. `SCHEMA_V2` (`:187-192`), `SCHEMA_V4` (`:124`) and `SCHEMA_V6` (`:131`) contain `ALTER TABLE … ADD COLUMN`. `executescript()` issues an implicit COMMIT, so each step is durable, but `PRAGMA user_version` is written only **after all seven** succeed. **Failure scenario:** a v1 DB upgrading to v7 is restarted mid-migration — which `install_dashboard_app.py`'s `docker restart` does routinely — after V2 applied. `user_version` is still 1, so the next start re-runs `SCHEMA_V2` → `OperationalError: duplicate column name: rate_bytes_per_sec` → the lifespan handler raises → the container crash-loops, recoverable only by manual `PRAGMA user_version` surgery. **Fix:** bump `user_version` after each step, inside that step's transaction.

- **`app.py:40-42` — with `SYNCTHING_GUI_URL` unset the collector never starts, and retention stops entirely** — *medium*. `db.prune()` is only ever called from the collector (`collector.py:457-458`). `settings.py`'s own docstring calls the Syncthing URL the one optional-until-needed knob, and reports/logins keep working without it. In that configuration `completion_history`, `lane_report_history`, `poll_runs`, `active_transfers`, `editor_media`, `media_tree_clips` and `missing_files` grow forever on a NAS dataset with no ceiling. **Fix:** run a prune-only timer when the collector is disabled, or refuse to start without a retention worker.

- **`api.py:816-820` — every `POST /api/v1/projects/link` walks the entire NAS Projects tree synchronously inside the request** — *medium*. `provision.scan_project_dirs(projects_dir)` is an `os.walk` to depth 8 over a network mount, run per request by any signed-in editor, in a sync route holding a threadpool worker. Repeated calls saturate the pool and hammer the NAS. **Fix:** reuse the collector's cached scan, or check only the immediate subtree.

- **`db.py:610-620` — `add_selection` computes `MAX(position)+1` in a separate statement from the insert** — *low*. The browser and the companion can both tick for the same editor; two requests read the same max and insert two slugs at the same `position` (no uniqueness constraint), leaving the sequencer's "sync in tick order" ambiguous. **Fix:** one `INSERT … SELECT COALESCE(MAX(position),0)+1`, or `BEGIN IMMEDIATE`.

- **`api.py:300-305` / `db.py:1111-1117` — `fetch_project` has no `active=1` filter while `fetch_projects` does** — *low*. A project the collector deactivated still looks live on its own page but is absent from the list.

- **`api.py:345-348` + `db.py:1101-1108` — N+1 plus a full fleet rebuild per queue render** — *low*. `fetch_projects` issues one `fetch_project_editors` query per project, and `build_queue_view` builds the *entire* fleet view just to pick out one editor's rows — on every fleet page load and every `/partials/queue` poll. **Fix:** one JOINed query, and a scoped query for the queue.

- **`api.py:669-677` → `:700` — `_validate_tree_part` doesn't reject NUL/control characters** — *low*. `Path.resolve()` then raises `ValueError` (not `OSError`), escaping the `ProjectSetupError` handling, so `POST /api/v1/projects` with `name: "a\u0000b"` returns a 500 traceback instead of the intended 422 banner.

---

# §8. Cross-cutting contract findings

Beyond S-1, S-2, S-9, S-14, S-15 above.

- **X-3 — `api.py:1456-1461` vs `collector.py:225-231` / `write_marker.py:42` — the report handler re-derives a slug that a moved project no longer has** — *high*. `api_report` derives `local_manifest`'s slug with `provision.slugify(rel)`, but the project's real slug is the **marker's immutable slug**, which deliberately need not match its current path — `_run_provision` says so explicitly ("using THE MARKER'S slug… an adopted/moved project's slug may not match its current path", `collector.py:170-172`) and retargets label→new rel on a move (`:233-239`). **Failure scenario:** after the documented "move a project on the NAS" flow, every editor's `local_manifest` rows are written under `slugify(new_rel)` — a slug with no `projects` row — so `build_presence_view` for the real slug reports zero editors ("has 0 of N originals") on a project that is in fact fully synced. Orphan rows linger until the 14-day media prune. `media_tree` is unaffected because it resolves via `project_roots`. **Fix:** in `_slug_for_rel`, look up `SELECT slug FROM projects WHERE label=?` first, falling back to `slugify`.

- **X-4 — `api.py:483` vs `docs/SERVER.md:241-245` / `app.py:601-605` — `DASH_ADMIN_USERS` membership silently disables all sync on that person's machine** — *medium*. `/api/v1/verify` returns `"role": "base" if auth.is_admin(...)`, and `_apply_identity_role()` sets `self._sync_enabled = (role != "base")`, **overriding config**. SERVER.md documents `DASH_ADMIN_USERS` only as "csv of accounts that may manage anyone's ticks". **Failure scenario:** an admin adds a second person to `DASH_ADMIN_USERS` so they can publish packages; on that person's next sign-in their companion stops syncing entirely ("sync disabled: this machine works directly off the NAS") and nobody connects the two facts. **Fix:** split the role source from the admin list (`DASH_BASE_USERS`), or document the coupling prominently.

- **X-5 — `api.py:248` vs `upgrade.py:55-57` — the out-of-date flag is hardcoded to the Windows package** — *medium*. `build_editors_view` calls `db.get_current_package(conn, "windows")`, but companions report `platform` as `windows`/`macos`/`linux`, SPEC.md:22 has macOS editors in scope, and `_PACKAGE_PLATFORMS = {"windows", "macos"}` (`api.py:1047`). **Failure scenario:** once a macOS build is published, every Mac companion is permanently flagged `[ OUT OF DATE ]` and listed in `outdated_machines`, because its version is compared against the *Windows* current version. **Fix:** key `companion_outdated` off the machine's reported platform.

- **X-6 — `docs/SERVER.md:207-212` vs `collector.py:197-231` / `compose.yaml:47` — the auto-provisioning paragraph is wrong on four counts** — *medium*. It claims (a) the tree is "mounted **read-only** at `/projects`" — compose mounts `:rw` (`compose.yaml:47`, `install_dashboard_app.py:94`), as SPEC.md:83 requires (SPEC.md:73 carries the same stale read-only claim); (b) a folder is created "for **any** `<year>/<series>/<project>` dir that lacks one" — discovery is markers-only at any depth and bare dirs are deliberately invisible (`provision.scan_project_dirs:108-139`); (c) "creates **+ shares**" — new folders are created explicitly **unshared** (`collector.py:228`, "unshared until ticked"); (d) "It never modifies or deletes existing folders" — `_run_provision` PUTs path and label changes on retarget and label drift (`:233-247`). **Failure scenario:** an admin `mkdir`s a project folder per this doc and waits — nothing ever provisions, because no marker exists. **Fix:** rewrite the bullet.

- **X-7 — `app.py:537-571` vs `watcher.py:95-98` / `config.py:132-137` — `ignored_resolve_projects` is enforced in the watcher but not in the media-tree reporter** — *medium*. `config.py` documents ignored projects as "not reported to the dashboard", but `_refresh_media_tree_once` calls `resolve_bridge.get_media_pool_items()` directly and caches `{project_name: clips}` with no ignore check. On the server, `_slug_for_resolve_name` falls back to `db.match_project_label` (`api.py:1475-1478`): `"Untitled Project"` tokenises to `{untitled, project}` and matches any label containing "project", whereupon `replace_media_tree` **wipes and replaces that real project's bin tree** with the scratch project's clips. **Note:** the uncommitted `api.py` change adds a server-side filter for `{"untitled project", "new doc"}`, which blunts this for those two names only — a user-configured `ignored_resolve_projects` entry is still unfiltered on both sides. **Fix:** filter in `_refresh_media_tree_once` the way the watcher does.

- **X-8 — `db.py:120` vs `api.py:647,1386`** — *low*. `project_roots.source` is documented in the schema as `'auto' | 'admin'`, but `'editor'` is also written. No functional break; the comment is a false enum for anyone writing a migration.

- **X-9 — `api.py:1274` vs `rclone_lane.py:576-588`** — *low*. `TransferIn.project_slug` is accepted and stored (`active_transfers.project_slug`, `db.py:106`) but the companion never populates it, so the column is always NULL and live transfers can never be attributed to a project. **Fix:** stamp it in `_normalize_transferring`, or drop the field.

- **X-10 — `upgrade.py:51` vs `api.py:1161`** — *low*. The staging name is hardcoded `ccsync-companion.new.exe` while macOS packages have no `.exe`. Cosmetic today, but `platform_key()` can return `"linux"`, which `_upgrade_info` coerces to `"windows"` only for its lookup default (`api.py:1074`) — a Linux companion would be offered a Windows exe if a `linux` row ever existed. **Fix:** derive the suffix from `Path(sys.executable).suffix`.

**Checked and found consistent** (no finding): report payload field names/types vs `ReportIn`/`LaneReportIn`/`ManifestProjectIn`; pydantic's default `extra="ignore"` makes new-companion→old-dashboard skew safe; lane state strings vs the `Literal` and `schema.sql:70`; version strings across `companion/config.py` = `companion/pyproject.toml` = 0.4.3, dashboard 0.1.0, bench 0.1.0, plus `build_editor_package.ps1`'s drift guard; `DASH_*` env keys in `settings.from_env` vs `compose.yaml` / `install_dashboard_app.compose_config`; `syncthing_data_prefix` `/data/Projects` vs `install_syncthing_app.SYNCTHING_CONTAINER_MOUNT` + `setup_syncthing_folder.py`; `TEMPLATE_FOLDERS` / `VIDEO_EXTENSIONS` / `slugify` / `MARKER_FILENAME` triplicated across `server/common.py`, `dashboard/provision.py`, `companion/fixer.py` — all byte-identical; every key in `config.example.toml` is present in `config.DEFAULTS`.

---

# §9. installer / onboarding / server scripts

Beyond S-3, S-12, S-13, D-7, D-8, D-9 and the SEC items above.

- **`windows_bootstrap.ps1:188, 192` — autostart shims written as ASCII mangle non-ASCII usernames** — *medium*. The `.cmd`/`.vbs` shims embed `$CCRoot` and `$SyncthingHome` (which contains `%LOCALAPPDATA%`, i.e. the Windows username). On `C:\Users\José\…` every such character becomes `?`, so the logon shim points at a nonexistent path: Syncthing never starts at logon and, in the unelevated fallback, `subst P:` never runs. No error is ever shown. **Fix:** write UTF-8-no-BOM or the OEM codepage.

- **`windows_upgrade.ps1:84-92` — a locked exe leaves the editor with no companion at all** — *medium*. The companion is force-killed at `:75`, then `Copy-Item -Force` runs at `:90` under `$ErrorActionPreference = "Stop"` with no try/catch. If the 800 ms wait isn't enough (AV scanning the exe, a lingering handle — the exact scenario `build_editor_package.ps1:216-224` documents as seen live), the script dies **having already killed the companion** and without re-registering autostart or relaunching. **Fix:** retry the copy in try/catch and always run the relaunch step.

- **`onboard.py:470-505` — `_clean_slate()` runs before the bootstrap with no rollback** — *medium*. It kills processes, deletes all Run values and the scheduled task, deletes every companion exe, and unmounts `P:`. Any bootstrap failure — including S-3's `& $null` abort, no network, or winget prompting — leaves the machine with no companion, no autostart, and no `P:` drive: **strictly worse than before the "safe to re-run" installer was started**. The RETRY button only helps for transient failures. **Fix:** snapshot the removed Run values/exe paths and restore them on failure.

- **`onboarding/steps.py:355` — the bootstrap is invoked with no timeout** — *medium*. `subprocess.run(cmd, capture_output=True, text=True)`; `powershell -File` inherits a non-interactive captured stdin, so a winget prompt, a hung `subst`, or a stalled `Invoke-WebRequest` blocks the worker thread forever with both wizard buttons disabled (`onboard.py:416-418`) and no way out but killing the process mid-install. **Fix:** pass `timeout=` and surface it as an install failure.

- **`setup_syncthing_folder.py:85` — slug collisions silently point two projects at one path** — *medium*. The folder id is `slugify(rel)`, which collapses every non-alphanumeric run to `-`, so `2026/CCT/Season 1`, `…/Season-1` and `…/Season_1` all yield `2026-cct-season-1`. The second run hits `find_folder`, prints "folder already exists, skipping create", and **project B silently ends up sharing project A's path** — editors tick B and sync A. **Fix:** detect an id collision whose existing `path` differs from the computed one and fail loudly.

- **`windows_bootstrap.ps1:691` — `Add-Content` without `-Encoding` writes the system ANSI codepage** — *low*. A non-ASCII `-TailnetHost`/`-EditorName` lands mangled in `rclone.conf`, and appending ANSI bytes to an existing UTF-8 `rclone.conf` mixes encodings in one file. **Fix:** `[IO.File]::AppendAllText` with UTF8-no-BOM.

- **`windows_bootstrap.ps1:571` — `New-Item -Force` on an existing registry key deletes that key's values** — *low*. Harmless today because only `(default)` is used under `…\DriveIcons\P\DefaultLabel`. **Fix:** guard with `Test-Path`.

- **`server/requirements.txt:1-4` — floor-only constraints, no lockfile** — *low*. `paramiko>=3.4`, `requests>=2.31`, `urllib3>=2.0`. A future breaking major silently changes the behaviour of scripts that run as root against the NAS, with nothing recording the validated version. **Fix:** pin exact versions.

---

# §10. bench — measurement validity

This subsystem's output is used to choose the production sync engine, so a wrong number is as costly as a crash. The four criticals below all inflate throughput.

- **`_rclone_common.py:126` + `matrix.py:125-126` — a leftover destination turns a download into a no-op that reports full throughput *and passes verification*** — *critical*. The "down" destination is only `mkdir(exist_ok=True)`'d, never emptied; `matrix` cleans `dest_dir` with `shutil.rmtree(..., ignore_errors=True)` **after** the run, so a Ctrl-C/crash/AV-lock leaves `work/down/rclone_sftp/large/0` fully populated. The next run does `rclone copy remote dest`, rclone skips every identical file, exits 0 in ~2 s, `num_bytes` is set to the full 12 GiB manifest → **~6000 MB/s**, and `spot_check` passes because the correct files really are on disk. That row then wins Lane B's recommendation. **Fix:** delete `dest_dir` (non-`ignore_errors`, failing the run if it can't be emptied) immediately before the timed download, as `robocopy_smb.py:101-102` already does.

- **`_rclone_common.py:146` and `robocopy_smb.py:118` — `num_bytes` is the manifest total whenever the tool exits 0, never the bytes actually moved** — *critical*. Combined with silently-swallowed pre-cleans (`cleanup_remote` at `:84-88` catches everything and ignores `rclone purge`'s exit code; `robocopy_smb.py:94` uses `ignore_errors=True`), an "up" repeat whose remote pre-clean failed copies zero files, exits 0 in seconds, and is recorded as the full dataset at an impossible rate with `verified=True`. **Fix:** parse the real transferred byte count and reject runs that don't match the manifest; make pre-clean failures fatal.

- **`syncthing.py:263-273` — `_wait_for_sync` declares success on the first poll, before the devices have connected** — *critical*. A freshly created folder on the destination reports `needBytes: 0, state: "idle"` because it has no index yet, so the loop returns `completed=True` after ~0.5 s → `ok=True`, `seconds≈0.5`, full manifest bytes → **thousands of MB/s**, topping the Lane C leaderboard. **Fix:** require `globalBytes == expected_bytes and needBytes == 0 and inSyncBytes == globalBytes`, and don't start the timer until `/rest/system/connections` shows the peer connected.

- **`_rclone_common.py:69-81` — `_seed_remote` discards the return code and swallows `TimeoutExpired`** — *critical* (30 min default vs a 12 GiB seed). A partially-seeded remote makes the timed download move, say, 4 GiB while `num_bytes` records 12 GiB → **Lane B reported at 3× reality** — and the 3-file spot check frequently still passes because the sampled files happen to be among those that made it. **Fix:** check the seed's exit code and assert remote size/count against the manifest before timing anything.

- **`_rclone_common.py:177-178`, `robocopy_smb.py:144-145` — the remote is purged after *every* run, including "down" runs** — *high*. Each download repeat is preceded by a full re-upload, so the timed read hits the NAS's own ARC/page cache seconds later: Lane B measures RAM-to-network, not disk-to-network. It also roughly doubles data moved — the example config's Lane B sweep becomes ~1.1 TiB. **Fix:** skip cleanup for "down" (purge once at lane end) and add a cool-down / cache drop.

- **`report.py:42-57` + `base.py:112-137` — repeats are collapsed with `max(MB_s)` and no cache is dropped between them** — *high*. The ~600 MB "small" dataset fits entirely in RAM, so repeat 1 reads from cache and always beats repeat 0; taking the max systematically publishes the warm-cache outlier, and an engine that happens to run second gets a free win. **Fix:** report median or min, and drop caches (or enforce a dataset larger than RAM).

- **`_rclone_common.py:152-156`, `robocopy_smb.py:125` — every "up" run is `verified=True` on exit code alone** — *high*. The README promises a size+sha256 spot check on every successful transfer, and `report._winner` (`:97-98`) **prefers** verified rows — so unverifiable Lane A uploads structurally outrank genuinely verified rows. **Fix:** read files back from the remote for "up", or set `verified=False` and add `checked_by="exit-code"`.

- **`report.py:22-35` — the report re-derives the lane by substring-matching the dataset name and ignores the recorded `lane` field** — *high*. `matrix.py:75-98` carefully records `lane`. Name the dataset dirs `data/originals` and `data/proxies` and every row classifies as `"?"`: all three "Recommended per-lane config" sections print "No successful runs recorded for this lane yet" after a multi-hour run. `combo_key_no_repeat` (`:38-39`) also omits `lane`, silently merging two lanes that share a dataset+direction. **Fix:** use `r.lane` when non-empty; add `lane` to the key.

- **`syncthing.py:304-361` + `matrix.py:36` — Syncthing is benchmarked as a **loopback pair on local disk** yet ranked against real over-the-network engines** — *high*. Lane C will report Syncthing at local-disk speed and the report will assert Lane C "beats both readings" of the 60 mb/s baseline — a statement about nothing. `matrix.py:36` also runs this engine for Lanes A/B on the 12 GiB dataset. **Fix:** flag loopback results and exclude them from winner selection and the baseline verdict.

- **`syncthing.py:330-332` — the timer starts at folder creation, so it includes full-dataset hashing and device connection** — *high*. Syncthing must SHA-256 the entire seeded folder before announcing anything (minutes at GiB scale), while rclone/robocopy timers cover the transfer only. The harness will conclude Syncthing is slow for reasons unrelated to transfer speed. **Fix:** wait for the source folder to reach `idle` with `globalBytes == expected` before starting the timer.

- **`result.py:52-69` + `matrix.py:99` — the resume key excludes the endpoint and any dataset fingerprint** — *high*. Change `endpoints.sftp.host` from the LAN IP to the Tailscale address, or regenerate the dataset at a different size/seed, and re-running prints `[skip-cached]` for everything while the report mixes old and new numbers. **Fix:** fold the endpoint label and the manifest's `seed`/`total_bytes` into `combo_key`.

- **`matrix.py:108-119` — `runner.run(...)` is not wrapped, despite the documented "runners must never raise" contract** — *high*. `rclone_sftp.py:36` / `rclone_smb.py:49` raise `KeyError('host')` when the `[endpoints.*]` section is absent (default `{}`), `robocopy_smb.py:87` raises `ValueError` outside its `try:` when `unc_path` is unset, and `iperf3.py:114` raises `KeyError` if the JSON lacks `end.sum_received`. Any of these aborts a multi-hour matrix with a traceback. **Fix:** wrap and record `ok=False`.

- **`base.py:144-147` + `report.py:124` — MiB/s computed, MB/s reported and compared** — *medium*. `mb_per_s` divides by 1024² but the column, the recommendation text and the baseline arithmetic (`60/8 = 7.5`) treat it as decimal MB/s. Every published number is **4.86% below** the value it's compared against — exactly the margin the "did we beat 60 mb/s" verdict turns on near the threshold. **Fix:** pick one base and convert consistently.

- **`base.py:82-93` — `spot_check`'s `seed` defaults to `None` and no production caller ever passes one** — *medium*. The README promises "3 randomly chosen files (seeded, so the same 3 files are checked across an A/B comparison)". In reality each run samples different files, so a transport corrupting 1% of files passes or fails at random. **Fix:** pass a fixed seed derived from the combo key.

- **`result.py:107-117, 39-42` — one malformed line kills both `report` and every future resumable `run`** — *medium*. A truncated final line (a crash between the two `f.write` calls at `:103-104`) makes `json.loads` raise; `existing_keys` uses the same reader, so both paths die on the same traceback with no way forward but hand-editing. A row from an older schema missing a field raises `TypeError` from `RunResult(**filtered)`. **Fix:** skip-and-warn, and default absent fields.

- **`syncthing.py:230-234` — `restart_if_required()` POSTs to an instance launched with `--no-restart`** — *medium*. With the monitor disabled, an API restart makes the process exit instead of respawning; `_wait_for_gui` then burns 20 s and raises, so **every** Syncthing row becomes `ok=False, reason="exception: syncthing GUI never came up"`. **Fix:** drop `--no-restart`, or apply options via config file before start.

- **`syncthing.py:304-312` — each Syncthing run copies the dataset into `%TEMP%` and syncs a second copy beside it** — *medium*. With `bench.toml.example`, Lane A/B use the 12 GiB dataset and `matrix.py:36` includes Syncthing, so each run puts 24 GiB on `C:`, twice per lane at `repeats=2` — filling a typical system SSD mid-matrix. **Fix:** place instance dirs under `general.work_dir` and refuse to start below 2.5× dataset free space.

- **`dataset.py:147-167` — `generate()` doesn't clear `out_dir`** — *medium*. Regenerating `data/small` with `--small-count 100` over a previous 400-file run leaves 300 orphans; every engine transfers all 400 while `num_bytes` counts 100, **understating throughput ~4×** on a directory the user believes is clean. **Fix:** refuse to write into a non-empty dir without `--force`.

- **`iperf3.py:87` — hardcoded 120 s client timeout vs a configurable `duration_s`** — *medium*. Set `duration_s = 120` and `subprocess.run` raises `TimeoutExpired` out of `run()`, killing the matrix. **Fix:** derive the timeout as `duration_s * 2 + 30` and catch it locally.

- **Lower severity:** `dataset.py:56-67` file content depends on `chunk_size` (`randbytes` re-chunking reorders the stream), so changing `DEFAULT_CHUNK` silently invalidates every stored manifest — *low*; no free-space precondition before writing 12 GiB (`dataset.py:183-196`, `matrix.py:105`) — *low*; `report.py:86-89` doesn't escape `|` in table cells, so a reason containing a pipe shifts every following column — *low*; `config.py:5-7` vs `:64-70` — only `results_file`/`work_dir`/`[datasets]` are resolved relative to bench.toml, not `key_file`, contradicting the docstring and README — *low*; `base.py:124-137` inherits the parent's stdin, so a prompting tool blocks until the 3600 s timeout and looks like an ultra-slow transfer — *low*; `matrix.py:89` assigns `avail_fn` and never uses it (a lost skip-early) — *low*.

---

# §11. dashboard — collector, clients, templates, deploy

### C-1 — `compose.yaml:43` + `install_dashboard_app.py:225-226` — any editor can overwrite the container's entrypoint and execute code holding the NAS admin password — **CRITICAL** **[verified]**

**[Verified by the orchestrator:** `compose.yaml` mounts `/mnt/tank/apps/ccsync-dashboard/app:/app` with **no `:ro`**; `command: ["/bin/sh", "/app/deploy/run.sh"]`; `TRUENAS_PW` is in `environment:`; and `install_dashboard_app.py:225-226` does `chown -R 3000:3001` + `chmod -R u+rwX,g+rwX,o-rwx` — group `editors`.**]**

**Failure scenario:** Every editor has a real TrueNAS shell account (`shell: /usr/bin/bash`, `truenas_client.py:169`) in group `editors`, and the app dir is group-writable. Any editor overwrites `app/deploy/run.sh` — the literal `command:` target — and on the next container restart runs arbitrary code as `3000:3001` with `TRUENAS_PW` (the **TrueNAS admin password**) in its environment and `/projects` mounted rw. This chains directly with SEC-2.

**Fix:** Mount `/app` as `:ro` and give the app dir a group the editors are not in.

---

- **`collector.py:438` (with `:433`) — `_incomplete` is never pruned, and one stale entry permanently stops missing-file refresh for the whole fleet** — *high*. Entries are popped only when a device reaches 100%. Untick a project (or delete an editor device) while it is behind: `_run_config` rebuilds `_folder_devices` without that device so `_run_completion` never pops the key, and `_run_remoteneed` keeps calling `/rest/db/remoteneed?folder=…&device=<gone>`. Real Syncthing **errors** on an unknown folder/device pair; `_timed` catches it and aborts the *entire* remoteneed cycle, so missing-file lists stop refreshing for every editor, permanently. The suite is green only because `tests/fake_syncthing.py:149-156` returns an empty 200 for unknown keys. **Fix:** rebuild `_incomplete` from scratch each cycle and wrap the per-entry call in try/except.

- **`collector.py:408-435` — a SQLite write transaction is held open across every Syncthing HTTP call in the cycle** — *high*. `sqlite3` defaults to `LEGACY_TRANSACTION_CONTROL`, so the implicit `BEGIN` at `:421` is not released until `_timed` commits at `:153`. With 20 folders × 5 devices that is ~120 sequential requests at a 10 s timeout each holding the write lock, while companions' `/api/v1/report` POSTs (`db.connect` `busy_timeout=5000`) fail with `database is locked` → 500s and lost lane A/B status. `_run_inventory:352-363` has the same shape with multi-project `os.walk`s inside the transaction. **Fix:** collect all HTTP results first, then write and commit in one short burst.

- **`ui.py:584, 620, 647, 138` (with `truenas_client.py:235`) — blocking I/O and `time.sleep` inside `async def` handlers freeze the entire event loop** — *high*. `partial_admin_create_user` is `async def` and calls `create_or_update_editor` → `_fix_home_permissions` → `_wait_for_job`, which `time.sleep(2)`-polls for **up to 120 s** on the event loop; every other user's page, every htmx poll and every companion report stalls for that whole window. `page_login_submit` (`:138`) does the same with `_verify_smb`'s 10 s TCP connect (see SEC-13). **Fix:** make these four handlers `def` so FastAPI runs them in the threadpool.

- **`collector.py:228-232` — a failed `set_ignores` after a successful `add_folder` is never retried** — *high*. If the second call errors transiently, the folder exists, so the next provision cycle takes the retarget/label branches, which never call `set_ignores`. The server-side folder then has **no `.stignore`**, indexes `*.braw`/`*.mov` and every `Proxy/` dir into the global index, and lane C ships exactly the content lanes A/B exist to carry. **Fix:** verify/repair ignores for existing folders every cycle, not only at creation. (Same class as the `syncthing_admin.py:128-129` window in §4.)

- **`deploy/run.sh:15` — `pip install -e /app` on every container start turns any PyPI outage into a permanent crash-loop** — *high*. Under `set -eu`, the editable install uses PEP 517 build isolation, so pip must fetch `setuptools>=68` from PyPI on **every** boot, and `--no-cache-dir` guarantees it can't be served locally. No outbound internet, PyPI down, or broken DNS → `set -e` aborts → `restart: unless-stopped` loops forever with no dashboard. **Fix:** add `--no-build-isolation`, drop `--no-cache-dir`, and skip the install when the venv already imports `ccsync_dashboard`.

- **`deploy/compose.yaml:40-41` — `"8480:8480"` publishes on all interfaces** — *high*. Duplicate of SEC-10 from the compose side; recorded separately because fixing `install_dashboard_app.py` alone leaves the checked-in compose file wrong.

- **`collector.py:81-82, 149-153` — a DB error kills the collector thread for good** — *medium*. `_timed` catches the *runner's* exceptions, but its own `db.record_poll_run` at `:149/152` is unprotected. A `sqlite3.OperationalError: database is locked` — very reachable given the transaction finding above — propagates out of `run_cycle` → out of `_loop`'s `while` → the thread exits. `app.state.collector` still looks alive, nothing restarts it, and polling stops forever (which, per §7, also stops all retention). **Fix:** wrap the whole `while` body in try/except and log-and-continue.

- **`ui.py:441-445` + `templates/partials/project_detail.html:11-13` — "TICK FOR ME" destroys the polling wrappers and the media panel** — *medium*. The button swaps `closest main` with `innerHTML`; on `/project/<slug>` the response (just `project_detail.html`) overwrites `<main>`'s children, deleting both the `hx-trigger="every 10s"` wrapper (`project.html:8`) and the entire MEDIA PRESENCE panel (`project.html:11-13`). After one tick the page is frozen and the bins section is gone until a manual reload. **Fix:** target the inner polling div rather than `closest main`.

- **`collector.py:354` — the NAS inventory walk uses `projects.label` instead of the authoritative `projects.path`** — *medium*. `_run_config:262` stores `folder.get("label") or slug`, so any folder whose label is a display name rather than the rel path (hand-created, or predating the label-drift fixer) makes `projects_dir / label` miss — hitting `record_inventory_error("project dir missing on NAS")` every cycle and leaving MEDIA PRESENCE permanently at "NAS has 0 original(s) · 0 proxy file(s)". **Fix:** strip `syncthing_data_prefix` off `projects.path` to get the rel.

- **`truenas_client.py:193-206` — home-directory permissions are fixed only `if not warnings`** — *medium*. If TrueNAS hasn't propagated `sshpubkey` by the re-fetch at `:181`, a warning is appended, `_fix_home_permissions` never runs, the home stays group/world-accessible, sshd `StrictModes` rejects the key, and the editor's lanes A/B fail with a generic auth error — while the admin banner mentions only the sshpubkey and never the real cause. **Fix:** run the permission fix unconditionally and report both results independently.

- **`truenas_client.py:146-155` (from `ui.py:605`) — "create editor account" silently hijacks a pre-existing TrueNAS account** — *medium*. An admin typing `truenas_admin` (or any service account) into the create form has its `sshpubkey` overwritten with the submitted key, is force-added to the `editors` group, and then gets a `password_disabled: True` attempt at `:210`. `is_valid_username` only checks the character set. **Fix:** refuse usernames that exist but aren't already in `editors`, and require an explicit "update existing" confirmation.

- **`ui.py:140, 562` — unbounded `await request.body()` on the unauthenticated `/login` path** — *medium*. `/login` is in `app.py:_OPEN_EXACT`, so any tailnet host can POST a multi-GB body and OOM the single-worker container (uvicorn enforces no body limit); `parse_qs` also has no `max_num_fields`. **Fix:** check `Content-Length` and reject bodies over a few KB before reading.

- **`truenas_client.py:76` — `verify=False` on every TrueNAS call, including those carrying the admin password** — *medium*. Same root cause as SEC-3/`common.py:253-256`, on the dashboard side: an on-path host on 192.168.0.x can present any certificate and capture `truenas_admin`'s Basic-Auth credentials on the very first `GET /group` of a page load. **Fix:** pin the NAS certificate rather than disabling verification.

- **`deploy/compose.yaml:50` — `restart: unless-stopped` with no `healthcheck:`** — *medium*. The process stays alive when the collector thread dies (above) or uvicorn's loop is wedged, so Docker never restarts it and the UI serves indefinitely stale data. `/api/v1/health` already exists for exactly this. **Fix:** add a healthcheck hitting it.

- **`collector.py:366-377` — the change-detection signature hashes directory mtimes only** — *low*. Re-rendering a proxy or replacing an original **in place** (same filename, same dir) updates the file's mtime but not the parent directory's, so the signature matches, the walk is skipped, and `nas_media.size`/`mtime_ns` stay stale indefinitely. **Fix:** include a file-count or max-file-mtime per directory.

- **`syncthing_client.py:106, 109, 85` — `folder_id`/`device_id` interpolated into REST paths unencoded** — *low*. Folder slugs come from `.ccsync-project` marker JSON on a tree editors can write (`provision.read_marker:83-85` does no charset validation — see SEC-7), so a slug containing `/`, `?` or `#` yields a malformed or redirected `PUT /rest/config/folders/<slug>`. `approve_device` has the same shape with an unvalidated admin form field. **Fix:** `quote(..., safe="")` the segment and validate marker slugs.

- **`ui.py:254-268` — a `PermissionError` on one child aborts the browse loop but the partial listing is still rendered** — *low*. `entries` is created at `:235` outside the `try`, so the panel shows a truncated folder listing *plus* an error banner, and a user can "LINK THIS FOLDER" on the wrong target believing the tree is complete. The extra `child.iterdir()` at `:259-261` is also an N+1 syscall per row over an NFS/ZFS mount. **Fix:** catch per-child and mark that row degraded.

- **`truenas_client.py:96, 118, 128, 178, 184, 228, 239` — bare `resp.json()` after only an `ok()` status check** — *low*. A 2xx non-JSON body (proxy interstitial, middleware restart page) raises `json.JSONDecodeError`, which is not a `TrueNASError`, so it escapes the `except TrueNASError` handlers at `ui.py:610/637` and returns a 500 instead of the intended error banner. **Fix:** wrap and re-raise as `TrueNASError`.

- **`collector.py:95-98` — failure backoff replaces the interval instead of extending it** — *low*. `interval_prune` is 3600 s, but after one failed prune `next_due` becomes `now + 15 s`, so a persistently failing hourly cycle retries 240× more often than its own cadence. **Fix:** `max(interval, backoff)`.

- **`deploy/compose.yaml:13` — `image: python:3.12-slim` is an unpinned floating tag** — *low*. Combined with `pip install -e` on every boot, a background image update can silently change the Python patch level and the resolved dependency set between two restarts of an app that is never deliberately rebuilt. **Fix:** pin by digest.

- **`ui.py:157` — session cookie has no CSRF token and no `Secure` flag** — *low*. `SameSite=Lax` does block the cross-site POSTs that all mutating endpoints use, so this is defence-in-depth rather than an open hole; missing `Secure` is moot only because the deployment is plain HTTP. **Fix:** add a per-session CSRF token before the dashboard ever gains a reverse proxy.

### Explicitly checked and clean (dashboard UI)

These were the brief's headline concerns and came back clean — worth recording so they aren't re-audited:

- **XSS:** no `|safe`, no `Markup`, no `{% autoescape false %}`, and no `{{ }}` inside any `<script>` anywhere in `templates/`. Starlette builds the env with `autoescape=jinja2.select_autoescape()` and every template is `.html`, so escaping is on. All `{{ }}` in attributes are inside quotes, and the URL-bearing ones in `project_setup_panel.html` are `| urlencode`'d.
- **htmx mutation via GET:** every state-changing route is `@router.post`; all `hx-get` endpoints are read-only.
- **Open redirect:** `_safe_next` (`ui.py:120-126`) misses the `/\evil.com` trick, but Starlette's `RedirectResponse` percent-encodes `\` (`responses.py:213`), so **it is not exploitable as written**. (This supersedes the `ui.py:124` row in the SEC-15 table — worth a comment, not a fix.)
- **Template variables and routes:** every `{{ }}` / `{% %}` reference was cross-checked against each route's context, and every `href` / `hx-get` / `hx-post` target against the routers — no missing variables, no dangling routes.
- **Path traversal in `/project-setup`:** `_safe_rel` + `_validate_tree_part` + the post-`resolve()` prefix check correctly reject `..`, slashes, dotfiles and symlink escapes.
- Container runs non-root (`user: "3000:3001"`), `/data` is a persistent volume so SQLite and packages survive restarts, and `restart: unless-stopped` is present.

---

# §12. Suggested fix order

Ordered by (blast radius × likelihood), not by severity label alone.

**Tier 1 — fix before the next editor install.** These are either already happening on every install or destroy data on first use.

| # | Finding | Why first |
|---|---|---|
| 1 | **S-1** blank `remote_root` | Affects *every* `onboard.exe` editor today; originals go to the wrong place silently |
| 2 | **S-2** UTF-8 BOM → config silently ignored | Every upgrade run can zero out a working config |
| 3 | **S-3** `& $null` aborts bootstrap | Installs fail *after* the clean slate has removed the working install |
| 4 | **S-4 / S-5** case-sensitive rclone filters | Uppercase camera extensions never leave the machine; `proxy/` inverts both lanes |
| 5 | **D-1 / D-2** consolidate deletes proxies it says it won't | Data loss on the exact flow it was written for |
| 6 | **S-6** cp1252 decode deadlock | One CJK filename wedges the sequencer permanently — likely in this production context |

**Tier 2 — security, before any wider rollout.**

| # | Finding | Why |
|---|---|---|
| 7 | **C-1** editors can overwrite the container entrypoint | Editor → NAS admin, chains with SEC-2 |
| 8 | **SEC-1** identity token *is* a 30-day session | A file on a laptop is an admin session |
| 9 | **SEC-2 / SEC-3** admin password in container env + `AutoAddPolicy` | Credential capture, root-equivalent |
| 10 | **SEC-4 / SEC-5** unbounded lanes list, editor-spoofable reports | One editor can wedge or corrupt the fleet view |

**Tier 3 — silent-failure and stability.** S-7 through S-15, D-3 through D-9, the collector transaction/thread-death pair (§11), `db.py:230-248` migration bricking (§7), and the `os.renames` prune (D-3).

**Tier 4 — bench measurement validity.** All four §10 criticals before trusting any existing benchmark output. **Nothing in the current results file should be used to pick an engine until these are fixed** — every one of them inflates throughput, and two of them produce results that also pass verification.

**Tier 5 — everything else**, roughly in severity order.

---

# Appendix: method and confidence

- **Coverage:** all 169 tracked files. Eight auditors: companion sync lanes / companion core runtime / companion project logic / dashboard backend / dashboard clients+UI+deploy / installer+onboarding+server / bench / cross-cutting contracts.
- **Read-only:** no source file was modified. `AUDIT.md` is the only file created.
- **Verification tiers:**
  - **[verified]** in this document means the orchestrator independently re-read the code or ran a check. Empirically executed: the cp1252 stderr decode failure (S-6), the identity-token-as-session acceptance and dotted-username rejection (SEC-1, S-9), and the full test-suite baseline.
  - Two auditors ran live checks of their own: the rclone filter behaviour (S-4, S-5) against the repo's bundled `rclone.exe` v1.74.4, and the PowerShell BOM / `tomllib` rejection / `& $null` behaviours (S-2, S-3).
  - Unmarked findings are single-auditor, code-read only. They were required to cite `file:line` plus a concrete failure path, but have not been executed — treat the *mechanism* as reliable and the *severity* as an estimate.
- **Known limits:** no runtime testing against a real Resolve instance, a real TrueNAS, or a real Syncthing pair. Concurrency findings (the Resolve bridge lock, the collector transaction, lane thread leaks) are reasoned from the code, not reproduced under load. The bench findings are the least verifiable without hardware, and are also the ones where being wrong is cheapest to check.
- **Duplicates:** where two auditors independently found the same defect from different sides (the BOM issue, the `0.0.0.0` bind, `verify=False`, the `.stignore` window), both anchors are retained — they usually need two separate fixes.
