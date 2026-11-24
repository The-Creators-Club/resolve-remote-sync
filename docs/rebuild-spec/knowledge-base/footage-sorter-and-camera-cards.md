# The Footage Sorter and camera cards: what real use taught

183 lessons. Each is one rule the product can be tested against: what a person saw (the heading), why it happened, and what the product must do. Kinds: *given* is a fact about something the studio has whatever is built; *ruling* is the owner's decision; *situation* is something the product must survive.

## Recognising cards and drives

### SRT-001: Cards in CFexpress Type B readers and camera SSDs look like fixed disks.
- Why: Windows presents a card in a CFexpress Type B reader, a built-in reader, or a Blackmagic camera SSD as a fixed disk, so a removable-only check misses it.
- Must: A fixed disk with a camera's folder layout is detected, copied and judged as a card; the system disk never is, and a card is never offered as a destination.
- Kind: given

### SRT-002: A card that mounts slowly looked empty at first and was ignored for minutes.
- Why: Some cards appear to Windows seconds before their files can be read, so the first look finds nothing.
- Must: A newly mounted drive that looks empty is checked again over the next several scans and appears as a card once its files show.
- Kind: given

### SRT-003: A Mac never listed its own startup disk.
- Why: On macOS the startup disk appears in the volumes folder as a link to the root; its data volume's ID survives macOS updates.
- Must: A Mac's startup disk is listed exactly once for local backups, never as a card, and is identified by an ID that survives macOS updates.
- Kind: given

### SRT-004: Drive letters change between plug-ins and computers; volume serials do not.
- Why: One drive gets different letters on different computers and plug-ins, and Windows hands an unplugged drive's letter to the next card reader.
- Must: Every drive is known by its volume serial, never its letter, and a card is detected whatever letter it gets, including one another drive used earlier.
- Kind: given

### SRT-006: A camera card formatted in camera must still be recognised.
- Why: An in-camera format erases every file, including any mark written on the card, and on some bodies also changes the card's volume serial.
- Must: Each card keeps a name and number recognised after in-camera formatting, guessed from its kind, capacity and days of use, with the owner confirming a guess.
- Kind: given

### SRT-007: One Windows drive that never answered made every camera card vanish.
- Why: Windows' request for one drive's volume information can hang without end, freezing every card and drive report from that computer with nothing logged.
- Must: A drive that does not answer within 5 seconds is skipped and logged, and every other card and drive on that computer keeps being reported.
- Kind: given

### SRT-008: Windows Task Manager can switch off a startup entry, and it stays off.
- Why: An entry disabled once in Task Manager stays disabled across reinstalls; the owner disabled one with no recognisable name, so inserting a card opened nothing.
- Must: Whatever notices cards starts at sign-in under the product's name and icon, and installing it clears a stale disabled flag.
- Kind: given

### SRT-010: Each inserted card opened another browser tab.
- Why: The owner: "I never want it to do that"; several cards opened five tabs, and cards inserted while the sorter was open did not join its list.
- Must: A new card shows in an already open sorter tab, a tab opens only if none is open, and every card inserted while it runs joins its card list.
- Kind: ruling

### SRT-005: A field drive returned under another letter; a laptop's NAS letter pointed at itself.
- Why: Field drives came back under other letters between copy rounds, and one laptop's letter for the NAS pointed at its own disk.
- Must: A copy refuses a destination on its own source drive, and refuses a destination different from earlier rounds unless the person confirms it.
- Kind: situation

### SRT-009: A card swapped in right after another was pulled raised no prompt.
- Why: The owner: "IT'S NOT POPPING UP WHEN I PULL A CARD OUT AND PUT ANOTHER ONE IN"; another time card detection had not started and nothing said so.
- Must: Every card inserted, including straight after another is pulled, appears within seconds without a click, and the sorter says so when card detection is not running.
- Kind: situation

### SRT-011: Backup drives chosen in the field were offered as cards to back up.
- Why: A field SSD and hard drive are removable just like cards.
- Must: Drives chosen as copy destinations are recognised by identity and never offered as cards to back up.
- Kind: situation

### SRT-012: A camera card closed in the source list could not be brought back.
- Why: Closing a card hid it until it was unplugged and reinserted.
- Must: A closed card still in its reader stays listed under its computer as closed and is shown again with one click.
- Kind: situation

### SRT-013: Camera cards disappeared from the page whenever the server restarted.
- Why: Cards were known only to the running server, so each restart dropped them until the computer next reported.
- Must: A card still in its reader stays listed across a server restart.
- Kind: situation

### SRT-014: "Which drive is which" question windows stacked up without end.
- Why: On Windows a question window leaves the app's timers running, so a drive check every 3 s asked the same question again on each tick.
- Must: At most one question window is shown at a time, and nothing asks again while one is open.
- Kind: situation

### SRT-015: A broken field settings file quietly made the laptop behave as if at home.
- Why: An unreadable field settings file was ignored, and the sorter silently fell back to home behaviour.
- Must: Settings that cannot be read are reported loudly where the person looks, never silently ignored.
- Kind: situation

## What cameras and recorders write

### SRT-016: Sony cards carry per-clip thumbnails and index files that are not clips.
- Why: A Sony card holds a thumbnail per clip (THMBNL/<clip>T01.JPG) and card index files (the AVF INFO folder, MEDIAPRO.XML, CUEUP.XML, STATUS.BIN).
- Must: The thumbnail attaches to its clip, index files are never listed as clips, and both are still copied with the card.
- Kind: given

### SRT-017: A Sony FX3 keeps each clip's proxy in a separate SUB folder.
- Why: The FX3 writes each proxy as <clip>S03.MP4 in PRIVATE/M4ROOT/SUB beside the CLIP folder, so a card of 88 clips listed as 172.
- Must: Each SUB proxy joins its master as that clip's proxy; a proxy whose master is not on the card stays listed on its own.
- Kind: given

### SRT-019: The studio's own camera clips can be told apart by their files.
- Why: A Sony clip has a companion XML file beside it, and a Blackmagic clip is .braw or follows the camera's reel-and-clip naming.
- Must: Own-camera clips are identified by these marks, and downloaded video is never treated as the studio's footage.
- Kind: given

### SRT-020: Cards used on a Mac are full of hidden "._" files.
- Why: Two Blackmagic CF cards held 160 and 255 macOS "._" files beside 239 and 382 real media files.
- Must: Card checks and backups ignore "._" files and never count them as missing footage.
- Kind: given

### SRT-021: Card housekeeping files share names and sizes across different cards.
- Why: SONYCARD.IND, DATABASE.BIN, MEDIAPRO.XML and "._" files repeat across cards, giving false matches, while folders reorganised on the way to the NAS gave false misses.
- Must: A card's backup check matches every real media file wherever it sits in the archive and ignores housekeeping files.
- Kind: given

### SRT-022: Opening a folder in Explorer adds a file that breaks size checks.
- Why: Visiting an image-sequence folder in Explorer leaves a Thumbs.db there, which made later move checks fail on a size mismatch.
- Must: Size and completeness checks ignore files Windows adds by itself, while those files still travel with their folder.
- Kind: given

### SRT-023: Reused Blackmagic cards carry empty metadata stubs named like real files.
- Why: A card can hold 0 or 24-byte metadata files while the archive already holds the real multi-megabyte file of the same name.
- Must: An offload never replaces an archived file with a smaller file of the same name.
- Kind: given

### SRT-025: Resolve attaches proxies found in a Proxy folder beside their originals.
- Why: The owner wanted card proxies "inside a 'proxy' subfolder within the main date folder so that blackmagic can pick them up".
- Must: Proxies copied off a card land in a Proxy subfolder of the dated folder holding their originals, with matching base names.
- Kind: given

### SRT-026: Camera RAW video has no picture to show until its proxy exists.
- Why: Common open decoders cannot read Blackmagic RAW or RED RAW, so such a clip gets a thumbnail or preview only from its proxy.
- Must: A RAW clip previews from its proxy, says plainly when it has none yet, and picks up the picture soon after a proxy appears.
- Kind: given

### SRT-027: Sony RAW stills carry a ready JPEG preview.
- Why: 4,681 .ARW stills had no thumbnail although each holds an embedded JPEG preview readable from a few KB of tags.
- Must: Every camera RAW still shows a thumbnail taken from its embedded preview.
- Kind: given

### SRT-018: A Sony proxy folder's own XML file was read as the clip's metadata.
- Why: When a proxy folder holds an XML file, taking the first XML found read the proxy's, losing the clip's unique id and camera model.
- Must: A clip's identity and camera model come from the metadata file beside its master, never from one in its proxy folder.
- Kind: situation

### SRT-024: Camera side files cluttered the clip view and got separated from their clips.
- Why: Side files showed as entries beside videos, 35 clips' side files were moved into a proxy folder, and clips gone from disk vanished from the move plan unannounced.
- Must: A camera's side files travel with their clip on every copy and move, are never shown as clips, and an assigned clip missing from a scan is listed.
- Kind: situation

### SRT-028: Some FX3 clips have no sound track and kept failing as errors.
- Why: Pulling sound from these clips failed before upload, and each counted as an error.
- Must: A soundless clip is recognised as such, reported once as unmatchable by speech, and never retried as a failure.
- Kind: situation

## Damaged and unfinished recordings

### SRT-029: A camera stopping mid-clip on exFAT leaves a full-size file of zeros.
- Why: exFAT keeps a valid-data length apart from file size; if never written, the clip reads as zeros and every copy verifies. Two 48 GB FX3 interview clips were lost.
- Must: Every clip is checked for real content before its card counts as backed up, and a verified copy is never taken as proof a clip plays.
- Kind: given

### SRT-030: Interrupted Sony and Blackmagic takes can be recovered only from a raw card image.
- Why: Sony leaves an unfinished-recording file; a BRAW take cut short has no index at its end and no in-camera recovery file.
- Must: Such clips are flagged at offload, and the person is told a raw card image taken before formatting is the only recovery.
- Kind: given

### SRT-031: Damaged clips must be caught at offload, before the card is reused.
- Why: Warning signs: an empty XML metadata file, a missing camera proxy, an all-zero start or tail, no index at the end, Sony unfinished recordings, BRAW without its index.
- Must: Every card and copy is checked for these signs; a damaged copy is marked, never counts as a backup, and the editor is told before wiping.
- Kind: situation

## Clocks and file dates

### SRT-032: A sound recorder with an unset clock writes wrong dates but keeps steady time.
- Why: Fifteen of forty recorder files said January 2021 while the cameras were right; one offset (+12:33) lined every file up with the camera takes.
- Must: Recorder audio is matched to interviews by its content and the cameras' times, never by the recorder's own timestamp.
- Kind: given

### SRT-033: Camera and recorder clocks are often whole hours off, and change mid-trip.
- Why: A cinema camera ran five hours off local time, a recorder four hours behind, wireless mic recorders reset to 2000 with one shared offset; clocks were changed mid-trip.
- Must: Time matching tries whole-hour offsets and a fitted offset for reset clocks, never assumes one offset holds for a trip, and names shoot folders in local time.
- Kind: given

### SRT-034: File dates on camera and recorder media are often not the recording time.
- Why: BRAW files carried the day the card was copied; recorder files copied without timestamps carried the copy time, or the recording's end, 47 minutes late.
- Must: Every copy keeps the original file times, and placement treats file dates as a hint that sound matching may overrule.
- Kind: given

### SRT-035: A night shoot crosses midnight, so its clips carry two dates.
- Why: The owner: "The party went into the next day", and clips from after midnight were left out of the shoot.
- Must: Clips recorded after midnight stay with the night's shoot, not filed as a separate day.
- Kind: given

### SRT-036: A Sony clip carries a unique id; a recorder file's start must be worked out.
- Why: Sony clips carry a unique id in their metadata file; a recorder WAV's start is its modified time minus its length.
- Must: A clip is identified by its camera id where present, else by name, size and day, with recorder files also matched by modified time.
- Kind: given

## Telling recordings apart

### SRT-037: A file name does not identify a recording.
- Why: Same names held different clips (11.8 GB against 69.8 GB) or card files every card carries; reset recorders reused names like 010121 006; one clip's proxies differed by 12 bytes.
- Must: Recordings are told apart by content and size, never by name alone, and same-name different files are kept apart, never one replacing the other.
- Kind: given

### SRT-039: Sony dual-slot recording writes two differing files that hold the same footage.
- Why: Copies from slot A and slot B differ by 128 KiB, only in a padding block and the real-time metadata track; video and audio are bit-identical.
- Must: Such copies are recognised as one recording from two slots and treated as duplicates, never as conflicting takes.
- Kind: given

### SRT-040: A second card that stopped early holds a strict prefix of the recording.
- Why: One slot's copy ran 10:44 of a 63:42 recording; its packets were an exact prefix of the full one on the NAS.
- Must: A shorter same-name clip whose content is a prefix of a longer one is shown as a partial second-card copy, and the complete one is kept.
- Kind: given

### SRT-043: Redundant copies are quarantined, never deleted.
- Why: The owner: "quarantine, don't delete"; 1,479 verified-redundant files (1,036 GB) were set aside for him to delete by hand.
- Must: Clearing duplicates moves only content-verified redundant copies into a quarantine on the same volume mirroring their paths; nothing is deleted and empty folders are only reported.
- Kind: ruling

### SRT-044: Duplicates are badged, and the copy already sorted into a project wins.
- Why: The owner: keep the largest or newest, either if identical, mark duplicates red with "S" on the smaller, and keep a sorted copy over an unsorted one.
- Must: Duplicates carry a visible badge marking the smaller copy, and the plan keeps the sorted copy, else the larger or newer, never moving both.
- Kind: ruling

### SRT-038: Two files of the same size were treated as the same file.
- Why: A same-size file at the target was skipped as identical, and one version compared nothing for files over 64 MiB.
- Must: Two files count as identical only when their full content matches, whatever their size; a same-size different file is never skipped or replaced.
- Kind: situation

### SRT-041: Two recorders started together can write identical-looking files.
- Why: Synced recorders that start and stop together can match on name, size and time, so one card's file could mark another card's as backed up.
- Must: A copy proves a card file safe only when it is tied to that card; two cards' look-alike files never vouch for each other.
- Kind: situation

### SRT-042: A re-inserted card showed every clip twice, each its own duplicate.
- Why: The card was listed again beside its earlier listing, so its clips were flagged duplicates and looked not backed up.
- Must: A card inserted again replaces its earlier listing and keeps its assignments, and every clip appears once in any view.
- Kind: situation

## Copying a card

### SRT-047: A card copies only what has no verified copy yet.
- Why: Clips identical to backups were set to be copied over them; the owner: identical clips "should not be backed up again", and a card copies what no field drive holds.
- Must: From a card, every clip without a verified copy on a field drive or at home is copied, and "is it backed up" is answered from recorded verified copies.
- Kind: ruling

### SRT-048: In the field, a card copies to every ticked destination at once, offline.
- Why: On location a laptop copies a card to field drives, a laptop folder, and the NAS only if reachable.
- Must: One card copies to every ticked destination in parallel, shows "already on X" and "safe to format" offline, and the record catches up when next online.
- Kind: ruling

### SRT-050: Camera proxies are copied off a card only when asked.
- Why: The owner: "I don't want bmcc or fx3 proxies backed up automatically. It should ask me when I click copy... By default it is unticked."
- Must: The copy offers "Back up proxies too", unticked by default, and proxies and their descriptive files are copied only when it is ticked at Copy.
- Kind: ruling

### SRT-053: A card backup starts at once, even while the computer is in use.
- Why: Someone is standing at the reader, so a card copy must not wait for the computer to go idle as background work does.
- Must: A card or drive copy asked for from any browser starts right away on the computer holding the card, whether or not someone is using it.
- Kind: ruling

### SRT-054: Card backup to the NAS must be as fast as a dedicated copier.
- Why: A simple one-file, read-then-write copy lost overlapped reads, resume and verification; the owner: otherwise "the backup will be extremely slow".
- Must: Card backup overlaps reading and writing, reaches at least a dedicated copier's speed on the same card and link, and resumes without starting over.
- Kind: ruling

### SRT-058: Before copying, every clip on a card is accounted for.
- Why: The owner asked for a warning when clips neither backed up nor assigned remain at copy time.
- Must: Before copying, any clip neither backed up nor assigned raises a warning, and the summary shows backed-up and not-backed-up counts.
- Kind: ruling

### SRT-059: A finished card copy said nothing.
- Why: The owner: "after the fast verification finishes you should get a notification message".
- Must: When a card copy and its check finish, a notice names the card, counts copied, already there and checked, and points to any failures.
- Kind: ruling

### SRT-060: Copy progress and speed show live in the browser.
- Why: The owner: "you should also be able to see backup progress and speed in the browser", for card copies, drive copies, scans and the cloud upload.
- Must: Each running backup shows percent, speed, time left, current file and whether copying or checking, refreshed every few seconds while visible, never in a hidden tab.
- Kind: ruling

### SRT-061: A card can be used on several days before it is backed up.
- Why: A card shot on one day may be used again days later without backup and reset, and both uses must be recorded.
- Must: Logging a card's use on a new day always works and keeps earlier uses, and the card list includes every card the studio owns.
- Kind: ruling

### SRT-062: The crew's card tracker is bilingual and strict about "backed up".
- Why: The crew's card tracker shows English and Traditional Chinese together, and a finished copy flips a card to backed up.
- Must: Crew-facing card pages show English and Traditional Chinese, and a card is marked backed up only when every clip on it has a copy.
- Kind: ruling

### SRT-063: The card recorder page installs as an app on phones.
- Why: The owner: "make the card recorder also installable on ios and android".
- Must: The card recorder installs to the home screen on iOS and Android and opens as an app.
- Kind: ruling

### SRT-045: A card copy never overwrites, except to finish its own partial copy.
- Why: A destination checked up front can gain a file before the copy lands, and a half-copied clip skipped as "same size" was never resumed.
- Must: An existing file is skipped only when proven the same recording, its shorter copy is resumed, any other file stays and the card's file lands beside it, never overwriting.
- Kind: situation

### SRT-046: A different card swapped into the reader mid-copy got a false "copied".
- Why: Swapping cards mid-copy showed "copied", and an unchecked run marked the crew's card backed up in the card tracker.
- Must: A copy refuses when the card in the reader is not the planned one, and "copied" or "backed up" appears only once every clip on it has a checked copy.
- Kind: situation

### SRT-049: Copies made to the field SSD alone were never carried to the second drive.
- Why: On a trip only the SSD was plugged in; copies owed to the hard drive were forgotten, and the nightly copy gave up when it was absent.
- Must: Every copy owed to a second drive is remembered across restarts and starts by itself, or asks, as soon as that drive appears.
- Kind: situation

### SRT-051: A resumed copy saw a clip's master and skipped its missing proxy.
- Why: Masters copy before proxies, so every stopped run ended before the proxies, and resumes left 269 proxies uncopied.
- Must: A clip counts as copied only when every file chosen for it (master, and proxy and metadata if chosen) is present at full size; missing ones are copied.
- Kind: situation

### SRT-052: A card's still photos must be backed up with its video.
- Why: Two drone cards held 446 clips and 14 raw photos, and the owner had to ask whether the stills were copied.
- Must: A card backup copies and verifies every clip and still, and only then says the card may be removed or wiped.
- Kind: situation

### SRT-055: A computer with no NAS destination silently offered nowhere to copy.
- Why: An editor's computer had no NAS location set, so neither card copy nor the field page offered the NAS, and nothing said why.
- Must: When a computer cannot name the NAS as a destination, the card copy says so and how to fix it.
- Kind: situation

### SRT-056: An empty 2 TB SSD showed 0 GB free for a trip's first copy.
- Why: The target folder did not exist yet, so its free space read as zero.
- Must: Free space for a folder not yet created is the free space of the drive it will be created on.
- Kind: situation

### SRT-057: Clicking copy in the card sorter gave an unexplained error.
- Why: Copying a card's clips to their destinations failed with an error whose cause was never recorded.
- Must: A failed copy names the clip, the destination and the reason in plain words, and says what was partly copied.
- Kind: situation

## Checking a copy

### SRT-065: Reading a copy straight back checks the computer's memory, not the drive.
- Why: The operating system serves a just-written file from its memory cache, so a read-back proves nothing about what reached the disk.
- Must: A copy is called verified only after content read from the drive itself, bypassing the cache, matches the source.
- Kind: given

### SRT-064: Footage copies are checked quickly by default, never read back in full.
- Why: The owner: "headers and byte size. Don't run the full verification", later adding the end; this misses damage in the middle of a clip.
- Must: Every copy is checked by size, identical first and last 1 MiB and the movie index; a full read-back runs only when asked, and the check says it is quick.
- Kind: ruling

### SRT-066: A copy killed mid-file can leave a full-size file that passes a size check.
- Why: Copiers pre-size each file and stamp the source's modified time only on completion; a 217 GB clip changed free space not at all for 20 minutes.
- Must: A copy is done only when size and modified time (within 3 seconds) match or its content is checked, and progress is measured by bytes written, not free space.
- Kind: situation

### SRT-067: A stopped or resumed card copy left unchecked copies counted as safe.
- Why: Runs cancelled before their final check recorded what they had copied, and the next run skipped those by name and size, so 29 clips were never checked.
- Must: A copy counts only after its content is checked against the card, and a resumed run checks every earlier unchecked copy it skips.
- Kind: situation

### SRT-068: A drive that hung mid-check got 454 good copies marked bad.
- Why: The SSD hung during the check after copying, every later read failed, and each file was set aside as a bad copy.
- Must: A read error during checking stops the check and says so; only a proven size or content mismatch marks a copy bad.
- Kind: situation

### SRT-069: Two backup drives filed the same footage differently and kept partial copies.
- Why: One drive held unfinished partial copies, missed 500 GB, and filed the same card under folders dated a day apart from the other.
- Must: Backups are compared by recording identity, not folder, and an unfinished partial copy never counts as a backup.
- Kind: situation

## Drives, speed and interruptions

### SRT-070: Copying to the NAS one request at a time runs at half speed.
- Why: Over a 10 gigabit link, 1 MB writes with one in flight reached about 390 MB/s; four in flight held about 785 MB/s across 160 GB.
- Must: Bulk copies to or from the NAS keep several requests in flight and sustain at least 80% of a buffered Windows file copy's speed.
- Kind: given

### SRT-071: Several copies off one card at once are slower than one.
- Why: A card or spinning disk reads sequentially: three jobs gave 500 MB/s against 634 alone, a single-disk dock ran 26% slower; yet copies from different cards ran one by one.
- Must: Copies from different cards to different destinations run at once, one job per source device, parallel only across separate USB controllers, small proxy folders last.
- Kind: given

### SRT-072: Portable hard drives slow to 55-80 MB/s under long writes.
- Why: Shingled portable drives slow to 55-80 MB/s each in long writes, so writing three at once was fastest, while three readers on one source thrashed it to 77 MB/s.
- Must: Long copies are spread across destination drives in parallel, and concurrent reads from any one source disk are limited.
- Kind: given

### SRT-073: The field SSD hung after about 300 GB of non-stop writing.
- Why: A portable SSD used on location hung three times, each after roughly 300 GB or 20-25 minutes of continuous writing.
- Must: Long field copies pause to let the drive rest (for example 10 minutes after every 150 GB), show that it is resting, and stay cancellable.
- Kind: given

### SRT-074: Big copies to a slow USB disk froze the whole laptop.
- Why: Windows built up gigabytes of unwritten cache for a slow USB hard disk until the machine hung, even for reads from other disks.
- Must: Large copies to slow external disks never let the system's write cache pile up, so the computer stays responsive.
- Kind: given

### SRT-075: A power cut leaves an external drive dirty and its last writes lost.
- Why: An exFAT drive on its own mains supply lost power mid-write; it came back dirty and the last writes in its 256 MB cache were gone.
- Must: After a destination loses power, the drive is checked first, and each partial file resumes well before its recorded end.
- Kind: given

### SRT-078: A copy between folders on the NAS itself is instant.
- Why: Copying whole interviews between project folders on the NAS took no time and no space; the same copy from a workstation over the share ran at 82 MB/s.
- Must: Copies between folders on the same NAS are done on the NAS, never pulled through an editor's computer.
- Kind: given

### SRT-079: A move within one NAS volume is instant and keeps the creation time.
- Why: 512 MB moved in 15 ms with the creation time kept; a 328 GB re-file of 267 files took 3 seconds.
- Must: Moves between staging and project folders on one NAS volume are renames, finishing in seconds whatever the size.
- Kind: given

### SRT-080: Listing the footage tree over the network costs about 13 ms per file.
- Why: From an editor's PC a rescan took 57 s at 13.4 ms per file looked up (75k lookups); on the NAS itself 77,353 files took 22 s.
- Must: Whole-archive scans run on the NAS, and a rescan from a PC reuses what it read for files whose size and time are unchanged.
- Kind: given

### SRT-081: Watching folder times on the NAS is cheap but misses a file replaced in place.
- Why: 2,048 NAS folders' modified times read in 0.22 s warm, 2.7 s after a restart; adding a file changes its folder's time, rewriting one in place does not.
- Must: A change check based on folder times is backed by a periodic full scan that catches files replaced under the same name.
- Kind: given

### SRT-076: A destination drive hung or dropped off mid-copy.
- Why: External disks vanished mid-copy several times from heat, supply or USB bridge, some staying gone until replugged, while the copy sat without progress.
- Must: A copy with no progress for a set time stops cleanly, tells the person to replug if the drive stays gone, and later copies only what is missing.
- Kind: situation

### SRT-077: A long copy to the NAS ran unsteadily, then stopped moving unnoticed.
- Why: The owner: a trip's copy "has stopped moving", ran "much slower than this link should allow" on 10 Gb, and a card copy's speed was "so unstable".
- Must: A long copy runs steadily near the link's capacity, shows live speed, says when it stops moving, and shows where any slowdown comes from.
- Kind: situation

## Backed up and safe to format

### SRT-082: "Backed up" means on the NAS at home, or two copies on owned drives.
- Why: The owner: "what is 'backed up' will remain the same - if it's on the server at home"; client drives and cards never count; laptop copies are flagged.
- Must: A clip shows backed up only under that rule, with a daily reminder about anything not at home and one every few days about laptop-only footage.
- Kind: ruling

### SRT-089: Already backed-up clips were reported as having "no destination".
- Why: The owner: 322 clips "have no destination, but that's because they are duplicates and do not need backing up"; suggestions were offered for them too.
- Must: Backed-up clips show as backed up, never count as unassigned, and need no acceptance before copying.
- Kind: ruling

### SRT-083: Card clips already filed on the NAS read "not backed up" and "nowhere yet".
- Why: Sorting flattens a card's folders into project folders, and footage reached the NAS other ways; 125 clips with filed copies counted as not backed up.
- Must: A card clip counts as on the NAS, showing that folder, when a copy matching name, size and time exists anywhere there, unless tagged with another card's identity.
- Kind: situation

### SRT-084: A card is safe to format only when every file has its required verified copies.
- Why: An unreadable folder, a failed check, a copy from another card, or an unlisted type such as Nikon N-RAW could still let a card read "safe to format".
- Must: A card is safe only when every file, except known camera housekeeping, has its required verified copies on distinct physical disks, at home or on two field drives.
- Kind: situation

### SRT-085: Two copies on one physical disk counted as two backups.
- Why: Drive letters are reused, so two partitions of one disk could each count as a separate backup copy.
- Must: Copies are counted per physical disk, rechecked when drives change, so two partitions of one disk never count as two copies.
- Kind: situation

### SRT-086: A card whose folder could not be read was called "Safe to format".
- Why: A card folder that threw a read error dropped out of the listing, so the card was judged on its other folders.
- Must: If any part of a card cannot be read, it is never called safe to format, and the page names what could not be read.
- Kind: situation

### SRT-087: A card holding a proxy without its clip is not safe to wipe.
- Why: A camera proxy whose original is not on the card may be the only copy of that footage.
- Must: A card with such a proxy is never shown as backed up unless that proxy was copied.
- Kind: situation

### SRT-088: A card counted as backed up while 375 of its files had one copy.
- Why: Of three cards said to have backups, one card's 375 files (1,047 GB) existed on one drive only.
- Must: Before calling a card safe to wipe, the product shows how many separate copies each clip has and names clips with only one.
- Kind: situation

### SRT-090: Unplugging a backup drive removed its copies from the card's count.
- Why: Copies were counted only on drives currently plugged in, so a card looked less backed up than it was.
- Must: Verified copies on an unplugged backup drive still count, shown as on that drive while it is away.
- Kind: situation

## The record of every copy

### SRT-094: Tapes in the standard tape file system list in seconds but share one letter.
- Why: Listing such a tape reads only its index, so it takes seconds, but every tape mounts at the same drive letter.
- Must: A tape is identified by its barcode, never its letter, and a clip only on tape offers a restore request naming the tapes and where they are kept.
- Kind: given

### SRT-091: Every copy of every clip, and where it lives, in one view.
- Why: The owner asked for "an overview of every copy of every file" across the NAS, external drives, laptops, cards and the cloud, for masters, proxies and audio.
- Must: Each clip shows its copy count and every location, master, proxy and audio separately, and any clip view sorts and filters by drive or computer.
- Kind: ruling

### SRT-092: Copy badges are outlined when healthy and filled only for a problem.
- Why: With 36,000 clips, a filled green badge on every healthy one would make the grid a wall of green.
- Must: Copy-count badges are outlined when healthy, filled gold when not backed up, and red when only on a laptop, card or client drive.
- Kind: ruling

### SRT-093: A double-backup percentage, and a tape mark on clips with a tape copy.
- Why: The owner wants "a counter for what percentage of files has double backup and any file which has a tape backup should get a small icon".
- Must: The view shows the percent of master files with a second counting copy, and a clip with a tape copy carries a small non-green mark naming the tapes.
- Kind: ruling

### SRT-095: A known drive or watched folder updates the record by itself when it reappears.
- Why: The owner asked that a drive scanned before be detected and updated whenever plugged in, and watched folders "when they become visible".
- Must: Adding a drive or folder is one action, and each time it appears on any studio computer its changes reach the record unasked.
- Kind: ruling

### SRT-096: A laptop's system drive is never scanned whole.
- Why: A laptop's own drive holds the operating system and personal files; only folders someone chose to watch belong in the record.
- Must: A computer's system drive is never offered as a new drive; only folders explicitly watched on it are scanned or backed up.
- Kind: ruling

### SRT-097: A copy that vanishes is asked about, never written off.
- Why: The owner never deletes footage from home, only moves it onto backup drives, so a missing copy is a question, not a deletion.
- Must: A missing copy raises a per-folder "where did these go?" (moved, deleted on purpose after confirming, or rescan) and stays recorded until answered; cloud and card copies age out quietly.
- Kind: ruling

### SRT-105: A drive sitting in a drawer stays searchable as last seen.
- Why: Search saw only what was currently scanned, so a file living only on an unplugged drive was recorded but could not be found.
- Must: Every file ever listed on a drive stays searchable while it is unplugged, shown with its drive and last-seen date and marked as not on the NAS.
- Kind: ruling

### SRT-108: The cloud backup runs nightly for new files, controlled from the page.
- Why: The owner wanted new footage sent to the cloud every night, while a multi-day first upload was still running.
- Must: Nightly cloud backup sends only new and changed files, has on/off, time and Run now on the page, and never starts beside a run in progress.
- Kind: ruling

### SRT-109: Laptops and drives back themselves up to the NAS, into staging.
- Why: The owner: "automatically back up stuff that's on the laptop or other drive to the correct place on the nas"; a wrong project guess is worse than waiting in staging.
- Must: A per-drive switch, off by default, copies files with no NAS copy into staging by computer and drive, deletes or overwrites nothing, and shows the last run.
- Kind: ruling

### SRT-098: A move the product made itself must not raise "where did these go?".
- Why: Moves on the NAS change paths, so the next scan would otherwise see every moved file as gone.
- Must: Any move the product performs updates the copy record at once, so the next scan raises no question about the moved files.
- Kind: situation

### SRT-099: A file replaced at the same path looked like a loss plus a new file.
- Why: About 1,260 downloads rewritten in place to a new codec changed size and raised 62 false "where did it go?" questions.
- Must: A file replaced at the same path is the same file updated, not a loss, and stays tracked.
- Kind: situation

### SRT-100: A partial scan or listing must never mark files missing.
- Why: A scan of default folders shrank a 25,000-clip index to 191; drives pulled mid-scan, half-mounted or fresh from a disk check, or cut-short cloud listings, show fewer files.
- Must: Files are marked gone only after a complete listing covering their folder; a scan unfinished, under 80% of last time's count, or with unreadable folders only adds.
- Kind: situation

### SRT-101: New footage appears on its own, but never half-copied.
- Why: Clips copied into a project folder did not show until a full rescan; the owner: "keep it up to date without rescanning everything every time".
- Must: New files appear within about half a minute without a full rescan, only once unchanged across two looks, and an unplugged drive or missing root removes nothing.
- Kind: situation

### SRT-102: One odd file name must never make a drive unscannable.
- Why: Real drives hold names with broken characters, very long paths or junk, and refusing a whole batch for one bad name blocks the drive for ever.
- Must: A file the scan cannot record is skipped and counted, and the rest of the drive is still recorded.
- Kind: situation

### SRT-103: Thousands of Chinese NAS file names were recorded as question marks.
- Why: About 14,500 recorded names held "?" in place of non-Latin characters, and the repair stopped part-way with 4,950 still wrong.
- Must: The record stores every file name exactly as it is on disk, and an interrupted repair resumes where it stopped.
- Kind: situation

### SRT-104: A computer cannot pass off a USB stick as the NAS.
- Why: Editors' computers report copies, and a report naming a place by label alone could make any stick pose as the NAS or replace a real copy.
- Must: A computer records copies only on drives it identifies by serial, and a report disagreeing with a live copy is counted as a conflict, never replacing it.
- Kind: situation

### SRT-106: Footage on only one laptop drive was lost track of when the drive moved.
- Why: 277 files (757 GB) listed as laptop-only had changed folders and their drive had moved to another computer; none had a NAS copy.
- Must: Footage held on only one drive is found again after renames, folder moves or the drive moving computers, and its backup state stays true.
- Kind: situation

### SRT-107: The record of where copies live must survive losing the NAS.
- Why: Losing the NAS would lose the only record of which drive holds what, and a plain copy of a live record file can be torn.
- Must: The copy record and sorter state are copied nightly in a consistent, integrity-checked form, seven kept, and carried in the cloud backup.
- Kind: situation

### SRT-110: A laptop away from home must never start an automatic copy to the NAS.
- Why: Over the remote link a laptop can still reach the NAS, but a multi-gigabyte copy crawls; at home the round trip is under 15 ms.
- Must: Automatic backups run only when the computer is on the studio's own network; when it cannot tell, it does not copy and says "away from home".
- Kind: situation

## Sorting into shoots, people and cameras

### SRT-127: Windows silently changes some folder names.
- Why: Windows drops trailing dots and spaces when it creates a folder, rejects device names like CON and LPT1, and matches names regardless of case.
- Must: Planned folder names are cleaned the way Windows will store them, reserved names are refused, and names compare without case.
- Kind: given

### SRT-128: The NAS is case-sensitive, so a differently cased folder became a second folder.
- Why: Windows treats "Ukraine trip" and "Ukraine Trip" as one folder; the NAS treats them as two, splitting footage between them.
- Must: When a destination folder already exists in another letter case, copies and moves use the existing folder's spelling.
- Kind: given

### SRT-112: Clips are filed under the person in date-and-time subfolders.
- Why: The owner wanted backup and sorting joined: every copy recorded, calendar suggestions, choices per clip, and subfolders named by times under each person.
- Must: Clips are filed under the person's folder in subfolders named by date and time range.
- Kind: ruling

### SRT-114: Suggestions are reviewed with their evidence before acceptance.
- Why: The owner accepted all without seeing them, then asked for "which evidence, and also other, secondary evidence - for example if multiple calendar events clash".
- Must: Each suggestion shows its destination, evidence and conflicting alternatives, appears in its destination marked unconfirmed, and accepting can be undone.
- Kind: ruling

### SRT-115: Many clips switch to an alternative suggestion in one step, undoably.
- Why: Bulk accept only warned that clips "could also be" filed elsewhere, so choosing an alternative meant changing each clip by hand.
- Must: For a selection, any suggested alternative applies once to every clip that has it, reports how many were skipped, and one Undo restores previous assignments.
- Kind: ruling

### SRT-116: Every interviewee on the roster appears as a destination, greyed until used.
- Why: The owner: "ALL interviewees in the sheet should be added", greyed and not created on disk until clips arrive.
- Must: Every roster person appears in each episode's destinations, greyed and not created until assigned clips; people in several episodes show greyed in the others.
- Kind: ruling

### SRT-117: A missing view lists events without footage and people lacking a camera or sound.
- Why: The owner wanted events with no footage, interviewees with one camera or no sound file, and interviewees missing per episode, with a warning on such destinations.
- Must: A missing view lists those gaps, events can be dismissed, and each affected destination shows a warning naming what is missing.
- Kind: ruling

### SRT-118: A second camera counts as covered when two cameras' clips land on one person.
- Why: The studio often shoots BRAW as A camera and an FX3 as B filed in an "A cam" folder; shoots holding both cameras and sound were flagged incomplete.
- Must: A missing-camera or missing-sound warning clears whenever a destination holds two cameras' clips or a matching recorder file, whatever the folders are called.
- Kind: ruling

### SRT-120: A clip already inside a project folder counts as assigned.
- Why: Only 6,641 of 13,334 clips in the projects tree counted as assigned; the owner: "if the clip is in a folder in P it should be counted as assigned".
- Must: Any clip already inside a project folder on the NAS counts as assigned and in place, never as work left to do.
- Kind: ruling

### SRT-121: A person's sorting plan survives every rescan and restart.
- Why: The owner: "Do not reset the current manifest from where it is, I have done a lot of work moving things around."
- Must: Rescans, restarts and updates keep every assignment and plan the person has made, saved or not.
- Kind: ruling

### SRT-122: Clips assigned but not yet moved show dashed and dimmed in their folder.
- Why: The owner: they "should show in the UI but with a dashed outline and lowered opacity to show that the move is staged but not yet completed".
- Must: A destination folder lists clips assigned to it but not yet there, drawn with a dashed outline at lower opacity.
- Kind: ruling

### SRT-123: Clips the automatic match cannot place confidently are reviewed and sorted by hand.
- Why: The owner: "we can use the footage sorter UI to sort out unmatched video", and wants to "see matches, approve, and adjust them... show why they are a match".
- Must: Unconfident matches wait for a person; each proposed match shows why, plays the audio, shows transcript and paired clips, and nothing moves until approved or adjusted.
- Kind: ruling

### SRT-124: Each shoot day goes onto one client drive, never split.
- Why: The owner wanted each day's material together on one client drive, no clip on two of them, with copying spread across the drives for speed.
- Must: Each shoot day is assigned to one client drive, and no clip is placed on two client drives.
- Kind: ruling

### SRT-111: The studio calendar already says where footage belongs.
- Why: Event titles like "Reproductive陳昭姿interview" name episode and person, with typos; reading them placed 6,971 clips (17 TB) that had no home.
- Must: Footage is suggested a home from its calendar event title, tolerating common typos, and a name belonging to two episodes is never guessed.
- Kind: situation

### SRT-113: A calendar event naming two interviewees filed both under the first.
- Why: Three shoot days had one event for two interviews; the second person's clips and recorder audio went into the first person's folder.
- Must: When one event names two people, its clips and audio are split between them or the person is asked, never filed under one name.
- Kind: situation

### SRT-119: Two weeks of camera footage were on no drive, shown only by numbering gaps.
- Why: Two cameras' clip numbers jumped across a fortnight; nothing in the gap was on any drive, the NAS or the catalogue.
- Must: Gaps in each camera's clip numbering are flagged with the dates either side, so cards never offloaded are noticed.
- Kind: situation

### SRT-125: Which card goes to which camera folder is studio data.
- Why: The studio renamed a camera folder from the camera's model to its angle letter, and the offload still used the old name.
- Must: Camera-to-folder naming is data an owner can change without changing or reinstalling the program.
- Kind: situation

### SRT-126: Existing shoot folder names must survive a change of software.
- Why: Which of two shoots got a "(2)" folder depended on sort order, and Chinese names sort by radical and stroke in one place, by character code in another.
- Must: A replacement keeps every existing shoot folder name and clip identity exactly, including any "(2)" suffix.
- Kind: situation

### SRT-129: A Windows card path read on the NAS became one bogus file name.
- Why: The NAS does not split at backslashes, so "H:\clip.braw" became a file name, the planned destination left the storage area, and the copy was refused.
- Must: Paths reported by a Windows computer are split by Windows rules wherever handled, and a card copy started on the page begins on that computer.
- Kind: situation

### SRT-130: Clips moved into a folder with an accented name did not show there.
- Why: After a real move, an interviewee's clips were not visible in his destination folder, whose name contains accented letters.
- Must: A move into a folder whose name has accented or non-Latin letters lands there and is shown there.
- Kind: situation

## Moving footage on the NAS

### SRT-131: Sorting never loses an original, and every move is checked first.
- Why: The owner required a test run "to make sure no original footage gets lost or accidentally deleted", then a single clip, then everything.
- Must: Every move is checked just before and after it runs, can run on one clip, and never deletes or overwrites an original.
- Kind: ruling

### SRT-132: A move must be a rename and say "Move"; it never quietly becomes a copy.
- Why: Clips in a transfer folder were offered only "copy" with the pool 91% full, and a failed rename across mounts can be papered over by a slow copy.
- Must: The sorter offers Move as well as Copy, labels each by what will really happen, and a move that cannot be a rename stops, leaving both sides untouched.
- Kind: ruling

### SRT-140: Destination folders can be dragged, nested, renamed and deleted.
- Why: The owner could not drag two animal folders into a new parent folder, nor move a folder from one parent to another.
- Must: In the destination tree a person can drag a folder under any other parent, rename it and delete it.
- Kind: ruling

### SRT-133: A move plan with clashing destinations moves only the clean clips.
- Why: A 5,781-entry plan held 380 duplicate and 16 occupied destinations; 5,095 entries (6.76 TB) moved.
- Must: A move never overwrites or splits a clip: a clip with any conflicting file stays whole where it is and is listed for a person to decide.
- Kind: situation

### SRT-134: An interrupted move was left "moving" for ever.
- Why: A move that failed partway left its plan marked "moving", with no rescan or reconciling.
- Must: After a move fails or the app restarts mid-move, the product rescans and shows which files moved and which did not.
- Kind: situation

### SRT-135: A check after one move reported 2,528 false problems from past moves.
- Why: A folder was moved in Explorer minutes after a run, and the after-move check, judging every past move, reported history as damage.
- Must: A check after a move judges only that move, follows later and hand moves to where files are now, and reports only files truly gone.
- Kind: situation

### SRT-136: A clip moved by hand keeps its assignment; a copy left behind is a duplicate.
- Why: Clips moved in Explorer lost assignments; adopting every hand move then took in 5 real duplicates (one WAV in two folders, one person in two episodes).
- Must: A filed clip found elsewhere is adopted as moved only when no copy remains in its planned folder; otherwise it is a duplicate, left alone and counted.
- Kind: situation

### SRT-137: After a move, moved clips vanished and counts went stale.
- Why: The sorter still showed 10,393 clips in the transfer folder and none in destinations; folders created in Explorer did not appear either.
- Must: Moved clips show at their new location and can be planned again, and counts and the folder tree follow changes on disk.
- Kind: situation

### SRT-138: Planned empty folders were never created.
- Why: The page promised folders would be created by the move, but a plan with folders and nothing to move created nothing.
- Must: Every planned folder is created even when no clip moves into it.
- Kind: situation

### SRT-139: A clip already final in another project could only be copied again.
- Why: A second copy doubled the bytes and let the two drift apart.
- Must: A clip filed in another project can be shared into this one as a link to its folder, only on an explicit click.
- Kind: situation

### SRT-141: A file dragged in from Explorer did not join the plan.
- Why: The owner dragged a recording from his Videos folder onto a destination and it never appeared there.
- Must: A file dragged from Explorer onto a destination joins the plan for that destination and shows there at once.
- Kind: situation

## Placing sound recordings

### SRT-142: Recorder files are often misfiled, unfiled, or second offloads.
- Why: Of 141 staging recordings, 121 were byte-identical second offloads; 21 filed ones sat in the wrong person's folder; "missing" ones lay loose with 2021 dates.
- Must: Before a recording counts as missing, every unassigned recording everywhere is searched by content, and a filed file whose audio disagrees with its folder is flagged.
- Kind: given

### SRT-143: Each sound file gets a suggested interviewee from what is said in it.
- Why: Recorder files are named only by date and counter; the owner wanted the likely interviewee suggested, speed over accuracy.
- Must: Each sound file gets a suggested interviewee from its content and exact duplicates, with a confidence, shows its transcript on click, and can be reassigned.
- Kind: ruling

### SRT-145: Field audio is placed beside its video by time, then waveform, then speech.
- Why: The owner wants every field recording, even ones already filed, matched "by date and time", then "waveform matching", then transcripts of the first ten minutes.
- Must: Every field recording ends up in its shoot's audio folder beside the matching video, duplicates set aside not deleted, trying time, then waveform, then transcript.
- Kind: ruling

### SRT-146: Sound matching considers only the studio's own camera footage.
- Why: The owner: "we are matching to our footage, fx3 a74 or bmcc only. youtube downloads are obviously irrelevant to this process".
- Must: Matching recordings to video considers only the studio's camera clips (FX3, A7 IV, BMCC), never downloaded video.
- Kind: ruling

### SRT-147: Loose field recordings are found by format, length and name.
- Why: The owner: field audio "is .wav, is of relevant length, is not broken, does not have the name of a piece of music"; "all field wavs are 32 bit".
- Must: A search for unplaced field audio on every computer and drive keeps only unbroken 32-bit WAV files of plausible length not named like music.
- Kind: ruling

### SRT-144: Speakers who introduce their organisation, or say their name late, went unidentified.
- Why: An interviewee opening "大家好，我們是婦女新知基金會" was skipped, names came many minutes in, and a recording was credited to someone merely mentioned.
- Must: Attribution uses the whole recording, handles "we are" introductions, never credits a name only mentioned, marks guesses, and reports recordings it cannot attribute.
- Kind: situation

### SRT-148: Loose waveform matching split one take's two channels across two shoots.
- Why: Single-clip waveform matches at low thresholds put the two channels of one recording in different shoots; a peak of 0.75 with a 0.25 margin over the next held.
- Must: A single-clip audio match is accepted only when it clearly beats the next candidate, and both channels of a take stay together.
- Kind: situation

### SRT-149: The same speech in Simplified and Traditional Chinese never matched.
- Why: One speech-to-text wrote Chinese in Simplified, another in Traditional, so identical speech in mixed transcripts never matched.
- Must: Chinese text is compared in one script, so identical speech matches whichever engine wrote either side.
- Kind: situation

### SRT-150: A long transcription run stopped partway through thousands of files.
- Why: A 6,246-file run (about 173 hours) stopped partway, and nothing already transcribed may be lost or done again.
- Must: An interrupted transcription run keeps every finished transcript and resumes unattended, skipping finished files.
- Kind: situation

## Thumbnails and hover filmstrips

### SRT-151: Thumbnails are made once in the background and kept.
- Why: Only 5% of videos had one and a screen of 48 took 5.2 s on demand; the owner: "generate thumbnails once and have them stored".
- Must: After each scan or card read every clip gets a thumbnail in the background, shown instantly once stored, and a card clip's is reused for its NAS copy.
- Kind: ruling

### SRT-156: A hover filmstrip has one frame per 10 seconds, between 12 and 50.
- Why: Hovering streamed the whole proxy (244 MB for 5 minutes), and 12 frames were too coarse for long clips; the owner: "up to a maximum of 50".
- Must: Hover preview shows one frame per 10 s of clip, at least 12 and at most 50, from an image of tens of kilobytes made ahead of time.
- Kind: ruling

### SRT-158: Thumbnails must not pile up on a phone.
- Why: The owner: the page "shouldn't keep thumbnails permanently on a phone"; storage a site keeps lasts until the site deletes it, unlike the browser's ordinary cache.
- Must: Thumbnails and filmstrips on a phone are small (about 2 to 3 KB) and held only in the browser's ordinary evictable cache.
- Kind: ruling

### SRT-152: The thumbnail on screen waited behind hours of background thumbnails.
- Why: Workers took a waiting background job before the one on screen.
- Must: A thumbnail on screen is made before any background thumbnail still waiting.
- Kind: situation

### SRT-153: A clip's thumbnail and assignment must follow the recording, not its path.
- Why: Clips were known by their path, so moving them into projects orphaned 8,835 of 9,926 thumbnails (390 MB) and lost their assignments.
- Must: A clip keeps its thumbnail, filmstrip and assignment through any move, copy or hand rename.
- Kind: situation

### SRT-154: Clips the server cannot reach got blank thumbnails.
- Why: The NAS cannot read a card or local disk in an editor's computer; there a whole card's 47 thumbnails took 1.8 s and 350 KB.
- Must: The computer holding the clips sends their thumbnails, from the camera's own proxies where present, shown within about 5 seconds in grid order; sound-only clips show an audio card.
- Kind: situation

### SRT-155: Hover filmstrips showed only a clip's first seconds.
- Why: The owner saw "only playing the first few frames of the video, not a playback sprite spread across the whole clip".
- Must: Each filmstrip tile comes from a later point than the one before, spread evenly to the end, and strips made wrongly are remade.
- Kind: situation

### SRT-157: Making filmstrips in the background overloaded the NAS.
- Why: Single jobs grew to 31-41 GB on a 62 GB NAS and were killed 35 times in five hours; parallel jobs pushed it to 72-81 C with fans doubled.
- Must: Background picture-making on the NAS stays within a few hundred MB per job at low priority and capped concurrency, and a failed clip is not retried every restart.
- Kind: situation

### SRT-159: Heavy sorter work must never stall the rest of the dashboard.
- Why: 100 cold thumbnails at once stalled every other dashboard request by 1.8 s, and 300 by 7.2 s.
- Must: While the sorter scans or makes hundreds of thumbnails, every other dashboard page still answers within a fraction of a second.
- Kind: situation

## The sorter page

### SRT-160: The sorter works from any signed-in browser and names places, not drive letters.
- Why: The owner: "make it into a website which can be accessed anywhere … queue up file moves and backups from anywhere", "computer agnostic".
- Must: Sorting, moves and backups are queued from any signed-in browser, phone included, under the product's one sign-in, and every place is named by its server location.
- Kind: ruling

### SRT-163: Every source is listed under the computer it lives on, closed by default.
- Why: The owner: "everything should be under its own computer name", cards inside their computer, "by default all dropdowns should be closed".
- Must: Sources group under each computer, NAS first, all closed; a newly inserted card opens its computer, cards present at load do not; there is no "all clips" source.
- Kind: ruling

### SRT-164: Project folders are destinations, never sources, and a computer is never guessed.
- Why: The owner: "projects should not be there, as that is exclusively a destination"; sources were named with no hint of their computer.
- Must: Sources never list project folders; each shows its computer as the server knows it, one name per computer however spelt, or "Unknown computer".
- Kind: ruling

### SRT-165: The source list can be hidden, and the clips fill its space.
- Why: The owner: "you should be able to hide it and open it. If you hide it the clips panel should expand to fill the space."
- Must: Hiding the source list widens the clips to full width, one control brings it back, and the choice is remembered per browser.
- Kind: ruling

### SRT-166: Managing known drives stays off the main sorting screen.
- Why: The owner: "it's a rarely looked at option, so just move it into a settings panel".
- Must: Managing known drives lives in a settings area, not on the main sorting screen.
- Kind: ruling

### SRT-167: A clip and its destination are each one click from the other.
- Why: There was no way to browse by assigned folder; the owner wanted clip to destination, destination to contents, and open-in-source inside the app and in Explorer.
- Must: Selecting a clip opens its destination, and its menu offers open in source (in the app and in Explorer) and show in destinations.
- Kind: ruling

### SRT-168: A clip's menu offers other suggestions and the other camera's footage of that moment.
- Why: Suggestions often caught the A camera but missed the B camera; the owner wanted to jump between camera folders covering the same date and time.
- Must: A clip's menu lists alternative destinations and the folders of other cameras that recorded the same date and time, each openable.
- Kind: ruling

### SRT-169: Selecting a clip shows all its details.
- Why: The owner asked for an info pane showing every piece of metadata about the selected file.
- Must: Selecting any clip shows its size, frame rate, duration, camera and every location it is stored.
- Kind: ruling

### SRT-170: The clip view plays sound, resizes thumbnails, sorts by length and filters by day.
- Why: The owner asked for audio in the preview, larger thumbnails, sorting by clip length and a calendar picker showing all footage from one day.
- Must: The clip view can play sound, change thumbnail size, sort by duration, and filter to every clip from a picked day.
- Kind: ruling

### SRT-161: The footage page took over 20 seconds to open on a remote laptop.
- Why: Every open downloaded all 36,000 clips (43 MB raw, over 4 MB compressed), 98% of them already filed into projects.
- Must: The first view asks for a source and loads under 0.2 MB within a few seconds; a source's and a destination's clips load only when opened.
- Kind: situation

### SRT-162: The footage page said "no clips match" while still loading.
- Why: The empty message appeared about 60 ms after page start and stayed until data arrived.
- Must: Until clips arrive the page says it is loading, a failed load offers Try again, and "no clips match" appears only once data is there.
- Kind: situation

### SRT-171: The sorter page showed a "too many open files" error.
- Why: Opening the sorter returned an error that the process had too many files open on Windows instead of the page.
- Must: The sorter keeps its open files bounded during long scans, and the page always loads.
- Kind: situation

### SRT-172: The calendar connect button flashed up and disappeared.
- Why: The option to connect the studio's calendar showed for a second and vanished before it could be clicked.
- Must: The calendar connect control stays visible until the calendar is connected, and a failed connection says why.
- Kind: situation

## Archive search

### SRT-173: The archive sorts and searches every place footage lives, four ways.
- Why: The owner: sorting "by project / date / name / etc", searching "lots of different drives", tapes tracked, "fuzzy search, precise search, cross-language search" and an assistant search.
- Must: One search covers the NAS, every known drive, the cloud and tapes, sorts by project, date, name, camera, size and copies, with exact, loose, cross-language and assistant modes.
- Kind: ruling

### SRT-174: An English search must find Chinese names, and the reverse.
- Why: Folders, people and events mix Traditional Chinese and English: "typhoon" should find 颱風災後, 台灣 match 台湾, "zhang" find 張; two-character words like 颱風 are common.
- Must: Name searches match across Traditional and Simplified, English, Chinese and pinyin, any two-character query finds every name containing it, and corrected translations are kept.
- Kind: ruling

### SRT-175: Searching a person's name shows their event and its clips.
- Why: The owner wanted to search a name or folder and get the matching event with its date and every clip assigned to it.
- Must: A search by event or folder name, in Chinese or English, returns the event with its date and its assigned clips.
- Kind: ruling

### SRT-176: An assistant search shows the searches it ran and sends only names out.
- Why: A plain-language archive question is answered by searches over the index, and no media or transcripts may leave the NAS.
- Must: An assistant answer lists every search it ran as an editable query with a reason per result, and only file metadata ever leaves the NAS.
- Kind: ruling

## Downloading originals and sharing folders

### SRT-178: Chrome will not let a page save into Documents, Desktop, Downloads or a drive root.
- Why: Chrome's folder picker refuses those folders themselves ("contains system files"), while a folder inside any of them is allowed.
- Must: Downloading to a chosen folder explains which folders the browser refuses and starts the picker where a subfolder can be chosen.
- Kind: given

### SRT-179: A browser saving into a picked folder writes each file only when it closes.
- Why: If the tab crashes or power fails mid-file, that file restarts from its last closed state, usually zero; network drops, Pause and Cancel lose nothing.
- Must: A large download survives dropped connections without losing bytes, and the person is told a crashed tab restarts the file in progress.
- Kind: given

### SRT-177: Anyone signed in can download chosen originals into a folder they pick.
- Why: The owner: "it should just ask you for a download directory on your local computer", no project needed; picking a folder works only in Chrome or Edge on a computer.
- Must: Selected clips download into a chosen local folder, folders kept, with progress, Pause, Cancel, skipping files already there, proxies only if ticked; other browsers get per-file links.
- Kind: ruling

### SRT-182: Any footage folder can be shared by an expiring link.
- Why: The owner: "you should be able to generate a unique link for any folder to send to people".
- Must: An admin links one folder, lasting 14 days by default and 365 at most, with an off switch; a whole root is refused; holders download files or a zip.
- Kind: ruling

### SRT-180: A resumed download continues only its own unfinished files.
- Why: Re-running into the same folder must fetch only what is missing, and a smaller file of the same name may be the editor's own.
- Must: Full-size files are skipped, only files the download itself marked in progress are continued, and a same-name file without that mark is left alone and reported.
- Kind: situation

### SRT-181: A download never delivers the wrong file after a rescan.
- Why: A file asked for by its position in a clip's list can change after a rescan, and a server answering a resume with the whole file corrupts it.
- Must: Every requested file is checked by name before it is sent, a mismatch asks to start again, and a resume answered with the whole file restarts that file.
- Kind: situation

### SRT-183: A shared folder link must never reach anything outside its folder.
- Why: A shared link opens with no sign-in, so paths, symbolic links and junk files are its attack surface.
- Must: Unknown, revoked and expired links answer not found, no path climbs out, and links, hidden files, system junk and half-written files are never listed or served.
- Kind: situation

## Filed here, belonging elsewhere

See also, filed under another capability:

- SYN-124 (Sync): Footage dated in the future by a wrong camera clock never uploads.
