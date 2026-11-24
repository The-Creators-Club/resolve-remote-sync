# The knowledge base: what the owner is asked

Stays behind (not part of the pack). Written by `tools/assemble_kb.py`; do not edit by hand.

- 123 lessons the old product never solved (**still open**). Each is a rule the rebuild must meet; say if any is no longer wanted.
- 150 reports whose outcome could not be found (**outcome not found**). Say whether it was fixed, still happens, or no longer matters.
- 108 fixes written but never released to the editors (**fixed, never shipped**), so nobody has used them.
- 8 questions where two sources disagreed and the dates did not settle it.
- 0 pairs of lessons that cannot both hold.

## Accounts, privacy and the legal paperwork

### Still open

- **ACC-001** Accounts outside the editing team could sign in and browse everything. Must: The admin decides which accounts may open the product, and every sign-in route, single sign-on included, refuses any account outside that set.
- **ACC-014** Two computers with the same name keep signing each other out. Must: A computer's identity never depends on its hostname; two same-named computers keep separate, working credentials.
- **ACC-043** Pages sent no browser security headers and some admin actions skipped origin checks. Must: Every page sends browser security headers, every changing action checks its origin, and admins can use a second factor.
- **ACC-055** A new licence version stopped sync until each editor clicked accept. Must: A licence change asks each editor at once without stopping their sync, and a computer still waiting shows that as its state.
- **ACC-075** Connections carrying footage or passwords did not check who answered. Must: Every connection carrying footage or a credential verifies the far end's identity, and a changed identity is refused.

### Outcome not found

- **ACC-002** An outside sign-in could take over another person's account by name. Must: An outside sign-in maps to an account only through an identifier the person cannot change at the sign-in service, never by name.
- **ACC-007** An admin grants a person access with one button. Must: An admin can grant a person access from a single button on the dashboard, with no other step.
- **ACC-050** Transcripts kept for the assistant had no retention limit. Must: Every stored transcript and assistant record is deleted after a site-set period, and the published report list matches what is actually sent.
- **ACC-076** The mail password could be sent unencrypted. Must: No password is sent over an unencrypted connection; such a mail setting is refused at save and at send.

### Fixed, never shipped

- **ACC-011** One credential shared by every computer could not be revoked for one. Must: Each computer holds its own credential bound to one person, revocable alone; a site-wide shared credential is off unless the admin turns it on.
- **ACC-018** Disabling or deleting a person left their browsers and computers working. Must: Disabling, deleting or suspending a person ends their sessions, shares and every computer's access at the next request, all or nothing, and the confirm states this.
- **ACC-019** A deleted person came back when their computer reported. Must: No report or registration ever re-creates a deleted person.
- **ACC-024** A new account reusing a deleted person's name inherited their access. Must: A new account with a deleted person's name starts with none of their projects or rights, and keeps rights given to it directly.
- **ACC-044** Any editor could reach and delete any project on the NAS. Must: Each project folder is limited to its members, admins manage members from the project, and re-creating an existing project grants nothing.
- **ACC-045** The server held NAS-admin power by default. Must: By default the server holds no NAS-admin-equivalent credential, verifies the NAS it talks to, and editors delete only projects granted to them.
- **ACC-051** The privacy policy said "no phone-home" while the server checked for releases. Must: The privacy policy lists every automatic outbound request and outside service, what it carries, and how to turn it off.

## Music

### Question only

- **MUS-052** Inserting music at the playhead cut into a clip spanning that point. Must: Inserting music refuses, before changing anything, when a clip straddles the insert point.
  - **Question:** should inserting a cue in the middle of an existing music bed succeed by making room, or always be refused as the later finding says?

### Still open

- **MUS-002** A track added from an editor's computer lacked tempo, key and loudness. Must: Every library track gets the same analysis, including tempo, key and loudness measured the same way, wherever it was added.
- **MUS-012** A track that failed local analysis stayed only on the editor's computer. Must: A track that cannot be analysed locally is still uploaded and queued under a library-issued name; nothing reaches the library under a name the library did not issue.

### Outcome not found

- **MUS-003** "Similar tracks" returned only tracks from the same stock library. Must: Search and "similar" rank by sound, tags, genre and mood; a file name never affects results, and similar results are not dominated by one source library.
- **MUS-027** An open music tab kept starting work on the editor's computer. Must: A browser tab left open for an hour causes no repeated process starts and no growing disk writes on the editor's computer.

## Proxies and file moves

### Still open

- **PRX-027** 148 ordinary clips were sent to the external proxy generator. Must: Clips the product can decode get proxies from its own encoder; only formats it cannot decode, such as Blackmagic RAW, go elsewhere.
- **PRX-041** A proxy an editor made locally could be trashed by proxy downloads. Must: A proxy an editor's computer made itself is never trashed or removed as a stray by proxy downloads or tidying.
- **PRX-061** A failed project folder move was "finished" by adopting a proxy-only folder. Must: A blocked move completes only into the really moved folder; nothing creates the new path meanwhile, and a stray folder there never counts as the move.
- **PRX-083** When proxies are moved on the NAS, editors re-download them all. Must: When proxies are only moved on the NAS, each editor's copies are moved locally, not trashed and fetched again.
- **PRX-089** Fixing a project would duplicate 100 GB that was already in the tree. Must: When a missing clip's file exists in the tree with the same name and size, the person is offered a relink to it, never a copy.

### Outcome not found

- **PRX-010** "Sync stuck" was really Resolve refusing proxies a few frames short. Must: A proxy whose frame count differs from its original is named to the editor and on the dashboard as a proxy fault, not a sync stall, and remade.
- **PRX-020** Proxy making failed again and again on camera originals truncated on the NAS. Must: An original that cannot be read to its end is reported as damaged with its path, not retried forever.
- **PRX-029** The proxy generator stalled on one file and failed others with no reason. Must: When a project's proxies cannot be made, the editor is told which file failed and why, instead of a stuck progress line.
- **PRX-092** Clips with known copies stayed offline because their drive was unplugged. Must: When a clip cannot be relinked because the drive holding its copy is unreachable, the result says that drive is offline.
- **PRX-095** Gathering a project failed on a remote editor's computer only. Must: Gathering behaves the same on every computer, and a failure names the file and the reason.

### Fixed, never shipped

- **PRX-039** A new project said "0 originals" for up to 45 minutes. Must: A new project is counted within about a minute, and until then every view says "counting", never 0.
- **PRX-040** The originals picker showed no picture and could not play a clip. Must: Each file in the originals picker has a thumbnail and plays its proxy; a Blackmagic RAW file without a proxy says "no proxy yet".

## Releases and updates

### Still open

- **REL-002** On a Mac, the app lost its disk permission after an update, or never started. Must: An update on macOS keeps the app's permissions and its ability to start, and a refused launch is visible to someone.
- **REL-007** Windows warns every editor who installs an unsigned program. Must: Every Windows program a person runs, first-run installer included, ships code-signed, and a release states which of its files are unsigned.
- **REL-014** Anyone posing as the dashboard could install any program on every computer. Must: Every app the product installs refuses any update whose signature does not verify against a key built into it, whatever the update's source.
- **REL-034** A trial build was blamed for crashes written by older builds. Must: Only real crashes after the build started on that computer count; deliberate restarts never do, and when it cannot be told the build is not passed and says so.
- **REL-052** Installing an update threw away an upload that had run for hours. Must: An update waits for uploads, fetches and jobs to reach a safe point, or they resume where they stopped, unless a person chooses otherwise.
- **REL-065** Each part of the dashboard should update on its own. Must: A change to one part (editor, b-roll, music, downloader) is tested and shipped without retesting or redeploying the unrelated parts.

### Outcome not found

- **REL-022** One version number meant two different programs. Must: A version always means one set of bytes everywhere; republishing identical bytes changes nothing, different bytes are refused as a conflict, and the studio tests exactly what customers receive.
- **REL-038** The builds list must show the newest first and hide old versions. Must: Each product and platform shows its newest build first, older ones only in a rollback picker, one place updates everything, and only truly modified builds are marked so.
- **REL-050** An update killed midway left nothing to start at sign-in. Must: An update interrupted at any point leaves a program that starts at sign-in, recovered without a person renaming files.
- **REL-077** The update address written into every install can never move. Must: Every install fetches updates from a vendor-owned address that can be redirected without touching any installed site.

### Fixed, never shipped

- **REL-012** The key the whole fleet trusts sat unprotected, with no backup. Must: Signing asks for the passphrase every time, the key restores from either backup, missing backups are reminded each release, and a written plan exists for a stolen key.
- **REL-018** An old or wrongly dated release list could lock computers out. Must: Computers refuse a release list older than one already seen, and list dates never go backwards because a publisher's wrong clock is caught and named.
- **REL-021** A release failed twenty minutes in, or halfway, for something known at the start. Must: Every refusal a release can meet is checked before its first long or irreversible step.
- **REL-023** An untested build from any branch could reach customers. Must: Only an unmodified main-line build above every published version, whose full tests actually ran and passed, reaches customers, and a check fails when the customer channel trails.
- **REL-024** A packaged build was never started before it shipped. Must: Every release build is started once in its packaged form and passes a self-test before it is signed or published.
- **REL-049** A computer reinstalled the crashing build it had just rolled back from. Must: A build undone on a computer or server is never installed there again automatically, only a newer one, and an admin's push of it is refused in words.
- **REL-055** A computer refusing every update looked like one that had not reported. Must: A refusing computer shows the refusal and reason until it runs that build or the offer is withdrawn; a withheld offer is told apart from no update.
- **REL-066** A server update that could not serve pages was never undone. Must: An update that started but does not pass its health check within ten minutes is reverted with its real reason shown; a refusal names its cause instead.
- **REL-072** Customers get one exact build after it ran on the studio first. Must: A customer site updates only to the exact build named for it, refused until that same build ran 24 hours on the studio.
- **REL-073** A customer on a fixed server build was given update steps that changed nothing. Must: Every update notice for a server fixed to one build names the exact new build and the steps that actually change it.

## Resolve on the editor's computer

### Still open

- **RSV-007** Sweeping Resolve's media pool by script stalls Resolve's own interface. Must: Background work never sweeps Resolve's whole media pool or timeline on a timer when nothing changed, and asks Resolve nothing during playback.
- **RSV-008** A single Resolve call can block for seconds, minutes or indefinitely. Must: No Resolve call blocks the tray, a window, other features or quitting; each call has a deadline after which it is reported and abandoned.
- **RSV-020** Blackmagic Proxy Generator runs as the Resolve program itself. Must: Detecting Resolve ignores a Resolve process started with the proxy generator switch.
- **RSV-030** A scheduled per-project Resolve export must wait for Resolve to finish launching. Must: Scheduled Resolve exports connect only after Resolve has fully registered with its script server, never during launch.
- **RSV-035** Driving Resolve from another computer needs its network scripting switch, never tested. Must: Nothing relies on network scripting until tested, and if used, the port is reachable only from the studio's own computers.
- **RSV-147** A remote editor needs one frame of a camera raw original in Resolve to grade. Must: A remote editor can bring one frame of a raw original from the NAS into Resolve and change its raw settings, without downloading the whole clip.

### Outcome not found

- **SRT-186** Re-importing a folder of numbered stills duplicates them in Resolve. Must: Re-importing a folder into Resolve never adds a second copy of stills it already holds as image sequences.
- **RSV-010** Resolve's scripting went dead for hours with nothing logged. Must: When Resolve stops answering, the product says so plainly and tells the person Resolve must be relaunched.
- **RSV-013** After a forced restart Resolve showed a "save current project" box that would not close. Must: The product never force-closes Resolve without first saving or closing the open project, and checks Resolve is usable after a restart.
- **RSV-027** A check for a competing Resolve client mistook unrelated programs and stayed refused. Must: The check identifies only a real competing Resolve client, names it, and re-checks by itself without an app restart.
- **RSV-031** Resolve crashed instantly on launch on the studio's main computer. Must: Nothing on an editor's computer contacts Resolve before its launch completes, and Resolve launch failures are logged for diagnosis.
- **RSV-034** Resolve installed on another drive stopped the app from reaching it. Must: The product reaches Resolve wherever it is installed, or says in plain words that it cannot find Resolve and where it looked.
- **RSV-041** Setup must cope with Resolve Free, scripting off, older Resolve and non-English Windows. Must: On each, setup completes or names exactly what the editor must change, and syncing keeps working without Resolve's scripting.
- **RSV-051** Resolve regenerated every audio waveform at each launch. Must: Opening a synced project shows its audio waveforms without waiting for them to regenerate on each launch.
- **RSV-056** The fix list pointed clips at another project's folder and ran off screen. Must: Fix suggestions target only the open project's folder, empty rows never appear, and the window fits the screen and scrolls.
- **RSV-057** The out-of-project prompt went quiet until Resolve was restarted. Must: The out-of-project check keeps working for a whole Resolve session, and if it loses Resolve it says so instead of going quiet.
- **RSV-082** Resolve crashed opening a project whose clip was relinked to a shortcut file. Must: Relinking never links or offers a shortcut or any file that is not playable media of the clip's kind.
- **RSV-085** The owner wanted a quick relink of only the open timeline. Must: Relink offers a scope of just the active timeline's clips, besides the whole project.
- **RSV-117** A conformed timeline had no sound on one editor's computer. Must: When a conformed timeline is silent on one computer, the product can check that computer's playback and offline clips and say which is at fault.
- **RSV-143** One fix needed several undos, and a repeat undo claimed success. Must: Each press is undone by one undo restoring the exact earlier state or saying it cannot, a repeat says it is already undone, and relinks re-check each clip's path just before.

### Fixed, never shipped

- **RSV-023** A computer that had never connected was told "quit and reopen Resolve" for ever. Must: A computer that has never connected to Resolve gets setup advice, not restart advice, and that knowledge survives restarts of both programs.
- **RSV-025** Checking whether Resolve is running must cost almost nothing. Must: An idle computer starts no helper processes to learn whether Resolve is running, and one answer serves every part of the product.
- **RSV-032** Resolve's external scripting is off by default and absent from the free edition. Must: Setup detects edition and setting, sets Local or names exactly what to change or that Studio is needed, and says done only after a real connection.
- **RSV-033** A dongle-licensed Resolve Studio has no licence file, like the free edition. Must: A found Studio licence counts as proof of Studio, and no editor is told they have the free edition because a licence file is missing.
- **RSV-053** A Resolve project is linked to a project folder only on an exact name match. Must: A Resolve project links automatically only when its name exactly matches one project folder's name; anything else, or an unreadable tree, asks the editor.
- **RSV-115** Resolve cannot decode VP9 originals at full resolution, though proxies edit fine. Must: The editor is warned as soon as a timeline uses VP9 originals, naming each clip and the fix, and is warned again for any newly added one.

## Sync

### Question only

- **SYN-058** Quitting or updating the app left its old transfer running beside a new one. Must: Once quit, sign-out or update begins nothing new starts, and no file is ever sent by an old and a new transfer at once.
  - **Question:** Should quitting or updating the app stop an in-flight upload, losing its progress, or leave it running to finish?
- **SYN-073** With the sync drive unplugged, downloads would have filled the internal disk. Must: With the drive absent or mounted under another name, all syncing pauses, nothing is written elsewhere, free space is never measured on another disk, and the app says the drive is disconnected.
  - **Question:** One early ruling had the same drive resume under any mount name; later rules pause a numbered remount with instructions. Which does the owner want?

### Still open

- **SYN-004** An urgent project could not be moved to the front of a computer's queue. Must: An editor or admin can move a project to the front of one computer's sync queue from the screen.
- **SYN-027** A wired computer re-read the whole NAS tree every five minutes. Must: A wired computer never re-reads the whole NAS tree on a short cycle.
- **SYN-039** An editor's undo window is 14 days while the NAS keeps versions a year. Must: The owner sets both recovery windows together, and each is stated where a person goes looking for a lost file.
- **SYN-062** Macs leave hidden "._" files and folder settings files on shared drives. Must: macOS system companion files never sync in either direction, are never counted, and any already on the NAS are found and cleared.
- **SYN-094** An offline laptop spent each pass on failing transfers and blamed a broken sync. Must: When the NAS is unreachable the app shows "cannot reach the server" as its own state, stops trying, and resumes promptly when the network returns.
- **SYN-105** An upload status flipped between error and idle while nothing was missing. Must: An error names its files and reason in the log and on screen, and a pass is never shown red when every file is on the NAS.
- **SYN-112** A warning about one project was cleared by a clean scan of another. Must: Each project's warnings persist until that project itself scans clean.
- **SYN-117** Every computer re-sent its unchanged file lists every few minutes. Must: A report about unchanged projects sends and stores almost nothing, idle computers back off, and an over-size report drops only enough detail.
- **SYN-124** Footage dated in the future by a wrong camera clock never uploads. Must: Future-dated files upload like any other, and the editor sees which file and date are wrong until they are fixed.

### Outcome not found

- **SYN-034** A file made on an editor's computer went to the bin before it was uploaded. Must: A file created on an editor's computer is never removed by syncing down before it has reached the NAS.
- **SYN-036** A laptop's record of holding the only copy of some originals expired. Must: A computer stays marked as holding unique originals until each of those files is confirmed on the server, however long that takes.
- **SYN-056** Signing in or restarting silently resumed syncing the editor had paused. Must: While Pause is on nothing starts, through sign-in, restart, update or another stop's release, and sync never starts with nobody signed in.
- **SYN-071** After an update, a laptop started downloading its whole project again. Must: An update never makes a computer re-download files it already holds intact; if names must change, local copies are renamed in place.
- **SYN-079** A sync drive pulled mid-upload got the same calm note as a finished day. Must: Unplugging with uploads owed, or of unknown direction, names what is owed and reminds every 30 minutes, across restarts, until it returns; any narrowing needs the owner's agreement.
- **SYN-098** A laptop opened after sleep did not sync for many minutes. Must: A computer that wakes from sleep syncs at once, not at its next timer slot.
- **SYN-119** Several remote editors syncing at once share the studio's upload. Must: Transfers to several editors run together and together fill the server's uplink, none waiting for another to finish.
- **SYN-125** Transfers sat at 0% forever after an editor's computer was reinstalled. Must: When a known computer appears with a new sync identity, the dashboard says so and lets an admin approve it, after which transfers resume within a minute.
- **SYN-135** Power loss can leave a full-size file of zeros that a size check calls good. Must: A zero-filled file left by a power cut is never sent over a good copy on the server or another computer.

### Fixed, never shipped

- **SYN-028** An editor with footage backed up locally wants to upload it, downloading nothing. Must: A project can be ticked upload-only per computer: every file except system clutter and temporary files goes up, nothing comes down, and it never reads as out of sync.
- **SYN-033** "Remove from this computer" deleted footage the NAS had never received. Must: Removal is refused while any local file, of any age or date, is not on the NAS at the same size and content; it lists and keeps each one.
- **SYN-050** Suspending one editor froze every untick across the studio. Must: Removals caused by a recorded admin act apply at once, an admin can approve a held batch, the limit scales with studio size, and unexplained mass removals stay refused.
- **SYN-113** After a re-tick or a mode change, new files could be skipped for hours. Must: After a project is re-ticked or its mode changes, the next pass examines every file in it.
- **SYN-133** Synology's built-in secure file transfer silently cut proxies over 514 MiB short. Must: Transfer settings known to truncate on that NAS are refused, and a downloaded file shorter than the source is never marked done.

## The Footage Sorter and camera cards

### Question only

- **SRT-131** Sorting never loses an original, and every move is previewed first. Must: Every move offers a dry run, can run on one clip, needs approval before it runs, and never deletes or overwrites an original.
  - **Question:** Now that filing runs on its own with a manual override, must a move out of staging still wait for an admin's approval?

### Still open

- **SRT-013** Camera cards disappeared from the page whenever the server restarted. Must: A card still in its reader stays listed across a server restart.
- **SRT-041** Two recorders started together can write identical-looking files. Must: A copy proves a card file safe only when it is tied to that card; two cards' look-alike files never vouch for each other.
- **SRT-093** A double-backup percentage, and a tape mark on clips with a tape copy. Must: The view shows the percent of master files with a second counting copy, and a clip with a tape copy carries a small non-green mark naming the tapes.
- **SRT-094** Tapes in the standard tape file system list in seconds but share one letter. Must: A tape is identified by its barcode, never its letter, and a clip only on tape offers a restore request naming the tapes and where they are kept.
- **SRT-105** A drive sitting in a drawer stays searchable as last seen. Must: Every file ever listed on a drive stays searchable while it is unplugged, shown with its drive and last-seen date and marked as not on the NAS.
- **SRT-119** Two weeks of camera footage were on no drive, shown only by numbering gaps. Must: Gaps in each camera's clip numbering are flagged with the dates either side, so cards never offloaded are noticed.
- **SRT-123** Clips the automatic match cannot place confidently are reviewed and sorted by hand. Must: Unconfident matches wait for a person; each proposed match shows why, plays the audio, shows transcript and paired clips, and nothing moves until approved or adjusted.
- **SRT-134** An interrupted move was left "moving" for ever. Must: After a move fails or the app restarts mid-move, the product rescans and shows which files moved and which did not.
- **SRT-145** Field audio is placed beside its video by time, then waveform, then speech. Must: Every field recording ends up in its shoot's audio folder beside the matching video, duplicates set aside not deleted, trying time, then waveform, then transcript.
- **SRT-147** Loose field recordings are found by format, length and name. Must: A search for unplaced field audio on every computer and drive keeps only unbroken 32-bit WAV files of plausible length not named like music.
- **SRT-152** The thumbnail on screen waited behind hours of background thumbnails. Must: A thumbnail on screen is made before any background thumbnail still waiting.
- **SRT-173** The archive sorts and searches every place footage lives, four ways. Must: One search covers the NAS, every known drive, the cloud and tapes, sorts by project, date, name, camera, size and copies, with exact, loose, cross-language and assistant modes.
- **SRT-174** An English search must find Chinese names, and the reverse. Must: Name searches match across Traditional and Simplified, English, Chinese and pinyin, any two-character query finds every name containing it, and corrected translations are kept.
- **SRT-176** An assistant search shows the searches it ran and sends only names out. Must: An assistant answer lists every search it ran as an editable query with a reason per result, and only file metadata ever leaves the NAS.

### Outcome not found

- **SRT-006** A camera card formatted in camera must still be recognised. Must: Each card keeps a name and number recognised after in-camera formatting, guessed from its kind, capacity and days of use, with the owner confirming a guess.
- **SRT-009** A card swapped in right after another was pulled raised no prompt. Must: Every card inserted, including straight after another is pulled, appears within seconds without a click, and the sorter says so when card detection is not running.
- **SRT-010** Each inserted card opened another browser tab. Must: A new card shows in an already open sorter tab, a tab opens only if none is open, and every card inserted while it runs joins its card list.
- **SRT-027** Sony RAW stills carry a ready JPEG preview. Must: Every camera RAW still shows a thumbnail taken from its embedded preview.
- **SRT-028** Some FX3 clips have no sound track and kept failing as errors. Must: A soundless clip is recognised as such, reported once as unmatchable by speech, and never retried as a failure.
- **SRT-057** Clicking copy in the card sorter gave an unexplained error. Must: A failed copy names the clip, the destination and the reason in plain words, and says what was partly copied.
- **SRT-058** Before copying, every clip on a card is accounted for. Must: Before copying, any clip neither backed up nor assigned raises a warning, and the summary shows backed-up and not-backed-up counts.
- **SRT-061** A card can be used on several days before it is backed up. Must: Logging a card's use on a new day always works and keeps earlier uses, and the card list includes every card the studio owns.
- **SRT-063** The card recorder page installs as an app on phones. Must: The card recorder installs to the home screen on iOS and Android and opens as an app.
- **SRT-077** A long copy to the NAS ran unsteadily, then stopped moving unnoticed. Must: A long copy runs steadily near the link's capacity, shows live speed, says when it stops moving, and shows where any slowdown comes from.
- **SRT-088** A card counted as backed up while 375 of its files had one copy. Must: Before calling a card safe to wipe, the product shows how many separate copies each clip has and names clips with only one.
- **SRT-103** Thousands of Chinese NAS file names were recorded as question marks. Must: The record stores every file name exactly as it is on disk, and an interrupted repair resumes where it stopped.
- **SRT-106** Footage on only one laptop drive was lost track of when the drive moved. Must: Footage held on only one drive is found again after renames, folder moves or the drive moving computers, and its backup state stays true.
- **SRT-116** Every interviewee on the roster appears as a destination, greyed until used. Must: Every roster person appears in each episode's destinations, greyed and not created until assigned clips; people in several episodes show greyed in the others.
- **SRT-118** A second camera counts as covered when two cameras' clips land on one person. Must: A missing-camera or missing-sound warning clears whenever a destination holds two cameras' clips or a matching recorder file, whatever the folders are called.
- **SRT-125** Which card goes to which camera folder is studio data. Must: Camera-to-folder naming is data an owner can change without changing or reinstalling the program.
- **SRT-130** Clips moved into a folder with an accented name did not show there. Must: A move into a folder whose name has accented or non-Latin letters lands there and is shown there.
- **SRT-141** A file dragged in from Explorer did not join the plan. Must: A file dragged from Explorer onto a destination joins the plan for that destination and shows there at once.
- **SRT-167** A clip and its destination are each one click from the other. Must: Selecting a clip opens its destination, and its menu offers open in source (in the app and in Explorer) and show in destinations.
- **SRT-168** A clip's menu offers other suggestions and the other camera's footage of that moment. Must: A clip's menu lists alternative destinations and the folders of other cameras that recorded the same date and time, each openable.
- **SRT-170** The clip view plays sound, resizes thumbnails, sorts by length and filters by day. Must: The clip view can play sound, change thumbnail size, sort by duration, and filter to every clip from a picked day.
- **SRT-171** The sorter page showed a "too many open files" error. Must: The sorter keeps its open files bounded during long scans, and the page always loads.
- **SRT-172** The calendar connect button flashed up and disappeared. Must: The calendar connect control stays visible until the calendar is connected, and a failed connection says why.
- **SRT-175** Searching a person's name shows their event and its clips. Must: A search by event or folder name, in Chinese or English, returns the event with its date and its assigned clips.

### Fixed, never shipped

- **SRT-014** "Which drive is which" question windows stacked up without end. Must: At most one question window is shown at a time, and nothing asks again while one is open.
- **SRT-018** A Sony proxy folder's own XML file was read as the clip's metadata. Must: A clip's identity and camera model come from the metadata file beside its master, never from one in its proxy folder.
- **SRT-026** Camera RAW video has no picture to show until its proxy exists. Must: A RAW clip previews from its proxy, says plainly when it has none yet, and picks up the picture soon after a proxy appears.
- **SRT-049** Copies made to the field SSD alone were never carried to the second drive. Must: Every copy owed to a second drive is remembered across restarts and starts by itself, or asks, as soon as that drive appears.
- **SRT-051** A resumed copy saw a clip's master and skipped its missing proxy. Must: A clip counts as copied only when every file chosen for it (master, and proxy and metadata if chosen) is present at full size; missing ones are copied.
- **SRT-056** An empty 2 TB SSD showed 0 GB free for a trip's first copy. Must: Free space for a folder not yet created is the free space of the drive it will be created on.
- **SRT-065** Reading a copy straight back checks the computer's memory, not the drive. Must: A copy is called verified only after content read from the drive itself, bypassing the cache, matches the source.
- **SRT-067** A stopped or resumed card copy left unchecked copies counted as safe. Must: A copy counts only after its content is checked against the card, and a resumed run checks every earlier unchecked copy it skips.
- **SRT-068** A drive that hung mid-check got 454 good copies marked bad. Must: A read error during checking stops the check and says so; only a proven size or content mismatch marks a copy bad.
- **SRT-073** The field SSD hung after about 300 GB of non-stop writing. Must: Long field copies pause to let the drive rest (for example 10 minutes after every 150 GB), show that it is resting, and stay cancellable.
- **SRT-085** Two copies on one physical disk counted as two backups. Must: Copies are counted per physical disk, rechecked when drives change, so two partitions of one disk never count as two copies.
- **SRT-086** A card whose folder could not be read was called "Safe to format". Must: If any part of a card cannot be read, it is never called safe to format, and the page names what could not be read.
- **SRT-090** Unplugging a backup drive removed its copies from the card's count. Must: Verified copies on an unplugged backup drive still count, shown as on that drive while it is away.
- **SRT-092** Copy badges are outlined when healthy and filled only for a problem. Must: Copy-count badges are outlined when healthy, filled gold when not backed up, and red when only on a laptop, card or client drive.
- **SRT-096** A laptop's system drive is never scanned whole. Must: A computer's system drive is never offered as a new drive; only folders explicitly watched on it are scanned or backed up.
- **SRT-098** A move the product made itself must not raise "where did these go?". Must: Any move the product performs updates the copy record at once, so the next scan raises no question about the moved files.
- **SRT-102** One odd file name must never make a drive unscannable. Must: A file the scan cannot record is skipped and counted, and the rest of the drive is still recorded.
- **SRT-104** A computer cannot pass off a USB stick as the NAS. Must: A computer records copies only on drives it identifies by serial, and a report disagreeing with a live copy is counted as a conflict, never replacing it.
- **SRT-107** The record of where copies live must survive losing the NAS. Must: The copy record and sorter state are copied nightly in a consistent, integrity-checked form, seven kept, and carried in the cloud backup.
- **SRT-148** Loose waveform matching split one take's two channels across two shoots. Must: A single-clip audio match is accepted only when it clearly beats the next candidate, and both channels of a take stay together.
- **SRT-149** The same speech in Simplified and Traditional Chinese never matched. Must: Chinese text is compared in one script, so identical speech matches whichever engine wrote either side.
- **SRT-150** Paid transcription credit ran out partway through thousands of files. Must: Running out of paid transcription keeps every finished transcript, resumes skipping finished files, and finishes the rest with local transcription unattended.
- **SRT-180** A resumed download continues only its own unfinished files. Must: Full-size files are skipped, only files the download itself marked in progress are continued, and a same-name file without that mark is left alone and reported.
- **SRT-181** A download never delivers the wrong file after a rescan. Must: Every requested file is checked by name before it is sent, a mismatch asks to start again, and a resume answered with the whole file restarts that file.
- **SRT-182** Any footage folder can be shared by an expiring link. Must: An admin links one folder, lasting 14 days by default and 365 at most, with an off switch; a whole root is refused; holders download files or a zip.
- **SRT-183** A shared folder link must never reach anything outside its folder. Must: Unknown, revoked and expired links answer not found, no path climbs out, and links, hidden files, system junk and half-written files are never listed or served.

## The app on each editor's computer

### Still open

- **APP-026** Every setup turned off incoming file sharing on the editor's PC without saying so. Must: Any local share the product makes is closed to other computers, the PC's other file sharing keeps working, and no unrelated system setting changes unannounced.
- **APP-043** Changing the studio's drive letter after install silently split the fleet. Must: A change of drive letter or tree name after computers are installed is either refused or carried to every computer, never silently ignored.
- **APP-055** A Mac app froze at start with its sync folder on an exFAT drive. Must: A stuck file-change watch never freezes the app; the tray, Resolve checks and sync keep running.
- **APP-060** Fourteen "crashes" on one computer were all deliberate stops. Must: A deliberate stop (upgrade, quit, an operator's kill) is never counted as a crash, and two upgrade routes on one computer never kill each other's result.
- **APP-073** A very long menu line stretched the right-click menu across the whole screen. Must: Tray menu lines stay short, about 80 characters at most, with full explanations in a window.
- **APP-074** Tray hover text cut to 127 characters still failed on Windows. Must: Tray hover text always fits Windows' 128-unit limit, measured the way Windows counts, including emoji and rare Chinese characters.
- **APP-082** Right-clicking the tray icon opened the menu seconds late, or not at all. Must: A right-click opens the tray menu within half a second, and highlighting follows the mouse instantly, every time, whatever Resolve or the sync is doing.
- **APP-091** A folder picker left open on a Mac blocked every other window and update. Must: A picker left open never silently blocks fixes, settings or updates; the app says what is waiting on it.
- **APP-136** Files the product keeps on an editor's computer grew without limit. Must: Every file the product stores on an editor's computer has a size or age limit and is removed when it passes it.
- **APP-141** Any web page could drive the editor's local helper. Must: Only the studio's own pages can trigger actions on an editor's computer, untrusted text never runs as script there, and repeated status checks spawn bounded work.

### Outcome not found

- **APP-006** Rewriting the Windows user search path flattened its variables for good. Must: Install and uninstall change only their own search-path entries and keep every other entry in its unexpanded form.
- **APP-020** A whole drive could be chosen as the editor's local project folder. Must: The editor's local project folder can never be a bare drive or volume root.
- **APP-021** A new editor could not download the installer before joining the private network. Must: A new editor downloads the installer without being on the private network, and setup never asks for a value it already has.
- **APP-024** A computer set up for a second site kept talking to the first. Must: After setup for a new site, the computer holds only that site's credential and reports only to that site's server.
- **APP-027** The installer took a drive letter a disk used, and another program's sync. Must: Setup never claims a drive letter a disk uses and never adopts a sync process it did not start.
- **APP-029** A Mac app loses Full Disk Access after every update. Must: Mac builds carry a stable developer identity; the app checks Full Disk Access at every start and tells the editor exactly how to grant it.
- **APP-065** A restart, update or Quit cut off a multi-hour copy halfway. Must: No automatic restart or update starts during a copy, relink or sharing job; Quit names what is in flight and asks, proceeding if that cannot be checked.
- **APP-085** "Open dashboard" did nothing when clicked. Must: If opening the dashboard fails, the person is told and shown the address to open by hand.
- **APP-086** An editor's app was not showing up on his Mac. Must: While the app runs on a Mac its menu-bar presence is visible, and the dashboard shows whether that computer is reporting.
- **APP-097** One unanswered dialog silenced every other project's prompts and held back updates all day. Must: Prompts for different projects are never merged or suppressed by an open dialog, and an update waiting on an open dialog shows that on the dashboard.
- **APP-133** An update must never reset a computer's own settings. Must: After any update, every setting chosen on that computer, including where Resolve is installed, is unchanged.
- **APP-142** An admin's request for diagnostics was dropped or refused for good. Must: An admin's request is marked done only once it succeeds and is retried until then; every "in progress" mark expires after a generous limit.
- **APP-144** A Mac laptop on battery with its lid closed sleeps despite keep-awake. Must: When an upload is owed, the editor is warned that closing the lid on battery stops it, and the dashboard shows this as the reason.
- **APP-151** Uninstalling left the computer able to reach the studio's server. Must: After uninstall, no credential that lets the computer reach the studio's server remains on it.

### Fixed, never shipped

- **APP-004** On stock Windows 11 the first install ended "not ready", missing a helper tool. Must: Setup installs exact, verified helper versions, checks each install's real result, finds them without a restart, and never records a version-numbered package-manager path.
- **APP-028** Unsigned installers meet a Windows warning whose default is Don't run, and macOS blocks them. Must: The download page walks through both, including re-allowing after an update and checking the checksum; each program names the vendor, never the customer, as publisher.
- **APP-031** After a Windows install the app could not read or save its own state. Must: After any install or update every file in the app's state folder is readable and writable, the app repairs this at start, and an unsavable safety stop is reported.
- **APP-064** Quit, cancel or an update left a transfer or encoder running after the app. Must: Quit, cancel, restart and update stop every helper the app started (waiting up to 40 seconds), and at start any leftover helper is stopped first.

## The b-roll archive

### Still open

- **BRO-027** Zero-byte files all looked like duplicates of one random clip. Must: Zero-byte files are flagged as broken downloads and never treated as duplicates of anything.
- **BRO-066** A clip could show another clip's preview still. Must: Each clip's preview still belongs to that clip alone and can never collide with another clip's.
- **BRO-095** A batch read "40 clips, 38 indexed" with no explanation. Must: Every clip dropped appears in its batch with an outcome, including "skipped, duplicate of" the kept clip, so counts always add up.
- **BRO-126** The owner wants to share one folder with a client himself, link first. Must: An editor picks any tree folder and immediately gets a client link with previews, without waiting for indexing or publishing anything else.

### Outcome not found

- **BRO-012** Two archive names differing only in case land in one folder. Must: Archive names are compared without case, and a new name matching an existing one apart from case is refused or renamed.
- **BRO-051** A search can be limited to what is seen or to what is said. Must: A search can be restricted to picture descriptions or to the spoken transcript, and the results say which was searched.
- **BRO-077** Camera mis-taps under a second long failed preview making. Must: A clip shorter than the sampling interval gets a preview from its first frame, or is skipped with a stated reason.
- **BRO-081** Copying 85 GB of previews to the NAS over 10GbE took far longer than minutes. Must: A bulk copy to the NAS shows progress and speed, and moves many small files at close to the link's capacity.
- **BRO-111** Send to Resolve offers both append and place on top. Must: The person chooses between appending the clip at the timeline's end and placing it on a track above, at the playhead.
- **BRO-112** Sending a b-roll clip to Resolve showed an error. Must: Send to Resolve either places the clip in the open project or says in plain words why not and what to do.

### Fixed, never shipped

- **BRO-017** Own-shoot footage files under its project's name with every shoot subfolder kept. Must: Own-shoot footage files under the project's spoken name with the shoot's folders shown to any depth; a later rename moves, never recopies; footage timelines use is never re-filed.

## The dashboard

### Still open

- **DSH-001** The home page is an Overview, not the sync page. Must: Home shows problems, health, a sync summary, each module's status, the version, and quick links to commonly used settings.
- **DSH-002** A Sync menu holds Projects, Transfers and a per-computer view. Must: Sync opens a menu, on hover with a mouse and on tap on touch, offering Projects, Transfers and a per-computer view, each its own page.
- **DSH-003** A Projects page lists every project to open, manage, tick and untick. Must: One page lists all projects; opening one offers every action on that project, including ticking and unticking it for sync.
- **DSH-004** Settings are grouped by what they do and have their own search. Must: Settings are grouped by purpose, and a search inside Settings finds and opens any setting by name, returning settings only.
- **DSH-005** A search in the menu bar opens any module, setting, project, computer or person. Must: Typing a name in the menu-bar search finds and opens any module, setting, project, computer or person.
- **DSH-051** New footage took hours to show as on the server. Must: A file that reached the server shows as on the server within five minutes, at 500 projects as at 5.
- **DSH-052** Clips in a folder borrowed from another project were missing from its totals. Must: A project's media figures include files in folders it borrows, labelled as borrowed.
- **DSH-094** Alerts counted deliberate restarts as crashes. Must: Alerts never count a deliberate restart as a crash, and never flag running a newer release than the vendor offers.
- **DSH-126** The home page grew slow as the fleet grew. Must: The home page loads within a second for 20 computers and stays fast at 50 editors and 400 projects; a refresh with nothing changed costs little.
- **DSH-127** One slow save froze the dashboard for everyone. Must: While one write waits, every other page and report is answered within a second; "busy" answers at once, background writes wait their turn, and the slow writer is recorded.

### Outcome not found

- **DSH-007** An admin can open any person and see what they have and lack. Must: An admin opening any person sees each project they ticked, per computer: what has synced, what has not, and what is missing.
- **DSH-026** A wrong clock on the NAS must not turn every computer red. Must: A wrong server clock is reported as itself and never marks healthy computers as stale.
- **DSH-033** Choosing what a computer syncs starts from a person, then a computer. Must: Where an admin sets what a computer syncs, nothing is listed until a person and a computer are chosen, preselected when the site has only one.
- **DSH-053** A computer's file counts showed files it could not have. Must: A computer's file counts come only from files found on that computer, and one computer reports under one identity.
- **DSH-098** The admin chooses which kinds of alert are mailed. Must: Each alert kind can be switched on or off for mail by an admin, and a switched-off kind still shows on the dashboard.
- **DSH-102** A failed alert and a failed editor install reached nobody. Must: An alert that cannot be sent shows as undelivered until it goes, and an editor's failed install appears on the dashboard.
- **DSH-104** Connecting an AI provider is a short click-through setup. Must: Only active providers are listed, plus "add new": a picker, then a guided setup (notice, verified install, browser sign-in with code, test), with the manual path still offered.

### Fixed, never shipped

- **DSH-048** Projects are linked only on an exact name, never on a guess. Must: A project is linked automatically only on an exact name match with one project; any partial match asks a person, and no guess is stored unconfirmed.
- **DSH-084** A network check that could not read the network mailed "cleared". Must: A check that cannot read its evidence reports "could not check", never "cleared" or OK, and sends no all-clear mail.
- **DSH-085** A check failing now still showed OK because it once passed. Must: A check shows OK only if its latest run passed recently; one failing shows failed, and one not run recently shows not checked.

## The server: installing it and keeping it running

### Still open

- **SRV-017** The owner: a customer shows setup their folder layout instead of adopting ours. Must: Setup derives the project layout from one or more sample project folders, and no folder name of this studio is required anywhere.
- **SRV-060** Nothing recorded which code a deploy shipped, so nothing could check it. Must: Every deploy records what it shipped with per-file checksums, and the server shows "not checked" rather than a verdict when that record is missing.
- **SRV-073** A NAS mounts each snapshot folder only when it is first opened. Must: The recovery page sees every snapshot, including ones never opened since the server started, and explains an empty snapshot folder as not visible.
- **SRV-084** Old builds, backups and histories grew without limit on the server's disk. Must: Every snapshot, backup, build and history the product keeps expires by a stated age or count, and the data disk's use is shown.
- **SRV-088** A 1.4 GB publish that dropped near the end started again from zero. Must: An interrupted large publish to the NAS resumes from the files already delivered, each verified by its content.
- **SRV-089** Cold archive storage is cheap to keep and slow and costly to restore. Must: Any off-site plan for originals states monthly cost, first-upload time on the studio uplink (about 3 weeks at 30 MB/s), restore time and restore cost.
- **SRV-091** The NAS's single long-distance streams jump from 0.3 to 17 MB/s with BBR. Must: The NAS uses congestion control fit for long, lossy links, and any network tuning the product depends on is re-checked after every NAS reboot.
- **SRV-093** The owner: off-site backup is ticked per project on the dashboard. Must: Each project can be ticked for off-site backup; an unticked one shows when its copy expires, and a ticked one with no upload in 3 days raises an alert.
- **SRV-096** The off-site copy could not be read without a key kept only on the NAS. Must: The off-site backup's key is held somewhere other than the NAS, and the product warns until the owner confirms it is stored safely.
- **SRV-097** Restoring from the off-site copy had never been tried. Must: A small project is restored and rendered from the off-site copy on a laptop as a rehearsal, and a sample of the backup is verified monthly.

### Outcome not found

- **SRV-020** Nobody but its makers had ever installed the product on a clean NAS. Must: On a clean NAS, following only the published guide, a newcomer reaches first sync, first update and first rollback on one Windows and one Mac editor.
- **SRV-041** Settings the operator changed did nothing, or reverted at an update. Must: Every setting takes effect when changed or the dashboard says why not, and updates and reinstalls keep every setting, secret and saved choice, showing any change first.
- **SRV-042** The owner: updating the server must not take the dashboard away. Must: A server update keeps the dashboard and open editor pages answering throughout, with no gap a person or an editor's app can notice.
- **SRV-054** A broken optional part took the whole dashboard down. Must: No failure in an optional part ever stops the dashboard starting or serving; that part is shown unavailable with its reason.
- **SRV-061** A missing server database would start fresh and reopen first-admin setup. Must: A missing or damaged database stops the server with a clear message, every data upgrade backs up first, and a locked-out admin has a documented recovery.
- **SRV-083** Camera originals deleted over the NAS file share had no way back. Must: An original deleted through the file share can be restored by an admin for a stated period, and editors cannot delete originals by default.
- **SRV-086** Nothing warned before the NAS filled or when backups missed something. Must: The dashboard warns before NAS free space runs low and says when there is no offsite copy or Resolve's project database is not backed up.
- **SRV-128** A NAS pool about 90% full made every read and listing crawl. Must: The product warns before the NAS pool passes about 80% full, and names fullness as the cause when reads slow down.

### Fixed, never shipped

- **SRV-002** TrueNAS 26 drops the management interface older TrueNAS versions answer. Must: Installing and managing works on TrueNAS 25 and 26 with no setting, and a NAS version the product cannot drive is refused with a named reason.
- **SRV-006** A TrueNAS API key was refused when presented as the admin. Must: The server signs in to the NAS as the key's own account, and a refused sign-in names the account that was presented.
- **SRV-007** Synology and TrueNAS number users differently, so a fixed account number fails. Must: Install uses the real NAS account the server runs as, and every start warns, naming account and owner, when that account does not own its data folder.
- **SRV-013** Resolve's project database server ships with a well-known superuser password. Must: Any Resolve project database the product sets up gets a random password, accepts only the studio's LAN and private network, and is backed up.
- **SRV-015** The owner: a customer installs two things, then a browser wizard does the rest. Must: A new studio is set up from a browser wizard after those installs, with no commands, builds, signing keys or manual steps on the customer's side.
- **SRV-021** The admin could see setup problems but had no way to fix them. Must: Every value setup checks can be entered in setup itself, and every finding's next action is doable from the product's pages, never by editing files or redeploying.
- **SRV-026** A fresh install's sync service restart-looped because it could not write its folders. Must: On a fresh install every server service starts once and stays up, and every folder it writes exists and is writable by the account it runs as.
- **SRV-027** Re-running the install with the build already running tore the app down. Must: Re-running the install with the build already running leaves the running server untouched.
- **SRV-030** Setup said the dashboard was published while only the server could reach it. Must: The publishing step turns green only when the dashboard answers over the private network at a valid secure address.
- **SRV-034** Changing the tree's drive letter after computers joined would break every path. Must: The drive letter and tree name are fixed once any computer has joined, and are shown read-only.
- **SRV-045** A server update that crashed on boot was reverted, then reapplied for ever. Must: A failed server update is reverted and never reapplied automatically.
- **SRV-113** The server lost its own network link and nobody heard for a day. Must: The server alerts once, within minutes, when its own network link is down or its sign-in nears expiry, and when many computers fall silent together.
- **SRV-117** Server memory grew without limit as long clips arrived at once. Must: Opening an episode of many two-hour interviews with no waveforms yet keeps server memory under a fixed ceiling, and no single feature can exhaust it.
- **SRV-118** A NAS ships with a self-signed certificate. Must: The NAS certificate seen at first connection is trusted, a changed one is refused, and turning certificate checking off is never offered.
- **SRV-121** A dropped NAS connection must not make a change happen twice. Must: After a dropped connection the server retries reads and unsent requests once, and never re-sends a change that may already have landed.
- **SRV-124** A helper's admin page on the server was open to the network with no login. Must: No admin page the server runs is reachable without a login, and a login the admin already set is kept, never replaced.

## The whole product

### Still open

- **BRD-035** One action's several refusals stacked identical red notices. Must: Several refusals from one action show as one summary with a count, the details kept where they can be read.
- **ALL-028** Small screen faults: undersized buttons, clipped placeholders, mislabelled searches. Must: Every touch target is at least 44 x 44 px, no label is clipped at 1440 px, empty panels take no room, and every label says what it does.
- **ALL-038** The product's own name was spelled two ways. Must: The product's name is spelled one way in every sentence a person reads.
- **ALL-039** Browser tabs showed the product's name, not the studio's. Must: Every browser tab title, search and download pages included, carries the studio's own name from site settings.

### Outcome not found

- **ALL-009** A feature switched off kept its work running on the server. Must: Within a minute of a feature being switched off, none of its work is still running anywhere.
- **ALL-036** The owner: no customer's name, drive letter or example in what ships. Must: A fresh site shows no name, folder, drive letter, language default or example taken from another studio; every such value comes from the site's own settings.
- **ALL-041** Screens showed internal codes, ids and raw errors instead of sentences. Must: Every state, refusal and error is a plain sentence naming cause and next step; raw values sit one click away, and tests check the rendered text.
- **ALL-061** A question window opened out of sight, so a run seemed to do nothing. Must: Any window waiting for a person's answer comes to the front and stays on top until answered.

### Fixed, never shipped

- **ALL-024** Fonts ship with the product; Chinese names use a Chinese-capable face. Must: No page loads fonts or other assets from the internet, and Chinese folder and clip names always render in a Chinese-capable face.
- **ALL-046** "Contact support" never said who or where support is. Must: Every "contact support" line, mail, help page and setup finish names a real support contact, which a reseller or site can replace.
- **ALL-053** An optional feature a site lacks showed broken parts or a permanent "not checked". Must: When a feature is not enabled or present, its controls, chips, banners and checks are hidden and the rest of the page is unchanged.
- **ALL-089** Customer builds use only the studio's own paid assistant key. Must: In a customer build every assistant call uses the site's own paid key, no setting enables subscription sign-in, nothing is bundled, and keys never show in full.

## Timeline Cards: footage in, ready to cut

### Still open

- **CFI-037** Better audio shorter than the old left a silent tail under a cut. Must: An audio replacement that cannot cover every span the cuts use either fills the tail from the old sound or refuses; it never leaves silence.
- **CFI-061** Mandarin speech-to-text writes soundalike characters, hiding search terms. Must: Transcript search finds soundalike spellings of a Mandarin term, so a misheard word never hides the passage.
- **CFI-072** A transcript, its translation, word times and word links are one file. Must: Correcting a word never detaches its timing or English, a readable Markdown copy is always kept in step, and old transcripts import keeping every paragraph reference.
- **CFI-088** Word-link accuracy is measured before any other linker or offline option is used. Must: Word-link quality is scored against a hand-checked answer key, and any dedicated aligner or offline option is compared on the same paragraphs before it ships.
- **CFI-107** An imported paragraph that cannot be placed says only "text not found". Must: An imported paragraph that cannot be placed is kept, listed, and shows the closest stretch of the recording and how similar it was.

### Outcome not found

- **CFI-062** A batch transcription silently skipped 16 of 51 clips. Must: After a batch, every clip is checked for a transcript, and each missing one is retried or listed.
- **CFI-066** Short cuts showed words not in the edit, and audible words greyed out. Must: A card shows exactly the words audible within its cut, with none heard greyed and none unheard shown.
- **CFI-086** Paragraphs whose word links failed were never asked again. Must: Failed paragraphs are retried on the next run, and any that fail twice are shown with a plain reason such as "English is a summary, not a translation".
- **CFI-095** A corrected transcript left the old words on cuts already made. Must: A transcript added or changed shows on every card and saved cut within minutes, with no restart and no edit.
- **CFI-099** The editor found no transcripts in an episode's folder. Must: Opening an episode lists every transcript in it, or says which files it rejected and why.

### Fixed, never shipped

- **CFI-051** When paid transcription runs out of credit, transcription carries on locally. Must: Transcription continues on the local engine when the paid service refuses for lack of credit, and each transcript says which engine made it.
- **CFI-105** Drawing a waveform held a whole decoded clip in memory. Must: Waveforms for clips of any length are made in bounded memory, and several at once cannot exhaust the machine.

## Timeline Cards: the board

### Question only

- **BRD-045** A montage draws only on downloaded news and archive footage. Must: A montage's pool holds only downloaded news and archive clips, never the film's own interviews or their transcripts.
  - **Question:** Are studio anchors' link lines still excluded? An early montage ruling excluded them, later rulings favour newsreader delivery.

### Still open

- **BRD-001** Planning is a hand-worked board of theme columns holding transcript paragraphs. Must: A person drags transcript paragraphs onto the board as cards, makes, names and reorders theme columns, and the board saves as a self-contained Markdown file.
- **BRD-002** The board is the first step of Timeline Cards, offered pre-sorted or empty. Must: The order is clips in, board, cut, Resolve; processing offers a first sort, a person can start empty, and nothing goes from board straight to Resolve.
- **BRD-003** The board has a notes area, and the assistant reworks the board from it. Must: A person writes notes on the board and calls the assistant, which reworks themes and card placement from those notes as proposals.

### Outcome not found

- **BRD-008** An episode's board opens on a phone from a short, memorable address. Must: Every episode board opens on a phone from a short, memorable address, reachable without knowing a file path.
- **BRD-010** Planning documents reach every editor's computer on their own, with a "sync now". Must: Planning documents reach every editor's computer within minutes unaided, and a "sync now" action does a full round trip and says what it did.
- **BRD-013** Re-paragraphing a transcript left cards on other boards pointing at nothing. Must: When a transcript's paragraphs are split or merged, every card citing them on any board points to the paragraph now holding its text.
- **BRD-015** A card's full text could not be read during review. Must: A card's full text is readable wherever a decision is made about it, scrolling if it is long.
- **BRD-016** Dragging a card opens a gap and the others shuffle; each drag can be undone. Must: A dropped card opens a gap so no card covers another, columns reorder, each drag is one undo step back to the exact prior board, and Escape cancels a drag.
- **BRD-017** Setting cards aside takes one key and works on several at once. Must: One or many selected cards are set aside with one key, and set-aside cards count as handled.
- **BRD-020** The board said 35 cards remained but showed none of them. Must: Every card counted as remaining can be shown and acted on from the count itself.
- **BRD-021** Reopening the board on a later day showed an empty board. Must: Reopening an episode's board resumes its latest saved state, whatever the date.
- **BRD-031** The accept and decline offer did not match the card on screen. Must: Accept and decline always act on the proposal shown, and the card shown always belongs to that proposal.
- **BRD-034** Every beat in the owner's notes must reach the board. Must: Every beat in the notes appears on the board, a heading broken over lines is read as one, and an unreadable heading is reported by name.

### Fixed, never shipped

- **BRD-014** A placed long quote lost its last line. Must: A card handed to the cut plays every word of its marked passage through to its end, however long.

## Timeline Cards: the editor

### Still open

- **CE1-066** One cut list saved from two places at once can lose one side's change. Must: When one cut list is saved from two places at once, both changes are kept or the second is refused, with the conflict shown to both people.
- **CE1-090** Zoomed in, the playing playhead jumped and the strip did not follow. Must: A playing playhead moves smoothly at every zoom, and the strip pages forward when the head reaches its edge unless the person is panning.
- **CE1-137** Any cut list of any episode can be kept offline. Must: Any cut list of any episode can be downloaded and listed offline, and its queued edits replay without it being opened first.
- **CE1-144** Updating one episode's offline copy deleted every other episode's. Must: Each episode's offline copy survives updates to the others, and downloaded media is removed when no longer needed or space runs low.
- **CE2-062** A multicam clip in Resolve has no file path of its own. Must: Previewing a cut from a multicam clip shows picture taken from its angles' source files.
- **CE2-084** Finding words stays instant at hundreds of transcripts. Must: Find across 500 transcripts answers within a second, a newer keystroke cancels the older search, and the transcript panel redraws within 60 ms.
- **CE2-096** Closing a tab must stop the assistant work it started. Must: Closing the tab cancels its assistant work within seconds, and interactive requests never wait behind background ones.
- **CE2-123** An offline edit that could not be stored was shown as made. Must: If an offline edit cannot be stored, the page says so at once and the edit is not shown as saved.
- **CE2-131** An editor working offline could be thrown out of their episode. Must: Presence follows a person actually working, offline or on a sleeping phone; unsent work keeps an episode occupied; a closer is told who was last in and when.
- **CE2-139** A phone paints an installed app's frame from its declared colours. Must: The declared theme and icon colours match the page's current look, and changing them is treated as visible to every installed phone.
- **CE2-153** The lane's button bar does not fit a 390 px phone. Must: Every control bar, close included, fits and can be tapped on a 390 px portrait phone without clipping or sideways scrolling.
- **CE2-172** The cut view must stay smooth on a phone at 500 cards. Must: At 500 cards one change updates the edit view on a mid-range phone within one frame (16 ms).
- **CE2-175** Closing an episode leaked about 128 MB until memory ran out. Must: Closing an episode frees everything it used, so opening and closing episodes for days never exhausts the server.
- **CE3-017** "Fit" showed only the first quarter of a 2.5-hour cut. Must: Fit shows a 2.5-hour cut whole, or says its limit and keeps the head in view.
- **CE3-022** A held trim key during playback shrank a whole cut to frame-long pieces. Must: Holding an editing key never repeats the edit; one press is one edit; every cut-list revision is kept so a damaged list can be restored.
- **CE3-047** The picture drifted 0.13 s behind the sound during playback. Must: During playback the picture stays within three frames of the sound, on the local network and over a slow remote link.
- **CE3-052** Dropping one search result onto a cut wiped the rest of the results. Must: Dropping one result never silently loses the others; results stay until the person runs a new search or closes them.
  - **Question:** should transcript search results survive every refresh of the page's state?
- **CE3-107** When the server stops, open cut lists are saved first. Must: On a normal server stop, every open cut list is saved first, within the stop grace period.

### Outcome not found

- **CE1-081** Several audio preparations at once starved the disks. Must: Audio preparation never runs many jobs at once, and playing a clip moves its preparation to the front instead of starting another.
- **CE1-082** A partial project copy played silence and guessed the English. Must: When a project's audio, word timings or translations are missing, the editor names which, never showing an empty player, silence or substitute English.
- **CE1-094** The playhead stopped, jumped back, and selections reverted, cause never found. Must: The playhead and selection move only by the editor's own action; a second window or a controller of the same episode never fights it.
- **CE1-130** An open editor page stuck after the server restarted. Must: An open editor page reconnects by itself after a server restart, without a manual reload and without losing work.
- **CE2-012** Go-to-clip-start and end keys act on the clip under the playhead. Must: The go-to-clip-start and go-to-clip-end keys move the playhead within the clip it is in, whatever is selected.
- **CE2-044** Neighbouring montage clips from different sources should differ in colour. Must: Each speaker or source in a montage gets its own colour, and no two adjacent clips from different sources share one.
- **CE2-128** Downloaded projects sit in a readable folder chosen per computer. Must: The desktop app opens projects from the NAS and keeps each downloaded cut list as named files in a visible folder chosen per project per computer.
- **CE3-016** The phone's vertical edit view must zoom out to an overview. Must: The phone's vertical edit view zooms vertically, from detail out to an overview of many cards.
- **CE3-036** Section colours disappeared from a cut. Must: Section colours persist through every edit, reload and import of a cut.
- **CE3-045** The first cut list of an episode said "no audio sources" until reloaded. Must: A slow first audio load shows loading and keeps retrying, including on Play, and never stays stuck on an error that has since cleared.

### Fixed, never shipped

- **CE1-110** The controller drives the transcript like the timeline. Must: The pad acts on the focused pane; in the transcript the right stick steps word by word, LT plus stick selects, and LT plus X inserts after the selected card.
- **CE2-067** An abandoned video request kept streaming the whole file. Must: When a browser abandons a media request, the server stops reading and sending it within a second.
- **CE2-105** Retiring or updating a page wiped other pages' offline copies. Must: Retiring or updating a page never deletes anything a device saved; installed pages keep working offline, and unsent edits survive a rollback.
- **CE2-114** Offline downloads run only where switched on and never repeat. Must: Media downloads for offline use only where the person switched it on, and media already held is never downloaded again.
- **CE3-092** The desktop editor is one whole window, like Resolve. Must: The desktop editor shows as one window whose header doubles as its title bar, with the window buttons in the editor's colours.

## Timeline Cards: the hand-over to Resolve, and exports

### Question only

- **CRX-010** A sent timeline is butt-joined at a chosen rate, 29.97 drop-frame by default. Must: A send offers a rate (default 29.97 drop-frame), butt-joins cuts and first imports any clip the Resolve project lacks; a file stating another rate keeps it.
  - **Question:** The same ruling asked for marker-free timelines, yet later rulings place section and gap-note markers: are markers wanted?

### Still open

- **CRX-005** Mixed-rate clips land in Resolve at a length Resolve decides. Must: Each cut starts at the previous item's read-back end, with no gaps or overlaps, and its placed length matches the clip's real rate within 0.04 seconds.
- **CRX-042** A per-cut gain was asked for but never reached Resolve. Must: A cut's gain reaches Resolve at the level set, proven by reading back a known level; until proven, every send and export says plainly whether gain was carried.
- **CRX-073** A build stopped early left 54 cuts with no audio or markers. Must: A send reports done only when picture, sound and markers are all placed, flags any partial timeline, and keeps a steady status while Resolve is idle.
- **CRX-106** A TV network delivery needs two-language subtitles and a name-strap list per episode. Must: Each delivered episode gets English and Chinese subtitle files in its own folder, and a list of every speaker with a screenshot and name.

### Outcome not found

- **CRX-015** A cut built in Resolve came out at the wrong total length. Must: A timeline built from a cut runs the cut list's length, give or take a frame per clip.
- **CRX-034** A timeline rebuilt by duplicating and renaming has a new id. Must: What the product remembers about a timeline survives it being duplicated and renamed, or the product says plainly that it lost track.
- **CRX-047** Every Resolve call returns nothing while a dialog box is open. Must: A call that returns nothing is treated as a possible blocking dialog and named to the editor, and an editor's own transcription is never cancelled.
- **CRX-050** Building a long timeline one Resolve call at a time is very slow. Must: A build or bulk change of several hundred items shows progress and finishes in minutes.
- **CRX-057** Keys sent to Resolve on the editor's behalf stopped him typing in Resolve. Must: Nothing the product installs ever intercepts keys the editor types into Resolve or any other program.
- **CRX-071** A thirteen-cut montage built a timeline with far more clips. Must: A timeline made from a cut holds exactly one clip per card, in the cut's order, and nothing else.
- **CRX-072** Clip colours set in the cards did not reach Resolve. Must: A colour set on a cut in the cards appears on that clip in the timeline Resolve receives.
- **CRX-092** A render queue across projects must survive Resolve crashing. Must: When Resolve dies during a queued render, the queue restarts Resolve, re-runs the interrupted job and continues with the rest.
- **CRX-093** The studio's default render is QuickTime H.264 at 3840x2160, proxies off. Must: Before a queue starts, each job differing from the studio defaults is listed per project with a yes or no to switch it.
- **CRX-094** Before rendering, clips hidden inside compound clips must be checked online. Must: Before a render is queued, every clip inside every compound clip on the timeline is checked, and offline ones are named.
- **CRX-096** Compound clips should carry the name and colour of what they hold. Must: A compound clip the product creates is named after the clip it wraps and takes the clip colour of the related interviewee's multicam.
- **CRX-097** Name titles sat half off screen and could cover the speaker. Must: A name title's visible edge sits 50 px in from the side and bottom, on the side away from where the speaker appears.
- **CRX-098** When one interviewee cuts straight to another, name titles hand over. Must: On a direct cut between two speakers, the first speaker's title plays its exit and the second speaker's title plays its entrance.
- **CRX-109** A person's name was spelled differently across subtitles and name straps. Must: Each person's name is spelled one way per language across every subtitle file and name-strap list of an episode.

### Fixed, never shipped

- **CRX-038** Resolve's scripting cannot set fades, keyframes, transitions or clip volume. Must: Every send and export carries fades, gain and levelling where it can, and names each one it dropped, with a count in words.
- **CRX-044** A gap-note title must never cover the next cut or move anything. Must: Gap text never overlaps picture, no cut moves, every track lock is restored, and a note marker never reads back as a section.

## YouTube downloads

### Still open

- **YTD-009** A search for a named show returned aerials of its setting, not the show. Must: An editor can search exactly the typed term with no expansion, and any expansion of a named title stays about that title.
  - **Question:** Is an expansion of a named title now kept about the title, or is the exact-term scope the whole answer?
- **YTD-081** The queue looked stuck while jobs waited for their creators' review. Must: A job waiting for a person's review shows as waiting for that named person, never as stuck.

### Outcome not found

- **YTD-002** An archive channel's uploads are barely reachable through YouTube search. Must: Footage search can list every upload of a named channel and filter it by title.
- **YTD-010** Videos longer than half an hour are skipped. Must: Search results longer than 30 minutes are left out of downloads.
- **YTD-016** Unticking clips mid-download changed nothing; a new scope kept the old ticks. Must: Unticking a clip during a download stops it being fetched, and choosing a selection scope replaces the previous selection.
- **YTD-038** Opus audio makes a clip flicker between online and offline in a timeline. Must: Clips already downloaded with Opus audio are found and re-encoded to AAC, and no new download lands with Opus.
- **YTD-056** An editor's computer stopped downloading its own clips, and nobody knew why. Must: When a computer that should download a clip does not, the dashboard states that computer's reason.
- **YTD-071** Downloads landed in a different project from the one selected. Must: A download lands in the project selected when download was pressed, and the job shows that project.

### Fixed, never shipped

- **YTD-028** A live-stream link never finishes downloading. Must: A live-stream link is refused or stopped at a set time limit, no download holds the downloader past a limit, and cancel stops one in progress within seconds.

## sealed notes

### Still open

- **BRO-S03** Fixed instructions after the images never hit the cache, and answers were cut off. Must: Repeated fixed text is cached, no answer is cut off by the output limit, and a long session's input does not grow with every earlier image.
- **BRO-S10** Every vision model tested called a gun "a tool with a laser pointer". Must: The comparison set includes weapons and look-alikes, known misnamings are recorded per model, and a weapons search finds such footage despite softened wording.
- **CFI-S13** Singing and chanting come out as gaps with no text. Must: Long stretches of sound with no text are marked, so the editor can find sung or chanted material.
- **CFI-S28** Writing corrected transcripts back into Resolve's library was never proven. Must: No transcript is written into Resolve's library until a sandbox test shows Resolve reading it back correctly.
- **CRX-S06** Reading Resolve's live library must not hold it open or bypass its locks. Must: Reads never stay open between uses, writes always check Resolve's lock, and every real library is protected whatever its name.
- **SYN-S12** The folder sync tool upgrades itself and reports crashes to its makers. Must: Helper tools on editors' computers stay at the pinned version and send nothing to their makers.

### Outcome not found

- **APP-S10** Every secure download from the packaged Mac app failed certificate checks. Must: The Mac app verifies secure downloads against a trust store it can always find, proven on a real Mac build.
- **APP-S13** A single-file self-extracting app writes hundreds of megabytes per start. Must: Starting the app writes no large temporary files, leaves nothing behind after a forced kill, and is not flagged by common security software.
- **RSV-S06** A quarter of in-points read from the library are one frame off Resolve's. Must: Library reads give cards identical to the live read or report the difference, tolerate a one-frame in-point gap, and frame-exact work uses Resolve's own figure.
- **SRV-S05** Restarting the service that owns a shared network strands its neighbours. Must: After the network-owning service restarts, every service sharing its network is reachable again without a person stepping in.

### Fixed, never shipped

- **ACC-S01** A single-file program cannot carry a lesser-GPL library. Must: Lesser-GPL libraries ship as separate replaceable files with their full licence text and how to replace them, never inside a single-file build.
- **BRO-S08** Full-HD stills cost twice the image budget of the local vision model. Must: Every b-roll clip from a 1080p proxy is described without failing on input size.
- **APP-S09** A handed-over new build was judged dead because the wrong process was watched. Must: When handing over to a new build, either the spawned process or its child counts as the new app, waiting up to thirty seconds.
- **APP-S11** The app trusted expired Windows store certificates that Windows itself ignores. Must: Expired store certificates are filtered out before any secure connection object is created.
- **RSV-S07** Resolve's list of project libraries can miss the shared database libraries. Must: Every project library is found from the scripting list, Resolve's log and the disk library folders, and each is read read-only, once per library.
- **RSV-S10** Resolve's scripting switch lives in both preference files, which must agree. Must: The setting is written to both files while Resolve is closed, and reported as set only when both say Local.
- **SRV-S01** The private-network tool's packaged start-up gives up and keeps minting login links. Must: A first sign-in to the private network on the NAS shows one stable login link until completed from setup, and publishing is set only afterwards.
- **SRV-S02** An empty private-network member answers "nothing published" with a null body. Must: Read a null answer as "nothing published", and refuse to publish, naming the admin page to fix, while the network's certificates are off.
- **SRV-S03** The server's private-network sign-in expires after 180 days by default. Must: The server watches its own network connection, warns 14 days before expiry, and raises one alert when most computers go silent together.
- **SRV-S11** A new database password was announced but the existing database kept the old one. Must: Changing the password on an existing database actually changes it, or the server refuses to start and says so.
- **SYN-S21** The transfer tool reported success on a proxy the NAS had cut short. Must: Use 64 KiB chunks and 16 parallel requests or fewer against such servers, and check the finished size independently of the tool's success.
- **SYN-S26** Editors' transfers failed with "key mismatch" on every new site. Must: Record the NAS host key with its key type and tell the tool to use exactly that type.
- **SYN-S31** Each transfer run opens its own NAS login pool and lists the whole folder. Must: Size connection counts for checks that find nothing, not for big uploads, and do not start a run when nothing local has changed.
