# Tailnet policy: who may reach what

CC Sync's perimeter is **Tailscale and nothing else** (owner decision
2026-10-07, GL-19 / COM-H15, CR-368): the dashboard, the NAS's sshd, SMB,
Syncthing and the optional Postgres project server are reached over the tailnet,
there is no LAN-only product, and nothing here is published to the internet
except the one client-share port described at the end.

That makes the **tailnet policy file part of the product's security**. Tailscale's
default policy lets every device reach every other device on every port, so an
intern's laptop, a guest's phone or a compromised editor machine can open the
dashboard's admin pages, speak to Postgres, and SSH to the NAS. This page is the
policy a site should apply instead. It is a template: copy it, change the group
members, and paste it into *Tailscale admin console > Access controls*.

## The shape

| Tag | Put it on | Why a tag |
|---|---|---|
| `tag:ccsync-server` | the NAS (the machine running the dashboard, Syncthing and SSH) | the target every editor machine talks to |
| `tag:ccsync-editor` | each editor's computer | may reach the server's four service ports and nothing else |
| `tag:ccsync-admin` | the base rig and the owner's own devices | may also reach the server's admin surfaces |

What an **editor** needs from the server, and therefore all it is granted:

| Port | Service | Used by |
|---|---|---|
| `tcp:8480` | the dashboard (`/api/v1/*`, `/broll`, `/music`, `/cards`) -- **or** `443` if you put `tailscale serve` in front, see below | the companion, the web UIs |
| `tcp:22` | the NAS's sshd, SFTP only for editors (`editor_shell = "sftp-only"`) | lanes A and B (rclone) |
| `tcp:22000`, `udp:22000` | Syncthing sync protocol | lane C |
| `tcp:445` | SMB, for the `P:` drive | Resolve's mapped drive |
| `tcp:5432` | the Resolve project server (Postgres) | Resolve, **only if** the bundled `project-server` profile is used |

What an editor is **not** granted: other editors' computers (no editor to editor
traffic at all), the NAS's web UI (`tcp:443`/`5001`), Syncthing's GUI (it listens on
loopback and is never needed over the network), and any admin port.

If your sshd or dashboard port is not the default, edit the numbers below to
match `[net] sftp_port` and the dashboard `--port`.

## The policy

HuJSON (comments and trailing commas are allowed in the admin console). Replace
the example addresses in `groups`.

```jsonc
{
  // Who may tag devices. The owner(s) only.
  "tagOwners": {
    "tag:ccsync-server": ["group:ccsync-owners"],
    "tag:ccsync-editor": ["group:ccsync-owners"],
    "tag:ccsync-admin":  ["group:ccsync-owners"],
  },

  "groups": {
    "group:ccsync-owners": ["owner@example.com"],
  },

  // NO catch-all `{"action": "accept", "src": ["*"], "dst": ["*:*"]}` rule:
  // Tailscale denies everything not granted below.
  "grants": [
    // Editors: the server's service ports, nothing else.
    {
      "src": ["tag:ccsync-editor"],
      "dst": ["tag:ccsync-server"],
      "ip":  ["tcp:8480", "tcp:22", "tcp:22000", "udp:22000", "tcp:445"],
    },

    // Admins: the same, plus the optional Postgres project server and the
    // NAS's own management UI (TrueNAS 443, DSM 5001) and TLS dashboard port.
    {
      "src": ["tag:ccsync-admin"],
      "dst": ["tag:ccsync-server"],
      "ip":  ["tcp:8480", "tcp:22", "tcp:22000", "udp:22000", "tcp:445",
              "tcp:5432", "tcp:443", "tcp:5001"],
    },

    // If you publish the dashboard through `tailscale serve` (https on 443 of
    // the NAS, as the studio does), editors need that one port instead of
    // 8480. Uncomment and drop tcp:8480 from the editor grant above.
    // {
    //   "src": ["tag:ccsync-editor"],
    //   "dst": ["tag:ccsync-server"],
    //   "ip":  ["tcp:443"],
    // },

    // The Resolve project server for editors, ONLY if you use the bundled
    // `project-server` profile (compose.yaml). A Postgres you run elsewhere
    // is granted to its own tag instead.
    // {
    //   "src": ["tag:ccsync-editor"],
    //   "dst": ["tag:ccsync-server"],
    //   "ip":  ["tcp:5432"],
    // },
  ],

  // These are checked when you save the file: a policy that breaks one of them
  // is refused, so an edit cannot quietly reopen the tailnet.
  "tests": [
    {
      "src": "tag:ccsync-editor",
      "accept": ["tag:ccsync-server:8480", "tag:ccsync-server:22",
                 "tag:ccsync-server:22000", "tag:ccsync-server:445"],
      "deny":   ["tag:ccsync-server:5432", "tag:ccsync-server:5001",
                 "tag:ccsync-server:8384", "tag:ccsync-editor:22",
                 "tag:ccsync-editor:3389"],
    },
    {
      "src": "tag:ccsync-admin",
      "accept": ["tag:ccsync-server:8480", "tag:ccsync-server:5432"],
      "deny":   ["tag:ccsync-editor:22"],
    },
  ],
}
```

## Applying it, and what will break

1. Tag the NAS `tag:ccsync-server`, **every editor computer**
   `tag:ccsync-editor`, and the base rig `tag:ccsync-admin` *before* saving the
   policy (*Machines > ... > Edit ACL tags*). A machine with no tag is reachable
   by nothing and reaches nothing.
2. Save the policy. The `tests` block above is evaluated first.
3. On an editor machine check each port (`Test-NetConnection <nas> -Port 8480`,
   or the dashboard's own grid showing the machine as reporting). The companion's
   tray line names a refused connection.
4. A tagged device **loses its user identity** in the policy: an editor who also
   needs admin access to the dashboard must use an admin-tagged machine, not a
   second login on the same computer.

Things this policy deliberately leaves out, and what to do instead:

- **Remote desktop / SSH between editors** is not granted. If your studio
  supports remote editors through the tailnet, add a narrow grant for the support
  person's tag, not a wildcard.
- **Syncthing's local discovery** (`udp:21027`) is LAN-only and is not needed over
  the tailnet; the NAS is a configured device, not a discovered one.
- **The Syncthing GUI** (8384) listens on loopback. Do not grant it.
- **A second NAS or an offsite replica** gets its own tag and its own grant.

## The dashboard is not the whole perimeter

- The dashboard binds only the NAS's LAN and tailnet addresses (`[net]
  bind_lan`, `bind_tailnet`), never `0.0.0.0`; the optional Postgres profile
  now binds the same two addresses and refuses to start without a generated
  password (`PG_PASSWORD`, never Resolve's well-known default).
- **LAN reach is not tailnet reach.** The grants above govern tailnet traffic. A
  site whose NAS is also on an office LAN still has the LAN as a path to the
  ports it binds there; keep guest Wi-Fi and IoT devices off that LAN's route to
  the NAS.
- **Client share links** (`/broll/share/<token>/`) are the one thing published
  past the tailnet, with Tailscale Funnel on a separate port (`docs/CLIENT_FOLDERS.md`).
  Funnel needs `"nodeAttrs": [{"target": ["tag:ccsync-server"], "attr": ["funnel"]}]`
  in this policy; grant it to the server tag only, and nothing else gets it.

```jsonc
  // add to the policy above ONLY if you publish client share links
  "nodeAttrs": [
    { "target": ["tag:ccsync-server"], "attr": ["funnel"] },
  ],
```

## Checking it

`tools/` does not call the Tailscale API. To verify the live policy, use the
admin console's *Preview rules* for one editor tag, and keep the `tests` block:
it is the regression test for this file. The suite in this repository
(`server/tests/test_secure_defaults.py`) parses the JSON block above and pins
that every port the product needs is granted to editors and that no wildcard
rule is present, so a change to the template that opens the tailnet fails CI.
