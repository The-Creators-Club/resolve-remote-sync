# ccsync-sftp -- the chrooted internal-sftp sidecar

`ZERO_TOUCH_PLAN.md` section 3.1 ("SFTP as a sidecar is the decision that
removes the most") and section 5 (the cost/gain table for that decision).
This directory is `ccsync-sftp`'s entire source: `Dockerfile`, `sshd_config`,
`entrypoint.sh` and the two helper scripts `ccsync-keys.sh` /
`ccsync-users.sh`, built and pushed by `.github/workflows/image.yml` beside
the dashboard image.

## Why this exists at all

Today lane A/B (rclone) talk to the NAS host's own sshd, which is why the
product needs per-editor NAS accounts, home directories with
StrictModes-correct modes, an `editors` group, `chown -R`/setgid on the tree,
platform-specific ACLs, and an sshd `Match Group` block hand-appended to a
config file the platform's own middleware owns (`docs/TENANCY.md`'s "home
directory trap"). An sshd *inside the stack*, chrooted to a tree it mounts
itself, with keys served by the dashboard instead of a local
`authorized_keys` file, needs none of that: the container is root *inside
itself* and owns the mount, so tree/account ownership is its own business,
never the NAS host's.

## Chroot layout

```
/jail                    root:root, mode 755 -- REQUIRED by sshd's
                          ChrootDirectory StrictModes check: this directory
                          and every one above it (all the way to /) must be
                          owned by root and not writable by group or other,
                          or every login is refused with nothing more
                          specific than "Connection reset" on the editor's
                          end. entrypoint.sh re-asserts this on every boot.
/jail/tree                the PROJECT TREE bind mount -- compose's job
                          (`${CCSYNC_TREE}` on the customer's compose file),
                          not this image's. An empty /jail/tree at container
                          start just means the volume has not been attached
                          yet.
```

`ForceCommand internal-sftp -d /tree` (in `sshd_config`'s `Match Group
editors` block) is what lands every editor at `/tree` — the `-d` flag sets
`internal-sftp`'s starting directory *inside the chroot*, so from an
editor's own sftp client the path is simply `/…`, exactly as it is against
today's NAS-native sshd.

## uid model

Every editor's OS account inside this container shares **one uid:gid** —
`APP_UID:APP_GID`, the same pair the dashboard and (bundled) Syncthing
already run as. `ccsync-users.sh` creates each account with `useradd -o` (a
non-unique uid; BusyBox's own `adduser` refuses this, which is why the image
installs the `shadow` package instead of using Alpine's built-in tool) and
puts it in one shared `editors` group, matching `sshd_config`'s single
`Match Group editors` block. Anything an editor writes therefore lands owned
by the service account — exactly as Syncthing's and the dashboard's own
writes into the tree already do, and exactly what `ZERO_TOUCH_PLAN.md`
section 5 costs out: per-editor file ownership on the NAS host is gone, and
per-project *authorisation* moves into the dashboard's own selection rows
instead of POSIX permissions.

**Per-project bind views are a follow-up, not this file.** `ZERO_TOUCH_PLAN.md`
section 7 (spike S3) is where per-editor chroots with one bind mount per
ticked project get decided — it needs `SYS_ADMIN` inside this sidecar for
mount propagation from a compose service, which is a real increase in this
container's own privilege and deliberately not taken on here. Today every
editor who can authenticate sees the whole tree, which is the same posture
(`project_acl = "shared"`) every live site already runs
(`docs/TENANCY.md`).

## Identity: the dashboard, not this container

This sidecar holds no editor identity of its own:

- **Keys**: `AuthorizedKeysCommand /usr/local/bin/ccsync-keys %u` calls the
  dashboard's internal `GET /internal/sftp/keys/<username>` per connection
  attempt and prints back whatever `authorized_keys`-format lines it
  returns (empty for a user with no keys, and for an unknown one — see
  `ccsync-keys.sh`'s own comment for why those two cases are handled
  identically). Revoking an editor is one row in the dashboard's `users`
  table; nothing here needs to change.
- **Accounts**: `ccsync-users.sh` polls `GET /internal/sftp/users` (a list
  of `{username, uid}`) every 30s, plus once synchronously at boot and again
  on `SIGHUP` to the container, and creates any account it does not already
  have. It never DELETES an account — the dashboard revoking a key is
  already sufficient (no valid key, no login), and removing an OS account
  out from under a `chroot` mid-session is worse than leaving a stale,
  keyless one behind. Deleting stale accounts, if it is ever needed, is a
  deliberate follow-up, not silent cleanup.

Both endpoints are on the **compose network only** (this sidecar and the
dashboard share it — see `dashboard/deploy/compose.appliance.yaml`'s
`tailscale`/`dashboard` service comments) and require `Authorization: Bearer
<CCSYNC_INTERNAL_TOKEN>`. That contract is owned by the dashboard side
(`ZERO_TOUCH_PLAN.md` WP C); this sidecar only *consumes* it.

## Host keys persist, deliberately

`entrypoint.sh` generates `ssh_host_ed25519_key` / `ssh_host_rsa_key` into
`/etc/ssh/keys` **only if they are not already there**, and that directory
is a named volume on the customer's compose file
(`${CCSYNC_DATA}/sftp-hostkeys:/etc/ssh/keys`). **A regenerated host key
would make every editor's rclone refuse the NAS on its very next
connection** — rclone (like any SSH client) pins the host key it first saw,
and a changed one is exactly the "the NAS has been replaced or
compromised" signal SSH exists to give. Never delete that volume as part of
an upgrade or a "start fresh" troubleshooting step; if the host keys are
ever genuinely lost, every editor has to manually clear the stale entry
from their own `known_hosts` (or rclone's own host-key store) before they
can sync again.

## What this image deliberately does NOT do

- **No password authentication, ever** (`sshd_config`: `PasswordAuthentication
  no`, unconditionally — there is no "migration window" toggle the way the
  dashboard's own `smb` login flag has one).
- **No shell for any editor account** (`useradd -s /sbin/nologin`), and no
  path to one even if that were wrong: `ForceCommand internal-sftp` in the
  `Match Group editors` block overrides whatever the account's own shell
  says.
- **No port forwarding, no X11, no tunnelling** — `AllowTcpForwarding no`,
  `AllowAgentForwarding no`, `X11Forwarding no`, `PermitTunnel no`, both
  globally and inside the `Match` block, belt and braces.
- **Does not touch `ffmpeg`, `deno`, or anything from
  `dashboard/deploy/Dockerfile`.** This is a separate image with a separate,
  much smaller footprint (Alpine + OpenSSH + two shell scripts) — see that
  Dockerfile's own comments for why the dashboard's optional mounted tools
  stay mounts, never baked layers.
