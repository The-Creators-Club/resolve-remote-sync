# B-roll: the archive, search and client folders

## Givens: browsers, cameras, files and Resolve

### BRO-001: Previews of 10-bit camera footage played as black rectangles in browsers.
- What was going on: Sony FX3 and FX30 record 10-bit; a 10-bit H.264 preview plays black where the browser decodes in hardware (3,467 of 7,110 archive previews were affected).
- What the product must do: Every browser preview, poster and still is 8-bit 4:2:0 whatever the source, and plays in Chrome, Edge and Safari; Resolve editing proxies may stay 10-bit.
- Kind: 1a
- From: L01-009, C02-026, L03-061, C01-092, M01-014, P05-027

### BRO-002: A browser preview with keyframes far apart seeks slowly.
- What was going on: Previews and proxies with one keyframe every two seconds made seeking in the browser sluggish.
- What the product must do: Browser previews and proxies carry one keyframe per second, so a seek lands quickly.
- Kind: 1a
- From: C03-030

### BRO-003: Resolve refused every 29.97 preview after a camera's timecode was rewritten.
- What was going on: A colon in a file's timecode track is genuine non-drop-frame; Sony's own metadata colon is read as drop-frame; only files with no timecode track need guessing.
- What the product must do: Timecode from a file's timecode track is kept as written; only a file with none gets its drop-frame form decided from its frame rate.
- Kind: 1a
- From: C03-031

### BRO-004: A video file's declared frame count can be wrong.
- What was going on: An MP4 from an encoder killed partway still declares the frame count it intended; trusted, it made offline clips the wrong length on every remote computer.
- What the product must do: A declared frame count is used only when duration times frame rate agrees within one frame plus 1%; otherwise the length is treated as unknown.
- Kind: 1a
- From: L08-069, L09-036

### BRO-005: Videos with no readable duration crashed processing with a cryptic error.
- What was going on: Raw video streams, some MPEG-TS files and recordings still being written report no duration at all.
- What the product must do: A file with no duration is set aside with a plain reason, never crashed on and never published.
- Kind: 1a
- From: L09-049

### BRO-006: Dropping a folder of over 100 clips in Chrome silently lost the rest.
- What was going on: Chrome hands a dropped folder's contents over 100 entries per read and empties the drop after the first pause; drag highlights flicker per element crossed.
- What the product must do: Dropping a folder of any size onto a page brings in every file in it, and the drop highlight stays steady while dragging.
- Kind: 1a
- From: C02-029

### BRO-007: A 4 GB upload with no progress bar looked like a hung page.
- What was going on: The browser's newer request method cannot report upload progress, and browsers cannot preview camera raw or MXF files, so a drop showed nothing for minutes.
- What the product must do: Every file uploading from a page shows its progress, and a file the browser cannot preview says so until a thumbnail arrives.
- Kind: 1a
- From: C02-030

### BRO-008: Refusing an upload part-way lost the reason the browser was given.
- What was going on: A server that answers a refusal without reading the rest of the upload resets the connection, and the browser sees only a network error.
- What the product must do: When an upload is refused (no space, no permission), the person sees the reason, not a network error.
- Kind: 1a
- From: C02-032

### BRO-009: The page said the local app was not running when Chrome had blocked it.
- What was going on: Chrome's local-network permission can block a plain-http page from calling the app on this computer, and that looks identical to nothing listening.
- What the product must do: A page that cannot reach the local app never claims it is not running; it names both possibilities and offers a one-click self-test.
- Kind: 1a
- From: C01-100, L03-077

### BRO-010: A clip uploaded from a Mac was treated as having no original.
- What was going on: macOS spells accented and Chinese names decomposed; compared byte for byte with the NAS spelling, originals and proxies went unfound and editors pulled the heavy original instead.
- What the product must do: Name matching treats the Mac and NAS spellings of one name as equal, while every file is opened by the exact spelling on disk.
- Kind: 1a
- From: L09-018, L10-014

### BRO-011: Changing a folder name's capitals made the whole folder be indexed again.
- What was going on: Windows drives and NAS shares treat "Youtube" and "YouTube" as one folder, but an exclusion rule compared letter case exactly.
- What the product must do: Path comparisons on these drives and shares ignore letter case, so a capitals-only rename changes nothing.
- Kind: 1a
- From: H01-034

### BRO-012: Two archive names differing only in case land in one folder.
- What was going on: Windows and macOS treat file names that differ only in letter case as the same name.
- What the product must do: Archive names are compared without case, and a new name matching an existing one apart from case is refused or renamed.
- Kind: 1a
- State: outcome not found
- From: H08-041

### BRO-013: Two clips with the same camera name in one batch became one.
- What was going on: Cameras restart numbering per card, so two cards hold the same clip name under the same card path; matching by name and folder indexed one twice and lost the other.
- What the product must do: Every ingested file is tracked by its own identity, and two different same-named files in one batch both arrive and are indexed, in b-roll and music alike.
- Kind: 1a
- From: H06-044, C04-007, L10-045

### BRO-014: Resolve's own smart search data cannot be reused to describe b-roll.
- What was going on: Resolve stores IntelliSearch results as 768-number vectors per shot, with no captions or tags, so nothing readable can be lifted from them.
- What the product must do: B-roll descriptions are produced by the product itself and never depend on Resolve's IntelliSearch data.
- Kind: 1a
- From: P06-012, C02-006

### BRO-015: An overseas client downloaded at 2 MB/s from a 39 MB/s studio uplink.
- What was going on: Taiwan to US round trips of 130-200 ms hold one connection to about 0.3 MB/s; eight connections gave 4.1 MB/s.
- What the product must do: Client downloads resume after interruption, allow several parallel connections, and every request is logged durably with address, file and bytes.
- Kind: 1a
- From: M05-085

## How the archive is laid out

### BRO-016: The archive is browsed as folders, downloaded and own-shoot clips apart.
- What was going on: The owner wanted a folder browser with "the downloaded b-roll in a root folder 'Downloads' and all our custom b-roll in a separate root folder".
- What the product must do: B-roll search has a folder tree with separate roots for downloaded and own-shoot clips, listing every clip in a chosen folder.
- Kind: 2
- From: P03-027

### BRO-017: Own-shoot footage files under its project's name with every shoot subfolder kept.
- What was going on: The owner: footage goes "into their origin folders" and "we should maintain the subfolders"; editors find own footage by shoot, day and camera, and a project code means nothing.
- What the product must do: Own-shoot footage files under the project's spoken name with the shoot's folders shown to any depth; a later rename moves, never recopies; footage timelines use is never re-filed.
- Kind: 2
- State: fixed, never shipped
- From: P06-047, M01-003, P04-014, P13-026

### BRO-018: Own-shoot b-roll enters the archive as high-quality proxies, shots under 5 minutes.
- What was going on: The owner: "I only want to keep high quality proxies of this footage on the nas, I don't want the originals", and "ignore any shot which is longer than 5 minutes."
- What the product must do: The archive copy can be a high-quality proxy, indexed like an original and renderable in timelines without the camera original; a shot of 5 minutes or more never enters.
- Kind: 2
- From: P03-035, P06-046, P03-026, P04-015

### BRO-019: The archive records where every clip's original lives.
- What was going on: Originals sit on backup drives and in download folders; the owner asked to "store the locations of all the originals ... so we can keep track".
- What the product must do: Every archive clip, downloaded or own-shoot, carries the location of its original.
- Kind: 2
- From: P03-036

### BRO-020: Own-shoot b-roll is filed without full indexing or speech-to-text.
- What was going on: The owner did not want own-shoot clips fully indexed ("random chatter", no real audio), but they must be in folders, perhaps lightly indexed.
- What the product must do: Own-shoot clips are sorted into folders without transcription, with full indexing optional later and never ruled out.
- Kind: 2
- From: P03-037

### BRO-021: Every clip sits in one broad category, described by subject, format and place.
- What was going on: The owner wanted "useful category folders, not minute categories that fit only one or two videos".
- What the product must do: Every archive clip sits in one broad category folder, none left uncategorised, with subject, format and place shown as descriptions.
- Kind: 2
- From: P03-028

### BRO-022: A categorised clip never moves and no category is ever deleted.
- What was going on: The owner: "clips once categorised should not move between them. No categorised should be deleted, only new categorised created."
- What the product must do: Re-indexing never moves a categorised clip or removes a category; it may only add new categories.
- Kind: 2
- From: P03-029

### BRO-023: Interviewee footage was filed under wrong subjects by guessing from the picture.
- What was going on: The owner: a clip inside an interviewee's folder is that interviewee's b-roll; guessing from the picture mislabelled 1,463 such clips.
- What the product must do: A clip inside an interviewee's folder is classed as that interviewee's b-roll from the folder alone; no clip outside one gets that class from its content.
- Kind: 2
- From: M01-005, P04-016

### BRO-024: Footage used by many projects must not be set up again per project.
- What was going on: The owner wanted one shoot in several projects; a per-project bin of outside files "would be fiddly to set up every time there's a new [series] project".
- What the product must do: Footage shared across projects lives in one shared library every editor can use, with no setup when a new project starts.
- Kind: 2
- From: P11-045
- Move to: sync

### BRO-025: Editors' old proxy folders are kept and copied, never indexed.
- What was going on: Old project folders held about 2,100 proxies that existing Resolve projects link to; at about 47 MB a minute they are ten times too big for search previews.
- What the product must do: Proxy folders are skipped by indexing but kept at their linked paths when copied to the NAS, and search previews are made from originals.
- Kind: 2
- From: P01-050, M05-018

### BRO-026: Duplicate videos are indexed once and copied once.
- What was going on: The owner wanted byte-identical duplicates flagged and skipped, in indexing and in the copy to the NAS; 246 files, 41 GB, were duplicates.
- What the product must do: A file identical to one already indexed is flagged, not indexed again, and left out of the archive copy.
- Kind: 2
- From: P01-049

### BRO-027: Zero-byte files all looked like duplicates of one random clip.
- What was going on: Every empty file hashes alike, so duplicate detection piled five unrelated failed downloads onto one arbitrary clip.
- What the product must do: Zero-byte files are flagged as broken downloads and never treated as duplicates of anything.
- Kind: 3
- State: still open
- From: M01-066

### BRO-028: Indexing starts where clips are and survives their move onto the NAS.
- What was going on: The archive was spread over many drives for days before the NAS was ready; the owner wanted indexing to begin anyway and follow the files.
- What the product must do: Clips indexed in their old locations keep their index entries after being copied onto the NAS, with nothing indexed twice.
- Kind: 3
- From: P01-051

### BRO-029: Two editors adding files at once could both claim one archive name.
- What was going on: Two editors dropping cards at once, or two music files named theme.wav, could each take the same name and overwrite a clip already in a timeline.
- What the product must do: Archive and music library names are assigned in one place, never twice, so a file added by one editor never overwrites another's.
- Kind: 3
- From: C02-016

### BRO-030: A published archive file was overwritten with different footage already in timelines.
- What was going on: Archive file names were worked out afresh each run, so a new clip with the same title took the plain name and shifted the others.
- What the product must do: Once a clip's archive path is published it never changes, and a file at a published path is never overwritten with another clip's footage.
- Kind: 3
- From: H02-017

### BRO-031: A repair tool could re-encode archive originals over themselves.
- What was going on: Pointed at an original, the preview repair shrank it in place, and archive rebuilds comparing size only restored broken files over repairs.
- What the product must do: Nothing writes over an original, recorded repairs survive rebuilds, and anything replaced is kept aside.
- Kind: 3
- From: L01-043

## Describing and indexing clips

### BRO-032: B-roll is described on the studio's own graphics card, Good or Best.
- What was going on: The owner chose local describing (about 10-16 s a clip against 69 s hosted, cheaper, and judged better), with a smaller and a larger model chosen by graphics memory.
- What the product must do: A new install describes b-roll locally by default, offering "Good" and "Best" whose tooltips state the video memory each needs, and the customer picks.
- Kind: 2
- From: C02-007, P06-013

### BRO-033: Describing beats proxy making, runs now or when idle, and checks graphics memory.
- What was going on: The owner ruled both jobs want the one graphics card and the editor is waiting on the describing; a model too big for the card must be refused visibly.
- What the product must do: Proxy making waits while describing runs, saying why; each batch runs now or when idle; an unfit model is never downloaded and its refusal shows the memory figure to editor and admins.
- Kind: 2
- From: P06-018, M01-009, C02-010, C02-011

### BRO-034: Indexing used up the assistant allowance and needed a cap and a stop time.
- What was going on: Indexing reached 27% of the weekly allowance in an hour; the owner asked for a limit and to "let ongoing videos complete after 4pm before stopping".
- What the product must do: Indexing shows the allowance spent; at the owner's limit or stop time it starts nothing new but lets every clip already started finish and be saved.
- Kind: 2
- From: P04-013, P03-006

### BRO-035: Background indexing must leave the computer usable while it runs.
- What was going on: The owner asked that the b-roll processing run use at most 60% of the computer so he could keep working.
- What the product must do: Background indexing on a working computer stays under the owner's set share of its capacity, 60% by default.
- Kind: 2
- From: P04-073

### BRO-036: Clip descriptions are nouns only, with on-screen text kept.
- What was going on: The owner asked for "nouns only", which halved the median description from 36 to 18 words; on-screen captions are often the best detail.
- What the product must do: Clip descriptions are terse noun phrases and always include readable on-screen text.
- Kind: 2
- From: M05-008

### BRO-037: Most searches were answerable from speech before any visual indexing.
- What was going on: Transcripts alone met 19 of 20 test queries; only purely visual ones, like "aerial drone shot of coastline", needed frame descriptions.
- What the product must do: Speech search works as soon as clips are transcribed, without waiting for visual indexing.
- Kind: 3
- From: M05-019

### BRO-038: Audio-only archive files were never transcribed, so search never found them.
- What was going on: A file with no picture is rightly skipped for visual indexing, and the same skip kept it from transcription; a three-hour take skipped for length was transcribed anyway.
- What the product must do: Audio-only archive files are transcribed and searchable by speech; a clip skipped for length or with no readable duration is never transcribed or analysed.
- Kind: 3
- From: L10-003, H06-112, H01-020

### BRO-039: Turning indexing back on for a share left its prepared clips invisible.
- What was going on: Clips of a share set to "do not index" rest prepared, and one way of starting indexing never looked at them again.
- What the product must do: When a share is switched to indexed, every clip already prepared for it is picked up by the next run, however it is started.
- Kind: 3
- From: H02-016

### BRO-040: Re-indexing a clip left old search data that hid its real content.
- What was going on: Earlier search entries stayed behind, and cached results kept being served when the row count did not change.
- What the product must do: Re-indexing a clip replaces all its earlier search data, and search reflects the change at once.
- Kind: 3
- From: H01-033

### BRO-041: One setup mistake marked all 2,000 queued clips as failed.
- What was going on: Failures from configuration, rate limits, credit or sign-in hit every clip alike, but were treated as one clip's problem, so the run marched through the queue failing each.
- What the product must do: A failure that would hit every item stops or pauses the run with one clear message and leaves the queue waiting; only clip-specific failures mark a clip failed.
- Kind: 3
- From: M05-010, L01-078, H03-041

### BRO-042: A camera file named C0429.MP4 stopped overnight indexing as if rate-limited.
- What was going on: Error text was searched for "429", which camera file names, clip numbers and progress counters routinely contain.
- What the product must do: A rate limit is recognised only from the service's own reply; any other failure marks that clip failed, names the cause, and the queue moves on.
- Kind: 3
- From: H02-015

### BRO-043: A stalled indexing run looked healthy for eight hours.
- What was going on: Output appeared only at exit, times were UTC not local, a partial run reported success, and "queued, heartbeat 3 hours ago" really meant the computer had stopped answering.
- What the product must do: Runs show live progress in local time as sentences that age, flag no progress within minutes, and report success only when every queued item is done.
- Kind: 3
- From: M05-016, L04-138

### BRO-044: Long indexing runs died with their window, a crash or an update reboot.
- What was going on: Batches run for hours; the starting window closes, the app is updated or crashes, and Windows reboots for updates outside active hours.
- What the product must do: Long runs outlive the window that started them, survive a reboot, and resume each item at the step it reached without redoing finished work.
- Kind: 3
- From: M05-015, C02-038

### BRO-045: A second copy of the local describing model stayed in video memory.
- What was going on: When the running model was slow to answer a health check, a replacement was started without stopping the old one.
- What the product must do: At most one local model holds the graphics card at a time, the old one is stopped before a replacement starts, and all are released when the editor returns.
- Kind: 3
- From: L04-002, H04-082

### BRO-046: A failed clip showed "error" with no message.
- What was going on: The error text sent with a failed clip was dropped on the way to the server.
- What the product must do: A failed clip always shows why it failed, and a later plain rescan never blanks that message.
- Kind: 3
- From: L01-081

### BRO-047: A briefly busy archive database threw away finished local describing work.
- What was going on: Parts of the server answered a busy database with a plain error, and the editor's app treated any error as final, discarding minutes of analysis.
- What the product must do: A momentarily busy server answers "busy, try again" everywhere, and clients retry that answer instead of discarding completed work.
- Kind: 3
- From: L09-015

### BRO-048: Ten minutes after asking for the describing model the page still said "no model".
- What was going on: The 3.3 GB model download crawled on one stuck connection while the page showed a raw status word.
- What the product must do: A model download shows percent, rate and time left on the page and in the editor's app, and recovers from a stalled connection.
- Kind: 3
- From: P06-024

## Search

### BRO-049: A search shows when its subject appears and sends that range to Resolve.
- What was going on: The owner wanted "navy ship" to show every clip at the times ships appear, then an in and out point inserted into the open Resolve.
- What the product must do: A result shows the times its subject appears; the person sets in and out and inserts exactly that range into Resolve.
- Kind: 2
- From: P01-043

### BRO-050: Search results are thumbnails only, with no text under them.
- What was going on: The owner ruled text under each result "just distracts from looking at the results".
- What the product must do: Search results show only thumbnails; titles and buttons appear only when a clip is opened.
- Kind: 2
- From: P04-022

### BRO-051: A search can be limited to what is seen or to what is said.
- What was going on: The owner: "I need a way to search only visuals or only transcript".
- What the product must do: A search can be restricted to picture descriptions or to the spoken transcript, and the results say which was searched.
- Kind: 2
- State: outcome not found
- From: P01-052

### BRO-052: Searching "wind farm" showed a talking head instead of the matching frame.
- What was going on: The owner calls the matching thumbnail "a feature we explicitly built out"; long clips get coarser preview strips than the page assumed, and hover showed wrong frames on 95% of clips.
- What the product must do: Each result's thumbnail and hover-scrub show the frame where the query matched, for clips of any length and any preview spacing, old or new.
- Kind: 2
- From: P06-016, C01-074, P04-018, H01-018

### BRO-053: Opening a search result lands on the matching moment.
- What was going on: Clicking a found video started at its beginning; the owner said it "should auto jump me to the section of the video which I searched for".
- What the product must do: Opening a search result starts playback at the moment that matched, not at the clip's start.
- Kind: 2
- From: P03-007

### BRO-054: A clip sometimes opened two minutes in, at an earlier clip's hit.
- What was going on: A pending jump from a clip whose preview never loaded was applied to the next clip opened.
- What the product must do: A clip opens at its own start or its own search hit, never at a point belonging to a clip opened earlier.
- Kind: 3
- From: H02-013

### BRO-055: The typo "ambluance" became "Blu" and "mars" matched "marriage".
- What was going on: A loose similarity score treats a short string as a perfect match for anything containing it, and stem prefix search widened short terms.
- What the product must do: Spelling suggestions are whole words of similar length, and a search term under five letters never matches unrelated words sharing its stem.
- Kind: 3
- From: M05-020

### BRO-056: Two-character Chinese words, and the other script's spelling, found nothing.
- What was going on: Chinese has no spaces; plain word search needs three characters of an unbroken run, and Traditional and Simplified forms differ.
- What the product must do: Searching 堵車, its Simplified form, or 同志伴侶 finds clips whose speech or text holds those words in either script, as soon as they are indexed.
- Kind: 3
- From: C02-017, M05-005

### BRO-057: Chinese and Japanese queries returned nothing in meaning-based search.
- What was going on: A guard meant for mixed-language queries discarded every meaning-based hit for any mostly non-Latin query.
- What the product must do: A Chinese, Japanese or other non-Latin query returns matching clips in every search mode where an equivalent English query does.
- Kind: 3
- From: H02-010, C01-102, H01-043

### BRO-058: Searches for names absent from the archive returned 15 to 17 unrelated videos.
- What was going on: Meaning-based scores cannot tell absent from present; an absent Chinese name scored 0.88, above every genuine cross-language match (best 0.74).
- What the product must do: A query with no word match returns at most a few clips labelled related, none for a Chinese query, and an empty result stays possible.
- Kind: 3
- From: M05-004

### BRO-059: Meaning-based search could return nothing for ever without saying why.
- What was going on: When the model behind meaning-based search was missing or mismatched, every query returned nothing with no sign anywhere.
- What the product must do: A search mode the server cannot run is disabled with its reason; the default mixed mode is never disabled and says what it lost.
- Kind: 3
- From: L04-137

### BRO-060: A common-word search sent about 1 MB for 24 results and felt slow remotely.
- What was going on: Each search returned every matching passage of every result, up to 193 per clip, and rebuilt its typo data on every query.
- What the product must do: One page of results answers within about a second over a remote link, even for very common or misspelt words.
- Kind: 3
- From: H02-012

### BRO-061: Older search results replaced newer ones on screen.
- What was going on: A slow earlier answer could arrive last and overwrite the latest search's results, in b-roll and music.
- What the product must do: The results on screen always belong to the most recent search or filter the person made.
- Kind: 3
- From: H01-031

### BRO-062: A search that found nothing showed a blank page.
- What was going on: An empty result gave no hint of what was searched or which filters narrowed it.
- What the product must do: An empty result names the query, the scope and how many clips were searched, and offers to clear only the filters actually on.
- Kind: 3
- From: L04-136

### BRO-063: Each proxied shoot clip showed twice, once as a blank card.
- What was going on: Camera originals that had proxies were listed beside their own proxies, as cards with no preview.
- What the product must do: A clip with a proxy appears once in browse and search, with its preview.
- Kind: 3
- From: C01-066

### BRO-064: Clips marked as duplicates came up in search with black previews and failing sends.
- What was going on: The duplicate copy kept its descriptions, so search found it, but it had no archive file.
- What the product must do: A clip marked as a duplicate never appears in search results or folder counts; only the kept copy does.
- Kind: 3
- From: H02-011

### BRO-065: The search homepage was full of broken or "no preview" thumbnails.
- What was going on: Clips reached the shared archive without their stills and hover strips, so search had nothing to show.
- What the product must do: A clip appears in search only once its media, still and preview strip are all in the archive; a missing one shows a placeholder saying so.
- Kind: 3
- From: P03-008, P04-017, M01-006

### BRO-066: A clip could show another clip's preview still.
- What was going on: Stills were keyed by a number that a clip added from an editor's computer and a clip added in bulk could share.
- What the product must do: Each clip's preview still belongs to that clip alone and can never collide with another clip's.
- Kind: 3
- State: still open
- From: L10-052

### BRO-067: Clicking a folder in a clip's path must show exactly that folder.
- What was going on: A loose match would also catch "B-roll Archive" for "B-roll", and a folder named like "100%_Real" would select everything.
- What the product must do: A folder filter matches that exact folder and below and treats every character literally.
- Kind: 3
- From: C01-075

### BRO-068: Combined filters left an empty grid the clear button could not escape.
- What was going on: A breadcrumb folder, a tree folder, a category and an earlier query combined silently, and a filter control rendered blank depending on how a folder was reached.
- What the product must do: Every active filter is named and clearable, a new folder or category replaces the old one, and a folder shows the same controls however it was reached.
- Kind: 3
- From: H01-019, H02-014

### BRO-069: Folder counts did not match what clicking the folder showed.
- What was going on: Counts and clicks used different matching rules and different sets of clips, and some results shown could not be previewed.
- What the product must do: A folder's count equals the results clicking it shows, and every result shown can be previewed or says why not.
- Kind: 3
- From: H01-032

### BRO-070: Browser Back left b-roll for the dashboard, and an opened clip hid its video.
- What was going on: The search kept its views in one page state, and an opened clip showed empty space until the editor scrolled to the video.
- What the product must do: Back walks through the search's own views (results, folder, clip) before leaving, and an opened clip shows its video without scrolling.
- Kind: 2
- From: C01-067, P04-019

## The clip player

### BRO-071: A preview is scrubbed by hovering its thumbnail or dragging its playhead.
- What was going on: The owner wanted to "scrub the playhead by dragging" and to scrub a result by hovering it; dragging was jerky or did nothing.
- What the product must do: Hovering a result scrubs its preview, and dragging a clip's playhead scrubs the video smoothly without falling behind the pointer.
- Kind: 2
- From: P03-030, P04-020

### BRO-072: The stretches of a clip that match the search are marked on its seek bar.
- What was going on: The owner wanted relevant stretches highlighted; the existing markers ran off the end of the bar.
- What the product must do: The seek bar highlights each stretch matching the search, and no marker draws beyond either end of the bar.
- Kind: 2
- From: P04-021

### BRO-073: Pressing I showed nothing until O was set.
- What was going on: The owner wanted a red in-point line; a fresh in point sits exactly under the white playhead, which drew over it.
- What the product must do: In and out points show at once as red lines on the seek bar, drawn above the playhead.
- Kind: 2
- From: P05-028, C01-094

### BRO-074: Pressing Enter on a focused button could append a clip to the live timeline.
- What was going on: The clip view captured Enter and Space for its own shortcut, even on focused buttons and in drawers open over it.
- What the product must do: Keyboard shortcuts never override a focused button or field, and nothing reaches Resolve without the editor meaning to send it.
- Kind: 3
- From: H06-096

## Previews made for the archive

### BRO-075: Re-encoded previews came out at 95% of their source's size.
- What was going on: High-resolution settings barely shrink already-compressed downloads, and editors' proxies are ten times too big for web previews.
- What the product must do: Web previews are 540p, never upscaled, much smaller than the source, and made from originals rather than editors' proxies.
- Kind: 3
- From: M05-017

### BRO-076: A 16-minute clip's preview sheet was too large to build.
- What was going on: A fixed frame interval asked for a 490-frame sheet, beyond what the encoder accepts; 1.8-hour clips need far more.
- What the product must do: Preview frame spacing widens with clip length so any clip, hours long included, gets a preview of bounded size.
- Kind: 3
- From: M05-014

### BRO-077: Camera mis-taps under a second long failed preview making.
- What was going on: Clips of 0.07-0.5 s yielded no frame for a preview sheet sampling one frame every two seconds.
- What the product must do: A clip shorter than the sampling interval gets a preview from its first frame, or is skipped with a stated reason.
- Kind: 3
- State: outcome not found
- From: M02-037

### BRO-078: Long clips lost their proxies on computers without a hardware encoder.
- What was going on: Encodes had a fixed 15-minute limit, so a ten-minute clip encoded in software timed out and lost its proxy or the whole item.
- What the product must do: Encode time limits scale with clip length and the computer's speed, and a timeout is reported as a timeout, not a bad file.
- Kind: 3
- From: H06-110

### BRO-079: An editing proxy a few frames short failed the whole clip.
- What was going on: Resolve refuses proxies even 1 to 18 frames short, but a failed optional editing proxy also discarded the preview, stills and original upload.
- What the product must do: An editing proxy failing its exact frame check is dropped with a stated reason, and the clip still goes live with its preview.
- Kind: 3
- From: L08-068

### BRO-080: A clip went live with an empty preview from a killed transfer.
- What was going on: A zero-byte file passed the upload check because no declared size existed to compare against.
- What the product must do: A zero-byte file is never accepted as an uploaded file, whether or not a size was declared.
- Kind: 3
- From: L09-048

### BRO-081: Copying 85 GB of previews to the NAS over 10GbE took far longer than minutes.
- What was going on: The owner expected about 85 GB over a 10 gigabit link to take a few minutes; many small preview files ran much longer.
- What the product must do: A bulk copy to the NAS shows progress and speed, and moves many small files at close to the link's capacity.
- Kind: 3
- State: outcome not found
- From: P04-074

## Bringing new footage in

### BRO-082: B-roll is dropped on the dashboard and described on the dropper's computer.
- What was going on: The owner specified: drop clips or folders on the dashboard, preview them, pick settings, run; that computer converts and describes; results reach the shared archive on their own.
- What the product must do: Dropped clips and folders are previewed and described on the dropper's computer, with progress there and on the dashboard; admins see every describing computer; results publish automatically.
- Kind: 2
- From: P06-017

### BRO-083: A 200 GB card drop filled the editor's drive mid-batch.
- What was going on: Camera originals reach 40 GB; the drop capped clip count, not size, checked space after accepting bytes, and a cut-off file could be used as the whole clip.
- What the product must do: A drop larger than free space minus 20 GB is refused whole; over 50 GB asks first with size and hours; skipped non-video files are counted; only complete files are used.
- Kind: 3
- From: C02-031, L03-009

### BRO-084: Rescanning a share, or dropping in one song, re-read gigabytes over the network.
- What was going on: Rescans re-read 16 MB of every known file (about 25 minutes per share), and each music drop read the whole 9.5 GB library.
- What the product must do: Checking for new, changed or duplicate files reads only files whose size or date changed, never the whole already-known library.
- Kind: 3
- From: H02-018

### BRO-085: Dropped clips sat at "uploading" for ever after a cancel, restart or failed upload.
- What was going on: A cancelled batch, a restart mid-batch, a failed upload or a computer gone after a cancel left clips never live nor failed, holding their names, and every new drop was refused.
- What the product must do: Every dropped clip ends live, failed or cancelled within bounded time, a stuck batch never blocks new drops, and a cancelled batch frees the names it held.
- Kind: 3
- From: H03-012, L01-073, L10-015

### BRO-086: A clip whose camera card was pulled before upload froze the whole batch.
- What was going on: An original missing at upload was never sent nor failed, so the batch never finished, the computer refused later drops, and its previews reached the archive orphaned.
- What the product must do: An import checks every file a clip needs before uploading any; a clip whose original vanished fails alone with a reason, uploads nothing, and the batch finishes.
- Kind: 3
- From: L06-017, H05-009, L07-013

### BRO-087: A clip went live undescribed when the server refused its description.
- What was going on: The app uploaded the clip and marked it done anyway, so it was live, unsearchable and never described again.
- What the product must do: A clip never goes live without its stored description; a refused description is retried, and after the retry budget the clip fails visibly.
- Kind: 3
- From: H03-013

### BRO-088: An upload the server refused for good stayed "uploading" for ever.
- What was going on: Only two server answers were handled; every other refusal, permanent ones included, was re-sent silently with no attempt count.
- What the product must do: Every upload answer is classed as done, retry later with a limit, or failed for good with the server's own sentence, shown to the editor and retryable.
- Kind: 3
- From: L08-074, H06-021

### BRO-089: A NAS outage during an upload used up the file's retries.
- What was going on: Counting "NAS unreachable" as a failed attempt lets a short outage exhaust a file's retries and abandon it.
- What the product must do: While the NAS is unreachable, uploads wait and resume, and only failures with the NAS reachable count against a file.
- Kind: 3
- From: C02-027

### BRO-090: One wifi blip at 95% of a 4 GB upload lost that clip for good.
- What was going on: A failed upload in a 200-clip drop was skipped for ever; the only way back was clearing and re-dropping everything.
- What the product must do: Network failures retry three times (2, 4, 8 s), then offer retry per item and for all; a stall is two minutes without progress, never a total time limit.
- Kind: 3
- From: L04-123

### BRO-091: One unexpected error stopped every later upload or download on that computer.
- What was going on: An escaping error left the upload worker marked busy for good, and a download that never started read "downloading 0%" for ever.
- What the product must do: An unexpected error fails only the item it hit, with its text, and work carries on; a transfer that never started reports failed.
- Kind: 3
- From: L06-021

### BRO-092: Quitting or cancelling an import left the encoder running and the file locked.
- What was going on: A running decode carried on up to 15 minutes after cancel or quit and held the staged file, so cleanup failed on Windows.
- What the product must do: Quit or cancel stops any running encode within seconds, including one started during shutdown, and no half-written output reaches the archive.
- Kind: 3
- From: L03-007

### BRO-093: New b-roll stayed invisible until its multi-GB originals finished uploading.
- What was going on: A day of 6K material was hidden for the eight hours its originals took; a batch can also be cancelled after some clips were cut into timelines.
- What the product must do: A clip appears once its preview and proxies are uploaded, before its original; cancelling a batch removes only clips whose media never arrived.
- Kind: 3
- From: C02-018, L08-067

### BRO-094: A clip went live while its original failed to upload, and nobody knew.
- What was going on: Clips publish once previews arrive; a later failure of the original was recorded nowhere, the batch said done, and no retry could reach it.
- What the product must do: A clip whose original is still owed shows so, ends its batch "with errors", can be retried, and the editor's local copy is kept meanwhile.
- Kind: 3
- From: L09-058

### BRO-095: A batch read "40 clips, 38 indexed" with no explanation.
- What was going on: Duplicates the editor unticked were left out of the batch record instead of recorded as skipped.
- What the product must do: Every clip dropped appears in its batch with an outcome, including "skipped, duplicate of" the kept clip, so counts always add up.
- Kind: 3
- State: still open
- From: L01-010, C02-041

### BRO-096: Failed and waiting imports could be seen only by dropping another file.
- What was going on: Failed items never retried, and re-dropping made duplicates.
- What the product must do: An editor can open the import list directly, see waiting items and failures with reasons, and retry one so it keeps its archive slot with no duplicate.
- Kind: 3
- From: L04-133

### BRO-097: "Try the failed clips again" said "12 clips queued" while nothing ran.
- What was going on: The retry named items and the staged drop wrongly, so the editor's computer answered zero retried or failed every clip in seconds with the files still staged.
- What the product must do: A retry reruns failed clips from the files this computer staged, refuses with a reason if it cannot tell which drop, and says running only once a computer took it.
- Kind: 3
- From: L06-023, H05-078, L07-011

### BRO-098: Retrying failed items took a batch from the computer still working on it.
- What was going on: Retry reset a running batch to queued, so the working computer was cut off and the editor's second computer could claim the same clips.
- What the product must do: A retry is refused while a computer still holds the batch, naming that computer; an abandoned batch can still be retried.
- Kind: 3
- From: L06-024, H05-079

### BRO-099: A batch whose computer went away could be finished by no one.
- What was going on: The editor's other computer could not pick it up, though a notice said it could.
- What the product must do: An editor sees their unfinished batches and can take one over on this computer, unless another computer holds a live claim.
- Kind: 3
- From: L04-135

### BRO-100: A refused retry falsely said another computer would pick it up.
- What was going on: The page discarded the editor's computer's real reason, invented one, showed success green and watched a run that did not exist.
- What the product must do: When the editor's computer refuses work, its own sentence is shown as a warning, and the page never shows a run that did not start.
- Kind: 3
- From: L07-059

### BRO-101: When the app on this computer was not running, the page blamed it for refusing.
- What was going on: A failed connection, or an app too old for the request, was shown as the app's refusal, hiding the advice to use the computer holding the files.
- What the product must do: The page tells "the app on this computer did not answer" and "the app is too old" apart from a real refusal, keeping the next-step advice.
- Kind: 3
- From: L10-016

### BRO-102: Staged import copies filled the editor's disk, and clearing them broke live drops.
- What was going on: Staged copies stayed for ever in a hidden folder, the space message pointed at a button that freed nothing, and clearing deleted drops still uploading.
- What the product must do: Staging is released once nothing is owed and expires 7 days after its last bytes; unfinished drops are never cleared; editors can remove unwanted drops; space messages name actions that work.
- Kind: 3
- From: H06-114, L07-012, L03-008, L06-018, H05-050

### BRO-103: The computer that made an editing proxy downloaded it back from the NAS.
- What was going on: The importing computer left its editing proxy in staging, so it re-downloaded hundreds of MB it had just uploaded.
- What the product must do: A computer never downloads a file it produced and still holds.
- Kind: 3
- From: L08-066

### BRO-104: A web page could make the editor's app upload any file on the computer.
- What was going on: A blank library location was treated as the whole disk, and the drop request accepted any local path.
- What the product must do: The editor's app imports, reveals or uploads only files inside a configured library location or picked by the editor; a blank location means not configured.
- Kind: 3
- From: H03-014

## Sending a clip to Resolve

### BRO-105: A remote editor picks b-roll, it lands in the timeline, and the proxy follows.
- What was going on: The owner said the archive "is mainly for remote editors": open search, insert a clip into the timeline, and receive its proxy.
- What the product must do: Inserting an archive clip from search on a remote editor's computer places it in Resolve and brings its proxy down with no other step.
- Kind: 2
- From: P03-031

### BRO-106: Send to Resolve on a remote computer failed with "file not found".
- What was going on: Remote editors do not hold the archive or music library; the owner: sync it down to the matching path under the local tree.
- What the product must do: Sending a clip or track the computer lacks fetches just it to the matching local path with visible progress, then imports it, b-roll into an archive bin.
- Kind: 2
- From: P05-026, M01-010

### BRO-107: A heavy clip sent to Resolve remotely arrives in seconds, then upgrades.
- What was going on: The owner: it "should still only sync the proxy down, and leave the reference to [the archive]"; previews were "too low quality" to keep, and originals are relinked from backups for export.
- What the product must do: A remote insert gives a usable preview within seconds, upgrades to the editing proxy unprompted, keeps pointing at the archive original, and never reports that absent original as missing.
- Kind: 2
- From: P11-046, M01-012, L08-053, P03-033

### BRO-108: A clip used from the archive stays there, never copied into the project.
- What was going on: The owner ruled a clip "stays in the b-roll archive root, and doesn't get copied into the project directory", avoiding duplicates on the NAS.
- What the product must do: Using an archive clip never copies it into a project; the archive's own folder layout is what comes down to the editor.
- Kind: 2
- From: P03-032

### BRO-109: Send to Resolve inserted from a drive only one computer had.
- What was going on: Clips were remembered by their import location on the owner's computer, a private path that other machines lacked.
- What the product must do: Send to Resolve always references the archive copy at the shared path every machine reaches, fetching it first if missing.
- Kind: 3
- From: C01-093, P05-025, M01-011

### BRO-110: Resolve was given the search preview where the editing proxy belonged.
- What was going on: The owner: "why are we remaking proxies ... when we already have proxies?"; on computers holding the original, every insert still attached the 540p preview as proxy.
- What the product must do: An existing editing proxy is reused, a missing one is made at editing quality, and Resolve is never given the browser preview as a clip's proxy.
- Kind: 2
- From: P03-034, L08-059

### BRO-111: Send to Resolve offers both append and place on top.
- What was going on: Sending could only append; the owner asked for "both 'append' and 'place on top'".
- What the product must do: The person chooses between appending the clip at the timeline's end and placing it on a track above, at the playhead.
- Kind: 2
- State: outcome not found
- From: P05-029

### BRO-112: Sending a b-roll clip to Resolve showed an error.
- What was going on: The owner hit an error pressing send on a clip; what it said was not recorded.
- What the product must do: Send to Resolve either places the clip in the open project or says in plain words why not and what to do.
- Kind: 3
- State: outcome not found
- From: P04-031

### BRO-113: "Already downloading, not sent yet" was shown as a red error or a green success.
- What was going on: The per-computer download limit expected the page to retry, but pages read the busy answer as failure, or as success while nothing resumed.
- What the product must do: "Busy" is a wait starting "not sent yet", never success in any open page version; the page retries at the suggested pace for 15 minutes, and queued work starts when a slot frees.
- Kind: 3
- From: L04-122, L06-019, H05-051

## Previews standing in for originals

### BRO-114: During an archive outage, inserts recorded permanent low-resolution stand-ins.
- What was going on: When the server briefly could not list the archive, it answered as if the clip had no original, so previews went permanently into projects (a stand-in is a preview under the original's name).
- What the product must do: "Could not read the archive" is never "no original"; inserts then fetch the clip asked for, record nothing lasting, and the server shows and mails the problem until readable.
- Kind: 3
- From: L10-001, L08-057, L09-017

### BRO-115: A clip inserted while its original uploaded stayed the preview for ever.
- What was going on: For the hours a heavy original uploads, the server answered "no original", so Resolve got the preview as the clip and nothing upgraded it.
- What the product must do: An insert during upload points where the original will land, is marked a stand-in, and upgrades when it arrives; imports that send no originals owe none.
- Kind: 3
- From: M01-013, L09-059, H06-020

### BRO-116: A clip with no original was recorded as a stand-in for ever.
- What was going on: Clips whose original never was or will be uploaded were treated as heavy originals, so a stand-in was recorded for a file that did not exist.
- What the product must do: A clip with no original inserts its preview as itself, records no stand-in, and is never offered an upgrade.
- Kind: 3
- From: L08-056

### BRO-117: A 1080p stand-in under a 6K original's name was forgotten and rendered as real.
- What was going on: The stand-in was recorded only if someone watched the download finish; a closed tab, failed fetch or absent drive left it unrecorded or unclearable.
- What the product must do: A stand-in is recorded before any byte is written, one bad record never blocks later ones, and it is cleared only when the real original is verified in place.
- Kind: 3
- From: L08-054, H06-018

### BRO-118: Picture size alone cannot tell a stand-in from an original of 1080 lines or less.
- What was going on: Previews scale to at most 1080 lines, never up, so smaller originals and their previews share dimensions, and a real original was once recorded as a stand-in.
- What the product must do: Stand-in or original is decided by something that differs between them, never picture size alone, and a file that cannot be identified stays a stand-in.
- Kind: 3
- From: H06-019, L09-056

### BRO-119: A drive unplugged for one check erased the record of stand-ins.
- What was going on: A pulled sync drive, unmapped share or NAS reboot made every file unreadable at once, and the cleanup read that as deletion.
- What the product must do: A cleanup that cannot see the folder tree does nothing, and an unreadable file is never treated as deleted.
- Kind: 3
- From: L09-057

### BRO-120: Other computers could not tell which clips were cut against a stand-in.
- What was going on: Only the computer that placed a stand-in knew, so others re-examined archive clips every two minutes or decoded whole files to find them.
- What the product must do: Every computer opening the project learns which archive clips are stand-ins; "the server does not know" means keep checking, never "no"; the mark clears when the real file lands.
- Kind: 3
- From: L09-026, L08-060

### BRO-121: Stand-ins were upgraded only if Resolve happened to be open.
- What was going on: An editor who inserted a clip, restarted the app and left Resolve closed kept a 1080p preview under a 6K name for good.
- What the product must do: Fetching the editing proxy for a stand-in proceeds with Resolve closed, and the clip picks it up when Resolve next opens.
- Kind: 3
- From: L09-060

### BRO-122: An editor cut on a stand-in without being told.
- What was going on: When the editing proxy's arrival failed, gave up or was held behind an unrelated setting, the editor kept cutting the 1080p preview unaware.
- What the product must do: While any clip is a stand-in the editor's app shows a count and says to send them again, and the upgrade proceeds regardless of other settings.
- Kind: 3
- From: L08-055

### BRO-123: The editing proxy upgrade started another worker every two minutes.
- What was going on: An upgrade still downloading, or one Resolve could not link, was started again every cycle, piling up processes per clip with no ceiling.
- What the product must do: Each clip's upgrade runs once at a time and stops after 8 failed attempts counted across restarts; re-sending the clip resets the count.
- Kind: 3
- From: L08-062

### BRO-124: A preview could be written under an MXF, AVI or MKV name.
- What was going on: A preview's bytes are MP4; under an .mxf name Resolve refuses or misreads it, and the unopenable clip was re-imported on every insert.
- What the product must do: A preview stands in only for .mov, .mp4 or .m4v originals; any other original gets the preview inserted as itself.
- Kind: 1a
- From: L08-058

## Client folders and links

### BRO-125: Curated b-roll folders get a link a client opens without signing in.
- What was going on: The owner wanted clients to browse a curated folder like an editor does, with the studio's logo, "no need for passwords, no need for downloads".
- What the product must do: A client link opens one curated folder, browsable like the b-roll search, branded, with no sign-in, no download, and reachable off the private network.
- Kind: 2
- From: P06-045

### BRO-126: The owner wants to share one folder with a client himself, link first.
- What was going on: The owner: "priority is to get the link out so skip indexing", and "I want to be able to share only a single folder going forward"; it was done by hand.
- What the product must do: An editor picks any tree folder and immediately gets a client link with previews, without waiting for indexing or publishing anything else.
- Kind: 2
- State: still open
- From: P10-040, M01-062

### BRO-127: A distant client had to download terabytes without joining the private network.
- What was going on: The owner: "several terabytes for a client to download it once", 500 Mbps at both ends, "I don't want them to have to join our [private network]."
- What the product must do: A client link downloads chosen folders read-only and resumable straight from the NAS near line speed, needing no client software or private-network access.
- Kind: 2
- From: P10-036

### BRO-128: A renamed or rebuilt clip vanished from, or swapped inside, client folders.
- What was going on: Client folders remembered clips by path or by a number that index rebuilds reassign and other machines number differently, so clips dropped, swapped or duplicated.
- What the product must do: A clip keeps one identity across renames, moves, rebuilds and machines; a folder serves exactly its curated clips; one that cannot be confirmed is hidden from the client, shown missing to the curator.
- Kind: 3
- From: L04-001, H04-081, L02-035, L01-079, H03-042, H06-045

### BRO-129: Revoking a client's link did not stop playback for an hour.
- What was going on: Shared media was sent with a one-hour browser cache, and every link appeared in the access log.
- What the product must do: Every client request is checked against the folder's curated clips; after revoking, the very next media request is refused; a link never appears in any log.
- Kind: 3
- From: H07-047, L02-036

### BRO-130: A client's expired link named nobody to ask for a new one.
- What was going on: A revoked or expired link said only "contact whoever sent it", and a clip removed while the client watched became a broken video box.
- What the product must do: An expired or revoked link names the curating editor and contact, an unknown link reveals nothing, no client page names a file path, and a pulled clip says to refresh.
- Kind: 3
- From: C02-055, L03-095

### BRO-131: An editor checking their own client link was counted as the client opening it.
- What was going on: Every open of a client link was recorded as a client view, including the curator's own check from the dashboard.
- What the product must do: "Client opened this" counts only opens by someone other than the studio's own signed-in people.
- Kind: 3
- From: H06-113, H07-048

### BRO-132: A client's link expired without warning.
- What was going on: Client links and stuck import batches had no alarm, so a link quietly expired and a batch with no heartbeat sat for days.
- What the product must do: The owner is warned when a live client link is within 7 days of expiry, and when an import batch has had no heartbeat for a day.
- Kind: 3
- From: L04-092

### BRO-133: The public client page exposed the whole internal app's files.
- What was going on: The public share address served every static file of the internal b-roll app, not just the viewer's.
- What the product must do: The public share serves only the viewer's own files and answers anything else as not found.
- Kind: 3
- From: L01-080

### BRO-134: One interrupted data upgrade broke every client link for good.
- What was going on: Part of the upgrade was saved before its version mark, so after a kill mid-upgrade every start failed; a failed fill step was also marked done, dropping clips.
- What the product must do: Every stored-data upgrade step can be interrupted and rerun safely, a failed step is retried, and a read-only disk never takes client links down.
- Kind: 3
- From: H05-007, L06-068, L07-061

### BRO-135: A briefly locked client-folder store at startup hid the whole archive.
- What was going on: A lock on the client-folder records at startup marked all of b-roll unavailable though every search worked.
- What the product must do: A failure in one feature's storage at startup disables only that feature; b-roll search and everything else stay up.
- Kind: 3
- From: L07-053

## Replacing the search index

### BRO-136: Publishing a rebuilt search index deleted the clips added since.
- What was going on: Clips and tracks added by editors exist only in the live index; swapping in a rebuilt copy dropped them and the import queue, a size check passed it, and success was reported.
- What the product must do: Replacing a search index keeps every item and queue entry added since the rebuild began, or refuses before anything changes, and a failed merge is reported naming the recovery.
- Kind: 3
- From: L04-067, H07-036, L09-044

### BRO-137: A published index the running server could not read switched search off.
- What was going on: An index in a newer format disabled b-roll search; an older one under a newer server made every import fail until restart.
- What the product must do: Publishing an index whose format version differs from the running server's is refused in either direction, naming what to do first.
- Kind: 3
- From: L09-045

## Sealed

### BRO-S01: The describer narrated an emergency from brake lights.
- What was going on: When a shot shows little, the describer narrates events; lamps on a tunnel gantry became "emergency lights", topping searches for "emergency vehicle".
- What the product must do: Descriptions state only what the frames show, and shots with nothing to describe get fixed labels such as newsreader, title card, black frame or colour bars.
- Kind: 1b
- Tool: Claude as the clip describer
- From: M05-007

### BRO-S02: Describing cost came from images and output, not the large fixed prompt.
- What was going on: Spend was output 56%, frame images 38%, the cached fixed prompt 6%; the longest 9% of videos made 36% of all calls.
- What the product must do: Frames sent per video are capped and spread across the whole clip, so a 1.8-hour clip costs a bounded number of calls.
- Kind: 1b
- Tool: Anthropic API pricing (cache reads billed at 0.1x)
- From: M05-013

### BRO-S03: Fixed instructions after the images never hit the cache, and answers were cut off.
- What was going on: Instructions after images missed the prompt cache, an output limit below a third of past answers truncated them (two paid calls, then failure), and conversations kept every earlier photo.
- What the product must do: Repeated fixed text is cached, no answer is cut off by the output limit, and a long session's input does not grow with every earlier image.
- Kind: 1b
- Tool: Anthropic Messages API (prompt caching, output token limit, Batch API at half price)
- State: still open
- From: H08-076

### BRO-S04: One model rejected "thinking disabled" and failed every clip.
- What was going on: The newest model always thinks and rejects an explicit "off", while omitting the setting on other models turns on billed thinking.
- What the product must do: The thinking setting is chosen per model, so no request is rejected and no unrequested thinking is billed.
- Kind: 1b
- Tool: Anthropic Messages API, Claude Fable 5 (thinking omitted or adaptive, never explicitly disabled)
- From: H03-040, L01-077

### BRO-S05: The assistant's command line reported failures on normal output and exited successfully.
- What was going on: Its errors appear on standard output rather than the error stream, and the exit code can still be zero.
- What the product must do: Each assistant call is judged by the content it returned, never by its exit code alone.
- Kind: 1b
- Tool: Claude Code CLI
- From: M05-011

### BRO-S06: An exhausted API key silently overrode the signed-in subscription.
- What was going on: Wherever the key variable is set, the command line uses it instead of the signed-in account, without saying so.
- What the product must do: Each assistant call uses the account the admin chose and records which account it used.
- Kind: 1b
- Tool: Claude Code CLI (ANTHROPIC_API_KEY overrides login)
- From: M05-012

### BRO-S07: The largest local vision model needed about 18 minutes per clip on a laptop.
- What was going on: On an Apple M4 laptop the 30-billion-parameter model was forecast at 6 hours for 20 clips; the owner: "it's a disaster then".
- What the product must do: Every describing tier offered finishes a 20-clip batch in under an hour on the hardware its tooltip names.
- Kind: 1b
- Tool: Qwen3-VL 30B-class local vision model on Apple silicon
- From: P06-014

### BRO-S08: Full-HD stills cost twice the image budget of the local vision model.
- What was going on: A 1080p frame costs about 2,040 image tokens against 1,024 at 960 wide, so an 8 or 9 frame window overflows the 16,384-token slot and the clip fails.
- What the product must do: Every b-roll clip from a 1080p proxy is described without failing on input size.
- Kind: 1b
- Tool: local Qwen3-VL vision model
- State: fixed, never shipped
- From: H08-057

### BRO-S09: Descriptions from separate frames beat a mosaic; model size barely mattered.
- What was going on: In a 100-clip owner-judged test, every local model size beat the hosted model's mosaic-based index; separate frames and a compact constrained answer were the lever.
- What the product must do: Clip descriptions are written from several separate frames, and the describing method is chosen by a human judging the studio's own footage.
- Kind: 1b
- Tool: Qwen3-VL (local), Claude Haiku (hosted)
- From: M01-007

### BRO-S10: Every vision model tested called a gun "a tool with a laser pointer".
- What was going on: Safety tuning in every model tried, hosted included, softened weapons into harmless objects, so a search for "gun" missed them.
- What the product must do: The comparison set includes weapons and look-alikes, known misnamings are recorded per model, and a weapons search finds such footage despite softened wording.
- Kind: 1b
- Tool: Qwen3-VL (all sizes), Claude Haiku image description
- State: still open
- From: P06-015, M01-008

### BRO-S11: A local vision model invents shot times unless pinned to real frames.
- What was going on: Model-reported shot times drift; frames labelled with timecodes, output bounded to the frames sent, and times looked up from those frames gave usable segments.
- What the product must do: Every shot segment's start and end come from frames actually sampled, and adjacent near-identical segments are merged.
- Kind: 1b
- Tool: Qwen3-VL through llama.cpp, with a GBNF grammar and timecode-labelled frames
- From: C02-008

### BRO-S12: Silent dashcam footage got an invented subtitle-credit line as its transcript.
- What was going on: The speech-to-text invents text over silence, and quality floors tuned for English reject real Chinese, which is denser.
- What the product must do: Transcripts showing repetition, credit artefacts or implausible density are discarded, with thresholds that accept normal Chinese speech.
- Kind: 1b
- Tool: Whisper speech-to-text
- From: M05-006

### BRO-S13: A 3.3 GB model download crawled at 2 MB/s on one stuck connection.
- What was going on: The model host can pin one long connection to a slow edge; fresh connections got 13 MB/s, six parallel ranges about 40 MB/s.
- What the product must do: Large downloads use parallel ranges, reconnect a range moving under 256 KiB in 20 s, resume per range, and retry from the original link.
- Kind: 1b
- Tool: Hugging Face (model download network)
- From: L01-011

### BRO-S14: Client downloads through the tunnel crawled at about 3 MB/s.
- What was going on: The tunnel's default transport gave about 3 MB/s, its alternative about 18 MB/s, while a direct address reached the line's 39 MB/s.
- What the product must do: Large client transfers get a measured direct path rather than an untested tunnel.
- Kind: 1b
- Tool: Cloudflare Tunnel (cloudflared, QUIC transport)
- From: P10-037

### BRO-S15: The public link relay strips the URL path before forwarding.
- What was going on: The relay removes its mount path when forwarding, so its target must carry the client-folder prefix itself.
- What the product must do: The public client-folder link serves its page and media under its prefix, tested from outside the studio network.
- Kind: 1b
- Tool: Tailscale Funnel
- From: M01-063

### BRO-S16: Replacing the live search database by plain copy risks corrupting it.
- What was going on: Copying over a database in write-ahead mode, or leaving old journal files beside a replaced copy, can corrupt it, and the search kept serving the old file until restarted.
- What the product must do: A new index is staged beside the live one, integrity-checked, refused on a large row shrink, swapped atomically keeping the previous copy, and reloaded by search on change.
- Kind: 1b
- Tool: SQLite (write-ahead log mode)
- From: L01-030, M01-065

## Removed

- L08-070 | old build only

