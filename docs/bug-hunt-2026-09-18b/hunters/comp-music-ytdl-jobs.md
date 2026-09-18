# comp-music-ytdl-jobs - the companion's music, YouTube-downloader and fleet-jobs files

Files read (with approximate coverage):
- `git diff` over the whole territory FIRST. Only four of my files are touched
  by today's fix pass: `music_clap_sidecar.py` (`host_allowed`, `_is_loopback`,
  the `ensure()` call site), `broll_vlm_sidecar.py` (`host_allowed`),
  `ytdl_cookies.py` (`install_text`), `ytdl_executor.py` (the edit-ready `rc`).
  All four carry `comp-music-ytdl-jobs-N` comments citing this morning's
  findings 1/3/4/5; finding 2 was fixed entirely in the tests.
- Tests in the diff: `tests/test_music_clap_sidecar.py`,
  `tests/test_ytdl_cookies.py`, `tests/test_ytdlp_manager.py`,
  `tests/test_jobs_media.py`, plus `tests/conftest.py`'s new
  `require_ffmpeg_or_skip`, and `tests/test_bug_hunt_2026_09_18_companion_media.py`
  (the new regression file's music/ytdl half).
- New ground this round (the morning's coverage note named these as unread):
  `ytdl_browser_login.py` (100%), `job_paths.py` (100%), `jobs_runner.py`
  (~55%: the child runner, `_terminate`, `_post_result`, `_note_finished`,
  `_whisper_command`, the loop/gate), `music_server.py` (~40%),
  `music_clap_sidecar.py`'s feed half again end to end.
- Read for the other end of a wire, not reported on: `secretfile.py`,
  `broll_vlm/local_runtime.py` (`download_verified`, `_final_url`),
  `sidecar_tools.py`, `ffmpeg_tools._win_creationflags`,
  `E:\Projects\Editing\Resolve\MulticamPipeline\multicam_pipeline\transcripts\whisper_corpus.py`
  (what `pipeline.py transcribe` actually spawns),
  `installer/windows_uninstall.ps1` + `installer/macos_uninstall.sh`,
  `KNOWN_BUGS.md` MEDIA-2 and the onboarding `terminate_bootstrap` entry.

Tests run:
- `companion\.venv\Scripts\python.exe -m pytest tests/test_ytdlp_manager.py tests/test_music_clap_sidecar.py tests/test_ytdl_cookies.py tests/test_jobs_media.py tests/test_bug_hunt_2026_09_11b_comp_ytdl_jobs.py -q`
  -> **244 passed, 1 skipped in 16.18 s**. The same five files at HEAD were the
  11-minute pairing this morning's finding 2 measured, so that fix is real and
  holds in one process.
- `... -m pytest tests/test_broll_ingest.py tests/test_ytdlp_manager.py -q` with
  a scratch `pytest_sessionfinish` plugin (in the scratchpad, not the repo) ->
  220 passed, and 56 threads still alive at session end (see OUT OF TERRITORY).

Verdict on the four fixes in my territory: all four close the scenario they
were written for. `install_text` now creates the `.new` file with
`O_CREAT|O_EXCL|O_WRONLY` and hardens it while it is empty, and the already-open
fd means an icacls that revokes our own access cannot break the write;
`os.replace` still works because DELETE comes from the parent directory's ACE,
which is the same reasoning the pre-fix code already relied on. The
`rc = 1 if code is None else int(code)` change preserves the "missing attribute
is a failure" default. `test_ytdlp_manager.py`'s autouse stub is applied to
every test and the two tests that want the real shape re-patch after it, so
nothing passes vacuously. My findings below are three pieces of ground the
morning's hunt did not reach, plus one neighbour that finding 1's fix opened.

## Findings

### comp-music-ytdl-jobs-1 - a cancelled or HALTED whisper job kills `pipeline.py` and leaves the whisper worker (and the GPU) running
- Severity: medium
- Confidence: CONFIRMED
- Where: `companion/src/ccsync_companion/jobs_runner.py:1496` (`_terminate`), spawned at `:1272` with `creationflags=_win_creationflags()` (`:1548`, CREATE_NO_WINDOW only); the grandchild is `E:\Projects\Editing\Resolve\MulticamPipeline\multicam_pipeline\transcripts\whisper_corpus.py:535` (`subprocess.Popen(full, ...)`)
- What: `_run_child` spawns `<whisper venv python> pipeline.py transcribe`, and
  that process is not the worker: `whisper_corpus.run_worker` Popens a SECOND
  process which is the one that loads the model, holds the VRAM and writes the
  transcripts. `_terminate` calls `proc.terminate()` / `proc.kill()` on the
  parent only, with no process group and no job object, so on Windows
  (TerminateProcess) and on macOS (SIGTERM, default action, no cleanup) the
  worker is orphaned and runs to completion.
- Failure scenario: an admin presses `POST /api/v1/jobs/<id>/cancel` on a held
  whisper job, or a FLEET HALT arrives, or the editor quits the tray. The
  runner reports `cancelled` / "a fleet halt stopped this job" within a
  heartbeat and the machine goes back to idle - while an orphaned whisper
  worker keeps the GPU for the rest of the run, keeps writing into the
  episode folder, and is invisible to the tray, the dashboard and
  `stop_current()`. The machine then reports idle and can claim the NEXT
  whisper job, so two workers contend for the same VRAM. A fleet halt is a
  safety latch (CLAUDE.md, `docs/SYNC_SAFETY.md`) and this one does not stop
  the work it says it stopped.
- Evidence: read both sides. `_win_creationflags()` returns
  `subprocess.CREATE_NO_WINDOW` and nothing else - no
  `CREATE_NEW_PROCESS_GROUP`, no `start_new_session`, no taskkill. The repo
  already has the correct shape elsewhere and says so: `KNOWN_BUGS.md:7579-7581`
  ("`Popen` in its own process group (`CREATE_NEW_PROCESS_GROUP` /
  `start_new_session`) ... `terminate_bootstrap` takes the whole tree down
  (`taskkill /T /F` on Windows ...; `os.killpg` elsewhere)"), and
  `supervisor.py:454`, `sync/syncthing_supervisor.py:267`,
  `broll_vlm/local_vlm.py:169` and `bpg.py:878` all pass the group flag.
  `jobs_runner.py` is the one child-spawner in this territory that does not.
  MEDIA-2 fixed the same class for the ingest ffmpeg but only for a DIRECT
  child.
- Ledger: new (MEDIA-2 is the direct-child case and is FIXED; nothing in
  `KNOWN_BUGS.md` covers the jobs runner's grandchild - grepped `-an` for
  `jobs_runner`, `_terminate`, `orphan`, `taskkill`)
- Suggested fix: spawn the pipeline with
  `CREATE_NEW_PROCESS_GROUP` / `start_new_session` and make `_terminate` take
  the tree down (`taskkill /T /F /PID` on Windows, `os.killpg` elsewhere),
  exactly as `onboarding`'s `terminate_bootstrap` already does; fall back to
  the current single-process terminate when the group spawn is unavailable.

### comp-music-ytdl-jobs-2 - the browser sign-in leaves a live Google session in `~/.ccsync/yt-login-profile` with no ACL, forever
- Severity: medium
- Confidence: CONFIRMED
- Where: `companion/src/ccsync_companion/ytdl_browser_login.py:517-525` (`profile.mkdir` then `os.chmod(profile, 0o700)`), against `companion/src/ccsync_companion/secretfile.py:1-23` and `ytdl_cookies.install_text`
- What: the sign-in flow deliberately KEEPS the Chromium profile ("so 'sign in
  again' is instant", module docstring), and that profile's
  `Default/Network/Cookies` plus `Local State` are the same live Google
  session the module goes to such lengths to protect in `cookies.txt`. The
  profile directory gets `os.chmod(0o700)` and nothing else. `secretfile.py`'s
  own docstring states the rule this breaks: "Windows has no mode bits at all,
  so `os.chmod` there only toggles the read-only attribute and does nothing
  whatsoever about who may read the file". So on Windows - "where most of this
  fleet's editors are", same docstring - the whole profile sits at whatever
  the profile directory's inherited ACL is.
- Failure scenario: an editor on a shared or domain-joined Windows box signs
  in once. `cookies.txt` beside it is owner-only (and today's fix makes it
  owner-only from the first byte), but any other local account, or anything
  running as them, can copy `~/.ccsync/yt-login-profile` wholesale and get a
  signed-in Google session out of it. Nothing ever removes the profile: it is
  not deleted when the cookies are marked stale or expired
  (`ytdl_cookies.mark_stale`), there is no sign-out action anywhere (grepped
  the whole package for a caller of `profile_dir` - there is exactly one, the
  launcher), and the default uninstall keeps `~/.ccsync`
  (`installer/macos_uninstall.sh:15` - `--full` is opt-in;
  `installer/windows_uninstall.ps1:22` deletes only `~/.ccsync\state`). So the
  session outlives the feature being turned off and the product being
  uninstalled.
- Evidence: `grep -rn "profile_dir\|yt-login-profile"` over
  `companion/src/ccsync_companion/` returns only the definition at :192 and
  the single use at :517. `secretfile.harden` (the cross-platform answer, used
  for `identity.json`, `config.toml` and the cookie jar) is never called on
  this path. Note that a naive `harden(profile)` is not enough either: its
  icacls line is `/inheritance:r /grant:r <owner>:(R,W)` with no `(OI)(CI)`,
  so it would not reach the files Chromium writes inside.
- Ledger: new (extends the COMMERCIAL_READINESS item 5 work that
  `secretfile.py` exists for, and is the same class as this morning's
  comp-music-ytdl-jobs-4, which hardened the 2 KB copy and left the 40 MB
  original alone)
- Suggested fix: harden the profile directory WITH container/object
  inheritance before the browser is launched (an `(OI)(CI)` variant of
  `secretfile.harden`), and give the feature a "forget this sign-in" that
  deletes both `cookies.txt` and the profile - wired to the same place
  `mark_stale` / the uninstaller already reach. If keeping the profile is not
  worth the exposure, delete it in `_shutdown` and drop the "instant re-sign-in"
  claim from the docstring.

### comp-music-ytdl-jobs-3 - killing yt-dlp does not kill the ffmpeg it spawned
- Severity: medium
- Confidence: CONFIRMED
- Where: `companion/src/ccsync_companion/ytdl_executor.py:2013` (`_kill_proc`, `proc.kill()`), spawn at `:483` (`creationflags=ytdlp_manager._win_creationflags()`), and the timeout path at `:514`
- What: the same shape as finding 1, in the downloader. yt-dlp runs ffmpeg as
  its own child for the merge/remux/postprocess step of essentially every
  DASH download. `_kill_proc` kills the yt-dlp process alone; the ffmpeg
  grandchild keeps running and keeps its handles on the `.part` / output
  files.
- Failure scenario: a lease is lost (`lose_lease`, a 410 from the dashboard),
  or the job is cancelled, or the spawn races the lease check at `:2010`, at
  the moment yt-dlp is merging a 4K video. The companion logs "stopping; the
  server downloads what is missing" and moves on, while an orphaned ffmpeg
  finishes writing. On Windows that open handle is what makes
  `clear_partials` / `clear_aside_originals` (`:1362`, `:1384`) fail to remove
  the file, so the editor is left with a partial next to the real download -
  the exact symptom MEDIA-2 recorded for the ingest ffmpeg
  ("holding a handle on the staged file (which then blocks any later staging
  cleanup on Windows)"), one process further out.
- Evidence: read `_kill_proc` and the spawn; `ytdlp_manager._win_creationflags()`
  (`:1548` of jobs_runner is a copy of the same three lines) is CREATE_NO_WINDOW
  only. No process group, no `taskkill /T`, no ffmpeg pid tracked anywhere in
  the module (`grep -n "ffmpeg" ytdl_executor.py` finds the separate
  edit-ready conversion, which is our own direct child and therefore fine).
- Ledger: new (MEDIA-2 is FIXED for the ingest's direct ffmpeg child and does
  not cover this)
- Suggested fix: as finding 1 - spawn yt-dlp in its own process group and kill
  the group. One helper shared by `jobs_runner`, `ytdl_executor` and anything
  else that spawns a spawner would be better than a fourth copy of
  `_win_creationflags`.

### comp-music-ytdl-jobs-4 - the CLAP allow-list is now a tautology, and an https feed can redirect to http unchecked
- Severity: low
- Confidence: CONFIRMED
- Where: `companion/src/ccsync_companion/music_clap_sidecar.py:245-257` (the new feed-host branch) with `planned_urls` at `:270` and `music_clap/music_models.py:143` (`urls`); the redirect side is `broll_vlm/local_runtime.py:249` (`_final_url`) and `download_verified`
- What: this morning's finding 1 was real and the fix is the right call, but
  it closes the gate on itself. Every URL `ensure()` checks comes from
  `planned_urls` -> `music_models.urls(feed_base(cfg, site))`, i.e. it is
  `feed_base` plus a filename, so the new `host == base_host` test can never
  be false. After the fix the only thing the allow-list still decides is the
  SCHEME. Two consequences the fix comment does not claim: (a) a typo'd or
  spoofed `release_feed_base` arriving on `/api/v1/site` is now accepted with
  no second opinion at all, and (b) `download_verified` goes through
  `urllib`'s default redirect handling, which happily follows an https->http
  hop, so even the surviving scheme test is advisory - the https promise in
  the new docstring is not enforced past the first request.
- Failure scenario: the dashboard's `DASH_RELEASE_FEED_URL` is wrong or
  hostile; the companion fetches 280 MB from it in the clear over a redirect.
  The sha256 pin still stops a swapped artefact, and the artefact is a public
  model, so the loss is confidentiality and bandwidth rather than integrity -
  which is why this is low and not medium. It matters because the docstring
  now describes a gate that no longer gates.
- Evidence: `music_models.urls` is `FEED_URL_TEMPLATE.format(base=base, filename=name)`
  for both names and raises on an empty base, so the host of every planned URL
  IS `base_host` by construction. `local_runtime` has no scheme or host check
  on the response: `_final_url` takes `resp.geturl()` and reuses it for the
  parallel workers. CLAUDE.md's "No dashboard call follows a redirect" rule
  carves out exactly one caller (`release_feed.py`, https-only and
  signature-verified) and says it "is not precedent"; this is a second one.
- Ledger: "CR-286-class fix opens a neighbour" - the fix for
  comp-music-ytdl-jobs-1 (2026-09-18) is correct but leaves its own docstring
  overstating what remains
- Suggested fix: keep the behaviour and say what it is (scheme check plus "the
  URL is the configured feed's"), and push the real control down into
  `download_verified`: refuse a redirect that leaves https, or re-run the
  caller's host predicate on `resp.geturl()`. A `host_allowed` hook on the
  download is what would make both sidecars' gates mean something.

### comp-music-ytdl-jobs-5 - `signed_in()` matches a domain by substring, and `netscape_text` sanitises a cookie value but not a cookie name
- Severity: low
- Confidence: CONFIRMED
- Where: `companion/src/ccsync_companion/ytdl_browser_login.py:435-443` (`signed_in`) and `:469` (`netscape_text`'s skip test)
- What: two small inconsistencies in the same file. `relevant()` two lines
  above does the correct domain test (`dom == s or dom.endswith("." + s)`);
  `signed_in()` does `"youtube.com" in dom`, which is the bare-suffix shape
  CLAUDE.md and `host_allowed`'s own comment warn about
  ("evil-youtube.com.attacker.test" contains it). And the line-injection guard
  skips a cookie when the NAME holds a tab or the VALUE holds a tab or a
  newline, but never when the name holds a newline, and never for `\r` in
  either; `domain` and `path` are not checked at all.
- Failure scenario: neither is exploitable from outside the editor's own
  browser profile, which is why this is low. The reachable version is a
  malformed cookies.txt: one crafted or corrupt cookie name/domain adds a line
  break to the file, `ytdl_cookies.validate` then reads the rest of the jar as
  a different record, and the editor is told their sign-in is invalid with no
  hint why.
- Evidence: read both functions side by side with `relevant()` between them.
- Ledger: new
- Suggested fix: reuse `relevant()`'s domain predicate inside `signed_in()`,
  and reject any field containing `\t`, `\n` or `\r` (name, value, domain and
  path) in one test.

## Coverage note
- `ytdl_executor.py` is 3,454 lines; between this round and the morning's I
  have read maybe 45% of it. `_download_all` / `_download_one`, `build_argv`,
  the cookie/PO-token fallback ladder and the breaker arithmetic are still
  only skimmed.
- `music_ingest.py`'s per-item pipeline, `music_worker.py`'s dispatch and
  `music_clap_sidecar.py`'s DSP half (`decode`, `windows`, `embed_windows`,
  `peaks`) remain unread by me in both rounds - the morning's report says the
  same, so this is the largest hole in the territory. `ingest_kinds.py`,
  `youtube_import.py` and `ytdl_attestation.py` I re-read only where the diff
  or a wire touched them. I tried to hand the music trio to a subagent and the
  fleet's concurrency limit refused, so it stayed undone rather than being
  done badly.
- `jobs_media.py` I read only around the spawn/kill path (its ffmpeg is a
  direct child, so findings 1 and 3 do not apply to it).
- The suite does not cover, anywhere I could find: what happens to the whisper
  WORKER when a job is cancelled (every jobs test injects a fake runner, so
  the grandchild does not exist in any of them); the browser profile's
  permissions or its lifetime (`test_ytdl_browser_login.py` drives the flow
  with a fake browser, which is right, but nothing asserts the profile is
  protected or ever removed); and a redirect that changes scheme during
  `download_verified`.
- I touched no live system: no Resolve, no NAS, no dashboard, no `~/.ccsync`,
  no YouTube. Scratch files went to the scratchpad.

## OUT OF TERRITORY
- `companion/tests/test_broll_ingest.py`: 53 `ccsync-broll-heartbeat` threads
  and 3 `ccsync-broll-ingest` threads are still alive at session end (measured
  this round with a scratch `pytest_sessionfinish` plugin). They are benign in
  production - one ingestor per companion - but each parks for up to 30 s in
  `_stop_event.wait`, and this is the leak the morning's report handed to the
  tests lens; today's fix pass added the per-file guard to
  `test_ytdlp_manager.py` only, not the companion-wide autouse fixture the
  finding asked for. The tests lens should decide.
- `companion/tests/test_bug_hunt_2026_09_11b_comp_ytdl_jobs.py:131`
  (`_downloader_on`): the second half of this morning's finding-2 suggested
  fix - patch `install_tool` so the helper cannot reach the network - was not
  taken. It is harmless today only because `pinned_assets` is stubbed to
  `example.invalid`, which cannot resolve.
- `companion/src/ccsync_companion/job_paths.py:104`: the absolute-path refusal
  tests `raw[1] == ":"`, so a Windows alternate data stream
  (`sub/file.mp4:evil`) and the reserved device names (`NUL`, `COM1`) pass
  `resolve()`. Admin-authenticated input only; comp-app or the security lens
  may want a view.
