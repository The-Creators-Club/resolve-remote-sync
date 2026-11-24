# Sync: what real use taught

135 lessons. Each is one rule the product can be tested against: what a person saw (the heading), why it happened, and what the product must do. Kinds: *given* is a fact about something the studio has whatever is built; *ruling* is the owner's decision; *situation* is something the product must survive.

## What syncs where

### BRO-024: Footage used by many projects must not be set up again per project.
- Why: The owner wanted one shoot in several projects; a per-project bin of outside files "would be fiddly to set up every time there's a new [series] project".
- Must: Footage shared across projects lives in one shared library every editor can use, with no setup when a new project starts.
- Kind: ruling

### SYN-001: Remote editors get proxies down and their own media up, in the server's layout.
- Why: The owner's founding ask: proxies download unasked into a local copy of the server's folder tree, and media an editor adds uploads to the same place there.
- Must: An editor's local tree mirrors the server's layout; proxies arrive unasked, and media they add uploads to the matching server folder.
- Kind: ruling

### SYN-002: Syncing is part of the product's core, never an optional module.
- Why: The owner ruled "sync is core to dashboard and the [app on each editor's computer]", so it can never be switched off like an optional module.
- Must: Syncing and its status are always present on the dashboard and on every editor's computer, whatever modules are enabled.
- Kind: ruling

### SYN-003: Nothing syncs until a project is ticked, and ticked projects go one at a time.
- Why: Everything was syncing at once; the owner wanted editors to tick or untick projects, nothing moving until ticked, and projects synced one after another.
- Must: Nothing syncs to a computer until a project is ticked for it; unticking stops it; several ticked projects sync one at a time, in order.
- Kind: ruling

### SYN-004: An urgent project could not be moved to the front of a computer's queue.
- Why: Queue order was the order projects were ticked; the owner wanted one project "top of the queue" and it waited behind seven others.
- Must: An editor or admin can move a project to the front of one computer's sync queue from the screen.
- Kind: ruling

### SYN-005: A project can sit at any depth on the server, inside series or categories.
- Why: Owner: "The project could be any project inside any year inside any series"; an episode inside its series folder could not be found or ticked.
- Must: A project at any folder depth on the server appears in the project list, can be ticked, and is reproduced locally with the server's exact names and nesting.
- Kind: ruling

### SYN-007: Ticking a project brings down its whole folder structure, empty folders included.
- Why: Owner: ticking "should clone the entire folder structure from the nas ... even if there is no content inside certain subfolders"; only files arrived.
- Must: Within one pass of a full tick, every folder of that project on the server exists on the editor's computer, including folders holding no files.
- Kind: ruling

### SYN-008: An editor can choose single clips, or whole timelines, whose originals come down.
- Why: Owner: "there should be an option to sync CERTAIN originals... selectable on specific clips inside of resolve"; an earlier timeline-based attempt downloaded nothing.
- Must: An editor can pick clips or timelines whose originals sync to their computer, sees the plan before it runs, and sees whether each file arrived.
- Kind: ruling

### SYN-009: YouTube originals go up, and come down only to the editor who asked.
- Why: A remote editor's computer started pulling 58 GB of colleagues' YouTube originals; the owner: that is a "waste of bandwith".
- Must: A YouTube original goes up to the NAS and comes down by itself only to the requester's computer syncing the project; others get its proxy and may fetch it.
- Kind: ruling

### SYN-010: Footage filed in one project but needed in another never reached the editor.
- Why: An interviewee folder in one project was used in another; sync covered only a project's own folder, and copying would have doubled 414 GB.
- Must: A project can borrow a folder from another project, and every computer ticking the borrower receives it at its true path, with no second copy on the NAS.
- Kind: ruling

### SYN-014: Each editor reaches the NAS by their own drive letter or Mac volume name.
- Why: Editors on Windows mount the server share by drive letter and on a Mac by volume name; the same project must still find the same files.
- Must: A project opened on any editor's Windows or Mac computer resolves every clip to that computer's own mount of the same server file.
- Kind: ruling

### SYN-006: Reorganising the NAS into deeper folders made a category look like a project.
- Why: The owner moved projects into category folders; discovery at a fixed depth took a grouping folder for a project and lost track of the moved ones.
- Must: A project keeps an identity that travels with its folder, so a move on the server keeps its ticks, history and synced data without re-transferring.
- Kind: situation

### SYN-011: A borrowed folder never came down when its owning project was ticked upload-only.
- Why: A borrowed folder counted as covered whenever its owning project was ticked in any mode, but upload-only brings no files down, and the editor was told to ask an admin.
- Must: A computer syncing a project fully gets every folder it borrows, whatever mode the owning project is ticked in.
- Kind: situation

### SYN-012: Studio-wide libraries must reach every computer, even one with nothing ticked.
- Why: The shared LUT library and gallery stills had to reach everyone; deciding sharing from project ticks alone would have unshared them from every computer.
- Must: The studio's LUT library and shared gallery stills sync to every editor's computer automatically, with no project ticked, and never appear as projects.
- Kind: situation

### SYN-013: A shared library that failed on one computer left no trace anywhere.
- Why: A library that failed to share left nothing even in the log, and library problems were shown only after a project check that stopped early when nothing was ticked.
- Must: A failing shared library is retried, then named to the editor with what to do, whether or not any project is ticked, without marking project sync broken.
- Kind: situation

### SYN-015: A blank setting could widen sync from one project to the whole tree.
- Why: A blank active project meant "everything", a missing project path became a folder named "None", and an empty tick list uploaded unticked projects.
- Must: A blank, missing or empty value always narrows what is synced, moved or deleted, never widens it; the action stops instead.
- Kind: situation

### SYN-016: A mistyped server folder sent camera originals into the editor's home folder.
- Why: A server destination that was not a full path was only a warning, so uploads landed in the editor's own home folder on the server, where nothing finds them.
- Must: An empty or relative server destination is refused at install, and nothing uploads or downloads until a valid one is set.
- Kind: situation

### SYN-017: Renaming the projects folder in setup made every computer sync nothing.
- Why: The projects-folder name was honoured by server setup only, so a customer who changed it got a server tree under one name and computers looking for another.
- Must: Every setting offered is honoured by every part of the product, or the product refuses to start with it set and says why.
- Kind: situation

## Uploads that cannot resume, shutdown and sleep

### SRT-185: Field internet abroad is too slow for uploads and downloads.
- Why: Hotel and mobile internet abroad was slow and dropped, so proxy uploads kept failing and downloads ran at about 60 KB/s.
- Must: Field uploads survive slow, dropping connections by resuming, and heavy work such as transcription is left for home.
- Kind: given

### SYN-097: A Mac laptop on battery with its lid closed sleeps despite a keep-awake request.
- Why: macOS sleeps a closed-lid laptop on battery even with a keep-awake request, waking only briefly, so an overnight upload stalled from about 23:00 to 03:21.
- Must: When a Mac is about to sleep with transfers owed, the person is told what is unfinished, and transfers resume by themselves on wake.
- Kind: given

### SYN-096: Switching off mid-upload threw away 19.3 GB of half-sent camera originals.
- Why: An editor shut down with three files part-sent on a 53 Mbit/s uplink, and idle sleep interrupts uploads the same way overnight.
- Must: While a transfer is really moving, shutdown names it, says it will resume, and offers "shut down anyway"; idle sleep is held off; a stalled transfer never keeps it awake.
- Kind: situation

### SYN-098: A laptop opened after sleep did not sync for many minutes.
- Why: Owner: "I've had the laptop open for about half an hour and it didn't sync"; syncs ran on a fixed timer and nothing started one on wake.
- Must: A computer that wakes from sleep syncs at once, not at its next timer slot.
- Kind: situation

### SYN-099: "Am I safe to close my laptop?" had no answer, then named the wrong computer.
- Why: Footage not yet uploaded sits on one disk only; the answer was worked out for the person but worded "this computer", so the wrong machine was told to stay on.
- Must: The editor sees one line saying whether it is safe to close, naming the computer or computers that still owe uploads, and none rather than a guess.
- Kind: situation

## A plan belongs to a computer

### SYN-021: A Mac renames itself on the network when its name clashes.
- Why: macOS appends "-2" to a computer's network name when it clashes with another, so plans keyed by that name split into two records for one computer.
- Must: A computer keeps one identity across renames and name clashes, and one computer never holds two plans at once.
- Kind: given

### SYN-018: One person with two computers could not have two sync plans.
- Why: Sync choices were stored per person, so a second computer shared the plan; the owner wants one person able to own several computers with separate plans.
- Must: Each computer has its own sync plan; an untick made for the person applies on all their computers.
- Kind: ruling

### SYN-019: Changing one computer's plan changed the person's other computers too.
- Why: "Remove from this computer" sent a person-wide removal, an empty untick was widened to the whole person, and a computer's first own tick replaced every project it had inherited.
- Must: Ticking, unticking or removing a project for one computer changes only that project on that computer; if nothing was removed it says so instead of widening.
- Kind: situation

### SYN-020: Renaming a computer onto another live computer's name deleted that computer's plan.
- Why: A rename onto a name already held by a live computer overwrote it, erasing its sync choices.
- Must: A rename onto a name another live computer holds is refused with a warning, and both computers keep their plans.
- Kind: situation

### SYN-022: Signing in as someone else ran the previous person's projects.
- Why: The saved sync plan was not tied to who signed in, and a sign-in with an unusable answer overwrote a working identity.
- Must: After a sign-in the computer runs only the signed-in person's plan, and a failed sign-in leaves the previous working identity intact.
- Kind: situation

## Wired or remote

### SYN-023: Wired or remote belongs to each computer, not to the person signed in.
- Why: One account owns an office desktop wired to the NAS and a remote laptop; the owner's laptop synced as wired because admins were treated as wired.
- Must: Any number of computers can be wired; each is set on that computer, never derived from who signs in, and automatic detection may switch to wired but never back.
- Kind: ruling

### SYN-024: A computer wired to the NAS works straight off it and syncs nothing.
- Why: Owner: the studio base machine "does not need to pull proxies" and "doesn't need to sync anything locally at all"; it sat forever in a queue it could never clear.
- Must: A wired computer downloads nothing, copies no project locally, never appears in the sync queue, shows healthy, and still reports what its Resolve sees.
- Kind: ruling

### SYN-025: A project reached a wired or upload-only computer by a side route.
- Why: A tick made for a person landed on their wired desktop, stuck "getting ready", and a per-person fallback shared projects to unidentified devices, including wired and upload-only ones.
- Must: A project's files come down only to computers known to hold a full tick for it; ticking a wired computer directly is refused.
- Kind: situation

### SYN-026: A computer switched to wired raised a permanent error about its old ticks.
- Why: Old ticks on a computer that now reads the NAS directly produced a red "server not sending that project" notice about a correct setup.
- Must: Ticks left on a wired computer never raise an error or notice, and an admin can still see and clear them.
- Kind: situation

### SYN-027: A wired computer re-read the whole NAS tree every five minutes.
- Why: Wired computers walked the entire tree over the network share on every cycle.
- Must: A wired computer never re-reads the whole NAS tree on a short cycle.
- Kind: situation

## Upload only

### SYN-028: An editor with footage backed up locally wants to upload it, downloading no files.
- Why: The owner asked for "an upload only tick for editors who have backed up footage locally"; he later ruled that such a project carries every file, not only video.
- Must: A project can be ticked upload-only per computer: all but system clutter and temporary files go up, only empty folders come down, and it never reads as out of sync.
- Kind: ruling

## Deletions and removing a project

### SYN-030: An editor's accidental delete of one file spread to the NAS and every editor.
- Why: The owner ruled that a remote editor deleting a file, a proxy or a whole project folder locally must never remove it from the NAS, on every computer and version.
- Must: Deleting any file or folder on an editor's computer never removes it from the NAS or any other computer, with no step by the editor.
- Kind: ruling

### SYN-032: Editors must be able to remove a whole project from their own computer.
- Why: Owner: blocking deletes of uploaded originals "is completely breaking behaviour. Editors will cycle through different projects a lot and delete the entire folders".
- Must: One action unticks, stops syncing, then deletes the local copy, stopping before deletion on any failure; the server's copy is never touched.
- Kind: ruling

### SYN-031: Nothing automatic may delete footage on the NAS.
- Why: The design holds only while no automatic action deletes on the NAS and the only editor-side deletions are recoverable and capped.
- Must: No automatic action deletes on the NAS; downloads that remove local files move them to a recoverable bin, capped per pass, and stopping downloads never stops uploads.
- Kind: situation

### SYN-033: "Remove from this computer" deleted footage the NAS had never received.
- Why: Files under two minutes old, future-dated by a camera clock, same-named but different, or not video on an upload-only project, counted as safe and were deleted.
- Must: Removal is refused while any local file, of any age or date, is not on the NAS at the same size and content; it lists and keeps each one.
- Kind: situation

### SYN-034: A file made on an editor's computer went to the bin before it was uploaded.
- Why: Downloads keep the local copy matching the NAS, so a proxy made locally or a fresh YouTube download the NAS did not yet have was swept into the local bin and never uploaded.
- Must: A file created on an editor's computer is never removed by syncing down before it has reached the NAS.
- Kind: situation

### SYN-035: A proxy re-rendered on the NAS vanished from editors' computers.
- Why: A file rewritten on the NAS seconds ago is hidden while it settles, so its older local copy looked deleted and was moved to the bin.
- Must: A file new or rewritten on the NAS is replaced on editors' computers, never removed, and never counts as a deletion.
- Kind: situation

### SYN-036: A laptop's record of holding the only copy of some originals expired.
- Why: The record that a laptop held camera originals not yet on the server aged out after 14 days, so the product forgot they still had to go up.
- Must: A computer stays marked as holding unique originals until each of those files is confirmed on the server, however long that takes.
- Kind: situation

### SYN-037: An editor's newer copy of a file silently never uploaded.
- Why: When the server already holds a same-named camera original of a different size, the editor's copy never goes up, and the warning gave only a count.
- Must: The warning names each file with both sizes, gives the two fixes (rename yours, or have the admin remove the server's copy) and opens the folder.
- Kind: situation

### SYN-038: Removed files are kept in a recovery folder nobody could find.
- Why: Files the sync removes are kept locally for a set period, but nothing named the folder or its size, and one message quoted the default period, not the site's.
- Must: The editor can open the recovery folder and see its file count, size, oldest copy and the site's actual keep period, stated identically everywhere.
- Kind: situation

### SYN-039: An editor's undo window is 14 days while the NAS keeps versions a year.
- Why: Deleted files stay recoverable on an editor's computer for 14 days or 50 GB, while the server keeps versions 365 days; the two were never chosen together.
- Must: An admin sets both recovery windows together for the site, and each is stated where a person goes looking for a lost file.
- Kind: situation

## Safety stops

### SYN-040: Downloads could bin an editor's proxies 20 GB per pass while showing green.
- Why: An empty listing, a wrong root, an unshare, a moved folder or a re-render all look like deletions, and the limit bounded one pass only.
- Must: Download deletions are bounded across passes; a tripped safety stop pauses downloads, not uploads, until a person clears it.
- Kind: situation

### SYN-041: An empty, refused or wrong source could look like a project whose files were deleted.
- Why: An unreachable server can answer with a sign-in page that lists as zero files, and a stale copy of the tree would show its missing files as deletions.
- Must: Before deleting anything locally, the product confirms the source is the live studio tree and answering; an empty listing while this computer holds files pauses downloads instead.
- Kind: situation

### SYN-042: One failed read of a finished project hid it from editors for good.
- Why: A project that failed to read once was marked unreadable and, since nothing in it changed, never read again; editors' downloads behaved as if its files had vanished.
- Must: A project that could not be read is read again on the next pass, and one failed read never removes its files from any editor's view.
- Kind: situation

### SYN-043: Deletions made before a crash did not count toward the safety limit.
- Why: Deletions were counted only when a download pass finished, so a crash or power cut mid-pass gave the next pass a full fresh budget.
- Must: Every deletion counts toward the safety limit as it happens, once only, through crashes, power cuts and passes that end early.
- Kind: situation

### SYN-044: Files moved on the NAS read as deleted and stopped downloads for a day.
- Why: An editor's reorganisation moved 148 originals and 214 proxies; they read as vanished, and moves made a few at a time later added up to a false stop.
- Must: A file gone from one path but present elsewhere with the same name and size is a move, never counted toward any limit; every real removal is counted.
- Kind: situation

### SYN-045: Only the editor at the keyboard could clear a tripped safety stop.
- Why: A remote computer stayed stopped until its owner returned; a first remote resume then stayed in force, re-releasing every new stop and binning 100 proxies a minute.
- Must: An admin can clear one computer's safety stop from the dashboard; one click releases exactly one current stop, and any later stop waits for a person again.
- Kind: situation

### SYN-046: Pressing Resume on a safety stop did nothing: it stopped again at once.
- Why: The stop compared the NAS listing with a remembered one, and resuming kept the old memory, so an intended reorganisation tripped it again forever.
- Must: When a person resumes a safety stop, the NAS's current state becomes the new reference, and the same listing never trips it again.
- Kind: situation

### SYN-047: A safety stop cleared itself on restart, power loss or a support clean-up.
- Why: Stops sat in the folder support tells people to delete, the editor's pause lived only in memory, and a torn write after power loss read as "not tripped".
- Must: Every safety stop and the editor's pause survive restarts, updates, power loss and support clean-ups; a stop record that cannot be read counts as still stopped.
- Kind: situation

### SYN-048: A safety stop whose save failed was silently forgotten on restart.
- Why: On a full or locked home folder a stop lived only in memory, so the restart an editor tries first cleared it.
- Must: A stop that cannot be saved is shown to the editor and on the admin's view of that computer, retried every minute, and never "fixed" by advising a restart.
- Kind: situation

### SYN-049: A safety stop told an editor to check a setting they cannot reach.
- Why: When downloads stopped themselves to protect files, the editor saw the technical reason, naming an internal setting.
- Must: A safety stop tells the editor in plain words that nothing was deleted, uploads continue, and to ask their admin; technical detail goes to the admin and the log.
- Kind: situation

### SYN-050: Suspending one editor froze every untick across the studio.
- Why: A brake against mass unsharing treated an admin's recorded act, one editor with six projects on two computers, like an unexplained mass removal, and only a server setting undid it.
- Must: Removals caused by a recorded admin act apply at once, an admin can approve a held batch, the limit scales with studio size, and unexplained mass removals stay refused.
- Kind: situation

### SYN-051: The mass-unshare brake missed devices added between planning and acting.
- Why: Removals were counted against the plan's snapshot, so a device an admin shared by hand in between was dropped uncounted and unlogged.
- Must: No unshare escapes the count; a device that appeared since the plan was made is kept until the next plan sees it.
- Kind: situation

### SYN-052: A device with no known owner was unshared from every project.
- Why: A device's owner was read from its typed label; a machine-like label became a non-existent editor with no projects, so the device lost every share.
- Must: A device's owner comes from what its signed-in computer reports; a device with no known owner is never unshared, and unsharing is capped per folder.
- Kind: situation

## Studio-wide stops and the editor's pause

### SYN-053: A studio-wide stop kept the shared libraries syncing.
- Why: An admin's stop paused project folders only; libraries kept syncing, a library offered for the first time was accepted, and releasing the stop unpaused folders paused for other reasons.
- Must: A studio-wide stop halts every transfer on every folder, including libraries and first-time acceptance; its release returns each folder only to its otherwise-correct state.
- Kind: situation

### SYN-054: A studio-wide stop was quietly undone by a later quit, pause, update or unplug.
- Why: Quitting, pausing, self-updating, restarting or unplugging the drive re-enabled sharing while the app still said stopped, and one slow step resumed a folder after the stop landed.
- Must: While a studio-wide stop is in force no file moves on any computer by any path, through restarts and reboots; a stop state that cannot be read counts as stopped.
- Kind: situation

### SYN-055: A studio-wide stop could be forgotten and left in force indefinitely.
- Why: The stop had no expiry and no standing notice, so a forgotten stop silently kept every computer from syncing.
- Must: A studio-wide stop shows a banner on every page, expires after a set time unless renewed, and its expiry is announced.
- Kind: situation

### SYN-056: Signing in or restarting silently resumed syncing the editor had paused.
- Why: Sign-in restarted every transfer while Pause still showed ticked, releasing a studio-wide stop erased an editor's own stop, and accepting the licence started sync with nobody signed in.
- Must: While Pause is on nothing starts, through sign-in, restart, update or another stop's release, and sync never starts with nobody signed in.
- Kind: situation

### SYN-057: A synced folder could start syncing before its skip rules were in place.
- Why: When writing a folder's rules about which files to skip failed, timed out, was cut short by quitting, or the project was archived, the folder was unpaused and could exchange every file both ways.
- Must: A synced folder stays paused until its skip rules are confirmed in place, across retries, restarts and the release of any stop.
- Kind: situation

### SYN-058: Quitting or updating the app left its old transfer running beside a new one.
- Why: On Windows a transfer the app starts outlives the app, and a drive check finishing during shutdown could start transfers in an exiting app.
- Must: Once quit, sign-out or update begins nothing new starts, and no file is ever sent by an old and a new transfer at once.
- Kind: situation

### SYN-059: "Sync now" ran downloads this computer had switched off.
- Why: The button ran every transfer, ignoring that a computer reading proxies straight off the share has downloads disabled, under a line saying they were off.
- Must: "Sync now" runs only the transfers this computer has enabled, the same set its automatic start uses.
- Kind: situation

## Files that must never sync

### SYN-062: Macs leave hidden "._" files and folder settings files on shared drives.
- Why: macOS writes a "._name" companion file beside files on exFAT and other non-Mac volumes and folder-settings files everywhere; both were uploaded and caused conflict copies.
- Must: macOS system companion files never sync in either direction, are never counted, and any already on the NAS are found and cleared.
- Kind: given

### SYN-060: Half-finished and temporary files spread to every editor and could not be deleted.
- Why: An interrupted 40 GB upload left a 39 GB part-file, and the downloader's 1.6 GB of partial files were synced everywhere and then kept by delete protection.
- Must: Partial, temporary and work files of every tool are excluded by every upload and download path, the same set everywhere, and interrupted transfers' leftovers are cleaned up.
- Kind: situation

### SYN-063: Two editors changing one file left one editor's work set aside unseen.
- Why: When two computers changed one file the sync kept one version and set the other aside as a conflict copy, which spread without anyone being told.
- Must: Conflict copies of any file type are found and shown to the editor and admin with their paths, and are never merged or deleted automatically.
- Kind: situation

See also, filed under another capability:

- YTD-026 (YouTube downloads): One quality of a clip can arrive truncated every time while another works.

## Names

### SYN-065: The NAS and some Mac volumes treat letter case as different names.
- Why: "youtube" and "Youtube" can both exist on the NAS, while Windows ignores case; looking a project up by a lower-cased spelling found nothing on a case-sensitive volume.
- Must: Names may be compared ignoring case, but a folder is looked up and opened by its exact spelling on disk.
- Kind: given

### SYN-066: A Mac spells accented file names differently, so held files looked missing forever.
- Why: macOS returns names decomposed (NFD), Windows and the NAS composed (NFC); 12 accented files showed owed for a day, and moves read as deletions. Chinese names have no decomposed form.
- Must: Every comparison of a path from a Mac with one from elsewhere treats both spellings as equal, while files are opened, renamed or deleted by their exact bytes.
- Kind: given

### SYN-064: Camera files with capital-letter extensions were never uploaded.
- Why: Cameras write extensions like .MOV and .BRAW in capitals; case-sensitive rules skipped them, and a lowercase "proxy" folder inverted both directions.
- Must: Every file-type and folder-name rule in the sync matches regardless of letter case.
- Kind: situation

### SYN-067: Names with full-width punctuation arrived changed and never relinked.
- Why: YouTube and Chinese titles use full-width ： ？ ｜ ⧸; names were rewritten on the editor's disk, worse each pass, so 29 of 68 proxies on one computer never relinked.
- Must: A name containing full-width punctuation arrives byte-identical on the NAS and every computer, both ways, on every transfer path, recovery runs included.
- Kind: situation

### SYN-068: Folder names with brackets or braces were shared or filtered wrongly.
- Why: The studio's tree really contains bracketed names, and escaping them for a filter misfired on Windows, leaving a shared folder invisible while it read as confirmed.
- Must: Names containing brackets, braces or other pattern characters are shared and filtered as plain names, proven on Windows and macOS.
- Kind: situation

### SYN-069: A share path containing a space was cut off at the space.
- Why: Reading which share a drive letter points to stopped at the first space, so a correctly mapped drive was reported wrong.
- Must: Share paths and folder names containing spaces are read and compared in full everywhere.
- Kind: situation

### SYN-070: One file name with non-Latin characters froze all syncing.
- Why: A single non-ASCII file name crashed the reading of a transfer's output, which stalled every later sync on that computer.
- Must: File names in any script, Chinese included, never stall syncing; an unreadable name affects at most that one file.
- Kind: situation

### SYN-071: After an update, a laptop started downloading its whole project again.
- Why: Straight after an update a laptop re-downloaded everything, coinciding with a change in how special characters in names are written.
- Must: An update never makes a computer re-download files it already holds intact; if names must change, local copies are renamed in place.
- Kind: situation

## The sync drive

### SYN-072: On a Mac, an unplugged sync drive leaves a folder that fills the boot disk.
- Why: macOS lets an app create folders at an absent drive's mount path on the boot disk, an unclean eject leaves one too, and the drive then remounts as "<name> 1".
- Must: A Mac sync location is used only when it is a real mounted volume matching its recorded identity; cannot tell counts as absent, and nothing is created there meanwhile.
- Kind: given

### SYN-074: A plugged-in drive or network mapping can stop answering while looking present.
- Why: A Mac's external SSD, or a Windows mapping over a dropped network, can block any read or folder check indefinitely with no error.
- Must: Every check of the sync drive is time-limited so it cannot freeze the app, and a drive silent for 5 seconds is reported as not answering.
- Kind: given

### SYN-083: A Mac's file-change alerts for an external SSD can silently stop.
- Why: The macOS change-notification stream for an editor's external drive was seen wedged, and only a remount or reboot brought it back.
- Must: Sync never relies on change notifications alone; it notices when they stop and still finds changes by looking.
- Kind: given

### SYN-079: A sync drive pulled mid-upload got the same calm note as a finished day.
- Why: The owner asked for a warning when the drive goes with work owed, then "every half an hour the notification should recur".
- Must: Unplugging with uploads owed, or of unknown direction, names what is owed and reminds every 30 minutes, across restarts, until it returns; any narrowing needs the owner's agreement.
- Kind: ruling

### SYN-073: With the sync drive unplugged, downloads would have filled the internal disk.
- Why: A missing sync folder would be recreated on the boot disk and filled, and the app called it "project deleted locally".
- Must: With the drive absent, or renamed and not provably the same, all syncing pauses, nothing is written to or measured on another disk, and the app says the drive is disconnected.
- Kind: situation

### SYN-075: Editors were told to check the cable of a drive that was plugged in.
- Why: A frozen drive kept passing presence checks, so syncing was never paused and no message matched what was happening.
- Must: A drive present but not answering pauses syncing and says it is not answering, to reconnect or restart, distinct from "disconnected".
- Kind: situation

### SYN-076: "Eject it and plug it back in" fitted only one kind of missing drive.
- Why: A sync drive can be gone because it was unplugged or because it came back under another drive letter; one sentence covered both.
- Must: The missing-drive message says which it is, unplugged or present under another letter and not provably the same drive, and gives the matching fix.
- Kind: situation

### SYN-077: A scan overlapping a drive being unplugged reported the computer as holding nothing.
- Why: The drive vanished mid-walk and the empty result was reported as the computer's real holdings.
- Must: A scan that overlaps the drive going away is discarded, never reported as the computer holding nothing.
- Kind: situation

### SYN-078: After a sync drive came back, folders on it stayed in error for hours.
- Why: When a Mac's external drive slept or was replugged, some projects and shared folders on it stayed in "path missing" error, even after an app restart.
- Must: Within minutes of the drive returning, including when the app starts with it already present, every folder on it resumes by itself, shared folders too.
- Kind: situation

### SYN-080: The missing-drive reminder could not be quieted.
- Why: The repeating reminder had no snooze, yet a data-safety warning must not be silenced for good by accident.
- Must: An editor can snooze for two hours or stop reminders for this episode; the warning line stays, and a restart with the drive still out reminds again.
- Kind: situation

### SYN-081: A sync drive that stopped answering got one note, then silence.
- Why: Reminders followed only a drive unplugged with work owed; a drive that hangs while everything is up to date is harder to spot.
- Must: A sync drive that stays not answering gets its own repeating reminder, which ends by itself when the drive answers or is removed.
- Kind: situation

### SYN-082: A drive in the editor's bag kept being reported as "not answering".
- Why: A remembered warning resumed after restart whatever the drive now did, a second change in one outage was never announced, and a new warning inherited the old mute.
- Must: Drive warnings describe the drive's current state, each change during an outage is announced, owed work is remembered across restarts, and a mute covers one episode.
- Kind: situation

## Disk space

### SYN-084: Proxy downloads filled a laptop drive until nothing could work.
- Why: Nothing measured free space before moving footage, so one "tick everything" filled a laptop, and a full disk then failed downloads file by file.
- Must: Downloads pause below about 20 GB free and resume at 40 GB while uploads continue, recovery copies are pruned under pressure, and a tick first shows its size against free space.
- Kind: situation

### SYN-085: A low-disk stop never cleared by itself, and its verdicts used the wrong floor.
- Why: The stop cleared at twice the floor while clearing space stopped at once the floor, figures went stale, and statements used the server's default floor, not the computer's own.
- Must: A low-disk stop clears once its space is free, shows current free space, uses the computer's own floor, never fires when the floor is off, and labels guesses.
- Kind: situation

## Stuck, slow and fair transfers

### SYN-087: One huge upload held every other upload and download for 13 hours.
- Why: The owner: "why is it only pushing one file at once, it should be pushing 4"; one 22 GB file ran alone on a 17 Mbit/s uplink while 52 files waited.
- Must: While more than one file is owed every upload slot stays busy, a large file in flight is never killed, and other projects' transfers are not held behind it.
- Kind: ruling

### SYN-086: An upload sat "syncing" for hours with nothing moving, starving downloads.
- Why: A transfer stuck on a sleeping external drive or a local read moved zero bytes for over two hours, looked identical to a working one, and held every download behind it.
- Must: Bytes moved, not time, decide: a transfer with no progress for 15 minutes is stopped and shown red with "no progress for N minutes"; one still moving is never stopped or alerted on.
- Kind: situation

### SYN-088: A stall that healed a week ago kept a computer red and mailed daily.
- Why: A stall record never expired, so an idle computer with nothing owed showed blocked and the owner got "still not fixed" mails four mornings running.
- Must: A stall counts as current only until that transfer completes a pass, or 24 hours at most; another direction's recovery never erases it.
- Kind: situation

### SYN-089: One hung download stopped all proxy downloads until the app restarted.
- Why: Each project turn started another download behind the hung one, a late pass could run against a moved folder, and a stuck flag left downloads off while showing green.
- Must: While a download is stuck no new one starts, the computer shows "stalled on" that project, a late pass for a non-current project is dropped, and recovery needs no restart.
- Kind: situation

### SYN-090: A transfer the editor asked for was dropped by a background rule.
- Why: The rule that drops a background pass for a project no longer in turn also dropped the editor's own copy-and-upload, after the screen said proxies were downloading.
- Must: A transfer a person asked for is never dropped by rules meant for background passes.
- Kind: situation

### SYN-091: One slow project held up proxies for every other project for ten minutes.
- Why: Each pass waited up to 600 seconds per project for its other files to settle, so one slow connection delayed proxies for every project behind it.
- Must: A slow or stuck project never delays downloads for other projects beyond a short settle time.
- Kind: situation

### SYN-092: A project with 97 GB of proxies owed waited while idle projects were re-checked.
- Why: Projects took turns in a fixed order, so with 89 proxies due, about 2 of every 12 minutes went to projects that had just found nothing.
- Must: When other projects just found nothing, the project with work left gets the next turn, and every quiet project is still re-checked within a bounded time.
- Kind: situation

### SYN-093: The same camera file was uploaded twice at once, splitting the uplink.
- Why: A quick upload of a just-finished file and the regular pass both saw it missing on the NAS and both sent it, over an uplink saturated near 50 Mbit/s.
- Must: A file is never uploaded by two transfers at once, and one skipped for that reason is picked up on the next pass.
- Kind: situation

### SYN-094: An offline laptop spent each pass on failing transfers and blamed a broken sync.
- Why: Off the network, a laptop with ten projects spent about 45 minutes per pass on failing attempts and showed "exited 1" instead of "cannot reach the server".
- Must: When the NAS is unreachable the app shows "cannot reach the server" as its own state, stops trying, and resumes promptly when the network returns.
- Kind: situation

### SYN-095: The sync loop died and the computer kept reporting a frozen healthy state.
- Why: An unexpected error, such as the mapped drive dropping mid-pass, ended the sync loop while reports kept sending its last state.
- Must: A failing pass costs one pass; a background loop that dies or stops checking in is restarted within 30 minutes and its restarts are reported.
- Kind: situation

## Saying truthfully what the sync is doing

### SYN-100: Programs started in a Windows session die when the session ends.
- Why: Processes started in a Windows session die with it, and logon start-up entries run only at the next logon, so a background sync stayed dead 18 hours.
- Must: Every background process the sync depends on is brought back within a minute or two of dying, whenever that happens, without waiting for a new logon.
- Kind: given

### SYN-101: The background sync died overnight and showed green for 18 hours, 12 GB waiting.
- Why: The sync on an editor's computer died with the Windows session; nothing restarted it, and its being unreachable went only to a log nobody reads.
- Must: A dead sync process is restarted with backoff, shown as failing with its cause until running, the editor is told after repeated failures, and a deliberate pause is never overridden.
- Kind: situation

### SYN-102: After signing out and back in, proxies never downloaded again while status stayed green.
- Why: Stopping sync at sign-out left downloads switched off for the life of the app, still showing their last healthy status.
- Must: Every part of the sync resumes after pause, sign-out or sign-in, and a direction that is not running never shows a healthy status.
- Kind: situation

### SYN-103: Signing out mid-download turned the download status red.
- Why: A transfer stopped on purpose was recorded as a transfer that failed.
- Must: A transfer stopped because a person or the app asked it to stop shows as stopped, never as an error.
- Kind: situation

### SYN-104: The app said "Something went wrong" for hours without naming the cause.
- Why: Only a transfer's last line was kept, hiding the real cause, and the main status said "Something went wrong" while a line below gave the reason.
- Must: An error names its real first cause in the same words in the editor's app, the dashboard and the log; a safety limit doing its job shows as paused, not an error.
- Kind: situation

### SYN-105: An upload status flipped between error and idle while nothing was missing.
- Why: One failing file failed the whole pass, the next pass touching nothing went idle, and no log line named the file.
- Must: An error names its files and reason in the log and on screen, and a pass is never shown red when every file is on the NAS.
- Kind: situation

### SYN-106: "Why isn't this computer syncing?" had no answer on any page.
- Why: Blocking reasons (signed out, drive out, disk full, stopped, paused, stalled) were kept separately, uploads sat queued with no reason shown, and an editor cleared the one reason shown while another held.
- Must: Each computer names every reason it is not syncing, most actionable first, in identical words in the editor's app and on the dashboard, within one report.
- Kind: situation

### SYN-107: "Ask your admin" appeared when the computer's own sync was not answering.
- Why: One message covered three cases: not yet offered by the server, the local sync not answering, and a deliberate stop holding it.
- Must: Each cause gets its own sentence, a deliberate stop is not shown as a problem, and only a truly missing approval sends the editor to the admin.
- Kind: situation

### SYN-108: One project of five never synced while the computer showed green.
- Why: A project held paused waiting for its skip rules counted as healthy, because the status turned paused only when every project was paused.
- Must: Any single project held back makes the computer's status say so, naming the project, even when all the others are fine.
- Kind: situation

### SYN-109: A computer syncing a week-old plan looked healthy, and a fresh one looked old.
- Why: With the dashboard unreachable the computer ran its cached plan unnoticed, and the plan's age counted from the last change, not the last answer.
- Must: Plan age is the time since the server last answered; past a day the status says so, and an unknown age is never shown as fresh.
- Kind: situation

### SYN-110: After a tick, nothing happened for a minute, then pages said nothing moved.
- Why: A tick waited out a 60-second cycle, a just-ticked project was missing from views, and its setup showed as an error while 2.9 GB flowed.
- Must: A tick takes effect within about 5 seconds, shows "getting ready" until data flows, and progress counts proxies and synced files by bytes.
- Kind: situation

### SYN-111: Every fresh tick raised a red "not sending this project" card and an alarm mail.
- Why: Checks compared against sharing state from before the new share existed, and a new folder is briefly unfiltered while it is set up.
- Must: For 30 minutes after a tick, normal setup states raise no error, notice or mail; anything still wrong after that alerts as usual.
- Kind: situation

### SYN-112: A warning about one project was cleared by a clean scan of another.
- Why: The "skipped, already exists" alarm and the half-finished-file report kept only the last project scanned, so a clean project hid another's problems.
- Must: Each project's warnings persist until that project itself scans clean.
- Kind: situation

### SYN-113: After a re-tick or a mode change, new files could be skipped for hours.
- Why: A memory that a project was clean survived unticking and re-ticking, or a switch to upload-only, so new files could be skipped for up to two hours.
- Must: After a project is re-ticked or its mode changes, the next pass examines every file in it.
- Kind: situation

## What is owed

### SYN-114: "Safe to close" or "nothing owed" was claimed from an incomplete list.
- Why: A computer's file list was cut at 2,000 entries, so 100 to 523 proxies per large project looked owed for ever, and a cut or missing list still read "all done".
- Must: Lists of what is owed are never silently cut; when the whole list is not seen the product says it cannot tell, never "safe to close".
- Kind: situation

### SYN-115: Leftovers of a dead YouTube download sat as owed uploads for ever.
- Why: Temporary parts, 31.7 GB, left by a crashed download were counted as originals to upload, though uploads deliberately skip such files.
- Must: Anything uploads deliberately skip is never counted as owed, judged by the same rules on both ends.
- Kind: situation

## Load on the NAS when nothing changes

### SYN-116: An idle editor's computer logged in to the NAS about 1,900 times an hour.
- Why: Every six minutes each ticked project's upload check opened up to 16 connections and listed the whole project, though nothing local had changed.
- Must: A computer with nothing new costs the NAS a few logins an hour, not growing with computers times projects, yet a new file, tick or mode change syncs within about 5 minutes.
- Kind: situation

### SYN-117: Every computer re-sent its unchanged file lists every few minutes.
- Why: About 510 MB a day per computer was re-sent and rewritten unchanged, about 47 GB of server writes a day at 20 computers.
- Must: A report about unchanged projects sends and stores almost nothing, idle computers back off, and an over-size report drops only enough detail.
- Kind: situation

## Speed and routes

### SYN-120: Remote editors on 500 Mbit lines got only about 18 MB/s from the NAS.
- Why: Between two Taiwanese home lines the direct internet route capped near 18 MB/s, while a laptop on the studio network moved 35-76 MB/s through the same software.
- Must: Each computer's real transfer rate is shown against a public speed baseline, so an internet route, not the product, is seen as the limit.
- Kind: given

### SYN-118: Transfers must be as fast as the studio saw from Resolve's own cloud.
- Why: Owner: "On resolve cloud we get around 60mb/s max up and down", and big transfers must "maximise speed", not ride a slow private network.
- Must: On the same connection uploads and downloads each reach at least 60 MB/s, over the fastest route available, with the achieved speed visible.
- Kind: ruling

### SYN-119: Several remote editors syncing at once share the studio's upload.
- Why: Owner: "If you have multiple remote editors syncing at once it should just split the bandwidth until it hits the maximum upload."
- Must: Transfers to several editors run together and together fill the server's uplink, none waiting for another to finish.
- Kind: ruling

### SYN-121: Another route tripled one remote editor's download speed.
- Why: Through a relay in the same city one editor's proxy downloads reached 47-55 MB/s instead of 18; such a relay can answer with a sign-in page that lists as empty.
- Must: A slow editor's downloads can use another read-only route; a failing or empty answer there pauses downloads and never deletes local files.
- Kind: situation

## Clocks and file age

### SYN-122: Editors' computer clocks are often wrong by minutes or days.
- Why: A dead clock battery, a resumed virtual machine or a Mac just out of sleep runs far off the true time, and a slow clock made every server file look too new to download.
- Must: Each computer's clock is measured against the server's; a gap over a minute is shown to the editor and admin, and no age rule trusts a computer's clock alone.
- Kind: given

### SYN-123: A just-copied 40 GB camera file looks hours old on Windows.
- Why: Windows copy tools keep the source file's modified time, so a file's age cannot tell a just-landed file from an old one.
- Must: Checks for whether a file is finished watch for a changing size or time, never the file's age alone.
- Kind: given

### SYN-124: Footage dated in the future by a wrong camera clock never uploads.
- Why: Cameras with clocks set ahead write files dated in the future, and a rule to wait until files stop changing never sees them as settled.
- Must: Future-dated files upload like any other, and the editor sees which file and date are wrong until they are fixed.
- Kind: situation

## Computers joining and changing

### SYN-125: Transfers sat at 0% forever after an editor's computer was reinstalled.
- Why: The computer came back with a new sync identity and the server kept sharing to the old dead one, so 387 items, 48.5 GB, never moved and nothing said why.
- Must: When a known computer appears with a new sync identity, the dashboard says so and lets an admin approve it, after which transfers resume within a minute.
- Kind: situation

### SYN-126: One failure stopped the rest of a sharing change and was reported wrongly.
- Why: When one folder of 40 failed to share, the other 30 were never tried and the record still described all 40 as done.
- Must: Each folder succeeds or fails alone, the rest still run, and the page states "applied N of M" with the refusal reason.
- Kind: situation

### SYN-127: A folder list any editor can edit could make the server store unlimited rows.
- Why: Entries past the cap were each recorded as invalid, so a list naming 10,000 folders produced 10,000 records rewritten every cycle.
- Must: Input from a file editors can write is capped in what it stores too: past the cap, one record says how many were ignored.
- Kind: situation

## Project folders on an editor's computer

### SYN-128: A project folder renamed by hand on an editor's computer stopped uploading unnoticed.
- Why: A folder present last pass and now gone read as "not yet downloaded", so new footage stopped uploading and the old folder was re-downloaded beside it.
- Must: A project folder seen before and now gone is an error naming it, and where it went if found, with a one-click put-back that deletes nothing.
- Kind: situation

### SYN-129: A project renamed while open in Resolve later pointed sync at an empty folder.
- Why: The local move failed because Resolve held files; the next pass created the new folder with proxies only and adopted it, leaving the real copy unsynced.
- Must: A rename that cannot be applied locally stays visibly blocked until it can; the app never adopts a folder it created itself or stops uploading the real copy.
- Kind: situation

### SYN-130: A project kept saying it could not move its folder after that was fixed.
- Why: The message cleared only on a successful move, so once the folder was right by another route the project stayed paused.
- Must: Once a project's folder is where it belongs, the "could not move" message clears and the project syncs again.
- Kind: situation

### SYN-131: Project folders on a computer that are in no sync plan were invisible.
- Why: A project folder left on disk outside every plan was never synced or reported, yet still counted as that computer holding the files.
- Must: Folders in no plan are reported with count and size and never deleted, and an empty or unreachable plan is never read as "everything is stray".
- Kind: situation

## Facts about the NAS and the operating systems

### SYN-132: A NAS share in restricted permission mode refuses permission changes.
- Why: On a TrueNAS dataset in restricted ACL mode, changing a file's or folder's permissions is refused, so a sync that set permissions stalled at its temporary files.
- Must: Sync onto the NAS never depends on changing file or folder permissions, and transfers complete on a restricted share.
- Kind: given

### SYN-133: Synology's built-in secure file transfer silently cut proxies over 514 MiB short.
- Why: With large read sizes and many parallel requests, Synology DSM 7.2's secure file transfer stops at 539,000,832 bytes while the download appears successful.
- Must: Transfer settings known to truncate on that NAS are refused, and a downloaded file shorter than the source is never marked done.
- Kind: given

### SYN-134: On macOS a rename silently replaces a file already at the destination.
- Why: Windows refuses to rename onto an existing file, but macOS replaces it silently, so a restore that "never overwrites" lost a fresh copy on Macs.
- Must: Restoring or moving a file never overwrites an existing file on any platform, including one that appears during the move; a clash is refused and named.
- Kind: given

### SYN-135: Power loss can leave a full-size file of zeros that a size check calls good.
- Why: After power loss NTFS and APFS can leave a file at its full size but filled with zeros; comparing by name and size then spreads it everywhere.
- Must: A zero-filled file left by a power cut is never sent over a good copy on the server or another computer.
- Kind: given
