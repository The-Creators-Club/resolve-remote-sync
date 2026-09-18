# comp-music-ytdl-jobs - the companion's music, YouTube-downloader and fleet-jobs files

Files read (with approximate coverage):
- `companion/src/ccsync_companion/jobs_runner.py` (100%), `jobs_media.py` (100%),
  `job_paths.py` (100%)
- `companion/src/ccsync_companion/music_server.py` (100%), `music_worker.py`
  (the b-roll/link-proxy half and the dispatch, ~60%),
  `music_clap_sidecar.py` (~60%: feed/allow-list/ensure/model_ready),
  `music_ingest.py` (the 09-11b hunks + `_forget_batch_scratch` path, ~25%)
- `companion/src/ccsync_companion/ingest_kinds.py` (100%),
  `broll_vlm_sidecar.py` (~40%: `fits`, the fetch/allow-list half)
- `companion/src/ccsync_companion/ytdlp_manager.py` (~70%: versions, install,
  self_update, ensure), `ytdl_cookies.py` (~50%), `ytdl_server.py` (~60%),
  `ytdl_executor.py` (~35%: FleetClient, edit-ready conversion, swap_in, the
  sweep/disown helpers, the module-level job control), `youtube_import.py`
  (~40%: `_collect`/`scan_once`), `ytdl_common.py`, `ytdl_attestation.py` (skim)
- cross-checks outside the territory, read only: `broll_server.py`'s
  proxy-upgrade caller, `broll_ingest.py`'s `_forget_batch_scratch` call sites,
  `dashboard/src/ccsync_dashboard/api.py`'s `commands.jobs` block,
  `music/web/musicweb/{ingest_batches,routes_ingest,config}.py`,
  `sidecar_tools.py`'s `ensure`/`ensure_ffmpeg_pair`.
- `git diff 34a3c8f..HEAD` and `git diff 18e69f3..34a3c8f` over every file above.

Tests run:
- `companion\.venv\Scripts\python.exe -m pytest tests/test_music_server.py tests/test_music_worker.py tests/test_ytdlp_manager.py -q` -> 244 passed in 15 s
- `... -m pytest tests/test_jobs_media.py tests/test_jobs_runner.py tests/test_bug_hunt_2026_09_11b_comp_ytdl_jobs.py -q` -> 108 passed in 15 s
- `... -m pytest tests/test_jobs_phase4.py tests/test_jobs_resilience.py -q` -> 23 passed in 0.6 s
- `... -m pytest tests/test_ytdl_server.py -q` -> 78 passed in 8 s
- all nine together in ONE process -> **453 passed in 660 s (11 minutes)**; see
  finding 2.

## Findings

### comp-music-ytdl-jobs-1 - the CLAP model allow-list is hard-coded to GitHub, so a fleet whose release feed is anywhere else can never download it
- Severity: medium
- Confidence: CONFIRMED
- Where: `companion/src/ccsync_companion/music_clap_sidecar.py:93` (`ALLOWED_HOST_PATTERNS`) and `:217` (`host_allowed`), enforced at `:465` in `ensure()`
- What: the module comment says the allow-list is "DERIVED: the artefact is
  ours and is served from the site's own release feed, so the allow-list is
  exactly that feed's host plus the hosts a feed on GitHub Releases redirects
  to", and `host_allowed`'s own docstring repeats "The feed's OWN host is
  trusted by definition - it is the one the site manifest named". Neither is
  implemented: `host_allowed` only fnmatches a fixed four-entry GitHub tuple
  and never consults `feed_base(cfg, site)`. The feed host is whatever the
  dashboard published as `release_feed_base` on `/api/v1/site`, or whatever an
  operator put in `music_clap_feed_base`.
- Failure scenario: a customer fleet publishes its release feed from anywhere
  that is not `github.com` / `*.githubusercontent.com` - a self-hosted feed,
  an S3/R2 bucket, or the dashboard's own Tailscale Serve host, all of which
  `release_feed_base` can legitimately name. `ensure()` then returns
  `refusing to download the music indexing model: <their own host> is not one
  of the hosts this build is allowed to fetch from` on every ingest tick, for
  ever. Music indexing is permanently unavailable on every editor machine in
  that fleet, and the sentence blames the admin's own correctly configured
  feed, so there is no action that fixes it short of a new companion build.
  The same line kills the `music_clap_feed_base` override that `feed_base`'s
  docstring offers for "a base rig or a dev loop pointing at a local directory
  server": `http://...` fails the scheme test and a LAN host fails the pattern
  test.
- Evidence: from the companion venv -
  ```
  https://dash.example.ts.net/feed/clap.onnx      False
  http://192.168.0.5:8000/clap.onnx               False
  https://nas.local/feed/x.onnx                   False
  https://github.com/x/y/releases/download/a/b.onnx True
  feed_base({'music_clap_feed_base':'https://nas.local/feed'}) -> 'https://nas.local/feed'
  planned_urls(...) -> {'music-clap-audio-1.onnx': 'https://nas.local/feed/music-clap-audio-1.onnx', ...}
  models.is_pinned(DEFAULT_MODEL) -> True
  ```
  i.e. the model IS pinned (so this is live code, not a dormant placeholder
  path) and the planned URLs are refused. This studio is unaffected only
  because its vendor feed happens to be GitHub Releases.
- Ledger: new (nothing in `KNOWN_BUGS.md` for `host_allowed` / `music_clap`;
  grepped with `grep -an`)
- Suggested fix: make the list what the comment says - accept the parsed
  hostname of `feed_base(cfg, site)` (and its redirect targets) in addition to
  the GitHub patterns, keeping the https-only rule for a remote host; the
  sha256 pin is the real guarantee either way. If a purely-GitHub policy is
  actually wanted, the two docstrings and the `music_clap_feed_base` override
  should be deleted rather than left describing behaviour the code does not
  have.

### comp-music-ytdl-jobs-2 - `test_ytdlp_manager.py` leaks a live ytdlp manager thread that holds `sidecar_tools._work_lock` through real GitHub I/O, adding ~11 minutes to the companion gate
- Severity: medium
- Confidence: CONFIRMED
- Where: `companion/tests/test_ytdlp_manager.py:993` (`test_start_with_the_feature_off_still_runs_the_thread`, `mgr.join(timeout=5)`) blocking `companion/tests/test_bug_hunt_2026_09_11b_comp_ytdl_jobs.py:147` (`test_a_full_disk_on_a_youtube_machine_reaches_the_editor`) at `companion/src/ccsync_companion/sidecar_tools.py:447` (`with _work_lock:`)
- What: that test starts a real `YtDlpManager` with `sidecar_tools` UNSTUBBED,
  so the loop thread calls the real `ensure_ffmpeg_pair()`, which takes
  `sidecar_tools._work_lock` and then does real network I/O against GitHub.
  `stop()` only sets an event; `join(timeout=5)` returns while the thread is
  still inside that call, and the daemon thread survives the file with the
  module lock held. A later test in the same process that calls
  `sidecar_tools.ensure({})` blocks on the lock until the leaked thread's
  network call finishes. The comment at `test_ytdlp_manager.py:969` documents
  exactly this hazard and stubs it out for ONE test only.
- Failure scenario: `tools\run_all_tests.ps1` runs the companion suite in one
  pytest process, so this pairing is the normal gate. Measured here: the nine
  files run separately take ~40 s in total; the same nine in one process take
  **660 s**, essentially all of it in that one test (two `ensure()` calls, ~5
  min each). On a CI runner where the GitHub connection hangs rather than
  fails the wait is the socket timeout, not 5 minutes - and this is the test
  suite reaching the public internet, which is also why 214869b and 3c7cf8e
  existed.
- Evidence: reproduced deterministically.
  `pytest tests/test_bug_hunt_2026_09_11b_comp_ytdl_jobs.py -q` -> 23 passed
  in 0.82 s; `pytest tests/test_ytdlp_manager.py tests/test_bug_hunt_2026_09_11b_comp_ytdl_jobs.py -q`
  -> exceeds 115 s. A scratch pytest plugin dumping threads at the start of
  the slow test printed
  `THREADS: ['MainThread', 'ccsync-ytdlp', 'ccsync-broll-ingest', 'ccsync-broll-ingest', 'ccsync-broll-ingest']`
  and a 30 s faulthandler dump put the main thread at
  `sidecar_tools.py:447 in ensure_ffmpeg_pair` (the `with _work_lock:`), with
  the leaked `ccsync-ytdlp` thread live. Calling the same `ensure({})` in a
  fresh interpreter with the test's own monkeypatches returns in 0.0 s.
- Ledger: new (related to the 2026-09-11b hand-off note in
  `test_ytdlp_manager.py:969`, which fixed the symptom for one test only)
- Suggested fix: stub `sidecar_tools.ensure` / `ensure_ffmpeg_pair` in
  `test_start_with_the_feature_off_still_runs_the_thread` (and anywhere else
  a real `YtDlpManager` is started), and add a companion-wide autouse
  conftest fixture that fails a test which leaves a `ccsync-*` thread alive -
  three `ccsync-broll-ingest` threads are leaking from another suite too.
  Separately, `_downloader_on` in the 09-11b test file should patch
  `install_tool`, so the test cannot reach the network at all.

### comp-music-ytdl-jobs-3 - `broll_vlm_sidecar.host_allowed` accepts an `http://` URL; its music sibling refuses one
- Severity: low
- Confidence: CONFIRMED
- Where: `companion/src/ccsync_companion/broll_vlm_sidecar.py:400-406`, against `music_clap_sidecar.py:217-232`
- What: the b-roll VLM's allow-list gate tests only the hostname. The music
  one tests `parts.scheme != "https"` first. A pinned catalogue entry (or a
  future per-site override of it) spelled `http://github.com/...` would pass
  the b-roll gate and be fetched in clear.
- Failure scenario: today the catalogue is vendored and every URL is https, so
  nothing is exploitable; the moment the b-roll model URLs become
  site-derived the way the CLAP ones already are, the weaker of the two gates
  is the one that ships. The sha256 pin still prevents a swapped artefact, so
  the exposure is confidentiality/traffic analysis, not integrity.
- Evidence: read both functions side by side; `broll_vlm_sidecar.host_allowed`
  never touches `urlsplit(url).scheme`.
- Ledger: new
- Suggested fix: add the same `scheme != "https"` refusal to
  `broll_vlm_sidecar.host_allowed`, or factor the two into one helper.

### comp-music-ytdl-jobs-4 - the YouTube cookie jar is written to a temp file before it is hardened, contrary to the comment beside it
- Severity: low
- Confidence: CONFIRMED
- Where: `companion/src/ccsync_companion/ytdl_cookies.py:199-201`
- What: the comment says harden() "hardens the TEMP file before the rename so
  the secret is never briefly world-readable", but the order is
  `tmp.write_text(text)` -> `secretfile.harden(tmp)` -> `os.replace`. The
  bytes of a live Google session therefore exist on disk under the inherited
  ACL (Windows) or the umask (posix) for the duration of the write plus the
  harden call.
- Failure scenario: an editor machine whose profile or `~/.ccsync` is on a
  share, or has a broad inherited ACL, exposes the signed-in cookie jar to
  any local reader for that window. Small, but this is the one file in the
  tree that is a logged-in Google account, and the code already takes the
  trouble to say it does not happen.
- Evidence: read `install_text`; `secretfile.py` exposes only `harden(path)`
  (no create-then-write helper), so there is no atomic path today.
- Ledger: new
- Suggested fix: create the temp file with `os.open(..., O_CREAT|O_EXCL|O_WRONLY, 0o600)`
  (and call `secretfile.harden` on the empty file on Windows) before writing
  any bytes into it.

### comp-music-ytdl-jobs-5 - a `None` returncode from the edit-ready conversion reads as success
- Severity: low
- Confidence: PLAUSIBLE
- Where: `companion/src/ccsync_companion/ytdl_executor.py:2515` (`rc = int(getattr(proc, "returncode", 1) or 0)`)
- What: `X or 0` maps `None` to `0`, and `0` is the success branch. The
  default when the attribute is missing is `1` (correct), but a completed
  object whose `returncode` is `None` is read as "ffmpeg succeeded". The
  `not tmp.exists()` test below catches the common case, so the reachable
  damage is limited to a conversion that produced a file and reported no
  code.
- Failure scenario: any `deps.run` implementation that returns before the
  child is reaped (a future async runner, or a test double) delivers a
  half-written `.editready.mp4` straight into `swap_in`, which then deletes
  or renames aside the good original.
- Evidence: read; `_call_run` -> `deps.run` is an injected seam, and
  `subprocess.run` happens to always set `returncode`, which is why this has
  not bitten.
- Ledger: new
- Suggested fix: `code = getattr(proc, "returncode", None); rc = 1 if code is None else int(code)`.

## Coverage note
- `ytdl_executor.py` is 3,447 lines and I read about a third of it: the fleet
  client, the conversion/swap path, the sweep helpers and the module-level job
  control. `_download_all`, `_download_one`, `build_argv`, the cookie/PO-token
  fallback ladder and the breaker arithmetic were skimmed only, and
  `ytdl_browser_login.py` (678 lines, a pty-driven browser sign-in) was not
  read at all - it is the most likely remaining home for a security finding in
  this territory.
- `music_clap_sidecar.py`'s DSP half (`decode`, `windows`, `embed_windows`,
  `peaks`, `content_hash`) and `music_ingest.py`'s per-item pipeline were not
  read; the base-rig fallback (`queued_for_base_rig`) was only checked for
  contract parity against `musicweb.ingest_batches`.
- The suite does not cover, anywhere I could find: a `jobs_media` recipe whose
  `_publish` loses the race to a Timeline Cards server mid-encode on a real
  filesystem; `music_clap_sidecar.ensure()` against a non-GitHub feed base
  (finding 1 would have been caught by one assertion); and thread hygiene
  across suite boundaries (finding 2).
- I did not attempt any live system: no Resolve, no NAS, no dashboard, no
  `~/.ccsync`.

## OUT OF TERRITORY
- `companion/src/ccsync_companion/broll_server.py:1203-1223`: when
  `act_broll_link_proxy` answers `not_in_pool` (the editor never inserted the
  clip, or deleted it), the stand-in ledger row stays `UPGRADE_PENDING` for
  ever and every later relink cycle spawns another Resolve worker child for a
  clip that will never be in the pool - comp-broll-tiers should check whether
  that retry is bounded.
- `companion/tests/`: three `ccsync-broll-ingest` threads are alive at the end
  of `test_ytdlp_manager.py` and were started by an earlier suite; the tests
  lens should decide whether a "no leaked ccsync-* threads" autouse fixture
  belongs in `companion/tests/conftest.py`.
