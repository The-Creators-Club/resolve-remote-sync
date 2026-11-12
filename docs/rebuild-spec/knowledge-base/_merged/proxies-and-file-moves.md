# Proxies, and moving footage

A proxy is a small copy of a camera original that editors cut with; Resolve plays the proxy and renders from the original.

## What Resolve accepts as a proxy

### PRX-001: Resolve linked a proxy on its own when it sat in a Proxy folder.
- What was going on: On plain import Resolve links a same-named file in a Proxy subfolder beside the original; its own "Generate Proxy Media" writes to a separate cache folder instead.
- What the product must do: Proxies sit in a Proxy folder beside their originals under matching names, and editors are told to set Proxy Handling to Prefer Proxies.
- Kind: 1a
- From: M05-062, M02-038

### PRX-002: A proxy one character off in its name never attached in Resolve.
- What was going on: Resolve pairs proxies by exact file name; a synced name that differed in one fullwidth punctuation mark (？ ：) left the clip without its proxy.
- What the product must do: Every file reaches the other side with a byte-identical name, Chinese and fullwidth punctuation included, in both directions.
- Kind: 1a
- From: P02-041

### PRX-003: Resolve refused a proxy whose timecode differed from its original's.
- What was going on: Resolve validates a pairing on embedded start timecode; a proxy without the camera's timecode starts at 00:00:00:00 and is refused despite matching rate, frame count and duration.
- What the product must do: Every proxy carries its original's start timecode, or none when the original has none, and a link counts as done only when Resolve accepts it.
- Kind: 1a
- From: G01-025, P05-023, C01-095, L03-057

### PRX-004: Sony footage at 29.97 or 59.94 got proxies Resolve refused on drop-frame form.
- What was going on: Sony metadata prints drop-frame timecode in colon (non-drop) form; same digits in the two forms are different frames, and a rewrite can silently flip a file's drop-frame flag.
- What the product must do: A proxy's timecode names the same frame in the same drop-frame form Resolve reads from the original, verified on the value and form written and by Resolve accepting it.
- Kind: 1a
- From: H01-052, C01-096, L03-058, M02-036, L09-037
- Check: Should Sony colon timecode at 29.97 and 59.94 always be written drop-frame, or only when Resolve reads the original as drop-frame?

### PRX-005: Resolve refused proxies only one or two frames short.
- What was going on: Resolve rejects a proxy whose frame count differs from the original's by even one frame, though it plays fine; a check with two frames of slack let them through.
- What the product must do: Every proxy, from any producer, has exactly the original's frame count for constant-frame-rate footage, or is refused and remade.
- Kind: 1a
- From: H06-032, L09-035

### PRX-006: Phone footage has no exact frame count for a proxy to match.
- What was going on: Variable-frame-rate sources, such as phones, failed a strict frame-count equality, which failed the whole ingest item.
- What the product must do: The proxy length check accepts variable-frame-rate sources by a rule suited to them and never fails a whole ingest over it.
- Kind: 1a
- From: H06-033

### PRX-007: A video file's stated frame count and duration differ from its real frames.
- What was going on: Header frame counts are often missing or wrong, and duration can include audio running past the last picture frame.
- What the product must do: A clip's length for proxies or offline placeholders comes from counted picture frames, read at most once per file version, never from header figures.
- Kind: 1a
- From: H06-034

### PRX-008: HEVC proxies played everywhere except Resolve, which showed Media Offline.
- What was going on: Resolve and QuickTime refuse HEVC in MP4 tagged "hev1" (VLC plays it), and common encoders write "hev1" by default.
- What the product must do: Every HEVC-in-MP4 proxy is tagged "hvc1", verified by opening it in Resolve.
- Kind: 1a
- From: G01-024

### PRX-009: Proxies kept only the first audio track of multi-track camera files.
- What was going on: Camera originals routinely carry two or more audio streams (channel pairs, scratch plus lav), and a proxy made with default settings keeps only one.
- What the product must do: A proxy carries every audio track of its original, in the same order.
- Kind: 1a
- From: H01-011

### PRX-010: "Sync stuck" was really Resolve refusing proxies a few frames short.
- What was going on: Every file had synced, but 7 proxies were 1 to 18 frames short and another covered 1,238 of 3,741 seconds, so Resolve would not link them.
- What the product must do: A proxy whose frame count differs from its original is named to the editor and on the dashboard as a proxy fault, not a sync stall, and remade.
- Kind: 3
- State: outcome not found
- From: P11-038, M02-033

### PRX-011: Refused proxies were re-offered every two minutes, 1,357 times.
- What was going on: Real refusals were retried for days, while a link that failed only because Resolve had closed was stored as a permanent refusal.
- What the product must do: Only a real refusal is remembered, per file version, and shown once; a failure because Resolve is closed is retried later.
- Kind: 3
- From: L03-060

### PRX-012: The editor could not tell why Resolve would not use their proxies.
- What was going on: Resolve refuses a proxy with mismatched timecode and will not play an unreadable proxy even when the link is right.
- What the product must do: The editor sees how many proxies Resolve refused, the first such clip, and the likely cause in plain words.
- Kind: 3
- From: L04-111

### PRX-013: A half-finished proxy check would have relinked 1,300 clips nobody asked for.
- What was going on: When proxy details were not fetched, every clip read as "no proxy" and would have received an unrequested relink.
- What the product must do: "Could not find out" is never treated as "no proxy"; an incomplete answer about a project's clips is discarded, not acted on.
- Kind: 3
- From: G01-009

## What a proxy must be

### PRX-014: Blackmagic Proxy Generator only sees proxies saved as .mov.
- What was going on: The owner: "blackmagic proxy generator cannot see proxies in any other format", so .mp4 proxies were invisible to it, while browsers need .mp4 previews.
- What the product must do: Proxies made for Resolve are .mov files; previews played in a browser stay .mp4.
- Kind: 1a
- From: P06-060, M02-044

### PRX-015: Proxies travel over the internet, so they must be small.
- What was going on: The owner wants proxies compressed about as much as Blackmagic's generator output: at most 1080p, H.264 around 2.5 Mbps, never larger than the original.
- What the product must do: Every proxy is at most 1080p, averages no more than about 2.5 Mbps, is never larger than its original, and sits where Resolve links it.
- Kind: 2
- From: P04-032, P07-005

### PRX-016: Proxies with a LUT burned in are useless and are set aside.
- What was going on: The owner had all of one camera's proxies quarantined: "they're useless because they have the lut on".
- What the product must do: A proxy with a look burned in is never linked as an editing proxy; it is set aside, not deleted.
- Kind: 2
- From: P05-061

### PRX-017: Proxies for odd-height screen recordings failed and were given up on.
- What was going on: Some sources (screen captures, full-colour or lossless video) have an odd pixel width or height, and video encoders refuse odd dimensions.
- What the product must do: A source with an odd width or height still gets a proxy, rounded to even dimensions.
- Kind: 3
- From: H01-013

### PRX-018: 10 of 244 generated previews were corrupt despite correct metadata.
- What was going on: An encode can destroy the picture while duration and size look right, or stop early with no error; checking a 10-second sample missed 2 of 10.
- What the product must do: Every proxy or preview is fully decoded and its duration compared with the source before use, and failures are remade.
- Kind: 3
- From: M05-009

### PRX-019: Proxies of multi-hour clips were encoded, then thrown away by a too-short check.
- What was going on: The decode check of a finished proxy had a fixed 30-minute limit, and a multi-hour proxy checked over the network takes longer.
- What the product must do: Every time limit on making or checking a proxy grows with the clip's length, and finished work is never discarded for a limit alone.
- Kind: 3
- From: H01-012

### PRX-020: Proxy making failed again and again on camera originals truncated on the NAS.
- What was going on: Two originals on the NAS were incomplete, missing the index at the end of the file, so every proxy attempt failed.
- What the product must do: An original that cannot be read to its end is reported as damaged with its path, not retried forever.
- Kind: 3
- State: outcome not found
- From: M02-035

## Raw camera formats and Blackmagic Proxy Generator

### PRX-021: Blackmagic RAW, RED and Canon raw clips sat without proxies for months.
- What was going on: General-purpose encoders cannot decode .braw, .r3d or .crm; the owner: re-encoding them "will require bm proxy generator".
- What the product must do: Raw clips are counted, routed to a decoder that reads them, started without the editor's help, verified like any proxy, and never failed as broken.
- Kind: 1a
- From: M02-043, M05-063, P11-039

### PRX-022: Blackmagic Proxy Generator is Resolve started with a flag.
- What was going on: Its shortcut runs Resolve with "-pg", so only the command line tells it from the editor; it watches folders listed in its own settings.
- What the product must do: The generator is told from Resolve by its command line, the user's own watch folders are never removed, and it is never killed mid-run.
- Kind: 1a
- From: C01-076

### PRX-023: Blackmagic Proxy Generator silently did nothing, then duplicated existing proxies.
- What was going on: It opens idle until Start is pressed, does nothing with an empty watch list, rewrites its settings on exit, and re-encoded 172 clips proxied under another name.
- What the product must do: Its watch folders are set only while it is closed, it is running before work counts as handed over, and it never re-encodes clips already proxied.
- Kind: 1a
- From: L03-072, P05-034

### PRX-024: A Chinese-named watch folder in Proxy Generator was garbled and never watched.
- What was going on: Blackmagic Proxy Generator reads its settings file as Latin-1 and writes non-ASCII back as its own escape codes; raw UTF-8 was garbled and re-added every launch.
- What the product must do: A watch folder with Chinese or accented characters shows correctly in the generator, is watched, and is never added twice.
- Kind: 1a
- From: L01-086, C02-074, P07-004

### PRX-025: Proxy Generator has no settings folder until its own first run.
- What was going on: Its preferences folder is created by its first launch, not by the Resolve installer, so waiting for that folder means it never launches.
- What the product must do: On any machine with Resolve installed, the product can set up and launch the proxy generator even if it was never opened.
- Kind: 1a
- From: H01-055

### PRX-026: Raw proxies and other proxies fought over one graphics card.
- What was going on: Raw clips go to Resolve's own generator while other clips are encoded by the product, and both want the same GPU.
- What the product must do: Raw clips' proxy run starts only once every other clip's proxy is made, so two proxy jobs never compete for one GPU.
- Kind: 1a
- From: P04-030

### PRX-027: 148 ordinary clips were sent to the external proxy generator.
- What was going on: Clips that were not raw went to Blackmagic's generator; the owner said they "should have just been done by" the product's own proxy maker.
- What the product must do: Clips the product can decode get proxies from its own encoder; only formats it cannot decode, such as Blackmagic RAW, go elsewhere.
- Kind: 2
- State: still open
- From: P05-035

### PRX-028: A "please click Start" for the proxy generator went only to a log.
- What was going on: When the app could not press Start in the generator on the editor's screen, the request was logged and nobody saw it.
- What the product must do: When an automated step needs a person to act, that person is told on their computer, and the request clears once done.
- Kind: 3
- From: L04-115

### PRX-029: The proxy generator stalled on one file and failed others with no reason.
- What was going on: The owner twice saw Blackmagic Proxy Generator stall on a file or report failure, with no reason shown to him.
- What the product must do: When a project's proxies cannot be made, the editor is told which file failed and why, instead of a stuck progress line.
- Kind: 3
- State: outcome not found
- From: P14-002

## Making proxies on editors' computers

### PRX-030: Missing proxies are made only while the computer is idle.
- What was going on: Clips without proxies never reach remote editors; the owner wants gaps reported and filled on editors' own computers without getting in their way.
- What the product must do: Proxy making starts after 5 minutes without input, treats unknown idleness as busy, stops within seconds of input and discards its partial file.
- Kind: 2
- From: P04-028, M02-041

### PRX-031: Proxy making uses the whole computer while idle, but backs off for Resolve.
- What was going on: The owner: idle proxy making "can absolutely max out compute", "unless yeah the computer is doing a render or something else".
- What the product must do: An idle computer encodes several proxies in parallel, dropping to one whenever Resolve is open or rendering, even on a forced run; each computer can override.
- Kind: 2
- From: C01-082, M01-077, P05-001

### PRX-032: Proxy making could fill the disk or encode a file still being copied.
- What was going on: No free-space floor, one modified-time look judged a copy finished though copiers stamp it at start and end, and proxies of proxies were made.
- What the product must do: Proxy making keeps at least 20 GB or 5 percent free, waits for two equal size-and-time samples, and never encodes proxy-folder, partial or its own files.
- Kind: 3
- From: L01-042

### PRX-033: A person can see which proxies were made, live progress and time left.
- What was going on: The owner wanted "a place to track what proxies it made, progress"; with only a rotating log, a long run looked identical to a stuck app.
- What the product must do: The app shows the clip being encoded with its length and percent, a queue estimate, and a made-and-failed history that survives a restart.
- Kind: 2
- From: C01-079, P05-002

### PRX-034: A machine made zero proxies overnight while showing a full queue.
- What was going on: About 1,040 clips were queued and none were made, every encode failing, and nothing told the owner.
- What the product must do: A pass that ends with none made and some failed shows that failure plainly on that pass.
- Kind: 3
- From: P04-029

### PRX-035: The retry and stop buttons for proxy making did not do what they said.
- What was going on: "Make the missing proxies now" kept the failure limit, so nothing retried, and a stale Stop pressed when nothing ran cancelled the next run's queue.
- What the product must do: A manual retry retries every failed clip now, and Stop stops only work running at that moment.
- Kind: 3
- From: H01-028

### PRX-036: Failed clips filled the proxy queue, so 540 makeable clips were never made.
- What was going on: Only the newest 500 clips per project were looked at, and once all had hit the failure limit the machine reported nothing to do.
- What the product must do: Clips that failed never crowd out clips that can still be made; a machine idles only when nothing makeable remains.
- Kind: 3
- From: H01-029

### PRX-037: Proxy making stopped for low space and only the admin could see why.
- What was going on: Proxy making paused for low disk, a retry limit or a truncated list, and only the dashboard showed it.
- What the product must do: Every reason proxy making is held back is told to the editor at that computer in a sentence, naming any clip given up on.
- Kind: 3
- From: L04-113

### PRX-038: Originals with no proxy were invisible to every editor, and nothing said so.
- What was going on: Only proxies travel down to editors, so an original without one never reaches anyone; one machine had 1,046 such clips.
- What the product must do: Originals lacking a proxy are counted per project and shown on the editor's computer and on the dashboard.
- Kind: 3
- From: C01-070

### PRX-039: A new project said "0 originals" for up to 45 minutes.
- What was going on: New projects were counted in a slow rotation, so views showed 0 originals, an empty picker, and "43/0" beside people.
- What the product must do: A new project is counted within about a minute, and until then every view says "counting", never 0.
- Kind: 3
- State: fixed, never shipped
- From: P18-023

### PRX-040: The originals picker showed no picture and could not play a clip.
- What was going on: The owner: "there's no thumbnail or preview in the bring originals here dialogue".
- What the product must do: Each file in the originals picker has a thumbnail and plays its proxy; a Blackmagic RAW file without a proxy says "no proxy yet".
- Kind: 2
- State: fixed, never shipped
- From: P18-024

### PRX-041: A proxy an editor made locally could be trashed by proxy downloads.
- What was going on: A proxy generated on the editor's own computer is not yet on the server, and downloading treats local files the server lacks as unwanted.
- What the product must do: A proxy an editor's computer made itself is never trashed or removed as a stray by proxy downloads or tidying.
- Kind: 3
- State: still open
- From: L10-085

## Pairing proxies with their originals

### PRX-042: Sony cameras' own proxies were reported as dozens of broken pairs.
- What was going on: Sony cameras record a small proxy named "<clip>S03.MP4" beside each clip; the owner: "ignore s03 as an exception, this will happen to a lot of users".
- What the product must do: Pairing also tries the name with known camera proxy suffixes removed, from an easily extended list; a file matching neither reading is still reported.
- Kind: 1a
- From: L04-026, M02-096, C03-059, P10-002

### PRX-043: A Mac leaves hidden "._" files beside everything it copies to the NAS.
- What was going on: macOS writes "._name" resource files and a folder-settings file beside files copied over a share; 22 were flagged as orphan proxies.
- What the product must do: Files whose names start with a dot are ignored by every check, count and pairing of media and proxies.
- Kind: 1a
- From: C03-060, L04-027

### PRX-044: A Blackmagic RAW metadata file left behind made moved footage look present.
- What was going on: BRAW clips carry a same-named metadata file; when footage moved without it, a name-only check paired that leftover with the old proxy.
- What the product must do: Pairing proxies with footage ignores camera metadata files, so footage that moved is detected even when its metadata file stayed.
- Kind: 1a
- From: L10-023

### PRX-045: Two originals with one name but different extensions shared a proxy.
- What was going on: Resolve matches proxies by name in the Proxy folder, so "A001.mov" and "A001.mp4" map to one proxy; one is never made, or two writers corrupt it.
- What the product must do: Two originals sharing a name in one folder never share or overwrite one proxy, and neither counts as covered by the other's.
- Kind: 3
- From: H01-053

### PRX-046: Proxies left behind after their originals moved raised a warning per file.
- What was going on: When originals moved, the old Proxy folder kept 56 orphaned proxies (6.7 GB), each raising its own warning.
- What the product must do: Leftover proxies whose originals moved are reported once per folder, with the originals' new location when it can be found.
- Kind: 3
- From: M02-095

## Writing, copying and deleting files safely

### PRX-047: Proxies still being written were sent to editors truncated, pass after pass.
- What was going on: Blackmagic Proxy Generator grows a proxy in place at its final name (203 MB over 933 s); Resolve renders into growing .tmp files and leaves .lock files.
- What the product must do: A file whose size or time is still changing, or a temporary, lock or partial file, never travels; it moves once it has been still for a set time.
- Kind: 1a
- From: C01-039, P03-020, P03-021

### PRX-048: Resolve keeps media and proxy files locked while a project is open.
- What was going on: Resolve holds attached files open without delete sharing; superseded proxies could not be removed, and a laptop showed 99 of 69 proxies and "tidying" for half an hour.
- What the product must do: A move or delete blocked by Resolve says "waiting for Resolve to close", finishes once it closes, and never inflates a count.
- Kind: 1a
- From: P02-023, G01-010, C01-033

### PRX-049: A rename blocked by Resolve left a temporary-named copy that got uploaded.
- What was going on: On Windows, Resolve holding a clip open blocks renaming it, so a failed case-only rename left the file under a temporary name.
- What the product must do: Temporary names used during a move are never uploaded by any route.
- Kind: 1a
- From: L06-089

### PRX-050: A delete on the NAS share reported success but the file was still there.
- What was going on: From Windows, deleting a file on the NAS share sometimes returned success while the file stayed, mostly files another program had just renamed.
- What the product must do: After deleting or replacing a file on the NAS share, the folder is re-listed and a file still present counts as a failed delete.
- Kind: 1a
- From: M06-001

### PRX-051: A copy inside the NAS share was slow, while a rename was instant.
- What was going on: Copying within the NAS share from Windows rewrites every byte on the NAS disks (190 to 450 MB/s), and a move across disks quietly becomes a copy.
- What the product must do: Moving within the NAS is a rename in place, never copy-then-delete; when a rename is impossible the move fails visibly.
- Kind: 1a
- From: P10-039, M06-007, M04-077

### PRX-052: A Synology's own SSH server cut every proxy over 514 MiB short.
- What was going on: A larger transfer-window setting made Synology's SSH server silently truncate large files while downloads reported success.
- What the product must do: Transfers to a Synology use settings it handles, larger ones are refused, and each transferred file's size is checked.
- Kind: 1a
- State: fixed, never shipped
- From: H07-118

### PRX-053: An interrupted copy left an empty or partial clip that spread to every editor.
- What was going on: A crash, quit or hiccup mid-copy left a zero-byte or partial file under the real name; it uploaded, and other tools counted half-written files.
- What the product must do: A copy appears under its final name only when complete, and any leftover partial or placeholder is cleaned up at next start and never synced.
- Kind: 3
- From: C01-015, H01-047, H07-070, P02-022

### PRX-054: During a multi-gigabyte copy the editor had no way to stop or skip.
- What was going on: The only control while copying media into a project was "stop after this file", so one huge file trapped the editor.
- What the product must do: During a copy the editor can skip the current file, cancel the batch, or stop after this file, and an aborted file leaves nothing behind.
- Kind: 3
- From: C01-018

### PRX-055: Files set aside on an editor's computer were deleted before the promised time.
- What was going on: Moved-out copies promised recoverable for a year were pruned after 14 days, or sooner under disk pressure.
- What the product must do: Anything set aside instead of deleted is kept at least as long as people are told, and never removed while the NAS lacks it.
- Kind: 3
- From: H06-005

## Moving footage through the product

### PRX-056: A file moved by hand on the NAS came back at its old path.
- What was going on: Uploads copy whatever the NAS lacks and never delete, so every computer still holding the old path re-uploads it; only staging, which no editor holds, is safe.
- What the product must do: A move through the product moves the file on the NAS and every holding computer, proxies included, nothing deleted, and the old path never uploads again.
- Kind: 3
- From: L01-037, C03-001, M02-091, P07-015, H04-001, L03-006, D07-046

### PRX-057: The move confirmation named no file or destination, and nothing could undo it.
- What was going on: A typo moved files everywhere behind a generic "move it?" prompt, and undo restored only the folder, losing the original name on every editor.
- What the product must do: The confirmation names file, source, destination and computer count; undo restores the original name and place everywhere unless a computer failed or the path is taken.
- Kind: 3
- From: L03-004, H04-076

### PRX-058: Renaming a file through the dashboard left its proxy under the old name.
- What was going on: The proxy was moved but kept its old name, so it no longer paired with the renamed original, and Resolve showed the moved clips without proxies.
- What the product must do: A moved or renamed file takes its proxy along under the matching new name, and Resolve shows both original and proxy online afterwards.
- Kind: 3
- From: H06-115, P05-062

### PRX-059: A move must never separate a clip from its proxy.
- What was going on: A move could carry an original into a project while its proxy stayed behind, or mark a clip filed before all its files had moved.
- What the product must do: A clip counts as moved only when all its files have moved; anything left behind is remembered and carried by the next move.
- Kind: 3
- From: C07-018

### PRX-060: A half-finished server move reported "nothing moved".
- What was going on: The original was renamed before the move was recorded, so a proxy that could not follow, or a crash, left files moved and no computer told.
- What the product must do: A move is recorded before it starts, a partial move names what stayed, and an interrupted move is completed or flagged on the next start.
- Kind: 3
- From: L02-074

### PRX-061: A failed project folder move was "finished" by adopting a proxy-only folder.
- What was going on: After a move failed, sync recreated the new path holding only proxies; the next pass took that as the moved folder and relinked Resolve to nothing.
- What the product must do: A blocked move completes only into the really moved folder; nothing creates the new path meanwhile, and a stray folder there never counts as the move.
- Kind: 3
- State: still open
- From: L10-040

### PRX-062: "Could not move this project's folder" stayed after the problem went away.
- What was going on: A blocked folder rename was cleared only by a later successful move, so undoing the rename or re-ticking left the warning forever.
- What the product must do: The message clears when the mismatch no longer exists, and the project is never shown as fine while its sync is still paused.
- Kind: 3
- From: H05-018

## Moves that reach every computer

### PRX-063: A laptop away for two weeks never heard about a move, then undid it.
- What was going on: Move instructions expired after 7 days, even while a computer answered "waiting for the sync drive", so a returning laptop re-uploaded the old path.
- What the product must do: A move waits for each computer however long it is offline or its drive is away; expiry measures only silence, on the server's clock.
- Kind: 3
- From: L03-003, H05-027, L05-080, L06-092, L07-046, H07-033

### PRX-064: A computer that could not follow a move later uploaded the file back.
- What was going on: A computer that failed to apply a move kept its copy at the old path, and a day later uploaded it back where the admin had cleared it.
- What the product must do: A failed move is retried, the old path never uploads meanwhile, and the admin sees per computer "still trying", "blocked", or red with an ask-again button.
- Kind: 3
- From: L03-002

### PRX-065: Moves were not announced to every computer holding the file.
- What was going on: Computers borrowing a shared folder were never told when a file moved out of it and re-uploaded it; others filed copies under projects they do not sync.
- What the product must do: A move reaches every computer holding the file, borrowers of a shared folder included, and each files its copy only where its own plan says.
- Kind: 3
- From: H06-009

### PRX-066: A computer working straight off the NAS was told to move a file again.
- What was going on: A wired computer's project tree is the NAS share itself, so the server's rename is the only one; telling it to move its copy moves the file twice.
- What the product must do: A file move is never sent to a computer that reads the project straight from the NAS, unless it reports holding a separate copy.
- Kind: 3
- From: L06-035

### PRX-067: Moving one folder sent the move to a computer holding a look-alike folder.
- What was going on: Path matching treated an underscore as a wildcard, so a folder name with an underscore matched one spelled with a hyphen.
- What the product must do: Paths are compared literally; underscores, percent signs and every other character match only themselves.
- Kind: 3
- From: L10-005

### PRX-068: Pending moves for a renamed or forgotten computer were never delivered or closed.
- What was going on: Commands stayed filed under a computer's old name; answers after a rename updated nothing, and a forgotten computer warned forever while its copy re-uploaded.
- What the product must do: Pending commands follow a computer through a rename, both delivery and answer, and are deleted with a computer the admin forgets.
- Kind: 3
- From: L09-024

### PRX-069: Two computers cloned from one disk could receive each other's commands.
- What was going on: A cloned disk carries one computer identity onto two live machines, and a Resolve undo meant for one would replay in the other's open project.
- What the product must do: A command reaches only its own computer; one filed under a former name is delivered only after that name goes quiet, never to a live twin.
- Kind: 3
- From: L09-025

## Following a move on an editor's computer

### PRX-070: A crash in the middle of a file move turned it into a permanent failure.
- What was going on: A kill between moving and recording left no record, so the redelivered move looked done or failed for good, or the missing-clip fixer copied the file back.
- What the product must do: A move interrupted at any point, by crash, reboot or update, finishes on the next attempt, is never reported done early, and nothing recreates the old path.
- Kind: 3
- From: L06-087, L07-027, H05-028, L05-081, L06-086

### PRX-071: Following a move binned camera originals that were never uploaded.
- What was going on: A local folder the computer did not sync was moved whole to the trash, including originals the NAS did not yet hold.
- What the product must do: No move or tidy removes a local file until the server is seen holding the same content at the same path and size.
- Kind: 3
- From: L10-043, C04-006, H08-026

### PRX-072: A computer with nothing ticked trashed every file it was told to move.
- What was going on: An empty or unreadable sync plan was read as "syncs nothing", so even moves inside one project sent a possibly only copy to the trash.
- What the product must do: An empty or unreadable plan means "cannot tell"; the local copy follows the move and is never trashed.
- Kind: 3
- From: H06-004, L09-032

### PRX-073: A move into a project this computer does not sync left an invisible orphan.
- What was going on: A computer not syncing the destination built the folder anyway, filling its disk; "moved" would be untrue and "failed" would send an admin hunting.
- What the product must do: Its copy goes to the recoverable bin, the history says it does not sync the destination, and the command is not sent again.
- Kind: 3
- From: L08-030, L09-034

### PRX-074: A file moved into a partly synced project sat in the bin for two weeks.
- What was going on: A computer syncing only some folders of a project treated a file moved into one of them as having no home there.
- What the product must do: A file moved into any folder this computer syncs, including folders of a partly synced project, is moved there locally.
- Kind: 3
- From: L08-029

## Relinking Resolve after a move

### PRX-075: A clip moved while its project was closed went offline days later.
- What was going on: Repointing after a move, or a project renamed on the server, touched only the project open at that moment, so clips elsewhere went offline unexplained.
- What the product must do: Every Resolve project using a moved file is relinked when it next opens, the editor is told, and an offline moved clip gets a one-click relink.
- Kind: 3
- From: L03-005, L04-110

### PRX-076: After following a move, Resolve stayed Media Offline while history said "followed".
- What was going on: The local copy was moved but Resolve kept the old paths; a later move notice found nothing to do, or a locked proxy, left the record wrong.
- What the product must do: A computer has followed a move only when its copy and proxy moved and every Resolve clip under it points at the new path.
- Kind: 3
- From: L08-028, H06-003

### PRX-077: A folder renamed by hand became hundreds of moves and left clips offline.
- What was going on: Renaming a folder counted one move per file, and where the sync had already carried the files, computers relinked nothing.
- What the product must do: A folder renamed or moved on the NAS is one move, and every clip under it is relinked in each editor's Resolve once the whole folder has arrived.
- Kind: 3
- From: L09-009

### PRX-078: A file in the trash was offered as the place to relink Resolve.
- What was going on: After a move put the local copy in the trash, "repoint Resolve to where it is now" left clips offline once the trash emptied.
- What the product must do: Resolve is never offered, or relinked to, a file in the trash.
- Kind: 3
- From: L09-033

## Moves made by hand on the NAS

### PRX-079: Every hand move on the NAS tripped the download safety stop.
- What was going on: The owner: "this happening every time I move something on the server is a major issue"; to every holding computer, a hand move looked like mass deletion.
- What the product must do: A file found elsewhere on the NAS with the same name and size is followed as moved and never counts as a deletion toward the safety stop.
- Kind: 3
- From: P10-063, L08-026, C02-069

### PRX-080: A file deleted on the NAS came back to its own path on every pass.
- What was going on: An out-of-date NAS listing still showed the deleted file, so "found elsewhere" named the very path it vanished from.
- What the product must do: A file's new home must differ from where it vanished, in a listing known current; found only at the old path, it is a deletion.
- Kind: 3
- From: L08-027, H06-001

### PRX-081: A copy into another project, original deleted later, looked exactly like a move.
- What was going on: Name, size and time survive a copy, so unrelated deletes and arrivals up to two days apart, in either order, were paired and applied fleet-wide.
- What the product must do: A hand move is applied unattended only when the file left one place and then arrived at exactly one other; weaker evidence waits for an admin.
- Kind: 3
- From: L09-008, H06-007, L10-007

### PRX-082: Many hand moves at once, or one big upload, switched off move detection.
- What was going on: Moves past 500 per scan, between projects scanned at different times, or after a 6,000-clip upload were dropped, then treated as deletions and re-uploaded.
- What the product must do: Every hand move is recognised however many there are and however scanning is split, or the admin is told exactly how many were not.
- Kind: 3
- From: H06-008, L09-007, L10-008

### PRX-083: When proxies are moved on the NAS, editors re-download them all.
- What was going on: A hand move of 214 proxies was mirrored as deletions plus fresh downloads on every editor's computer, over a slow uplink, for unchanged bytes.
- What the product must do: When proxies are only moved on the NAS, each editor's copies are moved locally, not trashed and fetched again.
- Kind: 3
- State: still open
- From: H04-002

### PRX-084: An answer's "as of" time showed the freshest project, not the data used.
- What was going on: A project whose NAS scan had failed for three days kept old data while answers about it were stamped fresh from another project's scan.
- What the product must do: Every answer built from scanned NAS data carries the time of the oldest scan that contributed to it.
- Kind: 3
- From: L09-027

## Names: letter case and Unicode

### PRX-085: Moved clips with accented names never relinked on a Mac.
- What was going on: macOS and Resolve on a Mac spell accented names decomposed, the NAS and Windows composed, so raw comparisons matched nothing and one project appeared twice.
- What the product must do: Every comparison of file or project names treats both Unicode spellings as equal, while disk operations use the exact bytes on disk.
- Kind: 1a
- From: H05-025, L06-095, L05-087, H04-073

### PRX-086: A Mac did not recognise its own moved file spelled with other capitals.
- What was going on: Windows and Mac volumes ignore letter case by default, though a Mac volume can be case-sensitive; Linux and the NAS always distinguish case.
- What the product must do: Path comparisons follow the real volume's case rule, and file operations use the path's own spelling.
- Kind: 1a
- From: C03-007, L01-070

### PRX-087: A rename that only changed letter case ended as two files.
- What was going on: The case-sensitive NAS saw a rename that editors' disks saw as done already; the proxy kept the old case, and the old spelling was uploaded back.
- What the product must do: A case-only file rename is applied on every computer with its proxy renamed to match; a case-only folder rename is refused with a sentence.
- Kind: 1a
- From: L05-086, H05-026, L06-088

### PRX-088: Clips with Chinese names were not found by the relink though on disk.
- What was going on: The file list was read in the wrong text encoding, so Chinese-named clips showed "no match" while the owner's own search found them.
- What the product must do: A clip with Chinese characters in its name is found and relinked exactly as one with an English name.
- Kind: 3
- From: P01-009

## Relinking and gathering missing clips

### PRX-089: Fixing a project would duplicate 100 GB that was already in the tree.
- What was going on: 107 interview clips pointed at an editor's former drive while the same files sat in the project tree, and the fix could only copy.
- What the product must do: When a missing clip's file exists in the tree with the same name and size, the person is offered a relink to it, never a copy.
- Kind: 3
- State: still open
- From: M02-028, P02-018

### PRX-090: When several copies of a missing clip exist, the largest is the right one.
- What was going on: The owner ruled "1.mov should be the largest": same-named duplicates were full-resolution files beside proxies, and backups were byte-identical across drives.
- What the product must do: Among same-named candidates the largest file, the original, beats a proxy, and identical backups do not count as a conflict.
- Kind: 2
- From: P01-008

### PRX-091: Uncertain relink matches are reviewed one by one before anything changes.
- What was going on: The owner asked for near-match handling "with a UI which foregrounds all the information and allows things to be selected, viewed".
- What the product must do: A fuzzy or ambiguous match is never applied silently; the person sees each candidate's path, size and a preview and picks before relinking.
- Kind: 2
- From: P01-010

### PRX-092: Clips with known copies stayed offline because their drive was unplugged.
- What was going on: The drive holding the copies was disconnected when the relink ran, and nothing said so.
- What the product must do: When a clip cannot be relinked because the drive holding its copy is unreachable, the result says that drive is offline.
- Kind: 3
- State: outcome not found
- From: P01-031

### PRX-093: A blank "what still needs uploading" was not taken as "nothing to do".
- What was going on: Before gathering a project the upload check came back blank, and the app rightly refused to offer the copy.
- What the product must do: Any check that returns no data is treated as failed and named to the person, never as an empty to-do list.
- Kind: 3
- From: P02-019

### PRX-094: Fixing must cover the whole project and gather its stray media.
- What was going on: Fixing covered only the timeline, and a pre-existing project had originals on an editor's disk outside the project tree.
- What the product must do: A person can scan the whole project, and out-of-tree media is moved into the project folder on that computer and then uploaded.
- Kind: 2
- From: P02-016

### PRX-095: Gathering a project failed on a remote editor's computer only.
- What was going on: Gathering a pre-existing project errored on a remote editor's machine while the same build worked on the owner's computer.
- What the product must do: Gathering behaves the same on every computer, and a failure names the file and the reason.
- Kind: 3
- State: outcome not found
- From: P02-017

### PRX-096: Music files in AAC were filed as b-roll instead of music.
- What was going on: Stray clips were sorted by extension and the audio list lacked .aac and .opus, so 30 licensed music tracks landed in a b-roll folder.
- What the product must do: .aac, .opus and every other common audio type are filed as audio when stray clips are copied into the tree.
- Kind: 3
- From: P13-009, M02-027

### PRX-097: A project backup gathers only media used in chosen timelines, with proxies.
- What was going on: The owner wanted a backup copying exactly the clips used in selected timelines, plus their proxies and a project export, with visible progress.
- What the product must do: A backup copies only media used in the chosen timelines plus their proxies and a project file, showing free space first and live progress.
- Kind: 2
- From: P01-032

### PRX-098: A new project gets the studio's folder template without disturbing what exists.
- What was going on: The owner wanted the standard folders laid down at project start, including on folders already holding interviewee footage.
- What the product must do: Creating or adopting a project adds missing template folders and never moves, renames or overwrites a folder or file already there.
- Kind: 2
- From: P02-003

## Sealed

### PRX-S01: The open-source encoder cannot make proxies from BRAW, R3D or Canon RAW.
- What was going on: The encoder cannot decode these camera raw formats at any quality, so those clips stayed without proxies.
- What the product must do: Raw clips missing proxies are reported and handed to a tool that reads them, never queued for this encoder.
- Kind: 1b
- Tool: ffmpeg (no BRAW, R3D or CRM decoding)
- From: C01-072, L03-073

### PRX-S02: An overnight run of 1,040 proxies produced none.
- What was going on: The encoder picks its output format from the file extension, and a temporary ".partial" name gave it none, so all 6,290 attempts failed at start.
- What the product must do: Every encode names its output format explicitly whatever the temporary file is called, and a failure records the encoder's first error lines.
- Kind: 1b
- Tool: ffmpeg
- From: C01-077, M02-040

### PRX-S03: Encode progress stuck at 0 percent, or the encoder hung.
- What was going on: The progress field named in milliseconds holds microseconds, and an unread progress pipe fills at about 64 KB and blocks the encoder for good.
- What the product must do: Progress shows a true percentage, is updated at most once a second, and asking for it never stalls an encode.
- Kind: 1b
- Tool: ffmpeg -progress (out_time_ms holds microseconds, like out_time_us)
- From: G01-026, C01-078

### PRX-S04: A machine listed a GPU encoder it could not use.
- What was going on: The encoder lists NVIDIA's hardware encoder on a machine with no GPU, and a 64x64 test encode fails even on a real RTX 3080.
- What the product must do: Hardware encoding is used only after a real one-frame 320x240 test encode has succeeded on that machine.
- Kind: 1b
- Tool: ffmpeg with NVIDIA's hardware encoder (nvenc)
- From: M02-045

## Removed
