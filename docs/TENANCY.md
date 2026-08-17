# Tenancy — who can reach whose footage

Written 2026-08-17 for `docs/COMMERCIAL_READINESS.md` item 7 (finding H4).
Companion runbooks: `docs/SERVER.md` (TrueNAS), `docs/SERVER-SYNOLOGY.md`.

This document answers three separate questions that are easy to run together:

1. **Between organisations** — can two customers share one deployment?
2. **Between editors of one organisation** — can one editor read, write or
   delete another's project?
3. **Between an editor and the NAS itself** — what does an editor account
   actually let a person do on the box?

The answers are, in order: **no, and deliberately so**; **not any more, if you
turn it on**; and **transfer files, nothing else**.

---

## 1. Multi-org: one container per customer. Full stop.

There is no tenant table, no per-org namespace and no plan for one. Every
identity in this system is global:

- a project **slug** is the primary key of every dashboard row *and* the
  Syncthing folder ID — two customers with a `2026-brand-launch` project would
  collide in Syncthing's config, not just in a database;
- the shared asset libraries (`Assets/Luts`, `Assets/Stills`) are auto-shared
  with **every** editor by design — there is no tick to opt out of, which is
  the whole point of them;
- the fleet report token, the b-roll ingest token and the upgrade channel are
  one-per-deployment;
- the tree root is one dataset, mapped as one drive letter.

Retrofitting in-instance tenancy is a schema rewrite plus a Syncthing
namespace scheme plus a re-think of the asset libraries. It is not on the
roadmap, and pricing/packaging should not assume it.

**So: one customer = one dashboard container = one tree = one Syncthing
instance.** On a NAS that can host several (the compose stack is already
project-scoped), give each its own `[apps] root`, its own `site.toml`, its own
ports and its own tree dataset. They share hardware and nothing else.

---

## 2. Between editors: `[stack] project_acl`

### What it was (and still is by default)

`setup_tree.py` makes the whole tree `<owner>:<editors>` mode `2770` (setgid),
recursively. That gives every member of `editors`:

- read/write on every project, including ones they were never ticked onto;
- **delete** on every project, because deleting a directory needs write on the
  directory *above* it and the containers are group-writable too.

The dashboard's per-project ticks are a *sharing* mechanism (they decide which
Syncthing folders reach which machine), not an *access control* mechanism. An
editor who mounts `P:` over SMB sees everything.

For a single studio whose editors are colleagues, that is a reasonable and
deliberate posture, and it stays the default: `project_acl = "shared"`.

### What you can turn on

```toml
[stack]
project_acl = "per-project"
```

Then, for a project with slug `2026-ff4-nuclear`:

| Path | Owner:group | Mode | Effect |
|---|---|---|---|
| `.../Projects` | `broll:editors` | `3770` | editors may create projects; **only the owner may delete an entry** (sticky) |
| `.../Projects/2026` | `broll:editors` | `3770` | same |
| `.../Projects/2026/FF4` | `broll:editors` | `3770` | same |
| `.../Projects/2026/FF4/Nuclear` | `broll:proj-2026-ff4-nuclear` | `2770` | only members of that group get in at all |
| everything inside it | `broll:proj-2026-ff4-nuclear` | inherited setgid | a shared cut: members may still delete each other's files *within* the project |

Two halves, and both are load-bearing:

- **The group** stops an editor who was never ticked onto the project from
  reading or writing it over SMB.
- **The sticky bit on the containers** stops any editor from `rm -rf`-ing a
  project directory they cannot enter. Without it, per-project groups protect
  nothing — which is the mistake this design exists to avoid. Project
  directories are owned by the *service account*, so no editor is ever the
  owner of one.

The project is *not* sticky inside itself: two editors on one cut must be able
to fix up each other's renders, and making that a permissions error would
break the product rather than the threat.

### Group names

`proj-<slug>`, truncated deterministically to 32 characters with a 6-hex tail
when the slug is long (`common.project_group_name`). Derived, never stored:
the dashboard provisioner, `setup_tree.py` and a human reading `ls -l` all
arrive at the same name from the slug alone.

### Membership

```powershell
python server/setup_editor_account.py --name jsmith --ssh-pubkey-file jsmith.pub `
    --project 2026-ff4-nuclear --project 2026-cct-season-1
```

`--project` is repeatable and idempotent. Under `project_acl = "shared"` it
prints a note and does nothing, so a runbook can carry it either way.

The dashboard's Users section ticks the same projects; when `per-project` is
on, a tick should mean "in the group" as well as "share the Syncthing folder".
*(Operator TODO: the dashboard provisioner does not yet add group membership
itself — do it with `--project` from the base rig until it does.)*

### What this does NOT protect against

- **Lane C.** Syncthing shares are a separate trust path: a folder shared with
  a device reaches that device whatever the POSIX group says. Unshare on the
  dashboard as well as removing group membership.
- **Anything the service account can do.** See below.
- **An editor with a NAS shell.** Which is why they no longer have one — §3.

---

## 3. The service account, and why lane C survives all of this

Syncthing runs as **one uid** (`[stack] uid`/`gid`, the `broll`/service
account) and must be able to write into **every** folder in the fleet. So must
the dashboard container, which shares that uid.

Every scheme above keeps the service account as the **owner** of the whole
tree; only the *group* changes. That is what makes per-project mode safe to
turn on:

- Syncthing writes as the owner → unaffected by the group split;
- the dashboard's `/project-setup` create flow writes as the owner → unaffected;
- rclone lanes A/B authenticate as the **editor**, so they *are* affected —
  which is the point. An editor's lane A upload into a project they are not in
  will fail, exactly as their SMB access does.

Consequence to plan for: an editor removed from a project group keeps whatever
is already on their local disk. Removal is not retroactive.

---

## 4. Editor accounts: `[stack] editor_shell`

Until 2026-08-17 every editor got `/usr/bin/bash` on the NAS holding all of the
customer's footage. It bought exactly one feature — rclone's
`shell_type = unix`, which runs `md5sum` over SSH to verify a transfer.
Nothing else in this product ever executes a remote command as an editor
(verified across `companion/`, `installer/`, `onboarding/`, `write_marker.py`
and `accept_device.py`).

`editor_shell = "sftp-only"` (the default for a new install) means:

- the account's shell is `/usr/sbin/nologin` (`/sbin/nologin` on DSM, which is
  already its default);
- sshd carries a `Match Group editors` block with `ForceCommand internal-sftp`,
  `PasswordAuthentication no`, and no forwarding, tunnels or TTY. On TrueNAS it
  is installed into the SSH service's *auxiliary parameters*, because a file in
  `sshd_config.d` is erased the next time middleware regenerates the config.

**No `ChrootDirectory`**, deliberately. sshd requires every component of a
chroot to be root-owned and not group-writable, and the tree root is
`<owner>:editors 2770` by design — so the only chrootable point is the pool
mountpoint. Chrooting there would re-root every absolute path the site manifest
publishes (`DASH_SITE_REMOTE_ROOT`, every editor's `rclone.conf`, every
dashboard remote path): a fleet-wide breaking change for containment that §2
provides properly. If a future release wants chroot, it needs a re-rooted
manifest first.

**The manifest consequence is wired, not documented:** with `sftp-only`, the
deploy publishes `sftp_shell_type = "none"` whatever `[net] shell_type` says.
rclone then compares size + modtime instead of MD5. A manifest still promising
`unix` to a nologin account is a fleet whose every checksum call fails.

### Migrating an existing fleet

Order matters.

```powershell
# 1. Report only -- lists every editor and what would change.
python server/setup_editor_account.py --migrate-existing

# 2. Flip the site manifest first, so the two can never disagree for long.
#    site.toml:  [stack] editor_shell = "sftp-only"

# 3. Do it.
python server/setup_editor_account.py --migrate-existing --apply

# 4. Redeploy so the manifest says shell_type = none.
tools\ship.cmd -DashboardOnly
```

Between steps 3 and 4 (and until each editor's companion refreshes its config
from `GET /api/v1/site`) their `rclone.conf` still says `shell_type = unix`,
and lanes A/B log `failed to calculate hash` on every pass. Transfers still
happen; verification does not. Keep the window short, and tell editors what
they will see.

### Offboarding

Editor keys are generated **without a passphrase** (a tray app cannot prompt
for one on every rclone pass), so they must be revocable — and until
2026-08-17 nothing in this repo ever removed one:

```powershell
python server/setup_editor_account.py --name jsmith --revoke-key            # report
python server/setup_editor_account.py --name jsmith --revoke-key --apply --lock
```

That covers lanes A and B and (with `--lock`) SMB and the dashboard login.
**Lane C is separate**: unshare their Syncthing device on the dashboard too,
or their machine keeps receiving every folder it already has.

Rotation is the same command followed by a fresh key through the normal
onboarding path.

---

## 5. Summary of the switches

| Key | Default | Turns on |
|---|---|---|
| `[stack] editor_shell` | `"sftp-only"` | nologin + `ForceCommand internal-sftp`; forces `sftp_shell_type=none` in the manifest |
| `[stack] project_acl` | `"shared"` | `proj-<slug>` groups + sticky containers |
| `[syncthing] gui_bind` | unset (every interface) | publishes Syncthing's admin GUI on one address |
| `[nas] ssh_hostkey` | unset | pins the NAS host key (an unknown key is refused either way) |
| `TRUENAS_API_KEY` | unset | a scoped key replaces the admin password in the container |

Per-org isolation is not in that table on purpose. It is a deployment shape,
not a setting.
