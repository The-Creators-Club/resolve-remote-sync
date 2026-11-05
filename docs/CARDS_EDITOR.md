# The new Timeline Cards editor at /cards/edit

Written 2026-11-05 (MulticamPipeline `editor/docs/NAS-CUTOVER.md`, phase 2).
Built and tested, **not released and not deployed**: nothing here has run
against the NAS. This is the dashboard's half; the editor's half is
`editor/features/projects/README.md` section 3, "What CC Sync must do".

The plan is "beside first, then flip": the rebuilt editor is served at
`/cards/edit` while the original page stays at `/cards`; `/cards` moves over
once the new one has been used live on the NAS.

Shipping it is two things, in this order, because they are two different
pipelines (`docs/CARDS_DEPLOY.md` says why):

1. **A dashboard release** carrying `cards_edit.py`, the `websockets`
   dependency and the installer changes (`tools\ship.cmd`, Alex's password,
   interactive; `docs/RELEASE.md` section 6). The new dependency means the
   **image is rebuilt**, not just an OTA code bundle: `dashboard/requirements.lock`
   and `dashboard/deploy/requirements.lock` both changed.
2. **The Cards deploy** of a commit that carries `editor/dist-server/host.mjs`
   (`docs/CARDS_DEPLOY.md`, "The usual deploy"), with `[timeline_cards]
   editor = true` in `site.toml`. That run provisions Node (below), mounts it,
   sets the two environment variables and restarts the container.

## What the dashboard does

`dashboard/src/ccsync_dashboard/cards_edit.py`.

* **Starts the editor as a child process**, from the lifespan (never from
  `create_app`, so a test that builds an app spawns nothing):
  `<node> <cards-src>/editor/dist-server/host.mjs --write`. `--write` is
  deliberate: this is the live editor and it edits the vault, like the old page.
* **Supervises it.** A crash restarts it with a backoff (1 s doubling to 60 s;
  a child that lived 60 s resets the count). Five quick exits in a row is
  `failed`, which still retries, every 300 s at most. Its stdout and stderr go
  to the dashboard log prefixed `editor:`. The lifespan's shutdown sends
  SIGTERM and waits up to 15 s before SIGKILL, because the editor's SIGTERM
  handler is what flushes every open cut list to its `.cut.md`.
* **Gives it a minimal environment.** Not the dashboard's: the NAS password,
  the session secret and the fleet tokens are not passed (the allow-list is
  `cli_tools.cli_env`, the one the AI CLIs get). It receives `TC_VAULT` (the
  vault mount), `TC_HOST=127.0.0.1`, `TC_PORT`, `TC_MOUNT_BASE=/cards/edit`,
  `TC_MOUNT_HOME=/cards/`, `TC_PROXY_SECRET` (random, made once per dashboard
  process, memory only, 43 characters), `TC_WORK`, `TC_MEDIA_CACHE`,
  `TC_VIDEO_CACHE`, `TC_TRANSLATE_CACHE` and `TC_SEARCH_DATA` (all under
  `<data>/cards-edit/`), `TC_STATIC` (`<cards-src>/editor/dist` when present),
  `TC_PYTHON` (the container's own interpreter) with `PYTHONPATH=<cards-src>`
  for the Python workers, and `TC_CLAUDE_BIN` when the SET UP wizard installed
  a Claude Code CLI. The port is a free loopback port chosen at each start
  unless `DASH_CARDS_EDITOR_PORT` fixes it.
* **Proxies it, behind the login.** `/cards/edit` -> 308 `/cards/edit/`;
  `/cards/edit/{path}` for every method goes through `login_gate` like all of
  `/cards`, then to `http://127.0.0.1:<port>/cards/edit/{path}`: the raw path
  and query string unchanged, the request body streamed, the response streamed
  byte for byte (Range / 206 untouched, so audio and video seek), hop-by-hop
  headers handled. Every incoming `X-TC-*` header is dropped, the dashboard's
  own cookies (`ccsync_session`, `ccsync_cards_last`) and `Authorization` do
  not reach the editor, and `X-TC-Proxy-Secret` and `X-TC-User` are added.
* **Relays the WebSocket** (`/cards/edit/sync`, and any other socket under the
  mount) both ways with the same headers. **The socket is authenticated in
  `edit_socket`, not by `login_gate`**: that is an `http` middleware and never
  sees a websocket scope. It resolves the session cookie itself and refuses an
  Origin that is not the page's own Host (a WebSocket is not stopped by CORS).
  Nothing is accepted from the browser until the editor has accepted the
  upgrade.
* **Never fatal, tri-state.** Off (`DASH_CARDS_EDITOR` is not 1): no route is
  registered, nothing is spawned, `/cards/edit/...` is the old mount's
  not-found. On with something missing (no Node, no bundle, no vault, a crash
  loop): the routes exist and answer **503 with a plain page** (JSON for a
  `fetch`) saying what is missing and linking back to `/cards/`, and the
  dashboard boots regardless. `GET /api/v1/health` reports it under
  `cards.editor` (`status`, `state` = idle / absent / starting / running /
  backoff / failed, `detail`, `port`, `pid`, `restarts`, `last_exit`).
* **Does not depend on the old mount.** It reads `DASH_CARDS_SRC` and
  `DASH_CARDS_VAULT_ROOT` itself, so it works whether or not `/cards` mounted.
* **Links from the landing page.** `/cards/` shows a quiet "Open in the new
  editor" beside each episode, to `/cards/edit/?key=<Episode>/Script
  Docs/Cuts/<name>.cut.md` (newest cut list; the bare `/cards/edit/`, where the
  editor's own sheet chooses, when the episode has none), and **only while the
  editor is really answering**.

Routes are registered before the `/cards` mount (which is a catch-all under the
same prefix); `/cards/sw.js`, the manifest and the landing are untouched.
`/cards/edit/api/` and `/cards/edit/media/` answer an expired session with JSON
401, not a login page, like the old page's fetches and media elements.

## Settings

| Where | Name | Default | What |
|---|---|---|---|
| `site.toml` | `[timeline_cards] editor = true` | off | the installer provisions Node, mounts it and sets the two variables below. Needs `[timeline_cards] enabled` (a noted refusal otherwise) |
| env | `DASH_CARDS_EDITOR` | unset (off) | `1` turns the mount on |
| env | `DASH_NODE` | blank | the Node binary. Blank means `/opt/node/bin/node`, then `node` on PATH (a dev run). A named path that is not a file is an `absent` editor that says so, never a silent fallback |
| env | `DASH_CARDS_EDITOR_PORT` | `0` | `0` = a free loopback port per start; a number fixes it |
| env | `DASH_CARDS_SRC`, `DASH_CARDS_VAULT_ROOT` | (the old mount's) | the bundle's checkout and the vault, as for `/cards` |
| installer | `--no-node` | | skip provisioning Node for this run |
| installer | `CARDS_NODE_FILE` | | a copy of the pinned tarball already on this machine (its checksum is still enforced) |

The installer emits `DASH_CARDS_EDITOR` and `DASH_NODE` **only** when the
editor is on, so the default environment key set (and `compose.yaml`, and the
goldens) are unchanged.

## Node

`install_dashboard_app.py`, step 2h (`provision_node`), on deno's terms but
pinned: the official **Node v24.22.2 linux-x64** tarball from nodejs.org into
`<host-root>/node` (root:root 755), mounted read-only at `/opt/node`. Only
`bin/node` is installed: the editor ships as one bundled file and needs no
npm. **No checksum, no install**: the SHASUMS256.txt that nodejs.org publishes
must be fetchable, list the tarball, and agree with the sha256 pinned in the
script; otherwise nothing is fetched or sent. The remote script checks the
digest before unpacking and runs the candidate (`--version` must print exactly
the pinned version) before it replaces anything; an older binary is kept as
`bin/node.prev`. Non-fatal like ffmpeg: a failure is a note, and the editor's
page says Node is missing. `--dry-run` prints the step.

A bump is `NODE_VERSION` and `NODE_SHA256` together, from the published list.
The binary is the host's file run inside a Debian container, so "does it run"
is checked on the host at install and again by the supervisor at first start
(`cards.editor.detail` in the health block).

## Decisions made here (the owner may want to change them)

* **Host and Origin.** The editor refuses a `Host` that is a DNS name it was
  not told about, and a browser Origin that is not its own Host; the child
  cannot know the dashboard's name at start. So the proxy does the same-origin
  test itself (browser Origin against the Host it was sent) and then speaks to
  the editor as a loopback client: `Host: 127.0.0.1:<port>` and, only for an
  Origin that passed, `Origin: http://127.0.0.1:<port>`. A foreign Origin is
  forwarded unchanged and the editor refuses it. No `TC_ALLOWED_ORIGINS` or
  `TC_ALLOWED_HOSTS` is set, so none can go stale. `X-Forwarded-Host`,
  `-Proto` and `-For` carry what the browser saw. If a TLS terminator in front
  of the dashboard rewrites `Host`, the same-origin test fails closed (the
  editor answers 403 "cross-origin") and `TC_ALLOWED_ORIGINS` would be the fix.
* **User header.** `X-TC-User` is the signed-in account name as the dashboard
  knows it (not the display name, which is a label), plain when ASCII and
  percent-encoded otherwise (a header is latin-1 on the wire).
* **Port.** A free loopback port per start, not a fixed one; fix it with
  `DASH_CARDS_EDITOR_PORT` if the host wants to firewall it. The editor's own
  default (47900) is not used.
* **POST bodies.** The dashboard's `body_size_gate` buffers a POST/PUT/PATCH
  body up to 4 MiB before the proxy sees it; the editor's writes are small
  JSON. The proxy streams what it is given, and the response is streamed
  without ever reading `receive` (`Passthrough`, which exists because the
  replayed body made `StreamingResponse`'s disconnect listener fail).

## Not covered, on purpose

* **The editor's PWA manifest and service worker.** `/cards/edit/sw.js` and any
  manifest are behind the login (only the old `/cards/sw.js`, `/cards/manifest.
  webmanifest` and `/cards/icon.svg` are open, because a browser fetches a
  manifest without cookies). If the editor links a manifest, it will need
  `_open_path` entries like the old page's; the editor's `index.html` has none today.
* **The apps' update root.** `/cards/app/latest.json` stays where it is
  (`cards_app.py`); the editor README notes that under `/cards/edit/` the apps
  would look for `/cards/edit/app/latest.json`. Keep `/cards/` as the apps'
  update root until phase 4.
* **Stanza** is absent in the container, so the editor's cross-language
  analysis aids degrade (stored alignments and word links still work).

## The flip, later (phase 5)

When the new editor has been used live and is trusted:

1. Run the editor at `TC_MOUNT_BASE=/cards` (a settings value, not a rewrite:
   `cards_edit.MOUNT_PATH` and the router prefix become `/cards`, and the
   old page's mount moves to `/cards/old`, keeping its `/cards/p/<slug>/`
   pages one release for rollback). The landing's per-episode link then points
   at `/cards/` itself.
2. The routes that matter for the order in `app.py`: the editor's router stays
   registered **before** the old mount, the three `/cards/agent/*` fleet
   routes (`cards_tunnel`) and `/cards/app/*` stay ahead of both, and
   `login_gate`'s open paths (`/cards/sw.js`, manifest, icon) must be re-read
   for what the new editor serves there.
3. `_CSRF_ORIGIN_ONLY_PREFIXES` already covers `/cards/` (writes need a
   same-origin Origin), and the JSON-401 prefixes in `login_gate` already name
   `/cards/edit/api/` and `/cards/edit/media/`; they would move with the base.
4. Rollback is one setting: turn the editor off and `/cards` is the old page
   again, because nothing about the old mount was changed to make room.

## Tests

`dashboard/tests/test_cards_edit.py` runs a real stand-in child (a Python
script at the bundle's path, run by `sys.executable`, refusing any request
without the secret as `createProxyAuth` does) and covers: disabled registers
and spawns nothing; a missing Node / bundle / vault / checkout is a page naming
it, health reports it, nothing spawns; the secret and user are added and a
client's `X-TC-*`, session cookie and `Authorization` never arrive; Range /
206, HEAD, a gzip body, a streamed POST, a percent-encoded path and query;
the WebSocket both ways, refused without a login and across sites; a crash
loop backs off and says so; the child stops with the lifespan; the landing
page draws the link only while the editor answers.
`server/tests/test_cards_editor_node.py` covers the pin, the checksum rule
(unreachable list, no line, disagreement, failed download: nothing moves), the
remote script run for real under a stub sudo, the compose wiring and the dry run.
