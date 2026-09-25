# Verifier med-18 (2026-09-25)

Judged against HEAD (63d4290) via `git show` / `git grep` and a HEAD
`git archive` of `onboarding/` + `companion/src` in the session scratchpad.
Read-only: no repo file touched except this one; the Tk measurement ran with
HOME/USERPROFILE pointed at a scratch folder and `_install_finished` /
breadcrumb reads stubbed out.

## ui-onboarding-1 - CONFIRMED (medium)

Every page packs its nav bar last with `side="bottom"` (`_nav_bar`,
onboard.py:207-208), so an over-tall page loses the nav bar first. Measured
off-screen at the default 660x560 (page frame 524 px after the container
padding): the install page requests 555 px with no role note and 611 px with
it, and in both cases BACK is unmapped (height 1). The finish page is fine
with 0-2 real-length warnings on this rig's fonts, but with 3 warnings CLOSE
is unmapped and with 5 nine widgets are. The window is resizable
(`minsize` only), which is the only mitigation, and nothing tells the editor
to enlarge it. Evidence: `measure.py` in the scratchpad, using the verbatim
`Add-CapabilityMiss` device-ID text from windows_bootstrap.ps1:2443.

## ui-onboarding-2 - CONFIRMED (medium), same defect as ui-comp-windows-3

`steps.eula_text()` (steps.py:680-689) returns the file verbatim and
`show_eula` inserts it untouched (onboard.py:365). HEAD's
`onboarding/assets/EULA.md` opens with the `DRAFT FOR COUNSEL ... NOT YET
EXECUTABLE ... TODO(legal) ... almost certainly NOT the correct contracting
entity` comment, then markdown headings/bold, and contains 14 U+2014 (counted
with Python). CR-5 records the EULA as a draft awaiting counsel, but not that
the internal comment and markup are what an editor is asked to ACCEPT; no
earlier hunt has it. ui-comp-windows-3 is the identical defect on the
companion's `popup.licence_dialog` surface: one fix (strip comments except
the EULA-VERSION marker, render minimal text) should cover both.

## ui-onboarding-3 - DOWNGRADE (low)

Real: `show_interrupted` (onboard.py:279-286) and `install_close_warning`
(steps.py:2164-2174) always say "no CCSync app and no <letter> drive", while
the base cleanup plan never unmaps (`unmount_p=(role == "editor")`,
steps.py:2616; macOS `unmount_p=False`, :2897), and the breadcrumb's
`clean_slate:<role>` phase (onboard.py:1057) is never read back. But the
consequence is one wrong sentence on a rare path: the page's instruction
("finishing the install is safe and is the only thing that fixes it") is
still right, and the resume radio defaulting to "editor" is overridden by
the dashboard role at verify (the CR-66 behaviour the hunter already links).
On a Mac the wizard itself speaks of "Resolve's P:\ mapping", so the letter
is not meaningless there either.

## ui-onboarding-4 - CONFIRMED (medium)

All three parts hold at HEAD. (a) The INSTALLED/NOT INSTALLED label is
computed once in `show_tailscale` (onboard.py:635-639) and never updated.
(b) `_on_install_tailscale` (681-696) ignores `subprocess.run`'s return code
and prints the GREEN "winget install finished" for any non-exception exit,
including a UAC cancel. (c) `_tailscale_cli_candidates` returns only
`["tailscale"]` off macOS (steps.py:943-948), resolved against the wizard's
own environment captured at launch, so a freshly installed
`C:\Program Files\Tailscale\tailscale.exe` raises FileNotFoundError and
`tailscale_up` returns False, although `tailscale_installed` does check that
path. NEXT is enabled only by `up and probe.ok` (onboard.py:715-720), so the
editor who used the button cannot leave the page until they restart the
wizard. That blocks onboarding, so medium is right.

## ui-copy-1 - CONFIRMED (medium)

`_check_fleet_halt` (alerts.py:1402) says "SYNC STATUS, then [ RELEASE THE
HALT ]". That label exists nowhere in templates (`git grep` finds it only in
alerts.py and the VOCABULARY_ALLOWED allow-list, test_sweep_2026_09_04_copy.py:396);
the controls are `[ START SYNCING AGAIN ]` / `[ KEEP IT STOPPED ]` in
`partials/fleet_halt.html` on `/admin/users#admin-fleet-halt`, and fleet.html
has no halt control. The alert half is softened by the halt banner on EVERY
page (base.html:148, fleet_halt_banner.html), which links an admin to the
right place, so the "syncing stays stopped" scenario is mostly refuted for
the alert. The recovery step is not softened: `_stop_the_fleet_step`
(recovery.py:862-869) sends the admin to `/fleet` BEFORE a halt exists, so no
banner shows and there is no stop control there, in the middle of a restore
whose whole point is that the fleet must be halted first. That keeps it at
medium.

## ui-copy-2 - CONFIRMED (medium)

Five notice fix strings (notices.py:241, 290, 315, 1001, 1515) name
"Settings, Diagnostics", which is not in `SETTINGS_NAV_GROUPS`
(ui.py:165-190). The registry points at least nine kinds
(`collector_cycle_failed`, `collector_watchdog_restart`,
`syncthing_unreachable`, `feature_not_mounted`, `server_error`, `db_busy`,
`slow_write`, `slow_poll`, ...) at `/fleet#fleet-diagnostics`, which is the
bare `<div id="fleet-diagnostics"></div>` (fleet.html:42) filled only by
`[ READ THE ANSWER ]` / the partial's own link (fleet_grid.html:463,
admin_diagnostics.html:37); no static JS loads it from the hash. So a server
error notice leads to an empty anchor and a page name that does not exist.
The crash-report notice has its own working href (db.py `server_crash_report`),
so only its sentence is wrong.
