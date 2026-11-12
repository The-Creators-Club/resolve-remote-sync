# Shared server-script behaviour: `server/common.py` and `server/truenas_rpc.py`

## Site manifest (`site.toml`): where it is found and what is read
(source: common.py)

- **How the file is found.** The first of these that applies wins:
  1. `--site <path>` or `--site=<path>` on the command line. This is read straight from the raw arguments when the module is imported, so it works even in a script that does not parse the flag.
  2. The environment variable `CCSYNC_SITE`.
  3. `<repo>/site.toml`.
  4. Nothing: every value is blank.
- **A named file that is missing is refused.** If `--site` or `CCSYNC_SITE` names something that is not a file, the run fails with: `--site/CCSYNC_SITE points at '<path>', which is not a file`.
  - This happens when the module is imported, which is before the top-level error wrapper is running. The operator therefore gets a Python traceback, not the one-line `FAILED:` message.
  - Invalid TOML in the file also gives a raw traceback at import.
- **A missing `<repo>/site.toml` is not an error.** Every value is blank, and a later refusal names the key that was needed.
- **The `--site` flag in help.** Every script adds `--site` (default empty) with help text saying it "carries the NAS host, tree root and app paths -- never secrets. Start from site.example.toml."
- **How values are read.**
  - Strings are trimmed.
  - Booleans accept `1/true/yes/on` and `0/false/no/off`. Anything else falls back to the default.
  - A whole number that cannot be read falls back to the default.
  - A list value can be a single string (treated as a one-item list). Backslashes become `/`, leading and trailing `/` are stripped, and blank items are dropped. Any other type counts as absent.
- **Order of precedence (general rule):** a command-line flag beats an environment variable, which beats `site.toml`, which beats blank.
  - Exception: host, user and NAS kind take no flag here. For those, the environment beats `site.toml`.
- **Keys read, with their defaults:**
  - `[nas] kind`: defaults to `truenas`.
  - `[nas] host`: no default. If blank, the run is refused.
  - `[nas] admin_user`: no default. If blank, the run is refused.
  - `[nas] verify_ssl`: see the TLS section.
  - `[nas] ssh_hostkey`: the pinned SSH host key.
  - `[nas] ssh_port`: see the SSH section.
  - `[nas] dsm_port`: defaults to 5001.
  - `[net] sftp_port`: used as the SSH port when `[nas] ssh_port` is not set.
  - `[tree] pool_root` and `[tree] tree_name`: the tree root is `<pool_root>/<tree_name>`. If either is blank, the tree root is blank.
  - `[tree] projects_dir`: defaults to `Projects`. The projects root is `<tree root>/<projects_dir>`.
  - `[tree] homes_parent`: defaults to `<pool_root>/homes`, or blank when there is no pool root.
  - `[tree] template_folders`: defaults to `AE`, `Audio/Music`, `Audio/Voiceover`, `B-roll`, `Interviewees`, `Render in Place`, `Subs`, `Youtube`.
  - `[tree] shared_assets`: defaults to `Assets/Luts` (folder id `assets-luts`, label "Assets/Luts (LUT library)") and `Assets/Stills` (folder id `assets-stills`, label "Assets/Stills (Resolve gallery)"). When overridden, each folder id is the slug of its path, and the label is the default label or else the path itself.
  - `[apps] root`: the dashboard app's host tree. No default.
  - `[stack] owner`: defaults to `broll`.
  - `[stack] group`: defaults to `editors`.
  - `[stack] editor_shell`: `sftp-only` (the default) or `shell`. Any other value is refused with `[stack] editor_shell is '<x>'; expected one of sftp-only, shell (docs/SERVER.md, "Editor accounts")`.
    - The sftp-only login shell is `/usr/sbin/nologin`.
  - `[stack] project_acl`: `per-project` (the default when unset) or `shared`. Any other value is refused with `[stack] project_acl is '<x>'; expected one of shared, per-project (docs/TENANCY.md)`.
  - `[security]` legacy opt-outs. Each defaults to false and is read only from `site.toml`, never from the environment. Asking for an unknown flag raises `unknown [security] flag '<x>'`.
    - `allow_nas_password_in_container`
    - `allow_nas_admin_as_dashboard_admin`
    - `skip_lane_host_key_pin`
- **Paths derived from the tree root.**
  - B-roll archive: `<tree root>/Assets/B-roll Archive`.
  - LUT library: `<tree root>/Assets/Luts`.
  - Gallery: `<tree root>/Assets/Stills`.
- **Refusal when an identity value is blank.** The message is: `<key> is not configured. Set it in <loaded site file or <repo>/site.toml>[, or pass <flag>]. Copy site.example.toml to site.toml and fill it in -- there are deliberately no built-in defaults for site identity (host, pool, tree).`

## Environment variables (complete list for these two files)
(source: common.py, truenas_rpc.py)

**Which NAS, and how to reach it**
- `CCSYNC_SITE`: path to the site manifest (see above).
- `SYNO_HOST`, then `TRUENAS_HOST`, then `[nas] host`: the NAS address.
  - `SYNO_HOST` wins whatever the NAS kind is.
  - The refusal when all are blank names `[nas] host` and `TRUENAS_HOST`.
- `SYNO_USER`, then `TRUENAS_USER`, then `[nas] admin_user`: the admin account. Same precedence and refusal shape as the host.
- `CCSYNC_NAS_KIND`: `truenas` or `synology`. It comes after the `--nas-kind` flag and before `[nas] kind`.
  - Any other value is refused: `unknown NAS kind '<x>': expected one of truenas, synology`.
- `CCSYNC_SSH_PORT`: the SSH port (see the SSH section).

**Passwords and keys**
- `TRUENAS_PW` (TrueNAS) or `SYNO_PW` (Synology): the admin password.
  - The variable matching the NAS kind is used first. The other is accepted with a one-time stderr note: `NOTE: <primary> is not set; using <alias> instead (this site's [nas] kind is '<kind>'). Set <primary> to make the intent explicit.`
  - If neither is set, a real run is refused: `Required environment variable <primary> is not set. See server/README.md for the full list of env vars this script needs.`
  - A dry run uses the placeholder `<TRUENAS_PW-unset-dry-run>` (or the `SYNO_PW` equivalent) instead.
- `TRUENAS_SUDO_PW` or `SYNO_SUDO_PW` (by kind): a separate sudo password. If unset, sudo uses the login password.
- `TRUENAS_API_KEY`: a scoped TrueNAS API key. When set it replaces password authentication for API calls, and those calls then need no admin password. SSH still uses the password.
- `TRUENAS_API_KEY_USER`: the account the key was made for. Blank means the key belongs to the admin account.
- `PG_PASSWORD` and `CCSYNC_PG_PASSWORD_FILE`: see the project-server password section.
- The general "required variable" refusal reads: `Required environment variable <NAME> is not set. See server/README.md for the full list of env vars this script needs.`

**TLS, host keys and first-use trust**
- `TRUENAS_VERIFY_SSL`: TLS verification for the TrueNAS API. It beats `[nas] verify_ssl`.
- `SYNO_VERIFY_SSL`: TLS verification for DSM. It beats `TRUENAS_VERIFY_SSL`, which beats `[nas] verify_ssl`.
- `CCSYNC_KNOWN_CERTS`: overrides the location of the recorded-certificate file. Default: `~/.ccsync/known_certs.json`.
- `CCSYNC_SSH_HOSTKEY`: the pinned SSH host key. It comes after `--host-key` and before `[nas] ssh_hostkey`.
- `CCSYNC_SSH_TRUST_ON_FIRST_USE`: `1/true/yes/on` behaves like `--trust-host-key-on-first-use`. It covers both the SSH host key and the API certificate.
- `CCSYNC_KNOWN_HOSTS`: overrides the location of the recorded host-key file. Default: `~/.ccsync/known_hosts`.

**Snapshots**
- `CCSYNC_REQUIRE_SNAPSHOT`: the values `1`, `true` and `yes` (exact lowercase; `on` does not count) make a failed pre-operation snapshot a refusal.
- `CCSYNC_SNAPSHOT_LOG`: overrides the location of the snapshot log. Default: `~/.ccsync/snapshot_log.jsonl`.

**TrueNAS API transport**
- `TRUENAS_WS_URL`: an exact WebSocket URL for the JSON-RPC API, replacing `wss://<host>/api/current`.
- `DASH_NAS_API_TRANSPORT`, then `TRUENAS_API_TRANSPORT`: `auto` (the default), `jsonrpc` or `rest`. Any other value counts as `auto`.
  - The dashboard's `DASH_` name is honoured on the workstation and wins.
- `DASH_NAS_API_PATH`, then `TRUENAS_API_PATH`: the WebSocket path.
  - `current` means `/api/current`.
  - A value starting with `/` is used as written. Anything else becomes `/api/<value>`.
  - The default is `/api/current`.

## Flags shared by scripts
(source: common.py)

- **`--site <path>`**: see above.
- **`--host-key <line>`** (default empty): pins the NAS SSH host key for this run. Its help says an unpinned host not already in `~/.ccsync/known_hosts` "is REFUSED".
- **`--trust-host-key-on-first-use`** (off by default): accepts an unknown SSH host key or an unknown API certificate once and records it.
  - It is also detected from the raw command line, so it works in scripts that never pass it on.
- **`--nas-kind truenas|synology`** (default empty): falls back to `CCSYNC_NAS_KIND`, then `[nas] kind`, then `truenas`.
- **Confirmation flag (`--yes`, or whatever name the script passes):** see "Confirming destructive runs".
- **Warning when a secret is typed on the command line.** For a flag a script names as a secret (tests use `--api-key` with `SYNCTHING_API_KEY`), using `<flag> value` or `<flag>=value` prints this to stderr:
  - `WARNING: <flag> puts a secret on the command line (shell history, the process list). Leave it off and set <ENV> in the environment instead: `. .\tools\load_secrets.ps1` does that on the base rig.`
  - The flag still works.
  - `--api-key-file` does not trigger it.
  - The text names a PowerShell script on the base rig, whatever OS the operator is on.
  - Per grep, the callers are `setup_syncthing_folder.py`, `secure_syncthing_gui.py`, `accept_device.py` and `check_health.py`. Which flag each one passes is not verified, because those files are outside this part.

## Top-level wrapper, banner and exit codes
(source: common.py)

- **Banner.** Every script started through the shared wrapper prints one line to stdout before it does anything, unless `-h` or `--help` is on the command line. The line is printed at most once per process.
  - Format: `NAS: <user>@<host>:<port> (<kind>)  site: <site file or <none>>  tree: <tree root or <not configured>>`
  - A missing host or user shows as `<not configured>`.
  - A bad kind shows as `unknown kind`.
  - The kind shown reads `--nas-kind` from the raw command line.
- **Configuration refusal.** The script prints `FAILED: <message>` to stderr and exits with code 2. Nothing is changed.
- **Backend not available.** Choosing a NAS backend that is not ready (Synology, if its backend says it is not ready) prints `FAILED: <pending message>` and exits 2, before any connection is opened. The pending text and whether Synology is ready live in `backends/synology.py`, which is outside this part.
- **Any other exception** is not caught: the operator sees a Python traceback and exit code 1.
  - This includes the `ConnectionError` raised for TrueNAS JSON-RPC transport or authentication failures. Whether individual scripts catch it is outside this part.
- **Normal exit:** the script's own return value is the exit code.
- **TrueNAS version note.** At most once per process, on a TrueNAS site and not in a dry run, a script may call `GET /system/info` and print `NOTE: <note>` to stderr. It never refuses, and any failure is silent.
  - Version below 25.04: `TrueNAS <v> predates 25.04: only the REST API exists there, which works but is not a supported version. Upgrade to 25.04 or later`
  - Version above 26.99: `TrueNAS <v> is newer than this CC Sync release has been tested against. Check docs/SERVER.md for the supported versions before upgrading`
  - Version that cannot be read (the check looks for `NN.N` or `NN.NN`): `cannot tell the TrueNAS version from '<text>'`

## Confirming destructive runs
(source: common.py)

- **Dry run:** never asks.
- **Otherwise:** prints the banner (if not already printed), then:
  - **No host configured:** returns without asking, and the caller's own refusal follows.
  - **Confirmation flag given:** prints `<what>\n  confirmed by <flag>: proceeding against <user>@<host>.` and continues.
  - **Standard input is not a terminal:** refused with `<what>\n  This changes <user>@<host> and there is no terminal here to confirm it on. Re-run with <flag> if that is the box you mean, or with --dry-run to see what it would do. Nothing was changed.` (exit 2).
  - **Interactive:** prompts `<what>\n  This changes <user>@<host>. Type the NAS's name (<short>) to go ahead: `.
    - `<short>` is the first label of the host name, or the whole address when the host is an IP literal.
    - The answer is compared without regard to case.
    - A wrong answer is refused with `stopped: '<typed>' is not '<short>'. Nothing was changed. (<flag> skips this question.)`

## Reaching the NAS over SSH
(source: common.py)

- **Library and login.** SSH uses paramiko with the username and password only: no key files and no agent.
  - Connect timeout: 20 s.
  - Command timeout: 120 s by default (a caller may change it).
  - No terminal is requested. There are no retries.
- **SSH port.**
  - Order: `CCSYNC_SSH_PORT`, then `[nas] ssh_port`, then `[net] sftp_port`, then 22.
  - A value that is not a number, or is outside 1 to 65535, becomes 22.
- **How the sudo password reaches the NAS.** It is never placed on a command line.
  - Every remote command is prefixed with a line that reads the password from standard input into `SUDO_PW` and exports it.
  - The sudo password (or the login password) is written as the first line of input, and input is then closed. A remote command therefore cannot read input of its own.
  - Privileged commands use `echo "$SUDO_PW" | sudo -S -p "" ...`.
- **Result.** Each call returns the exit code, stdout and stderr. Decoding errors are replaced, not raised.
- **Dry run.** Nothing is connected. The script prints `[dry-run] ssh <user>@<host>[ -p <port>]: <cmd>` and the command counts as succeeding with exit code 0.
  - Host and user are still required in a dry run. The password is not.
- **Host-key trust has three states:**
  1. **Pinned** (`--host-key`, `CCSYNC_SSH_HOSTKEY` or `[nas] ssh_hostkey`): only that key is accepted.
     - Accepted formats: `<type> <base64>`, `<host> <type> <base64>`, or `<type> <base64> <comment>`.
     - The type token must start with `ssh-`, `ecdsa-`, `sk-ssh-` or `sk-ecdsa-`.
     - Errors: `host key pin '<x>' is not a known_hosts-style line (expected e.g. 'ssh-ed25519 AAAAC3...')`, `host key pin base64 is not decodable: ...`, `unsupported host key type in pin: '<t>'`, `could not parse host key pin: ...`.
  2. **Not pinned, but recorded** in `~/.ccsync/known_hosts` (OpenSSH format; a non-22 port is recorded as `[host]:port`): only the recorded key is accepted.
     - A file that cannot be read is refused: `<path> could not be read as a known_hosts file (<Err>: <msg>). Fix or delete it, or pin the key with [nas] ssh_hostkey instead.`
  3. **Neither pinned nor recorded:**
     - With first-use trust on, the offered key is accepted, appended to the file (permissions 0600, a no-op on Windows), and this is printed to stderr: `TRUSTED ON FIRST USE: <host> host key SHA256:<fp> (<type>), recorded in <path>. Later runs are checked against it and a change is a refusal.` followed by the exact `ssh_hostkey = "<type> <base64>"` line to paste into `[nas]`.
     - Without first-use trust, the run is refused with a multi-line message. It begins `refusing to SSH to <host> (port <port>): its host key is neither pinned nor known.`, explains that the channel carries the admin password, and gives the `ssh-keyscan -t ed25519 [-p <port>] <host>` command, the `[nas] ssh_hostkey` / `CCSYNC_SSH_HOSTKEY` option, and the `--trust-host-key-on-first-use` / `$CCSYNC_SSH_TRUST_ON_FIRST_USE=1` option with the file path.
- **Changed host key** (against a pin or a recorded key): refused with `REFUSING to talk to <host> (port <port>): its SSH host key CHANGED.`, the expected and offered SHA256 fingerprints, the source (`[nas] ssh_hostkey / CCSYNC_SSH_HOSTKEY` or the file path), the advice to update the pin or run `ssh-keygen -R <host> -f <path>`, and `Nothing was sent.` It is never re-trusted automatically.
- **Host key passed on to other components.** The single `<type> <base64>` key line is taken from the pin, or else from the recorded key. Callers carry it into the Synology dashboard's NAS host key and the site manifest's SFTP host key.
  - A pin that cannot be parsed is passed on as written, with whitespace normalised.
- **Writing small text files over SFTP** (used for a compose file and `.env` on Synology):
  - Existing files are replaced and nothing is deleted.
  - Each file prints `uploaded <n> bytes to <path> (SFTP view)`.
  - Any failure prints `FAILED: SFTP write to <dir> did not finish (<Err>: <msg>)` and reports failure without raising.
  - Dry run prints `[dry-run] would SFTP <n> bytes to <dir>/<name>`.

## TLS verification of the NAS web API (TrueNAS and DSM)
(source: common.py, truenas_rpc.py)

- **Possible values** (from the environment variables or `[nas] verify_ssl` above):
  - **Unset (the secure default): a certificate pin.**
    - If `~/.ccsync/known_certs.json` has an entry for `host:port`, the certificate is pinned to it.
    - Otherwise, with first-use trust on, one TLS handshake is made (10 s timeout, nothing sent, the chain is not checked). Its SHA-256 is recorded (file permissions 0600) and this is printed to stderr: `TRUSTED ON FIRST USE: the NAS API certificate at <host:port> (sha256 <hex>) is recorded in <path>. Later runs are checked against it and a change is a refusal.` followed by the `verify_ssl = "sha256:<hex>"` line to paste.
    - Otherwise the run is refused with a multi-line message beginning `refusing to talk to the NAS API at <host:port>: its TLS certificate is neither pinned nor recorded.` It gives three ways forward: an openssl command to read the fingerprint, the first-use flag or variable, and `[nas] verify_ssl = "0"`.
    - A handshake that returns no certificate is refused: `<host>:<port> presented no certificate`.
    - A corrupt certificate file is refused: `<path> could not be read (<err>). Fix or delete it, or set [nas] verify_ssl = "sha256:<fingerprint>" in site.toml instead.`
  - **`0`, `false`, `no` or `off`: verification off.** A warning is printed once per variable name: `WARNING: TLS certificate verification is OFF for <the NAS|DSM>'s API (<VAR> is 0). The admin password and every account this creates cross that connection (...). Pin the certificate with <VAR>=sha256:<fingerprint>, or point it at a CA file -- ...`
  - **`1`, `true`, `yes` or `on`:** the system CA bundle is used.
  - **`sha256:<64 hex>`:** pinned to that fingerprint. Colons and spaces are ignored and case does not matter.
    - A malformed pin is refused, never treated as off: `'<x>' is not a certificate pin: expected 'sha256:' and 64 hex digits (`openssl x509 -noout -fingerprint -sha256`).`
  - **Anything else:** treated as the path of a CA file.
- **Which port's certificate is checked.** 443 on TrueNAS, and `[nas] dsm_port` (default 5001) on Synology.
  - The kind is read from `CCSYNC_NAS_KIND` or `[nas] kind` only. The `--nas-kind` flag is not consulted here.
- **How a pin is enforced.** REST and DSM calls compare the fingerprint during the handshake. The JSON-RPC WebSocket compares it right after the handshake, and a mismatch is refused: `the certificate <host>:<port> presented does not match the pinned sha256 fingerprint; refusing (a changed NAS certificate is never re-trusted)`.
- **The urllib3 "insecure request" warning is suppressed** for the whole process.

## TrueNAS API calls
(source: common.py, truenas_rpc.py)

- **Authentication.**
  - If `TRUENAS_API_KEY` is set, the key is used: REST sends `Authorization: Bearer <key>`, and JSON-RPC uses the key login. No admin password is needed.
  - Otherwise the admin username and password are used: HTTP basic auth for REST, password login for JSON-RPC.
- **Dry run.** Nothing is sent. The script prints `[dry-run] <METHOD> https://<host>/api/v2.0<path> params=<..> body=<..> auth=<api-key|basic:<user>>`.
- **Choosing the transport** (`auto` by default):
  - **`auto` or `jsonrpc`, and the host is not currently marked REST-only:** the call is made over JSON-RPC 2.0 on a WebSocket at `wss://<host>/api/current` (port 443, timeout 30 s).
    - If the NAS has no JSON-RPC there and the setting is `auto`: the host is marked REST-only for 300 s, stderr shows `NOTE: <host> serves no JSON-RPC API (<reason>); using REST /api/v2.0, which TrueNAS 26 no longer has.`, and the call goes over REST.
    - Same situation with `jsonrpc`: a connection error is raised: `<host> has no JSON-RPC API (<reason>) and TRUENAS_API_TRANSPORT=jsonrpc forbids falling back to REST`.
    - A route with no JSON-RPC equivalent: under `auto` it silently goes over REST. Under `jsonrpc` it raises `TrueNAS JSON-RPC <METHOD> <path>: <METHOD> <path>`.
    - A transport or login failure raises a connection error `TrueNAS JSON-RPC <METHOD> <path>: <detail>`, with no fallback to REST.
  - **REST:** `https://<host>/api/v2.0<path>`, timeout 30 s.
    - A 404 that arrives after falling back to REST clears the REST-only mark, so the next call tries JSON-RPC again.
    - For routes that do not contain `/id/`, it also prints: `NOTE: <METHOD> <path> answered 404 on <host>: if this NAS runs TrueNAS 26 or later REST is gone and JSON-RPC at /api/current must be reachable (docs/SERVER.md, supported versions).`
- **Rules for the JSON-RPC connection:**
  - Plain `ws://` to any host other than loopback is refused: `refusing plaintext ws:// to a non-loopback host: TrueNAS revokes an API key used over an unencrypted connection`. A URL that is not ws or wss is refused: `not a websocket URL: '<url>'`.
  - Handshake answers:
    - HTTP 101: connected.
    - Any other status below 500, except 429: treated as "no JSON-RPC here", so REST may be used.
    - 5xx, 429 or no status: a transport error, `websocket handshake refused: '<status line>'`.
    - A bad accept header: `websocket handshake: bad Sec-WebSocket-Accept`.
    - Handshake replies over 65,536 bytes are refused.
  - Messages over 64 MiB are refused. The client answers pings. A close frame from the NAS is an error: `the NAS closed the websocket`.
  - Connection failures read: `cannot connect to <host>:<port>: <err>`.
  - Messages from the NAS that are not replies to the call (notifications) are ignored.
- **Logging in over JSON-RPC.**
  - **With an API key:**
    1. `auth.login_ex` with mechanism `API_KEY_PLAIN`, as `TRUENAS_API_KEY_USER` or else the admin user.
    2. If that does not succeed, the older `auth.login_with_api_key`.
    - "No such method", `EINVAL` and `EAUTH` move on to the next method. Other errors are re-raised.
    - If both fail: `the NAS refused the API key. <hint>. A key sent over a connection TrueNAS does not treat as secure is revoked by it`. The hint is one of three, depending on whether `TRUENAS_API_KEY_USER` was set: it names the account the key was presented as and points to setting `DASH_NAS_API_KEY_USER / TRUENAS_API_KEY_USER` (and `create_api_key.py --username`).
  - **With a password:**
    1. `auth.login_ex` with mechanism `PASSWORD_PLAIN`.
    2. If that method does not exist, the older `auth.login`.
    - A non-success response type gives `the NAS refused the login (<type>)`. A final failure gives `the NAS refused the username or password`.
  - Any other login error is wrapped as `the NAS refused the login: <message> (<errname>)`.
- **Session reuse.**
  - One logged-in session is kept per target and set of credentials, and reused within the process.
  - It is dropped after 25 s of idleness.
  - Before a write on a reused session, a `core.ping` liveness check runs, and a dead session is replaced first.
  - After a transport failure there is one retry on a fresh login, only for a read or for a write that was never sent. A write that may already have run is never replayed.
- **Routes that have a JSON-RPC equivalent** (every other route counts as having none):
  - **`user`, `group`, `app`, `api_key`:**
    - `GET /<ns>` becomes `<ns>.query`, with the query parameters turned into `=` filters (an `id` made of digits is sent as a number).
    - `POST /<ns>` becomes `<ns>.create`.
    - `GET /<ns>/id/<x>` becomes `get_instance`.
    - `PUT /<ns>/id/<x>` becomes `update`.
    - `DELETE /<ns>/id/<x>` becomes `delete`, with the body sent if there is one.
  - **`/pool/snapshottask`:** `GET` becomes query, `POST` becomes create, `PUT /pool/snapshottask/id/<x>` becomes update.
  - **Single routes:**
    - `POST /filesystem/setperm` becomes `filesystem.setperm`.
    - `GET /core/get_jobs` becomes `core.get_jobs` with filters.
    - `POST /zfs/snapshot` becomes `pool.snapshot.create`, and is retried as `zfs.snapshot.create` when that method does not exist.
    - `GET /system/info` becomes `system.info`.
    - `GET /ssh` becomes `ssh.config`, and `PUT /ssh` becomes `ssh.update`.
    - `GET /app/available` becomes `app.available` with filters.
    - `GET /catalog/apps` becomes `catalog.apps`.
    - `POST /app/redeploy` becomes `app.redeploy` and requires `app_name` in the body; without it, the route is treated as having no equivalent.
- **How JSON-RPC errors are reported to callers (as HTTP-like status codes):**
  - `EINVAL` gives 422. `ENOENT` gives 404. `EACCES` and `EPERM` give 403. `ENOTAUTHENTICATED` and `EAUTH` give 401. `EEXIST` gives 409.
  - Without an error name: "no such method" (-32601) gives 404, bad parameters (-32602) give 422, and anything else gives 500.
  - The body carries message, errname, reason and extra. A success counts as status 200.
- **Waiting for a TrueNAS job.**
  - Polls `GET /core/get_jobs?id=<n>` every 2 s for up to 120 s by default.
  - It finishes on `SUCCESS`, `FAILED` or `ABORTED`, with the job's error.
  - Non-2xx answers and empty answers are silently retried.
  - On timeout it returns `TIMEOUT` with `job <id> did not finish within <timeout>s`, and does not raise.

## Synology DSM Web API
(source: common.py)

- **Endpoint.** `https://<host>:<dsm_port, default 5001>/webapi/<cgi>`, timeout 30 s, using the TLS rule above.
- **API check before the first login.** `SYNO.API.Info` is queried for every API that will be used. If any is missing, or does not offer the needed version, the run is refused.
  - Needed versions: Auth v7. User, Group, Group.Member, User.Group, AppPriv.Rule, FileServ.FTP.SFTP, Share, Share.Permission and Share.Snapshot at v1.
  - Refusal: `this DSM does not offer the web API shapes CC Sync installs with: <api: not offered by this DSM | need version N, this DSM offers a-b>; .... Refusing to guess a different shape -- a half-provisioned NAS is worse than an unprovisioned one. See docs/synology-spikes-2026-08-17.md spike 3.`
  - If DSM refuses the Info query itself: `the DSM web API at <host:port> refused SYNO.API.Info -- this does not look like a DSM 7 box`.
- **Login.**
  - POSTed, so the password is not in a URL. Login API version 7, session name `ccsync`, a session id (sid) is requested, and a SynoToken is requested.
  - The session is cached for the process per host and user.
  - Failure: `DSM login for '<user>' failed: error <code> -- <meaning>`. A login that returns no sid: `DSM login succeeded but returned no sid (format=sid was ignored)`.
  - No logout is ever sent.
- **Each call.**
  - Parameters are encoded as JSON (booleans as `true`/`false`, lists and dicts as JSON). Parameters set to None are dropped.
  - The sid is sent as `_sid`, and the SynoToken both as a parameter and in an `X-SYNO-TOKEN` header.
  - If the session has expired (error 119), the run logs in again once. After a second 119: `<api>.<method> kept losing its DSM session`.
  - Any other failure: `<api>.<method> failed: DSM error <code> -- <meaning>`. Error 105 is deliberately not retried.
- **Bad response from DSM:**
  - Non-2xx: `<what>: DSM answered HTTP <n>`.
  - Not JSON: `<what>: response was not JSON ('<first 120 chars>')`.
  - JSON but not an object: `... was not a JSON object (...)`.
- **Error meanings shown to the operator:**
  - 103: no such method
  - 105: the session has no privilege; almost always a session from login version below 7
  - 119: the session id expired
  - 400: invalid account or password
  - 402: the account has no permission to log in to DSM
  - 403: needs a 2-factor code, or the Snapshot Replication package is not installed
  - 3101: bad argument
  - 3103: invalid parameter (a Python boolean sent as text)
  - 3106: no such user
  - 3107: user already exists
  - 3117: the password fails this DSM's password policy
  - 3201: bad group argument
  - 3205: no such group
  - 3206: group already exists
  - 3400: bad or missing parameters
  - Any other code: `DSM error <n>`
- **Dry run.** Prints `[dry-run] DSM <api>.<method> v<n> on <host>: {params}` with `passwd` and `password` shown as `<redacted>`.

## Syncthing REST calls
(source: common.py)

- **Request.** `<gui_url><path>` with an `X-API-Key` header and a 30 s timeout. The standard TLS check of the HTTP library applies, with no pin and no setting to change it.
- **Dry run.** Prints `[dry-run] <METHOD> <url> params=.. body=..`.
- **Success.** Any 2xx response counts as success.

## Snapshot before privileged recursive operations
(source: common.py)

- **What is snapshotted.** The given path, or by default the tree root (`<pool_root>/<tree_name>`). The snapshot is taken by the NAS backend.
  - Snapshot names and retention are decided by the backend, outside this part.
- **Best effort by default.**
  - No path at all prints `WARNING: skipping the pre-<label> snapshot -- no path to snapshot: neither an explicit path nor [tree] pool_root/tree_name in site.toml.`
  - A failed or refused snapshot prints `WARNING: no pre-<label> snapshot of <target> (<detail>). Continuing -- but this operation has nothing behind it. Run server/setup_snapshots.py --apply to put a floor under the tree (docs/BACKUP_RESTORE.md).`
  - In both cases the run continues.
- **Strict mode** (the caller asks for it, or `CCSYNC_REQUIRE_SNAPSHOT` is `1`, `true` or `yes`): the same failures refuse the run with exit 2.
  - No path: `--require-snapshot was given but there is no path to snapshot: ...`
  - Failure: `refusing to run '<label>' without a snapshot of <target>: <detail>. Configure snapshots (server/setup_snapshots.py --apply), or drop --require-snapshot / CCSYNC_REQUIRE_SNAPSHOT to accept the risk.`
- **Snapshot log.** Every attempt, including dry runs (detail "dry run") and failures, appends one JSON line `{ts (UTC, ISO, seconds), label, path, ok, detail}` to `~/.ccsync/snapshot_log.jsonl`.
  - If the append fails: `WARNING: could not append to <path> (<err>). The snapshot verdict below is still correct for this run.`
- **Closing summary line.** One of:
  - `this run had a snapshot behind it: yes`
  - `this run had a snapshot behind it: NO (none was attempted)`
  - `this run had a snapshot behind it: NO (<detail>)`

## Project paths, slugs, markers and group names
(source: common.py)

- **Project location from year, series and project.** Each part must be non-empty and must not contain `/` or `\`, start with `.`, or contain `..`. Otherwise the run is refused: `invalid --<year|series|project> value: '<x>'`.
- **Project location from a path of any depth.** An empty path gives `empty --project-rel-path`. A bad segment gives `invalid path segment: '<x>'`.
- **Slug (the project's identity).**
  - Made by lowercasing, splitting on any run of characters that are not letters or digits, and joining with `-`. A slug that comes out empty is refused: `slugify('<x>') produced an empty slug`.
  - Validation: `empty slug: a project marker must carry an identity`, or `invalid slug '<x>': only lowercase a-z, 0-9 and '-' are allowed (the slug becomes a Syncthing folder id and a dashboard URL segment)`.
- **Project marker file `.ccsync-project`** (JSON with `slug`, `created_by` defaulting to `setup_tree`, and any extra keys kept from an existing marker):
  - **Reading.** The marker is read as root. The result is either `MARKER-PRESENT` followed by its contents, or `MARKER-ABSENT`. If the privileged read cannot run, it prints `MARKER-UNREADABLE` on stderr and exits with code 9, so a sudo failure is never mistaken for "no marker".
  - **Writing.** Written as root. Prints `marker written: .ccsync-project`.
  - **Writing only when absent:**
    - Same slug already there: `marker already present with the same identity, left as is: .ccsync-project (slug <s>)`
    - Different slug already there: `marker already present with a DIFFERENT identity: .ccsync-project keeps slug '<old>' -- NOT overwriting it with '<new>'. The slug is the project's immutable identity; every dashboard row (ticks, Resolve mappings, completion history, media inventory) is keyed on it. If this project really must change identity, do it deliberately with write_marker.py --slug ... --force`
- **Per-project group name.** `proj-<slug>` when that fits in 32 characters. Otherwise the first 25 characters (trailing `-` removed), then `-`, then the first 6 hex characters of the slug's SHA-256.

## Syncthing ignore lists
(source: common.py)

- **Project folder ignore list.**
  - One line `(?i)*<ext>` per video extension: `.braw .mov .mp4 .mxf .avi .mts .m2ts .mkv .r3d .crm .mpg .mpeg .wmv .webm .insv .360`.
  - rclone partial files: `(?i)**/*.partial`, `(?i)*.partial`.
  - yt-dlp partial files: `*.part`, `*.part-Frag*`, `*.ytdl`, each in a `**/` form and a bare form.
  - Proxy folders: `(?i)Proxy`, `(?i)**/Proxy`, `(?i)**/Proxy/**`.
- **Shared asset folder ignore list.**
  - The same video lines and partial-file lines.
  - Operating-system junk: `.DS_Store`, `Thumbs.db`, `desktop.ini`, `*.tmp`, `*.ccsync-tmp`, each in two forms.
  - No yt-dlp lines and no Proxy lines.

## SFTP transfer limits on Synology
(source: common.py)

- **Applies only when the NAS kind is `synology`.**
  - A chunk size above 64 KiB is refused: `sftp_chunk_size '<x>' is above 64Ki: DSM's sshd silently truncates downloads over 514 MiB at that size`.
  - A chunk size that cannot be read is refused: `sftp_chunk_size '<x>' is not a size (use "64Ki")`.
  - A concurrency above 16 is refused: `sftp_concurrency <n> is above 16`.
  - When there is more than one problem, they are joined with `; `.
- **Blank values on Synology** are filled with `64Ki` and `16`. Values over the limit are never lowered silently; they are refused instead.
- **How sizes are read.** Accepted forms include `64Ki`, `64k`, `1M`, a plain number of bytes, and K, M, G or T. Every unit is binary (1024-based), and a trailing `i` or `b` is allowed.

## Resolve project-server (Postgres) password
(source: common.py)

- **Where it comes from.** `PG_PASSWORD`. Otherwise the file at `CCSYNC_PG_PASSWORD_FILE`, or by default `~/.ccsync/pg_password`.
- **If neither has one**, a random 32-character URL-safe value is generated once and saved to that file (permissions 0600, a no-op on Windows). Redeploys reuse it.
- **Refusal.** The value `davinci` in any letter case is refused, from any source: `the Postgres project-server password is Resolve's well-known default ('DaVinci'); anyone who can reach port 5432 would have a superuser. Unset $PG_PASSWORD and let this toolchain generate one, or choose your own.`

## Files created on the workstation
(source: common.py)

- `~/.ccsync/known_hosts`: SSH keys accepted on first use. Appended, permissions 0600.
- `~/.ccsync/known_certs.json`: API certificate fingerprints keyed `host:port`. Rewritten whole, permissions 0600.
- `~/.ccsync/snapshot_log.jsonl`: append-only record of snapshot attempts.
- `~/.ccsync/pg_password`: the generated Postgres password, permissions 0600.
- **Windows:** every chmod above silently does nothing, which these files allow for. No other differences between Windows, macOS and Linux exist in these two files.
  - The one Windows-specific text is the secret-warning hint naming `.\tools\load_secrets.ps1`, shown on every OS.

## Files created or changed on the NAS (directly by this code)
(source: common.py)

- `<project>/.ccsync-project`: written as root (see markers).
- Any file the caller passes to the SFTP upload: replaced in the SFTP view.
- Everything else on the NAS is changed by callers or backends, which are outside this part.

## Looks redundant or overlapping

- `truenas_rpc.py` exists twice, here and in the dashboard. A test pins the two byte-identical (`server/tests/test_truenas_rpc.py`).
- The ignore lists, the video extension list, the shared-asset defaults and the marker filename are copied in the dashboard and the companion, and kept in step by tests.
- There are two TLS-pin enforcement paths (the REST/DSM requests adapter and the WebSocket comparison), with two separate pin parsers that refuse with different messages.
- There are two TrueNAS transports (JSON-RPC and REST) with automatic fallback, a 300 s REST-only memory, and resetting of that memory on a 404. There are also two login generations for each authentication mode (`login_ex` plus the legacy `login` / `login_with_api_key`).
- Every NAS identity value has paired environment names: `TRUENAS_*` / `SYNO_*` for host, user, password, sudo password and TLS verification, and `DASH_NAS_*` / `TRUENAS_*` for transport and API path. The dashboard's `DASH_` names are honoured on the workstation and win.
- The same first-use flag and variable controls both SSH host-key trust and API certificate trust.
- `--site`, `--nas-kind` and `--trust-host-key-on-first-use` are each read both from argparse and from the raw command line.

## Claims the code does not back

- The `common.py` header says TrueNAS calls are "Python + `requests` for TrueNAS REST API". In fact JSON-RPC over a stdlib WebSocket is preferred, and REST is only a fallback.
- The same header says "Every credential comes from an environment variable". The Postgres password can come from, and is generated into, `~/.ccsync/pg_password`. Secret flags such as `--api-key` are still accepted, with only a warning.
- The `synology_verify_ssl` docstring says unset means "False (trust the self-signed DSM cert, the out-of-the-box state)". In fact unset means pin, record on first use, or refuse.
- The `truenas_api` docstring says it "Returns a requests.Response in real mode". On JSON-RPC it returns a lookalike object, with headers always empty.
- The `run_ssh` docstring says it runs "as TRUENAS_USER". `SYNO_USER` beats `TRUENAS_USER` on any NAS kind.
- The `confirm_destructive` docstring says the run is gated on a flag or a typed hostname. With no host configured it returns without asking.
- The strict snapshot refusal says `--require-snapshot was given` even when strict mode came from `CCSYNC_REQUIRE_SNAPSHOT` or a caller's own setting. The `cli()` docstring implies configuration errors are always one line, but a bad `--site` / `CCSYNC_SITE` path or invalid TOML is raised at import, before the wrapper runs, and shows as a traceback.
- The DSM comment about a named session implies the session is logged out. No logout is ever sent.
- The `truenas_rpc` docstring says "wait loops poll every 2 s". That is true of the job wait here, but other callers were not checked.

## Could not determine

- Snapshot names, retention and the actual snapshot API calls: these are in `backends/truenas.py` and `backends/synology.py`, outside this part.
- Whether the Synology backend is "ready", and its pending message.
- Which scripts call the version note, `confirm_destructive` (and with which flag name) and `snapshot_before`, and which secret flag each script passes to the command-line secret warning.
- Whether scripts catch the `ConnectionError` raised for JSON-RPC failures, or whether the operator sees a traceback.
- Whether the JSON-RPC login shapes work against a live TrueNAS. The module's own docstring says they were not verified live.

## Line ranges read

- `server/common.py`: lines 1 to 2506, all of it, in chunks 1-420, 420-869, 870-1318, 1319-1767, 1768-2166 and 2167-2506.
- `server/truenas_rpc.py`: lines 1 to 715, all of it, in chunks 1-360 and 360-715.
- As evidence only, I grepped `server/tests/test_truenas_rpc.py` (the byte-identical test) and the tree for callers of `warn_secret_on_argv`.

## Most likely bloat in this part

- Two TrueNAS transports, with fallback memory and a REST-404 reset.
- Duplicated JSON-RPC and DSM clients kept in step with the dashboard's copies.
- Legacy login fallbacks for each authentication mode.
- Pairs of environment variable names (`TRUENAS_*`, `SYNO_*` and `DASH_NAS_*`) for the same values.
- Raw command-line re-parsing of flags that argparse already parses.
