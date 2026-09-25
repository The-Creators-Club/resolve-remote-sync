# Verifier med-04 (2026-09-25)

Judged against HEAD (`git show HEAD:<path>`), read-only. Seven findings.

## bug-comp-core-3 - CONFIRMED (medium)

The mechanism holds. `site_mod.refresh_site` has exactly one caller: a single fire-and-forget thread in `App.start()` (app.py:9342-9356). `save_site` is called only from `refresh_site`. No report reply carries the manifest. `feature_enabled` reads only the cache (site.py:278-298). A companion that started while the dashboard was unreachable therefore never refreshes the manifest for the rest of the process. A flag flipped on the dashboard (`auto_update` at app.py:7778/7810, `youtube_download`) reaches no running companion until its tray restarts. site.py's own docstring says `refresh_site()` is "for any long-running caller that wants to keep it current", and the tray is not doing that. The 2026-08-21 hunt fixed a neighbour (YtDlpManager never starting). broll_server's origin list got a TTL for the same reason (comp-broll-music-2), but its TTL rereads the same stale cache. Medium is right: an operator's switch silently does nothing across the fleet for days.

Evidence: `git grep refresh_site|save_site|fetch_site HEAD -- companion/src`, read of site.py:230-315 and app.py:9335-9360.

## bug-comp-core-4 - DOWNGRADE (low)

The mechanism is real. `verify_credentials` (identity.py:320-328) sends no `arch`. `VerifyIn` (api.py:2079) does not declare one, so `getattr(payload, "arch", None)` is None, and `_arch_matches` offers everything. api_verify passes no `withheld`, so the reply never carries `upgrade_none_reason`. `app.sign_in` then feeds `{"upgrade": X}` to `note_report_response`, and that clears a standing refusal when no offer and no reason are present (upgrade.py:1561-1592). The client deliberately does not check arch (upgrade.py:1428). But this happens only at an interactive sign-in, which is rare. For (a), the swap guard rolls the wrong-CPU binary back (REL-16's own text says so), and the next report, which carries arch, withdraws the offer. The cost is one wasted download and swap on an Intel Mac, and only with `auto_update` on. For (b), the only loss is a diagnostic: the `[ REFUSING x ]` chip and the alert disappear. It needs a sign-in during a standing refusal of a withheld build. Both are real consistency holes on a rare path with a self-correcting or display-only result.

Evidence: read identity.py:305-360, app.py:6495-6510, api.py:2079-2084 and 2200-2235, `_upgrade_info` withheld branches (api.py:5774-5841), upgrade.py:1420-1440 and 1543-1592, KNOWN_BUGS REL-16.

## bug-comp-core-5 - CONFIRMED (medium)

The mechanism holds. `refresh_once` (manifest.py:316-347) samples `_root_is_present()` once, BEFORE `scan_local_manifest`. `os.walk(project_dir)` has no `onerror`, so a scandir failure on a vanished volume yields nothing. A `size_fn` OSError is `continue`d. The result then replaces the cache unconditionally. Every project not yet walked when the drive goes becomes a 0/0 rollup. Later refreshes are then skipped because the root is absent, so the zeros persist for the WHOLE time the drive is unplugged, not only 10 minutes. The reporter sends `manifest_cache.get` with no presence gate (app.py:2152). This is exactly the "indistinguishable from deleted" report the docstring says the guard exists to prevent. It depends on a race with a walk of up to several minutes, while a drive pulled mid-activity is an expected event (CR-92). The consumers found are the health colours and presence rollups (health.py, api.py:465-498), so the result is a wrong view, not data loss. Medium stands.

Evidence: read manifest.py:150-360. `git grep manifest_cache|root_is_present` in app.py and reporter.py. `git grep n_originals` over the dashboard.

## bug-comp-media-2 - REFUTED (intended)

The companion applying its own flat `jobs_idle_seconds` on top of the dashboard's per-kind floor is the documented design. docs/CONFIG.md's row for `jobs_idle_seconds` says: "THE DASHBOARD HAS ITS OWN FLOOR PER KIND (300 s for whisper and proxies, 60 s for audio and peaks) and both have to pass -- this key is the machine's own answer and it is never loosened by the server's". So the 60 s floor is a server-side ceiling that takes effect where a machine lowers its own key. The base-rig exemption is likewise the dashboard's offer filter only. The documented ways past the companion's gate are the tray volunteer and a forced (`--now`) job, both of which `_gate` implements (jobs_runner.py:729-747). The rank is a 60 s grace period, not a filter (CLAUDE.md), so a base rig that declines leaves the job to the next machine rather than stranding it.

Evidence: read jobs_runner.py:250-275, 580-600 and 720-760, dashboard jobs.py:45-60 and 855-890, docs/CONFIG.md:675-700, config.py:1465-1485.

## bug-comp-media-3 - DOWNGRADE (low)

The mechanism is real. `_media_paths` (jobs_runner.py:1226) takes `out_stem` from the job inputs unchecked, after `job_paths.resolve` has carefully refused absolute and climbing `rel_path`/`out_rel`. `out_dir / f"{stem}{ext}"` then lets an absolute stem or `..` escape, and `/` or `:` misplace the file. However, `POST /api/v1/jobs` is admin-only (api.py:10692-10697), and the other submitter is the in-process Cards engine. The "write anywhere" case therefore needs an admin, who already controls what code the fleet runs. The realistic case is a multicam name containing `/` or `:`. MulticamPipeline's own standalone engine writes `os.path.join(lite_dir, name + ".peaks")` with the same unsanitised name (library_engine.py:3154), so that is a shared naming defect, not one the fleet executor introduces. It is worth the one-line validation, but it is low.

Evidence: read jobs_runner.py:1200-1227 and api.py:10692-10718. `git grep out_stem` in both repos. Read library_engine.py:3128-3178 (MulticamPipeline HEAD).

## bug-comp-media-4 - CONFIRMED (medium)

The mechanism holds and reproduces. `_peaks` (jobs_media.py:916-939) discards the probed codec and runs `peaks_cmd`. On a video-only file ffmpeg exits non-zero, and the `code != 0` branch raises `MediaJobError(err)` with the default retryable=True. The non-retryable "no audio to draw" branch is reached only on exit 0. `_audio` and `_proxy` both short-circuit a missing track as `retryable=False`. The input is realistic: the Cards engine submits peaks for the reference WAV "or the clip's own media when it has none" (library_engine.py `peaks_state`), which can be a video-only angle. The peaks retry budget is 4 (db.py JOB_RETRY_BUDGET) and each failure puts that machine on a 120 s cooldown for every kind. After that the job pins onto the dashboard's engine, which fails it too.

Evidence: scratchpad run with ffmpeg on PATH. A 1 s video-only mp4 through the exact argv (`-loglevel error -i vonly.mp4 -vn -ac 1 -ar 8000 -f s16le -`) printed "Output file does not contain any stream", gave a non-zero exit and wrote 0 bytes. Also read jobs_media.py:800-940 and db.py:10081-10115.

## bug-comp-media-6 - CONFIRMED (medium)

The arithmetic holds. `affected` is every item on the track with `GetEnd() > rec` (music_worker.py:361), which includes a clip with `GetStart() < rec`. That clip is re-appended at `start + shift` with its full duration, so its span `[start+shift, start+shift+dur)` always overlaps the new cue's `[rec, rec+shift)`, because `dur > rec - start`. There are two outcomes. If Resolve refuses the occupied span (which the module's own `place()` verify assumes), the `GetStart()` check raises "ripple failed" and the insert rolls back every time. If Resolve overwrites, the verify passes and the new cue's tail is silently destroyed. Both are wrong for the ordinary "drop a sting in the middle of the bed" case. No KNOWN_BUGS or earlier-hunt entry covers it. Resolve's overlap behaviour was not measured live (scriptapp() is forbidden), but either branch is a defect.

Evidence: read music_worker.py:250-430. `grep -a straddl` over KNOWN_BUGS.md and docs/bug-hunt-*.md found nothing relevant.

## Duplicates

None within the group.
