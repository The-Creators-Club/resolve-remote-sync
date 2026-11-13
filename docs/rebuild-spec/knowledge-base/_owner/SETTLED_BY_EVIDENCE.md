# Disagreements in the knowledge base, settled from the code and the record

This file stays behind (working record for the merge; it may name files, functions and commits).

Read-only research, 2026-11-13. "HEAD" means `E:\Projects\Editing\ccsync` at 9fa8152 and `E:\Projects\Editing` (MulticamPipeline, resolve-relink) at 94cbab7. Where a fact about Resolve could only be confirmed by a live test, it says so.

## 1. BRO-011 vs PRX-086
- Verdict: Case handling depends on the volume. Editors' Windows disks and the SMB drive letters fold case, and so does a Mac's default disk. The NAS's own ZFS file system keeps case: a case-only rename on the NAS left the old spelling to be uploaded back beside the new one. The b-roll exclusion rule lowercases because every share it scans today is reached through a Windows drive letter. The ledger says that choice reverses if a share is ever scanned directly on the NAS.
- Which wording stands: PRX-086 as written; BRO-011 with this change: "Path comparisons follow each volume's own case rule: editors' Windows and Mac disks ignore case, the NAS itself does not, so a capitals-only rename must not re-index anything."
- Evidence: broll/indexer/broll_index/scanner.py:54-71 (BROLL-16); KNOWN_BUGS.md:9728-9733 (R6, "the NAS holds `youtube` and `Youtube` as distinct folders") and :16738-16744 (CR-234, "the NAS (case-sensitive)"); companion/src/ccsync_companion/file_moves.py:162-194 (`_cmp_key`: folds case on Windows and macOS, not on Linux; CR-94, L-0100).
- Confidence: high. A one-off `zfs get casesensitivity` on the share's dataset would make it certain.

## 2. CRX-016 vs RSV-110
- Verdict: Naming one media type does restrict a placement to that stream. Timeline Cards names the track and both media types: picture (type 1) and sound (type 2) go down in two passes, are linked afterwards, and a cut that got no sound is reported. The companion's b-roll insert names the track but deliberately no media type, so the clip's own sound comes with it. The record measured on 2026-08-09 that a placement on a chosen track brings the sound but leaves it unlinked from the picture. The companion's own comment says a live check of its overlay placement is still owed. Both lessons agree a placement must name its track. Their only real disagreement is "name a media type" against "never pin one", and both work as long as a typed placement places both streams.
- Which wording stands: RSV-110 as written; CRX-016 with this change: "Every placement names its track; naming a media type means placing picture and sound separately and linking them; count only after read-back and report missing picture or sound by track."
- Evidence: MulticamPipeline/multicam_pipeline/cards/resolve_engine.py:2155-2200 (`_place_span`), :2273-2276 ("trackIndex appends carry no linked audio"); ccsync companion/src/ccsync_companion/resolve_bridge.py:2946-2957, :3440-3450 (no mediaType, "a live check ... is owed"); register P-00867, D-tc-reorder-plan-006 (2026-08-09).
- Confidence: medium. A live test would raise it: place a clip with sound on V2 by track only, then read back whether A2 got the sound and whether it is linked.

## 3. CRX-038 vs CRX-042
- Verdict: Resolve's scripting still has no clip-volume setter. Both conform routes (the script conform and the library writer) never write gain, and each one says so in words. The new editor's FCPXML export does write each cut's gain, its fades and baked-in levelling (as `adjust-volume`). OTIO and EDL report gain as dropped. Nobody has confirmed that Resolve's FCPXML import honours those levels: the editor's own record says nothing in it has called a live Resolve. So a carrying route exists, but none is proven. The FCPXML export also tells the person that levelling "is baked into the gain" as if that were settled.
- Which wording stands: CRX-038 as written (its rule, "carry where it can, name what was dropped", matches the code); CRX-042 with this change: "A cut's gain reaches Resolve at the level set, proven by reading back a known level; until proven, every send and export says plainly whether gain was carried."
- State: script sends still open (said, not carried). FCPXML gain export is live in the editor but unverified in Resolve.
- Evidence: MulticamPipeline/multicam_pipeline/cards/project_conform.py:429-438 (`gain_note`); editor/adapters/fcpxml.ts:7, :113-121; editor/features/resolve/exports.ts:17 (`CARRIES_GAIN`), :39-52; editor/adapters/edl.ts:12, otio.ts:14; editor/docs/STANDALONE-REBUILD.md:401.
- Confidence: high on what the code does. Whether Resolve imports the level: cannot tell without a live import of a cut at a known gain.

## 4. PRX-090 vs RSV-096
- Verdict: Both lessons are about the same tool, the standalone resolve-relink utility (built 2026-06-01; 1,559 clips relinked). At HEAD it ranks by longest matching folder-path tail first, then by the root most other clips resolved to. Whatever is still ambiguous goes to a list for the person. Only when "prefer largest" is asked for does the largest file win, with size ties broken by root vote and then by the shortest path. The owner's "largest" ruling is the last step, not the first.
- Which wording stands: RSV-096 as written; PRX-090 with this change: "Among same-named candidates the closest matching folder path wins; only when that leaves a tie does the largest file, the original, beat a proxy; identical backups are no conflict."
- Evidence: E:\Projects\Editing\Resolve\resolve-relink\relink.py:493-512 (`pick_largest`), :640-677 (path-tail, then path-tail+root, then ambiguous, then the `--prefer-largest` pass); register P-00067/P-00068 (2026-06-14), M-home-resolve-relink-utility.
- Confidence: high.

## 5. RSV-115 vs YTD-037
- Verdict: The two lessons describe two different behaviours. The download pipeline (server and companion) converts anything that is not H.264 video with AAC sound, so AV1 and Opus are converted along with VP9. The companion's timeline guard warns about VP9 originals only. The best-dated evidence, a render investigation on 2026-11-01, found that AV1 and HEVC originals rendered fine in Resolve 21 on that machine and only VP9 failed. The earlier note (2026-09-30) grouped "VP9/AV1/Opus" as Media Offline without testing AV1 on its own. So "Resolve cannot decode AV1" is not supported. Converting AV1 anyway is a cautious policy, not a measured need.
- Which wording stands: RSV-115 as written; YTD-037 with this change: "No downloaded clip reaches an editor's Resolve in anything but H.264 with AAC: VP9 fails to decode, Opus flickers offline, and AV1 is converted too though it rendered fine." Its "What was going on" should stop saying AV1 shows as Media Offline.
- State: VP9 guard fixed and live on Windows (in companion 0.9.88, current 2026-11-08); macOS current is older.
- Evidence: companion/src/ccsync_companion/vp9_guard.py:1-11 (CR-380); ytdl/web/ytdlweb/vendor/downloader.py:84-91 (`EDIT_SAFE_VCODECS = {"h264"}`); E:\Projects\Editing\Resolve\MontagePipeline\docs\VP9_MONTAGE_DOWNLOADS_2026-11-01.md:74-75.
- Confidence: medium. It rests on one machine and one Resolve version; a deliberate AV1 render test on another machine would raise it.

## 6. APP-068 vs REL-048
- Verdict: The companion has two separate guards, so both numbers are right. If a new build dies before it finishes starting, two failed starts restore the previous build, with no time window (CR-370, 0.9.86). If a build boots and then crashes, three starts of the same version within 10 minutes restore it (APP-5, 2026-08-28). Both refuse to go below the signed minimum version. A clean quit resets the count.
- Which wording stands: both stand (they are about different things: APP-068 is a build that dies before it has started, REL-048 is a build that starts and then keeps crashing).
- State: fixed and live on Windows. Both guards are ancestors of dd084b6, companion 0.9.88, made current on 2026-11-08. The macOS current build (0.9.84) carries the crash-loop guard but not the early-death one. APP-068's "never shipped" and REL-048's "outcome not found" are both out of date.
- Evidence: companion/src/ccsync_companion/startguard.py:50 (`EARLY_FAILURE_LIMIT = 2`); upgrade.py:120-130 (`CRASH_LOOP_STARTS = 3`, `CRASH_LOOP_WINDOW_SECONDS = 600`), :1134-1150 (floor check); KNOWN_BUGS CR-370 (L-1233).
- Confidence: high for the code. Medium for the shipping state, which comes from the 2026-11-08 ship record and not from the live feed.

## 7. DSH-142 vs DSH-092
- Verdict: Yes, it still does. A server-error notice records the error type, its message (masked for keys and tokens, capped at 700 characters) and the three innermost code locations as repo-relative file:line. Pages show it only to admins (the Health panel requires an admin, and the notices context is marked admin-only). Error pages and the landing page show only the error type and "the log has the detail" (CR-285AH). So the two lessons cover different surfaces. One gap: the masking catches secret-shaped text, but not a host name, user name or path quoted in an exception message.
- Which wording stands: DSH-092 as written; DSH-142 with this change: "Pages show only the kind of error and where the detail is kept; only the admin's problem notice carries a masked, size-limited message and code location."
- State: fixed and live (CR-266b 2026-09-11, CR-285AH dashboard 0.7.50).
- Evidence: dashboard/src/ccsync_dashboard/notices.py:1400-1520 (`error_detail`); ui.py:1890-1896, ui_health.py:54-58 (`_require_admin_page`); crash_report.py:67-95 (what the masking covers); register L-0920.
- Confidence: high.

## 8. PRX-004
- Verdict: The code decides by rule, not by asking Resolve. A timecode printed with colons, at 29.97 or 59.94, from a file with no timecode track (Sony's metadata stream), is always rewritten to drop-frame form. A file that has a timecode track keeps its own form, because there the separator is the real drop-frame flag. That is what fixed 231 Johnny Harris proxies (2026-09-17). What was measured: on 2026-08-12, one live case was refused in colon form and accepted in semicolon form, and Resolve's clip property read "Drop frame: 1". The code admits that a Sony clip genuinely recorded non-drop would get a refused proxy (never a wrong pairing). No such clip is in the record.
- Which wording stands: PRX-004 as written. The right answer to its question is "only when Resolve reads the original as drop-frame". Today the code approximates that with "always, for Sony colon timecode at those rates".
- Evidence: companion/src/ccsync_companion/ffmpeg_tools.py:379-423 (`timecode_from_probe`), :432-475 (`dropframe_normalized`, the 2026-08-12 measurement); broll/indexer/broll_index/ffmpeg_tools.py (same rule).
- Confidence: high on the code. Medium on the camera fact: a Sony clip shot non-drop at 29.97, run through the proxy maker and linked live, would settle it.

## 9. CRX-005
- Verdict: The record contradicts itself, and so does the code. On 2026-08-04, a 24 fps clip on a 29.97 timeline was rate-conformed. On 2026-09-30, three montages showed Resolve giving off-rate cuts their real-time length at the timeline's rate: advancing by source frames made cuts overwrite each other, and the rebuild that places each cut at the previous item's real end came within 0.04 s. Only 2026-08-31 reported frame-for-frame placement leaving gaps. The 2026-09-30 note also found the cut file's clip rates wrong (25 vs 29.97, 29.97 vs 59.94), which may explain the 08-31 reading. At HEAD the conform still advances by source frames (the 08-31 rule) while the insert path assumes rate-conform. Nothing in the record shows that a project setting decides which behaviour you get.
- Which wording stands: CRX-005 as written (the read-back rule holds whichever Resolve does).
- State: still open (conform unchanged since the 2026-09-30 finding).
- Evidence: MulticamPipeline/multicam_pipeline/cards/resolve_engine.py:2544-2549 ("1:1"), :3113-3119 ("speed-conformed by Resolve on insert"); register M-cc-cards-conform-from-base-rig (2026-09-30 paragraphs), M-home-canvas-timeline-tool, C-ed-ee8cf80a3.
- Confidence: low on the Resolve fact. A live test would settle it: place 24, 25, 30 and 59.94 clips (rates read from Resolve) on a 29.97 timeline and read back each item's duration, with any project or clip frame-rate setting changed between runs.

## 10. DSH-106
- Verdict: The settings named in the finding (brand, folder templates, shared folders, the YouTube switch, auto-update) now come from one stored table, with the deploy-time environment only as a fallback. The YouTube mount is checked on every request (5 s cache) and the brand cache is cleared on every save, so none of them needs a restart. Where a deploy-time value also exists, the settings page shows it as "not applied". I found no admin-editable setting that needs a restart, but I did not audit every key.
- State: fixed and live (CR-58, 2026-08-21; every dashboard release since carries it).
- Evidence: dashboard/src/ccsync_dashboard/site_store.py:811-834 (row first, then fallback), :1095-1115 (`invalidate`); ytdl.py:101-110; dashboard/templates/admin_settings.html:91; KNOWN_BUGS CR-58 (line 2118).
- Confidence: medium. A key-by-key check of every reader would raise it.

## 11. SRV-015
- Verdict: The browser set-up wizard and the appliance compose file are built. The customer install document is still marked DRAFT, until someone other than its author has run it end to end, and still lists "not yet true" steps (publishing on the private network was the last open part). There is no record of any customer installing it.
- State: fixed, never shipped (built and partly finished, never delivered to a customer).
- Evidence: docs/APPLIANCE_INSTALL.md:1-17; dashboard/deploy/compose.appliance.yaml; docs/COMMERCIAL_READINESS.md item 15 / ZERO_TOUCH_PLAN.md.
- Confidence: medium. Absence of a customer is inferred from the record, not proven.

## 12. CE3-022
- Verdict: No, not every revision. The new editor keeps an operation log, a snapshot every 200 edits, the last 3 snapshots, up to 100 older log segments and one `.bak` copy of the file, and prunes beyond that. A damaged log is quarantined and the list recovers up to the last good version. A recent window can be rebuilt, but very old revisions are deleted. I found no action that lets a person restore an earlier revision; the only person-facing restore loads an offline copy.
- State: still open as worded ("every revision kept, restorable"). Bounded history is live.
- Evidence: MulticamPipeline/editor/server/sync/store.ts:290-382 (recovery), :772-800 (`.bak`), :869-881 (`prune`); editor/server/sync/options.ts:49-50; editor/server/types.ts:112 (`snapshotEvery: 200`).
- Confidence: medium. I did not trace whether undo or redo reaches past a snapshot.

## 13. CE2-037
- Verdict: In the new editor (the one in use) sections are rows with their own ids. Moving and dragging a section go by that id, and folding goes by the section's title (a repeated title gets "#2"), not by position. So an empty section folds and moves on its own. Placing cuts into an empty section in the middle is still refused, with a sentence telling the person to drag a cut under its heading. I could not find a separate tap-to-place path to check.
- State: fixed and live for fold and drag in the new editor. Placing into an empty middle section is refused with a sentence, not done. The old page cannot tell; it has been retired since dashboard 0.7.80.
- Evidence: MulticamPipeline/editor/features/markers/fold.ts:16-23; editor/core/src/reduce.ts:1046-1059 (`moveSection` by id); editor/features/shelf/test/ops.test.ts:448-457.
- Confidence: medium. A by-hand check on a phone with an empty section between two full ones would raise it.

## 14. CE1-083
- Verdict: Yes. The old page's fix (a second audio element so a same-interview join pre-starts, plus a short edge ramp) was committed on 2026-09-21 (83c48d2) and went out with later Cards deploys. The new editor gives every join a 4 ms ramp, and a browser test measures sample steps at each join, including a control that proves the measurement can fail. The by-ear check the owner was promised is not in the record.
- State: fixed and live.
- Evidence: MulticamPipeline/editor/audio/types.ts:14-19 (`SPLICE_RAMP_S = 0.004`); editor/audio/test/render.browser.test.ts:97-109, :266; multicam_pipeline/cards/page/03-lane.js:2433-2445.
- Confidence: medium-high.

## 15. SRV-S01
- Verdict: Fixed in the appliance compose file. The private-network container runs its daemon directly, without the stock start-up script, so it waits for sign-in without restarting. The dashboard's wizard asks it for the sign-in link and shows it. Publishing is set only after sign-in, through the local API. But that compose file is the customer appliance, which has never been installed anywhere (item 11). The studio's own NAS does not use it. "Fixed and live" overstates it.
- State: fixed, never shipped.
- Evidence: dashboard/deploy/compose.appliance.yaml:470-500; commits 18ef385 and 0615b3d (2026-08-17); dashboard/src/ccsync_dashboard/tailscale_local.py; docs/APPLIANCE_INSTALL.md:9-17.
- Confidence: medium.

## 16. SRV-S07
- Verdict: The deploy has mounted the snapshot folder with follow-the-host propagation since 2026-09-11. Ledger CR-264 calls the live check "still owed" and offers an off switch in case the NAS refuses the option. But the ship record from the same day reports that the 0.7.43 deploy listed a snapshot's contents inside the container ("rslave option WORKS, propagation shared"). The later record is the stronger evidence. It does not say whether the snapshot tested was one nobody had opened recently, which was the hard case.
- State: fixed and live.
- Evidence: server/install_dashboard_app.py:1665-1703 (`snapshot_volumes`), :1734-1756; KNOWN_BUGS.md:19628-19635 and CR-264h (line 23399); register M-cc-ship-2026-09-11-and-hunt-b.
- Confidence: medium. Running `ls` inside the container on a snapshot untouched for an hour, after a NAS reboot, would raise it.
