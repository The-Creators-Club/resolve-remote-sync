# Known bugs

**Status 2026-08-15: everything below that says "in repo, unshipped" IS NOW
SHIPPED** — the 08-14 hunt pass, R14 and R15 all went out in one commit
(`5ab221d`) as **companion 0.7.8 / installer 1.0.27**, together with phases
1+2 of requester-first ytdl downloads. Base rig verified after the ship:
`check_deploy_drift.ps1` clean, running build sha-identical to
`companion/dist` and stamped with that commit, `ytdlp_manager` installed
yt-dlp 2026.07.04 on first run. Note the version skew: `docs/
YTDL_LOCAL_DOWNLOAD.md` was written against a **0.8.0** target and the
feature actually shipped under **0.7.8**. Still owed, as ever: the **Mac
builds** (not cross-buildable from Windows) and every editor accepting the
tray upgrade. The `setup_syncthing_folder.py` re-run this paragraph used to
ask for is NOT owed — see R15.

**Status 2026-08-11 (evening): the morning's 82-finding hunt is FIXED — same
day, all of it, plus the 45-finding ytdl ledger and the delete-protection
patch.** The full hunt text with per-entry resolutions and the deliberate
divergences is archived at `docs/bug-hunt-2026-08-11.md`; the ytdl ledger
(`docs/youtube_dlp_bugs.md`) carries its own resolution header. The fix pass
was eleven Opus agents over disjoint file territories, orchestrator-verified,
~125 files, +6.7k lines (about half of it tests). All ten suites green
(`tools\run_all_tests.ps1` — which now genuinely runs all of them, OPS-6).

That pass SHIPPED the same day as companion 0.7.0 / installer 1.0.22 /
dashboard 0.4.0 (drift doctor clean, base rig upgraded, sprites and the
migrated b-roll DB pushed to the NAS). Only the Mac builds were left behind,
and they still are.

This file is the ledger of what is STILL open.

**2026-08-14: a third full-repo hunt ran (12 Opus hunters + 12 adversarial
verifiers, every tracked source file, briefed on this ledger and both 08-11
archives). It confirmed 94 NEW findings — 10 critical / 46 major / 38 minor —
plus 7 uncertain. FIXED the same evening by an 11-agent Opus fix pass
(disjoint file territories, orchestrator-reconciled; resolution header in
`docs/bug-hunt-2026-08-14.md` — the per-finding OUTCOMES are not in that
file, each fix cites its finding id and date at the code site instead, so
`grep -rn COMP-GUARD-1` is how you find what was done about one). All 10 criticals
fixed; all 10 suites green (`tools\run_all_tests.ps1`: 0 of 10 failed,
~+250 tests); eight findings deliberately NOT fixed — see R16. Two pieces
of the pass already happened outside the repo: the base rig's
`broll-indexer-watchdog` scheduled task was re-registered against the
in-repo `watchdog.ps1` (still Disabled, ops half of BROLL-IDX-2), and the
music UI's reveal now requires a companion carrying `POST /music/reveal` —
one more entry in the "editors need a republished companion" column.
SHIPPED 2026-08-15 as companion 0.7.8 / installer 1.0.27 (commit `5ab221d`)
— NOT the 0.8.0 the ytdl plan names as its target.**

---

**Status 2026-08-17 (evening): the commercial-readiness pass
(`docs/COMMERCIAL_READINESS.md`, all 15 items) was IMPLEMENTED IN REPO by a
15-agent Opus fleet on branch `commercial-readiness` (disjoint file
territories, integration agent + full-suite verification afterwards; ~220
files, ~+18k lines, roughly half tests). NOTHING FROM IT IS SHIPPED. Every
entry below tagged CR-n is "fixed in repo, unshipped" unless it says
otherwise, and several need an operator step on a live NAS, a certificate,
counsel, or a Mac before the fix is real. The consolidated operator list is
the "Status 2026-08-17" paragraphs in `docs/COMMERCIAL_READINESS.md`.**

---

## Open - the sync engine's lifetime (SYNC-17, 2026-08-18)

### SYNC-17 - Syncthing died with the Windows session and stayed dead for 18 hours, with lane C green - FIXED in repo 2026-08-18, unshipped
Editor `ruskin` (DESKTOP-LQQ41TC, companion 0.9.0). His Windows session ended
at **00:53**: rclone exited `0x40010004` (`DBG_TERMINATE_PROCESS`) and
Syncthing logged "Syncthing is being stopped / Exiting". The companion came
back at **18:24** (autostart, then a self-upgrade). Syncthing did not, and
stayed dead for eighteen hours with **12 GB unsynced**.

Three separate failures, and the third is the one that made it last eighteen
hours instead of five minutes:

1. **Nothing supervises Syncthing on an editor machine.** It is started by an
   HKCU `Run` entry (`CCSyncSyncthing` -> `wscript CCSyncSyncthing.vbs` ->
   `CCSyncSyncthing.cmd` -> `syncthing serve --home=...`), and **the Run key
   fires at logon and never again**. Nothing anywhere restarts it. The
   companion gets away with the same arrangement only because an editor who
   sees no tray icon says so.
2. **The companion knew and said it at DEBUG.** `repath.reconcile` logged
   `repath: local syncthing unreachable -- skipping reconcile` once a pass,
   for eighteen hours, at a level nothing collects.
3. **Lane C reported idle / green / 0 queued the whole time.** `check_once`
   does return `error` when the ping fails, but nothing carried that to a
   sentence anyone could act on: the tray's `classify_lane_error` had no
   branch for "Syncthing not running" and rendered the generic "Something
   went wrong. Tray -> Copy diagnostics for your admin."

**Fixed.** `companion/src/ccsync_companion/sync/syncthing_supervisor.py` is a
supervisor driven from lane C's existing 15 s poll (no thread of its own): 30 s
of unreachability, then it runs the same shim the Run key runs
(`wscript.exe //B //Nologo %LOCALAPPDATA%\ccsync\bin\CCSyncSyncthing.vbs`;
macOS `launchctl kickstart -k gui/<uid>/com.ccsync.syncthing`), detached
(`DETACHED_PROCESS | CREATE_NEW_PROCESS_GROUP`, `close_fds`, DEVNULL handles --
a child of the tray dies with the tray's next self-upgrade), waits up to 20 s
for the API, and backs off 30 s / 1 m / 2 m / 4 m / 8 m capped at 10 m. `INFO`
per attempt, `WARNING` plus a tray balloon naming the last stderr line at the
third failure, one balloon when it comes back. State lives in
`~/.ccsync/state/syncthing_supervisor.json` so the counter survives the
companion's own self-upgrade. It **stands off** while `sync_halt.json` is
active, while syncing is paused, and on `sync_enabled = false`: resurrecting
what somebody deliberately stopped is the one thing it must not do. Kill
switch: `supervise_syncthing = false`.

Lane C is now `error` whenever the API is unreachable, carrying the
supervisor's own sentence ("the sync engine (Syncthing) is not running on this
machine -- restarting it" / "...could not be started: `<why>`" / "...and it is
not being restarted: `<why>`"), which the tray line and the dashboard chip
repeat verbatim; an open incident also rides the report as
`sync_guard.syncthing_supervisor` (which the dashboard does not declare yet,
so it is dropped there for now -- the chip goes red off lane C's own state). `installer/windows_upgrade.ps1` gained step
5b, which starts the engine through the same shim when no `syncthing` process
is running -- the belt for a machine whose companion has not been upgraded
yet. A `401`/`403` is deliberately NOT an outage (the process is up, holding
another home's key).

Docs: `docs/SYNC_SAFETY.md` section 6, `docs/GOTCHAS.md` section 14
("processes die with the session that started them" -- including the SSH
corollary: a daemon started over SSH lives exactly as long as that session).
Tests: `companion/tests/test_syncthing_supervisor.py` (state machine, backoff,
three strikes, latches, kill switch, persistence, and the launcher seam's argv
and flags on both platforms -- no test spawns a process), plus the lane C,
tray and app-wiring halves in `test_syncthing_lane.py`, `test_tray.py` and
`test_sync_halt.py`.

**Still owed:** this is unshipped. Every editor keeps the old behaviour until
they take a build carrying it, and the Mac half needs a Mac to build.

---

## Open — dashboard self-update over the air (WP K, 2026-08-18)

### WPK-1 — image mode never carried `templates/` or `static/` — FIXED in repo 2026-08-18, no image rebuilt yet
`dashboard/deploy/Dockerfile` copied `dashboard/src` and `dashboard/deploy`
and nothing else, while `ui.py`/`app.py` resolve `TEMPLATES_DIR`/`STATIC_DIR`
as `parents[2]` of the package — `/app/templates` and `/app/static`. That path
exists in bind-mount mode (the whole `dashboard/` tree is mounted at `/app`)
and did not exist in the image, so an image-mode container answered
`/api/v1/health` perfectly, passed its healthcheck, and returned a 500 for
every page and a 404 for every stylesheet. Never noticed because no
deployment runs image mode yet. Two `COPY` lines added; **every image built
before 2026-08-18, including anything `.github/workflows/image.yml` has
already pushed to GHCR, is unusable for the UI and must be rebuilt.**

### WPK-6 — the pre-recreate ZFS snapshot had been failing silently on every deploy — FIXED in repo 2026-08-18
Seen on the first image-mode migration: `FAILED to snapshot
tank/apps/ccsync-dashboard@...: dataset does not exist`, then `WARNING: no
pre-recreate snapshot ... Continuing`. `TrueNASBackend.resolve_dataset` asks
`df --output=source` which dataset a path lives in, and on this box the app
dir is a plain directory in the pool root, so df answers `tank` -- a name with
no slash, which the code treated as "not a dataset" and fell back to the naive
`tank/apps/ccsync-dashboard`. Every `--recreate` since the snapshot rule
landed (item 8) has run with nothing behind it; nobody read the WARNING
because the deploy went on to succeed. Fixed: a slash-less answer is a
dataset (a pool root), and only a device path / blank / whitespace answer
falls back. Two tests pin it. Sibling finding, same run: the runtime_id
differed between the CI image and this checkout only because git's autocrlf
gave the Windows working copy a CRLF `requirements.lock`; `runtime_id()` now
normalises line endings and every lockfile is `eol=lf` in `.gitattributes`.

### WPK-2 — nothing works until an image is rebuilt with `/venv/.runtime-id`
The whole two-tier rule keys off that file, and only an image built from the
updated Dockerfile has it. Until then `image_mode()` is false everywhere:
every apply is refused ("this deployment updates from the base rig"), the
Packages page's Dashboard section says so, and `select_code_root.py` boots the
image's own code no matter what is in `/data/code`. That is the correct
behaviour for **every live site today**, all of which are bind-mount mode —
this is a note about the order of operations for the first image site, not a
defect.

### WPK-3 — the code path is untested against a real container
Everything here was built and tested on Windows against temp directories: 63
tests, including the real bundle, the real stage-verify subprocess and the
real `select_code_root.py`, but **no `docker build`, no `docker run`, and no
NAS**. Specifically unexercised: `/venv/.runtime-id` actually being written by
the Dockerfile's `RUN` (the recipe is unit-tested, the `RUN` line is not); the
exit-75 loop under a real container runtime's signal handling and restart
policy; a real update over a real feed. First image site should do one apply
and one rollback deliberately before relying on it.

### WPK-4 — `min_version` is signed but unused for `dashboard` records
Every record signs `min_version`; for this kind nothing reads it. The only
ordering rule is "newer than the image's own version"
(`select_code_root.check_tree`), plus the operator's own choice of what to
publish. A downgrade floor for dashboard code would need a monotonic
high-water mark on the data volume, the way the companion keeps one in
`~/.ccsync/upgrade_floor.json`. Deliberately not built: a dashboard rollback
is one click by an admin who is standing in front of the thing, not an
unattended fleet-wide event.

### WPK-5 — the pre-update NAS snapshot needs a dataset name it cannot derive
`dashboard_update.snapshot_before` is best-effort like
`server/common.snapshot_before`, but a container sees `/data`, not the pool
path behind it — so it needs `DASH_UPDATE_SNAPSHOT_DATASET` in the
environment, and without it reports "skipped, and why" rather than guessing.
Also TrueNAS-only (`/zfs/snapshot`); a DSM site gets the same skip. The
database backups under `/data/backups/<ts>/` are taken either way and are the
recovery path that actually matters here.

## Open — b-roll ingest (BROLL-ING-n, 2026-08-18)

Found while building `docs/BROLL_INGEST_PLAN.md`. The first two are fixes that
happen to be about OLD features: the ingest work walked through code the ingest
work then had to share, and found both defects sitting there.

### BROLL-ING-1 — the fleet report threw away two whole sections, for weeks — FIXED in repo 2026-08-18, unshipped
`ReportIn` declared neither `proxy_coverage` nor `youtube_import`, and the
model is `extra="ignore"`, so pydantic discarded both on **every tick since
those features shipped**. The companion computed them, sent them, and reached
nobody: no proxy coverage on the grid, no YouTube import state, and no way to
tell from either end that anything was missing. Nothing logged, because
dropping an undeclared field is what `extra="ignore"` is for.

All three sections (the two above plus the new `broll_ingest`) now parse
through `_ReportSectionIn`, which **bounds instead of raising**: strings
truncated, sequences sliced, numbers clamped. A section that will not parse at
all is dropped with a log line rather than 422'ing the report, because a 422
here skips the route body entirely and takes that machine's lanes, transfers,
presence and upgrade advertisement off the grid with it (B6).

The lesson for the next section anyone adds: a field the dashboard does not
declare is not a warning, it is silence.
`dashboard/tests/test_broll_ingest_report.py` asserts each of the three
sections is persisted and chipped.

### BROLL-ING-2 — the companion's own preview proxies were black rectangles from any 10-bit camera — FIXED in repo 2026-08-18, unshipped
`ffmpeg_tools.preview_proxy_cmd` in the COMPANION had no `-pix_fmt yuv420p`.
The indexer's copy gained it on 2026-08-11, after every preview cut from an
FX3/FX30 XAVC source came back yuv420p10le, which browsers draw as a black
rectangle (R9). The companion's copy never got the fix, and the YouTube tier
has been using it since: every preview it made from a 10-bit source has the
same defect, and b-roll ingest was about to inherit it.

Fixed in `companion/src/ccsync_companion/ffmpeg_tools.py` (posters and frames
in `broll_ingest_media.py` pin `yuvj420p` for the same reason). Two copies of
one encoder that drifted for a week is the actual finding, and the guard is a
hand-copied literal: `companion/tests/test_ffmpeg_tools.py` asserts the whole
argv against `BROLL_NVENC_TAIL` / `BROLL_CPU_TAIL`, transcribed from the
indexer's `build_proxy`. It is a transcription, so it catches drift only in the
direction of the companion. A change on the indexer side still has to be
carried over by hand.

**Not swept.** Previews already made by the YouTube tier from 10-bit sources
are still black and will stay that way until something re-cuts them, exactly as
R9's archive sweep was declined.

### BROLL-ING-3 — a duplicate the editor unticks leaves no trace anywhere
Deferred, found in PR-J review. The pre-check marks duplicates and unticks them
by default ("already in the archive - clip #4127"), and the panel then sends
only the ticked rows: `chosen.map(...)` in `static/ingest.js`. So a clip the
editor deliberately declined is simply **absent from the batch**, not recorded
as `skipped` in it.

The schema is ready for the better answer -- `skipped` is already an
`ITEM_ENDING` and an `ITEM_TERMINAL` state, and the browse/tree/search queries
already exclude it -- so this is a UI and one request-body change, not a
migration. What it costs today: "40 clips, 38 indexed" with no explanation of
the other two, and no way to ask later what a batch chose not to ingest. Worth
doing the next time the panel is opened for other reasons.

### BROLL-ING-4 - the model download crawled at 2 MB/s on one stuck connection - FIXED in repo 2026-08-18, unshipped
Measured on the base rig while the tray fetched the Good tier: **~2 MB/s for
thirty minutes** on one long-lived HTTPS connection to Hugging Face, while
fresh connections from the same machine at the same moment got **13 MB/s**
single-stream and **~45 MB/s** over four parallel range requests. py-spy had
our thread parked in `ssl.read`, so the slow party was the CDN edge we had
been assigned, not the disk, not the GIL and not the hash. At that rate the
Good tier's 3.3 GB is over four hours, and an editor watching a bar that has
not moved in a minute concludes the feature is broken and closes the tray.

`download_verified` (in `broll/indexer/broll_index/local_runtime.py`, vendored
verbatim into the companion) now does two things instead of one:

- **Parallel ranged fetch.** When the first GET answers 206 with a total size,
  the file is split into up to `CCSYNC_DOWNLOAD_STREAMS` (default 6, clamped
  1..16) contiguous slices, each on its own connection, writing into a
  preallocated `.part` at its own offset. That first connection becomes slice
  0's rather than being closed, so N streams cost exactly N connections. A
  `.part.json` sidecar records the slice boundaries and the bytes done per
  slice, so a killed download resumes **each slice where it stopped**; it is
  deleted when the file completes and hashes. A `.part` with no sidecar is a
  partial from an older build (or from N=1) and resumes single-stream exactly
  as before, and a server with no Range support gets today's single stream
  unchanged.
- **Stall detection.** A stream that moves less than 256 KiB in 20 s is closed
  and its remaining range reopened on a new connection, which lands on a
  different edge, and that is the measured cure. Five stalls in a row, or
  three failed attempts, fail that slice and therefore the download, which
  KEEPS the partial and the sidecar so the next run resumes rather than
  restarts. Every retry after the first goes back to the ORIGINAL URL, because
  a signed CDN URL can expire under a multi-GB download.

Measured after the fix, same machine, same file (the Good tier's 836 MB
mmproj), 15 s each: **N=1 → 7.8 and 8.6 MB/s** (its rolling window down to
1.5-1.9 MB/s by the end, i.e. the bug reproducing), **N=6 → 37.1 and
39.8 MB/s**. About 4.6x.

The aggregate rate is published as
`download_verified.last_rate_bytes_per_s` (the progress callback's signature
belongs to the indexer and could not carry it) and both sidecars read it, so
`status()["downloading"]` gains `rate_bytes_per_s`/`eta_seconds`, the progress
window's headline reads "Downloading Qwen3-VL 4B (Good): 61% at 38 MB/s, about
1 min left", and the loopback `progress` payload's `model` object carries both
for the ingest SPA. The music CLAP artefact fetch benefits without a line
changed: `music_clap_sidecar` has always called this same function, and a test
now pins that it does.

Tests: `broll/indexer/tests/test_download_parallel.py` and
`companion/tests/test_vendored_downloader.py` run a threaded stdlib
`http.server` (Range and no-Range variants, a slice that goes quiet, a slice
that always 500s) over a 12 MiB random payload. What is NOT covered by a test:
the real CDN. The numbers above are the only evidence that the edge behaves
this way, and they came from a hand-run measurement against the live URL.

## Open — music ingest (MUSIC-ING-n, 2026-08-18)

Deferred deliberately while building `docs/MUSIC_INGEST_PLAN.md` steps 3-5.
Everything here is a gap in the NEW companion path; the older browser-upload
path is unaffected by all of it.

### MUSIC-ING-1 — a track the companion indexes has no bpm, key or loudness
`index_music.analyse_one` computes four DSP features beside the embedding:
tempo, key + confidence, LUFS and peak dB. Three of the four are librosa's,
and the companion has no librosa and must not gain one (it is a ~40 MB
dependency chain with numba and llvmlite inside a frozen exe, for four numbers
nothing searches on). So `music_ingest._post_result` sends them as null, the
server stores null, and the track's card shows no bpm.

Everything that matters is complete: the embedding, the per-window vectors,
the waveform, the probe fields, the tags and the axes. What is missing is the
**BPM and duration filters** in the left rail, which those rows fall out of,
and the key badge. A base-rig `index_music.py --retag` does not fill them in
either -- retag re-scores from stored embeddings and never touches audio.

Fix, when it is worth it: a `--features-only` sweep on the base rig that
decodes rows whose `bpm IS NULL` and fills the four columns, or a
scipy/numpy-only tempo+key estimator in the sidecar (they are not hard; they
are just not free to get identical to librosa's, and a bpm that disagrees
with the library's other 376 rows is worse than a blank one).

### MUSIC-ING-2 — the mid-batch fallback leaves the audio on the editor's machine
A companion whose model becomes unusable *after* the claim (a deleted cache, a
download that will not complete) ends the item `queued_for_base_rig` and does
**not** upload the audio. It cannot: the library's filenames are allocated by
the server at `result`, which never happened for that item, and the only name
this side could use is the one the file already has -- which is how you
overwrite another editor's `theme.wav`.

So the audio stays staged on the editor's machine and the page tells them to
drop it again (the browser upload does the whole safe dance: name allocation,
both duplicate defences, the transcode, the queue row). The plan's §1 wording
("uploads the file to the NAS and leaves an `ingest_queue` row") is therefore
only half-true today.

Fix: a fleet route that allocates a name and writes an `ingest_queue` row
without an embedding -- `POST .../items/{iuid}/queue` -- after which this path
uploads to the allocated name and the base rig drains it exactly as a browser
upload. Small, and it needs a decision about whether a *server-side* dedupe
should run at that point or at drain time.

### MUSIC-ING-3 — one progress window at a time
`CompanionApp._open_work_window` keeps a single window and closes the previous
one, so a music batch starting while the b-roll window is open replaces it
(and the tray's "Show … progress" items each bring their own back). Both
batches keep running and both tray sections stay correct; only the window is
exclusive. Fixing it means keying `_work_window` by kind and is a popup
change, not an ingest one.

### MUSIC-ING-4 — a queued_for_base_rig item counts as neither done nor failed
`status()["done"]` counts `live` and `failed` counts `failed`, so an item that
ended in the fallback leaves the progress window reading e.g. "11 of 12
tracks" for ever even though the batch has finished and been released. The
batch state on the fleet grid and in the panel is correct; the local window's
counter is not.

### MUSIC-ING-5 — every `GET /music/ingest/*` 404'd, so the feature was invisible on the machine holding the files — FIXED in repo 2026-08-18 (release prep), unshipped
`BrollRequestHandler._dispatch_get` tested `path.startswith(INGEST_PREFIX)` --
b-roll's prefix alone -- while the POST and PUT dispatchers both tested the
whole `INGEST_PREFIXES` set. So `capabilities`, `progress` and `thumb` fell
through to the generic 404 for music, and `capabilities` is the FIRST call the
music page makes: the page read the 404 as "this companion is too old", fell
back to the browser upload, and did so correctly and silently. Every other
piece of music ingest worked; nothing could reach it.

One line, now the same shape as the POST dispatcher, plus
`test_music_ingest.py::test_a_music_ingest_get_reaches_the_ingest_dispatcher`.
The general point: `_kind_for_path` made the handlers kind-agnostic, and the
three dispatchers each decide separately whether a path is theirs. A sixth
route group needs all three checked.

### MUSIC-ING-6 — the staging free-space floor was b-roll's on the route and music's in the batch — FIXED in repo 2026-08-18 (release prep), unshipped
`IngestKind.cfg_key` gives each kind its own `<prefix>_free_space_floor_gb`,
and the orchestrator has always read it that way. The loopback's own pre-flight
(`broll_server._ingest_floor_bytes`) read the b-roll key for both kinds, so a
site that set only `music_ingest_free_space_floor_gb` got its number in the
batch and b-roll's at the PUT that refuses before the first byte. Both default
to 20 GB, so only a site that changed one would ever have seen it. The helper
takes the kind now; `docs/CONFIG.md` §2.5b and §3 document both sets.

---

## Open — the 2026-08-17 commercial-readiness pass (CR-n)

### CR-1 — the b-roll indexer billed a personal Claude Code subscription — FIXED in repo 2026-08-17, unshipped
`broll/indexer` drove `claude -p` against one operator's claude.ai login: a
customer install has no `claude` binary and no such login, the session
limits are per-person, and the Consumer Terms do not cover reselling it. The
`claude` stage now calls the Messages API through the `anthropic` SDK
(`broll_index/claude_client.py`), key from `ANTHROPIC_API_KEY` (name
configurable) or a keyfile — never from config.yaml, which the loader
refuses. Contact sheets travel as base64 image blocks; `parallel_claude.py`
is a thread pool whose `--workers` is also the client's in-flight ceiling;
429/5xx/overloaded retry with jittered backoff honouring `retry-after`, then
classify as account-wide so the queue stays resumable. `total_cost_usd` in
`usage.jsonl` is now a LOCAL ESTIMATE. Not yet exercised against a live key —
owed: one real pass on a customer key to re-baseline per-clip cost.
`broll/docs/indexing-api.md`.

### CR-2 — the YouTube feature shipped on by default, with the vendor's Claude account, an unverified identity and no rights record — FIXED in repo 2026-08-17, unshipped
Items 1, 2, 3, 7/H5, 15 of the readiness doc, all in the ytdl stack:
- **It was on for everybody.** Now `site.toml [features] youtube_download`
  (default OFF, published in `GET /api/v1/site`): off, `mount_ytdl()` returns
  `disabled` before importing anything, `/ytdl` and every fleet route 404, and
  each companion hides its tray items, refuses `/ytdl/*` loopback calls and
  installs no tooling. A client that cannot read the manifest treats it as off.
  THIS studio's git-ignored `site.toml` sets both flags on.
- **No rights record.** A rights/ToS attestation is now accepted per user
  (`ytdl.db.attestations`) and per machine
  (`~/.ccsync/state/ytdl-attestation.json`) with wording version, digest and
  timestamp; downloads 403 (`reason:'attestation'`) in the browser, at the
  claim and in `capabilities()`. Wording is a DRAFT FOR COUNSEL
  (`docs/legal/YOUTUBE_FEATURE_NOTICE.md`).
- **The circumvention components were part of the install.** PO-token
  sidecar, deno n-challenge solver and cookie sign-in are a second, narrower
  opt-in (`[features] youtube_unblock` / `--enable-youtube-unblock`). The
  vendor build provisions none of them; the code stays dormant.
- **Every deployment ran on one human's Claude account** (`claude -p` +
  a hand-performed `/login` in a `claude-home` volume). Now the `anthropic`
  SDK with the CUSTOMER's `ANTHROPIC_API_KEY`; claude-bin/claude-home mounts
  deleted (removal + credential revocation steps in `ytdl/web/DEPLOY.md`).
  Untrusted page/title text goes in the user turn as fenced data.
- **The fleet token was treated as an identity (H5).** `X-CCSync-Identity`
  now carries the dashboard's signed identity token and `routes_fleet`
  verifies it against `DASH_SESSION_SECRET` (fails closed); `is_leaseholder`
  no longer accepts a nameless caller. `YTDL_DEV_USER` is gone, replaced by an
  in-process `session.set_test_user()`.
Owed: a written licence grant for `ytdl/web/ytdlweb/vendor/`
(`PROVENANCE.md` — upstream `The-Creators-Club/Utilities` has no licence
file), counsel review of the attestation wording, a retention policy for the
attestation + download records, and on the live NAS `rm -rf
<host-root>/claude-home <host-root>/claude-bin` + revoking the OAuth
credential.

### CR-3 — pystray (LGPLv3) was frozen into the companion, and its internals were copied — FIXED in repo 2026-08-17, unshipped
`pystray` is LGPLv3 (verified from installed metadata). It was collected into
the single-file PyInstaller freeze, which conveys it with no way to relink
against a modified copy, and `tray.py:242-395` monkeypatched its win32
internals. Replaced by `ccsync_companion/tray_native.py` — original, written
from the Shell_NotifyIconW / TrackPopupMenuEx / CreateIconIndirect and
NSStatusBar / NSMenu documentation. Removed from `pyproject.toml`,
`build.spec` and `requirements.lock`; `tools/check_licenses.py` FAILS if it
comes back. `CCSYNC_TRAY_BACKEND=pystray` remains as a dev escape hatch that
refuses under `sys.frozen`. Two old bugs die with it: the HMENU is built at
right-click time and destroyed on close (the destroyed-handle race and USER
leak behind the 2026-07-26 freezes are structurally impossible), and the
menu-open flag is set by the backend on BOTH platforms. Verified on the base
rig with `companion/tools/tray_smoke.py` (icon added, menu read back out of
USER32, item selected). **macOS is code-complete but unverified.**

### CR-4 — the installer conveyed a GPLv3 ffmpeg to the customer's NAS — FIXED in repo 2026-08-17
`install_dashboard_app.py` defaulted to `--ffmpeg-fetch local`: this
workstation SFTP-pushed johnvansickle's GPLv3 static build onto the target —
conveying under §6 with no source offer. Default flipped to `remote` (the
NAS curls the same pinned URL and verifies the same sha256); the 2026-08-10
reason for `local` (42 MB at ~28 kB/s outlived `run_ssh`'s 600 s) is
answered by `FFMPEG_REMOTE_INSTALL_TIMEOUT = 1800`, `curl --retry 3`, still
NON-FATAL. Air-gapped sites keep the push behind `--push-ffmpeg-from-local`,
which prints `FFMPEG_LOCAL_PUSH_GPL_NOTICE` before any bytes move. Watch the
first deploy: first time a NAS does the ~25-minute download under the new
ceiling.

*Posture note, 2026-08-18 (open, no action believed necessary).* The EDITOR
side changed scope: `sidecar_tools.ensure_ffmpeg_pair` is no longer behind the
YouTube feature gate, because b-roll and music ingest need ffmpeg on any
machine an editor drops files on. So every editor machine now fetches the
pinned `eugeneware/ffmpeg-static` build, where before only a youtube-enabled
fleet did. **The conveyance analysis is unchanged**: the editor's own machine
downloads it from GitHub, so upstream conveys and we only choose the build
(mode B in `docs/legal/THIRD_PARTY_NOTICES.md`). What changed is how many
customers meet a GPLv3 component at all, which is a question for counsel's
review of the notices, not a code change. The written offer in the notices
already covers the case where we do convey.

### CR-5 — no LICENSE, EULA, privacy policy, telemetry disclosure or third-party notices — DRAFTED 2026-08-17, awaiting counsel
All exist as DRAFTS FOR COUNSEL: `LICENSE`, `docs/legal/EULA.md`,
`PRIVACY.md`, `TELEMETRY.md`, `THIRD_PARTY_NOTICES.md` (generated by
`tools/gen_notices.py`, `--check` as a CI gate). The wizard's new page 0
requires acceptance and records `~/.ccsync/eula_accepted.json`; the companion
refuses to start lanes without a current one, and FAILS OPEN when the bundled
document is missing (a packaging fault must never stop a fleet syncing —
`build.spec`'s `assets/EULA.md` datas line is pinned by
`test_build_spec_ships_the_eula`). Bumping the EULA's `<!-- EULA-VERSION -->`
marker pushes every editor in every fleet back through the wizard — a
release-level decision. Open and both hard: counsel review starting with the
legal entity name (placeholder "Cablewrap Creative" was INFERRED from the
operator's email domain), and the `yt-credit-downloader` grant (CR-2). Also
from TELEMETRY.md: `resolve_project` / `local_manifest` / `media_tree`
reporting has no "off" but uninstalling — a config switch is owed.

### CR-6 — the upgrade channel was unauthenticated (STOP-SHIP) — FIXED in repo 2026-08-17, certificates NOT bought
`upgrade.url` and the sha256 that "verified" the download arrived in the SAME
plain-HTTP `/api/v1/report` response, so anything able to answer as the
dashboard could hand an editor an arbitrary binary plus a matching hash,
which `upgrade.py` renamed over the running companion and launched. FIXED:
every published record is signed offline with an ed25519 key that exists on
no server (`tools/release_key.py`, `tools/sign_release.py`; public half baked
into `ccsync_companion/release_pubkey.py`, pure-Python RFC 8032 verifier in
`ed25519.py`, no new frozen dep). The companion verifies BEFORE downloading
and the signed sha256 after; the dashboard verifies on publish against
`DASH_RELEASE_PUBKEYS` and refuses an unsigned publish (422) or an
unconfigured key (503). Plus a monotonic downgrade floor
(`~/.ccsync/upgrade_floor.json`, `min_version` in the signed record) and a
transport rule (https, or plain http to tailnet/LAN only, logged once).
Migration is additive: 0.7.11 can still take the first signed build. A key WAS
generated on this rig (`%USERPROFILE%\.ccsync-release\release.key`, pubkey
`GKNmk8MktRkGkrBv+ziF7O6ZNKCnjXfC9/TwDiYwKDY=`, id `ed717ff9611d6ec8`) — decide
whether to keep it before the first customer ship, and BACK IT UP OFFLINE
(losing it means no build can ever be offered to the fleet again). STILL
OPEN: no Authenticode or Developer ID certificate exists, so every build is
`signed_binary=false` and `tools\ship.cmd` needs `-AllowUnsignedBinary`; and
`DASH_RELEASE_PUBKEYS` must be set on both live dashboards (+ `--recreate`) or
every publish 503s. `docs/RELEASE.md` "Code signing".

### CR-7 — the 8899 loopback answered any page in the editor's browser (CRITICAL C1) — FIXED in repo 2026-08-17, unshipped
`broll_server.py` sent `Access-Control-Allow-Origin: *` plus
`Access-Control-Allow-Private-Network: true` and checked no Origin, Host,
token or content type — any ad iframe or phished link could insert clips
into the timeline being graded, start NAS fetches, spawn Explorer/`open`, and
claim fleet ytdl jobs. Three smaller holes went with it: `probe_darwin_mount`
interpolated `share` into `/Volumes/<share>` unvalidated (`../..` = `/`),
`/insert` was the one path route without containment, and a reveal could
`open` a `.app`. `docs/YTDL_LOCAL_DOWNLOAD.md:331` claimed an origin check
existed; it never had. Now: `loopback_guard.py` allow-lists the Origin to this
deployment's dashboard (`dashboard_url` + the cached site manifest, both
schemes); a POST needs that Origin OR the `X-CCSync-Loopback` token from
`~/.ccsync/loopback-token`, plus `Content-Type: application/json` and a
loopback `Host`; `share` is one safe segment; every path route
realpath-contains; bundles are revealed, never opened; fetches are capped at 2
and go through `root_guard`. `docs/LOOPBACK_API.md`. **Ops note for the ship:
every companion's `dashboard_url` must equal the origin editors actually
browse** (Tailscale Serve `https://nas.<tailnet>.ts.net` vs a provisioned
`http://100.x:8480`) or every Send-to-Resolve 403s; `loopback_extra_origins`
is the per-machine escape hatch, the site manifest's `dashboard_url` the
fleet-wide one.

### CR-8 — the dashboard's session layer: no revocation, no secret floor, spoofable X-Forwarded-Proto, no CSRF token — FIXED in repo 2026-08-17, unshipped
Items 6/H1, 12 and 15. A stolen session cookie was good for seven days and
nothing could stop it (rotating `DASH_SESSION_SECRET` signs out the fleet AND
invalidates every companion identity token); two browsers signing in as the
same editor in the same second got a byte-identical cookie;
`X-Forwarded-Proto` was believed from anyone; `DASH_SESSION_SECRET` /
`DASH_REPORT_TOKEN` had no strength check while compose ships `REPLACE_ME`;
the login throttle was an unlocked in-process dict, per-username only; CSRF
rested on `SameSite=Lax`; `DASH_REPORT_TOKEN_OPTIONAL` was one env var from
unauthenticated fleet writes. Fixed: server-side revocable sessions
(`sessions.py`, `auth_sessions` keyed by HMAC(secret, cookie); logout,
`[ LOGOUT ALL ]`, admin revoke on Users; 12h idle / 7d absolute), per-login
nonce, `DASH_TRUSTED_PROXIES` (default loopback), `DASH_COOKIE_SECURE=1`
refuses plaintext login, `check_boot_secrets` reuses
`broll.check_ingest_token` and REFUSES TO START on a weak secret, SQLite
throttle per-username AND per-IP with backoff and one generic message, CSRF
synchroniser token on every dashboard htmx/form POST, 12-char floor on
passwords the dashboard SETS, `DASH_AUTH_METHOD=oidc` (PKCE, state/nonce,
JWKS via PyJWT, `/login?local=1` break-glass) — never pointed at a real IdP.
`DASH_DEV_INSECURE=1` is the ONE dev/test bypass (`dashboard/tests/conftest.py`
sets it). BEHAVIOUR CHANGES ON DEPLOY: everyone is signed out once; the
container REFUSES TO BOOT if either secret is under 24 chars/placeholder —
CHECK THE LIVE VALUES FIRST; behind Tailscale Serve set `DASH_COOKIE_SECURE=1`
(not `auto` — the request arrives from the docker bridge, not loopback).
STILL OPEN: the three mounted SPAs (`/broll`, `/music`, `/ytdl`) do not send
the CSRF token yet and sit on `app._CSRF_EXEMPT_PREFIXES` (the token is on
the topbar they inject as `data-csrf`; one header each).

### CR-9 — the base rig trusted any host key, the container held the NAS root password, and every editor had a shell — FIXED in repo 2026-08-17, unshipped
Items 6 (H2/H3) and 7 (H4). SSH: `ssh_client` accepted whatever answered on
22 while writing the admin password to that channel — pinning is now the rule
(`[nas] ssh_hostkey`); an unknown host is a refusal, first use needs
`--trust-host-key-on-first-use` and is recorded in `~/.ccsync/known_hosts`, a
CHANGED key refuses naming both fingerprints. TLS: `verify=False` became
`TRUENAS_VERIFY_SSL` (off still allowed, warned every run, CA path works from
the container). Container: `server/create_api_key.py` mints a scoped TrueNAS
API key; with `TRUENAS_API_KEY` set the deploy writes NO password into the
container (DSM has no equivalent and keeps the password behind loopback).
Editors: new accounts are `nologin` + sshd `Match Group editors` block
(`ForceCommand internal-sftp`, `PasswordAuthentication no`) and the manifest
publishes `sftp_shell_type=none` automatically; NO ChrootDirectory (would
re-root every absolute path the manifest publishes); `[stack] project_acl =
"per-project"` adds `proj-<slug>` groups + setgid+sticky containers
(`docs/TENANCY.md`), default `shared`. `server/secure_syncthing_gui.py` puts
a login on the Syncthing GUI (an unauthenticated admin surface on both
platforms until it is run). Residual, deliberate: THIS fleet is pinned to
`[stack] editor_shell = "shell"` in its site.toml until
`setup_editor_account.py --migrate-existing --apply` runs (deploying with it
flipped early breaks every editor's rclone checksums); the `api_key.create`
body shape and the chart's `web_port.host_ips` are coded from knowledge and
marked "verify against the live version"; the dashboard provisioner does not
yet add proj-<slug> membership on a tick; DSM per-project is a grant plus an
operator TODO.

### CR-10 — the fleet had no backups at all, and the b-roll index was published by `copy` over a live WAL database — FIXED in repo 2026-08-17, NOT YET APPLIED to either NAS
Zero references to snapshots, replication or restore existed; the only
`broll.db` publish recipe was a plain SMB copy over a WAL-mode database the
container holds open read-write. `server/setup_snapshots.py` creates the
periodic tasks on the tree AND the apps dataset (hourly keep 24, daily keep
30, recursive) idempotently — TrueNAS via `/pool/snapshottask`; DSM prints the
exact Snapshot Replication click path and exits 1. `common.snapshot_before()`
snapshots before `setup_tree.py`'s `chown -R` and before the deploy /
`--recreate` swap (best-effort unless `--require-snapshot` /
`$CCSYNC_REQUIRE_SNAPSHOT`). `server/publish_db.py --which broll|music` is
the ff3 memory-note recipe as code: checkpoint, local `sqlite3.backup()`,
`quick_check` locally AND on the NAS, >10 % row-count shrink refusal, atomic
rename, `<name>.db.prev-<ts>` kept, `--rollback`. Runbook
`docs/BACKUP_RESTORE.md`. Owed by the operator: `setup_snapshots.py --apply`
on the TrueNAS (and the Synology), then `--list` within the hour — until then
this entry is code, not protection; the `pool.snapshottask` payload is
unverified against a live 25.10 middleware.

### CR-11 — lane B could walk a proxy set into the trash 20 GB per pass with the grid green — FIXED in repo 2026-08-17, unshipped
`--max-delete 100 / 20G` bounds ONE pass, not the sequence: a wrong
`remote_root`, a NAS listing empty while its pool imports, or a project
unshared behind the companion's back all present as "the source no longer
has these files". Four more edges went with it: `.ccsync-trash` never pruned;
"Remove from this machine" `rmtree`'d with no caught-up check; Pause was not
Stop and nothing could halt lane C or the fleet; lane A silently never
re-uploads a same-name re-export. Fixed in `sync/lane_guard.py`: a persisted
**circuit breaker** (trips BEFORE a pass on a marker-less/empty/halved
remote, AFTER on >50 deletions or >25 % of the local proxy set, and on a
cumulative leak; lane B parks `paused` — never `error` — while lanes A and C
keep running; cleared only from the tray); **trash retention** (14 days /
50 GB, oldest first, never while tripped — a deliberate reversal of AUDIT_2
C-7); a fail-closed **removal gate** (lane A `--dry-run` + Syncthing
completion; override = type the project name, logged AND reported); a real
**halt** (lanes A+B stopped and every lane C folder paused via Syncthing REST,
persisted; fleet-wide via `POST /api/v1/fleet/halt` + a Users-page panel,
delivered on the report reply's `commands.halt`); and a `rclone check
--one-way --size-only` "won't upload" counter. Dashboard: schema v16,
`sync_guard` report section, row chips + fleet banners. `docs/SYNC_SAFETY.md`.
Costs: one extra `rclone lsf` per lane B pass; the first pass after upgrade
computes the baseline and may trip once on a project mid-reorganisation.

### CR-12 — the companion rewrote Resolve project databases with no save, no backup and no undo — FIXED in repo 2026-08-17, unshipped
Four code paths write clip paths — FIX ALL, the automatic canonical relink,
the automatic proxy repoint, the post-import canonicaliser — and two are
unprompted; none saved, exported or journalled, and Resolve's Undo does not
cover a scripted `ReplaceClip`. Now `resolve_journal.py` + a
`_before_mutation()` hook inside `resolve_bridge.replace_clip` /
`link_proxy_media`: `SaveProject()`, best-effort
`ProjectManager.ExportProject()` to `~/.ccsync/resolve_edits/<project>/<ts>.drp`,
and a per-burst JSON journal of old/new path per clip; Tray → Advanced →
"Undo the last clip-path change CCSync made…" replays it in reverse; the
unprompted paths are rate-limited to one burst per project per 15 min; the
fixer re-checks its O_EXCL reservation immediately before `os.replace` and
verifies copy size + source stability before relinking; `fixer_dry_run` /
`proxy_dry_run` rehearsal switches. `docs/RESOLVE_EDIT_SAFETY.md`. Add new
Resolve mutations THROUGH those two bridge functions. The companion suite's
`_no_live_resolve` conftest fixture exists because the save point calls
`connect()`. Unverified: that `ExportProject` really writes the `.drp` on a
live Resolve (fakes only) — check once on the base rig.

### CR-13 — proxy generation: no free-space floor, one-sample growing-source test, would encode a proxy of a proxy — FIXED in repo 2026-08-17, unshipped
`free_space_shortfall()` keeps max(20 GB, 5 %) clear
(`proxy_gen_free_space_floor_gb/_pct`), checked before anything is created,
skipped-and-surfaced (log, tray, `coverage()["low_space"]`); two (size,
mtime) samples `proxy_gen_stability_seconds` apart replace the single mtime
(rclone/Syncthing/card copiers stamp mtime at create AND finish); `is_proxy_path`
refuses `Proxy/`/`proxies/` at any depth, `.partial`, and a file that is its
own output.

### CR-14 — `fix_10bit_proxies.py --apply` could transcode an archive ORIGINAL in place, and `build_archive.py --apply` undid its repairs — FIXED in repo 2026-08-17
`reencode()` overwrote whatever it was handed and `source_for()` fell back to
the target itself whenever the parent was not `Proxy` — a row pointing at the
top-slot original got the archive's best copy re-encoded to 540p over
itself, `fixed` printed beside it. Now refused outright (`is_a_proxy`),
refusals printed in the dry run too. `build_archive --apply` decided by size
alone, so every R9 repair looked un-copied and the next build put the 10-bit
source back — now `needs_copy()` walks absent → size → mtime → quick
head+tail hash, `broll_index/inplace_fixes.py` records repairs at the archive
root and protects them, and anything replaced is stashed under
`.ccsync-replaced/<ts>/` (never swept automatically).

### CR-15 — the onboarding wizard tore down a real NAS `P:` mapping — FIXED in repo 2026-08-17
`execute_cleanup` ran `subst P: /D` + `net use P: /delete /y` on the ROLE
alone; the bootstrap (INST-15) and uninstaller (D-8) already refused to touch
a `P:` they did not create. Now `p_mapping_is_ours()` applies the bootstrap's
rule verbatim (subst = ours, `\\localhost\CCSync_P` = ours, the site's
`smb_unc` or any other UNC = refuse, unreadable = refuse).

### CR-16 — a Mac upgraded across the LaunchAgent rename could run two companions — FIXED on both sides in repo 2026-08-17, unshipped
Bundle ids and launchd labels moved `com.creatorsclub.*` → `com.ccsync.*`
(item 10). A machine installed before that has the legacy label still
bootstrapped, pointing at the same `~/.local/ccsync/bin`. The wizard
(`steps.retire_legacy_launch_agents()`) and `installer/macos_bootstrap.sh`
(`retire_legacy_agent`) both bootout + unload + delete the legacy pair before
writing the new one; `macos_uninstall.sh` enumerates both generations. Never
run on a Mac — the first Mac upgrade after this must be watched
(`launchctl list | grep ccsync` shows exactly one companion). Also from the
brand pass: every "Creators Club" string is site data (`org_name`/`org_short`,
fallback `product_name` = "CC Sync"), the tray mark was briefly the neutral
`assets/ccsync_mark.png` — reversed 2026-08-18, see CR-25 — the
b-roll own-footage slug is `BROLL_DEFAULT_COLLECTION` (default `owned`, legacy
`creators_club` still routed), and the music `W:\Creators_Club` probe is
`MUSIC_LIBRARY_ROOT`. Not changed on purpose: the PHYSICAL `Creators_Club`
archive/tree directory name — a migration, not an edit.

### CR-17 — the installers were a fork per customer, and shipped unverified binaries — FIXED in repo 2026-08-17, unshipped
`P:` and `Creators_Club` were literals at ~70 sites in `windows_bootstrap.ps1`
(mount, teardown, `CCSync-SubstP` task, `CCSync_P` share, `MountPoints2`
label, the "is this drive somebody else's?" guard); a site mounting elsewhere
got an uninstaller that silently removed nothing. Both now derive from the
manifest's `canonical_prefix`/`tree_name`; the uninstallers read the prefix
from the local `config.toml` (off-tailnet). rclone (v1.75.0) and Syncthing
(v2.1.3) are pinned by version + sha256 in both bootstraps, verified before
unpacking, "latest" resolvers gone. The editor-laptop SMB share now comes with
an inbound block on TCP 139/445 (loopback is not filtered, so the mapping
still works; `-KeepRemoteSmbOpen` opts out); the elevated helper is a per-run
random name in an ACL'd per-user dir; `config.toml`/`identity.json` get
`icacls /inheritance:r` on install AND upgrade; `setx` for the four operator
secrets is replaced by `tools/load_secrets.ps1` (DPAPI) + `docs/SECRETS.md`.
Client data files (`config.queue.yaml`, `config.ff2.yaml`,
`duplicates_report.md`, `broll/eval/queries_*.yaml`) moved to a git-ignored
`private/`; `docs/macos-onboarding-handoff.md` scrubbed; `.gitignore` gained
the defence-in-depth patterns; `tools/make_product_repo.ps1` +
`docs/PRODUCT_REPO.md` are the squashed-product-repo recipe (not run). Owed:
`INSTALLER_VERSION` 1.0.30, one real install on a scratch Windows machine, and
the macOS half has still never run on a Mac.

### CR-18 — one fleet token for everyone, and four write paths behind it — FIXED in repo 2026-08-17, unshipped
`DASH_REPORT_TOKEN` proved "this is a companion", nothing about WHOSE, and
was not revocable per editor. Now an admin mints a per-editor token on Admin
› Users (`cce1.<id>.<secret>`, stored as sha256, shown once, revocable) and it
BINDS: a report or selection read under it may not claim another editor; the
shared token stays accepted behind `DASH_SHARED_REPORT_TOKEN_ENABLED`
(default 1) and the dashboard NAMES the machines still using it at every
boot. Handing a token over is manual by design (`/api/v1/verify` is the
unauthenticated bootstrap and must never issue one); it goes in `config.toml`
as `report_token`. Also: `identity.json`/`config.toml` owner-only via
`secretfile.harden` (`icacls` on Windows — `chmod` is a no-op there); the
reporter, selection client and ytdl executor no longer follow redirects
(stub the OPENER in tests, never `urlopen`); `broll/web` standalone ingest
fail-closed (no token = 503, dev branch deleted); `music/web` ingest
fail-closed when not behind the dashboard login and bounded (64 files /
512 MB); error bodies no longer carry NAS hosts or absolute paths (+ a global
500 handler); fleet reads are scoped (an editor sees their own machines plus
counts; another editor's device is a 404). Owed: publish a companion build
BEFORE minting any token; flip the shared token off only when the boot log
goes quiet; set `BROLL_INGEST_TOKEN` on any dev checkout of `broll/web`.

### CR-19 — the container's dependency set was never recorded, and no CI ever ran — FIXED in repo 2026-08-17, unshipped
Every dependency was a floor, one exact pin, no lockfile, no
`--require-hashes`. Now eleven `requirements.lock` files (`uv pip compile
--universal --generate-hashes`), `deploy/run.sh` prefers the lock with
`--require-hashes`, `dashboard/deploy/Dockerfile` bakes it into a
digest-pinned image (`compose.image.yaml`, `docs/DOCKER.md` — bind-mount mode
stays the default and both share one entrypoint), `.github/workflows/ci.yml`
runs every suite on Windows/Linux/macOS with `tools/check_licenses.py` and a
CRLF byte-scan; `release-windows.yml` / `release-macos.yml` build (never
publish) — the Mac runner is the answer to "PyInstaller needs a Mac".
`crash_report.py` on both sides writes a local redacted crash JSON always and
sends only on an explicit opt-in the shipped builds cannot satisfy (no
`sentry_sdk`). NOT verified: nothing has been through `docker build` (no
Docker on the base rig; `--require-hashes` forbids the source-build fallback,
so a wheel-less package fails early); `install_dashboard_app.py` still deploys
bind-mount mode only; the repo has never been pushed to a CI provider.

### CR-20 — the music queue drain overwrote every upload queued while it ran — FIXED in repo 2026-08-17 (MUSIC-13)
"Pull `music.db`, drain on the base rig, push back" is a file copy with no
merge — every `pending` row created during the window was discarded. Now
`ingest_queue.uid` (migration `003_ingest_journal.sql`), `index_music.py
--queue --export-drain` writes a result bundle, and `python -m musicweb.drain
apply` merges it in one transaction (`INSERT … ON CONFLICT`), closing only
the named uids and only when the live journal still agrees on `rel_path` +
`content_hash`. Also from item 14: both indexers' paths are
required-not-defaulted (`BROLL_DATA_ROOT`, `BROLL_DB_PATH`, `CCSYNC_WHISPER_*`,
`MUSIC_DB_PATH`, …; the base rig must now SET the two whisper keys or
transcription skips), the faster-whisper env is in-repo
(`broll/indexer/tools/make_whisper_env.*`), and `tools/Dockerfile.indexer-gpu`
packages both indexers (written, not built). `docs/INDEXERS.md`. The NAS's
`music.db` migrates to v3 on the first redeployed dashboard boot; the first
real drain has not been run.

---

### CR-21 — a declined NEW PROJECT prompt could come back after a companion restart — FIXED in repo 2026-08-17 (found by the integration pass), unshipped
`project_setup._record_asked` wrote the "already asked" map with
`write_text` (create-truncate-write-close), so a concurrent reader could see
zero bytes; `_load_asked` swallowed the `JSONDecodeError` and the whole map
came back empty — the popup returns for a project the editor already
declined (the same family as the 2026-07-25 recurring-popup incident). It
surfaced as one intermittent test failure during the 13-suite integration
run. Now temp-file + `os.replace`, like `identity.save_identity`; two tests
pin it.

### CR-22 — 0.8.0 upgraded a machine into "this machine isn't set up yet" and left no way out — FIXED in repo 2026-08-18, unshipped
Seen live on the base rig the morning after the 0.8.0 build. CR-5's licence
gate is correct — `_start_lanes()` refuses without a current
`~/.ccsync/eula_accepted.json` — but the ONLY thing that wrote that record was
the onboarding wizard, and **the wizard does not run on the path editors
upgrade by**: `upgrade.py` swaps the exe in place and restarts. So the new
build came up, refused to sync, and `tray._format_lane_line_from` rendered
that refusal as the generic *"NOT SYNCING (this machine isn't set up yet)"* on
all three lanes — a sentence that points at the admin, for a state only the
person at the keyboard can clear. A toast said the real reason; nothing in the
menu could act on it. Every editor taking the 0.8.0 offer would have landed
here, silently, one machine at a time.

Now the companion asks, showing the document it already bundles:
`popup.licence_dialog` (scrolling, verbatim `assets/EULA.md`, ACCEPT /
DECLINE — no Return binding, since this is the one dialog where a stray
keypress records a legal agreement), `app.prompt_licence_acceptance` once per
run three seconds after the tray starts, and a **tray item** *"► Accept the
licence agreement to start syncing…"* that is present exactly while the gate
is (in the menu fingerprint, or it would survive the click that cleared it —
UI-3's shape). ACCEPT calls `_start_lanes()` in the same breath, so syncing
resumes with no restart. A build with no bundled document refuses to record
anything rather than accept nothing (the gate itself still fails OPEN there,
per CR-5). The wizard remains the fresh-install path, and
`installer/windows_upgrade.ps1` now launches it (step 6) when a package
upgrade finds no current acceptance — skipped on `mode = "base"`, where
`tools\ship.cmd` runs that script at the end of every release and the rig's
config is hand-built. The package ships `EULA.md` beside `onboard.exe` so the
script can read the `<!-- EULA-VERSION -->` marker a frozen exe hides.

### CR-23 — item 10's de-branding took a fleet's logo and could only be given back machine by machine — FIXED in repo 2026-08-18, unshipped
The tray/window mark became `theme.PRODUCT_MARK_ASSET` with one escape hatch,
`$CCSYNC_BRAND_LOGO` — **machine environment**. Right for the vendor default
and wrong for the fleet already wearing its own logo: on upgrade every editor
silently swapped to the neutral mark, and getting the studio's back meant
setting an env var on every machine (in practice, a reinstall). The customer
noticed the same morning as CR-22, on the same build.

The mark now travels with the brand strings it belongs to: `brand_logo` in
`[site]`, published by `GET /api/v1/site` (additive to schema 1, blank = the
product's own), editable on the dashboard's Settings page with no container
`--recreate`, seeded at deploy by `DASH_SITE_BRAND_LOGO`. `theme.
brand_logo_override()` is now env → manifest → product mark; **the env var
still wins**, because an escape hatch a server can overrule is not one. A bare
name still selects a mark the build ships — `build.spec` keeps
`cc_mark_white.png` beside `ccsync_mark.png` for exactly this — and a manifest
naming a missing file falls back rather than failing, since a server can now
set it. `companion/tests/conftest.py` clears the env var for every test: a
developer's own branded rig was otherwise deciding what the suite measured.

---

### CR-24 — the taskbar never showed the window mark at all: Windows grouped every popup under the exe and drew the exe's icon — FIXED in repo 2026-08-18, unshipped
`theme.apply_window_icon` had been setting the title-bar icon since 0.4.7 and
nobody had checked the taskbar button. Measured 2026-08-18: same window, title
bar wearing the mark, taskbar wearing **python.exe's snakes** (a frozen build:
`icon.ico`, i.e. the exe's icon rather than the window's, regardless of
`brand_logo`). The Windows taskbar decides which *application* a window
belongs to when its button is created; a process that never declared an
AppUserModelID is "the exe", and the button takes the exe's icon.

*Corrected 2026-08-18:* this entry originally called `icon.ico` "one studio's
logo on every customer's taskbar", which read it as a branding leak. CR-25
settled that question the other way: the Creators Club mark IS the product
default, so `icon.ico` being the CC logo is correct and was never the defect.
The defect is only that the taskbar showed the *exe's* icon instead of the
*window's*, so a white-label fleet's `brand_logo` had no effect there.

`theme.claim_app_identity()` declares `com.ccsync.companion` (the same
product-id family as the macOS bundle/launchd labels) — Windows-only,
idempotent, silent. `app.run()` calls it before `load_config()` (the earliest
thing that can put a dialog up), and `apply_window_icon` calls it again so a
process that never went through `run()` (the wizard, a test) still claims it
before its first window maps. Verified: with the id set before the first
`tk.Tk()` *or* after it but before the first map, the taskbar shows the tinted
window mark; set after the first map, the button is already grouped and stays
on the exe icon. Which mark that is remains `brand_logo`'s decision (CR-23);
this fleet's `site.toml` names `cc_mark_white.png`.

Also seen while measuring: a companion-suite run leaked a REAL Tk window
("MAKING PROXIES", system `python -m pytest`) onto the operator's desktop — the
progress-window tests must go through the conftest's headless pattern; sent
back to the builder before merge.

---

### CR-25 — the neutral product mark was the wrong call: this is Creators Club software, branded like Resolve or Premiere — DONE in repo 2026-08-18, unshipped
Item 10 read "no customer's name in code" as "no brand in code" and shipped a
neutral placeholder mark by default, with the CC logo demoted to a per-fleet
setting (CR-23). The owner's answer 2026-08-18: *"our brand on every
customer's build is what I want"* — CC Sync is sold under the Creators Club
mark the way Resolve carries Blackmagic's. `theme.PRODUCT_MARK_ASSET` is
`cc_mark_white.png` again; `ccsync_mark.png` stays shipped as the neutral
alternative a white-label fleet can select through `brand_logo` (the
mechanism CR-23 built is unchanged — only the default flipped). Not touched:
`org_name`/`org_short`/`product_name` stay site data (a customer's *name* is
theirs; the *mark* is ours), the dashboard favicon (already CC), `icon.ico`
(already CC).

### CR-26 — the AI CLI setup wizard: two halves that could only be verified from Windows — BUILT in repo 2026-08-18, UNVERIFIED on a container
The owner read the Settings row *"Claude Code: not installed. no `claude` on
this container's PATH. Install it on the dashboard host, or set its full path
below"* and said: *"we should make this process a click-through wizard, this is
too complex for most users."* Built as
`dashboard/src/ccsync_dashboard/cli_tools.py` (notice, install, sign in, test).
What was verified, and how, on 2026-08-18 from the base rig:

* **The Claude Code distribution.** `GET
  downloads.claude.ai/claude-code-releases/latest` answers `2.1.234`;
  `/2.1.234/manifest.json` carries `platforms["linux-x64"].checksum` (sha256)
  and `.size` (328,358,192 bytes = **313 MiB**, so the 300 MiB cap this was
  first specified with would have refused the real binary on day one; the cap
  is 512 MiB and the manifest's exact size is enforced instead).
* **The Claude Code command surface**, against the locally installed 2.1.234:
  `claude auth login [--claudeai|--console]`, `claude auth logout`, `claude
  auth status --json` (`{loggedIn, authMethod, apiProvider, apiKeySource,
  email, orgId, orgName, subscriptionType}`) and `claude setup-token` all exist
  with those spellings.
* **The Codex distribution.** The asset names in the task
  (`codex-x86_64-unknown-linux-gnu.tar.gz`) **do not exist**: the publisher's
  own `install.sh` picks `codex-package-<arch>-unknown-linux-musl.tar.gz` on
  every Linux (the Linux builds are static musl) and verifies it against the
  `codex-package_SHA256SUMS` asset in the same release. That is what is
  implemented, checked against `rust-v0.147.0`'s 200 assets.

**What could NOT be verified from Windows, and is what to check first on the
container:**

1. **The pty sign-in itself.** `claude auth login` was never run: this machine
   has no pty (`pty.openpty` is Linux-only) and no WSL, and running the real
   login would have re-authenticated the owner's own account. So it is not
   known whether `auth login` accepts a pty as a terminal inside the container,
   nor exactly how it prompts for the code. BOTH strategies are implemented,
   login first, with an automatic fall back to `setup-token` when the CLI says
   something in `_NO_TTY_MARKERS` before printing a URL. The URL parser is
   pinned by tests against synthesised output, NOT against a real transcript.
2. **`codex login --device-auth`.** Detected at runtime from the downloaded
   binary's own `codex login --help` rather than assumed, but neither branch
   has been run.
3. **A real 313 MB download onto the NAS**, and the pointer flip under a
   container uid.

Until 1 is verified, the manual path stays documented and the page still
prints the login command beside the wizard.

### CR-27 — the licence dialog CR-22 added can never open on a machine with stray clips — FIXED in repo 2026-08-18, STILL UNSHIPPED, and it cost another 18 hours on 2026-08-19
CR-22 gave a self-upgraded machine two ways back: a dialog three seconds after
the tray starts, and a tray item. On the first machine in the fleet to take
the 0.9.0 offer, **only the tray item ever existed**, and nobody knew to look
for it. `app.prompt_licence_acceptance` takes `_popup_active_lock`, and the
offline-clips popup (`app.py`'s *"N clip(s) outside <root>"*) takes that lock
~3 seconds earlier on every single start:

```
18:24:46 INFO  ccsync.app: popup: 65 clip(s) outside F:\Creators_Club
18:24:49 INFO  ccsync.app: licence dialog: another CCSync window is open -- not stacking a second modal on it
```

The `_licence_prompted = False` reset in that branch is written for "ask again
next start" — but the collision is not a coincidence of timing, it is the
steady state of any editor whose Resolve projects reference clips outside the
tree (here: 65, then 102, every start, for hours). Reproduced verbatim on
0.9.0 and again on 0.9.2 after a remote upgrade the same evening. Net effect:
ruskin's three lanes sat parked from 18:24 local with 514 files / 12.3 GB
queued behind them, and the only route out was an admin telling him which tray
item to click.

Fixed with the re-arm: `app._licence_watch()` (a thread, not the old
`threading.Timer(3.0, ...)`) keeps offering the document every
`LICENCE_RETRY_SECONDS` for as long as the gate is live AND the dialog has
never actually been shown. It stops on `_licence_asked`, which is set once
the document reaches a person -- accepting or declining is their call, and a
modal that comes back after a DECLINE is how an editor learns to dismiss it
unread. A build with no bundled `assets/EULA.md` settles immediately (a
packaging fault is not something a retry fixes), a Tk root that cannot be
built at logon does not (that one a retry does fix), and the deferral logs
once per run and then at DEBUG. `_stop_event` ends it, so a Quit or a
self-upgrade is never held up by a licence nobody accepted.

### CR-28 — the base rig sits in [ QUEUED ] forever, because a tick belongs to a person and not to a computer — FIXED in repo 2026-08-18, unshipped
Seen on the fleet page 2026-08-18: `alex · 2026/FF5/Animals [ GETTING READY ]
just ticked; sharing and first file lists are being set up, syncing starts
within a minute or two`, ten hours after the tick, on the machine that works
directly off the NAS and syncs nothing. `api.build_transfers_view`'s pending
block (the GETTING READY source) joins `selections` to `projects` and nothing
else, so it reads "ticked, and no completion row yet" as "starting up" — a
condition a base-mode machine satisfies permanently, because it never syncs
and therefore never gets a completion row. `db.fetch_sync_backlog` already
excludes base machines (`WHERE emp.mode != 'base'`); the other two queue
sources in the same view do not.

The deeper cause is that `selections` is keyed `(editor_username,
project_slug)` while every consumer downstream of it is keyed by machine, and
`mode` is only ever persisted onto `editor_media_project` rows.

Fixed as WP0 of `docs/MULTI_MACHINE_PLAN.md`: `machine_state.mode` (schema
v22) records the role on the machine's own row, so a base rig that has never
sent a media manifest is still knowable as one; `db.base_only_editors` is the
one predicate all three queue sources now share; and the tick itself is
refused (409, *"this is a base rig account: it works directly off the NAS and
syncs nothing"*) on `PUT /api/v1/selection/...`, on the sidebar toggle route,
and visibly -- the checkbox renders disabled and the assignments column says
`base rig`. UNTICKING stays open, or the row that started this could never be
removed. The rest of that plan (per-machine sync plans, so one person can own
two editing machines) landed in the same pass.

**Live data still owed on the NAS**: the stray row
`('alex','2026-ff5-animals')` predates the refusal and is invisible but
present -- `DELETE FROM selections WHERE editor_username='alex'` after the
dashboard carrying v22-v25 is deployed.

---

### CR-27a — CR-27 recurred on the same machine, because the fix is in the repo and not on the editor
Investigated 2026-08-19. ruskin's three lanes were parked again from
2026-08-18 18:24 to 2026-08-19 12:10 local -- roughly 18 hours -- with the
same `lane_report_current.detail`:

```
NOT SYNCING: The CC Sync licence agreement has not been accepted on this machine.
```

`~/.ccsync/eula_accepted.json` was absent and his log carried the CR-27
collision verbatim on 2026-08-18 23:01 and 2026-08-19 11:54, plus one new
line at 11:24:39 -- `licence agreement DECLINED (or dismissed)` -- i.e. when
the document finally did reach him he closed it, and CR-27's re-arm
deliberately stops after `_licence_asked`. He accepted at 12:10:54 and the
lanes came straight back.

Nothing new to fix in the code: CR-27's `_licence_watch` is the fix and it is
sitting in the repo at companion 0.9.3 while the fleet runs 0.9.2. **The
lesson is the shipping order, not the logic** -- a gate that parks sync was
released (0.9.0) before the dialog that clears it worked. Two things worth
carrying:

- the dashboard shows a parked machine as `state=idle, queued=0`, which is
  visually identical to "nothing to do". `detail` holds the whole diagnosis
  and no page reads it. A machine that is refusing to sync for a reason the
  editor can fix should say so on the fleet page.
- a DECLINE is indistinguishable from a dismissal (a closed window). Treating
  "they clicked the X" as "they read it and said no" is what left the re-arm
  disarmed here.

### CR-29 — requester-first YouTube downloads never ran once, because a busy companion cannot answer in a second
Measured on ruskin's machine 2026-08-19. Every ytdl job ever created is
`download_mode: server` -- **45 of 45, across every editor** -- despite the
NAS having `YTDL_LOCAL_DOWNLOAD=1`, his companion answering
`/ytdl/capabilities` with `ok: true`, and yt-dlp/ffmpeg/deno all present in
`%LOCALAPPDATA%\ccsync\tools`. R18 blamed the flag and the missing ffmpeg;
both were fixed, and the feature still never engaged.

The cause is the probe budget. `app.js` allowed the capability probe
`PROBE_MS = 1000` and made exactly one attempt. Timed on the live machine
with the client's own HTTP stack pre-warmed, so the number is the server's:

```
warm-stack, server warm  :    6 ms
after 60s companion idle : 3949 ms      <- aborts, job silently goes server-side
after 120s idle          :    3 ms
```

`capabilities()` does no I/O by design and answers in single-digit
milliseconds warm, so this is not that function being slow -- it is the
request waiting behind whatever else the companion is doing (his lanes had
just restarted, so it was mid-sync-pass). Intermittent, multi-second, and
invisible: the editor sees "downloading on the server" and no error, which
reads as the feature not existing. The exact confound is worth naming for
whoever picks this up: a *client*-side first-call cost looks identical, which
is why the number above was re-measured with the stack warmed first.

FIXED in repo 2026-08-19 (`ytdl/web/static/app.js`): the probe now tries
`PROBE_MS` and then, **only if the first attempt timed out**, `PROBE_RETRY_MS
= 5000`. A refusal (nothing listening, Chrome blocking the local-network
request) still fails in milliseconds and is not retried, so a machine with no
tray app costs exactly what it did before. Nothing the editor waits on:
`startDownload` never awaits the probe, and a late claim is the handover
`claim_download`'s lease design already supports.

Not fixed, and deliberately left: **why** a request that does no I/O waits
four seconds. That is a companion-side question, it needs a companion
release, and this deploy is the dashboard.

Still true regardless, and NOT a bug: a job that does fall back to the server
stays on the NAS. Lane B has not pulled `/Youtube/**` down since 2026-08-16
(owner's policy reversal, R18), so the editor gets `Youtube/<term>/Proxy/`
previews and no original. That is the intended behaviour and the reason CR-29
mattered: requester-first was the only route by which an editor's own
YouTube clips reached their disk, and it had never once run.

### CR-30 — "cancelling: it stops after the video in flight" on a job with nothing in flight
Hit by the owner 2026-08-19 on job 42, parked in `ready_for_review` since
2026-08-18 and blocking every new search and every GET LINKS
(`db.active_job` counts `ready_for_review` as active, one job per editor).
Clicking CANCEL answered with the downloading-phase copy, so it read as a
cancel that had not taken -- the job had in fact gone straight to `cancelled`.

FIXED in repo 2026-08-19: the toast is phase-aware, `cancelled` for anything
not actually downloading. The blocking itself is correct and stays.

### CR-31 — a three second dashboard outage cost an editor 20 of 22 clips
Found 2026-08-19 while answering "are ruskin's YouTube downloads reaching him".
Job 46 was the FIRST job in the fleet ever to run on the requester's machine
(CR-29's probe retry, live since dashboard 0.7.0 that morning). It ran for 58
seconds and downloaded 2 of 22 clips. Then the dashboard container restarted --
exit 0, back up in ~3 s -- and the clip-status POST that landed in the gap
raised `ConnectionRefusedError`. `FleetClient._call` did not catch it, so it
left `_download_all`, left `run()`, and the catch-all logged `job 46 failed`.
The lease lapsed, the server reclaimed the job, and the other 20 clips
downloaded onto the NAS, which lane B has not brought YouTube originals down
from since 2026-08-16. The editor lost them to an outage he never saw.

FIXED in repo 2026-08-19, companion 0.9.4: `_call` retries a raised TRANSPORT
failure for up to `CALL_RETRY_BUDGET_SECONDS` (60 s, budgeted on ELAPSED time
because six attempts that each hit the 15 s HTTP timeout is 90 s of wall clock,
not six seconds) with exponential backoff, aborting at once on the job's stop
predicate. An HTTP STATUS is still never retried: 410 ends the job, and every
other code is an answer the caller branches on.

### CR-32 — a clip the server downloaded could not reach the editor who asked for it
The consequence of the 2026-08-16 policy reversal that nobody had a route
around. Lane B stopped carrying the Youtube tree down on the reasoning that
requester-first downloads put every editor's own clips on their own disk. Every
way that falls back to the server -- no companion, no capability, a lapsed
lease (CR-31), a clip the requester's IP was bot-checked on and the server's
second-chance sweep fetched, or simply losing the race (CR-34) -- leaves the
original on the NAS with nothing to move it. Measured on job 46: 2 mp4s on the
editor's disk, 20 on the NAS, and a `.credits.json` for all 22 (Syncthing
carries the sidecars; the .stignore excludes video).

FIXED in repo 2026-08-19, companion 0.9.4: `POST /ytdl/fetch` on the 8899
loopback pulls ONE original down, through broll_fetch's existing registry
(same two-at-once cap, same rclone tuning, same shutdown kill) with
`PROJECTS_REMOTE_REL` as its third NAS-side folder. `/ytdl/reveal` now answers
`absent: true` when the ledger has a clip this machine does not, and the page
turns that into [ GET IT FROM THE NAS ] with a progress toast.
**Needs the companion shipped: the deployed build 404s on `/ytdl/fetch`.**

### CR-33 — every clip whose format ladder made yt-dlp test a format died instantly
Hit by the owner 2026-08-19 on two GET LINKS jobs in a row:

    failed: [Errno 13] Permission denied: '/tmpf1m0z55x.tmp'

A path that appears nowhere in this repo. yt-dlp resolves its scratch directory
as `sanitize_path(join(paths['home'], paths['temp']), force=windowsfilenames)`,
and with no `paths` at all that is `sanitize_path('', force=True)`, which in
2026.07.04 is `os.path.normpath('') == '.'`. `_check_formats` then opens a probe
file in `.` -- and the container's cwd is `/` (run.sh never chdirs), which uid
3000 cannot write. Both halves were ours: `windowsfilenames: True` is half of
the naming contract with `ytdl_common`, and nothing ever gave the process a
writable working directory. Latent since the feature shipped; it only fires for
clips whose ladder makes yt-dlp test a format, which is why other jobs the same
morning downloaded 42 clips without a murmur.

FIXED in repo 2026-08-19, dashboard 0.7.1: `build_opts` sets
`paths: {"home": outdir}`. `home` and not `temp` -- temp is where `.part` files
and fragments go, and moving those out of the clip's folder would take the
partial-cleanup, dedupe and disown paths with it. `prepare_filename` is
byte-identical with and without it (the outtmpl is absolute, so it wins
`os.path.join`), verified in the live container. The worker also logs
`exc_info` on a clip failure now: `str(exc)` alone made this a bug hunt.

### CR-34 — the server won the race for every small selection, so requester-first never engaged
Third distinct reason after R18's two and CR-29's one, and the first that is
pure scheduling: every guard between the two executors was correct and the
outcome was still wrong. `start_download` writes the pending rows and nudges
the worker in ONE request; the SPA then probes the loopback and the companion
claims. Measured on job 50 (one clip): `/download` returned at T+0.000, the
worker took the row, the claim landed at T+0.161 and the download-manifest
truthfully said 0 clips. The companion logged `job 50 -- 0 clip(s)`, stood
down, and the clip downloaded onto the NAS. Job 46's 22 clips only worked at
all because the worker was 2 clips in when the claim landed and handed back the
other 20.

FIXED in repo 2026-08-19, dashboard 0.7.1: `_phase_download` waits up to
`LOCAL_CLAIM_GRACE_SECONDS` (4 s, `YTDL_LOCAL_CLAIM_GRACE_SECONDS`) for a lease
before taking the first row, and returns if one appears. Ends the instant the
claim lands, so a job with a companion behind it pays nothing; a job without
one pays a few seconds once, against a download of minutes. Skipped entirely
when `LOCAL_DOWNLOAD` is off, because that flag is the rollback switch and has
to mean byte-for-byte the old behaviour.

### CR-35 — DOWNLOAD greyed out for good after the first clip
Reported by the owner 2026-08-19 with 67 clips in the grid: download one, and
the button dies. `start_download` has accepted `done` as well as
`ready_for_review` since YTDL-16 -- pressing DOWNLOAD on a finished job is the
documented retry path, and `mark_pending` re-queues exactly the rows that
failed or were never fetched -- but the SPA's `#download` button tested
`phase !== 'ready_for_review'` and disabled itself. The editor's only route to
a second clip was another whole search: another Claude spend and another twenty
minutes of yt-dlp.

FIXED in repo 2026-08-19, dashboard 0.7.1: the button accepts both phases. The
server's 400 ("nothing new is selected") and 409 ("you already have a job
running") already arrive as toasts, and a permanently grey button is not a
better error message than either.

### CR-36 — GET LINKS never offered the job to the editor's own machine
Found 2026-08-19 chasing "it is still downloading on the server". `dispatchLocal`
was called from `startDownload` -- the review-grid path -- and from nowhere
else, so **every pasted-link job this fleet has ever run downloaded on the
NAS**, for every editor, since the feature shipped. A paste has no review step,
so there was no second place the offer could have been made from. Jobs 48, 49
and 51 (all `kind=urls`) each went server-side with no claim in the log at all.

Since lane B stopped carrying YouTube originals down on 2026-08-16, the editor
who pasted the link was the one person guaranteed not to end up with the clip.

FIXED in repo 2026-08-19, dashboard 0.7.2: `runUrls` dispatches after the
server accepts the job, on the same contract `startDownload` uses -- not
awaited, and a companion that cannot take it changes nothing.

### CR-37 — clearing the executor pin lasted two milliseconds
The one the owner was actually looking at. Job 50, on the live fleet:

    06:10:15.477  POST /jobs/50/download  200      <- pin cleared (YTDL-WEB-7)
    06:10:15.479  job 50: the local download lease held by ruskin expired;
                  the server is taking the job back
    06:10:15.592  POST /jobs/50/claim     410 "this job is pinned to the server"

`start_download` clears `mode_lock` because the pin belonged to the run that
ended. But `download_mode` stayed `local` from that dead run -- a job that
finishes while local keeps the value, and a `done` job is never picked up again
for the worker to reclaim it -- so the nudge this same request sends took
`_phase_download` down the reclaim path for a run that had ended half an hour
earlier, and `reclaim_download` re-pinned the job. Correctly, in its own terms:
reclaim is one-way WITHIN a run. The editor's machine was then refused on every
retry, permanently.

FIXED in repo 2026-08-19, dashboard 0.7.2: `db.clear_mode_lock` clears all four
columns of the last run's executor state (`mode_lock`, `download_mode`,
`claimed_by`, `lease_expires_at`). Safe for the reason clearing the pin was:
`start_download` accepts only `ready_for_review` and `done`, so the previous run
is over and there is no lease to preserve. The reclaim's accounting is not lost
either -- `mark_pending`, which the same request calls next, re-queues exactly
the rows that failed or were never fetched, which is the set the reclaim would
have produced.

### CR-38 — requester-first was invisible, so four separate failures all read as "it doesn't work"
Not a defect of its own: the shape of CR-29, CR-31, CR-34, CR-36 and CR-37 put
together. The page never said which machine it was about to ask, never said
that it had asked, and never said why the answer was no -- §11 kept every
machine-side refusal deliberately quiet, on the reasoning that the editor could
not act on it and the server would do the job anyway. That reasoning died on
2026-08-16, when lane B stopped bringing YouTube originals down: from then on
"the server did it" was not a detail, it was the difference between having the
footage and not having it. The owner, 2026-08-19: "we need a switch for download
locally and we need an error and some feedback for when it doesn't do it."

DONE in repo 2026-08-19, dashboard 0.7.2:
- **the switch** -- an "on this machine" tickbox beside the quality picker,
  remembered per browser, defaulting to ON, and hidden outright when the
  fleet's `local_download` flag is off. Read at dispatch time, not at page
  load. A page served without the element (a cached `index.html`) reads as
  ticked, so a stale asset cannot become a silent fleet-wide opt-out.
- **the feedback** -- every path that ends server-side names its reason once:
  no tray app, a companion too old, a reasoned refusal, a timeout, an
  out-of-scope quality, a refused hand-off. Each says what it means for the
  clip ("YouTube originals only sync upwards, so use the download history to
  fetch a clip onto this machine"), and each is said once per reason so a poll
  cannot turn it into a stream.

### CR-39 — the editor's machine had no PO token, so YouTube 403'd every download it tried
THE root cause of "requester-first doesn't work", under all the others. Found
2026-08-19 by running the companion's own argv on a live editor machine.

yt-dlp's DEFAULT player client hands back media URLs bound to a GVS PO token.
The NAS has a provider for one -- the bgutil sidecar
(`downloader.pot_opts`, `ytdl/web/DEPLOY.md`) -- and an editor's machine has
none. So the server could always fetch the bytes and the requester's machine
could not. Measured on ruskin's box, one clip, one binary, one minute:

    default (android_vr)  ERROR: unable to download video data:
                          HTTP Error 403: Forbidden
    ios                   "requires a GVS PO Token which was not provided ...
                          may yield HTTP Error 403"
    tv                    "The page needs to be reloaded"
    web                   works, but falls to format 18 -- 360p, 6 MB
    web_safari            works, 17.3 MB, full quality, exit 0

...and on `zhOvgxGbXvc`, a clip that HAD downloaded locally 90 minutes
earlier, the default client 403'd after 10.3 MB while web_safari returned the
same 16.2 MB. YouTube tightened enforcement during the day, which is exactly
why this read as "it worked once and then stopped": job 46 landed 2 clips at
13:06 and every clip after it failed, including ones that had worked at 13:06.

The failure was also INVISIBLE. `_fail_clip` reported the 403 to the server and
reset the row without logging, so the companion log went from "job 53 -- 1
clip(s)" straight to the next job. The editor saw the badge flash "downloading
on your machine" and settle back on "the server", with no line anywhere on
their machine saying why -- which is what CR-38's feedback was added for, one
layer up.

FIXED in repo 2026-08-19, companion 0.9.4: `build_argv` sends
`--extractor-args youtube:player_client=web_safari`. ONE client and not a list:
yt-dlp picks the best format across every client named, which is how a
PO-token-bound URL gets chosen again. Overridable per machine with
`ytdl_player_client` in config.toml (empty string = yt-dlp's own default set),
because this is YouTube's to change and the lever must not be a release.
`_fail_clip` logs the failure now.

**Needs the companion shipped.** The argv is baked into the frozen exe; there
is no lever on a running 0.9.3.

## The 2026-08-19 ultrareview of the day's work (CR-40..CR-43)

`/code-review ultra 163f2e0` over the five 08-19 commits (per-machine plans,
release tooling, the ytdl requester-first pass: 83 files, +6.5k). Four
findings, all verified against the code, all fixed the same day -- dashboard
0.7.3, companion 0.9.41. The first two are in the headline feature of
MULTI_MACHINE_PLAN.md §9 (updates without a click) and would have shipped it
half-working; neither has been in the field.

### CR-40 — the `auto_update` site flag was dead on arrival in the companion
`site.normalise()` rebuilds the manifest's `features` from a hardcoded
whitelist, `FEATURE_KEYS = ("youtube_download", "youtube_unblock")`, so the
`auto_update: true` the dashboard published was stripped before
`feature_enabled("auto_update")` ever read it -- and `feature_enabled` fails
closed, so the gate at `_on_upgrade_available` returned every time. A site
with `DASH_SITE_AUTO_UPDATE=1` would have seen zero unattended upgrades and
no log line saying why. Every test of the path monkeypatched
`feature_enabled` directly, which is how a real manifest never went through
the real `normalise()`.

FIXED in repo 2026-08-19, companion 0.9.41: `"auto_update"` is in
`FEATURE_KEYS`, the comment above it now says the tuple IS the whitelist,
and `test_site.py` runs every flag the dashboard publishes through
`normalise()` -> `save_site()` -> `cached_site()` -> `feature_enabled()`.
The admin push (`commands.upgrade` on the report reply) never depended on
the manifest and was unaffected.

### CR-41 — a pushed update parked itself on the first "Can't update while a window is open"
`_apply_pushed_update` set `_pushed_update_applying` on the reporter thread
BEFORE starting the apply thread, and nothing ever cleared it: not the popup
stand-down, not the consolidate stand-down, not a failed download. The
dashboard re-sends the request on every report until the machine reports the
new version -- which it never does -- so every subsequent report hit the
debounce and returned silently. ruskin's PC, whose out-of-tree popup takes
the lock three seconds after launch (CR-27), would have got ONE toast and
then ignored the push until the tray was restarted: on exactly the machine
§9 names as the reason unattended updates exist.

FIXED in repo 2026-08-19, companion 0.9.41: `apply_upgrade` returns why it
did not swap (`"popup" | "consolidate" | "failed" | "no-offer"`, `""` on
success), the push runs through `_run_pushed_update`, which releases the
latch when the attempt comes back without swapping and holds the next try
off (`PUSHED_UPDATE_RETRY_SECONDS` = 90 s after a stand-down, 600 s after a
failed download). Retries pass `quiet_refusals=True` so the editor is told
once per request, not every minute. The debounce key is the REQUEST
(`version@requested_at`), so an admin who cancels and pushes again gets a
fresh attempt at once.

### CR-42 — a rename onto another live computer's name destroyed that computer's plan
`adopt_renamed_machine` DELETEd whatever sat at the new hostname before
moving the old rows across, and `upsert_machine`'s COALESCE then wrote the
incoming `machine_id` / Syncthing device over the existing row's. An editor
who renamed PC B to decommissioned PC A's name, or restored an image
carrying A's `machine.json` onto a box called B, silently lost B's plan and
sticky root -- with a friendly "moving its sync plan across" in the log.
MULTI_MACHINE_PLAN.md §6 called a same-person hostname collision "solved by
construction"; it is not, because every table but the registry is keyed on
the hostname (the deliberate WP1 choice).

FIXED in repo 2026-08-19, dashboard 0.7.3: `adopt_renamed_machine` returns
False and writes nothing when the new name is already a registered computer
of that editor; `_register_machine` logs a WARNING naming both machines and
records the report under the name it used. Both plans stay exactly where
they were -- under-sharing is the safe direction; an admin copies or clears
one by hand ("give this computer another one's plan"). `machine_by_machine_id`
orders by `last_seen DESC` so the row that just reported wins the id lookup
and the rename branch does not re-fire every 30 s. §6 now says so.

### CR-43 — `machine_state.mode`'s COALESCE was a no-op (the comment described a guard the code lacked)
`api.py` defaulted a missing `mode` to `"editor"` BEFORE the upsert, so
`excluded.mode` was never NULL and the COALESCE that the comment presented
as CR-28's defence against a mode-less report never engaged: such a report
would have re-labelled the base rig an editor machine. No live impact (every
0.4.x+ companion sends `mode`), but a misleading comment at the boundary
between two pieces of code that must agree invites the refactor that
reintroduces CR-28.

FIXED in repo 2026-08-19, dashboard 0.7.3: the machine row receives `None`
when the report omitted `mode` (the COALESCE is real now); the
`editor_media_project` write keeps the `"editor"` default because its column
is NOT NULL. `test_presence.py` pins a mode-less report keeping a stored
`base`.

## The lane B breaker's two blind spots (CR-44, CR-45, 2026-08-20)

Both found by working ruskin's PC on 2026-08-19, where proxy download sat
stopped for a day and neither the trip nor the recovery was the breaker's
finest hour. Nothing was ever lost: the trip was correct in the narrow sense
that the server no longer had the files at the path lane B was syncing, and
`.ccsync-trash` held every byte throughout. The trip was still WRONG about
what had happened, and the fix for that could not be delivered without the
second change.

### CR-44 — a folder MOVED on the NAS reads as a folder emptied

Lane B is `rclone sync` down, so it learns exactly one thing about a local
file: whether the remote has it at that path. An editor who drags
`Interviewees/Creator_Interviews` into `B-roll/Creator Intel Reel Shooting
CCT` deletes nothing, but every proxy underneath leaves the path lane B is
watching in one pass, and the breaker read that as the tree being emptied.

Measured on ruskin/DESKTOP-LQQ41TC, 2026-08-19: 148 originals and 214
proxies moved between the 17:00 and 18:00 ZFS snapshots (Season 1's own file
count went 3519 -> 3518, which is how the move was told from a deletion);
lane B trashed 100 of his local copies at 17:49, tripped, and stopped. The
reorganisation was routine and every byte was on the server the whole time.

FIXED in repo 2026-08-20, companion 0.9.43: `LaneBBreaker.note_pass` takes a
`relocation_probe`, and `RcloneLane._count_relocations` answers it by listing
the scope recursively (`rclone lsf -R --format sp`) and matching each trashed
file on BASENAME + EXACT SIZE. A trashed file's own remote path is gone by
construction -- rclone moved it out precisely because the remote lacks it
there -- so any match is at another path, which is what "moved" means.
Relocations come off both the per-pass and the cumulative counters.

Three properties worth keeping if this is ever touched:

* the probe is LAZY. It costs a recursive listing, so it runs only on a pass
  that is about to trip, never on the ~99% that are nowhere near a limit.
* every failure falls back to 0, i.e. "treat them all as deletions". A probe
  that throws, or a listing that fails, must leave the breaker exactly as
  strict as it was without one, and the count is clamped to the pass's own
  deletions so a bug there cannot talk it out of a real trip.
* a failed listing (None) and an empty remote ({}) are different answers. The
  empty remote is the case the breaker exists for and must stay free to trip.

A re-encode is still a deletion, on purpose: when the base rig superseded the
`Nuclear_Restart_Montage` `.mp4` proxies with `.mov` ones the same afternoon,
the old bytes really did go, and the size match refuses to call that a move.

### CR-45 — only the editor's own tray could clear it

The breaker is deliberately an operator decision: resuming asserts the server
is in a state worth syncing from, which is the exact judgement the software
could not make. What it was not, until now, is a decision the operator could
REACH. There was no dashboard action, no admin API, and the companion's
command channel carried only `upgrade` and `halt`; the 8899 loopback has no
resume route. The state is read once in `CompanionApp.__init__`, so editing
`lane_b_breaker.json` under a running companion does nothing and is then
overwritten.

So a remote machine stayed parked until its owner was next at the keyboard.
ruskin's PC spent 2026-08-19 that way, and the admin who had already checked
the NAS and knew the trip was benign could do nothing but send a message.

FIXED in repo 2026-08-20, dashboard 0.7.4 + companion 0.9.43: schema v26 adds
`machines.lane_b_resume_requested_at/_by`, delivered in the same `commands`
block the fleet halt and the pushed update ride. `[ RESUME ]` sits beside the
red chip on the fleet page for admins, with `POST|DELETE
/api/v1/admin/machines/{editor}/{machine}/resume-lane-b` behind it.

Nothing about the decision moved. The companion does exactly what the tray
click does, and only while its breaker is actually tripped -- so it is
idempotent by construction rather than by remembering which request it saw.
The request is CLEARED when the machine reports its breaker no longer
tripped, which is what stops a standing one from silently clearing a later,
unrelated trip; a report carrying no guard section at all keeps it, or a
companion too old to send one would look like "not tripped" forever and the
admin's click would never be delivered.

**Deploy the dashboard before the companions**, as ever -- but note the
inverse gap here: the dashboard half is inert until a companion that knows
`resume_lane_b` is on the machine, so this does NOT help any machine still on
0.9.42 or earlier. Ruskin's current trip needs the tray click regardless.

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

### R18 — requester-first downloads never engaged; the fleet ran the server path for two days without anyone noticing — FIXED in repo 2026-08-16 (companion 0.7.9 + dashboard env), unshipped
Read live on an editor's machine the morning after they took 0.7.8 (SSH,
`companion.log`, `127.0.0.1:8899`, the dashboard's fleet + ytdl APIs), while
chasing five symptoms they reported at once. What each turned out to be:

- **"Syncing 48 GB of Creator Profiles he already has"** — lane B's first
  pass after 0.7.4 → 0.7.8: 0.7.6's `+ /Youtube/**` pulling every YouTube
  original in the project (58 GB) down to him. Working as designed, and the
  design was wrong — see the fix below.
- **"Not showing on the dashboard"** — his reporter timed out 10:43–11:16
  (WinError 10060, around the upgrade/restart); it has reported cleanly since
  11:20. Transient.
- **"Videos land in F: not P:"** — on his machine P: *is* `\\localhost\CCSync_P`
  = `F:\Creators_Club`; the reveal opens the local-root spelling by design
  (a Mac has no drive letters). Not a defect.
- **"Weren't downloads supposed to happen locally?"** — they never once did.
  Every job `download_mode: server`, `claimed_by: null`, for **two
  independent reasons**: (a) the NAS dashboard had no `YTDL_LOCAL_DOWNLOAD=1`
  (`/ytdl/api/health` → `local_download: false`; the ship checklist named the
  step, `install_dashboard_app.py` never performed it), so the SPA never
  probed the companion; (b) his machine has **no ffmpeg** —
  `/ytdl/capabilities` → `ok:false, "ffmpeg is not installed"` (COMP-BROLL-5
  refusing correctly) — and nothing had ever shipped one to an editor.
  Invisible because the server path is the designed fallback and kept working.
- **Age-restricted clip fails ("Sign in to confirm your age")** — failed
  *server-side* (job 34). The NAS `cookies.txt` is present (`cookies: true`)
  but carries only the `__Secure-3P*` half of a session (no `SID`/`HSID`/
  `SSID`/`APISID`/`SAPISID`/`LOGIN_INFO`), and yt-dlp rewrites it on every
  run (mtime = job time). Whatever account it was exported from either is not
  age-verified or the export was partial. **FIXED both ways** (fix 7 + the
  operator note below): the NAS cookies.txt was re-exported and reinstalled,
  and the LOCAL executor now passes `--cookies` too (it used to pass none),
  so an editor who runs "Sign in to YouTube" downloads age-gated clips on
  their own machine — no server round trip.
- **"Open in Explorer opens the default folder"** — real, and every clip:
  `Popen(list)` quotes any argument containing a space, every path in this
  tree has one, so Explorer got `"/select,F:\...\Season 1\clip.mp4"` — a
  token starting with a quote, which it does not recognise as a switch and
  silently answers with Documents. Endpoint said ok:true, a window opened.
- **Music "+ Resolve" dead-ends "file not found — is the share mounted?"** —
  the library is not a synced folder any more than the b-roll archive is, and
  `music_server.build_send_response` had no on-demand fetch (b-roll's
  `/insert` got one 2026-08-11).
- **"Open dashboard" not opening** — `webbrowser.open()` returns False with
  no log line, so nothing distinguished "a tab opened and timed out" (the
  dashboard WAS unreachable from his box 10:43–11:16) from "nothing
  launched". His log's three `TrackPopupMenuEx returned 0, GetLastError=0`
  are `TPM_RETURNCMD` dismissals, not failures.
- His three local Syncthing folders carry 23 of 29 ignore lines and the
  sequencer's startup verify latched them "paused until a re-assert" — but
  they were never paused (0.7.4 left them running), so the claim in the log
  is wrong while the risk is nil (the six missing lines are the `.part`/
  `.ytdl` set the NAS now filters at source; the lane C turn re-asserts).
  Left as-is; verify it self-healed after his lane B pass.

FIXED, all in repo:
1. **`sidecar_tools.py`** (companion 0.7.9): a *pinned* static ffmpeg +
   ffprobe (eugeneware/ffmpeg-static `b6.1.1`) AND a deno (denoland/deno
   `v2.9.5`), each sha256 hardcoded per asset and verified against a real
   download, installed into the same tools dir as yt-dlp on the yt-dlp
   manager's daily thread, under the same opt-out. `ffmpeg_tools
   ._resolve_binary`/`ffmpeg_available` fall back to the managed ffmpeg
   behind PATH for the bare default `ffmpeg_path` only; the executor hands
   yt-dlp the deno by path. An editor's own ffmpeg/deno, or an explicit
   path, is never touched. capabilities() turns ok the moment ffmpeg lands;
   no restart, no config edit.
2. **`YTDL_LOCAL_DOWNLOAD=1`** set by `install_dashboard_app.py` and
   `dashboard/deploy/compose.yaml` (pinned equal by test_safety), so a
   redeploy can never drop it again.
3. **Lane B no longer pulls `/Youtube/**`** (owner's call: originals go UP
   only, other editors' clips are bandwidth). Editor-local originals the NAS
   lacks are now excluded rather than swept to trash (item 22's Youtube case
   is gone). `Youtube/<term>/Proxy/` still comes down. The reveal's not-here
   message says where the clip is instead of "has it synced here yet?".
4. **Explorer reveal**: `ytdl_server.windows_command_line` builds
   `explorer /select,"<path>"` by hand and `spawn()` hands Popen ONE string
   on win32 (verbatim to CreateProcess, no shell). Verified live on the base
   rig by reading the opened window's `Shell.Application` LocationURL, not
   by "a window appeared". A path containing `"` is refused (Windows names
   cannot), never escaped. Music's reveal shares the function.
5. **Music on-demand fetch**: `broll_fetch` takes a `remote_rel`
   (`Assets/Music`), `music_server.build_send_response` pulls the missing
   track down and answers `state:"downloading"` with progress; the music UI
   re-POSTs every 1.5 s until the send goes through. Same gate as b-roll
   (derived mount only, never a base rig, never another share).
6. `_open_dashboard` logs the attempt, logs when no browser launched, and
   tells the editor the URL in a toast.
7. **Signed-in LOCAL downloads (COMP-YTDL)**: measured that anonymous
   downloads reach 1080p with no JS runtime but a `--cookies` file makes
   every format vanish without one — hence the deno sidecar (fix 1). The
   executor sends `--cookies` from `ytdl_cookies.resolve()`: the
   `ytdl_cookies_file` config key, else the tray-written
   `~/.ccsync/youtube-cookies.txt`, else nothing. The tray's **"Sign in to
   YouTube (for downloads)…"** validates a browser-exported cookies.txt
   (Netscape header + real youtube.com session cookies; the `__Secure-3P*`-
   only logged-out shape is rejected — same shape as the NAS's own broken
   file) and saves it 0600. Proven end-to-end: the real `build_argv`'s
   command line passes the age gate (`Clay | 480p | age_limit=18`) with a
   managed deno + a signed-in cookies.txt on this residential IP, no
   PO-token provider. Deliberately a FILE not `--cookies-from-browser`
   (Chrome app-bound encryption; reading a live profile rotates the session).

Also this session, OPERATOR side (done, not code): the NAS `cookies.txt`
was re-exported from a signed-in age-verified session and installed
(uid 3000, 0600); `ggfhWx8h5Tg` — the clip that started this — now extracts
in-container. The old partial file is `cookies.txt.bak-20260816`.

Ship: `tools\ship.cmd` (dashboard deploy carries the flag; companion 0.7.9
publishes the sidecar + lane B + reveal + music + YouTube sign-in). An
editor's box gets ffmpeg+deno ~30 s after their tray takes 0.7.9; their next
YouTube job downloads locally, and age-gated clips work once they run "Sign
in to YouTube" with their own cookies.txt. **Still open after the ship:** Mac builds.

### R17 — ten clips whose proxies Resolve refuses, and R10 does not explain nine of them
Found 2026-08-15 reading the base rig's `companion.log` after the 0.7.8 ship:
**1,357** `proxy relink: Resolve refused …` WARNINGs between 2026-08-11 13:10
and 2026-08-15 07:05, over **10 distinct clips**, re-offered every ~120 s for
as long as Resolve was open.

**The retry loop itself is already closed** — COMP-MEDIA-5 (0.7.8) remembers
each refusal against the proxy's `(mtime, size)`, demotes the per-clip line to
DEBUG and prints one summary WARNING per pass. Those 1,357 lines are 0.7.7
behaviour and will not recur. What is still open is *why these ten are
refused*, because R10's answer does not cover nine of them.

All ten proxies come from the same batch: the one-off Energy Transition driver
run of 2026-08-11 13:10–14:04 (the archive one re-touched by the R10 sweep at
08-12 01:02). Measured with ffprobe, 2026-08-15:

- **Nine of ten** (the FF5 Energy Transition YouTube clips) have **no embedded
  timecode on either side**, identical `r_frame_rate`, identical `nb_frames`,
  matching duration, same `pix_fmt`, same stream layout — R10's "timecode-less
  source, nothing to mismatch" class, which the sweep skipped on purpose
  (2,152 of them). A **control** in the same tree is decisive: `…/typhoon
  powercuts/…[SZqTalujBTc].mp4` has the identical shape (640x480, 30000/1001,
  no timecode either side) and **links fine** — its proxy was written 08-14 by
  the ordinary `proxy_gen`. Nor is it the CJK names: the same log holds 54
  successful relinks, CJK ones among them. The only variable left standing is
  which encoder run produced the file.
- **One of ten** (`20250323_fx3_traffic_yu_ba_ba_1057.mp4`, ff3 archive) is a
  real timecode mismatch: source `03:40:27:12` (colon), preview
  `03:40:27;12` (semicolon) — the DF normalization R10's second half applies
  at 59.94. This is the one case where that rule can be wrong: it cannot tell
  "Sony printed a colon form for drop-frame material" (the case measured live
  on 08-12) from a genuinely non-drop-frame recording, and at 3h40m the two
  readings are thousands of frames apart. The sweep's "799 fixed, 0 failed"
  counted successful remuxes, not Resolve acceptances.

Two cheap experiments, both needing Resolve open on the rig, neither run yet:
re-encode one of the nine with 0.7.8's `proxy_gen` and re-link (if it
attaches, the 08-11 driver batch is the suspect and the repair is a re-encode
sweep over those 438); and remux the ff3 preview with the **colon** form and
re-link (if it attaches, `dropframe_normalized` needs a way to tell real NDF
material from Sony's colon-printed DF, and the 799 swept previews need
re-checking).

Cost while open: those ten clips edit without a proxy. Nothing else.

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
A remote editor's Windows machine was left with **no
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

### R15 — the empty Youtube folder: ytdl delivered json and corpses, never videos — FOUR FIXES, SHIPPED 2026-08-15 in 0.7.8
Investigated live on an editor's machine 2026-08-13 23:2x → 2026-08-14 (full
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
   `*.ytdl`: 27 orphans, 1.6 GB, three days deep on that editor's disk (cleaned).
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

All four shipped 2026-08-15: the dashboard deploy is `ship.cmd` step 1 and
the companion publish is step 2, so fix 3's two halves landed together (it
was INERT until both — the deployed collector strips the new ignore lines
every provision cycle until it is redeployed).

The NAS side needed no hand-work at all, and the "re-run
`setup_syncthing_folder.py` per existing project" this entry used to list as
owed was **never necessary**: the same exact-equality repair that would have
stripped a server-only fix pushes the dashboard's list instead, on every
existing folder, every provision cycle (`collector._ensure_ignores`).
Verified read-only 2026-08-16 against the live NAS Syncthing config API — 7
project folders, **0 missing** `(?i)**/*.part`, `(?i)**/*.part-Frag*` or
`(?i)**/*.ytdl`. Re-running the server script by hand is now only for a
folder the collector cannot see (no marker, or a project it refuses to
provision). **Still owed:** that editor (plus any other stale tray) accepting the
upgrade — the editor half lives in the companion's own `STIGNORE_LINES`,
re-asserted at startup and per turn, so it reaches a machine only when its
companion does.

### R14 — the BPG hand-off launched a generator that watched nothing, then never started it — FIXED, SHIPPED 2026-08-15 in 0.7.8
`bpg.py` opened the Blackmagic Proxy Generator whenever BRAW/R3D/CRM had no
proxy and deliberately touched neither its watch list ("that config is
yours") nor its window. Both halves were load-bearing, and on the base rig
both were empty:

- `watchFolderList=@Invalid()` — Qt's spelling of "no folders". BPG rewrites
  that file from memory on every exit, so a folder removed once is gone for
  good, and a watcher with no folders is a silent no-op. The rig launched it
  at 14:09, 15:26 and 18:13 on 2026-08-13 alone, against 6 BRAW clips that
  had had no proxy since 2026-05-20 (`…/Creator Profiles/Season 1/B-roll/
  Editor Added/<editor>/`), and the gap never moved.
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
  FSEvents stream on a Mac editor's external disk still needs hands on the
  machine.
- **Bench Syncthing 1.x (was item 1 residual)** — v1 argv test-pinned but
  never live-verified.
- **Mac builds owed — now carrying the whole 2026-08-11 fix pass.** Until
  `release_macos.sh --publish --make-current` and
  `build_onboard_macos.sh --publish --make-current` run on a Mac, Mac
  editors have none of today's fixes (including both UI criticals, which are
  worst on darwin), and `/music/send` + `/music/status` still 404 on every
  deployed companion until the fleet republish.
- **NAS hygiene (was item 7 incidental)** — `owen_laptop` in the `editors`
  group still looks like a machine-shaped account; rename if it is one.
