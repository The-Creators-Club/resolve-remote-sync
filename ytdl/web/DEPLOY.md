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
| `YTDL_DEV_USER` / `YTDL_DEV_PROJECTS` | *(never set)* | standalone dev only |

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
bot-checks. The mitigations in order: the 3 s pacing, modest per-term caps, and
— if it still happens — export cookies from a signed-in browser to a
`cookies.txt` (Netscape format), put it somewhere only uid 3000 can read, and
set `YTDL_COOKIES_FILE`. It is passed to yt-dlp as `cookiefile`.

**Never `cookiesfrombrowser`**: there is no browser and no profile for uid 3000
in the container. The vendored `downloader.py` still accepts `cookies_browser`
for the standalone utility's sake; nothing on the NAS sets it.

Treat the file as a credential — it is a logged-in session for whichever
account exported it.

## Where things live

```
ytdl/web/
  schema.sql            source of truth; ensure_schema() re-runs it on every DB it opens
  migrations/           NNN_name.sql + a predicate in ytdlweb.db._MIGRATIONS (none yet)
  ytdlweb/
    config.py           env paths, safe_join(), safe_term_dirname()
    db.py               ALL the SQL
    session.py          reads the gate-injected `x-ccsync-user` header
    projects.py         read-only query of the dashboard DB
    routes_api.py       sync, SQLite-only handlers
    worker.py           the pipeline thread + the phase machine
    claude_cli.py       `claude -p` + the four error prefixes
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
