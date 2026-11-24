# Trace of sync-2

## Coverage

- 01-018 | Each computer says in one sentence why it is not syncing, and since when
- 01-021 | An editor asks for a sync now
- 02-021 | An editor sees the originals they asked for arrive
- 02-022 | The app and the dashboard show the same live picture of what is moving
- 02-029 | How a sync that did not simply succeed is shown
- 03-010 | An interrupted upload never leaves a broken file where a good one is expected
- 03-021 | The app and the dashboard show the same live picture of what is moving ; The app and the dashboard say when a computer's connection goes the slow way round
- 03-031 | A file changed in two places at once keeps both versions
- 03-041 | Syncing comes back by itself when it stops running ; The app and the dashboard show the same live picture of what is moving
- 04-012 | The app's menu says in one phrase what syncing is doing now
- 04-042 | The app's window shows what is going up, what is coming down and the originals asked for
- 11-012 | Each computer says in one sentence why it is not syncing, and since when ; The dashboard lists what each computer still owes, and never claims "nothing" when it cannot tell
- 12-033 | The app and the dashboard show the same live picture of what is moving
- 13-045 | The sync list shows, per person and computer, the order projects sync in and what is left
- 15-029 | Admins are told when syncing has been down or failing on a computer for an hour
- 15-031 | Admins are told when syncing has been down or failing on a computer for an hour
- 15-110 | Each computer says in one sentence why it is not syncing, and since when
- 16-034 | Each project's progress on each computer is shown, with the project's own state on the NAS
- 20-007 | Each project's progress on each computer is shown, with the project's own state on the NAS
- 20-008 | Each project's progress on each computer is shown, with the project's own state on the NAS
- 20-026 | A computer's warnings clear as soon as it reports they are over, and silence means "cannot tell"
- 20-029 | Syncing comes back by itself when it stops running
- 20-053 | The app and the dashboard show the same live picture of what is moving
- 01-028 | When the sync drive is pulled with work owed, the editor is told what is owed and reminded until it is back
- 02-030 | An interrupted upload never leaves a broken file where a good one is expected
- 02-033 | A newer local file that will never upload because the server has its name is reported
- 03-034 | When the sync drive is pulled with work owed, the editor is told what is owed and reminded until it is back
- 11-009 | The dashboard lists what each computer still owes, and never claims "nothing" when it cannot tell
- 12-036 | The dashboard knows what each computer holds, project by project
- 13-042 | Every editor is told whether it is safe to shut down or unplug their computer
- 16-035 | The dashboard lists what each computer still owes, and never claims "nothing" when it cannot tell
- 20-009 | The dashboard lists what each computer still owes, and never claims "nothing" when it cannot tell
- 20-062 | The dashboard lists what each computer still owes, and never claims "nothing" when it cannot tell ; Files that are never sent are never counted as owed
- 20-063 | The dashboard lists what each computer still owes, and never claims "nothing" when it cannot tell
- 03-003 | A change starts syncing within about a minute, and an idle studio barely touches the NAS
- 02-013 | A remote editor's downloads take the studio's fastest path, and an admin can choose it
- 03-009 | A computer can be set to sync one project at a time, everything in it included
- 09-008 | A remote editor's downloads take the studio's fastest path, and an admin can choose it
- 12-038 | The app and the dashboard say when a computer's connection goes the slow way round ; An interrupted upload never leaves a broken file where a good one is expected
- 16-057 | Footage travels only over the studio's own private network
- 27-033 | left out: for the builders only (what it states for a person, a relayed route being shown, is written into "The app and the dashboard say when a computer's connection goes the slow way round")
- 02-002 | A file is sent only once it has stopped changing
- 02-006 | A new proxy on the server is brought down only once it has stopped changing
- 02-034 | Files dated in the future are shown to the editor until their date is fixed
- 09-035 | Each computer's clock is measured against the server's and a gap is shown
- 15-033 | Admins are told when a computer's clock is five minutes or more out
- 20-027 | Each computer's clock is measured against the server's and a gap is shown
- 01-040 | An editor is told once when their computer may not be recognised after a rename, and syncing carries on
- 12-056 | A renamed computer keeps its plan and everything waiting for it ; A disk copied onto a second computer is caught and explained
- 15-079 | A disk copied onto a second computer is caught and explained
- 15-080 | An admin approves a new computer and ties it to an editor
- 16-022 | An admin approves a new computer and ties it to an editor
- 16-027 | A new server over a NAS editors already sync from keeps what each computer syncs
- 16-028 | A computer belongs to a person only once it is tied to a known editor
- 20-006 | A computer belongs to a person only once it is tied to a known editor
- 20-020 | A disk copied onto a second computer is caught and explained
- 20-022 | A renamed computer keeps its plan and everything waiting for it
- 21-015 | An admin approves a new computer and ties it to an editor
- 01-034 | A project folder moved or renamed by the editor is noticed, named and can be put back in one click
- 02-015 | When an admin renames or moves a project on the server, every editor's copy follows by itself
- 02-016 | When an admin renames or moves a project on the server, every editor's copy follows by itself
- 02-032 | A project folder moved or renamed by the editor is noticed, named and can be put back in one click
- 02-035 | Project folders in no sync plan are reported and never deleted
- 03-005 | A ticked project's folder layout is made on the editor's computer, empty folders included
- 04-065 | A project folder moved or renamed by the editor is noticed, named and can be put back in one click
- 04-066 | Project folders in no sync plan are reported and never deleted
- 12-045 | The dashboard shows and warns about project folders out of place and footage not yet filed
- 15-067 | The dashboard shows and warns about project folders out of place and footage not yet filed
- 15-098 | Every project folder on the server is checked to still be recognised as its project
- 20-049 | A computer or a person can have a chosen project that new footage lands in
- 22-016 | The editor picks the folder for the project tree when setting up
- 22-017 | The editor picks the folder for the project tree when setting up
- 16-060 | Downloads from a Synology NAS always arrive whole
- 21c-014 | Downloads from a Synology NAS always arrive whole
- 21d-015 | Downloads from a Synology NAS always arrive whole

## Questions for the owner

### sync-2-Q1: Should a computer be able to sync one project at a time, holding every other project's files still while one has its turn?
- Kind: dormant
- Today: the mode exists but is off on every computer and can only be switched on by hand at the computer itself; normally the smaller project files of every ticked project keep syncing whatever project is busy.
- Options: A: cut it; every ticked project's files keep syncing. B: keep it as a per-computer setting an admin can turn on.
- Recommend: A, because nobody uses it and a setting nobody needs is a moving part with nothing to show for it.
- Changes for a person: with A nothing changes for anyone; with B an admin gains one more per-computer setting.
- Text assumes: B, written in its place and marked pending, to be deleted if you choose A
- Items: 03-009
- Covers: 03-Q2

### sync-2-Q2: Should footage always travel only over the studio's own private network, never through outside relay services, with the NAS never announcing itself publicly?
- Kind: unreachable
- Today: a setting meant to keep the NAS's file sharing off outside relays and public announcement exists on the server, but nothing applies it, so nobody can turn it on.
- Options: A: always so, no setting. B: a setting an admin can turn on. C: drop the idea.
- Recommend: A, because footage of clients should never pass through someone else's service, and one fixed rule is fewer parts than a switch; it matches your earlier decision that the studio's private network is the only way in.
- Changes for a person: with A nothing to set; a remote editor whose computer cannot reach the studio's private network directly is shown the slow-route warning instead of silently going through a relay.
- Text assumes: A
- Items: 16-057
- Covers: 16-Q3

### sync-2-Q3: The vendor's tool for measuring transfer speeds, with its comparison against a cloud service, is for the people building the product. Can it go from the specification?
- Kind: dev only
- Today: a measuring tool for the vendor times every way of moving files up and down, checks the files arrived, and compares the result with a cloud service's advertised speed (marked internal only).
- Options: A: leave it out; the builders make their own tools. B: keep it as part of the product.
- Recommend: A; what it proves for a person (at least 60 MB/s, the speed and the route shown) is written into the product's own promises.
- Changes for a person: none; an editor and an admin still see each computer's speed and whether its route is slow.
- Text assumes: left out
- Items: 27-033
- Covers: 27-Q6

## Readers' questions and unsettled points

- 01-Q2 | with sync-1
- 02-Q1 | answered: SYN-121 (a slow editor's downloads can use another read-only route, and a failing or empty answer pauses and never deletes), so the separate download route is written as live
- 02-Q2 | answered: SYN-128 (a folder the editor moved is named, with where it went, and a one-click put-back that deletes nothing; the app does not follow it on its own)
- 02-Q3 | with sync-1
- 03-Q2 | sync-2-Q1
- 03-Q6 | with sync-1
- 09-Q10 | with editor-app
- 12-Q3 | with sync-1
- 13-Q1 | with dashboard-1
- 13-Q2 | with dashboard-1
- 15-Q5 | with sync-1
- 15-Q13 | with sync-1
- 16-Q1 | with accounts-privacy-legal
- 16-Q3 | sync-2-Q2
- 20-Q1 | with dashboard-1
- 27-Q6 | sync-2-Q3
- U-01-4 | settled: a computer that works straight off the server syncs nothing, and its lines read "not used on this computer (it works straight off the server)"; the choice itself is in Sync: Wired or remote
- U-01-5 | settled: a computer's syncing not running is shown on the dashboard with its restarts and last error, and alerted after an hour ("Syncing comes back by itself when it stops running")
- U-03-5 | settled: a file is sent once its size and time have stood still for 2 minutes, and the state words are listed in full; how long a download may overrun a project's turn is behind the glass
- U-03-6 | settled: what an editor's computer does and says when a project moves on the server is written in full here; the rest belongs to proxies-and-file-moves
- U-12-6 | settled: a computer time more than 7 days off is not trusted as a time, and an unreadable one is "unknown", never "no difference"
- U-13-7 | behind the glass
- U-22-1 | open: sync-2-U1

## Still unsettled

- sync-2-U1 | whether a computer whose setting up was left unfinished refuses to sync | it shows "Sync: not set up yet" and does not sync until setting up is finished | 04-012, 04-042

## Conflicts between an item and a lesson

- SYN-122 | 01-018, 15-110, 09-035, 15-033 | the items make a clock 5 minutes or more out a reason proxy download transfers nothing, and tell nobody but the log; the lesson requires that no age rule trusts the computer's clock alone and that a gap over a minute is shown to the editor and the admin. Wrote the lesson: the clock is never a reason for not syncing, and is shown at over 60 seconds.
- SYN-123 | 02-002 | the item waits until a file's last change is 2 minutes old by its date; the lesson requires watching for a changing size or time, never the age alone. Wrote watching size and time stand still for 2 minutes.
- SYN-124 | 02-002, 02-034 | the items hold a future-dated file until its date has passed; the lesson requires it to upload like any other and the editor to see the wrong dates. Wrote the lesson.
- SYN-106 | 15-110 | the item shows at most two causes; the lesson requires every reason. Wrote every separately fixable cause after the first.
- SYN-106 | 01-018, 15-110 | the app and the dashboard word the same reasons differently and in different orders; the lesson requires identical words. Wrote one list in one order (the order question itself is written up by sync-1).
- SYN-133 | 16-060 | the item warns the admin and quietly hands editors the safe values; the lesson requires unsafe values to be refused. Wrote neither: downloads from a Synology stay within its limits on their own and there is nothing for an admin to set, which meets the lesson's aim (no truncating setting can be in force).
- SYN-110 | 03-003 | the item brings a change of plan into effect at the next round, about a minute; the lesson requires a tick to take effect within about 5 seconds. Wrote 5 seconds.

## New in this text

- Transfers are fast, and each computer's speed is shown against what its connection can do | at least 60 MB/s each way, and the achieved speed shown against a public baseline (SYN-118, SYN-120)
- Several editors' transfers run together and share the studio's connection | SYN-119
- A tick takes effect within seconds and says "getting ready" until data flows | SYN-110, SYN-111, SYN-113
- Syncing comes back by itself when it stops running | brought back within a minute or two without a new sign-in, backing off, the editor told after repeated failures (SYN-100, SYN-101, SYN-102, SYN-103)
- Each computer says in one sentence why it is not syncing, and since when | a project held back while the others sync is named (SYN-108); the clock is no longer among the reasons; the same words everywhere
- A change starts syncing within about a minute, and an idle studio barely touches the NAS | a change on the server reaches a computer within about 5 minutes, an idle computer costs a few sign-ins an hour, and reports about unchanged projects carry almost nothing (SYN-116, SYN-117)
- Each computer's clock is measured against the server's and a gap is shown | shown to the editor and the admin over 60 seconds, with the fix (SYN-122)
- Files dated in the future are shown to the editor until their date is fixed | they upload like any other (SYN-124)
- Downloads from a Synology NAS always arrive whole | downloads stay within Synology's limits on their own, with nothing for an admin to tune; a downloaded file shorter than its source is never marked done (SYN-133)
- Sync onto the NAS never depends on changing permissions | SYN-132
- Moving or restoring a file never overwrites one already there, on any system | SYN-134
- A file of zeros left by a power cut is never sent over a good copy | SYN-135
- An admin approves a new computer and ties it to an editor | the admin approves from the list of computers waiting and chooses the editor, in place of a hand-run step where a device identity and a username are typed in; "applied N of M" (SYN-126); a known computer back with a new identity is shown (SYN-125)
- A disk copied onto a second computer is caught and explained | found once, in one wording, in place of three findings
- The dashboard knows what each computer holds, project by project | what a computer or an editor-writable file reports is capped, with one entry saying how many were left out (SYN-127)
- A computer belongs to a person only once it is tied to a known editor | a computer that belongs to nobody is listed as such, in place of a line only in the server's log
- A remote editor's downloads take the studio's fastest path, and an admin can choose it | the per-computer view shows which connection each computer's downloads use and says when it is the slow one; a connection not used is said there, not only in the app's log
- When an admin renames or moves a project on the server, every editor's copy follows by itself | the sentences with the help for the editing program off (owner's requirements, section 2)
- A project folder moved or renamed by the editor is noticed, named and can be put back in one click | on macOS the answers name Finder, since a Mac has no Explorer
- The app's window shows what is going up, what is coming down and the originals asked for | the window's lines are by direction and by what was asked for, in place of one line per way of moving files

## Parts of items left out

- 01-018 | "project-file sharing is not running" and "waiting for their filter list" are folded into "syncing has stopped running" and "projects held back"; they named one way of moving files
- 15-110 | "a reason this dashboard is too old to explain" (one part older than another); the server's guess from a 20 GB default build value (an arrangement: the computer itself says when it stopped)
- 15-110 | the limit of two causes (SYN-106 asks for every cause)
- 04-042 | the per-way labels ("Proxies (server → you)", "Everything else, both ways (audio, graphics, subs)") and "Sync queue: <which project out of how many>" for projects taking turns
- 04-012 | "proxy download stopped" reworded to "downloading stopped": it named one way of moving files
- 03-021 | states of one way of moving files on its own, and "waiting for their filter list" (folded into projects held back)
- 03-041 | "N failed pass(es) since launch" reworded to attempts: a pass is the build's inside
- 03-003 | the steps of the wait between looks (about one, two, then five minutes), abandoning a round, asking about once a minute with nothing ticked; kept as promises of how soon and how little
- 03-010, 03-005 | "about one round in twenty" and "one round in ten" (how often the build looks); written as "every so often" and "within about 5 minutes"
- 12-033 | "a marker that changes whenever real work happens", written as since when progress last moved
- 16-035, 20-009 | 600 names fetched against 500 kept: wrote 500 as the length of the full list, unsure whether it is a pipe size
- 13-045 | "one project at a time" (an arrangement of turns, written as the order they sync)
- 02-021 | "the same rules that guard b-roll fetches" generalised to every download into the tree
- 02-013 | "Nobody is told except in the app's log" (replaced: the per-computer view says so); "next pass" reworded
- 09-008 | "the folder layout" kept; "the server is told" written as the dashboard shows it
- 09-035 | the warning written only to the log, once an hour, and "every time the computer reports wrong" as the cause of proxies not coming down (SYN-122)
- 15-033 | the explanation that proxy download takes only files past a minimum age (SYN-122)
- 02-034 | files held until their date (SYN-124)
- 21-015 | the device identity's shape and length (63 characters), and naming the computer with the editor's NAS username typed by hand: insides of one way of sharing
- 20-006 | the shape of a valid sign-in name (belongs to accounts-privacy-legal) and "a raw device identifier"
- 16-022 | approval on the NAS as a step of its own, and the line only in the server's log
- 16-027 | the words "seed deferred" reworded to plain words
- 16-028 | "an older app's computer shared by person": one part older than another
- 15-079 | the three separate findings and the sync-network clash fix "reinstall or reset that computer's sync identity" (an inside of one way of sharing)
- 16-057 | "a setting meant to ... but nothing applies it", and automatic discovery as a named mechanism
- 16-060, 21c-014, 21d-015 | the admin-facing piece-size and transfers-at-once settings, their refusal messages, blank defaults and how sizes are written: tuning of one way of transferring; the fact about Synology and the promise that downloads complete are kept, with nothing to tune; "sshd" named
- 22-016 | "Step 5" (the place in the set-up screens)
- 02-032 | "project dir not yet local" reworded
- 12-056 | "Forget on the sync status page" written as the per-computer view
- SYN-100 | the half about programs started in a Windows session dying with it; the promise (back within a minute or two, without a new sign-in) is met
- 02-013, 09-008 | the download route as its own address and folder on the server, and refusing a route only half described or naming the normal one: how one build sets up a second path; written as the choice of which of the studio's connections downloads use
- 02-030, 03-010, 12-038 | counting partly written files left in a project on the server, their examples, and an admin deleting them by hand: leftovers of one way of uploading; kept are the promise (no broken file where a good one is expected, nothing deleted to tidy up) and the space unfinished uploads hold
- 01-040 | the id file, its name, and reporting without an identity: the computer's identity record is an inside; kept is what the editor is told and that syncing carries on
- 12-056, 15-079, 20-020 | deleting the stored identity in the user's home folder (written as starting afresh as a new computer from the Settings window) and one identity moving between entries: insides of how a computer is recognised
- 02-006 | the per-computer setting for how long a new proxy must stand unchanged: a person would not feel it; the promise that a proxy still being written never comes down cut short is kept

## Joins with other capabilities


- sync / What syncs where | A newer local file that will never upload because the server has its name is reported | the first version of a name to reach the server is the one kept
- sync / Files that must never sync | Files that are never sent are never counted as owed | which files uploads leave behind
- sync / Files that must never sync | Each computer says in one sentence why it is not syncing, and since when | a project held back until it is protected
- sync / Disk space | An editor sees the originals they asked for arrive | the disk-space sentences
- sync / Safety stops | How a sync that did not simply succeed is shown | the limit on removals and the safety stop
- sync / Stuck, slow and fair transfers | How a sync that did not simply succeed is shown | a project's time running out
- sync / The sync drive | When the sync drive is pulled with work owed, the editor is told what is owed and reminded until it is back | the drive phrases and what stops when the drive goes
- sync / Wired or remote | The app's window shows what is going up, what is coming down and the originals asked for | a computer that works straight off the server
- sync / Upload only | The dashboard lists what each computer still owes, and never claims "nothing" when it cannot tell | an upload-only tick
- sync / Studio-wide stops and the editor's pause | The app's menu says in one phrase what syncing is doing now | stops and the pause
- accounts-privacy-legal / What the product records about a person | The dashboard lists what each computer still owes, and never claims "nothing" when it cannot tell | a computer withholding its file list
- accounts-privacy-legal / Who may sign in | A computer belongs to a person only once it is tied to a known editor | what a known editor and a sign-in name are
- resolve-on-the-editors-computer / Missing clips, relinking and refreshing | When an admin renames or moves a project on the server, every editor's copy follows by itself | relinking Resolve after the folder moved
- resolve-on-the-editors-computer / Clip paths and media outside the shared tree | Each computer says in one sentence why it is not syncing, and since when | clips outside the tree that will never upload
- proxies-and-file-moves / Moves that reach every computer | When an admin renames or moves a project on the server, every editor's copy follows by itself | the server side of a project moved
- dashboard / Each computer's state | Each computer says in one sentence why it is not syncing, and since when | the per-computer view
- dashboard / Transfers and the queue | The app and the dashboard show the same live picture of what is moving | the Transfers page and the transfer history
- dashboard / Alerts by mail | Admins are told when syncing has been down or failing on a computer for an hour | delivery of alerts
- dashboard / Problems the server finds | A disk copied onto a second computer is caught and explained | the overview's problems
- dashboard / People and computers | An admin approves a new computer and ties it to an editor | the list of computers waiting for approval
- editor-app / Installing and setting up | The editor picks the folder for the project tree when setting up | the set-up screens
- editor-app / The tray or menu-bar icon and its menu | The app's menu says in one phrase what syncing is doing now | the menu itself
- editor-app / Starting, staying running and crashing | Syncing comes back by itself when it stops running | crash reports and restarts of the app
- editor-app / Signing in, the computer's identity and the licence | An editor is told once when their computer may not be recognised after a rename, and syncing carries on | the computer's identity
- footage-sorter-and-camera-cards / Sorting into shoots, people and cameras | A computer or a person can have a chosen project that new footage lands in | footage dropped in and filed
- broll / Sending a clip to Resolve | A remote editor's downloads take the studio's fastest path, and an admin can choose it | b-roll fetched when needed
- server-install-and-running / Installing on a NAS | Downloads from a Synology NAS always arrive whole | kinds of NAS
- server-install-and-running / NAS speed, load and clock | A change starts syncing within about a minute, and an idle studio barely touches the NAS | the NAS's load
