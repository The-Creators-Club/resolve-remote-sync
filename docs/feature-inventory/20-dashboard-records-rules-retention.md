# Dashboard: what it remembers, the rules it decides by, and what it forgets

Terms used throughout:

- **Dashboard**: the web server on the NAS that every editor computer reports to.
- **Companion**: the program on each editor computer that syncs files and reports to the dashboard roughly every 30 seconds ("a report").
- **Computer** / **machine**: one editor computer, identified to the dashboard by its owner's sign-in name plus its hostname (the name the operating system gives the computer). The hostname is treated as a label, not as a permanent identity.
- **Machine id**: a random identifier the companion creates once and reports afterwards, so the dashboard can recognise the same computer after it is renamed.
- **Project**: one folder on the NAS that is synced as a unit. Its **slug** is its short identifier.
- **Tick**: one computer being assigned one project to sync. The set of ticks for a computer is its **plan**.
- **Unassigned bucket**: ticks recorded for a person without naming a computer. They apply to any of that person's computers that has no ticks of its own.
- **Wired machine** / **base rig**: a computer that works directly off the NAS share and syncs nothing. Reported by the companion as mode `base`. Any other mode, or no mode at all, counts as an ordinary editing computer.
- **Lane A / B / C**: the companion's three sync channels. A uploads camera originals to the NAS, B downloads proxies, C is Syncthing (a peer-to-peer sync engine) for everything else.
- **Syncthing share**: the NAS's Syncthing folder for a project being shared with one computer's Syncthing device. The **enforce cycle** is the dashboard's background pass that adds and removes those shares to match the plans.
- **Collector**: the dashboard's background thread that runs a series of passes ("kinds"): talking to Syncthing, walking the NAS, pruning, checking invariants, sending alerts.
- **Server clock** / **client clock**: the dashboard's own time versus the time a companion claims. Every freshness, ordering and age-out decision listed here uses the server clock unless stated.
- **Latch rule**: a reported value that is overwritten (including back to empty) by every report that carries the section it belongs to, so a condition that ended can clear. **Keep rule**: a reported value that is only overwritten when a report carries a new value, so a report that says nothing does not erase what was known.
- **NFC**: the composed Unicode spelling of accented characters. macOS reports file names decomposed; Windows and the NAS report them composed. Several comparisons below fold both to NFC.

Source for every section: `dashboard/src/ccsync_dashboard/db.py` and, for the original seven record kinds, `dashboard/src/ccsync_dashboard/schema.sql`. The routes, pages and background passes that call these rules live in other files and are inventoried in other sections; this section says what the records are and what the record-keeping itself decides.

## 1. Projects
(source: schema.sql, db.py)

### What is remembered about each project
- Its slug (the Syncthing folder identifier), its label (the path relative to the projects root, for example `2025/FF4/Nuclear`) and its full folder path on the server.
- When it was first and last seen by the collector.
- Whether it is active. Inactive projects disappear from every list, queue and backlog.
- Whether, when and by whom it was archived.
- Syncthing's own health for its folder: the folder state (for example `idle`, `scanning`, `error`, `stopped`), the folder error text (for example "folder marker missing"), when that was read, and how many items and bytes the NAS's own Syncthing folder still needs (what editors are pushing to the server).
- Its NAS inventory (see section 7), its cross-project folder links (section 1, below) and its per-device completion (section 2).

### Rules
- Every collector pass that still finds the Syncthing folder refreshes the label, path and last-seen time, and marks the project active again, unless it is archived. An archived project stays inactive no matter how often its folder is seen.
- **Archive**: sets the project inactive and records who and when. Refused (returns false) when the project is already archived or does not exist. Nothing is deleted: the folder, its marker, its files and every tick on it survive.
- **Unarchive**: makes the project active immediately (not at the next collector pass) and clears the archive stamp. Refused when the project is not archived.
- The archived-projects list is newest-archived first and shows, per project, how many different people still have it ticked.
- "Who has this project ticked" (for the archive confirmation) is the distinct list of people with a tick on any of their computers.
- **Projects that vanished from Syncthing** are deactivated, with two protections:
  - A grace period of 900 seconds (15 minutes) since the project was last seen, so a project created a moment ago, whose Syncthing folder is created by a later pass, is not deactivated in the gap.
  - A blast-radius brake: if the pass would deactivate more than the larger of 2 and a quarter of the active projects, nothing is deactivated. The refusal is stored with its time, the counts, the ceiling and up to 100 affected slugs, for a banner. Its wording is "Syncthing reported 0 of N folders - not deactivating anything" when Syncthing reported no folders at all, otherwise "Syncthing reported X of N folders - not deactivating K project(s)". The stored refusal is only cleared by a later pass that comes in under the brake.
  - A "force" option exists that applies the pass regardless of size. `UNREACHABLE: no caller passes it` (the code says so itself).
- When a project goes inactive, its NAS inventory is deleted at the next hourly prune.

### Cross-project folder links ("shared folders")
- A project's marker file can declare that it includes a folder of another project. For each declared path the dashboard keeps: the borrowing project, the declared path, the resolved lending project and sub-folder, a status (`ok`, `missing`, or another word with a detail), and first and last seen.
- Each collector pass replaces a borrower's whole link list; links that survive keep their first-seen time. A borrower whose marker no longer declares anything has its links cleared.
- A borrower's links are deleted outright only when the borrower is both absent from the marker scan and inactive as a project. A borrower that is merely unreadable for one pass keeps its links, so one bad read cannot unshare a lender's folder from every borrower's computers.
- The lender's project page lists only `ok` links. The enforce cycle reads only `ok` links.
- A file move inside a lent folder is also sent to the borrowers' computers (see section 8), for links that are `ok` or `missing`.

## 2. Syncthing devices and per-device completion (lane C)
(source: schema.sql, db.py)

### What is remembered
- Every Syncthing device the NAS knows: its device identifier, its name, which person it maps to (or none), whether it is the server itself, first and last seen, whether it is connected now, its last address and when it last connected.
- For each (project, device) pair currently shared: completion percentage (0 to 100), items, bytes and deletions still needed, the folder's total items and bytes, a smoothed download rate, and when it was last updated.
- A completion history for each pair, written only on meaningful change (rules below).
- For each incomplete pair, a list of the files the device is still missing, with sizes.

### Rules
- **Which person a device belongs to**: the device name, lowercased and trimmed. A name shaped like a Syncthing device identifier (eight groups of seven capital letters or digits separated by hyphens) belongs to nobody. A name that is not a valid username (must start with a lowercase letter, then up to 31 more lowercase letters, digits, dots, underscores or hyphens) belongs to nobody. A name that is username-shaped but not a **known editor** (section 3) belongs to nobody. Devices that belong to nobody are never added to or removed from shares by the enforce cycle.
- The mapping is recomputed on every collector pass, not remembered.
- **Connections**: each pass marks every device disconnected, then marks the currently connected ones connected with their address and the time.
- **Download rate**: each update computes how many bytes of "still needed" disappeared since the last update, divided by the elapsed seconds. The stored rate is 0.3 times that sample plus 0.7 times the previous rate. The rate restarts from the new sample when the "still needed" amount grew (new work arrived) or there was no previous rate. With no elapsed time, the previous rate is kept.
- **When a completion history row is written** (anything else is skipped):
  - always for the first row of a pair;
  - when both the new and the last row are at 100 percent, only every 6 hours;
  - when the whole-number percentage changed;
  - when the items needed went from 0 to more than 0, or changed by more than 10 percent;
  - when incomplete and at least 15 minutes have passed since the last row.
- **Missing files**: at most 500 names are kept per pair; a capped list is flagged as truncated on every row. An unchanged list is not rewritten; only its "refreshed" time is bumped, and only once it is at least 600 seconds old. Changed lists replace the old one wholesale. The list for a pair is cleared when the pair is complete.
- When Syncthing stops sharing a (project, device) pair, its completion and missing-file rows are deleted, so a computer that no longer syncs a project stops showing as behind on it.
- Forgetting a device deletes its completion, history and missing-file rows.
- The project list attaches every non-server device's completion row, ordered by person then device name. Only active projects are listed, ordered by label.

## 3. People: who counts as an editor, suspension, removal, display names, credentials
(source: db.py)

### Known editors
- The dashboard keeps a record of every sign-in name it has positive evidence is a real editor account, with when it was first recorded and the source: `report` (a companion reported under it), `seed` (the one-time seeding from existing Syncthing shares), `selection` (a project was ticked for it) or `admin` (an admin approved a device or created the account). Names must be valid usernames; anything else is ignored.
- **Who counts as a known editor** (used by device mapping, suspension and the display-name clash check): anyone in that record, anyone with a tick, anyone with a stored project-root preference, and anyone whose companion has a current machine report. Names are folded to lowercase.
- Recording a name with source `admin` also lifts that person's **delete tombstone** (below). No other source ever does, so a removed person's laptop cannot re-admit itself by reporting.

### Suspension (pausing a person's fleet access)
- Stored on the known-editor record: when, by whom, and a reason (at most 255 characters).
- Suspending is refused (returns false) for an invalid username or for a name that is not a known editor.
- Suspending records the name as a known editor with source `admin` first, which, as a side effect, lifts any delete tombstone for that name.
- Lifting a suspension clears the three fields; it is refused when the person is not suspended.
- The plan is untouched by either: lifting a suspension restores exactly what was ticked.
- "Who is suspended" answers "nobody" only when the database is too old to have the field. A busy or locked database is raised as an error rather than answered as "nobody", so a lock can never re-share a suspended person's folders.

### Identity revocation and the delete tombstone
- Per person, one small record: a generation counter, a "valid after" time, a removed flag, and when, by whom and why (reason at most 255 characters). It is stored under a key derived from a keyed hash of the name, so the record itself carries no readable name.
- **Revoking** bumps the generation and moves "valid after" to one second past now (never earlier than its previous value, so a clock step cannot revive old tokens). Every companion identity token issued before that moment stops being accepted (the check itself is in another file). Revoking with "removed" sets the delete tombstone; once set, a later revoke never unsets it.
- **Lifting the tombstone** happens only through an admin re-creating or approving the name (or suspending it, see above). The generation and "valid after" stay, so tokens from before the removal stay dead.
- If the record cannot be read because the database is older than the feature, it reads as "never revoked" (fail open). A lock is raised.

### Pending SSH keys (accounts whose key arrives from the setup wizard)
- The setup wizard can submit a public SSH key for an account before an admin has finished creating it. The dashboard keeps: username, key fingerprint, key text (at most 4096 characters), the computer it came from (at most 128 characters), when, and the source (default `wizard`, at most 32 characters).
- One row per (username, fingerprint): a resubmission replaces the same row.
- A row grants nothing. It is a queue an admin approves or drops; listing is newest first.

### Per-person report tokens
- Format `cce1.<16 hex>.<48 hex>`: a version tag, a public identifier and a secret. Only a SHA-256 hash of the secret is stored; the full token exists only at the moment it is minted.
- Kept per token: the public identifier, the person, the hash, a label (at most 64 characters), who created it and when, when it was last used, and when and by whom it was revoked.
- Minting is refused for an invalid username.
- Verifying answers the person's name or nothing. Every failure (wrong shape, unknown identifier, wrong secret, revoked) gives the same "nothing", and the secret is compared in constant time.
- "Last used" is updated on a best-effort basis and never fails a request.
- Revoking is a soft delete: the row stays, marked revoked. Revoking an already revoked token does nothing.
- The token list excludes revoked tokens unless asked, ordered by person then newest.
- **Which credential each computer last reported with**: per computer, `shared` (the old fleet-wide token) or `editor` (a per-person token) and which per-person token identifier. Used to show an admin which computers will stop reporting when a token is revoked, and how many computers are still on the shared token (listed as `person/computer`). Unknown is shown as "cannot tell", never "none".

### Display names
- A display name is a label shown instead of the sign-in name; it is never used as a key anywhere.
- Normalisation: composed Unicode (NFC), trimmed, every run of whitespace collapsed to one space. Tab, line feed, carriage return, vertical tab and form feed count as whitespace; every other control character is refused.
- Refused with these exact sentences:
  - empty after normalisation: "A name cannot be empty. To go back to your sign-in name, clear the box and save."
  - longer than 64 characters: "A name can be at most 64 characters."
  - containing a control, format (for example zero-width or right-to-left override), surrogate, private-use or unassigned character: "A name cannot contain invisible or control characters."
  - equal (case-folded, composed) to another person's sign-in name or display name: "Someone else already goes by that name. Pick another." Your own sign-in name in any capitalisation is allowed.
- "Another person" covers known editors, local accounts, anyone with a profile, and any extra names the caller supplies (the configured admin list).
- The clash check and the write happen under one write lock, so two people cannot claim the same name at the same instant.
- Clearing a display name deletes it; the sign-in name shows again.
- Audit action names reserved for the account page: `account.display_name`, `user.display_name`, `account.password_change`, `account.signout_one`, `account.signout_others` (written by the routes, not here).

### Local accounts
- Kept only on sites using the dashboard's own sign-in: username, password hash (scrypt), role (`admin` or `editor`, enforced), created time, a disabled flag and a "must change password" flag; plus each user's SSH public keys (key text, fingerprint, when added, label), one row per (user, fingerprint). The behaviours around them are in other files.

## 4. Computers: the registry and what each computer last reported
(source: db.py)

### The computer registry
- One entry per (person, hostname): the machine id, platform, Syncthing device identifier, first and last seen.
- On every report, the entry is created or its last-seen time bumped. Machine id, platform and device identifier keep their old value when a report omits them.
- A person's computers are listed oldest-registered first.
- **One device, one computer**: when a computer reports a Syncthing device identifier that another registry entry also holds, the other entry loses it (its plan is untouched). The reporting computer keeps it.
- **Same computer under a new name**: a lookup by machine id returns the most recently heard-from entry first.
- **Lost computers**: entries not heard from for 7 days are listed with the projects still ticked for them.
- **Live**: an entry counts as live when it reported within the last 300 seconds by the server clock. An unreadable time is not live.

### Renamed computers (adoption)
- When a computer is recognised as renamed, its plan, its project-root preference, its original-file picks, its unanswered file-move and Resolve-undo commands and a pending settings request move to the new hostname, and the old registry entry is deleted. Manifests, lane reports and transfers are not moved; they rebuild under the new name and the old ones age out.
- Refused (nothing written) when the new hostname is already a registered computer of that person, so a name collision can never destroy a plan. The one exception: when the caller has already confirmed it is the same computer (same machine id, old name quiet), adoption onto an existing new-name entry is allowed only if that entry has no plan and no project-root preference of its own.
- A finished settings request already sitting at the new name gives way to a pending one from the old name; a pending one at the new name is kept (the newer ask).

### Per-person machine cap and eviction
- After every report, only a person's 20 most recently reporting computers (by server receive time) keep their current-state record. Older ones lose it.
- The registry entry of an evicted computer is also deleted, unless it still has ticks of its own or still has a Syncthing device identifier. In that case it is kept (and shows as lost), and a warning is logged: "NOT evicting <person>/<computer> past the 20-machine cap: N project(s) still ticked for it, it still has a Syncthing device. Its registry row is kept and it shows as LOST on the fleet page until somebody presses FORGET." Plans of evicted computers are never deleted by this cap.

### Forgetting a computer
- Deletes, for that one (person, hostname): its registry entry, current state, plan, project-root preference, lane reports, live transfers, media manifests and rollups, Resolve bin tree, credential record, file-move commands, Resolve-undo requests, b-roll stand-in records, settings request, original-file picks and diagnostics bundles.
- Lane history and transfer history are kept on purpose.
- The unassigned bucket is not touched (it belongs to the person).
- Returns the computer's Syncthing device identifier so the caller can remove it from Syncthing first.
- Refused (nothing) when the registry has no such computer, or the hostname is empty.
- A companion still running there registers the computer again on its next report; forgetting is not a revocation.

### What each computer's last report left behind
Each computer has one current-state record. The groups below each follow one of three update rules: **every report** (written blind), **keep** (only a new value replaces the old), or **latch** (rewritten, including back to empty, by any report carrying the section; left alone by a report without it).

- **Every report**: the project root the companion detected, the Resolve project open, whether the report carried a verified identity, the server receive time, the client's own clock reading and the measured clock skew.
  - Client clock: the companion's timestamp is stored only if within 7 days of the server clock; beyond that the server time is stored in its place and the real skew is kept as a number. An unreadable timestamp is stored as "unknown", never as "no skew". Skew is positive when the client is ahead. The threshold for flagging skew is 60 seconds (the flagging itself is elsewhere).
- **Keep**: platform, companion version, architecture, role (`base` or `editor`), transport counts (relayed and direct connections, orphaned partial files and their bytes, express-lane drops), trash size and count, the "skipped, already exists" counter (its project scope travels with it in the same write), the computer's own disk-space floor, proxy coverage (missing proxies, generator state, left to do), free and total disk space (replaced only when a disk section is present), and the project rotation interval.
  - The express-lane last error is replaced only when the report carried a transport section.
- **Latch**: lane B circuit breaker (tripped, reason, time), fleet or machine halt (active, scope, reason), the Syncthing supervisor record (down since, attempts, last error, supervising), crash count and newest crash file, unfiltered Syncthing folders (count and names), Syncthing conflict count, the companion-killed stall record (lane, seconds, killed, time). The marker is the time of the report's safety section.
- **Every report, never kept**: whether a b-roll indexing batch is active, and whether a music indexing batch is active. A report without the section sets them to "not indexing". The rest of each ingest section (batch, state, gate, done, total, failed, current clip or track, percent, tier for b-roll, warning) is replaced only when the section is present, so a section without a warning clears an old warning.
- **Version-since clock**: when a computer first reports a given companion version (or first reports at all), the server time is stored as "running this version since". It is the soak gate's input (section 10).
- Separately written groups, each with its own rule:
  - **Why it is not syncing** (latch, only from a report with a safety section): the companion's own blocked reason, detail and since, plus the sync-thread restart record (count in 24 hours, last time, last error).
  - **Upgrade outcomes** (latch, from a report with a safety section): the version it tried, attempts, last error, last attempt time. The "reverted from" version (sent once after a crash-loop rollback) is kept until the computer runs a version at or above it, then cleared automatically. Architecture is kept (keep rule) even from a report without the section. The error code `crash-looped` means "kept crashing and was rolled back", never a failed download.
    - A revert withdraws any standing pushed update for the version the computer fled, audited as `machine.update_push_withdrawn` by `system` with reason "crash-looped and rolled back".
  - **Refused offers**: the version, reason and time of an update the computer refused on receipt. Absent means not refusing.
  - **Resolve health** (latch): clips referenced from outside the tree, clips with a bad path prefix, missing clips, ignored clips, last scan time, stray project folders (count, bytes), moved project folders, bytes waiting in an ingest drop folder, and the list of Resolve projects not open that hold clips only on that computer (with counts) and its scan time. A further nine details (connected, project open, wedged seconds, wedged call, missing clips, non-canonical refusals, proxy attach, proxy gaps, stills) are kept in a separate per-computer record; a report whose section carries none of them deletes it.
  - **Send to Resolve port** (latch): enabled, bound, port, error, since. All empty means "too old to say", never "bound".
  - **Undo journals**: up to 20 journals the computer holds. A report without the section keeps the old list; a damaged list reads as empty.
  - **Capabilities** (replaced wholesale when present, untouched when absent): GPU present, GPU name (128 characters), VRAM, hardware video encoder, ffmpeg, ffprobe, whisper and its detail (255), Claude, mounts (at most 16 names of 32 characters), CPU count, idle seconds, load, Resolve running and its project (255), jobs enabled (default true), its own allowed job kinds (at most 16 names of 32 characters; empty or absent means every kind), volunteering until (64), the Timeline Cards agent's connected flag, state (32), timeline (255), version, since, gate state (32), detail (1000), last poll time (64), last HTTP status, and the job gate's reason (32) and detail (255).
    - Idle seconds being empty means "cannot tell", which every reader treats as not idle. Zero means someone is typing.
    - A computer that never sent capabilities has none, which the scheduler treats as "offer nothing with a requirement".
  - **Reported settings** (replaced wholesale when present, untouched when absent; section 15).
  - **Telemetry opt-outs, how the report arrived, accepted licence** (section 16).
  - **Job cooldown** (section 14).
- **Cannot tell versus no**: a computer whose last report had no safety section answers "unknown" to "is its breaker tripped", never "no".
- **Role**: the role on the current-state record wins; a role on a project rollup is the fallback for computers that have not reported since roles were recorded. A computer with neither is an editing computer. "Base-only person" means every known computer of theirs is wired; a person with no computers at all is not base-only.
- The most recently detected project root across a person's computers, and the most recent current-state record of a person, are both looked up by the latest report time.

### Parked one-shot requests to a computer
Three requests are stored on the registry entry and delivered on that computer's next report reply. Each is refused (returns false) when no such computer exists, and is audited.
- **Pushed update** (audited `machine.update_push`): the version, when, by whom, and the version the computer was on when pushed (looked up from its last report if the caller did not say). The direction lets the report handler tell an upgrade from a rollback. A new push resets the "withheld" verdict to undecided. Cleared when done. Expires after 14 days unanswered, audited `machine.update_push_expired` by `system` with reason "not taken within 14 days".
  - **Withheld verdict**: a sentence saying why the push is not being sent (written only when it changes, not audited). Empty means undecided, which every job reader treats as "about to upgrade" and refuses all job kinds to that computer.
- **Resume proxy download** (lane B breaker; audited `lane_b.resume_request`): when and by whom. Cleared when the computer reports its breaker no longer tripped, so it can never clear a later trip.
- **Ask this machine why** (audited `diagnostics.request`): when and by whom. Cleared only when a diagnostics bundle with trigger `admin_request` arrives, not when the reply goes out. Computers with an ask in flight are listed so the button can say it was asked.
- A summary of what is already parked on a computer (update version and time, resume yes or no, diagnostics yes or no) is read before a second click.

### Report refused on identity
- When a report is refused only because its identity token cannot be verified, the registry entry records when and why (reason at most 200 characters), and nothing else from the unverified body. Only an existing registry entry is stamped. Any accepted report clears it.
- Computers whose identity token was signed with a retired signing key are listed with the time (at most 200, newest kept); an accepted report on the current key removes the computer from the list.

### Diagnostics bundles
- Kept per bundle: person, computer, machine id, trigger, the companion's time, the server receive time, and the text (at most 256 KB of characters).
- Only the newest 5 bundles per computer are kept, enforced at write time. Bundles older than 30 days (server receive time) are pruned.
- Lists are newest first, capped between 1 and 200. A per-computer view shows only each computer's newest bundle.

## 5. Sync plans: ticks, modes, the unassigned bucket, and where footage lands
(source: db.py)

### What is remembered about each tick
- Person, computer (or empty for the unassigned bucket), project, position in that computer's queue (the order its sequencer works through), when and by whom it was created, when it was last written or had its mode switched, and its mode.
- **Modes**: `full` (lanes A, B and C) or `upload_only` (lane A only: originals go up, nothing comes down, and the Syncthing folder is never shared with that computer). Any other mode is refused with "unknown sync mode".

### The one inheritance rule
- A computer syncs its own ticks. Only if it has no ticks of its own at all (in any mode) does it inherit the person's unassigned bucket.
- A wired computer syncs nothing, whether by own ticks or by inheritance.
- A person with no registered computer keeps bucket ticks attached to "no computer"; they are still counted as ticked for that person, not dropped.
- The rule is applied by: the per-computer plan read, the fleet-wide "which computers sync this project" map, the per-computer plan summary and project-list maps, and the backlog query. They differ in one respect:
  - the fleet-wide map drops a wired computer's own ticks only when asked to (its "for enforce" view); without that it keeps them, and the admin tick grid uses the version that keeps them;
  - the plan project-list map keeps a wired computer's own ticks;
  - the per-computer plan read drops them always.
- A person-level read with no computer named is the union of all the person's computers' ticks (deduplicated by project, first by queue position), so an old companion over-syncs rather than under-syncs.
- Per project and person, the mode is reported as `full`, `upload_only`, or `mixed` when that person's computers disagree.

### Ticking
- **Tick one computer**: if the computer has no ticks of its own yet, the bucket is first copied onto it (keeping who ticked and when, and not counted as a change), so the new tick does not silently replace an inherited plan. The new tick goes to the end of that computer's queue. Ticking a project already ticked in another mode switches the mode and keeps the queue position. Returns whether anything changed.
- **Tick a person** (no computer named): ticks every registered computer of theirs that is not wired. A person with no registered computer gets a bucket tick, which their first computer inherits. A person whose every computer is wired gets nothing written.

### Unticking
- **Untick a person** (no computer named, which is also what an old companion's untick means): removes the project from every computer of theirs and from the bucket.
- **Untick one computer**: if the computer held the project only by inheritance, it first gets its own copy of the bucket, then every other registered non-wired computer of that person gets its own copy too, then the project is removed from the bucket, then from this computer. Other computers therefore keep syncing it. This only happens for a registered computer that really was inheriting; an untick on a computer with its own plan that never held the project changes nothing.
- Every untick also drops the original-file picks for that project on the affected computers (files already downloaded stay where they are).

### Copying one computer's plan to another
- Replaces the target's plan with the source's: same projects, same modes, positions renumbered from 1, created by the person copying.
- Refused with "'<source>' is wired to the server: it works directly off the NAS and holds no plan, so there is nothing to copy from it" when the source is wired.
- Refused with "<source> has no projects ticked - copying it would empty <target>." when the source has no ticks (including inherited).
- The target's original-file picks for projects the source does not have are dropped; the source's picks are not copied.

### Plan snapshots for undo
- Before and after a plan change, the caller records where a project is ticked for a person and in which mode. A computer that holds the project only by inheritance is reported under its own name, so an untick of an inherited project is still visible and undoable.

### Where a computer's footage lands (project-root preferences)
- **Per-computer override**: a chosen project for a computer, with who set it and when. A computer without its own override falls back to the person's bucket override; a person-level lookup with neither falls back to any of their computers' overrides.
- **Sticky mapping of Resolve project names to tree projects**: one entry per Resolve project name (trimmed, compared without regard to capitalisation), with the project, source (`auto`, `editor` or `admin`), who and when.
  - The first mapping wins and is permanent: a second first-set is refused (two simultaneous first-sets cannot both win).
  - Only an admin can change or delete a mapping.
  - Resolve project names that companions have reported and that have no mapping are listed.
  - A person may only make a first mapping for a Resolve project name that one of their own computers has actually reported having open (compared trimmed and without regard to capitalisation). The exemption for admins is applied elsewhere.
- **Automatic matching of a Resolve project name to a tree project**:
  - A loose matcher scores shared words (lowercase letters and digits; numbers of up to 4 digits, such as years and part numbers, never count) and returns the single best label, or nothing on a tie. Used only where a wrong answer is cheap.
  - The confident matcher, the only one allowed to create a permanent mapping, requires the name to equal (after composing, case-folding, reading hyphens and underscores as spaces and collapsing spaces) either a whole label or a label's last folder name, for exactly one label. Two projects with that name (for example `2025/Shinto` and `2026/Shinto`) means no match.
  - A further check lists unregistered folders on the tree whose last folder name equals the name; any such folder (other than a folder containing the match) makes it a human's choice.

### Original files on request (picks)
- A pick names a file or folder of camera originals that one computer wants downloaded beside its proxies. Kept: person, computer, project, the composed key of the path, the path as typed, whether it is a folder, who picked it, how (`resolve` or `dashboard`) and when.
- Refused: a pick for the unassigned bucket ("a pick belongs to one computer, never the unassigned bucket"), an unknown source ("unknown pick source"), an empty path ("a pick needs a path inside the project").
- Picking the same path again keeps the first picker and time; switching a pick between file and folder updates it.
- Un-picking matches the composed key, so a Mac's spelling removes a pick made on Windows. Files already downloaded stay.
- **Expansion**: a folder pick means every original the last NAS walk found under that folder, so later uploads are included automatically. A file pick is handed to the companion even if the NAS walk has not seen it yet (marked "not on NAS", size unknown).
- Only projects with at least one file are included in a computer's list.
- **Total size** shown before a download: each file once however many picks cover it; a file the walk has not seen counts 0.
- **A file move takes picks with it**: picks on the moved path or under it are re-keyed to the destination; a folder pick that merely contained the moved file stays.
- The first companion version that acts on picks is 0.9.87; the add button is meant to be gated on it (gate applied elsewhere).
- Audit rows for picks name at most 100 paths; the count is always exact (the audit writing is elsewhere).

## 6. Lane reports and live transfers
(source: schema.sql, db.py)

### Current lane state
- Per (person, computer, lane): state (the companion's word; the schema comment lists `idle`, `syncing`, `error`, `paused` but nothing enforces it), queued count, transferring count, last error, last sync time, detail, companion version, the client's report time, the server receive time, the current project, bytes done and total, speed, estimated time left, a progress token, when that token last changed, and since when the lane has been in its state.
- **Progress token rule**: "since" is the server time of the first report that carried the current token. Re-sending the same token never resets it. A report with no token clears it ("no verdict").
- **Lane history**: a row is appended only when the lane's state or last error changes (person, computer, lane, state, queued, last error, server time).

### Live transfers
- Per (person, computer, lane, file name): direction (up or down), bytes done and total, percentage, speed, time left, project, and when updated.
- Each report replaces all of that computer's live transfers; an empty list clears them.
- A transfer counts as live only for 120 seconds after its last update. Lists show live transfers fastest first.
- A clip in a Resolve bin is shown as "uploading" when a live transfer for that computer has the same file name.

### Completed-file history
- Per completed file: person, computer, lane, name, direction, when it completed (the companion's time, or the server time if absent) and when received.
- Only the newest 300 rows per computer are kept, at write time. Rows older than 7 days are pruned. Lists are newest first (default 50).

## 7. Media presence: what the NAS holds and what each computer holds
(source: db.py)

### NAS inventory (per project)
- Per file: path relative to the project (composed Unicode), kind (`original` or `proxy`), extension, size, modified time, when refreshed.
- Per project: a signature of the folder tree (used to skip an unchanged walk), folder count, original and proxy counts and bytes, when walked, and the last error.
- **Collapse brake**: a new walk does not replace the inventory when the previous inventory had files and either the previous inventory had originals and the new walk has none, or the new walk found fewer than 10 percent of the previous count. The old inventory is kept and the last error is set to "walk returned N of M files - not replacing. The project directory looks unmounted or was renamed on the NAS." The tree signature is not updated, so the next pass walks again.
- A successful walk replaces the inventory wholesale and clears the last error.
- **Inventory error**: recorded with the time, and the tree signature is cleared so the next pass is forced to walk again (a transient error cannot become permanent).
- **Never-walked projects**: active projects with no inventory record at all are reported separately ("not counted yet" rather than "0 originals") and are walked first.
- **Proxy bytes for the tick warning**: unknown (not zero) for a project never walked.
- **Two halves of a hand move across passes**: when a file vanishes from one project and appears in another in different collector passes, each unpaired half is kept (half type `vanished` or `appeared`, file name, size, modified time, project, project path, relative path, raw path, first seen) so a later pass can pair them.
  - The first sighting time is kept even when seen again.
  - Only halves seen within 2 days are considered, at most 4000, oldest first.
  - Paired halves are deleted.
  - Before a pairing is believed, the current inventory is asked whether another file with the same name, size and modified time sits somewhere else right now (up to 200 candidates checked). If so it was a copy, not a move.

### Each computer's own disk (manifests)
- **Per-project rollup**: person, computer, project, role, original and proxy counts and bytes, whether the companion capped the list, and when reported.
- **Per-file list**: path (composed Unicode), kind, size, when refreshed. Capped at 2000 per kind per (person, computer, project); replaced wholesale on each report.
- **Resolve bin tree**: per clip: bin path (empty is the root bin), clip name, file path, kind (`original`, `proxy` or `other`), whether present, when refreshed. Capped at 4000 clips per (person, computer, project); replaced wholesale.
- Pages read: per project, each computer's rollup; which computers sent a bin tree; each bin with its clips and present and total counts.
- **Free disk space** for the tick warning: unknown when the computer never reported a disk section; otherwise free bytes and when measured. A whole-fleet map of free and total space exists for the assignment grid.

### b-roll stand-ins
- Per (archive path of the original, composed Unicode; person; computer): first and last seen. A stand-in is a temporary small clip placed on a remote computer in place of an editing proxy.
- Each report replaces that computer's whole set; a path seen again keeps its first-seen time.
- The fleet-wide list (most recently seen first, at most 200) is given to wired computers. An empty list means "this dashboard knows of none", never "there are none".

### The upload and download backlog (lanes A and B)
- Built per (person, computer, ticked active project) for computers that have reported a per-file list for that project, excluding wired rollups. The tick is resolved with the inheritance rule.
- **Download owed (lane B)**: NAS proxies not in the computer's list. Not listed at all for an `upload_only` tick.
  - When the computer's proxy list was capped (it holds more proxies than it listed), the count becomes the smaller of the diff and "NAS proxies minus proxies held", bytes likewise, and no file names are shown.
- **Upload owed (lane A)**: originals in the computer's list that are not on the NAS, minus files lane A never uploads. Those are, by file name, case-insensitive: `._*`, `*.editready.*`, `*.original.*`, `*.temp.*`, `*.f` followed by three digits then anything (download fragments), `*.failed`, `.ccsync-move-*`.
  - When the originals list was capped, the row is kept even at zero files and flagged uncertain.
- Each row: lane, direction, kind, file count, bytes, up to 50 file names (configurable), whether names were cut, whether the computer's manifest was capped, and whether the upload count is uncertain.
- **Computers that withhold their file list** (section 16): one uncertain upload row with zero files, marked "not reported", for each ticked active project of each non-wired such computer, so nothing reads as "nothing owed".

## 8. File moves made on the server and followed by every computer
(source: db.py)

### What is remembered
- **The move**: source project and its folder path as it was, source path, destination project and its folder path as it was, destination path, whether it is a folder, how many proxies moved with it, who asked and when, the server-side state and its detail (at most 512 characters), and links to the move it undid and the move that undid it.
- **Who asked**: `admin` (the project page's move button) or `detected` (a move someone made by hand on the NAS that the inventory walk recognised). Every move is audited `file.move` with from, to, folder or not, source and the number of computers told.
- **Per computer told**: when it was first told, when it answered, whether it succeeded, detail (512), attempts, last error, its state, when the wait expired, and whether Resolve still needs repointing.

### Which computers are told
- Every non-wired computer with the source project ticked (either mode).
- Every non-wired computer with a project ticked that borrows a folder of the source project (link `ok` or `missing`) when the moved path is inside that folder, is that folder, or contains it.
- Every computer whose per-file list shows it holds the moved path or something under it (compared composed; special characters in the path are escaped so `Gold_Card_Meetup` does not match look-alike names).
- If the source project is active: every non-wired computer that withholds its file list (section 16), since its holdings cannot be checked.
- The unassigned bucket is never a target.

### Server-side state machine
- `pending`: written and saved before the rename on the NAS. Pending moves are reconciled at boot and every collector cycle (by another file) and are never offered to computers.
- `done`: the rename returned. `partial`: the original moved but at least one proxy did not. `undone`: a later move put it back.
- A move recorded directly as `done` (a detected hand move) re-keys original-file picks at once; a pending one does so when it becomes `done` or `partial`.
- **Deduplication of detected moves**: an exact same move (same source and destination) recorded within a caller-given number of days is not recorded again.

### Per-computer state machine
- Untold, then told (the first delivery time is kept; the command keeps riding every report until answered).
- `retrying`: the computer tried and will try again; attempts and error are recorded and the command stays open.
- Answered: success (`done` or no state), failure, `blocked` (the computer ran out of attempts) or `not_synced_here` (it trashed its copy because it does not sync the destination; final and counted as success).
- A success marked "Resolve not repointed yet" can be completed by a second success answer, which clears the flag. A failure is never rewritten.
- **Expired**: a told-but-unanswered command expires 7 days after first delivery. An untold command never expires. A `retrying` command is spared while its computer is still reporting within those 7 days.
- **Reissue**: clears expiry, delivery and state so the clock restarts at the next report; audited `file.move.reissue` when an admin did it.
- **Offer**: at most 20 unanswered, unexpired commands per report, oldest first, only for moves that are `done` or `partial`. Commands filed under a former hostname of the same machine id are offered too, but only if that former name has been silent for more than 5 minutes (a live twin, such as a cloned disk, is not handed the other's commands). Answers are matched against the same set of names.

### Undo
- Offered while the move is `done` or `partial`, no computer has failed it (blocked counts as answered and failed), and it has not already been undone.
- The inverse move is an ordinary move; the original's target computers are added to it so every computer holding the file follows it back.

### Pages
- Per project: moves into or out of it, newest first (20), each with every computer's outcome and the number of days it has been waiting (since delivery, or since the request when untold), and counts of waiting, failed, expired, blocked and awaiting-relink computers.
- Fleet-wide: every unanswered computer of every `done` or `partial` move, oldest first, at most 50, with days waiting.

## 9. Admin-side Resolve undo
(source: db.py)
- An admin can ask one computer to replay one of its undo journals in reverse (undoing a clip-path change made by the companion). Kept: person, computer, journal identifier (256 characters), project name (256), who and when, first delivery, answer time, success, state, attempts, detail (512).
- Refused (returns 0) when the computer is not registered. Audited `resolve.undo.request`.
- Offered at most 4 per report, oldest first, unanswered only, including under quiet former hostnames (same rule as file moves). Never expires by age.
- Answers: `retrying` (it tried and something got in the way) and `parked` (no project is open in Resolve, so it did not try) both keep the request open. Any other answer closes it, recorded as `done` or `failed` when no state is given.
- The computer's recovery panel lists its requests newest first (20).

## 10. Release channel: published builds, rollout, recall, vendor feed
(source: db.py)

### What is remembered per published build
- Kind (`companion` or `onboard`), version, platform, file name, SHA-256, size, the signer's publish time and publisher, whether it is the current build for its kind and platform, the release signature, signing key identifier, the minimum version floor it asserts, whether the file itself is code-signed, rollout state (`staged` or `current`), when staged, the dashboard version it requires, architecture, the git commit and whether it was dirty, whether it was ever current, when it was recalled and why, when it was made current, and a one-line "what's new" note.
- One build per (kind, platform, version).

### Rules
- Publishing always enters a build as `staged`, with the staged time from the server clock.
- The note is folded to one line and cut to 300 characters; it is not covered by the signature.
- Only the advisory provenance (git commit, dirty) can be corrected after publishing; the signed fields never.
- **Make current**: refused for an unknown or recalled build. Every other build of that kind and platform becomes `staged` and not current; this one becomes `current`, marked "ever current", with "made current at" set to now (re-pointing restarts the clock; the build moved off keeps its stamp). Making an onboard build current never affects companion builds and vice versa. Other gates (the dashboard-version requirement, the soak gate, the unsigned confirmation) live in other files and are bypassed by anything calling this directly.
- **Recall**: un-currents the build and stamps when and why; the record and file stay. Recalling a build this dashboard never published, or one already recalled, does nothing (the time is not re-stamped). Audited `package.retract`, actor default `release-feed`. Recalled builds are listed so computers still running one can be flagged.
- **Delete**: removes one record and returns it for the caller to delete the file; it does not itself refuse the current build (the caller must).
- **Prune**: keeps the current build plus the 2 newest non-current builds per kind and platform (the number is a parameter); returns the removed records for file deletion.
- Lists are by kind, platform, newest published first.

### Soak gate input
- For one platform and version: every computer whose last report says it runs that exact version (platform missing is read as Windows), with how long it has run it (from the "version since" clock), its lifetime crash count, newest crash file and any crash-loop revert.
- **Whose crashes**: none recorded (count 0 or less) is "none"; no count is "unknown"; otherwise the newest crash file's time (read from a name starting `YYYYMMDDTHHMMSS`, or a plain timestamp) is compared with "version since": strictly earlier is "none", otherwise "some"; unreadable is "unknown".
- The gate passes when at least one computer has run the version for the soak time (default 30 minutes) with crashes "none" and no revert. Every "unknown" counts against passing.

### Rollout status
- For each platform with a current companion build: machines reporting a version on that platform, how many run the current one exactly, the ones strictly older by numeric version (a newer one is not behind), the ones refusing an offer (also counted behind), revert count, total failed attempts, and when it was made current (empty means cannot tell, for builds made current before that was recorded). Only companion channels are built.
- **Version comparison**: dotted numbers compared numerically (0.9.9 is below 0.10.0); anything non-numeric sorts below every real version.

### Vendor feed state
- One record: when last checked (success or failure), the last error (empty on success), the feed's own generated time, an unused cache tag, and a policy override (empty means the environment setting; otherwise `manual`, `stage` or `current`). Updates are partial; unknown fields are ignored.
- What the vendor feed offers, per platform (a list of versions); empty means unknown, never "nothing offered".
- A record of "every dashboard build on offer needs a new container image", cleared when no longer true.

## 11. Fleet halt
(source: db.py)
- One record: active, reason (at most 500 characters), who set it (64), when, when it expires, and how many times it was extended.
- Default length 24 hours. An expired halt reads as not active (and flagged expired), so the next report reply releases the fleet. An unreadable expiry is not treated as expired. A missing or unreadable record reads as not halted.
- **Keep halted** (extend) keeps the original reason, setter and start time, moves the expiry and adds 1 to the extension count.
- Extend with a reason shorter than 3 characters when nothing is halted is refused with "Syncing already started again at <date and time in the site's time zone, else UTC>. To stop it again, give a reason." or, with no time on record, "Nothing is stopped, so there is nothing to keep stopped. Stop syncing with a reason." A real reason with extend starts a fresh halt.
- Release stores an inactive record with the reason and setter.
- The last 20 halts, extensions and releases are kept newest first (time, action, who, reason, expiry).
- Audited `fleet.halt_set` or `fleet.halt_clear`.

## 12. The collector's own record and its brakes
(source: schema.sql, db.py)

### Run log
- One row per collector pass: kind, start, finish, success, and a note or error. A successful run may carry a note (for example "skipped" or "refused N removals"). The newest 2000 rows are kept.
- **Per kind status colour**: red when the last run failed; amber when it succeeded with a note or is overdue; green otherwise.
- **Overdue**: only for a kind this deployment actually schedules (prune, invariants and alerts always; the others only with a Syncthing address configured; provision and inventory also need a projects folder; with no settings in hand only the first three), only when the last run succeeded and the collector is not already stale. Bound: the larger of 180 seconds and twice the kind's cadence (the larger of the observed gap between its last two starts and its configured interval), plus the length of one recent collector cycle (the sum of each kind's longest run in the newest 200 runs). The note reads "overdue".
- **Syncthing reachable**: the newest run of a kind that needs Syncthing succeeded and finished less than 180 seconds ago.
- **Collector stale** (the thread has stopped): the newest start of any kind is older than the bound. Bound: twice the shortest observed gap between two starts of the same kind, at most 2 hours, at least 180 seconds. Before any kind has started twice: 180 seconds on a site with Syncthing (or where a Syncthing-backed run is on record), otherwise the larger of 180 seconds and twice the shortest configured interval of prune, invariants and alerts. No runs at all is not stale.
- **Folder errors**: active projects whose Syncthing folder has an error or is in state `error` or `stopped`.
- "Retention last ran" is the last prune run.
- **Held sharing notes**: the 5 most recent sharing passes (`config` or `enforce`) whose note is not empty.

### Enforce-cycle brake (share removals)
- **Refusal record**: when, how many removals, the limit, the folders and devices involved and up to 200 (folder, device) pairs, flagged truncated beyond that. Cleared by the next pass.
- **Per-computer allowance** (site setting `enforce_removals_per_computer`, 0 to 100, else "must be a whole number from 0 to 100"): the limit becomes the larger of the fixed limit and this number times the number of computers. Absent, unreadable or 0 means the fixed limit. Audited `enforce.allowance` with before and after.
- **Approve the refused removals**: refused with "no share removals are waiting for approval"; "the list changed: N removal(s) are waiting now, not M. Reload and check them again."; or, when the list was truncated, "too many removals to approve one by one; raise the per-computer allowance under Settings, then Sharing safety, instead". An approval names the exact pairs, lasts 1 hour, is audited `enforce.approve_removals` (first 50 pairs) and is consumed whole by the next cycle that reads it.
- **Pre-authorised removals**: a removal is explained by an admin act when, within the last 24 hours, the latest plan audit row for that (person, project, computer) is an untick that was not undone and the plan still lacks it, or a tick that switched the computer to upload-only and it is still upload-only.
- **Freeze after an untick**: shares affected by an untick in the last 60 seconds are left exactly as they are for that pass, so an undo within that minute costs nothing.
- **Plan preview**: what the last cycle was about to add and remove per folder (up to 100 folders, with totals).

### Report sections this dashboard does not read
- Accumulated across reports: per unknown section name (at most 20 names, 64 characters each, newest kept), up to 10 computers that sent it, a report count, and first and last seen, plus the dashboard version that recorded it.
- At boot, the record is dropped if a different dashboard build wrote it (or it has no version).

### Site settings history
- The last 10 saves or imports of site settings, newest first: when, who, what kind of change, and the before and after values of only the keys that change touched.

## 13. Self-diagnosis: notices, invariant checks, alerts and the audit ledger
(source: db.py)

### Notices ("problems the server found")
- One row per (kind, subject): severity (`info`, `warn` or `error`; anything else becomes `warn`), body, fix, first seen, last seen, cleared time.
- **Raise**: keeps first seen, bumps last seen and re-opens a cleared or dismissed notice. A dismissed condition that is still true comes back.
- **Clear by the pass that owns it**: closes one subject, or every subject of a kind except those still failing.
- **Dismiss** (admin): only an open notice; dismissing nothing is reported as a failure. Audited `notice.dismiss`.
- **Auto-clear** when a condition is evidenced as over: audited `notice.auto_clear` by `auto` with "auto: <reason>" (300 characters).
- The home panel shows at most 25 open notices, newest first. Counts by severity are kept for the health endpoint and the top bar.
- **"Checked" evidence**: every raise and clear (even with nothing to clear) stamps "this kind was evaluated now". Auto-clear does not. A kind not stamped within 36 hours shows as not checked, never OK; an undatable stamp is stale. Event-style kinds can be stamped without raising.
- **The registered kinds**, with severity, meaning and where its button goes (button label "Take me there" unless stated; a subject that looks like a slug goes to that project's page, otherwise the home page):
  - `project_container_marker` (error): a project marker on a folder that contains projects, hiding them all.
  - `project_nested_marker` (error): a project marker inside another project.
  - `duplicate_syncthing_folder` (error): two Syncthing folders over one directory.
  - `duplicate_slug_dirs` (error): one project identity claimed by two directories.
  - `unreadable_project_marker` (warn): a damaged project marker.
  - `provision_failed` (error): a project folder could not be set up for syncing.
  - `shared_assets_failed` (error): the shared asset libraries (LUT library) could not be set up.
  - `project_links_failed` (warn): a shared-folder link could not be resolved.
  - `collector_cycle_failed` (error, collector panel): a background job keeps failing.
  - `collector_db_write_failed` (error, packages page): the dashboard could not write its database.
  - `collector_watchdog_restart` (warn, collector panel): the background thread died and was restarted.
  - `syncthing_unreachable` (error, collector panel).
  - `projects_dir_missing` (error): the projects folder is missing or not mounted.
  - `inventory_refused` (error, project page): the file count collapsed, so the last good one is kept.
  - `file_move_detected` (info, home page): files moved by hand on the server, now being followed.
  - `enforce_refusal` (error, project page): too many share removals in one pass, none applied.
  - `deactivation_refusal` (error, no button): too many projects would have been marked gone at once.
  - `ignored_report_sections` (warn, packages page): a computer sends information this dashboard is too old to store.
  - `duplicate_machine_id` (error, home): one computer identity claimed by two hostnames (a cloned computer).
  - `duplicate_device_id` (error, home): one Syncthing device claimed by two computers.
  - `pending_device_approval` (warn, users page): a computer waiting to be approved.
  - `plan_without_share` (error, the project named after "->" in the subject): a project ticked for a computer that is not being sent it.
  - `share_without_plan` (warn, home): a computer being sent a project nobody ticked for it.
  - `editor_without_machine` (info, users page): an account no computer has reported for.
  - `invariant_broken` and `invariant_check_failed` (error, invariants page).
  - `protection_missing` (error) and `protection_unverifiable` (warn), protection page.
  - `dashboard_disk_low` (error, packages page), `machine_disk_low` (warn, home), `machine_trash_oversize` (warn, home).
  - `machine_forgotten` (warn, home): a computer stopped reporting long enough that the server gave up asking.
  - `feature_not_mounted` (warn, health page): b-roll, music, YouTube or cards did not start.
  - `feed_unreachable` (warn), `feed_publish_refused` (error), `feed_runtime_mismatch` (warn), all packages page.
  - `insecure_secret` (error, no button): a configured secret has quotes or spaces around it.
  - `dev_insecure` (error, no button): running with security checks relaxed.
  - `server_error` (error, health page): a page or API call failed.
  - `alerts_delivery_slow` (warn) and `alerts_sink_none` (warn), alerts page.
  - `server_crash_report` (error): button "Download crash reports" to the crash-report download.
  - `db_busy`, `slow_write`, `slow_poll` (warn, collector panel).
  - `file_moves_dropped` (error, home): more hand moves at once than could be followed.
  - `broll_archive_unreadable` (error, b-roll page): every clip sent to Resolve is the small preview.
  - `ai_cli_update_failed` (warn) and `cli_lock_stranded` (error), AI providers settings.
  - `triage_reply_refused` (warn, alerts page): a reply to the server-check email failed a check.
  - `notice_check_failed` (error, health page): one of the server's own checks is failing.

### Invariant check results
- Per invariant: a summary row and up to 20 subject rows naming what is broken, each with state, detail and check time.
- States: `ok`, `broken`, `not_checked`, `check_failed` (an unknown state is stored as `check_failed`). The yes/no flag is 1 for ok, 0 for broken, empty otherwise.
- An `ok` or `broken` verdict deletes subject rows the pass did not name. A `check_failed` verdict keeps the old subjects with their old times.
- A missing table reads as "no results", never an error.

### Alert delivery log
- Per send attempt: time, kind, subject (400 characters), where it went (400), success, detail (800), and a batch identifier (64) shared by rows that went out in one digest message.
- Failures are recorded.
- **Deduplication**: one (kind, subject) is not re-sent within 24 hours. By default only successful sends count; the sender counts failed attempts too, so a broken mail setup is not retried every cycle. An unreadable time counts as "not sent".
- A summary of the last scan's open alerts is kept for the top bar.
- Lists are newest first, 1 to 500.

### Fleet audit ledger
- Append-only per action: time, actor (never blank; "?" when unknown), action, subject, and a detail object.
- The timeline is newest first (1 to 1000) with a substring search over subject, actor and action; a weekly report reads it oldest first. A damaged detail shows as raw text.
- **Recent plan changes**: ticks and unticks in the last hour, newest first (at most 200), each marked when it has been undone (undo rows searched over 2 hours).
- Action names written in this file: `notice.dismiss`, `notice.auto_clear`, `enforce.allowance`, `enforce.approve_removals`, `package.retract`, `machine.update_push`, `machine.update_push_withdrawn`, `machine.update_push_expired`, `lane_b.resume_request`, `diagnostics.request`, `file.move`, `file.move.reissue`, `resolve.undo.request`, `fleet.halt_set`, `fleet.halt_clear`, `machine.settings_request`, `machine.settings_withdraw`, `machine.settings_applied`, `machine.settings_refused`, `machine.settings_expired`. Names defined here for other files: `plan.tick`, `plan.untick`, `plan.undo`, `plan.copy`.

## 14. Fleet job queue
(source: db.py)

### What is remembered per job
- Kind, created time and creator, priority, inputs (pairs of a root name and a relative path), hard requirements, a cost estimate, state, holder (person and computer), lease expiry, last heartbeat, attempts, last error, result, progress (0 to 1, or unknown), whether forced, a target computer, cancel request time and requester, last update time. Each JSON field is at most 16 KB, otherwise it is stored empty.

### Kinds and their numbers
- `whisper` (label WHISPER; 3 attempts; at most 2 running fleet-wide), `proxy-480p` (PROXY 480p; 3; 4), `audio-extract` (AUDIO; 2; 4), `peaks` (PEAKS; 2; 4), `card-ingest` (CARD COPY; 2; 4), `drive-copy` (DRIVE COPY; 2; 2), `ledger-scan` (DRIVE SCAN; 2; 4). Unknown kinds: 3 attempts, 4 running, label is the kind in capitals; they are accepted but never offered.
- Lease: 300 seconds without a heartbeat. Cooldown after a failure: 120 seconds. Finished window on the jobs page: 24 hours.

### State machine
- `queued` -> `claimed` (a computer took it) -> `running` (first heartbeat) -> `done`.
- From `claimed` or `running`, a failure: not retryable -> `failed`; retry budget spent -> `pinned` for `proxy-480p`, `audio-extract` and `peaks` when the dashboard has its own executor, otherwise `abandoned`; else back to `queued`. Every failure and every expired lease adds an attempt.
- Lease expiry re-queues (or pins or abandons) with "the lease held by <person>/<computer> expired at <time>".
- `pinned`: taken by the dashboard's own worker (holder "(dashboard)"), never offered to the fleet again. It ends `done`, or `abandoned` on failure. At boot, pinned jobs marked in hand are released back to the worker's queue. Pinned jobs do not count towards the fleet cap.
- Terminal: `done`, `failed`, `abandoned`.

### Rules
- **Candidates**: queued, not asked to stop, highest priority then oldest, at most a window of 200 per kind (so one kind's backlog cannot hide another's). Offered ids are looked up directly, beyond the window.
- **Claim**: one atomic write that succeeds only if the job is still queued, not asked to stop, and (when a cap is given) fewer than the kind's cap are held fleet-wide. Capabilities are re-checked at claim time. The claimant's own narrowing is intersected with what the scheduler offered, never widened.
- **Requirements**: `mount`/`mounts` names must be among the computer's mounts ("this computer has no X mount"); a true/false requirement must match ("X is not available on this computer" / "X is set on this computer"); a number requires at least that much ("X is V, the job needs at least W"); anything else must be equal ("X is V, the job needs W").
- **Heartbeat** extends only a live lease and moves `claimed` to `running`; a heartbeat after expiry fails. A heartbeat note goes into the last error; progress is clamped to 0..1 (not-a-number or absent means unknown).
- **Finish** is accepted from the holder even after its lease expired, as long as the job is still `claimed` or `running`; it clears the computer's cooldown.
- **Cooldown**: a retryable failure (not a cancelled one) parks the computer for 120 seconds with "job #N (<kind>) failed here: <first 120 characters of the error>"; a lost lease with "job #N (<kind>) lost its lease here". Reason at most 255 characters.
- **One job per computer**: the jobs a computer holds are listed so neither side gives it a second.
- **Cancel**: a queued job becomes `failed` at once with "cancelled by <who>" (who at most 64 characters, default "an admin"). A held or pinned job records the request; the computer is told on its next report and the pinned worker checks the flag. A job that finishes failing after a cancel request ends `failed` with "cancelled: the holder reported a failure instead (...)"; a cancelled job whose lease expires ends `failed` with "cancelled: the lease held by ... expired at ... without an answer". Nothing forces a running job terminal. Already-finished or missing jobs: nothing happens.
- **Try again**: creates a new job with the same kind, inputs (plus a pointer to the old job), requirements, cost, priority, force and target; the old job is untouched. Refused with "job #N is <state> and has not finished, so there is nothing to try again yet. Cancel it first." or "job #M is already a new attempt at job #N and it is still on the queue."
- **Queue depth** sent to companions: queued (excluding stop-requested), running, pinned, and the oldest queued job's age (empty, not zero, when nothing is queued).
- **Force and target**: stored as given; an unknown target computer is accepted.
- **A computer's own kind list**: empty means every kind.
- Finished jobs older than 30 days (last update) are pruned; queued jobs never are.
- The fleet grid shows each holder's job: kind label, state, heartbeat, lease, percent (unknown rather than 0 when not reported) and path.

## 15. Asking a computer to change its job settings, and what it reports about its settings
(source: db.py)

### The settings request
- Only two settings can be asked for: `jobs_enabled` (true or false) and `jobs_kinds` (a list of kind names, duplicates dropped, 32 characters each; a list naming every known kind is stored as empty, meaning every kind). The wired-or-remote mode can never be asked for.
- One request per computer. Refused (nothing) for an unregistered computer; a request with no valid setting raises "no computer setting to request".
- A new ask while one is pending is merged into it per setting (newer wins) under a new request identifier with delivery cleared. Any finished request is replaced outright. Audited `machine.settings_request`.
- States: `pending` -> `applied` or `refused` (from the computer's answer, audited with the editor as actor), `withdrawn` (admin, only while pending, audited), or `expired` (pending for 14 days, audited by `system` with "not answered within 14 days").
- Delivery time is stamped once per request identifier.
- An answer for a request identifier that is not the pending one is ignored. Any answer word other than applied or refused keeps the request pending and only updates its detail (255 characters).

### What a computer reports about its own settings
- Which of the two settings it can accept (only known names kept; absent means "cannot take a request"), its volunteer minutes (whole number 0 to 100000), its drive-reminder minutes (0 to 100000), YouTube status words (downloads, sign-in enabled, terms accepted: each yes, no or unknown; sign-in state at most 16 characters; nothing else is stored), settings waiting for a restart (only jobs enabled, jobs kinds (16 x 32), volunteer minutes, drive reminder), and when reported.
- Replaced wholesale when the section is present; untouched when absent. An absent "waiting for restart" is stored as "cannot tell", not "nothing waiting".

## 16. Telemetry opt-outs, how a report arrived, the accepted licence
(source: db.py)

### Withheld report categories
- Four categories a computer or the site can switch off: `resolve_project`, `local_manifest`, `media_tree`, `input_idle`. Switching off `resolve_project` also switches off `media_tree`. Unknown names are ignored.
- Per computer: the union of its own list and the site's, and its own list as sent. A report without its own list keeps the stored one (absent is not empty). Nothing known at all is stored as empty.
- **What withholding deletes** for that computer, at once and on every later report:
  - `resolve_project`: the open Resolve project (both places it is kept), the Resolve health details, the unopened-projects list; undo journals are kept but their project names blanked and identifiers masked.
  - `local_manifest`: its per-file lists and per-project rollups; and, unless `resolve_project` is also withheld, the path-bearing Resolve health details (missing clips, refused non-canonical clips).
  - `media_tree`: its Resolve bin trees.
  - `input_idle`: its idle time.
- A category newly withheld by a computer that can appear in diagnostics (all but `input_idle`) deletes that computer's diagnostics bundles.
- **Site policy change**: every computer's union is recomputed, and what the site now withholds is deleted for every computer, including ones known only from media records. A newly withheld diagnostic category deletes every diagnostics bundle. Switching a category back on restores and deletes nothing.
- Readers treat a withheld category as "not reported", never as zero or none.

### How the report arrived
- `https`, `http_local` or `http_public`; written only when it changes; any other value is refused.

### Accepted licence
- Version, accepted time and licence hash, each at most 128 characters. A block without a version is ignored; a report without one leaves it alone. Absent means "not reported", never "not accepted".

## 17. Personal data: export, history erasure, deletion and pseudonyms
(source: db.py)
- **The registry of records about a person**, each tagged:
  - current state (deleted on account deletion, untouched by "erase history"): computer registry (including requests they made), current state, ticks (including ones they created), preferences, lane state, live transfers, manifests, rollups, bin trees, credential records, file-move commands, Resolve undos, stand-ins, settings requests, picks, Syncthing devices (name and last address), invariant subjects naming them;
  - identity: known-editor record (and suspensions they made), profile, local account (password hash excluded from export), SSH keys, pending SSH keys, report tokens (hash excluded);
  - history (erased by "erase history"): lane history, transfer history, completion history, missing-file lists, diagnostics bundles;
  - evidence (kept, pseudonymised on deletion): audit rows (by actor, subject or detail naming them), alert rows, notices, jobs, file moves, sticky mappings they set, packages they published (signature excluded), projects they archived, site settings they changed (value excluded).
  - A subject matches a person when it is their name, starts with "name/", or is a computer name only they use (a hostname shared with someone else is not matched).
  - Declared as not about a person: triage replies (the sender is a site mailbox).
  - Declared as kept in other stores: sessions and sign-in attempts, YouTube download jobs, downloads and attestations, b-roll and music ingest batches, client folders and items.
- **Export** returns every registry row about the person with secret columns removed; tables missing from an older database are skipped.
- **Erase history** deletes only the history-tagged rows.
- **Delete a person** (in order): collect every computer name they ever reported under; erase their history; forget each registered computer (section 4); delete every per-computer record under their name, including the unassigned bucket and unregistered names; delete their diagnostics, their Syncthing devices with completion rows, their known-editor record and profile, their entry in the project group ledger and their membership in project group grants; then pseudonymise.
- **Pseudonyms**: `deleted-user-<10 hex>` and `deleted-machine-<10 hex>`, from a keyed hash under a 32-byte salt created once and never rotated, so one person stays one stand-in everywhere.
  - "Who did it" columns on surviving records are replaced exactly.
  - Audit actors are replaced unless the person was an admin (kept until the 180-day audit prune).
  - Subjects are replaced only at their structured positions (name, "name/...", the computer after "name/"); a bare computer name only on a row already tied to the person.
  - Free text (alert detail, notice body and fix, audit detail strings) is rewritten only on rows tied to the person, whole names only, case-sensitive (so `alice-b`, `alice.smith` and "Send a test email" survive deleting `alice` or `test`).
  - Computer names someone else also uses are never rewritten. Jobs' claimed and target computer names are rewritten.
  - When a renamed notice collides with an existing one, the newer is kept.
- After the person's tokens are revoked (elsewhere), their revoked tokens are deleted. Live tokens never are.

## 18. Other records kept here whose behaviour lives elsewhere
(source: db.py)
- **Site settings**: key, value, when and by whom changed. Only one key is read or written in this file: `enforce_removals_per_computer` (section 12).
- **Setup wizard progress**: per task, a status (default `todo`), detail, time and a skipped flag, so a wizard survives a restart.
- **Server triage agent**: runs (start, finish, status default `running`, a reply token stored only as a hash and its expiry, the report, whether the email went out, detail); the actions each run offered (number, action, parameters, why, state starting `offered`, result, the reply that acted, when), one per (run, number); and handled replies, one per email Message-ID (received time, sender, run, verdict, detail). Nothing in this file prunes them.
- **Project group grants and ledger**: two records stored here as JSON, only touched by person deletion in this file.

## 19. How the database itself behaves
(source: db.py)
- A request waits up to 5 seconds for the write lock; the collector and the session store wait up to 20 seconds.
- Writes are flushed in the mode that survives a crash or container restart but can lose the last transactions on a power loss of the host.
- Large lists (manifests, inventories, transfer history, stand-ins) are written in one statement each.
- **Upgrading the database**: each numbered step is saved together with its number, so an upgrade interrupted half way resumes at the next start; a step that adds a column already present skips it. A database newer than the running build refuses to start with "database schema is newer than this build: user_version=N, this build knows M. Deploy the matching (or a newer) image." The current number is 61.
- **Timestamps** are UTC text in one fixed shape, compared as text. A timestamp without a time zone is read as UTC.
- **"Too old to know" versus "busy"**: several readers (suspension, archive, pending keys, identity revocation, personal data) answer empty only when the database lacks the table or column; a lock or disk error is raised instead.

## 20. Retention: everything the dashboard forgets, and when
(source: db.py)
The hourly prune (the collector's `prune` kind) does all of the following in one sweep, measured against the server clock:
- Completion history: deleted after 30 days; after 48 hours thinned to the first row per pair per hour.
- Completed-file transfer history: deleted 7 days after receipt (also capped at 300 per computer at write time).
- Lane history: 30 days.
- Current lane state of a computer silent for 30 days.
- A computer's current-state record after 30 days of silence (also capped at 20 computers per person at every report). The registry entry and plan are not pruned by age.
- Missing-file lists not refreshed for 7 days.
- Unpaired hand-move halves after 2 days.
- b-roll stand-in records not re-reported for 30 days.
- Audit ledger rows after 180 days (the only deletion of audit rows; person deletion rewrites but does not delete them).
- Revoked report tokens 180 days after revocation; live tokens never.
- Alert log rows after 120 days.
- Cleared notices after 120 days, only if both cleared and last seen more than 120 days ago. Open notices are never pruned.
- Diagnostics bundles after 30 days (server receive time); also only the newest 5 per computer at write time.
- Collector run log: newest 2000 rows kept.
- Per-file manifests, project rollups and Resolve bin trees not refreshed for 14 days.
- Live transfers not updated for 120 seconds.
- Pushed updates unanswered for 14 days (audited).
- Settings requests pending for 14 days become expired (audited).
- Job leases that have expired (with the configured cooldown, default 120 seconds).
- Finished jobs not updated for 30 days; queued jobs never.
- NAS inventory of inactive projects.

Kept at write time or by count, outside the prune: missing files 500 per pair; manifests 2000 per kind; bin trees 4000 clips; site settings history 10; fleet halt history 20; retired-key computer list 200; ignored report sections 20 names; enforce refusal 200 pairs; enforce plan preview 100 folders; deactivation refusal 100 slugs; invariant subjects 20; undo journals 20; capabilities 16 mounts and 16 kinds; published builds pruned to the current plus 2 others per kind and platform (when the caller prunes).

Never forgotten by age: projects (only deactivated), the computer registry and plans (only by forget, rename, or the 20-computer cap when no plan or device remains), known editors, display names, live report tokens, sticky Resolve project mappings, file moves and their per-computer outcomes, Resolve undo requests, settings requests once finished, published builds, original-file picks, queued and pinned jobs, triage records, site settings, setup tasks, open notices, invariant results.

## 21. Database upgrades that change behaviour or rewrite records
(source: db.py)
What a site upgrading across each step observes. Pure additions of empty columns or tables are omitted.
- **v11** (package kinds): every published package becomes a `companion` package; installers become a separate kind with their own current build.
- **v23** (computer registry): every computer that ever reported is registered at once, with its last report time as first and last seen.
- **v24** (plans per computer): every existing tick is copied onto each of that person's registered computers; people with no registered computer keep it in the unassigned bucket. Project-root overrides are copied the same way. A fleet of one-computer people sees no change; a person with two computers now has two independent plans, both starting as the old one.
- **v28** (tick modes): every existing tick becomes `full`.
- **v30** (server receive time): filled from the old report time.
- **v31** (audit ledger): existing ticks get an empty "changed" time.
- **v34** (rollout): builds that were current become `current` and "ever current"; all others become `staged`; staged time is set to the publish time. Every computer's "running this version since" is set to its last report time, so soak clocks start at the upgrade, not at the real install time.
- **v36** (file-move states): every existing move becomes `done`.
- **v48**: "made current at" is left empty for existing builds, so rollouts started before the upgrade read as "cannot tell".
- **v49**: existing notes are empty; which token each computer used is unknown until its next report.
- **v50**: archive and suspension start empty; nothing changes until used.
- **v52**: existing pushed updates have no "from version" and keep the old rule (cleared once the computer reports that version or later).
- **v53**: every existing move is recorded as an admin move.
- **v56**: open `slow_write` notices whose subject begins "collector poll " are closed (a one-time cleanup).
- **v59, v61**: telemetry, licence and unopened-project fields start as "not reported".

## 22. State machines (summary)
(source: db.py)
- **Project**: active <-> inactive (folder gone past the grace and the brake) ; active -> archived (inactive) -> unarchived (active).
- **Computer registry entry**: registered -> live (reported within 5 minutes) / quiet / lost (7 days) -> forgotten or renamed (adopted) or evicted (cap, only without plan and device).
- **Computer current state**: present -> evicted (cap) or pruned (30 days silent).
- **Person**: unknown -> known editor -> suspended <-> unsuspended; revoked (generation bumped); removed (tombstone) -> re-admitted only by an admin.
- **Report token**: live -> revoked -> deleted 180 days later (or on person deletion).
- **Pushed update**: none -> requested (withheld verdict: undecided / a sentence) -> cleared (taken, withdrawn by a crash-loop revert, or expired after 14 days).
- **Lane B resume**: none -> requested -> cleared when the breaker reports untripped.
- **Diagnostics ask**: none -> requested -> cleared when an admin-requested bundle arrives.
- **File move (server)**: pending -> done / partial -> undone.
- **File move (per computer)**: untold -> told -> retrying ... -> answered (done, failed, blocked, not synced here); told -> expired (7 days) -> reissued -> untold.
- **Resolve undo**: requested -> delivered -> retrying / parked ... -> done / failed.
- **Settings request**: pending (merges) -> applied / refused / withdrawn / expired.
- **Published build**: staged -> current -> staged (another made current) ; any -> recalled (staged, never current again) ; deleted or pruned.
- **Fleet halt**: released -> halted -> extended ... -> expired or released.
- **Job**: queued -> claimed -> running -> done; held -> queued (retry) / failed / pinned / abandoned; pinned -> done / abandoned; queued -> failed (cancelled).
- **Notice**: open -> cleared (by its pass, by dismiss, or auto) -> reopened when raised again -> deleted 120 days after clearing.
- **Invariant**: not checked / ok / broken / check failed, replaced each pass.
- **Enforce approval**: none -> approved (1 hour) -> spent by the next cycle or expired.
- **Pending SSH key**: submitted (re-submit replaces) -> approved or dropped (deleted).

## Looks redundant or overlapping
- Six separate "command for one computer" channels with nearly the same deliver-until-answered contract: pushed update, lane B resume and diagnostics ask (columns on the registry), file-move targets, Resolve undo requests and settings requests (their own tables), plus job cancel requests. Each has its own expiry and clearing rule, and the former-hostname fallback is applied to only some of them.
- The computer is described twice: the registry (platform, last seen, machine id) and the current-state record (platform, version, last report), with different retention (registry kept, state pruned after 30 days and capped at 20).
- The computer's role is stored both on its current state and on every project rollup.
- The unassigned-bucket inheritance rule is reimplemented in at least five readers (per-computer plan, fleet map, plan summary, plan project list, backlog query), and they disagree on whether wired computers' own ticks count.
- Two Resolve-name matchers (loose and confident) plus a rivals check; the loose matcher and a retired constant for the old confident rule remain.
- b-roll ingest and music ingest are two copies of the same column set.
- Resolve health is split between columns on the current state and a separate per-computer record.
- Several histories that overlap: fleet audit, alert log, notices, site settings history, fleet halt history, the enforce refusal and plan preview records, and ignored report sections, each with its own shape and retention.
- Collector liveness is computed three ways (stale bound, configured bound, per-kind overdue bound) from the same run log.
- Four ways to stop a person: suspension, identity revocation, the delete tombstone, and the local account's disabled flag.
- Token use is recorded twice: "last used" on the token and "which credential" per computer.
- Diagnostics are bounded both by count (5 per computer) and age (30 days); transfer history by count (300) and age (7 days).
- The job queue has both a fleet path and a dashboard-side pinned executor for the same three media kinds.

## Claims the code does not back
- The suspension function's description says an account created on the NAS and never used "still has to be suspendable"; the code refuses any name that is not already a known editor (ticked, reported, approved or with a preference).
- The audit ledger's description says nothing ever updates or deletes its rows except the 180-day prune; person deletion rewrites actor, subject and detail on existing rows.
- The known-editor record is described as append-only; suspension updates it and person deletion deletes from it.
- The schema comment lists the collector kinds as `config | connections | completion | remoteneed`; the code also records `prune`, `invariants`, `alerts`, `provision`, `inventory` and `enforce`.
- The schema comment lists lane states `idle | syncing | error | paused`; nothing enforces that list.
- The job requirement check is described as refusing "everything unrecognised"; an unrecognised requirement whose wanted value is an empty string is satisfied by a computer that reports nothing for it.
- The pending file moves function takes a maximum age argument and ignores it.
- The fleet-wide plan map's "for enforce" option is named for the enforce cycle, which (per the code's own comment) does not use it; the collector drops wired computers by a separate rule of its own.
- The "card-ingest" and "drive-copy" kinds are described as always submitted forced and targeted; nothing in this file enforces that.
- The vendor feed's cache tag field is described as reserved; nothing uses it.
- The "force" option on deactivating vanished projects has no caller.

## Could not determine
- The fixed share-removal limit (`DASH_ENFORCE_MAX_REMOVALS`) and the per-kind running-cap override (`DASH_JOBS_MAX_RUNNING`): defaults and parsing are in other files.
- Whether the "must change password" flag is enforced anywhere (comment says it is not).
- Who calls the package prune and with what number kept.
- Whether the triage tables are ever pruned (a comment elsewhere in this file says 60 days, but no prune here touches them).
- Whether the collector actually applies the 60-second untick freeze, the 24-hour authorisation and the per-computer allowance as described; this file only provides them.
- The configured cadences of each collector kind (in the settings file).
- What writes the project group grants and ledger records.
- The `cancelled` prefix's interpretation by companions.

Files of this part, both read in full: `dashboard/src/ccsync_dashboard/db.py` (all 14,472 lines) and `dashboard/src/ccsync_dashboard/schema.sql` (all 101 lines); both are represented above.
