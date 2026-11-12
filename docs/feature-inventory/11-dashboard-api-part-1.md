# Dashboard: the API, part 1

Covers `dashboard/src/ccsync_dashboard/api.py` lines 1 to about 6600 (every
route that starts before line 6600 is finished even where it runs past it).
All routes here live under the prefix `/api/v1`. Terms used throughout:

- **companion**: the tray app on an editor's computer that reports to the
  dashboard.
- **fleet credential**: what a companion sends in the `X-CCSync-Token`
  header. Either a **per-editor token** (shape `cce1.<id>.<secret>`, minted
  per person by an admin, bound to that person) or the **shared token** (the
  one fleet-wide `DASH_REPORT_TOKEN`, accepted only while the setting
  `shared_report_token_enabled` is on; it identifies nobody).
- **identity header**: `X-CCSync-Identity`, a signed "this is editor X"
  value the companion also sends; routes that say "identity checked" verify
  it matches the person the route acts for.
- **signed-in user**: anyone with a browser session. **admin**: a signed-in
  user the dashboard treats as an administrator.
- **machine** / **computer**: one editor's computer, keyed by
  (editor username, hostname).
- **tick**: a project chosen to sync on a machine (a "selection").

## Who may call what: the general gate
(source: api.py, app.py login_gate as far as needed)

- Every `/api/v1/...` route needs a signed-in browser session UNLESS it is
  one of the open paths: `/api/v1/login`, `/api/v1/logout`, `/api/v1/me`,
  `/api/v1/health`, `/api/v1/report`, `/api/v1/verify`,
  `/api/v1/diagnostics`, `/api/v1/ssh-key`, `/api/v1/site`,
  `/api/v1/setup/...`, or one of the fleet-credential exceptions:
  `/api/v1/selection/...`, `/api/v1/companion/package/...`, `GET
  /api/v1/fleet/halt`, `/api/v1/files/locate`, and the job routes `claim`,
  `machines`, `<id>/heartbeat`, `<id>/result`, which pass with a valid
  fleet credential instead of a session. "Open" means no session needed; the
  route itself still checks the credential it wants.
- A route below that says "admin" calls the admin check itself and refuses
  a signed-in non-admin.
- Session-authenticated write calls also need the session's anti-forgery
  (CSRF) token, except the companion-facing doors (`/report`, `/verify`,
  `/diagnostics`, `/selection/...` and others listed in app.py); that check
  lives in app.py, not in this file.
- **Scoping of fleet reads** (applies to `/projects`, `/projects/{slug}`,
  `/editors`, `/transfers`, `/projects/{slug}/presence`): an editor sees
  their own machines in full and only anonymous fleet totals for everyone
  else; an admin sees everything and may narrow the view to one editor with
  the query parameter `?as=<editor>` (ignored for non-admins).
- **Barred accounts** (applies to every companion-facing route that says
  "bar check"): a computer is refused when its person's account is
  - removed (deleted from the dashboard), on any sign-in method: refused with
    "this account was removed from the dashboard. Ask your admin to add it
    again if that was a mistake";
  - suspended by an admin, on any sign-in method: "this account is suspended
    on the dashboard. Ask your admin to press RESUME: your sync plan is
    untouched and comes straight back";
  - disabled, local-account sites only: "this account has been disabled on
    the dashboard. Ask your admin to turn it back on: nothing will sync
    until they do". On a local-account site a username with NO local account
    also counts as disabled, but only once at least one local account exists
    (a site that has created none yet is not refused).
  - On SMB or OIDC sign-in sites the "disabled" check is skipped (the account
    lives elsewhere); suspension covers it.
  - A database error while checking lets the request through (fails open).
  - The short reasons ("this account has been disabled", "this account is
    suspended", "this account was removed") are what the fleet page and the
    `report_refused` alert show; the longer sentences above are what the
    computer is told.
  - The same check is offered to the b-roll, music and YouTube-download apps
    so they can refuse a barred person too.
- Token comparison is constant-time; a token with non-ASCII bytes is simply
  a wrong token (401), never a server error.
- A per-editor token is never compared against the shared secret, and vice
  versa.

## Resolve scratch project names the server ignores
(source: api.py `is_ignored_resolve_project`)

- The Resolve project names "Untitled Project" and "New Doc" (any case,
  whitespace collapsed), and those names followed only by a number
  ("New Doc 1", "Untitled Project (3)", "New Doc - 2", "New Doc [4]"), are
  treated as scratch projects: they never auto-match a project root, never
  raise the "this Resolve project is not mapped" prompt, never update the
  machine's state, never count as media presence. "New Documentary" or
  "New Doc Final" are real projects and are not ignored.

## What the fleet views contain
(source: api.py view builders `build_projects_view`, `build_project_view`,
`build_transfers_view`, `build_presence_view`, `build_editors_view`,
`build_queue_view`; shared with the HTML pages)

### Projects list (`build_projects_view`)
- One entry per project: slug, label, path, Syncthing folder state and
  folder error (a "stopped / folder marker missing" state shows a project
  folder was moved), a health status, per-device editor rows, total bytes
  still needed, and how many editors are below 100%.
- Per project, counts of cross-project folder links it borrows: how many are
  `ok` and how many are not (invalid, missing, lender inactive).
- A fleet-wide status (worst of the projects) and whether Syncthing is
  reachable.
- A nested project tree built from slash-separated labels
  (`2026/CCT/Website Highlights`) for the sidebar: one group per path
  segment, each project shown by its last segment, each group listing every
  project slug under it so the page can open the branch holding the current
  project.
- Per editor-device row: device id, name, editor username (or "unmapped"
  when the Syncthing device is not linked to a person), connected or not,
  address, last connected time, completion %, items/bytes/deletes still
  needed, global items/bytes, items held, transfer rate, ETA (needed bytes /
  rate, only when rate > 1 B/s), a status, the time the companion last
  reported anything, a reason sentence when the dot is not green because the
  machine went silent, and the lane rows.
- Per lane row (lanes are A = video up by rclone, B = proxies down by rclone,
  C = Syncthing): lane letter, machine, state, a coloured chip and the chip's
  reason in words, progress token and since when, state since, queued count,
  last error, last sync, received time, companion version, current project,
  bytes done/total, speed, ETA.

### One project (`build_project_view`)
- Everything above for one project, plus: active flag, folder state time,
  the server's media summary for the project, both directions of folder
  links (what this project borrows, every status; who borrows from it, ok
  only).
- "Who has what" also lists machines that report media for the project but
  have no Syncthing device in it (for example a wired base rig): they appear
  as "report only" rows with their media counts and a presence status.
- Each editor row gets a total sync percentage: (Syncthing bytes held +
  proxy bytes held, capped at the server's proxy bytes) / (Syncthing global
  bytes + server proxy bytes), rounded to 0.1. Camera originals are left out.
  When no media manifest has arrived, the Syncthing completion is shown
  instead.

### Transfers (`build_transfers_view`)
- Live per-file transfers (editor, machine, lane, file name, direction, bytes
  done/total, %, speed, ETA), plus one project-level row per Syncthing
  download that is moving faster than 1 B/s (no per-file data for lane C).
- One row per active project whose server-side Syncthing folder still needs
  bytes: "<label>: N file(s) arriving at the server" (direction up, no
  editor named).
- Total fleet speed (sum of all row speeds), sorted fastest first.
- **Queue** (what is waiting, per editor, machine, project):
  - lanes A and B from the difference between the server's file list and the
    machine's reported file list; lane C from Syncthing's missing-files list
    (first 50 files, with a "truncated" flag).
  - Only ticked projects can be queued; only "full" ticks count for lane C.
  - Base-mode (wired) machines, and people whose every machine is wired,
    never appear in the queue.
  - A lane C device is attributed to a person and computer from the machine
    registry first, then from the device's label; a device that cannot be
    resolved to a computer falls back to "any of this person's ticks".
  - Files already in the live transfers are subtracted from the queue
    (compared after Unicode normalisation, also by bare file name).
  - Rows with zero files are dropped unless flagged "uncertain" (a machine
    whose originals list was capped, so zero means "cannot tell").
  - A just-ticked project with no Syncthing completion row yet shows a
    "preparing" row (one per computer and project).
  - An upload-only tick shows "preparing" until that machine's first media
    manifest for the project arrives. If the machine (or, for an unassigned
    tick, every computer of that person it stands for) withholds its file
    list by a reporting switch, it shows an "uncertain / not reported" upload
    row instead, never "nothing owed".
  - A queue row on a machine that has said it cannot move (drive unplugged,
    halted, not signed in and so on) carries a "held" reason.
  - Totals: queued files (excluding preparing rows) and queued bytes.
- **History**: the last 50 completed transfers (editor, machine, lane, name,
  direction, completion time).

### Presence (`build_presence_view`)
- For one project: the server's media counts, and per (editor, machine):
  mode, originals and proxies held, bytes of each, truncated flag, a
  role-aware status, a "proxy only" badge, the Resolve bin tree with each
  clip online or offline, and the number of offline clips. A machine with a
  bin tree but no disk report yet still appears (zero counts).

### Fleet machines (`build_editors_view`)
- One row per (editor, machine) that has ever reported, even when its live
  lane rows have been pruned (after 30 silent days) or filtered out.
- Each row carries: lanes, a status (worst of the lane chips and a report
  freshness check, so a machine that stopped reporting goes non-green), a
  reason sentence, verified flag, network transport facts (for example
  relayed), safety latches (lane B breaker, halt), whether an admin's
  "resume proxy download" is still waiting to be picked up, disk colour and
  percentage (no chip at all when the machine never reported disk), clock
  skew shown as "AHEAD" or "SLOW" when at least the warning threshold off,
  whether a diagnostics bundle was asked for, whether the stall shown is
  still current, the time and reason the server last refused its report,
  diagnostics stamps, mode (editor or base), account suspended flag, its sync
  plan summary, fleet halt flag, b-roll and music indexing progress, the
  fleet job it holds now, its reported capabilities, a "volunteering" chip,
  proxy coverage, YouTube import state, platform, running and current
  companion version.
- Lane chips are recomputed with that machine's own rotation time, so a lane
  stuck in "syncing" eventually turns into a stall.
- **"Why is this machine not syncing"**: one sentence, plus each separate
  cause; marked informational (not red) for reasons such as upload-only.
  Appended to it, informational:
  - "N clip(s) in the open project are outside the tree and will never
    upload";
  - "N clip(s) only on this computer in '<project>' [and M other
    project(s)], which it does not have open; they will never upload".
- **Volunteering chip**: shown when the machine's own person has offered
  its GPU until a time that has not passed; shows the UTC HH:MM end time.
  There is no dashboard button for it.
- **Out of date**: the running companion version differs from (not merely is
  older than) the current published package for that machine's own platform
  (no platform reported counts as Windows). A machine that reports no
  version is flagged "unknown build". A machine running a build the vendor
  has recalled shows the recall reason.
- **Owed files**: "Idle, nothing owed" is only claimed when the server could
  count lanes A and B's backlog for that machine; never for a base machine,
  a machine that never sent a file list, or one whose only answer is
  "uncertain". This count is cached for up to 15 seconds and recomputed as
  soon as any of its inputs change.
- A headline per row and the three lanes in fixed order.
- Fleet-level lists: machines with a tripped lane B breaker (with reason),
  machines halted (with scope), the fleet halt state, machines whose reports
  are being refused (with reason), "lost" machines (registered, past the
  lost-machine age, with no live row; they keep their plan), report sections
  this dashboard accepted but does not read, how many computers were last
  accepted on a retired session key (count plus up to 20 names; zero means a
  key rotation has finished), the release feed alarm, and the collector's
  own health.
- **Release feed alarm**: last check time, age in days, last error, "stale"
  when the feed HAS been read before and the last check is older than the
  stale limit (a feed never checked is not called stale here), and whether
  every build on offer needs a newer container image.
- Each row is annotated with which reporting categories that computer
  withholds ("NOT REPORTED BY THIS COMPUTER") and its licence (EULA) state;
  a failure here is logged, never fatal.
- **What a non-admin sees**: their own rows; a summary of the whole fleet
  (machines total, ok, unhealthy, out of date) with no names; the count of
  hidden machines; breaker, halted, lost and refused lists trimmed to their
  own; the fleet halt in full; no collector block, no ignored-sections list,
  no key-drain block, no feed alarm.

## Health check
(source: api.py `api_health`)

- `GET /api/v1/health`. Open (no session needed).
  - Always answers HTTP 200, even when unhealthy (a deploy script and the
    macOS onboarding wizard use it as "is the dashboard up").
  - `ok` is true when Syncthing is reachable (or no Syncthing URL is
    configured) AND the background collector thread has not died. The
    container healthcheck reads `ok` from the body.
  - Without a session or a valid fleet credential: only `ok` and `version`.
  - With either: also
    - `code`: which code is running (version, container image, source,
      runtime id, commit); empty on failure;
    - `syncthing_reachable`, `collector_stale` (last poll too long ago),
      `collector_alive`;
    - `folder_errors`; `last_polls` per poll kind (finished time, ok, error);
    - `collector_alarms`: refused enforce or deactivation passes;
    - `rollout`: per platform, the current version, when it was made
      current, machines total, machines on current, how many behind and how
      many refusing. Counts only, no names. `null` (not empty) when it
      cannot be computed;
    - `rollout_platforms`: machines seen per platform (missing platform
      counts as Windows); `null` when it cannot be counted;
    - `feed`: release feed health; `data`: free space on the data volume;
    - `open_alerts`: counts of current error and warn findings, computed
      live; a scan failure reports one error plus `scan_failed`;
    - `notices`: counts of open error and warn diagnoses; a read failure
      reports one error;
    - `cards`: the Timeline Cards mount's state, vault and whether its AI
      features can run;
    - `mounts`: status and detail for each optional mount (`broll`, `music`,
      `ytdl`, `cards`, `sorter`), "unknown" when never recorded.
  - None of the optional blocks can make `ok` false or fail the route.

## Site manifest
(source: api.py `api_site`)

- `GET /api/v1/site`. Open (installers, the onboarding wizard and companions
  read it before signing in). Must never carry a secret, user, project, path
  inventory or token. Every value comes from the site settings stored in the
  database first, then the `DASH_SITE_*` environment value; blank means
  "this deployment was not told". Returns:
  - `schema`: 1;
  - `org_name`; `org_short` (falls back to `org_name`); `support_contact`;
    `product_name` (default "CC Sync"); `brand_logo` (blank = product mark);
  - `tree_name`, `canonical_prefix` (the editor drive), `remote_root`,
    `smb_unc`;
  - `sftp_host`, `sftp_port`, `sftp_hostkey` (from configuration, else read
    on each request from the appliance's SFTP sidecar public key file,
    default `/sftp-hostkey-pub/ssh_host_ed25519_key.pub`, overridable with
    `DASH_SFTP_HOSTKEY_FILE`; only a single `ssh-ed25519 <base64>` line is
    accepted, anything else gives ""), `sftp_chunk_size`,
    `sftp_concurrency`, `sftp_shell_type`, `rclone_remote`;
  - `nas_syncthing_id`: read live from the server's Syncthing (5 s timeout,
    cached for the life of the process once read; a failed read is retried
    at most once per 60 s), else the stored site setting, else
    `DASH_SITE_NAS_SYNCTHING_ID`;
  - `dashboard_url`, `template_folders`, `shared_asset_folders`;
  - `video_extensions`: the fixed list of extensions that travel by rclone
    instead of Syncthing (not configurable);
  - `release_feed_base`: the configured release feed URL with its file name
    removed, only for an `https://` URL; otherwise "";
  - `nas_kind`;
  - `features`: `youtube_download`, `youtube_unblock` (only ever true when
    `youtube_download` is also true), `auto_update`; all default false;
  - `telemetry`: the four site reporting switches (true = reported);
  - `indexer.model_tier`: "good" (smaller local vision model, 8 GB VRAM) or
    "best" (larger, 12 GB).

## Fleet reads for signed-in users
(source: api.py)

- `GET /api/v1/projects`. Signed-in user. The projects list above, scoped
  (other editors' device rows removed for non-admins, with an
  `editors_hidden` count; project totals kept).
- `GET /api/v1/projects/{slug}`. Signed-in user. One project, scoped the same
  way. Refusal: 404 "unknown project '<slug>'".
- `GET /api/v1/transfers`. Signed-in user. The transfers view limited to the
  caller (non-admin) or to `?as=` (admin) or everyone (admin, no `?as=`).
- `GET /api/v1/projects/{slug}/presence`. Signed-in user. The presence view,
  limited the same way. Refusal: 404 unknown project.
- `GET /api/v1/projects/{slug}/devices/{device_id}/missing`. Signed-in user.
  The list of files missing from one Syncthing device in one project, plus
  how many items it needs. Refusals: 404 unknown project; 404 "device not in
  project: <id>" when the device is not in the project OR belongs to another
  editor and the caller is not an admin (404, not 403, so an editor cannot
  learn the device exists).
- `GET /api/v1/editors`. Signed-in user. The fleet machines view above,
  scoped.

## Per-project access grants
(source: api.py `api_project_access`, `set_project_access`)

- `GET /api/v1/projects/{slug}/access`. Admin. Lists the editors explicitly
  granted access to the project. Under per-project access control this is
  the only way a wired editor (who cannot tick) gets into a project.
  Refusal: 404 unknown project.
- `PUT /api/v1/projects/{slug}/access/{editor}`. Admin. Grants one editor
  (name lower-cased and trimmed). Refusals: 404 unknown project; 404
  "unknown editor '<name>'" when the editor is not a known editor. Returns
  `{slug, editor, changed}`. When something changed: an audit row
  `project.access.grant`, a log line, and the background collector is woken
  to apply it.
- `DELETE /api/v1/projects/{slug}/access/{editor}`. Admin. Revokes; same as
  above, audit row `project.access.revoke`; no known-editor check on revoke.
- The project page's access window uses the same function.

## Sign-in, sign-out and session
(source: api.py `api_login`, `api_logout`, `api_me`, `api_session`; refusal
wording and limits from auth.py and sessions.py)

- `POST /api/v1/login`. Open. The JSON twin of the browser sign-in form.
  - Body: `username` (1 to 64 characters, trimmed and lower-cased),
    `password` (1 to 256 characters).
  - Refusals, in order:
    - 503 "login not configured (DASH_SESSION_SECRET unset)" when no session
      secret is configured;
    - 403 "this dashboard is configured for https only (DASH_COOKIE_SECURE=1):
      use the https URL" when the cookie is set to secure-only and the
      request did not arrive over https (by URL scheme or an
      `X-Forwarded-Proto: https` header); not counted as a failure;
    - 401 "bad username or password" on an OIDC (single sign-on) site for
      anyone who is not an admin: the password form is break-glass for
      admins only there; counted as a failure;
    - 429 "Too many sign-in attempts. Try again in <a minute | N minutes |
      about an hour>." with a `Retry-After` header in seconds, when either
      budget is exhausted: 5 failures per username or 40 per client address,
      counted over the last hour; past the limit the wait doubles from 60 s
      up to 1 hour. An invented username is throttled exactly like a real
      one;
    - 503 "login busy: <reason>; try again" when the credential check is busy;
    - 401 "bad username or password" on a wrong password (counted), and also
      for a person an admin deleted (unless they are in the configured admin
      list), so the page never says which half was wrong.
  - A successful sign-in clears only that username's failure count (not the
    address's), creates a revocable server-side session and its cookie
    (HttpOnly, SameSite=Lax), and returns `ok`, `user`, `is_admin` and
    `csrf`: the caller's own anti-forgery token, so a non-browser tool can
    make later write calls.
  - Sessions last up to 100 days (idle and absolute default, from
    sessions.py).
- `POST /api/v1/logout`. Open. Revokes the server-side session and clears the
  cookie. Returns `{ok: true}`.
- `GET /api/v1/me`. Open. Returns the signed-in user (or null) and whether
  they are an admin.
- `GET /api/v1/session`. Signed-in user. Returns user, `expires_at` (UTC
  ISO), `expires_epoch`, `days_left` (2 decimals), used to warn a person as
  the sign-in nears its end. Refusal: 401 "Your sign-in has expired. Sign in
  again."

## Companion sign-in (machine identity)
(source: api.py `api_verify`, `_require_fleet_member`,
`_mint_verify_report_token`)

- `POST /api/v1/verify`. Open. The tray's sign-in. Turns a username and
  password into a long-lived signed identity token for the computer.
  - Body: `username`, `password` (same limits as login), optional
    `companion_version`, `platform`, `arch` (processor, cut to 32
    characters, never refused), `machine` (computer name, trimmed and cut to
    48 characters).
  - Refusals:
    - 503 "identity not configured (DASH_SESSION_SECRET unset)";
    - 429 throttle, same budgets and wording as login;
    - 503 "verify busy: <reason>; try again";
    - 401 "bad username or password" (counted);
    - not a fleet member (admins in the configured admin list always pass):
      - local-account sites: 403 "'<name>' is not an account on this
        dashboard - ask an admin to create it on Settings, Users" (no local
        account); 403 with the suspended/disabled/removed sentence; 403
        "'<name>' is not an editor on this dashboard - ask an admin to give
        the account the editor role" when the account's role is not one of
        the known roles;
      - SMB sites with a NAS configured: 403 "'<name>' is not in the
        'editors' group on the NAS. Ask an admin to add the account in Admin
        > Users"; 503 "cannot confirm fleet membership right now: try again
        shortly" when the NAS cannot be asked (the NAS error is only logged);
      - SMB or OIDC sites with no NAS credential: no membership check at all,
        a warning is logged;
    - 403 with the removed / suspended / disabled sentence (any site).
  - Returns:
    - `token`: the identity token, minted above the person's revocation
      point so a fresh sign-in after a revocation works;
    - `report_token`: the shared fleet token when it is enabled, else "";
    - `report_token_kind`: "shared" or "editor";
    - `role`: "base" for an admin, "editor" otherwise (kept for older
      companions; nothing gates on it);
    - when the shared token is OFF: a fresh per-editor report token, in both
      `report_token` and `editor_report_token`. It is labelled "tray sign-in:
      <machine>" (or "tray sign-in" with no machine name); the same computer
      signing in again revokes its previous one; a person may hold at most 16
      such tokens, and the least recently used beyond that are revoked;
    - `upgrade`: an upgrade offer for this platform, version and processor
      when one exists (same rules as the report reply), or
      `upgrade_none_reason` naming why an available build was withheld.

## Identity checks for the mounted apps
(source: api.py `identity_bar`, `strip_barred_identity`)

- The b-roll, music and YouTube-download apps check the identity header
  themselves; before they see it, the dashboard removes the header when the
  identity was revoked ("this computer's sign-in was revoked: sign in again
  from the CC Sync tray") or the person is suspended, disabled or removed, so
  those apps refuse with their own "identity required" answer. A warning is
  logged naming the mount. Fails open on a database error.

## Sync plan (selection) reads and ticks
(source: api.py `api_get_selection`, `api_tick`, `api_untick`,
`_selection_view`, `_expand_includes`, `tick_capacity_warning`)

- Who may READ a plan for editor X (`_require_selection_read`):
  - a per-editor token bound to X (bar check applies); a per-editor token of
    someone else: 401 "this X-CCSync-Token belongs to a different editor";
  - the shared token plus an identity header naming X (identity tokens signed
    by a retired session key still pass); otherwise 401 "X-CCSync-Identity
    required (and must match the editor) alongside X-CCSync-Token. Sign in
    from the companion tray, or its signing key was retired". DEV ONLY: with
    no session secret configured, the shared token alone is enough;
  - a signed-in session that is X or an admin (a barred account's plan stays
    readable to a session, so an admin can see what RESUME will restore);
  - otherwise 401 "log in, or present X-CCSync-Token".
- `GET /api/v1/selection/{editor}?machine=<hostname>`. Returns:
  - `editor`, `machine` ("" when not named), every computer the person has,
    generation time;
  - `project_roots`: every remembered mapping from a Resolve project name to
    a project (Resolve project, slug, project folder path, source, who set it,
    when);
  - `selection`: per ticked project in queue order: slug, label, folder path,
    position, active flag, `sync_mode` (`full` or `upload_only`), and
    `includes` (borrowed folders from other projects);
  - with a named machine only: per FULL tick of an ACTIVE project, the list
    `originals` of camera originals picked to come down to that computer
    (omitted when empty).
  - With no machine named the answer is the union of all the person's
    computers (what an old companion gets).
- **Borrowed folders (`includes`)**: only links with status ok, only on full
  ticks; each entry gives the folder path `<lender label>/<sub path>`, lender
  slug and label, sub path and `covered`. `covered` is true when the lender
  project is itself full-ticked on the same machine (the companion then does
  not fetch it separately, but uses the relation to warn before the lender is
  removed). A borrowed folder inside one already handed out is dropped
  (longest prefix wins). An upload-only lender covers nothing.
- `PUT /api/v1/selection/{editor}/{slug}?machine=&mode=`. Signed-in session
  only (the editor themself or an admin; companions cannot tick).
  - `mode`: `full` (default) or `upload_only`; anything else 400 "unknown
    sync mode '<x>': use 'full' or 'upload_only'". Ticking an already-ticked
    project in the other mode switches it.
  - Refusals: 401/403 "you can only change your own projects (admins
    excepted)"; 404 "unknown or inactive project '<slug>'"; 409 "this account
    is wired to the server: it works directly off the NAS and syncs nothing,
    so projects cannot be ticked for it" when every machine of the person is
    wired; 404 "'<editor>' has no computer named '<machine>'"; 409
    "'<machine>' is wired to the server: it works directly off the NAS and
    syncs nothing, so projects cannot be ticked for it".
  - No machine named: ticks it on every computer the person has (or in the
    "unassigned" bucket, inherited by their first computer to report, when
    they have none yet).
  - Writes an audit row (tick) recording placements before and after;
    nothing is recorded when nothing changed. Wakes the collector so sharing
    starts at once.
  - Returns the plan as for GET, plus `changed` and `warning`.
  - `warning` (never a refusal): when the project's proxies would not fit
    comfortably on a computer: "<project> is <size> of proxies. <machine>
    has <size> free." plus " That is more than will fit." when larger than
    the free space. Triggered when proxies + 20 GB exceed free space or
    proxies are at least half the free space; silent when either figure is
    unknown; with no machine named, each of the person's computers is
    checked and at most three sentences are joined.
- `DELETE /api/v1/selection/{editor}/{slug}?machine=`. Session (self or
  admin) OR a companion: per-editor token bound to that editor, or shared
  token plus matching identity (bar check applies; same 401 wordings as the
  read). Companions may untick their own projects so the tray can "remove
  this project from this machine" before deleting it.
  - No machine named: removes it from every computer and the unassigned
    bucket.
  - Refusal (companion callers only): 409 "There is no tick for <slug> under
    this computer's name (<machine>), but it is still ticked for another of
    your computers. Nothing was removed. If this computer was renamed, wait
    until the dashboard shows the new name, or untick it on the dashboard."
    when nothing was removed for that machine name but the person still has
    the project ticked elsewhere. A project ticked nowhere answers 200.
  - Audit row (untick; actor "companion:<editor>" for a companion), wakes
    the collector, returns the plan plus `changed`.

## Camera originals on request
(source: api.py `api_put_original_picks`, `apply_original_picks`,
`_clean_pick_rel`, `_originals_refusal`)

- `PUT /api/v1/selection/{editor}/{slug}/originals?machine=<hostname>`.
  Same callers as untick (a session for self or admin, or the editor's
  companion; used by a Resolve menu on the computer itself).
  - Body: `add` (up to 5000 entries of `{rel, is_dir}`, `rel` 1 to 1024
    characters), `remove` (up to 5000 paths), `via` ("resolve" or
    "dashboard", default "dashboard"; anything else 400 "unknown source
    '<x>': use 'resolve' or 'dashboard'").
  - Each path must be inside the project: refused 400 for an absolute path or
    drive letter ("'<p>' is an absolute path: name the file inside the
    project instead"), an empty path ("a pick needs a path inside the
    project"), an invalid segment, any `Proxy` folder ("'<p>' is inside a
    Proxy folder: proxies already come down on their own"), or the project
    marker file ("the project marker is not footage"). Backslashes become
    slashes. Paths are refused, never repaired.
  - Refusals: 400 "say which computer: originals are picked for one computer
    at a time" (no machine); 404 "'<editor>' has no computer named
    '<machine>'"; 404 unknown or inactive project.
  - Additions (never removals) are refused whole with 409 when: the machine
    (or the whole person) is wired ("<machine> is wired to the server: it
    works directly off the NAS, so every original of <label> is already there
    and nothing needs to come down."); the project is not ticked there
    ("<label> is not ticked on <machine>, so nothing of it comes down there.
    Tick it for <machine> first, then choose its originals."); the tick is
    upload-only ("<label> is set to upload only on <machine>, so nothing
    comes down to it. Switch it to full sync on the dashboard first.").
  - Removals are applied first, then additions. Audit rows
    `originals.pick` / `originals.unpick` with the count and a capped list of
    paths. Returns `ok`, `added`, `removed`, and `total_bytes` picked for
    that computer and project.
  - The pick is recorded under the editor's username even when a companion
    made it.

## Server-side file moves
(source: api.py `api_move_project_files`, `move_project_files`,
`_move_proxy_siblings`, `api_project_moves`, `undo_file_move`,
`api_reissue_project_move`, `reconcile_file_moves`)

- All four routes are admin only: 401 "log in first"; 403 "only an admin can
  move files on the server".
- `POST /api/v1/projects/{slug}/move`. Moves a file or folder inside the
  Projects tree on the server, then tells every computer that must follow.
  - Body: `path` (inside the source project, required, up to 1024),
    `to_slug` (destination project, default the same project), `to_path`
    (a folder or a full path inside the destination; empty means the
    destination project's root).
  - Path rules: backslashes become slashes, each segment validated (no
    slashes, no leading ".", no "..", no control characters), no `Proxy`
    segment ("must not name a Proxy folder: proxies move with their
    originals"), never the project marker; must stay inside the tree ("path
    escapes the Projects tree"). Violations: 400 with the reason. The
    Projects folder not configured or missing: 400 "the server's Projects
    folder is not mounted on this dashboard. Ask whoever installed this
    server to create or link the folder: it is a server-side step".
  - Refusals: 404 unknown or inactive project (either end); 404 "nothing at
    <label>/<path> on the server"; 409 "<label>/<path> already exists:
    nothing was moved"; 400 "a folder cannot be moved into itself"; 400 "that
    is where it already is".
  - An existing folder as destination means "into it" (keeps the name).
  - Machines that must follow: every computer that has the source project
    ticked (either mode), plus any computer whose file list says it holds the
    file.
  - Order: a "pending" move record is written and committed first (offered
    to no machine); then the rename, which never overwrites anything at the
    destination (on Linux an atomic no-replace rename, falling back to hard
    link plus unlink for files, or claiming the destination with an empty
    folder for directories; on Windows a plain rename, which already
    refuses).
  - If the rename fails: the record is deleted, an audit row
    `file.move.refused` is written, 503 "the server could not move it:
    <error>".
  - For a single file, its proxies (`Proxy/<same name stem>.*` beside it,
    matched case-insensitively after Unicode normalisation) are moved to
    `Proxy/` beside the new location and renamed to the file's new stem. A
    proxy that cannot follow (something already there, held open, unreadable
    folder) is listed, never fatal. A case-only rename goes through a
    temporary `.ccsync-move-<name>` name.
  - The record ends "done", or "partial" with "these proxies did not move:
    ...". Returns `ok`, `move_id`, `state`, from, to, `is_dir`,
    `proxies_moved`, `proxies_failed`, and the machines to follow. Answers
    HTTP 207 instead of 200 when a proxy failed.
  - The machines receive the move as a command on their next report reply.
- `GET /api/v1/projects/{slug}/moves`. Admin. Lists the project's moves and
  every move still awaiting machines.
- `POST /api/v1/projects/{slug}/moves/{move_id}/undo`. Admin. Puts a move
  back by making the reverse move through the same machinery, restoring the
  exact original path and name.
  - Refusals: 404 "no move <id> on this project"; 409 "that move has already
    been put back"; 409 "one of the computers could not apply this move, so
    its copy is still at the old path. Sort that computer out first, then put
    it back."; plus every refusal of a move (for example something has been
    recreated at the old path).
  - For a folder, a NAS snapshot is attempted first, named
    `file-move-undo-<id>`; failure only logs.
  - Every computer the original move reached is added to the undo's targets
    as well. The original is marked "undone"; audit row `file.move.undo`.
- `POST /api/v1/projects/{slug}/moves/{move_id}/reissue?editor=&machine=`.
  Admin. Offers an expired move to one computer again. Refusals: 404 no such
  move on this project; 409 "that computer has already answered this move".
- **Background reconciliation** (at boot and once per collector cycle):
  every move still "pending" is checked on disk:
  - only the destination exists: completed ("completed after an interrupted
    move") and the machines are told;
  - only the source exists: the record is dropped (the move never happened);
  - both or neither: left pending, offered to nobody, and listed as an alarm
    (id, from, to, whether both exist, the two projects) that the project
    page shows;
  - in the same pass, a move command that was DELIVERED to a computer and
    never answered expires (logged: "that computer may re-upload the old
    path until it is re-issued"); an undelivered one never expires.

## Shared folders between projects (folder links)
(source: api.py `api_add_project_link`, `api_remove_project_link`,
`add_project_link`, `remove_project_link`, `_sync_link_rows`)

- Who may call: an admin, or a signed-in editor who has this project ticked.
  Refusals: 401 "log in first"; 403 "only an admin or an editor syncing this
  project can change its shared folders".
- The declaration lives in the borrowing project's marker file on the server
  (its `includes` list, other keys preserved); the dashboard's copy is
  refreshed at once after every edit.
- Shared refusals: 503 when the Projects folder is not mounted; 404 unknown
  or inactive project; 409 "this project's folder marker does not carry its
  identity; repair the marker before editing its shared folders".
- `POST /api/v1/projects/{slug}/links`. Body `path` (1 to 1024 characters).
  A path typed in label form ("2026/FF5/...") gets the Projects folder name
  prefixed. Refusals: 422 "cannot share that folder: <reason>" when the path
  does not resolve to a valid folder of another project; 422 "this project
  already shares <max> folders; remove one first" at the cap. Adding a path
  already declared changes nothing. Each entry records who added it and
  when. Returns `changed`, the declared path and the project's links.
- `DELETE /api/v1/projects/{slug}/links?path=`. Removes the matching
  declaration (the `includes` key is deleted when it becomes empty). Returns
  `changed`, the declared path and the links.
- Link statuses after the refresh: ok, missing, lender inactive ("the lending
  project is not active on the dashboard"), or the validator's own failure.

## Resolve project to destination mappings (project roots)
(source: api.py `api_project_roots`, `api_set_project_root`,
`may_first_claim`)

- `GET /api/v1/project-roots`. Signed-in user. Lists every mapping (Resolve
  project name, project slug, folder path, source, who set it, when).
- `PUT /api/v1/project-roots`. Signed-in user, tiered:
  - Body: `resolve_project` (1 to 256 characters), `slug` (absent or blank =
    delete the mapping; it is re-detected on the next report).
  - Delete, or change an existing mapping: admin only, refused 403 "admins
    only: destination roots are fixed once set" (401 "log in first" with no
    session).
  - First mapping of an unmapped name: an admin always; an editor only for a
    Resolve project one of their own computers has reported, else 403
    "'<name>' is not a Resolve project any of your computers has reported.
    Open it in Resolve first, or ask an admin". First write wins: 409
    "already mapped. Ask an admin to change it." when someone got there
    first.
  - 404 "unknown or inactive project '<slug>'".
  - Returns `ok` and the full mapping list.
- The generic admin refusal used by about 45 routes is 401 "log in first" /
  403 "admins only".

## The "my queue" panel data
(source: api.py `build_queue_view`; used by the HTML pages, no route of its
own in this range)

- For one editor (optionally one named computer): each ticked project in
  queue order with label, position, sync mode and an upload-only flag,
  whether the project no longer exists, whether it is the project the
  companion is working on right now, completion, items and bytes needed,
  rate and ETA (the rclone lane's figures preferred over Syncthing's), a
  status (green when nothing is known), and the borrowed folders it pulls in
  (ok links only: sub path and lender label).
- Also: every computer of the person (named in the confirm of a person-level
  untick), the open Resolve project and the project it was detected as, its
  label, and whether that mapping came from an editor, an admin or
  auto-detection. With a computer named, that computer's own last report is
  used; without, the person's most recent report.
- A list of not-yet-ticked projects is still computed. UNREACHABLE: nothing
  renders it any more (ticking moved to the sidebar tree).

## Creating, adopting and archiving projects
(source: api.py `api_create_project`, `create_tree_project`,
`api_link_folder`, `adopt_folder`, `_register_project`,
`api_archive_project`)

- `POST /api/v1/projects`. ANY signed-in user (401 "log in first"
  otherwise). Creates `Projects/<parent>/<name>` on the server.
  - Body: `parent_rel` (up to 512, default the Projects root), `name` (1 to
    128), `resolve_project` (optional Resolve project name to map to it, up
    to 256), `use_existing` (default false).
  - Every refusal is 422 with the reason:
    - Projects folder not mounted (sentence above);
    - "parent folder does not exist: <parent or (root)>";
    - name rules: "project name is required", "must not contain slashes",
      "must not start with '.' or contain '..'", "must not contain control
      characters";
    - "cannot create a project inside another project (<path>)" when any
      ancestor folder carries a project marker;
    - "that folder already contains a project (<path> [(+N more)]). Pick that
      one instead" when the target folder has a marked project below it;
    - "that name produces an empty identifier. Use letters or numbers";
    - "<path> is an archived project. An admin can put it back with
      "Unarchive" under "Archived projects" on the Sync plans page, and it
      keeps its folder, its files and its ticks";
    - "that folder is already a project with a different identity (<slug>)";
    - "Projects/<path> already exists. Use "Use this folder" to point the
      project at it instead of creating another folder inside it" when the
      folder exists unmarked and `use_existing` is false;
    - "a different project already uses this identifier: <label>. Pick
      another name";
    - "could not create the folders on the NAS. Ask an admin to check the
      dashboard log" (the real error, which names server paths, is only
      logged);
    - "'<name>' is not a Resolve project any of your computers has reported.
      Open it in Resolve first, or ask an admin to set the mapping" (checked
      before anything is registered).
  - Creates the folder, the site's template subfolders (from the site
    settings, else the environment), and the project marker file recording
    who created it (an earlier creator's name is kept on a retry).
  - The project identifier (slug) is derived from the folder path.
  - Same request again for the same path is harmless (idempotent).
  - Per-project access control sites: a newly made folder is closed to that
    project's own group, and the creator is granted access (also on the
    creator's own retry of an unfinished create). Inert on shared sites.
  - Registers the project as active immediately (its Syncthing folder
    follows on the collector's next provisioning pass) and, when a Resolve
    project was given, writes the first mapping for it (first write wins).
  - Audit row `project.create` (label, whether an existing folder was used).
  - Returns `ok`, slug, path, whether the mapping was written, and all
    mappings.
- `POST /api/v1/projects/link`. Any signed-in user. "Use this folder": claims
  an existing folder as a project without touching its contents (no template
  subfolders).
  - Body: `rel` (1 to 512), `resolve_project` (optional).
  - Refusals (422): Projects folder not mounted; path rules; "pick a folder:
    the Projects root itself cannot be a project"; "folder does not exist:
    <path>"; "this folder is inside an existing project (<path>)"; contains
    a project; empty identifier ("that folder name produces an empty
    identifier"); archived project; "a different project already uses this
    identifier: <label>"; "could not write the project marker: <error>";
    "this folder claims the identity of <label>, which still exists. Resolve
    the duplicate on the NAS first" (a copied, not moved, project); Resolve
    project not reported by the caller.
  - A folder that already carries a marker keeps that identity (a moved
    project is re-adopted at its new path).
  - No audit row is written for an adopt.
- `POST /api/v1/projects/{slug}/archive`. Admin. Body `archived` (default
  true; false restores).
  - Archiving deletes nothing: folder, marker, files and ticks stay. The
    project leaves the tick lists, the assignments grid and the queue, and the
    collector removes its Syncthing shares on its next pass. On per-project
    access sites the group membership is withdrawn while archived and
    restored on unarchive (stated in the route's description; done outside
    this file).
  - Refusals: 404 "no project called '<slug>'"; 409 "'<slug>' is already
    archived"; 409 "'<slug>' is not archived".
  - Audit rows `project.archive` (label, editors who have it ticked) and
    `project.unarchive`. Returns `ok`, slug, archived, and the editors who
    have it ticked.

## Share-removal brake controls
(source: api.py `api_approve_enforce_removals`, `api_set_enforce_allowance`;
db.py for the refusal wording)

- Background: the collector refuses to remove more Syncthing shares in one
  pass than a limit allows, and records the refused list.
- `POST /api/v1/enforce/approve-removals`. Admin. "APPLY THESE N REMOVALS".
  - Body `count`: the number the admin saw on the banner.
  - Approves exactly the (folder, computer) pairs the standing refusal names,
    for one hour. Refusals (409): "no share removals are waiting for
    approval"; "the list changed: N removal(s) are waiting now, not M. Reload
    and check them again."; "too many removals to approve one by one; raise
    the per-computer allowance under Settings, then Sharing safety, instead"
    (the refused list was truncated).
  - Audit row with the count and up to 50 pairs; the collector is woken; a
    warning is logged. Returns `approved` and `expires`.
- `POST /api/v1/enforce/allowance`. Admin. Body `per_computer`: share
  removals allowed per computer in one pass, a whole number 0 to 100 (else
  422 "must be a whole number from 0 to 100"); 0 restores the flat limit.
  Stored as a site setting with who set it; audited (before and after);
  collector woken. Returns the value.

## Users page (admin): view
(source: api.py `api_admin_users`, `build_admin_users_view`,
`build_computers_view`)

- `GET /api/v1/admin/users`. Admin. Returns:
  - `auth_method` (local, smb or oidc); on local sites, every local account;
  - `computers`: every registered computer (editor, hostname, platform,
    Syncthing device id, companion version, last seen, mode, number of
    ticked projects on it);
  - suspended people with each suspension's details; when the suspension
    table cannot be read (database busy), an empty list plus
    `suspensions_unreadable` so the page can say so;
  - SSH keys offered by editors' setup wizards and waiting for approval, with
    the same "unreadable" flag;
  - when a NAS is configured: the NAS editor accounts (username, uid, full
    name, SMB enabled, has an SSH key, home, locked), never including the
    stack's own service account; `truenas_error` when the NAS could not be
    asked;
  - Syncthing devices needing approval: devices configured on the server's
    Syncthing whose name does not resolve to a known editor ("unmapped"),
    and devices waiting in Syncthing's pending list ("pending"); each with a
    suggested owner and computer when a companion already reported that
    device id; `syncthing_error` when Syncthing could not be asked;
  - `known_editors`: the names a device may be approved under (editors the
    fleet knows plus local accounts);
  - `fleet_only_editors`: people the fleet knows who have no account (only
    these can be cleaned up by DELETE); empty when the NAS could not be read.
  - With no NAS configured the NAS and device halves are simply empty.
  - The two backends fail independently.
- A device id typed for approval must look like 8 dash-separated groups of 7
  characters A-Z and 2-7 (upper-cased first), else: "'<id>' is not a
  Syncthing device ID. Expected 8 groups of 7 characters (A-Z, 2-7)
  separated by dashes, e.g. P56IOI7-... Copy it whole: it is 63 characters.
  Adding a malformed ID creates a device entry that can never connect."
  (The approve route itself is outside this range; the helper is here.)
- Approving a device under a name that is not a known editor is refused
  unless "create new editor" is ticked: "'<name>' is not an editor this
  dashboard knows. Pick the OWNER of this computer: one editor can own
  several computers, so a second computer takes the same username as the
  first. Tick CREATE NEW EDITOR if this really is a new person." (helper
  here, route outside this range).

## Users page (admin): accounts
(source: api.py `api_admin_create_user`, `api_admin_set_password`,
`api_admin_disable_user`, `api_admin_suspend_user`, `api_admin_delete_user`,
`delete_user_everywhere`, `_forget_elsewhere`)

- `POST /api/v1/admin/users`. Admin. Create (or update) an account.
  - Body: `username` (1 to 32), `ssh_pubkey`, `full_name`, `password`
    (optional; when given, at least the minimum password length), `role`
    (local sites: "admin" or "editor", default editor).
  - Local sites: creates a local account; a blank password generates a
    random one returned ONCE as `generated_password` and never shown again;
    an SSH key, when given, is added. Errors from the account store: 422.
    The person is recorded as a known editor.
  - SMB/NAS sites: 503 "DASH_NAS_PW is not configured on the dashboard"
    with no NAS credential (or 503 with the error for an unknown NAS kind);
    422 "username must start with a letter and contain only lowercase
    letters, digits, '.', '_', '-'"; 422 "does not look like an OpenSSH
    public key"; a blank key is allowed for a NEW account only, else 422
    "<name> already has an account. Leave the key blank only when creating a
    new one: to change this editor's key, paste the new key here"; NAS errors
    502. Creates or updates the NAS account in the editors group with that
    key; sets the password when given (then audited as a password reset via
    "create", and every session of that person is signed out). Records the
    person as a known editor.
  - Returns the result and the refreshed Users view.
- `POST /api/v1/admin/users/{username}/password`. Admin. Body `password` (at
  least the minimum length). Local sites: sets it (422 on store errors). NAS
  sites: username rule (422), 503 without NAS, NAS errors 502 (the NAS side
  refuses system accounts and anyone outside the editors group). Audit row
  `user.password_reset` (method and door, nothing about the password). Then
  signs that person out of every browser session, except the admin's own
  current session when they reset their own password. Returns
  `sessions_revoked`.
- `POST /api/v1/admin/users/{username}/disable`. Admin, local sites only
  (400 "this action is only available with DASH_AUTH_METHOD=local"). Body
  `disabled` (default true; false re-enables).
  - Refusals: 404 "'<name>' is not a local account"; 409 "you cannot disable
    the account you are signed in as - sign in as another admin to disable
    this one"; 409 "this is the last enabled admin account - create another
    admin before disabling it"; other store guards 409.
  - Disabling revokes every browser session and every per-editor report
    token of that person (so their computers stop reporting). Re-enabling
    restores only the password, not old sessions or tokens.
  - Audit rows `user.disable` / `user.enable`. Returns counts purged and the
    refreshed view.
- `POST /api/v1/admin/users/{username}/suspend`. Admin, any sign-in method.
  Body `suspended` (default true; false resumes), `reason` (free text up to
  255, shown on the row and in the audit, never sent to the computer).
  - Effects of suspending: the person's computers are refused on report and
    on every companion door with the suspended sentence; the collector
    removes their Syncthing shares; the plan is kept untouched so RESUME
    restores it exactly. Nobody is signed out of the browser.
  - Refusals: 422 "not a valid username"; 409 "you cannot suspend the
    account you are signed in as - sign in as another admin to suspend this
    one"; 404 "'<name>' is not an editor this dashboard knows".
  - Audit rows `user.suspend` (with reason) / `user.resume`.
- `DELETE /api/v1/admin/users/{username}`. Admin. Deletes a person from the
  whole product, in this order:
  1. the local account row (local sites); its own guards (self, last
     enabled admin) refuse with 409 before anything irreversible;
  2. every Syncthing device of theirs (from the registry, plus any configured
     device whose label is their username) is removed with its shares; if
     Syncthing cannot be asked, everything is rolled back: 502 "syncthing
     could not be reached (<error>), so nothing was deleted - try again once
     it is up";
  3. the NAS account (NAS sites); on failure the local rows are rolled back
     (devices stay removed): 502 "<nas kind>: <error> - the account and the
     fleet records were left in place";
  4. every fleet record of theirs (computers, plans and so on), and a
     permanent "removed" marker so their computers are refused from then on
     (even where the account still exists on the NAS or the identity
     provider); the audit row `user.delete` names them only by a pseudonym,
     with counts;
  5. after the commit: every report token and browser session revoked, then
     the revoked tokens deleted, the session rows and sign-in attempt rows
     deleted, and their name replaced by the pseudonym in the YouTube
     download ledger and the client folders. Each of these last steps is
     best effort and adds a warning instead of failing ("their revoked report
     tokens were kept; they are deleted 180 days after revocation", "their
     signed-out sessions were kept until they expire", "their name could not
     be removed from <YouTube requests | client folders>: the dashboard log
     names the reason").
  - Other refusals: 422 "not a valid username"; 409 "you cannot delete the
    account you are signed in as - sign in as another admin to remove this
    one"; 502 "<nas kind>: <error> - nothing was deleted" when the NAS cannot
    be asked whether the account exists; 404 "'<name>' is not an account or
    an editor this dashboard knows".
  - A name the fleet knows but no backend has (a device approved under an
    unprovisioned name, an account removed at the NAS by hand) can be
    deleted too.
  - Whether the person was an admin is captured before deletion (affects how
    their name is pseudonymised in the audit log; done in db.py).
  - The display-name cache is cleared. Returns what was deleted (account,
    computers, devices removed, sessions and tokens revoked and deleted),
    warnings, and the refreshed view.
- **Forget one computer** (`forget_machine_everywhere`, used by `DELETE
  /api/v1/admin/machines/{editor}/{machine}`, which starts after line 6600
  and is described in part 2): removes that computer's Syncthing device and
  shares first (502 "syncthing could not be reached (<error>), so the
  computer was not removed - try again once it is up"), then its records and
  plan; 404 "no computer '<machine>' for '<editor>'"; audit `machine.forget`.
  Not a revocation: the answer says "a companion still running and signed in
  on this computer will register it again on its next report".

## SSH keys
(source: api.py `api_submit_ssh_key`, `approve_pending_ssh_key`,
`_install_nas_key_keeping_others`, `api_admin_dismiss_ssh_key`,
`api_admin_add_ssh_key`, `api_admin_remove_ssh_key`)

- `POST /api/v1/ssh-key`. Open, but needs a valid identity header for the
  same username (identity tokens from a retired key accepted). The setup
  wizard offers the public key it just generated. Grants nothing: the key
  waits for an admin.
  - Body: `username` (1 to 64), `ssh_pubkey` (1 to a fixed maximum length),
    `machine` (which computer made it, up to 128; for display only).
  - Refusals: 503 "identity not configured (DASH_SESSION_SECRET unset)"; 401
    "X-CCSync-Identity required: sign in from the installer or the companion
    tray first"; 403 with the removed / suspended / disabled sentence; 422
    "does not look like an OpenSSH public key"; 422 when no fingerprint can
    be computed.
  - Stores the key with its fingerprint, audit row `ssh_key.offered`.
    Returns `pending: true` and the fingerprint.
- `POST /api/v1/admin/users/{username}/keys/pending/approve`. Admin. Body
  `fingerprint`. Installs the waiting key on the account, then drops it from
  the queue.
  - Local sites: added to the local account (a key already present is fine;
    other errors 422).
  - NAS sites: ADDS the key, keeping the account's other keys (every
    computer of a person offers its own key). If the NAS backend can append,
    it does; otherwise the existing key lines are kept verbatim and the new
    one appended unless the same key (type and body) is already there. Where
    the NAS cannot show existing key text, the approved key becomes the only
    key (logged). 503 without a NAS; 502 "<nas kind>: <error> - the key is
    still waiting" on a NAS error (the offer is kept).
  - Refusal: 404 "no key waiting for <name> with that fingerprint".
  - Records the person as a known editor; audit `ssh_key.approve`.
- `POST /api/v1/admin/users/{username}/keys/pending/dismiss`. Admin. Body
  `fingerprint`. Throws the offer away (nothing is revoked; the computer can
  offer again). Audit `ssh_key.dismiss` when something was dropped.
- `POST /api/v1/admin/users/{username}/keys`. Admin, local sites only (400
  otherwise). Body `key_text` (required), `label`. Adds a key to the local
  account (served to the SFTP sidecar). 422 on store errors.
- `DELETE /api/v1/admin/users/{username}/keys/{fingerprint}`. Admin, local
  sites only. Removes it; returns `removed`.

## Browser sessions and computer sign-ins (admin)
(source: api.py `api_admin_sessions`, `api_admin_revoke_sessions`,
`api_admin_revoke_identity`)

- `GET /api/v1/admin/sessions`. Admin. Every recorded browser session, with
  the session id cut to its first 12 characters. Works without the NAS.
- `POST /api/v1/admin/users/{username}/sessions/revoke`. Admin. Signs that
  person out of every browser. Refusals: 422 "not a valid username"; 503
  "sessions are not being recorded". Returns the count; logged.
- `POST /api/v1/admin/users/{username}/identity/revoke`. Admin. Withdraws
  every computer identity token issued to the person so far ("I think a
  laptop was taken"): their computers are refused on the next report and the
  tray asks them to sign in again, which works at once. Nothing deleted, no
  plan touched. 422 for an invalid username. Audit `user.identity_revoke`
  with the new generation number; returns `generation`.

## Per-editor report tokens (admin)
(source: api.py `api_admin_report_tokens`, `api_admin_create_report_token`,
`api_admin_revoke_report_token`, `build_report_tokens_view`)

- `GET /api/v1/admin/report-tokens`. Admin. Returns every live token, each
  with the computers whose LAST report used it; plus `shared_machines`,
  `shared_count`, `editor_count`: how many computers' last report still used
  the shared fleet token versus a per-editor token (tells an operator when it
  is safe to switch the shared token off).
- `POST /api/v1/admin/report-tokens`. Admin. Body `username` (1 to 32,
  username rule, 422 otherwise), `label` (up to 64). Mints a token; the
  secret is in this one response only (only a hash is stored). Logged.
- `DELETE /api/v1/admin/report-tokens/{token_id}`. Admin. Revokes it.
  Refusal: 404 "no such live token". Never refused for being in use; the
  answer says who is affected: "Revoked. <A | A and B | A, B and N more> was
  using this token and will stop reporting within a minute. Give that editor
  a new token." or "Revoked. No computer's last report used this token, so
  nothing should stop reporting."

## Fleet halt
(source: api.py `api_fleet_halt`, `api_set_fleet_halt`; default length and
expired-extend wording from db.py)

- `GET /api/v1/fleet/halt`. A signed-in user or any valid fleet credential
  (per-editor or enabled shared token). 401 "log in first" otherwise.
  Returns the halt: active, expired, reason, who set it, when, when it
  expires, how many times extended.
- `POST /api/v1/fleet/halt`. Admin. Stops (or releases) syncing on every
  computer at once; delivered on each computer's next report reply, so it
  survives a dashboard restart and reaches machines that were offline. A
  companion refuses to release a fleet halt locally.
  - Body: `active`, `reason` (up to 500; shown in every editor's tray),
    `hours` (above 0, at most 720; default 24 hours), `extend` ("KEEP
    HALTED": keeps the original reason, setter and start time and only moves
    the expiry).
  - Refusals: 422 "say why: the reason is shown in every editor's tray (at
    least 3 characters)" for a new halt; 422 for extending a halt that has
    already ended with no reason ("Syncing already started again at <time>.
    To stop it again, give a reason." or "Nothing is stopped, so there is
    nothing to keep stopped. Stop syncing with a reason.").
  - The halt expires by itself at its expiry time. Logged as "FLEET HALT
    ENGAGED/released".

## Push an update to one computer
(source: api.py `api_push_machine_update`, `_command_delivery`,
`fled_push_refusal`)

- `POST /api/v1/admin/machines/{editor}/{machine}/update`. Admin. "UPDATE
  NOW" on someone's behalf: the computer applies the named build on its next
  report, only if the signed offer it holds is that exact version and only
  when swapping the program would not kill work in progress (checks on the
  companion).
  - Body (optional): `version` (up to 32). Absent: the current companion
    package for that computer's platform.
  - Refusals: 404 "no computer '<machine>' for '<editor>'"; 409 "no current
    companion package is published for that computer's platform"; 404
    "<version> is not in this channel for <platform>"; 409 "<machine> kept
    crashing on <version> and rolled itself back, so it will not install
    that build again, not even from UPDATE NOW. Publish a fixed build and it
    is offered as usual."
  - A build that is published but not current ("staged") may be pushed: this
    makes it available to that one computer only (a canary).
  - Returns: version, whether a request was already waiting, whether
    staged, and a delivery note:
    - `applies`: "on that computer's next report, usually within 30 s. It
      was last heard from <N s | N minutes | N hours | N days> ago"; or,
      when last heard from 24 hours ago or more, "when that computer next
      reports. It was last heard from ..., so this may sit for a while"; or,
      with no report on record, "when that computer next reports. Nothing on
      record says when it last did"; plus ", as a targeted offer of a staged
      build" for a staged build;
    - `queued_for`, `last_report_at`, `last_report_age_seconds`, `stale`
      (no report or 24 hours or older). It warns, never refuses.

## Looks redundant or overlapping

- `GET /api/v1/projects/{slug}` and `GET /api/v1/projects` carry the same
  per-device rows; the single-project view adds media and links.
- `GET /api/v1/project-roots` returns the same list that every
  `GET /api/v1/selection/{editor}` already includes as `project_roots`.
- `GET /api/v1/me` and `GET /api/v1/session` both answer "who am I"; session
  adds expiry.
- `POST /api/v1/login` and the HTML sign-in form are twins (the route
  comment says both call one refusal helper); likewise every admin route here
  has an htmx twin in ui.py (users, tick, file moves, links, password).
- Disable (local only), suspend (any site), revoke sessions, revoke computer
  identities, revoke report tokens, and delete are six overlapping "stop this
  person" controls, each covering a different subset of sessions, tokens,
  shares and reporting.
- Three credential types reach the companion doors (shared token, per-editor
  token, identity header), and `/verify` can also mint per-editor tokens
  ("tray sign-in") beside the admin's manually minted ones.
- `POST /api/v1/projects` with `use_existing: true` and `POST
  /api/v1/projects/link` both adopt an existing folder; the first also adds
  the template subfolders.
- The "my queue" view still computes an `available` list nothing renders.
- `/health` carries `rollout`, `rollout_platforms`, `open_alerts`,
  `notices`, `cards`, `mounts`, `feed`, `data`, `collector_alarms`: many of
  these duplicate admin pages and the fleet view (the feed alarm also appears
  in `/editors`).
- File moves are reconciled at boot and every collector cycle; expired
  deliveries are both auto-expired and manually re-issuable.

## Claims the code does not back

- The module docstring says "The report endpoint is the only write path
  exposed over HTTP"; this range alone has dozens of write routes (ticks,
  moves, users, halts, tokens).
- `api_verify` comments say "CR-18 stands: /verify never mints a cce1
  token"; the same route mints one whenever the shared token is disabled.
- `revoke_sessions_after_password_reset` says a leaked password's session
  lasted "up to seven days"; sessions.py's defaults are 100 days.
- `_nas_client_or_503` says "DASH_NAS_PW is not configured on the dashboard"
  for every NAS kind and auth configuration, including ones not configured by
  that variable (a later comment in `_require_fleet_member` notes the same
  wording was wrong there).
- `api_archive_project`'s description of group membership being withdrawn
  and restored is not done in this file; not verified.
- `api_site` docstring: "Every string defaults to """; `product_name`
  defaults to "CC Sync" and `sftp_hostkey` may come from a sidecar file.
- `_scope_editors_view` comments call the fleet halt "deliberately NOT
  redacted"; true, but the per-machine `fleet_halt_active` flag only appears
  on rows the viewer may see.

## Could not determine

- The exact behaviour of the many db.py and health.py helpers these routes
  call (the "why not syncing" sentence wording, the headline wording, lane
  chip colours, freshness thresholds, lost-machine age, clock-skew threshold,
  the share-removal limit formula `max(DASH_ENFORCE_MAX_REMOVALS, per
  computer x computers)` stated only in a docstring); they belong to other
  sections.
- (Settled by a constant lookup, not deeper reading: local roles are
  "admin" and "editor"; at most 32 shared folders per project; an offered
  SSH key is at most 4096 characters; the minimum password length a
  dashboard sets is 12 characters.)
- Coverage: api.py lines 1 to 6628 were read in full (the last route,
  `POST /admin/machines/{editor}/{machine}/update`, ends at 6628); lines
  6629 onward belong to part 2. `fled_push_refusal` and `_upgrade_info`
  (defined after 6600) were read only for their refusal sentence and
  signature.
