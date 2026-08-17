# API reference

The dashboard's HTTP API, and a pointer to the companion's loopback API.
Written 2026-08-17 (`COMMERCIAL_READINESS.md` item 13) against the code in
`dashboard/src/ccsync_dashboard/api.py`, `app.py` and `auth.py`. Where this
file and the code disagree, the code is right — and that is a bug report.

**Base path:** every route below is under `/api/v1` unless stated otherwise.
**Base URL:** whatever `[net] dashboard_url` says — a tailnet address, or a
Tailscale Serve `https://…ts.net` name.

There is deliberately **no** interactive `/docs` or `/openapi.json`: they are
blocked, on the dashboard and on both mounted SPAs.

---

## 1. Credentials

| Credential | Sent as | Who holds it | Notes |
|---|---|---|---|
| **Session** | `ccsync_session` cookie | a signed-in browser | HMAC token *plus* a server-side row; a cookie with no row is not a session |
| **Shared report token** | `X-CCSync-Token` | every deployed companion | `DASH_REPORT_TOKEN`. Identifies nobody — that is its weakness. Retire it with `DASH_SHARED_REPORT_TOKEN_ENABLED=0` |
| **Per-editor report token** | `X-CCSync-Token` | one editor's companion | shape `cce1.<id>.<secret>`, stored hashed, revocable individually, and **bound** to that editor |
| **Machine identity** | `X-CCSync-Identity` | one editor's companion | 30-day signed token from `POST /verify`. Proves *whose machine this is* |
| **CSRF** | `X-CSRF-Token` header or a `csrf` form field | browsers | required on cookie-authenticated `POST/PUT/PATCH/DELETE` |
| **Ingest** | `X-Ingest-Token` | the b-roll indexer | guards `/broll/api/ingest/*` only |
| **Loopback** | `X-CCSync-Loopback` | non-browser callers of the tray | see [`LOOPBACK_API.md`](LOOPBACK_API.md) |

A shape note that matters when you are debugging a 401: a per-editor token is
recognised **by shape first** and is never compared against the shared secret,
so a fleet mid-migration cannot have one accidentally accepted as the other.

### The gate

A middleware (`app.login_gate`) runs before routing. Everything not on the open
list needs a session; JSON paths get `401 {"detail": "login required"}` and
page paths get a redirect to `/login`.

**Open without any credential:**
`/api/v1/login`, `/api/v1/logout`, `/api/v1/me`, `/api/v1/health`,
`/api/v1/site`, `/api/v1/verify`, `/api/v1/report`, `/login`, `/favicon.ico`,
`/static/*`, and the two OIDC legs `/auth/oidc/login` and
`/auth/oidc/callback`.

`/report` and `/verify` are "open" only in the sense that the *gate* lets them
through — both authenticate inside, and `/report`'s token is checked **before
the body is read**.

**Open to a companion token instead of a session:**
`/api/v1/selection/*`, `/api/v1/companion/package/*`, `/broll/api/ingest/*`
(ingest token), `/ytdl/api/config/ytdl-client` (unauthenticated read by
design), and the ytdl fleet job routes.

### Body-size ceilings

Enforced in the middleware, from `Content-Length` *and* by counting bytes
(`Content-Length` is advisory for a chunked request):

| Route | Ceiling |
|---|---|
| `POST /api/v1/report` | 8 MB |
| `PUT /api/v1/admin/packages/…` | 200 MB |
| the music UI's ingest upload | 512 MB |

---

## 2. Open endpoints

### `GET /api/v1/health`

Liveness for anyone; detail only for authenticated callers.

Unauthenticated:

```json
{ "ok": true, "version": "0.4.1" }
```

With a session or a companion token, it also returns `syncthing_reachable`,
`collector_stale`, `folder_errors` and `last_polls` (per collector kind:
`finished_at`, `ok`, `error`).

**The status code stays 200 even when `ok` is false**, and that is load
bearing: release tooling polls this route after a deploy and the macOS
onboarding wizard uses it as its connection test, so a 503 for "Syncthing is
unreachable" would read as "the dashboard is down". The container healthcheck
parses `ok` out of the body.

### `GET /api/v1/site`

The site manifest — this deployment's non-secret facts, for clients that need
them *before* they have any credentials (the installer, the wizard, the
companion).

```json
{
  "schema": 1,
  "org_name": "", "org_short": "", "product_name": "CC Sync",
  "tree_name": "", "canonical_prefix": "P:\\",
  "remote_root": "", "smb_unc": "",
  "sftp_host": "", "sftp_port": 22,
  "sftp_chunk_size": "", "sftp_concurrency": 0, "sftp_shell_type": "",
  "rclone_remote": "", "nas_syncthing_id": "", "dashboard_url": "",
  "template_folders": ["…"],
  "shared_asset_folders": [{"id": "assets-luts", "rel": "Assets/Luts", "label": "…"}],
  "video_extensions": ["…"],
  "nas_kind": "truenas",
  "features": { "youtube_download": false, "youtube_unblock": false }
}
```

Rules a client can rely on:

- **Nothing secret is in here, ever.** A Syncthing device ID is a public key;
  every other value is an address the caller is about to be handed anyway. No
  user, project, path inventory or token may be added.
- **Blank means "not configured"**, never another site's value.
- `org_short` falls back to `org_name`, and both blank falls back to
  `product_name`.
- `nas_syncthing_id` prefers the **live** value read from Syncthing over the
  configured fallback, cached for the life of the process (a re-created
  Syncthing config regenerates the ID, and a stale one points every new editor
  at a device that no longer exists).
- `features.youtube_unblock` is never true on its own — it implies
  `youtube_download`.
- `schema` is a monotonic integer, not the dashboard version. Unknown keys are
  additive; a client that cannot read `features` must behave as if the feature
  is **off**.

### `POST /api/v1/login`

```json
{ "username": "…", "password": "…" }        →  { "ok": true, "user": "…", "is_admin": false }
```

Sets the session cookie. `401` bad credentials, `429` throttled (per-username
*and* per-IP, five failures in an hour then exponential backoff to 1h), `503`
if `DASH_SESSION_SECRET` is unset or the credential-probe pool is saturated.
The failure text is identical for every refusal on purpose — anything else is
a username/role oracle.

### `POST /api/v1/logout`

Revokes the server-side session, not just the browser's copy. Always
`{"ok": true}`.

### `GET /api/v1/me`

`{ "user": "…" | null, "is_admin": bool }`. The only "open" route that simply
reports who you are.

### `POST /api/v1/verify`

Companion bootstrap: the same credential check as login, returning a long-lived
signed identity token.

```json
{ "username": "…", "password": "…", "companion_version": "0.7.11", "platform": "windows" }
```
```json
{
  "ok": true, "username": "…",
  "token": "v2.identity.…",
  "report_token": "<the shared fleet token, or \"\">",
  "role": "editor",
  "upgrade": { "...": "present only when a different build is current" }
}
```

`role` is `base` for anyone in `DASH_ADMIN_USERS`, `editor` otherwise; the
companion uses it to choose its sync behaviour instead of trusting a
hand-edited local `mode`.

`403` if the account is not in the NAS `editors` group and not an admin — any
account the NAS's SMB service accepts would otherwise come back with a valid
identity **and** the shared report token. `503` when the NAS is configured but
unreachable (retryable, never open); with **no** NAS credentials configured at
all the check is skipped and logged, so a NAS-less lab deployment still works.

### `POST /api/v1/report`

The companion's status report — the busiest route in the product, and the only
channel the dashboard has back to a tray.

**Auth:** `X-CCSync-Token` (either kind) **and**, whenever
`DASH_SESSION_SECRET` is configured, a matching `X-CCSync-Identity`. A
per-editor token additionally must agree with `editor_name` in the body.

Request (abridged — `api.ReportIn`):

| Field | Notes |
|---|---|
| `editor_name`, `machine` | ≤ 64 / ≤ 128 chars; `machine` is whitespace-stripped because it is half of a primary key in four tables |
| `companion_version`, `platform`, `reported_at` | `platform` is `windows` or `macos`; anything else is offered no upgrade |
| `lanes[]` | ≤ 32; state, queued, transferring, errors, bytes, speed, ETA per lane |
| `completed[]` | ≤ 256 finished transfers, for the history panel |
| `queue[]`, `current_project`, `resolve_project` | the editor's ordered selection and what is open |
| `mode` | `base` or `editor` |
| `local_manifest`, `media_tree` | media presence; **absent leaves the tables untouched**, so a light report never wipes them |
| `transport_health` | direct-vs-relayed path, orphaned `.partial` counters |
| `sync_guard` | the alarms: a tripped lane B breaker, a halted machine, trash size, lane A "skipped, exists" |

Oversized sections are **sliced to the ceiling, not rejected** — a 422 used to
take the whole machine off the fleet grid. What was dropped comes back in
`truncated` and is logged on both sides.

Response:

```json
{
  "ok": true, "lanes": 3, "received_at": "…",
  "truncated": { "completed": 12 },
  "upgrade": { "version": "0.7.12", "url": "/api/v1/companion/package/windows/0.7.12",
               "sha256": "…", "size_bytes": 41234567, "kind": "companion",
               "platform": "windows", "filename": "…", "published_at": "…",
               "min_version": "0.7.0", "signed_binary": true,
               "signature": "…", "pubkey_id": "…" },
  "resolve_project_unmapped": "Some Project",
  "commands": { "halt": { "active": false, "reason": "", "at": null } }
}
```

- `upgrade` — **absent when up to date.** Present when a *different* version is
  current for that platform ("different, not newer", so a rollback is offered
  like any other update). The first four keys are exactly what companions in
  the field already parse; everything else was added beside them, never
  substituted.
- `resolve_project_unmapped` — echoes the **name**, not a bool, so the
  companion's prompt cannot race a project switch.
- `commands.halt` — **always present, in both states.** An absent key means
  "this dashboard is too old to have an opinion" and the companion holds
  whatever halt it has; `active: false` is what releases one.

---

## 3. Fleet reads

All of these are session-authenticated. All but the last are **scoped**: a
non-admin sees only their own rows, an admin sees the fleet and may focus one
editor with `?as=<editor>`.

| Route | Returns |
|---|---|
| `GET /projects` | `generated_at`, `syncthing_reachable`, `fleet_status`, `projects[]` (slug, label, path, `folder_state`, `folder_error`, status, editors, `need_bytes_total`, `editors_behind`), and a nested `tree` |
| `GET /projects/{slug}` | one project's detail. `404` for an unknown slug |
| `GET /transfers` | `transfers[]` in flight, `fleet_speed_bps`, `queues`, `queued_files`, `queued_bytes`, `history` (last 50 completions) |
| `GET /projects/{slug}/presence` | who has what, for one project |
| `GET /projects/{slug}/devices/{device_id}/missing` | the file paths missing from one named machine |
| `GET /editors` | the editor roster with lane state |
| `GET /project-roots` | the sticky Resolve-project-name → project-slug mappings. **Not scoped** — any signed-in user sees all of them; they are destinations, not per-person data |

`…/devices/{device_id}/missing` answers **404, not 403**, to a caller outside
its scope: it is the one route here that returns actual file paths, and an
editor has no business learning that another editor's device id exists.

---

## 4. Selection (which projects sync to whom)

| Route | Auth |
|---|---|
| `GET /selection/{editor}` | session (self or admin), **or** a companion token + a matching identity — or a per-editor token, which is itself the identity |
| `PUT /selection/{editor}/{slug}` | **session only** (self or admin) |
| `DELETE /selection/{editor}/{slug}` | session, **or** the companion credential above |

The asymmetry is deliberate. Ticking starts syncing data *to* a machine, so it
stays session-only; unticking is how the tray's "Remove this project from this
machine" works (a delete while ticked just errors the Syncthing folder), so a
machine may remove its own ticks.

Response shape:

```json
{ "editor": "…", "generated_at": "…",
  "project_roots": [ … ],
  "selection": [ { "slug": "…", "label": "…", "rel_path": "…", "position": 1, "active": true } ],
  "changed": true }
```

`changed` appears on the write routes only. Both writes nudge the collector so
sharing reconciles immediately instead of up to 60s later.

### `PUT /project-roots`

Sets or clears a sticky "this Resolve project name lives at this tree project"
mapping. **Tiered:** an editor may *first-set* an unmapped name that one of
their own machines has reported (first-write-wins); changing or deleting an
existing mapping is admin-only. Admins may first-set anything.

### `POST /projects` and `POST /projects/link`

Create a project directory in the tree (laying down the template folders and
the `.ccsync-project` marker) or adopt an existing bare folder. Any signed-in
user; `422` with a readable message on any refusal (a path escaping the tree,
a folder that already contains projects, and so on).

---

## 5. Admin

Every route here requires a session belonging to a user in `DASH_ADMIN_USERS`
(`401` if not signed in, `403` if signed in and not an admin).

### Users

| Route | What |
|---|---|
| `GET /admin/users` | editors, their devices, key status. The stack's own service account is filtered out |
| `POST /admin/users` | create/update a NAS editor account: `{username, ssh_pubkey, full_name, password?}` |
| `POST /admin/users/{username}/password` | set a known password (≥ 12 chars; refusals for uid < 1000 or non-`editors` live in the NAS backend) |
| `POST /admin/devices/approve` | approve a pending Syncthing device: `{username, device_id}` |

These need NAS credentials in the container (`DASH_NAS_PW`, or preferably
`DASH_NAS_API_KEY`). Without them this section — **and only this section** —
answers `503`. `502` means the NAS itself refused.

### Sessions

| Route | What |
|---|---|
| `GET /admin/sessions` | every live browser session. `sid` is truncated to 12 chars — it is a keyed digest and cannot be replayed, but there is no reason to publish it whole |
| `POST /admin/users/{username}/sessions/revoke` | sign that account out everywhere → `{"ok": true, "revoked": n}` |

### Per-editor report tokens

| Route | What |
|---|---|
| `GET /admin/report-tokens` | live tokens, plus `shared_machines` / `shared_count` / `editor_count` — the migration counter that tells you when `DASH_SHARED_REPORT_TOKEN_ENABLED=0` is safe |
| `POST /admin/report-tokens` | `{username, label?}` → `{"ok": true, "token": "cce1.…", "token_row": {…}, "view": {…}}` |
| `DELETE /admin/report-tokens/{token_id}` | revoke. `404` if there is no live token by that id |

**The secret appears in that one response and never again** — only a hash is
stored, so nothing could answer it a second time. Handing it to the editor is
deliberately not automated; use the channel you already use for their NAS
password.

### Fleet halt

| Route | Auth | What |
|---|---|---|
| `GET /fleet/halt` | any signed-in user, or a companion holding the shared report token | `{"halt": {"active": bool, "reason": "…", "set_at": "…"}}` |
| `POST /fleet/halt` | **admin** | `{"active": bool, "reason": "≤500 chars"}` |

Reading is wide on purpose: an editor whose tray says "your admin stopped
syncing" must be able to confirm it. The state is persisted and handed to every
companion on its next report reply, so it survives a dashboard restart *and*
reaches a machine that was offline when it was set. The companion refuses a
*local* release of a fleet halt, so one editor cannot opt out.

### Assignment matrix

| Route | What |
|---|---|
| `GET /admin/assignments` | every active project x every known editor, one page |

Not a new write surface: each cell is a plain browser `fetch` straight at
**§4's** `PUT`/`DELETE /selection/{editor}/{slug}`, acting as the editor named
in that cell's column rather than through `?as=`. `auth.can_manage` already
lets an admin session write any editor's selection either way, so a tick made
here is the identical row-level write the `?as=` editor switcher's checkboxes
make — same `created_by`, same collector nudge, same lane C share / lane A-B
scope / enforce-cycle consequences. There is no bulk-tick endpoint either:
"tick all" / "untick all" for a column replay that one write per project,
client-side.

`editors[]` on this page comes from `db.known_editor_usernames` — the same
evidence-based roster the `?as=` switcher uses (a known-editors row, a tick,
a stored pref, or a companion report) — never a guess, and never the admin's
own name unless the admin independently satisfies one of those.

### Packages (the upgrade channel)

| Route | What |
|---|---|
| `GET /admin/packages` | everything published, per platform and kind, with which is current |
| `PUT /admin/packages/{platform}/{version}` | publish. Body = **raw bytes** of the build (no multipart) |
| `POST /admin/packages/{platform}/{version}/current` | make current — also how you roll back |
| `DELETE /admin/packages/{platform}/{version}` | delete. `409` on the current version: make another current first |
| `GET /companion/package/{platform}/{version}` | download. Session **or** either companion token |

`platform` ∈ `windows`, `macos`. `kind` (query param, default `companion`) ∈
`companion`, `onboard` — the fleet must never be offered the onboarding
installer as a self-upgrade, since the client renames it over the running exe.
`version` must look like `1.2.3`.

Publish query parameters:

| Param | Meaning |
|---|---|
| `sha256` | **required**, 64 hex chars, verified server-side before anything becomes visible |
| `signature`, `pubkey_id`, `min_version`, `published_at`, `signed_binary` | from `tools/sign_release.py` |
| `make_current=1` | publish and promote in one call |
| `prune=1` | **opt-in** deletion of all but the current build and the two newest non-current ones. Off by default: publishing must not silently destroy rollback material |

Refusals worth recognising:

- **`503`** — `DASH_RELEASE_PUBKEYS` is unset (or holds only a placeholder like
  `REPLACE_ME`, which is filtered out because "no key configured" and
  "signature rejected" are very different bugs to chase).
- **`400`/`422` "unsigned publish REFUSED"** — publish tooling older than
  2026-08-17 cannot publish to a dashboard newer than it.

Downloads carry `X-CCSync-SHA256` and `X-CCSync-Signature` headers. Those exist
for the one client that cannot verify Ed25519 — `installer/macos_bootstrap.sh`,
a POSIX shell script doing a first install. It cannot check the signature, but
it *can* refuse a channel that has none.

Staging uses a per-request `.part` file plus `os.replace`, so the served file
is always complete and two concurrent publishes cannot write into each other's
staging file.

---

## 6. Non-`/api/v1` surfaces

| Path | What |
|---|---|
| `/` and `/partials/*` | the server-rendered UI (htmx fragments). Session-gated |
| `/login`, `/logout` | the HTML login/logout forms |
| `/auth/oidc/login`, `/auth/oidc/callback` | the two OIDC legs. Inert unless `DASH_AUTH_METHOD=oidc` — they answer 503 with the break-glass URL otherwise, and the callback authenticates on a signed flow cookie plus a verified `id_token`, never on being reachable |
| `/broll/*` | the b-roll SPA and its API. Ingest routes take `X-Ingest-Token` |
| `/music/*` | the music SPA and its API. The bare `/music` → `/music/` redirect is load-bearing |
| `/ytdl/*` | the downloader SPA, **only when the feature is on** |
| `/static/*`, `/favicon.ico` | assets |

The mounted SPAs are currently exempt from the CSRF check
(`app._CSRF_EXEMPT_PREFIXES`) because their `fetch()` calls do not send the
token yet; `SameSite=Lax` holds that line meanwhile. The token is already
published to them on the injected topbar (`data-csrf`), so the fix is a
frontend change plus deleting the prefix.

---

## 7. The companion loopback API

Separate service, separate trust model, separate document:
**[`LOOPBACK_API.md`](LOOPBACK_API.md)**.

Summary: one HTTP listener on `127.0.0.1:8899` inside the tray app
(`companion/src/ccsync_companion/broll_server.py`), with three route groups —
b-roll (`GET /status`, `POST /insert`), music (`GET /music/status`,
`POST /music/send`, `POST /music/reveal`) and ytdl (`POST /ytdl/reveal`,
`GET /ytdl/capabilities`, `POST /ytdl/download`, `GET /ytdl/progress`).
Callers get in with an **allow-listed `Origin`** or the **`X-CCSync-Loopback`**
token from `~/.ccsync/loopback-token`; everything else is 403 with no CORS
headers. Bodies name a `share` and a `rel_path`, never a filesystem path.

---

## 8. Error conventions

| Code | Means |
|---|---|
| `401` | no credential, or a bad one. Also what an out-of-scope *identity* claim gets |
| `403` | authenticated, not allowed (non-admin on an admin route; an account outside the `editors` group at `/verify`) |
| `404` | not found — **or** deliberately indistinguishable from not-found, on the one route that would otherwise confirm another editor's device exists |
| `409` | a state conflict (deleting the current package) |
| `422` | the request is malformed: a bad username, a non-`1.2.3` version, a path that escapes the tree |
| `429` | login/verify throttled |
| `502` | the NAS refused something the dashboard asked it to do |
| `503` | a dependency is not configured (`DASH_SESSION_SECRET`, NAS credentials, `SYNCTHING_GUI_URL`, `DASH_RELEASE_PUBKEYS`) or is momentarily saturated |

Error bodies are `{"detail": "…"}`. Detail text on **open** routes is
deliberately generic — a `NasError`'s text names the NAS host and its API path,
and `/verify` is reachable by anyone who can reach the port, so the specifics
go to the log instead.

---

## See also

- [`ARCHITECTURE.md`](ARCHITECTURE.md) — how the pieces fit
- [`CONFIG.md`](CONFIG.md) — every env var named above
- [`../dashboard/README.md`](../dashboard/README.md) — the deep dive on auth
- [`LOOPBACK_API.md`](LOOPBACK_API.md) — the tray's own API
