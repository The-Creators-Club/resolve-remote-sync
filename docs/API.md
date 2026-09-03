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
| **Machine identity** | `X-CCSync-Identity` | one editor's companion | non-expiring signed token from `POST /verify` (CR-86; 30-day before 2026-08-27). Proves *whose machine this is* |
| **CSRF** | `X-CSRF-Token` header or a `csrf` form field | browsers | required on cookie-authenticated `POST/PUT/PATCH/DELETE` |
| **Ingest** | `X-Ingest-Token` | the b-roll indexer | guards `/broll/api/ingest/*` only |
| **Loopback** | `X-CCSync-Loopback` | non-browser callers of the tray | see [`LOOPBACK_API.md`](LOOPBACK_API.md) |
| **Internal bearer** | `Authorization: Bearer …` | the sftp sidecar | `CCSYNC_INTERNAL_TOKEN`, guards `/internal/sftp/*` only (§5b) |

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
`/static/*`, `/setup` and `/api/v1/setup/*` (the wizard; the page and the
engine routes re-check admin-or-first-run inside), the two OIDC legs
`/auth/oidc/login` and `/auth/oidc/callback`, and the two first-admin
bootstrap routes `/api/v1/setup/status` and `/api/v1/setup/admin` (§5a).
`/internal/sftp/*` (§5b) is open on a different basis entirely — it is not
reachable by a browser at all in practice, gated on its own bearer token
rather than the session.

`/report` and `/verify` are "open" only in the sense that the *gate* lets them
through — both authenticate inside, and `/report`'s token is checked **before
the body is read**. `/setup` and `/api/v1/setup/*` are the same shape: open at
the middleware, but every route (and `ui.page_setup`) re-checks via
`setup_routes.require_setup_access`/`first_run_open`, which is fail-closed —
see §5's "Setup wizard" for what that means today.

**Open on a link token instead of a session:** `/broll/share/*` — a client
folder's public viewer (`docs/CLIENT_FOLDERS.md`). The 128-bit token in the
path is the credential; the b-roll app re-checks it (and clip membership) on
every request, revoked/expired is a 404, and nothing under it writes. It is
the ONE prefix an operator publishes past the tailnet (Tailscale Funnel on its
own port), which is why it must stay exactly `/broll/share/`.

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
`collector_stale`, `folder_errors`, `last_polls` (per collector kind:
`finished_at`, `ok`, `error`) and `code`:

```json
{ "code": { "running": "0.5.1", "image": "0.5.0",
            "source": "volume", "runtime_id": "9f2c…" } }
```

`code` says WHICH code is live (`ZERO_TOUCH_PLAN.md` WP K, 2026-08-18):
`running` is this process's `VERSION`, `image` is the version baked into the
container image, `source` is `image` | `volume` | `checkout`, and `runtime_id`
is the image's `/venv/.runtime-id` (empty in bind-mount mode). **`ok` and
`version` are unchanged** and stay where they are: release tooling, the
onboarding wizard and the container healthcheck read those two and nothing
else.

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
  "brand_logo": "",
  "tree_name": "", "canonical_prefix": "P:\\",
  "remote_root": "", "smb_unc": "",
  "sftp_host": "", "sftp_port": 22,
  "sftp_chunk_size": "", "sftp_concurrency": 0, "sftp_shell_type": "",
  "rclone_remote": "", "nas_syncthing_id": "", "dashboard_url": "",
  "template_folders": ["…"],
  "shared_asset_folders": [{"id": "assets-luts", "rel": "Assets/Luts", "label": "…"}],
  "video_extensions": ["…"],
  "nas_kind": "truenas",
  "release_feed_base": "",
  "features": { "youtube_download": false, "youtube_unblock": false },
  "indexer": { "model_tier": "good" }
}
```

Rules a client can rely on:

- **Nothing secret is in here, ever.** A Syncthing device ID is a public key;
  every other value is an address the caller is about to be handed anyway. No
  user, project, path inventory or token may be added.
- **Blank means "not configured"**, never another site's value.
- `org_short` falls back to `org_name`, and both blank falls back to
  `product_name`.
- `brand_logo` names the mark this fleet's companions wear in the tray and in
  window title bars (2026-08-18) — a bare filename means "the asset in your
  build", anything with a separator is a path on the editor's own machine.
  Blank is the vendor default: wear the product's mark, never the last
  tenant's. A client resolves it env-first (`$CCSYNC_BRAND_LOGO`), and treats
  a name it cannot find as blank rather than as an error.
- `nas_syncthing_id` prefers the **live** value read from Syncthing over the
  configured fallback, cached for the life of the process (a re-created
  Syncthing config regenerates the ID, and a stale one points every new editor
  at a device that no longer exists).
- `features.youtube_unblock` is never true on its own — it implies
  `youtube_download`.
- `indexer.model_tier` (2026-08-18) is `good` or `best` — which LOCAL vision
  model the b-roll indexer loads, chosen on Settings by the indexing
  machine's VRAM. A NEW top-level object, same convention as `features`; an
  indexer too old to read it defaults to `good` itself. See `CONFIG.md`
  `[indexer]`.
- `release_feed_base` (2026-08-18) is where this fleet's vendor artefacts
  live: the configured `DASH_RELEASE_FEED_URL` **minus its filename**, or ""
  when no feed is configured (or the URL is not https). It exists because the
  companion fetches the CLAP audio model for music ingest from there
  (`docs/MUSIC_INGEST_PLAN.md` step 3, `docs/RELEASE_FEED.md` §6) and no
  vendor host may be written down in the repo -- the same rule that keeps a
  customer's name out of it. Not a credential: the feed is world-readable
  static files, and every byte a client takes from it is signature- or
  sha256-verified afterwards. Blank means "this fleet cannot fetch models",
  which every client reads as a refusal with a fix, not an error.
- `schema` is a monotonic integer, not the dashboard version. Unknown keys are
  additive; a client that cannot read `features` must behave as if the feature
  is **off**.
- Since `ZERO_TOUCH_PLAN.md` WP D (2026-08-17): every field except
  `video_extensions` is resolved **DB-first** (`site_settings` table, editable
  from Settings) with the `DASH_SITE_*` environment value as the fallback —
  see `CONFIG.md` §1.1. The response shape and every rule above is unchanged;
  only where the value comes from can now be "an admin typed it in", not just
  "the compose file said so".

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
| `proxy_coverage` | `proxy_gen.coverage()`: `state`, `missing`, `left`, plus the per-project map and history. Only `missing`/`state`/`left` are stored (schema v20) |
| `youtube_import` | `youtube_import.status()`: whether the clips the dashboard downloaded reached the editor's Resolve |
| `broll_ingest` | one local b-roll indexing batch (below) |
| `music_ingest` | one local MUSIC indexing batch: the same fields plus `kind: "music"` |

`proxy_coverage` and `youtube_import` were **undeclared until 2026-08-18**, so
pydantic's `extra="ignore"` silently dropped both on every tick since their
features shipped; declaring them is what put the missing-proxy count on the
fleet grid.

`broll_ingest` (`BROLL_INGEST_PLAN.md` §1 step 8) is scalars only, all
optional, and **omitted entirely when there is no batch** — the absence is how
"finished" is spelled, and `machine_state.ingest_active` returns to 0 on any
report that lacks it:

```json
"broll_ingest": {
  "active": true, "batch_uid": "<32 hex>", "state": "running", "gate": "",
  "done": 12, "failed": 1, "total": 40, "clip": "A001_C003.MP4", "percent": 55,
  "tier": "good", "run_mode": "idle", "uploading": true, "upload_paused": false,
  "model_download_percent": null, "warning": "", "at": "2026-08-18T09:59:30+00:00"
}
```

`warning` is the insufficient-VRAM refusal ("Best needs 12 GB VRAM, this GPU
has 8 GB — choose Good"). It shows on the fleet grid **even when `active` is
false**: the batch the editor asked for is not happening, and their own tray
is otherwise the only place that says so.

`music_ingest` (2026-08-18, `MUSIC_INGEST_PLAN.md` step 3) is the same shape
with `kind: "music"`, an always-empty `tier` (music has one model), and a
`clip` that is a track name. It is a **second section, not a reuse of the
first**, and it lands in its own `machine_state.music_ingest_*` columns
(schema v21) because both can be true at once: music needs no GPU, so a
machine can be embedding an album while it indexes a camera card, and one
section could only ever describe one of them. Its `warning` is a model refusal
("this fleet has no release feed configured…") and shows on the grid on the
same terms.

Oversized sections are **sliced to the ceiling, not rejected** — a 422 used to
take the whole machine off the fleet grid. What was dropped comes back in
`truncated` and is logged on both sides. The three diagnostic sections above go
one step further: one that cannot be parsed **at all** is dropped with a
warning in the dashboard log, and the rest of the report is accepted.

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
  "commands": { "halt": { "active": false, "reason": "", "at": null },
                "broll_ingest": { "cancel": ["<32 hex>"] },
                "music_ingest": { "cancel": ["<32 hex>"] } }
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
- `commands.broll_ingest` — **present only when there is something to
  cancel** (≤ 16 batch uids). Unlike `halt`, an empty list is not an
  instruction, and this reply rides every tick of every machine. It is a
  best-effort shortcut: the authoritative stop is the 410 the companion gets
  from its next ingest heartbeat, and every failure to reach the b-roll
  database here — absent checkout, unmigrated schema, unreadable file —
  answers "nothing to cancel" rather than failing the report.
- `commands.music_ingest` — the same thing for a music batch, on the same
  terms and with the same best-effort rules, read from `music.db`. Two
  separate keys because one editor can be running one of each, and a cancel
  must reach the orchestrator it was meant for.

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

## 4. Selection (which projects sync to which computer)

| Route | Auth |
|---|---|
| `GET /selection/{editor}?machine=` | session (self or admin), **or** a companion token + a matching identity — or a per-editor token, which is itself the identity |
| `PUT /selection/{editor}/{slug}?machine=&mode=` | **session only** (self or admin). `mode` is `full` (default) or `upload_only` (docs/UPLOAD_ONLY_TICK.md): the same PUT on a tick in the other mode switches it (`changed: true`); anything else is a 400. Every item of the `GET` carries `sync_mode` |
| `DELETE /selection/{editor}/{slug}?machine=` | session, **or** the companion credential above |
| `POST /projects/{slug}/move` `{path, to_slug?, to_path?}` | admin session. Moves a file or folder on the server (proxies with it) and queues `commands.file_moves` for every machine that has to follow (docs/FILE_MOVES.md); `GET /projects/{slug}/moves` lists the outcomes |
| `POST /admin/machines/{editor}/{machine}/copy-plan?source=` | admin session |
| `POST\|DELETE /admin/machines/{editor}/{machine}/update` | admin session |
| `DELETE /admin/machines/{editor}/{machine}` | admin session. Remove ONE computer (CR-76): its Syncthing device and shares first, then its plan, prefs, status and manifest rows. The unassigned bucket and the person's account and tokens are untouched, so a companion still running there registers it again on its next report (the response `note` says so). `404` unknown machine; `502`, nothing removed, when Syncthing could not be asked |

**`?machine=` (2026-08-18, `docs/MULTI_MACHINE_PLAN.md`).** The plan belongs
to a computer, so every route above takes one. Omitting it means the PERSON,
and each verb reads that the safe way: `GET` returns the **union** of their
computers' plans (what a companion too old to name itself gets, and for a
one-machine editor exactly their plan), `PUT` ticks it on **every** computer
they have, and `DELETE` removes it from **all** of them including the
unassigned bucket — under-sharing is the safe direction for a removal, and
"stop syncing this" must not leave it running on their other machine. The
value is a hostname (`machine` in the report payload), never the minted
`machine_id`.

`copy-plan` gives one computer another's plan verbatim (a new machine starts
EMPTY on purpose). The `update` pair is the pushed upgrade: it records a
version that rides `commands.upgrade` on that machine's next report, and the
companion applies it only if the signed offer it already holds is that
version — see §9 of the plan.

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
| `GET /admin/users` | editors, their devices, key status. The stack's own service account is filtered out. Response gains `auth_method` and `local_users` (WP C, below) |
| `POST /admin/users` | `DASH_AUTH_METHOD=local`: create a **local account** — `{username, password?, role?, ssh_pubkey?}`. Otherwise: create/update a NAS editor account — `{username, ssh_pubkey, full_name, password?}` |
| `POST /admin/users/{username}/password` | local mode: `{password}` sets it directly. Otherwise: set a known NAS password (≥ 12 chars; refusals for uid < 1000 or non-`editors` live in the NAS backend) |
| `POST /admin/users/{username}/disable` | **local mode only** (`400` otherwise): `{disabled: bool}` |
| `POST /admin/users/{username}/keys` | **local mode only**: add an SSH key — `{key_text, label?}` → `{"fingerprint": "SHA256:…"}` |
| `DELETE /admin/users/{username}/keys/{fingerprint}` | **local mode only**: revoke a key |
| `DELETE /admin/users/{username}` | delete a person **everywhere** (CR-76, 2026-08-24; every mode). Goes, in this order: the account (local row, or the NAS account through the backend's `delete_editor`, behind the same refusals `POST /admin/users` has), every one of their computers' records, their Syncthing devices and shares, then browser sessions and per-editor report tokens. Kept: `lane_report_history`, `transfer_history`, the tree itself, and whatever is on their computers. Response `deleted` carries `machines`, `devices_removed`, `sessions_revoked`, `report_tokens_revoked`; `warnings` names the home directory's fate (TrueNAS keeps it, DSM removes it). A username the fleet knows but no backend has an account for is deletable too. `404` unknown everywhere; `409` for the lockout guards (the account you are signed in as; local mode's last enabled admin); `502` when Syncthing or the NAS could not be asked, and the detail says what was and was not done — a Syncthing failure means **nothing** was deleted, because a device left behind would be unmapped and keep its shares forever (B16). `DISABLE` is the non-destructive button |
| `POST /admin/devices/approve` | approve a pending Syncthing device: `{username, device_id}` — unchanged, Syncthing device approval is independent of which auth method identifies editors |

The NAS-account rows above need NAS credentials in the container
(`DASH_NAS_PW`, or preferably `DASH_NAS_API_KEY`); without them the NAS half
of this section answers `truenas_configured: false` (no longer a `503` — see
below). `502` means the NAS itself refused.

**Local accounts (WP C, `docs/ZERO_TOUCH_PLAN.md` §3.3, 2026-08-17).**
`DASH_AUTH_METHOD=local` moves editor identity into the dashboard's own
`users`/`user_ssh_keys` tables — no NAS credential of any kind. `GET
/admin/users` always includes `"auth_method"` and, in local mode,
`"local_users": [{"username", "role", "created_at", "disabled",
"must_change_password", "ssh_keys": [{"fingerprint", "label", "added_at"}]}]`
— this is populated **even when no NAS backend is configured at all**, which
is the appliance's default shape. Creating a local user with no `password`
generates a one-time one, returned exactly once as `"generated_password"` in
the create response — nothing stores the plaintext anywhere it could be shown
again.

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

### The dashboard's own code updates

`ZERO_TOUCH_PLAN.md` WP K, 2026-08-18. Admin session + CSRF, like everything
else that changes what runs. See `docs/RELEASE_FEED.md` §2.1a for the record
and `docs/DOCKER.md` for what happens on disk.

| Route | What |
|---|---|
| `GET /admin/dashboard-update` | the status view below |
| `GET /admin/dashboard-update/status` | the same body; the progress panel polls it once a second |
| `POST /admin/dashboard-update/apply` | `{version, force}` — starts the update on a worker thread |
| `POST /admin/dashboard-update/rollback` | `{to_version, restore_db}` — swap back, optionally restoring a named backup |

The status body:

```json
{
  "image_mode": true, "running": "0.5.0", "image": "0.5.0",
  "source": "image", "runtime_id": "9f2c…",
  "current": {"version": "", "previous": "", "applied_at": "", "reverted_reason": ""},
  "code_updates":    [{"version": "0.5.1", "size_bytes": 982575,
                       "published_at": "…", "notes": "…", "runtime_id": "9f2c…"}],
  "runtime_updates": [{"version": "0.6.0", "...": "built against another image"}],
  "nas_hint": "Apps > ccsync > Update",
  "in_progress": false, "step": "idle", "message": "", "last_error": "",
  "backups": [{"name": "20260818T1200Z-before-0.5.1", "created_at": "…",
               "from_version": "0.5.0", "databases": ["dashboard"], "size_bytes": 1234}],
  "boot_attempts": 0
}
```

`code_updates` can be applied from here; `runtime_updates` cannot (they need a
new image) and carry the platform's own click in `nas_hint`. Every refusal
`apply` can answer with, and what it means:

| Status | Refusal |
|---|---|
| `400` | the version is not dotted-numeric (it names a directory), or the record's `url` is not https, or the downloaded bundle failed a check |
| `404` | no verified `dashboard` record for that version in the last feed check — run **Check now** first |
| `409` | bind-mount mode (this deployment updates from the base rig); another apply in flight; the version is already running; it is a **runtime** update; a ytdl job is running (pass `force`) |
| `500` | `/data/code` is not writable, or the staged code's checks could not be run |
| `507` | not enough free space on the data volume (the message names both numbers) |

`apply` returns as soon as preflight passes; the work continues on a worker
thread and the process exits 75 when it is done, which `deploy/run.sh` turns
into a re-exec on the new tree. Poll `/status` while `in_progress`, then
`/api/v1/health` until the new `version` answers.

### Site settings

`ZERO_TOUCH_PLAN.md` WP D, 2026-08-17 — the manifest as writable data
(`CONFIG.md` §1.1, `ARCHITECTURE.md` §6).

| Route | What |
|---|---|
| `GET /admin/site` | the resolved manifest (same shape `GET /api/v1/site` publishes, plus `auto_derived`: which keys are read-only in the UI right now because a live value exists) |
| `PUT /admin/site` | `{"values": {"org_name": "…", "sftp_port": "2222", …}}` → the resolved manifest. **All-or-nothing**: every field is validated before any is written, so one bad field changes nothing. `422` names the field and why |
| `GET /admin/site/export` | `site.toml`-shaped `text/plain`, section names matching `site.example.toml` |
| `POST /admin/site/import` | `{"text": "…"}` — parses pasted `site.toml`-shaped text (stdlib `tomllib`) into the same validated write `PUT` uses. Unrecognised `[section]`s are ignored, not refused (an import is additive to what this store owns) |

Values are always strings on the wire (`"1"`/`"0"` for the two boolean
`features.*` keys, comma-joined for `template_folders` and
`shared_asset_folders`) — `site_store.validate()` is the one place that
decides a value is acceptable, so the API and the Settings page form can
never disagree about what is valid.

### AI providers

`ai_providers.py`, 2026-08-18 — which AI answers `/ytdl`'s two calls, and
where its credentials live ([`CONFIG.md`](CONFIG.md) §2.5a). Admin-only, CSRF
like every other cookie-authenticated write.

| Route | What |
|---|---|
| `GET /admin/ai-providers` | every provider in **chain order** (`claude_code`, `anthropic_api`, `codex`, `openai_api`, `deepseek_api`) with `rank`, `status`, `available`, a **masked** key and its source; plus `preference`, `cli_enabled`, `cli_tos_note` and `resolved` (`{name, label, reason, pinned}`) |
| `PUT /admin/ai-providers/{name}/key` | `{"key": "sk-…"}` → the same snapshot. `400` for a CLI provider (it has no key), `409` when the environment sets that key (it always wins), `422` for a blank/spaced/control-character value, `404` for an unknown provider |
| `DELETE /admin/ai-providers/{name}/key` | forget a stored key → the snapshot |
| `PUT /admin/ai-providers/{name}/path` | `{"path": "/usr/local/bin/claude"}` — **CLI providers only** (`400` otherwise); blank clears it back to the wizard's install, then a `PATH` search. A typed path **wins** over anything the wizard installed |
| `POST /admin/ai-providers/{name}/test` | one tiny live call → `{"ok": bool, "detail": "…"}`. A model-list request for the API providers, the login probe for a CLI. Never 500s, never echoes the key |
| `PUT /admin/ai-providers/preference` | `{"preference": "auto"｜"<name>"}` → the snapshot. A pin that is not available is a **refusal** (`resolved.name` is `""`), never a fall-through to the next provider |

**No key is ever in a response, a query string, a log line or
`GET /api/v1/site`.** The stored value goes exactly one place: the mounted
ytdl app, in-process, through a callback it invokes per AI call.

`status` is one of `available`, `not_configured`, `not_installed`,
`not_signed_in`, `disabled_by_site`, `unknown`. The last two are CLI-only:
`disabled_by_site` means `[features] ai_cli_providers` is off, in which case
the CLI is **not probed at all** — no subprocess runs.

### AI CLI setup wizard

`cli_tools.py`, 2026-08-18 — install the publisher's build and sign it in from
the page, because "install it on the dashboard host" assumes a shell an
appliance customer does not have ([`CONFIG.md`](CONFIG.md) §2.5a). Admin-only
and CSRF-gated like everything above; `{name}` is `claude_code` or `codex` and
anything else is a `404`.

| Route | What |
|---|---|
| `GET /admin/ai-providers/{name}/setup` | everything the stepper needs in one poll, and **no subprocess**: `{tool, label, publisher, supported, unsupported_detail, cli_enabled, notice{title,text,checkbox}, install{…}, signin{…}, signed_in, home, modes[]}` |
| `POST /admin/ai-providers/{name}/install` | install (or update to) the publisher's latest build, on a background thread → the first status. `409` while another install runs or while `ai_cli_providers` is off, `400` on a host the wizard cannot install for (not Linux, musl, unknown arch, unwritable data volume) |
| `GET /admin/ai-providers/{name}/install-status` | `{state: idle｜running｜done｜error, step, version, bytes, total, percent, error, checksum_source, installed, installed_version, installed_at, installed_sha256, unverified}` |
| `DELETE /admin/ai-providers/{name}/install` | delete the tree **and the sign-in with it** (the credential lives in the `$HOME` inside it) and the stored OAuth token |
| `POST /admin/ai-providers/{name}/signin` | `{"mode": "subscription"｜"console"}` → starts the pty login and answers as soon as the CLI prints its URL: `{state, url, user_code, strategy, detail, account, expires_in}`. `400` when nothing is installed, when the dashboard is not on Linux, `409` when a sign-in is already open |
| `GET /admin/ai-providers/{name}/signin` | the same object. `state` walks `starting → awaiting_url → awaiting_code｜awaiting_browser → verifying → signed_in｜failed｜cancelled` |
| `POST /admin/ai-providers/{name}/signin/code` | `{"code": "…"}` → written to the CLI's pty. **In the body, never a query string, and never logged** |
| `POST /admin/ai-providers/{name}/signin/cancel` | kill the child, free the slot |
| `DELETE /admin/ai-providers/{name}/signin` | sign out: the CLI's own logout, plus the stored token, best-effort in that order so the credential goes even if the binary is gone |

One install and one sign-in at a time, process-wide: these are 100-330 MB
downloads onto a NAS that is also serving footage, and two pty children would
be two writers in one `$HOME`. The sign-in times out after 5 minutes and the
child is killed. Nothing in any of these answers carries the code, the OAuth
token or an unmasked email (`a…x@example.com`).

### Setup wizard

Behind `/setup`. Unlike every other route in this section, these are reachable
**without a session** in one narrow window: no local admin account exists yet
and auth is not OIDC (reported by the identity module `ZERO_TOUCH_PLAN.md` WP
C adds; until it lands, every route below is admin-only, fail-closed — see
`setup_routes.require_setup_access`).

| Route | What |
|---|---|
| `GET /setup/tasks` | every registered task: `id, title, description, optional, can_run, run_label, status, detail, at`, plus `outstanding_required` (task ids gating the wizard) |
| `POST /setup/tasks/{id}/check` | re-inspect the world, save and return the new state. Runs off the event loop (`run_in_threadpool`) |
| `POST /setup/tasks/{id}/run` | perform the task's action. `400` if it has none (e.g. `admin` — account creation is `POST /setup/admin`, WP C's route, not this one) |
| `POST /setup/tasks/{id}/skip` | `400` unless the task is `optional` |
| `GET /setup/eula` | `{"text": "…", "version": "1.0"}` — `""`/`null` if no EULA is shipped in this build |
| `POST /setup/eula` | records acceptance of the current marker version |

One task, one id, one lock: two concurrent `run` calls for the same task id
serialise; different task ids never block each other. Every task's state
survives a container restart (`setup_tasks` table) — the wizard resumes,
never restarts.

`run_label` (added 2026-08-18) is what the button says: `DO IT` for a task
that changes something, `CHECK NOW` for `software`, whose action is a poll of
the vendor feed. Clients render it and need not know the default.

**The eleven tasks and what each `check` looks at** (`setup_engine.py`). Every
one of them catches everything and answers `todo`/`warn`/`fail` with one line
naming the next action; a check never raises past `run_check`:

| id | required? | `ok` when |
|---|---|---|
| `eula` | yes | the shipped `EULA.md` marker version has been accepted (or no EULA is in this build) |
| `admin` | yes | somebody can administer this dashboard: under `DASH_AUTH_METHOD=local` a local admin row exists; otherwise `DASH_ADMIN_USERS` (or an OIDC admin claim) names one. **A NAS-auth site is `ok` with no local account at all** |
| `studio` | yes | `org_name`, `tree_name`, `canonical_prefix` and `template_folders` are all set in the site manifest |
| `storage` | yes | the tree is mounted and the shared asset folders exist |
| `secrets` | yes | all five secrets are in the environment or `<data>/secrets/` |
| `syncthing` | yes | the configured Syncthing answers with a device id |
| `done` | yes | every required task above is `ok` |
| `tailnet` | no | the bundled Tailscale node's LocalAPI (`TS_SOCKET`, read only if the socket file exists) reports `BackendState=Running`; else the published `dashboard_url` is a `*.ts.net` name or a `100.64.0.0/10` address |
| `nas_connect` | no | a NAS credential is configured and the NAS answers within 3s (detail = kind, and version/hostname where the backend can say) |
| `snapshots` | no | the NAS holds a periodic snapshot task (TrueNAS `pool.snapshottask`; DSM cannot be asked, see `BACKUP_RESTORE.md`) **or** `/data/backups/` holds an export under 7 days old |
| `editors` | no | at least one editor is known (`known_editors` and, under local login, `role='editor'` accounts) |
| `software` | no | a **current** companion package exists for `windows` **and** `macos`; `warn` for one of the two |

---

## 5a. First-admin setup (WP C, `docs/ZERO_TOUCH_PLAN.md` §3.3/§3.5)

Two routes, `setup_api.py`, both in `app.py`'s open list (no session needed —
that is the whole point of a first-run wizard):

| Route | What |
|---|---|
| `GET /api/v1/setup/status` | `{"auth_method": "…", "users_exist": bool}`. Non-`local` methods always report `users_exist: true` (there is no local-admin step to show) |
| `POST /api/v1/setup/admin` | `{username, password}` → creates the **first** local admin and logs it in (same cookie as `/login`) |

`POST /api/v1/setup/admin` is safe to leave open: it refuses `403` outside
`DASH_AUTH_METHOD=local`, and `409` the instant one local account exists —
checked inside an explicit transaction so two concurrent submits cannot both
win. This is the exact contract the Setup wizard calls; do not change the
path or body shape without updating it.

## 5b. Internal SFTP identity (WP C)

`internal_sftp.py`, prefix `/internal/sftp` — **not** under `/api/v1` and
**not** behind the session. This is what the sftp sidecar's
`AuthorizedKeysCommand` and user-listing step call; the sidecar is a separate
container with no cookie jar, so the gate is a bearer token instead of a
login:

| Route | What |
|---|---|
| `GET /internal/sftp/users` | `{"users": [{"username", "uid", "gid"}, …]}` — every enabled local account (role `admin` or `editor`) that holds at least one SSH key. `uid`/`gid` are this process's own ids (or `APP_UID`/`APP_GID` if set) — SFTP is a **single service account**, not per-editor NAS accounts |
| `GET /internal/sftp/keys/{username}` | `text/plain`, one `authorized_keys` line per key. `404` for an unknown or disabled user |

**Auth:** `Authorization: Bearer <token>`, compared with `hmac.compare_digest`.
The token is `CCSYNC_INTERNAL_TOKEN`, or — when that is unset — the file
agent D's SetupEngine generates at `<data dir>/secrets/internal_token` (read
fresh on every call, never cached, never written by this module). Neither
configured → `503 "internal token not configured"`. Every refusal is logged
with the caller's peer address. sshd's own `Match`/chroot block is what
restricts the resulting session — this endpoint does not prefix keys with
`restrict,`/`command=`, since that would be the dashboard silently
overriding the sidecar's own `sshd_config` rather than the sidecar owning
its policy.

---

## 6. Non-`/api/v1` surfaces

| Path | What |
|---|---|
| `/` and `/partials/*` | the server-rendered UI (htmx fragments). Session-gated |
| `/partials/topbar` | the one header, fetched and injected by the three SPAs. Since 2026-08-18 it carries the left nav drawer (HTML popover, no script: `innerHTML` would never run one) and, for admins, the settings gear |
| `/admin/settings`, `/admin/users`, `/admin/assignments`, `/setup`, `/admin/packages` | the Settings hub. Admin-only except `/transfers`, which editors may open. `/admin/packages` is **new on 2026-08-18**: the packages table, the vendor feed and this dashboard's own update, which used to be the bottom of `/admin/users` |
| `/download`, `/download/{platform}` | the drawer's `[ INSTALLER ]` entry (2026-08-18): the click IS the download. `/download` 303s to this browser's package for a Windows or macOS User-Agent, and renders `/installer`'s two-platform chooser when the UA names neither -- it no longer guesses Windows for anything unrecognised. `/installer` is that chooser on its own URL; it is not a hub page |
| `/login`, `/logout` | the HTML login/logout forms |
| `/auth/oidc/login`, `/auth/oidc/callback` | the two OIDC legs. Inert unless `DASH_AUTH_METHOD=oidc` — they answer 503 with the break-glass URL otherwise, and the callback authenticates on a signed flow cookie plus a verified `id_token`, never on being reachable |
| `/broll/*` | the b-roll SPA and its API. Ingest routes take `X-Ingest-Token`; the ingest **panel** and **fleet** routes are §6a. `/broll/api/client-folders` is the client-folder curation API (session, identity-stamped like §6a's panel; the public base URL is admin-only) |
| `/broll/share/{token}/…` | a client folder's **public** viewer (`docs/CLIENT_FOLDERS.md`, 2026-08-18): the page, `api/folder`, `api/videos/{id}`, `media/{proxy,sprite,poster}/{id}` and `../assets/*`. No session — the token is the credential; read-only; one 404 for revoked, expired and unknown |
| `/music/*` | the music SPA and its API. The bare `/music` → `/music/` redirect is load-bearing |
| `/ytdl/*` | the downloader SPA, **only when the feature is on** |
| `/static/*`, `/favicon.ico` | assets |

`/ytdl`'s own SPA API is session-gated, same-origin and deliberately not part
of `/api/v1`; it is documented with the feature (`ytdl/web/DEPLOY.md`). The job
row a browser polls carries, besides the phase and the counters: `kind`
(`search` | `urls`), `mode` (`visuals` | `news` -- which rubric the two AI calls
ran under, 2026-08-18), `shot_types` (the ticked boxes, as a list),
`max_candidates`, `term_scope` (`both` | `en` | `zh` | `exact` -- which
languages the search ran in, or the editor's text alone with no AI expansion,
2026-08-25) and `date_from` / `date_to` (an upload-date range as `YYYYMMDD`,
or null; accepted as ISO `YYYY-MM-DD` on create). All of them are inputs to the
search that already ran and none is updatable afterwards; `mode`, `shot_types`,
`term_scope` and the dates are validated on create (400 on an unknown value, a
non-calendar date or a reversed range, never silently defaulted) and a row
written before a column existed reads as what it actually ran with. The **fleet** job routes the
companion calls are §1's gate plus `docs/YTDL_LOCAL_DOWNLOAD.md` §4.

The mounted SPAs are currently exempt from the CSRF check
(`app._CSRF_EXEMPT_PREFIXES`) because their `fetch()` calls do not send the
token yet; `SameSite=Lax` holds that line meanwhile. The token is already
published to them on the injected topbar (`data-csrf`), so the fix is a
frontend change plus deleting the prefix.

---

## 6a. B-roll ingest — `/broll/api/ingest-batches` and `/broll/api/fleet/ingest`

Added 2026-08-18 (`docs/BROLL_INGEST_PLAN.md` §4.2/§4.3). Drag clips onto the
b-roll page and the editor's **own machine** indexes them — ffmpeg, then a local
model — and uploads the results to the NAS. Three parties, and the split of
credentials between them is the whole design:

- the **browser** only dispatches. It creates a batch and hands the uid to the
  local companion over the loopback; it never learns a path and never dictates
  one.
- the **companion** claims that batch on the fleet routes and receives the work
  order — video ids, archive folder and stem, taxonomy, lease.
- the **server** flips rows live only after it has `stat()`ed the uploaded files
  in `BROLL_DATA_ROOT`, which *is* the NAS archive.

### The panel's routes (session)

Authorised by `X-CCSync-User` / `X-CCSync-Admin`, which
`ccsync_dashboard.broll.BrollGate` mints from the session cookie and **strips
inbound** — the same rule `/ytdl` runs on. A request with no stamp is 401 in the
sub-app even if something let it past `login_gate`.

| Route | Body | Answer |
|---|---|---|
| `POST …/precheck` | `{share, keep_subfolders, items:[{local_id,name,size,hash,rel_dir}]}` | `{items:[{local_id, duplicate_of, duplicate_name, final_name}]}`. Reserves nothing |
| `POST …/` | `{share, collection?, settings, items:[…]}` | `{uid, state:"queued", n_items}` |
| `GET …/?scope=mine\|all` | — | `{scope, admin, batches:[…]}`. `scope=all` needs `X-CCSync-Admin: 1` |
| `GET …/{uid}` | — | `{batch, items:[…]}` |
| `POST …/{uid}/cancel` | — | sets `cancel_requested` **and expires the lease**. Owner or admin |
| `POST …/{uid}/upload-paused` | `{paused}` | holds the uploads; the crunching continues |

`settings` = `{tier: good\|best, run_mode: idle\|foreground, upload_originals,
keep_subfolders, transcribe:false}`. A tier or run mode this server does not
know is 422, not a machine that waits forever for a model nobody can fetch;
`transcribe: true` is 422 until phase 2 exists.

Another editor's batch is **404, never 403** — a 403 hands out a uid, and the
uid is the only thing between an editor and someone else's drop.

### The companion's routes (fleet)

`X-CCSync-Token` (the shared `DASH_REPORT_TOKEN`) **plus** a signed
`X-CCSync-Identity`, both fail-closed, exactly as the ytdl fleet routes do (§1,
and H5 — the token proves *a* fleet machine and nothing about **which**).
`login_gate` carves these six shapes out **per suffix**, so a leaked fleet token
cannot read or stop a batch through the panel routes above.

| Route | Body | Answer |
|---|---|---|
| `POST …/batches/{uid}/claim` | `{machine, companion_version, tier, capabilities}` | the manifest: `{batch, settings, lease_seconds, heartbeat_seconds, archive_remote_rel, taxonomy, items:[…]}` |
| `POST …/batches/{uid}/heartbeat` | `{}` | `{ok, cancel_requested, upload_paused, lease_expires_at}` |
| `POST …/batches/{uid}/items/{iuid}/status` | `{state, stage_percent?, error?, attempts?, hash?, probe?}` | the batch counters |
| `POST …/batches/{uid}/items/{iuid}/result` | `{segments, themes, quality_flags, category_hint, model, probe fields, sprite_*}` | server writes the rows **and computes `search_norm`** |
| `POST …/batches/{uid}/items/{iuid}/uploaded` | `{files:[{rel,size}], original_uploaded}` | `{ok, live:true, archive_path}` |
| `POST …/batches/{uid}/release` | `{state: done\|failed\|cancelled, summary}` | finalises; `done` with failures becomes `done_with_errors` |

Both uids are 32 lowercase hex characters (`lower(hex(randomblob(16)))`), and
the shape is load-bearing: an integer id would be one an editor could
enumerate, and `app.py`'s carve-out regex pins it.

**Every call after `claim` should also send `X-CCSync-Machine`** — the same
string that claim's body carried. It is what proves the caller is still *this*
editor's leaseholding machine rather than another of their companions, and
without it that one check is skipped (the editor, lease and cancel checks all
still run). A machine that does not match gets 410 `reason: other_machine`.

**`claim` is one transaction** and is idempotent for the machine that already
holds the batch (a companion restarting mid-batch re-issues it): it mints the
`videos` rows at `status='ingesting'`, allocates each archive name against what
is already published in that folder ∪ this batch (`_2`, `_3`… — the
`build_archive.claim_name` rule), records the share with
`share_roots.collection`, and takes the lease.

**`uploaded` believes nothing.** Every declared `rel` is resolved under
`BROLL_DATA_ROOT`, containment-checked and `stat()`ed, and the proxy the server
itself allocated is required whether or not the companion mentioned it.

### Status codes here

| Code | Means, on these routes |
|---|---|
| `403` | a credential problem, and only that: no/invalid fleet token, an unverifiable identity, or a claim on **another editor's** batch |
| `409` | another of this editor's machines holds a live lease; or (on `uploaded`) the files are not all there — body carries `{missing[], size_mismatch[]}` so an interrupted rclone retries those and not the clip |
| `410` | **your claim is over**, however it ended: lease expired and reclaimed, cancelled, taken by another machine, batch finished. The companion's answer to all of them is the same one — stop, quietly — and a 403 would read as "fix your credentials" and be retried forever |
| `400` | an illegal item transition (an item cannot go backwards; only `failed` may be left again), or a `rel` that points outside the archive root — no retry can fix either |

---

## 6b. Music ingest — `/music/api/ingest-batches` and `/music/api/fleet/ingest`

Added 2026-08-18 (`docs/MUSIC_INGEST_PLAN.md` step 2). The same three-party
split as §6a and the same credentials, for a different pipeline: drop music on
the `/music` page and the editor's **own machine** embeds it with the exported
CLAP **audio** tower (`music/indexer/export_audio_encoder.py`, ONNX +
onnxruntime, no GPU needed), uploads the audio to the library, and the
**server** turns that embedding into a track with tags and axes using the CLAP
**text** tower it already runs for every search query. Nothing on either end
needs torch.

The older browser-upload path (`POST /music/api/ingest`, `ingest_queue`, a
base-rig `index_music.py --queue` drain) is untouched and is the documented
fallback for a companion that cannot embed: its item ends `queued_for_base_rig`
and a `pending` journal row waits for the drain.

### The panel's routes (session)

Authorised by `X-CCSync-User` / `X-CCSync-Admin`, which
`ccsync_dashboard.music.MusicGate` mints from the session cookie and **strips
inbound** — the same rule `/broll` and `/ytdl` run on. A request with no stamp
is 401 in the sub-app even if something let it past `login_gate`.

| Route | Body | Answer |
|---|---|---|
| `POST …/precheck` | `{items:[{local_id,name,size,duration,content_hash}]}` | `{items:[{local_id, duplicate_of, duplicate_name, final_name, unsupported}]}`. Reserves nothing |
| `POST …/` | `{settings, items:[…]}` | `{uid, state:"queued", n_items}` |
| `GET …/?scope=mine\|all` | — | `{scope, admin, batches:[…]}`. `scope=all` needs `X-CCSync-Admin: 1` |
| `GET …/limits` | — | `{max_items, audio_exts, transcode_exts, run_modes}` — what the SPA must not exceed, said by the server that enforces it |
| `GET …/{uid}` | — | `{batch, items:[…]}` |
| `POST …/{uid}/cancel` | — | sets `cancel_requested` **and expires the lease**. Owner or admin |
| `POST …/{uid}/upload-paused` | `{paused}` | holds the uploads; the embedding continues |

`settings` = `{run_mode: idle\|foreground}`. No tier, unlike b-roll: music
ingest never uses the GPU (~93 ms per 10 s window on CPU), so there is no model
size to choose and nothing for it to block. A file whose extension is not audio
is a **422 that names it**, not a silent drop.

**Both duplicate defences run before anything is written**, the two
`musicweb.db` already applies to a browser upload: normalised stem + duration
within 2 s (`find_reencode` — the only one that can see a re-encode, since
transcoding changes every byte) and the whole-file blake2b-16
(`find_content_duplicate_by_digest`, which takes the digest the editor's
machine computed and only opens library rows whose byte count already matches).

Another editor's batch is **404, never 403** — a 403 hands out a uid.

### The companion's routes (fleet)

`X-CCSync-Token` (the shared `DASH_REPORT_TOKEN`) **plus** a signed
`X-CCSync-Identity`, both fail-closed (§1, and H5 — the token proves *a* fleet
machine and nothing about **which**). `login_gate` carves these six shapes out
**per suffix** via `_music_fleet_re`, a separate pattern from b-roll's, so a
leaked fleet token cannot read or stop a batch through the panel routes above.

| Route | Body | Answer |
|---|---|---|
| `POST …/batches/{uid}/claim` | `{machine, companion_version, capabilities}` | `{batch, settings, lease_seconds, heartbeat_seconds, library_remote_rel:"Assets/Music", audio_exts, transcode_exts, items:[…]}` |
| `POST …/batches/{uid}/heartbeat` | `{}` | `{ok, cancel_requested, upload_paused, lease_expires_at}` |
| `POST …/batches/{uid}/items/{iuid}/status` | `{state, stage_percent?, error?, attempts?, content_hash?, transcoded?, probe?}` | the batch counters |
| `POST …/batches/{uid}/items/{iuid}/result` | `{embedding, dim, model, name?, transcoded, content_hash, size_bytes, duration, bpm?, music_key?, key_conf?, lufs?, peak_db?, probe, peaks, windows:[{idx,t0,t1,vector}]}` | writes the `tracks` row, then re-scores the library: `{ok, track_id, rel_path, scores, …counters}` |
| `POST …/batches/{uid}/items/{iuid}/uploaded` | `{size}` | `{ok, live:true, rel_path, bytes}` |
| `POST …/batches/{uid}/release` | `{state: done\|failed\|cancelled, summary}` | finalises; `done` with failures becomes `done_with_errors` |

`embedding`, `peaks` and each window `vector` are **base64 of raw
little-endian float32** (uint8 for `peaks`) — the bytes `db.to_blob` stores,
with a base64 in between. A JSON array of 512 numbers is ~9× the bytes and
every one of them is parsed into a Python float and thrown away.

Item states are music's own: `pending → transcoding → embedding → indexed →
uploading → live`, plus `duplicate`, `failed` (the one terminal state a retry
may leave), `cancelled`, `skipped` and `queued_for_base_rig`.

**`claim` mints no `tracks` rows** — the one real difference from b-roll's.
b-roll can mint a hidden `videos` row at claim because `status='ingesting'` is
excluded from browse, tree and search; `tracks` has no status column and every
facet, percentile and debias axis reads every row, so a placeholder would skew
the library rather than hide from it. The row is written at `result`, with the
embedding, under a name allocated against the library **and** against every
other unlanded item (`theme.wav`, `theme (2).wav`).

**`result` re-scores the whole library** (`musicweb/rescore.py`). Tags are a
softmax over labels z-scored down the library's own column and every `pct` is a
rank among the others, so there is no such thing as scoring one track alone.
An embedding whose width disagrees with the library's is **409
`model_mismatch`**: a vector from another CLAP version is not comparable with
these, and mixing two would make every cosine in the index meaningless.

**`uploaded` believes nothing.** The music share is mounted in this container
(it is what `/api/audio` streams), so the file is `stat()`ed at the path the
**server** allocated — nothing about it comes off the wire — and the size must
agree. It also widens the mode to 0664, because the container's `umask 077`
otherwise leaves a file that is in the index and invisible over SMB.

Status codes are §6a's, with two music-specific 409 reasons: `model_mismatch`
(above) and `size_mismatch` / `not_uploaded` on `uploaded`.

---

## 6c. Fleet jobs -- `/api/v1/jobs`

Added 2026-08-29 (`docs/TIMELINE-CARDS-INTO-CCSYNC.md` phase 0), extended
2026-08-30 (phase 1, phase 4 and section 10). A general queue of work the
fleet can do: one row, a set of hard requirements, and a lease.

### The kinds

| kind | what it does | requirements | idle floor | retries | preferred machine |
|---|---|---|---|---|---|
| `whisper` | MulticamPipeline's corpus stage over a folder in the vault (a subprocess) | the submitter's: `{whisper, gpu_vram_gb, mount}` | 300 s | 3 | one with a GPU |
| `proxy-480p` | `<clip>.480p.mp4`, what Timeline Cards' video window plays | `{ffmpeg, ffprobe, mount:[<root>, <out_root>]}` | 300 s | 3 | one with **nvenc** |
| `audio-extract` | `<clip>.m4a` (aac copy) or `.ogg` (mono Opus), what the lane plays | same | **60 s** | 2 | the **base rig** |
| `peaks` | `<clip>.peaks`, the waveform under the lane | same | **60 s** | 2 | the **base rig** |

`conform` and `resolve-edit` are **not here and never will be** (section 4.2):
every edit is a synthetic keystroke into whatever Resolve has open on ONE
machine, and a scheduler that moved one to an idle machine has moved it into
the wrong timeline. A job of an unknown kind is accepted into the table (a
newer submitter must not be refused by an older dashboard) and offered to
nobody -- `why` says exactly that.

The three media kinds are the Timeline Cards recipes, run byte-compatibly on a
machine that is not the one serving the page
(`companion/src/ccsync_companion/jobs_media.py`; the argv is pinned verbatim
against `library_engine.py` by `companion/tests/test_jobs_media.py`).

**The idle floor is per kind because the cost is.** A whisper pass or an x264
encode is minutes; an audio copy is `-c:a copy` on one file and a peaks pass
is an 8 kHz decode. Making a laptop wait five minutes of stillness before it
will copy an audio track is how a lane sits on a spinner while a fleet of
capable machines does nothing.

**`requires` may be left empty for the three media kinds** and the dashboard
fills in the standard set (`jobs.default_requires`): ffmpeg, ffprobe, and both
of the roots the job names. An explicit `requires` always wins. Whisper's
stays the submitter's, because a VRAM floor is a property of the model they
chose.

Two audiences and two credentials, and the split is the design:

| Who | Routes | Credential |
|---|---|---|
| an **admin** at a browser or `tools/jobs.py` | `POST/GET /jobs`, `GET /jobs/{id}`, `GET /jobs/{id}/why` | the session cookie, admin only. A job is work on somebody else's computer |
| a **companion** with nobody at the keyboard | `POST /jobs/claim`, `POST /jobs/{id}/heartbeat`, `POST /jobs/{id}/result` | `X-CCSync-Token` **plus** a signed `X-CCSync-Identity`, both fail-closed -- §6a's posture exactly |

`login_gate` carves out the three fleet shapes **per suffix**
(`^/api/v1/jobs/(claim|\d+/(heartbeat|result))$`), never the prefix: a leaked
fleet token can neither read the queue nor put work on it.

### A job

```json
{"id": 12, "kind": "whisper", "created_at": "...", "created_by": "owen",
 "priority": 0,
 "inputs":   {"root": "vault", "rel_path": "Vault/2026/FF5/Ep/Youtube/A",
              "episode_rel": "Vault/2026/FF5/Ep", "speakers": false},
 "requires": {"whisper": true, "mount": "vault", "gpu_vram_gb": 6},
 "state": "queued|claimed|running|done|failed|abandoned",
 "forced": false, "target_machine": "",
 "claimed_by": null, "claimed_machine": null, "lease_expires_at": null,
 "heartbeat_at": null, "attempts": 0, "last_error": "",
 "result": {"files": ["Clips/A/A_words.json"], "seconds": 214.0, "realtime": 11.4}}
```

A media job:

```json
{"id": 31, "kind": "proxy-480p",
 "inputs": {"root": "media", "rel_path": "FF5/Civil Defence/Interview 3.mp4",
            "out_root": "vault",
            "out_rel": "Vault/2026/FF5/CD/Script Docs/remote_audio/source",
            "out_stem": "Interview 3"},
 "requires": {"ffmpeg": true, "ffprobe": true, "mount": ["media", "vault"]},
 "progress": 0.62,
 "result": {"files": ["Vault/2026/.../remote_audio/source/Interview 3.480p.mp4"],
            "out_root": "vault", "seconds": 3.3, "realtime": 11.0,
            "skipped": false}}
```

`root`/`rel_path` name the SOURCE media, `out_root`/`out_rel` the DIRECTORY
the file goes in (for Timeline Cards: `<episode>/Script Docs/remote_audio/
source` for an extraction or a proxy, `<episode>/Script Docs/remote_audio` for
peaks). `out_stem` is the name the page knows the clip by -- its multicam
name, which is not always the media file's own stem; the default is the
file's stem. Nothing anywhere guesses where a cache belongs in somebody's
vault: a media job with no `out_rel` is refused with a sentence.

`result.files` are relative to `result.out_root`, and `skipped: true` means
the file was already there and current (the same `mtime >= source mtime` test
the page uses) -- a success, and one with no `realtime` figure, because there
is nothing honest to divide.

**PATHS ARE (ROOT NAME, RELATIVE PATH) PAIRS AND NEVER ABSOLUTE.** The vault
is `X:\` on creator-1, `/vault` inside the Timeline Cards container and a UNC
path on the wire, so a path on the wire would be right on exactly one machine.
Root names are `tree` (the project tree, `local_root`), `vault` and `media`;
the claimant resolves them through its own config
(`companion/src/ccsync_companion/job_paths.py`) and **refuses** anything
absolute or climbing. Results name paths relative to the episode root for the
same reason. Nothing streams through the dashboard: the output is in the
vault, which every machine shares.

`requires` is the HARD filter, evaluated against the machine's reported
capabilities (§ the report's `capabilities` section). Four shapes:
`gpu_vram_gb`/`cpu_count` (a number, `>=`), `mount` (a name that must appear
in `capabilities.mounts`), and anything else compared for equality
(`whisper: true`). **Anything the dashboard does not understand is a
refusal** -- an unknown requirement must never read as satisfied.

### The admin routes (session)

| Route | Body | Answer |
|---|---|---|
| `POST /api/v1/jobs` | `{kind, inputs, requires, cost, priority, force?, target_machine?}` | `{ok, job, why}` -- the receipt carries the scheduling answer, so a job nothing can run says so at submit time |
| `GET /api/v1/jobs?state=open\|queued\|…&kind=&limit=` | -- | `{jobs:[…], kinds:[…]}` -- `kinds` is what THIS dashboard can schedule |
| `GET /api/v1/jobs/{id}` | -- | `{job}` |
| `GET /api/v1/jobs/{id}/why` | -- | `{job, schedulable, reason_code, transient, capable, running, cap, summary, machines:[{editor, machine, ok, reason, why, rank, score, signals, why_not_first}]}` |
| `GET /api/v1/jobs/queue` | -- | `{queue:{queued, running, pinned, oldest_age_s}, kinds:[{kind, running, cap}], pinning:{available, why_not}}` |
| `POST /api/v1/jobs/{id}/cancel` | -- | `{ok, state, job}`; **409** for a job that has already finished |

`why` is **"unschedulable, and why", per machine**, and it exists from the
first commit on purpose: a scheduler that quietly assigns nothing looks
exactly like a fleet with nothing to do. Per-machine `reason`s are
`capability | fleet_halt | machine_halt | upgrading | lane_b_breaker |
already_holds_a_job | not_idle | no_capabilities_reported | kind_unknown |
another_machine_is_preferred | cooling_down | kind_not_allowed |
jobs_disabled | fleet_cap | not_the_target`.

**`schedulable` and `reason_code` are two different questions** (phase 4).
`schedulable` keeps its phase-1 meaning -- "is anything going to take this,
soon" -- because Timeline Cards' client makes the file itself when it is
false, and that is the right answer for a fleet whose every machine has
somebody sitting at it. `reason_code` is what tells the two kinds of false
apart, and it is a CODE because a client branches on it:

| `reason_code` | means | `transient` |
|---|---|---|
| `""` | schedulable | -- |
| `no_machine_reported` | nothing has ever reported here | no |
| `no_capable_machine` | every machine fails the capability filter | no |
| `all_busy` | capable machines, all holding a job / upgrading / breaker-tripped / inside the grace window | yes |
| `fleet_cap` | this kind is at the fleet's own limit | yes |
| `idle_wait` | somebody is at every machine that could | yes |
| `cooling_down` | every capable machine failed a job recently | yes |
| `halted` | a fleet halt, or every machine's sync halted | no |
| `kind_not_allowed` | every machine's config excludes this kind | no |
| `kind_unknown` | this dashboard does not know the kind | no |
| `target_away` | this job named one machine, and that machine is here and not free | yes |
| `target_unknown` | this job named a machine no report has ever come from | no |
| `held` / `pinned` / `finished` | somebody has it, or it is over | held and pinned, yes |

**The worst answer wins, not the commonest**: one machine that could do this
if its editor stood up is a fleet that will get to it, and answering
`no_capable_machine` because four other machines have no GPU would send a
client off to do GPU work on a laptop. `capable` is how many machines could
EVER run it -- the number to read before buying hardware.

**Cancelling** is three different acts wearing one route. A **queued** job is
`failed` when the call returns, with the admin's name in `last_error`, and is
never retried. A **held** one is not touched: the request is recorded, rides
`commands.jobs.cancel` on that machine's next report until it answers, and
the companion kills its child and posts `failed(cancelled, retryable=false)`.
A **pinned** one is read by the dashboard's own worker within a second.
Nothing forces a row terminal behind a live ffmpeg -- a machine that never
answers keeps the job until its lease expires, because saying "stopped" while
a child is still writing into the vault is how a half-made proxy gets
published.

These are session routes, so a non-browser client sends the CSRF token
`POST /api/v1/login` now returns as `csrf` (it is an HMAC over that session's
own id -- worthless without the cookie, and the alternative was exempting the
write routes, which is the wrong direction).

### The companion routes (fleet)

| Route | Body | Answer |
|---|---|---|
| `POST /api/v1/jobs/claim` | `{machine, machine_id?, capabilities, kinds?, ids?}` | `{job, lease_seconds}` or `{job: null, offered: […]}` |
| `POST /api/v1/jobs/{id}/heartbeat` | `{machine, note?, progress?}` | `{ok, lease_seconds}`, or **410** |
| `POST /api/v1/jobs/{id}/result` | `{machine, ok, retryable, error, result}` | `{ok, state}`, or **410** |
| `GET /api/v1/jobs/machines` | -- | `{machines:[…], kinds:[…]}` -- the computers a job can be AIMED at |

The claim is a **compare-and-set** (`db.claim_job`): two machines offered the
same job both arrive, SQLite serialises the writes, and the loser is told the
truth. The capabilities in the claim body are re-checked there and then --
an offer rode a report reply up to a report interval ago, and an editor who
has come back to their desk in that interval must not be handed a transcode.

`progress` is **0..1 and optional**, and null is not zero: a runner with no
honest fraction to report (a peaks pass reads its input in one gulp) sends
none, and the fleet chip then shows the job id instead of a machine that looks
wedged at 0%. A media recipe gets its fraction from ffmpeg's `-progress`
stream against the source duration and publishes it at most once a second; the
heartbeat carries the latest every 30 s. The column is `COALESCE`d, so a
silent heartbeat does not erase the last number. The chip reads
`[ PROXY 480p: 62% ]`.

**410 GONE, never 403**, on heartbeat and result: "your claim is over" is the
answer to every way they can fail (the lease expired and the job was
re-queued, another machine has it, it finished), and the companion's response
to all of them is the same one -- stop, quietly.

Leases: 300 s, heartbeat every 30 s. An expiry re-queues the job **and counts
as an attempt**; past the per-kind retry budget (3 for `whisper`) it becomes
`pinned` where this dashboard has an executor of its own and `abandoned`
where it has not, rather than ping-ponging around the fleet for ever.
`ok: false, retryable: false` is the runner saying the fault is in the JOB,
which no other machine will fix.

**`pinned` is the fifth state** (phase 4, section 4.4 rule 5): the three media
kinds only -- never `whisper`, since the dashboard container has ffmpeg and no
GPU -- and only where `/cards` is mounted with an engine that implements
`fleet_execute`. The dashboard's own worker runs it and the job then finishes
`done` with `result.files`, so a client polling the row on another server sees
it complete and cannot tell who made the file. **A pinned job never goes back
to the fleet.** With no executor nothing pins and the state is `abandoned`,
exactly as in phase 1 -- a job pinned into a queue nothing drains would be
worse than one that says it was given up on.

A **retryable** failure, and a lost lease, also put that machine on a short
**cooldown** (`DASH_JOBS_COOLDOWN_SECONDS`, 120 s): the box with the broken
ffmpeg is otherwise first in the queue for every retry, because failing in two
seconds is exactly what keeps it idle. A success clears it; `retryable=false`
never sets it, because the fault was in the clip.

### The offer, on the report reply

```json
{"commands": {"jobs": {
  "offered": [12, 13],
  "forced": [13],
  "cancel": [11],
  "queue": {"queued": 4, "running": 2, "pinned": 0, "oldest_age_s": 91.2}
}}}
```

Each key is present only when it has something to say (the `broll_ingest`
rule: an empty list is not an instruction, and this rides every tick of every
machine). `cancel` names jobs THIS machine is holding that an admin has
stopped, and keeps riding until the machine answers with a result. `queue` is
the **depth signal** (phase 4): a companion with nothing offered and an empty
queue lengthens its own tick (4x, capped at 120 s), and a DEEP queue never
lengthens it -- backpressure on that side means stop asking, never stop
working. `oldest_age_s` is null, never 0, on an empty queue. `forced` is the subset of
`offered` whose row carries the admin's "now" (section 10 below): always a
subset, and never a second list to claim from, because naming a job there that
had not also been offered would be pushing rather than offering.
**Offer, do not push** -- the ids are an invitation and the claim is the
decision. Computed by `ccsync_dashboard/jobs.py`: capability match, then
policy (not halted, not mid-upgrade, breaker not tripped, not already holding
a job, idle enough for this kind -- the base rig exempt, because nobody sits
at it), then rank.

**Rank is a preference, never a gate** (phase 1). For the first
`RANK_GRACE_SECONDS` (60 s, two report intervals) a job is offered only to the
best-placed machines; a TIE is offered to all of them, because the
compare-and-set is what decides between equals. After that every capable
machine is offered it. A scheduler that can starve a queue is worse than one
with no opinion at all, because the symptom is identical to a fleet with
nothing to do.

The rank (phase 4) is `(preference, -live jobs, -load, idle seconds)`,
biggest first, and only `preference` differs by kind -- an ORDERED list of
signals, the first worth more than the second:

| kind | signals, best first |
|---|---|
| `whisper` | `gpu_fits` (VRAM at or above the job's own `gpu_vram_gb` plus 1 GB of headroom), then `gpu` |
| `proxy-480p` | `nvenc` |
| `audio-extract`, `peaks` | `near_media` (the base rig: next to the media, and nobody sits at it) |

A GPU that will not report its size is no preference (not a refusal), and a
missing load average is not a penalty -- `null` is "Windows has no loadavg",
and reading it as busy would rank every Windows box below every Mac for a
reason that says nothing about either. `why` reports each able machine's
`rank`, its `score` tuple, the `signals` behind it and `why_not_first` -- the
first component it lost on, in words -- so "three machines could and it went
to the one without the encoder" is an answerable question.

**A per-kind FLEET CAP** sits over all of it (`DASH_JOBS_MAX_RUNNING`,
default 2 for `whisper` and 4 for the media kinds): one job at a time per
machine was never a limit on the NAS's disk or the media share's bandwidth,
which four simultaneous 480p encodes reading rushes over SMB find long before
any one machine does. **And a machine's own allow-list** (`jobs_kinds` in its
config, reported as `capabilities.job_kinds`) is honoured here and on the
companion: empty is every kind, so an editor's laptop can be kept out of
`whisper` without being taken out of the fleet.

`idle_seconds` keeps `idle.py`'s contract end to end: **null means cannot
tell means NOT IDLE**, on the machine and on the server.

### Force, target and volunteer

Added 2026-08-30 (`docs/TIMELINE-CARDS-INTO-CCSYNC.md` section 10, dashboard
**0.7.23** / companion **0.9.61**). Everything above is a reason to WAIT, and
until now the only lever over a fleet of machines with people sitting at them
was to go and ask somebody to stand up. Three levers answer that, and each is
pulled by a different person:

| lever | who pulls it | what it bypasses |
|---|---|---|
| **volunteer** -- the tray item *"Take fleet jobs now (30 min)"* | the person AT the machine | that machine's idle gate and its Resolve-open gate, on both sides, until the timer runs out or they click it off |
| **force** -- `"force": true` on the job (`tools/jobs.py submit --now`) | the admin submitting | the idle floor, the per-machine cooldown and the rank grace on EVERY machine offered this job, and the companion's own idle/Resolve gates for THIS job only |
| **target** -- `"target_machine"` (`tools/jobs.py submit --on <machine>`) | the admin submitting | the ranking: the job is offered to that one machine and nobody else |

**Nothing bypasses** a fleet halt, a machine halt, an update waiting, a
tripped breaker, `jobs_enabled = false`, the machine's own `jobs_kinds`, a job
it already holds, the fleet cap, or the capability filter. "Force" means "do
not wait for anybody to leave their desk"; it does not mean "run on a machine
that cannot".

* **`force`** (body) / **`forced`** (row, and the column -- the two names
  differ so the column never argues with SQL) is a bool, default false.
* **`target_machine`** is a machine name as the report spells it
  (`machine_state.machine`), compared **case-insensitively**;
  `editor/machine` is accepted and the editor half is then also required to
  match, because two editors' laptops can carry the same machine name. An
  **unknown name is accepted**: the receipt's `why` says nobody by that name
  has reported, and that machine may be switched on tomorrow. Refusing it at
  submit time would make an admin guess at a spelling with nothing to check it
  against. The row and the `why`/receipt JSON carry both fields back
  (`""` when there is no target).
* **`capabilities.volunteer_until`** is an ISO-8601 UTC string, or null, in
  every capabilities section from companion 0.9.61. Absent from an older
  build, which reads as null. Unparseable also reads as **not volunteering**:
  `idle_seconds`' direction, because a value this server cannot read must
  never be the reason work starts under somebody's hands. There is
  deliberately **no dashboard button** that sets it -- the person at a machine
  is the one who knows whether they mind, and the admin's lever is
  `--on --now`, which that machine's companion obeys.
* **`commands.jobs.forced`** on the report reply is the subset of `offered`
  whose row is forced; **`ids`** on the claim body is the claimant's own
  narrowing, INTERSECTED with what was offered. A companion whose gate is
  closed but which holds forced offers claims with `ids = forced`, and asking
  for a job can never widen what the scheduler was willing to give.

`volunteering` is also a rank signal, and it LEADS every kind's list: a
machine whose editor said "go ahead" costs nobody anything, which beats an
encoder on a machine somebody merely walked away from. Like every other
signal it is a preference and not a gate.

### The machines a job can be aimed at -- `GET /api/v1/jobs/machines`

Added 2026-09-03 (cards-machine-picker). `target_machine` above has worked end
to end since dashboard 0.7.23, but nothing published the NAMES, so Timeline
Cards' intake head shipped a remembered free-text box instead (its
`docs/STAGED-AND-BINS-PLAN.md` section 8: "the clean v2 is one small
`GET /api/v1/jobs/machines` on the dashboard"). A target typed wrongly is a
job addressed to nobody, and the only thing that says so is the receipt's
`why`.

**Two credentials, because both audiences ask the same question**
(`api._require_jobs_reader`): a **fleet** caller -- `X-CCSync-Token` plus a
signed `X-CCSync-Identity`, the same gate as claim/heartbeat/result, and the
one `app.py`'s `login_gate` carves the suffix out for -- **or an ADMIN
session**, which is what `MulticamPipeline`'s `cards/fleet_jobs.py` already
holds (it signs in as an admin to submit). The fleet gate runs first when a
token is present, so a companion's failure is the fleet routes' 403 and its
sentence rather than "log in first". A non-admin session is refused: this is
the fleet's inventory, and the editor pages show a person their own computers
only. **The cards PAGE in a browser never calls it** -- its own session is not
necessarily an admin's and its URLs are document-relative under `/cards/` --
so the cards SERVER reads it and serves the list on its own route.

```json
{"machines": [
  {"editor": "alex", "machine": "CREATOR-1", "mode": "base",
   "online": true, "reported_at": "2026-09-03T09:12:44Z",
   "jobs_enabled": true, "kinds": [],
   "capabilities": {"gpu_present": true, "gpu_name": "RTX 4090",
                    "gpu_vram_gb": 24.0, "nvenc": true, "ffmpeg": true,
                    "ffprobe": true, "whisper": true, "cpu_count": 16,
                    "mounts": ["tree", "vault", "media"]},
   "idle_seconds": 900, "current_job": {"id": 12, "kind": "whisper"}}
 ],
 "kinds": ["whisper", "proxy-480p", "audio-extract", "peaks"]}
```

* The rows are the union of the `machines` registry and `machine_state`, which
  are the same set on a healthy fleet and are not on a database that predates
  v23's backfill or one DASH-16 has pruned state from.
* `online` is **the alerts silent window** (`alerts.SILENT_SECONDS`, 24 h), not
  the grid's six: this feeds a picker, and a laptop that reported this morning
  is a sensible thing to aim tonight's transcode at. An unreadable or missing
  `reported_at` is offline.
* `kinds` is that machine's own allow-list (`jobs_kinds`), and **empty is every
  kind** -- `db.machine_allows_kind`'s rule, on this side too. `jobs_enabled`
  is the separate switch, and a machine that has never reported capabilities
  reads `false`: `{}` is "unknown", which the scheduler already treats as
  "offer it nothing that has a requirement".
* `idle_seconds` keeps idle.py's contract: **null means cannot tell means NOT
  IDLE**, never 0.
* `capabilities` is an explicit whitelist of the columns the scheduler filters
  and ranks on, not the decoded capabilities dict, so a future column cannot
  join this answer by accident. **No token, no machine id, no Syncthing device
  id, no path, and not the open Resolve project's name**: this is a list of
  computers and what they can do.
* Sorted **online first, then hostname**. A machine nobody has heard from in a
  day belongs under the ones that will answer.
* It says nothing about whether a machine may take a job right now. That is a
  question about a particular job (`GET /jobs/{id}/why`), and a second opinion
  here could disagree with the first.

### Submitting from the command line

```
python tools/jobs.py submit --kind whisper --root vault \
    --rel "Vault/2026/FF5/Civil Defence/Youtube/Interview 3" \
    --episode "Vault/2026/FF5/Civil Defence" [--speakers] [--watch]
python tools/jobs.py submit --kind proxy-480p --root media \
    --rel "FF5/Civil Defence/Interview 3.mp4" --out-root vault \
    --out-rel "Vault/2026/FF5/CD/Script Docs/remote_audio/source" \
    [--out-stem "Interview 3"] [--watch]

python tools/jobs.py submit --kind whisper --rel "..."     --now                       # do not wait for an idle machine
    --on CREATOR-1              # ...and give it to that one machine

python tools/jobs.py list [--state open] | why <id> | watch <id>
python tools/jobs.py queue          # the depth, the per-kind caps, and
                                    # whether anything pins here
python tools/jobs.py cancel <id>
```

`watch` prints the percentage while a recipe runs, and says "already
made" rather than "0 file(s) written" for a job that found its output
current.

`--dashboard-url` / `--admin-user` (or `CCSYNC_DASHBOARD_URL` /
`CCSYNC_ADMIN_USER`); the password is prompted or `--password-stdin`, never
argv and never the environment.

---

## 6d. The Timeline Cards agent tunnel -- `/cards/agent/*`

`docs/TIMELINE-CARDS-INTO-CCSYNC.md` §3.3 option (a), phase 2 (2026-08-30).
Implemented by `dashboard/src/ccsync_dashboard/cards_tunnel.py`.

The machine with DaVinci Resolve open pushes the timeline it has swept and
long-polls for the next edit. This is the **interactive** channel: a card
click has a ~0.3 s budget, which is why it is not on the report reply the way
fleet jobs are (§6c). It is a thin proxy: the dashboard holds no state for it
and decides nothing about it.

| Method | Path | Body / query | Answer |
|---|---|---|---|
| POST | `/cards/agent/state` | the agent's state document, or a playhead-only ping | `{ok, version, root, resend}` |
| GET | `/cards/agent/pending` | `?wait=<0..25>` | `{}` or the next edit request |
| POST | `/cards/agent/result` | `{id, ok, note, error, inserted_uid, conformed, renamed}` | `{ok}` |

**The credential is the fleet's**, exactly as for `/api/v1/jobs/claim`:
`X-CCSync-Token` (the shared report token, or a per-editor `cce1.` one) **and**
a dashboard-signed `X-CCSync-Identity`, both checked by
`api._require_fleet_caller`. `app.py`'s `login_gate` and `csrf_gate` carve out
these three suffixes and nothing else -- `/cards/` is where phase 3 mounts the
page, and it stays session-gated.

**The upstream token is the dashboard's alone.** `DASH_CARDS_TOKEN` is
attached outbound as `X-Cards-Token`; a `token` field in the caller's body is
dropped rather than forwarded, and one echoed by the upstream is stripped on
the way back. That is the point of the tunnel: `CARDS_TOKEN` stops living in a
`.cmd` file on an editor's PC.

**The agent's `name` is the verified identity**, plus the machine the caller
declared (`alex/CREATOR-1`), never the `name` the body carried -- the page's
"the agent is away" text is built from it, so it has to mean something.

Status codes:

| Code | Means |
|---|---|
| 200 | the cards server's own answer, verbatim |
| 401 / 403 | no fleet token, or no signed identity, or a per-editor token that names somebody else. JSON, never a login page: a pull loop handed HTML to `json.loads` says "Expecting value: line 1 column 1" every 25 s and never says why |
| 502 | the cards server could not be reached, refused this dashboard's token (the detail says `DASH_CARDS_TOKEN`), or did not answer JSON |
| 503 | no `DASH_CARDS_SERVER_URL` / `DASH_CARDS_TOKEN` configured here. Named, because 404 reads as an old dashboard |

`wait` is clamped to 25 s (the agent's own `AGENT_WAIT_S`) and the outbound
read timeout is that plus 20 s. The route is a blocking `def`, so it runs in
the threadpool: one worker per connected agent, and there is one agent per
machine.

**Since phase 3 (2026-08-30) there may be no upstream at all.** When the page
is mounted in this container (`DASH_CARDS_ENABLED=1`, below), these three
routes call the engine IN THIS PROCESS -- no HTTP hop, no `X-Cards-Token`, and
`DASH_CARDS_SERVER_URL`/`DASH_CARDS_TOKEN` are not read. Nothing else about
them changes: same paths, same credential, same verified-identity name rule,
same `{"error": ...}`-with-a-200 for an engine that refused. A dashboard
WITHOUT the mount still forwards to the separate cards server exactly as
described above, which is what lets both origins run side by side while the
old app is retired.

### 6e. `/cards/*` -- the Timeline Cards page (phase 3)

The whole cut, mounted in-process at `/cards` behind the dashboard login
(`docs/TIMELINE-CARDS-INTO-CCSYNC.md` §7d), on the same contract as `/broll`
and `/music`. **Its ~70 routes are Timeline Cards' own and are not documented
here** -- they are a `BaseHTTPRequestHandler` in that repo, served byte for
byte through a WSGI shim, and this document would go stale the first time
somebody added one over there.

What IS this repo's contract:

| | |
|---|---|
| auth | the dashboard session, for every path under `/cards/` except the three `/cards/agent/*` suffixes above. There is **no `?key=`**: the standalone server's browser gate is retired under this login |
| a logged-out fetch | **401 JSON** for `/cards/api/`, `/cards/audio`, `/cards/video`, `/cards/peaks` (the page's fetches and its `<audio>`/`<video>` srcs); a 303 to `/login` for the document itself |
| CSRF | the page sends no token, like `/broll` and `/ytdl`, so the POSTs are exempt from the TOKEN -- but **not** from the ORIGIN check. A cross-site POST to `/cards/api/delete` is a 403 |
| `/cards` with no slash | **307 to `/cards/`**. Every URL in the page is document-relative, so without the slash they would resolve against the dashboard root |
| `POST /cards/api/restart` | **refused** with `{"error": "...cannot restart itself..."}`. In the standalone server that route re-execs the process; here that process is the dashboard |
| `GET /cards/agent/<anything else>` | 404 naming the three real routes |
| Range requests | passed through unchanged: `/cards/audio?mp=...` answers 206 with `Content-Range`, `ETag` and `If-Range` exactly as the standalone server does, and the body streams rather than buffering |
| when it is not mounted | every path under `/cards/` except the agent three is a 404, and `GET /api/v1/health` says why in one sentence |

`GET /api/v1/health` (authenticated) carries the mount's state:

```json
"cards": {"status": "mounted|absent|disabled", "detail": "<one sentence>",
          "root": "/vault", "agent": true,
          "claude": {"ok": false, "why": "no provider has a working credential"}}
```

`status` is never part of `ok`: an optional feature that is off is not an
unhealthy dashboard, and the container healthcheck restarts on `ok`.

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
