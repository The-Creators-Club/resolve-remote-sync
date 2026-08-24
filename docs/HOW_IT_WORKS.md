# How CC Sync works

A plain-English guide for production company owners, producers and editors.
It explains what the product is, what each piece does, what you will see day
to day, and what to do when something looks wrong. Nothing here requires you
to be a developer. Where a term is used for the first time, it is explained
first; there is also a glossary at the end.

CC Sync is a companion for DaVinci Resolve Studio. DaVinci Resolve is a
product of Blackmagic Design, licensed to you separately by them; CC Sync is
not affiliated with, endorsed by or sponsored by Blackmagic Design.

---

## 1. The problem it solves

A video production company usually keeps its footage in one place: a storage
server in the office. Everyone who edits in the building works straight off
it. The trouble starts when an editor is not in the building.

Camera originals are huge. Mirroring a whole project to every editor's home
machine would take days and fill every drive. Resolve makes this worse in a
specific way: it remembers the exact path of every clip (for example
`P:\Projects\2026\Series\Episode\B-roll\clip.braw`). If the same project is
opened on a computer where that path does not exist, every clip shows as
"Media Offline".

CC Sync solves this with three ideas working together:

1. **One canonical folder tree**, held on your storage server, which every
   machine sees at the same path spelling. On Windows that is the `P:` drive.
   On a Mac, Resolve is told that `P:\` means your local sync folder.
2. **Each editing computer syncs only a slice of the tree**: the projects it
   has been assigned, and for video, only small proxy copies rather than the
   originals. Anything the editor adds goes back up automatically.
3. **A small helper app on every machine** (the CC Sync companion, which lives
   in your system tray or menu bar) that watches Resolve, fixes paths, copies
   stray media into the right place, reports health to a dashboard, and
   refuses to do anything dangerous.

The result is that an editor at home opens the shared project, the clips play
from local proxies, the things they add appear for everyone else, and the
team admin can see from one web page whether everybody's footage is syncing.

---

## 2. The pieces

### 2.1 The NAS (your storage server)

A NAS (network-attached storage) is a box of hard drives with its own small
operating system, reachable over the network. CC Sync supports two makes:
TrueNAS SCALE and Synology DSM. The NAS holds:

- the canonical project tree (the one true copy of everything),
- the dashboard (a small web application running in a container on the NAS),
- the sync engine services that editors' machines talk to,
- Resolve's own shared project library (the Resolve Project Server), which is
  Blackmagic's feature and runs alongside CC Sync. CC Sync handles the media;
  Resolve handles the project database.

The NAS also takes regular snapshots of the tree (see section 8), so that
"somebody deleted a folder" is a restore, not a disaster.

### 2.2 The dashboard

The dashboard is a web page served from the NAS. Every editor signs into it to
choose which projects their computer should hold and to see how their sync is
going. The team admin uses it to see the whole fleet, manage people and
machines, publish updates, and stop everything in an emergency. The b-roll
library, the music library and (if switched on) the YouTube downloader all
live inside the dashboard as extra tabs.

### 2.3 The companion (the tray app)

The companion is a small program installed on every editing computer. On
Windows it sits in the system tray next to the clock; on a Mac it sits in the
menu bar. Right-click (or click) it for a menu. It:

- runs the three sync lanes (section 4),
- watches the open Resolve timeline and offers to fix media that lives
  outside the synced tree,
- repairs stale proxy links and keeps the shared LUT library visible to
  Resolve,
- reports status to the dashboard about once a minute,
- receives updates, halts and resume requests from the dashboard,
- provides the local "Send to Resolve" bridge that the b-roll and music
  pages use.

It requires DaVinci Resolve Studio. The free edition of Resolve does not
expose the scripting interface the companion relies on, so with the free
edition the sync lanes still run but nothing that touches Resolve does.

### 2.4 Wired machines and remote machines

Every computer that runs the companion is registered as one of two kinds.
The setup wizard asks this on its first page.

| Kind | What it means | What syncs |
|---|---|---|
| **Physically connected (wired)** | The computer is in the office and reaches the NAS directly, so its `P:` drive *is* the NAS share | Nothing. It edits straight off the server. It is also usually the machine that makes proxies and runs the heavy indexing jobs |
| **Remote editor** | The computer is anywhere else and holds its own local copy of its assigned projects | The three lanes run; `P:` points at the local copy |

A site can have several wired machines and one person can own both kinds
(an office desktop that is wired, a laptop that is remote) under one account.
The role belongs to the computer, not the person.

### 2.5 Tailscale (the private network)

Your NAS is not on the public internet and should never be. Tailscale is a
service that creates a private, encrypted network (a "tailnet") between
devices you enrol, wherever they physically are. Each editing computer and
the NAS join the tailnet once; from then on the editor's machine can reach
the NAS as if it were on the office network, and nobody else can.

Everything in CC Sync travels over the tailnet: sync traffic, the dashboard,
Resolve's project database. There is one deliberate exception, the client
preview links in section 9.4.

### 2.6 Resolve itself

Resolve is unchanged. Editors connect to the shared project library as they
normally would and set **Playback > Proxy Handling > Prefer Proxies** once,
so that a clip whose original is not on their machine plays from the proxy.
Wired machines are set the opposite way because they hold everything.

---

## 3. The project tree

The tree is one folder on the NAS, mapped to `P:` on every Windows machine.
Inside it:

```
P:\
  Projects\
    2026\
      Series name\
        Episode name\          <- one project
          AE\
          Audio\Music\
          Audio\Voiceover\
          B-roll\
            Proxy\             <- proxies for the clips next to it
          Interviewees\
            Proxy\
          Render in Place\
          Subs\
          Youtube\
  Assets\
    Luts\                      <- shared LUT library, everyone gets it
    Stills\                    <- shared Resolve gallery stills
    B-roll Archive\            <- the searchable b-roll library
    Music\                     <- the searchable music library
```

Three things about this layout matter:

**Projects can sit at any depth.** Year, series, season, client: organise the
containers however you like. A folder is a project because it carries a small
hidden marker file the admin's tools put there, not because of where it sits.
New projects simply appear in the dashboard's list, ready to be ticked.

**Every folder of video has a `Proxy` subfolder next to it.** This is the
convention Resolve and Blackmagic's Proxy Generator already use to link a
proxy to its original automatically. CC Sync is built around it: the
`Proxy` folders are what travel down to remote editors.

**The template folders are your organisation's.** The list above is the
default; your admin can set a different list per site. The `Assets`
libraries are fixed by the product.

**Sharing a folder between two projects.** Sometimes one folder genuinely
belongs to two projects: an interview shot for one episode and reused in
another. Copying it doubles the storage and the two copies drift apart the
moment anyone renames or deletes one side. Instead, a project can *borrow* a
folder from another project: on the borrowing project's dashboard page,
[ SHARE A FOLDER INTO THIS PROJECT ] takes the folder's path (for example
`2026/FF5/Elections/Interviewees/...`). From then on, everyone syncing the
borrowing project also receives that folder, at its original path, through
the same three lanes; nothing is copied and nothing needs relinking in
Resolve. The project page lists what a project shares from others (and what
is shared out of it), and a red [ LINK ] chip in the sidebar means one of
those declarations needs attention. Whole projects cannot be borrowed (tick
both projects instead), and `Proxy` folders cannot be borrowed directly
(share their parent).

---

## 4. The three sync lanes

"Syncing" here means: the companion compares the NAS copy and the local copy
of your assigned projects and moves files until they agree, in a direction
that depends on what kind of file it is. Not every file goes both ways, and
that is the whole design.

| Lane | Direction | What it carries | Engine | Safety rule |
|---|---|---|---|---|
| **A: originals up** | your machine to the NAS | video originals you add, outside any `Proxy` folder | rclone over SFTP | **Never deletes anything on the NAS.** Skips a file that already exists there |
| **B: proxies down** | the NAS to your machine | only the contents of `Proxy` folders | rclone over SFTP | Mirrors the NAS exactly, so it can delete locally. Guarded by the circuit breaker (section 8.1) and a local trash folder |
| **C: everything else, both ways** | both | project files, audio, graphics, After Effects comps, subtitles, documents, stills, LUTs | Syncthing | Deletions are not applied to other machines; the NAS keeps 30 days of old versions |

What this means in practice:

- Video you add to a project uploads automatically. Other editors do not
  receive your original; they receive its proxy once one has been made
  (section 6.4).
- Proxies for everything in your assigned projects download to you.
- Small files (music cues, voiceover, subtitles, AE comps) flow both ways
  within a minute or two.
- If you rename or move a video file locally, the NAS gets a second copy
  under the new name and keeps the old one. Lane A never tidies up. Ask the
  admin to reorganise on the server side.
- If you re-export a video under the same name as one already on the NAS,
  lane A skips it, because the first version of a name is the only one it
  will ever upload. The tray and the dashboard show a "won't upload" warning
  naming the file. Rename it, or have the admin remove the server copy.

### 4.1 Your sync plan belongs to a computer

A sync plan is the list of projects a particular computer holds. It belongs
to the computer, not to you. If you have a desktop and a laptop, each has its
own plan, and a new computer starts with **nothing** ticked, on purpose:
nobody wants a laptop to start pulling 50 GB because a desktop had it.

- On the dashboard's main page, the checkboxes in the sidebar are for **you as
  a person**: ticking there means "every computer I use". Unticking there
  removes the project from all of them.
- The per-computer lists are on **Settings > Assignments**, a grid of projects
  against machines. Each machine column has a "copy from" box so the admin
  can hand a new laptop another machine's plan in one click.
- Projects sync **one at a time, in the order they were ticked**, each taking
  a turn of up to about ten minutes before the next one gets a go. A big
  project high on the list does not block a small one below it forever.
- Unticking stops new transfers. Files already on your disk stay until you
  remove them (the tray has a gated "remove from this machine" action; see
  section 8.4).

A wired machine cannot be ticked at all. It syncs nothing, so a tick would
mean nothing, and the dashboard says so.

---

## 5. Day one for a new editor

What a new editor goes through, from an empty computer to a playing timeline.

1. **Before you start.** DaVinci Resolve Studio installed and activated, with
   *Preferences > System > General > External scripting using* set to
   **Local**. A drive with real headroom for the local sync folder: every
   proxy and everything you add lands there. On a Mac this is normally the
   external SSD you edit from.
2. **Get the installer.** The admin sends you the dashboard address and a
   username and password. Open the dashboard in a browser, sign in, and
   download the installer for your platform from the menu's [ INSTALLER ]
   entry.
3. **The wizard.** The installer is a four-step wizard:
   - *Step 1: How is this machine connected.* "I'm a remote editor" or "I'm
     physically connected to the server/NAS".
   - *Step 2: Join the network.* It installs Tailscale if needed and opens
     the browser for you to sign in to your organisation's tailnet.
   - *Step 3: Sign in.* Your CC Sync username and password.
   - *Step 4: Install.* You choose the local sync folder. The wizard installs
     the sync engines and the companion, maps `P:` (Windows) or sets
     Resolve's mapped-mount preference (Mac), and starts the tray app. It is
     safe to run again; every step checks what is already done.
   Before any of that, the wizard shows the licence agreement. Syncing will
   not start on a machine where it has not been accepted; if you ever see
   "Accept the licence agreement to start syncing" in the tray, click it.
4. **Sign in at the tray.** If the wizard did not do it for you, right-click
   the tray icon and choose **Sign in**. Until the menu says "Signed in as
   you", nothing syncs and the admin cannot see your machine. This is
   deliberate: the companion does nothing until it knows who you are.
5. **The admin approves your machine.** The first time your machine's sync
   engine contacts the NAS it shows up as a pending device; the admin
   approves it once. Until then lane C (the both-ways lane) waits.
6. **Tick your projects.** In the dashboard, tick the projects this computer
   should hold (or the admin does it from the Assignments grid). Within a
   minute or two the tray shows the first project syncing, with speed and
   files remaining. The companion first recreates the project's folder
   skeleton locally, then pulls proxies, then lets the both-ways lane carry
   the small files.
7. **Connect Resolve** to the shared project library the way the admin
   describes (server address, port, username, password), set **Prefer
   Proxies**, open a timeline. Clips stored as `P:\Projects\...` play from
   your local proxies without a relink prompt. If Resolve asks you to locate
   a file, the mapping is not right yet; tell the admin.

**Mac editors, two extra notes.** There is no `P:` drive on a Mac and there
never will be; Resolve's mapped mount translates `P:\` to your sync folder,
and the wizard sets it while Resolve is quit. Unplugging the SSD is fine: the
companion pauses every lane, the icon goes orange, and syncing resumes on its
own when the drive returns.

**Do not map any NAS share to a drive letter of your own.** If a letter you
map collides with a path stored in the shared project database, Resolve will
silently stream full-resolution originals over the network instead of using
your proxies. It produces no error, it just feels inexplicably slow.

---

## 6. A day in the life of an editor

### 6.1 Opening Resolve

Nothing to do. The companion notices Resolve is running and starts watching
the current timeline every few seconds. If Resolve's scripting server is
down, the companion says so in a dialog every few minutes, because it is the
one failure you cannot otherwise see.

### 6.2 The popup

Drag a clip onto the timeline from your Desktop, a download folder or a
camera card, and within a few seconds a CC Sync window appears listing the
clip (or clips) that live outside the synced tree. For each one it suggests a
destination inside the current project (audio to `Audio\Music`, video to
`B-roll`, and so on), which you can change.

- **FIX ALL** copies each file into the tree, relinks the clip in Resolve to
  the new location, and queues the upload. Originals are **copied, never
  moved**; delete the old copy yourself once you are happy. There is a live
  progress bar per file, and the X during a copy means stop, not hide.
- **IGNORE** hides those clips for this session only. They will be offered
  again next time.

The popup only looks at the current timeline. For media you imported into
bins but have not cut in yet, use **Advanced > Scan whole project** in the
tray menu.

### 6.3 Bringing in a project you started before CC Sync

**Advanced > Bring an existing project's media into the synced folder** scans
the whole media pool, shows a report of how much will be copied and uploaded,
and on your confirmation copies every out-of-tree clip into the project,
relinks Resolve, uploads the originals and pulls any proxies. Again: copies,
never moves.

### 6.4 Proxies

A proxy is a small, easy-to-play copy of a camera original (here, H.264 at
1080p or below) with the same name and timecode, stored in the `Proxy`
folder next to the original. Resolve links them automatically.

Where proxies come from:

- **A wired machine** makes them. Blackmagic's Proxy Generator can watch the
  tree there, and the companion on a wired machine also fills gaps itself
  with ffmpeg, but **only while nobody is using the computer**: it waits for
  idle time and stops within a couple of seconds when someone comes back.
  The tray shows "Proxies this machine has made" and progress.
- **Remote machines** do not make proxies for others. When you upload an
  original, the tray says how many clips are waiting for a proxy, and other
  editors see your clip once the proxy has come back down to them. This can
  take minutes or hours depending on the queue.

If a project arrives carrying stale proxy paths from another machine (for
example a drive letter that never existed on yours), the companion repoints
them to the local `Proxy` folder automatically. Every such change is
journalled so it can be undone (section 8.5).

### 6.5 LUTs and stills

`P:\Assets\Luts` is a shared LUT library that every machine receives without
ticking anything. The companion adds it to Resolve's list of LUT locations
(you can see it in *Preferences > System > General > LUT Locations*). Drop a
LUT into Resolve's own LUT folder as you always have and the tray will offer
"N LUTs only on this machine: share with the team", which copies them into
the library after a confirmation naming them. If Resolve was launched before
`P:` was ready, it may not list the library until its LUT list is refreshed;
the companion detects that from Resolve's own log and refreshes it for you.

`P:\Assets\Stills` does the same job for Resolve's gallery stills.

### 6.6 The rest of the tray menu

| Menu item | What it does |
|---|---|
| Sync now | Start the next pass immediately |
| Pause syncing | Stop the upload and proxy lanes (the both-ways lane keeps running); for a laptop on a hotspot |
| Open my project folder | Explorer or Finder at your local tree |
| Open dashboard | The web page, in your browser |
| Grade from server originals (swap P:) | Windows only: temporarily point `P:` at the NAS share so Resolve plays full-resolution originals over the network for a grading session, then swap back. Sync is unaffected |
| Copy diagnostics for your admin | Puts a status summary on the clipboard to paste into a message |
| Open log | The companion's own log file |
| Advanced | Scan whole project; bring an existing project's media in; undo the last clip-path change; stop all syncing on this machine |
| Quit CCSync | Stops syncing until you next sign in |

### 6.7 Shutting down

Uploads cannot resume part-way. If you shut down with a file half-sent, the
companion warns you and the file starts again from zero next time. While a
lane is busy the companion also keeps the machine from sleeping.

---

## 7. What the team admin sees and does

| Dashboard page | What it is for |
|---|---|
| **Sync status** (the front page) | Every project with a health dot; per project, each editor and machine, how complete it is and what is missing. The sidebar ticks are here |
| **Transfers** | Live queue: what is moving right now, speed, ETA, what is queued and what is still "getting ready" |
| **Fleet** grid | One row per machine: online, version, lane states, and the coloured chips that mark an unusual state (breaker tripped, halted, indexing, needs proxies, will not upload). A [ RESUME ] button appears beside a tripped machine |
| **Settings > Users** | People, their machines, approving a new machine's sync device, per-editor tokens, active sessions, the **fleet sync halt** |
| **Settings > Assignments** | The project-by-machine grid with "copy from" |
| **Settings > Packages** | Published companion builds, which one is current, [ UPDATE NOW ] per out-of-date machine, and the vendor's release feed |
| **Settings** (site) | The organisation's name, addresses, feature switches, AI provider keys for optional features |
| **Project setup** | Create a new project folder from the template, straight from the browser |

Admins see everything; editors see their own projects, machines and
transfers only.

---

## 8. Safety features, in plain terms

A sync engine's worst failure is deleting the customer's footage. Several
independent latches exist so that no single mistake, on any machine, can do
that. All of them prefer to stop and ask a human rather than guess.

### 8.1 The lane B circuit breaker

Lane B is the one lane that removes local files, because it mirrors the NAS
proxy folders. If the NAS briefly looks empty (a pool still importing, a
share not mounted, a project unshared by mistake), a naive mirror would
delete every proxy on your machine to match. The breaker stops that.

It trips, **before anything is deleted**, if the NAS no longer looks like the
tree, lists a project as empty that was not empty before, or has shrunk by
more than half. It trips **after** a pass if that pass removed more than a
handful of files or more than a quarter of your proxies. It also trips on a
slow leak over several passes. Before tripping it first checks whether the
files were simply *moved* on the NAS rather than deleted, which is not an
alarm.

**What you see.** The tray line reads "PROXY DOWNLOAD STOPPED (safety)" with
the reason, and a red chip appears on the admin's fleet grid. Lanes A and C
keep running: your uploads and the shared files are unaffected.

**What to do.** Tell the admin. Once they have confirmed the NAS is healthy,
either they click [ RESUME ] beside your machine on the fleet grid, or you
choose **Resume proxy download** in the tray and confirm. Nothing clears it
automatically, on purpose: a trip is precisely the moment somebody should
look.

### 8.2 The local trash

Everything lane B removes goes first into a `.ccsync-trash` folder at the top
of your local tree, in a subfolder named by date and time. It is kept for 14
days or until it exceeds 50 GB (oldest batches go first, never the newest),
and nothing is pruned while the breaker is tripped. If a proxy vanished, look
there.

### 8.3 The halt

**Pause is not stop.** Pause leaves the both-ways lane running. The halt
stops every lane on a machine, including the both-ways one, and survives a
restart.

- **Local:** tray > Advanced > *Stop ALL syncing on this machine*. You clear
  it yourself with *Start syncing again*.
- **Fleet-wide:** the admin sets it on Settings > Users with a mandatory
  reason. Every companion stops within about a minute and shows the reason
  in its tray. A machine that is off adopts it when it comes back. Editors
  cannot release a fleet halt; the admin releases it from the same panel. It
  exists for "something is destroying files and I do not yet know which
  machine".

### 8.4 Delete protection and removal gating

- On the both-ways lane, **a deletion is never applied to another machine**.
  Delete a music cue by accident and it disappears from your disk only; the
  NAS and every other editor keep it. The NAS also keeps 30 days of old
  versions of every file that lane carries. Two people editing the same small
  file at once produces a conflict copy rather than a silent overwrite, and
  the tray points it out.
- Deleting a whole project folder locally does not propagate: the sync engine
  sees its marker file is gone and stops that folder instead.
- **"Remove from this machine"** for a project first asks both outbound lanes
  whether anything of yours has not yet reached the NAS. If it cannot get an
  answer, it refuses. An override exists for a dead NAS and a full disk, but
  it requires typing the project's folder name, and it is reported to the
  admin.

### 8.5 The undo journal for Resolve edits

The companion changes clip paths inside Resolve from a few places: FIX ALL,
the automatic repointing of stale proxy paths, and the relinking of clips
that arrive with another machine's drive letter. Resolve's own Undo does not
cover scripted changes, so before any of them the companion saves the
project, exports a rollback copy of it, and writes a journal naming every
clip's old and new path.

**Tray > Advanced > Undo the last clip-path change CCSync made** replays the
newest journal in reverse and reports, for example, "Put 158 clip path(s)
back the way they were". If that is not enough, the exported project copy can
be imported into Resolve's Project Manager as a separate project, alongside
the current one, so nothing is overwritten. Journals are kept for 60 days and
never leave your machine.

### 8.6 Snapshots on the NAS

Your local copy is a replica, not a backup. The NAS takes snapshots of the
tree and of the dashboard's own data: hourly for a day and daily for a month,
and an extra one before any privileged operation that touches many files.
Restoring a file, a project or the whole tree is an admin task described in
the operator documentation. Snapshots live on the same NAS; protection
against fire or theft needs replication to a second box, which is a separate
decision your admin makes.

### 8.7 Keeping the engines alive

If the both-ways sync engine stops on your machine (a Windows session ending
can do that), the companion notices within half a minute, restarts it, and
tells you once: "Sync engine was not running: restarted it". If it cannot be
started after three tries, lane C shows an error instead of pretending to be
green.

---

## 9. The b-roll library

### 9.1 What it is

Every clip in `P:\Assets\B-roll Archive` is described by an AI vision model
(what is on screen, shot by shot, including any burned-in text), optionally
transcribed (what is said), and stored in a search index. The **B-ROLL** tab
in the dashboard searches that index.

- Type what you are looking for. **Keyword** matches words; **Semantic**
  matches meaning ("golden hour coastline" finds sunset cliffs); **Hybrid**
  combines them. Switch between **Visuals** (what is seen) and **Transcript**
  (what is said).
- Results are per segment, with timecodes, so you land on the right eight
  seconds of a four-minute clip. Hover a thumbnail to scrub it; open a clip to
  play the preview and step through its visual segments and transcript.
- Browse by category tree, hide clips with flagged defects, filter to your
  own uploads.

The heavy indexing runs on a machine with an NVIDIA GPU (typically a wired
machine), or on the machine that dropped the clips (below). The NAS itself
never needs a GPU: it only searches the finished index.

### 9.2 Send to Resolve

Each clip has a **Send to Resolve** button. Because the web page is served
from the NAS but your Resolve is on your machine, the page asks the companion
on your own computer to do the insert; nothing on the NAS can reach your
Resolve, and only your companion knows where the archive is on your disk.
The clip lands in a **B-Roll / Archive** bin in the open project. If the
clip's file is not on your machine yet, the companion fetches it from the NAS
on demand (at most two at once) and inserts it when it arrives.

If the button does nothing, the page shows a self-test link. The usual causes
are the companion not running, an old companion build, or the dashboard
address in the companion not matching the address you are browsing (the
companion logs exactly that).

### 9.3 Adding to the archive

Drag clips or folders onto the b-roll page (or use **Add b-roll**). You give
the batch a shoot name, choose whether to keep sub-folders, whether to upload
the originals too, and **when to run**: "only when idle" (the default, it
waits until you are away and Resolve is closed, and pauses when you return)
or "start now". **Your own machine** then makes the previews, runs the vision
model locally, and uploads the results. Indexing takes priority over proxy
generation while it runs. A machine whose GPU cannot fit the chosen model is
told so (the tray shows a VRAM warning) and the batch stays queued for
another of your machines. The tray shows indexing progress and has a cancel.

### 9.4 Client folders and share links

A client folder is a hand-picked set of archive clips with a title,
description and contact line, and a **link**. Whoever has the link, and
nobody else, sees a page that works like the archive does for you:
thumbnails that scrub, a preview player, and what is in each clip. No login,
no account, no software. Previews only, never an original.

- Hover any thumbnail and click the **+** to add it to a folder. The
  **Client folders** panel in the header lists every folder with its status
  (live, revoked, expired), clip count and how often the link has been
  opened. Set an expiry, reorder, caption clips, copy the link.
- **Revoke** kills a link at once, even for a browser that already has the
  page open. **New link** replaces a link that was forwarded on.
- The link works outside the tailnet only after the admin has published that
  one path through Tailscale Funnel on a separate port and set the public
  link base. Until then the panel warns that the link works only for people
  already on the tailnet. Nothing else (the login page, the libraries, the
  dashboard) is ever published that way.

The client's page reveals no file paths, no transcripts, no other clips and
no other folders. A dead link, whether revoked, expired or mistyped, shows
one neutral "not available" page.

---

## 10. The music library

`P:\Assets\Music` holds your royalty-free music. Each track is embedded with
an audio model and tagged for genre, mood, energy and instrumentation; the
**MUSIC** tab lets you search by feel: "tense driving synth pulse", "warm
nostalgic piano", "hopeful build for a montage". Filter by duration, find
similar tracks, play with a waveform, and **send to Resolve** the same way
b-roll works, via your own companion. Tracks you do not have locally are
fetched on demand.

Adding music is drag-and-drop on the music page, and the analysis runs on
your own machine on the CPU (no GPU needed, and an audio model of about
280 MB is fetched once per machine from the vendor's release feed). A track
that cannot be analysed locally falls back to a plain upload.

---

## 11. YouTube clip downloads (optional)

**This feature is off in the standard build and is switched on per customer
by agreement.** When it is off, the YOUTUBE tab does not exist and nothing
related to it runs on any machine.

When it is on:

- The **YOUTUBE** page takes a topic ("offshore wind protest, drone show") or
  pasted links. [ GET LINKS ] searches and shows a review grid of candidate
  videos; you untick what you do not want, then [ DOWNLOAD ]. Pasted links
  skip the review and download exactly those.
- Before the first use, the page and the tray both show a notice about rights
  and YouTube's terms; you accept it once per person and once per machine
  (**Accept YouTube Terms** in the tray). Downloads are refused until both
  are recorded.
- Downloads run **on the machine that asked**, into the project's `Youtube`
  folder, so the original is on your disk immediately and lane A carries it
  up. If your machine cannot do it (no companion, wrong settings), the server
  does it instead, and the job's badge says which.
- One job per person at a time. A job that is parked in review blocks new
  searches until you finish or cancel it.
- Some videos need a signed-in YouTube session. The tray's **Sign in to
  YouTube (for downloads)** takes a cookies file exported from your browser
  and keeps it on your machine only.
- The topic search uses an AI provider the admin configures under
  **Settings > AI providers** with their own keys. Keys are stored on the
  NAS, never shown back in full, never sent to editors.

---

## 12. How updates reach machines

The companion updates itself. The vendor publishes a build to your
dashboard (or your dashboard fetches it from the vendor's signed release
feed and the admin clicks Publish); each companion, on its regular report,
is told a different version is current.

- **By default, the editor clicks.** A tray notification appears and the menu
  grows "Update available > vX.Y.Z (install)". Clicking confirms, downloads,
  checks the file's fingerprint and signature against keys built into the
  running app, and swaps itself over. It will not do this in the middle of
  a FIX ALL or a consolidate.
- **The admin can push.** Settings > Packages lists out-of-date machines with
  an [ UPDATE NOW ] button each. The request reaches that machine on its
  next report and it installs the same signed build the click would have.
- **Unattended updates** are a per-site switch, off by default. With it on,
  a companion takes any newer build on its own, but never an older one.
- Rolling back is the admin making an older build current again; machines
  take it like any other update, above a signed minimum version floor.

The Mac build is produced separately and can lag the Windows build. The
dashboard updates its own code the same way, from the signed feed, with a
database backup and rollback; an update that changes its runtime needs a
click in the NAS's own interface instead.

---

## 13. What stays private, and how access works

- **Tailscale only.** Nothing in CC Sync listens on the public internet.
  The NAS is reachable by enrolled devices on your tailnet and by nobody
  else. The one door opened outward is the client preview path, and only
  when the admin turns it on.
- **Logins.** You sign into the dashboard and the tray with one username and
  password that the admin issues. Browser sessions expire after 12 idle
  hours or 7 days; an admin can sign a person out everywhere. Repeated bad
  passwords are throttled.
- **Tokens, in plain terms.** When you sign in at the tray, the dashboard
  hands your companion a signed note saying "this is this person's machine",
  valid for 30 days. Every status report carries it, so no other machine can
  impersonate yours, and the admin can revoke one machine's access without
  touching the others.
- **Between editors.** By default every editor in an organisation can read
  every project on the share (colleagues on one team). Your admin can switch
  on per-project permissions so that an editor sees only the projects they
  are assigned. Editor accounts on the NAS can transfer files and nothing
  else: no shell, no commands.
- **Between organisations.** One customer is one dashboard, one tree, one
  sync service. There is no shared multi-company instance.
- **On your machine.** The companion's local web bridge (the thing "Send to
  Resolve" talks to) answers only to pages served from your organisation's
  dashboard address, or to the companion's own tools. A random web page
  open in another tab cannot drive your Resolve.
- **Secrets.** Your password is never stored by the companion. AI provider
  keys live on the NAS with restricted permissions and are shown masked.
  Nothing secret appears in the status reports or logs.
- **Software integrity.** Every companion build is signed with a key the
  vendor keeps offline; the dashboard refuses an unsigned publish, and the
  companion refuses an unsigned or tampered download.

---

## 14. What the product does NOT do

- It does not run on the free edition of Resolve in any useful way, and it
  does not support Linux editing machines.
- It does not send camera originals down to remote editors. Remote editors
  receive proxies; originals travel up only. For a full-resolution grade, a
  Windows editor can temporarily swap `P:` to the server (section 6.6) and
  stream over the network.
- It does not delete anything on the NAS on an editor's behalf. Renames,
  moves and deletions of video on an editor's machine do not propagate;
  reorganising is a server-side job for the admin.
- It does not replace Resolve's Project Server. The shared project database
  is Blackmagic's; CC Sync makes sure the media it refers to is where it
  says.
- It is not an off-site backup. Snapshots protect against mistakes on the
  NAS; replication to a second site is a separate decision.
- It does not host several companies on one installation.
- It does not make proxies on remote machines for other people; that is a
  wired machine's job.
- It does not watermark client previews or let clients download anything.
- It does not publish the dashboard on the public internet, and it should
  not be put behind a port-forward or a reverse proxy to make it so.

---

## 15. Glossary

| Term | Meaning |
|---|---|
| **NAS** | Network-attached storage: the server box holding the one true copy of your footage |
| **Tailnet / Tailscale** | A private encrypted network between your enrolled devices, so a home machine reaches the NAS as if it were in the office |
| **Tree** | The canonical folder structure on the NAS, seen as `P:` on Windows |
| **Canonical path** | The path spelling stored in the shared project database (`P:\Projects\...`), identical on every machine |
| **Companion / tray app** | The CC Sync helper running on each editing computer |
| **Wired machine** | A computer physically connected to the NAS, editing straight off it, syncing nothing |
| **Remote machine** | A computer holding its own local copy of its assigned projects |
| **Sync plan** | The list of projects one computer holds |
| **Lane A / B / C** | Originals up; proxies down; everything else both ways |
| **Proxy** | A small, easy-to-play copy of a camera original, in the `Proxy` folder beside it |
| **Original** | The camera file itself |
| **Circuit breaker** | The latch that stops proxy download when the NAS looks wrong or a pass deletes too much |
| **Halt** | A full stop of every lane, local or fleet-wide, that survives restarts |
| **Trash** | `.ccsync-trash` at the top of your local tree: 14 days of anything lane B removed |
| **Undo journal** | The record of every clip path the companion changed in Resolve, replayable in reverse |
| **Snapshot** | A point-in-time copy of the NAS tree, taken hourly and daily |
| **Dashboard** | The web page on the NAS for status, plans, libraries and admin |
| **Fleet** | All the machines running the companion for your organisation |
| **Mapped mount** | Resolve's Mac preference translating `P:\` to a local folder |
| **Client folder** | A curated set of archive clips with a revocable preview link |
| **Funnel** | Tailscale's way of publishing one path to the public internet, used only for client links |
| **Release feed** | The vendor's signed list of available builds that a dashboard can fetch |

---

## 16. Troubleshooting: if you see X, it means Y, do Z

| If you see | It means | Do |
|---|---|---|
| Tray says "Sign in" and nothing is syncing | The companion does not know who you are | Right-click the tray, **Sign in**, use your CC Sync username and password |
| "Accept the licence agreement to start syncing" | The licence was not accepted on this machine (often after an update) | Click the menu item, read, accept |
| The admin says they cannot see your machine | You are not signed in at the tray, or the companion is not running | Check the tray says "Signed in as you"; start the companion if the icon is missing |
| The tray shows no project lines, or "no selection" | This computer's sync plan is empty (a new computer starts empty), or the dashboard could not be reached to read it | Tick projects on the dashboard, or ask the admin to copy another machine's plan |
| "PROXY DOWNLOAD STOPPED (safety): ..." | The lane B circuit breaker tripped; uploads and shared files still run | Tell the admin. After they confirm the NAS is healthy: admin clicks [ RESUME ] on the fleet grid, or you choose **Resume proxy download** |
| A proxy you had has vanished | Lane B mirrored a removal | Look in `.ccsync-trash` at the top of your local tree, newest folder |
| "Your administrator stopped syncing for everyone" or "Syncing is STOPPED on this machine" | The admin stopped the whole fleet, or you used *Stop ALL syncing* | Fleet halt: wait for the admin. Local: *Start syncing again* |
| "N file(s) won't upload" or a [ WON'T UPLOAD ] chip | A file with the same name but a different size already exists on the NAS; lane A never overwrites | Rename your file, or ask the admin to remove the server copy |
| "N need proxies" in the tray | Your uploaded originals have no proxy yet, so others cannot see them | Nothing; a wired machine makes them when idle. Ask the admin if the count never falls |
| A CC Sync popup lists clips | You cut in media from outside the synced tree | Pick destinations, **FIX ALL**; or **IGNORE** for this session |
| "Media Offline" for clips other people can see | Their proxy has not arrived yet, the project is not ticked on this computer, or `P:` is not mapped | Check the project is ticked for this computer and the tray shows it syncing; on Windows check `P:` exists; on Mac check the mapped mount |
| "mapping looks wrong" warning | Resolve resolves `P:\` paths to somewhere other than your sync folder | Mac: re-run the wizard's mapping step with Resolve quit. Windows: log off and on, then tell the admin if it persists |
| Playback is strangely slow and the tray shows little activity | Resolve is streaming originals over the network, usually because a NAS share is mapped to a colliding drive letter | Check your mapped drives and remove any NAS mapping you made yourself |
| "Sync engine will not start: <why>" | The both-ways engine could not be restarted after three tries | Send the admin diagnostics (tray > *Copy diagnostics for your admin*) |
| "PAUSED, drive disconnected" (Mac) | The SSD holding your tree is unplugged | Plug it back in; syncing resumes by itself. If macOS mounts it as "Name 1", see the Mac notes the admin has |
| The scripting warning dialog keeps appearing | Resolve's scripting server is not answering | Restart the companion, then Resolve; check *External scripting using* is set to Local |
| "Send to Resolve" does nothing | Companion not running, too old, or the dashboard address in it does not match the one you are browsing | Open the self-test link the page offers; if it answers, tell the admin the addresses differ |
| The b-roll page says your GPU cannot fit the model | Local indexing needs more video memory than this machine has | Pick a smaller model tier, or leave the batch for another of your machines |
| "Update available" in the tray | A different build is current on the dashboard | Click it when you are not mid-copy; it verifies and swaps itself |
| A client says the share link does not open | The public link base is not set, or the link was revoked or has expired | Check the folder's status in the Client folders panel; ask the admin whether the public link path is published |
| Syncthing's own web page shows folders "Paused" | Normal. Projects sync one at a time and the companion pauses the others between turns | Do not pause, unpause or remove folders there by hand |
