# The Footage Sorter and camera cards

## Recognising cards and drives

### SRT-001: Cards in CFexpress Type B readers and camera SSDs look like fixed disks.
- What was going on: Windows presents a card in a CFexpress Type B reader, a built-in reader, or a Blackmagic camera SSD as a fixed disk, so a removable-only check misses it.
- What the product must do: A fixed disk with a camera's folder layout is detected, copied and judged as a card; the system disk never is, and a card is never offered as a destination.
- Kind: 1a
- From: C04-041, P17-007, H08-048, L11-069, P18-001, M04-075

### SRT-002: A card that mounts slowly looked empty at first and was ignored for minutes.
- What was going on: Some cards appear to Windows seconds before their files can be read, so the first look finds nothing.
- What the product must do: A newly mounted drive that looks empty is checked again over the next several scans and appears as a card once its files show.
- Kind: 1a
- From: P18-002

### SRT-003: A Mac never listed its own startup disk.
- What was going on: On macOS the startup disk appears in the volumes folder as a link to the root; its data volume's ID survives macOS updates.
- What the product must do: A Mac's startup disk is listed exactly once for local backups, never as a card, and is identified by an ID that survives macOS updates.
- Kind: 1a
- From: C04-040, P17-025

### SRT-004: Drive letters change between plug-ins and computers; volume serials do not.
- What was going on: One drive gets different letters on different computers and plug-ins, and Windows hands an unplugged drive's letter to the next card reader.
- What the product must do: Every drive is known by its volume serial, never its letter, and a card is detected whatever letter it gets, including one another drive used earlier.
- Kind: 1a
- From: D07-064, C07-008

### SRT-005: A field drive returned under another letter; a laptop's NAS letter pointed at itself.
- What was going on: Field drives came back under other letters between copy rounds, and one laptop's letter for the NAS pointed at its own disk.
- What the product must do: A copy refuses a destination on its own source drive, and refuses a destination different from earlier rounds unless the person confirms it.
- Kind: 3
- From: M04-086

### SRT-006: A camera card formatted in camera must still be recognised.
- What was going on: An in-camera format erases every file, including any mark written on the card, and on some bodies also changes the card's volume serial.
- What the product must do: Each card keeps a name and number recognised after in-camera formatting, guessed from its kind, capacity and days of use, with the owner confirming a guess.
- Kind: 1a
- State: outcome not found
- From: P14-001, P13-046

### SRT-007: One Windows drive that never answered made every camera card vanish.
- What was going on: Windows' request for one drive's volume information can hang without end, freezing every card and drive report from that computer with nothing logged.
- What the product must do: A drive that does not answer within 5 seconds is skipped and logged, and every other card and drive on that computer keeps being reported.
- Kind: 1a
- From: C04-044, P18-028

### SRT-008: Windows Task Manager can switch off a startup entry, and it stays off.
- What was going on: An entry disabled once in Task Manager stays disabled across reinstalls; the owner disabled one with no recognisable name, so inserting a card opened nothing.
- What the product must do: Whatever notices cards starts at sign-in under the product's name and icon, and installing it clears a stale disabled flag.
- Kind: 1a
- From: C06-107, P06-061

### SRT-009: A card swapped in right after another was pulled raised no prompt.
- What was going on: The owner: "IT'S NOT POPPING UP WHEN I PULL A CARD OUT AND PUT ANOTHER ONE IN"; another time card detection had not started and nothing said so.
- What the product must do: Every card inserted, including straight after another is pulled, appears within seconds without a click, and the sorter says so when card detection is not running.
- Kind: 3
- State: outcome not found
- From: P01-002, P10-070

### SRT-010: Each inserted card opened another browser tab.
- What was going on: The owner: "I never want it to do that"; several cards opened five tabs, and cards inserted while the sorter was open did not join its list.
- What the product must do: A new card shows in an already open sorter tab, a tab opens only if none is open, and every card inserted while it runs joins its card list.
- Kind: 2
- State: outcome not found
- From: P07-027, C06-106, P12-057

### SRT-011: Backup drives chosen in the field were offered as cards to back up.
- What was going on: A field SSD and hard drive are removable just like cards.
- What the product must do: Drives chosen as copy destinations are recognised by identity and never offered as cards to back up.
- Kind: 3
- From: C06-110

### SRT-012: A camera card closed in the source list could not be brought back.
- What was going on: Closing a card hid it until it was unplugged and reinserted.
- What the product must do: A closed card still in its reader stays listed under its computer as closed and is shown again with one click.
- Kind: 3
- From: P18-009, L11-072

### SRT-013: Camera cards disappeared from the page whenever the server restarted.
- What was going on: Cards were known only to the running server, so each restart dropped them until the computer next reported.
- What the product must do: A card still in its reader stays listed across a server restart.
- Kind: 3
- State: still open
- From: P18-029

### SRT-014: "Which drive is which" question windows stacked up without end.
- What was going on: On Windows a question window leaves the app's timers running, so a drive check every 3 s asked the same question again on each tick.
- What the product must do: At most one question window is shown at a time, and nothing asks again while one is open.
- Kind: 3
- State: fixed, never shipped
- From: C07-010

### SRT-015: A broken field settings file quietly made the laptop behave as if at home.
- What was going on: An unreadable field settings file was ignored, and the sorter silently fell back to home behaviour.
- What the product must do: Settings that cannot be read are reported loudly where the person looks, never silently ignored.
- Kind: 3
- From: C06-112

## What cameras and recorders write

### SRT-016: Sony cards carry per-clip thumbnails and index files that are not clips.
- What was going on: A Sony card holds a thumbnail per clip (THMBNL/<clip>T01.JPG) and card index files (the AVF INFO folder, MEDIAPRO.XML, CUEUP.XML, STATUS.BIN).
- What the product must do: The thumbnail attaches to its clip, index files are never listed as clips, and both are still copied with the card.
- Kind: 1a
- From: C07-024

### SRT-017: A Sony FX3 keeps each clip's proxy in a separate SUB folder.
- What was going on: The FX3 writes each proxy as <clip>S03.MP4 in PRIVATE/M4ROOT/SUB beside the CLIP folder, so a card of 88 clips listed as 172.
- What the product must do: Each SUB proxy joins its master as that clip's proxy; a proxy whose master is not on the card stays listed on its own.
- Kind: 1a
- From: C07-025, P18-035

### SRT-018: A Sony proxy folder's own XML file was read as the clip's metadata.
- What was going on: When a proxy folder holds an XML file, taking the first XML found read the proxy's, losing the clip's unique id and camera model.
- What the product must do: A clip's identity and camera model come from the metadata file beside its master, never from one in its proxy folder.
- Kind: 3
- State: fixed, never shipped
- From: D07-053, P17-024

### SRT-019: The studio's own camera clips can be told apart by their files.
- What was going on: A Sony clip has a companion XML file beside it, and a Blackmagic clip is .braw or follows the camera's reel-and-clip naming.
- What the product must do: Own-camera clips are identified by these marks, and downloaded video is never treated as the studio's footage.
- Kind: 1a
- From: M04-083

### SRT-020: Cards used on a Mac are full of hidden "._" files.
- What was going on: Two Blackmagic CF cards held 160 and 255 macOS "._" files beside 239 and 382 real media files.
- What the product must do: Card checks and backups ignore "._" files and never count them as missing footage.
- Kind: 1a
- From: P14-032

### SRT-021: Card housekeeping files share names and sizes across different cards.
- What was going on: SONYCARD.IND, DATABASE.BIN, MEDIAPRO.XML and "._" files repeat across cards, giving false matches, while folders reorganised on the way to the NAS gave false misses.
- What the product must do: A card's backup check matches every real media file wherever it sits in the archive and ignores housekeeping files.
- Kind: 1a
- From: M05-035

### SRT-022: Opening a folder in Explorer adds a file that breaks size checks.
- What was going on: Visiting an image-sequence folder in Explorer leaves a Thumbs.db there, which made later move checks fail on a size mismatch.
- What the product must do: Size and completeness checks ignore files Windows adds by itself, while those files still travel with their folder.
- Kind: 1a
- From: C06-097

### SRT-023: Reused Blackmagic cards carry empty metadata stubs named like real files.
- What was going on: A card can hold 0 or 24-byte metadata files while the archive already holds the real multi-megabyte file of the same name.
- What the product must do: An offload never replaces an archived file with a smaller file of the same name.
- Kind: 1a
- From: M05-036

### SRT-024: Camera side files cluttered the clip view and got separated from their clips.
- What was going on: Side files showed as entries beside videos, 35 clips' side files were moved into a proxy folder, and clips gone from disk vanished from the move plan unannounced.
- What the product must do: A camera's side files travel with their clip on every copy and move, are never shown as clips, and an assigned clip missing from a scan is listed.
- Kind: 3
- From: P17-008, C06-098

### SRT-025: Resolve attaches proxies found in a Proxy folder beside their originals.
- What was going on: The owner wanted card proxies "inside a 'proxy' subfolder within the main date folder so that blackmagic can pick them up".
- What the product must do: Proxies copied off a card land in a Proxy subfolder of the dated folder holding their originals, with matching base names.
- Kind: 1a
- From: P01-001

### SRT-026: Camera RAW video has no picture to show until its proxy exists.
- What was going on: Common open decoders cannot read Blackmagic RAW or RED RAW, so such a clip gets a thumbnail or preview only from its proxy.
- What the product must do: A RAW clip previews from its proxy, says plainly when it has none yet, and picks up the picture soon after a proxy appears.
- Kind: 1a
- State: fixed, never shipped
- From: M04-108

### SRT-027: Sony RAW stills carry a ready JPEG preview.
- What was going on: 4,681 .ARW stills had no thumbnail although each holds an embedded JPEG preview readable from a few KB of tags.
- What the product must do: Every camera RAW still shows a thumbnail taken from its embedded preview.
- Kind: 1a
- State: outcome not found
- From: D07-081

### SRT-028: Some FX3 clips have no sound track and kept failing as errors.
- What was going on: Pulling sound from these clips failed before upload, and each counted as an error.
- What the product must do: A soundless clip is recognised as such, reported once as unmatchable by speech, and never retried as a failure.
- Kind: 3
- State: outcome not found
- From: P19-031

## Damaged and unfinished recordings

### SRT-029: A camera stopping mid-clip on exFAT leaves a full-size file of zeros.
- What was going on: exFAT keeps a valid-data length apart from file size; if never written, the clip reads as zeros and every copy verifies. Two 48 GB FX3 interview clips were lost.
- What the product must do: Every clip is checked for real content before its card counts as backed up, and a verified copy is never taken as proof a clip plays.
- Kind: 1a
- From: M05-043, P12-046

### SRT-030: Interrupted Sony and Blackmagic takes can be recovered only from a raw card image.
- What was going on: Sony leaves an unfinished-recording file; a BRAW take cut short has no index at its end and no in-camera recovery file.
- What the product must do: Such clips are flagged at offload, and the person is told a raw card image taken before formatting is the only recovery.
- Kind: 1a
- From: P12-047

### SRT-031: Damaged clips must be caught at offload, before the card is reused.
- What was going on: Warning signs: an empty XML metadata file, a missing camera proxy, an all-zero start or tail, no index at the end, Sony unfinished recordings, BRAW without its index.
- What the product must do: Every card and copy is checked for these signs; a damaged copy is marked, never counts as a backup, and the editor is told before wiping.
- Kind: 3
- From: M05-044

## Clocks and file dates

### SRT-032: A sound recorder with an unset clock writes wrong dates but keeps steady time.
- What was going on: Fifteen of forty recorder files said January 2021 while the cameras were right; one offset (+12:33) lined every file up with the camera takes.
- What the product must do: Recorder audio is matched to interviews by its content and the cameras' times, never by the recorder's own timestamp.
- Kind: 1a
- From: P11-010, D01-005

### SRT-033: Camera and recorder clocks are often whole hours off, and change mid-trip.
- What was going on: A cinema camera ran five hours off local time, a recorder four hours behind, wireless mic recorders reset to 2000 with one shared offset; clocks were changed mid-trip.
- What the product must do: Time matching tries whole-hour offsets and a fitted offset for reset clocks, never assumes one offset holds for a trip, and names shoot folders in local time.
- Kind: 1a
- From: P18-042, M04-080

### SRT-034: File dates on camera and recorder media are often not the recording time.
- What was going on: BRAW files carried the day the card was copied; recorder files copied without timestamps carried the copy time, or the recording's end, 47 minutes late.
- What the product must do: Every copy keeps the original file times, and placement treats file dates as a hint that sound matching may overrule.
- Kind: 1a
- From: D02-005

### SRT-035: A night shoot crosses midnight, so its clips carry two dates.
- What was going on: The owner: "The party went into the next day", and clips from after midnight were left out of the shoot.
- What the product must do: Clips recorded after midnight stay with the night's shoot, not filed as a separate day.
- Kind: 1a
- From: P14-041

### SRT-036: A Sony clip carries a unique id; a recorder file's start must be worked out.
- What was going on: Sony clips carry a unique id in their metadata file; a recorder WAV's start is its modified time minus its length.
- What the product must do: A clip is identified by its camera id where present, else by name, size and day, with recorder files also matched by modified time.
- Kind: 1a
- From: C06-103

## Telling recordings apart

### SRT-037: A file name does not identify a recording.
- What was going on: Same names held different clips (11.8 GB against 69.8 GB) or card files every card carries; reset recorders reused names like 010121 006; one clip's proxies differed by 12 bytes.
- What the product must do: Recordings are told apart by content and size, never by name alone, and same-name different files are kept apart, never one replacing the other.
- Kind: 1a
- From: D07-112, D02-007

### SRT-038: Two files of the same size were treated as the same file.
- What was going on: A same-size file at the target was skipped as identical, and one version compared nothing for files over 64 MiB.
- What the product must do: Two files count as identical only when their full content matches, whatever their size; a same-size different file is never skipped or replaced.
- Kind: 3
- From: C07-017, H08-069

### SRT-039: Sony dual-slot recording writes two differing files that hold the same footage.
- What was going on: Copies from slot A and slot B differ by 128 KiB, only in a padding block and the real-time metadata track; video and audio are bit-identical.
- What the product must do: Such copies are recognised as one recording from two slots and treated as duplicates, never as conflicting takes.
- Kind: 1a
- From: D07-110, P07-028, M04-078

### SRT-040: A second card that stopped early holds a strict prefix of the recording.
- What was going on: One slot's copy ran 10:44 of a 63:42 recording; its packets were an exact prefix of the full one on the NAS.
- What the product must do: A shorter same-name clip whose content is a prefix of a longer one is shown as a partial second-card copy, and the complete one is kept.
- Kind: 1a
- From: D07-111

### SRT-041: Two recorders started together can write identical-looking files.
- What was going on: Synced recorders that start and stop together can match on name, size and time, so one card's file could mark another card's as backed up.
- What the product must do: A copy proves a card file safe only when it is tied to that card; two cards' look-alike files never vouch for each other.
- Kind: 3
- State: still open
- From: P17-021

### SRT-042: A re-inserted card showed every clip twice, each its own duplicate.
- What was going on: The card was listed again beside its earlier listing, so its clips were flagged duplicates and looked not backed up.
- What the product must do: A card inserted again replaces its earlier listing and keeps its assignments, and every clip appears once in any view.
- Kind: 3
- From: P07-026, C06-105, P05-059

### SRT-043: Redundant copies are quarantined, never deleted.
- What was going on: The owner: "quarantine, don't delete"; 1,479 verified-redundant files (1,036 GB) were set aside for him to delete by hand.
- What the product must do: Clearing duplicates moves only content-verified redundant copies into a quarantine on the same volume mirroring their paths; nothing is deleted and empty folders are only reported.
- Kind: 2
- From: D07-114, P07-029

### SRT-044: Duplicates are badged, and the copy already sorted into a project wins.
- What was going on: The owner: keep the largest or newest, either if identical, mark duplicates red with "S" on the smaller, and keep a sorted copy over an unsorted one.
- What the product must do: Duplicates carry a visible badge marking the smaller copy, and the plan keeps the sorted copy, else the larger or newer, never moving both.
- Kind: 2
- From: P05-056

## Copying a card

### SRT-045: A card copy never overwrites, except to finish its own partial copy.
- What was going on: A destination checked up front can gain a file before the copy lands, and a half-copied clip skipped as "same size" was never resumed.
- What the product must do: An existing file is skipped only when proven the same recording, a shorter copy of it is resumed, any other file is kept and reported, and nothing is overwritten.
- Kind: 3
- From: C04-036, P17-015, C06-104

### SRT-046: A different card swapped into the reader mid-copy got a false "copied".
- What was going on: Swapping cards mid-copy showed "copied", and an unchecked run marked the crew's card backed up in the card tracker.
- What the product must do: A copy refuses when the card in the reader is not the planned one, and "copied" or "backed up" appears only once every clip on it has a checked copy.
- Kind: 3
- From: D07-050, C07-019

### SRT-047: A card copies only what has no verified copy yet.
- What was going on: Clips identical to backups were set to be copied over them; the owner: identical clips "should not be backed up again", and a card copies what no field drive holds.
- What the product must do: From a card, every clip without a verified copy on a field drive or at home is copied, and "is it backed up" is answered from recorded verified copies.
- Kind: 2
- From: M04-093, P05-057

### SRT-048: In the field, a card copies to every ticked destination at once, offline.
- What was going on: On location a laptop copies a card to field drives, a laptop folder, and the NAS only if reachable.
- What the product must do: One card copies to every ticked destination in parallel, shows "already on X" and "safe to format" offline, and the record catches up when next online.
- Kind: 2
- From: M04-068, P17-016, D07-071

### SRT-049: Copies made to the field SSD alone were never carried to the second drive.
- What was going on: On a trip only the SSD was plugged in; copies owed to the hard drive were forgotten, and the nightly copy gave up when it was absent.
- What the product must do: Every copy owed to a second drive is remembered across restarts and starts by itself, or asks, as soon as that drive appears.
- Kind: 3
- State: fixed, never shipped
- From: C07-007

### SRT-050: Camera proxies are copied off a card only when asked.
- What was going on: The owner: "I don't want bmcc or fx3 proxies backed up automatically. It should ask me when I click copy... By default it is unticked."
- What the product must do: The copy offers "Back up proxies too", unticked by default, and proxies and their descriptive files are copied only when it is ticked at Copy.
- Kind: 2
- From: P18-036, C07-034

### SRT-051: A resumed copy saw a clip's master and skipped its missing proxy.
- What was going on: Masters copy before proxies, so every stopped run ended before the proxies, and resumes left 269 proxies uncopied.
- What the product must do: A clip counts as copied only when every file chosen for it (master, and proxy and metadata if chosen) is present at full size; missing ones are copied.
- Kind: 3
- State: fixed, never shipped
- From: C07-006

### SRT-052: A card's still photos must be backed up with its video.
- What was going on: Two drone cards held 446 clips and 14 raw photos, and the owner had to ask whether the stills were copied.
- What the product must do: A card backup copies and verifies every clip and still, and only then says the card may be removed or wiped.
- Kind: 3
- From: P15-002

### SRT-053: A card backup starts at once, even while the computer is in use.
- What was going on: Someone is standing at the reader, so a card copy must not wait for the computer to go idle as background work does.
- What the product must do: A card or drive copy asked for from any browser starts right away on the computer holding the card, whether or not someone is using it.
- Kind: 2
- From: D07-049

### SRT-054: Card backup to the NAS must be as fast as a dedicated copier.
- What was going on: A simple one-file, read-then-write copy lost overlapped reads, resume and verification; the owner: otherwise "the backup will be extremely slow".
- What the product must do: Card backup overlaps reading and writing, reaches at least a dedicated copier's speed on the same card and link, and resumes without starting over.
- Kind: 2
- From: P17-014, M04-067

### SRT-055: A computer with no NAS destination silently offered nowhere to copy.
- What was going on: An editor's computer had no NAS location set, so neither card copy nor the field page offered the NAS, and nothing said why.
- What the product must do: When a computer cannot name the NAS as a destination, the card copy says so and how to fix it.
- Kind: 3
- From: P17-027

### SRT-056: An empty 2 TB SSD showed 0 GB free for a trip's first copy.
- What was going on: The target folder did not exist yet, so its free space read as zero.
- What the product must do: Free space for a folder not yet created is the free space of the drive it will be created on.
- Kind: 3
- State: fixed, never shipped
- From: C07-009

### SRT-057: Clicking copy in the card sorter gave an unexplained error.
- What was going on: Copying a card's clips to their destinations failed with an error whose cause was never recorded.
- What the product must do: A failed copy names the clip, the destination and the reason in plain words, and says what was partly copied.
- Kind: 3
- State: outcome not found
- From: P06-064

### SRT-058: Before copying, every clip on a card is accounted for.
- What was going on: The owner asked for a warning when clips neither backed up nor assigned remain at copy time.
- What the product must do: Before copying, any clip neither backed up nor assigned raises a warning, and the summary shows backed-up and not-backed-up counts.
- Kind: 2
- State: outcome not found
- From: P06-063

### SRT-059: A finished card copy said nothing.
- What was going on: The owner: "after the fast verification finishes you should get a notification message".
- What the product must do: When a card copy and its check finish, a notice names the card, counts copied, already there and checked, and points to any failures.
- Kind: 2
- From: C04-047, P18-039

### SRT-060: Copy progress and speed show live in the browser.
- What was going on: The owner: "you should also be able to see backup progress and speed in the browser", for card copies, drive copies, scans and the cloud upload.
- What the product must do: Each running backup shows percent, speed, time left, current file and whether copying or checking, refreshed every few seconds while visible, never in a hidden tab.
- Kind: 2
- From: D07-072, P17-019

### SRT-061: A card can be used on several days before it is backed up.
- What was going on: A card shot on one day may be used again days later without backup and reset, and both uses must be recorded.
- What the product must do: Logging a card's use on a new day always works and keeps earlier uses, and the card list includes every card the studio owns.
- Kind: 2
- State: outcome not found
- From: P12-069

### SRT-062: The crew's card tracker is bilingual and strict about "backed up".
- What was going on: The crew's card tracker shows English and Traditional Chinese together, and a finished copy flips a card to backed up.
- What the product must do: Crew-facing card pages show English and Traditional Chinese, and a card is marked backed up only when every clip on it has a copy.
- Kind: 2
- From: M04-126

### SRT-063: The card recorder page installs as an app on phones.
- What was going on: The owner: "make the card recorder also installable on ios and android".
- What the product must do: The card recorder installs to the home screen on iOS and Android and opens as an app.
- Kind: 2
- State: outcome not found
- From: P13-047

## Checking a copy

### SRT-064: Footage copies are checked quickly by default, never read back in full.
- What was going on: The owner: "headers and byte size. Don't run the full verification", later adding the end; this misses damage in the middle of a clip.
- What the product must do: Every copy is checked by size, identical first and last 1 MiB and the movie index; a full read-back runs only when asked, and the check says it is quick.
- Kind: 2
- From: P18-038, C04-046, M04-094, P14-028, D07-051

### SRT-065: Reading a copy straight back checks the computer's memory, not the drive.
- What was going on: The operating system serves a just-written file from its memory cache, so a read-back proves nothing about what reached the disk.
- What the product must do: A copy is called verified only after content read from the drive itself, bypassing the cache, matches the source.
- Kind: 1a
- State: fixed, never shipped
- From: H08-049, L11-070

### SRT-066: A copy killed mid-file can leave a full-size file that passes a size check.
- What was going on: Copiers pre-size each file and stamp the source's modified time only on completion; a 217 GB clip changed free space not at all for 20 minutes.
- What the product must do: A copy is done only when size and modified time (within 3 seconds) match or its content is checked, and progress is measured by bytes written, not free space.
- Kind: 3
- From: M04-087, M05-039

### SRT-067: A stopped or resumed card copy left unchecked copies counted as safe.
- What was going on: Runs cancelled before their final check recorded what they had copied, and the next run skipped those by name and size, so 29 clips were never checked.
- What the product must do: A copy counts only after its content is checked against the card, and a resumed run checks every earlier unchecked copy it skips.
- Kind: 3
- State: fixed, never shipped
- From: C07-004

### SRT-068: A drive that hung mid-check got 454 good copies marked bad.
- What was going on: The SSD hung during the check after copying, every later read failed, and each file was set aside as a bad copy.
- What the product must do: A read error during checking stops the check and says so; only a proven size or content mismatch marks a copy bad.
- Kind: 3
- State: fixed, never shipped
- From: C07-003

### SRT-069: Two backup drives filed the same footage differently and kept partial copies.
- What was going on: One drive held unfinished partial copies, missed 500 GB, and filed the same card under folders dated a day apart from the other.
- What the product must do: Backups are compared by recording identity, not folder, and an unfinished partial copy never counts as a backup.
- Kind: 3
- From: P14-031

## Drives, speed and interruptions

### SRT-070: Copying to the NAS one request at a time runs at half speed.
- What was going on: Over a 10 gigabit link, 1 MB writes with one in flight reached about 390 MB/s; four in flight held about 785 MB/s across 160 GB.
- What the product must do: Bulk copies to or from the NAS keep several requests in flight and sustain at least 80% of a buffered Windows file copy's speed.
- Kind: 1a
- From: M06-005

### SRT-071: Several copies off one card at once are slower than one.
- What was going on: A card or spinning disk reads sequentially: three jobs gave 500 MB/s against 634 alone, a single-disk dock ran 26% slower; yet copies from different cards ran one by one.
- What the product must do: Copies from different cards to different destinations run at once, one job per source device, parallel only across separate USB controllers, small proxy folders last.
- Kind: 1a
- From: M05-040, P12-058

### SRT-072: Portable hard drives slow to 55-80 MB/s under long writes.
- What was going on: Shingled portable drives slow to 55-80 MB/s each in long writes, so writing three at once was fastest, while three readers on one source thrashed it to 77 MB/s.
- What the product must do: Long copies are spread across destination drives in parallel, and concurrent reads from any one source disk are limited.
- Kind: 1a
- From: M04-091

### SRT-073: The field SSD hung after about 300 GB of non-stop writing.
- What was going on: A portable SSD used on location hung three times, each after roughly 300 GB or 20-25 minutes of continuous writing.
- What the product must do: Long field copies pause to let the drive rest (for example 10 minutes after every 150 GB), show that it is resting, and stay cancellable.
- Kind: 1a
- State: fixed, never shipped
- From: C07-001

### SRT-074: Big copies to a slow USB disk froze the whole laptop.
- What was going on: Windows built up gigabytes of unwritten cache for a slow USB hard disk until the machine hung, even for reads from other disks.
- What the product must do: Large copies to slow external disks never let the system's write cache pile up, so the computer stays responsive.
- Kind: 1a
- From: M04-089

### SRT-075: A power cut leaves an external drive dirty and its last writes lost.
- What was going on: An exFAT drive on its own mains supply lost power mid-write; it came back dirty and the last writes in its 256 MB cache were gone.
- What the product must do: After a destination loses power, the drive is checked first, and each partial file resumes well before its recorded end.
- Kind: 1a
- From: M04-088

### SRT-076: A destination drive hung or dropped off mid-copy.
- What was going on: External disks vanished mid-copy several times from heat, supply or USB bridge, some staying gone until replugged, while the copy sat without progress.
- What the product must do: A copy with no progress for a set time stops cleanly, tells the person to replug if the drive stays gone, and later copies only what is missing.
- Kind: 3
- From: C07-002, M04-090

### SRT-077: A long copy to the NAS ran unsteadily, then stopped moving unnoticed.
- What was going on: The owner: a trip's copy "has stopped moving", ran "much slower than this link should allow" on 10 Gb, and a card copy's speed was "so unstable".
- What the product must do: A long copy runs steadily near the link's capacity, shows live speed, says when it stops moving, and shows where any slowdown comes from.
- Kind: 3
- State: outcome not found
- From: P14-029, P18-025

### SRT-078: A copy between folders on the NAS itself is instant.
- What was going on: Copying whole interviews between project folders on the NAS took no time and no space; the same copy from a workstation over the share ran at 82 MB/s.
- What the product must do: Copies between folders on the same NAS are done on the NAS, never pulled through an editor's computer.
- Kind: 1a
- From: D02-030

### SRT-079: A move within one NAS volume is instant and keeps the creation time.
- What was going on: 512 MB moved in 15 ms with the creation time kept; a 328 GB re-file of 267 files took 3 seconds.
- What the product must do: Moves between staging and project folders on one NAS volume are renames, finishing in seconds whatever the size.
- Kind: 1a
- From: D07-043

### SRT-080: Listing the footage tree over the network costs about 13 ms per file.
- What was going on: From an editor's PC a rescan took 57 s at 13.4 ms per file looked up (75k lookups); on the NAS itself 77,353 files took 22 s.
- What the product must do: Whole-archive scans run on the NAS, and a rescan from a PC reuses what it read for files whose size and time are unchanged.
- Kind: 1a
- From: D07-082

### SRT-081: Watching folder times on the NAS is cheap but misses a file replaced in place.
- What was going on: 2,048 NAS folders' modified times read in 0.22 s warm, 2.7 s after a restart; adding a file changes its folder's time, rewriting one in place does not.
- What the product must do: A change check based on folder times is backed by a periodic full scan that catches files replaced under the same name.
- Kind: 1a
- From: P18-019

## Backed up and safe to format

### SRT-082: "Backed up" means on the NAS at home, or two copies on owned drives.
- What was going on: The owner: "what is 'backed up' will remain the same - if it's on the server at home"; client drives and cards never count; laptop copies are flagged.
- What the product must do: A clip shows backed up only under that rule, with a daily reminder about anything not at home and one every few days about laptop-only footage.
- Kind: 2
- From: D07-036, M04-070

### SRT-083: Card clips already filed on the NAS read "not backed up" and "nowhere yet".
- What was going on: Sorting flattens a card's folders into project folders, and footage reached the NAS other ways; 125 clips with filed copies counted as not backed up.
- What the product must do: A card clip counts as on the NAS, showing that folder, when a copy matching name, size and time exists anywhere there, unless tagged with another card's identity.
- Kind: 3
- From: C07-031, P18-030, M04-072, C04-039, P17-020, P10-069

### SRT-084: A card is safe to format only when every file has its required verified copies.
- What was going on: An unreadable folder, a failed check, a copy from another card, or an unlisted type such as Nikon N-RAW could still let a card read "safe to format".
- What the product must do: A card is safe only when every file, except known camera housekeeping, has its required verified copies on distinct physical disks, at home or on two field drives.
- Kind: 3
- From: C04-038, C06-109, H08-047, L11-068

### SRT-085: Two copies on one physical disk counted as two backups.
- What was going on: Drive letters are reused, so two partitions of one disk could each count as a separate backup copy.
- What the product must do: Copies are counted per physical disk, rechecked when drives change, so two partitions of one disk never count as two copies.
- Kind: 3
- State: fixed, never shipped
- From: H08-050

### SRT-086: A card whose folder could not be read was called "Safe to format".
- What was going on: A card folder that threw a read error dropped out of the listing, so the card was judged on its other folders.
- What the product must do: If any part of a card cannot be read, it is never called safe to format, and the page names what could not be read.
- Kind: 3
- State: fixed, never shipped
- From: L11-067, H08-046

### SRT-087: A card holding a proxy without its clip is not safe to wipe.
- What was going on: A camera proxy whose original is not on the card may be the only copy of that footage.
- What the product must do: A card with such a proxy is never shown as backed up unless that proxy was copied.
- Kind: 3
- From: P18-037

### SRT-088: A card counted as backed up while 375 of its files had one copy.
- What was going on: Of three cards said to have backups, one card's 375 files (1,047 GB) existed on one drive only.
- What the product must do: Before calling a card safe to wipe, the product shows how many separate copies each clip has and names clips with only one.
- Kind: 3
- State: outcome not found
- From: P14-033

### SRT-089: Already backed-up clips were reported as having "no destination".
- What was going on: The owner: 322 clips "have no destination, but that's because they are duplicates and do not need backing up"; suggestions were offered for them too.
- What the product must do: Backed-up clips show as backed up, never count as unassigned, and need no acceptance before copying.
- Kind: 2
- From: P06-062

### SRT-090: Unplugging a backup drive removed its copies from the card's count.
- What was going on: Copies were counted only on drives currently plugged in, so a card looked less backed up than it was.
- What the product must do: Verified copies on an unplugged backup drive still count, shown as on that drive while it is away.
- Kind: 3
- State: fixed, never shipped
- From: L11-071

## The record of every copy

### SRT-091: Every copy of every clip, and where it lives, in one view.
- What was going on: The owner asked for "an overview of every copy of every file" across the NAS, external drives, laptops, cards and the cloud, for masters, proxies and audio.
- What the product must do: Each clip shows its copy count and every location, master, proxy and audio separately, and any clip view sorts and filters by drive or computer.
- Kind: 2
- From: D07-062, M04-069, P17-017

### SRT-092: Copy badges are outlined when healthy and filled only for a problem.
- What was going on: With 36,000 clips, a filled green badge on every healthy one would make the grid a wall of green.
- What the product must do: Copy-count badges are outlined when healthy, filled gold when not backed up, and red when only on a laptop, card or client drive.
- Kind: 2
- State: fixed, never shipped
- From: D07-085

### SRT-093: A double-backup percentage, and a tape mark on clips with a tape copy.
- What was going on: The owner wants "a counter for what percentage of files has double backup and any file which has a tape backup should get a small icon".
- What the product must do: The view shows the percent of master files with a second counting copy, and a clip with a tape copy carries a small non-green mark naming the tapes.
- Kind: 2
- State: still open
- From: D07-037, P17-042

### SRT-094: Tapes in the standard tape file system list in seconds but share one letter.
- What was going on: Listing such a tape reads only its index, so it takes seconds, but every tape mounts at the same drive letter.
- What the product must do: A tape is identified by its barcode, never its letter, and a clip only on tape offers a restore request naming the tapes and where they are kept.
- Kind: 1a
- State: still open
- From: D07-038

### SRT-095: A known drive or watched folder updates the record by itself when it reappears.
- What was going on: The owner asked that a drive scanned before be detected and updated whenever plugged in, and watched folders "when they become visible".
- What the product must do: Adding a drive or folder is one action, and each time it appears on any studio computer its changes reach the record unasked.
- Kind: 2
- From: D07-063, P17-018

### SRT-096: A laptop's system drive is never scanned whole.
- What was going on: A laptop's own drive holds the operating system and personal files; only folders someone chose to watch belong in the record.
- What the product must do: A computer's system drive is never offered as a new drive; only folders explicitly watched on it are scanned or backed up.
- Kind: 2
- State: fixed, never shipped
- From: D07-069

### SRT-097: A copy that vanishes is asked about, never written off.
- What was going on: The owner never deletes footage from home, only moves it onto backup drives, so a missing copy is a question, not a deletion.
- What the product must do: A missing copy raises a per-folder "where did these go?" (moved, deleted on purpose after confirming, or rescan) and stays recorded until answered; cloud and card copies age out quietly.
- Kind: 2
- From: D07-065, M04-071

### SRT-098: A move the product made itself must not raise "where did these go?".
- What was going on: Moves on the NAS change paths, so the next scan would otherwise see every moved file as gone.
- What the product must do: Any move the product performs updates the copy record at once, so the next scan raises no question about the moved files.
- Kind: 3
- State: fixed, never shipped
- From: D07-070

### SRT-099: A file replaced at the same path looked like a loss plus a new file.
- What was going on: About 1,260 downloads rewritten in place to a new codec changed size and raised 62 false "where did it go?" questions.
- What the product must do: A file replaced at the same path is the same file updated, not a loss, and stays tracked.
- Kind: 3
- From: M04-065

### SRT-100: A partial scan or listing must never mark files missing.
- What was going on: A scan of default folders shrank a 25,000-clip index to 191; drives pulled mid-scan, half-mounted or fresh from a disk check, or cut-short cloud listings, show fewer files.
- What the product must do: Files are marked gone only after a complete listing covering their folder; a scan unfinished, under 80% of last time's count, or with unreadable folders only adds.
- Kind: 3
- From: D07-066, C07-020, M04-047

### SRT-101: New footage appears on its own, but never half-copied.
- What was going on: Clips copied into a project folder did not show until a full rescan; the owner: "keep it up to date without rescanning everything every time".
- What the product must do: New files appear within about half a minute without a full rescan, only once unchanged across two looks, and an unplugged drive or missing root removes nothing.
- Kind: 3
- From: C07-015, P18-018

### SRT-102: One odd file name must never make a drive unscannable.
- What was going on: Real drives hold names with broken characters, very long paths or junk, and refusing a whole batch for one bad name blocks the drive for ever.
- What the product must do: A file the scan cannot record is skipped and counted, and the rest of the drive is still recorded.
- Kind: 3
- State: fixed, never shipped
- From: D07-067

### SRT-103: Thousands of Chinese NAS file names were recorded as question marks.
- What was going on: About 14,500 recorded names held "?" in place of non-Latin characters, and the repair stopped part-way with 4,950 still wrong.
- What the product must do: The record stores every file name exactly as it is on disk, and an interrupted repair resumes where it stopped.
- Kind: 3
- State: outcome not found
- From: P15-001

### SRT-104: A computer cannot pass off a USB stick as the NAS.
- What was going on: Editors' computers report copies, and a report naming a place by label alone could make any stick pose as the NAS or replace a real copy.
- What the product must do: A computer records copies only on drives it identifies by serial, and a report disagreeing with a live copy is counted as a conflict, never replacing it.
- Kind: 3
- State: fixed, never shipped
- From: D07-068

### SRT-105: A drive sitting in a drawer stays searchable as last seen.
- What was going on: Search saw only what was currently scanned, so a file living only on an unplugged drive was recorded but could not be found.
- What the product must do: Every file ever listed on a drive stays searchable while it is unplugged, shown with its drive and last-seen date and marked as not on the NAS.
- Kind: 2
- State: still open
- From: D07-032

### SRT-106: Footage on only one laptop drive was lost track of when the drive moved.
- What was going on: 277 files (757 GB) listed as laptop-only had changed folders and their drive had moved to another computer; none had a NAS copy.
- What the product must do: Footage held on only one drive is found again after renames, folder moves or the drive moving computers, and its backup state stays true.
- Kind: 3
- State: outcome not found
- From: P19-032

### SRT-107: The record of where copies live must survive losing the NAS.
- What was going on: Losing the NAS would lose the only record of which drive holds what, and a plain copy of a live record file can be torn.
- What the product must do: The copy record and sorter state are copied nightly in a consistent, integrity-checked form, seven kept, and carried in the cloud backup.
- Kind: 3
- State: fixed, never shipped
- From: D07-074

### SRT-108: The cloud backup runs nightly for new files, controlled from the page.
- What was going on: The owner wanted new footage sent to the cloud every night, while a multi-day first upload was still running.
- What the product must do: Nightly cloud backup sends only new and changed files, has on/off, time and Run now on the page, and never starts beside a run in progress.
- Kind: 2
- From: P17-023

### SRT-109: Laptops and drives back themselves up to the NAS, into staging.
- What was going on: The owner: "automatically back up stuff that's on the laptop or other drive to the correct place on the nas"; a wrong project guess is worse than waiting in staging.
- What the product must do: A per-drive switch, off by default, copies files with no NAS copy into staging by computer and drive, deletes or overwrites nothing, and shows the last run.
- Kind: 2
- From: D07-039, P18-008

### SRT-110: A laptop away from home must never start an automatic copy to the NAS.
- What was going on: Over the remote link a laptop can still reach the NAS, but a multi-gigabyte copy crawls; at home the round trip is under 15 ms.
- What the product must do: Automatic backups run only when the computer is on the studio's own network; when it cannot tell, it does not copy and says "away from home".
- Kind: 3
- From: C04-042, D07-040

## Sorting into shoots, people and cameras

### SRT-111: The studio calendar already says where footage belongs.
- What was going on: Event titles like "Reproductive陳昭姿interview" name episode and person, with typos; reading them placed 6,971 clips (17 TB) that had no home.
- What the product must do: Footage is suggested a home from its calendar event title, tolerating common typos, and a name belonging to two episodes is never guessed.
- Kind: 3
- From: C06-099

### SRT-112: Clips are filed under the person in date-and-time subfolders.
- What was going on: The owner wanted backup and sorting joined: every copy recorded, calendar suggestions, choices per clip, and subfolders named by times under each person.
- What the product must do: Clips are filed under the person's folder in subfolders named by date and time range.
- Kind: 2
- From: P05-064

### SRT-113: A calendar event naming two interviewees filed both under the first.
- What was going on: Three shoot days had one event for two interviews; the second person's clips and recorder audio went into the first person's folder.
- What the product must do: When one event names two people, its clips and audio are split between them or the person is asked, never filed under one name.
- Kind: 3
- From: D01-006, P11-062

### SRT-114: Suggestions are reviewed with their evidence before acceptance.
- What was going on: The owner accepted all without seeing them, then asked for "which evidence, and also other, secondary evidence - for example if multiple calendar events clash".
- What the product must do: Each suggestion shows its destination, evidence and conflicting alternatives, appears in its destination marked unconfirmed, and accepting can be undone.
- Kind: 2
- From: P05-043

### SRT-115: Many clips switch to an alternative suggestion in one step, undoably.
- What was going on: Bulk accept only warned that clips "could also be" filed elsewhere, so choosing an alternative meant changing each clip by hand.
- What the product must do: For a selection, any suggested alternative applies once to every clip that has it, reports how many were skipped, and one Undo restores previous assignments.
- Kind: 2
- From: P17-010, D07-094

### SRT-116: Every interviewee on the roster appears as a destination, greyed until used.
- What was going on: The owner: "ALL interviewees in the sheet should be added", greyed and not created on disk until clips arrive.
- What the product must do: Every roster person appears in each episode's destinations, greyed and not created until assigned clips; people in several episodes show greyed in the others.
- Kind: 2
- State: outcome not found
- From: P05-052

### SRT-117: A missing view lists events without footage and people lacking a camera or sound.
- What was going on: The owner wanted events with no footage, interviewees with one camera or no sound file, and interviewees missing per episode, with a warning on such destinations.
- What the product must do: A missing view lists those gaps, events can be dismissed, and each affected destination shows a warning naming what is missing.
- Kind: 2
- From: P05-051

### SRT-118: A second camera counts as covered when two cameras' clips land on one person.
- What was going on: The studio often shoots BRAW as A camera and an FX3 as B filed in an "A cam" folder; shoots holding both cameras and sound were flagged incomplete.
- What the product must do: A missing-camera or missing-sound warning clears whenever a destination holds two cameras' clips or a matching recorder file, whatever the folders are called.
- Kind: 2
- State: outcome not found
- From: P05-053, P12-059

### SRT-119: Two weeks of camera footage were on no drive, shown only by numbering gaps.
- What was going on: Two cameras' clip numbers jumped across a fortnight; nothing in the gap was on any drive, the NAS or the catalogue.
- What the product must do: Gaps in each camera's clip numbering are flagged with the dates either side, so cards never offloaded are noticed.
- Kind: 3
- State: still open
- From: M03-082

### SRT-120: A clip already inside a project folder counts as assigned.
- What was going on: Only 6,641 of 13,334 clips in the projects tree counted as assigned; the owner: "if the clip is in a folder in P it should be counted as assigned".
- What the product must do: Any clip already inside a project folder on the NAS counts as assigned and in place, never as work left to do.
- Kind: 2
- From: P07-030, M04-079

### SRT-121: A person's sorting plan survives every rescan and restart.
- What was going on: The owner: "Do not reset the current manifest from where it is, I have done a lot of work moving things around."
- What the product must do: Rescans, restarts and updates keep every assignment and plan the person has made, saved or not.
- Kind: 2
- From: P05-054, P07-033

### SRT-122: Clips assigned but not yet moved show dashed and dimmed in their folder.
- What was going on: The owner: they "should show in the UI but with a dashed outline and lowered opacity to show that the move is staged but not yet completed".
- What the product must do: A destination folder lists clips assigned to it but not yet there, drawn with a dashed outline at lower opacity.
- Kind: 2
- From: C07-033, P18-034

### SRT-123: Clips the automatic match cannot place confidently are reviewed and sorted by hand.
- What was going on: The owner: "we can use the footage sorter UI to sort out unmatched video", and wants to "see matches, approve, and adjust them... show why they are a match".
- What the product must do: Unconfident matches wait for a person; each proposed match shows why, plays the audio, shows transcript and paired clips, and nothing moves until approved or adjusted.
- Kind: 2
- State: still open
- From: P19-025, P18-041

### SRT-124: Each shoot day goes onto one client drive, never split.
- What was going on: The owner wanted each day's material together on one client drive, no clip on two of them, with copying spread across the drives for speed.
- What the product must do: Each shoot day is assigned to one client drive, and no clip is placed on two client drives.
- Kind: 2
- From: M04-092

### SRT-125: Which card goes to which camera folder is studio data.
- What was going on: The studio renamed a camera folder from the camera's model to its angle letter, and the offload still used the old name.
- What the product must do: Camera-to-folder naming is data an owner can change without changing or reinstalling the program.
- Kind: 3
- State: outcome not found
- From: P01-003

### SRT-126: Existing shoot folder names must survive a change of software.
- What was going on: Which of two shoots got a "(2)" folder depended on sort order, and Chinese names sort by radical and stroke in one place, by character code in another.
- What the product must do: A replacement keeps every existing shoot folder name and clip identity exactly, including any "(2)" suffix.
- Kind: 3
- From: P16-054

### SRT-127: Windows silently changes some folder names.
- What was going on: Windows drops trailing dots and spaces when it creates a folder, rejects device names like CON and LPT1, and matches names regardless of case.
- What the product must do: Planned folder names are cleaned the way Windows will store them, reserved names are refused, and names compare without case.
- Kind: 1a
- From: C06-096

### SRT-128: The NAS is case-sensitive, so a differently cased folder became a second folder.
- What was going on: Windows treats "Ukraine trip" and "Ukraine Trip" as one folder; the NAS treats them as two, splitting footage between them.
- What the product must do: When a destination folder already exists in another letter case, copies and moves use the existing folder's spelling.
- Kind: 1a
- From: C07-016

### SRT-129: A Windows card path read on the NAS became one bogus file name.
- What was going on: The NAS does not split at backslashes, so "H:\clip.braw" became a file name, the planned destination left the storage area, and the copy was refused.
- What the product must do: Paths reported by a Windows computer are split by Windows rules wherever handled, and a card copy started on the page begins on that computer.
- Kind: 3
- From: C07-032, P18-033

### SRT-130: Clips moved into a folder with an accented name did not show there.
- What was going on: After a real move, an interviewee's clips were not visible in his destination folder, whose name contains accented letters.
- What the product must do: A move into a folder whose name has accented or non-Latin letters lands there and is shown there.
- Kind: 3
- State: outcome not found
- From: P05-063

## Moving footage on the NAS

### SRT-131: Sorting never loses an original, and every move is previewed first.
- What was going on: The owner required a test run "to make sure no original footage gets lost or accidentally deleted", then a single clip, then everything.
- What the product must do: Every move offers a dry run, can run on one clip, needs approval before it runs, and never deletes or overwrites an original.
- Kind: 2
- From: P05-042, D07-042
- Check: Now that filing runs on its own with a manual override, must a move out of staging still wait for an admin's approval?

### SRT-132: A move must be a rename and say "Move"; it never quietly becomes a copy.
- What was going on: Clips in a transfer folder were offered only "copy" with the pool 91% full, and a failed rename across mounts can be papered over by a slow copy.
- What the product must do: The sorter offers Move as well as Copy, labels each by what will really happen, and a move that cannot be a rename stops, leaving both sides untouched.
- Kind: 2
- From: P16-053, D07-044

### SRT-133: A move plan with clashing destinations moves only the clean clips.
- What was going on: A 5,781-entry plan held 380 duplicate and 16 occupied destinations; 5,095 entries (6.76 TB) moved.
- What the product must do: A move never overwrites or splits a clip: a clip with any conflicting file stays whole where it is and is listed for a person to decide.
- Kind: 3
- From: D07-113

### SRT-134: An interrupted move was left "moving" for ever.
- What was going on: A move that failed partway left its plan marked "moving", with no rescan or reconciling.
- What the product must do: After a move fails or the app restarts mid-move, the product rescans and shows which files moved and which did not.
- Kind: 3
- State: still open
- From: H08-067

### SRT-135: A check after one move reported 2,528 false problems from past moves.
- What was going on: A folder was moved in Explorer minutes after a run, and the after-move check, judging every past move, reported history as damage.
- What the product must do: A check after a move judges only that move, follows later and hand moves to where files are now, and reports only files truly gone.
- Kind: 3
- From: D07-115

### SRT-136: A clip moved by hand keeps its assignment; a copy left behind is a duplicate.
- What was going on: Clips moved in Explorer lost assignments; adopting every hand move then took in 5 real duplicates (one WAV in two folders, one person in two episodes).
- What the product must do: A filed clip found elsewhere is adopted as moved only when no copy remains in its planned folder; otherwise it is a duplicate, left alone and counted.
- Kind: 3
- From: P07-031, D07-116

### SRT-137: After a move, moved clips vanished and counts went stale.
- What was going on: The sorter still showed 10,393 clips in the transfer folder and none in destinations; folders created in Explorer did not appear either.
- What the product must do: Moved clips show at their new location and can be planned again, and counts and the folder tree follow changes on disk.
- Kind: 3
- From: P05-055

### SRT-138: Planned empty folders were never created.
- What was going on: The page promised folders would be created by the move, but a plan with folders and nothing to move created nothing.
- What the product must do: Every planned folder is created even when no clip moves into it.
- Kind: 3
- From: C06-101

### SRT-139: A clip already final in another project could only be copied again.
- What was going on: A second copy doubled the bytes and let the two drift apart.
- What the product must do: A clip filed in another project can be shared into this one as a link to its folder, only on an explicit click.
- Kind: 3
- From: C06-108

### SRT-140: Destination folders can be dragged, nested, renamed and deleted.
- What was going on: The owner could not drag two animal folders into a new parent folder, nor move a folder from one parent to another.
- What the product must do: In the destination tree a person can drag a folder under any other parent, rename it and delete it.
- Kind: 2
- From: P05-044

### SRT-141: A file dragged in from Explorer did not join the plan.
- What was going on: The owner dragged a recording from his Videos folder onto a destination and it never appeared there.
- What the product must do: A file dragged from Explorer onto a destination joins the plan for that destination and shows there at once.
- Kind: 3
- State: outcome not found
- From: P05-058

## Placing sound recordings

### SRT-142: Recorder files are often misfiled, unfiled, or second offloads.
- What was going on: Of 141 staging recordings, 121 were byte-identical second offloads; 21 filed ones sat in the wrong person's folder; "missing" ones lay loose with 2021 dates.
- What the product must do: Before a recording counts as missing, every unassigned recording everywhere is searched by content, and a filed file whose audio disagrees with its folder is flagged.
- Kind: 1a
- From: M03-081, D02-006, D07-095

### SRT-143: Each sound file gets a suggested interviewee from what is said in it.
- What was going on: Recorder files are named only by date and counter; the owner wanted the likely interviewee suggested, speed over accuracy.
- What the product must do: Each sound file gets a suggested interviewee from its content and exact duplicates, with a confidence, shows its transcript on click, and can be reassigned.
- Kind: 2
- From: P10-041

### SRT-144: Speakers who introduce their organisation, or say their name late, went unidentified.
- What was going on: An interviewee opening "大家好，我們是婦女新知基金會" was skipped, names came many minutes in, and a recording was credited to someone merely mentioned.
- What the product must do: Attribution uses the whole recording, handles "we are" introductions, never credits a name only mentioned, marks guesses, and reports recordings it cannot attribute.
- Kind: 3
- From: C06-005, D02-009, P11-018, P05-048

### SRT-145: Field audio is placed beside its video by time, then waveform, then speech.
- What was going on: The owner wants every field recording, even ones already filed, matched "by date and time", then "waveform matching", then transcripts of the first ten minutes.
- What the product must do: Every field recording ends up in its shoot's audio folder beside the matching video, duplicates set aside not deleted, trying time, then waveform, then transcript.
- Kind: 2
- State: still open
- From: P18-040, M04-082

### SRT-146: Sound matching considers only the studio's own camera footage.
- What was going on: The owner: "we are matching to our footage, fx3 a74 or bmcc only. youtube downloads are obviously irrelevant to this process".
- What the product must do: Matching recordings to video considers only the studio's camera clips (FX3, A7 IV, BMCC), never downloaded video.
- Kind: 2
- From: P19-024

### SRT-147: Loose field recordings are found by format, length and name.
- What was going on: The owner: field audio "is .wav, is of relevant length, is not broken, does not have the name of a piece of music"; "all field wavs are 32 bit".
- What the product must do: A search for unplaced field audio on every computer and drive keeps only unbroken 32-bit WAV files of plausible length not named like music.
- Kind: 2
- State: still open
- From: P18-043

### SRT-148: Loose waveform matching split one take's two channels across two shoots.
- What was going on: Single-clip waveform matches at low thresholds put the two channels of one recording in different shoots; a peak of 0.75 with a 0.25 margin over the next held.
- What the product must do: A single-clip audio match is accepted only when it clearly beats the next candidate, and both channels of a take stay together.
- Kind: 3
- State: fixed, never shipped
- From: M04-081

### SRT-149: The same speech in Simplified and Traditional Chinese never matched.
- What was going on: One speech-to-text wrote Chinese in Simplified, another in Traditional, so identical speech in mixed transcripts never matched.
- What the product must do: Chinese text is compared in one script, so identical speech matches whichever engine wrote either side.
- Kind: 3
- State: fixed, never shipped
- From: P19-027

### SRT-150: Paid transcription credit ran out partway through thousands of files.
- What was going on: A 6,246-file run (about 173 hours) ran out of paid credit; the owner ruled that local transcription should then finish "the remaining clips".
- What the product must do: Running out of paid transcription keeps every finished transcript, resumes skipping finished files, and finishes the rest with local transcription unattended.
- Kind: 3
- State: fixed, never shipped
- From: P19-026

## Thumbnails and hover filmstrips

### SRT-151: Thumbnails are made once in the background and kept.
- What was going on: Only 5% of videos had one and a screen of 48 took 5.2 s on demand; the owner: "generate thumbnails once and have them stored".
- What the product must do: After each scan or card read every clip gets a thumbnail in the background, shown instantly once stored, and a card clip's is reused for its NAS copy.
- Kind: 2
- From: D07-078, P17-001, P18-032

### SRT-152: The thumbnail on screen waited behind hours of background thumbnails.
- What was going on: Workers took a waiting background job before the one on screen.
- What the product must do: A thumbnail on screen is made before any background thumbnail still waiting.
- Kind: 3
- State: still open
- From: H08-068

### SRT-153: A clip's thumbnail and assignment must follow the recording, not its path.
- What was going on: Clips were known by their path, so moving them into projects orphaned 8,835 of 9,926 thumbnails (390 MB) and lost their assignments.
- What the product must do: A clip keeps its thumbnail, filmstrip and assignment through any move, copy or hand rename.
- Kind: 3
- From: C07-012, D07-047

### SRT-154: Clips the server cannot reach got blank thumbnails.
- What was going on: The NAS cannot read a card or local disk in an editor's computer; there a whole card's 47 thumbnails took 1.8 s and 350 KB.
- What the product must do: The computer holding the clips sends their thumbnails, from the camera's own proxies where present, shown within about 5 seconds in grid order; sound-only clips show an audio card.
- Kind: 3
- From: C07-030, C04-045, P18-031, P17-013

### SRT-155: Hover filmstrips showed only a clip's first seconds.
- What was going on: The owner saw "only playing the first few frames of the video, not a playback sprite spread across the whole clip".
- What the product must do: Each filmstrip tile comes from a later point than the one before, spread evenly to the end, and strips made wrongly are remade.
- Kind: 3
- From: P18-004, C07-026

### SRT-156: A hover filmstrip has one frame per 10 seconds, between 12 and 50.
- What was going on: Hovering streamed the whole proxy (244 MB for 5 minutes), and 12 frames were too coarse for long clips; the owner: "up to a maximum of 50".
- What the product must do: Hover preview shows one frame per 10 s of clip, at least 12 and at most 50, from an image of tens of kilobytes made ahead of time.
- Kind: 2
- From: D07-080, P17-002

### SRT-157: Making filmstrips in the background overloaded the NAS.
- What was going on: Single jobs grew to 31-41 GB on a 62 GB NAS and were killed 35 times in five hours; parallel jobs pushed it to 72-81 C with fans doubled.
- What the product must do: Background picture-making on the NAS stays within a few hundred MB per job at low priority and capped concurrency, and a failed clip is not retried every restart.
- Kind: 3
- From: P18-005, C07-027, M05-081

### SRT-158: Thumbnails must not pile up on a phone.
- What was going on: The owner: the page "shouldn't keep thumbnails permanently on a phone"; storage a site keeps lasts until the site deletes it, unlike the browser's ordinary cache.
- What the product must do: Thumbnails and filmstrips on a phone are small (about 2 to 3 KB) and held only in the browser's ordinary evictable cache.
- Kind: 2
- From: P17-003, D07-079

### SRT-159: Heavy sorter work must never stall the rest of the dashboard.
- What was going on: 100 cold thumbnails at once stalled every other dashboard request by 1.8 s, and 300 by 7.2 s.
- What the product must do: While the sorter scans or makes hundreds of thumbnails, every other dashboard page still answers within a fraction of a second.
- Kind: 3
- From: D07-048

## The sorter page

### SRT-160: The sorter works from any signed-in browser and names places, not drive letters.
- What was going on: The owner: "make it into a website which can be accessed anywhere … queue up file moves and backups from anywhere", "computer agnostic".
- What the product must do: Sorting, moves and backups are queued from any signed-in browser, phone included, under the product's one sign-in, and every place is named by its server location.
- Kind: 2
- From: D07-041, P16-052, M04-076

### SRT-161: The footage page took over 20 seconds to open on a remote laptop.
- What was going on: Every open downloaded all 36,000 clips (43 MB raw, over 4 MB compressed), 98% of them already filed into projects.
- What the product must do: The first view asks for a source and loads under 0.2 MB within a few seconds; a source's and a destination's clips load only when opened.
- Kind: 3
- From: P17-004, D07-077, C07-013

### SRT-162: The footage page said "no clips match" while still loading.
- What was going on: The empty message appeared about 60 ms after page start and stayed until data arrived.
- What the product must do: Until clips arrive the page says it is loading, a failed load offers Try again, and "no clips match" appears only once data is there.
- Kind: 3
- From: P18-017

### SRT-163: Every source is listed under the computer it lives on, closed by default.
- What was going on: The owner: "everything should be under its own computer name", cards inside their computer, "by default all dropdowns should be closed".
- What the product must do: Sources group under each computer, NAS first, all closed; a newly inserted card opens its computer, cards present at load do not; there is no "all clips" source.
- Kind: 2
- From: D07-091, C07-023, P17-006

### SRT-164: Project folders are destinations, never sources, and a computer is never guessed.
- What was going on: The owner: "projects should not be there, as that is exclusively a destination"; sources were named with no hint of their computer.
- What the product must do: Sources never list project folders; each shows its computer as the server knows it, one name per computer however spelt, or "Unknown computer".
- Kind: 2
- From: P17-005, D07-093

### SRT-165: The source list can be hidden, and the clips fill its space.
- What was going on: The owner: "you should be able to hide it and open it. If you hide it the clips panel should expand to fill the space."
- What the product must do: Hiding the source list widens the clips to full width, one control brings it back, and the choice is remembered per browser.
- Kind: 2
- From: D07-092, P18-003

### SRT-166: Managing known drives stays off the main sorting screen.
- What was going on: The owner: "it's a rarely looked at option, so just move it into a settings panel".
- What the product must do: Managing known drives lives in a settings area, not on the main sorting screen.
- Kind: 2
- From: P17-009

### SRT-167: A clip and its destination are each one click from the other.
- What was going on: There was no way to browse by assigned folder; the owner wanted clip to destination, destination to contents, and open-in-source inside the app and in Explorer.
- What the product must do: Selecting a clip opens its destination, and its menu offers open in source (in the app and in Explorer) and show in destinations.
- Kind: 2
- State: outcome not found
- From: P05-045

### SRT-168: A clip's menu offers other suggestions and the other camera's footage of that moment.
- What was going on: Suggestions often caught the A camera but missed the B camera; the owner wanted to jump between camera folders covering the same date and time.
- What the product must do: A clip's menu lists alternative destinations and the folders of other cameras that recorded the same date and time, each openable.
- Kind: 2
- State: outcome not found
- From: P05-046

### SRT-169: Selecting a clip shows all its details.
- What was going on: The owner asked for an info pane showing every piece of metadata about the selected file.
- What the product must do: Selecting any clip shows its size, frame rate, duration, camera and every location it is stored.
- Kind: 2
- From: P05-047

### SRT-170: The clip view plays sound, resizes thumbnails, sorts by length and filters by day.
- What was going on: The owner asked for audio in the preview, larger thumbnails, sorting by clip length and a calendar picker showing all footage from one day.
- What the product must do: The clip view can play sound, change thumbnail size, sort by duration, and filter to every clip from a picked day.
- Kind: 2
- State: outcome not found
- From: P05-050

### SRT-171: The sorter page showed a "too many open files" error.
- What was going on: Opening the sorter returned an error that the process had too many files open on Windows instead of the page.
- What the product must do: The sorter keeps its open files bounded during long scans, and the page always loads.
- Kind: 3
- State: outcome not found
- From: P13-045

### SRT-172: The calendar connect button flashed up and disappeared.
- What was going on: The option to connect the studio's calendar showed for a second and vanished before it could be clicked.
- What the product must do: The calendar connect control stays visible until the calendar is connected, and a failed connection says why.
- Kind: 3
- State: outcome not found
- From: P05-060

## Archive search

### SRT-173: The archive sorts and searches every place footage lives, four ways.
- What was going on: The owner: sorting "by project / date / name / etc", searching "lots of different drives", tapes tracked, "fuzzy search, precise search, cross-language search" and an assistant search.
- What the product must do: One search covers the NAS, every known drive, the cloud and tapes, sorts by project, date, name, camera, size and copies, with exact, loose, cross-language and assistant modes.
- Kind: 2
- State: still open
- From: D07-031, M04-066, P17-041

### SRT-174: An English search must find Chinese names, and the reverse.
- What was going on: Folders, people and events mix Traditional Chinese and English: "typhoon" should find 颱風災後, 台灣 match 台湾, "zhang" find 張; two-character words like 颱風 are common.
- What the product must do: Name searches match across Traditional and Simplified, English, Chinese and pinyin, any two-character query finds every name containing it, and corrected translations are kept.
- Kind: 2
- State: still open
- From: D07-033

### SRT-175: Searching a person's name shows their event and its clips.
- What was going on: The owner wanted to search a name or folder and get the matching event with its date and every clip assigned to it.
- What the product must do: A search by event or folder name, in Chinese or English, returns the event with its date and its assigned clips.
- Kind: 2
- State: outcome not found
- From: P07-032

### SRT-176: An assistant search shows the searches it ran and sends only names out.
- What was going on: A plain-language archive question is answered by searches over the index, and no media or transcripts may leave the NAS.
- What the product must do: An assistant answer lists every search it ran as an editable query with a reason per result, and only file metadata ever leaves the NAS.
- Kind: 2
- State: still open
- From: D07-035

## Downloading originals and sharing folders

### SRT-177: Anyone signed in can download chosen originals into a folder they pick.
- What was going on: The owner: "it should just ask you for a download directory on your local computer", no project needed; picking a folder works only in Chrome or Edge on a computer.
- What the product must do: Selected clips download into a chosen local folder, folders kept, with progress, Pause, Cancel, skipping files already there, proxies only if ticked; other browsers get per-file links.
- Kind: 2
- From: P18-020, M04-105, D07-054

### SRT-178: Chrome will not let a page save into Documents, Desktop, Downloads or a drive root.
- What was going on: Chrome's folder picker refuses those folders themselves ("contains system files"), while a folder inside any of them is allowed.
- What the product must do: Downloading to a chosen folder explains which folders the browser refuses and starts the picker where a subfolder can be chosen.
- Kind: 1a
- From: P18-022, C07-028, M04-106

### SRT-179: A browser saving into a picked folder writes each file only when it closes.
- What was going on: If the tab crashes or power fails mid-file, that file restarts from its last closed state, usually zero; network drops, Pause and Cancel lose nothing.
- What the product must do: A large download survives dropped connections without losing bytes, and the person is told a crashed tab restarts the file in progress.
- Kind: 1a
- From: D07-055

### SRT-180: A resumed download continues only its own unfinished files.
- What was going on: Re-running into the same folder must fetch only what is missing, and a smaller file of the same name may be the editor's own.
- What the product must do: Full-size files are skipped, only files the download itself marked in progress are continued, and a same-name file without that mark is left alone and reported.
- Kind: 3
- State: fixed, never shipped
- From: D07-056

### SRT-181: A download never delivers the wrong file after a rescan.
- What was going on: A file asked for by its position in a clip's list can change after a rescan, and a server answering a resume with the whole file corrupts it.
- What the product must do: Every requested file is checked by name before it is sent, a mismatch asks to start again, and a resume answered with the whole file restarts that file.
- Kind: 3
- State: fixed, never shipped
- From: D07-057

### SRT-182: Any footage folder can be shared by an expiring link.
- What was going on: The owner: "you should be able to generate a unique link for any folder to send to people".
- What the product must do: An admin links one folder, lasting 14 days by default and 365 at most, with an off switch; a whole root is refused; holders download files or a zip.
- Kind: 2
- State: fixed, never shipped
- From: P18-021, D07-058

### SRT-183: A shared folder link must never reach anything outside its folder.
- What was going on: A shared link opens with no sign-in, so paths, symbolic links and junk files are its attack surface.
- What the product must do: Unknown, revoked and expired links answer not found, no path climbs out, and links, hidden files, system junk and half-written files are never listed or served.
- Kind: 3
- State: fixed, never shipped
- From: D07-059

## Filed here, belonging elsewhere

### SRT-184: A camera with a wrong clock dates clips in the future, and they never upload.
- What was going on: Clips dated ahead of now never passed an "old enough to upload" test, and nothing reported it.
- What the product must do: Footage dated in the future is uploaded like any other and reported to the editor, never skipped as too new.
- Kind: 1a
- State: still open
- From: H07-113
- Move to: sync

### SRT-185: Field internet abroad is too slow for uploads and downloads.
- What was going on: Hotel and mobile internet abroad was slow and dropped, so proxy uploads kept failing and downloads ran at about 60 KB/s.
- What the product must do: Field uploads survive slow, dropping connections by resuming, and heavy work such as transcription is left for home.
- Kind: 1a
- From: M04-095
- Move to: sync

### SRT-186: Re-importing a folder of numbered stills duplicates them in Resolve.
- What was going on: Resolve groups numbered JPGs into image sequences whose path is not one file, so an "already imported" check misses them; 941 stills became 86 sequences and 50 stills.
- What the product must do: Re-importing a folder into Resolve never adds a second copy of stills it already holds as image sequences.
- Kind: 1a
- State: outcome not found
- From: D02-029
- Move to: resolve-on-the-editors-computer

## Sealed

### SRT-S01: On Windows, card and drive copies go through the owner's chosen copier.
- What was going on: A build swapped in a home-made copier against the plan; that was ruled a mistake and reversed, the home-made one kept only for a Mac or a PC without it.
- What the product must do: On Windows, card and drive backups run through the owner's chosen copier; any other copier is only a fallback where it is missing.
- Kind: 1b
- Tool: TeraCopy
- From: D07-052

### SRT-S02: The copier loses jobs sent at once, and its history format differs by version.
- What was going on: Several jobs handed to the running copier at once lost all but one; its history marks copied-and-verified as result 3; version 3.17 keeps history in another layout.
- What the product must do: Copier jobs launch one at a time, each confirmed in its history before the next, read correctly from whichever version is installed, with matching hashes required.
- Kind: 1b
- Tool: TeraCopy (history database; 3.x layout differs; 211 MB/s with verify against 188 for a plain copier)
- From: C04-037, C06-111

### SRT-S03: The copier's verify is one global setting, and unchecked results look queued.
- What was going on: Verify-after-copy is one global setting, and with it off a finished file reports the same result code as a queued one.
- What the product must do: What landed is decided by looking at the disk, not the copier's result, and the global verify setting is restored even after a crashed run.
- Kind: 1b
- Tool: TeraCopy 4.0.5 (global TestAlways setting, result code 2)
- From: C07-005

### SRT-S04: The copy tool gives a file its full size the moment it starts writing.
- What was going on: A progress view counting files by size alone would call unfinished files done, because the tool pre-sizes each file.
- What the product must do: A file counts as done only when its size and timestamp both match the source, or a check proves its contents.
- Kind: 1b
- Tool: robocopy
- From: P14-030

### SRT-S05: The general decoder cannot read BRAW or R3D, so pictures come from the proxy.
- What was going on: BRAW clips showed no thumbnail or preview because the decoder used cannot open BRAW or RED RAW files.
- What the product must do: A RAW clip's thumbnail and preview come from the camera's proxy; with no proxy yet the page shows a placeholder and retries later.
- Kind: 1b
- Tool: ffmpeg (no BRAW or R3D decoder)
- From: C07-029, D07-060

### SRT-S06: One decode run reading many points of one file grew to tens of gigabytes.
- What was going on: Opening the same 4K clip as 50 separate inputs in one run, each with every processor thread, held frame buffers for all of them at once.
- What the product must do: Each filmstrip frame is taken by its own short seek-and-decode with few threads, and frames are tiled in a separate small step.
- Kind: 1b
- Tool: ffmpeg
- From: P18-006

### SRT-S07: Joining many seeked inputs of one clip gave consecutive frames from the start.
- What was going on: When each seeked input ran to the end of the file, the join took the first input's frames first, so every tile came from the opening seconds.
- What the product must do: Each seeked input is limited to exactly one frame before frames are joined into a strip.
- Kind: 1b
- Tool: ffmpeg
- From: P18-007

### SRT-S08: A rename between two separately mounted folders fails even on one dataset.
- What was going on: Staging and the project tree were mounted separately, so a rename between them failed with a cross-device error although both sat on one dataset.
- What the product must do: Whatever performs moves sees staging and project folders under one mount, so a move between them is a rename.
- Kind: 1b
- Tool: Docker bind mounts on TrueNAS (EXDEV)
- From: D07-045

### SRT-S09: The cloud backup tool counts a file only when it finishes.
- What was going on: Its live progress jumps per finished file, so an instantaneous speed is meaningless.
- What the product must do: Cloud upload speed shown to a person is smoothed over about two minutes.
- Kind: 1b
- Tool: restic --json status
- From: D07-075

### SRT-S10: A hosted database's shared daily limits ran out and took other sites down.
- What was going on: 100,000 writes and 5 million reads a day per account; one change list read 26 million rows and a one-off repair 442 million, failing every site on the account.
- What the product must do: The copy record lives where no daily quota can stop it, and every job's reads scale with what it changes, are bounded, watched and stopped when far over.
- Kind: 1b
- Tool: Cloudflare D1 (free plan, limits shared per account)
- From: D07-076, C07-011, P14-042

### SRT-S11: The studio's website blocked the server's requests by their default client name.
- What was going on: The card tracker on the studio's public site answered 403 to the NAS, because its protection blocks a generic library client name.
- What the product must do: Requests to the studio's own sites carry a named client identity and are tested against the live site, not only locally.
- Kind: 1b
- Tool: Cloudflare in front of the card tracker; Python urllib's default User-Agent
- From: P17-026, C07-021

### SRT-S12: A three-character substring index cannot find two-character Chinese words.
- What was going on: A trigram index matches only queries of three or more characters, but two characters, such as 颱風, is a common Chinese word length.
- What the product must do: A two-character Chinese query finds every name containing it.
- Kind: 1b
- Tool: SQLite FTS5 trigram tokenizer (needs 3.34 or newer)
- From: D07-034

### SRT-S13: The script language turns lists of one or none into something else.
- What was going on: Returning a one-item list gave a single item and an empty list read as missing, so a one-file card silently stopped card detection.
- What the product must do: Card detection works for cards holding zero, one or many files, and a failure in detection is reported, never swallowed.
- Kind: 1b
- Tool: PowerShell array unrolling
- From: C06-102

### SRT-S14: A public link relay is too slow for hundreds of gigabytes.
- What was going on: Links published past the private network go through a relayed, bandwidth-limited service: fine for a few files, slow for hundreds of GB.
- What the product must do: A link shows both its team-network address (full speed) and its public one, and large outside deliveries are flagged as slow.
- Kind: 1b
- Tool: Tailscale Funnel
- From: D07-061

### SRT-S15: The paid speech-to-text writes Taiwanese Chinese in Simplified characters.
- What was going on: The paid service returned Simplified Chinese for Taiwanese speech, while the local engine and the studio's transcripts were Traditional.
- What the product must do: Output from the paid service is converted to the studio's script before it is stored, shown or compared.
- Kind: 1b
- Tool: Soniox
- From: P19-028

### SRT-S16: Paid batch transcription costs about $0.10 per audio hour.
- What was going on: 173.5 hours of audio was estimated at about $17.35; a per-file minimum could add more across thousands of short clips.
- What the product must do: Before a paid run, the expected cost is shown from real file lengths so a person can check the credit covers it.
- Kind: 1b
- Tool: Soniox
- From: P19-029

### SRT-S17: Local transcription takes 6 to 13 seconds per 10-minute file on a desktop GPU.
- What was going on: The large turbo model on an RTX 3080 agreed with the paid service on 78-90% of phrases and on timing within 0.02 s.
- What the product must do: Local transcription stands in for the paid service for speech matching, at about 6-13 s per 10 minutes of audio.
- Kind: 1b
- Tool: Whisper large-v3-turbo
- From: P19-030

## Removed
