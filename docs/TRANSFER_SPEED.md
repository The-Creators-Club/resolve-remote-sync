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
   peer. Confidence high that it is the path, not an endpoint.
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
   about 3x).** Zero code. It is a network problem in one of four places
   (section 6's plan tells which in an afternoon): the studio router's UDP
   NAT path (gateway `192.168.0.1`, MAC `3c:52:a1:85:40:ad`, which is also
   the studio access point), UDP shaping by Ruskin's cable ISP or modem,
   Ruskin's Wi-Fi + Windows Tailscale packet path, or the HiNet to his-ISP
   route for UDP. Risk: none from testing. Effort: an hour of the owner's
   and Ruskin's time each. If it turns out to be the studio router, a router
   with hardware NAT for UDP (or turning that on) fixes every remote editor
   at once.
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

## 7. The Razer (the owner's laptop, on the studio Wi-Fi): partly measured, and one finding

Its read-only state at 11:20: Windows Tailscale direct to the NAS over the
LAN (`192.168.0.102:39501`, 2 ms), Wi-Fi 802.11ac on the studio AP
(`Cablewrap_5G`, channel 161) at 866.7 Mbps both ways, signal 79 %, MediaTek
MT7921, rclone v1.74.4, companion running with no rclone in flight, Ryzen 9
5900HS, CUBIC.

**Its SFTP matrix could not run: the laptop's rclone remote cannot log in
to the NAS at all.** `creators_club_sftp` there is `host = 100.71.216.3`,
`user = alex_laptop`, `key_file = ~/.ssh/ccsync_ed25519`, and every attempt
(its own remote over Tailscale, and the same user over the LAN IP) failed
with `ssh: unable to authenticate, attempted methods [none publickey]`. On
the NAS, `alex_laptop` exists only as a **group** (`alex_laptop:x:3002:`);
there is no such user, the owner's account is `alex` with its home at
`/mnt/tank/TheCreatorsPool/homes/alex`. So the laptop's lanes A and B have
nothing to talk to today. The laptop's key (`~/.ssh/ccsync_ed25519`, made
2026-07-25) is present, and its `companion.log` holds no
"unable to authenticate" or "handshake failed" line at all, so whatever the
tray shows for lanes A and B there, the log does not name the cause. This
is a setup defect to fix (create the account, or point the laptop's remote
and key at `alex`), not a speed matter, and it was not touched here.

What did measure, over the studio Wi-Fi, outside the tunnel:

| Test | Rate |
|---|---|
| Raw UPLOAD, 150 MB POST to Cloudflare | 14.9 MB/s (119 Mbit/s); the wired rig got 41 MB/s on the same test |
| Raw DOWNLOAD, OVH Singapore, 1 stream, 100 MB | 17.3 MB/s |
| Raw DOWNLOAD, OVH Singapore, 4 streams | 14.8 + 9.0 + 9.6 MB/s (one stream failed to start) = about 33 MB/s |

So a Wi-Fi client of the studio router reaches the internet at roughly a
third of what the wired rig gets on the same line, which is worth keeping
in mind for section 6 step 2 and 3: on this Wi-Fi the laptop would not be
able to prove much above 250 Mbit/s either way.

The Wi-Fi-versus-Wi-Fi-plus-tunnel control (pulling a file from this rig
over `192.168.0.103` and then over `100.74.115.96`, no NAS login needed) was
prepared, but the laptop dropped off the network twice in fifteen minutes
(Tailscale "offline", no answer on `192.168.0.112`), so it did not run. Two
scripts sit ready for the next time it is awake at the studio: `rz_http.ps1`
(the control above, 2 minutes, nothing on the NAS) and `rz_bench.ps1` (the
full section 6 matrix, 8 minutes, once its NAS login works).

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
Resolve was not touched on any machine. The only process started outside a
test was a read-only `rclone serve http` on this rig's tailnet address for
40 seconds, stopped afterwards.

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
