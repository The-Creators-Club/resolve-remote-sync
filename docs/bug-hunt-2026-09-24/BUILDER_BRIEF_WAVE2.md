# Fix-pass brief, wave 2 (2026-09-25): every medium and low - read fully before editing anything

Repo: E:\Projects\Editing\ccsync, HEAD `4462a2a` (companion 0.9.78 / dashboard
0.7.58, the highs wave CR-322..CR-332 committed). You are ONE of about twenty
builders, each owning a FILE GROUP (below), fixing the eleventh hunt's
remaining MEDIUM and LOW findings (`docs/bug-hunt-2026-09-24.md`; full text
under `### <id>` in `docs/bug-hunt-2026-09-24/hunters/<hunter>.md`, the hunter
being the id less its trailing number). Your chunk of findings is in your
prompt. Several chunks of one group run one after another, so an earlier chunk
of your own group may already have changed your files: read them fresh.

## Verify first

- A MEDIUM was checked by an adversarial verifier: its verdict and reason are
  in `docs/bug-hunt-2026-09-24/verifiers/med-*.md` (grep the id) and
  `verdicts.json`. Some were DOWNGRADED to low; that is the severity to use.
- A LOW was NOT verified by anyone. Verify it yourself before you touch code:
  read the cited code, its callers and callees, CLAUDE.md, `KNOWN_BUGS.md`
  (`grep -a`) and the earlier hunts. If it is not a real defect, change
  nothing and say why.
- Owner decisions that are NOT defects: a computer with nothing ticked is
  fine (never an error, warning or alert anywhere); any editor's companion may
  finish another editor's expired YouTube job; companion versions stay below
  1.0; no customer's name in code.
- A finding may already be fixed by the highs wave or by the Timeline Cards
  picker redesign (commits `5a26e10`, `5ff6982`, `4462a2a`). Check `git log`
  and the code; if so, say ALREADY_FIXED and name the commit.

## Rules

1. Edit only files your group OWNS (list below) and TESTS for them. Put new
   tests in a NEW file named `test_bug_hunt_2026_09_24_w2_<group>.py` (or
   `Test-*.ps1` for installer) in the owning component's tests dir, so two
   builders never edit one shared test file. Edit an existing test file only
   when it must change because behaviour you fixed changed, and say so.
2. If a correct fix needs a change in a file ANOTHER group owns, make the
   smallest change in your own files and write the rest as OWED, naming the
   owning group, the file, and exactly what is needed. The orchestrator routes
   OWED items to that group in a later round. Never edit another group's file.
3. Do NOT bump versions, edit `KNOWN_BUGS.md`, edit `docs/README.md`, commit,
   push, or run `git stash/checkout/reset`.
4. Every fix gets a REGRESSION TEST that FAILS on HEAD's code and passes on
   yours (say how you know: ran it against `git show HEAD:<file>` in a scratch
   copy, or reasoned line by line). For a UI change, also render it where you
   can (a test client or a static file) and, for layout, look at it in headless
   Chrome at 1280 and 390 px wide (`"C:\Program Files\Google\Chrome\Application\chrome.exe"
   --headless=new --screenshot=... --window-size=...`; headless has a minimum
   window width, so put a 390 px iframe inside a wider page for the phone
   view). Screenshots go in your scratchpad, not the repo.
5. Run ONLY the test files you touched or that exercise the functions you
   changed (owner rule: the full gate runs once, centrally). Interpreters per
   component are in CLAUDE.md "Running tests"; `server/` from Git Bash;
   installer tests with `powershell -NoProfile -ExecutionPolicy Bypass -File`.
6. Comments at each fix cite the finding id and date
   (`# ui-dash-main-3 (2026-09-25): ...`) and explain the constraint or failure
   mode, never what the next line does. Match the surrounding code's idiom.
7. Version skew: the field runs companion 0.9.77 against dashboard 0.7.57
   (0.9.78 / 0.7.58 are committed, unshipped). A new wire key must be optional
   on read and harmless when ignored, in BOTH directions. A schema change is a
   new migration step that runs on any older database and twice; every reader
   of a new column survives NULL. Say the deploy order in your ledger.
8. No user-visible em dash anywhere (tray, popups, templates, SPA strings,
   HTTP detail, alert mail). Comments, docs and logs are exempt.
9. Do not touch `~/.ccsync`, `%LOCALAPPDATA%\ccsync`, the NAS, the live
   dashboard, Resolve, or any live process: this machine is the studio's base
   rig and its companion is running. Never call `scriptapp()`.
10. Keep each fix proportionate. A finding whose honest fix is a redesign, or
    that needs the owner's decision, is DEFERRED with the reason and the
    decision needed, not half-built.

## File groups (who owns what)

All companion paths under `companion/src/ccsync_companion/`, dashboard under
`dashboard/src/ccsync_dashboard/`.

- **c-app**: `app.py`, `__main__.py`.
- **c-sync**: `sync/*`, `selection.py`, `file_moves.py`, `drive_reminder.py`,
  `drive_swap.py`, `manifest.py`, `root_guard.py`.
- **c-ui**: `tray.py`, `tray_native.py`, `popup.py`, `settings_window.py`,
  `ui_dispatch.py`, `ui_copy.py`, `ui_state.py`, `theme.py`, `crash_report.py`,
  `stills.py`, `eula.py`, `ytdl_browser_login.py`.
- **c-resolve**: `resolve_*.py`, `script_server.py`, `fixer.py`,
  `proxy_relink.py`, `watcher.py`, `luts.py`, `consolidate.py`,
  `project_setup.py`, `timeline_cards_*.py`, `library.py`.
- **c-broll-music**: `broll_*.py`, `broll_vlm/*`, `loopback_guard.py`,
  `music_*.py`, `music_clap/*`.
- **c-ytdl**: `ytdl_executor.py`, `ytdl_server.py`, `ytdl_common.py`,
  `ytdl_cookies.py`, `ytdl_attestation.py`, `youtube_import.py`,
  `ytdlp_manager.py`.
- **c-media**: `jobs_*.py`, `job_paths.py`, `proxy_gen.py`, `proxy_scan.py`,
  `proxy_history.py`, `ffmpeg_tools.py`, `bpg.py`, `sidecar_tools.py`,
  `proc_tree.py`.
- **c-core**: every other companion module (`upgrade.py`, `supervisor.py`,
  `shutdown_guard.py`, `config.py`, `site.py`, `identity.py`, `machine.py`,
  `reporter.py`, `capabilities.py`, `paths.py`, `canon.py`, `idle.py`,
  `secretfile.py`, `release_pubkey.py`, `ed25519.py`, ...).
- **d-db**: `db.py` (and schema migrations).
- **d-api**: `api.py`.
- **d-diag**: `alerts.py`, `notices.py`, `invariants.py`, `health.py`,
  `collector.py`, `recovery.py`, `protection.py`, `mount_status.py`,
  `triage*.py`.
- **d-cards**: `cards*.py`, `jobs.py`, `broll.py`, `music.py`, and
  `dashboard/static/cards_landing.*` + `dashboard/templates/cards_landing.html`.
- **d-auth**: `auth.py`, `app.py`, `settings.py`, `setup_*.py`,
  `site_store.py`, `provision.py`, `assignments.py`, `links.py`, `locate.py`,
  `sessions.py`, `oidc.py`, `local_users.py`, `secrets_boot.py`.
- **d-ops**: every other dashboard module (`ai_providers.py`, `cli_tools.py`,
  `ytdl.py`, `dashboard_update.py`, `release_feed.py`, `release_trust.py`,
  `package_store.py`, `nas/*`, `help.py`, `syncthing_client.py`, ...).
- **d-ui**: `ui.py`, `dashboard/templates/*` and `dashboard/static/*` except
  the Cards landing files.
- **broll**: `broll/*`.
- **music-ytdl**: `music/*`, `ytdl/*`.
- **onboarding**: `onboarding/*`, `installer/*`.
- **release-tools**: `tools/*`, `server/*`, `bench/*`, `.github/*`,
  `docs/RELEASE*.md`.
Docs describing a component belong to its group (`docs/*.md` other than
README.md); if two groups need one doc, the second writes OWED.

## Output

Append to `docs/bug-hunt-2026-09-24/ledger2/<group>.md`, one section per
finding:

```
## <finding-id> - <title>
- Status: FIXED | NOT_A_DEFECT | ALREADY_FIXED | DEFERRED | PARTIAL (rest OWED)
- Verified as: <what you read or ran that shows it is (not) real>
- Fix: <what changed, files:lines>
- Regression test: <file>::<test> - fails on HEAD because ...
- Tests run: <command> -> <result>
- Skew / deploy order: ...
- OWED: <group, file, exactly what> | none
```

Then return the same as structured output.
