# Zero-touch spikes S5 / S1 / S2 (+S3) — run on the DS423+, 2026-08-17

The pre-implementation spikes from `docs/ZERO_TOUCH_PLAN.md` §7, run against
the same live Synology the port spikes used (`docs/synology-spikes-2026-08-17.md`
has the box's full description). Everything below is measured, not inferred;
where something could not be measured it says so and why. **Read this before
writing WP A/B/C code** — one of the plan's assumptions (the sidecar prints a
login link and the wizard shows it) does not survive contact with the stock
image's entrypoint, and one bonus question (per-project bind views) came back
*yes, with one extra compose line*.

| | |
|---|---|
| Device | DS423+ (`synology_geminilake_423+`), DSM 7.2.1, kernel `4.4.302+`, Btrfs `/volume1`, 59 GB free before and after |
| Docker | `Docker version 24.0.2, build 610b8d0`; `Docker Compose version v2.20.1-6047-g6817716`; storage driver `btrfs`, cgroup v1, `SecurityOptions=[name=apparmor]` |
| Access | LAN `192.168.0.104:22`, `Cablewrap` (administrators), password on stdin to `sudo -S`, every command wrapped in `sh -c 'export PATH=/usr/syno/bin:/usr/syno/sbin:/usr/local/bin:...; <cmd>'` |
| Base rig | Windows 11, `rclone v1.74.4` (winget), `OpenSSH_for_Windows_9.5p2`, 1 GbE to the NAS |
| Time | ~20 minutes wall on the device, 22:26–22:43 local (containers log UTC, 14:26–14:43) |
| Live things not touched | the `ccsync` stack (`ccsync-dashboard-1`, `ccsync-syncthing-1`, `ccsync-bgutil-1`, "Up 6 hours" throughout), every other stack, shares, users, firewall. Note that **8480/8384 are no longer free on this box** — they belong to that stack now (`127.0.0.1:8480`, `127.0.0.1:8384`, `0.0.0.0:22000`); the spike needed none of them |

Everything created was prefixed `ccsync-spike`, and the *Removed* table at the
bottom is exhaustive; nothing was left on the device.

Two things learned about the box itself before any spike ran, both relevant
to WP D's "connect to your NAS" step: DSM's own SFTP is chrooted to the shares
(paramiko `put` to `/tmp` fails `No such file`; small files were shipped
`echo <base64> | base64 -d > path` through the sudo shell instead), and the
users the earlier session created (`ccsync_a`/`ccsync_b`) are gone while
`ccsync-svc` (uid **1043**, gid 100) and group `editors` (gid **65536**, no
members) exist. `1043:65536` is therefore the uid:gid used everywhere below —
it is the shape the current port renders into `user:`.

---

## S5 — compose features under Container Manager's compose

### What was run

`/volume1/docker/ccsync-spike/compose.yaml`, brought up as root with
`docker compose -p ccsync-spike -f compose.yaml up -d` (final shape, after the
revisions described in S1/S2):

```yaml
services:
  tailscale:                              # containerboot, stock image
    image: tailscale/tailscale:latest
    container_name: ccsync-spike-tailscale
    hostname: ccsync-spike
    environment:
      TS_STATE_DIR: /var/lib/tailscale
      TS_USERSPACE: "true"
      TS_HOSTNAME: ccsync-spike
      TS_SOCKET: /var/run/tailscale/tailscaled.sock
      TS_SERVE_CONFIG: /config/serve.json
    volumes:
      - ./ts-state:/var/lib/tailscale
      - ./ts-config:/config:ro           # a DIRECTORY -- the docs say a single-file bind is not watched
      - ts-sock:/var/run/tailscale
    restart: unless-stopped
  web:                                    # stands in for the dashboard, in tailscale's netns
    image: python:3.12-slim
    container_name: ccsync-spike-web
    network_mode: service:tailscale
    command: ["sh", "-c", "mkdir -p /www && echo ccsync-spike-web-ok > /www/index.html && cd /www && exec python -m http.server 8480"]
    depends_on: [tailscale]
  tsd:                                    # variant B: tailscaled directly, no containerboot
    image: tailscale/tailscale:latest
    container_name: ccsync-spike-tsd
    hostname: ccsync-spike-tsd
    entrypoint: ["tailscaled", "--socket=/var/run/tailscale/tailscaled.sock", "--statedir=/var/lib/tailscale", "--tun=userspace-networking"]
    volumes:
      - ./tsd-state:/var/lib/tailscale
      - tsd-sock:/var/run/tailscale
    restart: unless-stopped
  lapi:                                   # the "dashboard" reading LocalAPI over the shared socket
    image: python:3.12-slim
    container_name: ccsync-spike-lapi
    command: ["sleep", "infinity"]
    volumes:
      - ts-sock:/var/run/tailscale
      - tsd-sock:/var/run/tsd
      - ./lapi.py:/lapi.py:ro
    depends_on: [tailscale, tsd]
  writer:                                 # user: + bind mount under the share
    image: alpine:3.19
    container_name: ccsync-spike-writer
    user: "1043:65536"
    command: ["sleep", "infinity"]
    volumes:
      - /volume1/CCSyncTest/spike-tree:/tree
  sftp:                                   # S2, see below
    image: ccsync-spike-sftp:local
    container_name: ccsync-spike-sftp
    ports: ["2222:22"]
    cap_add: [SYS_ADMIN]
    security_opt: ["apparmor=unconfined"]
    volumes:
      - /volume1/CCSyncTest/spike-tree:/jail/tree
      - ./sftp/keys:/keys:ro
    restart: unless-stopped
volumes:
  ts-sock:
  tsd-sock:
```

`docker compose ... config --quiet` → `CONFIG-OK`; `up -d` pulled and started
everything with no DSM-specific refusal of any kind. Two things bit that are
*not* DSM's doing: `alpine:3.19`'s busybox has **no `httpd` applet**
(`sh: exec: line 0: httpd: not found`, exit 127 — hence `python:3.12-slim`,
which was already on the box), and `docker compose ls` does not list a
CLI-created project in Container Manager's *Project* UI (already known from
the port spikes).

### (a) `network_mode: service:<other>` — works

```
$ docker inspect -f '{{.Name}} net={{.HostConfig.NetworkMode}} capadd={{.HostConfig.CapAdd}} devices={{.HostConfig.Devices}} priv={{.HostConfig.Privileged}}' ...
/ccsync-spike-web net=container:b106d19cf4a7... capadd=[] devices=[] priv=false
/ccsync-spike-tailscale net=ccsync-spike_default capadd=[] devices=[] priv=false

$ docker exec ccsync-spike-tailscale sh -c 'ip -o addr | cut -c1-80; wget -qO- http://127.0.0.1:8480/'
1: lo    inet 127.0.0.1/8 scope host lo
1013: eth0    inet 192.168.176.4/20 brd 192.168.191.255 scope global eth0
ccsync-spike-web-ok

$ docker exec ccsync-spike-web cat /sys/class/net/eth0/address   -> 02:42:c0:a8:b0:04
$ docker exec ccsync-spike-tailscale cat /sys/class/net/eth0/address -> 02:42:c0:a8:b0:04   (same interface)
```

The web service's `:8480` is reachable on `127.0.0.1` inside the tailscale
container and the two share one `eth0`, which is exactly what Serve's
`http://127.0.0.1:8480` proxy target and userspace-netstack inbound delivery
need.

**But — the dependent keeps an orphaned netns when the owner restarts.**
Measured while the containerboot variant was crash-looping (see S1):

```
$ docker inspect -f '{{.State.Status}} restarts={{.RestartCount}} pid={{.State.Pid}}' ccsync-spike-tailscale ccsync-spike-web
running restarts=3 pid=444
running restarts=0 pid=29682
$ ls -l /proc/444/ns/net /proc/29682/ns/net
/proc/29682/ns/net -> net:[4026533777]        # web: the ORIGINAL netns
/proc/444/ns/net   -> net:[4026533998]        # tailscale: a NEW one
$ docker exec ccsync-spike-tailscale wget -qO- -T 3 http://127.0.0.1:8480/
wget: can't connect to remote host (127.0.0.1): Connection refused
$ docker exec ccsync-spike-web cat /sys/class/net/eth0/address
cat: /sys/class/net/eth0/address: No such file or directory   # web has NO eth0 any more, its own 127.0.0.1:8480 still answers
```

So after any restart of the netns owner, every `network_mode: service:` sibling
is unreachable from the tailnet until *it* is restarted too, and compose does
not do that for a runtime crash (only `depends_on: {tailscale: {restart: true}}`
on the next `compose up`). This is a real constraint on §3.1's shape — see the
verdict.

### (b) a named volume carries a unix socket between services — works

`ts-sock` (named volume, mountpoint `/volume1/@docker/volumes/ccsync-spike_ts-sock/_data`)
holds `srw-rw-rw- root root tailscaled.sock`; the `lapi` service (a *different*
image, python) opened it with stdlib `socket.AF_UNIX` and got HTTP 200 from
`GET /localapi/v0/status` (full transcript in S1). The `tsd-sock` volume did
the same for the second daemon.

### (c) `user: 1043:65536` + bind mount under `/volume1/CCSyncTest` — writes land

```
$ mkdir -p /volume1/CCSyncTest/spike-tree && chown 1043:65536 ... && chmod 2770 ...
drwxrws--- 1 1043 65536 0 Aug 17 22:26 /volume1/CCSyncTest/spike-tree
$ synoacltool -get /volume1/CCSyncTest/spike-tree
(synoacltool.c, 596)It's Linux mode              # chmod stripped the share ACL, exactly as spike 1 said it would

$ docker exec ccsync-spike-writer sh -c 'id; echo hello-from-writer > /tree/writer.txt && mkdir -p /tree/writer-dir && ls -ln /tree'
uid=1043 gid=65536 groups=65536
drwxr-sr-x    1 1043     65536            0 Aug 17 14:28 writer-dir
-rw-r--r--    1 1043     65536           18 Aug 17 14:28 writer.txt
$ ls -ln /volume1/CCSyncTest/spike-tree                            # host view, identical
drwxr-sr-x 1 1043 65536  0 Aug 17 22:28 writer-dir
-rw-r--r-- 1 1043 65536 18 Aug 17 22:28 writer.txt
```

### VERDICT (S5)

**Container Manager's compose accepts every construct the plan uses**:
`network_mode: service:`, named-volume sockets, `user:` + share bind mounts,
`cap_add`, `security_opt`, `entrypoint:` overrides, `restart:` policies. No
DSM refusal was seen anywhere. The one finding that changes the design is not a
refusal but a Docker semantic: **the netns-sharing siblings die with the
sidecar's netns and do not come back on their own.**

---

## S1 (auth-free half) — the Tailscale sidecar

Image resolved: `tailscale/tailscale:latest` =
`tailscale/tailscale@sha256:321ce041508c19079b57a28b6666c8d81ab0b08accc0a2585b3ab663d557ac24`,
created `2026-07-31T03:18:15Z`, reporting **`v1.102.2-teb67e5dcb`, Go 1.26.5**.
Pin that digest (or `v1.102.2`) in WP B.

`ts-config/serve.json` as mounted (the `ipn.ServeConfig` shape containerboot
substitutes `${TS_CERT_DOMAIN}` into after login; the KB pages fetched for this
spike — `kb/1282/docker`, `docs/features/containers/docker/docker-params` — no
longer print an example, they only say "the shape `tailscale serve status --json`
prints" and "mount a directory, not a file"):

```json
{
  "TCP": {"443": {"HTTPS": true}},
  "Web": {"${TS_CERT_DOMAIN}:443": {"Handlers": {"/": {"Proxy": "http://127.0.0.1:8480"}}}}
}
```

### (a) userspace mode starts with no tun and no NET_ADMIN — yes

```
$ docker exec ccsync-spike-tailscale sh -c 'ls -l /dev/net/tun; grep -E "^Cap(Eff|Bnd)" /proc/1/status'
ls: /dev/net/tun: No such file or directory
CapEff: 00000000a80425fb            # docker's default set, no NET_ADMIN
CapBnd: 00000000a80425fb
$ docker logs ccsync-spike-tailscale | head
boot: 2026/08/17 14:27:09 Starting tailscaled
boot: 2026/08/17 14:27:09 Waiting for tailscaled socket at /var/run/tailscale/tailscaled.sock
TPM: error opening: stat /dev/tpmrm0: no such file or directory
2026/08/17 14:27:10 Program starting: v1.102.2-teb67e5dcb, Go 1.26.5: []string{"tailscaled", "--socket=/var/run/tailscale/tailscaled.sock", "--statedir=/var/lib/tailscale", "--tun=userspace-networking"}
2026/08/17 14:27:10 wgengine.NewUserspaceEngine(tun "userspace-networking") ...
2026/08/17 14:27:10 magicsock: [warning] failed to force-set UDP read buffer size to 7340032: operation not permitted; using kernel default values (impacts throughput only)
2026/08/17 14:27:10 Engine created.
2026/08/17 14:27:10 Switching ipn state NoState -> NeedsLogin (WantRunning=false, nm=false)
boot: 2026/08/17 14:27:10 Running 'tailscale up'
```

The UDP-buffer warning is the only capability complaint; it is throughput-only
(and is the reason kernel mode stays an option, below).

### (b) the login URL in `docker logs` — yes, but containerboot then kills the daemon

```
2026/08/17 14:27:11 localapi: [POST] /localapi/v0/login-interactive
2026/08/17 14:27:12 control: Generating a new nodekey.
2026/08/17 14:27:17 control: RegisterReq: got response; nodeKeyExpired=false, machineAuthorized=false; authURL=true
2026/08/17 14:27:17 control: AuthURL is https://login.tailscale.com/a/<code>

To authenticate, visit:

	https://login.tailscale.com/a/<code>

boot: 2026/08/17 14:28:09 Sending SIGTERM to tailscaled
boot: 2026/08/17 14:28:09 failed to auth tailscale: failed to auth tailscale: tailscale up failed: context deadline exceeded
2026/08/17 14:28:09 tailscaled got signal terminated; shutting down
```

URL shape: `https://login.tailscale.com/a/<12 lowercase hex chars>` (masked
here; the codes were never used and the node was never signed into any
tailnet). **Sixty seconds after `tailscale up` starts, containerboot gives up,
SIGTERMs tailscaled and exits.** With `restart: "no"` the container was simply
dead; with `restart: unless-stopped` it crash-loops at ~66 s per cycle and every
cycle **generates a new node key and a new AuthURL** (`regen=true` in the
log; four distinct codes over five minutes):

```
$ docker logs ccsync-spike-tailscale | grep -E 'boot:|AuthURL is'
boot: 14:30:44 Running 'tailscale up'      14:30:49 AuthURL is https://login.tailscale.com/a/1cc7…
boot: 14:31:44 Sending SIGTERM to tailscaled  / failed to auth tailscale: tailscale up failed: context deadline exceeded
boot: 14:31:50 Running 'tailscale up'      14:31:57 AuthURL is https://login.tailscale.com/a/ac05…
boot: 14:32:50 Sending SIGTERM …
boot: 14:32:57 Running 'tailscale up'      14:32:59 AuthURL is https://login.tailscale.com/a/117d…
boot: 14:33:57 Sending SIGTERM …
boot: 14:34:05 Running 'tailscale up'      14:34:08 AuthURL is https://login.tailscale.com/a/165b…
$ docker inspect -f '{{.State.Status}} restarts={{.RestartCount}}' ccsync-spike-tailscale
restarting restarts=3
```

For roughly one in every eleven seconds the socket does not exist at all
(`ConnectionRefusedError` / `AuthURL: ""` right after a restart), and the URL
the wizard would have shown is stale a minute later. **The plan's "the wizard
shows the link tailscaled prints" cannot be built on containerboot without an
auth key.** It *can* be built on tailscaled itself — variant B, next.

### (c) LocalAPI over the shared socket, from a second service — yes (both variants)

The `lapi` service is `python:3.12-slim` with a 60-line stdlib client (a
`http.client.HTTPConnection` whose `connect()` opens `AF_UNIX`), i.e. what the
dashboard image can do with no new dependency. No `Sec-Tailscale` or other
header was needed for GET, PATCH or POST over the unix socket.

Containerboot variant, during its 60 s window:

```
$ docker exec ccsync-spike-lapi python /lapi.py raw GET /localapi/v0/status
HTTP 200 {'Content-Type': 'application/json'}
{
	"Version": "1.102.2-teb67e5dcb",
	"TUN": false,
	"BackendState": "NeedsLogin",
	"AuthURL": "https://login.tailscale.com/a/<code>",
	"TailscaleIPs": null,
	"Self": { "ID": "", "NodeID": 0, "PublicKey": "nodekey:0000…", "HostName": "ccsync-spike", "DNSName": "", "OS": "lin…
```

Variant B (`entrypoint: tailscaled …`, no containerboot), driven entirely from
python — this is the sequence WP B should implement:

```
$ … python /lapi.py status                     # fresh state dir
BackendState NeedsLogin, AuthURL "", Health ["Tailscale is stopped."], Self.HostName ccsync-spike-tsd
$ … python /lapi.py prefs                      # GET /localapi/v0/prefs
{'WantRunning': False, 'LoggedOut': True, 'Hostname': '', 'ControlURL': '', 'CorpDNS': True, 'RouteAll': False, 'NetfilterMode': 2}
$ … python /lapi.py edit-prefs                 # PATCH /localapi/v0/prefs  {"WantRunning":true,"WantRunningSet":true,"Hostname":"ccsync-spike-tsd","HostnameSet":true,"CorpDNS":true,"CorpDNSSet":true}
HTTP 200 { "WantRunning": true, "LoggedOut": true, "Hostname": "ccsync-spike-tsd", … }
$ … python /lapi.py login                      # POST /localapi/v0/login-interactive
HTTP 204
   (8 s later)
$ … python /lapi.py status
BackendState NeedsLogin, AuthURL "https://login.tailscale.com/a/<code>", Health ["You are logged out. The last login error was: fetch control key: … context canceled"]
$ docker exec ccsync-spike-tsd tailscale --socket=/var/run/tailscale/tailscaled.sock status
Logged out.
Log in at: https://login.tailscale.com/a/<code>
```

That daemon then **sat in `NeedsLogin` without a single restart for the
remaining twelve minutes of the spike** (`Up 6 minutes` at 14:37, still up at
teardown 14:43, `RestartCount` 0) — which is the behaviour the wizard needs
(poll `GET /status` until `BackendState == "Running"`, then read
`Self.DNSName`). Whether tailscaled itself rotates the AuthURL over a longer
wait was not re-checked; the wizard should simply re-read `AuthURL` on every
poll rather than cache it. The transient "context canceled" health
line is the first control-key fetch racing the prefs edit; the second attempt
two seconds later succeeded (`control server key from
https://controlplane.tailscale.com` in the log).

Serve config over LocalAPI, **before** login:

```
$ … python /lapi.py serve-get                  # GET /localapi/v0/serve-config
HTTP 200 {'Etag': '74234e98…'} null
$ … python /lapi.py serve-set ccsync-spike-tsd.example.ts.net    # POST /localapi/v0/serve-config, If-Match: <etag>
HTTP 500 {"error":"updating config: netMap is nil"}
$ docker exec ccsync-spike-tsd tailscale … serve status
No serve config
```

So `serve-config` is rejected until the node has a netmap (is logged in), and
containerboot's `TS_SERVE_CONFIG` was likewise never applied (no `serve` line
in any log; the substitution needs `TS_CERT_DOMAIN`). **In variant B the
dashboard POSTs the serve config itself once `BackendState=Running`, with
`Self.DNSName` (minus the trailing dot) in the `Web` key.** Whether Serve then
actually terminates TLS on `:443` and proxies to `127.0.0.1:8480` **was not
measured — it needs a tailnet login**, which this spike was forbidden to do.
Same for "inbound tailnet-IP:22000 reaches the netns sibling" and userspace vs
kernel throughput: all three need one throwaway tailnet + one auth key, one
afternoon, and belong to the *first hour of WP B*, not to this spike.

### Kernel mode on this box — possible

Host: `crw-rw-rw- 1 root root 10, 200 /dev/net/tun`, `tun` module loaded.

```
$ docker run -d --name ccsync-spike-tskern --cap-add NET_ADMIN --device /dev/net/tun --entrypoint tailscaled tailscale/tailscale:latest --socket=/tmp/ts.sock --statedir=/tmp/ts --tun=tailscale0
$ docker exec ccsync-spike-tskern ip -o link
3: tailscale0: <POINTOPOINT,MULTICAST,NOARP,UP,LOWER_UP> mtu 1280 …
  log: router: default choosing iptables ; router: disabling tunneled IPv6 due to system IPv6 config: disable_ipv6 is set
$ (same without --device)
  log: wgengine.NewUserspaceEngine(tun "tailscale0") error: tstun.New("tailscale0"): CreateTUN("tailscale0") failed; /dev/net/tun does not exist
```

`devices: ["/dev/net/tun:/dev/net/tun"]` + `cap_add: [NET_ADMIN]` is enough on
DSM 7.2 / kernel 4.4.302+; iptables mode is picked automatically. Keep it as
the commented-out "throughput" block in the customer compose the plan already
describes.

### VERDICT (S1)

- **WP B must not use containerboot's implicit `tailscale up`.** Run
  `tailscaled` as the service command (stock image, `entrypoint:` override, no
  build of our own) and let the dashboard drive `PATCH /prefs` →
  `POST /login-interactive` → poll `GET /status` (`AuthURL`, then
  `BackendState=Running`, `Self.DNSName`, `TailscaleIPs`) → `POST /serve-config`.
  Every one of those calls is proven above from python over the shared socket.
  The alternative — hand containerboot a `TS_AUTHKEY` — makes the customer mint
  a key in the admin console, which is precisely the step the plan exists to
  remove.
- **State dir on `/data`** is confirmed to be what keeps the machine key: with a
  fresh dir every start regenerated one.
- **Design risk to resolve first in WP B**: siblings in `network_mode:
  service:tailscale` are orphaned by a sidecar restart (S5). Options, in order
  of preference: (1) don't share netns — keep sftp/syncthing on the compose
  network and have Serve **TCP-forward** `:22 → tcp://sftp:22` and
  `:22000 → tcp://syncthing:22000` (LocalAPI `TCPForward` takes any host:port —
  the k8s operator relies on it — but this needs the login to test); (2) keep
  the shared netns and make the tailscale service the most boring container
  in the stack (variant B is: it never exits on its own) plus
  `depends_on: {tailscale: {condition: service_started, restart: true}}` so
  every *deliberate* recreate carries the siblings along; a runtime crash of
  tailscaled would still need the customer's "Restart project" click.
- Kernel mode: available on DSM with two compose lines; leave it opt-in.

---

## S2 — the SFTP sidecar

### The image (built on the NAS, 9 MiB of packages, ~20 s)

`/volume1/docker/ccsync-spike/sftp/Dockerfile`:

```Dockerfile
FROM alpine:3.19
RUN apk add --no-cache openssh-server openssh-sftp-server \
 && ssh-keygen -A \
 && mkdir -p /jail /jail2 /run/sshd \
 && chmod 755 /jail /jail2 \
 && addgroup -g 65536 editors \
 && printf 'editor1:x:1043:65536:CC Sync editor:/:/sbin/nologin\neditor2:x:1043:65536:CC Sync editor:/:/sbin/nologin\n' >> /etc/passwd \
 && printf 'editor1:*:19000:0:99999:7:::\neditor2:*:19000:0:99999:7:::\n' >> /etc/shadow
COPY sshd_config /etc/ssh/sshd_config
COPY keys.sh /usr/local/bin/keys.sh
RUN chmod 755 /usr/local/bin/keys.sh && chown root:root /usr/local/bin/keys.sh /etc/ssh/sshd_config && chmod 644 /etc/ssh/sshd_config
EXPOSE 22
CMD ["/usr/sbin/sshd", "-D", "-e"]
```

Two users, **same uid:gid `1043:65536`**, written straight into
`/etc/passwd`/`/etc/shadow` because busybox `adduser -u` refuses a duplicate
uid. Shadow field `*` (not `!`): sshd treats `!` as *locked* and refuses the
account before it ever consults the key — the spike hit exactly that message
for the `nobody` probe below.

`sshd_config`:

```
Port 22
HostKey /etc/ssh/ssh_host_ed25519_key
LogLevel VERBOSE
PermitRootLogin no
PasswordAuthentication no
KbdInteractiveAuthentication no
PubkeyAuthentication yes
AuthorizedKeysFile none
AuthorizedKeysCommand /usr/local/bin/keys.sh %u
AuthorizedKeysCommandUser nobody
Subsystem sftp internal-sftp
Match User editor2
    ChrootDirectory /jail2
    ForceCommand internal-sftp -u 002
    AllowTcpForwarding no
    X11Forwarding no
    AllowAgentForwarding no
    PermitTunnel no
Match User editor*
    ChrootDirectory /jail
    ForceCommand internal-sftp -u 002
    AllowTcpForwarding no
    X11Forwarding no
    AllowAgentForwarding no
    PermitTunnel no
```

(`UsePAM no` was in the first draft and is *unsupported* on Alpine's PAM-less
build — `sshd_config line 7: Unsupported option UsePAM` — harmless, but leave
it out.) `keys.sh` returns one fixed ed25519 public key for `editor1|editor2`
from a read-only bind mount and nothing for anyone else; the product version
does an HTTP GET to the dashboard instead. Sanity inside the image:

```
OpenSSH_9.6p1, OpenSSL 3.1.8 11 Feb 2025     (alpine 3.19.9)
uid=1043(editor1) gid=65536(editors) groups=65536(editors)
drwxr-xr-x  root root /jail    drwxr-xr-x  root root /jail2
sshd -t -f /etc/ssh/sshd_config -> CONFIG-TEST-OK
```

Service: `ports: ["2222:22"]`, tree at `/jail/tree` (bind of
`/volume1/CCSyncTest/spike-tree`, `1043:65536` `2770`), keys at `/keys:ro`,
`cap_add: [SYS_ADMIN]` for (e). Started first try; `netstat` on the host:
`docker-proxy` on `0.0.0.0:2222` and `:::2222`. The DSM firewall did not stand
in the way of a fresh published port on this box (LAN reached it without any
firewall change).

Note what sshd sees as the client address: `192.168.176.1` — the docker bridge
gateway, because published ports go through `docker-proxy`. Anything per-IP
(MaxStartups penalties, "who is connected" in the dashboard) is blind behind a
published port; behind the tailscale netns it would see whatever
userspace-netstack presents (unmeasured, needs the login).

### (a) shell refused, SFTP works — from the base rig

```
> ssh -i <key> -p 2222 editor1@192.168.0.104 'id; ls /'
This service allows sftp connections only.                              exit 1
> ssh -i <key> -p 2222 editor1@192.168.0.104                             (no command)
Connection from user editor1 192.168.176.1 port 46568: refusing non-sftp session
This service allows sftp connections only.
Connection to 192.168.0.104 closed.                                     exit 1
> ssh -i <key> -p 2222 -L 18480:127.0.0.1:22 -N editor1@…                (forwarding)
   hangs with no session and no usable forward (AllowTcpForwarding no) -- killed after 60 s

> sftp -i <key> -P 2222 editor1@192.168.0.104
sftp> ls /
/tree
sftp> pwd
Remote working directory: /
sftp> mkdir /tree/sftp-mkdir-test
sftp> put spike_ed25519.pub /tree/sftp-mkdir-test/put.txt
sftp> ls -la /tree/sftp-mkdir-test
-rw-******    ? 1043     0              95 Aug 17  2026 /tree/sftp-mkdir-test/put.txt
sftp> ls /jail2
Can't ls: "/jail2" not found
```

Container log for the same: `Accepted key ED25519 SHA256:8uLh… found at
/usr/local/bin/keys.sh %u:1` → `Accepted publickey for editor1 …` → `Changed
root directory to "/jail"` → `Starting session: forced-command (config)
'internal-sftp -u 002'`. The chrooted view is `/tree` and nothing else (there
is no `/etc/passwd` inside the jail, so listings show numeric ids — cosmetic).

### What sshd demanded of the chroot and the keys command (each broken deliberately, then restored)

| Change | Client saw | `docker logs` |
|---|---|---|
| `chmod 775 /jail` (group-writable) | rclone: `couldn't initialise SFTP: ssh: unexpected packet in response to channel open: <nil>` | `bad ownership or modes for chroot directory "/jail"` |
| `chown 1043:65536 /jail` (mode 755) | identical | identical |
| restored `0:0` `0755` | `rclone lsd` → `tree` | — |
| `chmod 775 /usr/local/bin/keys.sh` | `ssh: handshake failed: ssh: unable to authenticate, attempted methods [none publickey], no supported methods remain` | `Unsafe AuthorizedKeysCommand "/usr/local/bin/keys.sh": bad ownership or modes for file /usr/local/bin/keys.sh` |
| `ssh nobody@…` (keys.sh returns nothing; account has `!`) | `Permission denied (publickey)` | `User nobody not allowed because account is locked` / `Connection closed by invalid user nobody … [preauth]` |

So: **the chroot directory itself and every path component above it must be
`root:root` and not group/world-writable**; what is *inside* it (`/jail/tree`,
`2770 1043:65536`) may be anything. `/jail` root-owned in the image + the tree
bind-mounted one level down is the right shape, and it is what §3.1 already
says. The keys command must be root-owned, `0755`, and its interpreter reachable
by `AuthorizedKeysCommandUser` (`nobody`); when the product's `keys.sh` needs a
token to call the dashboard, that token has to be readable by that user —
give the sidecar a dedicated `sftpkeys` user rather than `nobody`, and mount the
token `0440 root:sftpkeys`.

### (b) rclone up / down / check, 768 MiB, and (d) the chunk-size question

Test file: 805,306,368 bytes of `RandomNumberGenerator` output — deliberately
**larger than the 539,000,832-byte truncation point** the port spikes measured
against DSM's own `OpenSSH 8.2p1` at 255Ki. Remote created exactly as the
task specified plus the fleet's flags:

```
rclone config create ccsyncspike sftp host=192.168.0.104 port=2222 user=editor1 key_file=<key> shell_type=none
common: --sftp-concurrency 64 --sftp-connections 16 --checkers 16 --ignore-checksum --transfers 4
```

| Direction / chunk | wall (incl. rclone start + SSH handshake) | effective | result |
|---|---|---|---|
| UP `--sftp-chunk-size 255Ki` | 7.6 s | ~106 MB/s | `rclone check --size-only` → `0 differences found, 1 matching files` |
| DOWN 255Ki | 8.9 s | ~90 MB/s | 805,306,368 bytes, **sha256 matches** the original |
| DOWN 64Ki | 7.8 s | ~103 MB/s | 805,306,368 bytes, sha256 matches |
| UP 64Ki | 7.8 s | ~103 MB/s | listed at 805,306,368 on the remote |

Host-side sha256 of the uploaded file: `3dc7fbad46d5f6800ab363df7332eddcf1ffa02aafa820cbfcb2b678a6de8510`,
identical to the base rig's. **255Ki does not truncate against
OpenSSH-in-Alpine.** The reason is visible in the SFTP handshake
(`sftp -vvv`): the sidecar's server advertises `limits@openssh.com revision 1`
(plus `posix-rename`, `statvfs`, `fstatvfs`, `hardlink`, `fsync`, `lsetstat`,
`expand-path`, `copy-data`, `users-groups-by-id`), which 8.2p1 did not — rclone
reads the server's real packet limit and sizes accordingly. On a 1 GbE LAN
every variant is at line rate, so **no throughput difference between 64Ki and
255Ki is measurable here**; the difference the fleet tuning was written for
(in-flight window at 150 ms RTT) needs a WAN path to show and was not
measured. `rclone check` without `--size-only` reports `No common hash found`
under `shell_type=none`, as expected — size-only is the check the lanes get.

### (c) ownership on the host

```
$ ls -lnR /volume1/CCSyncTest/spike-tree
drwxrwsr-x 1 1043 65536 14 sftp-mkdir-test
drwxrwsr-x 1 1043 65536 24 up255
drwxrwsr-x 1 1043 65536 24 up64
-rw-rw-r-- 1 1043 65536 95 sftp-mkdir-test/put.txt
-rw-rw-r-- 1 1043 65536 805306368 up255/spike768.bin
$ synoacltool -get …/up255/spike768.bin -> (synoacltool.c, 596)It's Linux mode ; -get-archive -> Archive: None
```

Everything an editor writes lands **`1043:65536`, files `664`, dirs `2775`**
(the `-u 002` umask + setgid) — readable by the host, by the dashboard, by
Syncthing running as the same uid, and by SMB users the customer puts in the
`editors` group. Under a *chmod-free* share (i.e. one that still carries the
DSM ACL) the ACL inheritance from spike 1 would apply instead; the spike dir
had been `chmod`ed so it shows the pure-POSIX case.

### (e) BONUS — per-editor bind views inside the sidecar (S3)

With `cap_add: [SYS_ADMIN]` alone, under DSM's default `docker-default`
AppArmor profile:

```
$ docker exec ccsync-spike-sftp sh -c 'cat /proc/1/attr/current; mount --bind /jail/tree/ProjectA /jail2/tree/ProjectA'
docker-default (enforce)
mount: mounting /jail/tree/ProjectA on /jail2/tree/ProjectA failed: Permission denied     (rc 255)
```

With `security_opt: ["apparmor=unconfined"]` added to the sftp service only
(seccomp default profile kept; container recreated):

```
$ docker exec ccsync-spike-sftp sh -c 'cat /proc/1/attr/current; grep CapEff /proc/1/status; mount --bind /jail/tree/ProjectA /jail2/tree/ProjectA; echo mount-rc=$?; grep jail /proc/self/mountinfo'
unconfined
CapEff: 00000000a82425fb
mount-rc=0
874 856 0:34 /@syno/CCSyncTest/spike-tree           /jail/tree           rw,nodev,relatime - btrfs /dev/mapper/cachedev_0 rw,ssd,synoacl,…,subvol=/@syno/CCSyncTest
686 856 0:34 /@syno/CCSyncTest/spike-tree/ProjectA  /jail2/tree/ProjectA rw,nodev,relatime - btrfs /dev/mapper/cachedev_0 …
$ docker exec ccsync-spike-sftp sh -c 'mount -o remount,bind,ro /jail2/tree/ProjectA; echo rc=$?'
rc=0        -> …/jail2/tree/ProjectA ro,nodev,relatime …
```

And it is exactly what sshd's chroot for `editor2` (`ChrootDirectory /jail2`)
serves — from the base rig, same key, `user=editor2`:

```
> rclone lsl ccsyncspike2:/
        8 2026-08-17 22:40:46.000000000 tree/ProjectA/a.txt          # ProjectB is invisible
> rclone touch ccsyncspike2:/tree/ProjectA/editor2-was-here.txt      # while the bind is ro
ERROR : … failed to touch (create): Update Create failed: sftp: "Failure" (SSH_FX_FAILURE)
> rclone lsd ccsyncspike:/tree                                       # editor1, full chroot
ProjectA  ProjectB  sftp-mkdir-test  up255  up64  writer-dir
```

`umount` afterwards: rc 0. **Per-project (and per-project *read-only*) SFTP
views work inside the sidecar, from a mount namespace that sshd's chroot sees
immediately, without touching the host** — at the cost of `SYS_ADMIN` +
`apparmor=unconfined` on that one service. TrueNAS SCALE was not tested (no
AppArmor there by default, so `SYS_ADMIN` alone should do; confirm in S3).

### VERDICT (S2, and S3)

- **Ship the SFTP sidecar (WP C) as spiked**: Alpine + `openssh-server`
  9.6p1, `internal-sftp -u 002`, chroot `/jail` root-owned with the tree one
  level down, `AuthorizedKeysCommand` under a dedicated low-priv user, users
  sharing one uid:gid, `AllowTcpForwarding no`. Nothing about it needed the
  host, root-over-SSH, DSM ACLs or `chown -R`. `Match User editor*` needs the
  more specific `Match` block *first* (sshd takes the first match).
- **Manifest default `sftp_chunk_size` for the appliance = 255Ki**, measured
  end-to-end above the old truncation point with sha256 intact. Keep the
  64Ki rule *only* for `sftp_host` = a NAS's own sshd (`OpenSSH < 8.5`, no
  `limits@openssh.com`) — the companion's `_SITE_CONFIG_KEYS` comment already
  says exactly that; it stays true.
- **S3 is answered: per-project bind views can ship in WP C**, not as a
  follow-up, provided the compose carries `cap_add: [SYS_ADMIN]` and
  `security_opt: ["apparmor=unconfined"]` on the sftp service. The dashboard
  drives them by `docker exec`-free means: a tiny root loop *inside the sidecar*
  reading a `views.json` on `/data` (the same selection rows lane C
  enforcement uses) and issuing `mount --bind` / `remount,ro` / `umount`.
  Read-only project grants come free.
- Host key persistence: the spike's host key lived in the image (regenerated
  on every `docker build`); the product must keep `/etc/ssh/ssh_host_*` on
  `/data` or every image update makes every editor's rclone refuse the host.

---

## Recommendations for WP A / B / C, in one place

| WP | Keep | Change because of this spike |
|---|---|---|
| **A** image + registry | `ccsync-sftp` = the Dockerfile above, pinned `alpine:3.19` (or 3.20), 9 MiB | host keys and the keys-command token on `/data`, not in the image; `AuthorizedKeysCommandUser` a dedicated user, not `nobody` |
| **B** tailscale sidecar | stock image pinned to `v1.102.2` (digest above), userspace default, state on `/data`, kernel mode as a commented `devices:`+`cap_add:` block | **no containerboot login**: `entrypoint: tailscaled …`; dashboard does `PATCH /prefs`, `POST /login-interactive`, polls `/status`, then `POST /serve-config` (it 500s `netMap is nil` before login); decide netns-sharing vs Serve TCP-forward on day 1 of WP B with a throwaway tailnet, because a restarted sidecar orphans its siblings' netns; `depends_on … restart: true` either way |
| **C** sftp + identity | everything in the S2 verdict; chunk 255Ki; `sftp_shell_type=none` | per-project bind views move *into* C (S3 is answered); `SYS_ADMIN` + `apparmor=unconfined` on the sftp service in the customer compose, with one line in the security notes saying why |

Still owed before B is coded, one afternoon with a throwaway tailnet: Serve
`https:443 → 127.0.0.1:8480` actually terminating TLS; inbound
`tailnet-ip:22000`/`:22` reaching a netns sibling; whether Serve `TCPForward`
to `tcp://sftp:22` works from LocalAPI (the "don't share netns" option);
userspace vs kernel SFTP throughput through the node.

---

## Left on the device

Nothing. Specifically: no container, image, volume, network, compose project,
directory, user, group, share, port or firewall change from this session
remains. `ccsync-svc` (uid 1043) and `editors` (gid 65536) predate it and were
only *read*.

## Removed

| Item | Verification |
|---|---|
| compose project `ccsync-spike` (7 services) + volumes `ccsync-spike_ts-sock`, `ccsync-spike_tsd-sock` + network `ccsync-spike_default` | `docker compose … down -v` output above; `docker ps -a --filter name=ccsync-spike \| wc -l` → 0; `docker volume ls \| grep -c ccsync-spike` → 0; `docker network ls \| grep -c ccsync-spike` → 0; `docker compose ls \| grep -c ccsync-spike` → 0 |
| ad-hoc containers `ccsync-spike-tskern`, `ccsync-spike-tskern2` | `docker rm -f` (they ran ~6 s each) |
| images `ccsync-spike-sftp:local` (+ its 8 intermediate layers), `tailscale/tailscale:latest`, `alpine:3.19` | `docker rmi` output shows `Untagged`/`Deleted`; `docker images \| grep -E 'ccsync-spike\|tailscale\|alpine'` → only the pre-existing `postgres:15-alpine`. `python:3.12-slim` pre-existed and stays |
| `/volume1/docker/ccsync-spike/` (compose, serve.json, lapi.py, ts-state with a never-authorised machine key, tsd-state, sftp build context, keys) | `ls /volume1/docker \| grep -i ccsync` → only the live `ccsync` |
| `/volume1/CCSyncTest/spike-tree/` (2 × 768 MiB, ProjectA/B, writer files) | `ls -lna /volume1/CCSyncTest` → `@eaDir`, `Creators_Club`, `Projects` as before; `df -h /volume1` → 59 G free, unchanged |
| host port `2222` | `netstat -tlnp \| grep ':2222 ' \| wc -l` → 0 |
| Tailscale side | the spike nodes only ever reached `NeedsLogin`; no auth URL was visited, no node exists in any tailnet |
| base rig: rclone remotes `ccsyncspike`, `ccsyncspike2` | `rclone listremotes` → only the pre-existing `creators_club_sftp:` |
| base rig: spike keypair `spike_ed25519{,.pub}`, 768 MiB test file + 2 downloads (2.3 GB), sftp batch file | scratchpad `keys/`, `bench/` removed; no ssh/sftp process left running (`ssh` was invoked with `UserKnownHostsFile=NUL`, so no known_hosts entry either) |

The password was read from its file into `SYNO_PW` for the paramiko helper
and never printed; the private key never left the scratchpad and is deleted.
