# Wave 2 ledger: release (owed round)

The group's wave-2 chunk ledger is `release-tools.md`; this file holds only the
owed round the orchestrator addressed to the group as "release".

## Owed round

### bug-comp-app-7 (from c-app) - "needs a Mac build (tools/release_macos.sh) to reach macOS editors"
- Status: DEFERRED (an operator act at ship time, not a code change)
- Verified as: the note is correct. The fix (`app.py` `_pid_looks_like_companion`
  / `_own_executables`) only changes behaviour on posix, so a Windows ship
  delivers nothing for it; it reaches Mac editors only in a macOS bundle.
  PyInstaller does not cross-compile, and `tools\ship.cmd` already publishes no
  macOS artefact and prints the advisory to run the Mac half (CLAUDE.md
  "Building & shipping", `docs/RELEASE.md`). The release tooling therefore
  already says what is owed; there is nothing in `tools/*` or `docs/RELEASE*.md`
  to change, and a builder on the Windows base rig cannot run
  `release_macos.sh` or publish to the channel (publishing is the owner's
  step, and ships are never done inside a fix wave).
- Fix: none in code. The action is recorded for the ship of this pass.
- Regression test: none (no code change; the behaviour is pinned by c-app's
  tests in the companion suite).
- Tests run: none (no file touched).
- OWED: owner / ship: after the wave-2 companion version is committed, on a
  Mac run `git pull && ./tools/release_macos.sh --publish --make-current`
  (pathway A), or let CI's macOS runner build it and publish via
  `tools/publish_latest.py` (pathway B, `docs/RELEASE_PATHWAYS.md`). Until
  then Mac editors keep the old single-instance guard.
