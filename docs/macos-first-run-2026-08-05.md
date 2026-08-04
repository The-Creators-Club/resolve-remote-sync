# macOS first-run findings — 2026-08-05 (session 2: it runs)

Sequel to `macos-first-run-2026-08-04.md`, which got as far as *building* on a
Mac. This session is the first time the port has **run**: companion started,
signed in, tray icon on screen, tree on an external SSD, Resolve mapped, all
three lanes moving real bytes, and the onboarding wizard built, published and
executed end to end on the machine it targets.

**Scope reached: A7 through D, plus the wizard install drill.** Sections E
(SSD unplug), F (self-upgrade), G (caffeinate) and H (uninstall) are still
unrun. KNOWN_BUGS item 8's "code-complete, runtime-unvalidated" wording is now
out of date for lanes A/B/C and the install path; it is still accurate for
everything in E–H.

Four defect families were found, all of them invisible to the test suites and
all of them macOS-only. Three had already shipped to the fleet by the time
they were found.

---

## The machine

| | |
|---|---|
| Hardware | 16" MacBook Pro, arm64, macOS 15.7.4 |
| Display | 3456×2234, notch spanning x 771–956 in a 1728pt menu bar |
| Tcl/Tk | **9.0.3** — this is load-bearing; see MAC-8 |
| Sync root | `/Volumes/SAMDISK/Creators_Club` on a 2 TB **exFAT** volume, uuid `A8424FB3-…` |
| Versions at end | companion 0.4.22, installer 1.0.19, dashboard 0.3.7 |

The drive-and-filesystem question that blocked section E last session is
answered, but not the way the deployment is tested: exFAT was chosen because
the volume already holds 1.1 TB of the editor's unrelated work and there is
nowhere to park it while reformatting to APFS. Everything below therefore runs
on a filesystem with no POSIX permissions, case-insensitive names, and
AppleDouble sidecars — see Outstanding #1.

---

## MAC-6. Two Tk-interpreter defects in the companion — CRITICAL [fixed, `0c8a3cb`]

Both are consequences of the hidden `tk.Tk()` root that `ui_dispatch` creates
on the main thread on darwin, which makes a dialog's own root the *second* Tcl
interpreter in the process. Neither can happen on Windows, where no such root
exists.

**6a — a filled-in sign-in form failed with "username and password are both
required".** A masterless `tk.StringVar()` binds to `tkinter._default_root`,
which on darwin is the hidden root. The `Entry` wrote the typed text into the
dialog's interpreter; `.get()` read the hidden one's empty variable. Verified
directly: masterless `var.get()` returns `''` while the entry displays
`'alex'`; with `master=root` it returns `'alex'`. The fixer's destination
comboboxes had the identical bug, where it would have filed media at the tree
root. `companion/tests/test_tk_interpreter_hygiene.py` is an AST guard against
the next one.

**6b — the sign-in dialog opened exactly once per session.** Tk's loop runs
`while Tk_GetNumMainWindows() > 0`, and that count is **per thread, not per
interpreter**. The hidden root is a main window that never closes, so a
dialog's nested `mainloop()` does not return when the dialog is destroyed:

    entering nested mainloop
    t+2.5s: still inside the nested mainloop     # after destroy()
    HARD EXIT: nested loop never returned

The caller stayed blocked, `app._popup_active_lock` was never released, and
every later dialog was refused with "Another CCSync window is already open".
The same wedged main thread made the process ignore SIGTERM — it had to be
`kill -9`'d, which is how it presented in the wild. Fixed with
`ui_dispatch.run_dialog()`: `tkwait window` on darwin, `mainloop()` unchanged
everywhere else. `root.quit()` is **not** an alternative — _tkinter's quit flag
is process-global and would break `serve()` out of its own loop.

## MAC-7. The tray icon was never drawn, and the log said `tray icon started` — MAJOR [diagnostic added, `0c8a3cb`]

pystray reports success once the `NSStatusItem` exists. On a full menu bar
macOS gives the item a frame in the menu bar row and then does not render it.
Four items created at once landed on x = 812, 774, 736, 698 — **every one
invisible, including the one clear of the notch**. Anything left of the notch's
right edge is not drawn.

Ruled out by live probe, each one a real experiment on the hardware, not
reasoning: it is not a pystray/Tk run-loop conflict (identical placement with
no Tk in the process at all, and Tk's own windows draw fine in the same
process); not the activation policy (`setActivationPolicy_(1)` returns True and
reads back Accessory); not packaging (a real `.app` bundle with `LSUIElement`
and a working `CFBundleIdentifier` places identically); not icon width (a
forced 28pt item lands in the notch too).

Nothing app-side can conjure menu bar space, so the fix is diagnostic:
`tray.classify_status_item_placement()` compares the item's frame against
`NSScreen.auxiliaryTop{Left,Right}Area` three seconds after `run_detached()`
and logs a warning plus a toast when the icon landed where macOS will not draw
it. Confirmed in both directions — five overflowed items each warned; the one
at x=992 was called visible and a screenshot confirms it renders.

**Editors on notched MacBooks will hit this.** The remedy is freeing a menu bar
slot, which is a user action, not a code change.

## MAC-8. Every wizard UI update was silently discarded on macOS — CRITICAL [fixed, `a1a4f75`]

`OnboardWizard._safe_after()` marshalled background results to the UI with
`self.root.after(0, fn)` **called from the worker thread**. On Windows/Tk 8.6
that works, which is why it shipped. On macOS with Tk 9 it raises nothing and
never runs the callback:

    tcl/tk: 9.0.3
    after() from worker: no exception raised
    landed=[]                                    # 3 s later, still not run

So `_safe_after`'s `except Exception: pass` was never even reached — there was
no exception, just a discarded UI update and no log line anywhere. All
**eleven** call sites are affected: the Tailscale check (where it presents as a
status label stuck on "checking…" — the reported symptom), sign-in, the
bootstrap run, install failure, and both finish pages. **The wizard was
unusable past page 3 on a Mac**, and 1.0.17 had already been published as the
thing every Mac's `[ INSTALLER ]` serves.

Fixed with the same shape as the companion's `ui_dispatch`: a `queue.Queue`
drained by an `after()` timer created and re-armed **on the main thread**, so
only `queue.put()` crosses the boundary.

## MAC-9. The installer emptied `rclone.conf` — CRITICAL [fixed, `a016f04`]

`macos_bootstrap.sh`'s "the stanza disagrees with the values you passed"
branch — taken whenever the installer is **re-run** against an existing remote,
i.e. the normal upgrade path — passed a seven-line stanza through
`awk -v stanza=...`. macOS ships BWK awk, which rejects a `-v` value containing
a newline:

    awk: newline in string [creators_club_sftp]... at source line 1
    exit 2, zero bytes written

The script then `chmod`ped and `mv`d that empty output over
`~/.config/rclone/rclone.conf` with **no check on awk's exit status and no
check that anything came out**, destroying every remote in the file —
credentials for unrelated remotes included, directly contradicting the comment
above it. GNU awk accepts multi-line `-v` values, so no Linux or CI run ever
reproduced it.

Fixed in two layers: awk now only *deletes* the old section (single-line `-v`),
the shell appends the stanza; and nothing is swapped in until awk succeeded,
the new section is present, and every other section the file started with is
still there, with a timestamped backup kept. Mutation-verified — reintroducing
the old awk fails 3 of the 7 tests while the other 4 pass, because the verify
layer refuses the write and the config survives.

**Proven in production**: the 1.0.19 install run produced
`rclone.conf.ccsync-backup-20260805-001013` and left a working config, on the
exact code path that had emptied it 90 minutes earlier.

---

## What is now proven on real hardware

| Checklist area | Status |
|---|---|
| A7 install drill | **done** — wizard 1.0.19 run end to end, editor role |
| A8 publish | **done** — companion 0.4.22 and wizard 1.0.19 both current |
| B1 Tk dialogs vs pystray's AppKit loop | **answered** — they coexist; the icon problem was menu bar space (MAC-7), and the dialog problems were interpreter/loop scoping (MAC-6) |
| B3 SIGTERM reaching the shutdown guard | **works** — graceful shutdown observed repeatedly, once the MAC-6b wedge was fixed |
| C TCC prompts / quarantine | **partial** — Full Disk Access needed for the three binaries; quarantine only affects browser-delivered copies |
| D Resolve mapping write | **done** — `P:\` → the SSD in both `config.dat` and `.config.data`, `verify` exits 0, survives a Resolve restart |
| Lane A / B | **moving** — 409 proxy files, tree at 23 GB, after the SSH key was registered |
| Lane C | **moving** — Syncthing connected, folders accepted by the sequencer |
| Root guard | **works** — volume recorded with its real uuid on first present sighting |
| LaunchAgent | **installed and starts the companion**; never yet tested across an actual login |

---

## Outstanding

Ordered by what would hurt most if left alone.

1. **AppleDouble `._*` files are being synced — now live, not theoretical.**
   126 of them already in the tree (`…/Proxy/._energy_8187.mov`). On exFAT
   macOS writes a sidecar beside every file it touches, and the sidecar keeps
   the original's extension, so lane A's `+ *.mov` matches it. Verified against
   the real rule builders and the real rclone binary. This Mac will publish
   junk 4 KB `._clip.mov` files into the shared tree that Windows editors see,
   and lane B redistributes the proxy-side ones. Fix is `- ._*` at the head of
   both `build_filter_rules_up()` and `build_filter_rules_down()` (first,
   because rclone is first-match-wins), plus a sweep of what is already there.
   KNOWN_BUGS item 12.

2. **`rclone_lane.py:515` logs the first 300 characters of rclone's stderr.**
   For any SFTP remote the host-key `NOTICE` is ~260 of them, so the actual
   failure is always cut off mid-sentence. Tonight that turned
   `Permission denied (publickey)` into `Failed to create file system for` and
   nothing else, and the SSH problem needed a manual repro to find. Log the
   tail, or drop the NOTICE line. KNOWN_BUGS item 14.

3. **The broken wizard 1.0.18 is still a published package.** It carries the
   MAC-9 rewrite. 1.0.19 is current so nobody is served it by default, but it
   can still be fetched by number. Delete that row from the admin page — the
   delete endpoint refuses only the *current* version, so this is safe now.

4. **The Windows wizard needs rebuilding.** `onboard.py` is shared and changed
   in 1.0.18/1.0.19 (MAC-8). The Windows onboard package is still 1.0.17 while
   the repo is 1.0.19, so `check_deploy_drift.ps1` will flag it. The queue pump
   is correct on Tk 8.6 too — this is parity, not a Windows bug fix.

5. **The onboarding suite is red on macOS: 18 failed, 197 passed.** All in
   `test_steps.py` / `test_cleanup_steps.py`, all Windows-shaped assertions
   (PowerShell argv, drive letters, UNC paths, `.exe` fallbacks, registry Run
   values) running unguarded on darwin. Pre-existing — identical before and
   after this session's changes — but it means the suite cannot gate the
   platform the wizard now ships to. Same class as MAC-2 for the companion
   suite last session. KNOWN_BUGS item 15.

6. **The companion's Full Disk Access grant will not survive a self-upgrade.**
   It is ad-hoc signed (`TeamIdentifier=not set`), so its TCC identity is a
   hash of the binary and every upgrade looks like a different program.
   `rclone` and `syncthing` are properly signed and only need granting once. If
   proxies stop arriving after an update, check this first. KNOWN_BUGS item 16.

7. **Sections E, F, G, H remain unrun** — SSD unplug/ghost-dir/numbered-remount
   drills, self-upgrade, caffeinate, uninstall. E is now *possible* for the
   first time (the root really is on an external volume with its uuid
   recorded), and F matters more than it did: the LaunchAgent deliberately
   carries no `KeepAlive` and does carry `AbandonProcessGroup`, both marked in
   the source as awaiting first-Mac validation, and both only get exercised by
   a real self-upgrade under launchd.

8. **exFAT as the sync root is untested territory** beyond #1: no POSIX
   ownership or permissions, and case-insensitive names mean two clips
   differing only in case collide. Both lanes pass `--ignore-case`, which is
   consistent with the filesystem but does not make the collision safe.

9. **`installer/README.md` and the banner comments** in `macos_bootstrap.sh` /
   `macos_uninstall.sh` still describe macOS as runtime-unvalidated. That was
   correct this morning. It should now say: lanes and install path validated,
   E–H outstanding.
