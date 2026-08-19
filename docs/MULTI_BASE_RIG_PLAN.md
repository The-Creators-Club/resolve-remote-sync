# Wired or remote — the role belongs to the computer, not the person

Written 2026-08-19, from what the owner said while the tray-icon fix was
being made:

> the companion also needs updating so that more than one person can have
> 'base rig' status. For example, people who work in offices with multiple
> computers directly connected to the nas.

> the wizard options should be changed to 'I'm a remote editor' and 'I'm
> physically connected to the server/NAS'

> Billy has a computer at the office, a laptop and a desktop at home, he
> should use the same account to log in on all of them but we should register
> that his computer at the office is a physically connected identity, the
> personal laptop and PC are remote editor identity.

That is the whole diagnosis in the owner's own words. There is no such thing
as *the* base rig: there is a machine that reaches the footage over a wire and
a machine that reaches it by syncing, one person can own both, and the product
currently asks a different question - *is this person an admin?* - and derives
everything from the answer.

Companion: `mode` in `config.toml` + `identity.role`. Dashboard: `role` at
sign-in, `machine_state.mode`, `db.base_only_editors`. Related:
`docs/MULTI_MACHINE_PLAN.md` (per-machine sync plans, built 2026-08-18/19,
whose model this completes), `SPEC.md`, `docs/TENANCY.md`, `KNOWN_BUGS.md`
CR-27/CR-28.

---

## STATUS

* **WP0 — DONE 2026-08-19, in repo, unshipped.** `effective_mode()` answers
  `base` when either source says so (`companion/.../app.py`), the tray icon is
  green on a wired machine (`tray.compute_overall_color`), and
  `installer/windows_upgrade.ps1`'s comment about the role overriding the local
  value is corrected. One prior assertion was deliberately reversed:
  `test_editor_role_can_never_enable_sync_on_a_base_flagged_config` used to
  pin `effective_mode() == "editor"` so an admin could see the disagreement -
  see the comment in `companion/tests/test_role.py` for why that lost.
* **WP5's copy — DONE 2026-08-19** (installer 1.0.35), the wizard question
  itself. The precedence half of WP5 is not built.
* Everything else below is unbuilt.

---

## 0. Decisions taken (2026-08-19, owner)

1. **Per-machine toggle on the dashboard** - yes, and switchable **both by
   the editor for their own machines and by an admin for anyone's**.
2. **Auto-detected too**: the companion works out for itself whether it is
   physically connected or remote, and reports it.
3. **One account, several machines.** Billy signs in as `billy` on all three;
   the office desktop is registered wired, the laptop and home PC remote. No
   more `billy_office` second accounts.
4. **Producers stay at one** per site (proxies, b-roll indexing, music
   indexing) - the safe default, no cross-machine lock work for now.
5. Each computer keeps its **own tree and its own ticked projects**. Already
   true as of dashboard 0.7.0 (per-machine plans, schema v24); §5 says what is
   left.

Terminology from here: **wired** (works directly off the NAS; the role stored
as `base`) and **remote** (syncs its own copy; stored as `editor`). The stored
values do not change - too much code and too many rows key on them - but every
piece of visible copy uses the owner's words.

---

## 1. Ground truths (read in the tree 2026-08-19, nothing assumed)

1. **A machine can already be wired locally, and more than one can be.**
   `config.toml`'s `mode = "base"` selects `MODE_PROFILES["base"]`
   (`companion/src/ccsync_companion/config.py:656`), forcing
   `sync_enabled = false` and `lane_b_enabled = false`. Nothing counts wired
   machines or objects to a second one. The *engine* already supports an
   office of them.

2. **Nothing supported puts a machine in that state.** The value is
   hand-edited. `installer/windows_upgrade.ps1:296` only preserves an existing
   `mode` line and writes `mode = "editor"` when there is none. The wizard has
   a radio - and loses it, see (6).

3. **The dashboard mints the role from the PERSON.**
   `dashboard/src/ccsync_dashboard/api.py:1368`:
   `"role": "base" if auth.is_admin(settings, username) else "editor"`.
   That is the `DASH_ADMIN_USERS` list, reused by design in 2026-07 when the
   base rig and the admin were the same one machine. It is the root cause of
   everything in §2.

4. **The companion is protected against that in ONE direction only.**
   `app.py:2967` `_apply_identity_role` is deliberately monotonic: the role
   may only ever *disable* sync, never enable it (AUDIT_2 CORE-C1 - a
   server-supplied `role="editor"` on a wired machine points a deleting
   `rclone sync` DOWN at the live NAS tree). The unprotected direction is
   `role="base"` arriving at a machine that really does sync.

5. **`effective_mode()` prefers the role over the machine's own file**
   (`app.py:3033`), so a wired machine owned by a non-admin *reports*
   `mode="editor"` - and `machine_state.mode` is what CR-28's queue exclusion
   rests on (`db.machine_modes`, `db.py:1133`).

6. **The wizard's radio is overridden by that same person-level role.**
   `onboarding/steps.py:1146` `effective_install_role`: "the verified role
   wins whenever the dashboard sent a recognised one". For an office user who
   is not in `DASH_ADMIN_USERS`, picking wired yields an **editor install**,
   which on Windows runs `subst P: /D` + `net use P: /delete /y` and re-creates
   `P:` as a loopback share of a local folder. On a machine whose `P:` is the
   real NAS share, that is the B20 failure the docstring warns about,
   triggered from the other side.

7. **`base_only_editors` is a person-level rollup** (`db.py:1156`): "usernames
   whose EVERY known machine is a base rig". Five call sites: the queue
   exclusion (`api.py:423`), the tick 409 (`api.py:1562`), the copy-plan 409
   (`api.py:2718`), the assignments grid (`assignments.py:96`) and the sidebar
   (`ui.py:769`, `ui.py:859`). By contrast `fetch_sync_backlog` (`db.py:3117`)
   excludes wired machines **per machine** already - the model is
   half-migrated.

8. **The machine registry is already per person, per computer.** `machines`
   (v23) is keyed `(editor_username, machine)` with the companion-minted
   `machine_id` surviving renames, and `selections` is keyed
   `(editor_username, machine, project_slug)` (v24). Billy's three computers
   are three rows under one account **today**; nothing about the account model
   needs changing.

9. **The detection signals exist.** Windows: `drive_swap.current_p_target()`
   already reads `net use` / `subst` and `classify_p_target` compares a UNC
   against the derived server share (`derive_server_unc`, `drive_swap.py:492`).
   macOS: `root_guard` already spawns `diskutil info -plist` per volume and
   caches it. Neither answers "is my tree on the NAS" yet, but neither needs
   new machinery to.

10. **Nothing coordinates two wired machines writing into the same tree.**
    `proxy_gen._claim_partial` (`proxy_gen.py:725`) is an in-process set. The
    ytdl download lease is keyed on the editor NAME
    (`ytdl/web/ytdlweb/db.py:673`), so one person's two machines each believe
    they hold it. Decision 4 above is the answer for now.

11. **The tray icon was amber on the base rig for exactly this reason** -
    fixed 2026-08-19 in `tray.compute_overall_color` (a wired machine's "sync
    is off" is its correct state, not a warning), reading the local `mode`
    first *because* of (5).

---

## 2. What a second wired machine costs today

| Situation | What happens now |
|---|---|
| Two admins, one wired machine each, `mode="base"` hand-written | Works. Both report `base`, both excluded from the queue. |
| Billy's office desktop (Billy is not a dashboard admin) | Lanes stay down if someone hand-edited the config, but it **reports `editor`**, so it sits in `[ QUEUED ]` under a `GETTING READY` chip that can never clear - CR-28 again, one machine at a time. Amber tray icon until today's fix. |
| Billy runs the wizard on that desktop | Picks wired, gets an **editor install**: `P:` unmapped and replaced with a loopback share of a local folder. Every `P:\Projects\...` path in the Resolve database now points at the wrong tree. |
| An admin with a wired desktop AND a remote laptop | The laptop is told `role="base"` at sign-in and **silently syncs nothing**, for ever, with no error. Not yet observed only because no admin has onboarded a second machine. |
| Billy's laptop and home PC want different projects | Already correct (v24 per-machine plans). |
| Two wired machines both idle-generating proxies | Both scan the same tree, both queue the same clip, both write the same `.partial`, and whichever finishes first is published over the other's half-written file. |

---

## 3. The model

**R1. Wired/remote is a property of a COMPUTER.** Same ruling
`docs/MULTI_MACHINE_PLAN.md` made for sync plans, applied to the role that
decides whether there is a plan at all.

**R2. Dashboard admin and NAS-wired are orthogonal.** `auth.is_admin` keeps
deciding dashboard permissions and stops deciding sync behaviour.

**R3. Detection may promote, never demote.** The companion's own detection can
move a machine to **wired** on its own (the safe direction: lanes stop). It may
never move a machine to **remote** on its own, because that is the direction
that starts a deleting `rclone sync` down onto the live tree (CORE-C1). Going
remote is always a human act.

**R4. A human choice pins the role.** Once an editor or an admin sets a
machine's role, detection stops changing it and only *warns* when it
disagrees. `mode_source` records which it was.

**R5. The companion refuses to sync onto the NAS, whatever anyone says.** If
detection finds that this machine's tree IS the NAS share, lane B does not run
- role, config file and dashboard notwithstanding. This turns CORE-C1 from a
rule three code paths remember into one mechanical refusal.

**R6. The reported mode is the machine's truth.** `effective_mode()` answers
`base` if either source says so, so `machine_state.mode` stops lying about
office machines.

**R7. One producer per site.** Proxies, b-roll indexing and music indexing run
on the machine the admin nominates, not on every wired machine that happens to
be idle.

---

## 4. Work packages

### WP0 — report the truth (companion, ~10 lines) — SHIP FIRST, ALONE

`effective_mode()` returns `base` when *either* the verified role or
`config.toml` says so. No schema, no dashboard, no UI.

Effect on its own: a wired machine reports `base`, so CR-28's queue exclusion,
`fetch_sync_backlog`'s `WHERE emp.mode != 'base'` and today's green tray icon
all start covering it. Tests: a `mode="base"` config with `role="editor"`
reports `base`; a dashboard test that such a report keeps the machine out of
the queue. Fix `installer/windows_upgrade.ps1:296`'s comment in the same
commit - it currently claims the role overrides the local value entirely.

Risk: a machine wrongly carrying `mode="base"` disappears from the queue.
Mitigated by it already syncing nothing in that state, and by WP2's machine
list making every wired machine visible in one place.

### WP1 — detection (companion)

A new `link.py`: `detect(config) -> {"link": "wired"|"remote"|"unknown",
"why": str, "server": str}`, run at start-up and on the same cadence as the
P: mapping refresh (`_refresh_p_mapping_mode`, already a 10 s cached probe).

* **Definition**: *wired* means **this machine's `local_root` resolves onto a
  network filesystem served by the NAS host**. Not "is on the office LAN": a
  machine that syncs its own copy from the next desk is a remote editor on a
  fast link, and must keep its lanes.
* Windows: `local_root` is a UNC, or its drive letter is `DRIVE_REMOTE`
  (`GetDriveTypeW`) whose `net use` target names the NAS host. The parsing
  already exists in `drive_swap.current_p_target` / `classify_p_target`.
* macOS: the mount point behind `local_root` is `smbfs`/`nfs` and its server
  is the NAS host (`mount` output, or the `diskutil info -plist` probe
  `root_guard` already caches).
* The NAS host comes from `remote_root` / the site manifest / `dashboard_url`,
  the same derivation `drive_swap.derive_server_unc` uses.
* Anything unclear answers `unknown`, which changes nothing anywhere.

Reported on every heavy report as `link` + `link_why`. Also drives R5's
refusal and a tray line ("this machine works directly off the NAS").

### WP2 — the toggle (dashboard, schema v26)

`machines` gains: `mode` (the role the dashboard holds, NULL = never decided),
`mode_source` (`auto` | `user` | `admin`), `mode_set_by`, `mode_set_at`,
`detected_link`, `detected_at`.

Resolution, in order:

1. No stored `mode` -> adopt `detected_link` (`mode_source='auto'`).
2. Stored `base`, detection says remote -> **keep base**, show a chip. (R3.)
3. Stored `editor`, detection says wired -> promote to `base` when
   `mode_source='auto'`, log it, and show what happened; when a human set it,
   keep their choice and show the loud version of the chip: *this machine is
   on the NAS and is not syncing*. (R3 + R5 mean nothing dangerous happens
   either way.)
4. A user/admin write always sets `mode_source` to who wrote it (R4).

**Two surfaces, one endpoint** (`PUT /api/v1/machines/{editor}/{machine}/mode`,
guarded by `_require_selection_write`, which is already the "my own account, or
I am an admin" gate the tick uses):

* **Editor-facing**: their own machines are already listed on the scoped fleet
  page (`api_scope_editors_view`, `ui.py:186`) - the toggle goes there, per
  machine, with the auto-detected answer shown beside it.
* **Admin-facing**: the same control on Settings -> Machines / the packages
  machine list, for anyone's machine.

Copy spells out the consequence: no sync lanes, no plan, nothing in the queue.
Switching a machine to remote does not conjure it a local tree - it needs the
wizard - and the dialog says so.

### WP3 — the role at sign-in becomes per-machine (dashboard + companion)

* `LoginIn`/`VerifyIn` (`api.py:1237`) gain optional `machine` / `machine_id`
  (the two fields the report already sends).
* `/api/v1/verify` answers with the role recorded for THAT machine, falling
  back to what the companion says it is running as, and **never** to
  `is_admin`. Unknown machine -> `editor`, safe only because R5 exists.
* The report reply carries the role too, so a dashboard change reaches a
  machine without a re-sign-in (the `commands` channel, `app.py:4218`, is the
  precedent).
* Adopting a role mid-life: stopping lanes goes through the pause path (never
  mid-file); starting them goes through `on_signed_in`'s gate and R5's refusal.

`docs/SERVER.md`'s "Admin: Users section" and `api.py:1362`'s comment both
need rewriting: admin-ness no longer implies a base rig.

### WP4 — dashboard consumers go per-machine

* `db.base_machines(conn) -> set[(editor, machine)]`; `base_only_editors`
  survives as a thin derived helper for the two places that genuinely mean
  "this whole account".
* The tick 409 (`api.py:1562`) refuses **the target machine** when `?machine=`
  names a wired one. A person-level tick (no `?machine=`) fans out to that
  person's remote machines and reports how many it skipped - it must not
  refuse Billy's whole account because one of his three computers is wired.
* The copy-plan 409 (`api.py:2718`) refuses per source/target machine.
* The assignments grid marks wired **cells**, not whole columns
  (`assignments.py:96`, `admin_assignments.html`).
* The sidebar's `toggle_editor_base` becomes "every machine of this person is
  wired", which is what it already means, honestly named.

### WP5 — the wizard stops being overridden (onboarding)

`effective_install_role` inverts its precedence: the **radio wins** unless the
dashboard holds a role for THIS MACHINE (WP3), because the person-level role is
the thing that is wrong. Better still, seed the radio from WP1's detection so
the wizard already knows the answer before anyone picks. The asymmetry argument
in its docstring survives intact - "unknown lands on base, the non-destructive
branch" - and gains a second: an editor install on a wired machine unmaps the
live tree.

Copy: **done 2026-08-19** (installer 1.0.35). Page 2 asks how this computer
reaches the footage: "I'M A REMOTE EDITOR" / "I'M PHYSICALLY CONNECTED TO THE
SERVER/NAS", with an intro saying any number of machines can be on the NAS.
Stored values unchanged.

### WP6 — one producer per site (decision 4)

`machines.produces` (or a site-manifest hostname): proxy generation, b-roll
indexing and music indexing run only there. Every other wired machine keeps
its watcher, fixer, popup and loopback server. Deliberately NOT built: a
cross-machine `.partial` claim (an `O_EXCL` owner file with a heartbeat would
work, but SMB exclusive-create semantics need proving on the live share first).

One small correctness fix rides along: the ytdl download lease keys on
`(editor, machine)` rather than the editor name (`ytdl/web/ytdlweb/db.py:673`),
so one person's two machines cannot both believe they hold a job.

### WP7 — provisioning, docs, ledger

A wired machine needs an account to sign in and report, but no SFTP home, no
Syncthing folder share and no plan. `server/`'s account creation,
`docs/SERVER.md`, `docs/EDITOR_SETUP.md` and `docs/TENANCY.md` all still
describe one base rig; `docs/TENANCY.md` should also record that the
`billy_office`-style second account is no longer the way to give one person two
machines (`MULTI_MACHINE_PLAN.md` §7.2 declined to merge the existing split
accounts - they keep working, they are just not the pattern any more).

---

## 5. What Billy's three computers need that is not already built

Almost nothing structural - which is the point of having done
`MULTI_MACHINE_PLAN.md` first:

* **Own tree**: `local_root` is per machine in each `config.toml`. Nothing
  server-side overwrites it. Already true.
* **Own ticked projects**: `selections` is keyed `(editor, machine, slug)`
  since v24, `?machine=` on the selection fetch, the enforce cycle shares with
  one device. Already true.
* **Own role**: WP1-WP4. This is the missing piece.
* **One sign-in**: already true - `machines` is keyed per account per computer,
  and the identity token is per person by design.
* **The person-level tick must skip his wired desktop** rather than refuse his
  account: WP4.

---

## 6. Rollout

**Deploy the dashboard before the companions** - the B16 shape
(`MULTI_MACHINE_PLAN.md`). A companion reporting a per-machine role to a
dashboard that still derives it from the admin list is harmless; the reverse of
WP4 (person-level enforcement over per-machine data) is what unshared a fleet
once.

Order: **WP0** (companion, alone, low risk) -> **WP1** (companion detection,
reported but not yet acted on) -> **WP2+WP3+WP4** (one dashboard release, then
the companion that consumes it) -> **WP5** (installer) -> **WP6** -> **WP7**.

---

## 7. Risks

* **A machine that stops syncing silently.** Every change here can turn a
  syncing machine into a non-syncing one. R3 stops the server and the detector
  doing it by accident; WP2's list and chips are how a human notices.
* **Detection that is confidently wrong.** A wrong `wired` costs a machine its
  lanes; a wrong `remote` is refused by R5. `unknown` must be common and
  harmless rather than a rare fallback - measure it on the real fleet (base
  rig, ruskin's PC, the Mac) before WP2 acts on it.
* **`is_admin` removal from the login contract** may be depended on by
  something this pass did not find: grep `verified_role` and `role` across
  `onboarding/` and `installer/` before landing WP3.
* **Two producers is not only a `.partial` problem**: `server/publish_db.py`
  assumes one machine builds the search index. Decision 4 keeps that true.

---

## 8. Proposed ledger entries (not yet added)

* **CR-44** - the sign-in role is derived from the admin list, so an admin's
  REMOTE machine is told it is a base rig and silently syncs nothing.
* **CR-45** - a wired machine owned by a non-admin reports `mode="editor"` and
  sits in `[ QUEUED ]` for ever (CR-28's shape, one machine at a time; WP0
  fixes it).
* **CR-46** - the wizard's role radio loses to the person-level role, so
  picking "physically connected to the NAS" on a non-admin account runs the
  P:-teardown install on a machine whose `P:` is the live NAS share (B20 from
  the other direction; WP5 fixes it).

---

## 9. What I would ship first

WP0 alone: ten lines, no dashboard, and on its own it makes every machine
already carrying `mode = "base"` behave correctly everywhere - green tray icon,
out of the queue, out of the backlog. Then WP1, whose only job at first is to
report what it sees so we can check the detector against the real fleet before
anything acts on it.
