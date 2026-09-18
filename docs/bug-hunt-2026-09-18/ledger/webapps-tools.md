# Ledger entry for KNOWN_BUGS.md (2026-09-18 fix pass, the webapps-tools group)

Written by the builder; the orchestrator copies it into `KNOWN_BUGS.md` and
bumps the versions. Nothing below was committed and no version was changed.

## CR-286 - the ninth hunt's webapps and tools: a cancel that could not be swept, a paste nobody measured, and a dry run that told an editor to delete their install (CR-286, 2026-09-18)

The 32 findings of `docs/bug-hunt-2026-09-18.md` that live under `broll/`,
`music/`, `ytdl/`, `server/`, `tools/`, `bench/`, `installer/` and
`onboarding/` - 13 medium, 19 low - fixed in the order ASSIGNMENTS.md gives
them, against `214869b` plus the first wave's ten highs. Every one carries a
regression test that fails on the unfixed source.

### CR-286A (broll-indexer-1) - the one editor-proxy producer that never got the frame-count check - FIXED (broll/indexer/tools/make_own_proxies.py, broll_index/ffmpeg_tools.py)

2026-09-17 (CR-281) added the third proxy-verification failure mode - "a few
frames short, decodes perfectly, Resolve refuses it as a proxy" - to the
indexer's browsing proxy and to the companion's ingest. `make_own_proxies.py`
was missed, and it is the one that produces EDITOR-GRADE `Proxy/<stem>.mp4`
from the companion's own `own_proxy_cmd`: files Resolve links directly. Its
`_bad()` checked decode errors and duration >= 97% only, and 18 frames at 30
fps is 0.6 s against a 1.8 s tolerance on a 60 s clip. Its stated use is a
sweep over backup trees (~6,700 clips), so a dropped NVENC session a few
frames early would have been verified clean, renamed into `Proxy/`, indexed
and lane-B'd to every editor - verbatim the Reproductive Rights incident the
check exists to end. `own_proxy_cmd` sets no `-r`, so the two counts are
comparable exactly as in `build_proxy`. The comparison itself is now ONE
predicate, `ffmpeg_tools.frames_match`, shared by both producers, so the open
question of a VFR tolerance (comp-broll-tiers-3) has one place to land
instead of three.

### CR-286B (broll-indexer-3) - the new frame check cost a second full network read of every original - FIXED (broll/indexer/broll_index/ffmpeg_tools.py)

`count_frames` runs `ffprobe -count_packets`, which demuxes the whole file,
and `build_proxy._bad()` ran it against the ORIGINAL for every clip.
`stage_proxy` and `_frames_source` exist precisely to stop that - their own
comments say "with source media on a 46 MB/s network share those reads
dominate the whole run ... one network read per file instead of three" - so
the check roughly doubled the NAS read load of a back-catalogue run with no
log line attributing the cost. The probe `build_proxy` already takes for the
timecode and the rate gives `duration * fps` for free, so the expensive read
now happens only when the PROXY's own packet count disagrees with it
(`expected_frames`, `FRAME_SLACK = 2`). Both-known-or-skip is unchanged, and
the argv is untouched - the parity tests and the companion's loader pin it.

### CR-286C (install-onboard-1) - a macOS dry-run uninstall ended "CCSync uninstall NOT complete" - FIXED (installer/macos_uninstall.sh, installer/tests/test_macos_site_values.sh)

CR-265's fix made the closing line conditional on `REMOVAL_INCOMPLETE`, and
the pre-existing "`$BIN_DIR` still exists" block sets that flag
unconditionally. A dry run deletes nothing, so the bin dir is of course still
there, so every dry run on an installed Mac ended with a red warning whose
own remedy is `rm -rf "$CCSYNC_LOCAL"` - at an editor who ran the script
precisely to change nothing. The "(dry run -- nothing changed)" sentence was
unreachable on any machine that has the app. The block is now gated on
`DRY_RUN`.

### CR-286D (install-onboard-2) - `-Full` on Windows said "removed" and "your identity is gone" without looking - FIXED (installer/windows_uninstall.ps1)

Section 4 re-reads the bin dir after its delete (CR-265); section 5's `-Full`
removal of the whole of `%LOCALAPPDATA%\ccsync` - which CONTAINS that bin dir
plus `syncthing-config`, the device identity - did not. PowerShell 5.1's
`Remove-Item -Recurse` deletes NOTHING when one child is locked, and section
1's `Stop-Process -Force` is never waited on, so a syncthing.exe still
holding a handle left the whole tree while the script printed "removed
%LOCALAPPDATA%\ccsync" and the paragraph telling the editor to send the admin
a NEW device ID. They reinstall, Syncthing comes up on the OLD id, and the
admin waits for a device that will never appear on the pending list - the
stuck-lane-C incident pointing the other way. New `Get-FullRemovalLeftovers`
(the twin of `Get-BinDirLeftovers`), the identity paragraph is printed only
when the identity really did go and is replaced by its opposite when it did
not, and the leftovers feed `Get-UninstallClosingAdvice` through a new
optional `-IdentityLeftovers`, so the verdict can no longer say "complete"
over a surviving device identity.

### CR-286E (music-1) - a cancel that landed between lease expiry and the next sweep wedged the batch in `running` for ever - FIXED (music/web/musicweb/routes_batches.py, broll/web/app/routes_batches.py)

`cancel` was the one batch route that did not call `expire_stale_leases`
first, and it decided "nobody holds this" on the truthiness of
`lease_expires_at` rather than on `lease_live`. A batch whose lease had run
out but which no request had swept took the request-not-kill branch, which
sets `cancel_requested = 1` and NULLs the lease while leaving
`state='running'` - a row `expire_stale_leases` can never touch again (its
predicate requires the column NOT NULL) and `claim` 410s for ever. The panel
kept drawing live work with a cancel button and no take-over button, and only
a second click cleared it, which nothing told the editor. Both halves fixed:
the sweep first, and the test is `state == 'queued' or not lease_live(batch)`.
The b-roll twin had the identical shape and moved with it.

### CR-286F (music-2) - every loopback 409 was reported as "another of your computers is still working on this batch" - FIXED (music/web/static/ingest.js, broll/web/static/ingest.js)

`broll_ingest.run()` answers 409 for three things of its own - this computer
is already indexing another batch, those tracks are no longer staged here,
and CR-253A's `staging_id_missing` ("reload the page and try again") - and
forwards the dashboard claim's 409 as a fourth. `miTakeOver` branched on
`e.status === 409` alone and discarded the body, so the one message that
names the action the editor must take was the one thrown away, and
`miRetryFailed` swallowed it entirely in a bare `catch { }` while toasting
that the tracks were queued. The companion's own sentence is now shown
whenever it sent one (`miRefusalText`, keyed on `reason`/`message`, never on
the prose), the "another of your computers" wording is kept for the claim's
own 409, and the retry toast says when this computer did not pick the tracks
up. b-roll's `ingestTakeOver` had the same blind branch and moved with it.

### CR-286G (regression-1) - CR-262C and CR-253A, from the same fix pass, made a reloaded music batch undispatchable by any button on the page - FIXED (music/web/static/ingest.js)

CR-262C made the dispatch unconditional and sends `staging_id: ''` when the
page no longer remembers the drop; CR-253A refuses exactly that request 409
`staging_id_missing` while this machine is still holding the staging entries
for those files - and `self._staging` is in-process and persisted, so a page
reload clears none of it. Both exits from the reload state were therefore
refused on the one computer that has the audio, and the only ways out were
cancel-and-re-drop or a companion restart. The guard is NOT dropped (it is
what stops a retry burning `MAX_ITEM_ATTEMPTS` on every track): the refusal's
body already names the staging id the companion holds, so `miDispatchLocal`
sends it straight back and retries once. Web-side only - no companion change
and no new wire field.

### CR-286H (server-tools-1) - an LGPL dependency conveyed to customers had no notice, and the generator that would catch it inventories developer venvs - FIXED (tools/gen_notices.py, docs/legal/THIRD_PARTY_NOTICES.md)

`tools/license_allowlist.toml` excuses `psycopg2-binary` (LGPL) for the
`dashboard-container` target on the written promise that "the notice, the
licence text, and a written offer" are tracked in
`docs/legal/THIRD_PARTY_NOTICES.md`. That file carried no psycopg2 row in any
of its five tables: the ONE gate that runs (`check_licenses.py --strict`)
passed because a human wrote a promise into a TOML file, and nothing checked
the promise. The deeper half is that `gen_notices.py` inventories the five
component VENVS and has no notion of the artefact a customer receives, so
even a regeneration would have printed the dev venv's 2.9.13 rather than the
2.9.12 the image installs. `CONTAINER_LOCKS` now scans
`dashboard/deploy/requirements.lock` itself: names and versions from the
lock, licence borrowed from whichever scanned venv holds the same package and
LABELLED as borrowed (`_licence_source`), unknown - never permissive - when
no venv holds it, and folded into the attention scan rather than into a
footnote. The file is regenerated: psycopg2-binary 2.9.12 now appears under
LICENCES NEEDING ATTENTION as `dashboard-container`.

### CR-286I (server-tools-2) - a b-roll publish whose drain merge failed still exited 0, and a test pinned that - FIXED (server/publish_db.py, server/tests/test_broll_drain.py)

The drain's second half runs AFTER the rename. When it fails (`database is
locked`, a container mid-restart) the code printed a WARNING with the
recovery command and fell through to `return 0`, so every scripted caller and
every `&&` chain was told the publish succeeded while the live index was
missing each clip the fleet had ingested since the source copy was pulled -
plus every `ingest_batches`/`ingest_items` row, which exist nowhere else
until the merge lands. `do_apply_drain` returns 1 for the identical failure
when it is the whole command. Now `RC_DRAIN_UNMERGED = 3`, distinct because 1
means "nothing was published" everywhere else in this CLI and the swap DID
happen; the WARNING text is unchanged.
`test_a_merge_that_fails_after_the_swap_names_the_bundle_and_the_command`
asserted `rc == 0`, i.e. the suite pinned the lie; it asserts the new code.

### CR-286J (ytdl-web-2) - the worker's "no room" refusal reintroduced the wrong sentence a vanished share earns - FIXED (ytdl/web/ytdlweb/worker.py, routes_api.py)

`_no_room_note` duplicates `_refuse_if_full`'s two numbers, its factor, its
floor and its cache invalidation, but not its TREE GUARD. A bind mount that
has gone away leaves its mount point on the container overlay, so
`disk_usage` answers with the overlay's couple of spare gigabytes and the job
failed with "there is only 2.0 GB free on the server where these clips go ...
Free some space" about a share with 900 GB on it - the exact sentence
CR-263a/ytdl-web-1 exist to stop an admin acting on, emitted from the
executor path instead of the press path. The tree test is factored out of
`_refuse_if_the_tree_is_gone` into `tree_is_gone` / `tree_missing_note`,
which return rather than raise (a worker thread cannot raise an
`HTTPException`), keep `_named_under_the_root` for CR-90, and answer False
for everything they cannot prove - including a `PROJECTS_ROOT` that is not
readable at all, which is a container whose mount has not arrived yet.

### CR-286K (ytdl-web-3) - the "no room" failure told the editor to press a button the page hides in exactly that state - FIXED (ytdl/web/static/app.js)

`renderRetry` offers `[ RETRY N FAILED ]` only when `failed > 0`, and
`_no_room_note` fires BEFORE any clip is attempted: `start_download` has just
written `dl_failed = 0`, `mark_pending` put every row back to `pending`, and
`_phase_download` returns before the loop. So no row is `failed`, `offer` is
false, the button is hidden - and so is `#dlnote`, which is gated on the same
expression - and `poll()` does not reload the manifest for a failed job while
`startDownload` has already hidden the review grid. The editor frees 500 GB
and has no control on the page; their only route back is a whole new search,
which is the YTDL-16 situation the button exists to end. `offer` now also
covers "phase is `failed` and the manifest has pending rows", and the button
reads `[ RETRY N CLIPS ]` in that case. The rows are deliberately NOT marked
`failed` server-side (the breaker path leaves them `pending` on purpose,
CR-263b).

### CR-286L (ytdl-web-4) - a pasted-links job got no free-space check at all, on either executor - FIXED (ytdl/web/ytdlweb/routes_api.py, worker.py)

YTWEB-9's guard lives in `start_download`, and a url job goes straight to
`downloading` from `create_url_job`; the worker's backstop is gated on
`config.LOCAL_DOWNLOAD and created_local`, and `YTDL_LOCAL_DOWNLOAD` is off
in the shipped fleet. So 40 links into a project with 6 GB left produced N
opaque per-clip ENOSPC failures and a breaker note about identical failures -
precisely the symptom one sentence replaced, still live for the paste door.
Both halves: `create_url_job` calls `_refuse_if_full` when the server is the
executor for that paste, and `_no_room_note` treats a url job as one the
press did not measure. The refusal takes the caller's own button (`press`
parameter) because the paste page's control is GET LINKS, not DOWNLOAD - the
same class of defect as CR-286K one screen over.

### CR-286M (ytdl-web-5) - when the share vanished but the host had room, the download SUCCEEDED into the container overlay - FIXED (ytdl/web/ytdlweb/worker.py)

`_refuse_if_full` consults the tree guard only on the way to a disk_full
refusal, by design ("a download that fits is a download that fits"). On a
host with 200 GB free and a vanished bind mount the check passes,
`ensure_outdir` makedirs the mount point's children, yt-dlp writes there, and
`db.ledger_add` records every clip at a NAS-relative path with no file behind
it - `phase='done'`, no notice, no refusal. The clips are lost on the next
container recreate, and every later search or paste of those video ids is
skipped as "the fleet already has that video". `_phase_download` now asks
`tree_missing_note(job)` unconditionally before anything is fetched and fails
the job with the share's own sentence.

### CR-286N (broll-2) - a published `broll.db` could be unreadable by the deployed dashboard, and the publish neither checked nor warned - FIXED (server/publish_db.py)

`PRAGMA user_version` is stamped 12 by this week's indexer. A dashboard in
the field on 0.7.34..0.7.48 carries `CURRENT_SCHEMA_VERSION = 11` and
`ensure_schema` raises deliberately for a file newer than the app, which the
mount turns into a DEGRADED `/broll` - the whole search UI off, with the
reason only in the container log. The reverse skew is worse in its own way:
`ensure_schema` runs at mount time, so an OLDER file dropped under a running
newer container is never stepped and every ingest push 500s on `no such
column` until somebody restarts it. `publish_db.py` had no notion of a
version at all. It now reads the staged snapshot's version locally and the
live file's through the container - IN THE SAME `container_exec` the row
counts already use, because this chain is an ordered script of container
calls - and refuses either skew with the action that fixes it
(`--allow-schema-skew` to override). A version either side cannot read never
refuses.

### CR-286O (broll-3) - the archive top slot was matched by an exact stem string, with no normaliser - FIXED (broll/web/app/routes_api.py)

CR-90's rule is that a path from one platform is not `==` a path from
another. `insert_target_detail` compared `os.listdir()` bytes on the NAS
against a stem the DB holds, raw: a name a Mac's rclone upload spelled NFD
does not compare equal to the NFC stem, `len(matches)` is 0, `original_rel`
becomes null, and the clip silently degrades to a preview-only insert - the
archive-task-#23 path, for a clip that does have an original, which is also
the shape proxy-tiers-2 turns into a bad stand-in ledger row. Both sides now
go through `unicodedata.normalize("NFC", ...)` for the STEM TEST only; the
join that follows keeps the entry's own bytes, where the truth is. Two
candidates differing only by normalisation still degrade, but say so in the
log rather than in silence.

### CR-286P (broll-4) - `edit_proxy_rel` could name the preview itself - FIXED (broll/web/app/routes_api.py)

The editing proxy is derived as `<preview.parent>/<preview.stem>.mov` with no
check that it is a different file. `build_archive.preview_source` falls back
to the TOP SLOT for an audio-only clip and keeps its suffix, so a `.mov`
preview was advertised as its own editing proxy: the companion records
`upgrade_rel` = the file it has already downloaded, runs a background upgrade
thread that re-fetches it and links a clip's preview as its own proxy, and
keeps a stand-in ledger row for a tier that does not exist. One inequality
guard.

### CR-286Q (broll-5) - the zero-byte guard covered only the declared editing proxy, not the preview the server itself requires - FIXED (broll/web/app/ingest_batches.py)

"A zero-byte file is a transfer that died, not an upload" applies verbatim to
`slots.proxy` and `slots.original` - and those are the files this route adds
to `required` itself with `declared.setdefault(rel, None)`, i.e. with NO
declared size, so the size-mismatch arm (`want is not None`) skips them. A
0-byte preview from a killed transfer therefore passed presence AND size, and
the clip went live with the one file the search UI plays being empty. The
rule is now `actual == 0` for every required entry, and deliberately still
not "a size must be declared": a queue entry rebuilt after a restart
legitimately carries no size and would 409-loop for ever.

### CR-286R (broll-indexer-2 = proxy-tiers-7) - the column that decides an offline clip's LENGTH was read from a field this module calls a lie - FIXED (broll/indexer/broll_index/ffmpeg_tools.py)

Migration 012's own comment says `frames` is "what phase 3 writes into the
interchange file that creates an OFFLINE media-pool clip ... a wrong or
absent frame count is a clip of the wrong length on every remote machine".
Fifty lines below `probe_video`, `count_frames_cmd` explains that `nb_frames`
"is absent or a lie in exactly the cases that matter (an mp4 written by a
killed encoder still carries the count it intended)" - and `probe_video`
filled the column from `nb_frames` with nothing cross-checking it. It is now
checked against `duration * fps`, which the same probe already has, with one
frame plus 1% of slack for a rounded container duration and an averaged VFR
rate; a claim that fails is recorded as NULL, which every reader already
handles and which is the honest answer. Deliberately NOT `count_frames`,
which would be CR-286B's cost moved onto the probe stage.

### CR-286S (broll-indexer-4) - a probe that yields no duration crashed the proxy stage with a bare TypeError - FIXED (broll/indexer/broll_index/pipeline.py)

`probe_video` answers `duration_s = None` for a raw elementary stream, some
MPEG-TS and a growing recording; `stage_probe` guarded only on a missing
codec, so such a row reached `probed` and `stage_proxy` passed the None into
`build_sprite`/`build_poster` and `stage_frames` into `fill_gaps` -
`TypeError: unsupported operand type(s) for //: 'NoneType' and 'float'` in
the row's `error` column instead of the diagnosis an operator can act on.
Parked at `skipped` with its own sentence, like the other two. It is
structurally distinguishable from both: `skipped_for_length` requires a codec
AND a duration, and the audio-only arm has no codec, so neither reads this
third kind as itself - and `build_archive.eligible` (codec IS NULL AND
duration_s IS NOT NULL) does not ship it.

### CR-286T (broll-indexer-5) - `fix_proxy_timecode` verified that the remux had A timecode, not the one it had just decided on - FIXED (broll/indexer/fix_proxy_timecode.py)

Since audit F6 the VALUE is the whole point of this tool: a colon and a
semicolon at the same numbers are different absolute frames, and writing the
wrong one is what makes Resolve refuse the proxy. `plan()` compares
`read_timecode(preview) == wanted`; `remux()` asserted only that some
timecode survived, so a container that normalises the form would have every
file reported "fixed" and replaced while still carrying the form `plan()`
rejected, re-planned on the next run, for ever, with the run exiting 0 each
time - "green while dead" for a repair sweep whose whole output is a count.
The mp4 tmcd box stores a drop-frame FLAG rather than a separator, which is
exactly where that can happen silently. Now compared, and the two faults
("dropped the timecode", "wrote X, not Y") stay distinguishable in the
summary.

### CR-286U (install-onboard-3) - the macOS uninstall test pinned the verdict function, not the code path that sets its argument - FIXED (installer/tests/test_macos_site_values.sh)

The closing-verdict case extracts `closing_verdict`, forces `DRY_RUN=0` and
calls it with a hand-picked argument, so the one thing CR-265 changed about
the script's FLOW - which branch a real run reaches - was untested, and
CR-286C was green in CI. A new case runs section 3 WHOLESALE over a populated
fake tree with `DRY_RUN=1` and reads the verdict the section computes: no
"NOT complete", no "remove it by hand", no past-tense identity claim, and the
tree still on disk afterwards.

### CR-286V (install-onboard-4) - `_same_dashboard` compared hostnames only, so two deployments on one host shared a cache - FIXED (onboarding/steps.py)

Both URLs were reduced to `urlparse(...).hostname`, so `nas:8480` and
`nas:8481` - a customer's staging and production container on one NAS, or a
move from the container port to a Funnel port - counted as one dashboard. The
other deployment's cached `canonical_prefix` and `tree_name` then went onto
the bootstrap's argv, where they BEAT its own `Get-SiteValue` fetch (which
only runs when the flag is empty): the wrong drive letter and the wrong
folder name, which is the exact failure the cache guard was written to stop,
one level down. Only a PROVEN port mismatch refuses, and only an EXPLICIT
port counts - a bare host in the cache and `https://host:8480` this run are
the same deployment spelled two ways, and the normaliser's scheme guess is a
guess.

### CR-286W (install-onboard-5) - a macOS dry run claimed, in the past tense, that the Syncthing identity was deleted - FIXED (installer/macos_uninstall.sh)

The "that included the Syncthing identity in ... A reinstall generates a NEW
device ID" warning sat inside the `-d "$CCSYNC_LOCAL"` block gated only on
`REMOVAL_INCOMPLETE = 0`, which is still 0 at that point in a dry run. An
editor checking what the uninstaller would do mails the admin "my device ID
has been reset"; the admin removes and re-invites a device whose id never
changed. The sentence moved into the real-removal branch, and the dry run has
its own "would also remove ..." line.

### CR-286X (music-3) - the drop preview minted names that ignore every name already promised to an unlanded item - FIXED (music/web/musicweb/ingest_batches.py)

`precheck` called `allocate_name(..., reserved=set())` while the real
allocation in `write_item_result` passes `reserved=reserved_names(conn)` -
every `dest_name` held by an item of any batch that has not landed. The
preview's collision set was a strict subset of the real one, and the two
answered differently for exactly the case the reservation ledger exists for:
editor A's batch in flight holding `Theme.mp3`, editor B told their file
keeps its name and then finding `Theme (2).mp3`. Reading the ledger is not
reserving, so the docstring's property is intact; the set is copied because
`allocate_name` mutates it per item.

### CR-286Y (music-4) - `make_proxies --dry-run` died on the files the real run survives, and over-counted the ones it cannot decode - FIXED (music/indexer/music_index/proxies.py, make_proxies.py)

`_ffprobe` documents "{} if unreadable" and caught only `ValueError` from
`json.loads`; `subprocess.run` still raised `TimeoutExpired` (120 s, a
truncated `.aac`) and `OSError` out of it. Every real-run caller is inside
`build_all.one`'s blanket `except Exception` (one FAILED row); the
`--dry-run` branch has no guard at all, so the estimate died with a traceback
and no summary, several hundred files in, over a library the real run
completes. `decoded_duration` had the identical unguarded shape with a 900 s
timeout. Both guarded. Separately, `source_info` answers `{}` for a file with
no audio stream and `is_pointless({})` is False, so the dry run counted it
BUILT with duration 0 while the real run raises "no decodable audio stream"
and counts it FAILED: it is FAILED in both now, because an estimate that
promises proxies the run cannot make is worse than no estimate.

### CR-286Z (server-tools-3) - `tailscale status --json` was decoded with the console codec - FIXED (server/check_health.py)

`text=True` with no `encoding=` decodes tailscale's UTF-8 JSON with
`locale.getencoding()` - cp1252 here, cp950 on a Traditional-Chinese install
- and every peer name is in that JSON. One non-ASCII machine name raises
`UnicodeDecodeError` inside `subprocess.run`, which the broad `except` at the
next line reports as "skipped -- `tailscale status --json` failed": check 2b,
the DERP-vs-direct probe that matches what an editor experiences, silently
stops being performed and the health run still exits 0. Same class as the
`git_out` fix in e050413, which was made one file over and only there.

### CR-286AA (server-tools-4) - bench's rclone readback decoded with the console codec, and its decode failure was not caught - FIXED (bench/ccbench/runners/_rclone_common.py, base.py, syncthing.py, iperf3.py)

`rclone lsjson -R` emits every remote path, and this fleet's vault holds
`母母女子` and `Matej Šimalčík`. `remote_listing` caught only
`TimeoutExpired`/`OSError`, so the `UnicodeDecodeError` - a `ValueError` -
escaped the function that documents `None` as its failure answer and took the
run with it. Both halves matter and both are done: `encoding="utf-8",
errors="replace"` on all five subprocess reads in the runners, and the except
widened to `ValueError` - with the replacement characters alone,
`verify_upload` would have reported every file of a transfer that worked as
missing.

### CR-286AB (server-tools-5) - one absent guide suppressed the licence agreement as well - FIXED (server/install_dashboard_app.py, server/tests/test_bug_hunt_2026_09_11b_server_tools.py)

`ship_dashboard_docs` built `missing` from `SHIPPED_DOCS` and
`SHIPPED_DOC_TREES` together and returned False for any member, so after
dash-core-6 promoted `EDITOR_SETUP.md` into `SHIPPED_DOCS` a hand-trimmed
bind-mode checkout deployed successfully while shipping NO documents at all -
including `legal/`, the EULA the first-run wizard gates on. `/setup` told
every editor no licence agreement is included in this build and the operator
was pointed at a guide. Ship what is present, NOTE what is not, refuse only
for the legal tree. CR-265's own test asserted the all-or-nothing refusal; it
now asserts the saying half, which was the fix, and that the licence
agreement still ships.

### CR-286AC (tests-6) - three copies of the b-roll schema and migrations, and no test that they are the same - FIXED (broll/indexer/tests/test_bug_hunt_2026_09_18_webapps_tools.py)

The twelve migration scripts exist in three copies and `schema.sql` in two,
each suite testing only its own. Worse than the hunter knew: both
`broll_index/migrate.py` and `broll/web/app/db.py` resolve REPO-ROOT FIRST,
so in a checkout - which is what every test run is - the bundled copies are
exercised by no test at all, and drift would show up only in a deployed
container or an installed package. One test hashes the SQL of every copy,
comments and blank lines stripped (the bundled copies carry a five-line
"kept in sync here" header, so a byte comparison fails on day one and would
have to be disabled, which is how three copies stay unwatched), and names the
file that drifted.

### CR-286AD (ytdl-web-6) - any fleet-credentialled editor could claim another editor's job - DECLINED by the owner (2026-09-18)

`claim` never compares `editor` with `job['created_by']`, so once a lease
has lapsed any live companion in the fleet may take the work order (the
owner's project label, term dir and clip list) and download it. The hunter
and the verifier read that as a leak; the builder closed it with a 410
`not_your_job` and reversed the test that pinned the old contract
(`test_local_download.py::test_a_second_editor_may_claim_once_the_lease_has_run_out`,
"until the SERVER has taken the job back, a live companion may pick it up").
The owner ruled the same evening: "I want the old behaviour back" - a
colleague's machine finishing an expired job is the DESIGN, not a leak, in
a studio whose editors share one archive. The guard and the reversed tests
were removed by the orchestrator before the gate; the route is exactly as
0.7.49 shipped it. If the studio ever has editors who must not see each
other's jobs, this is the four-line guard to put back.

### CR-286AE (ytdl-web-7) - `db.py` defined `_column` twice - FIXED (ytdl/web/ytdlweb/db.py)

Two module-level `def _column(row, key)`, at 206 and 976; the second shadowed
the first for every caller in the file, including the fourteen readers
written against the first. Behaviourally identical today, so nothing was
broken - and a future tightening of either would have been a silent no-op for
half the module. One definition, kept where the first readers are.

### CR-286AF (ytdl-web-8) - the "download on this computer was unticked" sentence said "this search" on a pasted-links job - FIXED (ytdl/web/static/app.js)

regression-26's sentence serves all three callers of `dispatchLocal`, one of
which is `runUrls` and another the review grid's DOWNLOAD on a url job (the
reachable path: a paste submitted unticked, the box ticked afterwards, then
RETRY FAILED). The editor was told to change a setting on a screen they did
not use. "this job ... before the next one".

### CR-286AG (proxy-tiers-3, OWED from companion-media) - the archive folder the server could not READ answered the same shape as "this clip has no original" - FIXED web half (broll/web/app/routes_api.py)

`insert_target_detail` discovers the original and the editing proxy by
listing the archive folder inside the container. An OSError - the dataset
unmounted, an SMB hiccup, `BROLL_DATA_ROOT` wrong after an image update - was
swallowed into `entries = []`, and a stat that could not be taken into "no
editing proxy", which is byte for byte the answer for a clip that genuinely
has neither. Ten minutes of that turns every Send to Resolve in the window
into a preview-only insert with a stand-in ledger row whose `is_stale`
retirement can never fire, and the damage outlives the outage for ever on
projects nobody re-checks.

The insert object now carries `known`, and only a listing or a stat that
RAISED makes it false: an empty directory is an answer, and is still
`known: true`. Both failure paths log which path they could not read. The
keys stay PRESENT and null on that path, deliberately - an ABSENT
`preview_rel`/`edit_proxy_rel` means "use the stem convention" to the
companion, which re-creates the identical wrong answer by another road. The
companion half is CR-284G and is already in the tree, so the pair is
complete; the key is optional on the wire and a companion that has never
heard of it behaves exactly as before.

Tests: `broll/web/tests/test_insert_target.py::test_a_missing_archive_directory_answers_without_a_proxy`
(the new key, plus that the two null keys are still there) and
`::test_the_preview_only_fallback_reports_no_original` (a JUDGED null is
`known: true`, and `original_rel` is present-and-null so no reader may fall
back to the posted `rel_path`, which in that case IS the preview).

### CR-286AH (comp-broll-tiers-3, OWED from companion-media) - the frame-count comparison's open question is answered - FIXED (broll/indexer/broll_index/ffmpeg_tools.py, docstring only)

`frames_match` is the one predicate `build_proxy` and `make_own_proxies` both
use (CR-286A), and its docstring said the VFR tolerance was still open. The
companion-media builder settled it in the same pass by giving the companion's
ingest the EXACT twin of this rule, so all three producers refuse the same
file. The docstring now records the answer and keeps the standing rule: a
tolerance introduced later belongs here and in the companion's twin in the
SAME change. No code change - the behaviour was already exact.

### CR-286AI (tests-1, OWED from companion-media) - the two release scripts now require a real ffmpeg, where there is one - FIXED (tools/release.ps1, tools/release_macos.sh)

Twenty media-job tests - the three Timeline Cards recipes, whose ffmpeg argv
another repo's page reads byte for byte, plus proxy_gen's `.partial` +
atomic-rename rule - skipped silently on every CI and release runner, and
pytest exits 0 on a skip, so the argv could break and the build would still
be published. `CCSYNC_REQUIRE_FFMPEG=1` turns those skips into failures and
the companion suite has read it since the first wave; neither release script
set it.

Both do now, beside the `CCSYNC_REQUIRE_RCLONE=1` they have always set - and
GUARDED, which is the part worth the comment. rclone is a prerequisite of the
lane tests; ffmpeg is not a prerequisite of building the companion, and a
release that cannot be cut on a rig without `brew install ffmpeg` is a worse
failure than the hole it closes. So the variable is set only when
`Get-Command ffmpeg` / `have_cmd ffmpeg` finds one, and its absence is a
WARNING in the run log rather than a silent skip or a refusal. The Windows
half restores the previous value in the existing `finally`, so the release
script does not leak the pin into the shell it was run from.

Test: `tools/tests/test_release_scripts.py::TestTheMediaJobTestsAreRequiredWhereFfmpegExists`
(five cases: each script sets it, each script warns rather than fails without
one, the Windows restore, and rclone still required).

### CR-286AJ (dash-release-jobs-3, taken from the dashboard builder) - the "only upload what changed" skip could not see a half-uploaded asset - FIXED (tools/publish_feed.py)

The 2026-09-11 speed-up reads the release's own asset list and skips any
planned file the release already holds at the same NAME and SIZE. It never
read the asset's `state`. A GitHub asset whose upload was interrupted keeps
its declared name and size while sitting in `starter`, and a `starter` asset
serves nothing usable - so what used to heal itself on the next release
(before the speed-up every run pushed everything with `--clobber`) is now
skipped for ever, because nothing downstream ever compares the published
bytes against the record's sha again. `fresh_key` protects only the one
package this run signed, not the other three artefacts or the older records
in the mirror. The outcome is fail-closed - a customer's dashboard refuses
the bytes with `FeedHashMismatch` and shows it as `last_error` on its feed
page - but permanent and self-inflicted, which is why the verifier put it at
low rather than refuting it.

`published_assets` now asks for `state` and `digest` alongside `size` in the
SAME `gh` call (this path is pinned verb for verb by the feed tests, and a
second round trip would be a change to every one of them), and
`_asset_is_held` decides: the size still has to match, the asset has to be
`uploaded`, and where GitHub offers a `digest` the local bytes have to hash
to it - which is the check the customer's dashboard will make anyway, made
before the skip instead of after the release. Every "cannot tell" answers
False and re-uploads: a missing digest, an older `gh` that sends no state at
all, a stat that raised. That is the pre-2026-09-11 behaviour, which costs
bandwidth and nothing else.

Tests (`tools/tests/test_publish_feed.py`, five new or extended cases):
`::test_an_interrupted_upload_is_not_mistaken_for_a_published_asset` - with
its CONTROL, an `uploaded` asset of the same size still being skipped,
without which the case passes on the old code for the wrong reason;
`::test_the_asset_list_is_asked_for_the_state_and_the_digest` (a field nobody
asks for cannot be read, and still one `runner(` call);
`::test_a_digest_the_bytes_do_not_match_is_re_uploaded` both ways;
`::test_a_gh_that_sends_no_state_uploads_everything`; and the existing
`::test_assets_the_release_already_holds_are_not_re_uploaded`, whose FakeGh
now answers state and digest.

### CR-286AK (regression-7 = tests-4, taken from the dashboard builder) - the neutered test that was dropped from the 09-11b pass with no fix, no decline and no ledger entry - FIXED (music/web/tests/test_bug_hunt_2026_09_11_music.py)

`test_the_force_docstring_describes_what_actually_settles_a_batch` grepped
`musicweb` for a production `apply_for_track(..., force=True)` caller and
`pytest.skip()`d if it found one - so the guard switched itself off exactly
when the thing it guards happened, invisibly, because a skip in a suite of
149 is invisible. tests-4 reported that in the 09-11b hunt and is the ONE id
of that hunt's 154 with neither a fix nor a recorded decline anywhere, which
is regression-7.

Both branches assert now, and the assertion is about what the docstring must
then SAY: with no production caller, `force` is a test-only parameter and the
docstring has to say so ("only the tests use it today") and must not claim
`release` passes it; with one, that sentence has to be gone and the caller
named. `_settle_scores` - the thing that actually clears the stale marker -
is asserted in both worlds. Checked by mutation both ways: neutering the
docstring fails it, and adding a `force=True` caller to `routes_fleet.py`
fails it too (it used to skip).

While in that file: `::test_the_page_only_says_running_when_the_companion_claimed_it`
pinned `batch_uid`/`staging_id` as literals INSIDE `miRetryFailed`, which
CR-286F/G moved into the shared `miDispatchLocal`. It now asserts the same
three properties across both halves (the path and the dispatch call in the
button, the body fields in the helper, 202 still the only "running"). This
was a real break my own fix introduced and it would have been red in the
central gate: the full `music/web` suite is 615 passed / 2 skipped now.

### CR-286AL (test hygiene, taken from the dashboard builder) - two indexer tests read the developer's own environment and answered differently in the gate - FIXED (broll/indexer/tests/test_cli_local_backend.py, test_indexer_backend_config.py)

`broll_index.config`'s indexer block resolves `local_cache_dir`, `llama_server_path` and
`dashboard_url` as `_env(NAME) or raw.get(...)`, i.e. the environment BEATS
the config file. This rig has `BROLL_LOCAL_CACHE_DIR` set machine-wide for
the real local-VLM cache, so
`test_indexer_paths_default_empty_and_read_from_config` asserted the config
file's value against the developer's own environment, and
`test_doctor_reports_gpu_tier_and_missing_runtime` had `doctor` resolve to
that directory, find the models already downloaded and print the opposite of
"NOT downloaded yet". Both failed in the central gate and passed in the shell
of whoever wrote them, which is the worst shape a test can have: it makes the
gate look wrong.

The config test deletes the three names itself. The CLI file gets an AUTOUSE
fixture instead, because the exposure is `_write_config`'s and every case in
that file calls it. `test_env_overrides_win_over_config_yaml` is unaffected -
a fixture runs before the test body, so its own `setenv` still wins.
Confirmed by running the two files three ways (as-is on this rig, with the
variable forced to the rig's value, and with it unset): 18 passed in all
three, where before it was 16 passed / 2 failed with the variable set.

### Verification

Run as CLAUDE.md prescribes, from each component directory.

- broll-indexer-1 -> `broll/indexer/tests/test_bug_hunt_2026_09_18_webapps_tools.py::test_make_own_proxies_checks_the_frame_count` (+ `::test_a_good_proxy_still_lands`)
- broll-indexer-3 -> same file `::test_a_proxy_whose_length_is_right_costs_no_second_read_of_the_source`, `::test_a_suspect_proxy_still_pays_for_the_real_count`, `::test_the_expected_count_comes_from_the_probe_and_not_nb_frames`
- install-onboard-1 -> `installer/tests/test_macos_site_values.sh` ("a dry run ends with the nothing-changed sentence", "a dry run asks nobody to delete anything")
- install-onboard-2 -> `installer/tests/Test-BinDirLeftovers.ps1` ("a tree the delete could not clear is reported", "a -Full run that left the identity behind does not end 'complete'", "a -Full run that removed nothing never claims it did", "the -Full leftovers are printed where an editor can read them")
- music-1 -> `music/web/tests/test_bug_hunt_2026_09_18_webapps_tools.py::test_a_cancel_after_the_lease_died_finalises_the_batch`, `::test_a_cancel_never_leaves_a_row_no_sweep_can_reach`, `::test_a_cancel_on_a_live_lease_still_only_asks`; b-roll twin in `broll/web/tests/test_bug_hunt_2026_09_18_webapps_tools.py::test_a_cancel_after_the_lease_died_finalises_the_batch`
- music-2 -> `music/web/tests/test_bug_hunt_2026_09_18_webapps_tools.py::test_the_companions_own_refusal_is_what_the_editor_is_shown` (node-driven, skips where node is absent)
- regression-1 -> same file `::test_a_dispatch_that_lost_its_staging_id_adopts_the_one_the_companion_names`
- server-tools-1 -> `tools/tests/test_gen_notices.py::test_the_container_lock_is_licence_scanned_and_flagged` (+ `::test_a_hash_pinned_lock_is_read_as_names_and_versions`, `::test_an_absent_lock_is_not_an_exception`, `::test_a_locked_package_no_venv_holds_is_unknown_not_permissive`)
- server-tools-2 -> `server/tests/test_broll_drain.py::test_a_merge_that_fails_after_the_swap_names_the_bundle_and_the_command` (now asserts `RC_DRAIN_UNMERGED`)
- ytdl-web-2 -> `ytdl/web/tests/test_bug_hunt_2026_09_18_webapps_tools.py::test_the_workers_no_room_note_names_the_lost_share_not_a_full_disk`, `::test_a_present_tree_still_earns_the_full_disk_sentence`
- ytdl-web-3 -> same file `::test_a_job_that_failed_before_any_clip_still_offers_the_retry`
- ytdl-web-4 -> same file `::test_a_pasted_job_is_measured_at_the_press`, `::test_the_workers_backstop_covers_a_paste_with_the_flag_off`
- ytdl-web-5 -> same file `::test_a_vanished_share_stops_the_download_even_when_there_is_room`, `::test_a_root_that_cannot_be_read_is_never_called_gone`
- broll-2 -> `server/tests/test_bug_hunt_2026_09_18_webapps_tools.py::test_publishing_a_newer_schema_than_the_deployed_app_is_refused` (+ the older-schema, unreadable-version and one-exec cases)
- broll-3 -> `broll/web/tests/test_bug_hunt_2026_09_18_webapps_tools.py::test_an_nfd_top_slot_is_still_found_beside_an_nfc_preview`
- broll-4 -> same file `::test_a_mov_preview_is_not_its_own_editing_proxy`
- broll-5 -> same file `::test_a_zero_byte_preview_does_not_take_the_clip_live`, `::test_a_preview_with_bytes_still_goes_live`
- broll-indexer-2 -> `broll/indexer/tests/...::test_a_frame_count_the_duration_contradicts_is_not_recorded`, `::test_probe_video_uses_the_checked_frame_count`, `::test_a_frame_count_nothing_can_check_is_left_alone`
- broll-indexer-4 -> same file `::test_a_clip_with_no_duration_is_parked_rather_than_crashing`, `::test_the_parked_row_is_not_mistaken_for_an_over_length_clip`
- broll-indexer-5 -> same file `::test_the_remux_verifies_the_value_it_decided_on`, `::test_a_remux_that_kept_the_value_is_not_an_error`
- install-onboard-3 -> `installer/tests/test_macos_site_values.sh` (the section-3 case above; it is the test)
- install-onboard-4 -> `onboarding/tests/test_bug_hunt_2026_09_18_webapps_tools.py::test_two_dashboards_on_one_host_are_not_the_same_deployment` (+ the three control cases)
- install-onboard-5 -> `installer/tests/test_macos_site_values.sh` ("a dry run does not claim the device identity is gone")
- music-3 -> `music/web/tests/test_bug_hunt_2026_09_18_webapps_tools.py::test_the_precheck_preview_honours_a_name_an_unlanded_item_holds`
- music-4 -> `music/indexer/tests/test_bug_hunt_2026_09_18_webapps_tools.py` (all four cases)
- server-tools-3 -> `server/tests/test_bug_hunt_2026_09_18_webapps_tools.py::test_the_tailscale_status_read_names_its_encoding`
- server-tools-4 -> same file `::test_every_bench_subprocess_read_declares_utf8` (4 params), `::test_the_rclone_listing_returns_none_on_a_decode_failure`
- server-tools-5 -> same file `::test_an_absent_guide_does_not_withhold_the_licence_agreement`, `::test_an_absent_legal_tree_is_still_fatal`, and the rewritten `test_bug_hunt_2026_09_11b_server_tools.py::test_a_missing_editor_setup_is_named_and_does_not_stop_the_ship`
- tests-6 -> `broll/indexer/tests/...::test_the_three_migration_copies_hold_the_same_sql`, `::test_the_two_schema_copies_hold_the_same_sql` (a DRIFT GUARD: it passes today by construction and fails the moment one copy is edited alone)
- ytdl-web-6 -> DECLINED by the owner; guard and tests removed, `test_local_download.py` restored to HEAD
- ytdl-web-7 -> same file `::test_the_db_module_defines_column_once`
- ytdl-web-8 -> same file `::test_the_unticked_note_does_not_call_a_paste_a_search`
- proxy-tiers-3 (OWED in) -> `broll/web/tests/test_insert_target.py::test_a_missing_archive_directory_answers_without_a_proxy`, `::test_the_preview_only_fallback_reports_no_original` -> both fail with the `known` key removed
- comp-broll-tiers-3 (OWED in) -> docstring only; `broll/indexer/tests/test_bug_hunt_2026_09_18_webapps_tools.py` still pins the EXACT behaviour the sentence now describes
- tests-1 (OWED in) -> `tools/tests/test_release_scripts.py::TestTheMediaJobTestsAreRequiredWhereFfmpegExists` (5 cases) -> fails on both scripts at HEAD
- dash-release-jobs-3 (taken in) -> `tools/tests/test_publish_feed.py` five cases -> all five fail on the unfixed `publish_feed.py`
- regression-7 / tests-4 (taken in) -> `music/web/tests/test_bug_hunt_2026_09_11_music.py::test_the_force_docstring_describes_what_actually_settles_a_batch` -> mutation-checked both ways (neuter the docstring, add a production `force=True` caller); it SKIPPED silently before
- test hygiene (taken in) -> `broll/indexer/tests/test_cli_local_backend.py`, `::test_indexer_paths_default_empty_and_read_from_config` -> 2 failed with `BROLL_LOCAL_CACHE_DIR` set before the fix, 18 passed with it set, unset and forced after

Every one was run against the reverted source and fails there (tests-6 and
`test_a_suspect_proxy_still_pays_for_the_real_count` excepted, and said so
above: both are guards against a regression rather than proofs of a defect).

### Not fixed
- none. All 32 findings in the group are fixed.

### OWED TO ANOTHER GROUP
- DISCHARGED, and recorded above as CR-286AG / CR-286AH / CR-286AI: the three items companion-media owed ME (the `known` key on the insert object, the `frames_match` docstring, and `CCSYNC_REQUIRE_FFMPEG` in the two release scripts). Nothing is owed back to them for any of the three.
- dashboard: `.github/workflows/ci.yml`: add `python tools/gen_notices.py --check` beside the `check_licenses.py --strict` steps (server-tools-1's third half; `tools/` is mine, the workflow is not). CAVEAT the orchestrator must weigh: `--check` renders from the COMPONENT VENVS on the machine it runs on, so it can only pass in a job that installs every component lock; anywhere else it would fail for reasons that have nothing to do with the notices. Either put it in the strict/all-locks job, or narrow `--check` to the `dashboard-container` table first. The file is regenerated in this pass, so it is current for THIS rig's venvs. Either side deploys first; nothing ships.
- companion-media: `companion/src/ccsync_companion/ffmpeg_tools.py` (`probe_video`, the `"frames": _int_or_none(video_stream.get("nb_frames"))` line, ~567): apply the same `duration * fps` cross-check the indexer now applies (CR-286R), or the two producers of the same wire field disagree about how confident it is. The indexer's helper is `_plausible_frames`; copying it is four lines and needs no import. Either side first: the field is optional on read and a NULL is what every reader already handles.
- companion-media: if comp-broll-tiers-3 settles on a TOLERANCE for the proxy/original frame-count comparison, it must be mirrored in `broll/indexer/broll_index/ffmpeg_tools.frames_match` (one function, used by `build_proxy` and by `make_own_proxies` since CR-286A), or the three producers grow two rules about the same file. I have left it EXACT, which is what the fleet shipped on 2026-09-17.
- companion-media: `companion/src/ccsync_companion/broll_server.py` `derive_insert_paths`: the `basename(parent) == "Proxy"` arm builds `stem + ".mov"` the same way `insert_target_detail` does, so an old page (or a companion deriving for itself) can still produce the self-referential preview/editing-proxy pair CR-286P closes on the web side. One inequality guard. Web side is already safe on its own; deploy order does not matter.

### Deploy order
- The web apps and the dashboard first, as always: everything here is
  server-side or page-side, and no companion change is required by any of it.
  Nothing in this group adds or changes a wire field a companion reads. The
  ONE contract change an operator should know about is
  `server/publish_db.py`'s new non-zero exit `RC_DRAIN_UNMERGED = 3`: a
  scripted publish that used to see 0 after a failed post-swap merge now sees
  3. `docs/INDEXERS.md` and `docs/BACKUP_RESTORE.md` were checked for a
  documented `&&` chain that would newly stop; there is none.

### Owner decisions
- **ytdl-web-6: the owner chose the old behaviour** ("I want the old behaviour back", 2026-09-18): an expired job may be finished by any editor's live companion. Reverted before the gate.
- **server-tools-1: the notices file is regenerated from THIS rig's venvs.**
  That is what the generator does, and it is why the diff is larger than
  psycopg2 (pystray is gone from the companion venv, several versions moved).
  The alternative - hand-editing the generated half - is what the file's own
  header forbids.
- **broll-2 refuses BOTH directions of a schema skew.** The newer-than-the-app
  direction is the one the finding is about; refusing the older direction too
  is my call, because a file dropped under a running container is never
  stepped and 500s every ingest push until a restart.
  `--allow-schema-skew` is the escape hatch.
- **ytdl-web-4's paste refusal is measured only when the server is the
  executor** (`not (LOCAL_DOWNLOAD and req.local)`), matching
  `start_download`'s existing rule. A created-local paste is still measured by
  the worker if it ends up executing it.
