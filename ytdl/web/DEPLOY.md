# Deploying `ytdl/web`

The YouTube downloader sub-app: one topic in, Claude Code expands it into EN+ZH
search terms, the server searches and filters, the editor reviews a thumbnail
manifest, and the selected clips land in
`<project>/Youtube/<term>/` on the NAS — from where sync distributes them and
the companion imports them into Resolve.

It is mounted in-process at `/ytdl` by `ccsync_dashboard.ytdl.mount_ytdl()`, on
exactly the contract `broll/web` and `music/web` use: tri-state
`mounted`/`absent`/`degraded`, fail-absent, no auth of its own. **A broken or
missing ytdl checkout must never stop the dashboard booting** — it is what tells
everyone whether their footage is syncing.

## Running it standalone (dev loop)

```powershell
cd ytdl\web
..\..\dashboard\.venv\Scripts\python.exe -m uvicorn ytdlweb.main:app --port 8791
```

`ytdl/web` has **no venv of its own** — the dashboard's has everything this app
imports (FastAPI, uvicorn, yt-dlp), and it is the interpreter the deployed
mount runs under, so it is the one to develop and test against.

```powershell
$env:YTDL_DEV_USER   = "alex"                          # stands in for the gate header
$env:YTDL_DEV_PROJECTS = "2026-ff5-energy=2026/FF5/Energy Transition"
$env:YTDL_DATA_ROOT  = "E:\tmp\ytdl-data"
$env:YTDL_PROJECTS_ROOT = "E:\tmp\projects"
```

| env var | container value | what it is |
|---|---|---|
| `YTDL_DATA_ROOT` | `/ytdl-data` | holds `ytdl.db`; also `claude`'s cwd. **The only tree this app owns** |
| `YTDL_PROJECTS_ROOT` | `/projects` | the Projects tree. Downloads land under `<label>/Youtube/<term>/` |
| `YTDL_DASH_DB` | `/data/dashboard.db` | the dashboard's database, opened **read-only** for the ticked-projects query |
| `YTDL_CLAUDE_HOME` | `/claude-home` | HOME + CLAUDE_CONFIG_DIR **for the claude subprocess only** |
| `YTDL_CLAUDE_BIN` | `claude` | absolute path if it is not on PATH |
| `YTDL_COOKIES_FILE` | *(unset)* | optional `cookies.txt` for YouTube bot checks — see below |
| `YTDL_FFMPEG_DIR` | `/opt/ffmpeg` | passed to yt-dlp; auto-detected if that directory exists |
| `YTDL_WORKER` | *(unset)* | `0` disables the pipeline thread. **The test suite sets it** |
| `YTDL_DOWNLOAD_PAUSE` | `3` | seconds between downloads — pacing against bot detection |
| `YTDL_ENRICH_WORKERS` | `2` | metadata fetches in flight at once during the enrich phase (was a hard-coded 4) |
| `YTDL_ENRICH_PAUSE` | `0.75` | seconds between metadata **requests across the whole pool** — 80/minute. See below |
| `YTDL_DEV_USER` / `YTDL_DEV_PROJECTS` | *(never set)* | standalone dev only |

The candidate ceiling itself is **not** an env var: the editor picks it per
search (50 / 100 / 200 / 400, default 100) and it is stored on the job row, so
a job resumed after a restart re-runs with the number it was submitted with.
The menu lives in `ytdlweb.config.CANDIDATE_CAPS` because the SPA's dropdown,
the API's allow-list and migration 006's SQL default all have to agree.

Every one is `YTDL_`-prefixed because this app shares one environment with the
dashboard, with b-roll (`BROLL_*`) and with music (`MUSIC_*`).

## The one-time Claude login

Claude Code runs headless on the server under a real account. **Until the login
has been done once, every job fails immediately with a `claude_auth:` banner
telling the editor to fetch an admin — never a hang.** The credentials live in
the `claude-home` volume and survive redeploys, so this is once per NAS.

```sh
docker exec -it -u 3000:3001 \
  -e HOME=/claude-home -e CLAUDE_CONFIG_DIR=/claude-home/.claude \
  <container> /opt/claude/claude
# then, at the prompt:
/login
# it prints an OAuth URL -- open it in any browser, sign in, paste the code back
```

Verify with the exact command the app's health probe runs:

```sh
docker exec -u 3000:3001 -e HOME=/claude-home -e CLAUDE_CONFIG_DIR=/claude-home/.claude \
  <container> /opt/claude/claude -p "say ok" --output-format json
```

**Headless alternative** (no interactive TTY on the NAS): run
`claude setup-token` on a machine that has a browser, then drop the resulting
credentials file into `claude-home/.claude/` and fix the ownership —
`chown -R 3000:3000 claude-home` and `chmod 600` on the credentials file.
Nothing else in the container may be able to read it.

`/ytdl/api/health` reports the state (`ok` / `unauthenticated` / `missing` /
`timeout`) from a **cached** probe refreshed by the worker at start and on every
failure — never per request, because `claude -p` costs a second or two and this
endpoint is hit by every page load. The SPA shows the banner from it *before*
anyone submits a job.

### `HOME` is set for the subprocess, not the container

uid 3000 has no `passwd` entry in the slim image, so `claude` cannot work out
where its credentials live and refuses to start. `ytdlweb/claude_cli.py` sets
`HOME`/`CLAUDE_CONFIG_DIR` **in the subprocess env only**. Do **not** export
`HOME` from `run.sh`: it is process-wide and would change it for the dashboard,
ffmpeg and everything else in the container. The subprocess also runs with
`cwd=/ytdl-data` (claude writes project state next to where it is run, and that
is the one directory this app owns) and `--disallowed-tools "*"` — these prompts
want text back, and `/projects` is mounted rw.

## What the deploy has to provide

| thing | where | why |
|---|---|---|
| `ytdl/web` tree | `<host>/ytdl-web` → `/ytdl-app:ro`, on PYTHONPATH | the app |
| `ytdl-data` volume | `/ytdl-data:rw`, `3000:3000 770` | `ytdl.db` + claude's cwd |
| `/projects:rw` | already mounted | downloads land here |
| `claude` binary | `/opt/claude:ro` | provisioned like ffmpeg (URL + sha256, cached tarball, root:root 755) |
| **`deno` binary** | `/opt/deno:ro`, on PATH | **not optional** |
| `yt-dlp` | `deploy/requirements.txt` | the downloader |
| `/opt/ffmpeg:ro` | already mounted | merge + the H.264/CFR conversion |

**Deno is not optional.** yt-dlp asks for `js_runtimes {deno,node}` +
`remote_components ejs:github` because YouTube now requires solving JS
challenges for full-quality formats, and the slim image has neither runtime.
Without deno on PATH, high-quality formats fail and jobs come back with
per-video download errors that look like YouTube being flaky.

## The umask trap

`deploy/run.sh` sets `umask 077`, so anything this process writes into
`/projects` is mode 0600 owned by uid 3000: present on disk, **and invisible
over SMB to every editor**. The worker therefore chmods explicitly —
`0o2775` on directories it creates, `0o664` on every file it writes including
the `.credits.json` sidecars and the provenance `manifest.json`. Each call is
non-fatal and logged (same pattern as `musicweb.routes_ingest`).

Loosening the umask instead is not an option: it is process-wide, and `007`
would hand group `editors` write access to `dashboard.db` in the same
container.

Verify once on the NAS after the first job: the files must be visible at
`P:\Projects\<label>\Youtube\<term>\` from an editor machine. (The NFSv4
`aclmode` caveat `run.sh` already documents applies here too.)

## `cookies.txt` escape hatch

Bulk anonymous downloads from a single datacentre IP is exactly what YouTube
bot-checks. The mitigations in order: the 3 s download pacing, the 0.75 s
metadata pacing, the per-search candidate ceiling, modest per-term caps, and
— if it still happens — export cookies from a signed-in browser to a
`cookies.txt` (Netscape format), put it somewhere only uid 3000 can read, and
set `YTDL_COOKIES_FILE`. It is passed to yt-dlp as `cookiefile`.

**Never `cookiesfrombrowser`**: there is no browser and no profile for uid 3000
in the container. The vendored `downloader.py` still accepts `cookies_browser`
for the standalone utility's sake; nothing on the NAS sets it.

Treat the file as a credential — it is a logged-in session for whichever
account exported it.

### Cookies are MANDATORY here, and useless on their own — measured 2026-08-11

The NAS got bot-checked for real: one search enriched 336 candidates, and
partway through the metadata pass YouTube started refusing the IP outright —
after which even a single `--print title` failed. All four states were then
tested in the live container against the same video:

| setup | result |
|---|---|
| anonymous | `Sign in to confirm you're not a bot` |
| cookies alone | past the bot check, then `No video formats found!` |
| cookies + PO token | past the check, formats found, `n challenge solving failed` |
| **cookies + PO token + EJS solver** | **works** |

Three things are load-bearing together, and any one alone reads as failure:

1. **`YTDL_COOKIES_FILE`** — a signed-in `cookies.txt`. There is no anonymous
   path left for a datacentre IP doing bulk extraction. Operator-provisioned;
   it is a live Google session, so it is never in this repo. Export it in
   Netscape format (a "Get cookies.txt LOCALLY"-style extension; Chrome's
   app-bound encryption defeats `--cookies-from-browser` on the desktop), then
   `install -o 3000 -g 3000 -m 600` it at `<host-root>/ytdl-data/cookies.txt`.
2. **`YTDL_POT_BASE_URL`** — the `bgutil` sidecar (compose). YouTube demands a
   GVS proof-of-origin token for *authenticated* requests and yt-dlp ships no
   provider, so cookies without this return **no formats at all** — the trap
   that makes cookies look like the problem.
3. **`YTDL_CACHE_DIR`** — yt-dlp *downloads* the EJS challenge solver
   (`remote_components: ejs:github`) and caches it. `run.sh` exports no HOME,
   so the default is `/.cache`, which uid 3000 cannot create: `PermissionError`
   and a re-fetch on every call.

`/api/health`'s `cookies: false` therefore means **broken**, not "fine, that
one is optional" — the opposite of what this section said before the block.

Sanity check the whole chain (expect a title and a real height):

```sh
docker exec -u 3000:3001 -e PATH=/opt/deno:/opt/ffmpeg:/usr/bin:/bin <container> \
  /venv/bin/python -m yt_dlp --cookies /ytdl-data/cookies.txt \
  --extractor-args "youtubepot-bgutilhttp:base_url=http://bgutil:4416" \
  --remote-components ejs:github --skip-download \
  --print "%(title)s | %(height)sp" https://www.youtube.com/watch?v=jNQXAC9IVRw
```

Look for `[pot:bgutil:http] Generating a gvs PO Token` in `-v` output: that
line is the provider working. Cookies expire — when jobs start failing with
the bot-check banner again, re-export them first.

**Volume is still the trigger.** The fix makes requests legitimate; it does not
make 336 rapid metadata calls look human. Pacing and caps are the other half,
and the worker's bot-check classification (`docs/youtube_dlp_bugs.md` YTDL-21)
is what tells you it happened instead of burning retries.

Both halves of that landed 2026-08-11, after the incident above:

- **a candidate ceiling per search** — 50 / 100 / 200 / 400, **default 100**,
  on `jobs.max_candidates` and enforced in `worker._phase_search` where the
  candidates are accumulated. That is deliberate: the cap has to bound the
  metadata CALLS (one per candidate row), not the length of the manifest after
  they have all been made. 100 sits just under 112, the only measured point at
  which YouTube has cut this IP off — so it also degrades safely if the cookies
  expire and behaviour drifts back towards anonymous.
- **a paced metadata phase** — `YTDL_ENRICH_WORKERS=2` in flight and
  `YTDL_ENRICH_PAUSE=0.75` s between requests *across the pool* (one gate, held
  during the wait, so the ceiling is 1/pause requests a second whatever
  YouTube's latency does). Before this the enrich phase was four threads with
  no delay at all — the download phase paced itself and the busier phase did
  not.

The arithmetic: 80 requests/minute against the roughly 240–480 the blocked
burst managed. A default 100-candidate search spends ~75 s in pacing, which
puts its whole metadata phase about where a 336-candidate unpaced one used to
be; a deliberate 400 costs ~5 minutes there. Raising `YTDL_ENRICH_WORKERS`
does **not** raise the rate — the gate does — it only lets a slow
`extract_info` stop stalling the phase.

## Where things live

```
ytdl/web/
  schema.sql            source of truth; ensure_schema() re-runs it on every DB it opens
  migrations/           NNN_name.sql + a predicate in ytdlweb.db._MIGRATIONS (at v6; see its README)
  ytdlweb/
    config.py           env paths, safe_join(), safe_term_dirname()
    db.py               ALL the SQL
    session.py          reads the gate-injected `x-ccsync-user` header
    projects.py         read-only query of the dashboard DB
    routes_api.py       sync, SQLite-only handlers
    worker.py           the pipeline thread + the phase machine
    claude_cli.py       `claude -p`, the four error prefixes, the SHOT_TYPES fragments
    vendor/             downloader.py + ytsearch.py from yt-credit-downloader
  static/               the SPA (every URL document-relative)
  tests/
```

Run the suite from `ytdl/web` so `python -m pytest` puts the in-repo package
first on sys.path:

```powershell
cd ytdl\web; ..\..\dashboard\.venv\Scripts\python.exe -m pytest tests -q
```

It needs neither `yt-dlp` nor the `claude` CLI: both are reached through seams
the tests replace, which is the same property that lets the app mount on a host
that has neither.
