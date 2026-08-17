# CC Sync on a Synology NAS (DSM 7.2+)

The Synology runbook. `docs/SERVER.md` stays the TrueNAS one; everything an
editor does is identical on both. Written 2026-08-17 from the bring-up that
produced it: `install_dashboard_app.py --nas-kind synology` against a live
DS423+ (DSM 7.2.1-69057 Update 6, Celeron J4125, Btrfs, 1 GbE), followed by
`setup_tree.py`, an editor SFTP write, `check_health.py` 7/7, and an editor
created and deleted through the deployed dashboard.

The measurements behind every design decision here are in
`docs/synology-spikes-2026-08-17.md` (eight spikes on the same unit). Where
this file says "measured", that is where.

---

## The three things that are different, and why

**1. Group write is an ACL, and `chmod` DELETES it.** A Synology shared folder
carries Windows-style ACEs. `SYNO.Core.Share.Permission set` installs an
inheritable `group:editors:allow:rwxpdDaARWc--:fd--` at the share root, and
everything created below inherits it -- with mode bits `0000` and owner
`root`, which look alarming and are irrelevant. Run one `chmod` on such a path
and its ACL is gone ("It's Linux mode"), inheritance with it; DSM's sftp
subsystem runs `internal-sftp -u 000`, so every file created afterwards lands
world-writable. The Synology backend therefore emits **no chmod and no chown
anywhere under the tree share**, ever, and `server/tests/test_synology_backend.py`
fails the build if one appears. The repair, if someone does it by hand:

```sh
sudo synoacltool -enforce-inherit "/volume1/<share>/<path>"
# and if that is not enough (a path with no ACL at all):
sudo synoacltool -add "/volume1/<share>/<path>" 'group:editors:allow:rwxpdDaARWc--:fd--'
```

`synoacltool -get <path>` is the oracle; `check_health.py` asserts it on every
run.

**2. `sftp_chunk_size` must be `64Ki`.** DSM 7.2.1 ships OpenSSH **8.2p1**,
which has no `limits@openssh.com` extension, so a client never learns the
server's 64 KiB read cap. rclone at the fleet's 255Ki asks for more, gets a
short reply, and treats it as EOF: **every lane-B download over ~514 MiB fails**
with `corrupted on transfer: sizes differ`. Measured, deterministic, truncating
at 539,000,832 bytes every time. `[net] sftp_chunk_size = "64Ki"` (and 16
concurrency) is not tuning, it is correctness. Downloads at 64Ki measured
112 MiB/s on 1 GbE -- line rate.

**3. Editors are `/sbin/nologin`, so rclone needs `shell_type = none`.** DSM
gives a new account no shell, which is exactly what a sync account should have
(SFTP is a subsystem, not a login shell) -- but rclone's `shell_type = unix`
then cannot run `md5sum` over SSH and every checksum call fails. `[net]
shell_type = "none"`.

---

## Requirements

| | |
|---|---|
| DSM | 7.2 or newer, x86_64 model with **Container Manager** (Plus/XS/RS) |
| Volume | **Btrfs** (snapshots; the Snapshot Replication package is only needed for SCHEDULING them) |
| Services | SSH on (admin-only by design), **SFTP service on** (the installer turns it on), User Home service on, SMB on |
| Account | a member of `administrators`, **2FA off** -- the scripts SSH in as it and call the DSM API with it |
| Network | ≥1 GbE; 2.5 GbE recommended. Tailscale package for remote editors |
| Free space | ~2 GB for the stack (images + the venv the container pip-installs at first boot). The music artefacts and the ytdl binaries are ~1.5 GB more and are **off by default** on Synology (`--with-host-binaries` opts in) |

The DSM API version gate is `SYNO.API.Auth` **version 7**. Anything older is
refused up front rather than half-provisioning: a v6 login yields a session
that reads fine and is denied on every mutation (error 105).

---

## site.toml for a Synology site

`server/tests/fixtures/site.synology.toml` is a complete, commented example.
The shape:

```toml
[nas]
kind = "synology"
host = "192.0.2.10"           # LAN or tailnet address
admin_user = "dsmadmin"       # administrators group, 2FA off
verify_ssl = "0"              # DSM's own cert is self-signed out of the box
# ssh_hostkey = "ssh-ed25519 AAAA..."   # ssh-keyscan -t ed25519 <nas>

[tree]
pool_root = "/volume1/CCSyncTest"       # /volume<N>/<share>
tree_name = "Creators_Club"
share_name = "CCSyncTest"
smb_unc = "\\\\192.0.2.10\\CCSyncTest\\Creators_Club"
homes_parent = "/var/services/homes"    # DSM's User Home service

[apps]
root = "/volume1/docker/ccsync"         # MUST match /volume<N>/<share>/ccsync

[net]
dashboard_url = "http://192.0.2.10:8480"
bind_lan = "127.0.0.1"                  # see "Publishing" below
sftp_port = "22"
sftp_chunk_size = "64Ki"                # NOT 255Ki -- see above
sftp_concurrency = 16
shell_type = "none"                     # editors are /sbin/nologin
rclone_remote = "ccsync_sftp"

[syncthing]
gui_url = "http://syncthing:8384"       # the compose service name

[stack]
owner = "ccsync-svc"                    # the service account, created for you
group = "editors"
project_server = "false"                # no Postgres in this stack (a profile)
```

`[stack] uid`/`gid` are deliberately absent: DSM allocates local users from
**1024** and local groups from **65536**, and the installer reads the live
values at every deploy. A hardcoded `3000:3001` is wrong on every DSM unit.

Secrets stay in the environment, and the password variable is **`SYNO_PW`**
(`TRUENAS_PW` is accepted with a note). Generate the rest per site -- never
reuse another site's:

```sh
export SYNO_PW='...'                 # the DSM admin password
export DASH_SESSION_SECRET=$(openssl rand -hex 24)
export DASH_REPORT_TOKEN=$(openssl rand -hex 24)
export SYNCTHING_API_KEY=$(openssl rand -hex 24)
export BROLL_INGEST_TOKEN=$(openssl rand -hex 24)   # or DASH_BROLL_ENABLED=0
```

---

## Install

```sh
python server/install_dashboard_app.py --site site.toml --nas-kind synology --dry-run
python server/install_dashboard_app.py --site site.toml --nas-kind synology
```

Read the dry-run first: it prints every remote command, with secrets masked.
What the real run does, in order:

1. **The shared folder** (`SYNO.Core.Share create` if missing) and its
   permission list (`SYNO.Core.Share.Permission set`, `editors` RW) -- which is
   what installs the inheritable ACE. Verified by read-back.
2. **The SFTP service**, enabled if it is off, and the `SYNO.SFTP` application
   privilege *verified*. (The privilege is granted by default; only an explicit
   deny matters. Both failure modes look identical to an editor: key auth
   succeeds, then "channel closed", with nothing in any log.)
3. **The tree skeleton** -- `<tree>/Projects`, the b-roll archive and the music
   library, `mkdir -p` only. Docker refuses to auto-create a bind-mount source,
   so an absent one fails the whole `up`.
4. **The `editors` group and the service account** (`synouser --add`, nologin),
   and their live uid/gid, which become `user: "<uid>:<gid>"` in the compose
   render. uid < 1024 or ≥ 170000 (package accounts) is refused.
5. **The host dirs** under `[apps] root`: code trees root-owned 0755 and
   mounted read-only; the container's own state (`data`, `venv`, `ytdl-data`,
   `syncthing-config`, ...) **0700 owned by the service uid**. Not TrueNAS's
   "group 3000, mode 770": on DSM every local account is in the only group a
   local account gets (`users`), so a group-writable /data would be
   world-writable in effect.
6. **The code**, by the same staged-verify-swap SFTP route as TrueNAS -- with
   one difference: staging is `<apps root>/staging`, not `/tmp`, because DSM's
   SFTP server chroots every account (the admin included) to its **share view**
   and cannot see `/tmp` at all.
7. **The stack**: `compose.yaml` (0644 root) and `.env` (**0600 root**, holding
   the five secrets) uploaded by SFTP -- never a heredoc, whose quoting eats a
   compose file -- then
   `docker compose --env-file … -p ccsync -f … --profile bundled-syncthing up -d`.

Syncthing is a service **in this stack** (`profiles: ["bundled-syncthing"]`),
not a package: we pin the version, we generate `STGUIAPIKEY`, and `/data` is
the tree by construction. `install_syncthing_app.py` is a no-op here and says
so.

Re-running is safe and idempotent. Compose-level changes (env, mounts, ports)
need `--recreate`, which is `compose down --remove-orphans` + `up -d`;
**volumes are never taken** -- `/data` holds the fleet database.

Then:

```sh
python server/setup_tree.py --site site.toml --nas-kind synology \
    --project-rel-path "2026/Demo/Port Test"
python server/check_health.py --site site.toml --nas-kind synology \
    --gui-url http://127.0.0.1:8384 --api-key "$SYNCTHING_API_KEY"
```

`check_health.py` runs from an admin workstation, and both the dashboard and
the Syncthing GUI are on the NAS's loopback, so tunnel them:

```sh
ssh -L 8384:127.0.0.1:8384 -L 8480:127.0.0.1:8480 <admin>@<nas>
```

Its Synology arm additionally asserts that the tree still has its ACL (not
"Linux mode") and lists `editors` through the DSM API.

---

## Publishing the dashboard (WP4)

The stack binds **127.0.0.1:8480** and nothing else. That is deliberate: DSM's
own nginx already owns `0.0.0.0:80/443/5000/5001`, so the dashboard cannot have
:443, and a NAS that gains an interface must not silently publish the fleet
dashboard on it. **Editors reach it over Tailscale, and only over Tailscale**
-- product decision 2026-08-17: no DSM reverse proxy, no DDNS/QuickConnect, no
LAN bind for customers. The dashboard's login is the only gate it has, and the
Syncthing GUI beside it is admin over every folder in the fleet; neither
belongs on the public internet.

**Tailscale Serve** publishes it with HTTPS and a valid certificate, tailnet
only:

```sh
sudo /var/packages/Tailscale/target/bin/tailscale serve --bg --yes --https=443 \
     http://127.0.0.1:8480
```

`--yes` matters: without it the command blocks on a prompt. **Serve is gated at
the TAILNET level**, not the node. On a tailnet that has not enabled HTTPS
certificates the command prints

```
Serve is not enabled on your tailnet.
To enable, visit: https://login.tailscale.com/f/serve?node=...
```

which is a one-time click in the Tailscale admin console (DNS -> "Enable
HTTPS"). Most freshly created tailnets are in this state, so treat the string as
an expected first-run condition, show the click, and re-run -- never as
success. VERIFIED 2026-08-17 on the DS423+ after that click: `serve status`
reports `https://nas.tail26290e.ts.net (tailnet only) |-- / proxy
http://127.0.0.1:8480`; from a tailnet peer, `curl` verifies the certificate
(`ssl_verify_result 0`), `/` 303s to the login page, `/api/v1/health` answers,
and the container has `DASH_COOKIE_SECURE=1`. It works with DSM's nginx
holding host :443 -- tailscaled answers the tailnet address itself.

Then set `[net] dashboard_url = "https://<nas>.<tailnet>.ts.net"` and
`--recreate` (that is what pins `DASH_COOKIE_SECURE=1`; a plain redeploy only
swaps code). Serve config survives tailscaled and NAS restarts; `tailscale
serve --https=443 off` removes it.

For the record, so nobody re-spends the day: DSM's reverse proxy
(`SYNO.Core.AppPortal.ReverseProxy` v1) was probed -- `list` works, `create`
answers error 4151 for every payload variant tried -- and a raw LAN bind
(`[net] bind_lan`) works mechanically. Both are deliberately unsupported for
customers; `bind_lan` remains only for a lab.

The DSM firewall is not touched by any of this. If it is on, the ports editors
need are 22 (SFTP), 445 (SMB), 22000/tcp+udp and 21027/udp (Syncthing), plus
whatever publishes the dashboard.

---

## Editors

Same flow as TrueNAS (`docs/SERVER.md`), with DSM's shapes:

```sh
python server/setup_editor_account.py --site site.toml --nas-kind synology \
    --name jsmith --ssh-pubkey-file jsmith.pub --tailnet-host <nas>
```

or from the dashboard's `/admin/users`, which does the same thing through the
runtime backend (`dashboard/src/ccsync_dashboard/nas/synology.py`) -- verified
end to end on the device: the deployed container created a DSM account, wrote
its `authorized_keys` over its own SSH channel, and that key then worked for
SFTP.

What DSM does differently:

- the account is created with **no shell** (`/sbin/nologin`) and still gets
  SFTP -- it is a subsystem, not a login shell;
- there is **no `sshpubkey` field**: `~/.ssh/authorized_keys` is written over
  SSH, `.ssh` 0700 and the file 0600, owned by the editor. **The home itself is
  never touched** -- DSM ships it 0711, which already satisfies sshd's
  StrictModes, and a chmod would strip its ACL;
- there is **no `password_disabled` flag**. The password exists for SMB and the
  dashboard login; SSH is key-only regardless. The script says so instead of
  warning about it;
- **sshd logs NOTHING for a StrictModes refusal** at DSM's default LogLevel
  (there is no journal; `/var/log/auth.log` stays silent). The editor's only
  symptom is "Authentication failed", so
  `setup_editor_account.py`'s verification step is the diagnosis.

Every editor's rclone remote needs `port`, `shell_type = none` and the 64Ki
chunk size; the dashboard serves all of them from `GET /api/v1/site`, which the
installers and the companion read.

---

## Snapshots

Taking, listing, restoring and deleting share snapshots is **base DSM** -- the
Snapshot Replication package is only needed to SCHEDULE them (`set_schedule`
answers 403 without it) and for the UI. `backend.snapshot()` calls
`SYNO.Core.Share.Snapshot create`; snapshots land as an ordinary read-only
Btrfs subvolume tree at `/volume1/@sharesnap/<share>/<GMT+NN-YYYY.MM.DD-HH.MM.SS>/`,
so restoring one file is a plain `cp` -- but note `cp -a` does **not** carry
the Synology ACL or the owner (the restored file re-inherits from its
destination and is owned by root). Use `synoacltool -copy SRC DST` where owner
fidelity matters.

A snapshot made outside the API (`btrfs subvolume snapshot`, `synobtrfssnap`)
is invisible to DSM's own list, which keys off `@<share>.meta`.

---

## Known gaps (validated, and honest about it)

- **Reboot survival is untested.** The stack uses `restart: unless-stopped`,
  the same mechanism every other container on the tested box relies on, but
  that box is a production NAS with 77 days of uptime and was not rebooted.
  A CLI-created stack also does **not** register as a Container Manager
  *project* (`SYNO.Docker.Project list` does not see it), only as containers.
  Reboot a test unit before promising this.
- **uid/gid stability across a DSM update** is untested for the same reason.
  The risk shape is a new *package* claiming a uid (packages live at
  170000+), not an update renumbering local accounts.
- **`tailscale serve`** VERIFIED 2026-08-17 (see Access) -- after the tenant's
  one-time "Enable HTTPS" click.
- **Throughput** on the tested unit: SFTP up 90 MiB/s, SMB up 102-104 MiB/s,
  both down ~112 MiB/s -- i.e. 1 GbE line rate, and SFTP is ~12 % *slower* than
  SMB on upload. Lanes A/B do not need to change, but on a ≥2.5 GbE unit the
  per-stream single-core cost of SSH (~0.55 of a J4125 core for 90 MiB/s) is
  what will bite first.
