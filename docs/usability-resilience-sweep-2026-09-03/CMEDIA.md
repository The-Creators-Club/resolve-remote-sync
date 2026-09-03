# Companion media side (CMEDIA): 8899 loopback, b-roll/music ingest, local VLM, fleet jobs

## Summary
The ingest half of this area is the best-surfaced background work in the
companion: a gate with editor-worded states, a tray tooltip that counts, a
Settings panel with pause/resume/index-now/cancel/progress buttons, a progress
window with an EMA ETA, and (new since 08-28) staging retention with its own
line and button. The fleet JOB runner, shipped a fortnight later and doing the
same kind of thing on the same machines, has none of it: no tray line, no
Settings section, no history, no stop for the person sitting at the keyboard,
and no local precedence against the two GPU consumers that already negotiate
with each other. That is the biggest usability gap and, because a whisper job
and a b-roll batch open their gates on the same event ("nobody is here"), also
the biggest resilience risk. The worst silent failure is smaller and older: if
port 8899 cannot be bound the companion starts anyway, says nothing anywhere,
and every web page then tells the editor "tray app not running" - which is
false. The cheapest high-value win is publishing the loopback's own health
(bound? which origins? which port?) in `GET /status` and in the report, so both
the page and the admin can name the cause instead of guessing.

## Findings

### CMEDIA-1: three GPU consumers on one machine, and only two of them negotiate
- **Lens:** both
- **Who:** editor, admin
- **Where:** `companion/src/ccsync_companion/jobs_runner.py:404-441` (`_gate`),
  `app.py:1779-1791` (JobRunner built with no `blocked_fn`),
  `app.py:7934-7953` (`_proxy_block_reason`), `broll_ingest.py:22-26`
- **Today:** the documented rule is "indexing beats proxy generation": the
  ingest orchestrator answers `blocking_reason()` and `ProxyGenerator` stands
  down with "waiting: indexing b-roll first". The job runner is outside that
  agreement entirely. Its gate asks: enabled, dashboard, halted, already
  holding a job, capability, user away, Resolve open - and never asks whether
  this machine is currently running a Qwen3-VL batch or a proxy encode. Both
  gates open on the same event (`_user_is_away()` / `idle_seconds`), so the
  common case is that they open together: a whisper job (GPU) claimed onto a
  machine already holding 8-12 GB of VLM weights. The failure is an OOM or a
  crawl, reported as a job failure, which then earns that machine the
  dashboard's per-machine cooldown for a fault it did not have.
- **Proposed:** give `JobRunner` the same `blocked_fn` seam the other two have,
  wired to a new `app._jobs_block_reason()` that returns the ingestor's
  `blocking_reason()` (either kind) or `"waiting: making proxies"`; report it
  as a new gate state `STATE_LOCAL_WORK` and send it up in the capabilities
  section so `GET /api/v1/jobs/<id>/why` can say "busy indexing b-roll" instead
  of ranking a saturated machine first on longest-idle. Conversely have
  `broll_ingest._gate` treat a held job as a reason to wait, so an editor's own
  drop is not queued behind the fleet's transcription.
- **Effort:** M   **Value:** high   **Confidence:** high
- **Related:** `docs/TIMELINE-CARDS-INTO-CCSYNC.md` phase 4 rank signals
  (nvenc / GPU headroom) are computed from a capabilities section that cannot
  see local work.

### CMEDIA-2: an editor cannot see, stop, or review the fleet work their machine does
- **Lens:** usability
- **Who:** editor
- **Where:** `jobs_runner.py:78-81` ("Gate states ... The tray does not render
  these yet"), `jobs_runner.py:648-655` (the only notify), `tray.py:3405-3443`
  (menu), `settings_window.py:472-511` (ingest has a full panel; jobs have
  none), `app.py:7034-7053` (gate is diagnostics-bundle only)
- **Today:** the tray offers exactly one job control, "⚡ Take fleet jobs now
  (30 min)". While a job runs there is no line, no tooltip suffix, no window,
  and no way to stop it - the volunteer toggle only closes the gate for the
  NEXT claim, and the module docstring is explicit that a running job is not
  killed when the editor comes back. The only feedback is one balloon after a
  successful whisper pass ("Finished a transcription job for the fleet
  (412s).") which names no file and no folder; a media recipe notifies nothing
  at all, and a FAILURE notifies nothing ever. Compare the same person's
  proxies: "PROXIES THIS MACHINE HAS MADE…" (`proxy_history.py`), a stop
  button, and a progress window.
- **Proposed:** a `FLEET JOBS` section in Settings, built from
  `job_runner.status()`, with (a) a live line `Running a fleet job for the
  team: transcribing 3 of 12 (started 4 min ago)`, or, when idle, the gate in
  words - `Not taking fleet work: you are at the keyboard` /
  `... nothing queued` / `... this computer has no whisper set-up`; (b) a
  `[ STOP THIS JOB ]` button calling the same `should_stop()` path an admin's
  cancel uses, posting the result as `cancelled`, not retryable; (c)
  `[ JOBS THIS MACHINE HAS RUN… ]` over a new `~/.ccsync/state/jobs_history.json`
  (id, kind, started, seconds, ok, error, files) written at every
  `_post_result` - the answer to "is there a way for an editor to see what
  their machine ran or refused and why", which today is no. Add the tooltip
  suffix `· fleet job 3/12` beside the ingest one (`tray.py:2840`).
- **Effort:** M   **Value:** high   **Confidence:** high

### CMEDIA-3: the loopback can fail to start, and the page then blames the tray
- **Lens:** both
- **Who:** editor, admin
- **Where:** `broll_server.py:2069-2085` (bind failure -> `return None`),
  `app.py:7641-7664` (`self._broll_server = None`, nothing else),
  `broll/web/static/app.js:1650-1653`, `music/web/static/app.js:298-301`
- **Today:** if 8899 is held (the retired standalone companion, a leftover
  process after a crash, any other tool), the companion logs one WARNING and
  runs happily forever with no listener. Nothing else records it: no tray line,
  no `broll_server` field in the report, no notice, no alert kind, and no
  retry - the port is never tried again for the life of the process, so
  quitting the offender does not fix it. What the editor sees is
  `couldn't reach the ccsync companion: tray app not running, or the browser
  blocked local connections` - a message that is wrong in its first clause and
  sends them to restart something that is already running.
- **Proposed:** (1) retry the bind on the tick (every 60 s) until it succeeds,
  logging once per transition; (2) publish `loopback: {bound, port, error}` in
  the report so the dashboard can raise a `loopback_down` notice with the exact
  next action ("quit the old BRoll Companion on <machine>, or restart CC
  Sync"); (3) a Settings line under HELP: `Send to Resolve is not available on
  this computer: another program is using port 8899. Quit it, then restart CC
  Sync.` A state this invisible is what SELF_DIAGNOSIS wave 4 exists to end.
- **Effort:** S   **Value:** high   **Confidence:** high
- **Related:** `alerts.ALERT_KINDS:1425-1512` has forty kinds and none for the
  loopback.

### CMEDIA-4: `queued_for_base_rig` is invisible in every counter and then deleted
- **Lens:** both
- **Who:** editor
- **Where:** `music_ingest.py:349-372`, `broll_ingest.py:982-984` (`done` counts
  `ITEM_LIVE` only), `:1125` (`finished = done + failed >= total`),
  `:1013` (`eta_seconds` over `total - done - failed`),
  `:2851-2893` (`prune_staging`), `settings_window.py:304-318, 437-446`
- **Today:** a music item whose CLAP model goes away mid-batch ends
  `queued_for_base_rig` - "the audio is in the library, the ledger says who has
  to finish it" - except that it is NOT uploaded (the docstring says so
  explicitly) and the file stays in staging. That state is in the kind's
  finished set but in neither counter: the tray says "Indexing music… 8 of 10",
  the progress window's `finished` never becomes true, the ETA divides by a
  remainder that never reaches zero, and the dashboard chip shows 8/10 forever.
  Then MEDIA-3's new retention deletes the staging directory seven days after
  the batch ended, with no exemption for the file whose whole contract is "it
  is still on this machine" - and `[ CLEAR FINISHED STAGING ]` does it
  immediately, with no confirmation and no count of what is about to go.
- **Proposed:** add `queued` to `status()`/`report()` and to the progress
  window's overall line (`8 of 10 tracks · 2 waiting for the base rig`); give
  the tray/Settings a line `2 track(s) need the base rig to finish. They are
  still on this computer.`; make `prune_staging` skip a staging dir that holds
  any `queued_for_base_rig` item (or refuse and say so), and give
  `action_clear_ingest_staging` a confirm naming the GB and any held tracks.
- **Effort:** M   **Value:** high   **Confidence:** high

### CMEDIA-5: the one refusal an editor ever reads points at a menu item that does not exist
- **Lens:** usability
- **Who:** editor
- **Where:** `loopback_guard.py:111-112`, `tray.py:3426-3443` (the ten-item
  menu: no log entry), `settings_window.py:593` (`Button("OPEN LOG", ...)`)
- **Today:** every 403/415 answer carries `"this request was refused by the CC
  Sync companion -- see its log (Tray > Open log) for the reason"`. There is no
  "Open log" in the tray menu - it is Settings… → HELP → `[ OPEN LOG ]`. So the
  single sentence the product gives an editor for the commonest deployment
  failure (a `dashboard_url` that does not match the URL they browse) names a
  control that is not there, and the log line that does hold the diagnosis is
  one an editor will never open anyway.
- **Proposed:** copy: `"CC Sync refused this request. Open the tray menu →
  Settings → Open log, or send Copy diagnostics to your admin."` And close the
  loop at the other end: a `loopback_origin_mismatch` alert kind fed by the
  allow-list published in the report (see CMEDIA-6), because today one wrong
  URL 403s every Send-to-Resolve in the fleet and no admin surface says so.
- **Effort:** S   **Value:** high   **Confidence:** high
- **Related:** 08-28 MEDIA-6 (still open, see below) - this is the copy and
  admin-visibility half of it, not the recompute.

### CMEDIA-6: `broll_server_port` is a setting that silently breaks every button
- **Lens:** resilience
- **Who:** editor, admin
- **Where:** `broll_server.py:2019-2040` (`configured_port`, validated and
  honoured), vs the hardcoded `http://127.0.0.1:8899` in
  `broll/web/static/app.js:7`, `broll/web/static/ingest.js`,
  `music/web/static/app.js:246`, `music/web/static/ingest.js`
- **Today:** the key exists, is documented as deliberately excluded from
  `validate_config` ("a typo in it must not join config_problems"), and moving
  it is a total, silent break: every page keeps calling 8899, gets a connection
  refusal, and reports "tray app not running". Nothing publishes the real port
  anywhere a page could read it.
- **Proposed:** either delete the key, or make it honest - refuse a non-default
  port with a `config_warnings` entry ("Send to Resolve only works on port
  8899; the b-roll and music pages cannot be told about another one") and keep
  listening on 8899 as well.
- **Effort:** S   **Value:** med   **Confidence:** high

### CMEDIA-7: "this machine is already downloading" is delivered as a hard failure
- **Lens:** both
- **Who:** editor
- **Where:** `broll_fetch.py:58-60` (`BUSY_MESSAGE`), `:366-374` ("the web UI
  re-POSTs every 1.5 s anyway, so 'busy' IS the retry mechanism"),
  `broll_server.py:753-760` / `music_server.py:423-429` (`state != done` ->
  `ok:false`), `broll/web/static/app.js:1566-1578`
- **Today:** the retry mechanism the cap relies on does not exist. The page
  loops only while `state === "downloading"`; any `ok:false` is toasted and the
  loop returns. So an editor who clicks "+ Resolve" on a music cue while two
  camera originals are in flight gets a red toast - `couldn't sync the track
  from the NAS: this machine is already downloading as much as it will at once
  - try again when the clip in progress has finished` - and must remember to
  come back in an hour and click again. There is still no way to cancel either
  of the two downloads that are hogging the cap (`FetchJob.cancel()` exists and
  is only called by `stop_all()` at shutdown).
- **Proposed:** answer `{"state": "queued", "message": "waiting for this
  computer's other download to finish"}` and let the page's existing poll loop
  keep polling on it exactly as it does for `downloading`; size-aware slot
  reservation and a cancel affordance as 08-28 MEDIA-25 proposed.
- **Effort:** S   **Value:** med-high   **Confidence:** high

### CMEDIA-8: a killed fleet media job leaves `.partial` files nothing ever sweeps
- **Lens:** resilience
- **Who:** admin, editor
- **Where:** `jobs_media.py:877-905` (`_with_partial`), `app.py:8360-8410`
  (`_sweep_stale_tmp_files` walks `local_root` ONLY),
  `proxy_gen.sweep_stale_partials:425`
- **Today:** the companion has a careful stale-`.partial` sweep, and it is
  scoped to the sync tree. Media jobs write into the `vault` and `media` roots
  (`jobs_vault_root` / `jobs_media_root`), which the sweep never sees. A power
  cut, a `Stop-Process`, or a supervisor relaunch mid-encode leaves
  `<name>.mp4.partial` inside somebody's `Script Docs/remote_audio/source`
  forever; the in-process `_partials` claim registry is memory-only, so nothing
  even remembers it existed. Timeline Cards' page reads that directory.
- **Proposed:** extend the existing sweep over `job_paths.roots(cfg)` (report
  only, never delete - the same posture as the tree sweep), and add the count
  to the same Settings line the tree's leftovers use.
- **Effort:** S   **Value:** med   **Confidence:** high

### CMEDIA-9: the 20 GB staging floor is b-roll's number applied to music
- **Lens:** usability
- **Who:** editor
- **Where:** `broll_server.py:864-877` (`_ingest_floor_bytes`, default `20`
  regardless of kind), `:1063-1069` (the music refusal),
  `:1090` (`MUSIC_MAX_FILE_BYTES` = 512 MiB)
- **Today:** a music drop is refused on a laptop with 15 GB free with
  `only 15.0 GB free where the tracks would be staged (the floor is 20 GB)`,
  and the drop zone never renders. The largest thing a music batch can stage is
  512 MB per file; the floor was sized for 40 GB camera originals. The key is
  per-kind (`music_ingest_free_space_floor_gb`) but its DEFAULT is not, so
  every fleet gets b-roll's number for music until somebody sets it.
- **Proposed:** `IngestKind.free_space_floor_gb` (b-roll 20, music 2) as the
  default `coerce_numeric` falls back to; the config key keeps overriding.
- **Effort:** S   **Value:** med   **Confidence:** high

### CMEDIA-10: a failed clip's reason exists in three places, none of them the tray
- **Lens:** usability
- **Who:** editor
- **Where:** `tray.py:2806-2807` (`"{n} b-roll clip(s) could not be indexed.
  See the log"`), `popup.py:1683-1690` (`ProgressModel` carries `failed` as a
  count only), `broll_ingest.py` per item `item["error"]` (rich, and only in
  `progress()` and the log)
- **Today:** the orchestrator knows exactly why each clip failed ("the source
  file is not on this machine any more", "the archive never saw these files:
  …", a tier refusal) and puts it on the item. The editor's two local surfaces
  reduce all of it to a count plus "See the log". The reason is readable only
  in the browser page they may well have closed hours ago.
- **Proposed:** carry `failures: [{name, error}]` (first 5) into
  `progress_model()` and draw them under the bars, the way `popup.py:1204`
  already lists FIX ALL failures; make the tray line
  `3 b-roll clip(s) could not be indexed. Settings → Show b-roll indexing
  progress`.
- **Effort:** S   **Value:** med   **Confidence:** high

### CMEDIA-11: `[ CLEAR FINISHED STAGING ]` is a destructive button that looks like the others
- **Lens:** usability
- **Who:** editor
- **Where:** `settings_window.py:437-446, 304-318`
- **Today:** one click deletes every finished batch's staging tree with no
  confirmation, no size preview and no undo, rendered identically to
  `[ OPEN LOG ]`. Every other destructive action in this window ends in `…` and
  confirms (`CANCEL THE B-ROLL BATCH…`, `STOP ALL SYNCING ON THIS MACHINE…`,
  `REMOVE '<project>' FROM THIS MACHINE…`).
- **Proposed:** rename to `CLEAR FINISHED STAGING…`, confirm with the number
  and size ("Delete 4 finished batches (11.3 GB)? The clips are already in the
  archive."), and refuse/flag when CMEDIA-4's held tracks are inside.
- **Effort:** S   **Value:** med   **Confidence:** high

### CMEDIA-12: the machine's own answer to "why am I taking no work" never leaves the machine
- **Lens:** both
- **Who:** admin
- **Where:** `jobs_runner.py:293-303` (`status()`), `app.py:7034-7053`
  (diagnostics bundle only), `capabilities.py:277-310` (the reported section
  has `jobs_enabled`, `idle_seconds`, `job_kinds` - not the gate)
- **Today:** `GET /api/v1/jobs/<id>/why` reconstructs a machine's eligibility
  from the capabilities section. The runner's actual verdict - `user_active`,
  `resolve_open`, `no_capability`, `nothing_offered`, `running`, `forced` - is
  written only into a diagnostics bundle an editor has to be asked to copy. The
  two can disagree (a stale offer, a volunteer window that expired between the
  report and the claim) and nothing would show it.
- **Proposed:** add `jobs_gate` and `jobs_holding` to the capabilities section
  and render them in the `why` answer beside the dashboard's own reasoning:
  "this machine says: user_active". Two fields, and it turns a model into an
  observation.
- **Effort:** S   **Value:** med   **Confidence:** high

### CMEDIA-13: a "forced" job is invisible to the person it is being forced onto
- **Lens:** usability
- **Who:** editor
- **Where:** `jobs_runner.py:88-93` (`STATE_FORCED` - "Reported by status()
  while it runs so the tray and the diagnostics can say why work started with
  somebody at the keyboard"), `:424-437`, and no tray/Settings reader
- **Today:** an admin's `--now` claim starts a GPU job with the editor sitting
  at the machine. The state exists precisely so the tray can explain it; the
  tray does not read it. The editor experiences an unexplained slowdown.
- **Proposed:** with CMEDIA-2's line: `Your admin asked this computer to run a
  fleet job now (transcribing, 4 min so far).` plus the stop button.
- **Effort:** S   **Value:** med   **Confidence:** high

### CMEDIA-14: `roots()` calls `exists()` on every configured root, on the claim path
- **Lens:** resilience
- **Who:** editor
- **Where:** `job_paths.py:59-75` (`roots`), called by `mounts()` in the
  capabilities section (every 30 s report) and by `resolve()` per job
- **Today:** `jobs_media_root` is documented as "the footage share, where it is
  mounted separately from the tree", i.e. plausibly an SMB path. A
  `Path.exists()` against a dead SMB mount blocks for the SMB timeout (up to
  ~20 s on Windows, longer on a VPN that has dropped), inside
  `capabilities.build`, which is called on the report thread and on the job
  runner's tick. `capabilities` has a 60 s cache, so the worst case is one
  stalled report cycle per minute - but the runner's `runnable_kinds()` call
  goes through the same probe on every gate evaluation.
- **Proposed:** cache the root-existence probe for ~60 s beside the
  capabilities cache, and never probe it inside `_gate()`; a root that has
  answered within the last minute is a root.
- **Effort:** S   **Value:** med   **Confidence:** med

### CMEDIA-15: the media recipes' failures are all retryable by default, including the ones that are not
- **Lens:** resilience
- **Who:** admin
- **Where:** `jobs_media.py:115-124` (`retryable=True` default),
  `:886-889` ("another writer on this machine already has X"),
  `:895-903` (any unexpected exception -> `MediaJobError(str(exc))`, retryable),
  `jobs_runner.py:733-741`
- **Today:** a disk-full `os.replace`, a permission denial on the vault and an
  unexpected `Exception` all come back as retryable, so the dashboard re-queues
  them; the per-machine cooldown slows that, but the machine with the full disk
  is still first in line for every one of its own retries once the cooldown
  lapses, and rule 5 eventually pins the job onto the dashboard's own ffmpeg -
  which has none of the information about which machine was broken.
- **Proposed:** classify: `ENOSPC` / `EACCES` on the OUTPUT root is
  `retryable=True` (another machine may have room) but should carry a distinct
  `error` prefix the scheduler can count, and repeated space failures from one
  machine should raise the existing `disk_low` alert rather than only
  cooling that machine down. The "another writer" case is not a failure at all
  and should report success-with-`skipped`.
- **Effort:** M   **Value:** med   **Confidence:** med

## Still open from 08-28
Verified in the source at `097f5a3`; only MEDIA-2 and MEDIA-3 were built in the
companion (`grep MEDIA- companion/src`).

- MEDIA-6, loopback origin allow-list frozen at tray start: **not built** -
  still computed once in `BrollCompanionServer.__init__`
  (`broll_server.py:1978-1996`), nothing recomputes it, `/status` publishes
  neither the list nor `dashboard_url`.
- MEDIA-9, orphaned llama-server holds VRAM after a hard kill: **not built** -
  `broll_vlm/local_vlm.py:187-221` is still `atexit` only, no pid file, no
  Job Object, no boot scan.
- MEDIA-10, a batch that finishes during a dashboard blip is re-claimed:
  **not built** - `release()` still swallows the error (`broll_ingest.py:399-410`)
  and `_maybe_finish` clears `_batch` unconditionally (`:2557-2575`).
- MEDIA-11, `mark_uploaded` answering anything but 200/409 loops for ever:
  **not built** - the `else` at `broll_ingest.py:2479-2481` is still one log
  line with no attempt counter, beside two capped neighbours.
- MEDIA-12, an unplugged card fails every remaining clip: **not built** -
  no `source-absent` gate state; `_picked_roots` is still not consulted before
  failing an item.
- MEDIA-17, base-rig staging lands inside the live library: **not built** -
  `broll_ingest_staging_dir` defaults to `""` (`config.py:513`), nothing checks
  whether the resolved staging root is on a network path, and the requirement
  lives only in `companion/README.md:118`.
- MEDIA-25, one fetch cap for three callers, no cancel: **not built** (see CMEDIA-7); the picked-root
  allow-list (MEDIA-31) still never expires either.
- MEDIA-26, CLAP inference runs in the tray process: **not built** -
  `music_clap_sidecar.session()/embed_windows()` still call onnxruntime inline
  (`:546-588`, `:857-880`).
- MEDIA-27, the companion fabricates a 7200.0 s duration for a long file:
  **not built** - `embed_file` still returns `samples.size / sample_rate` after
  a `MAX_DECODE_SECONDS` truncation (`:761`, `:933`).
- MEDIA-28, `UploadQueue._loop` can wedge on an unexpected exception:
  **not built** - `broll_upload.py:424-466` still has no outer try/except and
  `_active` is cleared only in `_finish`.
- MEDIA-29, the music library's location is hardcoded on fetch/send:
  **not built** - `music_server.py:56` and `broll_fetch.py:69` still literal
  `Assets/Music`.
- MEDIA-30, a heartbeat outage lets a machine keep crunching a lost batch:
  **not built** - `_heartbeat_loop` still debug-logs a failure and continues,
  with no consecutive-failure count.

## Cross-cutting notes
- **Dashboard/jobs agent:** CMEDIA-1 and CMEDIA-12 both land on the
  capabilities section and on `GET /api/v1/jobs/<id>/why`; a rank that sorts on
  "longest idle" without knowing about local ingest/proxy work will keep
  choosing the busiest GPU in the fleet.
- **Self-diagnosis agent:** `alerts.ALERT_KINDS` has no kind for the loopback
  being down or origin-refused, which is the failure that takes Send-to-Resolve
  away from every editor at once (CMEDIA-3, CMEDIA-5).
- **Tray/settings agent:** the `Tray > Open log` string in
  `loopback_guard.py:112` is one of several places that name a menu item CR-88
  removed; worth a grep for others (`app.py:2817`, `popup.py:1204` both say
  "Tray → Open log" too).
- **Web/SPA agent:** `broll/web/static/app.js:1524` loops `for(;;)` on /insert
  with no cap and no cancel while a 40 GB original downloads; the companion has
  a `FetchJob.cancel()` that no UI reaches.
