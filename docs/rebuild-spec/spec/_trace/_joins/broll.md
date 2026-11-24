# Joins aimed at broll

## Checked

- J1 | F6
- J2 | fine
- J3 | F11
- J4 | F3
- J5 | F4
- J6 | F5, F6
- J7 | F2
- J8 | F1
- J9 | fine
- J10 | F8, F9
- J11 | F10
- J12 | fine
- J13 | fine
- J14 | F7
- J15 | fine

## Findings

### F1: Whether the b-roll browser preview is ever attached in Resolve as a clip's proxy
- Kind: contradiction
- From: proxies-and-file-moves / Some clips are deliberately not pointed at a proxy
- Here: A clip sent to Resolve gets its editing proxy, never the browser preview as its proxy
- From says: "In the b-roll archive only, an MP4 in the "Proxy" folder is the browser preview, not an editing proxy; when the full-quality original is on this computer, it is not attached"
- Here says: "The browser preview is never attached as a clip's proxy."
- Settled by: BRO-110 (ruling): "Resolve is never given the browser preview as a clip's proxy."
- Fix: proxies-and-file-moves should say the b-roll browser preview is never attached as a proxy, whether or not the original is on this computer (keeping its message for the case where it is).

### F2: Whether a music drop is held on the editor's computer and counts against the free-space floor
- Kind: contradiction
- From: music / Dropping audio anywhere on the music page adds it to the library
- Here: A drop holds at most 2,000 clips and is taken only if it fits; Dropped files are cleaned away a week after they are no longer needed
- From says: "A drop is never refused for lack of free space on the person's own computer."
- Here says: "the one floor of free space on this computer that nothing CC Sync writes there (dropped b-roll and music, proxies, downloads) ever eats into" and "When the b-roll archive is off: the button and the line count music drops only."
- Settled by: the owner must say: when an editor drops music, is it held on their own computer until it is analysed (and so can be refused when that computer is short of space), or does it go straight to the library? (Decision 16.6, answered with recommendation A, makes one floor cover everything the product writes on a computer, but does not say whether a music drop writes there.)
- Fix: if music drops are not held on the computer, broll should drop "dropped ... music" from the floor setting and "count music drops only" from the staging line; if they are, music should replace its sentence with the one floor and the staging clean-up.

### F3: Two per-computer settings for b-roll drops that broll does not have
- Kind: missing
- From: editor-app / The settings each computer holds
- Here: nowhere (Dropped files are cleaned away a week after they are no longer needed gives a fixed 7 days; no setting names the holding folder)
- From says: "the free-space floor, where dropped files wait and how long finished drops are kept (see The b-roll archive, Music, and Work shared out across the computers)"
- Here says: "The files held on a computer for a drop are deleted 7 days after the drop ended" (nothing on choosing where dropped files wait)
- Settled by: the owner must say: can an editor choose where on their computer dropped clips wait, and how long finished drops are kept, or are both fixed?
- Fix: either broll adds the two settings (with defaults: the computer's tree, 7 days) or editor-app removes "where dropped files wait and how long finished drops are kept" from its list.

### F4: Whether describing stops when the person comes back, or finishes the work it is on
- Kind: contradiction
- From: fleet-jobs / The kinds of shared work and what each needs (and its "Work already running is finished when the person comes back")
- Here: Describing keeps the computer it runs on usable
- From says: "the computer takes no new shared work, but finishes the piece it is running. A long piece of work is never killed because its person came back."
- Here says: "The conditions are checked again between every step of every clip, so a person coming back loses at most the step in progress" and "Indexing b-roll… D of T (stops when you're back)"
- Settled by: JOB-003 (situation, weaker): "a long job already running is not killed when they return"; nothing says what "the piece" is for a b-roll drop, so the owner must say: when a person comes back to a computer describing a b-roll drop, does it finish the clip it is on and then wait, or stop at once?
- Fix: both pieces should say the same unit: broll that the clip under way is finished and saved before it waits (not "loses ... the step in progress"), and fleet-jobs that for b-roll "the piece" is one clip, not the whole drop.

### F5: The one list of every link handed outside the studio is two lists with different people and words
- Kind: contradiction
- From: footage-sorter-and-camera-cards-3 / An admin sees every folder link and can switch one off at once
- Here: An editor manages the folder list and makes new folders; An editor revokes a link, reactivates it, or issues a new one
- From says: "Links lists every link ever made that hands footage to people outside the studio ... the Sorter's folder links, and the b-roll archive's client folder links ... "switched off" or "ran out" ... Who: an admin."
- Here says: "The same list also holds the folder links the Footage Sorter makes ... and the delivery links, each marked as what it is." (a list anyone signed in opens, with states "revoked" / "expired" and "Revoke link" / "Reactivate link")
- Settled by: decision 21.5 (answered 2026-11-24, recommendation A): "show every link handed outside the studio in one list, each saying its kind, switched off from there"
- Fix: one piece holds the one list (who sees it, that it includes delivery links, and one set of words for a dead link and for switching one off) and the other points at it; broll's client-folder list should then hold only client folders, or the Sorter's "Folder links" should be described as that same list.

### F6: The delivery link and the Sorter's folder link: one thing or two, and the open doors miss it
- Kind: differs
- From: accounts-privacy-legal / Everything needs a sign-in except a short list of open doors; footage-sorter-and-camera-cards-3 / An admin makes a link that hands a folder of footage to anyone holding it
- Here: A delivery link lets a client download full-quality files
- From says: "a client folder link in the b-roll archive and a shared folder link in the Footage Sorter, where the link itself is the credential" and (Sorter) "Who: an admin" with "7, 14, 30 or 90 days, or No end date; 14 at first"
- Here says: "an editor can give a client a delivery link to chosen folders of the archive ... It is revoked, reactivated, renewed and expires exactly as a preview link does ... Who: anyone signed in makes one"
- Settled by: the owner must say: is the link that lets a client download whole folders of full-quality footage one kind of link (made by an admin from the Sorter) or also a separate b-roll link any editor can make on an archive folder?
- Fix: if one kind, broll's delivery link should become a pointer to the Sorter's folder link; if two, accounts-privacy-legal's open doors should name the b-roll delivery link and both pieces should say how it differs from the Sorter's.

### F7: "The one exception" to the private network is not the only link reachable from outside
- Kind: contradiction
- From: server-install-and-running-2 / The dashboard is reached only through the studio's private network
- Here: A delivery link lets a client download full-quality files
- From says: "The one exception is the link an editor hands to a client for a client folder"
- Here says: "a distant client can download full-quality files, possibly terabytes, without joining the studio's private network" (and the Sorter's folder links show a "For anyone" public address)
- Settled by: BRO-127 (ruling): "A client link downloads chosen folders read-only and resumable straight from the NAS near line speed, needing no client software or private-network access."
- Fix: server-install-and-running-2 should say the exceptions are the links handed to people outside the studio (client folder links, delivery links and the Sorter's folder links), pointing at the one list of F5.

### F8: Sending a b-roll clip does not check the project's frame rate that Resolve's facts promise for every import
- Kind: contradiction
- From: resolve-on-the-editors-computer / What Resolve does with multicams, timelines and frame rates
- Here: An editor sends the marked part of a clip to the timeline open in Resolve on their own computer
- From says: "Before anything is imported or built, the project's rate is checked against the footage (29.97 fps drop-frame for this studio's footage), and the person is stopped, with the reason, if it cannot be set." (kept by "sending a b-roll clip")
- Here says: "A clip whose frame rate is unknown is sent as 24 fps." (no rate check; refusals are only Resolve unreachable, no project, no timeline)
- Settled by: the owner must say: when an editor sends a b-roll clip whose frame rate differs from the open project's, does it go in as it is, or is the editor stopped?
- Fix: resolve-on-the-editors-computer should limit the rate check to building projects and timelines, or broll should add the check and its message to its refusals.

### F9: A placement that lands a frame off: laid again, or removed and reported as failed
- Kind: contradiction
- From: resolve-on-the-editors-computer / What Resolve does with multicams, timelines and frame rates
- Here: An editor sends the marked part of a clip to the timeline open in Resolve on their own computer
- From says: "Every clip the product places in Resolve is read back and laid again once if it is a frame out."
- Here says: "placement failed on V<n> at the playhead - something already occupies that span, or the track is locked" (anything that landed in the wrong place is removed)
- Settled by: the owner must say: when Resolve lays a sent b-roll clip one frame off, should the product lay it again by itself or remove it and tell the editor the placement failed?
- Fix: broll should say that a clip landing a frame off is laid again once before any "placement failed" (or resolve-on-the-editors-computer should exempt b-roll sends).

### F10: The guard on adding clips to the b-roll index, and its "not working" state, are not in broll
- Kind: missing
- From: server-install-and-running-1 / Adding clips to the b-roll index is always guarded
- Here: nowhere (Describing and indexing clips says nothing of it; Search never stops because of an update has only "its search data cannot be read")
- From says: "The b-roll part does not come up when that secret is missing or weak ... its status then says that no usable secret is set ... the admin can let the server make one or switch b-roll off. See The b-roll archive: Describing and indexing clips."
- Here says: nothing
- Settled by: the owner must say: when the server is not set up to guard additions to the b-roll archive, is the whole archive (search and client links included) shown as not working until an admin fixes it?
- Fix: broll should list this among the reasons the archive is shown as not working (and say whether client links keep working then, which "Client links keep working when something else fails" suggests), or server-install-and-running-1 should drop the pointer.

### F11: Whether the b-roll progress window reopens by itself after the editor closed it
- Kind: contradiction
- From: editor-app / Long background work has a progress window the editor can close and reopen
- Here: The computer doing the work shows what describing is doing, and the person at it can pause, resume, start now or cancel
- From says: "It opens by itself once when a piece of work starts (if the editor closes it, it stays closed for that piece of work)"
- Here says: "opens from the menu, or by itself when a drop starts or a download begins"
- Settled by: the owner must say: if an editor closes the b-roll progress window, should it open again by itself when the one-off download for describing begins?
- Fix: broll should say it opens by itself once per drop (dropping "or a download begins"), or editor-app should name the download as a second time it opens.
