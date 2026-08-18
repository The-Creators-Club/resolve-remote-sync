# Deploying `ytdl/web`

The YouTube downloader sub-app: one topic in, Claude expands it into EN+ZH
search terms, the server searches and filters, the editor reviews a thumbnail
manifest, and the selected clips land in
`<project>/Youtube/<term>/` on the NAS — from where sync distributes them and
the companion imports them into Resolve.

Pasted links (the second box) skip all of that and land in `<project>/Youtube/`
**itself**, with no subfolder: there is no search term to sort them by, so a
folder invented for them was a Resolve bin with nothing meaningful in it
(2026-08-11). The companion collects those loose clips from **0.7.1** onwards —
before that its importer only walked the one level of term folders.

It is mounted in-process at `/ytdl` by `ccsync_dashboard.ytdl.mount_ytdl()`, on
exactly the contract `broll/web` and `music/web` use: `mounted` /
`disabled` / `absent` / `degraded`, fail-absent, no auth of its own. **A broken
or missing ytdl checkout must never stop the dashboard booting** — it is what
tells everyone whether their footage is syncing.

## THE FEATURE IS OFF UNTIL THE CUSTOMER TURNS IT ON

**2026-08-17 (docs/COMMERCIAL_READINESS.md item 2).** Shipping the tree used to
be the switch. It is now the site manifest:

```toml
# site.toml
[features]
youtube_download = true    # mount /ytdl at all
youtube_unblock  = false   # see "The unblock components" below
```

`--enable-youtube` / `--enable-youtube-unblock` on `install_dashboard_app.py`
do the same thing for a one-off deploy. With `youtube_download` off — the
default, and what the vendor build ships — `mount_ytdl()` returns `disabled`
BEFORE importing anything: `/ytdl` and the fleet claim/manifest/status routes
answer the dashboard's own 404, the nav link is absent, and every companion
hides its YouTube tray items, refuses the `/ytdl/*` loopback calls and installs
no downloader tooling (it reads `features.youtube_download` from
`GET /api/v1/site`).

Why: the customer, not the vendor, decides whether downloading third-party
YouTube material is lawful for them. See
**docs/legal/YOUTUBE_FEATURE_NOTICE.md**, which is also what the editor-facing
rights attestation below implements.

## The rights attestation

Every editor accepts a notice — "you have the right to use this material; you
are responsible for complying with YouTube's Terms of Service and copyright
law; CC Sync grants you no rights" — before their first download. It is
recorded **per user** in `ytdl.db`'s `attestations` table (username, wording
version, digest of the exact text, timestamp) and **per machine** in the
companion's `~/.ccsync/state/ytdl-attestation.json`. Until both exist:

* `POST /api/jobs`, `POST /api/jobs/urls` and `POST /api/jobs/{id}/download`
  answer **403** with `reason: "attestation"`;
* `POST /api/jobs/{id}/claim` (the companion's path) answers the same;
* the companion's `GET /ytdl/capabilities` reports `ok:false`, so the SPA
  quietly takes the server path.

The wording lives in `ytdlweb/attestation.py` (`TEXT_VERSION`, `NOTICE_TEXT`,
`COPYRIGHT_NOTICE`, `RATE_DISCLAIMER`) and is mirrored, trimmed for a dialog
box, in `companion/src/ccsync_companion/ytdl_attestation.py`. **Editing the text
means bumping `TEXT_VERSION` in both** — the version is stored with each
acceptance, so a re-worded notice re-prompts everyone instead of leaving the
records pointing at wording nobody agreed to.

## Running it standalone (dev loop)

```powershell
cd ytdl\web
..\..\dashboard\.venv\Scripts\python.exe -m uvicorn ytdlweb.main:app --port 8791
```

`ytdl/web` has **no venv of its own** — the dashboard's has everything this app
imports (FastAPI, uvicorn, yt-dlp), and it is the interpreter the deployed
mount runs under, so it is the one to develop and test against.

```powershell
$env:YTDL_DEV_PROJECTS = "2026-ff5-energy=2026/FF5/Energy Transition"
$env:YTDL_DATA_ROOT  = "E:\tmp\ytdl-data"
$env:YTDL_PROJECTS_ROOT = "E:\tmp\projects"
$env:ANTHROPIC_API_KEY = "<your key>"                  # the two AI calls
```

**There is no `YTDL_DEV_USER` any more** (2026-08-17, item 15). One environment
variable used to make every request on a deployed host arrive as that named
editor — their ticked projects, their jobs, their download history — with only
a comment standing between production and that. Standalone, the app now answers
401 until something *in the process* calls `ytdlweb.session.set_test_user()`;
add a two-line startup shim to your dev runner if you want a stand-in.

| env var | container value | what it is |
|---|---|---|
| `YTDL_DATA_ROOT` | `/ytdl-data` | holds `ytdl.db`. **The only tree this app owns** |
| `YTDL_PROJECTS_ROOT` | `/projects` | the Projects tree. A search's downloads land under `<label>/Youtube/<term>/`, a paste's directly in `<label>/Youtube/` |
| `YTDL_DASH_DB` | `/data/dashboard.db` | the dashboard's database, opened **read-only** for the ticked-projects query |
| `ANTHROPIC_API_KEY` | *(the CUSTOMER's)* | **required for search jobs.** The two AI calls go through the `anthropic` SDK. Blank = every job fails with the `claude_auth:` banner; nothing else on the dashboard is affected |
| `ANTHROPIC_BASE_URL` | *(unset)* | point the SDK at a proxy/gateway. Blank = `api.anthropic.com` |
| `YTDL_CLAUDE_MODEL` | `claude-sonnet-5` | a full model id (there is no CLI left to expand an alias) |
| `YTDL_CLAUDE_MAX_TOKENS` | `8000` | ceiling on one reply |
| `YTDL_COOKIES_FILE` | *(unset unless `youtube_unblock`)* | signed-in `cookies.txt` — see "The unblock components" |
| `YTDL_FFMPEG_DIR` | `/opt/ffmpeg` | passed to yt-dlp; auto-detected if that directory exists |
| `YTDL_WORKER` | *(unset)* | `0` disables the pipeline thread. **The test suite sets it** |
| `YTDL_DOWNLOAD_PAUSE` | `3` | seconds between downloads — pacing against bot detection |
| `YTDL_ENRICH_WORKERS` | `2` | metadata fetches in flight at once during the enrich phase (was a hard-coded 4) |
| `YTDL_ENRICH_PAUSE` | `0.75` | seconds between metadata **requests across the whole pool** — 80/minute. See below |
| `YTDL_MAX_DURATION` | *(unset = 1800)* | longest video (seconds) a **search** job keeps selected; longer ones are deselected with an "over N minutes" note the editor can overrule. Pasted-link jobs are exempt — they skip the filter phase |
| `YTDL_LOCAL_DOWNLOAD` | *(unset)* — **`install_dashboard_app.py` sets it to `1`** | `1` lets the SPA offer download jobs to the requester's companion (docs/YTDL_LOCAL_DOWNLOAD.md). Unset = the server-side path, byte for byte — which is what the fleet silently ran on for two days after 0.7.8 shipped, because nothing set this (2026-08-16). The deploy script now does; `GET /ytdl/api/health` → `local_download` says whether it took |
| `YTDL_LEASE_SECONDS` | `180` | how long a companion's download claim lives without a heartbeat before the server reclaims the job |
| `YTDL_HEARTBEAT_SECONDS` | `30` | how often the local executor is told to heartbeat (returned to it at claim time) |
| `YTDL_MIN_YTDLP_VERSION` | `2026.07.04` | claims from a companion whose yt-dlp is older are refused 403; its sidecar manager reads this via `GET /ytdl/api/config/ytdl-client` and self-updates |
| `DASH_REPORT_TOKEN` | *(the dashboard's)* | **required for local downloads**: the fleet routes (claim/heartbeat/manifest/clip-status) fail closed without it. Shared with the dashboard process — the mount runs in it |
| `DASH_SESSION_SECRET` | *(the dashboard's)* | **required for local downloads**: the fleet routes verify the companion's `X-CCSync-Identity` token against it (H5). Unset = 403, and the NAS worker downloads everything |
| `DASH_SITE_YOUTUBE_DOWNLOAD` / `_UNBLOCK` | `0` | set from `site.toml [features]` by the deploy; published in `GET /api/v1/site` |
| `YTDL_DEV_PROJECTS` | *(never set)* | standalone dev only |

The candidate ceiling itself is **not** an env var: the editor picks it per
search (50 / 100 / 200 / 400, default 100) and it is stored on the job row, so
a job resumed after a restart re-runs with the number it was submitted with.
The menu lives in `ytdlweb.config.CANDIDATE_CAPS` because the SPA's dropdown,
the API's allow-list and migration 006's SQL default all have to agree.

Every one is `YTDL_`-prefixed because this app shares one environment with the
dashboard, with b-roll (`BROLL_*`) and with music (`MUSIC_*`).

## Which AI answers the two calls (2026-08-18)

There are five possible backends now, chosen by the dashboard's **Settings →
AI providers** page (`ccsync_dashboard/ai_providers.py`) and resolved by
`ytdlweb/ai_backend.py` on **every call** — so a key an admin pastes works on
the next job, with no container restart, and a key they clear stops working
just as fast.

**The chain, first available wins:**

| # | provider | available when | credential |
|---|---|---|---|
| 1 | `claude_code` | the CLI is installed **on this host by the customer** and signed in | their own Claude subscription |
| 2 | `anthropic_api` | a key is set | `ANTHROPIC_API_KEY` or Settings |
| 3 | `codex` | the CLI is installed **by the customer** and signed in | their own ChatGPT subscription |
| 4 | `openai_api` | a key is set | `OPENAI_API_KEY` or Settings |
| 5 | `deepseek_api` | a key is set | `DEEPSEEK_API_KEY` or Settings |

An admin can **pin** one instead of `auto`. A pin that is not available is a
refusal, not a fallback: nothing else is spent in its place.

**The two CLI rows are behind `site.toml [features] ai_cli_providers`, which
ships OFF.** Nothing in this repo downloads, bundles or installs either CLI —
the customer installs it on the dashboard host themselves and signs it in
themselves, on the host, because an interactive OAuth cannot be completed from
a web page. Using a personal subscription to power a service may breach that
subscription's terms; the Settings page says so, and it is the customer's
decision. **API keys are the supported path** and the only one a deployment
gets without asking. See `docs/legal/YOUTUBE_FEATURE_NOTICE.md`.

Keys typed on Settings are files under `<data>/secrets/ai/`, 0600, written the
same way the five boot secrets are. **The environment always wins** where it is
set — the page says "set by the deployment" and refuses to overwrite it (409).

Standalone (`uvicorn ytdlweb.main:app`, no dashboard in reach) there is no
Settings page and no feature flag, so the app falls back to
`ANTHROPIC_API_KEY` → `OPENAI_API_KEY` → `DEEPSEEK_API_KEY` from its own
environment and **never** to a CLI.

| env var | container value | what it is |
|---|---|---|
| `OPENAI_API_KEY` / `OPENAI_BASE_URL` | *(unset)* | provider 4. Plain `urllib` against `/chat/completions` — **no `openai` SDK dependency** was added for two HTTP calls |
| `DEEPSEEK_API_KEY` / `DEEPSEEK_BASE_URL` | *(unset)* | provider 5. OpenAI-compatible, same implementation |
| `YTDL_OPENAI_MODEL` | `gpt-4o-mini` | conservative default; an unknown model id is an HTTP 400 on every job |
| `YTDL_DEEPSEEK_MODEL` | `deepseek-chat` | as above |
| `YTDL_CLAUDE_CODE_ARGS` | `-p --output-format text --disallowed-tools *` | how the customer's `claude` is invoked, non-interactive, prompt on **stdin**. One string so a customer on a different CLI build can correct a flag without waiting for a release |
| `YTDL_CODEX_ARGS` | `exec --sandbox read-only -` | the same for `codex` |
| `YTDL_AI_CLI_TIMEOUT` | `300` | a CLI is slower to start than an HTTPS call, so it has its own ceiling |
| `DASH_SITE_AI_CLI_PROVIDERS` | `0` | the feature flag's env spelling (a `site_settings` row from Settings beats it) |

The CLI subprocess is given an environment with `ANTHROPIC_API_KEY` /
`OPENAI_API_KEY` / `DEEPSEEK_API_KEY` **removed**: an admin who picked a CLI
provider wants the subscription used, and Claude Code prefers an API key when
it finds one — which would silently bill the wrong account, invisibly until
the invoice.

## The Anthropic API key (the customer's)

**2026-08-17, docs/COMMERCIAL_READINESS.md item 1.** The two AI calls —
search-term expansion and relevance filtering — used to shell out to the
interactive `claude` CLI, provisioned onto the NAS by the installer and
authenticated by a one-time `/login` whose OAuth credentials lived in a
`claude-home` volume. That ran every deployment on one human's personal Claude
account, could not be rotated or metered, and put an agent binary with
filesystem tools inside a container that mounts the whole Projects tree rw.

It is now `ytdlweb/ai_backend.py` (the transport; `claude_cli.py` kept the
prompts and the health cache) → the `anthropic` SDK, with a key **the customer
supplies**, either on Settings → AI providers or in the container's
environment:

```
ANTHROPIC_API_KEY=sk-ant-...
```

`install_dashboard_app.py` reads it from the deploying shell's environment,
masks it in `--dry-run` output, and (on Synology) writes it into the 0600 `.env`
beside the compose file rather than into the world-readable YAML. Blank is a
supported state: every job then fails immediately with a `claude_auth:` banner
telling the editor to fetch an admin — never a hang — and nothing else on the
dashboard is affected.

No tools are ever sent with these requests: not a policy the model is asked to
follow, a capability it is not given.

`/ytdl/api/health` reports the state (`ok` / `unauthenticated` / `missing` /
`timeout`) **and which provider it is about** (`ai_provider`, 2026-08-18) from
a **cached** probe refreshed by the worker at start and on every
failure — never per request, because a live call costs a second or two and this
endpoint is hit by every page load. The SPA shows the banner from it *before*
anyone submits a job. Verify by hand with any tiny request against the key.

### Prompt injection

The relevance call judges YouTube titles and channel names, which anyone can
write. Instructions therefore live in the **system** prompt (composed from this
repo's own tables) and every scrap of fetched text goes in the **user** turn
inside a labelled `<candidates>` / `<topic>` block, with the system prompt
saying out loud that the block is material to be judged rather than
instructions. `ytdl/web/tests/test_claude_cli.py` pins the split.

### Removing the old CLI provisioning (operator step, once per NAS)

A previously-deployed host still has two directories nothing mounts any more.
They are not deleted by the deploy (no-deletion rule); remove them by hand when
convenient, and note that `claude-home` holds a **live OAuth credential** for
whoever performed the original login:

```sh
sudo rm -rf <host-root>/claude-home <host-root>/claude-bin
# and, on the base rig, the cached download the installer kept:
rm -rf .cache/ytdl/claude
```

Revoke that credential from the Claude account it belongs to as well — deleting
the file does not.

## What the deploy has to provide

| thing | where | why |
|---|---|---|
| `ytdl/web` tree | `<host>/ytdl-web` → `/ytdl-app:ro`, on PYTHONPATH | the app |
| `ytdl-data` volume | `/ytdl-data:rw`, `3000:3000 770` | `ytdl.db` |
| `/projects:rw` | already mounted | downloads land here |
| `anthropic` + `ANTHROPIC_API_KEY` | `deploy/requirements.txt` + container env | the two AI calls |
| `yt-dlp` | `deploy/requirements.txt` | the downloader |
| `/opt/ffmpeg:ro` | already mounted | merge + the H.264/CFR conversion |
| **`deno` binary** | `/opt/deno:ro`, on PATH | **only on a `youtube_unblock` site** — see below |

## The unblock components (`[features] youtube_unblock`)

**Off by default and not part of the vendor build** (2026-08-17, item 3). Three
things exist only to get past YouTube's own anti-automation measures, and a
vendor should not install them on a customer's behalf:

| component | where | what it does |
|---|---|---|
| `bgutil` PO-token sidecar | a compose service | mints the GVS proof-of-origin token YouTube demands for authenticated requests |
| `deno` | `/opt/deno:ro`, on PATH | answers the "n challenge" JS puzzle for full-quality formats |
| `YTDL_COOKIES_FILE` | `/ytdl-data/cookies.txt` | downloads as a signed-in Google account |

With `youtube_unblock` unset, `compose_config()` emits none of them: no service,
no mount, no `YTDL_POT_BASE_URL`, no `YTDL_COOKIES_FILE`. `provision_ytdl_binaries`
does not run, and on the editor side `sidecar_tools` installs no deno and the
tray's "Sign in to YouTube (for downloads)…" item does not exist. **The code
stays in the tree, dormant** — turning the flag on is a configuration change,
never a different binary.

With it set, everything below applies as it always did.

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
`P:\Projects\<label>\Youtube\<term>\` (a search) or `P:\Projects\<label>\Youtube\`
(a paste) from an editor machine. (The NFSv4
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

## The download history needs a companion to open folders

The page's history panel is the permanent `downloads` ledger, read back
newest-first and **fleet-wide** (it is the cross-project dedupe record: every
editor already sees everyone's rows through the ALREADY IN badge, and rows are
upserted on the video id, so a per-caller view would lose clips as soon as
somebody else re-downloaded one). It is still behind the dashboard's login like
every other route here.

Clicking a row opens that clip's folder **on the editor's own machine**, which a
browser cannot do from an http page: it goes to the companion's loopback server
(`POST http://127.0.0.1:8899/ytdl/reveal`, body `{"rel_path": "<path under the
Projects root>"}`) exactly as b-roll's "Send to Resolve" does. Nothing about
this deploy needs to know where `P:` is — the companion resolves the path.

**Editors need companion 0.7.1 for it.** An older tray app 404s the route and
the page says so and offers the path to copy instead; no companion at all is the
same message. Nothing errors, and the rest of the panel works either way.

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
