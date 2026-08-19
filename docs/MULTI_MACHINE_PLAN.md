# One person, several computers — per-machine sync plans

Written 2026-08-18, from two things the owner said the same afternoon:

> Alex should never show up in the queue because it's the base rig account.

> I also want to add single users having multiple computers and therefore
> needing multiple sync plans.

They look like two requests. They are one: **the fleet's unit of sync is the
machine, and the dashboard still models it as the person.** The base rig
appears in `[ QUEUED ]` because a tick belongs to `alex` rather than to a
machine of alex's, and a second laptop needs its own plan for exactly the same
reason. Fixing the first properly is the first work package of the second.

Related: `SPEC.md` (fleet model), `docs/SERVER.md` (provisioning),
`docs/TENANCY.md` (accounts), `docs/SYNC_SAFETY.md` (what stops a lane),
`KNOWN_BUGS.md` CR-27/CR-28.

---

## STATUS — BUILT 2026-08-18/19, in repo, unshipped

All of it, plus the pushed/unattended updates in §9. What changed from the
plan as written below, and why:

* **§3.1/§3.2, the key.** The plan is keyed **`(editor_username, machine)`**,
  where `machine` is the hostname every other per-machine table in the fleet
  is already keyed on -- NOT on a synthetic `machine_id` primary key. Keying
  the one table differently from `machine_state`, `editor_media_project`,
  `editor_media`, `lane_report_current` and `active_transfers` would have put
  a lookup in the middle of the widest queries in the dashboard, to buy
  nothing those tables get. `machine_id` is still minted and still reported:
  it is an ATTRIBUTE of the machine row, and its job is the rename case --
  a report whose id matches a known machine under a different hostname
  ADOPTS it (`db.adopt_renamed_machine`), carrying the plan and the sticky
  root across.
* **The unassigned bucket.** `machine = ''` means "this editor's machines
  that have none of their own", resolved once in
  `db.selections_for_machine`. It is not the inheritance §3.2 argues
  against -- a machine with a plan is never also handed the bucket -- it is
  what stops the migration, the collector's one-shot seed and a
  too-old companion from losing rows. A migrated fleet has none.
* **§4 WP8 (merging `alex_laptop` into `alex`) was NOT built**, per §7.2.
  The split accounts keep working untouched.
* **The sidebar checkboxes stayed the PERSON.** Ticking there means "every
  computer I use" (it fans out; its tooltip says so), and unticking removes it
  everywhere. One computer at a time is the assignments grid. Two controls
  with two scopes beats one control whose meaning depends on a hidden
  selector -- and "I want this project" is what an editor is actually
  expressing when they tick it next to a project name.
* **The wizard's copy-plan (WP6)** landed on the **assignments grid** instead
  (`copy from…` per column, `POST /api/v1/admin/machines/{editor}/{machine}/
  copy-plan`): same affordance, no installer release needed to get it.

Schema: `machine_state.mode` (v22), `machines` (v23),
`selections`/`editor_prefs` re-keyed (v24), pushed updates (v25). Companion:
`machine.py`, the two report fields, `?machine=` on the selection fetch.

---

## 0. Ground truths (verified in the tree and against the live NAS, 2026-08-18)

- **`selections` is keyed `(editor_username, project_slug)`** — `db.py`'s
  schema, PK on those two columns. There is no machine anywhere in it. It is
  the authority for three separate consumers: the Syncthing share set
  (`collector._run_enforce`), the lane A/B backlog
  (`db.fetch_sync_backlog`), and the companion's own queue
  (`GET /api/v1/selection/{editor}`, `companion/selection.py:198`).
- **Everything downstream of a tick already knows about machines.**
  `editor_media_project`, `editor_media`, `machine_state`,
  `lane_report_current`, `active_transfers`, `media_tree_clips` and
  `transfer_history` are all keyed `(editor_username, machine, …)`. The
  companion reports `machine = platform.node()` on every tick
  (`reporter.py:329`). The fleet grid already draws one row per machine.
  The tick is the ONLY per-person thing in a per-machine pipeline.
- **Lane C shares are already per device.** Syncthing shares a folder with a
  *device ID*, and `collector._run_enforce` fans a tick out to
  `editor_devices[editor]` — *every* device whose name resolves to that
  username. Per-machine plans are not a new concept for lane C; they are the
  concept Syncthing has, which the enforce cycle currently flattens.
- **A Syncthing device name is a username**, by convention
  (`db.resolve_editor_username`, `POST /api/v1/admin/devices/approve`
  sets `name = username`). A name that is username-*shaped* but unknown is
  UNMAPPED and is never touched — the B16 fail-safe. Two devices may carry
  the same name: ruskin has two rows in `devices` today, one dead from the
  2026-07-27 key regeneration.
- **`mode` ("base" | "editor") reaches the dashboard on every heavy report**
  (`ReportIn.mode`, `api.py:3691`) but is only ever persisted onto
  `editor_media_project` rows (`api.py:3970,3996`; column at `db.py:64`).
  There is no `machine_state.mode`, so a machine that has never sent a media
  manifest has no recorded role at all.
- **The lane A/B backlog already excludes base machines** —
  `db.fetch_sync_backlog`'s pair query ends `WHERE emp.mode != 'base'`. The
  other two queue sources in `api.build_transfers_view` do not:
  the lane C block (`api.py:417-437`) joins `selections` to `devices` by
  username, and the "just ticked / GETTING READY" block (`api.py:470-499`)
  joins `selections` to `projects` and nothing else.
- **Live data confirming the bug**: `selections` holds
  `('alex', '2026-ff5-animals', created_by 'alex', 2026-08-18T03:57:36Z)`;
  every `editor_media_project` row for `alex/Creator_1` says `mode='base'`;
  there is no Syncthing device named `alex`. So the row can never gain a
  completion row, and the GETTING READY chip it renders is permanent.
- **The current multi-machine answer is a second account**: `alex` (base rig,
  Creator_1) and `alex_laptop` (Razer) are one human with two NAS accounts,
  two Syncthing identities, two tokens and two tick lists. It works. It is
  also why the fleet page lists four "editors" for three people.
- **Per-machine already works elsewhere.** Requester-first ytdl downloads,
  b-roll ingest and music ingest all dispatch to a *machine*
  (`machine_state.ingest_*`, the fleet job routes). The tick list is the
  outlier.
- The companion can read its own Syncthing device ID:
  `sync/syncthing_admin.py:551` (`GET /rest/system/status` → `myID`). It does
  not report it today.

---

## 1. WP0 — the base rig must never appear in `[ QUEUED ]`

**Symptom** (screenshot, 2026-08-18): `alex · 2026/FF5/Animals [ GETTING
READY ] just ticked; sharing and first file lists are being set up, syncing
starts within a minute or two` — for a machine that syncs nothing, ten hours
after the tick, forever.

**Cause.** `api.build_transfers_view`'s pending block asks only "is there a
selections row for an active project with no completion row yet?". For a base
machine both halves are true permanently: nothing syncs, so no completion row
is ever written.

**Fix, in three parts** (the third is the one that matters):

1. **Record the role where it belongs.** Add `machine_state.mode TEXT` and
   write `ReportIn.mode` to it on every report (one column, one assignment;
   the value is already parsed and validated). `editor_media_project.mode`
   stays as it is — `fetch_sync_backlog` reads it and the two must not drift,
   so both writes happen in the same report handler.
2. **Teach the other two queue sources what the first one knows.** The lane C
   block and the pending block both grow the same exclusion: a machine whose
   `machine_state.mode = 'base'` contributes no queue rows, and an editor
   whose every known machine is base contributes none at all. Keep
   `editor_media_project.mode` as the fallback for a machine that has
   reported manifests but predates the new column.
3. **Stop the tick from being possible.** A base machine works directly off
   the NAS tree; a project tick for it means nothing and is how the phantom
   row got created. The sidebar checkbox and the assignments grid cell render
   disabled with `base rig - syncs nothing` for a base-only editor, and
   `PUT /api/v1/selection/{editor}/{slug}` returns 409 with that sentence
   rather than writing the row. (Hyphen, not an em dash: this string is
   user-visible.)

**Data fix**: delete the one stray row
(`DELETE FROM selections WHERE editor_username='alex'`). Harmless either way
once (2) lands — there is no `alex` Syncthing device for the enforce cycle to
share anything with — but it should not sit in the table looking like intent.

**Tests**: `dashboard/tests/test_presence.py` already asserts GETTING READY
appears; add its mirror (a base-mode machine with a tick produces *no* queue
row, and the whole panel says "everything that should be somewhere is
there"), plus a 409 test for the write path.

WP0 is independently shippable and does not need anything below it.

---

## 2. What a second computer costs today

Everything a person owns is welded to their username: the NAS account and its
SFTP home, the Syncthing device name, the per-editor report token
(`editor_report_tokens`), the tick list, the sticky project-root override
(`editor_prefs`), and their row on every page. So "Ruskin gets a laptop"
currently means **make a second person**: `ruskin_laptop`, its own account,
its own device approval, its own token, its own ticks. That is what
`alex_laptop` is.

It works, and it should keep working — but it is wrong in ways that get worse
with a paying customer:

- The fleet page counts machines as people. Four "editors", three humans.
- Presence, health and the assignments grid can't say "Ruskin is fine, his
  laptop is stale" — they say two unrelated editors have two unrelated states.
- Nothing shared per person is shared: sign in twice, get handed two tokens,
  accept the licence twice under two identities.
- Quota, retention and any future per-seat licensing count seats wrong.
- The admin has to invent and remember the naming convention.

---

## 3. The model: the machine is the unit, the person is the owner

**Keep** the username as the identity of a *person*: NAS/SFTP account, login,
Syncthing device name, tokens, licence acceptance, permissions. Nothing about
accounts, provisioning or auth changes.

**Add** a machine as a first-class row that belongs to a person, and move the
*plan* onto it:

```
person   ruskin          NAS account, login, token, permissions
  machine  DESKTOP-LQQ41TC   plan: Season 1, Event 1, Energy Transition
  machine  ruskin-macbook    plan: Energy Transition only
```

A tick answers "should THIS COMPUTER hold this project", which is the question
the sync engine has always been answering.

### 3.1 Machine identity

`platform.node()` (the hostname) is what we have and it is not stable enough
to key a plan: it changes when someone renames their PC, and two people can
own two machines with the same stock Dell name. The Syncthing device ID is
stable and unique but **regenerates** on a Syncthing reinstall — that exact
event cost a fleet day on 2026-07-27.

So: **the companion mints a machine id once** — a UUID4 in
`~/.ccsync/machine.json`, written next to `identity.json`, never derived from
hardware — and reports it on every tick alongside the display name and, new,
its Syncthing device ID. The dashboard keys plans on `machine_id` and shows
`machine` (the hostname) as a label the editor can rename without consequence.

Two payoffs beyond this feature:

- The `(machine_id → syncthing_device_id)` map means a machine whose
  Syncthing identity regenerates arrives as *the same machine with a new
  device ID*, which the pending-device screen can say out loud instead of
  leaving an admin to infer it from a never-connected device row.
- The enforce cycle can finally target a device instead of a name.

`machine_id` is self-asserted by the companion, exactly as `machine` is today,
and rides inside the same authenticated report — it is an identifier, not a
credential, and nothing is authorised by it. Worth stating in the code
comment so nobody later mistakes it for one.

### 3.2 Where the plan lives

`selections` gains a `machine_id` column and becomes
`(editor_username, machine_id, project_slug)`. **No inheritance rule** — a
plan belongs to exactly one machine. A new machine starts empty and the admin
(or the editor) ticks it, or clicks **Copy plan from…** and picks another of
that person's machines. The alternative — a per-person default plan that
machines inherit until they override it — is one more state to explain and,
worse, silently starts a 50 GB download on a laptop that was never given a
plan. Explicit is the safer default here.

---

## 4. Work packages

Each is separately shippable and leaves the fleet working.

### WP1 — the machine registry
*Companion*: mint/read `~/.ccsync/machine.json`; add `machine_id` and
`syncthing_device_id` to the report payload (`reporter.py`, beside the
existing `machine`). Both getters are cached and zero-I/O like every other
section.
*Dashboard*: `machines` table — `(machine_id PK, editor_username, name,
platform, syncthing_device_id, first_seen, last_seen)`; upsert on report;
backfill one row per existing `(editor_username, machine)` pair with a
generated id, so history and manifests keep resolving. `machine_state` and
friends keep their `(editor, machine)` keys for now and gain `machine_id` as
an indexed column — a rename of every key is a separate, later, mechanical
change and must not ride in with behaviour.
*Surfacing*: the fleet grid names the machine from `machines.name`; the admin
users page grows a "machines" column per person.

### WP2 — plans move onto machines
Schema: `selections.machine_id` + PK change (SQLite: new table, copy,
rename — the existing migration pattern in `db.py`).
Migration: **fan out**, one row per (existing tick × that user's known
machines). One machine per user today, so the fleet's live behaviour is
byte-identical the moment it lands.
API: `GET /api/v1/selection/{editor}?machine=<machine_id>`,
`PUT|DELETE /api/v1/selection/{editor}/{slug}?machine=<machine_id>`. The
machine parameter is **optional** and back-compatible (see §5).
`_require_selection_read/_write` are unchanged: authority is still the
person, and an admin can still write anyone's.

### WP3 — the enforce cycle targets devices
`collector._run_enforce` builds `desired` from
`selections × machines.syncthing_device_id` instead of
`selections × editor_devices[editor]`. Devices with no `machines` row remain
UNMAPPED and untouched (B16 fail-safe, unchanged). The blast-radius brake
(`enforce_max_share_removals`) stays exactly as it is and will be the thing
that catches a bad migration — expect to raise it deliberately for one cycle
if a big fleet's fan-out reshuffles shares, and say so in the runbook.
The one-shot `selections_seeded` bootstrap becomes machine-aware: it seeds
against the device's machine, not the name.

### WP4 — the queue and the backlog
`db.fetch_sync_backlog`'s pair query joins `selections` on
`(editor_username, machine_id)` as well as slug — it already carries
`emp.machine`, so this is a two-line change that makes the panel *correct*
rather than merely per-person. The lane C block joins through
`machines.syncthing_device_id`. The pending/GETTING READY block keys on
`(editor, machine, slug)` — which is also WP0's fix, one machine at a time
instead of one person at a time. `queue-group` `data-key` in
`partials/transfers.html` already has a `machine` slot; it starts being
filled.

### WP5 — the admin surfaces
`/admin/assignments` grows a machine dimension: rows are projects, columns are
machines grouped under their owner (`ruskin ▸ DESKTOP-LQQ41TC | macbook`), a
person-level header cell ticks/unticks the row for all of their machines,
and each column header carries **Copy plan from…**. `assignments.py` keeps its
"no write path of its own" property — every cell is still the one existing
selection endpoint, now with `?machine=`. The sidebar tick list and the
`?as=<editor>` switcher gain a machine selector that defaults to the viewer's
own machine when the viewer is an editor.

### WP6 — the editor's side
The companion sends `?machine=<machine_id>` on its selection fetch
(`selection.py`), so it receives *its* plan. The wizard, on a machine whose
person already has one, offers "copy <other machine>'s projects" as the
first-run default. Tray and popup copy says "on this computer" where it
currently says "you". Nothing changes for a single-machine editor.

### WP7 — per-machine preferences
`editor_prefs.project_root_override` is a property of a machine's Resolve
setup, not of a person; move it to `(editor_username, machine_id)` with the
same fan-out migration. `project_roots` (Resolve project name → tree slug)
stays fleet-wide; it is about the tree, not the machine.

### WP8 — optional: merge an account into a person
A one-shot admin tool that folds `alex_laptop` into `alex` as a second
machine: re-point the device, move the selections and manifests, keep the NAS
account alive until the machine's rclone remote has been re-keyed, then
disable it. Real work, entirely skippable — the split accounts keep working
untouched. Do this only when the owner actually wants the fleet page to read
"3 people, 4 computers".

---

## 5. Back-compat and rollout

- **Old companions never send `machine_id`.** Rule: a selection request with
  no machine parameter returns the **union** of that person's machine plans.
  For every editor in the fleet today (one machine each) that is identical to
  what they get now. It only diverges once a person genuinely has two
  machines, and there the dashboard warns on the assignments page: *"Razer is
  on companion 0.7.4 and cannot take its own plan - upgrade it first."*
  The union direction is deliberate: an old build that over-syncs is a full
  drive, an old build that under-syncs is an editor who quietly cannot open a
  project.
- **Order**: WP0 alone first (fixes the visible bug, no migration). Then
  WP1 (registry, invisible), WP2+WP3+WP4 together (the plan actually moves —
  these three must ship in one dashboard version, since a per-machine
  `selections` table with a per-person enforce cycle would unshare the fleet),
  then WP5/WP6, then WP7. WP8 if ever.
- **Rollback**: WP2's migration keeps the pre-migration `selections` content
  recoverable (the fan-out is lossless: collapse on `machine_id` to get the
  old table back). Take the usual `common.snapshot_before()` on the NAS before
  the dashboard deploy that carries it.

---

## 6. Risks

| Risk | Why it bites | Guard |
|---|---|---|
| A migration mis-fan-out unshares folders fleet-wide | This is the B16 shape, and it is silent | `enforce_max_share_removals` brake refuses the removals and logs loudly; deploy WP2-4 together; verify share counts before/after on the live Syncthing config |
| A new machine starts empty and the editor thinks sync is broken | No inheritance is the deliberate choice | The tray says "no projects are set for this computer yet"; the wizard's copy-plan default; the dashboard shows the machine with an empty plan rather than omitting it |
| Two machines, one NAS account, two rclone remotes on one SFTP home | Lane A uploads from both | Already true for any editor with a laptop today; lane A is add-only and path-canonical. Worth one integration test, not a design change |
| `machine_id` lost (profile reset) | Machine arrives as new, with an empty plan | Recoverable in the UI: "this looks like <old machine>, adopt its plan?" keyed on the Syncthing device ID match. Ship the prompt with WP5, not before |
| Hostname collisions inside one person | Two `DESKTOP-ABC` under one user | Solved by construction: the key is the minted id, the hostname is a label |

---

## 7. Decisions I need from you

1. **No inheritance** — a new computer starts with an empty plan and someone
   ticks it (or copies another machine's). Agreed, or would you rather a new
   machine automatically get everything that person's other machines have?
2. **`alex_laptop` and friends stay as they are** (WP8 skipped) unless you
   want the fleet page to stop counting machines as people.
3. **Who ticks?** Today an editor can tick their own projects and an admin can
   tick anyone's. With machines, do editors keep that for each of their own
   computers (my assumption), or does a second machine's plan become
   admin-only?
4. **Base machines**: WP0 makes a base rig untickable. If you ever want the
   base rig to *pull* a project locally, that is a different feature (a base
   machine with lanes enabled) and I would build it as one, not by leaving
   the tick open.

## 8. What I would ship first

WP0, on its own, this week: it is small, it needs no migration, it removes a
permanently-wrong row from the page that tells everyone whether their footage
is syncing, and it closes the tick hole that created it. The rest lands as one
dashboard version plus one companion version, in the order in §5.

(In the event all of it was built in one pass -- see the STATUS block at the
top. The ordering above still governs the SHIP: the dashboard carries v22-v25
and must go out first, because a per-machine `selections` table read by a
person-level enforce cycle is exactly the unshare-the-fleet shape §6 warns
about. Companions can follow at their own pace; one too old to name itself
gets the union of its owner's plans.)

---

## 9. Updates without a click (built 2026-08-18)

The owner's question, the same afternoon: *"is there a way to push an upgrade
to a user over the air without them clicking update"*. There was not: the only
thing that could install a published build was the editor clicking **Update
now** in their own tray, which is how ruskin's PC sat two versions behind for
a day with its lanes parked and nothing on the dashboard able to move it.

Two paths now, both built on machinery that already existed:

**Pushed, one machine at a time.** Settings → Packages lists out-of-date
machines; each row has **[ UPDATE NOW ]**. That records a version on the
machine's registry row (v25) and the request rides the `commands` block of
that machine's next report -- the same channel the fleet halt uses, so it
arrives within one report interval with no push infrastructure and no inbound
connection to an editor's PC. `POST /api/v1/admin/machines/{editor}/{machine}/
update` is the API; the request clears itself the moment the machine reports
the version that was asked for.

**Unattended, per site.** `site.toml [features] auto_update` (default OFF,
published in `GET /api/v1/site`, read fail-closed by the companion). With it
on, a companion applies any offer that is NEWER than what it runs, as soon as
swapping the exe would not kill work in progress.

What neither of them does:

- **Neither installs anything the tray click could not have.** The command
  names a VERSION; the bytes come from the signed offer the companion is
  already holding, checked against the release public keys baked into the
  running build and against that machine's downgrade floor
  (`upgrade._accept_offer`). A push for a build this machine is not being
  offered is refused and logged.
- **Neither interrupts work.** `apply_upgrade`'s stand-down test (an open
  CCSync window, a consolidate in flight) applies exactly as it does for the
  click.
- **Auto-update never rolls a machine BACKWARDS.** The dashboard advertises
  "different, not newer", and a rollback taken silently is a one-click loss
  of everything the running build fixed (seen live 2026-07-25). An admin
  rolling one back deliberately uses the push, which says so.

**Order matters, and it was followed here:** CR-27 -- the licence dialog that
could never open -- is fixed in the same pass. Turning unattended updates on
before that would have carried every editor across the 0.8.0 licence gate
silently and parked them, one machine at a time, with nothing on screen to
explain it.
