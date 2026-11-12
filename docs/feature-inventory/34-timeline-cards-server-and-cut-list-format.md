# Timeline Cards: the editor's server, the cut-list model and the .cut.md file format

Terms used throughout:

- **Vault**: the folder tree that holds the episodes (the `TC_VAULT` setting). An **episode** is any folder in it that has a `Script Docs` subfolder.
- **Cut list**: one `.cut.md` file at `<Episode>/Script Docs/Cuts/<name>.cut.md`. It holds **the cut** (the ordered rows that make the edit) and **the bench** (sections that are out of the cut: shelves, saved sequences, legacy alternates).
- **Key**: a cut list's path relative to the vault, forward slashes, ending `.cut.md`. Every route and message names a cut list by key.
- **Op**: one edit, as data. Every change to a cut list is an op. **Version**: how many ops a cut list has had applied (the server's counter; the file's `rev:` line).
- **Client**: a browser tab or app that has a cut list open.
- **Working copy**: the private copy of every cut list a read-only run edits instead of the vault.

## Starting the server: command line, environment and run modes
(source: server/main.ts, server/types.ts, server/platform/modreg.ts)

- Started with `npm start` (runs the server from source) or from the bundled `dist-server/*.mjs`. The CC Sync dashboard starts the same configuration through another entry point (`features/projects/host.ts`, covered by another section), which calls this file's config reader, mirror and service loader.
- **Command-line flags**
  - `--write`: edit the vault's `.cut.md` files in place. Without it the run is READ-ONLY (the default).
  - Any other argument stops the server: "unknown argument X (the only flag is --write)".
- **Environment variables read by this part** (default, effect):
  - `TC_VAULT` (required): the vault root. Missing: the server stops with "set TC_VAULT to the vault root (a copy, for tests)".
  - `TC_HOST` (default `127.0.0.1`): the address to listen on. Any non-loopback address requires `TC_PASSWORD` (see Login).
  - `TC_PORT` (default `47900`): the port. `0` picks a free port.
  - `TC_ALLOWED_HOSTS` (default none): comma-separated extra host names the server answers to (for example a Tailscale name).
  - `TC_STATIC` (default `<editor root>/dist` when that folder exists, else none): folder of the built web client to serve.
  - `TC_WORK` (default `<system temp>/tc-editor-work/<first 12 hex of sha256 of the lower-cased absolute vault path>`): the working copy of a read-only run. Refused at start when it is inside the vault: "TC_WORK (...) is inside the vault; a read-only run must not write there".
  - `TC_WRITE_DEBOUNCE_MS` (default 150): delay before a cut list's file is rewritten after acknowledged edits.
  - `TC_SNAPSHOT_EVERY` (default 200, minimum 1): edits between history snapshots.
  - `TC_POLL_MS` (default 2000; 0 turns polling off): how often each open cut list's file is checked for outside edits.
  - A value for the three timing variables that is not a number, or below the minimum, stops the server: "not a usable number: X".
  - `TC_TOOL_PATH` (default `/opt/ffmpeg`, list separated by `;` on Windows and `:` elsewhere): when no folder on `PATH` holds `ffmpeg` (`ffmpeg.exe` on Windows), the first listed folder that does is put at the front of `PATH` for the server and everything it starts. No change when `PATH` already reaches ffmpeg.
  - `TC_ROOT` (default: two folders above the server code): the editor's root folder (where `dist`, `server`, `features` are looked up).
  - `TC_SYNC_PING_MS` (default 15000) and `TC_SYNC_IDLE_MS` (default 600000; 0 = never): socket heartbeat interval and idle-close time for cut lists (see Sync). Bad values fall back to the default silently.
  - Login, feature, media, Python and AI variables are listed in their own sections below.
- **Read-only run (default)**
  - At start every cut list found in the vault (see "the cut-list list") is copied into the working copy under the same relative path, but only if the working copy does not already have that file. Files already in the working copy are kept (their edits and history are the newer truth). Deleting the working copy starts again from the vault.
  - Log line: "READ-ONLY: nothing is written to the vault; edits go to the working copy (start with --write to edit the vault)", with counts copied and kept.
  - Every sync route and socket reads and writes the working copy. The media service still reads audio and cut lists from the vault, and keeps any waveform file it makes in memory instead of writing it.
  - Cut lists that appear in the vault after start are not copied until the next start.
- **`--write` run**: log line "--write: editing the cut lists in the vault itself"; sync reads and writes the vault directly; waveform files are written into the vault.
- **Startup order**: config read; working copy mirrored; login mode decided (a refusal stops the server before anything listens); the core services (sync, media), the platform service and every enabled feature mounted; then listen.
  - Log lines: "login required: the editor asks for TC_PASSWORD" (password mode); "trusted-proxy login: every request must come through the dashboard (TC_PROXY_SECRET)" (proxy mode); "listening on http://<host>:<port>" with the service names and vault.
- **Shutdown**: on SIGINT, SIGTERM, SIGHUP and SIGBREAK (the last two are the console window closing and Ctrl+Break on Windows) the server closes every service in reverse mount order (each open cut list is flushed to its file and its lock released), closes every socket, then exits with code 0 (1 if closing failed). A second signal during shutdown is ignored. A failure in one service's close is logged ("service close failed") and the rest continue.
- When run from the bundle, a service or feature module that is not in the bundle fails with "<path> is not in the server bundle (npm run bundle:server)".

## The HTTP router and error shape
(source: server/app.ts, server/types.ts, server/index.ts, server/media/index.ts)

- Every route is an exact path with optional named parts and an optional trailing wildcard. A `HEAD` request is answered by the matching `GET` route.
- Every error answer is JSON `{error, code}` with `cache-control: no-store`.
  - A path that is not valid URL encoding: 400 "the path is not valid URL encoding" (`bad-path`).
  - A route that throws unexpectedly: 500 "internal error" (`internal`), logged as "route failed". If the response had already started, the connection is cut.
  - No route and no static client: 404 "no such route" (`not-found`).
- JSON request bodies are capped (1 MiB unless a route says otherwise): over the cap 413 "request body over N bytes" (`too-large`); not JSON 400 "the request body is not JSON" (`bad-json`).
- WebSocket upgrades are dispatched by exact path; an unknown path gets a raw `404 Not Found` and the socket is closed. One handler per path. Largest WebSocket message: 8 MiB (a larger one closes the socket).

## Request guards: host name, origin, cross-site
(source: server/app.ts)

- **Host-name guard (DNS rebinding)**, on every request and every socket upgrade. Allowed: no `Host` header at all; any IP address literal (IPv4 or IPv6); `localhost` and any `*.localhost`; the machine's own name; the configured `TC_HOST`; every name in `TC_ALLOWED_HOSTS`; the host name of every allowed origin. Anything else: 403 "this server does not answer to that host name" (`bad-host`); for an upgrade, a raw 403.
- **Origin guard** applies to every request that is not a GET or HEAD, and to every GET or HEAD whose first path part is `api` or `media` (judged on the decoded, normalised path, so encoded or `..` tricks are caught), and to every socket upgrade.
  - A request with no `Origin` header passes (it is not from a browser page), unless it carries `Sec-Fetch-Site: cross-site` (a cross-site image or audio tag), which is refused.
  - An `Origin` passes when it is `http:` or `https:` and its host equals the request's `Host`, or when it is listed in the config's allowed origins. `null` origins (sandboxed frames, `file://`) are refused.
  - Refusal: 403 "requests from another site are not accepted" (`cross-origin`); raw 403 for an upgrade.
  - The allowed-origins list cannot be set from `npm start`'s environment; only the dashboard entry point fills it (`TC_ALLOWED_ORIGINS`, other section). From `npm start` it is always empty.
- Static client files (GET, not under `/api` or `/media`) are not origin-guarded.
- The login gate (next section) runs after both guards, so a login POST from another site is refused before it is read.

## Login
(source: server/auth.ts, server/app.ts)

Three modes, chosen at start by `TC_AUTH` and `TC_HOST`.

- **Mode selection**
  - `TC_AUTH=proxy`: trusted-proxy mode.
  - `TC_AUTH` empty or `password`: password mode if `TC_PASSWORD` is set; if it is not set, no login when `TC_HOST` is loopback (`localhost`, `::1`, any `127.x.x.x`), and a refusal to start otherwise: "TC_HOST=<host> answers beyond this machine: set TC_PASSWORD (8 or more characters) and the editor will ask for it".
  - Any other `TC_AUTH` value stops the server: "TC_AUTH=X: the choices are password (the default) and proxy".
- **No login (loopback, no password)**
  - `GET /api/session` answers `{ok: true, login: false}` (so the page knows there is no login rather than seeing a 404).
  - Everything else is open (subject to the guards above).
- **Password mode**
  - `TC_PASSWORD`: at least 8 characters (counted as Unicode code points), else the server stops: "TC_PASSWORD is shorter than 8 characters". May also be set on loopback to require a login there.
  - `TC_SESSION_SECRET` (optional): mixed into the cookie signing key. Changing it, or changing the password, signs everyone out. A restart with the same values keeps everyone signed in.
  - `TC_COOKIE_SECURE=1`: adds `Secure` to the cookie (behind HTTPS).
  - `TC_SESSION_DAYS` (default 30, minimum 1; not a number = 30): session length.
  - **The session cookie**: `tc_auth=v1.<expiry ms>.<signature>`, `Path=/; HttpOnly; SameSite=Strict; Max-Age=<session length>`. Valid when the signature matches, the expiry is in the future and no more than session length plus one day ahead, and it has not been logged out.
  - **Renewal**: on a page load (the request accepts `text/html`) by a session with less than half its life left, a fresh cookie is set.
  - **`GET /login`** (or HEAD): when already signed in, 303 to the `next` target; otherwise the login page.
    - The login page: title "Log in - Timeline Cards", the Timeline Cards mark and "TIMELINE CARDS", heading "Log in", text "This editor is open to the network, so it asks for its password.", one "Password" field (autofocus, browser password autocomplete), a hidden `next` field, a "Log in" button. Dark design, red button. Sent with `X-Frame-Options: DENY` and a strict content security policy (no frames, form posts to itself only).
    - With JavaScript: the button is disabled while sending; on success the page goes to `next`; on failure the server's sentence is shown under the form (fallback "The login failed.") and the password field is selected; a network failure shows "The server did not answer.".
    - Without JavaScript: a plain form POST; a wrong password re-draws the page with status 401 and "That is not the password." shown.
  - **`POST /api/login`**: body is a form (`password`, `next`) or JSON `{password, next}`, at most 8 KB.
    - Unreadable or oversized body: 400 "the login could not be read" (`bad-request`).
    - Wrong password: 401 "That is not the password." (`bad-password`) for JSON; the login page again for a form.
    - Right password: sets the cookie; JSON gets `{ok: true, next}`; a form gets 303 to `next`. Clears that address's failure count.
    - The password comparison takes constant time.
  - **Wrong-password slowdown**
    - Per client address: the first 5 failures are free; each further failure makes that address wait 2^(failures - 5) seconds, at most 300 seconds. The per-address count is only cleared by a successful login (it is not forgotten with time; at most 10,000 addresses are remembered, oldest dropped).
    - Per network (IPv4 first three octets, IPv6 first four groups): 20 free failures, then 2^(failures - 20) seconds, at most 300 seconds.
    - Whole server: 100 free failures, then 2^(failures - 100) seconds, at most 300 seconds.
    - The network and whole-server counts are forgotten 10 minutes after their last failure.
    - While any of the three waits applies: 429 "Too many wrong passwords. Try again in N s." (`slow-down`) with a `Retry-After` header. Checked both before and after reading the body, so parallel guesses count one by one.
  - **`next` target rules**: must start with `/`, must not start with `//`, `/\` or `/login`, must not contain a line break, at most 4000 characters after encoding; non-ASCII characters are percent-encoded. Anything else becomes `/`.
  - **`POST /api/logout`**: ends that session (the cookie is remembered as revoked until it would have expired; at most 50,000 remembered; forgotten on restart), clears the cookie, answers `{ok: true}`. Origin-guarded.
  - **`GET /api/session`**: 200 `{ok: true, login: true, expires}` when signed in; 401 "log in first" (`login-required`, `login: true`) when not.
  - **Every other path without a valid session**: a page load (GET or HEAD, accepts `text/html`, not under `/api/` or `/media/`) gets 303 to `/login?next=<the path>`; everything else gets 401 "log in first" (`login-required`).
  - **Socket upgrades** need a valid session, else a raw 401.
  - A crash inside the login gate answers that one request 500 and is logged "the login gate failed"; the server keeps running.
- **Trusted-proxy mode** (`TC_AUTH=proxy`, for the CC Sync dashboard mount)
  - `TC_PROXY_SECRET`: required, at least 16 characters, else the server stops: "the trusted-proxy login needs TC_PROXY_SECRET of at least 16 characters".
  - `TC_PROXY_USER_HEADER` (default `x-tc-user`): the header the proxy names the signed-in user in.
  - `TC_TRUSTED_PROXIES` (optional, comma-separated addresses): when set, only requests from those peer addresses are believed (IPv4-mapped IPv6 prefixes are ignored when comparing).
  - Every request and every socket must carry header `x-tc-proxy-secret` equal to the secret (constant-time compare) and, if a trusted list is set, come from a listed address. Otherwise: 403 "this editor is reached through its dashboard" (`proxy-required`), or a raw 401 for a socket.
  - `GET /api/session` answers `{ok: true, login: false, proxy: true, user}`; the user is the header's value with control characters removed, trimmed, cut to 120 characters, or null.

## Serving the web client
(source: server/main.ts)

- When a static folder is configured, any request no route answered is served from it.
- A path that decodes badly: 400 "bad path". A path that resolves outside the folder: 403 "outside the client" (`forbidden`).
- A missing file under `/api/` or `/media/`: 404 "no such route". Any other missing path is answered with `index.html` (the client routes itself). No `index.html`: 404 "the client is not built (npm run build)" (`not-built`).
- Content types for html, js, css, json, woff2, woff, svg, png, webmanifest, map; anything else `application/octet-stream`. Every static file is sent with `cache-control: no-cache`.

## Feature modules and feature flags
(source: server/platform/features.ts, server/platform/index.ts, server/platform/modreg.ts)

- A **feature** is a folder `features/<name>/` (name: lower-case letter, then up to 40 lower-case letters, digits or hyphens) containing any of `server.ts` (server half), `client.ts` (page half), `ops.ts` (extra edit types and feature-data rules), `bridge.py` (Python commands). Folders with none of the first three are ignored. No list is kept: dropping in a folder adds the feature.
- Mount order: transcripts, search, translate, markers, gapnotes, shorten, montage, chat, resolve, video, projects, lane, shelf, looks; any other feature after those, alphabetically.
- **Flags**
  - `TC_FEATURES=a,b`: only those features are on.
  - `TC_FEATURES_OFF=x,y`: all but those are on.
  - Names are lower-cased; names that are not valid feature names are ignored. Both may be set; "off" wins.
- A feature's extra edit types and data rules are registered before anything replays a history that might contain them. A failure there is recorded as that feature's failure; the feature still mounts.
- A feature whose server half cannot be loaded is logged "feature X could not be loaded" and skipped. One whose mount throws is logged "feature X did not start; the editor carries on without it" and skipped. The editor keeps running in both cases.
- **`GET /api/features`**: `{features: [{name, enabled, server, client, failed}], only, off}` (the flags as read). The page mounts the same set.
- **`GET /api/platform`**: `{python, ai}`: the shared Python pool's state (workers with index, process id, calls running, start count, alive; queued; running; registered features) or null if never used; the shared Claude runner's state (running, queued, dollars spent in the current hour, run count, and whether the CLI is usable with a reason and path) or null if never used.
- When the server stops, the shared Python pool and Claude runner are closed so no helper or CLI outlives it. A later use makes fresh ones.

## Proposals: edits offered for the person to accept
(source: server/platform/proposals.ts, server/platform/index.ts)

- A **proposal** is a titled list of edits produced by something on the server, which the page shows, previews and applies as one undo step. The server never applies a proposal itself.
- **`GET /api/proposals?key=<cut list>`**: `{proposals: [{id, title, why, ops, source, at}]}`, oldest first, expired ones removed.
- **`POST /api/proposals?key=<cut list>`**, body `{title, why, ops, source}` (at most 1 MiB): answers `{id}`.
  - Refusals (400 `invalid`): body not JSON or not an object; "a proposal needs a title" (empty after trimming); "a proposal is 1 to 2000 ops"; "op N of the proposal is not an edit this editor knows" (each op is checked against the edit catalogue, including feature edits).
  - Over 32 MiB on its own: 413 "that proposal is too large to keep".
  - Title cut to 200 characters, why to 4000. `source` must look like a feature name, else `server`.
- **`DELETE /api/proposals/<id>?key=<cut list>`**: `{ok: true}`; 404 "that proposal is gone" when it is not there.
- A bad or missing key: 400 `bad-key` with the key rule's sentence (see Keys).
- Limits: 50 open per cut list (oldest dropped), 200 cut lists (the least recently added cut list's proposals dropped), one day's life, 32 MiB of edits across all cut lists (oldest proposals of the oldest cut lists dropped first; the new one is kept). Held in memory only: a restart forgets them.
- No server code in the editor submits a proposal; only an outside caller of the POST route can (see Could not determine).

## The shared Python helper pool
(source: server/pybridge/index.ts, server/pybridge/worker.py, server/platform/shared.ts)

Features run the old pipeline's Python through this one pool.

- **Settings**
  - `TC_PYTHON` (or `TC_PY`), split on spaces: the interpreter command. Default `py -3.12` on Windows, `python3` elsewhere.
  - `TC_PY_WORKERS` (default 2, at most 8): long-lived Python processes.
  - Fixed: 4 calls at once per worker; 64 calls may wait; default timeout 120 s per call (a feature may set its own); 10 s grace for a cancelled call before its worker is restarted; at most 3 restarts per worker per 10 s; an answer line at most 32 MiB; 100 log lines per worker per 10 s.
- Each worker is started isolated and in UTF-8 mode (`-I -X utf8`, `PYTHONIOENCODING=utf-8`, `PYTHONUTF8=1`) with the pipeline folder on its import path. It announces itself ready, then serves calls, each on its own thread, so a long call does not block status calls.
- **Registration**: a feature registers its `bridge.py` (must exist; a feature name may not be registered with two different files). A feature with state in its process is **pinned**: all its calls go to the same worker. Others go to the least busy worker.
- **Fairness**: a feature that already holds a slot on a worker cannot take that worker's last free slot when another feature could use it. Per-feature concurrency defaults to 4 x workers.
- **Every call ends**
  - Timeout (counts time waiting in the queue too): "the <feature> helper did not answer \"<command>\" within N s"; the worker is told to stop that call; if it has not answered 10 s later, the worker is restarted and its other calls get "the helper was restarted because a request that was given up would not stop".
  - Caller gives up: "stopped" (`cancelled`), same stop-then-restart rule.
  - Queue full and no worker has room: "the <feature> helper is busy with other requests; try again in a moment" (`busy`).
  - Worker exits: its running calls fail with "the <feature> helper stopped (exit N): <last stderr lines>; ask again and it will be restarted"; it is started again on the next call.
  - Python not installed: "Python (<command>) is not on this machine, so the <feature> cannot run (set TC_PYTHON)"; later calls get "Python (<command>) is not on this machine (set TC_PYTHON)" until restarts are allowed again.
  - Restart budget spent: "the <feature> helper keeps stopping; it will be tried again in a few seconds".
  - An answer line over 32 MiB: the worker is restarted, its calls get "the helper sent an answer far too large to read, so it was restarted".
  - An answer line that is not JSON but names its call: that call fails "the <feature> helper sent an answer that could not be read".
  - Unregistered feature: "no Python bridge is registered for X".
  - Server stopping: "the server is shutting down" (`closed`); workers get 2 s to exit, then are killed.
- **Python-side errors**: a module with no `COMMANDS` registry or missing file (`no-module`), an unknown command (`unknown-command`), an ordinary refusal (the command's own sentence, no traceback logged), any other exception (its message; traceback logged).
- **Asks**: a command may ask the server something mid-call (how a bridge uses the server's one Claude runner). At most 8 open asks per call ("too many questions to the server at once", `busy`); a call whose caller answers no asks gets `no-ask`. An ask ends when its call ends.
- **Progress events** a command emits are passed to the caller while the call runs.
- Python's own prints go to the server log, never into the protocol. Numbers that are not finite are sent as null; lone surrogate characters are escaped so the answer still arrives.
- The worker never talks to DaVinci Resolve, starts no process and writes no file.

## The shared Claude runner
(source: server/ai/runner.ts, server/ai/sessions.ts, server/platform/shared.ts)

One runner for every AI feature; it drives the Claude Code command-line tool.

- **Which binary**: `TC_CLAUDE_BIN`, then `CLAUDE_BIN`, then `claude` on `PATH`.
  - On Windows the `PATH` search tries each `PATHEXT` extension first (so `claude.cmd` wins over the shell script npm also writes); the bare name only if it already has such an extension.
  - A `.mjs` or `.js` file runs under the server's own Node; a `.cmd` or `.bat` runs under `cmd.exe /d /s /c` with careful quoting (paths with spaces work).
  - A named binary that does not exist: "TC_CLAUDE_BIN=X is not an executable file and is not on PATH". None found: "the claude CLI is not on PATH (set TC_CLAUDE_BIN)". Both are `no-cli` results.
  - DEV ONLY: under the test runner (`VITEST` set or `NODE_ENV=test`) with no binary named, every run is refused: "no fake Claude is configured (TC_CLAUDE_BIN): tests never call the real one".
- **How a run is made**: the prompt goes on standard input; arguments `-p --model <model, default sonnet> --output-format stream-json --verbose --include-partial-messages --strict-mcp-config --max-turns N`.
  - `--max-turns` defaults to 1 with no tools, 8 with tools.
  - Tools: none unless the call names them. `Bash, Edit, Write, NotebookEdit, WebFetch, WebSearch, Task` are always disallowed unless named. Named tools are allowed with `--permission-mode acceptEdits`.
  - Environment: every `ANTHROPIC_*` and `CLAUDE_CODE_*` variable and `CLAUDECODE`, `CLAUDE_PID`, `CLAUDE_EFFORT`, `MAX_THINKING_TOKENS` removed; `CARDS_CLAUDE_OAUTH_TOKEN` is passed as `CLAUDE_CODE_OAUTH_TOKEN`, or else `CARDS_ANTHROPIC_API_KEY` as `ANTHROPIC_API_KEY`. Unless the call asks for thinking, `CLAUDE_EFFORT=low` and `MAX_THINKING_TOKENS=0` are set.
  - Working folder fixed at `<system temp>/tc-editor-claude-cwd`.
  - The reply is streamed to the caller as it is written.
- **Limits** (settings: `TC_AI_CONCURRENCY`, `TC_AI_BUDGET_USD`)
  - At most 4 runs at once (or `TC_AI_CONCURRENCY`), 32 waiting. A full queue: "Claude is busy with other requests; try again in a moment" (`busy`). A run that waited past its timeout: "<label> did not get a turn within N s because Claude was busy with other requests".
  - Default timeout 15 minutes per run: "<label> did not answer within N s, so the run was stopped".
  - Output over 16 MiB: "<label> wrote far more than an answer, so the run was stopped".
  - Cost budget (only when `TC_AI_BUDGET_USD` is set): the reported cost of runs in the last rolling hour; once reached, new runs get "the AI budget of $X for this hour is spent; try again later (TC_AI_BUDGET_USD)". Checked before queueing and again after getting a slot.
  - Ran out of turns: "<label> needed more than N turns, so the run was stopped" (N printed is the call's own turn limit or 1, even when the default with tools was 8).
  - Any other failure: "claude failed (exit N): <last lines>". A run asked for JSON that did not get it: "<label> answered, but not with the JSON it was asked for".
  - Stop: "stopped" (`cancelled`). Server stopping: "the server is shutting down" (`closed`).
  - Stopping a run kills the whole process tree on Windows (`taskkill /T /F`, at most 5 s, then a hard kill), a plain hard kill elsewhere.
- **JSON answers**: the reply (or a file the model was told to write) is parsed as one JSON object; code fences and text around the object are tolerated.
- **Conversations (sessions)**: a feature may keep one Claude conversation per scope (for example per cut list).
  - Kept as a small file in `TC_AI_SESSIONS` (default `<system temp>/tc-editor-ai-sessions`), `/<feature>/<first 24 hex of sha256 of the scope>.json`, holding the conversation id, completed turns, a corpus hash and when it was made. Never in the vault.
  - The first turn opens the conversation under that id; later turns resume it. A different corpus hash starts a new conversation. Reset deletes the file.
  - When the CLI says the id is unknown or already in use, the run fails `lost` without retrying.
- **The fake Claude** (DEV ONLY, `server/ai/fake-claude.mjs`): a stand-in CLI for tests. Reads `TC_FAKE_CLAUDE_DIR` (session store and a `calls.jsonl` record of every call) and `TC_FAKE_CLAUDE_RULES` (a JSON list of rules: prompt pattern, reply, delays, failure, exit code, lose session, cost, turns, write-to-file). Mimics the real CLI's session errors, streamed output and max-turns ending. Default reply echoes the first prompt line, prompt length and turn number. Never uses the network.

## The background work queue and daily budget (for features)
(source: server/platform/workqueue.ts)

A building block the features use for background Claude or Python work (used by the aids and montage features); described here as the rules it enforces.

- Three priorities: `now` (somebody is waiting), `visible` (on screen), `background`. Most urgent first, oldest first within a priority.
- A batch holds only units of one cut list, one priority and one group (for example one language). Defaults: 2 runs at once, 4 units per batch (at most 64; the batch size is saved), 2000 units waiting.
- When full, the lowest-priority, newest unit nobody is waiting on is dropped; a unit with a waiter is never dropped. A waiter that cannot be queued is told "too much work is queued already; try again in a moment" (`busy`).
- **Daily budget** (optional, may be shared between queues): a count of runs per calendar day (UTC date), saved to a file. When spent, the queue stands still and says "today's budget is spent (N Claude calls)"; a waiter is answered at once with that. Raising the limit restarts the queue.
- **Standing conditions**: when a run reports the worker is missing (no CLI, no language model), the queue holds, answers waiters at once, and looks again after 60 s.
- A unit missing from a batch's answer is asked once more on its own; then it fails "it was left out of the answer".
- Cancel by scope drops queued units of that scope and stops a run only that scope wanted. A waiter that leaves withdraws its wish.
- Resumable: the queue (including what was running) is written to a state file 200 ms after a change and at shutdown, and read back at start ("resumed the queue"). A unit that no longer reads is dropped. On shutdown waiters get "the server is stopping".

## Media: listing a cut list's or episode's sources
(source: server/media/service.ts, server/media/library.ts, core/src/media.ts)

- **Where audio is found** for a clip name in an episode, in order of preference:
  1. `<Episode>/Script Docs/remote_audio/<clip>.ogg` (the small Opus copy).
  2. `<Episode>/Interviewees/<person>/<clip>.wav`, only files whose name ends ` Multicam.wav` (case-insensitive); person folders starting with `.` are skipped.
  3. `<Episode>/Script Docs/remote_audio/source/<clip>.opus.m4a`, `.m4a` or `.ogg` (an extraction, used for news montages), preferring that order.
- **Name aliases**:
  - A clip name too long for a file name (over 238 UTF-8 bytes) is also found under its shortened file name: the head cut on a character boundary, `~` plus the first 8 hex of the name's SHA-1, and the `[id]` tag kept.
  - A clip named after a video file (`.mp4 .mov .mkv .webm .m4v .avi .mts .mxf`, case-insensitive) is found as the extraction with the same name minus the extension; its waveform file is `<clip>.peaks` under the full name.
- A clip is matched only against files that exist; a name never becomes a path. Episode and key paths are checked part by part (no empty, `.` or `..` parts, no `\ : * ? " < > |` or control characters, no part ending in a space or dot, at most 1024 characters) and must stay inside the vault even through links ("outside the vault", `bad-key`; a missing episode is 404 "no such episode").
- A **source id** is the first 16 hex characters of SHA-256 of `<episode>` newline `<clip>`.
- **`GET /media/sources?project=<key>`**: reads the cut list file from the VAULT (not the working copy), takes every clip name used on a cut line (in the cut and on the bench, first-use order), and answers `{project, sources, missing}`.
  - Each source: `{id, kind (ogg | wav | m4a), clip, duration_s, sampleRate, channels, hash, audioUrl, peaksUrl}`, with URLs in the `?project=&clip=` form.
  - `missing`: names with no audio, and names whose audio could not be probed (logged "media: unreadable source").
  - The key must be `<Episode>/Script Docs/Cuts/<name>.cut.md` (400 "the project key must end .cut.md" or "the project key must be <Episode>/Script Docs/Cuts/<name>.cut.md"); the file must exist (404 "no such cut list") and be at most 16 MiB (413 "the cut list is too large").
  - A cut list that exists only in the working copy (made by the editor in a read-only run) is "no such cut list" here.
- **`GET /media/sources?episode=<episode>`**: every source the episode has, `{episode, sources}`, URLs in the `/<id>` form, sorted by clip name. Unreadable sources are skipped.
- Neither: 400 "give project=<key> or episode=<episode>".
- **Facts** (duration, rate, channels) come from ffprobe (15 s timeout); the **hash** is SHA-256 of the file (first 16 hex), or for files over 64 MiB of size, modification time and the first and last MiB. Facts are remembered per file until its size or time changes (4096 files).
- **Addressing by id** (`/media/<what>/<id>`): the id must be 16 hex characters. An id never listed by this process triggers a scan of every episode in the vault (folders up to 4 deep, skipping hidden, `Script Docs`, `Interviewees`, `node_modules`), at most once every 5 s. Not found: 404 "no such source". A listed id whose file has gone is forgotten.
- **Addressing by name** (`?project=&clip=`): `project` missing: 400 "project is required"; `clip` missing or empty: 400 "clip is required"; no audio: 404 "no audio for clip \"X\" in this episode" (`no-media`).

## Media: audio, preview video, waveforms, decoded windows, loudness
(source: server/media/service.ts, server/media/range.ts, server/media/peaks.ts, server/media/wav.ts, server/media/loudness.ts, server/media/ffmpeg.ts, server/media/cache.ts)

- **`GET /media/audio?project=&clip=`** and **`GET /media/audio/<id>`**: the audio file itself, `audio/ogg`, `audio/mp4` or `audio/wav`.
  - Byte ranges: one range honoured (206 with `Content-Range`); a malformed or multi-part range is ignored (whole file, 200); a range past the end is 416 "the range is outside the file" (`bad-range`) with `bytes */<size>`.
  - `ETag` from size and modification time; `If-None-Match` gives 304; `If-Range` with another tag ignores the range. `Accept-Ranges: bytes`, `cache-control: no-cache`. HEAD gives headers only.
  - File gone between lookup and send: 404 "the audio file went away".
- **`GET /media/video?project=&clip=`**: the pipeline's small preview render `<clip> Preview.mp4`, looked for in `Interviewees/`, then each `Interviewees/<person>/`, then `Script Docs/remote_audio/`. Served like audio, `video/mp4`. A clip containing `/`, `\` or `..`: 400 "not a clip name". None: 404 "no preview video for this clip". Found paths are remembered 5 minutes, not-found 30 s (the memory is cleared at 2000 entries).
- **`GET /media/peaks?project=&clip=`** and **`/media/peaks/<id>`**: the waveform file.
  - Format: bytes `P`, `K`, 200 (bins per second), 0, then one byte per 1/200 s: the loudest absolute sample of that 5 ms of 8 kHz mono audio, scaled to 0..255. A partial last bin is dropped.
  - An existing `remote_audio/<clip>.peaks` is served when its header is valid and it is no more than 2 s older than the audio.
  - Otherwise it is made with ffmpeg (one whole-file job at a time, 10 minute timeout). In a `--write` run it is written into `remote_audio` (created if needed) through a temporary file and rename; if another writer made a current one meanwhile, that one is used ("first writer wins"); a write failure is logged "media: could not write peaks (serving them anyway)". In a read-only run it is kept in memory (at most 256 files, newest kept) and remade after a restart.
  - Several requests for the same waveform share one ffmpeg run. `ETag` and 304 supported.
- **`GET /media/pcm?project=&clip=&from=&to=&rate=`**: a window of decoded audio as raw little-endian 32-bit float mono samples.
  - `from` and `to` in source seconds, required and numeric (400 "X is required" / "X is not a number", `bad-range`); `from` at least 0 ("from must be >= 0"); `to` after `from` ("to must be after from"); at most 30 s ("a window is at most 30 s"); `rate` one of 8000, 16000, 22050, 24000, 44100, 48000 (default 48000) ("rate must be one of ...").
  - Exactly the asked number of samples (clamped to the source's end; short output padded with silence). Each decode starts 0.25 s earlier and discards that part, so the joins between windows have no crackle.
  - Headers `x-tc-rate`, `x-tc-from` (actual start), `x-tc-samples`; `cache-control: private, max-age=3600`.
- **`GET /media/pcm/<id>?from=&to=&rate=[&format=f32]`**: the same window, as a 32-bit float WAV file (`audio/wav`), or raw with `format=f32`.
- Decoded windows are cached on disk in `TC_MEDIA_CACHE` (default `<system temp>/tc-media-cache`) under `pcm/`, at most 512 MiB, least recently used dropped. Never in the vault.
- **`GET /media/loudness?project=&clip=`** and **`/media/loudness/<id>`**: `{format: 1, hash, rate: 1, s, integrated, id, clip}`.
  - `s`: one value per second, the EBU R128 short-term loudness (3 s window) in LUFS, rounded to 0.01; silence (at or below -120 LUFS) and unmeasurable values are null.
  - `integrated`: the gated level of the whole source (absolute gate -70 LUFS, then relative gate 10 LU below), null when silent.
  - Measured with ffmpeg once per audio content hash (one whole-file job at a time, 10 minute timeout) and cached in `loudness/` under the media cache (at most 64 MiB).
- **Levelling rules exported for the page and audio engine** (not used by the server itself): the level around a source second is the gated level of a 120 s window either side, centre rounded to 5 s, used only when at least 20 s were measured, clamped to within 18 dB of the whole source; a cut's gain toward a target is constant over the cut (asked at its middle) and clamped between -26 dB (0.05x) and +18 dB (8x); the target is the median of the sources' integrated levels.
- **`GET /media/status`**: `{procs, heavy, queued, pcmCacheBytes, pcmCacheFiles, inFlight}`.
- **Limits and failures for every media route**
  - At most 3 decodes and probes at once, 12 waiting; beyond that 503 "too many decodes in flight; retry shortly" (`busy`) with `Retry-After: 1`. Whole-file jobs: 1 at once, 64 waiting.
  - Timeouts: decode window 20 s, whole-file 10 minutes, probe 15 s. A timeout is 504 (`ffmpeg`); any other ffmpeg failure is 502 (`ffmpeg`) with the last stderr lines. ffprobe finding no audio stream: "ffprobe found no audio stream".
  - A request whose client hangs up gets no answer, and its ffmpeg is killed as soon as no other request is waiting for the same result.
  - `ffmpeg` and `ffprobe` are run by name from `PATH` (see `TC_TOOL_PATH`).
  - The media service writes nothing into the vault except `remote_audio/<clip>.peaks` in a `--write` run.

## Sync: the live connection a client edits through (`/sync`)
(source: server/sync/service.ts, server/sync/options.ts, core/src/protocol.ts, core/src/validate.ts)

- One WebSocket per open cut list, at path `/sync`. All messages are JSON text; a binary message closes the socket ("messages are JSON text").
- **Opening**: the first message must be `hello` `{proto, clientId, project: <key>, have: {version, hash} | null}`.
  - No hello within 10 s: closed ("no hello").
  - First message not a hello: "the first message on /sync is hello". A second hello: "one hello per connection".
  - Protocol number other than 1: "this server speaks protocol 1, not N: reload the editor".
  - A bad key: the key rule's sentence (`bad-key`).
  - **Renamed cut list**: when the key's file is gone and a rename record says where it went (see Keys), the socket follows it and the client is told (info notice) `this cut list was renamed to "<new name>" on another device; your edits go there`. Edits held offline under the old name land on the renamed list.
  - Cut list cannot be opened: `not-found` with "there is no cut list <key>", or `internal` with the open failure's sentence (locked, unreadable, broken history; see below), or "the cut list could not be opened".
  - These fatal errors are sent as an `error` message, then the socket is closed (code 1008) and cut 1 s later.
- **The answer to hello (`welcome`)**: `{proto, serverId, project, version, hash}` plus EITHER the missing edits after the client's version (when the client's version is not ahead of the server, is at most 5000 edits behind, those edits are still in memory, and the client's hash matches the server's state at that version) OR the whole cut list as a snapshot. Then any sticky notices of the last 10 minutes are re-sent. From that moment the client receives every new edit.
- **Messages a client may send after hello**
  - `op` `{env: {opId, clientId, parent, op, at}}`: one edit. Answered with `ack {opId, version}` once it is on disk, or `reject {opId, code, message, version}` when the edit does not apply (nothing changed). Re-sending the same `opId` is always safe: the original answer comes back.
  - `ping {n}`: answered `pong {n}`.
  - `resync {reason}`: the client asks for a fresh welcome (whole snapshot).
- **Messages the server sends**: `welcome`, `ack`, `reject`, `ops {entries}` (every new history entry, the client's own included, to every client of that cut list), `notice {level: info | warn | error, message, version}`, `pong`, `error {code: proto | not-found | bad-key | internal | overload, message}`.
- **Edit envelope limits**
  - Over 512 KB: `reject` code `too-large` "that edit is too large to send (over 524288 bytes)" if an `opId` can be read, else a warn notice "a message too large to read was ignored".
  - Not a recognised edit: `reject` code `invalid` "that edit is not one the editor knows how to make", or warn notice "a message I could not read was ignored".
  - `opId` 1 to 200 characters, `clientId` at most 200; `parent` a whole number (informational; the server does not use it).
- **Who an edit is attributed to**: a `clientId` starting `adapter:` is recorded as origin `adapter`, `derive:` as `derive`, anything else as `client`. The client chooses its own id; nothing checks it. Outside-file edits are recorded as `external` and cannot be claimed by a client.
- **Not saved**: when an edit could not be written to disk, the server answers nothing for it and closes the socket (code 1011, "not-saved"); the client reconnects and re-sends its pending edits in order.
- **Capacity limits**
  - 256 sockets per server: "too many editors are connected to this server" (`overload`). While stopping: "the server is shutting down".
  - 64 clients per cut list: "too many editors have this cut list open".
  - 256 unanswered edits queued per socket: "more than 256 edits waiting: slow down and reconnect".
  - A socket with more than 32 MiB waiting to be sent is cut (logged "slow client dropped"); it reconnects and catches up.
- **Heartbeat** (background, every `TC_SYNC_PING_MS`, default 15 s, never more often than every 50 ms nor less often than every 15 s): each socket is pinged; one silent (no message, no pong) for 3 intervals is cut.
- **Idle close** (same timer): a cut list with no clients and no activity for `TC_SYNC_IDLE_MS` (default 10 minutes; 0 = never) is flushed to its file and closed ("closing an idle cut list"). It reopens on next use.
- Client-side numbers the protocol also fixes (the page honours them): 64 edits in flight before waiting for acks; reconnect backoff 250 ms to 10 s, doubling, full jitter.

## Sync over plain HTTP
(source: server/sync/service.ts, server/sync/keys.ts)

- **`GET /api/projects`**: every cut list (in the working copy in a read-only run, else the vault), each `{key, title, cuts, version, modified}`, sorted by key.
  - `title`: the file's `# ` line; `cuts`: the number of cut lines before the first bench heading; `version`: the live version if the cut list is open, else the file's `rev:`; `modified`: the file's modification time.
  - Read by a quick line scan (files over 16 MiB report no title, 0 cuts, rev 0), cached per file until its size or time changes (4096 files). An unreadable file is left out.
- **`GET /api/project?key=<key>`**: `{key, version, hash, project}`: the whole cut list as the model, opening it if needed.
- **`POST /api/ops?key=<key>`**, body: one edit envelope (at most 512 KB): answers the `ack` or `reject` message (HTTP 200 for both). Not an envelope: 400 "the body is not an op envelope" (`invalid`). Could not be saved: 503 "the edit could not be saved yet; send it again" (`not-saved`).
- **`GET /api/log?key=<key>&after=<version>`**: `{entries, head}`: at most 5000 history entries after that version, from memory. `after` not a whole number: 400 "after must be a version number" (`bad-after`). No longer held: 410 "that part of the log is no longer held here; fetch the whole project" (`gone`).
- **Opening errors for the last three**: bad key 400 (`bad-key`); missing 404 (`not-found`); another server holds it 409 (`locked`); a file line that cannot be read 422 (`unreadable`); history that cannot be rebuilt 500 (`broken`).
- The HTTP routes do not follow rename records (only the socket does).

## Keys, the cut-list list and renames
(source: server/sync/keys.ts)

- **A key is refused** (`bad-key`) when it is: missing or empty ("no project key"); over 1024 characters ("the project key is too long"); contains NUL, `\`, `:`, `*`, `?`, `"`, `<`, `>`, `|` or a control character ("the project key has a character a path cannot have"); starts with `/` ("the project key must be relative to the vault"); does not end `.cut.md`, or is only `.cut.md` ("a project key names a .cut.md file"); has an empty, `.` or `..` part ("the project key has an empty, \".\" or \"..\" segment"); has a part starting with `.` ("the project key names a hidden folder or file", so the `.tcards` history folders can never be addressed); has a part with leading or trailing spaces ("a project key segment starts or ends with a space").
- The resolved file must lie inside the vault, also through symbolic links (compared case-insensitively): "the project key leaves the vault".
- **Finding cut lists**: every folder up to 4 levels below the root that has a `Script Docs` subfolder is an episode; its `Script Docs/Cuts/*.cut.md` files (not hidden ones, not ones whose name a key cannot carry) are the cut lists. Hidden folders, `Script Docs` itself and `node_modules` are not descended into. It is not a full walk of the vault.
- **Rename records**: a rename done elsewhere (the projects feature) leaves a forwarding entry in `<root>/.tcards/moves.json` (old key to new key, with a time). The newest 500 are kept; renaming back removes the forward entry. A key whose file is gone is followed through at most 16 hops to a file that exists; loops and invalid targets end the search.

## One open cut list: history, snapshots and the file on disk
(source: server/sync/store.ts, server/sync/oplog.ts, server/sync/fsx.ts, server/sync/opfilter.ts, server/sync/options.ts)

- **Files and folders a cut list gets** (beside the `.cut.md`, in `<Cuts folder>/.tcards/<name>/`):
  - `log/<12-digit version>.jsonl`: the history ("op log"), one JSON entry per line: `{version, opId, clientId, origin, op, at}`. A new segment file starts at each snapshot. A blank line is tolerated.
  - `snap/<12-digit version>.json`: snapshots `{format: 1, version, hash, project}`.
  - `head.json`: `{format, version, fileVersion, fileSha256, snapshot, serverId, writing}`: what version the file on disk was written from and its SHA-256, the newest snapshot, the history's identity, and a marker for a file write in progress.
  - `quarantine/`: damaged history and unreadable or torn copies of the file, each named with a timestamp.
  - `<name>.cut.md.bak`: the previous version of the file, replaced on each write.
  - `lock`, `lock.takeover`: the single-writer lock (next section).
  - `<name>.cut.md.tmp` beside the file during a write.
- **First open** (no history yet): the file is the whole truth. A line the reader cannot accept refuses the open: "the cut list has a line I cannot read: line N: <reason>" (`unreadable`). The version starts at the file's `rev:` (0 if absent or negative). A snapshot is taken. If any row lacked an id, the file is written back at once at the same version so the ids become permanent.
- **Every later open (recovery)**:
  - Starts from the newest snapshot that verifies (shape and hash); a failing one is skipped ("snapshot does not verify; trying an older one"). With no good snapshot, the file itself is used if it is byte-for-byte the one last written. Otherwise the open fails: "the history of this cut list (.tcards/<name>) cannot be rebuilt: no snapshot verifies and the file is not the one last written. Move that folder aside to start again from the file." (`broken`).
  - Replays the history entries after the base, in version order.
  - A last line cut off mid-write (never acknowledged) is moved to quarantine and trimmed from the log (logged only).
  - A hole in the versions, an entry that no longer applies, a bad line or a torn line in the middle: everything from there on (that segment's rest and all later segments) is moved to quarantine and deleted from the log; the cut list opens at the last good version and every client is told (sticky warning): "the op log of this cut list was damaged after version N (<reason>); everything up to version N is safe, and the rest is kept in .tcards/<name>/quarantine". Damage inside a segment that the snapshot already covers is quarantined but replay carries on.
  - If `head.json` is unreadable, the file's own `rev:` says which version it was written from.
  - A file that was being written in place when the server stopped and now holds neither the old nor the new bytes is quarantined and rewritten from the history; clients are told (sticky): "the cut list file was being written when the server stopped and holds only part of it; it was written again from the op log (nothing was lost; the partial copy is in .tcards/<name>/quarantine)".
  - A file that claims a newer version than the history can give is treated as an outside edit and merged.
  - Snapshots written before gaps became rows are migrated on read (see Legacy).
- **Applying edits** (all work on one cut list runs strictly one thing at a time):
  - Edits queued while a disk write is in progress are committed together (up to 256 per batch): applied in arrival order to the current state, written as one append, flushed to disk, and only then acknowledged and broadcast.
  - The server applies edits with no knowledge of source durations, so "no more source after this cut" is never enforced by the server (only by the page).
  - A duplicate `opId` is answered with its original acknowledgement or refusal. The last 10,000 answers are held exactly; beyond that every `opId` in the retained history is checked through a compact probabilistic index (about 1 in 10,000 false "maybe", confirmed against the log on disk).
  - A refused edit is answered `reject` and remembered (last 10,000).
  - A failed append is retried in place after 25, 100 and 400 ms. If it still fails, nothing in the batch is acknowledged, every client is told (error notice) "could not save to the op log (<reason>); your edits are kept in the editor and will be sent again", and each affected client's LATER edits are held back (not applied, not answered) until the failed one arrives again, for at most 10 minutes (at most 512 clients tracked).
  - A failed append that cannot even be undone on disk marks the log broken: no edit is saved until the cut list is reopened.
- **Snapshots** (background): after every 200 edits (`TC_SNAPSHOT_EVERY`) a snapshot is written and a new log segment started. The newest 3 snapshots are kept; log segments wholly older than the oldest kept snapshot are kept up to 100, older ones deleted.
- **Memory held per open cut list**: the last 5000 entries (at most 64 MiB) for catch-up; the states and hashes of the last 256 versions.
- **Writing the file** (background): 150 ms after the last acknowledged edit (`TC_WRITE_DEBOUNCE_MS`), and on close.
  - First looks at the file; anything changed on disk that the server did not write is merged first, never overwritten.
  - The text is rendered with `rev:` set to the version and `written:` set to `YYYY-MM-DDTHH:MM:SS+0000 by Timeline Cards` (UTC), with every row's id line present.
  - Written to `<name>.cut.md.tmp`, flushed, the old file copied to `.bak`, then renamed over the file. Just before the copy and just before the rename the server checks again that the file on disk is still the one it last wrote; if not, the write is abandoned and the outside edit merged first ("the file changed while it was being written; merging that first").
  - On sharing errors (EPERM, EBUSY, EACCES; a Windows reader holding the file) the rename is retried after 10, 20, 30 and 40 ms, then the file is overwritten in place.
  - A failed write: clients are told once (warning) "could not write the .cut.md (<reason>); every edit is safe in the op log and the write will be tried again"; retried after 0.5, 1, 2, 4 ... s, at most 30 s apart.
  - File deleted while open: rewritten from history; info notice "the cut list file had gone, so it was written again; nothing was lost".
- **Notices marked sticky** are kept 10 minutes (at most 20) and shown to every client that joins in that time.
- **Closing** (idle, or server stop): stops timers and watchers, merges and writes the file a last time (failure logged "final write of the cut list failed; the op log has every edit"), closes the log, releases the lock.

## One writer per cut list (the lock)
(source: server/sync/lock.ts, server/sync/options.ts)

- Opening a cut list creates `.tcards/<name>/lock` exclusively, holding `{pid, host, startedAt, beat, nonce, beatMs}`. The holder rewrites `beat` every 10 s.
- **When an existing lock may be taken over**
  - Holder on this machine: its process no longer exists, or its beat is 30 s or more old.
  - Holder on another machine: beat within 30 s of this machine's clock: held. Beat more than 1 hour off either way: dead. Otherwise the lock file is watched for twice the holder's beat interval (at most 30 s); any change means it is alive.
  - An unreadable (empty or torn) lock is watched for 2 s; if it does not change it counts as a crash and is taken over.
- Takeover is serialised by `lock.takeover` (created exclusively; one left by a crash is deleted once older than 30 s). Under it the lock is re-read and must be unchanged, then replaced and read back.
- **Refusals** (the open fails `locked`): "another Timeline Cards server (pid N on HOST) has this cut list open"; "another server opened this cut list at the same moment"; "another server is taking this cut list over at the same moment"; "another server took this cut list over at the same moment".
- **Lost lock**: before each beat the holder checks the lock is still its own. If another server took it over, this server stops saving (edits stay pending on the clients), logs an error and tells every client (sticky error): "another Timeline Cards server took this cut list over; this one has stopped saving edits (they stay pending in the editor). Reload to connect to the server that has it now".
- On close the lock file is deleted only if it is still this server's.

## Outside edits to the file (Obsidian, a text editor)
(source: server/sync/store.ts, server/sync/index.ts, cutmd/src/diff.ts, cutmd/src/hash.ts)

- **When the server looks** (background): every 2 s (`TC_POLL_MS`; 0 = only the watcher), 50 ms after the operating system reports a change to the file (folder watcher; if watching fails, polling alone continues), when the cut list opens, and before every file write.
- A file whose size and time are unchanged is skipped; one whose bytes (compared by SHA-256 of the exact bytes) are what the server last wrote is skipped.
- **A file that does not read**: given two more looks (the person may still be typing); on the third it is copied to `.tcards/<name>/quarantine/<timestamp>.cut.md` and clients are told (warning): "the file has a line I cannot read: line N: <reason>. A copy is kept in .tcards/<name>/quarantine/<file>; the editor's version stands and is written back on the next edit".
- **A file that reads**: compared with the state it was last written from (or the current state, logged, when that is not held), turned into edits, applied on top of the current state, then the file is rewritten from the result (keeping the person's formatting where possible).
  - Edit ids are `ext:<file version>:<first 16 hex of the file's hash>:<n>` with client `external:obsidian`, so the same file after a crash gives the same edits and they cannot apply twice.
  - Rows are matched by id. A row whose id line was deleted is matched back: cuts by clip and span in three passes (exact span, one span inside the other, overlapping), ties to the nearest in order then the earliest; headings, note rows, bench sections and gaps by kind and words (gaps by length), nearest in order. Only then is a row new.
  - The edits produced, in order: a title / clip-facts / timeline / conform-stamp change (`setMeta`); one rearrangement (`restore`: new cuts, new or changed headings, note rows and bench sections, a hand-fixed clip name, speaker or link, removed headings and sections, and the file's order merged three ways so that only what the file moved moves); a `delete` for cuts whose bullets left the cut (so they go to a shelf, never lost); then per cut its edges, fades, gain, colour, note and highlights; per gap its length and note; per heading its summary.
  - A cut removed from the bench in the file is really removed.
  - Edits to a cut's words, its `(12.4s)` duration and its `[[transcript]]` link text are ignored and written back as they were.
  - A cut whose new span cannot be reached edge by edge is replaced whole.
  - Frontmatter fields with no edit (`project`, `vault_root`, `canvas`, `fps`, `drop`, `tl_start`, `timing`) are kept as they were, with a warning "the frontmatter's X was edited; no edit can change it, so it is kept as it was".
- **What clients are told**: "merged an edit made to the file outside the editor (N change(s))" (N counts produced edits, the rearrangement as one); or, when nothing in the file changes the cut, "the file was edited outside the editor, but nothing in the edit changes the cut (the words are written from the transcript), so it was written back as it was"; for edits that no longer apply, "K of the file's changes no longer apply and were skipped: <up to 5 reasons>"; plus up to 5 merge warnings joined.
- An edit set that could not be saved is retried at the next look.

## The sync protocol's shape checks
(source: core/src/validate.ts, core/src/protocol.ts)

- Every message off the wire is checked for shape before anything acts on it: JSON types, required fields, and that an edit's type is in the catalogue (or a registered feature edit that passes its own check). Malformed input is ignored or refused, never thrown on. Messages over 8 MiB are not parsed.
- Id lists in an edit hold 1 to 100,000 strings; batches nest at most 32 deep.
- A `welcome` must carry exactly one of history entries or a snapshot.
- The full list of refusal codes a `reject` may carry: `not-found`, `bad-op`, `bad-value`, `too-short`, `whole-cut`, `edge-of-cut`, `no-source-before`, `no-source-after`, `question`, `not-contiguous`, `in-cut`, `not-staged`, `exists`, `inside-itself`, `conflict`, `noop`, `stale`, `too-large`, `invalid`. (`noop` and `stale` are never produced: UNREACHABLE.)

## The cut-list model: what a cut list can hold
(source: core/src/model.ts, core/src/derive.ts, core/src/hash.ts)

- **Times are seconds**, plain numbers, never frames. Source spans hold the value as written in the file; every edit rounds what it writes to 6 decimal places. Frames appear only in exporters (other sections). Seconds above 1,000,000,000 in either direction are refused ("X is past 1 000 000 000 seconds -- no clip is that long").
- **A cut list** has: frontmatter facts (`meta`), an optional title, the cut's rows in order, the bench sections in order, and optional feature data (`ext`, one value per feature).
- **Row kinds in the cut**: cut, gap, heading, note row.
- **A cut** (one piece of a source):
  - id: `c` + 7 characters from `0-9a-z`.
  - clip: the source's name exactly as between the backticks in the file. It is the source's identity (never a Resolve media-pool id).
  - person: the speaker, or none (a montage clip).
  - in and out: source seconds, in before out always.
  - fade in, fade out: seconds, each clamped to the cut's length (they may overlap).
  - gain: manual dB, rounded to 0.1, clamped to plus or minus 30, on top of automatic levelling.
  - colour: a Resolve clip colour name, or none (the speaker's colour).
  - ref: the transcript block reference (`^ref`, or a full `doc#^ref` target), or none.
  - text: the words (derived decoration, refreshed by the transcript service; never sliced by an edit).
  - highlights: the highlighted substrings of the words, in order; an entry may name which occurrence of a repeated phrase it is.
  - note: free text, possibly several lines.
  - question: "the interviewer asked this". Not stored in the file. A question can never be in the cut (house rule: "no questions included in the edit ever"); it may sit on the bench.
- **A gap** (black and silence on the timeline): id `g` + 7 characters; length in seconds (more than 0, rounded to 6 places); an optional note. A gap is its own row: it stays where it was put when a neighbour moves or is deleted, and is selected, moved, resized, deleted and copied like a cut.
- **A heading** in the cut: id `s` + 7 characters; kind `section` (default colour Blue), `note` (default colour Green) or `plain` (no default colour); title; marker colour; optional AI summary of its section and an optional short hash of the words the summary was written from (so a changed section can read "out of date").
- **A note row**: id `n` + 7 characters; kind `note` (a direction card) or `unmatched`; one line of text (may be empty).
- **Bench sections** (always after the cut's rows):
  - `staged`: a shelf. Its name is the category; the empty name is the plain shelf. Holds cuts, note rows and gaps.
  - `sequence`: a saved run, kept whole with its gaps and note rows.
  - `alt`: the legacy alternates bench, read and written as is.
  - Each has an id (`s` + 7), name, exact title as read, colour, items.
- **Frontmatter facts**: `rev` (the version the file encodes), `written`, `project`, `vault_root`, `canvas`, `timeline`, `conformed`, `updated_from_timeline`, `fps` (timeline rate; default 30000/1001), `drop` (drop-frame; default true for a new list), `tl_start` (default `01:00:00:00`), `timing` (`word` or `srt`), and `clips`: per clip name `{fps, start_tc, uid}` (hints for exporters only).
- **A new, empty cut list**: rev 0, title as given, 29.97 drop-frame, start `01:00:00:00`, word timing, no rows.
- **Fixed values**
  - Clip colours (16): Orange, Apricot, Yellow, Lime, Olive, Green, Teal, Navy, Blue, Purple, Violet, Pink, Tan, Beige, Chocolate, Brown. Brown is never written: it is turned into Chocolate.
  - Marker colours (16): Blue, Cyan, Green, Yellow, Red, Pink, Purple, Fuchsia, Rose, Lavender, Sky, Mint, Lemon, Sand, Cocoa, Cream.
  - New-section colour rotation: Blue, Sand, Purple, Mint, Rose, Sky, Lemon, Fuchsia, Cyan, Cocoa, Lavender, Yellow, Pink, Cream.
  - Shortest cut an edit may leave: 1/24 s. Shortest gap an edit may leave: 1/24 s. (A file may hold a shorter cut, for example one 29.97 frame.)
  - Category and sequence names: at most 60 characters. Gap notes: at most 2000 characters. Summaries: at most 4000 characters. Summary hashes: 1 to 32 characters of `0-9a-z`.
- **Derived views** (computed, never stored):
  - The timeline: every cut and gap of the cut in order; each item's start is the sum of the lengths before it (so every trim ripples by construction); each item knows the heading it sits under; total duration.
  - Find the item at a time, find a cut or gap anywhere, where a cut is (in the cut or on the bench), every cut, every item, every note row.
- **The project hash** (replica check): SHA-256 of the canonical JSON (keys sorted, no whitespace, no undefined values, `question` left out unless true). Same answer on the server and in the browser.

## Ids
(source: core/src/ids.ts, cutmd/src/ids.ts)

- Every cut, gap, heading, note row and bench section has an id that is written into the file and never matched back by name, time or position.
- Ids for rows the page creates are random (crypto-random where available) and travel inside the edit, so every replica makes the same ids.
- Ids for rows that arrive without one (an old file, a bullet typed by hand, a shelf a delete makes) are deterministic: the kind letter plus the last 7 base-36 characters of a 64-bit FNV-1a hash of the kind, the row's content (cut: clip, in and out to 6 places; gap: length; heading or bench section: kind and title; note row: kind and text) and an occurrence counter, counted up until unused. The same bytes always get the same ids.

## The edit catalogue: every edit there is and its rules
(source: core/src/ops.ts, core/src/reduce.ts, core/src/guard.ts, core/src/index.ts)

General rules for every edit:

- Addressed by id, never by position or name-and-time (bench categories and sequences are addressed by name).
- Absolute where possible (set an edge to X, set gain to Y), so applying it twice changes nothing more.
- A refused edit changes nothing and carries a code and the sentence the editor shows.
- After every edit the result is checked against the cut list's invariants; an edit that would ADD a problem the cut list did not already have is refused ("internal: that edit would break the cut list (...)", or the question sentence). A cut list read with an oddity of its own can still be edited.
- Any unexpected failure inside an edit becomes a `bad-op` refusal "internal: ...".
- Common refusals: an id list empty or not a list ("name at least one of the cuts"), not strings ("cuts are named by id"), or with a repeat ("the same cut is named twice (<id>)"); a place with both before and after ("a place is before a cut OR after one, not both"); a number that is not a number ("X must be a number of seconds"); a cut that is gone ("that cut is no longer in the cut list"); a gap that is gone ("that gap is no longer in the cut list").
- **Places** (where a moved or inserted block lands): "before item X" lands between the rows above X and X, so the block joins X's section (headings above X stay above the block); "after item X" lands directly after X; neither means the end of the cut. The anchor must be a cut or gap in the cut.
- **Shelf places**: a category (made on demand; empty is the plain shelf), or before / after a staged item (the anchor's shelf wins over the category; an anchor next to itself is refused "a cut cannot be put next to itself"; an anchor not on the bench is "that staged cut is no longer in the file"; an anchor in an alternates section is ignored and the category is used).

### Span edits
- **setEdge** (trim or extend one edge, absolute): moves a cut's in or out point to a source second; everything after ripples.
  - In point below 0: "the clip starts N s later than that -- there is no more source before this cut" (`no-source-before`).
  - Out point past a known source length (only where lengths are known, i.e. on the page): "the clip runs out N s before that -- there is no more source after this cut" (`no-source-after`).
  - A result of 0 or less, or shorter than 1/24 s AND shorter than before: "that would leave nothing of the cut -- delete it instead" (`too-short`). A cut already shorter than 1/24 s may still be lengthened or set unchanged.
  - Fades are shortened to fit the new length.
  - Pulling an edge out over a neighbouring cut of the same source is allowed (that source then plays twice).
  - Works on a cut in the cut or on the bench.
- **removeRange** (take a stretch out of the middle): the cut keeps [in, from); a new cut with the given new id gets [to, out) and is placed right after it. The range is clamped to the cut.
  - Range under 1/24 s: "the selection is empty -- nothing removed" (`bad-value`).
  - Whole cut: "that is the whole cut -- delete it instead" (`whole-cut`).
  - Touching an edge (leaving a sliver under 1/24 s on one side): "that would leave a piece shorter than a frame -- trim the edge instead" (`too-short`).
  - New id malformed: "the second piece needs a well-formed id" (`bad-op`); already used: "that id is already in use in this cut list" (`exists`).
  - First piece keeps id and fade in (fade out cleared); second piece takes the fade out (fade in cleared); both keep gain, colour, note, ref, words and highlights.
- **split** (blade at a source second): same pieces as removeRange with no gap between. Within 1/24 s of either edge: "the blade is at the edge of the cut -- nothing to split" (`edge-of-cut`).

### Structure edits
- **move**: a block of named cuts and gaps (in the given order) to a place. A gap moves only when named. Next to itself: "a block cannot be put next to itself". Only items in the cut can be moved.
- **delete**: each named cut leaves the cut and goes onto the shelf named after the last `§` section heading above it (a `◆` or plain heading does not count); before the first section, or when the title cannot be a category name, to the plain shelf. Shelves are made on demand at the end of the bench with an id derived from the category. A named gap is simply removed. Nothing is lost by a delete.
- **stage**: named cuts out of the cut onto a shelf place; named gaps are removed.
- **unstage**: named cuts from any bench section (shelf, sequence, alternates) back into the cut at a place. A cut already in the cut: "that cut is already in the cut" (`not-staged`). Not found: "that staged cut is no longer in the file". A question: "that is an interviewer question -- questions never go in the cut" (`question`).
- **moveStaged**: staged cuts within or between shelves. A cut in the cut: "that cut is in the cut -- stage it first" (`in-cut`). Anchored next to a cut in the cut: "a staged cut moves next to another staged cut". With an anchor, the anchor's section decides, whatever kind it is; with a category, cuts already in that category stay where they are and the rest go to its end.
- **discard**: permanently removes cuts that are on the bench (the only true delete). A cut in the cut: "that cut is in the cut -- only a cut on the bench can be thrown away" (`in-cut`).
- **insert**: a new cut (id chosen by the sender) at a place, or straight onto a shelf place. Must be at least 1/24 s long (`too-short`); id unused (`exists`); a question cannot go into the cut (allowed onto a shelf); past a known source length refused. All the new-cut rules below apply.
- **insertRun** (paste): a run of new cuts and gaps, whole, in its own order, at a place. Empty: "nothing to paste - copy some cuts first". Any id used, or repeated in the run: `exists`. Any question: refused. Pasted gaps bring their notes.
- **insertGap**: a new gap of at least 1/24 s ("a gap shorter than a frame is no gap -- delete it instead", `too-short`) at a place. Malformed id: "a new gap needs an id like g1a2b3c4".
- **New-cut rules** (insert, paste, and field fixes): id like `c1a2b3c4` ("a new cut needs an id like c1a2b3c4"); a clip name that is not empty, has no backtick or line break ("a cut needs the name of its clip"), no leading or trailing space ("a clip name cannot start or end with a space"), no `<!--` or `-->` ("a clip name cannot contain a comment"); in point not below 0; in before out ("a cut ends after it starts"); fades not negative ("a fade cannot be negative"); gain rounded and clamped; a hand-written colour kept as given (Brown becomes Chocolate; empty means none; no comment or line break: "a colour cannot contain a comment"); speaker one plain line without `**`, backtick or comment ("a speaker name is one line of plain text (no line break, ** or `)"), trimmed, empty means none; ref one line with no `[[` or `]]` ("a transcript ref is one line with no [[ or ]]"); note lines trimmed, blank lines at the ends dropped; highlights kept only where their words are in the text (a partly matching one keeps the whole words that match); fades clamped to the length.

### Property edits (all absolute)
- **setGap**: a gap's length; at least 1/24 s (`too-short`). Works on a gap in the cut or in a saved sequence. A legacy form (`cut`, `seconds`, optional `from`: "the black directly before this cut is N seconds", 0 removes it, `from` clears the black before another cut) is still accepted so old histories replay; nothing creates it any more.
- **setFades**: either or both fades; a missing end is left alone; negative refused; clamped to the cut's length.
- **setGain**: the same gain on each named cut, rounded to 0.1 dB (Python rounding: halves to even on the exact binary value), clamped to plus or minus 30. Works on bench cuts too.
- **setColour**: a clip colour from the 16 names, or none (back to the speaker's): "\"X\" is not a clip colour". Brown is written Chocolate.
- **setNote**: a cut's note; empty or whitespace removes it; each line trimmed, blank lines at the ends dropped.
- **setHighlights**: a cut's highlights; entries not found in its words are dropped (partly matching ones trimmed to the matching whole words).
- **setText**: a cut's words, highlights and optionally ref (sent by the transcript service after a span edit; never changes a span). With "refit", the cut's CURRENT highlights are carried onto the new words (using the given position shift when the texts agree there), so a highlight made since is not wiped.
- **setGapNote**: a gap's note, in the cut or a saved sequence; empty removes it; each line trimmed, control characters become spaces, broken surrogate characters become U+FFFD, blank end lines dropped; over 2000 characters: "a gap note is at most 2000 characters" (`bad-value`). Same note again: no change.
- **setSummary**: a heading's AI summary and the hash it was written from (`0-9a-z`, 1 to 32: "what a summary was written from is a short hash"); empty removes both; over 4000 characters refused; only a heading: "only a heading carries a summary"; gone: "that section is no longer in this cut list".

### Markers: headings and note rows in the cut
- **addMarker**: a new heading (section, note or plain) or note row, in front of a given cut or gap, or at the end.
  - Title: one line (whitespace runs become single spaces), no comment ("a marker cannot contain a comment"); an empty heading title becomes "Section"; an empty note row is allowed.
  - A plain heading's title may not start with "Alternates", "staged" (any case), `§`, `◆` or `⧉`: "a plain heading cannot start with \"Alternates\", \"staged\", §, ◆ or ⧉: the cut list reads those as a shelf or another kind of heading; make it a section instead".
  - Colour: a marker colour ("\"X\" is not a marker colour"), or none: a new section takes the next colour in the rotation after the section above it (Blue when there is none, or when that section's colour is not in the rotation); a note heading Green; a plain heading none.
  - Ids: heading `s...`, note row `n...`, unused.
- **updateMarker**: rename, recolour or change kind in place. A colour change never changes the kind. Setting colour to none gives the kind's default. A section or note heading always keeps a colour. An empty new title keeps the old one. Note rows only take a new text. A cut or gap id: "that is a cut, not a marker" / "that is a gap, not a marker"; missing: "that marker is not in this cut list".
- **moveMarker**: one heading or note row in front of a given item (or to the end). Cuts and gaps do not move.
- **removeMarker**: removes one heading or note row; the rows under it stay.
- **moveSection**: a whole section (the heading and every row up to the next heading) in front of another heading or to the end. Into itself: "a section cannot be moved inside itself" (`inside-itself`). Only headings: "only a section heading can be moved that way".

### The bench: categories and sequences
- **addCategory**: a new empty shelf `staged <category>`. Name cleaned (one line, leading separator characters such as spaces, colon, slash, bar, dashes and middle dot removed, no comment or leading `#`: "a category name cannot contain a comment or a #"; over 60 characters: "a category name is a heading, not a paragraph"). Empty: "a category needs a name". Exists: "that category already exists".
- **removeCategory**: the shelf goes; its items move to the plain shelf (made if needed), never deleted. Missing: "no category called \"X\""; empty name: "which category? none was named".
- **renameCategory**: same name rules; taken: "there is already a category called \"X\"". Same name: no change.
- **saveSequence**: the stretch of the cut from the first named item to the last becomes a saved sequence `⧉ <name>`, taken out of the cut. Every cut in the stretch must be named ("a sequence is a run of cuts next to each other - select one unbroken stretch", `not-contiguous`); gaps and note rows inside the stretch travel with it; headings inside it stay in the cut; at least one cut ("a sequence needs at least one cut"); a gap just before the first cut goes only if named. Name rules as categories; taken: "there is already a sequence called \"X\"".
- **restoreSequence**: the sequence back into the cut, whole (gaps and note rows as saved), at a place; the sequence section is removed. No cuts in it: "the sequence \"X\" has no cuts in it". Any question in it: refused. Missing: "no saved sequence called \"X\"".
- **renameSequence**, **deleteSequence** (removes the sequence and everything in it).

### Frontmatter, batches, undo
- **setMeta**: title, timeline, conformed, updated_from_timeline (each text or none, one line: "X is one line"), and per-clip facts (set or remove).
  - A title is trimmed; blank becomes none.
  - Clip names: not blank, no outer spaces, no `:` or line break ("\"X\" cannot be a clip name in the frontmatter").
  - Rate: a positive number stored as the file would give it back (within 0.01 of 23.976, 29.97, 59.94 or 47.952 it IS that rate; else the nearest fraction with denominator up to 1001); 0 allowed; a rate the file would turn into 0 or cannot write: refused.
  - Start timecode and uid: one plain word with no `, { } " ' \` or line break ("a start timecode is one plain word, like 01:00:00:00"; "a uid is one plain word, or null"). An empty start timecode becomes `00:00:00:00`; an empty uid none.
- **batch**: several edits applied as one, all or none. Nested batches are flattened (at most 32 deep: "batches nested too deep"). Empty: "an empty batch".
- **restore**: the exact inverse of any edit (undo and redo), and the vehicle for outside-file merges and imports. It can: put cuts back field for field (re-creating removed ones), drop cuts, put headings, note rows, gaps and bench sections back or remove them, patch a cut's clip, speaker, question flag or ref only, put the frontmatter back, put feature data back, and put the whole arrangement back.
  - **Preconditions** (on undo): the restore carries hashes of the rows it touches (a cut's words, highlights and ref are not compared, since the transcript service rewrites them) and optionally the arrangement. If any touched row changed since: "cannot undo: that part of the cut list was changed since by another edit" (`conflict`). If rows both sides still have were reordered: "cannot undo: the order of the cut list was changed since by another edit" (`conflict`). Rows added or discarded by someone else do not block it.
  - **Highlights made since are kept**: when a restored cut's highlights changed since the undone edit, the current highlights are carried onto the restored words (each grown by an overlapping restored highlight); a highlight removed since stays removed. Highlights made since on a piece the undo drops are carried onto the restored cut of the same clip whose span and words cover them.
  - **Notes kept**: a heading's summary or a gap's note that the restore did not mean to change keeps its current value.
  - **Three-way arrangement**: when the restore says which arrangement it was made from, only rows the edit moved (or added) are placed as it says; every other row keeps its current place, so a move made since is not undone. Rows added by someone else since stay after the row they followed.
  - A re-created cut with nowhere to go: "cannot undo: that cut is no longer in the cut list". A row placed twice: "restore: X is placed twice". Malformed parts: "restore: ..." (`bad-op`).
- The inverse of `setMeta` is a `setMeta` of the old values; a feature edit may provide its own inverse; every other inverse is a computed `restore`.
- **Rebase**: a client's pending edits are re-applied in order on each newer server state; any that no longer apply are dropped with their refusal sentence. The server applies incoming edits the same way, on its current state.
- `noop` exists as a refusal code but no edit ever raises it (an edit with no effect simply changes nothing): UNREACHABLE.

## Invariants every edit must leave standing
(source: core/src/check.ts)

- Every id unique across the whole cut list and well formed for its kind.
- Cuts: a clip name; in, out, fades and gain finite; in before out; fades between 0 and the length; gain within plus or minus 30; highlights a list of text; no `-0` gain; no legacy gap field on a cut.
- No question in the cut.
- Gaps: positive length rounded to 6 places; a note exactly as the file would give it back and within 2000 characters.
- Headings: kind section, note or plain; a title; section and note headings have a colour; a summary as the file would give it back and within 4000 characters; a summary hash only with a summary and only `0-9a-z` up to 32.
- Note rows: kind note or unmatched; text.
- Bench: no two shelves with the same category, no two sequences with the same name, only known kinds and item kinds.

## Feature edits and feature data
(source: core/src/opreg.ts)

- A feature may register extra edit types, named `<feature>.<name>`, each with a shape check, an apply rule, and optionally its own inverse, a rule for applying it to a newer state (returning nothing means "that X no longer applies", `not-found`) and a short description for sentences. They travel through sync, history, undo and replay like any other edit. An unregistered type: "that is not an edit this editor knows". A malformed one: "that <description> edit is malformed". Registering a different edit under a taken type is an error.
- **Feature data**: one JSON value per feature kept in the cut list (written in the frontmatter, see the file format). Setting it is refused (`bad-value`) when the value does not survive JSON exactly (undefined, non-finite numbers, non-plain objects, a value containing itself), when the feature's own data rule rejects it ("that is not valid X data"), or when it is over 64 KB as canonical JSON ("the X data is larger than a cut list keeps (64 KB)"). Setting none removes it. Setting the same value again: no change.

## Legacy gaps
(source: core/src/legacy.ts, core/src/reduce.ts)

- Cut lists, snapshots, saved client copies and pending edits made before gaps became rows carried "black before this cut" as a field on the cut. Any such field is turned into a gap row directly in front of its cut, with an id derived from the cut's id, so every replica migrates alike. A zero or negative value is dropped. Applied when reading a snapshot, and when an insert, paste or restore carries the old field.

## Text rules shared by the model and the file
(source: core/src/text.ts)

- Whitespace and line breaks follow Python's definitions (the file format was defined by a Python reader that is still used).
- Cut notes: each line trimmed, blank lines at the ends dropped, blank lines inside kept.
- Gap notes and summaries: as cut notes, plus control characters become spaces and broken surrogate characters become U+FFFD.
- **Highlight placement**: each highlight lands on the first free occurrence at or after the previous one, else the first free one anywhere; one that is no longer in the words is dropped. When that rule would land on the wrong copy of a repeated phrase, the entry carries which occurrence it is, using the invisible separator U+2063 around the number; the file itself only ever holds `==...==` in the right place.
- **Fitting a highlight onto changed words**: an exact match is kept; otherwise the longest common run of letters and digits (case-folded) is found and cut back to the whole words it fully covers (CJK characters count as words each); under 2 matching letters is no match; texts whose product of lengths exceeds 4,000,000 are not fitted.

## Language detection (shared helpers)
(source: core/src/lang.ts)

- Detects a stretch of speech's language by script: the script with the most letters wins. Han plus kana: Japanese when kana is at least 10 percent, else Traditional Chinese when more traditional-only common characters than simplified-only, else Chinese. Hangul: Korean. Cyrillic: Ukrainian or Russian by letters only one of them writes; with neither, Russian when there are at least 200 Cyrillic letters, else "Russian or Ukrainian". No such script: English when plainly English (at least one and at least 20 percent common English words, accented letters only in capitalised Latin names, at most a third of the words), else unknown.
- Which lines of a cut are the original language: with any non-Latin script present, a line is original when its share of non-Latin characters is at least half the most original line's share; otherwise a line that has letters and is not plainly English.
- Labels: names (Mandarin, Russian, Ukrainian, "Russian or Ukrainian", Japanese, Korean, English) and switcher labels (中文, RU, UK, RU/UK, 日本語, 한국어, EN, or "Original"); a mix of Russian and Ukrainian says RU/UK; three or more languages say "Original". `lang` attributes write "Russian or Ukrainian" as `ru`.
- These are used by the page and features, not by the server itself.

## Turning a changed cut list into edits (for imports)
(source: core/src/diff.ts)

- A second implementation of "the edits that turn cut list A into cut list B", used by the Resolve import feature (not by the server's outside-edit merge, which uses the file format's own version below).
- Rows matched by id; cuts that lost their id matched by clip and span in three passes; headings, note rows and gaps by kind and words or length; bench sections by kind and name.
- Field changes on matched cuts become absolute field edits (edges ordered so the span never empties, fades, gain, colour, note, highlights), unless the clip, speaker, question flag changed, the colour is not a known clip colour, or the new span is under 1/24 s or before 0, in which case the cut travels whole in one restore with its old words and link kept and only highlights still found in the old words.
- Everything else (order, new and removed rows, headings, bench, frontmatter fields with no edit of their own, feature data) is one restore; gap notes and summaries edited alone become their own field edits.

## The .cut.md file: overall shape
(source: cutmd/src/parse.ts, cutmd/src/lines.ts, cutmd/src/render.ts, cutmd/src/layout.ts, cutmd/src/grammar.ts, cutmd/src/types.ts, cutmd/src/index.ts)

- A UTF-8 Markdown file at `<Episode>/Script Docs/Cuts/<name>.cut.md`, meant to be readable and editable in Obsidian and readable by the old Python pipeline (`cutlist.py`), which still reads these files.
- In order: the frontmatter block; a comment preamble; an optional `# Title`; the cut's rows (headings, cut bullets, gap bullets, note bullets) in order; then the bench sections, each a `##` heading followed by its items.
- Line endings `\r\n`, `\r` and `\n` are all read. The writer keeps the file's dominant ending.
- Blank lines anywhere in the body are ignored on read. The canonical writer puts one blank line between blocks and ends the file with exactly one newline.
- Reading never fails: a line the old Python reader would refuse is recorded as a **problem** (1-based line number and that reader's sentence) and kept as an opaque line that is written back as it was. The server refuses to open a never-opened file with a problem, and quarantines an outside edit with one (see Sync). Non-fatal oddities are **warnings**.
- A strict reading mode that stops at the first problem exists for tools (`parseStrict`); the server does not use it.

## The frontmatter
(source: cutmd/src/parse.ts, cutmd/src/lines.ts, cutmd/src/py.ts, cutmd/src/ext.ts)

- **Must** start on line 1 with `---` and end with a line `---`. Otherwise problems: line 1 "a cut list starts with a --- frontmatter block"; "the frontmatter is never closed".
- **Written by the writer, in this order** (canonical form):
  - `---`
  - `kind: timeline-cards/cut-list`
  - `rev: <whole number>`: the version the file encodes.
  - `written: <stamp>`: `YYYY-MM-DDTHH:MM:SS+0000 by Timeline Cards` when the server writes.
  - `project: <text>`, `vault_root: <text>`, `canvas: <text>`, `timeline: <text>`: written even when empty (as `key:` with nothing after).
  - `conformed: <text>` and `updated_from_timeline: <text>`: only when set.
  - `fps: <rate>`: `25.0` for a whole rate, else up to 8 decimal places with trailing zeros removed (`29.97002997`).
  - `drop: true` or `drop: false`.
  - `tl_start: <timecode>`
  - `timing: word` or `timing: srt`
  - `x-<feature>: "<json>"` lines (feature data), sorted by feature name.
  - `clips:` then one indented line per clip, sorted by Unicode code point: `  <name>:<padding> {fps: <rate>, start_tc: <timecode>, uid: <uid>}` (padding aligns the braces one column past the longest name; `uid` left out when none).
  - `---`
- **Value quoting** (writer): none is written as nothing; an empty string as `""`; a value is double-quoted (with `\` and `"` escaped) when it has leading or trailing whitespace, starts with a double quote, single quote, `[`, `{`, `>`, `|`, `&`, `*`, `#`, `!`, `%`, `@`, a backtick, `-` or `?`, contains `:` or `#`, or looks like a number; otherwise bare.
- **Reading values**: empty is none; a value in matching single or double quotes is the inside with `\"` and `\\` unescaped; bare `true` / `false` are booleans (written back as `true` / `false`); anything else verbatim.
- **Reading rules per key**
  - `kind`: if present and not `timeline-cards/cut-list`: problem "this is a 'X' file, not timeline-cards/cut-list".
  - `rev`: a whole number (Unicode digits, `_` separators and a sign accepted), else problem "rev is not a whole number: 'X'". Absent: 0.
  - `fps`: a number (Python's number syntax including `inf`/`nan`), else problem "fps is not a number: 'X'". Snapped to the exact rate (within 0.01 of 23.976, 29.97, 47.952 or 59.94 it IS that rate; else the nearest fraction with denominator at most 1001). Absent: 30000/1001.
  - `drop`: true when `true` or any non-empty text (even `0`); false when `false` or empty.
  - `tl_start`: absent means `01:00:00:00`.
  - `timing`: `word` or `srt`; anything else is a problem ("timing is 'word' or 'srt', not 'X'"); absent means `word`.
  - `conformed`, `updated_from_timeline`: empty means none.
  - The same key twice: the last one counts; the earlier lines are kept as written.
  - A line with no `:`: problem "'X' is not a frontmatter key".
  - An unknown key: warning "unknown frontmatter key 'X' kept as written"; kept on write.
  - Blank lines are allowed.
- **Clip lines** (indented, after `clips:`):
  - Need a `:` (problem "'X' is not a clip entry") and a `{...}` value (problem "a clip needs {fps: .., start_tc: ..}, got 'X'").
  - Inside the braces, `name: value` pairs separated by commas; values may be quoted.
  - `fps` required (problem "this clip has no fps") and numeric (problem "this clip's fps is not a number"); snapped like the timeline rate.
  - `start_tc` absent or empty: `00:00:00:00`. `uid` absent or empty: none.
  - A clip line with a problem is left out of the model and kept as written.
- **Feature data lines**: `x-<feature>: "<json>"`, where the feature name is a lower-case letter then up to 40 lower-case letters, digits or hyphens.
  - The value is the canonical JSON of the data (keys sorted, no whitespace), double-quoted with `\` and `"` escaped; CJK and Cyrillic written as they are.
  - A bare value is also read (`x-flag: true`, `x-n: 3`).
  - A value that does not decode, or decodes to null: warning "line N: the X data on this line cannot be read; it is left out"; it is not in the model and disappears on the next write.
  - Wherever they were placed by hand, they are written back as one sorted group just before `clips:` (or at the end of the frontmatter when there is no `clips:` line).
  - The old Python reader ignores these keys.

## The comment preamble
(source: cutmd/src/grammar.ts, cutmd/src/lines.ts)

- Every file the writer makes carries, after the frontmatter, a 7-line HTML comment starting "<!-- Timeline Cards owns this file while the draft is open, and the writer is" that tells a person editing by hand: the words, the `(12.4s)` and the `[[transcript#^ref]]` link are rewritten on every save; spans, bullet order, notes and colours are data and are kept; deleting a bullet removes that cut, pasting one back returns it.
- When `timing: srt`, a second 4-line comment follows, starting "<!-- timing: the text was matched from .srt cues, so a span can carry a", explaining that spans are exact but the words may include a neighbouring sentence.
- On read, these (and any other comments) are skipped.

## The title
(source: cutmd/src/parse.ts, cutmd/src/lines.ts)

- `# <title>`: the cut list's title (trimmed). Written after the preamble when there is one.
- A second `# ` line: problem "a cut list has one title; this is a second one".

## Headings
(source: cutmd/src/parse.ts, cutmd/src/lines.ts, cutmd/src/grammar.ts)

- Any line starting `## ` is a heading. A trailing `<!-- ... -->` on it is its colour (or its tag). The heading's kind is decided in this order:
  1. Trailing `<!-- heading -->` or `<!-- heading <Colour> -->`: a **plain heading** whatever the title says, with that colour or none.
  2. Title starts `§`: a **section** heading (in the cut). No colour comment means Blue.
  3. Title starts `◆`: a **note** heading (in the cut). No colour comment means Green.
  4. Title starts `⧉`: a **saved sequence** (bench). Name is the rest.
  5. Title starts `Alternates` (exact case): an **alternates** section (bench), title kept verbatim.
  6. Title starts `staged` (any case): a **shelf** (bench). The category is the rest after leading spaces, colons, slashes, bars, en or em dashes, middle dots and hyphens are removed; empty means the plain shelf.
  7. Anything else: a **plain heading** in the cut.
- Rows after a bench heading belong to that bench section until the next `##`. An in-cut heading after a bench section returns following rows to the cut (the writer then writes all in-cut rows before the bench).
- **Written forms**
  - Section: `## § <title>` then the colour comment. Note heading: `## ◆ <title>` then the colour comment. Plain: `## <title>`, colour comment only when it has one.
  - A plain heading whose title would read as another kind (starts with `§`, `◆`, `⧉`, `Alternates` or `staged`) is written with the tag: `## <title>  <!-- heading -->` or `<!-- heading <Colour> -->`. (New edits refuse such titles; this form only round-trips files that already have them.)
  - The colour comment `<!-- <Colour> -->` starts at column 66 (at least one space after the title).
  - Shelf: the title as read when it still names the same category; otherwise `## staged` or `## staged` + space + U+2014 em dash + space + category.
  - Sequence: `## ⧉ <name>`. Alternates: `## <title as read>`.
  - Every heading is followed by its id line, flush left: `<!-- id: s1234567 -->`.
  - An in-cut heading's summary follows its id line, one comment line per line of text: `<!-- summary [<hash>]: <text> -->` (the hash only on the first line, and only when there is one).

## Bullets: cuts, gaps and note rows
(source: cutmd/src/parse.ts, cutmd/src/lines.ts, cutmd/src/grammar.ts, cutmd/src/py.ts)

- A **cut line**: `- **<Speaker>** \`<clip>\` <in> → <out> (<duration>) <!-- <Colour> -->`
  - The speaker part is optional. The clip is between backticks (trimmed).
  - In and out: optional minus, digits, optional decimals; any Unicode decimal digits are accepted (fullwidth digits typed with a Chinese input method read as numbers).
  - The separator may be `→`, `->`, `-->`, an en dash or an em dash, with any spacing.
  - The `(...)` duration is optional and ignored on read.
  - The colour comment is optional: a colour name (Brown read as Chocolate), or a hex colour `#rrggbb` / `#rgb` mapped to the nearest Resolve clip colour (an exact canvas-palette colour first, else the nearest by weighted RGB distance, never Brown). An unknown name is kept as written with warning "unknown clip colour 'X' kept as written".
  - Written as `- **<Speaker>** \`<clip>\` <in to 6 places> → <out to 6 places> (<length to 1 place>s)`, plus ` <!-- <Colour> -->` when coloured, then the id line `  <!-- id: c1234567 -->`.
- A **gap line**: `- gap <seconds>` with an optional `s` (`gap` in any case). The length is rounded to 6 places. A length of 0 or less: warning "line N: a gap of N s is no gap; it is not part of the cut list", dropped. Each gap line is a gap row where it stands (consecutive gap lines stay separate rows). Written `- gap <seconds with as few decimals as needed, always one>s`, then `  <!-- id: g1234567 -->`, then its note lines `  <!-- note: <text> -->`, one per line.
- A **note row**: `- (note) <text>` or `- (unmatched) <text>` (text trimmed, may be empty). Written the same, then `  <!-- id: n1234567 -->`.
- Any other line starting `-`: problem "cannot read this bullet: '<first 72 characters>'".
- Any other line that is not blank, not a comment, not a heading and not a continuation of a cut: problem "expected a bullet, a heading or a blank line, got '<first 48 characters>'".

## Lines under a cut (continuation lines)
(source: cutmd/src/parse.ts, cutmd/src/lines.ts, cutmd/src/grammar.ts)

- Read only directly under a cut bullet (before the next bullet or heading), tried in this order:
  - **Fade**: `  - fade: in <s>s out <s>s` (indented; either part optional; the `s` optional; any case). Rounded to 6 places. A negative value: problem "a fade in cannot be -N seconds long" (or "fade out"). Written `  - fade: in <s>s out <s>s` with only the non-zero parts; no line when both are zero.
  - **Gain**: `  - gain: +6.0 dB` (indented; sign and `dB` optional; any case). Rounded to 0.1 and clamped to plus or minus 30. Written `  - gain: <sign><one decimal> dB` only when non-zero.
  - **Note**: `  - note: <text>` (indented). Several note lines join with line breaks. An indented line after a note line that matches nothing else continues the note (trimmed).
  - **Link**: `  [[<target>]]` (greedy to the last `]]`, so targets containing `]` work). When the target starts `<speaker or clip>_Transcript#^`, only the part after `^` is kept as the ref; otherwise the whole target is kept.
  - **Words**: `  > <text>` lines, joined with line breaks. `==text==` marks a highlight (trimmed; a lone `==` is literal; an empty one is ignored).
- **Written order under a cut**: id line; link (`  [[<speaker or clip>_Transcript#^<ref>]]`, or the full target when the ref contains `#`); words, one `  > ` line per line with `==` put back around each highlight (a line with no words written `  >`); fade; gain; note.
- **Note lines after the first** are written indented four spaces when the line is plain; a line that is empty, has leading or trailing spaces, or starts with `-`, `>`, `<`, `#` or `[` is written as another `  - note: <line>` line instead (both forms read back the same).

## Comments, id lines, gap notes and section summaries
(source: cutmd/src/parse.ts, cutmd/src/grammar.ts, cutmd/src/render.ts)

- Any line whose trimmed text starts `<!--` is a comment. One without `-->` on the same line runs until a line containing `-->`; everything inside is skipped.
- **Id line** `<!-- id: <letter><7 characters> -->` (any spacing): attaches to the row directly above it when the letter matches the row's kind (`c` cut, `g` gap, `s` heading or bench section, `n` note row) and that row has no id yet. Otherwise warning "line N: an id line that belongs to no row above it is kept as a comment".
- An id used twice in the file: the second row gets a new id, warning "line N: id X is used twice; this row is given a new one".
- A row with no id line gets a deterministic id (see Ids) and the reader reports that ids were minted.
- **Gap note lines** `<!-- note: <text> -->` directly under a gap (after its id line, before any other non-comment line). **Summary lines** `<!-- summary: <text> -->` or `<!-- summary [<hash>]: <text> -->` directly under an in-cut heading; the first hash given wins. A note line under a heading, a summary under a gap, or a `note [hash]` form is just a comment.
  - Escapes inside these lines: `\` is written `\\`; the `>` of `-->` or `--!>` is written `\>`. A lone backslash in a hand edit is kept.
  - Read text is normalised like an edit would normalise it; a gap note over 2000 characters or a summary over 4000 is cut there with a warning ("a gap note is longer than 2000 characters; the rest is not read").
- Every other comment is ignored by the reader. In the preserving writer, hand-written comments are kept (see the writer).

## The writer: canonical and preserving
(source: cutmd/src/render.ts, cutmd/src/lines.ts, cutmd/src/layout.ts)

- **Canonical**: the same cut list always gives the same bytes, with LF line endings: frontmatter, preamble, title, every in-cut row, then each bench section heading followed by its items; one blank line between blocks; one final newline. Feature data lines are spliced into the frontmatter.
- **Preserving** (what the server uses when it rewrites a file it has read): the file was cut into blocks when read (frontmatter, preamble, title, and one per row and bench section).
  - A block whose content is unchanged is written exactly as it was read: line endings, spacing, hand comments, unreadable lines and the blank lines after it.
  - A changed block is written in canonical form, followed by the complete hand comments it contained (stray id lines and unreadable lines inside it are dropped).
  - Blank lines and complete comments between blocks travel with the block before them when blocks are reordered.
  - The frontmatter is merged line by line: unchanged keys keep their raw line, changed keys are rewritten, keys the file lacked are inserted in canonical order, unknown keys, comments and blank lines are kept. (`rev:` and `written:` change on every server write.)
  - When the server writes, every row gets its id line (added under a row that had none, corrected where the file's id was a duplicate).
  - The result is re-read and must give back exactly the cut list it was asked to write (ids included); otherwise the canonical text is written instead (in the file's line ending).
- Not stored in the file: the `question` flag.

## Python-compatible text and numbers in the file
(source: cutmd/src/py.ts, core/src/num.ts)

- Whitespace and line breaks are Python's (includes U+001C to U+001F and U+0085; excludes the byte-order mark).
- Numbers are formatted and rounded exactly as Python's `'%.6f'` and `round()` do (halves to even on the exact binary value), so a value written by the old Python writer reads and writes back identically.
- Lengths and sorting count Unicode code points, not UTF-16 units.
- Frontmatter numbers accept Python's full float and int syntax (signs, `_` separators, exponents, `inf`, `nan`, any Unicode decimal digits).

## Looks redundant or overlapping

- Two implementations of "turn an edited cut list into edits": `core/src/diff.ts` (`diffProjects`, used only by the Resolve import feature) and `cutmd/src/diff.ts` (`diffAgainst`, used by the server's outside-edit merge). They match rows, choose field edits and build the restore differently (the cutmd one stages removed cuts, merges order three ways and patches clip or speaker; the core one restores whole cuts and places by full layout).
- Two copies of the deterministic id mint (`core/src/ids.ts` and `cutmd/src/ids.ts`), two copies of Python whitespace, strip and split-lines (`core/src/text.ts` and `cutmd/src/py.ts`), two copies of Python rounding (`core/src/num.ts` and `cutmd/src/py.ts`), and two copies of the frame-rate snapping (`core/src/num.ts` `fileRate` and `cutmd/src/py.ts` `exactFps`). Each pair is kept equal by tests.
- Two clip-name scanners of a `.cut.md` besides the real reader: the media service's line scan (`clipNamesOfCutMd`) and the project list's line scan (`peekCutMd`), each with its own copy of the cut-line pattern.
- Two in-process background schedulers with overlapping jobs: the Claude runner's own queue and cost budget, and the work queue's per-day run budget (features use both on top of each other).
- Proposals (`/api/proposals`) duplicate what an edit through `/api/ops` or the socket does, with an in-memory store only and no server-side producer in the editor.
- Three login front doors for one editor: none, password (with its own login page and throttling) and trusted proxy; the dashboard deployment uses only the proxy door.
- Read-only mode keeps a whole working copy of every cut list in the system temp folder, and the media service separately keeps waveforms in memory, to achieve "do not write to the vault".
- `GET /api/log` and the socket's welcome both deliver catch-up history.
- The legacy `setGap` form, legacy gap migration on snapshots and legacy gap fields on inserts and restores all exist only to replay data made before 2026-10-29.

## Claims the code does not back

- `core/src/ops.ts`, `SaveSequenceOp`: "gaps INCLUDING the first one kept with it". The code takes a gap before the first cut only when it is named.
- `core/src/ops.ts`, `RemoveRangeOp` ("the gap stays on the first") and `SplitOp` ("[in, at) keeps id/gap/fade-in"): cuts no longer carry a gap; gaps are rows and are not touched by either edit.
- `core/src/diff.ts` header: field edits on matched cuts include `setGap`. The code never produces `setGap`; gaps travel in the restore.
- `core/src/ops.ts` and `core/src/protocol.ts` list refusal codes `noop` and `stale`; nothing produces either.
- `core/src/media.ts`: `missing` is "clip names the project uses that have no media in remote_audio", and media is "<Episode>/Script Docs/remote_audio/<clip>.ogg". The code also finds `Interviewees/.../* Multicam.wav` and `remote_audio/source/` extractions, and lists as missing clips whose audio exists but could not be probed.
- `server/main.ts` header: `TC_STATIC` defaults to "./dist when it exists". The code uses `<editor root>/dist` (from `TC_ROOT` or the code's location), not the working folder.
- `server/types.ts`: `allowedOrigins` "Origins besides the server's own that may open /sync or call /api/* (e.g. a dashboard on another port)". `npm start` has no way to set it; only the dashboard entry point does.
- `server/ai/runner.ts`: the "needed more than N turns" sentence prints the call's own limit or 1, so a tool run that hit the default limit of 8 is told "more than 1 turns".
- `server/platform/proposals.ts` header: "A producer that runs on the server (a Resolve import, a background job, a feature's server route) hands a proposal in". No server code in the editor calls the proposal store.

## Could not determine

- Who, if anyone, POSTs to `/api/proposals` in production (only the page's GET and DELETE were found).
- Whether the media service reading cut lists from the vault (not the working copy) in a read-only run is intended; a cut list created in the editor during a read-only run has no `/media/sources?project=` answer.
- Whether any real client uses the `adapter:` or `derive:` client-id prefixes to set an edit's origin; the prefix is trusted from the client.
- The exact text of the dashboard-mounted variant's settings (`TC_MOUNT_BASE`, `TC_ALLOWED_ORIGINS`, `TC_MOUNT_HOME`) is in `features/projects/host.ts`, outside this part; only their existence was confirmed.
