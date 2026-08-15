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

**2026-08-14: a third full-repo hunt ran (12 Opus hunters + 12 adversarial
verifiers, every tracked source file, briefed on this ledger and both 08-11
archives). It confirmed 94 NEW findings — 10 critical / 46 major / 38 minor —
plus 7 uncertain. FIXED the same evening by an 11-agent Opus fix pass
(disjoint file territories, orchestrator-reconciled; resolution header and
per-finding outcomes in `docs/bug-hunt-2026-08-14.md`). All 10 criticals
fixed; all 10 suites green (`tools\run_all_tests.ps1`: 0 of 10 failed,
~+250 tests); eight findings deliberately NOT fixed — see R16. Two pieces
of the pass already happened outside the repo: the base rig's
`broll-indexer-watchdog` scheduled task was re-registered against the
in-repo `watchdog.ps1` (still Disabled, ops half of BROLL-IDX-2), and the
music UI's reveal now requires a companion carrying `POST /music/reveal` —
one more entry in the "editors need a republished companion" column.
NOTHING SHIPPED: same ship path as above (companion → 0.8.0 was already the
target; this pass adds no new version spots).**

---

## Open — residuals from the 2026-08-14 fix pass

### R16 — eight 08-14 findings deliberately not fixed
Each was investigated by its territory's agent and declined for cause; the
full reasoning lives in each finding's entry in `docs/bug-hunt-2026-08-14.md`.

Needs a live spike or real-media benchmark before any code change:
- **YTDL-WEB-5** (enrich re-fetches flat-search metadata) — the collapse
  would silently drop the availability gate, the BotCheckError tripwire and
  `upload_date`; needs a live yt-dlp session to establish what flat entries
  actually carry.
- **COMP-GUARD-8** (proactive MappedRoot canon) — MappedRoot is unproven in
  both directions and `ensure_media_storage` renumbers `GALLERY_FS_KEY`
  entries; needs a base-rig experiment.
- **BROLL-IDX-7** (fold frame extraction into the scene-detect decode) —
  crosses the status-gated `organised` stage boundary and most timestamps
  derive FROM the detection output; needs benchmarking, and `stage_frames`
  is already input-seek + marker-idempotent.

Two-sided designs that must land atomically (design written, not built):
- **BROLL-WEB-7** (incremental semantic-cache invalidation) — the web half
  alone reintroduces the BROLL-17/R2 staleness class, and the vocabulary
  half is unsound without per-token refcounting; the safe two-sided design
  (dirty-video generation ledger in `meta`) is in the b-roll agent's report
  inside the hunt doc's entry.

New subsystems, not patches:
- **SERVER-10** (rclone-backed music-data push) — new command + remote
  config + root-owned post-step; its concrete costs were reduced by
  SERVER-1/-5/-6 this pass. **SERVER-11** (image-based provisioning) — no
  proven build/delivery path from this fleet's infrastructure.

Architecture changes declined on the merits:
- **DASH-8** (polling → SSE) — verifier holed two premises; unweighed costs
  on the page whose failure mode is "nobody can tell whether footage syncs".
- **DASH-7**'s cache halves (pending devices are not stored anywhere to
  serve from; a TrueNAS roster TTL cache would stale the admin's own
  actions) — the real harm (one backend blip blanks the whole panel) WAS
  fixed: the two backends now fail independently.

Also carried from the pass: `resolve_bridge.bridge_activity()` (COMP-MEDIA-9)
is a new zero-I/O reader nothing surfaces yet — a tray status line or
reporter field would make a wedged fusionscript call visible without log
archaeology.

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

### R10 — archive previews can't attach as Resolve proxies (no timecode) — FIXED, sweep RUN 2026-08-12
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
is logged, never fails the insert). SECOND half of the root cause (1643880):
Sony rtmd tags print colon (non-drop) forms for drop-frame material, and at
59.94 the colon reading is a different absolute frame — equally refused —
so both the encoder and the sweep normalize to the semicolon form at
29.97/59.94 (`dropframe_normalized`). The sweep
(`broll/indexer/fix_proxy_timecode.py --apply`, a `-c copy` container remux,
unrelated to the declined R9 re-encode) RAN 2026-08-12: 799 previews fixed,
0 failed; 4,046 already matched; 2,152 have timecode-less sources (YouTube —
nothing to mismatch); 113 have no unique top-slot sibling. End-to-end
verified live: the archive preview now links to its imported clip. Editors
need the 0.7.4 republish for the explicit link on insert.

### R11 — the Windows self-upgrade races its own single-instance mutex — FIXED in repo 2026-08-12, ships with 0.7.6
A remote editor's machine (ruskin, DESKTOP-LQQ41TC) was left with **no
companion at all** by a one-click update. Its log is the whole proof:

    00:34:53,950 upgrade: v0.7.3 launched; shutting down v0.7.0
    00:34:53,950 timeline watcher stopped
    00:34:55,034 another ccsync-companion is already running -- this instance is exiting

The second line is the CHILD. `upgrade.apply()` has to spawn the new build
before the old one exits (a failed spawn is what the rollback hangs off —
`upgrade.py` ~line 635), so for a second or two there really are two
companions. On posix the newcomer copes: `CCSYNC_REPLACES_PID` names the
predecessor and `app._acquire_lock_file()` waits up to
`PREDECESSOR_WAIT_SECONDS` for that exact pid to let go. **On Windows it does
not.** `acquire_single_instance()` reads `_replaced_pid()` only to drop it,
then returns False the moment `CreateMutexW` reports `ERROR_ALREADY_EXISTS`
— on the stated assumption (`upgrade.py` ~line 734) that "the named mutex is
released the instant we die and the child simply wins by timing". That is
backwards: the child reaches the guard ~1.1 s after being spawned, while the
parent is still tearing down lanes and holding the mutex. The child exits,
the parent finishes exiting, and nothing is left running. Nothing retries —
the Run-key autostart is logon-only — so the editor is silently offline until
the next reboot or a manual start.

It is a RACE, not a certainty: the same machine's 0.4.22 → 0.7.0 upgrade
earlier the same day survived it, and the base rig has never lost it. That is
why this has shipped several times unnoticed.

Fixed 2026-08-12 (companion 0.7.5, both halves of the sketch above):
- `app._acquire_mutex_win32()` — the win32 branch now keeps the
  `_replaced_pid()` value and, on `ERROR_ALREADY_EXISTS` during an upgrade
  hand-off, polls up to `PREDECESSOR_WAIT_SECONDS` re-trying `CreateMutexW`
  each pass. Deliberately NOT `_wait_for_predecessor()`'s liveness-only
  loop: `_pid_is_alive_win32` can read a dead process as alive (exit code
  259 + both fail-safe arms), so the wait is keyed on the mutex actually
  clearing; liveness only decides "the holder isn't our predecessor". Every
  probe handle is closed before waiting — our own handle would keep the
  named object alive forever. No hand-off pid → immediate refusal, exactly
  the old behaviour. The mutex-broken fallback now hands the already-popped
  pid to `_acquire_lock_file(replaces_pid=…)` instead of losing the wait to
  a second (empty) env pop.
- Belt and braces: `_default_spawn` returns the Popen and `apply()` watches
  it for `CHILD_TAKEOVER_GRACE_SECONDS` (2 s) — a child that dies inside the
  window rolls the swap back and keeps the old build running instead of
  standing down over a corpse.

Aftermath on that machine, worth knowing about:
- The editor tried to restart it by hand at 00:37:42 and got a **stale
  packaged build** — it logged `ccsync-companion v0.1.0 starting`, could not
  use the current v2 identity (`sign-in required`, `dashboard report skipped:
  no verified editor identity`) and was gone within 3 s. Prefetch shows it
  ran from a path used exactly once (`CCSYNC-COMPANION.EXE-6E2F19E6.pf`,
  distinct from the installed `…-BB78F76F.pf`) that no longer exists — most
  likely the July `CCSync_Editor_Package` opened straight out of its zip or
  out of the recycle bin (`C:\Users\user\Downloads\CCSync_Editor_Package.zip`
  is still there; the extracted folder is in the recycle bin, and the exe in
  it is a genuine v0.1.0 — its PYZ has `watcher`/`theme` and no
  `reporter`/`identity`/`upgrade`). Unresolved residual: that log block also
  contains lines only a post-0.2.0 build emits (`config OK:`, `sign-in
  required`, `timeline watcher started`, the reporter DEBUG), so the "v0.1.0"
  stamp and the code that ran do not match any commit here. Either two
  processes interleaved into `~/.ccsync/companion.log`, or a build exists in
  the wild whose `config.VERSION` was never bumped. Two lessons stand
  regardless: pre-guard builds (< 0.2.0) have **no** single-instance guard at
  all and will happily run alongside the real one, and every build shares the
  one log file, so a stray old exe corrupts the evidence.
- Resolved 2026-08-12 by installing **0.7.4** over SSH (exe + release
  manifest into `%LOCALAPPDATA%\ccsync\bin`, sha256 verified against
  `companion/dist`) and launching it into the console session via a throwaway
  `InteractiveToken` scheduled task — an SSH-spawned process lands in the
  network-logon session with no visible tray. It came up clean: identity
  intact, lanes and sequencer started, Resolve bridge connected.
  Note the CIM `*-ScheduledTask` cmdlets hang over that SSH logon; classic
  `schtasks /create /xml` works, and the XML's `UserId` must be the **SID**
  (`DOMAIN\user` fails with "No mapping between account names and security
  IDs was done").
- Both machines now have a Start Menu **CCSync** shortcut pointing at
  `%LOCALAPPDATA%\ccsync\bin\ccsync-companion.exe`, so a lost companion is a
  Start-menu search away rather than a hunt for a stale exe.
- Still owed: 0.7.4 is NOT published to the dashboard upgrade channel, which
  still advertises 0.7.3 as current. Both machines are on 0.7.4, and
  `upgrade.py`'s deliberate "different, not newer" rule means they will be
  offered an "Install v0.7.3" downgrade until the channel is bumped.

### R15 — the empty Youtube folder: ytdl delivered json and corpses, never videos — FOUR FIXES in repo 2026-08-14, unshipped
Investigated live on ruskin's machine 2026-08-13 23:2x → 2026-08-14 (full
writeup: "The Empty Youtube Folder" artifact; hybrid redesign plan:
docs/YTDL_LOCAL_DOWNLOAD.md). One editor-visible symptom — every
`credits.json` and 540p preview present, zero videos, a growing pile of
`.part` files — decomposed into four independent defects:

1. **The ytdl page's project select reverts to position 1 on every load**
   (`app.js` rebuilt it fresh, ordered by the editor's dashboard sync
   positions, nothing remembered), so searches meant for Energy Transition
   filed 16 term folders under Creator Profiles. Fixed: last pick persisted
   in localStorage, restored only if the slug is still in the server's list
   (assigning a `<select>` a missing value silently selects nothing);
   ytdl/web suite 362.
2. **YouTube serving one format truncated failed the whole clip.** Video
   SAQBbd1Rxmo's f137 died at ~10 MB from BOTH the NAS's IP and the base
   rig's ("N bytes read, M more expected … Giving up after 10 retries")
   while f136 worked; five clips across the tree had a stalled `.part` and
   no deliverable anywhere. Fixed in `worker.py` (vendor file untouched —
   retry policy is the worker's): the truncation signature (both markers,
   DownloadError by name) triggers ONE retry a rung down via the
   downloader's own QUALITY_HEIGHTS, note recorded on the done row;
   transient 403s/bot checks never downgrade. Final failure now sweeps the
   clip's own `[id]`-bearing `.part`/`.ytdl` litter via the unified
   `_record_failure()`. All five stranded clips hand-recovered to the NAS
   the same night (two only had 720p left server-side).
3. **Syncthing replicated yt-dlp's in-flight files and the editor-side
   `ignoreDelete=True` retrofit (2026-08-11) made them immortal** —
   `.stignore` ignored rclone's `*.partial` but not `*.part`/`*.part-Frag*`/
   `*.ytdl`: 27 orphans, 1.6 GB, three days deep on ruskin's disk (cleaned).
   Fixed three ways in lockstep — server/common.py, dashboard provision.py
   (the load-bearing copy: `collector._ensure_ignores` re-POSTs on ANY
   list difference, so a server-only fix would be stripped every provision
   cycle), companion syncthing_admin.py — plus a three-way cross-component
   pin. server 244, dashboard 425, companion 2752.
4. **The watcher's per-clip "missing on disk" DEBUG line rotated 5 MB of
   log every ~25 min** on a machine missing media (thousands of clips ×
   every poll), rotating away the very upgrade history the investigation
   needed. Fixed: per-watcher dedupe set (assignment-per-pass, so recovery
   re-arms and the set is bounded by the open timeline), one line per
   newly-missing path plus a per-pass count summary.

Delivery context, so the symptom reads right: NO lane carried Youtube
originals on his 0.7.4 build (Syncthing stignores video extensions by
design, lane B was Proxy-only until 8985571's `+ /Youtube/**` shipped in
0.7.6, lane A is up-only) — the fix existed a full day, published 12:40
2026-08-13, parked behind the notify-and-one-click upgrade he hadn't
clicked. The LNG folders (~9 GB, 86 clips) were hand-pulled to his machine
that night via his own rclone under schtasks; both folders verified equal
to the NAS.

Still owed: fixes 1–3 ride the next dashboard deploy + companion publish
(fix 3 is INERT until both — the deployed collector strips the new ignore
lines every provision cycle until it is redeployed); fix 4 rides 0.7.8;
`setup_syncthing_folder.py` re-run per existing project (no --force) to
push the new stignore; ruskin (and any other stale tray) onto ≥0.7.6.

### R14 — the BPG hand-off launched a generator that watched nothing, then never started it — FIXED in repo 2026-08-13, unshipped
`bpg.py` opened the Blackmagic Proxy Generator whenever BRAW/R3D/CRM had no
proxy and deliberately touched neither its watch list ("that config is
yours") nor its window. Both halves were load-bearing, and on the base rig
both were empty:

- `watchFolderList=@Invalid()` — Qt's spelling of "no folders". BPG rewrites
  that file from memory on every exit, so a folder removed once is gone for
  good, and a watcher with no folders is a silent no-op. The rig launched it
  at 14:09, 15:26 and 18:13 on 2026-08-13 alone, against 6 BRAW clips that
  had had no proxy since 2026-05-20 (`…/Creator Profiles/Season 1/B-roll/
  Editor Added/ruskin/`), and the gap never moved.
- Even with folders, the window opens **Idle** with a **Start** button and the
  folders at "Waiting". There is no flag, env var or INI key for it.

Fixed: `proxy_scan` now reports `needs_resolve_dirs` (a count cannot tell a
watcher where to look), `bpg.ensure_watch_folders` seeds the list additively
before launch — user entries carried over as text, ancestors honoured, one
`.ccsync-backup`, capped, only while BPG is down since a running one would
overwrite the file — and `bpg.press_start` presses Start over UI Automation
(PowerShell + `UIAutomationClient`, the CIM probe's precedent). The control's
NAME is its state, "Start"/"Stop", so we press only when it says "Start" and
never press Stop; `InvokePattern.Invoke()` works where `TogglePattern.Toggle()`
silently does not. Both halves have config opt-outs
(`bpg_manage_watch_folders`, `bpg_autostart`, on by default). Live-verified
end to end on the rig the same evening: all 6 BRAW clips now have proxies.

**Open decision — the duplicate-encode collateral.** BPG watches folders, not
files, and recognises only its own `Proxy/<stem>.mov`; it re-encoded 172 clips
in that folder that the companion had already proxied as `.mp4` (the 161 `.mp4`
duplicates were deleted afterwards, keeping BPG's `.mov` side, which is what
BPG itself tracks). The candidate fix is to make `proxy_scan.GENERATED_EXT`
`.mov` (with `-f mov` in both `ffmpeg_tools` builders) so BPG treats companion
output as done and only ever encodes what ffmpeg cannot decode. It does not
touch the b-roll browser, which serves the INDEXER's 540p H.264 `.mp4`
(`broll/web/app/routes_media.py:44-47`, `Content-Type` hardcoded `video/mp4`)
from the archive tree and never a `proxy_gen` file — and `archive_path` may
already be `.mov` today by design (`broll/indexer/build_archive.py:181-183`).
Not taken yet: it changes what every machine in the fleet writes.

### R13 — a half-failed ship had no way to finish itself — FIXED in repo 2026-08-13
The 0.7.6 ship published the companion, then failed on the installer:
`onboard.exe` bundles the companion exe, so a companion release changes the
installer's bytes by itself, and 1.0.24 was already published — the server
kept the old build and `build_editor_package.ps1` correctly called that a
failed run (the 1.0.21 rule, third time it has bitten). What it left behind
had no supported exit: the fix is installer-only, but `ship.cmd`'s fail-fast
gate hard-stops on "companion 0.7.6 is ALREADY published", and
`build_editor_package.ps1` publishes the companion FIRST and exited 1 on any
409 — including a 409 whose bytes are identical, which is exactly what a
half-failed ship guarantees.

- Installer version bumped 1.0.24 → 1.0.25 across all four sites.
- The companion 409 now compares the server's sha256 against the local exe,
  the same way the installer upload has always done: identical bytes → say
  so and carry on to the installer; different bytes (or unknown) → the old
  hard stop, since the fleet would silently keep the old build. `-MakeCurrent`
  cannot ride a skipped upload, so it says to confirm CURRENT by hand.

`ship.cmd`'s own gate is deliberately NOT relaxed — a full ship builds a new
companion, so re-shipping a published version is a real error there. Recovery
runs the individual script, which is what it is for.

### R12 — the Energy Transition path-canon incident — FIXED in repo 2026-08-12 (evening), unshipped
Two hundred–plus clips in the shared "Energy Transition" project carried
machine-private paths with zero warnings from anyone: 47 imported on the base
rig via `W:\Creators_Club\...`, 158 imported by the remote editor from his
`F:\Creators_Club\...\Youtube\<term>\Proxy\*.mp4` (the 540p previews were the
ONLY rendition any sync lane ever delivered to him), plus strays on `Z:\`,
`I:\` and a Desktop. All relinked to `P:\` by script the same day; the repo
fixes that stop it recurring, all with tests, all green (2646 + 81 + 77):

- `resolve_bridge.replace_clip` now verifies by re-reading File Path with
  retries — ReplaceClip returns None even on success, so the old code
  misreported every success (resolve-relink's relink_one pattern).
- Lane B also pulls `/Youtube/**` (originals + credits sidecars) down to
  editors; `*.part`/`*.ytdl` debris excluded. youtube_import skips a root
  `Youtube/Proxy/` dir instead of importing it as a term named "Proxy".
- Canonicalize-at-import: youtube_import, the b-roll insert and the music
  worker now ReplaceClip freshly imported clips to the `P:\` spelling
  (identity no-op on the base rig); their dedupe folds both spellings.
- `paths.classify_path` grew NON_CANONICAL (in-tree, local spelling →
  auto-relinked, once per path) and FOREIGN (another machine's path, not on
  disk → tray warn-once; MISSING stays reserved for canonical not-yet-synced
  files). Wired into the timeline watcher AND a new classification pass on
  the existing 120 s media-tree sweep — bins are no longer a blind spot.
- Stale-fusionscript recovery: when the Resolve the companion had connected
  to exits, the companion restarts itself (upgrade.restart_self — the R11
  spawn/hand-off machinery without the swap; `bridge_auto_restart = false`
  opts out). Left in place, the stale client wedges every NEW Resolve
  session's scripting server for every client — proven live on the remote
  editor's rig across three Resolve restarts, healed only by
  companion-then-Resolve restart order. NO_SCRIPTING_MESSAGE now gives that
  order.
- Web UIs no longer assert "companion not running" on a rejected fetch (a
  Chrome local-network-permission block on the http:// dashboard origin is
  indistinguishable); they hedge and offer the `127.0.0.1:8899/status`
  self-test. The music UI's inverted error mapping fixed.

Not addressed here: serving the dashboard over HTTPS (makes the browser's
local-network permission grantable/durable), and routing inserts through the
dashboard's companion-poll channel instead of browser→loopback — both remain
open options if the block recurs. Ships with the next companion release;
remember the upgrade channel still advertises 0.7.3 (R11's residual).

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
