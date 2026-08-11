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

### R1 — the TrueNAS password rode `net use`'s argv — FIXED 2026-08-11 (afternoon)
`drive_swap.py` now maps P: via in-process `WNetAddConnection2W` (credentials
in call arguments, no argv, no console prompt to hang — the error-1223
constraint dissolves rather than being worked around) and persists via
`CredWriteW`. The 30 s ceiling survives on a daemon thread. Live-verified on
the base rig with a scratch target: the stored entry is byte-identical in
shape to what `cmdkey /add` wrote (`Domain:target=<host>`), so Explorer and
uncredentialed connects find it as before. Deliberate behaviour change:
error 1219 (session-credential conflict) no longer classifies as an auth
failure — the old localized-text match tripped it incidentally and looped a
login prompt into the same error. Still owed at ship time: one real
credentialed swap from an editor machine to confirm which error code the NAS
actually returns for "needs credentials" (5/86/1223/1326 are mapped), and
frozen-build DLL resolution per the verify-against-deployed rule.

### R2 — same-size re-index could serve stale semantic vectors — FIXED 2026-08-11 (afternoon)
Broll schema v10 adds a `meta` search-generation counter bumped in the same
transaction as every embeddings/search_norm/transcript write (web ingest AND
the indexer's sqlite backend), folded into the semantic and fuzzy cache keys
(count/high-water stay as belt and braces). Negative control ran: with the
generation neutered, exactly the two residual tests fail. The live
`E:\broll-queue\broll.db` is migrated to v10; the NAS copy migrates itself
on the next dashboard deploy's boot (same story as 009).

### R3 — 428 b-roll rows remain on the legacy sprite fallback — AUDITED, nothing to do
Audited 2026-08-11 afternoon: all 390 proxy-less rows are `skipped` rows
(the over-length duration cap — 156 ff3, 230 ff4, 4 mofa-disaster) that were
never proxied, never sprited, and never surface a scrub UI; none has ever had
a sheet on disk. The 38 with proxies are error/degenerate rows (sub-second,
audio-only, broken). No rebuild pass is warranted. `sprite_cell_h IS NULL`
stays the work-list query if any of them ever become real
(`broll/indexer/regen_sprites.py` is the sweep, idempotent).

### R4 — two OPS fixes unverified against the live NAS — VERIFIED 2026-08-11
Checked over SSH against the real box, no deploy involved:
- OPS-2 prune guard: the container's bind source appears in mountinfo as the
  ZFS-dataset-relative path (`/apps/ccsync-dashboard/app`, not
  `/mnt/tank/...`) — and the guard greps the BASENAME, which that line
  contains, so it works. Proven both ways as root on the live host: the
  running container's mount is visible to a `/proc/*/mountinfo` sweep (1
  process), and the existing unmounted `app.old.20260811090814`'s basename
  matches nothing (correctly prunable).
- OPS-8 staging: `mkdir + chown truenas_admin + chmod 700` of
  `<host-root>/staging` succeeds on this dataset (no aclmode=restricted
  refusal), and the unprivileged SSH user can write there. Cleaned up after.

### R5 — delete-protection pre-flight — VERIFIED AND ROLLED OUT NAS-SIDE 2026-08-11
The partial `PATCH {"ignoreDelete": true}` round-trips on the deployed NAS
Syncthing (GET confirms the flag, staggered versioning untouched), and it was
then applied to **all 9 NAS folders** (7 projects + both asset libraries) —
so the critical direction, an editor's slip deleting the NAS's authoritative
copy, is closed as of today with no code deployed. The collector's drift
repair keeps it asserted once the new dashboard ships. Still pending: editor
machines get their own flag from the companion's per-turn retrofit at the
fleet republish (verify one editor's folder then, per the doc); the base
rig runs no local Syncthing (nothing to flag there). Still open,
deliberately untouched: the staggered-versioning `maxAge` disagreement
(companion 30 d vs server/dashboard 365 d — pick one and reconcile).

### R6 — BROLL-16 overrode a documented decision — review it
`is_excluded_dir` is now case-insensitive. The old test pinned
case-SENSITIVITY as deliberate ("the NAS holds `youtube` and `Youtube` as
distinct folders"), but every configured share root today is a
case-insensitive Windows drive letter, so the premise no longer holds. If a
NAS-rooted (case-sensitive) share is ever configured, this flips back.

### R8 — the base rig's companion is still 0.6.1 — OPS-4 observed in the wild
Discovered 2026-08-11 while starting the Energy Transition proxy run:
`%LOCALAPPDATA%\ccsync\bin\ccsync-release.json` says **0.6.1** (built
2026-08-10), though the 4075b3c ship published 0.6.3 as CURRENT — i.e. the
exact OPS-4 failure (windows_upgrade fails, exits 0, relaunches the old exe,
ship prints complete). Consequences live on this machine right now: the
broken proxy muxer (its generator failure-capped all 1,046 gap clips
overnight and its queue reads 0), no `/music/send`/`/music/status`, none of
today's fixes. The Energy Transition proxies were therefore generated by a
one-off driver over the repo's fixed `encode_once` path (identical
artifacts; the companion's next scan simply sees them as covered). The next
`ship.cmd` — with the OPS-4 hard stop now in place — replaces this build and
clears the poisoned caps by restart; verify with `check_deploy_drift.ps1`.

### R7 — ytdl behavioural-JS tests need node
`ytdl/web/tests/test_static_app.py` runs the real `app.js` in a `node:vm`
shim; its 13 behavioural tests skip cleanly where node is absent (the 8
source-level assertions still run). Dev machines and any future CI should
have node so those don't skip silently — `run_all_tests.ps1` will show the
skips.

### R9 — many browser previews are 10-bit H.264 — pipeline FIXED, archive sweep DECLINED
Reported by a remote editor 2026-08-11 (evening): poster fine, clicked-into
player black, on Creators_Club clips. Cause: the indexer's `build_proxy`
never pinned a pixel format, so libx264 inherited the source's — and every
FX3/FX30 shoot is 10-bit, so those previews came out H.264 High 10 /
yuv420p10le, which browsers draw as a black rectangle (sampled 12 across 4
creators shares: 10 were 10-bit; Downloads are YouTube-sourced 8-bit and all
fine). Encoder now pins `-pix_fmt yuv420p`
(`broll/indexer/broll_index/ffmpeg_tools.py`, regression test cuts a proxy
from a 10-bit source and asserts 8-bit out). Dry-run measured the archive:
7,110 previews, **3,467 browser-hostile** — and not only under
Creators_Club/; plenty of 10-bit FX3 shots were filed under
Downloads/<category>/ by the archive build. **Admin declined the re-encode
sweep 2026-08-12** ("okay on Chrome"): playback relies on the browser
falling back to software decode, which current Chrome does. If a black
player comes back on some machine/browser, the prepared fix is
`broll/indexer/fix_10bit_proxies.py --apply` on the base rig (dry-run by
default; re-encodes from the adjacent top-slot original, atomic replace, DB
untouched, archive is under no sync lane so nothing fans out). NOT the
companion's proxy generator: its 10-bit HEVC editing proxies are for
Resolve, deliberate, untouched.

### R10 — archive previews can't attach as Resolve proxies (no timecode) — FIXED in code, sweep pending
Reported 2026-08-12: a b-roll insert landed from the correct archive path
but with Proxy: None. Diagnosed live against Resolve: scripted ImportMedia
never runs the adjacent-Proxy auto-attach, and an explicit LinkProxyMedia is
REFUSED — because Resolve validates the pairing and the preview carries no
embedded timecode while the camera original does (fps/frames/duration all
match; remuxing the same bytes with `-timecode 03:40:27;12` flipped the
identical link to accepted, in .mov and .mp4 alike — timecode is the
deciding factor, container irrelevant). Fixes: `build_proxy` now embeds the
source's timecode (`read_timecode` + `-timecode`); companion 0.7.4's insert
explicitly links `<dir>/Proxy/<stem>.*` after import, best-effort (a refusal
is logged, never fails the insert). The previews already in the archive stay
unattachable until `broll/indexer/fix_proxy_timecode.py --apply` runs on the
base rig — a container REMUX (`-c copy`), seconds per file, no GPU, no
quality change, unrelated to the declined R9 re-encode. Editors need the
0.7.4 republish for the explicit link.

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
