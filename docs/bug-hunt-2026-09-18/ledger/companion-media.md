# Ledger entry for KNOWN_BUGS.md (2026-09-18 fix pass, the companion-media group)

Written by the builder; the orchestrator copies it into `KNOWN_BUGS.md` and
bumps the versions. Nothing below was committed and no version was changed.

## CR-284 - the tiers on the insert path: a preview ledgered as a lie, a 540p proxy nobody could take back, and twenty tests that never ran (2026-09-18)

The twenty-five companion-media findings (plus three owed in from webapps-tools) of `docs/bug-hunt-2026-09-18.md`
(twelve medium, thirteen low), fixed in that document's order against
`214869b` plus the uncommitted first wave (CR-282), which several of these
build directly on. Twelve of the twenty-five are in the proxy-tiers release
the whole fleet took on 2026-09-17 (companion 0.9.74); the rest are the
music/ytdl sidecars, the Cards agent's health line, and the test gaps that
let the first twelve ship. Every fix carries a regression test that fails on
the unfixed source.

### CR-284A (comp-broll-tiers-2) - a still-downloading editing proxy grew one thread and one Resolve worker child every two minutes - FIXED (broll_server.py, broll_standins.py)

`start_proxy_upgrade` refused only a row already `done`, kept no registry of
what was running, and `resume_pending_upgrades` is called from the 120 s
relink cycle for every row whose state is `pending` - which is exactly the
state a RUNNING upgrade sits in. A 400 MB editing proxy over SFTP therefore
accumulated one thread per pass, all polling one fetch, and when the file
landed every one of them called `music_server.call(BROLL_LINK_PROXY_ACTION)`:
six worker child processes for one clip. The worse half is the row
`run_proxy_upgrade` deliberately leaves `pending` when the download landed
but Resolve would not link it (Resolve closed, or open on another project):
with no backoff and no ceiling anywhere, a dozen such rows cost a dozen
threads and a dozen child processes every two minutes, for ever.

Two bounds, because the two cases are different. In flight: a module-level
set of stand-in paths keyed through `broll_standins.normalise_key` (never the
raw string, or two spellings of one path both start), claimed before the
thread and cleared in its `finally`. Given up: `upgrade_attempts` on the
LEDGER row, not in memory - a restart must not hand the budget back -
incremented by `set_upgrade(..., count_attempt=True)` on the leave-it-pending
branch, and `pending_upgrades()` stops offering a row that has spent
`UPGRADE_MAX_ATTEMPTS` (8). It stays `pending` rather than becoming `failed`,
so an insert of that clip by the editor still picks it up; that insert passes
`asked_for=True`, which resets the count, because an editor asking is not the
cycle sweeping.

Tests: `test_bug_hunt_2026_09_18_companion_media.py::test_a_running_upgrade_is_not_started_again_by_the_next_cycle`
and `::test_an_upgrade_that_can_never_link_stops_costing_a_worker_child`.

### CR-284B (comp-music-ytdl-jobs-1) - music indexing was impossible on any fleet whose release feed is not GitHub - FIXED (music_clap_sidecar.py)

The module comment says the CLAP allow-list "is DERIVED: the artefact is ours
and is served from the site's own release feed", and `host_allowed`'s
docstring repeats "the feed's OWN host is trusted by definition". Neither was
implemented: the list was four fixed GitHub patterns, while `feed_base`
genuinely honours `music_clap_feed_base` and the manifest's
`release_feed_base`. A customer publishing from a self-hosted feed, an S3/R2
bucket or the dashboard's own Tailscale Serve host got `refusing to download
the music indexing model: <their own host> is not one of the hosts this build
is allowed to fetch from` on every ingest tick, for ever, with no action
short of a new companion build - and the sentence blamed their own correct
configuration. This studio was unaffected only because its feed happens to be
GitHub Releases.

`host_allowed(url, cfg, site)` now accepts the parsed hostname of
`feed_base(cfg, site)` as well as the GitHub redirect chain. The sha256 pin
is what makes an artefact safe, on that host exactly as on GitHub's; the
allow-list is here to stop a URL nobody configured. https stays a condition
for a remote host, with plain http allowed for LOOPBACK only, which is what
the override's own "a local directory server" docstring offers a dev loop.

Tests: `::test_the_clap_model_may_be_fetched_from_the_fleets_own_feed`, and
`test_music_clap_sidecar.py::test_ensure_refuses_a_feed_that_is_not_https`
replaces the test that pinned the old refusal.

### CR-284C (comp-music-ytdl-jobs-2) - the companion suite reached GitHub and cost the gate eleven minutes - FIXED (tests/test_ytdlp_manager.py)

Six tests in that file start a real `YtDlpManager`, whose `_loop` calls
`sidecar_tools.ensure` / `ensure_ffmpeg_pair` - both of which take the
module-level `sidecar_tools._work_lock` and then do real network I/O against
GitHub. `stop()` only sets an event and `join(timeout=5)` cannot be asked
whether it worked, so a daemon thread parked in that call outlived the file
WITH THE LOCK HELD, and the next test in the same process to call
`sidecar_tools.ensure({})` blocked on it. `tools\run_all_tests.ps1` runs the
companion suite in one pytest process, so that pairing is the normal gate:
nine files measured at ~40 s run separately and 660 s together. It is also
the suite reaching the public internet, which 3c7cf8e and 214869b exist to
stop.

An autouse fixture stubs both entry points for every test in the file - the
leak is a property of starting the manager at all, not of the one test that
noticed, and the tests that want the sidecar's own behaviour monkeypatch them
again afterwards, which still wins. Measured after: the two files the hunter
paired run in 1.6 s.

Test: `test_ytdlp_manager.py::test_no_sidecar_thread_this_file_started_outlives_it`
(last in the file, deliberately): no `ccsync-ytdlp` thread is alive and
`sidecar_tools._work_lock` is free.

### CR-284D (comp-resolve-4) - the refresh's shipped default was exercised nowhere - FIXED (tests/test_bug_hunt_2026_09_18_companion_media.py)

All three refresh tests injected `replace_fn`, so `resolve_bridge.replace_clip`
- which is what `app._relink_proxies_once` actually gets, because it passes
only `link_fn` - was tested nowhere, and it was the half that was broken
(CR-282D). Fifty-two green tests pinned the shape of a feature that had never
refreshed a clip, which is the specific reason CR-281 shipped written up as
built.

The new test calls `apply_relinks` with NO `replace_fn` against a fake media
pool item, so the real `replace_clip` runs end to end and the assertion is
that `ReplaceClip` WAS called on the clip's own path. No Resolve is involved:
the forced path takes no save point, so `_before_mutation` -> `connect()` is
never reached, and the `_no_live_resolve` fixture stays in force.

Test: `::test_apply_relinks_default_replace_fn_really_calls_replace_clip`.

### CR-284E (proxy-tiers-1) - every insert still attached the 540p preview, and the relink pass could never take it back - FIXED (resolve_bridge.py)

Phase 3's one behaviour change for existing clips is that the browser preview
is no longer the proxy of a clip whose real file is on this machine (plan
section 6: "Original, with the good proxy or none"). Two readers implement
the offer of `Proxy/<stem>.{mov,mp4}` and only `proxy_relink.plan_relinks`
got the rule; `_attach_adjacent_proxy` still walked `expected_proxy_paths`
and linked the first file that existed, `.mov` then `.mp4`, for every insert.
The 120 s pass cannot undo it, because it skips a clip whose proxy IS working
- which is audit F1's own point. So the editor cut at 540p under a
full-quality original, permanently, on the machine the feature exists for,
while CR-281 recorded the behaviour as changed.

`_attach_adjacent_proxy` now asks the relink pass's two questions before a
`.mp4` candidate, through `_real_original_here`: is the clip's own file
there, and is it a ledgered stand-in. Both are filesystem/JSON only, because
this runs with `_API_LOCK` held and nothing in it may be a bridge call. The
`.mov` arm is unconditional - that is the editing proxy, and linking it is
what the plan's table asks for.

Tests: `::test_an_insert_does_not_attach_the_preview_over_a_real_original`,
`::test_a_stand_in_still_gets_its_preview_attached`,
`::test_the_editing_proxy_is_still_attached_unconditionally`. The two tests
in `test_broll_server.py` that pinned the old unconditional attach now use a
`.mov` sibling and say why.

### CR-284F (proxy-tiers-2 = broll-1 = comp-broll-tiers-4 = wire-4) - "there is no original" was read as "use the preview and pretend", and a genuine archive preview was ledgered as a lie - FIXED (broll_server.py)

`insert_target_detail` answers `original_rel: null` for the two states where
no original sits beside the preview: the stem-diverged archive clips, and any
clip ingested with "upload originals" off or whose original has not landed
yet - a first-class, supported steady state, not four legacy rows. Its own
docstring spends a paragraph saying so ("a caller must not read 'no original'
as 'use the preview and pretend'"). `derive_insert_paths` honoured an
explicit null for `preview_rel` and `edit_proxy_rel` and deliberately not for
`original_rel` ("there is always an original"), so the null fell back to the
posted rel - which in exactly these cases IS the preview. `plan_insert` then
answered `fetch_standin`: download the preview onto the preview's own path,
`broll_standins.record()` that genuine, lane-B-managed file as a lie about a
6K original that does not exist, and import it. `is_standin` answers True for
it for ever - its size never changes, so `is_stale` can never retire the row
- the watcher exempts it from the missing count on false grounds,
`proxy_relink` treats its geometry as suspect, and every re-insert reports
"the stand-in for this clip is already in place" and restarts an
editing-proxy upgrade.

`derive_insert_paths` carries a third state, `original_known`, set False when
the object is present and `original_rel` is explicitly null; `original_rel`
still holds the posted rel, so every path-shaped reader works unchanged.
`plan_insert` answers `PLAN_PREVIEW_ONLY` for it - fetch the preview to its
own path, import that, record nothing - with `resolved original_rel ==
preview_rel` as the belt-and-braces test, which is also the bare-rel
stem-diverged shape.

Tests: `::test_a_clip_with_no_original_is_preview_only_and_ledgers_nothing`
(the producer's real object, copied verbatim from the shape
`broll/web/tests/test_insert_target.py` pins) and
`::test_a_clip_with_a_real_original_still_gets_its_stand_in`.

### CR-284G (proxy-tiers-3) - the container losing sight of the archive was indistinguishable from "this clip has no original" - FIXED companion half (broll_server.py)

`insert_target_detail` discovers the original and the editing proxy by
listing the archive folder inside the dashboard container, and an OSError -
the dataset unmounted, an SMB hiccup, `BROLL_DATA_ROOT` wrong after an image
update - is swallowed into "no entries", which is byte for byte the answer
for "this clip has no original". Ten minutes of that turns every Send to
Resolve in the window into CR-284F, and the damage outlives the outage for
ever on projects nobody re-checks.

The companion half is here and is safe on its own: an `insert` object
carrying `known: false` is read as "the server judged nothing", and the plan
is the pre-phase-3 route - download the file the editor asked for - never a
stand-in and never the preview, because in this case the original probably IS
there. The key is optional on the wire: no dashboard sends it yet, and its
absence means exactly what it meant before. The server half (answer
`known: false` rather than a null that reads as an answer, and raise a
notice) is OWED below.

Test: `::test_an_archive_the_server_could_not_read_falls_back_to_the_old_route`.

### CR-284H (proxy-tiers-4) - the wired rig had no working signal that a clip was born from a stand-in - FIXED (broll_standins.py, proxy_relink.py, app.py)

`broll_standins.record` runs on the machine doing the insert and the ledger is
that machine's own file, so the plan's last table row - "a clip is born from a
stand-in when its stored `Frames`/`Resolution` disagree with the file at its
path, OR the ledger says so" - had no working second half on the wired rig,
which is the only machine that needs it and the machine whose ledger is empty
for exactly those clips by construction. What was left there was
`_geometry_disagrees`' `ffprobe -count_packets` over the archive (CR-282E made
it cheap; it is still the expensive question), and one `replace_clip` per clip
that until CR-282D did nothing at all.

Built to the dashboard builder's contract
(`docs/bug-hunt-2026-09-18/ledger/dashboard.md`, "proxy-tiers-4 contract"),
unchanged, in three pieces:

  * **Producer.** `broll_standins.placed_report(local_root, canonical_prefix)`
    answers `{rels, checked_at}` and `app.sync_guard()` sends it as
    `sync_guard.standins_placed`. Each rel is the ARCHIVE-RELATIVE path of the
    ORIGINAL the stand-in stands in for, forward slashes, NFC (CR-90 - the
    value is only ever compared, and a path a Mac reported is not `==` a path
    anything else reported), never an absolute path, capped at
    `broll_standins.FLEET_REPORT_MAX` (200, the same bound written down on
    both sides). Every entry is listed, stale or not: the question a wired rig
    asks is "was this clip ever placed as a stand-in by anybody", and a row
    this machine has since replaced still describes a project cut against the
    stand-in's geometry. The section is ALWAYS sent, empty list included,
    because the dashboard replaces this machine's set from it - an absent
    section could never clear a stand-in that has been replaced.
  * **Consumer.** `proxy_relink.note_fleet_standins(resp)` reads
    `standins_known.rels` off the report REPLY, and `_geometry_disagrees` asks
    `fleet_says_standin` FIRST - after the remembered verdict and the local
    ledger, before the header estimate and before the exact count. A True is
    conclusive (one `ReplaceClip` on the clip's own path, and CR-284R's memory
    stops that repeating); a False is not, because the dashboard only knows
    what machines have told it, so it falls through to the probes that were
    there before.
  * **The third state.** An ABSENT `standins_known` means THIS DASHBOARD DOES
    NOT KNOW, and behaves exactly as today: `fleet_says_standin` answers None
    rather than False and the demux still runs. A dashboard deployed behind
    the companions therefore cannot turn the geometry check off. Knowledge
    from an earlier reply is kept rather than cleared on a silent one - at
    worst that costs one ReplaceClip which changes nothing.

`app.py` belongs to companion-core and carries exactly two additions, both
cited `proxy-tiers-4`: one `try` block in `sync_guard()` that calls
`placed_report`, and one in `_on_report_response` that calls
`note_fleet_standins`. Everything else is in this group's files. Nothing new
reaches Resolve, and both calls are wrapped the way every other section and
every other reply consumer in those two functions is.

Tests: `::test_the_report_carries_the_archive_rels_this_machine_stood_in_for`,
`::test_the_report_says_none_rather_than_saying_nothing`,
`::test_the_fleet_report_is_bounded_and_deduplicated`,
`::test_a_wired_rig_learns_from_the_fleet_without_demuxing_the_archive`,
`::test_a_clip_the_fleet_has_not_heard_of_is_still_probed`,
`::test_a_dashboard_that_does_not_know_behaves_exactly_as_before`,
`::test_a_mac_spelling_of_one_name_is_one_key`.

### CR-284I (proxy-tiers-5) - a clip stayed invisible until its multi-GB original had finished uploading - FIXED (broll_ingest.py)

Plan section 5 item 5 says "an editor can use a clip from the moment its
editing proxy lands, long before a multi-GB original finishes", and the
upload ORDER was built for it (`broll_upload.UPLOAD_ORDER` puts the original
last). Nothing consumed the order: `_pump_uploads` posts `/uploaded` once,
when NOTHING is missing, and `mark_uploaded` is the only writer of
`status = 'indexed'`. Browse, tree and search all skip an `ingesting` row, so
a day of 6K material showed nothing in the archive for the eight hours its
originals took, and the only signal was the ingest SPA's progress bar.

`_maybe_stage_live` posts the first stage - the landed files,
`original_uploaded: false` - as soon as everything except the original is up,
once per item, leaving it in `uploading` so the ordinary post still flips the
flag when the original lands. The server was already ready for it:
`mark_uploaded` requires the original slot only when the flag is true and
stores it on the row, and the route has no item-state guard. This lands WITH
CR-284F by necessity: until that fix, a clip live before its original was on
the NAS inserted the PREVIEW at the original's path.

Test: `test_broll_ingest.py::test_a_clip_goes_live_when_its_proxies_land_not_when_its_original_does`.

### CR-284J (proxy-tiers-6) - a stand-in could be written under a .mxf, .avi or .mkv name - FIXED (broll_server.py)

A stand-in is the preview's ISO-BMFF bytes under the ORIGINAL's name and
extension, and the only guard was `proxy_scan.NEEDS_RESOLVE_EXTS` (`.braw`,
`.r3d`, `.crm`). The archive indexer scans `.mov .mp4 .mxf .braw .avi .mkv
.m4v`, and the phase 0 spike measured method C against one ProRes `.mov`, so
an MXF original got an MP4 wearing an `.mxf` name - which Resolve's MXF path,
not a content sniffer the way ffmpeg is, either refuses silently or imports
with the wrong container's geometry. Either way `broll_standins.record` has
already run (deliberately, before the import), so the next insert takes the
"already in place" branch and re-imports the same unopenable file for ever.

`STANDIN_EXTS` is an allow-list - `.mov`, `.mp4`, `.m4v`, the containers the
preview's bytes could BE - and everything else falls to `PLAN_PREVIEW_ONLY`,
which is already implemented and always works. A deny-list would put the next
extension the archive learns to scan straight back into this shape.

Tests: `::test_a_container_the_preview_is_not_gets_the_preview_instead`
(`.mxf`, `.avi`, `.mkv`) and `::test_the_containers_the_spike_covers_still_get_a_stand_in`.

### CR-284K (tests-1) - twenty media-job tests skipped silently on every CI and release runner - FIXED (tests/conftest.py, tests/test_jobs_media.py, .github/workflows/*)

`test_jobs_media.py` gated twenty tests on a bare `shutil.which` skipif with
no `CCSYNC_REQUIRE_*` escape, and its module-scoped `clips` fixture skipped
as well, so the whole file could vanish at exit code 0. Those twenty are the
only thing holding `jobs_media.py`'s three Timeline Cards recipes to
`library_engine.py`'s ffmpeg argv VERBATIM (CLAUDE.md) and to `proxy_gen`'s
`.partial` + atomic-rename rule. ffmpeg is installed by exactly one CI step,
`if:`-scoped to the broll/indexer job on Linux; neither companion job nor
either release workflow had it.

`conftest.require_ffmpeg_or_skip` is `rclone_binary`'s treatment, beside it so
a future ffmpeg-dependent companion test inherits it: a skip normally, a
`pytest.fail` when `CCSYNC_REQUIRE_FFMPEG=1`. The `needs_ffmpeg` mark is a
fixture now rather than a `skipif`, because a mark cannot fail. Both companion
CI jobs install ffmpeg (continue-on-error: a broken package feed must not red
a run about our own code - the tests fall back to skipping, exactly where they
were), and BOTH release workflows install it as a hard requirement and set
`CCSYNC_REQUIRE_FFMPEG=1`, so a release cannot be cut without that coverage.

Test: `::test_a_missing_ffmpeg_is_a_failure_when_the_release_says_so`.

### CR-284L (wire-3 = dash-cards-8) - an agent pushing into nothing reported itself healthy - FIXED (timeline_cards_role.py)

`cards_tunnel._no_engine` answers HTTP 200 with `{"error": "<editor> is not
in a Timeline Cards episode..."}` - deliberately, because a 4xx would put the
loops into retry/backoff and re-create the hot loop CR-282H just fixed. The
companion's transport judged on the STATUS alone: `_note_call(200, "")` moved
`_last_poll_at` and cleared `_last_error`, and `_note_traffic` then recorded
the pushed timeline off the REQUEST body. So the tray, the role's health and
the fleet grid all read `[ CARDS: E1 v5 ]` while every sweep was dropped on
the floor, and the one sentence that says what to do ("open an episode at
/cards/") reached no log line, no tray line and no fleet page.

`call()` inspects a 200 body for `error`/`note` through `_note_answer`: the
sentence becomes the role's health DETAIL, the discarded push is not recorded
as traffic served, and a change of state is logged once rather than once per
poll. Nothing raises and the health WORD stays `running`, because the loops
are alive and the dashboard is answering - that is what the word means, and a
raise would reintroduce the hot loop from the other end. `/agent/pending`'s
`{}` answer is untouched: `pull_loop`'s `if got.get("id") is None: continue`
depends on its shape.

Tests: `::test_a_push_the_dashboard_threw_away_is_not_reported_as_serving`
and `::test_an_answer_with_no_refusal_records_the_timeline_as_before`.

### CR-284M (comp-broll-tiers-3) - an editing proxy that would not encode failed the whole clip - FIXED (broll_ingest.py)

`_encode_verified` is one loop for the preview and the editing proxy, and its
exhaustion path calls `_fail_item`. So a frame-count mismatch on the EDITING
proxy - the optional tier - failed the entire item: no preview, no stills, no
original uploaded, for a clip whose preview had already verified. An
edit-weight original and a BRAW both reach the archive with no editing proxy
and nothing is wrong with them, which is what `edit_proxy_reason` exists to
say.

`_encode_verified` takes `required`, and `_make_edit_proxy` passes False: the
tier drops with the encoder's own sentence in `edit_proxy_reason` and the
clip goes live with its preview, which is what a remote editor cut on before
the tier existed. No tolerance was added to `_frames_missing` - the
Reproductive Rights clips were 1 to 18 frames short and Resolve refused every
one, so a tolerance would readmit the exact defect the check was written for.

Test: `test_broll_ingest.py::test_an_editing_proxy_a_few_frames_short_drops_the_tier_not_the_clip`
(the test that pinned the old behaviour, rewritten).

### CR-284N (comp-broll-tiers-5) - the stand-in ledger grew for ever and a failed upgrade reached nobody - FIXED (broll_standins.py, broll_server.py)

Entries were added and never removed except by a `forget()` nothing called,
and `all()` re-reads and re-sorts the whole file on every `pending_upgrades()`
poll from the 120 s cycle. An upgrade that ends `failed` was written to the
ledger and the log and to nothing an editor sees: they keep cutting on the
1080p preview believing it is the editing proxy.

Pruning is both conditions in the module's own order: a file that is merely
absent leaves its entry standing (an absent path is still one we lied about),
and only a file that has been gone for longer than `PRUNE_AFTER_SECONDS` (30
days) retires one. It happens on load and is carried by the next write, so a
read-only pass costs no I/O. `given_up_upgrades()` is the new reader -
`failed`, plus pending past CR-284A's attempt ceiling - and `GET /status`
carries it as `standins_owed`, an ADDED key. The tray line an editor would
actually see is OWED to companion-core: `app.py` is not this group's to
change.

Test: `::test_an_entry_whose_file_has_been_gone_for_a_month_is_forgotten`,
plus the `given_up_upgrades` half of `::test_an_upgrade_that_can_never_link_stops_costing_a_worker_child`.

### CR-284O (comp-music-ytdl-jobs-3) - the b-roll model allow-list accepted an http:// URL - FIXED (broll_vlm_sidecar.py)

`broll_vlm_sidecar.host_allowed` tested the hostname alone while its music
sibling refuses a non-https scheme first, and nothing downstream re-checks.
Nothing today can reach it (the catalogue is vendored and every pin is
https) and the sha256 pin means the exposure would be confidentiality rather
than a swapped artefact - the defect is the asymmetry, which is what bites
the day these URLs become site-derived as the CLAP ones already are. The
scheme test is now in both.

Test: `::test_the_vlm_allow_list_refuses_plain_http`.

### CR-284P (comp-music-ytdl-jobs-4) - the YouTube cookie jar was written before it was hardened - FIXED (ytdl_cookies.py)

The comment beside it says harden() runs "before the rename so the secret is
never briefly world-readable". The order was write -> harden -> replace, so
the bytes of a live Google session existed on disk under the inherited ACL
(Windows) or the umask (posix) for the duration of the write. It is now
create-empty with `O_CREAT|O_EXCL|O_WRONLY, 0o600` (the mode does it on
posix; on Windows it is ignored, so `secretfile.harden` runs on the empty
file before a byte goes in), then write, then harden again, then replace. A
`.new` left by a killed write is unlinked first, or `O_EXCL` would fail every
install from then on.

Test: `test_ytdl_cookies.py::test_install_hardens_the_temp_file_before_the_rename`
now asserts the FIRST harden saw a zero-byte file.

### CR-284Q (comp-music-ytdl-jobs-5) - a None returncode from the edit-ready conversion read as success - FIXED (ytdl_executor.py)

`int(getattr(proc, "returncode", 1) or 0)` maps `None` onto 0, which is the
success branch, while a missing attribute correctly yields 1. `deps.run` is an
injected seam, so a runner that returns before the child is reaped (or a test
double) would deliver a present-but-truncated `.editready.mp4` into
`swap_in`, which renames the good original aside. `subprocess.run` always
sets an int, which is why it has not bitten.

Test: `::test_a_conversion_that_reported_no_return_code_is_not_a_success`
drives the real `_ensure_edit_ready` with a runner that writes a file and
answers `returncode=None`.

### CR-284R (comp-resolve-3 = res-companion-5) - a clip that would not converge was re-ReplaceClip'd for ever - FIXED (proxy_relink.py)

The proxy half of this module has a refusal memory keyed on the proxy file's
(mtime, size) precisely so Resolve is not asked the same impossible thing
every pass. The refresh half had none: CR-282E remembers a refresh Resolve
took that changed nothing, but a refresh that SUCCEEDED and still left the
clip's stored `Frames` where they were - an mp4 with an edit list, a file
Resolve reads at another rate, a clip it will not re-read - was re-planned
every pass, each one spending one of `allow_automatic`'s eight grants a day,
so genuine proxy relinks were rate-limited out for the rest of it.

A successful refresh now records its verdict too, under the frame count the
clip believed BEFORE the call (`note_geometry_verdict(path, False, stat,
stored_frames)`). If the geometry really moved, the next pass reads a
different stored count, which is a different key, and asks again as it
should; if it did not, the key matches and the op is not re-planned. A
refresh that got no answer at all is NOT remembered - that is Resolve going
away, and it deserves the next attempt.

Test: `::test_a_clip_that_will_not_converge_is_refreshed_once_not_for_ever`.

### CR-284S (comp-resolve-5) - a pass that refreshed forty clips reported "nothing to do" - FIXED (proxy_relink.py)

`refreshed` was added to the return dict and read by nobody: `message` was
built only `if relinked or failures`, so a refresh-only pass produced `""`
and `app.py` logged "proxy relink: nothing to do". The operator diagnosing a
wired rig had no signal that phase 3's refresh was running at all, which is
exactly what hid CR-282D. The message now names both counts. The other half -
`_note_proxy_attach`'s stored dict, which still reads `relinked` only, so the
tray and the report say `attached: 0` - is OWED to companion-core.

Test: `::test_a_pass_that_only_refreshed_does_not_report_nothing_to_do`.

### CR-284T (comp-resolve-6) - a refresh on a clip with a working proxy carried no proxy back - FIXED (proxy_relink.py, resolve_bridge.py)

`plan_relinks` computes `new_proxy` only when the proxy is NOT working, so a
refresh planned for a clip that was playing its editing proxy carried none,
and `ReplaceClip` is the API's re-import path. If it clears the attachment,
the clip drops to its original (or to offline media on a remote-ish rig)
until the next pass - 120 s away at best and behind `allow_automatic`'s 900 s
bar at worst. The verifier could not confirm what Resolve does here without a
live Resolve, so the fix is the cheap, always-safe half rather than the one
that would need `plan_relinks`' careful `.mp4` rule changed: the op carries
`reattach_proxy` (the proxy it was playing, only when it was working), and
after a changed refresh `apply_relinks` reads the clip's `Proxy` property
back through `resolve_bridge.clip_proxy_state` and re-links only if it came
back blank. One property read per refresh; nothing is re-linked when the
attachment survived. A live check on the wired rig is still owed, and is
already on CR-281's list.

Tests: `::test_a_refresh_that_blanked_the_proxy_re_attaches_it`,
`::test_a_refresh_that_left_the_proxy_alone_re_attaches_nothing`,
`::test_a_refresh_plans_the_proxy_it_is_playing`.

### CR-284U (comp-resolve-7) - the archive exemption stat'ed the disk for every missing clip every three seconds - FIXED (watcher.py)

`_archive_exempt`'s cache was per POLL, and the poll is every 3 s. For every
distinct MISSING archive path it read the stand-in ledger (a stat of the
ledger plus a stat of the media file inside `_entry_is_stale`) and then
`find_proxy_on_disk`, which probes up to four candidates. A remote rig with a
proxy-only b-roll timeline is the designed steady state in which every one of
those clips is MISSING on every poll: a 200-clip timeline is roughly a
thousand filesystem probes every three seconds, on the thread the popup and
fixer latency depend on, for a diagnostic count.

The verdict is now remembered per path across polls with a 60 s TTL - short
on purpose, because the answer flips when a proxy lands or is deleted and a
long memory would keep a genuinely missing clip out of the count. The memo is
dropped whole past 4,000 entries; it is a cache, not a ledger. The
`archive_exempt_fn` injection point the tests use is unchanged.

Tests: `::test_the_archive_exemption_is_remembered_across_polls`,
`::test_the_exemption_memory_expires`.

### CR-284V (proxy-tiers-8) - the machine that made the editing proxy downloaded it back from the NAS - FIXED (broll_ingest.py)

`_mirror_locally` moves this machine's own PREVIEW into the archive so a
later Send to Resolve needs no fetch (plan section 9.9). The editing proxy it
just encoded was left in staging, so the very machine that produced all three
files answered `fetch_standin` for its own clips: it downloaded its own
preview from the NAS onto the original's archive path, then its own editing
proxy in the upgrade lane. Hundreds of MB back down a link that had just sent
them up.

Both outputs go through one `_mirror_one` now, which re-points the item at
where the file landed so a later re-send uses the right path. The clip still
takes the stand-in route (the ORIGINAL's archive path genuinely is not on
that machine - the original was dropped from outside the tree); what it no
longer does is re-download a file it made. Noticing the real original out of
tree, via the ingest state file's `local_path`, crosses a module boundary
`broll_server` has no handle on today and is not attempted here.

Tests: `test_broll_ingest.py::test_the_editing_proxy_is_mirrored_into_the_archive_too`,
and `::test_a_restart_does_not_re_encode_the_editing_proxy` follows the file
to where it now lives.

### CR-284W (tests-2) - `from_page` was true for any dict, and a malformed object could place a stand-in - FIXED (broll_server.py, tests/test_broll_server.py)

`derive_insert_paths` set `from_page = True` for ANY dict, before a single
field was validated, and `plan_insert` reads `from_page` as the licence to
treat a null weight beside a STEM-CONVENTION editing proxy as "the server
judged this original too heavy". So a truncated or garbled object - one with
`share` and `original_rel` and no tier fields is enough - made the companion
place a stand-in for a clip nobody had ever weighed: the 1080p preview at the
original's canonical path, a ledger row, and an upgrade owed against a
`Proxy/<stem>.mov` the server never made. Every shipped producer sends the
full object, so this is hardening rather than a live break - and the test
that existed asserted four fields and never this one.

`from_page` is now true only when a tier field was ACCEPTED: a `preview_rel`
or `edit_proxy_rel` that is an explicit null or a rel that passed the
traversal test, a boolean weight, or a dict geometry. The parametrised
malformed-object test asserts `from_page is False` and that the plan is
`fetch_original`.

Test: `test_broll_server.py::test_a_malformed_insert_object_is_ignored_never_fatal`
(extended), plus `::test_a_malformed_insert_object_does_not_count_as_the_dashboard_looking`.

### CR-284X (tests-3) - a phase-2 test still pinned "the insert object changes nothing" - FIXED (tests/test_broll_server.py)

The test asserted the worker call was identical with and without the `insert`
object, with a docstring saying "phase 3 is gated on the phase 0 spike".
Phase 3 shipped on 2026-09-17 and the object now decides which file is
fetched and imported; the test kept passing only because `_mode_gate_body`
writes the clip to disk, so both runs took the `import_original` row. It is
vacuous for the thing it is named after, and its docstring invites the next
change to be "fixed" by narrowing phase 3. Renamed to what it actually pins
(that row IS object-independent, which is worth keeping), and paired with
`::test_an_absent_original_plus_an_insert_object_changes_the_fetch`, which
goes red the moment the object stops mattering.

### CR-284Y (tests-4) - the "a write that cannot land is not an exception" test monkeypatched away the thing that raises - FIXED (broll_standins.py, tests/test_broll_standins.py)

The test replaced `StandinLedger._persist_locked` - the exact function whose
failure it claims to cover - with `lambda self: False`, so it proved only
that a False return is tolerated. The real one catches `OSError` and nothing
else, `json.dumps` sits inside that try, and the module-level `record()` was
the one public wrapper in the file without the `try/except -> log.debug` its
five siblings have, against a docstring that says no method here raises. A
geometry value json cannot encode therefore raised out of `record()` on the
insert path - and worse: the entry is inserted into `_entries` BEFORE the
persist, so the in-memory ledger was poisoned and every subsequent `record()`
in the process raised too, with the file never written.

Three changes: `_persist_locked` catches `TypeError`/`ValueError` as well
(they are `json.dumps`'s); `record()` rolls the entry back when the write did
not land, so one bad payload cannot poison the process; and the module-level
`record()`/`forget()` wrappers are guarded like their siblings. The old test
now raises a real `OSError` from `os.replace`.

Tests: `test_broll_standins.py::test_a_write_that_cannot_land_is_not_an_exception`
(rewritten), `::test_a_value_json_cannot_encode_does_not_raise_and_does_not_poison`,
`::test_a_write_that_really_cannot_land_is_not_an_exception`.

### CR-284Z (broll-indexer-2 = proxy-tiers-7, owed in by webapps-tools) - the companion's `frames` column was a container's claim - FIXED (ffmpeg_tools.py)

`probe_video` read `"frames": _int_or_none(video_stream.get("nb_frames"))`,
which this same module's `count_frames` docstring calls a claim rather than a
count - and that column is what decides an OFFLINE clip's length on a remote
editor's timeline (migration 012, plan section 5). The indexer's twin got a
`duration x fps` cross-check in this same pass (CR-286R), and two producers
of one wire field have to agree about how confident it is.

`_plausible_frames` is a verbatim twin of the indexer's helper: the claim
stands when duration x fps supports it (one frame of slack plus 1% for a VFR
average), None when it does not, and unchanged when there is nothing to check
it against. None is what every reader of the field already handles.

Tests: `::test_a_containers_frame_claim_is_cross_checked_against_its_duration`,
`test_ffmpeg_tools.py::test_a_frame_claim_the_duration_does_not_support_is_not_reported`,
and `::test_probe_video_reports_frames_and_bitrate` whose fixture now gives a
duration that agrees with its own claim.

### CR-284AA (comp-broll-tiers-3's second half, owed in by webapps-tools) - one frame-count rule, on both sides - FIXED (ffmpeg_tools.py, broll_ingest.py)

The indexer grew `frames_match` in this pass and deliberately left it EXACT,
pending this group's decision on a tolerance. **The decision is EXACT**, and
it is a decision rather than an omission: the verifier measured the VFR
mechanism comp-broll-tiers-3 proposed and refuted it (a filtered encode
passes VFR timestamps through - 200 packets in, 200 out, in both
containers), and the Reproductive Rights clips were 1 to 18 frames short with
Resolve refusing every one, so "a frame rate's worth" of slack would readmit
exactly the defect the check exists for. What comp-broll-tiers-3 changed is
the blast radius (CR-284M), not the threshold.

The companion now carries `ffmpeg_tools.frames_match` as the twin of the
indexer's, with the reasoning in its docstring, and `_frames_missing` calls
it instead of an inline `==`. A tolerance introduced later cannot land on one
side alone without the other function's docstring contradicting it.

Test: `::test_the_two_frame_count_rules_are_one_rule`.

### CR-284AB (broll-4's companion half, owed in by webapps-tools) - an editing proxy that IS the preview - FIXED (broll_server.py)

`derive_insert_paths`' `basename(parent) == "Proxy"` arm builds
`stem + ".mov"` exactly as `insert_target_detail` does, so a preview that is
itself a `.mov` names one file twice: `edit_proxy_rel == preview_rel`.
Downstream that is a `heavy` verdict resting on an editing proxy that does
not exist, an upgrade owed against the file the clip already is, and a
background lane that can never finish. `_no_self_referential_proxy` drops the
editing proxy when it equals the preview, on both the derived and the
page-supplied path. The web side closes its own half (CR-286P); this is the
one a companion can reach on its own, and either may deploy first.

Test: `::test_an_editing_proxy_that_is_the_preview_is_no_editing_proxy`.

### Verification

All in `companion/`, run from that directory with `.venv\Scripts\python.exe -m pytest`.
"Fails before" means on 214869b plus the first wave (CR-282), except where
noted.

- tests/test_bug_hunt_2026_09_18_companion_media.py::test_a_running_upgrade_is_not_started_again_by_the_next_cycle -> fails before (the second cycle starts a second thread), passes now
- tests/test_bug_hunt_2026_09_18_companion_media.py::test_an_upgrade_that_can_never_link_stops_costing_a_worker_child -> fails before (no ceiling exists), passes now
- tests/test_bug_hunt_2026_09_18_companion_media.py::test_the_clap_model_may_be_fetched_from_the_fleets_own_feed -> fails before (the fleet's own host is refused), passes now
- tests/test_music_clap_sidecar.py::test_ensure_refuses_a_feed_that_is_not_https -> replaces the test that pinned the defect
- tests/test_ytdlp_manager.py::test_no_sidecar_thread_this_file_started_outlives_it -> fails before (a ccsync-ytdlp thread is still in a real GitHub call), passes now; the file pairing measured 115+ s before and 1.6 s now
- tests/test_bug_hunt_2026_09_18_companion_media.py::test_apply_relinks_default_replace_fn_really_calls_replace_clip -> fails at 214869b (replace_clip short-circuits and ReplaceClip is never called), passes now
- tests/test_bug_hunt_2026_09_18_companion_media.py::test_an_insert_does_not_attach_the_preview_over_a_real_original -> fails before, passes now
- tests/test_bug_hunt_2026_09_18_companion_media.py::test_a_stand_in_still_gets_its_preview_attached -> passes both (the case the fix must not break)
- tests/test_bug_hunt_2026_09_18_companion_media.py::test_a_clip_with_no_original_is_preview_only_and_ledgers_nothing -> fails before (fetch_standin onto the preview's own path), passes now
- tests/test_bug_hunt_2026_09_18_companion_media.py::test_an_archive_the_server_could_not_read_falls_back_to_the_old_route -> fails before (`known` is not read), passes now
- tests/test_broll_ingest.py::test_a_clip_goes_live_when_its_proxies_land_not_when_its_original_does -> fails before (nothing is posted until the original lands), passes now
- tests/test_bug_hunt_2026_09_18_companion_media.py::test_a_container_the_preview_is_not_gets_the_preview_instead -> fails before (a `.mxf` gets a stand-in), passes now
- tests/test_bug_hunt_2026_09_18_companion_media.py::test_a_missing_ffmpeg_is_a_failure_when_the_release_says_so -> fails before (no such gate exists), passes now
- tests/test_bug_hunt_2026_09_18_companion_media.py::test_a_push_the_dashboard_threw_away_is_not_reported_as_serving -> fails before (the timeline is recorded and the detail says "serving the page"), passes now
- tests/test_broll_ingest.py::test_an_editing_proxy_a_few_frames_short_drops_the_tier_not_the_clip -> fails before (the whole item is failed), passes now
- tests/test_bug_hunt_2026_09_18_companion_media.py::test_an_entry_whose_file_has_been_gone_for_a_month_is_forgotten -> fails before (nothing prunes), passes now
- tests/test_bug_hunt_2026_09_18_companion_media.py::test_the_vlm_allow_list_refuses_plain_http -> fails before, passes now
- tests/test_ytdl_cookies.py::test_install_hardens_the_temp_file_before_the_rename -> fails before (the first harden sees the written file, not an empty one), passes now
- tests/test_bug_hunt_2026_09_18_companion_media.py::test_a_conversion_that_reported_no_return_code_is_not_a_success -> fails before (rc reads as 0 and the truncated file is swapped in), passes now
- tests/test_bug_hunt_2026_09_18_companion_media.py::test_a_clip_that_will_not_converge_is_refreshed_once_not_for_ever -> fails before (no verdict is remembered for a changed refresh), passes now
- tests/test_bug_hunt_2026_09_18_companion_media.py::test_a_pass_that_only_refreshed_does_not_report_nothing_to_do -> fails before (message is ""), passes now
- tests/test_bug_hunt_2026_09_18_companion_media.py::test_a_refresh_that_blanked_the_proxy_re_attaches_it -> fails before (nothing re-attaches), passes now
- tests/test_bug_hunt_2026_09_18_companion_media.py::test_a_refresh_plans_the_proxy_it_is_playing -> fails before (no `reattach_proxy` key), passes now
- tests/test_bug_hunt_2026_09_18_companion_media.py::test_the_archive_exemption_is_remembered_across_polls -> fails before (five polls, five probes; and there is no memo), passes now
- tests/test_bug_hunt_2026_09_18_companion_media.py::test_the_exemption_memory_expires -> fails before, passes now
- tests/test_broll_ingest.py::test_the_editing_proxy_is_mirrored_into_the_archive_too -> fails before (only the preview is mirrored), passes now
- tests/test_bug_hunt_2026_09_18_companion_media.py::test_a_malformed_insert_object_does_not_count_as_the_dashboard_looking -> fails before (`from_page` is True and the plan is fetch_standin), passes now
- tests/test_broll_server.py::test_a_malformed_insert_object_is_ignored_never_fatal -> the new `from_page` assertion fails before, passes now
- tests/test_broll_server.py::test_an_absent_original_plus_an_insert_object_changes_the_fetch -> replaces the vacuous phase-2 pin
- tests/test_bug_hunt_2026_09_18_companion_media.py::test_a_value_json_cannot_encode_does_not_raise_and_does_not_poison -> fails before (TypeError out of record()), passes now
- tests/test_broll_standins.py::test_a_write_that_cannot_land_is_not_an_exception -> rewritten to raise from os.replace; the ledger-is-empty assertion fails before, passes now
- tests/test_bug_hunt_2026_09_18_companion_media.py::test_a_containers_frame_claim_is_cross_checked_against_its_duration -> fails before (no such helper; `frames` is the raw claim), passes now
- tests/test_ffmpeg_tools.py::test_a_frame_claim_the_duration_does_not_support_is_not_reported -> fails before (1674 is reported against a 12.5 s file), passes now
- tests/test_bug_hunt_2026_09_18_companion_media.py::test_the_two_frame_count_rules_are_one_rule -> fails before (no `frames_match` in the companion), passes now
- tests/test_bug_hunt_2026_09_18_companion_media.py::test_an_editing_proxy_that_is_the_preview_is_no_editing_proxy -> fails before (the pair names one file twice), passes now
- tests/test_bug_hunt_2026_09_18_companion_media.py::test_the_report_carries_the_archive_rels_this_machine_stood_in_for -> fails before (no such producer), passes now
- tests/test_bug_hunt_2026_09_18_companion_media.py::test_the_report_says_none_rather_than_saying_nothing -> fails before, passes now
- tests/test_bug_hunt_2026_09_18_companion_media.py::test_the_fleet_report_is_bounded_and_deduplicated -> fails before, passes now
- tests/test_bug_hunt_2026_09_18_companion_media.py::test_a_wired_rig_learns_from_the_fleet_without_demuxing_the_archive -> fails before (the reply is ignored and the clip is demuxed), passes now
- tests/test_bug_hunt_2026_09_18_companion_media.py::test_a_clip_the_fleet_has_not_heard_of_is_still_probed -> fails before (no such reader), passes now
- tests/test_bug_hunt_2026_09_18_companion_media.py::test_a_dashboard_that_does_not_know_behaves_exactly_as_before -> fails before (no such reader), passes now; this is the compatibility direction
- tests/test_bug_hunt_2026_09_18_companion_media.py::test_a_mac_spelling_of_one_name_is_one_key -> fails before, passes now

Suites run (only the files touched, per the brief): test_bug_hunt_2026_09_18_companion_media.py,
test_broll_server.py, test_broll_insert_tiers.py, test_broll_standins.py,
test_broll_proxy_upgrade.py, test_broll_ingest.py, test_proxy_relink.py,
test_proxy_relink_standins.py, test_watcher.py, test_music_clap_sidecar.py,
test_broll_vlm_sidecar.py, test_ytdl_cookies.py, test_ytdl_executor.py,
test_ytdlp_manager.py, test_timeline_cards_role.py, test_jobs_media.py,
test_vendored_downloader.py, test_loopback_guard.py, test_music_server.py,
test_ffmpeg_tools.py, test_broll_ingest_media.py, test_proxy_gen.py,
test_bug_hunt_2026_09_18_companion.py (the first wave's, unaffected) -> every
one green. `py_compile` clean on every source file touched; the three
workflow files parse as YAML.

### Not fixed

- none. The two halves listed here at first (comp-broll-tiers-5's
  editor-facing line and comp-resolve-5's report key) were built by
  `companion-core` the same evening as CR-283X and CR-283W, and the dashboard
  declared both keys as CR-285N.

### OWED TO ANOTHER GROUP

- webapps-tools: `broll/web/app/routes_api.py`: `insert_target_detail` / `_insert_object`: when the archive listing raises OSError (both the `entries = []` swallow at ~106-110 and the editing-proxy one at ~120-127), put `"known": false` in the insert object instead of answering the same shape as "this clip has no original". The companion already refuses to judge on such an object (CR-284G) and falls back to fetching the original. Do NOT drop the keys instead: an ABSENT `preview_rel`/`edit_proxy_rel` means "use the stem convention" to the companion, which re-creates the wrong answer. Either side may deploy first: the key is optional on the wire and a companion that has never heard of it behaves exactly as today.
- webapps-tools: `broll/web/tests/test_insert_target.py`: `test_a_missing_archive_directory_answers_without_a_proxy` pins the conflation ("could not look" answered as "there is none") and needs the new key asserted; `test_the_preview_only_fallback_reports_no_original` should also assert that a caller reading `original_rel: null` gets no `original_rel` fallback - the companion half of that contract is now `original_known` (CR-284F).
- webapps-tools / dashboard: a notice kind for "the container cannot list the b-roll archive" (proxy-tiers-3's second half). `mount_status` already records the b-roll root, and `dash-collector-alerts` owns the registry; the schema/registry row is the dashboard builder's (CLAUDE.md: register a kind WITH its writer).
- companion-core: `app.py`: `_note_proxy_attach`: add `refreshed` to the stored dict from `apply_relinks`' answer (comp-resolve-5's other half). ADDED key, same rule the module already states; no wire change, companion-only.
- companion-core: `app.py`: the tray/report surface: one line for `broll_standins.given_up_upgrades()` (comp-broll-tiers-5), reusing `_note_proxy_attach`'s RES-3 shape rather than a new tray path. The reader exists and `GET /status` already carries it as `standins_owed`; companion-only.
- companion-core (INFORMATION, not a request): `app.py` carries two lines for proxy-tiers-4 (CR-284H) - `sync_guard()` sends `standins_placed`, `_on_report_response` calls `proxy_relink.note_fleet_standins`. That builder had finished, so there was no conflict; both are cited `proxy-tiers-4` and wrapped like their neighbours.
- dashboard: proxy-tiers-4's other half is being built to the same contract by a second dashboard builder (`StandinsPlacedIn`, schema v54's `broll_standins` table, `standins_known` on the report reply). The exact keys this companion sends and reads are in CR-284H. DASHBOARD FIRST, per the contract.
- webapps-tools: the three items owed IN to this group are done and are CR-284Z, CR-284AA and CR-284AB above. The frame-count decision is EXACT, so `broll/indexer/broll_index/ffmpeg_tools.frames_match` needs no change; its docstring's "comp-broll-tiers-3 is the open question" sentence can now say it was answered.
- webapps-tools: `tools/release.ps1` and `tools/release_macos.sh`: nothing is strictly owed (the release WORKFLOWS now set `CCSYNC_REQUIRE_FFMPEG=1`), but the two scripts are where `CCSYNC_REQUIRE_RCLONE=1` lives, so a local release cut from a terminal still skips those twenty tests. Setting it there too is the tidy finish; only do it beside an ffmpeg the machine actually has.

### Deploy order

- **Either, with one exception.** Everything in CR-284 is companion-side and
  safe against a 0.7.49 dashboard: the one new wire key (`insert.known`) is
  read optionally and nothing sends it yet.
- The exception is the pair CR-284F + CR-284I. Taking a clip live before its
  original is on the NAS (CR-284I) makes every such clip answer
  `original_rel: null`, which is precisely the state CR-284F fixes. They are
  in the same build, so no ordering is needed - but neither may be
  cherry-picked without the other.
- **CR-284H is DASHBOARD FIRST**, per the contract. A dashboard that does not
  declare `standins_placed` drops it (`extra="ignore"`), and the companion's
  reader treats a missing `standins_known` as "this dashboard does not know",
  which is exactly today's behaviour - so a companion shipped first is inert
  rather than wrong, and a dashboard shipped first simply has nothing to
  record until the companions arrive.
- CR-284K changes CI and both release workflows; it must land before the next
  release is cut, or the release runner will fail on a missing ffmpeg it was
  never asked to install.

### Owner decisions

- **A clip with no original inserts the PREVIEW, not the editing proxy.**
  proxy-tiers-2 suggested inserting the editing proxy where one exists, since
  it is better quality. It is also a file the server only THINKS is there
  (the same listing that was wrong about the original), and a failed fetch
  fails the insert, whereas the preview is the one file the archive always
  has. If the owner wants the editing proxy used, it should be a
  `preview_only` variant that falls back to the preview when the fetch
  refuses.
- **A failed IMPORT does not retire the stand-in ledger row.** proxy-tiers-6
  asked for it. It would re-open CR-282C's hole - a stand-in on disk with no
  row is the one failure the ledger exists to prevent, and a render would
  then render 1080p under a 6K name. With the extension allow-list the
  scenario it was for (an unopenable `.mxf` stand-in re-imported for ever)
  cannot arise.
- **`upgrade_attempts` is 8 and lives on the ledger row.** In memory it would
  be handed back by every restart, which is the shape the finding is about. A
  smaller ceiling would give up on a slow NAS; a larger one is most of a day
  of worker children.
- **The archive exemption's TTL is 60 s.** Long enough to turn twenty probes
  a minute into one, short enough that a proxy landing shows up in the
  missing count while the editor still remembers doing it.
- **The CI ffmpeg install is `continue-on-error`, the release one is not.**
  A broken package feed must not red a CI run about our own code (the tests
  fall back to skipping, exactly where they were), but a release that cannot
  run the coverage it is being cut on should stop. If the owner would rather
  a release never blocked on choco/brew, drop `CCSYNC_REQUIRE_FFMPEG` from
  the two release workflows and the skip comes back.
- **CR-284H reports EVERY ledger entry, stale or not, and a fleet "yes" is
  conclusive.** A stale row still describes a project that was cut against the
  stand-in's geometry, and the cost of a "yes" that turns out not to matter is
  one `ReplaceClip` on the clip's own path, which CR-284R then remembers. The
  cautious alternative (report only live stand-ins, treat the answer as a
  hint) leaves the wired rig demuxing for exactly the clips the feature exists
  for.
- **An earlier reply's knowledge survives a reply that carries none.**
  Forgetting on every silent reply would make one dashboard restart cost a
  full archive demux.
- **comp-resolve-6 is fixed by reading the proxy back, not by planning one.**
  The verifier could not confirm what `ReplaceClip` does to an attached proxy
  without a live Resolve. Reading it back costs one property read and needs
  no change to `plan_relinks`' `.mp4` rule (audit F1). The live check on the
  wired rig is still owed and is already on CR-281's list.
