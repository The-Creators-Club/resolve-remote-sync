# Known bugs

**Status 2026-08-11 (evening): the morning's 82-finding hunt is FIXED — same
day, all of it, plus the 45-finding ytdl ledger and the delete-protection
patch.** The full hunt text with per-entry resolutions and the deliberate
divergences is archived at `docs/bug-hunt-2026-08-11.md`; the ytdl ledger
(`docs/youtube_dlp_bugs.md`) carries its own resolution header. The fix pass
was eleven Opus agents over disjoint file territories, orchestrator-verified,
~125 files, +6.7k lines (about half of it tests). All ten suites green
(`tools\run_all_tests.ps1` — which now genuinely runs all of them, OPS-6).

**NOTHING IS DEPLOYED YET.** The working tree has the fixes; the fleet does
not. Shipping this needs: a companion version bump (`config.py` +
`pyproject.toml`), `tools\ship.cmd` (which now runs the companion+dashboard
suites itself — expect step 2 to take longer), and the Mac builds on a Mac.
The regenerated sprite sheets (2.4 GB) and the migrated b-roll DB reach the
NAS with the next b-roll data push; dashboard-side migration 009 applies
itself on next boot.

This file is the ledger of what is STILL open.

---

## Open — residuals from the 2026-08-11 fix pass

### R1 — the TrueNAS password still rides `net use`'s argv (SYNC-4 residual)
The log/toast/clipboard redaction shipped, but the credential is still passed
positionally on the command line, visible to any process on the box that can
enumerate argv. Moving it to stdin conflicts with the deliberate
`stdin=subprocess.DEVNULL` (the error-1223 prompt-hang fix), so this is a
design change: probably `cmdkey` first, then a credential-less `net use`.
Low urgency — editor-owned machines — but real.

### R2 — a same-size re-index can still serve stale semantic vectors (BROLL-17 residual)
The caches now key on `(count, MAX(rowid))`, which catches every observed
re-index shape except one: a replacement whose rows were already the table's
highest ids AND arrive in exactly the same number — SQLite reassigns the same
rowids and no cheap key can tell. `PRAGMA data_version` is unusable across
per-request connections. Documented at the cache sites; revisit only if a
same-count re-index is ever a real workflow.

### R3 — 428 b-roll rows remain on the legacy sprite fallback
After the same-day regeneration (7,118 sheets rebuilt with recorded
geometry): 390 rows have no local proxy to rebuild from and 38 are
error/degenerate rows (sub-second, audio-only, broken proxies) that have
never had a sheet. All keep the pre-fix browser behaviour exactly. The 390
become exact if their proxies ever return; `sprite_cell_h IS NULL` is the
work-list query (`broll/indexer/regen_sprites.py` is the sweep, idempotent).

### R4 — two OPS fixes are unverified against the live NAS
Both fail safe, but neither has run against the real box yet:
- OPS-2's prune guard greps `/proc/*/mountinfo` for a backup dir's basename
  before `rm -rf`; the path-string-after-rename behaviour is assumed.
- OPS-8's `<host-root>/staging` creation + `chown <TRUENAS_USER>` has not
  been exercised (falls back to `/tmp` non-fatally).
Watch both on the next `ship.cmd` deploy.

### R5 — delete-protection pre-flight: confirm the `ignoreDelete` PATCH round-trips
Implemented everywhere (creation sites, companion per-turn retrofit, shared
folders, and the dashboard collector's drift repair for pre-existing NAS
folders). Still owed, per the doc's own pre-flight: after the first
post-upgrade turn, `GET /rest/config/folders/<id>` on the base rig and one
editor and confirm the flag stuck — a Syncthing that silently dropped the key
would leave the fleet believing it is protected when it is not. Also still
open, deliberately untouched: the staggered-versioning `maxAge` disagreement
(companion 30 d vs server/dashboard 365 d — whichever wrote last wins; pick
one and reconcile).

### R6 — BROLL-16 overrode a documented decision — review it
`is_excluded_dir` is now case-insensitive. The old test pinned
case-SENSITIVITY as deliberate ("the NAS holds `youtube` and `Youtube` as
distinct folders"), but every configured share root today is a
case-insensitive Windows drive letter, so the premise no longer holds. If a
NAS-rooted (case-sensitive) share is ever configured, this flips back.

### R7 — ytdl behavioural-JS tests need node
`ytdl/web/tests/test_static_app.py` runs the real `app.js` in a `node:vm`
shim; its 13 behavioural tests skip cleanly where node is absent (the 8
source-level assertions still run). Dev machines and any future CI should
have node so those don't skip silently — `run_all_tests.ps1` will show the
skips.

---

## Carryover — unchanged from before the 2026-08-11 hunt

Full write-ups in `docs/bug-hunt-2026-08.md` and
`docs/macos-first-run-2026-08-05.md`.

- **Proxy generator, live-attach proof (was item 23) — still the SHIP-BLOCKER
  for the editor proxy rollout.** The four-point Resolve proof (HEVC Main-10 +
  `hvc1` + source timecode; adjacent-`Proxy/` auto-link; `LinkProxyMedia`
  over a stale absolute path; byte-flag parity with the b-roll indexer) has
  still not been run on the base rig. MED-1/MED-4 were exactly the class of
  gap this proof exists to catch — and both were real.
- **Lane B can sweep an editor-generated proxy into `.ccsync-trash` (was item
  22)** — tracked risk, mitigated by the tri-state `proxy_gen_enabled`
  default; revisit only if editor-side generation is ever wanted.
- **AppleDouble sweep (was item 12 residual)** — the `._*` excludes are
  fixed, but the one-time NAS sweep for already-uploaded sidecars is still
  owed.
- **macOS code-signing (was item 16)** — ad-hoc signature means the TCC/Full
  Disk Access grant dies on every self-upgrade; a Developer ID identity (a
  purchase) is the real fix.
- **macOS runtime validation backlog** — `installer/MACOS_FIRST_RUN.md`
  §A7–H unrun; wizard bundle never built on a Mac; onboarding suite needs a
  darwin run; lane C `.stfolder` behaviour untested there; MAC-12's wedged
  FSEvents stream on Leso's SAMDISK still needs hands on the machine.
- **Bench Syncthing 1.x (was item 1 residual)** — v1 argv test-pinned but
  never live-verified.
- **Mac builds owed — now carrying the whole 2026-08-11 fix pass.** Until
  `release_macos.sh --publish --make-current` and
  `build_onboard_macos.sh --publish --make-current` run on a Mac, Mac
  editors have none of today's fixes (including both UI criticals, which are
  worst on darwin), and `/music/send` + `/music/status` still 404 on every
  deployed companion until the fleet republish.
- **NAS hygiene (was item 7 incidental)** — `alex_laptop` in the `editors`
  group still looks like a machine-shaped account; rename if it is one.
