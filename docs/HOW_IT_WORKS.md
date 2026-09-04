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
computer would take days and fill every drive. Resolve makes this worse in a
specific way: it remembers the exact path of every clip (for example
`P:\Projects\2026\Series\Episode\B-roll\clip.braw`). If the same project is
opened on a computer where that path does not exist, every clip shows as
"Media Offline".

CC Sync solves this with three ideas working together:

1. **One canonical folder tree**, held on your storage server, which every
   computer sees at the same path spelling. On Windows that is the `P:` drive.
   On a Mac, Resolve is told that `P:\` means your local sync folder.
2. **Each editing computer syncs only a slice of the tree**: the projects it
   has been assigned, and for video, only small proxy copies rather than the
   originals. Anything the editor adds goes back up automatically.
3. **A small helper app on every computer** (the CC Sync companion, which lives
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
- the sync engine services that editors' computers talk to,
- Resolve's own shared project library (the Resolve Project Server), which is
  Blackmagic's feature and runs alongside CC Sync. CC Sync handles the media;
  Resolve handles the project database.

The NAS also takes regular snapshots of the tree (see section 8), so that
"somebody deleted a folder" is a restore, not a disaster.

### 2.2 The dashboard

The dashboard is a web page served from the NAS. Every editor signs into it to
choose which projects their computer should hold and to see how their sync is
going. The team admin uses it to see the whole fleet, manage people and
computers, publish updates, and stop everything in an emergency. The b-roll
library, the music library and (if switched on) the YouTube downloader all
live inside the dashboard as extra tabs.

### 2.3 The companion (the tray app)

The companion is a small program installed on every editing computer. On
Windows it sits in the system tray next to the clock; on a Mac it sits in the
menu bar. Right-click (or click) it for a menu. It:

- runs the three kinds of syncing (section 4),
- watches the open Resolve timeline and offers to fix media that lives
  outside the synced tree,
- repairs stale proxy links and keeps the shared LUT library visible to
  Resolve,
- reports status to the dashboard about once a minute,
- receives updates, stop and resume requests from the dashboard,
- provides the local "Send to Resolve" bridge that the b-roll and music
  pages use.

It requires DaVinci Resolve Studio. The free edition of Resolve does not
expose the scripting interface the companion relies on, so with the free
edition syncing still runs but nothing that touches Resolve does.

### 2.4 Wired computers and remote computers

Every computer that runs the companion is registered as one of two kinds.
The setup wizard asks this on its first page.

| Kind | What it means | What syncs |
|---|---|---|
| **Physically connected (wired)** | The computer is in the office and reaches the NAS directly, so its `P:` drive *is* the NAS share | Nothing. It edits straight off the server. It is also usually the computer that makes proxies and runs the heavy indexing jobs |
| **Remote editor** | The computer is anywhere else and holds its own local copy of its assigned projects | All three kinds of syncing run; `P:` points at the local copy |

A site can have several wired computers and one person can own both kinds
(an office desktop that is wired, a laptop that is remote) under one account.
The role belongs to the computer, not the person.

### 2.5 Tailscale (the private network)

Your NAS is not on the public internet and should never be. Tailscale is a
service that creates a private, encrypted network (a "tailnet") between
devices you enrol, wherever they physically are. Each editing computer and
the NAS join the tailnet once; from then on the editor's computer can reach
the NAS as if it were on the office network, and nobody else can.

Everything in CC Sync travels over the tailnet: sync traffic, the dashboard,
Resolve's project database. There is one deliberate exception, the client
preview links in section 9.4.

### 2.6 Resolve itself

Resolve is unchanged. Editors connect to the shared project library as they
normally would and set **Playback > Proxy Handling > Prefer Proxies** once,
so that a clip whose original is not on their computer plays from the proxy.
Wired computers are set the opposite way because they hold everything.

---

## 3. The project tree

The tree is one folder on the NAS, mapped to `P:` on every Windows computer.
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
the same three ways; nothing is copied and nothing needs relinking in
Resolve. The project page lists what a project shares from others (and what
is shared out of it), and a red [ LINK ] chip in the sidebar means one of
those declarations needs attention. Whole projects cannot be borrowed (tick
both projects instead), and `Proxy` folders cannot be borrowed directly
(share their parent).

---

## 4. The three ways files move

"Syncing" here means: the companion compares the NAS copy and the local copy
of your assigned projects and moves files until they agree, in a direction
that depends on what kind of file it is. Not every file goes both ways, and
that is the whole design.

| Name | Direction | What it carries | Safety rule |
|---|---|---|---|
| **Upload** | your computer to the NAS | video originals you add, outside any `Proxy` folder | **Never deletes anything on the NAS.** Skips a file that already exists there |
| **Proxy download** | the NAS to your computer | only the contents of `Proxy` folders | Mirrors the NAS exactly, so it can delete locally. It stops itself when the server stops looking right (section 8.1), and everything it removes goes to a local trash folder |
| **Folder sync** | both ways | project files, audio, graphics, After Effects comps, subtitles, documents, stills, LUTs | Deletions are not applied to other computers; the NAS keeps 30 days of old versions |

Logs, support messages and the technical API still call these three lane A,
lane B and lane C. On any screen you look at, they are upload, proxy download
and folder sync.

What this means in practice:

- Video you add to a project uploads automatically. Other editors do not
  receive your original; they receive its proxy once one has been made
  (section 6.4).
- Proxies for everything in your assigned projects download to you.
- Small files (music cues, voiceover, subtitles, AE comps) flow both ways
  within a minute or two.
- If you rename or move a video file locally, the NAS gets a second copy
  under the new name and keeps the old one. The upload never tidies up. Ask
  the admin to reorganise on the server side.
- If you re-export a video under the same name as one already on the NAS,
  the upload skips it, because the first version of a name is the only one
  it will ever send. The tray and the dashboard show a "won't upload" warning
  naming the file. Rename it, or have the admin remove the server copy.

### 4.1 Your sync plan belongs to a computer

A sync plan is the list of projects a particular computer holds. It belongs
to the computer, not to you. If you have a desktop and a laptop, each has its
own plan, and a new computer starts with **nothing** ticked, on purpose:
nobody wants a laptop to start pulling 50 GB because a desktop had it.

- On the dashboard's main page, the checkboxes in the sidebar are for **you as
  a person**: ticking there means "every computer I use". Unticking there
  removes the project from all of them.
- The per-computer lists are on **Settings > Sync plans**, a grid of projects
  against computers. Each computer's column has a "copy from" box so the
  admin can hand a new laptop another computer's plan in one click.
- Projects sync **one at a time, in the order they were ticked**, each taking
  a turn of up to about ten minutes before the next one gets a go. A big
  project high on the list does not block a small one below it forever.
- Unticking stops new transfers. Files already on your disk stay until you
  remove them (the tray has a gated "remove from this computer" action; see
  section 8.4).

A wired computer cannot be ticked at all. It syncs nothing, so a tick would
mean nothing, and the dashboard says so.

### 4.2 Sending originals up without bringing the project down

Some footage only needs to go one way. An editor who already holds a shoot on
their own drive may want it safely on the server without pulling the rest of
that project down onto a laptop that has no room for it.

That is an **upload only** tick. It is the same tick as any other, with one
difference: only upload runs. Proxy download and folder sync do not, and the
project's folder is never shared with that computer at all.

- Put the footage where a full tick would have put it, in the tree's own
  layout (`P:\Projects\<year>\<series>\<project>\...`). The companion
  uploads the video originals it finds outside any `Proxy` folder, on exactly
  the rules ordinary upload follows: nothing is overwritten, nothing on the
  server is ever deleted.
- Nothing comes back. No proxies, no shared project files, no other editor's
  work.
- It is set per computer, like every tick. On the project page it is
  **[ UPLOAD ONLY FOR ME ]**, and a project already ticked normally offers
  **[ SWITCH TO UPLOAD ONLY ]**; the admin's grid on Settings > Sync plans has
  a small box beside each tick. A person whose desktop syncs a project fully
  and whose laptop only uploads it is marked
  **[ UPLOAD ONLY ON ONE COMPUTER ]**.
- Untick it the way you untick anything else. Removing the files from the
  computer still asks first whether the originals have reached the server.

Your companion needs to be reasonably current for this to exist at all: an
older build would run proxy download for it too, which is exactly what an
upload-only tick is for avoiding.

---

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
   - *Step 1: How is this computer connected.* "I'm a remote editor" or "I'm
     physically connected to the server/NAS".
   - *Step 2: Join the network.* It installs Tailscale if needed and opens
     the browser for you to sign in to your organisation's tailnet.
   - *Step 3: Sign in.* Your CC Sync username and password.
   - *Step 4: Install.* You choose the local sync folder. The wizard installs
     the sync engines and the companion, maps `P:` (Windows) or sets
     Resolve's mapped-mount preference (Mac), and starts the tray app. It is
     safe to run again; every step checks what is already done.
   Before any of that, the wizard shows the licence agreement. Syncing will
   not start on a computer where it has not been accepted; if you ever see
   "Accept the licence agreement to start syncing" in the tray, click it.
4. **Sign in at the tray.** If the wizard did not do it for you, right-click
   the tray icon and choose **Sign in**. Until the menu says "Signed in as
   you", nothing syncs and the admin cannot see your computer. This is
   deliberate: the companion does nothing until it knows who you are.
5. **The admin approves your computer.** The first time your computer's sync
   engine contacts the NAS it shows up as a pending device; the admin
   approves it once. Until then folder sync waits.
6. **Tick your projects.** In the dashboard, tick the projects this computer
   should hold (or the admin does it from the Assignments grid). Within a
   minute or two the tray shows the first project syncing, with speed and
   files remaining. The companion first recreates the project's folder
   skeleton locally, then pulls proxies, then lets folder sync carry
   the small files.
7. **Connect Resolve** to the shared project library the way the admin
   describes (server address, port, username, password), set **Prefer
   Proxies**, open a timeline. Clips stored as `P:\Projects\...` play from
   your local proxies without a relink prompt. If Resolve asks you to locate
   a file, the mapping is not right yet; tell the admin.

**Mac editors, two extra notes.** There is no `P:` drive on a Mac and there
never will be; Resolve's mapped mount translates `P:\` to your sync folder,
and the wizard sets it while Resolve is quit. Unplugging the SSD is fine: the
companion pauses everything, the icon goes orange, and syncing resumes on its
own when the drive returns. Unplug it while something was still uploading or
downloading and the companion says so at once ("...was disconnected before
syncing finished: 2 uploads still to go. Plug it back in to finish syncing.")
and repeats the reminder every half hour until the drive is back.

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
bins but have not cut in yet, use **Settings > ADVANCED > Scan whole
project**.

### 6.3 Bringing in a project you started before CC Sync

**Settings > ADVANCED > Bring an existing project's media into the synced
folder** scans
the whole media pool, shows a report of how much will be copied and uploaded,
and on your confirmation copies every out-of-tree clip into the project,
relinks Resolve, uploads the originals and pulls any proxies. Again: copies,
never moves.

### 6.4 Proxies

A proxy is a small, easy-to-play copy of a camera original (here, H.264 at
1080p or below) with the same name and timecode, stored in the `Proxy`
folder next to the original. Resolve links them automatically.

Where proxies come from:

- **A wired computer** makes them. Blackmagic's Proxy Generator can watch the
  tree there, and the companion on a wired computer also fills gaps itself
  with ffmpeg, but **only while nobody is using the computer**: it waits for
  idle time and stops within a couple of seconds when someone comes back.
  The tray shows "Proxies this computer has made" and progress.
- **Remote computers** do not make proxies for others. When you upload an
  original, the tray says how many clips are waiting for a proxy, and other
  editors see your clip once the proxy has come back down to them. This can
  take minutes or hours depending on the queue.

If a project arrives carrying stale proxy paths from another computer (for
example a drive letter that never existed on yours), the companion repoints
them to the local `Proxy` folder automatically. Every such change is
journalled so it can be undone (section 8.5).

### 6.5 LUTs and stills

`P:\Assets\Luts` is a shared LUT library that every computer receives without
ticking anything. The companion adds it to Resolve's list of LUT locations
(you can see it in *Preferences > System > General > LUT Locations*). Drop a
LUT into Resolve's own LUT folder as you always have and the tray will offer
"N LUTs only on this computer: share with the team", which copies them into
the library after a confirmation naming them. If Resolve was launched before
`P:` was ready, it may not list the library until its LUT list is refreshed;
the companion detects that from Resolve's own log and refreshes it for you.

`P:\Assets\Stills` does the same job for Resolve's gallery stills.

### 6.6 The rest of the tray menu

Right-click the tray icon (Windows) or the menu bar icon (Mac). The menu is
deliberately short: it carries what you might click *now*, and everything
that is a setting or a rarely used tool lives one click away in **Settings**
(section 6.7).

| Menu item | What it does |
|---|---|
| *Your name, at the top* | Who this computer is signed in as. Not clickable; it is a statement. If it says you are not signed in, **Sign in…** is directly under it and nothing syncs until you answer it |
| Sync now | Start the next pass immediately, instead of waiting for the timer |
| Take fleet jobs now | Lends this computer to the team for a set number of minutes: while it is on, the server may give it work like making proxies or transcribing. Only shown if your admin has enabled it. Click it again to stop |
| Pause syncing | Stops upload and proxy download, for a laptop on a hotspot. Folder sync keeps running. It reads *Resume syncing (paused by you)* while it is on |
| Open my sync drive | Explorer or Finder at your local tree |
| Open dashboard | The web page, in your browser |
| Settings… | The companion's own window: everything else it can do (section 6.7) |
| Restart CCSync | Stops and starts the companion. This is the answer whenever anything tells you to restart it |
| Quit CCSync | Stops syncing until you start it again, or log in to this computer again |

Above those, the menu shows **only what is currently true**, and each line
removes itself when it stops being true:

- one line of sync state, in plain words ("Up to date", "Downloading
  proxies", "PROXY DOWNLOAD STOPPED (safety)"), plus what Resolve is doing;
- a running YouTube download, with a **Stop the YouTube download** item;
- prompts you can act on: accept the licence, set this project up on the
  server, share LUTs only this computer has, resume proxy download, start
  syncing again, install an update.

If a prompt is in your menu, it is because nothing else will clear it.

### 6.7 The Settings window

*Settings…* opens the companion's own window. It refreshes itself while it is
open, and every section is present only when it has something to say.

| Section | What is in it |
|---|---|
| **THIS COMPUTER** | This computer's name and its role: **[ REMOTE EDITOR ]** or **[ WIRED TO THE SERVER ]**, which you set here and nowhere else. Who you are signed in as, sign in or out, and **[ RESTART CCSYNC NOW ]** |
| **SYNCING** | Upload, proxy download and folder sync, a line each, with what is moving and what stopped. The buttons that belong to a stopped state appear here: resume proxy download, start syncing again, accept the licence |
| **PROJECTS ON THIS COMPUTER** | Every project on this computer's sync plan, and which are **upload only** (section 4.2) |
| **RESOLVE** | What the companion can see of your Resolve: clips whose files it cannot find, proxies it could not attach, and what it did about them |
| **FLEET JOBS** | Whether this computer is taking work for the team, what it is running right now with a **[ STOP THIS JOB ]** button, and the last few jobs it finished |
| **YOUTUBE** | Only if your admin has enabled YouTube downloads: signing in to YouTube, and stopping a download |
| **ADVANCED** | Scan a whole project; bring an existing project's media into the synced folder; undo the last clip-path change; grade from server originals (Windows: swap `P:` for a session); stop ALL syncing on this computer; remove a project from this computer |
| **HELP** | **[ COPY DIAGNOSTICS FOR YOUR ADMIN ]** puts a summary of this computer's state on the clipboard to paste into a message. **[ OPEN LOG ]**. **[ HOW CC SYNC WORKS ]** and **[ WHAT DO THESE MEAN? ]** open this document, and the version this computer is running is at the bottom |

HELP moves to the top of the window whenever something is wrong, because that
is when somebody needs it.

### 6.8 Shutting down

Uploads cannot resume part-way. If you shut down with a file half-sent, the
companion warns you and the file starts again from zero next time. While a
transfer is running the companion also keeps the computer from sleeping.

---

## 7. What the team admin sees and does

| Dashboard page | What it is for |
|---|---|
| **Sync status** (the front page) | Every project with a health dot; per project, each editor and computer, how complete it is and what is missing. The sidebar ticks are here |
| **Transfers** | Live queue: what is moving right now, speed, ETA, what is queued and what is still "getting ready" |
| **Fleet** grid | One row per computer: online, version, what upload, proxy download and folder sync are each doing, and the coloured chips that mark an unusual state (proxy download stopped itself, stopped by the admin, indexing, needs proxies, will not upload). A [ RESUME ] button appears beside a computer whose proxy download stopped itself |
| **Settings > Users** | People, their computers, approving a new computer's sync device, per-editor tokens, active sessions, and the switch that **stops syncing for the whole fleet** |
| **Settings > Sync plans** | The project-by-computer grid with "copy from" |
| **Settings > Packages** | Published companion builds, which one is current, [ UPDATE NOW ] per out-of-date computer, and the vendor's release feed |
| **Settings** (site) | The organisation's name, addresses, feature switches, AI provider keys for optional features |
| **Project setup** | Create a new project folder from the template, straight from the browser |

Admins see everything; editors see their own projects, computers and
transfers only.

### 7.1 What the server tells you it has found

The dashboard does not keep its own bad news in a log file. Every few minutes
the server checks what it can see of itself and the fleet, and anything it
finds opens a row that stays open until it stops being true.

- **PROBLEMS THE SERVER FOUND**, on the front page above the grid. It is
  there only when something is open, so a healthy fleet does not show a
  panel. Each row says what happened, what it means and **WHAT TO DO**, and
  most carry a **[ TAKE ME THERE ]** button that opens the page where you fix
  it. Dismissing a row is allowed; it comes back by itself if it is still
  true.
- **Settings > HEALTH** is the one page that answers "is everything all
  right?". It gathers, worst first, the open problems, the alerts, the facts
  that have stopped being true, and the safety mechanisms the server cannot
  currently confirm. Each line is printed in the words of the page it came
  from, and links back to it. Nothing on that page changes anything.
- **[ NOT CHECKED ] is not [ OK ].** Where the server cannot answer a check,
  it says so and gives the reason, rather than showing a green tick it has
  not earned. This is deliberate, and it is the point of the whole panel.

An admin can also have findings sent on: your admin can point the server at
an email address or a webhook, and it sends a summary once a week.

---

---

## 8. Safety features, in plain terms

A sync engine's worst failure is deleting the customer's footage. Several
independent latches exist so that no single mistake, on any computer, can do
that. All of them prefer to stop and ask a human rather than guess.

### 8.1 When proxy download stops itself

Proxy download is the one of the three that removes local files, because it mirrors the NAS
proxy folders. If the NAS briefly looks empty (a pool still importing, a
share not mounted, a project unshared by mistake), a naive mirror would
delete every proxy on your computer to match. That is what proxy download
stopping itself prevents.

It stops, **before anything is deleted**, if the NAS no longer looks like the
tree, lists a project as empty that was not empty before, or has shrunk by
more than half. It stops **after** a pass if that pass removed more than a
handful of files or more than a quarter of your proxies. It also stops on a
slow leak over several passes. Before stopping it first checks whether the
files were simply *moved* on the NAS rather than deleted, which is not an
alarm.

**What you see.** The tray line reads "PROXY DOWNLOAD STOPPED (safety)" with
the reason, and a red chip appears on the admin's fleet grid. Upload and folder sync
keep running: your uploads and the shared files are unaffected.

**What to do.** Tell the admin. Once they have confirmed the NAS is healthy,
either they click [ RESUME ] beside your computer on the fleet grid, or you
choose **Resume proxy download** in the tray and confirm. Nothing clears it
automatically, on purpose: this is precisely the moment somebody should
look.

### 8.2 The local trash

Everything proxy download removes goes first into a `.ccsync-trash` folder at the top
of your local tree, in a subfolder named by date and time. It is kept for 14
days or until it exceeds 50 GB (oldest batches go first, never the newest),
and nothing is pruned while proxy download is stopped. If a proxy vanished, look
there.

### 8.3 Stopping syncing on purpose

**Pause is not stop.** Pause leaves folder sync running. Stopping
stops all three on a computer, folder sync included, and survives a
restart.

- **On this computer:** Settings > ADVANCED > *Stop ALL syncing on this
  computer*. You clear
  it yourself with *Start syncing again*.
- **Fleet-wide:** the admin sets it on Settings > Users with a mandatory
  reason. Every companion stops within about a minute and shows the reason
  in its tray. A computer that is off adopts it when it comes back. Editors
  cannot start it again themselves; the admin does that from the same panel,
  and it releases itself after a day unless they keep it stopped. It
  exists for "something is destroying files and I do not yet know which
  computer".

### 8.4 Delete protection and removal gating

- In folder sync, **a deletion is never applied to another computer**.
  Delete a music cue by accident and it disappears from your disk only; the
  NAS and every other editor keep it. The NAS also keeps 30 days of old
  versions of every file it carries. Two people editing the same small
  file at once produces a conflict copy rather than a silent overwrite, and
  the tray points it out.
- Deleting a whole project folder locally does not propagate: the sync engine
  sees its marker file is gone and stops that folder instead.
- **"Remove from this computer"** for a project first asks upload and folder sync
  whether anything of yours has not yet reached the NAS. If it cannot get an
  answer, it refuses. An override exists for a dead NAS and a full disk, but
  it requires typing the project's folder name, and it is reported to the
  admin.

### 8.5 The undo journal for Resolve edits

The companion changes clip paths inside Resolve from a few places: FIX ALL,
the automatic repointing of stale proxy paths, and the relinking of clips
that arrive with another computer's drive letter. Resolve's own Undo does not
cover scripted changes, so before any of them the companion saves the
project, exports a rollback copy of it, and writes a journal naming every
clip's old and new path.

**Settings > ADVANCED > Undo the last clip-path change CCSync made** replays the
newest journal in reverse and reports, for example, "Put 158 clip path(s)
back the way they were". If that is not enough, the exported project copy can
be imported into Resolve's Project Manager as a separate project, alongside
the current one, so nothing is overwritten. Journals are kept for 60 days and
never leave your computer.

### 8.6 Snapshots on the NAS

Your local copy is a replica, not a backup. The NAS takes snapshots of the
tree and of the dashboard's own data: hourly for a day and daily for a month,
and an extra one before any privileged operation that touches many files.
Restoring a file, a project or the whole tree is an admin task described in
the operator documentation. Snapshots live on the same NAS; protection
against fire or theft needs replication to a second box, which is a separate
decision your admin makes.

### 8.7 Keeping the engines alive

If the folder sync engine stops on your computer (a Windows session ending
can do that), the companion notices within half a minute, restarts it, and
tells you once: "Sync engine was not running: restarted it". If it cannot be
started after three tries, folder sync shows an error instead of pretending to be
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

The heavy indexing runs on a computer with an NVIDIA GPU (typically a wired
computer), or on the computer that dropped the clips (below). The NAS itself
never needs a GPU: it only searches the finished index.

### 9.2 Send to Resolve

Each clip has a **Send to Resolve** button. Because the web page is served
from the NAS but your Resolve is on your computer, the page asks the companion
on your own computer to do the insert; nothing on the NAS can reach your
Resolve, and only your companion knows where the archive is on your disk.
The clip lands in a **B-Roll / Archive** bin in the open project. If the
clip's file is not on your computer yet, the companion fetches it from the NAS
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
or "start now". **Your own computer** then makes the previews, runs the vision
model locally, and uploads the results. Indexing takes priority over proxy
generation while it runs. A computer whose GPU cannot fit the chosen model is
told so (the tray shows a VRAM warning) and the batch stays queued for
another of your computers. The tray shows indexing progress and has a cancel.

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
your own computer on the CPU (no GPU needed, and an audio model of about
280 MB is fetched once per computer from the vendor's release feed). A track
that cannot be analysed locally falls back to a plain upload.

---

## 11. YouTube clip downloads (optional)

**This feature is off in the standard build and is switched on per customer
by agreement.** When it is off, the YOUTUBE tab does not exist and nothing
related to it runs on any computer.

When it is on:

- The **YOUTUBE** page takes a topic ("offshore wind protest, drone show") or
  pasted links. [ GET LINKS ] searches and shows a review grid of candidate
  videos; you untick what you do not want, then [ DOWNLOAD ]. Pasted links
  skip the review and download exactly those.
- Before the first use, the page and the tray both show a notice about rights
  and YouTube's terms; you accept it once per person and once per computer
  (**Accept YouTube Terms** in the tray). Downloads are refused until both
  are recorded.
- Downloads run **on the computer that asked**, into the project's `Youtube`
  folder, so the original is on your disk immediately and upload carries it
  up. If your computer cannot do it (no companion, wrong settings), the server
  does it instead, and the job's badge says which.
- One job per person at a time. A job that is parked in review blocks new
  searches until you finish or cancel it.
- Some videos need a signed-in YouTube session. **Settings > YOUTUBE > Sign
  in to YouTube (for downloads)** takes a cookies file exported from your browser
  and keeps it on your computer only.
- The topic search uses an AI provider the admin configures under
  **Settings > AI providers** with their own keys. Keys are stored on the
  NAS, never shown back in full, never sent to editors.

---

## 12. How updates reach computers

The companion updates itself. The vendor publishes a build to your
dashboard (or your dashboard fetches it from the vendor's signed release
feed and the admin clicks Publish); each companion, on its regular report,
is told a different version is current.

- **By default, the editor clicks.** A tray notification appears and the menu
  grows "Update available > vX.Y.Z (install)". Clicking confirms, downloads,
  checks the file's fingerprint and signature against keys built into the
  running app, and swaps itself over. It will not do this in the middle of
  a FIX ALL or a consolidate.
- **The admin can push.** Settings > Packages lists out-of-date computers with
  an [ UPDATE NOW ] button each. The request reaches that computer on its
  next report and it installs the same signed build the click would have.
- **Unattended updates** are a per-site switch, off by default. With it on,
  a companion takes any newer build on its own, but never an older one.
- Rolling back is the admin making an older build current again; computers
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
  hands your companion a signed note saying "this is this person's computer",
  valid for 30 days. Every status report carries it, so no other computer can
  impersonate yours, and the admin can revoke one computer's access without
  touching the others.
- **Between editors.** By default every editor in an organisation can read
  every project on the share (colleagues on one team). Your admin can switch
  on per-project permissions so that an editor sees only the projects they
  are assigned. Editor accounts on the NAS can transfer files and nothing
  else: no shell, no commands.
- **Between organisations.** One customer is one dashboard, one tree, one
  sync service. There is no shared multi-company instance.
- **On your computer.** The companion's local web bridge (the thing "Send to
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
  does not support Linux editing computers.
- It does not send camera originals down to remote editors. Remote editors
  receive proxies; originals travel up only. For a full-resolution grade, a
  Windows editor can temporarily swap `P:` to the server (section 6.6) and
  stream over the network.
- It does not delete anything on the NAS on an editor's behalf. Renames,
  moves and deletions of video on an editor's computer do not propagate;
  reorganising is a server-side job for the admin.
- It does not replace Resolve's Project Server. The shared project database
  is Blackmagic's; CC Sync makes sure the media it refers to is where it
  says.
- It is not an off-site backup. Snapshots protect against mistakes on the
  NAS; replication to a second site is a separate decision.
- It does not host several companies on one installation.
- It does not make proxies on remote computers for other people; that is a
  wired computer's job.
- It does not watermark client previews or let clients download anything.
- It does not publish the dashboard on the public internet, and it should
  not be put behind a port-forward or a reverse proxy to make it so.

---

## 15. Glossary

These are the words the product uses, and it uses only these: every page,
tray line and message in CC Sync is written from this table. The dashboard
links straight to a row here wherever one of them appears.

| Term | Meaning |
|---|---|
| **Tick** | To say that a project should sync to a computer. You tick a project on the dashboard; unticking stops new transfers and leaves what is already on the disk |
| **Sync plan** | The set of projects one computer holds. It belongs to the computer, not to the person: a desktop and a laptop have a plan each. The page is **Settings > Sync plans** |
| **Computer** | Any editing machine running the companion. The product says "computer" everywhere a person reads; "device" is used only for a computer's sync identity on the network |
| **Wired** | A computer in the office, connected to the server directly, editing straight off it. It syncs nothing, and it cannot be ticked |
| **Remote** | A computer anywhere else, holding its own copy of the projects on its sync plan |
| **Upload** | Video originals going from your computer to the server. It never deletes anything on the server |
| **Proxy download** | Proxies coming from the server to your computer |
| **Folder sync** | Everything else (project files, audio, graphics, subtitles, stills, LUTs), both ways |
| **Upload only** | A tick that sends this computer's video originals for a project to the server and downloads nothing back: no proxies, no shared project files |
| **Paused** | Syncing is off because you turned it off, on this computer. You turn it back on the same way |
| **Stopped by your admin** | Your admin stopped syncing for the whole fleet. Only they can start it again, and it releases itself after a day unless they keep it stopped |
| **Stopped itself** | The companion stopped one thing on its own for safety: proxy download stops when the server does not look like the tree any more, or when your disk is nearly full. Nothing is deleted, and it stays stopped until a person clears it |
| **Sync status** | The dashboard's front page: every project, every computer, and what is moving |
| **Copy diagnostics** | The button that puts a summary of this computer's state on the clipboard to send to your admin. It is in the companion's own window: **Settings > Help > Copy diagnostics** |
| **NAS** | Network-attached storage: the server holding the one true copy of your footage |
| **Tree** | The folder structure on the server that every computer mirrors, seen as `P:` on Windows |
| **Canonical path** | The path spelling stored in the shared project database (`P:\Projects\...`), identical on every computer, which is what stops clips going offline when a project moves between them |
| **Companion** | The CC Sync helper running on each editing computer, in the tray or menu bar |
| **Proxy** | A small, easy-to-play copy of a camera original, in the `Proxy` folder beside it |
| **Original** | The camera file itself |
| **Trash** | `.ccsync-trash` at the top of your local tree: 14 days of anything proxy download removed |
| **Undo journal** | The record of every clip path the companion changed in Resolve, replayable in reverse |
| **Snapshot** | A point-in-time copy of the server's tree, taken hourly and daily |
| **Dashboard** | The web page on the server for status, sync plans, libraries and admin |
| **Fleet** | Every computer running the companion for your organisation |
| **Tailnet** | Your private encrypted network, so a home computer reaches the server as if it were in the office |
| **Mapped mount** | Resolve's Mac preference translating `P:\` to a local folder |
| **Client folder** | A curated set of archive clips with a revocable preview link |
| **Release feed** | The list of available builds this dashboard fetches from us, signed, so an update can be checked before it is offered |

---

## 16. Troubleshooting: if you see X, it means Y, do Z

| If you see | It means | Do |
|---|---|---|
| Tray says "Sign in" and nothing is syncing | The companion does not know who you are | Right-click the tray, **Sign in**, use your CC Sync username and password |
| "Accept the licence agreement to start syncing" | The licence was not accepted on this computer (often after an update) | Click the menu item, read, accept |
| The admin says they cannot see your computer | You are not signed in at the tray, or the companion is not running | Check the tray says "Signed in as you"; start the companion if the icon is missing |
| The tray shows no project lines, or "no selection" | This computer's sync plan is empty (a new computer starts empty), or the dashboard could not be reached to read it | Tick projects on the dashboard, or ask the admin to copy another computer's plan |
| "PROXY DOWNLOAD STOPPED (safety): ..." | Proxy download stopped itself; uploads and shared files still run | Tell the admin. After they confirm the NAS is healthy: admin clicks [ RESUME ] on the fleet grid, or you choose **Resume proxy download** |
| A proxy you had has vanished | Proxy download mirrored a removal | Look in `.ccsync-trash` at the top of your local tree, newest folder |
| "Your administrator stopped syncing for everyone" or "Syncing is STOPPED on this computer" | The admin stopped the whole fleet, or you used *Stop ALL syncing* | Stopped by your admin: wait for them. Stopped by you: *Start syncing again* |
| "N file(s) won't upload" or a [ WON'T UPLOAD ] chip | A file with the same name but a different size already exists on the NAS; the upload never overwrites | Rename your file, or ask the admin to remove the server copy |
| "N need proxies" in the tray | Your uploaded originals have no proxy yet, so others cannot see them | Nothing; a wired computer makes them when idle. Ask the admin if the count never falls |
| A CC Sync popup lists clips | You cut in media from outside the synced tree | Pick destinations, **FIX ALL**; or **IGNORE** for this session |
| "Media Offline" for clips other people can see | Their proxy has not arrived yet, the project is not ticked on this computer, or `P:` is not mapped | Check the project is ticked for this computer and the tray shows it syncing; on Windows check `P:` exists; on Mac check the mapped mount |
| "mapping looks wrong" warning | Resolve resolves `P:\` paths to somewhere other than your sync folder | Mac: re-run the wizard's mapping step with Resolve quit. Windows: log off and on, then tell the admin if it persists |
| Playback is strangely slow and the tray shows little activity | Resolve is streaming originals over the network, usually because a NAS share is mapped to a colliding drive letter | Check your mapped drives and remove any NAS mapping you made yourself |
| "Sync engine will not start: <why>" | The folder sync engine could not be restarted after three tries | Send the admin diagnostics (companion window: *Settings > Help > Copy diagnostics*) |
| "PAUSED, drive disconnected" (Mac) | The SSD holding your tree is unplugged | Plug it back in; syncing resumes by itself. If macOS mounts it as "Name 1", see the Mac notes the admin has |
| "...was disconnected before syncing finished: N uploads still to go", repeating every half hour | The SSD was unplugged with a transfer still running; what it names is still owed | Plug it back in and leave the companion running until the `Sync:` line reads up to date. The reminders stop by themselves when the drive is back |
| The scripting warning dialog keeps appearing | Resolve's scripting server is not answering | Restart the companion, then Resolve; check *External scripting using* is set to Local |
| "Send to Resolve" does nothing | Companion not running, too old, or the dashboard address in it does not match the one you are browsing | Open the self-test link the page offers; if it answers, tell the admin the addresses differ |
| The b-roll page says your GPU cannot fit the model | Local indexing needs more video memory than this computer has | Pick a smaller model tier, or leave the batch for another of your computers |
| "Update available" in the tray | A different build is current on the dashboard | Click it when you are not mid-copy; it verifies and swaps itself |
| A client says the share link does not open | The public link base is not set, or the link was revoked or has expired | Check the folder's status in the Client folders panel; ask the admin whether the public link path is published |
| Syncthing's own web page shows folders "Paused" | Normal. Projects sync one at a time and the companion pauses the others between turns | Do not pause, unpause or remove folders there by hand |
