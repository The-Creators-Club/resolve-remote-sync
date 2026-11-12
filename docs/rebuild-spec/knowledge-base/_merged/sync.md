# Syncing projects

## What syncs where

### SYN-001: Remote editors get proxies down and their own media up, in the server's layout.
- What was going on: The owner's founding ask: proxies download unasked into a local copy of the server's folder tree, and media an editor adds uploads to the same place there.
- What the product must do: An editor's local tree mirrors the server's layout; proxies arrive unasked, and media they add uploads to the matching server folder.
- Kind: 2
- From: P01-045

### SYN-002: Syncing is part of the product's core, never an optional module.
- What was going on: The owner ruled "sync is core to dashboard and the companion", so it can never be switched off like an optional module.
- What the product must do: Syncing and its status are always present on the dashboard and on every editor's computer, whatever modules are enabled.
- Kind: 2
- From: P19-006

### SYN-003: Nothing syncs until a project is ticked, and ticked projects go one at a time.
- What was going on: Everything was syncing at once; the owner wanted editors to tick or untick projects, nothing moving until ticked, and projects synced one after another.
- What the product must do: Nothing syncs to a computer until a project is ticked for it; unticking stops it; several ticked projects sync one at a time, in order.
- Kind: 2
- From: P02-009

### SYN-004: An urgent project could not be moved to the front of a computer's queue.
- What was going on: Queue order was the order projects were ticked; the owner wanted one project "top of the queue" and it waited behind seven others.
- What the product must do: An editor or admin can move a project to the front of one computer's sync queue from the screen.
- Kind: 2
- State: still open
- From: P11-040, M02-034

### SYN-005: A project can sit at any depth on the server, inside series or categories.
- What was going on: Owner: "The project could be any project inside any year inside any series"; an episode inside its series folder could not be found or ticked.
- What the product must do: A project at any folder depth on the server appears in the project list, can be ticked, and is reproduced locally with the server's exact names and nesting.
- Kind: 2
- From: P02-001, P04-011

### SYN-006: Reorganising the NAS into deeper folders made a category look like a project.
- What was going on: The owner moved projects into category folders; discovery at a fixed depth took a grouping folder for a project and lost track of the moved ones.
- What the product must do: A project keeps an identity that travels with its folder, so a move on the server keeps its ticks, history and synced data without re-transferring.
- Kind: 3
- From: C01-006

### SYN-007: Ticking a project brings down its whole folder structure, empty folders included.
- What was going on: Owner: ticking "should clone the entire folder structure from the nas ... even if there is no content inside certain subfolders"; only files arrived.
- What the product must do: Within one pass of a full tick, every folder of that project on the server exists on the editor's computer, including folders holding no files.
- Kind: 2
- From: P02-002, C01-109

### SYN-008: An editor can choose single clips, or whole timelines, whose originals come down.
- What was going on: Owner: "there should be an option to sync CERTAIN originals... selectable on specific clips inside of resolve"; an earlier timeline-based attempt downloaded nothing.
- What the product must do: An editor can pick clips or timelines whose originals sync to their computer, sees the plan before it runs, and sees whether each file arrived.
- Kind: 2
- From: P14-040, P01-029

### SYN-009: YouTube originals go up from the computer that downloaded them, never down to others.
- What was going on: A remote editor's computer started pulling 58 GB of colleagues' YouTube originals; the owner: that is a "waste of bandwith".
- What the product must do: A YouTube original goes up to the NAS only; other computers get its proxy, and a requester gets their own clip by downloading it themselves.
- Kind: 2
- From: L03-052, M03-009, P05-012

### SYN-010: Footage filed in one project but needed in another never reached the editor.
- What was going on: An interviewee folder in one project was used in another; sync covered only a project's own folder, and copying would have doubled 414 GB.
- What the product must do: A project can borrow a folder from another project, and every computer ticking the borrower receives it at its true path, with no second copy on the NAS.
- Kind: 2
- From: P07-013, M02-019

### SYN-011: A borrowed folder never came down when its owning project was ticked upload-only.
- What was going on: A borrowed folder counted as covered whenever its owning project was ticked in any mode, but upload-only brings nothing down, and the editor was told to ask an admin.
- What the product must do: A computer syncing a project fully gets every folder it borrows, whatever mode the owning project is ticked in.
- Kind: 3
- From: H06-124

### SYN-012: Studio-wide libraries must reach every computer, even one with nothing ticked.
- What was going on: The shared LUT, b-roll and music libraries had to reach everyone; deciding sharing from project ticks alone would have unshared them from every computer.
- What the product must do: Studio-wide library folders sync to every editor's computer automatically, with no project ticked, and never appear as projects.
- Kind: 3
- From: C01-059

### SYN-013: A shared library that failed on one computer left no trace anywhere.
- What was going on: A library that failed to share left nothing even in the log, and library problems were shown only after a project check that stopped early when nothing was ticked.
- What the product must do: A failing shared library is retried, then named to the editor with what to do, whether or not any project is ticked, without marking project sync broken.
- Kind: 3
- From: L04-109, H05-017

### SYN-014: Each editor reaches the NAS by their own drive letter or Mac volume name.
- What was going on: Editors on Windows mount the server share by drive letter and on a Mac by volume name; the same project must still find the same files.
- What the product must do: A project opened on any editor's Windows or Mac computer resolves every clip to that computer's own mount of the same server file.
- Kind: 2
- From: P01-044

### SYN-015: A blank setting could widen sync from one project to the whole tree.
- What was going on: A blank active project meant "everything", a missing project path became a folder named "None", and an empty tick list uploaded unticked projects.
- What the product must do: A blank, missing or empty value always narrows what is synced, moved or deleted, never widens it; the action stops instead.
- Kind: 3
- From: C01-014

### SYN-016: A mistyped server folder sent camera originals into the editor's home folder.
- What was going on: A server destination that was not a full path was only a warning, so uploads landed in the editor's own home folder on the server, where nothing finds them.
- What the product must do: An empty or relative server destination is refused at install, and nothing uploads or downloads until a valid one is set.
- Kind: 3
- From: L05-005

### SYN-017: Renaming the projects folder in setup made every computer sync nothing.
- What was going on: The projects-folder name was honoured by server setup only, so a customer who changed it got a server tree under one name and computers looking for another.
- What the product must do: Every setting offered is honoured by every part of the product, or the product refuses to start with it set and says why.
- Kind: 3
- From: L05-019

## A plan belongs to a computer

### SYN-018: One person with two computers could not have two sync plans.
- What was going on: Sync choices were stored per person, so a second computer shared the plan; the owner wants one person able to own several computers with separate plans.
- What the product must do: Each computer has its own sync plan; an untick made for the person applies on all their computers.
- Kind: 2
- From: P06-043, C02-056

### SYN-019: Changing one computer's plan changed the person's other computers too.
- What was going on: "Remove from this computer" sent a person-wide removal, an empty untick was widened to the whole person, and a computer's first own tick replaced every project it had inherited.
- What the product must do: Ticking, unticking or removing a project for one computer changes only that project on that computer; if nothing was removed it says so instead of widening.
- Kind: 3
- From: H02-034, H04-006, L01-036, H07-056, H03-020

### SYN-020: Renaming a computer onto another live computer's name deleted that computer's plan.
- What was going on: A rename onto a name already held by a live computer overwrote it, erasing its sync choices.
- What the product must do: A rename onto a name another live computer holds is refused with a warning, and both computers keep their plans.
- Kind: 3
- From: C02-067

### SYN-021: A Mac renames itself on the network when its name clashes.
- What was going on: macOS appends "-2" to a computer's network name when it clashes with another, so plans keyed by that name split into two records for one computer.
- What the product must do: A computer keeps one identity across renames and name clashes, and one computer never holds two plans at once.
- Kind: 1a
- From: H04-035

### SYN-022: Signing in as someone else ran the previous person's projects.
- What was going on: The saved sync plan was not tied to who signed in, and a sign-in with an unusable answer overwrote a working identity.
- What the product must do: After a sign-in the computer runs only the signed-in person's plan, and a failed sign-in leaves the previous working identity intact.
- Kind: 3
- From: H06-102

## Wired or remote

### SYN-023: Wired or remote belongs to each computer, not to the person signed in.
- What was going on: One account owns an office desktop wired to the NAS and a remote laptop; the owner's laptop synced as wired because admins were treated as wired.
- What the product must do: Any number of computers can be wired; each is set on that computer, never derived from who signs in, and automatic detection may switch to wired but never back.
- Kind: 2
- From: P07-008, M02-023, C03-002, H04-030, C02-068

### SYN-024: A computer wired to the NAS works straight off it and syncs nothing.
- What was going on: Owner: the studio base machine "does not need to pull proxies" and "doesn't need to sync anything locally at all"; it sat forever in a queue it could never clear.
- What the product must do: A wired computer downloads nothing, copies no project locally, never appears in the sync queue, shows healthy, and still reports what its Resolve sees.
- Kind: 2
- From: P02-012

### SYN-025: A project reached a wired or upload-only computer by a side route.
- What was going on: A tick made for a person landed on their wired desktop, stuck "getting ready", and a per-person fallback shared projects to unidentified devices, including wired and upload-only ones.
- What the product must do: A project's files come down only to computers known to hold a full tick for it; ticking a wired computer directly is refused.
- Kind: 3
- From: H03-031, L03-088, H05-096

### SYN-026: A computer switched to wired raised a permanent error about its old ticks.
- What was going on: Old ticks on a computer that now reads the NAS directly produced a red "server not sending that project" notice about a correct setup.
- What the product must do: Ticks left on a wired computer never raise an error or notice, and an admin can still see and clear them.
- Kind: 3
- From: L06-041

### SYN-027: A wired computer re-read the whole NAS tree every five minutes.
- What was going on: Wired computers walked the entire tree over the network share on every cycle.
- What the product must do: A wired computer never re-reads the whole NAS tree on a short cycle.
- Kind: 3
- State: still open
- From: H07-135

## Upload only

### SYN-028: An editor with footage backed up locally wants to upload it, downloading nothing.
- What was going on: The owner asked for "an upload only tick for editors who have backed up footage locally"; he later ruled that such a project carries every file, not only video.
- What the product must do: A project can be ticked upload-only per computer: every file except system clutter and temporary files goes up, nothing comes down, and it never reads as out of sync.
- Kind: 2
- State: fixed, never shipped
- From: L03-035, C02-083, M02-090, P07-014, H08-011, L11-015

### SYN-029: Ticking a project upload-only created the NAS's folder skeleton on the editor's disk.
- What was going on: The project's folder structure was still copied down before the upload-only check, filling the local folder with empty folders.
- What the product must do: An upload-only project creates nothing on the editor's computer and makes no download-side connection for it.
- Kind: 3
- Check: Earlier the owner was recorded as wanting upload-only editors to receive the empty folder structure to place originals in; should it come down or not?
- From: L05-089, H05-030

## Deletions and removing a project

### SYN-030: An editor's accidental delete of one file spread to the NAS and every editor.
- What was going on: The owner ruled that a remote editor deleting a file, a proxy or a whole project folder locally must never remove it from the NAS, on every computer and version.
- What the product must do: Deleting any file or folder on an editor's computer never removes it from the NAS or any other computer, with no step by the editor.
- Kind: 2
- From: P06-044, C01-081, L03-063, P04-034

### SYN-031: Nothing automatic may delete footage on the NAS.
- What was going on: The design holds only while no automatic action deletes on the NAS and the only editor-side deletions are recoverable and capped.
- What the product must do: No automatic action deletes on the NAS; downloads that remove local files move them to a recoverable bin, capped per pass, and stopping downloads never stops uploads.
- Kind: 3
- From: H04-003

### SYN-032: Editors must be able to remove a whole project from their own computer.
- What was going on: Owner: blocking deletes of uploaded originals "is completely breaking behaviour. Editors will cycle through different projects a lot and delete the entire folders".
- What the product must do: One action unticks, stops syncing, then deletes the local copy, stopping before deletion on any failure; the server's copy is never touched.
- Kind: 2
- From: P02-024, C01-027

### SYN-033: "Remove from this computer" deleted footage the NAS had never received.
- What was going on: Files under two minutes old, future-dated by a camera clock, same-named but different, or not video on an upload-only project, counted as safe and were deleted.
- What the product must do: Removal is refused while any local file, of any age or date, is not on the NAS at the same size and content; it lists and keeps each one.
- Kind: 3
- State: fixed, never shipped
- From: M02-093, L01-035, L11-014, L11-016, H07-112, P12-064

### SYN-034: A file made on an editor's computer went to the bin before it was uploaded.
- What was going on: Downloads keep the local copy matching the NAS, so a proxy made locally or a fresh YouTube download the NAS did not yet have was swept into the local bin and never uploaded.
- What the product must do: A file created on an editor's computer is never removed by syncing down before it has reached the NAS.
- Kind: 3
- State: outcome not found
- From: M02-042, H02-028

### SYN-035: A proxy re-rendered on the NAS vanished from editors' computers.
- What was going on: A file rewritten on the NAS seconds ago is hidden while it settles, so its older local copy looked deleted and was moved to the bin.
- What the product must do: A file new or rewritten on the NAS is replaced on editors' computers, never removed, and never counts as a deletion.
- Kind: 3
- From: L01-033

### SYN-036: A laptop's record of holding the only copy of some originals expired.
- What was going on: The record that a laptop held camera originals not yet on the server aged out after 14 days, so the product forgot they still had to go up.
- What the product must do: A computer stays marked as holding unique originals until each of those files is confirmed on the server, however long that takes.
- Kind: 3
- State: outcome not found
- From: H08-024

### SYN-037: An editor's newer copy of a file silently never uploaded.
- What was going on: When the server already holds a same-named file of a different size, the editor's copy never goes up, and the warning gave only a count.
- What the product must do: The warning names each file with both sizes, gives the two fixes (rename yours, or have the admin remove the server's copy) and opens the folder.
- Kind: 3
- From: L04-094

### SYN-038: Removed files are kept in a recovery folder nobody could find.
- What was going on: Files the sync removes are kept locally for a set period, but nothing named the folder or its size, and one message quoted the default period, not the site's.
- What the product must do: The editor can open the recovery folder and see its file count, size, oldest copy and the site's actual keep period, stated identically everywhere.
- Kind: 3
- From: L04-095, L06-097

### SYN-039: An editor's undo window is 14 days while the NAS keeps versions a year.
- What was going on: Deleted files stay recoverable on an editor's computer for 14 days or 50 GB, while the server keeps versions 365 days; the two were never chosen together.
- What the product must do: The owner sets both recovery windows together, and each is stated where a person goes looking for a lost file.
- Kind: 3
- State: still open
- From: L04-047

## Safety stops

### SYN-040: Downloads could bin an editor's proxies 20 GB per pass while showing green.
- What was going on: An empty listing, a wrong root, an unshare, a moved folder or a re-render all look like deletions, and the limit bounded one pass only.
- What the product must do: Download deletions are bounded across passes; a tripped safety stop pauses downloads, not uploads, until a person clears it.
- Kind: 3
- From: L01-032

### SYN-041: An empty, refused or wrong source could look like a project whose files were deleted.
- What was going on: An unreachable server can answer with a sign-in page that lists as zero files, and a stale copy of the tree would show its missing files as deletions.
- What the product must do: Before deleting anything locally, the product confirms the source is the live studio tree and answering; an empty listing while this computer holds files pauses downloads instead.
- Kind: 3
- From: C04-014, H04-008

### SYN-042: One failed read of a finished project hid it from editors for good.
- What was going on: A project that failed to read once was marked unreadable and, since nothing in it changed, never read again; editors' downloads behaved as if its files had vanished.
- What the product must do: A project that could not be read is read again on the next pass, and one failed read never removes its files from any editor's view.
- Kind: 3
- From: L10-004

### SYN-043: Deletions made before a crash did not count toward the safety limit.
- What was going on: Deletions were counted only when a download pass finished, so a crash or power cut mid-pass gave the next pass a full fresh budget.
- What the product must do: Every deletion counts toward the safety limit as it happens, once only, through crashes, power cuts and passes that end early.
- Kind: 3
- From: L05-090, H05-095, L06-085

### SYN-044: Files moved on the NAS read as deleted and stopped downloads for a day.
- What was going on: An editor's reorganisation moved 148 originals and 214 proxies; they read as vanished, and moves made a few at a time later added up to a false stop.
- What the product must do: A file gone from one path but present elsewhere with the same name and size is a move, never counted toward any limit; every real removal is counted.
- Kind: 3
- From: P07-010, H06-002, H02-033

### SYN-045: Only the editor at the keyboard could clear a tripped safety stop.
- What was going on: A remote computer stayed stopped until its owner returned; a first remote resume then stayed in force, re-releasing every new stop and binning 100 proxies a minute.
- What the product must do: An admin can clear one computer's safety stop from the dashboard; one click releases exactly one current stop, and any later stop waits for a person again.
- Kind: 3
- From: C02-070, L01-067, H02-030

### SYN-046: Pressing Resume on a safety stop did nothing: it stopped again at once.
- What was going on: The stop compared the NAS listing with a remembered one, and resuming kept the old memory, so an intended reorganisation tripped it again forever.
- What the product must do: When a person resumes a safety stop, the NAS's current state becomes the new reference, and the same listing never trips it again.
- Kind: 3
- From: H02-029

### SYN-047: A safety stop cleared itself on restart, power loss or a support clean-up.
- What was going on: Stops sat in the folder support tells people to delete, the editor's pause lived only in memory, and a torn write after power loss read as "not tripped".
- What the product must do: Every safety stop and the editor's pause survive restarts, updates, power loss and support clean-ups; a stop record that cannot be read counts as still stopped.
- Kind: 3
- From: L02-015, H07-031, H04-009

### SYN-048: A safety stop whose save failed was silently forgotten on restart.
- What was going on: On a full or locked home folder a stop lived only in memory, so the restart an editor tries first cleared it.
- What the product must do: A stop that cannot be saved is shown to the editor and on the admin's view of that computer, retried every minute, and never "fixed" by advising a restart.
- Kind: 3
- From: L05-082, H05-015

### SYN-049: A safety stop told an editor to check a setting they cannot reach.
- What was going on: When downloads stopped themselves to protect files, the editor saw the technical reason, naming an internal setting.
- What the product must do: A safety stop tells the editor in plain words that nothing was deleted, uploads continue, and to ask their admin; technical detail goes to the admin and the log.
- Kind: 3
- From: L05-021, L04-152

### SYN-050: Suspending one editor froze every untick across the studio.
- What was going on: A brake against mass unsharing treated an admin's recorded act, one editor with six projects on two computers, like an unexplained mass removal, and only a server setting undid it.
- What the product must do: Removals caused by a recorded admin act apply at once, an admin can approve a held batch, the limit scales with studio size, and unexplained mass removals stay refused.
- Kind: 3
- State: fixed, never shipped
- From: H07-124, L11-055

### SYN-051: The mass-unshare brake missed devices added between planning and acting.
- What was going on: Removals were counted against the plan's snapshot, so a device an admin shared by hand in between was dropped uncounted and unlogged.
- What the product must do: No unshare escapes the count; a device that appeared since the plan was made is kept until the next plan sees it.
- Kind: 3
- From: L06-053

### SYN-052: A device with no known owner was unshared from every project.
- What was going on: A device's owner was read from its typed label; a machine-like label became a non-existent editor with no projects, so the device lost every share.
- What the product must do: A device's owner comes from what its signed-in computer reports; a device with no known owner is never unshared, and unsharing is capped per folder.
- Kind: 3
- From: H04-036

## Studio-wide stops and the editor's pause

### SYN-053: A studio-wide stop kept the shared libraries syncing.
- What was going on: An admin's stop paused project folders only; libraries kept syncing, a library offered for the first time was accepted, and releasing the stop unpaused folders paused for other reasons.
- What the product must do: A studio-wide stop halts every transfer on every folder, including libraries and first-time acceptance; its release returns each folder only to its otherwise-correct state.
- Kind: 3
- From: H04-005, L01-034, L06-090

### SYN-054: A studio-wide stop was quietly undone by a later quit, pause, update or unplug.
- What was going on: Quitting, pausing, self-updating, restarting or unplugging the drive re-enabled sharing while the app still said stopped, and one slow step resumed a folder after the stop landed.
- What the product must do: While a studio-wide stop is in force no file moves on any computer by any path, through restarts and reboots; a stop state that cannot be read counts as stopped.
- Kind: 3
- From: H06-012, C04-005, L10-039, H07-054

### SYN-055: A studio-wide stop could be forgotten and left in force indefinitely.
- What was going on: The stop had no expiry and no standing notice, so a forgotten stop silently kept every computer from syncing.
- What the product must do: A studio-wide stop shows a banner on every page, expires after a set time unless renewed, and its expiry is announced.
- Kind: 3
- From: H07-053

### SYN-056: Signing in or restarting silently resumed syncing the editor had paused.
- What was going on: Sign-in restarted every transfer while Pause still showed ticked, releasing a studio-wide stop erased an editor's own stop, and accepting the licence started sync with nobody signed in.
- What the product must do: While Pause is on nothing starts, through sign-in, restart, update or another stop's release, and sync never starts with nobody signed in.
- Kind: 3
- State: outcome not found
- From: H08-021, H01-005

### SYN-057: A synced folder could start syncing before its skip rules were in place.
- What was going on: When writing a folder's rules about which files to skip failed, timed out, was cut short by quitting, or the project was archived, the folder was unpaused and could exchange every file both ways.
- What the product must do: A synced folder stays paused until its skip rules are confirmed in place, across retries, restarts and the release of any stop.
- Kind: 3
- From: H04-007, H01-007

### SYN-058: Quitting or updating the app left its old transfer running beside a new one.
- What was going on: On Windows a transfer the app starts outlives the app, and a drive check finishing during shutdown could start transfers in an exiting app.
- What the product must do: Once quit, sign-out or update begins nothing new starts, and no file is ever sent by an old and a new transfer at once.
- Kind: 3
- Check: Should quitting or updating the app stop an in-flight upload, losing its progress, or leave it running to finish?
- From: H01-001

### SYN-059: "Sync now" ran downloads this computer had switched off.
- What was going on: The button ran every transfer, ignoring that a computer reading proxies straight off the share has downloads disabled, under a line saying they were off.
- What the product must do: "Sync now" runs only the transfers this computer has enabled, the same set its automatic start uses.
- Kind: 3
- From: L06-094

## Files that must never sync

### SYN-060: Half-finished and temporary files spread to every editor and could not be deleted.
- What was going on: An interrupted 40 GB upload left a 39 GB part-file, and the downloader's 1.6 GB of partial files were synced everywhere and then kept by delete protection.
- What the product must do: Partial, temporary and work files of every tool are excluded by every upload and download path, the same set everywhere, and interrupted transfers' leftovers are cleaned up.
- Kind: 3
- From: P05-015, H04-056, C01-104, L03-070, M01-081, M03-017

### SYN-061: A YouTube download that keeps getting cut short is retried at a lower quality.
- What was going on: Partial and fragment files from repeatedly truncated YouTube downloads sat in a synced project folder.
- What the product must do: A download truncated repeatedly retries one quality step lower rather than leaving partial files.
- Kind: 3
- Move to: youtube
- From: M03-017

### SYN-062: Macs leave hidden "._" files and folder settings files on shared drives.
- What was going on: macOS writes a "._name" companion file beside files on exFAT and other non-Mac volumes and folder-settings files everywhere; both were uploaded and caused conflict copies.
- What the product must do: macOS system companion files never sync in either direction, are never counted, and any already on the NAS are found and cleared.
- Kind: 1a
- State: still open
- From: C01-054, L10-083, H01-039

### SYN-063: Two editors changing one file left one editor's work set aside unseen.
- What was going on: When two computers changed one file the sync kept one version and set the other aside as a conflict copy, which spread without anyone being told.
- What the product must do: Conflict copies of any file type are found and shown to the editor and admin with their paths, and are never merged or deleted automatically.
- Kind: 3
- From: L02-008

## Names

### SYN-064: Camera files with capital-letter extensions were never uploaded.
- What was going on: Cameras write extensions like .MOV and .BRAW in capitals; case-sensitive rules skipped them, and a lowercase "proxy" folder inverted both directions.
- What the product must do: Every file-type and folder-name rule in the sync matches regardless of letter case.
- Kind: 3
- From: C01-011

### SYN-065: The NAS and some Mac volumes treat letter case as different names.
- What was going on: "youtube" and "Youtube" can both exist on the NAS, while Windows ignores case; looking a project up by a lower-cased spelling found nothing on a case-sensitive volume.
- What the product must do: Names may be compared ignoring case, but a folder is looked up and opened by its exact spelling on disk.
- Kind: 1a
- From: L03-064, H03-019

### SYN-066: A Mac spells accented file names differently, so held files looked missing forever.
- What was going on: macOS returns names decomposed (NFD), Windows and the NAS composed (NFC); 12 accented files showed owed for a day, and moves read as deletions. Chinese names have no decomposed form.
- What the product must do: Every comparison of a path from a Mac with one from elsewhere treats both spellings as equal, while files are opened, renamed or deleted by their exact bytes.
- Kind: 1a
- From: H06-063, P08-002, M02-001, L02-004, H07-045, C03-006, L03-033, G01-014

### SYN-067: Names with full-width punctuation arrived changed and never relinked.
- What was going on: YouTube and Chinese titles use full-width ： ？ ｜ ⧸; names were rewritten on the editor's disk, worse each pass, so 29 of 68 proxies on one computer never relinked.
- What the product must do: A name containing full-width punctuation arrives byte-identical on the NAS and every computer, both ways, on every transfer path, recovery runs included.
- Kind: 3
- From: G01-011, C01-025, M03-016

### SYN-068: Folder names with brackets or braces were shared or filtered wrongly.
- What was going on: The studio's tree really contains bracketed names, and escaping them for a filter misfired on Windows, leaving a shared folder invisible while it read as confirmed.
- What the product must do: Names containing brackets, braces or other pattern characters are shared and filtered as plain names, proven on Windows and macOS.
- Kind: 3
- From: H06-125

### SYN-069: A share path containing a space was cut off at the space.
- What was going on: Reading which share a drive letter points to stopped at the first space, so a correctly mapped drive was reported wrong.
- What the product must do: Share paths and folder names containing spaces are read and compared in full everywhere.
- Kind: 3
- From: H01-049

### SYN-070: One file name with non-Latin characters froze all syncing.
- What was going on: A single non-ASCII file name crashed the reading of a transfer's output, which stalled every later sync on that computer.
- What the product must do: File names in any script, Chinese included, never stall syncing; an unreadable name affects at most that one file.
- Kind: 3
- From: C01-012

### SYN-071: After an update, a laptop started downloading its whole project again.
- What was going on: Straight after an update a laptop re-downloaded everything, coinciding with a change in how special characters in names are written.
- What the product must do: An update never makes a computer re-download files it already holds intact; if names must change, local copies are renamed in place.
- Kind: 3
- State: outcome not found
- From: P02-043

## The sync drive

### SYN-072: On a Mac, an unplugged sync drive leaves a folder that fills the boot disk.
- What was going on: macOS lets an app create folders at an absent drive's mount path on the boot disk, an unclean eject leaves one too, and the drive then remounts as "<name> 1".
- What the product must do: A Mac sync location is used only when it is a real mounted volume matching its recorded identity; cannot tell counts as absent, and nothing is created there meanwhile.
- Kind: 1a
- From: C01-048, H01-010, H03-015, L02-007, G01-018

### SYN-073: With the sync drive unplugged, downloads would have filled the internal disk.
- What was going on: A missing sync folder would be recreated on the boot disk and filled, and the app called it "project deleted locally".
- What the product must do: With the drive absent or mounted under another name, all syncing pauses, nothing is written elsewhere, free space is never measured on another disk, and the app says the drive is disconnected.
- Kind: 3
- Check: One early ruling had the same drive resume under any mount name; later rules pause a numbered remount with instructions. Which does the owner want?
- From: P03-044, C01-049

### SYN-074: A plugged-in drive or network mapping can stop answering while looking present.
- What was going on: A Mac's external SSD, or a Windows mapping over a dropped network, can block any read or folder check indefinitely with no error.
- What the product must do: Every check of the sync drive is time-limited so it cannot freeze the app, and a drive silent for 5 seconds is reported as not answering.
- Kind: 1a
- From: L02-043, L03-032

### SYN-075: Editors were told to check the cable of a drive that was plugged in.
- What was going on: A frozen drive kept passing presence checks, so syncing was never paused and no message matched what was happening.
- What the product must do: A drive present but not answering pauses syncing and says it is not answering, to reconnect or restart, distinct from "disconnected".
- Kind: 3
- From: L02-044

### SYN-076: "Eject it and plug it back in" fitted only one kind of missing drive.
- What was going on: A sync drive can be gone because it was unplugged or because it came back under another drive letter; one sentence covered both.
- What the product must do: The missing-drive message says which it is, unplugged or present under another letter, and gives the matching fix.
- Kind: 3
- From: L04-041

### SYN-077: A scan overlapping a drive being unplugged reported the computer as holding nothing.
- What was going on: The drive vanished mid-walk and the empty result was reported as the computer's real holdings.
- What the product must do: A scan that overlaps the drive going away is discarded, never reported as the computer holding nothing.
- Kind: 3
- From: H07-055

### SYN-078: After a sync drive came back, folders on it stayed in error for hours.
- What was going on: When a Mac's external drive slept or was replugged, some projects and shared folders on it stayed in "path missing" error, even after an app restart.
- What the product must do: Within minutes of the drive returning, including when the app starts with it already present, every folder on it resumes by itself, shared folders too.
- Kind: 3
- From: L08-043, P11-041

### SYN-079: A sync drive pulled mid-upload got the same calm note as a finished day.
- What was going on: The owner asked for a warning when the drive goes with work owed, then "every half an hour the notification should recur"; interrupted uploads restart from zero.
- What the product must do: Unplugging with uploads owed, or of unknown direction, names what is owed and reminds every 30 minutes, across restarts, until it returns; any narrowing needs the owner's agreement.
- Kind: 2
- State: outcome not found
- From: L02-003, P08-006, C03-010, M01-074, H07-057

### SYN-080: The missing-drive reminder could not be quieted.
- What was going on: The repeating reminder had no snooze, yet a data-safety warning must not be silenced for good by accident.
- What the product must do: An editor can snooze for two hours or stop reminders for this episode; the warning line stays, and a restart with the drive still out reminds again.
- Kind: 3
- From: L04-157

### SYN-081: A sync drive that stopped answering got one note, then silence.
- What was going on: Reminders followed only a drive unplugged with work owed; a drive that hangs while everything is up to date is harder to spot.
- What the product must do: A sync drive that stays not answering gets its own repeating reminder, which ends by itself when the drive answers or is removed.
- Kind: 3
- From: L04-108

### SYN-082: A drive in the editor's bag kept being reported as "not answering".
- What was going on: A remembered warning resumed after restart whatever the drive now did, a second change in one outage was never announced, and a new warning inherited the old mute.
- What the product must do: Drive warnings describe the drive's current state, each change during an outage is announced, owed work is remembered across restarts, and a mute covers one episode.
- Kind: 3
- From: H05-021, L05-078

### SYN-083: A Mac's file-change alerts for an external SSD can silently stop.
- What was going on: The macOS change-notification stream for an editor's external drive was seen wedged, and only a remount or reboot brought it back.
- What the product must do: Sync never relies on change notifications alone; it notices when they stop and still finds changes by looking.
- Kind: 1a
- From: H01-041

## Disk space

### SYN-084: Proxy downloads filled a laptop drive until nothing could work.
- What was going on: Nothing measured free space before moving footage, so one "tick everything" filled a laptop, and a full disk then failed downloads file by file.
- What the product must do: Downloads pause below about 20 GB free and resume at 40 GB while uploads continue, recovery copies are pruned under pressure, and a tick first shows its size against free space.
- Kind: 3
- From: C03-011, L02-047, H07-018

### SYN-085: A low-disk stop never cleared by itself, and its verdicts used the wrong floor.
- What was going on: The stop cleared at twice the floor while clearing space stopped at once the floor, figures went stale, and statements used the server's default floor, not the computer's own.
- What the product must do: A low-disk stop clears once its space is free, shows current free space, uses the computer's own floor, never fires when the floor is off, and labels guesses.
- Kind: 3
- From: H06-109, L09-029

## Stuck, slow and fair transfers

### SYN-086: An upload sat "syncing" for hours with nothing moving, starving downloads.
- What was going on: A transfer stuck on a sleeping external drive or a local read moved zero bytes for over two hours, looked identical to a working one, and held every download behind it.
- What the product must do: Bytes moved, not time, decide: a transfer with no progress for 15 minutes is stopped and shown red with "no progress for N minutes"; one still moving is never stopped or alerted on.
- Kind: 3
- From: L03-031, H07-002, C03-008, L02-042, M02-014, L08-045

### SYN-087: One huge upload held every other upload and download for 13 hours.
- What was going on: The owner: "why is it only pushing one file at once, it should be pushing 4"; one 22 GB file ran alone on a 17 Mbit/s uplink while 52 files waited.
- What the product must do: While more than one file is owed every upload slot stays busy, a large file in flight is never killed, and other projects' transfers are not held behind it.
- Kind: 2
- From: L10-064, L08-046, P11-043, P12-049, M02-012, C04-017

### SYN-088: A stall that healed a week ago kept a computer red and mailed daily.
- What was going on: A stall record never expired, so an idle computer with nothing owed showed blocked and the owner got "still not fixed" mails four mornings running.
- What the product must do: A stall counts as current only until that transfer completes a pass, or 24 hours at most; another direction's recovery never erases it.
- Kind: 3
- From: L09-013, L08-087

### SYN-089: One hung download stopped all proxy downloads until the app restarted.
- What was going on: Each project turn started another download behind the hung one, a late pass could run against a moved folder, and a stuck flag left downloads off while showing green.
- What the product must do: While a download is stuck no new one starts, the computer shows "stalled on" that project, a late pass for a non-current project is dropped, and recovery needs no restart.
- Kind: 3
- From: L05-084, H05-020, L06-083

### SYN-090: A transfer the editor asked for was dropped by a background rule.
- What was going on: The rule that drops a background pass for a project no longer in turn also dropped the editor's own copy-and-upload, after the screen said proxies were downloading.
- What the product must do: A transfer a person asked for is never dropped by rules meant for background passes.
- Kind: 3
- From: L06-084

### SYN-091: One slow project held up proxies for every other project for ten minutes.
- What was going on: Each pass waited up to 600 seconds per project for its other files to settle, so one slow connection delayed proxies for every project behind it.
- What the product must do: A slow or stuck project never delays downloads for other projects beyond a short settle time.
- Kind: 3
- From: H04-041

### SYN-092: A project with 97 GB of proxies owed waited while idle projects were re-checked.
- What was going on: Projects took turns in a fixed order, so with 89 proxies due, about 2 of every 12 minutes went to projects that had just found nothing.
- What the product must do: When other projects just found nothing, the project with work left gets the next turn, and every quiet project is still re-checked within a bounded time.
- Kind: 3
- From: P12-015, L10-037

### SYN-093: The same camera file was uploaded twice at once, splitting the uplink.
- What was going on: A quick upload of a just-finished file and the regular pass both saw it missing on the NAS and both sent it, over an uplink saturated near 50 Mbit/s.
- What the product must do: A file is never uploaded by two transfers at once, and one skipped for that reason is picked up on the next pass.
- Kind: 3
- From: C01-042, P03-024, P02-055, H01-051

### SYN-094: An offline laptop spent each pass on failing transfers and blamed a broken sync.
- What was going on: Off the network, a laptop with ten projects spent about 45 minutes per pass on failing attempts and showed "exited 1" instead of "cannot reach the server".
- What the product must do: When the NAS is unreachable the app shows "cannot reach the server" as its own state, stops trying, and resumes promptly when the network returns.
- Kind: 3
- State: still open
- From: H04-042

### SYN-095: The sync loop died and the computer kept reporting a frozen healthy state.
- What was going on: An unexpected error, such as the mapped drive dropping mid-pass, ended the sync loop while reports kept sending its last state.
- What the product must do: A failing pass costs one pass; a background loop that dies or stops checking in is restarted within 30 minutes and its restarts are reported.
- Kind: 3
- From: L02-041

## Uploads that cannot resume, shutdown and sleep

### SYN-096: Switching off mid-upload threw away 19.3 GB of half-sent camera originals.
- What was going on: An interrupted upload restarts from zero; an editor shut down with three files part-sent on a 53 Mbit/s uplink, and idle sleep does the same overnight.
- What the product must do: While a transfer is really moving, shutdown warns and names it with "shut down anyway", idle sleep is held off, and a stalled transfer never keeps it awake.
- Kind: 3
- From: C01-044, P03-025, P11-047, H01-027

### SYN-097: A Mac laptop on battery with its lid closed sleeps despite a keep-awake request.
- What was going on: macOS sleeps a closed-lid laptop on battery even with a keep-awake request, waking only briefly, so an overnight upload stalled from about 23:00 to 03:21.
- What the product must do: When a Mac is about to sleep with transfers owed, the person is told what is unfinished, and transfers resume by themselves on wake.
- Kind: 1a
- From: M02-011

### SYN-098: A laptop opened after sleep did not sync for many minutes.
- What was going on: Owner: "I've had the laptop open for about half an hour and it didn't sync"; syncs ran on a fixed timer and nothing started one on wake.
- What the product must do: A computer that wakes from sleep syncs at once, not at its next timer slot.
- Kind: 3
- State: outcome not found
- From: P14-036

### SYN-099: "Am I safe to close my laptop?" had no answer, then named the wrong computer.
- What was going on: Footage not yet uploaded sits on one disk only; the answer was worked out for the person but worded "this computer", so the wrong machine was told to stay on.
- What the product must do: The editor sees one line saying whether it is safe to close, naming the computer or computers that still owe uploads, and none rather than a guess.
- Kind: 3
- From: L04-141, L06-057

## Saying truthfully what the sync is doing

### SYN-100: Programs started in a Windows session die when the session ends.
- What was going on: Processes started in a Windows session die with it, and logon start-up entries run only at the next logon, so a background sync stayed dead 18 hours.
- What the product must do: Every background process the sync depends on is brought back within a minute or two of dying, whenever that happens, without waiting for a new logon.
- Kind: 1a
- From: C02-052

### SYN-101: The background sync died overnight and showed green for 18 hours, 12 GB waiting.
- What was going on: The sync on an editor's computer died with the Windows session; nothing restarted it, and its being unreachable went only to a log nobody reads.
- What the product must do: A dead sync process is restarted with backoff, shown as failing with its cause until running, the editor is told after repeated failures, and a deliberate pause is never overridden.
- Kind: 3
- From: P06-040, G01-032, L01-001, C02-053

### SYN-102: After signing out and back in, proxies never downloaded again while status stayed green.
- What was going on: Stopping sync at sign-out left downloads switched off for the life of the app, still showing their last healthy status.
- What the product must do: Every part of the sync resumes after pause, sign-out or sign-in, and a direction that is not running never shows a healthy status.
- Kind: 3
- From: C01-101, H01-003

### SYN-103: Signing out mid-download turned the download status red.
- What was going on: A transfer stopped on purpose was recorded as a transfer that failed.
- What the product must do: A transfer stopped because a person or the app asked it to stop shows as stopped, never as an error.
- Kind: 3
- From: H01-004

### SYN-104: The app said "Something went wrong" for hours without naming the cause.
- What was going on: Only a transfer's last line was kept, hiding the real cause, and the main status said "Something went wrong" while a line below gave the reason.
- What the product must do: An error names its real first cause in the same words in the editor's app, the dashboard and the log; a safety limit doing its job shows as paused, not an error.
- Kind: 3
- From: C01-034, L04-040

### SYN-105: An upload status flipped between error and idle while nothing was missing.
- What was going on: One failing file failed the whole pass, the next pass touching nothing went idle, and no log line named the file.
- What the product must do: An error names its files and reason in the log and on screen, and a pass is never shown red when every file is on the NAS.
- Kind: 3
- State: still open
- From: M05-030

### SYN-106: "Why isn't this computer syncing?" had no answer on any page.
- What was going on: Blocking reasons (signed out, drive out, disk full, stopped, paused, stalled) were kept separately, uploads sat queued with no reason shown, and an editor cleared the one reason shown while another held.
- What the product must do: Each computer names every reason it is not syncing, most actionable first, in identical words in the editor's app and on the dashboard, within one report.
- Kind: 3
- From: L02-050, L04-151, P06-042

### SYN-107: "Ask your admin" appeared when the computer's own sync was not answering.
- What was going on: One message covered three cases: not yet offered by the server, the local sync not answering, and a deliberate stop holding it.
- What the product must do: Each cause gets its own sentence, a deliberate stop is not shown as a problem, and only a truly missing approval sends the editor to the admin.
- Kind: 3
- From: L05-085

### SYN-108: One project of five never synced while the computer showed green.
- What was going on: A project held paused waiting for its skip rules counted as healthy, because the status turned paused only when every project was paused.
- What the product must do: Any single project held back makes the computer's status say so, naming the project, even when all the others are fine.
- Kind: 3
- From: L02-006

### SYN-109: A computer syncing a week-old plan looked healthy, and a fresh one looked old.
- What was going on: With the dashboard unreachable the computer ran its cached plan unnoticed, and the plan's age counted from the last change, not the last answer.
- What the product must do: Plan age is the time since the server last answered; past a day the status says so, and an unknown age is never shown as fresh.
- Kind: 3
- From: L04-101, L05-088

### SYN-110: After a tick, nothing happened for a minute, then pages said nothing moved.
- What was going on: A tick waited out a 60-second cycle, a just-ticked project was missing from views, and its setup showed as an error while 2.9 GB flowed.
- What the product must do: A tick takes effect within about 5 seconds, shows "getting ready" until data flows, and progress counts proxies and synced files by bytes.
- Kind: 3
- From: C01-035

### SYN-111: Every fresh tick raised a red "not sending this project" card and an alarm mail.
- What was going on: Checks compared against sharing state from before the new share existed, and a new folder is briefly unfiltered while it is set up.
- What the product must do: For 30 minutes after a tick, normal setup states raise no error, notice or mail; anything still wrong after that alerts as usual.
- Kind: 3
- From: P12-005, L10-029

### SYN-112: A warning about one project was cleared by a clean scan of another.
- What was going on: The "skipped, already exists" alarm and the half-finished-file report kept only the last project scanned, so a clean project hid another's problems.
- What the product must do: Each project's warnings persist until that project itself scans clean.
- Kind: 3
- State: still open
- From: H08-066

### SYN-113: After a re-tick or a mode change, new files could be skipped for hours.
- What was going on: A memory that a project was clean survived unticking and re-ticking, or a switch to upload-only, so new files could be skipped for up to two hours.
- What the product must do: After a project is re-ticked or its mode changes, the next pass examines every file in it.
- Kind: 3
- State: fixed, never shipped
- From: H08-065

## What is owed

### SYN-114: "Safe to close" or "nothing owed" was claimed from an incomplete list.
- What was going on: A computer's file list was cut at 2,000 entries, so 100 to 523 proxies per large project looked owed for ever, and a cut or missing list still read "all done".
- What the product must do: Lists of what is owed are never silently cut; when the whole list is not seen the product says it cannot tell, never "safe to close".
- Kind: 3
- From: H07-095, H06-107, L10-033

### SYN-115: Leftovers of a dead YouTube download sat as owed uploads for ever.
- What was going on: Temporary parts, 31.7 GB, left by a crashed download were counted as originals to upload, though uploads deliberately skip such files.
- What the product must do: Anything uploads deliberately skip is never counted as owed, judged by the same rules on both ends.
- Kind: 3
- From: L10-034

## Load on the NAS when nothing changes

### SYN-116: An idle editor's computer logged in to the NAS about 1,900 times an hour.
- What was going on: Every six minutes each ticked project's upload check opened up to 16 connections and listed the whole project, though nothing local had changed.
- What the product must do: A computer with nothing new costs the NAS a few logins an hour, not growing with computers times projects, yet a new file, tick or mode change syncs within about 5 minutes.
- Kind: 3
- From: C04-033, L11-062, P15-017, H04-040

### SYN-117: Every computer re-sent its unchanged file lists every few minutes.
- What was going on: About 510 MB a day per computer was re-sent and rewritten unchanged, about 47 GB of server writes a day at 20 computers.
- What the product must do: A report about unchanged projects sends and stores almost nothing, idle computers back off, and an over-size report drops only enough detail.
- Kind: 3
- State: still open
- From: L01-076, H08-058

## Speed and routes

### SYN-118: Transfers must be as fast as the studio saw from Resolve's own cloud.
- What was going on: Owner: "On resolve cloud we get around 60mb/s max up and down", and big transfers must "maximise speed", not ride a slow private network.
- What the product must do: On the same connection uploads and downloads each reach at least 60 MB/s, over the fastest route available, with the achieved speed visible.
- Kind: 2
- From: P01-047, P02-054

### SYN-119: Several remote editors syncing at once share the studio's upload.
- What was going on: Owner: "If you have multiple remote editors syncing at once it should just split the bandwidth until it hits the maximum upload."
- What the product must do: Transfers to several editors run together and together fill the server's uplink, none waiting for another to finish.
- Kind: 2
- State: outcome not found
- From: P12-037

### SYN-120: Remote editors on 500 Mbit lines got only about 18 MB/s from the NAS.
- What was going on: Between two Taiwanese home lines the direct internet route capped near 18 MB/s, while a laptop on the studio network moved 35-76 MB/s through the same software.
- What the product must do: Each computer's real transfer rate is shown against a public speed baseline, so an internet route, not the product, is seen as the limit.
- Kind: 1a
- From: C04-013, P12-036

### SYN-121: Another route tripled one remote editor's download speed.
- What was going on: Through a relay in the same city one editor's proxy downloads reached 47-55 MB/s instead of 18; such a relay can answer with a sign-in page that lists as empty.
- What the product must do: A slow editor's downloads can use another read-only route; a failing or empty answer there pauses downloads and never deletes local files.
- Kind: 3
- From: P12-038, M01-061

## Clocks and file age

### SYN-122: Editors' computer clocks are often wrong by minutes or days.
- What was going on: A dead clock battery, a resumed virtual machine or a Mac just out of sleep runs far off the true time, and a slow clock made every server file look too new to download.
- What the product must do: Each computer's clock is measured against the server's; a gap over a minute is shown to the editor and admin, and no age rule trusts a computer's clock alone.
- Kind: 1a
- From: L02-019, H07-021

### SYN-123: A just-copied 40 GB camera file looks hours old on Windows.
- What was going on: Windows copy tools keep the source file's modified time, so a file's age cannot tell a just-landed file from an old one.
- What the product must do: Checks for whether a file is finished watch for a changing size or time, never the file's age alone.
- Kind: 1a
- From: C01-040

### SYN-124: Footage dated in the future by a wrong camera clock never uploads.
- What was going on: Cameras with clocks set ahead write files dated in the future, and a rule to wait until files stop changing never sees them as settled.
- What the product must do: Future-dated files upload like any other, and the editor sees which file and date are wrong until they are fixed.
- Kind: 3
- State: still open
- From: L11-017

## Computers joining and changing

### SYN-125: Transfers sat at 0% forever after an editor's computer was reinstalled.
- What was going on: The computer came back with a new sync identity and the server kept sharing to the old dead one, so 387 items, 48.5 GB, never moved and nothing said why.
- What the product must do: When a known computer appears with a new sync identity, the dashboard says so and lets an admin approve it, after which transfers resume within a minute.
- Kind: 3
- State: outcome not found
- From: P03-001, M02-017

### SYN-126: One failure stopped the rest of a sharing change and was reported wrongly.
- What was going on: When one folder of 40 failed to share, the other 30 were never tried and the record still described all 40 as done.
- What the product must do: Each folder succeeds or fails alone, the rest still run, and the page states "applied N of M" with the refusal reason.
- Kind: 3
- From: L04-143

### SYN-127: A folder list any editor can edit could make the server store unlimited rows.
- What was going on: Entries past the cap were each recorded as invalid, so a list naming 10,000 folders produced 10,000 records rewritten every cycle.
- What the product must do: Input from a file editors can write is capped in what it stores too: past the cap, one record says how many were ignored.
- Kind: 3
- From: L06-043

## Project folders on an editor's computer

### SYN-128: A project folder renamed by hand on an editor's computer stopped uploading unnoticed.
- What was going on: A folder present last pass and now gone read as "not yet downloaded", so new footage stopped uploading and the old folder was re-downloaded beside it.
- What the product must do: A project folder seen before and now gone is an error naming it, and where it went if found, with a one-click put-back that deletes nothing.
- Kind: 3
- From: L03-010, H07-141

### SYN-129: A project renamed while open in Resolve later pointed sync at an empty folder.
- What was going on: The local move failed because Resolve held files; the next pass created the new folder with proxies only and adopted it, leaving the real copy unsynced.
- What the product must do: A rename that cannot be applied locally stays visibly blocked until it can; the app never adopts a folder it created itself or stops uploading the real copy.
- Kind: 3
- From: H06-011

### SYN-130: A project kept saying it could not move its folder after that was fixed.
- What was going on: The message cleared only on a successful move, so once the folder was right by another route the project stayed paused.
- What the product must do: Once a project's folder is where it belongs, the "could not move" message clears and the project syncs again.
- Kind: 3
- From: L05-083

### SYN-131: Project folders on a computer that are in no sync plan were invisible.
- What was going on: A project folder left on disk outside every plan was never synced or reported, yet still counted as that computer holding the files.
- What the product must do: Folders in no plan are reported with count and size and never deleted, and an empty or unreachable plan is never read as "everything is stray".
- Kind: 3
- From: L03-011

## Facts about the NAS and the operating systems

### SYN-132: A NAS share in restricted permission mode refuses permission changes.
- What was going on: On a TrueNAS dataset in restricted ACL mode, changing a file's or folder's permissions is refused, so a sync that set permissions stalled at its temporary files.
- What the product must do: Sync onto the NAS never depends on changing file or folder permissions, and transfers complete on a restricted share.
- Kind: 1a
- From: C01-001

### SYN-133: Synology's built-in secure file transfer silently cut proxies over 514 MiB short.
- What was going on: With large read sizes and many parallel requests, Synology DSM 7.2's secure file transfer stops at 539,000,832 bytes while the download appears successful.
- What the product must do: Transfer settings known to truncate on that NAS are refused, and a downloaded file shorter than the source is never marked done.
- Kind: 1a
- State: fixed, never shipped
- From: L11-009

### SYN-134: On macOS a rename silently replaces a file already at the destination.
- What was going on: Windows refuses to rename onto an existing file, but macOS replaces it silently, so a restore that "never overwrites" lost a fresh copy on Macs.
- What the product must do: Restoring or moving a file never overwrites an existing file on any platform, including one that appears during the move; a clash is refused and named.
- Kind: 1a
- From: H06-064, L08-032

### SYN-135: Power loss can leave a full-size file of zeros that a size check calls good.
- What was going on: After power loss NTFS and APFS can leave a file at its full size but filled with zeros; comparing by name and size then spreads it everywhere.
- What the product must do: A zero-filled file left by a power cut is never sent over a good copy on the server or another computer.
- Kind: 1a
- State: outcome not found
- From: H08-023

## Sealed

### SYN-S01: The folder sync tool stalls on a restricted-permission NAS share.
- What was going on: On a NAS dataset in restricted ACL mode the tool's per-folder permission changes failed and transfers sat in temporary files.
- What the product must do: The tool is told to ignore permissions on the NAS side, and transfers complete there.
- Kind: 1b
- Tool: Syncthing (ignorePerms on a TrueNAS restricted-ACL dataset)
- From: M05-065

### SYN-S02: Sharing a folder with an unapproved device looks successful and silently does nothing.
- What was going on: The tool accepts a folder share naming a device it has not approved, replies OK and drops the device, so repeating the share every minute changes nothing.
- What the product must do: A device is added to a share only after approval; one awaiting approval is shown as waiting, and no share to it is claimed or logged as made.
- Kind: 1b
- Tool: Syncthing (a folder config naming an unconfigured device is accepted and the device stripped)
- From: L01-068, H03-032, H02-035

### SYN-S03: A sync tool with its settings wiped comes back as a new device.
- What was going on: Started on an empty settings folder the tool regenerates its settings with a new device identity, but the app neither restarted it nor re-read the identity.
- What the product must do: When the tool's settings are missing it is restarted to regenerate them, and its identity is re-read so shares follow the new one within one report.
- Kind: 1b
- Tool: Syncthing
- From: H03-002, H03-001

### SYN-S04: A new computer's connection to the NAS dropped one second after connecting, forever.
- What was going on: Handshake then "reading length: EOF" after about 1 s means the other side does not list this device; a fresh configuration knows no devices.
- What the product must do: Setup enrols the computer and the NAS in each other's device lists before the first connection, confirms it stays up, and names any second running copy.
- Kind: 1b
- Tool: Syncthing
- From: G01-013, C01-022

### SYN-S05: The folder sync tool keeps "folder path missing" after a drive returns.
- What was going on: The tool rechecks a missing folder path only on its next scan; its folder marker's name is set per folder, was a file in old versions, and paths may begin with ~.
- What the product must do: When a folder is in that error and its directory and marker exist again, a rescan is requested, at most every five minutes.
- Kind: 1b
- Tool: Syncthing
- From: C03-065, P11-042, L08-044

### SYN-S06: The folder sync tool reports "nothing needed" before it has heard from its peer.
- What was going on: A freshly added empty folder reads idle with zero bytes needed before it connects, which a benchmark recorded as a completed sync at zero seconds.
- What the product must do: "Synced" is reported only after the peer is connected and has sent its file list.
- Kind: 1b
- Tool: Syncthing
- From: H04-065

### SYN-S07: The folder sync tool's web control page has no login by default.
- What was going on: The tool ships its control page without a password, on the NAS and on editors' computers alike.
- What the product must do: Every control page the product runs requires a login or is unreachable from the network.
- Kind: 1b
- Tool: Syncthing
- From: L01-029

### SYN-S08: The folder sync tool's conflict copies are silent files with a fixed name pattern.
- What was going on: The tool renames the losing version "<name>.sync-conflict-<date>-<time>-<id>.<ext>" beside the file, for any file type, and reports nothing.
- What the product must do: A scan of the synced tree finds files matching that pattern for every extension and reports the count and up to 20 paths.
- Kind: 1b
- Tool: Syncthing (sync-conflict files)
- From: L02-009, H07-140

### SYN-S09: Un-ignoring one subfolder in the folder sync tool un-ignores everything under its parent.
- What was going on: In the tool's ignore rules an include naming a folder includes its whole subtree, and the tool descends into ignored folders when a deeper include could match.
- What the product must do: Sharing one subfolder of a project delivers exactly that subfolder, and both sides then report complete.
- Kind: 1b
- Tool: Syncthing v2 ignore patterns (.stignore negation)
- From: M02-018, C02-075

### SYN-S10: On Windows the folder sync tool reads backslash escapes as path separators.
- What was going on: Names with brackets or braces were escaped with backslashes, which the tool on Windows reads as separators, so a shared subtree stayed invisible while reading back confirmed.
- What the product must do: Ignore patterns for such names are written in a form the tool reads the same on Windows and macOS, proven against the real tool before release.
- Kind: 1b
- Tool: Syncthing ignore patterns
- From: H07-059

### SYN-S11: Auto-accepted shared folders land flattened on editors' disks.
- What was going on: The tool's auto-accept turns a folder label containing slashes into one flat folder name instead of the nested project path.
- What the product must do: Each shared project lands at its true nested path on the editor's disk.
- Kind: 1b
- Tool: Syncthing (autoAcceptFolders)
- From: C01-023

### SYN-S12: The folder sync tool upgrades itself and reports crashes to its makers.
- What was going on: The pinned version was replaced by the tool's own updater every 12 hours, and crash data left the studio.
- What the product must do: Helper tools on editors' computers stay at the pinned version and send nothing to their makers.
- Kind: 1b
- Tool: Syncthing (auto-upgrade, crash reporting)
- State: still open
- From: H07-133

### SYN-S13: The owner found the folder sync tool much faster than the copy tool.
- What was going on: Bulk transfers ran on a copy tool the owner saw as much slower than the folder sync tool; moving them across was planned, then dropped.
- What the product must do: The heaviest transfers run close to the link's real speed, measured, before any choice of how they travel is settled.
- Kind: 1b
- Tool: Syncthing (seen faster) versus rclone (seen slower) for the bulk transfers
- From: P04-012

### SYN-S14: A filter for folders at any depth missed the folder at a project's top.
- What was going on: The tool's any-depth folder pattern requires at least one parent folder, so a Proxy folder at the project root did not match.
- What the product must do: Proxy folders at every depth, the project root included, follow the proxy rules.
- Kind: 1b
- Tool: rclone filter patterns (**/Proxy/**)
- From: M05-064

### SYN-S15: The transfer tool's filters match raw bytes, and the first matching rule wins.
- What was going on: A composed-spelling exclude missed a Mac's decomposed file, and an include listed earlier overrode a later exclude.
- What the product must do: Every exclude is given in both Unicode spellings, placed before any include, and a folder exclude also covers everything inside it.
- Kind: 1b
- Tool: rclone (filter rules)
- From: L02-005

### SYN-S16: Folder names with [brackets] in a transfer filter excluded files nobody asked to skip.
- What was going on: The tool's filter rules read brackets as a pattern, and the studio's tree really contains bracketed names.
- What the product must do: Any real name passed into a filter rule is escaped so it matches only itself.
- Kind: 1b
- Tool: rclone filter rules
- From: C01-043

### SYN-S17: The transfer tool rewrites full-width punctuation in file names unless told not to.
- What was going on: By default on Windows it marked names holding full-width forms with U+201B and mapped ： ？ ｜ back to plain forms, asking for files that did not exist (628 of 2,507 names).
- What the product must do: The tool's local name encoding is pinned so names round-trip byte for byte, tested with full-width ？ ： and quotes, and a failure names the file.
- Kind: 1b
- Tool: rclone (--local-encoding; default Windows encoding) with yt-dlp's full-width names
- From: P05-036, M05-029, P02-042

### SYN-S18: A slow computer clock silently stopped every proxy download.
- What was going on: The tool ages remote files against the local clock, so with a slow clock every NAS file looks future-dated, is skipped, and the run still exits successfully.
- What the product must do: A minimum-age rule on remote files is not trusted while the local clock is off, and such a run is reported as blocked by the clock.
- Kind: 1b
- Tool: rclone (--min-age)
- From: L02-020

### SYN-S19: Mirroring with a minimum-age filter bins files freshly rewritten on the source.
- What was going on: The age filter applies to each side separately, so a recently rewritten NAS file is hidden and the editor's older copy is treated as deleted and moved to backup.
- What the product must do: No age filter is combined with mirroring deletions in a way that hides a rewritten source file.
- Kind: 1b
- Tool: rclone (sync with --min-age and --backup-dir)
- From: H02-031

### SYN-S20: Files moved to the local bin appeared in transfer history as downloads.
- What was going on: Moving a file into the backup folder logs two records, a move then a move-into-backup, and counting the first made it look transferred.
- What the product must do: History and counts show a file moved to the local bin as removed, never as downloaded, and count it once.
- Kind: 1b
- Tool: rclone JSON log with --backup-dir ("Moved (server-side)" then "Moved into backup dir")
- From: H02-032

### SYN-S21: The transfer tool reported success on a proxy the NAS had cut short.
- What was going on: With 255 KiB chunks and 64 parallel requests against a server lacking the transfer-limits extension, the tool finished with success on a truncated file.
- What the product must do: Use 64 KiB chunks and 16 parallel requests or fewer against such servers, and check the finished size independently of the tool's success.
- Kind: 1b
- Tool: rclone (SFTP backend, chunk size and concurrency)
- State: fixed, never shipped
- From: L11-010

### SYN-S22: The transfer tool's checksums over secure file transfer need a shell on the NAS.
- What was going on: It computes checksums by running hash commands on the NAS, which a file-transfer-only account cannot do.
- What the product must do: Transfers verify integrity without running commands on the NAS before editor accounts are restricted to file transfer only.
- Kind: 1b
- Tool: rclone (over SFTP)
- From: L01-028

### SYN-S23: An interrupted upload to the NAS restarts every file from zero.
- What was going on: The tool cannot resume uploads over secure file transfer; ending it by an app update, a sleep or a timeout throws away hours of a big file.
- What the product must do: An in-flight upload is never ended for routine reasons or for being slow; an app update waits for it or leaves it running.
- Kind: 1b
- Tool: rclone over SFTP
- From: C01-045, L08-047, P12-050

### SYN-S24: The transfer tool's own timeouts do not cover a stuck local read.
- What was going on: Its network timeout covers remote traffic only, and its maximum-duration limit is never checked during a blocked local read.
- What the product must do: Every transfer run is watched from outside for byte progress.
- Kind: 1b
- Tool: rclone (--timeout, --max-duration)
- From: L02-045

### SYN-S25: A time-limited transfer run waits alone on its last big file.
- What was going on: Past a soft time limit it starts nothing new and waits for files in flight; one stream used a quarter of the line, and two runs share temporary names.
- What the product must do: Never end a run mid-file, never transfer one file in two runs at once, and keep the computer awake while a file is in flight.
- Kind: 1b
- Tool: rclone over SFTP (--max-duration soft limit)
- From: L10-065

### SYN-S26: Editors' transfers failed with "key mismatch" on every new site.
- What was going on: The NAS offers several host key types, the tool prefers ECDSA, and only the ed25519 key had been recorded.
- What the product must do: Record the NAS host key with its key type and tell the tool to use exactly that type.
- Kind: 1b
- Tool: rclone (SFTP host key checking)
- State: fixed, never shipped
- From: L11-023

### SYN-S27: Leaving out the parallel-streams setting does not mean zero streams.
- What was going on: The tool defaults to 4 parallel streams per file, so a recommendation that omitted a winning value of 0 selected the slower setting.
- What the product must do: Any recommended or applied transfer setting states every value explicitly, including zero.
- Kind: 1b
- Tool: rclone (--multi-thread-streams)
- From: H04-066

### SYN-S28: The transfer tool's "obscured" passwords can be read back.
- What was going on: Its stored passwords are only obscured, revealed by a single command, and could land in benchmark output.
- What the product must do: Stored transfer passwords are treated as plain secrets and never written to logs, reports or results.
- Kind: 1b
- Tool: rclone (obscure / reveal)
- From: H04-067

### SYN-S29: The transfer tool logs retries as errors even when the run succeeds.
- What was going on: Retried operations are written at error level; only the exit code says whether the run failed.
- What the product must do: A transfer run is judged failed only by the tool's final result, never by error-level lines in its output.
- Kind: 1b
- Tool: rclone
- From: C01-002

### SYN-S30: The transfer tool reads a minimum size of "1" as 1 KiB, not one byte.
- What was going on: Measured: a bare "1" as the minimum file size means 1 KiB; "1B" is needed to skip only empty files.
- What the product must do: A minimum-size filter meant to skip empty files still lets one-byte and small files sync.
- Kind: 1b
- Tool: rclone (--min-size)
- From: H01-042

### SYN-S31: Each transfer run opens its own NAS login pool and lists the whole folder.
- What was going on: Pools are not shared between runs, so a run set to 16 connections can log in 16 times per project per pass plus a full recursive listing.
- What the product must do: Size connection counts for checks that find nothing, not for big uploads, and do not start a run when nothing local has changed.
- Kind: 1b
- Tool: rclone (sftp-connections, checkers, per-run connection pool)
- State: fixed, never shipped
- From: L11-063

### SYN-S32: The transfer tool leaves part-files beside the real file in the destination.
- What was going on: By default an interrupted transfer leaves a file named with a random token and a ".partial" ending in the destination folder, which nothing removes.
- What the product must do: Every filter for the synced folders excludes these part-files, and orphans are found and reported.
- Kind: 1b
- Tool: rclone
- From: H04-057

### SYN-S33: A free tunnel service may carry video only with caching turned off.
- What was going on: The service's terms were read as allowing video when caching is bypassed; that is a reading, not written permission, and throttling must be watched.
- What the product must do: A route through a third-party tunnel runs uncached, on its own account, with its rate checked daily for throttling.
- Kind: 1b
- Tool: Cloudflare Tunnel
- From: P12-039

### SYN-S34: Keeping Windows awake silently failed after a single nudge.
- What was going on: A Windows keep-awake request belongs to the thread that made it and vanishes with it; without the continuous flag it resets the idle timer only once.
- What the product must do: Sleep is held off exactly as long as work is moving and always released afterwards.
- Kind: 1b
- Tool: Windows SetThreadExecutionState (ES_CONTINUOUS, per-thread)
- From: C01-046

### SYN-S35: A time-limited child-process wait could still hang forever on Windows.
- What was going on: After killing a child on timeout, the call waits for its output pipes to close, which never happens when a grandchild inherited them.
- What the product must do: Every wait on a child process has a hard limit, and a run cut off is reported as "could not tell", never as an empty result.
- Kind: 1b
- Tool: Python subprocess.run(timeout=) on Windows
- From: L02-046

## Removed

- P01-030 | no longer applies: the studio's projects live on its NAS; keeping cloud-drive files offline is not part of the product
