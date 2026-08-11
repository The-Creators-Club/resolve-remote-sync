# Deploying `music/web`

**Both halves are done (2026-08-10).** `ccsync_dashboard.music.mount_music()` mounts this
app at `/music` in-process, exactly the way `ccsync_dashboard.broll` mounts `broll/web` at
`/broll`, and `server/install_dashboard_app.py` now ships the tree, its data and an
`ffmpeg` to the host. [What the installer does](#what-the-installer-does) is the record of
that change; it used to be the spec for it, and several things in it were wrong — those
are called out below rather than quietly deleted.

## Running it today

```powershell
cd music\web
.venv\Scripts\python.exe -m uvicorn musicweb.main:app --port 8790
```

`web/.venv` deliberately has **no torch**: `fastapi uvicorn[standard] numpy pytest httpx
python-multipart` and nothing else. CLAP is imported lazily inside
`musicweb/search.py::Index.clap`, so everything except `/api/search` works without it —
including similarity, which runs off the embeddings the base rig already stored.

| env var | default | what it is |
|---|---|---|
| `MUSIC_DATA_ROOT` | `music/web/data` | holds `music.db` and the ingest `staging/` dir. **The only path the app writes** |
| `MUSIC_SHARE_ROOT` | `W:\Creators_Club\Assets\Music` | the library. `P:\Assets\Music` on editor machines |
| `MUSIC_PROXIES_DIR` | `<MUSIC_DATA_ROOT>/proxies` | 128k preview mp3s, one per track id |
| `MUSIC_TEXT_ENCODER_DIR` | `<MUSIC_DATA_ROOT>/text_encoder` | the exported CLAP text tower |
| `MUSIC_INDEXER_DIR` | `music/indexer` | only used by ingest and the waveform fallback |
| `HOST` / `PORT` | `127.0.0.1` / `8790` | standalone run only |

Every one of those is `MUSIC_`-prefixed **because this app is mounted inside the dashboard
container and shares one environment with the dashboard and with the b-roll mount** (which
namespaces everything `BROLL_*`). The bare `DATA_ROOT` and `MUSIC_ROOT` still work as
fallbacks — they predate the mount and the dashboard's test conftest pins them — but
nothing should set them on a deployed host, and the installer sets only the prefixed ones.

## Mounted in-process at `/music`

`dashboard/src/ccsync_dashboard/music.py` is a copy of `broll.py` — it already solved this
for video — and the same four things make it safe. All four are covered by
`dashboard/tests/test_music_mount.py`:

- **In-process, not proxied.** `/api/audio/{id}` serves **HTTP Range / 206** so the player
  can seek. A reverse proxy in front of it reintroduces the "pass Range through
  unmodified" problem; mounted, uvicorn serves the 206s directly.
- **Auth comes from the dashboard.** Starlette middleware wraps mounted apps, so
  `login_gate` already covers `/music/*`. This app must never grow auth of its own, and
  `/music/api/*` answers **401 JSON** rather than a 303 to the login page, because
  `fetch()` and `<audio>` cannot follow an HTML redirect — `"/music/api/"` is listed
  alongside `"/broll/api/"` in `login_gate` for exactly that. Note it is `/music/api/` and
  nothing else: audio comes from `/api/audio/{id}`, not from a `/media` prefix the way
  b-roll's does.
- **The sub-app's lifespan does NOT run.** Starlette only runs the outermost app's. There
  is no lifespan here (`musicweb.db.con()` applies `schema.sql` on first use), so nothing
  strictly has to be replicated — but `music._init_music_storage()` opens the database and
  applies the schema at mount time anyway, because that is the **probe** that tells
  `mounted` from `degraded`. It closes its own connection and does not touch
  `musicweb.db._schema_ready`, so no global of this app is mutated by being mounted.
- **Tri-state, fail-absent.** `mounted` / `absent` / `degraded`. A broken or missing music
  checkout must never stop the dashboard booting. "The dashboard is what tells everyone
  whether their footage is syncing" outranks this feature.

`app.state.music_status` carries the tri-state and `app.state.music_mounted` is
`status == mounted`; the `[ MUSIC ]` nav link is shown only for the latter, because a link
to a page that 500s on every request is worse than no link.

| state | what happened | what an operator sees |
|---|---|---|
| `mounted` | imported, DB opened, schema applied | `/music` works, nav link shown |
| `absent` | `import musicweb.main` raised | `/music/*` 404s, no nav link, one WARNING in the log |
| `degraded` | imported, but the DB could not be opened | `/music` mounted and reachable if typed, **no nav link**, one ERROR in the log |

### There is deliberately no ingest token here

`broll.py` re-checks `X-Ingest-Token` on every `/broll/api/ingest/*` request because those
routes are an unauthenticated-by-design write path for the indexer (not a browser, no
session), so they are allowed *past* `login_gate` — and the b-roll app's own guard treats
the token as optional ("not configured = dev mode = open"). None of that applies here:
`/api/ingest`, `/api/resolve*` and `/api/reveal` are all called by the SPA from a
logged-in browser, nothing about `/music/*` is exempt from `login_gate`, and there is no
upstream dev-mode branch to reach. **The session is the credential.** The day music grows
a machine-to-machine ingest for the base rig (port step 7's queued handoff), it needs the
full b-roll treatment — a mandatory token validated in `create_app` and re-checked in
`MusicGate` — and a `music_enabled` / `MUSIC_INGEST_TOKEN` pair in
`dashboard/src/ccsync_dashboard/settings.py` to go with it.

For the same reason there is **no `DASH_MUSIC_ENABLED` flag**: b-roll needs one so the
dashboard can refuse to start rather than serve a write path with a weak token. Music has
no credential to validate, so whether the tree is shipped to the host *is* the switch, and
a host without it reports `absent`.

**The UI is prefix-safe** (port step 2, done 2026-08-10). Every fetch and asset URL in
`static/` is document-relative, and `tests/test_mounted_prefix.py` fails if a root-relative
`/api|/static` URL is reintroduced — verified by mutation, not just by passing.

Two things about that are load-bearing:

- **The bare `/music` → `/music/` redirect.** Starlette compiles `Mount("/music")` to
  require the trailing slash, so `/music` matches no route and the parent router 307s to
  `/music/`. Only then is the page's base directory `/music/`, making `api/stats` resolve
  to `/music/api/stats` rather than `/api/stats`. Do not "optimise" that redirect away.
- `main.py` still serves `/app.js` and `/style.css` as **explicit routes** rather than a
  `/static` mount. Relative URLs make the subdirectory pointless, and `tests/test_api.py`
  pins those two content types. This differs from b-roll; it is deliberate.

## What ships to the NAS

The `web/` tree, and — separately — the three things in `data/` the app cannot work
without. Not `indexer/`: it needs the RTX 3080, ffmpeg and a local mount of the library,
and the container has none of those. `musicweb/config.py` imports it lazily through
`add_indexer_to_path()` so a web-only tree still starts; the two routes that need it
(`/api/ingest`'s *inline* half, and the on-demand waveform rebuild) fall back to the queued
path or answer 503/404 with a readable message instead.

| what | size | where it lands | why it has to ship |
|---|---|---|---|
| `musicweb/`, `static/`, `schema.sql`, `migrations/` | 131 KB | `<host-root>/music-web` → `/music-app` **:ro** | the app itself |
| `data/music.db` | 19.5 MB | `<host-root>/music-data` → `/music-data` **:rw** | the entire index (376 tracks). **Writable**: queued ingest writes `pending` rows into it |
| `data/text_encoder/` | 481.6 MB | `<host-root>/music-encoder` → `/music-encoder` :ro | without it `Index.clap` falls back to the full CLAP model, which needs torch, which the container deliberately does not have → **`/music/api/search` 500s** |
| `data/proxies/` | 864.4 MB, 338 files | `<host-root>/music-proxies` → `/music-proxies` :ro | without them `/api/audio` still works and streams the 60 MB originals over Tailscale |
| static `ffmpeg` + `ffprobe` | ~160 MB unpacked | `<host-root>/ffmpeg` → `/opt/ffmpeg` :ro, on `PATH` | `/api/ingest`'s queued path returns 503 without them |

<a id="what-the-installer-does"></a>

### What the installer does

`server/install_dashboard_app.py`, steps 2c–2e. It mirrors what the script already does for
`broll/web` — `MUSIC_WEB_SRC`, the staged-verify-swap `install_tree`, root-owned `:ro`
mount, a `PYTHONPATH` entry — and adds what b-roll did not need, because b-roll's data is a
shared archive the container fills in itself and music's is not.

| b-roll | the music equivalent |
|---|---|
| `DEFAULT_BROLL_WEB_DIR = <repo>/broll/web`, `BROLL_WEB_SRC` | `DEFAULT_MUSIC_WEB_DIR = <repo>/music/web`, `MUSIC_WEB_SRC` (the same env var `dashboard/tests/test_music_mount.py` honours) |
| startup check for `broll_src/"app"/"main.py"`, hard-fails when `DASH_BROLL_ENABLED=1` | checks `music_src/"musicweb"/"main.py"` and **warns and skips** — there is no flag asserting the operator wanted it |
| step 2b `install_tree(root, "broll-web", …, staging_slug="ccsync-brollweb-upload")` | step 2c `install_tree(root, "music-web", …, excludes=MUSIC_EXCLUDE_DIRS, staging_slug="ccsync-musicweb-upload")` |
| — | step 2d, the data artefacts: `install_tree` for `music-encoder`/`music-proxies`, and `install_music_db` for the index |
| — | step 2e, static ffmpeg/ffprobe into `<root>/ffmpeg` (fetched **here** and pushed over the LAN by default — see below) |
| `mkdir`/`chown root:root`/`chmod 755` on `<root>/broll-web` | the same on `music-web`, `music-encoder`, `music-proxies`, `ffmpeg`; `music-data` is `3000:3000` mode `770` instead, like `<root>/data`, because it is the one music path the container writes |
| the archive root prepared `broll:editors 2770` setgid | `…/Creators_Club/Assets/Music` prepared exactly the same way, mounted `rw` |
| `run.sh`: `export PYTHONPATH=/app/src:/broll-app` | `export PYTHONPATH=/app/src:/broll-app:/music-app`, plus `export PATH="/opt/ffmpeg:$PATH"` |
| env `BROLL_DATA_ROOT: /broll-data` | env `MUSIC_DATA_ROOT`, `MUSIC_SHARE_ROOT`, `MUSIC_PROXIES_DIR`, `MUSIC_TEXT_ENCODER_DIR` |

**`MUSIC_EXCLUDE_DIRS` is `BROLL_EXCLUDE_DIRS | {"data"}`.** Excluding `data/` from the code
push is the whole point of the split; `.venv` needed no new entry, contrary to what this
document used to say — it has been in `EXCLUDE_DIRS` all along.

#### The 1.4 GB problem, and `--music-data`

The three data artefacts total ~1.37 GB and go up over paramiko's SFTP. Putting them in the
code push would mean re-uploading a 500 MB model and 338 mp3s every time somebody fixes a
template in the dashboard, so they are on their own switch:

    --music-data auto       (default) ship only what the NAS does not have yet
    --music-data all        force all three -- how you publish a re-index
    --music-data db         force just the index (or encoder / proxies / "db,proxies")
    --music-data none       ship nothing
    MUSIC_DATA_PUSH=…       same values, for a non-interactive deploy
    MUSIC_DATA_SRC=…        the data/ dir to ship, if it is not <MUSIC_WEB_SRC>/data

`auto` makes the *first* install the 1.4 GB one and every routine deploy a 131 KB one. It
probes with one `ls -A` per component, so a directory that exists but is **empty** — which
is exactly what step 1 creates — counts as missing, and a probe that fails counts as
missing too: re-pushing is cheap next to deploying a music UI with no index.

The index is the one artefact with a **merge hazard**, and it is why `db` is separately
switchable rather than bundled with the code. `music.db` on the NAS accumulates `pending`
rows from queued ingest; overwriting it with the base rig's copy discards any that the base
rig has not picked up yet. So it is never pushed implicitly, the previous file is kept as
`music.db.old.<ts>` (and never auto-pruned, unlike the code backups), and its **WAL
sidecars move with it** — `music.db` is in WAL mode, and a stale `-wal` left beside a
replaced database is how a working index becomes a corrupt one. The installer also warns if
the *source* has a non-empty `-wal`, because a plain file copy leaves those transactions
behind.

<a id="draining-the-nas-ingest-queue"></a>

#### Draining the NAS ingest queue

The container has no GPU, so a drag-and-drop upload only gets embedded, tagged and made
searchable when a base rig runs `index_music.py --queue` — and the `pending` row is in the
**NAS's** `music.db`, not the base rig's. Until 2026-08-11 there was no way for the two to
meet (MUSIC-3): `--queue` opened `config.DB_PATH` unconditionally, so on the base rig it
drained the in-repo index, printed "nothing to analyse", and the next `--music-data db`
push overwrote the NAS copy and discarded the row. `--db <path>` closes the loop. It is a
**pull, drain, push** — there is no merge, so the copy you push back must be the newest
index in existence when you push it.

```powershell
# 0. is anything waiting?  /music (the ingest panel) or, on the NAS:
#    the mount is 3000:3000 mode 770, so every read of it needs sudo
ssh truenas_admin@192.168.0.102 `
  "sudo ls -l /mnt/tank/apps/ccsync-dashboard/music-data"

# 1. pull it down -- music.db AND its -wal/-shm. The index is in WAL mode and a
#    file copy that leaves the -wal behind loses the transactions in it; a -wal
#    that arrives beside a DIFFERENT database is how a working index becomes a
#    corrupt one. Take the copy when nobody is mid-upload: this is a file copy,
#    not a snapshot.
ssh truenas_admin@192.168.0.102 `
  "sudo cp -a /mnt/tank/apps/ccsync-dashboard/music-data/music.db* /tmp/ && sudo chown truenas_admin /tmp/music.db*"
scp truenas_admin@192.168.0.102:/tmp/music.db* .\nas-index\

# 2. drain it HERE, where the GPU and the library (W:) are. The uploads
#    themselves are already in the share, so nothing but the index moves.
cd music\indexer
python index_music.py --queue --db ..\..\nas-index\music.db      # --retry-failed to re-attempt parked rows
python index_music.py --queue-status --db ..\..\nas-index\music.db

# 3. that drained copy is now the truth: it has everything the base rig's index
#    had, plus the queued tracks. Make it the base rig's copy too, or the next
#    routine `--music-data db` will push a stale index back over it. A clean
#    close checkpoints and removes the -wal, so there should be none to carry --
#    but the DESTINATION's stale sidecars must go either way.
Remove-Item ..\web\data\music.db-wal, ..\web\data\music.db-shm -ErrorAction SilentlyContinue
Copy-Item ..\..\nas-index\music.db ..\web\data\music.db -Force

# 4. push just the index back (never `all` -- that is a 1.4 GB re-upload)
cd ..\..\server
python install_dashboard_app.py --music-data db
```

Two hazards worth naming, because neither is detectable after the fact:

- **The window between step 1 and step 4 is a lost-write window.** Anything an editor
  queues while you hold the copy lands in the NAS `music.db` and is overwritten by the push.
  Re-check `/music`'s queue immediately before step 4; if it grew, go back to step 1.
- **A `--music-data db` push from a base rig that never drained** discards pending rows the
  same way. That is why `db` is opt-in and why the installer keeps `music.db.old.<ts>`
  forever — it is the only copy of the row you just lost.

`--db` is not queue-specific: any subcommand takes it, so `--peaks`, `--retag` and
`--queue-status` can all be pointed at a pulled-down copy. A path that does not exist is
refused rather than created, because an empty database answers `--queue` with "nothing to
analyse" — indistinguishable from a queue that was already drained.

#### ffmpeg: there is no image to build

`/api/ingest`'s queued path needs `ffprobe` (to prove an upload is audio) and `ffmpeg` (to
transcode `.ogg`) and returns 503 without them. **Nothing in this deployment builds an
image**: `dashboard/deploy/compose.yaml` runs a pinned, stock `python:3.12.7-slim` and
`command:`s `/app/deploy/run.sh` inside it. The container also runs as `3000:3001`, so it
cannot `apt-get install ffmpeg` for itself, and `run.sh` runs too late and too unprivileged
to help. (`broll/web/Dockerfile` exists but builds the *standalone* b-roll service; the
dashboard never uses it.)

So the installer provisions it, with the root SSH access it already has: it obtains a
**pinned, checksummed** static build (`MUSIC_FFMPEG_URL` / `MUSIC_FFMPEG_SHA256`), unpacks
it, **runs `-version` on the candidate before moving it into place**, and installs it to
`<host-root>/ffmpeg`, which compose mounts read-only at `/opt/ffmpeg`. It is idempotent
(already-installed binaries are left alone), non-fatal (a fleet dashboard must not fail to
deploy because a download host was unreachable) and skippable with `--no-ffmpeg`.

**The download happens *here*, not on the NAS** (`--ffmpeg-fetch local`, the default). This
is the one step that has actually failed a deploy: the NAS pulls `johnvansickle.com` at
~28 kB/s, so 42 MB needs ~25 minutes against `run_ssh`'s 600 s timeout — and because step 2e
runs *before* any tree ships, the whole deploy died having landed nothing (2026-08-10; the
dashboard stayed up on the old version throughout, which is the design working, but a fresh
host could not be provisioned at all). Fetching on the workstation and pushing over gigabit
LAN moves the slow, flaky half onto the machine that is fastest at it and leaves the NAS a
few seconds of SFTP and `tar`:

    --ffmpeg-fetch local     (default) fetch here, verify the pin, SFTP it over
    --ffmpeg-fetch remote    the NAS curls it -- for a workstation with no route out
    MUSIC_FFMPEG_FETCH=…     same values, for a non-interactive deploy
    MUSIC_FFMPEG_FILE=…      a tarball you already have; still checked against the pin
    MUSIC_FFMPEG_CACHE=…     where fetched tarballs are kept, default <repo>/.cache/ffmpeg

The local path probes the host **first** (`[ -x ffmpeg ] && [ -x ffprobe ]`), so a routine
redeploy of a provisioned host neither downloads nor pushes anything; the cache means a
*second* host does not re-download either. A tarball that fails the pin is deleted rather
than cached — one truncated transfer would otherwise poison every later deploy with an error
that reads like tampering. What ships to the NAS carries a digest either way: the pinned
hash, or, if `MUSIC_FFMPEG_URL` was overridden without one, the digest of the file actually
fetched. That cannot vouch for the download's provenance (nothing can, at that point) but it
does prove the NAS received what this machine holds, which is the failure a 42 MB SFTP adds.
`remote` needs `curl` and `tar -J` on the NAS; `local` needs only `tar -J` and `sha256sum`.

> The verification is an explicit `if ! … sha256sum -c -`, not a bare pipeline under
> `set -e`. A pipeline's exit status is its **last** command, so `check | filter` reports the
> filter's success — that is how `ffmpeg -version | head -1` printing `Killed` (SIGPIPE, on
> binaries that turned out fine) sailed past a hand-run `set -e` install script on
> 2026-08-10 and nearly shipped an unverified binary past the gate built to catch exactly
> that.

`FFMPEG`/`FFPROBE` are deliberately **not** set in the container environment even though
`_tool()` reads them first: those are absolute paths taken on trust, so pointing them at a
mount that was never provisioned would turn the clean 503 into a `FileNotFoundError`
partway through an upload. `PATH` is checked with `shutil.which()`, which tells the truth
about an empty mount.

#### Things that do not carry over from b-roll

- **The package is `musicweb`, not `app`.** `broll/web` is on `PYTHONPATH` as the top-level
  package `app`; a second package of that name would collide in `sys.modules` and one of
  the two would win silently. Do not rename it to match.
- **`python-multipart` in `dashboard/deploy/requirements.txt`.** FastAPI raises at *import*
  time — not at request time — for `/api/ingest`'s `UploadFile` parameter, so without it
  `import musicweb.main` raises and the mount reports `absent` with one WARNING, which is a
  very quiet way to lose the feature. ✅ present, along with `onnxruntime` (the text-encoder
  runtime) and `numpy` (which b-roll already needed).
- ~~`DATA_ROOT` is read at import time and `config.py` `mkdir`s it there.~~ **No longer
  true, and it was the point of the fix:** the `mkdir` moved into `ensure_data_root()`,
  called from startup, precisely so that an unwritable data root fails as `degraded` ("the
  tree is here and its data root is not usable by this container's uid") rather than as
  `absent` ("it was never shipped"). Those are different operator problems.
- ~~Rename `DATA_ROOT`/`MUSIC_ROOT` to `MUSIC_DATA_ROOT`/`MUSIC_LIBRARY_ROOT` before
  deploying.~~ **Done, and the second name was wrong.** `config.py` reads
  `MUSIC_DATA_ROOT`, `MUSIC_SHARE_ROOT` (not `MUSIC_LIBRARY_ROOT`), `MUSIC_PROXIES_DIR` and
  `MUSIC_TEXT_ENCODER_DIR`, each falling back to the bare name. The installer sets the
  prefixed ones.

#### The two write routes, revisited

- `/api/ingest` — **port step 7 landed**, so this no longer needs the b-roll token
  treatment on the NAS: with no importable indexer the container takes the *queued* path
  (validate → de-duplicate → transcode → land in the share → write a `pending` row), and a
  base-rig `index_music.py --queue --db <a copy pulled off the NAS>` does the embedding
  ([Draining the NAS ingest queue](#draining-the-nas-ingest-queue)). It is still a write path on the
  fleet's origin, and it is still guarded by nothing but the dashboard session — which is
  the deliberate choice argued above, not an oversight.
- `/api/resolve*` and `/api/reveal` — **port step 8 landed**: they live in
  `ccsync_companion/music_server.py` on the editor's own `127.0.0.1:8899` now, reached by
  the browser. Nothing in this process talks to Resolve, and nothing here should — this
  process runs on the NAS, where `127.0.0.1` is the NAS.

#### Known gap: ingested files land unreadable to editors

`run.sh` sets `umask 077` (correct for `/data`, which holds `dashboard.db` in a container
whose effective GID is `3001`/editors). Queued ingest writes the accepted upload under
`MUSIC_DATA_ROOT/staging/` and then `shutil.move`s it into the share, so the file arrives
in `P:\Assets\Music` as mode `0600` owned by uid 3000 — **invisible to the editors who
browse that library over SMB**, even though the directory itself is `broll:editors 2770`
setgid. `/broll-data` has the same caveat and works around it by pre-creating the
directories the app writes into; that does not help here, because it is the *files* that
are wrong. The fix belongs in `queue_one()` (an explicit `chmod` on the landed file, or a
per-call umask), not in the deploy, and it is not done. Until it is, an ingested track is
searchable in `/music` and unopenable from `P:` until someone fixes its mode.

## Bandwidth

The library is 9.5 GB across 376 tracks and 199 of them are `.wav` — up to 60 MB each.
Streaming originals to a remote editor for *preview* is wasteful; port step 6 generates a
128k mp3 per track at index time and serves those from `/api/audio/{id}`, keeping the
original path for Resolve (which reads it from `P:` directly, not over HTTP). Waveform
peaks are already precomputed at **900 bytes** per track, so scrubbing stays instant
regardless. Those proxies are the 864 MB `proxies/` push above — the one artefact the app
degrades *gracefully* without, which is why it is a separate `--music-data` component and
not a hard requirement.
