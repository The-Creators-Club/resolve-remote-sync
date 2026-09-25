# ui-onboarding - onboarding wizard UI (onboard.py + steps.py copy) and installer-visible messages
Files read (approximate coverage): onboarding/onboard.py (all), onboarding/steps.py (~35%: verify/probe/URL/tailscale, finish helpers, breadcrumb, close warning, console-user refusal, local-root validation, effective_install_role), onboarding/assets/EULA.md (head), onboarding/tests/test_no_em_dashes.py, companion theme.py (neon_button, palette), installer/windows_bootstrap.ps1 (end banner + capability misses), non-ASCII/em-dash scan of every installer/*.ps1 and *.sh.
Tests/probes run: rendered every wizard page off-screen with the companion venv's Tk (steps' disk-touching helpers stubbed, nothing written to ~/.ccsync) and measured requested height against the 660x560 window and which widgets end up unmapped; WCAG contrast of the theme palette; em-dash scan of EULA.md and the installer scripts.

## Findings

### ui-onboarding-1 - Fixed 660x560 window clips CLOSE / BACK / the log path off the finish and install pages
- Severity: medium
- Confidence: CONFIRMED
- Where: onboarding/onboard.py:71 (WINDOW_SIZE), onboarding/onboard.py:1333-1381 (show_finish), onboarding/onboard.py:832-953 (show_install)
- What: every page packs its nav bar LAST (side=bottom), so when the content is taller than the window Tk takes the space from the nav bar first. The finish page with warnings and the install page with the role-override note are both taller than 560 px at default size.
- Failure scenario: an install that ends with two ordinary capability misses (the bootstrap's own ~290-character "Syncthing device ID could NOT be determined..." text, twice) squeezes CLOSE to 1 px; with more warnings the SSH-key field, "Send these to your admin", the install-log path and CLOSE are all unmapped - on the page whose instruction is "send them this list" and "the file named at the bottom of this one". On the install page with the "you picked X, but the dashboard says" note, BACK is unmapped (and even without the note it is clipped to 16 px tall), so after a failed install RETRY is the only visible way forward.
- Evidence: measured off-screen: install page 564 px requested (620 px with the role note, BACK winfo_ismapped()=0); finish page with 2 real-length warnings: CLOSE frame height 1; with 8 warnings the last four widgets report ismapped=0.
- Ledger: new
- Suggested fix: pack the nav bar FIRST (side=bottom) so it is always reserved, and put the variable middle (warning list, log box) in a scrollable/expanding region; or size the window from winfo_reqheight after the page is built.

### ui-onboarding-2 - The licence page shows the raw draft file: HTML comment with TODO(legal) notes, markdown syntax and em dashes
- Severity: medium
- Confidence: CONFIRMED
- Where: onboarding/onboard.py:365 (text_widget.insert(steps.EULA_TEXT)), onboarding/steps.py:680-698, onboarding/assets/EULA.md:1-19
- What: eula_text() returns the .md verbatim and the page inserts it into a Text widget untouched. The first thing every new editor reads is `<!-- DRAFT FOR COUNSEL -- NOT LEGAL ADVICE, NOT YET EXECUTABLE ... TODO(legal): replace "Cablewrap Creative" ... almost certainly NOT the correct contracting entity ... -->`, then `# CC Sync ... ` / `**Version 1.0 ...**` markup, and 14 em dashes (owner rule: none in anything an editor reads; test_no_em_dashes.py only scans *.py so it cannot see this).
- Failure scenario: a customer's editor opens onboard.exe and is asked to ACCEPT a document that says in its first lines it is not executable and names the wrong legal entity (and a brand the owner has retired).
- Evidence: read EULA.md head; eula_text() has no stripping; `grep -c` of U+2014 in EULA.md = 14.
- Ledger: new
- Suggested fix: strip HTML comments (keeping the EULA-VERSION marker for parse_eula_version) and render headings/bold minimally (or ship a plain-text EULA); extend the em-dash scan to assets/EULA.md.

### ui-onboarding-3 - "Last install did not finish" page and the close-mid-install warning always say "no P drive", on the base path and on a Mac
- Severity: medium
- Confidence: CONFIRMED
- Where: onboarding/onboard.py:279-286 (show_interrupted), onboarding/steps.py:2164-2174 (install_close_warning)
- What: both texts are role- and platform-blind. A base ("physically connected") install never touches the drive mapping (build_cleanup_plan sets unmount_p only for role == "editor", steps.py:2616; macOS plan unmount_p=False), and a Mac has no drive letter at all. The breadcrumb records the phase (`clean_slate:base`) but show_interrupted ignores it, and FINISH THE INSTALL returns to a role page whose radio defaults to "editor" rather than the role the interrupted run used.
- Failure scenario: the wired studio machine's install is closed mid-way; on reopening the wizard says the P drive is gone and "nothing is syncing" although the NAS mapping is intact, and the resume flow preselects the remote-editor radio (the destructive install) for a machine that was running the base one. A Mac editor is told they have "no P drive".
- Evidence: code read; base cleanup plan confirmed at steps.py:2616/2897.
- Ledger: new (the radio default on resume is related to CR-66, deferred)
- Suggested fix: branch the copy on the breadcrumb's phase role and IS_MACOS ("no CCSync app" only, for base/Mac), and preselect role_var from the breadcrumb.

### ui-onboarding-4 - INSTALL TAILSCALE (winget) leaves the page stuck: stale "NOT INSTALLED", green success on failure, and a join check that cannot find the new tailscale.exe
- Severity: medium
- Confidence: CONFIRMED
- Where: onboarding/onboard.py:635-639, 681-696; onboarding/steps.py:943-969
- What: (a) the INSTALLED/NOT INSTALLED line is computed once at render and never refreshed; (b) the winget worker ignores returncode and prints "winget install finished -- sign in..." in GREEN even when winget failed or UAC was cancelled; (c) tailscale_up on Windows tries only the bare `tailscale` name, resolved against the wizard's own PATH, which was captured before Tailscale's installer added its folder to PATH - tailscale_installed() checks Program Files\Tailscale\tailscale.exe but tailscale_up does not.
- Failure scenario: a new editor clicks INSTALL TAILSCALE, signs in to Tailscale, clicks CHECK CONNECTION and is told "tailscale isn't joined yet -- open the Tailscale tray icon and sign in" every time, with NOT INSTALLED still shown above, until they close and reopen the wizard.
- Evidence: code read; `_tailscale_cli_candidates` returns ["tailscale"] off macOS; FileNotFoundError falls through to False.
- Ledger: new
- Suggested fix: add `%ProgramFiles%\Tailscale\tailscale.exe` to the Windows candidates (as macOS already does with its app path), check winget's exit code, and refresh the status line after the install and on every check.

### ui-onboarding-5 - Finish page copy contradicts itself and the rest of the install
- Severity: low
- Confidence: CONFIRMED
- Where: onboarding/onboard.py:1371-1378, onboarding/onboard.py:1105-1133, onboarding/steps.py:2094-2097
- What: (a) "One more step: right-click the tray icon -> "Sign in..." is already done for you" - a step and not a step in one sentence; (b) the wizard already POSTed the SSH key to the dashboard (_offer_ssh_key, OPS-2) but the page never says whether that worked and still says "Send these to your admin to finish signup"; (c) the truncation line tells the editor to "use COPY LOG on the previous page", but the finish page has no BACK and no COPY LOG, so that page is unreachable.
- Failure scenario: an editor reads that there is one more step, looks for it, and sends the admin a key the admin already has in the approval queue; with >6 warnings they are sent to a button they cannot reach.
- Evidence: code read; show_finish calls _nav_bar(back=None).
- Ledger: new
- Suggested fix: reword the tray line ("You are already signed in; nothing downloads until your admin approves the two values above"), record _offer_ssh_key's result and say "already sent to your admin" when ok, and put a COPY LOG button on the finish page.

### ui-onboarding-6 - Welcome says you need "nothing else" but the next page requires a dashboard URL
- Severity: low
- Confidence: CONFIRMED
- Where: onboarding/onboard.py:417-418, 427-428 vs 500
- What: both welcome texts end "You'll need the TrueNAS username and password your admin set up for you -- nothing else." The very next page makes the dashboard url REQUIRED and refuses NEXT without it (WP0 removed the default).
- Failure scenario: an editor starts the wizard with only their login, as told, and is stopped on page 2 waiting for the admin.
- Evidence: code read; DEFAULT_DASHBOARD_URL is "" (steps.py:143).
- Ledger: new
- Suggested fix: "You'll need two things from your admin: the dashboard address and your username and password."

### ui-onboarding-7 - Role-override note speaks the internal words 'base'/'editor', not the radio labels the person picked
- Severity: low
- Confidence: CONFIRMED
- Where: onboarding/onboard.py:857-862
- What: the note reads "you picked 'base', but the dashboard says this account is 'editor' -- so this is a 'editor' install ... only the 'editor' install unmaps and re-creates the P: drive". The page the person answered said "I'M PHYSICALLY CONNECTED TO THE SERVER/NAS" / "I'M A REMOTE EDITOR"; 'base' appears nowhere on screen, and the only action offered next to a warning about unmapping P: is BEGIN INSTALL.
- Failure scenario: a non-admin editor on a wired office machine cannot tell from this note that the install about to run will tear down their NAS drive mapping (the destructive direction CR-66 describes).
- Evidence: code read.
- Ledger: related to CR-66 (deferred; bug-hunt-2026-08-21 data-model-2)
- Suggested fix: use the radio labels in the note and, while CR-66 stands, say in plain words "this will disconnect your P: drive from the NAS; press BACK and ask your admin if this computer is wired".

### ui-onboarding-8 - Keyboard: no Enter on sign-in, no initial focus, no visible focus ring on any button
- Severity: low
- Confidence: CONFIRMED
- Where: onboarding/onboard.py (no bind/focus call anywhere), companion/src/ccsync_companion/theme.py:436-449 (neon_button highlightthickness=0)
- What: the sign-in form has no <Return> binding and nothing takes focus when a page opens; every button is drawn with highlightthickness=0, so tabbing gives no indication which one is focused (and tk.Button answers Space, not Enter).
- Failure scenario: an editor types their password and presses Enter: nothing happens; tabbing to VERIFY & CONTINUE shows nothing.
- Evidence: `grep -n "bind\|focus" onboarding/onboard.py` returns nothing.
- Ledger: new
- Suggested fix: focus the first entry on each form page, bind <Return> to the page's primary action, give neon_button a visible focus highlight.

### ui-onboarding-9 - Secondary text and input borders fall below readable contrast
- Severity: low
- Confidence: CONFIRMED
- Where: companion/src/ccsync_companion/theme.py:19,23; used throughout onboard.py (e.g. 500, 474, 939-945)
- What: MUTED #6f6f7a on BG #0a0a0d is 3.98:1 (3.63:1 on FIELD), used for 8-9 pt text: the "dashboard url (REQUIRED ...)" label, both radio subtitles that explain what each choice installs, the log-file path and every BACK button. RED_DIM entry borders are 1.86:1, so the input fields barely show.
- Failure scenario: on a dim laptop screen the explanation of which install unmaps the drive, and the field outline for the required URL, are hard to read.
- Evidence: WCAG relative-luminance computation.
- Ledger: new
- Suggested fix: lighten MUTED to about #8c8c98 (>=4.5:1) for text and use a >=3:1 border colour for fields.

### ui-onboarding-10 - Wrong-account refusal tells the person to sign in as the account that is already signed in
- Severity: low
- Confidence: CONFIRMED
- Where: onboarding/steps.py:2210-2215
- What: "You are running as X but Y is signed in ... Sign in as Y and run it again". Y is already signed in; what went wrong is that the wizard was started under X (typically by typing an admin login into a UAC credential prompt).
- Failure scenario: the editor signs out and back in as Y, starts the wizard the same way, and gets the same refusal.
- Evidence: code read of console_user_mismatch.
- Ledger: new
- Suggested fix: "Close this and start the installer again by double-clicking it as Y; do not use Run as administrator or enter another account's password when asked."

### ui-onboarding-11 - Bootstrap end banner streams "remaining manual steps" into a wizard run that has done them
- Severity: low
- Confidence: CONFIRMED
- Where: installer/windows_bootstrap.ps1:2446-2469
- What: every wizard editor install ends its log (and the saved install log the admin is sent) with "Remaining manual steps (see docs/EDITOR_SETUP.md): 1. tailscale up ... 2. generate an SSH keypair ... ssh-keygen ... send the .pub file ... 3. SIGN IN ...", written for a hand run. The wizard already joined Tailscale, made and submitted the key and signed in; an editor has no docs/ folder.
- Failure scenario: an editor or admin reading the install log follows steps 1-2 and generates or sends a second key.
- Evidence: code read; run_bootstrap streams every line to _append_log.
- Ledger: new
- Suggested fix: pass a -FromWizard switch (or detect the identity token) and print only what is actually left.

### ui-onboarding-12 - VERIFY & CONTINUE and CHECK CONNECTION stay clickable while their request is in flight
- Severity: low
- Confidence: PLAUSIBLE
- Where: onboarding/onboard.py:698-733, 759-821
- What: neither button is disabled while its worker runs, so a double click starts two verifications; each success calls show_install, so the second one rebuilds the install page, and a later failure clears the password field under a page that has moved on.
- Failure scenario: a double-click on a slow link signs in twice (two identity tokens minted), and if BEGIN INSTALL was pressed between the two results the second show_install replaces the live log widget mid-install.
- Evidence: code read; not reproduced.
- Ledger: new
- Suggested fix: disable the button and show "verifying..." until the worker's _ui runs; ignore stale results with a generation counter.

## Coverage note
Not read: the remaining ~65% of steps.py (cleanup executors, config merge, macOS validators), most of windows_bootstrap.ps1 / macos_bootstrap.sh / windows_upgrade.ps1 / uninstallers beyond the end banner and a non-ASCII scan (clean: no em dash or non-ASCII outside comments in any installer script), the macOS wizard's rendering (measured on Windows fonts only; Menlo metrics differ), and high-DPI scaling of the frozen exe.

## OUT OF TERRITORY
- dashboard/src/ccsync_dashboard/api.py:2226: /verify still derives the machine role from is_admin (CR-66, deferred); the wizard's override is the visible end of it.
