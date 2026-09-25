# Transfer speed: where the ceiling is, and what would move it

Investigation of 2026-09-25, in answer to the owner's question of the same
day: "do a deep dive into how we can optimise transfer speeds to the
theoretical maximum. Me and Ruskin are both on 500 megabit lines so we
should be able to hit that in theory. In reality we are stuck around 18 MB/s
maximum. Also, does the system handle transferring to multiple users at the
same time? If multiple remote editors sync at once it should split the
bandwidth until it hits the maximum upload that can be reached."

Everything below was measured that morning from three places: Ruskin's PC
(the real remote editor, over the internet), this base rig (wired, on the
studio LAN with the NAS), and the NAS itself. Nothing was changed anywhere:
no config, no service, no lane, no Syncthing setting. Every test file was
random data in a temp folder, and every temp folder on the NAS, on Ruskin's
PC and on this rig was deleted afterwards (section 8 has the raw numbers).

---

## 1. The answer in plain words

**The 18 MB/s is not our software, and it is not the NAS.** The sync flags,
the SFTP window, the number of parallel streams, the NAS's CPU, disks and
sshd, and the studio's internet line were each tested and each one has
headroom of 3x to 40x above what Ruskin sees. The ceiling is in two places,
one per direction, and they are different problems:

| | What Ruskin gets today | Where the ceiling is | Confidence |
|---|---|---|---|
| **Lane A, his originals going UP to the NAS** | **6.1 MB/s (49 Mbit/s)** in every configuration tried | **His internet line's upload tier.** His raw upload to Cloudflare, outside Tailscale, outside SFTP, is 6.13 MB/s: identical. A "500 Mbit line" from a cable provider is 500 down and, here, about 50 up. | Very high (same number inside and outside the tunnel, six rclone configurations, flat to 0.1 MB/s) |
| **Lane B, proxies coming DOWN to him** | **15 to 19.5 MB/s (120 to 156 Mbit/s)** whether 1, 4, 8 or 16 streams | **A cap on the Tailscale UDP path between the studio and his PC.** His raw download outside the tunnel does 57 MB/s. Downloading over the tunnel from THIS rig instead of the NAS hits the same 17 to 22 MB/s cap. Adding streams does not help, which means one shared bottleneck, not a per-stream one. | High that it is the tunnel path; medium on WHICH hop (section 6 splits it) |

So "we should be able to hit 500 in theory" is half true. Downloads to
Ruskin could reach roughly 55 MB/s (about 450 Mbit/s) once the tunnel-path
cap is found, because both his line and the studio's line can carry it.
Uploads from Ruskin cannot exceed about 6 MB/s on his current line no matter
what CC Sync does; the only fix is a plan with a faster upload, or a wired
connection at a site that has one.

Ranked list of what bounds each transfer today, with the evidence:

1. **Ruskin's upload tier, about 50 Mbit/s** (lane A). Evidence: SFTP uploads
   over the tunnel 6.1 MB/s x 6 configurations; HTTP upload outside the
   tunnel 6.13 MB/s. Confidence very high.
2. **The tunnel path to Ruskin, about 150 to 180 Mbit/s** (lane B, and lane C
   when it carries anything big). Evidence: SFTP from the NAS 15 to 19.5 MB/s
   with 1 to 16 streams; HTTP from the base rig over the tunnel 17.5 MB/s
   single, 22.5 MB/s with 4; raw HTTP from Singapore outside the tunnel
   57 MB/s with 4 streams; the NAS's own tunnel end does 107 MB/s to a LAN
   peer. The afternoon's tests (section 6a) ruled out CPU at either end,
   MTU, DERP, Wi-Fi and any per-flow or per-peer limit, and found Ruskin
   behind his ISP's carrier-grade NAT: **UDP policing on his side is the
   leading suspect, the studio router's UDP forwarding the second**, and one
   hotspot test tells them apart.
3. **Nothing else is close.** The SFTP window (255 KiB x 64 = 16.3 MiB per
   stream) allows about 800 MB/s at Ruskin's 21 ms round trip. The NAS
   takes a single SFTP stream at 290 to 315 MB/s and four at 645 MB/s
   (writing to the real pool, past ZFS's 4 GiB write cushion). The studio
   line sends at least 64 MB/s (514 Mbit/s) outbound. rclone's flags are
   already the right ones (section 3 shows the wrong ones cost 3.5x and 6x).

## 2. Multiple editors at once: what happens today

**Yes, several remote editors can transfer at the same time today, and
nothing in CC Sync serialises them.** Traced end to end:

- Each machine runs its own sequencer (`companion/src/ccsync_companion/sync/sequencer.py`).
  It walks that machine's ticked projects ONE AT A TIME, but for each project
  lane A (up) and lane B (down) run **concurrently** in two rclone processes
  (`_run_lanes_a_and_b`, sequencer.py:2513-2534), and express lane A can run
  a third rclone beside them (`rclone_lane.py:2676-2681`). Machines do not
  know about each other; the dashboard only supplies each machine its
  project order, it never schedules or throttles transfers.
- Per rclone process: `--transfers 4` (`config.py:246`, Ruskin's
  `config.toml` has `transfers = 4`), `--sftp-connections 16`
  (`rclone_lane.py:408`), and for lane B rclone's default multi-thread
  download (4 streams per file over 256 MiB, confirmed live on Ruskin's
  PC: "multi-thread copy: ... OpenWriterAt" in section 8). So one busy
  machine holds up to 16 SSH connections per rclone, up to 48 in total.
- On the NAS, sshd is at OpenSSH defaults apart from the lines in
  section 8: `MaxSessions 10` is per connection (rclone uses one session
  per connection, so it never binds), and `MaxStartups 10:30:100` only
  limits handshakes that are simultaneously *in progress and not yet
  authenticated*. With four machines that is not reached; with ten
  machines all starting a pass at once it starts dropping 30 % of new
  handshakes beyond the tenth, which rclone survives by retrying
  (`--retries-sleep 10s`, `rclone_lane.py:1675`). The rclone comment at
  `rclone_lane.py:406-408` sized `--sftp-connections 16` against exactly
  this. Live during the test: 2 SSH sessions on the NAS in total.
- No `--bwlimit`, `--tpslimit` or any bandwidth cap exists anywhere in the
  companion, the config or the dashboard (grepped: none). Syncthing on the
  editor side has `maxSendKbps = 0`, `maxRecvKbps = 0`.
- Syncthing (lane C): the NAS folder config carries `maxConcurrentWrites 32`
  and `pullerMaxPendingKiB 65536` (`server/setup_syncthing_folder.py:140-143`,
  `dashboard/src/ccsync_dashboard/provision.py:503-504`); the editor side runs
  `maxFolderConcurrency 2` (`config.py:294`, applied by
  `syncthing_admin.ensure_max_folder_concurrency`, :720). Ruskin's Syncthing
  is connected to the NAS **directly** (`tcp-client` to `100.71.216.3:22000`,
  TLS 1.3, not a relay), so the dashboard's RELAYED chip is not lit for him.

**How the studio's outbound bandwidth is shared** when two editors pull
proxies at once: by TCP's per-flow fairness inside the studio's uplink and
the NAS's tunnel end. Each editor's lane B holds up to 16 flows, so two
editors with the same settings get roughly equal shares; an editor who set
`transfers = 8` would get more. Today this is academic: the studio sends at
least 64 MB/s outbound and each remote editor is capped near 18 MB/s by
their own tunnel path, so three editors pulling flat out still fit. It only
becomes a fairness question once per-editor ceilings rise above about
30 MB/s each (section 5, item 6).

**Lane A across editors**: each editor's uploads are bounded by their own
line's upload tier before anything at the studio matters. The studio's
inbound side was not measured directly (it is at least 500 Mbit/s nominal
and took Ruskin's 49 Mbit/s without effort); two or three editors uploading
at 6 MB/s each do not approach it.

## 3. The exact transfer shape in code, and what each part is worth

All three rclone commands are built in
`companion/src/ccsync_companion/sync/rclone_lane.py`:

| Piece | Where | What it is | Measured worth |
|---|---|---|---|
| Lane A periodic | `build_up_command`, :1706-1754 | `rclone copy <local> <remote> --filter-from ... --ignore-existing --ignore-case --min-age 120s --min-size 1B --transfers 4` + tuning + transport flags | |
| Lane A express | `build_express_command`, :1897-1966 | same shape with `--files-from-raw`, `--no-traverse --no-update-dir-modtime`, its own `--partial-suffix` | |
| Lane B | `build_down_command`, :1969-2032 | `rclone sync <remote> <local> --filter-from ... --min-age 120s --backup-dir ... --max-delete ... --transfers 4` + tuning + transport flags | |
| `--sftp-chunk-size 255Ki` | `DEFAULT_SFTP_CHUNK_SIZE`, :401 | largest chunk SFTP allows; rclone's default is 32Ki | LAN upload 342 MB/s vs **98 MB/s at 32Ki** (3.5x). At Ruskin's RTT no difference (his cap is elsewhere) |
| `--sftp-concurrency 64` | :405 | in-flight window = 255Ki x 64 = 16.3 MiB per stream | at 21 ms RTT this allows ~800 MB/s per stream; 128 measured identical on Ruskin's link |
| `--sftp-connections 16` | :408 | caps the SSH pool per rclone process | sized against sshd `MaxStartups` |
| `--checkers 16` | :409 | parallel comparisons | listing speed only |
| `--ignore-checksum` | :410-423 | skips the post-copy `md5sum` the NAS would otherwise run over the whole file | LAN upload 342 MB/s vs **47 MB/s with the md5 re-read** (the NAS spent 40 s re-reading 2 GiB) |
| `--order-by modtime,descending` / `size,ascending` | :427-428 | newest originals first; smallest proxies first | perceived progress, not throughput |
| multi-thread download | rclone default (`--multi-thread-cutoff 256Mi`, `--multi-thread-streams 4`), not set by us | one proxy over 256 MiB is read with 4 SFTP streams into a sparse local file | LAN download 716 MB/s vs 285 MB/s single stream (2.5x); on Ruskin's link 15.5 vs 14.9 (the cap is shared) |
| `--timeout 5m --contimeout 60s --retries-sleep 10s` | `_transport_flags`, :1663-1677 | stalled-peer bounds | |
| `transfers = 4` | `config.py:246`, per machine | files in flight per lane | |
| no multi-thread UPLOAD | rclone's SFTP backend cannot | one original rides one SSH stream | the reason the window flags above exist |

The rclone remote is written by the installer
(`installer/windows_bootstrap.ps1:2041-2146`, `macos_bootstrap.sh`):
`type = sftp`, `host = <NAS tailnet IP>`, `port = 22`, `shell_type = unix`,
key auth. Ruskin's is exactly that, host `100.71.216.3`, rclone v1.74.4.

Syncthing tuning is in section 2. The NAS-side "tailnet only" option set
(`dashboard/src/ccsync_dashboard/syncthing_client.py:57-70`,
`relaysEnabled false` etc.) is deliberately NOT applied, and does not need
to be for speed: Ruskin's device is already direct.

## 4. The network path and the theoretical maximum per lane

Measured facts about the path:

| | Studio (NAS + this rig) | Ruskin |
|---|---|---|
| Tailscale path to the NAS | direct, LAN, 2 ms (this rig) | **direct** (`114.34.8.231:39501`), not DERP; 21 ms; 0 % loss over 20 pings (13 to 19 ms) |
| Nearest DERP | Hong Kong 27 ms | Hong Kong 75 ms (irrelevant while direct) |
| Public IP / ISP | 114.34.8.231 (HiNet) | 122.100.70.91 (a different, cable-class ISP) |
| Line, measured outside the tunnel | upload at least **64 MB/s (514 Mbit/s)** to Cloudflare with 2 streams (41 MB/s single); download not cleanly measurable from here (public test hosts refused or throttled curl) | upload **6.13 MB/s (49 Mbit/s)**; download **18 MB/s single stream, 57 MB/s with 4 streams** from Singapore |
| Last hop | NAS: 10 GbE `eno1np0`, MTU 9000; this rig wired | **Wi-Fi 6**, Intel AX210, 681 Mbps receive / 576 Mbps transmit PHY, signal 64 to 75 % |
| Tunnel MTU | 1280 on both `tailscale0` and the Windows Tailscale adapter | same |
| TCP stack | NAS: cubic + fq_codel, 32 MiB max windows; Windows: CUBIC | CUBIC, autotuning normal |
| SSH | sshd defaults + `Ciphers +aes128-cbc`, `Compression no`; rclone (Go) picks `aes128-gcm@openssh.com` | same server |
| NAS | 2 x Xeon E5-2620 v4 (32 threads), 62 GB, load 0.2 to 0.4, 96 % idle during tests; `tank` = raidz1 of 6 x 14 TB SAS HDD; homes and the tree both on `tank/TheCreatorsPool` (sync standard) | |

What the NAS can do (this rig, wired, writing to the real pool at
`/mnt/tank/TheCreatorsPool`, temp folder purged):

| | Single stream | Parallel |
|---|---|---|
| SFTP up over the LAN | 287 to 315 MB/s (three 2 GiB files back to back, 6 GiB, past the 4 GiB ZFS dirty cushion) | 645 MB/s (4 files) |
| SFTP down over the LAN | 285 MB/s | 716 MB/s (4 multi-thread streams) |
| SFTP up over the NAS's **Tailscale** address, both ends on the LAN | 192 MB/s (1.5 Gbit/s) | |
| SFTP down over the NAS's Tailscale address | 107 MB/s (859 Mbit/s) | 100 MB/s (4 files) |

So the tunnel software on the NAS and on a Windows peer costs something
(107 to 192 MB/s versus 285 to 315 on the raw LAN) but sits 5 to 10x above
Ruskin's cap. The remaining candidates for his 150 to 180 Mbit/s download cap
are all on the path between the studio router and his Wi-Fi card, none of
them ours (section 6 says how to tell them apart).

Theoretical maximum per lane, given all of the above:

| Lane | Bound today | Bound after the fixable things | Hard bound |
|---|---|---|---|
| A, Ruskin's originals up | **6.1 MB/s** (his upload tier) | unchanged until his line changes | his line: a 250 Mbit upload plan would give ~30 MB/s; the NAS side takes 290 MB/s per stream |
| B, proxies down to Ruskin | **15 to 20 MB/s** (tunnel path cap) | **~50 to 57 MB/s** (his download line) once the tunnel path cap is removed | min(his line 57 MB/s, studio uplink 64+ MB/s shared by every remote editor) |
| C, Syncthing, to Ruskin | same tunnel path, so the same ~18 MB/s ceiling for a large file; usually latency-bound small files | same as B | same as B |
| A and B, an editor at the studio on Wi-Fi (the Razer) | **nothing: its rclone remote cannot log in (section 7)** | after the account fix: Wi-Fi bound, roughly 30 to 60 MB/s (it reached 33 MB/s to Singapore on this Wi-Fi) | Wi-Fi ac at 866 Mbps PHY |
| Aggregate, all remote editors' downloads | sum of their individual caps | **~64 MB/s+, the studio uplink**, shared by TCP fairness | the studio line |

## 5. What would change things, ranked

Expected gain, risk and effort per item. Nothing here has been done; the
owner decides.

1. **Find and remove the tunnel-path cap to Ruskin (lane B: 18 to ~50 MB/s,
   about 3x).** Zero code. Section 6a narrowed it to two places: UDP
   policing on Ruskin's side (he is behind his ISP's carrier-grade NAT; the
   leading suspect) or the studio router's software UDP forwarding (gateway
   `192.168.0.1`, MAC `3c:52:a1:85:40:ad`, also the studio AP, PPPoE WAN, no
   UPnP). Two short tests settle it: Ruskin on a phone hotspot pulling the
   same 1 GiB from the NAS, and a studio laptop tethered to a phone doing
   the same. Risk: none from testing. Effort: half an hour each. If it is
   his ISP, the fixes are on his side (a different ISP or plan, or a static
   or non-CGNAT address if the ISP sells one) and the same cap will apply
   to any editor on such a connection; if it is the studio router, a router
   with hardware NAT for UDP fixes every remote editor at once.
2. **Ruskin's line: a plan with a faster upload (lane A: 6 to 30 MB/s, 5x).**
   Zero code. His upload tier is the whole of lane A's ceiling. A 40 GB card
   takes 1.8 hours at today's 6.1 MB/s and 22 minutes at 30 MB/s. Risk:
   none. Effort: an ISP change on his side. Nothing in CC Sync can improve
   this by even 10 %.
3. **If the cap is UDP-specific and cannot be removed: a TCP path for bulk
   bytes.** `SPEC.md:28` records that a forwarded high TCP port on the HiNet
   router "hit line rate" (BitTorrent 51413). An SFTP endpoint on a forwarded
   high port, key-only and SFTP-only (`docs/TENANCY.md`, `Match Group
   editors` with `ForceCommand internal-sftp`), reachable only by the editor
   accounts, would carry lanes A and B outside the UDP tunnel. Expected gain:
   the same ~3x on lane B, if the cap is UDP-only. Risk: it reverses the
   2026-08-17 "Tailscale only, nothing on the public internet" decision
   (`docs/HOW_IT_WORKS.md:778`), exposes sshd to the internet, and needs the
   companion to learn a second host per remote (the installer writes one
   `host`, `windows_bootstrap.ps1:2064-2069`). Effort: medium (a day), plus
   the security review. Only worth it after item 1's diagnosis says the cap
   is UDP and not fixable at the router.
4. **Keep the rclone flags exactly as they are.** The two flags an outsider
   would suspect were both measured to be right: the 255 KiB chunk is 3.5x
   faster than rclone's default, and `--ignore-checksum` avoids a 6x
   slowdown from the NAS re-reading every file. `--sftp-concurrency 128`
   measured identical to 64 on Ruskin's link and on the LAN. Lane B's
   multi-thread download is already on. Do not add `--bwlimit` to editors:
   their own lines are already the limit.
5. **`MaxStartups` on the NAS when the fleet passes about eight machines.**
   Ten machines x three rclone processes each starting a pass together can
   exceed the default 10 concurrent unauthenticated handshakes. Raising it
   to `30:30:100` in the SSH service's auxiliary parameters
   (`docs/SERVER.md:349-353`) costs nothing; rclone already retries, so
   today this shows only as a slower first pass, never a failure. Gain:
   none today. Risk: none. Effort: five minutes.
6. **Fair sharing between editors: a per-machine download cap the dashboard
   hands out.** Not needed while per-editor ceilings are 18 MB/s against a
   64 MB/s studio uplink. If item 1 lifts editors to 50 MB/s each, two
   editors will contend and the one with more streams wins. The cheap
   version is a `bwlimit_down` key read into `RcloneTuning.flags`
   (`rclone_lane.py:575-590`) as `--bwlimit`, set per machine in
   `config.toml`. The right version has the dashboard divide the studio's
   configured uplink by the number of machines currently in lane B and send
   each its share on the report reply, the same channel `commands.halt`
   uses. Gain: fairness, not speed. Risk: a wrong cap slows everyone. Effort:
   a day for the dashboard version. Do this after item 1, not before.
7. **A different transport for lane B (rclone over SMB, WebDAV or an S3-style
   endpoint on the NAS) is NOT recommended.** On the LAN the SFTP path
   already does 285 to 716 MB/s, so SSH is not the bottleneck at this
   fleet's speeds (`docs/SERVER-SYNOLOGY.md:446-449` measured the same
   conclusion on a much weaker NAS: SFTP within 12 % of SMB). Changing the
   transport would not touch either real ceiling.
8. **Lane C (Syncthing) tuning is not where the time goes.** Its folders
   already carry the WAN pull tuning, the editor connects direct, and
   `compression = metadata` (`windows_bootstrap.ps1:1922`) is right for
   video. Nothing to change for speed.
9. **Tailscale MTU / DERP / relays: nothing to do.** Both remote peers are
   direct; MTU 1280 is Tailscale's fixed default and cannot explain a flat
   cap; disabling Syncthing relays on the NAS remains a safety change, not
   a speed one.

## 6a. The lane B cap: which culprit the evidence points at (afternoon of 2026-09-25)

The owner ruled Wi-Fi capacity out, and the numbers agree: Ruskin pulled
57 MB/s from Singapore over the same Wi-Fi, on the same 5 GHz 802.11ax link
(649 to 721 Mbps receive, signal 57 to 75 %), that carries 14 to 19 MB/s
through the tunnel. A radio that carries 460 Mbit/s of TCP is not the thing
holding the tunnel to 120 to 150. Time was therefore not spent on band or
signal beyond recording them beside each test.

The tests run to split the remaining suspects, all read-only, no setting
changed anywhere:

| Test | Result |
|---|---|
| `tailscale status --json` on both ends | Ruskin sees `truenas` at `CurAddr 114.34.8.231:39501`, direct; this rig and the Razer see it at `192.168.0.102:39501`, direct over the LAN. His own endpoints: `122.100.70.91:4751`, `:1794`, `:41641` and `192.168.0.12:41641` |
| `tailscale netcheck`, both ends | UDP yes on both; `MappingVariesByDestIP: false` on both; `PortMapping` empty on both (no UPnP/NAT-PMP/PCP on either router); no captive portal; nearest DERP Hong Kong for both (27 ms studio, 75 ms Ruskin) |
| `tracert` first hops, for double NAT | Studio: `192.168.0.1` then `168.95.98.254` (HiNet, public). **No double NAT at the studio.** Ruskin: `192.168.0.1` then `10.104.128.1`, `10.102.254.121`, `10.102.251.130`: **his ISP puts him behind carrier-grade NAT** (his "public" `122.100.70.91` is the ISP's shared address) |
| MTU probes (`ping -f -l`) | Tunnel: 1252 passes, 1272 fails, from every machine, i.e. the expected 1280 tunnel MTU, no black hole. Internet from Ruskin: 1472 passes (a clean 1500 path). Internet from the studio: 1472 is refused by `192.168.0.1` itself, so the studio WAN is PPPoE-class (1492 or less); a tunnel packet is at most about 1340 bytes and fits with room, so no fragmentation on the path |
| Per-core CPU on Ruskin's PC during a 1 GiB tunnel download | busiest core 5 to 26 %, average 2 to 8 %; `tailscaled` 26 % of one core. **No pinned core.** Same on the Razer (busiest 6 to 11 %, `tailscaled` 3 to 8 %) |
| Per-core CPU on the NAS during the same download | busiest core 6 to 29 %, average 1.5 to 8 %; his `sshd` 7 %; `tailscaled` (pid 7943, 6.6 % lifetime average) below the top lines, under 1.4 %. **No pinned core.** |
| Two tunnel peers at once (NAS SFTP + this rig HTTP, both to Ruskin) | 10.3 + 9.3 = **19.6 MB/s aggregate**, the same as one peer alone. A second WireGuard session, a second sshd, a second source host and a second studio LAN port bought nothing: the cap is shared by everything heading to him |
| Time of day | 10:40 download 15.5 MB/s; 12:13 download 13.7 MB/s; upload 6.1 then 6.0 MB/s. Flat so far; an evening point is still owed |
| A Windows Tailscale client on Wi-Fi at the studio (the Razer, both ends on the LAN) | tunnel 18.4 to 29 MB/s versus 24 to 27 MB/s on the raw LAN: the tunnel costs nothing measurable at these rates on a Windows Wi-Fi client |

Verdicts:

| Suspect | Verdict | What says so, or what would settle it |
|---|---|---|
| (c) per-flow CPU in the tunnel, Ruskin's end (Windows Tailscale / wintun decrypting) | **Ruled out** | no core above 26 % during the transfer, `tailscaled` at a quarter of one core, and a second peer added nothing |
| (c) per-flow CPU in the tunnel, the NAS end (tailscaled encrypting) | **Ruled out** | no core above 29 %, `tailscaled` under 1.4 %; the NAS pushes 107 MB/s through the same tunnel process to a LAN peer |
| Ruskin's Wi-Fi | **Ruled out** (owner's ruling, and the 57 MB/s raw download over it) | |
| MTU / fragmentation / DERP relay | **Ruled out** | direct path both ways, clean 1280 tunnel MTU, no black hole |
| A per-peer or per-flow limit anywhere | **Ruled out** | more streams, and a second peer, do not add up past ~20 MB/s |
| (b) UDP shaping on Ruskin's side: his ISP's carrier-grade NAT, or his own router | **Ruled in as the leading suspect** | He is behind CGNAT (`10.104.128.1`), which is exactly where ISPs police UDP per subscriber; every tunnel flow to him shares one cap regardless of source; his TCP download is 3x faster. Settled by: Ruskin on a phone hotspot (a different carrier) pulling the same 1 GiB; or Ruskin wired to his router (rules his Wi-Fi driver in or out for UDP specifically, which the TCP test does not cover); or a UDP iperf3 from the studio to his PC showing loss at 150 to 180 Mbit/s |
| (a) the studio router's UDP/NAT handling | **Still possible, second** | It is a consumer router (`3c:52:a1:85:40:ad` at `192.168.0.1`, also the studio AP, PPPoE WAN, no UPnP) forwarding every tunnel byte in software; the two-peer test cannot separate it from (b), because both peers leave through it to the same destination. Settled by: a laptop tethered to a phone (off the studio line) pulling from the NAS over the tunnel at 40+ MB/s rules it in; a second remote site that is not behind CGNAT getting 40+ MB/s rules it out |
| (b') UDP shaping by HiNet at the studio | **Unlikely, not excluded** | HiNet forwarded a high UDP port at line rate before (`SPEC.md:28`); the same hotspot test settles it with (a) |

## 6. Measurement plan for the remote-editor side

What to run, and what each result would mean. Every step is short, uses temp
files only, and changes no setting. The scripts used on 2026-09-25 are the
recipe: an rclone copy of a 1 GiB random file to and from a `ccsync_bench_tmp`
folder in the editor's own SFTP home (never the tree), timed, with the
companion's flags (`--sftp-chunk-size 255Ki --sftp-concurrency 64
--sftp-connections 16 --checkers 16 --ignore-checksum --transfers 4`), then
`rclone purge` of that folder.

**Splitting the tunnel-path cap (item 1 above), in order:**

1. **Ruskin on an Ethernet cable to his router**, same test. If the download
   jumps from 18 to 40+ MB/s: it was his Wi-Fi's handling of the tunnel's
   UDP packet stream (Wi-Fi carried 460 Mbit/s of TCP fine, so this would be
   a driver or power-saving matter, not signal). If unchanged: not his
   Wi-Fi.
2. **A laptop at the studio, on the studio Wi-Fi, pulling from the NAS over
   the NAS's Tailscale address** (the Razer; scripts ready, section 7, and
   its NAS login has to be repaired first). If it does 40+ MB/s: Windows
   Tailscale over Wi-Fi is fine and the cap is on the internet path or the
   router. This is the control that was missing on the day.
3. **The same laptop tethered to a phone hotspot (off the studio line),
   pulling from the NAS over Tailscale.** If it caps near 150 to 180 Mbit/s
   too: the cap is at the studio end (router UDP NAT or HiNet's UDP
   treatment). If it does better than Ruskin: the cap is on Ruskin's side
   or his ISP.
4. **The studio router's admin page** (`http://192.168.0.1`): look for
   hardware NAT / NAT acceleration / "flow offload" and whether it applies
   to UDP; note the model. A consumer router forwarding 150 Mbit/s of UDP
   in software is a known shape.
5. **iperf3, if the owner agrees to install it on the NAS host or a studio
   PC and on Ruskin's PC**: `iperf3 -c <nas tailnet ip> -R` (TCP, over the
   tunnel) and `-u -b 400M` (UDP) in both directions. This gives the tunnel's
   raw capacity independent of rclone and confirms whether UDP is being
   policed (loss and jitter in the UDP report).
6. **Repeat Ruskin's download at two other times of day** (his ISP's evening
   contention shows up as a lower cap after 20:00).
7. **Ruskin's raw upload to any public speed test**, when convenient: it
   will read about 50 Mbit/s and settles the lane A question with him
   directly.

**The owner's own remote sessions:** when the Razer is next away from the
studio, run the same rclone copy pair and a public upload/download test.
That gives the second remote editor's two ceilings; the doc's section 8
table has a row waiting for it.

## 7. The Razer (the owner's laptop, on the studio Wi-Fi), measured 16:02 to 16:35

The third case: a Windows editor machine whose Tailscale path to the NAS is
direct over the studio LAN (`192.168.0.102:39501`, 1 ms), on Wi-Fi 802.11ac
at 866.7 Mbps both ways, signal 78 to 79 %, MediaTek MT7921, Ryzen 9 5900HS,
CUBIC, rclone v1.74.4, companion running with no rclone in flight. Its
remote `creators_club_sftp` (`100.71.216.3`, user `alex`, key
`~/.ssh/ccsync_ed25519`) is exactly the companion's own path, and the tests
below use it with the companion's flags. The laptop was held awake for the
tests by a `SetThreadExecutionState(ES_CONTINUOUS | ES_SYSTEM_REQUIRED |
ES_AWAYMODE_REQUIRED)` call inside the test process itself (checked with
`powercfg /requests`, gone when the script ended); no power setting was
changed. A first attempt at 12:17 lost its output at a session reset and
left one `rclone` hung at a 0-byte `.partial` on the LAN-IP control
download; that process and its two parents were the only things killed,
and every test was rerun with a hard 4-minute bound per transfer.

| Test (CC Sync path: `creators_club_sftp` over Tailscale, direct on the LAN) | Time | Rate |
|---|---|---|
| lane A: UP 1 GiB single, companion flags | 23.5 s | **45.7 MB/s (366 Mbit/s)** |
| lane A: UP 4 x 256 MiB, --transfers 4 | 18.3 s | **58.6 MB/s (469 Mbit/s)** |
| lane B: DOWN 1 GiB single, companion flags (rclone default multi-thread 4) | 31.0 s | **34.7 MB/s (278 Mbit/s)** |
| lane B: DOWN 1 GiB single, 1 stream | 24.3 s | 44.2 MB/s (354 Mbit/s) |
| lane B: DOWN 4 x 256 MiB, --transfers 4 | 27.0 s | 39.8 MB/s (318 Mbit/s) |
| control only: UP 1 GiB single via the NAS LAN IP, no tunnel | 19.4 s | 55.3 MB/s (442 Mbit/s) |
| control only: DOWN 1 GiB single via the NAS LAN IP, no tunnel | **hung at 0 bytes, twice** (12:23 and 16:05), killed by hand at the 4-minute bound; see below |

Lane C on the laptop, read-only: its Syncthing is connected to the NAS
directly (`tcp-server` from `192.168.0.102:22000`). Of its 4 folders, one
(`2026-ff5-elections`) reports `needBytes` of 19.97 GB with state `idle` and
a live rate of 0.00 MB/s over 20 s, so there was no lane C transfer to time.
That 20 GB sitting still is an observation for the owner, not a speed
number: a folder that needs 20 GB and is idle is either paused, waiting on
the sequencer's turn, or short of the remote side, and this doc did not
touch it.

Generic-internet baseline on the same Wi-Fi, immediately before and after a
CC Sync-path UP + DOWN pair (same session, Wi-Fi rx/tx/signal beside each
run; the OVH host refuses parallel connections from one address, so the
4-stream rows count only the streams it accepted):

| Run (Wi-Fi 866.7/866.7 Mbps, signal 80 % on every row) | BEFORE (16:24) | AFTER (16:26) |
|---|---|---|
| Singapore, 1 stream, 200 MB, run 1 | 36.3 MB/s | 40.8 MB/s |
| Singapore, 1 stream, run 2 | 45.1 MB/s | 39.5 MB/s |
| Singapore, 1 stream, run 3 | 44.0 MB/s | 37.7 MB/s |
| Singapore, 4 streams, run 1 | 46.3 MB/s (2 accepted) | 51.3 MB/s (2 accepted) |
| Singapore, 4 streams, run 2 | 6.9 MB/s (1 accepted, slow) | 40.9 MB/s (1 accepted) |
| Singapore, 4 streams, run 3 | 44.3 MB/s (2 accepted) | 0 (none accepted) |
| Cloudflare UP 150 MB | 16.6 MB/s | 16.6 MB/s |
| CC Sync path between the two: lane A UP 1 GiB | 76.4 MB/s (14.1 s) | |
| CC Sync path between the two: lane B DOWN 1 GiB | 37.4 MB/s (28.7 s) | |

Wi-Fi-versus-tunnel control against this rig (not the NAS; no SFTP), so
the tunnel's own cost on a Windows Wi-Fi client can be read directly:

| HTTP to/from this rig | Raw LAN (`192.168.0.103`) | Tunnel (`100.74.115.96`, direct over the LAN, 2 ms) |
|---|---|---|
| DOWN 1 GiB, 1 stream, run 1 | 41.3 MB/s | **58.9 MB/s** |
| DOWN 1 GiB, 1 stream, run 2 | 34.3 MB/s | **58.6 MB/s** |
| DOWN 4 x 256 MiB, 4 streams | 14.8 MB/s (two of the four streams stalled at 57 KB/s) | **62.6 MB/s** (all four ran) |
| UP 512 MiB, 1 stream | 38.8 MB/s | **54.3 MB/s** |

Two things stand out. The tunnel is FASTER than the raw LAN on this laptop
(59 versus 34 to 41 MB/s), and raw-LAN TCP to it is flaky: two of four
parallel streams stalled, and the SFTP download from the NAS's LAN address
hung at 0 bytes both times it was tried, while the same download over the
tunnel ran at 35 to 44 MB/s. The tunnel's packets are 1280-byte UDP; the
raw LAN path carries full-size TCP segments through the studio AP, and
the NAS's LAN interface runs jumbo frames (`eno1np0` MTU 9000). That is a
LAN/AP/MTU matter on the raw path, not a CC Sync one (the companion uses
the tunnel), and it is recorded here so nobody reads the LAN control as
the laptop's ceiling. The hung rclone processes were mine, from these
tests, and were the only processes killed on the laptop all day.

Reading the three side by side (single-stream, companion flags, same hour
band; the wired rig's Singapore numbers are from 16:12):

| | Ruskin (remote, internet, direct tunnel, 21 ms) | Razer (studio Wi-Fi, direct tunnel over the LAN, 1 ms) | Wired rig (studio LAN, 2 ms) |
|---|---|---|---|
| lane A UP 1 GiB, companion flags | 6.1 MB/s | 45.7 MB/s | 287 to 315 MB/s (2 GiB) |
| lane B DOWN 1 GiB, companion flags | 15.5 then 13.7 MB/s | 34.7 MB/s | 716 MB/s (2 GiB) |
| generic Singapore, 1 stream | 18.2 MB/s | 36.3 to 45.1 MB/s (6 runs) | 37.6 to 43.6 MB/s (3 runs) |
| generic Singapore, 4 streams | ~57 MB/s (3 of 4 accepted) | 41 to 51 MB/s when 2 accepted | 41 to 44 MB/s (1 to 2 accepted) |
| Cloudflare upload, 150 MB | 6.13 MB/s | 16.6 MB/s (twice; 14.9 at 11:30) | 38.1 MB/s (41 and 64 earlier) |
| tunnel HTTP from this rig, 1 stream | 17.5 MB/s | 58.9 MB/s | (is this rig) |

What the laptop settles: a Windows client on Wi-Fi, through the very same
Tailscale process, the same NAS `tailscaled`, the same sshd and the same
rclone flags, moves 35 to 76 MB/s on the CC Sync path and 59 to 63 MB/s
through the tunnel to this rig, at the same moment its generic internet
download is 36 to 45 MB/s. Every component CC Sync owns therefore
carries more than three times Ruskin's ceiling on a client that shares
nothing with Ruskin except the software. That leaves the internet path
between the studio router and his PC as the only place his cap can live,
which is where section 6a already put it. No verdict in section 1 changes.
## 8. What was measured, raw

All on 2026-09-25 between 10:30 and 11:25 local. MB/s is decimal
(bytes / 1e6 / s) of wall clock including rclone's connect, so a few percent
under rclone's own figure. Companion flags means `--sftp-chunk-size 255Ki
--sftp-concurrency 64 --sftp-connections 16 --checkers 16
--ignore-checksum --transfers 4`.

### Ruskin's PC (remote editor over the internet), 10:38 to 11:07

Windows, Ryzen 7 7700X, Wi-Fi 6E AX210 on a 5 GHz 802.11ax link (721/576
Mbps at start, 681/576 at the end, signal 64 to 75 %), F: is a USB SanDisk
Extreme SSD, companion 0.9.7x running with no rclone in flight, Syncthing
v2.1.5 connected direct to the NAS. `tailscale ping truenas`: direct via
`114.34.8.231:39501`, 21 ms. 20 ICMP pings over the tunnel: 0 lost, 13 to
19 ms. Test files: 1 GiB and 4 x 256 MiB of random bytes in `%TEMP%`, remote
folder `ccsync_bench_tmp` in his SFTP home (on `tank/TheCreatorsPool`), all
deleted afterwards ("remote bench dirs left: 0", local folder gone).

| Test | Time | Rate |
|---|---|---|
| UP 1 GiB, companion flags (1 stream) | 176.0 s | 6.1 MB/s (49 Mbit/s) |
| UP 1 GiB, rclone defaults 32Ki x 64 | 176.1 s | 6.1 MB/s |
| UP 1 GiB, 255Ki x 128 | 176.7 s | 6.1 MB/s |
| UP 4 x 256 MiB, --transfers 4 | 173.5 s | 6.2 MB/s |
| UP 4 x 256 MiB, --transfers 1 | 176.1 s | 6.1 MB/s |
| UP 4 x 256 MiB, --transfers 8, 255Ki x 128 | 174.9 s | 6.1 MB/s |
| DOWN 1 GiB, companion flags (rclone's default multi-thread, 4 streams) | 69.1 s | 15.5 MB/s (124 Mbit/s) |
| DOWN 1 GiB, --multi-thread-streams 0 (1 stream) | 71.8 s | 14.9 MB/s |
| DOWN 1 GiB, --multi-thread-streams 8 | 60.2 s | 17.8 MB/s |
| DOWN 1 GiB, rclone defaults 32Ki x 64 | 57.9 s | 18.6 MB/s |
| DOWN 4 x 256 MiB, --transfers 4 (up to 16 streams) | 55.0 s | 19.5 MB/s (156 Mbit/s) |
| Raw UPLOAD outside the tunnel: 150 MB POST to Cloudflare | 25.6 s | **6.13 MB/s (49 Mbit/s)** |
| Raw DOWNLOAD outside the tunnel: OVH Singapore, 1 stream, 100 MB | 5.5 s | 18.2 MB/s |
| Raw DOWNLOAD outside the tunnel: OVH Singapore, 4 streams x 100 MB | 4.5 to 5.9 s | 22.2 + 17.0 + 18.0 MB/s (one stream failed to start) = **~57 MB/s** |
| Over the tunnel from THIS RIG (not the NAS), HTTP, 1 stream, 20 s | 20 s | 17.5 MB/s (140 Mbit/s) |
| Over the tunnel from this rig, HTTP, 4 streams, 20 s | 20 s | 5.0 + 5.4 + 5.7 + 6.4 = 22.5 MB/s (180 Mbit/s) |

Multi-thread evidence from his `-vv` download: `multi-thread copy: disabling
buffering because destination uses OpenWriterAt` and `Writing sparse files`,
i.e. rclone's default 4-stream download is in effect on lane B for any file
over 256 MiB.

### This rig (base rig, wired LAN with the NAS), 11:15 to 11:25

rclone v1.74.4 (the companion's bundled copy), key auth as the NAS admin,
temp folder `_ccsync_bench_tmp_<pid>` at `/mnt/tank/TheCreatorsPool` (the
pool the tree lives on; outside `Creators_Club` and `homes`), purged
afterwards ("bench dirs left at the pool root: 0"). 2 GiB random file and
4 x 512 MiB.

| Test | Time | Rate |
|---|---|---|
| POOL LAN UP #1, 2 GiB single, companion flags | 7.5 s | 287 MB/s |
| POOL LAN UP #2, 4 x 512 MiB, --transfers 4, back to back | 3.3 s | 645 MB/s |
| POOL LAN UP #3, 2 GiB single again (6 GiB written, past the 4 GiB `zfs_dirty_data_max`) | 6.8 s | 315 MB/s |
| POOL LAN DOWN 2 GiB single, companion flags (multi-thread 4) | 3.0 s | 716 MB/s |
| POOL LAN DOWN 2 GiB single, 1 stream | 7.5 s | 285 MB/s |
| POOL UP 2 GiB single via the NAS's Tailscale IP (direct over the LAN) | 11.2 s | 192 MB/s (1.5 Gbit/s) |
| POOL DOWN 2 GiB single via the NAS's Tailscale IP | 20.0 s | 107 MB/s (859 Mbit/s) |

A first pass of the same matrix (11:07 to 11:12) wrote into the admin's
home by mistake, which is on `boot-pool` (the single SATA SSD), and is kept
only for the two flag comparisons it settles, both of which are about the
wire and the NAS CPU, not the disk:

| Test (boot-pool home, 2 GiB) | Time | Rate |
|---|---|---|
| UP single, companion flags 255Ki x 64 | 6.3 s | 342 MB/s |
| UP single, rclone defaults 32Ki x 64 | 21.8 s | **98 MB/s** |
| UP single, companion flags but WITHOUT `--ignore-checksum` (NAS runs `md5sum` over the file) | 46.0 s | **47 MB/s** |
| DOWN single, multi-thread 4 (default) | 3.1 s | 703 MB/s |
| DOWN single, 1 stream | 9.5 s | 225 MB/s |

Studio line from this rig, outside the tunnel (Cloudflare `__up`):
200 MB single stream 40.9 MB/s; 2 x 300 MB in parallel 35.7 + 28.6 =
**64.3 MB/s (514 Mbit/s)**. Download could not be measured cleanly: the
Cloudflare and Ubuntu endpoints refuse curl (403), OVH Singapore gave
23.6 MB/s on one stream and thinkbroadband (UK) 17 MB/s, both far away and
single-stream.

### The NAS, read-only, 10:35

`truenas`, TrueNAS SCALE 25.10, 2 x Xeon E5-2620 v4 (32 threads), 62 GB
(4.9 GB free, ARC holds the rest), load 0.18/0.34/0.40, 96 % idle, no swap.
`tcp_congestion_control cubic`, `default_qdisc fq_codel`, `tcp_rmem/wmem
4096 1048576 33554432`. `eno1np0` 10 Gbit/s MTU 9000; `tailscale0` MTU 1280.
`tank` raidz1 x 6 WDC WUH721414ALE604 (14 TB SAS); boot SSD SanDisk
SDSSDH3 1 TB. `zfs_dirty_data_max` 4 GiB, `zfs_txg_timeout` 5. sshd
(`/etc/ssh/sshd_config`): `Subsystem sftp internal-sftp`, `Ciphers
+aes128-cbc`, `Compression no`, `PasswordAuthentication no` (per-user
overrides for `truenas_admin` and `ruskin`), `AllowTcpForwarding no`,
`ClientAliveInterval 15`, no `MaxStartups`/`MaxSessions` override (so
`10:30:100` and `10`). Established SSH sessions during the Ruskin run: 2
(his and this rig's); his `sshd` at about 10 % of one core. Syncthing
listening on 22000 tcp and udp. Homes: `ruskin`, `leso`, `alex` under
`/mnt/tank/TheCreatorsPool/homes/`; `truenas_admin` under `/home` on
`boot-pool`.

`tailscale netcheck` from the studio: UDP yes, IPv4 `114.34.8.231`, nearest
DERP Hong Kong 27 ms. From Ruskin: UDP yes, IPv4 `122.100.70.91`, nearest
DERP Hong Kong 75 ms, no captive portal.

### Not changed, not touched

No config, service, scheduled task, Syncthing setting, NAS setting or
companion was changed on any machine. No lane was stopped or paused. Nothing
under `Creators_Club`, `homes/<editor>/` beyond a temp folder that was
purged, or any project folder was written. Ruskin's companion was idle the
whole time (no rclone process before, during or after; `lane_stall.json`
there records an unrelated lane A kill of 2026-09-11, recovered 2026-09-24).
Resolve was not touched on any machine. The only processes started outside
a test were a read-only `rclone serve http` / `serve webdav` of a temp file
on this rig (stopped afterwards), and the laptop's keep-awake, held by the
test scripts themselves through `SetThreadExecutionState` and confirmed
released with `powercfg /requests` at the end. The only processes killed
anywhere were this investigation's own on the laptop: the two `rclone`
LAN-control downloads that hung at 0 bytes, and the PowerShell sessions
that had launched them.

## 9. Related documents

- `bench/README.md`: the `ccbench` harness, which can repeat section 6's
  matrix (`ccbench run`, `ccbench tailscale-check`) once a `bench.toml`
  points at an editor's remote; it was not used on the day because it
  needs a config per machine and the question was narrower.
- `docs/synology-spikes-2026-08-17.md` section on throughput: the same
  flags measured against a Synology, and the SFTP-vs-SMB comparison.
- `docs/SYNC_SAFETY.md`, `docs/UPLOAD_ONLY_TICK.md`: what lanes A and B
  are allowed to do, which is why none of this doc's changes touch their
  `copy`/`sync` shape.
- `docs/TENANCY.md`: the SFTP-only account model that item 3 in section 5
  would depend on.
