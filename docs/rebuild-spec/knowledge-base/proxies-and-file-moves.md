# Proxies and file moves: what real use taught

97 lessons. Each is one rule the product can be tested against: what a person saw (the heading), why it happened, and what the product must do. Kinds: *given* is a fact about something the studio has whatever is built; *ruling* is the owner's decision; *situation* is something the product must survive.

## Making proxies on editors' computers

### PRX-030: Missing proxies are made only while the computer is idle.
- Why: Clips without proxies never reach remote editors; the owner wants gaps reported and filled on editors' own computers without getting in their way.
- Must: Proxy making starts after 5 minutes without input, treats unknown idleness as busy, stops within seconds of input and discards its partial file.
- Kind: ruling

### PRX-031: Proxy making uses the whole computer while idle, but backs off for Resolve.
- Why: The owner: idle proxy making "can absolutely max out compute", "unless yeah the computer is doing a render or something else".
- Must: An idle computer encodes several proxies in parallel, dropping to one whenever Resolve is open or rendering, even on a forced run; each computer can override.
- Kind: ruling

### PRX-033: A person can see which proxies were made, live progress and time left.
- Why: The owner wanted "a place to track what proxies it made, progress"; with only a rotating log, a long run looked identical to a stuck app.
- Must: The app shows the clip being encoded with its length and percent, a queue estimate, and a made-and-failed history that survives a restart.
- Kind: ruling

### PRX-040: The originals picker showed no picture and could not play a clip.
- Why: The owner: "there's no thumbnail or preview in the bring originals here dialogue".
- Must: Each file in the originals picker has a thumbnail and plays its proxy; a Blackmagic RAW file without a proxy says "no proxy yet".
- Kind: ruling

### APP-147: Background encoding at normal priority slowed Resolve's own render.
- Why: Three normal-priority encoders took the processor; dropping them to below normal raised Resolve's output from about 100 to 144 MB/s.
- Must: The product's encoding on an editor's computer runs below normal priority so Resolve keeps its speed.
- Kind: situation

### PRX-032: Proxy making could fill the disk or encode a file still being copied.
- Why: No free-space floor, one modified-time look judged a copy finished though copiers stamp it at start and end, and proxies of proxies were made.
- Must: Proxy making keeps at least 20 GB or 5 percent free, waits for two equal size-and-time samples, and never encodes proxy-folder, partial or its own files.
- Kind: situation

### PRX-034: A machine made zero proxies overnight while showing a full queue.
- Why: About 1,040 clips were queued and none were made, every encode failing, and nothing told the owner.
- Must: A pass that ends with none made and some failed shows that failure plainly on that pass.
- Kind: situation

### PRX-035: The retry and stop buttons for proxy making did not do what they said.
- Why: "Make the missing proxies now" kept the failure limit, so nothing retried, and a stale Stop pressed when nothing ran cancelled the next run's queue.
- Must: A manual retry retries every failed clip now, and Stop stops only work running at that moment.
- Kind: situation

### PRX-036: Failed clips filled the proxy queue, so 540 makeable clips were never made.
- Why: Only the newest 500 clips per project were looked at, and once all had hit the failure limit the machine reported nothing to do.
- Must: Clips that failed never crowd out clips that can still be made; a machine idles only when nothing makeable remains.
- Kind: situation

### PRX-037: Proxy making stopped for low space and only the admin could see why.
- Why: Proxy making paused for low disk, a retry limit or a truncated list, and only the dashboard showed it.
- Must: Every reason proxy making is held back is told to the editor at that computer in a sentence, naming any clip given up on.
- Kind: situation

### PRX-038: Originals with no proxy were invisible to every editor, and nothing said so.
- Why: Only proxies travel down to editors, so an original without one never reaches anyone; one machine had 1,046 such clips.
- Must: Originals lacking a proxy are counted per project and shown on the editor's computer and on the dashboard.
- Kind: situation

### PRX-039: A new project said "0 originals" for up to 45 minutes.
- Why: New projects were counted in a slow rotation, so views showed 0 originals, an empty picker, and "43/0" beside people.
- Must: A new project is counted within about a minute, and until then every view says "counting", never 0.
- Kind: situation

### PRX-041: A proxy an editor made locally could be trashed by proxy downloads.
- Why: A proxy generated on the editor's own computer is not yet on the server, and downloading treats local files the server lacks as unwanted.
- Must: A proxy an editor's computer made itself is never trashed or removed as a stray by proxy downloads or tidying.
- Kind: situation

## What Resolve accepts as a proxy

### PRX-001: Resolve linked a proxy on its own when it sat in a Proxy folder.
- Why: On plain import Resolve links a same-named file in a Proxy subfolder beside the original; its own "Generate Proxy Media" writes to a separate cache folder instead.
- Must: Proxies sit in a Proxy folder beside their originals under matching names, and editors are told to set Proxy Handling to Prefer Proxies.
- Kind: given

### PRX-002: A proxy one character off in its name never attached in Resolve.
- Why: Resolve pairs proxies by exact file name; a synced name that differed in one fullwidth punctuation mark (？ ：) left the clip without its proxy.
- Must: Every file reaches the other side with a byte-identical name, Chinese and fullwidth punctuation included, in both directions.
- Kind: given

### PRX-003: Resolve refused a proxy whose timecode differed from its original's.
- Why: Resolve validates a pairing on embedded start timecode; a proxy without the camera's timecode starts at 00:00:00:00 and is refused despite matching rate, frame count and duration.
- Must: Every proxy carries its original's start timecode, or none when the original has none, and a link counts as done only when Resolve accepts it.
- Kind: given

### PRX-004: Sony footage at 29.97 or 59.94 got proxies Resolve refused on drop-frame form.
- Why: Sony metadata prints drop-frame timecode in colon (non-drop) form; same digits in the two forms are different frames, and a rewrite can silently flip a file's drop-frame flag.
- Must: A proxy's timecode names the same frame in the same drop-frame form Resolve reads from the original, verified on the value and form written and by Resolve accepting it.
- Kind: given

### PRX-005: Resolve refused proxies only one or two frames short.
- Why: Resolve rejects a proxy whose frame count differs from the original's by even one frame, though it plays fine; a check with two frames of slack let them through.
- Must: Every proxy, from any producer, has exactly the original's frame count for constant-frame-rate footage, or is refused and remade.
- Kind: given

### PRX-006: Phone footage has no exact frame count for a proxy to match.
- Why: Variable-frame-rate sources, such as phones, failed a strict frame-count equality, which failed the whole ingest item.
- Must: The proxy length check accepts variable-frame-rate sources by a rule suited to them and never fails a whole ingest over it.
- Kind: given

### PRX-007: A video file's stated frame count and duration differ from its real frames.
- Why: Header frame counts are often missing or wrong, and duration can include audio running past the last picture frame.
- Must: A clip's length for proxies or offline placeholders comes from counted picture frames, read at most once per file version, never from header figures.
- Kind: given

### PRX-008: HEVC proxies played everywhere except Resolve, which showed Media Offline.
- Why: Resolve and QuickTime refuse HEVC in MP4 tagged "hev1" (VLC plays it), and common encoders write "hev1" by default.
- Must: Every HEVC-in-MP4 proxy is tagged "hvc1", verified by opening it in Resolve.
- Kind: given

### PRX-009: Proxies kept only the first audio track of multi-track camera files.
- Why: Camera originals routinely carry two or more audio streams (channel pairs, scratch plus lav), and a proxy made with default settings keeps only one.
- Must: A proxy carries every audio track of its original, in the same order.
- Kind: given

### PRX-010: "Sync stuck" was really Resolve refusing proxies a few frames short.
- Why: Every file had synced, but 7 proxies were 1 to 18 frames short and another covered 1,238 of 3,741 seconds, so Resolve would not link them.
- Must: A proxy whose frame count differs from its original is named to the editor and on the dashboard as a proxy fault, not a sync stall, and remade.
- Kind: situation

### PRX-011: Refused proxies were re-offered every two minutes, 1,357 times.
- Why: Real refusals were retried for days, while a link that failed only because Resolve had closed was stored as a permanent refusal.
- Must: Only a real refusal is remembered, per file version, and shown once; a failure because Resolve is closed is retried later.
- Kind: situation

### PRX-012: The editor could not tell why Resolve would not use their proxies.
- Why: Resolve refuses a proxy with mismatched timecode and will not play an unreadable proxy even when the link is right.
- Must: The editor sees how many proxies Resolve refused, the first such clip, and the likely cause in plain words.
- Kind: situation

### PRX-013: A half-finished proxy check would have relinked 1,300 clips nobody asked for.
- Why: When proxy details were not fetched, every clip read as "no proxy" and would have received an unrequested relink.
- Must: "Could not find out" is never treated as "no proxy"; an incomplete answer about a project's clips is discarded, not acted on.
- Kind: situation

## What a proxy must be

### PRX-014: Blackmagic Proxy Generator only sees proxies saved as .mov.
- Why: The owner: "blackmagic proxy generator cannot see proxies in any other format", so .mp4 proxies were invisible to it, while browsers need .mp4 previews.
- Must: Proxies made for Resolve are .mov files; previews played in a browser stay .mp4.
- Kind: given

### PRX-015: Proxies travel over the internet, so they must be small.
- Why: The owner wants proxies compressed about as much as Blackmagic's generator output: at most 1080p, H.264 around 2.5 Mbps, never larger than the original.
- Must: Every proxy is at most 1080p, averages no more than about 2.5 Mbps, is never larger than its original, and sits where Resolve links it.
- Kind: ruling

### PRX-016: Proxies with a LUT burned in are useless and are set aside.
- Why: The owner had all of one camera's proxies quarantined: "they're useless because they have the lut on".
- Must: A proxy with a look burned in is never linked as an editing proxy; it is set aside, not deleted.
- Kind: ruling

### PRX-017: Proxies for odd-height screen recordings failed and were given up on.
- Why: Some sources (screen captures, full-colour or lossless video) have an odd pixel width or height, and video encoders refuse odd dimensions.
- Must: A source with an odd width or height still gets a proxy, rounded to even dimensions.
- Kind: situation

### PRX-018: 10 of 244 generated previews were corrupt despite correct metadata.
- Why: An encode can destroy the picture while duration and size look right, or stop early with no error; checking a 10-second sample missed 2 of 10.
- Must: Every proxy or preview is fully decoded and its duration compared with the source before use, and failures are remade.
- Kind: situation

### PRX-019: Proxies of multi-hour clips were encoded, then thrown away by a too-short check.
- Why: The decode check of a finished proxy had a fixed 30-minute limit, and a multi-hour proxy checked over the network takes longer.
- Must: Every time limit on making or checking a proxy grows with the clip's length, and finished work is never discarded for a limit alone.
- Kind: situation

### PRX-020: Proxy making failed again and again on camera originals truncated on the NAS.
- Why: Two originals on the NAS were incomplete, missing the index at the end of the file, so every proxy attempt failed.
- Must: An original that cannot be read to its end is reported as damaged with its path, not retried forever.
- Kind: situation

## Raw camera formats and Blackmagic Proxy Generator

### PRX-021: Blackmagic RAW, RED and Canon raw clips sat without proxies for months.
- Why: General-purpose encoders cannot decode .braw, .r3d or .crm; the owner: re-encoding them "will require bm proxy generator".
- Must: Raw clips are counted, routed to a decoder that reads them, started without the editor's help, verified like any proxy, and never failed as broken.
- Kind: given

### PRX-022: Blackmagic Proxy Generator is Resolve started with a flag.
- Why: Its shortcut runs Resolve with "-pg", so only the command line tells it from the editor; it watches folders listed in its own settings.
- Must: The generator is told from Resolve by its command line, the user's own watch folders are never removed, and it is never killed mid-run.
- Kind: given

### PRX-023: Blackmagic Proxy Generator silently did nothing, then duplicated existing proxies.
- Why: It opens idle until Start is pressed, does nothing with an empty watch list, rewrites its settings on exit, and re-encoded 172 clips proxied under another name.
- Must: Its watch folders are set only while it is closed, it is running before work counts as handed over, and it never re-encodes clips already proxied.
- Kind: given

### PRX-024: A Chinese-named watch folder in Proxy Generator was garbled and never watched.
- Why: Blackmagic Proxy Generator reads its settings file as Latin-1 and writes non-ASCII back as its own escape codes; raw UTF-8 was garbled and re-added every launch.
- Must: A watch folder with Chinese or accented characters shows correctly in the generator, is watched, and is never added twice.
- Kind: given

### PRX-025: Proxy Generator has no settings folder until its own first run.
- Why: Its preferences folder is created by its first launch, not by the Resolve installer, so waiting for that folder means it never launches.
- Must: On any machine with Resolve installed, the product can set up and launch the proxy generator even if it was never opened.
- Kind: given

### PRX-026: Raw proxies and other proxies fought over one graphics card.
- Why: Raw clips go to Resolve's own generator while other clips are encoded by the product, and both want the same GPU.
- Must: Raw clips' proxy run starts only once every other clip's proxy is made, so two proxy jobs never compete for one GPU.
- Kind: given

### PRX-027: 148 ordinary clips were sent to the external proxy generator.
- Why: Clips that were not raw went to Blackmagic's generator; the owner said they "should have just been done by" the product's own proxy maker.
- Must: Clips the product can decode get proxies from its own encoder; only formats it cannot decode, such as Blackmagic RAW, go elsewhere.
- Kind: ruling

### PRX-028: A "please click Start" for the proxy generator went only to a log.
- Why: When the app could not press Start in the generator on the editor's screen, the request was logged and nobody saw it.
- Must: When an automated step needs a person to act, that person is told on their computer, and the request clears once done.
- Kind: situation

### PRX-029: The proxy generator stalled on one file and failed others with no reason.
- Why: The owner twice saw Blackmagic Proxy Generator stall on a file or report failure, with no reason shown to him.
- Must: When a project's proxies cannot be made, the editor is told which file failed and why, instead of a stuck progress line.
- Kind: situation

## Pairing proxies with their originals

### PRX-042: Sony cameras' own proxies were reported as dozens of broken pairs.
- Why: Sony cameras record a small proxy named "<clip>S03.MP4" beside each clip; the owner: "ignore s03 as an exception, this will happen to a lot of users".
- Must: Pairing also tries the name with known camera proxy suffixes removed, from an easily extended list; a file matching neither reading is still reported.
- Kind: given

### PRX-043: A Mac leaves hidden "._" files beside everything it copies to the NAS.
- Why: macOS writes "._name" resource files and a folder-settings file beside files copied over a share; 22 were flagged as orphan proxies.
- Must: Files whose names start with a dot are ignored by every check, count and pairing of media and proxies.
- Kind: given

### PRX-044: A Blackmagic RAW metadata file left behind made moved footage look present.
- Why: BRAW clips carry a same-named metadata file; when footage moved without it, a name-only check paired that leftover with the old proxy.
- Must: Pairing proxies with footage ignores camera metadata files, so footage that moved is detected even when its metadata file stayed.
- Kind: given

### PRX-045: Two originals with one name but different extensions shared a proxy.
- Why: Resolve matches proxies by name in the Proxy folder, so "A001.mov" and "A001.mp4" map to one proxy; one is never made, or two writers corrupt it.
- Must: Two originals sharing a name in one folder never share or overwrite one proxy, and neither counts as covered by the other's.
- Kind: situation

### PRX-046: Proxies left behind after their originals moved raised a warning per file.
- Why: When originals moved, the old Proxy folder kept 56 orphaned proxies (6.7 GB), each raising its own warning.
- Must: Leftover proxies whose originals moved are reported once per folder, with the originals' new location when it can be found.
- Kind: situation

## Writing, copying and deleting files safely

### PRX-047: Proxies still being written were sent to editors truncated, pass after pass.
- Why: Blackmagic Proxy Generator grows a proxy in place at its final name (203 MB over 933 s); Resolve renders into growing .tmp files and leaves .lock files.
- Must: A file whose size or time is still changing, or a temporary, lock or partial file, never travels; it moves once it has been still for a set time.
- Kind: given

### PRX-048: Resolve keeps media and proxy files locked while a project is open.
- Why: Resolve holds attached files open without delete sharing; superseded proxies could not be removed, and a laptop showed 99 of 69 proxies and "tidying" for half an hour.
- Must: A move or delete blocked by Resolve says "waiting for Resolve to close", finishes once it closes, and never inflates a count.
- Kind: given

### PRX-049: A rename blocked by Resolve left a temporary-named copy that got uploaded.
- Why: On Windows, Resolve holding a clip open blocks renaming it, so a failed case-only rename left the file under a temporary name.
- Must: Temporary names used during a move are never uploaded by any route.
- Kind: given

### PRX-050: A delete on the NAS share reported success but the file was still there.
- Why: From Windows, deleting a file on the NAS share sometimes returned success while the file stayed, mostly files another program had just renamed.
- Must: After deleting or replacing a file on the NAS share, the folder is re-listed and a file still present counts as a failed delete.
- Kind: given

### PRX-051: A copy inside the NAS share was slow, while a rename was instant.
- Why: Copying within the NAS share from Windows rewrites every byte on the NAS disks (190 to 450 MB/s), and a move across disks quietly becomes a copy.
- Must: Moving within the NAS is a rename in place, never copy-then-delete; when a rename is impossible the move fails visibly.
- Kind: given

### PRX-053: An interrupted copy left an empty or partial clip that spread to every editor.
- Why: A crash, quit or hiccup mid-copy left a zero-byte or partial file under the real name; it uploaded, and other tools counted half-written files.
- Must: A copy appears under its final name only when complete, and any leftover partial or placeholder is cleaned up at next start and never synced.
- Kind: situation

### PRX-054: During a multi-gigabyte copy the editor had no way to stop or skip.
- Why: The only control while copying media into a project was "stop after this file", so one huge file trapped the editor.
- Must: During a copy the editor can skip the current file, cancel the batch, or stop after this file, and an aborted file leaves nothing behind.
- Kind: situation

### PRX-055: Files set aside on an editor's computer were deleted before the promised time.
- Why: Moved-out copies promised recoverable for a year were pruned after 14 days, or sooner under disk pressure.
- Must: Anything set aside instead of deleted is kept at least as long as people are told, and never removed while the NAS lacks it.
- Kind: situation

See also, filed under another capability:

- SYN-133 (Sync): Synology's built-in secure file transfer silently cut proxies over 514 MiB short.

## Moving footage through the product

### PRX-056: A file moved by hand on the NAS came back at its old path.
- Why: Uploads copy whatever the NAS lacks and never delete, so every computer still holding the old path re-uploads it; only staging, which no editor holds, is safe.
- Must: A move through the product moves the file on the NAS and every holding computer, proxies included, nothing deleted, and the old path never uploads again.
- Kind: situation

### PRX-057: The move confirmation named no file or destination, and nothing could undo it.
- Why: A typo moved files everywhere behind a generic "move it?" prompt, and undo restored only the folder, losing the original name on every editor.
- Must: The confirmation names file, source, destination and computer count; undo restores the original name and place everywhere unless a computer failed or the path is taken.
- Kind: situation

### PRX-058: Renaming a file through the dashboard left its proxy under the old name.
- Why: The proxy was moved but kept its old name, so it no longer paired with the renamed original, and Resolve showed the moved clips without proxies.
- Must: A moved or renamed file takes its proxy along under the matching new name, and Resolve shows both original and proxy online afterwards.
- Kind: situation

### PRX-059: A move must never separate a clip from its proxy.
- Why: A move could carry an original into a project while its proxy stayed behind, or mark a clip filed before all its files had moved.
- Must: A clip counts as moved only when all its files have moved; anything left behind is remembered and carried by the next move.
- Kind: situation

### PRX-060: A half-finished server move reported "nothing moved".
- Why: The original was renamed before the move was recorded, so a proxy that could not follow, or a crash, left files moved and no computer told.
- Must: A move is recorded before it starts, a partial move names what stayed, and an interrupted move is completed or flagged on the next start.
- Kind: situation

### PRX-061: A failed project folder move was "finished" by adopting a proxy-only folder.
- Why: After a move failed, sync recreated the new path holding only proxies; the next pass took that as the moved folder and relinked Resolve to nothing.
- Must: A blocked move completes only into the really moved folder; nothing creates the new path meanwhile, and a stray folder there never counts as the move.
- Kind: situation

### PRX-062: "Could not move this project's folder" stayed after the problem went away.
- Why: A blocked folder rename was cleared only by a later successful move, so undoing the rename or re-ticking left the warning forever.
- Must: The message clears when the mismatch no longer exists, and the project is never shown as fine while its sync is still paused.
- Kind: situation

## Moves that reach every computer

### PRX-063: A laptop away for two weeks never heard about a move, then undid it.
- Why: Move instructions expired after 7 days, even while a computer answered "waiting for the sync drive", so a returning laptop re-uploaded the old path.
- Must: A move waits for each computer however long it is offline or its drive is away; expiry measures only silence, on the server's clock.
- Kind: situation

### PRX-064: A computer that could not follow a move later uploaded the file back.
- Why: A computer that failed to apply a move kept its copy at the old path, and a day later uploaded it back where the admin had cleared it.
- Must: A failed move is retried, the old path never uploads meanwhile, and the admin sees per computer "still trying", "blocked", or red with an ask-again button.
- Kind: situation

### PRX-065: Moves were not announced to every computer holding the file.
- Why: Computers borrowing a shared folder were never told when a file moved out of it and re-uploaded it; others filed copies under projects they do not sync.
- Must: A move reaches every computer holding the file, borrowers of a shared folder included, and each files its copy only where its own plan says.
- Kind: situation

### PRX-066: A computer working straight off the NAS was told to move a file again.
- Why: A wired computer's project tree is the NAS share itself, so the server's rename is the only one; telling it to move its copy moves the file twice.
- Must: A file move is never sent to a computer that reads the project straight from the NAS, unless it reports holding a separate copy.
- Kind: situation

### PRX-067: Moving one folder sent the move to a computer holding a look-alike folder.
- Why: Path matching treated an underscore as a wildcard, so a folder name with an underscore matched one spelled with a hyphen.
- Must: Paths are compared literally; underscores, percent signs and every other character match only themselves.
- Kind: situation

### PRX-068: Pending moves for a renamed or forgotten computer were never delivered or closed.
- Why: Commands stayed filed under a computer's old name; answers after a rename updated nothing, and a forgotten computer warned forever while its copy re-uploaded.
- Must: Pending commands follow a computer through a rename, both delivery and answer, and are deleted with a computer the admin forgets.
- Kind: situation

### PRX-069: Two computers cloned from one disk could receive each other's commands.
- Why: A cloned disk carries one computer identity onto two live machines, and a Resolve undo meant for one would replay in the other's open project.
- Must: A command reaches only its own computer; one filed under a former name is delivered only after that name goes quiet, never to a live twin.
- Kind: situation

## Following a move on an editor's computer

### PRX-070: A crash in the middle of a file move turned it into a permanent failure.
- Why: A kill between moving and recording left no record, so the redelivered move looked done or failed for good, or the missing-clip fixer copied the file back.
- Must: A move interrupted at any point, by crash, reboot or update, finishes on the next attempt, is never reported done early, and nothing recreates the old path.
- Kind: situation

### PRX-071: Following a move binned camera originals that were never uploaded.
- Why: A local folder the computer did not sync was moved whole to the trash, including originals the NAS did not yet hold.
- Must: No move or tidy removes a local file until the server is seen holding the same content at the same path and size.
- Kind: situation

### PRX-072: A computer with nothing ticked trashed every file it was told to move.
- Why: An empty or unreadable sync plan was read as "syncs nothing", so even moves inside one project sent a possibly only copy to the trash.
- Must: An empty or unreadable plan means "cannot tell"; the local copy follows the move and is never trashed.
- Kind: situation

### PRX-073: A move into a project this computer does not sync left an invisible orphan.
- Why: A computer not syncing the destination built the folder anyway, filling its disk; "moved" would be untrue and "failed" would send an admin hunting.
- Must: Its copy goes to the recoverable bin, the history says it does not sync the destination, and the command is not sent again.
- Kind: situation

### PRX-074: A file moved into a partly synced project sat in the bin for two weeks.
- Why: A computer syncing only some folders of a project treated a file moved into one of them as having no home there.
- Must: A file moved into any folder this computer syncs, including folders of a partly synced project, is moved there locally.
- Kind: situation

## Relinking Resolve after a move

### PRX-075: A clip moved while its project was closed went offline days later.
- Why: Repointing after a move, or a project renamed on the server, touched only the project open at that moment, so clips elsewhere went offline unexplained.
- Must: Every Resolve project using a moved file is relinked when it next opens, the editor is told, and an offline moved clip gets a one-click relink.
- Kind: situation

### PRX-076: After following a move, Resolve stayed Media Offline while history said "followed".
- Why: The local copy was moved but Resolve kept the old paths; a later move notice found nothing to do, or a locked proxy, left the record wrong.
- Must: A computer has followed a move only when its copy and proxy moved and every Resolve clip under it points at the new path.
- Kind: situation

### PRX-077: A folder renamed by hand became hundreds of moves and left clips offline.
- Why: Renaming a folder counted one move per file, and where the sync had already carried the files, computers relinked nothing.
- Must: A folder renamed or moved on the NAS is one move, and every clip under it is relinked in each editor's Resolve once the whole folder has arrived.
- Kind: situation

See also, filed under another capability:

- RSV-097 (Resolve on the editor's computer): The editor was offered a one-click relink into the product's own trash.

## Moves made by hand on the NAS

### PRX-079: Every hand move on the NAS tripped the download safety stop.
- Why: The owner: "this happening every time I move something on the server is a major issue"; to every holding computer, a hand move looked like mass deletion.
- Must: A file found elsewhere on the NAS with the same name and size is followed as moved and never counts as a deletion toward the safety stop.
- Kind: situation

### PRX-080: A file deleted on the NAS came back to its own path on every pass.
- Why: An out-of-date NAS listing still showed the deleted file, so "found elsewhere" named the very path it vanished from.
- Must: A file's new home must differ from where it vanished, in a listing known current; found only at the old path, it is a deletion.
- Kind: situation

### PRX-081: A copy into another project, original deleted later, looked exactly like a move.
- Why: Name, size and time survive a copy, so unrelated deletes and arrivals up to two days apart, in either order, were paired and applied fleet-wide.
- Must: A hand move is applied unattended only when the file left one place and then arrived at exactly one other; weaker evidence waits for an admin.
- Kind: situation

### PRX-082: Many hand moves at once, or one big upload, switched off move detection.
- Why: Moves past 500 per scan, between projects scanned at different times, or after a 6,000-clip upload were dropped, then treated as deletions and re-uploaded.
- Must: Every hand move is recognised however many there are and however scanning is split, or the admin is told exactly how many were not.
- Kind: situation

### PRX-083: When proxies are moved on the NAS, editors re-download them all.
- Why: A hand move of 214 proxies was mirrored as deletions plus fresh downloads on every editor's computer, over a slow uplink, for unchanged bytes.
- Must: When proxies are only moved on the NAS, each editor's copies are moved locally, not trashed and fetched again.
- Kind: situation

### PRX-084: An answer's "as of" time showed the freshest project, not the data used.
- Why: A project whose NAS scan had failed for three days kept old data while answers about it were stamped fresh from another project's scan.
- Must: Every answer built from scanned NAS data carries the time of the oldest scan that contributed to it.
- Kind: situation

## Names: letter case and Unicode

### PRX-085: Moved clips with accented names never relinked on a Mac.
- Why: macOS and Resolve on a Mac spell accented names decomposed, the NAS and Windows composed, so raw comparisons matched nothing and one project appeared twice.
- Must: Every comparison of file or project names treats both Unicode spellings as equal, while disk operations use the exact bytes on disk.
- Kind: given

### PRX-086: A Mac did not recognise its own moved file spelled with other capitals.
- Why: Windows and Mac volumes ignore letter case by default, though a Mac volume can be case-sensitive; Linux and the NAS always distinguish case.
- Must: Path comparisons follow the real volume's case rule, and file operations use the path's own spelling.
- Kind: given

### PRX-087: A rename that only changed letter case ended as two files.
- Why: The case-sensitive NAS saw a rename that editors' disks saw as done already; the proxy kept the old case, and the old spelling was uploaded back.
- Must: A case-only file rename is applied on every computer with its proxy renamed to match; a case-only folder rename is refused with a sentence.
- Kind: given

### PRX-088: Clips with Chinese names were not found by the relink though on disk.
- Why: The file list was read in the wrong text encoding, so Chinese-named clips showed "no match" while the owner's own search found them.
- Must: A clip with Chinese characters in its name is found and relinked exactly as one with an English name.
- Kind: situation

## Relinking and gathering missing clips

### PRX-090: When several copies of a missing clip exist, the largest is the right one.
- Why: The owner ruled "1.mov should be the largest": same-named duplicates were full-resolution files beside proxies, and backups were byte-identical across drives.
- Must: Among same-named candidates the closest matching folder path wins; only when that leaves a tie does the largest file, the original, beat a proxy; identical backups are no conflict.
- Kind: ruling

### PRX-091: Uncertain relink matches are reviewed one by one before anything changes.
- Why: The owner asked for near-match handling "with a UI which foregrounds all the information and allows things to be selected, viewed".
- Must: A fuzzy or ambiguous match is never applied silently; the person sees each candidate's path, size and a preview and picks before relinking.
- Kind: ruling

### PRX-094: Fixing must cover the whole project and gather its stray media.
- Why: Fixing covered only the timeline, and a pre-existing project had originals on an editor's disk outside the project tree.
- Must: A person can scan the whole project, and out-of-tree media is moved into the project folder on that computer and then uploaded.
- Kind: ruling

### PRX-097: A project backup gathers only media used in chosen timelines, with proxies.
- Why: The owner wanted a backup copying exactly the clips used in selected timelines, plus their proxies and a project export, with visible progress.
- Must: A backup copies only media used in the chosen timelines plus their proxies and a project file, showing free space first and live progress.
- Kind: ruling

### PRX-098: A new project gets the studio's folder template without disturbing what exists.
- Why: The owner wanted the standard folders laid down at project start, including on folders already holding interviewee footage.
- Must: Creating or adopting a project adds missing template folders and never moves, renames or overwrites a folder or file already there.
- Kind: ruling

### PRX-089: Fixing a project would duplicate 100 GB that was already in the tree.
- Why: 107 interview clips pointed at an editor's former drive while the same files sat in the project tree, and the fix could only copy.
- Must: When a missing clip's file exists in the tree with the same name and size, the person is offered a relink to it, never a copy.
- Kind: situation

### PRX-092: Clips with known copies stayed offline because their drive was unplugged.
- Why: The drive holding the copies was disconnected when the relink ran, and nothing said so.
- Must: When a clip cannot be relinked because the drive holding its copy is unreachable, the result says that drive is offline.
- Kind: situation

### PRX-093: A blank "what still needs uploading" was not taken as "nothing to do".
- Why: Before gathering a project the upload check came back blank, and the app rightly refused to offer the copy.
- Must: Any check that returns no data is treated as failed and named to the person, never as an empty to-do list.
- Kind: situation

### PRX-095: Gathering a project failed on a remote editor's computer only.
- Why: Gathering a pre-existing project errored on a remote editor's machine while the same build worked on the owner's computer.
- Must: Gathering behaves the same on every computer, and a failure names the file and the reason.
- Kind: situation

### PRX-096: Music files in AAC were filed as b-roll instead of music.
- Why: Stray clips were sorted by extension and the audio list lacked .aac and .opus, so 30 licensed music tracks landed in a b-roll folder.
- Must: .aac, .opus and every other common audio type are filed as audio when stray clips are copied into the tree.
- Kind: situation
