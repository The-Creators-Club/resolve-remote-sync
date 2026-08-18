# The companion loopback API on 127.0.0.1:8899 — who may call it

*Written 2026-08-17 with COMMERCIAL_READINESS.md item 5 (finding C1).*

The tray app runs one HTTP listener on `127.0.0.1:8899`
(`companion/src/ccsync_companion/broll_server.py`). Three route groups hang off
it, because a second process holding that port breaks the tray (CLAUDE.md):

| Route | What it does |
|---|---|
| `GET /status`, `POST /insert` | the b-roll library's "Send to Resolve" |
| `GET /music/status`, `POST /music/send`, `POST /music/reveal` | the music library's |
| `POST /ytdl/reveal`, `GET /ytdl/capabilities`, `POST /ytdl/download`, `GET /ytdl/progress` | the YouTube downloader page's |
| `GET /broll/ingest/capabilities`, `POST /broll/ingest/{pick,prepare,run,control}`, `PUT /broll/ingest/upload/{staging_id}/{local_id}`, `GET /broll/ingest/{progress,thumb}` | b-roll ingest — drag clips onto the b-roll page and **this machine** indexes them (2026-08-18, `BROLL_INGEST_PLAN.md` §4.1) |

## What was wrong

Until 2026-08-17 the server answered every caller: `Access-Control-Allow-Origin: *`
plus `Access-Control-Allow-Private-Network: true`, and no Origin, Host, token or
content-type check anywhere. The justification written into the code was that the
socket binds to loopback only — but **a loopback bind is not an authorisation
decision**. Every page in the editor's browser is on the same machine: an ad
iframe, a forum, a link in a Slack message could

- insert clips into the timeline the editor was grading,
- start NAS downloads on their machine,
- spawn Explorer / `open` on their desktop,
- claim fleet YouTube jobs under their identity.

Three smaller holes travelled with it: `probe_darwin_mount` interpolated the
client's `share` into `f"/Volumes/{share}"` unvalidated (`share="../.."`
resolved to `/`, serving the whole filesystem), `POST /insert` was the one route
without the containment check the music/ytdl routes grew in MED-11, and a reveal
could `open` a path ending in `.app`, which on macOS *runs* it.

## What it does now

`companion/src/ccsync_companion/loopback_guard.py` holds the rules. Two ways in,
and only two:

**1. An allow-listed Origin.** The browser states, unforgeably, which page is
calling. The list is this deployment's dashboard: `dashboard_url` from
`~/.ccsync/config.toml` **plus** the same key from the cached site manifest
(`~/.ccsync/state/site.json`), each in both its `http` and `https` form —
Tailscale Serve fronts the same host on both, and a fleet provisioned before TLS
must not lose the button on the day the NAS moves behind it. An Origin that is
not on the list gets **403 and no CORS headers at all**, so the calling page
cannot even read the refusal. `Access-Control-Allow-Private-Network` is sent
only for allowed origins, and only they get a preflight answered.

**2. The loopback token.** A per-session random string written to
`~/.ccsync/loopback-token` (0600 on posix; on Windows the ACL is rewritten with
`icacls /inheritance:r /grant:r <user>:F`, because `chmod` there only toggles the
read-only bit), presented as the `X-CCSync-Loopback` header. This is for callers
that are not a browser and have no Origin to offer: the tray itself, the
onboarding wizard, an operator with `curl`. A page in a browser can never read
that file, which is the whole point of putting the secret on disk rather than
treating "no Origin header" as proof of locality.

On top of those:

- **GET with no Origin still works.** Opening `http://127.0.0.1:8899/status` in
  a tab is the self-test all three web UIs print when the button fails, and a
  top-level navigation sends no Origin. Nothing state-changing is a GET.
- **POST needs** an allowed Origin *or* the token, **and**
  `Content-Type: application/json`. That content type is not pedantry:
  `text/plain`, `multipart/form-data` and `application/x-www-form-urlencoded`
  are the three a cross-origin `<form>` can send with no preflight at all, so
  insisting on JSON is what makes the browser ask permission first.
- **`Host` must name loopback** (`127.0.0.1` / `localhost` / `[::1]`, on the
  listening port). Otherwise `evil.example` resolved to 127.0.0.1 would make the
  attacker's page same-origin with this server and skip the Origin check
  entirely. A missing `Host` is allowed — no browser omits it, and the caller
  that would is the one that must present the token anyway.
- **`share` is one safe path segment**: no `/`, `\`, `:`, control characters,
  leading dot, or surrounding whitespace, ≤ 64 characters. The macOS
  `/Volumes/<share>` probe additionally realpath-contains its answer under
  `/Volumes`, so a symlink planted there cannot redirect a share.
- **Every path-taking route realpath-contains** its answer inside the share
  root (`broll_server.contained_local_path`, which `/insert`, `/music/*` and
  `/ytdl/reveal` all now share).
- **A bundle is revealed, never opened.** `.app`, `.bundle`, `.framework`,
  `.pkg`, `.dmg` and friends force the "select in parent" form of the reveal on
  both platforms.
- **On-demand fetches go through the root guard.** Before an `rclone copyto`
  starts, the destination must be inside `local_root` and `root_guard.probe_root`
  must not say the tree is absent or misplaced — on macOS, rclone into an
  unmounted `/Volumes/<Name>` does not fail, it fills the boot disk. At most
  **two** fetches run at once; a third gets a clear "already downloading as much
  as it will at once" answer, which the UI's own 1.5 s re-poll turns into a retry.
- **The ingest upload route is the one PUT, and it has its own two rules**
  (2026-08-18). Every other route on this listener caps a body at 256 KiB and
  insists on `application/json`; a camera original is 40 GB and is not JSON, so
  `PUT /broll/ingest/upload/{staging_id}/{local_id}` takes
  **`application/octet-stream`** with a cap of **that one file's declared size
  + 1 %** (floor 64 KiB), streamed to `<local_id>.<ext>.partial` and renamed
  only on a complete body. `application/octet-stream` is accepted **only there**
  and **only with the `X-CCSync-Ingest` header** (or the loopback token): the
  header is not a credential, it is what forces the browser to preflight, so a
  page that never asked permission cannot stream bytes into staging. The
  envelope is otherwise unchanged — Host, then an allowed Origin *or* the token.
  Answers: `409` the slot is already filled, `413` bigger than declared, `507`
  the staging volume is below its free-space floor (checked *before* a byte is
  accepted), `403` a destination that does not realpath-contain inside the
  staging root.
- **Staging is inside the tree**, `<local_root>/Assets/B-roll Archive/.ingest`
  (`broll_ingest_staging_dir` overrides it for the base rig, whose `local_root`
  *is* the NAS share). Every write is containment-checked against that root,
  twice — once by the orchestrator, once by the route.
- **`POST /broll/ingest/run` reads three fields**: `batch_uid`, `staging_id`,
  `run_mode`. The tier, archive names, taxonomy and settings all come back from
  the server's `claim` under the fleet token. Same principle as `/music/send`:
  the browser is the only party that can see both the dashboard and this
  loopback, which is why it dispatches — not a reason to trust it with the work
  order.
- **`GET /broll/ingest/capabilities` is 200 always**, verdict in the body, and
  does no GPU probe or ffmpeg spawn: it is asked before the page renders its
  drop zone. `POST /broll/ingest/pick` is the one route that *learns* a local
  path — a native dialog on the UI thread, ≤ 300 s, after which it answers
  "cancelled" rather than parking a request thread (and, on macOS, the UI
  dispatcher's main thread) for the life of the process.
- **Refusals are generic.** "This request was refused — see the log." The
  reason, the offending Origin and the allow-list are log lines. A caller this
  server has just declined to talk to is not owed a description of the check it
  failed.

## Operating it

The failure mode to know: **if `dashboard_url` does not match the URL editors
actually type, every browser call 403s.** The companion logs exactly that, with
both the refused origin and the list it holds:

```
broll: refusing POST /insert from origin 'https://nas.example.ts.net' -- this
companion serves ['http://100.64.0.1:8000', 'https://100.64.0.1:8000']. If
that is the dashboard your editors actually browse, set dashboard_url (or
loopback_extra_origins) in ~/.ccsync/config.toml to match it.
```

Two escape hatches, both read straight off `config.toml` with no `DEFAULTS`
entry, because neither is a setting anyone should be setting routinely:

```toml
# additional exact origins (a deployment browsed under a second name)
loopback_extra_origins = ["https://nas.example.ts.net"]

# accept any loopback origin -- a dashboard running on the developer's own box
loopback_dev_origins = true
```

At startup the log line names the allow-list it built, or says
`NONE -- dashboard_url is blank, so no web page can drive this companion`.

## What this does *not* fix

- The dashboard-side half of the trust story: the pages are still served over
  plain HTTP on the LAN unless Tailscale Serve fronts them (item 6 / H1). An
  attacker who can MITM the dashboard origin can serve a page *from* it.
- The token authenticates *locality*, not a *user*: any process running as that
  editor can read the file. That is the correct boundary for a per-user tray app,
  and it is the same boundary `identity.json` already sits behind.
- Chrome's Local Network Access permission prompt is unaffected — a blocked
  fetch and a refused one still look alike from the page, which is why both web
  UIs tell editors to open `/status` in a tab to tell them apart.
