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
| `MUSIC_LIBRARY_ROOT` | `P:\Assets\Music` | the library. An indexing host that maps the NAS share on another letter sets this; `MUSIC_SHARE_ROOT`/`MUSIC_ROOT` are accepted aliases, in that order |
| `MUSIC_PROXIES_DIR` | `<MUSIC_DATA_ROOT>/proxies` | 128k preview mp3s, one per track id |
| `MUSIC_TEXT_ENCODER_DIR` | `<MUSIC_DATA_ROOT>/text_encoder` | the exported CLAP text tower |
| `MUSIC_INDEXER_DIR` | `music/indexer` | only used by ingest and the waveform fallback |
| `MUSIC_INGEST_TOKEN` | unset | `X-Ingest-Token` for `/api/ingest`. **Required when this app runs standalone** — unset there, ingest answers 503. Mounted in the dashboard the session is the credential; see below |
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

### The ingest credential depends on WHERE this app is running

`broll.py` re-checks `X-Ingest-Token` on every `/broll/api/ingest/*` request because those
routes are an unauthenticated-by-design write path for the indexer (not a browser, no
session), so they are allowed *past* `login_gate`. Music's `/api/ingest` is different: it
is called by the SPA from a logged-in browser (as `/api/resolve*` and `/api/reveal` were
before they moved onto the companion's loopback), and nothing about `/music/*` is exempt
from `login_gate`. **Mounted in the dashboard, the session is the credential** — and it
must stay that way, because the page has no token to send.

**Standalone, it is not** (2026-08-17, `COMMERCIAL_READINESS.md` item 15). Run under its
own uvicorn there is no login in front of this app at all, so an open `/api/ingest` means
anyone who can reach the port writes files into the shared library and spends 900 s ffmpeg
transcodes doing it. So:

| where | `MUSIC_INGEST_TOKEN` | `/api/ingest` |
|---|---|---|
| mounted in the dashboard | unset | allowed — `login_gate` already ran |
| mounted in the dashboard | set | allowed with the header **or** on the session |
| standalone | set | requires a matching `X-Ingest-Token` (401 otherwise) |
| standalone | unset | **503, fail-closed** |

"Mounted" is a CALL, not an environment variable: `mount_music` runs
`musicweb.config.set_login_gated(True)`. A host that merely has a variable set is not a
process with the middleware wrapped around it, and the difference is the whole security
property. (`MUSIC_LOGIN_GATED=1` exists as an escape hatch for a deployment that puts its
own authenticating proxy in front — use it knowing exactly what is doing the
authenticating.)

One request is also **bounded**: `config.MAX_INGEST_FILES` (64) and
`MAX_INGEST_TOTAL_BYTES` / `MAX_INGEST_FILE_BYTES` (512 MB), refused with a 413 before a
byte is written. `app.py`'s `body_size_gate` only makes a *declaration* check on
`/music/api/ingest` — the multipart body is spooled past it on purpose, because buffering
a dropped album is the memory problem that middleware exists to prevent — so nothing
counted the parts themselves, and a request could carry ten thousand of them, each costing
a staging write, an ffprobe and two library hashes on the single-worker container.

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
- `main.py` still serves `/app.js`, `/ingest.js` and `/style.css` as **explicit routes**
  rather than a `/static` mount. Relative URLs make the subdirectory pointless, and
  `tests/test_api.py` pins the content types. This differs from b-roll; it is deliberate.
  `ingest.js` (2026-08-18) is a second CLASSIC script that shares `app.js`'s helpers
  through the global scope, so it is served and loaded after it, never bundled and never
  a module.

## Dashboard ingest: the fleet routes and what they need (2026-08-18)

`docs/MUSIC_INGEST_PLAN.md` step 2. There are now **two** ways music reaches the
library, and only the older one goes through this app's `/api/ingest`:

| | browser upload (2026-08-17) | dashboard ingest (2026-08-18) |
|---|---|---|
| who embeds | nobody here — the base rig drains `ingest_queue` later | the **editor's own machine**, with the exported CLAP audio tower (ONNX, no GPU) |
| who tags | the base rig, and a drain bundle carries the rows back | **this container**, from the uploaded embedding, with the text tower it already loads for queries (`musicweb/rescore.py`) |
| routes | `POST /music/api/ingest` | `/music/api/ingest-batches` (session) + `/music/api/fleet/ingest/…` (fleet) |
| credential | the session, or `MUSIC_INGEST_TOKEN` standalone | `X-CCSync-Token` (`DASH_REPORT_TOKEN`) **plus** a signed `X-CCSync-Identity` |
| still supported | **yes** — and it is the ONLY way a track a companion could not embed reaches the library (see below) | — |

**The fallback does not queue anything** (music-6, 2026-08-21; `KNOWN_BUGS`
MUSIC-ING-2). A companion that cannot embed ends the item
`queued_for_base_rig`, and that is a note in the batch ledger and nothing more:
the audio is still on the editor's machine and no `pending` journal row was
written, because the library allocates a filename at `result` and that item
never got one. There is no `queue_add` anywhere in the fleet routes. The page
asks the editor to drop the track through the browser upload above, which does
the whole safe dance (name allocation, both duplicate defences, the transcode,
the queue row) — a drain run in the belief that the fallback queued something
will correctly find nothing.

**Nothing new to configure.** The fleet routes read `DASH_REPORT_TOKEN` and
`DASH_SESSION_SECRET`, which this container already has, and they fail closed
without them: every `/music/api/fleet/ingest/*` call answers 403 and nothing
else about `/music` changes. `docs/CONFIG.md` §2.5b is the table.

Three deployment facts worth knowing before the first drop:

- **The music share must be mounted `:rw`-readable to this container**, which it
  already is for `/api/audio`. `uploaded` does not believe the companion: it
  `stat()`s the file at the path the SERVER allocated and compares the size,
  then widens the mode to 0664 — the container's `umask 077` otherwise leaves a
  file that is in the index and invisible over SMB (the same fix
  `routes_ingest._make_readable_to_the_fleet` applies to a browser upload).
- **`music-data` must stay writable.** `result` writes a `tracks` row, its
  windows and its waveform, and then re-scores every tag and axis in the
  library — the percentiles are library-relative, so one new track changes
  everybody's numbers.
- **Migration 004** adds `ingest_batches`/`ingest_items` and is applied by
  `ensure_schema` on the first connection after the deploy, like every
  migration here. `ingest_queue` is untouched: it is the fallback, not
  something 004 replaces.

The artefact the COMPANION needs — `music-clap-audio-<ver>.onnx` plus its
params JSON — is **not** shipped by this installer and is not in the table
below. It goes to the vendor release feed (`docs/RELEASE_FEED.md`), pinned by
sha256 in `music/indexer/music_models.py`; the container never embeds audio.
It is exported into `data/audio_encoder/`, which is exactly why `data/` is
shipped item by item rather than wholesale.

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
| `data/text_encoder/` | 481.6 MB | `<host-root>/music-encoder` → `/music-encoder` :ro | without it `Index.clap` falls back to the full CLAP model, which needs torch, which the container deliberately does not have → **`/music/api/search` 500s**. Ship the directory the exporter published, not a hand-assembled one: an artefact whose `manifest.json` carries no passing `check` block is treated as absent (MUSIC-1, 2026-08-14), and the exporter leaves the one it replaced beside it as `text_encoder.prev` — do not ship that |
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
| — | step 2e, static ffmpeg/ffprobe into `<root>/ffmpeg` (the **NAS** fetches it itself by default — see below) |
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
ssh truenas_admin@192.168.0.10 `
  "sudo ls -l /mnt/tank/apps/ccsync-dashboard/music-data"

# 1. pull it down -- music.db AND its -wal/-shm. The index is in WAL mode and a
#    file copy that leaves the -wal behind loses the transactions in it; a -wal
#    that arrives beside a DIFFERENT database is how a working index becomes a
#    corrupt one. Take the copy when nobody is mid-upload: this is a file copy,
#    not a snapshot.
ssh truenas_admin@192.168.0.10 `
  "sudo cp -a /mnt/tank/apps/ccsync-dashboard/music-data/music.db* /tmp/ && sudo chown truenas_admin /tmp/music.db*"
scp truenas_admin@192.168.0.10:/tmp/music.db* .\nas-index\

# 2. drain it HERE, where the GPU and the library are. The uploads themselves
#    are already in the share, so nothing but the index moves. --export-drain
#    writes the ANALYSED RESULTS of the rows this run closed to a small bundle;
#    that bundle, not this file, is what goes back (step 3a).
cd music\indexer
python index_music.py --queue --db ..\..\nas-index\music.db --export-drain drain.db
python index_music.py --queue-status --db ..\..\nas-index\music.db

# 3. that drained copy is now the truth: it has everything the base rig's index
#    had, plus the queued tracks. Make it the base rig's copy too, or the next
#    routine `--music-data db` will push a stale index back over it. A clean
#    close checkpoints and removes the -wal, so there should be none to carry --
#    but the DESTINATION's stale sidecars must go either way.
Remove-Item ..\web\data\music.db-wal, ..\web\data\music.db-shm -ErrorAction SilentlyContinue
Copy-Item ..\..\nas-index\music.db ..\web\data\music.db -Force

# 3a. THE PREFERRED WAY BACK (2026-08-17, COMMERCIAL_READINESS.md item 14):
#     apply the bundle to the LIVE index instead of pushing a file over it. It
#     closes only the journal rows this drain analysed, so anything an editor
#     queued in the meantime is still pending afterwards rather than gone. One
#     transaction, idempotent, and it needs nothing but the standard library --
#     so it runs on the NAS host, in the container, or against a copy.
scp drain.db truenas_admin@192.168.0.10:/tmp/
ssh truenas_admin@192.168.0.10 `
  "sudo python3 -m musicweb.drain apply /tmp/drain.db --db /mnt/tank/apps/ccsync-dashboard/music-data/music.db"
#     (run it from the shipped music-web tree so `musicweb` is importable; or
#      `python -m musicweb.drain inspect drain.db` first to see what it holds)
#     It reports failures too since 2026-08-21 (music-3): a row the base rig
#     could not analyse is parked `failed` HERE as well, with the reason, so
#     the editor's panel stops counting it as still waiting.

# 4. the whole-file push. Still correct for a FIRST install or a rebuild, and
#    still a lost-write window for anything else -- prefer 3a. Never `all`;
#    that is a 1.4 GB re-upload.
cd ..\..\server
python publish_db.py --which music --apply       # preferred; see below
# python install_dashboard_app.py --music-data db   # the deploy-time route
```

**Does the running app pick any of this up?** Yes, since 2026-08-21 (music-2),
and it did not before. `musicweb` caches one SQLite connection per worker
thread and builds its search matrices once per process, so an index changed by
another process — a `drain apply` writing to the file, or a publish renaming a
new one into place — used to be invisible until somebody POSTed
`/music/api/reload`, which no runbook mentioned. It now stats the database (and
its `-wal`) on the way through, at most every couple of seconds: a replaced
file drops every cached connection, and a changed one rebuilds the matrices on
the next search. **An older deployment does not**, so after applying a bundle
to a container running a musicweb from before that date, POST
`/music/api/reload` as an admin or restart the container.

**Prefer `publish_db.py --which music`** (added 2026-08-17,
`docs/COMMERCIAL_READINESS.md` item 8). It is `--music-data db` plus the three
checks that step 4 cannot make on its own: it checkpoints the source before
copying it, it runs `PRAGMA quick_check` on the candidate **on the NAS** before
anything live is renamed, and it refuses a publish whose content tables lost
more than 10% of their rows — which is exactly what a wrong `--source` or a
half-drained pull looks like. It keeps the previous index as
`music.db.prev-<ts>` and `--rollback --apply` puts it back by rename.
`ingest_queue` is deliberately excluded from the shrink check, because those
rows exist only on the NAS. Full procedure: `docs/BACKUP_RESTORE.md` §6.

Two hazards worth naming, because neither is detectable after the fact:

- **The window between step 1 and step 4 is a lost-write window — which is why step 3a
  exists.** Anything an editor queues while you hold the copy lands in the NAS `music.db`
  and is overwritten by a whole-file push. Applying the bundle (step 3a) has no such
  window: it names the journal rows the drain closed and touches nothing else, so a
  mid-drain upload is simply still pending. If you do push the file anyway, re-check
  `/music`'s queue immediately before step 4 and go back to step 1 if it grew.
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

**The download happens on the NAS, not here** (`--ffmpeg-fetch remote`, the default since
2026-08-17). It was the other way round from 2026-08-10, for a real reason: this is the one
step that has actually failed a deploy — the NAS pulls `johnvansickle.com` at ~28 kB/s, so
42 MB needs ~25 minutes against the 600 s timeout the step was then given, and because step
2e runs *before* any tree ships, the whole deploy died having landed nothing (the dashboard
stayed up on the old version throughout, which is the design working, but a fresh host could
not be provisioned at all). What outranks it is licensing: the static build is **GPLv3**, so
a machine that pushes it onto a customer's NAS is *conveying* it and owes corresponding
source or a three-year written offer (COMMERCIAL_READINESS.md item 3). A NAS that fetches
its own copy from upstream conveys nothing. The operational half is answered instead of
ignored — the remote step now gets 1800 s, its `curl` retries three times, and the step is
non-fatal, so the worst a slow host costs is `/api/ingest` answering 503:

    --ffmpeg-fetch remote        (default) the NAS curls the pinned URL and checks the pin
    --push-ffmpeg-from-local     fetch here, verify the pin, SFTP it over -- for an
                                 air-gapped site; prints the GPLv3 notice that then
                                 applies to you (== --ffmpeg-fetch local)
    MUSIC_FFMPEG_FETCH=…         same values, for a non-interactive deploy
    MUSIC_FFMPEG_FILE=…          a tarball you already have; still checked against the
                                 pin (local push only -- in remote mode it is ignored,
                                 loudly)
    MUSIC_FFMPEG_CACHE=…         where fetched tarballs are kept, default
                                 <repo>/.cache/ffmpeg

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
- `/api/resolve*` — **port step 8 landed**: they live in
  `ccsync_companion/music_server.py` on the editor's own `127.0.0.1:8899` now, reached by
  the browser. Nothing in this process talks to Resolve, and nothing here should — this
  process runs on the NAS, where `127.0.0.1` is the NAS.
- `/api/reveal` — port step 8 **missed this one**, and this document claimed otherwise
  until MUSIC-6 (2026-08-14). It stayed here running `explorer /select,<path>` on the
  serving host: on the container `os.name != 'nt'`, so it answered a 200 `{"ok": false}`
  that `app.js` threw away, and the button did nothing for every editor, silently, from
  the day music was mounted. It is gone from this app; the page now posts
  `{share, rel_path}` to `POST /music/reveal` on the companion, beside `/music/send`.
  **Editors need a companion new enough to have that route** — older builds 404 and the
  pane says so.

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
