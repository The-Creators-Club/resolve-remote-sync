# The b-roll archive: what real use taught

134 lessons. Each is one rule the product can be tested against: what a person saw (the heading), why it happened, and what the product must do. Kinds: *given* is a fact about something the studio has whatever is built; *ruling* is the owner's decision; *situation* is something the product must survive.

## Givens: browsers, cameras, files and Resolve

### BRO-001: Previews of 10-bit camera footage played as black rectangles in browsers.
- Why: Sony FX3 and FX30 record 10-bit; a 10-bit H.264 preview plays black where the browser decodes in hardware (3,467 of 7,110 archive previews were affected).
- Must: Every browser preview, poster and still is 8-bit 4:2:0 whatever the source, and plays in Chrome, Edge and Safari; Resolve editing proxies may stay 10-bit.
- Kind: given

### BRO-002: A browser preview with keyframes far apart seeks slowly.
- Why: Previews and proxies with one keyframe every two seconds made seeking in the browser sluggish.
- Must: Browser previews and proxies carry one keyframe per second, so a seek lands quickly.
- Kind: given

### BRO-003: Resolve refused every 29.97 preview after a camera's timecode was rewritten.
- Why: A colon in a file's timecode track is genuine non-drop-frame; Sony's own metadata colon is read as drop-frame; only files with no timecode track need guessing.
- Must: Timecode from a file's timecode track is kept as written; only a file with none gets its drop-frame form decided from its frame rate.
- Kind: given

### BRO-004: A video file's declared frame count can be wrong.
- Why: An MP4 from an encoder killed partway still declares the frame count it intended; trusted, it made offline clips the wrong length on every remote computer.
- Must: A declared frame count is used only when duration times frame rate agrees within one frame plus 1%; otherwise the length is treated as unknown.
- Kind: given

### BRO-005: Videos with no readable duration crashed processing with a cryptic error.
- Why: Raw video streams, some MPEG-TS files and recordings still being written report no duration at all.
- Must: A file with no duration is set aside with a plain reason, never crashed on and never published.
- Kind: given

### BRO-006: Dropping a folder of over 100 clips in Chrome silently lost the rest.
- Why: Chrome hands a dropped folder's contents over 100 entries per read and empties the drop after the first pause; drag highlights flicker per element crossed.
- Must: Dropping a folder of any size onto a page brings in every file in it, and the drop highlight stays steady while dragging.
- Kind: given

### BRO-007: A 4 GB upload with no progress bar looked like a hung page.
- Why: The browser's newer request method cannot report upload progress, and browsers cannot preview camera raw or MXF files, so a drop showed nothing for minutes.
- Must: Every file uploading from a page shows its progress, and a file the browser cannot preview says so until a thumbnail arrives.
- Kind: given

### BRO-008: Refusing an upload part-way lost the reason the browser was given.
- Why: A server that answers a refusal without reading the rest of the upload resets the connection, and the browser sees only a network error.
- Must: When an upload is refused (no space, no permission), the person sees the reason, not a network error.
- Kind: given

### BRO-009: The page said the local app was not running when Chrome had blocked it.
- Why: Chrome's local-network permission can block a plain-http page from calling the app on this computer, and that looks identical to nothing listening.
- Must: A page that cannot reach the local app never claims it is not running; it names both possibilities and offers a one-click self-test.
- Kind: given

### BRO-011: Changing a folder name's capitals made the whole folder be indexed again.
- Why: Windows drives and NAS shares treat "Youtube" and "YouTube" as one folder, but an exclusion rule compared letter case exactly.
- Must: Path comparisons follow each volume's own case rule: editors' Windows and Mac disks ignore case, the NAS itself does not, so a capitals-only rename there is a real rename.
- Kind: given

### BRO-012: Two archive names differing only in case land in one folder.
- Why: Windows and macOS treat file names that differ only in letter case as the same name.
- Must: Archive names are compared without case, and a new name matching an existing one apart from case is refused or renamed.
- Kind: given

### BRO-013: Two clips with the same camera name in one batch became one.
- Why: Cameras restart numbering per card, so two cards hold the same clip name under the same card path; matching by name and folder indexed one twice and lost the other.
- Must: Every ingested file is tracked by its own identity, and two different same-named files in one batch both arrive and are indexed, in b-roll and music alike.
- Kind: given

### BRO-014: Resolve's own smart search data cannot be reused to describe b-roll.
- Why: Resolve stores IntelliSearch results as 768-number vectors per shot, with no captions or tags, so nothing readable can be lifted from them.
- Must: B-roll descriptions are produced by the product itself and never depend on Resolve's IntelliSearch data.
- Kind: given

### BRO-015: An overseas client downloaded at 2 MB/s from a 39 MB/s studio uplink.
- Why: Taiwan to US round trips of 130-200 ms hold one connection to about 0.3 MB/s; eight connections gave 4.1 MB/s.
- Must: Client downloads resume after interruption, allow several parallel connections, and every request is logged durably with address, file and bytes.
- Kind: given

See also, filed under another capability:

- SYN-066 (Sync): A Mac spells accented file names differently, so held files looked missing forever.

## How the archive is laid out

### BRO-016: The archive is browsed as folders, downloaded and own-shoot clips apart.
- Why: The owner wanted a folder browser with "the downloaded b-roll in a root folder 'Downloads' and all our custom b-roll in a separate root folder".
- Must: B-roll search has a folder tree with separate roots for downloaded and own-shoot clips, listing every clip in a chosen folder.
- Kind: ruling

### BRO-017: Own-shoot footage files under its project's name with every shoot subfolder kept.
- Why: The owner: footage goes "into their origin folders" and "we should maintain the subfolders"; editors find own footage by shoot, day and camera, and a project code means nothing.
- Must: Own-shoot footage files under the project's spoken name with the shoot's folders shown to any depth; a later rename moves, never recopies; footage timelines use is never re-filed.
- Kind: ruling

### BRO-018: Own-shoot b-roll enters the archive as high-quality proxies, shots under 5 minutes.
- Why: The owner: "I only want to keep high quality proxies of this footage on the nas, I don't want the originals", and "ignore any shot which is longer than 5 minutes."
- Must: The archive copy can be a high-quality proxy, indexed like an original and renderable in timelines without the camera original; a shot of 5 minutes or more never enters.
- Kind: ruling

### BRO-019: The archive records where every clip's original lives.
- Why: Originals sit on backup drives and in download folders; the owner asked to "store the locations of all the originals ... so we can keep track".
- Must: Every archive clip, downloaded or own-shoot, carries the location of its original.
- Kind: ruling

### BRO-020: Own-shoot b-roll is filed without full indexing or speech-to-text.
- Why: The owner did not want own-shoot clips fully indexed ("random chatter", no real audio), but they must be in folders, perhaps lightly indexed.
- Must: Own-shoot clips are sorted into folders without transcription, with full indexing optional later and never ruled out.
- Kind: ruling

### BRO-021: Every clip sits in one broad category, described by subject, format and place.
- Why: The owner wanted "useful category folders, not minute categories that fit only one or two videos".
- Must: Every archive clip sits in one broad category folder, none left uncategorised, with subject, format and place shown as descriptions.
- Kind: ruling

### BRO-022: A categorised clip never moves and no category is ever deleted.
- Why: The owner: "clips once categorised should not move between them. No categorised should be deleted, only new categorised created."
- Must: Re-indexing never moves a categorised clip or removes a category; it may only add new categories.
- Kind: ruling

### BRO-023: Interviewee footage was filed under wrong subjects by guessing from the picture.
- Why: The owner: a clip inside an interviewee's folder is that interviewee's b-roll; guessing from the picture mislabelled 1,463 such clips.
- Must: A clip inside an interviewee's folder is classed as that interviewee's b-roll from the folder alone; no clip outside one gets that class from its content.
- Kind: ruling

### BRO-025: Editors' old proxy folders are kept and copied, never indexed.
- Why: Old project folders held about 2,100 proxies that existing Resolve projects link to; at about 47 MB a minute they are ten times too big for search previews.
- Must: Proxy folders are skipped by indexing but kept at their linked paths when copied to the NAS, and search previews are made from originals.
- Kind: ruling

### BRO-026: Duplicate videos are indexed once and copied once.
- Why: The owner wanted byte-identical duplicates flagged and skipped, in indexing and in the copy to the NAS; 246 files, 41 GB, were duplicates.
- Must: A file identical to one already indexed is flagged, not indexed again, and left out of the archive copy.
- Kind: ruling

### BRO-027: Zero-byte files all looked like duplicates of one random clip.
- Why: Every empty file hashes alike, so duplicate detection piled five unrelated failed downloads onto one arbitrary clip.
- Must: Zero-byte files are flagged as broken downloads and never treated as duplicates of anything.
- Kind: situation

### BRO-028: Indexing starts where clips are and survives their move onto the NAS.
- Why: The archive was spread over many drives for days before the NAS was ready; the owner wanted indexing to begin anyway and follow the files.
- Must: Clips indexed in their old locations keep their index entries after being copied onto the NAS, with nothing indexed twice.
- Kind: situation

### BRO-029: Two editors adding files at once could both claim one archive name.
- Why: Two editors dropping cards at once, or two music files named theme.wav, could each take the same name and overwrite a clip already in a timeline.
- Must: Archive and music library names are assigned in one place, never twice, so a file added by one editor never overwrites another's.
- Kind: situation

### BRO-030: A published archive file was overwritten with different footage already in timelines.
- Why: Archive file names were worked out afresh each run, so a new clip with the same title took the plain name and shifted the others.
- Must: Once a clip's archive path is published it never changes, and a file at a published path is never overwritten with another clip's footage.
- Kind: situation

### BRO-031: A repair tool could re-encode archive originals over themselves.
- Why: Pointed at an original, the preview repair shrank it in place, and archive rebuilds comparing size only restored broken files over repairs.
- Must: Nothing writes over an original, recorded repairs survive rebuilds, and anything replaced is kept aside.
- Kind: situation

## Describing and indexing clips

### BRO-032: B-roll is described on the studio's own graphics card, Good or Best.
- Why: The owner chose local describing (about 10-16 s a clip against 69 s hosted, cheaper, and judged better), with a smaller and a larger model chosen by graphics memory.
- Must: A new install describes b-roll locally by default, offering "Good" and "Best" whose tooltips state the video memory each needs, and the customer picks.
- Kind: ruling

### BRO-033: Describing beats proxy making, runs now or when idle, and checks graphics memory.
- Why: The owner ruled both jobs want the one graphics card and the editor is waiting on the describing; a model too big for the card must be refused visibly.
- Must: Proxy making waits while describing runs, saying why; each batch runs now or when idle; an unfit model is never downloaded and its refusal shows the memory figure to editor and admins.
- Kind: ruling

### BRO-034: Indexing used up the assistant allowance and needed a cap and a stop time.
- Why: Indexing reached 27% of the weekly allowance in an hour; the owner asked for a limit and to "let ongoing videos complete after 4pm before stopping".
- Must: Indexing shows the allowance spent; at the owner's limit or stop time it starts nothing new but lets every clip already started finish and be saved.
- Kind: ruling

### BRO-035: Background indexing must leave the computer usable while it runs.
- Why: The owner asked that the b-roll processing run use at most 60% of the computer so he could keep working.
- Must: Background indexing on a working computer stays under the owner's set share of its capacity, 60% by default.
- Kind: ruling

### BRO-036: Clip descriptions are nouns only, with on-screen text kept.
- Why: The owner asked for "nouns only", which halved the median description from 36 to 18 words; on-screen captions are often the best detail.
- Must: Clip descriptions are terse noun phrases and always include readable on-screen text.
- Kind: ruling

### BRO-037: Most searches were answerable from speech before any visual indexing.
- Why: Transcripts alone met 19 of 20 test queries; only purely visual ones, like "aerial drone shot of coastline", needed frame descriptions.
- Must: Speech search works as soon as clips are transcribed, without waiting for visual indexing.
- Kind: situation

### BRO-038: Audio-only archive files were never transcribed, so search never found them.
- Why: A file with no picture is rightly skipped for visual indexing, and the same skip kept it from transcription; a three-hour take skipped for length was transcribed anyway.
- Must: Audio-only archive files are transcribed and searchable by speech; a clip skipped for length or with no readable duration is never transcribed or analysed.
- Kind: situation

### BRO-039: Turning indexing back on for a share left its prepared clips invisible.
- Why: Clips of a share set to "do not index" rest prepared, and one way of starting indexing never looked at them again.
- Must: When a share is switched to indexed, every clip already prepared for it is picked up by the next run, however it is started.
- Kind: situation

### BRO-040: Re-indexing a clip left old search data that hid its real content.
- Why: Earlier search entries stayed behind, and cached results kept being served when the row count did not change.
- Must: Re-indexing a clip replaces all its earlier search data, and search reflects the change at once.
- Kind: situation

### BRO-041: One setup mistake marked all 2,000 queued clips as failed.
- Why: Failures from configuration, rate limits, credit or sign-in hit every clip alike, but were treated as one clip's problem, so the run marched through the queue failing each.
- Must: A failure that would hit every item stops or pauses the run with one clear message and leaves the queue waiting; only clip-specific failures mark a clip failed.
- Kind: situation

### BRO-042: A camera file named C0429.MP4 stopped overnight indexing as if rate-limited.
- Why: Error text was searched for "429", which camera file names, clip numbers and progress counters routinely contain.
- Must: A rate limit is recognised only from the service's own reply; any other failure marks that clip failed, names the cause, and the queue moves on.
- Kind: situation

### BRO-043: A stalled indexing run looked healthy for eight hours.
- Why: Output appeared only at exit, times were UTC not local, a partial run reported success, and "queued, heartbeat 3 hours ago" really meant the computer had stopped answering.
- Must: Runs show live progress in local time as sentences that age, flag no progress within minutes, and report success only when every queued item is done.
- Kind: situation

### BRO-044: Long indexing runs died with their window, a crash or an update reboot.
- Why: Batches run for hours; the starting window closes, the app is updated or crashes, and Windows reboots for updates outside active hours.
- Must: Long runs outlive the window that started them, survive a reboot, and resume each item at the step it reached without redoing finished work.
- Kind: situation

### BRO-045: A second copy of the local describing model stayed in video memory.
- Why: When the running model was slow to answer a health check, a replacement was started without stopping the old one.
- Must: At most one local model holds the graphics card at a time, the old one is stopped before a replacement starts, and all are released when the editor returns.
- Kind: situation

### BRO-046: A failed clip showed "error" with no message.
- Why: The error text sent with a failed clip was dropped on the way to the server.
- Must: A failed clip always shows why it failed, and a later plain rescan never blanks that message.
- Kind: situation

### BRO-047: A briefly busy archive database threw away finished local describing work.
- Why: Parts of the server answered a busy database with a plain error, and the editor's app treated any error as final, discarding minutes of analysis.
- Must: A momentarily busy server answers "busy, try again" everywhere, and clients retry that answer instead of discarding completed work.
- Kind: situation

### BRO-048: Ten minutes after asking for the describing model the page still said "no model".
- Why: The 3.3 GB model download crawled on one stuck connection while the page showed a raw status word.
- Must: A model download shows percent, rate and time left on the page and in the editor's app, and recovers from a stalled connection.
- Kind: situation

## Search

### BRO-049: A search shows when its subject appears and sends that range to Resolve.
- Why: The owner wanted "navy ship" to show every clip at the times ships appear, then an in and out point inserted into the open Resolve.
- Must: A result shows the times its subject appears; the person sets in and out and inserts exactly that range into Resolve.
- Kind: ruling

### BRO-050: Search results are thumbnails only, with no text under them.
- Why: The owner ruled text under each result "just distracts from looking at the results".
- Must: Search results show only thumbnails; titles and buttons appear only when a clip is opened.
- Kind: ruling

### BRO-051: A search can be limited to what is seen or to what is said.
- Why: The owner: "I need a way to search only visuals or only transcript".
- Must: A search can be restricted to picture descriptions or to the spoken transcript, and the results say which was searched.
- Kind: ruling

### BRO-052: Searching "wind farm" showed a talking head instead of the matching frame.
- Why: The owner calls the matching thumbnail "a feature we explicitly built out"; long clips get coarser preview strips than the page assumed, and hover showed wrong frames on 95% of clips.
- Must: Each result's thumbnail and hover-scrub show the frame where the query matched, for clips of any length and any preview spacing, old or new.
- Kind: ruling

### BRO-053: Opening a search result lands on the matching moment.
- Why: Clicking a found video started at its beginning; the owner said it "should auto jump me to the section of the video which I searched for".
- Must: Opening a search result starts playback at the moment that matched, not at the clip's start.
- Kind: ruling

### BRO-070: Browser Back left b-roll for the dashboard, and an opened clip hid its video.
- Why: The search kept its views in one page state, and an opened clip showed empty space until the editor scrolled to the video.
- Must: Back walks through the search's own views (results, folder, clip) before leaving, and an opened clip shows its video without scrolling.
- Kind: ruling

### BRO-054: A clip sometimes opened two minutes in, at an earlier clip's hit.
- Why: A pending jump from a clip whose preview never loaded was applied to the next clip opened.
- Must: A clip opens at its own start or its own search hit, never at a point belonging to a clip opened earlier.
- Kind: situation

### BRO-055: The typo "ambluance" became "Blu" and "mars" matched "marriage".
- Why: A loose similarity score treats a short string as a perfect match for anything containing it, and stem prefix search widened short terms.
- Must: Spelling suggestions are whole words of similar length, and a search term under five letters never matches unrelated words sharing its stem.
- Kind: situation

### BRO-056: Two-character Chinese words, and the other script's spelling, found nothing.
- Why: Chinese has no spaces; plain word search needs three characters of an unbroken run, and Traditional and Simplified forms differ.
- Must: Searching 堵車, its Simplified form, or 同志伴侶 finds clips whose speech or text holds those words in either script, as soon as they are indexed.
- Kind: situation

### BRO-057: Chinese and Japanese queries returned nothing in meaning-based search.
- Why: A guard meant for mixed-language queries discarded every meaning-based hit for any mostly non-Latin query.
- Must: A Chinese, Japanese or other non-Latin query returns matching clips in every search mode where an equivalent English query does.
- Kind: situation

### BRO-058: Searches for names absent from the archive returned 15 to 17 unrelated videos.
- Why: Meaning-based scores cannot tell absent from present; an absent Chinese name scored 0.88, above every genuine cross-language match (best 0.74).
- Must: A query with no word match returns at most a few clips labelled related, none for a Chinese query, and an empty result stays possible.
- Kind: situation

### BRO-059: Meaning-based search could return nothing for ever without saying why.
- Why: When the model behind meaning-based search was missing or mismatched, every query returned nothing with no sign anywhere.
- Must: A search mode the server cannot run is disabled with its reason; the default mixed mode is never disabled and says what it lost.
- Kind: situation

### BRO-060: A common-word search sent about 1 MB for 24 results and felt slow remotely.
- Why: Each search returned every matching passage of every result, up to 193 per clip, and rebuilt its typo data on every query.
- Must: One page of results answers within about a second over a remote link, even for very common or misspelt words.
- Kind: situation

### BRO-061: Older search results replaced newer ones on screen.
- Why: A slow earlier answer could arrive last and overwrite the latest search's results, in b-roll and music.
- Must: The results on screen always belong to the most recent search or filter the person made.
- Kind: situation

### BRO-062: A search that found nothing showed a blank page.
- Why: An empty result gave no hint of what was searched or which filters narrowed it.
- Must: An empty result names the query, the scope and how many clips were searched, and offers to clear only the filters actually on.
- Kind: situation

### BRO-063: Each proxied shoot clip showed twice, once as a blank card.
- Why: Camera originals that had proxies were listed beside their own proxies, as cards with no preview.
- Must: A clip with a proxy appears once in browse and search, with its preview.
- Kind: situation

### BRO-064: Clips marked as duplicates came up in search with black previews and failing sends.
- Why: The duplicate copy kept its descriptions, so search found it, but it had no archive file.
- Must: A clip marked as a duplicate never appears in search results or folder counts; only the kept copy does.
- Kind: situation

### BRO-065: The search homepage was full of broken or "no preview" thumbnails.
- Why: Clips reached the shared archive without their stills and hover strips, so search had nothing to show.
- Must: A clip appears in search only once its media, still and preview strip are all in the archive; a missing one shows a placeholder saying so.
- Kind: situation

### BRO-066: A clip could show another clip's preview still.
- Why: Stills were keyed by a number that a clip added from an editor's computer and a clip added in bulk could share.
- Must: Each clip's preview still belongs to that clip alone and can never collide with another clip's.
- Kind: situation

### BRO-067: Clicking a folder in a clip's path must show exactly that folder.
- Why: A loose match would also catch "B-roll Archive" for "B-roll", and a folder named like "100%_Real" would select everything.
- Must: A folder filter matches that exact folder and below and treats every character literally.
- Kind: situation

### BRO-068: Combined filters left an empty grid the clear button could not escape.
- Why: A breadcrumb folder, a tree folder, a category and an earlier query combined silently, and a filter control rendered blank depending on how a folder was reached.
- Must: Every active filter is named and clearable, a new folder or category replaces the old one, and a folder shows the same controls however it was reached.
- Kind: situation

### BRO-069: Folder counts did not match what clicking the folder showed.
- Why: Counts and clicks used different matching rules and different sets of clips, and some results shown could not be previewed.
- Must: A folder's count equals the results clicking it shows, and every result shown can be previewed or says why not.
- Kind: situation

## The clip player

### BRO-071: A preview is scrubbed by hovering its thumbnail or dragging its playhead.
- Why: The owner wanted to "scrub the playhead by dragging" and to scrub a result by hovering it; dragging was jerky or did nothing.
- Must: Hovering a result scrubs its preview, and dragging a clip's playhead scrubs the video smoothly without falling behind the pointer.
- Kind: ruling

### BRO-072: The stretches of a clip that match the search are marked on its seek bar.
- Why: The owner wanted relevant stretches highlighted; the existing markers ran off the end of the bar.
- Must: The seek bar highlights each stretch matching the search, and no marker draws beyond either end of the bar.
- Kind: ruling

### BRO-073: Pressing I showed nothing until O was set.
- Why: The owner wanted a red in-point line; a fresh in point sits exactly under the white playhead, which drew over it.
- Must: In and out points show at once as red lines on the seek bar, drawn above the playhead.
- Kind: ruling

### BRO-074: Pressing Enter on a focused button could append a clip to the live timeline.
- Why: The clip view captured Enter and Space for its own shortcut, even on focused buttons and in drawers open over it.
- Must: Keyboard shortcuts never override a focused button or field, and nothing reaches Resolve without the editor meaning to send it.
- Kind: situation

## Previews made for the archive

### BRO-075: Re-encoded previews came out at 95% of their source's size.
- Why: High-resolution settings barely shrink already-compressed downloads, and editors' proxies are ten times too big for web previews.
- Must: Web previews are 540p, never upscaled, much smaller than the source, and made from originals rather than editors' proxies.
- Kind: situation

### BRO-076: A 16-minute clip's preview sheet was too large to build.
- Why: A fixed frame interval asked for a 490-frame sheet, beyond what the encoder accepts; 1.8-hour clips need far more.
- Must: Preview frame spacing widens with clip length so any clip, hours long included, gets a preview of bounded size.
- Kind: situation

### BRO-077: Camera mis-taps under a second long failed preview making.
- Why: Clips of 0.07-0.5 s yielded no frame for a preview sheet sampling one frame every two seconds.
- Must: A clip shorter than the sampling interval gets a preview from its first frame, or is skipped with a stated reason.
- Kind: situation

### BRO-078: Long clips lost their proxies on computers without a hardware encoder.
- Why: Encodes had a fixed 15-minute limit, so a ten-minute clip encoded in software timed out and lost its proxy or the whole item.
- Must: Encode time limits scale with clip length and the computer's speed, and a timeout is reported as a timeout, not a bad file.
- Kind: situation

### BRO-079: An editing proxy a few frames short failed the whole clip.
- Why: Resolve refuses proxies even 1 to 18 frames short, but a failed optional editing proxy also discarded the preview, stills and original upload.
- Must: An editing proxy failing its exact frame check is dropped with a stated reason, and the clip still goes live with its preview.
- Kind: situation

### BRO-080: A clip went live with an empty preview from a killed transfer.
- Why: A zero-byte file passed the upload check because no declared size existed to compare against.
- Must: A zero-byte file is never accepted as an uploaded file, whether or not a size was declared.
- Kind: situation

### BRO-081: Copying 85 GB of previews to the NAS over 10GbE took far longer than minutes.
- Why: The owner expected about 85 GB over a 10 gigabit link to take a few minutes; many small preview files ran much longer.
- Must: A bulk copy to the NAS shows progress and speed, and moves many small files at close to the link's capacity.
- Kind: situation

## Bringing new footage in

### BRO-082: B-roll is dropped on the dashboard and described on the dropper's computer.
- Why: The owner specified: drop clips or folders on the dashboard, preview them, pick settings, run; that computer converts and describes; results reach the shared archive on their own.
- Must: Dropped clips and folders are previewed and described on the dropper's computer, with progress there and on the dashboard; admins see every describing computer; results publish automatically.
- Kind: ruling

### BRO-083: A 200 GB card drop filled the editor's drive mid-batch.
- Why: Camera originals reach 40 GB; the drop capped clip count, not size, checked space after accepting bytes, and a cut-off file could be used as the whole clip.
- Must: A drop larger than free space minus 20 GB is refused whole; over 50 GB asks first with size and hours; skipped non-video files are counted; only complete files are used.
- Kind: situation

### BRO-084: Rescanning a share, or dropping in one song, re-read gigabytes over the network.
- Why: Rescans re-read 16 MB of every known file (about 25 minutes per share), and each music drop read the whole 9.5 GB library.
- Must: Checking for new, changed or duplicate files reads only files whose size or date changed, never the whole already-known library.
- Kind: situation

### BRO-085: Dropped clips sat at "uploading" for ever after a cancel, restart or failed upload.
- Why: A cancelled batch, a restart mid-batch, a failed upload or a computer gone after a cancel left clips never live nor failed, holding their names, and every new drop was refused.
- Must: Every dropped clip ends live, failed or cancelled within bounded time, a stuck batch never blocks new drops, and a cancelled batch frees the names it held.
- Kind: situation

### BRO-086: A clip whose camera card was pulled before upload froze the whole batch.
- Why: An original missing at upload was never sent nor failed, so the batch never finished, the computer refused later drops, and its previews reached the archive orphaned.
- Must: An import checks every file a clip needs before uploading any; a clip whose original vanished fails alone with a reason, uploads nothing, and the batch finishes.
- Kind: situation

### BRO-087: A clip went live undescribed when the server refused its description.
- Why: The app uploaded the clip and marked it done anyway, so it was live, unsearchable and never described again.
- Must: A clip never goes live without its stored description; a refused description is retried, and after the retry budget the clip fails visibly.
- Kind: situation

### BRO-088: An upload the server refused for good stayed "uploading" for ever.
- Why: Only two server answers were handled; every other refusal, permanent ones included, was re-sent silently with no attempt count.
- Must: Every upload answer is classed as done, retry later with a limit, or failed for good with the server's own sentence, shown to the editor and retryable.
- Kind: situation

### BRO-089: A NAS outage during an upload used up the file's retries.
- Why: Counting "NAS unreachable" as a failed attempt lets a short outage exhaust a file's retries and abandon it.
- Must: While the NAS is unreachable, uploads wait and resume, and only failures with the NAS reachable count against a file.
- Kind: situation

### BRO-090: One wifi blip at 95% of a 4 GB upload lost that clip for good.
- Why: A failed upload in a 200-clip drop was skipped for ever; the only way back was clearing and re-dropping everything.
- Must: Network failures retry three times (2, 4, 8 s), then offer retry per item and for all; a stall is two minutes without progress, never a total time limit.
- Kind: situation

### BRO-091: One unexpected error stopped every later upload or download on that computer.
- Why: An escaping error left the upload worker marked busy for good, and a download that never started read "downloading 0%" for ever.
- Must: An unexpected error fails only the item it hit, with its text, and work carries on; a transfer that never started reports failed.
- Kind: situation

### BRO-092: Quitting or cancelling an import left the encoder running and the file locked.
- Why: A running decode carried on up to 15 minutes after cancel or quit and held the staged file, so cleanup failed on Windows.
- Must: Quit or cancel stops any running encode within seconds, including one started during shutdown, and no half-written output reaches the archive.
- Kind: situation

### BRO-093: New b-roll stayed invisible until its multi-GB originals finished uploading.
- Why: A day of 6K material was hidden for the eight hours its originals took; a batch can also be cancelled after some clips were cut into timelines.
- Must: A clip appears once its preview and proxies are uploaded, before its original; cancelling a batch removes only clips whose media never arrived.
- Kind: situation

### BRO-094: A clip went live while its original failed to upload, and nobody knew.
- Why: Clips publish once previews arrive; a later failure of the original was recorded nowhere, the batch said done, and no retry could reach it.
- Must: A clip whose original is still owed shows so, ends its batch "with errors", can be retried, and the editor's local copy is kept meanwhile.
- Kind: situation

### BRO-095: A batch read "40 clips, 38 indexed" with no explanation.
- Why: Duplicates the editor unticked were left out of the batch record instead of recorded as skipped.
- Must: Every clip dropped appears in its batch with an outcome, including "skipped, duplicate of" the kept clip, so counts always add up.
- Kind: situation

### BRO-096: Failed and waiting imports could be seen only by dropping another file.
- Why: Failed items never retried, and re-dropping made duplicates.
- Must: An editor can open the import list directly, see waiting items and failures with reasons, and retry one so it keeps its archive slot with no duplicate.
- Kind: situation

### BRO-097: "Try the failed clips again" said "12 clips queued" while nothing ran.
- Why: The retry named items and the staged drop wrongly, so the editor's computer answered zero retried or failed every clip in seconds with the files still staged.
- Must: A retry reruns failed clips from the files this computer staged, refuses with a reason if it cannot tell which drop, and says running only once a computer took it.
- Kind: situation

### BRO-098: Retrying failed items took a batch from the computer still working on it.
- Why: Retry reset a running batch to queued, so the working computer was cut off and the editor's second computer could claim the same clips.
- Must: A retry is refused while a computer still holds the batch, naming that computer; an abandoned batch can still be retried.
- Kind: situation

### BRO-099: A batch whose computer went away could be finished by no one.
- Why: The editor's other computer could not pick it up, though a notice said it could.
- Must: An editor sees their unfinished batches and can take one over on this computer, unless another computer holds a live claim.
- Kind: situation

### BRO-100: A refused retry falsely said another computer would pick it up.
- Why: The page discarded the editor's computer's real reason, invented one, showed success green and watched a run that did not exist.
- Must: When the editor's computer refuses work, its own sentence is shown as a warning, and the page never shows a run that did not start.
- Kind: situation

### BRO-101: When the app on this computer was not running, the page blamed it for refusing.
- Why: A failed connection, or an app too old for the request, was shown as the app's refusal, hiding the advice to use the computer holding the files.
- Must: The page tells "the app on this computer did not answer" and "the app is too old" apart from a real refusal, keeping the next-step advice.
- Kind: situation

### BRO-102: Staged import copies filled the editor's disk, and clearing them broke live drops.
- Why: Staged copies stayed for ever in a hidden folder, the space message pointed at a button that freed nothing, and clearing deleted drops still uploading.
- Must: Staging is released once nothing is owed and expires 7 days after its last bytes; unfinished drops are never cleared; editors can remove unwanted drops; space messages name actions that work.
- Kind: situation

### BRO-103: The computer that made an editing proxy downloaded it back from the NAS.
- Why: The importing computer left its editing proxy in staging, so it re-downloaded hundreds of MB it had just uploaded.
- Must: A computer never downloads a file it produced and still holds.
- Kind: situation

### BRO-104: A web page could make the editor's app upload any file on the computer.
- Why: A blank library location was treated as the whole disk, and the drop request accepted any local path.
- Must: The editor's app imports, reveals or uploads only files inside a configured library location or picked by the editor; a blank location means not configured.
- Kind: situation

## Sending a clip to Resolve

### BRO-105: A remote editor picks b-roll, it lands in the timeline, and the proxy follows.
- Why: The owner said the archive "is mainly for remote editors": open search, insert a clip into the timeline, and receive its proxy.
- Must: Inserting an archive clip from search on a remote editor's computer places it in Resolve and brings its proxy down with no other step.
- Kind: ruling

### BRO-106: Send to Resolve on a remote computer failed with "file not found".
- Why: Remote editors do not hold the archive or music library; the owner: sync it down to the matching path under the local tree.
- Must: Sending a clip or track the computer lacks fetches just it to the matching local path with visible progress, then imports it, b-roll into an archive bin.
- Kind: ruling

### BRO-107: A heavy clip sent to Resolve remotely arrives in seconds, then upgrades.
- Why: The owner: it "should still only sync the proxy down, and leave the reference to [the archive]"; previews were "too low quality" to keep, and originals are relinked from backups for export.
- Must: A remote insert gives a usable preview within seconds, upgrades to the editing proxy unprompted, keeps pointing at the archive original, and never reports that absent original as missing.
- Kind: ruling

### BRO-108: A clip used from the archive stays there, never copied into the project.
- Why: The owner ruled a clip "stays in the b-roll archive root, and doesn't get copied into the project directory", avoiding duplicates on the NAS.
- Must: Using an archive clip never copies it into a project; the archive's own folder layout is what comes down to the editor.
- Kind: ruling

### BRO-110: Resolve was given the search preview where the editing proxy belonged.
- Why: The owner: "why are we remaking proxies ... when we already have proxies?"; on computers holding the original, every insert still attached the 540p preview as proxy.
- Must: An existing editing proxy is reused, a missing one is made at editing quality, and Resolve is never given the browser preview as a clip's proxy.
- Kind: ruling

### BRO-111: Send to Resolve offers both append and place on top.
- Why: Sending could only append; the owner asked for "both 'append' and 'place on top'".
- Must: The person chooses between appending the clip at the timeline's end and placing it on a track above, at the playhead.
- Kind: ruling

### BRO-109: Send to Resolve inserted from a drive only one computer had.
- Why: Clips were remembered by their import location on the owner's computer, a private path that other machines lacked.
- Must: Send to Resolve always references the archive copy at the shared path every machine reaches, fetching it first if missing.
- Kind: situation

### BRO-112: Sending a b-roll clip to Resolve showed an error.
- Why: The owner hit an error pressing send on a clip; what it said was not recorded.
- Must: Send to Resolve either places the clip in the open project or says in plain words why not and what to do.
- Kind: situation

### BRO-113: "Already downloading, not sent yet" was shown as a red error or a green success.
- Why: The per-computer download limit expected the page to retry, but pages read the busy answer as failure, or as success while nothing resumed.
- Must: "Busy" is a wait starting "not sent yet", never success in any open page version; the page retries at the suggested pace for 15 minutes, and queued work starts when a slot frees.
- Kind: situation

## Previews standing in for originals

### BRO-124: A preview could be written under an MXF, AVI or MKV name.
- Why: A preview's bytes are MP4; under an .mxf name Resolve refuses or misreads it, and the unopenable clip was re-imported on every insert.
- Must: A preview stands in only for .mov, .mp4 or .m4v originals; any other original gets the preview inserted as itself.
- Kind: given

### BRO-114: During an archive outage, inserts recorded permanent low-resolution stand-ins.
- Why: When the server briefly could not list the archive, it answered as if the clip had no original, so previews went permanently into projects (a stand-in is a preview under the original's name).
- Must: "Could not read the archive" is never "no original"; inserts then fetch the clip asked for, record nothing lasting, and the server shows and mails the problem until readable.
- Kind: situation

### BRO-115: A clip inserted while its original uploaded stayed the preview for ever.
- Why: For the hours a heavy original uploads, the server answered "no original", so Resolve got the preview as the clip and nothing upgraded it.
- Must: An insert during upload points where the original will land, is marked a stand-in, and upgrades when it arrives; imports that send no originals owe none.
- Kind: situation

### BRO-116: A clip with no original was recorded as a stand-in for ever.
- Why: Clips whose original never was or will be uploaded were treated as heavy originals, so a stand-in was recorded for a file that did not exist.
- Must: A clip with no original inserts its preview as itself, records no stand-in, and is never offered an upgrade.
- Kind: situation

### BRO-117: A 1080p stand-in under a 6K original's name was forgotten and rendered as real.
- Why: The stand-in was recorded only if someone watched the download finish; a closed tab, failed fetch or absent drive left it unrecorded or unclearable.
- Must: A stand-in is recorded before any byte is written, one bad record never blocks later ones, and it is cleared only when the real original is verified in place.
- Kind: situation

### BRO-118: Picture size alone cannot tell a stand-in from an original of 1080 lines or less.
- Why: Previews scale to at most 1080 lines, never up, so smaller originals and their previews share dimensions, and a real original was once recorded as a stand-in.
- Must: Stand-in or original is decided by something that differs between them, never picture size alone, and a file that cannot be identified stays a stand-in.
- Kind: situation

### BRO-120: Other computers could not tell which clips were cut against a stand-in.
- Why: Only the computer that placed a stand-in knew, so others re-examined archive clips every two minutes or decoded whole files to find them.
- Must: Every computer opening the project learns which archive clips are stand-ins; "the server does not know" means keep checking, never "no"; the mark clears when the real file lands.
- Kind: situation

### BRO-121: Stand-ins were upgraded only if Resolve happened to be open.
- Why: An editor who inserted a clip, restarted the app and left Resolve closed kept a 1080p preview under a 6K name for good.
- Must: Fetching the editing proxy for a stand-in proceeds with Resolve closed, and the clip picks it up when Resolve next opens.
- Kind: situation

### BRO-122: An editor cut on a stand-in without being told.
- Why: When the editing proxy's arrival failed, gave up or was held behind an unrelated setting, the editor kept cutting the 1080p preview unaware.
- Must: While any clip is a stand-in the editor's app shows a count and says to send them again, and the upgrade proceeds regardless of other settings.
- Kind: situation

### BRO-123: The editing proxy upgrade started another worker every two minutes.
- Why: An upgrade still downloading, or one Resolve could not link, was started again every cycle, piling up processes per clip with no ceiling.
- Must: Each clip's upgrade runs once at a time and stops after 8 failed attempts counted across restarts; re-sending the clip resets the count.
- Kind: situation

See also, filed under another capability:

- ALL-051 (The whole product): "Could not read" was acted on as "nothing there".

## Client folders and links

### BRO-125: Curated b-roll folders get a link a client opens without signing in.
- Why: The owner wanted clients to browse a curated folder like an editor does, with the studio's logo, "no need for passwords, no need for downloads".
- Must: A client link opens one curated folder, browsable like the b-roll search, branded, with no sign-in, no download, and reachable off the private network.
- Kind: ruling

### BRO-126: The owner wants to share one folder with a client himself, link first.
- Why: The owner: "priority is to get the link out so skip indexing", and "I want to be able to share only a single folder going forward"; it was done by hand.
- Must: An editor picks any tree folder and immediately gets a client link with previews, without waiting for indexing or publishing anything else.
- Kind: ruling

### BRO-127: A distant client had to download terabytes without joining the private network.
- Why: The owner: "several terabytes for a client to download it once", 500 Mbps at both ends, "I don't want them to have to join our [private network]."
- Must: A client link downloads chosen folders read-only and resumable straight from the NAS near line speed, needing no client software or private-network access.
- Kind: ruling

### BRO-128: A renamed or rebuilt clip vanished from, or swapped inside, client folders.
- Why: Client folders remembered clips by path or by a number that index rebuilds reassign and other machines number differently, so clips dropped, swapped or duplicated.
- Must: A clip keeps one identity across renames, moves, rebuilds and machines; a folder serves exactly its curated clips; one that cannot be confirmed is hidden from the client, shown missing to the curator.
- Kind: situation

### BRO-129: Revoking a client's link did not stop playback for an hour.
- Why: Shared media was sent with a one-hour browser cache, and every link appeared in the access log.
- Must: Every client request is checked against the folder's curated clips; after revoking, the very next media request is refused; a link never appears in any log.
- Kind: situation

### BRO-130: A client's expired link named nobody to ask for a new one.
- Why: A revoked or expired link said only "contact whoever sent it", and a clip removed while the client watched became a broken video box.
- Must: An expired or revoked link names the curating editor and contact, an unknown link reveals nothing, no client page names a file path, and a pulled clip says to refresh.
- Kind: situation

### BRO-131: An editor checking their own client link was counted as the client opening it.
- Why: Every open of a client link was recorded as a client view, including the curator's own check from the dashboard.
- Must: "Client opened this" counts only opens by someone other than the studio's own signed-in people.
- Kind: situation

### BRO-132: A client's link expired without warning.
- Why: Client links and stuck import batches had no alarm, so a link quietly expired and a batch with no heartbeat sat for days.
- Must: The owner is warned when a live client link is within 7 days of expiry, and when an import batch has had no heartbeat for a day.
- Kind: situation

### BRO-133: The public client page exposed the whole internal app's files.
- Why: The public share address served every static file of the internal b-roll app, not just the viewer's.
- Must: The public share serves only the viewer's own files and answers anything else as not found.
- Kind: situation

### BRO-134: One interrupted data upgrade broke every client link for good.
- Why: Part of the upgrade was saved before its version mark, so after a kill mid-upgrade every start failed; a failed fill step was also marked done, dropping clips.
- Must: Every stored-data upgrade step can be interrupted and rerun safely, a failed step is retried, and a read-only disk never takes client links down.
- Kind: situation

### BRO-135: A briefly locked client-folder store at startup hid the whole archive.
- Why: A lock on the client-folder records at startup marked all of b-roll unavailable though every search worked.
- Must: A failure in one feature's storage at startup disables only that feature; b-roll search and everything else stay up.
- Kind: situation

## Replacing the search index

### BRO-136: Publishing a rebuilt search index deleted the clips added since.
- Why: Clips and tracks added by editors exist only in the live index; swapping in a rebuilt copy dropped them and the import queue, a size check passed it, and success was reported.
- Must: Replacing a search index keeps every item and queue entry added since the rebuild began, or refuses before anything changes, and a failed merge is reported naming the recovery.
- Kind: situation

### BRO-137: A published index the running server could not read switched search off.
- Why: An index in a newer format disabled b-roll search; an older one under a newer server made every import fail until restart.
- Must: Publishing an index whose format version differs from the running server's is refused in either direction, naming what to do first.
- Kind: situation
