# Client delivery — handing a client terabytes of footage to download once

*Written 2026-09-08. Owner's ask: "the quickest and fastest way to give a
client access to download certain folders of our footage from our NAS, without
them joining our tailnet." The case that shaped it: several terabytes, one
download, studio in Taiwan, client on the US east coast, 500 Mbps at both
ends.*

This is a runbook, not a feature. Nothing in the product does this; the
dashboard's client-folders link (`CLIENT_FOLDERS.md`) is previews only, with
no download by design, and rides Tailscale Funnel, which is relayed and
bandwidth-limited. Delivering masters is a separate job and this is how to do
it.

Contents: [1. Choosing the route](#1-choosing-the-route) · [2. The Backblaze
route, step by step](#2-the-backblaze-route-step-by-step) · [3. What to tell
the client](#3-what-to-tell-the-client) · [4. Direct route: a shared Tailscale
node](#4-direct-route-a-shared-tailscale-node) · [5. Why not the others](#5-why-not-the-others)
· [6. Numbers](#6-numbers)

---

## 1. Choosing the route

The speed ceiling is the slower of the studio's upload link and the client's
download link. Cost is not the deciding factor at any size below tens of
terabytes. The two things that decide it are **distance** and **who has to
install what**.

| Situation | Route | Section |
|---|---|---|
| Client far away (another continent), any size | **Stage a copy in Backblaze B2**, region near the client | §2 |
| Client nearby, both links good, client can install one app | Share the NAS as a Tailscale node, rclone over SFTP, one hop | §4 |
| Either link slow, or nobody technical on the client side | Ship a drive | §5 |
| Under a few hundred GB, one-off, no setup wanted at all | MASV | §5 |

**Why distance decides it.** Taiwan to the US east coast is about 220 ms
round trip. A single TCP stream over that latency, with the packet loss a
trans-Pacific path always has, settles at tens of megabits whatever the two
links are rated. A direct SFTP session moves each video file as one stream,
so a folder of 50 GB originals crawls. Every route that works over distance
moves many chunks in parallel. Staging in a bucket does that on both legs:
the upload is chunked and parallel by construction, and the client's pull
comes from a data centre a few milliseconds away, where a plain download runs
at line speed with no flags.

## 2. The Backblaze route, step by step

### 2.1 One-time: the Backblaze account

1. Sign up at backblaze.com for **B2 Cloud Storage**.
2. **Pick the data region at signup and pick it for the client, not for us.**
   Backblaze fixes the region per account and every bucket in the account
   lives there; it cannot be changed later. For a US east-coast client that
   is **US East (Reston)**. Our upload is parallel and does not care about
   latency; the client's download does. A studio delivering to both coasts
   and to Europe is better served by one account per region than by one
   account.
3. In **Account → Caps and Alerts**, set a monthly spending cap. A few
   terabytes for a month is tens of dollars; a cap of twice that stops a
   mistake (a bucket forgotten for a year) from becoming a bill.
4. Under **Billing**, note the egress allowance: free up to three times what
   is stored in the month, then $0.01/GB. A client downloading once uses a
   third of it.

### 2.2 Per delivery: the bucket and two keys

1. **Buckets → Create a Bucket.** Name it for the client and the job
   (`cc-<client>-<job>-2026-09`), **Private**, encryption off (the files are
   the client's to read; encryption here only complicates their download).
2. **Lifecycle Settings on the bucket → "Keep only the last version of the
   file".** The default keeps every version of every file forever, including
   deleted ones, and a "deleted" bucket that still bills for its versions is
   the classic Backblaze surprise.
3. **App Keys → Add a New Application Key**, twice:
   - **Upload key** for the NAS: `<client>-upload`, *Allow access to Bucket(s)*:
     this bucket only, *Type of Access*: **Read and Write**, no prefix, no
     duration. This one stays on the NAS and is deleted with the bucket.
   - **Client key**: `<client>-download`, this bucket only, *Type of Access*:
     **Read Only**, *Duration*: the number of days the client has to fetch
     it (30 is reasonable; the key stops working by itself after that, which
     is the revocation nobody has to remember). This is the only credential
     the client ever holds. A read-only key cannot list other buckets, write,
     or delete.

   The key secret is shown **once**, at creation. Paste it straight into the
   place it is going (§2.3 or §3); a lost secret is a new key.

### 2.3 Upload from the NAS

Two ways. The TrueNAS UI is the one to use: it runs in the background as a
task, survives an SSH session dropping, and shows progress in the UI.

**A. TrueNAS Cloud Sync task (recommended).**

1. **Credentials → Backup Credentials → Cloud Credentials → Add**: Provider
   *Backblaze B2*, the upload key's ID and secret, *Verify Credential*, save.
2. **Data Protection → Cloud Sync Tasks → Add**:
   - Direction **Push**, Transfer Mode **Copy** (never *Sync*: sync deletes
     from the destination whatever is missing from the source, and a typo in
     the source path against a half-uploaded bucket is a rollback of the
     upload; copy only ever adds).
   - Directory/Files: the folder(s) to deliver, under
     `/mnt/tank/<pool>/<tree>/Projects/...` (the tree from `site.toml
     [tree]`). One task per top-level folder is fine.
   - Remote bucket: the bucket; folder: blank or `<job>/`.
   - Schedule: anything; you will run it by hand. Untick *Enabled* if you do
     not want it to also fire on the schedule.
   - **Advanced Options → Transfers: 16.** This is the whole trick for the
     Pacific. The default is 4 and will leave most of the link idle.
   - Leave *Follow Symlinks* off, *Use --fast-list* on, bandwidth limit
     blank (the point is to fill the link; do it overnight or over a weekend
     if editors need the uplink by day).
3. Save, then **Run Now** from the task's row. The row shows RUNNING with a
   progress log; **Cloud Sync Tasks → the task → Logs** has rclone's own
   output if it stalls.
4. When it says SUCCESS, **run it once more**. The second run finds nothing
   to transfer and finishes in minutes; that is the check that every file
   arrived with the size and checksum Backblaze recorded. If the second run
   transfers anything, the first run missed it and the third run is the
   check.

**B. rclone from the NAS shell.** For when the UI is unavailable or the
transfer needs flags the UI does not expose. TrueNAS SCALE ships rclone for
its own Cloud Sync tasks (`which rclone`); if it is missing, the static
binary from rclone.org unpacked under `/mnt/tank/apps/tools/` works, since the
root filesystem is not writable on SCALE. Run it under `tmux` so a dropped SSH
session does not kill a 22-hour transfer.

```sh
# on the NAS, as truenas_admin (the operator channel from docs/SERVER.md)
rclone config create b2-<client> b2 account <UPLOAD_KEY_ID> key <UPLOAD_KEY_SECRET>
tmux new -s deliver
rclone copy "/mnt/tank/<pool>/<tree>/Projects/<project>/<folder>" \
    "b2-<client>:cc-<client>-<job>-2026-09/<folder>" \
    --transfers 16 --checkers 16 --fast-list \
    --b2-chunk-size 96M --b2-upload-cutoff 200M \
    --progress --log-file /mnt/tank/apps/tools/deliver-<client>.log --log-level INFO
# detach: Ctrl-b d ; return: tmux attach -t deliver
```

The verification run is the same command again with `--checksum`; a clean
second pass prints `Transferred: 0 B` and nothing under `Errors:`. Remove
the remote afterwards (`rclone config delete b2-<client>`): the upload key
must not outlive the delivery on the NAS.

**How long.** 5 TB at 500 Mbps is about 22 hours. The Backblaze large-file
API takes 16 parallel chunks without complaint; the sustained rate on a
500 Mbps line should sit at 55 to 60 MB/s in the task log. Well under that
with 16 transfers means the uplink is shared with something (lane A from the
fleet, a Syncthing rescan) or the ISP is shaping; the fix is timing, not
flags.

### 2.4 After the client confirms

1. **Delete the client key** (App Keys → the key → Delete), even if it had a
   duration.
2. **Empty and delete the bucket** (Buckets → the bucket → Delete; a bucket
   with files refuses, so *Browse Files → select all → Delete* first, and
   with the lifecycle rule from §2.2 the versions go too).
3. Delete the upload key and the TrueNAS cloud credential.
4. Check the next Backblaze invoice: storage should drop to the free 10 GB.
   Storage is billed hourly, so the day the bucket goes is the day the meter
   stops.

There is no copy of the footage anywhere but the NAS again.

## 3. What to tell the client

The client needs three strings, sent by a channel that is not the one the
bucket name went by (a bucket name plus a key ID plus a secret in one email
is one credential): the **key ID**, the **key secret**, the **bucket name**.
Then one of these, easiest first.

**Cyberduck** (free, Mac and Windows, no command line). *Open Connection →
Backblaze B2*, Account ID = key ID, Application Key = secret. The bucket
appears; select the folder, right-click **Download To…**. In *Preferences →
Transfers → General* set **Transfers: 8** and under *Backblaze B2*
**Segmented downloads** on; those two settings are the difference between a
line-speed pull and a crawl for large files. Cyberduck resumes an interrupted
transfer from the same dialog.

**rclone** (for a client with a technician; fastest and verifiable).

```sh
rclone config create cc b2 account <KEY_ID> key <KEY_SECRET>
rclone copy cc:<bucket> "D:\Delivery\<job>" \
    --transfers 8 --multi-thread-streams 4 --checkers 16 --fast-list --progress
rclone check cc:<bucket> "D:\Delivery\<job>" --one-way   # prints "0 differences" when every byte is there
```

**The Backblaze website** works but downloads one file at a time through the
browser, which for a footage folder of a few thousand files is not an
option. Point them at Cyberduck.

Tell them the key expires on a date (from §2.2) and that the folder comes
down with the same structure it has on the NAS, so a Resolve project
relinked to it needs only the root changed.

## 4. Direct route: a shared Tailscale node

For a client that is close (same continent, ideally same coast) and can
install Tailscale, one hop beats staging: no copy to make or delete, and the
transfer starts the moment the account exists. It is the route that keeps
the 2026-08-17 decision fully intact: still Tailscale, nothing on the
router, no DDNS.

**Node sharing is not tailnet membership.** In the Tailscale admin console,
*Machines → the NAS → Share…* produces an invite link. The client accepts it
with their **own** Tailscale login (Google, Microsoft, GitHub, whatever they
have; a free personal account is enough). They get no seat on our tailnet,
see no machine but the NAS, and appear to our ACLs as `autogroup:shared`.

Before sharing, the ACL must say what a shared user may reach, and it must
be **port 22 only**:

```jsonc
{ "action": "accept", "src": ["autogroup:shared"], "dst": ["<nas-tailnet-ip>:22"] }
```

Without that line a shared user reaches nothing (Tailscale default-denies
shared users), which is the safe failure. With a wider line they would reach
the dashboard's login page on 443 and the Syncthing GUI, which is admin over
every fleet folder. Check `tailscale serve status` is not publishing anything
on a port that line would open.

On the NAS, a chrooted read-only SFTP account on just the delivery folders.
`server/setup_editor_account.py` makes editor accounts on the same shape
(`ForceCommand internal-sftp`, chroot to a home, `docs/TENANCY.md` §"sftp-only")
and is the model; a client account differs in being read-only, under a
different group so the editors' `Match Group` block does not apply, and in
its chroot being a directory holding **bind mounts** of the delivery folders
(a chroot root must be root-owned and not writable, so it cannot be the
project folder itself). Nothing in `server/` scripts that today; it is a
short manual job for one client and a script the day there is a second.

The client then runs rclone against `sftp://<nas-tailnet-ip>` with
`--transfers 8 --multi-thread-streams 4 --sftp-concurrency 64
--sftp-chunk-size 255k` (the same two SFTP values the fleet's `site.toml
[net]` carries, and for the same reason). Both machines must stay up for the
whole transfer; rclone resumes per file, not mid-file, so a dropped 50 GB
original starts over. Delete the account and the node share when they
confirm.

## 5. Why not the others

- **Tailscale Funnel.** Relayed through Tailscale's ingress servers and
  documented as bandwidth-limited; fine for the client-folders previews it
  carries today, not a channel for terabytes. `CLIENT_FOLDERS.md` §3.3.
- **A router port-forward or a public SFTP.** The raw fastest and the door the
  2026-08-17 decision closed: no public exposure of the NAS, because the
  login page is the dashboard's only gate. Not re-opened for a delivery.
- **Syncthing send-only folder.** It is "sync these folders" exactly and the
  NAS already runs it, but the client must install Syncthing and exchange
  device ids, the speed is whatever hole-punching yields (relay fallback is
  a few MB/s and you cannot tell in advance), and their device becomes a
  peer of the fleet's Syncthing instance. For a repeat client, a **second**
  Syncthing on the NAS just for clients would make it acceptable; for a
  one-off it is the wrong tool.
- **MASV** (or WeTransfer Pro, Frame.io Transfer). Zero setup on either end
  and genuinely the right answer below a few hundred gigabytes; at roughly
  $0.25/GB, 5 TB is over a thousand dollars.
- **Ship a drive.** For multi-terabyte one-offs with a slow link at either
  end, or a client with nobody to run a download, this is still what post
  houses do: an 8 TB USB drive costs about what a month of Backblaze does,
  fills in a few hours from the NAS over SMB, and a courier crosses the
  Pacific in two to three days. exFAT so either OS reads it; a
  `sha256sum`/`Get-FileHash` manifest on the drive so they can verify.

## 6. Numbers

| | |
|---|---|
| Backblaze storage | $6 per TB per month, billed hourly |
| Backblaze egress | free up to 3x stored per month, then $0.01/GB |
| Cloudflare R2, for comparison | $15 per TB per month, egress free; only cheaper when the same bytes are pulled many times |
| 5 TB, one month, one download, on Backblaze | about $30 |
| 5 TB at 500 Mbps, one leg | about 22 hours |
| 5 TB at 100 Mbps, one leg | about 5 days |
| Taiwan to US east, round trip | about 220 ms |
| MASV, 5 TB | over $1,000 |

Prices as published 2026-09-08; check the pricing pages before quoting a
client.
