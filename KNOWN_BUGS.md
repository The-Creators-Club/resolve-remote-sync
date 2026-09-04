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
unverified against a live 25.10 middleware. **Since 2026-08-29 the dashboard
says this out loud** (SYS-14, wave 5): Settings -> PROTECTION reads
`pool.snapshottask` and renders the apps dataset `[ MISSING ]` when nothing
covers it, `[ CANNOT VERIFY ]` when the container has not been told its name,
and the same line goes into the notices and every Monday report. The operator
work below is unchanged; what has changed is that not doing it is no longer
invisible.

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

### CR-95 — CR-28 follow-up (2026-08-30): a wired column's stale tick could not be cleared — FIXED in repo 2026-08-30 as dashboard 0.7.26, NOT YET SHIPPED
Owner, 2026-08-30: *"as a wired user I cannot assign any project, for some
reason animals is ticked but I cannot untick it. They're all greyed out."*

dash-admin-8 (CR-28 above) made "wired" a per-MACHINE predicate so a mixed
account (one wired desktop, one remote laptop -- the owner's own shape) could
still tick projects for its remote half. `api.api_tick`'s per-machine refusal
already said so explicitly: *"UNTICKING stays allowed (below), so an existing
one can be removed."* But `admin_assignments.html` never read that far --
every checkbox in a wired column rendered `disabled`, ticked or not, so a
stale tick (one written before the machine went wired, or carried over by a
migration) sat there greyed out with nothing on the page able to send the
DELETE that was always allowed.

Fixed in the template: a wired cell is `disabled` only when it is NOT already
ticked (a new tick is still refused, 409, and the title says why); a ticked
wired cell stays enabled, with a title explaining that unticking is what
clears it. `assignments.js` re-locks the box after a successful untick (the
server would refuse a re-tick anyway) rather than leaving it clickable until
the next reload. No server-side change -- `PUT`/`DELETE
/api/v1/selection/{editor}/{slug}?machine=` already had the right rule; only
the grid was hiding the DELETE half of it. Tests:
`dashboard/tests/test_admin_assignments.py`
(`test_wired_column_ticked_stays_enabled_and_untick_succeeds`,
`test_wired_column_unticked_stays_disabled`,
`test_a_remote_column_of_the_same_mixed_account_is_unaffected`).

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

## The 2026-08-21 full-repo hunt and fix pass (CR-46..CR-67)

The fifth fleet hunt (`docs/bug-hunt-2026-08-21.md`: 14 module hunters, each
batch adversarially verified, plus 6 macro design reviewers looking at the
approach rather than the lines) confirmed **78 findings** and **53 design
issues** against a clean tree at `f27c181` (companion 0.9.43, dashboard
0.7.4). Eleven fixers took disjoint file territories the same day.

Entries below group the findings by THEME, because that is how they were
fixed and how they will have to be shipped: one entry per mechanism, naming
every finding id it covers. All of it is **in repo, unshipped**. After wave
2 the orchestrator bumped **companion 0.9.44, dashboard 0.7.5, installer
1.0.36** (remember 0.9.9 is followed by 0.10.0, never 1.0), and the ship that
carries this pass must **deploy the dashboard before the companions** as
ever. CR-66 is the list of what was deliberately NOT done and why; CR-67
is the residue of half-fixes whose other half sat in a file nobody held.

Suites on the merged tree after wave 2 and the bumps (`tools/run_all_tests.ps1`,
orchestrator): **13 of 13 green**. companion 4425 passed / 2 skipped (4381 / 46
under run_all_tests, whose launcher skips the live-Resolve and macOS cases); dashboard 1570 / 5 skipped; server 572 / 2
skipped; onboarding 321; bench 175; broll/web 512; broll/indexer 788;
music/web 478; music/indexer 46; ytdl/web 657; tools 185; both installer table
suites; `check_licenses.py` OK. Three tests were reconciled on the merged
tree, none a product defect (see the hunt document's RESOLUTION block).

### CR-46 - [ RESUME ] did not resume, and one click could keep trashing (comp-lanes-ab-1, comp-lanes-ab-2) - FIXED in repo 2026-08-21, unshipped
CR-45 shipped the button; this pass found that neither end of it was safe.
`LaneBBreaker.resume()` cleared the latch and the deletion counters but left
`self._remote_counts`, and `check_remote()` writes a new baseline only on the
NON-trip path, so a trigger-1 trip ("shrank from 10 to 3", "listed EMPTY")
re-tripped on the IDENTICAL listing, for ever, with the identical sentence.
Reproduced. The operator's only exit was deleting `lane_b_breaker.json` with
the companion stopped, which is exactly what `resume()`'s own docstring said
the button existed to avoid.

Underneath it, the dashboard's request was a STANDING order, cleared only by
a report showing the breaker clear, while the companion posts no report on
resume and the reporter's next tick was chosen 60 s before the reply. A pass
that re-trips inside that window is resumed again on the next reply, and
again: up to `--max-delete 100` proxies into `.ccsync-trash` per cycle from
ONE admin click. That is the unbounded sequence the breaker was built to
stop, reinstated through its own recovery path.

FIXED on both sides. Companion (`sync/lane_guard.py`, `sync/rclone_lane.py`,
`app.py`): `resume()` drops the remembered remote listing with the latch, so
the next listing re-seeds the baseline (the operator has just asserted the
server is in the state it should be synced from); it takes an optional
`request_id`, records it in `lane_b_breaker.json` as `applied_resume_request`
BEFORE clearing the latch (a crash in between can lose a request, never
repeat one), and returns False for an id already applied even when the
breaker is not currently tripped, so an old standing request cannot clear a
LATER trip. `app.py` passes the dashboard command's `requested_at` as that
id, probes `resume_after_trip`'s signature with `inspect` rather than
catching TypeError, and posts one LIGHT report on its own thread immediately
after any resume so the dashboard learns at once. Dashboard (`api.py`,
`db.py`): the request is cleared when the reply that carries it goes out, not
when a later report says clear; the command still carries `requested_at` for
the companion's dedupe; and `POST .../resume-lane-b` now 409s unless that
machine's last report shows the breaker tripped, so a request can no longer
be pre-armed against a trip nobody has reviewed (`db.machine_breaker_tripped`
returns None for "no guard on record", which is not False).

The button is one-shot now. An admin whose reply is lost clicks again; a
second trip needs a second click, by design.

### CR-47 - three things lane B called a deletion that were not one (comp-lanes-ab-3, comp-lanes-ab-4, comp-lanes-ab-5) - FIXED in repo 2026-08-21, unshipped
CR-44 taught the breaker that a MOVE is not a deletion. Three more shapes
were still being counted as one.

* **A proxy rewritten on the NAS inside the `--min-age 120s` window.** rclone
  applies age filters per side, so a NAS file rewritten seconds ago is
  excluded from the SOURCE listing while the editor's older local copy is
  still on the DESTINATION side: `sync` moves it into `--backup-dir` and does
  not replace it. Verified against the bundled rclone 1.74.4. A bulk
  re-render at the same names trips the breaker on files that never left the
  server, and CR-44's basename+size probe cannot rescue it, because a
  re-encode changes the size.
* **Every trashed file counted twice.** A `--backup-dir` move writes two JSON
  records, `Moved (server-side)` then `Moved into backup dir`, and
  `RcloneRunTally` read the first as a completed download, so the dashboard's
  transfer history showed each trashed proxy as a file that had just arrived.
* **Relocations were discounted only on a pass that was about to trip**, so a
  reorganisation already judged benign kept feeding the cumulative "slow
  leak" counter until a handful of real deletions later tripped it and blamed
  the move.

FIXED in `sync/rclone_lane.py` and `sync/lane_guard.py`:
`_trashed_this_pass` returns each file's path RELATIVE to the backup dir
(which mirrors the destination root), `list_remote_files` fills an optional
`paths_out` set from the same walk, and `_count_relocations` treats a trashed
file as not-deleted when the remote holds that same relative path at ANY
size, falling back to CR-44's basename+size rule. `feed_record` returns early
on `Moved (server-side)`, so the twin is no longer a completion. And
`note_pass` runs the probe whenever a pass trashed at least half the ABSOLUTE
per-pass cap (25 at the default), not only when it would trip, so moves come
off the cumulative counter as they happen. That threshold deliberately
ignores the fraction-narrowed limit: on a 12-proxy project it would otherwise
spend a recursive listing on a two-file cleanup, and CR-44's laziness for the
~99% case is the property worth keeping.

Residue, reported rather than redesigned: the min-age proxy still disappears
from the editor's folder for one rotation and is re-downloaded next pass.
There is no filter expression that excludes a young file from the source AND
protects its old destination twin without giving up the truncated-download
guard `LANE_B_MIN_AGE_SECONDS` exists for. `sync-safety-7` (adopt
`--track-renames` so a NAS-side move becomes a local rename instead of a
trash-and-re-download) is DEFERRED: it is an empirical change against a
bundled rclone, and a wrong answer costs deletions on editor machines. CR-66.

### CR-48 - the safety latches: torn writes, a probe that never ran, and a halt that missed the asset libraries (sync-safety-8, sync-safety-5, sync-safety-2, sync-safety-4, sync-safety-6) - FIXED in repo 2026-08-21 (the halt's app.py half landed in wave 2), unshipped
Four defects in the latches themselves, plus the one deletion surface that
has no latch at all.

* **Non-atomic state files.** `lane_guard._write_json` wrote in place, and the
  old comment argued that a torn write degrades to "not tripped". It does
  not: the same file carries `remote_counts`, so a torn write also removes
  trigger 1's only baseline, and the same helper writes `sync_halt.json`,
  where a torn write releases a fleet halt on one machine. FIXED:
  `<path>.tmp` + `os.replace()`, tmp removed on failure. Never make a safety
  latch in-memory-only, and never write one non-atomically.
* **The remote_root marker probe never ran in managed mode**, though
  SYNC_SAFETY.md credits it with catching a wrong `remote_root`. FIXED:
  `RcloneLane.check_remote_root()` lists `remote_root` itself once per
  process (one `lsf` through the existing injected lister) and hands it to
  `breaker.check_remote('')`, where the marker-dir rule lives; the sequencer
  calls it once per pass before `_run_pass`, only when lane B is enabled,
  fault-isolated. A failed listing is never a trip.
* **The halt did not cover the shared asset libraries** (LUTs, B-roll
  archive, music), though the doc and its test say "every lane C folder", and
  the once-per-pass shared-folder reconcile would release a folder the halt
  had just paused. **Halt release** then unpaused every selected folder
  directly, bypassing the sequencer's "the `.stignore` never landed, stay
  paused" latch. FIXED: `SharedFolderManager` gained `folder_ids()` and an
  optional `halted` predicate and refuses to release a paused folder while a
  halt is active (a halt check that throws also leaves it paused);
  `Sequencer` gained `halt_folder_ids()` (selection slugs plus the shared
  folder ids, deliberately NOT folded into `expected_folder_slugs`, which is
  lane C's "am I behind" input) and `release_for_halt()`, which releases
  through `_unpause_all`'s existing ignores-confirmed filter. `app.py` now
  calls all three (wave 2, 2026-08-21): the Sequencer is built with
  `halted=lambda: self.halt.active` (constructed after `self.halt`, so the
  closure has something to read on the first pass), `_pause_lane_c_folders`
  takes its list from `sequencer.halt_folder_ids()` when that exists, and a
  new `_release_lane_c_folders()` routes BOTH release paths, the tray/admin
  `release_halt` and `_apply_fleet_halt`'s dashboard release, through
  `release_for_halt()`. A `release_for_halt()` that throws is logged and
  leaves lane C paused, because staying paused is the safe side; the direct
  unpause survives only as the no-sequencer legacy fallback.
* **The unguarded surface: a human deleting on the NAS.** Documented rather
  than fixed, in a new `docs/SYNC_SAFETY.md` section 7. Lane B mirrors up to
  50 proxies per pass into a 14-day trash before the breaker trips, lane C
  keeps `.stversions`, video originals have no version at all, the actual
  latch is a NAS snapshot, and CR-10 still says `setup_snapshots.py --apply`
  has never been run on either NAS. Nothing in the product reports a missing
  schedule. The `maxAge` disagreement is written down with its three call
  sites (companion 2592000 = 30 d against server and dashboard 31536000 =
  365 d, ledger R5); reconciling it is the companion's move to make, since
  lowering the server's would REDUCE protection, and R5 marks it as wanting
  an owner decision. A fleet-page banner for a MISSING snapshot task was
  attempted in wave 2 and declined as out of reach: the TrueNAS listing
  exists and the Setup wizard already consults it, but raising the banner
  needs the fleet template plus a cached background poll, and `health.py` is
  deliberately I/O-free so that a NAS timeout never sits in front of the
  container healthcheck. CR-67.

### CR-49 - a tick belongs to a computer, and now it does on the wire too (comp-lane-c-2, sync-safety-3, data-model-3, dash-core-1, dash-admin-8, data-model-1) - FIXED in repo 2026-08-21, unshipped
The per-machine plan work (CR-27, CR-28, dashboard 0.7.0) left three holes
where the ROW is per machine but the ACTION was not.

* **"Remove `<project>` from this machine" removed it from every machine the
  editor owns.** `SelectionClient.untick` issued a person-wide DELETE while
  the tray label said otherwise; on a two-machine editor that silently
  stopped lane A UPLOADS from the other computer. FIXED
  (`companion/selection.py`): the DELETE names this hostname, and the
  post-delete view (machine-scoped) is read back; only if the slug is still
  listed, which means this machine rides the unassigned bucket that a
  machine-scoped DELETE cannot touch, is the person-wide DELETE issued and
  logged. A dashboard too old to understand `?machine=` behaves exactly as
  today.
* **A machine's FIRST own row eclipsed everything it was inheriting.**
  `selections` resolves the `machine = ''` bucket only for machines with no
  plan, so the first tick on a bucket machine silently dropped every
  inherited project and the enforce cycle unshared them. Reproduced on a
  scratch DB. FIXED (`dashboard/db.py`): new `materialise_bucket(conn,
  editor, machine)` copies the bucket's rows onto a machine that is still
  inheriting them, keeping position and provenance; `add_selection` calls it
  before writing the first own row, and `remove_selection(machine=M)` calls
  it when the slug being unticked is inherited, so an inherited untick
  deletes a real row and answers `changed=true`. The bucket itself stays, for
  the person's other computers and their next machine. `copy_machine_plan`
  now INSERTs directly, because after its DELETE the target looks like a
  machine writing its first own row and materialising there would add the
  bucket's projects on top of the copied plan.
* **A wired machine could still be handed a tick.** CR-28's guards are per
  PERSON (`base_only_editors`), so an editor who owns BOTH a wired and a
  remote machine got a selection row written onto the wired one and the
  permanent [ GETTING READY ] chip came back. FIXED (`db.py`, `api.py`,
  `assignments.py`): `db.base_machines(conn)` from `machine_modes` is the
  predicate; `add_selection_for_person` skips a person's wired machines,
  `api_tick` 409s a `?machine=` naming one, copy-plan 409s a wired target,
  and both queue blocks test `(editor, machine)`. `base_only_editors` stays
  as the person-level rollup for rows whose machine cannot be resolved.
  `_assignments_view` publishes `base_machine_cells` so the grid can grey the
  COLUMN instead of the account; **`ui.py` and `admin_assignments.html` do
  not use it yet** (CR-67), which is cosmetic only, since every write
  endpoint refuses.

### CR-50 - who a Syncthing device belongs to, and who may start Syncthing (comp-lane-c-1, dash-admin-6, comp-lane-c-3, comp-lane-c-4, comp-lane-c-5, data-model-4, data-model-5) - FIXED in repo 2026-08-21, unshipped
The registry (`machines`) and Syncthing's own device labels are two
authorities for one fact, and the code added through one and removed through
the other.

* **The enforce cycle shared with devices the server has not approved.** A
  machine's reported device id went into the folder's device list whether or
  not the server's Syncthing had that device, so the PUT never converged: a
  re-PUT and a config.xml rewrite every 60 s, and a `+[id]` log line for a
  device Syncthing silently discards. FIXED (`collector.py`): a reported id
  is added only when it is in that pass's device list, with one warning per
  device naming the admin action (approve the pending device). No PUT is
  issued for a folder whose only change was the unapprovable id.
* **Removals went through the wrong authority.** `_run_enforce`'s "keep an
  unmapped device exactly as it is" rule now excludes devices the REGISTRY
  maps to a machine, so the unshare half of a hostname-labelled machine's
  plan is alive again; the lane C queue's join and the GETTING READY
  completion probe both resolve the owner as
  `COALESCE(machines.editor_username, devices.editor_username)`, so a device
  approved in the Syncthing GUI under its hostname no longer has its whole
  backlog dropped.
* **One device id could sit on two registry rows** while three joins assumed
  it sat on one. FIXED: `db.release_device_id_elsewhere` NULLs the id on
  every other row still claiming it when a report registers it, logging the
  move at WARNING. The report is the fresher evidence, and the loser's plan
  and identity are untouched, which is `adopt_renamed_machine`'s own rule.
  DEFERRED with it: the partial UNIQUE index (creating it during `migrate()`
  on a live database that already holds a duplicate pair fails, and the
  dashboard must boot) and WP1's re-key onto `machine_id`.
* **The companion cached its own device id for the process lifetime**, so a
  regenerated Syncthing identity was reported as the old one until the tray
  restarted, which is the shape of this ledger's "stuck lane C" memory. FIXED
  (`reporter.py`, `sync/syncthing_lane.py`): both caches re-read on a 300 s
  cadence; a refresh that comes back empty or throws KEEPS the last known id,
  because a briefly dead Syncthing is not evidence of a new identity, and a
  CHANGED id is logged at WARNING on both sides.
* **Lane C's "no API key" branch never told the supervisor**, so a Syncthing
  whose `config.xml` had vanished was never restarted and an incident opened
  before it vanished could never close. FIXED: that branch calls
  `_note_supervisor(False)` before returning. The launcher is key-independent
  and can regenerate the home.
* **The supervisor could launch twice.** FIXED with a test-and-set claim
  under the existing lock, released in a `finally`. The other half of that
  finding, the tray diagnostics builder calling `check_once()` and parking a
  worker for up to 20 s, is `app.py`'s (CR-67); the verifier had already
  half-refuted the UI-freeze claim, since `tray._spawn` runs it off the UI
  thread, so it is latency and not correctness.

### CR-51 - every Resolve edit, and every AppKit call, on the thread that owns it (comp-resolve-1, comp-resolve-2, comp-resolve-3, comp-resolve-4, comp-resolve-5, comp-app-core-2) - FIXED in repo 2026-08-21, unshipped
Five defects in the Resolve layer, plus its exact twin in the macOS tray.

* **Undo replayed the newest journal of ANY project against whatever project
  was open**, matched by file path only. Every project shares the paths under
  `Assets`, so undoing a canonicalisation done in one project could
  re-address a music bed the OPEN project legitimately uses. FIXED
  (`resolve_bridge.py`): `undo_last_relink` reads the open project first and
  asks for THAT project's journal; a mismatch is a refusal naming both
  projects, checked again after the media-pool walk, which also covers an
  explicitly passed `session_path`. A journal that names no project at all,
  the pre-fix shape, stays replayable, because refusing it would leave that
  editor with no rollback at all.
* **Journal bookkeeping called into fusionscript outside `_API_LOCK`** after a
  successful `ReplaceClip` or `LinkProxyMedia`. FIXED: the `GetName` and
  `GetClipProperty` reads moved inside the locked block and strings are
  passed out. The test double records every native call made while the lock
  is free, probed from a SECOND thread, because the reentrant lock would let
  the calling thread straight back in.
* **The exported `.drp` rollback copies were never swept**, contrary to
  RESOLVE_EDIT_SAFETY.md's 60-day claim, so they accreted in the editor's
  home. FIXED: `SWEPT_SUFFIXES = ('*.json', '*.drp')` under the same cutoff,
  which makes the doc true rather than aspirational.
* **Rate-limited non-canonical relinks were queued and nothing drained the
  queue**, though the refusal itself promises "Tray -> Advanced -> Scan whole
  project runs it now". FIXED (`app.py`): `_handle_non_canonical` takes
  `user_initiated` (a tray click IS the consent the limiter waits for) and
  starts the drain even with an empty incoming batch; `scan_whole_project`
  drains before its verdict. Deliberately NOT changed: the scan does not
  re-classify in-tree clips it finds, because an in-tree clip is in the tree
  whatever its spelling, which is what the scan's own message says.
* **A broken drive mapping cost one toast per clip** (on macOS, one blocking
  osascript spawn each, on the watcher thread). FIXED in `watcher.py` with a
  per-episode latch: one callback for the first BAD_PREFIX path, a logged
  warning naming each of the rest, re-armed when the mapping recovers. The
  per-poll count still counts every newly seen path, and `app.py` needs no
  change.
* **The macOS tray mutated AppKit from worker threads** (icon image, tooltip,
  menu rebuild) from the refresh and pulse threads. FIXED
  (`tray_native.py`): a per-instance hop through
  `NSOperationQueue.mainQueue().addOperationWithBlock_`, deliberately NOT
  `ui_dispatch.dispatch`, which BLOCKS the caller on a pump that parks inside
  a modal dialog's `tkwait` (MAC-11): a pulse thread must never be able to
  wait on an open window. Any failure to marshal falls back to calling
  inline, i.e. today's behaviour, because a tray that stops drawing is worse
  than one that draws from the wrong thread. `stop()`'s `removeStatusItem_`
  is still on the caller's thread and is worth a follow-up.

### CR-52 - the upgrade channel could brick itself, and an interrupted OTA had no exit (comp-app-core-1, comp-app-core-3, comp-app-core-4, comp-app-core-5, dash-core-6, dash-release-ai-2, dash-release-ai-3) - FIXED in repo 2026-08-21, unshipped
Found from both ends independently: **a signed record whose `min_version` is
above its own `version`** ("you may not install below 0.9.50" while offering
0.9.44) raised every machine's monotonic downgrade floor on RECEIPT, before
the offer was checked against it, refusing that build and every later build
below the floor. One stale `CCSYNC_MIN_VERSION` in a build environment would
have reached the whole fleet and been recoverable only by hand, per machine.
FIXED in three places: `upgrade._min_version_above_own` refuses such a record
BEFORE `note_floor`, so the corrected republish is still installable;
`release_trust.min_version_exceeds_version` plus `package_store` refuse it
with a 400 before the signature check, which covers the human PUT and the
feed's auto-publish from one place; and `release_feed._valid_records` drops
it, so it is never offered to an admin. Raising the floor on receipt is
deliberately unchanged: it is what makes a replayed old signed record useless
before a download starts. The signing rig should not be able to MAKE one
either, which is still owed (CR-67).

Beside it:

* **The Windows upgrade hand-off gave up after 20 s** while a shutdown can
  legitimately take longer, which is R11's shape with a different timer.
  FIXED: `PREDECESSOR_WAIT_SECONDS` 20 -> 90, with a documented
  `SHUTDOWN_WORST_CASE_SECONDS = 55.0` enumerating the bounded joins the
  teardown performs in series. The wait costs nothing when the predecessor
  exits early, and applies only to a hand-off keyed on
  `CCSYNC_REPLACES_PID`, never to an editor double-clicking the exe.
* **`auto_update` was one-shot per offer.** A stand-down ("popup",
  "consolidate") or a failed download was never retried, so the CR-27 machine
  class, the exact reason unattended updates exist, never got one. FIXED:
  `_on_upgrade_available` ARMS the update and `_maybe_auto_update()` is also
  called from every report reply, re-checking the site flag (fails closed),
  refusing a withdrawn or replaced offer, and reusing CR-41's retry constants
  (90 s after a stand-down, 600 s after a failure).
* **The downgrade floor file followed `log_path`**, so the documented "delete
  `~/.ccsync/upgrade_floor.json`" recovery did nothing on a machine whose log
  was redirected, and a log_path edit could silently reset a monotonic floor.
  FIXED: the floor lives beside `identity.json`, with a one-time adoption of
  a floor written beside a redirected log so it is carried FORWARD, never
  lowered.
* **A pushed update whose version the machine overtook was re-sent for
  ever.** FIXED (dashboard): the request retires when the reported version is
  at or PAST the one asked for, compared per dotted part so 0.10.0 outranks
  0.9.43, falling back to exact equality when either side is unparsable, so a
  `+dirty` build never reads as "past it" and silently retires a request the
  machine never honoured.
* **An interrupted dashboard self-update wedged the channel.** A process kill
  mid-apply left `in_progress=true`, and every later apply AND rollback 409'd
  with no way to clear it but a shell. FIXED: `_set_state` stamps
  `owner_pid`, and a state claiming in-progress under a pid that is not this
  process is healed to `failed` with "interrupted by a restart at step
  <step>", written back so the next reader sees it too. `restart_requested`,
  the one in-progress state that legitimately outlives its process, is
  exempt; a second apply inside a live process still 409s.

### CR-53 - the YouTube stack, both ends (comp-ytdl-1, comp-ytdl-2, comp-ytdl-3, comp-ytdl-4, comp-ytdl-5, ytdl-web-2, ytdl-web-3, ytdl-web-4) - FIXED in repo 2026-08-21, unshipped
* **The managed ffmpeg pair had no caller on a vendor build.** The 2026-08-18
  refactor left `ensure_ffmpeg_pair` reachable only from
  `sidecar_tools.ensure()`, which sits behind the `youtube_download` gate,
  and `YtDlpManager.start()` was a permanent no-op when that flag was off or
  the manifest cache was absent at tray launch. On the documented vendor
  default, therefore, **no machine ever got the ffmpeg that b-roll ingest and
  proxy generation depend on**, and turning the feature on later needed a
  tray restart on every machine in the fleet. FIXED: the thread always
  starts and the gate moved INTO `_loop`, which re-reads the flag every pass
  (`DISABLED_RECHECK_SECONDS` = 900 s); with YouTube off the loop still
  installs the ffmpeg pair and skips deno, because a JS runtime is a YouTube
  entitlement and a codec is not. `ensure()` also now distinguishes the two
  gates, since the old wording sent an admin to config.toml for a
  site-manifest decision. **Behaviour change for the release notes:** every
  editor machine on a vendor build will fetch the pinned ffmpeg-static build
  about 30 s after tray start, unless the editor has their own ffmpeg on PATH
  or one is already installed. That is what BROLL_INGEST_PLAN 3.3 and this
  ledger's posture note already describe.
* **The local executor ignored the root guard.** With the tree unmounted it
  would create the destination on a Mac's boot volume and download there.
  FIXED: `Deps` gained `root_present_fn` (a zero-I/O read of the guard's
  cached verdict, all the 1 s capability budget allows) and `root_probe_fn`,
  re-checked immediately before the mkdir, which is the line that would
  otherwise create a fake `/Volumes/<Name>` two round trips after the probe.
  A refused job is not failed: nothing is posted, the lease expires and the
  server downloads it, like every other refusal on that path. Note the
  implied change: a machine whose `local_root` does not exist now refuses
  local downloads, which is the same answer its lanes already give.
* **The base-rig label check stat'd a casefolded path**, so on a
  case-sensitive volume a wired Mac refused every label with a capital in it
  and let the lease expire. FIXED: the probe uses the label's own spelling;
  `normalize_label` stays what it is for the selection-set comparison.
* **Clip status posts were not idempotent**, so CR-31's transport retry
  double-counted `dl_done` and `dl_failed`, and a stranded counter is what
  CR-30 turns into "one job per editor blocks SEARCH". FIXED SERVER-SIDE,
  which is the right end: `db.finish_download` is `begin_download`'s twin, a
  compare-and-set from ('pending','downloading') to a terminal state; a loser
  gets `200 {duplicate: true}` and no counter bump, never a 4xx, because a
  4xx would put a perfectly downloaded clip into the executor's failed list.
  The companion needed no idempotency key at all, so none was added.
* **The project picker listed each project once per machine** since the
  dashboard's v24 selections key. FIXED: the no-machine query is the person's
  UNION, per CLAUDE.md's rule. The suite was blind to it because its
  hand-copied dashboard DDL predated v24; that copy is now the v24 shape,
  which is the drift its own comment predicted.
* **AI health was probed once at worker boot and never again**, so a
  transient boot failure pinned the red pip until a job happened to succeed.
  FIXED: `recheck_health()` from the worker's idle branch when the cached
  state is not ok and older than 300 s, non-forced so the provider's own
  probe floor still applies, every failure logged and swallowed so a probe
  can never kill the worker.

`ytdl-web-5` (resolving the provider per call probes every enabled CLI with a
live billed call even when an API provider is pinned) is DEFERRED to
`ai_providers.py`; the 300 s gate above exists partly so the health path does
not multiply its cost. See CR-66.

### CR-54 - drag-and-drop ingest could not survive anything going wrong (comp-loopback-1, comp-loopback-2, comp-loopback-3, comp-loopback-4, comp-loopback-5, comp-loopback-6, trust-model-9) - FIXED in repo 2026-08-21, unshipped
A feature three days old, every failure path of which ended in "already
indexing another batch" for every later drop.

* **A cancelled or 410'd batch killed the upload queue for the session.**
  `UploadQueue.stop_all()` latches, and the ingestor kept one queue for the
  whole tray process. FIXED: the queue is DROPPED after `stop_all()` and
  rebuilt per batch through a `_new_queue()` hook (overridden in
  `MusicIngestor`, so the new queue reads THIS batch's library path rather
  than the cancelled batch's); `stop_all` now reports what it cancelled.
  Rebuilding also drops the stale done/failed ledger, which matters when the
  same batch is re-run and its rels are the same strings.
* **A tray restart mid-batch stranded it.** `needs_claim` was written by the
  resume path and read by nobody, so there was no re-claim and no heartbeat.
  FIXED: `_reclaim()` at the top of `tick()` re-issues the idempotent claim,
  merges only what this side cannot know (never the item states, which are
  the checkpoints the restart exists to keep), restarts the heartbeat and
  re-enqueues every item still at `ITEM_UPLOADING`. 403/409/410 frees the
  machine; a transport failure is not an ending, and the next tick asks
  again.
* **An upload rclone failed parked the item for ever**: never retried, never
  failed, batch never finished. FIXED: attempts are counted, retried below
  the cap and failed at it; `UploadQueue.retry(rels)` drops those rels from
  the failed ledger (without it the item burns one attempt per tick with no
  new rclone), and only the rels that failed are re-sent, deliberately
  narrower than the 409 branch's whole-item re-declare, because re-sending a
  40 GB original after a 100 KB poster failed is an editor's evening.
* **A refused `/result` was ignored**: the clip was uploaded and went live
  with no segments, and was never re-described. FIXED: `_post_result` clears
  `described` so a retry re-runs the model, fails the item with the server's
  own words, and enqueues nothing.
* **A blank mount entry was treated as the filesystem root**, and
  `contained_local_path`'s containment check was guarded on the mount being
  truthy, i.e. skipped exactly when it mattered most. FIXED
  (`broll_server.py`): blank is absent (falling through to the darwin
  /Volumes probe, and refused if that answers blank too), and the containment
  test is unconditional.
* **`POST /broll/ingest/prepare` accepted any local path.** The allowed-roots
  refusal the plan and the docstring describe did not exist. FIXED: only
  `/pick` teaches the companion a local path. `pick_ingest_sources` records
  the PICKER's answer, never the body of the prepare that follows, through
  `note_picked`, which stores the picked FOLDERS (climbing back up each
  clip's rel_dir so a 400-clip card is one root, last 32, persisted so a tray
  restarted between the pick and the prepare does not refuse the drop);
  `_path_refusal` ends with a realpath containment test, and an EMPTY
  allow-list REFUSES, because "nothing was picked" and "everything is
  allowed" must not be the same answer.
* `trust-model-9`, the observation that the loopback allow-list makes any XSS
  in the dashboard-hosted SPAs equal to code execution on every editor's
  desk, is recorded in `loopback_guard.py`'s docstring naming the reachable
  routes (`/insert`, `/music/reveal`, `/ytdl/reveal`, `/broll/ingest/run`).
  Both code halves are deferred: the CSP is server-side and spans four apps
  (CR-67), and dropping the plain-http twin from `origins_for_url` is small
  but NOT safe, because both schemes are a documented fix for a live failure
  and the manifest carries no signal for which one editors browse.

### CR-55 - a per-editor token switched three fleet surfaces off (music-1, ytdl-web-1, dash-core-2, dash-core-5) - FIXED in repo 2026-08-21 (b-roll mirrored in wave 2), unshipped
CR-18 gave every editor a `cce1.` token that BINDS to an identity, and the
dashboard's own boot warning tells the operator to retire the shared one.
Three companion-facing surfaces only ever compared against the shared secret,
so minting an editor their own token silently disabled their fleet music
ingest and their requester-first YouTube downloads, while `/api/v1/verify`
still handed out the retired shared token for a freshly signed-in companion
to adopt and have refused on every report. `/fleet/halt` had the inverse bug:
it took the retired shared token and refused per-editor ones. Note the ytdl
half is live TODAY for any editor already holding a cce1 token, without
waiting for the shared one to be turned off, because the companion already
prefers the per-editor token.

FIXED with ONE verifier, the way `ai_backend.set_provider_lookup` already
works. `api.resolve_companion_credential(settings, conn|None, token) ->
(kind, editor)` already existed in the shape needed; the mounts now use it.
`MusicGate` and `YtdlGate` STRIP any inbound `X-CCSync-Fleet-Auth` on every
request and append their own verdict, `shared` or `editor:<name>`; the
sub-apps believe that stamp only when the mount installed the trust
(`trust_gate_stamp`), and otherwise fall back to the unchanged fail-closed
shared-secret compare, so standalone `musicweb` is unaffected and an older
deployed tree keeps working. The stamp is NEVER an identity: ytdl's
`require_fleet_caller` 403s `identity_mismatch` when a bound token's editor
is not the verified `X-CCSync-Identity`. `/verify` returns the shared token
only while `shared_report_token_enabled` and adds `report_token_kind` so the
tray can say which credential this fleet expects (CR-18's rule that /verify
never mints a `cce1` is unchanged), and `/fleet/halt` now authenticates
through `companion_token_ok` like every other companion route.

**b-roll now mirrors it** (wave 2, 2026-08-21). `broll/web/app/fleet_auth.py`
gained the same stamp header, the same `trust_gate_stamp(True)` installed
from `mount_broll` (b-roll has no `config.login_gated()` the way musicweb
does, so the trust is installed the ytdl way), and a single
`require_fleet_caller` that runs the machine credential first and the signed
identity second and 403s `identity_mismatch` when a bound token's editor is
not the verified `X-CCSync-Identity`. All six fleet routes moved from two
separate dependencies to that one, because nothing had both answers in one
place. `dashboard/broll.py`'s `BrollGate` strips `X-CCSync-Fleet-Auth` on
every request and appends its own verdict through
`api.resolve_companion_credential`, opening a connection only for a token
with the per-editor SHAPE and treating any failure as "no stamp" rather than
"stamped anyway". `api`/`db` are imported INSIDE `_fleet_stamp` on purpose:
`auth.py` imports `broll.py`, so a module-level import would close the
auth -> broll -> api -> auth cycle at boot. `/fleet/halt` also needed its
path in `login_gate` (GET only, exact path, verified companion credential);
that landed in wave 2 too, so a companion can now actually read it.

### CR-56 - the accounts, the sessions and the login throttle (dash-core-3, trust-model-2, dash-admin-5, dash-core-4, trust-model-3, trust-model-5, trust-model-7) - FIXED in repo 2026-08-21, unshipped
* **Disabling an account revoked nothing.** Its open tabs and its companion's
  per-editor report token kept working until expiry, or never. FIXED:
  `api_admin_disable_user` runs DELETE's own `_purge_user_credentials` (with
  a `why`, so the revocation reads "account disabled") AFTER the commit,
  which is the ordering that keeps the session store's own connection out of
  a deadlock. Re-enabling resurrects nothing: a new token is one click.
  Chosen over teaching `_resolve_session` and `verify_editor_report_token` to
  consult `users.disabled`, because those two run on every request and in
  SMB/OIDC modes where there is no `users` row at all.
* **An admin could disable themselves, or the last enabled admin**, and lock
  an appliance out of admin entirely. FIXED at both doors and in the library
  beneath them: `api_admin_disable_user` gained DELETE's two guards as 409s,
  `local_users.disable_user` refuses the same two, and
  `ui.partial_admin_disable_user` (the htmx twin, softer on both counts)
  passes `requested_by` and purges credentials too. `DASH_ADMIN_USERS` is
  deliberately not counted as an admin: on an appliance it needs a redeploy.
* **A successful login cleared the per-IP budget**, so owning one valid
  account reset the spray protection for every other username. FIXED: a
  successful sign-in clears only the per-username row; the IP row ages out
  through its own window.
* **One Tailscale Serve gateway was one throttle bucket for the whole
  fleet**: five wrong passwords by anybody locked everybody out of /login and
  /verify for up to an hour. FIXED in two places: `LOGIN_FAILURE_LIMIT_IP =
  40` against the per-username 5 (one address behind Serve is one GATEWAY,
  not one person, while 40 wrong passwords an hour from one address still
  trips), and `auth.client_ip` logs a WARNING once per peer when an
  `X-Forwarded-For` arrives from a peer NOT in `DASH_TRUSTED_PROXIES`, which
  is the exact signature of the misconfiguration. The list itself is now
  emitted by the installer (CR-61). Deliberately NOT done: exempting a "known
  shared gateway" from the budget, because the only evidence available is the
  spoofable header itself, so an attacker could opt out of the budget by
  adding it.
* **OIDC skipped the fleet-membership check password sign-in enforces**, and
  mapped the IdP username claim straight onto an editor identity. FIXED:
  `require_fleet_member` runs between id_token verification and
  `start_session`, in a threadpool with its own short-lived connection. Four
  ways to pass: `DASH_ADMIN_USERS`, the admin claim mapping, the new
  `DASH_OIDC_ALLOWED_GROUPS` (with `DASH_OIDC_GROUPS_CLAIM`), or a username
  this fleet already knows. An empty allow-list means "not configured", never
  "everybody"; a dashboard with no editors on record at all skips the check
  and logs why, so an operator cannot be locked out on day one.
* **The AI CLI SET UP wizard installed Codex with no publisher checksum**
  while the docs and CLAUDE.md call the fetch checksum-verified. FIXED:
  `_install_codex` refuses, before any download, when the release publishes
  no `SHA256SUMS` entry for the asset, pointing at the "type its full path"
  fallback the page already has. `checksum_source` can no longer be
  `downloaded_bytes` for a wizard install, so the claim is enforced rather
  than aspirational.

### CR-57 - the setup wizard and the appliance's first boot (dash-admin-1, dash-admin-2, dash-admin-4, dash-admin-7) - FIXED in repo 2026-08-21, unshipped
Four ways the zero-touch appliance could not actually be set up.

* **The Storage check task created the shared asset folders inside the
  container's root filesystem** and could never go green on any real
  deployment: it derived the tree root as `Path(projects_dir).parent`, which
  for the deployed `/projects` mount is `/`. FIXED: `_tree_root(ctx)` is
  `DASH_TREE_DIR` when the whole tree is mounted, else the parent only when
  it is not a filesystem root; when the root is not visible the task probes
  what it CAN answer (is `projects_dir` writable) and reports ok with "the
  shared asset folders live beside Projects on the NAS, which this container
  does not mount", so the required task goes and STAYS green. A failed mkdir
  now warns naming the folder and the path, instead of reporting ok with
  "created 0".
* **The appliance minted three different internal tokens.** secrets-init, the
  dashboard's bootstrap and the sftp sidecar each held their own, and the
  Syncthing API key flipped on first boot, so the sidecar's
  `AuthorizedKeysCommand` was refused 401 for ever. FIXED: one file per
  secret, agreed by every party. `secrets_boot.SIDECAR_ENV_FILES` ADOPTS
  whatever secrets-init already wrote (provenance `sidecar-file`) and mirrors
  it into the canonical secrets file, and it writes `internal.env`, the file
  the compose sftp service actually reads, instead of the `sftp.env` nothing
  ever read (a stale one is deleted on boot: say so in the release notes in
  case an operator built tooling around it).
* **First-admin bootstrap was unreachable from a browser.** In
  `DASH_AUTH_METHOD=local` with zero accounts, `/setup` redirected to /login
  and every `/api/v1/setup/*` 401'd. FIXED: `first_run_open` answers from
  `local_users.any_users_exist` when the admin probe is inconclusive AND the
  method is local; smb and oidc keep the fail-closed answer, because a NAS or
  an IdP can already authenticate an admin there, and a pre-v17 database
  still reads as closed. The window shuts the moment the first account
  exists, and `setup_admin`'s own BEGIN IMMEDIATE remains the lock.
* **`nas_kind` was unvalidated free text** on Settings and in the site.toml
  import, was published to installers, and was never what `nas.factory`
  actually reads. FIXED: `site_store.validate` normalises the case and
  refuses a kind no factory can build (422 from the PUT and from the import),
  and the Settings field is a select of `NAS_KINDS`, so an admin never meets
  the refusal. The factory still reads `DASH_NAS_KIND`, deliberately: what is
  fixed is that the two can no longer disagree by SPELLING.

`dash-core-7` (the `ccsync-dashboard` console entry point skips
`secrets_boot.ensure_secrets`, unlike the run.sh `--factory` path) is a
two-line change in `dashboard/app.py`, which was nobody's territory: CR-67.

### CR-58 - the Settings page wrote one truth and the dashboard read another (dash-release-ai-1, product-surface-1, product-surface-2, dash-admin-3, product-surface-5) - FIXED in repo 2026-08-21 (the three env readers landed in wave 2), unshipped
The wizard and Settings write the DB and publish it to companions; the
dashboard's own code read only the environment. On an appliance, where
compose sets no `DASH_SITE_*` at all, the admin's answers reached every
companion and not the dashboard itself.

* **Ticking "YouTube downloader" published the feature to the fleet and never
  mounted `/ytdl`.** FIXED: the flag resolves DB-row-first through the new
  `site_store.feature_enabled`, which fails closed on an unknown flag or an
  unreadable table (with `FEATURE_SETTINGS_ATTRS` as the one place a new flag
  is registered, the same discipline CR-40's `FEATURE_KEYS` whitelist
  imposes on the companion) and falls back to the env on any error, because a
  legal switch must never be flipped on a customer's behalf by a sqlite
  error. `ai_providers.cli_enabled` delegates to it, so there is one
  implementation of the precedence rather than two. The mount is now always
  present and gated PER REQUEST with a 5 s TTL: 404 for everything under
  `/ytdl` while the site says no, importing nothing, and on the first request
  after an admin ticks the box it loads the sub-app inline and serves it. No
  restart, which is what WP D promised, and the reverse works too. `ABSENT`
  (the tree is not deployed) deliberately stays unmounted rather than
  retrying an import, and walking sys.path, on every poll.
* **Brand, create-project template and shared-asset list.** FIXED:
  `site_store` gained `manifest_for_app` (a per-process cache on `app.state`
  that never raises, falling back to the Settings-only shape rather than
  breaking a render) with `invalidate()` on every writer, so `ui._render`
  paints the topbar brand from the DB and an admin who saves a new
  `org_name` sees it immediately; `/project-setup`'s preview and the Setup
  storage task read the manifest's template and shared-asset lists. Wave 2 closed the last three readers, so
  the preview and the create can no longer disagree: `api.create_tree_project`
  iterates `site_store.template_folders`, the collector re-reads
  `site_store.shared_asset_folders` once per cycle into
  `_shared_folders`/`_shared_folder_ids` (seeded from `provision` at
  `__init__`, so a Collector never handed a connection behaves as before, and
  a failed or EMPTY read keeps the previous list on purpose, because an empty
  shared-folder set in `_run_enforce` is the B16 unshare shape), and the ASGI
  title comes from `site_store.manifest_for_app`. One cosmetic consequence:
  on a database that has not been migrated yet, a genuine first boot,
  `create_app` logs one "could not read the site manifest" warning and falls
  back to the deploy-time values.
* **Only two of the four feature flags were on the Settings page.** FIXED:
  `auto_update` has a checkbox with its one-line consequence, and
  `ai_cli_providers` shows as a disabled, deliberately NAME-less checkbox
  linking to the AI providers section that owns it (name-less because the
  page collects by element name, and a nameless control cannot submit a `0`
  that would switch the CLI feature off).

### CR-59 - the release pipeline could overwrite the vendor channel, and nothing signed the installer (release-pipeline-1, release-pipeline-2, release-pipeline-3, release-pipeline-4, release-pipeline-5, release-pipeline-6, release-pipeline-7, release-pipeline-10, release-pipeline-11, installer-onboard-tools-1, installer-onboard-tools-2, installer-onboard-tools-6) - FIXED in repo 2026-08-21, unshipped
The critical one first. **`publish_feed.py` rebuilt `channel.json` from the
gitignored local `feed/` dir and uploaded it with `--clobber`**, so running it
from any machine but the one that happened to hold the history would replace
the live vendor channel with a one-record document. FIXED: with
`--github-upload` the tool downloads the PUBLISHED channel and its signature
first, verifies it against the baked release keys, and merges the local
overlay ON TOP of it. The failure modes are separated on purpose: "no such
release or asset" is a legitimate first publish, while any other `gh` failure,
or a channel that does not verify, refuses the upload entirely, because "I
could not ask" is never "nothing is published". A `shrink_report()` backstop
refuses any upload that removes published records unless `--allow-shrink`. The
local feed dir is still written and signed before that refusal, keeping the
old promise that a failed upload leaves a whole verifiable feed behind, and
`publish_latest.py` now reads the live channel instead of that directory.

The rest, in `tools/`, `installer/`, `onboarding/` and `.github/workflows/`:

* **A `current` pointer and a retraction** (release-pipeline-5): an optional
  top-level `{"<kind>/<platform>": "<version>"}` object INSIDE the signed
  document, written by `--make-current` and cleared by the new
  `--retract KIND/PLATFORM/VERSION`. The dashboard's `_apply_policy`
  publishes only the record the pointer names, falling back to the HIGHEST
  version (compared numerically, so 0.10.0 beats 0.9.41) rather than append
  order, so a fresh dashboard stops replaying the whole history. Under
  `current`, a pointer naming a build the dashboard already HOLDS makes it
  current, which is the retraction and rollback path the feed lacked; the
  retracted ASSET stays on the release on purpose, so a dashboard holding
  that record can still fetch the bytes it verified.
* **Same version, different bytes** (release-pipeline-6): the dashboard's
  "already published" 409 now compares the sha256 and NAMES the mismatch,
  logs it loudly on every check, and renders a [ SAME VERSION, DIFFERENT
  BYTES ] line on the Packages page. Nothing is ever replaced in place.
  `publish_feed`'s `--allow-replace` half is still owed (CR-67).
* **`publish_latest.py` signed whatever CI run was newest**, with no tie to
  main, to HEAD, or to version monotonicity (release-pipeline-7). FIXED: the
  run list is filtered to main AND independently verified with `git
  merge-base --is-ancestor` against origin/main, because a branch label is a
  claim a force-push can make untrue and an unknown answer counts as NOT
  verified; a version lower than the channel already carries is refused
  unless `--allow-older`. Both checks run before anything is signed. It is
  also DOCUMENTED at last (release-pipeline-10), in `docs/RELEASE.md` under
  "the command actually used since 2026-08-19", together with the policy line
  it implements: CI builds, this rig signs, `ship.cmd` is for the studio's
  own dashboard.
* **`ship.cmd` was unaware of image mode** (release-pipeline-3): it restarted
  the live dashboard for nothing and could not pass its health gate once the
  repo's dashboard VERSION was bumped. FIXED: it reads `[stack] mode`, skips
  the deploy script entirely in image mode, and the gate becomes live >= repo
  with a numeric per-component compare (a string compare would fail a good
  ship the day 0.10.0 exists). A repo ahead of the container stops the ship
  BEFORE anything is built and prints the over-the-air recipe. `-Recreate`
  still runs the deploy, because that flag is an explicit request about the
  CONTAINER.
* **`onboard.exe` was never Authenticode-signed** (installer-onboard-tools-1),
  which is the fresh-install SmartScreen case the signing gate exists for,
  and **the CI signing route could never fire** (installer-onboard-tools-2: a
  step-level `env` is not visible in that step's own `if`). FIXED: one shared
  `tools/sign_windows_binary.ps1` call site for the companion, the wizard and
  the CI build; `-MakeCurrent` with an unsigned onboard.exe refuses BEFORE
  the companion PUT, so a refusal leaves the channel untouched rather than
  half-published; the secret moved to job-level env with the emptiness test
  inside the body, and either branch writes a line into the run summary, so a
  skipped signing attempt can no longer be invisible.
  `check_deploy_drift.ps1` reports the installer row's `signed_binary`.
* **The installer channel was never published through the feed**
  (release-pipeline-4), so feed-only customers had no installer at all.
  FIXED: both workflows emit an `onboard` manifest (the companion's key set,
  with `tests_run` set by the onboarding suite actually run in that step
  against that tree, so it can never claim true on trust, since publish_feed
  refuses a `tests_run=false` manifest) and `publish_latest.py` accepts
  `--kind onboard` for both platforms.
* **`ship.cmd`'s "already published" probe downloaded the whole exe with no
  timeout** (installer-onboard-tools-6). FIXED: `-r 0-0 --max-time 20`, and
  206 counts as published, matching the installer probe directly below it,
  whose comment already explained why.
* **The Authenticode key's home is a contradiction** (release-pipeline-11:
  designed for GitHub secrets while the release-key policy is "CI builds,
  this rig signs"). Both resolutions are written up in `docs/RELEASE.md` for
  the owner to choose BEFORE a certificate is bought; the CI route was
  deliberately not deleted, since removing the only working CI signing path
  would be a unilateral answer.
* **Two publish paths with no reconciliation** (release-pipeline-2): PARTIAL.
  `ship.ps1` gained `-PublishFeed`, off by default because "CI builds, this
  rig signs" is standing policy and flipping it would send studio-built
  binaries to every customer, and by default it prints at the end of every
  ship that the vendor feed does NOT have this build, with the exact command
  to mirror it. Making the feed the single channel is a release-policy
  redesign: CR-66.

**Behaviour change worth an operator's attention:** on this studio, whose
site.toml says `[stack] mode = "image"`, `ship.cmd` will no longer deploy or
restart the dashboard during a companion ship, and will STOP if the repo's
dashboard VERSION is ahead of the live one. The failure message spells out
the three over-the-air commands.

### CR-60 - the wizard and the package builder still assumed `P:` (installer-onboard-tools-3, installer-onboard-tools-4, installer-onboard-tools-5) - FIXED in repo 2026-08-21, unshipped
Item 11 of the commercial-readiness pass made the tree root site data, and
both bootstraps, both uninstallers and the companion honour it. The
onboarding wizard did not: `SUBST_TASK_NAME`, the Run values, the loopback
share name, the local-root validation, the cleanup plan and every page's copy
were built around the letter `P`. `build_editor_package.ps1` had the tree
path hardcoded in its parameter default, and the wizard computed its default
local root BEFORE fetching the site manifest, so a first run ignored the
site's `tree_name` entirely.

FIXED: `onboarding/steps.py` derives all of it from `canonical_prefix`
(refusing to guess from a UNC or POSIX prefix, so the bootstrap's own refusal
is not masked), and the cleanup plan covers the site's letter AND the
historical `P` one, since a machine may predate the change. `_on_verify`
re-derives the prefill unconditionally once the manifest is in hand, and the
neutral first-run value is in the clobberable set so the recompute actually
replaces it (a hand-edited path is still never clobbered).
`build_editor_package.ps1` resolves its destination from `canonical_prefix`
at runtime (config.toml, then the cached site.json, then `P:\` as the last
resort the bootstrap already uses) and refuses a destination whose drive is
absent BEFORE PyInstaller runs, rather than throwing three minutes in.
`Test-DriveMapParser.ps1`'s "no `CCSyncSubstP` literal" scan now covers
`onboarding/steps.py` too. Verified on this rig to resolve to exactly the
previous literal.

### CR-61 - the server scripts (server-1, server-2, server-3, server-4, server-5, server-6, server-7, trust-model-3, ops-efficiency-7) - FIXED in repo 2026-08-21, unshipped
* **`publish_db --rollback` could not find the `.prev` it had just made.**
  `newest_prev` listed the directory unprivileged through a pipeline whose
  exit code was `tail`'s, so "could not read" and "nothing there" were the
  same answer and the operator was told there was nothing to roll back to.
  FIXED: a privileged `find` (sudo, like every other filesystem probe here),
  sorting in Python, and THREE answers instead of two, so a refused listing
  says so and names `--from-prev`. A dry run now describes what it would do
  and exits 0, rather than printing a FAILED line it cannot substantiate.
* **`setup_tree`'s pre-chown snapshot was never taken on TrueNAS.** The `df`
  probe that resolves the dataset ran unprivileged on a path the admin cannot
  stat, so `snapshot_before` had nothing to snapshot before a `chown -R`.
  FIXED: the probe runs under sudo, and the docstring's claim that it "needs
  no privilege" is replaced by why it does. Deliberately NOT done, because it
  is a policy change for the owner and not a bug fix: making a setup_tree
  snapshot failure louder than a WARNING, and defaulting `--require-snapshot`
  when `[tree] pool_root` is set. A NAS that cannot be snapshotted must not
  be a NAS where projects cannot be created.
* **A fresh TrueNAS install left `<tree>/Assets` root-owned**, so Syncthing
  could not create the LUT and Stills folders and editors could not write
  under Assets. FIXED: the deploy creates and owns the shared-assets parent
  and its leaves (from `common.SHARED_ASSET_FOLDERS`, the same list the
  collector provisions) with the posture Projects and the archive already
  have. The whole step is NON-FATAL on purpose: nothing MOUNTS
  `<tree>/Assets`, and a deploy must not die over the posture of a directory
  it does not mount.
* **Ownership was hardcoded 3000:3000 and 3000:3001** while the container
  runs as `[stack] uid/gid`. FIXED: every chown in the chain renders the
  configured ids, with a new `APP_PRIVATE_GID` (default = uid) so the private
  dirs stay off the editors group (AUDIT C-2) and the emitted script is byte
  identical on this fleet. `owner=""` still means "emit no chown at all",
  which is the DSM tree-share case, so the two answers stay distinct.
* **`publish_db` on a Synology staged in `/tmp`**, which its chrooted SFTP
  channel cannot reach, so every `--apply` failed at the transfer. FIXED:
  `staging_parent()` is `/tmp` on TrueNAS and `<apps root>/staging` on DSM,
  created as the SSH user at 700 (non-fatal preparation; the mktemp is what
  decides). Noted for a follow-up: three other `sftp.put` calls in
  `install_dashboard_app.py` pass a raw NAS path instead of going through
  `backend().sftp_path(...)`, which is the same bug in three more places.
* **`setup_snapshots.py` cannot schedule the apps target on this fleet** (the
  apps root is a directory in the pool root, not a dataset) while
  BACKUP_RESTORE.md claimed it was snapshotted and gave a restore path that
  does not exist. FIXED by naming the real remedy rather than widening
  `DATASET_RE`, whose refusal is a deliberate guard (a recursive hourly task
  on a pool is somebody's whole NAS): the refusal names the path, says it has
  no snapshot floor of its own and gives `zfs create -p`; `--list --apply`
  now reports a target that cannot be scheduled at all and exits 1; and the
  doc carries the conditional plus BOTH restore paths.
* **Every script SSH'd to port 22.** FIXED: `common.nas_ssh_port()`
  (`$CCSYNC_SSH_PORT`, then `[nas] ssh_port`, then `[net] sftp_port`, then
  22) and `host_key_id(host, port)` keyed the way OpenSSH and paramiko spell
  it, so a pinned or first-use key on a moved sshd is found and recorded.
  Every caller picks it up unchanged, and the "pin it" hint prints
  `ssh-keyscan -p <port>`.
* **`DASH_TRUSTED_PROXIES` is now emitted by the deploy** (trust-model-3's
  installer half; the dashboard half is CR-56). The compose TEMPLATE files
  are another territory, so the manual "Install via YAML" and Synology paths
  do not carry the line yet; the debt is recorded as
  `install_dashboard_app.COMPOSE_ENV_ONLY_IN_DICT`, and
  `test_safety.test_env_keys_match_compose` subtracts exactly that tuple and
  FAILS if it names a key compose_config does not set, or one compose.yaml
  has since gained. That is the one place a drift guarantee was narrowed, and
  it is self-expiring by construction.
* **Container stdout was unbounded** (ops-efficiency-7). PARTIAL: the compose
  BODY the TrueNAS deploy POSTs now caps json-file logging at 20m x 5 on the
  dashboard and the PO-token sidecar. `--no-access-log` and the same block in
  the three compose templates are `dashboard/deploy/`'s: CR-67.

`trust-model-4` (editor rclone lanes verify no NAS host key while the
operator scripts refuse an unpinned one, and a compose comment claims the
opposite) is DEFERRED but no longer undocumented: `docs/SERVER.md` now states
the three facts, the exposure, and the four-part shape of the real fix. CR-66.

### CR-62 - what the fleet costs when nothing is happening (ops-efficiency-1, ops-efficiency-2, ops-efficiency-3, ops-efficiency-4, ops-efficiency-5) - PARTLY FIXED in repo 2026-08-21, unshipped (still open: the per-project change signal, the NAS-reachability pre-probe, completion on its own thread)
* **Every machine re-sent its full manifest and media tree every 60 s** and
  the server rewrote thousands of rows per machine per minute. FIXED
  (`reporter.py`): the heavy sections are omitted when their sha1 equals the
  last one the dashboard ACCEPTED and that acceptance is younger than 600 s.
  The bookkeeping runs only after a successful POST and records the digest of
  the FITTED content, so a failed report resends, a section `_fit_payload`
  shed is remembered as not sent, a section the server says it TRUNCATED
  clears the whole record, signing in as a different editor clears it too,
  and the first report after a start always carries both. The server contract
  was confirmed and is now PINNED by a test: an absent section leaves the
  table untouched, it never clears rows. Consequence for the dashboard's own
  views: `editor_media_project` and `media_tree` row timestamps will lag by
  up to ten minutes even though the data is current, so anything rendering
  them as freshness should say "last CHANGED", not "last received".
* **A steady-state pass cost three rclone processes, two recursive SFTP
  listings and three local walks per project every minute with nothing to
  move.** PARTIAL: the between-passes wait now backs off 1x, 2x, 5x
  `sequencer_idle_seconds` while consecutive passes move nothing, reset by
  anything that is evidence something changed (a lane that moved a file, a
  watcher notify, a tray trigger, a resume, a changed selection set). Capped
  at 5x rather than the suggested 600 s because lane B has no NAS-side change
  signal, so the backoff IS the worst-case proxy latency. The real fix, a
  per-project proxy-tree signature published in the selection response so a
  pass can be skipped entirely, needs the collector and api.py: CR-67.
* **A lane C turn blocked the sequencer for up to 600 s per project** though
  the pause scheme that justified the wait is off by default. FIXED: under
  `PAUSE_SCHEME_ROTATE` the wait stays the full rotation, where it is
  load-bearing (the next turn pauses this folder); under the default scheme
  it is capped at `lane_c_settle_seconds` (30, and 0 restores the old
  behaviour), because nothing is paused and Syncthing paces lane C itself.
* **No NAS-reachability short-circuit**: an offline editor spent each pass
  spawning rclone processes into `contimeout x retries`, per project.
  PARTIAL, with no new probe: a pass where lanes A and B BOTH returned error
  for the same project ends with one WARNING instead of asking every
  remaining project (consulted only when lane B is enabled, since on a wired
  machine lane A is alone and its failures prove nothing). Deferred: a TCP
  pre-probe and a distinct "offline" lane state, because the companion does
  not hold the SFTP host at all (it is in rclone.conf, addressed by remote
  name) and a new lane state changes what the tray classifier and the fleet
  grid render.
* **The collector is one thread with sequential Syncthing calls and no
  deadline**, so a slow Syncthing parked enforce, connections and the health
  signal. PARTIAL: `_run_completion` has a wall-clock budget
  (`DASH_COMPLETION_BUDGET_SECONDS`, 30 s, 0 disables) that stops at a FOLDER
  boundary, never mid-folder (which would write some of a folder's pairs and
  drop the rest), writes what it gathered, records `partial: N folder(s) left
  for the next cycle` in `poll_runs` as a SUCCESSFUL run so the health panel
  can say why, and rotates a cursor so the next cycle starts where this one
  stopped; pairs whose folder was not reached keep their last known need
  count instead of being pruned as "no longer shared". The per-pair timeout
  landed in wave 2 (2026-08-21): `SyncthingClient._request`/`_get` take an
  optional `timeout` that overrides the client default for ONE call, and
  `db_status`/`completion`/`remoteneed` pass
  `Collector._completion_call_timeout()` (`min(client.timeout, 3.0)`, so a
  deliberately tighter client is never stretched) through its ~120 per-folder
  and per-pair reads, which is what stops one hung pair eating the whole
  30 s cycle budget. Every other call keeps the 10 s default. Still deferred:
  moving completion onto its own thread and connection.

**Operator-visible:** idle machines will report fewer pass cycles (60 -> 120
-> 300 s at the defaults), `current_project` moves through the queue faster,
and heavy reports may omit the media sections for up to ten minutes. All
three are the intended saving, not a stall.

### CR-63 - the b-roll platform (broll-1, broll-2, broll-3, broll-4, broll-5) - FIXED in repo 2026-08-21, unshipped
* **`--model fable` sent `{"type": "disabled"}`**, which that model rejects
  with a 400, and the 400 was classified per-video, so an archive run marked
  every clip `error`. FIXED: models whose thinking is always on get the key
  OMITTED, deliberately per-model rather than the simpler "never send
  disabled", because an absent `thinking` runs ADAPTIVE on the bigger models
  and would quietly buy billed thinking tokens on every one of tens of
  thousands of calls, which is the opposite of what `thinking: disabled`
  exists to do. Plus `is_config_api_error`: a 400 naming a parameter this
  module sends on EVERY call aborts the run with the queue resumable, instead
  of burning the archive one clip at a time. The marker list is deliberately
  narrow, so a clip-shaped 400 (image too large, prompt too long) stays that
  clip's problem.
* **The public share routes trusted a stale `item.video_id`** without the
  `(share, rel_path)` identity check `resolve_items` applies, so after a
  renumbering rebuild a client link could serve a DIFFERENT clip. FIXED:
  `member_video_id` re-checks the identity under that id before answering,
  keeping the direct-membership fast path (one indexed SELECT) rather than
  re-resolving every item in the folder on every media request. The same
  class of bug two lines below, where the curator note matched only the
  stored id and vanished after a rebuild, is fixed with it.
* **`/share/assets` published the ENTIRE editor static tree past the
  tailnet** (app.js, ingest.js, clientfolders.js, index.html), on the one
  prefix the operator publishes with Funnel. FIXED: an allow-listed
  `StaticFiles` subclass carrying the viewer's own files and nothing else,
  chosen over a second copied directory so nothing drifts; the refusal is the
  same 404 a missing file gets, so the mount reveals nothing about what the
  directory holds.
* **The card popover's "already in folder" tick compared the raw stored id**,
  so after a rebuild it was wrong and a second add made a duplicate. FIXED at
  all three sites: `add_items` reports an already-filed identity as `already`
  instead of inserting, the popover computes `contains` on id OR
  `(share, rel_path)`, and `resolve_items` dedupes by CURRENT index id, so a
  folder that already holds a legacy duplicate row draws the clip once.
* **Over the HTTP ingest backend, `set_error` and every field outside
  `VideoIn` was silently dropped**, so a failed clip's status became `error`
  with no message. FIXED by adding the columns the indexer actually forwards
  (error, full_hash, duplicate_of, archive_path, original_*), written on
  insert and COALESCEd on conflict so a later plain scan cannot blank them,
  plus `extra='allow'` and a WARNING naming the fields, deliberately NOT
  `extra='forbid'`: a 422 there would arrive while the indexer is already
  handling a failure and would lose the row as well as the message.

### CR-64 - the music platform (music-2, music-3, music-4, music-5, music-6) - FIXED in repo 2026-08-21, unshipped
(music-1, the per-editor token, is CR-55.)

* **A published or drained index was never picked up.** `musicweb` caches a
  connection per worker thread and holds the search matrices in memory, so a
  rename-publish left every thread serving the old, unlinked inode until an
  admin POSTed `/music/api/reload` or the container restarted, and no runbook
  said so. FIXED by self-healing: `con()` stats the path and drops the cached
  connections when the SAME path names a different (dev, ino); the search
  Index records the file state it was built from and rebuilds when it moves,
  rate-limited to one check every 2 s so a burst of fleet ingest cannot cost
  a matrix rebuild per search. Keyed by PATH on purpose, so repointing
  `MUSIC_DB_PATH` is a different database and not a swap. Deliberately NOT
  `PRAGMA data_version`, which is per connection and would make two threads
  ping-pong one shared Index. DEPLOY.md, `docs/INDEXERS.md` and the drain CLI
  all now say that a container running an OLDER musicweb still needs the
  reload.
* **Drain failures never reached the live index**: a queued upload that could
  not be analysed stayed `pending` on the NAS for ever and was re-decoded by
  every drain. FIXED: the bundle carries a `bundle_failures` table and the
  apply marks the matching LIVE row failed under the same agreement checks
  the successes use (uid exists, rel_path agrees, content_hash unchanged, and
  a row already `done` is never forced back). `BUNDLE_VERSION` stays 1 and
  the table is read inside a `try`, so the change is additive in BOTH
  directions: an older base rig's bundle still applies here, and a new bundle
  still applies on an older NAS.
* **A preview proxy was chosen by track id alone**, so a reused rowid served
  a different track's audio. PARTIAL: `config.drop_proxy(track_id)` is called
  from every path that FREES an id or creates a row at one (prune, the
  fleet-ingest insert, the drain apply), best-effort and after the commit.
  Renaming proxies to `<id>-<hash8>.mp3`, which would also survive shipping a
  base rig's whole `proxies/` directory over the NAS's after the two indexes
  diverged, invalidates every proxy in the field and needs a regenerate; that
  residual case is documented in `docs/INDEXERS.md` instead. An
  mtime-against-`analyzed_at` check was considered and rejected: a base-rig
  re-index bumps `analyzed_at` on every row without touching a proxy, so it
  would silently disable previews fleet-wide.
* **A vector whose byte count is not a multiple of 4 was a 500**, aborting
  the transaction after the track INSERT so the companion saw a server error.
  FIXED: a 422 naming the reason before the transaction opens; a truncated
  WINDOW vector drops that window with a log line instead, matching what the
  route already does for an empty or non-finite one.
* **DEPLOY.md and the ledger docstring promised a base-rig fallback that does
  not exist** (MUSIC-ING-2's open half: there is no `queue_add` anywhere in
  the fleet routes, the audio stays on the editor's machine, and a drain run
  in that belief correctly finds nothing). FIXED as documentation on both
  sides, naming the missing `POST .../items/{iuid}/queue` route.

### CR-65 - docs that were wrong, tests that skipped the gate they guard (product-surface-4, product-surface-6, product-surface-7, product-surface-8) - PARTLY FIXED in repo 2026-08-21, unshipped (the docs all landed in wave 2; the CLAP gate and the duplicate-module convention remain)
* **Doc statements that had gone false** (product-surface-6). Corrected where
  the fixer owned the file: `docs/RELEASE.md` no longer says the Authenticode
  signing is "wired and tested", it says plainly that none of it has ever run
  against a real certificate and that "wired" is not "tested"; `docs/CI.md`
  records that the .pfx route was dead until today. Four more corrections are
  written out ready to apply but live in files nobody owned this pass:
  `docs/CONFIG.md`'s "hardcoded by decision" row for `canonical_prefix`,
  `docs/LOOPBACK_API.md`'s missing `POST /ytdl/fetch` row, SPEC.md's two
  stale "current state" paragraphs, and CLAUDE.md's missing `publish_latest`
  line. All four landed in wave 2 (2026-08-21), each written from the code
  rather than from the recommendation: the `canonical_prefix` row now reads
  "site data since 2026-08-17" and says the old text had been wrong for four
  days, the `/ytdl/fetch` row was verified against `broll_server.py`'s
  dispatch before it was written, SPEC.md's "Current state (verified)"
  heading is now marked HISTORICAL with the three claims that stopped being
  true in week one, and CLAUDE.md states the CI-builds/this-rig-signs policy
  and `publish_latest.py`'s four refusals in one place.
* **`docs/APPLIANCE_INSTALL.md` tells the customer the first-run wizard does
  not exist** (product-surface-4), which was wrong the day it was written and
  is wronger now that `/setup` opens anonymously on a fresh local-mode
  appliance and the storage task behaves differently (CR-57). FIXED in wave 2
  (2026-08-21), rewritten from `setup_routes.py` and `setup_engine.py`: step 2
  now says why the three bind-mount SOURCES must still be created by hand
  (Docker invents a missing one root-owned, which uid 3000 cannot write),
  step 3 documents the wizard as it is (the seven-step ordered table, the five
  optional steps, `setup_tasks` persistence and resume, checks that never dial
  out speculatively, `require_setup_access`'s fail-closed local-only anonymous
  window), step 5 records that the editors/software/snapshots CHECKS have been
  real since 2026-08-18 and only the DOING is owed, and the doc header no
  longer claims WP D never landed. One genuine NOT YET TRUE survives, and is
  accurate: step 4's tailnet sign-in, because WP B is not built and an
  operator still signs `tailscaled` in over `docker compose exec`.
* **Skips that hide an un-run gate** (product-surface-7). PARTIAL:
  `run_all_tests.ps1` now parses each suite's skip count into the summary
  table and prints a footer whenever anything skipped, saying that a skip is
  not a pass and naming `-rs`. The CLAP artefact gate itself still runs on
  exactly one machine in the world, because checking in a fixture is a
  decision about what binary data enters the repo.
* **Same-named modules with different contents** (product-surface-8:
  `crash_report.py` in two components differs from line 1 and is under no
  parity test, sitting beside byte-identical vendored copies that are).
  DEFERRED: the header convention and the enforcing test span three files in
  two other territories.

### CR-66 - deliberately deferred, with reasons
Nothing here was missed. Each was looked at and declined for cause, and each
needs an owner decision, a live spike, a measurement, or a two-sided change
that has to land atomically.

**The design items this pass deliberately did not attempt:**

* **`sync-safety-1` - lane A has no upload ledger.** `copy --ignore-existing`
  with no memory of what this machine has already sent re-uploads anything
  MOVED on the NAS, from every editor who still holds it at the old path.
  CR-44 taught lane B to tolerate a reorganisation; nothing stops lane A from
  undoing it. That is a design decision (what the ledger is, where it lives,
  what a rebuild costs), not a patch, and it is the largest open sync-safety
  item in this ledger.
* **`data-model-2` - the machine's ROLE is still minted from the PERSON.**
  `DASH_ADMIN_USERS` decides wired against remote and both the companion and
  the wizard obey it, while `machine_state.mode` is the per-machine fact
  everything else now keys on. CR-49 made the GATES per machine; the
  AUTHORITY is still per account. Making the registry the authority is
  `docs/MULTI_BASE_RIG_PLAN.md` work.
* **`trust-model-1` - identity tokens are unrevocable 30-day bearers** with
  no refresh: too long to revoke, too short to live with. A revocable
  identity needs a token store, a refresh path and a companion that
  understands both. A security-model change, not a fix.
* **`release-pipeline-9` - dashboard OTA hinges on a mutable `:1` image tag**
  that the vendor has tagged exactly once, and a lock change silently
  disables OTA for every customer. Needs a tagging policy decision before any
  code.
* **`data-model-8` - `canonical_prefix` and `tree_name` are live-editable on
  the dashboard but install-time constants** in every companion and in the
  music service. Editing them today is a fleet-wide breakage with no
  migration: either the dashboard refuses the edit once machines exist, or
  the edit needs a rollout path.
* **`data-model-6` - the per-machine `editor_prefs` migration (v24 WP7)
  re-keyed a table nothing reads or writes.** Dead weight rather than a
  defect, and removing a shipped migration is its own risk.

**Deferred within a theme, reason recorded in the entry that names it:**
`sync-safety-7` (track-renames, needs measurement against the bundled rclone;
CR-47); `trust-model-4` (editor lanes verify no NAS host key: the fix spans
the dashboard, both installers and the companion and must land as one change;
now documented in `docs/SERVER.md`, and the compose comment that claimed the
opposite was retracted in wave 2, CR-61); `trust-model-6` (one secret
underwrites six trust relationships: HKDF-per-purpose changes a wire format
verified in four apps, and the `_PREVIOUS` overlap touches a dozen call sites
in other territories, so it wants one dedicated change across
dashboard+broll+music+ytdl with docs/SECRETS.md in the same pass);
`trust-model-8` (dashboard-to-TrueNAS REST disables TLS verification: needs a
`[nas] tls_fingerprint` and a fail-closed rule in another territory);
`trust-model-9`'s CSP (four apps, CR-54); `release-pipeline-8` (the downgrade
floor is never RAISED: wave 2 taught `publish_feed.py` to refuse a floor
DROP, but every record still carries 0.0.0 unless an operator types one, and
the real fix is a tracked MIN_VERSION constant read by three signers);
`product-surface-8` (the duplicate-module header convention); and
`release-pipeline-2`'s reconciliation of the two publish paths, which is a
release-policy redesign.

**Eight items this list used to carry were closed after all**, by the wave 2
pass on 2026-08-21, and are described in the entries that own them:
`ytdl-web-5` (the pin is read before anything is probed, CR-53),
`dash-core-7` (`secrets_boot` on the console entry point, CR-57),
`data-model-7` (the ytdl download lease is keyed on `(editor, machine_id)`,
CR-49), `ops-efficiency-6` (the lifespan watchdog and the corrected `ok`,
CR-62), `ops-efficiency-8` and `ops-efficiency-9` (the media-tree stat cache
and the log window, CR-62), `product-surface-3` (first-customer data out of
the vendor deploy defaults, CR-61) and `product-surface-4` (the appliance
install doc, CR-65). Deferring for cause is not declining forever.

### CR-67 - the seams still open after wave 2
Wave 1's eleven fixers on disjoint territories left thirteen seams: a fix
whose other half sat in a file nobody held. Wave 2, six engineers on
2026-08-21, closed all but a residue. What CLOSED, one line each:

1. `companion/app.py` owes the halt three calls (CR-48) - closed in wave 2
   (2026-08-21): the `halted` predicate, `halt_folder_ids()` and
   `release_for_halt()` on BOTH release paths, with seven regression tests.
2. b-roll fleet ingest 403s a `cce1` holder (CR-55) - closed in wave 2
   (2026-08-21): `fleet_auth`'s stamp plus one `require_fleet_caller`, and
   `BrollGate` stripping and re-stamping the header.
3. `tools/sign_release.py` and `installer/build_editor_package.ps1` can
   PRODUCE a `min_version > version` record (CR-52) - closed in wave 2
   (2026-08-21): a refusal in `sign_release.main()` before the release key is
   read, and two gates in the package builder, the first before PyInstaller
   runs so a stale env var costs seconds and not minutes.
4. `dashboard/app.py`'s `secrets_boot.ensure_secrets()` on the console entry
   point, and `/fleet/halt` in `login_gate` (CR-57, CR-55) - closed in wave 2
   (2026-08-21), both stale docstrings corrected with it; the carve-out is
   exact-path AND method GET AND a verified companion credential, so the
   admin's POST still needs a session.
5. `DASH_TRUSTED_PROXIES` and the json-file `logging:` cap in the compose
   templates, plus `run.sh --no-access-log` (CR-61) - closed in wave 2
   (2026-08-21), with the golden fixture regenerated in the same change and
   `COMPOSE_ENV_ONLY_IN_DICT` emptied.
6. `dashboard/api.py` and `collector.py` still lay down the ENV template
   folders and shared-asset list (CR-58) - closed in wave 2 (2026-08-21),
   along with the ASGI title; an empty read deliberately keeps the previous
   list, because an empty shared-folder set is the B16 unshare shape.
7. `ui.py` and `admin_assignments.html` grey a wired ACCOUNT, and the
   `/download/<platform>` 404 names a vendor-internal script (CR-49, CR-59) -
   closed in wave 2 (2026-08-21): the column is greyed per `(editor,
   machine)`, `partial_toggle` took the same `?machine=` refusals its JSON
   sibling already had, and the 404 speaks to the editor first and then names
   `publish_latest.py --kind onboard`.
8. `tools/publish_feed.py` owes `--allow-replace` and the min_version floor
   refusal (CR-59) - closed in wave 2 (2026-08-21); identical bytes are
   deliberately not a replacement, so a re-run after a failed upload works.
9. `companion/app.py`, the smaller ones (CR-51, CR-50, CR-66) - closed in
   wave 2 (2026-08-21): the open project reaches `describe_latest()`, the
   diagnostics builder reads lane C's cached status instead of `check_once()`
   and labels it "[last poll, not a fresh sweep]", the media-tree stat cache
   landed with a 900 s TTL on the PRESENT side (a tree that never notices a
   deletion would be worse than a slow one), and the log window went from
   20 MB to 55 MB with a rotation note written at the head of each new file.
10. `broll/web/app/ingest_batches.py` should refuse to flip a video off
    `ingesting` with no segments row (CR-54) - closed in wave 2 (2026-08-21):
    a 409 `no_result`, placed AFTER the outside-root 400 and the size checks
    so those keep their meanings and their priority.
11. The docs still owed (CR-65 and the entries that name them) - closed in
    wave 2 (2026-08-21): SYNC_SAFETY, RESOLVE_EDIT_SAFETY, CLIENT_FOLDERS,
    CONFIG, BACKUP_RESTORE with `server/publish_db.py`'s advice text,
    LOOPBACK_API, SPEC.md, APPLIANCE_INSTALL, `site.example.toml` and
    CLAUDE.md, plus three docs that had no `docs/README.md` row at all.
12. `companion/config.example.toml` should document `lane_c_settle_seconds`
    (CR-62) - closed in wave 2 (2026-08-21), with the
    `project_rotation_seconds` text amended to say the full 600 s is
    load-bearing ONLY under the `rotate` scheme. The key is owned by
    `sequencer.py`, not `config.py` DEFAULTS, and a new test in
    `test_config.py` pins that deal rather than letting the parity tests
    force it into DEFAULTS.
13. `syncthing_client.py` wants a per-call timeout (CR-62) - closed in wave 2
    (2026-08-21). Its `maxAge` half is NOT closed: see below.

**Still open after wave 2.** Shorter, and every item now wants a decision, a
measurement or a template owner rather than a mechanical mirror.

* **`companion/sync/syncthing_admin.py`'s `maxAge` (30 d) still disagrees
  with the server and the dashboard (365 d)** (CR-48, ledger R5). It is the
  one wave-1 seam no wave-2 engineer could take, because taking it means
  choosing a number: reconciling is the companion's move, since lowering the
  server's would REDUCE protection.
* **CR-62's real idle fix is still owed**: the per-project proxy-tree
  signature published in the selection response so a pass can be SKIPPED
  entirely (the collector plus `api.py`), the NAS-reachability pre-probe with
  a distinct "offline" lane state (which changes what the tray classifier and
  the fleet grid render), and moving the completion pass onto its own thread
  and connection. The idle backoff and the per-call timeout bought headroom;
  they did not remove the work.
* **Nothing in the product says a NAS snapshot schedule is MISSING**
  (sync-safety-6, CR-48). Attempted in wave 2 and declined for reach, not on
  the merits: `TrueNASClient.list_snapshot_tasks` exists and the Setup
  wizard already consults it, so the data is surfaced somewhere, but a fleet
  banner needs `base.html` or the fleet template plus a cached background
  poll, and `health.py` is deliberately pure rollup logic with no I/O so a
  TrueNAS timeout never sits in front of the container healthcheck. Wants its
  own change, with the template owner.
* **Two new dashboard knobs are undocumented, and one is deliberately not a
  first-class key.** `DASH_COLLECTOR_WATCHDOG_SECONDS` (0 disables) and
  `DASH_COLLECTOR_WEDGED_SECONDS` are read straight from `os.environ` in
  `dashboard/app.py` rather than through `settings.py`, because `settings.py`
  and `docs/CONFIG.md` were other territories at the time; they belong in
  both. `DASH_ACCESS_LOG` is a `run.sh`-only knob by choice: making it
  first-class means a row in both compose templates AND in
  `compose_config()`, or `test_safety`'s env-key parity fails.
* **This studio's own `site.toml` owes a `[broll]` block.**
  `creators_shares` now has an EMPTY product default and the studio's
  historical `mofa-disaster` survives only through one transitional branch, a
  manifest with no `[broll]` TABLE AT ALL. Writing ANY `[broll]` key ends
  that fallback, so `creators_shares` and `archive_creators_dir` go in
  together or the b-roll creators share empties itself. `docs/SERVER.md`
  spells out both lines. The same trap runs in reverse:
  `site.example.toml` carries an UNCOMMENTED `[broll]` header, so copying it
  yields the empty product default, which is right for a new site and wrong
  for this one.
* **`docs/APPLIANCE_INSTALL.md` keeps one genuine NOT YET TRUE**: step 4's
  tailnet sign-in. WP B is not built, the tailscale service runs a bare
  `tailscaled`, and an operator still signs it in over `docker compose exec`.
  That is an accurate doc of an unbuilt thing rather than a doc defect, and
  it goes when WP B lands.
* **Two test results disagree across the wave and must be reconciled before
  anything is built.** `server/tests/test_cross_component.py::test_the_done_video_row_falls_back_field_by_field_on_both_sides`
  raises StopIteration because it can no longer find its `db.set_video(...
  dl_state='done' ...)` call in `ytdl/web/ytdlweb/routes_fleet.py`, which
  wave 2 rewrote for the per-machine lease. It was already failing before
  that engineer started, so it is a cross-component grep gone stale rather
  than a regression, but it is RED and nobody owns it. Separately, one
  engineer's mid-wave dashboard run saw two `test_collector.py` tests and
  `test_packages.py::test_installer_download_route` fail; all three are in
  files another engineer was editing at that moment, and all three were green
  on that engineer's final run. Re-run the server and dashboard suites on the
  merged tree.

**Ordering, unchanged and now with a second reason:** deploy the dashboard
before the companions. ytdl migration 010 (`jobs.claimed_machine`, schema
v10) runs on the live `ytdl.db` at the next dashboard boot, is one idempotent
ALTER, and stays inert until a companion sends `machine_id` on its claim, so
the dashboard can go out first exactly as the per-machine plans required.
Everything the pass declined on the merits, rather than left as a seam, is in
CR-66 with its reason.

## Resolve's launch window, and BPG's INI escaping (CR-68, CR-69, 2026-08-21)

Two owner reports the evening of 2026-08-21, both fixed as **companion
0.9.45** and **SHIPPED the same evening** (commit `4d3f4a3`): dashboard
0.7.5 applied over the air (carrying the whole 0.9.44 pass's dashboard
half; live 0.7.3 -> 0.7.5, runtime id unchanged), then CI-built companion
0.9.45 + installer 1.0.36 published to the vendor feed with
`publish_latest.py --make-current` and pulled into the studio dashboard as
current for windows AND macos; the base rig upgraded in place. Every
editor is offered 0.9.45 on their next check. Suite after: companion 4457
passed / 2 skipped. The guard was also ported the same evening into the
MulticamPipeline tools (committed there) and the Resolve MCP server
(`src/utils/resolve_connect.py`, uncommitted alongside that repo's
earlier in-flight work).

### CR-68 - a client polling during Resolve's launch kills scripting for the session - FIXED in repo
**Symptom, every editor, for months.** Companion already running, Resolve
launched afterwards: Resolve hangs 10-20 s during launch, then no scripting
client on the machine can connect (`scriptapp("Resolve")` returns None, the
tray says "running but isn't accepting scripting connections") until the
editor closes Resolve, closes the companion, opens Resolve and THEN the
companion. The MCP server and the MulticamPipeline "Timeline cards" tool
trip the same thing.

**Mechanism, proven from Resolve's own log** (`Support/logs/
davinci_resolve.log`, 14:23 and 15:03 on 2026-08-21, both followed by the
dance and a clean relaunch). Resolve's scripting is brokered by a child
process, `fuscript.exe`, spawned 90-470 s into Resolve's launch (after the
project library), listening on TCP **1144**. Resolve then connects to it and
registers as the "HostApp"; a client connects to 1144 and is handed
Resolve's own port (49152 here). **The server exits when its last connection
closes.** A client that connects between "server started" and "Resolve
registered" gets no host, disconnects, and takes the server with it:

    Started script server: 30320 / Failed to connect to script server, retrying
    Started script server: 27240 / Failed to connect to script server, retrying
    Started script server: 8392  / Failed to connect to script server
    Script server log:
    90.859 Script Server Started
    91.125 Incoming connection      <- the companion's 3 s watcher poll
    91.125 HostApp create
    91.234 HostApp destroy
    91.234 Script Server Terminated: done: 1, err: 0

Three attempts (the "hang"), then Resolve never retries, so the API is dead
for that process's lifetime. The TCP table on the base rig showed 24
TIME_WAIT connections to 1144 in one two-minute window: the companion's
threads connecting and dropping on every poll. It is a race, not a
certainty (the 15:43 launch that day connected fine with the companion up),
which is why it read as flaky for so long. This is the same class of
failure R12's "stale client wedges the new Resolve" entry described from
the other side; `_maybe_recover_stale_bridge` restarts the companion when
its Resolve exits, and that restart is itself a fresh poller that can land
in the next launch's window.

**Fix: never connect until Resolve has registered.** New
`companion/src/ccsync_companion/script_server.py` reads the kernel's TCP
table (Windows `GetExtendedTcpTable` v4+v6 plus a Toolhelp32 process
snapshot, ~6 ms, no subprocess; macOS `lsof -F`, untested against a live
Mac as the studio Mac was unreachable) and answers READY (a LISTEN on 1144
owned by `fuscript`, and an ESTABLISHED connection to 1144 owned by
fuscript's PARENT process), STARTING (the listener with no such host), or
UNKNOWN (no listener, foreign process on the port, unreadable table, any
doubt). `resolve_bridge.connect()` asks before touching fusionscript and
returns None on STARTING only; everything else behaves exactly as before
(fail OPEN by construction). A new `STARTING_MESSAGE` ("DaVinci Resolve is
starting up") replaces the NO_SCRIPTING advice during the window - that
advice was telling editors to do the one dance that worked, because the
advice-giver was the thing breaking it. One INFO line per window, not one
per poll. Tests: `tests/test_script_server.py`,
`tests/test_resolve_bridge_launch_window.py`; conftest pins the probe to
UNKNOWN so no test reads the developer's machine.

**Proven live on the base rig, 2026-08-21 16:49 and 16:52** (two threads
calling `scriptapp("Resolve")` every 0.5 s, Resolve launched by the
harness, TCP table sampled at 50 ms, companion stopped so the harness was
the only poller). WITHOUT the guard: three `Started script server` lines
(16:49:40), each listener alive 50-100 ms before the harness's connection
took it down, `Failed to connect to script server` three times, the
harness never connected in 38 polls, scripting dead for the session.
WITH the guard, same harness: listener up at +15.9 s, Resolve registered
at +16.4 s (a 0.5 s window), both threads held off (8 skips), connected at
+16.8 s, ONE `Started script server` line and no failure. Deterministic
both ways on this rig.

**0.9.45 was not enough - the second pass, same evening (companion
0.9.46, SHIPPED 18:31: feed current for windows + macos via publish_latest
--make-current, pulled into the studio dashboard, base rig upgraded).** Two launches with 0.9.45 running (17:56 and 17:57) died the old
way, and the companion log shows why: no "holding off" line, because
`connect()` probed BEFORE the listener existed, got "no listener", failed
OPEN and called `scriptapp()` - and `scriptapp("Resolve")` with no server
present does not fail fast. Measured in the run #1 harness log: **4.0 s per
call, 8 s when a second thread queues behind it**, retrying its connect the
whole time. So a client that "just checked" is inside a connect loop at the
moment the server appears, and no snapshot taken before the call can see
that. The run #2 harness had passed only because its guard ALSO skipped on
"no listener". Fix: a fourth state, ABSENT, and `connect()` proceeds only on
READY (or UNKNOWN = the probe itself is unusable); STARTING and ABSENT both
hold. `ready_to_connect()` is the one predicate, and the two ports use it
(`not ready_to_connect()`, never `is_starting()`). The other product that
killed the 17:42 launch (two connections 0.08 s apart) was the pre-patch
Timeline Cards process, restarted at 17:43:30 by the owner.

**Third pass, 0.9.47 (shipped 19:20, feed current both platforms, base rig
on it):** the owner's first 0.9.46 launch worked, but within seconds of
quitting Resolve the tray said "running but isn't accepting scripting
connections - restart the companion first". That explainer jumped from
"Resolve.exe exists, no script server" straight to the dead-scripting
verdict, which is wrong for the minutes around a launch (server spawned
90-470 s in) or a quit (Resolve.exe lingers; the process probe is cached 30
s). Now `NO_SERVER_MESSAGE` ("starting up or shutting down") with a
10-minute grace clock, reset by any successful enumeration; the dead-server
advice leads with "quit and reopen Resolve" since the companion is no
longer what breaks it.

**Not done / for the owner.** (a) macOS `lsof` path untested against a
live Mac. (b) The Resolve MCP server's copy is in its working tree,
uncommitted, next to that repo's earlier in-flight mutex work; restart the
MCP server to pick it up. (c)
`resolve_prefs.resolve_is_running` counts the Blackmagic Proxy Generator
(`Resolve.exe -pg`) as Resolve, so "running but not accepting scripting"
appears while only BPG is up; cosmetic, left.

### CR-69 - BPG watch folder with a non-ASCII name is written garbled, never watched, and re-added every launch - FIXED in repo
**Symptom** (base rig, 2026-08-21, screenshot): the companion launched the
Blackmagic Proxy Generator with a watch folder listed as `ç¬¬ä¸‰å±†...` for
a CJK shoot name; BPG showed it, found no folder, and did not start.
`ProxyGeneratorSettings.ini` held two copies of it.

**Mechanism.** BPG is Qt 5 with a Latin-1 INI codec. `bpg.ensure_watch_
folders` wrote the path's UTF-8 bytes raw; BPG read them as Latin-1, showed
the mojibake, and on exit rewrote the entry as `\xe7\xac\xac...` (each byte
as Qt's `\xHH`). The companion's parser did not understand `\x`, so the next
launch saw the folder as uncovered and appended another copy.

**Fix.** `_qt_escape_text` writes non-ASCII as Qt's own `\xHHHH` UTF-16
code units (surrogate pairs for astral characters, and Qt's
escape-the-next-hex-digit rule, because its reader is greedy);
`parse_watch_folders` decodes `\x` escapes and rejoins surrogates; and the
one case the function now rewrites existing text is dropping entries whose
Latin-1 encoding is the UTF-8 of a folder we want - i.e. only our own past
damage, never an editor's `P:\Café`. Tests: `tests/test_bpg_qt_escape.py`.
The live base-rig INI still carries the two garbled entries until the next
BPG launch from a 0.9.45 companion cleans them.

### CR-71 - borrowed files are not counted in the borrower's MEDIA column - OPEN by design (v1), 2026-08-24
**Symptom.** A project that shares a folder from another project
(SHARED_FOLDERS_PLAN.md, built 2026-08-24) shows the borrowed clips nowhere
in its own MEDIA figures: the presence manifest reports files under the
project that OWNS the directory, and `_selected_project_rels` deliberately
excludes borrowed rels from the manifest scan scope (they would otherwise
also feed proxy generation scope on editors).

**Why it is deferred, not fixed.** Reporting borrowed files under the
borrower needs a per-file attribution split in `manifest.py` and a schema
addition on the dashboard side; SHARED_FOLDERS_PLAN.md carries it as WP6
(out of scope for v1). The sync itself is complete and visible: the borrowed
folder's rows appear on the LENDER's project page, and the borrower's page
lists the link under SHARES FROM.

### CR-70 - the tray menu sometimes opens late (variable delay, not every click) - OPEN, investigated 2026-08-21
**Symptom.** Right-clicking the tray icon sometimes shows the menu a
fraction of a second to many seconds late; survived the 2026-07-26 fixes and
the 2026-08-17 `tray_native` rewrite. Full investigation:
`docs/TRAY_MENU_LATENCY.md`.

**Primary cause.** The tray's window procedure is a ctypes callback and
needs the GIL; every fusionscript call holds the GIL for its whole native
duration, and a single call takes as long as Resolve's main thread takes to
service it (ms idle, seconds during playback/conform/render/modal). The
existing mitigations (`wait_while_menu_open`, `_sweep_yield`, the poll
cache) protect the OPEN menu and cut the number of calls per poll; none
bounds one call, and the watcher makes several every 3 s. The base-rig log
proves the GIL hold: six `_note_wedge` warnings 2026-08-19..21 (calls of
33-91 s) are each timestamped at the moment the call RETURNED, not at the
30 s mark the waiter timed out at. Sub-30 s stalls are recorded nowhere.

**Secondary.** GC pauses (unmeasured), `SHAppBarMessage` into Explorer on
the click path, working-set trimming, possible EcoQoS throttling; plus two
backend defects seen in the log - `_show_menu` has no re-entry guard
(GetLastError 1446 when a queued second click is dispatched inside the open
menu's modal loop) and clicks dispatched after the window is destroyed
(1400).

**Recommended order.** (1) instrument - DONE in repo 2026-08-21:
`tray_native._pump` stamps `GetTickCount() - MSG.time` per click and
`_show_menu` logs one WARNING ("tray menu opened late: the click waited N ms
in the queue and the menu took M ms to build (Resolve call in flight: ...;
gc counts ...)") when either passes 150 ms, DEBUG otherwise; tests in
`test_tray.py`. Ships with the next companion build; (2) re-entry/dead-
window guard in `_show_menu`; (3) move fusionscript into a killable child
process, the `music_worker` pattern, which also delivers the per-call
timeout the bridge cannot have in-process. Nothing built yet.

## The wired rig's empty ytdl picker (CR-72, 2026-08-24)

### CR-72 - a base-only editor cannot pick any project in the youtube downloader - FIXED, shipped 2026-08-24 (dashboard 0.7.7 OTA)
**Symptom** (owner, 2026-08-24): on a wired/base rig the ytdl page's project
dropdown is empty, so no download can be started from it at all.

**Mechanism.** The picker is `ytdlweb/projects.ticked_projects`, which reads
the dashboard's `selections` table: "the projects you sync are the legitimate
destinations" (REQ 7). But a base rig syncs nothing and CAN sync nothing -
CR-28 made the dashboard 409 any tick on a base-only account - so for an
editor whose every machine is wired, the ticked set is empty by construction,
forever. The two rules were individually right and jointly a lockout.

**Fix** (`ytdl/web/ytdlweb/projects.py`). When the requesting editor is
base-only - at least one known machine, every one reporting mode `base`, read
from `machine_state` with `editor_media_project` as the pre-v22 fallback,
same precedence as the dashboard's `machine_modes` - the picker offers EVERY
active project, ordered by label: a wired machine works directly off the
whole NAS tree, so every project is a legitimate destination for it.
`resolve_project` goes through the same path, so the server-side destination
check widens with the picker. Deliberately per-person and base-ONLY: a person
with one wired and one remote machine keeps the ticked list, because a job
they start is claimed by the requesting machine's own companion, and a
download into a project that machine does not sync would be a folder nothing
manages. An account with no known machines, or an older dashboard without the
mode tables, answers "not base-only" and behaves exactly as before. Tests in
`ytdl/web/tests/test_api.py`. Needs a dashboard deploy to reach the fleet.

### CR-96 — CR-72 follow-up (2026-08-30): the picker's per-PERSON rule still starved a mixed account's wired machine — BUILT in repo 2026-08-30 as dashboard 0.7.26 (half 1) and 2026-08-31 as companion 0.9.64 (half 2), NOT YET SHIPPED
Owner, 2026-08-30: *"I can still only select /animals as a destination on the
base rig."* CR-72's fix was deliberately per-person and base-ONLY: a mixed
account (a wired base rig and a remote laptop -- the owner's own shape, the
same one CR-95/dash-admin-8 above is about) kept the ticked list on EVERY
machine, on the reasoning that a job a remote machine's companion claims must
land in a project that machine actually syncs. Right for the remote half,
wrong for the wired one: sitting at the console of the wired machine itself,
`_base_only` still answered False for the person as a whole and handed back
the same stale ticked list CR-72 first found empty.

**Fixed, in two independent halves that both widen `ytdlweb.projects
.ticked_projects` / `resolve_project` to every active project:**

1. **Per EXECUTION PLACE** (`local=False`). When the download will run on the
   server -- the SPA's "on this machine" toggle unticked, or the fleet flag
   off -- no machine's companion claims the job, so no machine's sync plan is
   a constraint; any active project is a legitimate destination, the same
   argument CR-72 already made for a base-only editor. Threaded end to end:
   `GET /api/projects?local=`, `NewJob.local` / `NewUrlJob.local` (default
   `True`, so an old client is unchanged), and `resolve_project` takes the
   same flag from the job payload the picker was shown, so the two can never
   disagree. This half needs no new information from anywhere and is
   complete.
2. **Per MACHINE** (`machine=<hostname>`, `projects._wired`). Same
   `machine_state`/`editor_media_project` precedence `_base_only` already
   reads, narrowed to ONE machine instead of requiring all of them. Built and
   tested with a `machine=` query param supplied directly -- but **nothing in
   the fleet can supply a real one yet**: the companion's loopback
   (`GET /ytdl/capabilities`, `GET /status`) has no hostname or wired-mode
   field on it today (checked; `capabilities()`'s dict is `ok, reason,
   editor, ytdlp_version, template_version, sidecar_version,
   scope_qualities, free_bytes` -- `Deps.is_base_rig` exists internally and
   is not exposed), and companion is out of scope for this change. So the
   SPA never sends `machine=`, and a person on a mixed account standing at
   their OWN wired console with "on this machine" still ticked keeps seeing
   the ticked list, exactly as before this entry, UNTIL either the companion
   gains that field or they untick "on this machine" (half 1 above then
   widens it, because on a wired machine a local write and a server write
   land in the same place anyway).

**Residual CLOSED 2026-08-31 (companion 0.9.64), which completes half 2.**
`ytdl_executor.capabilities()` now answers `machine` (`platform.node()` -- the
hostname `machine_state`, `selections` and every lane report are already keyed
on, so the server matches the string exactly) and `mode` (`machine_mode(cfg)`,
app.effective_mode's config-only rule per CR-88; diagnostic, because the
server re-derives wiredness from `machine_state` and will not let a client
that claims "base" widen its own picker). The SPA asks once at BOOT
(`probeLocalMachine`, bounded by `PROBE_MS`) and puts the hostname on
`GET /api/projects`.

Three things that deliberately keep the old behaviour, because a missing
`machine` reads as "unknown" and unknown is not wired: no companion
listening, a companion too old to carry the field, and the fleet's
local-download flag off. The last is not merely tolerated but REQUIRED -- the
page must not touch 127.0.0.1 at all with the feature off (`test_with_the
_flag_off_the_page_never_looks_at_the_loopback`), and it does not need to,
because half 1 already widens a server-side download. The probe is gated on
`localWanted()` for exactly that, and re-runs when the switch is ticked back
on so the first flip does not need a reload. It is NOT gated on the
companion's `ok`: a tray app that cannot take the download (old yt-dlp, no
ffmpeg, terms unaccepted) is still this computer, and a wired rig works off
the whole tree whoever ends up fetching.

Tests: `ytdl/web/ytdlweb/projects.py` (`_machine_modes`, `_wired`);
`ytdl/web/tests/test_api.py::test_the_wired_machine_of_a_mixed_account_is
_offered_every_project` -- the `machine=`/`local=` params reached the route
UNTESTED on 2026-08-30 and are what the picker now runs on, so this pins all
four cases (wired, remote, unknown machine, none named) and that
`resolve_project` widens identically, since a picker offering what the POST
then refuses is the worse bug;
`ytdl/web/tests/test_static_app.py::test_the_picker_tells_the_server_which
_computer_is_asking` (the client half, including the three negatives);
`companion/tests/test_ytdl_executor.py` (the two new fields, and
`machine_mode`'s safe direction: anything that is not exactly "base" is an
editor machine, because a machine wrongly called wired would be offered
destinations it does not sync).

One test-harness note worth keeping: boot now makes a loopback call of its
own, so `test_static_app`'s dispatch invariants ("one probe, one POST, no
retry loop") measure from the end of boot (`dispatchedBy` / `_callsAtBoot`)
rather than from the start of the page. The invariant is unchanged; what it
counts is now scoped to the dispatch that it is about.

Needs BOTH a dashboard deploy and a companion release to reach the fleet --
and in that order, as ever. An editor below 0.9.64 gets half 1 only, which is
the behaviour this entry described as partial.

### CR-97 — a folder box for pasted links, reversing the 2026-08-11 call — BUILT in repo 2026-08-30 as dashboard 0.7.26, NOT YET SHIPPED
Owner, 2026-08-30: *"there should be a way to manually input the name of the
folder/bin you want links you are downloading to go into."* This reverses
2026-08-11's own call (`routes_api.py`'s `NewUrlJob.folder` had sat ACCEPTED
AND IGNORED since then, with a comment naming the two-reversal history from
that day) -- so the field is not new, it is reconnected.

Blank (the default) is still `URL_JOB_TERM_DIR` -- clips loose in
`<project>/Youtube/`, exactly as every paste has landed since 2026-08-11. A
name given is reduced through the SAME `config.safe_term_dirname` a search
topic is (YTDL-28's traversal / Windows-reserved-name / 255-byte rules) and
becomes the job's `term_dir`, which every downstream reader already treats
generically for either job kind -- `worker._phase_download`'s own docstring
already said "neither goes deeper than one level under Youtube/, which is
what the companion's youtube_import watcher walks" (companion untouched;
confirmed by reading `youtube_import.py`'s `_collect`, which walks exactly
that one level plus the loose root). `db.ledger_where` / `folder_label` /
the history panel's destination line all key off `term_dir` already, so
nothing there needed a change either.

SPA: `#urlfolder`, beside the paste box, remembered per browser
(`ytdl.url_folder`) like the destination project is. Tests:
`ytdl/web/tests/test_api.py`
(`test_a_folder_box_names_the_jobs_term_dir`,
`test_a_blank_or_whitespace_folder_still_lands_in_the_youtube_root`),
`ytdl/web/tests/test_static_app.py`
(`test_the_paste_box_has_a_folder_field_again`). Needs a dashboard deploy.

### CR-73 - server YouTube downloads crawled at ~1.8 MiB/s and some ended "The downloaded file is empty" - LIVE-FIXED on the NAS + hardened in repo, 2026-08-24
**Symptom** (owner, 2026-08-24): a server-side ytdl download at 18.3% doing
1.76 MiB/s; the same job's earlier clip failed outright with "ERROR: The
downloaded file is empty" out of yt-dlp's HLS fragment downloader.

**Mechanism.** The container boots with `DASH_SITE_YOUTUBE_UNBLOCK=1`, and
run.sh installs `requirements-unblock.lock` (the GPLv3
`bgutil-ytdlp-pot-provider` plugin, deliberately not baked into the vendor
image) into /venv at boot - non-fatally, by design. On BOTH recorded boots of
the live container that pip install failed ("PyPI unreachable?"), almost
certainly because it runs in the container's first seconds, before its
network/DNS is usable. Result: the bgutil sidecar ran for days with nothing
talking to it - `yt-dlp -v` said `[pot] PO Token Providers: none`. Without a
GVS PO token YouTube skips the https formats (SABR-forced, no URL) and leaves
only the throttled HLS ladder; fragments crawl and some videos produce empty
files. Diagnosis line to remember: `docker logs <dashboard> | grep run.sh`
plus the DEPLOY.md `-v` probe looking for `PO Token Providers`.

**Live fix** (2026-08-24): installed the lock into /venv by hand, wrote
run.sh's stamp, restarted the container. Verified: the exact clip that
failed empty now downloads 380 MiB in 18 s (20.6 MiB/s), with
`[pot:bgutil:http] Generating a gvs PO Token` in the log.

**Hardening in repo**: run.sh retries the unblock install (5/15/30 s
backoff) before giving up, which covers the boot-time network gap. Note the
residual: every image update resets /venv, so a site whose network is down
for longer than the retries still degrades until the next container boot.

**RESIDUAL CLOSED, and the diagnosis was wrong for image mode (CR-84,
2026-08-26).** The failure this entry blamed on a boot-time network gap was,
on the v0.7.11 image, `[Errno 13] Permission denied` on
`/venv/.../yt_dlp_plugins`: in image mode /venv is an `a+rX` image layer and
the container is uid 3000, so that install could never have succeeded, and
the retries only repeated it. run.sh now installs into `/data/unblock-site`
with `--no-deps --target` in image mode and puts it on PYTHONPATH, and a
failure prints pip's own error rather than "PyPI unreachable?". And note the
rule CR-84 adds: **there are THREE yt-dlp locks, and
`dashboard/deploy/requirements.lock` is the image's.**

### CR-74 - long server downloads crawl at 3-4 MiB/s even with the PO token working - FIXED, shipped 2026-08-24 (dashboard 0.7.8 OTA)
**Symptom** (owner, 2026-08-24, after CR-73's live fix): job 22's short news
clips landed in seconds, but a 36-minute 562 MiB clip sustained only 3-4
MiB/s (the SPA read 2.67 MiB/s), forty minutes after the same container
measured 20.6 MiB/s on CR-73's verification clip.

**Mechanism.** Even with a GVS PO token, YouTube SABR-forces the https
formats away (their URLs are withheld from the player response), so nearly
every server download walks the HLS m3u8 ladder - and yt-dlp fetches its
fragments ONE at a time, at whatever pace YouTube gives a single connection.
Short videos ride hot CDN caches; long ones get per-connection pacing.
Isolated live in the deployed container against the same clip and format:
sequential 23 MiB/s on a short video, 3-4 MiB/s sustained on the long one,
53 MiB/s with six fragments in flight. Not the pipe (raw curl 51 MB/s), not
the pool (writes to /projects at 27 MiB/s), not the worker process (8% CPU).

**Fix** (`ytdl/web/ytdlweb/vendor/downloader.py`): `concurrent_fragment_
downloads` = `fragment_jobs()`, default 6, env-tunable via
`YTDL_FRAGMENT_JOBS`, bounded 1..16 (1 restores the old behaviour; the
ceiling keeps one download from looking like bulk automation). The
companion's local-download argv is deliberately untouched: editors get real
https formats via player_client=web_safari (CR-39) and a companion change is
a fleet release. Needs a dashboard deploy.

### CR-75 - a search nobody downloads from blocks every later search, with no visible way out - FIXED, shipped 2026-08-24 (dashboard 0.7.8 OTA)
**Symptom** (owner, 2026-08-24): run a search, download nothing from its
results, and every later SEARCH / GET LINKS answers "you already have a job
in progress" until the parked job is cancelled - and the only cancel was the
small [ CANCEL ] on the progress strip, which nobody read as "throw this
search away". (The 409s are in the live log within minutes of the report.)

**Fix** (`ytdl/web/static/app.js`, `index.html`). Three affordances, all on
the existing cancel endpoint (the server has cancelled a ready_for_review
job outright since YTDL-1): (1) the review header now carries
[ CANCEL SEARCH ], shown only while the job is parked at ready_for_review
(a done job's review is the re-download view, CR-35), which cancels,
clears the page and refreshes Recent searches; (2) a SEARCH refused with a
409 against a job parked at ready_for_review - the one non-terminal phase
with nothing in flight - offers a confirm to discard it and re-sends the
refused payload as-is; (3) the same offer on GET LINKS. Declining, or a
browser with no confirm(), is exactly the old behaviour: re-attach and the
loud toast (which now names [ CANCEL SEARCH ]). Harness scenarios in
`tests/test_static_app.py`. Needs a dashboard deploy.

## The first CI run that ever saw waves 1-5 (CR-94, 2026-08-29)

### CR-94 - three green-on-Windows suites, four failures on Linux and macOS - FIXED in repo 2026-08-29, companion 0.9.55 / dashboard 0.7.17
**How it surfaced.** Seven commits (CR-92, the five resilience-sweep waves,
CR-93) had been sitting on this rig unpushed since 2026-08-27. Everything
was green here. The first push put them through `.github/workflows/ci.yml`
for the first time and four tests failed on the two operating systems this
rig is not - which is the entire reason that workflow exists
(COMMERCIAL_READINESS item 13). Three of the four are test defects; one is a
real macOS behaviour bug. None of them affects a Windows editor, which is
why none of them had ever been seen.

**1. `file_moves._cmp_key` - a Mac could not recognise its own moved file
(the real one).** `moved_to()` is what turns a MISSING clip into RES-10's
one-click relink, and it compared paths with `os.path.normcase`, which is a
**no-op on POSIX**. A Mac's APFS volume is case-insensitive by default, so
`Clip.braw` and `clip.braw` are one file there - and the ledger lookup for
one spelling missed a move recorded under the other, leaving the clip
looking like a mystery rather than a relink. Fixed with a `_cmp_key()`
helper that folds case on Windows (as before) and on darwin, and leaves
Linux alone, where case genuinely does distinguish two files. It is a
COMPARISON key only: nothing opens, renames or deletes through it, per
CLAUDE.md's rule that there the bytes on disk are the truth. The same helper
now backs `_same_file` and `_is_inside`.

**2. `test_tk_release_native` - three 120 s hangs on macOS.** Every child in
that file builds its Tk root on a WORKER thread, which is the CR-93 shape.
On macOS's Aqua Tk that is not a thing you may do at all: Tk initialises
against NSApplication, which belongs to the main thread, so the child does
not fail - it blocks for ever. The module's skip-probe created a root on the
MAIN thread, proved nothing about the shape actually under test, and let all
three run into the timeout. The probe is now the same shape as the tests
(worker-thread root, 30 s cap) and skips the module when it hangs. Windows
coverage of CR-93 is unchanged - all three still run and pass here.

**3. `test_invariants` - the page test raced the real collector.** Entering
the `TestClient` lifespan starts the live `Collector` thread, which runs
`invariants` on its own connection with `folder_devices=None` (no Syncthing
configured in a test), and so re-records invariant 1 as NOT CHECKED over the
BROKEN verdict the test had just seeded. The GET usually won that race here;
on the Linux runner it lost. Fixed by stopping the collector before seeding
- the same pattern, and the same reason, already documented in
`test_alerts.py`.

**4. `test_rclone_lane_races` - a safety test that had been a coin flip
since wave 1.** `_FakeProc.wait()` honoured `wait_for_terminate` only when
`timeout is None`. That was true of the runner until **CR-91** (wave 1,
2026-08-28) replaced the unbounded `proc.wait()` with a poll loop that
always passes a timeout. From that commit on the fake returned its exit code
on the first poll, the run finished and cleared its published child handle
before `stop()` could look, and `proc.terminated` was False unless `stop()`
happened to win the spawn race. It kept winning here and lost on a loaded
macOS runner. The fake now behaves like a real child: it blocks up to
`timeout` and raises `subprocess.TimeoutExpired`. This one is worth noting
beyond its own fix - **a wave-1 change to production code silently disarmed
a fake that four tests rely on**, and only a slower machine ever said so.

**...and then rclone.org fell over.** The very next run, and both release
builds with it, went red at `install pinned rclone` before a single test
ran: `curl: (28) Failed to connect to downloads.rclone.org port 443 after
75025 ms`. Not the runners - the host was unreachable from the base rig too.
Every CI run and every release build hung off one third-party web server
being up. All four steps now try `downloads.rclone.org` first and the
byte-identical GitHub release asset second (verified here: both are
sha256 `35e8f2a6...` for osx-arm64). The pin is unchanged and is still the
trust anchor, so a mirror serving different bytes fails exactly as loudly as
a corrupt download would.

**The lesson, and it is the CI one.** "Green on the base rig" is a claim
about one Windows box. Three of these four had been broken for a day or more
and two of them were latent races that this hardware simply kept winning.
Push before the pile gets to seven commits.

## The tray "kept closing itself": a Tk root freed on the wrong thread (CR-93, 2026-08-29)

### CR-93 - Tcl_AsyncDelete aborts the whole companion, with no traceback and no log line - first fix shipped as companion 0.9.55, RECURRED 2026-08-30 twice; the real fix is the continuation below (0.9.62)
**Reported** by the owner 2026-08-29, on the base rig: "ccsync companion seems
to keep closing itself in this version". The tray icon disappears, sync stops,
and `companion.log` shows nothing at all - its last line is whatever the
companion happened to be doing, then a gap, then the next `starting` line
from whoever relaunched it.

**It was not closing itself. It was aborting.** Windows Event Log, seven
times between 2026-08-18 17:16 and 2026-08-29 13:20 (three of them in the
five minutes of a restart on 08-28), every one in the same fault bucket:

```
Faulting application name: ccsync-companion.exe
Faulting module name: tcl86t.dll 8.6.15
Exception code: 0x80000003     Fault offset: 0xfee74
```

All seven minidumps in `%LOCALAPPDATA%\CrashDumps` carry a byte-identical
faulting stack: `tcl86t.dll` (the panic) <- `_tkinter.pyd+0x3ea7`
(Tkapp_Dealloc -> Tcl_DeleteInterp) <- an ordinary refcount-driven dealloc
chain in `python312.dll`. Reproduced locally in six lines, which is what
names it:

```
Tcl_AsyncDelete: async handler deleted by the wrong thread
```

**Cause.** A `tk.Tk()` root owns a Tcl interpreter, and `_tkinter` frees that
interpreter in `Tkapp_Dealloc` - inline, on whatever thread drops the last
Python reference, with none of the marshaling an ordinary Tk call gets. Tcl
answers an interpreter deleted from a thread other than its creator with
`Tcl_Panic`, i.e. `abort()`: the process is gone mid-instruction, so no
`finally`, no `atexit`, no `sys.excepthook`, no crash file, nothing in the
log. On win32 this companion builds every dialog on whatever thread wanted it
(`ui_dispatch`'s inline mode, deliberately - see its docstring), so ANY Tk
object that outlives its thread is the loaded gun: a widget in an attribute,
a per-row `StringVar`, a `ttk.Style`, the icon `PhotoImage`. Half the fix was
already there and undated as such: `WorkProgressWindow._drop_widgets` was
written for this exact abort on 2026-08-18 (the b-roll window closing, the
music window's build overwriting its widget attributes on a new thread) -
but it was treated as one window's bug rather than the class it is.

The three windows that keep widgets in ATTRIBUTES and outlive their thread:
`PopupDialog` (FIX ALL runs on a daemon thread holding `self._publish` /
`self._fix_done`, and the dialog kept one `tk.StringVar` PER ROW),
`ProgressWindow` (`run()` joins its worker with a 1 s TIMEOUT, and the worker
holds `publish`/`should_stop`), and `WorkProgressWindow` (the app holds it in
`_work_window`; a tray click or `shutdown()` on the MAIN thread could drop
the last reference while its own thread was still tearing the window down -
which is why three of the seven crashes are on restarts).

**Fixed** in `ui_dispatch.release_root()`: destroy the window, drop the icon
image, `gc.collect()`, then read `sys.getrefcount(root.tk)`. Baseline 2 means
the interpreter dies here, on the thread that built it. Anything more is a
leak, and the log line NAMES the holders' types instead of the process
vanishing - then the root is PARKED (with an immortal reference, `Py_IncRef`
via ctypes: module globals are cleared from the main thread during
interpreter shutdown, so a graveyard that is only a list aborts on the way
out - measured) and reclaimed by the next release on that same thread once
its holder lets go. Parking leaks a few hundred KB; the alternative leaks the
tray. Call sites: all three window classes clear their widget attributes
first (`_drop_widgets`, `_vars = []`, `self.root = None`), `_tk_pick` and
`copy_diagnostics` release their hidden roots, and `app._close_work_window`
now WAITS (3 s, bounded) for a work window's own thread to finish before
letting go of it. The dialogs whose widgets are all frame LOCALS
(`confirm_dialog`, the licence dialog, the tray's sign-in/update/credentials
forms) are safe by construction and deliberately do not call it - a live
frame's locals read as holders and would park for nothing.

**And the silence is fixed too**, because the next native abort of any kind
must not cost a dump-parsing session: `crash_report.install_native()` enables
`faulthandler` into `~/.ccsync/crashes/native.log` and writes a RUN MARKER
for the live pid, cleared at the top of `shutdown()` (the moment the process
DECIDES to stop, so the hard-exit backstop is not slandered as a crash). A
start that finds a marker writes a normal crash report, type `UncleanExit`,
carrying the native dump and the log tail - which means an abort, a kill and
a power cut all reach the tray line, the diagnostics bundle and the dashboard
through the machinery APP-6 already built. A Tcl_Panic reaches WER rather
than faulthandler, so that report also says where to look (Event Log,
0x80000003, tcl86t.dll).

Tests: `tests/test_tk_release_native.py` runs the real thing in a SUBPROCESS
(the disease aborts, the cure exits 0, including through interpreter
shutdown) because the failure kills the interpreter it is tested in;
`test_ui_dispatch.py` covers the parking, the per-thread graveyard and the
sweep against fake roots; `test_popup.py` covers the three teardowns;
`test_app.py` the close-and-wait and the clean-exit marker;
`test_crash_report.py` the marker, the report and the native log.

Ships as: companion 0.9.55 (the same unshipped build CR-92 and the resilience
sweep are on). Nothing dashboard-side. **Until it ships, every editor's tray
can still abort this way** - the symptom to ask about is "the tray icon is
gone and the log just stops".

**Recurrence on the fixed build (2026-08-30, base rig).** Companion 0.9.55 - the build that carries this fix - aborted at 12:17:06 in the SAME bucket (`tcl86t.dll`, 0x80000003, fault offset 0xfee74, faulting pid 0x68BC), 47 s after the tray's `tray: opening dashboard http://192.168.0.102:8480` line and while `ytdl: job 52` was downloading locally. The companion stayed dead until 15:28, when the AFK session relaunched it by hand (`Start-Process` of the Run-key path) - three hours with the tray gone and sync stopped. Then AGAIN at 22:40:39 on 0.9.61 (pid 0x6994 = 27028), 47 minutes dead until relaunched by hand at 23:27. The paragraph that used to end this section guessed at the open-dashboard path and the ytdl progress mirror; both guesses were wrong, and the second section below is what the evidence actually says.

### CR-93 (continued) - the abort is the cyclic GC freeing a dialog's closure cycle on the watcher thread; every interpreter is now pinned at birth and freed only by its own thread; a supervisor relaunches the companion after a death - FIXED in repo 2026-08-31 as companion 0.9.62, NOT YET SHIPPED

**What the 22:40 crash left behind that no earlier one had.** Two records, both from `crash_report.install_native` (0.9.55's own addition):

1. `~/.ccsync/crashes/native.log`, faulthandler's thread dump at the moment of the `0x80000003`. For BOTH 2026-08-30 crashes (12:17 on 0.9.55 and 22:40 on 0.9.61 - the log holds both) the current thread is the timeline WATCHER thread, and its top frame is `Garbage-collecting`:

   ```
   Current thread 0x00008568 (most recent call first):
     Garbage-collecting
     File "uuid.py", line 171 in __init__
     File "pg8000\converters.py", line 304 in uuid_in
     File "pg8000\core.py", line 830 in handle_DATA_ROW
     ...
     File "ccsync_companion\library.py", line 950 in timeline_items
     File "ccsync_companion\resolve_bridge.py", line 1337 in _library_timeline_items
     File "ccsync_companion\watcher.py", line 193 in poll_once
     File "ccsync_companion\app.py", line 7584 in _watcher_thread_target
   ```

   So the 12:17 death was NOT on the ytdl thread (that thread was sitting in `communicate()`), and the "47 s after the tray click" was a coincidence: the tray's open-dashboard handler builds nothing Tk at all (`tray._open_dashboard` is `webbrowser.open`).

2. The minidump `%LOCALAPPDATA%\CrashDumps\ccsync-companion.exe.27028.dmp` (8.7 MB; the 12:17 one, `.26812.dmp`, exists too - the previous paragraph was wrong about that). No cdb/WinDbg on this rig, and msdl.microsoft.com does not carry python.org's symbols (404), so the dump was read with the `minidump` + `pefile` packages in a scratch venv, the faulting thread's stack scanned for return addresses, and those named through `dbghelp.dll` against `python312.pdb`/`_tkinter.pdb` extracted from python.org's `3.12.10/amd64/core_pdb.msi` and `tcltk_pdb.msi` (`msiexec /a ... TARGETDIR=`, no install; the dump's `python312.dll` timestamp 1744115002 matches the installed one). The faulting thread is 0x8568 - the watcher thread above - and its stack, deepest caller last:

   ```
   tcl86t!Tcl_PanicVA+0x124            <- the int3 (fault offset 0xfee74)
   tcl86t!Tcl_Panic+0x22
   tcl86t!Tcl_AsyncDelete+0x106        "async handler deleted by the wrong thread"
   tcl86t!Tcl_DeleteInterp+0xf3
   _tkinter!Tkapp_Dealloc+0x63         (_tkinter.pyd+0x3ea7, the same offset as all seven 08-18..08-29 dumps)
   python312!subtype_dealloc           the Tk root
   python312!dict_dealloc
   python312!subtype_dealloc
   python312!dict_dealloc
   python312!cell_dealloc              \
   python312!tupledealloc               | a closure's cell holding a dict holding the root
   python312!func_clear                 |
   python312!func_dealloc               | FOUR times over: nested functions freeing
   python312!cell_dealloc               | each other through their closure cells
   python312!tupledealloc               |
   python312!func_clear                 |
   python312!func_dealloc              /
   python312!cell_clear
   python312!delete_garbage
   python312!gc_collect_main
   python312!gc_collect_with_callback
   python312!gc_collect_generations
   python312!_Py_RunGC
   python312!_Py_HandlePending
   python312!_PyEval_EvalFrameDefault   (uuid.__init__, per faulthandler)
   ```

**The mechanism, and why 0.9.55's fix could not see it.** `release_root()` counted references to the interpreter at the end of a dialog and parked the root when a widget still held it. That closes "a widget kept in an attribute". The stack above is a different animal: **nested functions in a reference cycle**. The Settings window (`settings_window._build_settings_window`, opened by a left-click on the tray, and it logs nothing - which is why the 22:40 process's log shows no dialog at all in its 50 minutes) has `_refresh` schedule ITSELF with `root.after(_REFRESH_MS, _refresh)`: function -> closure tuple -> cell -> the same function is a cycle, and `_refresh` reaches `root` through `_render` -> `_run` -> `_release_and_close`. When the window closes and the frame returns, nothing is freed - a cycle is freed by the **cyclic garbage collector**, later, on whichever thread's allocations trip it. While the window sat open refreshing every two seconds those objects were promoted to generation 2, and a gen-2 pass only runs when the long-lived heap has grown by a quarter - which is exactly what a project-library read does (`library.timeline_items` -> `pool_paths`/`_load_graph`, a hundred thousand fresh uuid/tuple objects on the watcher thread). Both crashes are inside that read: 21:50 "reading clips from the project library" on start, 22:39 Resolve restarted, 22:40:10 reconnected, 22:40:37 the read began, 22:40:39 dead. No refcount taken INSIDE the dialog can see any of this, because inside the dialog the frame is alive and every count is legitimately high. The 0.9.55 note that "a dialog whose widgets are all frame LOCALS is safe by construction" was the wrong belief: locals die with the frame; a cycle among them does not. The tray's sign-in/update/credentials forms and `confirm_dialog` have the same `_ok`/`_cancel` closures over `root`; whether each is a cycle today is a matter of which callback references which, and the fix below does not depend on the answer.

Reproduced in twenty lines (`tests/test_tk_release_native.py::CYCLE_ON_A_WORKER_THREAD`): a root built on a worker thread, reachable only through a self-scheduling closure, `gc.disable()` so nothing collects it early, the thread ends, `gc.collect()` on the main thread -> `Tcl_AsyncDelete: async handler deleted by the wrong thread`, exit 3. Every time.

**Fixed (B): every Tcl interpreter is pinned at birth and freed only by the thread that built it.** Three options were weighed. A persistent hidden root per UI thread reused as a Toplevel does nothing for the cycle: the hidden root is just as collectable, and the tray's per-click threads have no "per UI thread". One dedicated Tk thread for all UI (ui_dispatch's darwin marshalling mode, on win32 too) is the biggest change to a year-old working design and STILL does not cover the GC: a cycle from the UI thread is freed on whatever thread collects it. Only pinning makes the abort impossible regardless of who holds what, so `ui_dispatch` now:

- wraps `tkinter.Tk.__init__` (`install_tk_guard()`, at import - every dialog site imports the module first; `app.run` calls it again for the log line) so every root is `adopt()`ed the moment it exists: a registry record per interpreter (which thread built it, at which call site, a weakref to its root) plus a `Py_IncRef` on the `tkapp` through ctypes. The pin is invisible to Python and to finalisation; whoever drops the last visible reference, on whatever thread, only ever lowers the count to it. `Tkapp_Dealloc` has exactly one path left in this process: `_try_free()`;
- reclaims at the end of every `dispatch(fn)` (`reclaim_mine()`): fn's frame has returned and its closures are garbage, so THIS thread runs `gc.collect()` itself, then frees each interpreter it built whose count is at the baseline (record + pin + the root's own `tk`), swapping the root's `tk` for a sentinel that answers `TclError` first. `release_root()` is the same pass for the three window classes that own their root, and now refuses - loudly - when called from a thread other than the builder (the old graveyard was keyed on `threading.get_ident()`, which Windows recycles; a sweep on a recycled ident would have been this abort again);
- leaves a still-held interpreter pinned (1.8 MB each, measured: 20 roots, `tasklist` working set) and NAMES the holder: types, and referrer chains a few hops out (`Label <- dict{'master', 'tk'} <- cell <- function _refresh`). An interpreter whose thread has exited can never be freed (Tcl ties it to that thread's storage) and is reported once as a leak. `CCSYNC_TK_AUDIT=1` logs the whole registry after every pass - that is the probe: if a dialog leaks on the base rig, the next line in the log says which one, built where, held by what.

Proven the only honest way, in subprocesses (`tests/test_tk_release_native.py`, six children now): the widget-in-an-attribute disease still aborts and `release_root` still cures it; the closure-cycle disease aborts (exit 3, `Tcl_AsyncDelete` on stderr) with no guard; through `dispatch()` the same dialog's interpreter is freed on the dialog thread (`pinned_records() == []` there) and the main thread's collection survives; a root built OUTSIDE dispatch and never released stays pinned, is named, and the process exits 0 including through interpreter shutdown. `test_ui_dispatch.py` covers the registry with fakes (the cycle through dispatch, wrong-thread refusal, per-thread ownership, the orphan report, the audit).

**Fixed (C): a companion that dies is brought back.** An abort has no `finally`, so nothing in-process can help; the Run key fires at logon and never again; the lane watchdog restarts threads, not processes. `supervisor.py` (stdlib only, branched on in `launcher.py`/`__main__.py` BEFORE the app import) is the same exe re-entered as `ccsync-companion.exe --supervise <pid> --exe ... --crash-dir ... --state-dir ...`, spawned by `crash_report.start_supervisor()` right after `install_native()` has written the run marker and the single-instance slot is held (`[companion] supervise = true`, default; `CCSYNC_NO_SUPERVISOR` for a frozen build under test; Windows frozen builds only). It waits on the process handle and decides with `supervisor.decide()`, a pure function: relaunch iff the run marker is still there AND names that pid (shutdown() deletes it first thing, so a Quit, a fleet halt, a crash-loop revert and a self-upgrade hand-off - the newcomer writes its own marker - all read as deliberate) AND the exit code is not one a person or tool hands out (0; 1 = End task or a Python-level startup failure; 0xFFFFFFFF = `Stop-Process`, which is how `windows_upgrade.ps1` and the uninstaller stop it - and since the supervisor shares the image name, `Get-Process ccsync-companion | Stop-Process -Force` kills it too, so it can never fight an install; 0xC000013A = console closed) AND fewer than three relaunches in the last hour (`state/supervisor.json`). It then waits 10 s (WER is writing the dump), re-reads the marker in case a person got there first, writes `crashes/relaunched.json`, and starts the exe the way `upgrade._default_spawn` does (detached, no window, `_MEI*`/`PYTHONHOME` stripped, `PYINSTALLER_RESET_ENVIRONMENT=1`). A relaunch always goes through the single-instance guard, so there is never a second tray. The relaunched companion finds the old marker and the note: the `UncleanExit` report carries a `relaunch` block and its message says so, and the log says `this companion was RELAUNCHED by its supervisor: pid N died with exit code X ... down for about 10 s` - which rides to the dashboard with the crash summary as before. The supervisor's own log is `crashes/supervisor.log`. Two marker fixes rode along: `mark_clean_exit()` only removes a marker naming OUR pid (the old build's shutdown used to delete the newcomer's during a self-upgrade), and `install_native()` treats a marker whose pid is still alive as a hand-off, not a crash. `tests/test_supervisor.py` pins the verdict matrix, one supervised life end to end with injected waiter/spawn/clock, the loop cap, the person-got-there-first case, the clean environment, and - in a real child - that `--supervise` exits 0 without `ccsync_companion.app` ever being imported.

Ships as: companion 0.9.62. Nothing dashboard-side. **Until it ships, 0.9.61 aborts exactly as before** and stays down until someone relaunches it. After it ships, watch `companion.log` for `UI dispatch: ... closed with its Tcl interpreter still referenced` (a holder to name; not an abort) and for `RELAUNCHED by its supervisor` (the net caught something: read the crash report it points at), and the Event Log for 0x80000003 in tcl86t.dll, which should never appear again.

## Pulling the sync drive mid-upload looked exactly like pulling it after a finished day (CR-92, 2026-08-28)

### CR-92 - the unplug balloon never said whether anything was still owed, and nothing ever reminded the editor - FIXED in repo 2026-08-28 as companion 0.9.55, NOT YET SHIPPED
**Asked for** by the owner 2026-08-28, with leso's Mac in mind (the tree on an
external SSD at `/Volumes/SAMDISK/Creators_Club`): a warning when the drive
is removed but syncing has not completed, and then a reminder every half
hour, for as long as the drive stays out, telling the editor to plug it back
in to finish syncing.

**What it did before.** `root_guard.py` noticed the volume going and
`app._on_root_absent` paused the lanes with ONE balloon, "Sync paused: your
Creators Club drive is disconnected", the same sentence whether the machine
was up to date or three camera originals were part-uploaded. rclone has no
resume for SFTP uploads, so those files start from zero when the drive comes
back - IF it comes back before the project is needed. In between, the fleet
page shows the machine behind and the only person who can fix it is looking
at a menu-bar icon that reads "paused", which is what they asked for. Nothing
repeated, and a companion restart with the drive out forgot there had ever
been anything owed.

**What it does now** (`companion/src/ccsync_companion/drive_reminder.py`):

- At the moment the drive goes, BEFORE the lanes are paused (pausing rewrites
  every status to `paused`, which `busy_lanes()` rightly ignores), the app
  asks what was still in flight. If anything was, the balloon is "Your
  Creators Club drive was disconnected before syncing finished: 2 uploads and
  14 other files (1.9 GB left) still to go. Plug it back in to finish
  syncing." (title `ccsync-companion: sync unfinished`). Otherwise the calm
  one-liner stands, unchanged - the common case must stay calm.
- Then every `drive_reminder_minutes` (new config key, default 30, 0 = first
  warning only, a bad value warns and uses the default): "Your Creators Club
  drive is still disconnected and syncing is unfinished: ... still to go. Plug
  it back in to finish syncing." The tray `Sync:` line reads `paused (drive
  disconnected, 2 uploads (1.9 GB left) still to go)`, the tooltip and the
  Settings window's SYNC LANES section carry the same figure, so the balloon
  is not the only place the sentence exists.
- The episode is recorded in `~/.ccsync/state/drive_unfinished.json`. A
  companion that quits (self-upgrade, reboot) with the drive out owing work
  restarts with the drive out owing work: `root_guard` fires `on_absent` at
  startup, nothing is in flight, and the record is what says the reminders
  carry on - one goes out at once, then the cadence. The drive coming back
  is the only thing that clears it (also on the first healthy sighting after
  a restart, which retires a stale record). Not a safety latch: losing the
  file costs a reminder, never data.
- **What counts as "unfinished" is the power guards' verdict, not
  `busy_lanes()`.** `shutdown_guard.PendingTracker` grew `live_busy()`
  (`describe()` before it is rendered into a sentence), and the reminder
  reads that, so a lane sitting in `syncing` for hours with nothing moving -
  CR-91's exact shape, on the same machine this was asked for - is NOT
  reported as an upload the editor must plug the drive back in for every
  half hour. Cry-wolf is the failure that gets the real warning ignored.

**Where it cannot help.** The verdict is taken from the lanes' own status at
the moment of the unplug; a transfer that had already failed for another
reason (`error`) or one the editor had paused from the tray is not "owed",
and a lane that had not yet started its pass (nothing in flight, backlog
unknown to the companion) is not either - the dashboard's queue is the
authority for THAT. Also Mac notifications go through `osascript display
notification`, so a user who has silenced notifications for Script Editor
sees only the tray line.

Tests: `companion/tests/test_drive_reminder.py` (the module), CR-92 blocks in
`test_app.py` (the four sentences, the CR-91 guard, the restart carry-on,
shutdown keeping the record), `test_tray.py` (Sync: line, snapshot
fingerprint, tooltip length), `test_shutdown_guard.py` (`live_busy`),
`test_config.py` (the key is documented commented-out, like the keep-awake
pair). Ships as companion 0.9.55; no dashboard change.

## Resilience sweep, wave 1 (2026-08-28) - FIXED in repo, unshipped

The ten-agent resilience sweep (`docs/RESILIENCE_SWEEP_2026-08-28.md`, raw
findings in `docs/resilience-sweep-2026-08-28/`) produced 201 findings; wave 1
is the nineteen cheapest high-severity ones, built the same day by nine
builder agents. Ids below are the sweep's own (SYNC-n, APP-n, DASH-n, ...),
not new CR numbers, so they can be found in the sweep reports.

Ships as: companion 0.9.55 (the same unshipped build CR-92 is on), dashboard
schema v30 + v31 (the next dashboard release), AND a rebuilt installer
package + onboard.exe (OPS-8 adds `installer/drive_mapping.ps1`, which the
bootstrap now requires). Deploy the dashboard before the companions: the
companion sends new `sync_guard` sections that v30 declares.

Known follow-ups left by the builders: `sync/rclone_lane.py`'s test-only
fallback breaker still builds at the old `state/` path (APP-3); DASH-5's
"walk collapsed" refusal has no UI override (needs `force=True` if a
project's originals really were all deleted on the NAS); YT-3's staging
half (download outside the tree) is still open; SYS-11's rows are not yet
in any weekly report (SYS-8, later wave); `docs/CLIENT_FOLDERS.md` still
describes the old hour of media cache (MEDIA-22).

### SYNC-3 - on a Mac the relocation probe cannot match its own trashed files - FIXED in repo 2026-08-28, unshipped

**Symptom.** A Mac editor holds `Interviewees/Matej Šimalčík/...`; an admin reorganises that
folder on the NAS; lane B moves the proxies aside and the lane B breaker trips, parking proxy
download for a day even though every byte is still on the server. The operator runbook's promise
that "a move should no longer reach you as an alarm" (CR-44) was false on every Mac.

**Cause.** `_count_relocations` compared paths read off the LOCAL disk (macOS listdir: NFD)
against paths read off the NAS (NFC) with `rel in remote_paths` and `remote_files.get(name)`.
Every path containing a diacritic scored as a deletion, so the probe under-counted and the
breaker tripped. CR-90's lesson had been applied at the dashboard's write chokepoints only.
CJK folders beside it matched fine, which is what made the shape unreadable.

**Fix.** Both sides fold through a new `nfc_key()` helper before the comparison, for the rel
paths and the basename index alike (`sync/rclone_lane.py:400` for the helper,
`:3160` in `_count_relocations`). Comparison only: nothing on this path opens, renames or
deletes a file, so the bytes on disk are still the bytes rclone is handed.

**Tests.** `companion/tests/test_rclone_lane.py` - three tests against the real NFC/NFD pair
already committed in `dashboard/tests/test_unicode_paths.py`: an NFD trashed path matched
against the NAS's NFC listing at the same rel, the CR-44 basename+size move across the same
boundary, and a genuine deletion still counted as a deletion (the fold must not turn the
breaker off).

### SYNC-11 - the file-move exclusion does not match a macOS path, so the moved file re-uploads - FIXED in repo 2026-08-28, unshipped

**Symptom.** An admin moves a file on the NAS through the project page; the editor's Mac moves
its own copy and reports success; the next lane A pass puts the file straight back at the old
NAS path - the exact failure `docs/FILE_MOVES.md` exists to prevent, with nothing reporting it.

**Cause.** The dashboard's `from_rel` is NFC; the file on the Mac's own disk is NFD. The
exclusion is handed to rclone as a literal glob and rclone matches the bytes it reads off the
filesystem, so a path with any diacritic was never excluded. `apply_move` itself survives
(APFS lookups are normalisation-insensitive), which is what makes it look like it works.

**Fix.** `file_moves.FileMoveLedger.recent_excludes` (`file_moves.py:206`) emits every path in
BOTH spellings, deduped - an extra `-` rule that matches nothing is free. Separately,
`build_filter_rules_up` (`sync/rclone_lane.py:417`) now emits a `/**` directory-prune companion
for every excluded path, because a move can name a directory (`is_dir`) and `- /Sub/Dir` alone
is a prune that is easy to get wrong. Both still sit ahead of the `+ *<ext>` includes.

**Tests.** `companion/tests/test_file_moves.py` - both spellings emitted for a diacritic path,
an ASCII path still one rule, and the `/**` companion present and ahead of `+ *.mov`.
`test_rclone_filters.py`'s existing positional assertion updated for the second rule.

### SYNC-5 - a folder latched paused for missing ignores is invisible, lane C still reports green - FIXED in repo 2026-08-28, unshipped

**Symptom.** One project of an editor's five never syncs, indefinitely, while lane C reports
`state=IDLE, queued=0, last_sync=now` and the tray dot is green. The only trace was a single
DEBUG line.

**Cause.** The ignores-unconfirmed latch (AUDIT_2 L-3/B14) correctly keeps a folder paused when
its `.stignore` never landed, but `_ignores_unconfirmed` never left `sequencer.py`, and
`check_once` only reports `PAUSED` when EVERY expected folder is paused - with 1 of 5 it fell
through to the green `else`.

**Fix.** `Sequencer.unconfirmed_slugs()` (`sync/sequencer.py:645`) publishes the latch;
`SyncthingLane` takes it as `unfiltered_folders_fn` and a non-empty answer makes lane C
`state=error` with the sentence "N project(s) are not sharing yet - waiting for their filter
list: ..." (`sync/syncthing_lane.py:344`, `:660`), reported alongside a real folder error rather
than instead of it. The wiring is in `app.py:1421`; the machine-readable half rides the report as
`sync_guard.folders_unfiltered` (`app.py:4400`), and `tray._unfiltered_line` puts the same
sentence in the Settings window's SYNC LANES section.

**Tests.** `companion/tests/test_syncthing_lane.py` - error state and sentence with one folder
parked, both reasons reported together, a raising probe never taking the lane report down, and
the sentence's five-project cap. `companion/tests/test_sequencer.py` - the latch and the admin's
half-accepted-folder record both published, and a raising predicate answering `[]`.

### SYNC-6 - the shared/borrowed folder reconcile mkdirs into an absent local_root - FIXED in repo 2026-08-28, unshipped

**Symptom.** A Mac editor's SSD is out at login. Within the root guard's 5 s poll the sequencer's
loop head reconciles the shared and borrowed folders, `mkdir(parents=True)` builds
`/Volumes/SAMDISK/Creators_Club/Assets/...` on the BOOT disk, and macOS then mounts the real
drive as `/Volumes/SAMDISK 1` - `ROOT_MISPLACED`, permanently, until a human deletes the ghost.
On a first accept the Syncthing folder is also POINTED at the ghost.

**Cause.** `_clone_structure` and both rclone lanes check the root first; the shared/borrowed
reconcile, which runs earlier in the same loop, did not.

**Fix.** Both managers take the `root_present_fn` `ManifestCache` takes and return `{}` from
`reconcile()` when it is False (`sync/shared_folders.py:118`, `sync/borrowed_folders.py:98`);
unanswerable counts as ABSENT, because what it gates is a mkdir. A second `_mkdir_allowed()`
gate immediately before each mkdir refuses when the local_root ancestor is not a directory, for
the drive that goes out mid-reconcile - `_accept` returns "error", `_repoint` leaves the folder
pointed where it is. Wired from `sequencer.py:276`/`:290`.

**Tests.** `companion/tests/test_shared_folders.py` and `test_borrowed_folders.py` - reconcile
touches nothing and creates nothing while the tree is absent, an unanswerable probe counts as
absent, and the accept/repoint mkdir guards hold when the root check says present but the
directory is not there.

### UX-7 - Syncthing conflict copies are never detected or surfaced - FIXED in repo 2026-08-28, unshipped

**Symptom.** Two editors change the same file; Syncthing writes
`<name>.sync-conflict-20260828-104500-XXXX.<ext>` beside it and says nothing. Lane A uploads the
conflict copy to the NAS as a new file (it never deletes), lane B redistributes it, and one
editor's work is orphaned into a file nobody looks at. `SPEC.md:343` says this is surfaced in
the tray; the string appeared nowhere in `companion/src` or `dashboard/src`.

**Cause.** Nothing ever looked for it.

**Fix.** The manifest walk already visits every file, so the scan is free: `scan_local_manifest`
counts `*.sync-conflict-*` of ANY extension (the check sits ahead of the VIDEO_EXTS filter -
the common case is a .drp or an audio file) and fills an optional `conflicts_out`
(`manifest.py:110`, `:158`). `ManifestCache.sync_conflicts()` (`manifest.py:276`) holds the last
successful scan's count and up to 20 paths, logs a WARNING when non-zero, and rides the report as
`sync_guard.sync_conflicts` (`app.py:4407`). `tray._conflicts_line` renders the advisory in the
Settings window. Nothing here deletes or merges anything: which side is the work is a human's
judgement.

**Tests.** `companion/tests/test_manifest.py` - conflict copies of any kind counted and
path-prefixed by project, the path list capped while the count stays exact, `{}` when there are
none, and a skipped scan (drive out) never reading as "the conflicts are gone".

### YT-3 (filter half) - the pre-conversion original is uploaded under the final name - FIXED in repo 2026-08-28, unshipped

**Symptom.** An editor downloads a clip, YouTube serves VP9, and the companion starts a
ten-minute libx264 re-encode inside the tree. A lane A pass during those minutes uploads the
un-converted file under the final name; `copy --ignore-existing` then makes it the fleet's
permanent copy, undecodable, with no error anywhere. CR-79's failure arriving through the sync
lane.

**Cause.** `build_filter_rules_up` had no rule for the work files, and they carry real video
extensions.

**Fix.** `YTDL_WORK_EXCLUDE_RULES` (`sync/rclone_lane.py:113`) excludes `*.editready.*`,
`*.original.*`, `*.temp.*`, `*.f[0-9][0-9][0-9]*.*` and `*.failed`, inserted AHEAD of the
`+ *<ext>` includes (`:426`) because rclone filter matching is first-match-wins. This is the
filter half only; the `--no-mtime` half (which restores `--min-age` as a real gate) is on the
ytdl executors and belongs to another change.

**Tests.** `companion/tests/test_rclone_filters.py` - every pattern present and ahead of the
first include, plus a real-rclone dry run over a `Youtube/` dir holding a conversion in flight:
only the finished name is uploaded.

### APP-4 - a config.toml rewrite could take the machine to ALL DEFAULTS - FIXED in repo 2026-08-28, unshipped

**Symptom.** An editor uses Settings -> THIS COMPUTER to change the role on a
machine whose disk is full, or the process dies in the millisecond between
`write_text` truncating config.toml and refilling it. On the next start every
setting is a default: blank `local_root`, blank `remote`, and a blank
`dashboard_url`, which is what decides whether `DashboardReporter` exists at
all. The lanes refuse (correctly), and the machine also vanishes from the
fleet grid with the editor's credentials gone. The only route back was a
reinstall.

**Cause.** `config.set_value` was the one writer of config.toml at runtime and
the only one in the package that wrote in place: `text = path.read_text()` ...
`path.write_text(...)`. Every other holder of a credential here
(`identity.save_identity`, `machine.py`, `eula.py`, `upgrade.py`) already went
tmp + harden + `os.replace`. And a decode error had exactly one outcome,
"falling back to ALL DEFAULTS", with no memory of the file that worked
yesterday.

**Fix.** `set_value` writes `config.toml.tmp`, calls `secretfile.harden` on it
BEFORE the rename (config.toml carries a fleet report token) and `os.replace`s
it into position, returning False and leaving the live file untouched if any
of that fails (`companion/src/ccsync_companion/config.py`, `set_value`).
`load_config` keeps `config.toml.bak` of the last file that PARSED, refreshed
atomically and only when the content changed (`_refresh_backup`), and on a
`TOMLDecodeError` loads that backup instead of defaults, logging loudly and
recording `_config_load_error` plus a new `_config_from_backup` flag so
`validate_config` still raises it as a config problem the tray and the lane
detail show - with wording that says "the last good copy of your settings"
rather than the old "every setting below is a DEFAULT", which would now be a
lie.

**Tests.** `companion/tests/test_config.py`: the write survives a failing
`os.replace` with the live file byte-identical and no `.tmp` left behind; the
backup is written on a clean parse; a truncated config.toml loads the backup,
reports `_config_from_backup`, and still produces a `validate_config` error;
a corrupt file with no backup still falls back to defaults.

### APP-11 - the role button could write into a TOML table and then do nothing, forever - FIXED in repo 2026-08-28, unshipped

**Symptom.** On a config.toml somebody had hand-extended with a `[proxy]` or
`[experimental]` table, Settings -> WIRED TO THE SERVER appeared to do
nothing at all, every time, with nothing logged and no "takes effect next
start" banner.

**Cause.** `set_value` matched `^\s*key\s*=` anywhere in the file and, when
the key was absent, appended at EOF - which on such a file is INSIDE the last
table. `tomllib` then parsed it as `proxy.mode`, top-level `mode` stayed
absent, `load_config` returned the old value and `_mode_needs_restart`
compared equal.

**Fix.** `set_value` searches and writes only the top-level block above the
first `^\s*\[` header, inserts a new key before that header (backing up over
the blank lines that separate the block from it) rather than at EOF, and then
re-reads the file through `load_config` to prove the value took, logging ERROR
and returning False when it did not (`config.py`, `set_value` / `_value_took`).
`settings_window.action_set_role` routes a False into its existing "Couldn't
save that - see the log" toast instead of announcing the new role.

**Tests.** `companion/tests/test_config.py` (a file with a `[proxy]` table:
top-level `mode` takes, `proxy.mode` untouched; a lying `load_config` makes
`set_value` return False) and `companion/tests/test_settings_window.py` (a
role that cannot be read back is reported, not celebrated).

### UX-2(a) - WIRED TO THE SERVER turned all syncing off with no confirmation - FIXED in repo 2026-08-28, unshipped

**Symptom.** An editor opens Settings out of curiosity and clicks WIRED TO
THE SERVER because their desk is in the office. config.toml is written with no
dialog at all and a toast that only says the role changed; from the next start
`sync_enabled` is False, every lane is dead, and an admin cannot even tick a
project for that machine.

**Cause.** `action_set_role` gated only the DANGEROUS direction (to editor,
behind the typed-word "REMOTE" dialog, because lane B can delete on a real
base rig) on the argument that the base direction "is always safe". Safe from
data loss is not the same as safe: it is the one click that stops all syncing
on a machine that needs it.

**Fix.** The base direction now takes the popup lock the same way and asks
through `popup.confirm_dialog` (the plain yes/no variant of the same dialog
family, since nothing is deleted) with the consequence spelled out: no
uploads, no proxy downloads, no shared project files, and no ticks from the
admin (`companion/src/ccsync_companion/settings_window.py`,
`action_set_role`). Declining writes nothing.

**Tests.** `companion/tests/test_settings_window.py`: the dialog is asked
before anything is written and its copy names the consequences (and carries no
em dash); declining leaves `mode` alone and releases the lock; a second window
already open refuses without asking.

### APP-3 - both persistent safety latches lived in the directory support tells people to delete - FIXED in repo 2026-08-28, unshipped

**Symptom.** Lane B's breaker trips, or an admin sets a fleet halt. Support
(or the editor, following an old note) does the usual "close CCSync, delete
`~/.ccsync/state`, start it again" - and the breaker only a human may clear,
plus a fleet halt set on the dashboard, clear themselves on that machine.

**Cause.** `lane_b_breaker.json` and `sync_halt.json` were written under
`<log dir>/state/`. Both were made persistent precisely so a restart could not
clear them, and then placed where a restart-adjacent ritual does -
`machine.py`'s own comment names `state/` as "the directory a support session
is most likely to be told to delete", and `upgrade.py` moved the downgrade
floor out for exactly this reason.

**Fix.** Both latches now live in `config_mod.CONFIG_DIR`, beside
`machine.json` and `upgrade_floor.json` (`companion/src/ccsync_companion/app.py`,
the "two safety latches" block in `CompanionApp.__init__`), and
`lane_guard.adopt_legacy_latch()` MOVES a latch written by an older build into
the new place once, on start - a copy would let a downgrade re-latch on stale
state, and no adoption at all would have cleared a live latch on every machine
the move was meant to protect. The Syncthing supervisor's incident record
stays under `state/`: it is diagnostics, not a latch.
`docs/SYNC_SAFETY.md` updated.

**Tests.** `companion/tests/test_lane_guard.py` (adoption moves the file and
leaves nothing behind; it never overwrites a latch already in the new place;
it is a no-op without a legacy file; a fresh trip writes to the new location
and no `state/` dir is created) and `companion/tests/test_sync_halt.py` (both
latch paths are `CONFIG_DIR`; a fleet halt written by an older build under
`state/` is still in force after the move; the supervisor state is
deliberately NOT beside them).

### RES-2 - the unprompted-rewrite rate limiter lived only in RAM - FIXED in repo 2026-08-28, unshipped

**Symptom.** A machine with a wrong `canonical_prefix`/`local_root`
auto-relinks a project, the tray restarts (an OTA, an auto-update, an EULA
park, a crash, or the editor quitting and reopening it), and the same
unprompted rewrite of hundreds of clip paths runs again. Nothing bounded the
day: at one pass per 15 minutes a permanently misconfigured machine was
entitled to ~96 project-database rewrites the editor never asked for, and
nobody was ever told.

**Cause.** `_automatic_at`, `_save_points` and `_sessions` were module
globals, and both bars were monotonic - CLAUDE.md's own rule is "never make a
safety latch in-memory-only".

**Fix.** `resolve_journal.allow_automatic` now works on WALL clock and
persists the 15-minute bar to `~/.ccsync/state/resolve_auto.json`, loaded
lazily on the first call and written tmp + `os.replace`
(`companion/src/ccsync_companion/resolve_journal.py`: `auto_state_path`,
`_load_auto_state_locked`, `_save_auto_state_locked`). A stamp in the future
(a clock put back, a state file copied off another machine) is clamped to
"now" AND the correction is written back, or the same stamp would be
re-clamped forever and the pass would never be allowed again. Alongside it a
per-project daily cap (`AUTOMATIC_MAX_PER_DAY = 8`, counting both unprompted
sources together) which, when it holds a pass, logs a WARNING naming the
project and saying "this looks like a configuration problem, tray -> Copy
diagnostics". `_save_points` stays in memory on purpose: it is a cost limiter,
and a restart taking one extra save point is the safe direction.

**Tests.** `companion/tests/test_resolve_journal.py`: the bar still holds
after a simulated restart and expires correctly across one; a future stamp is
treated as now and does not bar forever; unreadable state never stops a
relink; the daily cap allows exactly N, is per project, counts both sources
together, resets the next day, and its log line names the fix.

### APP-1 - nobody was told when the dashboard stopped accepting this machine's reports - FIXED in repo 2026-08-28, unshipped

**Symptom.** An admin revokes an editor's `cce1.…` token, or an installer typo
leaves a wrong port in `dashboard_url`, and nothing anywhere says so. The lanes
keep syncing, the tray stays green, and the machine simply goes dark on the
fleet grid. The log carried one WARNING for the whole streak and DEBUG for
every failure after it, so a 401 (a human has to act) was indistinguishable
from a five-second timeout (the NAS is rebooting). `build_diagnostics()` -- the
bundle an admin actually asks for -- printed `dashboard_url` and never "has
anything this machine sent ever been accepted".

**Cause.** `DashboardReporter` kept no health state at all. `_run_cycle`'s
`self._error_logged` was the entire memory of a failure streak, it lived in
RAM, and no consumer of the report or the tray could read it.

**Fix.** `reporter.py` now keeps `last_success_at` (wall clock), `last_status`
(`"ok"` / `"HTTP 401"` / the exception class name) and `consecutive_failures`,
and persists the first two plus the measured clock skew to
`~/.ccsync/state/reporter.json` with tmp + `replace`
(`reporter.py:_load_state`/`_save_state`) -- "not reachable since Tuesday" is
precisely the fact a restart used to destroy. The record is kept in `post_once`
rather than in `_run_cycle` (`reporter.py`, around the `self._http_post` call)
so a tray "Sync now" counts the same as a loop tick; `_run_cycle` counts the
failures that never reached the POST. `health()` rides every report tick inside
`sync_guard` as `reporter: {last_success_at, last_status,
consecutive_failures}` (`app.py:sync_guard`), which is the one channel an admin
has. 401/403 gets a single toast ("Your CCSync credential was rejected by the
dashboard - sign in again", wired through the new `notify=` argument to
`self._notify_tray`) and re-logs at WARNING every hour instead of falling to
DEBUG (`AUTH_RELOG_SECONDS`). A new diagnostics section, `-- last dashboard
report --`, names the last accepted report, the last status, the streak and the
clock. Past ten failures in a row the Settings window carries a line
(`tray._reporter_line`, rendered from `settings_window.py`'s SYNC LANES
section), which names a rejected credential differently from an unreachable
server because they are different people's jobs.

**Tests.** `companion/tests/test_reporter_health.py` (health record, streaks,
the "HTTP 401" spelling, persistence across a restart, a corrupt state file, the
one-and-only-one credential toast, the hourly re-log, the tray line and its
threshold) and `companion/tests/test_app.py` (the `sync_guard` block, the
diagnostics section, a broken `health()` not taking the guard down).

### APP-6 - a crash report was written and surfaced nowhere - FIXED in repo 2026-08-28, unshipped

**Symptom.** `crash_report.py`'s own docstring names "the tray stayed up with a
dead lane" as the failure it exists to fix. A background thread raising out of
an unsupervised call wrote `~/.ccsync/crashes/<stamp>-<thread>.json` and one
ERROR line that rotates away at 5 MB. The tray stayed green, the dashboard
never heard, and `build_diagnostics()` did not mention that the directory
existed.

**Cause.** The writer had no reader. Nothing counted the files, and neither the
report payload nor the diagnostics bundle nor any tray line knew about them.

**Fix.** `crash_report.crash_summary()` returns `{count, newest}` from a
bounded, name-sorted scan of `crash_dir()`, cached for `SUMMARY_TTL_SECONDS`
and invalidated by `write_report` itself so the next report tick carries the
crash that just happened (`crash_report.py`). `install()` logs at WARNING what
an earlier run left behind -- a machine that starts with crash files is a
machine that has been failing and restarting. `app.sync_guard()` adds
`crashes: {count, newest}`, omitted while the count is zero on the same terms as
`skipped_exists`. `build_diagnostics()` gains a `-- background task failures
(crash reports) --` section listing the newest three with their exception type
and thread (`crash_report.recent_reports`), and `tray._crashes_line` puts "A
background task failed on this computer … Copy diagnostics for your admin" in
the Settings window while the count is non-zero.

**Tests.** `companion/tests/test_crash_report.py` (the summary before and after
a write, cache invalidation, the exception type in `recent_reports`, an
unreadable crash file reported rather than dropped, a hopeless config, the
install-time log) and `companion/tests/test_app.py` (`crashes` in `sync_guard`,
the diagnostics section) and `test_reporter_health.py` (the tray line).

### APP-13 / SYS-4 - nothing measured this computer's clock, while the server's own time was in every report reply - FIXED in repo 2026-08-28, unshipped

**Symptom.** A dead CMOS battery, a VM resumed from a snapshot or a Mac back
from sleep before NTP catches up, and two independent things break silently.
Lane B passes rclone `--min-age 60s`, and rclone ages a remote file against the
LOCAL clock: with a slow clock every file on the NAS looks like it was written
in the future, the pass excludes all of them, exits 0, and the lane reports
idle and green while the editor downloads no proxies at all. Separately a clock
far in the future invalidates a pre-CR-86 identity token instantly, and the
editor is told their sign-in expired -- a lie they cannot act on, because
signing in again yields a token the same clock rejects.

**Cause.** `api_report`'s reply has carried the server's own `received_at`
(`api.py:5453`) for months and `post_once` threw it away. There was no skew
check anywhere in either component.

**Fix.** `reporter._note_clock_skew()` parses the reply's `received_at`
(`parse_server_time`, tolerant of a naive stamp read as UTC, since guessing the
other way is what CR-89 cost the dashboard), stores
`clock_skew_seconds` in memory and in `reporter.json`, and logs a WARNING at
most once an hour past `CLOCK_SKEW_WARN_SECONDS` (5 minutes). The value rides
`sync_guard` as `clock_skew_seconds`, absent until a reply has carried one --
"could not check" must not render as zero. Past 60 s
`tray._clock_skew_line` says "This computer's clock is 20 minutes behind the
server's. Sync will not work correctly until it is fixed", and
`build_diagnostics()` carries the signed value. The identity-expiry toast now
goes through `app._identity_expired_text()`, which names the clock instead of
the sign-in when the measured skew is large. An older dashboard sends no
`received_at`: that is a `None`, never an exception.

**Tests.** `companion/tests/test_reporter_health.py` (skew computed from the
reply, an absent field leaving `None` rather than zero, junk values, a naive
stamp read as UTC, the hourly warning, persistence across a restart, the phrase
helper, the tray line) and `companion/tests/test_app.py` (the toast switching
on skew, the diagnostics line).

### SYS-3 / SYNC-8 - report telemetry the companion sends was discarded at the model boundary, for the third time - FIXED in repo 2026-08-28, unshipped

**Symptom.** The companion computed `sync_guard.syncthing_supervisor` (how long
that machine's Syncthing engine has been down, how many automatic restarts have
failed, the last error) and sent it on every report for weeks. Nothing on the
dashboard ever showed it, and no log line anywhere said so. Before it, the same
mechanism lost `transport_health` for months (B17) and `proxy_coverage` /
`youtube_import` for about a year each. Every occurrence was found by a human
reading the source, never by a signal.

**Cause.** `ReportIn` used pydantic's default `extra="ignore"`, so an
undeclared top-level key (and, on `SyncGuardIn`, an undeclared sub-key) was
dropped silently by the model before the route body ran. The companion's own
source said so out loud at `app.sync_guard()`: "THE DASHBOARD DOES NOT READ
THIS YET ... `extra='ignore'` drops it".

**Fix.** `ReportIn` and `SyncGuardIn` now carry
`model_config = ConfigDict(extra="allow")`
(`dashboard/src/ccsync_dashboard/api.py`, `ReportIn` / `SyncGuardIn`), and
`api_report` names what it does not read: `undeclared_report_sections()`
collects the top-level extras plus the `sync_guard.*` extras,
`_ignored_sections_to_log()` logs one WARNING per (machine, key) per UTC day
(a 30 s cadence would otherwise write 2,880 identical lines a day and roll the
log away), and `db.record_ignored_report_sections()` keeps a bounded `meta`
record that `build_editors_view` publishes as `ignored_report_sections` and
`templates/partials/fleet_grid.html` renders as
`[ N REPORT SECTIONS IGNORED: ... ]`. Then the sections themselves were
declared: `SyncthingSupervisorIn`, `ReporterHealthIn`, `CrashesIn`,
`SyncConflictsIn` plus `clock_skew_seconds` and `folders_unfiltered` on
`SyncGuardIn`, flattened by `flatten_sync_guard` into twelve v30
`machine_state` columns and chipped on the fleet grid
(`[ SYNC ENGINE DOWN 6h, 3 RESTARTS FAILED ]`, `[ CRASHES: n ]`,
`[ UNFILTERED FOLDERS: n ]`, `[ CONFLICTS: n ]`). All four follow the LATCH
rule rather than COALESCE: the supervisor section is empty-when-healthy by the
companion's design, so a guard-bearing report that omits it has to be able to
clear the incident. The new sub-models inherit a bounding validator
(`_BoundedSectionIn`, extracted from `_ReportSectionIn` as
`_bound_to_field_caps`) and `SyncGuardIn` now bounds its own fields too, because
`sync_guard` is not one of `ReportIn`'s tolerant sections and a raising cap
there would have 422'd the whole report - taking the lanes, transfers and
presence with it, and silencing the very alarm the section carries (B6).

**Tests.** `server/tests/test_cross_component.py` gains the parity gate the
finding asked for, in the same shape as the VIDEO_EXTS gate above it: an `ast`
walk of `reporter._build_payload`, `app.sync_guard` and
`rclone_lane.sync_guard_report` collects every dict key the companion CAN emit
and asserts each is declared, plus a test that neither model may go back to
`extra="ignore"`. `dashboard/tests/test_report_ingest_health.py` covers the
accept-and-record path, the namespaced sub-key, the once-a-day log, the
accumulate-not-replace record, every bound on it, an unparseable meta row, the
flattening, the clear-on-absence rule, tri-state `supervising`, and the
truncate-instead-of-422 behaviour.

### SYS-4 - retention and eviction read a client-supplied clock (dashboard half) - FIXED in repo 2026-08-28, unshipped

**Symptom.** A machine whose clock is far out (a VM resumed from a snapshot, a
dead CMOS battery, a Mac back from Time Machine) either vanishes from the fleet
grid on every prune while reporting perfectly, or pins itself as "most recent"
for ever and evicts its owner's genuinely live computers. Nothing anywhere in
either component measured clock skew.

**Cause.** `db.prune()` deleted `machine_state` rows on `reported_at < cutoff`
and `evict_extra_machines` ordered by `reported_at` - a column whose NAME says
the client supplied it, while every neighbouring table correctly uses
`received_at`/`refreshed_at`. api.py happened to pass the server's own
timestamp into it, so the bug was latent rather than live; the next hand that
passed the companion's value in would have made it real, and the companion's
timestamp had nowhere else to go.

**Fix.** v30 (`db.py`, `SCHEMA_V30`) adds `machine_state.received_at` (the
server's clock, backfilled from `reported_at`), `client_reported_at` and
`clock_skew_seconds`. `db.clamp_reported_at()` is the new pure helper: it
measures skew, stores the client's value as-is inside a 7-day window, and past
that replaces it with our own `received_at` while keeping the measurement -
a broken clock does not get to be a stored ordering key. An unreadable
timestamp comes back `(None, None, True)`, never as no-skew.
`upsert_machine_state` takes `client_reported_at` and writes all three;
`prune()` and `evict_extra_machines()` now read
`COALESCE(received_at, reported_at)`. Past `CLOCK_SKEW_WARN_SECONDS` (60 s,
twice lane B's `--min-age 60s`) `build_editors_view` chips
`[ CLOCK 20m SLOW ]` with a tooltip explaining that lane B can transfer
nothing at all with a clock that far out.

**Tests.** `dashboard/tests/test_report_ingest_health.py`: the clamp's three
outcomes, both clocks and the skew stored from a real report, a machine 40 days
behind real time surviving a prune while a genuinely silent one still ages out,
and a machine claiming 2098 losing the eviction race to twenty live ones.

### UX-2(b) - an editor who stops syncing for ever keeps a green dot - FIXED in repo 2026-08-28, unshipped

**Symptom.** An editor clicks Settings -> WIRED TO THE SERVER, or SIGN OUT, or
Quit. The lanes stop and, for the first two, so does the reporting. The dot the
owner scans on the dashboard stays GREEN for a machine that has been dark for a
week.

**Cause.** `health.editor_status` reddens on a lane error, on being offline
WHILE BEHIND, and on stale completion. An editor who was caught up when they
clicked has `behind=False`, so none of the three fires. On the fleet grid the
row's dot is `worst()` over the lane chips, and a machine that stopped
reporting has its last lane states frozen mid-green.

**Fix.** `health.py` gains `report_freshness()` and the thresholds the finding
named: no report for `>= 3 * STALE_REPORT_SECONDS` (15 min) is AMBER, `>= 6 h`
is RED, with a reason string naming the last report time. It is read
INDEPENDENTLY of `behind` inside `editor_status` (new `last_report_at`
keyword), and `build_editors_view` folds the same colour into each fleet row's
`worst()` and publishes `status_reason` as the dot's tooltip
(`templates/partials/fleet_grid.html`). health.py stays pure - no I/O, one new
function and two constants. `last_report_at=None` is deliberately not amber: a
Syncthing device with no companion row is the `unmapped` case, which the grid
already labels. An unparseable timestamp is AMBER with the reason naming it,
never green.

**Tests.** `dashboard/tests/test_report_ingest_health.py` (the UX-2b block):
green/amber/red on a caught-up machine by report age alone, None left alone,
the reason naming the timestamp, an unreadable timestamp not rendering as fine,
the thresholds themselves, and a fleet row with three frozen-green lane chips
coming out RED.

### DASH-16 - a computer that dies is pruned out of the fleet rather than marked lost - FIXED in repo 2026-08-28, unshipped

**Symptom.** An editor's PC dies, or an editor leaves and takes the laptop. The
grid does the right thing for a day; at 14 days the machine's media presence
disappears; at 30 days its `machine_state` row is deleted and the computer
quietly leaves the page, while its `machines` registry row, its `selections`
plan and its Syncthing share all remain. The fleet looks healthier than it is,
and a Syncthing device that still holds project data is shared with nothing
watching it.

**Cause.** Every fleet row was derived from a status table with its own
retention (`MACHINE_STATE_MAX_AGE_DAYS` = 30, `MEDIA_REPORT_MAX_AGE_DAYS` =
14). The registry row that survives every prune was never rendered.

**Fix.** `db.lost_machines()` returns registry rows whose `last_seen` is older
than `LOST_MACHINE_DAYS` (7) together with the plan each one still holds;
`build_editors_view` publishes the ones with no live row of their own as
`lost_machines`, `_scope_editors_view` redacts them the way it redacts the rows
beside them, and `templates/partials/fleet_grid.html` renders a
`[ LOST COMPUTERS ]` table with the still-planned projects and a `[ FORGET ]`
button. The button posts to a new `ui.partial_admin_forget_lost_machine`, which
is `forget_machine_everywhere` (CR-76, the same call the Users page's
[ REMOVE ] makes) re-rendering the fleet grid rather than the users partial.

**Tests.** `dashboard/tests/test_report_ingest_health.py` (the DASH-16 block):
a machine whose `machine_state` row is pruned away still appears as a LOST row
carrying its tick, a machine still on the grid is never also listed as lost,
and a machine that reported a minute ago is never lost.

### DASH-4 - an empty Syncthing folder list deactivated every project - FIXED in repo 2026-08-28, unshipped

Symptom: Syncthing on the NAS comes back with a default or restored config it
could not load, answers `/rest/config` with 200 and zero folders, and its
`myID` is perfectly valid, so none of the empty-myID guards fire. Fifteen
minutes later every project was `active=0`; the hourly prune's
`purge_nas_media_for_inactive` then deleted all of `nas_media` and
`nas_inventory_state`. The project list and fleet grid emptied out,
`fetch_sync_backlog` (which joins `p.active = 1`) reported nobody behind, and
`api_tick` answered `404 unknown or inactive project` so an admin could not
even re-tick. All of it silent.

Cause: `db.deactivate_missing_projects` had no floor at all - it trusted
whatever `seen` list `collector._run_config` handed it, while the enforce
cycle one function up has had a blast-radius brake for a year.

Fix: the same brake, in `db.py:deactivate_missing_projects`
(dashboard/src/ccsync_dashboard/db.py:1430). One trigger, two wordings: any
pass that would deactivate more than `max(2, 25%)` of active projects is
refused, and an empty `seen` gets its own sentence because "Syncthing reported
0 folders" is the signature an operator needs to read rather than a
percentage. The floor of 2 is what keeps a one- or two-project site able to
retire its projects legitimately. The refusal is
persisted to `meta` with the counts that produced it
(`db.META_DEACTIVATION_REFUSAL`), the next healthy pass is the only thing that
clears it, and `collector._run_config` (collector.py:931) logs it and returns
"refused deactivating N project(s)" as the cycle's note. The fleet page raises
a red banner carrying the message ("Syncthing reported 0 of 37 folders - not
deactivating anything") from templates/partials/fleet_grid.html, and
`/api/v1/health` returns it under `collector_alarms`. `force=True` applies a
pass whatever its size.

Tests: `dashboard/tests/test_db.py` (six cases: empty list, over-ceiling,
under-ceiling-applies-and-clears, the only project, force, the grace window),
`test_collector.py::test_an_empty_folder_list_does_not_empty_the_project_list`
(four folders vanish and come back, end to end through the collector, note and
alarm asserted), `test_api.py` for the banner and the health field.

### DASH-5 - an unmounted project dir wiped that project's NAS inventory - FIXED in repo 2026-08-28, unshipped

Symptom: the ZFS dataset under `/projects/<project>` is not mounted when the
container starts (pool import ordering after a NAS reboot), or a project is
renamed by hand while the inventory cycle runs. `/projects` is the bind mount
point so it exists, the project dir exists and is empty, the walk returns `[]`
- and `replace_nas_media` deleted the whole inventory and wrote the rollup as
0 originals / 0 proxies with `last_error` NULL. Every media-presence view then
said the NAS holds nothing, and the backlog reported every original an editor
holds as "the NAS is missing this": the page telling the owner his footage is
not on the server.

Cause: an unconditional `DELETE FROM nas_media WHERE project_id=?` followed by
zero inserts. No floor, no "this looks wrong" check, and an empty directory
was indistinguishable from an absent one.

Fix: `db.replace_nas_media`
(dashboard/src/ccsync_dashboard/db.py:3513) refuses a walk that takes a
project from originals to none, or that drops more than 90% of its files,
unless `force=True`: the previous inventory stays, `tree_sig` is deliberately
NOT advanced (so the next cycle walks again rather than believing itself up to
date), and `nas_inventory_state.last_error` becomes "walk returned 0 of N
files - not replacing". `fetch_nas_media_summary` carries `last_error` and
`walked_at` now, and the project page renders a red [ NAS INVENTORY NOT
UPDATED ] line above the figures (templates/partials/project_detail.html).
Plus the not-mounted canary in `collector._run_inventory`: a `Projects/` with
zero entries skips the whole cycle with a note, and a project dir with no
media AND no `.stfolder` is recorded as "it looks unmounted, not empty" rather
than walked.

Tests: `dashboard/tests/test_inventory.py` (seven cases: collapse to zero, the
90% floor, force, a genuinely-empty first walk, and three end-to-end through
the collector for an emptied dir, a marker-less dir and an unmounted
`Projects/`), `test_api.py` for the project-page line.

### DASH-3 - the enforce blast-radius brake fired into the container log and nowhere else - FIXED in repo 2026-08-28, unshipped

Symptom: Syncthing is restarted with a re-created config, or four editors'
devices are not yet approved, so the next enforce cycle computes more share
removals than `DASH_ENFORCE_MAX_REMOVALS` and refuses them all. `_timed`
recorded the cycle as ok (nothing raised), so `poll_runs`, `/api/v1/health`
and the whole UI said enforce was fine while every genuine untick since -
including an admin unticking a project to stop an editor filling their drive -
went unapplied. The state was per-cycle and in-memory: a container restart
lost even the log line.

Cause: the brake's only output was `log.error("REFUSING %d share
removal(s)...")`.

Fix: `collector._run_enforce`
(dashboard/src/ccsync_dashboard/collector.py:1151) persists the refusal
through `db.record_enforce_refusal` (timestamp, count, limit, the folder and
device sets, the capped pair list) and clears it on the first pass that comes
in under the limit; it also records the +/- it was about to apply through
`db.record_enforce_plan`, before the HTTP loop and committed there for the
same reason the seed is. `/api/v1/health` returns both under
`collector_alarms`; the fleet page raises a red banner ("N share removal(s)
refused: shares are FROZEN...") and renders a read-only pending-diff table in
a new [ COLLECTOR ] panel (templates/partials/collector_health.html). The
panel names Syncthing device ids, so `api._scope_editors_view` drops the whole
block for non-admins.

Tests: `dashboard/tests/test_enforce.py` (refusal persisted with the right
pairs, the note on `poll_runs`, the alarm clearing on a sane pass, the plan
recorded and reset to empty when nothing is pending), `test_api.py` (health
field, banner, panel, and that an editor sees none of it).

### DASH-14 - a cycle that early-returned or refused was recorded as a successful poll - FIXED in repo 2026-08-28, unshipped

Symptom: Syncthing answers with an empty `myID` for ten minutes during a
restart, so `_run_enforce` returns immediately every cycle - and `poll_runs`,
`/api/v1/health`'s `last_polls` and every view said enforce last ran
successfully N seconds ago. Three distinct "I did nothing" outcomes (empty
myID, a refused removal pass, a seed that could not be marked done) were
indistinguishable from "I reconciled everything".

Cause: `_timed` already stores a note a runner returns (the mechanism
ops-efficiency-5 added for completion's "partial: ..."), and none of these
runners returned one.

Fix: `_run_config`, `_run_enforce` and `_run_inventory` return notes now
("skipped: empty myID", "refused N share removal(s)", "seed deferred: ...",
"refused deactivating N project(s)", "skipped: the Projects tree looks
unmounted", "kept N project inventory(ies): the walk collapsed"). New
`db.collector_health` reads the last run per kind with its note and colours a
kind amber when the note is non-empty, red when it failed, and the [ COLLECTOR
] panel on the fleet page renders the note under WHAT IT DID NOT DO.

Tests: `dashboard/tests/test_enforce.py` (empty myID on both halves, the
refusal note, amber status), `test_collector.py` (a clean cycle stays green,
the deactivation note), `test_api.py` (the panel renders the note and an
[ INCOMPLETE ] chip).

### SYS-11 - no audit trail: "who unticked this, and when" was unanswerable - FIXED in repo 2026-08-28, unshipped

Symptom: an editor says a project stopped syncing on Tuesday. With two admins
on the dashboard, nothing in the product could say what changed on Tuesday.
Selections were DELETEd in place, and the fleet halt, the lane B resume,
pushed updates and file moves each kept some state in four different shapes,
none of them a timeline. The only history was a handful of `log.warning` lines
in a container log that rotates.

Cause: there was no history table. `grep -n audit dashboard/src/ccsync_dashboard/`
returned nothing, and every state-changing route wrote only the new state.

Fix: one append-only ledger, `fleet_audit(id, at, actor, action, subject,
detail_json)`, schema v31 (`db.py:966` SCHEMA_V31, migration step at
`db.py:1019`), with one helper `db.audit()` (`db.py:2888`) written from the
routes that already exist: tick and untick from both the JSON API and the
htmx checkbox (`api.py:1928`, `api.py:1954`, `ui.py:855`, through the shared
`api.audit_plan_change`), fleet halt set/clear and lane B resume and pushed
update inside the db functions that already carry the actor
(`db.set_fleet_halt`, `db.request_lane_b_resume`, `db.request_machine_update`,
`db.record_file_move`), user delete and machine forget in the one
implementation both doors share (`api.delete_user_everywhere`,
`api.forget_machine_everywhere`), package publish/make-current/delete
(`api.py:4210,4225,4256`, `ui.py:2018,2110`), device approval
(`api.py:3855`) and site settings save/import (`setup_routes.py:231,268`).
Retention is a single DELETE in the existing prune cycle at 180 days
(`db.py:4195`) - the only statement in the product that removes a row from
this table. The timeline is a Settings-hub page, `/admin/audit`
(`ui.py:1125`, `templates/admin_audit.html`,
`templates/partials/admin_audit.html`): last 200 rows newest first, with a
filter over subject, actor and action.

Tests: `dashboard/tests/test_fleet_audit.py` - a row for tick, untick, halt
from both doors, machine forget, make-current, pushed update and resume; that
the htmx checkbox is not a softer door than the JSON route; that a no-op tick
writes nothing; the subject filter; the page render; admins only; and the
180-day prune.

### DASH-8 - a tick or untick left no record of who did it, and no undo - FIXED in repo 2026-08-28, unshipped

Symptom: an admin unticks a project on the wrong row of the fleet grid - or
unticks with no `?machine=` from a stale page, which removes it from every
computer that person owns, deliberately. Within one enforce cycle the folder
is unshared from all of them and the editor's companion stops syncing the
project. There was no page that said who did it and no way to put it back
except remembering what had been there.

Cause: `remove_selection` DELETEs the rows. `selections` kept `created_by`
and `created_at` for an add and nothing at all for a removal, so both the
history and the material an undo would need were gone at the moment they were
needed.

Fix: three parts, on top of SYS-11's ledger. (1) A "recent plan changes"
panel on the fleet page (`ui.py:1037` and its partial
`templates/partials/plan_changes.html`, included from `fleet.html` for admins
only) listing the last hour's ticks and unticks with a one-click [ UNDO ]
(`ui.py:1044`). The undo is a RESTORE of the audit row's `before` placements,
not an inverse action: a person-level untick removed rows from several
computers, each possibly in a different mode, so re-ticking "the project"
would hand every one of them a full sync. It is itself audited, an
already-undone row is marked rather than hidden, and a change older than an
hour is refused in words rather than silently. (2) The enforce cycle holds an
existing share whose UNTICK is less than 60 s old (`collector.py:1087` and
`db.recent_plan_change_devices`), so an undo inside the window costs Syncthing
nothing. Deliberately narrow, both halves measured on 2026-08-28: it never
delays an ADDITION (that would hand back the 2026-07-26 nudge fix), and it
never freezes on row FRESHNESS - an upload-only tick writes a fresh row for a
machine whose share must be REMOVED, and freezing on `selections.changed_at`
held it (caught by
test_the_enforce_cycle_never_shares_a_folder_for_an_upload_only_tick).
`changed_at` (v31) is still stamped, because `created_at` cannot say when a
tick last changed mode. (3) The three person-level untick controls - the sidebar
checkbox, the project page's [ UNTICK FOR ... ] and the queue panel's
[ UNTICK ] - now carry an `hx-confirm` naming the computers it will affect
("This removes 2025/FF4 from ruskin's 2 computers (EDIT-PC, LAPTOP)"), on the
way OUT only.

Tests: `dashboard/tests/test_fleet_audit.py` - the undo round-trip for a
person-level untick across two computers in two modes, for a tick, and for a
mode switch; the refusals (not a plan change, hour-old, missing row); the
panel's presence for an admin and absence for an editor and on an empty hour.
`dashboard/tests/test_enforce.py` - a fresh untick keeps its share for one
cycle and loses it on the next, and a fresh tick is never delayed.

### YT-1 - nothing on an editor's machine ever updated yt-dlp on its own initiative - FIXED in repo 2026-08-28, unshipped

**Symptom.** YouTube ships a change; yt-dlp fixes it within the week; every
machine in the fleet sits on a binary that cannot download while logging
"yt-dlp X is current" nightly, and the only cure is a dashboard release plus an
OTA. CR-80 and CR-83 were both this shape, and both were reported by an editor
rather than noticed by the dashboard.

**Cause.** `ytdlp_manager.ensure()` updated only on `if floor and
version_is_older(current, floor)`, and that floor is `DEFAULT_MIN_YTDLP_VERSION`
- a constant in a dashboard release, overridable only by a hand-typed env var.
`_maybe_poke_ytdlp` (added so a download failure triggers a re-check) called the
same `ensure()`, re-read the same unchanged floor, and did nothing. Server side,
nothing anywhere measured the age of the yt-dlp the container was running.

**Fix.** A MAX-AGE rule: yt-dlp's versions ARE release dates, so
`ytdlp_manager.version_age_days` (companion/src/ccsync_companion/ytdlp_manager.py:364)
ages the installed version locally and `_enforce_max_age` (:696) runs
`self_update()` past `ytdlp_max_age_days` (config default 21, 0 switches it off)
regardless of the floor, publishing `ACTION_UPDATED`, or the new `ACTION_STALE`
(:149) with `ok=True` and the age in the message when `-U` could not help. It
never fires on the `ytdlp_path` override branch (which returns first: an
editor's own binary is theirs), never rolls backwards (`-U` goes to latest
stable only, and the reported version is always the one actually installed), and
never fires on an age it cannot compute - an unparseable version or one dated in
the future is "cannot tell", not "stale". Server side `/ytdl/api/health` now
carries `yt_dlp_age_days`, `yt_dlp_stale` and `yt_dlp_age_detail`
(ytdl/web/ytdlweb/routes_api.py:168-170, :197-250) against
`config.YTDLP_MAX_AGE_DAYS` (ytdl/web/ytdlweb/config.py:274-303, env
`YTDL_YTDLP_MAX_AGE_DAYS`, same 21 days), and the health strip's yt-dlp pip goes
amber with the age in it (ytdl/web/static/app.js).

**Tests.** companion/tests/test_ytdlp_manager.py: the age parser, the update
with no floor at all, the inside-the-window no-op, the config override and
off-switch, the junk value, the named-`stale` failure, "nothing newer to take",
the override branch never being touched, and a version that cannot be aged never
being updated on a guess. The suite now runs against a FROZEN clock (`_NOW`,
`_days_ago`) because the rule made `ensure()` time-dependent.
ytdl/web/tests/test_api.py: the age and the warning flag, the unrankable/future/
absent cases, and the off-switch.

### YT-9 - the AI CLI was handed the dashboard's entire secret environment - FIXED in repo 2026-08-28, unshipped

**Symptom.** A site turns on `ai_cli_providers`; the wizard installs `claude`;
an editor's search runs it over YouTube titles and descriptions - untrusted,
attacker-controlled text - in the container that holds the fleet's credentials.

**Cause.** `cli_tools.STRIPPED_ENV_VARS` was exactly four names (three API keys
plus `ANTHROPIC_AUTH_TOKEN`) and `cli_env` was `dict(os.environ)` minus those
four, so the CLI received `DASH_SESSION_SECRET`, `DASH_REPORT_TOKEN`,
`SYNCTHING_API_KEY`, `TRUENAS_API_KEY`, `BROLL_INGEST_TOKEN` and
`DASH_RELEASE_PUBKEYS`. Both modules' docstrings asserted the posture was "the
container's own AI keys are removed"; nothing stated or enforced that the rest
was withheld, because it wasn't.

**Fix.** `cli_env` is an ALLOW-LIST
(dashboard/src/ccsync_dashboard/cli_tools.py:301-372, :417-427): PATH, HOME,
LANG, LC_*, TZ, TERM, TMPDIR, the proxy variables in either case, the Windows
minimum a child process needs, and the publishers' own `CLAUDE_*` / `CODEX_*`
namespaces. One predicate, `env_var_allowed`, so the probe, the Test button, the
pty sign-in and the real ytdl call stay in agreement; the wizard's overlay is
applied after the filter and is not subject to it. `ytdlweb.ai_backend._cli_env`
carries the same list as a documented COPY that must not drift
(ytdl/web/ytdlweb/ai_backend.py:757-820) - the deployed ytdl app imports nothing
from the dashboard, the same rule as identity.py's copied properties. Both module
docstrings now state the posture.

**Tests.** dashboard/tests/test_cli_tools.py: no fleet credential (the six above
plus `TRUENAS_PW`) is in the child env even when set in `os.environ`, by name and
by value; and the other direction, that the locale, TMPDIR, proxy and publisher
variables still arrive. ytdl/web/tests/test_ai_backend.py: the same two, plus a
drift test asserting the ytdl copy's list and predicate equal the dashboard's
for every case.

### YT-3 - the pre-conversion original could become the fleet's permanent copy of a clip - PARTLY FIXED in repo 2026-08-28, unshipped

**Symptom.** An editor downloads a 1080p clip, YouTube serves VP9, a ten-minute
libx264 re-encode starts, and lane A's periodic pass runs during it. The VP9
file goes up under the final name; lane A is `copy --ignore-existing`, so the
first version of a name to reach the NAS is the only one that ever will. Every
other editor and every future project gets the undecodable copy, permanently,
with no error anywhere: CR-79's failure arriving through the sync lane.

**Cause.** The canonical tree IS the download workspace, and the only stability
gate on it is `--min-age 120s` - but neither executor passed `--no-mtime`, so
yt-dlp stamped the media response's `Last-Modified` (for YouTube, usually the
upload date, years back) on the finished file. It was eligible instantly.

**Fix.** `--no-mtime` in the companion executor's argv builder
(companion/src/ccsync_companion/ytdl_executor.py, `build_argv`) and
`updatetime: False` in the server's `build_opts`
(ytdl/web/ytdlweb/vendor/downloader.py), so `--min-age` is a real gate again on
both sides and a file that reaches the NAS from one is not datable differently
from the other. The lane-filter half of the finding (excluding `*.editready.*`,
`*.original.*`, `*.temp.*`, `*.f[0-9][0-9][0-9]*.*`, `*.failed` ahead of the
`+ *<ext>` block) belongs to `sync/rclone_lane.py` and was done by the sync
agent; neither half suffices alone, and the staging option (download outside the
tree) is still open.

**Tests.** companion/tests/test_ytdl_executor.py's argv contract test asserts
`--no-mtime`; ytdl/web/tests/test_downloader.py asserts `opts['updatetime'] is
False`.

### YT-6 - `.original.mp4` and `.editready.mp4` became second copies of the clip, in the media pool and on the NAS - FIXED in repo 2026-08-28, unshipped

**Symptom.** Two clips per converted download in a shared Resolve project, one
of them undecodable or truncated, plus a permanent second copy of the footage on
the NAS - and nothing anywhere explaining the odd name.

**Cause.** Three things at once. (1) `swap_in`'s fallback deliverable was
`<stem>.editready.mp4`, whose stem ends `.editready`, not `[id]` - and `[id]`
last in the stem is what the dedupe scan (`ytsearch._ID_RE`), `_landed_file` and
`youtube_import._is_clip_name` all anchor on. So it could not be swept (it was
the clip, YTDL-17) and could not be recognised as the clip either, which is how
a truncated `.editready` from a killed container sat in the canonical tree
matching lane A's `+ *.mp4` forever. (2) `_is_clip_name` excluded dotfiles,
`.partial/.tmp/.lock` and `.fNNN/.temp` stems but not `.editready` or
`.original`, both of which end `.mp4`, so the importer filed them into
`Master/Youtube` as extra clips. (3) Nothing ever removed a `.original` - the
pre-conversion download `swap_in` could not delete because Resolve had it open.

**Fix.** (a) The fallback deliverable is `<title>.converted [id].mp4`
(`ytdl_executor.converted_name` :1460 / `downloader.converted_name`), the marker
in FRONT of the id bracket so the stem still ends `[id]`. (b) `.editready` is
now an intermediate in both `_INTERMEDIATE_STEM_RE`
(companion/src/ccsync_companion/ytdl_executor.py:144),
`worker._INTERMEDIATE_STEM` (ytdl/web/ytdlweb/worker.py) and
`youtube_import._INTERMEDIATE_STEM_RE`, which the rename above is what made
safe; `.original` is excluded from the importer too but deliberately NOT from
either sweep, because an age rule over a shared folder must not be what deletes
footage. (c) `clear_aside_originals` (ytdl_executor.py:1272) and
`_retry_aside_originals` (worker.py) retry that delete id-scoped on the next
attempt at the same clip, when Resolve has usually let go; what they cannot
delete they report in bytes, and `reclaimable_note` / `_reclaimable_bytes` put it
on the clip row. `swap_in`'s own note now rides the row on both sides - the
server's through a new `notes` list on `ensure_edit_ready`/`_swap_in` and
`download()`'s `note` key, merged into `dl_error` on the done row.

**Tests.** companion/tests/test_ytdl_executor.py: `converted_name` including a
title with its own brackets, the locked-by-Resolve delivery and its note, the
`.editready`-is-litter / `.original`-is-not pair, the id-scoped retry with a
neighbour's file left alone, and the reported-not-forced case with the byte
formatter. companion/tests/test_youtube_import.py: both new intermediates are
never imported and a `.converted` deliverable still is.
ytdl/web/tests/test_downloader.py and test_worker.py: the same rename, the
retry, the reported bytes, and an end-to-end download whose clip row carries
both sentences. Three existing worker tests that pinned `.editready` as a
deliverable (YTDL-17's invariant) were updated to the new one.

### MEDIA-1 - a rebuilt index could serve a client an uncurated clip - FIXED in repo 2026-08-28, unshipped

**Symptom.** A client holding a share link saw, and could stream, a clip nobody
had curated into their folder: any clip that had inherited the `videos.id` of a
curated clip which had since left the archive. Nothing in the UI or the logs
said so, and the suite was green because its only renumbering test kept the
curated clip in the index.

**Cause.** `resolve_items` (broll/web/app/client_folders.py) read the item by
id, noticed the identity disagreed, tried `(share, rel_path)` -- and when that
found nothing KEPT the by-id row it had already read. `public_video_ids` is
built from `resolve_items`, and `routes_share._member_id` authorises the public
media and detail routes on it, so the intruder was published, drawn and served.
The fourth site of CR-63 (broll-1), which fixed `member_video_id` and the two
routes but not the function they fall back to.

**Fix.** broll/web/app/client_folders.py:555-570 -- the by-name row is now the
only answer in that branch (`video = <by name>`, which may be None), so an item
whose identity cannot be confirmed is dropped from the public list and reported
`missing` to the curator, exactly the verdict `member_video_id` already gave.
The docstring's promise was corrected with it.

**Tests.** broll/web/tests/test_client_folders.py
`test_a_rebuild_that_reuses_a_deleted_clips_id_serves_none_of_it`: curated clip
deleted, its id handed to a clip in another share, then the folder JSON, the
detail route and all three media routes are checked (404 each), plus
`public_video_ids` directly and the curator's `missing` row. It fails on the old
code.

### MEDIA-23 - pulling a clip out of a client folder 404'd after an index rebuild - FIXED in repo 2026-08-28, unshipped

**Symptom.** After a renumbering index build, the card popover correctly showed
a clip as held by a live client folder, but clicking to remove it answered
`404 "that clip is not in this folder"` while the client went on seeing it. A
note typed on such a clip disappeared the same way.

**Cause.** `client_folders.remove_item` and `set_note` matched
`video_id = ?` against the id the panel sends, which is the id the index has
NOW, not the id the item was stored under. `routes_client_folders.list_folders`
already resolves identity the right way (by id OR by `(share, rel_path)`) for
the tick, which is why the tick was right and the action was wrong. Sites four
and five of CR-63's family.

**Fix.** broll/web/app/client_folders.py:424-468 -- a shared `_identity_of`
helper reads the current `(share, rel_path)` for the id and both statements now
match `video_id = ? OR (share = ? AND rel_path = ?)`; a caller with no index
connection, or a clip that has left the index, gets the empty pair, which no
row carries, so the behaviour falls back to id-only rather than matching
everything. routes_client_folders.py:243-265 passes the index connection.

**Tests.** broll/web/tests/test_client_folders.py
`test_pulling_a_clip_out_of_a_folder_works_after_a_renumbering_rebuild`: note
then delete under the new id, the client's page emptied, and a clip that really
is not in the folder still 404s on both routes. It fails on the old code.

### MEDIA-22 - revoking a share link did not stop playback for an hour - FIXED in repo 2026-08-28, unshipped

**Symptom.** Revoke is the control the client-folders design leans on for "the
link got away", and the page JSON obeyed it at once, but proxies, sprites and
posters carried an hour of private cache: a client mid-session kept playing and
the browser was entitled not to re-ask at all until the hour was up.

**Cause.** `routes_share._MEDIA_CACHE = "private, max-age=3600"`, against a
module docstring and docs/CLIENT_FOLDERS.md that both promise the next request
after a revoke is refused.

**Fix.** broll/web/app/routes_share.py:206-215 -- `private, no-cache`, which
means "ask before reusing", not "do not store"; and
broll/web/app/media.py:36-49,66-79,109 gives `serve_file_with_range` a weak
ETag over size+mtime and answers a matching `If-None-Match` with 304, so the
re-ask costs a round trip rather than the file and the bandwidth win the hour
of cache was there for is kept. Both docstrings that promised the old
behaviour were corrected, including the honest limit: revoke stops the next
fetch, not the second of video already decoded in the element.

**Tests.** broll/web/tests/test_client_folders.py
`test_share_media_is_revalidated_not_cached_for_an_hour`: no `max-age` on any
of the three media routes, an ETag present, a conditional re-request answered
304, and the same conditional request after a revoke answered 404.

### MEDIA-21 - a Mac editor's NFD filename broke music ingest three ways - FIXED in repo 2026-08-28, unshipped

**Symptom.** A Mac editor drops `Matej Šimalčík - Theme.wav`. The upload lands
on the NAS but the item never goes live: `POST .../uploaded` answers
`409 not_uploaded` ("the library does not hold this file yet") every tick, for a
file sitting in the library. Separately, a re-encode of a track already held
under the other spelling sailed past `find_reencode`, and a name already on
disk in the decomposed spelling could be handed out a second time.

**Cause.** macOS listdir is NFD, the NAS and Windows are NFC, and the two
spellings are different byte strings (CR-90, docs/GOTCHAS.md section 17).
Nothing in `musicweb` normalised anything: `db.safe_upload_name` minted the NFD
name, `db.norm_stem`'s strip to `[a-z0-9]` deletes a precomposed `Š` but leaves
the bare `s` of the decomposed spelling (so `simalcik` vs `imalk` -- two keys
for one recording), `ingest_batches._taken_on_disk` compared one spelling
against an NFC library, and `mark_uploaded` stat()ed the allocated path while
rclone had written whatever the editor's machine holds.

**Fix.** music/web/musicweb/db.py:493-513 (`safe_upload_name` returns NFC --
this is where a library name is MINTED, so it decides what the bytes on disk
are called; it is not normalising a path something already opened, which CR-90
forbids) and :531-545 (`norm_stem` normalises before folding).
music/web/musicweb/ingest_batches.py:230-264 adds `_spellings`, used by
`_taken_on_disk` so the "is this name taken" QUESTION is asked of both
spellings, and by `mark_uploaded`:949-971, which stats each spelling and takes
the first that exists -- so what is opened and stat()ed is always a path that
exists on the disk exactly as written -- then corrects `tracks.rel_path` /
`filename` to the spelling on disk (:988-996) with a WARNING, because that is
the path `/api/audio` and the companion's "+ Resolve" have to open.

**Tests.** music/web/tests/test_db.py's three MEDIA-21 tests (normalised mint,
one duplicate key for both spellings, `find_reencode` across the pair, with the
NFC/NFD pair built rather than typed) and
music/web/tests/test_fleet_ingest.py
`test_a_mac_drop_lands_and_goes_live_in_whichever_spelling_it_arrives` /
`test_a_name_held_under_the_other_spelling_is_stepped_around`. All five fail on
the old code.

### OPS-4 - no server script said WHICH NAS it was about to change, and the destructive ones applied by default - FIXED in repo 2026-08-28, unshipped

**Symptom.** `setup_tree.py` printed `Target project root: /mnt/<pool>/<tree>/Projects/...` and nothing else, then `chown -R`'d as root on whichever box `[nas] host` resolved to. With a vendor `site.toml` in the repo and a customer's under `--site`, which box that is depends on whether the operator remembered the flag in that terminal. `install_dashboard_app --recreate` and `setup_editor_account --revoke-key --apply` had the same exposure: no host in any output line, no confirmation.

**Cause.** The pinned SSH host key was the only backstop, and it is silent when both hosts are recorded in `~/.ccsync/known_hosts`. Nothing in the package rendered the resolved identity at all.

**Fix.** `common.nas_banner()` / `print_nas_banner()` (`server/common.py:1834-1870`) build and print one idempotent line, `NAS: <user>@<host>:<port> (<kind>)  site: <file or "<none>">  tree: <root>`, and `common.cli()` prints it for EVERY script in the package before its first connection (`common.py:2063`, suppressed for `--help`); the three destructive scripts also call it themselves so a direct `main()` shows it. `common.confirm_destructive()` (`common.py:1873-1930`) gates a run on `--apply`/`--yes` or, on a tty, a typed match of the host's short name (`nas_short_name` returns an IP literal whole, because "192" confirms nothing); `--dry-run` never asks, and a non-tty with no flag is a refusal, not a go-ahead. Wired into `setup_tree.py:218-227,275-286` (new `--yes`), `install_dashboard_app.py:4003-4013` (`--recreate` only; a plain redeploy is the routine command and never asks) and `setup_editor_account.py:344-353` (`--revoke-key --apply`).

**Tests.** `server/tests/test_hardening.py` section "OPS-4": the banner's contents, `<not configured>` instead of a raise, once per process, IP vs hostname confirmation, a wrong word stops with "Nothing was changed", a non-tty refuses naming `--yes`, `setup_tree` reaches no ssh unconfirmed, `--recreate` asks while a redeploy does not, and `--revoke-key` cannot revoke without a confirmation. `server/`: 600 passed, 2 skipped.

### OPS-9(a) - "no snapshot" was a stderr line in a 500-line log and nothing durable - FIXED in repo 2026-08-28, unshipped

**Symptom.** WPK-6 again: `snapshot_before` warned on stderr and returned False, `setup_tree.py` and `install_dashboard_app.py` both DISCARDED that return value, the run went on to succeed, and the operator's belief that backups are configured was never contradicted.

**Cause.** The only signal was mid-log, and there was no record of the attempt anywhere afterwards.

**Fix.** `common.snapshot_before` now records every attempt through `_record_snapshot` (`server/common.py:1933-1972`): one `{ts, label, path, ok, detail}` JSON object appended (single write on an `O_APPEND` handle, not tmp + replace, because replacing a shared LOG would lose the other script's lines) to `~/.ccsync/snapshot_log.jsonl`, overridable with `$CCSYNC_SNAPSHOT_LOG`; an unwritable log warns and never stops a deploy. `common.snapshot_verdict()` (`common.py:1975-1992`) renders the one line the callers print in their FINAL block: `this run had a snapshot behind it: yes` / `NO (<detail>)`, with "none was attempted" as an explicit NO. Printed by `setup_tree.py:296,311,315` (Done, the remote-failure block and the dry run) and `install_dashboard_app.py:4508,4592,4606`. The ship gate proposed in the same finding is deliberately NOT here (later wave).

**Tests.** `server/tests/test_backup_restore.py` section 3b: both outcomes are appended with a non-blank detail on a NO, the log is appended and never rewritten, an unwritable log still yields a correct verdict, a skipped call reads NO, the reason is named, and both `setup_tree` and the deploy print the verdict in their final block.

### UX-6 - the grade swap deleted a foreign P: mapping with no ownership check - FIXED in repo 2026-08-28, unshipped

**Symptom.** On a machine whose P: is a real NAS mapping (the base rig, or any machine set up before CCSync), `GRADE FROM SERVER ORIGINALS (SWAP P:)` ran `net use P: /delete /y` on it, the `/y` answering the open-files prompt. The swap back re-maps P: at `local_root`, never at what used to be there, so the original mapping was gone for good and every `P:\...` clip path in that machine's Resolve database then resolved against a different tree. The confirmation dialog talked about playback speed only.

**Cause.** `drive_swap.swap_to_server` called `_unmap` unconditionally, while `classify_p_target` -- the answer -- already existed two functions above it, and both the installer and the wizard already refused a P: they did not create.

**Fix.** `swap_to_server` classifies BEFORE it unmaps (`companion/src/ccsync_companion/drive_swap.py:405-421`): `other` refuses with "P: is currently mapped to <target>, which CCSync did not create. Swapping would replace it and CCSync cannot put it back."; `none` (returned both for "nothing mapped" and for "the table could not be read") refuses the way the installer does; `server` is a no-op. It takes `local_root` as a keyword so a machine still on the legacy `subst P: <local_root>` mapping still classifies as ours (`app.py:3488-3494` passes it). No em dashes in either refusal.

**Tests.** `companion/tests/test_drive_swap.py`: a foreign P: refuses and the only spawn is the read-only query, an unreadable table refuses, a legacy subst of our own local_root still swaps, P: already on the server is a no-op, and a scan for em dashes in both strings. The existing scripted runners are wrapped by `_reports_local_p` so their recorded call lists are unchanged. 31 passed in that file.

### OPS-8 / UX-23 - the Windows uninstaller inverted the "can't tell = foreign" rule the bootstrap obeys - FIXED in repo 2026-08-28, unshipped

**Symptom.** Two failures on one guard. (a) `Get-PSDrive` inside a `try{}catch{}` left `$displayRoot` blank on any failure, and the ownership expression read blank as "a subst mapping, ours" -- so `net use P: /delete /y` ran on the base rig's real NAS mapping, the exact D-8/B21 destruction the bootstrap refuses to risk. `Test-Path` also reports false for a DISCONNECTED persistent mapping (NAS asleep, Tailscale down), which bypassed the guard entirely. (b) Run elevated (reasonable: `Remove-SmbShare` needs it) the unmap was skipped because the elevated token's device map does not hold the user's mapping, while `Remove-SmbShare` SUCCEEDED, leaving the user's session with a drive letter that errors on every access.

**Cause.** The bootstrap's `Get-DriveMapping` / `Invoke-MappingCommand` treatment (B21, INST-1) was never carried to the uninstaller, which kept its own weaker copy.

**Fix.** The five primitives moved into a shared `installer/drive_mapping.ps1` that both scripts dot-source from `$PSScriptRoot` (`windows_bootstrap.ps1:432-447`, which exits 1 when the file is absent rather than run a teardown with no ownership check; `windows_uninstall.ps1:69-105`, where a missing library leaves the mapping and share alone instead). Section 3 of the uninstaller (`windows_uninstall.ps1:186-278`) now classifies with `Get-DriveMapping` (`$null` = foreign), routes both unmap commands through `Invoke-MappingCommand` so an elevated run acts on the USER's device map, and proves the result by RE-READING the map -- neither exit code is a signal, since exactly one of `subst /D` and `net use /delete` can succeed. The SMB share is removed only after that settled; otherwise both are left in place and the two by-hand commands are printed, and the loopback firewall rule stays with the share it scopes. The library ships in the editor package (`build_editor_package.ps1:468-472`) and is bundled beside the bootstrap inside `onboard.exe` (`onboarding/build_onboard.spec:24-27,46`), which extracts and runs it from `_MEIPASS`. No `.gitattributes` change needed: `*.ps1 text eol=crlf` already covers it.

**Tests.** `installer/tests/Test-DriveMapParser.ps1` dot-sources the real library instead of slicing functions out of the bootstrap by string index, asserts all six functions exist, and adds thirteen source cases: both scripts dot-source it, neither redefines the parsers, the uninstaller no longer mentions `Get-PSDrive`/`DisplayRoot`, `$null` is foreign, the unmap goes through `Invoke-MappingCommand`, no raw `cmd /c net use /delete` survives, the share is gated on `$unmapSettled`, the two commands are printed, the bootstrap refuses without the library, and both packagers ship it. 41 cases pass, plus the live probe (which on this base rig correctly reports P: as a foreign netuse mapping).

## Resilience sweep, wave 2: "green while dead" (2026-08-28) - FIXED in repo, unshipped

Wave 2 of `docs/RESILIENCE_SWEEP_2026-08-28.md` (items 1, 2, 3, 16, 17, 28 of
its ranked list), built by five builder agents to one wire contract
(`sync_guard.disk / blocked / restarts / stalled / rotation_seconds /
root_state`, per-lane `progress_token` + `state_since`). This is the class
the ledger has paid for most often: SYNC-17, CR-27a, CR-86, CR-91 were all a
machine reporting green or amber while nothing moved. After this wave a lane
is RED on the grid with "syncing, no progress for N min" (server-side, from
a progress token, so the wedged thread is not the one asked to notice), the
companion kills an rclone that has stopped moving bytes and keeps the
evidence, a dead sequencer/watcher thread is restarted and the restarts are
reported, a wedged drive is `not_answering` rather than `present`, free disk
is in the report and lane B parks under a floor, and every machine's row
carries one sentence answering "why is this computer not syncing", with
[ ASK THIS MACHINE WHY ] fetching its diagnostics over the report channel.

Ships as: dashboard first (schema v32 + v33), then companion 0.9.55 (the same
unshipped build as CR-92 and wave 1). Companion-side new state files:
`~/.ccsync/state/watchdog.json`, `lane_stall.json`, `diagnostics_sent.json`,
`~/.ccsync/lane_b_disk_floor.json`. New config keys: `lane_b_min_free_bytes`
(20 GB). Deliberate judgements recorded in the entries below: a slow-but-
moving rclone is never killed at either ceiling; the disk-floor resume grants
no grace; `transport_offline` is the weakest evidence in the `blocked` list.

### SYS-2 - the sequencer thread could die and the machine kept reporting its frozen state as healthy - FIXED in repo 2026-08-28, unshipped

**Symptom.** An editor's machine sat on the fleet grid green, online and
reporting every 30 s, with a lane state that never changed and no log line
after one traceback. Nothing synced until somebody thought to restart the
tray. The dashboard, whose job is to say whether footage is syncing, could not
tell this apart from a quiet machine - the "green while dead" class the ledger
is full of.

**Cause.** `Sequencer._run` had no try/except around its loop body and the
`self._state = STATE_STOPPED` assignment sat *after* the `while`, so any
exception the inner handlers did not cover (an OSError out of
`_reconcile_paths` when a mapped `P:` drops mid-pass is the observed one)
killed the thread with `_state` frozen at `STATE_RUNNING` or
`STATE_BETWEEN_PASSES`. `start()` was never called again, and the reporter
cheerfully posted that frozen state forever. The timeline watcher and the
media-tree cache thread were unsupervised in exactly the same way. The
dashboard had already solved this on its own side
(`collector.thread_died`/`seconds_since_heartbeat`/`restart` driven by
`app.CollectorWatchdog`); the pattern simply had not been applied to the side
where the failure actually happens.

**Fix.** Three parts. (1) `sequencer.py:846-975`: the loop body is wrapped in
a log-and-continue try/except - one bad pass costs one pass, logged at ERROR
with the traceback and handed to `crash_report.handle` explicitly (a swallowed
exception never reaches `threading.excepthook`, so the local crash file would
otherwise not be written), then the normal between-passes wait
(`_sleep_after_failure`) before the next pass. `STATE_STOPPED` is now reached
in a `finally`, and an exception that ends the thread anyway is recorded in
`_thread_error` and re-raised so the hook still sees it. The loop stamps
`self._heartbeat` at the top of every iteration and at every project turn
(`sequencer.py:1617`), and exposes `thread_died()`,
`seconds_since_heartbeat()` (0.0 for a stopped or deliberately PAUSED
sequencer), `last_error()` and `loop_failures()` on the collector's contract.
(2) `app.py:700-1000` adds `LaneWatchdog`, started last in `start()`
(`_start_lane_watchdog`) and stopped first in `shutdown()`: every 60 s it
checks the sequencer, the watcher thread and the media-tree thread, restarting
a dead one through its existing start method (`_start_watcher_thread` /
`_start_media_tree_thread`, now the single start path for both) when it died
or when its heartbeat is older than its bound - `max(3 x
project_rotation_seconds, 30 min)` for the sequencer, 30 min for the others.
It never restarts during shutdown or while the popup/consolidate stand-down
predicate says no, and a state it cannot read is never treated as a fault.
Every restart is recorded atomically in `~/.ccsync/state/watchdog.json`
(per-thread event list, so the count survives a companion restart) and
reported as `sync_guard.restarts` (`count_24h`, `count_1h`, `last_at`,
`last_error`). (3) The visible half: three or more restarts of one thread
inside an hour gets a tray/Settings advisory line (`tray._restarts_line`,
`settings_window` SYNC LANES), and `build_diagnostics()` gained a "background
thread restarts" section naming the counts, the last error and the record
file. `watcher.py:420` stamps the watcher's own heartbeat (two lines, the
only file touched outside this finding's list).

**Tests.** `companion/tests/test_sequencer.py`: a pass that raises costs one
pass and not the thread (the next pass really runs, `loop_failures()==1`,
`last_error()` names it), the heartbeat advances, a stopped or paused
sequencer reads as no heartbeat question at all, a thread that dies anyway
leaves `STATE_STOPPED` and says why, and a failed pass writes a crash report.
`companion/tests/test_lane_watchdog.py` (new, 23 tests, no real threads and an
injected clock): a dead sequencer is restarted, recorded and reported; the
record outlives the process; events age out of the 24 h and 1 h windows; the
bound really is three rotations; nothing is restarted during shutdown or
mid-popup/consolidate; a sequencer that cannot answer is assumed fine; a
failed restart is recorded rather than raised; dead and wedged
watcher/media-tree threads are restarted while a deliberately stopped one is
not; the tray line appears only at three restarts in an hour; and the app's
`sync_guard`/`build_diagnostics` halves, including "could not check" never
rendering as "nothing has happened".

### SYNC-1 / SYS-17 - a hung rclone froze the lane, the run lock and the whole rotation, with no timer anywhere - FIXED in repo 2026-08-28, unshipped

**Symptom.** CR-91, verbatim: on leso's MacBook lane A reported
`state=syncing, transferring=1, last_sync=NULL, last_error=NULL` for 2 h 20 m
while nothing moved, and because lane A takes its turn first, lane B never ran
- the editor downloaded nothing at all for the whole period. On the fleet page
that is indistinguishable from a lane that is working.

**Cause.** `RcloneLane._run_popen` called `proc.wait()` with no timeout, and
none of rclone's own timers covers the failure: `--timeout` governs REMOTE IO,
`--cutoff-mode SOFT` deliberately lets the in-flight transfer land, and a local
read wedged in the kernel (a Mac's external SSD that stopped answering, a
dropped SMB mapping) never reaches rclone's scheduler at all, so
`--max-duration` is inert. The wait held `_run_lock`, and
`sequencer._run_lanes_a_and_b` joined the lane B thread with no timeout for the
(correct) reason that an un-joined lane B writes into a directory the next
project's repath moves. Both individually right, jointly unbounded.

**Fix.** `_run_popen` now polls `proc.wait(timeout=30)` through
`_wait_with_watchdog` (rclone_lane.py:3712) with two ceilings derived from the
pass budget: no bytes AND no files for `max(4 x budget, 900 s)`, or
`budget x 2 + 300 s` outright, then `_terminate_child` and `state=error` with
"rclone made no progress for Ns - killed" / "rclone did not exit after Ns -
killed" (rclone_lane.py:3138). Bytes and files, not wall clock, exactly as
CR-91 asks - and with one exemption CR-91's own text demands: a run still
moving bytes is never killed at either ceiling, because SFTP uploads do not
resume and killing a slow 40 GB original would restart it from byte 0 forever.
Every stall is written atomically to `~/.ccsync/state/lane_stall.json`
(`write_stall_record`, rclone_lane.py:272) so a restart cannot erase the
evidence, reaches the report as `sync_guard.stalled` (`stall_report`,
rclone_lane.py:3844, carried by lane B's `sync_guard_report` because both lanes
share the state dir and the wire has one slot) and reaches the editor as a tray
/ Settings line (`tray._stalled_line`). The lane B join is bounded to
`lane_b_join_timeout(budget)` (sequencer.py:83) - above the lane's own ceiling,
so the lane kills its own child first and this is the backstop - and on timeout
calls `RcloneLane.abort_run`, which ends the child WITHOUT setting `_stop_event`
(that would latch lane B off for its whole thread generation) and logs a named
WARNING before the rotation proceeds. `project_rotation_seconds <= 0` was
already refused by `config.validate_config`'s positive-number loop; that is now
pinned by a test, and `_stall_budget_seconds` falls back to the packaged
default rather than letting a zero disable the watchdog.

**Tests.** `companion/tests/test_rclone_lane.py` (a child that never exits and
moves nothing is killed and reported; the stall is persisted and reaches
`sync_guard`; a slow-but-progressing run is never killed, driven by an injected
clock over 3 h 20 m of simulated time; the hard ceiling; both formulas;
`abort_run` does not latch the lane off; a record survives into a new lane
object), `test_sequencer.py` (a wedged lane B does not freeze the rotation, the
named WARNING, a healthy lane B is joined exactly as before, and the join
timeout sits above the lane's ceiling), `test_config.py` (the rotation
refusal), `test_tray_guard.py` + `test_settings_window.py` (the stall line).

### SYS-1 (companion half) - a lane state with no evidence behind it - FIXED in repo 2026-08-28, unshipped

**Symptom.** The same CR-91 report: `syncing` with `last_error=NULL` is
unconditionally amber on the fleet page forever, and `lane_chip_status` reddens
only on REPORT staleness - and the reports were flowing.

**Cause.** Nothing in the report said whether a non-terminal lane state was
moving, or how long it had held.

**Fix.** `LaneStatus` gains `progress_token` and `state_since`
(`companion/src/ccsync_companion/sync/base.py:42`). `state_since` is stamped by
`__post_init__`/`__setattr__` rather than at the ~30 places that assign
`state`, and a snapshot copy (`LaneStatus(**vars(...))`, which every `status()`
returns) keeps the stamp it copied instead of re-dating it. `progress_token` is
`bytes:files:project` (`rclone_lane.progress_token`), published at the START of
a pass - the run that has moved nothing is the one the dashboard must be able
to red - and refreshed on every `--stats` tick in `_handle_stderr_line`. The
reporter serialises both per lane (`reporter._lane_liveness`, reporter.py:245);
both are OMITTED rather than sent as null when a lane cannot supply them, so
absent means "older companion" and never "claims to be moving", and the token
is omitted while a lane is idle. Neither is touched by `_fit_payload`, which
sheds only the heavy sections.

**Tests.** `companion/tests/test_reporter.py` (a running lane reports both, an
idle lane reports no token, a bare adapter omits both without 422ing, and both
survive `_fit_payload` on a 15.8 MB payload; the exact-shape contract test now
pins them), `test_rclone_lane.py` (the token exists before the first stats tick
and moves when bytes move; `state_since` moves only on a state change).

### SYNC-12 - "bounded" remote listings were not bounded - FIXED in repo 2026-08-28, unshipped

**Symptom.** None observed yet; the mechanism is the same one `_end_probe`'s
docstring already describes, one call layer up.

**Cause.** `_run_lsf` and `_run_capture` used `subprocess.run(timeout=)`, which
kills the child on expiry and then sits in `communicate()` waiting for the
pipes to close. On Windows an rclone whose grandchild inherited the write
handle - or a child in an uninterruptible kernel wait - leaves that call
blocked forever. `list_remote_files` runs inside `_run_lock` with a documented
600 s cap that could therefore be infinite, at the exact moment the breaker is
deciding whether to stop lane B.

**Fix.** Both go through `_run_bounded` (rclone_lane.py:947): Popen, two daemon
readers with `_run_popen`'s `abandoned` flag, `wait(timeout)`, then
`_end_probe`'s kill + one-second wait. A killed child answers `None`, which
`_run_lsf` reports as a FAILED listing (never an empty one) and `_run_capture`
as `PROBE_TIMEOUT_RETURNCODE` - i.e. "I could not tell", which is what makes
`scan_pending_uploads` refuse a removal.

**Tests.** `companion/tests/test_rclone_lane.py` (a child that ignores the
kill and whose pipes never close: `_run_lsf` returns None promptly, the
`_run_bounded` contract, and `_run_capture`'s non-zero code).
`test_rclone_filters.py`'s two decoding/no-console-window tests now stand in a
Popen instead of a CompletedProcess.

### SYNC-13 - the express lane had no duration bound and no abandoned-reader escape - FIXED in repo 2026-08-28, unshipped

**Symptom.** Express dies permanently and silently: the only sign is that new
clips take a full rotation to reach the NAS instead of ~10 s, and
`express_report()`'s counters simply stop advancing.

**Cause.** `_express_spawn` read stderr to EOF and then waited, both unbounded,
and `build_express_command` carried no `--max-duration`. A wedged express run
holds `_express_run_lock` for the life of the process.

**Fix.** `build_express_command` takes `max_duration_seconds` and emits the
usual `--max-duration ... --cutoff-mode SOFT` pair (not a filter flag, so
`--files-from-raw` still accepts it); the lane passes
`project_rotation_seconds` (floor 60 s, `_express_max_duration`).
`_express_spawn` now uses the same daemon reader + `_wait_with_watchdog` shape
as the periodic path, with the stall recorded as lane `"express"` and progress
measured from ITS OWN tally rather than the shared status bytes (which belong
to the periodic run). `express_report()` carries `last_run_age_seconds`, so a
dead express lane is visible instead of merely quiet.

**Tests.** `companion/tests/test_rclone_lane.py` (the flag and its SOFT
cutoff, the lane's budget from cfg, and the reported age), plus the existing
`test_rclone_express.py` suite, whose stderr stand-in is now iterable like a
real pipe.

### SYNC-2 - the root guard's own probe can block on the wedged mount it exists to detect - FIXED in repo 2026-08-28, unshipped

**Symptom.** A Mac editor's external SSD (or a Windows editor's SMB/`subst`
mapping over a dropped tailnet) stops answering opens. The drive is plugged
in, the directory is right there, and nothing anywhere says a word: the tray
keeps saying the drive is fine, the lanes are never paused, `RootGuard.state`
keeps returning its last good answer, and the fleet grid shows a healthy
machine that has not moved a byte. MAC-12's shape, and half of CR-91's.

**Cause.** Every root check in the area was an in-process `os.path.isdir` --
`root_guard.probe_root:369`, `rclone_lane._local_root_is_present`,
`sequencer._local_root_is_present`, `manifest`. On a wedged filesystem they
all block in the kernel, so `RootGuard._loop` stops polling and
`_on_root_absent` never fires. The one detector that would have named the
cause is the one thing that cannot answer, and `probe_once`'s own docstring
already said so.

**Fix.** A fourth answer, `ROOT_NOT_ANSWERING`
(`companion/src/ccsync_companion/root_guard.py:76`), produced by
`rclone_lane.probe_watch_root` -- already stdlib-only, out-of-process, 5 s
capped and never raising -- run *instead of* the in-process probe on the first
poll, then every `PROBE_EVERY_N_POLLS` (12, i.e. once a minute) and again
whenever the previous in-process probe took over `SLOW_PROBE_SECONDS`
(`root_guard._sample`/`_filesystem_probe_due`/`_filesystem_answers`, ~:790).
`state_is_absent` groups it with `absent`/`misplaced`, so the existing
`_on_root_absent` path pauses the lanes with no new wiring; `state_sentence`
gives it its own words ("the sync drive is not answering - reconnect it or
restart") because telling an editor to check a cable on a drive that is
plugged in is the MAC-10 dead end. It reaches the fleet grid as
`sync_guard.root_state` (`app.sync_guard`), the tray's Sync: line
(`tray._sync_line`) and the balloon (`app._on_root_absent`). A probe that
answers, that cannot be run, or that raises all fail OPEN to today's
behaviour -- refusing to trust the tree because our own subprocess did not
start would be a self-inflicted outage.

**Tests.** `companion/tests/test_root_guard.py` (12 new): a blocked probe
answers `not_answering` where `probe_root` would have said `present`; it
pauses the lanes and carries its own sentence; ok/unavailable/raising probes
all leave `probe_root` in charge; the cadence (first poll, then every Nth, and
the extra poll after a slow one); the drive coming back fires `on_present`; a
blank `local_root` spends no probe. `companion/tests/conftest.py` stubs the
out-of-process probe suite-wide so no test spawns one.

### SYS-5 / SYNC-7 - no lane checked free disk space, and nothing told the dashboard - FIXED in repo 2026-08-28, unshipped

**Symptom.** An editor ticks a big project and lane B pulls proxies onto a
laptop SSD at 40 GB free, with up to 50 GB of `.ccsync-trash` recovery copies
on the same volume. rclone fails per file with ENOSPC, the lane goes red with
a raw rclone string, and the grid shows a red dot with no cause. Nothing
warned before the wall, and no page anywhere could answer the owner's first
question.

**Cause.** Nothing in `sync/*` ever called `shutil.disk_usage`, though the
pattern exists in four other subsystems (`proxy_gen`, `broll_vlm_sidecar`,
`music_clap_sidecar`, `broll_server._free_bytes_at`) -- it was simply never
applied to the three lanes that move the actual footage, nor to anything the
dashboard can see.

**Fix.** `lane_guard.disk_report`/`free_bytes_at`/`system_drive_path`
(`companion/src/ccsync_companion/sync/lane_guard.py:~340`) and
`app.disk_snapshot` put `sync_guard.disk` = {root_free_bytes,
root_total_bytes, system_free_bytes, at} on the report, measured once per
HEAVY tick (`dashboard_report_interval`) and memoised, because the guard
section rides every light tick too. A drive that could not be measured reports
`None`, never 0. `lane_guard.DiskFloorLatch` parks lane B in `paused` -- never
`error`, the breaker's shape exactly, so lanes A and C keep running -- below
`lane_b_min_free_bytes` (new config key, default 20 GB, documented commented
out in `config.py`'s `DEFAULT_TOML_TEXT` and `companion/config.example.toml`).
The preflight is `RcloneLane._check_disk_floor`, at the top of
`_run_once_locked` beside the breaker check, and `_disk_stand_down` carries
the sentence. The park is persisted in `CONFIG_DIR/lane_b_disk_floor.json`
(never in-memory only), clears ITSELF at twice the floor, and is clearable by
the SAME [ RESUME PROXY DOWNLOAD ] the breaker uses (`app.resume_lane_b`,
`tray._confirm_resume_disk_floor` with its own dialog copy, and the button
condition in `tray.py`/`settings_window.py`). Tray lines: `tray._disk_line`
("Not downloading proxies: this drive has 8 GB free ..."). A measurement that
FAILS parks nothing and releases nothing.

**Tests.** `companion/tests/test_lane_guard.py` (13 new): the floor parks and
the park is `paused` with no rclone spawned; it clears itself only at 2x; a
failed measurement changes nothing either way; a park survives a restart; the
tray clears it; a floor of 0 disables it; `disk_report` names both volumes and
reports `None` on failure; a raising probe never parks the lane.
`companion/tests/test_app.py`: the `disk` section's shape, and that it is
measured once per heavy tick. `companion/tests/conftest.py` pins free space
suite-wide so no test outcome depends on how full the developer's C: is.

### SYNC-16 - the trash prune could only run on the code path a sick machine never reaches - FIXED in repo 2026-08-28, unshipped

**Symptom.** A machine that errors every lane B pass (NAS unreachable, disk
full, a filter file that will not validate) keeps up to 50 GB of recovery
copies forever -- and disk-full is precisely the state in which that matters.
Separately, the size rule could delete a batch created seconds ago before one
created a fortnight back.

**Cause.** `_maybe_prune_trash()` was the LAST statement of a lane B pass that
did not trip, was not stopped mid-transfer and did not error
(`rclone_lane.py:~2930`). "Nothing is pruned while the breaker is tripped" is
deliberate; "nothing is pruned while the lane is failing" was an accident of
placement. And `trash_entries` yielded `0.0` for a batch whose every stat
failed (lane_guard.py:~560), which sorted it as the OLDEST thing in the trash.

**Fix.** `Sequencer._prune_trash` (`sync/sequencer.py`, called once per pass
right after `_run_pass`, fault-isolated exactly like `_check_remote_root`);
the breaker gate stays inside `prune_trash` where it belongs, and the
interval gate stays inside `_maybe_prune_trash`. `prune_trash` gains a third
trigger, `min_free_bytes` + `free_bytes_fn` (wired to the same
`lane_b_min_free_bytes` the floor uses), so disk pressure prunes oldest-first
and never the last batch standing even when age and size have nothing to say.
`lane_guard.batch_stamp` parses the `%Y%m%d-%H%M%S` directory name as the
fallback timestamp -- `_backup_dir`'s own record of when the batch was made,
needing no filesystem at all.

**Tests.** `companion/tests/test_lane_guard.py` (7 new): disk pressure prunes
what age and size would have kept, and nothing when the drive has room or the
measurement failed; the breaker still gates it; a batch with no usable
timestamp sorts by its name and is not the first one dropped; `batch_stamp`
refuses anything that is not that format; the sequencer prunes on a lane whose
every pass fails, and swallows a prune that raises.

### SYNC-15 - nothing aggregated the sixteen independent reasons this machine is not syncing - FIXED in repo 2026-08-28, unshipped

**Symptom.** "Why isn't this machine syncing?" had no answer on any page. Each
latch had its own state, its own file and its own (or no) report field, and
the fleet page had to infer the reason from a lane state that SYNC-1/5/9 all
show can be wrong. `build_diagnostics()` was local, manual and clipboard-only.

**Cause.** No aggregation, not missing data: every value was already in
memory.

**Fix.** One derived, report-only field, `sync_guard.blocked` = {reason,
detail, since}, assembled LAST in `app.sync_guard()` from the picture already
built (`app.blocked_report`/`_blocked_candidate`/`_BLOCKED_ORDER`,
`companion/src/ccsync_companion/app.py:~4990`). Sixteen reasons in one
priority order -- not_signed_in, licence_pending, clock_skew, root_absent,
root_not_answering, root_misplaced, disk_full, fleet_halt, local_halt, paused,
breaker_tripped, no_selection, folders_unfiltered, lane_stalled,
syncthing_down, transport_offline -- first match wins, absent when nothing
blocks (an absent key is the ONLY thing that means "this machine is
syncing"). Ordered by what the reader can act on: the editor's own sign-in
before the admin's halt, a wedged drive before a tripped breaker. Every
candidate is isolated, so a broken getter cannot hide a lower-priority
reason, and `since` prefers the latch's own stamp and otherwise remembers the
first report that named it. The stall record another wave-2 change writes to
`~/.ccsync/state/lane_stall.json` is read if present. The tray shows the same
sentence (`tray._sync_line`'s fall-through and `tray._blocked_line`, rendered
in the Settings window) so the tray and the grid cannot disagree.

**Tests.** `companion/tests/test_app.py` (11 new): nothing blocking means no
key at all; each reason reaches the report on its own (parametrised over ten);
the priority order under four simultaneous blockages; the disk park's
sentence; a stall record; a raising candidate never hides a lower reason; the
`since` stamp holds still while the reason stands; the tray line and the
report detail are the same words.

### SYS-1 - a lane in `syncing` was green-or-amber for ever, fleet wide - FIXED in repo 2026-08-28 (dashboard half), unshipped

**Symptom.** leso's MacBook, 2026-08-28: lane A reported `state=syncing,
transferring=1, last_sync=NULL, last_error=NULL` for 2 h 20 m. Nothing moved,
no SFTP session ever existed on the NAS, and because lane A takes its turn
first lane B never ran, so the editor downloaded nothing for the whole period.
The fleet grid showed an amber chip on a healthy-looking row (CR-91b).

**Cause.** `health.lane_chip_status` reddened only on REPORT staleness, and
the reports were flowing. A lane in `syncing` was unconditionally AMBER, with
no notion of whether anything had moved; there was no field on the wire that
could have said. The same shape produced SYNC-17 (lane C green 18 h), CR-27a
and CR-86.

**Fix.** One contract, evidence-based: a state may not be green or amber
without a monotonic progress token and the time it last changed.
`LaneReportIn` gains `progress_token` and `state_since`
(`dashboard/src/ccsync_dashboard/api.py:4566`); v32 adds
`lane_report_current.progress_token / progress_token_since / state_since` and
`machine_state.rotation_seconds` (`db.py:999`). The time a stall is judged on
is the SERVER's: `db.upsert_lane_report` stamps `progress_token_since` with
the `received_at` of the first report carrying the CURRENT token and leaves it
alone while the token repeats, so a companion re-sending the same token every
30 s cannot reset the clock on its own stall, and a wrong client clock cannot
hide one. `health.lane_stall()` (pure) returns the seconds past
`max(3 x rotation_seconds, 30 min)`, `health.lane_chip()` turns that into RED
plus the sentence "syncing, no progress for 47 min", and
`api.build_editors_view` folds it into each row's `worst()` exactly as wave 1
folded `report_freshness` (`api.py:770`). An absent token is NO VERDICT, not
"fine": every machine in the field is one until the companion ships, and an
upgrade window must not redden the fleet. The companion's own kill record
(`sync_guard.stalled`, SYNC-1/SYS-17) is stored beside it and chipped
`[ STALLED A, KILLED ]`.

**Tests.** `dashboard/tests/test_health.py` (the budget, the floor, the
three-rotation stretch, terminal states, an old companion, an unreadable
stamp, silence outranking a stall) and
`dashboard/tests/test_report_ingest_health.py` (stored, stamped only on a
CHANGE, cleared by a token-less report, and the whole thing end to end
reddening a fleet row that keeps reporting). `server/tests/test_cross_component.py`
gains a parity gate over the per-LANE dict keys, which the section-level gates
could not see (the lanes are a comprehension over a dict literal).

### SYS-5 - free disk space was invisible to every page - FIXED in repo 2026-08-28 (dashboard half), unshipped

**Symptom.** An editor's project drive fills. Lane B thrashes per-file ENOSPC,
lane C goes out of sync, lane A keeps trying; the grid shows red dots with no
cause and the owner's first question ("why?") has no answer anywhere.

**Cause.** `ReportIn` had no disk field and nothing in `sync/` ever called
`shutil.disk_usage`, although the ingest and proxy paths have had free-space
floors for months (ledger class E: a guard on only some of N call sites).

**Fix.** `sync_guard.disk` is declared (`DiskIn`, `api.py`), flattened by
`flatten_sync_guard` and stored in v32's `machine_state.disk_root_free_bytes /
disk_root_total_bytes / disk_system_free_bytes / disk_at`. `disk_at` is the
section's own upsert marker rather than `guard_at`, because the measurement
rides HEAVY ticks only and a light report in between must not blank the last
known free space. `health.disk_status()` is the pure rule - amber under 10 %
or 50 GB free, red under 5 % or 20 GB, both a percentage and an absolute floor
because 8 % of 8 TB is still 640 GB - and the fleet grid renders `[ DISK 4% ]`
with the figures in its tooltip. A machine that has reported no disk section
gets NO chip rather than a green one: "could not check" must never render as
"fine". `sync_guard.disk_floor` and `sync_guard.root_state` (the companion
halves of SYNC-7 and SYNC-2, which landed in the same wave) are declared too
so they are not counted as ignored sections; their columns belong to the v33
step.

**Tests.** `test_health.py` (the two thresholds, and no-verdict on an absent
figure); `test_report_ingest_health.py` (flattened, chipped, and not blanked
by the light report that follows).

### UX-1 - ticking a project had no capacity preflight - FIXED in repo 2026-08-28, unshipped

**Symptom.** The owner opens Assignments, sees a new editor's column empty and
clicks `[ ALL ]` to give them everything: twelve projects, 4 TB of proxies,
onto a 500 GB MacBook. Every tick succeeds. rclone fills the drive,
`.ccsync-trash` cannot prune while the breaker is tripped, and the machine
becomes unusable for Resolve too.

**Cause.** `api_tick` validated the project, the base rig and the machine name
and never the size, and the dashboard held only one of the two numbers it
needed (the NAS proxy bytes; the machine's free space was not on the wire).

**Fix.** With SYS-5's disk columns in place, `api.tick_capacity_warning()`
answers one sentence per computer - "2026/FF5/Animals is 620 GB of proxies.
LESO-MBP has 180 GB free." - built by the pure `health.capacity_warning()`
(silent when either figure is unknown, or when it fits with room to spare; an
un-walked project reads as "cannot say", never as 0 GB). `api_tick` returns it
as `warning`, and BOTH UIs confirm before the write: the assignments grid
renders the two figures into each cell and `assignments.js` mirrors the
server's rule in the browser, so `[ ALL ]` confirms the COLUMN TOTAL before it
writes the first cell, and the sidebar checkbox and the project page's
`[ TICK FOR ... ]` carry an `hx-confirm` built from
`ui._sidebar_context`'s `tick_warning` - the same mechanism DASH-8's
person-level untick confirm uses. It REFUSES NOTHING by design (the owner may
know something the dashboard does not); it just may not be silent.

**Tests.** `test_health.py` (the sentence, the fits-with-room silence, the
unknown figure) and `test_report_ingest_health.py` (the route's `warning`, a
never-walked project, and that the tick still lands).

### SYS-7 - "why is my footage not syncing" had an answer on the machine and no route to the person asking - FIXED in repo 2026-08-28, unshipped

**Symptom.** An editor's proxies stop arriving. They message the owner. The
owner opens the fleet grid, which says amber, and has nothing else to read. The
one artefact that answers the question, `build_diagnostics()`, is genuinely good
(identity, token expiry, root state, config problems, sequencer state, rclone,
the Resolve bridge, every section fault-isolated) and went to the CLIPBOARD,
with the instruction "Paste them to your admin in a message" - and silently to
the log instead if any CCSync window happened to be open. So it existed only if
a non-technical editor performed a manual step at the right moment, on the
machine that was broken. Meanwhile every state that would have explained the
outage was already computed somewhere and never composed into a sentence: the
breaker in `lane_guard`, the halt in a latch file, the root guard's answer, the
plan in `selections`, the skew in v30's column, the disk in v32's.

**Cause.** Two gaps, not one. There was no CHANNEL for the bundle (nothing on
the report reply could ask for it, and nothing accepted one), and there was no
FUNCTION that turned the dashboard's own held state into words - `editor_status`
and `lane_chip_status` answered in colours only, which is how CR-91b rendered
2 h 20 m of a wedged lane A as amber.

**Fix.** `health.why_not_syncing(row, now) -> (reason_code, sentence) | None`
(`dashboard/src/ccsync_dashboard/health.py:337-596`), pure, ordered exactly as
the wire contract's `sync_guard.blocked.reason` list (`health.WHY_ORDER`) with
`upload_only` inserted where SYS-7's tree puts it. It PREFERS the companion's
own `blocked` (SYNC-15) - the only end that can see the root guard's fourth
answer, the licence park and its own transport - and falls back to a deliberate
SUBSET derived here: not signed in, clock skew, a red disk (`disk_status`'s own
threshold, not a second one), fleet/local halt, the breaker, no tick (never on a
base rig - CR-28), unfiltered folders, an upload-only plan, a stall from either
detector, a dead sync engine. `WHY_INFORMATIONAL` marks the one entry that is
not a fault, so an upload-only machine is EXPLAINED rather than accused (CR-85).
An unknown reason code from a newer companion is named, never swallowed.

Schema v33 (`db.py:998-1044`) stores `blocked_reason` / `blocked_detail` /
`blocked_since` and the LaneWatchdog's `restarts_count_24h` /
`restarts_last_at` / `restarts_last_error`, flattened in `api.flatten_sync_guard`
and written by `db.store_blocked_state` (`db.py:2598+`) - its own UPDATE rather
than six more columns in `upsert_machine_state`'s INSERT, and on the LATCH rule
(any guard-bearing report writes them), because an ABSENT `blocked` is how the
companion spells "nothing is blocking me now". The sentence is the first line of
each machine's row on the fleet grid, which is also the editor's own home view
(`templates/partials/fleet_grid.html`, `api.build_editors_view`), muted for an
informational reason and red otherwise.

The channel: `POST /api/v1/diagnostics` (`api.py`, `api_diagnostics`) with the
same auth as `/report` check for check, a 256 KB body ceiling through
`app._BODY_LIMITS`, and a v33 `diagnostics` table keeping the newest 5 per
(editor, machine) at write time plus a 30-day prune. `[ ASK THIS MACHINE WHY ]`
on the fleet grid writes a one-shot request (`db.request_diagnostics`, modelled
on `request_lane_b_resume` down to the `requested_at` stamp) that rides the
reply as `commands.diagnostics` and clears when a bundle with trigger
`admin_request` ARRIVES - the opposite of `resume_lane_b`, which is dropped as
the reply goes out, because a standing resume re-armed a breaker every cycle
whereas a standing ask costs one text upload. `[ READ THE ANSWER ]` opens
`partials/admin_diagnostics.html` outside the grid's 15 s poll. Both halves are
audited (`diagnostics.request`, `diagnostics.received`).

Companion side: `reporter.post_diagnostics(text, trigger)` on the report
channel with post_once's own headers and its "never without a verified
identity" rule; three triggers in `app.py` - Copy diagnostics (which still
fills the clipboard, and now also uploads on both of its fallback paths),
any lane entering `error` from a non-error state (one per lane per hour,
persisted in `~/.ccsync/state/diagnostics_sent.json`, tmp + os.replace), and
`commands.diagnostics` with the `requested_at` comparison so a redelivered
command is not re-run.

**Tests.** `dashboard/tests/test_health.py` (25 new: every reason in the
contract's order, the order itself, the companion's answer winning, an
appended-not-substituted detail, an unknown code named, the base-rig carve-out,
upload-only informational, both stall detectors, junk input raising nothing);
`dashboard/tests/test_diagnostics.py` (18: route auth including a mismatched
identity, the 413 and the truncate-not-drop cap, keep-5 per machine, the 30-day
prune, the request/ack round trip including "a button bundle does not answer an
admin's ask", audit rows, the sentence rendering on the fleet grid, the admin
partial, the ASKED chip); `companion/tests/test_diagnostics_upload.py` (20:
post_diagnostics' URL/headers/identity/cap, all three triggers, the rate limit
including its survival across a restart, the requested_at idempotency and its
persistence, and every failure path being a log line rather than a traceback on
the reporter thread). `test_hardening.py`'s `_BODY_LIMITS` assertion was widened
to name the new route.

## Resilience sweep, wave 3: the release pipeline (2026-08-28) - FIXED in repo, unshipped

Wave 3 of `docs/RESILIENCE_SWEEP_2026-08-28.md` (items 7, 14, 29, 30, 31, 32
plus REL-5/7/9/10/11/12/13/14/15/16 and OPS-12 from the same files), built by
four builder agents to one contract. Before this wave a build reached every
machine at once, a companion that crashed at minute five had no way back
(the rollback copy was deleted at 60 s), a retracted build was never
withdrawn, "deploy the dashboard before the companions" was a rule in four
documents and no code, a deploy that left the dashboard dead exited 0, and
rotating the session secret 401'd the whole fleet with no message.

After it: publish is STAGED by default and MAKE CURRENT is refused until one
machine has soaked the build (30 min, zero crashes) unless the version is
typed; a companion keeps `.old` until its first accepted report and puts
itself back after three crashing starts; a signed `retracted` list is
honoured under every feed policy with one ROLL THE FLEET BACK button;
`requires_dashboard` and `arch` are signed into the record and refused at
MakeCurrent when the dashboard is too old or the architecture wrong; the
deploy probes `/api/v1/health` and stops the ship on failure; the dashboard's
own crash-loop watchdog needs a served 200; `DASH_SESSION_SECRET_PREVIOUS`
drains a rotation and a refused machine is named on the grid.

**OVERLAP CONSTRAINT, read before the next ship:** the two signed extras are
only verifiable by companions 0.9.55+, so `sign_release.py` drops them unless
`--emit-kind-extras` (`ship.cmd -EmitKindExtras`) is passed. Turn that on
only once every machine reports 0.9.55 or newer (docs/RELEASE.md, "The
overlap cost of the two signed fields"). Companion `REQUIRES_DASHBOARD =
"0.7.17"` (config.py) is the value it will sign.

Ships as: dashboard first (schema v34 + v35), then companion 0.9.55, then a
rebuilt installer package (windows_upgrade.ps1's `.prev`, build_editor_
package.ps1's login-before-build and -EmitKindExtras). New state files on
the companion: `last_version.json` (adopts `last_version.txt`),
`~/.ccsync/state/upgrade_attempts.json`. New env: `DASH_SESSION_SECRET_PREVIOUS`,
`DASH_RELEASE_SOAK_MINUTES`. New tool flags: `--rollback-on-unhealthy`,
`-Resume`, `-AllowKeyRotation`, `-IReallyMeanDirtyCurrent`, `--retract`.

### APP-5 / REL-2 - an upgraded build that boots and then dies had no way back - FIXED in repo 2026-08-28, unshipped

**Symptom.** A published build starts fine, puts a tray icon up, and hits a
fault three minutes later (a Tk failure in the first dialog, an exception on a
code path only one editor's config reaches, a lane touching a surrogate path).
The editor is mid-edit and notices nothing: the tray icon is simply gone. On
Windows the Run key relaunches it at each logon into the same fault; on macOS
the LaunchAgent is RunAtLoad-only, so the machine has no companion at all - no
lanes, no Resolve fixer - and a whole fleet can take that offer at once.

**Cause.** `apply()` only rolls back if the child exits inside 2 s
(`CHILD_TAKEOVER_GRACE_SECONDS`), and `app.run()` armed
`threading.Timer(60.0, cleanup_old_exe)` at every start, so from minute one
there was no `<exe>.old` on disk. Nothing counted restarts: `note_version_start`
recorded the running version whether or not the run was healthy (AUDIT_2
CORE-H6 moved it off "did an unlink succeed", but it stayed a single line of
text).

**Fix.** The rollback copy is now kept on EVIDENCE, not a timer:
`upgrade.keep_old_exe_until_healthy` (upgrade.py:576) runs on its own daemon
thread from `app.run()` (app.py:8058) and deletes `<exe>.old` only after one
dashboard report has been ACCEPTED (`app._note_report_accepted`, app.py:4884,
on APP-1's channel) or after 60 minutes of uptime; a shutdown before either
leaves the copy for the next start. `last_version.txt` became
`last_version.json` (`{version, previous_version, starts, first_start_at,
last_clean_shutdown}`, atomic; the legacy .txt is adopted once and still
written for a rollback to an older build): `starts` counts launches of the same
version and is reset by `note_clean_shutdown` from `CompanionApp.shutdown`
(app.py:7723). Three starts inside ten minutes with an `.old` present makes
`crash_loop` true, and `app._revert_crashing_build` (app.py:7794) calls
`upgrade.revert_to_previous_build` (upgrade.py:637): it floor-checks the
recorded `previous_version` against `~/.ccsync/upgrade_floor.json` and REFUSES
below it, restores the binary through the existing `_rollback`, writes the
marker the next build reads, spawns through `_default_spawn` and stands this
process down. The restored build toasts "The last update kept crashing, so
CCSync went back to vX", carries `sync_guard.upgrade.reverted_from` until one
report is accepted, and shows a Settings line (`tray._reverted_line`).

**Tests.** `companion/tests/test_upgrade.py` - the start record (counting,
clean-shutdown reset, stale-window reset, legacy .txt adoption, never raises),
the keeper (`.old` survives past 60 s and goes on the first accepted report,
the 60-minute fallback, a shutdown keeps it), and the revert (restores and
records, refuses below the floor, refuses an unnameable `.old`, refuses with no
`.old`, keeps this build when the restored one will not start).
`tests/test_app.py` - the revert marker rides the report until one is accepted,
the guard's refusal is logged, diagnostics.

### REL-8 - a machine that could not take a build retried for ever and nobody was told - FIXED in repo 2026-08-28, unshipped

**Symptom.** An editor's AV quarantines every `ccsync-companion.new.exe`, or a
proxy mangles the download so the sha never matches, or the exe dir is on a
full disk. The machine pulls ~20 MB off the NAS every ten minutes for ever
(~2.9 GB/day, over a possibly relayed tailnet link) and rolls back each time,
and the admin's push shows as pending for ever: the report carried nothing
about upgrade outcomes, so "hasn't seen the push yet" and "has failed 140
times" looked identical.

**Cause.** `_run_auto_update` / `_run_pushed_update` re-armed on a flat
`PUSHED_UPDATE_FAILED_RETRY_SECONDS = 600` timer held in memory only, with no
attempt cap and no persistence, and the dashboard re-sends the request on every
report until the machine reports the new version.

**Fix.** A persisted ledger, `~/.ccsync/state/upgrade_attempts.json`
(upgrade.py:326 onwards): `note_upgrade_attempt` counts failures per TARGET
version (a new target resets, so publishing a fix always reaches the machine),
`upgrade_backoff_seconds` is 10 min -> 1 h -> 6 h, and `upgrade_retry_due` is
measured on the wall clock so a restart does not buy another download.
`app._upgrade_attempt_blocked` (app.py:4900) gates both update paths, and after
`MAX_UPGRADE_ATTEMPTS` (8) failures the machine stops trying and says so on
Settings (`tray._upgrade_line`: "CCSync could not install the update to vX 8
times, so it has stopped trying. Copy diagnostics for your admin"). WHY it
failed is distinguished by `UpgradeManager.last_failure`
(`download-failed`/`sha-mismatch`/`no-space`/`refused`/`swap-failed`/
`exec-failed`) and rides the report. Coming up ON the attempted version clears
the count (`app._load_upgrade_state`). A stand-down ("a CCSync window is open")
is still the short 90 s pause and is not counted: it is not a failed install.

**Tests.** `tests/test_upgrade.py` - the back-off schedule, persistence across
a restart, a new target resetting, retry-due (including a clock that went
backwards), the eight-failure cap, and `upgrade_report`'s always-full shape.
`tests/test_app.py` - a machine that cannot take a build stops after eight
downloads and reports the reason; `tests/test_tray_guard.py` - the line appears
only once it has given up.

### REL-16 (companion half) - the channel had no architecture discriminator - FIXED in repo 2026-08-28, unshipped

**Symptom.** An Intel Mac reports `platform: macos` and is offered the arm64
build GitHub's `macos-latest` runner produced. It downloads, verifies, is
renamed over the running companion, fails to exec and the swap rolls back (the
guard works) - so the machine keeps running but can never update, and with
`auto_update` on it retried for ever (REL-8).

**Cause.** The record's `platform` was the only discriminator, and the report
payload carried no architecture at all - `tools/release_macos.sh` measures the
arch, puts it in the manifest, and it is dropped at publish.

**Fix.** `upgrade.arch_key()` (upgrade.py:143) normalises `platform.machine()`
to `x86_64`/`arm64` (anything else is passed through lowercased, which the
dashboard treats as "offer nothing"), the report carries top-level `arch`
(`reporter._build_payload`), and `build_diagnostics()` names it. The dashboard
half - matching `arch` on the signed record and saying "no macos/x86_64 build
published" - is the RELEASE CHANNEL agent's.

**Tests.** `tests/test_upgrade.py::test_arch_key_normalises_the_two_spellings_of_each_cpu`,
`tests/test_reporter.py::test_payload_carries_the_architecture`.

### REL-1 / SYS-6 - a build reached every machine at once; there was no canary and no soak - FIXED in repo 2026-08-28, unshipped

**Symptom.** One `-MakeCurrent` (or one vendor `current` pointer) handed a
companion build to every machine in the fleet inside one report interval, and
on a site with `auto_update` on every machine also took it, unattended. The
only thing between a bad build and the whole fleet was the companion watching
its replacement for two seconds.

**Cause.** Nothing in the publish path staged a build against a subset first.
Every piece of a canary already existed - `publish_package` can publish
without `make_current`, `db.machine_update_request` can push a build to one
machine, and every machine reports its running version every 30 s - and
nothing joined them up.

**Fix.** A publish now writes `rollout='staged'` and `staged_at`
(`db.py` SCHEMA_V34, `db.insert_companion_package`), and `[ MAKE CURRENT ]`
goes through one gate that all three doors share
(`api.make_current_refusal`, used by `api_set_current_package` and
`ui.partial_admin_package_current`): refused with a 409 until at least one
machine has been reporting that exact version for `soak_minutes` (site
setting `release_soak_minutes` / `DASH_RELEASE_SOAK_MINUTES`, default 30)
with `crashes.count == 0` and no crash-loop revert (`db.soak_state`,
`db.machines_running_version`). "We could not tell" - an unparseable stamp, a
companion that never sent a crash counter - counts against passing and says
so. The override is `force=1` plus the version typed into a confirmation box.
The soak clock is `machine_state.companion_version_since`, stamped by the
SERVER's clock in `db.upsert_machine_state` before the row's version is
overwritten, so a machine's own clock cannot shorten a soak. A build that has
been current before carries `ever_current` and skips the gate: a rollback is
the recovery the gate exists to make possible.
`[ PUSH TO ONE MACHINE ]` (`ui.partial_admin_package_push_one`) writes the
existing per-machine `commands.upgrade` request for a chosen machine, and the
Packages page shows "canary: N machines on X for M min, C crashes" beside it.
Every one of these is audited through `db.audit` (`package.make_current` with
`forced`, `package.push_one`, `package.roll_fleet_back`, `package.retract`).

**Tests.** `dashboard/tests/test_release_channel.py`: staged by default, the
refusal before any machine reports, the refusal at 0 minutes, the pass at 45,
a crashing canary, a machine that never reported its crash counter, the typed
confirmation, a zero soak, the ungated rollback, push-to-one and its refusal
for an unpublished version.

### REL-3 - there was no recall; a build already taken could not be pulled back - FIXED in repo 2026-08-28, unshipped

**Symptom.** `publish_feed.py --retract` withdrew a build from the vendor
channel and a customer dashboard on the default `manual` policy never acted
on it: the bad build stayed published and `is_current`, and its fleet kept
being offered it. Machines that had already installed it needed a per-machine
`[ UPDATE NOW ]` click each.

**Cause.** `_apply_policy` returned immediately under `manual`, and nothing
anywhere consumed a retraction - the channel had no shape for one.

**Fix.** A signed `retracted: [{kind, platform, version, reason, at}]` block
inside the channel document (so the feed host can neither fabricate nor
suppress one), parsed by `release_feed.channel_retractions` and applied by
`release_feed.apply_retractions` from `check_now` BEFORE the policy runs and
outside it - honoured under every policy, `manual` included. `db.retract_package`
un-currents the row, stamps `retracted_at`/`retracted_reason` (v34) and is
idempotent; `db.set_current_package` refuses a retracted row from every door;
`api._upgrade_info` never serves one; `_valid_records` drops it so it is not
even offered for publish. The Packages page shows the reason and
`[ ROLL THE FLEET BACK ]`, which writes an update request for every machine
still reporting the recalled version (`api.roll_fleet_back`, refusing a
target that is itself recalled or unpublished), and the fleet grid chips
`[ RECALLED BUILD ]` on each machine running one
(`api.build_editors_view` -> `companion_retracted_reason`).

**Tests.** `test_release_channel.py`: the recall under the manual policy with
a fake feed, idempotence, the recalled record never being published under the
`current` policy, malformed entries not losing the good ones, the un-current
+ never-offered + cannot-be-re-currented path, the fleet rollback (including
the machine on another version being left alone) and its two refusals.

### REL-4 / SYS-13 - "deploy the dashboard before the companions" was enforced nowhere - FIXED in repo 2026-08-28, unshipped

**Symptom.** A companion record carried `min_version` (its own downgrade
floor) and nothing about the dashboard it needs, so a site on the `current`
feed policy could take a companion whose features its three-month-old
dashboard has no columns for. The rule is stated four times in CLAUDE.md and
was enforced by a human remembering it: CR-22, CR-27a, CR-49, CR-55, CR-83,
CR-85 and CR-87 are the same failure.

**Cause.** No `requires_dashboard` field existed in the record format.

**Fix.** `requires_dashboard` is an OPTIONAL kind-scoped signed extra on
companion records (`release_trust.OPTIONAL_KIND_EXTRA_FIELDS`, mirrored in
`companion/src/ccsync_companion/release_pubkey.py`), filled by the signing
tools from the new `REQUIRES_DASHBOARD` constant in the companion's
`config.py`. `package_store.blocks_on_dashboard_version` is the one
predicate: `_upgrade_info` never advertises such a build, `make_current_refusal`
refuses it with a 409 naming both numbers, and `package_store.store_verified_package`
refuses a publish that asks to make it current in the same act - which covers
the human PUT and the feed's `current` policy together. An unparseable
requirement blocks rather than passes. The Packages page chips
`[ UPDATE THE DASHBOARD FIRST ]`.

**Overlap cost, deliberate.** The two new signed fields are absent from the
canonical bytes when the record does not carry them, so every record
published before this wave still verifies byte for byte - but a record that
DOES carry one is only verifiable by a companion whose `release_pubkey.py`
mirrors the change. The tools must not emit either field until the fleet is
on such a build (documented in docs/RELEASE.md).

**Tests.** `test_release_channel.py`: the 409 from make-current and from
publish-with-make-current, a requirement equal to this dashboard passing, an
unparseable requirement blocking, and the offer being withheld for a row that
became current before the dashboard was rolled back.

### REL-16 - the channel had no architecture discriminator - FIXED (dashboard half) in repo 2026-08-28, unshipped

**Symptom.** An Intel Mac reports `platform: macos` and was offered the
arm64 build GitHub's runner produced: downloaded, verified, renamed over the
running companion, failed to exec, rolled back - forever, on a ten-minute
timer with `auto_update` on.

**Cause.** `platform` was the record's only discriminator; `release_macos.sh`
measures the arch and dropped it at publish.

**Fix.** `arch` is the second optional kind-scoped signed extra, stored in
v34 and re-served verbatim in the offer. `api._arch_matches` is the rule: an
absent record arch (every pre-wave record) or an absent machine arch is
offered everything, `universal2` matches both, and a stated mismatch is
offered NOTHING rather than a binary that cannot run. `_upgrade_info` takes
the machine's reported `arch` (read with `getattr` from the report payload,
which is `extra="allow"`, until the v35 work package stores
`machine_state.arch`), and the Packages page says "no <platform>/<arch> build
published" for a reported CPU no current build covers.

**Tests.** `test_release_channel.py`: the matching rules, the Intel Mac
offered nothing end to end through `/api/v1/report`, an arm64 machine and an
arch-less companion both still offered, the offer carrying the extras
verbatim and re-verifying, and a plain record's offer gaining no new keys.

### REL-13 - "+dirty" died at the publish boundary - FIXED (columns half) in repo 2026-08-28, unshipped

**Symptom.** A `ship.cmd -AllowDirty` hotfix published as plain `0.9.55`, and
the dashboard, the Packages page, every report and every drift check saw a
version with nothing to say it came from uncommitted code.

**Cause.** `release.ps1` stamps `+dirty` into the MANIFEST; the publish sends
the clean number, and `companion_packages` had nowhere to put provenance.

**Fix.** v34 adds advisory, deliberately UNSIGNED `git_sha` and `git_dirty`
columns; the publish route accepts them as optional query fields and
`release_feed.publish_from_feed` passes them through from the record; the
Packages page renders `0.9.55 (+dirty, no commit)`. The tooling half (filling
them in, and what `-AllowDirty` should do about `-MakeCurrent`) belongs to the
release-tools work package.

**Tests.** `test_release_channel.py::test_git_provenance_is_stored_and_shown`.

### REL-6 - the dashboard's crash-loop watchdog called a boot healthy without asking whether it could serve - FIXED in repo 2026-08-28, unshipped

**Symptom.** An applied code bundle imports cleanly (which is exactly what
stage-verify tested), boots, binds the port, and then 500s every request - a
template missing from the tarball, a lifespan thread deadlocked. The tree is
then permanently "healthy": `select_code_root.py` keeps booting it, the
auto-revert never fires, and the admin cannot roll it back from the dashboard
because the dashboard is the thing that is broken. Compose's
`restart: unless-stopped` restarts a *crashed* container, not a wedged one.

**Cause.** `dashboard_update.start_boot_watchdog`'s thread slept
`BOOT_HEALTHY_SECONDS` and unlinked `boot_attempts.json` regardless of whether
the process had ever answered a request, so the counter that
`deploy/select_code_root.py` reverts on could only ever record "the process
exited".

**Fix.** The same thread now sleeps for uptime as before and then has to PROVE
it can serve: one loopback `GET http://127.0.0.1:$DASH_PORT/api/v1/health`
that must answer 200 with this build's own `version`, retried for up to
`BOOT_HEALTH_PROBE_SECONDS` (`dashboard_update.probe_health` /
`wait_until_serving` / `start_boot_watchdog`, dashboard_update.py:302-410).
`ok: false` is deliberately not required - an unreachable Syncthing is not a
reason to revert code. A boot that never answers leaves the counter standing
and logs why. The opener is its own function (`_loopback_opener`), a redirect
is refused, and no credential is sent.

**Tests.** `dashboard/tests/test_dashboard_update.py`:
`test_a_served_health_route_is_what_marks_a_boot_healthy`,
`test_a_wedged_dashboard_leaves_the_boot_counter_standing`,
`test_a_health_route_answering_as_another_version_is_not_this_boot`,
`test_a_healthy_boot_clears_the_counter` - all through a stubbed opener, never
`urlopen`.

### REL-9 - the stale-update-flag heal keyed on a pid, and container pids repeat - FIXED in repo 2026-08-28, unshipped

**Symptom.** A NAS that loses power while an apply is downloading leaves
`update_state.json` with `in_progress: true, owner_pid: 7`. The container comes
back, `run.sh` is pid 1 and uvicorn is pid 7 again - and every apply AND every
rollback answers 409 for ever, on the appliance shape where the admin has no
shell to delete the file with. That is the exact failure dash-release-ai-2 was
written to end.

**Cause.** `_heal_orphaned_progress` treated `owner_pid == os.getpid()` as
"the worker that owns this flag is alive in THIS process". Container pids are
small and deterministic, so the collision is not a curiosity.

**Fix.** A per-process nonce (`PROCESS_NONCE`, uuid4 at import) is stamped
beside the pid by `_set_state`, and a state file whose nonce differs reads as
interrupted whatever its pid says (dashboard_update.py:120, :455-500). The log
line names both halves of both identities.

**Tests.** `test_the_same_pid_in_a_new_process_is_still_an_interrupted_update`
and `test_this_process_still_owns_its_own_flag`
(`dashboard/tests/test_dashboard_update.py`), alongside the existing
no-owner-pid case.

### REL-10 - rolling the dashboard's code back left the database migrated forward - FIXED in repo 2026-08-28, unshipped

**Symptom.** 0.7.20 applies, migrates `dashboard.db`, misbehaves; the admin
clicks Rollback without `restore_db` - the safe-looking choice, because it does
not throw away today's reports. The code goes back to 0.7.19 against a schema
it does not know. Forward-only additive columns survive that; a rename or a NOT
NULL one does not, and nothing checked or said anything. The UI could not even
express the alternative: `static/dashboard_update.js` sent
`restore_db: ""` as a literal.

**Cause.** The apply recorded nothing about schema on either side, so a
rollback had nothing to compare.

**Fix.** The stage-verify subprocess now reports the new tree's own
`db.SCHEMA_VERSION`; the apply writes it into that tree's `manifest.json` and
writes the live `PRAGMA user_version` of every database, plus the backup
directory, into `current.json` (dashboard_update.py:757-800, :1290-1330).
`schema_rollback_check` compares them and `rollback()` refuses with 409 -
naming the exact backup to restore alongside - unless `restore_db` names one or
`acknowledge_schema` is sent (`RollbackIn.acknowledge_schema`). Rolling back to
the IMAGE, or to a tree applied before this landed, is UNKNOWN rather than
unsafe: it is allowed (the image is the escape hatch of last resort) and the
page says so instead of implying it is fine. The Packages page grew a real
restore checkbox and a schema line, and the JS sends what it says
(`templates/partials/admin_dashboard_update.html:87-120`,
`static/dashboard_update.js:157-185`).

**Tests.** `test_an_apply_records_the_live_schema_and_the_trees_own`,
`test_rolling_back_past_a_migration_is_refused_and_names_the_backup`,
`test_rolling_back_to_the_image_is_never_blocked_by_an_unknown_schema`.

### REL-11 - a feed that has been unreachable for weeks was visible on exactly one admin page - FIXED in repo 2026-08-28, unshipped

**Symptom.** A customer's outbound DNS is filtered, or the vendor renames the
release tag: daily checks fail silently for six weeks and the site quietly
stops receiving fixes, which is indistinguishable from "no fixes were
published". The variant with the same shape: every offered bundle's
`runtime_id` diverges from the customer's image, so every update lands in
`runtime_updates` behind a NAS click nobody makes.

**Cause.** The poller logged a warning and wrote `feed_state.last_error`, and
`build_feed_view` (the Packages partial) was the only reader. `/api/v1/health`
carried no feed fields and no page had a banner.

**Fix.** `dashboard_update.feed_health()` puts `feed: {configured,
last_checked_at, age_days, last_error, records, stale}` into `/api/v1/health`
(api.py:1134-1160); never-checked reads as stale, not as fine. The fleet page
carries two banners built by `api._feed_alarm_block` from durable state: "no
successful update check for N days" past `FEED_STALE_DAYS` (7), and a distinct
"every dashboard build on offer needs a new container image" naming the exact
click `nas_update_hint()` produces. The runtime-mismatch verdict is recorded
into `meta` by the feed check itself (`dashboard_update.record_feed_runtime_mismatch`,
called from `release_feed.check_now`) so the fleet page's builder can read it
from the database rather than a per-process cache.

**Tests.** `test_health_carries_the_feed_age_and_the_data_gauge`
(`dashboard/tests/test_dashboard_update.py`).

### REL-5 - nothing on the release path ever pruned, and a full /data takes the dashboard down - FIXED in repo 2026-08-28, unshipped

**Symptom.** A year of shipping leaves 50 companion exes and 50 onboard exes in
`/data/packages`, a full copy of every database per dashboard update in
`/data/backups`, and every code tree ever applied in `/data/code` - on the
dataset `dashboard.db` lives on. A full `/data` is `sqlite3.OperationalError:
disk I/O error` on every write, i.e. the dashboard that tells everyone whether
their footage is syncing going down.

**Cause.** `db.prune_companion_packages` existed and kept current + 2, and
neither writer called it: `?prune=1` was opt-in and `ship` did not pass it, and
the feed's unattended publisher hardcoded `prune=False`. Neither publish path
looked at free space at all, while `dashboard_update.preflight` had refused an
apply at 507 since WP K.

**Fix.** Prune is now the default on both paths (`api.api_publish_package`'s
`prune: int = 1`, `?prune=0` to opt out; `release_feed.publish_from_feed`
passes `prune=True`). `/data/backups` is bounded to the newest 3 per label, 8
in total and 8 GiB, and `/data/code` to the running tree plus the one
`current.json` can roll back to plus one, both run after a successful swap
(`dashboard_update.prune_backups` / `prune_code_trees`). A publish below the
same free-space floor an apply is held to is refused with 507
(`api._refuse_publish_without_space`), and "could not measure" never refuses.
`/api/v1/health` and the Packages page carry a `/data` gauge
(`dashboard_update.data_space`).

**Tests.** `test_publish_prunes_by_default`, `test_prune_can_be_opted_out_of`,
`test_a_publish_is_refused_when_the_volume_is_nearly_full`,
`test_an_unmeasurable_volume_does_not_block_a_publish`
(`dashboard/tests/test_packages.py`); `test_backups_are_bounded_per_label`,
`test_old_code_trees_are_pruned_to_running_previous_and_one`,
`test_the_packages_page_shows_the_data_gauge`.

### DASH-2 - rotating (or losing) DASH_SESSION_SECRET 401s every companion in the fleet - FIXED in repo 2026-08-28, unshipped

**Symptom.** The owner rotates `DASH_SESSION_SECRET` (which `secrets_boot`'s
docstring explicitly says stays possible), or restores `/data` from a snapshot
taken before `<data>/secrets/dash_session_secret` existed. `X-CCSync-Identity`
is an HMAC over that secret and never expires (CR-86), so `POST
/api/v1/report` 401s for the entire fleet at once: the grid goes stale, and the
halt / pushed-update / lane-B-resume / file-move command channel dies with it.
The only cure was every editor clicking "Sign in..." at their own tray, with no
message anywhere saying why - and the grid's only symptom, rows going stale,
is exactly what a switched-off machine looks like.

**Cause.** One secret, no accept-only predecessor, and a refusal with no
record: `api_report` raised 401 before anything was written.

**Fix.** `DASH_SESSION_SECRET_PREVIOUS` (comma-separated, newest first,
ACCEPT-ONLY - nothing is ever minted with one) is read into
`settings.session_secrets_previous` and consulted by `auth._read_token_any`
for both purposes, so companion identities and browser sessions both survive a
rotation (auth.py:369-435, :506-520 - a session id is derived with the secret
that verified the cookie, or the server-side row could not be found). Every
accepted report on a retired key is logged and counted
(`db.record_retired_key_identity`), and the fleet page shows
`[ N COMPUTER(S) STILL ON A RETIRED SIGNING KEY ]` counting DOWN as editors
sign in again - the drain, so the operator knows when the old key can go. The
boot log names the retired keys at every start, and a weak one is refused like
any other. A report refused ONLY because its identity cannot be verified now
stamps v35 `machines.report_refused_at` / `report_refused_reason` on the
EXISTING row and nothing else (`db.stamp_report_refused`, api.py:5990-6040), so
the grid says `[ BEING REFUSED: SIGN IN ON ITS TRAY ]` with a fleet banner
beside it; an accepted report clears it. Nothing from the refused body is
stored. `docs/SECRETS.md` gained the rotation runbook.

**Tests.** `dashboard/tests/test_auth.py` (four: previous-key acceptance for
both token purposes, accept-only + retired flag, the boot-time floor);
`dashboard/tests/test_report_endpoint.py`
(`test_a_refused_identity_is_recorded_against_the_machine`,
`test_an_accepted_report_clears_the_refusal`,
`test_a_refused_report_stores_nothing_from_its_body`,
`test_the_grid_says_a_computer_is_being_refused`,
`test_the_grid_counts_the_retired_key_drain`);
`dashboard/tests/test_db.py::test_the_retired_key_ledger_counts_up_and_back_down`.

### REL-8 (dashboard half) - a machine that cannot take a build retried for ever and nobody was told - FIXED in repo 2026-08-28, unshipped

**Symptom.** An editor's AV quarantines every downloaded companion exe, or a
proxy mangles it so the sha never matches. The report payload carried nothing
about upgrade outcomes, so the dashboard could not tell "has not seen the push
yet" from "has failed 140 times", and the admin's pushed update showed as
pending for ever - with no expiry, so the request rode every report
indefinitely.

**Cause.** No `upgrade` block on the wire, no columns, no expiry on
`machines.update_requested_*`.

**Fix.** v35 adds `machine_state.arch` and `upgrade_version` /
`upgrade_attempts` / `upgrade_last_error` / `upgrade_last_attempt_at` /
`upgrade_reverted_from`, plus `machines.report_refused_at` /
`report_refused_reason` (db.py SCHEMA_V35). `api.UpgradeIn` declares
`sync_guard.upgrade` and `ReportIn.arch` the top-level field;
`db.store_upgrade_state` writes them on the latch rule, except
`reverted_from`, which the companion sends once and which clears itself when
the machine reports a build at or above the one it fell back from (two-digit
minors compared properly - `db.version_tuple`). The grid chips
`[ UPDATE FAILED x8 ]` and `[ REVERTED FROM 0.9.56 ]`, and the Packages page
shows attempts and the last error beside the pending request. A
`machine_update_request` older than 14 days is expired in the prune cycle with
the reason in the audit ledger (`db.expire_machine_update_requests`).

**Tests.** `dashboard/tests/test_report_endpoint.py` (storage, the unknown-key
tolerance, the revert marker's own lifecycle, both chips);
`dashboard/tests/test_db.py::test_a_pushed_update_expires_with_an_audit_row`;
`server/tests/test_cross_component.py::test_the_upgrade_telemetry_the_dashboard_stores_is_actually_sent`
- the parity gate in the other direction, so a dashboard chip that no build in
the field can ever light fails the build instead of reading as "nothing wrong".

### OPS-1 - a bind-mode deploy never checked that the dashboard came back up - FIXED in repo 2026-08-28, unshipped

**Symptom.** `tools\ship.cmd` reports "restarted container: ccsync-dashboard",
exits 0 and goes on to publish companions to the whole fleet, while the
dashboard itself is down. The only signal is an owner opening a browser.

**Cause.** Every path through `install_dashboard_app.py`'s redeploy branch
ended at `restart_dashboard_container()` returning True and `return 0`.
`docker restart` succeeding means the container was recreated and nothing
more: new code that raises at import (a moved template, a module
`EXCLUDE_DIRS` dropped, a lockfile drift, a bad `site.toml` value) restarts
perfectly and answers nothing. In image mode `verify_image_boot` did run, and
its result was discarded on that same path.

**Fix.** `probe_dashboard_health()` asks `/api/v1/health` from INSIDE the
container (`/venv/bin/python`, 127.0.0.1, `docker exec`) and requires a 200
whose `version` equals this checkout's dashboard VERSION, read by regex from
`dashboard/src/ccsync_dashboard/__init__.py` (`repo_dashboard_version`,
`install_dashboard_app.py:865-1000`). It retries for 150 s, covering the
compose healthcheck's own 120 s `start_period`, so a slow cold start is not
reported as a dead dashboard. `verify_dashboard_after_restart()` prints the
exact rollback one-liner - `mv <root>/app <root>/app.failed-<ts>; mv
<root>/app.old.<ts> <root>/app; docker restart <container>`, naming the tree
THIS run renamed aside (`install_tree` records it in `_LAST_OLD_DIRS`) rather
than a glob - runs it under the new `--rollback-on-unhealthy`, and returns 1
either way, because a rolled-back deploy is undone rather than finished. Both
the redeploy branch (`:4600+`) and the fresh-create path now gate on it, and
`verify_image_boot`'s result is honoured on the redeploy path too.
`tools\ship.ps1` already stopped on a non-zero deploy (step 1's
`if ($LASTEXITCODE -ne 0) { exit 1 }`, verified, unchanged).

**Tests.** `server/tests/test_deploy_resilience.py` (11 new): the probe
demands the version and not merely a 200, retries across a cold start, reads
health from inside the container, an unhealthy dashboard prints the exact
rollback and returns 1, `--rollback-on-unhealthy` runs the rename and
re-probes, a rollback with no recorded tree refuses rather than guessing,
`install_tree` records the tree it renamed aside, and a redeploy that does not
come back exits non-zero while one that does exits 0.
`server/tests/conftest.py` stubs the probe healthy for every other test (the
suite's fake `run_ssh` answers "" to everything, which is the wedged-container
shape).

### OPS-12 - the ship asked for the dashboard password only after the whole build - FIXED in repo 2026-08-28, unshipped

**Symptom.** A mistyped password, or a dashboard still restarting from the
deploy step `ship.cmd` just ran, ends the run after gates, deploy, two
PyInstaller builds and twenty minutes - in the half-shipped state (dashboard
deployed, companion not published) this repo has been bitten by before.

**Cause.** `build_editor_package.ps1` prompted and logged in immediately
before the upload, one attempt, `exit 1` on any failure - while the CR-52
floor check two hundred lines above makes exactly the opposite argument
("PyInstaller takes minutes; tell the operator at second 1").

**Fix.** `Connect-Dashboard` runs beside the CR-52 preflight, before the
build, and the session it opens is the one the uploads use
(`installer/build_editor_package.ps1:320-420`). It probes `/api/v1/health`
first, so "cannot reach the dashboard" is said without prompting for a
password at all; a 401/403 is retried up to three times with "wrong password
(n of 3)"; anything else refuses with the server's message. The late login
block is gone.

**Tests.** `tools/tests/test_release_scripts.py::TestThePasswordIsAskedForBeforeTheBuild`
pins the ordering (login before the PyInstaller section) and both messages.

### REL-7 - a mis-rotated release key stranded the fleet, and the parity check could not see it - FIXED in repo 2026-08-28, unshipped

**Symptom.** Everything passes - the new build trusts the new key, the record
verifies, the dashboard accepts the publish - and every companion in the field
refuses the offer for ever, logged once, tray silent, recoverable only by a
hands-on reinstall per machine.

**Cause.** The one guard (`release.ps1:492-527`) compared the signing key with
the keys baked into **the build being built**, which is the single place the
two can never disagree. Nothing compared it with the build the fleet is
actually running.

**Fix.** `release.ps1` now records `baked_pubkey_ids` (plus `requires_dashboard`
and `arch`) in the release manifest, computing the ids the way
`release_pubkey.pubkey_id` does. `publish_feed.py` carries them onto the
channel record and refuses, before signing anything, when the signing key is
not in the `baked_pubkey_ids` of the record `current` points at
(`baked_keys_of_current`, `--allow-key-rotation` overrides); a current record
with no list says the check could not run rather than passing silently.
`build_editor_package.ps1` does the same against the dashboard for the PUT
path, comparing this rig's key id with the `pubkey_id` of the current windows
companion row (`Test-SigningKeyTheFleetTrusts`), refusing with "EVERY MACHINE
ON v<current> WILL REFUSE THIS BUILD" unless `-AllowKeyRotation`;
`ship.ps1` passes the flag through and `publish_latest.py` has
`--allow-key-rotation`. `release_key.py bake` stays warning-only and prints
the same sentence.

**Tests.** `tools/tests/test_publish_feed.py` (4): a key the current build
does not trust is refused, a deliberate rotation is allowed and says what it
costs, the ordinary ship publishes freely, and a pre-2026-08-28 current record
says the check could not run.
`tools/tests/test_release_scripts.py::TestAKeyTheFleetDoesNotTrustIsRefused`.

### REL-12 - `windows_upgrade.ps1` overwrote the installed exe with no copy of what it replaced - FIXED in repo 2026-08-28, unshipped

**Symptom.** The new build exits inside the relaunch window and the script
prints an accurate, useless warning: this machine now has no companion, no
lanes, no Resolve bridge, and nothing retries before the next logon. Unlike
the self-upgrade path there was no `.old`, so there was nothing to restore
even by hand.

**Cause.** Step 2 was `Copy-Item -Force` straight over the live exe.

**Fix.** `Move-InstalledAside` renames the installed exe to
`ccsync-companion.exe.prev` before the copy, and `Restore-InstalledFromPrev`
puts it back - moving the failed build to `ccsync-companion.exe.failed` first,
because it is the only evidence of why. The relaunch-failed branch restores,
relaunches, and says "the new build would not start - this machine is back on
vX" (the previous version read out of the manifest before it was overwritten);
a copy that fails all five attempts also restores, so the machine is never
left with no exe. `.prev` survives until the next upgrade renames over it.
`installer/windows_upgrade.ps1:76-115, 168-235, 400-460`.

**Tests.** `installer/tests/Test-PrevRollback.ps1` (14 checks), sliced out of
the script the way `Test-LicenceGate.ps1` slices its helpers; wired into
`tools/run_all_tests.ps1`'s installer row.

### REL-13 - "+dirty" died at the publish boundary - FIXED in repo 2026-08-28, unshipped

**Symptom.** A `ship.cmd -AllowDirty` hotfix reaches the fleet as plain
"0.9.55". Nothing on the Packages page, in a report or in the drift check says
it came from uncommitted code - and the real committed 0.9.55 can then never
be published (same version, different bytes), so the fleet's 0.9.55
corresponds to no commit, permanently.

**Fix.** `sign_release.py` takes `--git-sha`/`--git-dirty` and puts them in the
query the publish sends (UNSIGNED: they change nothing about what may be
installed, and signing them would cost an overlap release); `publish_feed.py`
reads them from the manifest and records them on the channel record;
`build_editor_package.ps1` passes them from `ccsync-release.json`, and drops
them if the manifest describes a different exe. `-MakeCurrent` on a dirty
build now needs `-IReallyMeanDirtyCurrent` as well - without it the build is
published STAGED and says so, in both `ship.ps1` (at the dirty gate, before
anything moves) and `build_editor_package.ps1` (at the publish, from the
manifest, which is the authority on the exe in hand). The `+dirty` version
stamp in the manifest is unchanged.

**Tests.** `tools/tests/test_sign_release.py` (the query carries both),
`tools/tests/test_publish_feed.py::test_provenance_rides_along_unsigned` (and
that the record still verifies with them present),
`tools/tests/test_release_scripts.py::TestADirtyBuildIsNotHandedToTheFleetByAccident`.

### REL-14 - `publish_latest` asked a possibly-stale local ref whether a commit is on main - FIXED in repo 2026-08-28, unshipped

**Symptom.** A commit is pushed to main, CI goes green, the commit is
force-pushed away; a rig that has not fetched since signs and publishes a
build the release branch no longer contains.

**Cause.** `commit_is_on_main` ran `git merge-base --is-ancestor <sha>
origin/main` with no fetch. The guard's own docstring says a branch label is
"a claim a force-push can make untrue"; the local remote-tracking ref can be
untrue the same way.

**Fix.** `remote_head_sha()` asks `git ls-remote origin refs/heads/main`,
`release_branch_tip()` fetches only when this clone does not already hold that
commit, and the ancestry test compares against that sha
(`tools/publish_latest.py:172-230`). A remote that cannot be asked is a
refusal, not a fallback to the local ref. The tip is printed at the start of
the run and again in the summary, so the operator sees what was compared.

**Tests.** `tools/tests/test_publish_latest.py::TestTheBranchTipComesFromTheRemote`
(4): ls-remote is used, an unreachable remote yields nothing, a missing commit
is fetched before it is trusted, and the ancestry test uses the tip it was
given.

### REL-15 - ship published the companion and the installer as two independent acts - FIXED in repo 2026-08-28, unshipped

**Symptom.** A dropped connection or a Ctrl-C between the two PUTs leaves the
companion CURRENT for the whole fleet while the installer channel still serves
an `onboard.exe` bundling the previous companion, so every fresh install lands
a version behind. Nothing recorded how far the ship got; the only recovery was
to read the script and re-run the right half.

**Fix.** Both artefacts are now uploaded STAGED (`make_current=0` on both
PUTs) and flipped to current in one final step, two calls back to back after
both uploads (`installer/build_editor_package.ps1`). A refused flip - the
dashboard's soak gate (REL-1) - prints the dashboard's own words verbatim and
exits 3; `ship.ps1` treats 3 as "published and staged", not a failed ship, and
says what to do. `tools\.ship-state.json` (gitignored) records
`{step, version, installer_version, timestamp, made_current, dashboard_url}`
at every step, and `ship.cmd -Resume` continues from it, refusing a journal
that names a different companion version because that is a new ship rather
than a resumption.

**Tests.** `tools/tests/test_release_scripts.py::TestBothArtefactsBecomeCurrentTogether`
(5): the uploads are staged, the flip comes after both PUTs, exit 3 is not a
failed ship, the journal exists with all six steps, and it is gitignored.

### REL-4 / REL-16 / REL-3 (tool halves) - the record could not carry the ordering rule, the architecture, or a recall - FIXED in repo 2026-08-28, unshipped

**Fix (REL-4/REL-16).** `sign_release.py` takes `--requires-dashboard` and
`--arch` and puts them in the signed record through
`release_pubkey.OPTIONAL_KIND_EXTRA_FIELDS` (the companion agent's
optional-extras mechanism: blank reads as ABSENT, so every record published
before this wave canonicalises byte for byte as it always did and no overlap
release is owed). The two fail in opposite directions on a checkout whose
record module does not cover them: a `requires_dashboard` that would be
dropped is REFUSED (an ordering rule that exists only in the operator's head
is worse than none), while an `arch` degrades to "offered to every machine on
that platform" with a note, which is what every earlier record says.
`release.ps1` measures both (`REQUIRES_DASHBOARD` read from `config.py` by
regex, arch from `PROCESSOR_ARCHITECTURE`) into the manifest,
`release_macos.sh` does the same with `uname -m` and passes them to the
signer, and `publish_feed.py`/`build_editor_package.ps1` carry them from the
manifest rather than letting anyone retype them.

**Fix (REL-3).** `publish_feed.py --retract KIND/PLATFORM/VERSION` now
requires `--reason` and writes a signed `retracted` list entry
`{kind, platform, version, reason, at}` beside removing the record. The list
is what reaches a dashboard on the default `manual` policy, which otherwise
never acts on the channel again. `merge_into_published` only ever ADDS recall
entries, so a publish from a fresh clone cannot re-offer a build the vendor
pulled, and publishing a recalled version is refused unless the same run
retracts it (the deliberate withdraw-then-republish path stays open).

**Tests.** `tools/tests/test_sign_release.py` (6): a blank optional extra is
omitted so pre-wave records keep verifying, declared values are inside the
signature and tampering breaks it, both ride in the query, an unsignable
`requires_dashboard` is refused, an unsignable `arch` degrades with a note,
and an unrankable `requires_dashboard` is refused.
`tools/tests/test_publish_feed.py` (5): the reason is published and required,
a recalled version cannot be republished in a later run, a recall survives a
publish from a feed dir that never saw it, and an arch the record cannot carry
does not make the build unpublishable.

## Resilience sweep, wave 4: the human layer (2026-08-28) - FIXED in repo, unshipped

Wave 4 of `docs/RESILIENCE_SWEEP_2026-08-28.md` (items 15, 24, 25, 27, 35,
38, 41 and the ten confirmation dialogs C-1 to C-10 from `UX.md`, plus
UX-12/13/14/15/19/20/21/22, OPS-6/7, RES-10, DASH-3/4/5/8/9/10/11,
SYS-3/5/9 and SYNC-17 from the same files), built by builder agents to one
contract and closed out by a documentation pass that wrote the tests the
first pass had not. Before this wave the dashboard had never once been the
DISCOVERER of an outage: sixteen `log.error` diagnoses in the collector
reached nobody, every alarm was pull-only, HALT ALL SYNCING was one
unconfirmed click with no expiry, an unsigned build could be made current
and silently stop every companion updating, a package delete threw away the
bytes a rollback needs, a file move Resolve blocked was refused for ever and
the file re-uploaded itself a day later, a project folder renamed in
Explorer reported as idle, IGNORE ALL was permanent for the session and
invisible, ingest staging was never cleaned up, and a closed wizard left a
machine with no companion and no record of it.

After it: the server keeps a `notices` ledger (v37) that the home page shows
as PROBLEMS THE SERVER FOUND, each row carrying the exact next action, and a
WHAT THE SERVER CHECKS list in which a kind nothing writes reads NOT
CHECKED, never OK; forty alert kinds are evaluated every collector cycle
from data the dashboard already had, deduplicated per `(kind, subject)`,
logged (`alert_log`, v38) and delivered through a sink the site chooses
(none, the vendor default; smtp; an https webhook), with a Monday weekly
report that lists what was checked and found fine; a halt has a 24 h expiry,
a banner on every page, a history, a confirm with the consequence in it and
a 3-character reason on both routes; MAKE CURRENT on an unsigned build is a
409 unless the version is typed; a deleted package goes to
`<data>/packages/.trash/` for 30 days; a file move is two-phase (v36), the
companion answers `retrying` and is re-sent the command until it is done or
blocked, an undelivered move never expires, the confirm names the file and
both ends, and there is an UNDO; a project directory that was here last pass
and is gone is `project_dir_moved`, with a PUT IT BACK button, and a project
folder in no plan is counted; SKIP FOR NOW is a record, "leave this folder
alone" is persisted with a FORGET button, and Scan whole project offers
everything again; ingest staging is retained for a configurable number of
days with a CLEAR FINISHED STAGING button; a drop is refused above the free
space and confirmed with its size and hours; the wizard leaves a breadcrumb
the companion reports as a config problem until the install is finished;
site.toml import snapshots the previous values and can be undone.

Ships as: dashboard first (schema v36 + v37 + v38, which `db.py` requires to
ship together), then companion 0.9.55 (the build waves 1 to 3 already owe),
then a rebuilt installer package AND onboard.exe as installer 1.0.37 (1.0.36
was published 2026-08-21; the bootstraps and the wizard changed in waves 3
and 4). Deploy order is load-bearing for the file-move retry: a pre-v36
dashboard reads a `retrying` answer as "answered, stop asking" and never
resends the command. The new companion report sections (`resolve_health`,
`stray_projects`, `moved_project_dirs`, `ingest_staging`) are tolerated by an
old dashboard (`SyncGuardIn` is `extra="allow"`) and merely not shown. New
settings (site_settings rows, never in `/api/v1/site`): `alerts_sink`,
`alerts_smtp_*`, `alerts_webhook_url`, `alerts_timezone`, `alerts_weekly`.
New env: `DASH_INTERVAL_ALERTS`, `DASH_ALERTS_SMTP_PASSWORD`. New secret
file: `<data>/secrets/alerts/smtp_password`. New companion config:
`broll_ingest_staging_retention_days` / `music_ingest_staging_retention_days`
(7). New companion state under `~/.ccsync/state/`: `fixer_ignores.json`,
`skipped_clips.json`, `project_dirs.json`, `install_in_progress.json` (the
wizard writes it). New collector kind `alerts`. New pages: Settings ->
ALERTS, the fleet-halt banner partial. Operator docs: `docs/SELF_DIAGNOSIS.md`
(new), `docs/FILE_MOVES.md` (rewritten for the two-phase shape).

Not built in this wave, deliberately or not, and still open in the theme
docs: DASH-10's `settings.num()` silent fallback and unstripped token
headers; DASH-11's "freeze that device's shares" (detection only); SYS-9's
remaining seven invariants (wave 5, item 40); the forward directory move
still takes no snapshot (only the undo does); the `file_move_quarantine`
meta key has no UI reader beyond the project-page chip; `notices` rows are
never pruned; the topbar `[ LOGOUT ALL ]` and the wizard's console-user
probe are weaker than their `.ps1` twin.


### UX-10 - the server refused things for good reasons and told only the container log - FIXED in repo 2026-08-28, unshipped

**Symptom.** Somebody copies a project folder onto `Projects/2026/CCT/` with its
`.ccsync-project` marker inside, or drops a marker on a folder that already
holds three projects. Provisioning refuses, correctly, with an excellent
sentence - into a Docker log a non-technical owner will never open. The three
projects are simply gone from the dashboard, nobody can tick them, and nothing
anywhere on screen says why. The sweep counted sixteen already-written
diagnoses in `collector.py` / `provision.py` (`_creatable`'s container and
nested-marker refusals, `_duplicate_path_folder`, two directories claiming one
slug, a damaged marker, a failed shared-asset or link resolution) with exactly
that fate, and the owner widened the brief the same day: "make the server as
self-diagnosing as possible. Any errors should be flagged, the diagnosis should
be as clear as possible" - so the same pass now also reads the last outcome of
every collector job, the persisted brakes, the registry, disk space, the feed
and the boot-time configuration, and a 500 an editor met at 2 am is on the
home page in the morning.

**Cause.** No `notices` table existed in `db.py` or `schema.sql`; the only
output of every refusal was `log.error`, per cycle and in memory, lost with the
container.

**Fix.** Schema v37 adds `notices` (`db.py` SCHEMA_V37): one row per
`(kind, subject)` with `severity` (`info`/`warn`/`error`), `body`, a mandatory
`fix` in plain words, `first_seen`, `last_seen`, `cleared_at`. `db.notice()`
upserts - `first_seen` is kept, `last_seen` bumped and `cleared_at` NULLed, so
a condition an admin dismissed that is still true comes straight back;
`db.clear_notice()` closes one, `db.clear_notices_of_kind(kind, keep_subjects)`
closes every subject of a kind that a pass-shaped writer no longer reports, and
`db.dismiss_notice()` is the admin's `[ DISMISS ]` (audited as
`notice.dismiss`, refuses an id that is not open). `db.NOTICE_KINDS` is the
registry of 31 kinds with a severity and a one-line "what", rendered by
`db.notice_kinds()` so an empty panel can say WHAT was checked.

Two halves write it. The WRITERS: `collector._provision_slug` / `_creatable`
(`project_container_marker`, `project_nested_marker`,
`duplicate_syncthing_folder`, `duplicate_slug_dirs`,
`unreadable_project_marker`, `provision_failed`, `shared_assets_failed`,
`project_links_failed`; `_creatable` grew a `conn` argument for it), each
draining a `self._notice_open` set at the end of the pass so a refusal that no
longer applies closes itself; `app.CollectorWatchdog` (`collector_watchdog_restart`,
on its own connection, so a notice can never stop a restart); and the 500
handler in `app.create_app` -> `notices.record_server_error` (`server_error`,
one row per `(path, exception class)` with a rising count, and NOTHING from the
exception's message is stored). The CHECKS: `notices.run_checks()`, a read-only
pass at the end of every collector cycle (`collector.run_cycle`, wrapped so a
diagnosis can never fail the cycle it describes), each check isolated and a
check that raises leaving its notices ALONE rather than clearing them:
`_check_collector_jobs` (`collector_cycle_failed` per kind with `_JOB_MEANING`
saying what that job's failure costs, `collector_db_write_failed` when the
error names a disk/readonly/locked sqlite fault, `syncthing_unreachable`),
`_check_collector_alarms`, `_check_tree` + `_check_inventory`,
`_check_identity_collisions`, `_check_pending_devices`, `_check_machine_space`,
`_check_dashboard_space`, `_check_release_feed` (`feed_unreachable` after 48 h
or any error, `feed_runtime_mismatch`), `_check_accounts`; plus
`notices.check_settings()` once at boot. Every body is built from names,
counts and timestamps, the one quoted string (a collector exception) is
truncated to 200 chars, and no secret is ever formatted.

Where it shows: `templates/partials/notices.html`, the `[ PROBLEMS THE SERVER
FOUND ]` panel above the fleet grid (`fleet.html`, admin only, `hx-trigger="load,
every 60s"`, `ui.partial_notices` / `partial_notice_dismiss`), which renders
NOTHING but the collapsed `partials/notice_checks.html` list when nothing is
open - `[ FOUND ]`, `[ OK ]` on EVIDENCE (`db.notice()` / `clear_notice()` /
`clear_notices_of_kind()` stamp `{kind: last_checked}` into
`NOTICE_CHECKS_META` every time a pass evaluates a kind, found or not, and
`db.notice_check_times` reads it back), or `[ NOT CHECKED ]` for a kind that
is registered and has never been evaluated, so a kind nobody writes can never
render as fine; the topbar chip `[ N PROBLEMS ]`
(`partials/topbar.html`, error count only, admin full-page renders only via
`ui._render` -> `_notice_counts_safe`, absent at zero because a bar that
always reads `[ 0 PROBLEMS ]` stops being read); and `/api/v1/health` ->
`notices: {error, warn}` (`api._open_notices_block`, a count that cannot be
read reports as one error). Open notices of severity `error` are also picked
up by the alerts registry as the `notice_error` kind (SYS-8), so they reach the
sink. The home panel shows at most `NOTICE_PANEL_LIMIT` (25) rows; the
per-kind cap in the checks is `MAX_ROWS_PER_KIND` (20).

**Tests.** `dashboard/tests/test_notices.py` (16, written in the closing
pass): upsert keyed `(kind, subject)`, a repeat updates rather than
duplicates, clear, DISMISS semantics, `run_checks()` never raises and leaves
a raising check's notices alone, the checked / not-checked evidence including
a full render of `/partials/notices`, `plan_without_share` (fires, clears,
excludes upload-only ticks and the unassigned bucket, silent before the
first config pass), the disk floor. `test_provision.py` was updated for
`_creatable`'s new `conn` argument; `test_no_em_dash.py` scans the new
templates and string literals.

### SYS-8 - there was no outbound notification of any kind; detection latency was "until the owner next looked" - FIXED in repo 2026-08-28, unshipped

**Symptom.** A lane B breaker trips on two machines at 18:00 on a Friday. The
dashboard renders the alarm perfectly, and nobody has the page open until
Monday. Every alarm this system raised - tripped breaker, fleet halt,
unfiltered folders, a stale collector, an editor 12 GB behind - was pull-only.
Read as a taxonomy, 0 of the ledger's ~120 entries were discovered by the
system telling anybody; SYNC-17's 18 h, CR-27a's 18 h and CR-86's two days were
each found by the owner happening to look.

**Cause.** No SMTP, webhook or notification code existed under
`dashboard/src/ccsync_dashboard/`; `/api/v1/health` was the only
machine-readable summary and nothing polled it.

**Fix.** `alerts.py`, measuring nothing new: every check reads state other
modules already compute (`api.build_editors_view`, `db.collector_health`,
`db.get_feed_state`, `db.get_fleet_halt`, the v37 notices, the v34 release
rows). THE CHECKS ARE DATA: `ALERT_KINDS` is a tuple of 40 `AlertKind(kind,
severity, title, what, check)` rows, gathered once per scan into a `Ctx` (no
per-machine queries; tables from sibling work packages read through `_rows`,
which treats an absent table as "nothing to report"), and `scan()` evaluates
all of them into flat findings `{kind, severity, title, subject, diagnosis, fix,
detail}`. The finding asked for four immediate alerts; the built registry
covers those four (`breaker_tripped`, `machine_silent` at 24 h,
`watchdog_restart`, `disk_low` / `disk_park` / `data_disk`) and 36 more,
including `fleet_halt` / `fleet_halt_expired`, `report_refused`, `clock_skew`
(5 min, deliberately above the grid's 1 min), `engine_down` /
`nas_engine_down`, `lane_stalled`, `lane_error` (1 h), `folders_unfiltered`,
`thread_restarts` (3/24 h), `crashes`, `upgrade_failed` (8) /
`upgrade_reverted`, `collector_kind_failed` / `collector_stale`,
`enforce_refusal` / `deactivation_refusal` / `enforce_plan`,
`ignored_sections`, `feed_stale` (7 d) / `feed_runtime_mismatch`, `nas_tree`,
`notice_error`, `file_move_expired`, `versions_behind` (3 published builds),
`soak_failed`, `retracted_running`, `key_drain` (7 d), `weekly_send_failed`,
and LAST `red_unexplained` (red for 1 h and no other kind named it; a machine
another kind named is skipped through `Ctx.name`). Every diagnosis is one or
two plain sentences, `fix` names a button or a tray action, `detail` carries
the technical line. A CHECK THAT RAISES BECOMES A FINDING: `CHECK_FAILED`
(severity error, subject = the kind that failed, "treat it as unchecked, not as
fine"), and a `Ctx` that cannot be built is one finding for the whole scan.

Delivery: `deliver()` applies the SEVERITY's repeat rule - an `error` is
re-sent once a day for as long as it is true, a `warn` once until it has
cleared and come back - through `send()`, which dedups on `alert_log`
(`db.alert_recently_sent`, 24 h window, counting FAILED sends so a broken sink
does not re-attempt every condition every cycle) and records every attempt
(`db.record_alert`, ok=0 rows kept). A subject that stops appearing gets a
recovery message filed under `<kind>.ok` (`RECOVERED_SUFFIX`), only for kinds
whose check actually ran this cycle; "is this subject open" is two timestamps
in `alert_log` (`_is_open`), durable across a container replacement. The sink
is a site setting, `alerts_sink`: `none` (the default and the vendor build's
shape - the scan still runs, the Alerts page still shows what is open, and each
send is recorded ok=0 "no sink configured"), `smtp` (`_send_smtp`: STARTTLS by
default, login when a user is set, `EmailMessage`, an auth failure reported as
"the mail server refused the sign-in" so the server's echo can never carry the
password) or `webhook` (`_send_webhook`: POST `{subject, text}` as JSON to an
https URL, refused at save AND at send if not https, no redirects followed per
GOTCHAS §12, opener stubbable for tests). One delivery is capped at
`SEND_TIMEOUT_SECONDS` (20) because this runs on the collector's single thread.
Settings live in `site_settings` through `alerts.set_settings` (validated
all-or-nothing, unknown keys refused; NOT `site_store`, so an SMTP username can
never reach `/api/v1/site`); the SMTP password is a 0600 file at
`<data>/secrets/alerts/smtp_password`, overridden by `DASH_ALERTS_SMTP_PASSWORD`
(env wins, and the page then says so), never in the database and never in a
response (`settings_view` returns `password_set`, `password_source` and a mask
that hides a short value entirely).

The weekly report: `compose_weekly()` - subject "CC Sync weekly: N
computer(s), E problem(s), W thing(s) to look at"; PROBLEMS and THINGS TO LOOK
AT (every open finding with its fix), BUILDS ("0.9.55: 6 of 8 machine(s)" plus
every laggard by name and since when), WHAT CHANGED THIS WEEK (`db.audit_since`,
40 rows), ALERTS SENT THIS WEEK with failures marked, `.ccsync-trash` per
machine where reported, CHECKED AND FOUND NOTHING WRONG (n of 40, by `what`)
and COULD NOT BE CHECKED. Bytes moved per lane is a live probe on
`lane_report_current` and is omitted today (no such column); `.stversions`
sizes are omitted because no companion measures them. Sent at Monday 08:00 in
`alerts_timezone` (`previous_weekly_slot`, computed on the local calendar so
DST does not move it), and "owed" is durable (`weekly_due` compares the last
`weekly` row in `alert_log` against the slot): a container replaced at 07:59
sends it once, one down all Monday sends it Tuesday, six restarts do not send
it six times. `alerts_weekly=0` turns it off.

Plumbing: `collector.KINDS` gains `alerts` as the ninth kind, in
`SYNCTHING_FREE_KINDS` so it can report Syncthing being unreachable, run last
on `settings.interval_alerts` (`DASH_INTERVAL_ALERTS`, 600 s); `_run_alerts`
hands the watchdog's restart count (`Collector._restarts`, counted BEFORE the
replacement thread starts) to `run_cycle` and returns its note ("3 problem(s)
open" / "N alert(s) could not be delivered") so a site with no sink is amber on
the collector panel rather than green. Settings -> ALERTS
(`templates/admin_alerts.html`, `partials/admin_alerts.html`,
`partials/settings_nav.html`; `ui.page_admin_alerts`, `partial_admin_alerts_save`
/ `_password` / `_test`, `page_admin_alerts_preview`): CURRENTLY OPEN computed
live from `scan()` (useful on a `none` site), WHERE ALERTS GO, `[ SEND A
TEST ]` (dedup off), `[ PREVIEW THIS WEEK'S REPORT ]` (text/plain), WHAT WAS
SENT (newest first, failures kept), WHAT THIS SERVER CHECKS. JSON twins
`api.api_alerts` / `api_alerts_test` / `api_alerts_preview` under
`/api/v1/admin/alerts`, and `/api/v1/health` -> `open_alerts` from a live scan
(`api._open_alerts_block`; a scan that cannot run is `{error: 1, scan_failed:
true}`, never zero). `alert_log` is pruned at `ALERT_MAX_AGE_DAYS` (120).

**Closing-pass fixes.** Two defects the documentation pass found in the
first build: (1) with the sink at `none` (the vendor default) the weekly
report was recorded through `send()` as `ok=0` "no sink configured", and
`_check_weekly_send` then raised `weekly_send_failed` every cycle from the
first Monday - a permanent red PROBLEM on a site that had configured
nothing. `run_cycle()` now records a sink-`none` weekly as
`ok=True, "generated, not sent (no sink configured)"` (still readable at
`/admin/alerts/preview`) and `weekly_send_failed` fires only for a CONFIGURED
sink that failed. (2) `db.META_ALERTS_OPEN` (`alerts_open_counts`) was read
by `ui._alert_counts_safe` and written by nothing; `run_cycle()` now writes
the per-severity counts from the same scan and the topbar shows
`[ N ALERTS ]` beside `[ N PROBLEMS ]`, linking to the Alerts page, absent at
zero.

**Tests.** `dashboard/tests/test_alerts.py` (13, written in the closing
pass): `scan()` on a seeded db finds a tripped breaker, a fleet halt, a
silent machine and an unreachable feed; dedup per `(kind, subject)` and the
one recovery message; sink `none` logs rows and raises no
`weekly_send_failed`; a webhook POSTs `{subject, text}` through a stubbed
opener (never `urlopen`) and a failed POST becomes a finding;
`/api/v1/health` counts by severity; the weekly report carries the
checked-and-fine list; the smtp password appears in no page or payload.

### DASH-3 / DASH-4 (self-diagnosis half) - the two persisted brakes now reach the home page and the sink - FIXED in repo 2026-08-28, unshipped

**Symptom.** Wave 1 made the enforce blast-radius refusal and the mass
deactivation refusal durable (`db.record_enforce_refusal`,
`record_deactivation_refusal`) and rendered them as red banners in the fleet
page's `[ COLLECTOR ]` panel. That panel is read in context by somebody who is
already on the fleet page looking for it; a refusal that stands for a week on a
site nobody is watching was still a banner nobody saw, and every untick made
since sat unapplied.

**Cause.** The brake state lived in `meta` and was read by exactly one partial
and `/api/v1/health`.

**Fix.** `notices._check_collector_alarms` reads `db.collector_alarms()` every
cycle and writes `enforce_refusal` (error, subject "share removals": the count,
the limit, the folders, and the fix "check no computer was just renamed or
removed; if the removals are genuine, raise `DASH_ENFORCE_MAX_REMOVALS` and
redeploy, or untick fewer at a time") and `deactivation_refusal` (error,
subject "projects": "if the projects folder was unmounted, that is what this
means", clears by itself once it is), clearing each on the first clean pass.
The refusal's recorded `(folder, device)` pairs also become one
`share_without_plan` warn notice each ("this computer is still being sent a
project nobody ticked for it", up to 20). The same two brakes are alert kinds
in `alerts.ALERT_KINDS` (`enforce_refusal`, `deactivation_refusal`, and
`enforce_plan` for a held plan), each built by `_collector_alarm` from the same
`meta` record, so the sink hears about them within one alerts interval. The
wave 1 banners stay where they are.

**Tests.** None for the notice or alert halves; wave 1's
`test_enforce.py` / `test_api.py` still cover the brake and the banner.

### DASH-5 (self-diagnosis half) - a refused inventory walk and an unmounted tree now say so on the home page - FIXED in repo 2026-08-28, unshipped

**Symptom.** Wave 1's `db.replace_nas_media` brake keeps the previous
inventory and writes `nas_inventory_state.last_error` when a walk collapses to
nothing, and the finding asked for two more things: that refusal surfaced on
the page, and a boot/cycle canary that reads an empty `Projects/` as "not
mounted" rather than "empty". Until now the `last_error` was on the project
page only, and there was no canary at all.

**Cause.** Nothing read `nas_inventory_state.last_error` outside the project
view, and nothing anywhere asked whether `projects_dir` was there.

**Fix.** `notices._check_tree` (when `settings.projects_dir` is set) writes
`projects_dir_missing` (error, subject = the path) in three wordings: the
directory could not be read (with the OSError), it is not there, or it is
EMPTY - "which normally means the storage is not mounted rather than that the
projects are gone. Nothing has been marked as deleted." It returns before the
inventory check in every failing case and clears the notice when the tree is
back. `_check_inventory` then writes `inventory_refused` (error, one per
active project slug with a non-empty `last_error`, quoting it and pointing at
`[ MOVE ON THE SERVER AND ON EVERY MACHINE ]` for a rename), closing the ones
whose walk has succeeded since via `clear_notices_of_kind`. The alert twin is
`alerts._check_nas_tree` (`nas_tree`, error: "is not there at all" / "is there
but completely empty", and an unreadable path RAISES so it lands as
`check_failed` rather than passing).

**Tests.** None; wave 1's `test_db.py` coverage of `replace_nas_media` is
unchanged.

### DASH-10 (partial) - a quoted or space-padded secret was accepted silently; now it is named at boot - FIXED in repo 2026-08-28 (the notice half), unshipped

**Symptom.** The owner edits the NAS `.env` by hand and writes
`DASH_REPORT_TOKEN="abc..."` with the quotes, or pastes a token with a trailing
space. `check_boot_secrets` measures length only, so it passes the floor, and
then every companion's token mismatches: the whole fleet 401s on report with a
boot log that says the configuration is fine. It looks exactly like a wrong
password on every machine at once.

**Cause.** Secrets were stored unstripped and unquoted, and nothing compared
the value's shape against what a hand-edit produces.

**Fix.** `notices.check_settings()` runs once from `app.create_app` (when the
values were read, wrapped so it can never block boot) and writes
`insecure_secret` (error) when any of `report_token`, `session_secret`,
`syncthing_api_key` differs from its stripped self or is wrapped in matching
quotes - naming the KEYS only, never a value, because a notice is rendered on a
page and may be mailed by the sink - with the fix "edit those settings on the
server (no quotes, no trailing spaces) and restart the dashboard". The same
function writes `dev_insecure` (error) while `DASH_DEV_INSECURE` is set,
because that switch relaxes password, session and CSRF checks and is for tests
only. Both clear when the condition is gone at the next boot.

**Still open from the finding, not built here:** `settings.num()` still
returns the default silently on an unparseable value (so a mis-set
`DASH_ENFORCE_MAX_REMOVALS=10 ` still reads as 3 with no log line), secrets are
not stripped at load, and the incoming `x-ccsync-token` / `x-ccsync-identity`
headers are still compared unstripped.

**Tests.** None.

### DASH-11 - two live computers sharing one identity ping-ponged the registry every report, and nothing named it - FIXED in repo 2026-08-28 (detection), unshipped

**Symptom.** A studio clones a base rig's disk to a second box, so both carry
the same `~/.ccsync/machine.json` AND the same Syncthing config, and both
report every 30 s. `adopt_renamed_machine` refuses the rename (the name is
taken) and `release_device_id_elsewhere` moves the device id onto whichever
machine reported LAST, every report; the enforce cycle sees the device under a
different `(editor, machine)` each cycle, computes a different `desired`, and
`put_folder`s the affected folders every 60 s, so lane C never settles. The
only signal was one `log.warning` per report, and a duplicate `machine_id`
across two editors was not detected at all (`machine_by_machine_id` is per
editor).

**Cause.** The registry resolved collisions by last-writer-wins and had no
standing check that each identity appears on exactly one row.

**Fix.** `notices._check_identity_collisions` runs every cycle with two GROUP
BY queries over `machines`: `duplicate_machine_id` (error, subject = the
machine_id, body naming both `editor/machine` rows: "this happens when a
computer's disk was copied onto another one; sync plans, updates and halts for
either of them can land on the wrong machine", fix: quit CCSync on the newer
computer, delete `.ccsync/machine.json`, start it again) and
`duplicate_device_id` (error, subject = the Syncthing device id: "only one of
them can actually receive anything, and which one is not something this server
chooses", fix: reinstall or reset the Syncthing identity on the newer
computer). Both cross editors, both clear through `clear_notices_of_kind` once
the duplicate is gone, and both reach the sink through `notice_error`. This is
the finding's "persistent alarm on the fleet page" half; the "enforce freezes
that device's shares until an admin resolves it" half is NOT built - enforce
still follows the last writer.

**Tests.** None.

### SYS-3 (self-diagnosis half) - a report section this dashboard drops is now a notice and an alert, not only a grid chip - FIXED in repo 2026-08-28, unshipped

**Symptom.** Wave 1 made `ReportIn` `extra="allow"` and rendered
`[ N REPORT SECTIONS IGNORED: ... ]` on the fleet grid from
`db.record_ignored_report_sections`. It is the signal the finding asked for,
in one place, on one page, in a grid an owner reads for colours.

**Cause.** The record lived in `meta` and was published by
`build_editors_view` only.

**Fix.** `notices._check_collector_alarms` reads `db.ignored_report_sections()`
and writes `ignored_report_sections` (warn, subject "report fields", naming
the sections: "editors' computers are sending information this dashboard is
too old to store, so it is being thrown away; the companions are ahead of the
dashboard", fix: `[ UPDATE THE DASHBOARD ]` on Settings, Packages), clearing
it when the record is gone. `alerts._check_ignored_sections` is the alert
twin (`ignored_sections`, warn: "that is how three earlier faults stayed
invisible for weeks: the computer was saying what was wrong and nothing here
was listening", fix "this dashboard needs updating; send us this list"). Both
count the sections from the same `meta` record; neither measures anything new.

**Tests.** None for the notice or alert; wave 1's tests on
`record_ignored_report_sections` and the chip are unchanged.

### SYS-5 (self-diagnosis half) - low disk now reaches the home page and the sink - FIXED in repo 2026-08-28, unshipped

**Symptom.** Wave 2 put `[ DISK 4% ]` on the grid from v32's
`machine_state.disk_*` columns and `health.disk_status()`, and made the
companion park lane B below its floor. A drive filling on a Friday evening
still waited for somebody to open the grid.

**Cause.** The chip was the only reader of the figures.

**Fix.** Three alert kinds in `alerts.ALERT_KINDS`: `disk_low` (error) uses
THE CHIP'S OWN RED from `health.disk_status` rather than a second threshold, and
a machine that never reported a disk section gets nothing rather than a
reassuring green; `disk_park` (error) fires on `guard.blocked_reason ==
"disk_full"`, naming the free bytes; `data_disk` (error) is the dashboard's OWN
volume (`shutil.disk_usage` of the `db_path` parent), in percentages only
because `/data` on an appliance is a share of a pool nobody sized for this
container - `DATA_DISK_WARN_PERCENT` 10, `DATA_DISK_RED_PERCENT` 5, and an
unreadable volume raises into `check_failed`. On the notices side,
`notices._check_machine_space` writes `machine_disk_low` (warn, below
`MACHINE_DISK_FLOOR_BYTES` = 50 GB: "proxy downloads for one project are
typically 50 to 300 GB") and `machine_trash_oversize` (warn, above
`MACHINE_TRASH_FLOOR_BYTES` = 200 GB of `.ccsync-trash`, fix: the computer
clears it every 6 hours unless its brake is on, look for `[ RESUME ]`), and
`_check_dashboard_space` writes `dashboard_disk_low` (error, below
`DASHBOARD_DISK_FLOOR_BYTES` = 2 GB, or when the volume cannot be measured:
"that is not the same as knowing it is fine"). Note the notice's machine floor
(50 GB absolute, warn) is a third threshold beside `disk_status`'s two; the
alert side deliberately does not add one.

**Tests.** None for the alert or notice kinds; wave 2's `test_health.py` /
`test_report_ingest_health.py` cover `disk_status` and the chip.

### SYS-9 (partial) - a continuous invariant pass, read-only, naming rather than repairing - FIXED in repo 2026-08-28 (three of ten invariants), unshipped

**Symptom.** Every invariant in the system was enforced at the moment
something wrote and never re-verified: a tick written while Syncthing was
unreachable, a device approved under the wrong name, a cloned machine. Nothing
ever asked whether the cross-component facts still agreed.

**Cause.** `folder_tuning_drift` proved the pattern for one kind of fact and
nothing generalised it.

**Fix.** Not the finding's ninth collector kind with its own table: the
invariants that landed are notice checks inside `notices.run_checks` (every
cycle, on the existing `notices` table), which is the same "one row per
(invariant, subject), repair nothing, feed the weekly report" shape by way of
`notice_error`. Built: invariant 3 (every `machine_id` and every
`syncthing_device_id` on exactly one `machines` row -
`_check_identity_collisions`, DASH-11 above); the inverse of invariant 1 as
far as the brake already knows it (`share_without_plan`: a `(folder, device)`
pair the refused enforce pass wanted to remove, i.e. a computer still being
SENT a project nobody ticked for it - `_check_collector_alarms`); and two
registry facts of the same family, `pending_device_approval` (warn, a device
in Syncthing's pending list for over `PENDING_DEVICE_HOURS` = 24, named by its
`machines` row when one exists; `pending is None` means "could not ask" and
clears nothing) and `editor_without_machine` (info, a `known_editors` row older
than 30 days with no `machines` row: "usually somebody who was set up and has
not run the wizard yet"). `partials/notice_checks.html` lists every registered
kind as `[ FOUND ]`, `[ OK ]` or `[ NOT CHECKED ]` (see UX-10: OK needs
evidence). Invariant 1 proper landed in the closing pass:
`notices._check_plan_without_share` reads
`db.fetch_machine_selections(sync_modes=(FULL,))` against the collector's
`_folder_devices` snapshot (passed into `run_checks()`; `None` before the
config job has completed once, and the check stays silent rather than
guessing), excludes upload-only ticks and the unassigned bucket, and raises
`plan_without_share` (error) for a full tick whose project folder is not
shared with that machine's device id - the inverse of `share_without_plan`
(the first build's comment called that "SYS-9 invariant 3"; invariant 3 is
device-id uniqueness, which `machine_id_collision` covers). NOT built:
invariants 2 and 4 to 10 - wave 5, item 40.

**Tests.** `test_notices.py`: the five `plan_without_share` cases and the
evidence mechanism (above).

### SYNC-17 (self-diagnosis half) - an 18-hour dead sync engine would now be mailed inside an hour - FIXED in repo 2026-08-28, unshipped

**Symptom.** The original entry (2026-08-18): an editor's Syncthing died with
the Windows session at 00:53 and stayed dead until the owner looked, eighteen
hours later, with lane C green and 12 GB unsynced. The supervisor
(companion 0.9.x) now restarts it and wave 1 stored the supervisor's section in
v30's `supervisor_down_since` / `supervisor_attempts` / `supervisor_last_error`
and chipped it on the grid. A machine whose engine genuinely cannot start,
or that is switched off, or whose companion is being refused, still waited
for a page view.

**Cause.** Every one of those states was a grid colour and nothing else.

**Fix.** Four alert kinds cover the shape, each reading a column that already
existed: `engine_down` (error, `supervisor_down_since` older than
`ENGINE_DOWN_SECONDS` = 1 h, with the failed restart attempts and last error in
`detail`; fix "quit and restart CC Sync from the tray, then send diagnostics"),
`nas_engine_down` (error, `collector_health.syncthing_reachable is False`, the
server's own engine), `machine_silent` (error, no report for `SILENT_SECONDS`
= 24 h - deliberately far above the grid's 6 h red, because waking somebody by
mail wants a threshold no laptop lid closed over lunch can reach; the last
known lane states ride in `detail`), and `red_unexplained` (error, red for
`RED_UNEXPLAINED_SECONDS` = 1 h and nothing more specific to say, fix
`[ ASK WHY ]`). `report_refused` (error) separates "this server is turning it
away" from "switched off". On the notices side `syncthing_unreachable` (error)
is the server-engine twin. With `alerts_sink` set, the eighteen hours become
one alerts interval past the hour, re-sent daily while true, and a recovery
message when the engine is back.

**Tests.** None for the alert kinds; the supervisor's own suite in
`companion/tests/` and wave 1's flattening tests are unchanged.


### UX-8 / C-2 - HALT ALL SYNCING was one click, had no expiry, and the JSON route needed no reason - FIXED in repo 2026-08-28, unshipped

**Symptom.** The owner halts the fleet on a Friday because something looked
wrong, goes home, and forgets: every computer in the company stops syncing
until somebody remembers, with no reminder, no expiry, and no record of who
stopped the fleet last month or why. Or the wrong red button on the Users
page is clicked, and the fleet stops with nothing asked. And while the Users
panel refused a halt with a blank reason, `POST /api/v1/fleet/halt` did not,
so a script or a curl could stop every companion with an empty sentence in
every editor's tray.

**Cause.** `db.set_fleet_halt` wrote one `meta` blob (`fleet_halt`:
`active`, `reason`, `set_by`, `set_at`) with no `expires_at` and no history;
the halt was visible only on the one admin panel that set it;
`fleet_halt.html`'s HALT button had no `hx-confirm`; and `FleetHaltIn.reason`
was `Field(default="")` while `ui.partial_admin_set_fleet_halt` was the only
door that checked it.

**Fix.** A halt now carries `expires_at` (`db.set_fleet_halt(..., hours=,
extend=)`, `db.FLEET_HALT_DEFAULT_HOURS = 24`, db.py:5501) and
`db.get_fleet_halt` applies it through `_halt_state` (db.py:5441): an expired
halt reads as `active: False` with `expired: True`, which is what makes the
release automatic with NO companion change, because the report reply
(`api.py:7132`) always carries `commands.halt.active` and a companion treats
false as "start again". An unparseable `expires_at` is NOT treated as
expired. `[ KEEP HALTED ]` (`fleet_halt.html`, form field `extend=1`) is the
same POST with the ORIGINAL reason, setter and start time kept and only the
expiry moved by another 24 h, counting `extended`, so the banner still says
how long the fleet has actually been stopped rather than how long since the
last click. Every halt, extend and release is appended to
`meta.fleet_halt_history` (`db._append_halt_history`, last 20, `{at, action:
halt|extend|release, by, reason, expires_at}`) and rendered as a PREVIOUS
HALTS table under the switch (`db.fleet_halt_history`, `ui._fleet_halt_render`
ui.py:2116). The standing banner is `partials/fleet_halt_banner.html`, served
by `GET /partials/fleet-halt-banner` (`ui.partial_fleet_halt_banner`,
ui.py:2105, any signed-in user: an editor whose sync has stopped is exactly
who needs to read it) and loaded from `base.html` on EVERY page
(`hx-trigger="load, every 60s"`, its own trigger so a slow read never holds
up a page); it counts hours since `set_at` and computers in the `machines`
registry (`ui._halt_banner_context`, the registry rather than the machines
reporting now, because a halt reaches a switched-off machine on its next
report), says when it releases itself, and after an expiry shows "THE FLEET
HALT HAS EXPIRED and syncing has started again everywhere" so the person
who stopped it is told. `FleetHaltIn` (api.py:4193) gained `hours`
(`gt=0, le=720`) and `extend`; `api_set_fleet_halt` (api.py:4232) refuses a
HALT whose stripped reason is under 3 characters with a 422 ("say why: the
reason is shown in every editor's tray (at least 3 characters)"). The check
is in the route rather than `min_length` on the field, deliberately: a
RELEASE needs no reason. The Users panel applies the same 3-character rule
(`ui.partial_admin_set_fleet_halt`, ui.py:2134, previously "not empty").
C-2 is the `hx-confirm` on HALT ALL SYNCING, exact UX.md copy: "Stop syncing
on EVERY computer in the fleet? Uploads, proxy downloads and shared project
files stop everywhere until you start them again here. Nothing is deleted.
Work done while the halt is on will not reach anyone until you release it."
[ KEEP HALTED ] has its own: "Keep every computer in the fleet halted for
another day? Nobody's uploads, proxy downloads or shared project files move
until you start them again here."

**Seams.** `hours` is reachable from the JSON route only; the panel always
takes the 24 h default. The JSON route 422s `extend: true` with a blank
reason while the panel's [ KEEP HALTED ] sends no reason and relies on the
carry-over, so the two doors disagree on that one input (known, harmless: the
JSON caller is a script that can type a reason). The third seam was closed
in the closing pass: `extend` against a halt that had ALREADY expired between
the panel's render and the click used to start a FRESH halt with the form's
blank reason; `db.set_fleet_halt` now raises `ValueError("The halt already
ended at {time}. Start a new one with a reason.")`, which the JSON route
turns into a 422 and the panel into its error banner.

**Tests.** `dashboard/tests/test_fleet_halt.py` (closing pass): the 24 h
default, a custom `hours`, an expired halt read as released by the report
`commands` block, the fleet grid and the standing banner (clock moved with
`monkeypatch.setattr(dbmod, "utcnow_iso", ...)`), [ KEEP HALTED ] extending
and carrying the reason, the short-reason 422 against a reason-free
release, `halt_history` recorded and rendered, the banner on a non-fleet
page, the expired-extend refusal through the panel and at the db layer, and
the C-2 copy pinned verbatim. The four pre-existing halt bodies changed from
`"x"` to `"checking the pool"` because a one-character reason is now refused.

### UX-9 / C-3 / C-4 / C-5 - the release controls were the least guarded and the most fleet-wide - FIXED in repo 2026-08-28, unshipped

**Symptom.** Three fleet-wide actions on Settings, Packages with nothing
between the admin and the fleet. (1) The feed policy `<select>` submitted its
own form on `change`, so tabbing into it and pressing Down armed
`current` - auto-publish AND make current, i.e. unattended fleet-wide
upgrades from the vendor feed - with no confirmation and nothing to undo.
(2) `[ MAKE CURRENT ]` on an UNSIGNED dev build went through: every
companion verifies the record signature (`release_trust`) and refuses the
offer, so the whole fleet silently stopped updating, and the only signal
anywhere was an `[ UNSIGNED ]` chip on that page. (3) `[ DELETE ]` unlinked
the bytes a rollback to that version needs, with no confirm, and its `OSError`
was swallowed (`except OSError: pass`), so a read-only or full volume dropped
the ROW and kept the FILE: the one combination that leaves a package both
unrecoverable through the dashboard and invisible on it.

**Cause.** `admin_packages.html`: `onchange="this.form.requestSubmit()"` on
the policy select, no `hx-confirm` on MAKE CURRENT or DELETE;
`api.make_current_refusal` (the one gate all three make-current doors share
since REL-1) had no signature check; `ui.partial_admin_package_delete` called
`Path.unlink(missing_ok=True)` inside a swallowed `try`.

**Fix.** (1) The select is now `data-previous="{{ feed.policy }}"` with no
inline handler; `dashboard/static/confirms.js` (new, loaded by
`templates/admin_packages.html`) owns a DELEGATED `change` listener on
`document` (the panel is swapped in by htmx every 30 s, so a listener on the
element itself would survive exactly one poll): choosing `current` asks C-3
with the exact UX.md copy ("Publish new builds automatically AND make them
current? Every editor's machine will take each new build from the vendor
feed without anyone approving it first. Choose 'stage' if you want to test a
build before the fleet gets it."), a cancel puts the select back to
`data-previous` so it never shows a policy that is not in force, and any
other choice submits as before. (2) `api.make_current_refusal` (api.py:5108)
refuses a row with no `signature` with a 409 naming the consequence, unless
`force` AND `confirm` equals the version typed - the SAME typed override the
soak gate uses, one mechanism rather than two, and placed after the recall
and `requires_dashboard` checks (facts about the build no confirmation
overrides) and before the `ever_current` rollback exemption. All three doors
inherit it: `api_set_current_package` (`?force=1&confirm=<version>`),
`ui.partial_admin_package_current` (form fields `force`/`confirm`,
ui.py:2345) and the roll-back button. `partials/admin_packages.html` shows
the typed-override form (`[ MAKE CURRENT ANYWAY ]` with the "type X" box)
whenever `not p.signature`, not only when the soak fails, and that form
carries C-4 as `hx-confirm`, exact UX.md copy: "This build has no release
signature. Companions verify signatures, so making it current stops EVERY
machine in the fleet from updating, silently. Republish it through
tools\ship.cmd instead. Make it current anyway?" The plain `[ MAKE CURRENT ]`
button on an unsigned row has no dialog; it 409s server-side with the same
sentence plus "To make it current anyway, type the version number (X) into
the confirmation box." (3) `[ DELETE ]` carries C-5 (`hx-confirm`, UX.md copy
with `{{ p.kind }}` where UX.md wrote the literal "companion": "Delete
{kind} {version} for {platform}? These are the bytes a rollback to that
version needs. Once it is gone you cannot put the fleet back on it without
rebuilding and republishing."), and `ui._trash_package_file` (ui.py:2606)
MOVES the file to `<data>/packages/.trash/<platform>/<utc-stamp>-<filename>`
instead of unlinking it; `ui._prune_package_trash` (ui.py:2631) then drops
trashed files older than `PACKAGE_TRASH_DAYS = 30` by mtime, best-effort (a
prune that cannot read the directory never fails the delete that triggered
it). A source file that is ALREADY gone is not an error (the row is what is
being deleted); a source that cannot be moved IS: the `OSError` is rendered
as the panel's error ("could not move X to the trash folder (...). Nothing
was deleted: the package row is still here and so are its bytes.") and the
row is kept. The audit row (`package.delete`) records where the bytes went
(`trashed`).

**Closing-pass fix.** The first build trashed only from the htmx partial;
the JSON twin `DELETE /api/v1/admin/packages/{platform}/{version}` still ran
the old `unlink(missing_ok=True)` inside a bare `except OSError: pass`, so a
script could throw away the rollback bytes the button protects. The helpers
(`PACKAGE_TRASH_DAYS`, `_trash_package_file`, `_prune_package_trash`) moved
from `ui.py` to `api.py` (ui re-imports them: one mechanism), and the JSON
route moves the bytes FIRST, refuses with a 500 naming the file when the
move fails (row kept), and answers `trashed_to`.

**Tests.** `dashboard/tests/test_packages.py` (closing pass): the unsigned
`MAKE CURRENT` 409 asserted against `api.make_current_refusal`'s own return,
`force` + the typed version succeeding, a wrong typed version still refused,
the htmx twin's parity, delete moving the bytes into `.trash` (asserted on
disk, both routes), the prune keeping only entries younger than
`PACKAGE_TRASH_DAYS`, an `OSError` on the move surfacing in the partial with
the row and file intact, feed policy `current` still accepted by the JSON
route, and the C-3 / C-4 / C-5 copy pinned. `test_release_channel.py`'s soak
gate and `test_settings_hub.py`'s admin-gate table still pass.

### UX-22 / C-8 / C-9 - revoking a token or a session was unconfirmed, unrecoverable, and could be your own - FIXED in repo 2026-08-28, unshipped

**Symptom.** One click on `[ REVOKE ]` (Users, report tokens) revoked a
per-editor `cce1.` token that is displayed exactly once and cannot be
re-shown, taking that editor's companion off the fleet - no reports, no sync
- until somebody issues a new one and the editor types it in. And
`[ REVOKE ALL ]` on the sessions table read identically on every row,
including the one marked `(you)`, so the admin fixing things could log
themselves out of the browser they were fixing them from.

**Cause.** No `hx-confirm` on either button
(`partials/admin_report_tokens.html`, `partials/admin_sessions.html`), and
the own-session row differed from the others only by the `(you)` marker.

**Fix.** C-8 on the token `[ REVOKE ]`, exact UX.md copy: "Revoke
{{ t.editor_username }}'s report token? Their companion stops reporting and
stops syncing until you issue a new token and they enter it. The old token
cannot be shown again." On the sessions table the button on the admin's own
row (`s.username == session_user`) is now labelled
`[ SIGN ME OUT EVERYWHERE ]` with C-9, exact UX.md copy: "Sign yourself out
of every browser, including this one? You will need to log in again to
finish what you are doing." Every OTHER row keeps `[ REVOKE ALL ]` and gained
a confirm UX.md did not specify: "Sign {{ s.username }} out of every browser?
They will need to log in again. Their computer's own sync is not affected."
(the last sentence because an admin has, more than once, taken "revoke" to
mean the companion). The finding's fourth site, the topbar's
`[ LOGOUT ALL ]`, got its confirm in the closing pass: that form is a plain
`method="post"` (it is injected by `innerHTML` into the b-roll, music and
ytdl SPAs, where `hx-confirm` cannot reach it), so it carries an
`onsubmit="return window.confirm(...)"` with the C-9 copy.

**Tests.** `dashboard/tests/test_sessions.py` (closing pass): the own-row
`[ SIGN ME OUT EVERYWHERE ]` against the other-row `[ REVOKE ALL ]` and
their distinct confirm copy, the topbar's `window.confirm` mechanism, and a
`/logout-everywhere` round trip; `test_report_tokens.py` pins the C-8 copy;
`test_no_em_dash.py` scans both templates.

### UX-12 / DASH-8 (partial render) - a tick with no machine means every computer that person owns, and the button did not say so - FIXED in repo 2026-08-28, unshipped

**Symptom.** The owner ticks a 900 GB project "for leso", meaning his
desktop; leso also owns a MacBook, and both computers start pulling it. The
button read `[ TICK FOR LESO ]`; the only place the fan-out was stated was a
`title` attribute on the sidebar checkbox.

**Cause.** `project_detail.html` rendered one person-level button whatever
the person owned, and the project-detail PARTIAL (`ui.partial_project`, the
fragment htmx swaps in after every toggle) did not carry the person's
machines at all, so the wave-1 DASH-8 untick confirm ("This removes X from
leso's N computers (...)") and any per-machine control could only have been
right on the first full-page render.

**Fix.** `ui.partial_project` (ui.py:1379) now passes
`toggle_editor_machines = db.machines_of(conn, tick_editor)` like the full
page does (ui.py:932, 1005), so the fragment carries the same confirm and the
same label. `partials/project_detail.html`: when the person is not yet
ticked and owns more than one computer the button reads
`[ TICK FOR ALL OF LESO'S COMPUTERS (2) ]` (`[ TICK FOR ALL OF MY COMPUTERS
(N) ]` for the signed-in editor), and beneath it "or one computer at a time:"
with one `[ <MACHINE> ]` button per computer posting the existing
`/partials/selection/{editor}/{slug}/toggle?...&machine=<name>` so "his
desktop, not his laptop" is one click rather than a trip to Settings,
Assignments. The person-level UNTICK label is unchanged: the wave-1 DASH-8
confirm already names every computer it will affect. The finding proposed
REPLACING the single button with the list; what was built keeps both, since
"every computer" is still the common case. The sidebar checkbox still states
the fan-out only in its `title`.

**Tests.** `dashboard/tests/test_fleet_audit.py` and `test_multi_machine.py`
(the person-level toggle and its confirm) pass; the new label and the
per-machine buttons are not pinned beyond the em-dash scan.

### UX-20 - [ RESUME ] on the fleet grid reported success for a machine it did not find - FIXED in repo 2026-08-28, unshipped

**Symptom.** An admin clicks `[ RESUME ]` (lane B breaker, CR-45) from a
fleet page left open across a machine rename or a `[ FORGET ]`. The grid
re-rendered looking fine, no resume was queued, and that editor's proxy
download stayed parked until somebody noticed. The JSON twin
(`api.py`'s resume route) was not affected.

**Cause.** `db.request_lane_b_resume` returns False for an unknown
editor/machine and `ui.partial_admin_resume_lane_b` discarded the return
value.

**Fix.** `ui.partial_admin_resume_lane_b` (ui.py:2473) keeps the result and
renders the grid with `error` set when nothing was queued; `partials/fleet_grid.html`
shows it as a banner above the grid: "That computer is no longer in the
fleet, so nothing was resumed. Reload the page." The finding's "same for
`partial_admin_machine_update`" was already handled there (it renders "no
machine ... for ..." on the same shape, ui.py:2460). The same lesson is
cited by wave 4's `db.dismiss_notice`, which returns None for a notice id
that names nothing open rather than reporting a silent success.

**Tests.** `dashboard/tests/test_multi_machine.py` (closing pass): the
`[ RESUME ]` reply for a machine no longer in the fleet, and
`partial_admin_machine_update`'s "no machine X for Y".

### UX-21 - site.toml IMPORT was a bulk overwrite with no confirmation and no history - FIXED in repo 2026-08-28, unshipped

**Symptom.** Pasting an older or another site's config into Settings and
clicking `[ IMPORT ]` overwrote every recognised key and reloaded the page.
`canonical_prefix`, `remote_root` and `tree_name` are among them, and both
installers and every companion read them. `[ EXPORT site.toml ]` existed, but
only helped if the operator thought to click it first. There was no history
and no way back.

**Cause.** `setup_routes.py`'s import applied the pasted values directly;
nothing snapshotted what they replaced, and the page had no way to show what
was about to change.

**Fix.** Two passes. The first built the ledger: `db.record_site_change(conn,
actor, action, before, after)` snapshots exactly the keys a write is about
to replace (never the whole config, so an undo restores what THAT write
changed and resurrects nothing that has moved on since) into
`meta.site_history` (`db.SITE_HISTORY_KEY`, newest first,
`db.SITE_HISTORY_KEEP = 10`), and `db.site_history` reads it without raising.
The closing pass gave it callers. `site_store.py`: `TREE_KEYS =
("canonical_prefix", "tree_name", "remote_root")`, `set_many` split into a
reusable `validate_many` + write, `diff_against_current` (before/after
against the stored-or-fallback values) and `mask_changes` (masks any key
whose name looks secret-shaped - none of `KEYS` does today; the guard is
there for the day one is added). `setup_routes.py`: `POST
/api/v1/admin/site/import?dry_run=1` validates and diffs, writes nothing and
answers `{changes, count}`; the real import snapshots (action `import`)
before writing and skips the snapshot when nothing changed; `PUT
/api/v1/admin/site` snapshots the previous value of any of the three tree
keys being changed (action `save`); `GET /api/v1/admin/site/history` lists
`{at, actor, action, count}` and deliberately never the values; `POST
/api/v1/admin/site/undo-last-change` re-applies the newest entry's `before`
through the same `validate_many` / `set_many` path (so every side effect an
import has, an undo has), records the undo as its own entry (action `undo`,
so undo-of-undo works), 404s "no site setting change is recorded to undo" on
an empty history and 422s like a save would if a restored value no longer
validates. `static/site_settings.js`: `runImport()` calls the dry run first;
zero changes shows "Nothing in that text differs from the current settings.
Nothing was changed." and stops; otherwise the confirm is built from the
diff: "This will change {n} settings, including {key} from {from} to {to},
..., and {k} more. Apply it?" (first three named). `admin_settings.html`
gained a `[ CHANGE HISTORY ]` panel with the last five entries and `[ UNDO
LAST IMPORT ]` ("Put back the {n} settings changed by {actor} at {at}?"),
hidden when the history is empty. All four routes sit behind
`_require_admin` like the routes beside them.

**Tests.** `dashboard/tests/test_site_history.py` (19): dry-run diff and
no-write, zero-diff reporting, import records history, the save-path
tree-key snapshot (including no half-taken snapshot on a validation refusal
and no entry when the value did not change), undo restores and records
(and undo-of-undo), the readable 404 on an empty history, undo running
through the same validation as apply (422 on a since-invalid stored value),
the history listing never exposing values, and secret masking through a
monkeypatched secret-shaped key.


### DASH-1 - the server-side move renamed first and recorded second, and a proxy that could not follow 503'd as "nothing moved" - FIXED in repo 2026-08-28, unshipped

**Symptom.** An admin presses `[ MOVE ON THE SERVER AND ON EVERY MACHINE ]`
on a mis-filed card dump. The original renames fine; then one proxy under
`Proxy/` is held open by a Resolve on a wired rig, or the destination
`Proxy/` directory cannot be created, and the page says "the server could not
move it" with a 503. The original is already at the new path, some proxies
with it, and there is no `file_moves` row anywhere - so no machine is ever
told, every machine still holding the file re-uploads it to the OLD path
(lane A never deletes), and the editors' Resolve projects now point at a
server file that is no longer where they say. The same shape with no proxy
involved at all: a container restart or a full `/data` between `src.rename`
and the `conn.commit()` that followed it. The exact failure the feature was
built the day before to end, with the original also gone.

**Cause.** `api.move_project_files` renamed and only THEN wrote the record,
and its one `try` wrapped `mkdir`, `src.rename` AND `_move_proxy_siblings`,
so an `OSError` from the proxy loop took the "nothing moved, safe outcome"
branch that was only true of the rename. Nothing anywhere could tell a move
that had happened from one that had not.

**Fix.** Two-phase. `db.record_file_move` now takes `state=` and the route
writes the row `pending` and COMMITS it before `dest.parent.mkdir` and
`src.rename` (api.py:2438); a rename that raises deletes its own reservation
(both tables), audits `file.move.refused` and still 503s, so a 503 once
again means nothing moved. `_move_proxy_siblings` returns `(moved, failed)`
and runs OUTSIDE the fatal try: the row is flipped by `db.complete_file_move`
to `done`, or to `partial` with `state_detail` naming every proxy that
stayed, and `api_move_project_files` answers 207 with `state: "partial"` and
`proxies_failed` rather than a 503 claiming nothing happened. The project
page says `[ MOVED, SOME PROXIES STAYED ]` on the result and
`[ SOME PROXIES STAYED ]` on the log row. `db.pending_file_moves` offers a
`pending` row to nobody. The crash window is closed by
`api.reconcile_file_moves`, run at boot (app.py:516, before anything else
reads the tree) and at the top of every `Collector.run_cycle`
(collector.py:313), never raising: for every `db.unfinished_file_moves` row it
stats both ends - destination only means the rename happened, so the row is
completed ("completed after an interrupted move") and fans out on the next
reports; source only means it did not, so the rows are dropped; both or
neither is QUARANTINED into the `meta` key `file_move_quarantine`
(`api.FILE_MOVE_ALARM_KEY`, read by `api.file_move_alarms`) with the row left
`pending`, offered to no machine, and the page shows a red
`[ UNFINISHED ON THE SERVER ]` chip with "Check both paths on the NAS; the
dashboard re-checks them every cycle". Schema v36 adds `file_moves.state`
(default `done`, so every row from 0.7.14 reads as completed), `state_detail`,
`undo_of` and `undone_by`.

**Tests.** `dashboard/tests/test_file_moves.py`:
`test_the_record_is_written_and_committed_before_the_rename` (a second
connection sees the `pending` row while `Path.rename` runs, and a failed
rename leaves no row and no target),
`test_a_proxy_that_could_not_follow_is_named_and_never_read_as_nothing_happened`
(207, `partial`, the proxy named, the original moved),
`test_an_interrupted_move_is_completed_or_quarantined_on_the_next_pass`
(destination-only completes and fans out; both-present quarantines, is
offered to nobody and chips the page). Ships as: dashboard OTA (v36).

### RES-1 - a move Resolve blocked was refused for ever, and the file re-uploaded itself a day later - FIXED in repo 2026-08-28, unshipped

**Symptom.** The admin moves a clip; on the editor's machine that clip (or
its proxy) is open in Resolve, which holds media without share-delete, so
`src.replace(dest)` raises `PermissionError`. The tray says the copy could
not follow. The editor closes Resolve an hour later and nothing happens: the
project page shows that computer `FAILED` for ever. Twenty-four hours after
the command arrived the lane A exclusion for the old path lapses, the next
pass uploads the local copy back to the path the admin cleared, and the move
is undone on the server by the machine that was told to follow it.

**Cause.** `apply_move` returned `(False, ...)`, `app._apply_file_moves`
called `self.file_moves.record(move, ok=False)` unconditionally, and every
later report found `entry(move_id)` non-None and re-answered the old failure:
a failure was final. `FileMoveLedger.recent_excludes` was bounded by
`EXCLUDE_WINDOW_SECONDS` (24 h) whether or not the copy was still at the old
path.

**Fix.** A failure is a schedule, not a verdict. `FileMoveLedger.record_attempt_failed`
(file_moves.py) writes the entry `retryable` with `attempts`,
`first_attempt_at` and `next_attempt_at` - `RETRY_FIRST_SECONDS` (10 min)
after the first failure, `RETRY_INTERVAL_SECONDS` (1 h) after each later
one - and flips it to `blocked` at `RETRY_MAX_ATTEMPTS` (20, which is about
18 hours of uninterrupted retrying) or `RETRY_MAX_SECONDS` (7 days, the
ceiling that matters when the machine is offline between attempts).
`retry_due` is measured on the wall clock; a stamp-less entry from an older
build is due. `recent_excludes` keeps the old path out of lane A for as long
as an entry is `retryable` or `blocked`, regardless of age: the copy is still
there, which is why the move failed. `app._apply_file_moves` (app.py:6142)
re-answers a not-yet-due entry as `state="retrying"` with its attempt count
WITHOUT re-attempting, runs `apply_move` again when due, and answers
`retrying` or `blocked` after a fresh failure; the editor gets one toast on
the first failure ("Nothing was deleted and CCSync will keep trying") and one
when it gives up ("after a week of trying ... ask your admin"), never one an
hour. On the wire, `file_moves_applied` entries carry `state`, `attempts` and
`relink_pending` (`_queue_file_move_answer`); `FileMoveResultIn`
(api.py:6556) accepts `state: "done"|"failed"|"retrying"|"blocked"`,
`attempts` and `relink_pending`, and `db.mark_file_move_applied` treats
`retrying` as an update of `state`/`attempts`/`last_error`/`detail` that does
NOT stamp `applied_at`, so `db.pending_file_moves` keeps sending the command
and the project page says "still trying here (N attempts)"; `blocked` stamps
`applied_at` with `ok=0` and `state='blocked'`, chips `[ N BLOCKED ]` and
"BLOCKED here after N attempts", and makes the move un-undoable (UX-11). A
companion that sends no `state` (0.9.54) keeps its original meaning: a
failure is an answer. Note the two vocabularies: the ledger's state is
`retryable`, the wire's and the dashboard's is `retrying`.

**Deploy order, and why it is load-bearing here.** The retry is driven by
REDELIVERY: the companion only re-attempts a move when the command rides the
next report reply. A pre-v36 dashboard drops the unknown `state` field
(`extra="ignore"` at HEAD too), reads a `retrying` answer as `ok=false`,
stamps `applied_at` and never sends the command again - the old latch, moved
to the server. Deploy the dashboard before the companion. (The comment on
`FileMoveResultIn` names 0.9.56 as the first companion sending `state`; the
build that does is 0.9.55.)

**Tests.** `companion/tests/test_file_moves.py`:
`test_an_unapplied_move_holds_its_exclusion_open` (ten windows later the old
path is still excluded), `test_a_failure_is_retried_on_a_schedule_and_then_blocked`
(not due, due at 10 min, due hourly, blocked at 20 with `next_attempt_at`
None and the exclusion still held), `test_the_week_long_ceiling_also_gives_up`,
`test_a_blocked_move_is_retried_until_it_works_then_answered_as_blocked` (the
app re-answers without re-attempting, moves the moment the obstruction goes,
and answers `blocked` with a toast when it never does),
`test_the_answers_ride_the_report`. `dashboard/tests/test_file_moves.py`:
`test_a_retrying_machine_keeps_the_command_and_shows_its_attempts` (a
`retrying` answer leaves `applied_at` NULL, records attempts and last_error,
and the command is in the same reply), `test_undo_is_refused_while_a_computer_could_not_follow`
(`blocked` retires it and chips `[ 1 BLOCKED ]`). Ships as: dashboard OTA
(v36) first, then companion 0.9.55.

### UX-5 / DASH-9 - an undelivered move expired after seven days, and an expired one was silent - FIXED in repo 2026-08-28, unshipped

**Symptom.** The owner moves a mis-filed card dump on Monday. One editor is
on a two-week shoot with the laptop closed. Day 15, the laptop comes back:
the command has aged out of `pending_file_moves`, so that machine is never
told; its copy still sits at the old path and was never excluded from lane A
(the exclusion starts when a machine HEARS); the next pass uploads it
straight back to the path the admin cleared. The project page shows that
computer as `[ WAITING FOR 1 ]` for ever, and nothing anywhere says a move
was never completed. Same silence for a machine that heard the command,
answered `ok: false` once, and aged past the cutoff.

**Cause.** `db.pending_file_moves` filtered on `m.requested_at >= cutoff`
(`FILE_MOVE_MAX_AGE_DAYS = 7`) - age, not delivery. The docstring's reason
("must not shuffle files shuffled again since") was already covered by the
companion refusing a move whose source is not where the command says. A
target with `applied_at IS NULL` was kept for ever and read by nobody.

**Fix.** Bounded by DELIVERY, not age. `db.pending_file_moves` has no age
cutoff any more (`max_age_days` stays in the signature and is discarded); it
offers every target with `applied_at IS NULL AND expired_at IS NULL` on a
`done`/`partial` move, oldest first, still capped at
`FILE_MOVE_COMMAND_LIMIT`. What ages out is a command that WAS delivered and
never answered: `db.expire_delivered_file_moves` stamps `expired_at` (v36) on
targets with `delivered_at` older than seven days, leaves undelivered ones
untouched, and runs inside `api.reconcile_file_moves` (boot and every
collector cycle) with a WARNING naming the machine. An expired target is loud:
the project page grows a `MOVES AWAITING MACHINES` panel
(`db.file_moves_awaiting_machines`, `waiting_days` measured from the delivery
when there was one and the request otherwise, so a machine not yet told is
not late) with `[ WAITING ]` under two days, `[ WAITING N DAYS ]` amber after,
`[ NOT APPLIED - THIS COMPUTER MAY RE-UPLOAD THE OLD PATH ]` red once expired,
the retry count and last error beside it, and `[ ASK THAT COMPUTER AGAIN ]`
on each expired row: `db.reissue_file_move` clears `expired_at`, `delivered_at`
and `state` so the age clock restarts from the next report, audits
`file.move.reissue`, and is reachable as
`POST /api/v1/projects/{slug}/moves/{id}/reissue?editor=&machine=` (409 once
that computer has answered) and the partial behind the button. The log row
chips `[ N NOT APPLIED ]`, and `GET /api/v1/projects/{slug}/moves` carries
`awaiting`. Not built from DASH-9's proposal: a fleet-level banner naming the
machine; the panel lives on the project page.

**Tests.** `dashboard/tests/test_file_moves.py::test_an_undelivered_move_never_expires_but_a_delivered_one_does`:
two machines, one hears the move and one is away; three weeks on, the one
that was told is expired and no longer offered, the one that never was still
gets the command, the page carries both chips, and the re-issue puts it back
in the first machine's next reply. Ships as: dashboard OTA (v36). No
companion change.

### UX-11 / C-6 - the MOVE confirmation named neither the file nor the destination, and there was no undo - FIXED in repo 2026-08-28, unshipped

**Symptom.** The owner pastes a path with a typo into the free-text box, or
leaves the destination select on the project he was looking at a minute ago.
The confirm reads "Move it on the server now, and tell every computer that
holds it to move its copy and relink Resolve?" whatever "it" and wherever
"there" is, and the move rewrites the server tree and fans out to every
holding machine. The `file_moves` row is a good journal and nothing reads it
backwards: putting the file back means typing the inverse move by hand, and
getting the machine list right a second time.

**Cause.** `project_detail.html` used one static `hx-confirm` string, and
there was no reverse endpoint. A directory move - privileged and recursive -
took no snapshot, against the repo's own rule.

**Fix.** The confirm is built from the form (`hx-on::confirm` in
`project_detail.html`, `htmx:confirm` because `hx-confirm` is static): "Move
'<path>' from <project> to <project>/<folder> on the server, and tell N
computers to move their copy and relink Resolve? Proxies move with it. You can
put it back with UNDO while every computer has either applied it or is still
waiting for it." An empty path goes through to the server's own "is
required" banner rather than a silent no-op. C-6's last sentence ("There is
no undo button") was written before the undo existed and is replaced by the
one above; N is `project.editors | length` (the page's editor/device list),
an approximation of the `(editor, machine)` set the route actually computes.
The undo is `api.undo_file_move`, `POST /api/v1/projects/{slug}/moves/{id}/undo`
and the partial behind `[ UNDO THIS MOVE ]`: it issues the INVERSE move
through `move_project_files` itself (`path=to_rel`, `to_slug=from_slug`,
`to_path=` the original's parent folder, `undo_of=<id>`), so it is a
`file_moves` row like any other with the same rename, the same two-phase
record and the same per-machine commands; `db.add_file_move_targets` then
adds every computer the ORIGINAL reached, because the inverse's source
project may be one they do not sync and they are the ones with a copy to put
back; `db.mark_file_move_undone` stamps the original `undone`/`undone_by`
(`[ PUT BACK ]` on the page, "putting move N back" on the new row); and
`db.audit(... "file.move.undo")` records both ids and both ends. `undoable`
(`db._hydrate_file_move`) is true only while the move is `done`/`partial`,
not already undone, and no target has FAILED or is BLOCKED - that machine
still has its copy at the old path, and moving the server copy back under it
would make a third state; the refusal is a 409 saying so, and a second undo
is a 409 "already been put back". For a DIRECTORY undo,
`dashboard_update.snapshot_before(settings, "file-move-undo-<id>")` runs
first, best-effort (TrueNAS only, a failure is a WARNING, never a lost
button). The FORWARD directory move still takes no snapshot: UX-11 asked for
one on the move, and what was built is one on the undo.

**Tests.** `dashboard/tests/test_file_moves.py::test_a_move_can_be_put_back`
(the file and its proxy are back, the original is `undone` with `undone_by`,
`file.move.undo` is in `fleet_audit`, a second undo is 409, and the inverse
rides the machine's next reply) and
`test_undo_is_refused_while_a_computer_could_not_follow`. The snapshot call
is not pinned by a test. Ships as: dashboard OTA (v36). No companion change.

### RES-10 - `_relink_moved` only fixed the project that happened to be open - FIXED in repo 2026-08-28, unshipped

**Symptom.** The admin moves footage belonging to project B while the editor
has project A open, or Resolve closed. The copy moves on disk, the companion
answers "moved; Resolve not relinked (not open)", the ledger calls it done and
it is never looked at again. Days later the editor opens B and the clip is
offline. Its path is still in-tree, so the watcher classified it `MISSING`,
wrote a DEBUG line, and did nothing: no popup, no toast, no dashboard signal,
for a file whose new location the companion knew exactly.

**Cause.** `app._relink_moved` walks the media pool that is OPEN
(`resolve_bridge.get_media_pool_items`), which was the only walk a move ever
got; nothing distinguished "nothing referenced it" from "the project that
references it was not open". `watcher.poll_once` treated every MISSING clip
the same way.

**Fix.** An applied move stays on the books until a walk has actually matched
it. `app._relink_moved_result` returns `(matched, text)`, where `matched` is
false for "Resolve not relinked ..." and "Resolve relink failed ..."; the
ledger entry is recorded with `relink_pending=True` (file_moves.py, plus
`old_local`/`new_local` so the question can be asked again later) and the
answer carries `relink_pending: true`, which `db.mark_file_move_applied`
stores (v36 `file_move_targets.relink_pending`) and the page shows as "moved,
Resolve not repointed yet". `app._on_resolve_project_changed` now calls
`_relink_pending_moves`, which re-runs the relink for every
`FileMoveLedger.pending_relinks()` entry (younger than
`RELINK_WINDOW_SECONDS`, 30 days) and on a match clears the flag
(`clear_relink_pending`) and queues a fresh `ok` answer with the relink text
so the dashboard row updates. The watcher takes two new callbacks
(`moved_lookup`, `on_moved_clip`; None keeps the old DEBUG-line behaviour and
every existing test): for a MISSING clip it asks `FileMoveLedger.moved_to`
(the newest entry whose `old_local` is the path, or a parent of it for a
directory move) and, on a hit, `app._on_moved_clip_missing` toasts "'<name>'
moved on the server. CCSync can repoint Resolve to where it is now" and
offers one `RELINK IT` dialog per move per process, under the popup lock; the
relink itself is still `_relink_moved` and therefore
`resolve_bridge.replace_clip`, the one door every media pool write goes
through. A lookup that raises costs the poll nothing.

**Tests.** `companion/tests/test_file_moves.py`:
`test_a_move_applied_with_no_project_open_stays_a_pending_relink` (the answer
carries `relink_pending`, the entry is pending, a later project change
matches, retires it and re-answers with the relink text),
`test_the_ledger_knows_which_move_took_a_path_away`;
`companion/tests/test_watcher.py`:
`test_a_missing_clip_that_a_file_move_took_away_is_offered_for_relink`,
`test_a_missing_clip_nothing_moved_offers_nothing`,
`test_a_raising_moved_lookup_costs_the_poll_nothing`;
`dashboard/tests/test_file_moves.py::test_a_retrying_machine_keeps_the_command_and_shows_its_attempts`
(the `relink_pending` answer reaches the page). Ships as: companion 0.9.55
(the ledger, the project-change re-run and the watcher), with the dashboard
half (the column and the page text) in the v36 OTA; deploy the dashboard
first so the flag has a column to land in.


### MEDIA-2 - stop() and cancel() could not kill the ffmpeg child, because there had never been one - FIXED in repo 2026-08-28, unshipped

**Symptom.** An editor drops a 90-minute mix or a 40 GB original into the
ingest and quits the tray four minutes into the decode, or an admin cancels
the batch from the dashboard. The decode keeps running: an orphaned
`ffmpeg.exe` outlives the tray, holding a handle on the staged file (which
then blocks any later staging cleanup on Windows), and the dashboard's
"cancelling" chip stays up for as long as the encode takes - up to the 900 s
timeout.

**Cause.** `BrollIngestor.__init__` set `self._child = None` and no code path
anywhere in the package ever assigned a Popen to it: ffmpeg ran under
`subprocess.run(timeout=...)` on a daemon thread (`broll_ingest_media.run_ffmpeg`
for b-roll, `music_clap_sidecar._run` for music), `_kill_child` was a no-op on
`None`, and `stop()`'s `join(timeout=5)` abandoned the thread. The docstrings
of `stop()` and of `app.CompanionApp.shutdown` both asserted the kill that the
code had never done.

**Fix.** The media runners now take a `child_sink` and publish their Popen
through it. `broll_ingest_media.run_ffmpeg(cmd, timeout, child_sink=None)`
keeps the blocking `subprocess.run` form when no sink is wired (every existing
test double) and otherwise spawns with `Popen`, hands it to the sink, reads it
with `communicate(timeout=...)`, kills-then-drains on `TimeoutExpired` and
hands `None` back in a `finally`; the sink itself can never fail the run
(`_publish_child` swallows). `music_clap_sidecar._run`, `transcode_to_mp3`,
`decode` and `embed_file` grew the same keyword, passed only when present
(`_sink_kwargs`, because `_run` is a monkeypatch seam whose doubles take the
old arguments); `music_ingest.MusicIngestor` passes `self._publish_child` to
both. On the orchestrator side `BrollIngestor._publish_child` stores the child
under `self._lock` and, if `stop()` or `cancel()` has ALREADY landed, kills it
on the spot - the spawn and the shutdown are on different threads, and that
window is exactly how an orphan used to outlive the tray. `_kill_child` is
real: `terminate()` first (ffmpeg closes its output on SIGTERM; proxies are
written to `.mp4.partial` and renamed only when complete, so nothing
half-written reaches the archive), `wait(timeout=5)`, then `kill()`.
`_run_media` probes the runner's signature (`_accepts_child_sink`) rather than
catching a bare `TypeError`, so a genuine `TypeError` inside a runner still
surfaces. `cancel()` already called `_kill_child`; it now does something. Ships
in the companion build; nothing on the dashboard changes.

**Tests.** `companion/tests/test_broll_ingest.py::test_the_media_runner_publishes_its_child_and_stop_kills_it`,
`::test_a_child_published_after_stop_is_killed_at_once`,
`::test_a_runner_without_the_keyword_is_still_called`;
`tests/test_music_ingest.py`'s `FakeSidecar` takes the new keyword.

### MEDIA-3 - ingest staging was never cleaned up, and the plan said it was - FIXED in repo 2026-08-28, unshipped

**Symptom.** An editor who drops 40 clips a week fills their own disk: every
batch left `<local_root>/Assets/B-roll Archive/.ingest/<staging_id>/` holding
the uploaded originals, proxies, posters, sprites and frame sheets for ever,
and `_staging` kept every entry in the state file across restarts. When free
space fell below the 20 GB floor, `prepare` answered 507 and the gate said
"Not enough space where the clips would be staged ... Free some space and it
will continue" - naming a dot-folder inside the archive that the editor has
no UI to see or clear. `docs/BROLL_INGEST_PLAN.md` (lines 219, 259) has
promised "staging retained 7 days after live" since the feature shipped.

**Cause.** No `rmtree` of a staging directory existed anywhere in the
companion, no retention key existed, and nothing recorded when a batch
ENDED (the only sensible start of a retention clock).

**Fix.** `broll_ingest.DEFAULT_STAGING_RETENTION_DAYS = 7`, overridable per
kind as `<kind>_ingest_staging_retention_days` (config.py DEFAULTS carries
`broll_ingest_staging_retention_days = 7`, documented commented-out in
`config.example.toml`; the music kind reads `music_ingest_staging_retention_days`
through `IngestKind.cfg_key` and falls back to 7; 0 means "as soon as the
batch ends"). `_note_staging_ended` stamps `ended_at` on the staging entry
when a batch finishes, is cancelled or is abandoned - the clock starts when
the BATCH ends, not when the drop was staged, so a 400-clip batch three days
into its crunch never has its inputs deleted underneath it.
`BrollIngestor.prune_staging(max_age_days=None)` runs LAST in `tick()`, after
the finish so a batch that ended this tick has its stamp; it deletes every
finished staging dir older than the retention, forgets its `_staging` entry
and saves, and never raises (an `rmtree` refused by a Windows handle is left
for the next tick, entry kept). The RUNNING batch's staging is never a
candidate (`_staging_entries` excludes it) and neither is a drop that has
been staged but not run; an unparseable timestamp reads as ancient
(`_iso_epoch` -> 0.0), which only ever deletes bytes already in the archive.
`staging_report()` returns `{bytes, batches, oldest_at}` (bounded walk,
`_dir_bytes`), aggregated across both kinds by
`app.CompanionApp.ingest_staging_report` into `sync_guard.ingest_staging`
(present only when bytes > 0). `_space_refusal` now names how much of the
drive is finished staging and where the button is: "... 12.0 GB of that
drive is finished b-roll staging: open Settings from the tray icon and use
CLEAR FINISHED STAGING". Settings > SYNC LANES shows "Finished indexing
staging is holding N GB on this computer" with `[ CLEAR FINISHED STAGING ]`
(`settings_window.action_clear_ingest_staging` ->
`app.clear_finished_ingest_staging`, which is `prune_staging(max_age_days=0)`
on both kinds and answers "Cleared N finished staging folder(s), X GB" or
"There is no finished staging to clear on this computer"). In the same
function, UX-17's companion half: `prepare` sums the `upload` items' sizes
and `_space_refusal(root, wanted_bytes=...)` refuses the WHOLE drop before
the first byte ("this drop needs 200.0 GB on top of the 20 GB floor")
instead of 507ing per file once part of it was already on the disk. Ships in
the companion build; the dashboard's v38 `ingest_staging_bytes` column shows
it on the grid.

**Tests.** `tests/test_broll_ingest.py::test_finished_staging_older_than_the_retention_is_deleted`,
`::test_a_recent_batch_and_an_unfinished_drop_are_left_alone`,
`::test_the_running_batch_staging_is_never_a_candidate`,
`::test_clear_finished_staging_takes_everything_now`,
`::test_staging_report_counts_the_bytes_the_space_refusal_blames`,
`::test_a_batch_that_ends_starts_the_retention_clock`,
`::test_a_drop_bigger_than_the_free_space_is_refused_whole`,
`::test_a_drop_that_fits_is_still_accepted`;
`tests/test_app.py::test_ingest_staging_is_attributable_in_the_report`,
`::test_clear_finished_staging_reports_what_it_freed`,
`::test_nothing_to_clear_says_so_rather_than_claiming_success`;
`tests/test_config.py` (the key is documented and commented out like every
other tunable); `tests/test_settings_window.py::test_finished_staging_has_a_line_and_a_clear_button`.

### UX-3 / SYNC-10 - a project folder renamed in Explorer stopped syncing and reported as idle; a project directory in no plan was invisible - FIXED in repo 2026-08-28, unshipped

**Symptom.** An editor tidies up: `P:\Projects\2026\Nuclear` becomes
`P:\Projects\2026\Nuclear FINAL`, or is dragged one level up by accident.
Lane A finds no source directory and sets `idle` with the detail
"project dir not yet local: <subpath>" - the same string an ordinary first
run shows on the tray line and the fleet chip - so everything filed in the
renamed folder from that moment on is invisible to the fleet while the
machine reports as normal; lane B recreates the original folder and
re-downloads it, so the editor ends up with two folders and no error.
Separately (SYNC-10), a server-side repath onto a target the editor already
had a stale copy at leaves the old directory in place with one WARNING
(`repath.py` "re-pointing the folder anyway"): that tree is in no selection,
no lane ever touches it again, the manifest counts its files as this
machine's presence, and nothing ever reported it.

**Cause.** Lane A could not distinguish "never seen" from "was here last
pass and is gone" - no per-project record existed - and nothing walked
`Projects/` for a `.ccsync-project` marker whose slug is in no selection.
`repath.reconcile` handles SERVER-side moves only.

**Fix.** `sync/rclone_lane.py` persists a per-project record in
`<state dir>/project_dirs.json` (`PROJECT_DIRS_FILENAME`; `{version, seen:
{subpath: {last_seen_at, path, slug}}, updated_at}`, tmp + `os.replace`):
`_note_project_dir_seen` writes it on every pass the directory exists and
clears any moved-entry for it (an editor who put the folder back must not
keep a stale alarm), and `_project_dir_absent` replaces the old inline
branch of the pass: no `last_seen_at` is still `idle` with the old detail;
a record means `STATE_ERROR` with `detail`/`last_error` "Your project folder
for <label> is not where CCSync expects it. Did you rename or move it?",
plus " It looks like it is at <path> now." when `_find_moved_project_dir`
locates the marker somewhere else on the machine. `scan_project_markers`
walks `<local_root>/Projects` for `.ccsync-project` markers (bounded by
`MAX_PROJECT_SCAN_DIRS = 20000`, never descends into a project, first
duplicate slug wins and the rest are logged) and returns `None` for "could
not look", which callers must not read as "there are none".
`_refresh_stray_projects` runs on the orphan-scan cadence
(`_maybe_scan_orphans`), local-only, and reports project directories whose
marker slug is in no selection as `{count, bytes, paths, slugs, checked_at}`
- report-only, the `.partial` scan's posture, nothing deleted; it answers
`None` when `known_rels_fn` is unwired or the selection is EMPTY, because
the sequencer answers `[]` before its first fetch and whenever the dashboard
is unreachable, and the ambiguous reading would name every project on the
machine. `app.sync_guard` carries `moved_project_dirs` (<= 20, only when
non-empty; an absent key is what clears the chip) and `stray_projects` (only
when `count > 0`), and a new blocked reason `project_dir_moved` (after
`no_selection`, before the filter/stall reasons) renders the same sentence
with "(N project folders are missing)" when there are several. The self-heal
is a CLICK, never automatic: Settings > SYNC LANES lists each moved folder
("'Nuclear' is not where CCSync expects it - nothing in it is reaching the
server", "found at <path>") with `[ PUT 'Nuclear' BACK WHERE CCSYNC EXPECTS
IT ]` only when the marker was found (`settings_window.action_put_project_back`
-> `app.put_project_dir_back`, which goes through the sequencer's
`repath._move_dir` - the same move the server-side repath uses, refuses an
occupied target and deletes nothing - and answers "N project folder(s) put
back where CCSync expects them. Syncing starts again on the next pass" or
"Close Resolve and Explorer on it and try again"). Strays get a line with no
button on purpose: "N project folder(s) on this computer are in no sync plan
(X GB). Nothing syncs them and CCSync will not delete them". Ships in the
companion build; the dashboard's v38 `moved_project_dirs_count` and
`stray_projects_count/bytes` columns show them per machine.

**Tests.** `tests/test_rclone_lane.py::test_a_project_dir_that_was_never_here_is_still_idle`,
`::test_a_project_dir_that_vanishes_is_an_error_naming_the_folder`,
`::test_putting_the_folder_back_clears_the_alarm`,
`::test_the_last_seen_record_survives_a_restart`,
`::test_stray_project_dirs_are_reported_never_deleted`,
`::test_an_empty_selection_is_not_evidence_that_everything_is_stray`,
`::test_scan_project_markers_does_not_descend_into_a_project`,
`::test_scan_project_markers_says_could_not_look_rather_than_none`;
`tests/test_app.py::test_a_moved_project_folder_reaches_the_report_and_the_one_sentence`,
`::test_no_moved_folders_means_no_key_and_no_reason`,
`::test_stray_project_dirs_ride_the_report_when_there_are_any`,
`::test_putting_a_project_folder_back_goes_through_the_repath_move`,
`::test_a_folder_we_cannot_find_is_not_offered_as_a_move`;
`tests/test_settings_window.py::test_a_moved_project_folder_is_readable_with_a_button_to_put_it_back`,
`::test_a_folder_we_cannot_find_gets_the_warning_but_no_button`,
`::test_stray_project_folders_are_reported_with_no_delete_button`.

### APP-2 / RES-12 / UX-4 - IGNORE ALL was permanent for the session, invisible, honoured even by "Scan whole project", and out-of-tree clips never reached the admin - FIXED in repo 2026-08-28, unshipped

**Symptom.** The out-of-tree popup opens with 65 clips (ruskin's PC did this
on every start, CR-27); the editor is mid-edit and presses SKIP FOR NOW.
Later they use tray > Scan whole project and it answers "all media is in
the tree", because both the popup batch and the scan filtered through the
same in-memory set, and nothing in the tray, the log summary, diagnostics or
the report said "65 clips are hidden because you skipped them"; the only
cure was restarting the tray, which nobody knew. An editor with a personal
stock library outside the tree was offered the same 300 clips at every
start and trained to dismiss the one dialog that also catches a genuinely
un-synced card dump. And no field in the report carried out-of-tree,
bad-prefix or missing counts: `watcher.poll_once` computed exactly those
numbers and threw them away, so the owner could not learn that a machine
held 40 timeline clips that would never reach anyone. The headless fallback
(a wedged Tk) auto-skipped whole batches and looked identical to an editor
pressing SKIP.

**Cause.** `fixer.IgnoreTracker` was a per-session set by SPEC, with no
`clear()` caller anywhere; there was no persisted third answer; and the
watcher's counts stopped at `ok`.

**Fix.** `fixer.IgnoreTracker(state_dir)` now has three parts. (1) The
session set is unchanged in meaning, and `app.scan_whole_project` calls
`clear()` AFTER the Resolve call and its refusals (a scan that could not run
must not spend the editor's skip decisions), logging how many it released;
its "all media is in the tree" toast appends "(N folder(s) are set to be
left alone - Settings shows them)" when folder ignores exist. (2) A
persisted FOLDER layer (RES-12): `ignore_folder(folder, reason)` /
`forget_folder` / `folders()` / `folder_count()` in `fixer_ignores.json`
(`{folders: [{folder, reason, when}]}`), matched by `canon._is_under` in the
path's own platform spelling (CR-90) so a sibling with the same prefix is not
caught; `ignore_folder` returns False when it cannot persist, because an
"always" that lasts until the next restart is worse than no button. The
popup grew a third button, `[ ALWAYS LEAVE THIS FOLDER ALONE ON THIS
COMPUTER ]` (or `... THESE n FOLDERS ...`, `popup._folder_button_label`),
wired to `popup.perform_ignore_folders` (one entry per distinct folder via
`folders_of`, then `perform_ignore_all(how="folder")` so the clips go away
now whatever happened to the file); a failed write shows "CCSync could not
save that choice, so these clips are only skipped until you restart. Tray >
Settings > COPY DIAGNOSTICS FOR YOUR ADMIN". It is undone from Settings >
ADVANCED only ("Leaving clips in <folder> alone (<reason>)" + `[ FORGET:
<folder> ]`, `settings_window.action_forget_ignored_folder`, toast "CCSync
will offer clips in <folder> again"), and `scan_whole_project` deliberately
leaves it standing: a standing decision, not a dismissal. (3) A persisted
LEDGER (UX-4): `ignore(path, how)` records `{path, when, how}` in
`skipped_clips.json`, capped at `_MAX_SKIPPED_RECORDED = 5000` oldest-out;
it suppresses nothing (the button still says "this session" and means it),
it exists so a tray restart does not erase the count, and `how` is `skip`,
`folder` or `headless` so a wedged display is distinguishable from an editor
pressing SKIP. Both files live under `<log dir>/state/` (~/.ccsync/state by
default), deliberately NOT beside config.toml where APP-3 moved the safety
latches: deleting them costs nothing worse than being re-offered clips. A
corrupt file reads as `{}` (fails towards showing the clips) and a tracker
built without a state dir is the old session-only behaviour. The counts
travel: `watcher.poll_once` now keeps `total_out_of_tree` / `total_bad_prefix`
as poll TOTALS (the four counters beside them stay per-poll deltas), returns
them as `out_of_tree_total` / `bad_prefix`, and `_note_scan` publishes
`last_counts` / `last_scan_at` only at the END of a full pass, so an early
return (drive out, Resolve closed) leaves the last real answer standing.
`app.resolve_health()` is ALWAYS in `sync_guard` as
`{out_of_tree, bad_prefix, missing, ignored_this_session, ignored_folders,
skipped_ever, last_scan_at, open_project}`; `last_scan_at = None` until a
poll has completed is load-bearing (a zero that means "we have not looked"
must not render as "nothing is wrong"). The tray line
(`tray._ignored_line`, rendered in Settings > SYNC LANES) reads "⚠ 14
clip(s) skipped this session and still not syncing - Settings > SCAN WHOLE
PROJECT offers them again" and "2 folder(s) are set to be left alone on this
computer - Settings can undo that"; diagnostics gain a "resolve media"
section (`app._resolve_health_text`: "65 clip(s) outside the tree, 1 on a
broken P: mapping, 2 missing on disk, 1 skipped this session, 14 skipped
ever, 1 folder(s) left alone on purpose (last scan ...)" or "no timeline
scan has completed yet (is Resolve open?)"). Ships in the companion build;
the dashboard's v38 `resolve_out_of_tree` and companions are what put the
"clips outside the tree" note on the grid.

**Tests.** `tests/test_fixer.py::test_a_folder_ignore_is_honoured_and_survives_a_restart`,
`::test_a_folder_ignore_does_not_catch_a_sibling_with_the_same_prefix`,
`::test_forget_folder_brings_the_clips_back`,
`::test_a_folder_ignore_that_cannot_be_persisted_is_refused`,
`::test_a_tracker_with_no_state_dir_is_the_old_session_only_behaviour`,
`::test_skipped_clips_are_recorded_across_a_restart`,
`::test_the_skip_ledger_records_how_the_clip_was_skipped`,
`::test_clear_forgets_the_session_but_not_the_folders`,
`::test_a_corrupt_ignore_file_fails_towards_showing_the_clips`,
`::test_the_skip_ledger_is_bounded`;
`tests/test_popup.py::test_perform_ignore_folders_persists_one_entry_per_distinct_folder`,
`::test_perform_ignore_folders_reports_what_it_could_not_save`,
`::test_the_folder_button_names_its_own_scope`,
`::test_the_headless_fallback_records_that_nobody_chose_this`;
`tests/test_app.py::test_scan_whole_project_clears_the_session_skips` (this
test used to assert the OPPOSITE), `::test_scan_whole_project_still_honours_a_persisted_folder_ignore`,
`::test_resolve_health_rides_the_report`, `::test_resolve_health_before_any_scan_says_so`,
`::test_diagnostics_names_the_clips_somebody_dismissed`,
`::test_skipped_clips_survive_a_tray_restart`;
`tests/test_tray.py::test_ignored_line_names_the_way_back`,
`::test_ignored_line_mentions_the_folders_left_alone_on_purpose`,
`::test_ignored_line_is_silent_on_a_healthy_machine`;
`tests/test_settings_window.py::test_the_skipped_clip_line_appears_in_sync_lanes`,
`::test_each_leave_alone_folder_gets_a_forget_button`,
`::test_no_forget_buttons_when_nothing_is_left_alone`.

### UX-15 - the broken-mapping toast told the editor something untrue and offered no repair - FIXED in repo 2026-08-28, unshipped

**Symptom.** When Resolve's canonical path did not land in the sync folder,
the toast said "Resolve is looking for media on P: but that path doesn't
land in your sync folder. Your P: drive (Windows) or Mapped Mount (Mac) is
wrong. See EDITOR_SETUP step 6. Nothing will sync until this is fixed." Both
halves were wrong for the audience: lanes A and B run off `local_root` and
were unaffected (what is broken is Resolve's view of the media), and an
editor has no EDITOR_SETUP. It fired once per episode, was not reported, and
offered no button even though `drive_swap.swap_to_local` is exactly the
repair.

**Cause.** `drive_swap.classify_p_target` computed `other` / `none` and only
`server` was ever consumed; the toast copy predates the site-manifest drive
letter and the Settings window.

**Fix.** The toast (app.py, the `bad_prefix` branch of the watcher callback)
now reads "Resolve is looking for your media on P: but P: is not pointing at
your synced folder, so clips will show offline. Your uploads and downloads
are still running. Tray > Settings > REPAIR P: NOW", with the letter from
`app.canonical_prefix_label()` (site data, COMMERCIAL_READINESS item 11: a
customer on Q: reads Q:, and an empty prefix falls back to "your media
drive" rather than a guessed letter). Settings > ADVANCED shows the same
sentence and `[ REPAIR P: NOW ]` (`settings_window._needs_p_repair`: the
cached `p_mode` is `other`/`none`, OR `resolve_health.bad_prefix > 0` this
poll; `app.p_repair_available` is Windows-only, because macOS has no drive
namespace to repair and drive_swap's runner would try to spawn `net`/
`subst`), placed ABOVE the grade swap because this is the broken state and
the swap is a thing the editor chose. `settings_window.action_repair_p_mapping`
-> `app.repair_p_mapping()`: `local` is a no-op ("P: is already pointing at
your synced folder"), `server` refuses ("... because you asked for a grade
swap. Use FINISH GRADING to put it back"), `other` REFUSES before anything
is unmapped, naming the target ("P: is mapped to \\nas\someone_else, which
CCSync did not create. Nothing was changed. Ask your admin before removing
it") - UX-6's ownership check kept, because `swap_to_local`'s first act is an
unconditional unmap that cannot put a foreign mapping back - and `none`,
the state the toast actually fires for, goes through the existing
`swap_p_to_local`. `bad_prefix` rides `sync_guard.resolve_health` (UX-4) so
the owner sees it too. Ships in the companion build.

**Tests.** `tests/test_app.py::test_the_mapping_toast_tells_the_editor_the_truth`,
`::test_the_toast_names_the_site_drive_not_a_hardcoded_p`,
`::test_repair_refuses_a_mapping_ccsync_did_not_create`,
`::test_repair_refuses_while_the_editor_is_grading_from_the_server`,
`::test_repair_maps_the_drive_back_when_it_points_at_nothing`,
`::test_repair_is_a_no_op_when_the_drive_is_already_right`;
`tests/test_settings_window.py::test_the_repair_button_appears_only_when_the_mapping_is_broken`,
`::test_the_repair_button_is_absent_where_it_could_do_nothing`,
`::test_the_repair_button_names_the_site_drive`.

### UX-13 / OPS-6 (companion half) - an interrupted install left a machine with no companion and no P:, and nothing recorded it - FIXED in repo 2026-08-28, unshipped

**Symptom.** An editor re-runs the wizard to fix something, it stalls on a
slow winget/Tailscale step, and they close the window. The wizard's worker
is a daemon thread, so it dies wherever it happens to be - after the tree
drive was unmapped, after the autostart entries were deleted, with a
config.toml from either side of the wipe - and no file on disk says an
install was interrupted. If a companion ever starts again against that
config it syncs as if nothing happened, and the editor spends a week
believing they are set up.

**Cause.** Nothing wrote a record before the wizard's clean-slate phase, and
the companion had no reason to refuse.

**Fix.** The wizard now writes `~/.ccsync/state/install_in_progress.json`
before `_clean_slate` and deletes it on Finish, opening on a page with
`[ FINISH THE INSTALL ]` when it finds one (that half is
`onboarding/steps.py install_breadcrumb_path` / `onboarding/onboard.py`, the
wizard agent's slice). The companion half: `app.install_in_progress_problem(cfg,
config_dir)` (`INSTALL_BREADCRUMB_FILENAME`) reads the FIXED
`~/.ccsync/state` path - not the configured log directory's state dir, since
the wizard cannot know a `log_path` that a config it is about to overwrite
might name - and, when the breadcrumb exists, `CompanionApp.__init__` appends
a CONFIG PROBLEM: "The last install of CCSync on this computer did not
finish, so this machine may have no P: drive and a half-written setup.
Nothing will sync until it is finished. Run the CCSync installer again and
choose FINISH THE INSTALL." (letter from `canonical_prefix`, "your media
drive" when unset). A config problem deliberately, because that is the one
gate every lane, the popup, FIX ALL and Consolidate already obey (DEL-3). An
unreadable directory means "no breadcrumb": this is a refusal to sync, and a
permissions hiccup must not manufacture one. Ships in the companion build,
but only a rebuilt installer/onboarding package ever WRITES the breadcrumb.

**Tests.** `tests/test_app.py::test_no_breadcrumb_is_not_a_problem`,
`::test_the_breadcrumb_names_this_sites_drive`,
`::test_an_interrupted_install_stops_the_companion_syncing`,
`::test_a_finished_install_leaves_no_problem`.


### UX-17 / C-7 - the ingest drop had a count cap and no size gate: hundreds of GB started staging with no confirmation, no leave-page guard and no word about what was filtered out - FIXED in repo 2026-08-28, unshipped

**Symptom.** An editor drops a 200 GB camera card on the b-roll ingest panel.
Staging starts at once; the only thing that could stop it was the companion's
per-file 507, which fired mid-batch once part of the drop was already on the
disk, and only for the files not yet staged. Nothing asked before committing
an evening of the machine's GPU to it. Closing the tab lost the whole un-run
drop (only a DISPATCHED batch is re-attached on reload) and the bytes already
streamed into staging went with it. A mixed drop discarded its non-video half
with no message at all - "40 clips" where 60 files were dropped - and the
no-entry-API branch (Firefox pre-50, a synthetic drop) pushed EVERY file,
video or not.

**Cause.** `ING_MAX_ITEMS = 2000` (ingest.js) was a COUNT cap and the only
ceiling the panel had. The companion's `GET /broll/ingest/capabilities`
already answered `staging.free_bytes` and `staging.floor_bytes`
(broll_server.py:997, :1110) and the page read neither;
`BrollIngestor.prepare` ran `_space_refusal(root)` against the floor alone,
never against the drop, so the whole-drop check existed nowhere. No
`beforeunload` handler in any of the three scripts. `ingestWalkEntry` dropped
a non-video entry with a bare `return`.

**Fix.** Two gates, one each side, both before the first byte:

- Page (`broll/web/static/ingest.js`): `ingestSpaceRefusal(items)` measures
  the UPLOAD items' bytes (a picked path is indexed where it is and stages
  nothing) against `ing.caps.staging.free_bytes` less `floor_bytes`, and
  `ingestAddItems` runs it over what is already held plus what arrived - two
  100 GB drops in a row are the same 200 GB - refusing the whole drop through
  `ingestSetNotice` and an error toast: "That drop is 180.0 GB and this
  computer has 95.0 GB free where clips are staged, of which 20.0 GB is kept
  clear. Nothing was staged. Free some space, or drop fewer clips at a time."
  A companion that has not answered yet, or could not measure the drive,
  refuses NOTHING ("I could not tell" must never read as "no", the same rule
  as the companion's `_space_refusal`); the companion's 507 backstops that
  case.
- Companion (`broll_ingest.py`, `BrollIngestor.prepare`): sums `size` over
  the raw items whose `source` is not `path` and calls `_space_refusal(root,
  wanted_bytes=wanted)`, which now refuses when `free < floor + wanted` with
  one 507 for the WHOLE drop naming the figures ("... 30.0 GB free, and this
  drop needs 50.0 GB on top of the 20 GB floor"). The same sentence now also
  names how much of the drive is finished staging and points at CLEAR
  FINISHED STAGING; that clause is MEDIA-3's and is documented there.
- Confirmation (C-7, `ingestRun`): above `ING_CONFIRM_BYTES = 50e9` only ("a
  four-clip drop does not need a dialog"), a `window.confirm` with C-7's copy
  verbatim: "This drop is {size} across {n} clips. Staging it needs {size}
  free on this computer and it has {free}. Indexing will run for about
  {hours} hours. Start it?" - `hours = max(1, round(n * 1.5 / 60))`
  (`ING_MINUTES_PER_CLIP = 1.5`, the measured Good-tier rate on a 4090,
  deliberately rough: the number exists to say "hours, not minutes"); `free`
  reads "an unknown amount" when the companion could not measure.
- `beforeunload` (registered in `ingestInit`): armed while
  `ingestUploadsInFlight()` - an item mid-upload, or an included, accepted,
  not-yet-uploaded upload item in a batch that is not running. The browser
  shows its own wording.
- The filtered half: `ingestCollect` threads a `skipped` counter through
  `ingestWalkEntry` and the flat-files branch (which now applies
  `ingestIsVideo` too) and toasts "{k} of {total} files were not video and
  were left out." (warn).

Every URL the new code builds stays document-relative or on the configured
loopback `COMPANION_URL`; `test_mounted_prefix.py` scans ingest.js as before.

**Tests.** `broll/web/tests/test_ingest_ui.py` (source scans, like the rest
of that module): the refusal call precedes `ing.items.push`, the
could-not-measure branch refuses nothing, the C-7 figures are in the copy,
`beforeunload` + `ingestUploadsInFlight` exist, the not-video sentence and the
flat-branch filter. `companion/tests/test_broll_ingest.py`:
`test_a_drop_bigger_than_the_free_space_is_refused_whole` (ten 5 GB uploads
against 30 GB free is one 507 naming "50.0 GB") and
`test_a_drop_that_fits_is_still_accepted`.

**Ships as:** page half with the dashboard OTA (broll/web); companion half in
companion 0.9.55.

### UX-19 - the client's dead end: a dead share link named nobody, and a clip pulled mid-session was a broken video box - FIXED in repo 2026-08-28, unshipped

**Symptom.** A client opens a link that has since been rotated or expired and
gets "THIS LINK IS NOT AVAILABLE ... Please contact whoever sent it to you for
a fresh link." - no name, no organisation, no address, from the only page they
have. A clip the editor removed from the folder while the client had the page
open 404'd on its next fetch and the browser's own broken-video state was all
there was to see; the detail panel said "No description available."

**Cause.** `routes_share._gone_page()` served `share_gone.html` as a static
file with nothing from the record, though the record already carried both
halves (`client_folders.created_by`, the curating editor, and `contact`, the
free text the live page renders as a mailto). `share.js` had no `error`
listener on the `<video>` and collapsed every detail-fetch failure into one
string.

**Fix.** `client_folders.gone_contact_sentence(folder)` builds the plain-text
sentence - "Please ask jsmith at sales@example.com for a fresh link." /
"Please ask jsmith for a fresh link." / "Please contact {contact} for a fresh
link." / "" when the record names nobody or there is no record - and
`routes_share._gone_page(folder)` (from both `share_root` and `share_page`)
replaces `client_folders.GONE_FALLBACK_SENTENCE` in the HTML once,
`html.escape`d (both halves are editor-entered text landing on a public
page), as an `HTMLResponse` with the SAME 404, the same public headers and
`private, no-store`. Only a token we still RECOGNISE (revoked or expired,
`cf.is_live` false) gets a name: an unknown token gets the unchanged generic
file, because naming somebody would reveal that the token once existed, and
nothing else about the folder leaks (no title, clip or count). The sentence
is an exact string match between `share_gone.html` and the constant; the
HTML comment says so and a test pins that the file holds it exactly once.
Mid-session: `share.html` gains `#share-clip-gone` (amber, `share.css`);
`shareInit` adds one `error` listener on the reused player which calls
`shareExplainPlaybackFailure(video.id)` - the element reports "it broke" and
never why, so it re-asks `api/videos/{id}`: a 404 there renders "This clip is
no longer in this folder. Refresh the page to see what is." and anything
else "This clip could not be played just now. Refresh the page to see what is
in this folder."; `shareOpen`'s detail fetch treats its own 404 the same way,
and `shareOpen`/`shareClose` clear the box. The finding's "carry the name
into the share record" needed no schema change: both columns existed. Every
fetch stays document-relative.

**Tests.** `broll/web/tests/test_client_folders.py` section 6: a revoked link
names the editor and contact on both the bare and trailing-slash forms with
the 404 and headers unchanged and no title/clip in the body; an unknown token
still gets the generic page; a folder with no contact still names the editor;
the sentence is escaped; `gone_contact_sentence` on a record with nobody on
it; the page and the constant agree; and the viewer scan (both doors, the
element id, no root-relative `/api/videos/`).

**Ships as:** dashboard OTA (broll/web).

### UX-13 / OPS-6 - closing the wizard mid-install left a machine with no companion, no tree drive and no autostart, and nothing recorded it - FIXED in repo 2026-08-28, unshipped

**Symptom.** An editor re-runs the wizard, a winget or Tailscale step stalls,
and they close the window ("I'll try again later") or reboot. The daemon
worker died wherever it was - after `_clean_slate` had unmapped the drive,
killed the companion and deleted every autostart entry, before the bootstrap
put anything back - while the spawned bootstrap PowerShell kept running
UNPARENTED, mapping drives and writing config into a machine whose wizard was
gone and racing the second run started a minute later. No file on disk said
an install was interrupted; the editor believed they still had CCSync, and a
companion that did start afterwards synced against a config from either side
of the wipe.

**Cause.** `onboard.py` registered no `WM_DELETE_WINDOW` handler, so Tk's
default (destroy everything, silently) applied at every phase.
`steps.run_bootstrap` ran the child through `subprocess.run`, which gives no
handle to kill and no process group. Nothing was written before the
destructive phase.

**Fix.** Three pieces, wizard + companion:

- The breadcrumb (`onboarding/steps.py`): `write_install_breadcrumb(phase)`
  writes `~/.ccsync/state/install_in_progress.json` (`{phase, started_at,
  installer_version}`, tmp + `os.replace`) and `OnboardWizard._clean_slate`
  calls it BEFORE its first destructive act with `clean_slate:<role>` (a
  write failure logs a WARNING into the install log and installs anyway).
  `clear_install_breadcrumb` is called from `_install_finished()`, reached by
  BOTH finish pages (`show_finish`, `show_finish_base`) and nothing else:
  "half-installed", not "not perfect", so a finish with warnings still clears
  it. `read_install_breadcrumb` returns `{}` for a corrupt file: the file
  existing is the signal. On start the wizard opens on `show_interrupted`
  ("THE LAST INSTALL DID NOT FINISH ... Until it is finished, there is no
  CCSync app and no {letter} drive on this machine, so nothing is syncing. It
  started at {started_at}.") with [ CLOSE ] / [ FINISH THE INSTALL ], the
  latter going to the licence page; the crumb is NOT cleared on that click,
  only by a real finish.
- The close handler (`OnboardWizard._on_close_request`): free everywhere
  except while `self._installing`, where `messagebox.askyesno` (default No,
  warning icon) asks `steps.install_close_warning(letter)`: "The install is
  part-way through. Closing now leaves this computer with no CCSync and no
  {letter} drive. Close anyway?" - the letter from the site manifest, never a
  literal P. On yes, `steps.terminate_bootstrap()` first, then destroy.
  `run_bootstrap`'s default runner is now `steps.default_bootstrap_run`:
  `Popen` in its own process group (`CREATE_NEW_PROCESS_GROUP` /
  `start_new_session`), published in `steps._bootstrap_child`, and
  `terminate_bootstrap` takes the whole tree down (`taskkill /T /F` on
  Windows because the .ps1 spawns winget, an elevated helper and Syncthing;
  `os.killpg` elsewhere); a runner timeout terminates the group too. Tests
  that inject their own `run` are unaffected.
- The companion (`app.install_in_progress_problem`, app.py:109, applied in
  `CompanionApp.__init__` at :1175): finding the breadcrumb under
  `config.CONFIG_DIR/state` adds a CONFIG PROBLEM - "The last install of
  CCSync on this computer did not finish, so this machine may have no
  {prefix} drive and a half-written setup. Nothing will sync until it is
  finished. Run the CCSync installer again and choose FINISH THE INSTALL." -
  because `config_problems` is the one gate every lane, the popup, FIX ALL
  and Consolidate already obey (DEL-3). An unreadable state dir is "no
  breadcrumb": a permissions hiccup must not manufacture a refusal.

Button names differ from the findings' sketches (`[ RESUME ]` and `[ KEEP
INSTALLING ] / [ CLOSE ANYWAY ]` became [ FINISH THE INSTALL ] and a Yes/No
box carrying UX-13's sentence) but every mechanism proposed is built.

**Tests.** `onboarding/tests/test_steps.py`: the breadcrumb round trip and
idempotent clear, a corrupt crumb counts as present, the close warning uses
the site's letter (and no em dash), `terminate_bootstrap` with no child and
the `/T` group kill. `companion/tests/test_app.py`: no crumb is no problem,
the sentence names this site's drive and never a guessed P:, an interrupted
install lands in `config_problems`, a finished install leaves none.

**Ships as:** onboard.exe + the macOS wizard (INSTALLER_VERSION bump owed,
see the facts block); the companion half in companion 0.9.55.

### UX-14 - nothing on the install path checked free space, though the wizard's own copy asks for room - FIXED in repo 2026-08-28, unshipped

**Symptom.** A local root on a nearly-full drive validated cleanly in the
wizard, the bootstraps said nothing, and the disk filled days later during
the first lane B pass.

**Cause.** `steps.validate_local_root` made nine checks, none about space;
no `disk_usage`/`df` anywhere in `windows_bootstrap.ps1` or
`macos_bootstrap.sh`.

**Fix.** A WARNING, deliberately never a refusal: a nearly-full drive
installs perfectly well, so the check is kept OUT of `validate_local_root`'s
contract and a test pins that. One sentence in three places, below 200 GiB
free: "This drive has 41 GB free. Synced proxies for one project are
typically 50 to 300 GB."

- Wizard: `steps.local_root_space_warning(value)` (`LOW_SPACE_WARN_BYTES =
  200 * 1024**3`; `_default_free_bytes` walks up to the first existing parent
  because the folder is usually about to be created) is shown live in a new
  AMBER label under the local-root field from `_revalidate_local_root`, and
  only when the path is otherwise valid (two lines about one empty field is
  noise). "Could not measure" is silence: never a figure, never a refusal.
- `windows_bootstrap.ps1`: `Get-LowSpaceWarning` / `Get-FreeBytesForPath`
  (`$LowSpaceWarnBytes = 200GB`; -1 = could not measure = say nothing),
  called once where `$LocalRoot` is finally known, through `Write-Warn2`
  with "Sync will still be set up here; keep an eye on the drive, or re-run
  with -LocalRoot pointing at a bigger one."
- `macos_bootstrap.sh`: `low_space_message` (KiB in, text out;
  `LOW_SPACE_WARN_KB=209715200`) and `free_kb_for_path` (`df -k`, walking
  up), same wording, same `warn`, `--local-root` in the hint.

**Tests.** `onboarding/tests/test_steps.py` (figure and typical-size text,
silent with room and at exactly the floor, silent when unmeasurable or the
probe raises, never refuses what validate accepts);
`installer/tests/Test-ConsoleUser.ps1` (plenty / exactly at the floor / -1 /
41 GB, and that the bootstrap still calls `Get-LowSpaceWarning`);
`installer/tests/test_macos_site_values.sh` (the same table plus a
non-numeric df result and the no-em-dash scan).

**Ships as:** onboard.exe + macOS wizard (the wizard half), rebuilt editor
package (both bootstraps); INSTALLER_VERSION bump owed.

### OPS-7 - the whole Windows install landed in the wrong profile when UAC prompted for another account - FIXED in repo 2026-08-28, unshipped

**Symptom.** A standard-user editor right-clicks "Run as administrator" (or
simply gets a CREDENTIAL prompt rather than consent) and types the machine's
admin account. Every artefact - `%LOCALAPPDATA%\ccsync\bin`,
`~/.ccsync/config.toml`, the identity, the Syncthing home, the HKCU Run
entries, the scheduled-task principal, the loopback share's FullAccess grant -
was created for the ADMIN profile. The script reported success and printed a
device ID; the editor logged back into their own account to no tray icon, no
tree drive and no config, and the dashboard showed a machine that reported
once and never again.

**Cause.** Nothing in `windows_bootstrap.ps1` or the wizard compared the
running identity with the interactive one.

**Fix.** A REFUSAL, the first thing that happens, with the finding's wording
verbatim: "You are running as {running} but {signed_in} is signed in.
Everything this installs is per-user, so {signed_in} would get nothing. Sign
in as {signed_in} and run it again (it does not need administrator rights)."
Domain prefix and UPN suffix are folded (`DOMAIN\alex`, `alex@corp` and
`alex` are one person; case-insensitive) and an UNKNOWN console user says
nothing: a locked session, an RDP session or a hardened WMI service must not
lock somebody out of their own install.

- `windows_bootstrap.ps1`: `Get-ConsoleUser` (`Win32_ComputerSystem.UserName`,
  falling back to `explorer.exe`'s owner) and the pure
  `Test-ConsoleUserMismatch` / `Get-BareAccountName`, run at the top of
  section 0 before anything is read, fetched or created; a mismatch prints
  the refusal plus "Nothing on this computer has been changed." and `exit 2`;
  an undeterminable console user prints a WARNING telling a "run as" user to
  close it and run from their own signed-in account.
- Wizard: `steps.console_user_mismatch(console, running)` is the same rule in
  Python (`_bare_account`), fed by `steps.default_console_user()` (the
  `Win32_ComputerSystem` probe through PowerShell, 20 s timeout, `None` on
  darwin/linux or any failure) and `steps.current_user()`; `show_role`, the
  first page that decides anything, draws a "WRONG ACCOUNT" page with the
  refusal, "Nothing on this computer has been changed." and [ CLOSE ] instead
  of the role question (`_wrong_profile_refusal`, probed once per wizard).
  macOS is exempt on purpose: the wizard is opened from the Finder by the
  person sitting there and there is no credential-prompt path that could
  switch accounts under it.

**Tests.** `installer/tests/Test-ConsoleUser.ps1` (new; AST-extracted, never
dot-sourced): the bare-name folding, the genuine-mismatch wording and no
em/en dash, the same account domain-qualified / different case, unknown
console or running user says nothing, and that the bootstrap still calls the
check. `onboarding/tests/test_steps.py`: the refusal names both accounts,
folds domain and case, says nothing when it cannot tell, the probe is `None`
on darwin, reads the first line, and survives a broken probe.

**Ships as:** rebuilt editor package (the .ps1) + onboard.exe (the wizard);
INSTALLER_VERSION bump owed. No macOS or companion half.

## Resilience sweep, wave 5: recovery and invariants (2026-08-29) - FIXED in repo, unshipped

Wave 5 of `docs/RESILIENCE_SWEEP_2026-08-28.md` (items 34, 40, 42, 43): what
makes the system tell the owner what it is NOT protected against, and the
tests that stop the earlier waves' classes coming back. Schema numbers v39,
v40 and v41 were reserved one per work package so the packages could merge
without renumbering; two were taken (**39 the invariant checker, 40 the
recovery package's Resolve-undo ledger, 41 unused** - the protection panel
chose `meta` over a table and gave its number back, and the migration list
has to stay gapless, so the recovery package moved down into 40 rather than
leaving a hole). Entries below, one per finding.

### SYS-9 - every invariant in this system is enforced at write time and never re-checked - FIXED in repo 2026-08-29, unshipped

**Symptom.** Nothing in this product ever asks whether a fact it relies on is
still true. A tick written while Syncthing was unreachable stays a tick with
no share behind it, and the fleet page renders it exactly like a working one.
A project folder renamed on the NAS by hand keeps its row and loses its
marker, so everybody's ticks for it quietly stop meaning anything. A disk
image copied onto a second PC gives two computers one `machine_id`, and
`adopt_renamed_machine` then ping-pongs one sync plan and one Syncthing
device between two live machines on every report, restarting the affected
folders every enforce cycle. A package published with a `min_version` above
its own version (CR-52) bricks the upgrade channel for every machine that
takes it, and the only thing that ever asked was the publish path. A machine
below 0.9.3 cannot be reached by [ UPDATE NOW ] at all, which is how leso's
Mac sat on 0.9.2 for ten days while an admin pressed a button that did
nothing. None of these is detected, and none of them is what anybody was
looking at when they were finally found.

**Cause.** `collector.folder_tuning_drift` is the only drift check in the
tree: it re-reads a Syncthing folder's settings each cycle and repairs the
keys that drifted, and it covers folder tuning alone. Every other
cross-component fact is enforced by whichever code path wrote it, once, and
is never re-verified by anything.

**Fix.** A ninth collector kind, `invariants`
(`dashboard/src/ccsync_dashboard/invariants.py`), on the slowest cadence in
the collector (`interval_invariants`, `DASH_INTERVAL_INVARIANTS`, default
900 s), running immediately before `alerts` so the alert kind reads the rows
it has just written, and in `SYNCTHING_FREE_KINDS` because most of what it
verifies is a table read and a cloned disk must still be reported on a
deployment with no sync engine.

**It repairs nothing. It names things** - that is the whole gap, and a
checker trusted to write to Syncthing, the tree and the registry on a timer
has B16 (the fleet unshared in one pass) as its failure mode.

THE INVARIANTS ARE DATA, `invariants.INVARIANTS`, the shape
`alerts.ALERT_KINDS` uses: one row per invariant carrying its key, SYS-9's
own number, the fact in a line, the CONSEQUENCE a non-technical owner
understands, the exact next action, its severity and its callable. Adding an
invariant is adding a row; the ledger, the page, the notices, the alert kind
and the weekly report all pick it up with no second edit. Nine of SYS-9's ten
are evaluated: (1) `plan_has_share`, every full tick shared with that
computer's device id; (2) `machine_has_plan`, a reporting computer has a
plan, the unassigned bucket or a base-rig role (CR-28); (3)
`one_identity_per_computer`, one `machine_id` and one device id per computer,
**including the disk-clone signature** - two hostnames on one `machine_id`
that BOTH reported inside one interval get the "a copied disk is in use on
two computers at once" sentence, where the same pair with one stale row reads
as a rename nobody tidied up - the half of that case this could not reach until SYS-18a was fixed below (both clones signed in as the SAME editor, `db.adopt_renamed_machine` deleting one of the two rows on every report, so there was never a second row to group) now reaches it, because the adoption is refused while the other hostname is still reporting (and only adopted later, once it has gone quiet), so both rows survive; (4) `project_markers`, an active project's
marker exists and its slug matches the row; (5) `tree_markers`, the tree root
still looks like the tree rather than an empty mount (the server's half of
`sequencer._check_remote_root`, which only the companion ever ran); (6)
`package_floor`, CR-52's brick plus the floor-drop rule, asked continuously
rather than only at publish; (7) `companion_floor`, a build new enough for
the plan it was given (0.9.3 for a pushed update, 0.9.43 for [ RESUME ],
0.9.54 for an upload-only tick); (9) `snapshot_schedule`, SYS-14's standing
red line, asked of the NAS's own periodic snapshot tasks; (10)
`proxy_pairs`, a `Proxy/<stem>.*` with no original beside it - the cheapest
detector of a half-finished reorganisation.

**(8) `versioning_agrees` is registered and deliberately NOT evaluated**, and
that is the point of the tri-state: `.stversions` retention is 365 d NAS-side
and 30 d editor-side (R5), the editor-side number lives in the companion
build, and no machine reports it - so this server can see one of the two
values it would have to compare. It renders `[ NOT CHECKED ]` with that
sentence. Deleting the row would have hidden the same fact behind an absence.

FOUR STATES, STORED, never two: `invariant_results` (schema v39) keeps `ok`
as 1/0/**NULL** beside a `state` of `ok` / `broken` / `not_checked` /
`check_failed`, so no reader can flatten "could not check" into "fine" - the
load-bearing rule of this whole sweep. A check that RAISES becomes its own
`check_failed` verdict and an `invariant_check_failed` notice reading "treat
it as unchecked, not as fine", exactly as `alerts.scan` does; one raising
invariant never stops the other nine, and the collector kind still succeeds
(a checker that took the collector down with it would cost more than it tells
anybody). Every `not_checked` verdict carries the reason it could not run: no
tree mounted, no NAS API key, no `config` pass completed in this process, no
build published.

Each broken subject is a `db.notice` of kind `invariant_broken` at the
invariant's own severity, carrying the registry's consequence and fix, so it
lands in PROBLEMS THE SERVER FOUND and (at `error`) reaches the alert sink
through `notice_error`; a pass that finds it fixed closes it, and the subject
rows a pass did not name are deleted, because this table is a picture of the
last pass and not a history. One new alert kind, `invariant_broken`, sits
above `red_unexplained` and READS those rows rather than re-evaluating (an
older database with no such table reads as nothing to report there). The page
is Settings -> INVARIANTS, read-only, listing every invariant with its state,
subjects, last-checked time and, when it is broken, the consequence and the
fix; THE REGISTRY IS THE SPINE, so an invariant with no row yet renders
`[ NOT CHECKED ]` rather than being absent. There is deliberately no
[ RE-CHECK NOW ] button: the pass walks the tree and asks the NAS, and a
button an admin can hammer is one that parks the collector's single thread.

**Overlap with wave 4 is deliberate.** Wave 4's "SYS-9 (partial)" entry
below landed invariants 1 and 3 as notice checks inside `notices.run_checks`
(`_check_plan_without_share`, `_check_identity_collisions`), which was the
right shape for a wave that was building the notices ledger anyway. They stay
exactly as they are: this kind is the finding's own ninth collector kind with
its own table and its own tri-state page, and the two agree on the same
conditions from the same data. So one broken share can produce both a
`plan_without_share` and an `invariant_broken` notice, deduped per
`(kind, subject)` and each closing itself - the same "some conditions are
reported twice" that `docs/SELF_DIAGNOSIS.md` already records for the enforce
brake. What the invariant kind adds over the notice is the standing verdict:
the notice can only ever speak up when something is wrong, and the page has to
be able to say "checked, all 34 ticks are shared" and "NOT CHECKED, and here
is why" as well.

**Files.** `dashboard/src/ccsync_dashboard/invariants.py` (new);
`db.py` (SCHEMA_V39 + the `(39, SCHEMA_V39)` step, `record_invariant_result`
/ `fetch_invariant_results` / `broken_invariants`, the `invariant_broken` and
`invariant_check_failed` rows in `NOTICE_KINDS`); `collector.py` (the
`invariants` kind in `KINDS` and `SYNCTHING_FREE_KINDS`, `_interval`,
`_run_invariants`); `settings.py` (`interval_invariants`);
`alerts.py` (`_check_invariants` + the `invariant_broken` registry row);
`notices.py` (the `_JOB_MEANING` line for the new kind); `ui.py`
(`/admin/invariants`); `templates/admin_invariants.html`,
`templates/partials/invariant_checks.html`,
`templates/partials/settings_nav.html` (the INVARIANTS entry).

**Tests.** `dashboard/tests/test_invariants.py` (28): the registry is
complete and every row evaluates on an empty database with nothing claiming
OK; a broken fact writes a notice carrying the registry's own fix and the
alert kind reports it with the registry's consequence; a fixed fact closes
its notice and drops its subject rows; a raising check becomes `check_failed`
with `ok` NULL and does not stop its neighbours or fail the collector cycle;
the deliberately unevaluated invariant 8 and a never-run pass both render NOT
CHECKED and never OK; the cold folder cache and an unaskable NAS are NOT
CHECKED rather than broken; the disk-clone signature is told apart from an
old rename; and the kind is registered before `alerts`, is Syncthing-free,
runs on its own interval and leaves the other kinds' results alone.

**Ships as:** dashboard only (schema v39), one OTA. No companion, installer
or NAS-script change: every invariant is computed from data this dashboard
already holds, plus one bounded `/pool/snapshottask` read on a TrueNAS site
that has an API key. New env: `DASH_INTERVAL_INVARIANTS` (900). New collector
kind: `invariants`. New page: Settings -> INVARIANTS. Operator docs:
`docs/SELF_DIAGNOSIS.md` section 13. Nothing here is required by a companion,
so the usual "dashboard before the companions" ordering has no extra rule
attached this time.

### SYS-18 - thirteen suites, strong on logic and near silent on conditions - BUILT in repo 2026-08-29

**Symptom.** Not a defect in the product: a defect in how the product is
tested, and the reason so much of this ledger exists. The systems agent read
all 4,821 lines of `KNOWN_BUGS.md` as data and counted how each entry was
found: about 40 % by the owner noticing something, about 58 % by a periodic
hand audit, about **2 % by a test**, and 0 % by the system telling anyone.
Every failure class in the sweep is a fault a test could have induced in
seconds and never did, because the suites exercise LOGIC (given this input,
what does the function return) and almost never CONDITIONS (the child never
exits; the clock is wrong; the disk is full; the credential was revoked; the
process died mid-write).

**Cause.** No `chaos`/fault-injection module existed in any of the thirteen
suites (verified by grep across the tree). The seams were not the obstacle -
`popen_factory`, the reporter's `_http_post`, the selection client's opener,
`subprocess.run`, `RcloneLane._monotonic` and `_wait_poll_seconds` are all
injectable and were already used for logic tests, so the harness was about
90 % built and unused for this purpose.

**Fix.** Two modules, one per component that owns an observable:

* `companion/tests/chaos/test_fault_injection.py` - seven injections.
  A `popen_factory` whose child never exits, on both lane directions
  (CR-91b/SYS-17): the pass ends `error` with a sentence, `transferring` and
  `current_project` are cleared, the stall is on disk in `lane_stall.json`
  and rides `sync_guard.stalled` from the OTHER lane; plus its converse, a
  child past both ceilings that is still moving bytes and must never be
  killed. A reply whose `received_at` is 20 minutes ahead (SYS-4): the skew
  is measured, the WARNING names `--min-age` rather than just a number, and
  `blocked_report` answers `clock_skew` with "proxy download will not
  transfer anything" for the grid and the tray. `disk_usage` at 1 GB
  (SYS-5/SYNC-7): lane B parks `paused` before rclone is spawned, the latch
  survives a restart and rides the guard section; and a measurement that
  RAISES parks nothing. A report POST that 401s three times then recovers
  (APP-1): the health record counts the streak, exactly one toast fires, the
  streak clears on recovery and the record survives a restart; and the same
  401 on `/api/v1/selection` serves the cached plan and labels the source
  `cache`, never `live`. The loop raising on its third pass (SYS-2): one
  pass is lost, not the thread, `loop_failures` and `last_error` say so; and
  a scaffolding failure that really does end the thread leaves `_state` at
  STOPPED, is restarted by `LaneWatchdog`, and reaches `watchdog.json` and
  `sync_guard.restarts` with the exception that caused it. A kill between an
  atomic latch's tmp-write and its `os.replace` (class G), parameterised over
  `config.toml`, `lane_stall.json` and `lane_b_breaker.json`: the previous
  committed value is what the next reader gets, and the stray `.tmp` the kill
  leaves behind is not adopted. An empty remote listing on a project scope
  (CR-44/CR-47): the breaker parks lane B before a byte is trashed, and a
  listing that FAILED is still not an empty one.
* `dashboard/tests/chaos/test_fault_injection.py` - the three whose
  observable only exists on the server. An undeclared top-level section and
  an undeclared `sync_guard` sub-key (SYS-3): 200 rather than 422, named in
  the log, folded into the meta record, and rendered as a notice with a fix;
  and every wave-2 section still reading as declared, so the banner cannot
  cry wolf. One `machine_id` on two hostnames (DASH-11): the notice fires,
  is `error`, names both computers and tells the owner to delete
  `machine.json`; a rename is not a clone. A folder listing that answers 200
  with nothing in it (DASH-4): the brake refuses, every project stays active,
  the alarm is persisted - **and the hourly prune is then run**, because a
  brake that stops the deactivation but leaves `purge_nas_media_for_inactive`
  to empty the inventory would be no brake at all.

Two rules govern the modules, and they are what separates them from the unit
tests next door. **Assert the observable, never the call**: the state the
lane reports, the sentence the tray shows, the file the next boot reads, the
notice a person is handed - a test that asserts "the guard ran" passes
against a guard whose answer nobody surfaces, which is the exact shape of
UX-10 and of "green while dead". **No sleeps, no spawns, no network**: clocks
are injected, children are scripted, hours-long ceilings are crossed in
milliseconds; both modules run in under 4 s.

The fault list is DATA (a `FAULTS` tuple naming all nine, the ledger entry
each closes, and which component owns it) with a registry test in each
module, so dropping an injection fails a test instead of quietly making nine
into eight.

**Tests.** The modules are the tests. `companion`: 19 passing. `dashboard`:
13 passing and 1 `xfail(strict=True)` as of the SYS-18a fix below (it was 9
passing and 2 xfails: the two real gaps the injections found, one of which
has since been fixed and its xfail deleted). Operator note in
`docs/SELF_DIAGNOSIS.md` section 11.

**Ships as:** nothing. Tests only; no product code was changed in this work
package.

### SYS-18a - a same-editor disk clone was read as a rename, so `duplicate_machine_id` could never fire for the case its own fix text describes - FIXED in repo 2026-08-29, unshipped

**Symptom.** One person images their editing PC's disk onto their second
computer. Both are signed in as them, both mint no new identity, so both
report the same `machine_id` every 30 s. `notices._check_identity_collisions`
never raises `duplicate_machine_id`, whose own fix text is written for
exactly this ("On the newer computer, quit CCSync, delete the file
.ccsync/machine.json..."). Worse than silence: the two machines' sync plans
are merged and re-homed continuously.

**Cause.** `api._register_machine` read "this `machine_id` at a new hostname"
as a RENAME (WP1, `MULTI_MACHINE_PLAN.md`) with no test of WHEN the old
hostname last reported, and `db.adopt_renamed_machine` then DELETEs the old
`machines` row and moves that computer's `selections` and `editor_prefs`
across. Two clones therefore ping-ponged a SINGLE registry row between the
two hostnames for ever, and each swap deleted the other computer's plan rows
and carried the survivor's plan onto whichever machine reported last. The
collision check groups `machines` by `machine_id` `HAVING n > 1`, and there
was never more than one row. The same starvation hit all three readers: wave
5's invariant 3 (`one_identity_per_computer`) groups the same table and could
not see this shape either, because the adoption had deleted the row it needed
to group.

**Fix, part 1: freshness decides, and the safe direction is to UNDER-act.** A
rename is one computer with two names over TIME; a clone is two computers
with one identity at the SAME time, and the evidence that tells them apart
was already in the table. `_register_machine` adopts only when the old row
has gone QUIET; if it reported inside `api.CLONE_ADOPTION_WINDOW_SECONDS` the
adoption is REFUSED - nothing deleted, no `selections` or `editor_prefs`
moved, the report still recorded under its own hostname, so both rows survive
and the collision lands in front of `duplicate_machine_id` and invariant 3,
which were both already written and already correct. The refusal also raises
`duplicate_machine_id` itself, at the report, naming both hostnames, how long
ago the other was heard from, and the exact next action. No new alert kind was
needed: `duplicate_machine_id` is `error` severity and `alerts`' `notice_error`
kind already delivers every open error notice.

**Fix, part 2: the verdict is REVISITED, not made once.** No window separates
"rebooting after a rename" from "the twin was briefly quiet". A renamed
Windows box reboots and reports under its new name one to three minutes
later, i.e. inside any window wide enough to catch a clone - so **the first
report after a rename is refused BY DESIGN, and recovers by itself**. What
tells the two apart is what happens NEXT: a clone's twin keeps reporting
every 30 s, while a renamed computer's old hostname is never heard from
again. So every report asks again, over EVERY row carrying the id rather than
only the most recent (after a refusal the most recent holder is the reporting
machine itself, and a rule that only looked there could never change its
mind). Once the old row has been quiet for the window, the rename is
confirmed and adopted - the plan and the sticky root move, the old row goes,
and the notice the refusal raised is cleared, so a rename leaves no permanent
finding. Typical cost to a real rename: one to two reports, about five
minutes, and nobody has to do anything. The deferred adoption reuses
`db.adopt_renamed_machine` (`same_computer=True`) rather than a second
plan-moving helper: the taken-name test it has enforced since the ultrareview
of 2026-08-19 is not weakened but REPLACED BY THE THING IT PROTECTED - a row
at the new name that has a plan or a sticky root of its own is a different
computer and is still refused, so the only row that can be adopted onto is an
empty registry row and nothing can be destroyed.

**The window is five minutes** (`health.STALE_REPORT_SECONDS`, reused rather
than invented), measured on `machines.last_seen`, which `upsert_machine`
fills from the server's `received_at` and never from the companion's own
clock (SYS-4: a machine set to 2098 must not be able to declare itself fresh
and make every rename look like a clone). It is ten report cycles at the
companion's 30 s cadence, so a live clone is caught with an order of
magnitude of margin, and it is affordable to be generous in the clone
direction precisely because a refusal is reversible on the next report while
a wrong adoption destroys a plan every 30 s for ever.

**Takes no schema version.** No table, no column, no migration: a freshness
test on a column that has always been there, one extra read on the same
table, a keyword on an existing helper, and a `notices` row of a kind that
already exists.

**Tests.** `dashboard/tests/chaos/test_fault_injection.py`:
`test_a_same_editor_clone_is_named_as_a_clone` was the `xfail(strict=True)`
that pinned this and is now a passing regression test (the notice is raised
by the report itself, is `error`, names both hostnames, carries the
machine.json action, and the collector's own pass keeps it open);
`test_a_live_same_editor_clone_is_refused_and_both_rows_survive` replaces the
old characterisation test and asserts the inverse of what it recorded, over
eight alternating reports (two rows, the plan still on the machine that owns
it, the notice still open);
`test_a_rename_refused_at_first_sight_adopts_itself_once_the_old_name_is_quiet`
is the self-healing path end to end, including the notice being cleared;
`test_a_new_name_given_a_plan_of_its_own_is_never_adopted_onto` is the guard
on it; `test_the_invariant_checker_now_sees_the_same_editor_clone` proves
invariant 3's blind spot is gone. The ordinary rename is pinned by
`test_one_computer_that_was_renamed_is_not_a_clone` and
`test_a_rename_still_carries_the_sync_plan_to_the_new_name`, and the helper
itself by `test_adopt_onto_the_same_computers_own_empty_row_is_allowed` /
`test_adopt_never_lands_on_a_row_that_has_a_plan_of_its_own` in
`tests/test_multi_machine.py`. Rename tests elsewhere now quieten the old row
first (`test_multi_machine.py`, `test_upload_only.py`), which is what a reboot
does and what the two-step verdict reads.

**Ships as:** a dashboard deploy. No companion change, no schema version.

### SYS-18b - the DASH-4 deactivation refusal reads the wrong key, so the notice is cleared instead of raised - FIXED in repo 2026-08-29, unshipped

**Symptom.** A Syncthing whose config was re-created answers 200 with zero
folders. The wave 1 brake works: nothing is deactivated, the NAS inventory
survives, and the refusal is persisted. The wave 4 half does not: PROBLEMS
THE SERVER FOUND never shows it, so the condition reaches a person only if
they open the fleet banner or the container log - which is UX-10 again, in
the mechanism built to close UX-10.

**Cause.** `db.deactivate_missing_projects` persists
`{at, message, seen, active, would_deactivate, ceiling, projects}`, while
`notices._check_collector_alarms` tests `deactivation.get("count")` and its
body formats `deactivation["count"]`. The key is never present, so the `if`
is false on every cycle and the `else` branch CLEARS the notice; had the `if`
ever been true, the f-string would `KeyError` inside `run_checks`' own
per-check isolation and be logged-and-swallowed. Wave 4's own rule is
"register a notice kind WITH its writer"; here the writer is registered and
reads a key its writer never wrote. `enforce_refusal` beside it does have a
`count`, which is what makes the shape easy to miss.

**Fix.** `notices._check_collector_alarms` reads `would_deactivate`, the key
its writer actually persists, through a local (`n_refused`) that both the
condition and the sentence use, so the two cannot drift apart again. Read the
key ONCE: a second `deactivation[...]` inside the f-string is how this
survived review the first time. No schema change and no companion half.

**Tests.** `dashboard/tests/chaos/test_fault_injection.py`:
`test_a_config_with_no_folders_at_all_takes_nothing_off_the_fleet` covers the
brake, the surviving inventory and the persisted alarm;
`test_the_refused_deactivation_reaches_a_person_on_the_home_page` was the
`xfail(strict=True)` that pinned this and is now the regression for the last
hop, from the persisted record to the panel an owner reads.

### SYS-14 - nothing in the product ever said a safety mechanism was ABSENT - FIXED in repo 2026-08-29, unshipped

**Symptom.** Every panel in this dashboard reports what is WRONG. Nothing
reported what is NOT THERE, and a mechanism that does not exist produces no
errors, so its absence rendered as green everywhere. The live TrueNAS keeps
`dashboard.db`, `broll.db` and `music.db` under `/mnt/tank/apps`, which is a
plain directory and not a dataset: it cannot carry a periodic snapshot task
at all, and `setup_snapshots.py --apply` has never been run on either NAS
(CR-10, open). The fleet's projects, editors, ticks and client links have had
no point-in-time behind them since the day they existed, and every page in
the product looked healthy about it. `SYNC_SAFETY.md` said so in prose -
"there is no banner for 'this NAS has no snapshot schedule'. Until there is,
it is a runbook item, not a system property" - and the dashboard was one API
call away from knowing.

**Cause.** Absence has no writer. Every check in the product starts from a
thing that exists and asks whether it is healthy; nothing enumerated the
safety mechanisms the system depends on and asked whether each is present.
The same shape produced the two "could not ask rendered as fine" bugs the
sweep already paid for (`folder_errors` and the container healthcheck).

**Fix.** `dashboard/src/ccsync_dashboard/protection.py`: **a safety mechanism
this server cannot POSITIVELY VERIFY is reported as missing or as
unverifiable, never as silence.** Eight lines, each green only on evidence
this server actually holds: an enabled `pool.snapshottask` covering the tree
dataset; the same for the dashboard's own data (the CR-10 line); a last run
under 25 h (WPK-6: a schedule that stopped running looks identical to one
that works); `DASH_RELEASE_PUBKEYS` set, counted and never rendered; the
release key backed up, as an admin-set DATE; a restore drill inside a year,
as a date the dashboard reads rather than a boolean it computes, so the
sibling recovery package can record its own through
`protection.record_restore_drill`; server-side file versioning on every
project folder; and `.ccsync-trash` on editors' machines under its 50 GB
bound (the 14-day half of that rule is reported by no companion, and the line
says which half it checked).

THE TRI-STATE IS THE POINT, and it is `invariants.py`'s: this reuses its
`Outcome`, its four states and its constructors rather than growing a second
vocabulary, and it reads the snapshot schedule through ONE memoised probe
(`protection.nas_probe`) shared with `invariants._check_snapshot_schedule`,
so the two cannot disagree about what the NAS said at two different moments.
The panel chips are `[ PROTECTED ]`, `[ MISSING ]`, `[ CANNOT VERIFY ]` and
`[ COULD NOT RUN ]`. **AMBER FOREVER IS AN ACCEPTABLE ANSWER**: on a Synology
the snapshot lines read "cannot verify, confirm in DSM" for the life of the
deployment, because DSM's schedules live in a package with no supported API
and a green chip there would be a guess. An unset dataset name is
`[ CANNOT VERIFY ]` naming the environment variable, never "there is no
snapshot" - a question nobody asked is not an answer.

Wired into wave 4's machinery rather than beside it: two notice kinds
(`protection_missing` error, `protection_unverifiable` warn - a warn is said
once and not again until it clears, which is what makes DSM's permanent amber
honest rather than nagging), two rows in `alerts.ALERT_KINDS`, a standing
WHAT IS PROTECTED block in the weekly report printed every week whether or
not anything is wrong (a block that appeared only on bad weeks would make its
absence read as good news), and the panel at Settings -> PROTECTION rendered
in the shape of `partials/notice_checks.html`. It rides the `invariants`
collector kind, wrapped, so a protection pass that raised cannot cost the
fleet its invariant verdicts. Every external read is bounded and fails to
"cannot verify", never to an exception on a page or in the cycle. Nothing
here formats a secret: `DASH_RELEASE_PUBKEYS` is checked for PRESENCE and
counted.

**Schema.** None. v40 was reserved for this package and is deliberately
UNUSED: the last verdict per line and the two admin-set dates live in `meta`
(`protection_results`, `protection_acks`), the shape `META_ALERTS_OPEN` and
`NOTICE_CHECKS_META` already use. A migration every customer's database must
run, to add a table a JSON blob holds, is a migration not worth the number;
40 stays skipped rather than recycled.

**What it says about THIS NAS today.** Not green. With no
`DASH_TREE_DATASET` / `DASH_UPDATE_SNAPSHOT_DATASET` on the container the
three snapshot lines read `[ CANNOT VERIFY ]` naming the variables; set them
and, until `setup_snapshots.py --apply` is run, "this dashboard's own data is
on a snapshot schedule" reads `[ MISSING ]` with `tank/apps` named and the
sentence "the fleet's projects, editors, ticks and search indexes have no
point-in-time behind them". "Somebody has actually restored from a backup
this year" is `[ MISSING ]` on every deployment in existence, because nobody
ever has. **This closes CR-10's reporting half**: the operator work it names
(`--apply` on both NAS boxes, then `--list` within the hour) is still owed,
but from this build on the dashboard says so out loud on its own page, in its
notices and in every Monday report, instead of the ledger being the only
place the gap is written down.

**Tests.** `dashboard/tests/test_protection.py` (36): nothing is green on a
deployment that can prove nothing; a NAS that cannot be asked, one whose API
raises, and a Synology all render CANNOT VERIFY and never OK; a check that
raises becomes COULD NOT RUN; a disabled task is not a schedule and a
recursive parent task covers a child; the CR-10 missing-apps-dataset case is
reported by name; a schedule that stopped running is MISSING though the task
exists; both last-run shapes TrueNAS reports are read; a key is counted and
never rendered; a future or unreadable date is refused where it is typed; and
the panel, the notices, both alert kinds and the weekly report all carry it.

### SYS-15 - the owner cannot recover from anything without a root shell - FIXED in repo 2026-08-29, unshipped

**Symptom.** The owner deletes a project folder on the NAS by hand on a
Sunday. Every one of the five restore paths `docs/BACKUP_RESTORE.md`
documented is a root SSH session that asks him for judgements he has no way to
make: is `apps` a dataset or a plain directory (this decides which of two `cp`
lines is correct, and whether a snapshot of it exists at all - on this fleet's
own box it is a directory, CR-10); which snapshot; is everything written since
it expendable; has the fleet stopped writing; and - platform dependent and
destructive if wrong - `chown` is REQUIRED on TrueNAS and DELETES the share's
ACL on DSM. `zfs rollback -r` destroys later snapshots, guarded by a
parenthetical in a doc. The one self-service path in the whole document is
browsing `.stversions` over SMB, which never covers video originals: they have
no versioning at all, NAS-side. And the Resolve undo was a TRAY CLICK on the
editor's own machine with no admin route, unlike the lane B breaker, whose
blast radius is smaller and which got [ RESUME ] in CR-45.

**Cause.** Recovery was written as prose for a systems administrator, in a
product whose operator is not one. Nothing in the dashboard had ever performed
a restore, and nothing had ever verified that one would work.

**Fix.** A RECOVERY page (Settings -> RECOVERY, `/admin/recovery`), four
parts, in `dashboard/src/ccsync_dashboard/recovery.py`:

**(a) Snapshot browse-and-restore, into a quarantine folder.** Pick a project,
pick a snapshot, see exactly what is missing, and the dashboard copies it back
into `<project>/.restored-<ts>/`. **Nothing is overwritten, nothing is deleted
and nothing is chowned**, which is the whole point: the destructive judgement
("is everything since this snapshot expendable?") disappears, and a wrong
snapshot costs disk space and nothing else. The leading dot is load-bearing -
`provision`'s walk prunes dot-directories, so a restored copy of a project,
which carries a copy of that project's `.ccsync-project` marker, cannot be
discovered as a second project claiming the same slug. A destination that
already exists is refused, never merged. A pre-restore NAS snapshot is taken
best-effort first (`dashboard_update.snapshot_before`), because "snapshot
before anything privileged and recursive" applies to the restore path too.

**Snapshots are not visible from a container by default**: `/projects` is a
bind mount of the Projects directory and ZFS's `.zfs/snapshot` belongs to the
dataset above it, so the browse path is a read-only mount this deployment was
TOLD about (`DASH_SNAPSHOT_DIR`, plus `DASH_SNAPSHOT_PROJECTS_SUBPATH` for the
path from a snapshot root to the tree). Unset is "this server was never told",
never "there are no snapshots" - the same rule the protection panel's dataset
lines follow - and the page says so and falls back to printing commands.

**(b) An admin-side Resolve undo** on the command channel (schema v40):
`commands.resolve_undo` names a journal id, and the companion replays the SAME
journal through the SAME `resolve_bridge.undo_last_relink` the tray's own menu
item calls - one place in this product writes to a media pool, and this is not
a second one. Delivered on the report reply and kept riding every report until
the machine answers (`resolve_undo_applied`): the `file_moves` contract,
including `retrying`. An undo refused because Resolve is closed, or because
the change was made in a project that is not the one open, is going to work
later, and retiring the command there would leave the wrong paths in place
with the admin believing they had been put back. A week of retrying becomes a
failure. The companion reports what it holds (`resolve_journals`, names and
counts only, on heavy ticks) because there is no inbound connection to an
editor's PC and an admin cannot name a file they have no way to know about;
absent is not empty, so an older build does not blank the list.

**(c) A guided runbook that is a wizard, not prose.** It names what is
protected RIGHT NOW (the protection panel's own evidence, not a second opinion
about it), asks which of five things went wrong, and either performs the
recovery or prints the exact commands **with this customer's real pool name,
dataset and platform substituted in**. THE REFUSAL IS THE FEATURE: a step
whose facts this server could not VERIFY prints no command at all, only a
refusal naming what is missing and how to supply it. A dataset is verified
only when the NAS's own snapshot task list names it or a recursive parent of
it - deliberately a stronger bar than "somebody set the variable", because
`/mnt/tank/apps` being a plain directory is exactly the fact the two `cp`
lines in BACKUP_RESTORE.md 4c differ by. The platform is verified by a bounded
call to the NAS, because `chown` is required on one and destroys the share's
ACL on the other. A generated `zfs rollback` with a guessed dataset in it is
worse than no command at all.

**(d) A restore drill.** [ REHEARSE A RESTORE NOW ] copies one real file out
of the newest snapshot into a scratch folder under `/data`, compares it byte
for byte, deletes it and records the DATE through
`protection.record_restore_drill` - the same store the admin's button writes,
so the panel's line needs no edit and the two can never disagree. A drill that
FAILS records nothing there: that line reads a date meaning "a restore worked
here", and it must stay MISSING rather than turn green. A backup nobody has
restored from is a hypothesis, and until this button existed nothing in this
product had ever tried.

**Schema v40.** `resolve_undo_requests` plus `machine_state.resolve_journals`.
Wave 5's reservations ended up 39 invariants, 40 recovery, 41 unused: the
migration list has to stay gapless (test_db's ordering test), so the number the
protection panel reserved and then gave up was renumbered away rather than
left as a hole. The restore and the drill add no table at all - they write
files into a quarantine directory and a date into `meta`.

**What an owner can now do without a shell**: put back a deleted or overwritten
file or folder from any snapshot this dashboard can read; undo a clip-path
change CC Sync made on any computer in the fleet; roll this dashboard's own
databases back from its update backups; rehearse a restore and record that it
worked. **What still needs one**: a whole-tree `zfs rollback`, restoring
`dashboard.db` from a NAS snapshot when the in-app backups are gone too, and
any deployment that has not been given a snapshot mount. For each of those the
page prints the exact commands for THIS server, or refuses to and says which
fact it could not confirm.

**Tests.** `dashboard/tests/test_recovery.py` (24): a restore leaves every
pre-existing file byte-for-byte identical and writes only under `.restored-`;
the quarantine folder cannot become a second project; a snapshot, project,
tree mount or snapshot mount that cannot be identified is a refusal with a
sentence in it rather than a guess; the preview changes nothing; a drill
records a date the protection panel then reads as OK, leaves no scratch files
behind, and records nothing when it could not run; the runbook prints no `zfs
rollback` while the dataset is unverified, treats a dataset nothing snapshots
as unverified (CR-10), substitutes a verified one, prints nothing at all when
the NAS did not answer, and leaves no `{placeholder}` in any of the five
plans; and the page renders with no NAS and no snapshots at all.
`companion/tests/test_resolve_undo_command.py` (16): a journal id off the wire
never resolves outside `~/.ccsync/resolve_edits`; the replay is the bridge's
own; the wrong project open and a raising bridge are both `retrying`; a swept
journal is a failure rather than an eternal retry; and a redelivered command
is answered from the ledger rather than replayed.

## Approving a computer under its own name mints a phantom editor (CR-91, 2026-08-28)

### CR-91 - "one user, many devices" read as "assign a NEW username per device", and typing the machine name is the B16 unshare - FIXED in repo 2026-08-28 as dashboard 0.7.16, NOT YET DEPLOYED
**Seen** (owner, 2026-08-28): signed a second computer (`Razer`) into the
existing `alex` account; the Users page listed it under [ DEVICES AWAITING
APPROVAL ] with a free-text box headed `ASSIGN USERNAME` and, in the column
immediately to its left, `CURRENT NAME: Razer`. Reported as "to approve it you
need to assign a username, which creates a new user, thus making the point of
1 user - multiple devices pointless."

**Not what it looked like.** Approving does not create an account.
`api_admin_approve_device` only names the Syncthing device and calls
`db.record_known_editor`, an `INSERT OR IGNORE`; typing the OWNER's existing
username is a no-op on an editor who already exists, and one editor owning
several devices is the design - every device map in the system is keyed by
deviceID, never by name (`collector.py` `editor_devices` is `editor -> set()`,
and `machine_devices[(editor, machine)]` addresses the exact device), so two
Syncthing devices both labelled `alex` is correct, not a collision.

**The real defect** is that the panel invites the machine name, and the machine
name is the one answer that breaks the fleet. Being a KNOWN editor is exactly
what promotes a device from UNMAPPED to mapped in `db.resolve_editor_username`,
and `record_known_editor` is what makes a name known. So approving `Razer` as
`razer` mints an editor with no `selections` rows, and the next enforce cycle
computes `desired` without that device and unshares it from every folder it is
on. That is B16 - the failure the whole known-editors mechanism was built to
prevent - reached through the supported admin UI instead of a hand-edited
Syncthing config. `db.py:1036` already names the hazard ("machine names look
exactly like usernames"); nothing stopped the dialog from manufacturing the
knowledge that defeats it. The blast-radius brake catches this only for a
device on many folders; a device on one or two sails under the limit.

**Fix.** The column is `COMPUTER NAME`, the box is `OWNER (EDITOR)` backed by a
`<datalist>` of the editors the dashboard already knows, with the standing
sentence "One editor can own several computers, so a second machine takes the
SAME username as their first." Both approve paths - the htmx partial a human
uses and its JSON twin - refuse a username that is not already known unless
`create_new` is set, which is what [ CREATE NEW EDITOR ] sends. Picker and
guard share ONE definition, `api.approvable_editor_usernames`, so the page can
never offer a name the POST refuses; it is deliberately local-only (no NAS
call) so a backend blip cannot read as "this editor does not exist". The guard
runs AFTER the device-id shape check so a truncated paste still reports DASH-1.

**And the guessing is removed where it can be.** A companion self-reports
`machines.syncthing_device_id` as soon as it has a local Syncthing, normally
before an admin opens this page at all - so in the ordinary case the registry
already holds the answer the admin was being asked to guess.
`_pending_owner_hint` reads `db.machine_by_device_id` and the row arrives with
the owner already in the box, its real machine name in the COMPUTER NAME
column and a green [ REPORTED ] chip; approving is one click. A device the
registry has never seen (added by hand in the Syncthing GUI, or one that has
never reported) falls back to the datalist, which is the old behaviour minus
the free-text trap.

Tests: `dashboard/tests/test_admin_users.py` (refusal on the machine name, the
JSON twin, the second-computer-same-username case, the picker, and the
registry prefill).

## Settings, Sessions 500'd for three days on one hand-minted row (CR-89, 2026-08-27)

### CR-89 - `ago` refused a timestamp with no offset, and the 2026-08-24 ship left one behind - LIVE-FIXED on the NAS 2026-08-27 (row deleted), filter hardened and SHIPPED 2026-08-28 in dashboard 0.7.15
**Seen** while reading the container log after the 0.7.14 OTA: thirteen
`TypeError: can't subtract offset-naive and offset-aware datetimes` in
`partial_admin_sessions`, all before the update. Cause: the 2026-08-24 ship's
minted admin session (`operator ship 2026-08-24 (shared folders)`, written
with `2026-08-24 03:16:18`, no offset) was never deleted, and `ui.ago`
subtracted it from an aware now. Every render of the Sessions page 500'd for
whoever opened it - and the row was a standing admin credential.

**Fix.** Row deleted on the live DB (no other naive rows). `ui.ago` reads a
naive timestamp as UTC instead of raising: a template filter on the pages
that tell the fleet whether footage is syncing must never be the reason a
page does not render. Every scripted admin session since (ota.py,
companions.py) writes `+00:00` stamps and deletes its row in a `finally`.
Test: `dashboard/tests/test_ui_filters.py`.

## The tray menu is ten items, Settings is a window, and the role belongs to the computer (CR-88, 2026-08-27)

### CR-88 - "why does it think Razer is wired?": the role came from the PERSON (admin = base), and the right-click menu had grown to forty lines - BUILT in repo 2026-08-27/28 as companion 0.9.54, NOT YET SHIPPED
**Seen** (owner, 2026-08-27): the Assignments grid marked the owner's Razer
laptop `wired`, so it could not be given a sync plan. `/verify` answered
`role: base` for any ADMIN username (`api.py:1493`) and `effective_mode()`
took that role as the machine's mode - so every computer the admin signed
into became a base rig (`MULTI_BASE_RIG_PLAN.md` WP1, the unbuilt half of
"the role belongs to the computer").

**Fix, role.** `effective_mode()` reads config `mode` only; `identity.role`
is diagnostics and no longer gates sync (`_apply_identity_role` sets
`_sync_enabled` from config alone; the base rig's own `mode = "base"` still
turns its lanes off through MODE_PROFILES). The dashboard still sends the
admin-derived role for older builds; 0.9.54 ignores it. The switch is in the
new Settings window, THIS COMPUTER: `[ REMOTE EDITOR ]` /
`[ WIRED TO THE SERVER ]` writes `mode` with `config.set_value` (line-level
TOML patch, comments kept); WIRED needs no confirmation, REMOTE on a machine
that says base needs the typed word `REMOTE` (AUDIT_2 CORE-C1: a wired rig
switched to remote starts deleting lane B passes against the live share);
takes effect on restart, `[ RESTART CCSYNC NOW ]` offered
(`upgrade.restart_self`, gated by the stand-down test).

**Fix, menu** (owner-approved layout, 2026-08-27): identity line (plus the
sign-in prompt when signed out); ONE bracketed conditional block (NOT SET
UP, licence, set up project, stray LUTs, resume proxy download, start
syncing again, update offer); `Sync: <state>` (new `_sync_line`: halted /
proxy download stopped / not set up / paused / uploading N files · X MB/s /
N files waiting / up to date) and `Resolve: connected`; `Sync now`, Pause /
Resume, `Open my sync drive` (was "Open my project folder", which opened
local_root and never a project), `Open dashboard`, `Settings…`; Quit.
Everything else moved into `settings_window.py` (red CLI style, scrollable,
takes the popup lock, refreshes every 2 s; sections THIS COMPUTER, SYNC
LANES, YOUTUBE, ADVANCED, HELP; every button closes the window and releases
the lock before spawning its action, so two Tk roots never run). Menu
actions are module-level `action_*(app)` functions shared by both.

Tests: `tests/test_tray.py` (reduced shape, conditional block, `_sync_line`),
`tests/test_settings_window.py` (model builder, role switch),
`tests/test_role.py` (rewritten), `tests/test_config.py` (`set_value`).

## A file moved on the NAS by hand comes straight back (CR-87, 2026-08-27)

### CR-87 - lane A re-uploads whatever an admin moves on the server, from every machine still holding it at the old path - BUILT in repo 2026-08-27 as dashboard 0.7.14 (schema v29) + companion 0.9.54, NOT YET SHIPPED
**Seen** (owner, 2026-08-27): leso dropped a card into `2026/Base Drone/B-roll`
and it uploaded; the owner moved the files on the NAS to
`2026/FF5/Animals/Interviewees/Pangolin/臺北動物園`; the next lane A pass on
leso's machine uploaded them into `Base Drone/B-roll` again. Not a defect
in lane A: it is `rclone copy --ignore-existing`, one way, never deletes,
never mirrors a removal (`SYNC_SAFETY.md` §5), so a server-side move is
indistinguishable from "new footage the server lacks". Every machine
holding a copy repeats it after every move, for as long as its copy stays.

**Fix.** The move is made through the dashboard and happens on BOTH ends
(`docs/FILE_MOVES.md`). Project page, admins only: `MOVE: <path> to
<project> / <folder> [ MOVE ON THE SERVER AND ON EVERY MACHINE ]`.
`api.move_project_files` renames the file or folder inside the mounted
Projects tree (a file's `Proxy/<stem>.*` goes with it), refuses a
destination that exists, a folder into itself, a `Proxy` folder as either
end, the marker, or anything escaping the tree; records it (`file_moves` +
one `file_move_targets` row per computer that syncs the source project in
either mode, or reported holding the file); and delivers
`commands.file_moves` in every report reply until the machine answers
(`file_moves_applied`; seven-day delivery window). The companion
(`file_moves.py`, `app._apply_file_moves`) moves its copy the same way,
proxies with it, repoints every media pool clip on the old path through
`replace_clip` (save point + journal), answers with the outcome, and keeps
the old path out of lane A for 24 h (`FileMoveLedger.recent_excludes`,
wired into lane A's filter) whether the move succeeded or was refused -
which is what closes the race with a pass that runs before the command
lands. Nothing in the path deletes; a refused move leaves the file where it
was and says why on the project page, per computer.

**Not done, on purpose:** detecting a move made in Explorer on the NAS
(rename-plus-copy and same-size same-name cards would be misread); moving
on a machine with only the destination ticked (nothing there to move).
Companions < 0.9.54 ignore the command and keep re-uploading: deploy the
dashboard, then push the companion.

Tests: `dashboard/tests/test_file_moves.py`, `companion/tests/test_file_moves.py`.

## Lane A can sit in `syncing` forever, silently, and starve lane B (CR-91, 2026-08-28) - OPEN

**2026-08-28, later the same day: the mechanism was verified and closed by
the resilience sweep's wave 2** (`SYNC-1 / SYS-17`, `SYS-1`, `SYNC-2` in the
"Resilience sweep, wave 2" section): `_run_popen`'s `proc.wait()` and the
sequencer's lane B `thread.join()` were both unbounded and `--max-duration`
is SOFT, so a local read blocked in the kernel held `_run_lock` forever.
Now the companion kills an rclone that has moved nothing for
max(4 x budget, 15 min) and reports `sync_guard.stalled`, the root guard can
answer `not_answering` from an out-of-process probe, and the DASHBOARD turns
the lane RED from a per-lane progress token after three rotations with no
movement, on the reasoning that the wedged thread is the wrong one to ask.
Unshipped; the entry below is kept as the incident record.

### CR-91 - a lane that never finishes and never errors looks exactly like a lane that is working
**Seen on leso's MacBook 2026-08-28**, straight after its 0.9.2 -> 0.9.54
hand-upgrade. Over 2 h 20 m the machine kept reporting (`machine_state.reported_at`
advanced 20:12 -> 20:29 -> 20:57 -> 21:16 -> 21:34 -> 21:50), and across every one
of those reports:

```
lane_a_video_up   state=syncing  transferring=1  last_sync=NULL  last_error=NULL
lane_b_proxy_down state=idle     transferring=0  last_sync=NULL  last_error=NULL
```

Nothing was actually moving. No SFTP session from that machine existed on the
NAS at any point; nothing under `Projects/` changed mtime for 150 minutes; and
`current_project` was `2026-ff5-animals`, a project where that machine holds
**0 originals** - so lane A had nothing to upload in the first place. Its
disk-manifest half stopped too: `editor_media_project.reported_at` froze at
19:00:42, before the upgrade, while the light reports kept flowing.

**Most likely cause, not confirmed** (the machine refused SSH throughout, so
this is inference from the reports): the external SSD. Its first 0.9.54 boot
logged MAC-12 verbatim - `the sync drive's filesystem is not answering -- a
separate test process could not open /Volumes/SAMDISK/Creators_Club (no answer
within 5s)`. A blocked read there would hang the lane A pass AND the manifest
walk while leaving the reporter thread free, which is exactly the shape
observed. The documented remedy is the editor's: reconnect the drive or
restart the machine.

**What is a defect regardless of that cause.** A lane that has been `syncing`
for hours with no bytes and no error is indistinguishable, on the fleet page,
from a lane that is working - and because the sequencer gives lane A its turn
first, lane B never runs, so the editor silently downloads NOTHING for as long
as it lasts. This is the same family as the lane B breaker (`docs/SYNC_SAFETY.md`)
and CR-86's silent identity stop: the failure is invisible exactly where the
fleet page is supposed to be the thing that tells you.

Wanted: a per-pass watchdog - a lane in `syncing` past some multiple of its
normal pass time with zero bytes transferred reports a state the grid can show
(and the sequencer moves on to the next lane rather than waiting on it
forever). Design it so a genuinely slow single large file over a thin uplink is
not mistaken for a hang: bytes moved, not wall clock, is the test.

## A Mac is permanently behind on files it already holds (CR-90, 2026-08-28)

### CR-90 - the lane A/B backlog diffs macOS's decomposed filenames against the NAS's composed ones - FIXED and SHIPPED 2026-08-28 as dashboard 0.7.15 (OTA, runtime 869eed1052a8..., live 17:57Z)
**Symptom** (owner, 2026-08-28): "why is leso queued but not moving anything".
The fleet page showed `leso liaoshaoxuandeMacBook-Pro.local - 2026/FF5/Animals
: 12 file(s) - 2.9 GB [proxies]` under LIVE TRANSFERS - "nothing transferring
right now" - and had done for a day.

Everything about the machine was healthy. It had reported 25 s earlier; all
three lanes `idle`, no `last_error`, breaker not tripped, no halt; and lane B's
last pass said `transferred 0 file(s)`. rclone was right: **all 12 files were
already on the disk, byte for byte.**

**Cause.** macOS hands filenames back DECOMPOSED (NFD). The NAS inventory walk
and every Windows machine spell the same name COMPOSED (NFC).
`db.fetch_sync_backlog` is a rel_path diff of `nas_media` against
`editor_media` done as an exact string comparison in SQL, so the two spellings
never matched:

```
nas_media     Interviewees/Pangolin/Matej Šimalčík/Proxy/A002_07161726_C048.mp4
editor_media  Interviewees/Pangolin/Matej Šimalčík/Proxy/A002_07161726_C048.mp4
              (S+U+030C, c+U+030C, i+U+0301)          same size: 1431853821
```

All 12 rows had a diacritic somewhere in the path - 9 under `Matej Šimalčík`,
3 under `Youtube/pangolins in prague` (`Taiwán`, `Mašek`, `китайский`). The CJK
folders beside them (`臺北動物園`, `民視新聞網`) matched perfectly, because those
characters have no decomposed form. That is what made it read as a partial
sync rather than as a comparison bug, and it is why nobody looked at it for a
day: 9 of 10 things about the machine said "fine", and the tenth said "12
files short" in the one place the fleet trusts.

There is no clearing state: lane B fetches nothing (correctly), so the
manifest never changes, so the phantom row is permanent. The diff is
symmetric, so the same mismatch could invent lane A **uploads** that never
complete either.

**Fix.** `db.media_rel_key()` - `unicodedata.normalize("NFC", ...)` - applied
at the two write chokepoints, `replace_editor_media` and `replace_nas_media`.
Normalising on the way IN rather than in the SQL is safe for these two tables
*specifically*: neither table's `rel_path` ever drives a filesystem
operation - they feed the backlog diff, the rollup counts and the name list a
human reads. Anything that opens, renames or deletes a path must keep using
the bytes on disk (`file_moves` keeps its own copy for exactly this reason).
`api.build_transfers_view`'s in-flight subtraction folds both sides too: rclone
names a file the way the Mac's filesystem spells it, so an accented clip
mid-download would otherwise count as transferring AND as queued.

**It heals itself.** `editor_media` is replaced wholesale on every heavy
report (~5 min), so the phantom rows clear on the machine's next report after
the deploy - no migration, no companion build. `nas_media` was already NFC and
is rewritten when the tree signature changes.

Measured on the live DB after the deploy: **12 of 11,447 `editor_media` rows
were non-NFC, all 12 leso/2026-ff5-animals; 0 of 14,159 `nas_media` rows**.
Since that machine is a laptop and was asleep, those 12 were folded in place
rather than waited for (`UPDATE editor_media SET rel_path = NFC(rel_path)`,
with a delete-the-duplicate arm for a key clash that did not occur), and the
backlog query then returned 0. A fresh pre-0.7.15 database backup existed from
the deploy itself.

**Related but not this.** `links.normalise_declared` (2026-08-18) carries the
comment "the NAS, Windows and macOS all serve these names in NFC". The first
two are true; the third is not, and this is the bug that proves it. That
function already normalises, so it is correct code behind a wrong reason.

**Also seen while diagnosing this, not caused by it:** `ruskin
DESKTOP-LQQ41TC`'s three queued rows (460 files / 13.8 GB) are the last known
state of a machine that last reported **2026-08-25 15:37Z** - offline, not
stuck. And leso's machine is on companion **0.9.2** with `machine_id` and
`syncthing_device_id` both NULL, so it predates `commands.upgrade` (0.9.3) and
the dashboard's [ UPDATE NOW ] push cannot reach it.

Tests: `dashboard/tests/test_unicode_paths.py` (6, using the real NFC/NFD pair
off the NAS and off that MacBook: the held file is not queued, a genuinely
missing one still is, the upload direction too, both tables store the composed
spelling, and a file mid-download is not double-counted).

## Companion sign-ins no longer expire (CR-86, 2026-08-27)

### CR-86 - a 30-day identity token stopped an editor's sync for two days and nobody could see it - FIXED in repo 2026-08-27, unshipped
**Symptom** (owner, 2026-08-27): "check why his ccsync hasn't reported in
ages". The remote editor's machine had been absent from the fleet grid since
**2026-08-25 23:38**. Everything on it looked healthy - companion running
(v0.9.47), tray up, config loading, the NAS reachable - and the log said the
same line every 60 s for two days:

```
2026-08-25 23:38:43  DEBUG   ccsync.reporter: dashboard report skipped: no verified editor identity
2026-08-25 23:39:15  WARNING ccsync.app: identity token is no longer valid -- sign in again
```

His `~/.ccsync/identity.json` was minted 2026-07-26 23:38 and stamped
`1787672311` = 2026-08-25 23:38:31. Exactly 30 days, exactly the first skip.

**It was not just reporting.** `_identity_watch_loop` calls `_stop_lanes()` on
that transition, so lanes A/B/C stopped with it: not one `ccsync.sync.*`
INFO/WARNING line exists in any of his logs after that timestamp. The only
notice was one tray balloon, on a machine that renders unattended, 23:39 on a
Tuesday night. This is trust-model-1's second consequence arriving in the
field verbatim ("every editor in every fleet has their sync silently STOP once
a month ... on an unattended render rig that is a lost weekend"), deferred by
decision as CR-66 on 2026-08-21.

**Decision** (owner, 2026-08-27): "let's just get rid of expiring login on
companions, not needed". A machine identity is not a browser session. It
answers WHICH machine this is, it changes only when the editor signs in as
somebody else, and there is no human at the keyboard when it lapses.

**Fix.** `auth.IDENTITY_TTL_SECONDS` 30 days -> 100 years. Kept as a TTL
rather than a "never" sentinel on purpose: the five-field wire shape
(`v2.identity.<user_b64url>.<expires_epoch>.<hexsig>`) is what every deployed
companion parses, so **a build already in the field accepts the new token with
no upgrade** - which matters, because the editor has to sign in once more
anyway (his old token really is expired and `read_identity_token` still
rejects it). Session cookies are untouched: there a human can just sign in
again.

The companion keeps honouring the expiry field - `is_valid` is unchanged, and
so is the lane stop behind it. Post-CR-86 tokens never trip it; pre-CR-86
tokens still do, and a machine whose clock is years fast must still stop
calling itself verified rather than post reports the server will 401. What did
change is the diagnostics line, which would otherwise read `876000.0h from
now`: `identity.NON_EXPIRING_AFTER_SECONDS` (10 years) is the display-only bar
that makes it print `never (non-expiring token; nominal <date>)`, and a
pre-CR-86 token still prints its date, because "when did it expire" is the
question that panel gets read for.

**The trade this accepts.** trust-model-1's other half - identity tokens are
unrevocable bearers with no server-side row - is now unbounded rather than
bounded at 30 days. It was always the weaker bound of the two: `/report` needs
a report token as well, and that IS revoked by disable/delete
(`_purge_user_credentials`, CR-56), so the way to take an editor's access away
has not changed. But on a site that still has the shared fleet token enabled
(`DASH_SHARED_REPORT_TOKEN_ENABLED=1`, the default), a departed editor's
credential no longer ages out at all. The real fix stays trust-model-1's:
a row per identity token, revoked by disable/delete, and retiring the shared
token. Recorded here, not fixed here.

Tests: `dashboard/tests/test_auth.py` (a minted token is >50 years out and
still reads back 40 years later; the expired-token 401 arm now mints its
pre-CR-86 token through `_make_token` with an explicit 30-day ttl),
`companion/tests/test_identity.py` (a century-out token is valid, today and
in 40 years), `companion/tests/test_app.py` (the diagnostics line says
`never` for one and a date for the other). Companion suite green (436 in the
three touched files), dashboard `test_auth.py` 35 green. Needs a dashboard
deploy; needs no companion build, though the diagnostics polish rides the
next one.

## The upload-only tick (CR-85, 2026-08-27)

### CR-85 - a tick could only mean "everything, both ways"; an editor with the footage already on their disk had no way to send the originals without the whole project coming down - BUILT in repo 2026-08-27 as dashboard 0.7.14 (schema v28) + companion 0.9.54, NOT YET SHIPPED
**Ask** (owner, 2026-08-27): "add an upload only tick for editors who have
backed up footage locally and want to upload originals to the server but
don't want to sync all the other project files down."

**Fix.** A tick carries a mode, `full` or `upload_only`
(`selections.sync_mode`, v28, default `full` so an upgraded dashboard changes
nothing for an existing fleet). Upload-only is **lane A alone**: the
companion skips lane B for the project and never takes a lane C turn, and
the enforce cycle never shares the Syncthing folder with that machine -
deliberately "no share" rather than a `sendonly` folder, which would exist,
index, and read as permanently out of sync on every page that draws
completion. Controls: `[ UPLOAD ONLY FOR ME ]` / `[ SWITCH TO FULL SYNC ]` on
the project page (a SET, never an untick), an `up` box in every Assignments
cell, `?mode=` on `PUT /api/v1/selection/{editor}/{slug}` (unknown mode 400,
never read as full). The lane A/B backlog lists uploads only for it; its
GETTING READY row clears on the machine's first manifest, not on a
completion row it will never have (the CR-28 shape, avoided). The tray's
"Remove from this machine" gate asks the lane A question only. A companion
reading an UNKNOWN mode syncs the project not at all (fail closed, logged).
Design, limits and the deploy order in `docs/UPLOAD_ONLY_TICK.md`.

**Known limits, decided for now.** Only video originals go up (lane A's
filter is unchanged; separate-recorder audio would need the filter widened,
owner's call). An old companion (< 0.9.54) runs lanes A and B for it -
originals up, proxies down, still no lane C. Deploy the dashboard before
the companions.

Tests: `dashboard/tests/test_upload_only.py`,
`companion/tests/test_upload_only.py`, `companion/tests/test_sync_halt.py`.

## Companion: the clip walk reads Resolve's project library instead of holding the scripting API for 11-14 s (CR-81, CR-82, 2026-08-26)

### CR-81 - the watcher's clip walk stalls every other Resolve client on the machine, and is blind to multicam angles - FIXED in repo 2026-08-26, NOT YET SHIPPED
**Symptom** (owner, base rig, 2026-08-26): clicking a card in Timeline Cards
took **7 s** instead of its usual **0.3 s**, in bursts, on a machine where
nothing else had changed. Resolve itself felt fine.

**Measured** (Resolve 21.0.1.11, project "Civil Defence", timeline
"Civil Defence - E1", 904-926 items, library "FF5" on the fleet's
postgres:13):

- `resolve_bridge.get_timeline_items()` took **11-14 s** per walk (32-95 s on
  a bad evening, per this companion's own "inside Resolve for Ns" warnings),
  and ran every 10th poll plus after every edit that changed an item count.
  Resolve serves scripting calls **one at a time**, so the entire duration is
  time every other client on the machine spends queued. Full timing in
  `E:\Projects\Editing\Resolve\MulticamPipeline\LAG-INVESTIGATION.md`.
- The cost was `MediaPoolItem.GetClipProperty()` with **no argument**, which
  builds and formats a 60-key dictionary: **12.5 ms** a clip, against 0.1 ms
  for `GetClipProperty("File Path")`. The two agreed on all 1,298 clips of
  the open project and on every clip kind (BRAW, R3D, ProRes, PNG sequence,
  multicam, compound), so the dict was buying nothing but time.
- Worse, the walk was **blind**. It found **0-3 usable file paths out of
  904**: every item on that timeline is a multicam, a multicam answers `""`
  to `GetClipProperty("File Path")`, and the API exposes nothing at all about
  its angles. So the popup, the fixer and Scan whole project could not see
  the offline media that was actually there. Read out of the project library
  the same timeline yields all **44** angle clips.
- The media pool walk had the same shape: **20.0 s** through the API against
  **31 ms** out of the library, 1,298 / 1,298 paths and bin paths identical.

**Fix** (branch `library-walk`, merged at 029db90; plan and interface
contract in `docs/LIBRARY_WALK_PLAN.md`, traps in `docs/GOTCHAS.md` section
16):

- `companion/src/ccsync_companion/library.py` (new): `locate()` (the API
  first, then Resolve's log, config overrides winning over both) and
  `ProjectLibrary` with `timeline_items` / `pool_items` / `pool_paths` /
  `changed` / `close`. `pg8000` (BSD, pure Python, no LGPL entry in the
  licence gate and no compiled wheel per platform) for PostgreSQL libraries,
  stdlib `sqlite3` for disk libraries, `zstandard` for the `Clip` blobs.
  Read-only: every statement is a SELECT. 5 s connect and statement timeouts,
  and every public method raises only `LibraryUnavailable`.
- `resolve_bridge.py`: `get_timeline_items` / `poll_timeline_items` /
  `get_media_pool_items` read the library first and fall back to the API walk
  on ANY failure, with the item dicts unchanged in shape and a new `source`
  key saying which. Database reads happen with `_API_LOCK` released; lock
  order is `_LIBRARY_LOCK` then `_API_LOCK`. The API walk itself now uses the
  one-argument `GetClipProperty`, which takes it from 11 s to under 1 s for
  the machines that will always fall back.
- `media_pool_item_by_uid()` / `resolve_media_pool_item()`: a library-walked
  item carries `media_pool_uid` (`Sm2MpMedia_id` **is**
  `MediaPoolItem.GetUniqueId()`) and no object, so every native call site
  (`app._handle_non_canonical`, `popup`, `fixer`, `consolidate`,
  `proxy_relink`, the undo replay) re-finds the live object on demand:
  ~0.15 s for 1,318 clips, and only when there is something to fix.
- Config: `library_walk` (default true), `library_db_host` / `_port` /
  `_name` / `_user` / `_password`, documented in `config.example.toml` and
  pushed into the bridge by `app.py`. `library_walk = false` restores the old
  behaviour exactly.
- Packaging: `pg8000` and `zstandard` in `companion/pyproject.toml`,
  `requirements.lock`, `build.spec` hidden imports, and
  `docs/legal/THIRD_PARTY_NOTICES.md`.

Tests: `companion/tests/test_library.py` (a SQLite fixture built with the
live schema's exact mixed-case quoted column names, and `Clip` blobs that are
real Resolve framing around real zstd + protobuf; the postgres dialect; the
malformed-uid refusal; the closed-on-failure backend), the library-first walk,
fallback and backoff tests in the bridge suite, and the uid-only call-site
tests. `tools/library_walk_check.py` is the live check: library versus API for
the open project, read-only, `scriptapp()` guarded through
`script_server.state()` (CR-68), exit 1 on any disagreement.

**Shipping checklist** (nothing of this has reached an editor yet):

1. On a Mac, `uv pip install -r requirements.lock` once **before** the release
   build, to confirm the arm64 wheel hashes for `pg8000` and `zstandard`
   resolve. The lock was generated on Windows; a missing arm64 hash fails the
   macOS build, not the Windows one, and it fails late.
2. Ask a Mac editor what the log line
   `resolve: reading clips from the project library ...` reports, and which
   spelling the library's own paths come back in - the stored canonical
   `P:\Projects\...` or the Mapped-Mount-resolved local path.
   `docs/LIBRARY_WALK_PLAN.md` open question 4; `classify_path` wants the
   stored string, and this is the only question the whole design leaves open.
3. Then the normal path: bump, build, `publish_latest --make-current`, base
   rig first, watch for the `library walk unavailable` WARNING in the fleet's
   logs.

### CR-82 - "pystray is still in the frozen exe" - NOT A BUG, refuted 2026-08-26
**Worry** (raised during the library-walk review, and it has been raised
before): the LGPLv3 removal of CR-3 was incomplete and `pystray` is still
being collected into the single-file build, or still listed in the notices.

**Refuted, on the files:**

- `companion/build.spec` does not collect it and says so at the top of the
  file ("pystray USED to be collected here too and deliberately is not any
  more (2026-08-17, docs/COMMERCIAL_READINESS.md item 3)"), with the reason
  attached: a single-file PyInstaller freeze conveys it with no way for the
  recipient to relink against a modified copy, which is what LGPL section 4
  requires.
- `companion/pyproject.toml` does not depend on it. `pyobjc-framework-Cocoa`
  is pinned there in its own right, which is what used to arrive through it.
- `tray.py`'s backend is `tray_native.py` (ours, ctypes on Windows and PyObjC
  on macOS). `CCSYNC_TRAY_BACKEND=pystray` is a dev-machine affordance for
  somebody who installs pystray by hand and is **inert in a frozen build**.
- `docs/legal/THIRD_PARTY_NOTICES.md` is generated by `tools/gen_notices.py`,
  which scans the **installed venv** with pip-licenses rather than a
  hand-kept list. A package that is not installed cannot appear in the table,
  and a package that is installed cannot be forgotten. pystray's LGPLv3 is
  how `has_license_text()` came to exist in the first place.

Recorded so the next reader does not spend an afternoon on it. If it ever
does come back, the thing that would catch it is the licence gate
(`tools/check_licenses.py`) on the build machine, not a reading of the spec.
## Every server YouTube download failed "The page needs to be reloaded" (CR-80, 2026-08-26)

### CR-80 - the signed-in cookie jar got flagged, and yt-dlp 2026.07.04 had no anonymous path left - LIVE-FIXED on the NAS + floor raised in repo, 2026-08-26

**Symptom** (owner, 2026-08-26): the downloads panel on job 28 sitting at
"0/29 downloaded - 5 failed", and by the end all 29 of the job's remaining
clips failed. Every one of them carried the same `dl_error`:

    ERROR: [youtube] <video id>: The page needs to be reloaded.

The same job had already downloaded 36 clips successfully. The flag arrived
mid-job, and afterwards even those 36 failed when retried.

**Mechanism, two halves that had to be fixed together.**

1. *The cookies.* `YTDL_COOKIES_FILE` pointed at a signed-in `cookies.txt`
   (the escape hatch `ytdl/web/DEPLOY.md` has called MANDATORY since the
   2026-08-11 bot-check). YouTube decided it did not like that session: with
   the cookies attached, the `tv` client came back downgraded
   (`tv_downgraded player response playability status: UNPLAYABLE`) and
   `web_safari`'s https formats were SABR-forced away, leaving storyboards and
   nothing else. Measured live against six video ids, every `player_client`
   (`tv_simply`, `web`, `mweb`, `web_safari`, `android_vr`, `ios`,
   `web_embedded`): no media formats at all. The cookies were NOT expired -
   the subscriptions feed listed fine with them - so `/api/health`'s
   `cookies: true` is not evidence downloads work. It is a playback flag on
   the account, not an auth failure, and the container cannot "reload a page".

2. *The yt-dlp version.* Dropping the cookies did not fix it on the installed
   yt-dlp 2026.07.04: anonymously the only client that still produced URLs was
   `android_vr`, and its media fetch 403'd (the CR-39 shape). 2026.8.19 adds
   the `visionos` client, which returns real https formats anonymously - and
   the bot check that made cookies necessary on 2026-08-11 is answered by the
   `bgutil` PO-token sidecar that has been running since CR-73.

   Measured on the same clip, in the live container:

   | yt-dlp | cookies | result |
   |---|---|---|
   | 2026.07.04 | yes | `The page needs to be reloaded.` |
   | 2026.07.04 | no | formats found, then `HTTP Error 403: Forbidden` |
   | 2026.8.19 | yes | `The page needs to be reloaded.` |
   | **2026.8.19** | **no** | **1080p, ~20 MiB/s** |

**Fix applied live on the NAS** (2026-08-26, container
`ix-ccsync-dashboard-dashboard-1`):

- `docker exec -u 0 <c> /venv/bin/pip install --no-cache-dir --upgrade
  yt-dlp==2026.8.19`
- the flagged jar copied to `/ytdl-data/cookies.txt.bak-20260826-flagged` and
  `/ytdl-data/cookies.txt` truncated to its two Netscape header lines.
  `YTDL_COOKIES_FILE` stays set: an empty jar loads cleanly, yt-dlp writes its
  own anonymous cookies back into it, and the escape hatch survives.
- `docker restart`, then the REAL production path verified in-container -
  `ytdlweb.vendor.downloader.download(..., quality="1080p",
  ffmpeg_location=config.FFMPEG_DIR)` returned a merged mp4 in 16.4 s for a
  10-minute clip.

**In repo**: the yt-dlp floor raised to `>=2026.8.19` in
`ytdl/web/pyproject.toml` and `dashboard/pyproject.toml`, both
`requirements.lock` files re-pinned to 2026.8.19 with its PyPI hashes, and
`ytdl/web/DEPLOY.md` given a "2026-08-26 REVERSAL" block ahead of the
"cookies are MANDATORY" section so the next reader does not restore a
signed-in export on the strength of a measurement that has since inverted.

**RESIDUAL**, same shape as CR-73's: `/venv` is the image's, so a dashboard
IMAGE update (not an OTA exit-75 restart) puts 2026.07.04 back until a build
carries the new lock. Diagnosis is one line -
`docker exec <c> /venv/bin/python -c "import yt_dlp;print(yt_dlp.version.__version__)"`.

**AND IT DID, THE SAME DAY - CR-84.** "A build carries the new lock" meant
`dashboard/deploy/requirements.lock`, and this entry's fix did not touch it:
**there are THREE yt-dlp locks in this repo** (`dashboard/requirements.lock`,
`ytdl/web/requirements.lock`, `dashboard/deploy/requirements.lock`) and the
deploy one is the ONLY one the vendor image installs. The v0.7.11 image
shipped 2026.07.04 straight back onto the live NAS. Fixed in the lock, and
pinned by `test_deploy_locks_satisfy_their_own_floor_files`.
And "YouTube flagged the account" is not a state we control: if anonymous
downloads start failing the bot check again, the answer is a FRESH cookie
export, tested BOTH ways before it is left in place, not the old one.

**Job 28 was re-requested and completed the same day**: 29 of 29 downloaded,
zero failures, 8.8 GiB in the term folder with no leftover `.part` files. The
retry went through the ordinary `POST /ytdl/api/jobs/28/download`, which
re-queues exactly the failed rows on a `done` job (YTDL-16).

**THE FLEET HALF OF THIS IS CR-83, FIXED IN REPO 2026-08-26 AND NOT YET
SHIPPED.** The editors' companions were broken the same way and the NAS fix
does not touch them: they were pinned to yt-dlp 2026.07.04 by
`config.DEFAULT_MIN_YTDLP_VERSION`, their
`ytdl_executor.DEFAULT_PLAYER_CLIENT = "web_safari"` returns no usable formats
on either version, and their own cookie jars hit the same account flag.
Measured on the base rig 2026-08-26. `docs/YTDL_RESILIENCE_PLAN.md` is the
write-up and the work-package numbering; CR-83 below is what was built against
it (dashboard 0.7.11 / companion 0.9.52), and until the dashboard ships,
`YTDL_MIN_YTDLP_VERSION=2026.08.19` on the live container moves the fleet
sooner.

## Every editor's machine was broken the same way, and could not tell anyone (CR-83, 2026-08-26)

### CR-83 - the fleet half of CR-80: a yt-dlp floor of 2026.07.04, a pinned `web_safari`, an unconditional cookie jar, and a classifier blind to the phrase - FIXED and SHIPPED 2026-08-26: dashboard 0.7.11 then 0.7.12 (image mode, tags v0.7.11 / v0.7.12), companion 0.9.52 current on windows + macos in the studio channel, base rig upgraded and its tray logged `updated yt-dlp 2026.07.04 -> 2026.08.19`

**Symptom**: nothing. That is the bug. CR-80 was found because the NAS's
downloads panel showed 29 failures on one job; the editors' machines had been
failing the same way, for roughly as long, and produced no report at all - a
claimed job that fails hands its clips back to the server, the server
downloads them, and the editor sees a slower download rather than a broken
one. `YTDL_LOCAL_DOWNLOAD=1` is on fleet-wide, so this was every local job.
Job 28 only ever reached the NAS because its `download_mode` was `server`.

**Measured on the base rig, 2026-08-26**, against the DEPLOYED companion's own
yt-dlp (`%LOCALAPPDATA%\ccsync\tools\yt-dlp.exe`, 2026.07.04) and its own jar
(`~/.ccsync/youtube-cookies.txt`), on a residential IP:

| companion config | result |
|---|---|
| `web_safari` (its pinned default), anonymous | no usable formats |
| `web_safari`, with its cookies | no usable formats |
| default client, with its cookies | "The page needs to be reloaded." |
| default client, anonymous | formats found, then HTTP 403 |
| **2026.8.19, default client, anonymous** | **works** |

**Mechanism, four independent halves.**

1. *The fleet was pinned to a dead yt-dlp.* `ytdlp_manager` updates the
   companion's binary only when it is below the floor the dashboard serves,
   and that floor is `config.DEFAULT_MIN_YTDLP_VERSION` - `2026.07.04`, with
   `YTDL_MIN_YTDLP_VERSION` **unset** in the live container. So every
   companion in the fleet compared 2026.07.04 against 2026.07.04, concluded
   "current", and stayed on the one version with no working anonymous path
   left. The base rig's log said exactly that, nightly:
   `ytdlp: yt-dlp 2026.07.04 is current`.
2. *A pinned player client is a pinned bug.* CR-39 (2026-08-19) pinned
   `ytdl_executor.DEFAULT_PLAYER_CLIENT = "web_safari"` because it was the one
   client that worked on an editor's machine without a GVS PO-token provider.
   Six weeks later YouTube SABR-forced its https formats away and it returns
   no usable formats at all, on either yt-dlp, with or without cookies.
3. *The jar was unconditional.* Every argv the executor built carried
   `--cookies` whenever one resolved, exactly as the server's
   `worker._download_video` passed `cookies_file=config.COOKIES_FILE or None`
   on every call. There was no path that did not carry the jar, so when
   YouTube flagged the account there was nothing to fall back to.
4. *Nothing said so.* `ytdl_cookies.STALE_SIGNATURES` did not contain "the page
   needs to be reloaded", so a flagged session was never marked stale and the
   tray never spoke; and a failure that repeats identically for every clip was
   handled the way one dead video is, burning yt-dlp's full retry budget per
   row (CR-80's job 28 discovered the same wall 29 times).

**Fix in repo** (branch `ytdl-resilience`; the write-up and the work-package
numbering are `docs/YTDL_RESILIENCE_PLAN.md`):

- **WP1, the floor.** `ytdlweb.config.DEFAULT_MIN_YTDLP_VERSION` is
  `'2026.08.19'`, **zero-padded**, and `dashboard/deploy/requirements.txt`
  raised to `yt-dlp>=2026.8.19` to match the pyproject/lock pins CR-80 already
  made. The padding is load-bearing, not cosmetic: `routes_fleet` ranks the
  floor as a string (the rule the fleet inherited from COMP-BROLL-9,
  2026-08-14), and the plan's `'2026.8.19'` spelling sorts as a string ABOVE
  every real `2026.08.xx` release - which would have 403'd every local-download
  claim in the fleet while each companion, ranking tuples, still concluded it
  was current.
- **WP2, the pin.** `ytdl_executor.DEFAULT_PLAYER_CLIENT = ""`: no
  `--extractor-args` at all, i.e. yt-dlp's own default client set, whose
  maintainers track this weekly. `ytdl_player_client` in `config.toml` stays as
  an override for the day a specific client is known-good and the default is
  not. The vendored server downloader never pinned one and still does not.
- **WP3, the inversion, on both executors.** A clip is downloaded
  ANONYMOUSLY first; the cookie jar is spent only on the one failure it
  answers, a bot check; and an account flag on the cookies path falls back to
  anonymous. Both refused is `DownloadPathsBlockedError` on the server (a
  subclass of `BotCheckError`, so it is phase-fatal on the same terms) with
  `BOTH_PATHS_NOTE`, and `BOTH_BLOCKED_ERROR` on the row for the companion.
  The preference is sticky - module-level on the server, per executor on the
  companion, anonymous again after a restart - so the extra failed extraction
  a genuinely bot-checked line costs is paid once per flip, not once per clip.
  A jar holding only its Netscape header lines (CR-80's parked state,
  `ytdl_evidence.cookie_jar_state` == `empty`) is not a path at all and is
  never attempted. `cookies_used` on the companion now follows the path that
  actually ran, so an anonymous failure can no longer light the tray warning
  for a session nothing touched, and a clip landed by the fallback carries a
  note on its clip-status report.
- **WP4, the classifiers.** "the page needs to be reloaded" is an
  account-flag class of its own on both sides, distinct from the bot check
  because the remedies are opposite (the bot check says *this IP needs an
  account*, the flag says *this account is refused*). On the companion it
  joins `ytdl_cookies.STALE_SIGNATURES`, and `stale_reason` gives the tray a
  line that says the signed-in session is being refused and downloads are
  continuing without it, rather than the "sign in again" the other signatures
  get - the cookies still authenticate, so a re-export of the same session
  fixes nothing.
- **WP6, the breaker.** N consecutive clip failures with the same normalised
  signature stop the run instead of grinding through the rest.
  `YTDL_MAX_IDENTICAL_FAILURES` (default 3, 0 disables) parks the server job at
  phase `failed` with a note chosen by class - no usable format names the
  running yt-dlp version and says to check for an update, HTTP 403 names the
  PO-token sidecar and the yt-dlp version, anything else quotes the error and
  says to press RETRY. Unreached rows stay `pending` and the manifest is still
  written. `ytdl_max_identical_failures` (config.toml, else
  `CCSYNC_YTDL_MAX_IDENTICAL_FAILURES`, default 3) is the companion's, which
  hands the remaining clips back to the server through the existing lease
  expiry and pokes `ytdlp_manager.ensure()` once per job when the signature
  says the binary rather than the video. A clip that lands resets the count:
  only CONSECUTIVE identical failures mean "stop".
- **The retry.** `POST /ytdl/api/jobs/{id}/download` accepts phase `failed`
  as well as `ready_for_review` and `done`, but only for a job that has
  download rows, and it clears the job note it re-queues past. A job that died
  in search or enrich still 409s "nothing to retry": the fix there is a new
  search. `[ RETRY n FAILED ]` on the SPA is the button that reaches it - the
  endpoint has re-queued exactly the failed rows since YTDL-16, and that one
  call is what made the CR-80 recovery a one-liner, but the only control that
  ever reached it was DOWNLOAD on the review grid, which is gone by the time a
  job is done.
- **WP5, health that is evidence.** `/ytdl/api/health` gains
  `yt_dlp_version` (answering it took a `docker exec` during CR-80),
  `cookies_state` (`none|empty|anonymous|present`, beside the old boolean that only ever
  meant "a path is set"), `pot_provider` (`unconfigured|ok|unreachable`, from a
  1 s probe of the bgutil sidecar's own `/ping`, cached 60 s - CR-73 sat
  undetected for days behind a sidecar that was configured and silent),
  `paths` (the last real outcome per path, mirrored to
  `<data>/ytdl_evidence.json` so a container restart does not blank it),
  `last_download` and `canary`. Every old key is kept, and the SPA reads each
  new one behind a null guard, so a cached bundle paints the strip it painted
  before.
- **The canary** (opt-in, OFF in this build and in the vendor default):
  `YTDL_CANARY_INTERVAL_SECONDS` unset or 0 means it never runs; set, it is
  floored at 300 s. One extract-only pass at `YTDL_CANARY_URL` (default
  `https://www.youtube.com/watch?v=jNQXAC9IVRw`), anonymous then cookies on a
  bot check, filed into the same evidence with source `canary`.
  `ytdlweb/ytdl_canary.py`, started beside `worker.ensure_started()` in both
  the standalone lifespan and the dashboard mount, wrapped there so a checkout
  without it cannot report the mount degraded.

**ORDERING, and what the operator can do before the ship.** The dashboard
deploys BEFORE the companions, as always: the floor lives on the server and a
companion reads it. Until dashboard 0.7.11 is out, the operator can move the
whole fleet today by setting `YTDL_MIN_YTDLP_VERSION=2026.08.19` on the live
container - every companion picks it up from
`GET /ytdl/api/config/ytdl-client` on its next daily check and runs `yt-dlp -U`.
**Type it zero-padded.** `2026.8.19` is compared as a string by the fleet route
and sorts above every `2026.08.xx` release, so an unpadded floor refuses every
claim in the fleet with "your yt-dlp is old" while no companion updates - the
exact silent shape of this bug, arrived at from the other direction.

**Residuals.**

- **WP7's `cookies.txt.orig`** is documented, not enforced: yt-dlp rewrites
  `cookies.txt` in place on every run, so an operator's export is overwritten
  by whatever the session became. Keep the pristine export beside the jar and
  restoring is a copy, not a re-export (`ytdl/web/DEPLOY.md`).
- **The canary is built and off.** Turning it on is real automated traffic to
  YouTube on a fixed cadence from the deployment's own IP, which is the shape
  that got this NAS bot-checked on 2026-08-11. `docs/YTDL_RESILIENCE_PLAN.md`
  section 7 parks it for the owner, along with whether the NAS should keep a
  cookie jar configured at all now that anonymous is the normal path.
- **WP8, a pool of accounts to rotate through, is deliberately NOT built.**
  The reasoning is in the plan's WP8: it optimises the path the system worked
  better without, every jar is a live credential in a deployment we ship to
  customers, and "the product farms Google accounts" is materially harder to
  defend than "the product supports an optional operator-supplied cookie file"
  (`COMMERCIAL_READINESS.md` item 2). If a second jar is ever wanted, the
  honest version is a manual second slot an admin switches to deliberately.
- **CR-80's own residual stands**: `/venv` belongs to the image, so a
  dashboard IMAGE update reinstalls whatever the lock says. The lock is the
  durable fix - and it has to be `dashboard/deploy/requirements.lock`, the
  third of this repo's three yt-dlp locks and the only one the image installs.
  It was missed, the v0.7.11 image put 2026.07.04 back on the live NAS the
  same day, and that is CR-84.

**How to verify** (the plan's section 6, and the first diagnostic for every
future "downloads are failing"). Run it in the live container AND on one editor
machine, against the same clip, with and without the jar:

```sh
# in the dashboard container
for CK in "" "--cookies /ytdl-data/cookies.txt"; do
  /venv/bin/python -m yt_dlp --simulate --no-warnings $CK \
    --extractor-args "youtubepot-bgutilhttp:base_url=$YTDL_POT_BASE_URL" \
    -f "bv*[height<=1080]+ba/b[height<=1080]" \
    -O "%(format_id)s h=%(height)s" "https://www.youtube.com/watch?v=<id>"
done
```

Which of the two works has flipped once already and will flip again. A
simulate is not proof on its own - CR-80's anonymous path extracted happily on
2026.07.04 and then 403'd on the bytes - so always finish with one REAL
download through the production path
(`ytdlweb.vendor.downloader.download(..., ffmpeg_location=config.FFMPEG_DIR)`),
which is how the CR-80 fix was confirmed. On an editor machine the equivalent
is the deployed companion's own binary and its own jar, and after the ship
`GET /ytdl/api/health` answers three of these questions without a shell:
`yt_dlp_version`, `pot_provider`, `last_download`.

## The image update put both of the day's live fixes back (CR-84, 2026-08-26)

### CR-84 - a THIRD yt-dlp lock nothing checked, and a plugin install that cannot succeed in image mode - FIXED and SHIPPED 2026-08-26 as dashboard 0.7.12 (image `ghcr.io/the-creators-club/ccsync@sha256:9bb05dd5...`, runtime id 869eed1052a8...; the plugin verified in /data/unblock-site at boot, yt-dlp 2026.08.19 from the image itself)

**Symptom** (measured live on the studio NAS, container
`ix-ccsync-dashboard-dashboard-1`, an hour after the CR-83 ship). The
dashboard was redeployed in image mode on the CI image built from tag
v0.7.11 (`ghcr.io/the-creators-club/ccsync@sha256:745eb71a80eeb58024fb9788f4
fa982fed73f6b552f2e4f732538bf414c3065a`) and came up carrying both of the
regressions the ledger had already warned an image update would bring back:

1. **yt-dlp was 2026.07.04 again** - the exact version CR-80 measured as
   having no working anonymous path left, i.e. "The page needs to be
   reloaded" on every server download, on a container that had been
   hand-fixed out of it that morning.
2. **The PO-token plugin install failed four times**, with
   `[Errno 13] Permission denied: '/venv/lib/python3.12/site-packages/
   yt_dlp_plugins'`, once per retry, under CR-73's "PyPI unreachable?"
   wording. No PO-token provider means the CR-73 shape: throttled HLS only,
   ~1.8 MiB/s, some clips landing empty.

Two more things happened in the same redeploy and are NOT bugs, recorded here
because they cost time on the night: `select_code_root.py` booted the image's
own 0.7.11 code over the OTA-staged 0.7.10 tree (correct - rule 5, an older
or equal bundle is the image's job), and the deploy's post-check gave up
while the container was still inside its 120 s compose `start_period`.

**Mechanism.**

- **There are THREE yt-dlp locks in this repo and the deploy one is the
  image's.** CR-80 raised the floor to `yt-dlp>=2026.8.19` and re-pinned
  `dashboard/requirements.lock` and `ytdl/web/requirements.lock`, but
  `dashboard/deploy/requirements.lock` still said `yt-dlp==2026.7.4` - and
  that is the file `dashboard/deploy/Dockerfile` COPYs and installs with
  `--require-hashes`, and the one `run.sh` installs in bind-mount mode. The
  image's `/venv/.runtime-id` therefore did not even change
  (`b8088534983a67ad7a6b27b4582f551032f1329501acbdc2f3cea4dca01589c6`), which
  is itself the tell: a runtime id that survives a dependency bump means the
  bump did not reach the deploy lock. Nothing caught it, because
  `test_deploy_requirements_match_pyproject_dependencies` compares
  `requirements.txt` to `pyproject.toml` and both were right; a lock that no
  longer satisfies its own floor file was unchecked.
- **In image mode that pip install can never succeed.** `/venv` is an image
  layer, `chmod -R a+rX` on purpose (AUDIT C-1: a writable code path in a
  process holding the NAS admin password is remote code execution), and the
  container runs as uid 3000. The GPLv3 `bgutil-ytdlp-pot-provider` is
  deliberately not baked into the vendor image (licence: a customer who never
  enabled `youtube_unblock` must not be conveyed it), so run.sh installs it at
  boot - into the one directory it is not allowed to write. CR-73's retries
  were treating an EACCES as a network blip and said so in the log.

**Live fix applied (2026-08-26, the SECOND time for both halves):**

```sh
C=ix-ccsync-dashboard-dashboard-1
docker exec -u 0 $C /venv/bin/pip install --no-cache-dir --require-hashes \
    -r /app/deploy/requirements-unblock.lock
docker exec -u 0 $C /venv/bin/pip install --no-cache-dir --upgrade \
    yt-dlp==2026.8.19
docker exec -u 0 $C sh -c \
    'md5sum /app/deploy/requirements-unblock.lock | cut -d" " -f1 \
     > /venv/.requirements-unblock-hash'
docker restart $C
```

Both are `docker exec -u 0` into `/venv`, i.e. both are discarded by the next
image update. That is the point of the durable fix.

**Durable fix in repo** (ships as dashboard 0.7.12, whose image carries a NEW
runtime id - so it is a real image update, not an OTA code bundle):

- `dashboard/deploy/requirements.lock` re-pinned to `yt-dlp==2026.8.19` with
  its PyPI hashes, copied from `dashboard/requirements.lock`'s block. It was
  the only pin in that lock below a floor in its `requirements.txt`.
- `dashboard/tests/test_hardening.py::test_deploy_locks_satisfy_their_own_
  floor_files` - every `>=` floor (and the unblock file's `==` pin) in both
  deploy requirement files must be satisfied by the matching lock, with PEP
  503 name normalisation and `packaging.version` comparison. It FAILS on the
  pre-fix lock, naming the file, the pin and the floor.
- `dashboard/deploy/run.sh`: in image mode the unblock lock is installed with
  `--no-deps --target /data/unblock-site` and stamped at
  `/data/.requirements-unblock-hash`, and `/data/unblock-site` is APPENDED to
  PYTHONPATH (in the plain export, in `IMAGE_PYTHONPATH`, and re-attached to
  whatever `select_code_root.py` selects, so an OTA'd code tree does not lose
  the plugin). yt-dlp discovers a plugin by walking `sys.path` for a
  `yt_dlp_plugins` package (`yt_dlp/plugins.py`, `default_plugin_paths`:
  "Load from PYTHONPATH directories"), so a path entry is all it needs - it
  does not have to live inside the venv. `/data` is uid-3000-owned, 770, not
  editor-reachable (AUDIT C-2), and survives an image update, exactly like
  the `/data/code` tree the OTA path already executes from. `--no-deps` is a
  CONDITION of `--target`, not a tidy-up: the lock is a hash-pinned closure of
  one package whose only dependency is yt-dlp, which the venv already holds
  and which has no hash in that lock, so without it `--require-hashes` would
  refuse. Bind-mount mode is byte-for-byte unchanged - there `/venv` is a
  bind mount uid 3000 owns, the install has always worked, and moving it would
  strand the copy already installed.
- The CR-73 retry loop stays, but a failure now prints **pip's own last
  words** instead of only "PyPI unreachable?" - the whole reason this took a
  live shell to diagnose.

**THE RULE, added to the residuals of CR-73 and CR-80: there are THREE yt-dlp
locks and `dashboard/deploy/requirements.lock` is the image's.** Bumping
`dashboard/requirements.lock` and `ytdl/web/requirements.lock` changes what a
dev checkout and a bind-mount site install; it changes nothing about the
vendor image, which is what every image-mode customer runs. A dependency fix
that is not in the deploy lock is not shipped. The one-line check after any
image update:

```sh
docker exec <c> /venv/bin/python -c "import yt_dlp; print(yt_dlp.version.__version__)"
docker exec <c> /venv/bin/python -m yt_dlp -v 2>&1 | grep "PO Token Providers"
docker logs <c> 2>&1 | grep run.sh
```

**Also found during the same redeploy, same day: the parked jar had grown anonymous
cookies.** `/ytdl/api/health` on the new build said `cookies_state: present` for
the jar CR-80 had parked as two header lines. yt-dlp rewrites `cookies.txt` in
place on every run it is passed to, and between the CR-80 fix and the
anonymous-first inversion every run was passed it, so the file held PREF, SOCS,
YSC, VISITOR_INFO1_LIVE and friends: YouTube's consent/visitor cookies, no login
cookie, not a credential. `ytdl_evidence.cookie_jar_state` called any cookie
line a session, so the worker would have "fallen back" to it on a bot check.
Fixed in the same release: `present` now needs a Google login cookie name (the
companion's `_SESSION_COOKIE_NAMES` list plus the `__Secure-*PSID` pair), a jar
of anonymous cookies is the new `anonymous` state, and only `present` is a path.
The NAS jar was parked again as its header lines with the anonymous copy kept
beside it (`cookies.txt.bak-20260826-anon`); since the inversion the anonymous
path never passes the jar to yt-dlp, so it stays parked.

## Companion: a locally downloaded YouTube clip is checked and, if Resolve could not decode it, converted on the editor's machine (CR-79, 2026-08-25)

### CR-79 - local YouTube downloads were never checked for a Resolve-decodable codec; the server's conversion did not run for them - FIXED, SHIPPED as companion 0.9.50 (CI builds on 0fb926d, vendor feed + studio channel current on both platforms, base rig upgraded 2026-08-25 11:38Z)
**Ask** (owner, 2026-08-25): "do videos downloaded locally on the companion
still get properly remuxed into resolve-friendly format" and, on hearing the
executor handed anything non-AVC back to the server: "surely the companion
could just ffprobe and convert it itself if needed? No need to send back to
the server."

**Measured first** (base rig, companion 0.9.49's real `build_argv`, a 1080p
test clip): the file that lands IS fine today - ISO MP4, `avc1` H.264 High
yuv420p, AAC LC, CFR, credits tags embedded - i.e. exactly what the server's
`ensure_edit_ready` passes through untouched. But it is fine by luck, not by
design: `player_client=web_safari` (CR-39) serves muxed HLS only, so all
three AVC-constrained `bestvideo+bestaudio` alternatives in
`ytdl_common.format_selector` are unsatisfiable and yt-dlp takes the LAST,
codec-unconstrained `best[height<=1080]` (format 96). YouTube's HLS ladder is
all AVC today; the day it is not, a local download lands undecodable and
silent, because `_download_one` posted `done` on whatever `landed_file`
found. The server ffprobes every clip (`vendor/downloader.py`
`ensure_edit_ready`, YTDL-22/23); the companion had no check at all.

**The 0.8.0 scope cut was built on a misreading.** `SCOPE_QUALITIES` and
the module header said the rungs above 1080p could not run locally because
the server's converted deliverable is `<stem>.editready.mp4`, "a name the
CLI cannot reproduce". `_swap_in` in fact REPLACES the download under its
original name; `.editready` survives only when Windows holds the original
open (clip in an open Resolve project), and `.original` is where a locked
original is moved aside. Nothing about the name was ever unreproducible.

**Fix (companion 0.9.50, `ytdl_executor.py`).** After `landed_file`, every
clip goes through `DownloadJob._ensure_edit_ready`, which is the vendored
`ensure_edit_ready` split into pure pieces and run through this executor's
own seams:

- `probe_argv` / `parse_probe` (probe_streams, incl. YTDL-22's "a failure
  is never `{}`"), `_same_rate` and `_color_args` verbatim,
  `edit_ready_plan` (the decision: h264/aac/CFR is fine; VP9/AV1/Opus or a
  VFR stream re-encodes that stream and COPIES the other; a failed probe
  converts both on suspicion), `edit_ready_argv` (the exact ffmpeg command:
  libx264 medium crf 18 High yuv420p cfr + colour tags / aac 320k,
  `-map_metadata 0`, `+use_metadata_tags+faststart`), `editready_name`,
  `swap_in` (same-name replace, `.original` aside for a locked file,
  `.editready` kept as a last resort, each with the vendored note).
- Both subprocesses run through `deps.run` (windowless, sanitized env) and
  register with the lease's kill handle, so a lost lease ends a re-encode
  the way it ends a download; the tmp is removed on any non-success.
  `PROBE_TIMEOUT_SECONDS` 120, `CONVERT_TIMEOUT_SECONDS` 3 h (a re-encode
  of a two-hour clip on a laptop is legitimate; unbounded would hold the
  lease forever).
- The three outcomes are the vendored ones: fine or converted -> `done`
  under the original name (a swap-in note joins the truncation note);
  conversion failed after the probe asked for it -> the clip FAILS and the
  download is disowned to `.failed` (so the server's second-chance sweep
  starts over and the `[id]` dedupe never points at an undecodable file);
  conversion failed after the probe merely failed -> kept as downloaded
  with the note.
- ONE deliberate deviation: no ffprobe beside ffmpeg (a hand-set-up
  machine; the sidecar installs both) means "delivered unchecked", logged,
  never "convert on suspicion" - on an editor's laptop that suspicion is a
  full re-encode of every clip.
- `phase` on the progress snapshot (`downloading` / `converting`);
  `tray.ytdl_download_line` says `Converting YouTube clip 3/12 to H.264`
  so a ten-minute re-encode does not read as a stalled download.
- `SCOPE_QUALITIES` is unchanged at 480p/720p/1080p, now for the honest
  reason: 1440p/2160p/`best` are a guaranteed full 4K VP9/AV1 -> H.264
  re-encode on the editor's machine. Widening the tuple is the whole change
  if the owner wants those rungs local too.

Tests: `companion/tests/test_ytdl_executor.py` (the plan, the argv, the
probe parser, the tmp name, `swap_in`'s three paths, end-to-end untouched /
converted / failed-conversion / failed-probe / joined note / no-ffprobe /
lease lost mid-conversion, the phase), `test_tray.py` (the sentence),
`server/tests/test_cross_component.py` (the vendored `ensure_edit_ready`
driven with its seams patched: the companion's command == the server's
command for vp9+opus, h264-VFR, av1+aac and a failed probe; both leave
h264/aac/CFR and audio-only alone; codec sets, rate rule and colour args
agree; the forgive-only-a-guess fork). Shipped 2026-08-25 on the CI path
(release-windows 32839447955 / release-macos 32839451157, `publish_latest
--make-current`, studio pull); editors get it at their next tray click or
auto-update. Not yet observed live: the `Converting YouTube clip N/M to
H.264` tray line on a real non-AVC download.

## Companion: the tray says how a local YouTube download is going, and fetches it six fragments at a time (CR-78, 2026-08-25)

### CR-78 - local YouTube downloads were invisible in the tray and crawled one HLS fragment at a time - FIXED, SHIPPED as companion 0.9.49 (CI builds on 2b29b54, vendor feed + studio channel current on both platforms, base rig upgraded 2026-08-25 11:24)
**Ask** (owner, 2026-08-25): "the companion should be updated so that when
it is downloading a youtube clip it shows the information. Downloading: x/x
(xx mb/s). Right now it seems like the youtube downloads are going very
slowly." Observed live: job 23, 22 clips, `download_mode=local` on the base
rig, 11 done after ~40 minutes.

**Two causes, one per half of the ask.**

1. `build_argv` passed `--no-progress`, so yt-dlp printed nothing a tray
   could read, and `default_run` read stdout only after the process exited
   (`communicate`). The executor's progress mirror knew `done/total` and the
   clip id, and the tray never asked it for even that.
2. `web_safari` (CR-39) serves HLS, and the companion fetched fragments one
   at a time: the same shape as CR-74 on the server, where a long clip
   sustained 3-4 MiB/s sequentially against 53 MiB/s with six in flight.
   CR-74 deliberately left the companion's argv alone ("a companion change
   is a fleet release"); this is that release.

**Fix (companion 0.9.49).**

- `build_argv`: `--progress --newline --progress-template
  <PROGRESS_TEMPLATE>` in place of `--no-progress` - one tab-separated
  `CCSYNC-PROGRESS` line per update (downloaded, total, estimate, speed)
  that nothing else on stdout can look like (`parse_progress_line` requires
  the first field to BE the prefix); and `-N <ytdl_fragment_jobs>` (config
  key, default 6, bounded 1..16 like the server's `fragment_jobs`; 1 is
  the old behaviour).
- `default_run`: stdout is pumped line by line on a helper thread to an
  optional `on_line` keyword while the process runs; `.stdout` is still
  the whole text afterwards. `_call_run` passes the keyword only to a
  runner whose signature admits it, so the three-argument `RunFn` seam
  every fake and any operator replacement uses is unchanged.
- `DownloadJob`: `bytes_done` / `bytes_total` / `speed_bps` on the
  snapshot (and on `GET /ytdl/progress`), reset to None as each clip
  starts so the previous clip's rate never sits under the next clip's
  name.
- `tray.ytdl_download_line`: `Downloading YouTube clip 3/12 (4.2 MB/s,
  38%)`, dropping whatever is unknown (`(38%)`, `(4.2 MB/s)` under HLS
  with no total, bare `3/12` before the first update or while merging),
  one-based on the clip in flight, in the state lines after the Resolve
  line, and in the menu fingerprint so the numbers refresh on an
  otherwise-idle machine (UI-3's shape).

Tests: `test_ytdl_executor.py` (argv, the knob's bounds, the parser, the
pump through the real `default_run` with a fake yt-dlp that prints template
lines, `_call_run` against 3-arg / 4-arg / `**kw` runners, the end-to-end
mirror with a clean second clip), `test_tray.py` (the sentence, what is
left out, no line when idle, no em dash), `test_config.py` (the key is
documented). Companion suite 4507 green. Needs a companion release on both
platforms; the base rig's own upgrade should wait for job 23 to finish -
the upgrade kills a download in flight.

## YouTube downloader: language scope and an upload-date range (CR-77, 2026-08-25)

### CR-77 - the search always expanded into both languages, and a date meant one of YouTube's five windows - FIXED, SHIPPED as dashboard 0.7.10 (OTA, 2026-08-25 02:57Z; waited out local job 23, never forced)
**Ask** (owner, 2026-08-25): "add some search modes to the youtube downloader:
'only english', 'only chinese' or 'single search term only' - so it only
searches things that match the exact input the user provided", and "there
should also be a date selector". Every search ran the editor's term plus
8-12 English and 8-12 Taiwanese-Chinese queries the model wrote from it,
with no way to switch either language off or to search the typed text alone;
and the only date control was the `any date / today / week / month / year`
select, which is YouTube's own `sp=` filter and cannot say "2019".

**Fix.** Two new per-job inputs, stored on the job row like `mode` is
(migration `011_jobs_term_scope_dates.sql`, schema v11), so a job re-run from
`queued` after a restart runs as it was submitted:

- `term_scope`: `both` (default, byte for byte the search that ran before -
  `tests/golden/` still pins it), `en`, `zh`, `exact`
  (`claude_cli.TERM_SCOPES`). `en`/`zh` swap the term prompt's language
  block (16-24 queries in the one language, the other named as not wanted),
  reword the ticked-box bias so it stops asking for "BOTH languages", and
  append a language rule to the relevance pass that DROPs a candidate whose
  title and channel are plainly in the other language (KEEP when it cannot be
  told). `_usable_terms` ENFORCES the language on the reply, so a model that
  ignores the instruction still cannot run a query in the switched-off
  language. `exact` skips the term call entirely: the editor's text is the
  one term, and that one flat search is given the whole candidate ceiling
  (`max_candidates`, not the 15-per-term the expanded search paces with).
  The relevance pass still runs, and degrades the way it always has - which
  means an exact search STARTS with the AI provider down.
- `date_from` / `date_to`: ISO in (`<input type=date>`), `YYYYMMDD` stored
  (yt-dlp's `upload_date` shape, so the worker compares strings). Enforced
  in the filter phase as a mechanical drop beside the live/over-length ones,
  BEFORE the judge sees the card (no tokens on a card the range decided);
  a video with no `upload_date` is kept. Refused with a 400: a
  non-calendar date, a reversed pair.

SPA: a `SEARCH IN` row above the search box - `[ EN + ZH ] [ ENGLISH ONLY ]
[ CHINESE ONLY ] [ MY TERM ONLY ]`, remembered per browser like the mode
(`ytdl.term_scope`), a note under `MY TERM ONLY` saying no expansion happens
and the candidate limit is the search's size - and two date inputs with a
`[ CLEAR ]` that appears only when one is set. The dates are deliberately
NOT remembered: a range is about one search, and one carried silently into
next week's would drop most of what it found. Every view of a job (ticker,
review header, Recent searches) names its scope and range when they narrow
it; the default claims nothing. A url job carries neither.

Tests: `test_claude_cli.py` (prompt blocks per scope, reply enforcement,
golden unchanged), `test_api.py` (storage, 400s, url-job ignores),
`test_worker.py` (exact skips the model + gets the ceiling, scope reaches
both calls, date drops and their notes), `test_db.py` (v10 -> v11 migration,
tolerant readers), `test_static_app.py` (three harness scenarios + source
pins, table matched against the server's). ytdl suite 708, dashboard suite
1666 green. Needs a dashboard deploy (OTA).

## Admins can delete users and computers (CR-76, 2026-08-24)

### CR-76 - no way to delete a user or a computer from the dashboard - FIXED, SHIPPED as dashboard 0.7.9 (OTA, 2026-08-25)
**Symptom** (owner, 2026-08-24): an editor who leaves, or a laptop that is
wiped or replaced, stayed on the fleet page forever. DELETE on the Users
page was local-mode only and by design left every fleet record standing
(the docstring's B16 argument: a grid row that vanishes turns a known editor
into an unmapped stranger). In the studio's NAS mode there was no button at
all, and there has never been one for a computer. Worse than the clutter:
an ex-editor's Syncthing device kept every share it had, because the enforce
cycle deliberately leaves an UNMAPPED device alone - so "delete them at the
NAS by hand" left their machine receiving projects.

**Fix.** Two routes, one implementation each, the Users page buttons calling
the same functions as the JSON routes (`api.delete_user_everywhere`,
`api.forget_machine_everywhere`):

- `DELETE /api/v1/admin/users/{username}` now works in every mode and
  removes the person everywhere, IN THIS ORDER: the local account row
  (uncommitted, so its self/last-admin guards refuse first), their Syncthing
  devices and shares (`SyncthingClient.remove_device`; a Syncthing failure
  rolls everything back and 502s "nothing was deleted"), the NAS account
  (new `NasBackend.delete_editor` on both backends, behind the refusals
  CREATE has - never a system account, never one outside `editors`), the
  fleet rows (`db.forget_editor`: every per-machine table, the '' bucket,
  `known_editors`, the collector's `devices` mirror), commit, then sessions
  and report tokens. Also deletes a username the fleet knows but no backend
  has an account for (a device approved under a name nobody provisioned).
  Home directory: TrueNAS leaves it, DSM removes it; both come back as a
  warning/notice. Kept on purpose: `lane_report_history`,
  `transfer_history`, the tree, the files on their computers.
- `DELETE /api/v1/admin/machines/{editor}/{machine}` removes ONE computer
  (Syncthing device first, then `db.forget_machine`), leaving the person,
  their bucket and their tokens alone. Not a revocation: report tokens
  belong to the person, so a companion still running there re-registers on
  its next report; the confirm and the response say so.
- Users page: [ DELETE ] on NAS editor rows, a [ COMPUTERS ] table (every
  registered machine, [ REMOVE ] each) and [ EDITORS WITHOUT AN ACCOUNT ]
  for the fleet-only names. `GET /admin/users` gains `computers` and
  `fleet_only_editors`.

Tests: `dashboard/tests/test_admin_delete.py` (both NAS backends via
`nas_case`, Syncthing-down abort, refusals, htmx twins, db layer); the two
local-mode tests that pinned the old "keep the fleet rows" semantics were
rewritten. Docs: `docs/API.md`, `docs/MULTI_MACHINE_PLAN.md` §10. Needs a
dashboard deploy; no companion change.

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

## The ytdl page "ate" a paste-and-leave, and a locked Settings URL (CR-98/99, 2026-08-30)

Two more of the five things the owner hit tonight, 2026-08-30, on the base
rig — the other three are CR-95, CR-96 and CR-97 above.

### CR-98 — "I just submitted 12 youtube links... it seems to have eaten them" — ALREADY FIXED, same day, by a9ef83a; regression tests added, dashboard 0.7.26
Owner, 2026-08-30: *"I just submitted 12 youtube links to be downloaded but I
clicked away and came back and it seems to have eaten them"* — the downloads
were fine (server-side, the clips landed), only the page came back showing
nothing.

Investigated: `ytdl/web/static/app.js`'s `init()` already re-reads BOTH
halves of "what is my downloader doing" on every load — `openingJob()` asks
`GET /api/jobs/active` fresh (attaching to a still-running job's full
progress view, hash and all, regardless of what `#job=` a stale bookmark
carries) and `loadQueue()` asks the same route's `queue` field for the jobs
still waiting behind it, independently of any hash. `loadRecent()`
(`GET /api/jobs?limit=15`) shows a job that finished while the tab was closed
without needing either. All three run unconditionally in `init()`, before
`openingJob()`'s attach decision. This is `a9ef83a` ("ytdl: the page shows
the terms to tick, and the queue under the job", same day, 13:42, already on
`main` before this branch was cut) — the queue feature the owner had just
asked for ("there should also be a queue so you can queue up multiple
searches") landed with this re-read built in from the start.

So the literal report is **already fixed in the repo the owner hit it in** —
what was missing was deployment (`tools\ship.cmd`, which only the owner
runs) and a regression test pinning the exact scenario, in case a later edit
narrows `openingJob()`/`loadQueue()` back down. Added:
`ytdl/web/tests/test_static_app.py`
(`test_a_paste_and_leave_is_never_mistaken_for_a_loss`,
`test_a_finished_paste_still_shows_in_recent_on_a_fresh_load`) — both
constructed straight from the owner's words (a still-downloading paste with
a queue behind it; a paste that finished while the tab was away) and both
pass against the CURRENT `app.js` with no further code change. **Ship the
dashboard to make this real on the live NAS** — until then the deployed page
is whatever build predates `a9ef83a`.

### CR-99 — Settings → Dashboard URL was locked the moment a deployment had ever had ANY value in it — FIXED in repo 2026-08-30 as dashboard 0.7.26, NOT YET SHIPPED
Owner, 2026-08-30: *"it won't let me change the dashboard url."* Tonight's
values: the container's env carried
`DASH_SITE_DASHBOARD_URL=https://truenas.tail26290e.ts.net:9443`, the DB row
held `http://100.71.216.3:8480` — the field showed the DB row (right, per
`site_store`'s "the DB is authoritative once written" rule) and could not be
changed (wrong).

`admin_settings.html` greyed a field out whenever its key was in
`site_store.AUTO_DERIVED_KEYS` **and the DB row had ever been given any
value at all** — which every deployment's `dashboard_url`/`sftp_host`/
`nas_syncthing_id` had, from the first boot's env seed
(`site_store.seed_from_env_once`) alone. Nothing about a stored value means a
live source is deriving it TODAY; `site_store.AUTO_DERIVED_KEYS`'s own
comment and `docs/CONFIG.md` already promised the opposite ("greys those out
only when a live value is actually available"), and neither the Tailscale
sidecar (WP B) nor the SFTP sidecar (WP C) exist on Alex's deployment (or
most others) — so this had been permanently wrong since the day
`AUTO_DERIVED_KEYS` was introduced.

**Fixed**: `ui._live_auto_derived_values` checks each key against an actual
live source, bounded and fail-open (a probe that cannot answer leaves the
field EDITABLE, never locked):
  - `dashboard_url` — the bundled Tailscale sidecar
    (`tailscale_local.socket_present()`, a `Path.exists()` on a unix socket,
    no network at all when absent — the common case, including tonight's)
    signed in (`BackendState == "Running"`) with a resolvable name.
  - `nas_syncthing_id` — this site's own Syncthing, `/rest/system/status`'s
    `myID`, the same call `setup_engine._check_syncthing` already makes,
    bounded to 2 s here too.
  - `sftp_host` — WP C's SFTP sidecar has NO outbound status route in this
    repo (`internal_sftp.py` is inbound identity only, called BY the
    sidecar). No live source exists, so this key is never auto-derived,
    full stop, until one is built.
`page_admin_settings` passes only the keys with a live answer as
`auto_derived` (was: the static full set), plus `auto_derived_reason` (why,
shown next to the label) and `env_hint` (the DASH_SITE_* value, shown
whenever it differs from the DB row — the truenas.tail26290e.ts.net vs
100.71.216.3 disagreement from tonight, now visible instead of silent).
Server-side `PUT /api/v1/admin/site` never refused these keys either — the
`readonly` HTML attribute was the entire lock. Tests:
`dashboard/tests/test_settings_auto_derived.py` (11 cases: editable with a
stale stored value + no live source; never editable for `sftp_host`; greys
correctly when Tailscale/Syncthing DO answer live; stays editable on
NeedsLogin / unreachable / a raised exception; the env hint shows and hides
correctly; a previously-locked field can actually be saved once unlocked).

---

## The phone's "Install" made a shortcut, and a switched episode showed no canvases (CR-100/101, 2026-09-02)

Both reported by the owner from the phone on 2026-09-02, on the Timeline
Cards page under the dashboard's `/cards` mount, over
`https://truenas.tail26290e.ts.net:9443`. "There is no certificate" was the
first description; the origin's certificate was fine (Let's Encrypt via
Tailscale Serve, "Connection is secure" in the page-info sheet) and neither
fault had anything to do with TLS.

### CR-100 — "Install" on the cards page made a Chrome shortcut that opens with the URL bar — FIXED in repo 2026-09-02 as dashboard 0.7.27
Owner: *"it's saying install but the thing that actually appears is just a
chrome shortcut which opens the browser with the full URL bar etc, not full
screen as we intended."*

The cards page links its manifest document-relative
(`<link rel="manifest" href="manifest.webmanifest">`, scope `.`,
TIMELINE-CARDS-INTO-CCSYNC.md 7e), which under the mount is
`/cards/manifest.webmanifest`. A browser fetches a manifest WITHOUT the
session cookie, and the dashboard's `login_gate` answered that fetch with a
303 to `/login` - so Chrome had no manifest, judged the page not
installable, and its Install produced a home-screen shortcut instead of a
fullscreen app. The cards handler itself serves `/manifest.webmanifest` and
`/icon.svg` BEFORE its own gate for exactly this reason (2026-08-29); the
dashboard's gate in front of it did not. `tools/check_mobile_origin.py`
passed throughout because it checks the DASHBOARD's manifest, which has been
in `_OPEN_EXACT` since M4.

**Fixed**: `/cards/manifest.webmanifest` and `/cards/icon.svg` join
`app._OPEN_EXACT` (neither names a path, a token or anything the login page
does not). `dashboard/tests/test_pwa.py` pins both in the set and pins that
the gate never 303s them. Verified live under the mount with a session
before the change (both answer 200, the bare `/cards` 307s to `/cards/`);
needs the dashboard deployed to reach the phone. After the deploy: open
`/cards/` in Chrome, `⋮` → Install, and the icon opens fullscreen.

### CR-101 — after switching the episode root, the drawer's OPEN panel said "no cut lists yet / none in Script Docs" for 30 s (Civil Defence has nine canvases) — FIXED in the MulticamPipeline repo 2026-09-02, LIVE on the NAS same day
Owner: *"I'm in civil defence but it is reading no canvas files."*

Server side was right all along: `GET /cards/api/projects` answered nine
`.canvas` files for `/vault/Vault/2026/FF5/Civil Defence/Script Docs` (the
container sees the folder; `cards_ui.json` held that root; the NAS
`cards-web` tree was byte-identical to the checkout). The page was wrong:
a root switch (`api/root` POST, and the poll noticing `d.root` moved) nulls
`PROJS` - the last `api/projects` answer the OPEN panel renders from - and
rebuilds through `txBuild()`, which fetches `api/projects` itself but kept
the answer LOCAL. `openDraw()` then refetches only when
`Date.now()-OPENFETCH>30000`, and `OPENFETCH` had been set by the draw just
before the switch, so the panel rendered `files` from the state poll (empty:
right for Civil Defence, which has no cut lists) and canvases from a null
answer (`none in Script Docs`) until the throttle expired AND something
redrew the drawer.

**Fixed** (`multicam_pipeline/cards/page/01-state.js`): `txBuild` keeps a
real `api/projects` answer as `PROJS` (a bare `{}` from its catch is not an
answer), and both root-switch sites reset `OPENFETCH=0` beside `PROJS=null`
so the next draw asks at once. `tests/test_open_panel.js` (node, no
server) pins both rules against the shipped page files. Deployed by a
staged copy + atomic rename into
`/mnt/tank/apps/ccsync-dashboard/cards-web/…/page/01-state.js` (previous
file kept as `.bak-20260902`; `render_page` re-reads on mtime, so no
restart) and verified in the served page. The next
`install_dashboard_app.py` run re-ships the whole tree from the checkout,
which carries the same bytes.

Not a fault, noted while looking: the dashboard log's `X-Forwarded-For
from 192.168.0.102, which is not in DASH_TRUSTED_PROXIES` line is real -
Serve proxies to the LAN address, so the session cookie goes out without
`Secure` and every browser shares one throttle bucket. The one-line cure is
`tailscale serve --bg --https=9443 http://100.71.216.3:8480` (the address
the trusted list already carries, and the Funnel line already uses);
offered to the owner, not applied.

## The 2026-09-03 hunt's fix pass (CR-102..CR-119, 2026-09-03)

`docs/bug-hunt-2026-09-03.md` (17 hunters, 5 verifiers, 84 findings, 9 high)
was fixed the same day by a 16-builder pass over disjoint file territories,
orchestrator-reconciled, one ledger entry per THEME naming the finding ids it
covers; each fix cites its id at the code site, so `grep -rn <id>` finds what
was done. Every finding has a regression test that failed before the change.
Versions: companion **0.9.65**, dashboard **0.7.28**, installer **1.0.39**,
plus the **Timeline Cards checkout** the `/cards` mount imports (CR-122..CR-131,
another repo, not a version of ours).
**SHIPPED 2026-09-03**, in the order the fix pass required. **(1) The
dashboard**: 0.7.28 image-deployed 14:13Z (tag `v0.7.28`, pre-deploy snapshot
`tank@ccsync-pre-recreate-20260903-220815`), with the **cards checkout
reshipped in the same run** (previous tree kept as
`cards-web.old.20260903221017`) - one deploy, so the container restart the
cards Python modules need came with it. **(2) The companions**: 0.9.65 is
CURRENT on windows and macos in the studio channel and the base rig is
upgraded. **(3) onboard 1.0.39** is in the vendor feed for windows and macos.
The macOS bundle took three CI runs, all of them test-only faults on a runner
that is not Windows: two of this hunt's own test pairs assumed one
(`test_upgrade` tampering with its own platform's record, `test_fixer`
creating an NFC directory on case-preserving APFS), two onboarding
forbidden-drive tests named no platform at all, and one `test_jobs_resilience`
timing flake. No product code changed for any of them (commits 88dbcf7,
bf214ae, a300593). Three owner decisions were
left as such and are named in the entries: the companion's `arch` check
(CR-103), the REL-1 soak gate on the feed's `current` policy (CR-113), and
where the alerts webhook URL is stored (CR-112). One leftover nobody owned:
on Synology `install_dashboard_app.py` still writes `DASH_NAS_PW`
unconditionally, so the TrueNAS API-key mitigation (COMMERCIAL_READINESS item
6) does not apply there (server-tools-1's verifier aside).

### CR-102 — the express lane A door uploaded the half-made ytdl files the periodic pass refuses — FIXED in repo 2026-09-03 (companion 0.9.65)
comp-sync-1 (high), -2, -3, -4. `path_matches_lane_a_filter` was documented as
equivalent to `build_filter_rules_up()` and implemented three of its rules;
YT-3's five work-file patterns (`*.editready.*`, `*.original.*`, `*.temp.*`,
`*.f[0-9][0-9][0-9]*.*`, `*.failed`) and the file-moves excludes were absent, and
express cannot carry a filter file, so under `copy --ignore-existing` a whole
`.original.mp4` landed on the NAS for good. **Fixed**: the predicate compiles
its regexes FROM `YTDL_WORK_EXCLUDE_RULES`, so it cannot drift again, and the
express run consults `extra_excludes_fn` before writing its `--files-from-raw`
list; `recent_excludes` matches the run root as a prefix (borrowed subtrees and
whole-tree runs get their exclusions); `_cmp_key` folds NFC so a Mac recognises
its own moved file (RES-10's relink offer); `_repoint` reports whether it
paused so the borrowed folder is unpaused in the same pass. The equivalence
test runs fifteen names through a real rclone dry run against the predicate.

### CR-103 — the companion installed any genuinely signed record, including the onboarding installer, over its own exe — FIXED in repo 2026-09-03 (companion 0.9.65)
comp-core-1 (high), comp-core-5. `_accept_offer` checked the signature, the
CR-52 self-contradiction and the floor, then discarded `kind`/`platform`; the
only enforcer was the dashboard the offline key exists to distrust. A signed
`onboard` record served as `upgrade` was renamed over `ccsync-companion.exe`
and the Run key launched a wizard at every logon. **Fixed**: refused before
`note_floor` unless `kind == "companion"` and `platform == platform_key()`.
The `arch` half is an owner decision (`OPTIONAL_KIND_EXTRA_FIELDS` says arch is
enforced dashboard-side; a client test must treat a missing arch and
`universal2` as passing). A path-relative update URL is now resolved with
`urljoin` instead of burning REL-8's eight-attempt budget as `download-failed`.

### CR-104 — two tray dialogs built a Tk root outside `ui_dispatch`, and the error copy named menu rows deleted on 2026-08-27 — FIXED in repo 2026-09-03 (companion 0.9.65)
comp-ui-1 (high), -2, -3, -4, -5. `_install_youtube_cookies` and
`_show_youtube_terms_dialog` called `tk.Tk()` on a `_spawn` worker thread with
no `release_root()`, so each click pinned an interpreter for the life of the
process (CR-93's guard reported "held by: none"), and on macOS built Tk-Aqua
off the main thread. **Fixed**: both go through `dispatch` + `release_root` as
`popup._tk_pick` does, under the popup lock (no caller held it; proven), and
`test_tk_interpreter_hygiene.py` has an AST guard: every `tk.Tk(` must be
inside a function passed to `ui_dispatch.dispatch`. Twenty-odd strings across
tray/app/fixer/identity/resolve_journal/loopback_guard/resolve_bridge/popup
that said "Tray -> Copy diagnostics" / "Advanced -> ..." now name the Settings
row, and `test_tray_copy_names_real_menu_items.py` fails on the next survivor.
Also: LUT link warnings repeat per streak and hourly, `copy_into_library`
refuses a `dest_rel` outside the library, `_DarwinIcon.stop()` hops to the
main thread.

### CR-105 — concurrent media-pool edits lost undo-journal entries, and a Resolve that went away was remembered as a permanent proxy refusal — FIXED in repo 2026-09-03 (companion 0.9.65)
comp-resolve-1 (high), -2, -3, -4, -5, -6. `resolve_journal.record()` did an
unlocked read-append-write with one shared tmp name, and both writers sit
outside `_bridge_call`: 8 threads x 20 records kept 1 to 8 of 160 entries, so
UNDO reported success for clips it never knew about. **Fixed**: `_lock` across
the read-modify-write, a per-thread tmp name, the swallowed write failure is a
WARNING. `link_proxy_media` returns `reason: scripting_error | refused` and
`apply_relinks` remembers only a real refusal. Cards role: `check_contract`
and `_start` share one `engine_class()`; the slow-take warning stamps only when
it logs; `lsof +c 0` with prefix matching on macOS; a non-zero process probe
is "cannot tell" (fails closed).

### CR-106 — a Mac had no relaunch net, and a diacritic in a project rel made a phantom project — FIXED in repo 2026-09-03 (companion 0.9.65, dashboard 0.7.28)
comp-core-2, -3, -4. `supervisor.spawn_for` declined off Windows "because
launchd", while the LaunchAgent deliberately has no `KeepAlive`: a Mac that
aborts stays dead until logon. **Fixed minimally**: the docstring tells the
truth and the "no supervisor" line is WARNING on darwin (a POSIX port is more
than the two ctypes helpers). `fixer.list_project_dirs` unioned an NFD walk
with the NFC selection and the dashboard's `_slug_for_rel` slugified the two
spellings differently (`fran-ais` vs `franc-ais`): two `editor_media_project`
rows, one phantom. **Fixed** both sides through `nfc_key` / `media_rel_key`
(comparison only). The crash-loop revert now clears the run marker before
returning, so a deliberate rollback is not filed as `UncleanExit`.

### CR-107 — the 8899 loopback: a checkpoint that stopped being written, an unbounded Resolve-worker fan-out, a stale origin list — FIXED in repo 2026-09-03 (companion 0.9.65)
comp-broll-music-1, -2, -3, -4. `_save()` serialised LIVE dicts outside the
lock with `indent=2` (the pure-Python encoder yields the GIL) so a busy batch
raised `dictionary changed size` into one swallowed warning. **Fixed** with a
`_snapshot()` of `dict()`/`list()` copies (single C calls); the verifier's
`deepcopy` suggestion was tried and does NOT work, because the mutators hold no
lock. `GET /status` and `/music/status` are now memoised for a few seconds
behind one in-flight slot, so a page of `<img src>` loads costs one worker
child, not hundreds. The origin allow-list is a 30 s TTL accessor, so a changed
`dashboard_url` no longer 403s a whole session. `do_POST` drains a refused
body like `do_PUT`, and `_read_body` counts what it consumed.

### CR-108 — one failed heartbeat killed a running whisper job, and the jobs backoff never engaged — FIXED in repo 2026-09-03 (companion 0.9.65, dashboard 0.7.28)
comp-ytdl-jobs-1 (high), -2, -3, -4, -5, -6, dash-api-3. `JobRunner._heartbeat`
had zero transport tolerance: a 3 s dashboard restart terminated the child,
counted an attempt and cooled the machine down (CR-31's shape, in a module
written after CR-31). **Fixed**: a raised transport failure keeps going, only a
410 stops; `beat()` cannot be killed by anything it calls. The queue-depth
backpressure was dead code (the dashboard omitted `queue` on an empty queue,
the companion read absence as "cannot tell"). **Fixed as a contract**: a
companion reporting >= 0.9.65 always receives `commands.jobs.queue`, and the
companion's jobs thread has a wake event set on any offer so a backed-off
machine claims [ RUN NOW ] immediately; below 0.9.65 the dashboard keeps the
old shape (an old companion would back off with no wake). `_read_pcm` drains
on a thread with the stop/ceiling check on a timer; `_attempt_copy` discards
its `.partial` on a stop; a failed publish keeps the finished file.

### CR-109 — `DASH_SESSION_SECRET` rotation only worked for `/report`; UNDO of a renaming move kept the new name — FIXED in repo 2026-09-03 (dashboard 0.7.28)
dash-api-1 (high), -2, -4, -5, -6, plus dash-db-1's route half. Four gates
(`selection`, untick, diagnostics, every `/jobs` fleet route) verified an
identity against the current secret only, so during DASH-2's documented drain
window reports kept landing while no machine could learn a plan change and a
held job could never finish. **Fixed**: all four use `read_identity_token_ex`,
the refusal copy says the key may have been retired, and a test rotates and
then calls everything. `undo_file_move` now passes the full original path, so
a move-plus-rename is put back under its old name (a recreated file at that
path 409s rather than being dropped beside). `extend=true` no longer needs a
reason (UX-8's carve-out on the JSON door); the admin 403 says "admins only";
the file-move `editor_media` lookup binds `media_rel_key(from_rel)` (the
filesystem paths stay raw bytes); copying a plan from a wired machine 409s.
Left for the owner (dash-api-6's verifier): with NFD bytes on the NAS itself,
`commands.file_moves` still carries that raw path to Windows machines holding
the NFC spelling, which blocks their half of the move; a command that carries
both spellings is a design question, not a patch.

### CR-110 — the unassigned bucket was fanned out to WIRED machines — FIXED in repo 2026-09-03 (dashboard 0.7.28)
dash-db-1, -2, -3, -4. CR-28's "a base rig can hold no tick" guarded every
write path and not the bucket-inheritance read: `fetch_machine_selections`
handed a `machine=''` tick to a base rig and `_run_enforce` would Syncthing-
share the project with the machine whose tree root is the NAS share (reachable
once an ex-editor machine switches to `mode = "base"`). **Fixed** in the bucket
loop, in `selections_for_machine` (`[]` for a wired machine), in
`copy_machine_plan` (refuses a wired source) and as a belt in `_run_enforce`.
`db.notice()` always looks its id up (`lastrowid` is stale on DO-UPDATE); the
project marker's temp file is written in the parent `Projects` dir and
`os.replace`d across, so Syncthing never sees a `.tmp` in an ignoreDelete
folder; `_file_move_cutoff`'s fallback drops microseconds.

### CR-111 — `DASH_AUTH_METHOD=SMB` refused every login while boot said nothing; OIDC and NAS calls followed redirects — FIXED in repo 2026-09-03 (dashboard 0.7.28)
dash-core-1, -2, -3. `verify_credentials` was the one reader that did not
`.strip().lower()`, so a cased or newline-terminated value booted clean,
described itself as valid, let the wizard create a first admin, then refused
every password. **Fixed**: normalised in `Settings.__post_init__` AND an
unknown-method boot refusal naming the value and `AUTH_METHODS`. The OIDC token
POST and every TrueNAS request refuse a 3xx with the Location named (a 307
from a `client_secret_post` IdP replayed the secret); the discovery GET keeps
redirects on purpose (real IdPs 301 `.well-known`, no credential on that
call). `_validate_csv` refuses `..`, a leading separator and a drive letter
for the two path-list keys; `shared_asset_folders_for` strips `..` too.

### CR-112 — a crashed check read as clean, a raising invariant cleared its own broken subjects and mailed "cleared", STARTTLS never verified the relay — FIXED in repo 2026-09-03 (dashboard 0.7.28)
dash-collector-1..8. `record_invariant_result` deleted every subject row on a
`check_failed` verdict and `run_cycle` closed the notices, so `deliver()` sent
"no action is needed" for a tick still unshared. **Fixed**: the subject DELETE
runs only on a real verdict and a failed invariant's stored subjects stay in
the keep-list. `starttls()` ran with `CERT_NONE`; now `create_default_context`,
a mismatch is an `AlertError` naming the host, and `alerts_smtp_verify_tls`
(default on, a field on the alerts panel) is the explicit opt-out. The weekly
report subtracts crashed kinds from CHECKED AND FOUND NOTHING WRONG;
`_open_subjects` is a `GROUP BY` over `alert_log` rather than the newest 500
rows, so a warn is never muted for ever; the webhook URL is recorded and shown
as its origin only (storage location: owner decision); `machine_disk_low` skips
a reading older than `SILENT_SECONDS`; the two feed kinds read CHECKED on a
site with no feed; the dead first `lane_chip_status` is gone.

### CR-113 — the feed's `current` policy walked past REL-4, and a cards engine that failed to mount kept its threads — FIXED in repo 2026-09-03 (dashboard 0.7.28)
dash-release-jobs-1..6. `_apply_policy` made an already-published build
current through `db.set_current_package`, which checks retraction only, so a
build needing a newer dashboard was CURRENT on the page while `_upgrade_info`
refused to offer it and the fleet silently stopped upgrading; the same build
was re-downloaded in full every check and never staged. **Fixed** together:
`package_store.make_current` is the shared gate (`requires_dashboard` +
retraction), the feed stages a blocked build once with a log line, and
`db.set_current_package`'s docstring says it is not the whole gate. The REL-1
soak gate and UX-9 confirmation on the feed path are an owner decision.
`mount_cards` assigns `app.state.cards_engine` right after `engine.start()`,
so the wrap-failure branch's `stop_engine` finds it; `/cards/api/restart/` is
blocked with the slash; the redirect walk closes its 3xx; `job_age_seconds`'s
docstring matches its (correct) code.

### CR-114 — `assignments.js` had not parsed since 2026-08-28; the offline page was precached with the signed-in user's identity — FIXED in repo 2026-09-03 (dashboard 0.7.28)
dash-mounts-ui-1 (high), -2, -3, -4. Commit 55fdfa7's capacity confirm put two
raw newlines in a string literal; the whole admin assignment matrix is one IIFE,
so every tick, [ ALL ], [ NONE ], copy-plan and the CR-95 re-lock were silent
no-ops in dashboards 0.7.17 through the live 0.7.27. **Fixed** (`\n\n`) and
gated: `test_static_js_syntax.py` runs `node --check` when node exists and
always a dependency-free "no quoted literal spans a newline" scan. `/offline`
renders session-free (no name, no admin drawer, no CSRF token in the service
worker's precache); `dashboard_update.js` reloads on `!resp.ok` or
`HX-Redirect` instead of swapping the login page into the panel; the ingest
header compare is case-insensitive like its three siblings.

### CR-115 — a renamed clip vanished from every client link; an unhealthy llama-server was replaced, never stopped — FIXED in repo 2026-09-03 (broll/web, indexer, companion 0.9.65)
broll-1..5. `client_folder_items` pinned `(video_id, share, rel_path)` once;
the identity re-check that defeats id reuse after `publish_db` read a rename as
"a different clip" and dropped the card. **Fixed**: `client_shares.db` v2 adds
`hash` as a third, rename-stable identity (backfilled, accepted only when it
names exactly ONE video, last in precedence). **Forward only**: an older
broll/web pointed at a migrated data root refuses the ledger. `get_server`
stops the old process before starting a replacement and retries `/health`
once at 15 s, in BOTH the indexer and the companion's vendored copy (the tray
is long-lived and `stop_all_servers` could not see the orphan); the log handle
closes and a hung load is escalated through `ServerHandle.stop()`; both
document-relative URL scans derive from `SHARE_ASSETS`; `add_items` refuses
over capacity up front, naming how many would fit.

### CR-116 — an unmounted music share turned a drop into a false "queued", and a drain rolled the whole library's scores back — FIXED in repo 2026-09-03 (music/web)
music-1..5. `queue_one` did `mkdir` and moved the upload in with no mount
check, so on an unmounted bind mount the bytes landed on the host under the
mountpoint; `allocate_name` never consulted `tracks` and failed open, so a
result could overwrite a live track's embedding under its old id. **Fixed**
with one helper, `config.share_root_ready()`, used by both ingest routes (503)
and by `allocate_name`, which now also checks `tracks`; the first-run `mkdir`
survives only for an empty index. `drain.apply_bundle` skips the library-wide
rescore when the live index's `tagged_at` is newer than the bundle (stdlib
only; the apply runs on the NAS's python); a row failing read-back is rolled
back with a SAVEPOINT (and the outer transaction had to become explicit, or
RELEASE of the outermost savepoint commits half a bundle). `ingest.js` is in
the prefix scan.

### CR-117 — the ytdl DOWNLOAD button 409'd every job created with `local=false` — FIXED in repo 2026-09-03 (ytdl/web, migration 013)
ytdl-web-1 (high), -2 (high), -3. Regression of CR-96, both halves:
`start_download` re-validated with the narrow rule while creation had widened
(and `YTDL_LOCAL_DOWNLOAD` ships OFF, so every editor's create was widened);
the SPA never sent `machine` on a job POST, so the wired-rig picker offered
what the POST refused. **Fixed**: migration 013 persists `created_local` /
`created_machine` on the job row (defaults = the pre-widening pair) and
DOWNLOAD/RETRY pass the JOB's values back, never the request's; both POST
payloads carry `machine` (omitted when unknown); the CR-96 tests post real
bodies. `_record_done` validates the reported filename (`.` and `..` are 400,
not a ledger row pointing at a folder).

### CR-118 — the DSM `.env` writer refused the customer's own NAS password and corrupted others; a failed key rotation reported success — FIXED in repo 2026-09-03 (server/, tools/, CI)
server-tools-1..6. `render_env_file` refused `$` with `openssl rand` advice
that cannot apply to `TRUENAS_PW`, and wrote ` #`, quotes and padding raw for
compose-go's dotenv parser to eat. **Fixed**: every value single-quoted
(literal in compose-go), a `'` refused with wording that distinguishes a
secret we generate from a credential the operator owns, round-trip tests
through python-dotenv. `_install_authorized_keys` was a `;`-list whose rc was
the trailing `chmod`; now `set -e` plus a `grep -qxF` read-back, and a server
test runs the generated script under stub sudo so a failed `mv` surfaces.
`permissions: contents: read` on ci.yml and the four release/android
workflows; `check_licenses` keeps no per-run state on module dataclasses;
`load_secrets.ps1 -Save` never materialises the plaintext; the `synouser`
argv exception is recorded at its site.

### CR-119 — the wizard wrote `canonical_prefix = P:\` on a Q: site whenever one manifest fetch blipped; the uninstaller dropped the SMB block rule with the share still published — FIXED in repo 2026-09-03 (installer 1.0.39)
install-onboard-1..4. `ensure_config` was the one site-value reader with a
hardcoded fallback instead of `cached_site()`, and `onboard.py` passed the raw
`{}` rather than `_site()`; the bootstrap had no `-CanonicalPrefix`/`-TreeName`
flags so it fetched again with its own `P:\` fallback. **Fixed**:
`site_canonical_prefix()` with the siblings' fallback, both flags resolved
flag-first (the manifest's value, never config.toml's), `CCSYNC_CANONICAL_PREFIX`
/ `CCSYNC_TREE_NAME` on macOS, and a test that every manifest key
`run_bootstrap` holds has a flag. `windows_uninstall.ps1` re-reads the share
after the removal attempt through `Test-SmbShareGone` (unreadable = still
there) and gates the firewall rule on the share actually being gone; the
fifth installer test script covers it. `installer_on_forbidden_drive` refuses
under `/Volumes/` on macOS.

### CR-120 — the self-restart's replacement refused its own predecessor's slot, and the machine was left with no companion — FIXED in repo 2026-09-03 (companion 0.9.65)

Seen live on the base rig 2026-09-03 16:34 on the deployed 0.9.63, on the
"Resolve exited, restart so the scripting link starts clean" path
(`upgrade.restart_self`). The owner got the "already running" MessageBox and
had to relaunch the tray by hand:

```
16:34:51,956 INFO ccsync.app: the Resolve this companion was connected to has exited -- restarting the companion ...
16:34:53,097 INFO ccsync.app: single-instance: the slot is held and this build replaces pid 20040 -- waiting up to 90s for it to exit
16:34:53,971 INFO ccsync.upgrade: self-restart: replacement launched; shutting this instance down   <- pid 20040, still alive
16:34:54,350 WARNING ccsync.app: single-instance: pid 20040 is gone but the slot is still held -- a different companion owns it
16:34:54,350 WARNING ccsync.app: another ccsync-companion is already running -- this instance is exiting
```

**Cause**: `_acquire_mutex_win32`'s R11 wait sampled `_pid_is_alive` before
each retry and refused on the FIRST retry after the pid read dead that still
saw `ERROR_ALREADY_EXISTS`, on the assumption that a dead pid has already
dropped its handles. It has not. Windows sets `Process->ExitStatus` at the
START of termination (`NtTerminateProcess` writes it before the threads are
torn down; `ExitProcess` runs every `DLL_PROCESS_DETACH` first), so
`GetExitCodeProcess` -- the whole of `_pid_is_alive_win32` -- answers "dead"
for tens to hundreds of milliseconds while the process still owns the named
mutex. A frozen Python + Tk + ctypes companion tearing down its lanes takes
far longer than the 0.25 s between the liveness sample and the retry. The
replacement gave up 1.4 s in, and the predecessor then completed the shutdown
it had already announced. Same shape as R11's outcome, reached through R11's
own fix. The pid-file path shares the probe but not the failure: a pid file
has no handle semantics.

**Fixed**: the first dead reading now only STARTS a grace period
(`PREDECESSOR_RELEASE_GRACE_SECONDS = 15.0`); "a different companion owns it"
needs the slot to still be held when that grace expires, and the refusal names
how long after the death that was. The 90 s overall deadline is unchanged, and
a slot that frees at any point is taken immediately, as before.
`_pid_is_alive_win32` is stronger too: it opens with
`PROCESS_QUERY_LIMITED_INFORMATION | SYNCHRONIZE` and prefers
`WaitForSingleObject(handle, 0) == WAIT_OBJECT_0`, which is signalled only
once termination is COMPLETE, falling back to the exit code only when the wait
itself fails. Signalled means dead whatever the code says, which also retires
the "a process that really exited with 259 reads as alive" case. Regression
tests in `companion/tests/test_app.py` replay the live sequence (alive, alive,
dead forever, with the mutex held for another ten polls) and the genuine
foreign-holder case past the grace. Ships with companion 0.9.65.

### CR-121 — the /cards page said "claude not available on this server" on a site whose Claude Code was installed and signed in — FIXED in repo 2026-09-03 (dashboard 0.7.28)

Seen 2026-09-03 on a site with `[features] ai_cli_providers` on, Claude Code
installed by the SET UP wizard and signed in on Settings -> AI providers, and
the ytdl service's AI calls working through the same chain. The mounted
Timeline Cards page dimmed all three Claude buttons (translate, semantic
search, section summaries) with that tooltip, and nothing could be started.

**Cause**: `cards_ai.Runner.status()` must never probe (it is read on every
state publish, and a CLI probe is a real one-token subscription call behind a
600 s cache), so it asks `ai_providers.resolved(..., probe=False)`. In
`provider_states` a CLI under `elif not probe:` was a flat `ST_UNKNOWN` with
`available = False`. Availability is a BOOLEAN by the time `resolve_provider`
sees it, so "we did not look" and "there is nothing there" are the same value:
with no API key configured the resolver answered "no provider has a working
credential", `status()` reported not-ok, and every `start_*` in the cards
engine refuses up front on that. The real `run()` path probes and would have
worked, so nothing ever got as far as failing. Unknown is not no.

**Fixed**: `ai_providers.unprobed_cli_state()` answers a `probe=False` read
from what the container already knows, spawning nothing: first the last real
probe, EXPIRED OR NOT (`_cached_probe(name, allow_stale=True)` - a stale
answer is still what the CLI itself said, and refreshing it is precisely the
call `probe=False` exists to avoid), then the wizard's own snapshot
(`cli_tools.setup_snapshot`: installed, or a typed path that is a file, plus
`signin.state == "signed_in"`), which is two small file reads. Either one is
`ST_AVAILABLE` with a detail naming where the answer came from; a negative
cached reading keeps its own `not_installed` / `not_signed_in`; only when
neither source has ever said anything is the row still `ST_UNKNOWN`. A site
with the feature flag OFF is untouched - still `ST_DISABLED`, still nothing
read about somebody's agent binary - and every explicit `probe=True` caller
(the Settings page, its Test button, ytdl's `lookup_payload`) is unchanged, as
is `resolved()`'s pin semantics. `Runner.status()`'s refusal sentence for the
genuinely unchecked case now says Claude Code has not been checked on this
server yet and names Settings -> AI providers [ TEST ], because the page
prints `why` verbatim in the tooltip; a site with CLI providers off keeps the
resolver's own reason. Tests: the wizard-snapshot path, the stale-cache path
(with both subprocess seams booby-trapped, so an unprobed read that spawns
anything fails), the still-unknown path, the off-site path and `status()` at
both ends. Ships with dashboard 0.7.28.


## Timeline Cards, the 2026-09-03 wave (CR-122..CR-137, 2026-09-03)

Nine builders in the **MulticamPipeline** repo, gated together at the end of
the day; the index of all thirteen deliverables is that repo's
`docs/LAYOUT.md`, section **"2026-09-03 wave: what changed"** (with
`docs/PROJECT-FORMAT-PLAN.md` "The sections wave, server half" and
`docs/PERF-HARNESS.md` under it). Nothing below is in THIS repo's code: the
dashboard mounts that tree from `DASH_CARDS_SRC` (`/cards-app`), so every fix
here reaches an editor by **refreshing the NAS cards checkout and restarting
the container** — the runbook is `docs/CARDS_DEPLOY.md`. `/cards`' own
dashboard-side defect today is CR-121 and ships with dashboard 0.7.28, before
this.

### CR-122 — recolouring a section heading turned it into a ◆ bullet, in the page AND in the file — FIXED in the MulticamPipeline repo 2026-09-03 (cards checkout)
Owner: *"If you change the colour of a section from red its whole display type
changes and it becomes a bullet point with a diamond. Sections should keep the
section heading styling in any colour."*

**Cause**: the cut file always knew (`## § Name <!-- Red -->` loads as kind
`section`), but three places re-derived the kind from the COLOUR and one of
them wrote it back: `project_edit.move_marker` rewrote `row.kind` from the
colour on every recolour, so a heading recoloured Red was rewritten as `## ◆`
on disk; `cutlist.from_cards` demoted every non-Blue marker to `## ◆`; and the
served marker carried no kind at all, so the page had `color === 'Blue'` as
its only way to tell a heading from a note. A colour is a property. It is not
a kind.

**Fixed**: every served marker now carries `kind` — `section` / `note` /
`marker`. `ProjectEngine._marker` puts the FILE's own kind on the wire; every
other engine goes through `library_engine.marker_out`, which fills a missing
kind in from the colour with `cutlist.marker_kind` (the legacy reading, kept:
a marker read off a Resolve timeline really is only a colour and a name), so
the key is always present and the page never guesses. `move_marker(...,
color=, kind=)` sets each ONLY when given it; `POST /api/marker` takes an
optional kind in both forms; `from_cards` writes `§` for kind `section` in any
colour; `export_doc` reads the kind too. Page half: `markIsSection(m)` is
`!m.draft && m.kind === 'section'`, the colour becomes the heading's ACCENT
(`--mc`), the old `.ovi.Blue` overview rule is retired (a Blue NOTE is a note
now), and `editMarker` sends the kind back with every recolour so a section
recoloured Red survives even against an older server. Tests:
`tests/test_project_engine.py` (over HTTP: still `## §` in the file, still
`kind: section` on the wire), `tests/test_lane_page.js`.

### CR-123 — a card dragged up into the previous section shunted that section's last card down into the next one — FIXED in the MulticamPipeline repo 2026-09-03 (cards checkout)
Owner: *"If you drag a card up into a previous section, the section boundary
shifts down so the last card of the previous section gets shunted into the
next section."*

**Cause**: `project_edit`'s `_others` / `_weave` anchored every heading (and
every `- (note)` bullet) by its INDEX in the cut sequence — deliberately, to
mimic a Resolve marker holding an absolute frame while the cuts slide past it.
For a DOCUMENT that is the wrong model: `A[c1 c2] B[c3 c4]`, drag c3 above c2,
and B re-inserted at index 2 gives `A[c1 c3] B[c2 c4]`. c2 never moved and
changed section.

**Fixed**: the Head anchor rule. `_anchors(flat, dead=())` records, per
non-cut row, the cut it FOLLOWS and the cut it PRECEDES (surviving cuts only,
the old index as a last resort); `_weave(order, anchors, stable=None)` puts
each row back before the cut it preceded, else after the cut it followed, else
at the index it held — which is what keeps a heading whose whole section was
deleted at the end of the document instead of vanishing. **A cut that MOVED
may not anchor anything**: `reorder` passes the `stable` set from `_stable`
(the longest subsequence still in its old relative order, patience sorting);
every other edit passes `stable=None`, and `delete` passes its doomed cuts as
`dead` so a heading whose first card is deleted lands on the section's next
card. Splitting a section's last card now keeps both halves in that section.
`add_marker` / `move_marker` no longer weave at all — no cut moves when a
marker is added or dragged. An adjacent swap across a boundary is genuinely
ambiguous (two cards, one new order, and the page sends only the order);
`_stable` picks the same reading every time. `api/section_move` is unaffected:
`move_section` lifts the block and never goes through `_weave`. The whole
table of gestures is `tests/test_project_engine.py`'s `(f2)`.

### CR-124 — an AI section summary was orphaned by any trim above it, and by every section move — FIXED in the MulticamPipeline repo 2026-09-03 (cards checkout)
The summaries the page shows on a section are written by a Claude run that
costs real money and real minutes. `LibraryEngine.start_summary` persisted
them into the note store's `summaries` bucket keyed by `str(frame)`, and a
frame is not an identity: a trim anywhere above the heading moves it, and
`api/section_move` moves it a long way. The work stayed in the file under a
frame nothing sat on any more, silently, and the section read "no summary
yet".

**Fixed**: **stored by identity, served by frame.** The key is
`LibraryEngine.section_key(title, seen)` — the section's title, and
`Title#2` for the second of that name in the document, which is exactly how
the page keys `SECCLOSED` / `SECOF`. The entry is `{text, hash, title}` (the
content `hash` that decides `stale` is unchanged). `_load_summaries` reads the
bucket once per timeline and parks numeric keys in `_sum_legacy`;
`_adopt_legacy` migrates one on READ, and only when the title it recorded is
the title of the section on that frame NOW — an entry whose section is gone is
left alone, never guessed at. The WIRE shape is unchanged
(`state["summaries"]["<frame>"]`, derived at publish in `_summary_state`),
because the page looks a summary up by the frame of the marker it is drawing;
each entry gained `title` for a folded section to show. A section that MOVED
keeps its summary; a section that was RENAMED has none, on purpose — it is a
different section, and the words a summary describes are not what that heading
claims to be about any more.

### CR-125 — "clicking add note in this cut does nothing" — the note editor opened outside the card — FIXED in the MulticamPipeline repo 2026-09-03 (cards checkout)
Owner's words, from the desktop page. The note editor was appended outside
`.cbody`, and a desktop card is a **four-column grid**: an un-placed `.note`
auto-flowed into the next free cell, which is the few-pixels-wide colour rail.
The editor existed, had focus and was typing into an element two or three
pixels wide, so the gesture looked like a no-op. **Fixed**:
`page/02-markers.js:editNote` builds inside `.cbody`, with the note and
placeholder CSS beside it in `page/cards.css` (the dated block above the
retired looks). The same class of hiding was checked in the other three
densities.

### CR-126 — the card list stopped answering the mouse until the page was reloaded — `#list.busy` was never cleared on three success paths — FIXED in the MulticamPipeline repo 2026-09-03 (cards checkout)
Found by READING at the gate, not by a test, and it is the most user-visible
thing in the wave. The edit-latency work replaced the class clear in
`render()`'s confirm block and in `poll()` with `savingClear()`, and three
NON-edit routes still set `#list.busy` and relied on that confirm:
`07-conform.js:applyPost` (the library apply and the preview it insists on),
`07-conform.js:undoLibrary`, and `01-state.js:updateFromTimeline`.
`#list.busy{pointer-events:none}` stuck after each of them and the whole card
list ignored the mouse until a reload — while the KEYBOARD kept working,
because `busy()` reads `PENDING`, which WAS cleared, which is exactly the
shape that gets reported as "the page froze, no, it didn't". **Fixed**: each
road clears it on success, and `savingClear()` is now the ONE door every
confirmation and every refusal comes through. Pinned by
`tests/test_page_patch.js`'s last section, which drives all three to a
resolved success AND to a refusal and asserts `#list` carries no `busy` after
each.

### CR-127 — two section headings sharing a frame made the overview's drag a silent no-op — FIXED in the MulticamPipeline repo 2026-09-03 (cards checkout)
In the day's own section-drag feature, found by the gate run. A section with
no cuts under it takes the NEXT section's first cut as its frame, so both rows
carried `data-key="f90188"`; `ovReorder` then read every drop as "dropped on
itself" and the drag did nothing at all — no POST, nothing in the log, no
error on the page. **Fixed**: `renderOverview` puts each section's own key on
the row (`data-skey` — the TITLE, and `Title#2` for the second of that name,
which is `cardItems`' rule and `LibraryEngine.section_key`'s), and
`ovSecKey(el)` is what the drag, the drop line and the phone's tap-to-place
all compare. The wire is unchanged: `api/section_move` still carries frames
WITH their names, which is what tells them apart server-side. The same blind
spot survives in `SECBYFRAME` by construction — CR-136.

### CR-128 — `tests/perf_e2e.js --mount` could not run on Windows at all — FIXED in the MulticamPipeline repo 2026-09-03 (cards checkout)
The dashboard-mount shape of the perf harness — the one that measures Timeline
Cards **as CC Sync serves it** — timed out at exactly 120 s on every run, with
the log showing the cookie, the url and `status=mounted` seconds in.
**Cause**: `spawnLogged` split the child's output on a bare newline, leaving
the CR of a Python child's CRLF stdout on the end of every line, and
`startMount`'s matchers are anchored (`/^\[mount\] cookie=(.*)$/`): `.` does
not match a CR and `$` without `/m` does not match before one. **Fixed**: a
trailing CR is stripped per line and `logApplies` splits on `/\r?\n/` for the
same reason. `--mount` runs now and measures trim p50 98.7 / p95 103.3 ms on
this desktop.

### CR-129 — a phone-layout suite lost 13 checks to a file no run that day had written — FIXED in the MulticamPipeline repo 2026-09-03 (cards checkout, test harness)
`test_edit_view.js`. The agent fixture is reused ACROSS processes and the page
saves its place — including which VIEW was open — into the fixture's own root
as `timeline_place.json`. A run in which some other suite opened the lane left
`view: "lane"` there for every run after it; a phone page then loaded with
`body.lane`, which outranks `body.edv #main{display:none}`, and the edit view
stopped being a full-screen layer. Green alone, red in the gate, for a reason
in neither the page nor the suite. **Fixed**: `run_all.py` deletes
`timeline_place.json` before the agent server starts, and `docs/TESTING.md`
says why.

### CR-130 — two suites read a vault a third suite had already cut down to one cut — FIXED in the MulticamPipeline repo 2026-09-03 (cards checkout, test harness)
`test_page_latency.js` was red on its very first check in every gate run and
green alone: it shares the `project` fixture vault with `test_project_edit.js`,
which runs first and MUTATES it (docs/TESTING.md says so outright) down to ONE
cut, and the latency suite needs clips on the lane to drag.
`test_montage_drag.js` had the same problem for the same reason — no `CARDS[1]`
to drop a search result on. **Fixed**, two ways, deliberately: the latency
suite gets its OWN copy of that vault (a third kind, `project-lat`, the same
builder again, exactly as `project-ro` is) and fits its strip around the
longest clip it can actually see (`FITPICK`) instead of five fixed zooms;
`test_montage_drag.js` stubs every write route and so only needed to run
BEFORE the mutator, which it now does (first row of that kind in `SUITES` —
the reader before the mutator). Its "back on the clip it asks that document"
check also waited a fixed 300 ms for a POST identical to the one before it, so
a slow moment read the previous post and called it a scope that never
switched; it waits for the post it is about now.

### CR-131 — the Timeline Cards feature wave of 2026-09-03 (thirteen deliverables) — BUILT in the MulticamPipeline repo 2026-09-03 (cards checkout)
Not a defect; recorded here because it is what the cards checkout refresh
DELIVERS to editors alongside CR-122..CR-130, and because a page that gained a
categories strip, a playhead and a new palette in one day will generate
support questions. **The index is that repo's `docs/LAYOUT.md`, section
"2026-09-03 wave: what changed"** — thirteen rows, each with its files and its
tests; it is not restated here and it is the thing to read before answering a
question about any of this. The owner's own requests behind it:

* *"right click > add to category"* — categories on the staged shelf, a chip
  strip that filters it, one `## staged - <name>` section per category in the
  file (slice 12; the grammar is `docs/STAGED-AND-BINS-PLAN.md` §9).
* A pasted Obsidian block embed becomes a card (slice 13) — on the shelf when
  the shelf is the tab you are looking at, else after the selected cut.
* The transcript playhead: click the words to place a head, Space plays from
  it, Esc drops it — and **one thing plays at a time**, because the lane and
  the transcript are two clocks over the same words.
* `==highlighted text==` survives the canvas, the file and trim mode (the
  server sends `hl`, already refitted onto this card's text; the `==` never
  reach the page).
* Sections as things, not colours: the per-row section blob, the ruler band,
  folding with the summary on the collapsed heading (CR-122 is the defect half
  of the same wave).
* **The console look is the only look** — `default` / `suite` / `paper`
  retired, `?look=` and `localStorage['cards_look']` gone. Bigger targets came
  with it, which is what CR-135 is about.
* Whisper names the COMPUTER that will run it (the fleet machine list, not a
  free-text box, unless the list is empty).
* **F8, not F12**, for "head to where the mouse is": F12 is DevTools and no web
  page can have it. The owner's mouse back button sends F12, so the
  translation lives in `resolve_lefthand.ahk` (`#HotIf` scoped to Chrome and
  Edge) and nowhere else; Resolve's own F12 is untouched.

Also in it and invisible to an editor except as speed: the edit-latency wave
(the edit POST waits for the apply and answers with the state or a delta,
`#list` is a keyed DOM patch), the four-shape perf harness, an episode-root
switch dropping every per-episode cache, and the EN index made fast. Suite
after the gate: **49 suites, 46 green, 3 red, 2 skipped by design** — the
three reds are CR-137.

### CR-132 — OPEN: two perf thresholds were raised to get off a coin toss, and one clean run is owed
`tests/perf_e2e.js`'s two TRIM thresholds were raised at the end of the wave
because the wave's own code sat exactly ON them and the gate was a coin toss
rather than a measurement: **trim gesture->paint p95 100 -> 125 ms**
unthrottled (measured p95s 99.8 / 102.7 / 103.3 (`--mount`) / 107) and **250
-> 500 ms under `--cpu 4`** (302 / 325.5 / 355.9 / 428.8). Both are the worst
measured p95 of that shape plus 15%, and nothing else in the table moved. The
p50s in the same runs are 89 unthrottled (178 at HEAD `22e3c28`) and 281-303
throttled (938 at HEAD), so the wave's gain is intact and it is the p95 that
is noisy — the throttled one swung 40% across four runs on a box that was also
running other builders' Chromes. **Owed: one clean run on a quiet machine**
(`node tests/perf_e2e.js --standalone --cpu 4`, then `--mount`); if the
throttled p95 comes back near 300, the `--cpu 4` limit should come back down
with it. Read the p50 for the trend — a regression here shows there first.
`docs/PERF-HARNESS.md`, "The two trim thresholds were raised".
Owner confirmed the wave itself on 2026-09-03: "the latency changes really
worked well. No lag now dragging around in the timeline". The clean-machine
run is still owed - a subjective all-clear is not a p95.

### CR-133 — OPEN: an installed cards page still frames itself in the retired look's colours (owner decision)
`cards.html`'s `<meta name="theme-color" content="#15171c">` and the Android
manifest's `#15171c` / `#5b8cc4` (`page.py`) are the DEFAULT look's values;
the page is `#08090b` with a `#ff2140` accent since the console look became
the only look. That meta is what a phone paints its address bar and its task
switcher with, so a page installed from `/cards/` (CR-100) still wears the old
grey-blue. Not changed at the gate because it changes what the installed icon
and the splash look like on **every phone that already has it** — the owner's
call.

### CR-134 — OPEN: a state render wipes the transcript's search results (owner decision)
The results are the PAGE's own — the state carries no `sem` for them — and
`render()` calls `renderSem(d.sem)`, which empties `#semres` for a state that
has none. Not new: a poll did it before the wave too. What IS new is the
timing — the edit-latency wave's POST answers with the state, so a result
dropped onto a cut now takes the rest of the results with it instantly instead
of at the next poll a second later. `test_montage_drag.js` re-seeds its
results to get past it. Left alone deliberately: "keep the results" and "the
state is the truth" are both defensible, and it is the owner's call which the
page does.

### CR-135 — OPEN: the lane bar does not fit a 390 px portrait phone, and the console look made it worse
`test_cards_keys.js`'s "every lane-bar button fits a 390 px portrait phone" is
red at HEAD `22e3c28` too (it needed 419 px there), so it is not this wave's —
but the console look's bigger targets took it from **419 to 427 px** (`--tap`
44 -> 52, and the time field 65 -> 99 px). A real phone-layout defect with a
number attached now, and the phone is how the cards page is actually used.
Nothing in the wave fixed it.

### CR-136 — OPEN: `SECBYFRAME` cannot tell two sections apart when the first has no cuts
The same blind spot CR-127 fixed in the drag, still present in the map: a
section with no cuts under it shares the next section's frame, so two sections
share one `SECBYFRAME` entry. The drag no longer uses it; **folding does**
(`data-sec`), so a folded empty section and its neighbour share a fold state.
Not reached by any check today. Worth a look when someone next touches
folding.

### CR-137 — OPEN: three Timeline Cards suites are red at HEAD `22e3c28`, before this wave
Every red in the gate run was re-checked against a `git archive` of HEAD in a
scratch tree, running HEAD's OWN copy of the suite against HEAD's own page,
and these three are red there too. They are pre-existing, and each is owed a
look by whoever next touches its area:

* **`test_bridge.py`, 3 red** — it hashes `resolve_engine.py`'s methods
  against a `b17a5b5` baseline in `tests/golden/engine_methods.txt`; the
  engine moved and the baseline did not.
* **`test_ui_pass.js`, 9 red** — 9 of HEAD's own 10: the P9 bottom bar (the
  page lands on the `doc` view), P2's drawer groups (seven where P2 wrote
  five), P7's head style, P12's cut line. HEAD's tenth ("P1 the bar itself is
  the nine things README names") is GREEN today, because the overview button
  came back.
* **`test_cards_keys.js`, 4 red** — the transcript picker on `2`, the P1
  lane-icon float, the language toggle, and the 390 px lane bar (CR-135).

Six other reds in the same run WERE this wave's and are fixed above or in
`docs/LAYOUT.md`'s gate section (four tests pinned the retired look's numbers
and now pin the token; two had timing assumptions the wave broke). One
class-D flake is the harness, not the page: `test_project_engine.py` dies
under `--jobs` with `ConnectionAbortedError` because `free_port()` binds port
0, reads the number and CLOSES the socket before the server binds it again.


## Post-deploy pass, 2026-09-03 evening (CR-138..CR-144)

What the shipped 0.7.28 looked like from the operator's chair for an evening:
the home page's PROBLEMS THE SERVER FOUND panel with real traffic on it, the
dashboard log under a human clicking while the fleet reported, and the cards
page open on a real cut list. Seven findings, six of them fixed the same
evening. Dashboard **0.7.29**; the companion stays **0.9.65** (only its tests
changed) and the installer stays **1.0.39**. Two of the fixes are in the
**MulticamPipeline checkout** the `/cards` mount imports, which is another
repo and carries no version of ours - they reach the page only after a
checkout refresh AND a container restart (`docs/CARDS_DEPLOY.md`; Python
modules load once). CR-140 bakes new environment variables into the compose
file, so it needs a `--recreate`; an image-mode deploy already implies one.

### CR-138 - the proxy-pairs invariant called 44 Sony camera proxies broken - FIXED in repo 2026-09-03 (dashboard 0.7.29)
`proxy_pairs` reported 44 orphans in `2026-base-drone/.../Proxy/`, all named
`fx3_*S03.MP4`: Sony cameras write their own low-res proxy beside the original
with an `S03` suffix on the stem, so the file sat in `Proxy/` next to the
generated `.mov` we made from the same clip, and its stem `<clip>S03` matched
no original by construction. Nothing was wrong on disk, and the panel said
something was, 44 times. Owner: "ignore s03 as an exception, this will happen
to a lot of users". **Fixed** in `invariants.py`: `CAMERA_PROXY_SUFFIXES =
("S03",)` and `_proxy_stem_candidates` give a proxy stem a second reading, and
the pair holds if EITHER the literal stem or the suffix-stripped stem names an
original. A proxy whose neither stem exists is still broken - the exception
widens what counts as a match, it does not stop the check. Four tests in
`test_invariants.py` (a camera proxy pairs, a real orphan still fails, both
spellings present, the suffix list is data). `docs/SELF_DIAGNOSIS.md` records
the exception so the next suffix is a one-line addition. **Follow-up
2026-09-03:** once those 20 cleared on the live dashboard the cap revealed the
next 22 subjects, all macOS AppleDouble resource forks a Mac left beside the
proxies it copied over SMB (`2026-creator-profiles-season-1/Interviewees/Creator_Interviews/Proxy/._A001_05181238_C003.mp4`),
so `_is_sidecar_junk` now skips any file whose basename starts with a dot -
`._*` and `.DS_Store` alike - on both sides of the pairing, since a `._` file
is not a proxy and can never have an original.

### CR-139 - three alert kinds fired on the studio's own healthy dashboard - FIXED in repo 2026-09-03 (dashboard 0.7.29)
Three of the forty checks were findings about nothing, which is the way a
panel like this stops being read.

* **`engine_down` for the base rig.** It syncs nothing by configuration, so
  "the sync engine is not running" is its normal state. Nothing in the report
  carries `sync_enabled`, so the fix keys on the machine's ROLE instead:
  `machine_state.mode == 'base'`, with `db.base_only_editors` as the fallback
  for a row written before v22. A REMOTE machine reporting `sync_enabled =
  false` still alerts, deliberately - that one is a problem.
* **`enforce_plan` for an empty held plan.** The collector records the
  enforce dry-run view every cycle, including the do-nothing one, and the
  evaluator read "a plan is held" rather than "a plan differs". It now ignores
  a row with `n_add == n_remove == 0`.
* **`soak_failed` for a build nobody runs.** Staged 0.9.63 had failed its soak
  while 0.9.65 was current; the check now skips a staged row whose version is
  below current (`db.version_tuple`, so 0.9.9 < 0.9.65 reads correctly - the
  two-digit-minor rule).

Six tests in `test_alerts.py`, one per branch plus the two deliberate
non-suppressions.

### CR-140 - `protection_unverifiable` named an environment variable nothing could set - FIXED in repo 2026-09-03 (dashboard 0.7.29)
The snapshot checks `snapshot_tree` and `snapshot_apps` resolve to
NOT CHECKED without `DASH_TREE_DATASET` / `DASH_UPDATE_SNAPSHOT_DATASET`, and
their advice told the operator to set them on the container - but
`install_dashboard_app.py` had no source for either value, so following the
advice meant hand-editing a generated compose file that the next deploy
overwrites. A finding the operator cannot clear is worse than no finding.
**Fixed**: `[tree] dataset` and `[apps] dataset` in the site manifest, and
when they are absent the installer DERIVES them on TrueNAS from
`df --output=source` over the mount point
(`truenas.resolve_dataset(strict=True)`), which returns blank when it cannot
tell rather than guessing a name that would send a snapshot to the wrong
place. Both flow through `compose_config` / `compose_variables` into
`compose.yaml`, `compose.image.yaml` and the golden compose fixture;
`docs/CONFIG.md`, `docs/SELF_DIAGNOSIS.md` and `site.example.toml` document
the keys. The studio's values: tree = `tank/TheCreatorsPool` (hourly, daily
and weekly tasks all exist), apps = `tank` - flat, with **no snapshot task on
it**, so the operator still owes either a task on `tank` or a dataset of its
own for the apps root; the check will now say so instead of shrugging. The
environment is baked at container create time, so this needs a `--recreate`
(an image-mode deploy implies one). 13 tests in
`server/tests/test_protection_datasets.py`.

### CR-141 - `database is locked`, twelve times in 27 minutes, on a dashboard with one human on it - FIXED in repo 2026-09-03 (dashboard 0.7.29)
Twelve distinct `sqlite3.OperationalError: database is locked` failures in 27
minutes of live 0.7.28: `api_report`'s `clear_report_refused`, the session
store's touch, the collector's reconcile `meta_delete`, `/cards/api/state`,
`/partials/fleet-halt-banner`. Every victim was blocked on its FIRST write,
which is the tell: they were not slow, they were queued behind someone else.
The holder is `api_report`, which took ONE transaction per report and inside
it replaced up to `EDITOR_MEDIA_CAP` (2000) plus `MEDIA_TREE_CAP` (4000) rows
**per project**, on ZFS, with `synchronous=FULL`. Not a 0.7.28 regression -
the shape has been there for months; what was new was a human clicking around
the dashboard while the fleet reported. It is NOT the new invariants pass,
which does all of its evaluating before its first write. **Fixed**, all in the
dashboard:

* `api_report` commits after the fleet-state write and again after EACH
  project's media replace. **A report is no longer atomic**: it is 1+N+M
  transactions. That is safe because both media tables are a full replace per
  `(editor, machine, project)` and a half-applied report self-heals on the
  next one - but it is a contract now: a new write in `api_report` goes ABOVE
  the first commit, or is idempotent per project.
* `PRAGMA synchronous=NORMAL` in `db.connect` (WAL already gives us the
  crash-consistency that matters here).
* `busy_timeout` 20 s (`BUSY_TIMEOUT_BACKGROUND_MS`) on the collector's and
  the session store's connections, so a background writer waits instead of
  raising in a user's face.
* `notices.run_checks` commits between checks, so a NAS-mount syscall never
  sits under the write lock.
* `alerts.deliver` commits around each `send()`. Dormant today with
  `sink = none`, a landmine the first time a site configures SMTP.
* INFO logs when a collector poll or a report write exceeds 1 s
  (`SLOW_POLL_SECONDS` / `SLOW_REPORT_SECONDS`) - during the incident the log
  could say a write had failed but not which pass was holding the lock.

11 tests in `test_db_write_locks.py`.

### CR-142 - dragging a section in the overview was refused as "a ripple move" on a plain cut list - FIXED in the MulticamPipeline repo 2026-09-03 (cards checkout)
On a `.cut.md` project, dragging a SECTION in the overview answered "the edit
did not go through in the project file: sections are re-ordered in a cut list:
here that would be a ripple move...". The page draws the grip when a FILE is
open (`state.source`, stamped literally by publish), while `handler.py`'s
`/api/section_move` gate tested `engine.source != "project"` - the cards'
PROVENANCE (project / agent / library), which is a different question with an
overlapping vocabulary. The same wrong test guarded `/api/gap`, `/api/redo`,
`/api/stage_cat*` and the staged `/api/insert`. **Fixed** with one predicate,
`handler.serves_cut_list(engine)` (an open project AND a path), used by all
five. `move_section` itself needed nothing: it was already one revision,
identity-preserving and undoable. Test in `tests/test_handler.py`.
Uncommitted in that checkout; reaches the page only after a checkout refresh
AND a container restart.

### CR-143 - every card in Civil Defence reported `ts_src: srt` - FIXED in the MulticamPipeline repo 2026-09-03 (cards checkout)
Word-level timing was silently absent from a whole cut list. The library is
healthy (word tokens present for all seven interviewees); the file was BORN
that way. NEW FROM CANVAS on the mounted engine ran with no cut list open, and
`_lib` is bound only in `load()`, so `from_canvas` ran with `db=None`, took
the `srt_only=True` path, and wrote a header with `timing: srt`, clip fps
25.0 and no uid. **Fixed**: `new_project` calls `_open_library()` first, and
when a library is CONFIGURED but unreachable the result carries
`report["warning"]`, which the page shows in its confirm (`01-state.js`,
`projNewCanvas`) - a new project silently missing word timing is exactly the
failure this hides. 7 tests in `tests/test_project_picker.py`. Recovery for
the file that already exists is a header edit, `timing: srt` -> `timing:
word`, with the page NOT holding the file; verified on a copy (258 cards came
back on word timing). Owner has not run it yet. Uncommitted in that checkout.

### CR-144 - NOTE: the base rig's 14 "crashes" are all deliberate kills, and five things are the owner's to close
Not a defect in code. All 14 crash reports on the base rig are `UncleanExit`
markers from a companion killed from OUTSIDE: the installer's `Stop-Process`
during upgrades, the Cards test gate sweeping port 8899, and dev restarts. The
newest (15:04:49Z) is the interesting one - `windows_upgrade.ps1`'s
`Stop-Process` landed on the SELF-upgraded instance that had already taken the
slot 15 seconds earlier, i.e. auto-update and the manual upgrade collided and
the manual one shot the winner. Nothing was lost and no fix is proposed, but a
suggestion is left open: a supervisor that could see a deliberate exit code
would clear the run marker, so the next start files no report at all and the
count means something again.

Open for the owner, none of them code:

* ~~`machine_has_plan` for `alex/Razer`~~ - RESOLVED BY DECISION 2026-09-04
  ("it should be fine for a computer to have no projects ticked (aka the
  Razer). Not an error."): the invariant is informational now, reports ok and
  names the computers with nothing ticked, and the open notice clears on the
  next collector pass. Nothing to tick.
* `release_key_backup` - the offline signing key has no recorded backup.
* `restore_drill` - never run against a snapshot.
* `alerts_sink` is `none`, which is what "3 alert(s) could not be delivered"
  means. Vendor-build default; a studio wants SMTP or a webhook.
* The 44 `S03` files themselves. Harmless now that CR-138 pairs them;
  deleting them is optional and buys back a little space.


## Usability + resilience sweep, waves 0 and 1 (CR-145..CR-153, 2026-09-04)

`docs/USABILITY_RESILIENCE_SWEEP_2026-09-03.md` section 5 is the plan: 297
findings from the 15-agent sweep, ordered into six waves so each one is
shippable on its own. **Waves 0 and 1 are built** - nine Opus builders over
disjoint territories, one per theme below. Wave 0 is "the string day": no new
mechanism anywhere, one scan test per surface, and the reason it goes first is
that half the sweep's findings are sentences pointing at menu rows that stopped
existing on 2026-08-27 (CR-88's ten-item tray). Wave 1 is "stop the bleeding":
the S and S/M items where something is being lost, hidden or claimed falsely
today. Waves 2 to 5 are untouched and stay in the plan.

Dashboard **0.7.31** with **schema v47**, companion **0.9.66**, installer
**1.0.40** (all four copies of the installer constant: `windows_bootstrap.ps1`,
`onboarding/steps.py`, `installer/macos_bootstrap.sh` and
`onboarding/build_onboard_macos.spec`).

**Deploy order: the dashboard first, then the companions.** Two things make it
a rule rather than a habit this time. v47 adds the five `machine_state`
loopback columns and `SyncGuardIn.loopback`, and a companion sending a field
the dashboard has not declared has that field accepted (`extra='allow'`) and
then silently dropped, which is exactly how `syncthing_supervisor` was lost for
weeks (SYS-3 / SYNC-8). And the loopback guard section below is what makes the
new report block mean anything on the fleet page. v48 is next.

**A new operator step**, and it is a data-safety one: `server/publish_db.py
--which broll` now TAKES A DRAIN from the live index before it renames anything,
and merges it back afterwards (CR-152). A publish that cannot take the drain
refuses, before any rename. Nobody has to change how they run the command - but
if a publish is ever interrupted between the swap and the merge, the recovery is
`--apply-drain <bundle>` and the bundle is named in the run's output.
`docs/INDEXERS.md` has the procedure.

### CR-145 - about twenty companion sentences pointed at menu rows that had not existed since 2026-08-27 - FIXED in repo 2026-09-04 (companion 0.9.66)
The CR-88 menu reduction moved COPY DIAGNOSTICS FOR YOUR ADMIN, OPEN LOG, SCAN
WHOLE PROJECT, the YouTube items and the whole Advanced submenu into the
Settings window. The copy that tells an editor where to click did not move with
them, and the fix passes that chased individual sentences wrote the new path out
by hand at each site, which is the same failure one menu move later.

**Fixed** with `ccsync_companion/ui_copy.py`: a route into the UI is a constant
there and nowhere else (UX-1, APP-2, CYT-4, CMEDIA-5, and
`NO_SCRIPTING_MESSAGE`). Punctuation is settled too - ">" for a navigation path,
never "->" and never an arrow glyph, because half the copy said one and half the
other. The two rows whose label carries a value (`remove_project`,
`repair_drive`, `finish_grading`) are functions, so a caller that has the name
says it and one that does not gets a placeholder rather than a route reading as
if a project were really called `<project>`.

The rest of wave 0's companion half:

* **APP-3** - a macOS toast is an AppleScript string literal, and a literal
  cannot span a newline. Every multi-line safety toast was therefore silently
  never displayed on a Mac. `tray_native._one_line` collapses newline, tab and
  CR to a single space.
* **APP-4** - Windows balloon text is cut at ~250 characters, at the END, which
  is where the action is. `fit_toast` cuts the MIDDLE instead.
* **APP-10 / SYNC-114 / RES-9 / SYNC-103's dialog half** - a storage vendor's
  name and a hardcoded `P:` in sentences an editor reads. Both are site data now
  (`site.drive_phrase`, `canonical_prefix`), and the scan test fails on either
  coming back.
* **SYNC-104** - the stall watchdog kills a wedged rclone child and writes its
  own sentence into `last_error`; no branch matched it, so the lane line said
  "Something went wrong" while `_stalled_line` three rows below told the truth.
  Same words in both places now, per this repo's tray-line-and-chip-and-log
  rule. **SYNC-105** - which way the drive is gone (unplugged, or mapped
  somewhere else) decides the sentence; "eject it and plug it back in" was
  advice for one of those. **SYNC-108** - `relink_pending`. **SYNC-113** - a
  project slug appeared in tray copy, and an editor has never seen one.
  **SYNC-116** - the tray's most-read line was a developer's parenthetical.
* **UX-4** - `drive_reminder.notify_title` and its Settings-window twin: the
  toast title comes from the site manifest, so it is a function resolved at call
  time rather than a constant baked at import.
* **UX-10** - "(s)" in a sentence a person reads. `ui_copy.count` does the
  pluralisation, and the four call sites in `popup.py` were the visible ones.

`companion/tests/test_sweep_2026_09_04_copy.py` is the pin: **311 cases**, half
of them an AST scan over the package's user-visible string literals (the
`test_no_em_dash.py` walk, with docstrings and log arguments subtracted) and
half unit assertions on the functions that produce the rest, because a sentence
about a misplaced drive is only wrong when the drive is misplaced.
`test_tray_copy_names_real_menu_items.py` checks each route still ends at a row
that exists.

### CR-146 - the dashboard's own deep links, page names and titles - FIXED in repo 2026-09-04 (dashboard 0.7.31)
Wave 0's dashboard half, all copy, one scan test:

* **UX-7 / REL-10** - the setup wizard's next actions named pages that have not
  existed since the 2026-08-18 Settings redesign, and so did two recovery
  details. A task detail is a next action; naming a page nobody can find is
  worse than naming none.
* **UX-8** - two copies of the Settings page list, drifted apart by six pages.
  There is ONE now, `ui.SETTINGS_NAV`, published as a template global.
* **DUI-7** - both of the product's own deep links ([ 3 PROBLEMS ] to
  `/#server-notices`, the halt banner to `/admin/users#admin-fleet-halt`) point
  at panels that arrive a few hundred ms later from an `hx-trigger="load"`
  fetch. A browser scrolls to a fragment once, at parse time, and never retries,
  so the admin landed at the top of the page and had to hunt - in the one moment
  the product most needs to hand them a button. `base.html` now scrolls once
  after a swap, only for a target inside the swapped fragment, so it cannot
  fight a reader who has scrolled away from a polled panel.
* **UX-5** - every browser tab said "CC SYNC" even for a customer whose header
  said their own name. Every `<title>` reads `brand_org` now.
* **DUI-15** - this studio's own tailnet id as a placeholder in the vendor
  build. **UX-6** - "Every check below ran" printed over a panel rendering
  [ NOT CHECKED ]; the line counts the kinds this build actually evaluates.
  **UX-16** - four words for one thing; the product says "computer" to a person
  and keeps "machine" for routes, form fields and columns. **UX-17** - [ UP ]
  and [ UP ON ONE ], two of four spellings of upload-only. **DUI-14** - " -- ",
  the typewriter em dash the em-dash test could not see. **UX-10**'s dashboard
  half, and the **CR-88** route sweep as one constant,
  `health.COMPANION_DIAGNOSTICS_PATH`, re-exported to the templates.

`dashboard/tests/test_sweep_2026_09_04_copy.py`, **191 checks**. Two phrases are
deliberately left alone: **[ MOVE ON THE SERVER AND ON EVERY MACHINE ]**, which
says "machine" on purpose and is quoted verbatim in `CLAUDE.md` and
`docs/FILE_MOVES.md`, so changing it would silently unpick a documented
contract; and **" -- " inside Python log strings**, which no user reads and
which the em-dash rule explicitly exempts. The scan subtracts both, and says so
where it does.

### CR-147 - the two web UIs printed a drive letter, a state-machine enum and a model checkpoint id at editors - FIXED in repo 2026-09-04 (ytdl + music web)
* **YTWEB-10** - every no-companion dead end read "The clip is in
  `Projects\Foo\Youtube\bar` on your sync drive (P: on Windows)", and the
  history row rewrote the stored path to backslashes unconditionally. Wrong
  twice: the letter is site data, and half this fleet edits on a Mac where a
  backslash is a legal filename character. This page is served from the NAS and
  cannot know either, so it prints the stored relative path exactly as stored,
  forward slashes, no root, and says "under your sync drive" with no
  parenthetical. `ytdl/web/tests/test_no_drive_residue.py` scans the static
  files and `ytdlweb`'s literals.
* **MUSIC-12** - the ingest cards rendered the server's state machine straight:
  a batch header read `done_with_errors on DESKTOP-7K2`, a track read
  `queued_for_base_rig`. That last is the one an editor most needs a sentence
  for (the audio never left their computer and they must drop it again) and it
  was a bare identifier. Two lookup tables now, held to the Python enums so a
  new state cannot ship with no sentence, with the raw value kept in `title=`
  for support.
* **MUSIC-16** - the header stats line ended with the raw Hugging Face
  checkpoint id, the only place a third party's model name was shown to a
  customer, and one empty-state sentence served all five callers, so a `similar`
  lookup with no neighbours advised rewording a description nobody had typed.
  `music/web/tests/test_plain_words.py` names each retired phrase by its exact
  words, so a failure tells you which sentence came back.

**Still open, deliberately**: the three SPA `<title>` tags still say CC SYNC.
They are static HTML served before any JS runs, and the brand is only known
after the topbar fetch, so fixing them properly means setting the title from
`/partials/topbar`'s payload - a mechanism, which is not what wave 0 is.

### CR-148 - three safety docs told an operator something untrue - FIXED in repo 2026-09-04 (docs)
* **RES-1 / SYS-4** - `docs/GOTCHAS.md` section 15 published the CR-68 guard as
  `is_starting()`, which is the FIRST shipped guard, the one that failed open on
  "no listener" and killed two more launches the same evening. The section now
  gives the four-answer table (READY / STARTING / ABSENT / UNKNOWN), the
  drop-in is `ready_to_connect()`, and it says in words why ABSENT must hold off
  too: `scriptapp("Resolve")` with no server present does not fail fast, it
  blocks ~4 s retrying, so a client that "just checked" is already inside a
  connect loop when the server appears. This matters beyond us - it is the text
  other Resolve clients on the same machine copy from, and a tool advertising
  that it "automatically launches Resolve if it is not running" is the
  highest-risk shape there is.
* **SYS-9** - `docs/BACKUP_RESTORE.md` said `.ccsync-trash` is "never pruned".
  It has been pruned since the CR-48 era: `lane_guard.prune_trash` runs at the
  end of a healthy lane B pass, at most every 6 h, dropping batches older than
  **14 days** and then the oldest until what remains is under **50 GB**. That
  was wrong in the dangerous direction - an admin was told to go looking for a
  copy that had been swept a fortnight earlier. `.stversions/` was in the same
  bullet as "grows forever"; it is staggered with a `maxAge` of **one year**
  (`31536000`), which is what to size a pool against. The "grows forever" list
  is one item now (`.prev-<ts>`), with the dashboard's own `/data/backups/`
  pruning described.
* **RES-21** - `docs/RESOLVE_EDIT_SAFETY.md` documented the 15-minute bar and
  not the daily cap. Both bars are documented now, with where they live on disk
  (`~/.ccsync/state/resolve_auto.json`), that the 15-minute bar is per project
  AND per pass, that the daily cap of **8** unprompted rewrites is per project
  and SHARED by both passes, that it resets at UTC midnight on purpose, and that
  SCAN WHOLE PROJECT and FIX ALL still work while it is spent because they are
  prompted.

**One thing for the owner, not code.** Writing SYS-9 down exposed a
disagreement the docs had been hiding: an editor's undo window is **14 days**
(`.ccsync-trash`) and the NAS keeps **365 days** of Syncthing versions. That is
a 26x gap between "what the person who deleted it can recover" and "what the
server holds", and invariant 8 has no opinion on it. Neither number is wrong;
they were just never chosen together. An owner decision, listed here so it is
not decided by default a third time.

### CR-149 - the tray was green while sync was blocked, and Quit killed a copy in flight - FIXED in repo 2026-09-04 (companion 0.9.66)
Wave 1's companion half. Five things the machine already knew and did not say
or act on:

* **APP-1** - `compute_overall_color` and `_tooltip_text` did not read
  `sync_guard.blocked`. An EULA park, a tripped breaker or a rejected token left
  the icon its normal colour and the tooltip saying "up to date" - a claim made
  without ever asking whether syncing was allowed to happen at all.
* **RES-2** - the popup's buttons stayed live during FIX ALL, so a second click
  started a second copy of the same batch. All three are disabled for the run
  and re-enabled on the same thread.
* **RES-8** - Quit mid-copy took the copy with it. `tray` now asks first, with a
  sentence naming what is in flight, BEFORE `icon.stop()`, which is the point of
  no return. **It fails open**: if the check cannot answer, Quit goes ahead - a
  tray that will not close is worse than a lost copy the fixer can redo.
* **UX-9** - how much this click is about to move, and whether the disk has room
  for it, above [ FIX ALL ]. 0 free bytes means "no answer", never "the disk is
  full", so the line is dropped rather than turned into a false warning.
* **SYNC-103** - `drive_swap.py` read a literal `P:`. Every letter-carrying
  message is a template taking the letter from `canonical_prefix`, including the
  loopback share name and the two destructive commands.
* **CMEDIA-3** - the 8899 loopback was tried ONCE, at start, so quitting the
  program that held the port left the companion believing it was serving.
  Loopback health is in `GET /status` and in `sync_guard.loopback` on every
  report {enabled, bound, port, error, since}, healthy shape included.
* **CYT-5** - the cookie health cache could only get worse: a `stale` record
  with nothing since it stayed stale forever, and the clear path was gated on a
  per-job memo. It recovers now, and a record with no activity for **7 days** is
  reported as `aged`, which is the difference between "your sign-in stopped
  working" and "nobody has used it".

**Not covered by the Quit confirm: consolidate.** It is the other long
media-moving operation, it runs on its own path with its own progress window,
and wiring the confirm to it needs the same live-run registration RES-8 added to
the fixer. Left for wave 3, named here so the gap is not mistaken for coverage.


**Follow-up 2026-09-04 (found by the 0.9.66 CI build, run 33788381735, not by the local gate):** the CMEDIA-3 retry gave the loopback bind a second caller on the media-tree thread, racing `start()`'s own bind; when the retry won (the macOS runner did, this box did not) the second bind hit EADDRINUSE against our own listener and wrote None over the live handle - a listener nothing holds, `loopback.bound = false` for ever, and the "old BRoll Companion is holding 8899" advice naming ourselves. `_broll_server_lock` makes the two doors one; `_start_broll_server` never overwrites a live server and refuses after shutdown began. Test `test_the_retry_and_start_are_one_door_not_two`. The Windows runner's red the same run (test_rclone_express, run 33788378020) was the test helper's 0.1 s debounce timer closing the express window mid-loop on a slow disk; the helper now defaults to 30 s and only `_flush_now()` closes it.
### CR-150 - a credential in a polled panel, a wipe with no confirm, and a 600 s download in the event loop - FIXED in repo 2026-09-04 (dashboard 0.7.31, schema v47)
Wave 1's dashboard UI half:

* **DUI-2** - nothing anywhere listened for `htmx:responseError`, and the only
  freshness stamp on the page lived in a topbar rendered once per full page
  load. A dashboard unreachable for an hour kept saying "updated 4s ago".
  `static/htmx_errors.js` is a global handler for `htmx:responseError` and
  `htmx:sendError`; the stamp moved into a polled fragment
  (`partials/stamp.html`).
* **DUI-1** - a one-time password and a one-time fleet token were painted into
  panels `admin_users.html` re-fetches every 30 s / 60 s, and the password came
  back through the `error` key, wearing the warning triangle, in the same
  channel as "does not look like an OpenSSH public key". They are an
  out-of-band swap now (`partials/minted_secret.html`) with a [ COPY ] button
  (`static/copy_value.js`).
* **DUI-4** - no `hx-indicator` and no `.htmx-request` rule anywhere: [ CREATE ]
  blocks for up to two minutes with nothing on screen.
* **DUI-5 / DCORE-2** - [ NONE ] cleared a whole computer's plan with no
  confirmation and named the editor rather than the projects when it failed, and
  "copy from ..." replaced a plan on a `change` event with nothing asked. Both
  get a confirm naming both sides; the copy gets a client-side refusal of an
  empty source AND a **server 409** on one, because a client-side refusal is one
  curl away from bypassed and the route DELETEs the target's whole plan before
  inserting. It also writes one `plan.tick` / `plan.untick` audit row per
  project, in the shape `ui.partial_plan_change_undo` replays, so a copy shows
  in RECENT PLAN CHANGES with a working [ UNDO ] and its removals reach
  `db.recent_plan_change_devices` - the enforce cycle's 60 s grace applies to a
  copy exactly as to an untick. No template change was needed for either.
* **DUI-18** - [ REVOKE ] on an SSH key, [ SET ] on a password and [ DISABLE ]
  all fired on one click, in the panel where [ DELETE ] asks.
* **REL-2** - the HTML [ PUBLISH ] route ran a 600 s download inside the event
  loop, on a `--workers 1` uvicorn: the whole dashboard was unavailable for the
  duration. `run_in_threadpool` there and on the three recovery routes the same
  sweep of `ui.py` turned up.

**Schema v47** lands here too: CMEDIA-3's dashboard half. `SyncGuardIn.loopback`
is declared (undeclared it would be accepted and dropped, the SYS-3 / SYNC-8
mechanism), stored in five new `machine_state` columns
(`loopback_enabled`, `loopback_bound`, `loopback_port`, `loopback_error`,
`loopback_since`) and read back per machine, LATCHED so a machine that takes the
port back clears its own chip. "Send to Resolve does nothing on Ruskin's PC" was
a fault visible only in his browser. **v48 is next.**

Tests: `test_sweep_2026_09_04_dash_ui.py` (**36**),
`test_sweep_2026_09_04_copy_plan.py` (**7**),
`test_sweep_2026_09_04_loopback_guard.py`.

### CR-151 - the alarm pass had no budget, and a secret that could not be saved booted anyway - FIXED in repo 2026-09-04 (dashboard 0.7.31)
Wave 1's dashboard core half:

* **DDIAG-1** - a delivery pass had no bound at all, so a wedged SMTP server or
  a webhook host that blackholes packets could hold the collector cycle past the
  watchdog threshold. `ALERT_CYCLE_BUDGET_SECONDS = 120`, and a pass that spends
  its budget is itself a notice (`alerts_delivery_slow`), cleared when one does
  not.
* **DDIAG-16** - the protection panel had eight lines about safety nets and no
  line about whether anyone would ever hear. There is a ninth now, the
  `alerts_sink` line, and a pass with no sink says **"nobody was told: no alert
  channel is set up"** rather than reading as a broken mail server. The vendor
  build ships `sink = none`, so this is the normal state until a site configures
  one - which is exactly why it has to be said out loud.
* **SYS-2** - a build the vendor offers that this dashboard is too old to
  publish (`requires_dashboard`) was a log line and a silent no-op. It is a
  `feed_publish_refused` notice now, cleared per platform/version; and
  `_check_versions_behind` measures the fleet against the **vendor feed**
  instead of against this dashboard's own shelf, which could only ever say
  everyone is current. `GET .../feed/check` carries `refused`.
* **DCORE-3** - a generated session secret that could not be persisted was one
  warning in a log and then business as usual, working perfectly until the next
  restart invalidated every session. It refuses the boot now, before the
  strength check, on both the app-factory and console-script paths.
  `DASH_DEV_INSECURE=1` bypasses it, as it does the other boot checks, and the
  test suite has to construct a non-dev settings object explicitly because
  `conftest.py` sets that variable at import time.

17 tests in `test_sweep_2026_09_04_dashboard.py`.

**REL-3 and REL-6 are deferred to wave 2** and not attempted here. Both already
exist as mechanisms (the recall flag and the boot-proof retry, from the
2026-08-28 sweep); what the sweep asks for is that each becomes a NOTICE KIND,
and wave 2 is the batch of registry rows where those rows belong, alongside the
mount, ytdl, loopback and jobs kinds. Adding two rows here would have meant
touching `ALERT_KINDS` twice in two days, and a registered kind with no writer
was the self-diagnosis build's own first bug.

### CR-152 - publishing the b-roll index deleted the fleet's ingested clips, and a failed rescore wiped every tag - FIXED in repo 2026-09-04 (server, music, ytdl)
Four data-loss shapes, one theme: a write that could only go one way.

* **BROLL-1** - `publish_db.py --which broll --apply` renames the base rig's
  copy over the live one. The live one is the ONLY place drag-and-drop ingest
  exists: the `videos` rows the dashboard mints at claim time with their
  segments and embeddings, the whole of `ingest_batches` / `ingest_items` (whose
  migration says in as many words that this database is the only place the truth
  about a batch lives), and a `share_roots` row per ingested shoot. The swap took
  the lot, and the 10% shrink guard could not see it - 200 ingested clips against
  a 15,000-clip archive is 1.3%. **Fixed** with `server/broll_drain.py`:
  `publish_db` TAKES the drain out of the live file into a bundle, swaps, then
  MERGES it back in one idempotent transaction. A drain that could not be taken
  **refuses the publish before anything on the NAS is renamed** - a drain that
  could not be taken is not a drain of nothing. Recovery for an interrupted run
  is `--apply-drain <bundle>`. The music index solves this the other way round
  (the base rig exports results, the NAS merges), which b-roll cannot copy
  because its index really is rebuilt on the base rig and really is published as
  a file. `docs/INDEXERS.md` has the operator procedure; 13 tests in
  `server/tests/test_broll_drain.py`, run end to end against real databases and
  asserting what the bug WAS in the window between swap and merge.
* **MUSIC-1** - `write_scores` began `DELETE FROM tags` / `DELETE FROM axes`,
  built every row in Python and committed at the end. sqlite3 auto-begins on the
  first DML, so a failure in between left an OPEN write transaction on the
  thread's CACHED connection, in which the library had no tags and no axes - and
  the fleet ingest handler caught the exception and logged it WITHOUT a rollback,
  so the next write on that threadpool thread committed the wipe. Empty facets,
  for good, with a log line as the only evidence. Now: explicit transaction,
  `rollback()` on any failure, and `scores_stale` left behind and shown on
  `/api/stats`, so a library whose tags are behind says so.
* **MUSIC-5** - every ingest `result` re-scored the whole library and rebuilt
  the whole search index: ~8,700 row writes plus a full matrix read per track,
  so a 200-track album drop was ~1.7M row writes and 200 rebuilds through the
  container's single SQLite writer. Coalesced now
  (`RESCORE_MIN_SECONDS = 60`, `MUSIC_RESCORE_MIN_SECONDS`), forced once at
  `release`. 11 tests in `music/web/tests/test_rescore_transaction.py`.
* **YTWEB-6** - `_note_ok` was the only writer on the live-call path, so the AI
  health cache could only go GREEN. A key later revoked, rate limited or paying
  against an exhausted balance left `claude: 'ok'` for the life of the
  container: the pip stayed green, the pre-submit warning stayed cleared, and
  every search failed twenty minutes in. `recheck_health` could not help - it
  begins "return unless the cache is red". `note_failure` on every `claude_cli`
  path now; `ytdl/web/tests/test_health_recovery.py` ends with the pair of
  directions, red then green again, with no restart.

### CR-153 - the installer said DONE to a machine with no project drive - FIXED in repo 2026-09-04 (installer 1.0.40)
The install and first-run half of wave 1:

* **OPS-1** - the bootstrap's "that drive letter is already something else"
  refusal was the ONLY refusal in the script that did not reach the capability
  channel: it exited 0, so the wizard showed DONE to a machine with no tree
  drive. `New-ForeignDriveMiss` feeds `Add-CapabilityMiss` and the script exits
  **3**, which the wizard renders as **NOT READY YET** with the reason.
  `installer/tests/Test-ForeignDriveMiss.ps1` is a sixth installer script and is
  registered in `tools/run_all_tests.ps1` (the installer row's exit code is now
  the first non-zero of six, not five - `Test-SmbShareGone.ps1` had been
  collapsed into `$LASTEXITCODE` and is captured properly now).
* **OPS-4** - the bootstrap's stdout is streamed into the wizard as it runs,
  instead of appearing all at once at the end. A ten-minute silent install is
  indistinguishable from a hung one.
* **OPS-5** - the log died with the window. It is written to
  `~/.ccsync/logs/onboard-<ts>.log` and the finish page has [ COPY LOG ], with
  the file named at the bottom of the page for the case where the clipboard is
  the thing that failed.
* **OPS-6** - an admin says "the dashboard is nas.tail26290e.ts.net" and the
  editor types exactly that; `urlopen` raised `ValueError("unknown url type")`,
  swallowed into False, so the page said "wait a few seconds and retry" forever.
  A scheme-less URL is normalised (a tailnet name to `https://`, a bare IP or
  `host:port` to `http://`, because that is the container's own port with no
  certificate on it) and the probe returns a VERDICT rather than a boolean, so
  "not reachable" and "reachable but not a CC Sync dashboard" read differently.
* **OPS-21** - `installer/START_HERE.md` is rewritten around the dashboard's
  own [ INSTALLER ] button rather than a shared folder, and says up front that
  Resolve **Studio** is required.
* **OPS-25** - the finish page's two half-truths.

27 tests in `onboarding/tests/test_install_ux.py`, all in `steps.py`: `onboard.py`
is page layout and wiring with no automated tests by design, so anything that
DECIDES something lives on the other side of that seam.

**Left for a real Mac**: OPS-4's progress bar. The macOS bootstrap's long step
is a `curl` whose progress meter writes to the terminal with carriage returns,
and rendering that into the wizard's text widget needs to be watched on the
machine rather than reasoned about from here. The streamed output itself works
on both platforms; it is the CR-rewriting that is unverified.

### CR-154 - the health endpoint reported Syncthing reachable on a dashboard that had never talked to it - FIXED in repo 2026-09-04 (dashboard 0.7.31)
`GET /api/v1/health` answered `syncthing_reachable: true`, and an overall `ok`,
on a deployment with no Syncthing at all. The evidence it reads is "did a
collector cycle that NEEDS Syncthing complete", and the two ends of that
question had drifted: `collector.SYNCTHING_FREE_KINDS` grew from `("prune",)`
to `("prune", "invariants", "alerts")` in the 2026-08-28 resilience sweep, when
the invariants pass and the alerts pass were both given permission to run
without it, while `db.fetch_collector_status` still excluded `'prune'` with a
literal in its SQL. So the first cycle's `invariants` and `alerts` rows - cycles
that by construction prove nothing about Syncthing - were read as proof that
Syncthing had been reached.

In the field that is the wrong direction on three doors at once: the container
healthcheck, `ship.ps1`'s post-deploy poll and the wizard's connection test all
take that endpoint at its word, so a Syncthing-less or Syncthing-broken
deployment looked healthy to every automatic check that exists. Lane C being
dead fleet-wide is exactly what those checks are for.

It surfaced as `test_api.py::test_health_endpoint` failing **only in full
runs**, which is the tell that sent the first look at it in the wrong direction:
it reads as fixture leakage between suites, and it is not. It is a thread race
inside the one test - the collector's first cycle writing an `invariants` row
against the request reading the table - so it appears when the box is loaded
enough for the background thread to win, and never when the file is run alone.

**Fixed** by giving the list one owner: `db.SYNCTHING_FREE_KINDS` is the
constant, `collector.py` aliases it (`SYNCTHING_FREE_KINDS =
db.SYNCTHING_FREE_KINDS`, so the collector's own gate and the query can no
longer disagree), and `fetch_collector_status` filters `NOT IN` off the constant
with generated placeholders rather than a literal. Test in `test_collector.py`,
`test_syncthing_free_kinds_are_not_evidence_of_reachability`, which asserts both
that the two names are the same object's contents and that a row of each free
kind leaves the endpoint unconvinced.

## Usability + resilience sweep, wave 2: the alarm reaches someone (CR-155..CR-164, 2026-09-04)

`docs/USABILITY_RESILIENCE_SWEEP_2026-09-03.md` section 5, wave 2. The
08-28 self-diagnosis layer was found by the sweep to have reached nobody:
forty checks, ten invariants and a weekly report, delivered to a sink that
defaults to `none`, on a home panel whose "what to do" was prose, over a
fleet whose mounts, jobs, refusals and yt-dlp state had no registry row at
all. Wave 2 is that gap, built by ten Opus builders on disjoint files (the
alert registry last, because it reads fields the companion, mount and
rollout builders were adding). Waves 3 to 5 stay in the plan.

Dashboard **0.7.32** with **schema v48** (`companion_packages.made_current_at`,
`machine_state.upgrade_refused_*`), companion **0.9.67**. No installer change.

**Deploy order: the dashboard first, then the companions.** 0.9.67 reports
`sync_guard.upgrade.refused_*` and `sync_guard.ytdlp`, both additive, and the
alert kinds that read them live in 0.7.32; the other way round is harmless
but silent. **Two visible changes on day one for every live site:** the SETUP
badge lights up until an admin sets an alert destination or records a skip
for each of the three gate tasks (CR-158), and the `alerts_sink` protection
line is now `error`, not `warn` (CR-155), so a studio with no sink sees a
red line on the protection page, a standing notice on the home panel and
invariant 15 broken, all saying the same thing on purpose.

### CR-155 - every detector this server has was running into an empty room, and silence meant nothing - FIXED in repo 2026-09-04 (dashboard 0.7.32)

**What was wrong.** Four holes in the one mechanism that delivers all the
others (usability + resilience sweep 2026-09-03, SYS-1 / DDIAG-3 / DDIAG-4 /
DDIAG-16 / DDIAG-17):

* The vendor default is `alerts_sink = none`, which is right, and NOTHING said
  so. The one panel whose stated principle is "a safety net this server cannot
  positively verify renders as MISSING, never as silence" carried lines for
  snapshots, signing keys, backup drills and versioning, and none for the fact
  that no human would ever be told when any of them broke. The only place the
  state appeared was the Alerts page, which is where somebody who already
  trusts the alarm goes.
* A sink that WAS configured and had delivered nothing since March looked
  identical to a working one from every page in the product.
* Every alert is composed and sent by the thing being watched. A container
  that is off, a collector past its restart limit, a NAS powered down and a
  healthy fleet all produced the same experience: no mail. The weekly report
  was the only proof of life and it is a week wide.
* On the vendor default every finding still got an `alert_log` row (ok=0, "no
  sink configured") so the page could answer "why was nobody told" - but that
  row is what `_is_open` and the dedup window read. The day an admin finally
  configured SMTP, every `warn` open since before then counted as already said
  and would never be sent, on the one day the owner is most likely to be
  watching for a first message. 17 of the registry's kinds are warns.
* `machine_silent` is an `error`, and an error repeats once a day for as long
  as it is true, so a laptop that was retired, rebuilt under a new hostname or
  taken on a three-week shoot mailed the owner the same sentence 21 times. The
  fix text never mentioned that the row can be removed.

**What was built.**

* A ninth `ProtectionLine("alerts_sink", ...)`, `error`: "somebody is told when
  this server finds a problem". Green needs a configured sink AND a successful
  send inside 30 days. Its consequence sentence counts `alerts.ALERT_KINDS`
  rather than carrying a number that goes stale.
* `alerts.sink_deliverable(conn, now="") -> (ok, one line in editor English)`,
  the ONE verdict shared by that line and invariant 15 (`alerts_deliverable`),
  so the panel and the invariant can never disagree. It raises rather than
  answering False when the ledger cannot be read, and both callers turn that
  into `[ CANNOT VERIFY ]`: could not ask is never no.
* A dead-man's heartbeat: `alerts_heartbeat` (default off, on the Alerts page
  beside the weekly toggle) sends one short message a calendar day while a
  sink is set, `CC Sync: all quiet - 8 computer(s), 0 problem(s)`, from the
  counts the cycle already has. Owed durably like the weekly report (the DATE
  of the last `heartbeat` row in `alert_log`, in the site's zone), never a
  registry kind, never a raised problem, and NOT the weekly report doubling as
  one. The page says the only thing that makes it worth a mail a day: "If
  these stop arriving, the server itself is down."
* `set_settings` re-opens what was never delivered when the sink leaves
  `none`: those rows are re-filed under `<kind>.undelivered`, so they stay on
  WHAT WAS SENT as the record of a period with no channel and stop making a
  subject look raised. The save answers "Saved. The next check will send
  everything that is currently open."
* `SILENT_GIVE_UP_DAYS = 14`, through a new per-finding `repeat=False` (a
  finding may opt out of its kind's daily repeat; nothing may opt in). The row
  stays OPEN deliberately - a subject that leaves the scan is declared
  RECOVERED, and "this has cleared, no action is needed" about a computer that
  is dead is a worse lie than the daily mail - and the fix now names
  `[ FORGET ]` on the FLEET row.

No migration: `alerts_heartbeat` is a new key with a default in the existing
alerts settings store. `docs/SELF_DIAGNOSIS.md` sections 7, 8a and 14 carry
the rules.

**Tests.** `dashboard/tests/test_alerts.py` (+16: the five `sink_deliverable`
states, the heartbeat's once-a-calendar-day and its absence from the registry
and from CURRENTLY OPEN, the weekly not doubling as it, a warn open under no
sink being delivered on the cycle after SMTP is configured, a change between
two real sinks re-raising nothing, the save sentence on the page, and a
computer silent for a fortnight said once with `[ FORGET ]` in its fix);
`dashboard/tests/test_protection.py` (+4: the line's severity and copy, the
count read from the registry, the shared verdict, and an unreadable ledger
rendering CANNOT VERIFY). 40 + 57 pass in the alerts, protection and wave-1
sweep files; the two copy scans (313) stay green.

### CR-156 - the invariant checker looked only inside the deployment: five more for what the vendor published, what is deployed and what is rendered - FIXED in repo 2026-09-04 (dashboard 0.7.32)
SYS-17 of the usability + resilience sweep 2026-09-03. The ten built
invariants all look at state that has gone wrong INSIDE one deployment;
every recent ledger entry a machine could have caught is about the
relationship between what the vendor published, what this server is deployed
with, and what it renders, and none of the ten looks there. Five rows in
`invariants.INVARIANTS` (the registry is data, so the ledger, the page, the
notices, the alert kind and the weekly report picked them up with no second
edit):

* **11 `fleet_current_with_vendor`** - the newest companion build the vendor
  feed offers is published here and is current. Read from
  `db.get_feed_offered` (the durable `{platform: [version]}` every feed check
  writes, SYS-2's other half) and never from the network: this runs on the
  collector's single thread. NOT CHECKED with no `DASH_RELEASE_FEED_URL`, and
  NOT CHECKED with a feed that has recorded nothing yet, saying which. It
  tells "published but not current" from "never published", and compares
  two-digit minors numerically (0.10.0 is above 0.9.9).
* **12 `dashboard_meets_requirements`** - this dashboard's VERSION is at or
  above the `requires_dashboard` of every non-retracted record in the
  channel. It calls `package_store.blocks_on_dashboard_version` rather than
  comparing again, because a predicate duplicated between the writer and the
  checker is SYS-16's shape, and an unparseable requirement has to block here
  for the reason it blocks at publish time. A record can arrive from a
  restored backup or be left behind by a rolled-back dashboard, and then it
  sits on the shelf for ever with nothing saying so.
* **13 `mount_assets_open`** (CR-100) - every mounted app's installable-app
  files are in `app._OPEN_EXACT`, so the outer `login_gate` does not 303 them.
  Computed from the gate's own set, not by fetching: an HTTP call to
  ourselves from inside a collector cycle is a way to deadlock a worker pool,
  and the fetch proves nothing the set does not. `PWA_MOUNT_ASSETS` is the
  list (the dashboard's manifest and `sw.js`, Timeline Cards' manifest and
  icon), so the next mount that ships a PWA is one row. Deliberately NOT
  narrowed to the mounts enabled at this site: the regression is in the code,
  and a check that only looked at enabled mounts would go quiet on exactly
  the vendor build such a regression would ship in.
* **14 `cards_tree_matches_source`** - registered with a `skip_reason`, like
  invariant 8, because NOTHING RECORDS WHAT WAS SHIPPED.
  `install_dashboard_app.install_tree` uploads the checkout, verifies count
  and bytes, and swaps the directory, keeping no commit id, file list or
  checksum, and `CARDS_EXCLUDE_DIRS` drops `.git`, so the served tree carries
  no provenance either: hashing it would be hashing it against itself. To
  make this checkable the deploy has to WRITE what it shipped (source commit
  plus a per-file sha256 manifest into `<host-root>/cards-web`, or into
  `meta`) and then the check is a walk and a compare. Inventing a source of
  truth here was refused; `[ NOT CHECKED ]` with that sentence is the honest
  page entry, and CR-101 (a hand copy on the NAS with a `.bak` beside it) is
  the fault it would catch.
* **15 `alerts_deliverable`** (SYS-1) - a destination is configured and the
  last message sent to it arrived, through `alerts.sink_deliverable`, reached
  by `getattr` so an older alerts module renders NOT CHECKED rather than
  raising every pass. That helper RAISES rather than answering False when it
  cannot read the ledger, precisely so this renders "not checked" instead of
  inventing "no destination"; `warn`, because a warn is said once and an
  error repeats daily into a channel that by definition is not working.

`docs/SELF_DIAGNOSIS.md` section 13 lists all five, with invariant 14's
missing record written up beside invariant 10's narrowings.

Other sites of this shape: none. The five are the whole of SYS-17's proposal;
`tools/check_mobile_origin.py` still asks only the dashboard's own manifest
(SYS-11's other half, unchanged here).

Tests: `dashboard/tests/test_invariants.py`, fifteen more (53 in the file,
all green). Three existing ones were narrowed rather than weakened: the
empty-database sweep exempts `mount_assets_open` by key and says why (its
subject is the served code, not the deployment's data), and two that asserted
"no `invariant_broken` notice is open" now assert on their own subject, since
a test deployment has no alert destination either and that is a second, real
finding standing open beside the first.

### CR-157 - the alarm panel names pages nobody can click, judges a dead laptop's year-old reading, and never reads this server's own crash files - FIXED in repo 2026-09-04 (dashboard 0.7.32)
Wave 2's self-diagnosis half. No schema change: every fact added here is a
property of the KIND or of state the dashboard already holds.

* **DDIAG-8** - the owner's only alarm panel told a non-technical person to
  navigate by memory to a page whose name was written in prose, three levels
  into a twelve-entry settings strip, when every one of those targets is a URL
  this codebase knows. `NOTICE_KINDS` entries now carry an optional `href`
  (a string, or a callable of the SUBJECT for the kinds whose destination is
  the project the subject names), resolved by `db.notice_href` and rendered
  after the WHAT TO DO sentence as `[ TAKE ME THERE ]`. A column would have
  needed a migration for a fact that never varies per row. **The prose stays**:
  the alert sink mails the same sentence and a mail body has no link to offer.
* **DDIAG-9** - `_check_machine_space` selected `disk_at` and never read it, so
  every `machine_state` row was judged on whatever number it last reported,
  however old: a machine that reported 40 GB free and was then retired held an
  un-clearable warn for ever, because the only way to clear it was for the same
  machine to report again with more space. It now skips (and therefore clears)
  a reading older than `MACHINE_DISK_STALE_HOURS = 48`. That is its own line,
  not alerts' gone-quiet line: this is not "could not check", it is "this
  reading is not about now", and a silent machine is `machine_silent`'s
  business - saying it twice in different words is worse than saying it once.
* **DDIAG-3 (the notice half)** - a machine silent past
  `SILENT_GIVE_UP_DAYS = 14` becomes one standing `machine_forgotten` (warn)
  naming the editor, the computer and when it last reported, with the action
  nothing had ever pointed at: FLEET, `[ FORGET ]` on its row. It clears when
  the machine reports again or when the row is forgotten. The alert side gives
  up at the same threshold.
* **DDIAG-7** - each of `/broll`, `/music`, `/ytdl` and `/cards` computes a
  careful tri-state with a sentence in `detail`, and that sentence reached the
  container log and the authenticated health body only; on the page the topbar
  link simply disappeared, so "where has B-ROLL gone" had no answer anywhere.
  `feature_not_mounted` (warn, subject the mount name) is written per mount
  that is not `mounted`, from `mount_status.snapshot()`. That module is
  imported defensively: with no `mount_status` in the build nothing is written
  AND nothing is cleared, and the kind renders `[ NOT CHECKED ]`, because a
  status this pass could not read is not evidence the four pages are up.
* **SYS-1 (c)** - while `alerts_sink` is `none`, `alerts_sink_none` (warn)
  stands open on the home panel: "Nobody is being told when this server finds
  a problem." Forty checks, ten invariants and a weekly report ran into an
  empty room on the vendor default, and the panel whose premise is that an
  unverifiable safety net is reported carried no line for the one that
  delivers all the others. Clears the moment a sink is set.
* **DDIAG-10** - `crash_report.py` has written `<data>/crashes/*.json` since
  2026-08-17 and nothing ever read that directory: the collector thread dying
  was a fact only somebody with a shell in the container could reach, which is
  exactly the person this product assumes does not exist. `server_crash_report`
  (error) counts the files newer than this process's start - a module-level
  stamp in `notices.py`, because `run_checks` is handed `(conn, settings)` on
  the collector's thread and can reach neither `app.state` nor the app - and
  `GET /admin/diagnostics/crash-reports.zip` (admin only, beside the
  diagnostics bundles) hands over the newest 20, zipped in memory. Nothing is
  written into the data volume to serve it, and the files are NOT re-redacted:
  `crash_report.build_report` passes the message and the traceback through
  `redact` before the file is ever written, so what is on disk is already the
  redacted form and a second pass could only make it less faithful. The button
  shows on the diagnostics panel only when there are reports to send.

Files: `dashboard/src/ccsync_dashboard/{notices.py,db.py,ui.py}`,
`dashboard/templates/partials/{notices.html,admin_diagnostics.html}`,
`dashboard/tests/{test_notices.py,test_notices_sweep_wave2.py}`.

### CR-158 - The setup wizard said Done with nobody to tell, no signing key and no snapshot - FIXED in repo 2026-09-04 (dashboard 0.7.32)

**Symptom.** A new site finished the wizard, saw `Done: OK, setup complete`, and
had: no alert destination (`alerts_sink = none`, the vendor default), so all
forty-odd checks, the ten invariants and the weekly report ran into an empty
room; no `DASH_RELEASE_PUBKEYS`, so every publish 503s and the fleet can never
be updated from that dashboard; and no snapshot schedule, which CR-10 has never
had applied on either of the vendor's own two NASes. All three are named on the
protection panel, which a customer on their first day has not found. The wizard
had a "Protect your data" step and nothing at all for "who should we tell"
(SYS-1, SYS-18, usability sweep 2026-09-03).

**Cause.** `setup_engine.TASKS` held twelve tasks, none about alerting, and
`_check_done` waited only on `outstanding_required`, i.e. the six non-optional
tasks. Everything an appliance customer most needs and is least likely to do
unprompted was optional, unmentioned and invisible.

**Fix.** A thirteenth task, `alerts` ("Who should we tell?"), takes ONE
destination on the wizard (an email address reusing the existing SMTP settings
shape, or an https webhook) through `alerts.set_settings`, with
`[ SEND A TEST ]` on the same code path as the ALERTS page's own test button
(`compose_alert(KIND_TEST)` + `alerts.send`, dedup off). An address saved with
no mail server behind it is a `warn` naming the missing piece and pointing at
Settings, then ALERTS, never a green tick. A fourteenth task, `release_key`,
reports the signing key by COUNT only. `GATE_TASK_IDS = (release_key,
snapshots, alerts)` is the first-boot completeness gate: `_check_done` refuses
while any of the three is neither satisfied nor explicitly accepted, and names
what is outstanding by TITLE, with the wizard linking each name to its row.
`[ SKIP - I understand ]` records the acceptance under a second `setup_tasks`
row (`skip:<id>`), because the task's own row is what the next CHECK
overwrites with the state of the world, and a decision that un-does itself on
a button press is not a decision. A skip cannot turn any protection line
green: `protection._check_release_keys`, `_check_snapshot_*` and
`_check_alerts_sink` read the settings, the NAS's own task list and
`alert_log`, never `setup_tasks` (pinned by a test).

**Files.** `dashboard/src/ccsync_dashboard/setup_engine.py`,
`setup_routes.py` (`POST /api/v1/setup/alerts`, `POST /api/v1/setup/alerts/test`,
`gate` / `skip_recorded_at` / `outstanding_for_done` on the task list),
`dashboard/templates/setup.html`, `dashboard/static/setup.js`,
`dashboard/tests/test_setup_engine.py`, `dashboard/tests/test_setup_routes.py`.

**No migration.** The skip record uses the existing `setup_tasks` store under
an id nothing else walks.

**Watch for.** A dashboard deployed to an existing site now reports the wizard
as unfinished until an admin either sets a destination or presses
[ SKIP - I understand ] on each of the three. That is the point, but it means
the SETUP nav badge lights up on every deployment on the day this ships.

### CR-159 - a machine that REFUSED a build, and a yt-dlp past its shelf life, told nobody - FIXED in repo 2026-09-04 (companion 0.9.67)
Wave 2's companion half: two states the machine already knew and reported
nowhere.

* **REL-3** - an offer refused at RECEIPT (a rejected signature, a build below
  this machine's downgrade floor, a wrong kind/platform record, plain HTTP to a
  public host) makes no attempt, so REL-8's counters stayed all-zero and the
  Packages page rendered a machine that can never take a build identically to
  one that had simply not reported yet. The only evidence was one `log.error`
  in that editor's `companion.log`. `UpgradeManager` now remembers the verdict
  (`last_refusal`, read through `refusal()`), the report carries
  `sync_guard.upgrade.refused_version` / `refused_reason` / `refused_at` (null,
  never absent), and diagnostics names it. It **self-clears** on the next
  accepted offer and once the machine is running the refused version: a
  `[ REFUSING 0.9.65 ]` chip beside a machine already on 0.9.65 is the alarm
  that cries wolf.
* **REL-3 (retry)** - `_run_auto_update` / `_run_pushed_update` re-armed a
  refusal every flat 600 s for ever, because "no-offer" is not "failed". A
  refusal now backs off on the failed-attempt curve (10 min, 1 h, then 6 h)
  and is deliberately **NOT written to the attempts ledger**: nothing was
  downloaded, and `[ FAILED xN ]` has to keep meaning "N downloads went
  wrong". A withdrawn offer keeps the short flat timer - there is nothing
  wrong with that machine.
* **CYT-7** - the max-age rule (08-28 YT-1) detects a yt-dlp drifting past its
  shelf life and publishes it with `ok=True`, which is honest (it can still
  probably download) and is exactly why nothing surfaced it: `capabilities()`
  only reads `ok`, there was no tray line, and the manager's status was not in
  the report at all. The verdict went to one INFO line a day in a log nobody
  opens, so the first person to learn was the editor whose download failed.
  Now: `sync_guard.ytdlp` {version, action, ok, stale, age_days, message,
  checked_at}, **absent** when the manager never published one (absent must not
  read as stale); `capabilities().warning`, which never refuses the job; and one
  Settings > YOUTUBE line ("YouTube downloads on this computer may start
  failing: the downloader is 43 days old and could not update itself").
  `stale` is `action == "stale"` alone - a machine with no usable binary at all
  is a different alarm.

The dashboard half (the `[ REFUSING ... ]` chip and the `upgrade_refused` /
`ytdlp_stale` alert kinds) is B2's; the fields are additive inside the existing
`guard` dict, so an older dashboard ignores them.

### CR-160 - a mount that did not take said so nowhere a human looks, and the unblock plugin's install failed into a log - FIXED in repo 2026-09-04 (dashboard 0.7.32, ytdl web)
Wave 2's "the alarm reaches someone" half for the four optional mounts:

* **DDIAG-7 / BROLL-2 / MUSIC-10** - `/broll`, `/music`, `/ytdl` and `/cards`
  each computed a careful tri-state, and only `mount_cards` returned the
  SENTENCE that went with it. The other three ended in a `log.error` inside the
  container and a topbar link that silently disappeared, so an editor asking
  where B-ROLL had gone had no page that could answer and the forty-kind
  self-diagnosis registry had no evidence to read. `mount_broll`, `mount_music`
  and `mount_ytdl` now answer `(status, detail)` exactly as `mount_cards` does,
  with a sentence on every non-mounted branch (vault/data root not writable by
  the container's uid, checkout did not import, site switch off, no usable
  ingest token). The boot block records all four in a new module-level registry,
  `mount_status.record/snapshot`, which the alert checks and the notice writers
  read from the collector thread with no app object in hand, and
  `GET /api/v1/health` gained `mounts: {name: {status, detail}}` beside the
  existing `cards` block. `app.state.*_status` / `*_mounted` are unchanged, so
  `ui.py` and the topbar are untouched; `*_detail` is new beside them.
* **MUSIC-10, second half** - `publish_db --which music` can land a `music.db`
  written by a newer musicweb. `musicweb.db.ensure_schema` then raised inside
  EVERY request while the mount reported MOUNTED and the nav went on offering
  the link. The mount's storage probe already ran that check; it now recognises
  the refusal and reports DEGRADED at boot with `the music database was written
  by a newer version of the music app than this server runs`, and b-roll's
  identical guard is handled the same way.
* **YTWEB-5** - the deployment's real PO-token path is the pip-installed
  `bgutil-ytdlp-pot-provider` plugin, not the sidecar `pot_provider` reports on,
  and its boot install failing was invisible to every health key: CR-73 (DNS not
  up in the container's first seconds) and CR-84 (`[Errno 13]` into a read-only
  `/venv`) each ran for days behind four `run.sh: WARNING:` lines, with editors
  seeing 1.8 MiB/s downloads and "the downloaded file is empty". `run.sh` now
  writes `<data>/unblock-site/plugin_install.json`
  (`{ok, error, at, attempts, version}`, pip's own last words included) on
  SUCCESS as well as on failure - a marker that exists only when things are
  broken cannot be told from a run.sh too old to write one - and exports its
  path as `YTDL_PLUGIN_INSTALL_MARKER`. `/ytdl/api/health` gained
  `plugin_install: {ok, state, error, at, attempts, version}`, where `ok: null`
  means NOT CHECKED and never OK, and the SPA's "no PO-token sidecar is
  configured. That is normal" tooltip - flatly untrue on exactly the boots that
  mattered - is replaced by the plugin's failure when there is one.
* **YTWEB-2 (prep)** - every ytdl signal an owner needs (`yt_dlp_stale`,
  `yt_dlp_age_days`, `pot_provider`, `cookies_state`, `last_download.ok`,
  `canary.last`, `claude`, `worker_alive`, `plugin_install`) was computed on the
  health ROUTE and therefore visible only to an editor who opened /ytdl and read
  a pip's tooltip. The body is built by `ytdlweb.routes_api.health_snapshot(app,
  *, allow_probe=True)` now, and the dashboard reaches it in process through
  `ccsync_dashboard.ytdl.health_snapshot(app) -> dict | None` (None when /ytdl is
  not serving). `allow_probe=False` on that path: the PO-token answer is the last
  cached one, because a collector cycle that can make itself slow while
  diagnosing is one somebody turns off, and nothing there imports `ytdlweb` - an
  off site pays no yt-dlp import, which is what the site switch is for.

Nothing added here can raise out of the boot block: `_record_mount` swallows
everything, the registry's `record()` cannot throw, and the health block falls
back to `app.state` for a mount that never recorded.

### CR-161 - the JOBS page hid everything that failed, and had no way to try it again - FIXED in repo 2026-09-04 (dashboard 0.7.32)
Wave 2's fleet-queue half (DDIAG-11):

* `failed` and `abandoned` are terminal and the page listed OPEN jobs only
  (`db.list_jobs(conn, state="open")`), so a fleet that had just spent its
  retry budget on twelve whisper jobs - one machine with a broken ffmpeg is
  the documented case - showed the operator "Nothing is queued or running."
  No count, no list, no `last_error`, and the only way back was to retype the
  kind, the root, the relative path and the episode from nothing.
* `db.finished_jobs` (terminal states, window on `updated_at` so a job queued
  on Monday and abandoned an hour ago is news this morning) and
  `db.count_abandoned_jobs`, both 24 h by default. The count is on every
  render of `[ THE QUEUE ]`; the list only when asked for.
* `[ SHOW FINISHED ]` on the JOBS page: state, kind, the (root, relative
  path) pair, WHO held it last, when, and the **whole** `last_error` and not
  the open list's 120-character slice - the sentence ffmpeg wrote is what
  tells "this clip is bad" from "that computer is broken". An empty queue
  with abandoned work now says so in its own line instead of stopping at
  "Nothing is queued or running."
* The 15 s poll MOVED from the page's wrapper div onto the partial itself, so
  it re-emits its own URL with the toggle in it. A wrapper polling a fixed URL
  closed the finished list every 15 seconds.
* `POST /api/v1/jobs/{id}/retry` (admin, the cancel gate exactly) and
  `[ TRY AGAIN ]` / `tools/jobs.py retry <id>`: the same kind, inputs,
  requires, cost, priority and section 10 levers under a NEW id, with
  `inputs.retry_of` naming the origin. **The old row is left exactly as it
  was** - the attempt history is the only evidence anybody has for a bad clip
  as against a broken machine, and a retry that reopened the row would erase
  it. Two 409s, both sentences: a job that has not finished (nothing forces a
  row terminal behind a live ffmpeg, so it is cancelled first) and a job whose
  previous retry is still on the queue.
* No migration: a retry is a new row, and `retry_of` rides `inputs`, which
  every runner reads by key and ignores what it does not know.
* `docs/API.md` §6c documents the route and the field.

### CR-162 - the chaos suites were parameterised over the sweep before last, so nothing in CR-125..CR-154 had an injection - FIXED in repo 2026-09-04 (tests)

SYS-10, wave 2. Against ~10,600 test functions in 421 files this repo had 28
fault injections, and all 28 were written against the shapes of the 2026-08-28
sweep. Since then CI found four defects in one run (CR-94) and the chaos
suites found two the five build packages had missed (SYS-18a/b) - and
**everything else in the last thirty entries was found by the owner using the
product**. So the two chaos modules got a sibling each, written against the
newer ledger on the same two rules: every assertion is an OBSERVABLE (a
notice, a refusal, a safe state - never a log line, which is UX-10's whole
point), and nothing sleeps, spawns, opens a window or reaches the network.

**Ten shapes, in `dashboard/tests/chaos/test_fault_injection_wave2.py` (28
tests) and `companion/tests/chaos/test_fault_injection_wave2.py` (12):**

* **SYS-2** - a vendor build whose `requires_dashboard` is above this
  dashboard is staged and never made current (REL-4's refusal, correct), and
  the site then reads as fully up to date everywhere while the whole fleet has
  stopped updating. Parameterised over an above-us requirement, an
  UNPARSEABLE one (which must also block) and an ordinary one (which must stay
  silent, or the banner cries wolf the way CR-139's three findings-about-
  nothing did). Asserted as the `feed_publish_refused` NOTICE plus
  `db.get_feed_offered`, never the log line that was the only statement
  before wave 1 - and a second test that it CLEARS once the dashboard is
  updated (CR-140: a finding the operator cannot clear is worse than none).
* **CR-100 / SYS-11** - a phone fetches a manifest with no cookie jar.
  Parameterised over all six installable surfaces, `/cards/manifest.webmanifest`
  and `/cards/icon.svg` included: the gate must not answer a redirect, whether
  or not a cards checkout exists on the machine (a 404 still proves the
  request reached routing). The converse pins that opening a manifest did not
  open the app: `/cards/`, `/cards/api/state` and `/settings` still need a
  session.
* **SYS-3 / CR-95** - every `disabled`/`readonly` in `dashboard/templates/` is
  either CONDITIONAL on a name the server computes (found in
  `dashboard/src`, following `{% set %}` aliases one hop, so
  `is_auto` resolves to `setup_routes`' `auto_derived`) or listed in
  `COSMETIC_DISABLES` with a reason. **Seven sites today, zero violations**,
  so the test is green rather than an xfail. The allow-list is keyed
  `template#id-or-name`, not by file, so a new unconditional disable in an
  already-listed template still fails; both branches were negative-tested.
  The two cosmetic entries: the display-only `ai_cli_providers` mirror
  (the real switch is accepting the AI-providers notice) and the EULA
  [ ACCEPT ] button setup.js enables.
* **CR-141** - a report is no longer atomic (1+N+M transactions), which is a
  CONTRACT now. The injection fails the SECOND project's media replace with
  `database is locked` and asserts the first project's rows survived and the
  machine is still on the fleet grid; a second test asserts the self-healing
  half, that the next report fills in what was lost.
* **CR-154** - parameterised over `db.SYNCTHING_FREE_KINDS` itself, because
  the defect was the collector's gate and the query drifting apart: a
  successful cycle of each free kind must leave `/api/v1/health` unconvinced,
  and a real Syncthing-backed cycle must still convince it.
* **CR-149 (the 0.9.66 follow-up)** - the loopback's two bind doors. A
  `broll_server.start` that behaves like the OS (first bind wins, every later
  one EADDRINUSEs) is driven through both orders and then through a real
  two-thread race: one bind, the handle still ours, `loopback.bound` true.
  Plus the shutdown half - a retry during teardown must not re-take the port
  the self-upgrade's replacement is about to want.
* **CR-149 APP-1 / CR-27** - an EULA park and a signed-out machine are each
  named in `sync_guard.blocked` AND take the tray off green with every lane
  idle, which is exactly the state that used to paint green above "up to
  date". The converse keeps green reachable.
* **COMP-CORE-2 / AUDIT_2 CORE-H8** - a pushed update (`commands.upgrade` /
  `auto_update`, neither of which has an editor in scope) arriving mid-popup
  or mid-consolidate is refused and `upgrade.apply` is never reached; the
  same push a minute later installs, because a stand-down is transient.
* **CR-93** - the injection is the COLLECTION itself: a worker thread runs
  `gc.collect()` while another thread's dialog sits in a closure cycle. The
  interpreter must still be pinned afterwards (1.8 MB, deliberate; the
  alternative is `Tcl_AsyncDelete` and no traceback), freeable only by the
  thread that built it, and `release_root` from the wrong thread must destroy
  and free nothing. Fake roots, not real Tk - conftest `_no_real_tk_windows`
  makes a real one a failure and the native proof lives in
  `test_tk_release_native.py` - which is also what makes it identical on the
  macOS runner.

Both modules carry the parent's registry pin (a numbered section per
injection, so one cannot be dropped while the count stays true in the
report). **Nothing here is platform-gated**: no drive letters, no NFC/NFD, no
Tk, no wall-clock sleeps, which is the CR-138..CR-144 lesson (three red macOS
CI builds on tests that assumed a Windows runner). `dashboard/tests/chaos`
43 passed, `companion/tests/chaos` 31 passed.

**CR-101 is not covered**: the page-throttle-after-a-root-switch shape lives
in the MulticamPipeline repo, not here.

### CR-163 - "did it actually reach the fleet" had no answer anywhere, and a computer REFUSING a build looked exactly like one that had not reported yet - FIXED in repo 2026-09-04 (dashboard 0.7.32, schema v48, tools)
Wave 2's release half (REL-6, and REL-3's page half):

* **REL-6** - `ship` ended on a PREDICTION ("editors' trays will offer v0.9.66
  on their next report") and nothing ever said whether they took it. The drift
  doctor's only fleet lines were the per-machine `machine behind:` wall, which
  in the first minute after a ship is every machine in the fleet, i.e. exactly
  what a SUCCESSFUL ship looks like. There was no adoption number on the
  Packages page either, and the one automatic signal (`versions_behind`) needs
  a machine to be three published builds behind, so a fleet that stopped
  upgrading after one release stayed silent for months.
  * schema **v48** adds `companion_packages.made_current_at`: the rollout clock
    had no start time. `published_at` is the signer's, `staged_at` is when the
    bytes landed, and a build can sit staged for a week and be made current in
    a second. Stamped in `db.set_current_package`, the one writer every door
    goes through; **backfilled NULL**, because for a build already current we
    do not know, and a COALESCE onto `published_at` would date a rollout to a
    moment nobody was offered anything - the false "stalled for six days" a
    rollout alert must never invent.
  * `db.rollout_status(conn)` is the one query-only helper the three readers
    share: per (kind, platform) channel, `current_version`, `made_current_at`,
    `machines_total`, `machines_on_current`, `reverts`, `failed_attempts`,
    `behind[]` and `refusing[]`. `behind` is STRICTLY older by
    `version_tuple`, never `!= current`: a base rig running tomorrow's build
    did not fail to upgrade, and counting it as one is how an adoption number
    stops being believed.
  * on the page: a `[ ROLLOUT ]` block above OUT-OF-DATE COMPUTERS
    ("2 of 3 on 0.9.66 (1 behind: ruskin on RUSKIN-PC 0.9.65, 3d ago) -
    0 reverts, 0 failed attempts").
  * in `tools/check_deploy_drift.ps1`: the same line as a `[ ROLLOUT ]` block
    with `-AdminUser`, plus **`-Watch`** - re-read every 60 s, one line per
    pass, until every platform is fully on its current build or Ctrl+C. A
    dashboard that reports no rollout is NOT complete: an absent answer must
    never end a watch with "everyone has it".
  * in `tools/ship.ps1`, after "ship complete": the counts, read from
    `/api/v1/health` on the fleet credential the ship already holds (the
    dashboard login is read inside `build_editor_package.ps1` and never leaves
    it, so a second password prompt at the end of a ship was not an option).
    Health's block carries **counts only, no names**; who is behind stays on
    the admin packages view. Advisory: it never changes the exit code.
* **REL-3 (the page half only; the alert and the companion's report field are
  elsewhere in this wave)** - an offer refused at RECEIPT (`release signature
  rejected`, below the downgrade floor, plain HTTP) makes no attempt, so
  `upgrade_attempts` stays 0 and the machine rendered identically to one that
  had simply not reported yet: `[ 0.9.65 ]`, `[ UPDATE NOW ]`, no chip. v48
  adds `machine_state.upgrade_refused_version` / `_reason` / `_at` as the home
  for `sync_guard.upgrade.refused_*`; the row now carries
  `[ REFUSING 0.9.66 ]` with the reason in the title, and `[ UPDATE NOW ]` is
  replaced by "This computer refuses the current build: <reason>. Pushing it
  again will not change that." - the button queued a request that can never be
  honoured and then said "asked" for ever. Every reader treats absent/NULL as
  "not refusing", never "refusing for an unknown reason", so a fleet of
  companions too old to send the field reads exactly as it did before.


### CR-164 - the job queue, the release channel's own adoption, both yt-dlps, the 8899 loopback and the b-roll platform were in no diagnosis channel at all - FIXED in repo 2026-09-04 (dashboard 0.7.32)
Wave 2's alerts half. Sixteen kinds added to `alerts.ALERT_KINDS` (40 rows
before this wave, 59 after it), each with its writer, each reading state that
already existed and none of them costing the collector a network call, a
subprocess or a walk:

* **DDIAG-2 / DDIAG-6** - grep for `job` in `alerts.py` returned only the
  COLLECTOR's background jobs. The whole fleet queue, whose own module says "a
  scheduler that quietly assigns nothing looks exactly like a fleet with
  nothing to do", was diagnosed on `/admin/jobs` and nowhere else, and nothing
  on the home page links there. `jobs_starved` (warn: the oldest queued job
  over 6 h old whose `reason_code` is `no_capable_machine`, `kind_not_allowed`
  or `halted` - never `all_busy`, `idle_wait`, `fleet_cap` or `cooling_down`,
  which are the scheduler working), `jobs_abandoned` (warn: one finding for the
  24 h window, not one per job) and `jobs_pinned_no_executor` (error: pinned
  work with no Timeline Cards mount behind it, or a row this container holds
  whose heartbeat stopped an hour ago - DDIAG-6's stranding, read from the
  queue because the executor object is on `app.state` and the scan has no app).
  `jobs.explain` is asked about ONE job, the oldest, and only once the six
  hours are up: it reads the whole fleet, and the `Ctx` rule forbids that per
  row. The weekly report gains `JOBS: n queued, n running, n abandoned this
  week`, printed every week including all zeros.
* **REL-3** - a machine that REFUSES an offer (a signature it will not trust, a
  version below its downgrade floor, plain HTTP) makes no attempt, so
  `upgrade_attempts` stays 0 and Packages renders it identically to one that
  has not reported yet; the evidence was one `log.error` in that editor's
  companion.log. B10 added the v48 columns and the readers and **nothing wrote
  them**: `db.store_upgrade_state` predates them. `api._store_upgrade_refusal`
  is the writer (its own statement beside that function, the LATCH rule so a
  computer that stops refusing clears its own chip), `UpgradeIn` grew the three
  fields, and `upgrade_refused` (error) is the alarm. Its fix text says
  [ UPDATE NOW ] cannot fix a refusal, because it cannot.
* **REL-6** - `versions_behind` needs a computer to be THREE published builds
  behind, so a fleet that stopped updating after one release was silent for
  months. `rollout_stalled` (warn) asks the other question, off
  `db.rollout_status`: a channel made current over 48 h ago with a computer
  that has REPORTED since and is still behind. A NULL `made_current_at` is
  "cannot tell" and stays silent rather than dating a rollout to a moment
  nobody was offered anything.
* **REL-13** - the Mac half of every ship was a yellow advisory in a terminal's
  scrollback, twice per ship, and Mac builds have been owed across many ships
  (one Mac sat on 0.9.2 for weeks). `platform_channel_stale` (warn) fires when
  one platform's current build is over 7 days older than the other's by
  `made_current_at`, or more than 2 builds behind when the stamps are missing,
  and its next action is the two Mac commands verbatim.
* **CYT-7** - the yt-dlp max-age rule publishes "43 days old and it could not
  update itself" with `ok=True`, so `capabilities()` never surfaced it, no tray
  line carried it and the report had no field for it. The companion half (B6)
  shipped `sync_guard.ytdlp` and the dashboard ingested nothing: `YtdlpIn` is
  declared now (an extra would have been named in the ignored-sections banner
  and dropped, SYS-3 for the third time) and `api._store_ytdlp_state` files it
  in `meta` under `ytdlp:<editor>/<machine>` - deliberately NOT a column, since
  v48 had landed and this is one opaque verdict two checks read once a cycle.
  `ytdlp_stale` (warn, body is the companion's own message) and `ytdlp_failed`
  (error, no usable binary at all) are kept apart exactly as the companion
  keeps them apart.
* **CMEDIA-3, dashboard half** - `loopback_down` (warn) off the v47 columns:
  the feature is on and the port is not ours. `enabled` false is a choice and
  all-NULL is a companion too old to say, and neither fires.
* **YTWEB-2 / YTWEB-5** - not one of the forty checks was about /ytdl, though
  every signal was already computed on its health route. Five kinds read
  `ytdl.health_snapshot` in process (no probe, no HTTP, no database):
  `ytdl_worker_dead` (error), `ytdl_downloads_failing` (warn, and only when the
  CANARY failed too - one bad video is not a broken downloader),
  `ytdl_pot_provider_unreachable` (warn, `unreachable` only, never
  `unconfigured` or `unknown`), `ytdl_plugin_install_failed` (warn, CR-73 and
  CR-84's four WARNING lines in a container log) and `ytdl_stale` (warn).
  **Nothing alerts on `cookies_state == "anonymous"`**: since CR-80 that is the
  healthy state. That function takes the app object and the scan has none, so
  `alerts._ytdl_health` takes the mount's status from `mount_status` (DDIAG-7's
  registry, built for exactly this reader) and hands it in on a stand-in.
* **BROLL-2** - the b-roll platform's one row in the registry was
  `ingest_staging`, which is about the SYNC drop folder. `broll_batch_stuck`
  (warn: a non-terminal ingest batch with no heartbeat for a day) and
  `broll_share_expiring` (warn: a live client link inside 7 days of expiry, out
  of `client_shares.db` where it lives, never out of `broll.db`) read those
  files on their own READ-ONLY connections and are silent when the mount is
  absent. Its fourth kind, `broll_index_stale`, is deliberately NOT built and
  is named in `docs/SELF_DIAGNOSIS.md` so its absence is visible: the question
  needs a walk of the archive share, and a filesystem walk on the collector's
  single thread is the one thing `Ctx` forbids.

Nothing here duplicates the notices bridge: `feature_not_mounted`,
`alerts_sink_none`, `machine_forgotten` and `server_crash_report` are notice
kinds, and `_check_notices` already carries the error ones to the sink.

Deploy note: the four alarms that read a companion's report
(`upgrade_refused`, `ytdlp_stale`, `ytdlp_failed`, `loopback_down`) stay silent
until the fleet is on a build that sends those sections, which is the correct
direction - an absent section is "that computer has not said", never "it is
fine".


## Usability + resilience sweep, wave 3: the machine says what it knows (CR-165..CR-176, 2026-09-04)

`docs/USABILITY_RESILIENCE_SWEEP_2026-09-03.md` section 5, wave 3: the
shape-A findings, "return it, put it on the report, render it". Seventy-five
findings across sync, Resolve, YouTube, media, dashboard and companion, every
one a fact the machine already computed and never showed. Twelve Opus
builders, partitioned by FILE (tray; settings window + popup; app.py and its
producers; sync/; proxies + fixer + Resolve; cards role + jobs runner;
YouTube + ingest on the companion; ytdl web; music web; b-roll web; dashboard
templates + static; dashboard API + auth), each consuming the others'
contracts through getattr fallbacks so a partial landing renders nothing
rather than erroring. Waves 4 and 5 stay in the plan.

Dashboard **0.7.33**, companion **0.9.68**, ytdl migration 014
(`jobs.claim_free_bytes`). Dashboard first, as always: 0.9.68 reports
`sync_guard.youtube_import`, `capabilities.jobs_gate` and the cards role's
health words, and only 0.7.33 stores them.

Deferred inside the wave, for the next pass: `_describe_no_selection`'s stale
plan sentence (the tray line has it, the sequencer's does not); the DUI-3
five-chip cap and legend; `roll_fleet_back` for non-companion kinds; the
per-clip proxy-refusal log line staying DEBUG on purpose; a halt not stopping
a cards role already up (by design); `/ytdl/fetch` still classifying busy as
failed (one-line `STATE_BUSY` branch in `ytdl_server.build_fetch_response`).

### CR-165 - the tray knew the filename, the folder, the count, the reason and the countdown, and rendered none of them - FIXED in repo 2026-09-04 (companion 0.9.68)
Wave 3's tray half (SYNC-109, SYNC-110, SYNC-112, RES-5, RES-22, CYT-1,
CYT-14, CYT-15, CMEDIA-10, CMEDIA-13, APP-5, APP-6, APP-8, APP-13, APP-14).
Every fact below was already computed on the editor's own machine and shown
only in a log, a report field, or a browser page they had closed:

* **The one silent data-loss shape on lane A now names its file.**
  `_skipped_exists_line` said "3 files on the server have the same name but a
  different size. Your newer version will NOT upload" and stopped; the log
  line beside it named the file AND the two fixes. It now reads
  "... so your newer version will NOT upload (e.g. A001_C003.mov: yours
  3.9 GB, the server's 2.9 GB). Rename yours, or ask your admin to remove the
  server's copy", the tooltip lists up to three, and
  `action_open_skipped_folder` opens the folder the newest one is in.
  `skipped_exists_samples` normalises BOTH shapes: `rclone check --differ`'s
  plain relative paths (every build to date) and the richer
  `{path, local_size, server_size, at}`.
* **`.ccsync-trash` is the recovery story and had no door.** `_trash_line`
  names the folder, the count, the size and the retention ("Copies older than
  14 days are removed automatically" - `prune_trash` deletes by age and
  nothing anywhere said so), and `action_open_trash` opens it, with a balloon
  naming the path when it cannot. `trash_folder()` prefers `app.trash_path()`
  and falls back to `<local_root>/.ccsync-trash`.
* **"Resolve: connected" while a call has been wedged for twenty minutes is
  over** (RES-22). `resolve_bridge_line` reads `resolve_health()`'s
  `wedged_seconds`/`wedged_call`, falling back to `resolve_bridge
  .bridge_activity()` - lock-free by construction and, until now, with no
  status reader at all - and past `BRIDGE_WEDGE_SECONDS` (20) renders
  "Resolve: not answering for 300 s (ImportMedia)". The icon is **amber**
  there, never green: `connected` is a cached fact from the last COMPLETED
  enumeration, so it stayed true for as long as the wedge lasted.
* **The counts reach the editor** (RES-5): the two largest non-zero of
  out-of-tree / missing / wrong-drive / proxies-not-attached go on the Resolve
  line ("Resolve: connected - 3 clips outside the tree, 2 missing"), the rest
  in the tooltip. An editor with 40 dead links had no number anywhere.
* **A running YouTube download is visible from the tray** (CYT-1): the line
  `ytdl_download_line` has always built is in the menu and the tooltip, and
  goes away with the download. Its menu fingerprint is the CLIP ("Downloading
  YouTube clip 3/12"), never the speed or the percentage - a rebuild per tick
  is a menu destroyed under an editor's cursor.
* **...and can be stopped from the machine doing it** (CYT-14):
  "► Stop the YouTube download", present only while one runs, calls
  `app.cancel_local_downloads()` (falling back to `ytdl_executor.stop_all`)
  and answers "Stopped. The server will download the clips this computer did
  not finish." - the lease expires and the server picks up the rest, the
  documented hand-back for everything else.
* **The browser sign-in counts down** (CYT-15): `_youtube_sign_in` passes a
  `progress` callback that takes BOTH shapes - `(elapsed, remaining, phase)`
  and the single message string it shipped with - so the tray line reads
  "Waiting for you to finish signing in in the browser (570 s left)"; the
  opening balloon says "Close the window to cancel."; and a timeout says
  "Nothing was saved: try again from Tray > Settings > Sign in to YouTube."
* **A failed b-roll clip says why** (CMEDIA-10): "3 b-roll clip(s) could not
  be indexed: A001_C003.mov (the source file is not on this machine any
  more), and 2 more". Without `failures` the old count-and-the-log sentence
  stands.
* **A forced fleet job explains itself** (CMEDIA-13): `jobs_forced_line`
  renders `STATE_FORCED`'s own reason - "CCSync is transcribing for the fleet
  while you work because ..." - which is what that state was added for.
* **The lane lines name the broken setting** (APP-5): `validate_config`'s
  sentence was written into the lane detail and returned past, so all three
  lines said "NOT SYNCING (this machine isn't set up yet)" and the key was
  reachable only through a diagnostics blob. Capped at 180 characters.
* **"Sync now" acknowledges** (APP-6): "Sync requested: originals up, proxies
  down" / "Not now: <reason>" from `app.sync_now()`'s dict. A companion whose
  `sync_now` returns None keeps the old silence rather than being given a
  made-up answer.
* **A revoked credential offers the way back** (APP-8): `identity.valid()` is
  a LOCAL check, so a token the server has revoked still reads as signed in
  and the only button anywhere was SIGN OUT. `credential_rejected(guard)` puts
  "► Sign in again (the server rejected this computer's sign-in)" in the menu
  while signed in, and `_reporter_line` says the refusal in one sentence.
* **Restart is a menu item** (APP-13), next to Quit, delegating to the one
  restart the app has (`settings_window.action_restart_now` ->
  `upgrade.restart_self`). Quit's label was false - `identity.json` persists,
  so a restarted companion syncs with no sign-in - and now reads "Quit CCSync
  (nothing syncs until you start it again, or log in to this computer again)",
  which is what the installers' logon entries do (HKCU\...\Run on Windows, a
  RunAtLoad LaunchAgent with no KeepAlive on macOS).
* **"Open my sync drive" says why when it does nothing** (APP-14): a blank
  `local_root` sends the editor to Settings > THIS COMPUTER; a path that is
  not there names itself. Same helper (`_open_path_or_say_why`) behind
  `action_open_trash` and `action_open_skipped_folder`.
* **A day-old sync plan says so** (SYNC-110): "up to date (sync plan from 3
  days ago: the dashboard has not answered since)". `plan_fetched_at` was
  written by selection.py and read by nothing, so a machine running a
  week-old cached plan looked exactly like a healthy one.

New `action_*` (settings_window's buttons call these): `action_open_trash`,
`action_open_skipped_folder(app, snap=None)`, `action_stop_youtube_download`,
`action_restart_app`. New predicates for the same window:
`credential_rejected(guard)`, `skipped_exists_names(guard, samples, limit)`,
`trash_folder(app)`, `resolve_count_phrases(health)`, `resolve_wedge(...)`,
`jobs_forced_line(jobs)`, `ytdl_login_line(state)`.

Every app getter is read through `getattr`, wrapped by `_tray_snapshot`, and
absent means one line fewer, never a placeholder and never a raise: this
lands beside C2's `app.py` work and must be green with or without it.

### CR-166 - the Settings window knew this computer's projects, its Resolve and its fleet work, and drew none of it - FIXED in repo 2026-09-04 (companion 0.9.68)
Wave 3 of the usability + resilience sweep, the tray/window half (SYNC-107,
SYNC-118, RES-5, RES-13, CMEDIA-2, CMEDIA-10, APP-8, APP-9, APP-13). Nothing
here computes a new fact: every value was already in a snapshot, a health dict
or a result list, and was being thrown into a diagnostics bundle nobody opens
unprompted.

* **PROJECTS ON THIS COMPUTER** (SYNC-107) lists `sequencer.project_status()`:
  slug, the MODE in words (`full sync` / `uploads only (no proxies come
  down)`), each lane's state in words and the detail sentence when there is
  one. The only enumeration of this machine's plan used to be the stack of
  REMOVE buttons in ADVANCED, which was also the sole place an editor ever saw
  the words "upload only": inside the label of the button that deletes the
  project. An empty plan says "No projects are ticked for this computer yet:
  tick them on the dashboard" rather than nothing at all.
* **SYNC LANES is ranked** (SYNC-118). The sixteen `_*_line` producers were
  every one appended with `style="warning"` in source order, so a machine
  having a bad week showed a dozen equally loud red lines with the one
  sentence that matters at the bottom, next to "Recoverable files in
  .ccsync-trash: 12 GB", which is not a problem at all. Each producer now
  carries a severity (`blocking` / `warning` / `info`, red / plain / muted);
  identical sentences collapse to one with a count and the HIGHER severity
  wins; six lines are drawn, the rest sit behind "and N more" + [ SHOW ALL ].
  The toggle reopens the window, because every button in this window closes it
  first (the module's one rule) and a toggle that left the editor looking at a
  closed window is a button that appears to do nothing.
* **RESOLVE** (RES-5): connection, the wedged sentence past 20 s, the open
  project, each non-zero count with [ SCAN WHOLE PROJECT ] beside it, the
  proxy-attach summary with its reason, the proxy-gap reasons ("7 proxies
  skipped: this disk is low on space"), the stills instruction, "Checked 10
  min ago" and [ UNDO LAST FIX ]. A count is shown ONLY alongside a scan time:
  with Resolve closed every count is zero, and a zero that means "we have not
  looked" must not render as "nothing is wrong" (`resolve_health`'s own rule).
* **FIX ALL ends with a summary** (RES-13). 158 clips were copied and their
  paths rewritten in the editor's project database and the window simply
  closed. `show_popup` now passes an `on_done`, and after the dispatch returns
  - never from inside it, two Tk roots alive at once is the CORE-H8 hazard -
  a one-button notice says "Fixed N of M, copied X GB, K could not be fixed:
  <first reason>" and "To undo: Settings, RESOLVE, [ UNDO LAST FIX ]". A
  partial run, which keeps its window open to retry, gets the same undo
  pointer in the status block. The summary call sits OUTSIDE the try whose
  except branch auto-skips the whole batch on a headless machine.
* **JOBS** (CMEDIA-2): the gate in words ("Taking fleet work" / "Not taking
  work: you are at the keyboard"), the running job with kind, file and start
  time, [ STOP THIS JOB ], and the last ten with outcome and error. The tray
  offered exactly one job control and no way to see, stop or review the work
  this machine does for everybody else. "There is no fleet job running now" is
  what a stop with nothing to stop says: a `False` must never render as
  "stopped".
* **Failed clips are NAMED** (CMEDIA-10): `ProgressModel` carries
  `failures=[{name, error}]` and the ingest window draws the first five plus
  "and N more" under the bars, the way the fixer dialog has always listed its
  own. The reason was on the item all along and the editor's local surfaces
  reduced it to a count plus "See the log".
* **A refused credential offers the way back** (APP-8): `identity.valid()` is
  a purely LOCAL check, so a token the server has revoked still reads as
  signed in and THIS COMPUTER offered [ SIGN OUT ] and nothing else. When the
  reporter's last status is 401/403 past the failure streak, the section says
  "The server rejected this computer's sign-in, so your admin cannot see
  whether you are syncing" and puts [ SIGN IN AGAIN… ] ABOVE [ SIGN OUT ].
* **The licence refusal names the click that exists here** (APP-9): the
  rendered sentence drops `eula.acceptance_problem()`'s "Re-run the CCSync
  setup wizard to read and accept it" and is followed by [ READ AND ACCEPT THE
  LICENCE ], which is the modal that accepts in one click and starts syncing
  without a restart. `eula.py`'s three sentences are UNCHANGED: they are what
  the log and the report carry.
* **[ RESTART CCSYNC NOW ] is unconditional** (APP-13). Three separate pieces
  of copy tell an editor to restart the companion and the button that does it
  appeared only after a role change nobody has made.

Every one of the three new sections is drawn only when its producer exists
(`getattr`, then a dict test), so a companion whose app half is older draws
nothing rather than an empty section or a traceback; a producer that raises
costs its own section and nothing else.

### CR-167 - the machine knew every one of these and could not be asked - FIXED in repo 2026-09-04 (companion 0.9.68)

Wave 3's producer half (APP-5/-6/-8/-9, SYNC-101/-102/-109/-110/-112/-120,
RES-3/-11/-13/-17/-19, CYT-3/-14/-15, CMEDIA-2/-10/-12/-13). Not one of these
is a new measurement: each fact was already computed on a background loop and
then logged at DEBUG, reduced to a bool, or dropped on the floor between a
`return` and the caller. The work was returning it and putting it on the
report, so the tray (C1) and the Settings window (C1b) had something exact to
render and the dashboard something exact to parse.

* **One contract on the app object**, and every function in it obeys the same
  three rules: it exists, it never raises, and an absent producer is None or
  empty rather than a guess. `sync_now()` (now returns
  `{accepted, reason, lanes}` - additive; the old callers ignored it and still
  may), `sync_now_result()`, `trash_path()`, `trash_summary()`,
  `config_problem_detail()` / `config_problem_details()`, `plan_fetched_at` /
  `plan_age_seconds()`, `youtube_import_state()`, `ytdl_login_progress()` /
  `note_ytdl_login_progress()`, `cancel_local_downloads()`,
  `size_mismatch_samples()`, `shared_folder_problems()`, `repath_events()`,
  `broll_failed_items()`, `jobs_status()` / `jobs_gate()` /
  `stop_current_job()`, `undo_last_fix_available()` / `undo_last_fix()` /
  `undo_last_fix_summary()`, `open_licence_dialog()`, `sign_in_again()`,
  `restart_self()`, `proxy_gaps()`, `stills_state()`. Every delegation is a
  `getattr` against its producer: a missing producer costs the LINE, never the
  window it is in - and these windows are opened because something is already
  wrong.
* **`resolve_health()` grew the seven things "why is my footage offline"
  actually needs** and kept every key it had: `connected` (None until the
  first poll, because "we have not looked" is not "Resolve is closed"),
  `project_open`, `wedged_seconds`/`wedged_call` (`resolve_bridge`'s cached
  in-flight call - the one thread that knows a call is wedged is the one that
  cannot say so), `missing_clips`, `non_canonical_refused`, `proxy_attach`,
  `proxy_gaps`, `stills`.
* **RES-3**: `apply_relinks`' verdict is KEPT. "repointed 3 proxy link(s), 12
  refused by Resolve" was built and thrown away at the call site, so the whole
  attach half of proxies had no surface at all: the generate half has a tray
  line, a window, a toast and a history file, and "why is my proxy not
  attached?" was unanswerable by any human. `proxy_attach.why` names the count,
  the first clip and the usual cause (a timecode that does not match the
  original).
* **RES-17**: `stills.check()`'s return is read. Its "Resolve's preference
  files are not in the expected shape - add `<root>` as a media storage
  location by hand" cannot be actioned by any code, and was logged once per
  process and seen by nobody.
* **RES-19**: MISSING clips are LISTED, not only counted (capped at 50; the
  count stays exact), and `_offered_non_canonical` is re-armed on a FAILED
  relink - only a success may latch, because a success rewrites the clip's
  File Path and the key never comes back anyway. A relink refused because
  Resolve was busy for a second was otherwise never retried for the life of
  the process, and a restart was the only way back.
* **SYNC-110**: `selection.py` reads `fetched_at` back. It had been written
  into the cache since the cache existed and read by nothing in the repo, so a
  machine syncing a week-old plan behind an unreachable dashboard - new ticks
  never arriving, unticks never taking effect - looked exactly like a healthy
  one. `plan_age_seconds()` returns None for "cannot tell", which a caller
  must not render as fresh.
* **SYNC-120**: a drive that stays `not_answering` opens a `drive_reminder`
  episode too. CR-92's reminders were gated on work having been OWED at the
  moment the drive went, so a drive that WEDGES while the machine is up to
  date got one balloon and then silence, indefinitely - the harder of the two
  failures, because an absent drive is obvious and a wedged one is not. Its
  own sentence (`wedged_reminder`), no second balloon at the start, no
  "N still to go" in the tray (nothing is owed), and it ends by itself when
  the state changes. An unfinished-work episode is never displaced by one.
* **CYT-3**: `youtube_import.status()` carries `reason` (the gate state as a
  sentence) and `given_up`, and the report carries
  **`sync_guard.youtube_import {state, reason, pending, at}`** - absent when
  there is nothing to say, which is what clears the chip.
  `docs/API.md` documents it beside the other guard sections.
* **CMEDIA-12**: the `capabilities` section carries
  **`jobs_gate {taking_work, reason}`** - the runner's own verdict, in its own
  vocabulary, so `GET /api/v1/jobs/<id>/why` can print "this machine says:
  user_active" beside the dashboard's reconstruction of it. Absent, never
  guessed, from a companion too old to send one.
* **RES-6 follow-through**: `capabilities._cards_block` was a hard five-key
  allow-list, so the cards role's new `detail` / `gate_state` /
  `last_poll_at` / `last_http_status` never reached the wire. Passed through
  when the role sends them, omitted otherwise; the no-role default keeps the
  five-key `state: "disabled"` shape the dashboard's tests read.
* **SYNC-101 wiring**: lane C is built with
  `shared_folder_problems_fn=self.sequencer.shared_folder_problems`, so the
  shared LUT library failing on a machine finally reaches a lane detail
  instead of a DEBUG line whose own comment called it permanent.
* **CMEDIA-10 wiring**: the b-roll progress window is fed `failures`
  (`progress()['failed_items']`, first five) so the reasons the orchestrator
  already put on each item are drawn under the bars, instead of a count and
  "See the log".
* **APP-9**: `eula.py`'s three refusals name the ONE-CLICK action - "Press
  [ READ AND ACCEPT THE LICENCE ] in Settings, THIS COMPUTER" - not "re-run
  the CCSync setup wizard", which meant downloading the whole installer again
  to produce a three-line JSON file while the machine was already offering a
  modal that accepts in one click and starts syncing with no restart (CR-27's
  lesson: a parked editor needs the SMALLEST action available).
* No migration and no new state file. `restart_self()` is an ALIAS for
  `upgrade.restart_self` with the existing stand-down guard, never a second
  restart path.

### CR-168 - the sync engine knew what was wrong and told nobody - FIXED in repo 2026-09-04 (companion 0.9.68)
Wave 3's sync-engine half (SYNC-101, SYNC-102, SYNC-107, SYNC-109, SYNC-112).
Every value here was already computed somewhere under
`companion/src/ccsync_companion/sync/` and readable nowhere: the reconcile
outcome the sequencer discarded, the project the server renamed under the
editor's feet, the plan this computer is running, the files that will never
upload, and the recovery folder that is the whole "nothing was deleted"
story.

* **A shared or borrowed folder that fails is KEPT, with its reason**
  (SYNC-101). `SharedFolderManager.reconcile` / `BorrowedFolderManager.reconcile`
  have always returned `{id: outcome}` "for the log line and the tray", and
  `sequencer._reconcile_*_folders` called them as bare statements. So an
  editor whose LUT library was never shared with their device had no tray
  line, no lane state, no `sync_guard` field, no dashboard chip and - the
  `not-offered` branch being DEBUG - nothing in `companion.log` either. Both
  managers now hold a `FolderProblems` (in `shared_folders.py`, shared by
  both): a problem outcome is recorded with its reason and its `since`,
  RETRIED ON A BACKOFF (60 s doubling to 30 min, so an approval is noticed
  without a tray restart and a permanently unshared library does not cost a
  pending-folders GET every pass), promoted to a WARNING **in the editor's
  own words** on the third attempt, and cleared the moment that folder
  reconciles. `Sequencer.shared_folder_problems()` is one sentence per
  failure, naming the folder and what to do about it, from both managers.
  A folder held paused because its `.stignore` could not be confirmed is a
  new `unfiltered` outcome rather than an "ok": fail-closed was right and
  invisible. `SyncthingLane` takes an optional `shared_folder_problems_fn`
  and carries the first sentence in `detail`, never in the state - a library
  nobody shared is not a reason to call the lane that IS syncing the
  editor's projects broken.
* **A project the server renamed is recorded, and Resolve is relinked**
  (SYNC-102). `repath.reconcile` paused the folder, moved the editor's whole
  project directory and re-pointed Syncthing with the editor told nothing,
  while every clip in the open project still pointed at the old canonical
  path - so it went offline mid-session with no explanation. Contrast
  `file_moves.py`, where ONE file gets a toast, a relink, an undo journal
  and a retry ledger. `RepathLedger` (last 20 events,
  `~/.ccsync/state/repath_events.json`) records each rename with a sentence,
  and the relink goes through the same code the file-move path uses:
  `file_moves.relink_moved` (lifted to module level for it), i.e.
  `resolve_bridge.replace_clip`, save point and undo journal included, with
  `connect()` still the only caller of `scriptapp` (CR-68). `relinked` is
  `None` when Resolve did not answer the question - closed, or open on
  another project - which leaves the event PENDING, and every later
  `reconcile` retries it, exactly as `_relink_pending_moves` does for file
  moves. **The "leaving the folder PAUSED" branch records why**: that is the
  routine failure (Resolve or Explorer holding a handle) and it left one
  project quietly not syncing with a `log.error` nobody reads as its only
  trace. Nothing in this path deletes and nothing about the repath DECISION
  moved into the ledger: the local Syncthing config is still the state.
* **The plan is readable on the machine that runs it** (SYNC-107).
  `Sequencer.project_status()` is one row per ticked project - slug, label,
  `mode` (`full` / `upload_only`), `state` (`syncing` / `waiting` /
  `paused` / `blocked`), the three lanes and a whole sentence of detail -
  built from `_queue_slugs`, `_slug_to_item`, `_ignores_unconfirmed` and the
  repath ledger. Only the project whose turn it is has live lanes; an
  upload-only tick reads `B: off`, `C: off` and "Uploads only. Proxies do
  not come down for this project", which was the one fact an upload-only
  editor had no way to learn (the words "upload only" appeared to them
  exactly once, inside the label of the button that deletes the project).
* **The upload alarm names the files** (SYNC-109).
  `RcloneLane.size_mismatch_samples()` hands back `{path, local_size,
  server_size}` for up to 20 of the samples `_refresh_size_mismatches`
  already keeps, so "your newer version will NOT upload" - the one silent
  data-loss shape on lane A - can say which files. `local_size` is a stat of
  the copy on this machine and costs nothing; `server_size` is None because
  `rclone check --differ` prints names only and a second NAS listing per
  pass is not worth it for a line that already says what to do.
* **The recovery folder can be named and explained** (SYNC-112).
  `lane_guard.trash_summary(root)` is `{path, count, bytes, oldest,
  retention_days}` from ONE walk, cached 60 s per root and dropped whenever
  a prune changes the folder. `oldest` comes from the batch directory name
  (`_backup_dir`'s own record of when it was made) so "how long have I got"
  is answerable; `prune_trash` is untouched, including its refusal to prune
  anything while the breaker is tripped.

Deploy note: this is companion-side only and additive - every function is
new, every existing return shape is unchanged, and a dashboard that knows
nothing about them is not affected.

### CR-169 - the Resolve half of the companion computed seven diagnoses and told nobody - FIXED in repo 2026-09-04 (companion 0.9.68)
Wave 3's Resolve/proxy half (RES-3, RES-4, RES-10, RES-11, RES-14, RES-16,
RES-22). Every item here is a fact the companion already knew and threw away,
or logged into a 5 MB-rotating file nobody opens:

* **The proxy ATTACH half had no user-visible surface at all** (RES-3).
  `proxy_relink.apply_relinks` built "repointed 3 proxy link(s), 12 refused by
  Resolve" and `app.py` dropped the return; the sentence that IS the answer to
  "why is my proxy not attached" was a WARNING, the per-clip reason DEBUG, and
  the case where the clip already points at that exact file and Resolve still
  will not play it (an unreadable proxy) logged nothing whatever. It now
  returns `attached`, `failed`, `why` (one sentence, None when there is
  nothing to say) and `details` [{clip, reason}] in editor English -
  `REASON_REFUSED` / `REASON_NO_ANSWER` / `REASON_NOT_IN_POOL` /
  `REASON_UNREADABLE`. `ok`, `relinked`, `failures` and `message` keep their
  meanings beside them. `plan_relinks(..., notes=[])` is how the unreadable
  case gets out of a skip that no longer needs a restart to discover. The
  per-clip DEBUG line stays DEBUG: 200 refused clips every 120 s at INFO is
  COMP-MEDIA-5 again with a different level.
* **An admin's [ UNDO THIS CHANGE ] died permanently at the Project Manager**
  (RES-4). `resolve_undo` classified refusals by PROSE, and "no project open
  in Resolve" matched none of the substrings (no "not", and "project open" is
  not "is open"), so the commonest state Resolve is ever in was recorded
  `failed` and never offered again - although the editor opening their project
  is exactly what clears it. `_SCRIPTING_ERROR_MESSAGE` failed the same way
  ("didn't" contains no "not"). `PARK_HINTS`/`RETRY_HINTS` replace the prose
  test, the detail says **parked** and what will resume it, and the ledger
  stores a parked undo as an OPEN one so the machine is asked again.
  `STATE_PARKED` is returned only behind `apply_undo(allow_parked=True)`: the
  wire value is validated against a three-word `Literal` by the deployed
  dashboard (`ResolveUndoResultIn`, v40) and an unknown one would fail the
  WHOLE report for that machine. Turn it on when a dashboard that knows the
  word is deployed.
* **A whole-project proxy scan that raised reported "fully covered"**
  (RES-10). `scan_project` returned the zeroed gap, which is byte-identical to
  "every clip here has a proxy" - the failure direction the feature exists to
  prevent. A gap now carries `error` + `partial`, keeping whatever it had
  counted as a FLOOR rather than a verdict, and the sweep's totals carry
  `unreadable`, `error` and `partial`. A project the walk could not enter at
  all (an unplugged drive is zero iterations, not an exception, because
  `os.walk`'s onerror is None on purpose) is caught by the same test.
  docs/SELF_DIAGNOSIS.md: an unverified check is NOT CHECKED, never OK.
* **`capped`, `low_space` and `truncated` never reached the editor's tray**
  (RES-11). The dashboard could see a low-space machine; the editor sitting at
  it could not, and a clip that failed three times was capped for the life of
  the process with nothing anywhere naming it - a machine reporting "1040
  missing, 0 queued" and nothing else is the 0.6.1 muxer night. `gap()` and
  `coverage()` now both carry the three flags plus `reasons`, one sentence per
  flag, from `ProxyGenerator._brakes()`.
* **CANCEL could leave an unresponsive, unclosable window for minutes**
  (RES-14). `fsrc.read()` cannot be interrupted, so the chunk IS the
  cancellation latency, and it was 8 MB against a Google Drive placeholder
  hydrating at 222 MB per 10 s - while the dialog had already disabled
  STOP/SKIP/CANCEL and could not be closed. Polls are every 1 MB now
  (`POLL_CHUNK_BYTES`), and a read that takes longer than `POLL_MAX_SECONDS`
  halves the next one down to `MIN_CHUNK_BYTES`, so a link four times slower
  than the incident's still answers inside two seconds. `chunk_size` stays the
  unit of PROGRESS reporting, so the bar and the ETA are unchanged. The
  `ReplaceClip` loop consulted the predicate not at all - a clip cut in 50
  places is 50 uninterruptible calls - and now checks between clips, keeping
  the copy and answering `aborted` + `relinked` + `partial_relink`. Nothing on
  that path deletes: the copy landed and the clips already repointed are
  correct. The CORE-H5 bargain (`.ccsync-tmp` + the 0-byte reservation, both
  removed on an abort, never a partial under the final name) is unchanged and
  now pinned by a test.
* **BPG's one actionable instruction was addressed to the editor and delivered
  to a log** (RES-16). The companion opens a Resolve window on somebody's
  machine while they are away, and when the UI-automation press failed the
  only thing between the fleet and hours of no BRAW proxies was a sentence in
  `companion.log` telling a human to click a button. `BpgLauncher.status()`
  carries `needs_editor` (the sentence, or None), cleared the moment a press
  succeeds or answers already-running - so an editor who starts it by hand
  stops being nagged. A Mac never asks anyone: `press_start` answers
  `not-windows` and there is nothing to do about it. The WARNING stays.
* **The tray said "Resolve: connected" through a 20-minute wedge** (RES-22).
  That line comes from the last COMPLETED enumeration, so a wedged
  `ImportMedia` against a share that went away leaves it reading connected
  indefinitely while every Resolve feature does nothing. `bridge_activity()`
  gains `wedged_seconds` (0.0 while a call is merely answering) and
  `wedged_call`, off the same `BRIDGE_WEDGE_SECONDS` the log's wedge warning
  uses, so a status line and the log cannot disagree. Idle is still `{}`.
  Nothing else in `resolve_bridge.py` changed, and nothing here goes near
  `connect()` (CR-68).

### CR-170 - a machine that took no fleet work, or served no cards page, could not say why - FIXED in repo 2026-09-04 (companion 0.9.68)
Wave 3's companion half (CMEDIA-2, CMEDIA-12, CMEDIA-13, RES-6, RES-7):

* `jobs_runner.status()` carries the gate IN WORDS - `gate: {taking_work,
  reason}` from `GATE_SENTENCES`, one sentence per state, in the second
  person. The verdict is the one the LAST tick reached and not a fresh
  evaluation: `status()` runs on the tray's refresh thread, where any I/O
  stalls the win32 message loop (the right-click freeze of 2026-07-26).
  `no_capability` is two different problems with one state, so `_gate()`
  records which (nothing set up here, or `[jobs] kinds` narrowed to a kind
  this machine cannot run) where the capabilities are already in hand.
  "Nothing offered" is `taking_work: true`, deliberately: a fleet with no
  work must not read as a machine that is broken.
* `status()["current"]` names the job an editor's machine is busy with -
  id, kind, the RELATIVE path (the vault is a drive letter here and a mount
  there), when it started, and `forced_reason`. `STATE_FORCED` has existed
  since phase 1 exactly so somebody could be told why work started with them
  at the keyboard, and nothing read it: an admin's `--now` and the editor's
  own volunteer window are now two different sentences.
* `jobs_runner.stop_current()` is THE ADMIN'S CANCEL PATH, REUSED WHOLE: the
  id goes on the same `_cancel` list `commands.jobs.cancel` fills, so the
  thread that owns the child and the `.partial` is still the only thing that
  ends them, and the result goes back cancelled and NOT retryable. A second
  kill path would have been a second way to publish a half-written proxy.
* `status()["recent"]` is the last ten jobs this machine ran (id, kind, rel
  path, outcome, error, finished at), written at every `_post_result` BEFORE
  the call goes out - a result the dashboard never received is exactly the
  case where this machine is the only place that knows - and persisted to
  `~/.ccsync/state/jobs_recent.json`. proxy_history's posture: a ledger that
  cannot be written is never why a transcode fails. `cancelled` is its own
  outcome, not a failure: somebody chose it.
* `timeline_cards_role.report_block()` is a JUDGEMENT now, not a list length.
  `connected` was `bool(self._threads)` and nothing ever cleared that list,
  so a loop that raised, a loop that returned, a fleet credential that had
  been refused for hours and a dashboard that could not be reached all
  rendered on the fleet grid exactly like a healthy machine. `state` is one
  of `running` / `stopped` / `refused` / `credential_refused` /
  `unreachable` with a `detail` sentence, `last_poll_at` and
  `last_http_status` are the evidence, and the refusal vocabulary moved to
  `gate_state`. Green needs the loops alive AND a 200 within two long polls
  (50 s); a start buys 30 s of grace and a call that has FAILED spends it.
  A 401/403 says "the fleet credential is refused: sign in again from the
  tray", because that is the one thing that fixes it.
* The cards refusal is RE-ASKED every `PROBE_CACHE_SECONDS` (its own
  watchdog thread, only on machines with `cards_agent` on) instead of being
  decided once at start. Every refusal is a condition that clears: somebody
  signs in, somebody closes the standalone agent, a fleet halt expires at
  24 h by design. The old sentence told an editor to sign in from the tray
  when only a restart would have helped. A refusal that does not change is
  logged once, not once a minute.
* The advice names what to close: the process probe emits `pid<TAB>name<TAB>
  command line` on both platforms and the refusal reads "python.exe (pid
  4312): ... Close the standalone Timeline Cards agent window and this
  computer will pick the page up on its own within a minute." "Cannot tell"
  gets its own sentence rather than being rendered as `Found: this machine's
  processes could not be listed`, which sent people looking for a process
  nobody had seen. It still counts as a rival, and nothing here kills one.
* NOT done, deliberately: a halt does not stop a role that is already up
  (RES-6/7 proposed it) - the edits are synthetic keystroke sequences and one
  stopped half way through is a timeline nobody asked for; and a role whose
  loops have died is reported `stopped`, never restarted, because restarting
  an engine that owns Resolve is a decision, not a watchdog's.

### CR-171 - the companion did the work and told nobody: no download progress, no reason for a hand-back, no way to stop one, no retry for a failed upload - FIXED in repo 2026-09-04 (companion 0.9.68)

Wave 3's companion half (CYT-2, CYT-11, CYT-14, CYT-15, CMEDIA-4, CMEDIA-7,
CMEDIA-10, BROLL-5, APP-16). Everything here is additive on the loopback: a
page that has not been updated sees what it saw before.

* **`GET /ytdl/progress` had no consumer and the wrong shape** (CYT-2). The
  executor has kept `bytes_done`/`bytes_total`/`speed_bps`/`phase` per clip
  since 0.9.49 and served them as a flat dict its own docstring says exists
  "so the SPA can show something in the first seconds"; the SPA never fetched
  it, and a 40-minute 1080p clip showed the word `downloading` for its whole
  life. It answers `{"jobs": [{job_id, title, phase, percent, speed,
  eta_seconds, file, handed_back_reason, clip, done, failed, total,
  running}]}` now - a LIST, so "nothing to say" is not a different shape from
  "one job" - built by `ytdl_executor.snapshot()` / `progress_row()`.
  `percent`/`speed`/`eta_seconds` are the CLIP in flight (an average over
  clips that differ tenfold in length is a countdown that goes backwards);
  `done`/`total` are the job, for "clip 3 of 12". Unknown is `null`, never 0.
  `ytdl_executor.progress()` keeps the flat shape, because that is what the
  tray line reads.
* **Seven whole-job hand-backs were one `log.warning` each** (CYT-11): a
  naming-template or sidecar skew, a quality only the server can name, a
  destination this machine cannot resolve or create, an unmounted tree, not
  enough free space, the WP6 identical-failure breaker, and the everyday one -
  `_label_is_ours` false, i.e. the editor downloaded into a project this
  computer does not sync. All seven now call `DownloadJob.hand_back(why)` with
  a sentence in editor English that names what happens next, and it survives
  the job in `_LAST`, so the page that has had its 202 learns WHY the badge is
  about to flip instead of waiting minutes for the reclaim. Nothing about the
  "no release endpoint" design changed: the lease still expires and the server
  still downloads what is missing.
* **No way to stop a local download from the machine doing it** (CYT-14). The
  only escape hatches were the browser's [ DOWNLOAD ON THE SERVER INSTEAD ]
  (needs the page open and the tailnet up) and Quit CCSync, which stops
  syncing too. `ytdl_executor.cancel_job(job_id)` / `cancel_all()` and `POST
  /ytdl/cancel` `{job_id}` or `{all: true}` on the same origin/token guard as
  every other POST: the child is killed, `_cleanup_current` takes this clip's
  partials with it, the lease expires. Always 200 - `stopped: 0` means nothing
  was running, which is not an error, because a second click must mean what
  the first one meant.
* **The browser sign-in blocked for up to ten minutes behind one balloon**
  (CYT-15). `ytdl_browser_login.run(progress=...)` takes
  `(elapsed_s, remaining_s, phase)` and is called at launch (naming the
  browser AND that closing the window cancels), at least every
  `PROGRESS_SECONDS` (5 s) while waiting, and once more when the cookies are
  being saved. The timeout says what to do next: "the sign-in did not finish
  in time. Nothing was saved - try again from Settings > YOUTUBE". A callback
  that raises costs a debug line, never the sign-in.
* **`queued_for_base_rig` was invisible in every counter and then deleted**
  (CMEDIA-4). It is in the kind's finished set and was in neither counter, so
  the tray said "8 of 10" for ever, the progress window's `finished` never
  became true and the ETA divided by a remainder that could not reach zero.
  `status()` carries `queued_for_base_rig` and `queued_names`, the ETA
  subtracts them, `progress_model` counts them as finished AND names them
  ("2 track(s) need the base rig to finish. They are still on this
  computer."), and `progress()` carries the count. The file is the whole point
  of the state, so the drop is marked `held_for_base_rig` the moment the item
  is queued (not only when the batch ends, which a cancel or a lost lease
  never reaches) and `prune_staging` refuses to delete it - including at
  `max_age_days=0`, which is the tray's CLEAR FINISHED STAGING - and reports
  `held`/`held_names` so a button can say what it did not do.
* **"This machine is already downloading" was delivered as a hard failure**
  (CMEDIA-7). The two-download cap was designed around the page's own 1.5 s
  re-POST being the retry, but the page loops only while the state is
  `downloading`: every `ok: false` was a red toast and the end of the attempt.
  `broll_fetch.poll_fetch` answers `STATE_BUSY` with `retry_after`, and
  `/insert` and `/music/send` answer `{"ok": true, "state": "busy",
  "retry_after": 1.5, "message": ...}`. The sentence is worded to read
  correctly under a spinner and under a toast, because `/ytdl/fetch`
  (`ytdl_server.build_fetch_response`) still maps everything that is not
  downloading-or-done onto `failed`.
* **A failed clip's reason reached nobody** (CMEDIA-10): `progress()` carries
  `failed_items: [{name, error}]` (first 20), inside `batch` and mirrored at
  the top level, where the tray had a count and "See the log".
* **A failed upload was permanent** (BROLL-5): `POST
  /{broll,music}/ingest/retry` `{staging_id, items:[local_id]}` clears the
  item's error, deletes the half-written `.partial` and lets the page's pump
  pick it up; `{"ok": true, "retried": n}`, and retrying something that is not
  failed is a no-op. The companion was always safe to re-send to (`upload_slot`
  409s "already staged", `_stream_body_to` renames only on a complete body) -
  nothing had ever asked it to.
* **The update offer was a version number and nothing else** (APP-16).
  `parse_upgrade` carries an optional `notes` through (never rewriting one the
  signature covers - `canonical_record` reads `record_fields`, so an unsigned
  extra key is ignored by verification), `UpgradeManager.note_report_response`
  remembers it, and `offer_label` / `offer_toast` / `offer_dialog_text` render
  it: the first line in the menu item and the toast ("What's new: ..."), all
  of it in the dialog. Publisher text is control-character-stripped and capped
  before it reaches a Win32 menu item. A record without notes renders exactly
  as it did, to the character, so no deployed dashboard is broken by it.

Not done here, deliberately: the hand-back reason is NOT sent to the
dashboard. The job status the server receives is per CLIP, and a whole-job
hand-back posts nothing at all by design (there is no release endpoint, §3) -
adding a field would mean adding the call this design exists to avoid.

### CR-172 - the YouTube downloader measured more than its page ever showed - FIXED in repo 2026-09-04 (ytdl web, dashboard 0.7.33)
Wave 3's ytdl half (YTWEB-1/3/7/8/9/11/13, CYT-2). One shape said seven ways:
every fact below was already computed on the server and thrown away before it
reached the editor.

* **A queued job now says what it is waiting on** (YTWEB-1). The worker is
  fleet-serial - one job at a time for every editor on the site - and every
  number this app had was counted PER EDITOR, so the commonest queue there is
  (editor B behind editor A's 20-minute enrich phase) answered
  `queued_behind: 0`, toasted nothing (`announceQueued` returns on 0) and
  parked a bar in `PHASE_SPAN.queued` over an EMPTY ticker: every other bit in
  there is gated on a counter a queued job has none of. `db.fleet_ahead`
  counts the rows `claim_next_job` would take first, off the same candidate
  set and the same ORDER BY, and a job that is not startable yet is behind ALL
  of them rather than ahead of the ones that sort after it. It rides on the
  create answer AND on the poll (a toast is gone in seven seconds; a page
  reloaded onto a `queued` job has to say the same sentence), with
  `worker_alive` beside it because a queue nothing is draining looks exactly
  like a queue with something big at the front of it.
* **`js_runtime` is rendered** (YTWEB-3). Measured since YTDL-24 cost a week -
  without deno or node on PATH yt-dlp cannot run YouTube's player JS and EVERY
  clip fails "Requested format is not available", which reads as YouTube
  flakiness one video at a time - shipped on `api/health`, and read by no line
  of `app.js`. Now a fifth evidence pip (only when the answer is `missing`;
  a runtime that is there is not news) plus a banner, both `== null`-guarded
  like every other WP5 key. `worker.identical_failure_note`'s no-usable-format
  branch names it too, so a streak that IS this cause stops sending the editor
  to a yt-dlp update that would change nothing.
* **The degraded-filter note survives `hintFor`** (YTWEB-7). The worker writes
  `claude_auth: <note>` on a job whose phase is NOT failed, and the SPA matched
  the prefix and returned the generic hint INSTEAD of the string: the editor
  was told an admin must add a credential and never that the manifest below
  them is UNFILTERED, which is the one fact that changes what they do next
  (all 300 candidates arrive ticked as relevant). `hintFor` now returns the
  remainder in front of the hint, and `DEGRADED_NOTE` is reworded off its
  double hyphen.
* **What is MOVING beats what is parked** (YTWEB-8). `db.active_job` was
  "oldest non-terminal" from when an editor could only have one; the queue
  (2026-08-30) then deliberately let a second search start while an older one
  sat at `ready_for_review`. In-session it never showed - `runSearch` attaches
  by id - but on a reload, a second tab or the next morning the page attached
  to the week-old parked review, painted a full green bar, and the job that was
  actually downloading appeared nowhere. It now prefers BUSY, then the NEWEST
  parked job.
* **...and the parked ones are a list, not a memory** (YTWEB-13).
  `GET api/jobs/active` carries `waiting: [...]` (`db.parked_jobs`, the
  attached job never in it), rendered as WAITING FOR YOU above the queue with
  `[ RESUME ]` and `[ CANCEL ]` per row and a count in the header's own banner
  slot. Since a parked review blocks nothing, nothing ever nagged about one:
  five curated manifests could pile up discoverable only by reading `phase` in
  Recent searches. The one-job-per-editor 409 (CR-30's remnant, the RETRY path)
  now names the parked search and hands over the button instead of describing
  where to find one.
* **Free space is checked, and the number that was collected is shown**
  (YTWEB-9). Nothing anywhere tested it: the editor's only proxy before
  pressing DOWNLOAD was a DURATION, and 40 clips of 12 minutes at 1080p is
  15-40 GB. `start_download` now refuses below TWICE the estimate (or 2 GB
  when a manifest carries no durations, i.e. every paste) with a sentence
  naming the folder and both numbers, BEFORE `mark_pending` so a refusal
  leaves the job as it found it, and it FAILS OPEN on a disk it cannot read -
  the point is one sentence instead of N opaque per-clip errors, not a new way
  for a download to be impossible. `shutil.disk_usage` walks up to the nearest
  existing ancestor (the destination is created by the download phase) and is
  cached 60 s. The grid foot prints `roughly 22 GB` from a per-rung bitrate
  table duplicated in both halves on purpose, and the companion's `free_bytes`
  - sent on every claim since the feature shipped and written into a LOG LINE -
  lands on the job row (**migration 014**, `jobs.claim_free_bytes`, additive,
  NULL is a companion that does not say) and reads as "N GB free on the
  download machine". Still advisory at both ends: the machine that knows what
  a clip costs is the one that declines.
* **A finished clip opens from the DOWNLOADS list** (YTWEB-11). The reveal
  machinery worked from the history panel alone, so the last step of the flow
  this page exists for was a scroll past two panels into a fleet-wide ledger to
  find your own rows in it. The manifest carries `reveal_path` now
  (`db.video_reveal_path`: the JOB's destination plus the row's FILENAME -
  never `filepath`, which is absolute on whichever machine fetched it, with a
  separator this one must not assume), a `done` row is clickable through the
  same `reveal()`, and the header says how many clips landed where.
* **The browser watches its own machine download** (CYT-2). The executor has
  kept per-clip percent/speed/eta on the loopback since the feature shipped -
  its own docstring says "this exists so the SPA can show something in the
  first seconds" - and the SPA never fetched it: a 40-minute clip showed the
  word `downloading` for the whole job. `GET /ytdl/progress` is polled every
  2 s while THIS machine holds the job (one chain however many times a render
  asks, same 1 s abort budget, gated on the same server flag), printing
  `clip 3/12 · 38% at 4.2 MB/s · 2:10 left` and naming a `converting` clip so a
  ten-minute re-encode does not read as a stall. `[ STOP ]` posts
  `/ytdl/cancel` for that job and leaves the job itself alone - the server
  picks up what is missing, which is what happens when a laptop closes anyway.
  A companion answering 404 is a companion older than the route: the poll turns
  itself off for the session and the page is byte-for-byte today's.
* Deploy the dashboard before the companions as usual; the companion half of
  CYT-2 (`/ytdl/progress`, `/ytdl/cancel`) is C6's, and until an editor has that
  build the page degrades exactly as it does with no companion at all.

### CR-173 - the music page said "nothing matches" when the search was broken, hid every fleet-ingested track behind the tempo filter, and had no door to ingest at all - FIXED in repo 2026-09-04 (music web, dashboard 0.7.33)
Wave 3 of the usability + resilience sweep (MUSIC-2, MUSIC-3, MUSIC-4,
MUSIC-7, MUSIC-9, MUSIC-13, MUSIC-14, and the browser half of CMEDIA-7):

* **A failed query is no longer the empty state** (MUSIC-2). None of the three
  query functions had a `catch`, and all three render into a list already
  showing `render`'s empty copy, so a text encoder that would not load, a 401
  from an expired dashboard session, a 500 from a locked database and a
  genuinely empty answer were ONE screen - under advice ("try a looser
  description") that was wrong in three of the four cases. `api()` now attaches
  `err.status`, and `loadTracks`/`runSearch`/`showSimilar` each render
  `failureText()`: the status or the transport message, "Try again", and a
  separate sentence for a 401 ("your session expired. Reload the page to sign
  in again."). The looser-description wording stays for a real empty answer.
* **The left rail applies to a description search** (MUSIC-4). `SearchReq`
  carried `{query, k, pool}` and nothing else, so the mood chip, the axis
  slider and the BPM boxes were discarded the moment an editor typed - while
  the rail went on showing them lit, asserting a filter that was not in the
  query. `routes_api._filters()` is now the ONE builder for the browse route
  and the search route: same names, same defaults, same JOINs and WHERE. The
  hits are already an id set, so the rail is one more clause on the hydrate
  query - CLAP decides the order, the filters decide the membership. The id
  set binds LAST because the JOINs carry their own placeholders.
* **A NULL is unknown, not "no"** (MUSIC-14). A track the companion ingested
  has `bpm IS NULL` (MUSIC-ING-1: no librosa on an editor's machine) and
  `t.bpm >= 90` is never true of it, so a tempo or length filter dropped every
  fleet upload in silence. An unset filter still matches them; a set one
  answers `unknown_hidden` / `unknown_fields` and the result head says "N
  tracks have no bpm and are not shown" with `[ include them ]` beside it;
  `include_unknown` widens the clause (`OR col IS NULL`) rather than dropping
  it, so the range is still honoured for the tracks that HAVE a value. The
  count is computed against the rest of the filter (and, for a search, against
  that search's own hits), not against the library. `/api/facets` publishes
  `_unknown: {bpm, duration}` so the rail can offer the bucket before a filter
  is typed. **No schema change** - `music.db` is published by `publish_db.py`
  and this is a query change.
* **`[ ADD MUSIC ]` in the toolbar** (MUSIC-3). The whole ingest feature was
  reachable only by dragging a file onto the page: nothing said music could be
  added, and an editor whose batch ran yesterday could not read it, cancel it
  or find out why three tracks failed without dropping another file first. The
  button calls `miOpen()` behind a `typeof` guard (a stale index.html can ship
  app.js without ingest.js, and a TypeError there takes the search page with
  it). The staging area explains itself when empty.
* **The ingest queue has a UI** (MUSIC-7). `GET /api/ingest/queue` has always
  returned the counts, the pending rows and every parked failure's reason, and
  the browser never read it - and a failed queue row is NEVER retried, so the
  reason existed only in the log of whichever indexer run happened to hit it.
  The panel now shows "Waiting for the base rig: N tracks", each failure with
  its reason and "Nothing retries these on their own: fix the file and drop it
  again", refreshed every 15 s while the panel is open. Server text goes
  through `el()`/textContent, never innerHTML (MUSIC-15).
* **The library catches up after an ingest, and NEWEST is offered** (MUSIC-9).
  Nothing in ingest.js touched the results list, the facets or the header, so
  a batch reaching `done` left the page exactly as it was and the answer to
  "is my album in yet" was to reload. `miNoteBatchState` fires
  `refreshLibrary(true)` on the TRANSITION into a terminal state only - a page
  opened on last week's finished batches must not re-render the list under the
  editor - and the new sort control (filename / newest / bpm / length) is set
  to newest by that refresh. `sort=newest` was already supported by the route
  and had no caller.
* **An empty waveform says why** (MUSIC-13). The container has no indexer to
  build one, so every track without stored peaks drew a blank strip - and
  click-to-seek kept working over it, which read as "the waveform is broken".
  `loadPeaks` now returns `{data, note, detail}`: a 404 gets "No waveform yet:
  this track was added by the fleet and the base rig has not analysed it.
  Seeking still works." under the strip, with the route's own wording in
  `title=` for support. Only a real answer is still cached (MUSIC-4,
  2026-08-11).
* **"Already downloading" is a wait, not a refusal** (CMEDIA-7, browser half).
  The companion's per-machine download cap relies on the page re-POSTing, and
  the page looped only on `state === "downloading"`, so any `ok:false` ended
  the send with a red toast an editor had to remember to retry in an hour.
  The loop now keeps polling on `state` `busy` or `queued`, honouring
  `retry_after`, AND on the older build's `ok:false` + "already downloading"
  wording - an editor's tray app is upgraded on its own schedule, so both
  shapes are accepted.
* Tests: `music/web/tests/test_search_filters.py` (15) for the filter builder,
  the NULL rule and the placeholder ordering, and
  `music/web/tests/test_ui_says_what_it_knows.py` (23) pinning the frontend
  intent against its own source, the way `test_ingest_ui.py` and
  `test_plain_words.py` already do.

### CR-174 - the b-roll page never said what it had searched, what it could not search, or how to get a failed clip back - FIXED in repo 2026-09-04 (broll web, dashboard 0.7.33)
Wave 3's b-roll half (BROLL-5/8/9/10/18/22/23, and CMEDIA-7's browser side):

* **A failed upload was permanent** (BROLL-5). `xhr.onerror` set `item.error`
  for the life of the page and `ingestPumpUploads` skipped that item for ever,
  so a wifi blip at 95% of a 4 GB file cost one clip of a 200-clip drop and the
  only way back was to clear and re-drop everything - while the companion's own
  `upload_slot` 409 says in as many words that "the SPA retries a dropped file
  after a reconnect", a retry nobody had written. Now: three automatic attempts
  at 2/4/8 s for a NETWORK-level failure only (an HTTP refusal is the
  companion's considered answer and repeating it changes nothing), the row
  reading `upload interrupted, retrying (2 of 3)...`; then `[ retry ]` in the
  row and `[ retry all failed (n) ]` over the list, both of which clear the
  attempt count because a human pressing them knows something the three
  attempts could not - the wifi is back. The pump skips a backoff that has not
  elapsed (`item.retryAt`), never an item for ever. A black hole is caught by a
  STALL watchdog (no progress for two minutes) and deliberately not by
  `xhr.timeout`: that is a ceiling on the whole request, and a legitimate 4 GB
  body over a slow link takes an hour.
* **A batch whose machine went away could be picked up by NOTHING** (BROLL-8),
  under a notice claiming another of the editor's machines could take it. Six
  fleet routes, every one keyed by a uid the caller must already hold, and a
  companion that never polls. Now `GET /api/fleet/ingest/batches` lists the
  VERIFIED editor's unfinished batches with machine and heartbeat (a
  `?editor=` that does not match the identity is 403, not a way to enumerate
  another editor's machines), and the panel offers
  `[ take over on this computer ]` on any queued batch of the editor's own,
  which re-dispatches the uid to this machine's loopback exactly as Run does.
  Possession is still settled by the claim - another machine's live lease 409s
  and the button says so. **Deploy note:** the dashboard's login_gate carve-out
  (`app.py` `_broll_fleet_re`) covers `.../batches/<32 hex>/...` only, so a
  companion cannot reach the discovery route through the mounted dashboard
  until that regex is widened; the page's take-over path does not go through
  it, so nothing an editor sees waits on that.
* **`done_with_errors - 12 failed` was the end of the road** (BROLL-18): the
  only affordance was `clips`, i.e. twelve names to transcribe by hand and
  re-drop, which the first attempt's `videos` rows then read as duplicates.
  `POST /api/ingest-batches/{uid}/retry-failed` (owner or admin) moves the
  failed items back to `pending` and the batch back to `queued`; the video_id,
  archive_dir and archive_stem STAY, so claim re-uses the slot rather than
  allocating `_2`. `live`/`duplicate`/`cancelled` never move - somebody may
  already have cut with them. The page then tells its own companion
  (`POST /broll/ingest/retry {items}`, falling back to `/broll/ingest/run` on a
  404 from a build that predates it). Nothing is dispatched from the browser:
  it contributes the uid and nothing else.
* **A search that found nothing showed an empty page** (BROLL-9). `/api/search`
  carries `scope_total` when a query returned nothing - the size of what was
  searched, computed from the same clause builders in the same order, so it
  cannot describe a different scope - and the grid renders
  `Nothing matched "<q>" in <scope>. N clips were searched. Try fewer words, or
  switch to Semantic search`, plus only the levers that are actually on
  (clear the folder filter / stop hiding flagged clips / turn fuzzy back on).
* **Semantic mode could return nothing, for ever, and say nothing** (BROLL-10):
  fastembed is optional and the query model must match the stored vectors', and
  every one of those cases is a permanently empty grid with no signal to the
  editor or the admin. `/api/search` now carries `mode_available`
  (keyword/semantic/hybrid, each `{available, reason}`); the three buttons
  disable with the reason as their title, a page that arrives in a mode this
  server cannot run falls back to hybrid with one toast, and the empty state
  names it. Hybrid is never disabled - it is keyword plus a booster, and
  disabling the default mode would leave an editor with no mode at all - it
  says what it lost. The probe is `find_spec`, never an import: it is asked on
  every search response and building the encoder is a ~10 s ONNX load.
* **Batch state was the database's word** (BROLL-22): `queued - creator-2 -
  heartbeat 3 hours ago` reads as progress and means that computer stopped
  answering. One mapping, `ingest_batches.BATCH_STATE_TEXT` and
  `ING_BATCH_STATE_TEXT`, pinned as a pair by
  `tests/test_batch_state_words.py`; `batch_public` carries `state_text` for
  every other reader and the page re-renders it so its "3h ago" keeps ageing
  between polls. A pending cancel outranks the state it is cancelling.
  Counters in words: `180 of 200 indexed - 168 searchable - 12 failed - 20
  already in the archive` (`n_live` was index jargon).
* **Nothing said a search was in flight** (BROLL-23) while a semantic query
  costs a model load plus a scan over Tailscale: `aria-busy` and a `.searching`
  class on the grid (50% opacity) plus `Searching...` in the results head,
  cleared by the winning token only, on every outcome.
* **CMEDIA-7, the browser half:** "this machine is already downloading" was a
  red toast, and the cap's documented retry mechanism ("the web UI re-POSTs
  every 1.5 s anyway") did not exist - the loop polled only on `downloading`.
  Both shapes are now a WAIT: `{ok: true, state: "busy", retry_after}` from
  companion 0.9.67+ and the older `{ok: false}` whose message is the only tell.
  Capped at 15 minutes, because a wait with no end is the bug above it.

No migration: `failed -> pending` was already the one legal way back through
`_check_transition`, and nothing here adds a column, so `publish_db.py`'s
drain/re-apply is untouched (CR-152).

Files: `broll/web/app/{routes_api,routes_batches,routes_fleet,ingest_batches,search,semantic}.py`,
`broll/web/static/{app.js,ingest.js,style.css}`, four new test files.

### CR-175 - the fleet grid explained itself only to a mouse, and the refusal always landed off screen - FIXED in repo 2026-09-04 (dashboard 0.7.33)
Wave 3's page half (DUI-3, DUI-6, DUI-19, DUI-20, REL-11, REL-12, REL-16,
RES-6, DCORE-16, CYT-3):

* **A chip explains itself on a phone** (DUI-3). Every chip on the fleet grid
  carried its cause and its next action in `title=` alone, and eighteen of
  them can stack in one LANES cell; a touch device has no hover, so on the
  page whose whole reason for being opened on a phone is "is anything red",
  the entire explanatory layer was unreachable. The prose moved into ONE dict,
  `ui.CHIP_HELP` (format strings, filled by the `chip_help(key, **values)`
  Jinja global from the row's own numbers), so the tooltip and the sheet
  cannot drift; `partials/chip_sheet.html` lives in `base.html` and NOT in the
  grid, which replaces itself every 15 s and would swap the sheet shut under
  whoever was reading it. The tap handler and the tabindex pass are ~50 lines
  in `static/htmx_errors.js` - no library, no second `<script>` on every page.
  A missing key or a missing value answers with something rather than raising:
  this text is on the page that tells the fleet whether its footage is
  syncing.
* **The refusal renders beside the button that caused it** (DUI-6). These
  panels return their whole selves with `error` in a banner at the top and
  swap `outerHTML`, which preserves scroll - so [ DELETE ] on the fortieth
  package row was refused two thousand pixels above the viewport and nothing
  appeared to happen. The six partials mark that banner `error-banner`;
  `htmx_errors.js` remembers the path the write went to and, after the swap,
  moves the banner to the control that came back in its place. No match (a
  poll, or an error with no button behind it) leaves it where the template put
  it, which is right for those. In the wizard, `setup.js` had NO
  `showError(null)` call site at all, so one transient failure stayed on
  screen through every later success: it clears on every success now and
  writes into the failing step's own slot.
* **"Am I safe to close my laptop"** (DUI-19), one line above the queue and
  the transfers panel, from `ui.safe_to_close` and the view those panels
  already build. UPLOADS decide it: a download interrupted by a closed lid
  resumes, an upload that has not happened yet leaves that footage on one
  disk. An admin's fleet-wide view has no "this computer", so it says nothing
  rather than guessing.
* **A wired computer says where its setting lives** (DUI-20). The assignments
  column head printed `wired`, greyed every box, and never said that per CR-88
  the setting is that COMPUTER's own: "Change it on that computer: tray,
  Settings, THIS COMPUTER." is in all three assignment strings, in the
  sidebar's base-rig tooltip, and as visible muted text in the column head,
  because on a phone there is no hover (DUI-3 again). CR-95's rule is
  untouched: only a wired cell that is NOT ticked is disabled.
* **When the feed will check again** (REL-11), not only when it last did. The
  default interval is a DAY and nothing said so, so an admin who had just been
  told a fix was out could not tell whether waiting five minutes would help.
  `feed_interval_seconds` / `feed_next_check_seconds` come from
  `ui._packages_and_feed`, off the same settings value the poller sleeps on;
  with `last_error` set the line reads "next retry in about".
* **The four long controls on Packages show that they are working** (REL-12):
  `hx-indicator="this"` + `hx-disabled-elt="this"` on CHECK NOW, both PUBLISH
  forms and PUSH TO ONE COMPUTER, which now swaps its label like the two
  beside it. `[ PUBLISH ]` is a multi-megabyte download and looked identical
  to a dead button for its whole duration; the natural second click started a
  second download of the same artefact.
* **A recalled build of any kind can be rolled back** (REL-16). The recovery
  control was `{% if p.kind == "companion" and p.machines_running %}`, so a
  recall of anything else that machines are still running had no button at
  all; the version list beside it is that kind's now, not always the
  companion's.
* **The cards chip reads the state, not the connection** (RES-6). Two daemon
  threads and no watchdog meant `connected` stayed true through a dead loop
  and through hours of 401s, and the grid kept painting `[ CARDS: E1 v5 ]` in
  green. The chip takes its colour from the companion's `state` (running green
  / refused + unreachable amber / stopped + credential_refused red), names the
  state in its label, and puts `detail` (or the older `gate_state`, plus the
  HTTP status on a credential refusal) in the DUI-3 sheet. A companion too old
  to send `state` still reports `connected` and renders exactly as before.
* **A HELD sharing change is rendered** (DCORE-16). `record_enforce_plan`
  wrote the note and `alerts.enforce_plan` fired on it; the collector panel
  and the project page said nothing, so "applied 9 of 40; syncthing refused
  the rest" reached nobody. Both render `Sharing change held: <note> (<when>)`
  from `enforce_notes`, defaulted so a dashboard whose collector has not
  written one yet renders nothing.
* **YouTube clips that never reach Resolve** (CYT-3). The importer computed a
  full status - `no-project-match`, `resolve-closed`, `drive-absent`, `paused`
  - and it reached nobody at either end: the download worked, the clips are in
  `Youtube/<term>/`, and they are not in the media pool. The grid carries
  `[ YOUTUBE CLIPS WAITING FOR RESOLVE: N ]` and, when the machine has given
  up, `[ YOUTUBE IMPORT GAVE UP ]` with the reason. `no-project-match` is a
  per-machine misconfiguration an admin can fix and the editor cannot, which
  is why it belongs on this page. A companion that does not send the section
  renders nothing at all.

Tests: `dashboard/tests/test_templates_wave3_2026_09_04.py` (15).


### CR-176 - the dashboard did things and would not say what, to whom, or when - FIXED in repo 2026-09-04 (dashboard 0.7.33)
Wave 3's dashboard-core half (DCORE-8/9/13/14/16, REL-16, APP-16, CYT-3, plus
RES-4, RES-6 and BROLL-8 handed over by the companion and b-roll builders).
Schema **v49**: `companion_packages.notes`, `report_auth.token_id` and four
`machine_state.cap_cards_*` columns.

* **DCORE-8** `/api/v1/login` and `/verify` computed the wait
  (`auth.login_throttled` returns SECONDS, doubling 60 s -> 3600 s) and threw
  it away, answering "too many failed attempts; wait and retry" with no
  `Retry-After`. An editor at a tray could not tell a one-minute lockout from
  a sixty-minute one, so they retried, which on the shared IP budget extends
  it for everyone behind that address. Both routes now answer **"Too many
  sign-in attempts. Try again in 6 minutes."** with `Retry-After`
  (`auth.throttle_message` / `throttle_wait_phrase` / `throttle_headers`,
  rounded UP to the whole minute, "about an hour" past 45 min), and the login
  page says it too. **Not a username oracle** and the test now pins that
  rather than the old silence: `record_login_failure` is unconditional, so an
  invented username is throttled, and told the same wait, as a real one.
* **DCORE-9** the JSON 401 for the dashboard's OWN `/api/` is now
  `{"detail": "Your sign-in has expired. Sign in again.", "login": "/login"}`,
  and `static/assignments.js` navigates to `/login?next=<this page>` instead
  of toasting `could not tick <project>: login required` - copy that reads as
  a permissions bug. htmx's `HX-Redirect` only ever covered the polls, which
  stop while the tab is in the background, so the admin coming back to a
  twelve-hour-old tab was exactly the person it did not cover. A signed-out
  column run stops on the first 401 instead of grinding through 39 more. The
  mounted apps (`/broll`, `/music`, `/ytdl`, `/cards`) keep "login required":
  their consumers are companions and another repo's SPAs.
* **DCORE-13** `[ UPDATE NOW ]`, `[ RESUME ]` and `[ ASK THIS MACHINE WHY ]`
  all answered `{"ok": true}`, so pushing an update to a laptop that had been
  shut in a bag for nine days produced the same confirmation as pushing it to
  a live machine, and then an admin watched a queued row that was never going
  to move. All three now answer `queued_for`, `applies` ("on that computer's
  next report, usually within 30 s. It was last heard from 12 s ago" / "It was
  last heard from 9 days ago, so this may sit for a while"), `last_report_at`,
  `last_report_age_seconds`, `stale` and `pending_before` - read BEFORE the
  write, so a second click says it is re-arming rather than being congratulated
  twice. It WARNS, it refuses nothing: a machine that comes back on Tuesday
  applies it on Tuesday, and that is a good reason to press the button.
* **DCORE-14** `[ REVOKE ]` answered `{"ok": true}` and the panel could not
  say which computers a token was holding: `last_used_at` said WHEN, never BY
  WHICH, and one editor can own two machines and one token. `report_auth`
  gained `token_id` (v49, written by the report ingest through
  `db.report_token_id`, empty for the shared token which identifies nobody),
  `build_report_tokens_view` puts `machines`/`machine_names` on every row, and
  the revoke answers **"Revoked. jsmith/EDIT-PC and jsmith/EDIT-LAPTOP were
  using this token and will stop reporting within a minute. Give that editor a
  new token."** Nothing is refused.
* **DCORE-16** the enforce cycle's `put_folder` loop let an exception out on
  folder 10 of 40: `_timed` recorded the cycle as failed, the 30 after it were
  never attempted, and the plan persisted before the loop still described all
  40 - so the `enforce_plan` alert said "held" for shares that had been
  applied and said nothing about the ones that had not. Each folder now
  carries its own failure (`Collector._enforce_loop`), the pass finishes the
  rest, and the cycle's note is "applied 2 of 3 folder(s); syncthing refused
  the rest (bad: folder is paused)". `db.enforce_notes` puts the recent
  config/enforce notes into the project page and the fleet diagnostics
  contexts as `enforce_notes`, where the question "why is this computer not
  getting this project" is actually asked.
* **REL-16** `[ ROLL THE FLEET BACK ]` was reachable only from a vendor
  recall; the commoner case is nobody recalling anything (ship a build, an
  editor reports it broken an hour later) and the recovery was
  `[ MAKE CURRENT ]` plus `[ UPDATE NOW ]` on every machine by hand.
  `machines_running` is now on EVERY package row with a `machines_running_known`
  flag beside it - **present and empty** for onboard/installer, because
  nothing in a report says which installer a computer was set up with - and
  the route takes `?kind=`, refuses a same-version no-op, and answers a
  non-companion kind with why there is nobody to ask rather than an empty
  success.
* **APP-16** a package record carries `notes`, one line of what changed, shown
  in the editor's update dialog: accepted on the PUT and by
  `release_feed.publish_from_feed` (the feed record has carried `notes` since
  its first version and nothing read it), stored (v49, folded to one line and
  capped at 300 chars), returned in the packages view and added to the upgrade
  offer. **UNSIGNED, and that is a condition, not a shortcut**: the signature
  covers a field list every companion in the field mirrors, and a record
  carrying a field an older canonicaliser does not know is REFUSED by that
  build with no over-the-air recovery (REL-7). A sentence an editor reads must
  never be able to strand a machine. `--notes` on `sign_release.py` (also
  `$CCSYNC_RELEASE_NOTES`, which is how it reaches the PUT
  `build_editor_package.ps1` makes) and `publish_latest.py`; `-Notes` on
  `ship.ps1`; one paragraph in `docs/RELEASE.md`.
* **CYT-3 (dashboard half)** `sync_guard.youtube_import {state, reason,
  pending, at}` is declared, stored per machine in `meta` (the CR-164 shape,
  same latch rule: an absent section DELETES, because a stale "8 clips
  waiting" from March is worse than silence) and exposed as
  `machine.youtube_import` on the fleet grid. `no-project-match` is the state
  an admin can fix and the editor cannot, which is why it belongs there.
* **RES-4** `ResolveUndoResultIn.state` accepts `parked` (additive; every
  existing value unchanged) plus a `parked: bool` for the companion build that
  straddles the change, and both spellings store as `parked` -
  non-retiring like `retrying`, but read as "parked: no project open in
  Resolve, will resume when one is" (`state_sentence`) instead of as a machine
  that keeps failing.
* **RES-6** `CardsAgentIn` takes `gate_state`, `detail`, `last_poll_at`,
  `last_http_status` and any `state` string (`refused` /
  `credential_refused` / `unreachable` joined the old two; an unknown value
  must never 422 a whole report). Stored in four v49 columns beside
  `cap_cards_state` and exposed under the same `capabilities.cards_agent`
  object. NULL is "this build cannot say", never OK.
* **BROLL-8** `login_gate` carved out only
  `/broll/api/fleet/ingest/batches/<32 hex>/...`, so the new discovery route a
  companion learns batch uids from was 303'd into a login page. The collection
  path is carved out exactly (`/?$`), **GET only**, credential still required;
  `/broll/api/fleet/` at large stays closed.

Deploy the dashboard before the companions, as always: the report fields above
(youtube_import, parked, the cards detail) are ones a newer companion sends
and an older dashboard would 422 or drop.


## Usability + resilience sweep, wave 4: one vocabulary, one help page, one health page (CR-177..CR-181, 2026-09-04)

`docs/USABILITY_RESILIENCE_SWEEP_2026-09-03.md` section 4 (the vocabulary
table) and section 5 wave 4. Five Opus builders: companion tray/app copy,
companion settings window, dashboard templates + `/help` + `/admin/health`,
the three web UIs, dashboard API/scheduler copy. The words are now
**tick / sync plan, computer, paused / stopped by your admin / stopped
itself, wired / remote, upload / proxy download / folder sync,
[ UPLOAD ONLY ], SYNC STATUS**, and each surface carries a scan test with a
retired-words list and a reasoned allow-list, so the old words cannot creep
back. Built with NO gate between waves at the owner's instruction; the one
gate runs after wave 5.

Dashboard **0.7.34**, companion **0.9.69**. Owed into wave 5: the deploy
does not ship `docs/HOW_IT_WORKS.md` into the container, so `/help` answers
"not installed" on the NAS until `install_dashboard_app.py` copies it or
`DASH_HELP_DOC` is set; `broll_server.py`'s ~15 "this machine" ingest
refusals and `rclone_lane._breaker_stand_down`'s technical detail are the
companion's last old-vocabulary strings; `capabilities.jobs_gate` is not
persisted (v50 would let `why` say "busy making proxies" from the database);
HOW_IT_WORKS.md's prose outside the glossary still says machine/lane (SYS-5).

### CR-177 - four words for a computer, two for a stop, and a breaker that told an editor to edit config.toml - FIXED in repo 2026-09-04 (companion 0.9.69)
Wave 4 of the usability + resilience sweep, companion half (sweep section 4
"One vocabulary", UX-19, SYNC-106, CMEDIA-1, CMEDIA-9, SYS-21 (a)). The
owner approved one word per concept on 2026-09-04: a **computer** in copy
(`machine` stays in code, routes and DB columns; `device` is a Syncthing
identity and nothing else); sync that is not running is **paused** (you did
it), **stopped by your admin** (a fleet halt) or **stopped itself** (the
breaker, the disk floor); the transports are **upload** / **proxy download**
/ **folder sync**, never a lane and never a letter; a project is **ticked**
and the set of them is a **sync plan**.

* **The vocabulary is applied and then SCANNED.** Every visible string in
  `tray.py`, `tray_native.py`, `app.py`, `ui_copy.py`, `jobs_runner.py`,
  `capabilities.py`, `drive_reminder.py`, `eula.py`, `settings_window.py` and
  `sync/lane_guard.py` (about 45 sentences) reads the approved word, and
  `tests/test_sweep_2026_09_04_copy.py` fails on "lane / lane A / lane B /
  lane C / machine / base rig / rig / halted / parked / breaker / selection /
  assignment" as whole words in any of them. The scan skips DICT KEYS and
  lookups (`guard.get("parked")`, `{"reason": ...}`) and one- or two-word
  literals, because the state files and the wire deliberately did NOT change,
  and carries ONE allow-listed string with its reason. The two route labels
  `ui_copy` pins were renamed with the rows they quote ("STOP ALL SYNCING ON
  THIS COMPUTER", "REMOVE '<x>' FROM THIS COMPUTER"), so route and button
  still read the same words.
* **A stop and a pause are two switches and the tray named one** (UX-19).
  With both set the menu carried "Start syncing again" and "Resume syncing
  (currently PAUSED)" four lines apart and clicking either left the computer
  not syncing. The local stop's row is now named for its CAUSE and dated -
  "Clear the sync stop on this computer (set today at 09:12)", the stamp
  dropped rather than guessed when it cannot be read - the pause reads
  "Resume syncing (paused by you)", the state block grows "Two things are
  stopping sync on this computer: a stop and a pause. Clear both to sync
  again.", and the Sync: line carries the SECOND reason ("Sync: stopped on
  this computer (and paused)"). The ranking is the dashboard's own
  (`health.WHY_ORDER`: fleet halt, then local halt, then paused).
* **The breaker told an editor to edit a file they cannot open** (SYNC-106).
  The trip reason was one string doing two jobs, and one of the three ended
  "Check remote_root in config.toml." The trip now carries a CAUSE
  (`root_unrecognised` / `remote_empty` / `remote_shrank` / `pass_deletes` /
  `cumulative_deletes`); `reason` is unchanged and stays the admin's - the
  log, the report and copy_diagnostics carry it - and `editor_reason` is what
  the tray line, the balloon, the resume dialog and `sync_guard.blocked`
  render: "The server does not look like your project tree right now, so
  CCSync stopped downloading proxies before anything could be removed.
  Nothing was deleted and your uploads are still running. Ask your admin to
  check the server." That tail is on ALL FIVE reasons, not just the two that
  happened to have it. A latch tripped by an older build has a reason and no
  cause and is mapped back by the half of the sentence its trigger owns.
* **Three GPU consumers on one computer, and only two of them negotiated**
  (CMEDIA-1). `JobRunner` gets the `blocked_fn` seam the ingestors and the
  proxy generator have, wired to `app._jobs_block_reason()` (either
  ingestor's `blocking_reason()`, then "waiting: making proxies"), a new gate
  state `STATE_LOCAL_WORK` reported by `status()`, and `jobs_gate.detail`
  beside the machine-readable `reason` so `GET /api/v1/jobs/<id>/why` can say
  "busy indexing b-roll" instead of ranking a saturated machine first on
  longest-idle. It sits ABOVE the two gates a person can open: a volunteer
  click is not consent to run two GPU jobs at once. The seam fails CLOSED,
  like the halt and Resolve probes beside it, and is NOT the config gate
  `_proxy_block_reason` answers True for.
* **The 20 GB staging floor was b-roll's number applied to music**
  (CMEDIA-9). `IngestKind.free_space_floor_gb` (b-roll 20, music 2) is what
  `broll_server._ingest_floor_bytes` falls back to; the per-kind config key
  still wins. A music drop on a laptop with 15 GB free was refused and the
  drop zone never rendered, for a batch whose largest file stages 512 MiB.
* **One help page, one constant** (SYS-21 a). `ui_copy.HELP_URL_PATH`
  ("/help", the dashboard's new route), `ui_copy.HELP_PAGE`
  ("Tray > Settings > HELP", checked against a row that exists like every
  other route) and `ui_copy.help_url(cfg)` - `<dashboard_url>/help`, or None
  on a computer with no dashboard yet, never a relative path or a guess.

Deploy order is unchanged (dashboard first): the dashboard's `why` reads
`jobs_gate.detail` and its absence is what every companion below 0.9.69
sends. Nothing here changes a state file's keys or the report's `reason`.

### CR-178 - the Settings window spoke five vocabularies, hid its own help below everything, and could change one setting - FIXED in repo 2026-09-04 (companion 0.9.69)
Wave 4 of the usability + resilience sweep, the companion window half (APP-17,
SYS-8, SYS-21 (a), UX-3, UX-11, SYNC-117, RES-15, plus sweep section 4's
vocabulary table). `settings_window.py` and `popup.py` only; the tray's own
lines are the same wave's other half.

* **One vocabulary** (sweep section 4). `[ SYNC LANES ]` is `[ SYNCING ]`;
  the three transports are `upload` / `proxy download` / `folder sync`
  everywhere an editor reads them, taken from `ui_copy.lane_words` so the
  window and the dashboard's API say the same words about the same lane; a
  project's mode is `upload only (no proxy download)`, not "uploads only (no
  proxies come down)"; `Machine name:` is `Computer name:`; the two role
  dialogs say "this computer" and no longer say "the base rig" or "that
  lane". A scan test in `test_settings_window.py` walks every Line and
  Button label and fails on `lane`, `machine`, `base rig`, `halted`,
  `parked` or `breaker`. Two labels are exempt and still say MACHINE -
  `STOP ALL SYNCING ON THIS MACHINE` and `REMOVE '<x>' FROM THIS MACHINE` -
  because `ui_copy.ROUTE_ROWS` pins them as the row other modules' copy
  points at; renaming them is one edit in `ui_copy.py` and one here, and
  belongs to whoever owns that file next.
* **HELP goes FIRST when anything is a warning** (APP-17). Eight of the
  advisory lines instruct the reader to press [ COPY DIAGNOSTICS FOR YOUR
  ADMIN ], and on a computer with something wrong the SYNCING section alone
  is taller than the 640 px window, so that button was below two sections
  the reader had to scroll past to find. On a healthy computer nothing
  moves. Above the scroll area there is now a **jump strip**: one button per
  section header, `canvas.yview_moveto` to that header's y measured at CLICK
  time (the window rebuilds itself every two seconds, so a y captured at
  render points at whatever has since grown above it). The strip is packed
  outside the canvas so it does not scroll away from the reader who needs
  it, and it is the one control here that does NOT close the window: it
  opens nothing and changes nothing.
* **FLEET JOBS is a section, not a TOML file** (SYS-8, UX-11). `[x] Let the
  fleet use this computer` (`jobs_enabled`), one checkbox per kind from
  `capabilities.KNOWN_KINDS` in editor English ("Transcribe audio (uses the
  graphics card)", "Draw audio waveforms"), and `LEND THIS COMPUTER FOR 30
  MINUTES AT A TIME (click for 60)` cycling 15/30/60/120
  (`jobs_volunteer_minutes`). `conform` and `resolve-edit` are never
  offered, because they may never move between computers (plan §4.2).
  Every write goes through `config_mod.set_value` - the one-key line patch
  the role switch uses, with APP-11's read-back proof - and every one of the
  three is read at construction (`JobsRunner.__init__`, `capabilities`), so
  the section says "The settings above were changed and take effect when
  CCSync next starts" exactly the way the role does. Ticking all the kinds
  writes `""`, not the full list: a build that learns a new kind later must
  not find this computer excluded from it by a list nobody knew they were
  writing. Unticking the LAST kind is refused with "Untick 'Let the fleet
  use this computer' instead", because `jobs_kinds = ""` means every kind
  and "none" cannot be written at all. `cards_agent` is deliberately absent:
  exactly one computer in a fleet may run it and the server is the only
  party that can see all of them. The status half (CMEDIA-2) and the
  settings half share the one header.
* **The drive reminder can be turned off, for this episode only**
  (SYNC-117). While an episode is open, SYNCING carries [ REMIND ME LATER ]
  (two hours, then the usual cadence) and [ STOP REMINDING ME ABOUT THIS
  DRIVE ]. `drive_reminder.mute_episode(minutes)` stops the thread and
  nothing else: the record, the summary and `active` are untouched, so the
  standing warning line stays where it was, and the drive coming back clears
  everything as before. The mute is NOT written to the record and NOT a
  config key - a restart with the drive still out reminds again, because
  this is a data-safety warning and `drive_reminder_minutes` is still the
  way to turn the cadence down for good. `reminders_muted` compares the
  episode's own start time rather than reading a flag, so a new episode
  never inherits the last one's click.
* **A FIX ALL rehearsal reads as a rehearsal** (RES-15). `fixer.fix_clip`'s
  dry run returns `ok: True, dry_run: True` with `would_copy` /
  `would_relink` counts; it used to return `ok: False`, which every caller
  counts as a failure, so a clean 69-clip rehearsal was summarised as "0 of
  69 copied in, 69 failed" with 12 red rows. `summarize_fix_results` learns
  `dry_run`: "REHEARSAL: nothing was copied. 69 files would be copied into
  P:\." with neutral rows naming where each clip WOULD land, no undo pointer
  and no byte count (`fix_copied_bytes` and `fix_summary_text` exclude
  rehearsal rows). The mode is now visible before the click: a red line in
  the popup header ("FIX ALL is in rehearsal mode on this computer and will
  copy nothing.") and the same sentence in Settings > ADVANCED with
  [ TURN REHEARSAL OFF ], which writes `fixer_dry_run = false` AND drops
  `fixer.dry_run_default`'s per-process cache - without that the button
  would appear to do nothing until the next start, which is APP-11's shape.
* **HELP contains help** (UX-3, SYS-21 (a)). [ HOW CC SYNC WORKS ] and
  [ WHAT DO THESE MEAN? ] (the same page's `#glossary`) open the dashboard's
  help page in the default browser through `ui_copy.help_url(cfg)`, with a
  `dashboard_url` + `HELP_URL_PATH` fallback so a build whose `ui_copy` half
  is older still gets the buttons. Hidden entirely when this computer has no
  dashboard URL: a button that can only fail is worse than a section with
  two rows in it. `webbrowser.open()` returns False with nothing logged when
  no browser could be launched, so the failure is logged and named.

Config keys this window can now write: `mode` (unchanged), `jobs_enabled`,
`jobs_kinds`, `jobs_volunteer_minutes`, `fixer_dry_run`. All five through
`config_mod.set_value`, all five needing a restart to apply, all five saying
so on the line.

### CR-179 - four words for one thing, no help page, and four pages that each answered "is my fleet all right" - FIXED in repo 2026-09-04 (dashboard 0.7.34)
Wave 4's dashboard half (SYS-6, SYS-21a, UX-3, UX-22, DUI-11, DUI-12, and the
terminology table in `docs/USABILITY_RESILIENCE_SWEEP_2026-09-03.md` section
4):

* **One vocabulary, and a scan that keeps it.** The product said tick,
  selection, plan and assignment for one act; machine, computer, device and
  rig for one box; halted, parked, stopped and breaker for one state; and
  lane A/B/C for the three things a person actually watches. Every visible
  string in `templates/`, `static/` and `ui.py` now uses **tick** /
  **sync plan** (the page is `[ SYNC PLANS ]`), **computer** (`device` only
  for a Syncthing identity), **paused** (you did it) / **stopped by your
  admin** (a fleet halt) / **stopped itself** (the proxy-download brake, the
  disk floor), **wired** / **remote**, and **upload** / **proxy download** /
  **folder sync**. THE CODE KEEPS ITS NAMES: `selections` is still the table,
  `machine` is still the column, the route segment and the form field, and
  `api.LANE_LABELS` still answers A/B/C for the JSON API and every log line.
  The seam is one dict, `ui.LANE_WORDS` (`lane_word` as a Jinja filter), so a
  chip names itself from the lane the report carried. The scan that keeps it
  is `tests/test_sweep_2026_09_04_copy.py`, extended with a template/JS half
  that reads only what a browser paints: text outside any tag with `{{ }}`
  and `{% %}` removed, the values of `title` / `placeholder` / `aria-label` /
  `alt` / `hx-confirm`, and our own JS string literals. A string with no space
  in it is a key or a route and is skipped, `htmx.min.js` is vendored and
  skipped, and everything else that is left is in an allow-list WITH ITS
  REASON (four Syncthing-identity lines, the viewport meta, and the file-move
  button label the flow's own copy owns).
* **`/help` serves the guide** (UX-3 / SYS-21a). `docs/HOW_IT_WORKS.md` is 788
  lines of customer prose that was reachable only by someone with the
  repository: zero links to any document existed anywhere in the product.
  `help.py` finds it (`DASH_HELP_DOC`, then `<app>/docs/`, then the repo
  checkout beside the package - `install_dashboard_app.py` ships the
  `dashboard/` tree as `app` and nothing else, so **a deployed server needs
  the doc shipped or the env var set**; with neither, the page says "Help is
  not installed on this server" and never 500s) and renders it with a
  stdlib-only markdown subset, because `markdown` is not in
  `requirements.lock` and this is not worth a dependency for. Everything is
  escaped before anything is marked up; no HTML in the document passes
  through. Headings get numbering-free ids and every glossary row gets
  `id="term-<slug>"`, because four surfaces deep-link into it: the sync line
  and the SYNC column on SYNC STATUS, the UPLOAD ONLY chips (sidebar, queue,
  project page), the SYNC PLANS intro, and the topbar's `[ ? ]`. The guide's
  section 15 is the terminology table now, in customer prose.
* **One `[ HEALTH ]` page** (SYS-6). Open notices, the RED/AMBER alert
  findings, broken invariants and missing protection lines in ONE ranked list
  at `/admin/health`, read through the existing `db` / `alerts` /
  `invariants` / `protection` public functions - no new data, no new query.
  Every row carries its source's own `diagnosis` and `fix` VERBATIM plus the
  wave-2 `[ TAKE ME THERE ]` href, and links to the page that owns it: a
  composed page that paraphrases is a second place for the wording to be
  wrong. Bands are error, then warn, then **unknown** - `[ NOT CHECKED ]` is
  its own band and never folds into OK, which is the rule
  `docs/SELF_DIAGNOSIS.md` exists to hold. One source that raises costs its
  own rows and not the page. It is the SETTINGS LANDING (the drawer's
  [ SETTINGS ] and the topbar gear) and the topbar's alert chip points here
  rather than at one of the four sources.
* **The Settings strip is three labelled runs**, not fourteen flat entries:
  *Run the fleet* (SITE, USERS, SYNC PLANS, TRANSFERS, PACKAGES, JOBS,
  HISTORY, SETUP), *Is it healthy* (HEALTH, INVARIANTS, PROTECTION, ALERTS),
  *When it breaks* (RECOVERY, HELP). `ui.SETTINGS_NAV_GROUPS` is the list and
  `SETTINGS_NAV` is DERIVED from it, so a page cannot be in a run and not in
  the strip. A run whose every entry is admin-only renders nothing at all for
  an editor, heading included.
* **The audit log is `[ HISTORY ]`** (DUI-12): three things in one navigation
  were called a timeline (a Resolve timeline, the mounted Timeline Cards, and
  the audit log), so an owner told "check the timeline" had three places to
  look. Heading, tab title and `plan_changes.html`'s "the full history" link;
  the route is unchanged.
* **SITE SETTINGS explains itself** (DUI-11): sixteen jargon fields carried
  exactly one hint, in a mechanism built for hints, and a first-time customer
  meets that page immediately after the wizard. One sentence and an example
  for every field, READ rather than hovered (a phone has no hover), in three
  headed groups - `[ YOUR STUDIO ]`, `[ THE TREE ]` and
  `[ HOW EDITORS CONNECT - ADVANCED ]`, the last collapsed. `dashboard_url`
  carries its own amber line: *This must be exactly the address editors type
  in their browser, or Send to Resolve stops working* - the 8899 loopback's
  origin allow-list refuses every Send-to-Resolve call when it does not match.
* **The login page says what this is** (UX-22): the brand from the site
  manifest (never a literal) and one muted line, "Your admin creates this
  account for you. If you do not have one yet, ask them before installing."
  It still does NOT say "no account with that name here" on the error branch,
  and deliberately: on every deployment that authenticates against the NAS the
  question needs a second credential round-trip from an unauthenticated route,
  which is a free enumeration oracle, and item 15 (2026-08-17) settled on ONE
  message for every refusal for that reason. The comment at `_LOGIN_REFUSED`
  records it. The wave-3 throttle sentence is untouched.

Owed: the deploy does not ship `docs/HOW_IT_WORKS.md` into the container yet
(`install_dashboard_app.py` uploads `dashboard/` only), so `/help` on the NAS
answers "not installed" until either that script copies it or `DASH_HELP_DOC`
names a path in the compose file. The rest of the guide's prose still says
"machine" and "lane" outside the glossary, section 4, section 8 and the
troubleshooting table; that pass is wave 5's, with the doc's content
corrections.

### CR-180 - the three SPAs called one computer five things and the tray app four - FIXED in repo 2026-09-04 (broll, music and ytdl web)

Section 4 of the 2026-09-03 usability sweep ("One vocabulary", UX-4/UX-5)
found the same concept wearing a different name on every surface. Wave 4
builder C applied the owner's fixed vocabulary to every string an editor
READS in the three mounted web UIs - toasts, tooltips, empty states, button
labels, headings and the `detail` an HTTP refusal carries - and pinned it.
Code identifiers, DOM ids, CSS classes, routes, the `machine` query
parameter, the `machines` table and every log line keep their names on
purpose: renaming those would be a data change wearing a copy change.

* **the box on the desk is a computer.** "machine" left 46 visible strings
  across the three pages: b-roll's "Clip isn't on this machine yet", the
  ingest tier refusal ("this machine's GPU can't hold it"), music's "syncing
  the track to this machine", the batch cards' "no machine yet" and "All
  machines" tab, and ytdl's whole local-download vocabulary ("downloading on
  your machine", "this machine declined the job", "free on the download
  machine", the [ STOP ] and [ DOWNLOAD ON THE SERVER INSTEAD ] tooltips).
* **the program is the CC Sync tray.** The three pages between them called it
  "the companion", "the companion app", "the CC Sync companion", "the ccsync
  companion" and "the tray app", sometimes two of those in one sentence. All
  of them are "the CC Sync tray" now, and a test refuses the other four
  spellings. The two update instructions that still pointed at "tray icon ->
  check for updates" say "take the update your tray offers", which is the
  label `upgrade.offer_label` actually draws.
* **"the base rig" left the UI.** Music's queue panel was headed "Waiting for
  the base rig" and five sentences named it; an editor has no way to know
  which computer that is or whether they own it. It is "the indexing
  computer" throughout, including the `[ include them ]` tooltip and the
  no-waveform caption.
* **music's error sentinel moved with the copy.** `app.js` tells "the tray
  answered with an HTTP error" from "the request never reached 127.0.0.1" by
  the PREFIX of the thrown Error, which was the word `companion`. Renaming
  only the sentence would have silently picked the wrong branch for every
  failure - the same inversion as 2026-08-12 - so the sentinel is `tray HTTP
  <status>` and a test holds the two together.
* **the home page is SYNC STATUS.** All three `[ DASHBOARD ]` back links said
  "back to the CC Sync dashboard (project sync status)".
* **`selections` stays in the DB, "sync plans" is the words.** The ytdl
  project picker's one visible refusal said "no dashboard database to read
  project selections from".
* **the scan.** `test_one_vocabulary.py` in each of the three suites reads
  only where the product speaks: JS string literals with comments removed,
  HTML text nodes plus `title`/`placeholder`/`aria-label`/`alt`, and the
  `detail`/`message`/`error` values in the route modules. Interpolations
  (`${batch.machine}`, `{machine}`) are stripped first, because a template
  token filled with a hostname is not a word anyone reads. b-roll's
  allow-list has two entries, each with its reason; music's and ytdl's are
  empty. A stale allow-list entry is its own failure.

### CR-181 - one vocabulary in the dashboard's Python copy, two switches in one sentence, and the third GPU consumer - FIXED in repo 2026-09-04 (dashboard 0.7.34)

Wave 4's dashboard half. The sweep's section 4 gave one word per concept; this
is that word applied to every sentence the Python side hands a person - HTTP
`detail` messages, notice and alert titles, bodies and fix lines, invariant and
protection copy, the weekly report, and `jobs.explain`'s per-machine `why` -
plus the two behaviour changes the vocabulary exposed.

* **The words.** A **computer**, never a machine, a rig or a base rig
  ("device" stays for a Syncthing identity). **Upload** / **proxy download** /
  **folder sync**, never a lane: `alerts._lane_words`' fallback, the
  `lane_stalled` / `lane_error` alert titles ("a sync transfer is stuck"), the
  weekly report's `BYTES MOVED` heading and `health._lane_words`. The page an
  admin is sent to is **SYNC STATUS**, not FLEET, in seven fix lines across
  `alerts.py`, `notices.py`, `invariants.py`, `protection.py` and `api.py` -
  the nav has not said FLEET since 2026-08-18.
* **UX-19 - three ways for sync to be off, and they are three sentences.**
  **paused** = you did it, **stopped by your admin** = a fleet halt, **stopped
  itself** = the proxy-download brake or the disk floor. `health._why_sentence`
  says which one it is (the disk floor said only "the drive has 8 GB free" and
  read as a fault of the drive), and **where two are true the sentence names
  both**, ranked: `why_causes()` returns them apart, `why_not_syncing()` joins
  them with ". Also: ", and `/api/v1/fleet`'s `why` block carries `causes`.
  Only a switch a person can clear separately qualifies as a second cause
  (`WHY_SECOND_CAUSES`); a stall under a stop is the same fault said twice.
  With a pause under a local stop the editor used to clear the one the grid
  named and watch nothing move.
* **CMEDIA-1 - the third GPU consumer, the dashboard half.** B-roll indexing
  and proxy generation negotiate on the editor's own computer; the job
  scheduler was outside that agreement, and because both gates open on the
  same event (nobody at the keyboard) the common case was a whisper job ranked
  FIRST onto the computer that had been "idle" longest while it held 8-12 GB
  of VLM weights. The OOM came back as a job failure and earned that computer
  the per-machine cooldown for a fault it did not have. `jobs.policy_refusal`
  now refuses on `capabilities.jobs_gate.reason == "local_work"` with that
  companion's own sentence ("busy indexing b-roll", "busy making proxies"),
  which also keeps it out of `ranked_machines` entirely - refused before
  `rank_key` sees it, so longest-idle cannot promote it. `reason_code` for a
  job with no other candidate is `all_busy`: transient, so a Timeline Cards
  client waits instead of falling back for ever. An unknown gate reason is NOT
  a refusal - a dashboard that invents refusals from strings it has never seen
  is a queue that stops for a typo in a newer companion.
  **No column and no migration:** the gate is a fact about this second, so it
  rides the report and the claim (`machine_facts(capabilities=...)`), and
  `explain`, which answers from the database hours later, reads the two flags
  that ARE already stored on the row it selects, `ingest_active` and
  `music_ingest_active`. The companion's gate wins wherever there is one,
  because only the computer knows it is three minutes into a proxy encode.

`dashboard/tests/test_sweep_2026_09_04_copy.py` grew a second scan:
**`test_no_retired_word_in_python_copy`**, whole-word and case-insensitive
over `lane`, `machine`, `rig`, `halt(ed)`, `park(ed)`, `breaker`, `selection`
and `assignment` in every string these twelve modules hand a person. SQL, log
and `execute()` arguments, docstrings, route paths and single-word constants
are out of scope by construction, and everything left is in `VOCABULARY_ALLOWED`
with the reason: the `machine` FORM FIELD's validation message, `.ccsync/machine.json`
(a file name), and two button labels quoted back to the reader
([ MOVE ON THE SERVER AND ON EVERY MACHINE ], [ RELEASE THE HALT ]) which are
renamed in the templates or nowhere. The code keeps every name it had:
`selections` is still the table, `machine` the column, the route segment and
the form field, and `fleet_halt` / `disk_park` / `breaker_tripped` /
`machine_silent` are still the kind ids.

Tests: `test_health.py` +7 (UX-19 and the three sentences),
`test_jobs_scheduling.py` +8 (CMEDIA-1, from a stubbed report), the copy scan
+2. Twelve pins in seven suites moved to the new words, never loosened.
`docs/SELF_DIAGNOSIS.md` section 4 now states the rule for anyone adding a kind.


## Usability + resilience sweep, wave 5: the second customer (CR-182..CR-186, 2026-09-04)

`docs/USABILITY_RESILIENCE_SWEEP_2026-09-03.md` section 5, wave 5, the last
of the six. Five Opus builders: access (suspend, archive, local membership,
eviction that keeps a committed computer, optional SSH key with a pending
queue the wizard fills), install and restore (the snapshot mount set by the
deploy, deploy-time snapshot warning, uninstall registration on both
platforms, SmartScreen note, Resolve-not-installed probe, RECOVERY copy
without repo scripts, appliance doc reordered with the tailscale sign-in
link in the wizard), release (the soak gate on every door, gated
-EmitKindExtras, EULA + legal + HOW_IT_WORKS shipped in image, bundle and
bind mode, one free-space helper, release-key backup, WHAT IS RUNNING,
the dashboard's own unattended update on `policy = current` in code mode),
docs hygiene (HOW_IT_WORKS rewritten from the shipped tray and settings
window and pinned by a test, README index under test, ARCHITECTURE
blast-radius table, dated status headers, `projects_dir` refused at boot,
no repo script named in customer copy), and the companion's last
old-vocabulary strings. Waves 4 and 5 were built with no gate between them
at the owner's instruction; the one gate ran after this wave.

Dashboard **0.7.34** with **schema v50** (`known_editors.suspended_*`,
`projects.archived_*`, `machine_state.cap_jobs_gate_*`, `pending_ssh_keys`),
companion **0.9.69**, installer **1.0.41**. Dashboard first, as always.

Owed after the sweep: CI runs only one of the seven installer scripts
(`docs/CI.md` names the gap); the wizard specs bundle the uninstallers but
nothing pins the two `datas` rows; UX-21's Tailscale Serve half is still
NOT YET TRUE and the appliance doc keeps its DRAFT label; the htmx
feed-publish partial does not render `staged_note` yet (JSON, log and the
Mac scripts do); there is no box on an editor's computer to paste a report
token into, and queuing a fleet job is still CLI-only (CR-185's two
owner-level items).

### CR-182 - stopping a person, and removing a project, were things this dashboard could say but not do - FIXED in repo 2026-09-04 (dashboard 0.7.34, schema v50)
Wave 5's dashboard-core half, "the second customer" (DCORE-1, -4, -5, -6, -12,
OPS-2, UX-13, UX-14, plus CMEDIA-1's server side). Schema **v50**:
`known_editors.suspended_at/_by/_reason`, `projects.archived_at/_by`,
`machine_state.cap_jobs_gate_reason/_detail` and the `pending_ssh_keys` table.

* **DCORE-1** DISABLE revoked sessions and `cce1.` tokens and NOTHING else:
  nothing in the report path or the enforce cycle had ever read
  `users.disabled`, so a disabled contractor's companion kept posting under an
  identity token that never expires (CR-86), `record_known_editor` re-registered
  them every 30 s, and every project ticked for them stayed shared - while the
  page said DISABLED and the API answered `{"ok": true, "purged": {...}}`. The
  report path now asks `api._account_refusal` after the identity checks and
  before any write, and turns the computer away with the reason
  **"this account has been disabled"** stamped on `machines.report_refused_at/
  _reason` (the fleet grid's `[ BEING REFUSED ]` chip and the `report_refused`
  alert already render it). Absent counts as disabled on a local site - the
  account was deleted and the token outlives it - EXCEPT while no local account
  exists at all, which is the bootstrap window and must not 401 a live fleet.
  Fails open on a database error: a read that cannot answer never turns the
  fleet away. The confirm now names the consequence exactly ("Their computers
  stop reporting and keep the projects they already have until you remove the
  ticks or forget the computers"), and DISABLE/ENABLE write `user.disable` /
  `user.enable` to the audit ledger, which they never did.
* **DCORE-4** The shipped fleet runs `DASH_AUTH_METHOD=smb`, where DISABLE does
  not exist at all: the only "stop this person" control the Users page offered
  was DELETE, which removes the NAS account, forgets every computer, removes
  the Syncthing devices and drops the plan. **[ SUSPEND ] / [ RESUME ]** is the
  non-destructive one, auth-method independent because it acts on FLEET state:
  `known_editors.suspended_at` (v50), the report path refuses with **"this
  account is suspended"**, and the enforce cycle drops that person from
  `plan_rows` / `plan_editors` and from the unconditional shared-asset share, so
  their folders are unshared on the next cycle - the same path a removed tick
  takes, under the same blast-radius brake, and under-sharing is the safe
  direction. **The plan is never touched**, so RESUME puts back exactly what was
  there. `db.suspended_editors` is the ONE predicate every reader asks, the way
  `base_only_editors` is (CR-28). A SUSPENDED chip on Users and on SYNC STATUS,
  because otherwise a suspended person's computers look exactly like computers
  somebody switched off. Suspending yourself is a 409; suspending a name the
  fleet has no record of is a 404, never a row invented on the way past.
* **DCORE-5** Any signed-in editor can create a project - deliberately, it is
  how a shoot starts on a Friday night - and NOTHING could ever remove one: a
  typo became a permanent row in every tick list, in the plans grid and in the
  queue, and the only cure was deleting the folder on the NAS by hand and
  waiting up to 15 minutes for `deactivate_missing_projects`, which the DASH-4
  brake may itself refuse on a small site. **[ ARCHIVE ]** on SYNC PLANS
  (admin-only, `POST /api/v1/projects/{slug}/archive`) sets `active=0` - the
  flag every reader in `db.py` already filters on - stamps `archived_at/_by`,
  and the enforce cycle stops contributing that folder's ticks (its own and any
  borrower's). The stamp is load-bearing: archiving KEEPS the folder and the
  marker, so `upsert_project` runs for it on the next collector pass and a bare
  `active=1` would have un-archived it within 60 seconds, silently, with the
  shares. Nothing is deleted, the ticks stay in the table, and the confirm names
  how many editors sync it before the click. `project.create` (both doors: the
  JSON route and the editor's own NEW PROJECT partial), `project.archive` and
  `project.unarchive` are audited. The create form now SAYS who may create a
  project, that it appears for everyone, and that only an admin can take it back
  off those lists.
* **DCORE-6** `_require_fleet_member` proved membership by asking the NAS
  whether the account is in `editors`. On a `DASH_AUTH_METHOD=local` appliance -
  the zero-touch shape, which has no NAS credential by design - `nas_configured`
  is False, so the whole check was SKIPPED: any local account, including one
  made for browsing the b-roll library, got an identity token and the shared
  report token from `/api/v1/verify` and could write reports as itself. Local
  accounts carry a role and nothing consulted it. Membership on a local site is
  now the account row - present, not disabled, not suspended, role in
  `local_users.ROLES` - and the skip-with-warning path is reserved for
  smb/oidc sites with no NAS credential, where the log line names the real
  configuration ("no membership backend for auth_method='smb'") instead of
  pointing at DASH_NAS_PW, which is irrelevant there.
* **DCORE-12** Past the 20-machine cap, `evict_extra_machines` deleted the
  oldest `machine_state` AND `machines` rows, deliberately keeping the plan. But
  a computer with no registry row has no `syncthing_device_id` the enforce cycle
  can address, so its plan falls back to the person-level share set, and
  `api_tick` answers 404 "'leso' has no computer named 'LESO-MBP'" for a machine
  that is still holding footage and still in Syncthing - with no notice, no
  audit and no log line anywhere. The registry row is now KEPT whenever it still
  owes something (`_machine_has_commitments`: a `selections` row, or a Syncthing
  device id), which puts it in the LOST state the fleet grid already draws
  (`lost_machines`, DASH-16) with its `[ FORGET ]` button, and the cap refusal
  is logged at WARNING naming the computer and the reason. No new notice kind:
  a LOST state exists and rendering it there is what the finding asked for.
  `machine_state` is still pruned, and a row that owes nothing is still evicted.
* **OPS-2 / UX-14** Creating an editor account REQUIRED an SSH public key that
  only the wizard generates, and the wizard cannot run until the account exists:
  the owner's only exits were a repo checkout or emailing somebody a private
  key. The key is optional on create now (blank is refused only for an account
  that already exists, because both NAS backends WRITE the key they are handed
  and a blank one erases the key that account's lanes are using); the row shows
  **[ NO SSH KEY ]** with "upload and proxy download will not run until a key is
  added" and an **[ ADD SSH KEY ] / [ UPDATE SSH KEY ]** control that posts to
  the same `create_or_update_editor` path - which works in NAS mode, where the
  old keys routes were local-only. And the wizard now POSTs its public half to
  `POST /api/v1/ssh-key` under the identity token `/verify` has just issued it
  (`onboarding/steps.submit_ssh_key`, best effort, never a gate: an older
  dashboard 404s and the Finish page still prints the key). It lands in
  `pending_ssh_keys` (v50) and **grants nothing**: `[ SSH KEYS AWAITING
  APPROVAL ]` on Users is one click, the same shape a Syncthing device id
  already arrives in, and `[ DISMISS ]` throws the offer away without touching
  the account. A suspended or disabled editor cannot queue one.
* **UX-13** The Users page said "TRUENAS_PW is not configured on the dashboard
  ... Set TRUENAS_HOST / TRUENAS_USER / TRUENAS_PW on the app and redeploy" -
  the old variable names, and an instruction (edit the container's environment
  and redeploy) that is the one thing a non-technical owner cannot do, on the
  page the setup wizard's Editors step sends them to. It now reads "This
  dashboard has no NAS password, so editor accounts cannot be created here. Set
  it on Settings, Setup (Connect to your NAS), or set DASH_NAS_PW in the
  container", with a link to the setup task, and the htmx create route answers
  the same sentence instead of the bare variable name.
* **CMEDIA-1 (server side)** `jobs.local_work_words` reads
  `capabilities["jobs_gate"]` and nothing persisted it, so a machine holding
  8-12 GB of VLM weights or mid proxy encode looked to the scheduler exactly
  like an idle one - it ranked first on longest-idle, the job OOMed, and the
  machine earned the per-machine cooldown for a fault it did not have.
  `cap_jobs_gate_reason` / `_detail` (v50) are written beside the v49
  `cap_cards_*` columns, wholesale like every other capability, and decoded back
  into `jobs_gate`. NULL is "this companion did not say", never "idle".

**Deploy the dashboard before the companions**, as ever: a companion that sends
`jobs_gate` to a dashboard without v50 has that section discarded (loudly,
SYS-3), and SUSPEND on an old dashboard does not exist.

Not done, on purpose: `GET /api/v1/selection/...` still answers a suspended
editor's plan (the report refusal is what stops that machine, and a read that
returns the plan the enforce cycle is unsharing is not a way in); and DISABLE
still does not remove Syncthing devices - SUSPEND is the control that removes
shares, reversibly, and DELETE is the one that removes devices.

### CR-183 - the documented install ended with a recovery page that could only print commands, and an app nobody could uninstall - FIXED in repo 2026-09-04 (installer 1.0.41, server, dashboard 0.7.34)
Wave 5's install/recovery half, "the second customer": every item here is
something that worked on this fleet only because the person who built it was
standing next to it.

* **OPS-3** - `DASH_SNAPSHOT_DIR` had zero hits in `server/`, `INSTALL.md` and
  `SERVER.md`, while `BACKUP_RESTORE.md` opened with "start at the dashboard,
  not at this document". So every install that followed the documentation got a
  Settings -> RECOVERY that could browse nothing and restore nothing, and the
  owner found that out during an incident. The deploy sets both variables now
  (`install_dashboard_app.snapshot_source/snapshot_env/snapshot_volumes`): it
  asks the NAS which dataset the tree is in, checks `<mountpoint>/.zfs/snapshot`
  is really there, mounts it **read-only** at `/snapshots`, and computes
  `DASH_SNAPSHOT_PROJECTS_SUBPATH` from the paths it already has rather than
  guessing. Nothing is mounted where the directory could not be VERIFIED -
  docker creates a missing bind source, and inventing a `.zfs` inside a
  customer's footage tree is not a thing a deploy may do - so a Synology and a
  pasted compose file are one manifest key instead (`[tree] snapshot_dir`,
  `snapshot_projects_subpath`). Both variables are in `compose.yaml`,
  `compose.image.yaml` and the golden fixture, so the FILE and the POSTed DICT
  still describe one container. The page's own sentence changed with it: unset
  now reads **"this deployment was never given a snapshot mount"** and names
  the variable, never "there are no snapshots".
* **OPS-9** - Step 4 of the install configured snapshots and never checked that
  anything got scheduled, and the trap it cannot see is that `[apps] root` must
  BE a dataset while the deploy only ever `mkdir -p`s it (server-6: on this
  fleet's own box `dashboard.db` has never had a scheduled snapshot behind it,
  under a green transcript). `install_dashboard_app.py` asks the same question
  `setup_snapshots.py --list` asks - an EMPTY policy, so the refusal happens
  before the backend reads or writes anything - and prints
  `WARNING: no snapshot floor` with the backend's own sentence. It applies
  nothing and fails no deploy. `INSTALL.md` gained the Step 1 prerequisite
  (`sudo zfs create -p tank/apps/ccsync-dashboard`) and the Step 4
  `--list --apply` line, "not optional"; `SERVER.md` says it beside the key.
* **OPS-8** - the release signing key lives on one Windows profile, is never on
  the NAS and is in no snapshot, and the only "back it up" sentence in the repo
  was one line in `COMMERCIAL_READINESS.md`. It is a row in `BACKUP_RESTORE.md`
  §1 ("Protected by: **Nothing**") with the cost of losing it spelled out, plus
  the Android keystore beside it, and one line in `INSTALL.md` Step 6.
* **OPS-10** - on TrueNAS the Syncthing catalog app mints its own API key, so an
  owner following §3 literally invented a `SYNCTHING_API_KEY` that could never
  match and met 403s from four scripts with nothing pointing at the cause. The
  row is split by backend, and Step 2 says out loud that this is the one secret
  Step 3.1 produces rather than consumes.
* **OPS-22** - Syncthing's config (every device pairing, every folder share, the
  GUI credentials) lives in a TrueNAS-managed `ix_volume`, outside both
  `[tree] pool_root` and `[apps] root` - the only two things `setup_snapshots.py`
  knows about - and was in neither the protected table nor the deliberate
  omissions. It is a **NOT covered** row now, and §8 names the real recovery:
  re-run `install_syncthing_app.py`, re-approve every device, let the enforce
  cycle re-share. No footage is at risk in that state; replication simply stops.
* **OPS-24** - `$EDITOR site.toml` is bash on a page that calls the base rig
  Windows two paragraphs earlier (`notepad site.toml`, with the POSIX line
  underneath); `[stack] project_server = false` is named in Step 1, because it
  defaults to true and Step 8's health check FAILs its Postgres line by design
  without it; every `SERVER-SYNOLOGY.md` example passes `--site site.toml`, with
  a note saying why (a laptop holding several customers' manifests).
* **OPS-11** - macOS status 4 ("never launched") fires whenever Resolve's
  preference files are absent, which is also what a Mac with no Resolve on it
  looks like, so an editor who had not installed it was told to "launch it once,
  quit it, then re-run". `resolve_app_installed` probes the bundle first (the
  same probe the Tailscale step has always made) and a new status
  **`not-installed`** says "DaVinci Resolve is not installed on this Mac. CC
  Sync needs Resolve Studio (the paid version)." `onboarding/steps.py`'s
  `_RESOLVE_MAPPING_MESSAGES` carries the wizard's wording for it, so the
  Finish page says the same thing rather than falling through to "unexpected
  status".
* **OPS-12** - an EMPTY `--remote-root` was a named capability miss and exit 3;
  a MIS-TYPED one was a warning and a green run, which is the worse outcome,
  because upload then puts camera originals in the editor's bare SFTP home where
  nothing indexes them and the dashboard never sees them. Both platforms treat a
  non-absolute root as a capability miss now, "nothing was configured for upload
  and proxy download", and drop the value so nothing downstream writes it.
* **OPS-13** - only the companion had `com.apple.quarantine` stripped. rclone and
  Syncthing come out of the same curl-downloaded archives into the same
  `~/.local/ccsync/bin`, and a quarantined binary launched by launchd fails with
  no visible dialog at all - presenting as "upload and proxy download just never
  do anything", forever, because the re-run guard is `[ -x "$BIN_DIR/rclone" ]`.
  Both are cleared after the copy.
* **OPS-17** - `windows_uninstall.ps1` shipped inside the package zip and nowhere
  else, and the wizard path never delivers that zip: CC Sync appeared in no
  uninstall list on any machine. The Windows bootstrap copies the uninstaller
  (and `drive_mapping.ps1`, which it dot-sources) into `%LOCALAPPDATA%\ccsync\bin`
  and registers an **HKCU** uninstall entry - DisplayName from the site's
  `org_name`, `UninstallString` running it with `-NoProfile -ExecutionPolicy
  Bypass -File "<quoted path>"`, `NoModify`/`NoRepair`, `DisplayVersion`,
  `Publisher` - which `windows_uninstall.ps1` removes BEFORE it deletes the bin
  directory that entry names. macOS drops `macos_uninstall.sh` into
  `~/.local/ccsync/bin` and the closing banner names it. New sixth installer
  test: `installer/tests/Test-UninstallEntry.ps1` (19 cases, against a scratch
  key under `HKCU:\Software\ccsync-test`, cleaned up).
* **OPS-20** - with no certificate yet, an editor's first click meets "Windows
  protected your PC" whose default button is **Don't run**. That was documented
  for the developer in three places and for the editor nowhere. The Windows pick
  on `installer.html` says what to click and points at the sha256 already on the
  page; `START_HERE.md` says the same, with `Get-FileHash`.
* **UX-18** - the RECOVERY page prescribed three repo scripts to a person who has
  a container and a browser (the CR-59 shape). The snapshot one points at the
  SETUP page's "Protect your data" task; the post-rollback one is a button to
  the Projects page plus one sentence naming who to ask for the part no page
  here can do; the index rollback names the computer it runs on and who
  publishes the index. A scan test refuses `server/` in any fact's fix, and
  `setup_tree.py`/`setup_snapshots.py` in any step's body.
* **UX-21** - the appliance install's step 4 was `docker compose exec` followed by
  `docker compose logs` to read a sign-in URL out of a log: the one step of the
  whole install that forced a non-technical owner into a terminal. The setup
  wizard's tailnet task has a **[ GET A SIGN-IN LINK ]** button that asks the
  bundled node over its own LocalAPI, starts the interactive login and puts the
  `login.tailscale.com` link on the page. It never claims a sign-in it cannot
  see (that happens in the admin's browser, at Tailscale) and never posts to a
  node that is already Running. `APPLIANCE_INSTALL.md` is reordered so step 3 is
  "open the dashboard" and step 4 is "the wizard does the rest", with the CLI
  kept underneath as the fallback. **The DRAFT label stays**: nobody who is not
  the author has run it end to end, and WP B still owes Serve.

**Owed, and outside this builder's files:** `onboarding/build_onboard.spec` and
`build_onboard_macos.spec` bundle only the bootstrap, so on the WIZARD path
there is no `windows_uninstall.ps1` / `macos_uninstall.sh` to copy and OPS-17
degrades to the package path it already had (no entry is written pointing at a
file that is not there). One `datas` line in each spec finishes it. (The `not-installed` row in
`onboarding/steps.py` landed on E1's request, so that half is done.)

### CR-184 - the soak gate stood at three doors out of five, the EULA and the guide were in no shipped build, and the dashboard was the one component that could not update itself - FIXED in repo 2026-09-04 (dashboard 0.7.34, tools)
Wave 5's release half (REL-1, REL-4, REL-5, REL-7, REL-8, REL-9, REL-14,
REL-15, SYS-7 and SYS's cross-cutting "the dashboard's unattended update
path"). Nothing here is new machinery: it is the 08-28 controls standing at
the doors they were always meant to stand at, plus the two documents the
product asks a customer to read.

* **REL-1** - `make_current_refusal` lived in `api.py`, so the gate stood at
  the three doors that are HTTP routes and at neither of the two that are not:
  `./tools/release_macos.sh --publish --make-current` - the exact command
  CLAUDE.md tells the owner to run on the Mac - and a site on
  `[releases] policy = "current"`, which is the shape a second customer ships
  with. Both reached `store_verified_package(make_current=True)`, which checked
  the signature and the ordering and then set current with no soak, no recall
  check and no confirmation: a whole fleet taking a build no computer anywhere
  had run, unattended, on a daily poller.
  * `make_current_refusal` and `soak_minutes_for` moved to
    **`package_store.py`** - the only module allowed to write
    `companion_packages`, so a door that can publish is a door the gate stands
    at. `api.py` keeps one-line re-exports; every existing caller keeps its
    name.
  * a publish that ASKS for `make_current` and is refused is **published
    STAGED and returns the refusal as a `note`**, never a 4xx. The bytes are
    fine and signed; only the flip is in question. That also retires the
    ordering refusal that used to unlink the `.part` and 409 the whole publish
    - which is why the feed re-downloaded and re-discarded the same 40 MB on
    every check.
  * one sentence, every door: *"published and STAGED: push it to one computer,
    let it soak, then MAKE CURRENT."* (`package_store.STAGED_SENTENCE`). Both
    Mac scripts read the `note` out of the PUT's answer and print it instead of
    "made it CURRENT".
  * three carve-outs, all deliberate: a **rollback** (`ever_current`) as
    before; the **bootstrap** - nothing current for that platform and kind, so
    there is no fleet to protect and gating it would leave a new customer with
    no companion at all; and a **downgrade asked for by an unattended door**,
    which is a vendor WITHDRAWAL and must never be gated, or the gate pins
    every fleet on the build being withdrawn. An admin at `[ MAKE CURRENT ]`
    is refused exactly as before.
  * **`soak_minutes = 0` now really is the escape** the 08-28 comment
    promised. Zero used to leave `db.soak_state`'s "has any computer reported
    this build" half standing, which a build published thirty seconds ago can
    never satisfy - so with the gate at the publish door, a site that set 0
    would have found every publish staged for ever.
* **REL-4** - `-EmitKindExtras` signs `requires_dashboard`/`arch` into the
  record, and a companion below **0.9.55** does not know those field names: its
  signature check fails on the whole record, it refuses the build silently and
  permanently, and the recovery is a reinstall at that desk. The precondition
  was written in a code comment, in `docs/RELEASE.md` and in the owner's notes,
  and checked nowhere. `ship.ps1` step **0a** now reads the live dashboard's
  rollout counts on the fleet credential it already holds and refuses the flag
  unless every reporting computer is on 0.9.55 or newer - and a fleet it cannot
  read is a REFUSAL, not a pass. It names `check_deploy_drift.ps1 -AdminUser`
  to list them, because `_rollout_block` answers counts and never names, which
  is right. Every switch on `ship.ps1` has a `.PARAMETER` block now; the most
  dangerous one had none.
* **REL-5** - no EULA shipped in the image or the OTA bundle, so on the
  appliance shape the first-run wizard showed an empty licence box, a disabled
  `[ ACCEPT ]`, and ticked `eula` **green**. `docs/legal/` and
  `docs/HOW_IT_WORKS.md` now travel three ways: `COPY` lines in
  `dashboard/deploy/Dockerfile` (with the matching `!docs/legal` re-inclusion
  in `.dockerignore`), `TREES`/`FILES` in `tools/build_dashboard_bundle.py`
  (which REFUSES to build a bundle without them), and a bind-mode step 2a in
  `server/install_dashboard_app.py` that ships them into `<root>/app/docs`.
  `setup_engine`'s `EULA_PATH` searches `<app>/docs/legal` before the repo
  path - `parents[3]` is `/` in the container, where nothing has ever been -
  and the absent-file fallback is **`warn`**: *"no licence agreement is
  included in this build, so nothing has been accepted"*. It holds `done`,
  which is the point: a build that ships without one is visibly wrong rather
  than quietly complete. The same shipping makes `/help` (wave 4's owed item)
  answer on a deployed server for the first time.
* **REL-7** - the free-space floor guarded the human PUT and neither writer
  that arrives WITHOUT a human sizing it up. One helper now,
  `dashboard_update.space_refusal`, called by the PUT (507), by
  `release_feed.publish_from_feed` against the record's DECLARED `size_bytes`
  before a byte moves, and by `cli_tools.install_supported` against the tool's
  measured size (Claude Code is 313 MiB onto the volume `dashboard.db` lives
  on). The feed's refusal is recorded as its `last_error` - *"could not take
  companion 0.9.65: 380 MiB free"* - because a log line on a `policy = current`
  site is a sentence nobody will ever read. A volume that cannot be MEASURED
  still blocks nothing.
* **REL-8** - the Packages page told the admin to run
  `build_editor_package.ps1 -RebuildExe ... -Publish -MakeCurrent`, which is
  the exact command `ship.ps1` refuses to run (it restamps the manifest
  `tests_run=false`; OPS-1). It names `tools\ship.cmd` and `docs/RELEASE.md`
  now. Nothing on a customer-facing page should name a script flag that is a
  known footgun.
* **REL-9** - `publish_latest.py` signed off with the `manual` story
  unconditionally, including with `--make-current` and including for every
  site on `policy = current` - which is what this studio's own `site.toml`
  uses, and where the build reaches the fleet within one poll with nobody
  clicking anything. The closing block is conditional now, says what happens on
  both kinds of site, and carries the recall command, because that is the
  sentence you want in front of you at the moment you learn the build is bad.
* **REL-14** - losing `~/.ccsync-release/release.key` ends every fleet's
  ability to take another build, and the strongest statement of that was line
  668 of a 1200-line runbook. `release_key.py new` ends with the same warning
  voice `bake` uses; `release_key.py backup --to <path>` writes a copy and
  `--print` gives the base64 line for a password manager. **No passphrase
  wrap**: the in-tree crypto signs and verifies and does not encrypt, and a
  homemade construction protecting this particular secret is worse than the
  problem - so the tool says plainly that the copy IS the key. Either form
  records `backed_up_at` in `~/.ccsync-release/backup.json` and prints the
  instruction for the protection page's `[ I HAVE BACKED IT UP ]` (an
  admin-session htmx form with no JSON twin, and this script has no dashboard
  credential and no business acquiring one). `ship.cmd` prints one line when no
  backup was ever recorded. Never a refusal.
* **REL-15** - an install started in the CLI wizard was three module globals
  and a daemon thread, so a `docker restart` or an OOM kill during a 313 MB
  download lost it entirely: the page came back saying "not installed", with no
  trace, and left the `.part` behind for ever. `<data>/tools/<tool>/install.json`
  is written before the thread starts and cleared in its `finally`, so a record
  with no running thread means one thing only - this process died - and renders
  `[ INTERRUPTED ]` with `[ TRY AGAIN ]`. `.staging/*` older than 24 h is swept
  on the first status read of the process, the way `api._sweep_stale_parts`
  sweeps package uploads.
* **SYS-7** - `[ WHAT IS RUNNING ]` on **SETTINGS -> HEALTH**: this dashboard's
  version against the newest the vendor offers, the current companion against
  the newest the vendor offers, how many computers are on each build with the
  date each was published, and one sentence when they disagree, in SYS-2's
  wording. The drift doctor is a PowerShell script on a base rig, and a second
  customer has no base rig and no repo, so for them it does not exist. An
  unchecked vendor channel renders `[ VENDOR: NOT CHECKED ]`, never "up to
  date". Ship-time, the same question is a gate: `ship.cmd` refuses when the
  live dashboard is older than the build's `REQUIRES_DASHBOARD`
  (`-AllowBehind`), and `publish_latest.py` refuses when the newest dashboard
  bundle on the channel is (`--allow-behind`) - a channel with no dashboard
  record at all cannot answer, and says so rather than refusing.
* **the dashboard's unattended update path (SYS-2)** - the dashboard is the one
  component with no unattended update path and it gates every companion update
  through `requires_dashboard`, so one version stale freezes the whole fleet's
  updates on a site where nobody clicks anything. On `policy = "current"` **in
  image mode** the feed poller now applies a newer dashboard CODE bundle
  itself, through `dashboard_update.start_apply` with every stand-down rule
  intact (runtime-id match, nothing already running, free space, no live
  YouTube jobs, and the boot-attempt guard that rolls the tree back if the new
  code will not start). The soak is the same idea with the only evidence a
  dashboard bundle can have - **age**, i.e. whether the vendor has left the
  release standing for `release_soak_minutes`, the window in which a bad build
  is recalled. A bundle that failed here once is never retried unattended. The
  two pathways that stay manual say so in words the operator can act on: a
  **runtime** update names the NAS's own app manager, and **bind-mount** mode
  names `tools\ship.cmd -DashboardOnly` - the note lives in
  `meta.dashboard_auto_update_note` and prints in `[ WHAT IS RUNNING ]`.

Deliberately NOT done: no `dashboard_behind` notice KIND was registered.
`db.NOTICE_KINDS` is another builder's file this wave and the rule is that a
kind is registered WITH its writer; the same sentence reaches the operator
through the HEALTH box and the feed's `last_error`. Deploy the dashboard
before the companions as always, and note that after this the FIRST publish of
a version to a dashboard that already has a current build is STAGED - the ship
already knows that path (exit 3, `-Resume`), but a script that assumed
`make_current=1` meant "current" now gets a `note` instead of a lie.

### CR-185 - the document we hand a customer described a product that had not shipped for a fortnight, and eight surfaces answered a non-technical owner with "edit an env var" - FIXED in repo 2026-09-04 (docs, dashboard 0.7.34)

* **SYS-5** - `docs/HOW_IT_WORKS.md` section 6.6 listed nine tray items. Five of
  them ("Open my project folder", "Grade from server originals", "Copy
  diagnostics for your admin", "Open log", "Advanced") stopped being menu items
  at CR-88 on 2026-08-27 and moved into the companion's Settings window, which
  the customer explainer did not mention at all. The section is rewritten from
  `tray.py`'s own literals (the ten-item layout, plus the state lines and
  prompts that self-remove), and three sections were added: **6.7 The Settings
  window** (its eight sections as `settings_window.py` builds them today),
  **4.2 Sending originals up without bringing the project down** (upload only,
  CR-85, a phrase that did not occur in the document), and **7.1 What the
  server tells you it has found** (PROBLEMS THE SERVER FOUND, Settings >
  HEALTH, [ TAKE ME THERE ], and why [ NOT CHECKED ] is not [ OK ]). The whole
  document is now in the wave-4 vocabulary: no `machine` outside the glossary
  row that defines the word, no `lane` outside the one sentence that translates
  the three names for support, and no `halt` / `breaker` / `trip`.
  `dashboard/tests/test_help_doc_matches_the_companion.py` pins it both ways -
  a label that leaves `tray.py` fails, and a Settings section the window grows
  and the document does not describe fails too. The dashboard serves this file
  at `/help`, which is what makes it the dashboard suite's business.
* **SYS-12** - `docs/README.md` promised "every document in `docs/`, one line
  each" and was missing eleven, two of which CLAUDE.md names as required
  reading before touching their code paths (`FILE_MOVES.md`,
  `UPLOAD_ONLY_TICK.md`) and one of which exists because a session could not
  find the right release route (`RELEASE_PATHWAYS.md`). Rows added, and
  `tools/tests/test_docs_index.py` now asserts the promise in both directions:
  every `docs/*.md` and `docs/legal/*.md` is listed, and every link resolves.
* **SYS-13** - `ARCHITECTURE.md` said "up to three mounted sub-applications"
  three lines above a diagram with four, prose describing four and a rule that
  begins "three rules hold for all four". Fixed, plus the two weeks it had
  never caught up with: a "The server diagnoses itself" section pointing at
  `SELF_DIAGNOSIS.md`, one line each for `supervisor.py` and the phone port,
  and the **blast-radius table** the 08-28 sweep asked for (what stops, what
  keeps working and what it looks like, for each of eleven things being down).
  Two of them degrade quietly rather than badly, which is the harder failure,
  and the table says which two.
* **SYS-14** - `CLAUDE.md`'s "There is one command. It is `tools\ship.cmd`" is
  now the two-pathway sentence with the pointer to `RELEASE_PATHWAYS.md`. That
  framing cost a session half an hour reconstructing a ship it could not run,
  and CLAUDE.md is the file every session reads first.
* **SYS-19** - `MULTI_BASE_RIG_PLAN.md` and `COMMERCIAL_READINESS.md` are
  frozen snapshots written in the present tense, and both are read as status by
  anyone new. Each now carries a dated "Status as at 2026-09-04; not
  maintained: check `KNOWN_BUGS.md`" header. COMMERCIAL_READINESS's five
  per-item "DONE in repo, unshipped" lines name the ledger id that tracks each
  instead (CR-1/CR-2, CR-7, CR-11/CR-12/CR-13, CR-17, CR-8/CR-18), because the
  ledger is the thing that is maintained; where no single id covers a row it
  says "status unknown as at 2026-09-04" rather than guessing. Two sentences
  that had become untrue are marked where they stand: `effective_mode()`'s
  "either source says so" (CR-88 made it config only) and
  "`install_dashboard_app.py` still deploys bind-mount mode only".
* **SYS-20** - `[tree] projects_dir` has been half-wired since the 08-19 audit:
  read by `server/common.py` and by nothing else, absent from the manifest, and
  hard-coded as `Projects` in roughly a dozen companion modules. A customer who
  set it got a NAS tree under one name and a fleet that syncs nothing, silently.
  It is a refusal now, on `check_boot_secrets`' terms: `settings.py` will not
  start a dashboard whose `DASH_SITE_PROJECTS_DIR` is anything else (one hatch,
  `DASH_DEV_INSECURE=1`, loud in the log), and `site_store.import_toml` refuses
  a pasted `site.toml` carrying one rather than silently dropping it the way it
  drops `[apps]` and `[stack]` - the import is the path a second customer takes
  (ZERO_TOUCH_PLAN §6 step 1), so it is the one that mattered. Documented as
  fixed in `CONFIG.md` and `TREE_LAYOUT_AGNOSTICISM.md`. **Nothing sets this
  variable today**, so no live deployment changes behaviour. Still open: the
  same refusal on the base rig, in `server/common.py`, which is where the key
  is actually read.
* **DUI-8** - fifteen sentences answered a non-technical owner with "edit an
  env var and redeploy" or "run this script from the repo", for an owner who
  has neither a checkout nor SSH to the NAS. Two were also stale: the project
  page told an admin to run `server/accept_device.py` for something that has
  been a button on Settings, USERS for weeks. Each line now either points at
  the page that does it or says plainly "Ask whoever installed this server: it
  is a container setting, not something this page can change".
  `accept_device.py` and `~/.ccsync/config.toml` are gone from copy an
  appliance customer reads, and seven phrases (those two plus
  `DASH_RELEASE_FEED_URL`, `DASH_SHARED_REPORT_TOKEN_ENABLED`,
  `DASH_ENFORCE_MAX_REMOVALS`, `server/setup_tree.py`,
  `server/install_dashboard_app.py`) are in the wave-0 scan test so they cannot
  come back.

**Two things for the owner, not code.** The report-token panel used to say
"put it in that editor's `config.toml`"; there is no box anywhere on an
editor's computer to paste a report token into (`settings_window.py` has no
field for it), so the copy now says who to send it to. If that credential is
meant to be self-serve, it needs a control. And queuing a fleet job is still
CLI-only (`tools/jobs.py queue`); Settings > JOBS can only cancel.

### CR-186 - the loopback's ingest refusals, the fix summaries and the breaker's stand-down still spoke the old vocabulary - FIXED in repo 2026-09-04 (companion 0.9.69)

Wave 5 of the usability + resilience sweep (`docs/USABILITY_RESILIENCE_SWEEP_2026-09-03.md`
section 4, owner-approved 2026-09-04), finishing what wave 4 started on the
tray and the Settings window.

**What an editor saw.** Wave 4 converted the tray, the balloons, `app.py` and
the Settings window to one vocabulary: a computer is a COMPUTER, sync that is
not running is PAUSED / STOPPED BY YOUR ADMIN / STOPPED ITSELF, the transports
are UPLOAD / PROXY DOWNLOAD / FOLDER SYNC. The loopback server was not in that
pass, and it is the half an editor reads on their PHONE-sized b-roll and music
pages: about twenty refusals said "machine" (`"this machine has no synced tree,
so there is nowhere to stage the clips"`, `"nobody is signed in on this
machine"`, `"that file was not chosen on this machine"`, `"syncing the clip to
this machine: 42%"`, ...). The b-roll and music UIs print the companion's
`message`/`reasons` verbatim, so the same computer was a "machine" in the drop
zone and a "computer" in the tray, four inches apart. The ingest window's
held-back line said "need the base rig to finish", a phrase no editor has ever
been given a meaning for, and counted in "1 track(s)".

**And the breaker's sentence, SYNC-106's second half.** Wave 4 gave
`lane_guard.breaker_editor_reason()` the five editor sentences and wired them
into the tray line, the balloon and the report, but `rclone_lane`'s
`_breaker_stand_down` still wrote the TECHNICAL reason onto `LaneStatus.detail`
- which is what the Settings window and the dashboard's fleet chip render. So
one of the three trips still ended, on two screens, with `"Check remote_root in
config.toml."`: a file under `~/.ccsync` that a frozen build does not expose,
that names two internal keys, and that is not an editor's to edit.

**Fixed.** `detail` is now `"STOPPED (safety): "` plus the editor's sentence
for that trip's CAUSE (falling back through `_BREAKER_CAUSE_MARKERS` for a
latch written by an older build, which is read off disk on the next start).
Nothing else moved: the technical reason is still the breaker's `reason`, still
the `log.error` the trip writes, still `sync_guard.lane_b_breaker.reason` on
every report, and it is now also logged once per distinct trip at the
stand-down (`"lane B stands down, breaker reason: ..."`) rather than once per
rotation. The ~20 loopback refusals say "computer"; the held-back line reads
`"Waiting for the computer that is wired to the server: 1 track still on this
computer."`; the four `(s)` plurals left in `popup.py` / `fixer.py` go through
`ui_copy.count`.

**Words only.** No route, no JSON key, no state code, no report shape and no
behaviour changed - the web UIs pin the loopback's `state`/`ok` shapes and
prefer `message` when present, and every one of those keys is where it was.
`machine` stays what it is in code, on the wire (`X-CCSync-Machine`), in
`selections`/`machines` and in the log.

**Where.** `companion/src/ccsync_companion/`: `broll_server.py`,
`music_server.py`, `broll_fetch.py`, `broll_ingest.py`, `music_ingest.py`,
`popup.py`, `fixer.py`, `sync/rclone_lane.py`, `broll_vlm_sidecar.py`,
`music_clap_sidecar.py`, and one balloon in `app.py`. The scan that keeps it
that way is `companion/tests/test_sweep_2026_09_04_copy.py`: all ten modules
joined `MODULES`, with two allow-list entries, both `self.log` lines the
scan's log-argument filter cannot see (it only subtracts a module-level
`log.…`).

**The two sidecars and the stale-tmp toast, same day.** The seven refusals
`broll_vlm_sidecar.py` and `music_clap_sidecar.py` RAISE are not their own
screen: `broll_server.build_ingest_capabilities` puts them straight into
`reasons`, which both drop zones print. Converting the caller and not the
callee would have left one list saying "no usable GPU on this machine" beside
"nobody is signed in on this computer". So they went too - four in
`broll_vlm_sidecar.py` (including "this batch can run on another computer") and
three in `music_clap_sidecar.py` - and both modules joined `MODULES` with no
allow-list entry of their own. `app.py`'s stale-tmp balloon ("Found 1
half-copied file(s) from an interrupted copy") is the last `(s)` an editor
could be shown and now goes through `ui_copy.count` like the rest.
`test_broll_server.py`'s scan no longer excuses the GPU and model sentences: it
asserts over every reason in both capability answers, which is the one an
editor on a laptop reads most.

**Nothing left owed on this path.** Ten of the companion's modules that talk
to an editor now carry the scan, and the only "machine" left in any of them is
a dict key, a header name, a state code or a log line.


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
