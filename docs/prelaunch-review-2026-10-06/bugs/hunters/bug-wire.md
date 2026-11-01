# Pre-launch bug hunt 2026-10-06: bug-wire (cross-component wire contracts)

Lens: every wire contract between companion and dashboard (report body and
its models, the `commands` block, jobs claim/heartbeat/result, file moves,
resolve undos, machine settings, upgrade offers and package downloads,
telemetry switches), dashboard <-> mounted apps (b-roll/music gates, Cards
tunnel), web pages <-> the 8899 loopback, and version skew both ways.
Working tree as of HEAD 08b40eb plus the uncommitted changes.

Method: read both ends of each contract; probed `ReportIn` with the dashboard
venv (a throwaway script in the session scratchpad: 65 `file_moves_applied`
entries -> `too_long` 422; walked every model reachable from `ReportIn` for
raising constraints with no truncating validator); inspected CPython 3.12's
`platform._get_machine_win32` from the companion venv. Checked against
KNOWN_BUGS.md and docs/bug-hunt-2026-09-24.md: the 2026-09-25 bug-wire-1..7
are all fixed in the tree (lane caps truncate, standins_known sent empty,
answer queue locked, sub-app rotation drain, /verify arch, Latin-1 machine
header), so none of them is re-reported.

Looked at and found sound: report auth (token kinds, identity, account bar),
LG-1 strip order (before every write) and the two FIELDS tables, site
manifest `telemetry`/`features` encoding on both sides, the machine_settings
ask/accepts/answer cycle, jobs claim/heartbeat/result caps and the cancel
handshake, the locate batch cap, selection read/tick/untick, the 8899
Host/Origin vetting, the b-roll/music identity header strip, the Cards tunnel
routing by verified editor, the signed-record field lists, the ytdl client
config and yt-dlp version ranking.

Not covered: the Timeline Cards engine side of the agent protocol (another
repo), the Android app, and the macOS onboarding wizard's own internals.

### bug-wire-1 - Retrying file moves and parked undos hold the head of the offer queue, so newer commands are never delivered and lane A puts the files back
- Severity: medium
- Confidence: CONFIRMED (code read, both ends)
- Where: dashboard/src/ccsync_dashboard/db.py:6377-6410 (`pending_file_moves`, `ORDER BY m.id LIMIT 20`), db.py:6751-6777 (`pending_resolve_undos`, `ORDER BY id LIMIT 4`), db.py:6532-6540 (the retrying arm leaves `applied_at` NULL); companion/src/ccsync_companion/file_moves.py:65-67 (10 min, then hourly, 20 attempts); companion/src/ccsync_companion/sync/rclone_lane.py:3368-3383 (lane A excludes only moves the ledger knows about)
- What: the offer is "the oldest 20 targets with `applied_at IS NULL`". A `retrying` answer deliberately leaves `applied_at` NULL so the command is re-sent, and the companion answers each redelivery from its ledger until its next attempt time. So 20 retrying moves fill every slot of every reply for as long as they keep retrying (up to 20 attempts, roughly 20 hours, capped at 7 days), and move 21 onward is never offered. The lane A exclusion that protects an old path is fed ONLY by the companion's ledger, so an undelivered move has no exclusion at all. Resolve undos have the same shape with a limit of 4: a `parked` undo (its project is not open) stays non-terminal and can sit in front of an undo for the project that IS open, for weeks.
- Scenario: an admin moves 25 clips of a project an editor has open in Resolve, or the collector records a hand reorganisation of that project as per-file rows. Moves 1-20 are delivered; Resolve holds the files open, so each answers `retrying` and keeps answering. Moves 21-25 are never sent. Lane A's next pass finds those five originals on the editor's disk at the old paths, absent from the NAS, and uploads them back: duplicates at the old paths, the exact failure docs/FILE_MOVES.md exists to prevent. Moves 21-25 arrive only when moves 1-20 go `blocked`, about 20 hours later.
- Recommendation: order the offer so never-delivered targets come first (`ORDER BY t.delivered_at IS NOT NULL, m.id`), or do not count `retrying` targets answered in the last interval against the limit, or always include every undelivered target (they are small). Same for undos: undelivered first, and `parked` rows after the rest.
- Known: no. FILE_MOVES.md's "a lost reply costs one interval" assumes the queue drains.

### bug-wire-2 - File-move answers are unbounded on the companion, capped by a raising 64 on the dashboard, and lost for good when a report fails
- Severity: medium
- Confidence: CONFIRMED (probed `ReportIn` with 65 answers -> `too_long`; drain path read)
- Where: dashboard/src/ccsync_dashboard/api.py:9944 (`file_moves_applied ... max_length=64`, no truncating validator); companion/src/ccsync_companion/app.py:8930-8934 (`_file_move_results` drains the list), app.py:9042-9065 (`_relink_pending_moves` clears the ledger flag BEFORE queueing the answer); companion/src/ccsync_companion/reporter.py:1026-1033 (no cap), 1383-1388 (a failed POST does not requeue)
- What: (a) `file_moves_applied` is not one of the tolerant sections. Its `max_length=64` raises, and the companion sends whatever it has queued, with no cap. RES-10's "relinked after all" answers are queued in a burst: the moment a project is opened, `_relink_pending_moves` walks EVERY applied move still waiting for a relink (30-day window) and queues one answer per move it matches. (b) The answer list is drained when the payload is built and is not put back if the POST fails (timeout, a 5xx during a stage-verify-swap deploy, a 422). For ordinary answers that does no harm, because the dashboard re-sends the command and the ledger answers again. For the relink answer the loss is permanent: the ledger's `relink_pending` was cleared first and the dashboard row is already applied, so nothing ever asks again.
- Scenario: a hand reorganisation is recorded as 80 per-file moves in a project that was not open on an editor's laptop. All 80 apply with `relink_pending`. The editor opens that project and 80 answers are queued. The next report carries 80 entries and is refused with 422, so that report's lanes, alarms and transfers are lost, and every one of the 80 answers is gone. The project page shows "moved, Resolve not repointed yet" for all 80 for good, although Resolve was repointed. The same permanent loss follows a single answer that rode a report that timed out during a dashboard deploy.
- Recommendation: on the dashboard, give `file_moves_applied` (and `resolve_undo_applied` and `resolve_journals`) the same truncate-not-reject treatment as the other sections. On the companion, cap at 64 answers per report and carry the rest to the next one. Also on the companion, put drained answers back when the POST fails (or keep them until a 200 acknowledges them), or keep `relink_pending` in the ledger until the answer has been accepted, so the relink answer can be rebuilt.
- Known: related to the fixed bug-wire-1/bug-wire-6 of 2026-09-25 (same answer, different loss path); not recorded

### bug-wire-3 - A Mac's first install takes the channel's `current` package with no architecture check, so an Intel Mac is handed an arm64 companion
- Severity: high
- Confidence: CONFIRMED that no architecture is asked for or checked on this path; whether a customer has Intel Macs is the condition
- Where: installer/macos_bootstrap.sh:106 (`COMPANION_VERSION="current"`), :2398-2410 (download, sha256 and signature-presence checks only); dashboard/src/ccsync_dashboard/api.py:7375-7419 (`api_download_package` serves `current` for (kind, platform) with no arch); tools/release_macos.sh:683-699 (the release expects arm64 and only warns otherwise); the onboarding wizard's download of `macos/...?kind=onboard` (onboarding/tests/test_release_gates.py:105)
- What: REL-16 added the arch discriminator to the UPGRADE offer (`_arch_matches` in `_upgrade_info`), but the first-install paths never got it. The bootstrap and the dashboard's installer download ask for `macos/current`, check only that the bytes match the sha256 header, and install whatever arrived. The macOS companion and wizard are built arm64: the release script says so and warns on anything else. The same bootstrap already picks rclone's download by `uname -m`.
- Scenario: a new customer's editor on a 2019/2020 Intel iMac or MacBook Pro runs the installer. The arm64 companion downloads, passes the checks and is installed, but it cannot run ("Bad CPU type in executable"). The Resolve prefs step at macos_bootstrap.sh:1498 fails, and the editor is left with no working companion and nothing saying the hardware is the reason. The upgrade path in the report reply would have refused exactly this build.
- Recommendation: send the machine's arch with the package download (`?arch=$(uname -m)`), have `api_download_package` refuse (409, with a sentence) a record whose `arch` does not match, and have the bootstrap run `file`/`lipo -archs` on the download before installing it. Either publish a universal2 or x86_64 build, or state in the system requirements that Intel Macs are unsupported and have the installer say so before it starts.
- Known: REL-16 (FIXED for the upgrade offer only); the first-install half is not recorded

### bug-wire-4 - A Windows-on-ARM laptop reports `arm64` while running the x64 companion, so once records carry `arch` it is never offered an update
- Severity: medium (latent: it starts the day `-EmitKindExtras` / `CCSYNC_EMIT_KIND_EXTRAS=1` is turned on)
- Confidence: CONFIRMED (CPython 3.12.10's `platform._get_machine_win32` read from the companion venv)
- Where: companion/src/ccsync_companion/upgrade.py:157-176 (`arch_key` from `platform.machine()`); dashboard/src/ccsync_dashboard/api.py:6304-6323 (`_arch_matches`), 6528-6531; tools/release.ps1:600-606 (the Windows record's arch is the BUILD machine's, x86_64); installer/build_editor_package.ps1:140-142 and tools/publish_latest.py:177-183 (the opt-in)
- What: Python 3.12 on Windows answers `platform.machine()` with a WMI query for the CPU's NATIVE architecture. An x64 process running under emulation on an ARM64 Windows machine therefore reports `ARM64`, which `arch_key` turns into `arm64`. The Windows build is x64 only and is the only Windows build there is. `_arch_matches("x86_64", "arm64")` is False, so `_upgrade_info` offers nothing ("made for a different processor"), a pushed update is withheld and stored as `update_withheld`, and the machine stays on whatever it first installed, although the same build runs fine on that laptop under emulation.
- Scenario: a customer's editor on a Snapdragon X Windows laptop installs the companion with the installer, which works under x64 emulation. Once the vendor starts signing `arch` into records, every later release is withheld from that laptop, including security fixes and EULA updates, and the Packages page says it cannot take the build.
- Recommendation: for Windows, treat an x86_64 record as installable on arm64 (Windows 11 emulates x64), or report the process architecture instead of the CPU's (`struct.calcsize("P")`, `sysconfig.get_platform()` or `IsWow64Process2`) and keep the native CPU as a separate diagnostic field. Add a test that pins `arch_key()` when WMI answers ARM64.
- Known: REL-16 (the discriminator itself); this mismatch is not recorded

### bug-wire-5 - A Resolve project name over 256 characters gets every heavy report refused while its undo journal is among the newest 20
- Severity: low
- Confidence: PLAUSIBLE (both caps read; the longest project name Resolve accepts was not measured)
- Where: companion/src/ccsync_companion/resolve_journal.py:682-711 (`summaries` sends `project` uncapped; `id` is capped through the 80-character slug); dashboard/src/ccsync_dashboard/api.py:9641-9655 (`ResolveJournalIn.project max_length=256` raises, there is no truncating validator, and `resolve_journals` is not a tolerant section)
- What: a single journal whose `project` is longer than 256 characters fails `ReportIn`. That refuses the whole heavy report (lanes, alarms, presence) until the journal drops out of the newest 20, which can take weeks.
- Scenario: an editor gives a Resolve project a long descriptive title. CC Sync relinks a clip in it and writes a journal, and from the next heavy tick every heavy report from that machine is refused with 422. Light ticks still get through, so the machine looks alive, but its manifest, media tree and journals stop updating.
- Recommendation: cap `project` in the companion (`[:256]`) and give `ResolveJournalIn` the `_bound_to_field_caps` before-validator that the other report models have.
- Known: no
