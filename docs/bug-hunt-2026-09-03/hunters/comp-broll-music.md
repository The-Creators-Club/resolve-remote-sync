# comp-broll-music — the 8899 loopback, b-roll/music ingest, sidecars and ffmpeg plumbing

Files read (with approximate coverage):
- `companion/src/ccsync_companion/loopback_guard.py` (100%)
- `companion/src/ccsync_companion/broll_server.py` (100%)
- `companion/src/ccsync_companion/music_server.py` (100%)
- `companion/src/ccsync_companion/ingest_kinds.py` (100%)
- `companion/src/ccsync_companion/broll_fetch.py` (~90%)
- `companion/src/ccsync_companion/broll_ingest.py` (~65% — persistence, prepare/upload/thumb/run, crunch, fleet client, staging)
- `companion/src/ccsync_companion/music_ingest.py` (~50% — crunch, result, base-rig fallback)
- `companion/src/ccsync_companion/broll_upload.py` (~60%)
- `companion/src/ccsync_companion/broll_ingest_media.py` (~40% — the ffmpeg runner)
- `companion/src/ccsync_companion/ffmpeg_tools.py` (~40% — probes/encoder cache)
- `companion/src/ccsync_companion/sidecar_tools.py` (~60% — pins, download/verify/unpack)
- `companion/src/ccsync_companion/broll_vlm_sidecar.py` (~80%)
- `companion/src/ccsync_companion/music_clap_sidecar.py` (skim — spawn/timeout paths)
- `companion/src/ccsync_companion/app.py` (start-order only, out of territory)
- `companion/tests/test_no_em_dash.py` (100%), skim of `test_broll_server.py`, `test_loopback_guard.py`
- read-only comparison: `broll/web/app/routes_fleet.py`, `broll/web/static/ingest.js`, `music/web/musicweb/{config,ingest_batches,routes_ingest}.py`, `music/web/static/ingest.js`

Tests run:
`companion\.venv\Scripts\python.exe -m pytest tests/test_broll_server.py tests/test_loopback_guard.py tests/test_broll_ingest.py tests/test_music_server.py tests/test_music_ingest.py tests/test_broll_upload.py tests/test_broll_fetch.py tests/test_broll_paths.py tests/test_ffmpeg_tools.py tests/test_sidecar_tools.py tests/test_broll_vlm_sidecar.py tests/test_music_clap_sidecar.py tests/test_broll_ingest_media.py -q`
-> **803 passed, 1 skipped** (133 s). No failures; every finding below is a gap the suite does not cover.

## Findings

### comp-broll-music-1 — the ingest checkpoint file silently stops being written under concurrency
- Severity: medium
- Confidence: CONFIRMED
- Where: `companion/src/ccsync_companion/broll_ingest.py:697-731` (`BrollIngestor._save`), mutators at `:1961-2035` (`_crunch_item`), `:1305-1398` (`prepare`), `music_ingest.py:242-345`
- What: `_save()` takes the lock only to build `snapshot`, and puts **live references** to `self._batch` and `self._staging` into it (`"batch": self._batch, "staging": self._staging` — only `picked_roots` is copied). The lock is then released and `json.dumps(snapshot, indent=2)` runs inside `_save_lock` only. Because `indent` is not None, CPython does **not** use the C encoder: `json.dumps` runs the pure-Python `_make_iterencode`, which executes bytecode and therefore yields the GIL mid-iteration. Any other thread that adds a key to those dicts during the dump raises `RuntimeError: dictionary changed size during iteration`, which the broad `except Exception` swallows into one `could not write <state_path>` warning.
- Failure scenario: the tick thread is in `_crunch_item` doing `item.setdefault("outputs", {})` / `outputs["proxy"] = …` / `item["described"] = True` / (music) `item["analysis"] = …` — every one of those adds a key that `_item_from_manifest` did not pre-create. Concurrently the heartbeat thread calls `pause_upload()`/`cancel()` (`:1152`, `:1164`) → `_save()`, or a loopback request thread calls `prepare()` (which inserts a new key into `self._staging` under the lock and then saves) or `note_upload()`/`control()` → `_save()`. The dump aborts, `os.replace` never runs, and the state file keeps an older snapshot. The docstring's contract ("Called at EVERY transition", "a companion killed mid-batch must come back to the same batch at the same checkpoint") is broken exactly when the machine is busiest — the resumed batch re-does stages, or `_resume` fails items whose staging entries the stale file does not know about.
- Evidence: proved the encoder behaviour from the companion venv. With `json.dumps(d)` (C encoder, GIL held for the whole structure) a concurrent mutator produced **"no error seen"**; changing the single call to `json.dumps(d, indent=2)` produced `["RuntimeError('dictionary changed size during iteration')"]` on the first pass. Script: scratchpad `proof.py`. The three-threads-reach-this hazard is acknowledged in `_save`'s own comment, but the mitigation added (`_save_lock` + per-thread temp name) only serialises the *writers*, not the *readers of the live dicts*.
- Ledger: new (not in KNOWN_BUGS; `grep -n "_save\|dictionary changed"` finds nothing on this).
- Suggested fix: build the snapshot as a deep copy inside `self._lock` (`copy.deepcopy` of `_batch`/`_staging`, or `json.dumps` *inside* the lock), so nothing mutable is serialised outside it.

### comp-broll-music-2 — the browser origin allow-list is frozen at startup, and is built from the manifest cache the same startup is still refreshing
- Severity: medium
- Confidence: CONFIRMED (mechanism); the user-visible outcome needs a re-provisioned site
- Where: `companion/src/ccsync_companion/broll_server.py:2036-2052` (`BrollCompanionServer.__init__`), against `companion/src/ccsync_companion/app.py:7486-7493` and `app.py:7543-7557`
- What: `allowed_origins` is computed **once**, in the server constructor, from `ccsync_cfg["dashboard_url"]` plus `site_mod.cached_site()["dashboard_url"]`. `app.start()` kicks `site_mod.refresh_site()` off on a *background* thread at line 7490 and then runs `_start_broll_server` as a later synchronous step (line 7552). The constructor therefore reads whatever `~/.ccsync/state/site.json` held **before** the refresh, and nothing ever rebuilds the frozenset for the life of the process — there is no reload path (`grep -n "broll_server" app.py` shows only `start` at 7651 and `stop` at 8638).
- Failure scenario: an admin re-provisions the site so the manifest's `dashboard_url` changes (Tailscale Serve moves the dashboard to a new https host, a customer renames the NAS). The editor's `config.toml` still has the old value. On the next tray start the manifest refresh lands a second or two after the 8899 server was built, so the allow-list holds only the OLD origin for the whole session: **every** Send-to-Resolve, /music/send, /music/reveal, /ytdl/* and ingest POST/PUT from the page 403s with `loopback_guard.REFUSED_MESSAGE`, and the log names the stale list as if it were the configured one. It clears only on the *next* restart. Same shape if an operator fixes `dashboard_url` in config.toml and relies on any config re-read.
- Evidence: read both sides. `refresh_site` (`site.py:301-315`) fetches over the network and only then `save_site`; `_start_broll_server` is a plain synchronous starter in the same `start()` list, so it wins the race on every machine with a working tailnet. `BrollCompanionServer.__init__`'s own comment ("Computed ONCE, here, rather than per request") documents the caching but not the ordering dependency.
- Ledger: new. Related to CR-7 (the module this introduced) but not the same defect.
- Suggested fix: either await/serialise the manifest refresh before `_start_broll_server`, or make `allowed_origins` a callable/property the handler re-reads from a cheap cached snapshot (`site.cached_site()` is a file read, so a 30 s TTL is enough) so a manifest refresh takes effect without a restart.

### comp-broll-music-3 — any web page can make the companion spawn unbounded Resolve worker processes via GET /music/status
- Severity: medium
- Confidence: CONFIRMED (reachability and the spawn); PLAUSIBLE on the exact severity of the wedge
- Where: `companion/src/ccsync_companion/broll_server.py:1391-1397` (`do_GET`), `:1814-1820` (`/status`, `/music/status` dispatch), `music_server.py:216-224` + `:155-190` (`call`, default `TIMEOUT = 90`)
- What: GETs are deliberately exempt from `_post_authorised`, and `_vet_request` only refuses when an `Origin` header is *present* and not allow-listed. Subresource loads (`<img src>`, `<iframe>`, `<script src>`, `<link>`, a plain form GET) send **no** Origin, so they sail through — the docstring justifies the exemption with "a top-level navigation sends no Origin", which does not cover them. `GET /status` then calls `music_server.call(BROLL_STATUS_ACTION, timeout=20)` and `GET /music/status` calls `call("status")` with the module default `TIMEOUT = 90`: each is a fresh `subprocess.run` of the frozen companion re-entered as a Resolve worker. There is no cache, no in-flight de-duplication, no concurrency cap, and `ThreadingHTTPServer(daemon_threads=True)` gives one thread per request.
- Failure scenario: an editor opens any page (ad iframe, forum, phishing link) that runs `for (let i=0;i<300;i++) new Image().src='http://127.0.0.1:8899/music/status?'+i`. The attacker cannot read a single response (no `Access-Control-Allow-Origin` is emitted), but 300 copies of the ~80 MB frozen companion are spawned, each living up to 90 s and each attempting a Resolve scripting connection. The machine that is supposed to be moving everyone's footage stalls, and CR-68's fuscript window gets 300 extra clients knocking.
- Evidence: read the dispatch chain end to end. `do_GET` = `self._guarded(lambda: self._vet_request() and self._dispatch_get())`; `_vet_request` returns True for a missing Origin (`if origin:` guard at `:1197`). `music_server.call` has no cache and no lock; `build_status_response` in `music_server.py` calls it with the default 90 s timeout. Nothing between the socket and `subprocess.run` counts requests.
- Ledger: new; the class of thing CR-7 / trust-model-9 addressed for POSTs, left open for GETs.
- Suggested fix: memoise the two status probes for a few seconds and/or serialise them behind a single in-flight slot (the answer is a yes/no a settings dot draws), so N requests cost at most one child. A cheap second belt: require `Sec-Fetch-Dest: document|empty` or refuse `Sec-Fetch-Mode: no-cors` on the two spawning routes.

### comp-broll-music-4 — a refused POST leaves its body unread, so the client can lose the 4xx that explains it
- Severity: low
- Confidence: PLAUSIBLE
- Where: `companion/src/ccsync_companion/broll_server.py:1400-1406` (`do_POST`) vs `:1417-1445` (`do_PUT`)
- What: `do_PUT` wraps its dispatch in `try/finally: self._drain_small_body()` precisely because "a refusal that leaves an unread body in the socket's receive buffer makes the CLOSE a reset, and the client then loses the 403/409/507". `do_POST` has no such drain: a 403 from `_post_authorised`, a 415 from `_content_type_ok`, or a 500 from `_guarded` all answer and close with the body still in flight.
- Failure scenario: a page POSTs a ~200 KB `/broll/ingest/prepare` (2,000 items is allowed) from an origin that has just gone stale (see finding 2). On Windows the browser sees `ERR_CONNECTION_RESET` instead of the 403 body, so the SPA reports "the companion is not running" rather than the refusal that names the fix — the exact misdiagnosis the PUT path was written to avoid.
- Evidence: read both methods; the drain helper `_drain_small_body` is bounded and already generic, and is called only from `do_PUT` and `_ingest_content_type_ok`.
- Ledger: new.
- Suggested fix: give `do_POST` the same `try/finally: self._drain_small_body()` wrapper `do_PUT` has.

## Coverage note
Not reached: `music_clap_sidecar.py` beyond the spawn/timeout helpers (the ONNX runtime fetch and mel pipeline), `broll_vlm/local_runtime.py` and `local_vlm.py` in depth (vendored byte-for-byte from the indexer, with a release gate against drift), `broll_ingest._pump_uploads`/`_maybe_finish`/`_reclaim` in detail, and `broll_upload.UploadQueue`'s worker loop past `stop_all`.

Checks I ran that came back clean, so nobody repeats them:
- **em dashes**: the only U+2014 in a non-docstring, non-log string literal in the territory is `broll_vlm/compact_format.py`'s `_NONE_WORDS`, which `tests/test_no_em_dash.py::ALLOWED` exempts by exact value and which is model *input*, not copy. `broll_vlm_sidecar.py:213`'s em dash is inside `fits()`'s docstring; the string the editor actually gets (`:248`) uses ` - `. Clean.
- **rel_path traversal**: `contained_local_path` now covers `/insert` as well as the music/ytdl routes, refuses absolute/drive-letter/UNC-ish forms, re-checks containment with `resolve(strict=False).relative_to`, and `translate_path_with_root` refuses a blank root (comp-loopback-5 really is fixed).
- **share**: `loopback_guard.valid_share` is applied on every platform before the value is used as a mounts key or interpolated into `/Volumes/<share>`; `probe_darwin_mount` re-checks containment (C1 fixed).
- **PUT upload path**: `_UPLOAD_PATH_RE` never supplies the filesystem path — the path comes from the staging entry and is re-checked with `is_within(dest.parent, staging_root)`.
- **wire contracts**: `ingest_kinds.MUSIC_EXTS` / `MUSIC_TRANSCODE_EXTS` / `max_prepare_items=500` / `MUSIC_MAX_FILE_BYTES` all match `musicweb.config` and `musicweb.ingest_batches`; `broll_server.INGEST_VIDEO_EXTS` matches `schemas.MAX_BATCH_ITEMS=2000`; `FleetClient`'s six suffixes match `broll/web/app/routes_fleet.py` exactly.
- **ffmpeg subprocesses**: `broll_ingest_media.run_ffmpeg` drains both pipes via `communicate`, kills then re-drains on timeout, and publishes the child to the orchestrator's sink (MEDIA-2 fixed); `ffmpeg_tools` uses `capture_output` + timeouts throughout; every argv is a list, never a shell string.
- **MUSIC-ING-5 / MUSIC-ING-6**: `_dispatch_get` now tests the whole `INGEST_PREFIXES` set, and `_ingest_floor_bytes` takes the kind. Both genuinely fixed.
- **sidecar downloads**: pinned URL + sha256 over the downloaded bytes, verified before unpacking, `zf.open(member)` never `extractall`, `os.replace` as the only visible moment. Clean.

## OUT OF TERRITORY
- `companion/src/ccsync_companion/app.py:7486-7493` / `:7552`: the site-manifest refresh is a background thread started before the synchronous `_start_broll_server` step that reads its cache — the app-side half of finding 2.
