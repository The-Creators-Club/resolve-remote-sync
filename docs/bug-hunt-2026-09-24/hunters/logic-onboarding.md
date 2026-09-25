# logic-onboarding - the editor's first day: wizard, installers, EULA gate, first-run identity/config

Files read (approximate coverage): onboarding/onboard.py (all), onboarding/steps.py (EULA, verify, role, ensure_config, cleanup plan, p-mapping ~40%), companion eula.py (all), identity.py (save/preferred token/adopt ~40%), site.py (server_phrase/drive_phrase), app.py licence gate + prompt (6085-6300, 10985-11010), ui_copy.py, installer/windows_upgrade.ps1 (licence/wizard tail 600-774, mode block), installer/windows_bootstrap.ps1 (inputs/site manifest 640-860, foreign-drive refusal 1410-1470), installer/drive_mapping.ps1, dashboard api.py `api_verify` + `resolve_companion_credential`, auth.verify_credentials, docs/GOTCHAS.md per-editor token section, KNOWN_BUGS CR-66/CR-88/dash-core-2, docs/bug-hunt-2026-08-21.md data-model-2, docs/MULTI_BASE_RIG_PLAN.md.
Tests/probes run: one scratchpad probe (system python, onboarding + companion/src on sys.path) driving `steps.effective_install_role`, `steps.ensure_config` and `steps.build_cleanup_plan` against a temp config.toml. Nothing in the repo or `~/.ccsync` touched.

## Findings

### logic-onboarding-1 - The wizard still takes a machine's role from the PERSON, so a "safe to re-run" install dismantles an admin's remote laptop and loops a non-admin's wired desktop
- Severity: high
- Confidence: CONFIRMED
- Where: onboarding/steps.py:1752 (`effective_install_role`), onboarding/steps.py:3160 (`ensure_config` forces `mode`), onboarding/onboard.py:785-795 and 866-871; installer/windows_bootstrap.ps1:1428 (`New-ForeignDriveMiss` advice)
- What: `/api/v1/verify` answers `role = "base"` for every admin and `"editor"` for everyone else (api.py:2226). The wizard makes that override the radio the editor picked, then forces it into config.toml as `mode`, picks the cleanup plan from it, and picks the base or editor worker from it. Since CR-88 (companion 0.9.54) the rule is that wired/remote is the COMPUTER's own setting and the person's role is diagnostics only. The wizard is now the one place left that turns the person's role into the machine's mode, and it does this on every re-run. The amber note on the install page says the account's role is "which the companion obeys anyway", and that has been false since 0.9.54.
- Failure scenario: (a) The owner, an admin, re-runs onboard.exe on his remote Razer laptop, which Settings has set to REMOTE EDITOR, and picks "I'M A REMOTE EDITOR". The wizard switches to a base install. The probe shows config.toml rewritten to `mode = "base"` and `local_root = "P:\\"`. The base cleanup plan deletes the `CCSyncSyncthing` and `CCSyncSubstP` Run values and the `CCSync-SubstP` logon task. After the next reboot the laptop has no P: drive, Syncthing does not start, and the companion is in base mode and syncs nothing. The finish page says "DONE: CONNECTED TO THE NAS". (b) A non-admin editor on a wired office desktop picks "PHYSICALLY CONNECTED" and gets an editor install. The P: protection correctly refuses to touch the NAS mapping. The refusal then tells them to "run the wizard again and pick 'I'M PHYSICALLY CONNECTED TO THE SERVER/NAS' instead", and the wizard overrides that choice again, so every run ends in the same place. Meanwhile the rest of the editor install has already run: rclone/Syncthing installed, `mode = "editor"` and `local_root = C:\<tree>` written.
- Evidence: the probe printed `role: base`, then `mode = "base"` / `local_root = "P:\\"` over a config that had `mode = "editor"` / `local_root = "D:\\CCSync"`, and `run_values removed: [... 'CCSyncSyncthing', 'CCSyncSubstP' ...] tasks removed: ['CCSync-SubstP']`. onboarding/tests/test_steps.py:518-519 pin `effective_install_role("editor","base") == "base"` and `("base","editor") == "editor"`.
- Ledger: related to CR-66 (deferred data-model-2, 2026-08-21). CR-88 has since removed the companion half, which was the justification for that deferral, so the wizard now contradicts a CLAUDE.md invariant rather than matching the companion.
- Suggested fix: MULTI_BASE_RIG_PLAN WP5: let the radio win, and on a re-run default it from the existing config.toml `mode`. Keep only the mechanical guard: the P: foreign-mapping refusal, plus "an editor install onto a path that resolves to the NAS share". Delete the "companion obeys anyway" note.

### logic-onboarding-2 - On a site that has retired the shared report token, the wizard says DONE for a machine that has no fleet credential at all
- Severity: medium
- Confidence: CONFIRMED
- Where: onboarding/onboard.py:771-775 and 1334-1339 (finish page); dashboard/src/ccsync_dashboard/api.py:2216 (`report_token_kind`, read by nobody)
- What: Once `DASH_SHARED_REPORT_TOKEN_ENABLED=0`, `/verify` returns `report_token: ""` and `report_token_kind: "editor"` (dash-core-2 added that field "so the tray can say ask your admin for a per-editor token"). No consumer was ever written: grepping the whole tree finds the key only where it is set. The wizard writes a blank `dashboard_token`. It has no field for a `cce1.` token, and neither does either bootstrap. The only documented route is hand-editing `report_token = "cce1..."` into config.toml (GOTCHAS.md). The finish page then asks for "these two values" (device ID and SSH key) and does not mention the credential the machine is missing.
- Failure scenario: The operator follows the documented migration and turns off the shared token. A week later a new editor runs the wizard. It shows "DONE: SEND THESE TWO VALUES TO YOUR ADMIN", the admin approves both, and every report and selection read gets a 401 (`resolve_companion_credential` returns AUTH_NONE). The machine never shows up on the fleet grid, and nothing on either side says a per-editor token is the missing piece.
- Evidence: `grep -rn report_token_kind --include=*.py` finds only api.py:2216. steps.ensure_config puts a blank token into `defaults`, not `forced`. api.py:147-162 accepts only a cce1 token or the enabled shared token.
- Ledger: related to the dash-core-2 fix (KNOWN_BUGS ~line 2001, where `report_token_kind` was added and its consumer never built)
- Suggested fix: When verify returns `report_token_kind == "editor"`, show a "per-editor token (from your admin)" field on the install page and write it as config `report_token`. Alternatively, put the machine on the finish page in NOT READY state with that sentence.

### logic-onboarding-3 - windows_upgrade.ps1 sends a licence-only problem to the full reinstall wizard, alongside the companion's own licence dialog
- Severity: medium
- Confidence: CONFIRMED (route); PLAUSIBLE (two prompts on screen together)
- Where: installer/windows_upgrade.ps1:655-735
- What: If the acceptance record is missing, unreadable or older than the packaged EULA, the upgrade script `Start-Process`es onboard.exe and prints "work through it to accept the licence agreement". The wizard is the whole install: clean slate, companion killed, autostart deleted, P: remounted. APP-9 and CR-27 already decided that the smallest action is the companion's one-click licence dialog, which starts syncing without a restart. The companion this script has just relaunched opens that same dialog through `_licence_watch` about 3 seconds after start. So the editor gets two licence prompts at once, one of which leads into a reinstall. The script's copy also still describes the tray as "all three tray lines read 'this machine isn't set up yet'". Since CR-88 the tray shows a "► Accept the licence agreement to start syncing…" item and a NOT SYNCING licence line.
- Failure scenario: The owner bumps EULA-VERSION and an editor upgrades by hand with the package. The companion's licence modal and the wizard's LICENCE page open together. The editor accepts in the wizard, sees "WELCOME ... removes every trace of older CCSync versions" and either closes it (the companion modal is still waiting) or clicks through to a full reinstall of a working machine to produce a three-line JSON file.
- Evidence: windows_upgrade.ps1:714-722 (Start-Process onboard.exe) and :730-731; app.py:6130-6145 (the companion asks by design, "the upgrade path it never covered") and 10998-11015 (startup prompt).
- Ledger: new
- Suggested fix: Drop the wizard launch. Tell the editor to accept in the tray ("Tray > Accept the licence agreement", `ui_copy.ACCEPT_LICENCE`), which the relaunched companion is already offering.

### logic-onboarding-4 - The wizard and both bootstraps still ask for a "TrueNAS username and password"
- Severity: medium
- Confidence: CONFIRMED
- Where: onboarding/onboard.py:417, 427, 740; installer/windows_bootstrap.ps1:2463; installer/macos_bootstrap.sh:2836
- What: APP-10/SYNC-114 removed this vendor name from the companion's sign-in dialogs (`site.server_phrase()`) because it is false on the Synology target, and it is also false on a `DASH_AUTH_METHOD=local` site, where the account is a dashboard account with no NAS login. The wizard is the first thing a new editor reads, and its welcome page and the gate page ("STEP 3: SIGN IN") still name TrueNAS.
- Failure scenario: A zero-touch customer on local auth (or on Synology) creates an editor account on the dashboard. The editor reads "Enter the TrueNAS username and password your admin set up" and asks the admin for a NAS account that does not exist, or tries a NAS password and gets "bad username or password".
- Evidence: grep output listed above; site.py:422-435 docstring states the rule.
- Ledger: related to APP-10 (fixed on the companion side only)
- Suggested fix: Use `site_mod.server_phrase(self.site)` (or "the account your admin set up for you on the dashboard") in the three wizard strings and the two bootstrap end messages.

### logic-onboarding-5 - The editor finish page contradicts itself about signing in and asks for a key the wizard has already sent
- Severity: low
- Confidence: CONFIRMED
- Where: onboarding/onboard.py:1336-1343, 1072-1080
- What: The hint reads "One more step: right-click the tray icon → "Sign in…" is already done for you, but nothing downloads until...". It announces a step and then says the step is done. Separately, `_offer_ssh_key` has already posted the SSH key to the dashboard ("your admin approves it on the Users page"), and the heading still says "SEND THESE TWO VALUES TO YOUR ADMIN" and "Send these to your admin to finish signup". The page never says the key is already waiting for approval.
- Failure scenario: A non-technical editor reads "One more step: ... Sign in" and goes looking for a sign-in they do not need to do. They also paste a key to the admin that is already in the admin's approval queue, which is noise that makes a missing value harder to spot.
- Evidence: source text as quoted.
- Ledger: new
- Suggested fix: Say "You are already signed in." When `submit_ssh_key` succeeded, say the key is waiting on the dashboard's Users page and ask the editor to send only the device ID.

## Coverage note
Not reached: macos_bootstrap.sh beyond grep, windows_uninstall.ps1 / macos_uninstall.sh, build_editor_package.ps1, the macOS cleanup plan, config.py first-run validation (validate_config wording), identity.py sign-in dialog flow, onboarding's interrupted-install flow on macOS. Low-value observation not filed: the Tailscale page's NEXT goes back to disabled every time the page is re-entered through BACK, so the check has to be run again.

## OUT OF TERRITORY
- dashboard/src/ccsync_dashboard/api.py:2226: `/verify` still derives `role` from `is_admin`, and it is only harmless while every consumer ignores it. The wizard (finding 1) does not ignore it.
