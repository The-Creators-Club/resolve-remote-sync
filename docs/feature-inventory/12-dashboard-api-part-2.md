# Dashboard: the API, part 2

Scope: the JSON routes defined in `dashboard/src/ccsync_dashboard/api.py` from line 6400 to the end of the file. Every path below is under the prefix `/api/v1`. Terms used throughout:

- **Admin**: a person signed in to the dashboard in a browser whose account is an administrator. An admin-only route answers `401 "log in first"` with no session and `403 "admins only"` for a signed-in non-admin.
- **Companion**: the tray app on an editor's computer. It authenticates with a **fleet credential** sent in the `X-CCSync-Token` header: either the **shared report token** (one secret for the whole fleet, can be switched off by the operator) or a **per-editor token** (starts `cce1.`, bound to one editor's name).
- **Identity token**: a signed token in the `X-CCSync-Identity` header that the companion gets when its editor signs in at the tray. It names the editor and never expires; it can be revoked by an admin, and it stops verifying if the dashboard's session secret changes (a "retired" previous secret is still accepted during a rotation).
- **Report reply**: the answer to the companion's 30-second status report. It is the only channel the dashboard has back to an editor's computer; every "command" below is parked on the server and delivered on that computer's next report.
- **Barred account**: an editor whose account is suspended, disabled (local accounts only), or removed.

## Fleet halt (stop all syncing everywhere)
(source: api.py `api_fleet_halt`, `api_set_fleet_halt`; db.py `set_fleet_halt`, `get_fleet_halt`)

- `GET /fleet/halt`: read the fleet-wide halt.
  - Who: any signed-in user, or a companion holding either fleet credential (the login gate lets this one GET through with a fleet token). Otherwise `401 "log in first"`.
  - Returns `halt` with: `active`, `expired`, `reason`, `set_by`, `set_at`, `expires_at`, `extended` (how many times it was extended).
  - A halt whose expiry has passed reads as not active with `expired: true`. A stored halt that cannot be parsed reads as not halted.
- `POST /fleet/halt`: engage, extend or release the halt. Admin only.
  - Body: `active` (bool, required), `reason` (up to 500 characters), `hours` (greater than 0, at most 720 = 30 days; default 24), `extend` (bool, the "KEEP HALTED" button).
  - Refusal `422 "say why: the reason is shown in every editor's tray (at least 3 characters)"` when engaging a new halt (`active` true, `extend` false) with a reason shorter than 3 characters after trimming.
  - Engaging: stores the halt with the reason, who set it, when, and an expiry `hours` from now (24 hours by default). The halt ends by itself at the expiry.
  - Extending (`extend` true) while a halt is active: keeps the original reason, setter and start time, moves the expiry to `hours` from now, and counts one more extension.
  - Extending when no halt is active and no reason of at least 3 characters is given: refused `422` with "Syncing already started again at <time in site time zone>. To stop it again, give a reason." or, if nothing was ever stopped, "Nothing is stopped, so there is nothing to keep stopped. Stop syncing with a reason." Extending with a real reason after expiry starts a fresh halt.
  - Releasing (`active` false): clears the halt, no reason required.
  - Every engage, extend and release is appended to a history of the last 20 halts (who, when, action, reason, expiry) and written to the audit log (`fleet.halt_set` or `fleet.halt_clear`). The dashboard log gets a WARNING "FLEET HALT ENGAGED/released by <admin>: <reason>".
  - Returns `{ok, halt}`.
  - Delivery: every report reply carries `commands.halt` (see the report route). The halt is deliberately fleet-wide only; there is no per-machine halt here.

## Parked per-machine commands: how delivery is worded
(source: api.py `_command_delivery`, `_ago_phrase`)

- The admin buttons UPDATE NOW, RESUME (proxy download) and ASK THIS MACHINE WHY return, beside `ok`, a delivery estimate:
  - `queued_for` ("editor/machine"), `applies` (a sentence), `last_report_at`, `last_report_age_seconds`, `stale` (true when there is no report on record or it is 24 hours or older).
  - `applies` wording: no report on record: "when that computer next reports. Nothing on record says when it last did"; last report 24 hours or older: "when that computer next reports. It was last heard from <age>, so this may sit for a while"; otherwise "on that computer's next report, usually within 30 s. It was last heard from <age>". For a pushed staged build it adds ", as a targeted offer of a staged build".
  - Age wording: under 90 s "N s ago", under 90 minutes "N minutes ago", under 48 hours "N hours ago", else "N days ago".
  - These routes warn about a silent machine; they never refuse because of it.
- `pending_before` in those answers says whether the same request was already parked before this click.

## Admin actions on one computer
(source: api.py `api_push_machine_update`, `api_cancel_machine_update`, `api_forget_machine`, `forget_machine_everywhere`, `api_resume_machine_lane_b`, `api_cancel_machine_lane_b_resume`, `api_copy_machine_plan`; db.py `request_machine_update`, `copy_machine_plan`)

The `{editor}` path part is trimmed and lower-cased; `{machine}` is trimmed.

- `POST /admin/machines/{editor}/{machine}/update` ("UPDATE NOW" for one computer). Admin only.
  - Body (optional): `version` (up to 32 characters). Absent means the current companion build for that computer's platform.
  - Refusals:
    - `404 "no computer '<machine>' for '<editor>'"` when the computer is not in the registry.
    - `409 "no current companion package is published for that computer's platform"` when no version is given and nothing is current.
    - `404 "<version> is not in this channel for <platform>"` when the named version is not published for that platform.
    - `409` with "<machine> kept crashing on <version> and rolled itself back, so it will not install that build again, not even from UPDATE NOW. Publish a fixed build and it is offered as usual." when the version is the one this computer's crash-loop guard fled from (compared as text and as the numeric version, so "0.9.70+dirty" equals "0.9.70").
  - A version that is published but not current (a "staged" build) is accepted: pushing it is how a staged build reaches exactly one canary computer.
  - Effect: parks the request on the computer (version, who, when, and the version the computer was on, looked up from its last report). Any earlier "cannot be offered" verdict on that computer is cleared, so the new push is undecided until the next report. Audit row `machine.update_push`.
  - Returns `ok`, `editor`, `machine`, `version`, `pending_before`, `staged` (true when the build is not current), and the delivery estimate.
  - Nothing installs from the server: the companion takes the build only if the signed offer it already holds is that exact version, above its downgrade floor, and only when replacing the program would not interrupt work.
  - A parked update request older than 14 days is dropped by the dashboard (not by this route).
- `DELETE /admin/machines/{editor}/{machine}/update`: withdraw a pushed update. Admin only. Always `{ok: true}`, even if nothing was pending. Withdrawing also ends the targeted offer of a staged build to that computer.
- `DELETE /admin/machines/{editor}/{machine}` ("Forget" a computer). Admin only.
  - `404` when the registry has no such computer.
  - First removes that computer's Syncthing device (and with it its folder shares) from the server's Syncthing; if Syncthing cannot be reached, `502` "syncthing could not be reached (...), so the computer was not removed - try again once it is up" and nothing is removed.
  - Then deletes the computer's records (registry row, sync plan rows, status rows) and audits `machine.forget`.
  - Returns `devices_removed`, `deleted` (counts per kind of record) and a `note`: "a companion still running and signed in on this computer will register it again on its next report". This is not a revocation: the person keeps their account and tokens.
- `POST /admin/machines/{editor}/{machine}/resume-lane-b` (RESUME proxy download on that computer's behalf). Admin only.
  - "Lane B" is the companion's proxy-download lane; its **breaker** is a safety latch that stops downloads when the server stops looking like the tree or a pass would delete too much.
  - `404` when the editor has no such computer.
  - `409` "that computer's last report does not show proxy download stopped, so there is nothing to resume. Wait for its next report and try again." when its last report does not show the breaker tripped (a companion too old to report a breaker is refused for the same reason).
  - Effect: parks a one-shot resume request. Returns `ok`, `editor`, `machine`, `pending_before` and the delivery estimate.
- `DELETE /admin/machines/{editor}/{machine}/resume-lane-b`: withdraw the parked resume. Admin only. Always `{ok: true}`.
- `POST /admin/machines/{editor}/{machine}/copy-plan?source=<other machine>`: make this computer's sync plan (the projects ticked to sync to it) a copy of another of the same person's computers. Admin only.
  - Refusals:
    - `404` for an unknown target or an unknown `source` computer of that editor.
    - `422 "source and target are the same computer"`.
    - `409` "this account is wired to the server: it works directly off the NAS and syncs nothing, so projects cannot be ticked for it" when the whole account is a wired (base rig) account.
    - `409` "'<machine>' is wired to the server: it works directly off the NAS and syncs nothing, so a plan cannot be copied onto it" when the target computer is wired.
    - `409` "'<source>' is wired to the server: it works directly off the NAS and holds no plan, so there is nothing to copy from it" when the source is wired.
    - `409` "<source> has no projects ticked - copying it would empty <target>." when the source plan is empty.
  - Effect: replaces the target's plan with the source's projects, in the same order and with the same per-project mode (full sync or upload only).
  - Every project that was added or removed gets its own audit row (a tick or an untick, tagged as a plan copy from the source), so the plan panel can show and UNDO it, and an emptied project gets the same 60-second grace before Syncthing unshares it that a hand untick gets. A summary audit row `plan.copy` records the source, project count, added and removed lists.
  - Asks the background collector to run soon.
  - Returns `ok`, `editor`, `machine`, `source`, `projects` (count now on the target), `added`, `removed`.

## Approving a Syncthing device
(source: api.py `api_admin_approve_device`, `approve_username_error`, `normalize_device_id`)

- `POST /admin/devices/approve`: accept a pending Syncthing device on the server and assign it to an editor. Admin only.
  - Body: `device_id` (1 to 128 characters), `username` (1 to 32), `create_new` (bool, default false: the "CREATE NEW EDITOR" tick box).
  - Refusals:
    - `503 "SYNCTHING_GUI_URL is not configured"` when the server's Syncthing address is not set.
    - `422 "username must be a valid TrueNAS-style username"`.
    - `422` when the device ID is not 8 dash-separated groups of 7 characters A-Z and 2-7 (case is folded to upper): "'<id>' is not a Syncthing device ID. Expected 8 groups of 7 characters ... Copy it whole: it is 63 characters. Adding a malformed ID creates a device entry that can never connect."
    - `422` when the username is not an editor the dashboard knows (known editors plus local accounts) and `create_new` is false: "'<name>' is not an editor this dashboard knows. Pick the OWNER of this computer: one editor can own several computers, so a second computer takes the same username as the first. Tick CREATE NEW EDITOR if this really is a new person."
    - `502` with Syncthing's error when Syncthing refuses.
  - Effect: approves the device in Syncthing under that username, records the username as a known editor (source "admin"), audits `device.approve`.
  - Returns `{ok, view}` where `view` is the whole admin Users page model.

## Companion packages: the upgrade channel
(source: api.py `api_admin_packages`, `build_packages_view`, `api_publish_package`, `api_set_current_package`, `roll_fleet_back`, `api_roll_fleet_back`, `api_delete_package`, `api_download_package`, `_upgrade_info`, `_trash_package_file`, `_sweep_stale_parts`; package_store.py `make_current_refusal`, `store_verified_package`; db.py `prune_companion_packages`)

A **package** is one published build: kind `companion` (the tray program, offered to the fleet as a self-update) or `onboard` (the clean-install package behind the INSTALLER download), for platform `windows` or `macos`. Exactly one build per kind and platform can be **current**. A build that is published but not current is **staged**.

- Filenames are chosen by the server, never taken from the upload:
  - companion Windows: `ccsync-companion-<version>.exe`; companion macOS: `ccsync-companion-<version>` (no extension);
  - onboard Windows: `ccsync-onboard-<version>.exe`; onboard macOS: `ccsync-onboard-<version>.zip` when the upload starts with the zip signature "PK" (the zipped onboarding wizard app), otherwise `ccsync-onboard-<version>.sh` (the Terminal bootstrap script).
  - Files live under `<data>/packages/<platform>/`.

### Listing
- `GET /admin/packages`: the Packages page model. Admin only. Returns:
  - `packages`: every published build with kind, version, platform, filename, sha256, size, published at/by, `is_current`, `file_exists` (whether the file is on disk), signature, key id, `min_version` (the downgrade floor every companion that sees it will remember), `signed_binary` (Authenticode-signed exe), `signed`, `rollout` ("current" or "staged" unless stored otherwise), `staged_at`, `requires_dashboard`, `arch`, `git_sha`, `git_dirty`, `notes` (the publisher's one line of "what changed"), `retracted_at`, `retracted_reason`, `retracted`, `ever_current` (was it ever what the fleet was offered: making it current again is a rollback and skips the soak), `ordering_blocked` (it needs a newer dashboard than this one), `soak` (for companion builds: how many computers have run it, for how long, crashes), `machines_running` (companion builds: how many computers last reported that version) and `machines_running_known` (always false for onboard builds: no report says which installer a computer used, so 0 means "cannot tell").
  - `current`: platform to current companion version.
  - `outdated_machines`: every computer whose companion is out of date, with its version, last report time, `update_requested` (a pushed version, if any), `update_withheld` (why the dashboard cannot send that push, "" when it can), `upgrade` (its last update attempt: version, attempts, last error, last attempt time, the version it rolled back from), `refused` (the offer it is refusing at receipt, if any) and `fled_current` (the current build is the one it crashed on and rolled back from, so it is not offered).
  - `machines_by_platform`: every reporting computer grouped by platform, for the "push to one machine" picker (a computer with no reported platform counts as windows).
  - `arch_gaps`: (platform, processor architecture, number of computers) for every architecture computers report that the current build does not cover.
  - `retracted`: the recalled builds.
  - `rollout`: adoption figures per platform, and which computers are refusing their offer.
  - `soak_minutes`, `data` (free and total bytes on the data volume; -1 when it cannot be measured), `dashboard_version`, `generated_at`.

### Publishing a build
- `PUT /admin/packages/{platform}/{version}`: upload one build. Admin only. The request body is the raw file bytes (no multipart).
  - Query parameters: `sha256` (required, 64 hex characters), `make_current` (0/1, default 0), `prune` (0/1, default 1), `kind` (`companion` default, or `onboard`), `signature` (required), `pubkey_id`, `min_version` (required, dotted numbers), `published_at` (required), `signed_binary` (0/1), `requires_dashboard` and `arch` (optional, companion builds, covered by the signature), `git_sha` and `git_dirty` (optional, advisory, unsigned), `notes` (optional, unsigned, shown in the editor's update dialog).
  - Refusals, in order, before any bytes are read:
    - `422` platform not windows/macos; kind not companion/onboard; version not three dotted numbers ("version must look like 1.2.3"); sha256 not 64 hex characters.
    - `503` when the dashboard has no release public key configured (`DASH_RELEASE_PUBKEYS`): "this dashboard has no release public key configured, so it cannot verify a build and will not publish one. ..."
    - `422` "unsigned publish REFUSED: no signature. ..." when `signature` is empty.
    - `422` when `min_version` is not dotted-numeric.
    - `422 "published_at is part of the signed record and must be sent with it"`.
    - `409` "<kind> version <v> is already published for <platform>: bump VERSION in companion/src/ccsync_companion/config.py and rebuild" (for onboard the hint names the three installer version files).
    - `507` when the data volume is short of space: free space must be at least 3 times the declared Content-Length plus 256 MiB. Message: "not enough free space on the data volume: N MiB free, this publish needs about M MiB. Old builds are pruned on publish (current plus the two newest are kept); free some space and try again." When free space cannot be measured there is no refusal.
  - While receiving:
    - The upload streams into a uniquely named staging file `<filename>.<random>.part` in the platform folder, so two uploads of the same version cannot collide.
    - Before streaming, staging files older than 6 hours in that folder are deleted (logged as a WARNING).
    - Body larger than 200 MiB: `413 "package body too large (max 209715200 bytes)"`, staging file deleted.
    - Empty body or a hash that does not match `sha256`: `400 "sha256 mismatch (or empty body): the upload was corrupted, and nothing was published"`.
    - A disconnect mid-upload deletes the staging file.
  - After receiving (shared with the vendor-feed auto-publisher):
    - `400` when `min_version` is above the version itself ("... every companion that saw this offer would raise its downgrade floor above it and then refuse it. Nothing was published ...").
    - `400` "release signature REJECTED (...)" when the signature does not verify against the configured public keys over the record the server assembled (kind, platform, version, server-chosen filename, sha256, size, min_version, published_at, signed_binary, plus requires_dashboard and arch when given).
    - Same version already held with the same bytes: success with note "already published at this version, with these exact bytes."; with different bytes: `409`. (Normally unreachable from this route, which refused an existing version earlier; reachable in a race between two uploads.)
    - On success the row is inserted and the file moved into place.
    - With `make_current=1`: the build is made current only if the "make current" gate (below) allows it without a human override; otherwise it is published staged and the reply's `note` reads "published and STAGED: push it to one computer, let it soak, then MAKE CURRENT. <the gate's reason>". At publish, the soak is skipped when nothing is current yet or when the build is not newer than the current one.
    - With `prune=1` (the default): every non-current build of that kind and platform except the two newest is deleted, rows first and then files.
  - Audit `package.publish` with kind, platform, version, make_current, signed_binary, min_version, requires_dashboard, arch, git sha/dirty and notes.
  - Returns `{ok, note, view}` (`view` is the Packages page model).

### Making a build current (the release gate)
- `POST /admin/packages/{platform}/{version}/current?kind=companion|onboard&force=0|1&confirm=<text>`: set which build the fleet is offered (companion) or which installer is downloaded (onboard). Admin only.
  - Refusals (the gate, in order):
    - `404` no such published package.
    - `409` the build was recalled by the vendor: "<kind> <version> was RECALLED by the vendor[: reason]. It cannot be made current. Roll the fleet back to a build that was not recalled." No override.
    - `409` a companion build needs a newer dashboard: "<kind> <version> needs dashboard <x> and this dashboard is <y>. Update the dashboard first, then make this build current." No override. An unparseable requirement also blocks.
    - `409` the build has no release signature: "... has no release signature. Companions verify signatures, so making it current stops EVERY computer in the fleet from updating, silently. ... To make it current anyway, type the version number (<v>) into the confirmation box." The middle sentence points at "AVAILABLE FROM THE VENDOR" when a vendor feed is configured, else at `tools\ship.cmd`. Overridden by `force=1` with `confirm` equal to the version.
    - A build that was ever current before passes (it is a rollback).
    - `force=1` without `confirm` equal to the version: `409` "to override the soak gate, type the version number (<v>) into the confirmation box. Nothing changed."
    - Onboard builds have no soak.
    - Companion builds only, the **soak**: a staged build may become current only after at least one computer has run it for the soak window (default 30 minutes; a stored site value `release_soak_minutes` wins over the environment; 0 switches the soak off). The refusal says which of: no computer has reported the version yet ("Push it to one computer first, leave it for N min, then make it current."); some computers had to be rolled back off it by the crash-loop guard; computers crashed since it started running there; crashes on record cannot be dated, or no computer reported its crash counter; or not enough minutes yet. Every soak refusal starts "<v> has not soaked yet:" and ends "Make it current anyway by confirming the override." `force=1` with the right `confirm` overrides it.
  - On success: audit `package.make_current` (with `forced`), returns `{ok, view}`.

### Rolling the fleet back
- `POST /admin/packages/{platform}/{version}/roll-fleet-back?to=<version>&kind=companion`: ask every computer running `{version}` to install `to` on its next report. Admin only. Works for any build, recalled or not.
  - `to` defaults to the platform's current build; `409` "no current <kind> package is published for that platform, so there is nothing to roll back to" when nothing is current and no `to` is given.
  - Refusals: `409` when `to` equals `{version}` ("<v> is what those computers are already running. Pick the build to put them BACK on with ?to="); `409` for kind other than companion ("a <kind> build cannot be rolled back across the fleet: no computer reports which <kind> it was set up with, so there is nobody to ask. Make the older <kind> current instead, and it is what new installs download."); `404` when `to` is not published; `409` "<to> was recalled too. Pick a build that was not."
  - When `{version}` is the current build, the channel is re-pointed at `to` first, through the same release gate (without an override). If the gate refuses, `current` is left alone, the refusal sentence is returned in `current_refused`, and the fan-out still happens. When re-pointed, `uncurrented` names the old version and `newer_machines` lists computers on that platform running something newer than `to` (they will now be offered a downgrade).
  - Every computer whose last report says it runs `{version}` on that platform gets a parked update request for `to`, marked as a downward push so the report handler does not retire it early.
  - Audit `package.roll_fleet_back`. Returns `ok`, `platform`, `from_version`, `to_version`, `machines` (who was asked), `uncurrented`, `current_refused`, `newer_machines`.

### Deleting a build
- `DELETE /admin/packages/{platform}/{version}?kind=companion|onboard`. Admin only.
  - `404` no such package; `409 "cannot delete the current version. Make another version current first"`.
  - The file is moved to `<data>/packages/.trash/<platform>/<timestamp>-<filename>` and its modification time is reset to the deletion time. Trashed files older than 30 days are deleted whenever a trash move happens. A file that is already missing is not an error.
  - If the move fails: `500` "could not move <file> to the trash folder (...). Nothing was deleted: the package row is still here and so are its bytes."
  - Otherwise the row is deleted, audit `package.delete` with `trashed_to`, returns `{ok, trashed_to, view}`.
  - There is no route to restore a trashed package.

### Downloading a build
- `GET /companion/package/{platform}/{version}?kind=companion|onboard`. Who: any signed-in user, or a companion with either fleet credential (`401 "log in, or present X-CCSync-Token"` otherwise). A per-editor token whose owner is barred is refused `403` with the account sentence; the shared token and sessions are not checked for that.
  - `{version}` may be the word `current` (any case) for the current build of that kind and platform; `404 "no current <platform> <kind> package is published"` when none.
  - `404` for an unknown version, and `404 "package file missing on server"` when the row exists but the file does not.
  - Response: the bytes as `application/octet-stream` with the server-chosen filename, and headers `X-CCSync-SHA256`, `X-CCSync-Version`, and when signed `X-CCSync-Signature`, `X-CCSync-Pubkey-Id`, `X-CCSync-Min-Version`, `X-CCSync-Signed-Binary` (1/0). These headers exist for the macOS bootstrap shell script, which can check the hash and refuse an unsigned channel but cannot verify the signature.

### What the fleet is offered (the `upgrade` block of the report reply)
- Offered only when: the reported platform is windows or macos (an absent or other platform is offered nothing), the companion reported its running version, and that version differs from the build to offer ("differs", not "is older": a rollback made current is offered like an update).
- The build to offer is the platform's current companion build, except for a computer with a parked push: then it is the pushed version, even if staged (a targeted offer to that one computer). The targeted offer ends when the push clears or is withdrawn.
- Withheld, with a reason sent to the companion as `upgrade_none_reason` instead:
  - the build is the one this computer crashed on and rolled back from (and it is not an admin's push): "this computer kept crashing on that build and rolled itself back, so it is not offered again". Lasts until the computer runs that version or newer;
  - the build was recalled: "that build was recalled by the vendor";
  - the build needs a newer dashboard: "that build needs a newer dashboard than this one";
  - the build's architecture and the computer's are both stated, they differ, and the build is not `universal2`: "that build was made for a different processor than this computer". A build or a computer with no stated architecture is offered as before.
- Offer fields: `version`, `url` (`/api/v1/companion/package/<platform>/<version>`), `sha256`, `size_bytes`, `kind`, `platform`, `filename`, `published_at`, `min_version`, `signed_binary`, `signature`, `pubkey_id`; plus `arch` and `requires_dashboard` only when the record has them; plus `notes` when the publisher wrote one. The `/verify` route (outside this range) uses the same function without a computer name, so it can never carry a targeted offer.

## The companion report: `POST /report`
(source: api.py `api_report`, `ReportIn` and its section models, `_truncate_report_sections`, `_bound_to_field_caps`, `_register_machine`, `flatten_*`, `_store_*`, `undeclared_report_sections`, `_report_withheld`, `_record_legal_sections`; app.py body limits)

Every companion posts this every 30 seconds. A **heavy** report carries the big sections (file lists, media trees, diagnostics sections); a **light** one carries the lanes only. Throughout, "absent" (the section was not sent) and "empty" are different: an absent section usually leaves what the dashboard stored alone.

### Who may call it, and every refusal
- The login gate lets it through without a browser session; it is exempt from the cross-site-request check. The body is capped at 8 MiB before it is read (counted, not just the declared length).
- Fleet credential (`X-CCSync-Token`):
  - none valid, and the server has no shared token configured and the presented value does not look like a per-editor token: `401 "report token not configured on server (set DASH_REPORT_TOKEN)"`, unless `DASH_REPORT_TOKEN_OPTIONAL=1` is set together with `DASH_DEV_INSECURE=1`, in which case the report proceeds unauthenticated (DEV ONLY: without the dev flag the option is ignored with an ERROR at boot);
  - otherwise an invalid token: `401 "bad or missing X-CCSync-Token"`;
  - a per-editor token that belongs to a different editor than `editor_name`: `401 "this X-CCSync-Token belongs to a different editor than editor_name"`.
- Identity token (`X-CCSync-Identity`), required whenever the dashboard has a session secret (always, on a real deployment):
  - missing: `401` "X-CCSync-Identity required: sign in from the companion tray (Sign in…) to get a computer identity token";
  - revoked by an admin: `401` "X-CCSync-Identity was revoked: sign in again from the companion tray" (or the account sentence below when the person was removed);
  - cannot be verified (secret changed): `401` "X-CCSync-Identity is invalid or expired: sign in again from the companion tray";
  - names another editor: `401 "X-CCSync-Identity does not match editor_name"`. Without a session secret, a presented identity that verifies and names someone else is refused the same way.
  - An identity signed with the retired previous secret is accepted and logged; the dashboard records which computers still use the old key.
- Account check (after the credentials): the editor was removed, suspended, or (local accounts only) disabled or missing while other local accounts exist: `401` with:
  - removed: "this account was removed from the dashboard. Ask your admin to add it again if that was a mistake";
  - suspended: "this account is suspended on the dashboard. Ask your admin to press RESUME: your sync plan is untouched and comes straight back";
  - disabled: "this account has been disabled on the dashboard. Ask your admin to turn it back on: nothing will sync until they do".
  - A database error while checking fails open (the report is accepted).
- Every identity or account refusal also stamps the existing computer row with "report refused at <time>" and a reason (for example "no computer identity token was sent", "its computer identity token was revoked by an admin", "its computer identity token cannot be verified (the dashboard's session secret has changed)", "its computer identity token belongs to a different editor", or the account reason). Nothing else from a refused report is written. The next accepted report clears the stamp.
- A body that fails validation is `422` (for example a missing `editor_name`, `machine`, `reported_at` or `lanes`, a blank `machine`, a lane `state` outside the four words, or a malformed `sync_guard`, `file_moves_applied` (except its `state` word), `resolve_journals` or `resolve_undo_applied`).

### Never a refusal: truncation and tolerance
- Ceilings that cut rather than refuse (the report is accepted, the cut is logged as a WARNING and echoed in the reply as `truncated: {section: entries dropped}`):
  - `local_manifest` and `media_tree`: first 64 projects kept;
  - `queue`: first 64 entries;
  - each project's `originals` and `proxies` lists: first 4,000 files each (the project is then marked truncated), counted as `manifest_files`;
  - each Resolve project's clip list in `media_tree`: first 4,000 clips, counted as `media_clips`.
  - The companion's own order is kept, so its most important projects survive.
- Every string, list and number in the lane, transfer, completed-transfer, clip, `sync_guard` and diagnostic sections is cut to its field limit (strings shortened, lists sliced, numbers clamped) instead of refused.
- Lanes whose name is not one of `lane_a_video_up`, `lane_b_proxy_down`, `lane_c_syncthing` are silently dropped.
- The **tolerant sections** `proxy_coverage`, `youtube_import`, `broll_ingest`, `music_ingest`, `capabilities`, `machine_settings`, `report_optouts`, `eula`: one that cannot be parsed at all is dropped with a WARNING and the rest of the report lands.
- Unknown `state` words in `file_moves_applied` read as "no state".
- **Undeclared sections**: keys the dashboard does not know, at the top level, inside `sync_guard`, or one level inside a `sync_guard` sub-section, are accepted and discarded, logged once per computer per section per day ("report from <who> carries section '<key>' that this dashboard does not read ...") and accumulated into a stored record that a home-page banner reads. The key `truncated` sent by a client is ignored.

### Reporting switches applied on arrival (privacy categories)
- Four categories: `resolve_project` (Resolve project names; implies `media_tree`), `local_manifest` (the file lists of the editor's disk and the clip lists and paths in the health sections), `media_tree` (the Resolve bin trees), `input_idle` (how long the keyboard and mouse have been idle).
- Withheld = the site policy (read from site settings; if that cannot be read, the last applied site set) together with the computer's own list from `report_optouts`. When a report does not carry `report_optouts`, the computer's last stored own list is used.
- Every field those categories cover is removed from the report before anything is written. Resolve undo journal ids are masked to `withheld:project/<file name>` and undo answers have quoted project names replaced with `<project>`, rather than dropped. If removal fails, the whole top-level section is dropped; if even that fails, the report is refused.
- After the section writes: the computer's switches are recorded and anything the dashboard held under a newly withheld category is deleted (logged "now withholds ... what the dashboard held under it was deleted"); how this report reached the dashboard (plain http on a public address, LAN or tailnet http, https) is recorded when it changes (a WARNING when it is plain http to a public address); and the licence block (`eula`) is recorded. Each of the three is best effort and cannot fail the report.

### Fields and sections the server accepts, and what it does with each
- `editor_name` (1 to 64 characters, lower-cased) and `machine` (1 to 128, trimmed, not blank): who is reporting.
- `machine_id` (up to 64): the computer's own identity, minted once on that computer. Used for rename detection (below) and to answer commands filed under a former hostname.
- `syncthing_device_id` (up to 128): stored on the computer's registry row. If another of this editor's registry rows held the same device id, it is taken off that row (logged as a WARNING), because one device is one computer.
- `companion_version` (up to 64), `platform` (`windows`/`macos`, lower-cased), `arch` (up to 32): stored; used for the upgrade offer, the pushed-update clear rule and the job queue-depth rule.
- `reported_at` (required): the companion's own clock, stored separately and clamped; the dashboard's own receipt time is what every age is measured from.
- `lanes` (up to 32 entries; only the three known names survive): each lane's `state` (`idle`, `syncing`, `error`, `paused`), queued and transferring counts, `last_error` (2,000), `last_sync`, `detail` (500), current project, bytes done and total, speed, ETA, `progress_token` (changes whenever real work happens) and `state_since`. Each is written as that lane's current report.
  - Each lane's `transfers` (up to 256: name, direction, bytes done/total, percentage, speed, ETA, project slug) replace this computer's whole set of live transfers; an empty or absent list clears finished ones.
- `completed` (up to 256: name, direction, lane, time): appended to the transfer history (the HISTORY section).
- `queue` (list of names): accepted and truncated to 64; nothing in this route stores it.
- `current_project`: accepted; not stored by this route.
- `resolve_project` (up to 512): the project open in Resolve on that computer.
  - Ignored when it is a scratch project: "untitled project" or "new doc", optionally followed by a number (for example "New Doc 1", "Untitled Project (3)"), case and spacing ignored.
  - If a stored mapping from that Resolve project name to a tree project exists, it is used.
  - Otherwise an automatic match against active project labels is tried, and only a confident one is used (at least two shared non-trivial words, or the name equals the project's last path part). It is not used if an unregistered folder in the Projects tree matches as well, or if the tree cannot be read. A used match is stored permanently ("sticky"); only an admin changes it afterwards.
  - With no mapping, the reply carries `resolve_project_unmapped: <name>` so the companion can ask the editor to pick the folder.
- `mode` (`base` or `editor`): the computer's role (a wired base rig or an editor). Absent keeps the stored role.
- `local_manifest` (keyed by project path relative to the tree): per project, counts and bytes of originals and proxies, a truncated flag, and optionally the file lists (relative path and size).
  - The project path is mapped to a project by its label (compared after Unicode normalisation, so a Mac's decomposed spelling matches), preferring the active project whose stored path ends with it; with no registered project, a slug is generated from the path.
  - The per-project summary is stored; when file lists are present they replace this computer's whole list for that project. Each project is written in its own short database transaction.
- `media_tree` (keyed by Resolve project name): per clip, bin path, clip name, file path, kind, present flag. Scratch projects are skipped. Only a Resolve project with a stored mapping is written (no automatic match here); the computer's whole bin tree for that project is replaced, one project per transaction.
- `transport_health`: from `syncthing`, how many connected devices are relayed and how many direct; from `orphans`, the `.partial` files lane A left on the server, summed across lanes (count and bytes); from `express`, files dropped over the express cap and the last express error. Stored as columns. Other fields in it (express runs, local trash counts, per-device map) are accepted and not stored. Absent leaves the stored values.
- `sync_guard` (the safety and health section). Absent leaves everything stored alone. When present, every sub-section below follows a "latch" rule: what the report says replaces what was stored, and an absent sub-section clears its stored value. Sub-sections:
  - `lane_b_breaker`: `tripped`, `reason`, `tripped_at` are stored (tripped flag, reason, time). Also accepted and not stored: deletes, bytes, last pass deletes, resumed at, cause, editor's wording, and the "could not save the latch to disk" trio.
  - `trash` (the local `.ccsync-trash` of lane B): count and bytes stored; path, retention, oldest, kept, removed, skipped and so on accepted only.
  - `halt` (the computer's own halt state): active, and while active its scope (`local`/`fleet`) and reason, stored. The persist-failure trio accepted only.
  - `skipped_exists` (lane A files the server holds at a different size, never replaced): count and the project prefix it was measured under stored; samples (up to 64) and check time accepted only.
  - `removal_overrides` (up to 8: an editor deleted a project's local copy although it was not caught up): each one is written to the dashboard log as a WARNING "<editor>/<machine> DELETED the local copy of <project> past the caught-up gate (<n> pending upload(s)): <reasons>". Not stored anywhere else.
  - `syncthing_supervisor` (absent while healthy): down since, restart attempts, last error, whether anything is still trying to restart it (true/false/unknown). Stored.
  - `reporter` (the companion's own record of failed reports): accepted, not stored.
  - `crashes`: count of crash files and the newest name, stored.
  - `clock_skew_seconds`: accepted, not stored (the dashboard measures skew itself).
  - `folders_unfiltered` (Syncthing folders with no filter written, up to 64): stored as a count and the first 10 names.
  - `sync_conflicts`: count stored; sample paths (up to 32) accepted only.
  - `disk`: free and total bytes of the sync root, free bytes of the system drive, time. Stored; a report without this sub-section does not blank the last measurement (it rides heavy reports only).
  - `stalled` (the last lane the companion found stuck and possibly killed): lane, seconds, killed, time. Stored.
  - `restarts` (watchdog restarts of the sequencer, watcher and media-tree threads): stored summed across the three as restarts in 24 hours, newest restart time, first last error.
  - `blocked` (the companion's own ranked answer to "why is nothing moving"): reason (any word), detail, since. Stored.
  - `rotation_seconds` (how often that computer rotates projects): stored, used to size the stall judgement.
  - `disk_floor` (why lane B parked for low disk): the floor in bytes is stored; parked flag, reason, time, free bytes and persist-failure trio accepted only.
  - `upgrade` (the last time it tried to take a build): version, attempts, last error, last attempt time, the version it rolled back from (kept by the dashboard until the computer runs that version or newer), and the offer it refused at receipt (version, reason, time). Stored. Starts on this version and the count of failed state writes are accepted only.
  - `root_state` (`present`/`absent`/`misplaced`/`not_answering`/`unknown`): accepted, not stored by this route.
  - `shared_folder_problems` (up to 20 sentences): accepted, not stored by this route.
  - `repath_events` (up to 20 project folders this computer moved because an admin renamed them on the server: old, new, time as text or number, relinked, id, slug, note, moved): accepted, not stored by this route.
  - `resolve_health` (the Resolve media scan): counts of clips outside the tree, with a bad prefix, missing, and the two "ignored" counters summed into one, last scan time, and the list of unopened projects with clips only on that computer (`{project, count}`, up to 20, kept as JSON, and its scan time) are stored as columns. The rest (connected, open project, how long a call has been stuck and which call, up to 50 missing clips, up to 50 refused non-canonical clips, proxy attach results, proxy gaps, stills check, skipped ever, stand-ins owed) is stored whole as a detail record; an absent sub-section deletes it.
  - `stray_projects` (project folders on the editor's disk that are not in the tree): count and bytes stored; up to 20 paths and slugs and the check time accepted only.
  - `moved_project_dirs` (up to 20: project folders not where the tree says): stored as a count.
  - `ingest_staging` (footage dropped but not filed): bytes stored; batches and oldest accepted only.
  - `loopback` (the local 8899 "Send to Resolve" server): enabled, bound, port, error (an empty error is stored as nothing), since. Stored.
  - `ytdlp` (that computer's yt-dlp and ffmpeg/ffprobe/deno helper verdict): stored whole as a per-computer record (`ytdlp:<editor>/<machine>`) that two alert checks read; an absent sub-section deletes it.
  - `youtube_import` (clips downloaded that never reached Resolve: state such as `ok`, `no-project-match`, `resolve-closed`, `drive-absent`, `paused`; reason; pending count; time): stored whole per computer (`youtube_import:<editor>/<machine>`) and shown in the fleet view; absent deletes it.
  - `standins_placed` (archive originals this computer holds a stand-in proxy for: up to 200 archive-relative paths, check time): when the list is present it replaces this computer's whole set; absent changes nothing.
- `file_moves_applied` (up to 64 answers to `commands.file_moves`): each with id, ok, detail (512), state (`done`, `failed`, `retrying`, `blocked`, `applying`, `not_synced_here`, or none), attempts, and `relink_pending` (moved on disk, Resolve not yet repointed).
  - `applying` is stored as `retrying`, which keeps the command alive and re-sent.
  - `retrying` and `blocked` record the attempt; `not_synced_here` is terminal (the computer trashed its copy because it does not sync the destination project); no state is the old meaning (answered, stop asking).
  - The answer is matched to the move even when the move was filed under this computer's former hostname (via `machine_id`).
  - A change of answer is logged (INFO when ok, WARNING otherwise); repeats of the same answer are not.
  - Recorded before the reply is built, so a move answered in this report is not re-sent in this reply.
- `resolve_undo_applied` (up to 16 answers to `commands.resolve_undo`): id, ok, detail, state (`done`, `failed`, `retrying`, `parked`), attempts, `parked` flag. `parked` (no project is open in Resolve) is stored as one state whichever way it was spelt. Matched under a former hostname too. Logged.
- `resolve_journals` (up to 20 clip-path change records the computer holds: id, project, started, entries, sources): replaces the stored list for this computer; absent keeps the old list.
- `capabilities` (what this computer can do, for the fleet job scheduler): GPU present, name, VRAM, NVENC encoder, ffmpeg, ffprobe, whisper and its detail, claude, up to 16 mount names, CPU count, idle seconds (null means "cannot tell", treated as not idle), load, jobs enabled, jobs idle floor, its allowed job kinds (empty means all), volunteer-until time, `resolve` (running, project name), `cards_agent` (connected, state, timeline, version, since, gate state, detail up to 1,000, last poll time, last HTTP status), `jobs_gate` (why it takes no fleet work by itself: reason, detail). Replaces the stored capabilities wholesale; absent leaves them (and a computer that never sent any is offered no job with a requirement).
- `proxy_coverage` (the computer's proxy generator): stored are `missing`, `state` and `left`; everything else (per-project map up to 128, history, ffmpeg/NVENC flags, generated, failed, low space) is accepted and not stored. Absent leaves the stored values.
- `youtube_import` (top level, the importer's status: state, pending, imported and failed this session, last import time, bin, error): parsed and not stored by this route.
- `broll_ingest` and `music_ingest` (a local b-roll or music indexing batch): active, batch id, state, gate, done, total, failed, current clip or track, percent, tier (b-roll only), and warning (for example an insufficient-VRAM refusal, shown even when nothing runs) are stored. Run mode, uploading, upload paused and model download percent are accepted only. Absent sets "not indexing" while keeping the other stored values.
- `machine_settings` (what the account page shows and the answer to a settings request): `accepts` (filtered to the keys the dashboard allows to be requested: `jobs_enabled`, `jobs_kinds`; never `mode`), `jobs_volunteer_minutes`, `drive_reminder_minutes`, `youtube` (status words only: downloads on, sign-in enabled, terms accepted, sign-in state), `pending_restart` (only `jobs_enabled`, `jobs_kinds`, `jobs_volunteer_minutes`, `drive_reminder_minutes`, each with the right value type), and `applied` (the answer to a request: id, state, detail, time). Stored; absent leaves the stored values. An `applied` answer of `applied` or `refused` finalises the request; other words keep it pending.
- `lane_b_via` (`remote` or `remote_down`, the download route on a trial): accepted, not stored by this route.
- `report_optouts`: see the reporting switches above. Unknown category names are dropped one by one.
- `eula` (version, accepted at, sha256 of the licence the computer accepted): stored; absent leaves the stored value.

### Other effects of an accepted report
- Clears any "report refused" stamp on the computer.
- With a verified identity: records the editor as known (source "report") and whether the identity was signed by the retired key.
- Records which credential the computer used (shared or per-editor, and which per-editor token by its public id) and touches the token's last-used time.
- Machine registry and renames: a reported `machine_id` that another of this editor's registry rows carries under a different hostname means either a rename or a copied disk:
  - if that other row reported within the last 5 minutes, both are treated as live (a copied disk): nothing moves, both rows stay, a WARNING is logged, and a home-page problem of kind `duplicate_machine_id` is raised: "Two computers are reporting the same identity: ... This happens when one computer's disk was copied onto another one ..." with the fix "On the NEWER computer, quit CC Sync, delete the file .ccsync/machine.json in that user's home folder, and start CC Sync again ... wait five minutes ... remove that one with "Forget" on the Sync status page.";
  - if the other row has been quiet for 5 minutes or more, the new hostname adopts the old one's plan and records (logged), and the duplicate notice is cleared;
  - if the new hostname already has a plan of its own, nothing moves (logged as a WARNING).
- Slow writes: a report that takes more than 1 second to write is logged with its longest lock hold; a single lock hold over 5 seconds raises a slow-write notice.

### The reply
- Always: `ok: true`, `lanes` (how many lanes were accepted), `received_at`, `dashboard_version`.
- `truncated`: present when the report was cut.
- `upgrade`: the build offer (see the upgrade channel), when there is one.
- `upgrade_none_reason`: a sentence, when a build exists and is not offered to this computer, or when a pushed version cannot be offered to it.
- `resolve_project_unmapped`: the Resolve project name, when it has no folder mapping.
- `standins_known: {rels}`: the archive paths the whole fleet has stand-ins for, always sent (an empty list means "none"), omitted only if it cannot be read.
- `commands` (always present), holding:
  - `halt` (always): `active`, `reason`, `at`. Present in both states, because `active: false` is what releases a halt on the companion.
  - `upgrade` (`apply: true`, `version`, `requested_by`, `requested_at`): while an admin push is outstanding and the computer can be offered that build.
    - The push is cleared (and not sent) once the computer reports that version or later; for a downward push (a rollback), only once it reports exactly that version (numeric part compared).
    - If the computer cannot be offered the pushed build, the command is not sent, the reason goes into `upgrade_none_reason` (default "the update you were sent cannot be installed on this computer"), and the verdict is saved on the computer so the job scheduler stops treating it as "upgrading". The push stays parked and is sent as soon as the build becomes offerable, which also lifts the verdict.
  - `resume_lane_b` (`apply: true`, `requested_by`, `requested_at`): one shot. If the report carried a breaker section saying not tripped, the request is dropped without sending; otherwise it is sent. Either way the request is cleared with this reply.
  - `diagnostics` (`requested_by`, `requested_at`): sent on every reply until a bundle with trigger `admin_request` arrives.
  - `machine_settings` (`id`, `set`, `requested_by`, `requested_at`): a pending fleet-jobs settings change asked from the account page. `set` holds only `jobs_enabled` and `jobs_kinds`. Withheld (still pending) if any key is not in this computer's stored `accepts`; a computer that never reported the section is judged against the allowed keys alone. Sent on every reply until answered; the first delivery time is recorded.
  - `broll_ingest: {cancel: [batch ids]}` and `music_ingest: {cancel: [...]}`: b-roll or music indexing batches someone asked this computer to stop, up to 16 each, only when non-empty. Looked up read-only in the b-roll and music databases; any failure, a missing checkout, or (b-roll) the b-roll feature being off answers nothing.
  - `file_moves`: outstanding moves an admin made on the server that this computer must follow (id, from and to slug, project path and relative path, is_dir, requested by/at), including ones filed under its former hostname; sent on every reply until answered; each delivery is stamped.
  - `resolve_undo`: outstanding admin undo requests (id, journal, project, requested by/at); sent until answered; deliveries stamped.
  - `jobs`: present only when it has content:
    - `offered` (job ids this computer may claim, at most 8, computed from this report's capabilities);
    - `forced` (the subset an admin said to run now);
    - `cancel` (ids this computer holds that an admin asked to stop);
    - `queue` (the fleet queue depth: queued, running, pinned, and the age in seconds of the oldest queued job). Sent always to companions 0.9.65 or newer with jobs switched on, and to others only when something is queued, running or pinned.
    - Any failure here is logged and the block omitted.

## Diagnostics bundles ("ask this machine why")
(source: api.py `api_diagnostics`, `DiagnosticsIn`, `_diagnostics_withheld_unredacted`, `api_admin_ask_why`, `api_admin_diagnostics`; db.py `DIAGNOSTICS_MAX_CHARS`, `DIAGNOSTICS_MAX_AGE_DAYS`)

A **diagnostics bundle** is the companion's plain-text self-report (identity, token state, root state, configuration problems, lanes, Resolve bridge and so on).

- `POST /diagnostics`: a companion uploads one bundle.
  - Who: the same credential, identity and account checks as `/report` (same `401` sentences for the token; identity: `401` "X-CCSync-Identity required. Sign in from the companion tray, or its signing key was retired" when missing or unverifiable, `401 "X-CCSync-Identity does not match editor_name"` when it names someone else). A barred account is refused `403` with the account sentence. Body capped at 256 KiB before reading.
  - Body: `editor_name` (or `editor` as a synonym), `machine`, `machine_id`, `at`, `trigger`, `text`. Unknown keys accepted.
  - `text` longer than 256 KiB characters is cut, never refused.
  - `trigger` is one of `button` (the editor pressed the tray's button), `lane_error`, `admin_request`; any other word is stored as given (blank becomes `other`), never refused.
  - Privacy: when the site withholds a category that this computer's last reported own list did not name (including any computer that never reported its list, which is treated as not redacting), the bundle is NOT stored. A stub is stored instead: "=== CCSYNC DIAGNOSTICS === (not stored: this site withholds <categories>, and this computer's companion is too old to take those out of its bundle. Update the companion on this computer to see its bundles again.)" and the reply carries `stored: false`. Only the categories that can appear in a bundle count.
  - A bundle with trigger `admin_request` clears the admin's pending ask, which stops `commands.diagnostics` riding further replies.
  - Audit `diagnostics.received` (who, trigger, size, id, withheld categories). Returns `{ok, id}`.
  - Stored bundles are kept 30 days (pruned elsewhere).
- `POST /admin/machines/{editor}/{machine}/ask-why`: ASK THIS MACHINE WHY. Admin only.
  - `404 "no computer '<machine>' for '<editor>'"` for an unknown computer.
  - Parks a request that rides `commands.diagnostics` on every reply until the bundle arrives.
  - Returns `ok`, `editor`, `machine`, `pending_before` (an earlier ask is still unanswered), and the delivery estimate.
- `GET /admin/diagnostics?editor=&machine=`: stored bundles. Admin only. With either filter, every bundle matching it; with neither, the newest bundle per computer.

## Alerts (admin JSON twins of the Alerts settings page)
(source: api.py `api_alerts`, `api_alerts_test`, `api_alerts_preview`)

- `GET /admin/alerts`. Admin only. Runs a fresh scan of every alert check and returns:
  - `settings` (the alert configuration, never including a password, only whether one is set and where it came from),
  - `open` (the findings now) and `counts`,
  - `kinds` (every alert kind: kind, severity, title, what it means),
  - `groups` (the kinds grouped, each with whether it is sent),
  - `log` (the last 200 alerts sent).
- `POST /admin/alerts/test`. Admin only. Sends one message through the configured sink now: "This is a test of the CC Sync alert channel. Nothing is wrong." Duplicate suppression is off, so every press sends. Returns the sink's result.
- `GET /admin/alerts/preview`. Admin only. Returns plain text: "Subject: <subject>" then the body of this week's report exactly as it would be sent.

## Recovery (restores from server snapshots)
(source: api.py `api_recovery`, `api_recovery_preview`, `api_recovery_restore`, `api_recovery_drill`; the behaviour itself is in recovery.py, outside this part)

All four are admin only. A refusal from the recovery code is returned with its own status and sentence.

- `GET /admin/recovery?problem=`: what is protected now, what can have gone wrong, and the plan for a chosen problem. Designed to answer even when the NAS is down, saying what it could not gather.
- `GET /admin/recovery/preview?slug=&snapshot=`: what restoring that project from that snapshot would bring back.
- `POST /admin/recovery/restore?slug=&snapshot=&include_changed=false`: restore the project from the snapshot into a quarantine folder `<tree>/.restored-<timestamp>/<project>/`, outside the project, never over the live path. `include_changed` also brings back files that changed since the snapshot. There is no overwrite option.
- `POST /admin/recovery/drill?snapshot=`: rehearse a restore into a scratch path. Only a successful drill records its date on the protection panel.

## Undoing Resolve clip-path changes on a computer
(source: api.py `api_machine_resolve_journals`, `_undo_state_sentence`, `api_machine_resolve_undo`)

A **journal** is the companion's record of clip paths it changed in a Resolve project (a relink); replaying it puts the old paths back.

- `GET /admin/machines/{editor}/{machine}/resolve-journals`. Admin only. Returns `journals` (what the computer last reported holding) and `requests` (undo requests made of it), each request with a `state_sentence`:
  - parked: the companion's own detail, else "waiting: no project open in Resolve, will resume when one is";
  - retrying: detail, else "retrying on this computer's next report";
  - done: detail, else "done";
  - failed: detail, else "failed";
  - no answer yet: "waiting for that computer to report".
- `POST /admin/machines/{editor}/{machine}/resolve-undo?journal=<id>`: UNDO THIS CHANGE on that computer. Admin only.
  - `404` "that computer has not reported a change called '<id>'. Its list is refreshed every time it reports: reload and try again." when the journal is not in its last reported list.
  - `404 "no computer ..."` when the request cannot be recorded.
  - Parks the request; it rides `commands.resolve_undo` on every reply until answered. The companion refuses it while the wrong project is open. Returns `{ok, id}`.

## The fleet job API
(source: api.py `_require_fleet_caller`, `_require_jobs_reader`, `api_create_job`, `api_list_jobs`, `api_job_queue`, `api_job_machines`, `api_get_job`, `api_job_why`, `api_cancel_job`, `api_retry_job`, `api_claim_job`, `api_heartbeat_job`, `api_job_result`; db.py `request_job_cancel`, `retry_job`, `JOB_LEASE_SECONDS`, `JOB_KINDS`, `JOB_MAX_RUNNING`; jobs.py `out_stem_problem`)

A **job** is a unit of work the dashboard queues and an editor's computer runs while idle. Kinds: `whisper` (transcription), `proxy-480p`, `audio-extract`, `peaks` (waveform), `card-ingest`, `drive-copy`, `ledger-scan`. Paths in a job are (root name, relative path) pairs, never absolute. Default fleet-wide caps on jobs running at once: whisper 2, proxy-480p 4, audio-extract 4, peaks 4, card-ingest 4, drive-copy 2, others 4 (overridable by `DASH_JOBS_MAX_RUNNING`).

- **Fleet caller gate** (claim, heartbeat, result, locate, and machines when a token is sent): a valid fleet credential (`403 "missing or invalid X-CCSync-Token"`), a configured session secret (`403 "identity cannot be verified here"`, logged), a verifiable identity token (`403` "X-CCSync-Identity required - sign in from the companion tray, or its signing key was retired"), a per-editor token matching the identity (`403 "this report token belongs to a different editor"`). The editor is always taken from the identity token, never from the body. A barred account is `403` on claim, machines and locate, `410` on heartbeat, and allowed on result. The login gate lets these paths through without a session only when a fleet token is present.
- `POST /jobs`: queue a job. Admin only.
  - Body: `kind` (1 to 32 characters; not checked against the list of kinds here), `inputs`, `requires`, `cost` (free-form objects), `priority` (-100 to 100, higher first, default 0), `force` (run now: skips the idle wait, the per-computer cooldown and the ranking grace, but nothing else), `target_machine` (only this computer; an unknown name is accepted).
  - `422` for proxy-480p, audio-extract and peaks when `inputs.out_stem` is a dot name, contains "/", or contains a control character: "out_stem '<x>' is not a plain file name: it cannot be a dot name or hold a '/' or a control character, on any computer".
  - A blank `requires` is filled with the standard requirements for the kind (the media kinds need ffmpeg, ffprobe and the roots the job names).
  - Returns `{ok, job, why}`: `why` is the scheduler's per-computer explanation of who can run it and why not.
- `GET /jobs?state=&kind=&limit=200`. Admin only. Returns `jobs` and the list of `kinds`.
- `GET /jobs/queue`. Admin only. Returns `queue` (depth), per-kind `running` and `cap`, and `pinning` (`available`, and `why_not`: whether the dashboard's own engine can take a job the fleet gives up on; "no executor is configured" when none).
- `GET /jobs/machines`: the computers a job can be aimed at. An admin session, or a fleet caller (a non-admin session is `403 "admins only"`; with a token present the fleet gate runs first). For every computer in the registry, the status table or the capability table:
  - `editor`, `machine`, `mode`, `online` (reported within the last 24 hours), `reported_at`, `jobs_enabled` (false when no capabilities were ever reported), `kinds` (empty means all), `capabilities` (only GPU present/name/VRAM, NVENC, ffmpeg, ffprobe, whisper, CPU count, mounts), `idle_seconds` (null means cannot tell), `current_job` (id and kind of the job it holds).
  - Sorted online first, then by hostname. No tokens, device ids, paths or project names.
- `GET /jobs/{job_id}`: one job. Admin only. `404 "no such job"`.
- `GET /jobs/{job_id}/why`: per computer, why this job is or is not schedulable there. Admin only. `404 "no such job"`.
- `POST /jobs/{job_id}/cancel`. Admin only.
  - A queued job becomes failed at once ("cancelled by <admin>") and is never retried.
  - A job held by a computer, or pinned to the dashboard's engine, gets a cancel request: the computer is told through `commands.jobs.cancel` and kills its work; the dashboard engine checks the flag. The row is not forced to finished.
  - `404 "no such job"`; `409 "this job is already <state>"` for a finished job.
  - Returns `{ok, state ("failed" or "requested"), job}`.
- `POST /jobs/{job_id}/retry`: queue the same work again under a new id (same kind, inputs plus a `retry_of` marker, requirements, cost, priority, force and target). Admin only. The old row is untouched.
  - `404 "no such job"`.
  - `409` "job #N is <state> and has not finished, so there is nothing to try again yet. Cancel it first."
  - `409` "job #M is already a new attempt at job #N and it is still on the queue."
  - Returns `{ok, retry_of, job, why}`.
- `POST /jobs/claim`: a companion takes the next job it may run. Fleet caller.
  - Body: `machine`, `machine_id`, `capabilities` (re-checked now, not taken from the last report), `kinds` (up to 16), `ids` (up to 16: narrow to these offered ids; never widens).
  - First expires every lease not renewed in time (logged as a WARNING per job) and re-queues, pins or abandons those jobs, applying the per-computer cooldown after a failure (default 120 seconds).
  - Computes up to 8 offers for this computer and claims one with a compare-and-set that also enforces the fleet-wide cap per kind, so two computers can never both hold a job and simultaneous claims cannot exceed the cap.
  - Returns `{job, lease_seconds: 300}` on success, or `{job: null, offered}` when nothing could be claimed.
- `POST /jobs/{job_id}/heartbeat`: keep the lease (5 minutes) alive. Fleet caller (barred account: `410`).
  - Body: `machine`, `note` (500), `progress` (0 to 1, optional).
  - `410` with `{detail: "this job is no longer yours", job_id, state}` when the lease expired, someone else holds it, or it finished. The companion stops on 410.
  - Returns `{ok, lease_seconds: 300}`.
- `POST /jobs/{job_id}/result`: how the job ended. Fleet caller, allowed even for a barred account.
  - Body: `machine`, `ok`, `retryable` (default true), `error` (2,000), `result` (object of output paths).
  - ok: the job is done. Not ok: failed; a retryable failure is re-queued until the kind's attempt budget runs out, and then pinned to the dashboard's own engine if one can take it (whisper never pins), else abandoned; not retryable means the fault is in the job itself. The reporting computer gets the cooldown.
  - `410` "this job is no longer yours" when this computer does not hold it. Returns `{ok, state}`.
- Finished jobs are kept 30 days (pruned elsewhere).

## Where did a file go: `POST /files/locate`
(source: api.py `api_locate_files`; locate.py `locate`)

- Who: a fleet caller (token plus identity). Used by a companion that is about to give up on files that vanished from its synced path, to learn whether they were moved elsewhere on the server.
- Body: `files`, a list of `{name, size}` (base name and exact size, never a path). Body capped at 512 KiB before reading.
- `413` "ask about at most 2000 files at a time - this asked about N." when over 2,000 entries.
- Answer, from the server's file inventory (no disk access): `walked` (false when the inventory has never run, meaning "not known", not "not found"), `as_of` (the oldest inventory time that contributed), `unreadable` (projects whose last inventory failed and were excluded), and `files`: each `{name, size, found: [{project_slug, rel_path}]}`. Names are compared after Unicode normalisation; only active projects are searched; every match is returned when a file sits in several places (the server never picks one).

## Looks redundant or overlapping
- The halt, pushed update, lane B resume, diagnostics ask, settings request, file moves, Resolve undos, ingest cancels and job offers all ride the one report reply, each with its own delivery rule (always present, one-shot, until answered, until a separate upload arrives). Ten parallel command mechanisms with four different retirement rules.
- Three ways to move a computer to a different build: per-computer UPDATE NOW (`POST .../update`), MAKE CURRENT, and ROLL THE FLEET BACK (which itself may re-point current and then pushes per computer). Rollback can also be done with MAKE CURRENT on an older build plus per-computer pushes.
- The release gate is applied at five doors (this route, the Packages page's own form, roll-back, publish with make_current, and the vendor feed); the free-space refusal is shared with the feed and the CLI wizard.
- `youtube_import` exists twice in the report: a top-level tolerant section (parsed, not stored) and `sync_guard.youtube_import` (stored and shown).
- Many report fields are parsed, bounded and then not stored by this route: top-level `queue`, `current_project`, `lane_b_via`, `youtube_import`; inside `sync_guard`: `reporter`, `clock_skew_seconds`, `root_state`, `shared_folder_problems`, `repath_events`, most of `trash`, `disk_floor`, `stray_projects`, `ingest_staging`, `skipped_exists.samples`, `sync_conflicts.paths`, the breaker's extra fields and the persist-failure trios; most of `proxy_coverage`; `transport_health.express` beyond two fields. They exist to keep the "undeclared section" banner quiet.
- The "undeclared report sections" machinery (accept unknown keys, walk one level down, log once a day, store a banner record) exists only to detect the dashboard falling behind the companions.
- Two nearly identical ingest-cancel lookups (b-roll and music), and two identical ingest report sections.
- The rename-versus-cloned-disk logic duplicates a home-page check of the same kind (`duplicate_machine_id`) that the collector also evaluates every cycle.
- `GET /fleet/halt` and the `commands.halt` block of every report reply carry the same information to companions.
- `/jobs/machines` and `/jobs/{id}/why` both describe what computers can do; the former deliberately avoids saying whether one may take a job now.

## Claims the code does not back
- The `PUT /admin/packages` docstring and comments describe the "already published at this version, with these exact bytes" success path; the route itself refuses any existing version with `409` before receiving the body, so that path is reachable only when two uploads of a new version race.
- `CapabilitiesIn` and comments describe `claude`, `load`, `volunteer_until` and `jobs_idle_seconds` as inputs to scheduling; this route only stores the whole capabilities object. Whether the scheduler reads them is outside this part.
- Comments on `SyncGuardIn` say `restarts`, `root_state` and `disk_floor` are "stored by the v33 step"; in this route `root_state` is not stored at all, and of `disk_floor` only the floor bytes are.
- The report comment says per-project media writes run because "the same machine reports again 60 s later"; the companion's cadence named everywhere else in this file is 30 s.
- `MAX_JOB_OFFERS = 8` is described as "what one machine may be offered on one report reply", but the report reply does not pass it; it uses the scheduler's own default (also 8). The constant is used only by the claim route.

## Could not determine
- What `alerts.send` returns for the test button, and what `recovery.page_view`, `preview_restore`, `restore_into_quarantine` and `run_drill` return or refuse in detail (recovery.py and alerts.py are outside this part).
- The exact shape of `soak` per package and of `rollout` (db.py `soak_state`, `rollout_status` not followed).
- What `db.upsert_machine_state` does with each flattened column beyond storing it (for example how the client clock is clamped), and how `store_blocked_state`, `store_upgrade_state` and `store_resolve_health` treat an absent value in every case; the descriptions above follow the comments in this file plus the latch rule stated there.
- The full scheduling policy behind `offers_for_machine` and `explain` (jobs.py, outside this part): idle floors, ranking, cooldown and the "upgrading" refusal are only referred to here.
- How the `ever_current` flag, retraction (`retracted_at`) and `staged_at` are set: no route in this part sets a retraction.

